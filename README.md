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
- To run locally: `psql strata -f migrations/0001_drop_processed_by_llm_at.sql`
- After changing the schema, rerun `pg_dump --schema-only --no-owner > strata_core/schema.local.sql` so the snapshot stays current.

### Production environment

- Use `api/.env.example.prod` as a template for Railway variables. It includes the internal `DATABASE_URL`, `INVITE_DOMAIN`, `PUBLIC_BASE`, and `PORT=8000` so the health check works.
- Replace the placeholders (`[PWDGOESHERE]`, `[SIGNING_SECRET GOES HERE]`) with your actual values before adding them to Railway.

### Logging

- `uvicorn` prints HTTP access logs; running with `--log-level info --access-log` makes latency/status visible during dev.
- The FastAPI service also emits lightweight application logs (`invite_created`, `invite_response`, and request timing) so failures are easy to trace in both local runs and Railway.

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
  python apps/ingest/ingest_rss.py
  python apps/ingest/fetch_html.py
  python apps/ingest/clean_text.py
  python apps/ingest/llm_raw.py
  python apps/ingest/extract_entities.py
```