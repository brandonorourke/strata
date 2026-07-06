-- Drop 15-field-era columns the v2 regex-primary extractor never writes.
-- v2 (extract_dow_awards_v2.py) populates: awardees (PIID embedded), amounts,
-- completion_date_raw, completion_date, contracting_activity, purpose,
-- program_hint, action_type, source_excerpt, llm_status.
--
-- These five are leftovers from the LLM-only 15-field schema (0035) and are
-- empty on all v2 rows. Instrument type / pricing / funding will come from
-- SAM/USASpending enrichment keyed on PIID, not from press-release parsing.

ALTER TABLE dow_awards DROP COLUMN IF EXISTS funding_at_award;
ALTER TABLE dow_awards DROP COLUMN IF EXISTS instrument_type;
ALTER TABLE dow_awards DROP COLUMN IF EXISTS pricing_type_raw;
ALTER TABLE dow_awards DROP COLUMN IF EXISTS purpose_excerpt;
ALTER TABLE dow_awards DROP COLUMN IF EXISTS flags;
