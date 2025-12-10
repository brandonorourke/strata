# apps/ingest/llm_raw.py

import asyncio
import json
import logging

from openai import OpenAI
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from strata_core.db import AsyncSessionLocal
from strata_core.models import NewsArticle

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

client = OpenAI()  # uses OPENAI_API_KEY from env

SYSTEM_PROMPT = """
You are an extraction engine that reads news articles about companies and produces
a compact JSON structure describing the key entities and events.

Return ONLY valid JSON following this schema:

{
  "entities": [
    {
      "canonical_company_name": "string",
      "raw_mentions": ["string", ...],
      "is_primary_entity": true,
      "event_type": "mna_transaction | financing | legal_action | restructuring | performance_update | other",
      "event_description": "string",
      "event_date": "YYYY-MM-DD or null",
      "confidence": 0.0
    }
  ]
}

If no relevant companies or events are found, return: { "entities": [] }.
"""

def build_user_prompt(article: NewsArticle) -> str:
    # You can refine (truncate, etc.) later
    return f"""
Article title: {article.title or ""}

Article text:
{article.clean_text}
"""


async def fetch_pending_articles(session, limit: int = 5) -> list[NewsArticle]:
    stmt = (
        select(NewsArticle)
        .where(NewsArticle.clean_text.is_not(None))
        .where(NewsArticle.llm_raw.is_(None))
        .order_by(NewsArticle.id.asc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


def parse_llm_json(content: str) -> dict | None:
    if not content:
        return None

    text = content.strip()

    # Strip ```json ... ``` fences if present
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].lstrip()

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning("Failed to parse JSON from LLM: %s\nContent (truncated): %s", e, text[:500])
        return None


async def call_llm(system_prompt: str, user_prompt: str) -> dict | None:
    resp = await asyncio.to_thread(
        client.chat.completions.create,
        model="gpt-4.1-mini",  # or whatever you're standardizing on
        messages=[
            {"role": "system", "content": system_prompt.strip()},
            {"role": "user", "content": user_prompt.strip()},
        ],
        temperature=0.0,
    )

    content = resp.choices[0].message.content
    return parse_llm_json(content)


async def process_batch(limit: int = 5) -> int:
    """
    Fetch up to `limit` articles with clean_text and no llm_raw,
    call LLM, and store raw JSON in llm_raw.
    """
    async with AsyncSessionLocal() as session:
        articles = await fetch_pending_articles(session, limit=limit)
        if not articles:
            logger.info("No articles needing LLM enrichment.")
            return 0

        logger.info("Running LLM on %d article(s)", len(articles))
        updated = 0

        for article in articles:
            user_prompt = build_user_prompt(article)
            data = await call_llm(SYSTEM_PROMPT, user_prompt)
            if data is None:
                continue

            article.llm_raw = data
            updated += 1

        try:
            await session.commit()
        except SQLAlchemyError as e:
            logger.error("Commit failed, rolling back: %s", e)
            await session.rollback()
            return 0

        logger.info("Stored llm_raw for %d article(s)", updated)
        return updated


async def main():
    processed = await process_batch(limit=1)
    logger.info("Done. Processed batch size: %d", processed)


if __name__ == "__main__":
    asyncio.run(main())
