# Decisions

## 2026-01-28 — Keep event_type/transaction_role as text for v0
- Decision: Use text columns for `event_type` and `transaction_role` in `extracted_events` during v0.
- Rationale: Faster iteration while taxonomy is still evolving; avoid enum migration churn.
- Revisit: Move to enums once labels stabilize (v1).
