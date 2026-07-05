# To Build

## Next (immediate, in order)

1. **Apply pending migrations to prod** (0031–0034 not yet on Railway; 0030 and below already applied):
   ```
   psql $RAILWAY_URL -f migrations/0031_dow_contract_releases.sql
   psql $RAILWAY_URL -f migrations/0032_dow_raw_html.sql
   psql $RAILWAY_URL -f migrations/0033_dow_awards.sql
   psql $RAILWAY_URL -f migrations/0034_dow_award_purpose.sql
   ```
   After applying, sync DoW data: `pg_dump strata --no-owner --no-acl --data-only -t dow_contract_releases -t dow_awards | psql $RAILWAY_URL`

2. ~~**Fix `ingest_icfs.py` incremental to add second pass by `action_taken_date`**~~ — **DONE.**

3. ~~**Set up Railway crons**~~ — **DONE.** `scheduler.py` deployed as a Railway worker: full ICFS pipeline at 03:00 UTC daily + DoW window poller (90s cadence 4:55–5:20 PM ET, 7 min 5:20–6:30 PM ET, evening sweep at 8 PM ET).

4. **Alerting for SAT-PPL-20211207-00172** — Stas asked for this specifically. Watch for new filings/actions/pleadings where `file_number = 'SAT-PPL-20211207-00172'` and send an email when something new appears. Needs: a `watched_file_numbers` table or config, a check script that runs after each ingest, and an email send (sendgrid or SMTP).

## DoW extraction (built — full corpus run needed)

Spec: `docs/specs/dow_extraction.md`. Smoke tested on releases 28 (May 22) and 1 (July 2) — 26 awards, all validators green except one D.C. state code flag (now fixed).

Schema: `dow_awards` has `purpose TEXT` (migration 0034) — 1-2 sentence contract scope description extracted by LLM, populated on all 26 test awards.

- **Run full corpus**: `python apps/ingest/extract_dow_awards.py` — 2,955 releases remaining (~$5, ~2-3hrs). Apply 0033 + 0034 to prod first.
- `--reprocess` flag re-parses stored `llm_raw_response` with zero API cost (useful for validator changes)
- After full run: review validator flag rates, then build `dow_canonical_entities`
- **DoW UI next**: replace card layout with award-level table — columns: Date, Awardee, Purpose, Ceiling, Obligated, Contract Type, PIID, Activity, Flags

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
- **DoW award extraction**: `extract_dow_awards.py` — LLM-only (gpt-4o-mini, one call per release), extracts awardees, PIIDs, ceiling, obligated, contract type, completion date, contracting activity, program hint, and `purpose` (1-2 sentence scope description). 9 validators; `--reprocess` for zero-cost re-validation. Field trust policy in `docs/decisions.md`.
- **DoW UI**: `/admin/dow/contracts` — release list with per-award cards showing purpose, amounts, PIIDs, activity; collapsible raw text + LLM JSON.
