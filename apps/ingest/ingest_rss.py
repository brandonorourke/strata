# apps/ingest/ingest_rss.py

import asyncio
import os
from urllib.parse import urlparse
from datetime import datetime, timezone
from typing import Dict, List, Tuple

import feedparser
import httpx
from sqlalchemy import select

from strata_core.db import AsyncSessionLocal
from strata_core.models import NewsArticle, NewsSource

from dotenv import load_dotenv
load_dotenv()

RSS_FEEDS: List[Tuple[NewsSource, str]] = [
    (NewsSource.FREIGHTWAVES, "https://www.freightwaves.com/feed"),
    (NewsSource.SEC_PRESS_RELEASES, "https://www.sec.gov/news/pressreleases.rss"),
    (NewsSource.SEC_LITIGATION_RELEASES, "https://www.sec.gov/enforcement-litigation/litigation-releases/rss"),
    (NewsSource.SEC_ADMIN_PROCEEDINGS, "https://www.sec.gov/enforcement-litigation/administrative-proceedings/rss"),
]

DEFAULT_RSS_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate",
}

SEC_RSS_HEADERS = {
    "User-Agent": os.getenv(
        "SEC_USER_AGENT",
        "StrataBot/0.1 (contact: admin@example.com)",
    ),
    "Accept": "application/rss+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Host": "www.sec.gov",
}


def _rss_headers(feed_url: str) -> dict:
    host = urlparse(feed_url).hostname or ""
    if host.endswith("sec.gov"):
        return SEC_RSS_HEADERS
    return DEFAULT_RSS_HEADERS


def _parse_published(entry) -> datetime | None:
    """
    Convert feedparser's published_parsed (struct_time) to a timezone-aware datetime.
    If missing, return None.
    """
    t = getattr(entry, "published_parsed", None) or entry.get("published_parsed")
    if not t:
        print("No published_parsed found.")
        return None
    
    print(f"Parsed time struct: {t}")

    # feedparser gives a time.struct_time; map first 6 fields
    return datetime(
        year=t.tm_year,
        month=t.tm_mon,
        day=t.tm_mday,
        hour=t.tm_hour,
        minute=t.tm_min,
        second=t.tm_sec,
        tzinfo=timezone.utc,
    )


async def ingest_one_feed(session, source: NewsSource, feed_url: str) -> int:
    """
    Fetch a single RSS feed and insert any new articles into news_articles.
    Returns number of new rows inserted.
    """
    try:
        resp = httpx.get(feed_url, headers=_rss_headers(feed_url), timeout=15.0)
        resp.raise_for_status()
    except Exception as e:
        print(f"Error fetching feed {feed_url}: {e!r}")
        return 0

    parsed = feedparser.parse(resp.text)
    if parsed.bozo and not parsed.entries:
        print(f"Bozo feed with no entries for {feed_url}: {parsed.bozo_exception!r}")
        return 0
    if parsed.bozo and parsed.entries:
        print(f"Bozo feed but entries present for {feed_url}: {parsed.bozo_exception!r}")

    new_count = 0

    print(f"Entry count: {len(parsed.entries)}")

    for entry in parsed.entries:
        url = getattr(entry, "link", None) or entry.get("link")
        title = getattr(entry, "title", None) or entry.get("title")

        if not url or not title:
            continue

        # Check if this URL already exists
        existing = await session.execute(
            select(NewsArticle.id).where(NewsArticle.url == url).limit(1)
        )
        if existing.scalar_one_or_none() is not None:
            continue

        published_at = _parse_published(entry)

        print(f"Ingesting new article from {source.value}: {title}")

        article = NewsArticle(
            source=source,
            url=url,
            title=title,
            published_at=published_at,
            # raw_html=None, clean_text=None, processed defaults handled by model defaults
        )
        session.add(article)

        print(f"  -> added article: {title} ({url})")
        new_count += 1

    return new_count


async def main() -> None:
    """
    Entry point: iterate over all configured RSS feeds and ingest new articles.
    """
    if not RSS_FEEDS:
        print("No RSS feeds configured in RSS_FEEDS. Edit ingest_rss.py.")
        return

    async with AsyncSessionLocal() as session:
        total_new = 0
        for source, url in RSS_FEEDS:
            try:
                new_for_source = await ingest_one_feed(session, source, url)
                total_new += new_for_source
                # Commit per-feed to keep transactions bounded
                await session.commit()
                print(f"{source.value}: inserted {new_for_source} new articles.")
                await asyncio.sleep(0.2)
            except Exception as e:
                # Roll back on any error for this feed, move on
                await session.rollback()
                print(f"Error ingesting {source.value} from {url}: {e!r}")

        print(f"Total new articles inserted: {total_new}")


if __name__ == "__main__":
    asyncio.run(main())
