# To Build

## Next

- **Complete extraction pipeline after backfill.** Filings extraction done (13k rows). Pleadings backfill still running (~page 1105/5526 as of 2026-07-01). Public notices backfill starts automatically after pleadings. When done, run in order: `extract_icfs_pleadings.py`, `fetch_icfs_notice_documents.py` (at scale — currently only 50 fetched), `extract_icfs_notice_entities.py`, `extract_icfs_notice_summaries.py`. All scripts are incremental and safe to run at any time.
- **Run Public Notices pipeline at scale after backfill completes.** Document fetch proven on first 50; full table will be much larger. DA-numbered notices fetchable via `docs.fcc.gov/public/attachments/DA-{da_number}A1.txt`. Non-DA notices remain blocked by Akamai on `www.fcc.gov`. **Potential workaround unverified:** ECFS + EDOCS sanctioned APIs (free `api.data.gov` key) — test coverage against known non-DA notice numbers before investing. See `docs/decisions.md` 2026-07-01.
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
