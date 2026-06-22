# apps/ingest/fetch_html.py

import asyncio
import io
import logging
import random
from urllib.parse import urlparse

import httpx
from pypdf import PdfReader
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

SEC_HEADERS = {
    "User-Agent": "StrataBot/0.1 (contact: admin@example.com)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.8",
}


def _headers_for_url(url: str) -> dict:
    host = urlparse(url).hostname or ""
    if host.endswith("sec.gov"):
        return SEC_HEADERS
    return DEFAULT_HEADERS


async def polite_sleep(url: str):
    host = urlparse(url).hostname or ""
    if host.endswith("sec.gov"):
        await asyncio.sleep(random.uniform(1.5, 3.5))
        return
    await asyncio.sleep(random.uniform(1.0, 3.0))


async def fetch_content(client: httpx.AsyncClient, url: str) -> httpx.Response | None:
    try:
        resp = await client.get(url, timeout=15.0, headers=_headers_for_url(url))
    except httpx.HTTPError as e:
        logger.warning("HTTP error fetching %s: %s", url, e)
        return None

    if resp.status_code != 200:
        logger.warning("Non-200 status for %s: %s", url, resp.status_code)
        return None

    return resp


def extract_pdf_text(content: bytes) -> str | None:
    try:
        reader = PdfReader(io.BytesIO(content))
    except Exception as e:
        logger.warning("Failed to read PDF: %s", e)
        return None

    chunks = []
    for page in reader.pages:
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        if text:
            chunks.append(text)

    if not chunks:
        return None

    text = "\n\n".join(chunks).strip()
    return text or None


async def fetch_articles_needing_html(session, limit: int = 20) -> list[NewsArticle]:
    stmt = (
        select(NewsArticle)
        .where(NewsArticle.raw_html.is_(None))
        .where(NewsArticle.clean_text.is_(None))  # Skip PDFs or items already resolved to clean_text
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
                await polite_sleep(article.url)
                logger.info("Fetching content for [%s] %s", article.id, article.url)
                resp = await fetch_content(client, article.url)
                if not resp:
                    continue

                content_type = resp.headers.get("content-type", "").lower()
                if "application/pdf" in content_type or article.url.lower().endswith(".pdf"):
                    text = extract_pdf_text(resp.content)
                    if not text:
                        continue
                    article.clean_text = text
                    updated_count += 1
                    continue

                article.raw_html = resp.text
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
    await process_batch(limit=50)


if __name__ == "__main__":
    asyncio.run(main())
