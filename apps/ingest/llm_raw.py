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
You are an analyst that extracts structured information about private and public companies from unstructured news articles.

Your tasks:
1. Identify all companies and key entities mentioned.
2. Identify the primary company or companies—the ones the article is materially about.
3. Identify secondary or contextual entities that are mentioned but not the main focus.
4. Normalize company names to canonical form when possible.
5. Classify the event type.
6. For M&A / portfolio events, identify each entity's role in the transaction.
7. Only output valid JSON. No commentary, no explanations.

Definitions:

- Primary entities:
  - Are in the headline or lead paragraphs, OR
  - Undergo a material corporate event (financing, bankruptcy, layoffs, leadership change, legal/regulatory action, acquisition/disposition/M&A, major performance update).

- Context entities:
  - Vendors, partners, prior employers, investors, platforms, or comparison companies that are not the main subject of the article.

If information is unknown, return null rather than guessing, except:
- You may infer obvious things (e.g., that a named buyer in an acquisition is a "buyer").

Your output must always be valid JSON and conform strictly to the schema provided in the user message.
"""

def build_user_prompt(article: NewsArticle) -> str:
    # You can refine (truncate, etc.) later
    return f"""
Extract structured information from the following article.

ARTICLE TITLE: {article.title or ""}

ARTICLE:
{article.clean_text}


Return JSON with the following schema:

{
  "entities": [
    {
      "canonical_company_name": string | null,
      "raw_mentions": [string],
      "is_primary_entity": boolean,
      "event_type": string | null,
      "transaction_role": string | null,
      "event_description": string | null,
      "event_date": string | null,
      "confidence": float
    }
  ]
}

Field requirements:

- canonical_company_name:
  - The normalized, canonical name of the company or entity, if it can be inferred (e.g., "KKR & Co. Inc.", "Hyatt Regency Tokyo").
  - If unclear, set to the clearest form mentioned in the article.
  - If you cannot determine a canonical name, set to null.

- raw_mentions:
  - All distinct textual forms used in the article for this entity (e.g., ["KKR", "KKR & Co."]).

- is_primary_entity:
  - true if this entity is one of the main subjects of the article (headline/lead focus or undergoing a material event).
  - false if it is only a contextual or secondary mention (e.g., prior employer, investor, comparison company, vendor).

- event_type:
  - One of:
    [
      "financing",
      "bankruptcy",
      "layoffs",
      "leadership_change",
      "legal_action",
      "acquisition",
      "disposition",
      "mna_transaction",
      "regulatory",
      "performance_update",
      "other"
    ]
  - Choose the single best label for the main event affecting this entity in this article.
  - Use:
    - "acquisition" when the entity is clearly involved in buying a company or asset.
    - "disposition" when the entity is clearly selling a company or asset (e.g., portfolio exit, asset sale).
    - "mna_transaction" when there is clearly an M&A-related transaction but the direction (buy vs sell) is ambiguous or not clearly described.
  - "legal_action" for enforcement actions, settlements, lawsuits, or regulatory charges.
  - "regulatory" for non-enforcement regulatory decisions, approvals, rule changes, or supervisory actions.
  - "performance_update" for earnings, guidance changes, operational performance metrics, or major business KPIs.
  - Use "other" if none of the above fits.

- transaction_role:
  - Only set this field for entities involved in M&A / portfolio / transaction events
    (i.e., when event_type is "acquisition", "disposition", or "mna_transaction").
  - One of: ["buyer", "seller", "target", "advisor", "other"] or null.
  - Examples:
    - The acquiring company -> "buyer"
    - The selling sponsor or owner -> "seller"
    - The company or asset being acquired/sold -> "target"
    - Investment banks, brokers, or real estate services firms running the sale -> "advisor"
    - If involved but not fitting the above, use "other".
  - If the entity is not part of any M&A/transaction event, set transaction_role to null.

- event_description:
  - 1–3 sentences in plain English briefly describing the event for this entity in the context of this article.
  - Focus on the core action and its financial/corporate significance.
  - Example: "KKR led a consortium that sold its stake in the Hyatt Regency Tokyo for over $800 million."

- event_date:
  - Normalize the date of the event as precisely as the article allows.
  - Rules:
    - If an exact date is provided, return "YYYY-MM-DD".
    - If only month and year are given, return "YYYY-MM".
    - If only year is given, return "YYYY".
    - If the timing is vague or cannot be determined, return null.
    - Do NOT invent or guess a specific day-of-month when it is not stated.

- confidence:
  - A float between 0.0 and 1.0 representing how confident you are that this entity and event_type/event_description pairing is correct.
  - Higher = more confident.

Additional rules:

- If the article contains multiple unrelated mini-stories (e.g., a roundup), you may mark multiple entities as is_primary_entity = true, one per distinct story anchor.
- Always include all entities that are materially involved in a transaction or legal/regulatory event, even if they are not primary.
- Exclude purely generic mentions (e.g., "Wall Street", "the market") unless they refer to a specific company or entity.

Only output JSON that strictly conforms to the schema above. Do not include any commentary, explanation, or text outside the JSON.



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
