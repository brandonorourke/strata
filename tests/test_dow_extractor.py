"""Regex-layer tests for the DoW award extractor (`extract_dow_awards_v2._regex_groups`
and the PIID primitives). Covers the multi-PIID-parenthetical bug fixed 2026-07-12 —
an announcement like "(W58RGZ-26-G-0005, W58RGZ-26-F-0334)" lists the vehicle (BOA/IDIQ)
AND the order drawing against it; the old regex kept only the first and silently dropped
the rest. Only the deterministic regex layer is tested (the LLM merge needs an API call).
"""

import os
import sys

_ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, _ROOT)                                  # strata_core / apps.* imports
sys.path.insert(0, os.path.join(_ROOT, "apps", "ingest"))  # the module + its siblings

import extract_dow_awards_v2 as ex  # noqa: E402


def _piids(body: str) -> list[list[str]]:
    """PIIDs per award group, in order — the shape the UI/merge consumes."""
    return [[c["piid"] for c in g["piid_chunks"]] for g in ex._regex_groups(body)]


# ── The bug: multiple PIIDs in one parenthetical (vehicle + order) ───────────

def test_multi_piid_paren_captures_both():
    # THE regression. Vehicle (G-type BOA) + order (F-type) in one paren → keep both.
    body = ("AeroVironment Inc., Simi Valley, California, was awarded a $117,306,232 contract. "
            "Army Contracting Command is the contracting activity (W58RGZ-26-G-0005, W58RGZ-26-F-0334).")
    assert _piids(body) == [["W58RGZ-26-G-0005", "W58RGZ-26-F-0334"]]


def test_three_piids_in_one_paren():
    # DoW writes PIIDs dashed; the extra-scan uses the mod-stripping bare-dashed regex.
    body = "Foo Corp., City, State, was awarded a contract. Activity (W912CN-24-D-0002, W912CN-24-D-0003, W912CN-24-F-0034)."
    assert _piids(body) == [["W912CN-24-D-0002", "W912CN-24-D-0003", "W912CN-24-F-0034"]]


def test_mod_suffix_paren_extracts_clean_base():
    # Regression the corpus differential caught (release 93): "(PIID-P00008)" must yield the CLEAN
    # base PIID, not a truncated token — the anchored match rejects the over-long string, and the
    # bare fallback strips the mod. (The first fix truncated this to "M67854-22-F-1005-P00".)
    body = "Mod Co., City, State, was awarded a modification (M67854-22-F-1005-P00008)."
    assert _piids(body) == [["M67854-22-F-1005"]]


def test_slash_separated_pair():
    # Regression the corpus caught (release 31): "(order/vehicle)" → both PIIDs (bare fallback
    # splits on the slash).
    body = "Slash Co., City, State, was awarded a contract (SPRTA1-26-F-0175/SPE4A1-24-G-0014)."
    assert [set(g) for g in _piids(body)] == [{"SPRTA1-26-F-0175", "SPE4A1-24-G-0014"}]


def test_piid_with_amount_captures_only_the_piid():
    # "(PIID, $amount)" — the trailing amount must NOT become a second PIID.
    body = "Bar Corp., City, State, was awarded a contract. Activity (W58RGZ-26-F-0334, $437,665,005)."
    assert _piids(body) == [["W58RGZ-26-F-0334"]]


# ── Shape handling: dashless PIIDs, junk parens ─────────────────────────────

def test_dashless_piid_captured():
    # USASpending-style dashless PIIDs must still be caught (no regression from the fix).
    body = "Baz Inc., City, State, was awarded a contract. Activity (FA880725DB002)."
    assert _piids(body) == [["FA880725DB002"]]


def test_prose_and_amount_parentheticals_ignored():
    # "(10 received)", "(P550)", "($117,306,232)" contain no PIID-shaped token → nothing.
    body = ("Qux LLC, City, State, was awarded a contract; 10 offers were received (10 received) "
            "for the P550 (P550) system valued at ($117,306,232).")
    assert _piids(body) == []


def test_single_piid_baseline():
    body = "Solo Co., Town, State, was awarded a contract. Activity (N0003920D0058)."
    assert _piids(body) == [["N0003920D0058"]]


# ── Multiple awardees, each in its own parenthetical ────────────────────────

def test_multiple_awardees_separate_parens():
    body = ("A Co., Alpha, State, was awarded a $10,000,000 contract. Activity (W58RGZ-26-D-0001).\n\n"
            "B Corp., Bravo, State, was awarded a $5,000,000 contract. Activity (FA8807-26-C-0009).")
    groups = ex._regex_groups(body)
    assert [[c["piid"] for c in g["piid_chunks"]] for g in groups] == [
        ["W58RGZ-26-D-0001"], ["FA8807-26-C-0009"],
    ]
    # PIIDs stay attached to the correct awardee (positional city assignment).
    assert groups[0]["piid_chunks"][0]["city_raw"] == "Alpha"
    assert groups[1]["piid_chunks"][0]["city_raw"] == "Bravo"


# ── PIID type code (the 9th-char vehicle/order classifier) ──────────────────

def test_type_code_dashed():
    assert ex._piid_type_code("W58RGZ-26-G-0005") == "G"   # G = BOA / ordering agreement
    assert ex._piid_type_code("W58RGZ-26-F-0334") == "F"   # F = delivery/task order (a draw)


def test_type_code_dashless():
    assert ex._piid_type_code("FA880725DB002") == "D"      # D = IDIQ base (a vehicle)
    assert ex._piid_type_code("N0003920D0058") == "D"


def test_type_code_survives_mod_suffix():
    assert ex._piid_type_code("W58RGZ-26-F-0334-P00001") == "F"


def test_amount_has_no_type_code():
    # This is the real discriminator between a PIID and a "$amount" that slipped through —
    # amounts have no type code. (_is_piid alone is loose; the shape regex + this is the guard.)
    assert ex._piid_type_code("$117,306,232") is None


# ── PIID key normalization (join key across regex/LLM/feeds) ─────────────────

def test_piid_key_strips_dashes():
    assert ex._piid_key("W58RGZ-26-G-0005") == "W58RGZ26G0005"
    assert ex._piid_key("W58RGZ-26-F-0334") == "W58RGZ26F0334"


# ── Golden: the real 2026-06-03 release (end-to-end regex over a full day) ───

def test_golden_aerovironment_release_pairs_vehicle_and_order():
    path = os.path.join(os.path.dirname(__file__), "fixtures", "dow", "2026-06-03_release.txt")
    with open(path) as f:
        body = f.read()
    groups = ex._regex_groups(body)
    # Find the AeroVironment award group by its vehicle PIID; assert the order PIID is in the SAME group.
    av = [g for g in groups if any(c["piid"] == "W58RGZ-26-G-0005" for c in g["piid_chunks"])]
    assert len(av) == 1, "expected exactly one group carrying the AeroVironment vehicle PIID"
    piids = {c["piid"] for c in av[0]["piid_chunks"]}
    assert piids == {"W58RGZ-26-G-0005", "W58RGZ-26-F-0334"}


# ── PIID format-type coverage — one test per format the extractor is spec'd to catch ────

def test_format_dashed_in_prose():
    # bare fallback catches a dashed PIID mentioned in prose (not in parens)
    assert _piids("X, City, ST, was awarded a modification to W58RGZ-19-C-0003 for work.") == [["W58RGZ-19-C-0003"]]


def test_format_letter_serial():
    # serial segment may contain letters
    assert _piids("X, City, ST (N00164-16-G-JQ69).") == [["N00164-16-G-JQ69"]]


def test_format_purchase_order_type_kept():
    # type 'P' (purchase order) is a contract instrument — kept
    assert _piids("X, City, ST (N0038924P1234).") == [["N0038924P1234"]]


def test_format_solicitation_types_excluded():
    # types R/Q/S/I/J/T are SOLICITATION numbers, not contract PIIDs — must be dropped
    for t in ("R", "Q", "S", "I", "J", "T"):
        assert _piids(f"X, City, ST (FA8807-24-{t}-B009).") == [], f"type {t} should be excluded"


def test_format_unicode_dashes_normalized():
    # figure/en-dashes (U+2010 etc.) are normalized to ASCII before matching (the real pipeline step)
    body = ex._norm_dashes("X, City, ST (SPE603‐26‐C‐5013).")
    assert [[c["piid"] for c in g["piid_chunks"]] for g in ex._regex_groups(body)] == [["SPE603-26-C-5013"]]


# ── Known limitations — documented + locked (flip these if the gap is ever closed) ──────

def test_gap_dashless_in_prose_not_caught():
    # KNOWN GAP: the prose fallback is dashed-only, so a DASHLESS PIID in prose is missed.
    assert _piids("X, City, ST, was awarded a modification to FA880725DB002 for work.") == []


def test_gap_dashless_extra_in_paren_not_caught():
    # KNOWN GAP: the multi-PIID extra-scan is dashed-only, so a second DASHLESS PIID in one paren is
    # missed (the first, via the anchored match, is kept).
    assert _piids("X, City, ST (FA880725DB002, N0003920D0058).") == [["FA880725DB002"]]


# ── Golden fixtures — real releases covering the hard patterns ──────────────────────────

def _fixture_piids(name: str) -> set[str]:
    path = os.path.join(os.path.dirname(__file__), "fixtures", "dow", name)
    with open(path) as f:
        return {c["piid"] for g in ex._regex_groups(ex._norm_dashes(f.read())) for c in g["piid_chunks"]}


def test_golden_multi_award_recovers_all_eleven():
    # 2023-04-03: an 11-way IDIQ award — every W91278-23-D-0044..0054 present (the multi-PIID fix).
    p = _fixture_piids("2023-04-03_release.txt")
    assert all(f"W91278-23-D-00{n}" in p for n in range(44, 55))


def test_golden_mod_suffix_stored_as_clean_base():
    # 2026-02-20: a mod-suffixed PIID must appear as the clean base, never a truncated token.
    p = _fixture_piids("2026-02-20_release.txt")
    assert "M67854-22-F-1005" in p
    assert not any(x.startswith("M67854-22-F-1005-P00") for x in p)


def test_golden_dashed_and_dashless_multi():
    # 2026-05-19: dashed multi (FA2823-26-D-0006/7/8) + dashless multi (HR001126DE002..009).
    p = _fixture_piids("2026-05-19_release.txt")
    assert all(f"FA2823-26-D-000{n}" in p for n in (6, 7, 8))
    assert all(f"HR001126DE00{n}" in p for n in range(2, 10))
