# apps/ingest/extract_dow_awards_v2.py
#
# Combined regex + LLM extraction for DoW contract releases.
#
# Architecture (per spec):
#   Regex  → positional/rigid fields: PIIDs, city/state, amounts, contracting_activity,
#             completion_date_raw. Parse-status per awardee chunk (full/partial/failed).
#   LLM    → semantic fields: company_name_raw, awardee-PIID pairing, purpose,
#             program_hint, action_type. One call per release.
#   Merge  → join on PIID; cross-check regex vs LLM pairings → pairing_confidence.
#
# Unit: one dow_awards row per coherent contract action (award group).
# Multi-awardee announcements: one row, multiple entries in awardees JSONB.
# Each awardee entry: {name_raw, city_raw, state_raw, piid, parse_status, pairing_confidence}
#
# Usage:
#   python extract_dow_awards_v2.py                    # all unextracted releases
#   python extract_dow_awards_v2.py --release-id 1     # single release
#   python extract_dow_awards_v2.py --limit 5          # newest N unextracted
#   python extract_dow_awards_v2.py --reprocess        # overwrite existing rows
#   python extract_dow_awards_v2.py --dry-run          # print, no DB writes

import argparse
import asyncio
import html
import json
import logging
import re
from datetime import date, datetime, timezone

from openai import AsyncOpenAI
from sqlalchemy import select, delete

from strata_core.db import AsyncSessionLocal
from strata_core.models import DowContractRelease, DowAward

from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

LLM_MODEL = "gpt-4o-mini"

# ── State lookup sets ─────────────────────────────────────────────────────────

_STATE_NAMES = {
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
_STATE_CODES = {
    'AL','AK','AZ','AR','CA','CO','CT','DE','FL','GA','HI','ID','IL','IN','IA',
    'KS','KY','LA','ME','MD','MA','MI','MN','MS','MO','MT','NE','NV','NH','NJ',
    'NM','NY','NC','ND','OH','OK','OR','PA','RI','SC','SD','TN','TX','UT','VT',
    'VA','WA','WV','WI','WY','DC','PR','GU','VI','AS','MP',
}

# ── Regexes ───────────────────────────────────────────────────────────────────

# PIID in parens — handles (PIID) and (PIID, $amount)
_PIID_PAREN_RE = re.compile(r'\(([A-Z][A-Z0-9\-]{7,19})(?:,\s*[^)]+)?\)')
# Bare dashed PIID — unambiguous without parens (for "to contract PIID" references)
_PIID_BARE_RE  = re.compile(r'\b([A-Z]{1,2}[0-9A-Z]{3,6}-[0-9]{2}-[A-Z]-[A-Z0-9]{2,8})\b')

# Body extraction anchors
_CONTRACTS_DATE_RE  = re.compile(r'Contracts for \w+ \d{1,2}, \d{4}')
_SECTION_HEADER_RE  = re.compile(r'^[A-Z][A-Z &/\-\.]{3,}$', re.MULTILINE)

# Structural patterns
_AMOUNT_RE          = re.compile(r'\$([\d,]+(?:\.\d+)?)\s*(million|billion)?', re.IGNORECASE)
_COMPLETION_DATE_RE = re.compile(
    r'(?:estimated\s+)?(?:completion|completed|performance end)\s+(?:date\s+(?:is|of)\s*[:\-]?\s*|by\s+)'
    r'((?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|'
    r'Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)'
    r'[\s.,]+\d{1,2}[,\s]+\d{4}|'
    r'(?:fiscal\s+year\s+|FY\s*)\d{4})',
    re.IGNORECASE,
)
_ACTIVITY_RE        = re.compile(r'(.+?),?\s+is the contracting activity', re.IGNORECASE | re.DOTALL)
_ACTIVITY_PIID_RE   = re.compile(
    r'is the contracting activity\s*\(([A-Z][A-Z0-9\-]{7,19})(?:,\s*[^)]+)?\)',
    re.IGNORECASE,
)

# ── PIID validation ───────────────────────────────────────────────────────────

_SOLICITATION_TYPES = {'R', 'Q', 'S', 'I', 'J', 'T'}

def _piid_type_code(s: str) -> str | None:
    if '-' in s:
        parts = s.split('-')
        return parts[2].upper() if len(parts) >= 3 else None
    # Condensed: scan for 2-digit FY followed by a letter
    m = re.search(r'\d{2}([A-Z])', s[3:])
    return m.group(1) if m else None

def _is_piid(s: str) -> bool:
    if sum(c.isdigit() for c in s) < 2:
        return False
    tc = _piid_type_code(s)
    return tc not in _SOLICITATION_TYPES if tc else True

def _piid_key(s: str) -> str:
    """
    Normalized join key for matching PIIDs across regex and LLM output.

    Strips parentheses, whitespace, and dashes so that '(FA8520-26-D-B001)',
    'FA8520-26-D-B001', and 'FA852026DB001' all key identically. A trailing
    modification token (e.g. 'W58RGZ-19-C-0003 P00109') is dropped — the LLM
    sometimes appends the mod number; the contract PIID is the first token.
    """
    if not s:
        return ""
    first = s.strip().strip("()").split()[0] if s.strip().strip("()").split() else ""
    return re.sub(r'[^A-Z0-9]', '', first.upper())

# ── Body extraction ───────────────────────────────────────────────────────────

def _release_body(text: str) -> str:
    """Strip nav/share boilerplate; return from first service-branch heading."""
    date_matches = list(_CONTRACTS_DATE_RE.finditer(text))
    search_from = date_matches[-1].end() if date_matches else 0
    m = _SECTION_HEADER_RE.search(text, search_from)
    if m:
        return text[m.start():]
    m2 = re.search(r'^[A-Z][A-Z .\-]+$', text, re.MULTILINE)
    return text[m2.start():] if m2 else text

# ── City/state extraction from awardee chunk ─────────────────────────────────

def _parse_city_state(chunk: str) -> tuple[str | None, str | None, str]:
    """
    Given 'Company, Inc.,* City, State' or 'Company, City, State':
    return (city_raw, state_raw, parse_status).

    parse_status: 'full' if both extracted, 'partial' if state only, 'failed' if neither.
    """
    chunk = chunk.strip().lstrip('and ').strip()

    # Asterisk: company ends before ,* — strip asterisks from location portion
    clean = re.sub(r'\*+', '', chunk)
    if '*' in chunk:
        after_star = chunk.split('*', 1)[1].strip().lstrip(', ')
        parts = [p.strip() for p in re.sub(r'\*+', '', after_star).split(',') if p.strip()]
    else:
        parts = [p.strip() for p in clean.split(',') if p.strip()]

    if not parts:
        return None, None, 'failed'

    state_raw = None
    city_raw  = None

    # Walk backwards: find state name, code, or D.C.-style abbreviation
    for i in range(len(parts) - 1, -1, -1):
        seg = re.sub(r'\([^)]*\)', '', parts[i]).strip().rstrip('.')
        is_state = (
            seg.lower() in _STATE_NAMES
            or seg.upper() in _STATE_CODES
            or bool(re.fullmatch(r'[A-Z]\.[A-Z]\.?', seg.strip('.')))
        )
        if is_state:
            state_raw = parts[i].strip()
            if i > 0:
                city_raw = parts[i - 1].strip()
            break

    if state_raw:
        return city_raw, state_raw, 'full' if city_raw else 'partial'
    return None, None, 'failed'


# ── Regex: extract award groups from release body ────────────────────────────


def _regex_groups(body: str) -> list[dict]:
    """
    Return a list of regex-extracted award groups, one per paragraph with PIIDs.

    Each group:
    {
        "piid_chunks": [{"piid", "city_raw", "state_raw", "parse_status"}],
        "amounts":     ["$437,665,005", ...],
        "completion_date_raw": "...",
        "contracting_activity": "...",
        "source_excerpt": "...",
    }
    """
    paragraphs = [p.strip() for p in re.split(r'\n{2,}', body) if p.strip()]
    groups = []
    seen_piids: set[str] = set()

    for para in paragraphs:
        # Skip section headers
        if re.fullmatch(r'[A-Z][A-Z &/\-\.]+', para):
            continue

        piid_matches = [
            (m.group(1), m.start(), m.end())
            for m in _PIID_PAREN_RE.finditer(para)
            if _is_piid(m.group(1))
        ]

        if not piid_matches:
            # Try bare dashed PIIDs (modification "to contract PIID" references)
            bare = [
                (m.group(1), m.start(), m.end())
                for m in _PIID_BARE_RE.finditer(para)
                if _is_piid(m.group(1))
            ]
            if not bare:
                continue
            piid_matches = bare

        # De-duplicate within release
        piid_matches = [(p, s, e) for p, s, e in piid_matches if p not in seen_piids]
        if not piid_matches:
            continue
        for piid, _, _ in piid_matches:
            seen_piids.add(piid)

        # Build per-awardee chunks
        chunks = _extract_piid_chunks(para, piid_matches)

        # Amounts
        amounts = [m.group(0).strip() for m in _AMOUNT_RE.finditer(para)]

        # Completion date
        cdm = _COMPLETION_DATE_RE.search(para)
        completion_date_raw = cdm.group(1).strip() if cdm else None

        # Contracting activity (text before "is the contracting activity")
        am = _ACTIVITY_RE.search(para)
        if am:
            # Take only the last sentence fragment (activity name, not the whole para)
            activity_text = am.group(1).strip()
            # Extract the last comma-delimited meaningful segment
            last_sentence = activity_text.rsplit('\n', 1)[-1].strip()
            contracting_activity = last_sentence[-200:].lstrip(' .,').strip() if last_sentence else None
        else:
            contracting_activity = None

        groups.append({
            "piid_chunks": chunks,
            "amounts": amounts,
            "completion_date_raw": completion_date_raw,
            "contracting_activity": contracting_activity,
            "source_excerpt": html.unescape(para[:600]),
        })

    return groups


def _extract_piid_chunks(para: str, piid_matches: list[tuple]) -> list[dict]:
    """
    For each PIID in the paragraph, determine its city/state and parse_status
    by looking at the text preceding the PIID marker.
    """
    chunks = []

    # Multi-awardee: guard — if "was/is awarded" appears before first PIID, don't split
    text_before_first = para[:piid_matches[0][1]]
    is_multi = (
        len(piid_matches) >= 2
        and not re.search(r'\b(?:was|is|has been|have been)\s+awarded\b',
                          text_before_first, re.IGNORECASE)
    )

    if is_multi:
        for i, (piid, start, _end) in enumerate(piid_matches):
            if i == 0:
                chunk_start = 0
            else:
                prev_end = piid_matches[i - 1][2]
                sep_search = para[prev_end:start]
                sep_m = re.search(r'(?:;\s*|,?\s+and\s+)', sep_search)
                chunk_start = prev_end + sep_m.end() if sep_m else prev_end

            chunk = para[chunk_start:start].rstrip(', ').strip()
            city, state, status = _parse_city_state(chunk)
            chunks.append({"piid": piid, "city_raw": city, "state_raw": state, "parse_status": status})
    else:
        # Single awardee — all PIIDs from one paragraph share the same awardee context
        # (usually one PIID is the award, others are references to parent contracts)
        # Just record each PIID; city/state come from paragraph start
        city, state, status = _parse_para_location(para)
        for piid, _, _ in piid_matches:
            chunks.append({"piid": piid, "city_raw": city, "state_raw": state, "parse_status": status})

    return chunks


def _parse_para_location(para: str) -> tuple[str | None, str | None, str]:
    """Extract city/state from single-awardee paragraph start."""
    # "Company, City, State, was/is awarded..."
    m = re.match(
        r'^(?:CORRECTION|UPDATE|NOTE):\s*',
        para, re.IGNORECASE,
    )
    clean = para[m.end():] if m else para

    # Try asterisk form: "Company,* City, State,"
    m2 = re.match(r'^.+?,\*\s*([^,]+),\s*([^,(]+)', clean)
    if m2:
        return m2.group(1).strip(), m2.group(2).strip(), 'full'

    # Try "Company, City, State, was awarded"
    m3 = re.match(
        r'^.+?,\s+([^,]+),\s+([^,]+),?\s+(?:was|is|has been|have been|are|will be)\s+(?:awarded|being awarded)',
        clean, re.IGNORECASE,
    )
    if m3:
        city = m3.group(1).strip()
        state = m3.group(2).strip().rstrip('.')
        if state.lower() in _STATE_NAMES or state.upper() in _STATE_CODES:
            return city, state, 'full'
        # State not recognized — might be foreign or parse miss
        return city, state, 'partial'

    return None, None, 'failed'


# ── LLM: semantic extraction (one call per release) ───────────────────────────

_LLM_SYSTEM = """\
You extract structured award data from U.S. Department of Defense contract press release sections.

Return a JSON object with key "award_groups": an array, one entry per distinct contract action.

Each entry:
{
  "awardees": [{"name_raw": "...", "piid": "..."}],
  "purpose": "...",
  "program_hint": "...",
  "action_type": "award" | "modification" | "other"
}

Rules:
- One award_group per coherent announcement. Multi-awardee announcements with N companies = ONE group with N awardees.
- PIID is the contract number shown in parentheses in the text. Return it WITHOUT the surrounding parentheses, e.g. text "(W9126G-26-D-A042)" → piid "W9126G-26-D-A042".
- One PIID per awardee. Never share a PIID across awardees.
- name_raw: company name as written (e.g. "Lockheed Martin Corp."). Exclude city and state.
- purpose: what is being procured (the work/goods, not the contract action). 1-2 sentences, use words from the text. Start with a noun or gerund, not "awarded" — e.g. "Maintenance and repair of USS Wichita" not "was awarded a contract for maintenance...".
- program_hint: named program/system if explicitly stated (e.g. "F-35", "PTS-G"); null otherwise.
- action_type: "modification" when text says "modification to" an existing contract; "award" for new contracts/orders.
- Include CORRECTION and UPDATE paragraphs as valid award groups.
- Omit section headings (ARMY, NAVY, etc.) — they are not award groups.
- Enumerate independently and exhaustively: scan the ENTIRE text and return
  every distinct award with its PIID. Long releases can have 25+ awards — do
  not stop early. Do not rely on any external list; find them yourself.
- Do NOT include parent-contract references as awards. When text says an order
  is placed "against a previously issued basic ordering agreement (PIID)", that
  parenthetical PIID is the parent, not a new award — omit it.
"""

async def _llm_call(body: str, client: AsyncOpenAI) -> dict:
    """Call LLM once for the full release body.

    The LLM enumerates awards independently (no regex hint) so that its PIID list
    can be compared against regex to surface regex-brittleness gaps.

    Returns {"groups": [...], "raw": {...}} where "raw" is the full stored response:
    model, finish_reason, usage, and the model's parsed JSON content. `finish_reason
    == "length"` flags a truncated (max-tokens) response — diagnostic for enumeration.
    """
    try:
        resp = await client.chat.completions.create(
            model=LLM_MODEL,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _LLM_SYSTEM},
                {"role": "user", "content": f"Extract all award groups:\n\n{body}"},
            ],
        )
        content = resp.choices[0].message.content
        parsed = json.loads(content)
        raw = {
            "model":         resp.model,
            "finish_reason": resp.choices[0].finish_reason,
            "usage": {
                "prompt_tokens":     resp.usage.prompt_tokens,
                "completion_tokens": resp.usage.completion_tokens,
                "total_tokens":      resp.usage.total_tokens,
            },
            "content": parsed,   # the model's full raw JSON output
        }
        return {"groups": parsed.get("award_groups", []), "raw": raw}
    except Exception as e:
        logger.error("LLM call failed: %s", e)
        return {"groups": [], "raw": {"error": str(e)}}


# ── Merge: join regex + LLM on PIID ──────────────────────────────────────────

def _merge(regex_groups: list[dict], llm_groups: list[dict]) -> tuple[list[dict], list[str]]:
    """
    Merge regex + LLM results, regex-authoritative (v1).

    Regex owns the award list: every regex group becomes an award row, and every
    regex PIID becomes an awardee entry. The LLM supplies semantic fields
    (name_raw, purpose, program_hint, action_type), joined by PIID.

    pairing_confidence per awardee:
      - "agreed"     : regex PIID also enumerated by the LLM as an award.
      - "regex_only" : regex found it, LLM did not call it an award — usually a
                       parent-contract reference, occasionally an LLM miss.

    Returns (merged_groups, llm_only_piids). llm_only_piids = PIIDs the LLM
    enumerated that regex never found — the regex-brittleness research signal.
    """
    # Index LLM output by normalized PIID key (LLM enumerates independently;
    # its PIID strings may carry parens/mod-numbers, so match on _piid_key).
    key_to_llm_name:  dict[str, str]  = {}
    key_to_llm_group: dict[str, dict] = {}
    llm_keys: set[str] = set()
    llm_raw_by_key: dict[str, str] = {}
    for lg in llm_groups:
        for a in lg.get("awardees", []):
            raw = a.get("piid")
            key = _piid_key(raw or "")
            if not key:
                continue
            llm_keys.add(key)
            key_to_llm_name[key]  = a.get("name_raw")
            key_to_llm_group[key] = lg
            llm_raw_by_key[key]   = raw

    regex_keys: set[str] = set()
    merged: list[dict] = []

    for rg in regex_groups:
        awardees_out = []
        group_llm = None  # LLM group supplying this row's semantic fields

        for chunk in rg["piid_chunks"]:
            piid = chunk["piid"]
            key = _piid_key(piid)
            regex_keys.add(key)
            if key in llm_keys:
                confidence = "agreed"
                if group_llm is None:
                    group_llm = key_to_llm_group.get(key)
            else:
                confidence = "regex_only"

            awardees_out.append({
                "name_raw":           key_to_llm_name.get(key),
                "city_raw":           chunk["city_raw"],
                "state_raw":          chunk["state_raw"],
                "piid":               piid,   # regex's clean string is stored
                "parse_status":       chunk["parse_status"],
                "pairing_confidence": confidence,
            })

        lg = group_llm or {}
        merged.append({
            "awardees":             awardees_out,
            "amounts":              [{"raw": r} for r in (rg.get("amounts") or [])],
            "completion_date_raw":  rg.get("completion_date_raw"),
            "contracting_activity": rg.get("contracting_activity"),
            "purpose":              lg.get("purpose"),
            "program_hint":         lg.get("program_hint") or None,
            "action_type":          lg.get("action_type"),
            "source_excerpt":       rg.get("source_excerpt", ""),
        })

    # Research signal: PIIDs the LLM found that regex missed → possible regex gap.
    llm_only = sorted(llm_raw_by_key[k] for k in (llm_keys - regex_keys))
    if llm_only:
        logger.warning("llm_only PIIDs (regex may have missed — research signal): %s", llm_only)

    return merged, llm_only


# ── Date parsing ──────────────────────────────────────────────────────────────

_MONTH_MAP = {
    'jan':1,'feb':2,'mar':3,'apr':4,'may':5,'jun':6,
    'jul':7,'aug':8,'sep':9,'oct':10,'nov':11,'dec':12,
}

def _parse_completion_date(raw: str | None) -> date | None:
    if not raw:
        return None
    if re.search(r'fiscal\s+year|FY', raw, re.IGNORECASE):
        return None  # fiscal-year references → null, keep raw
    m = re.search(
        r'(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|'
        r'Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)'
        r'[\s.,]+(\d{1,2})[,\s]+(\d{4})',
        raw, re.IGNORECASE,
    )
    if not m:
        return None
    month = _MONTH_MAP.get(m.group(1).lower()[:3])
    if not month:
        return None
    try:
        return date(int(m.group(3)), month, int(m.group(2)))
    except ValueError:
        return None


# ── DB write ──────────────────────────────────────────────────────────────────

async def process_release(
    release: DowContractRelease,
    client: AsyncOpenAI,
    dry_run: bool,
    reprocess: bool,
    session,
) -> int:
    if not release.raw_text:
        return 0

    body = _release_body(release.raw_text)
    rg = _regex_groups(body)                       # regex is authoritative for the award list
    llm = await _llm_call(body, client)            # LLM enumerates independently (no hint)
    lg = llm["groups"]
    groups, llm_only = _merge(rg, lg)

    if not groups:
        logger.warning("release %d (%s): no award groups", release.id, release.release_date)
        return 0

    if dry_run:
        print(f"\n=== {release.release_date}  id={release.id} ({len(groups)} groups) ===")
        for i, g in enumerate(groups):
            for a in g["awardees"]:
                print(f"  [{i}] {a['piid']!r:30s} {(a['name_raw'] or '(none)')!r}  "
                      f"conf={a['pairing_confidence']}  "
                      f"city={a['city_raw']}  state={a['state_raw']}")
            print(f"       purpose={str(g.get('purpose',''))[:80]}")
        if llm_only:
            print(f"       LLM-ONLY (regex gap): {llm_only}")
        return len(groups)

    if reprocess:
        await session.execute(delete(DowAward).where(DowAward.release_id == release.id))

    for i, g in enumerate(groups):
        session.add(DowAward(
            release_id=release.id,
            award_index=i,
            awardees=g["awardees"],
            amounts=g["amounts"] or None,
            completion_date_raw=g["completion_date_raw"],
            completion_date=_parse_completion_date(g["completion_date_raw"]),
            contracting_activity=g["contracting_activity"],
            purpose=g["purpose"],
            program_hint=g["program_hint"],
            action_type=g["action_type"],
            source_excerpt=g["source_excerpt"],
            llm_status="combo",
        ))

    release.llm_extracted_at = datetime.now(timezone.utc)
    # Store ONLY the raw LLM response — nothing we compute. This is a faithful
    # record of the API call: model, finish_reason, usage, and the model's JSON
    # content. Merge/comparison metadata (n_regex, n_llm, llm_only_piids) is
    # deliberately NOT stored here: it is derived, and fully recomputable for
    # research from this stored content + re-running the deterministic regex on
    # raw_text. `llm_only` is still logged during the run (see _merge) for
    # operational visibility, just not persisted into the raw response.
    release.llm_raw_response = llm["raw"]
    await session.commit()
    return len(groups)


# ── Entry point ───────────────────────────────────────────────────────────────

async def run(
    release_id: int | None,
    limit: int | None,
    reprocess: bool,
    dry_run: bool,
    since: date | None = None,
) -> None:
    client = AsyncOpenAI()

    async with AsyncSessionLocal() as session:
        q = select(DowContractRelease).where(DowContractRelease.raw_text.isnot(None))
        if release_id:
            q = q.where(DowContractRelease.id == release_id)
        elif not reprocess:
            q = q.where(DowContractRelease.llm_extracted_at.is_(None))
        if since:  # only releases on/after the cutoff — leaves older backlog untouched
            q = q.where(DowContractRelease.release_date >= since)
        q = q.order_by(DowContractRelease.release_date.desc())
        if limit:
            q = q.limit(limit)

        rows = (await session.execute(q)).scalars().all()
        logger.info("processing %d releases", len(rows))

        total = 0
        for rel in rows:
            n = await process_release(rel, client, dry_run=dry_run, reprocess=reprocess, session=session)
            total += n
            if not dry_run and n:
                logger.info("release %d: %d group(s)", rel.id, n)

        logger.info("done: %d releases, %d award groups total", len(rows), total)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--release-id", type=int)
    ap.add_argument("--limit",      type=int)
    ap.add_argument("--reprocess",  action="store_true")
    ap.add_argument("--dry-run",    action="store_true")
    ap.add_argument("--since",      type=lambda s: date.fromisoformat(s),
                    help="only extract releases with release_date >= this (YYYY-MM-DD)")
    args = ap.parse_args()
    asyncio.run(run(
        release_id=args.release_id,
        limit=args.limit,
        reprocess=args.reprocess,
        dry_run=args.dry_run,
        since=args.since,
    ))
