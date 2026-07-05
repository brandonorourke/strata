# Spec: DoW contract extraction — LLM-only with scoped validators

## Goal
Extract structured award data from all ~2,957 DoW contract releases. One LLM call
per release; deterministic validators guard amounts and PIIDs after extraction.
End state: `dow_awards` rows powering `dow_canonical_entities` and the Viasat
cross-source demo.

## Context (read first)
- `docs/findings.md` — esp. "Award ceiling ≠ real value" and entity-resolution rules
- `docs/decisions.md` — DoW extraction field-trust policy (2026-07-04)
- Raw text is stored on every release row — parse from `raw_text` as primary input;
  `raw_html` available as fallback if `raw_text` is missing.

## Schema: `dow_awards` table

```sql
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
```

`llm_raw_response JSONB` and `llm_extracted_at TIMESTAMPTZ` live on
`dow_contract_releases` (one LLM call per release, not per award).

## Fields to extract (LLM schema)

### awardees
`[{name_raw, name_normalized, city_raw, state_raw, country_raw}]`
- `name_raw`: exactly as printed. `name_normalized`: derived in code (casefold + strip punctuation).
- US awardees: `city_raw`/`state_raw` as printed, `country_raw` null.
- Foreign awardees: `country_raw` populated, `state_raw` may be null.

### piids
`[{value, excerpt}]` — contract number as printed; excerpt = verbatim source span.

### amounts
`[{raw, cents, kind, scope, excerpt}]`
- `raw`: dollar string as printed. `cents`: normalized in code.
- `kind`: one of `individual_award_value`, `combined_award_value`, `maximum_ceiling`,
  `modification_delta`, `cumulative_contract_value`, `potential_value_if_options_exercised`,
  `initial_obligation`, `minimum_guarantee`, `other`.
- `scope`: `individual_awardee`, `combined_awardees`, or `unspecified`.
- `excerpt`: verbatim source span.

### funding_at_award
`{status, excerpt}`
- `status`: `amount_stated`, `none_obligated`, or `not_stated`.
- When an obligation is stated, include it in amounts as `initial_obligation` AND set
  status to `amount_stated`.

### action_type
`award`, `modification`, `option`, `definitization`, `other`, or `unknown`.

### instrument_type
`contract`, `IDIQ`, `delivery_order`, `task_order`, `BPA`, `BOA`, `other`, or `unknown`.

### pricing_type_raw
Cost/pricing arrangement ONLY (e.g. `"firm-fixed-price"`, `"cost-plus-fixed-fee"`).
Do NOT include delivery vehicle terms — those belong in `instrument_type`.

### completion_date / completion_date_raw
Preserve source phrase in `completion_date_raw`; parse to `YYYY-MM-DD` in
`completion_date`. First day of month when only month+year stated. **Fiscal years:
`completion_date` must be null; preserve phrase in `completion_date_raw`.**

### purpose / purpose_excerpt
`purpose`: 1-2 sentence factual description of what work/service/product is procured.
`purpose_excerpt`: verbatim source span the purpose was drawn from.

### contracting_activity, program_hint, source_excerpt
As stated. `source_excerpt`: full paragraph(s) for this award group.

## Extraction script: `extract_dow_awards.py`

One async function per release:
1. Build prompt with `raw_text` (fallback: stripped `raw_html`).
2. Call `gpt-4o-mini`, `temperature=0`, `response_format=json_object`.
3. Parse response → list of award dicts.
4. In code: add `name_normalized` to each awardee, add `cents` to each amount.
5. Write one `DowAward` row per award object.
6. Write `llm_raw_response` + `llm_extracted_at` to `dow_contract_releases`.
7. Run all validators on each row.

Run incrementally: skip releases where `llm_extracted_at IS NOT NULL`.

## Validators

Run post-extraction on every `DowAward`. Every failure adds a `{flag_name: reason}`
entry to `flags`. **Rows are never discarded.**

Normalization rule for all grounding checks: normalize both sides before comparing —
collapse whitespace, unify Unicode dashes (–—‐ → -), normalize smart quotes, convert
non-breaking spaces. Store original source unchanged; validate against a normalized copy.

### 1. Literal grounding
Every piid.value, amount.raw, piid/amount/purpose excerpts, awardee.name_raw,
completion_date_raw, and funding_at_award.excerpt (when status ≠ not_stated) must
appear in (normalized) source text. Failure → `ungrounded_<field>`.

### 2. Date consistency
`completion_date` must be null when `completion_date_raw` contains "fiscal"/"FY".
Failure → `date_inconsistent`.

### 3. Enum validation (flag, never reject)
`amount.kind`, `amount.scope`, `action_type`, `instrument_type`,
`funding_at_award.status` must be from their allowed sets. Out-of-set value →
`invalid_enum_<field>`. Preserve raw LLM response; set normalized field to
unknown/null only if downstream requires a valid value. Never discard the row.

### 4. Conditional math
When both `initial_obligation` and `maximum_ceiling` are present with compatible
scope: obligation ≤ ceiling. Failure → `obligation_exceeds_ceiling`.
Do NOT compare across mismatched scopes or with other amount kinds (e.g.
`combined_award_value` is not `maximum_ceiling`).

### 5. Funding consistency
`status=amount_stated` ⇒ `initial_obligation` amount exists (and vice versa).
`status=none_obligated` ⇒ no `initial_obligation` amount.
Failure → `funding_status_mismatch`.

### 6. State / country
`state_raw` (when present, no `country_raw`) must be a valid US state/territory
code or full name. Populated `country_raw` (non-US) is valid-foreign.
Failure → `state_unrecognized` (low severity).

### 7. Award-count sanity (advisory — never blocks or discards)
Count award-language markers in source: `was/is/has been/have been awarded`,
`are awarded`, `awarded a/an`, `will compete for each order`, `modification to`,
`task order`, `delivery order`. Flag `award_count_low` when extracted count is
well below marker count.

**Deliberately not validated:** purpose text, program_hint, pricing_type_raw,
contracting_activity, recipient-level amount allocation.

## Acceptance test — `tests/test_dow_extraction.py`

The **May 22, 2026 PTSG release** is the hard gate. Using stored raw text (no live
fetch), must extract one award group:
- awardees: VIASAT Inc. and INTELSAT General Communications LLC (city/state null,
  country_raw null — "Work will be performed at the listed contractors' locations")
- piids: FA880726FB004, FA880726FB005 (both grounded)
- amounts: `combined_award_value` "$437,665,005" (scope: combined_awardees) AND
  `initial_obligation` "$150,000,000" — **no `maximum_ceiling`**, so
  obligation ≤ ceiling check does NOT run for this fixture
- funding_at_award.status: "amount_stated"
- action_type: "award"; instrument_type: "IDIQ"; pricing_type_raw: "firm-fixed-price"
- completion_date: 2029-03-19; completion_date_raw: "March 19, 2029"
- program_hint: "Protected Tactical Satellite-Global"
- contracting_activity: contains "Space Systems Command"
- All validators pass (40 tests, 40/40 green)

## Out of scope (this pass)
- `dow_canonical_entities` population (next spec)
- Cross-source bridge to ICFS canonical entities
- LLM "why it matters" summaries
- Any UI

## Deferred enrichments
See `docs/dow_schema_v2.md`.

## Deliverables
1. Migration `0035_dow_awards_v2.sql` — drop/recreate `dow_awards` with new schema
2. `apps/ingest/extract_dow_awards.py` — extraction + normalization + validators
3. `tests/test_dow_extraction.py` — May 22 fixture + all validator assertions
4. `docs/specs/dow_extraction.md` — this spec
5. `docs/dow_schema_v2.md` — deferred enrichments
6. Full corpus run → flag summary (count per flag type) + flagged-rows dump + cost log
