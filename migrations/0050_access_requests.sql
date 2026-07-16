-- 0050_access_requests.sql
-- Capture "Request access" submissions from the public marketing page.
-- One row per submission (no dedup at the DB level — we want the full inbound trail).

CREATE TABLE IF NOT EXISTS access_requests (
    id         SERIAL PRIMARY KEY,
    email      TEXT NOT NULL,
    source     TEXT NOT NULL DEFAULT 'marketing',   -- where the request came from
    user_agent TEXT,                                 -- best-effort context on the submitter
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_access_requests_email      ON access_requests (email);
CREATE INDEX IF NOT EXISTS ix_access_requests_created_at ON access_requests (created_at DESC);
