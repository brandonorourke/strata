# Spec: DoW contract extraction — LLM-only with scoped validators

## Goal
Extract structured award data from all ~2,957 DoW contract releases. One LLM call
per release; deterministic validators guard amounts and PIIDs after extraction.
End state: `dow_awards` rows powering `dow_canonical_entities` and the Viasat
cross-source demo.

## Context (read first)
- `docs/findings.md` — esp. "Award ceiling ≠ real value" and entity-resolution rules
- `docs/decisions.md` — DoW extraction field-trust policy (2026-07-04); DoW entity
  extraction approach (2026-07-04, source-scoped canonical table)
- Raw text is stored on every release row — parse from `raw_text` as primary input;
  `raw_html` available as fallback if `raw_text` is missing.

## Schema decision: `dow_awards` table

One row per award, one LLM call per release. The model determines award boundaries;
no paragraph-split pre-processing step.

### `dow_awards` table
```sql
CREATE TABLE dow_awards (
    id                          SERIAL PRIMARY KEY,
    release_id                  INTEGER NOT NULL REFERENCES dow_contract_releases(id),
    award_index                 INTEGER NOT NULL,   -- 0-based order within release output

    -- Extracted fields
    awardees                    JSONB,              -- [{name, city, state}]
    piids                       JSONB,              -- [{value, excerpt}]
    ceiling_cents               BIGINT,
    ceiling_raw                 TEXT,
    ceiling_excerpt             TEXT,               -- verbatim source text the LLM read
    obligated_cents             BIGINT,
    obligated_raw               TEXT,
    obligated_excerpt           TEXT,               -- verbatim source text the LLM read
    contract_type               TEXT,
    completion_date             DATE,
    contracting_activity        TEXT,
    program_hint                TEXT,
    llm_status                  TEXT,               -- 'ok', 'partial', 'failed'

    -- Validator flags (each FALSE = flagged; NULL = not applicable)
    val_amount_format           BOOLEAN,            -- ceiling/obligated parse to valid cents
    val_obligated_lte_ceiling   BOOLEAN,            -- obligated ≤ ceiling (cross-field check)
    val_piid_grammar            BOOLEAN,            -- all PIIDs match known federal formats
    val_ceiling_grounded        BOOLEAN,            -- ceiling value found in source text
    val_obligated_grounded      BOOLEAN,            -- obligated value found in source text
    val_piid_grounded           BOOLEAN,            -- all PIIDs found in source text
    val_date_plausible          BOOLEAN,            -- completion_date is a real plausible date
    val_state_codes             BOOLEAN,            -- awardee states are valid 2-letter US codes
    val_award_count_sane        BOOLEAN,            -- release-level: LLM count vs. trigger count
    val_flag_reasons            JSONB,              -- {field: reason_string} for each FALSE flag

    extracted_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (release_id, award_index)
);
```

`llm_raw_response` is stored on `dow_contract_releases` (one LLM call per release,
not per award). Add `llm_raw_response JSONB` and `llm_extracted_at TIMESTAMPTZ` to
that table via migration.

## Fields to extract (LLM schema)

Per award object in the LLM's JSON output:

- **awardees**: `[{name, city, state}]`. Always a list. `city`/`state` null if not
  stated. State as 2-letter code if given as abbreviation; store as-printed if spelled
  out (validator normalizes for the flag check).

- **piids**: `[{value, excerpt}]`. `value` = contract number as printed.
  `excerpt` = verbatim span from the source text the LLM read it from.

- **ceiling_raw** / **ceiling_excerpt**: headline award amount as printed digit-string
  (e.g. `"$437,665,005"`); excerpt = verbatim source span. We normalize to cents.

- **obligated_raw** / **obligated_excerpt**: separately stated obligated amount.
  Multiple era variants — see `docs/findings.md`. **NEVER infer from ceiling.**

- **contract_type**: raw string as stated (e.g. `"firm-fixed-price,
  indefinite-delivery/indefinite-quantity"`). Not normalized by the LLM.

- **completion_date**: `"YYYY-MM-DD"` or null. Use first day of month when only
  month+year are stated (e.g. `"September 2026"` → `"2026-09-01"`).

- **contracting_activity**: closing sentence fragment before "is the contracting
  activity." Null if absent.

- **program_hint**: named program string if present. Null if absent.

## Extraction script: `extract_dow_awards.py`

One async function `extract_release(session, release)`:
1. Build prompt with the release's `raw_text` (fallback to stripped `raw_html`).
2. Call `gpt-4o-mini` with `response_format=json_object`, `temperature=0`.
3. Parse response → list of award dicts.
4. Normalize amounts (raw string → integer cents) in Python, not the model.
5. Write one `DowAward` row per award object.
6. Write `llm_raw_response` + `llm_extracted_at` back to `dow_contract_releases`.
7. Run all validators (see below) on each written row; update flag columns.

Run incrementally: skip releases that already have `llm_extracted_at IS NOT NULL`.

### Prompt rules
- Extract ONLY what is explicitly stated.
- Return null for absent fields — never infer.
- **Never infer `obligated_raw` from `ceiling_raw` or vice versa.**
- Return amounts as the exact digit-string as printed.
- `piids` entries must each include the verbatim excerpt the value was read from.
- `ceiling_excerpt` and `obligated_excerpt` must be verbatim spans from the source.
- Return awards as a JSON array under key `"awards"`.

### Award-count sanity (prompt-side assist)
To help the model not silently drop awards: before the main extraction,
count `awarded` occurrences in the raw text and include that count in the prompt:
`"The source text contains approximately N award-trigger phrases. Extract all awards."`

## Validators

Run post-extraction on every `DowAward` row. Each failure sets the relevant
`val_*` column to `FALSE` and writes a reason to `val_flag_reasons`. Validators
**never discard rows** — a flagged row stays in the table and is routed to review.

### 1. Amount format
`ceiling_raw` and `obligated_raw` (when present) must parse to a valid positive
integer cents value. A non-parseable amount string sets `val_amount_format=FALSE`.

### 2. Obligated ≤ ceiling
When both are present: `obligated_cents <= ceiling_cents`. A violation almost always
means field-swap (obligated and ceiling extracted in the wrong order) or hallucination.
Sets `val_obligated_lte_ceiling=FALSE`. Guards the differentiator field.

### 3. PIID grammar
Each PIID value must match one of the two known federal contract-number formats:
- Parens/modern format: `[A-Z0-9]{6,20}` (e.g. `FA880726FB004`)
- Hyphenated format: `[A-Z][A-Z0-9-]{7,25}` with at least one digit
  (e.g. `FA8650-14-D-2411`)

Anything else (short acronyms, pure digits, modification-only numbers like `P00168`
without a base contract) sets `val_piid_grammar=FALSE`.

### 4. Value grounding (fabrication guard)
For each amount and each PIID, confirm the extracted value appears in `raw_text`
(or `raw_html` if `raw_text` is absent). Match on the numeric value in its source
form — not strict verbatim-excerpt matching, to be robust to whitespace/encoding:

- Amounts: check that the digit string (e.g. `437665005` or `150000000` or
  `150,000,000`) appears in the source text.
- PIIDs: check that the PIID value string (e.g. `FA880726FB004`) appears in the
  source text.

A value not found in the source text is flagged as likely hallucinated:
- `val_ceiling_grounded=FALSE`, `val_obligated_grounded=FALSE`, or
  `val_piid_grounded=FALSE` respectively.

### 5. Date plausibility
`completion_date` (when present) must be a real date between 2000-01-01 and
2060-01-01. Fails parse or out-of-range sets `val_date_plausible=FALSE`.

### 6. State codes
Each awardee `state` (when present) must be a valid 2-letter US state/territory
code. Non-2-letter strings get `val_state_codes=FALSE` with a note. Foreign entities
(known non-US state strings) get `val_state_codes=FALSE` with reason `"foreign"` —
not an error, just a flag.

### 7. Award-count sanity (release-level)
Count `awarded` trigger occurrences in `raw_text` (`was awarded`, `is awarded`,
`has been awarded`, `have been awarded`). If the LLM returned fewer awards than
the trigger count, set `val_award_count_sane=FALSE` with reason `"expected N triggers,
got M awards"`. Stored on every award row for the release (same value on all rows).
This catches silent dropped/merged awards — the loud-failure the paragraph split
provided.

**Do NOT validate** awardee name strings, contract_type, program_hint, or
contracting_activity against fixed formats. Those are legitimately transformed/fuzzy.
The count sanity flag and value-grounding cover their real risks.

## Acceptance test

File: `tests/test_dow_extraction.py`

The May 22, 2026 PTSG release **must** extract correctly:
```
release:    Contracts for May 22, 2026
awardees:   [{name: "VIASAT Inc.", city: null, state: null},
             {name: "INTELSAT General Communications LLC", city: null, state: null}]
             -- city null: "Work will be performed at the listed contractors' locations"
piids:      [{value: "FA880726FB004", excerpt: <present>},
             {value: "FA880726FB005", excerpt: <present>}]
ceiling:    43766500500  cents  ($437,665,005)
obligated:  15000000000  cents  ($150,000,000)
type:       "firm-fixed-price, indefinite-delivery/indefinite-quantity" (or similar)
completion: 2029-03-19
program:    "Protected Tactical Satellite-Global" (or similar)
contracting_activity: contains "Space Systems Command"
```

All validators must pass for this award:
- `val_amount_format=TRUE`
- `val_obligated_lte_ceiling=TRUE`  (150M < 437M ✓)
- `val_piid_grammar=TRUE`
- `val_ceiling_grounded=TRUE`
- `val_obligated_grounded=TRUE`
- `val_piid_grounded=TRUE`
- `val_date_plausible=TRUE`

Use stored `raw_text` as test fixture input — no live fetch.

## Explicitly out of scope
- Regex extraction (not an extractor — see `docs/decisions.md` 2026-07-04)
- Paragraph-splitting pre-processing
- Dual-method comparison, per-field agreement report, comparison columns
- `dow_canonical_entities` population (next spec, after reviewing extraction quality)
- Cross-source bridge to ICFS canonical entities
- LLM one-line summaries per award
- Any UI

## Deliverables
1. Migration: `ALTER TABLE dow_contract_releases ADD COLUMN llm_raw_response JSONB,
   ADD COLUMN llm_extracted_at TIMESTAMPTZ`
2. Migration: drop and recreate `dow_awards` with new schema (existing table has
   old regex/comparison columns from the pilot; recreate clean)
3. `apps/ingest/extract_dow_awards.py` — extraction + validators, incremental
4. `tests/test_dow_extraction.py` — May 22 fixture + all validator assertions

## File layout
```
apps/ingest/
  extract_dow_awards.py       (replaces extract_dow_regex.py + extract_dow_llm.py)
migrations/
  0034_dow_awards_v2.sql      (drop/recreate dow_awards; add columns to releases)
tests/
  test_dow_extraction.py
```

### Scripts to delete after migration
- `apps/ingest/extract_dow_regex.py`
- `apps/ingest/extract_dow_llm.py`
- `apps/ingest/report_dow_extraction.py`
