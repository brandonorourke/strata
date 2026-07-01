# apps/ingest/fetch_icfs_filing_details.py
#
# Enriches Viasat SES filings with detail from the ICFS application summary page API.
# Calls /api/now/sp/page?id=ibfs_application_summary&number={file_number} per filing,
# extracts brief_description, grant/expiration dates, action_pn_url, and grant_doc_url
# (the direct download URL for the STA Grant PDF), then writes back to icfs_filings.
#
# Hardcoded to Viasat filings (applicant_name ILIKE '%Viasat%') with detail_fetched_at IS NULL.
# Run after ingest_icfs.py. Respects same 3s delay as the main ingest script.

import asyncio
import logging
import re
import time
from datetime import date, datetime, timezone

import httpx
from sqlalchemy import select

from strata_core.db import AsyncSessionLocal
from strata_core.models import IcfsFiling

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


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _fetch_page(client: httpx.Client, g_ck: str, file_number: str) -> dict | None:
    resp = client.get(
        PAGE_API_URL,
        params={"id": "ibfs_application_summary", "number": file_number},
        headers={"Accept": "application/json", "X-UserToken": g_ck},
    )
    resp.raise_for_status()
    return resp.json().get("result")


def _extract_detail(result: dict) -> dict:
    """
    Walk the ServiceNow page widget tree to extract summary fields and attachment URLs.
    The page response nests data inside containers → rows → columns → widgets.
    We search all widgets: one has data.summary (application fields), another has
    data.all_data (attachment list with download sys_ids).
    """
    summary = None
    attachments = []

    for container in result.get("containers", []):
        for row in container.get("rows", []):
            for col in row.get("columns", []):
                for widget_wrap in col.get("widgets", []):
                    data = (widget_wrap.get("widget") or {}).get("data") or {}
                    if "summary" in data and summary is None:
                        summary = data["summary"]
                    if "all_data" in data:
                        attachments.extend(data["all_data"])

    detail: dict = {}

    if summary:
        detail["brief_description"] = _display(summary.get("brief_application_description"))
        detail["grant_date"] = _parse_date(_display(summary.get("grant_date")))
        detail["expiration_date"] = _parse_date(_display(summary.get("expiration_date")))
        detail["begin_date"] = _parse_date(_display(summary.get("begin_date")))

        pn = summary.get("action_pn_date")
        if isinstance(pn, dict):
            detail["action_pn_url"] = pn.get("url") or None

    # Find the STA Grant attachment — first record whose name/description contains "grant"
    for att in attachments:
        doc_name = (_display(att.get("document_name")) or "").lower()
        desc = (_display(att.get("u_description")) or "").lower()
        if "grant" in doc_name or "grant" in desc:
            sys_id = att.get("sys_id")
            if isinstance(sys_id, dict):
                sys_id = sys_id.get("value") or sys_id.get("display_value")
            if sys_id:
                detail["grant_doc_url"] = (
                    f"https://api-prod.fcc.gov/icfs-attachment/exp/api/v1/{sys_id}"
                )
                break

    return detail


async def main() -> None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(IcfsFiling)
            .where(IcfsFiling.applicant_name.ilike("%Viasat%"))
            .where(IcfsFiling.detail_fetched_at.is_(None))
            .where(IcfsFiling.file_number.isnot(None))
            .order_by(IcfsFiling.submission_date.desc())
        )
        filings = result.scalars().all()
        # Detach scalar values we need before closing session
        pending = [(f.id, f.file_number) for f in filings]

    logger.info("Fetching details for %d Viasat filings with no detail yet", len(pending))
    if not pending:
        return

    client, g_ck = _bootstrap_session()
    updated = 0
    errors = 0

    try:
        for i, (filing_id, file_number) in enumerate(pending):
            if i > 0:
                time.sleep(REQUEST_DELAY_SECONDS)
            try:
                page_result = _fetch_page(client, g_ck, file_number)
                if page_result is None:
                    logger.warning("%s: empty page response", file_number)
                    continue

                detail = _extract_detail(page_result)

                async with AsyncSessionLocal() as session:
                    filing = await session.get(IcfsFiling, filing_id)
                    if filing is None:
                        continue
                    filing.brief_description = detail.get("brief_description")
                    filing.action_pn_url = detail.get("action_pn_url")
                    filing.grant_date = detail.get("grant_date")
                    filing.expiration_date = detail.get("expiration_date")
                    filing.begin_date = detail.get("begin_date")
                    filing.grant_doc_url = detail.get("grant_doc_url")
                    filing.detail_fetched_at = datetime.now(timezone.utc)
                    await session.commit()

                updated += 1
                exp = detail.get("expiration_date")
                logger.info(
                    "%s → %s%s%s",
                    file_number,
                    (detail.get("brief_description") or "—")[:70],
                    f" | exp {exp}" if exp else "",
                    " | grant PDF ✓" if detail.get("grant_doc_url") else "",
                )

            except Exception as e:
                errors += 1
                logger.error("%s: %r", file_number, e)

    finally:
        client.close()

    logger.info("Done. %d updated, %d errors.", updated, errors)


if __name__ == "__main__":
    asyncio.run(main())
