# apps/ingest/emit_alerts.py
#
# Watchlist alerting v1 (hardcoded: Viasat, Intelsat). Runs after ingest/extract.
#
#   dow_match  — a new DoW award whose awardee is on the watchlist
#   dow_scan   — heartbeat: fires whenever new DoW releases are scanned; lists them
#                and the match count. With 0 matches it's the "scanned these, nothing
#                found" confirmation (proves the pipeline ran + covered those releases).
#   icfs_match — a new ICFS filing by a watchlist applicant (Viasat/Intelsat).
#                v1: any new filing. v2 will filter to contested (>= N pleadings).
#   icfs_action— a new ACTION on an existing filing (grant, withdrawal, consummation,
#                action-taken change) from icfs_filing_action_history. Catches events on
#                filings already in the DB that icfs_match (new-filing-only) would miss.
#                Wider freshness window (ALERT_ACTION_MAX_AGE_DAYS) since actions lag.
#
# FUTURE (noted): alert on new PLEADINGS for *contested* filings specifically.
#
# Watermarks in alert_state make "new" detection cheap and prevent re-alerting.
# Delivery: one digest email per run via Resend (reads RESEND_API_KEY from env;
# never hard-coded). Falls back to console printing if the key isn't set.
#
# Usage:
#   python emit_alerts.py            # detect, record, send (email if RESEND_API_KEY set)
#   python emit_alerts.py --dry-run  # detect + print only, no writes

import argparse
import asyncio
import logging
import os
from datetime import datetime, timezone, date, timedelta

import httpx
from sqlalchemy import text, select

from strata_core.db import AsyncSessionLocal
from strata_core.models import Alert, AlertState

from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

WATCHLIST = ["Viasat", "Intelsat"]          # hardcoded for v1
# TEMPORARY (test): alert on EVERYTHING, ignoring the watchlist, for a few days to
# verify the whole pipeline end-to-end. Flip back to False to return to
# watchlist-only (Viasat/Intelsat). ~30 alerts/day here, delivered as digests.
ALERT_ALL = True

# Freshness guard: only alert on items dated within the last N days. Protects
# against dumping a backlog — on the first run, or after the scheduler has been
# down and the watermark is far behind, only genuinely-recent items alert.
# The watermark still handles "don't repeat"; this handles "don't dump backlog".
ALERT_MAX_AGE_DAYS = int(os.environ.get("ALERT_MAX_AGE_DAYS", "3"))
# Actions lag more than filings (FCC posts the action after it happens), so a wider window.
ALERT_ACTION_MAX_AGE_DAYS = int(os.environ.get("ALERT_ACTION_MAX_AGE_DAYS", "14"))

def _fresh_cutoff() -> date:
    return date.today() - timedelta(days=ALERT_MAX_AGE_DAYS)

# ── Email delivery (Resend) ──────────────────────────────────────────────────
RESEND_API_KEY = os.environ.get("RESEND_API_KEY")           # set in .env / Railway
ALERT_FROM = os.environ.get("ALERT_FROM", "Strata Alerts <onboarding@resend.dev>")
# Just me for now; add Stas later via ALERT_TO env var (comma-separated).
ALERT_TO = [e.strip() for e in os.environ.get("ALERT_TO", "bcorourke@gmail.com").split(",") if e.strip()]


def _matches_watchlist(name: str | None) -> str | None:
    if not name:
        return None
    if ALERT_ALL:            # test mode: everything matches; label with the name itself
        return name
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
          AND r.release_date >= :fresh          -- freshness guard: no backlog dumps
        ORDER BY da.id
    """), {"last_id": last_id, "fresh": _fresh_cutoff()})).mappings().all()

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


# ── ICFS: alert on each NEW watchlist filing (v1) ────────────────────────────
# v1 is deliberately simple: any new filing by Viasat/Intelsat → one alert.
# v2 will add a "contested" filter (>= N pleadings) on top of this.

async def detect_icfs(session, dry_run) -> int:
    last_ts_str = await _get_state(session, "last_icfs_ingested_at", "1970-01-01T00:00:00+00:00")
    last_ts = datetime.fromisoformat(last_ts_str)
    # Watchlist filter is in SQL; ALERT_ALL drops it (test mode = every applicant).
    applicant_filter = "" if ALERT_ALL else \
        "AND (applicant_name ILIKE '%viasat%' OR applicant_name ILIKE '%intelsat%')"
    new_filings = (await session.execute(text(f"""
        SELECT file_number, applicant_name, brief_description, action, submission_date
        FROM icfs_filings
        WHERE ingested_at > :ts
          AND submission_date >= :fresh          -- freshness guard: no backlog dumps
          {applicant_filter}
        ORDER BY ingested_at
    """), {"ts": last_ts, "fresh": _fresh_cutoff()})).mappings().all()

    # advance watermark past everything ingested so far (not just matches)
    maxts = (await session.execute(
        text("SELECT MAX(ingested_at) FROM icfs_filings")
    )).scalar()

    n = 0
    for f in new_filings:
        company = _matches_watchlist(f["applicant_name"])
        await _add_alert(
            session, "icfs_match", company,
            f"New ICFS filing — {f['applicant_name']} · {f['file_number']}",
            f"{f['brief_description'] or ''} ({f['action'] or 'pending'})".strip(),
            {"file_number": f["file_number"], "applicant": f["applicant_name"],
             "action": f["action"]},
            dry_run,
        )
        n += 1

    if not dry_run and maxts:
        await _set_state(session, "last_icfs_ingested_at", str(maxts))
    logger.info("ICFS: %d new watchlist filing(s) alerted", n)
    return n


# ── ICFS: alert on new ACTIONS on existing filings (not just new filings) ────
# A modification / action-taken change on a filing already in the DB does NOT create
# a new icfs_filings row, so detect_icfs misses it. icfs_filing_action_history gets a
# row each time the incremental ingest detects an action change — that's the signal.
# Separate watermark (by detected_at) so it can't miss or double-fire; freshness guard
# on the action's own date so the first run can't dump the backlog.

async def detect_icfs_actions(session, dry_run) -> int:
    last_ts_str = await _get_state(session, "last_icfs_action_at", "1970-01-01T00:00:00+00:00")
    last_ts = datetime.fromisoformat(last_ts_str)
    # Actions post with more lag than filings (FCC records the action days after it
    # happens), so use a wider freshness window than the filing default.
    action_fresh = date.today() - timedelta(days=ALERT_ACTION_MAX_AGE_DAYS)
    applicant_filter = "" if ALERT_ALL else \
        "AND (f.applicant_name ILIKE '%viasat%' OR f.applicant_name ILIKE '%intelsat%')"
    new_actions = (await session.execute(text(f"""
        SELECT ah.action, ah.action_taken_date, f.file_number, f.applicant_name, f.brief_description
        FROM icfs_filing_action_history ah
        JOIN icfs_filings f ON f.id = ah.filing_id
        WHERE ah.detected_at > :ts
          AND COALESCE(ah.action_taken_date, ah.detected_at) >= :fresh   -- freshness guard (wider for actions)
          {applicant_filter}
        ORDER BY ah.detected_at
    """), {"ts": last_ts, "fresh": action_fresh})).mappings().all()

    # advance watermark past everything detected so far (not just matches)
    maxts = (await session.execute(
        text("SELECT MAX(detected_at) FROM icfs_filing_action_history")
    )).scalar()

    n = 0
    for a in new_actions:
        company = _matches_watchlist(a["applicant_name"])
        # action_taken_date is a DATE (migration 0040). Handle both date and (pre-migration)
        # datetime so this is safe across the deploy window.
        atd = a["action_taken_date"]
        taken = (atd.date() if isinstance(atd, datetime) else atd).isoformat() if atd else "pending"
        await _add_alert(
            session, "icfs_action", company,
            f"ICFS action — {a['applicant_name']} · {a['file_number']}",
            f"{a['action'] or 'action'} ({taken}) · {a['brief_description'] or ''}".strip(),
            {"file_number": a["file_number"], "applicant": a["applicant_name"],
             "action": a["action"], "action_taken_date": taken},
            dry_run,
        )
        n += 1

    if not dry_run and maxts:
        await _set_state(session, "last_icfs_action_at", str(maxts))
    logger.info("ICFS: %d new action(s) alerted", n)
    return n


# ── sender: one digest email per run via Resend (console fallback) ───────────

async def _send_email(subject: str, body: str) -> bool:
    """Send one email via Resend. Returns True on success."""
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {RESEND_API_KEY}"},
                json={"from": ALERT_FROM, "to": ALERT_TO, "subject": subject, "text": body},
            )
        if r.status_code in (200, 201):
            return True
        logger.error("Resend send failed: HTTP %d %s", r.status_code, r.text[:300])
        return False
    except Exception as e:
        logger.error("Resend send error: %s", e)
        return False


async def send_pending(session, dry_run) -> int:
    if dry_run:
        return 0
    pending = (await session.execute(
        select(Alert).where(Alert.sent_at.is_(None)).order_by(Alert.created_at)
    )).scalars().all()
    if not pending:
        return 0

    # One digest email per run — avoid blasting N separate emails (e.g. the ICFS backlog)
    lines = []
    for a in pending:
        lines.append(f"[{a.kind}] {a.title}")
        if a.body:
            lines.append(f"    {a.body}")
    body = "\n".join(lines)
    subject = (f"Strata alert: {pending[0].title}" if len(pending) == 1
               else f"Strata: {len(pending)} new alerts")

    titles = " | ".join(a.title for a in pending)
    if RESEND_API_KEY:
        ok = await _send_email(subject, body)
        if not ok:
            logger.warning("email send failed — leaving %d alert(s) unsent for retry: %s", len(pending), titles)
            return 0  # don't mark sent; retry next run
        logger.info("emailed %d alert(s) to %s: %s", len(pending), ", ".join(ALERT_TO), titles)
    else:
        logger.info("no RESEND_API_KEY — console fallback (%d alert(s))", len(pending))
        for line in lines:
            print("  " + line)

    now = datetime.now(timezone.utc)
    for a in pending:
        a.sent_at = now
    return len(pending)


async def run(dry_run: bool) -> None:
    async with AsyncSessionLocal() as session:
        n_dow = await detect_dow(session, dry_run)
        n_icfs = await detect_icfs(session, dry_run)
        n_act = await detect_icfs_actions(session, dry_run)
        if not dry_run:
            await session.commit()
        n_sent = await send_pending(session, dry_run)
        if not dry_run:
            await session.commit()
        logger.info("done: DoW=%d, ICFS filings=%d, ICFS actions=%d, sent=%d", n_dow, n_icfs, n_act, n_sent)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    asyncio.run(run(dry_run=args.dry_run))
