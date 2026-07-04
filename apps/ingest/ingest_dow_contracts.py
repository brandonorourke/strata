# apps/ingest/ingest_dow_contracts.py
#
# Discovers and stores raw DoW daily contract releases.
# Fetches the contracts index at war.gov, finds new article URLs,
# fetches each article, and stores the raw text in dow_contract_releases.
#
# war.gov is behind Akamai TLS fingerprinting — requires curl_cffi with
# Chrome impersonation. Plain httpx/requests will get 403.
#
# Modes:
#   incremental (default): fetches index page 1 only, stops when all articles
#     on the page are already in the DB. Use for daily monitoring.
#   backfill: walks pages until no new articles are found. Use once to
#     populate historical releases.

import argparse
import asyncio
import hashlib
import logging
import re
import time
from datetime import datetime, timezone, date

from curl_cffi import requests as cffi_requests
from sqlalchemy import select

from strata_core.db import AsyncSessionLocal
from strata_core.models import DowContractRelease

from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

INDEX_URL = "https://www.war.gov/news/contracts/"
REQUEST_DELAY = 2.0


def _fetch(url: str) -> str:
    resp = cffi_requests.get(url, impersonate="chrome", timeout=30)
    resp.raise_for_status()
    return resp.text


def _discover_articles(html: str) -> list[dict]:
    """Extract article metadata from index page custom data attributes."""
    pattern = re.compile(
        r'article-id="(\d+)"\s+article-title="([^"]+)"\s+article-alt="[^"]*"\s+article-url="([^"]+)"'
    )
    articles = []
    for article_id, title, url in pattern.findall(html):
        articles.append({
            "article_id": article_id,
            "title": title,
            "url": url,
            "release_date": _parse_release_date(title),
        })
    return articles


def _parse_release_date(title: str) -> date | None:
    """Parse 'Contracts for July 2, 2026' or 'Contracts For Jun. 8, 2021' -> date."""
    match = re.search(r"(\w+\.?\s+\d+,\s+\d{4})", title)
    if not match:
        return None
    raw = re.sub(r"\s+", " ", match.group(1).replace(".", ""))
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    logger.warning("Could not parse release_date from title: %r", title)
    return None


def _extract_text(html: str) -> str:
    """Strip HTML tags, preserve paragraph breaks and section headers."""
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"</(p|div|li|h[1-6])>", "\n", html, flags=re.IGNORECASE)
    html = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    html = re.sub(r"<[^>]+>", "", html)
    html = (html.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
                .replace("&nbsp;", " ").replace("&#39;", "'").replace("&quot;", '"'))
    lines = [l.strip() for l in html.splitlines() if l.strip()]
    return "\n\n".join(lines).strip()


async def _store_article(article: dict) -> None:
    html = _fetch(article["url"])
    raw_text = _extract_text(html)
    content_hash = hashlib.sha256(raw_text.encode()).hexdigest()
    async with AsyncSessionLocal() as session:
        row = DowContractRelease(
            article_id=article["article_id"],
            url=article["url"],
            title=article["title"],
            release_date=article["release_date"],
            first_seen_at=datetime.now(timezone.utc),
            fetched_at=datetime.now(timezone.utc),
            raw_text=raw_text,
            raw_html=html,
            content_hash=content_hash,
        )
        session.add(row)
        await session.commit()
    logger.info("Stored %s — %s (%d chars)", article["article_id"], article["title"], len(raw_text))


async def main(mode: str = "incremental") -> None:
    async with AsyncSessionLocal() as session:
        existing = set(
            r[0] for r in (await session.execute(select(DowContractRelease.article_id))).all()
        )

    fetched = errors = 0
    page = 1

    while True:
        url = INDEX_URL if page == 1 else f"{INDEX_URL}?Page={page}"
        logger.info("Fetching index page %d", page)
        index_html = _fetch(url)
        articles = _discover_articles(index_html)

        if not articles:
            logger.info("No articles found on page %d — stopping", page)
            break

        new_articles = [a for a in articles if a["article_id"] not in existing]
        logger.info("Page %d: %d articles, %d new", page, len(articles), len(new_articles))

        for i, article in enumerate(new_articles):
            if i > 0 or page > 1:
                time.sleep(REQUEST_DELAY)
            try:
                await _store_article(article)
                existing.add(article["article_id"])
                fetched += 1
            except Exception as e:
                errors += 1
                logger.error("Failed %s: %r", article["article_id"], e)

        if mode == "incremental":
            break

        if not new_articles and page > 1:
            # Backfill: hit a page where everything is already known — caught up
            break

        page += 1
        time.sleep(REQUEST_DELAY)

    logger.info("Done. %d fetched, %d errors.", fetched, errors)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["incremental", "backfill"], default="incremental")
    args = parser.parse_args()
    asyncio.run(main(mode=args.mode))
