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
)
from strata_core.normalize import normalize_legal_name, normalize_loose_name

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

_ALLOWED_ENTITY_TYPES = {"operating_company", "financial_sponsor", "lender"}


async def _find_canonical_exact(session, legal_name: str, jurisdiction: str):
    stmt = select(CanonicalEntity).where(
        and_(
            CanonicalEntity.legal_name_normalized == legal_name,
            CanonicalEntity.jurisdiction == jurisdiction,
        )
    ).limit(1)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def _find_canonical_legal_only(session, legal_name: str):
    stmt = select(CanonicalEntity).where(
        and_(
            CanonicalEntity.legal_name_normalized == legal_name,
            CanonicalEntity.status == "confirmed",
        )
    ).limit(1)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def _create_canonical(session, extracted: ExtractedEntity) -> CanonicalEntity:
    status = "confirmed" if extracted.jurisdiction else "provisional"
    canonical = CanonicalEntity(
        canonical_name=extracted.extracted_name,
        legal_name_normalized=extracted.legal_name_normalized
        or normalize_legal_name(extracted.extracted_name),
        loose_name_normalized=extracted.loose_name_normalized
        or normalize_loose_name(extracted.extracted_name),
        jurisdiction=extracted.jurisdiction,
        status=status,
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
            legal_name = extracted.legal_name_normalized
            if not legal_name:
                legal_name = normalize_legal_name(extracted.extracted_name)

            canonical = None
            if extracted.jurisdiction:
                canonical = await _find_canonical_exact(
                    session, legal_name, extracted.jurisdiction
                )
                if canonical:
                    if canonical.status != "confirmed":
                        canonical.status = "confirmed"
                    await _create_link(
                        session,
                        extracted,
                        canonical,
                        confidence=0.95,
                        method="exact_legal+jurisdiction",
                    )
                    linked += 1
                    continue

            canonical = await _find_canonical_legal_only(session, legal_name)
            if canonical:
                await _create_link(
                    session,
                    extracted,
                    canonical,
                    confidence=0.7,
                    method="exact_legal_confirmed",
                )
                linked += 1
                continue

            canonical = await _create_canonical(session, extracted)
            await _create_link(
                session,
                extracted,
                canonical,
                confidence=1.0,
                method="new_canonical",
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
