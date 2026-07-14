# ops/2026-07-14_backfill_dow_source_excerpt.py   (one-off)
#
# Re-derive dow_awards.source_excerpt at FULL length for rows extracted before the
# `para[:600]` cap was lifted (extract_dow_awards_v2.py:275). Regex-only — re-runs the
# same paragraph parser (`_regex_groups`), NO LLM call, so it's free.
#
# The old excerpt (html.unescape(para[:600])) is a clean prefix of the new full paragraph,
# so each award is matched to its regenerated group by that prefix.
#
# Runs against whatever DATABASE_URL points at:
#   .venv/bin/python ops/2026-07-14_backfill_dow_source_excerpt.py            # local
#   DATABASE_URL="$PROD_DATABASE_URL" .venv/bin/python ops/..._source_excerpt.py   # prod

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root

from sqlalchemy import select
from strata_core.db import AsyncSessionLocal
from strata_core.models import DowContractRelease, DowAward
from apps.ingest.extract_dow_awards_v2 import _release_body, _regex_groups


async def main():
    updated = 0
    releases_touched = 0
    async with AsyncSessionLocal() as s:
        releases = (await s.execute(
            select(DowContractRelease).where(DowContractRelease.raw_text.is_not(None))
        )).scalars().all()

        for r in releases:
            excerpts = [g["source_excerpt"] for g in _regex_groups(_release_body(r.raw_text))
                        if g.get("source_excerpt")]
            if not excerpts:
                continue
            awards = (await s.execute(
                select(DowAward).where(DowAward.release_id == r.id)
            )).scalars().all()

            touched = False
            for a in awards:
                cur = a.source_excerpt
                if not cur:
                    continue
                key = cur[:400]                      # well inside 600 → clean prefix
                full = next((e for e in excerpts if e.startswith(key)), None)
                if full and full != cur:
                    a.source_excerpt = full
                    updated += 1
                    touched = True
            releases_touched += 1 if touched else 0

        await s.commit()
    print(f"updated {updated} award(s) across {releases_touched} release(s)")


if __name__ == "__main__":
    asyncio.run(main())
