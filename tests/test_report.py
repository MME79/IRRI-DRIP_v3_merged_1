"""
Export-side reporting: the verdict must survive leaving the screen.

Found in the field, not by the test suite. Dr. Mohamed ran a design on his own
Wadi El-Natrun field; the report page reported "1 of 15 design checks failed"
and then offered a workbook, a drawing and a snapshot that carried no mark of
the failure anywhere a reader opens. The page smoke test renders the report
page with an empty state, stops at the stage guard, and therefore never
executed one line of the export block.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import report as REP           # noqa: E402
from engine import kernels as K            # noqa: E402


CHECKS_OK = [("Lateral head spread within allowable", True, "1.0 m", "<= 2.0 m"),
             ("Emission uniformity meets target", True, "92 %", ">= 90 %")]
CHECKS_BAD = [("Lateral head spread within allowable", False, "3.9 m", "<= 2.0 m"),
              ("Emission uniformity meets target", True, "92 %", ">= 90 %")]


def test_a_single_failure_makes_the_whole_verdict_fail():
    v = REP.verdict_from_checks(CHECKS_BAD)
    assert v["passed"] is False
    assert v["checks_applied"] == 2
    assert v["checks_failed"] == 1
    assert v["failed_checks"] == ["Lateral head spread within allowable"]


def test_all_passing_is_a_pass():
    v = REP.verdict_from_checks(CHECKS_OK)
    assert v["passed"] is True and v["failed_checks"] == []


def test_first_row_of_the_workbook_states_the_verdict():
    rows = REP.verdict_rows(REP.verdict_from_checks(CHECKS_BAD))
    assert rows[0] == {"Item": "Design verdict", "Value": "NOT PASSED"}
    assert any("must not be issued" in str(r["Value"]).lower() for r in rows)
    assert any(r["Value"] == "Lateral head spread within allowable" for r in rows)


def test_a_passing_workbook_still_demands_verification():
    rows = REP.verdict_rows(REP.verdict_from_checks(CHECKS_OK))
    assert rows[0]["Value"] == "PASSED"
    assert any("independent verification" in str(r["Value"]).lower() for r in rows)
    assert not any("must not be issued" in str(r["Value"]).lower() for r in rows)


def test_failed_design_is_recognisable_from_the_filename_alone():
    v_bad = REP.verdict_from_checks(CHECKS_BAD)
    v_ok = REP.verdict_from_checks(CHECKS_OK)
    assert REP.stamped_filename("wadi", v_bad) == "wadi_NOT-PASSED"
    assert REP.stamped_filename("wadi", v_ok) == "wadi"


# --- the exported Assumptions sheet must not describe a method not used ----

def test_assumption_reports_the_exponent_actually_used_not_a_hard_coded_two():
    res = {"velocity_exponent": 1.752, "exponent_mode": "measured"}
    txt = REP.exponent_assumption(res, 130)
    assert "m = 1.752" in txt
    assert "measured" in txt
    # The m = 2 figure may appear only as an explicit comparison.
    assert "m = 2.000 would give" in txt
    assert f"F = {K.christiansen_f(130, 1.752):.4f}" in txt


def test_conventional_mode_is_reported_as_such():
    res = {"velocity_exponent": 2.0, "exponent_mode": "conventional"}
    txt = REP.exponent_assumption(res, 130)
    assert "m = 2.000" in txt and "conventional" in txt


def test_a_missing_exponent_is_reported_missing_not_defaulted_to_two():
    txt = REP.exponent_assumption({}, 130)
    assert "not recorded" in txt
    assert "m = 2.000 (" not in txt


# --- wiring guard ---------------------------------------------------------
# These are source-level assertions, which is weaker than exercising the page.
# They exist because the export block of modules/plant.py is still NOT covered
# by any rendering test: tests/test_pages.py renders the report page with an
# empty state and stops at the stage guard. Until a full headless design
# fixture exists, this is what stands between the tested helpers above and a
# page that quietly stops calling them.

def _plant_source():
    here = os.path.dirname(os.path.abspath(__file__))
    # v2.0: the report page is modules/reports.py.
    with open(os.path.join(os.path.dirname(here), "modules", "reports.py"),
              encoding="utf-8") as fh:
        return fh.read()


def test_page_delegates_to_the_tested_helpers():
    src = _plant_source()
    for call in ("REP.verdict_from_checks(", "REP.verdict_rows(",
                 "REP.exponent_assumption(", "REP.stamped_filename("):
        assert call in src, f"report page no longer calls {call}"


def test_page_carries_no_hard_coded_exponent_assumption():
    # The literal that was wrong for four versions.
    assert "velocity exponent m = 2" not in _plant_source()


def test_verdict_sheet_is_written_before_the_summary_sheet():
    src = _plant_source()
    i_verdict = src.index('sheet_name="Verdict"')
    i_summary = src.index('sheet_name="Design summary"')
    assert i_verdict < i_summary, "the workbook must open on the verdict"
