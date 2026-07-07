"""
Pull SAM.gov award notices (ptype=a) into sam_award_notices.

Purpose: test the real-time latency thesis — does SAM publish an award BEFORE DoW
announces it? Intended to run once a day, pre-market (~7 AM ET). See docs/sam_api.md.

Two SAM endpoints, two rate profiles:
  • SEARCH  /opportunities/v2/search  — KEYED, non-federal key = 10 requests/DAY.
    Gives the daily list but only a date-only postedDate. We spend ~1 request/day:
    a small overlapping window (--days) + one page (paginate only if >1000/day).
  • DETAIL  /api/prod/opps/v2/opportunities/{notice_id}  — UNKEYED (hal+json).
    Gives the PRECISE publish timestamp. Not key-limited, but still sam.gov infra,
    so --detail is throttled + capped (--detail-limit), biggest-dollar first.

Incremental model: no watermark. Each run re-requests an overlapping window and
upserts ON CONFLICT (notice_id) DO NOTHING, so fetched_at (our first-seen) is
preserved and re-runs are idempotent. The overlap catches notices posted late on a
prior day (postedDate is date-only) that weren't up when the previous run fired.

Usage:
  python ingest_sam_awards.py --days 3                 # seed / daily pull (search only)
  python ingest_sam_awards.py --days 2 --detail        # pull + enrich precise timing
  python ingest_sam_awards.py --days 30 --dry-run      # inspect, no writes, no key spend on detail
"""

import argparse
import asyncio
import json
import logging
import os
import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

import httpx
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from strata_core.db import AsyncSessionLocal
from strata_core.models import SamAwardNotice

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
# SECURITY: httpx logs the full request URL at INFO, and the SAM search key is a
# query param (?api_key=...) — that would leak the key into logs. Quiet httpx.
logging.getLogger("httpx").setLevel(logging.WARNING)

SEARCH_URL = "https://api.sam.gov/opportunities/v2/search"
DETAIL_URL = "https://sam.gov/api/prod/opps/v2/opportunities/{notice_id}"
PAGE_SIZE = 1000
DEFAULT_MAX_PAGES = 3          # protective ceiling on keyed search requests per run
RAW_DIR = os.environ.get("SAM_RAW_DIR", "data/sam_raw")
DETAIL_THROTTLE_S = 1.0        # politeness delay between unkeyed detail calls


def _piid_key(s: str | None) -> str:
    """Normalized join key, matching extract_dow_awards_v2._piid_key: first token,
    strip parens/mods, uppercase, drop non-alphanumerics. Keeps SAM↔DoW joinable."""
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
        return date.fromisoformat(v[:10])
    except ValueError:
        return None


def _row_from_opportunity(o: dict) -> dict:
    award = o.get("award") or {}
    awardee = award.get("awardee") or {}
    piid = award.get("number")
    return {
        "notice_id": o.get("noticeId"),
        "piid": piid,
        "piid_key": _piid_key(piid),
        "awardee_name": awardee.get("name"),
        "awardee_uei": awardee.get("ueiSAM"),
        "amount": _to_decimal(award.get("amount")),
        "agency_path": o.get("fullParentPathName"),
        "title": o.get("title"),
        "posted_date": _to_date(o.get("postedDate")),
        "sam_url": o.get("uiLink"),
        "raw": o,
    }


# ── SEARCH (keyed) ───────────────────────────────────────────────────────────

def _search_page(client: httpx.Client, key: str, pf: str, pt: str, offset: int) -> dict:
    params = {"api_key": key, "ptype": "a", "postedFrom": pf, "postedTo": pt,
              "limit": PAGE_SIZE, "offset": offset}
    r = client.get(SEARCH_URL, params=params, timeout=120)
    r.raise_for_status()
    return r.json()


def _save_raw(pf: str, pt: str, page: int, payload: dict) -> None:
    Path(RAW_DIR).mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    safe = lambda s: s.replace("/", "-")
    path = Path(RAW_DIR) / f"sam_search_{safe(pf)}_{safe(pt)}_{ts}_p{page}.json"
    path.write_text(json.dumps(payload))
    logger.info("saved raw page %d -> %s", page, path)


def fetch_search(days: int, max_pages: int) -> list[dict]:
    key = os.environ.get("SAM_API_KEY")
    if not key:
        raise SystemExit("SAM_API_KEY not set (env/.env). Keyed search cannot run.")
    today = date.today()
    pf = (today - timedelta(days=days)).strftime("%m/%d/%Y")
    pt = today.strftime("%m/%d/%Y")
    logger.info("SAM search window %s -> %s (ptype=a), up to %d page(s)", pf, pt, max_pages)

    opportunities: list[dict] = []
    with httpx.Client() as client:
        for page in range(max_pages):
            payload = _search_page(client, key, pf, pt, page * PAGE_SIZE)
            _save_raw(pf, pt, page, payload)
            batch = payload.get("opportunitiesData") or []
            total = payload.get("totalRecords")
            logger.info("page %d: %d records (totalRecords=%s)", page, len(batch), total)
            opportunities.extend(batch)
            if len(batch) < PAGE_SIZE:
                break
            if isinstance(total, int) and (page + 1) * PAGE_SIZE >= total:
                break
        else:
            logger.warning("hit max_pages=%d; more records may exist (widen at your own key-cost)", max_pages)
    return opportunities


# ── DETAIL (unkeyed, precise timing) ─────────────────────────────────────────

def fetch_detail_timestamps(notice_id: str) -> tuple[datetime | None, datetime | None]:
    """Return (published_at, sam_created_at) from the unkeyed detail endpoint."""
    try:
        r = httpx.get(DETAIL_URL.format(notice_id=notice_id),
                      headers={"Accept": "application/hal+json"}, timeout=30)
        if r.status_code != 200:
            logger.warning("detail %s: HTTP %d", notice_id, r.status_code)
            return None, None
        d = r.json()
        def parse(v):
            try:
                return datetime.fromisoformat(v) if v else None
            except (ValueError, TypeError):
                return None
        return parse(d.get("postedDate")), parse(d.get("createdDate"))
    except Exception as e:
        logger.warning("detail %s: %s", notice_id, e)
        return None, None


# ── DB upsert + enrich ───────────────────────────────────────────────────────

async def upsert(rows: list[dict], dry_run: bool) -> int:
    rows = [r for r in rows if r.get("notice_id")]
    if not rows:
        return 0
    if dry_run:
        for r in rows[:10]:
            logger.info("[dry] %s | %s | %s | $%s | %s", r["posted_date"], r["piid"],
                        (r["awardee_name"] or "")[:30], r["amount"], (r["title"] or "")[:40])
        logger.info("[dry] %d notice(s) parsed (not written)", len(rows))
        return 0
    # One row per statement + commit. A single bad row is logged and skipped
    # instead of aborting the whole pull (its own commit means no poisoned
    # transaction). Idempotent (ON CONFLICT DO NOTHING) so re-running is safe, and
    # row-at-a-time is plenty fast for a twice-daily background job.
    written = skipped = 0
    async with AsyncSessionLocal() as s:
        for r in rows:
            try:
                stmt = pg_insert(SamAwardNotice).values(r).on_conflict_do_nothing(index_elements=["notice_id"])
                await s.execute(stmt)
                await s.commit()
                written += 1
            except Exception as e:
                await s.rollback()
                skipped += 1
                logger.warning("skipped notice %s: %s", r.get("notice_id"), e)
    logger.info("upserted %d notice(s), skipped %d (existing notice_ids preserved)", written, skipped)
    return written


async def enrich_details(limit: int, min_amount: Decimal, dry_run: bool) -> int:
    """Fill precise timestamps for notices missing them, biggest-dollar first."""
    async with AsyncSessionLocal() as s:
        q = (select(SamAwardNotice)
             .where(SamAwardNotice.published_at.is_(None))
             .where(SamAwardNotice.amount >= min_amount if min_amount else text("TRUE"))
             .order_by(SamAwardNotice.amount.desc().nullslast())
             .limit(limit))
        pending = (await s.execute(q)).scalars().all()
        if not pending:
            logger.info("detail: nothing to enrich")
            return 0
        logger.info("detail: enriching %d notice(s) (unkeyed, throttled %.1fs)", len(pending), DETAIL_THROTTLE_S)
        n = 0
        for row in pending:
            pub, created = fetch_detail_timestamps(row.notice_id)
            if pub or created:
                if dry_run:
                    logger.info("[dry] %s published_at=%s created=%s", row.piid, pub, created)
                else:
                    row.published_at = pub
                    row.sam_created_at = created
                n += 1
            await asyncio.sleep(DETAIL_THROTTLE_S)
        if not dry_run:
            await s.commit()
    logger.info("detail: enriched %d notice(s)", n)
    return n


async def run(args) -> None:
    opportunities = fetch_search(args.days, args.max_pages)
    rows = [_row_from_opportunity(o) for o in opportunities]
    logger.info("parsed %d award notice(s)", len(rows))
    await upsert(rows, args.dry_run)
    if args.detail:
        await enrich_details(args.detail_limit, Decimal(str(args.detail_min_amount)), args.dry_run)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=2, help="overlapping window size (postedFrom = today - N)")
    ap.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES, help="keyed-search page ceiling (protects 10/day quota)")
    ap.add_argument("--detail", action="store_true", help="also fetch precise timestamps (unkeyed detail endpoint)")
    ap.add_argument("--detail-limit", type=int, default=50, help="max notices to detail-enrich per run")
    ap.add_argument("--detail-min-amount", type=float, default=0, help="only detail-enrich notices >= this amount")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    asyncio.run(run(args))
