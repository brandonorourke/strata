# apps/ingest/extract_icfs_entities.py
#
# Processing layer for ICFS — promotes structured icfs_filings rows into the
# canonical extracted_entities/extracted_events model, and collapses them within
# ICFS by exact normalized name into icfs_canonical_entities (Tier 1 of entity
# resolution — see docs/decisions.md 2026-06-23). No LLM call needed for any of
# this: applicant_name is already structured truth from the source. Mirrors
# extract_entities.py's shape but reads icfs_filings instead of news_articles.llm_raw.
# Deliberately NOT linked to the global canonical_entities table yet — that
# cross-source hop is human-gated and deferred.
# (Pleadings & Comments / Public Notices have no applicant name on the index itself —
# they need a real document-parsing step before they can feed this, not yet built.)

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select, and_
from sqlalchemy.exc import SQLAlchemyError

from strata_core.db import AsyncSessionLocal
from strata_core.models import IcfsFiling, ExtractedEntity, ExtractedEvent, IcfsCanonicalEntity
from strata_core.normalize import normalize_legal_name, normalize_loose_name

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

SOURCE_TYPE = "icfs_filing"


async def _get_or_create_icfs_canonical(session, canonical_name: str, legal_name: str, event_time):
    stmt = select(IcfsCanonicalEntity).where(IcfsCanonicalEntity.legal_name_normalized == legal_name).limit(1)
    result = await session.execute(stmt)
    icfs_canonical = result.scalar_one_or_none()
    if icfs_canonical:
        if event_time:
            if icfs_canonical.first_seen_at is None or event_time < icfs_canonical.first_seen_at:
                icfs_canonical.first_seen_at = event_time
            if icfs_canonical.last_seen_at is None or event_time > icfs_canonical.last_seen_at:
                icfs_canonical.last_seen_at = event_time
        return icfs_canonical

    icfs_canonical = IcfsCanonicalEntity(
        canonical_name=canonical_name,
        legal_name_normalized=legal_name,
        loose_name_normalized=normalize_loose_name(canonical_name),
        first_seen_at=event_time,
        last_seen_at=event_time,
    )
    session.add(icfs_canonical)
    await session.flush()  # assigns icfs_canonical.id for the FK set below
    return icfs_canonical


async def _get_or_create_entity(session, filing: IcfsFiling, canonical_name: str):
    legal_name = normalize_legal_name(canonical_name)
    if not legal_name:
        return None

    event_time = filing.submission_date or filing.action_taken_date
    icfs_canonical = await _get_or_create_icfs_canonical(session, canonical_name, legal_name, event_time)

    stmt = (
        select(ExtractedEntity)
        .where(ExtractedEntity.source_type == SOURCE_TYPE)
        .where(ExtractedEntity.source_id == filing.id)
        .where(ExtractedEntity.legal_name_normalized == legal_name)
        .limit(1)
    )
    result = await session.execute(stmt)
    entity = result.scalar_one_or_none()
    if entity:
        if entity.icfs_canonical_entity_id is None:
            entity.icfs_canonical_entity_id = icfs_canonical.id
        return entity

    entity = ExtractedEntity(
        source_type=SOURCE_TYPE,
        source_id=filing.id,
        extracted_name=canonical_name,
        entity_type="operating_company",
        created_from="icfs",
        legal_name_normalized=legal_name,
        loose_name_normalized=normalize_loose_name(canonical_name),
        first_seen_at=event_time,
        last_seen_at=event_time,
        icfs_canonical_entity_id=icfs_canonical.id,
    )
    session.add(entity)
    return entity


async def process_filing(session, filing: IcfsFiling) -> int:
    applicant_name = filing.applicant_name
    if not applicant_name:
        filing.entities_extracted_at = datetime.now(timezone.utc)
        return 0

    entity = await _get_or_create_entity(session, filing, applicant_name)
    if entity is None:
        filing.entities_extracted_at = datetime.now(timezone.utc)
        return 0

    await session.flush()  # ensure entity.id is assigned before the exists-check below

    exists_stmt = select(ExtractedEvent.id).where(
        and_(
            ExtractedEvent.source_type == SOURCE_TYPE,
            ExtractedEvent.source_id == filing.id,
            ExtractedEvent.entity_id == entity.id,
        )
    ).limit(1)
    already = await session.execute(exists_stmt)
    if already.scalar_one_or_none() is not None:
        filing.entities_extracted_at = datetime.now(timezone.utc)
        return 0

    if filing.action:
        event_date = (filing.action_taken_date or filing.submission_date)
        description = f'FCC action "{filing.action}" recorded on ICFS filing {filing.file_number}, filed by {applicant_name}.'
    else:
        event_date = filing.submission_date
        description = f"ICFS filing {filing.file_number} submitted by {applicant_name}."

    event = ExtractedEvent(
        source_type=SOURCE_TYPE,
        source_id=filing.id,
        entity_id=entity.id,
        extracted_name=applicant_name,
        is_primary_entity=True,
        event_type="regulatory",
        event_date=event_date.date() if event_date else None,
        event_description=description,
        confidence=1.0,
    )
    session.add(event)

    filing.entities_extracted_at = datetime.now(timezone.utc)
    return 1


async def fetch_filings_needing_extraction(session, limit: int = 200) -> list[IcfsFiling]:
    stmt = (
        select(IcfsFiling)
        .where(IcfsFiling.entities_extracted_at.is_(None))
        .order_by(IcfsFiling.id.asc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def process_batch(limit: int = 200) -> int:
    async with AsyncSessionLocal() as session:
        filings = await fetch_filings_needing_extraction(session, limit=limit)
        if not filings:
            logger.info("No icfs_filings needing entity extraction.")
            return 0

        total_inserted = 0
        for filing in filings:
            total_inserted += await process_filing(session, filing)

        try:
            await session.commit()
        except SQLAlchemyError as e:
            logger.error("Commit failed, rolling back: %s", e)
            await session.rollback()
            return 0

        logger.info("Inserted %d extracted_events from icfs_filings", total_inserted)
        return total_inserted


async def main():
    inserted = await process_batch(limit=500)
    logger.info("Done. Inserted %d event rows.", inserted)


if __name__ == "__main__":
    asyncio.run(main())
