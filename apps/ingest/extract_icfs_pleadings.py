# apps/ingest/extract_icfs_pleadings.py
#
# Processing layer for ICFS Pleadings & Comments. Unlike Filings, this table has no
# structured applicant name on the index — but a minority of rows (~20-35%, confirmed
# empirically) carry file_number, a zero-ambiguity structural join back to icfs_filings
# and from there to that company's already-resolved icfs_canonical_entity. Rows without
# a matching file_number are skipped, not guessed at — reading the actual document text
# to find out who's involved is real future work (LLM-based), not done here.

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select, and_
from sqlalchemy.exc import SQLAlchemyError

from strata_core.db import AsyncSessionLocal
from strata_core.models import IcfsPleadingAndComment, IcfsFiling, ExtractedEntity, ExtractedEvent

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

SOURCE_TYPE = "icfs_pleading"


async def process_pleading(session, pleading: IcfsPleadingAndComment) -> int:
    if not pleading.file_number:
        pleading.entities_extracted_at = datetime.now(timezone.utc)
        return 0

    filing_stmt = select(IcfsFiling).where(IcfsFiling.file_number == pleading.file_number).limit(1)
    filing_result = await session.execute(filing_stmt)
    filing = filing_result.scalar_one_or_none()
    if filing is None or not filing.applicant_name:
        # Either we haven't ingested the referenced filing yet, or it never had a
        # structured applicant name — nothing safe to link to either way.
        pleading.entities_extracted_at = datetime.now(timezone.utc)
        return 0

    filing_entity_stmt = (
        select(ExtractedEntity)
        .where(ExtractedEntity.source_type == "icfs_filing")
        .where(ExtractedEntity.source_id == filing.id)
        .limit(1)
    )
    filing_entity_result = await session.execute(filing_entity_stmt)
    filing_entity = filing_entity_result.scalar_one_or_none()
    if filing_entity is None:
        pleading.entities_extracted_at = datetime.now(timezone.utc)
        return 0

    exists_stmt = select(ExtractedEntity.id).where(
        and_(
            ExtractedEntity.source_type == SOURCE_TYPE,
            ExtractedEntity.source_id == pleading.id,
        )
    ).limit(1)
    already = await session.execute(exists_stmt)
    if already.scalar_one_or_none() is not None:
        pleading.entities_extracted_at = datetime.now(timezone.utc)
        return 0

    event_time = pleading.sys_created_on

    # A new per-occurrence entity row, same convention as news/filings (one row per
    # source mention) — but pointing at the SAME icfs_canonical_entity as the filing,
    # since the file_number join already tells us with certainty it's the same company.
    entity = ExtractedEntity(
        source_type=SOURCE_TYPE,
        source_id=pleading.id,
        extracted_name=filing.applicant_name,
        entity_type="operating_company",
        created_from="icfs",
        legal_name_normalized=filing_entity.legal_name_normalized,
        loose_name_normalized=filing_entity.loose_name_normalized,
        first_seen_at=event_time,
        last_seen_at=event_time,
        icfs_canonical_entity_id=filing_entity.icfs_canonical_entity_id,
    )
    session.add(entity)
    await session.flush()

    event = ExtractedEvent(
        source_type=SOURCE_TYPE,
        source_id=pleading.id,
        entity_id=entity.id,
        extracted_name=filing.applicant_name,
        is_primary_entity=True,
        event_type="regulatory",
        event_date=event_time.date() if event_time else None,
        event_description=(
            f'{pleading.pleading_type or "Pleading"} filed in case {pleading.file_number} '
            f"({filing.applicant_name})."
        ),
        confidence=1.0,
    )
    session.add(event)

    pleading.entities_extracted_at = datetime.now(timezone.utc)
    return 1


async def fetch_pleadings_needing_extraction(session, limit: int = 200) -> list[IcfsPleadingAndComment]:
    stmt = (
        select(IcfsPleadingAndComment)
        .where(IcfsPleadingAndComment.entities_extracted_at.is_(None))
        .order_by(IcfsPleadingAndComment.id.asc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def process_batch(limit: int = 200) -> int:
    async with AsyncSessionLocal() as session:
        pleadings = await fetch_pleadings_needing_extraction(session, limit=limit)
        if not pleadings:
            logger.info("No icfs_pleadings_and_comments needing entity extraction.")
            return 0

        total_inserted = 0
        for pleading in pleadings:
            total_inserted += await process_pleading(session, pleading)

        try:
            await session.commit()
        except SQLAlchemyError as e:
            logger.error("Commit failed, rolling back: %s", e)
            await session.rollback()
            return 0

        logger.info("Inserted %d extracted_events from icfs_pleadings_and_comments", total_inserted)
        return total_inserted


async def main():
    inserted = await process_batch(limit=500)
    logger.info("Done. Inserted %d event rows.", inserted)


if __name__ == "__main__":
    asyncio.run(main())
