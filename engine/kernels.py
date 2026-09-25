"""
IRRI-DRIP — Engineering computation kernels
Water Management Research Institute (WMRI)

Pure functions only. No user-interface code, no global state.
Every function is independently testable and every formula carries its
reference in the docstring.

UNITS (enforced throughout)
--------------------------
length / head .... m
diameter ......... mm at the interface, converted to m internally
discharge ........ L/h for emitters, m3/h for pipes and pumps
pressure ......... m of water column (bar and kPa via convert_pressure)
area ............. ha at the interface, m2 internally
depth ............ mm
time ............. h
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

G = 9.81                 # gravitational acceleration, m/s2
RHO = 1000.0             # water density, kg/m3
NU_20C = 1.004e-6        # kinematic viscosity of water at 20 C, m2/s


# ---------------------------------------------------------------------------
# 0. Unit helpers
# ---------------------------------------------------------------------------

def kpa_to_m(kpa: float) -> float:
    """Convert kPa to metres of water column. 1 kPa = 0.10197 m."""
    return kpa * 0.101972


def bar_to_m(bar: float) -> float:
    """Convert bar to metres of water column. 1 bar = 10.1972 m."""
    return bar * 10.1972


def m_to_kpa(m: float) -> float:
    return m / 0.101972


def _require_finite(name: str, value: float) -> float:
    """
    Reject NaN and infinity at the point of entry.

    Python makes EVERY comparison with NaN False, so a guard written as
    ``if x > limit: reject`` silently ACCEPTS a NaN, and a clamp written as
    ``max(0.0, min(100.0, x))`` returns the BEST possible answer for one:
    min(100.0, nan) keeps 100.0 because ``nan < 100.0`` is False. The emission
    uniformity kernel returned a perfect 100 % for a NaN coefficient of
    variation, and the localisation factor returned 1.0 — no reduction at all.
    Neither is reachable from today's widgets, but both are documented as
    independently testable kernels, and a clamp that turns missing data into a
    flawless result is the wrong failure direction.
    """
    v = float(value)
    if math.isnan(v) or math.isinf(v):
        raise ValueError(f"{name} is not a finite number ({value!r}).")
    return v


def kinematic_viscosity(temp_c: float) -> float:
    """
    Kinematic viscosity of water, m2/s.

    Empirical fit valid roughly 5-40 C. Temperature matters in drip design
    because laterals often run in the transitional Reynolds range where the
    friction factor is viscosity-sensitive; assuming 20 C on a 35 C field day
    biases head loss.
    """
    t = float(temp_c)
    return 1.0e-6 * (1.7745 / (1.0 + 0.0337 * t + 0.000221 * t * t)) * 1.0


# ---------------------------------------------------------------------------
# 1. Reference and crop evapotranspiration — FAO-56
# ---------------------------------------------------------------------------

def saturation_vapour_pressure(t_c: float) -> float:
    """e0(T), kPa. FAO-56 Eq. 11."""
    return 0.6108 * math.exp(17.27 * t_c / (t_c + 237.3))


def slope_vapour_pressure_curve(t_mean_c: float) -> float:
    """Delta, kPa/C. FAO-56 Eq. 13."""
    es = saturation_vapour_pressure(t_mean_c)
    return 4098.0 * es / ((t_mean_c + 237.3) ** 2)


def psychrometric_constant(altitude_m: float) -> float:
    """gamma, kPa/C. FAO-56 Eq. 7 and 8."""
    p = 101.3 * ((293.0 - 0.0065 * altitude_m) / 293.0) ** 5.26
    return 0.000665 * p


def et0_penman_monteith(
    t_max_c: float,
    t_min_c: float,
    rh_mean_pct: float,
    wind_2m_ms: float,
    rn_mj_m2_d: float,
    altitude_m: float = 0.0,
    g_mj_m2_d: float = 0.0,
) -> float:
    """
    Reference evapotranspiration ET0, mm/day.
    FAO-56 Penman-Monteith, Allen et al. (1998), Eq. 6.

    Daily time step, therefore soil heat flux G is normally taken as zero
    and the numerator coefficient is 900.
    """
    t_mean = (t_max_c + t_min_c) / 2.0
    delta = slope_vapour_pressure_curve(t_mean)
    gamma = psychrometric_constant(altitude_m)

    es = (saturation_vapour_pressure(t_max_c) + saturation_vapour_pressure(t_min_c)) / 2.0
    ea = es * rh_mean_pct / 100.0

    num = 0.408 * delta * (rn_mj_m2_d - g_mj_m2_d) + gamma * (900.0 / (t_mean + 273.0)) * wind_2m_ms * (es - ea)
    den = delta + gamma * (1.0 + 0.34 * wind_2m_ms)
    return max(0.0, num / den)


def ground_cover_reduction_factor(ground_cover_fraction: float) -> float:
    """
    Kr — localised-irrigation reduction factor.

    Keller & Bliesner (1990): Kr = GC / 0.85, capped at 1.0.

    This is the first structural departure from sprinkler design. Under drip
    only part of the soil surface is wetted and only part is shaded by the
    canopy, so applying the full FAO-56 Kc to a young orchard overestimates
    the requirement, sometimes by a factor of two.
    """
    gc = max(0.0, min(1.0, _require_finite("Ground cover fraction",
                                          ground_cover_fraction)))
    return min(1.0, gc / 0.85)


def etc_localised(et0_mm_d: float, kc: float, kr: float) -> float:
    """ETc adjusted for localised irrigation, mm/day."""
    return et0_mm_d * kc * kr


# ---------------------------------------------------------------------------
# 2. Soil water and irrigation depth
# ---------------------------------------------------------------------------

def readily_available_water(
    fc_mm_per_m: float,
    wp_mm_per_m: float,
    root_depth_m: float,
    depletion_fraction: float,
    wetted_fraction: float,
) -> float:
    """
    RAW under drip, mm.

    RAW = p * (FC - WP) * Zr * Pw

    Under drip only the wetted volume stores plant-available water, so the
    wetted fraction Pw enters the storage term directly. Omitting it — as a
    sprinkler kernel would — overestimates the interval and under-irrigates
    the crop.
    """
    if wetted_fraction <= 0.0:
        raise ValueError(
            "Wetted fraction must be greater than zero: with no wetted volume there is "
            "no plant-available water and no schedule can be derived.")
    taw = (fc_mm_per_m - wp_mm_per_m) * root_depth_m
    return taw * depletion_fraction * wetted_fraction


def leaching_requirement(ecw_ds_m: float, ece_max_ds_m: float) -> float:
    """
    Leaching requirement LR, fraction — high-frequency (drip) form.

        LR = ECw / (2 * max ECe)          (Rhoades 1974; Keller & Bliesner 1990)

    ``max ECe`` is the soil salinity at which the crop's yield falls to ZERO
    (FAO-29 Table 4, 0 % column) — NOT the threshold at which decline begins.
    v2.0.0 passed the threshold here, which for tomato (threshold 2.5, max 13
    dS/m) and ECw 1.0 gave LR 20 % instead of 3.8 %.

    The high-frequency form is the correct one for drip: the soil stays near
    field capacity so leaching is continuous rather than episodic.
    Returns 0 when either input is non-positive.
    """
    if ecw_ds_m <= 0 or ece_max_ds_m <= 0:
        return 0.0
    return min(LR_CAP, ecw_ds_m / (2.0 * ece_max_ds_m))


def leaching_requirement_fao29(ecw_ds_m: float, ece_threshold_ds_m: float) -> float:
    """
    Leaching requirement LR, fraction — FAO-29 eq. (9), Ayers & Westcot (1985):

        LR = ECw / (5 * ECe - ECw)

    with ECe the crop's threshold (100 % yield) salinity. Used when no
    zero-yield ECe is known for the crop. Water as salty as 5 x ECe cannot be
    leached at all: the LR is then capped (see :func:`leaching_verdict`).
    """
    if ecw_ds_m <= 0 or ece_threshold_ds_m <= 0:
        return 0.0
    den = 5.0 * ece_threshold_ds_m - ecw_ds_m
    if den <= 0:
        return LR_CAP
    return min(LR_CAP, ecw_ds_m / den)


LR_CAP = 0.90
LR_UNSUITABLE = 0.50


def leaching_verdict(lr: float) -> tuple[str, str]:
    """
    Interpret a leaching requirement instead of returning a bare number.

    The kernel clamps LR at 0.90, and a silent clamp was flagged by the
    edge-case probe: a design can be handed a gross depth three times the net
    depth with no indication that the water is simply unsuitable for the crop.
    """
    if lr <= 0.0:
        return "none", "No leaching demand at this water and crop salinity."
    if lr <= 0.10:
        return "absorbed", ("Leaching demand is met by the application inefficiency "
                            "itself; no extra depth is applied.")
    if lr < LR_UNSUITABLE:
        return "applied", ("Gross depth is inflated to satisfy the leaching demand. "
                           "Verify the crop threshold against FAO-29.")
    if lr < LR_CAP:
        return "severe", ("More than half of the applied water is leaving as drainage. "
                          "Reconsider the crop, blend the water, or treat this as a "
                          "salinity-management scheme rather than an irrigation design.")
    return "unsuitable", ("The leaching requirement has hit the 0.90 cap. This water "
                          "cannot sustain this crop. The computed depths are arithmetic, "
                          "not a design.")


def gross_depth(net_depth_mm: float, application_efficiency: float, lr: float = 0.0) -> float:
    """
    Gross application depth, mm.

    When LR <= 0.1 the leaching demand is normally met by the application
    inefficiency itself and no extra water is added. Above 0.1 the depth is
    inflated by 1/(1-LR). This threshold convention follows FAO-29.
    """
    ea = max(1e-6, application_efficiency)
    if lr > 0.1:
        return net_depth_mm / (ea * (1.0 - lr))
    return net_depth_mm / ea


# ---------------------------------------------------------------------------
# 3. Emitter hydraulics and wetting
# ---------------------------------------------------------------------------

def emitter_discharge(k: float, x: float, head_m: float) -> float:
    """
    Emitter discharge, L/h.

        q = k * H^x

    x characterises the emitter and has no counterpart in sprinkler design:
      x ~ 0.5        long-path / orifice, fully pressure-sensitive
      x ~ 0.7-0.8    micro-tube, laminar
      x = 0.0-0.15   pressure-compensating
    """
    if head_m <= 0:
        return 0.0
    return k * (head_m ** x)


def fit_emitter_kx(h1_m: float, q1_lph: float, h2_m: float, q2_lph: float) -> tuple[float, float]:
    """
    Derive (k, x) from two catalogue points by log-log regression through
    two points. Lets a designer use any manufacturer table without the
    manufacturer publishing k and x explicitly.
    """
    if h1_m <= 0 or h2_m <= 0 or q1_lph <= 0 or q2_lph <= 0 or abs(h1_m - h2_m) < 1e-9:
        raise ValueError("Two distinct positive head/discharge pairs are required.")
    x = math.log(q2_lph / q1_lph) / math.log(h2_m / h1_m)
    k = q1_lph / (h1_m ** x)
    return k, x


def wetted_fraction(
    wetted_diameter_m: float,
    emitter_spacing_m: float,
    lateral_spacing_m: float,
    laterals_per_row: int = 1,
) -> float:
    """
    Pw — fraction of the field area wetted, 0-1.

    Line-source treatment: adjacent bulbs along the lateral merge once the
    emitter spacing is smaller than the wetted diameter, producing a wetted
    strip of width Dw.

        Pw = laterals_per_row * min(Dw, overlap-limited width) / lateral_spacing

    Pw drives the storage term, the salinity behaviour and the emitter count.
    It has no analogue in sprinkler design, where the whole surface is wetted.

    The merge is CONTINUOUS, not a switch. The previous form used a bare disc
    row for Se >= Dw and a full strip of width Dw for Se < Dw, and the two
    branches disagree by a factor of 4/pi at the crossover: at Dw = 0.60 m,
    Sl = 2.00 m, moving the emitter spacing from 0.59 m to 0.60 m — one
    standard dripline step — dropped Pw from 30.0 % to 23.6 %, a 21 % jump in
    the stored water, the maximum interval and the emitter count. At
    Dw = 0.50 m, Sl = 2.50 m the same step straddles the report's 20 %
    acceptance band, so the design passed on one side and failed on the other.

    The wetted area per emitter period is now the union of a row of equally
    spaced circles of diameter Dw, computed from the circular-segment overlap
    of adjacent bulbs:

        A_overlap = 2R^2 acos(Se/2R) - (Se/2) sqrt(4R^2 - Se^2)
        strip     = (pi R^2 - A_overlap) / Se,  capped at Dw

    This reduces exactly to the disc row at Se >= Dw (the overlap vanishes)
    and tends to the full strip Dw as Se -> 0, with no step anywhere between.
    """
    if lateral_spacing_m <= 0 or wetted_diameter_m <= 0 or emitter_spacing_m <= 0:
        return 0.0
    r = wetted_diameter_m / 2.0
    if emitter_spacing_m >= wetted_diameter_m:
        # Bulbs do not merge: wetted area is a row of separate discs.
        strip = math.pi * r * r / emitter_spacing_m
    else:
        ratio = min(1.0, emitter_spacing_m / (2.0 * r))
        a_overlap = (2.0 * r * r * math.acos(ratio)
                     - (emitter_spacing_m / 2.0)
                     * math.sqrt(max(0.0, 4.0 * r * r - emitter_spacing_m ** 2)))
        # The pairwise subtraction over-corrects once three bulbs overlap
        # (Se < R); the union can never be wider than the bulb itself.
        strip = min(wetted_diameter_m,
                    (math.pi * r * r - a_overlap) / emitter_spacing_m)
    pw = laterals_per_row * strip / lateral_spacing_m
    return max(0.0, min(1.0, pw))


def wetting_verdict(pw: float) -> tuple[str, str]:
    """
    Interpret the wetted fraction instead of returning a bare clamped number.

    The clamp at 1.0 is correct arithmetic and was also silent: a layout whose
    raw Pw exceeds one is no longer behaving as drip at all, and the kernel
    said nothing about it. Flagged by the edge-case probe.
    """
    if pw <= 0.0:
        return "none", ("Wetted fraction is zero. No water is stored in the root zone and "
                        "no schedule can be built from it. Check the wetted diameter and "
                        "the spacings.")
    if pw < 0.20:
        return "low", ("Below roughly 20 per cent the wetted volume is too small to buffer "
                       "a pump failure or a hot spell, and salts concentrate sharply at the "
                       "bulb edge.")
    if pw <= 0.85:
        return "ok", "Wetted fraction is in the normal design range for drip."
    if pw < 1.0:
        return "high", ("Approaching full-surface wetting. The evaporation advantage that "
                        "justifies drip is largely lost.")
    return "saturated", ("The layout wets the entire surface: adjacent bulbs overlap "
                         "completely. This is no longer localised irrigation, and the "
                         "reported Pw of 100 per cent is a clamp, not a measurement.")


def emission_uniformity(cv_manufacturing: float, emitters_per_plant: int,
                        q_min_lph: float, q_avg_lph: float) -> float:
    """
    Design emission uniformity EU, percent.
    Keller & Karmeli (1974):

        EU = 100 * (1 - 1.27 * CV / sqrt(n)) * (q_min / q_avg)

    This replaces Christiansen's CU. CU describes overlap of sprinkler
    patterns; EU combines manufacturing variation with hydraulic variation,
    which is the governing pair in a drip subunit.
    """
    cv = _require_finite("Manufacturing CV", cv_manufacturing)
    q_min = _require_finite("Minimum emitter discharge", q_min_lph)
    q_avg = _require_finite("Average emitter discharge", q_avg_lph)
    n = max(1, int(emitters_per_plant))
    if q_avg <= 0:
        return 0.0
    eu = 100.0 * (1.0 - 1.27 * cv / math.sqrt(n)) * (q_min / q_avg)
    # Floor at zero and cap at 100: the expression goes negative for very high
    # CV, and a caller that passes q_min > q_avg (a downhill lateral, where the
    # minimum is at the inlet, not the end) would otherwise be handed a
    # physically impossible uniformity above 100 per cent.
    # The finite guards above matter because this clamp is written in the one
    # order that maps a NaN to 100.0 — a perfect score — rather than to zero.
    return max(0.0, min(100.0, eu))


def lateral_uniformity(k: float, x: float, h_inlet_m: float,
                       friction_total_m: float, slope_pct: float, length_m: float,
                       cv: float, emitters_per_plant: int = 1,
                       n_points: int = 41, exponent: float = 2.0) -> dict:
    """
    Emission uniformity of a lateral, evaluated over the WHOLE line.

    Two corrections over a naive calculation, both found by testing:

    1. DIRECTION. On a rising or level lateral the minimum head is at the far
       end. On a falling lateral the elevation gain can exceed friction, so the
       far end is the HIGH-pressure end. Feeding the end discharge in as q_min
       regardless produces a uniformity above 100 per cent and a green tick on
       an over-pressured design.

    2. INTERIOR MINIMUM. Checking only the two ends is still not enough.
       Friction is front-loaded — phi(r) = 1 - (1-r)^3 — while the elevation
       term is linear, so on a steeply falling lateral the head DIPS early and
       then recovers. The true minimum sits inside the line, typically around
       a quarter to a third of the way along. A two-point check misses it and
       overstates uniformity. This was found when the head profile was plotted:
       the chart showed a dip that the numbers had not.

    The profile is therefore scanned end to end, and q_avg is the mean over the
    whole lateral rather than the average of its two ends.
    """
    prof = lateral_head_profile(h_inlet_m, friction_total_m, slope_pct,
                                length_m, n_points, exponent=exponent)
    for pt in prof:
        pt["q_lph"] = emitter_discharge(k, x, max(0.0, pt["head_m"]))

    q_values = [pt["q_lph"] for pt in prof]
    heads = [pt["head_m"] for pt in prof]
    i_min = min(range(len(q_values)), key=lambda i: q_values[i])
    i_max = max(range(len(q_values)), key=lambda i: q_values[i])
    q_min, q_max = q_values[i_min], q_values[i_max]
    q_avg = sum(q_values) / len(q_values)

    r_min = prof[i_min]["relative"]
    if r_min <= 1e-9:
        where = "inlet"
    elif r_min >= 1.0 - 1e-9:
        where = "far end"
    else:
        where = f"{r_min*100:.0f} % along the lateral"

    return {
        "profile": prof,
        "h_inlet_m": h_inlet_m, "h_end_m": prof[-1]["head_m"],
        "h_min_m": min(heads), "h_max_m": max(heads),
        "q_inlet_lph": q_values[0], "q_end_lph": q_values[-1],
        "q_min_lph": q_min, "q_max_lph": q_max, "q_avg_lph": q_avg,
        "eu_pct": emission_uniformity(cv, emitters_per_plant, q_min, q_avg),
        "min_at": where,
        "min_is_interior": 1e-9 < r_min < 1.0 - 1e-9,
        "distance_of_min_m": prof[i_min]["distance_m"],
        "negative_pressure": min(heads) <= 0.0,
    }


def cv_class(cv: float) -> str:
    """
    Manufacturer's coefficient of variation classification.
    ASABE EP405.1 bands for point-source emitters.
    """
    if cv <= 0.05:
        return "excellent"
    if cv <= 0.07:
        return "average"
    if cv <= 0.11:
        return "marginal"
    if cv <= 0.15:
        return "poor"
    return "unacceptable"


def allowable_head_variation(h_nominal_m: float, x: float, eu_target_pct: float,
                             cv: float, emitters_per_plant: int) -> float:
    """
    Allowable head variation within a subunit, m.

    Derived by inverting the Keller & Karmeli expression for the required
    q_min/q_avg ratio and mapping it back through q = k*H^x:

        q_min/q_avg = EU_target / (100 * (1 - 1.27*CV/sqrt(n)))
        H_min/H_avg = (q_min/q_avg)^(1/x)
        dH_allow    = H_avg - H_min

    For a pressure-compensating emitter x tends to zero and the permissible
    variation becomes very large; the function caps it at HALF the operating
    head. (The docstring used to cite "the conventional 20 percent rule" while
    the code capped at 0.5 * h_nominal — a reader trusting the text was off by
    a factor of 2.5. The 50 per cent figure is the one actually applied and is
    the looser, safer bound for a compensating emitter; the 20 per cent rule
    belongs to the SUBUNIT budget, which the caller applies separately.)

    The CV / EU target pair can be mutually unattainable: CV alone caps EU at
    100*(1 - 1.27*CV/sqrt(n)) regardless of pressure. At CV = 0.11 with n = 1
    that ceiling is 86.0 %, so an EU target of 90 % cannot be met at any head.
    The old code clamped the required ratio to 1.0 and returned an allowable
    ΔH of 0.000 m, after which every design failed and the interface advised
    "shorten the lateral, increase the diameter, feed from the middle" — none
    of which can ever help. It now says what is actually wrong.
    """
    cv = _require_finite("Manufacturing CV", cv)
    n = max(1, int(emitters_per_plant))
    denom = 1.0 - 1.27 * cv / math.sqrt(n)
    if denom <= 0:
        raise ValueError(
            f"A manufacturing CV of {cv:.3f} over {n} emitter(s) leaves no "
            "uniformity at all before hydraulics are considered. Select a "
            "better-classified emitter.")
    ratio_q = (eu_target_pct / 100.0) / denom
    if ratio_q > 1.0:
        raise ValueError(
            f"An EU target of {eu_target_pct:.0f} % is unattainable with a "
            f"manufacturing CV of {cv:.3f} over {n} emitter(s): the CV alone "
            f"caps EU at {100.0 * denom:.1f} % at perfectly uniform pressure. "
            "Lower the target or select a better-classified emitter — no "
            "change to the pipe layout can close this gap.")
    ratio_q = min(1.0, max(1e-6, ratio_q))
    # A hard branch at x <= 0.02 used to make this discontinuous: x = 0.02
    # returned 20 per cent of the head and x = 0.03 returned 50 per cent.
    # Clamping the exponent instead keeps the function monotone in x and lets
    # the 50 per cent cap do the limiting for compensating emitters.
    x_eff = max(0.01, float(x))
    ratio_h = ratio_q ** (1.0 / x_eff)
    dh = h_nominal_m * (1.0 - ratio_h)
    return max(0.0, min(dh, 0.5 * h_nominal_m))


# ---------------------------------------------------------------------------
# 4. Pipe hydraulics — Darcy-Weisbach, NOT Hazen-Williams
# ---------------------------------------------------------------------------

def reynolds_number(q_m3h: float, d_mm: float, nu: float = NU_20C) -> float:
    d = d_mm / 1000.0
    if d <= 0:
        return 0.0
    v = velocity(q_m3h, d_mm)
    return v * d / nu


def velocity(q_m3h: float, d_mm: float) -> float:
    """Mean velocity, m/s."""
    d = d_mm / 1000.0
    if d <= 0:
        return 0.0
    area = math.pi * d * d / 4.0
    return (q_m3h / 3600.0) / area


# Absolute roughness, mm. Plastic pipe is hydraulically smooth when new;
# the values below carry a small allowance for ageing and jointing.
ROUGHNESS_MM = {"PE": 0.007, "PVC": 0.007, "STEEL": 0.045, "GI": 0.15, "CONCRETE": 0.3}


def friction_factor(re: float, rel_roughness: float = 0.0) -> tuple[float, str]:
    """
    Darcy friction factor and the regime label that justifies it.

      Re < 2000            laminar         f = 64/Re
      2000 <= Re < 4000    transitional    blended, flagged as uncertain
      Re >= 4000           Swamee-Jain     explicit Colebrook-White approximation

    Swamee-Jain:

        f = 0.25 / [ log10( eps/(3.7 D) + 5.74 / Re^0.9 ) ]^2

    valid for 1e-6 <= eps/D <= 1e-2 and 5e3 <= Re <= 1e8, which covers every
    pipe in a drip system from a 13.6 mm lateral to a 300 mm mainline. It
    reduces to the smooth-pipe curve as eps/D approaches zero, so laterals
    still get the smooth-pipe answer that Blasius gives, while mainlines are
    no longer computed outside the correlation's range.

    WHY NOT HAZEN-WILLIAMS. H-W with C = 150 is calibrated for large diameters
    at high Reynolds numbers. A 16 mm drip lateral carrying a few hundred
    litres per hour runs at Re of order 5e3 to 2e4 — inside the smooth-pipe
    regime where the H-W velocity exponent of 1.852 is simply wrong. Reusing a
    sprinkler kernel unchanged embeds a systematic error in every lateral.

    WHY NOT PLAIN BLASIUS. Blasius (f = 0.316 Re^-0.25) is calibrated only to
    Re = 1e5 and ignores roughness entirely. A 110 mm mainline at 36 m3/h runs
    above Re = 2e5, so every mainline computed with Blasius was extrapolated
    beyond the formula's validity. This was found by the edge-case probe and
    is the reason the kernel now uses Swamee-Jain.
    """
    if re <= 0:
        return 0.0, "no-flow"
    if re < 2000:
        return 64.0 / re, "laminar"
    if re < 4000:
        f_lam = 64.0 / 2000.0
        f_tur = _swamee_jain(4000.0, rel_roughness)
        w = (re - 2000.0) / 2000.0
        return f_lam + w * (f_tur - f_lam), "transitional (uncertain)"
    label = "turbulent (Swamee-Jain)"
    if rel_roughness <= 1e-6:
        label = "turbulent smooth (Swamee-Jain)"
    return _swamee_jain(re, rel_roughness), label


def _swamee_jain(re: float, rel_roughness: float) -> float:
    inner = rel_roughness / 3.7 + 5.74 / (re ** 0.9)
    return 0.25 / (math.log10(inner) ** 2)


def blasius_friction_factor(re: float) -> float:
    """
    Blasius smooth-pipe factor, retained for comparison and for the
    regression tests that check the published value f(1e4) = 0.0316.
    Not used by the design path any more — see friction_factor.
    """
    return 0.316 * (re ** -0.25)


def head_loss_darcy(q_m3h: float, d_mm: float, length_m: float,
                    nu: float = NU_20C, roughness_mm: float = 0.007) -> dict:
    """
    Friction head loss in a plain pipe run, m.

        hf = f * (L/D) * v^2 / (2g)
    """
    d = d_mm / 1000.0
    v = velocity(q_m3h, d_mm)
    re = reynolds_number(q_m3h, d_mm, nu)
    rel = (roughness_mm / d_mm) if d_mm > 0 else 0.0
    f, regime = friction_factor(re, rel)
    hf = f * (length_m / d) * (v * v) / (2.0 * G) if d > 0 else 0.0
    return {"hf_m": hf, "velocity_ms": v, "reynolds": re,
            "friction_factor": f, "regime": regime, "rel_roughness": rel}


EXPONENT_MODE_DEFAULT = "measured"


def resolve_exponent(mode: str, measured: float) -> float:
    """
    Choose the velocity exponent m, and make the choice visible.

    THERE ARE TWO DEFENSIBLE ANSWERS AND THIS PROGRAM REPORTS BOTH.

    "conventional" -> m = 2.0
        What most of the irrigation literature and most software pair with
        Darcy-Weisbach. It is what a reviewer checking this design against a
        textbook will compute. It is exact only where the friction factor has
        stopped depending on Reynolds number.

    "measured"     -> m from :func:`velocity_exponent`
        The exponent that the friction factor THIS PROGRAM USES actually
        implies at the working Reynolds number. On a smooth PE dripline that
        is about 1.75, and it reproduces a segment-by-segment march of the
        same lateral to 0.4 per cent, where m = 2 is 8 per cent low. On a
        rough pipe at high Reynolds number it returns to 2.00 on its own.

    The two differ by about 8.5 per cent of the lateral friction loss on a
    typical dripline. The default is "measured" because it is the answer
    consistent with the program's own friction model — using Swamee-Jain for
    f and then an exponent that assumes f is constant is internally
    contradictory. But the conventional figure is computed and returned
    alongside it on every call, because a designer whose work will be checked
    against a textbook needs to see both numbers and the reason they differ,
    not a silent default.
    """
    if mode == "conventional":
        return 2.0
    if mode == "measured":
        return measured
    raise ValueError(
        f"Unknown exponent mode {mode!r}. Use 'measured' or 'conventional'.")


def velocity_exponent(re: float, rel_roughness: float = 0.0,
                     delta: float = 0.01) -> float:
    """
    m = d(ln hf) / d(ln Q) for the friction factor actually in use.

    Head loss is hf = f(Re) * (L/D) * v^2/2g with Re proportional to Q, so

        m = 2 + d(ln f) / d(ln Re)

    evaluated numerically on the same Swamee-Jain factor the rest of the
    module uses. No coefficient is invented and no regime is named: whatever
    f does, m follows it.

    WHY THIS REPLACED A HARD-CODED 2.0
    ----------------------------------
    Versions up to 0.4.0 passed m = 2 everywhere, on the reasoning that
    Darcy-Weisbach gives hf proportional to v^2. That is true only when f is
    constant. On a 16 mm PE dripline the inlet Reynolds number is of order
    1.2e4 to 1.7e4 — smooth turbulent, where f falls roughly as Re^-0.25 —
    and the measured exponent is 1.71 to 1.78, not 2.

    The consequence was not small. Marching the same lateral segment by
    segment with no F factor at all (validation/step_method.py) gives an
    effective F of 0.365, against christiansen_f(n, 2.0) = 0.336: the
    lateral friction loss, the head spread, the emission uniformity, the
    total dynamic head and the seasonal energy were all understated by about
    8.5 per cent. christiansen_f(n, 1.75) = 0.366 matches the march to 0.4
    per cent, and on a deliberately roughened control pipe — where f really
    does stop depending on Re — the measured exponent returns to 1.99 and
    the effective F to 0.334, which is the m = 2 answer. The exponent is a
    property of the flow, not of the formula's name.

    Clamped to [1.0, 2.0]: below laminar and above fully rough are not
    physical for this term.
    """
    if re <= 0:
        return 2.0
    f1, _ = friction_factor(re, rel_roughness)
    f2, _ = friction_factor(re * (1.0 + delta), rel_roughness)
    if f1 <= 0 or f2 <= 0:
        return 2.0
    dlnf = math.log(f2 / f1) / math.log(1.0 + delta)
    return max(1.0, min(2.0, 2.0 + dlnf))


def christiansen_f(n_outlets: int, exponent: float = 2.0) -> float:
    """
    Christiansen multi-outlet reduction factor F.

        F = 1/(m+1) + 1/(2N) + sqrt(m-1)/(6N^2)

    m is the velocity exponent of the friction formula — the power of
    discharge in hf ~ Q^m. It is NOT a property of the formula's name:

        Hazen-Williams                       m = 1.852 (fixed by the formula)
        Darcy-Weisbach, fully rough          m = 2.00  (f independent of Re)
        Darcy-Weisbach, smooth turbulent     m ~ 1.75  (f ~ Re^-0.25)
        Darcy-Weisbach, laminar              m = 1.00  (f = 64/Re)

    Using the Hazen-Williams value of 1.852 with a Darcy-Weisbach head loss
    is a common and silent error. So is assuming that "Darcy-Weisbach"
    means m = 2: that holds only where the friction factor has stopped
    depending on Reynolds number, which a smooth PE dripline never reaches.
    Use :func:`velocity_exponent` to obtain m from the friction factor
    actually in use rather than naming a formula and guessing.
    """
    n = max(1, int(n_outlets))
    m = exponent
    return 1.0 / (m + 1.0) + 1.0 / (2.0 * n) + math.sqrt(max(0.0, m - 1.0)) / (6.0 * n * n)


def emitter_local_loss_equivalent_length(
    n_emitters: int, le_per_emitter_m: float) -> float:
    """
    Added equivalent length for integral emitter barbs, m.

    Each in-line emitter protrudes into the bore and causes a local loss.
    Standard practice converts it to an equivalent pipe length le and adds
    n*le to the physical length.

    Typical le is of the order of 0.1-0.3 m per emitter for 16-20 mm
    laterals, but it is a strong function of barb geometry and bore
    diameter. ALWAYS take le from the manufacturer where available; the
    defaults in this program are indicative only.

    Neglecting this term is unsafe on long laterals: on a 100 m lateral at
    0.33 m emitter spacing it can add 30 percent or more to the computed
    head loss.
    """
    return max(0, int(n_emitters)) * max(0.0, le_per_emitter_m)


LATERAL_V_MAX_MS = 2.0


def head_spread(friction_total_m: float, slope_pct: float, length_m: float,
                n_points: int = 81, exponent: float = 2.0) -> dict:
    """
    TRUE head variation along a multi-outlet run: max(head) - min(head) over
    the whole profile, not the algebraic difference between its two ends.

    What the emitters experience is the SPREAD of pressure across the run.
    On a level or rising run the head falls monotonically and the spread does
    equal ``hf + dz``, which is why the endpoint form survived so long. On a
    FALLING run it does not: friction is front-loaded, phi(r) = 1-(1-r)^(m+1),
    while elevation gain is linear, so the head dips and then recovers. The
    two ends can sit at almost the same pressure while a deep trough runs
    between them.

    Worked case (100 m lateral, hf 2.679 m, slope -2.5 %):
        endpoint hf + dz = +0.179 m   -> "26 % of the allowance, comfortable"
        true spread      =  1.109 m   -> 162 % of the allowance, REJECT
    a factor of 6.2. Version 0.3.0 fixed this for the uniformity calculation
    by scanning the profile, and left the ACCEPTANCE check — the one that
    actually gates the design — on the endpoint difference. Same defect, same
    function, one caller apart.

    Returns the spread, where the governing minimum sits, and the endpoint
    difference so the caller can still report the net direction.
    """
    prof = lateral_head_profile(0.0, friction_total_m, slope_pct, length_m,
                                n_points=n_points, exponent=exponent)
    heads = [p["head_m"] for p in prof]
    i_min = min(range(len(heads)), key=lambda i: heads[i])
    i_max = max(range(len(heads)), key=lambda i: heads[i])
    return {
        "spread_m": heads[i_max] - heads[i_min],
        "distance_of_min_m": prof[i_min]["distance_m"],
        "distance_of_max_m": prof[i_max]["distance_m"],
        "min_is_interior": 0 < i_min < len(heads) - 1,
        "endpoint_dh_m": friction_total_m + length_m * slope_pct / 100.0,
    }


def head_variation_check(dh_m: float, allowable_m: float,
                         spread_m: float | None = None) -> dict:
    """
    Judge a head variation against its allowance.

    Two defects of the same family have been fixed here:

    1. A signed comparison ``dh <= allowable`` passes trivially when dh is
       negative, and a negative dh is not a benign result: elevation gain
       exceeded friction, so the far end sits at a HIGHER pressure than the
       inlet. Version 0.2.0 gave a downhill design green ticks while its far
       end ran 3.6 m above design head. Fixed by judging ``abs(dh)``.

    2. ``abs(dh)`` is still only the difference between the two ENDS. Pass
       ``spread_m`` (from :func:`head_spread`) and the verdict is taken on the
       true head range over the whole profile instead. Without it the caller
       gets the old endpoint behaviour, which is correct only on a level or
       rising run.

    ``direction`` always describes the net endpoint difference, because that
    is what tells the engineer whether the far end is under- or over-pressured;
    ``magnitude_m`` is what the verdict was actually taken on.
    """
    endpoint_magnitude = abs(dh_m)
    if spread_m is None:
        magnitude = endpoint_magnitude
        spread_governs = False
    else:
        magnitude = abs(spread_m)
        spread_governs = magnitude > endpoint_magnitude + 1e-12
    # NaN-safe in the correct direction. Every comparison with a NaN is False,
    # so `m <= a` yields False and REJECTS it, whereas `not (m > a)` yields
    # True and would accept it. The two forms are equivalent for real numbers
    # and opposite for a NaN; this one fails safe.
    within = magnitude <= allowable_m
    direction = "loss" if dh_m >= 0 else "gain"
    return {
        "dh_m": dh_m, "magnitude_m": magnitude, "allowable_m": allowable_m,
        "endpoint_magnitude_m": endpoint_magnitude,
        "within": within, "direction": direction,
        "spread_governs": spread_governs,
        "over_pressure": dh_m < 0 and endpoint_magnitude > allowable_m,
    }


def lateral_head_loss(
    q_total_m3h: float,
    d_mm: float,
    length_m: float,
    n_emitters: int,
    le_per_emitter_m: float = 0.15,
    slope_pct: float = 0.0,
    nu: float = NU_20C,
    roughness_mm: float = 0.007,
    exponent_mode: str = EXPONENT_MODE_DEFAULT,
) -> dict:
    """
    Head loss along a multi-outlet drip lateral, m.

        hf_lateral = F * hf(L_eq, Q_inlet)
        dH_total   = hf_lateral +/- dZ

    A downhill lateral recovers elevation head, which can offset friction
    entirely; an uphill lateral compounds it. Sign convention: positive
    slope_pct means the lateral runs uphill.
    """
    l_eq = length_m + emitter_local_loss_equivalent_length(n_emitters, le_per_emitter_m)
    base = head_loss_darcy(q_total_m3h, d_mm, l_eq, nu, roughness_mm)
    m_measured = velocity_exponent(base["reynolds"], roughness_mm / max(d_mm, 1e-9))
    m_exp = resolve_exponent(exponent_mode, m_measured)
    f_factor = christiansen_f(n_emitters, exponent=m_exp)
    hf = base["hf_m"] * f_factor
    hf_conventional = base["hf_m"] * christiansen_f(n_emitters, exponent=2.0)
    hf_measured = base["hf_m"] * christiansen_f(n_emitters, exponent=m_measured)
    dz = length_m * slope_pct / 100.0
    spread = head_spread(hf, slope_pct, length_m, exponent=m_exp)
    return {
        "hf_m": hf,
        "elevation_m": dz,
        "total_dh_m": hf + dz,
        # The endpoint difference above is kept for reporting the direction.
        # `spread_m` is the true head range the emitters see and is what the
        # acceptance check must be taken on — see head_spread().
        "spread_m": spread["spread_m"],
        "spread_min_at_m": spread["distance_of_min_m"],
        "spread_min_is_interior": spread["min_is_interior"],
        "velocity_exponent": m_exp,
        "velocity_exponent_measured": m_measured,
        "exponent_mode": exponent_mode,
        # Both answers, always, so the difference is visible rather than
        # buried in a default. See resolve_exponent() for why there are two.
        "hf_conventional_m": hf_conventional,
        "hf_measured_m": hf_measured,
        "equivalent_length_m": l_eq,
        "local_loss_share_pct": 100.0 * (l_eq - length_m) / l_eq if l_eq > 0 else 0.0,
        "F": f_factor,
        "velocity_ms": base["velocity_ms"],
        "reynolds": base["reynolds"],
        "friction_factor": base["friction_factor"],
        "regime": base["regime"],
        # The velocity cap used to be applied to manifolds and mainlines only.
        # A 600 m lateral reached 9 m/s with no warning at all.
        "velocity_ok": base["velocity_ms"] <= LATERAL_V_MAX_MS,
        "velocity_limit_ms": LATERAL_V_MAX_MS,
    }


def lateral_head_profile(
    h_inlet_m: float,
    friction_total_m: float,
    slope_pct: float,
    length_m: float,
    n_points: int = 25,
    exponent: float = 2.0,
) -> list[dict]:
    """
    Pressure-head profile along a multi-outlet lateral, m.

    Friction does NOT accumulate linearly along a dripline: discharge is bled
    off at every emitter, so the flow — and with it the friction gradient —
    falls towards the far end. The fraction of the total friction loss already
    consumed at a relative distance r from the inlet is

        phi(r) = 1 - (1 - r)^(m+1)

    with m the velocity exponent of the friction formula (2 for
    Darcy-Weisbach). Most of the loss happens in the first third of the line.

    The elevation term is linear in r and is added with its sign, so a falling
    lateral shows head recovering towards the far end.

    Returns [{"distance_m", "relative", "head_m", "friction_m", "elevation_m"}].
    """
    n = max(2, int(n_points))
    m1 = exponent + 1.0
    out = []
    for i in range(n):
        r = i / (n - 1)
        phi = 1.0 - (1.0 - r) ** m1
        friction = friction_total_m * phi
        elevation = length_m * r * slope_pct / 100.0
        out.append({
            "distance_m": length_m * r,
            "relative": r,
            "friction_m": friction,
            "elevation_m": elevation,
            "head_m": h_inlet_m - friction - elevation,
        })
    return out


def manifold_head_loss(q_total_m3h: float, d_mm: float, length_m: float,
                       n_laterals: int, slope_pct: float = 0.0,
                       nu: float = NU_20C, roughness_mm: float = 0.007,
                       exponent_mode: str = EXPONENT_MODE_DEFAULT) -> dict:
    """Head loss along a multi-outlet manifold (submain), m."""
    base = head_loss_darcy(q_total_m3h, d_mm, length_m, nu, roughness_mm)
    m_measured = velocity_exponent(base["reynolds"], roughness_mm / max(d_mm, 1e-9))
    m_exp = resolve_exponent(exponent_mode, m_measured)
    f_factor = christiansen_f(n_laterals, exponent=m_exp)
    hf = base["hf_m"] * f_factor
    dz = length_m * slope_pct / 100.0
    # A manifold is a multi-outlet run exactly like a lateral, so it has the
    # same front-loaded friction profile and needs the same spread treatment.
    # It was judged on hf + dz alone, which on a falling manifold understated
    # the head range by a factor of 2.5 in the verified case.
    spread = head_spread(hf, slope_pct, length_m, exponent=m_exp)
    return {"hf_m": hf, "elevation_m": dz, "total_dh_m": hf + dz, "F": f_factor,
            "velocity_exponent": m_exp,
            "velocity_exponent_measured": m_measured,
            "exponent_mode": exponent_mode,
            "spread_m": spread["spread_m"],
            "spread_min_at_m": spread["distance_of_min_m"],
            "spread_min_is_interior": spread["min_is_interior"],
            "velocity_ms": base["velocity_ms"], "reynolds": base["reynolds"],
            "friction_factor": base["friction_factor"], "regime": base["regime"]}


def flushing_velocity_check(d_mm: float, q_flush_m3h: float,
                            v_required_ms: float = 0.30) -> dict:
    """
    Flushing check.

    A drip lateral must be flushed at a velocity high enough to carry
    settled particles out of the line. 0.30 m/s is the common minimum;
    0.50 m/s is specified where the water carries fine sediment, which is
    the normal case on Nile and drainage water.

    There is no equivalent requirement in sprinkler design.
    """
    v = velocity(q_flush_m3h, d_mm)
    return {"flush_velocity_ms": v, "required_ms": v_required_ms,
            "adequate": v >= v_required_ms}


# ---------------------------------------------------------------------------
# 5. Water quality, clogging hazard and filtration
# ---------------------------------------------------------------------------

# Bucks & Nakayama clogging-hazard classification, as reproduced widely in
# FAO and ASABE drip-irrigation literature.
# NOTE: thresholds must be verified against the original source before being
# quoted in an official document. Flagged in the program interface.
CLOGGING_CRITERIA = {
    "suspended_solids_mg_l": {"slight": 50.0, "moderate": 100.0, "unit": "mg/L"},
    "dissolved_solids_mg_l": {"slight": 500.0, "moderate": 2000.0, "unit": "mg/L"},
    "manganese_mg_l": {"slight": 0.1, "moderate": 1.5, "unit": "mg/L"},
    "iron_mg_l": {"slight": 0.2, "moderate": 1.5, "unit": "mg/L"},
    "hydrogen_sulphide_mg_l": {"slight": 0.2, "moderate": 2.0, "unit": "mg/L"},
    "ph": {"slight": 7.0, "moderate": 8.0, "unit": "-"},
    "bacterial_population_per_ml": {"slight": 10000.0, "moderate": 50000.0, "unit": "no./mL"},
}

_HAZARD_RANK = {"slight": 0, "moderate": 1, "severe": 2}
_RANK_HAZARD = {0: "slight", 1: "moderate", 2: "severe"}

PH_CORROSIVE_BELOW = 6.5


def clogging_hazard(water_quality: dict) -> dict:
    """
    Classify physical, chemical and biological clogging hazard.

    Returns the per-parameter class, the governing (worst) class that drives
    filtration grade and the chemical schedule, and a separate corrosion note.

    The pH criterion is deliberately one-sided: it measures the tendency to
    precipitate carbonate, so a low pH is a low CLOGGING hazard. That is
    correct, and it was also misleading — the edge-case probe showed pH 4.5
    reported as "slight" with nothing else said, and a reader takes that as
    "this water is fine". Acidic water is aggressive to metal fittings and to
    some emitter polymers, so it is now surfaced separately instead of being
    folded into a class it does not belong to.
    """
    per_param = {}
    worst = 0
    for key, value in water_quality.items():
        crit = CLOGGING_CRITERIA.get(key)
        if crit is None or value is None:
            continue
        if value <= crit["slight"]:
            cls = "slight"
        elif value <= crit["moderate"]:
            cls = "moderate"
        else:
            cls = "severe"
        per_param[key] = {"value": value, "class": cls, "unit": crit["unit"]}
        worst = max(worst, _HAZARD_RANK[cls])

    ph = water_quality.get("ph")
    corrosion = None
    if ph is not None and ph < PH_CORROSIVE_BELOW:
        corrosion = (f"pH {ph} is below {PH_CORROSIVE_BELOW}. The clogging class shown for "
                     "pH measures scale formation only, and low pH scores well on it. "
                     "Acidic water is nonetheless aggressive to metal fittings, pump "
                     "internals and some emitter polymers. Specify corrosion-resistant "
                     "materials and check the emitter manufacturer's pH range.")

    return {"per_parameter": per_param,
            "overall": _RANK_HAZARD[worst] if per_param else "unknown",
            "corrosion_note": corrosion}


def required_filtration_mesh(emitter_passage_mm: float, safety_divisor: float = 7.0) -> dict:
    """
    Required filtration grade.

    Rule of practice: filter to between one seventh and one tenth of the
    smallest emitter passage dimension. Returns the aperture in micron and
    the nearest standard mesh number.

    Mesh number is related to aperture by roughly:
        mesh ~ 16000 / aperture_micron
    which is an approximation adequate for selection, not for procurement
    specification.
    """
    if emitter_passage_mm <= 0:
        return {"aperture_micron": 0.0, "mesh": 0, "divisor": safety_divisor}
    aperture_micron = emitter_passage_mm * 1000.0 / safety_divisor
    mesh = int(round(16000.0 / aperture_micron)) if aperture_micron > 0 else 0
    return {"aperture_micron": aperture_micron, "mesh": mesh, "divisor": safety_divisor}


def recommend_filtration(source: str, hazard: str, emitter_passage_mm: float) -> dict:
    """
    Recommend a filtration train.

    Selection logic reflects normal Egyptian practice:
      surface water (Nile, canals, drains) carries algae and organic load
      -> media filter is mandatory, screen or disc downstream as a guard
      well water carrying sand -> hydrocyclone ahead of the fine filter
      clean pressurised supply -> disc or screen alone may suffice
    """
    src = (source or "").lower()
    train: list[str] = []
    notes: list[str] = []

    if "well" in src or "بئر" in src:
        train.append("Hydrocyclone (sand separator)")
        notes.append("Well water: sand separator upstream protects the fine filter from abrasion.")
    if any(t in src for t in ["nile", "canal", "drain", "surface", "نيل", "ترعة", "مصرف", "سطح"]):
        train.append("Media (sand) filter")
        notes.append("Surface water carries algae and organic load that a screen alone cannot hold.")
        train.append("Disc filter (guard)")
    else:
        train.append("Disc or screen filter")

    if hazard == "severe":
        notes.append("Severe clogging hazard: duplicate filtration and automatic backflush are required, not optional.")
    elif hazard == "moderate":
        notes.append("Moderate hazard: automatic backflush recommended; schedule chemical treatment.")

    mesh = required_filtration_mesh(emitter_passage_mm)
    return {"train": train, "notes": notes, "filtration_grade": mesh}


def chemical_maintenance_schedule(hazard: dict) -> list[dict]:
    """
    Derive a chemical maintenance schedule from the hazard classification.

    Chlorination addresses biological clogging; acid injection addresses
    carbonate precipitation. Both are design outputs in drip and have no
    counterpart in sprinkler design.

    Doses given are indicative practice ranges. They must be confirmed
    against the emitter manufacturer's chemical-compatibility statement and
    local regulations before use.
    """
    actions: list[dict] = []
    per = hazard.get("per_parameter", {})

    bact = per.get("bacterial_population_per_ml", {}).get("class")
    h2s = per.get("hydrogen_sulphide_mg_l", {}).get("class")
    if bact in ("moderate", "severe") or h2s in ("moderate", "severe"):
        freq = "continuous injection" if bact == "severe" else "weekly shock"
        actions.append({
            "treatment": "Chlorination",
            "target": "biological slime, algae, bacterial iron/sulphur",
            "indicative_dose": "1-2 mg/L free residual at the distal emitter (continuous), or 10-20 mg/L for 30-60 min (shock)",
            "frequency": freq,
        })

    ph = per.get("ph", {})
    fe = per.get("iron_mg_l", {}).get("class")
    mn = per.get("manganese_mg_l", {}).get("class")
    if ph.get("class") in ("moderate", "severe") or fe in ("moderate", "severe") or mn in ("moderate", "severe"):
        actions.append({
            "treatment": "Acid injection",
            "target": "carbonate scale, iron and manganese oxide precipitation",
            "indicative_dose": "lower line pH to 5.5-6.5 during treatment",
            "frequency": "monthly, or when discharge drop exceeds 5 percent",
        })

    actions.append({
        "treatment": "Line flushing",
        "target": "settled particles at lateral ends",
        "indicative_dose": f"flush velocity >= 0.30 m/s (0.50 m/s for silty water)",
        "frequency": "monthly minimum; weekly for surface water",
    })
    return actions


# ---------------------------------------------------------------------------
# 6. Operational design
# ---------------------------------------------------------------------------

def irrigation_interval(raw_mm: float, etc_peak_mm_d: float) -> float:
    """Maximum interval, days."""
    if etc_peak_mm_d <= 0:
        return 0.0
    return raw_mm / etc_peak_mm_d


def application_rate(emitter_q_lph: float, emitter_spacing_m: float,
                     lateral_spacing_m: float) -> float:
    """
    Equivalent application rate over the whole field, mm/h.

        Ia = q / (Se * Sl)
    """
    area = emitter_spacing_m * lateral_spacing_m
    if area <= 0:
        return 0.0
    return emitter_q_lph / area          # L/h per m2 == mm/h


def set_time(gross_depth_mm: float, application_rate_mm_h: float) -> float:
    """Irrigation time per set, h."""
    if application_rate_mm_h <= 0:
        return 0.0
    return gross_depth_mm / application_rate_mm_h


def number_of_shifts(available_flow_m3h: float, system_flow_full_m3h: float) -> int:
    """
    Number of shifts required when the source cannot feed the whole field
    at once. Always at least 1.

    Raises on a non-positive source discharge. It previously returned 1,
    implying the whole field could run at once on no water at all — found by
    the edge-case probe.
    """
    if available_flow_m3h <= 0:
        raise ValueError("Available source discharge must be greater than zero.")
    return max(1, math.ceil(system_flow_full_m3h / available_flow_m3h))


def water_balance(q_avail_m3h: float, hours_per_day: float, gross_mm_per_day: float,
                  area_ha: float) -> dict:
    """
    Can the source supply the peak daily gross demand at all?

        demand = gross depth (mm/d) x 10 x area (ha)       m³/day
        supply = source discharge (m³/h) x operating hours  m³/day

    This is the first question of any schedule and it does not depend on the
    layout. When it fails no arrangement of subunits or shifts can succeed,
    and the remedies are on the WATER side: more discharge, more hours, or
    less area. v2.0.0 only reported it indirectly, as a cycle that did not
    fit, with advice (fewer shifts, shorter interval) that cannot work.
    """
    demand = max(0.0, gross_mm_per_day) * 10.0 * max(0.0, area_ha)
    supply = max(0.0, q_avail_m3h) * max(0.0, hours_per_day)
    ok = supply >= demand - 1e-9
    q_needed = demand / hours_per_day if hours_per_day > 0 else float("inf")
    h_needed = demand / q_avail_m3h if q_avail_m3h > 0 else float("inf")
    area_max = supply / (gross_mm_per_day * 10.0) if gross_mm_per_day > 0 else float("inf")
    return {"demand_m3_day": demand, "supply_m3_day": supply, "ok": ok,
            "ratio": supply / demand if demand > 0 else float("inf"),
            "q_needed_m3h": q_needed, "hours_needed": h_needed, "area_max_ha": area_max}


def operating_hours_check(shifts: int, set_time_h: float, interval_d: float,
                          max_hours_per_day: float = 20.0) -> dict:
    """
    Verify the schedule fits inside the day.

    Failure here is the most common reason a drip design is infeasible in
    practice: the hydraulics balance but the farm cannot run the pump for
    the hours the schedule demands.

    TWO conditions, not one. The cycle total must fit inside the cycle, and
    each individual SET must fit inside a single working day. Judging on the
    cycle total alone lets a 25 h set pass against an 18 h day, because
    18 x 3 = 54 h of cycle capacity looks ample — but a set cannot be
    suspended overnight and resumed, so a 25 h set is simply not runnable.
    The old check reported that case as feasible at 46 % utilisation.

    A non-positive set time is not a zero-duration irrigation; it means the
    application rate was zero or negative, which is an input error. It used
    to pass as a comfortable schedule at 0 % utilisation.
    """
    required = shifts * set_time_h
    available = max_hours_per_day * max(1e-6, interval_d)
    # `<=` rather than `not (>)`: both are equivalent for real numbers, but a
    # NaN makes the first False (rejected) and the second True (accepted).
    set_fits_day = set_time_h <= max_hours_per_day
    cycle_fits = required <= available
    positive = set_time_h > 0.0
    if not positive:
        reason = ("The set time is zero or negative, which means the application "
                  "rate is not positive. This is an input error, not a schedule.")
    elif not set_fits_day:
        reason = (f"A single set of {set_time_h:.2f} h does not fit inside the "
                  f"{max_hours_per_day:.1f} h working day. An irrigation set cannot "
                  "be suspended overnight and resumed: raise the application rate, "
                  "shorten the set, or extend the working day.")
    elif not cycle_fits:
        reason = (f"The cycle needs {required:.2f} h against {available:.2f} h "
                  "available. The number of shifts is set by the water the source "
                  "supplies, and shortening the interval does not help (the set time "
                  "and the window shrink together). Increase the source discharge, "
                  "extend the daily operating hours, or reduce the irrigated area.")
    else:
        reason = ""
    return {"required_h_per_cycle": required, "available_h_per_cycle": available,
            "set_time_h": set_time_h, "max_hours_per_day": max_hours_per_day,
            "set_fits_day": set_fits_day, "cycle_fits": cycle_fits,
            "feasible": positive and set_fits_day and cycle_fits,
            "reason": reason,
            "utilisation_pct": 100.0 * required / available if available > 0 else 0.0}


# ---------------------------------------------------------------------------
# 7. Pump
# ---------------------------------------------------------------------------

def total_dynamic_head(
    static_lift_m: float,
    emitter_head_m: float,
    lateral_dh_m: float,
    manifold_dh_m: float,
    mainline_hf_m: float,
    filter_clean_m: float,
    filter_dirty_allowance_m: float,
    minor_loss_fraction: float = 0.10,
    fertigation_loss_m: float = 0.0,
) -> dict:
    """
    TDH, m.

    The filter differential is the term most often forgotten. A media filter
    passes 2-4 m clean and is normally allowed to reach 5-7 m before
    backflush; sizing the pump on the clean value guarantees the system
    falls below design pressure before every backflush cycle.
    """
    pipe_terms = lateral_dh_m + manifold_dh_m + mainline_hf_m
    minor = minor_loss_fraction * pipe_terms
    tdh = (static_lift_m + emitter_head_m + pipe_terms + minor
           + filter_clean_m + filter_dirty_allowance_m + fertigation_loss_m)
    return {
        "tdh_m": tdh,
        "static_m": static_lift_m,
        "emitter_head_m": emitter_head_m,
        "pipe_friction_m": pipe_terms,
        "minor_m": minor,
        "filter_m": filter_clean_m + filter_dirty_allowance_m,
        "fertigation_m": fertigation_loss_m,
    }


def pump_power(q_m3h: float, tdh_m: float, pump_efficiency: float,
               motor_efficiency: float = 0.90) -> dict:
    """
    Hydraulic, brake and motor-input power, kW.

    Both efficiencies were validated and the HEAD was not. A mainline rise of
    -100 m (inside the widget range) gave TDH -71.6 m, brake -10.8 kW, and
    _next_standard_motor returned its first entry, 0.37 kW, priced into the
    bill of quantities as though it were a real selection. A non-positive TDH
    means the system is gravity-fed or the inputs are wrong; either way it is
    not a pump duty.
    """
    if not 0.0 < pump_efficiency <= 1.0:
        raise ValueError("Pump efficiency must be greater than 0 and at most 1.")
    if not 0.0 < motor_efficiency <= 1.0:
        raise ValueError("Motor efficiency must be greater than 0 and at most 1.")
    if not q_m3h > 0.0:
        raise ValueError("Duty discharge must be greater than zero.")
    if not tdh_m > 0.0:
        raise ValueError(
            f"Total dynamic head is {tdh_m:.2f} m, which is not a pump duty. "
            "Either the system is gravity-fed and needs no pump, or an "
            "elevation input has the wrong sign.")
    q_s = q_m3h / 3600.0
    p_hyd = q_s * tdh_m * RHO * G / 1000.0
    p_brake = p_hyd / pump_efficiency
    p_motor = p_brake / motor_efficiency
    rating, off_scale = _next_standard_motor(p_brake)
    return {"hydraulic_kw": p_hyd, "brake_kw": p_brake, "motor_input_kw": p_motor,
            "motor_rating_kw": rating,
            "required_rating_kw": p_brake * MOTOR_SERVICE_MARGIN,
            "rating_off_scale": off_scale}


_STANDARD_MOTORS = [0.37, 0.55, 0.75, 1.1, 1.5, 2.2, 3.0, 4.0, 5.5, 7.5, 11, 15,
                    18.5, 22, 30, 37, 45, 55, 75, 90, 110, 132, 160, 200, 250]


MOTOR_SERVICE_MARGIN = 1.15


def _next_standard_motor(p_brake_kw: float) -> tuple[float, bool]:
    """
    Smallest standard frame carrying the brake power plus its service margin.

    Returns (rating, off_scale). The old form returned the top of the list
    silently: a 227 kW brake duty needs 261 kW with the margin, and the
    function returned 250 kW as an "ok"-coloured card, delivering the pump
    4 per cent below its own stated margin and understating the cost. The
    caller now knows the list ran out.
    """
    target = p_brake_kw * MOTOR_SERVICE_MARGIN
    for m in _STANDARD_MOTORS:
        if m >= target:
            return float(m), False
    return float(_STANDARD_MOTORS[-1]), True


# ---------------------------------------------------------------------------
# 8. Fertigation
# ---------------------------------------------------------------------------

def fertigation_injection_rate(fertiliser_kg_per_ha: float, area_ha: float,
                               stock_concentration_kg_per_l: float,
                               injection_time_h: float) -> dict:
    """
    Injector duty, L/h of stock solution.

    Injection is a design output in drip, not an afterthought: the injector
    duty and its head loss enter the pump calculation.
    """
    total_kg = fertiliser_kg_per_ha * area_ha
    if stock_concentration_kg_per_l <= 0 or injection_time_h <= 0:
        return {"stock_volume_l": 0.0, "injection_rate_lph": 0.0, "total_fertiliser_kg": total_kg}
    stock_l = total_kg / stock_concentration_kg_per_l
    return {"stock_volume_l": stock_l,
            "injection_rate_lph": stock_l / injection_time_h,
            "total_fertiliser_kg": total_kg}


# ---------------------------------------------------------------------------
# 9. Pipe sizing
# ---------------------------------------------------------------------------

@dataclass
class PipeOption:
    nominal_mm: float
    internal_mm: float
    material: str
    pn_bar: float
    price_egp_per_m: float = 0.0

    @property
    def roughness_mm(self) -> float:
        return ROUGHNESS_MM.get((self.material or "PE").upper(), 0.007)


def safe_filename(stem: str, fallback: str = "project", max_len: int = 80) -> str:
    """
    Turn a free-text project name into a filename Windows will accept.

    Replacing spaces alone was not enough: a name like "Project / East Delta"
    or a colon in an Arabic title reached the download filename and Windows
    rejected or truncated the file. Found by the edge-case probe.
    """
    cleaned = (stem or "").strip()
    for ch in '/\\:*?"<>|\r\n\t':
        cleaned = cleaned.replace(ch, "-")
    cleaned = "_".join(cleaned.split())
    cleaned = cleaned.strip("._-")
    if not cleaned:
        cleaned = fallback
    return cleaned[:max_len]


def select_pipe_diameter(
    q_m3h: float,
    length_m: float,
    catalogue: list[PipeOption],
    allowable_dh_m: float,
    n_outlets: int = 1,
    v_max_ms: float = 2.0,
    slope_pct: float = 0.0,
    nu: float = NU_20C,
) -> dict:
    """
    Deterministic bounded scan of the catalogue.

    Selects the smallest internal diameter satisfying BOTH the velocity cap
    and the allowable head SPREAD. If none satisfies both, returns the BEST
    of the catalogue — the one with the smallest combined violation — and
    reports the shortfall rather than iterating open-endedly.

    Two defects fixed here:

    1. The criterion was ``abs(hf + dz)``, the endpoint difference. On a
       falling run that is not monotone in diameter: |hf + dz| went
       4.675, 0.503, 1.932, 2.557, 2.831 m across the catalogue, because a
       particular diameter happens to make friction cancel the elevation drop
       AT THE TWO ENDS. "Smallest satisfying" then meant "smallest that
       happens to cancel", and larger, better pipes were rejected where a
       smaller one passed. Judged on the spread the criterion is monotone
       decreasing in diameter, as the scan assumes.

    2. The no-solution fallback returned the LARGEST size, on the reasoning
       that largest is closest to satisfying. Under the old non-monotone
       criterion that was false: the returned 315 mm PVC had |dH| 2.999 m
       against 63 mm PE's 0.503 m, six times worse on the very criterion it
       failed and fifteen times the unit price, and it went straight into the
       bill of quantities. The fallback now returns the actual best candidate.
    """
    if not catalogue:
        # Previously returned selected=None, and every caller then dereferenced
        # it and raised AttributeError somewhere far from the cause.
        raise ValueError("Pipe catalogue is empty; cannot select a diameter.")
    ordered = sorted(catalogue, key=lambda p: p.internal_mm)
    best = None            # (penalty, index, opt, res) — smallest penalty wins
    for i, opt in enumerate(ordered):
        res = manifold_head_loss(q_m3h, opt.internal_mm, length_m, n_outlets,
                                 slope_pct, nu, opt.roughness_mm)
        spread = res["spread_m"]
        # `spread <= allowable` rejects a NaN; `not (spread > allowable)` accepts it.
        if res["velocity_ms"] <= v_max_ms and spread <= allowable_dh_m:
            return {"selected": opt, "hydraulics": res, "satisfied": True,
                    "warning": None}
        # Normalised so the two violations are comparable; ties break towards
        # the smaller diameter, which is the cheaper pipe.
        penalty = (max(0.0, spread - allowable_dh_m) / max(allowable_dh_m, 1e-9)
                   + max(0.0, res["velocity_ms"] - v_max_ms) / max(v_max_ms, 1e-9))
        if best is None or penalty < best[0]:
            best = (penalty, i, opt, res)
    _, _, opt, res = best
    return {"selected": opt, "hydraulics": res, "satisfied": False,
            "warning": "No catalogue size satisfies both the velocity cap and the "
                       f"allowable head spread. Closest available size returned "
                       f"({opt.nominal_mm:.0f} mm {opt.material}, spread "
                       f"{res['spread_m']:.3f} m against {allowable_dh_m:.3f} m "
                       "allowable); shorten the run, split the subunit, or raise "
                       "the operating head."}
