"""
The design checks, UI-free.

Version 1 built this list inside the report page, where the only way to test
it was to render a complete design; the export defect of v0.8.2 lived there
for exactly that reason. The list now lives here and the page calls it.

Each check is (name, passed, measured, criterion). A check whose inputs are
missing is reported as a FAILED check with "not computed" as its measured
value — an absent result is not a pass.
"""

from __future__ import annotations

from . import kernels as K
from . import pumps as P
from . import state as STATE

__all__ = ["design_checks"]


def _g(d, *path, default=None):
    for k in path:
        if not isinstance(d, dict) or k not in d:
            return default
        d = d[k]
    return d


def design_checks(S: dict) -> list[tuple]:
    setup, wat, em = S.get("setup", {}), S.get("water", {}), S.get("emitter", {})
    op, lat, man = S.get("operation", {}), S.get("lateral", {}), S.get("manifold", {})
    pump = S.get("pump", {})
    sched = op.get("schedule", {})
    res = lat.get("res", {})
    checks = []

    def add(name, ok, measured, criterion):
        checks.append((name, bool(ok), measured, criterion))

    stale = STATE.stale_stages(S)
    add("Every saved result follows from the current inputs", not stale,
        ("out of date: " + ", ".join(sorted({STATE.STAGE_LABELS.get(k, k) for k in stale})))
        if stale else "all current", "no input changed after a page was saved")
    hy = S.get("hydraulic", {})
    q_avail = float(setup.get("q_avail", 0) or 0)
    q_duty = float(hy.get("q_duty", pump.get("q_duty_required", 0)) or 0)
    add("Design flow within the available source discharge",
        q_avail > 0 and q_duty <= q_avail * 1.001,
        f"{q_duty:.1f} m³/h largest shift", f"≤ {q_avail:.1f} m³/h available")
    if op.get("interval"):
        wb = K.water_balance(q_avail, float(setup.get("hours_day", 0) or 0),
                             op.get("d_gross", 0.0) / op["interval"],
                             sum(s.get("area_ha", 0.0) for s in op.get("subunits", [])))
        add("Source supplies the peak daily demand", wb["ok"],
            f"{wb['supply_m3_day']:,.0f} m³/day supplied",
            f"≥ {wb['demand_m3_day']:,.0f} m³/day needed")
    else:
        add("Source supplies the peak daily demand", False, "not computed",
            "supply ≥ peak daily demand")
    add("Schedule: cycle fits the operating window", sched.get("cycle_fits", False),
        f"{sched.get('required_h_per_cycle', 0):.2f} h per cycle",
        f"≤ {sched.get('available_h_per_cycle', 0):.2f} h available")
    add("Schedule: one set fits a working day", sched.get("set_fits_day", False),
        f"{sched.get('set_time_h', 0):.2f} h per set",
        f"≤ {sched.get('max_hours_per_day', 0):.1f} h/day")
    add("Interval within what RAW supports", op.get("interval_ok", False),
        f"{op.get('interval', 0):.2f} days chosen", f"≤ {op.get('interval_max', 0):.2f} days")
    longest = max((s["max_run_m"] for s in op.get("subunits", [])), default=0.0)
    add("Longest lateral on the field is the one checked",
        lat.get("l_len", 0.0) + 1e-6 >= longest,
        f"checked {lat.get('l_len', 0):.1f} m", f"≥ longest row {longest:.1f} m")
    dh = lat.get("dh_check", {})
    add("Lateral head spread within allowable", dh.get("within", False),
        f"{res.get('spread_m', float('nan')):.3f} m spread",
        f"≤ {lat.get('dh_allow_lateral', 0):.3f} m")
    add("Emission uniformity meets target", lat.get("eu", 0) >= lat.get("eu_target", 100),
        f"EU = {lat.get('eu', 0):.1f} %", f"≥ {lat.get('eu_target', 0):.0f} %")
    add("Lateral flow in a reliable regime", "uncertain" not in str(res.get("regime", "uncertain")),
        str(res.get("regime", "not computed")), "not transitional")
    add("Lateral velocity within limit", res.get("velocity_ok", False),
        f"{res.get('velocity_ms', 0):.2f} m/s", f"≤ {K.LATERAL_V_MAX_MS:.2f} m/s")
    add("Positive pressure along the whole lateral",
        not _g(lat, "uniformity", "negative_pressure", default=True),
        f"minimum head {_g(lat, 'uniformity', 'h_min_m', default=0):.2f} m", "> 0")
    designs = man.get("designs") or {}
    n_bad = sum(1 for d in designs.values() if not d.get("satisfied"))
    add("Every manifold within its allowable spread", bool(designs) and n_bad == 0,
        f"{len(designs) - n_bad} of {len(designs)} within", f"≤ {man.get('dh_allow_manifold', 0):.3f} m")
    sub = man.get("subunit_check", {})
    add("Governing subunit head spread within allowable", sub.get("within", False),
        f"{man.get('subunit_spread', float('nan')):.3f} m",
        f"≤ {lat.get('dh_allow_subunit', 0):.3f} m")
    add("Manifold velocity within limit", _g(man, "m_res", "velocity_ms", default=9) <= 2.0 + 1e-9,
        f"{_g(man, 'm_res', 'velocity_ms', default=0):.2f} m/s", "≤ 2.00 m/s")
    add("Mainline and submains within velocity and gradient limits",
        man.get("mainline_ok", False),
        f"max v {_g(man, 'main_res', 'velocity_ms', default=0):.2f} m/s",
        f"≤ {man.get('main_vmax', 1.5):.2f} m/s, J ≤ {man.get('main_jmax', 1.5):.1f} m/100 m")
    add("Every subunit valve reached by the network",
        bool(S.get("network")) and len(man.get("tree_paths", {})) == len(op.get("subunits", [])),
        f"{len(man.get('tree_paths', {}))} reached", f"= {len(op.get('subunits', []))} valves")
    add("Pump delivers the duty on the system curve", pump.get("qualifies", False),
        f"{_g(pump, 'operating_point', 'q_m3h', default=0):.1f} m³/h at the operating point",
        f"≥ {pump.get('q_duty_required', 0):.1f} m³/h")
    add("Pump operates in its preferred region", pump.get("in_por", False),
        f"Q/Q_BEP = {_g(pump, 'operating_point', 'bep_ratio', default=0):.2f}",
        f"{P.POR_LOW:.2f}–{P.POR_HIGH:.2f}")
    add("Motor rating on the standard list",
        not _g(pump, "power", "rating_off_scale", default=True),
        f"{_g(pump, 'power', 'required_rating_kw', default=0):.1f} kW required",
        f"≤ {_g(pump, 'power', 'motor_rating_kw', default=0):.0f} kW available")
    add("Wetted fraction within the accepted range", 0.20 <= em.get("pw", 0) <= 0.85,
        f"Pw = {em.get('pw', 0)*100:.1f} %", "20 % to 85 %")
    add("Leaching requirement below unsuitable threshold",
        wat.get("lr", 1.0) < K.LR_UNSUITABLE,
        f"LR = {wat.get('lr', 0)*100:.1f} %", f"< {K.LR_UNSUITABLE*100:.0f} %")
    return checks
