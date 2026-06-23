-- Make extracted_entities/extracted_events reference their source generically
-- (source_type + source_id) instead of a hard FK to news_articles only.
-- Needed because entities/events can now come from icfs_filings, etc., not just
-- news_articles, and more primary-source tables (UCC, court dockets) are planned.
-- Existing rows are backfilled as source_type='news_article' since article_id
-- only ever pointed at news_articles before this migration.

ALTER TABLE extracted_entities RENAME COLUMN article_id TO source_id;
ALTER TABLE extracted_entities ADD COLUMN source_type TEXT NOT NULL DEFAULT 'news_article';
ALTER TABLE extracted_entities DROP CONSTRAINT IF EXISTS extracted_entities_article_id_fkey;
DROP INDEX IF EXISTS ux_extracted_entities_article_legal;
CREATE UNIQUE INDEX IF NOT EXISTS ux_extracted_entities_source_legal
    ON extracted_entities (source_type, source_id, legal_name_normalized);

ALTER TABLE extracted_events RENAME COLUMN article_id TO source_id;
ALTER TABLE extracted_events ADD COLUMN source_type TEXT NOT NULL DEFAULT 'news_article';
ALTER TABLE extracted_events DROP CONSTRAINT IF EXISTS extracted_events_article_id_fkey;
DROP INDEX IF EXISTS ux_extracted_events_article_entity;
CREATE UNIQUE INDEX IF NOT EXISTS ux_extracted_events_source_entity
    ON extracted_events (source_type, source_id, entity_id);
