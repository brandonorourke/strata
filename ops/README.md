# ops/

Run-once operational scripts, kept in source control for **audit and reproducibility** —
not part of the app runtime.

**The contract:** scripts here are point-in-time records of something we ran (a backfill, a
prod data load, a one-off curation). They are **not maintained** as the schema/app evolves —
a script from months ago may no longer run, and that's fine: it documents what happened and
when (`git blame`), and gives the next person something to adapt.

Guidelines:
- Reusable, parametrized tooling lives elsewhere (`migrate.sh`, `apps/ingest/…`). Scripts
  here encode a **specific** action at a **specific** time.
- Use a descriptive (and/or `YYYY-MM-DD_`-prefixed) name so it reads as point-in-time.
- Anything that writes to prod must **confirm before writing** and support a **dry run**.

## Index

- `load_usaspending_batch2_to_prod.sh` (2026-07-14) — push the batch2 USASpending pull +
  curation from local `strata` to prod (TRUNCATE + data-only load + sequence reset). The
  curation (mapping_status, ownership verdicts) rides along in the data. Prereq:
  `./migrate.sh prod 48 && ./migrate.sh prod 49`.
