-- Detail-endpoint enrichment columns for usaspending_awards. The award DETAIL
-- endpoint (/api/v2/awards/{id}/) carries values spending_by_award does NOT:
-- base_and_all_options (ceiling → the existing `ceiling` col), base_exercised_options
-- (base + exercised options, a middle layer), total_obligation, and an explicit
-- parent_award link. `enriched_at` marks a row as detail-fetched, so the enrichment
-- pass is resumable/idempotent (only NULLs are (re)fetched). LOCAL-ONLY for now.

ALTER TABLE usaspending_awards
    ADD COLUMN base_exercised_options NUMERIC,
    ADD COLUMN enriched_at            TIMESTAMPTZ;

-- rows still needing a detail fetch
CREATE INDEX idx_usa_awards_needs_enrich ON usaspending_awards (id) WHERE enriched_at IS NULL;
