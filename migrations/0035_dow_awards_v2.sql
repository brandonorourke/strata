-- Drop and recreate dow_awards with v2 schema.
-- Old schema (0033/0034) had flat ceiling/obligated fields and val_* boolean columns.
-- New schema uses amounts[] array, structured flags JSONB, action/instrument/pricing
-- split, funding_at_award, completion_date_raw, purpose_excerpt, source_excerpt,
-- and country_raw on awardees for foreign contractors.

DROP TABLE IF EXISTS dow_awards;

CREATE TABLE dow_awards (
    id                      SERIAL PRIMARY KEY,
    release_id              INTEGER NOT NULL REFERENCES dow_contract_releases(id),
    award_index             INTEGER NOT NULL,   -- 0-based order within release output

    -- [{name_raw, name_normalized, city_raw, state_raw, country_raw}]
    awardees                JSONB,
    -- [{value, excerpt}]
    piids                   JSONB,
    -- [{raw, cents, kind, scope, excerpt}]
    amounts                 JSONB,
    -- {status, excerpt}
    funding_at_award        JSONB,

    action_type             TEXT,
    instrument_type         TEXT,
    pricing_type_raw        TEXT,
    completion_date_raw     TEXT,
    completion_date         DATE,
    contracting_activity    TEXT,
    program_hint            TEXT,
    purpose                 TEXT,
    purpose_excerpt         TEXT,
    source_excerpt          TEXT,
    llm_status              TEXT,               -- 'ok', 'partial', 'failed'

    -- Structured validation failures: {flag_name: reason_string}
    flags                   JSONB,

    extracted_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (release_id, award_index)
);
