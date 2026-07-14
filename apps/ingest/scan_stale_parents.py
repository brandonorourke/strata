# apps/ingest/scan_stale_parents.py
#
# PROOF OF CONCEPT — ownership verifier for the UEI-directory review queue.
#
# Runs ON DEMAND (not scheduled, not wired into the pull pipeline). It takes the same
# "review" candidates surfaced on /admin/idiq/recipients — non-eponymous + candidate +
# recently active + material — and asks an OpenAI web-search model whether each is
# CURRENTLY owned by its watchlist company or has been divested/sold. This is exactly the
# manual check that caught ASRC Federal (sold by SAIC in 2023, still hung off SAIC in the
# federal data). USASpending's parent field is stale on precisely these cases, so the
# verification MUST come from an external source (web), not the hierarchy.
#
# It is ADVISORY ONLY: prints verdict + citation + suggested action. It does NOT write to
# the DB — you review the output and curate mapping_status via SQL.
#
# The review-candidate definition is imported from apps.api.main so "the 12" here always
# matches the UI. (If this graduates past POC, lift the eponymy helpers into strata_core.)
#
# Usage:
#   python apps/ingest/scan_stale_parents.py             # verify the current review queue
#   python apps/ingest/scan_stale_parents.py --dry-run   # list candidates, no LLM calls ($0)
#   python apps/ingest/scan_stale_parents.py --limit 3   # first N by $ (cheap smoke test)

import argparse
import asyncio
import re
from datetime import datetime, timezone

from openai import OpenAI
from sqlalchemy import select, func, update

from strata_core.db import AsyncSessionLocal
from strata_core.models import Company, IdiqRecipient, UsaspendingAward
from apps.api.main import (
    _epo_roots, _is_eponymous, _REVIEW_RECENT_SINCE, _REVIEW_MATERIAL_USD,
)

MODEL = "gpt-4o-mini-search-preview"   # proven working on SDK 1.55.3 via chat.completions

PROMPT = """You are checking whether a U.S. federal contractor has been DIVESTED from the
company it rolls up to in federal data.

GIVEN (take as established — do NOT try to confirm it): per USASpending, {name} is listed
under {company} (ticker {ticker}) as its parent, so it was at some point part of {company}'s
family. We already know this. Do not spend any effort proving prior ownership.

YOUR ONE JOB: find out whether {company} STILL owns it today, or whether it has since been
SOLD, SPUN OFF, or DIVESTED to a different owner. USASpending's parent link stays stale for
years after a divestiture, so the link still pointing at {company} means nothing — look for
the actual sale / spin-off / change-of-ownership news.

Entity:        {name}
Listed parent: {company} (ticker {ticker})
UEI:           {uei}
Recent federal obligations (since 2023): ${recent_m:.0f}M

Search recent M&A / divestiture news for a transaction moving this entity away from {company}.
Confirm it is the same federal/defense contractor (watch name collisions). If you find a
divestiture, say divested. If it is now owned by a clearly different company, say independent.
If it is a joint venture, say jv. If you find no divestiture and it still appears held, say
owned. If you cannot tell, say unknown.

Reply with EXACTLY these lines:
VERDICT: <owned|divested|independent|jv|unknown>   (owned = {company} still owns it today)
AS_OF: <YYYY-MM of the divestiture, or unknown>
CONFIDENCE: <high|med|low>
SOURCE: <one URL or none>
RATIONALE: <one sentence>"""

# verdict -> what you'd do with the mapping_status
ACTION = {
    "owned": "keep → confirm",
    "divested": "EXCLUDE",
    "independent": "EXCLUDE",
    "jv": "JV — don't attribute full $",
    "unknown": "leave candidate (human)",
}


async def load_review_candidates():
    async with AsyncSessionLocal() as s:
        comps = (await s.execute(select(Company))).scalars().all()
        roots = {c.ticker: _epo_roots(c.name, c.aliases, c.ticker) for c in comps if c.ticker}
        cname = {c.ticker: c.name for c in comps if c.ticker}
        recs = (await s.execute(select(IdiqRecipient))).scalars().all()
        obl = {
            u: float(x or 0)
            for u, x in (await s.execute(
                select(UsaspendingAward.recipient_uei,
                       func.sum(UsaspendingAward.total_obligation).filter(
                           UsaspendingAward.base_obligation_date >= _REVIEW_RECENT_SINCE))
                .group_by(UsaspendingAward.recipient_uei)
            )).all()
        }
    out = []
    for r in recs:
        epo = _is_eponymous(r.recipient_name, roots.get(r.ticker, set()))
        ro = obl.get(r.uei, 0.0)
        if r.mapping_status == "candidate" and epo is False and ro >= _REVIEW_MATERIAL_USD:
            out.append({"uei": r.uei, "name": r.recipient_name, "ticker": r.ticker,
                        "company": cname.get(r.ticker, r.ticker), "recent_m": ro / 1e6})
    out.sort(key=lambda x: -x["recent_m"])
    return out


def verify(client, c):
    resp = client.chat.completions.create(
        model=MODEL,
        extra_body={"web_search_options": {}},
        messages=[{"role": "user", "content": PROMPT.format(**c)}],
    )
    txt = resp.choices[0].message.content or ""

    def grab(key, default="?"):
        m = re.search(rf"{key}:\s*(.+)", txt)
        return m.group(1).strip() if m else default

    # citation came inline in content on this model, so pull the first URL out
    url_m = re.search(r"https?://[^\s)\]]+", txt)
    source = url_m.group(0).rstrip(".,)") if url_m else grab("SOURCE", "none")
    return {
        "verdict": grab("VERDICT").lower().split()[0] if grab("VERDICT") != "?" else "unknown",
        "as_of": grab("AS_OF"),
        "confidence": grab("CONFIDENCE").lower(),
        "source": source,
        "rationale": grab("RATIONALE"),
        "raw": txt,
        "usage": resp.usage,
    }


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="list candidates, no LLM calls")
    ap.add_argument("--limit", type=int, help="only the first N (by recent $)")
    ap.add_argument("--no-write", action="store_true", help="don't persist verdicts to the DB")
    args = ap.parse_args()

    cands = await load_review_candidates()
    if args.limit:
        cands = cands[:args.limit]
    print(f"{len(cands)} review candidate(s) — non-eponymous · candidate · "
          f"active(≥{_REVIEW_RECENT_SINCE:%Y}) · ≥${_REVIEW_MATERIAL_USD/1e6:.0f}M\n")

    if args.dry_run:
        for c in cands:
            print(f"  {c['ticker']:5} ${c['recent_m']:>6.0f}M  {c['name']}")
        return

    client = OpenAI()   # key from env; never printed
    tot_in = tot_out = 0
    async with AsyncSessionLocal() as session:
        for c in cands:
            v = verify(client, c)
            tot_in += v["usage"].prompt_tokens
            tot_out += v["usage"].completion_tokens
            print(f"[{c['ticker']}] {c['name']}  (${c['recent_m']:.0f}M recent)")
            print(f"    → {v['verdict'].upper()} · {v['confidence']} · {v['as_of']}"
                  f"   ⇒ {ACTION.get(v['verdict'], '?')}")
            print(f"      {v['rationale']}")
            print(f"      {v['source']}\n")
            if not args.no_write:
                await session.execute(
                    update(IdiqRecipient).where(IdiqRecipient.uei == c["uei"]).values(
                        ownership_verdict=v["verdict"], ownership_confidence=v["confidence"],
                        ownership_as_of=v["as_of"], ownership_source=v["source"],
                        ownership_rationale=v["rationale"], ownership_raw=v["raw"],
                        ownership_model=MODEL,
                        ownership_checked_at=datetime.now(timezone.utc),
                    ))
                await session.commit()
    if not args.no_write:
        print("(verdicts persisted to idiq_recipients.ownership_*)")

    n = len(cands)
    # tool fee $0.01/search + ~8k search-content input tokens/search + your prompt/output
    est = n * 0.01 + (tot_in + n * 8000) / 1e6 * 0.15 + tot_out / 1e6 * 0.60
    print(f"— {n} searches · {tot_in} prompt + {tot_out} output tokens · est ≈ ${est:.2f} "
          f"(advisory; log real cost on OpenAI dashboard)")


if __name__ == "__main__":
    asyncio.run(main())
