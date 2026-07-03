"""
Daily ingest scheduler. Run as a long-lived worker process (e.g. Railway worker service).

Runs the full ICFS incremental pipeline once per day at RUN_AT (default 03:00 UTC).
On startup, checks whether today's run already completed and self-heals if the container
restarted after the scheduled time but before the run finished.

Writes each run to ingest_runs (pipeline='icfs'): started_at, finished_at, status,
failed_script, per-script return codes in script_results JSONB.
"""

import asyncio
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone, date
from pathlib import Path

import asyncpg
import schedule
import time

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

RUN_AT = os.getenv("SCHEDULER_RUN_AT", "03:00")  # UTC
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
]


def _asyncpg_dsn() -> str:
    url = os.environ["DATABASE_URL"]
    # asyncpg expects postgresql:// not postgresql+asyncpg://
    return url.replace("postgresql+asyncpg://", "postgresql://")


async def _db_today_completed(pipeline: str) -> bool:
    """Return True if a completed run for this pipeline already exists today (UTC)."""
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        row = await conn.fetchrow(
            "SELECT id FROM ingest_runs WHERE pipeline = $1 AND status = 'completed' AND started_at::date = $2",
            pipeline,
            date.today(),
        )
        return row is not None
    finally:
        await conn.close()


async def _db_start_run(pipeline: str) -> int:
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        row = await conn.fetchrow(
            "INSERT INTO ingest_runs (pipeline, started_at, status) VALUES ($1, NOW(), 'running') RETURNING id",
            pipeline,
        )
        return row["id"]
    finally:
        await conn.close()


async def _db_finish_run(run_id: int, status: str, failed_script: str | None, results: dict) -> None:
    conn = await asyncpg.connect(_asyncpg_dsn())
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


def run_pipeline() -> None:
    logger.info("Pipeline '%s' starting", PIPELINE_NAME)
    run_id = asyncio.run(_db_start_run(PIPELINE_NAME))
    results: dict[str, int] = {}
    failed_script = None

    for script_path, extra_args in PIPELINE:
        script_name = script_path.name
        cmd = [sys.executable, str(script_path)] + extra_args
        logger.info("Running %s", script_name)
        result = subprocess.run(cmd, check=False)
        results[script_name] = result.returncode
        if result.returncode != 0:
            logger.error("FAILED %s (exit %d) — stopping pipeline", script_name, result.returncode)
            failed_script = script_name
            break

    status = "failed" if failed_script else "completed"
    asyncio.run(_db_finish_run(run_id, status, failed_script, results))
    logger.info("Pipeline '%s' %s. Results: %s", PIPELINE_NAME, status, results)


def maybe_run_missed() -> None:
    """If it's past RUN_AT today and no completed run exists yet, run now."""
    now_utc = datetime.now(timezone.utc)
    run_hour, run_minute = (int(x) for x in RUN_AT.split(":"))
    scheduled_today = now_utc.replace(hour=run_hour, minute=run_minute, second=0, microsecond=0)
    if now_utc < scheduled_today:
        return
    if asyncio.run(_db_today_completed(PIPELINE_NAME)):
        logger.info("Today's '%s' run already completed, skipping catch-up", PIPELINE_NAME)
        return
    logger.info("Past %s UTC with no completed '%s' run — running now (catch-up)", RUN_AT, PIPELINE_NAME)
    run_pipeline()


if __name__ == "__main__":
    logger.info("Scheduler starting, pipeline='%s', daily run at %s UTC", PIPELINE_NAME, RUN_AT)
    maybe_run_missed()
    schedule.every().day.at(RUN_AT).do(run_pipeline)
    while True:
        schedule.run_pending()
        time.sleep(60)
