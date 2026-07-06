-- Drop piids top-level column; PIID is now embedded in each awardee entry
-- as awardees[*].piid. This is correct because one PIID = one awardee always.
-- Also adds pairing_confidence and parse_status per awardee entry (JSONB, no DDL needed).
--
-- Existing award rows are cleared — they predate this schema and will be
-- re-extracted by extract_dow_awards_v2.py.

DELETE FROM dow_awards;

UPDATE dow_contract_releases
SET llm_extracted_at = NULL,
    llm_raw_response = NULL;

ALTER TABLE dow_awards DROP COLUMN piids;
