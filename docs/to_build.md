# To Build

## Tomorrow (2026-07-02)

1. **Sync `icfs_filings` to prod** — local `fetch_icfs_filing_details.py` finishes tonight (~25 min left as of EOD). Then: `psql $RAILWAY_URL -c "TRUNCATE icfs_filings;"` + `pg_dump strata --no-owner --no-acl --data-only -t icfs_filings | psql $RAILWAY_URL`. Safe — no enforced FK from `extracted_entities` to `icfs_filings`.
2. **Set up incremental ingest on prod** — Railway cron job (check plan for scheduled task support) running `ingest_icfs.py` with `ICFS_MODE=incremental` daily. Also run `extract_icfs_entities.py`, `extract_icfs_notice_entities.py`, `extract_icfs_notice_summaries.py` after each ingest to keep summaries current.
3. **Pleadings document text + LLM summary** — new script analogous to notice pipeline.

## Next (priority order)

- **Pleadings document text + LLM summary.** Pleadings show on entity timeline with type + file_number only; no content fetched or summarized yet. Need a `fetch_icfs_pleading_documents.py` + LLM pass analogous to the notice pipeline.
- **STA Grant PDF extraction.** `grant_doc_url` is now populated per Viasat filing (after `fetch_icfs_filing_details.py` runs). Fetch + extract text from those PDFs to summarize grant terms/conditions on the timeline.
- **Remove Viasat hardcoding from `fetch_icfs_filing_details.py`.** Currently filters `applicant_name ILIKE '%Viasat%'`; should run for all filings with `action IS NOT NULL` and `detail_fetched_at IS NULL`.
- **Complete extraction pipeline after backfill.** Filings extraction done (13k rows). Pleadings backfill still running (~page 1105/5526 as of 2026-07-01). When done, run: `extract_icfs_pleadings.py`, `extract_icfs_notice_entities.py`, `extract_icfs_notice_summaries.py`. All scripts are incremental and safe to run at any time.
- **Non-DA notice documents (985 notices).** All 512 DA notices fetched and LLM-processed (1,169 events, 156 signal). The 985 non-DA notices remain blocked by Akamai on `www.fcc.gov` — these include all SES satellite notices, which are the most Viasat-relevant. **Potential workaround unverified:** ECFS + EDOCS sanctioned APIs (free `api.data.gov` key). Test coverage against known non-DA notice numbers (SES-02821, SAT-01961) before investing. See `docs/decisions.md` 2026-07-01.
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

## Tabled

- FreightWaves ingestion — was the original v0 bootstrap source; not aligned with the primary-source/credit wedge for now.

## Done

- Parse SEC RSS feeds (press releases, litigation releases, administrative proceedings).
- Extract candidate website domains from `raw_html` and store as suggestions (not authoritative).
- ICFS v0: dedicated `icfs_filings`/`icfs_pleadings_and_comments`/`icfs_public_notices` tables, reverse-engineered live ingestion, polymorphic `extracted_entities`/`extracted_events` (any source, not just news), within-source canonical collapse (`icfs_canonical_entities`), and a working `/admin/icfs` UI — proven end-to-end on a small real-data slice, full backfill still running.
- ICFS notice intelligence pipeline: `fetch_icfs_notice_documents.py` (DA notices via `docs.fcc.gov`) → `extract_icfs_notice_entities.py` (file_number → company lookup, no LLM) → `extract_icfs_notice_summaries.py` (per-company prose slice + LLM structured output: `summary`, `signal_tier`, `signal_reason`, `source_excerpt`). First 149 events processed; 13/149 (~9%) classified signal. CFIUS referrals, DIP context, and transfers of control surfaced automatically.
- Signal events global feed (`/admin/icfs/signals`): all signal-tier notice events across all entities, most recent first, with LLM-generated reason badge. Entity timeline (`/admin/icfs/entity/{id}`): chronological feed of all FCC activity for one canonical entity — filings, pleadings, notice appearances with summaries. Notice detail page (`/admin/icfs/notices/{id}`): per-notice company list with summaries and collapsible source excerpts for hallucination verification.
- Site redesign (Stripe/Carta-inspired) and a real marketing landing page at `/`.
