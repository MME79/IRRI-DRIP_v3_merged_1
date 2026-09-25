"""
Regressions for the defects found in the end-to-end review of v2.0.0
(25 Sep 2026). Each test fails on v2.0.0 and passes on v2.0.1.

Unlike the tests that pin a formula to its own output, the leaching tests
check the numbers against the published source (FAO-29, Ayers & Westcot 1985,
Table 4 and eq. 9), and the state tests drive the real pages: change an input
AFTER the design was saved, and look at what the report says.
"""

import json
import math
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

from engine import kernels as K          # noqa: E402
from engine import pumps as P            # noqa: E402
from engine import state as STATE        # noqa: E402
from engine import checks as CH          # noqa: E402


# ------------------------------------------------------------------ 1. LR

def test_leaching_drip_form_uses_zero_yield_ece_tomato():
    # FAO-29 Table 4: tomato ECe 2.5 dS/m at 100 % yield, 13 dS/m at 0 %.
    # Drip (high-frequency) LR = ECw / (2 max ECe) = 1.0 / 26.
    assert K.leaching_requirement(1.0, 13.0) == pytest.approx(1.0 / 26.0)


def test_leaching_fao29_eq9_on_threshold():
    # FAO-29 eq. (9): LR = ECw / (5 ECe - ECw), ECe = threshold.
    assert K.leaching_requirement_fao29(1.0, 2.5) == pytest.approx(1.0 / 11.5)
    assert K.leaching_requirement_fao29(13.0, 2.5) == K.LR_CAP   # unleachable


def test_crop_table_has_zero_yield_ece_above_threshold():
    with open(os.path.join(ROOT, "data", "crops.json"), encoding="utf-8") as fh:
        crops = json.load(fh)["crops"]
    fao29 = {"Tomato (open field)": 13, "Potato": 10, "Cucumber": 10, "Sweet pepper": 8.6,
             "Onion (dry)": 7.4, "Maize (grain)": 10, "Wheat": 20, "Cotton": 27,
             "Sugar beet": 24, "Alfalfa": 16, "Table grape": 12, "Citrus (with cover)": 8.0,
             "Date palm": 32}
    for c in crops:
        assert "ece_max_ds_m" in c, c["name"]
        if c["ece_max_ds_m"] is not None:
            assert c["ece_max_ds_m"] > c["ece_threshold_ds_m"], c["name"]
            assert c["ece_max_ds_m"] == pytest.approx(fao29[c["name"]]), c["name"]


def test_default_tomato_lr_is_below_the_ten_percent_line():
    # The v2.0.0 default (ECw 1.0 on tomato) gave LR 20 % and inflated the depth.
    lr = K.leaching_requirement(1.0, 13.0)
    assert lr < 0.10
    assert K.gross_depth(10.0, 0.9, lr) == pytest.approx(10.0 / 0.9)


# -------------------------------------------------- 2. water balance/message

def test_water_balance_numbers():
    wb = K.water_balance(3.0, 18.0, 7.89, 5.0)
    assert wb["demand_m3_day"] == pytest.approx(394.5)
    assert wb["supply_m3_day"] == pytest.approx(54.0)
    assert not wb["ok"]
    assert wb["q_needed_m3h"] == pytest.approx(394.5 / 18.0)
    assert wb["area_max_ha"] == pytest.approx(54.0 / 78.9)
    assert K.water_balance(40.0, 18.0, 7.89, 5.0)["ok"]


def test_cycle_failure_advice_does_not_recommend_a_shorter_interval():
    r = K.operating_hours_check(98, 3.65, 1.5, 18.0)
    assert not r["cycle_fits"]
    assert "shorten the interval" not in r["reason"].lower()
    assert "source discharge" in r["reason"]


# ------------------------------------------------------------ 3. pump match

def test_pump_short_of_head_does_not_qualify():
    q_req = 34.08
    sys_h = P.system_curve(q_req, 8.0, 15.0, 11.0, 16.0, 0.03)
    h_req = sys_h(q_req)                            # 50.0 m: the curve passes the duty

    class Flat:                                     # a pump 1.8 m short at the duty
        q_max, q_bep = 80.0, 40.0
        def head(self, q): return 48.2 + 0.0 * q - 0.001 * q
        def efficiency(self, q): return 0.7
    r = P.match_pumps([Flat()], q_req, h_req, sys_h)[0]
    assert r["op"] is not None
    assert r["op"]["q_m3h"] >= q_req * 0.98        # v2.0.0 accepted this
    assert not r["qualifies"]


# ------------------------------------------------------------ 4. strict JSON

def test_project_json_is_strict_json():
    S = {"water": {"climate": {"rows": [{"Tmax": float("nan"), "Rs": float("inf")}]}},
         "setup": {"name": "x", "area_ha": 5.0}}
    txt = STATE.project_json(S, "2.0.1")

    def refuse(c):
        raise ValueError(f"non-standard JSON constant {c}")
    doc = json.loads(txt, parse_constant=refuse)
    assert doc["S"]["water"]["climate"]["rows"][0] == {"Tmax": None, "Rs": None}


# ---------------------------------------------------------- 5. stale state

def _mini_state():
    S = {"setup": {"q_avail": 40.0, "area_ha": 5.0, "last_updated": "t0"}}
    for key, payload in [("water", {"etc": 7.1}), ("emitter", {"q": 4}),
                         ("operation", {"shifts": 6}), ("network", {"v": 6}),
                         ("lateral", {"eu": 94}), ("manifold", {"ok": 1}),
                         ("quality", {"tds": 640}), ("fertigation", {"dose": 25}),
                         ("hydraulic", {"q_duty": 34.1}), ("pump", {"kw": 11}),
                         ("cost", {"total": 1})]:
        S[key] = payload
        STATE.stamp(S, key)
    return S


def test_fresh_state_is_current():
    assert STATE.stale_stages(_mini_state()) == {}


def test_timestamp_alone_does_not_make_anything_stale():
    S = _mini_state()
    S["setup"]["last_updated"] = "t1"
    assert STATE.stale_stages(S) == {}


def test_upstream_edit_marks_every_downstream_stage():
    S = _mini_state()
    S["setup"]["q_avail"] = 3.0
    stale = STATE.stale_stages(S)
    for k in STATE.DEPS:
        assert k in stale, k


def test_mid_chain_edit_marks_only_what_follows():
    S = _mini_state()
    S["network"] = {"v": 7}
    STATE.stamp(S, "network")
    stale = STATE.stale_stages(S)
    assert "operation" not in stale and "water" not in stale
    for k in ("lateral", "manifold", "hydraulic", "pump", "cost"):
        assert k in stale, k


def test_resaving_the_chain_clears_the_flag():
    S = _mini_state()
    S["setup"]["q_avail"] = 3.0
    for k in STATE.DEPS:
        STATE.stamp(S, k)
    assert STATE.stale_stages(S) == {}


def test_legacy_file_without_stamps_is_not_judged_until_stamped():
    S = _mini_state()
    del S["_stamps"]
    S["setup"]["q_avail"] = 3.0
    assert STATE.stale_stages(S) == {}
    STATE.stamp_all(S)
    assert STATE.stale_stages(S) == {}


def test_design_checks_fail_on_stale_state():
    S = _mini_state()
    S["setup"]["q_avail"] = 3.0
    checks = {c[0]: c for c in CH.design_checks(S)}
    assert not checks["Every saved result follows from the current inputs"][1]
    assert not checks["Design flow within the available source discharge"][1]


# ------------------------------------------- 6. through the real pages

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest


@pytest.fixture(scope="module")
def designed():
    import test_v2_flow as F
    return F.run_full_design()


def test_clean_walkthrough_leaves_nothing_stale(designed):
    S = designed.session_state["S"]
    assert STATE.stale_stages(S) == {}
    assert S["verdict"]["passed"], S["verdict"]["failed_checks"]


def test_report_refuses_pass_after_source_cut_then_recovers(designed):
    import test_v2_flow as F
    at = designed
    F._goto(at, "home")
    box = [n for n in at.number_input if n.label.startswith("Available discharge")][0]
    box.set_value(3.0)
    F._run(at)
    F._click(at, "save_setup")
    F._goto(at, "report")
    S = at.session_state["S"]
    vd = S["verdict"]
    assert not vd["passed"]
    assert "Every saved result follows from the current inputs" in vd["failed_checks"]
    assert any("out of date" in (m.value or "").lower() for m in at.markdown)
    from engine import report_doc as RD
    assert "NOT PASSED" in RD.design_report_html(S)

    # Restore the source and re-save the chain: the design is current again.
    F._goto(at, "home")
    box = [n for n in at.number_input if n.label.startswith("Available discharge")][0]
    box.set_value(float(40.0))
    F._run(at)
    F._click(at, "save_setup")
    for page, key in [("water", "save_water"), ("emitter", "save_emitter"),
                      ("operation", "save_operation"), ("network", "save_network"),
                      ("design", "save_design"), ("quality", "save_quality"),
                      ("hydraulic", "save_hyd"), ("pump", "save_pump"), ("cost", "save_cost")]:
        F._goto(at, page)
        if any(b.key == key for b in at.button):
            F._click(at, key)
    F._goto(at, "report")
    assert STATE.stale_stages(at.session_state["S"]) == {}


def test_unsaved_home_edit_survives_navigation():
    import test_v2_flow as F
    at = AppTest.from_file(F.APP, default_timeout=120)
    at.session_state["page"] = "home"
    F._run(at)
    at.text_input[0].set_value("Kept name")
    F._run(at)
    F._goto(at, "water")
    F._goto(at, "home")
    assert at.text_input[0].value == "Kept name"


def test_report_and_cost_survive_cleared_intermediate_stages(designed):
    """v2.0.0 crashed (KeyError 'hydraulic') when Operational Design was re-saved
    with new subunits: it cleared network..hydraulic but pump and cost survived,
    and Reports/Cost guarded only on their immediate predecessor."""
    import copy
    import test_v2_flow as F
    at = designed
    keep = copy.deepcopy(at.session_state["S"])
    S = at.session_state["S"]
    for k in ("network", "lateral", "manifold", "hydraulic"):
        S.pop(k, None)
    at.session_state["S"] = S
    for page in ("cost", "report", "pump", "hydraulic", "design"):
        F._goto(at, page)                       # _run asserts no exception
    assert any("Pipe Network Layout" in (w.value or "") for w in at.warning)
    at.session_state["S"] = keep


def test_changing_the_crop_resets_crop_coefficients(designed):
    """v2.0.0 kept the previous crop's Kc curve, root depth and salinity limits."""
    import copy
    import json as _json
    import test_v2_flow as F
    at = designed
    keep = copy.deepcopy(at.session_state["S"])
    with open(os.path.join(ROOT, "data", "crops.json"), encoding="utf-8") as fh:
        olive = [c for c in _json.load(fh)["crops"] if c["name"] == "Olive"][0]
    F._goto(at, "home")
    box = [s for s in at.selectbox if s.label == "Primary Crop Type"][0]
    box.set_value("Olive")
    F._run(at)
    F._click(at, "save_setup")
    F._goto(at, "water")
    nums = {n.label: n.value for n in at.number_input}
    assert nums["Kc mid"] == pytest.approx(olive["kc_mid"])
    assert nums["Effective root depth (m)"] == pytest.approx(olive["root_depth_m"])
    assert nums["Crop ECe threshold (dS/m)"] == pytest.approx(olive["ece_threshold_ds_m"])
    assert nums["Crop max ECe, zero yield (dS/m)"] == 0.0
    assert any("crop changed" in (m.value or "") for m in at.markdown)
    F._click(at, "save_water")
    w = at.session_state["S"]["water"]
    assert w["crop_name"] == "Olive" and "FAO-29 eq. (9)" in w["lr_method"]
    at.session_state["S"] = keep


# ------------------------------------------------ 7. pipe prices in the UI

def test_pipe_price_overrides_reach_the_catalogue_without_touching_the_file():
    from engine import boq as BQ
    with open(os.path.join(ROOT, "data", "pipes.json"), encoding="utf-8") as fh:
        cat = json.load(fh)
    p0 = cat["pipes"][0]
    k = BQ.pipe_key(p0)
    out = BQ.apply_pipe_prices(cat, {k: 99.5})
    assert out["pipes"][0]["price_egp_per_m"] == 99.5
    assert cat["pipes"][0]["price_egp_per_m"] == p0["price_egp_per_m"]   # not mutated
    assert BQ.apply_pipe_prices(cat, None) == cat


def test_new_pipe_prices_mark_the_sizing_and_cost_out_of_date(designed):
    import copy
    import test_v2_flow as F
    from engine import boq as BQ
    at = designed
    keep = copy.deepcopy(at.session_state["S"])
    S = at.session_state["S"]
    with open(os.path.join(ROOT, "data", "pipes.json"), encoding="utf-8") as fh:
        k = BQ.pipe_key(json.load(fh)["pipes"][2])
    S["pipe_prices"] = {k: 1.0}
    at.session_state["S"] = S
    F._goto(at, "cost")
    stale = STATE.stale_stages(at.session_state["S"])
    assert "manifold" in stale and "cost" in stale
    assert "operation" not in stale
    F._goto(at, "design")
    F._click(at, "save_design")
    for page, key in [("hydraulic", "save_hyd"), ("pump", "save_pump"), ("cost", "save_cost")]:
        F._goto(at, page)
        F._click(at, key)
    assert STATE.stale_stages(at.session_state["S"]) == {}
    at.session_state["S"] = keep


def test_home_offers_the_arabic_user_guide():
    import test_v2_flow as F
    assert os.path.getsize(os.path.join(ROOT, "docs", "IRRI-DRIP_User_Guide_AR.pdf")) > 100_000
    at = AppTest.from_file(F.APP, default_timeout=120)
    at.session_state["page"] = "home"
    F._run(at)
    # AppTest has no download_button accessor in every version: look for it in the tree
    labels = [getattr(e, "label", "") for e in at.get("download_button")]
    assert any("دليل المستخدم" in (l or "") for l in labels), labels
