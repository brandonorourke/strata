# Spec: DoW contract extraction — dual-method (regex + LLM) with comparison

## Goal
Extract structured award data from all ~2,957 DoW contract releases using two
independent methods (regex + LLM), compare field-by-field, and produce a
per-field accuracy read that tells us which extractor to trust for which field.
End state: high-confidence extraction feeding dow_canonical_entities and the
Viasat cross-source demo.

## Context (read first)
- `docs/findings.md` — esp. "Award ceiling ≠ real value" and entity-resolution rules
- `docs/decisions.md` — DoW entity extraction approach ((name, location) key,
  source-scoped canonical table)
- Raw text is stored on every release row — parse from `raw_text`, never re-fetch.
  (`raw_html` available as fallback if `raw_text` is missing, but `raw_text` is
  cleaner for paragraph splitting and should be the primary input.)
- Releases are templated bureaucratic prose. One release contains MULTIPLE award
  paragraphs; the unit of extraction is the award paragraph, not the release.

## Schema decision: `dow_awards` table (not `extracted_entities`)
A dedicated `dow_awards` table rather than the polymorphic `extracted_entities/
extracted_events` model. Rationale: the award shape (piids list, ceiling vs
obligated, contract type, completion date, program hint, multi-awardee list)
fits poorly into `extracted_events` which was designed for event-type /
transaction-role / confidence. Noted in `docs/decisions.md`.

### `dow_awards` table
```sql
CREATE TABLE dow_awards (
    id                      SERIAL PRIMARY KEY,
    release_id              INTEGER NOT NULL REFERENCES dow_contract_releases(id),
    paragraph_index         INTEGER NOT NULL,         -- 0-based position in release
    paragraph_text          TEXT NOT NULL,            -- raw paragraph sent to both extractors

    -- Regex extraction
    regex_awardees          JSONB,   -- [{name, city, state}]
    regex_piids             JSONB,   -- [string]
    regex_ceiling_cents     BIGINT,
    regex_ceiling_raw       TEXT,
    regex_obligated_cents   BIGINT,
    regex_obligated_raw     TEXT,
    regex_contract_type     TEXT,
    regex_completion_date   DATE,
    regex_contracting_activity TEXT,
    regex_program_hint      TEXT,
    regex_status            TEXT,    -- 'full', 'partial', 'failed'

    -- LLM extraction
    llm_awardees            JSONB,
    llm_piids               JSONB,
    llm_ceiling_cents       BIGINT,
    llm_ceiling_raw         TEXT,
    llm_obligated_cents     BIGINT,
    llm_obligated_raw       TEXT,
    llm_contract_type       TEXT,
    llm_completion_date     DATE,
    llm_contracting_activity TEXT,
    llm_program_hint        TEXT,
    llm_status              TEXT,    -- 'full', 'partial', 'failed'
    llm_raw_response        JSONB,   -- full model response for provenance

    -- Comparison
    awardee_match           BOOLEAN,
    piid_match              BOOLEAN,
    ceiling_match           BOOLEAN,
    obligated_match         BOOLEAN,
    type_match              BOOLEAN,
    completion_match        BOOLEAN,
    overall_match           BOOLEAN,

    extracted_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

## Fields to extract (both methods, identical schema)
Per award paragraph:

- **awardees**: list of `{name, city, state}`. Multi-awardee is common — always
  a list. Pattern: `"Company Name, City, State"` preceding `"was/is/has been awarded"`.
  PIID (contract number) may appear in parens after each awardee name.

- **piids**: list of contract numbers e.g. `FA880726FB004`. In parens after
  awardee name(s). May be one per awardee in multi-awardee paragraphs.

- **ceiling_amount_cents**: headline dollar figure (`"awarded a $X ..."`).
  Integer cents. Null if absent.

- **obligated_amount_cents**: separately stated obligated/face value. Multiple
  variants across eras — this field gets its own pattern family and the most
  test fixtures:
  - `"$X are being obligated at the time of award"`
  - `"face value of this action is $X"`
  - `"fiscal 20XX [fund type] funds in the amount of $X"`
  - `"$X ... is being obligated"`
  Integer cents. Null if absent. **NEVER infer from ceiling.**

- **contract_type**: FAR-defined vocabulary. Store raw matched string + normalized
  enum. Common values: `firm-fixed-price`, `cost-plus-fixed-fee`,
  `cost-plus-incentive-fee`, `indefinite-delivery/indefinite-quantity`,
  `time-and-materials`, `undefinitized`.

- **completion_date**: `"expected to be completed by <date>"`. Null if absent.

- **contracting_activity**: `"X is the contracting activity"` closer sentence.
  Null if absent.

- **program_hint**: raw text of any named program in the paragraph e.g.
  `"Protected Tactical Satellite-Global program"`. String capture only, no
  resolution.

## Method 1: regex extraction
Script: `apps/ingest/extract_dow_regex.py`

- One function per field, each returning `(value, raw_string)`.
- Pattern families handle era drift (2014→2026 format changes).
- When a paragraph yields no awardee OR no ceiling, set `regex_status='failed'`
  rather than partial-guessing.
- Confidence tiers:
  - `full`: awardee + ceiling + piid all present
  - `partial`: awardee present, one of ceiling/piid missing
  - `failed`: no awardee found

## Method 2: LLM extraction
Script: `apps/ingest/extract_dow_llm.py`

- Model: `gpt-4o-mini` (cheap, structured output).
- One call per award paragraph.
- Prompt rules:
  - Extract ONLY what is explicitly stated.
  - Return null when a field is absent — never infer.
  - **NEVER infer obligated from ceiling.**
  - Return amounts as digit strings exactly as printed (normalization happens
    in our code, not the model's).
- Store full raw model response in `llm_raw_response` (same provenance
  discipline as ICFS notice summaries).
- Log total token counts and cost estimate on completion.

## Normalization layer (shared, applied before comparison)
Applied to both extractors' output before writing to DB and before comparison:
- **Amounts** → integer cents. Handle: `"$437,665,005"`, `"$437.7 million"`,
  `"437665005"`. Preserve raw string separately.
- **Names** → casefold, strip punctuation, normalize suffixes
  (Inc/Incorporated/LLC/Corp/Co/Ltd) for comparison only; preserve raw.
- **States** → two-letter codes (California → CA, etc.).
- **Dates** → `datetime.date`.

## Paragraph splitting
Split `raw_text` into award paragraphs before passing to either extractor.

Paragraph boundaries in DoW releases are consistent: double newline (`\n\n`).
Not every paragraph is an award — filter by presence of `"was awarded"`,
`"is awarded"`, or `"has been awarded"`. Paragraphs without those phrases
are headers, footers, or administrative lines — skip them.

## Comparison logic
After both extractors run on a paragraph, compute match booleans:
- **awardee_match**: normalized name sets overlap (at least one shared awardee).
- **piid_match**: piid sets identical.
- **ceiling_match**: cents values equal (or both null).
- **obligated_match**: cents values equal (or both null).
- **type_match**: normalized contract_type equal.
- **completion_match**: dates equal (or both null).
- **overall_match**: all non-null fields match.

## Comparison report
Script: `apps/ingest/report_dow_extraction.py`

Printed + saved to `docs/dow_extraction_report.md`:
- Per-field agreement % across corpus
- Count of each disagreement bucket (regex-only, llm-only, both-failed, mismatch)
- Full dump of disagreeing rows: release URL + both extractions side by side
- LLM cost actual

## Acceptance test
File: `tests/test_dow_extraction.py`

The May 22, 2026 PTSG release **must** extract correctly by at least one method:
```
release:    Contracts for May 22, 2026
url:        https://www.war.gov/News/Contracts/Contract/Article/4499778/...
awardees:   [{name: "VIASAT Inc.", city: "...", state: "CA"},
             {name: "INTELSAT General Communications LLC", city: "McLean", state: "VA"}]
piids:      ["FA880726FB004", "FA880726FB005"]
ceiling:    43766500500  (cents)
obligated:  15000000000  (cents)
type:       firm-fixed-price / indefinite-delivery/indefinite-quantity
completion: 2029-03-19
program:    "Protected Tactical Satellite-Global"
```
Use stored `raw_text` as the test fixture (no live fetch).

## Explicitly out of scope
- `dow_canonical_entities` population (next spec, after reading the report)
- Cross-source bridge to ICFS canonical entities
- LLM one-line summaries per award
- Any UI

## Deliverables
1. Migration for `dow_awards` table
2. `extract_dow_regex.py` — regex extractor, full corpus run
3. `extract_dow_llm.py` — LLM extractor, full corpus run
4. `report_dow_extraction.py` — comparison report
5. `tests/test_dow_extraction.py` — May 22 fixture test passing
6. `docs/dow_extraction_report.md` — per-field agreement rates + disagreement dump
7. LLM cost logged

## File layout
```
apps/ingest/
  extract_dow_regex.py
  extract_dow_llm.py
  report_dow_extraction.py
migrations/
  0033_dow_awards.sql
tests/
  test_dow_extraction.py
docs/
  dow_extraction_report.md   (generated)
  specs/
    dow_extraction.md        (this file)
```
