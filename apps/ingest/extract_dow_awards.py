# apps/ingest/extract_dow_awards.py
#
# LLM extraction of structured award data from DoW contract releases.
# One call per release; model determines award boundaries.
# Deterministic validators run post-extraction and flag suspicious rows.
#
# Usage:
#   python extract_dow_awards.py                   # all unextracted releases
#   python extract_dow_awards.py --release-id 28   # single release
#   python extract_dow_awards.py --reprocess        # re-parse stored responses

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

# ── Award-trigger markers ─────────────────────────────────────────────────────
# Broadened set; used for advisory award-count sanity check only.

AWARD_TRIGGER_RE = re.compile(
    r'\b(?:'
    r'(?:was|is|has been|have been|are)\s+awarded'
    r'|awarded\s+an?'
    r'|will\s+compete\s+for\s+each\s+order'
    r'|modification\s+to'
    r'|task\s+order'
    r'|delivery\s+order'
    r')\b',
    re.IGNORECASE,
)

# ── Enum sets ─────────────────────────────────────────────────────────────────

_AMOUNT_KINDS = {
    'individual_award_value', 'combined_award_value', 'maximum_ceiling',
    'modification_delta', 'cumulative_contract_value',
    'potential_value_if_options_exercised', 'initial_obligation',
    'minimum_guarantee', 'other',
}
_AMOUNT_SCOPES    = {'individual_awardee', 'combined_awardees', 'unspecified'}
_ACTION_TYPES     = {'award', 'modification', 'option', 'definitization', 'other', 'unknown'}
_INSTRUMENT_TYPES = {'contract', 'IDIQ', 'delivery_order', 'task_order', 'BPA', 'BOA', 'other', 'unknown'}
_FUNDING_STATUSES = {'amount_stated', 'none_obligated', 'not_stated'}

# ── State / territory codes and names ─────────────────────────────────────────

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

# ── Text normalization ────────────────────────────────────────────────────────

def _normalize_for_grounding(text: str) -> str:
    """Normalize text before grounding comparisons.

    Unifies Unicode dashes, smart quotes, and non-breaking spaces so that
    typography artifacts in HTML-sourced text don't cause false ungrounded flags.
    """
    if not text:
        return ''
    text = re.sub(r'[–—‐]', '-', text)   # en-dash, em-dash, hyphen
    text = text.replace('‘', "'").replace('’', "'")
    text = text.replace('“', '"').replace('”', '"')
    text = text.replace(' ', ' ')                   # non-breaking space
    text = re.sub(r'\s+', ' ', text)
    return text


def _normalize_name(raw: str | None) -> str | None:
    """Casefold + strip punctuation + normalize whitespace for entity matching."""
    if not raw:
        return None
    s = _normalize_for_grounding(raw).casefold()
    s = re.sub(r"[^\w\s\-]", '', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


# ── Amount parsing ────────────────────────────────────────────────────────────

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


# ── Date parsing ──────────────────────────────────────────────────────────────

def _parse_date(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except (ValueError, TypeError):
        return None


# ── Validators ────────────────────────────────────────────────────────────────

def _validate(award, source_text: str, trigger_count: int, award_total: int) -> dict:
    """Run all validators; set award.flags in-place; return flags dict.

    Every failure adds an entry to flags. Rows are never discarded.
    """
    flags: dict[str, str] = {}
    norm_src = _normalize_for_grounding(source_text)

    # ── 1. Literal grounding (normalize both sides before comparison) ──────────

    for p in (award.piids or []):
        if p.get('value') and _normalize_for_grounding(p['value']) not in norm_src:
            flags['ungrounded_piid'] = f"PIID '{p['value']}' not found in (normalized) source text"
        if p.get('excerpt') and _normalize_for_grounding(p['excerpt']) not in norm_src:
            flags['ungrounded_piid_excerpt'] = "PIID excerpt not found in (normalized) source text"

    for a in (award.amounts or []):
        if a.get('raw') and _normalize_for_grounding(a['raw']) not in norm_src:
            flags['ungrounded_amount'] = f"Amount '{a['raw']}' not found in (normalized) source text"
        if a.get('excerpt') and _normalize_for_grounding(a['excerpt']) not in norm_src:
            flags['ungrounded_amount_excerpt'] = "Amount excerpt not found in (normalized) source text"

    for a in (award.awardees or []):
        if a.get('name_raw') and _normalize_for_grounding(a['name_raw']) not in norm_src:
            flags['ungrounded_awardee_name'] = f"Awardee name '{a['name_raw']}' not found in source"

    if award.completion_date_raw:
        if _normalize_for_grounding(award.completion_date_raw) not in norm_src:
            flags['ungrounded_completion_date_raw'] = (
                f"completion_date_raw '{award.completion_date_raw}' not found in source"
            )

    if award.purpose_excerpt:
        if _normalize_for_grounding(award.purpose_excerpt) not in norm_src:
            flags['ungrounded_purpose_excerpt'] = "purpose_excerpt not found in (normalized) source text"

    if award.source_excerpt:
        if _normalize_for_grounding(award.source_excerpt) not in norm_src:
            flags['ungrounded_source_excerpt'] = "source_excerpt not found in (normalized) source text"

    fa = award.funding_at_award or {}
    if fa.get('status') != 'not_stated' and fa.get('excerpt'):
        if _normalize_for_grounding(fa['excerpt']) not in norm_src:
            flags['ungrounded_funding_excerpt'] = "funding_at_award.excerpt not found in (normalized) source text"

    # ── 2. Date consistency ───────────────────────────────────────────────────

    if award.completion_date_raw:
        raw_lower = award.completion_date_raw.lower()
        is_fiscal = 'fiscal' in raw_lower or 'fy' in raw_lower
        if is_fiscal and award.completion_date is not None:
            flags['date_inconsistent'] = (
                "completion_date must be null when completion_date_raw is a fiscal year"
            )

    # ── 3. Enum validation (flag, never reject) ───────────────────────────────

    for i, a in enumerate(award.amounts or []):
        kind  = a.get('kind')
        scope = a.get('scope')
        if kind  and kind  not in _AMOUNT_KINDS:
            flags['invalid_enum_amount_kind']  = f"amount[{i}].kind '{kind}' not in allowed set"
        if scope and scope not in _AMOUNT_SCOPES:
            flags['invalid_enum_amount_scope'] = f"amount[{i}].scope '{scope}' not in allowed set"

    if award.action_type and award.action_type not in _ACTION_TYPES:
        flags['invalid_enum_action_type'] = f"action_type '{award.action_type}' not in allowed set"

    if award.instrument_type and award.instrument_type not in _INSTRUMENT_TYPES:
        flags['invalid_enum_instrument_type'] = f"instrument_type '{award.instrument_type}' not in allowed set"

    status = fa.get('status')
    if status and status not in _FUNDING_STATUSES:
        flags['invalid_enum_funding_status'] = f"funding_at_award.status '{status}' not in allowed set"

    # ── 4. Conditional math (obligation ≤ ceiling, only when scopes compatible) ─

    amounts = award.amounts or []
    obligation = next((a for a in amounts if a.get('kind') == 'initial_obligation'),  None)
    ceiling    = next((a for a in amounts if a.get('kind') == 'maximum_ceiling'),     None)
    if obligation and ceiling:
        ob_scope   = obligation.get('scope', 'unspecified')
        ceil_scope = ceiling.get('scope',    'unspecified')
        compatible = (ob_scope == ceil_scope or
                      ob_scope == 'unspecified' or ceil_scope == 'unspecified')
        if compatible:
            ob_cents   = obligation.get('cents')
            ceil_cents = ceiling.get('cents')
            if ob_cents is not None and ceil_cents is not None and ob_cents > ceil_cents:
                flags['obligation_exceeds_ceiling'] = (
                    f"initial_obligation {ob_cents} > maximum_ceiling {ceil_cents}"
                )

    # ── 5. Funding consistency ────────────────────────────────────────────────

    has_obligation = any(a.get('kind') == 'initial_obligation' for a in amounts)
    if status == 'amount_stated' and not has_obligation:
        flags['funding_status_mismatch'] = (
            "funding_at_award.status=amount_stated but no initial_obligation amount found"
        )
    elif status == 'none_obligated' and has_obligation:
        flags['funding_status_mismatch'] = (
            "funding_at_award.status=none_obligated but initial_obligation amount present"
        )

    # ── 6. State / country ────────────────────────────────────────────────────

    for a in (award.awardees or []):
        state   = a.get('state_raw')
        country = a.get('country_raw')
        if state and not country:
            if (state.upper() not in _VALID_STATE_CODES and
                    state.lower() not in _VALID_STATE_NAMES):
                flags['state_unrecognized'] = f"unrecognized state: '{state}'"

    # ── 7. Award-count sanity (advisory — never blocks or discards) ───────────

    if award_total < trigger_count:
        flags['award_count_low'] = (
            f"expected ~{trigger_count} award markers, got {award_total} awards"
        )

    award.flags = flags if flags else None
    return flags


# ── Prompt ────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are extracting structured data from a U.S. Department of War daily contract
announcement. The input is the full text of one day's release, which contains
multiple distinct award announcements.

Return one record for each distinct source award group.

A source award group is one coherent contract action described in one paragraph
or a connected set of paragraphs. It may include one awardee or multiple
awardees. Do not split a jointly described award group into individual awards
unless the source explicitly assigns separate values or separate actions.

Rules:
- Extract ALL distinct award groups in the release. Do not silently merge,
  omit, or invent awards.
- Extract ONLY facts explicitly stated in the source text.
- Return null for absent fields. NEVER infer or guess.
- Preserve raw source wording for names, amounts, PIIDs, dates, contract
  language, and source excerpts.
- Every excerpt field must be copied VERBATIM, character-for-character, from the
  source text. Never paraphrase, summarize, or reconstruct an excerpt.
- Do not infer recipient-level allocation from a combined award amount.
- Do not infer a parent vehicle, referenced IDV, program ceiling, task-order
  relationship, or future award potential unless explicitly stated.
- Every PIID and every dollar amount must include an exact source excerpt
  containing that value.
- Dollar values must be returned exactly as printed, including "$" and commas.
- PIIDs must be returned exactly as printed.
- Awardee names should be returned exactly as printed. Do not normalize names.
- For completion dates:
  - preserve the source phrase in completion_date_raw
  - return completion_date as YYYY-MM-DD
  - when only month + year are stated, use the first day of that month
  - when only a calendar year is stated, use January 1
  - IMPORTANT: if the date is a FISCAL year (e.g. "fiscal 2029", "FY2029"),
    set completion_date to null and preserve the phrase in completion_date_raw.
    Do NOT convert a fiscal year to a calendar date. Fiscal years do not map
    to calendar dates.
- purpose must be factual and source-grounded: describe what work, service,
  product, or system is being procured. Do not explain why it matters.
- purpose_excerpt must be a verbatim span supporting the purpose summary.
- program_hint may name a program, platform, system, or effort only when
  explicitly named in the source text.
- Do not treat a cumulative contract value, options value, ceiling, modification
  amount, or minimum guarantee as an initial award amount unless the source says so.

Amounts:
- Extract every materially distinct dollar amount associated with an award group.
- Classify each amount using exactly one of:
  "individual_award_value"
  "combined_award_value"
  "maximum_ceiling"
  "modification_delta"
  "cumulative_contract_value"
  "potential_value_if_options_exercised"
  "initial_obligation"
  "minimum_guarantee"
  "other"
- Do not use an amount type when the text does not support it.
- If the amount's meaning is unclear, use "other".
- Record whether an amount applies to one awardee, all listed awardees jointly,
  or an unspecified scope.

Action and instrument:
- action_type must be one of:
  "award", "modification", "option", "definitization", "other", "unknown"
- instrument_type must be one of:
  "contract", "IDIQ", "delivery_order", "task_order", "BPA", "BOA",
  "other", "unknown"
- pricing_type_raw is the COST/PRICING ARRANGEMENT ONLY (e.g. "firm-fixed-price",
  "cost-plus-fixed-fee", "cost-plus-incentive-fee"). Do NOT put the instrument
  or delivery vehicle (IDIQ, delivery order, task order) in pricing_type_raw —
  those belong in instrument_type. Preserve exact source wording.

Funding:
- funding_at_award.status must be one of:
  "amount_stated", "none_obligated", "not_stated"
- Use "none_obligated" only when the source explicitly states that no funds
  are obligated at time of award.
- When an initial obligation amount is stated, include it in amounts with kind
  "initial_obligation" and set funding_at_award.status to "amount_stated".

Location:
- For U.S. awardees: city_raw and state_raw as printed; country_raw null.
- For foreign awardees: populate country_raw; state_raw may be null.

source_excerpt: the coherent source text (the paragraph or connected paragraphs)
that this award group was drawn from, for human review. Include the full relevant
text, not a minimal fragment.

The release contains approximately {n} award-trigger phrases. Extract all award groups.

Return a JSON object with exactly one key "awards":
{
  "awards": [
    {
      "awardees": [
        {
          "name_raw": "string",
          "city_raw": "string or null",
          "state_raw": "string or null",
          "country_raw": "string or null"
        }
      ],
      "piids": [{"value": "string", "excerpt": "string"}],
      "amounts": [
        {
          "raw": "string",
          "kind": "string (one of the amount types above)",
          "scope": "individual_awardee | combined_awardees | unspecified",
          "excerpt": "string"
        }
      ],
      "funding_at_award": {
        "status": "amount_stated | none_obligated | not_stated",
        "excerpt": "string or null"
      },
      "action_type": "string",
      "instrument_type": "string",
      "pricing_type_raw": "string or null",
      "completion_date_raw": "string or null",
      "completion_date": "YYYY-MM-DD or null",
      "contracting_activity": "string or null",
      "program_hint": "string or null",
      "purpose": "string or null",
      "purpose_excerpt": "string or null",
      "source_excerpt": "string"
    }
  ]
}
"""


# ── Core extraction ───────────────────────────────────────────────────────────

async def _write_awards(session, release: DowContractRelease, awards_raw: list, source_text: str) -> int:
    """Parse raw award dicts, write DowAward rows, run validators. Returns count inserted."""
    trigger_count = len(AWARD_TRIGGER_RE.findall(source_text))
    award_total   = len(awards_raw)

    existing = (await session.execute(
        select(DowAward).where(DowAward.release_id == release.id)
    )).scalars().all()
    for old in existing:
        await session.delete(old)
    await session.flush()

    for idx, a in enumerate(awards_raw):
        # Enrich awardees with name_normalized
        awardees = a.get('awardees') or []
        for awardee in awardees:
            awardee['name_normalized'] = _normalize_name(awardee.get('name_raw'))

        # Enrich amounts with cents
        amounts = a.get('amounts') or []
        for amt in amounts:
            amt['cents'] = _parse_cents(amt.get('raw'))

        award = DowAward(
            release_id           = release.id,
            award_index          = idx,
            awardees             = awardees or None,
            piids                = a.get('piids') or None,
            amounts              = amounts or None,
            funding_at_award     = a.get('funding_at_award') or None,
            action_type          = a.get('action_type'),
            instrument_type      = a.get('instrument_type'),
            pricing_type_raw     = a.get('pricing_type_raw'),
            completion_date_raw  = a.get('completion_date_raw'),
            completion_date      = _parse_date(a.get('completion_date')),
            contracting_activity = a.get('contracting_activity'),
            program_hint         = a.get('program_hint'),
            purpose              = a.get('purpose'),
            purpose_excerpt      = a.get('purpose_excerpt'),
            source_excerpt       = a.get('source_excerpt'),
            llm_status           = 'ok' if (awardees and amounts) else 'partial',
        )
        session.add(award)
        await session.flush()

        _validate(award, source_text, trigger_count, award_total)

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
                {'role': 'user',   'content': source_text},
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
            'prompt_tokens':     response.usage.prompt_tokens,
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
    """Re-parse stored llm_raw_response and re-run validators. No API call.

    Only meaningful if the stored response was generated with the current prompt schema.
    """
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
            stmt = select(DowContractRelease).where(DowContractRelease.llm_raw_response.isnot(None))
            if release_id is not None:
                stmt = stmt.where(DowContractRelease.id == release_id)
            releases = (await session.execute(stmt)).scalars().all()
            logger.info("Reprocessing %d releases from stored responses", len(releases))
            total = sum([await reprocess_release(session, r) for r in releases])
            logger.info("Done. Reprocessed %d awards total.", total)
            return

        client = AsyncOpenAI()
        total_input = total_output = 0

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
                cost = (total_input / 1_000_000 * COST_INPUT_PER_M +
                        total_output / 1_000_000 * COST_OUTPUT_PER_M)
                logger.info(
                    "[%d/%d] awards=%d | tokens in=%d out=%d | cost=$%.4f",
                    i, total_releases, total_awards, total_input, total_output, cost,
                )

        cost = (total_input / 1_000_000 * COST_INPUT_PER_M +
                total_output / 1_000_000 * COST_OUTPUT_PER_M)
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
