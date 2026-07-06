# apps/ingest/emit_alerts.py
#
# Watchlist alerting v1 (hardcoded: Viasat, Intelsat). Runs after ingest/extract.
#
#   dow_match  — a new DoW award whose awardee is on the watchlist
#   dow_scan   — heartbeat: fires whenever new DoW releases are scanned; lists them
#                and the match count. With 0 matches it's the "scanned these, nothing
#                found" confirmation (proves the pipeline ran + covered those releases).
#   icfs_match — a new watchlist ICFS filing whose applicant currently has contested
#                filings (pending, >= CONTESTED_MIN pleadings)
#
# Watermarks in alert_state make "new" detection cheap and prevent re-alerting.
# Sender is a console stub for now (sets sent_at); swap in SendGrid later.
#
# Usage:
#   python emit_alerts.py            # detect, record, send (console)
#   python emit_alerts.py --dry-run  # detect + print only, no writes

import argparse
import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import text, select, update

from strata_core.db import AsyncSessionLocal
from strata_core.models import Alert, AlertState

from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

WATCHLIST = ["Viasat", "Intelsat"]          # hardcoded for v1
CONTESTED_MIN = 3                            # pleadings threshold for "contested"


def _matches_watchlist(name: str | None) -> str | None:
    if not name:
        return None
    low = name.lower()
    for w in WATCHLIST:
        if w.lower() in low:
            return w
    return None


# ── state helpers ──────────────────────────────────────────────────────────────

async def _get_state(session, key: str, default: str) -> str:
    row = (await session.execute(
        select(AlertState.value).where(AlertState.key == key)
    )).scalar_one_or_none()
    return row if row is not None else default


async def _set_state(session, key: str, value: str) -> None:
    existing = (await session.execute(
        select(AlertState).where(AlertState.key == key)
    )).scalar_one_or_none()
    if existing:
        existing.value = value
        existing.updated_at = datetime.now(timezone.utc)
    else:
        session.add(AlertState(key=key, value=value))


async def _add_alert(session, kind, subject, title, body, meta, dry_run):
    if dry_run:
        print(f"\n[{kind}] {title}")
        if subject:
            print(f"   subject: {subject}")
        print(f"   {body}")
        return
    session.add(Alert(kind=kind, subject=subject, title=title, body=body, meta=meta))


# ── DoW: matches + scan heartbeat ────────────────────────────────────────────

async def detect_dow(session, dry_run) -> int:
    last_id = int(await _get_state(session, "last_dow_award_id", "0"))
    rows = (await session.execute(text("""
        SELECT da.id, da.release_id, r.release_date, r.title, da.awardees, da.purpose
        FROM dow_awards da
        JOIN dow_contract_releases r ON r.id = da.release_id
        WHERE da.id > :last_id
        ORDER BY da.id
    """), {"last_id": last_id})).mappings().all()

    if not rows:
        logger.info("DoW: no new awards since award id %d", last_id)
        return 0

    max_id = max(r["id"] for r in rows)
    releases = {}   # release_id -> (date, title)
    matches = []
    for r in rows:
        releases[r["release_id"]] = (r["release_date"], r["title"])
        for a in (r["awardees"] or []):
            w = _matches_watchlist(a.get("name_raw"))
            if w:
                matches.append({
                    "company": w, "name_raw": a.get("name_raw"), "piid": a.get("piid"),
                    "release_date": str(r["release_date"]), "purpose": r["purpose"],
                })

    # match alerts
    for m in matches:
        await _add_alert(
            session, "dow_match", m["company"],
            f"DoW award — {m['name_raw']} ({m['release_date']})",
            f"{m['name_raw']} · PIID {m['piid']} · {m['purpose'] or ''}".strip(),
            m, dry_run,
        )

    # scan heartbeat (covers the no-match confirmation)
    all_dates = sorted({str(d) for d, _ in releases.values()}, reverse=True)
    rel_list = all_dates[:15] + ([f"…+{len(all_dates)-15} more"] if len(all_dates) > 15 else [])
    n_rel, n_awards = len(releases), len(rows)
    if matches:
        summary = "; ".join(f"{m['company']}: {m['name_raw']} ({m['piid']})" for m in matches)
        heartbeat_body = f"Scanned {n_awards} awards across {n_rel} release day(s) [{', '.join(rel_list)}]. Watchlist matches: {summary}"
    else:
        heartbeat_body = f"Scanned {n_awards} awards across {n_rel} release day(s) [{', '.join(rel_list)}]. No Viasat or Intelsat found."
    await _add_alert(
        session, "dow_scan", None,
        f"DoW scan — {n_rel} release day(s), {len(matches)} match(es)",
        heartbeat_body, {"release_dates": rel_list, "n_awards": n_awards, "n_matches": len(matches)},
        dry_run,
    )

    if not dry_run:
        await _set_state(session, "last_dow_award_id", str(max_id))
    logger.info("DoW: %d new awards, %d release day(s), %d match(es)", n_awards, n_rel, len(matches))
    return len(matches) + 1


# ── ICFS: new watchlist filing -> alert on currently-contested filings ────────

async def detect_icfs(session, dry_run) -> int:
    last_ts_str = await _get_state(session, "last_icfs_ingested_at", "1970-01-01T00:00:00+00:00")
    last_ts = datetime.fromisoformat(last_ts_str)
    new_filings = (await session.execute(text("""
        SELECT id, file_number, applicant_name, ingested_at
        FROM icfs_filings
        WHERE ingested_at > :ts
          AND (applicant_name ILIKE '%viasat%' OR applicant_name ILIKE '%intelsat%')
        ORDER BY ingested_at
    """), {"ts": last_ts})).mappings().all()

    # advance watermark past everything ingested so far (not just matches)
    maxts = (await session.execute(
        text("SELECT MAX(ingested_at) FROM icfs_filings")
    )).scalar()

    if not new_filings:
        logger.info("ICFS: no new watchlist filings since %s", last_ts)
        if not dry_run and maxts:
            await _set_state(session, "last_icfs_ingested_at", str(maxts))
        return 0

    # applicants that just had new activity
    applicants = sorted({f["applicant_name"] for f in new_filings})
    alerted = set()
    n = 0
    for applicant in applicants:
        company = _matches_watchlist(applicant)
        contested = (await session.execute(text("""
            SELECT f.file_number, f.brief_description, f.submission_date,
                   COUNT(p.id) AS pleadings,
                   STRING_AGG(DISTINCT p.filer_name, ' · ')
                     FILTER (WHERE p.filer_name IS NOT NULL AND p.filer_name != f.applicant_name)
                     AS contestants
            FROM icfs_filings f
            LEFT JOIN icfs_pleadings_and_comments p
              ON p.file_number ILIKE '%' || f.file_number || '%'
            WHERE f.action IS NULL AND f.file_number IS NOT NULL
              AND f.applicant_name = :applicant
            GROUP BY f.file_number, f.brief_description, f.submission_date
            HAVING COUNT(p.id) >= :minp
            ORDER BY pleadings DESC
        """), {"applicant": applicant, "minp": CONTESTED_MIN})).mappings().all()

        for c in contested:
            if c["file_number"] in alerted:
                continue
            alerted.add(c["file_number"])
            await _add_alert(
                session, "icfs_match", company,
                f"ICFS contested — {applicant} · {c['file_number']} ({c['pleadings']} pleadings)",
                f"{c['brief_description'] or ''} — contested by: {c['contestants'] or 'n/a'}".strip(" —"),
                {"file_number": c["file_number"], "applicant": applicant,
                 "pleadings": c["pleadings"], "trigger": "new watchlist filing"},
                dry_run,
            )
            n += 1

    if not dry_run and maxts:
        await _set_state(session, "last_icfs_ingested_at", str(maxts))
    logger.info("ICFS: %d new watchlist filing(s), %d contested alert(s)", len(new_filings), n)
    return n


# ── sender (console stub; swap in SendGrid later) ────────────────────────────

async def send_pending(session, dry_run) -> int:
    if dry_run:
        return 0
    pending = (await session.execute(
        select(Alert).where(Alert.sent_at.is_(None)).order_by(Alert.created_at)
    )).scalars().all()
    now = datetime.now(timezone.utc)
    for a in pending:
        print(f"  [SEND:{a.kind}] {a.title}")
        if a.body:
            print(f"            {a.body}")
        a.sent_at = now   # console stub "delivers" it
    return len(pending)


async def run(dry_run: bool) -> None:
    async with AsyncSessionLocal() as session:
        n_dow = await detect_dow(session, dry_run)
        n_icfs = await detect_icfs(session, dry_run)
        if not dry_run:
            await session.commit()
        n_sent = await send_pending(session, dry_run)
        if not dry_run:
            await session.commit()
        logger.info("done: DoW alerts=%d, ICFS alerts=%d, sent=%d", n_dow, n_icfs, n_sent)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    asyncio.run(run(dry_run=args.dry_run))
