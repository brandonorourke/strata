CREATE TABLE ingest_runs (
    id             SERIAL PRIMARY KEY,
    pipeline       TEXT NOT NULL DEFAULT 'icfs',
    started_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at    TIMESTAMPTZ,
    status         TEXT NOT NULL DEFAULT 'running',  -- 'running', 'completed', 'failed'
    failed_script  TEXT,
    script_results JSONB
);
