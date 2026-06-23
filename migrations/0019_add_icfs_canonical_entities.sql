-- Tier 1 of entity resolution: collapse icfs_filings-derived entities within ICFS
-- by exact normalized name. Safe to do automatically because applicant_name is
-- structured truth from the source, not LLM-guessed text. Deliberately NOT linked
-- to canonical_entities yet (that cross-source hop stays human-gated, deferred —
-- see docs/decisions.md 2026-06-23).
CREATE TABLE IF NOT EXISTS icfs_canonical_entities (
    id SERIAL PRIMARY KEY,
    canonical_name TEXT NOT NULL,
    legal_name_normalized TEXT NOT NULL UNIQUE,
    loose_name_normalized TEXT,
    first_seen_at TIMESTAMPTZ,
    last_seen_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE extracted_entities ADD COLUMN IF NOT EXISTS icfs_canonical_entity_id INTEGER REFERENCES icfs_canonical_entities(id);
CREATE INDEX IF NOT EXISTS ix_extracted_entities_icfs_canonical ON extracted_entities (icfs_canonical_entity_id);
