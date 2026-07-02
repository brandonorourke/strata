ALTER TABLE icfs_pleadings_and_comments ADD COLUMN filer_name TEXT;
ALTER TABLE icfs_pleadings_and_comments ADD COLUMN attachments JSONB;
ALTER TABLE icfs_pleadings_and_comments ADD COLUMN detail_fetched_at TIMESTAMPTZ;
