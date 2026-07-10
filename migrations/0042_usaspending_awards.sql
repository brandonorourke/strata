-- Raw USASpending awards — one row per spending_by_award result, pulled by UEI.
-- A MANUAL pull-by-UEI viewer (apps/ingest/pull_usaspending.py), NOT part of the
-- daily pipeline. USASpending's free public API is the corpus spine; each row is a
-- single award: an IDV vehicle (is_idv) OR a contract/order. The parent PIID is
-- parsed out of generated_internal_id so a draw (task/delivery order) links to its
-- vehicle. LOCAL-ONLY for now — do NOT run this on prod yet.
--
--   generated_internal_id  USASpending's stable award id (upsert key)
--                            CONT_IDV_{piid}_{ag}                  → a vehicle (is_idv)
--                            CONT_AWD_{order}_{oag}_{parent}_{pag} → a contract/order
--                            parent = -NONE-  → standalone definitive contract
--   recipient_uei          the UEI actually on the award
--   seed_uei               the family anchor we pulled under (a company is a SET of
--                          UEIs; this records which pull surfaced the row)

CREATE TABLE usaspending_awards (
    id                    SERIAL PRIMARY KEY,
    generated_internal_id TEXT NOT NULL UNIQUE,            -- USASpending stable id + upsert key
    award_id              TEXT,                            -- "Award ID" (PIID / order number)
    award_id_key          TEXT,                            -- normalized join key (matches dow/sam piid_key)
    award_type            TEXT,                            -- "Contract Award Type" text
    is_idv                BOOLEAN NOT NULL DEFAULT FALSE,  -- a vehicle (IDV) vs a contract/order
    parent_award_id       TEXT,                            -- parent PIID parsed from gen id (NULL = standalone)
    parent_generated_id   TEXT,                            -- reconstructed CONT_IDV_{parent}_{ag} (links draw→vehicle)
    recipient_name        TEXT,
    recipient_uei         TEXT,                            -- UEI on the award
    recipient_id          TEXT,                            -- USASpending recipient hash (…-C/-P/-R)
    seed_uei              TEXT,                            -- family anchor we pulled under
    ticker                TEXT,                            -- optional label, if pulled by ticker
    awarding_agency       TEXT,
    awarding_sub_agency   TEXT,
    description           TEXT,
    start_date            DATE,
    end_date              DATE,
    amount                NUMERIC,                         -- "Award Amount"
    total_outlays         NUMERIC,
    naics_code            TEXT,
    psc_code              TEXT,
    last_modified         TEXT,                            -- API "Last Modified Date" (raw string)
    base_obligation_date  DATE,
    fetched_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    raw                   JSONB                            -- full spending_by_award result row
);

CREATE INDEX idx_usa_awards_recipient_uei  ON usaspending_awards (recipient_uei);
CREATE INDEX idx_usa_awards_seed_uei        ON usaspending_awards (seed_uei);
CREATE INDEX idx_usa_awards_parent_award_id ON usaspending_awards (parent_award_id);
CREATE INDEX idx_usa_awards_award_id_key    ON usaspending_awards (award_id_key);
CREATE INDEX idx_usa_awards_amount          ON usaspending_awards (amount DESC NULLS LAST);
CREATE INDEX idx_usa_awards_is_idv          ON usaspending_awards (is_idv);
