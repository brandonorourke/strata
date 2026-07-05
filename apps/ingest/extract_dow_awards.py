# apps/ingest/extract_dow_awards.py
#
# LLM extraction of structured award data from DoW contract releases.
# One call per release; the model determines award boundaries.
# Deterministic validators run post-extraction and flag suspicious rows.
#
# Usage:
#   python extract_dow_awards.py               # all unextracted releases
#   python extract_dow_awards.py --release-id 28   # single release

import argparse
import asyncio
import json
import logging
import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from openai import AsyncOpenAI
from sqlalchemy import select

from strata_core.db import AsyncSessionLocal
from strata_core.models import DowContractRelease, DowAward

from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

MODEL = "gpt-4o-mini"
COST_INPUT_PER_M  = 0.15
COST_OUTPUT_PER_M = 0.60

AWARD_TRIGGER_RE = re.compile(r'\b(?:was|is|has been|have been) awarded\b', re.IGNORECASE)

# ── Normalization ─────────────────────────────────────────────────────────────

_AMOUNT_RE = re.compile(r'\$([\d,]+(?:\.\d+)?)\s*(million|billion)?', re.IGNORECASE)

def _parse_cents(raw: str | None) -> int | None:
    if not raw:
        return None
    m = _AMOUNT_RE.search(raw)
    if not m:
        return None
    digits = m.group(1).replace(',', '')
    suffix = (m.group(2) or '').lower()
    try:
        val = Decimal(digits)
    except InvalidOperation:
        return None
    if suffix == 'million':
        val *= 1_000_000
    elif suffix == 'billion':
        val *= 1_000_000_000
    cents = int(val * 100)
    return cents if cents > 0 else None


def _parse_date(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except (ValueError, TypeError):
        return None


# ── Validators ────────────────────────────────────────────────────────────────

_VALID_STATE_CODES = {
    'AL','AK','AZ','AR','CA','CO','CT','DE','FL','GA','HI','ID','IL','IN','IA',
    'KS','KY','LA','ME','MD','MA','MI','MN','MS','MO','MT','NE','NV','NH','NJ',
    'NM','NY','NC','ND','OH','OK','OR','PA','RI','SC','SD','TN','TX','UT','VT',
    'VA','WA','WV','WI','WY','DC','D.C.','PR','GU','VI','AS','MP',
}
_VALID_STATE_NAMES = {
    'alabama','alaska','arizona','arkansas','california','colorado','connecticut',
    'delaware','florida','georgia','hawaii','idaho','illinois','indiana','iowa',
    'kansas','kentucky','louisiana','maine','maryland','massachusetts','michigan',
    'minnesota','mississippi','missouri','montana','nebraska','nevada',
    'new hampshire','new jersey','new mexico','new york','north carolina',
    'north dakota','ohio','oklahoma','oregon','pennsylvania','rhode island',
    'south carolina','south dakota','tennessee','texas','utah','vermont',
    'virginia','washington','west virginia','wisconsin','wyoming',
    'district of columbia','puerto rico','guam',
}

# Modern (no hyphen): ≥6 alphanum chars starting with a letter
_PIID_MODERN  = re.compile(r'^[A-Z][A-Z0-9]{5,19}$')
# Hyphenated (older): letter, alphanums + hyphens, ≥8 chars, must contain digit
_PIID_HYPHEN  = re.compile(r'^[A-Z][A-Z0-9-]{7,25}$')
_HAS_DIGIT    = re.compile(r'\d')


def _piid_valid(value: str) -> bool:
    if _PIID_MODERN.match(value) and _HAS_DIGIT.search(value):
        return True
    if _PIID_HYPHEN.match(value) and _HAS_DIGIT.search(value):
        return True
    return False


def _value_in_source(value_raw: str | None, source_text: str) -> bool:
    """Check if the dollar amount or PIID value appears in source_text."""
    if not value_raw or not source_text:
        return False
    # For amounts: strip $ and commas, search for the digit string
    digits_only = re.sub(r'[$,]', '', value_raw).strip()
    # Also try with commas (as printed in the source)
    with_commas = re.sub(r'(\d)(?=(\d{3})+(?!\d))', r'\1,', digits_only)
    return digits_only in source_text or with_commas in source_text


def _validate(award: DowAward, source_text: str, trigger_count: int, award_total: int) -> dict:
    """Run all validators; return {field: reason} for each failure."""
    flags: dict[str, str] = {}

    # 1. Amount format
    ceiling_ok   = award.ceiling_raw  is None or award.ceiling_cents  is not None
    obligated_ok = award.obligated_raw is None or award.obligated_cents is not None
    if not ceiling_ok:
        flags['ceiling_format'] = f"could not parse '{award.ceiling_raw}' to cents"
    if not obligated_ok:
        flags['obligated_format'] = f"could not parse '{award.obligated_raw}' to cents"
    award.val_amount_format = len(flags) == 0 or not any(
        k in flags for k in ('ceiling_format', 'obligated_format')
    )
    # Recompute cleanly
    award.val_amount_format = ceiling_ok and obligated_ok

    # 2. Obligated ≤ ceiling
    if award.obligated_cents is not None and award.ceiling_cents is not None:
        if award.obligated_cents > award.ceiling_cents:
            flags['obligated_lte_ceiling'] = (
                f"obligated {award.obligated_cents} > ceiling {award.ceiling_cents} "
                f"(likely field-swap or hallucination)"
            )
        award.val_obligated_lte_ceiling = 'obligated_lte_ceiling' not in flags
    # else: None (not applicable)

    # 3. PIID grammar
    if award.piids:
        bad_piids = [p['value'] for p in award.piids if not _piid_valid(p.get('value', ''))]
        if bad_piids:
            flags['piid_grammar'] = f"unrecognized PIID format: {bad_piids}"
        award.val_piid_grammar = not bad_piids
    # else: None

    # 4. Value grounding
    if award.ceiling_raw is not None:
        grounded = _value_in_source(award.ceiling_raw, source_text)
        if not grounded:
            flags['ceiling_grounded'] = f"'{award.ceiling_raw}' not found in source text"
        award.val_ceiling_grounded = grounded

    if award.obligated_raw is not None:
        grounded = _value_in_source(award.obligated_raw, source_text)
        if not grounded:
            flags['obligated_grounded'] = f"'{award.obligated_raw}' not found in source text"
        award.val_obligated_grounded = grounded

    if award.piids:
        ungrounded = [
            p['value'] for p in award.piids
            if p.get('value') and p['value'] not in source_text
        ]
        if ungrounded:
            flags['piid_grounded'] = f"PIIDs not found in source: {ungrounded}"
        award.val_piid_grounded = not ungrounded

    # 5. Date plausibility
    if award.completion_date is not None:
        plausible = date(2000, 1, 1) <= award.completion_date <= date(2060, 1, 1)
        if not plausible:
            flags['date_plausible'] = f"completion_date {award.completion_date} out of plausible range"
        award.val_date_plausible = plausible

    # 6. State codes — accept 2-letter codes AND known full state names
    if award.awardees:
        bad_states = [
            a.get('state') for a in award.awardees
            if a.get('state')
            and a['state'].upper() not in _VALID_STATE_CODES
            and a['state'].lower() not in _VALID_STATE_NAMES
        ]
        if bad_states:
            flags['state_codes'] = f"unrecognized state(s): {bad_states}"
        award.val_state_codes = not bad_states

    # 7. Award-count sanity (release-level, same value on all awards for this release)
    if award_total < trigger_count:
        flags['award_count_sane'] = (
            f"expected ~{trigger_count} awards (trigger count), got {award_total}"
        )
    award.val_award_count_sane = award_total >= trigger_count

    return flags


# ── Prompt ────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are extracting structured data from a U.S. Department of War daily contract
announcement. The input is the full text of one day's release, which contains
multiple award announcements.

Rules:
- Extract ALL awards from the text. The text contains approximately {n} award
  announcements — do not silently merge or drop any.
- For each award, extract ONLY what is explicitly stated.
- Return null for absent fields. NEVER infer or guess.
- NEVER infer obligated_raw from ceiling_raw or vice versa. They are different numbers.
- Return dollar amounts as the exact digit-string as printed (e.g. "$150,000,000").
- Return PIIDs (contract numbers) as printed (e.g. "FA880726FB004").
- For completion_date: return as "YYYY-MM-DD". Use first day of month when only
  month+year are given (e.g. "September 2026" → "2026-09-01").
- awardee state: 2-letter code if abbreviated, full name if spelled out.
- For amounts and PIIDs, return the verbatim span from the source text as "excerpt".
- "purpose": 1-2 sentences describing what the contract covers — what service,
  product, or work is being procured, and for what system or program if named.
  Use the source text's own words. Return null only if truly absent.

Return a JSON object with exactly one key "awards" containing a list:
{
  "awards": [
    {
      "awardees": [{"name": str, "city": str|null, "state": str|null}],
      "piids": [{"value": str, "excerpt": str}],
      "ceiling_raw": str|null,
      "ceiling_excerpt": str|null,
      "obligated_raw": str|null,
      "obligated_excerpt": str|null,
      "contract_type": str|null,
      "completion_date": str|null,
      "contracting_activity": str|null,
      "program_hint": str|null,
      "purpose": str|null
    }
  ]
}
"""


# ── Core extraction ───────────────────────────────────────────────────────────

async def _write_awards(session, release: DowContractRelease, awards_raw: list, source_text: str) -> int:
    """Parse a list of raw award dicts, write DowAward rows, run validators. Returns count inserted."""
    trigger_count = len(AWARD_TRIGGER_RE.findall(source_text))
    award_total = len(awards_raw)

    # Delete any existing awards for this release before rewriting
    existing = (await session.execute(
        select(DowAward).where(DowAward.release_id == release.id)
    )).scalars().all()
    for old in existing:
        await session.delete(old)
    await session.flush()

    for idx, a in enumerate(awards_raw):
        ceiling_raw   = a.get('ceiling_raw')
        obligated_raw = a.get('obligated_raw')
        piids_raw     = a.get('piids') or []
        completion_raw = a.get('completion_date')

        award = DowAward(
            release_id           = release.id,
            award_index          = idx,
            awardees             = a.get('awardees') or None,
            piids                = piids_raw or None,
            ceiling_cents        = _parse_cents(ceiling_raw),
            ceiling_raw          = ceiling_raw,
            ceiling_excerpt      = a.get('ceiling_excerpt'),
            obligated_cents      = _parse_cents(obligated_raw),
            obligated_raw        = obligated_raw,
            obligated_excerpt    = a.get('obligated_excerpt'),
            contract_type        = a.get('contract_type'),
            completion_date      = _parse_date(completion_raw),
            contracting_activity = a.get('contracting_activity'),
            program_hint         = a.get('program_hint'),
            purpose              = a.get('purpose'),
            llm_status           = 'ok' if (a.get('awardees') and ceiling_raw) else 'partial',
        )
        session.add(award)
        await session.flush()

        flags = _validate(award, source_text, trigger_count, award_total)
        if flags:
            award.val_flag_reasons = flags

    await session.commit()
    return award_total


async def extract_release(client: AsyncOpenAI, session, release: DowContractRelease) -> int:
    source_text = release.raw_text or ''
    if not source_text.strip():
        logger.warning("Release %d has no raw_text", release.id)
        return 0

    trigger_count = len(AWARD_TRIGGER_RE.findall(source_text))
    prompt = SYSTEM_PROMPT.replace('{n}', str(trigger_count))

    try:
        response = await client.chat.completions.create(
            model=MODEL,
            messages=[
                {'role': 'system', 'content': prompt},
                {'role': 'user', 'content': source_text},
            ],
            response_format={'type': 'json_object'},
            temperature=0,
        )
    except Exception as e:
        logger.error("LLM call failed for release %d: %s", release.id, e)
        return 0

    release.llm_raw_response = {
        'model': response.model,
        'usage': {
            'prompt_tokens': response.usage.prompt_tokens,
            'completion_tokens': response.usage.completion_tokens,
        },
        'content': response.choices[0].message.content,
    }
    release.llm_extracted_at = datetime.now(timezone.utc)

    try:
        awards_raw = json.loads(response.choices[0].message.content).get('awards') or []
    except (json.JSONDecodeError, TypeError):
        logger.error("Could not parse LLM response for release %d", release.id)
        await session.commit()
        return 0

    return await _write_awards(session, release, awards_raw, source_text)


async def reprocess_release(session, release: DowContractRelease) -> int:
    """Re-parse stored llm_raw_response and re-run validators. No API call."""
    if not release.llm_raw_response:
        logger.warning("Release %d has no stored llm_raw_response — skipping", release.id)
        return 0

    try:
        awards_raw = json.loads(release.llm_raw_response['content']).get('awards') or []
    except (json.JSONDecodeError, TypeError, KeyError) as e:
        logger.error("Could not parse stored response for release %d: %s", release.id, e)
        return 0

    source_text = release.raw_text or ''
    n = await _write_awards(session, release, awards_raw, source_text)
    logger.info("Reprocessed release %d (%s): %d awards", release.id, release.release_date, n)
    return n


# ── Entry point ───────────────────────────────────────────────────────────────

async def run(release_id: int | None = None, reprocess: bool = False) -> None:
    async with AsyncSessionLocal() as session:
        if reprocess:
            # Re-parse stored responses, no API calls
            stmt = select(DowContractRelease).where(DowContractRelease.llm_raw_response.isnot(None))
            if release_id is not None:
                stmt = stmt.where(DowContractRelease.id == release_id)
            releases = (await session.execute(stmt)).scalars().all()
            logger.info("Reprocessing %d releases from stored responses", len(releases))
            total = sum([await reprocess_release(session, r) for r in releases])
            logger.info("Done. Reprocessed %d awards total.", total)
            return

        client = AsyncOpenAI()
        total_input = 0
        total_output = 0

        if release_id is not None:
            releases = (await session.execute(
                select(DowContractRelease).where(DowContractRelease.id == release_id)
            )).scalars().all()
        else:
            releases = (await session.execute(
                select(DowContractRelease)
                .where(DowContractRelease.raw_text.isnot(None))
                .where(DowContractRelease.llm_extracted_at.is_(None))
                .order_by(DowContractRelease.release_date.asc().nullslast())
            )).scalars().all()

        total_releases = len(releases)
        logger.info("Releases to extract: %d", total_releases)
        total_awards = 0

        for i, release in enumerate(releases, 1):
            n = await extract_release(client, session, release)
            total_awards += n

            usage = (release.llm_raw_response or {}).get('usage', {})
            total_input  += usage.get('prompt_tokens', 0)
            total_output += usage.get('completion_tokens', 0)

            if i % 50 == 0 or i == total_releases:
                cost = (
                    total_input  / 1_000_000 * COST_INPUT_PER_M +
                    total_output / 1_000_000 * COST_OUTPUT_PER_M
                )
                logger.info(
                    "[%d/%d] awards=%d | tokens in=%d out=%d | cost=$%.4f",
                    i, total_releases, total_awards, total_input, total_output, cost,
                )

        cost = (
            total_input  / 1_000_000 * COST_INPUT_PER_M +
            total_output / 1_000_000 * COST_OUTPUT_PER_M
        )
        logger.info(
            "Done. releases=%d awards=%d | input_tokens=%d output_tokens=%d | cost=$%.4f",
            total_releases, total_awards, total_input, total_output, cost,
        )


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--release-id', type=int, default=None)
    parser.add_argument('--reprocess', action='store_true',
                        help='Re-parse stored llm_raw_response and re-run validators (no API call)')
    args = parser.parse_args()
    asyncio.run(run(release_id=args.release_id, reprocess=args.reprocess))
