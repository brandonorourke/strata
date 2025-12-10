import asyncio
import logging
from datetime import datetime, timezone

import httpx
import trafilatura
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from stratacore.db import AsyncSessionLocal
from stratacore.models import NewsArticle

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


# ---------- HTML → clean text via trafilatura ----------

def extract_main_text(html: str) -> str | None:
    """
    Use trafilatura to extract the main article text.
    This is intentionally simple for MVP.
    """
    if not html:
        return None

    try:
        text = trafilatura.extract(
            html,
            include_links=False,
            include_images=False,
            include_tables=False,
            include_comments=False,
            no_fallback=True,  # return None instead of junk if it can't extract
        )
    except Exception as e:
        logger.warning("trafilatura.extract failed: %s", e)
        return None

    if not text:
        return None

    # Normalize a bit and cap very long pages
    text = text.strip()
    if not text:
        return None

    if len(text) > 50_000:
        text = text[:50_000]

    return text


async def fetch_html(client: httpx.AsyncClient, url: str) -> str | None:
    try:
        resp = await client.get(url, timeout=10.0)
        if resp.status_code != 200:
            logger.warning("Non-200 status for %s: %s", url, resp.status_code)
            return None
        # trafilatura expects text/html, the raw response body is fine
        return resp.text
    except httpx.HTTPError as e:
        logger.warning("HTTP error fetching %s: %s", url, e)
        return None


# ---------- DB helpers ----------

async def fetch_pending_articles(session, limit: int = 20) -> list[NewsArticle]:
    stmt = (
        select(NewsArticle)
        .where(NewsArticle.clean_text.is_(None))
        .order_by(NewsArticle.id.asc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def process_batch(limit: int = 20) -> int:
    """
    Fetch up to `limit` articles without clean_text, fetch/parse HTML,
    and populate clean_text + text_extracted_at.
    Returns number of articles successfully updated.
    """
    async with AsyncSessionLocal() as session:
        articles = await fetch_pending_articles(session, limit=limit)
        if not articles:
            logger.info("No pending articles to process.")
            return 0

        logger.info("Processing %d articles for clean_text extraction", len(articles))

        updated_count = 0

        async with httpx.AsyncClient(follow_redirects=True) as client:
            for article in articles:
                if not article.url:
                    logger.warning("Article %s has no URL, skipping", article.id)
                    continue

                logger.info("Fetching HTML for [%s] %s", article.id, article.url)
                html = await fetch_html(client, article.url)
                if not html:
                    continue

                text = extract_main_text(html)
                if not text:
                    logger.warning(
                        "No clean text extracted for [%s] %s",
                        article.id,
                        article.url,
                    )
                    continue

                article.clean_text = text
                updated_count += 1

        try:
            await session.commit()
        except SQLAlchemyError as e:
            logger.error("Error committing clean_text updates: %s", e)
            await session.rollback()
            return 0

        logger.info("Updated clean_text for %d article(s)", updated_count)
        return updated_count


async def main():
    # Single batch for now; later this becomes a scheduled job.
    await process_batch(limit=20)


if __name__ == "__main__":
    asyncio.run(main())
