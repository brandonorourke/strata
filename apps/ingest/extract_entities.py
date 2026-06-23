# apps/ingest/extract_entities.py

import asyncio
import logging
import re
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select, exists, and_
from sqlalchemy.exc import SQLAlchemyError

from strata_core.db import AsyncSessionLocal
from strata_core.models import NewsArticle, ExtractedEntity, ExtractedEvent
from strata_core.normalize import normalize_legal_name, normalize_loose_name

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

_FULL_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _parse_event_date(value: Any) -> date | None:
    if not value or not isinstance(value, str):
        return None
    if not _FULL_DATE_RE.match(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _extract_entities_payload(llm_raw: dict | None) -> list[dict]:
    if not llm_raw or not isinstance(llm_raw, dict):
        return []
    entities = llm_raw.get("entities")
    if not isinstance(entities, list):
        return []
    return [e for e in entities if isinstance(e, dict)]


async def _get_or_create_entity(
    session,
    source_id: int,
    canonical_name: str,
    first_seen_at,
    entity_type: str | None,
    jurisdiction: str | None,
    source_type: str = "news_article",
):
    legal_name = normalize_legal_name(canonical_name)
    if not legal_name:
        return None

    stmt = (
        select(ExtractedEntity)
        .where(ExtractedEntity.source_type == source_type)
        .where(ExtractedEntity.source_id == source_id)
        .where(ExtractedEntity.legal_name_normalized == legal_name)
        .limit(1)
    )
    result = await session.execute(stmt)
    entity = result.scalar_one_or_none()
    if entity:
        if entity.entity_type is None and entity_type:
            entity.entity_type = entity_type
        if entity.jurisdiction is None and jurisdiction:
            entity.jurisdiction = jurisdiction
        if first_seen_at and (entity.last_seen_at is None or first_seen_at > entity.last_seen_at):
            entity.last_seen_at = first_seen_at
        return entity

    entity = ExtractedEntity(
        source_type=source_type,
        source_id=source_id,
        extracted_name=canonical_name,
        entity_type=entity_type,
        jurisdiction=jurisdiction,
        legal_name_normalized=legal_name,
        loose_name_normalized=normalize_loose_name(canonical_name),
        first_seen_at=first_seen_at,
        last_seen_at=first_seen_at,
    )
    session.add(entity)
    return entity


async def process_article(session, article: NewsArticle) -> int:
    entities_payload = _extract_entities_payload(article.llm_raw)
    if not entities_payload:
        article.entities_extracted_at = datetime.now(timezone.utc)
        return 0

    inserted = 0
    for payload in entities_payload:
        canonical_name = payload.get("entity_name") or payload.get("canonical_company_name") or None  # A previous prompt version used canonical_company_name for the field name
        if not canonical_name:
            raw_mentions = payload.get("raw_mentions") or []
            if raw_mentions and isinstance(raw_mentions, list):
                canonical_name = raw_mentions[0]
        if not canonical_name or not isinstance(canonical_name, str):
            continue

        fingerprint = payload.get("fingerprint") or {}
        if not isinstance(fingerprint, dict):
            fingerprint = {}

        entity = await _get_or_create_entity(
            session,
            article.id,
            canonical_name,
            article.published_at,
            payload.get("entity_type"),
            payload.get("jurisdiction"),
        )
        if entity is None:
            continue

        exists_stmt = select(ExtractedEvent.id).where(
            and_(
                ExtractedEvent.source_type == "news_article",
                ExtractedEvent.source_id == article.id,
                ExtractedEvent.entity_id == entity.id,
            )
        ).limit(1)
        already = await session.execute(exists_stmt)
        if already.scalar_one_or_none() is not None:
            continue

        event = ExtractedEvent(
            source_type="news_article",
            source_id=article.id,
            entity_id=entity.id,
            extracted_name=canonical_name,
            is_primary_entity=bool(payload.get("is_primary_entity")),
            event_type=payload.get("event_type"),
            transaction_role=payload.get("transaction_role"),
            event_date=_parse_event_date(payload.get("event_date")),
            event_description=payload.get("event_description"),
            confidence=payload.get("confidence"),
        )
        session.add(event)
        inserted += 1

        if entity.hq_country is None:
            entity.hq_country = fingerprint.get("hq_country")
        if entity.hq_region is None:
            entity.hq_region = fingerprint.get("hq_region")

    article.entities_extracted_at = datetime.now(timezone.utc)
    return inserted


async def fetch_articles_with_llm(session, limit: int = 20) -> list[NewsArticle]:
    stmt = (
        select(NewsArticle)
        .where(NewsArticle.llm_raw.is_not(None))
        .where(NewsArticle.entities_extracted_at.is_(None))
        .where(
            ~exists().where(
                and_(
                    ExtractedEvent.source_type == "news_article",
                    ExtractedEvent.source_id == NewsArticle.id,
                )
            )
        )
        .order_by(NewsArticle.id.asc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def process_batch(limit: int = 20) -> int:
    async with AsyncSessionLocal() as session:
        articles = await fetch_articles_with_llm(session, limit=limit)
        if not articles:
            logger.info("No articles needing entity extraction.")
            return 0

        total_inserted = 0
        for article in articles:
            inserted = await process_article(session, article)
            total_inserted += inserted

        try:
            await session.commit()
        except SQLAlchemyError as e:
            logger.error("Commit failed, rolling back: %s", e)
            await session.rollback()
            return 0

        logger.info("Inserted %d extracted_events", total_inserted)
        return total_inserted


async def main():
    inserted = await process_batch(limit=50)
    logger.info("Done. Inserted %d event rows.", inserted)


if __name__ == "__main__":
    asyncio.run(main())
