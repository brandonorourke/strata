# apps/ingest/fetch_icfs_notice_documents.py
#
# Fetches the actual document text for icfs_public_notices that have a da_number, via
# the direct https://docs.fcc.gov/public/attachments/DA-{da_number}A1.txt pattern
# (confirmed empirically, 5/5 in testing). docs.fcc.gov is a plain static-file host with
# no bot mitigation; www.fcc.gov is a different story (confirmed: Akamai-style HTTP/2-level
# blocking of non-interactive clients, including headless Chromium via Playwright — not
# just curl/httpx — so the original plan of navigating the www.fcc.gov/edocs search-results
# page to find the doc link is shelved). This means only notices with da_number (~56% of
# the table, confirmed empirically) are fetchable — report-number-only notices stay
# unresolved; there's no known workaround for those.
#
# docs.fcc.gov returns a soft-404 for an invalid document id — HTTP 200 with an HTML
# "404 - The page not found" body, not a real 404 status. Must check content, not status.

import asyncio
import logging
import os
from datetime import datetime, timezone

import httpx
from sqlalchemy import select, and_

from strata_core.db import AsyncSessionLocal
from strata_core.models import IcfsPublicNotice

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

USER_AGENT = "Mozilla/5.0 (compatible; StrataBot/0.1; contact: admin@example.com)"
REQUEST_DELAY_SECONDS = 1.0
SOFT_404_MARKER = "you are trying to retrieve is invalid"


def _document_url(da_number: str) -> str:
    return f"https://docs.fcc.gov/public/attachments/DA-{da_number}A1.txt"


async def fetch_notice_document(client: httpx.Client, notice: IcfsPublicNotice) -> tuple[str | None, str | None]:
    """Returns (document_url, document_text) — document_text is None if it's a soft-404."""
    doc_url = _document_url(notice.da_number)
    resp = client.get(doc_url)
    resp.raise_for_status()
    if SOFT_404_MARKER in resp.text:
        return doc_url, None
    return doc_url, resp.text


async def process_batch(limit: int = 50) -> int:
    client = httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30.0, follow_redirects=True)
    fetched_count = 0
    try:
        async with AsyncSessionLocal() as session:
            stmt = (
                select(IcfsPublicNotice)
                .where(IcfsPublicNotice.document_fetched_at.is_(None))
                .where(and_(IcfsPublicNotice.da_number.is_not(None), IcfsPublicNotice.da_number != ""))
                .order_by(IcfsPublicNotice.id.asc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            notices = list(result.scalars().all())

            if not notices:
                logger.info("No icfs_public_notices with a da_number needing document fetch.")
                return 0

            for notice in notices:
                try:
                    doc_url, doc_text = await fetch_notice_document(client, notice)
                except httpx.HTTPError as e:
                    # Transient/network failure — leave document_fetched_at unset so this
                    # notice is retried on the next run, rather than treating it as a
                    # confirmed "no document" result.
                    logger.error("Fetch failed for notice %s: %r", notice.number, e)
                    await session.commit()
                    await asyncio.sleep(REQUEST_DELAY_SECONDS)
                    continue

                notice.document_url = doc_url
                notice.document_text = doc_text
                notice.document_fetched_at = datetime.now(timezone.utc)
                if doc_text:
                    fetched_count += 1
                    logger.info("Fetched document for notice %s (%d chars)", notice.number, len(doc_text))
                else:
                    logger.info("Soft-404 (no document) for notice %s", notice.number)

                await session.commit()
                await asyncio.sleep(REQUEST_DELAY_SECONDS)
    finally:
        client.close()

    logger.info("Done. Fetched %d documents.", fetched_count)
    return fetched_count


async def main():
    limit_env = os.getenv("ICFS_NOTICE_FETCH_LIMIT")
    limit = int(limit_env) if limit_env else 50
    await process_batch(limit=limit)


if __name__ == "__main__":
    asyncio.run(main())
