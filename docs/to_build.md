# To Build

## Next

- **Run extraction pipeline on backfilled data.** Backfill ingested 2022–2026 (date-bounded at 2022-01-01 for demo). Run in order: `extract_icfs_entities.py`, `extract_icfs_pleadings.py`, `fetch_icfs_notice_documents.py`, `extract_icfs_notice_entities.py`. Extraction scripts are already incremental (`entities_extracted_at IS NULL`), safe to run at any time.
- **Run Public Notices document fetch + extraction at scale.** Pipeline proven but only run on small batch — `fetch_icfs_notice_documents.py` then `extract_icfs_notice_entities.py`. DA-numbered notices (~56% of table) are fetchable via `docs.fcc.gov/public/attachments/DA-{da_number}A1.txt` (static host, no bot protection). Non-DA notices link to `www.fcc.gov/edocs/search-results` (Akamai-blocked for automated clients). **Potential workaround unverified:** FCC offers sanctioned ECFS + EDOCS APIs (free `api.data.gov` key, register at `fcc.gov/ecfs/help/public_api`) that bypass Akamai by design — test whether EDOCS API covers non-DA notice documents before writing off that 44%. See `docs/decisions.md` 2026-07-01 for full API details and open coverage question.
- **National security flag extraction from ITC public notice `document_text`.** Two high-value string-match signals extractable without LLM: (1) CFIUS referral flag: "referred to the Executive Branch agencies" → application under national security review; (2) LOA conditions flag: "Petition to Adopt Conditions" → granted with binding DOJ/DHS/DoD commitments. Add boolean columns to `icfs_public_notices` and populate via a pass over already-fetched `document_text`. See `docs/decisions.md` 2026-07-01 for the full signal taxonomy.
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
