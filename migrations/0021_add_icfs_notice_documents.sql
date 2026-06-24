-- icfs_public_notices.url already stores the fcc.gov/edocs search-results page for the
-- notice. That page (server-rendered HTML, confirmed) embeds a direct link to the actual
-- document text at docs.fcc.gov/public/attachments/<id>.txt — these columns store that
-- resolved link and the fetched text, plus separate timestamps for the fetch step and the
-- (file_number-based, zero-ambiguity) entity extraction step that reads it.
ALTER TABLE icfs_public_notices ADD COLUMN IF NOT EXISTS document_url TEXT;
ALTER TABLE icfs_public_notices ADD COLUMN IF NOT EXISTS document_text TEXT;
ALTER TABLE icfs_public_notices ADD COLUMN IF NOT EXISTS document_fetched_at TIMESTAMPTZ;
ALTER TABLE icfs_public_notices ADD COLUMN IF NOT EXISTS entities_extracted_at TIMESTAMPTZ;
