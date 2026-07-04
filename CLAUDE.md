# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Strata ingests news (currently SEC RSS feeds) and extracts companies, events, and entity links for investor-facing screens (litigation finance / special situations / private credit monitoring). Pure Python package `strata_core` plus a FastAPI app under `apps/api`.

Read `docs/findings.md` before working on ingestion, extraction, or classification — it contains verified domain behavior about how the sources actually work that overrides assumptions (e.g. DA ≠ signal, notice families need separate parsing logic, award ceiling ≠ obligated value).

## Setup

Python 3.12.7 via pyenv + venv. Install with `pip install -r requirements.txt` (installs `strata_core` editable via `-e .`). No CI, no linter/formatter config, and `tests/` is empty — don't assume `pytest` or a linter will run; verify changes manually.

Local DB is Postgres, named `strata`, using the async driver string `postgresql+asyncpg://...`. Copy `infra/env.example` to `.env` and fill in `DATABASE_URL` / `OPENAI_API_KEY`. The working-tree `.env` has a live `OPENAI_API_KEY` — never read, echo, or commit it.

## Database schema

- Canonical schema lives at `strata_core/schema.local.sql` (the README's `db/schema.local.sql` reference is stale — that directory doesn't exist).
- DB + migrations are the source of truth, not the snapshot file. After any schema change, regenerate the snapshot: `pg_dump strata --schema-only --no-owner > strata_core/schema.local.sql`.
- When adding ORM/table columns, always append at the end — never reorder existing fields (keeps diffs and pg_dump output stable).
- Migrations are hand-written numbered SQL files under `migrations/`, applied manually and in order (`psql strata -f migrations/000N_*.sql`). There is no migration framework (no Alembic).
- `api/.env.example.prod`, referenced in the README for Railway production config, does not exist in the repo.

## Ingest pipeline

Scripts under `apps/ingest/` run in this order:
```
ingest_rss.py       -- pull top-level RSS feeds
fetch_html.py        -- fetch and store raw HTML for articles
clean_text.py        -- strip HTML to plain text
llm_raw.py           -- OpenAI call: clean text -> structured JSON
extract_domains.py   -- extract candidate domains from raw HTML
extract_entities.py  -- extract entities/events from LLM JSON
link_entities.py     -- link entities to canonical entities
```

## v0 architecture decisions (see docs/decisions.md for rationale)

- `extracted_entities` rows are per-article mentions, not deduped globally — canonicalization happens separately.
- Canonicalization is conservative: prefer duplicate `canonical_entities` over a wrong merge; only auto-merge on strong identifiers (domain/CIK/etc). Only `entity_type` in `{operating_company, financial_sponsor, lender}` is canonicalized in v0.
- Global entity resolution is deferred in favor of rolling time-window (7d/30d) clustering by `(entity_type, legal_name_normalized)`. Occasional collisions are preferred over brittle/false-certainty heuristics.
- Individuals may be extracted but are intentionally excluded from canonicalization and v0 UI screens.
- `event_type` / `transaction_role` on `extracted_events` are plain text columns for now (not enums) while the taxonomy is still evolving.
- UI is kept minimal/custom in v0 — no UI framework (e.g. Tailwind) yet.

## Git workflow

Branch model is `main` + `develop` (only `main` exists as a remote-tracked branch right now). Release flow:
```
git checkout main && git pull --ff-only
git merge --no-ff develop -m "vX.Y.Z"
git tag -a vX.Y.Z -m "vX.Y.Z"
git push origin main --tags   # pushing main deploys to Railway — land DB migrations first, and keep them backwards compatible
```
Commit messages are short and often prefixed by area, e.g. `Docs: ...`, `Schema: ...`, `Linker: ...`, `Ingest: ...`, `UI: ...`.
