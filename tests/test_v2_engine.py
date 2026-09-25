"""
Tests for the engine modules added in version 2.0: climate, blocks, subunits,
network (tree + telescoping), pumps, economics and the measured BOQ.

Where a published worked example exists it is used as the reference
(FAO-56 Examples 8, 9, 10 and 11). Where it does not, the test states the
property being protected instead of a number chosen to make it pass.
"""

import json
import math
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from engine import climate as C          # noqa: E402
from engine import blocks as B           # noqa: E402
from engine import subunits as SU        # noqa: E402
from engine import network as N          # noqa: E402
from engine import pumps as P            # noqa: E402
from engine import economics as E        # noqa: E402
from engine import boq as BQ             # noqa: E402
from engine import kernels as K          # noqa: E402


def _pipes():
    with open(os.path.join(ROOT, "data", "pipes.json"), encoding="utf-8") as fh:
        return N.pipe_catalogue(json.load(fh)["pipes"])


def _wadi_local():
    from modules import layout as L
    with open(os.path.join(HERE, "data", "wadi_el_natrun.kml"), "rb") as fh:
        pts, _ = L.parse_kml(fh.read())
    loc = L.to_local(pts)
    return loc, L.oriented_extent(loc)


# ---------------------------------------------------------------- climate --

def test_fao56_example_8_extraterrestrial_radiation():
    # 20 S, 3 September (J = 246): Ra = 32.2 MJ/m2/day
    assert C.extraterrestrial_radiation(-20.0, 246) == pytest.approx(32.2, abs=0.1)


def test_fao56_example_9_daylight_hours():
    assert C.daylight_hours(-20.0, 246) == pytest.approx(11.7, abs=0.05)


def test_fao56_example_10_solar_radiation_from_sunshine():
    # Rio de Janeiro 22 deg 54' S, mid-May, n = 220 h / 31 d = 7.1 h:
    # Ra = 25.1, N = 10.9, Rs = 14.5 MJ/m2/day
    ra = C.extraterrestrial_radiation(-22.9, 135)
    N_ = C.daylight_hours(-22.9, 135)
    assert ra == pytest.approx(25.1, abs=0.1)
    assert N_ == pytest.approx(10.9, abs=0.05)
    assert C.solar_radiation_from_sunshine(7.1, N_, ra) == pytest.approx(14.5, abs=0.1)


def test_fao56_example_11_net_longwave():
    # Tmax 25.1, Tmin 19.1, ea 2.1 kPa, Rs 14.5, Rso 18.8 -> Rnl = 3.5
    assert C.net_longwave(25.1, 19.1, 2.1, 14.5, 18.8) == pytest.approx(3.5, abs=0.05)


def test_missing_radiation_raises_instead_of_being_invented():
    with pytest.raises(ValueError):
        C.net_radiation(30.0, 180, 35, 22, 45, 20)


def test_given_et0_is_passed_through_unchanged():
    rows = [{"et0": 3.0 + i * 0.1} for i in range(12)]
    out = C.et0_monthly(rows, 30.0, 20.0)
    assert [r["et0"] for r in out] == pytest.approx([3.0 + i * 0.1 for i in range(12)])
    assert all(r["source"] == "given" for r in out)


def test_monthly_pm_matches_the_daily_kernel_without_soil_heat():
    # Constant weather -> G = 0 -> the monthly value must equal the daily PM.
    row = {"tmax": 34.0, "tmin": 20.0, "rh": 45.0, "wind": 2.0, "sun": 11.0}
    out = C.et0_monthly([dict(row) for _ in range(12)], 30.4, 20.0)
    rad = C.net_radiation(30.4, C.mid_month_doy(7), 34.0, 20.0, 45.0, 20.0, sunshine_h=11.0)
    ref = K.et0_penman_monteith(34.0, 20.0, 45.0, 2.0, rad["rn"], 20.0)
    assert out[6]["et0"] == pytest.approx(ref, rel=1e-9)


def test_kc_curve_counts_exactly_the_season_days():
    km = C.kc_monthly(10, 1, 0.6, 1.15, 0.8, (30, 40, 45, 30))
    assert sum(r["days"] for r in km) == 145


def test_kc_curve_reaches_mid_and_end_values():
    assert C.kc_daily(0, 0.6, 1.15, 0.8, 30, 40, 45, 30) == 0.6
    assert C.kc_daily(90, 0.6, 1.15, 0.8, 30, 40, 45, 30) == 1.15
    assert C.kc_daily(145, 0.6, 1.15, 0.8, 30, 40, 45, 30) == pytest.approx(0.8)
    assert C.kc_daily(146, 0.6, 1.15, 0.8, 30, 40, 45, 30) is None


def test_usda_effective_rainfall_formula():
    assert C.effective_rainfall(100) == pytest.approx(100 * (125 - 20) / 125)
    assert C.effective_rainfall(300) == pytest.approx(155.0)
    assert C.effective_rainfall(50, "none") == 0.0


def test_peak_month_is_the_highest_daily_demand_not_the_largest_total():
    et0 = [{"et0": v} for v in [3, 4, 5, 6, 7, 8, 8, 7, 6, 5, 4, 3]]
    km = C.kc_monthly(5, 1, 0.5, 1.1, 0.7, (20, 30, 40, 30))
    res = C.monthly_requirement(et0, km, 1.0, [0] * 12, 0.9, 0.0, 1.0, "none")
    active = [r for r in res["rows"] if r["days"]]
    assert res["peak_etc_mm_d"] == max(r["etc_loc_mm_d"] for r in active)
    assert res["season_volume_m3"] == pytest.approx(
        sum(r["gross_mm"] for r in res["rows"]) * 10.0)


# ----------------------------------------------------------------- blocks --

def test_equal_area_split_on_the_real_field():
    loc, ext = _wadi_local()
    pieces = B.split_equal_area(loc, ext["bearing_deg"], 3)
    total = B.polygon_area(loc)
    assert len(pieces) == 3
    for p in pieces:
        assert B.polygon_area(p) == pytest.approx(total / 3, rel=1e-6)


def test_split_of_an_l_shape_conserves_area():
    L_shape = [[0, 0], [100, 0], [100, 40], [40, 40], [40, 100], [0, 100]]
    pieces = B.split_equal_area(L_shape, 0.0, 4)
    assert sum(B.polygon_area(p) for p in pieces) == pytest.approx(
        B.polygon_area(L_shape), rel=1e-9)


# --------------------------------------------------------------- subunits --

def test_subunits_cover_the_field_and_respect_the_manifold_limit():
    loc, ext = _wadi_local()
    r = SU.subunits_for_block(loc, ext["bearing_deg"], 2.0, 65.0, 0.5, 2.0,
                              "middle", 100.0)
    sus = r["subunits"]
    area = sum(s["area_ha"] for s in sus)
    assert area == pytest.approx(B.polygon_area(loc) / 10000.0, rel=0.03)
    for s in sus:
        assert s["n_rows"] * 2.0 <= 100.0 + 2.0
        assert s["q_m3h"] > 0


def test_mid_fed_manifold_is_straight_not_zigzag():
    """Regression: feeding each row at its own midpoint zig-zagged a 98 m band
    into a 131 m manifold on the Wadi plot."""
    loc, ext = _wadi_local()
    r = SU.subunits_for_block(loc, ext["bearing_deg"], 2.0, 65.0, 0.5, 2.0,
                              "middle", 100.0)
    for s in r["subunits"]:
        straight = (s["n_rows"] - 1) * 2.0
        assert s["manifold_m"] <= straight * 1.30


def test_shift_packing_never_exceeds_the_source():
    loc, ext = _wadi_local()
    sus = SU.subunits_for_block(loc, ext["bearing_deg"], 2.0, 65.0, 0.5, 2.0,
                                "end", 100.0)["subunits"]
    for strategy in SU.SHIFT_STRATEGIES:
        a = SU.allocate_shifts(sus, 40.0, strategy, (0, -200))
        assert a["feasible"]
        assert max(a["loads"]) <= 40.0 + 1e-9
        assert len(a["assignment"]) == len(sus)
        assert a["n_shifts"] >= math.ceil(sum(s["q_m3h"] for s in sus) / 40.0)


def test_a_subunit_larger_than_the_source_is_reported_not_split():
    sus = [{"id": "A", "q_m3h": 50.0, "centre": [0, 0]},
           {"id": "B", "q_m3h": 10.0, "centre": [0, 0]}]
    a = SU.allocate_shifts(sus, 40.0)
    assert a["oversize"] == ["A"] and not a["feasible"]


# ---------------------------------------------------------------- network --

def test_manifold_march_agrees_with_christiansen_on_the_ideal_case():
    """
    Equal outlets, equal spacing, one diameter, level: the march's total
    friction (inlet to last outlet) must reproduce the Christiansen result
    with the measured exponent. This is what licenses the march on the
    non-ideal manifolds where Christiansen does not apply.
    """
    cat = _pipes()
    n, sp, q = 40, 2.0, 0.4
    br = [[(sp * (k + 1), q) for k in range(n)]]
    for i, opt in enumerate(cat):
        m = N.manifold_march(br, [[i] * n], cat, [0.0])
        if m["max_velocity_ms"] > 2.5:
            continue
        ref = K.manifold_head_loss(n * q, opt.internal_mm, n * sp, n, 0.0,
                                   K.NU_20C, opt.roughness_mm)
        if ref["reynolds"] < 2e4:
            continue       # tail of the manifold laminar: Christiansen's
                           # single exponent no longer describes it
        assert m["friction_m"] == pytest.approx(ref["hf_m"], rel=0.02), opt


def test_telescoped_manifold_meets_the_allowance_and_saves_money():
    cat = _pipes()
    br = [[(2.0 * (k + 1), 0.4) for k in range(40)]]
    t = N.telescoped_manifold(br, cat, 0.6, 2.0, [0.0])
    assert t["satisfied"]
    assert t["spread_m"] <= 0.6
    assert t["cost"] < t["single_size_cost"]
    assert t["n_sizes"] <= 3
    # Diameters never increase downstream.
    dns = [r["pipe"]["internal_mm"] for r in t["runs"]]
    assert dns == sorted(dns, reverse=True)


def test_mid_fed_symmetric_manifold_is_solved_not_stalled():
    """Regression: a one-branch upgrade does not change the spread of a
    symmetric mid-fed manifold, and the first greedy stalled there."""
    cat = _pipes()
    br = [[(2.0 * (k + 1), 0.4) for k in range(20)] for _ in range(2)]
    t = N.telescoped_manifold(br, cat, 0.3, 2.0, [0.0, 0.0])
    assert t["satisfied"] and t["spread_m"] <= 0.3


def test_unattainable_uphill_manifold_is_reported_and_not_gold_plated():
    cat = _pipes()
    br = [[(2.0 * (k + 1), 0.4) for k in range(40)]]
    t = N.telescoped_manifold(br, cat, 0.3, 2.0, [1.0])     # 0.8 m rise > 0.3
    assert not t["satisfied"] and not t["attainable"]
    assert t["runs"][0]["pipe"]["nominal_mm"] < 315


def test_downhill_manifold_uses_friction_to_cancel_elevation():
    cat = _pipes()
    br = [[(2.0 * (k + 1), 0.4) for k in range(40)]]
    t = N.telescoped_manifold(br, cat, 0.3, 2.0, [-2.0])
    assert t["satisfied"]


def test_tree_reaches_every_valve_and_sizes_every_used_pipe():
    loc, ext = _wadi_local()
    sus = SU.subunits_for_block(loc, ext["bearing_deg"], 2.0, 65.0, 0.5, 2.0,
                                "middle", 100.0)["subunits"]
    net = N.auto_network(sus, [-150.0, -120.0], ext["bearing_deg"], "end")
    tree = N.build_tree(net["pipes"], net["source"], net["valves"])
    assert not tree["unattached"]
    a = SU.allocate_shifts(sus, 40.0)
    shifts = {}
    for sid, sh in a["assignment"].items():
        shifts.setdefault(sh, []).append(sid)
    q = {s["id"]: s["q_m3h"] for s in sus}
    sizing = N.size_tree(tree, shifts, q, _pipes(), 1.5, 2.0)
    assert set(sizing) == set(tree["used_edges"])
    for s in sizing.values():
        assert s["velocity_ms"] <= 1.5 + 1e-9
    h = N.tree_hydraulics(tree, sizing, shifts, q, {v: 14.0 for v in q})
    for sh, d in h["per_shift"].items():
        # Every open valve receives at least its requirement; the critical
        # one receives exactly it.
        for v, x in d["valves"].items():
            assert x["surplus_m"] >= -1e-9
        assert d["valves"][d["critical_valve"]]["surplus_m"] == pytest.approx(0.0, abs=1e-9)


def test_design_flow_of_a_pipe_is_its_downstream_open_demand():
    pipes = [{"id": "M", "kind": "mainline", "points": [[0, 0], [100, 0], [200, 0]]}]
    valves = [{"id": "A", "xy": [100, 0]}, {"id": "B", "xy": [200, 0]}]
    tree = N.build_tree(pipes, [0, 0], valves)
    shifts = {1: ["A"], 2: ["B"]}
    sizing = N.size_tree(tree, shifts, {"A": 10.0, "B": 20.0}, _pipes(), 1.5, None)
    by_len = sorted(sizing.values(), key=lambda s: s["length_m"])
    # First pipe carries max(10, 20) = 20, the second only B = 20; neither
    # carries 30, because A and B never open together.
    assert all(s["q_design_m3h"] == pytest.approx(20.0) for s in by_len)


def test_valve_off_the_drawn_line_is_attached_by_a_tap():
    pipes = [{"id": "M", "kind": "mainline", "points": [[0, 0], [100, 0]]}]
    tree = N.build_tree(pipes, [0, 0], [{"id": "A", "xy": [50, 8]}])
    assert "A" in tree["paths"]
    assert any(e["pipe_id"] == "tap" for e in tree["edges"])


def test_max_lateral_run_matches_the_v1_design_length():
    # 2 L/h at 0.5 m on 13.6 mm, 1.0 m allowable, level: v1 designed 65 m.
    r = N.max_lateral_run(2.0, 0.5, 13.6, 0.12, 0.0, 1.0)
    assert 60.0 <= r["max_run_m"] <= 70.0
    one_more = K.lateral_head_loss((r["max_run_m"] + 1) / 0.5 * 2.0 / 1000.0, 13.6,
                                   r["max_run_m"] + 1, int((r["max_run_m"] + 1) / 0.5),
                                   0.12, 0.0)
    assert one_more["spread_m"] > 1.0


# ------------------------------------------------------------------ pumps --

def test_quadratic_fit_reproduces_three_points():
    a, b, c = P.fit_quadratic([(0, 50), (20, 45), (40, 30)])
    for q, h in [(0, 50), (20, 45), (40, 30)]:
        assert a + b * q + c * q * q == pytest.approx(h)


def test_rising_curve_is_rejected():
    with pytest.raises(ValueError):
        P.fit_quadratic([(0, 20), (10, 25), (20, 32)])


def test_operating_point_lies_on_both_curves():
    pump = P.PumpCurve("t", 50.0, 0.0, -0.01, 40.0, 0.75)
    sys_h = P.system_curve(35.0, 8.0, 10.0, 6.0, 7.0, 0.5)
    op = P.operating_point(pump, sys_h)
    assert op is not None
    assert pump.head(op["q_m3h"]) == pytest.approx(sys_h(op["q_m3h"]), abs=1e-6)


def test_drip_system_curve_is_steeper_for_compensating_emitters():
    nonpc = P.system_curve(30.0, 5.0, 10.0, 5.0, 5.0, 0.5)
    pc = P.system_curve(30.0, 5.0, 10.0, 5.0, 5.0, 0.05)
    assert nonpc(30.0) == pytest.approx(pc(30.0))
    assert pc(33.0) > nonpc(33.0)


# -------------------------------------------------------------- economics --

def test_crf_known_value():
    # 10 %, 10 years -> 0.16275
    assert E.crf(0.10, 10) == pytest.approx(0.16275, abs=1e-5)
    assert E.crf(0.0, 8) == pytest.approx(1 / 8)


def test_replacements_fall_in_the_right_years():
    flows = E.cash_flows([{"capital": 100.0, "life_years": 5}], 12, 0, 0, 0)
    assert flows[0] == -100 and flows[5] == -100 and flows[10] == -100
    assert flows[12] == 0


def test_irr_zeroes_the_npv():
    flows = [-1000.0] + [300.0] * 5
    r = E.irr(flows)
    assert E.npv(r, flows) == pytest.approx(0.0, abs=1e-6)


def test_payback_interpolates():
    assert E.payback_year([-100.0, 40.0, 40.0, 40.0]) == pytest.approx(2.5)


# -------------------------------------------------------------------- boq --

def test_boq_prices_every_manifold_section_not_manifold_times_shifts():
    loc, ext = _wadi_local()
    sus = SU.subunits_for_block(loc, ext["bearing_deg"], 2.0, 65.0, 0.5, 2.0,
                                "middle", 100.0)["subunits"]
    net = N.auto_network(sus, [-150.0, -120.0], ext["bearing_deg"], "end")
    cat = _pipes()
    designs = {}
    for su, mf in zip(sus, net["manifolds"]):
        brs = N.manifold_branches(mf["points"], su["outlets"], mf["inlet_index"])
        designs[su["id"]] = N.telescoped_manifold(brs, cat, 0.5, 2.0, [0.0] * len(brs))
    with open(os.path.join(ROOT, "data", "unit_rates.json"), encoding="utf-8") as fh:
        rates = json.load(fh)["rates"]
    items = BQ.auto_boq(sus, designs, {}, {"nominal_mm": 16, "price_egp_per_m": 4.5},
                        {"se": 0.5, "price_egp": 0.9, "name": "e"}, 7.5, 35.0, 0,
                        5.2, rates)
    man_m = sum(i["Quantity"] for i in items if i["Category"] == "Manifolds")
    expected = sum(r["length_m"] for d in designs.values() for r in d["runs"]) * (
        1 + rates["waste_pct_pipe"] / 100.0)
    assert man_m == pytest.approx(expected, rel=1e-3)
    drip = [i for i in items if i["Category"] == "Dripline"][0]
    assert drip["Quantity"] == pytest.approx(
        sum(s["dripline_m"] for s in sus) * (1 + rates["waste_pct_dripline"] / 100.0), rel=1e-3)
