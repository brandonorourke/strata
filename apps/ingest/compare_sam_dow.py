"""
Compare captured SAM award notices against DoW awards to answer the thesis
question: when does SAM publish an award BEFORE DoW announces it?

Joins sam_award_notices.piid_key to dow_awards (normalized PIID inside the awardees
JSONB) and buckets each SAM notice:
  • SAM-only        — no DoW match (discovery candidate; DoW's curated digest omitted it)
  • SAM earlier     — same PIID, SAM published_at date < DoW release_date (SAM led)
  • same day        — SAM published_at date == DoW release_date
  • DoW earlier     — DoW release_date < SAM published_at date (DoW led, e.g. SMIT +4d)

DoW has no precise publish time (release_date is date-only, dropped ~5 PM ET), so the
verdict is at day granularity; SAM's precise published_at is shown when enriched.

Usage:
  python compare_sam_dow.py                 # summary + notable rows
  python compare_sam_dow.py --min-amount 10000000
"""

import argparse
import asyncio
import logging
from zoneinfo import ZoneInfo

from sqlalchemy import text

# SAM detail timestamps are stored UTC (timestamptz). Convert to true Eastern for
# display. NB: SAM.gov's own web page mislabels times as "EST" year-round (fixed
# UTC-5); real Eastern is EDT in summer, so we convert properly here.
ET = ZoneInfo("America/New_York")

from strata_core.db import AsyncSessionLocal

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Match SAM piid_key against the normalized PIID of any awardee in a DoW award.
SQL = """
WITH dow AS (
    SELECT regexp_replace(upper(a->>'piid'), '[^A-Z0-9]', '', 'g') AS piid_key,
           r.release_date, r.first_seen_at
    FROM dow_awards da
    JOIN dow_contract_releases r ON r.id = da.release_id,
         jsonb_array_elements(da.awardees) a
    WHERE a->>'piid' IS NOT NULL
)
SELECT s.piid, s.awardee_name, s.amount, s.posted_date,
       s.published_at, s.agency_path, s.sam_url,
       (s.agency_path ILIKE '%DEFENSE%') AS is_dod,
       d.release_date AS dow_release_date, d.first_seen_at AS dow_first_seen,
       CASE
         WHEN d.release_date IS NULL THEN 'sam_only'
         WHEN COALESCE(s.published_at::date, s.posted_date) <  d.release_date THEN 'sam_earlier'
         WHEN COALESCE(s.published_at::date, s.posted_date) =  d.release_date THEN 'same_day'
         ELSE 'dow_earlier'
       END AS verdict,
       COALESCE(s.published_at::date, s.posted_date) - d.release_date AS day_delta
FROM sam_award_notices s
LEFT JOIN LATERAL (
    SELECT release_date, first_seen_at FROM dow d2
    WHERE d2.piid_key = s.piid_key AND s.piid_key <> ''
    ORDER BY d2.release_date ASC LIMIT 1
) d ON TRUE
WHERE s.amount >= :min_amount OR s.amount IS NULL
ORDER BY s.amount DESC NULLS LAST
"""


async def run(min_amount: float, show: int) -> None:
    async with AsyncSessionLocal() as s:
        rows = (await s.execute(text(SQL), {"min_amount": min_amount})).mappings().all()

    total = len(rows)
    buckets: dict[str, list] = {"sam_only": [], "sam_earlier": [], "same_day": [], "dow_earlier": []}
    for r in rows:
        buckets[r["verdict"]].append(r)

    print(f"\n=== SAM vs DoW — {total} SAM notice(s) (amount >= {min_amount:,.0f}) ===")
    for k in ("sam_earlier", "sam_only", "same_day", "dow_earlier"):
        print(f"  {k:12s}: {len(buckets[k])}")
    # sam_only is only meaningful for DoD (DoW is DoD-only). Split it out.
    so_dod = [r for r in buckets["sam_only"] if r["is_dod"]]
    so_other = [r for r in buckets["sam_only"] if not r["is_dod"]]
    print(f"    └─ sam_only DoD (real discovery candidates): {len(so_dod)}")
    print(f"    └─ sam_only non-DoD (out of DoW scope entirely): {len(so_other)}")

    def fmt(r):
        amt = f"${r['amount']:,.0f}" if r["amount"] is not None else "$?"
        pub = r["published_at"].astimezone(ET).strftime("%Y-%m-%d %H:%M ET") if r["published_at"] else str(r["posted_date"])
        dd = f" ({r['day_delta']:+d}d)" if r["day_delta"] is not None else ""
        return (f"  {amt:>16} | SAM {pub} | DoW {r['dow_release_date'] or '—'}{dd} | "
                f"{(r['awardee_name'] or '')[:28]:28} | {r['piid']}")

    # The two buckets that matter most for the thesis:
    if buckets["sam_earlier"]:
        print(f"\n--- SAM EARLIER than DoW (the edge) — top {show} ---")
        for r in buckets["sam_earlier"][:show]:
            print(fmt(r))
    if so_dod:
        print(f"\n--- SAM-ONLY, DoD only (real discovery candidates) — top {show} ---")
        print("    NOTE: local DoW stops at its latest release_date; recent DoD 'sam_only' may just be the local/prod gap.")
        for r in so_dod[:show]:
            print(fmt(r))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-amount", type=float, default=0, help="ignore SAM notices below this amount")
    ap.add_argument("--show", type=int, default=25, help="rows to print per notable bucket")
    args = ap.parse_args()
    asyncio.run(run(args.min_amount, args.show))
