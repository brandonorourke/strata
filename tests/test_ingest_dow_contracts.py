from datetime import date

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from apps.ingest.ingest_dow_contracts import _parse_release_date


def test_full_month_name():
    assert _parse_release_date("Contracts for March 2, 2026") == date(2026, 3, 2)

def test_full_month_name_caps():
    assert _parse_release_date("Contracts For July 2, 2026") == date(2026, 7, 2)

def test_abbreviated_month_with_period():
    assert _parse_release_date("Contracts For Jun. 8, 2021") == date(2021, 6, 8)

def test_abbreviated_month_july():
    # Jul. appears frequently in 2020–2021 era titles
    assert _parse_release_date("Contracts For Jul. 27, 2020") == date(2020, 7, 27)

def test_abbreviated_month_feb():
    assert _parse_release_date("Contracts For Feb. 27, 2026") == date(2026, 2, 27)

def test_multi_day_range_returns_first_date():
    # "Contracts for Feb. 2, 2026, Through Feb. 4, 2026" — only one record like this
    # The regex grabs the first date match, which is the start of the range
    assert _parse_release_date("Contracts for Feb. 2, 2026, Through Feb. 4, 2026") == date(2026, 2, 2)

def test_no_date_returns_none():
    assert _parse_release_date("Contracts") is None

def test_garbage_returns_none():
    assert _parse_release_date("") is None
