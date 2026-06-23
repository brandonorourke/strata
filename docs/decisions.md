# Decisions

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

## 2026-06-23 — Pivot from news to primary-source records as the v0 wedge
- Decision: De-prioritize general news as the primary signal. Shift v0 ingestion focus to primary-source documents — UCC lien filings, mortgage/recording-office documents, court dockets & complaints, and direct government regulatory portals — starting with the FCC's ICFS (International Communications Filing System), then broader FCC RSS (dockets, rulemakings, commissioner statements).
- Rationale: First customer conversation (Carronade, public credit PM — see `docs/customer_conversations/`) validated this directly, not hypothetically:
  - He has a live credit position (Altice) where a cluster of subsidiaries filed coordinated all-asset liens to JPMorgan on the same day, then debtor-change amendments months later — exactly the kind of structured-record signal news coverage wouldn't surface, and one he isn't analyzing himself because it's outside his skill set (legal/lien analysis), not because it's low-value.
  - He confirmed none of his existing paid tools (Reorg, CreditSights, AlphaSense) do UCC monitoring or lien-perfection analysis. "Knowing if liens were perfected would be huge — it changes rates and recoveries" — this is the sharper, dollar-linked version of the original "UCC/courts" idea, validated by a real trade (Talen Energy: bought unsecured paper because the lien wasn't perfected within the bankruptcy code's 30-day safe harbor).
  - He manually monitors FCC's ICFS portal for satellite/space-related positions (e.g. Viasat) and calls it "impossible to navigate." He currently pays a law firm for FCC-commissioner/government intelligence — proven willingness to pay for exactly this category of monitoring, not just stated interest.
- Scope: SEC + DOJ enforcement/litigation ingestion stays active — it's still a relevant entity/event signal and overlaps with the same primary-source thesis. FreightWaves ingestion is tabled; it was the original v0 bootstrap source and isn't tied to the credit/special-sits primary-source wedge.
- Effect on roadmap: pulls "UCC/courts as a premium lens" forward from v2 (see Strata OS Vision wedge progression) into the v0 wedge itself.
