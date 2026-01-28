# Decisions

## 2026-01-28 — Keep event_type/transaction_role as text for v0
- Decision: Use text columns for `event_type` and `transaction_role` in `extracted_events` during v0.
- Rationale: Faster iteration while taxonomy is still evolving; avoid enum migration churn.
- Revisit: Move to enums once labels stabilize (v1).

## 2026-01-28 — Conservative canonicalization for v0
- Decision: Treat `canonical_entities` as “best-known nodes,” not perfectly resolved identities.
- Rule: Prefer duplicates over wrong merges; only auto-merge with strong identifiers.
- Scope: Only canonicalize `entity_type` in `{operating_company, financial_sponsor, lender}` for v0.
- Status: `provisional` means “no jurisdiction or strong identifier yet”; `confirmed` requires jurisdiction (v0).
- Next: Add identifiers (domain/CIK/address) and a review workflow to safely reduce duplicates.
