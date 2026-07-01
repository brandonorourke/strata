# apps/ingest/ingest_icfs.py
#
# Scraping layer only — pulls raw ICFS data into source-shaped staging tables
# (icfs_filings, icfs_pleadings_and_comments, icfs_public_notices). Does not
# touch extracted_entities/extracted_events; see extract_icfs_entities.py for
# the processing step that promotes structured rows into the canonical model.
#
# Two modes (ICFS_MODE env var):
#   backfill    — resumes from stored page in icfs_ingest_state, walks to end of history
#   incremental — starts from newest, stops when records are older than MAX(date) - 1 day

import asyncio
import logging
import os
import re
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import func, select

from strata_core.db import AsyncSessionLocal
from strata_core.models import IcfsFiling, IcfsIngestState, IcfsPleadingAndComment, IcfsPublicNotice

from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

BASE_URL = "https://fccprod.servicenowservices.com"
WIDGET_SYS_ID = "842c213fdb4a0410d02ffb0e0f961934"
HOME_PAGE_URL = f"{BASE_URL}/ibfs?id=ibfs_home"
WIDGET_URL = f"{BASE_URL}/api/now/sp/widget/{WIDGET_SYS_ID}?id=ibfs_home"

USER_AGENT = "Mozilla/5.0 (compatible; StrataBot/0.1; contact: admin@example.com)"
# ICFS's robots.txt disallows all bot access site-wide (User-agent: * / Disallow: /).
# The data itself is unauthenticated public government records, so we're proceeding,
# but deliberately erring far on the side of caution on pacing given that signal.
REQUEST_DELAY_SECONDS = 3.0

# Sentinel/garbage dates appear in real ICFS data (e.g. 8888-08-08, 4444-04-04) — treat
# anything outside a plausible range as unknown rather than parsing it literally.
MIN_PLAUSIBLE_YEAR = 1990

# x_fmc_ibfs_base_table backs both "Recent Filings" and "Recent Actions" on the
# official site — request the union of fields once instead of walking it twice.
ICFS_TABLES = [
    {
        "table": "x_fmc_ibfs_base_table",
        "fields": "number,call_sign,applicant_name,submission_date,action,action_taken_date",
        "order_by": "submission_date",
        "model": IcfsFiling,
    },
    {
        "table": "x_fmc_ibfs_pleadings_and_comments",
        "fields": "pleading_type,applicant_names,sys_created_on,file_number",
        "order_by": "sys_created_on",
        "model": IcfsPleadingAndComment,
    },
    {
        "table": "x_fmc_ibfs_public_notices",
        "fields": "number,subsystem,type_of_document,public_notice_release_date,url,da_number",
        "order_by": "public_notice_release_date",
        "model": IcfsPublicNotice,
    },
]


def _bootstrap_session() -> tuple[httpx.Client, str]:
    """
    GET the ICFS home page to acquire session cookies + the g_ck CSRF token.
    Both are required on every subsequent POST to the widget endpoint, even
    though the API itself is publicly accessible with no login.
    """
    client = httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30.0, follow_redirects=True)
    resp = client.get(HOME_PAGE_URL)
    resp.raise_for_status()

    match = re.search(r"g_ck = '([^']+)'", resp.text)
    if not match:
        raise RuntimeError("Could not find g_ck token on ICFS home page — page structure may have changed.")

    return client, match.group(1)


def _fetch_page(client: httpx.Client, g_ck: str, table: str, fields: str, order_by: str, page: int) -> dict:
    payload = {
        "table": table,
        "fields": fields,
        "o": order_by,
        "d": "desc",
        "p": page,
        "filter": "",  # empty filter = entire table, not just the official site's default 7-day window
    }
    resp = client.post(
        WIDGET_URL,
        json=payload,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json;charset=UTF-8",
            "X-UserToken": g_ck,
        },
    )
    resp.raise_for_status()
    data = resp.json()["result"]["data"]

    if data.get("invalid_token"):
        raise RuntimeError("ICFS session token was rejected — session needs to be re-bootstrapped.")

    return data


def _parse_glide_datetime(value: str | None) -> datetime | None:
    """
    ServiceNow returns two date shapes depending on the field's glide type:
    glide_date_time ("2026-06-18 12:00:00") and glide_date ("2026-06-18", no time
    component — used by e.g. public_notice_release_date). Try both.
    """
    if not value:
        return None
    dt = None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(value, fmt)
            break
        except ValueError:
            continue
    if dt is None:
        return None
    if dt.year < MIN_PLAUSIBLE_YEAR or dt.year > datetime.now(timezone.utc).year + 1:
        return None
    return dt.replace(tzinfo=timezone.utc)


def _field(row: dict, name: str) -> str | None:
    """
    Most ServiceNow fields come back as {"display_value": ..., "value": ..., ...},
    but a few (e.g. public_notices' url) are computed/script fields returned as a bare
    string instead — handle both shapes.
    """
    cell = row.get(name)
    if isinstance(cell, dict):
        return cell.get("display_value") or None
    if isinstance(cell, str):
        return cell or None
    return None


def _row_to_model_kwargs(table: str, row: dict) -> dict:
    """Map one ServiceNow row to the matching staging-table model's constructor kwargs."""
    sys_id = row["sys_id"]

    if table == "x_fmc_ibfs_pleadings_and_comments":
        return {
            "source_sys_id": sys_id,
            "pleading_type": _field(row, "pleading_type"),
            "applicant_names": _field(row, "applicant_names"),
            "sys_created_on": _parse_glide_datetime(_field(row, "sys_created_on")),
            "file_number": _field(row, "file_number"),
        }

    if table == "x_fmc_ibfs_public_notices":
        return {
            "source_sys_id": sys_id,
            "number": _field(row, "number"),
            "subsystem": _field(row, "subsystem"),
            "type_of_document": _field(row, "type_of_document"),
            "public_notice_release_date": _parse_glide_datetime(_field(row, "public_notice_release_date")),
            "url": _field(row, "url"),
            "da_number": _field(row, "da_number"),
        }

    # x_fmc_ibfs_base_table — Filings + Actions
    return {
        "source_sys_id": sys_id,
        "file_number": _field(row, "number"),
        "call_sign": _field(row, "call_sign"),
        "applicant_name": _field(row, "applicant_name"),
        "submission_date": _parse_glide_datetime(_field(row, "submission_date")),
        "action": _field(row, "action"),
        "action_taken_date": _parse_glide_datetime(_field(row, "action_taken_date")),
        "target_table": row.get("targetTable"),
    }


async def _save_backfill_state(session, table: str, page: int, complete: bool) -> None:
    state = await session.get(IcfsIngestState, table)
    if state is None:
        session.add(IcfsIngestState(
            source_table=table,
            backfill_page=page,
            backfill_complete=complete,
            updated_at=datetime.now(timezone.utc),
        ))
    else:
        state.backfill_page = page
        state.backfill_complete = complete
        state.updated_at = datetime.now(timezone.utc)
    await session.commit()


async def ingest_table(session, table: str, fields: str, order_by: str, model, max_pages: int | None, mode: str) -> int:
    client, g_ck = _bootstrap_session()
    new_count = 0

    if mode == "backfill":
        state = await session.get(IcfsIngestState, table)
        start_page = state.backfill_page if state else 1
        stop_before = None
        if start_page > 1:
            logger.info("%s: resuming backfill from page %d.", table, start_page)
    else:
        start_page = 1
        result = await session.execute(select(func.max(getattr(model, order_by))))
        max_date = result.scalar_one_or_none()
        if max_date is None:
            logger.warning("%s: no existing records — incremental will run to end of table.", table)
            stop_before = None
        else:
            stop_before = max_date - timedelta(days=1)
            logger.info("%s: incremental stop_before=%s.", table, stop_before.date())

    page = start_page

    try:
        while True:
            data = _fetch_page(client, g_ck, table, fields, order_by, page)
            rows = data.get("list", [])
            if not rows:
                break

            page_new = 0
            stop_incremental = False

            for row in rows:
                if mode == "incremental" and stop_before is not None:
                    row_date = _parse_glide_datetime(_field(row, order_by))
                    if row_date is not None and row_date < stop_before:
                        stop_incremental = True
                        break

                sys_id = row["sys_id"]
                existing = await session.execute(
                    select(model.id).where(model.source_sys_id == sys_id).limit(1)
                )
                if existing.scalar_one_or_none() is not None:
                    continue

                session.add(model(**_row_to_model_kwargs(table, row)))
                page_new += 1
                new_count += 1

            await session.commit()

            if mode == "backfill":
                await _save_backfill_state(session, table, page, complete=False)

            logger.info(
                "%s page %d/%s: %d new of %d rows",
                table, page, data.get("num_pages"), page_new, len(rows),
            )

            if stop_incremental:
                logger.info("%s: reached stop_before threshold, done.", table)
                break

            num_pages = data.get("num_pages", page)
            if page >= num_pages:
                if mode == "backfill":
                    await _save_backfill_state(session, table, page, complete=True)
                    logger.info("%s: backfill complete.", table)
                break
            if max_pages is not None and page >= max_pages:
                logger.info("%s: hit ICFS_MAX_PAGES=%d cap, stopping early.", table, max_pages)
                break

            page += 1
            await asyncio.sleep(REQUEST_DELAY_SECONDS)
    finally:
        client.close()

    return new_count


async def main() -> None:
    """
    ICFS_MODE=backfill (default): resumes from stored page in icfs_ingest_state per table,
    walks to end of history. Safe to stop and restart — picks up where it left off.

    ICFS_MODE=incremental: starts from newest, stops when records are older than
    MAX(date) - 1 day. Designed for daily runs after the backfill is complete.

    ICFS_MAX_PAGES caps pages per table (useful for test runs).
    """
    max_pages_env = os.getenv("ICFS_MAX_PAGES")
    max_pages = int(max_pages_env) if max_pages_env else None

    mode = os.getenv("ICFS_MODE", "backfill")
    if mode not in ("backfill", "incremental"):
        raise ValueError(f"ICFS_MODE must be 'backfill' or 'incremental', got {mode!r}")

    logger.info("ICFS ingest mode: %s", mode)

    async with AsyncSessionLocal() as session:
        total_new = 0
        for spec in ICFS_TABLES:
            try:
                new_for_table = await ingest_table(
                    session, spec["table"], spec["fields"], spec["order_by"], spec["model"], max_pages, mode,
                )
                total_new += new_for_table
                logger.info("%s: inserted %d new rows.", spec["table"], new_for_table)
            except Exception as e:
                await session.rollback()
                logger.error("Error ingesting %s: %r", spec["table"], e)

        logger.info("Done. Total new ICFS rows inserted: %d", total_new)


if __name__ == "__main__":
    asyncio.run(main())
