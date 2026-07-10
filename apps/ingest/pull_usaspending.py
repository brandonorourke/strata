"""
Pull raw USASpending awards by UEI into usaspending_awards (manual, local-only).

USASpending's public spending_by_award API is FREE and unlimited (no key), so this
is the corpus spine. Given a seed UEI (or several), we:
  1. resolve the UEI FAMILY — a company is a *set* of UEIs (Viasat is L9Z1ASN3B8E7
     *and* JB7UBCTNM6N5, plus subs/acquisitions). The family = the seeds + the
     recipient `children/<uei>` endpoint (authoritative). Optionally
     (--discover-siblings) also pull fuzzy-surfaced same-name UEIs NOT in the
     children family — off by default.
  2. pull two award-type groups per family UEI:
       IDV_*  → the vehicles (bases/parents), incl. zero-drawn latent ones
       A,B,C,D → definitive contracts + delivery/task orders (the draws)
     (the API rejects mixing groups — "must only contain types from one group".)
  3. parse the parent PIID out of generated_internal_id so a draw links to its
     vehicle (CONT_AWD_{order}_{oag}_{PARENT}_{pag}; -NONE- = standalone).
  4. upsert (ON CONFLICT generated_internal_id) so re-pulls refresh amounts.

NOT part of the daily pipeline. You run it; it makes only free USASpending calls.

Usage:
  python apps/ingest/pull_usaspending.py --uei L9Z1ASN3B8E7 --ticker VSAT
  python apps/ingest/pull_usaspending.py --uei L9Z1ASN3B8E7 --dry-run   # no writes
  python apps/ingest/pull_usaspending.py --uei L9Z1ASN3B8E7 --no-children
"""

import argparse
import asyncio
import json
import logging
import re
import time
from datetime import date
from decimal import Decimal, InvalidOperation

import httpx
from sqlalchemy.dialects.postgresql import insert as pg_insert

from strata_core.db import AsyncSessionLocal
from strata_core.models import UsaspendingAward

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)  # its per-frame DEBUG trace is noisy under -v

SEARCH_URL   = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
CHILDREN_URL = "https://api.usaspending.gov/api/v2/recipient/children/{uei}/"
IDV_TYPES    = ["IDV_A", "IDV_B", "IDV_B_A", "IDV_B_B", "IDV_B_C", "IDV_C", "IDV_D", "IDV_E"]
ORDER_TYPES  = ["A", "B", "C", "D"]
FIELDS = ["Award ID", "Recipient Name", "Recipient UEI", "recipient_id",
          "Awarding Agency", "Awarding Sub Agency", "Description", "Start Date",
          "End Date", "Award Amount", "Total Outlays", "Contract Award Type",
          "NAICS", "PSC", "Last Modified Date", "Base Obligation Date",
          "Last Date to Order", "generated_internal_id"]  # Last Date to Order is IDV-only → null on contracts
PAGE_LIMIT = 100
MAX_RETRIES = 4                           # per-page transient-error retries
BACKOFF_BASE = 2.0                        # exponential backoff seconds: 2, 4, 8…
RETRY_STATUS = {429, 500, 502, 503, 504}  # USASpending blips transiently under load

_PARENT_RE = re.compile(r"^CONT_AWD_[^_]+_[^_]+_([^_]+)_([^_]+)$")


def _piid_key(s: str | None) -> str:
    """Normalized join key, matching extract_dow_awards_v2 / ingest_sam_awards."""
    if not s:
        return ""
    toks = s.strip().strip("()").split()
    first = toks[0] if toks else ""
    return re.sub(r"[^A-Z0-9]", "", first.upper())


def _to_decimal(v) -> Decimal | None:
    if v in (None, ""):
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError):
        return None


def _to_date(v: str | None) -> date | None:
    if not v:
        return None
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def _parse_parent(gid: str) -> tuple[str | None, str | None]:
    """(parent_piid, parent_agency) from CONT_AWD_{order}_{oag}_{PARENT}_{pag}; a
    standalone definitive contract has parent -NONE- → (None, None)."""
    m = _PARENT_RE.match(gid or "")
    if not m:
        return (None, None)
    parent, ag = m.group(1), m.group(2)
    if parent in ("-NONE-", "NONE", ""):
        return (None, None)
    return (parent, ag)


def _row(o: dict, seed_uei: str, ticker: str | None) -> dict:
    gid = o.get("generated_internal_id") or ""
    parent_piid, parent_ag = _parse_parent(gid)
    naics = o.get("NAICS") or {}
    psc = o.get("PSC") or {}
    award_id = o.get("Award ID")
    return {
        "generated_internal_id": gid,
        "award_id": award_id,
        "award_id_key": _piid_key(award_id),
        "award_type": o.get("Contract Award Type"),
        "is_idv": gid.startswith("CONT_IDV"),
        "parent_award_id": parent_piid,
        "parent_generated_id": f"CONT_IDV_{parent_piid}_{parent_ag}" if parent_piid else None,
        "recipient_name": o.get("Recipient Name"),
        "recipient_uei": o.get("Recipient UEI"),
        "recipient_id": o.get("recipient_id"),
        "seed_uei": seed_uei,
        "ticker": ticker,
        "awarding_agency": o.get("Awarding Agency"),
        "awarding_sub_agency": o.get("Awarding Sub Agency"),
        "description": o.get("Description"),
        "start_date": _to_date(o.get("Start Date")),
        "end_date": _to_date(o.get("End Date")),
        "amount": _to_decimal(o.get("Award Amount")),
        "total_outlays": _to_decimal(o.get("Total Outlays")),
        "naics_code": (naics or {}).get("code"),
        "psc_code": (psc or {}).get("code"),
        "last_modified": o.get("Last Modified Date"),
        "base_obligation_date": _to_date(o.get("Base Obligation Date")),
        "last_order_date": _to_date(o.get("Last Date to Order")),  # IDV-only; None on contracts
        "raw": o,
    }


# ── USASpending fetch (free, unlimited, no key) ──────────────────────────────

def fetch_children(client: httpx.Client, uei: str) -> list[str]:
    """UEIs of a recipient's registration family via the children endpoint.
    Defensive on shape (list or {'results': [...]}); children is supplementary —
    exhaustiveness also comes from fuzzy-search discovery below."""
    url = CHILDREN_URL.format(uei=uei)
    logger.info("→ GET  children uei=%s", uei)
    try:
        r = client.get(url, timeout=60)
        logger.info("← HTTP %d  children (%dms, %d bytes)",
                    r.status_code, int(r.elapsed.total_seconds() * 1000), len(r.content))
        logger.debug("  children response body: %s", r.text[:2000])
        if r.status_code != 200:
            logger.warning("children %s: HTTP %d", uei, r.status_code)
            return []
        data = r.json()
        items = data if isinstance(data, list) else (data.get("results") or [])
        ueis = [it.get("uei") for it in items if isinstance(it, dict) and it.get("uei")]
        logger.info("  children %s: %d UEI(s) parsed", uei, len(ueis))
        return ueis
    except Exception as e:  # noqa: BLE001 — best-effort expansion
        logger.warning("children %s: %s", uei, e)
        return []


def _post_search(client: httpx.Client, uei: str, type_codes: list[str], page: int) -> dict | None:
    """One spending_by_award page, with retry+backoff on transient errors (429/5xx,
    timeouts). Returns the parsed JSON, or None if it ultimately failed (caller skips)."""
    group = "IDV" if type_codes[0].startswith("IDV") else "A-D"
    payload = {
        "filters": {"recipient_search_text": [uei], "award_type_codes": type_codes},
        "fields": FIELDS, "sort": "Award Amount", "order": "desc",
        "limit": PAGE_LIMIT, "page": page,
    }
    logger.info("→ POST spending_by_award uei=%s group=%s page=%d", uei, group, page)
    logger.debug("  request payload: %s", json.dumps(payload))
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = client.post(SEARCH_URL, json=payload, timeout=120)
            logger.info("← HTTP %d  uei=%s group=%s page=%d (%dms, %d bytes)",
                        r.status_code, uei, group, page,
                        int(r.elapsed.total_seconds() * 1000), len(r.content))
            if r.status_code in RETRY_STATUS:
                raise httpx.HTTPStatusError(f"HTTP {r.status_code}", request=r.request, response=r)
            r.raise_for_status()
            logger.debug("  response body: %s", r.text[:2000])
            return r.json()
        except (httpx.HTTPStatusError, httpx.TransportError) as e:
            sc = getattr(getattr(e, "response", None), "status_code", "—")
            if attempt == MAX_RETRIES:
                logger.error("  giving up uei=%s group=%s page=%d after %d tries (last HTTP %s / %s) — skipping",
                             uei, group, page, MAX_RETRIES, sc, type(e).__name__)
                return None
            wait = BACKOFF_BASE ** attempt
            logger.warning("  transient uei=%s group=%s page=%d (HTTP %s / %s) — retry %d/%d in %.0fs",
                           uei, group, page, sc, type(e).__name__, attempt, MAX_RETRIES - 1, wait)
            time.sleep(wait)
    return None


def search_awards(client: httpx.Client, uei: str, type_codes: list[str], max_pages: int) -> list[dict]:
    """All spending_by_award results for one UEI + one award-type group, paginated.
    A page that ultimately fails is skipped (partial result) rather than crashing the
    whole pull — re-run to backfill, upserts are idempotent."""
    out: list[dict] = []
    for page in range(1, max_pages + 1):
        data = _post_search(client, uei, type_codes, page)
        if data is None:                      # exhausted retries → stop this group, keep going
            break
        batch = data.get("results") or []
        meta = data.get("page_metadata") or {}
        logger.info("  results=%d hasNext=%s", len(batch), meta.get("hasNext"))
        out.extend(batch)
        if not meta.get("hasNext"):
            break
    else:
        logger.warning("uei %s %s: hit max_pages=%d (more may exist)", uei, type_codes[0], max_pages)
    return out


def collect(seeds: list[str], ticker: str | None, use_children: bool,
            discover: bool, max_pages: int) -> list[dict]:
    """Resolve the UEI family, then pull every family UEI's IDVs + orders. Family =
    seeds + (unless --no-children) the recipient children endpoint's results. Keeps
    only awards whose Recipient UEI == the UEI searched (drops fuzzy false-positives).
    If `discover`, fuzzy-surfaced same-name siblings NOT already in the family are also
    pulled — off by default, since children is the authoritative family."""
    anchor = seeds[0]
    family: set[str] = set(seeds)
    queue: list[str] = list(seeds)
    with httpx.Client() as client:
        if use_children:
            for s in seeds:
                for c in fetch_children(client, s):
                    if c not in family:
                        family.add(c)
                        queue.append(c)
            logger.info("family after children expansion: %d UEIs", len(family))

        searched: set[str] = set()
        rows: dict[str, dict] = {}
        while queue:
            uei = queue.pop()
            if uei in searched:
                continue
            searched.add(uei)
            n_exact = 0
            for group in (IDV_TYPES, ORDER_TYPES):
                for o in search_awards(client, uei, group, max_pages):
                    ruei = o.get("Recipient UEI")
                    if ruei == uei:
                        rows[o.get("generated_internal_id") or ""] = _row(o, anchor, ticker)
                        n_exact += 1
                    elif discover and ruei and ruei not in family:  # opt-in: fuzzy sibling
                        family.add(ruei)
                        queue.append(ruei)
            logger.info("uei %s: %d exact award(s) | family now %d", uei, n_exact, len(family))

    rows.pop("", None)
    # the queue's end state: the resolved UEI family + each one's award count
    by_uei: dict[str, list] = {}
    for r in rows.values():
        slot = by_uei.setdefault(r["recipient_uei"], [0, r["recipient_name"]])
        slot[0] += 1
    logger.info("family resolved: %d UEI(s)", len(family))
    for u in sorted(family):
        cnt, name = by_uei.get(u, [0, None])
        logger.info("  %s  %-28s  %d award(s)", u, (name or "—")[:28], cnt)
    logger.info("collected %d distinct award(s) across %d family UEI(s)", len(rows), len(family))
    return list(rows.values())


# ── upsert ───────────────────────────────────────────────────────────────────

async def upsert(rows: list[dict], dry_run: bool) -> int:
    rows = [r for r in rows if r.get("generated_internal_id")]
    if not rows:
        logger.info("no rows to write")
        return 0
    if dry_run:
        idv = sum(1 for r in rows if r["is_idv"])
        orders = sum(1 for r in rows if not r["is_idv"] and r["parent_award_id"])
        standalone = sum(1 for r in rows if not r["is_idv"] and not r["parent_award_id"])
        ueis = {r["recipient_uei"] for r in rows if r["recipient_uei"]}
        total_amt = sum((r["amount"] or 0) for r in rows)
        for r in sorted(rows, key=lambda x: x["amount"] or 0, reverse=True)[:12]:
            logger.info("[dry] %-9s $%15s | %-22s | %s | %s",
                        "IDV" if r["is_idv"] else ("order" if r["parent_award_id"] else "standalone"),
                        f"{r['amount']:,.0f}" if r["amount"] is not None else "—",
                        (r["award_id"] or "")[:22],
                        (f"→ {r['parent_award_id']}" if r["parent_award_id"] else "").ljust(18),
                        (r["description"] or "")[:40])
        logger.info("[dry] %d awards | %d IDV / %d orders / %d standalone | %d UEIs | Σ$%s",
                    len(rows), idv, orders, standalone, len(ueis), f"{total_amt:,.0f}")
        return 0
    n = 0
    async with AsyncSessionLocal() as s:
        for r in rows:
            stmt = pg_insert(UsaspendingAward).values(**r)
            update = {k: stmt.excluded[k] for k in r if k != "generated_internal_id"}
            stmt = stmt.on_conflict_do_update(index_elements=["generated_internal_id"], set_=update)
            try:
                await s.execute(stmt)
                await s.commit()
                n += 1
            except Exception as e:  # noqa: BLE001 — skip a bad row, keep the pull going
                await s.rollback()
                logger.warning("upsert %s: %s", r.get("generated_internal_id"), e)
    logger.info("upserted %d award(s)", n)
    return n


async def run(args) -> None:
    rows = collect(args.uei, args.ticker, not args.no_children, args.discover_siblings, args.max_pages)
    await upsert(rows, args.dry_run)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--uei", action="append", required=True, help="seed UEI (repeatable); first is the family anchor")
    ap.add_argument("--ticker", default=None, help="optional label stored on every row")
    ap.add_argument("--max-pages", type=int, default=20, help="page ceiling per (UEI, award-type group)")
    ap.add_argument("--no-children", action="store_true", help="skip the recipient children-endpoint expansion")
    ap.add_argument("--discover-siblings", action="store_true", help="also pull fuzzy-surfaced same-name UEIs not in the children family (off by default)")
    ap.add_argument("--dry-run", action="store_true", help="parse + summarize, write nothing")
    ap.add_argument("-v", "--verbose", action="store_true", help="DEBUG: log full request payloads + response bodies")
    args = ap.parse_args()
    if args.verbose:
        logger.setLevel(logging.DEBUG)  # only OUR request/response DEBUG lines, not httpx/httpcore trace
    asyncio.run(run(args))
