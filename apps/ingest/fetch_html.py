# apps/ingest/fetch_html.py

import asyncio
import logging
import random

import httpx
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from strata_core.db import AsyncSessionLocal
from strata_core.models import NewsArticle

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.8",
}


async def polite_sleep():
    await asyncio.sleep(random.uniform(1.0, 3.0))


async def fetch_html(client: httpx.AsyncClient, url: str) -> str | None:
    try:
        resp = await client.get(url, timeout=10.0, headers=DEFAULT_HEADERS)
    except httpx.HTTPError as e:
        logger.warning("HTTP error fetching %s: %s", url, e)
        return None

    if resp.status_code != 200:
        logger.warning("Non-200 status for %s: %s", url, resp.status_code)
        return None

    return resp.text


async def fetch_articles_needing_html(session, limit: int = 20) -> list[NewsArticle]:
    stmt = (
        select(NewsArticle)
        .where(NewsArticle.raw_html.is_(None))
        .where(NewsArticle.url.is_not(None))
        .order_by(NewsArticle.id.asc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def process_batch(limit: int = 20) -> int:
    """
    For up to `limit` articles with raw_html IS NULL,
    fetch HTML over the network and populate raw_html.
    Does NOT touch clean_text.
    """
    async with AsyncSessionLocal() as session:
        articles = await fetch_articles_needing_html(session, limit=limit)
        if not articles:
            logger.info("No articles need HTML.")
            return 0

        logger.info("Fetching HTML for %d article(s)", len(articles))
        updated_count = 0

        async with httpx.AsyncClient(follow_redirects=True) as client:
            for article in articles:
                await polite_sleep()
                logger.info("Fetching HTML for [%s] %s", article.id, article.url)
                html = await fetch_html(client, article.url)
                if not html:
                    continue

                article.raw_html = html
                updated_count += 1

        try:
            await session.commit()
        except SQLAlchemyError as e:
            logger.error("Error committing raw_html updates: %s", e)
            await session.rollback()
            return 0

        logger.info("Stored raw_html for %d article(s)", updated_count)
        return updated_count


async def main():
    await process_batch(limit=20)


if __name__ == "__main__":
    asyncio.run(main())
