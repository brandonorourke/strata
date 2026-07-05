"""
Tests for DoW award extraction — normalization layer and validators.

The acceptance fixture uses the May 22, 2026 PTSG release (Viasat + Intelsat).
Tests verify that normalization and all validators behave correctly given the
known-good LLM output for that paragraph.

No live LLM calls. The validator and normalization functions are pure Python.
"""

import sys, os, types
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from datetime import date
from apps.ingest.extract_dow_awards import (
    _parse_cents,
    _parse_date,
    _piid_valid,
    _value_in_source,
    _validate,
)

# ── Normalization ─────────────────────────────────────────────────────────────

def test_parse_cents_full():
    assert _parse_cents('$437,665,005') == 43_766_500_500

def test_parse_cents_obligated():
    assert _parse_cents('$150,000,000') == 15_000_000_000

def test_parse_cents_million_suffix():
    assert _parse_cents('$437.7 million') == 43_770_000_000

def test_parse_cents_null():
    assert _parse_cents(None) is None

def test_parse_cents_unparseable():
    assert _parse_cents('not a number') is None

def test_parse_date_iso():
    assert _parse_date('2029-03-19') == date(2029, 3, 19)

def test_parse_date_null():
    assert _parse_date(None) is None

def test_parse_date_invalid():
    assert _parse_date('not-a-date') is None


# ── PIID grammar ──────────────────────────────────────────────────────────────

def test_piid_modern_valid():
    assert _piid_valid('FA880726FB004') is True

def test_piid_modern_second():
    assert _piid_valid('FA880726FB005') is True

def test_piid_hyphenated_valid():
    assert _piid_valid('FA8650-14-D-2411') is True

def test_piid_hyphenated_army():
    assert _piid_valid('W911SA-26-D-A019') is True

def test_piid_acronym_rejected():
    # Pure alpha, no digit — should fail
    assert _piid_valid('MARFLIR') is False

def test_piid_short_rejected():
    assert _piid_valid('FA88') is False


# ── Value grounding ───────────────────────────────────────────────────────────

PTSG_SOURCE = (
    "VIASAT Inc., (FA880726FB004), and INTELSAT General Communications LLC, "
    "(FA880726FB005), have been awarded a combined $437,665,005 firm-fixed-price, "
    "indefinite-delivery/indefinite-quantity, delivery contract for the procurement "
    "of space vehicles in support of the Protected Tactical Satellite-Global program. "
    "Work will be performed at the listed contractors' locations and is expected to "
    "be completed by March 19, 2029. Fiscal 2026 research, development, test and "
    "evaluation funds in the amount of $150,000,000 are being obligated at the time "
    "of award. The Space Systems Command, Los Angeles Air Force Base, Los Angeles, "
    "California, is the contracting activity."
)

def test_ceiling_grounded():
    assert _value_in_source('$437,665,005', PTSG_SOURCE) is True

def test_obligated_grounded():
    assert _value_in_source('$150,000,000', PTSG_SOURCE) is True

def test_fabricated_amount_not_grounded():
    assert _value_in_source('$999,999,999', PTSG_SOURCE) is False

def test_piid_grounded_in_source():
    assert 'FA880726FB004' in PTSG_SOURCE
    assert 'FA880726FB005' in PTSG_SOURCE


# ── May 22, 2026 fixture — validator acceptance test ─────────────────────────
#
# Simulates the known-good LLM output for the PTSG award and asserts that all
# validators pass. This is the hard acceptance requirement from the spec.

def _make_ptsg_award():
    """Plain namespace with the correct extracted values for the PTSG award."""
    a = types.SimpleNamespace(
        release_id          = 1,
        award_index         = 0,
        awardees            = [
            {'name': 'VIASAT Inc.', 'city': None, 'state': None},
            {'name': 'INTELSAT General Communications LLC', 'city': None, 'state': None},
        ],
        piids               = [
            {'value': 'FA880726FB004', 'excerpt': '(FA880726FB004)'},
            {'value': 'FA880726FB005', 'excerpt': '(FA880726FB005)'},
        ],
        ceiling_cents       = 43_766_500_500,
        ceiling_raw         = '$437,665,005',
        ceiling_excerpt     = '$437,665,005',
        obligated_cents     = 15_000_000_000,
        obligated_raw       = '$150,000,000',
        obligated_excerpt   = '$150,000,000',
        contract_type       = 'firm-fixed-price, indefinite-delivery/indefinite-quantity',
        completion_date     = date(2029, 3, 19),
        contracting_activity= 'The Space Systems Command, Los Angeles Air Force Base, Los Angeles, California',
        program_hint        = 'Protected Tactical Satellite-Global',
        llm_status          = 'ok',
        val_amount_format   = None,
        val_obligated_lte_ceiling = None,
        val_piid_grammar    = None,
        val_ceiling_grounded = None,
        val_obligated_grounded = None,
        val_piid_grounded   = None,
        val_date_plausible  = None,
        val_state_codes     = None,
        val_award_count_sane = None,
        val_flag_reasons    = None,
    )
    return a


def test_ptsg_all_validators_pass():
    award = _make_ptsg_award()
    flags = _validate(award, PTSG_SOURCE, trigger_count=1, award_total=1)
    assert flags == {}, f"Unexpected validation failures: {flags}"


def test_ptsg_amount_format():
    award = _make_ptsg_award()
    _validate(award, PTSG_SOURCE, trigger_count=1, award_total=1)
    assert award.val_amount_format is True


def test_ptsg_obligated_lte_ceiling():
    award = _make_ptsg_award()
    _validate(award, PTSG_SOURCE, trigger_count=1, award_total=1)
    assert award.val_obligated_lte_ceiling is True  # 150M < 437M


def test_ptsg_piid_grammar():
    award = _make_ptsg_award()
    _validate(award, PTSG_SOURCE, trigger_count=1, award_total=1)
    assert award.val_piid_grammar is True


def test_ptsg_ceiling_grounded():
    award = _make_ptsg_award()
    _validate(award, PTSG_SOURCE, trigger_count=1, award_total=1)
    assert award.val_ceiling_grounded is True


def test_ptsg_obligated_grounded():
    award = _make_ptsg_award()
    _validate(award, PTSG_SOURCE, trigger_count=1, award_total=1)
    assert award.val_obligated_grounded is True


def test_ptsg_piid_grounded():
    award = _make_ptsg_award()
    _validate(award, PTSG_SOURCE, trigger_count=1, award_total=1)
    assert award.val_piid_grounded is True


def test_ptsg_date_plausible():
    award = _make_ptsg_award()
    _validate(award, PTSG_SOURCE, trigger_count=1, award_total=1)
    assert award.val_date_plausible is True


def test_ptsg_awardee_cities_null():
    award = _make_ptsg_award()
    for a in award.awardees:
        assert a['city'] is None, f"Expected city=null for {a['name']}"


def test_ptsg_two_awardees():
    award = _make_ptsg_award()
    names = {a['name'] for a in award.awardees}
    assert 'VIASAT Inc.' in names
    assert 'INTELSAT General Communications LLC' in names


def test_ptsg_both_piids():
    award = _make_ptsg_award()
    values = {p['value'] for p in award.piids}
    assert values == {'FA880726FB004', 'FA880726FB005'}


# ── Validator edge cases ──────────────────────────────────────────────────────

def test_obligated_exceeds_ceiling_flagged():
    award = _make_ptsg_award()
    award.obligated_cents = award.ceiling_cents + 1
    flags = _validate(award, PTSG_SOURCE, trigger_count=1, award_total=1)
    assert 'obligated_lte_ceiling' in flags
    assert award.val_obligated_lte_ceiling is False


def test_ungrounded_amount_flagged():
    award = _make_ptsg_award()
    award.ceiling_raw = '$999,999,999'
    award.ceiling_cents = 99_999_999_900
    flags = _validate(award, PTSG_SOURCE, trigger_count=1, award_total=1)
    assert 'ceiling_grounded' in flags
    assert award.val_ceiling_grounded is False


def test_award_count_mismatch_flagged():
    award = _make_ptsg_award()
    # 3 triggers in source but only 1 award returned
    flags = _validate(award, PTSG_SOURCE, trigger_count=3, award_total=1)
    assert 'award_count_sane' in flags
    assert award.val_award_count_sane is False
