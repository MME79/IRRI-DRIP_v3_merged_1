"""
IRRI-DRIP — end-to-end worked example.

Runs the whole design chain through the kernels with no user interface, so
the numbers can be checked by hand and the chain can be regression-tested.

Case: 5 ha of open-field tomato on sandy loam in the Nile Delta, fed from a
canal, with inline pressure-compensating 4 L/h emitters.

Run:  python validation/worked_example.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import kernels as K


def line(t=""):
    print(t)


def sec(t):
    print()
    print(t)
    print("-" * len(t))


def main():
    # ---------------- inputs ----------------
    area_ha = 5.0
    altitude = 15.0
    q_avail = 40.0              # m3/h from the canal offtake
    static_lift = 8.0
    hours_day = 18.0

    # soil: sandy loam
    fc, wp = 180.0, 80.0        # mm/m
    zr, p = 0.50, 0.35

    # climate: peak summer month, Delta
    et0 = K.et0_penman_monteith(t_max_c=37.0, t_min_c=23.0, rh_mean_pct=48.0,
                                wind_2m_ms=2.2, rn_mj_m2_d=19.0, altitude_m=altitude)
    kc, gc = 1.15, 0.75
    kr = K.ground_cover_reduction_factor(gc)
    etc = K.etc_localised(et0, kc, kr)

    ea = 0.90
    # Tomato, FAO-29 Rev.1 Table 4: ECe 2.5 dS/m at 100 % yield, 13 dS/m at 0 %.
    # The drip leaching requirement takes the ZERO-yield value (v2.0.0 took
    # the threshold, which gave LR = 24 % here instead of 4.6 %).
    ecw, ece, ece_max = 1.2, 2.5, 13.0
    lr = K.leaching_requirement(ecw, ece_max)

    sec("1. Crop water requirement (FAO-56, localised)")
    line(f"ET0 peak                     = {et0:8.3f} mm/day")
    line(f"Kc                           = {kc:8.3f}")
    line(f"Ground cover                 = {gc:8.2f}")
    line(f"Kr (Keller & Bliesner)       = {kr:8.3f}")
    line(f"ETc localised                = {etc:8.3f} mm/day")
    line(f"ECw                          = {ecw} dS/m")
    line(f"ECe threshold / at zero yield= {ece} / {ece_max} dS/m  (FAO-29 Table 4)")
    line(f"Leaching requirement LR      = {lr*100:8.1f} %   = ECw / (2 max ECe)   "
         f"({'applied' if lr > 0.1 else 'absorbed by Ea, not applied'})")

    # ---------------- emitter ----------------
    k_em, x_em, cv = 3.734, 0.03, 0.04       # inline PC 4 L/h
    h_op = 15.0
    q_em = K.emitter_discharge(k_em, x_em, h_op)
    se, sl, dw = 0.50, 1.40, 1.00
    pw = K.wetted_fraction(dw, se, sl, 1)
    ia = K.application_rate(q_em, se, sl)
    emitters_per_ha = 10000.0 / (se * sl)
    n_total = emitters_per_ha * area_ha
    q_full = n_total * q_em / 1000.0

    sec("2. Emitter and wetting")
    line(f"Emitter q = k*H^x            = {q_em:8.3f} L/h at {h_op} m")
    line(f"Exponent x                   = {x_em:8.3f}  ({'pressure compensating' if x_em <= 0.15 else 'pressure sensitive'})")
    line(f"CV {cv:.3f}                      -> class: {K.cv_class(cv)}")
    line(f"Spacing Se x Sl              = {se} x {sl} m")
    line(f"Wetted fraction Pw           = {pw*100:8.1f} %")
    line(f"Application rate Ia          = {ia:8.3f} mm/h")
    line(f"Emitters, whole field        = {n_total:8.0f}")
    line(f"Flow if all run at once      = {q_full:8.2f} m3/h  (source {q_avail} m3/h)")

    # ---------------- operation ----------------
    raw = K.readily_available_water(fc, wp, zr, p, pw)
    raw_full = K.readily_available_water(fc, wp, zr, p, 1.0)
    imax = K.irrigation_interval(raw, etc)
    interval = 1.0
    d_net = etc * interval
    d_gross = K.gross_depth(d_net, ea, lr)
    t_set = K.set_time(d_gross, ia)
    shifts = K.number_of_shifts(q_avail, q_full)
    sched = K.operating_hours_check(shifts, t_set, interval, hours_day)
    q_shift = q_full / shifts

    sec("3. Operational design")
    line(f"RAW at Pw = {pw*100:.0f} %           = {raw:8.2f} mm")
    line(f"RAW if fully wetted          = {raw_full:8.2f} mm   <-- what a sprinkler kernel would give")
    line(f"Maximum interval             = {imax:8.2f} days")
    line(f"Chosen interval              = {interval:8.2f} days")
    line(f"Net depth                    = {d_net:8.2f} mm")
    line(f"Gross depth                  = {d_gross:8.2f} mm")
    line(f"Set time                     = {t_set:8.2f} h")
    line(f"Shifts                       = {shifts:8d}")
    line(f"Flow per shift               = {q_shift:8.2f} m3/h")
    line(f"Schedule feasible            = {str(sched['feasible']):>8}   "
         f"({sched['required_h_per_cycle']:.1f} h needed / {sched['available_h_per_cycle']:.1f} h available)")

    # ---------------- lateral ----------------
    # 65 m, not 70. Under the hard-coded velocity exponent m = 2 of versions
    # up to 0.4.0 a 70 m run computed 4.03 m of head spread against a 4.125 m
    # allowance and passed by 2 %. With the exponent measured from the
    # friction factor (m = 1.75 on a smooth PE dripline) the same run computes
    # 4.25 m and fails by 3 %. It was never a passing design; it was passing
    # on an understated number. Shortening the run to 65 m is the cheaper of
    # the two real fixes — the other is stepping the lateral up to 20 mm.
    l_len, d_lat, le = 65.0, 13.6, 0.20
    nu = K.kinematic_viscosity(28.0)
    n_em_lat = int(round(l_len / se))
    q_lat = n_em_lat * q_em / 1000.0
    res = K.lateral_head_loss(q_lat, d_lat, l_len, n_em_lat, le, slope_pct=0.0, nu=nu)

    eu_target = 90.0
    dh_sub = K.allowable_head_variation(h_op, x_em, eu_target, cv, 1)
    dh_lat_allow = dh_sub * 0.55
    uni = K.lateral_uniformity(k_em, x_em, h_op, res["hf_m"], 0.0, l_len, cv,
                               exponent=res["velocity_exponent"])
    h_min, q_min, eu = uni["h_end_m"], uni["q_min_lph"], uni["eu_pct"]

    # what an uncorrected sprinkler-style calculation would have reported
    res_no_local = K.lateral_head_loss(q_lat, d_lat, l_len, n_em_lat, 0.0, 0.0, nu)

    sec("4. Lateral hydraulics (Darcy-Weisbach + Swamee-Jain)")
    line(f"Emitters per lateral         = {n_em_lat:8d}")
    line(f"Lateral inlet flow           = {q_lat*1000:8.1f} L/h")
    line(f"Velocity                     = {res['velocity_ms']:8.4f} m/s")
    line(f"Reynolds number              = {res['reynolds']:8.0f}")
    line(f"Flow regime                  = {res['regime']}")
    line(f"Friction factor f            = {res['friction_factor']:8.5f}")
    line(f"Christiansen F (m = 2)       = {res['F']:8.4f}")
    line(f"Equivalent length            = {res['equivalent_length_m']:8.2f} m "
         f"(physical {l_len:.0f} m + emitter barbs)")
    line(f"Emitter local-loss share     = {res['local_loss_share_pct']:8.1f} %")
    line(f"Lateral head loss            = {res['hf_m']:8.4f} m")
    line(f"  ... ignoring emitter barbs = {res_no_local['hf_m']:8.4f} m   <-- understated by "
         f"{100*(1-res_no_local['hf_m']/res['hf_m']):.0f} %")
    line(f"Allowable lateral dH         = {dh_lat_allow:8.4f} m")
    line(f"Head at last emitter         = {h_min:8.3f} m")
    line(f"Discharge at last emitter    = {uni['q_end_lph']:8.3f} L/h  (inlet {q_em:.3f} L/h)")
    line(f"Minimum discharge is at      = {uni['min_at']:>8s}")
    line(f"Emission uniformity EU       = {eu:8.2f} %   (target {eu_target:.0f} %)")

    # ---------------- water quality ----------------
    wq = {"suspended_solids_mg_l": 65.0, "dissolved_solids_mg_l": 420.0, "ph": 7.9,
          "iron_mg_l": 0.35, "manganese_mg_l": 0.06,
          "hydrogen_sulphide_mg_l": 0.1, "bacterial_population_per_ml": 22000.0}
    hz = K.clogging_hazard(wq)
    rec = K.recommend_filtration("Nile canal", hz["overall"], 0.80)
    sched_chem = K.chemical_maintenance_schedule(hz)

    sec("5. Water quality, clogging hazard and filtration")
    for key, item in hz["per_parameter"].items():
        line(f"  {key:32s} {item['value']:>10}  {item['class']}")
    line(f"Governing hazard             = {hz['overall'].upper()}")
    line(f"Filtration aperture          = {rec['filtration_grade']['aperture_micron']:8.0f} micron "
         f"(~mesh {rec['filtration_grade']['mesh']})")
    line("Filtration train             = " + " -> ".join(rec["train"]))
    line("Chemical maintenance:")
    for a in sched_chem:
        line(f"  - {a['treatment']:16s} {a['frequency']}")

    # ---------------- manifold, mainline, pump ----------------
    n_lat_per_manifold = 25
    q_man = n_lat_per_manifold * q_lat
    cat = [K.PipeOption(50, 44.0, "PE", 6, 36.0), K.PipeOption(63, 55.4, "PE", 6, 56.0),
           K.PipeOption(75, 66.0, "PE", 6, 79.0), K.PipeOption(90, 79.2, "PE", 6, 113.0),
           K.PipeOption(110, 96.8, "PE", 6, 168.0)]
    man_sel = K.select_pipe_diameter(q_man, n_lat_per_manifold * sl, cat,
                                     dh_sub * 0.45, n_lat_per_manifold, 2.0, 0.0, nu)
    man_res = man_sel["hydraulics"]
    main_sel = K.select_pipe_diameter(q_shift, 250.0, cat, 1e9, 1, 1.8, 0.0, nu)
    main_res = K.head_loss_darcy(q_shift, main_sel["selected"].internal_mm, 250.0, nu)

    tdh = K.total_dynamic_head(static_lift, h_op, res["total_dh_m"], man_res["total_dh_m"],
                               main_res["hf_m"], 3.0, 4.0, 0.10, 6.0)
    power = K.pump_power(q_shift, tdh["tdh_m"], 0.72, 0.90)

    sec("6. Manifold, mainline and pump")
    line(f"Manifold flow                = {q_man:8.2f} m3/h")
    line(f"Manifold selected            = {man_sel['selected'].nominal_mm:.0f} mm "
         f"{man_sel['selected'].material} (satisfied: {man_sel['satisfied']})")
    line(f"Manifold velocity / dH       = {man_res['velocity_ms']:.3f} m/s / {man_res['total_dh_m']:.3f} m")
    line(f"Mainline selected            = {main_sel['selected'].nominal_mm:.0f} mm "
         f"{main_sel['selected'].material}")
    line(f"Mainline velocity / hf       = {main_res['velocity_ms']:.3f} m/s / {main_res['hf_m']:.3f} m")
    line(f"Subunit total dH             = {res['total_dh_m'] + man_res['total_dh_m']:8.3f} m "
         f"(allowable {dh_sub:.3f} m)")
    line("TDH breakdown:")
    for kk, vv in tdh.items():
        if kk != "tdh_m":
            line(f"  {kk:24s} {vv:8.3f} m")
    line(f"TOTAL DYNAMIC HEAD           = {tdh['tdh_m']:8.3f} m")
    line(f"  of which filtration        = {100*tdh['filter_m']/tdh['tdh_m']:8.1f} %")
    line(f"Duty discharge               = {q_shift:8.2f} m3/h")
    line(f"Hydraulic / brake power      = {power['hydraulic_kw']:.2f} / {power['brake_kw']:.2f} kW")
    line(f"Motor rating                 = {power['motor_rating_kw']:8.1f} kW")

    sec("Design checks")
    checks = [
        ("Schedule fits operating hours", sched["feasible"]),
        # Spread, not the end-to-end difference; and the subunit is the SUM of
        # the two spreads, not the algebraic sum of the two endpoint values.
        ("Lateral head spread within allowable", res["spread_m"] <= dh_lat_allow),
        ("EU meets target", eu >= eu_target),
        ("Subunit head spread within allowable",
         res["spread_m"] + man_res["spread_m"] <= dh_sub),
        ("Manifold velocity <= 2.0 m/s", man_res["velocity_ms"] <= 2.0),
        ("Mainline velocity <= 1.8 m/s", main_res["velocity_ms"] <= 1.8),
        ("Lateral in a reliable flow regime", "uncertain" not in res["regime"]),
        ("Lateral velocity within limit", res["velocity_ok"]),
        ("Pw between 20 % and 85 %", 0.20 <= pw <= 0.85),
        ("LR from the zero-yield ECe (FAO-29 Table 4), hand value 1.2/26",
         abs(lr - 1.2 / 26.0) < 1e-12),
        ("Gross depth = net / Ea when LR <= 0.10", abs(d_gross - d_net / ea) < 1e-9),
    ]
    for label, ok in checks:
        line(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    n_fail = sum(1 for _, ok in checks if not ok)
    line()
    line(f"{len(checks) - n_fail}/{len(checks)} checks passed.")
    return n_fail


if __name__ == "__main__":
    sys.exit(0 if main() == 0 else 1)
