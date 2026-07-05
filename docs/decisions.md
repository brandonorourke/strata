# Decisions

## 2026-07-02 — Nav structure: data source as top-level, analysis vs. raw as sub-sections
- Decision: Sidebar organized as source → sub-type. `FCC / ICFS` is the current top-level section, with `Analysis` (All Companies, Signal Notices, Contested Filings) and `Source Data` (Filings & Actions, Pleadings, Notices) as sub-labels within it.
- Rationale: Designed to scale — new data sources (Dept of War, SEC, etc.) get their own top-level section with the same Analysis/Source Data split inside.

## 2026-07-02 — Contested filings query is slow; deferred fix
- Decision: The `/admin/icfs/contested` query (~15s) uses a correlated ILIKE join (`p.file_number ILIKE '%' || f.file_number || '%'`) that can't be indexed. Acceptable for now since it's an admin-only page.
- Proper fix: Add a `filing_id FK` column to `icfs_pleadings_and_comments`, backfill it during detail fetch, and replace the ILIKE join with a normal indexed join. Deferred until query latency is actually a problem.
- Note: The per-company version (entity page contested tab) is fast because the outer loop is small (~50 filings vs. 1,400+).

## 2026-01-28 — Keep event_type/transaction_role as text for v0
- Decision: Use text columns for `event_type` and `transaction_role` in `extracted_events` during v0.
- Rationale: Faster iteration while taxonomy is still evolving; avoid enum migration churn.
- Revisit: Move to enums once labels stabilize (v1).

## 2026-01-28 — Conservative canonicalization for v0
- Decision: Treat `canonical_entities` as “best-known nodes,” not perfectly resolved identities.
- Rule: Prefer duplicates over wrong merges; only auto-merge with strong identifiers.
- Scope: Only canonicalize `entity_type` in `{operating_company, financial_sponsor, lender}` for v0.
- Status: drop explicit status; treat `confirmed_domain` as the confirmation signal.
- Next: Add identifiers (domain/CIK/address) and a review workflow to safely reduce duplicates.

## 2026-01-28 — Individuals excluded from v0 canonical UI
- Decision: Individuals may be extracted but are not canonicalized or shown in v0 screens.
- Rationale: Investor screens should focus on companies and avoid noise until person-level features are defined.

## 2026-01-28 — UI styling approach
- Decision: Keep UI styling minimal and custom in v0; avoid UI frameworks for now.
- Note: Consider Tailwind later if the UI expands or needs faster iteration.

## 2026-01-29 — Extracted entities are per-article mentions
- Decision: Treat `extracted_entities` as per-article mentions to avoid false global merges on name alone.
- Impact: One entity row per article + name; canonicalization handles cross-article identity.

## 2026-02-05 — Defer global entity resolution; use time-window clustering
- Decision: Defer a globally deduped canonical company database in v0. Use rolling-window clustering (7d/30d) by `(entity_type, legal_name_normalized)`.
- Rationale:
  - Global identity resolution is expensive and brittle early, with high wrong-merge risk.
  - Primary UX is time-based (“Most Changed / Most Notable”), where collision risk is lower than all-time identity matching.
  - Prefer occasional collisions over heavy manual linking or brittle heuristics that imply false certainty.
- UX:
  - Main screen shows clustered names for the last 7/30 days.
  - Detail pages should include an explicit ambiguity note (planned): clusters may contain collisions.
  - Show lightweight hints when available (planned): article domains and HQ region/country mentions.
- Data to keep capturing (for future canonicalization):
  - Per-article entity mentions (raw mentions + normalized name).
  - Optional fingerprint fields when present (hq_country, hq_region, sector keywords, etc.).
  - Source URLs/domains per article (domain extracted outside the LLM call).
- Future canonical path:
  - Separate linking process can promote clustered mentions into canonical entities when strong identifiers appear (e.g., consistent domain, explicit HQ, CIK/LEI).
  - AI-assisted linking + manual review is optional later, not required for v0 usefulness.
- Interpretation layer (planned):
  - After clustering, run a second LLM pass per top cluster to generate an evidence-backed brief:
    - What happened
    - What it implies / why it matters
    - What to watch next

## 2026-02-07 — Schema ordering convention
- Decision: Treat DB schema + migrations as source of truth; always regenerate `strata_core/schema.local.sql` from the DB.
- Convention: When adding ORM columns, append at the end for readability (do not reorder existing fields).

## 2026-06-16 — Pivot from news to primary-source records; ICFS confirmed as the first build, UCC pending
- Decision: De-prioritize general news as the primary signal ("upstream of the news — monitor primary sources at filing, before coverage"). Shift focus to primary-source documents: direct government regulatory portals, UCC lien filings, mortgage/recording-office documents, and court dockets & complaints.
- Decision rule (sequencing, not a flat list): **ICFS (FCC's International Communications Filing System) is the confirmed first build** — Stas (first customer conversation, public credit PM — see `docs/customer_conversations/`) wants it directly for his Viasat equity position, it has the least competition and most buildability, and no visible incumbent does FCC-for-investors monitoring. **UCC/credit is a pending second module**, gated on Stas confirming the Altice signal is actually tradeable — build it only on a strong trade-relevant yes.
- Rationale, validated by hand (not hypothetically):
  - **Talen Energy**: reconstructed a safe-harbor/preference trade end-to-end from primary sources (county mortgage filing + bankruptcy docket + entity resolution). The computable trigger (mortgage filed outside the 30-day safe harbor window) is real and machine-detectable; the judgment layer (open-end mortgage vs. revolving facility nuance) still needs a human.
  - **Altice**: footprint-monitoring surfaced a coordinated multi-entity JPMorgan lien transaction across the Cablevision subsidiary footprint (same-day origination across entities, including a transmitting-utility filing) — invisible filing-by-filing, visible only via entity-family resolution. Correction to an earlier read of this: the follow-up Feb amendments turned out to be **zip-code corrections, a false positive** caught on closer review — not a meaningful second signal. This is exactly why the product needs to surface *what changed*, not just *that something changed*. The engine surfaces candidates; a human still adjudicates benign-refi-vs-LME (can't be determined from UCC data alone) — that's the product's boundary, not a gap to hide.
  - None of Stas's existing paid tools (Reorg, CreditSights, AlphaSense) do UCC monitoring or lien-perfection analysis. He manually logs into the ICFS portal and calls it "impossible to navigate," and currently pays a law firm for FCC-commissioner/government intelligence — proven willingness to pay, not just stated interest.
- Architecture decision: one engine, two adapters — ingest document → extract entities → resolve against a watchlist (or create pending entities) → LLM summary with citations → score/cluster/alert. Works identically for ICFS and UCC; domain differences live only in the ingestion adapter. The moat is entity resolution + cross-source assembly that compounds, not the LLM (commodity). Framed for ICFS as "compression is the product": ~48 raw filings → ~20 clusters → 5-8 alerts → 1-3 worth reading.
- Competitive landscape: 9fin (well-funded, $1.3B valuation, 300+ credit firms) is building the same proactive-monitoring/cited-extraction thesis but at the covenants/cap-table/financials layer — apparently not registry-level UCC/lien-perfection (unverified, confirm with Stas). UCC monitoring is partly commoditized already (Baselayer, Springstreet, CSC, LexisNexis) but framed for compliance/lending, not investor-alpha — the distressed-perfection/cross-source angle is the differentiation to defend. FCC-for-investors has no visible incumbent.
- Scope: SEC + DOJ enforcement/litigation ingestion stays active for now (still a relevant entity/event signal). FreightWaves is tabled — it's the kind of trade-pub/news source this pivot explicitly moves away from.
- Effect on roadmap: pulls "UCC/courts as a premium lens" forward from v2 (see Strata OS Vision wedge progression) into the v0 wedge — but as a *second*, gated module behind ICFS, not built in parallel.
- Naming: product is "Strata Terminal," corporate entity is "Proofgraph, Inc." — settled, not to be relitigated.

## 2026-06-23 — Two-tier entity resolution: per-source collapse, human-gated cross-source link
- Decision (semi-decision — direction agreed, not yet implemented): split entity resolution into two tiers instead of one global matching function.
  - Tier 1 (automatic): collapse entities *within* a single structured source by normalized name. Safe because structured primary sources (ICFS now, UCC/courts later) give exact applicant/filer name strings straight from the source's own database — not LLM-guessed mentions from prose.
  - Tier 2 (human-gated): a person explicitly confirms a per-source entity is the same as a global `canonical_entities` row. No automatic merge ever crosses the source boundary. This generalizes the existing confirmed-domain pattern (`/admin/canonicals/{id}/confirm-domain`) to the source boundary itself rather than inventing a new mechanism.
- Why this was needed: ICFS-derived entities (e.g. "Viasat") can never reach the same canonical as SEC-derived "Viasat" today, because `link_entities.py` requires `hq_country`/`hq_region` to attempt a cluster match (`if not extracted.hq_country or not extracted.hq_region: continue`), and ICFS's index data has no geography field — so ICFS entities are silently skipped, never even reaching the "create new canonical" fallback. Loosening that gate symmetrically (letting bare name matches through generally) would reopen the false-merge risk it exists to prevent (2026-01-28 decision: "prefer duplicates over wrong merges"). Tiering the decision keeps automatic merging where it's actually safe (within one structured source) and keeps a human in the loop exactly where the risk lives (asserting identity *across* sources).
- Why this is more tractable than it sounds: the 2026-06-16 pivot away from news as the primary signal already shrank the hard case — news/LLM-derived entities are the ambiguous ones the geography gate was built for; structured primary sources are exactly the ones where within-source collapsing is cheap and low-risk. Near-term volume is also small: ingestion is watchlist-driven (one name, Viasat, to start), not broad/untargeted, so the number of cross-source links needing human confirmation stays in the tens, not thousands, for the foreseeable v0/v1 horizon.
- Not free: tier 1 isn't one generic algorithm — every new structured source needs its own name-normalization logic (debtor names, party names, applicant names each have different conventions), bounded work per source rather than open-ended risk.
- Open, not decided: whether the per-source canonical layer is a new table per source or a `source_type`-scoped view over `canonical_entities` with a separate link table.
- Deferred, not yet a bottleneck: a candidate-suggestion mechanism for the human-confirmation UI (so a person isn't browsing blind) will be needed once the canonical-entity count outgrows what's reviewable by eye — fine to defer until that's the actual constraint.

## 2026-07-01 — FCC notice taxonomy: DA = delegated authority; signal filter is action type, not DA number

- **DA = delegated authority** (bureau/staff-level action), not "Declaratory Action." FCC's own EDOCS definitions confirm: documents issued by a bureau/office under authority delegated by the Commission get a DA number; documents requiring a full Commissioner vote get an FCC number. Both notice families use the phrase "pursuant to delegated authority" in the body — the DA number is an administrative publishing distinction (which report series the batch was assigned to), not an indicator of whether an outcome occurred.
- **DA/non-DA is NOT a reliable signal/noise filter for satellite (SAT/SES) notices.** Both DA and non-DA "Actions Taken" satellite notices contain real dispositions (grants, surrenders, modifications, assignments). Confirmed by direct document comparison: a non-DA notice (SES-02821) contained Viacom surrendering seven earth-station authorizations at once — a material corporate event — while a DA notice (SAT-01961) contained routine STA grants. Using `da_number IS NOT NULL` as a signal filter for satellite notices would wrongly discard the surrender and wrongly keep operational noise.
- **The actual signal filter for satellite notices is action type:**
  - Signal: surrender of authorization, assignment/pro-forma modification (ownership change), consummated transaction, modification reflecting assignment, granted-with-conditions (what are the conditions?)
  - Noise: routine STA/TT&C/LEOP operational grants (short-term technical authority for a specific satellite operation)
- **Surrender events carry bonus signal:** FCC bond requirements ($1M+, escalating) become due and payable on default or surrender — a fleet surrender (like Viacom's) can have financial/bond implications beyond the license event itself.
- **DA/non-DA distinction DOES hold for ITC/international notices:** DA-numbered ITC notices carry ownership chains, CFIUS/national security narrative, LOA conditions — the high-value content. Non-DA ITC notices are accepted-for-filing receipts with no outcome content. The contrast that doesn't generalize: ITC non-DA = queue receipt; satellite non-DA = real disposition.
- **Two notice families need separate extraction logic:**
  - ITC/international notices → extract ownership structure (% + nationality), CFIUS referral flag ("referred to the Executive Branch agencies"), LOA conditions flag ("Petition to Adopt Conditions"), transaction narrative
  - SAT/SES satellite notices → extract action type + entity + surrender/assignment/consummation events; skip routine STA/TT&C/LEOP entries

## 2026-07-01 — LLM signal classification for notice events: structured output over keyword matching

- **Decision: use LLM structured output to classify signal vs. routine, not keyword matching.** Each extracted entity-notice event gets a `signal_tier` ("signal"/"routine") and `signal_reason` (5-10 word phrase) alongside the `llm_summary`, returned as a single structured JSON call on the same prose excerpt. No separate classification pass.
- **Why keyword matching was rejected:** "STA granted" appears in both routine grants (Intelsat's 50th transponder renewal) and genuinely important cases (first authorization for a new constellation). "Transfer of control" can be a PE fund shell restructuring or a foreign acquisition. "Dismissed" can be a small telco that forgot to respond or Astra Space shutting down operations. The classifier needs context — exactly what the LLM already has when summarizing.
- **Prose slice as the LLM input:** rather than sending the full notice document (3,000–20,000 chars, 30+ companies), the script slices the paragraph block for the specific filing (`file_number` as anchor, regex to next file number as end). Each LLM call is ~300–500 tokens. This keeps cost near zero at ICFS volumes and makes the watchlist gate explicit: companies not in the DB never get an LLM call.
- **`source_excerpt` stored for verification:** the exact prose block sent to the LLM is persisted on `extracted_events.source_excerpt` and surfaced via a "show source ▾" toggle in the UI. Readers can verify any summary against the FCC's original language without leaving the page. Addresses hallucination risk for a product where accuracy is trust-critical.
- **Empirical signal rate:** full run on 1,169 events → 156 signal (13.4%), 1,013 routine. Top signal categories: CFIUS/national security referral (21), foreign ownership + national security review (9), grant with national security conditions (17), service discontinuances (20+), ownership/transfer of control (7+), STA/LOA surrenders or withdrawals (13+), DIP contexts (2). Signal events include: SN Space Systems LLC/Limited CFIUS referral, Verscom CFIUS referral, Ligado Networks DIP modification, Astra Space dismissal with prejudice, Yonder Media transfer of control, Gridiron Fiber and Uniti Fiber transfers of control, Astranis Projects ownership change, Globalstar DIP grant, and coordinated same-day discontinuances by Jaguar/MetroNet/Vexus/Climax (TEL-02654) and Accipiter/Gridiron (TEL-02647).

## 2026-07-01 — SES notices vs. icfs_filings: what each source adds

- **SES notices and `icfs_filings` are complementary, not redundant.** The filing (`SES-STA-*` rows in `icfs_filings`) is the request Viasat submitted. The SES Actions Taken notice is the FCC's confirmation that STAs were granted. Both refer to the same file numbers. Empirical example: SES-02876 contained 28 separate Viasat STA grants for Viasat-3F1 earth stations across the US (Manchester KY, Ashville AL, Las Vegas NV, Carlton MN, etc.) — all 28 file numbers (`SES-STA-20260527-*`) are also rows in `icfs_filings` with `action = 'Grant of Authority'`.
- **What the notice adds that filings don't have:** the aggregated narrative, specific earth station locations and frequency bands (27.5–28.35 GHz Ka-band), the satellite name (Viasat-3F1, S2917), and the temporal cluster that 28 grants fired in the same week — interpretable as rapid ground-infrastructure expansion for Viasat-3F1. The filing row just has file_number + applicant + action type + date; no geographic or technical detail.
- **Third-party relationships only visible in notices:** SES-02876 also contained Intelsat License LLC operating TT&C earth stations for Viasat-3 F2 and F3 satellites — filed under Intelsat's call signs, invisible to a Viasat-only query on `icfs_filings`. Cross-entity relationships of this kind (vendor/operator grants relating to a watched entity's assets) are notice-only signals.
- **Current coverage gap:** all 443 SES notices have `da_number = NULL` → `fetch_icfs_notice_documents.py` skips them → no SES notice text in the DB. SES-02876 was reviewed manually. SES activities are all in `icfs_filings` (1,496 Viasat filings include many `SES-STA-*`), so the grant fact is captured, but not the narrative or cross-entity context. Workaround path: ECFS/EDOCS API (see below).

## 2026-07-04 — DoW extraction: LLM-only; deterministic validators guard amounts and PIIDs

- **Decision: DoW extraction is LLM-only.** Regex is not a parallel extractor.
  Deterministic validators guard amounts and PIIDs (format check, cross-field
  obligated ≤ ceiling, and value-grounding to source text). A flagged row routes to
  review; it is never discarded.
- **Rationale:** A 100-paragraph pilot (spanning 2014–2026 date range) showed the LLM
  materially outperforms regex on every field except amounts — and amounts agreed at
  ceiling 91%, obligated 98% before any regex tuning. The remaining regex bugs
  (missed PIID formats, two completion-date phrase variants, contract-type unicode
  normalization) were fixable, but the gap on flexible fields (program names, awardee
  sets in unusual formats, contract-type compound descriptions) was fundamental — not
  patchable with more patterns. Maintaining two extractors to gain determinism on
  fields where both methods agree would add ongoing maintenance cost without accuracy
  benefit.
- **Value-grounding closes the fabrication risk on money fields.** The LLM's known
  failure mode (confident hallucination) is worst on amounts and identifiers. The
  value-grounding validator (confirm the digit string appears in raw_text) is
  mechanically incapable of false-passing a hallucinated amount — it can only pass
  if the number is actually in the source. This gives the same fabrication protection
  regex provided, without the maintenance cost of a second extractor.
- **Field-trust policy in production:**
  - LLM primary for all fields.
  - Validators run post-extraction; failures flag rows for review, never auto-discard.
  - For amounts specifically: a grounding failure (value not in source) is the most
    severe flag — treat as likely hallucination, hold for human review before use.
  - For obligated specifically: `val_obligated_lte_ceiling=FALSE` almost always means
    field-swap or fabrication — the one error class this product cannot afford.
- **What "regex is not an extractor" means operationally:** `extract_dow_regex.py`,
  `extract_dow_llm.py`, and `report_dow_extraction.py` are pilot artifacts, to be
  deleted after `0034_dow_awards_v2.sql` migration and `extract_dow_awards.py`
  deployment. The regex patterns developed in the pilot (PIID grammar, state-name
  mapping, completion-date phrase variants) live on as validator logic, not as an
  extraction path.

## 2026-07-04 — DoW entity extraction: source-scoped canonical table, (name, location) as identity key

- **Decision: DoW entities get their own `dow_canonical_entities` table**, mirroring the `icfs_canonical_entities` pattern — not written against the ICFS table or the global `canonical_entities` table.
- **Identity key within DoW: `(normalized_name, location)`**. Contract text consistently provides city + state (`"Viasat Inc., Carlsbad, California"`), making the tuple a reliable disambiguator within DoW data. Two records with the same normalized name but different locations are treated as distinct entities; two with matching tuple collapse to one canonical row.
- **Cross-source linking (DoW ↔ ICFS ↔ global) stays human-gated and deferred**, consistent with the 2026-06-23 two-tier decision. The unified Viasat timeline (DoW contracts + ICFS regulatory activity on one view) becomes possible when a bridge row is manually confirmed — not before.
- **Reuses `extracted_entities` / `extracted_events`** with `source_type = 'dow_contract'`, consistent with how ICFS already uses those polymorphic tables. The one acknowledged wart: `extracted_entities` has an `icfs_canonical_entity_id` FK column baked in — a source-specific leak into the shared table. Accepted for now; a future refactor could move these to a generic linking table.

## 2026-07-04 — Store raw HTML for DoW contract releases

- **Decision: store `raw_html` on `dow_contract_releases`** in addition to the extracted `raw_text`. Rationale: scraping is the expensive/fragile step; if the extraction regex changes or breaks, re-parsing from stored HTML is free. Re-scraping 2,957 pages costs ~75 minutes of rate-limited fetching.
- `ingest_dow_contracts.py` stores `raw_html` on all new records going forward. `backfill_dow_raw_html.py` (one-shot script, to be deleted after run) backfills existing records.
- Secondary benefit: raw HTML enables a future preview pane in the UI without an additional fetch.

## 2026-07-01 — FCC ECFS/EDOCS sanctioned APIs as programmatic path (unverified coverage)

- The FCC offers two sanctioned, free-key APIs that bypass Akamai by design — the intended programmatic front door, not a scraping workaround:
  - **ECFS API**: filings, comments, pleadings, and public notices by docket/proceeding. Register at `fcc.gov/ecfs/help/public_api`; uses a free `api.data.gov` key. FCC actively encourages API use over scraping for bulk access.
  - **EDOCS API**: public releases, publications, Federal Register, FCC Record — the document index. Candidate path for non-DA notice documents (the ones blocked by Akamai on `www.fcc.gov`).
- **Auth:** free `api.data.gov` key, one-time registration. Same key system used across US government APIs.
- **Open question (unverified):** whether ICFS/IBFS satellite filings (SES/SAT) are covered by ECFS/EDOCS, or live in a separate ICFS system with a different access path. Third-party scrapers use `fcc.report` (a mirror site) for satellite licensing data — suggesting the satellite data may not be fully exposed through ECFS/EDOCS. Must verify before relying on this path for the satellite pipeline.
- **Strategic implication:** if EDOCS covers the document index for report-number-only notices, this closes the Akamai coverage gap for non-DA satellite notices without headless Chrome or TLS fingerprint manipulation. Test ECFS/EDOCS coverage against known notice numbers (SES-02821, SAT-01961) before investing further in the Akamai workaround path.
