# To Build

## Next

- **Run the real ICFS backfill.** Only a small test slice is ingested so far (~200 rows each of Filings/Pleadings/Notices, vs. real totals of ~140K/~110K/~89K). Full backfill at the deliberately conservative 10s/request pace (`REQUEST_DELAY_SECONDS` in `apps/ingest/ingest_icfs.py`, set this slow because ICFS's robots.txt disallows all bots) takes ~47 hours — run as a long-lived background process, then `extract_icfs_entities.py` / `extract_icfs_pleadings.py`.
- **Run Public Notices document fetch + extraction at scale.** Pipeline is proven (10/10 real fetches + resolutions in testing) but only run on a small batch — `fetch_icfs_notice_documents.py` then `extract_icfs_notice_entities.py`. Only notices with `da_number` (~56% of the table) are fetchable, via the direct `docs.fcc.gov/public/attachments/DA-{da_number}A1.txt` link — `www.fcc.gov`'s search-results page is blocked by Akamai-style bot mitigation at the protocol level (confirmed against curl, httpx, *and* headless Playwright), so report-number-only notices stay unresolved with no known workaround.
- **Show Stas the actual ICFS UI and get feedback.** The spec's (`docs/specs/2026-06-23-icfs-v0.md`) definition-of-done explicitly requires this — hasn't happened yet now that there's something real to show.
- **Tier 2 cross-source entity linking** (`icfs_canonical_entities` → global `canonical_entities`): deliberately deferred, human-gated, not built. See the semi-decision in `docs/decisions.md` (2026-06-23) for the design direction already agreed.
- **Public Notices LLM narrative extraction**: the fetched `document_text` contains real beneficial-ownership/foreign-control detail (parent companies, individual owners with equity %, national-security review flags) — genuinely valuable, but needs an LLM pass on top of the file_number-based structural resolution already built. Explicitly shelved for now in favor of the cheap path.
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
- ICFS v0: dedicated `icfs_filings`/`icfs_pleadings_and_comments`/`icfs_public_notices` tables, reverse-engineered live ingestion, polymorphic `extracted_entities`/`extracted_events` (any source, not just news), within-source canonical collapse (`icfs_canonical_entities`), and a working `/admin/icfs` UI — proven end-to-end on a small real-data slice, full backfill still to run.
- Site redesign (Stripe/Carta-inspired) and a real marketing landing page at `/`.
