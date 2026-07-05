-- Add LLM extraction tracking to releases (one call per release)
ALTER TABLE dow_contract_releases
    ADD COLUMN llm_raw_response  JSONB,
    ADD COLUMN llm_extracted_at  TIMESTAMPTZ;

-- Award-level extraction results (one row per award per release)
CREATE TABLE dow_awards (
    id                          SERIAL PRIMARY KEY,
    release_id                  INTEGER NOT NULL REFERENCES dow_contract_releases(id),
    award_index                 INTEGER NOT NULL,   -- 0-based order within release output

    -- Extracted fields
    awardees                    JSONB,              -- [{name, city, state}]
    piids                       JSONB,              -- [{value, excerpt}]
    ceiling_cents               BIGINT,
    ceiling_raw                 TEXT,
    ceiling_excerpt             TEXT,
    obligated_cents             BIGINT,
    obligated_raw               TEXT,
    obligated_excerpt           TEXT,
    contract_type               TEXT,
    completion_date             DATE,
    contracting_activity        TEXT,
    program_hint                TEXT,
    llm_status                  TEXT,               -- 'ok', 'partial', 'failed'

    -- Validator flags (FALSE = flagged; NULL = not applicable)
    val_amount_format           BOOLEAN,
    val_obligated_lte_ceiling   BOOLEAN,
    val_piid_grammar            BOOLEAN,
    val_ceiling_grounded        BOOLEAN,
    val_obligated_grounded      BOOLEAN,
    val_piid_grounded           BOOLEAN,
    val_date_plausible          BOOLEAN,
    val_state_codes             BOOLEAN,
    val_award_count_sane        BOOLEAN,
    val_flag_reasons            JSONB,              -- {field: reason} for each FALSE flag

    extracted_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (release_id, award_index)
);
