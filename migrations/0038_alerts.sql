-- Alerting v1: watchlist alerts for DoW awards + contested ICFS filings.
-- `alerts` is the timestamped record (the latency proof); a stub sender fills
-- sent_at until SendGrid is wired in. `alert_state` holds per-detector watermarks
-- so we detect "new" rows and don't re-alert.

CREATE TABLE alerts (
    id          SERIAL PRIMARY KEY,
    kind        TEXT NOT NULL,          -- dow_match | dow_scan | icfs_match
    subject     TEXT,                   -- watchlist company or release date
    title       TEXT NOT NULL,
    body        TEXT,
    meta        JSONB,                  -- structured payload (piids, file_numbers, etc.)
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sent_at     TIMESTAMPTZ             -- NULL until a sender delivers it
);

CREATE INDEX idx_alerts_created_at ON alerts (created_at DESC);
CREATE INDEX idx_alerts_unsent ON alerts (created_at) WHERE sent_at IS NULL;

CREATE TABLE alert_state (
    key         TEXT PRIMARY KEY,       -- e.g. 'last_dow_award_id', 'last_icfs_ingested_at'
    value       TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
