"""
End-to-end: the whole design on the Wadi El-Natrun plot, driven through the
real pages with Streamlit's AppTest harness.

Version 1's page test rendered every page with an EMPTY state, so every page
stopped at its stage guard and none of the design code below the guard ever
ran — the gap through which the unmarked NOT-PASSED export shipped. This
test fills each page in turn, presses its Save button, and checks that the
next page renders without an exception and that the state it produced is the
one the next page reads.
"""

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest
APP = os.path.join(ROOT, "app.py")


def _layout_state():
    from modules import layout as L
    with open(os.path.join(HERE, "data", "wadi_el_natrun.kml"), "rb") as fh:
        pts, _ = L.parse_kml(fh.read())
    local = L.to_local(pts)
    ext = L.oriented_extent(local)
    lat_c, lon_c = L.centroid(pts)
    return {"source": "test", "boundary_gps": pts, "boundary_local": local,
            "centre": [lat_c, lon_c], "area_m2": L.polygon_area_m2(local),
            "area_ha": L.polygon_area_m2(local) / 1e4, "long_m": ext["long_m"],
            "short_m": ext["short_m"], "bearing_deg": ext["bearing_deg"],
            "fill_ratio": ext["fill_ratio"], "assumed_rectangle": False,
            "source_local": [min(p[0] for p in local) - 15, min(p[1] for p in local) - 15]}


def _run(at):
    at.run()
    assert not at.exception, "\n".join(f"{e.type}: {e.message}\n{e.stack_trace}"
                                       for e in at.exception)
    return at


def _click(at, key):
    btn = [b for b in at.button if b.key == key]
    assert btn, f"button {key} not on the page; buttons: {[b.key for b in at.button]}"
    btn[0].click()
    return _run(at)


def _goto(at, page):
    at.session_state["page"] = page
    return _run(at)


def run_full_design():
    """Drive every page in turn; returns the AppTest with the finished design."""
    at = AppTest.from_file(APP, default_timeout=180)
    at.session_state["S"] = {"layout": _layout_state()}
    at.session_state["page"] = "home"
    _run(at)
    at.text_input[0].set_value("Wadi El-Natrun test")
    _run(at)
    _click(at, "save_setup")
    S = at.session_state["S"]
    assert S["setup"]["name"] == "Wadi El-Natrun test"
    assert S["setup"]["area_ha"] == pytest.approx(5.198, abs=0.01)

    _goto(at, "water")
    radio = [r for r in at.radio if "Peak month only" in r.options][0]
    radio.set_value("Peak month only")
    _run(at)
    _click(at, "save_water")
    assert at.session_state["S"]["water"]["etc"] > 0

    _goto(at, "emitter")
    _click(at, "save_emitter")
    assert at.session_state["S"]["emitter"]["max_run_m"] > 10

    _goto(at, "operation")
    _click(at, "save_operation")
    op = at.session_state["S"]["operation"]
    assert op["n_subunits"] >= 2 and op["shifts"] >= 1

    _goto(at, "network")
    _click(at, "save_network")
    assert at.session_state["S"]["network"]["n_valves"] == op["n_subunits"]

    _goto(at, "design")
    _click(at, "save_design")
    assert at.session_state["S"]["manifold"]["designs"]

    _goto(at, "quality")
    _click(at, "save_quality")
    _goto(at, "hydraulic")
    _click(at, "save_hyd")
    assert at.session_state["S"]["hydraulic"]["h_duty"] > 0
    _goto(at, "pump")
    _click(at, "save_pump")
    assert at.session_state["S"]["pump"]["power"]["brake_kw"] > 0
    _goto(at, "cost")
    _click(at, "save_cost")
    assert at.session_state["S"]["cost"]["total"] > 0
    _goto(at, "report")
    return at


@pytest.fixture(scope="module")
def designed():
    return run_full_design()


def test_every_page_saves_and_the_report_renders(designed):
    S = designed.session_state["S"]
    assert "verdict" in S
    assert S["verdict"]["checks_applied"] >= 15


def test_every_page_renders_with_the_full_design(designed):
    at = designed
    for page in ["home", "water", "emitter", "operation", "network", "design", "quality",
                 "hydraulic", "pump", "cost", "report"]:
        _goto(at, page)


def test_dark_mode_renders_the_full_design(designed):
    at = designed
    at.session_state["dark_mode_pref"] = True
    for page in ["operation", "design", "pump", "report"]:
        _goto(at, page)
    at.session_state["dark_mode_pref"] = False


def test_boq_has_no_manifold_times_shifts_line(designed):
    items = designed.session_state["S"]["cost"]["items"]
    man = [i for i in items if i["Category"] == "Manifolds"]
    assert man, "no manifold lines in the BOQ"
    S = designed.session_state["S"]
    measured = sum(r["length_m"] for d in S["manifold"]["designs"].values() for r in d["runs"])
    assert sum(i["Quantity"] for i in man) == pytest.approx(measured * 1.02, rel=0.01)


def test_exports_carry_the_verdict(designed):
    from engine import dxf as D, report_doc as RD
    S = designed.session_state["S"]
    txt = D.site_plan_dxf(S)
    assert "VERDICT:" in txt
    html = RD.design_report_html(S)
    assert ("NOT PASSED" in html) != S["verdict"]["passed"]
