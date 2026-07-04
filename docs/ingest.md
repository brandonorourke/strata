# ICFS Ingest Pipeline

## Scripts (run in order for a full pipeline cycle)

```
ingest_icfs.py               -- pull raw ICFS rows into staging tables
fetch_icfs_filing_details.py -- enrich filings with detail/attachments via ServiceNow API
fetch_icfs_pleading_details.py -- same for pleadings
fetch_icfs_notice_documents.py -- fetch DA notice PDFs from docs.fcc.gov
extract_icfs_entities.py     -- extract entities/events from filing data
extract_icfs_pleadings.py    -- extract entities/events from pleadings
extract_icfs_notice_entities.py  -- extract entities from notice text
extract_icfs_notice_summaries.py -- LLM summary + signal tier for notice events
```

## extract_icfs_entities.py — event_date logic

Each filing gets one `ExtractedEvent` row (used to drive the entity timeline). `event_date` is set as:
- `action_taken_date` if the filing has an action (grant, dismissal, etc.)
- `submission_date` otherwise (pending filings)

This means the entity timeline sorts actions by when the FCC acted, and pending filings by when they were submitted. A recent grant on a 2021 filing appears at the top of the timeline, not buried at 2021.

## ingest_icfs.py — three modes

### backfill (default)

Walks the full ICFS history from the page stored in `icfs_ingest_state`, table by table.
Ordered by `submission_date` (filings), `sys_created_on` (pleadings), `public_notice_release_date` (notices).
Safe to stop and restart — resumes from saved page.

```bash
python apps/ingest/ingest_icfs.py
# with cutoff:
python apps/ingest/ingest_icfs.py --stop-before-date 2024-01-01
# cap pages (test runs):
python apps/ingest/ingest_icfs.py --max-pages 2
```

### incremental

Designed for daily runs after backfill is complete. Runs two passes for filings:

**Pass 1 — by `submission_date`**: picks up new filings submitted since yesterday.
Stops when it sees records older than `MAX(submission_date) - 1 day` in the DB.

**Pass 2 — by `action_taken_date`**: picks up actions taken on old filings
(e.g. a 2021 application that gets granted today). Without this pass, that grant
would never appear — the filing itself was already in the DB and pass 1 only reaches recent submissions.

For pleadings and notices, one pass each (by their respective date fields).

When an action change is detected on an existing filing, the script:
1. Logs the old→new change to `icfs_filing_action_history` (append-only)
2. Updates `icfs_filings.action` and `action_taken_date`
3. Sets `detail_fetched_at = NULL` so `fetch_icfs_filing_details.py` re-fetches it

```bash
python apps/ingest/ingest_icfs.py --mode incremental
```

### Action history (`icfs_filing_action_history`)

Append-only table. Each row records a detected change: `filing_id`, `action`, `action_taken_date`, `detected_at`.
Watching this table is how alerting works (e.g. alerting on SAT-PPL-20211207-00172).

## FCC API notes

- **Endpoint**: `https://fccprod.servicenowservices.com/api/now/sp/widget/{WIDGET_SYS_ID}`
- **Auth**: Session cookie + `g_ck` CSRF token from the ICFS home page. Both required even for public data.
- **Rate limiting**: We use 3s delay between pages. `robots.txt` disallows all bots, but the data is unauthenticated public government records.
- **Garbage dates**: ICFS contains sentinel dates like `8888-08-08` — filtered out in `_parse_glide_datetime`.
- **FCC updates in place**: When an action is taken, the *same* `source_sys_id` row is updated in place by FCC. There is no separate "actions" table in the FCC API — just the updated `action` field.
- **FCC RSS feeds**: Full list at https://www.fcc.gov/news-events/rss-feeds-and-email-updates-fcc — covers public notices, daily digests, proceedings, and bureau-specific feeds. Not yet used; potential future ingest source for non-ICFS FCC activity.
- **EDOCS public API** (`api2.fcc.gov`): Fully accessible — no Akamai block. Three-step path to any FCC document:
  1. Bureau RSS: `https://api2.fcc.gov/api/exp/v1.0.0/edocspublic/rss/bureaus/SB` → items with `www.fcc.gov/edoc/{id}` links
  2. Document metadata: `https://api2.fcc.gov/api/exp/v1.0.0/edocspublic/documents/{id}` → returns `docs.fcc.gov/public/attachments/XXX.txt` download URL
  3. `docs.fcc.gov` → serves the `.txt` file (already confirmed working for DA notices)
  Space Bureau (`SB`) is active and current. International Bureau (`IB`) inactive post-2023 — FCC created Space Bureau in 2023 absorbing satellite licensing from IB.
  **This is the confirmed fix for the 985 non-DA SES/SAT notices.** Full path:
  1. `GET https://api2.fcc.gov/api/exp/v1.0.0/edocspublic/documents?reportNumber=SES-02821` → returns record ID (e.g. `416467`)
  2. `GET https://docs.fcc.gov/public/attachments/DOC-416467A1.txt` → full notice text
  Same format as DA notices (`DA-{da_number}A1.txt`), just `DOC-{recordId}A1` for non-DA.
  `fetch_icfs_notice_documents.py` needs a second fetch path for notices where `da_number IS NULL`.

## Scheduler (`apps/ingest/scheduler.py`)

Long-running worker process that runs the full pipeline daily at 03:00 UTC.
On startup, checks `ingest_runs` — if it's past 03:00 and no completed run exists today, runs immediately (handles container restarts mid-day).
Each run writes a row to `ingest_runs` (pipeline='icfs') with start/finish times, status, failed script, and per-script exit codes.

Override run time: `SCHEDULER_RUN_AT=HH:MM` env var (24h UTC).

### Railway deployment

1. Apply migration: `psql $DATABASE_URL -f migrations/0030_ingest_runs.sql`
2. New service → GitHub repo → same repo
3. Start command: `python apps/ingest/scheduler.py`
4. Environment variables (Variables tab):
   - `DATABASE_URL` — Railway Postgres URL
   - `OPENAI_API_KEY`
   - `PYTHONPATH=/app` — required: editable install (`-e .`) path doesn't survive the container build; this makes Python find `strata_core` at `/app/strata_core` directly
5. Deploy

To check run history:
```sql
SELECT pipeline, started_at, finished_at, status, failed_script, script_results
FROM ingest_runs ORDER BY started_at DESC LIMIT 10;
```

## Alerting (planned)

Watch `icfs_filing_action_history` for `filing_id` matching watched file numbers.
Stas has asked for alerts on `SAT-PPL-20211207-00172` specifically.
See `to_build.md` item #3.
