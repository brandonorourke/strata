CREATE TABLE icfs_ingest_state (
    source_table TEXT PRIMARY KEY,
    backfill_page INT NOT NULL DEFAULT 1,
    backfill_complete BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
