from datetime import datetime
from zoneinfo import ZoneInfo

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from apps.ingest.scheduler import _dow_poll_cadence

ET = ZoneInfo("America/New_York")


def et(dt_str: str) -> datetime:
    return datetime.fromisoformat(dt_str).replace(tzinfo=ET)


# ── Tight window (90s) ──────────────────────────────────────────────────────

def test_tight_window_summer():
    # July 7 2026 = Tuesday, EDT (UTC-4)
    assert _dow_poll_cadence(et("2026-07-07 17:05:00")) == 90

def test_tight_window_winter():
    # Jan 15 2026 = Thursday, EST (UTC-5)
    assert _dow_poll_cadence(et("2026-01-15 17:05:00")) == 90

def test_tight_window_boundary_start():
    assert _dow_poll_cadence(et("2026-07-07 16:55:00")) == 90

def test_tight_window_boundary_end():
    # 17:20 is the start of the loose window, not tight
    assert _dow_poll_cadence(et("2026-07-07 17:20:00")) == 420


# ── Loose window (420s) ─────────────────────────────────────────────────────

def test_loose_window_summer():
    assert _dow_poll_cadence(et("2026-07-07 17:45:00")) == 420

def test_loose_window_winter():
    assert _dow_poll_cadence(et("2026-01-15 18:00:00")) == 420

def test_loose_window_boundary_end():
    # 18:30 is outside the window
    assert _dow_poll_cadence(et("2026-07-07 18:30:00")) is None


# ── Outside window ──────────────────────────────────────────────────────────

def test_before_window():
    assert _dow_poll_cadence(et("2026-07-07 09:00:00")) is None

def test_after_window():
    assert _dow_poll_cadence(et("2026-07-07 19:00:00")) is None

def test_midnight():
    assert _dow_poll_cadence(et("2026-07-07 00:00:00")) is None


# ── Weekend — polls run every day in case of weekend release ────────────────

def test_saturday_in_window():
    # July 4 2026 is a Saturday — should still poll
    assert _dow_poll_cadence(et("2026-07-04 17:05:00")) == 90

def test_sunday_in_window():
    # July 5 2026 is a Sunday — should still poll
    assert _dow_poll_cadence(et("2026-07-05 17:05:00")) == 90


# ── DST boundary ────────────────────────────────────────────────────────────

def test_dst_spring_forward():
    # March 9 2026 = Monday, first weekday after spring forward (Mar 8 is Sunday)
    # 5pm is EDT (UTC-4) = 21:05 UTC
    assert _dow_poll_cadence(et("2026-03-09 17:05:00")) == 90

def test_dst_fall_back():
    # Nov 2 2026 = Monday, first weekday after fall back (Nov 1 is Sunday)
    # 5pm is EST (UTC-5) = 22:05 UTC — window must still fire at local 5pm
    assert _dow_poll_cadence(et("2026-11-02 17:05:00")) == 90
