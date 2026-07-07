"""
Ingest scheduler. Run as a long-lived worker process (e.g. Railway worker service).

Runs the full ICFS incremental pipeline every PIPELINE_EVERY_MINUTES (default 60 —
hourly, so contested-filing alerts stay fresh) plus once at startup. DoW releases
are polled separately in their evening window (see _dow_poll_cadence).

Writes each run to ingest_runs (pipeline='icfs'): started_at, finished_at, status,
failed_script, per-script return codes in script_results JSONB.
"""

import asyncio
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone, date, timedelta, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

import asyncpg
import schedule
import time

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

PIPELINE_EVERY_MINUTES = int(os.getenv("SCHEDULER_EVERY_MINUTES", "60"))  # ICFS pipeline cadence
PIPELINE_NAME = "icfs"

INGEST_DIR = Path(__file__).parent

PIPELINE = [
    (INGEST_DIR / "ingest_icfs.py", ["--mode", "incremental"]),
    (INGEST_DIR / "fetch_icfs_filing_details.py", []),
    (INGEST_DIR / "fetch_icfs_pleading_details.py", []),
    (INGEST_DIR / "fetch_icfs_notice_documents.py", []),
    (INGEST_DIR / "extract_icfs_entities.py", []),
    (INGEST_DIR / "extract_icfs_pleadings.py", []),
    (INGEST_DIR / "extract_icfs_notice_entities.py", []),
    (INGEST_DIR / "extract_icfs_notice_summaries.py", []),
    # DoW backstop — window poller is the primary path; this catches anything missed
    (INGEST_DIR / "ingest_dow_contracts.py", ["--mode", "incremental"]),
    # Extract awards from any new DoW releases, then fire alerts (DoW + ICFS).
    (INGEST_DIR / "extract_dow_awards_v2.py", []),
    (INGEST_DIR / "emit_alerts.py", []),
]

ET = ZoneInfo("America/New_York")
DOW_SCRIPT = INGEST_DIR / "ingest_dow_contracts.py"
EXTRACT_SCRIPT = INGEST_DIR / "extract_dow_awards_v2.py"
ALERTS_SCRIPT = INGEST_DIR / "emit_alerts.py"

# Only extract releases from the last N days — a rolling cutoff that catches new
# releases (+ a straggler buffer, misses hurt more than dupes which are impossible)
# while never touching the large historical backlog. Computed fresh each run so it
# rolls forward. Backfill history separately with `extract_dow_awards_v2 --since <old>`.
EXTRACT_SINCE_DAYS = int(os.getenv("DOW_EXTRACT_SINCE_DAYS", "7"))

def _extract_since() -> str:
    return (date.today() - timedelta(days=EXTRACT_SINCE_DAYS)).isoformat()

# ── Robustness knobs (why: a single hung DB/subprocess call used to freeze the
#    whole single-threaded loop silently — no timeout, no log, no recovery) ──
# DB timeouts set generously — only meant to break a genuine wedge (hung
# half-open connection), never to abort a slow-but-fine query. Our queries are
# trivial indexed lookups (<10ms), so 5 min is enormous headroom.
DB_CONNECT_TIMEOUT = 60           # asyncpg connection establishment (s)
DB_COMMAND_TIMEOUT = 300          # per-query ceiling (s) — 5 min
DB_TIMEOUT = 300                  # outer hard ceiling on a DB call (s) — matches command
HEARTBEAT_EVERY = 1800            # liveness log cadence (s) — silence => truly dead
# No subprocess timeouts by design: the child ingest scripts set their own HTTP
# timeouts (60s/30s/15s), so they can't hang on the network. Rely on logging
# ("Running X" before each) to see where a run is spending time.


def _dow_poll_cadence(now_et: datetime) -> int | None:
    """Return poll interval in seconds during the DoW release window, or None outside it.

    Weekdays only (war.gov contracts are a weekday ritual).
      4:55–5:20 PM ET  →  90s  (tight window; this is where the latency edge lives)
      5:20–6:30 PM ET  →  420s (7 min; catches late postings without wasting density)
    The 8pm ET evening sweep is handled separately in the main loop.
    """
    t = now_et.time()
    if dtime(16, 55) <= t < dtime(17, 20):
        return 90
    if dtime(17, 20) <= t < dtime(18, 30):
        return 420
    return None


def _asyncpg_dsn() -> str:
    url = os.environ["DATABASE_URL"]
    # asyncpg expects postgresql:// not postgresql+asyncpg://
    return url.replace("postgresql+asyncpg://", "postgresql://")


async def _connect():
    """Fresh connection per call, with connect + per-command timeouts.

    A fresh connection avoids reusing a stale/dead one (the likely cause of the
    silent freeze); the timeouts ensure a wedged DB can't block us forever.
    """
    return await asyncpg.connect(
        _asyncpg_dsn(),
        timeout=DB_CONNECT_TIMEOUT,
        command_timeout=DB_COMMAND_TIMEOUT,
    )


def _run_db(coro, what: str):
    """Run a DB coroutine with a hard timeout + log around it (log BEFORE trying,
    so a hang is visible as 'starting X' with no 'done', and a timeout is logged)."""
    logger.debug("DB: %s …", what)
    try:
        return asyncio.run(asyncio.wait_for(coro, timeout=DB_TIMEOUT))
    except asyncio.TimeoutError:
        logger.error("DB TIMEOUT (%ds): %s", DB_TIMEOUT, what)
        raise
    except Exception:
        logger.exception("DB ERROR: %s", what)
        raise


async def _db_start_run(pipeline: str) -> int:
    conn = await _connect()
    try:
        row = await conn.fetchrow(
            "INSERT INTO ingest_runs (pipeline, started_at, status) VALUES ($1, NOW(), 'running') RETURNING id",
            pipeline,
        )
        return row["id"]
    finally:
        await conn.close()


async def _db_finish_run(run_id: int, status: str, failed_script: str | None, results: dict) -> None:
    conn = await _connect()
    try:
        await conn.execute(
            """UPDATE ingest_runs
               SET finished_at = NOW(), status = $1, failed_script = $2, script_results = $3
               WHERE id = $4""",
            status,
            failed_script,
            json.dumps(results),
            run_id,
        )
    finally:
        await conn.close()


async def _has_today_dow_release(today_et: date) -> bool:
    """Return True if we already have a DoW release for today's ET date."""
    conn = await _connect()
    try:
        row = await conn.fetchrow(
            "SELECT id FROM dow_contract_releases WHERE release_date = $1 LIMIT 1",
            today_et,
        )
        return row is not None
    finally:
        await conn.close()


def poll_dow() -> None:
    """Check if today's DoW release is ingested; fetch it if not.

    Detection is a cheap DB query. Only hits war.gov when we don't have today's
    release yet. first_seen_at is stamped at store time in ingest_dow_contracts.py,
    so the detection timestamp is automatically instrumented.
    """
    now_et = datetime.now(ET)
    today_et = now_et.date()

    logger.info("DoW poll: checking DB for %s release", today_et)
    try:
        have = _run_db(_has_today_dow_release(today_et), f"check DoW release {today_et}")
    except Exception:
        logger.warning("DoW poll: DB check failed — will retry next cycle")
        return
    if have:
        logger.debug("DoW poll: already have today's release (%s)", today_et)
        return

    logger.info("DoW poll: no release yet for %s — running incremental ingest", today_et)
    result = subprocess.run(
        [sys.executable, str(DOW_SCRIPT), "--mode", "incremental"],
        check=False,
    )
    if result.returncode != 0:
        logger.error("DoW incremental ingest failed (exit %d)", result.returncode)
        return

    logger.info("DoW poll: ingest done, re-checking DB for %s", today_et)
    try:
        have = _run_db(_has_today_dow_release(today_et), f"re-check DoW release {today_et}")
    except Exception:
        logger.warning("DoW poll: post-ingest DB check failed")
        return
    if have:
        logger.info("DoW poll: detected today's release (%s) — extracting awards + alerting", today_et)
        # Latency path: extract the new release's awards, then fire alerts immediately.
        logger.info("Running extract_dow_awards_v2 --since %s", _extract_since())
        rc = subprocess.run(
            [sys.executable, str(EXTRACT_SCRIPT), "--since", _extract_since()],
            check=False,
        ).returncode
        if rc != 0:
            logger.error("extract_dow_awards_v2 failed (exit %d)", rc)
        logger.info("Running emit_alerts")
        rc = subprocess.run([sys.executable, str(ALERTS_SCRIPT)], check=False).returncode
        if rc != 0:
            logger.error("emit_alerts failed (exit %d)", rc)
    else:
        logger.info("DoW poll: ingest ran, no release for %s yet (not posted)", today_et)


def run_pipeline() -> None:
    logger.info("Pipeline '%s' starting", PIPELINE_NAME)
    try:
        run_id = _run_db(_db_start_run(PIPELINE_NAME), "start ingest_run")
    except Exception:
        logger.error("Pipeline: could not record run start — aborting this run")
        return
    results: dict[str, int] = {}
    failed_script = None

    for script_path, extra_args in PIPELINE:
        script_name = script_path.name
        if script_path == EXTRACT_SCRIPT:  # rolling date cutoff, computed fresh each run
            extra_args = extra_args + ["--since", _extract_since()]
        cmd = [sys.executable, str(script_path)] + extra_args
        logger.info("Running %s", script_name)
        result = subprocess.run(cmd, check=False)
        rc = result.returncode
        results[script_name] = rc
        if rc != 0:
            logger.error("FAILED %s (exit %d) — stopping pipeline", script_name, rc)
            failed_script = script_name
            break

    status = "failed" if failed_script else "completed"
    try:
        _run_db(_db_finish_run(run_id, status, failed_script, results), "finish ingest_run")
    except Exception:
        logger.warning("Pipeline: could not record run finish (status=%s)", status)
    logger.info("Pipeline '%s' %s. Results: %s", PIPELINE_NAME, status, results)


if __name__ == "__main__":
    logger.info("Scheduler starting, pipeline='%s' every %d min", PIPELINE_NAME, PIPELINE_EVERY_MINUTES)
    # Run once at startup so a restart/deploy doesn't leave up to a full interval
    # gap in freshness; then on the interval.
    try:
        run_pipeline()
    except Exception:
        logger.exception("startup pipeline run failed — continuing to main loop")
    schedule.every(PIPELINE_EVERY_MINUTES).minutes.do(run_pipeline)

    _last_dow_poll: datetime | None = None
    _dow_evening_done: date | None = None
    _last_heartbeat: datetime | None = None

    # The loop body is fully guarded: NO transient error (DB blip, network, hung
    # subprocess) may ever kill or freeze this loop. A break logs and continues;
    # the heartbeat means silence => the process is truly dead, not idle.
    while True:
        try:
            schedule.run_pending()

            now_utc = datetime.now(timezone.utc)
            now_et = now_utc.astimezone(ET)

            # Liveness heartbeat — proves the loop is alive even when idle
            if _last_heartbeat is None or (now_utc - _last_heartbeat).total_seconds() >= HEARTBEAT_EVERY:
                cad = _dow_poll_cadence(now_et)
                logger.info("scheduler alive — %s ET, DoW window %s",
                            now_et.strftime("%a %H:%M"), "OPEN" if cad else "closed")
                _last_heartbeat = now_utc

            # DoW window polling (weekdays, 4:55–6:30 PM ET)
            cadence = _dow_poll_cadence(now_et)
            if cadence is not None:
                if _last_dow_poll is None or (now_utc - _last_dow_poll).total_seconds() >= cadence:
                    poll_dow()
                    _last_dow_poll = now_utc

            # DoW 8pm ET evening sweep — one final check per day
            if (dtime(20, 0) <= now_et.time() < dtime(20, 30)
                    and _dow_evening_done != now_et.date()):
                logger.info("DoW evening sweep (8pm ET)")
                poll_dow()
                _dow_evening_done = now_et.date()

        except Exception:
            logger.exception("Scheduler loop iteration failed — continuing")

        time.sleep(60)
