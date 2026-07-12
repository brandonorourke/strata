-- FPDS metadata from the award DETAIL endpoint, populated by enrich().
-- [top] = award-level (current cumulative state); [LTCD] = latest_transaction_contract_data
-- (latest-mod snapshot — only the stable-across-mods fields are captured here; the
-- action-specific ones, number_of_offers_received / extent_competed, are deferred to a
-- future base-transaction pass because "latest transaction" misleads on old awards).
--   date_signed        [top]  canonical action-signed date
--   funding_sub_agency [top]  funding_agency.subtier — real end customer on pass-throughs
--   program_acronym    [LTCD] program key (e.g. "PTS-G"); "N/A"/"NONE" normalized to NULL
--   is_multi_award     [LTCD] multiple_or_single_award_description == "MULTIPLE AWARD" —
--                             THE de-noiser (a multi-award ceiling is shared, never summed)
--   solicitation_id    [LTCD] solicitation_identifier — vehicle → RFP link
--   set_aside          [LTCD] type_set_aside_description
--   pricing_type       [LTCD] type_of_contract_pricing_description
-- LOCAL-ONLY for now.

ALTER TABLE usaspending_awards
    ADD COLUMN date_signed        DATE,
    ADD COLUMN funding_sub_agency TEXT,
    ADD COLUMN program_acronym    TEXT,
    ADD COLUMN is_multi_award     BOOLEAN,
    ADD COLUMN solicitation_id    TEXT,
    ADD COLUMN set_aside          TEXT,
    ADD COLUMN pricing_type       TEXT;

CREATE INDEX idx_usa_awards_program_acronym ON usaspending_awards (program_acronym) WHERE program_acronym IS NOT NULL;
