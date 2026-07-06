# Spec: DoW award enrichment (PIID → authoritative contract data)

Design + validated findings, 2026-07-06. **Not yet built** — this documents the
plan and the empirical basis for it. Extraction (which produces the PIIDs) is in
`docs/specs/dow_extraction.md`; source mechanics in `docs/usaspending_api.md` and
`docs/sam_api.md`.

## Goal
Given the PIIDs extracted from DoW press releases, attach authoritative contract
data — ceiling (`base_and_all_options`), obligated-to-date (`total_obligation`),
canonical recipient name, and UEI — keyed on PIID. The press release supplies the
day-0 signal; enrichment matures it.

## Three lanes, keyed on PIID

| Lane | Window | Provides | Cost/limit |
|---|---|---|---|
| **SAM live API** | day 0–15 (active window) | ceiling + UEI for new IDIQ bases / standalone awards, **same-day** | 10 req/day (non-federal); poll narrow |
| **SAM archived CSV** | ~2–6 wk+ (backfill) | same, once archived | local, unlimited (but stale snapshot) |
| **USASpending** | pre-current-FY (permanent) | authoritative ceiling/obligated + UEI | free API, no key |

Handoff over time for one award:
```
Day 0      press-release signal (awardee, PIID, announced $, purpose)  ← already have
Day 0–15   SAM live API fills fresh IDIQ-base ceilings + UEI           ← only same-day lever
~2–6 weeks SAM CSV backfill (as notices archive)
Months     USASpending fills authoritative $ (as fiscal year reports)
```

## Coverage — validated on 3,993 extracted PIIDs (2026-07-06)

**Backfill / historical (whole corpus): 71% union enrichable today.**
- SAM CSV (7-year, FY2020–2026): 40%
- USASpending (net-new beyond SAM): +30%
- **Union: 71%**
- Sources are complementary — little overlap; you need both.
- Remaining ~29%: mostly FY26 originations (self-heal as FY2026 reports into
  USASpending) + F-type delivery orders (need parent link).

**Real-time (a release that dropped today): ~15–20%, and this is structural.**
A fresh release is dominated by new FY26 awards that exist in *no* queryable source
yet (USASpending FY-lag; SAM CSV archival-lag ~6wk). Only two parts enrich same-day:
- pre-FY26 **modifications** cited in the release → USASpending now (the $1–5B reveals)
- fresh **IDIQ bases** → SAM live API (if within 15 days; delivery orders excluded)

**Conclusion: real-time authoritative enrichment is inherently limited — the data
isn't published yet. No source-wrangling fixes it.** The product answer is
**progressive enrichment**: show the release signal on day 0, mark enrichment
`pending`, backfill as lanes catch up (retry loop keyed on `last_tried_at`). The
press release *is* the day-0 signal (awardee, PIID, announced amount, purpose);
enrichment adds *context* (true ceiling, obligated, underlying contract size, UEI).

## FY-based resolution rule (USASpending)
Resolution depends on the PIID's fiscal year (2-digit code after the office), not
contract age. Pre-current-FY resolves; current-FY (FY2026) doesn't yet — fiscal-year-wide,
not per-contract. C/D/A/G types resolve on their own PIID; **F-types need the parent PIID**.

## F-type (delivery order) resolution ladder

Delivery orders (~10% of PIIDs) are the hard case: they get no SAM notice, and
resolve on USASpending only via the parent. The parent is usually **older** than the
order, so it's typically already indexed — which makes parent-resolution more
real-time-friendly than enriching the order directly.

```
1. Direct: order PIID → SAM/USASpending            (rarely hits for fresh F-types)
2. Fuzzy parent lookup: awardee + awarding-office + D-type, in the SAM CSV index
     ├─ exactly 1 candidate → auto-enrich   (Viasat/Intelsat PTS-G → $4B) ✅
     ├─ 2–N candidates      → show candidates; disambiguate by purpose/program match
     └─ 0                    → press-release signal only; mark pending
3. Backstop: when the order eventually indexes in USASpending, its `parent_award`
   field is the exact parent — authoritative, no heuristics (but delayed).
```

**Reverse-lookup mechanics (validated):**
- Office (DoDAAC) = **first 6 chars of the normalized PIID** (works for dashed +
  condensed; don't parse "2-digit FY" positionally — Army offices like `W912QR`,
  `W56HZV` contain digits and break that).
- Awardee match: require **all** *significant* order tokens present in the CSV
  awardee — drop legal suffixes (INC/LLC/CORP…) **and** generic industry words
  (AIRCRAFT, SERVICES, DEFENSE, SYSTEMS…). Loose token-overlap caused false
  positives (Sikorsky↔Moog on "AIRCRAFT", Suvi↔KBR on "SERVICES").

**Guards for the "single candidate → auto" case** (all hold for PTS-G):
- Parent award date **< order date** (parent predates order: DB002 2025-07-28 < FB004 2026-05-22).
- Optional purpose/program keyword overlap ("Protected Tactical" ↔ PTS-G).
- Cap candidate display (>~5 → treat as no-confident-match, don't dump 16).

**F-type ladder coverage (7-year index, ~389 F-types):**
- ~9% → single candidate → auto
- ~18% → show candidates (mostly 2–4; big contractors under busy Navy office `N00019` hit 13–16)
- ~71% → none (parent not in our CSVs, or ordering office ≠ parent awarding office)

Adding FY2020–2024 CSVs raised F-type "parent found" only 22%→28% and mostly *added
ambiguity* (a contractor's many multi-year vehicles collide on office+awardee). More
CSVs help **direct** enrichment (34%→40%) far more than parent reverse-lookup.

### PTS-G reference case (Viasat/Intelsat), validated end-to-end
- Extracted: order `FA880726FB004` (Viasat), `FA880726FB005` (Intelsat) — F-type FY26.
- Order itself: not in SAM, 404 on USASpending (F-type, FY26).
- Parent (FY25) fully enrichable **now** in both sources: `FA880725DB002`/`DB005` →
  $4B ceiling, UEI `L9Z1ASN3B8E7` (Viasat) / `G3FMDEWF7YV3` (Intelsat).
- Fuzzy lookup (Viasat + office `FA8807` + D-type) → exactly 1 candidate → $4B. ✅
  Robust even against the noisy 7-year index (each holds one `FA8807` vehicle).

## SAM operational constraints (see docs/sam_api.md)
- Live API rate limit: **non-federal 10 req/day** (ours), federal 1,000/day. Not the
  real bottleneck — the live window is only ~15 days ≈ ~3 requests to fully drain.
  Production = 1 narrow poll/day (~1 req), cache results.
- CSV archival-lag: trails real-time ~3–6 weeks; can't enrich a this-week release.
- Delivery orders never get SAM notices.

## Planned schema
Promote awardees out of the `dow_awards.awardees` JSONB array into a child table so
enrichment has a write target and `name_raw` becomes an indexable column:
```
dow_awardees(id, award_id FK, piid, name_raw, city_raw, state_raw, pairing_confidence,
             -- enrichment (filled by the passes):
             source, uei, canonical_name, ceiling, obligated, parent_piid,
             resolved_at, last_tried_at)
```

## Build order (when greenlit)
1. `dow_awardees` migration + backfill from JSONB.
2. **SAM CSV pass** (local join, instant, ~40%) — fastest visible value, no limits.
3. **USASpending pass** (gentle: concurrency ≤3, pacing, backoff; +30% net-new).
   Mark FY26 `pending`, retry as the FY indexes.
4. **F-type parent ladder** (above) — CSV reverse-lookup + guards + purpose disambiguation.
5. **SAM live daily poll** (~1 req/day, cached) — same-day IDIQ-base ceilings for fresh releases.
6. Surface real ceiling/obligated in `/dow`.

## Data assets
- 7-year SAM CSVs (FY2020–2026, ~7 GB) in `~/Downloads/FY20*_archived_opportunities.csv`
  — **outside the repo, not source-controlled.** Static snapshots (re-download to advance).
- Cached index build: scan CSVs → `{normalized_award_number: (piid, amount, awardee, type, date, fy)}`.
