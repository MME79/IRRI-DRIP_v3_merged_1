"""
The four validation scripts run inside the test suite, so a change that
breaks one of them (or leaves its printed values stale, as happened to the
leaching requirement in v2.0.0 -> 3.0) fails here instead of only in
Run_Self_Test's log.
"""

import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run(name):
    r = subprocess.run([sys.executable, os.path.join(ROOT, "validation", name)],
                       capture_output=True, text=True, cwd=ROOT, timeout=300,
                       env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    return r.returncode, r.stdout + r.stderr


@pytest.mark.parametrize("name", ["worked_example.py", "edge_cases.py",
                                  "step_method.py", "published_cases.py"])
def test_script_exits_cleanly(name):
    code, out = _run(name)
    assert code == 0, out[-3000:]


def test_worked_example_uses_the_zero_yield_ece():
    code, out = _run("worked_example.py")
    assert "4.6 %" in out and "24.0 %" not in out, out[:1500]
    assert "11/11 checks passed" in out


def test_published_cases_include_fao56_and_fao29():
    code, out = _run("published_cases.py")
    assert "Ex.17 Bangkok April" in out and "Ex.18 Brussels 6 July" in out
    assert "FAO-29 Table 4" in out
    assert "FAIL" not in out


def test_edge_cases_report_no_findings():
    code, out = _run("edge_cases.py")
    assert "Total: 0 finding(s)" in out
