# apps/ingest/clean_text.py

import asyncio
import logging

import trafilatura
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from strata_core.db import AsyncSessionLocal
from strata_core.models import NewsArticle

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


def extract_main_text(html: str) -> str | None:
    """
    Use trafilatura to extract the main article text from stored HTML.
    No network involved.
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
            no_fallback=True,
        )
    except Exception as e:
        logger.warning("trafilatura.extract failed: %s", e)
        return None

    if not text:
        return None

    text = text.strip()
    if not text:
        return None

    if len(text) > 50_000:
        text = text[:50_000]

    return text


async def fetch_articles_needing_clean_text(
    session,
    limit: int = 20,
) -> list[NewsArticle]:
    stmt = (
        select(NewsArticle)
        .where(NewsArticle.clean_text.is_(None))
        .where(NewsArticle.raw_html.is_not(None))
        .order_by(NewsArticle.id.asc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def process_batch(limit: int = 20) -> int:
    """
    For up to `limit` articles where raw_html IS NOT NULL
    and clean_text IS NULL, extract main text and store in clean_text.

    No network calls here.
    """
    async with AsyncSessionLocal() as session:
        articles = await fetch_articles_needing_clean_text(session, limit=limit)
        if not articles:
            logger.info("No articles need clean_text.")
            return 0

        logger.info("Extracting clean_text for %d article(s)", len(articles))
        updated_count = 0

        for article in articles:
            text = extract_main_text(article.raw_html)
            if not text:
                logger.warning("No clean text extracted for [%s]", article.id)
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
    await process_batch(limit=20)


if __name__ == "__main__":
    asyncio.run(main())
