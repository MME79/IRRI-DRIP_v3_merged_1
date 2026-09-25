"""
IRRI-DRIP — systematic edge-case probe.

Drives the kernels with degenerate, extreme and adversarial inputs and
reports anything that crashes, returns a physically impossible value, or
silently produces a number a designer would trust and should not.

Run:  python validation/edge_cases.py
"""

import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import kernels as K

FINDINGS = []


def probe(name, fn):
    try:
        result = fn()
        return result
    except Exception as exc:
        FINDINGS.append(("CRASH", name, f"{type(exc).__name__}: {exc}"))
        return None


def flag(severity, name, detail):
    FINDINGS.append((severity, name, detail))


def main():
    print("=" * 78)
    print("IRRI-DRIP edge-case probe")
    print("=" * 78)

    # ------------------------------------------------------------------
    # A. Zero and negative inputs
    # ------------------------------------------------------------------
    print("\nA. Zero / negative / degenerate inputs")

    r = probe("velocity, zero diameter", lambda: K.velocity(10.0, 0.0))
    print(f"  velocity(q=10, D=0)                 -> {r}")

    r = probe("head loss, zero diameter", lambda: K.head_loss_darcy(10.0, 0.0, 100.0))
    print(f"  head_loss_darcy(D=0)                -> {r}")

    r = probe("head loss, zero flow", lambda: K.head_loss_darcy(0.0, 16.0, 100.0))
    print(f"  head_loss_darcy(Q=0)                -> hf={r['hf_m'] if r else None}, regime={r['regime'] if r else None}")

    r = probe("emitter, zero head", lambda: K.emitter_discharge(1.0, 0.5, 0.0))
    print(f"  emitter_discharge(H=0)              -> {r}")

    r = probe("emitter, negative head", lambda: K.emitter_discharge(1.0, 0.5, -5.0))
    print(f"  emitter_discharge(H=-5)             -> {r}")

    r = probe("application rate, zero spacing", lambda: K.application_rate(4.0, 0.0, 2.0))
    print(f"  application_rate(Se=0)              -> {r}")

    r = probe("set time, zero rate", lambda: K.set_time(30.0, 0.0))
    print(f"  set_time(Ia=0)                      -> {r}")

    r = probe("interval, zero ETc", lambda: K.irrigation_interval(20.0, 0.0))
    print(f"  irrigation_interval(ETc=0)          -> {r}")

    try:
        K.pump_power(50.0, 40.0, 0.0)
        flag("WEAK", "pump_power zero efficiency", "Returned instead of raising.")
        print("  pump_power(eta=0)                   -> returned (WEAK)")
    except ValueError as exc:
        print(f"  pump_power(eta=0)                   -> raises ValueError: {exc}")

    r = probe("fertigation, zero stock", lambda: K.fertigation_injection_rate(25.0, 5.0, 0.0, 2.0))
    print(f"  fertigation(stock=0)                -> {r}")

    try:
        K.select_pipe_diameter(10.0, 100.0, [], 5.0, 10)
        flag("BUG", "select_pipe_diameter with empty catalogue",
             "Returned silently instead of raising.")
        print("  select_pipe_diameter(catalogue=[])  -> returned (BUG)")
    except ValueError as exc:
        print(f"  select_pipe_diameter(catalogue=[])  -> raises ValueError: {exc}")

    # ------------------------------------------------------------------
    # B. Downhill laterals — pressure gain
    # ------------------------------------------------------------------
    print("\nB. Steep downhill lateral (pressure recovery)")

    res = probe("steep downhill lateral",
                lambda: K.lateral_head_loss(0.30, 13.6, 100.0, 300, 0.15, slope_pct=-8.0))
    print(f"  slope -8 %: hf={res['hf_m']:.3f} m, dZ={res['elevation_m']:+.3f} m, "
          f"total dH={res['total_dh_m']:+.3f} m")

    h_op = 10.0
    h_end = h_op - res["total_dh_m"]
    q_in = K.emitter_discharge(0.632, 0.5, h_op)
    q_end = K.emitter_discharge(0.632, 0.5, h_end)
    uni = K.lateral_uniformity(0.632, 0.5, h_op, res["hf_m"], -8.0, 100.0, 0.05)
    eu = uni["eu_pct"]
    print(f"  inlet head {h_op:.2f} m -> end head {h_end:.2f} m")
    print(f"  inlet q {q_in:.3f} L/h -> end q {q_end:.3f} L/h")
    print(f"  minimum discharge is at             -> {uni['min_at']}")
    print(f"  EU (direction-aware)                -> {eu:.2f} %")
    if eu > 100.0:
        flag("BUG", "Emission uniformity exceeds 100 % on a downhill lateral",
             f"EU returned {eu:.1f} %. On a falling lateral the LAST emitter has the "
             "HIGHEST pressure, so q_min is at the inlet, not the end. Passing "
             "(q_end, q_inlet) inverts the ratio and reports a physically impossible "
             "uniformity. A designer sees a green tick on a design that is actually "
             "over-pressured at the far end.")

    print("\n   Head-variation check in both directions:")
    dh_allow = K.allowable_head_variation(15.0, 0.5, 90.0, 0.04, 1) * 0.55
    for dh in (0.4, -0.4, 3.6, -3.6):
        c = K.head_variation_check(dh, dh_allow)
        print(f"     dH={dh:+6.2f} m vs allowable {dh_allow:.3f} m -> "
              f"within={str(c['within']):5s} direction={c['direction']:4s} "
              f"over_pressure={c['over_pressure']}")
        if dh < 0 and abs(dh) > dh_allow and c["within"]:
            flag("BUG", "Negative head variation passes the allowance check",
                 "A signed comparison passes trivially when the head variation is "
                 "negative. A negative value means the far end is at HIGHER pressure "
                 "than the inlet, which is an over-pressure condition, not a margin.")

    # ------------------------------------------------------------------
    # C. Laminar and transitional flow
    # ------------------------------------------------------------------
    print("\nC. Low-flow regimes")

    for q, label in [(0.004, "very short tape lateral"), (0.010, "short tape lateral"),
                     (0.030, "normal tape lateral")]:
        r = K.head_loss_darcy(q, 13.6, 50.0)
        print(f"  Q={q*1000:6.1f} L/h  Re={r['reynolds']:8.0f}  f={r['friction_factor']:.5f}  "
              f"regime={r['regime']}")

    r = K.head_loss_darcy(0.30, 96.8, 200.0)
    print(f"  mainline 110 mm at 300 L/h          -> Re={r['reynolds']:.0f} {r['regime']}")

    r = K.head_loss_darcy(60.0, 96.8, 200.0)
    print(f"  mainline 110 mm at 60 m3/h          -> Re={r['reynolds']:,.0f} {r['regime']}")
    if "extrapolat" in r["regime"].lower():
        flag("BUG", "Blasius extrapolated beyond its calibrated range",
             f"Mainline at Re = {r['reynolds']:,.0f} exceeds the 1e5 upper bound of the "
             "Blasius correlation, and pipe roughness is ignored entirely. Head loss on "
             "every mainline is computed outside the formula's validity. Replace with "
             "Swamee-Jain (explicit Colebrook-White approximation) with an explicit "
             "roughness for the material.")

    # ------------------------------------------------------------------
    # D. Salinity extremes
    # ------------------------------------------------------------------
    print("\nD. Salinity")

    # Drip form LR = ECw / (2 max ECe); max ECe is the ZERO-yield salinity of
    # FAO-29 Table 4 (wheat 20, tomato 13, onion 7.4 dS/m).
    for ecw, ece_max, crop in [(0.5, 20.0, "wheat"), (2.0, 13.0, "tomato"),
                               (4.0, 13.0, "tomato"), (8.0, 7.4, "onion"),
                               (20.0, 7.4, "onion")]:
        lr = K.leaching_requirement(ecw, ece_max)
        d = K.gross_depth(20.0, 0.90, lr)
        print(f"  ECw={ecw:5.1f}  max ECe={ece_max:4.1f} ({crop:6s})  LR={lr*100:5.1f} %  "
              f"gross depth={d:7.2f} mm")
    # FAO-29 eq. (9) on the threshold, used when no zero-yield value is known
    for ecw, ece_t in [(1.0, 2.7), (6.0, 2.7), (13.5, 2.7), (20.0, 2.7)]:
        lr9 = K.leaching_requirement_fao29(ecw, ece_t)
        print(f"  ECw={ecw:5.1f}  ECe threshold={ece_t:3.1f} (olive, FAO-29 eq.9)  LR={lr9*100:5.1f} %")
    if K.leaching_requirement_fao29(20.0, 2.7) != K.LR_CAP:
        flag("BUG", "FAO-29 eq. 9 with ECw >= 5 ECe is not capped",
             "Water as salty as five times the threshold cannot be leached; the "
             "equation's denominator is zero or negative and must return the cap.")
    lr_max = K.leaching_requirement(20.0, 7.4)
    print(f"  verdict at LR=0.90                  -> {K.leaching_verdict(lr_max)[0]}")
    if lr_max >= 0.89 and K.leaching_verdict(lr_max)[0] != "unsuitable":
        flag("WEAK", "Leaching requirement hits its internal cap silently",
             f"LR is clamped at 0.90 (returned {lr_max:.2f}) with no warning. At that "
             "level the crop is simply unsuitable for the water, and the program should "
             "say so rather than return a huge gross depth.")

    # ------------------------------------------------------------------
    # E. Emitter exponent extremes
    # ------------------------------------------------------------------
    print("\nE. Emitter exponent and CV extremes")

    for x in [0.0, 0.01, 0.03, 0.5, 1.0]:
        dh = K.allowable_head_variation(15.0, x, 90.0, 0.04, 1)
        print(f"  x={x:4.2f}  allowable dH={dh:6.3f} m ({100*dh/15.0:5.1f} % of head)")

    for cv in [0.02, 0.10, 0.20, 0.40]:
        eu = K.emission_uniformity(cv, 1, 0.95, 1.0)
        cls = K.cv_class(cv)
        print(f"  CV={cv:4.2f} ({cls:12s}) EU={eu:7.2f} %")
        if eu < 0:
            flag("BUG", "Negative emission uniformity",
                 f"CV={cv} returns EU={eu:.1f} %, which is meaningless. The "
                 "Keller-Karmeli expression goes negative for CV above about 0.79/sqrt(n); "
                 "the result must be floored and the input rejected.")

    dh0 = K.allowable_head_variation(15.0, 0.0, 90.0, 0.04, 1)
    if abs(dh0 - 3.0) < 1e-9:
        print("  x=0 handled by the pressure-compensating branch (20 % cap).")

    # ------------------------------------------------------------------
    # F. Wetted fraction extremes
    # ------------------------------------------------------------------
    print("\nF. Wetted fraction")

    for dw, se, sl, n in [(0.3, 2.0, 3.0, 1), (1.0, 0.3, 1.0, 1),
                          (2.0, 0.3, 1.0, 2), (1.0, 0.5, 0.4, 1)]:
        pw = K.wetted_fraction(dw, se, sl, n)
        print(f"  Dw={dw:4.1f} Se={se:4.1f} Sl={sl:4.1f} n={n} -> Pw={pw*100:6.1f} %")
    pw_clamped = K.wetted_fraction(2.0, 0.3, 1.0, 2)
    print(f"  verdict at Pw = 1.0                 -> {K.wetting_verdict(pw_clamped)[0]}")
    if pw_clamped >= 1.0 and K.wetting_verdict(pw_clamped)[0] != "saturated":
        flag("WEAK", "Wetted fraction clamps to 100 % without comment",
             "Pw is clamped to 1.0. That is correct arithmetic but hides a layout that "
             "no longer behaves as drip. The interface warns above 85 %, the kernel does not.")

    try:
        K.readily_available_water(180, 80, 0.5, 0.35, 0.0)
        raw_raised = False
        print("  RAW at Pw = 0                       -> returned (WEAK)")
    except ValueError as exc:
        raw_raised = True
        print(f"  RAW at Pw = 0                       -> raises ValueError: {exc}")
    if not raw_raised:
        flag("WEAK", "Zero wetted fraction yields a zero interval, not an error",
             "Pw = 0 gives RAW = 0 and an interval of 0 days. The UI cannot produce it, "
             "but a scripted call would propagate a division-free zero into the schedule.")

    # ------------------------------------------------------------------
    # G. Schedule feasibility extremes
    # ------------------------------------------------------------------
    print("\nG. Schedule")

    r = K.operating_hours_check(24, 3.0, 1.0, 20.0)
    print(f"  24 shifts x 3 h in 1 day            -> feasible={r['feasible']}, "
          f"utilisation={r['utilisation_pct']:.0f} %")

    try:
        K.number_of_shifts(0.0, 100.0)
        flag("BUG", "Zero available discharge silently returns one shift", "Did not raise.")
        print("  number_of_shifts(q_avail=0)         -> returned (BUG)")
    except ValueError as exc:
        print(f"  number_of_shifts(q_avail=0)        -> raises ValueError: {exc}")

    # ------------------------------------------------------------------
    # H. Pipe selection under impossible constraints
    # ------------------------------------------------------------------
    print("\nH. Pipe selection")

    cat = [K.PipeOption(50, 44.0, "PE", 6, 36.0), K.PipeOption(63, 55.4, "PE", 6, 56.0),
           K.PipeOption(75, 66.0, "PE", 6, 79.0)]
    r = K.select_pipe_diameter(200.0, 400.0, cat, 0.5, 20)
    print(f"  impossible duty -> satisfied={r['satisfied']}, "
          f"selected={r['selected'].nominal_mm:.0f} mm, v={r['hydraulics']['velocity_ms']:.2f} m/s")

    # ------------------------------------------------------------------
    # I. Water quality with missing parameters
    # ------------------------------------------------------------------
    print("\nI. Water quality")

    hz = K.clogging_hazard({})
    print(f"  empty water quality                 -> {hz['overall']}")
    hz = K.clogging_hazard({"ph": None, "iron_mg_l": 0.3})
    print(f"  None values ignored                 -> {hz['overall']}")
    hz = K.clogging_hazard({"unknown_param": 5.0})
    print(f"  unknown parameter ignored           -> {hz['overall']}")

    ph_low = K.clogging_hazard({"ph": 4.5})
    print(f"  pH 4.5 (strongly acidic)            -> {ph_low['per_parameter']['ph']['class']}, "
          f"corrosion note: {'yes' if ph_low.get('corrosion_note') else 'NO'}")
    if ph_low["per_parameter"]["ph"]["class"] == "slight" and not ph_low.get("corrosion_note"):
        flag("BUG", "Acidic water classified as slight clogging hazard",
             "The pH criterion is one-sided: any pH below 7.0 is 'slight'. pH 4.5 is "
             "corrosive to metal fittings and aggressive to some emitter polymers. The "
             "classification is correct for scaling hazard but the program presents it as "
             "an overall water-suitability class, which it is not.")

    r = K.required_filtration_mesh(0.0)
    print(f"  filtration for zero passage         -> {r}")

    # ------------------------------------------------------------------
    # J. Temperature effect
    # ------------------------------------------------------------------
    print("\nJ. Water temperature")

    for t in [5.0, 20.0, 35.0, 45.0]:
        nu = K.kinematic_viscosity(t)
        r = K.head_loss_darcy(0.30, 13.6, 70.0, nu)
        print(f"  T={t:4.1f} C  nu={nu:.3e}  Re={r['reynolds']:7.0f}  hf={r['hf_m']:.4f} m")
    hf_cold = K.head_loss_darcy(0.30, 13.6, 70.0, K.kinematic_viscosity(5.0))["hf_m"]
    hf_hot = K.head_loss_darcy(0.30, 13.6, 70.0, K.kinematic_viscosity(45.0))["hf_m"]
    print(f"  cold/hot head-loss ratio            -> {hf_cold/hf_hot:.3f}")

    # ------------------------------------------------------------------
    # K. Very long lateral
    # ------------------------------------------------------------------
    print("\nK. Very long lateral")

    for L in [50, 150, 300, 600]:
        n = int(L / 0.5)
        q = n * 4.0 / 1000.0
        r = K.lateral_head_loss(q, 13.6, float(L), n, 0.15)
        print(f"  L={L:4d} m  n={n:4d}  Q={q*1000:7.0f} L/h  v={r['velocity_ms']:6.2f} m/s  "
              f"hf={r['hf_m']:9.2f} m")
    r = K.lateral_head_loss(4.8, 13.6, 600.0, 1200, 0.15)
    print(f"  600 m lateral velocity_ok flag      -> {r['velocity_ok']}")
    if r["velocity_ms"] > 3.0 and r.get("velocity_ok", True):
        flag("WEAK", "No velocity ceiling on laterals",
             f"A 600 m lateral reaches {r['velocity_ms']:.1f} m/s with no warning. "
             "The velocity cap is applied to manifolds and mainlines only. Laterals "
             "need the same guard.")

    # ------------------------------------------------------------------
    # L. Filename safety
    # ------------------------------------------------------------------
    print("\nL. Export filename safety")
    for name in ["Project / East Delta", "مشروع: الشرقية*2026", ""]:
        safe = K.safe_filename(name)
        risky = any(c in safe for c in '/\\:*?"<>|')
        print(f"  {name!r:34s} -> {safe!r} risky={risky}")
        if risky:
            flag("BUG", "Unsafe export filename",
                 f"Project name {name!r} becomes {safe!r}. Only spaces are replaced, so "
                 "slashes and colons reach the download filename and Windows rejects or "
                 "truncates the file.")

    section_m_comparison_audit()

    # ------------------------------------------------------------------
    # Report
    # ------------------------------------------------------------------
    print("\n" + "=" * 78)
    print("FINDINGS")
    print("=" * 78)
    if not FINDINGS:
        print("  none")
    order = {"CRASH": 0, "BUG": 1, "WEAK": 2}
    for sev, name, detail in sorted(FINDINGS, key=lambda f: order.get(f[0], 9)):
        print(f"\n[{sev}] {name}")
        for lineno, chunk in enumerate(_wrap(detail, 72)):
            print(f"        {chunk}")
    print()
    print(f"Total: {len(FINDINGS)} finding(s) — "
          f"{sum(1 for f in FINDINGS if f[0]=='CRASH')} crash, "
          f"{sum(1 for f in FINDINGS if f[0]=='BUG')} bug, "
          f"{sum(1 for f in FINDINGS if f[0]=='WEAK')} weakness")
    # A crash or a bug fails the self-test; a weakness is reported only.
    return 1 if any(f[0] in ("CRASH", "BUG") for f in FINDINGS) else 0


def section_m_comparison_audit():
    """
    Section M — the numeric-comparison audit of v0.4.0.

    Every probe here reproduces a defect that the 83 tests of v0.3.1 passed
    with. The family is one comparison that reads as a safety check and
    cannot fail in the situation it was written for.
    """
    print("\nM. Numeric-comparison audit (v0.4.0)")

    sp = probe("head spread downhill", lambda: K.head_spread(2.679, -2.5, 100.0))
    if sp:
        print("  100 m lateral, hf 2.679 m, slope -2.5 %")
        print(f"    endpoint hf+dz  -> {sp['endpoint_dh_m']:+.3f} m")
        print(f"    true spread     -> {sp['spread_m']:.3f} m "
              f"(min at {sp['distance_of_min_m']:.0f} m)")
        if sp["spread_m"] <= abs(sp["endpoint_dh_m"]) * 1.5:
            flag("BUG", "head spread collapsed to the endpoint difference",
                 "The spread must exceed the endpoint difference on a falling run; "
                 "if it does not, the interior-trough treatment has been lost and "
                 "the acceptance check is back on the two ends.")

    a = probe("verdict on endpoints", lambda: K.head_variation_check(0.179, 0.685))
    b = probe("verdict on spread",
              lambda: K.head_variation_check(0.179, 0.685, spread_m=1.109))
    if a and b:
        print(f"    verdict on endpoints -> within={a['within']}")
        print(f"    verdict on spread    -> within={b['within']}")
        if b["within"]:
            flag("BUG", "spread verdict still passes",
                 "1.109 m of spread against a 0.685 m allowance must fail.")

    lat = K.head_spread(0.600, 0.0, 100.0)["spread_m"]
    man = K.head_spread(2.497, -2.5, 120.0)["spread_m"]
    print(f"  subunit: lateral spread {lat:.3f} + manifold spread {man:.3f} "
          f"= {lat+man:.3f} m, algebraic endpoint sum = {0.600-0.503:+.3f} m")
    if lat + man < 1.5:
        flag("BUG", "subunit spread cancelled",
             "The two spreads are non-negative and can only add.")

    for name, fn_ in (("EU with a NaN CV",
                       lambda: K.emission_uniformity(float("nan"), 1, 2.0, 2.0)),
                      ("Kr with a NaN ground cover",
                       lambda: K.ground_cover_reduction_factor(float("nan")))):
        try:
            v = fn_()
            flag("BUG", f"{name} returned a value",
                 f"Returned {v!r} instead of raising. Every comparison with a NaN "
                 "is False, so a clamp written max(0, min(100, x)) maps a NaN to "
                 "the BEST possible answer.")
            print(f"    {name:34s} -> {v}  <-- accepted")
        except ValueError:
            print(f"    {name:34s} -> rejected")
    v = K.head_variation_check(float("nan"), 1.0)["within"]
    print(f"    {'head variation with a NaN':34s} -> within={v}")
    if v:
        flag("BUG", "head variation accepted a NaN",
             "Use `m <= a`, which is False for a NaN and rejects it, not "
             "`not (m > a)`, which is True for a NaN and accepts it.")

    s_ = probe("25 h set against an 18 h day",
               lambda: K.operating_hours_check(1, 25.0, 3.0, 18.0))
    if s_:
        print(f"  25 h set, 18 h/day, 3 d interval -> feasible={s_['feasible']} "
              f"(cycle fits={s_['cycle_fits']}, set fits day={s_['set_fits_day']})")
        if s_["feasible"]:
            flag("BUG", "a 25 h set passed an 18 h day",
                 "The cycle total fits inside 18 x 3 = 54 h, but a set cannot be "
                 "suspended overnight and resumed.")
    s0 = probe("zero set time", lambda: K.operating_hours_check(1, 0.0, 2.0, 18.0))
    if s0 and s0["feasible"]:
        flag("BUG", "a zero set time passed as feasible",
             "A non-positive set time means the application rate is not positive "
             "— an input error, not a costless schedule.")

    p_ = probe("1200 m3/h at 50 m", lambda: K.pump_power(1200.0, 50.0, 0.72, 0.90))
    if p_:
        print(f"  brake {p_['brake_kw']:.1f} kW needs {p_['required_rating_kw']:.1f} kW "
              f"-> rating {p_['motor_rating_kw']:.0f} kW, off_scale={p_['rating_off_scale']}")
        if not p_["rating_off_scale"]:
            flag("BUG", "motor truncation not flagged",
                 "The list ran out and the caller was not told.")

    try:
        v = K.pump_power(40.0, -71.59, 0.72, 0.90)
        flag("BUG", "negative TDH produced a motor",
             f"Returned {v['motor_rating_kw']} kW for a head of -71.59 m.")
        print(f"    negative TDH -> {v['motor_rating_kw']} kW  <-- accepted")
    except ValueError:
        print("    negative TDH                       -> rejected")

    pws = [K.wetted_fraction(0.60, se, 2.0) for se in (0.599, 0.600, 0.601)]
    print(f"  Pw at Se = 0.599 / 0.600 / 0.601 with Dw 0.60 -> "
          f"{pws[0]*100:.2f} / {pws[1]*100:.2f} / {pws[2]*100:.2f} %")
    if max(abs(pws[0]-pws[1]), abs(pws[1]-pws[2])) > 1e-3:
        flag("BUG", "step in the wetted fraction at the merge point",
             "The disc and strip branches differ by 4/pi at Se = Dw, which moves "
             "Pw, the stored water and the maximum interval by 21 % across one "
             "standard dripline spacing.")

    try:
        v = K.allowable_head_variation(10.0, 0.5, 90.0, 0.11, 1)
        flag("WEAK", "unattainable EU target clamped instead of named",
             f"CV 0.11 caps EU at 86.0 %, so a 90 % target is impossible at any "
             f"pressure. Returned {v:.3f} m, after which every design fails and "
             "the advice given cannot help.")
        print(f"    CV 0.11 / EU 90 %                  -> {v:.3f} m  <-- clamped")
    except ValueError:
        print("    CV 0.11 / EU 90 %                  -> named as unattainable")

    cat = [K.PipeOption(50, 44.0, "PE", 6), K.PipeOption(63, 55.4, "PE", 6),
           K.PipeOption(75, 66.0, "PE", 6), K.PipeOption(90, 79.2, "PE", 6),
           K.PipeOption(110, 96.8, "PE", 6)]
    sel = probe("no size satisfies",
                lambda: K.select_pipe_diameter(16.0, 120.0, cat, 0.4, 20, slope_pct=-2.5))
    if sel and not sel["satisfied"]:
        largest = max(cat, key=lambda o: o.internal_mm)
        worst = K.manifold_head_loss(16.0, largest.internal_mm, 120.0, 20,
                                     slope_pct=-2.5)["spread_m"]
        print(f"  no-solution fallback -> {sel['selected'].nominal_mm:.0f} mm, "
              f"spread {sel['hydraulics']['spread_m']:.3f} m "
              f"(largest would give {worst:.3f} m)")
        if sel["hydraulics"]["spread_m"] > worst + 1e-9:
            flag("BUG", "fallback returned a worse pipe than the largest",
                 "The fallback must be the candidate with the smallest violation.")


def _wrap(text, width):
    words, line, out = text.split(), "", []
    for w in words:
        if len(line) + len(w) + 1 > width:
            out.append(line)
            line = w
        else:
            line = (line + " " + w).strip()
    if line:
        out.append(line)
    return out


if __name__ == "__main__":
    sys.exit(main())
