# Spec: DoW contract extraction — regex-primary + LLM semantic

> **Supersedes** the original "LLM-only with scoped validators" spec (15-field
> schema, 9 grounding validators). That design was reversed on 2026-07-06 — see
> `docs/decisions.md` ("Regex-primary reversal"). This document describes the
> current `extract_dow_awards_v2.py` pipeline.

## Goal
Extract award records from all ~2,957 DoW contract releases. The load-bearing
field is the **PIID** (contract number) — the join key to SAM.gov / USASpending,
which supply authoritative amounts, canonical names, UEIs, and ceilings. The
press-release extraction exists to produce a same-day record (for alerting) and
the PIID; SAM/USASpending mature it asynchronously.

End state: `dow_awards` rows powering PIID-keyed enrichment and, later,
`dow_canonical_entities`.

## Context (read first)
- `docs/findings.md` — "Award ceiling ≠ real value", entity-resolution rules
- `docs/decisions.md` — regex-primary reversal + field-trust policy
- `docs/usaspending_api.md`, `docs/sam_api.md` — PIID → enrichment
- Raw text is stored on every release row (`raw_text`); parse from it directly.

## Architecture

Three layers, PIID is the spine:

1. **Regex (primary / authoritative for the award list).** Owns the rigid,
   positional fields. Every regex-found award group becomes a `dow_awards` row;
   every regex PIID becomes an awardee entry. Extracts: PIID, city_raw, state_raw,
   amounts (raw strings), completion_date(_raw), contracting_activity.
2. **LLM (semantic, one call per release).** Supplies fields that require reading
   comprehension: `name_raw` (company), `purpose`, `program_hint`, `action_type`.
   Also enumerates PIIDs **independently** (no regex hint) so its list can be
   compared against regex.
3. **Merge (regex-authoritative).** Join regex ↔ LLM on a normalized PIID key
   (`_piid_key`: strips parens/whitespace/dashes, drops a trailing mod token).
   Regex defines which rows exist; LLM data attaches by PIID. A dropped or
   reformatted LLM award never deletes a row — it only lowers confidence.

**Why regex-primary:** the LLM under-counts / reformats PIIDs on long releases,
which silently dropped ~50% of awards under the old LLM-authoritative merge.
Regex enumerates positionally and reliably. The LLM's judgment is retained where
it's strong (which PIID is a real award vs. a parent reference) via the
confidence flag, not by letting it gate row existence.

## Per-awardee confidence (`awardees[*].pairing_confidence`)
- `agreed` — regex PIID also enumerated by the LLM as an award. High confidence.
- `regex_only` — regex found it, LLM did not call it an award. Usually a
  parent-contract reference ("order against a previously issued BOA (PIID)"),
  occasionally a genuine LLM miss. Written with `name_raw = null`, flagged.

`llm_only` PIIDs (LLM found, regex missed) are **not** written as rows — they are
logged and stored in `dow_contract_releases.llm_raw_response.llm_only_piids` as a
regex-brittleness research signal, to study whether regex needs new patterns.

## Schema: `dow_awards`

```sql
CREATE TABLE dow_awards (
    id                   SERIAL PRIMARY KEY,
    release_id           INTEGER NOT NULL REFERENCES dow_contract_releases(id),
    award_index          INTEGER NOT NULL,   -- 0-based order within release output

    -- one entry per awardee; PIID embedded (one PIID = one awardee, always)
    -- [{name_raw, city_raw, state_raw, piid, parse_status, pairing_confidence}]
    awardees             JSONB,
    amounts              JSONB,               -- [{raw}] — raw strings only, not classified
    action_type          TEXT,                -- award | modification | other (LLM)
    completion_date_raw  TEXT,
    completion_date      DATE,                -- null for fiscal-year phrases
    contracting_activity TEXT,
    program_hint         TEXT,                -- named program/system, else null (LLM)
    purpose              TEXT,                -- 1-2 sentence scope (LLM)
    source_excerpt       TEXT,                -- award-group paragraph
    llm_status           TEXT,                -- 'combo'
    extracted_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (release_id, award_index)
);
```

`llm_raw_response JSONB` and `llm_extracted_at TIMESTAMPTZ` live on
`dow_contract_releases` (one LLM call per release). **`llm_raw_response` stores
ONLY the raw API response — nothing we compute:**

```jsonc
{
  "model":         "gpt-4o-mini-...",
  "finish_reason": "stop",   // "length" ⇒ response truncated at max-tokens (incomplete)
  "usage":         { "prompt_tokens": …, "completion_tokens": …, "total_tokens": … },
  "content":       { "award_groups": [ … ] }   // the model's full JSON output
}
```

**Derived merge/comparison metadata is deliberately NOT persisted here.** Values
like `n_regex`, `n_llm`, and `llm_only_piids` (the set diff {LLM PIIDs} −
{regex PIIDs}, i.e. the regex-brittleness signal) are computed by `_merge()` at
run time and **logged**, not stored — they mix derived analysis into the raw
record. They are fully recomputable for research from this stored `content` plus
re-running the deterministic regex on `raw_text`, so nothing is lost by omitting
them. The extraction outcome itself is captured in the `dow_awards` rows
(`awardees[*].pairing_confidence`).

PIID lives inside each awardee (`awardees[*].piid`); the standalone `piids`
column was dropped in migration 0036. Query by PIID with the JSONB containment
operator: `WHERE awardees @> '[{"piid":"FA880726FB004"}]'`.

## Field ownership

| Field | Source | Notes |
|---|---|---|
| `piid` (per awardee) | regex | load-bearing SAM join key; regex's clean string stored |
| `city_raw`, `state_raw` | regex | display-only; SAM overwrites on enrichment |
| `amounts[].raw` | regex | raw strings; not classified (SAM returns authoritative amounts) |
| `completion_date_raw` → `completion_date` | regex | fiscal-year phrase → `completion_date` null |
| `contracting_activity` | regex | text before "is the contracting activity" |
| `name_raw` | LLM | company only, city/state excluded; not canonical (SAM canonicalizes) |
| `purpose` | LLM | what is procured, 1-2 sentences |
| `program_hint` | LLM | named program only (e.g. "PTS-G"), else null |
| `action_type` | LLM | award / modification / other |
| `pairing_confidence`, `parse_status` | merge | cross-check + regex parse quality |

## Known limitations (v1, accepted)
- **Parent references** written as flagged `regex_only` rows (nameless). Common in
  Navy modification paragraphs. Visible and filterable; SAM confirms IDV parents.
- **Awards announced without a new PIID** (e.g. an OTA action described only "to a
  previously awarded prototype OTA (PIID)") surface as a `regex_only` row on the
  referenced PIID — flagged for review, not silently dropped.
- **Inline-PIID paragraphs** occasionally leak the PIID into `state_raw`.
  Display-only; SAM overwrites.

## Extraction script: `apps/ingest/extract_dow_awards_v2.py`
Per release: `_release_body` → `_regex_groups` (authoritative list) → one
`_llm_groups` call (independent enumeration) → `_merge` (regex-authoritative,
normalized-key join) → write one `DowAward` row per group.

CLI: `--release-id`, `--limit`, `--reprocess`, `--dry-run`. Incremental by
default (skips releases where `llm_extracted_at IS NOT NULL`); `--reprocess`
re-runs regex + LLM and overwrites (incurs LLM cost — not a free re-parse).

## Out of scope (this pass)
- SAM/USASpending enrichment write-back (next)
- `dow_canonical_entities` population
- Cross-source bridge to ICFS canonical entities
- Any UI

## Deliverables (built)
1. Migrations `0036_dow_awards_embed_piid.sql`, `0037_dow_awards_drop_dead_columns.sql`
2. `apps/ingest/extract_dow_awards_v2.py`
3. Full corpus run → confidence-distribution summary + `llm_only_piids` review
