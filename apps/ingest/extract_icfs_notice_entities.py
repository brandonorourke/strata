# apps/ingest/extract_icfs_notice_entities.py
#
# Processing layer for ICFS Public Notice documents. Rather than regexing out company
# names from the document text directly (fragile — formatting varies block to block,
# e.g. company name sometimes precedes the file number line, sometimes follows it on
# the same line), we extract the file_number tokens instead (a fixed, reliable shape:
# PREFIX-SUBCODE-YYYYMMDD-SEQ) and resolve the company via the same zero-ambiguity
# file_number -> icfs_filings join already used for Pleadings & Comments. A notice can
# reference multiple companies (multiple applications in one bulletin) — each resolved
# company becomes its own per-occurrence entity/event, same convention as elsewhere.

import asyncio
import logging
import re
from datetime import datetime, timezone, time

from sqlalchemy import select, and_
from sqlalchemy.exc import SQLAlchemyError

from strata_core.db import AsyncSessionLocal
from strata_core.models import IcfsPublicNotice, IcfsFiling, ExtractedEntity, ExtractedEvent

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

SOURCE_TYPE = "icfs_notice"

FILE_NUMBER_RE = re.compile(r"\b[A-Z]{2,4}-[A-Z0-9]{2,6}-\d{8}-\d{5}\b")


async def process_notice(session, notice: IcfsPublicNotice) -> int:
    if not notice.document_text:
        notice.entities_extracted_at = datetime.now(timezone.utc)
        return 0

    file_numbers = sorted(set(FILE_NUMBER_RE.findall(notice.document_text)))
    if not file_numbers:
        notice.entities_extracted_at = datetime.now(timezone.utc)
        return 0

    inserted = 0
    seen_legal_names = set()

    for file_number in file_numbers:
        filing_stmt = select(IcfsFiling).where(IcfsFiling.file_number == file_number).limit(1)
        filing_result = await session.execute(filing_stmt)
        filing = filing_result.scalar_one_or_none()
        if filing is None or not filing.applicant_name:
            continue

        filing_entity_stmt = (
            select(ExtractedEntity)
            .where(ExtractedEntity.source_type == "icfs_filing")
            .where(ExtractedEntity.source_id == filing.id)
            .limit(1)
        )
        filing_entity_result = await session.execute(filing_entity_stmt)
        filing_entity = filing_entity_result.scalar_one_or_none()
        if filing_entity is None:
            continue

        if filing_entity.legal_name_normalized in seen_legal_names:
            continue  # same company already resolved via a different file_number in this notice
        seen_legal_names.add(filing_entity.legal_name_normalized)

        exists_stmt = select(ExtractedEntity.id).where(
            and_(
                ExtractedEntity.source_type == SOURCE_TYPE,
                ExtractedEntity.source_id == notice.id,
                ExtractedEntity.legal_name_normalized == filing_entity.legal_name_normalized,
            )
        ).limit(1)
        already = await session.execute(exists_stmt)
        if already.scalar_one_or_none() is not None:
            continue

        event_time = notice.public_notice_release_date   # pure date (glide_date), see migration 0041
        # first_seen_at columns are timestamptz; promote the date to a datetime.
        event_dt = (datetime.combine(event_time, time.min, tzinfo=timezone.utc)
                    if event_time and not isinstance(event_time, datetime) else event_time)
        entity = ExtractedEntity(
            source_type=SOURCE_TYPE,
            source_id=notice.id,
            extracted_name=filing.applicant_name,
            entity_type="operating_company",
            created_from="icfs",
            legal_name_normalized=filing_entity.legal_name_normalized,
            loose_name_normalized=filing_entity.loose_name_normalized,
            first_seen_at=event_dt,
            last_seen_at=event_dt,
            icfs_canonical_entity_id=filing_entity.icfs_canonical_entity_id,
        )
        session.add(entity)
        await session.flush()

        event = ExtractedEvent(
            source_type=SOURCE_TYPE,
            source_id=notice.id,
            entity_id=entity.id,
            extracted_name=filing.applicant_name,
            is_primary_entity=True,
            event_type="regulatory",
            event_date=(event_time.date() if isinstance(event_time, datetime) else event_time) if event_time else None,
            event_description=(
                f"Mentioned in Public Notice {notice.number} (DA {notice.da_number or '—'}), "
                f"referencing filing {file_number} ({filing.applicant_name})."
            ),
            confidence=1.0,
        )
        session.add(event)
        inserted += 1

    notice.entities_extracted_at = datetime.now(timezone.utc)
    return inserted


async def fetch_notices_needing_extraction(session, limit: int = 200) -> list[IcfsPublicNotice]:
    stmt = (
        select(IcfsPublicNotice)
        .where(IcfsPublicNotice.entities_extracted_at.is_(None))
        .where(IcfsPublicNotice.document_fetched_at.is_not(None))
        .order_by(IcfsPublicNotice.id.asc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def process_batch(limit: int = 200) -> int:
    async with AsyncSessionLocal() as session:
        notices = await fetch_notices_needing_extraction(session, limit=limit)
        if not notices:
            logger.info("No icfs_public_notices needing entity extraction.")
            return 0

        total_inserted = 0
        for notice in notices:
            total_inserted += await process_notice(session, notice)

        try:
            await session.commit()
        except SQLAlchemyError as e:
            logger.error("Commit failed, rolling back: %s", e)
            await session.rollback()
            return 0

        logger.info("Inserted %d extracted_events from icfs_public_notices", total_inserted)
        return total_inserted


async def main():
    inserted = await process_batch(limit=500)
    logger.info("Done. Inserted %d event rows.", inserted)


if __name__ == "__main__":
    asyncio.run(main())
