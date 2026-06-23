# apps/ingest/link_entities.py

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select, and_, exists
from sqlalchemy.exc import SQLAlchemyError

from strata_core.db import AsyncSessionLocal
from strata_core.models import (
    ExtractedEntity,
    CanonicalEntity,
    EntityLink,
    ArticleDomain,
)
from strata_core.normalize import normalize_legal_name, normalize_loose_name

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

_ALLOWED_ENTITY_TYPES = {"operating_company", "financial_sponsor", "lender"}


async def _find_confirmed_canonical_by_cluster(
    session,
    legal_name: str,
    entity_type: str,
    hq_country: str,
    hq_region: str,
):
    filters = [
        CanonicalEntity.legal_name_normalized == legal_name,
        CanonicalEntity.entity_type == entity_type,
        CanonicalEntity.confirmed_domain.is_not(None),
        CanonicalEntity.hq_country == hq_country,
        CanonicalEntity.hq_region == hq_region,
    ]

    stmt = select(CanonicalEntity).where(and_(*filters)).limit(1)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def _find_confirmed_canonical_by_domain(
    session,
    legal_name: str,
    entity_type: str,
    article_id: int,
):
    # ArticleDomain is extracted from news_articles.raw_html specifically — there's
    # nothing to match for entities sourced from a non-news_article table.
    if article_id is None:
        return None

    stmt = (
        select(CanonicalEntity)
        .join(ArticleDomain, ArticleDomain.domain == CanonicalEntity.confirmed_domain)
        .where(
            and_(
                CanonicalEntity.legal_name_normalized == legal_name,
                CanonicalEntity.entity_type == entity_type,
                CanonicalEntity.confirmed_domain.is_not(None),
                ArticleDomain.article_id == article_id,
            )
        )
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def _find_provisional_cluster(
    session,
    legal_name: str,
    entity_type: str,
    hq_country: str,
    hq_region: str,
):
    filters = [
        CanonicalEntity.legal_name_normalized == legal_name,
        CanonicalEntity.entity_type == entity_type,
        CanonicalEntity.confirmed_domain.is_(None),
        CanonicalEntity.hq_country == hq_country,
        CanonicalEntity.hq_region == hq_region,
    ]

    stmt = select(CanonicalEntity).where(and_(*filters)).limit(1)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def _create_canonical(session, extracted: ExtractedEntity) -> CanonicalEntity:
    canonical = CanonicalEntity(
        canonical_name=extracted.extracted_name,
        entity_type=extracted.entity_type,
        legal_name_normalized=extracted.legal_name_normalized
        or normalize_legal_name(extracted.extracted_name),
        loose_name_normalized=extracted.loose_name_normalized
        or normalize_loose_name(extracted.extracted_name),
        jurisdiction=extracted.jurisdiction,
        hq_country=extracted.hq_country,
        hq_region=extracted.hq_region,
    )
    session.add(canonical)
    await session.flush()
    return canonical


async def _create_link(
    session,
    extracted: ExtractedEntity,
    canonical: CanonicalEntity,
    confidence: float,
    method: str,
):
    if canonical.id is None:
        await session.flush()
    link = EntityLink(
        extracted_entity_id=extracted.id,
        canonical_entity_id=canonical.id,
        link_confidence=confidence,
        link_method=method,
        created_at=datetime.now(timezone.utc),
    )
    session.add(link)
    return link


async def fetch_unlinked_entities(session, limit: int = 200) -> list[ExtractedEntity]:
    stmt = (
        select(ExtractedEntity)
        .where(
            ~exists().where(EntityLink.extracted_entity_id == ExtractedEntity.id)
        )
        .order_by(ExtractedEntity.id.asc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def process_batch(limit: int = 200) -> int:
    async with AsyncSessionLocal() as session:
        extracted_entities = await fetch_unlinked_entities(session, limit=limit)
        if not extracted_entities:
            logger.info("No unlinked extracted_entities.")
            return 0

        linked = 0
        for extracted in extracted_entities:
            if extracted.entity_type and extracted.entity_type not in _ALLOWED_ENTITY_TYPES:
                continue
            if not extracted.entity_type:
                continue
            legal_name = extracted.legal_name_normalized
            if not legal_name:
                legal_name = normalize_legal_name(extracted.extracted_name)

            canonical = await _find_confirmed_canonical_by_domain(
                session,
                legal_name,
                extracted.entity_type,
                extracted.source_id if extracted.source_type == "news_article" else None,
            )
            if canonical:
                await _create_link(
                    session,
                    extracted,
                    canonical,
                    confidence=0.9,
                    method="confirmed_domain_match",
                )
                linked += 1
                continue

            if not extracted.hq_country or not extracted.hq_region:
                continue

            canonical = await _find_confirmed_canonical_by_cluster(
                session,
                legal_name,
                extracted.entity_type,
                extracted.hq_country,
                extracted.hq_region,
            )
            if canonical:
                await _create_link(
                    session,
                    extracted,
                    canonical,
                    confidence=0.7,
                    method="confirmed_cluster_match",
                )
                linked += 1
                continue

            canonical = await _find_provisional_cluster(
                session,
                legal_name,
                extracted.entity_type,
                extracted.hq_country,
                extracted.hq_region,
            )
            if canonical:
                await _create_link(
                    session,
                    extracted,
                    canonical,
                    confidence=0.5,
                    method="provisional_cluster",
                )
                linked += 1
                continue

            canonical = await _create_canonical(session, extracted)
            await _create_link(
                session,
                extracted,
                canonical,
                confidence=0.5,
                method="new_provisional_cluster",
            )
            linked += 1

        try:
            await session.commit()
        except SQLAlchemyError as e:
            logger.error("Commit failed, rolling back: %s", e)
            await session.rollback()
            return 0

        logger.info("Linked %d extracted_entities", linked)
        return linked


async def main():
    linked = await process_batch(limit=200)
    logger.info("Done. Linked %d entities.", linked)


if __name__ == "__main__":
    asyncio.run(main())
