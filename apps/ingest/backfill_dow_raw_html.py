# apps/ingest/backfill_dow_raw_html.py
#
# Re-fetches war.gov article pages for existing dow_contract_releases rows
# that are missing raw_html, and stores the HTML + re-derives raw_text.
#
# Run once after applying migration 0032_dow_raw_html.sql.
# Safe to interrupt and re-run — skips rows that already have raw_html.

import asyncio
import hashlib
import logging
import time

from sqlalchemy import select

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from strata_core.db import AsyncSessionLocal
from strata_core.models import DowContractRelease
from ingest_dow_contracts import _fetch, _extract_text

from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

REQUEST_DELAY = 1.5


async def main() -> None:
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(DowContractRelease)
            .where(DowContractRelease.raw_html.is_(None))
            .order_by(DowContractRelease.release_date.desc())
        )).scalars().all()

    logger.info("%d rows need raw_html backfill", len(rows))
    ok = errors = 0

    for i, row in enumerate(rows):
        if i > 0:
            time.sleep(REQUEST_DELAY)
        try:
            html = _fetch(row.url)
            raw_text = _extract_text(html)
            content_hash = hashlib.sha256(raw_text.encode()).hexdigest()
            async with AsyncSessionLocal() as session:
                r = await session.get(DowContractRelease, row.id)
                r.raw_html = html
                r.raw_text = raw_text
                r.content_hash = content_hash
                await session.commit()
            ok += 1
            if ok % 50 == 0:
                logger.info("Progress: %d / %d", ok, len(rows))
        except Exception as e:
            errors += 1
            logger.error("Failed id=%d url=%s: %r", row.id, row.url, e)

    logger.info("Done. %d updated, %d errors.", ok, errors)


if __name__ == "__main__":
    asyncio.run(main())
