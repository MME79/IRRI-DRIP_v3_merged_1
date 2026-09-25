"""
Pipe Network Design — OpenIrri's tabs (line, lateral, submain, mainline,
summary) for drip: Lateral Design, Manifold Design, Mainline Design, Network
Summary. Each design tab has OpenIrri's four views: Visual Diagram,
Performance Analysis, Detailed Table, Advisory.

What is sized here
------------------
* The lateral: Darcy–Weisbach / Swamee–Jain with the measured velocity
  exponent, judged on the head SPREAD over the whole line (v1 method, kept).
* Every manifold: marched outlet by outlet with its real row flows and
  telescoped in up to three sizes against the manifold's share of the
  subunit allowance.
* The mainline and submains: the drawn tree, each pipe for the largest flow
  it carries in any shift, then solved shift by shift for the head required
  at the source and the surplus at every valve.
"""

from __future__ import annotations

import json
import math

import pandas as pd
import streamlit as st

from engine import kernels as K
from engine import network as N
from engine import fieldnet as FN
from modules import plots as PL
from modules.common import (page_header, sub_header, section, cards, banner, note,
                            caption, save, stage_guard, goto, dev_panel, context_strip,
                            verdict)

VIEWS = ["📊 Visual Diagram", "📈 Performance Analysis", "📋 Detailed Table", "💡 Advisory"]


@st.cache_data(show_spinner=False, max_entries=64)
def _telescope_cached(branches_json: str, cat_json: str, allowable: float, v_max: float,
                      slopes: tuple, max_sizes: int, nu: float) -> dict:
    branches = [[tuple(o) for o in br] for br in json.loads(branches_json)]
    cat = N.pipe_catalogue(json.loads(cat_json))
    return N.telescoped_manifold(branches, cat, allowable, v_max, list(slopes), nu, max_sizes,
                                 inlet_outlet=True)


def _inlet_index(feeds, valve_xy):
    return min(range(len(feeds)), key=lambda i: math.hypot(feeds[i][0] - valve_xy[0],
                                                           feeds[i][1] - valve_xy[1]))


def show(ctx):
    S = ctx["S"]
    page_header("Pipe Network Design",
                "Size the lateral, every manifold (telescoped) and the mainline tree. "
                "Head loss is Darcy–Weisbach with the Swamee–Jain friction factor for "
                "every pipe from the 16 mm dripline to the mainline.")
    if not stage_guard(S, "network", "Pipe Network Layout", page_key="network"):
        return
    context_strip(S)
    setup, em, op, net = S["setup"], S["emitter"], S["operation"], S["network"]
    prev_l = S.get("lateral", {})
    prev_m = S.get("manifold", {})

    tabs = st.tabs(["Lateral Design", "Manifold Design", "Mainline Design",
                    "Network Summary"])

    # ================================================================ LATERAL
    with tabs[0]:
        lat = _lateral_tab(S, ctx, prev_l)
    if lat is None:
        return

    # =============================================================== MANIFOLD
    with tabs[1]:
        man = _manifold_tab(S, ctx, prev_m, lat)
    if man is None:
        return

    # =============================================================== MAINLINE
    with tabs[2]:
        main = _mainline_tab(S, ctx, prev_m, lat, man)
    if main is None:
        return

    # ================================================================ SUMMARY
    with tabs[3]:
        _summary_tab(S, lat, man, main)

    st.markdown("---")
    ok_all = (lat["dh_check"]["within"] and man["all_satisfied"] and main["all_ok"])
    c1, c2 = st.columns([3, 1])
    with c1:
        if ok_all:
            st.success("✅ Lateral, manifolds and mainline all within their limits.")
        else:
            st.warning("⚠️ Design needs adjustment — see the Advisory views.")
    with c2:
        if st.button("💾 Save", type="primary", key="save_design", width="stretch"):
            _save(S, lat, man, main)
            st.success("✅ Pipe network design saved.")
            goto("quality")
    dev_panel(S, "manifold")


# ---------------------------------------------------------------------------
# Lateral
# ---------------------------------------------------------------------------

def _lateral_tab(S, ctx, prev):
    setup, em, op = S["setup"], S["emitter"], S["operation"]
    sub_header("Lateral (Dripline) Design")
    lat_cat = ctx["pipes"]["laterals"]
    labels = [f"{p['nominal_mm']:.0f} mm (ID {p['internal_mm']:.1f}, PN{p['pn_bar']:g})"
              for p in lat_cat]
    longest = max(s["max_run_m"] for s in op["subunits"])
    c1, c2, c3 = st.columns(3)
    with c1:
        l_len = st.number_input("Lateral length checked (m)", 1.0, 1000.0,
                                float(prev.get("l_len", round(longest, 1))), 1.0,
                                help=f"The longest run on the field is {longest:.1f} m — "
                                     "the governing lateral")
    with c2:
        li = st.selectbox("Lateral pipe", labels,
                          index=prev.get("l_idx", em.get("l_idx", 0)))
        lat = lat_cat[labels.index(li)]
    with c3:
        le = st.number_input("Emitter local loss le (m)", 0.0, 1.0,
                             float(prev.get("le", em.get("le_m", 0.15))), 0.01, format="%.3f")
    c1, c2, c3 = st.columns(3)
    with c1:
        slope = st.number_input("Slope along lateral (%) — positive uphill", -15.0, 15.0,
                                float(prev.get("slope", setup.get("slope", 0.0))), 0.1)
    with c2:
        temp = st.number_input("Water temperature (°C)", 1.0, 45.0,
                               float(prev.get("temp", 25.0)), 1.0)
    with c3:
        mode = st.selectbox("Velocity exponent m", ["measured", "conventional"],
                            index=["measured", "conventional"].index(prev.get("exponent_mode",
                                                                              "measured")),
                            format_func=lambda m: {"measured": "Measured from f (default)",
                                                   "conventional": "Conventional m = 2"}[m])
    nu = K.kinematic_viscosity(temp)
    rough = K.ROUGHNESS_MM.get(str(lat.get("material", "PE")).upper(), 0.007)
    n_em = max(1, int(round(l_len / em["se"])))
    q_lat = n_em * em["q_emitter"] / 1000.0
    res = K.lateral_head_loss(q_lat, lat["internal_mm"], l_len, n_em, le, slope, nu, rough,
                              exponent_mode=mode)
    dh_sub = em["dh_allow_subunit"]
    share = em["share"]
    dh_lat = dh_sub * share
    uni = K.lateral_uniformity(em["k"], em["x"], em["h_op"], res["hf_m"], slope, l_len,
                               em["cv"], exponent=res["velocity_exponent"])
    dh_check = K.head_variation_check(res["total_dh_m"], dh_lat, spread_m=res["spread_m"])
    eu = uni["eu_pct"]
    lat_in_req = em["h_op"] + max(0.0, uni["h_inlet_m"] - uni["h_min_m"])

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Head spread", f"{res['spread_m']:.3f} m",
                  f"allowable {dh_lat:.3f} m", delta_color="off")
    with c2:
        st.metric("EU achieved", f"{eu:.1f} %", f"target {em['eu_target']:.0f} %",
                  delta_color="off")
    with c3:
        st.metric("Inlet head required", f"{lat_in_req:.2f} m")
    with c4:
        if dh_check["within"] and eu >= em["eu_target"] and res["velocity_ok"]:
            st.success("✅ Lateral OK")
        else:
            st.warning("⚠️ Lateral needs adjustment")

    views = st.tabs(VIEWS)
    with views[0]:
        st.markdown("##### Lateral line — pressure and discharge profile")
        st.plotly_chart(PL.lateral_profile(uni, em["h_op"], dh_lat, em["q_emitter"], l_len),
                        width="stretch", key="lat_prof")
    with views[1]:
        rows = []
        for L in [l_len * f for f in (0.5, 0.75, 1.0, 1.25, 1.5, 2.0)]:
            n = max(1, int(round(L / em["se"])))
            r = K.lateral_head_loss(n * em["q_emitter"] / 1000.0, lat["internal_mm"], L, n,
                                    le, slope, nu, rough, exponent_mode=mode)
            u = K.lateral_uniformity(em["k"], em["x"], em["h_op"], r["hf_m"], slope, L,
                                     em["cv"], exponent=r["velocity_exponent"])
            rows.append({"Length (m)": round(L, 1), "Emitters": n,
                         "v (m/s)": round(r["velocity_ms"], 3),
                         "Spread (m)": round(r["spread_m"], 3), "EU (%)": round(u["eu_pct"], 1),
                         "Within allowable": "yes" if (r["spread_m"] <= dh_lat
                                                       and r["velocity_ok"]) else "no"})
        st.markdown("##### Sensitivity to lateral length")
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        cards([("Reynolds", f"{res['reynolds']:,.0f}", "", "neutral"),
               ("Regime", res["regime"], "", "warn" if "uncertain" in res["regime"] else "ok"),
               ("Christiansen F", f"{res['F']:.3f}", f"m = {res['velocity_exponent']:.3f}",
                "neutral"),
               ("Barb loss share", f"{res['local_loss_share_pct']:.1f}", "%", "neutral")])
    with views[2]:
        st.dataframe(pd.DataFrame([{"Distance (m)": round(p["distance_m"], 1),
                                    "Head (m)": round(p["head_m"], 3),
                                    "Discharge (L/h)": round(p["q_lph"], 3)}
                                   for p in uni["profile"]]), hide_index=True, width="stretch")
    with views[3]:
        verdict(dh_check["within"],
                f"Lateral head spread {res['spread_m']:.3f} m is within the allowable "
                f"{dh_lat:.3f} m.",
                f"Lateral head spread {res['spread_m']:.3f} m exceeds the allowable "
                f"{dh_lat:.3f} m. Shorten the lateral (lower the design run on Operational "
                "Design), use a larger dripline, feed from the middle, or move to a "
                "pressure-compensating emitter.")
        verdict(eu >= em["eu_target"], f"EU {eu:.1f} % meets the target.",
                f"EU {eu:.1f} % falls short of the {em['eu_target']:.0f} % target.")
        verdict(res["velocity_ok"], f"Velocity {res['velocity_ms']:.2f} m/s within the limit.",
                f"Velocity {res['velocity_ms']:.2f} m/s exceeds the "
                f"{res['velocity_limit_ms']:.1f} m/s limit.")
        gap = 100.0 * (res["hf_measured_m"] - res["hf_conventional_m"]) / max(
            res["hf_conventional_m"], 1e-9)
        note(f"<b>Velocity exponent.</b> Friction loss {res['hf_measured_m']:.3f} m at the "
             f"measured m, {res['hf_conventional_m']:.3f} m at the conventional m = 2.0 "
             f"({gap:+.1f} %). Both are reported because a reviewer checking against a "
             "textbook will compute the second.")
        if uni["min_is_interior"]:
            banner("warn", f"The governing emitter is {uni['distance_of_min_m']:.1f} m along "
                           "the lateral, not at either end: head dips and recovers.")
        if uni["negative_pressure"]:
            banner("bad", "Minimum head along the lateral is not positive — the line cannot "
                          "deliver water over its full length.")
        over = [s["id"] for s in op["subunits"] if s["max_run_m"] > l_len + 1e-6]
        if over:
            banner("bad", f"{len(over)} subunit(s) have rows longer than the {l_len:.1f} m "
                          f"checked here: {', '.join(over[:8])}. Check the longest run.")
    return {"l_len": l_len, "l_idx": labels.index(li), "lateral": lat, "le": le,
            "slope": slope, "eu_target": em["eu_target"], "temp": temp, "nu": nu,
            "n_em": n_em, "q_lat": q_lat, "res": res, "share": share,
            "dh_allow_subunit": dh_sub, "dh_allow_lateral": dh_lat, "eu": eu,
            "q_min": uni["q_min_lph"], "q_avg": uni["q_avg_lph"], "uniformity": uni,
            "roughness_mm": rough, "dh_check": dh_check, "exponent_mode": mode,
            "lateral_inlet_required_m": lat_in_req}


# ---------------------------------------------------------------------------
# Manifolds
# ---------------------------------------------------------------------------

def _manifold_tab(S, ctx, prev, lat):
    setup, em, op, net = S["setup"], S["emitter"], S["operation"], S["network"]
    sub_header("Manifold (Submain) Design — telescoped")
    cat_rows = ctx["pipes"]["pipes"]
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        mats = st.multiselect("Materials", sorted({p["material"] for p in cat_rows}),
                              default=prev.get("man_materials", ["PE"]))
    with c2:
        v_max = st.number_input("Velocity limit (m/s)", 0.5, 3.0,
                                float(prev.get("man_vmax", 2.0)), 0.1)
    with c3:
        max_sizes = st.number_input("Maximum sizes per manifold", 1, 4,
                                    int(prev.get("man_max_sizes", 3)), 1)
    with c4:
        use_leftover = st.checkbox("Give the manifold what the lateral leaves unused",
                                   value=prev.get("man_leftover", True),
                                   help="The subunit allowance is shared; if the lateral "
                                        "uses less than its share, the manifold may use "
                                        "the rest.")
    rows = [p for p in cat_rows if p["material"] in (mats or ["PE"])]
    if not rows:
        banner("bad", "Select at least one material.")
        return None
    dh_sub = em["dh_allow_subunit"]
    allow = dh_sub * (1.0 - em["share"])
    if use_leftover:
        allow = max(allow, dh_sub - lat["res"]["spread_m"])
    s_across = float(setup.get("slope_across", 0.0))
    cat_json = json.dumps(rows, sort_keys=True)
    valves = {v["id"]: v["xy"] for v in net["valves"]}
    designs = {}
    for su in op["subunits"]:
        mf = next(m for m in net["manifolds"] if m["subunit"] == su["id"])
        k = _inlet_index(mf["points"], valves.get(su["id"], mf["points"][mf["inlet_index"]]))
        brs = N.manifold_branches(mf["points"], su["outlets"], k)
        slopes = tuple([s_across] + ([-s_across] if len(brs) > 1 else []))
        if len(brs) == 1 and k != 0:
            slopes = (-s_across,)
        d = _telescope_cached(json.dumps(brs), cat_json, float(allow), float(v_max),
                              slopes, int(max_sizes), float(lat["nu"]))
        d["inlet_index"] = k
        d["valve_head_m"] = lat["lateral_inlet_required_m"] + d["inlet_minus_min_m"]
        designs[su["id"]] = d
    ids = list(designs)
    crit = max(ids, key=lambda i: designs[i]["spread_m"] - designs[i]["allowable_spread_m"])
    all_ok = all(d["satisfied"] for d in designs.values())

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Allowable manifold spread", f"{allow:.3f} m")
    with c2:
        st.metric("Manifolds within limit", f"{sum(d['satisfied'] for d in designs.values())}"
                                            f" / {len(designs)}")
    with c3:
        st.metric("Telescoped cost (EGP)", f"{sum(d['cost'] for d in designs.values()):,.0f}",
                  f"single size {sum(d['single_size_cost'] for d in designs.values()):,.0f}",
                  delta_color="off")
    with c4:
        if all_ok:
            st.success("✅ All manifolds OK")
        else:
            st.warning("⚠️ Some manifolds need adjustment")

    pick = st.selectbox("Manifold to inspect", ids, index=ids.index(crit),
                        format_func=lambda i: f"{i} — spread {designs[i]['spread_m']:.3f} m"
                                              f"{' (critical)' if i == crit else ''}")
    d = designs[pick]
    su = next(s for s in op["subunits"] if s["id"] == pick)
    views = st.tabs(VIEWS)
    with views[0]:
        st.markdown(f"##### Manifold {pick} — variable pipe sizing diagram")
        st.plotly_chart(PL.pipe_sizing_diagram(d["runs"]), width="stretch", key="man_diag")
        st.plotly_chart(PL.march_profile(d, allow), width="stretch", key="man_prof")
    with views[1]:
        segs = [s for br in d["branches"] for s in br["segments"]]
        st.plotly_chart(PL.segment_performance(segs), width="stretch", key="man_perf")
        cards([("Spread", f"{d['spread_m']:.3f}", "m", "ok" if d["satisfied"] else "bad"),
               ("Friction", f"{d['friction_m']:.3f}", "m", "neutral"),
               ("Max velocity", f"{d['max_velocity_ms']:.2f}", "m/s",
                "ok" if d["max_velocity_ms"] <= v_max else "bad"),
               ("Valve outlet head", f"{d['valve_head_m']:.2f}", "m", "accent")])
    with views[2]:
        st.dataframe(pd.DataFrame([{
            "Branch": r["branch"], "From (m)": round(r["from_m"], 1),
            "To (m)": round(r["to_m"], 1), "Length (m)": round(r["length_m"], 1),
            "Pipe": f"{r['pipe']['nominal_mm']:.0f} mm {r['pipe']['material']} PN{r['pipe']['pn_bar']:g}",
            "ID (mm)": r["pipe"]["internal_mm"], "Q in (m³/h)": round(r["q_in_m3h"], 2),
            "v max (m/s)": round(r["velocity_max_ms"], 2), "hf (m)": round(r["hf_m"], 3),
            "Cost (EGP)": round(r["length_m"] * r["pipe"]["price"])} for r in d["runs"]]),
            hide_index=True, width="stretch")
        st.markdown("##### All manifolds")
        st.dataframe(pd.DataFrame([{
            "Subunit": i, "Length (m)": round(designs[i]["length_m"], 1),
            "Sizes": " → ".join(f"{r['pipe']['nominal_mm']:.0f}" for r in designs[i]["runs"]
                                if r["branch"] == 1)
            + ("  |  " + " → ".join(f"{r['pipe']['nominal_mm']:.0f}" for r in designs[i]["runs"]
                                    if r["branch"] == 2) if len(designs[i]["branches"]) > 1 else ""),
            "Spread (m)": round(designs[i]["spread_m"], 3),
            "Valve head (m)": round(designs[i]["valve_head_m"], 2),
            "Cost (EGP)": round(designs[i]["cost"]),
            "OK": "✓" if designs[i]["satisfied"] else "✗ FAIL"} for i in ids]),
            hide_index=True, width="stretch")
    with views[3]:
        saving = d["single_size_cost"] - d["cost"]
        verdict(d["satisfied"],
                f"Manifold {pick}: spread {d['spread_m']:.3f} m within {allow:.3f} m, "
                f"velocity {d['max_velocity_ms']:.2f} m/s within {v_max:.1f} m/s.",
                f"Manifold {pick}: spread {d['spread_m']:.3f} m against {allow:.3f} m allowed.")
        if not d["attainable"]:
            banner("bad", f"No pipe size meets the allowance on this manifold: even the best "
                          f"achievable spread is {d['min_achievable_spread_m']:.3f} m, which "
                          "is elevation, not friction. Put the valve at the uphill end or "
                          "the middle, shorten the manifold (Operational Design), or use "
                          "pressure-compensating emitters.")
        if saving > 0:
            note(f"Telescoping saves <b>{saving:,.0f} EGP</b> on this manifold against "
                 f"running the largest size ({d['single_size_pipe']['nominal_mm']:.0f} mm) "
                 f"over its whole {d['length_m']:.0f} m.")
        note("Each manifold is marched outlet by outlet with its real row flows — short "
             "corner rows draw less — rather than by the Christiansen factor, which assumes "
             "equal outlets on one diameter. On the ideal case the two agree within 2 %.")
    return {"designs": designs, "critical": crit, "allowable": allow, "v_max": v_max,
            "materials": mats, "max_sizes": int(max_sizes), "use_leftover": use_leftover,
            "all_satisfied": all_ok}


# ---------------------------------------------------------------------------
# Mainline tree
# ---------------------------------------------------------------------------

def _z_function(S):
    setup, op = S["setup"], S["operation"]
    along, across = FN.unit_vectors(op["bearing"])
    s1 = float(setup.get("slope", 0.0)) / 100.0
    s2 = float(setup.get("slope_across", 0.0)) / 100.0

    def z(xy):
        u = xy[0] * along[0] + xy[1] * along[1]
        v = xy[0] * across[0] + xy[1] * across[1]
        return s1 * u + s2 * v
    return z


def _mainline_tab(S, ctx, prev, lat, man):
    setup, op, net = S["setup"], S["operation"], S["network"]
    sub_header("Mainline & Submain Design — sized shift by shift")
    cat_rows = ctx["pipes"]["pipes"]
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        mats = st.multiselect("Materials", sorted({p["material"] for p in cat_rows}),
                              default=prev.get("main_materials", ["PVC", "PE"]), key="ml_mat")
    with c2:
        v_max = st.number_input("Velocity limit (m/s)", 0.5, 3.0,
                                float(prev.get("main_vmax", 1.5)), 0.1, key="ml_v")
    with c3:
        j_max = st.number_input("Friction gradient limit (m/100 m)", 0.2, 10.0,
                                float(prev.get("main_jmax", 1.5)), 0.1, key="ml_j")
    with c4:
        valve_loss = st.number_input("Valve + regulator loss (m)", 0.0, 10.0,
                                     float(prev.get("valve_loss", 1.5)), 0.1, key="ml_vl",
                                     help="Across the subunit valve (and regulator, where fitted)")
    rows = [p for p in cat_rows if p["material"] in (mats or ["PVC"])]
    if not rows:
        banner("bad", "Select at least one material.")
        return None
    cat = N.pipe_catalogue(rows)
    tree = N.build_tree(net["pipes"], net["source"], net["valves"])
    if tree["unattached"] or tree["source_node"] is None:
        banner("bad", "The saved network does not reach every valve. Return to Pipe Network "
                      "Layout.")
        return None
    shifts = {}
    for sid, sh in op["assignment"].items():
        shifts.setdefault(int(sh), []).append(sid)
    q_valve = {s["id"]: s["q_m3h"] for s in op["subunits"]}
    h_req = {sid: man["designs"][sid]["valve_head_m"] + valve_loss for sid in q_valve}
    z = _z_function(S)
    sizing = N.size_tree(tree, shifts, q_valve, cat, v_max, j_max, lat["nu"])
    hyd = N.tree_hydraulics(tree, sizing, shifts, q_valve, h_req, z, lat["nu"])
    crit = hyd["critical_shift"]
    ps = hyd["per_shift"]
    # One pump serves every shift at the critical shift's head. A valve in a
    # shift that needs less therefore receives the difference on top of its
    # own-shift surplus — that is what its regulator has to burn off. Judging
    # regulators on the own-shift surplus alone assumes a variable-speed pump.
    h_pump = hyd["h_source_max_m"]
    for s in ps.values():
        for x in s["valves"].values():
            x["surplus_pump_m"] = x["surplus_m"] + (h_pump - s["h_source_m"])
    surplus_max = max(x["surplus_pump_m"] for s in ps.values() for x in s["valves"].values())
    reg_thr = st.slider("Fit a pressure regulator where the valve surplus exceeds (m)",
                        0.5, 10.0, float(prev.get("reg_threshold", 2.0)), 0.5, key="ml_reg",
                        help="Surplus at the pump's single duty head, i.e. without a "
                             "variable-speed drive")
    regs = sorted({v for s in ps.values() for v, x in s["valves"].items()
                   if x["surplus_pump_m"] > reg_thr})
    all_ok = all(s["satisfied"] for s in sizing.values())

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Network inlet head", f"{hyd['h_source_max_m']:.2f} m",
              f"shift {crit}", delta_color="off")
    c2.metric("Largest shift flow", f"{hyd['q_max_m3h']:.1f} m³/h",
              f"shift {hyd['max_flow_shift']}", delta_color="off")
    c3.metric("Pressure regulators", f"{len(regs)}", f"surplus > {reg_thr:.1f} m",
              delta_color="off")
    with c4:
        if all_ok:
            st.success("✅ Mainline OK")
        else:
            st.warning("⚠️ Some pipes exceed the limits")

    labels = {}
    pipes_draw = []
    for eid, s in sizing.items():
        e = tree["edges"][eid]
        a, b = tree["nodes"][e["a"]], tree["nodes"][e["b"]]
        pid = f"E{eid}"
        pipes_draw.append({"id": pid, "kind": e["kind"], "points": [a, b]})
        labels[pid] = (f"{s['pipe']['nominal_mm']:.0f} mm {s['pipe']['material']} · "
                       f"{s['length_m']:.1f} m · Qd {s['q_design_m3h']:.1f} m³/h · "
                       f"v {s['velocity_ms']:.2f} m/s")
    views = st.tabs(VIEWS)
    with views[0]:
        st.markdown("##### Sized mainline tree (hover a pipe for its size)")
        fig = PL.plan_view(boundary=op["boundary_local"], manifolds=net["manifolds"],
                           pipes=pipes_draw, pipe_labels=labels, valves=net["valves"],
                           source=net["source"], height=620)
        st.plotly_chart(fig, width="stretch", key="ml_plan")
    with views[1]:
        sh_list = sorted(ps)
        st.plotly_chart(PL.shift_heads(sh_list, [ps[s]["h_source_m"] for s in sh_list],
                                       [ps[s]["q_m3h"] for s in sh_list]),
                        width="stretch", key="ml_shifts")
        st.dataframe(pd.DataFrame([{
            "Shift": s, "Flow (m³/h)": round(ps[s]["q_m3h"], 2),
            "Head at source (m)": round(ps[s]["h_source_m"], 2),
            "Critical valve": ps[s]["critical_valve"],
            "Path friction (m)": round(ps[s]["critical_path_loss_m"], 2),
            "Lift to valve (m)": round(ps[s]["critical_lift_m"], 2)} for s in sh_list]),
            hide_index=True, width="stretch")
    with views[2]:
        st.dataframe(pd.DataFrame([{
            "Pipe": f"E{eid}", "Drawn line": tree["edges"][eid]["pipe_id"],
            "Kind": tree["edges"][eid]["kind"], "Length (m)": round(s["length_m"], 1),
            "Design flow (m³/h)": round(s["q_design_m3h"], 2),
            "Size": f"{s['pipe']['nominal_mm']:.0f} mm {s['pipe']['material']} PN{s['pipe']['pn_bar']:g}",
            "v (m/s)": round(s["velocity_ms"], 2), "J (m/100 m)": round(s["j_m_per_100m"], 2),
            "hf at Qd (m)": round(s["hf_m"], 3), "Cost (EGP)": round(s["cost"]),
            "OK": "✓" if s["satisfied"] else "✗ FAIL"} for eid, s in sorted(sizing.items())]),
            hide_index=True, width="stretch")
        st.markdown("##### Valve pressures, shift by shift")
        st.dataframe(pd.DataFrame([{
            "Shift": s, "Valve": v, "Required (m)": round(x["required_m"], 2),
            "Received (m)": round(x["pressure_m"], 2),
            "Surplus, own shift (m)": round(x["surplus_m"], 2),
            "Surplus at pump duty (m)": round(x["surplus_pump_m"], 2),
            "Regulator": "yes" if v in regs else ""} for s in sorted(ps)
            for v, x in ps[s]["valves"].items()]), hide_index=True, width="stretch")
    with views[3]:
        verdict(all_ok, "Every mainline and submain pipe is within the velocity and "
                        "friction-gradient limits.",
                "At least one pipe has no catalogue size inside the limits; the largest was "
                "used. Add larger sizes or split the flow.")
        if surplus_max > reg_thr:
            note(f"The largest surplus at a valve is <b>{surplus_max:.2f} m</b>. "
                 f"{len(regs)} valve(s) get a pressure regulator. A big surplus near the "
                 "source is the price of one pump duty for all shifts; balancing shifts by "
                 "distance (Operational Design) reduces it.")
        spread = (max(s["h_source_m"] for s in ps.values())
                  - min(s["h_source_m"] for s in ps.values()))
        if spread > 3.0:
            banner("warn", f"The head needed at the source varies by {spread:.1f} m between "
                           "shifts. A single-speed pump runs at the critical shift's duty "
                           "and throttles the others; a variable-speed drive would save that "
                           "energy.")
    return {"tree": tree, "sizing": sizing, "hyd": hyd, "shifts": shifts, "h_req": h_req,
            "valve_loss": valve_loss, "v_max": v_max, "j_max": j_max, "materials": mats,
            "regulators": regs, "reg_threshold": reg_thr, "all_ok": all_ok}


# ---------------------------------------------------------------------------
# Summary and save
# ---------------------------------------------------------------------------

def _summary_tab(S, lat, man, main):
    sub_header("Network Summary")
    sizing = main["sizing"]
    by = {}
    for s in sizing.values():
        k = f"{s['pipe']['nominal_mm']:.0f} mm {s['pipe']['material']}"
        by.setdefault(("Mainline / submain", k), 0.0)
        by[("Mainline / submain", k)] += s["length_m"]
    for d in man["designs"].values():
        for r in d["runs"]:
            k = f"{r['pipe']['nominal_mm']:.0f} mm {r['pipe']['material']}"
            by.setdefault(("Manifold", k), 0.0)
            by[("Manifold", k)] += r["length_m"]
    drip = sum(s["dripline_m"] for s in S["operation"]["subunits"])
    rows = [{"Component": c, "Size": k, "Length (m)": round(v, 1)} for (c, k), v in sorted(by.items())]
    rows.append({"Component": "Dripline", "Size": f"{lat['lateral']['nominal_mm']:.0f} mm",
                 "Length (m)": round(drip, 0)})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    hyd = main["hyd"]
    crit = hyd["per_shift"][hyd["critical_shift"]]
    cv = crit["critical_valve"]
    d = man["designs"][cv]
    em = S["emitter"]
    section(f"Critical path — shift {hyd['critical_shift']}, valve {cv}")
    parts = [("Emitter operating head", em["h_op"]),
             ("Lateral: inlet above minimum emitter", lat["lateral_inlet_required_m"] - em["h_op"]),
             ("Manifold: inlet above minimum outlet", d["inlet_minus_min_m"]),
             ("Valve and regulator", main["valve_loss"]),
             ("Mainline / submain friction", crit["critical_path_loss_m"]),
             ("Lift from source to valve", crit["critical_lift_m"])]
    st.plotly_chart(PL.head_breakdown([p[0] for p in parts], [p[1] for p in parts],
                                      "Head at the network inlet, critical path"),
                    width="stretch", key="sum_bd")
    cards([("Network inlet head", f"{hyd['h_source_max_m']:.2f}", "m", "accent"),
           ("Critical shift flow", f"{crit['q_m3h']:.1f}", "m³/h", "neutral"),
           ("Pipe cost (sized)",
            f"{sum(s['cost'] for s in sizing.values()) + sum(x['cost'] for x in man['designs'].values()):,.0f}",
            "EGP", "neutral"),
           ("Valves / regulators", f"{len(S['network']['valves'])} / {len(main['regulators'])}",
            "", "neutral")])
    caption("The network inlet head excludes the head control (filters, injector) and the "
            "static lift — those are added on the Hydraulic Design page.")


def _save(S, lat, man, main):
    save(S, "lateral", lat)
    designs = man["designs"]
    crit = man["critical"]
    d = designs[crit]
    su = next(s for s in S["operation"]["subunits"] if s["id"] == crit)
    big = (max(d["runs"], key=lambda r: r["pipe"]["internal_mm"])["pipe"] if d["runs"]
           else {"nominal_mm": 0.0, "internal_mm": 0.0, "material": "-", "pn_bar": 0.0,
                 "price": 0.0})
    hyd = main["hyd"]
    crit_shift = hyd["per_shift"][hyd["critical_shift"]]
    sub_spread = lat["res"]["spread_m"] + d["spread_m"]
    sub_dh = lat["res"]["total_dh_m"] + d["total_dh_m"]
    sub_check = K.head_variation_check(sub_dh, lat["dh_allow_subunit"], spread_m=sub_spread)
    sizing = main["sizing"]
    big_main = max((s["pipe"] for s in sizing.values()), key=lambda p: p["internal_mm"])
    v_main = max(s["velocity_ms"] for s in sizing.values())
    first = min(sizing, key=lambda e: main["tree"]["distance_m"].get(
        main["tree"]["edges"][e]["a"], 0.0))
    main_res = K.head_loss_darcy(sizing[first]["q_design_m3h"], sizing[first]["pipe"]["internal_mm"],
                                 sizing[first]["length_m"], lat["nu"],
                                 K.ROUGHNESS_MM.get(sizing[first]["pipe"]["material"].upper(), 0.007))
    main_res["hf_m"] = crit_shift["critical_path_loss_m"]
    main_res["velocity_ms"] = v_main
    path_len = sum(main["tree"]["edges"][e]["length_m"]
                   for e in main["tree"]["paths"][crit_shift["critical_valve"]])
    save(S, "manifold", {
        # v1-compatible summary of the governing subunit
        "n_lat": su["n_laterals"], "m_len": d["length_m"], "m_slope": 0.0, "auto": True,
        "manifold_pipe": big, "q_manifold": su["q_m3h"],
        "m_res": {"spread_m": d["spread_m"], "total_dh_m": d["total_dh_m"],
                  "velocity_ms": d["max_velocity_ms"], "hf_m": d["friction_m"]},
        "dh_allow_manifold": man["allowable"], "subunit_dh": sub_dh,
        "subunit_spread": sub_spread, "subunit_check": sub_check,
        "main_len": path_len, "main_rise": crit_shift["critical_lift_m"],
        "main_pipe": big_main, "main_res": main_res,
        # v2 network design
        "designs": designs, "critical_subunit": crit,
        "man_materials": man["materials"], "man_vmax": man["v_max"],
        "man_max_sizes": man["max_sizes"], "man_leftover": man["use_leftover"],
        "all_manifolds_ok": man["all_satisfied"],
        "tree_sizing": {str(k): v for k, v in sizing.items()},
        "tree_edges": main["tree"]["edges"], "tree_nodes": main["tree"]["nodes"],
        "tree_paths": main["tree"]["paths"],
        "hydraulics": {str(k): {kk: vv for kk, vv in v.items()
                                if kk not in ("edge_flows", "edge_hf")}
                       for k, v in hyd["per_shift"].items()},
        "critical_shift": hyd["critical_shift"], "h_network_inlet_m": hyd["h_source_max_m"],
        "q_max_m3h": hyd["q_max_m3h"], "max_flow_shift": hyd["max_flow_shift"],
        "h_req_valve": main["h_req"], "valve_loss": main["valve_loss"],
        "main_materials": main["materials"], "main_vmax": main["v_max"],
        "main_jmax": main["j_max"], "regulators": main["regulators"],
        "reg_threshold": main["reg_threshold"], "mainline_ok": main["all_ok"],
    })
    S.pop("hydraulic", None)
