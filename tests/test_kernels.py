"""
IRRI-DRIP — regression and validation tests for the engineering kernels.

Where a published value exists, the test asserts against that value and
names the source in the docstring. Where none exists, the test asserts an
internal consistency property or a hand calculation reproduced in the
docstring.
"""

import math
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import kernels as K


# ---------------------------------------------------------------------------
# Christiansen F — validated against published tabulated values
# ---------------------------------------------------------------------------

def test_christiansen_f_darcy_n10():
    """
    Christiansen F for N = 10 outlets with velocity exponent m = 2
    (Darcy-Weisbach) is tabulated at 0.385.
    """
    assert abs(K.christiansen_f(10, 2.0) - 0.385) < 0.001


def test_christiansen_f_hazen_n10():
    """
    Christiansen F for N = 10 with m = 1.852 (Hazen-Williams) is tabulated
    at 0.402. Confirms the exponent is actually being used, which is the
    silent-error case this program is built to avoid.
    """
    assert abs(K.christiansen_f(10, 1.852) - 0.402) < 0.001


def test_christiansen_f_asymptote():
    """As N -> infinity, F -> 1/(m+1) = 1/3 for m = 2."""
    assert abs(K.christiansen_f(100000, 2.0) - 1.0 / 3.0) < 1e-4


def test_darcy_and_hazen_F_differ():
    """The two exponents must not give the same factor."""
    assert K.christiansen_f(20, 2.0) != K.christiansen_f(20, 1.852)


# ---------------------------------------------------------------------------
# Friction factor
# ---------------------------------------------------------------------------

def test_blasius_reference_value_retained():
    """Blasius: f = 0.316 * Re^-0.25. At Re = 1e4 this is exactly 0.0316."""
    assert abs(K.blasius_friction_factor(1.0e4) - 0.0316) < 1e-6


def test_swamee_jain_matches_blasius_on_smooth_pipe():
    """
    On a hydraulically smooth pipe the design formula must agree with the
    classical smooth-pipe result to within a few per cent across the range
    where Blasius is valid.
    """
    for re in (5.0e3, 1.0e4, 5.0e4, 1.0e5):
        f_sj, _ = K.friction_factor(re, 0.0)
        f_bl = K.blasius_friction_factor(re)
        assert abs(f_sj - f_bl) / f_bl < 0.05, (re, f_sj, f_bl)


def test_swamee_jain_valid_above_1e5():
    """
    The mainline case that the edge-case probe flagged: Blasius was being
    extrapolated past its 1e5 ceiling. Swamee-Jain is valid to 1e8 and must
    return a sensible factor with a regime label that does not say
    'extrapolated'.
    """
    f, regime = K.friction_factor(2.2e5, 0.007 / 96.8)
    assert 0.010 < f < 0.030
    assert "extrapolat" not in regime.lower()


def test_roughness_increases_friction():
    f_smooth, _ = K.friction_factor(1.0e5, 0.0)
    f_rough, _ = K.friction_factor(1.0e5, 0.15 / 100.0)
    assert f_rough > f_smooth


def test_laminar_regime():
    f, regime = K.friction_factor(1000.0)
    assert abs(f - 64.0 / 1000.0) < 1e-9
    assert regime == "laminar"


def test_transitional_flagged():
    _, regime = K.friction_factor(3000.0)
    assert "uncertain" in regime


def test_typical_lateral_is_in_smooth_turbulent_range():
    """
    A 16 mm lateral carrying 0.30 m3/h sits at Re of order 1e4 — inside the
    smooth-pipe regime, which is precisely where Hazen-Williams with C = 150
    is not calibrated.
    """
    re = K.reynolds_number(0.30, 16.0)
    assert 4000 < re < 1.0e5


# ---------------------------------------------------------------------------
# Head loss — hand calculation reproduced
# ---------------------------------------------------------------------------

def test_head_loss_hand_calculation():
    """
    Hand check, 16 mm ID, Q = 0.30 m3/h, L = 100 m, nu = 1.004e-6,
    roughness 0.007 mm (PE).

      A       = pi*0.016^2/4                    = 2.0106e-4 m2
      v       = (0.30/3600)/A                   = 0.4145 m/s
      Re      = v*D/nu                          = 6605
      eps/D   = 0.007/16                        = 4.375e-4
      Re^0.9  = 2742.6
      inner   = 4.375e-4/3.7 + 5.74/2742.6      = 2.2111e-3
      f       = 0.25/log10(inner)^2             = 0.035458
      v^2/(2g)= 0.17181/19.62                   = 0.008757 m
      f*(L/D) = 0.035458*6250                   = 221.61
      hf      = 221.61*0.008757                 = 1.941 m
    """
    r = K.head_loss_darcy(0.30, 16.0, 100.0)
    assert abs(r["velocity_ms"] - 0.4145) < 0.002
    assert abs(r["reynolds"] - 6605) < 30
    assert abs(r["friction_factor"] - 0.035458) < 1e-5
    assert abs(r["hf_m"] - 1.941) < 0.01


def test_head_loss_scales_with_length():
    a = K.head_loss_darcy(0.30, 16.0, 50.0)["hf_m"]
    b = K.head_loss_darcy(0.30, 16.0, 100.0)["hf_m"]
    assert abs(b - 2.0 * a) < 1e-9


# ---------------------------------------------------------------------------
# Emitter local losses — the term sprinkler kernels omit
# ---------------------------------------------------------------------------

def test_emitter_local_loss_is_material():
    """
    100 m lateral, emitters at 0.33 m, le = 0.15 m per emitter.
    n = 303 emitters -> added length 45.5 m, i.e. 31 percent of the
    equivalent length. Omitting it under-predicts head loss badly.
    """
    n = int(100.0 / 0.33)
    add = K.emitter_local_loss_equivalent_length(n, 0.15)
    l_eq = 100.0 + add
    share = 100.0 * add / l_eq
    assert 28.0 < share < 34.0


def test_lateral_reports_local_loss_share():
    r = K.lateral_head_loss(0.30, 16.0, 100.0, 303, 0.15)
    assert 28.0 < r["local_loss_share_pct"] < 34.0
    assert r["F"] > 0.33


def test_downhill_lateral_recovers_head():
    up = K.lateral_head_loss(0.30, 16.0, 100.0, 300, 0.15, slope_pct=+1.0)
    down = K.lateral_head_loss(0.30, 16.0, 100.0, 300, 0.15, slope_pct=-1.0)
    assert down["total_dh_m"] < up["total_dh_m"]
    assert abs((up["total_dh_m"] - down["total_dh_m"]) - 2.0) < 1e-6


# ---------------------------------------------------------------------------
# Emitter hydraulics
# ---------------------------------------------------------------------------

def test_emitter_exponent_fit_roundtrip():
    k_true, x_true = 0.6, 0.5
    h1, h2 = 10.0, 20.0
    q1 = K.emitter_discharge(k_true, x_true, h1)
    q2 = K.emitter_discharge(k_true, x_true, h2)
    k, x = K.fit_emitter_kx(h1, q1, h2, q2)
    assert abs(k - k_true) < 1e-9
    assert abs(x - x_true) < 1e-9


def test_pressure_compensating_emitter_is_flat():
    """x = 0.05: doubling head raises discharge by only about 3.5 percent."""
    q1 = K.emitter_discharge(4.0, 0.05, 10.0)
    q2 = K.emitter_discharge(4.0, 0.05, 20.0)
    assert (q2 / q1 - 1.0) < 0.05


def test_non_compensating_emitter_is_sensitive():
    """x = 0.5: doubling head raises discharge by 41 percent."""
    q1 = K.emitter_discharge(0.6, 0.5, 10.0)
    q2 = K.emitter_discharge(0.6, 0.5, 20.0)
    assert abs((q2 / q1) - math.sqrt(2.0)) < 1e-9


# ---------------------------------------------------------------------------
# Emission uniformity
# ---------------------------------------------------------------------------

def test_eu_perfect_case():
    """CV = 0, q_min = q_avg -> EU = 100 percent."""
    assert abs(K.emission_uniformity(0.0, 1, 4.0, 4.0) - 100.0) < 1e-9


def test_eu_hand_calculation():
    """
    CV = 0.05, n = 1, q_min/q_avg = 0.95
      EU = 100 * (1 - 1.27*0.05) * 0.95 = 100 * 0.9365 * 0.95 = 88.97
    """
    assert abs(K.emission_uniformity(0.05, 1, 0.95, 1.0) - 88.97) < 0.02


def test_more_emitters_per_plant_raises_eu():
    """Averaging over more emitters suppresses manufacturing variation."""
    one = K.emission_uniformity(0.10, 1, 0.95, 1.0)
    four = K.emission_uniformity(0.10, 4, 0.95, 1.0)
    assert four > one


def test_cv_classification_bands():
    assert K.cv_class(0.03) == "excellent"
    assert K.cv_class(0.06) == "average"
    assert K.cv_class(0.10) == "marginal"
    assert K.cv_class(0.20) == "unacceptable"


def test_allowable_head_variation_larger_for_pc_emitter():
    non_pc = K.allowable_head_variation(10.0, 0.5, 90.0, 0.05, 1)
    pc = K.allowable_head_variation(10.0, 0.02, 90.0, 0.05, 1)
    assert pc > non_pc


# ---------------------------------------------------------------------------
# Wetted fraction
# ---------------------------------------------------------------------------

def test_wetted_fraction_merged_bulbs():
    """
    Se < Dw: overlapping bulbs, union of a row of circles.

    Hand calculation, Dw = 1.0, Se = 0.4, Sl = 3.0, R = 0.5:
        A_overlap = 2(0.25)acos(0.4) - 0.2*sqrt(1 - 0.16)
                  = 0.579640 - 0.183303 = 0.396337
        strip     = (pi*0.25 - 0.396337) / 0.4 = 0.389061 / 0.4 = 0.972653
        Pw        = 0.972653 / 3 = 0.324218
    """
    pw = K.wetted_fraction(1.0, 0.4, 3.0)
    assert abs(pw - 0.324218) < 1e-5


def test_wetted_fraction_has_no_step_at_the_merge_point():
    """
    Regression, finding 0.4.0-B5.

    The old model switched from a disc row (Se >= Dw) to a full strip of
    width Dw (Se < Dw). The two branches differ by 4/pi, so crossing the
    merge point moved Pw by 21 per cent in one step: at Dw = 0.60, Sl = 2.00
    an emitter spacing of 0.59 m gave Pw = 30.0 % and 0.60 m gave 23.6 %.
    One standard dripline step changed the stored water, the maximum interval
    and the emitter count by a fifth, and at Dw = 0.50 / Sl = 2.50 it moved
    the design across the report's 20 per cent acceptance band.
    """
    below = K.wetted_fraction(0.60, 0.599, 2.0)
    at = K.wetted_fraction(0.60, 0.600, 2.0)
    above = K.wetted_fraction(0.60, 0.601, 2.0)
    assert abs(below - at) < 1e-3, "step on the merged side of the crossover"
    assert abs(at - above) < 1e-3, "step on the separated side of the crossover"
    # and it must stay monotone decreasing in spacing across the whole range
    spacings = [0.10, 0.20, 0.30, 0.40, 0.50, 0.59, 0.60, 0.70, 1.00]
    pws = [K.wetted_fraction(0.60, s, 2.0) for s in spacings]
    assert all(a >= b for a, b in zip(pws, pws[1:])), pws


def test_wetted_fraction_tends_to_full_strip_at_tight_spacing():
    """As Se -> 0 the bulbs merge completely and the strip approaches Dw."""
    assert abs(K.wetted_fraction(0.60, 0.01, 2.0) - 0.60 / 2.0) < 5e-3


def test_wetted_fraction_separated_bulbs_is_smaller():
    merged = K.wetted_fraction(1.0, 0.4, 3.0)
    separated = K.wetted_fraction(1.0, 2.0, 3.0)
    assert separated < merged


def test_wetted_fraction_bounded():
    assert K.wetted_fraction(5.0, 0.2, 1.0) <= 1.0


def test_two_laterals_per_row_double_pw():
    one = K.wetted_fraction(1.0, 0.4, 4.0, 1)
    two = K.wetted_fraction(1.0, 0.4, 4.0, 2)
    assert abs(two - 2.0 * one) < 1e-9


# ---------------------------------------------------------------------------
# Soil water, leaching, depths
# ---------------------------------------------------------------------------

def test_raw_includes_wetted_fraction():
    """
    This is the drip-specific correction. A sprinkler kernel would return
    the Pw = 1.0 value and overestimate the interval.
    """
    full = K.readily_available_water(300, 150, 0.6, 0.4, 1.0)
    drip = K.readily_available_water(300, 150, 0.6, 0.4, 0.4)
    assert abs(drip - 0.4 * full) < 1e-9


def test_leaching_requirement_rhoades():
    """ECw = 2.0, max (zero-yield) ECe = 5.0 -> LR = 2/(2*5) = 0.20."""
    assert abs(K.leaching_requirement(2.0, 5.0) - 0.20) < 1e-9


def test_leaching_ignored_below_threshold():
    """LR <= 0.1 is absorbed by application inefficiency; depth unchanged."""
    a = K.gross_depth(20.0, 0.90, 0.05)
    b = K.gross_depth(20.0, 0.90, 0.0)
    assert abs(a - b) < 1e-9


def test_leaching_inflates_depth_above_threshold():
    base = K.gross_depth(20.0, 0.90, 0.0)
    with_lr = K.gross_depth(20.0, 0.90, 0.20)
    assert with_lr > base
    assert abs(with_lr - 20.0 / (0.90 * 0.80)) < 1e-9


# ---------------------------------------------------------------------------
# FAO-56 ET0
# ---------------------------------------------------------------------------

def test_et0_is_positive_and_plausible():
    """
    Hot dry summer day: ET0 must land in a physically plausible band.
    This is a range check, not a validation against a published example.
    """
    et0 = K.et0_penman_monteith(38.0, 22.0, 35.0, 2.0, 20.0, altitude_m=20.0)
    assert 5.0 < et0 < 14.0


def test_et0_rises_with_radiation():
    low = K.et0_penman_monteith(30, 18, 50, 2.0, 10.0)
    high = K.et0_penman_monteith(30, 18, 50, 2.0, 22.0)
    assert high > low


def test_et0_rises_with_wind_in_dry_air():
    calm = K.et0_penman_monteith(35, 20, 30, 0.5, 18.0)
    windy = K.et0_penman_monteith(35, 20, 30, 4.0, 18.0)
    assert windy > calm


def test_kr_caps_at_one():
    assert K.ground_cover_reduction_factor(0.95) == 1.0
    assert abs(K.ground_cover_reduction_factor(0.34) - 0.4) < 1e-9


def test_etc_localised_reduces_young_orchard_demand():
    """30 percent ground cover: demand is 0.35 of the full-canopy value."""
    kr = K.ground_cover_reduction_factor(0.30)
    full = K.etc_localised(6.0, 0.9, 1.0)
    young = K.etc_localised(6.0, 0.9, kr)
    assert young < 0.4 * full


# ---------------------------------------------------------------------------
# Operational design
# ---------------------------------------------------------------------------

def test_application_rate_hand_calculation():
    """q = 2.0 L/h, Se = 0.5 m, Sl = 2.0 m -> Ia = 2.0 mm/h."""
    assert abs(K.application_rate(2.0, 0.5, 2.0) - 2.0) < 1e-9


def test_set_time():
    assert abs(K.set_time(8.0, 2.0) - 4.0) < 1e-9


def test_shifts_round_up():
    assert K.number_of_shifts(50.0, 120.0) == 3
    assert K.number_of_shifts(50.0, 50.0) == 1


def test_schedule_infeasible_is_detected():
    r = K.operating_hours_check(shifts=8, set_time_h=5.0, interval_d=1.0, max_hours_per_day=20.0)
    assert not r["feasible"]
    assert r["utilisation_pct"] > 100.0


# ---------------------------------------------------------------------------
# Flushing
# ---------------------------------------------------------------------------

def test_flushing_velocity_check():
    ok = K.flushing_velocity_check(16.0, 0.30)
    assert ok["adequate"]
    poor = K.flushing_velocity_check(16.0, 0.10)
    assert not poor["adequate"]


# ---------------------------------------------------------------------------
# Water quality and filtration
# ---------------------------------------------------------------------------

def test_clogging_hazard_worst_governs():
    hz = K.clogging_hazard({"suspended_solids_mg_l": 10.0, "iron_mg_l": 3.0})
    assert hz["per_parameter"]["suspended_solids_mg_l"]["class"] == "slight"
    assert hz["per_parameter"]["iron_mg_l"]["class"] == "severe"
    assert hz["overall"] == "severe"


def test_clean_water_is_slight():
    hz = K.clogging_hazard({"suspended_solids_mg_l": 10.0, "ph": 6.8,
                            "iron_mg_l": 0.05, "bacterial_population_per_ml": 500})
    assert hz["overall"] == "slight"


def test_filtration_mesh_from_passage():
    """0.7 mm passage / 7 = 100 micron -> mesh about 160."""
    r = K.required_filtration_mesh(0.7, 7.0)
    assert abs(r["aperture_micron"] - 100.0) < 1e-6
    assert 150 <= r["mesh"] <= 170


def test_surface_water_requires_media_filter():
    rec = K.recommend_filtration("Nile canal", "moderate", 0.7)
    assert any("Media" in t for t in rec["train"])


def test_well_water_gets_hydrocyclone():
    rec = K.recommend_filtration("deep well", "slight", 0.7)
    assert any("Hydrocyclone" in t for t in rec["train"])


def test_chlorination_triggered_by_bacteria():
    hz = K.clogging_hazard({"bacterial_population_per_ml": 60000})
    actions = K.chemical_maintenance_schedule(hz)
    assert any(a["treatment"] == "Chlorination" for a in actions)


def test_acid_triggered_by_high_ph():
    hz = K.clogging_hazard({"ph": 8.4})
    actions = K.chemical_maintenance_schedule(hz)
    assert any(a["treatment"] == "Acid injection" for a in actions)


def test_flushing_always_scheduled():
    hz = K.clogging_hazard({"ph": 6.5})
    actions = K.chemical_maintenance_schedule(hz)
    assert any(a["treatment"] == "Line flushing" for a in actions)


# ---------------------------------------------------------------------------
# Pump
# ---------------------------------------------------------------------------

def test_tdh_includes_filter_differential():
    without = K.total_dynamic_head(10, 10, 2, 2, 3, 0.0, 0.0)["tdh_m"]
    with_filter = K.total_dynamic_head(10, 10, 2, 2, 3, 3.0, 4.0)["tdh_m"]
    assert abs((with_filter - without) - 7.0) < 1e-9


def test_pump_power_hand_calculation():
    """
    Q = 50 m3/h, TDH = 40 m, eta = 0.70
      Phyd  = (50/3600)*40*1000*9.81/1000 = 5.45 kW
      Pbrake= 5.45/0.70                   = 7.79 kW
    """
    r = K.pump_power(50.0, 40.0, 0.70)
    assert abs(r["hydraulic_kw"] - 5.45) < 0.02
    assert abs(r["brake_kw"] - 7.79) < 0.03
    assert r["motor_rating_kw"] >= r["brake_kw"]


def test_motor_rating_has_margin():
    r = K.pump_power(50.0, 40.0, 0.70)
    assert r["motor_rating_kw"] >= 1.15 * r["brake_kw"] - 1e-6


# ---------------------------------------------------------------------------
# Fertigation
# ---------------------------------------------------------------------------

def test_fertigation_injection_rate():
    """
    50 kg/ha over 10 ha = 500 kg. Stock at 0.4 kg/L -> 1250 L over 2 h
    -> 625 L/h.
    """
    r = K.fertigation_injection_rate(50.0, 10.0, 0.4, 2.0)
    assert abs(r["stock_volume_l"] - 1250.0) < 1e-6
    assert abs(r["injection_rate_lph"] - 625.0) < 1e-6


# ---------------------------------------------------------------------------
# Pipe selection
# ---------------------------------------------------------------------------

def _catalogue():
    return [
        K.PipeOption(50, 44.0, "PE", 6),
        K.PipeOption(63, 55.4, "PE", 6),
        K.PipeOption(75, 66.0, "PE", 6),
        K.PipeOption(90, 79.2, "PE", 6),
        K.PipeOption(110, 96.8, "PE", 6),
    ]


def test_pipe_selection_respects_velocity_cap():
    r = K.select_pipe_diameter(40.0, 200.0, _catalogue(), allowable_dh_m=5.0, n_outlets=10)
    assert r["satisfied"]
    assert r["hydraulics"]["velocity_ms"] <= 2.0


def test_pipe_selection_picks_smallest_that_works():
    cat = _catalogue()
    r = K.select_pipe_diameter(10.0, 100.0, cat, allowable_dh_m=10.0, n_outlets=10)
    assert r["satisfied"]
    smaller = [p for p in cat if p.internal_mm < r["selected"].internal_mm]
    for p in smaller:
        h = K.manifold_head_loss(10.0, p.internal_mm, 100.0, 10)
        assert h["velocity_ms"] > 2.0 or abs(h["total_dh_m"]) > 10.0


def test_pipe_selection_warns_when_impossible():
    r = K.select_pipe_diameter(400.0, 500.0, _catalogue(), allowable_dh_m=1.0, n_outlets=10)
    assert not r["satisfied"]
    assert r["warning"] is not None


# ---------------------------------------------------------------------------
# Unit conversions
# ---------------------------------------------------------------------------

def test_pressure_conversions():
    assert abs(K.bar_to_m(1.0) - 10.1972) < 1e-4
    assert abs(K.kpa_to_m(100.0) - 10.1972) < 1e-3
    assert abs(K.m_to_kpa(K.kpa_to_m(250.0)) - 250.0) < 1e-6


def test_viscosity_falls_with_temperature():
    assert K.kinematic_viscosity(35.0) < K.kinematic_viscosity(15.0)


# ---------------------------------------------------------------------------
# Regression tests for the defects found by validation/edge_cases.py
# ---------------------------------------------------------------------------

def test_downhill_lateral_uniformity_never_exceeds_100():
    """
    BUG (edge-case probe): on a falling lateral the far end has the HIGHEST
    head, so the minimum discharge is at the inlet. Feeding the end discharge
    in as q_min returned EU = 118 % and a green tick on an over-pressured
    design.
    """
    res = K.lateral_head_loss(0.30, 13.6, 100.0, 300, 0.15, slope_pct=-8.0)
    u = K.lateral_uniformity(0.632, 0.5, 10.0, res["hf_m"], -8.0, 100.0, 0.05)
    assert u["eu_pct"] <= 100.0
    assert u["q_end_lph"] > u["q_inlet_lph"]


def test_uphill_lateral_minimum_is_at_far_end():
    res = K.lateral_head_loss(0.30, 13.6, 80.0, 240, 0.15, slope_pct=+1.0)
    u = K.lateral_uniformity(0.632, 0.5, 12.0, res["hf_m"], +1.0, 80.0, 0.05)
    assert u["min_at"] == "far end"
    assert u["q_end_lph"] < u["q_inlet_lph"]
    assert 0.0 <= u["eu_pct"] <= 100.0


def test_uniformity_flags_negative_pressure():
    u = K.lateral_uniformity(0.632, 0.5, 5.0, 9.0, 0.0, 80.0, 0.05)
    assert u["negative_pressure"]
    assert u["q_end_lph"] == 0.0


def test_uniformity_finds_the_interior_minimum():
    """
    BUG found while plotting the head profile: on a steeply falling lateral
    friction is front-loaded and the elevation term is linear, so the head dips
    early and then recovers. The true minimum is INSIDE the line. A two-point
    end check reported the inlet as the minimum and overstated uniformity.

    Hand check for h=15, hf=8, slope=-15 %, L=80 m:
      head(r) = 15 - 8*(1-(1-r)^3) + 12r
      d/dr = -24(1-r)^2 + 12 = 0  ->  (1-r)^2 = 0.5  ->  r = 0.293
      head(0.293) = 13.34 m, against 15.00 at the inlet and 19.00 at the end.
    """
    u = K.lateral_uniformity(1.265, 0.5, 15.0, 8.0, -15.0, 80.0, 0.04, n_points=201)
    assert u["min_is_interior"]
    assert abs(u["distance_of_min_m"] - 0.293 * 80.0) < 1.0
    assert abs(u["h_min_m"] - 13.34) < 0.05
    assert u["h_min_m"] < u["h_inlet_m"] and u["h_min_m"] < u["h_end_m"]
    # and the naive two-end calculation would have overstated uniformity
    q_ends_min = min(u["q_inlet_lph"], u["q_end_lph"])
    assert u["q_min_lph"] < q_ends_min


def test_emission_uniformity_is_bounded():
    assert K.emission_uniformity(0.90, 1, 1.0, 1.0) == 0.0        # would go negative
    assert K.emission_uniformity(0.0, 1, 2.0, 1.0) == 100.0       # would exceed 100


def test_allowable_head_variation_is_continuous_in_x():
    """
    BUG: a hard branch at x <= 0.02 made this jump from 20 % of the head to
    50 % between x = 0.02 and x = 0.03.
    """
    values = [K.allowable_head_variation(15.0, x, 90.0, 0.04, 1)
              for x in (0.0, 0.01, 0.02, 0.03, 0.05)]
    assert max(values) - min(values) < 1e-9        # all at the 50 % cap, no jump
    # and it must still fall as the emitter becomes pressure sensitive
    assert K.allowable_head_variation(15.0, 0.5, 90.0, 0.04, 1) < values[0]


def test_zero_source_discharge_raises():
    """BUG: returned 1 shift, implying the field runs on no water at all."""
    import pytest
    with pytest.raises(ValueError):
        K.number_of_shifts(0.0, 100.0)


def test_empty_catalogue_raises():
    """BUG: returned selected=None and callers raised AttributeError later."""
    import pytest
    with pytest.raises(ValueError):
        K.select_pipe_diameter(10.0, 100.0, [], 5.0, 10)


def test_zero_pump_efficiency_raises():
    import pytest
    with pytest.raises(ValueError):
        K.pump_power(50.0, 40.0, 0.0)
    with pytest.raises(ValueError):
        K.pump_power(50.0, 40.0, 0.7, 0.0)


def test_lateral_velocity_guard_present():
    """WEAK: laterals had no velocity ceiling; a 600 m lateral hit 9 m/s."""
    ok = K.lateral_head_loss(0.40, 13.6, 50.0, 100, 0.15)
    bad = K.lateral_head_loss(4.80, 13.6, 600.0, 1200, 0.15)
    assert ok["velocity_ok"]
    assert not bad["velocity_ok"]
    assert bad["velocity_ms"] > K.LATERAL_V_MAX_MS


def test_acidic_water_raises_a_corrosion_note():
    """BUG: pH 4.5 reported only as 'slight' clogging hazard."""
    hz = K.clogging_hazard({"ph": 4.5})
    assert hz["per_parameter"]["ph"]["class"] == "slight"
    assert hz["corrosion_note"] is not None
    assert "pH" in hz["corrosion_note"]


def test_normal_ph_has_no_corrosion_note():
    assert K.clogging_hazard({"ph": 7.6})["corrosion_note"] is None


def test_leaching_verdict_escalates():
    """WEAK: the 0.90 cap was applied silently."""
    assert K.leaching_verdict(0.0)[0] == "none"
    assert K.leaching_verdict(0.05)[0] == "absorbed"
    assert K.leaching_verdict(0.25)[0] == "applied"
    assert K.leaching_verdict(0.70)[0] == "severe"
    # onion: zero-yield ECe 7.4 dS/m (FAO-29 Table 4); ECw 20 is far beyond it
    assert K.leaching_verdict(K.leaching_requirement(20.0, 7.4))[0] == "unsuitable"


def test_safe_filename():
    """BUG: slashes and colons reached the download filename."""
    assert K.safe_filename("Project / East Delta") == "Project_-_East_Delta"
    assert ":" not in K.safe_filename("مشروع: الشرقية*2026")
    assert "*" not in K.safe_filename("مشروع: الشرقية*2026")
    assert K.safe_filename("") == "project"
    assert K.safe_filename("   ") == "project"
    assert len(K.safe_filename("x" * 500)) == 80


def test_pipe_option_roughness_by_material():
    assert K.PipeOption(110, 96.8, "PVC", 6).roughness_mm == K.ROUGHNESS_MM["PVC"]
    assert K.PipeOption(110, 96.8, "GI", 6).roughness_mm > K.ROUGHNESS_MM["PE"]


def test_wetting_verdict_bands():
    """WEAK: the Pw clamp at 1.0 used to be silent."""
    assert K.wetting_verdict(0.0)[0] == "none"
    assert K.wetting_verdict(0.10)[0] == "low"
    assert K.wetting_verdict(0.50)[0] == "ok"
    assert K.wetting_verdict(0.92)[0] == "high"
    assert K.wetting_verdict(1.0)[0] == "saturated"


def test_zero_wetted_fraction_raises():
    """WEAK: Pw = 0 used to give RAW = 0 and an interval of 0 days."""
    import pytest
    with pytest.raises(ValueError):
        K.readily_available_water(180, 80, 0.5, 0.35, 0.0)


def test_head_variation_check_catches_over_pressure():
    """
    BUG found by the live retest on Windows: `dh <= allowable` passes
    trivially when dh is negative. A downhill design with a 3.65 m net
    pressure GAIN collected green ticks on both the lateral and the subunit
    check while running well above design head.
    """
    gain = K.head_variation_check(-3.649, 0.833)
    assert not gain["within"]
    assert gain["direction"] == "gain"
    assert gain["over_pressure"]

    loss = K.head_variation_check(0.500, 0.833)
    assert loss["within"] and loss["direction"] == "loss" and not loss["over_pressure"]

    small_gain = K.head_variation_check(-0.400, 0.833)
    assert small_gain["within"] and small_gain["direction"] == "gain"
    assert not small_gain["over_pressure"]


def test_head_variation_check_is_symmetric():
    for allowable in (0.5, 2.0, 7.5):
        for magnitude in (0.1, 1.0, 3.0, 10.0):
            assert (K.head_variation_check(magnitude, allowable)["within"]
                    == K.head_variation_check(-magnitude, allowable)["within"])


# ---------------------------------------------------------------------------
# Lateral head profile (drives the hydraulic-profile chart)
# ---------------------------------------------------------------------------

def test_profile_endpoints_match_the_lumped_result():
    prof = K.lateral_head_profile(15.0, 6.0, 0.0, 80.0, n_points=41)
    assert abs(prof[0]["head_m"] - 15.0) < 1e-9
    assert abs(prof[-1]["head_m"] - (15.0 - 6.0)) < 1e-9
    assert abs(prof[-1]["distance_m"] - 80.0) < 1e-9


def test_profile_friction_is_front_loaded():
    """
    phi(r) = 1 - (1-r)^3 for m = 2: at the half-way point 87.5 % of the total
    friction is already spent. A linear profile would say 50 %.
    """
    prof = K.lateral_head_profile(15.0, 8.0, 0.0, 100.0, n_points=3)
    mid = prof[1]
    assert abs(mid["friction_m"] / 8.0 - 0.875) < 1e-9


def test_profile_is_monotonic_on_a_level_lateral():
    prof = K.lateral_head_profile(15.0, 6.0, 0.0, 80.0, n_points=30)
    heads = [p["head_m"] for p in prof]
    assert all(b <= a + 1e-12 for a, b in zip(heads, heads[1:]))


def test_profile_recovers_head_downhill():
    prof = K.lateral_head_profile(15.0, 8.0, -15.0, 80.0, n_points=30)
    assert prof[-1]["head_m"] > prof[0]["head_m"]
    # and the minimum is somewhere in the middle, not at either end
    heads = [p["head_m"] for p in prof]
    assert min(heads) < min(heads[0], heads[-1])


def test_profile_uphill_worst_point_is_the_far_end():
    prof = K.lateral_head_profile(15.0, 4.0, +2.0, 80.0, n_points=30)
    heads = [p["head_m"] for p in prof]
    assert heads[-1] == min(heads)


# ---------------------------------------------------------------------------
# v0.4.0 — regressions from the numeric-comparison audit
#
# Every test below pins a defect that the 83 tests of v0.3.1 all passed with.
# The family is the same in each case: a comparison that reads as a safety
# check but cannot fail in the situation it was written for.
# ---------------------------------------------------------------------------

def test_head_spread_equals_endpoint_difference_on_a_level_run():
    """
    Sanity anchor. On a level run the head falls monotonically, so the true
    spread and the endpoint difference agree — which is exactly why the
    endpoint form survived so long without being noticed.
    """
    sp = K.head_spread(2.679, 0.0, 100.0)
    assert abs(sp["spread_m"] - 2.679) < 1e-6
    assert abs(sp["endpoint_dh_m"] - 2.679) < 1e-6
    assert not sp["min_is_interior"]


def test_head_spread_equals_endpoint_difference_uphill():
    sp = K.head_spread(2.679, +2.0, 100.0)
    assert abs(sp["spread_m"] - sp["endpoint_dh_m"]) < 1e-6
    assert not sp["min_is_interior"]


def test_head_spread_catches_the_interior_trough_downhill():
    """
    Regression, finding 0.4.0-B1 — the most serious defect found to date.

    100 m lateral, friction 2.679 m, slope -2.5 %:
        endpoint hf + dz = +0.179 m  -> 26 % of a 0.685 m allowance, "fine"
        true spread      =  1.109 m  -> 162 % of the allowance, REJECT
    The acceptance check that gates the entire hydraulic design was understated
    by a factor of 6.2. v0.3.0 fixed exactly this for the UNIFORMITY figure by
    scanning the profile, and left the ACCEPTANCE check on the two endpoints.
    """
    sp = K.head_spread(2.679, -2.5, 100.0)
    assert abs(sp["endpoint_dh_m"] - 0.179) < 1e-3
    assert abs(sp["spread_m"] - 1.109) < 5e-3
    assert sp["min_is_interior"]
    assert 40.0 < sp["distance_of_min_m"] < 50.0
    # the endpoint form would have passed a 0.685 m allowance; the spread must not
    assert abs(sp["endpoint_dh_m"]) <= 0.685
    assert sp["spread_m"] > 0.685


def test_head_variation_check_takes_the_verdict_on_the_spread():
    endpoint = K.head_variation_check(0.179, 0.685)
    spread = K.head_variation_check(0.179, 0.685, spread_m=1.109)
    assert endpoint["within"] is True          # the old, wrong verdict
    assert spread["within"] is False           # the corrected one
    assert spread["spread_governs"] is True
    assert spread["direction"] == "loss"       # direction still from the endpoints
    assert abs(spread["endpoint_magnitude_m"] - 0.179) < 1e-9


def test_head_variation_check_rejects_a_nan():
    """`m > a` is False for a NaN, so a naive guard ACCEPTS one."""
    assert K.head_variation_check(float("nan"), 1.0)["within"] is False
    assert K.head_variation_check(0.1, 1.0, spread_m=float("nan"))["within"] is False


def test_lateral_head_loss_reports_the_spread():
    res = K.lateral_head_loss(1.2, 13.6, 100.0, 200, 0.15, slope_pct=-2.5)
    assert res["spread_m"] > abs(res["total_dh_m"])
    assert res["spread_min_is_interior"] is True


def test_manifold_head_loss_reports_the_spread():
    """
    Regression, finding 0.4.0-B1(c). The manifold is a multi-outlet run with
    the same front-loaded friction profile as a lateral, and was judged on
    hf + dz alone.
    """
    res = K.manifold_head_loss(16.0, 55.4, 120.0, 20, slope_pct=-2.5)
    assert abs(res["total_dh_m"]) < 0.7
    assert res["spread_m"] > 1.1
    # the point of the test: the spread is what matters and it is far larger
    # than the end-to-end difference the old check was taken on
    assert res["spread_m"] > 2.0 * abs(res["total_dh_m"])
    assert res["spread_min_is_interior"] is True


def test_subunit_spread_does_not_cancel_across_lateral_and_manifold():
    """
    Regression, finding 0.4.0-B2.

    The subunit variation was the ALGEBRAIC sum of the lateral and manifold
    endpoint differences, so a downhill manifold cancelled a lateral loss:
    +0.600 + (-0.503) = +0.097 m, reported as 1 % of operating head and given
    a green tick. The emitters actually span the sum of the two RANGES, which
    for that case is an order of magnitude larger.
    """
    lat = K.head_spread(0.600, 0.0, 100.0)["spread_m"]
    man = K.head_spread(2.497, -2.5, 120.0)["spread_m"]
    algebraic = 0.600 + (-0.503)
    assert abs(algebraic - 0.097) < 1e-3
    assert lat + man > 1.8
    assert lat + man > 18.0 * abs(algebraic)


def test_pipe_selector_fallback_returns_the_best_not_the_largest():
    """
    Regression, finding 0.4.0-B3.

    With no size satisfying, the old code returned the LARGEST because the
    loop variable happened to end there. It must return the candidate with the
    smallest violation.
    """
    cat = _catalogue()
    sel = K.select_pipe_diameter(16.0, 120.0, cat, allowable_dh_m=0.4,
                                 n_outlets=20, slope_pct=-2.5)
    assert sel["satisfied"] is False
    largest = max(cat, key=lambda p: p.internal_mm)
    assert sel["selected"].internal_mm < largest.internal_mm
    worst = K.manifold_head_loss(16.0, largest.internal_mm, 120.0, 20,
                                 slope_pct=-2.5)["spread_m"]
    assert sel["hydraulics"]["spread_m"] <= worst


def test_schedule_rejects_a_set_longer_than_the_working_day():
    """
    Regression, finding 0.4.0-B4.

    A 25 h set against an 18 h day: the cycle total 25 h fits inside
    18 x 3 = 54 h of cycle capacity, so the old check reported "feasible" at
    46 % utilisation. A set cannot be suspended overnight and resumed.
    """
    s = K.operating_hours_check(shifts=1, set_time_h=25.0, interval_d=3.0,
                                max_hours_per_day=18.0)
    assert s["feasible"] is False
    assert s["set_fits_day"] is False
    assert s["cycle_fits"] is True          # the condition that used to decide
    assert "overnight" in s["reason"]


def test_schedule_rejects_a_zero_set_time():
    """A zero application rate is an input error, not a costless schedule."""
    s = K.operating_hours_check(shifts=1, set_time_h=0.0, interval_d=2.0,
                                max_hours_per_day=18.0)
    assert s["feasible"] is False


def test_schedule_still_accepts_a_normal_case():
    s = K.operating_hours_check(shifts=6, set_time_h=3.65, interval_d=2.0,
                                max_hours_per_day=20.0)
    assert s["feasible"] is True


def test_motor_rating_flags_a_duty_off_the_top_of_the_list():
    """
    Regression, finding 0.4.0-B5.

    227 kW brake needs 261 kW with the 15 % service margin. The old code
    returned 250 kW silently, delivering the pump below its own stated margin
    and understating the bill of quantities.
    """
    p = K.pump_power(1200.0, 50.0, 0.72, 0.90)
    assert p["rating_off_scale"] is True
    assert p["required_rating_kw"] > p["motor_rating_kw"]


def test_motor_rating_normal_case_is_not_flagged():
    p = K.pump_power(40.0, 46.4, 0.72, 0.90)
    assert p["rating_off_scale"] is False
    assert p["motor_rating_kw"] >= p["required_rating_kw"]


def test_pump_power_rejects_a_non_positive_head():
    """
    Regression, finding 0.4.0-W4. A -100 m mainline rise gave TDH -71.6 m,
    brake -10.8 kW, and the motor selector returned its FIRST entry, 0.37 kW,
    which was then priced into the bill of quantities.
    """
    import pytest
    with pytest.raises(ValueError):
        K.pump_power(40.0, -71.59, 0.72, 0.90)
    with pytest.raises(ValueError):
        K.pump_power(0.0, 46.4, 0.72, 0.90)


def test_emission_uniformity_rejects_a_nan_instead_of_scoring_it_perfect():
    """
    Regression, finding 0.4.0-W1. `min(100.0, nan)` returns 100.0, so the
    clamp `max(0.0, min(100.0, eu))` mapped a NaN to a flawless design.
    """
    import pytest
    with pytest.raises(ValueError):
        K.emission_uniformity(float("nan"), 1, 2.0, 2.0)
    with pytest.raises(ValueError):
        K.ground_cover_reduction_factor(float("nan"))


def test_allowable_head_variation_names_an_unattainable_eu_target():
    """
    Regression, finding 0.4.0-W2. CV 0.11 at n = 1 caps EU at 86.0 %, so a
    90 % target cannot be met at ANY pressure. The old code clamped and
    returned 0.000 m, after which the interface advised shortening the lateral
    and increasing the diameter — neither of which can ever close the gap.
    """
    import pytest
    with pytest.raises(ValueError) as exc:
        K.allowable_head_variation(10.0, 0.5, 90.0, 0.11, 1)
    assert "86" in str(exc.value)
    # and a reachable pair still returns a normal number
    assert K.allowable_head_variation(10.0, 0.5, 90.0, 0.03, 1) > 0.0


# ---------------------------------------------------------------------------
# v0.5.0 — the velocity exponent, found by the independent step method
# ---------------------------------------------------------------------------

def test_velocity_exponent_is_measured_not_assumed():
    """
    Regression, finding 0.5.0-B1.

    m is the power of discharge in hf ~ Q^m, and it is a property of the FLOW,
    not of the formula's name. Versions to 0.4.0 passed a hard-coded m = 2 on
    the reasoning that Darcy-Weisbach gives hf proportional to v^2 — true only
    where f has stopped depending on Reynolds number, which a smooth PE
    dripline never reaches.
    """
    smooth_dripline = K.velocity_exponent(1.2e4, 0.007 / 13.6)
    assert 1.70 < smooth_dripline < 1.80, smooth_dripline

    rough_at_high_re = K.velocity_exponent(2.1e5, 3.0 / 100.0)
    assert rough_at_high_re > 1.98, rough_at_high_re

    laminar = K.velocity_exponent(1000.0, 0.0)
    assert abs(laminar - 1.0) < 1e-6

    assert K.velocity_exponent(0.0) == 2.0          # no flow, no crash


def test_measured_exponent_matches_the_segment_by_segment_march():
    """
    Regression, finding 0.5.0-B1, against an INDEPENDENT calculation.

    Marching a lateral segment by segment uses no Christiansen factor at all:
    each segment carries the discharge the emitters downstream of it actually
    take, and is charged its own Darcy-Weisbach loss. The ratio of that total
    to a single whole-length loss at the inlet discharge IS the multi-outlet
    factor, measured rather than tabulated.

    On a 16 mm PE dripline the march gives 0.3651. christiansen_f(n, 2.0)
    gives 0.3358 — 8.0 per cent low. The measured exponent gives 0.3654.
    """
    k, x, h, d_mm, L, n, le = 0.600, 0.500, 15.0, 13.6, 100.0, 200, 0.15

    # -- the independent march, written out here so the test does not depend
    #    on the validation package --
    se = L / n
    q_nom = K.emitter_discharge(k, x, h)
    total = 0.0
    for j in range(n):
        q_seg = q_nom * (n - j) / 1000.0          # m3/h still to be delivered
        total += K.head_loss_darcy(q_seg, d_mm, se + le)["hf_m"]

    base = K.head_loss_darcy(q_nom * n / 1000.0, d_mm, L + n * le)
    f_measured = total / base["hf_m"]

    f_old = K.christiansen_f(n, 2.0)
    m = K.velocity_exponent(base["reynolds"], 0.007 / d_mm)
    f_new = K.christiansen_f(n, m)

    assert abs(f_measured - 0.3651) < 1e-3, f_measured
    assert abs(f_old - f_measured) / f_measured > 0.07, "the old error was ~8 %"
    assert abs(f_new - f_measured) / f_measured < 0.01, (f_new, f_measured)


def test_lateral_head_loss_uses_the_measured_exponent():
    res = K.lateral_head_loss(0.24, 13.6, 100.0, 200, 0.15)
    assert 1.70 < res["velocity_exponent"] < 1.80
    assert abs(res["F"] - K.christiansen_f(200, res["velocity_exponent"])) < 1e-12
    # and the loss is materially larger than the old m = 2 answer
    old = K.head_loss_darcy(0.24, 13.6, 100.0 + 200 * 0.15)["hf_m"] * K.christiansen_f(200, 2.0)
    assert res["hf_m"] > old * 1.07


def test_profile_shape_uses_the_same_exponent_as_the_loss():
    """
    The Christiansen factor and the profile shape phi(r) = 1-(1-r)^(m+1) are
    two faces of the same assumption. If they are allowed to use different
    exponents the head spread stops matching the head loss that produced it.
    """
    res = K.lateral_head_loss(0.24, 13.6, 100.0, 200, 0.15, slope_pct=-2.5)
    m = res["velocity_exponent"]
    direct = K.head_spread(res["hf_m"], -2.5, 100.0, exponent=m)
    assert abs(direct["spread_m"] - res["spread_m"]) < 1e-9
    assert abs(direct["distance_of_min_m"] - res["spread_min_at_m"]) < 1e-9


def test_exponent_mode_reports_both_answers():
    """
    The measured exponent departs from the m = 2 convention that most of the
    literature pairs with Darcy-Weisbach. A silent default would leave a
    reviewer unable to reconcile this program with a textbook, so both
    figures are computed on every call.
    """
    res = K.lateral_head_loss(0.24, 13.6, 100.0, 200, 0.15)
    assert res["exponent_mode"] == "measured"
    assert res["hf_measured_m"] > res["hf_conventional_m"] * 1.07
    assert abs(res["hf_m"] - res["hf_measured_m"]) < 1e-12

    conv = K.lateral_head_loss(0.24, 13.6, 100.0, 200, 0.15,
                               exponent_mode="conventional")
    assert conv["velocity_exponent"] == 2.0
    assert abs(conv["hf_m"] - res["hf_conventional_m"]) < 1e-12
    # the measured value is still reported even when it is not the one used
    assert 1.70 < conv["velocity_exponent_measured"] < 1.80

    import pytest
    with pytest.raises(ValueError):
        K.lateral_head_loss(0.24, 13.6, 100.0, 200, 0.15, exponent_mode="whatever")


def test_christiansen_matches_its_exact_summation_definition():
    """
    External reference: F = (1^m + 2^m + ... + N^m) / N^(m+1), the closed
    definition, against the three-term approximation the program uses.
    """
    for n in (5, 10, 50, 200):
        for m in (1.75, 1.852, 2.0):
            exact = sum(i ** m for i in range(1, n + 1)) / (n ** (m + 1.0))
            assert abs(K.christiansen_f(n, m) - exact) < 2e-4, (n, m)
