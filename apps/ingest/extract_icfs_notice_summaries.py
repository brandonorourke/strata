# apps/ingest/extract_icfs_notice_summaries.py
#
# For each extracted_event tied to an "Actions Taken" icfs_public_notice where the
# notice has document_text, slices out the prose block for that specific filing and
# calls the LLM to summarize what happened. Stores the result in extracted_events.llm_summary.
#
# This is the watchlist gate in practice: extract_icfs_notice_entities.py already
# identified which companies appear in which notices (via file_number lookup). This
# script only runs LLM calls for those matched rows — notices without the entity
# never reach this script, and the prose slice keeps each call to ~300-500 tokens.
#
# Run after: fetch_icfs_notice_documents.py + extract_icfs_notice_entities.py

import asyncio
import logging
import os
import re

from openai import AsyncOpenAI
from sqlalchemy import select, and_

from strata_core.db import AsyncSessionLocal
from strata_core.models import ExtractedEvent, ExtractedEntity, IcfsPublicNotice, IcfsFiling

from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

FILE_NUMBER_RE = re.compile(r"\b[A-Z]{2,4}-[A-Z0-9]{2,6}-\d{8}-\d{5}\b")

SYSTEM_PROMPT = (
    "You are an analyst reviewing excerpts from FCC Public Notices. "
    "Summarize in 2-3 sentences what action was taken on this specific application: "
    "the type of action (grant, denial, surrender, assignment, modification), "
    "the authorization or service type, any ownership or foreign-control details mentioned, "
    "and any national security conditions or CFIUS referral. Be concise and factual."
)


def _extract_prose_block(document_text: str, file_number: str) -> str | None:
    pos = document_text.find(file_number)
    if pos == -1:
        return None

    # Walk back to the start of the line containing the file number
    line_start = document_text.rfind("\n", 0, pos)
    line_start = 0 if line_start == -1 else line_start + 1

    # Find the next file number entry — that's where this block ends
    next_match = FILE_NUMBER_RE.search(document_text, pos + len(file_number))
    if next_match:
        next_line_start = document_text.rfind("\n", 0, next_match.start())
        block = document_text[line_start:next_line_start]
    else:
        block = document_text[line_start:]

    return block.strip() or None


async def _llm_summarize(client: AsyncOpenAI, company_name: str, prose_block: str) -> str:
    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Company: {company_name}\n\n"
                    f"FCC Notice excerpt:\n{prose_block}"
                ),
            },
        ],
        max_tokens=200,
        temperature=0.1,
    )
    return response.choices[0].message.content.strip()


async def process_batch(limit: int = 100) -> int:
    client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    updated = 0

    async with AsyncSessionLocal() as session:
        # Find extracted_events for icfs_notices that have document_text but no summary yet
        stmt = (
            select(ExtractedEvent, ExtractedEntity, IcfsPublicNotice)
            .join(ExtractedEntity, ExtractedEvent.entity_id == ExtractedEntity.id)
            .join(
                IcfsPublicNotice,
                and_(
                    ExtractedEvent.source_type == "icfs_notice",
                    ExtractedEvent.source_id == IcfsPublicNotice.id,
                ),
            )
            .where(ExtractedEvent.source_type == "icfs_notice")
            .where(ExtractedEvent.llm_summary.is_(None))
            .where(IcfsPublicNotice.document_text.is_not(None))
            .where(IcfsPublicNotice.type_of_document == "Actions Taken")
            .order_by(ExtractedEvent.id.asc())
            .limit(limit)
        )
        rows = list((await session.execute(stmt)).all())

        if not rows:
            logger.info("No notice events needing LLM summary.")
            return 0

        for event, entity, notice in rows:
            # Find which of this entity's file numbers actually appears in this notice's text.
            # A company can have many filings — we need the specific one referenced here.
            filing_stmt = (
                select(IcfsFiling.file_number)
                .where(IcfsFiling.applicant_name == entity.extracted_name)
                .where(IcfsFiling.file_number.is_not(None))
            )
            filing_result = await session.execute(filing_stmt)
            candidate_file_numbers = [r[0] for r in filing_result.all()]

            file_number = next(
                (fn for fn in candidate_file_numbers if fn in notice.document_text),
                None,
            )
            if not file_number:
                logger.warning("No matching file number found in notice %s for %r — skipping.", notice.number, entity.extracted_name)
                continue

            prose_block = _extract_prose_block(notice.document_text, file_number)
            if not prose_block:
                logger.warning("File number %s not found in document text for notice %s.", filing.file_number, notice.number)
                continue

            try:
                summary = await _llm_summarize(client, entity.extracted_name, prose_block)
                event.llm_summary = summary
                await session.commit()
                updated += 1
                logger.info(
                    "Summarized %s in %s: %s",
                    entity.extracted_name,
                    notice.number,
                    summary[:80],
                )
            except Exception as e:
                logger.error("LLM call failed for %s / %s: %r", entity.extracted_name, notice.number, e)
                await session.rollback()

    logger.info("Done. Updated %d event summaries.", updated)
    return updated


async def main():
    limit_env = os.getenv("ICFS_SUMMARY_LIMIT")
    limit = int(limit_env) if limit_env else 100
    await process_batch(limit=limit)


if __name__ == "__main__":
    asyncio.run(main())
