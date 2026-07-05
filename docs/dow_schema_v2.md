# Deferred DoW schema enrichments

*Add when USAspending/SAM enrichment or contract-lineage work begins and a real
use case pulls them. Good ideas, not needed for the current cross-source timeline demo.*

---

## 1. PIID roles

Each PIID in the `piids` array currently has only `value` and `excerpt`. Add a
`role` field:

```
"award_instrument"         — the contract/order being announced
"referenced_parent_vehicle"— an IDIQ or BOA the order is placed against
"prior_or_modified_contract"— the contract being modified
```

**Trigger:** When contract-lineage work begins (tracing modifications back to base
awards, or linking task orders to their parent IDIQs).

---

## 2. Per-awardee index mapping on amounts and PIIDs

When multiple awardees each receive separate values or separate PIIDs, the current
schema has no way to say "this amount goes to awardee[0]". Add `awardee_indices: []`
to each amount and PIID entry.

**Trigger:** When USAspending enrichment begins and per-awardee obligation tracking
becomes meaningful. Until then, `scope=individual_awardee` is the signal and the
mapping is left implicit.

---

## 3. Multi-valued instrument tags + instrument_type_raw

Some awards are simultaneously multiple instrument types (e.g. a firm-fixed-price
delivery order against an IDIQ). The current `instrument_type` scalar can only hold
one value. Add:
- `instrument_tags: []` — ordered list of instrument types
- `instrument_type_raw: str` — verbatim source fragment

**Trigger:** When instrument-type distribution analysis is needed (e.g. breakdown of
IDIQ vs. standalone contract share in the corpus).

---

## 4. completion_date_precision enum

`completion_date` is always normalized to `YYYY-MM-DD`, but the source may have said
"March 2029" (month precision) or "fiscal 2030" (fiscal year, stored as null). Add:

```
completion_date_precision: "day" | "month" | "year" | "fiscal_year" | "unknown"
```

**Trigger:** When temporal analysis of completion distributions needs to distinguish
"exactly March 19, 2029" from "sometime in March 2029."

---

## 5. Plural program_hints with provenance

`program_hint` is a single nullable string. Some awards mention multiple programs.
Replace with:
```
program_hints: [{"hint": str, "excerpt": str}]
```

**Trigger:** When program-level aggregation (e.g. "all awards mentioning F-35") is
built as a first-class feature.
