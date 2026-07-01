-- Enrich icfs_filings with detail fetched from the ICFS application summary page API.
-- Hardcoded fetch is Viasat-only; columns are nullable for all other rows.
ALTER TABLE icfs_filings ADD COLUMN brief_description TEXT;
ALTER TABLE icfs_filings ADD COLUMN action_pn_url TEXT;
ALTER TABLE icfs_filings ADD COLUMN grant_date DATE;
ALTER TABLE icfs_filings ADD COLUMN expiration_date DATE;
ALTER TABLE icfs_filings ADD COLUMN begin_date DATE;
ALTER TABLE icfs_filings ADD COLUMN grant_doc_url TEXT;
ALTER TABLE icfs_filings ADD COLUMN detail_fetched_at TIMESTAMPTZ;
