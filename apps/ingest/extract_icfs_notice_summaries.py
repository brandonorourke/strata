# apps/ingest/extract_icfs_notice_summaries.py
#
# For each extracted_event tied to an "Actions Taken" icfs_public_notice where the
# notice has document_text, slices out the prose block for that specific filing and
# calls the LLM to produce a structured analysis: summary, signal_tier, and signal_reason.
#
# signal_tier "signal": ownership change, CFIUS/national security referral,
#   surrender/discontinuance, bankruptcy/DIP, denial/dismissal of significant operator,
#   foreign ownership ruling, transfer of control.
# signal_tier "routine": standard STA grant, minor modification, operational TT&C/LEOP,
#   routine resale authority grant with no notable ownership detail.
#
# source_excerpt stores the prose block sent to the LLM so readers can verify summaries.
#
# Run after: fetch_icfs_notice_documents.py + extract_icfs_notice_entities.py

import asyncio
import json
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

SYSTEM_PROMPT = """\
You are an analyst reviewing excerpts from FCC Public Notices for an investor intelligence product.

For the given company and notice excerpt, return a JSON object with exactly three fields:

"summary": 2-3 sentences describing what action was taken — type of action (grant, denial,
  surrender, assignment, modification, referral), the authorization or service type, any
  ownership or foreign-control details, and any national security conditions.

"signal_tier": exactly "signal" or "routine".
  Use "signal" for: ownership change or transfer of control, CFIUS/national security referral
    to Executive Branch, surrender or discontinuance of authorization, bankruptcy/debtor-in-
    possession context, denial or dismissal of a significant operator, foreign ownership ruling
    or § 310(b) petition, grant with LOA/DOJ/DHS conditions.
  Use "routine" for: standard Special Temporary Authority (STA) grant for an existing operator,
    minor technical modification, operational TT&C/LEOP grant, routine global resale authority
    grant with no notable ownership detail.

"signal_reason": one short phrase (5-10 words) explaining the classification, e.g.
  "CFIUS referral pending national security review" or "routine STA renewal for existing fleet".\
"""

RESPONSE_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "notice_analysis",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "signal_tier": {"type": "string", "enum": ["signal", "routine"]},
                "signal_reason": {"type": "string"},
            },
            "required": ["summary", "signal_tier", "signal_reason"],
            "additionalProperties": False,
        },
    },
}


def _extract_prose_block(document_text: str, file_number: str) -> str | None:
    pos = document_text.find(file_number)
    if pos == -1:
        return None

    line_start = document_text.rfind("\n", 0, pos)
    line_start = 0 if line_start == -1 else line_start + 1

    next_match = FILE_NUMBER_RE.search(document_text, pos + len(file_number))
    if next_match:
        next_line_start = document_text.rfind("\n", 0, next_match.start())
        block = document_text[line_start:next_line_start]
    else:
        block = document_text[line_start:]

    return block.strip() or None


async def _llm_analyze(client: AsyncOpenAI, company_name: str, prose_block: str) -> dict:
    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Company: {company_name}\n\nFCC Notice excerpt:\n{prose_block}",
            },
        ],
        response_format=RESPONSE_SCHEMA,
        max_tokens=300,
        temperature=0.1,
    )
    return json.loads(response.choices[0].message.content)


async def process_batch(limit: int = 100) -> int:
    client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    updated = 0

    async with AsyncSessionLocal() as session:
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
            .where(ExtractedEvent.signal_tier.is_(None))
            .where(IcfsPublicNotice.document_text.is_not(None))
            .where(IcfsPublicNotice.type_of_document.ilike("Actions Taken%"))
            .order_by(ExtractedEvent.id.asc())
            .limit(limit)
        )
        rows = list((await session.execute(stmt)).all())

        if not rows:
            logger.info("No notice events needing LLM analysis.")
            return 0

        for event, entity, notice in rows:
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
                logger.warning("No matching file number in notice %s for %r — skipping.", notice.number, entity.extracted_name)
                continue

            prose_block = _extract_prose_block(notice.document_text, file_number)
            if not prose_block:
                # SCL and other notice families cite file numbers inline (e.g. "See File Nos. X and Y.")
                # rather than as section headers — the slicer can't extract a meaningful block.
                # Mark unparseable so this event is excluded from future batches.
                logger.warning("Prose block extraction failed for %s / %s — marking unparseable.", notice.number, file_number)
                event.signal_tier = "unparseable"
                await session.commit()
                continue

            try:
                result = await _llm_analyze(client, entity.extracted_name, prose_block)
                event.llm_summary = result["summary"]
                event.signal_tier = result["signal_tier"]
                event.signal_reason = result["signal_reason"]
                event.source_excerpt = prose_block
                await session.commit()
                updated += 1
                logger.info(
                    "[%s] %s in %s: %s",
                    result["signal_tier"].upper(),
                    entity.extracted_name,
                    notice.number,
                    result["signal_reason"],
                )
            except Exception as e:
                logger.error("LLM call failed for %s / %s: %r", entity.extracted_name, notice.number, e)
                await session.rollback()

    logger.info("Done. Updated %d event analyses.", updated)
    return updated


async def main():
    limit_env = os.getenv("ICFS_SUMMARY_LIMIT")
    limit = int(limit_env) if limit_env else 100
    await process_batch(limit=limit)


if __name__ == "__main__":
    asyncio.run(main())
