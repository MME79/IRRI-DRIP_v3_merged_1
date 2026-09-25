"""
IRRI-DRIP — independent verification of the lateral by the step method.

WHY THIS EXISTS
---------------
The design path in engine/kernels.py computes a lateral in two compressed
steps: one Darcy-Weisbach loss for the whole equivalent length at the INLET
discharge, multiplied by a Christiansen factor F to account for the flow
being bled off along the way; and a separate closed-form profile
phi(r) = 1 - (1-r)^(m+1) to place that loss along the line.

Both are approximations, and the whole of v0.4.0's head-spread correction
rests on the second one. Verifying that path against another program that
uses the same two approximations would prove nothing.

The step method uses NEITHER. It marches segment by segment from the inlet:
the discharge in each segment is the sum of what the emitters downstream of
it actually take, and the loss in that segment is computed on its own. No
Christiansen factor appears anywhere in this file, and neither does phi(r).
Where the two paths agree, the approximation is doing its job; where they
disagree, the difference is the price of the approximation and is reported
as a number rather than assumed away.

TWO MODES
---------
FIXED     every emitter delivers its nominal discharge. This is exactly the
          assumption the Christiansen factor is derived under, so it isolates
          the F factor and the phi(r) profile shape and nothing else.

COUPLED   every emitter delivers q = k*H^x at its own local head, solved by
          fixed-point iteration. This is what the pipe actually does, and the
          gap between COUPLED and FIXED is the error introduced by assuming
          uniform outflow in the first place.

Run:  python validation/step_method.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import kernels as K


# ---------------------------------------------------------------------------
# The independent engine
# ---------------------------------------------------------------------------

def step_lateral(
    k: float,
    x: float,
    h_inlet_m: float,
    d_mm: float,
    length_m: float,
    n_emitters: int,
    le_per_emitter_m: float = 0.15,
    slope_pct: float = 0.0,
    nu: float = K.NU_20C,
    roughness_mm: float = 0.007,
    coupled: bool = True,
    max_iter: int = 200,
    tol_lph: float = 1e-7,
) -> dict:
    """
    March the lateral segment by segment.

    Geometry. Emitter j (j = 1..n) sits at distance j*Se from the inlet, with
    Se = length / n. Segment j is the pipe between emitter j-1 and emitter j,
    with emitter 0 meaning the inlet. Segment j therefore carries everything
    that emitters j..n will discharge.

    Losses. Each segment is charged its own Darcy-Weisbach loss over a length
    of Se plus le_per_emitter_m, the equivalent length of the barb that
    protrudes into the pipe at the emitter ending that segment. Each segment
    is also charged its own elevation change, Se * slope/100, with sign.

    Discharges. In COUPLED mode q_j = k * H_j^x with H_j the head actually
    standing at emitter j, solved by damped fixed-point iteration from a
    uniform first guess. In FIXED mode every q_j is held at k * h_inlet^x.

    Nothing here uses christiansen_f() or lateral_head_profile(). The only
    kernel this file calls is head_loss_darcy(), which is the plain
    Darcy-Weisbach relation for a single full-flowing pipe segment and is the
    common physical ground both paths must stand on.
    """
    n = int(n_emitters)
    if n < 1:
        raise ValueError("A lateral needs at least one emitter.")
    se = length_m / n
    dz_seg = se * slope_pct / 100.0
    l_seg = se + le_per_emitter_m

    q_nom_lph = K.emitter_discharge(k, x, h_inlet_m)
    q = [q_nom_lph] * n                      # first guess, L/h

    heads = [h_inlet_m] * n
    seg_hf = [0.0] * n
    iterations = 0
    residual = float("inf")

    for iterations in range(1, max_iter + 1):
        # ---- forward march: heads from the current discharges -------------
        h = h_inlet_m
        for j in range(n):
            # everything from emitter j+1 to emitter n passes through segment j
            q_seg_lph = sum(q[j:])
            res = K.head_loss_darcy(q_seg_lph / 1000.0, d_mm, l_seg, nu,
                                    roughness_mm)
            seg_hf[j] = res["hf_m"]
            h = h - res["hf_m"] - dz_seg
            heads[j] = h

        if not coupled:
            residual = 0.0
            break

        # ---- update the discharges from the new heads ---------------------
        q_new = [K.emitter_discharge(k, x, max(0.0, hj)) for hj in heads]
        residual = max(abs(a - b) for a, b in zip(q, q_new))
        # Light damping: the loop is contractive for x <= 0.5 but a raw update
        # oscillates on a steep downhill line where the head recovers.
        q = [0.5 * a + 0.5 * b for a, b in zip(q, q_new)]
        if residual < tol_lph:
            break
    else:
        # Not converged. This happens on a lateral so overloaded that the head
        # goes negative part way along: emitters clamp to zero discharge, the
        # friction collapses, the head recovers, and they switch back on. The
        # oscillation is physical, not numerical — the lateral has no steady
        # solution as specified — and the caller must not be handed the last
        # iterate as though it were an answer.
        if coupled:
            raise RuntimeError(
                f"The coupled march did not converge in {max_iter} iterations "
                f"(residual {residual:.3e} L/h). The lateral is overloaded to "
                "the point where part of it loses pressure entirely. Shorten "
                "it, increase the diameter, or raise the inlet head.")

    # The head at the inlet itself is h_inlet_m; the profile the emitters see
    # runs from there through heads[0..n-1].
    profile = [h_inlet_m] + heads
    distances = [0.0] + [(j + 1) * se for j in range(n)]

    i_min = min(range(len(profile)), key=lambda i: profile[i])
    i_max = max(range(len(profile)), key=lambda i: profile[i])

    q_min = min(q)
    q_max = max(q)
    q_avg = sum(q) / n
    eu = K.emission_uniformity(0.0, 1, q_min, q_avg)   # CV set aside: hydraulics only

    return {
        "mode": "COUPLED" if coupled else "FIXED",
        "iterations": iterations,
        "converged": (not coupled) or residual < tol_lph,
        "residual_lph": residual,
        "n_segments": n,
        "segment_length_m": se,
        "friction_total_m": sum(seg_hf),
        "elevation_total_m": length_m * slope_pct / 100.0,
        "endpoint_dh_m": h_inlet_m - profile[-1],
        "spread_m": profile[i_max] - profile[i_min],
        "distance_of_min_m": distances[i_min],
        "min_is_interior": 0 < i_min < len(profile) - 1,
        "h_min_m": profile[i_min],
        "h_end_m": profile[-1],
        "q_min_lph": q_min,
        "q_max_lph": q_max,
        "q_avg_lph": q_avg,
        "eu_hydraulic_pct": eu,
        "profile_m": profile,
        "distances_m": distances,
        "q_lph": q,
    }


# ---------------------------------------------------------------------------
# Comparison against the design path
# ---------------------------------------------------------------------------

def design_path(k, x, h_inlet_m, d_mm, length_m, n_emitters,
                le_per_emitter_m=0.15, slope_pct=0.0, nu=K.NU_20C,
                roughness_mm=0.007):
    """The kernels' own answer, for the same lateral."""
    q_nom_lph = K.emitter_discharge(k, x, h_inlet_m)
    q_lat_m3h = q_nom_lph * n_emitters / 1000.0
    res = K.lateral_head_loss(q_lat_m3h, d_mm, length_m, n_emitters,
                              le_per_emitter_m, slope_pct, nu, roughness_mm)
    uni = K.lateral_uniformity(k, x, h_inlet_m, res["hf_m"], slope_pct,
                               length_m, cv=0.0, n_points=201,
                               exponent=res["velocity_exponent"])
    return {
        "friction_total_m": res["hf_m"],
        "elevation_total_m": res["elevation_m"],
        "endpoint_dh_m": res["total_dh_m"],
        "spread_m": res["spread_m"],
        "distance_of_min_m": res["spread_min_at_m"],
        "min_is_interior": res["spread_min_is_interior"],
        "h_min_m": uni["h_min_m"],
        "h_end_m": uni["h_end_m"],
        "q_min_lph": uni["q_min_lph"],
        "q_avg_lph": uni["q_avg_lph"],
        "eu_hydraulic_pct": uni["eu_pct"],
        "F": res["F"],
        "m": res["velocity_exponent"],
    }


def _pct(a, b):
    """Difference of a from b, per cent of b. Guards a zero reference."""
    if abs(b) < 1e-9:
        return float("nan") if abs(a) > 1e-9 else 0.0
    return 100.0 * (a - b) / abs(b)


CASES = [
    # name,                       L,     n,   slope, ID,   k,     x
    ("Level, 16 mm, 80 m",        80.0,  160, 0.0,   13.6, 3.734, 0.030),
    ("Level, non-compensating",   80.0,  160, 0.0,   13.6, 0.600, 0.500),
    ("Uphill +2 %",              100.0,  200, +2.0,  13.6, 0.600, 0.500),
    ("Downhill -1 %",            100.0,  200, -1.0,  13.6, 0.600, 0.500),
    ("Downhill -2.5 % (v0.4.0)", 100.0,  200, -2.5,  13.6, 0.600, 0.500),
    ("Downhill -15 %, steep",     80.0,  160, -15.0, 13.6, 0.600, 0.500),
    ("Long 150 m, level",        150.0,  300, 0.0,   13.6, 0.600, 0.500),
]

TOLERANCES = {
    "friction_total_m": 6.0,     # per cent — the F factor is an approximation
    "spread_m": 8.0,
    "distance_of_min_m": 12.0,   # of the lateral length, in metres
}

FINDINGS = []


def compare(name, length_m, n, slope_pct, d_mm, k, x, h_inlet=15.0):
    print(f"\n{'-'*78}\n{name}")
    print(f"  L={length_m:.0f} m  n={n}  Se={length_m/n:.3f} m  "
          f"slope={slope_pct:+.1f} %  ID={d_mm:.1f} mm  k={k:.3f}  x={x:.3f}")

    fixed = step_lateral(k, x, h_inlet, d_mm, length_m, n,
                         slope_pct=slope_pct, coupled=False)
    coupled = step_lateral(k, x, h_inlet, d_mm, length_m, n,
                           slope_pct=slope_pct, coupled=True)
    design = design_path(k, x, h_inlet, d_mm, length_m, n, slope_pct=slope_pct)

    print(f"  {'':28s} {'design (F, phi)':>16s} {'step FIXED':>14s} "
          f"{'diff %':>9s} {'step COUPLED':>14s}")
    rows = [
        ("friction total, m", "friction_total_m", "{:.4f}"),
        ("endpoint dH, m", "endpoint_dh_m", "{:+.4f}"),
        ("head spread, m", "spread_m", "{:.4f}"),
        ("minimum head, m", "h_min_m", "{:.4f}"),
        ("distance of minimum, m", "distance_of_min_m", "{:.1f}"),
        ("q_min, L/h", "q_min_lph", "{:.4f}"),
        ("q_avg, L/h", "q_avg_lph", "{:.4f}"),
        ("EU (hydraulic only), %", "eu_hydraulic_pct", "{:.2f}"),
    ]
    for label, key, fmt in rows:
        d, f, c = design[key], fixed[key], coupled[key]
        print(f"  {label:28s} {fmt.format(d):>16s} {fmt.format(f):>14s} "
              f"{_pct(f, d):>8.2f}% {fmt.format(c):>14s}")

    print(f"  design path: velocity exponent m = {design['m']:.4f}, "
          f"Christiansen F = {design['F']:.4f}")
    print(f"  step method: {fixed['n_segments']} segments, "
          f"COUPLED converged in {coupled['iterations']} iterations "
          f"(residual {coupled['residual_lph']:.2e} L/h)")

    # ---- the checks ------------------------------------------------------
    for key, tol_pct in (("friction_total_m", TOLERANCES["friction_total_m"]),
                         ("spread_m", TOLERANCES["spread_m"])):
        diff = abs(_pct(fixed[key], design[key]))
        if diff != diff:          # NaN reference
            continue
        if diff > tol_pct:
            FINDINGS.append(
                (name, key,
                 f"design {design[key]:.4f} vs step {fixed[key]:.4f} "
                 f"({diff:.1f} % apart, tolerance {tol_pct:.0f} %)"))

    dist_gap = abs(fixed["distance_of_min_m"] - design["distance_of_min_m"])
    if dist_gap > TOLERANCES["distance_of_min_m"]:
        FINDINGS.append(
            (name, "distance_of_min_m",
             f"design places the governing minimum at "
             f"{design['distance_of_min_m']:.1f} m, the step method at "
             f"{fixed['distance_of_min_m']:.1f} m — {dist_gap:.1f} m apart"))

    if fixed["min_is_interior"] != design["min_is_interior"]:
        FINDINGS.append(
            (name, "min_is_interior",
             f"design says interior={design['min_is_interior']}, "
             f"step method says interior={fixed['min_is_interior']}"))

    # The uniform-outflow assumption itself, reported not judged.
    gap = _pct(coupled["spread_m"], fixed["spread_m"])
    print(f"  cost of assuming uniform outflow: spread moves {gap:+.2f} % "
          f"between FIXED and COUPLED")


def main():
    print("=" * 78)
    print("IRRI-DRIP — independent lateral verification by the step method")
    print("=" * 78)
    print("The step method uses no Christiansen factor and no phi(r) profile.")
    print("It marches segment by segment with the discharge each segment")
    print("actually carries. Where the two paths agree, the compression in the")
    print("design path is sound; where they do not, the gap is printed.")

    for name, length_m, n, slope, d_mm, k, x in CASES:
        compare(name, length_m, n, slope, d_mm, k, x)

    print("\n" + "=" * 78)
    print("FINDINGS")
    print("=" * 78)
    if not FINDINGS:
        print("  none — the design path agrees with the independent march")
        print("  within tolerance on every case.")
    for case, key, detail in FINDINGS:
        print(f"\n[{case}] {key}")
        print(f"        {detail}")
    print(f"\nTotal: {len(FINDINGS)} finding(s) across {len(CASES)} cases.")
    return 1 if FINDINGS else 0


if __name__ == "__main__":
    sys.exit(main())
