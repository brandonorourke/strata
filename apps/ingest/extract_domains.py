# apps/ingest/extract_domains.py

import asyncio
import logging
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import trafilatura
from sqlalchemy import select, exists
from sqlalchemy.exc import SQLAlchemyError

from strata_core.db import AsyncSessionLocal
from strata_core.models import NewsArticle, ArticleDomain

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

_URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
_DENY_DOMAINS = {
    "prnewswire.com",
    "bbc.com",
    "businesswire.com",
    "cnbc.com",
    "youtube.com",
    "reuters.com",
    "freightwaves.com",
    "finance.yahoo.com",
    "truthsocial.com",
    "abcnews.go.com",
    "x.com",
    "twitter.com",
    "facebook.com",
    "linkedin.com",
    "instagram.com",
    "tiktok.com",
    "threads.net",
    "reddit.com",
    "doubleclick.net",
    "googletagmanager.com",
    "google-analytics.com",
    "gstatic.com",
    "scorecardresearch.com",
    "taboola.com",
    "outbrain.com",
    "criteo.com",
    "adnxs.com",
    "facebook.net",
}


def _extract_domains(html: str) -> set[str]:
    if not html:
        return set()

    extracted = None
    try:
        extracted = trafilatura.extract(
            html,
            include_links=True,
            include_images=False,
            include_tables=False,
            include_comments=False,
            no_fallback=True,
        )
    except Exception:
        extracted = None

    text = extracted or html

    domains: set[str] = set()
    for match in _URL_RE.findall(text):
        try:
            parsed = urlparse(match)
        except Exception:
            continue
        netloc = parsed.netloc.lower()
        if not netloc:
            continue
        if netloc.startswith("www."):
            netloc = netloc[4:]
        if "." not in netloc:
            continue
        if netloc in _DENY_DOMAINS:
            continue
        domains.add(netloc)
    return domains


async def fetch_articles_with_html(session, limit: int = 50) -> list[NewsArticle]:
    stmt = (
        select(NewsArticle)
        .where(NewsArticle.raw_html.is_not(None))
        .where(NewsArticle.domains_extracted_at.is_(None))
        .where(
            ~exists().where(ArticleDomain.article_id == NewsArticle.id)
        )
        .order_by(NewsArticle.id.asc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def process_batch(limit: int = 50) -> int:
    async with AsyncSessionLocal() as session:
        articles = await fetch_articles_with_html(session, limit=limit)
        if not articles:
            logger.info("No articles needing domain extraction.")
            return 0

        inserted = 0
        for article in articles:
            domains = _extract_domains(article.raw_html or "")
            for domain in domains:
                session.add(ArticleDomain(article_id=article.id, domain=domain))
                inserted += 1
            article.domains_extracted_at = datetime.now(timezone.utc)

        try:
            await session.commit()
        except SQLAlchemyError as e:
            logger.error("Commit failed, rolling back: %s", e)
            await session.rollback()
            return 0

        logger.info("Inserted %d article_domains", inserted)
        return inserted


async def main():
    inserted = await process_batch(limit=50)
    logger.info("Done. Inserted %d domains.", inserted)


if __name__ == "__main__":
    asyncio.run(main())
