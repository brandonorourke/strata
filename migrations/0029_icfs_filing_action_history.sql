CREATE TABLE icfs_filing_action_history (
    id SERIAL PRIMARY KEY,
    filing_id INTEGER NOT NULL REFERENCES icfs_filings(id),
    action TEXT,
    action_taken_date TIMESTAMPTZ,
    detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
