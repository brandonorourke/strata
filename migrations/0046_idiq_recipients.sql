-- UEI → ticker directory (normalized recipient mapping). Lean v1.
-- The children/discovery resolution SEEDS candidate rows; the ticker mapping is
-- human-curated via mapping_status:
--   candidate  — auto-seeded, not yet reviewed (don't trust the rollup)
--   confirmed  — a human verified this UEI belongs to the ticker
--   excluded   — reviewed and deliberately NOT mapped (e.g. an affiliate that
--                shouldn't roll up)
-- Awards roll up to a ticker via usaspending_awards.recipient_uei = idiq_recipients.uei,
-- counting only WHERE mapping_status='confirmed'. LOCAL-ONLY for now.

CREATE TABLE idiq_recipients (
    uei            TEXT PRIMARY KEY,                       -- SAM UEI (award.recipient_uei joins here)
    recipient_name TEXT,
    ticker         TEXT,                                   -- NULL = unmapped / private
    mapping_status TEXT NOT NULL DEFAULT 'candidate',      -- candidate | confirmed | excluded
    seed_uei       TEXT,                                   -- family anchor this UEI was found under
    first_seen_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_idiq_recipients_ticker ON idiq_recipients (ticker) WHERE ticker IS NOT NULL;
CREATE INDEX idx_idiq_recipients_status ON idiq_recipients (mapping_status);
