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
    _normalize_for_grounding,
    _normalize_name,
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

def test_normalize_for_grounding_dashes():
    assert _normalize_for_grounding('firm–fixed—price') == 'firm-fixed-price'

def test_normalize_for_grounding_smart_quotes():
    assert _normalize_for_grounding('‘hello’') == "'hello'"

def test_normalize_for_grounding_nbsp():
    assert _normalize_for_grounding('A B') == 'A B'

def test_normalize_name_casefold():
    assert _normalize_name('VIASAT Inc.') == 'viasat inc'

def test_normalize_name_null():
    assert _normalize_name(None) is None


# ── May 22, 2026 fixture ──────────────────────────────────────────────────────
#
# Simulates the known-good LLM output for the PTSG award.
# $437,665,005 is a combined_award_value (not maximum_ceiling), so the
# conditional-math (obligation ≤ ceiling) check does not run for this fixture.

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

PTSG_PURPOSE_EXCERPT = (
    "for the procurement of space vehicles in support of the Protected Tactical "
    "Satellite-Global program"
)

PTSG_FUNDING_EXCERPT = "$150,000,000 are being obligated at the time of award"


def _make_ptsg_award():
    return types.SimpleNamespace(
        release_id          = 1,
        award_index         = 0,
        awardees            = [
            {'name_raw': 'VIASAT Inc.',
             'name_normalized': 'viasat inc',
             'city_raw': None, 'state_raw': None, 'country_raw': None},
            {'name_raw': 'INTELSAT General Communications LLC',
             'name_normalized': 'intelsat general communications llc',
             'city_raw': None, 'state_raw': None, 'country_raw': None},
        ],
        piids               = [
            {'value': 'FA880726FB004', 'excerpt': '(FA880726FB004)'},
            {'value': 'FA880726FB005', 'excerpt': '(FA880726FB005)'},
        ],
        amounts             = [
            {'raw': '$437,665,005', 'cents': 43_766_500_500,
             'kind': 'combined_award_value', 'scope': 'combined_awardees',
             'excerpt': '$437,665,005'},
            {'raw': '$150,000,000', 'cents': 15_000_000_000,
             'kind': 'initial_obligation', 'scope': 'combined_awardees',
             'excerpt': '$150,000,000'},
        ],
        funding_at_award    = {'status': 'amount_stated', 'excerpt': PTSG_FUNDING_EXCERPT},
        action_type         = 'award',
        instrument_type     = 'IDIQ',
        pricing_type_raw    = 'firm-fixed-price',
        completion_date_raw = 'March 19, 2029',
        completion_date     = date(2029, 3, 19),
        contracting_activity= 'The Space Systems Command, Los Angeles Air Force Base, Los Angeles, California',
        program_hint        = 'Protected Tactical Satellite-Global',
        purpose             = 'procurement of space vehicles in support of the Protected Tactical Satellite-Global program',
        purpose_excerpt     = PTSG_PURPOSE_EXCERPT,
        source_excerpt      = PTSG_SOURCE,
        llm_status          = 'ok',
        flags               = None,
    )


def test_ptsg_all_validators_pass():
    award = _make_ptsg_award()
    flags = _validate(award, PTSG_SOURCE, trigger_count=1, award_total=1)
    assert flags == {}, f"Unexpected validation failures: {flags}"


def test_ptsg_two_awardees():
    award = _make_ptsg_award()
    names = {a['name_raw'] for a in award.awardees}
    assert 'VIASAT Inc.' in names
    assert 'INTELSAT General Communications LLC' in names


def test_ptsg_awardees_city_null():
    award = _make_ptsg_award()
    for a in award.awardees:
        assert a['city_raw'] is None, f"Expected city_raw=null for {a['name_raw']}"


def test_ptsg_awardees_country_null():
    award = _make_ptsg_award()
    for a in award.awardees:
        assert a['country_raw'] is None


def test_ptsg_both_piids():
    award = _make_ptsg_award()
    values = {p['value'] for p in award.piids}
    assert values == {'FA880726FB004', 'FA880726FB005'}


def test_ptsg_combined_award_value():
    award = _make_ptsg_award()
    cv = next((a for a in award.amounts if a['kind'] == 'combined_award_value'), None)
    assert cv is not None
    assert cv['cents'] == 43_766_500_500
    assert cv['scope'] == 'combined_awardees'


def test_ptsg_initial_obligation():
    award = _make_ptsg_award()
    ob = next((a for a in award.amounts if a['kind'] == 'initial_obligation'), None)
    assert ob is not None
    assert ob['cents'] == 15_000_000_000


def test_ptsg_no_maximum_ceiling():
    # $437M is combined_award_value — obligation ≤ ceiling check must NOT run
    award = _make_ptsg_award()
    ceiling = next((a for a in award.amounts if a['kind'] == 'maximum_ceiling'), None)
    assert ceiling is None


def test_ptsg_funding_status():
    award = _make_ptsg_award()
    assert award.funding_at_award['status'] == 'amount_stated'


def test_ptsg_action_instrument():
    award = _make_ptsg_award()
    assert award.action_type     == 'award'
    assert award.instrument_type == 'IDIQ'
    assert award.pricing_type_raw == 'firm-fixed-price'


def test_ptsg_completion_date():
    award = _make_ptsg_award()
    assert award.completion_date == date(2029, 3, 19)
    assert award.completion_date_raw == 'March 19, 2029'


# ── Validator edge cases ──────────────────────────────────────────────────────

def test_fiscal_date_flags_date_inconsistent():
    award = _make_ptsg_award()
    award.completion_date_raw = 'fiscal 2030'
    award.completion_date = date(2030, 1, 1)   # model wrongly parsed a fiscal year
    flags = _validate(award, PTSG_SOURCE, trigger_count=1, award_total=1)
    assert 'date_inconsistent' in flags


def test_fiscal_date_null_completion_passes():
    award = _make_ptsg_award()
    award.completion_date_raw = 'fiscal 2030'
    award.completion_date = None
    flags = _validate(award, PTSG_SOURCE, trigger_count=1, award_total=1)
    assert 'date_inconsistent' not in flags


def test_invalid_enum_amount_kind():
    award = _make_ptsg_award()
    award.amounts[0]['kind'] = 'not_a_kind'
    flags = _validate(award, PTSG_SOURCE, trigger_count=1, award_total=1)
    assert 'invalid_enum_amount_kind' in flags


def test_invalid_enum_action_type():
    award = _make_ptsg_award()
    award.action_type = 'grant'
    flags = _validate(award, PTSG_SOURCE, trigger_count=1, award_total=1)
    assert 'invalid_enum_action_type' in flags


def test_invalid_enum_instrument_type():
    award = _make_ptsg_award()
    award.instrument_type = 'blanket_purchase'
    flags = _validate(award, PTSG_SOURCE, trigger_count=1, award_total=1)
    assert 'invalid_enum_instrument_type' in flags


def test_funding_status_mismatch_amount_stated_no_obligation():
    award = _make_ptsg_award()
    award.amounts = [a for a in award.amounts if a['kind'] != 'initial_obligation']
    flags = _validate(award, PTSG_SOURCE, trigger_count=1, award_total=1)
    assert 'funding_status_mismatch' in flags


def test_funding_status_none_obligated_with_obligation():
    award = _make_ptsg_award()
    award.funding_at_award = {'status': 'none_obligated', 'excerpt': None}
    flags = _validate(award, PTSG_SOURCE, trigger_count=1, award_total=1)
    assert 'funding_status_mismatch' in flags


def test_obligation_exceeds_ceiling_flagged():
    award = _make_ptsg_award()
    # Introduce a maximum_ceiling smaller than the obligation
    award.amounts = [
        {'raw': '$100,000,000', 'cents': 10_000_000_000,
         'kind': 'maximum_ceiling', 'scope': 'combined_awardees', 'excerpt': '$100,000,000'},
        {'raw': '$150,000,000', 'cents': 15_000_000_000,
         'kind': 'initial_obligation', 'scope': 'combined_awardees', 'excerpt': '$150,000,000'},
    ]
    # Need $100M in source for grounding; use a modified source
    source = PTSG_SOURCE.replace('$437,665,005', '$100,000,000')
    flags = _validate(award, source, trigger_count=1, award_total=1)
    assert 'obligation_exceeds_ceiling' in flags


def test_obligation_not_compared_to_combined_award_value():
    # combined_award_value is NOT maximum_ceiling — no math check runs
    award = _make_ptsg_award()
    # obligation ($150M) > combined_award_value would be weird, but should not trigger
    # obligation_exceeds_ceiling because combined_award_value != maximum_ceiling
    flags = _validate(award, PTSG_SOURCE, trigger_count=1, award_total=1)
    assert 'obligation_exceeds_ceiling' not in flags


def test_ungrounded_amount_flagged():
    award = _make_ptsg_award()
    award.amounts[0]['raw'] = '$999,999,999'
    award.amounts[0]['cents'] = 99_999_999_900
    flags = _validate(award, PTSG_SOURCE, trigger_count=1, award_total=1)
    assert 'ungrounded_amount' in flags


def test_ungrounded_piid_flagged():
    award = _make_ptsg_award()
    award.piids[0]['value'] = 'FAKEPID001'
    flags = _validate(award, PTSG_SOURCE, trigger_count=1, award_total=1)
    assert 'ungrounded_piid' in flags


def test_state_unrecognized_flagged():
    award = _make_ptsg_award()
    award.awardees[0]['state_raw'] = 'XZ'
    flags = _validate(award, PTSG_SOURCE, trigger_count=1, award_total=1)
    assert 'state_unrecognized' in flags


def test_foreign_country_not_flagged_as_bad_state():
    award = _make_ptsg_award()
    award.awardees[0]['state_raw'] = None
    award.awardees[0]['country_raw'] = 'Singapore'
    flags = _validate(award, PTSG_SOURCE, trigger_count=1, award_total=1)
    assert 'state_unrecognized' not in flags


def test_dc_state_code_accepted():
    award = _make_ptsg_award()
    award.awardees[0]['state_raw'] = 'D.C.'
    flags = _validate(award, PTSG_SOURCE, trigger_count=1, award_total=1)
    assert 'state_unrecognized' not in flags


def test_award_count_low_flagged():
    award = _make_ptsg_award()
    flags = _validate(award, PTSG_SOURCE, trigger_count=5, award_total=1)
    assert 'award_count_low' in flags


def test_grounding_normalization_passes_unicode_dash():
    # Source text has en-dash in amount position; normalized match should succeed
    award = _make_ptsg_award()
    # Put an en-dash in source but not in the raw amount value
    source_with_dash = PTSG_SOURCE.replace('$437,665,005', '$437–665,005')
    award.amounts[0]['raw'] = '$437-665,005'   # hyphenated form
    award.amounts[0]['excerpt'] = '$437-665,005'
    # Both sides normalize dashes → '-', so this should pass grounding
    flags = _validate(award, source_with_dash, trigger_count=1, award_total=1)
    assert 'ungrounded_amount' not in flags
