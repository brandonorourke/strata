# Strata

### Quick start

We use Python 3.12.7

```bash
cd strata
pyenv local 3.12.7
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
pip freeze > requirements.lock                # To make sure no changes

# create a local env file and database (values should match your Postgres setup)
cp infra/env.example .env  # adjust values inside if needed
createdb strata || true
psql strata -f db/schema.local.sql  # optional: load base schema snapshot

# Optional: capture schema snapshot for reference
pg_dump strata --schema-only --no-owner > strata_core/schema.local.sql
```

### Database schema

- The canonical schema lives in `strata_core/schema.local.sql`. Load it into a fresh database with `psql "$DATABASE_URL" -f strata_core/schema.local.sql`.
- Ad-hoc SQL migrations (if needed) live under `migrations/` and should be applied manually in order.
- Apply one with the wrapper: `./migrate.sh local 0040` (or `./migrate.sh prod 0040` — confirms first, uses `PROD_DATABASE_URL` from `.env`). Add `--show` to preview the SQL without running it. Under the hood it's just `psql -v ON_ERROR_STOP=1 -f`, so `psql strata -f migrations/000N_*.sql` still works too.
- After changing the schema, rerun `pg_dump --schema-only --no-owner > strata_core/schema.local.sql` so the snapshot stays current.
- Deploy note: a **non**-backwards-compatible migration (e.g. a column type change) must deploy the forward-compatible code **first**, then run the migration.
- When adding ORM columns, append at the end for readability (do not reorder existing fields).

### Production environment

- The app only reads `DATABASE_URL`, `OPENAI_API_KEY`, and `ENV` (see `strata_core/settings.py`) — set those wherever this runs in production.
- Not yet set up for an actual deploy: there's no Procfile/start command, no `$PORT` binding, and no health-check route, so a Railway (or similar) deploy will need that infra added first.

### Logging

- `uvicorn` prints HTTP access logs; running with `--log-level info --access-log` makes latency/status visible during dev.

---

### Git branching strategy

```
# Merge from develop
git checkout main
git pull --ff-only
git merge --no-ff develop -m "vX.Y.Z"
git tag -a vX.Y.Z -m "vX.Y.Z"
git push origin main --tags   # This deploys to Railway so do any db migrations first (always backwards compatible)

# Sync develop forward with exactly what's on main
git checkout develop
git pull --ff-only
git merge --ff-only main     # <- fast-forward or fail
git push origin develop
```

### Running the pipeline
```
  python apps/ingest/ingest_rss.py         -- Processes top level RSS feeds (right now just FreightWaves)
  python apps/ingest/fetch_html.py         -- Fetches and stores raw HTML for articles
  python apps/ingest/clean_text.py         -- Takes raw HTML and converts it to text, no links, images, etc
  python apps/ingest/llm_raw.py            -- Calls OpenAI API to convert clean text to structured JSON
  python apps/ingest/extract_domains.py    -- Extracts candidate domains from raw HTML
  python apps/ingest/extract_entities.py   -- Extracts entities and events from LLM JSON
  python apps/ingest/link_entities.py      -- Links entities to canonical entities
```
