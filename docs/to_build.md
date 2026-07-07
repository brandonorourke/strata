# To Build

## Build order (Brandon, 2026-07-07) — current priority

1. **Alerts for Stas: Viasat + Intelsat on new ICFS filings + DoW awards.**
   Mostly BUILT — `apps/ingest/emit_alerts.py` already has `WATCHLIST=["Viasat","Intelsat"]`,
   `detect_dow` (watchlist DoW awards) and `detect_icfs` (watchlist ICFS filings), Resend
   delivery, freshness guard, and `alert_state` watermarks. Remaining work:
   (a) flip `ALERT_ALL = True` → `False` (it's in end-to-end test mode, alerting on everything);
   (b) add Stas to `ALERT_TO` (currently just bcorourke@gmail.com — need his email);
   (c) verify end-to-end on a real watchlist hit.
2. **Fix DoW obligated-vs-ceiling extraction.** THE data-quality fix (see the ceiling
   mis-attribution bug below). Extract the obligated amount from the DoW prose
   ("$X are being obligated at time of award") instead of stamping the ceiling; flag
   shared multi-award IDIQs ("1 of M"). Fixtures: Andromeda ($1.843B ceiling / $1.4M
   obligated / 14 awardees) and PTS-G ($437.7M / $150M / Viasat+Intelsat). Delivers the
   obligated-vs-ceiling differentiator in real time — no USASpending needed (the number is
   in the announcement text). USASpending deferred: it's the deterministic-but-lagged
   backfill/confirmation layer, not a near-term build (progressive lag: ~15–20% at
   award-day → ~71% over months; the real-time obligated $ comes from DoW prose).
3. **Confirm alerts cover ACTIONS, not just filings.** GAP: `detect_icfs` currently fires
   only on new `icfs_filings` rows. A new *action* on an existing watchlist filing
   (modification / `action_taken_date` change in `icfs_filing_action_history`, or a new
   pleading) would NOT alert. Add detection over action history + pleadings for watchlist
   entities. (Same subsystem as #1 — bundle them.)
4. **Program fuzzy-match for DoW contracts → possible parent program.** Heuristic linkage
   of a bare delivery order to its parent vehicle/program, real-time. Candidate generation:
   office (PIID[:6]) + type=D (IDIQ vehicles only — the real reducer) + awardee name;
   disambiguate multi-vehicle primes with program-title + NAICS/PSC + timing (NOT amount —
   amount doesn't identify the parent). Frame as **"possible parent program"** with a
   confidence tier (confirmed/likely/possible/unresolved) + the matching basis; gate the
   ambiguous tail (big primes, e.g. Lockheed 8 vehicles in one office). Deterministic cases
   handled separately and already partly done: modifications (strip `-P00xxx` suffix, already
   in `_piid_key`) and slash-pairs (`parent/order`). USASpending confirms the heuristic later.

## Next (immediate, in order)

1. **Apply pending migrations to prod** (0031–0035 not yet on Railway; 0030 and below already applied):
   ```
   psql $RAILWAY_URL -f migrations/0031_dow_contract_releases.sql
   psql $RAILWAY_URL -f migrations/0032_dow_raw_html.sql
   psql $RAILWAY_URL -f migrations/0033_dow_awards.sql
   psql $RAILWAY_URL -f migrations/0034_dow_award_purpose.sql
   psql $RAILWAY_URL -f migrations/0035_dow_awards_v2.sql
   ```
   After applying, sync DoW data: `pg_dump strata --no-owner --no-acl --data-only -t dow_contract_releases -t dow_awards | psql $RAILWAY_URL`

2. ~~**Fix `ingest_icfs.py` incremental to add second pass by `action_taken_date`**~~ — **DONE.**

3. ~~**Set up Railway crons**~~ — **DONE.** `scheduler.py` deployed as a Railway worker: full ICFS pipeline at 03:00 UTC daily + DoW window poller (90s cadence 4:55–5:20 PM ET, 7 min 5:20–6:30 PM ET, evening sweep at 8 PM ET).

4. **Alerting for SAT-PPL-20211207-00172** — Stas asked for this specifically. Watch for new filings/actions/pleadings where `file_number = 'SAT-PPL-20211207-00172'` and send an email when something new appears. Needs: a `watched_file_numbers` table or config, a check script that runs after each ingest, and an email send (sendgrid or SMTP).

## DoW extraction (redesigned v2 — regex-primary + LLM semantic; full corpus run needed)

Extractor: `apps/ingest/extract_dow_awards_v2.py`. Regex owns the award list (PIIDs,
city/state, amounts, completion date, contracting activity); one LLM call per release
supplies semantic fields (company name, purpose, program_hint, action_type) and an
independent PIID enumeration. Merge is regex-authoritative, joined on a normalized PIID
key; `awardees[*].pairing_confidence` = `agreed` | `regex_only`. `llm_only` PIIDs are
logged/stored in `llm_raw_response.llm_only_piids` as a regex-brittleness research signal.
Spec: `docs/specs/dow_extraction.md` (rewritten for v2). Enrichment design (next major
build): `docs/dow_enrichment.md` — 3-lane PIID enrichment (SAM live / SAM CSV / USASpending),
71% backfill vs ~15–20% real-time coverage (progressive-enrichment model), F-type parent ladder.

Schema: PIID is embedded per awardee (`awardees[*].piid`); the standalone `piids` column was
dropped in migration 0036. Unused 15-field-era columns remain but v2 never writes them
(`funding_at_award`, `instrument_type`, `pricing_type_raw`, `purpose_excerpt`, `flags`) —
candidates for a drop migration.

- **Run full corpus**: `python apps/ingest/extract_dow_awards_v2.py` — ~2,945 releases remaining (~$3, gpt-4o-mini). Apply migration 0036 to prod first.
- `--reprocess` re-runs regex + LLM for already-extracted releases (incurs LLM cost — not free like the old validator re-parse)
- After full run: SAM/USASpending enrichment keyed on PIID, then `dow_canonical_entities`
- **DoW UI next**: award-level table — columns: Date, Awardee (raw), PIID, Amount, Purpose, Activity, Confidence

## DoW multi-award IDIQ ceiling mis-attribution (BUG — investor-facing, priority)

The extractor stamps a **shared program ceiling** onto each awardee individually, massively
overstating award value on the `/dow` screen. When one DoD announcement lists multiple
awardees sharing a single IDIQ ceiling, that ceiling is NOT per-awardee — the real value is
the small **obligated-at-award** figure. `docs/findings.md` already notes "ceiling ≠
obligated," but the extractor doesn't act on it. Same trap exists in SAM data (e.g. NSNS
$4.8B shared across 5+ awardees).

**Fixture — the Andromeda award (announced April 7, 2026):** 14 companies (Anduril
`FA881926DB0011`, Astranis `DB013`, BAE `DB006`, General Atomics `DB008`, Intuitive Machines
`DB014`, L3Harris `DB003`, Lockheed `DB004`, Millennium `DB005`, Northrop `DB001`, Quantum
`DB002`, Redwire `DB012`, Sierra Space `DB007`, True Anomaly `DB009`, Turion `DB010`) share
ONE `ceiling $1,843,000,000` FFP IDIQ; only **$1,400,000 obligated at award** — total, across
all 14 (~$100K each). Strata's DoW screen showed `Intuitive Machines · FA881926DB014 ·
$1,843,000,000 · award` — overstating IM's real obligation by ~4 orders of magnitude, which
is exactly why the stock didn't move (it wasn't a $1.8B win). This mis-attribution is what
derailed a whole tradability analysis — the "material award" was a phantom ceiling.

**Fix:** detect multi-awardee shared-ceiling announcements. Signals in the DoD text: multiple
awardees + sequential PIIDs in one announcement, "were awarded a **ceiling** $X," "**$Y are
being obligated at time of award**," "N offers were received." Capture the obligated amount as
the awardee's amount; keep the ceiling separately; flag the row "1 of M · shared $X IDIQ
ceiling." This is a credibility fix for the screen investors actually see.

## Next (priority order)

- **Pleadings document text + LLM summary.** Pleadings show on entity timeline with type + file_number only; no content fetched or summarized yet. Need a `fetch_icfs_pleading_documents.py` + LLM pass analogous to the notice pipeline.
- **STA Grant PDF extraction.** `grant_doc_url` is now populated per Viasat filing (after `fetch_icfs_filing_details.py` runs). Fetch + extract text from those PDFs to summarize grant terms/conditions on the timeline.
- ~~**Remove Viasat hardcoding from `fetch_icfs_filing_details.py`.**~~ Already done — query runs for all filings with `detail_fetched_at IS NULL`.
- **Complete extraction pipeline after backfill.** Filings extraction done (13k rows). Pleadings backfill still running (~page 1105/5526 as of 2026-07-01). When done, run: `extract_icfs_pleadings.py`, `extract_icfs_notice_entities.py`, `extract_icfs_notice_summaries.py`. All scripts are incremental and safe to run at any time.
- **Non-DA notice documents (985 notices).** All 512 DA notices fetched and LLM-processed. The 985 non-DA SES/SAT notices were blocked on `www.fcc.gov` but the fix is confirmed: query `api2.fcc.gov/api/exp/v1.0.0/edocspublic/documents?reportNumber={number}` to get a record ID, then fetch `docs.fcc.gov/public/attachments/DOC-{id}A1.txt`. Tested against SES-02821 — works end to end. Needs a second fetch path in `fetch_icfs_notice_documents.py` for notices where `da_number IS NULL`.
- **Show Stas the signal events feed and entity timeline.** `/admin/icfs/signals` and `/admin/icfs/entity/{id}` are built. The signals page already surfaces CFIUS referrals, DIP context, transfers of control, and coordinated surrenders from just 5 months of data. Entity timeline will be most compelling once Viasat's historical SAT activity is in the DB (needs full backfill).
- **Tier 2 cross-source entity linking** (`icfs_canonical_entities` → global `canonical_entities`): deliberately deferred, human-gated, not built. See the semi-decision in `docs/decisions.md` (2026-06-23) for the design direction already agreed.
- **FRN as a stronger filer identity** than name-matching — mentioned early, never followed up. Worth revisiting once cross-source linking (Tier 2) actually needs a stronger identifier than exact name match.
- Minor cosmetic: `event_description` double-period when a company name already ends in one (e.g. "S.a.r.l..") in `extract_icfs_entities.py`/`extract_icfs_pleadings.py`/`extract_icfs_notice_entities.py`.
- **UCC/credit — pending second module, not yet started.** Gated on the customer confirming the Altice signal (coordinated subsidiary liens) is actually tradeable, not just interesting. Build only on a strong trade-relevant yes. If/when it's a go: UCC lien filings (state-level, starting with NY/DE), mortgage/recording-office documents (county clerk records), court dockets & complaints (PACER/CourtListener-style sources), then lien-perfection analysis as its own lens.
- Add an explicit ambiguity note on cluster detail pages (collisions are possible for same normalized name).
- Show lightweight disambiguation hints on cluster detail pages (article domains + HQ country/region mentions when present).
- Add a second LLM pass per top cluster to generate an evidence-backed brief: what happened, why it matters, what to watch.
    - Proof of concept for: AI synthesis of “friction over time” to answer: “What does this all mean?”
- The first sellable MVP for the first wedge (litigation finance or special situations or private credit portfolio monitoring)

## Pending cleanup

- **Run `apps/ingest/backfill_dow_raw_html.py` then delete it.** After the HTML backfill completes and all rows have `raw_html`, delete the script — `ingest_dow_contracts.py` stores `raw_html` on all new records going forward.

## Tabled

- FreightWaves ingestion — was the original v0 bootstrap source; not aligned with the primary-source/credit wedge for now.

## Done

- Parse SEC RSS feeds (press releases, litigation releases, administrative proceedings).
- Extract candidate website domains from `raw_html` and store as suggestions (not authoritative).
- ICFS v0: dedicated `icfs_filings`/`icfs_pleadings_and_comments`/`icfs_public_notices` tables, reverse-engineered live ingestion, polymorphic `extracted_entities`/`extracted_events` (any source, not just news), within-source canonical collapse (`icfs_canonical_entities`), and a working `/admin/icfs` UI — proven end-to-end on a small real-data slice, full backfill still running.
- ICFS notice intelligence pipeline: `fetch_icfs_notice_documents.py` (DA notices via `docs.fcc.gov`) → `extract_icfs_notice_entities.py` (file_number → company lookup, no LLM) → `extract_icfs_notice_summaries.py` (per-company prose slice + LLM structured output: `summary`, `signal_tier`, `signal_reason`, `source_excerpt`). First 149 events processed; 13/149 (~9%) classified signal. CFIUS referrals, DIP context, and transfers of control surfaced automatically.
- Signal events global feed (`/admin/icfs/signals`): all signal-tier notice events across all entities, most recent first, with LLM-generated reason badge. Entity timeline (`/admin/icfs/entity/{id}`): chronological feed of all FCC activity for one canonical entity — filings, pleadings, notice appearances with summaries. Notice detail page (`/admin/icfs/notices/{id}`): per-notice company list with summaries and collapsible source excerpts for hallucination verification.
- Site redesign (Stripe/Carta-inspired) and a real marketing landing page at `/`.
- **DoW contracts ingestion**: `ingest_dow_contracts.py` + `fetch_dow_html.py`, `dow_contract_releases` table with `raw_html` and `raw_text`, `/admin/dow` UI (release list + detail).
- **DoW window poller + daily scheduler**: `scheduler.py` — ICFS pipeline at 03:00 UTC + DoW window polling (90s/7min cadence 4:55–6:30 PM ET, evening sweep 8 PM ET), logged to `ingest_runs`.
- **DoW award extraction**: `extract_dow_awards_v2.py` — regex-primary (award list, PIIDs, city/state, amounts, dates, activity) + one LLM call per release for semantic fields (name, purpose, program_hint, action_type) and independent PIID enumeration. Regex-authoritative merge on normalized PIID key; per-awardee `pairing_confidence`. Superseded the LLM-only 15-field extractor (`extract_dow_awards.py`, deleted). PIID embedded per awardee; `piids` column dropped in 0036.
- **DoW UI**: `/admin/dow/contracts` — release list with per-award cards showing purpose, amounts, PIIDs, activity; collapsible raw text + LLM JSON.
