-- ICFS raw/structured staging tables — mirror the source ServiceNow tables directly,
-- kept separate from the generic news_articles shape since this data is genuinely
-- structured (not freeform article text needing an LLM pass).

CREATE TABLE IF NOT EXISTS icfs_filings (
    id SERIAL PRIMARY KEY,
    source_sys_id TEXT NOT NULL UNIQUE,
    file_number TEXT,
    call_sign TEXT,
    applicant_name TEXT,
    submission_date TIMESTAMPTZ,
    action TEXT,
    action_taken_date TIMESTAMPTZ,
    target_table TEXT,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    entities_extracted_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_icfs_filings_file_number ON icfs_filings (file_number);
CREATE INDEX IF NOT EXISTS ix_icfs_filings_applicant_name ON icfs_filings (applicant_name);
CREATE INDEX IF NOT EXISTS ix_icfs_filings_submission_date ON icfs_filings (submission_date);

CREATE TABLE IF NOT EXISTS icfs_pleadings_and_comments (
    id SERIAL PRIMARY KEY,
    source_sys_id TEXT NOT NULL UNIQUE,
    pleading_type TEXT,
    applicant_names TEXT,
    sys_created_on TIMESTAMPTZ,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_icfs_pleadings_sys_created_on ON icfs_pleadings_and_comments (sys_created_on);

CREATE TABLE IF NOT EXISTS icfs_public_notices (
    id SERIAL PRIMARY KEY,
    source_sys_id TEXT NOT NULL UNIQUE,
    number TEXT,
    subsystem TEXT,
    type_of_document TEXT,
    public_notice_release_date TIMESTAMPTZ,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_icfs_public_notices_release_date ON icfs_public_notices (public_notice_release_date);
