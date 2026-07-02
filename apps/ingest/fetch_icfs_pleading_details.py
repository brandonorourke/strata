# apps/ingest/fetch_icfs_pleading_details.py
#
# Enriches ICFS pleadings with filer name and attachments from the ibfs_pc_summary page API.
# Calls /api/now/sp/page?id=ibfs_pc_summary&sys_id={source_sys_id} per pleading.
#
# Runs for all pleadings with detail_fetched_at IS NULL.
# Resumable — committed per row, safe to stop and restart.

import argparse
import asyncio
import logging
import re
import time
from datetime import datetime, timezone

import httpx
from sqlalchemy import select

from strata_core.db import AsyncSessionLocal
from strata_core.models import IcfsFiling, IcfsPleadingAndComment

from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

BASE_URL = "https://fccprod.servicenowservices.com"
HOME_PAGE_URL = f"{BASE_URL}/ibfs?id=ibfs_home"
PAGE_API_URL = f"{BASE_URL}/api/now/sp/page"
USER_AGENT = "Mozilla/5.0 (compatible; StrataBot/0.1; contact: admin@example.com)"
REQUEST_DELAY_SECONDS = 1.0


def _bootstrap_session() -> tuple[httpx.Client, str]:
    client = httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30.0, follow_redirects=True)
    resp = client.get(HOME_PAGE_URL)
    resp.raise_for_status()
    match = re.search(r"g_ck = '([^']+)'", resp.text)
    if not match:
        raise RuntimeError("Could not find g_ck token on ICFS home page")
    return client, match.group(1)


def _display(field) -> str | None:
    if isinstance(field, dict):
        return field.get("display_value") or None
    if isinstance(field, str):
        return field or None
    return None


def _fetch_page(client: httpx.Client, g_ck: str, sys_id: str) -> dict | None:
    resp = client.get(
        PAGE_API_URL,
        params={"id": "ibfs_pc_summary", "sys_id": sys_id},
        headers={"Accept": "application/json", "X-UserToken": g_ck},
    )
    resp.raise_for_status()
    return resp.json().get("result")


def _extract_detail(result: dict) -> dict:
    """
    Walk the ServiceNow widget tree for a pleading summary page.

    Summary fields live at containers → rows → columns → widgets → widget.data.summary
    Attachments at widget.data.tabs.data.widgets[0] → widgets → data.all_data[]
    Download URL at attachment.actions.links[0].url
    """
    summary = None
    raw_attachments = []

    for container in result.get("containers", []):
        for row in container.get("rows", []):
            for col in row.get("columns", []):
                for widget_wrap in col.get("widgets", []):
                    data = (widget_wrap.get("widget") or {}).get("data") or {}

                    if "summary" in data and summary is None:
                        summary = data["summary"]

                    tabs_data = data.get("tabs", {}).get("data", {})
                    tab_widgets = tabs_data.get("widgets", [])
                    if tab_widgets:
                        attachments_tab = tab_widgets[0]
                        for sw in attachments_tab.get("widgets", []):
                            sw_data = sw.get("data") or {}
                            raw_attachments.extend(sw_data.get("all_data", []))

    detail: dict = {}

    if summary:
        detail["filer_name"] = _display(summary.get("filer_name"))

    attachment_list = []
    for att in raw_attachments:
        links = att.get("actions", {}).get("links", [])
        url = links[0].get("url") if links else None
        if not url or not url.startswith("http"):
            continue
        doc_name = _display(att.get("document_name")) or ""
        desc = _display(att.get("u_description")) or None
        date = _display(att.get("sys_created_on")) or None
        attachment_list.append({"name": doc_name, "description": desc, "date": date, "url": url})

    if attachment_list:
        detail["attachments"] = attachment_list

    detail["raw_detail"] = {"summary": summary, "attachments": raw_attachments}

    return detail


async def main(viasat_only: bool = False) -> None:
    async with AsyncSessionLocal() as session:
        stmt = (
            select(IcfsPleadingAndComment)
            .where(IcfsPleadingAndComment.detail_fetched_at.is_(None))
            .order_by(IcfsPleadingAndComment.sys_created_on.desc())
        )
        if viasat_only:
            viasat_file_numbers = select(IcfsFiling.file_number).where(
                IcfsFiling.applicant_name.ilike("%viasat%"),
                IcfsFiling.file_number.isnot(None),
            )
            stmt = stmt.where(IcfsPleadingAndComment.file_number.in_(viasat_file_numbers))

        result = await session.execute(stmt)
        pleadings = result.scalars().all()
        pending = [(p.id, p.source_sys_id) for p in pleadings]

    logger.info("Fetching details for %d pleadings with no detail yet", len(pending))
    if not pending:
        return

    client, g_ck = _bootstrap_session()
    updated = 0
    errors = 0

    try:
        for i, (pleading_id, sys_id) in enumerate(pending):
            if i > 0:
                time.sleep(REQUEST_DELAY_SECONDS)
            try:
                page_result = _fetch_page(client, g_ck, sys_id)
                if page_result is None:
                    logger.warning("%s: empty page response", sys_id)
                    continue

                detail = _extract_detail(page_result)

                async with AsyncSessionLocal() as session:
                    pleading = await session.get(IcfsPleadingAndComment, pleading_id)
                    if pleading is None:
                        continue
                    pleading.filer_name = detail.get("filer_name")
                    pleading.attachments = detail.get("attachments")
                    pleading.raw_detail = detail.get("raw_detail")
                    pleading.detail_fetched_at = datetime.now(timezone.utc)
                    await session.commit()

                updated += 1
                att_count = len(detail.get("attachments") or [])
                logger.info(
                    "%s → filer=%s | %d attachment%s",
                    sys_id,
                    (detail.get("filer_name") or "—")[:50],
                    att_count,
                    "s" if att_count != 1 else "",
                )

            except Exception as e:
                errors += 1
                logger.error("%s: %r", sys_id, e)

    finally:
        client.close()

    logger.info("Done. %d updated, %d errors.", updated, errors)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--viasat", action="store_true", help="Only fetch Viasat-related pleadings")
    args = parser.parse_args()
    asyncio.run(main(viasat_only=args.viasat))
