"""
Operational Design — OpenIrri's expander sequence, drip's content.

System parameters (depth, interval, set time) come first, as in OpenIrri.
Then the field is cut into SUBUNITS by geometry and the subunits are packed
into SHIFTS by water — the two numbers version 1 confused. The subdivision
diagram, the schedule layout and the manual override follow OpenIrri's
"days" pattern, with shifts in place of days.
"""

from __future__ import annotations

import math

import pandas as pd
import streamlit as st

from engine import kernels as K
from engine import subunits as SU
from engine import blocks as B
from modules import plots as PL
from modules.common import (page_header, sub_header, section, cards, banner, note,
                            caption, save, stage_guard, goto, dev_panel, context_strip,
                            verdict, stable_editor)

DIRECTIONS = ["Along the long axis (recommended)", "Across the long axis", "Custom bearing"]


def _geometry(S, prev):
    """Blocks to design, and where they came from."""
    lay = S.get("layout") or {}
    if lay.get("boundary_local"):
        blocks = [b for b in (lay.get("blocks") or []) if b.get("irrigation") == "Drip"]
        if lay.get("blocks") and not blocks:
            return None, "Every block is set to sprinkler; there is nothing to design."
        if not blocks:
            blocks = [B.make_block(1, lay["boundary_local"], 0, "", "Drip", "Whole field")]
        src = "assumed rectangle" if lay.get("assumed_rectangle") else (
            f"{len(blocks)} drip block(s)" if lay.get("blocks") else "field boundary")
        return {"blocks": blocks, "bearing": float(lay.get("bearing_deg", 0.0)),
                "boundary": lay["boundary_local"], "source": src,
                "water_source": lay.get("source_local")}, ""
    return {"blocks": None, "bearing": 0.0, "boundary": None,
            "source": "assumed rectangle", "water_source": None}, ""


def show(ctx):
    S = ctx["S"]
    page_header("Operational Design",
                "Irrigation depth, interval and set time; the field cut into subunits "
                "by geometry; the subunits packed into shifts by the water available. "
                "This is where a hydraulically valid design most often turns out to be "
                "operationally impossible.")
    if not stage_guard(S, "emitter", "Emitter Selection", page_key="emitter"):
        return
    context_strip(S)
    setup, wat, em = S["setup"], S["water"], S["emitter"]
    prev = S.get("operation", {})

    # ---------------------------------------------------- system parameters ---
    with st.expander("💧 System Parameters", expanded=True):
        try:
            raw = K.readily_available_water(wat["fc"], wat["wp"], wat["zr"], wat["p"], em["pw"])
        except ValueError as exc:
            banner("bad", f"Cannot build a schedule: {exc}")
            return
        interval_max = K.irrigation_interval(raw, wat["etc"])
        cap = max(0.25, interval_max)
        default = float(prev.get("interval", min(2.0, math.floor(cap * 4) / 4)))
        default = min(max(0.25, default), cap)
        c1, c2 = st.columns(2)
        with c1:
            interval = st.number_input("Chosen irrigation interval (days)", 0.25, float(cap),
                                       default, 0.25)
        with c2:
            st.metric("Maximum interval from RAW", f"{interval_max:.2f} days")
        interval_ok = interval <= interval_max + 1e-9
        d_net = wat["etc"] * interval
        d_gross = K.gross_depth(d_net, wat["ea"], wat["lr"])
        t_set = K.set_time(d_gross, em["ia"])
        cards([("RAW in wetted volume", f"{raw:.1f}", "mm", "neutral"),
               ("Net depth", f"{d_net:.1f}", "mm", "neutral"),
               ("Gross depth", f"{d_gross:.1f}", "mm", "accent"),
               ("Set time", f"{t_set:.2f}", "h", "accent")])
        if not interval_ok:
            banner("bad", f"<b>The chosen interval of {interval:.2f} days exceeds the "
                          f"{interval_max:.2f} days the readily available water supports.</b>")

    # ------------------------------------------------------- field geometry ---
    geo, why = _geometry(S, prev)
    if geo is None:
        banner("bad", why)
        return
    with st.expander("📐 Field Geometry", expanded=True):
        if geo["boundary"] is None:
            banner("warn", "No field boundary was drawn, so the field is taken as an "
                           "<b>assumed rectangle</b> of the project area. Draw or upload the "
                           "boundary on Home › Field Layout & Blocks for a real layout.")
            c1, c2 = st.columns(2)
            area_m2 = setup["area_ha"] * 10000.0
            with c1:
                L = st.number_input("Field length along the laterals (m)", 10.0, 5000.0,
                                    float(prev.get("rect_L", round(math.sqrt(area_m2 * 1.3)))),
                                    5.0)
            with c2:
                st.metric("Width for the project area", f"{area_m2 / L:.1f} m")
            rect = SU.rectangle_polygon(L, area_m2 / L)
            geo["boundary"] = rect
            geo["blocks"] = [B.make_block(1, rect, 0, "", "Drip", "Assumed rectangle")]
            geo["bearing"] = 0.0
            geo["rect_L"] = L
        else:
            caption(f"Geometry: <b>{geo['source']}</b>, long axis at "
                    f"{geo['bearing']:.0f}° from north.")
        c1, c2, c3 = st.columns(3)
        with c1:
            direction = st.selectbox("Lateral direction", DIRECTIONS,
                                     index=DIRECTIONS.index(prev.get("direction", DIRECTIONS[0])))
            if direction == DIRECTIONS[2]:
                bearing = st.number_input("Lateral bearing (° from north)", 0.0, 180.0,
                                          float(prev.get("bearing", geo["bearing"])), 1.0)
            else:
                bearing = (geo["bearing"] if direction == DIRECTIONS[0]
                           else (geo["bearing"] + 90.0) % 180.0)
        with c2:
            feed = st.selectbox("Lateral feed", ["middle", "end"],
                                index=["middle", "end"].index(prev.get("lateral_feed", "middle")),
                                format_func=lambda f: {"middle": "From the middle (laterals "
                                                                "both sides of the manifold)",
                                                       "end": "From one end"}[f])
        with c3:
            max_run = float(em.get("max_run_m", 60.0))
            design_run = st.number_input("Design lateral run (m)", 5.0, 600.0,
                                         float(min(prev.get("design_run", max_run), max(5.0, max_run))
                                               if max_run > 0 else 60.0), 1.0,
                                         help=f"The Uniformity budget allows up to "
                                              f"{max_run:.0f} m")
        c1, c2 = st.columns(2)
        with c1:
            max_man = st.number_input("Maximum manifold length (m)", 10.0, 1000.0,
                                      float(prev.get("max_manifold", 100.0)), 5.0,
                                      help="Longer manifolds need larger pipe for the "
                                           "same head spread")
        with c2:
            man_inlet = st.selectbox("Valve position on the manifold", ["end", "middle"],
                                     index=["end", "middle"].index(prev.get("manifold_inlet", "end")),
                                     format_func=lambda f: {"end": "At one end",
                                                            "middle": "At the middle"}[f])
        if design_run > max_run + 1e-9 and max_run > 0:
            banner("bad", f"The design run of {design_run:.0f} m exceeds the {max_run:.0f} m "
                          "the uniformity budget allows. The lateral check on Pipe Network "
                          "Design will fail.")

    # ---------------------------------------------- water & operating hours ---
    with st.expander("🚰 Water Source & Operating Hours", expanded=False):
        c1, c2, c3 = st.columns(3)
        c1.metric("Available discharge", f"{setup['q_avail']:.1f} m³/h")
        c2.metric("Max operating hours", f"{setup['hours_day']:.1f} h/day")
        with c3:
            strategy = st.selectbox("Shift grouping", list(SU.SHIFT_STRATEGIES),
                                    index=list(SU.SHIFT_STRATEGIES).index(prev.get("strategy", "balanced")),
                                    format_func=lambda s: {"balanced": "Balanced flows",
                                                           "contiguous": "Neighbours together"}[s])
        min_shifts = st.number_input("Minimum number of shifts", 1, 50,
                                     int(prev.get("min_shifts", 1)), 1,
                                     help="Raise to spread the flow further, e.g. to "
                                          "match a smaller pump")
        caption("Change the source discharge or the working day on Home › Project Setup.")

    # ------------------------------------------------------------- compute ---
    auto_fit = st.session_state.get("op_autofit", prev.get("auto_fit", True))

    def build(man_len):
        out = []
        for blk in geo["blocks"]:
            try:
                r = SU.subunits_for_block(blk["polygon_local"], bearing, em["sl"], design_run,
                                          em["se"], em["q_emitter"], feed, man_len,
                                          int(em.get("lat_per_row", 1)), blk["id"], blk["name"])
            except ValueError as exc:
                banner("bad", f"{blk['name']}: {exc}")
                continue
            segs = {row["index"]: row["segments"] for row in r["geometry"]["rows"]}
            for su in r["subunits"]:
                su["_segments"] = [s for i in su["rows"] for s in segs.get(i, [])]
            out += r["subunits"]
        return out

    eff_man = max_man
    subunits = build(eff_man)
    # A subunit that alone draws more than the source cannot be scheduled.
    # Shorter manifolds make smaller subunits; shrink until every one fits,
    # but never below two lateral spacings.
    while (auto_fit and subunits and eff_man > 2.0 * em["sl"]
           and max(s["q_m3h"] for s in subunits) > setup["q_avail"] + 1e-9):
        eff_man = max(2.0 * em["sl"], eff_man * 0.85)
        subunits = build(eff_man)
    if not subunits:
        banner("bad", "No subunit could be laid out on this geometry.")
        return
    st.checkbox("Shorten manifolds automatically so that every subunit fits the source",
                value=auto_fit, key="op_autofit")
    if eff_man < max_man - 1e-9:
        banner("warn", f"Manifolds were shortened from {max_man:.0f} m to "
                       f"<b>{eff_man:.0f} m</b> so that no single subunit draws more than the "
                       f"{setup['q_avail']:.0f} m³/h the source supplies.")
    src_xy = geo.get("water_source") or [0.0, 0.0]
    alloc = SU.allocate_shifts(subunits, setup["q_avail"], strategy, src_xy, int(min_shifts))
    assignment = dict(alloc["assignment"])
    sig_now = _sig(subunits)
    draft = st.session_state.get("op_override") or {}
    if draft.get("sig") == sig_now:
        override = draft.get("assign")
    elif prev.get("override_sig") == sig_now:
        override = prev.get("override")
    else:
        override = None
    if override:
        assignment.update(override)
    loads = SU.shift_loads(subunits, assignment)
    n_shifts = max(loads) if loads else 0

    # --------------------------------------------------- subdivision results ---
    with st.expander("📋 Field Subdivision Results", expanded=True):
        q_total = sum(s["q_m3h"] for s in subunits)
        cards([("Subunits", f"{len(subunits)}", "valves", "accent"),
               ("Shifts", f"{n_shifts}", "", "accent"),
               ("Flow, whole field", f"{q_total:.1f}", "m³/h", "neutral"),
               ("Longest lateral run", f"{max(s['max_run_m'] for s in subunits):.1f}", "m",
                "ok" if max(s['max_run_m'] for s in subunits) <= design_run * 1.05 else "warn")])
        df = pd.DataFrame([{
            "Subunit": s["id"], "Block": s["block_name"], "Band": s["band"],
            "Part": s["part"], "Rows": s["n_rows"], "Laterals": s["n_laterals"],
            "Dripline (m)": round(s["dripline_m"]), "Area (ha)": round(s["area_ha"], 3),
            "Flow (m³/h)": round(s["q_m3h"], 2), "Manifold (m)": round(s["manifold_m"], 1),
            "Longest run (m)": round(s["max_run_m"], 1),
            "Shift": assignment.get(s["id"], 0)} for s in subunits])
        st.dataframe(df, hide_index=True, width="stretch")
        if alloc["oversize"]:
            banner("bad", f"Subunit(s) {', '.join(alloc['oversize'])} draw more than the "
                          "source can supply on their own. Reduce the maximum manifold "
                          "length or the design run so that each subunit is smaller.")
        note("Subunits come from GEOMETRY — how far one lateral may run and how long one "
             "manifold may be. Shifts come from WATER — how much of the field the source "
             "can irrigate at once. The two numbers are independent; version 1 assumed one "
             "manifold per shift, which the Wadi El-Natrun layout test showed to be wrong.")

    with st.expander("🗺️ Subdivision Layout Diagram", expanded=True):
        fig = PL.plan_view(boundary=geo["boundary"], subunits=subunits,
                           shift_of=assignment, source=geo.get("water_source"),
                           height=620, title="Subunits coloured by shift")
        st.plotly_chart(fig, width="stretch", key="op_plan")

    # ---------------------------------------------------- results & schedule ---
    q_shift = max(loads.values()) if loads else 0.0
    sched = K.operating_hours_check(n_shifts, t_set, interval, setup["hours_day"])
    area_net = sum(s["area_ha"] for s in subunits)
    wb = K.water_balance(setup["q_avail"], setup["hours_day"], d_gross / interval, area_net)
    with st.expander("📊 Irrigation Results Summary", expanded=True):
        if not wb["ok"]:
            banner("bad", f"<b>The source cannot supply the peak demand.</b> The field needs "
                          f"{wb['demand_m3_day']:,.0f} m³/day at peak; "
                          f"{setup['q_avail']:g} m³/h × {setup['hours_day']:g} h gives "
                          f"{wb['supply_m3_day']:,.0f} m³/day ({wb['ratio']*100:.0f} %). No "
                          f"layout or shift arrangement can fix this. Needed: a source of at "
                          f"least {wb['q_needed_m3h']:.1f} m³/h at {setup['hours_day']:g} h/day, "
                          f"or {wb['hours_needed']:.1f} h/day at the present discharge, or "
                          f"an irrigated area of at most {wb['area_max_ha']:.2f} ha.")
        cards([("Flow per shift (max)", f"{q_shift:.1f}", "m³/h",
                "ok" if q_shift <= setup["q_avail"] + 1e-9 else "bad"),
               ("Area per shift (mean)",
                f"{sum(s['area_ha'] for s in subunits) / max(n_shifts, 1):.2f}", "ha", "neutral"),
               ("Cycle hours needed", f"{sched['required_h_per_cycle']:.1f}", "h", "neutral"),
               ("Utilisation", f"{sched['utilisation_pct']:.0f}", "%",
                "ok" if sched["feasible"] else "bad")])
        verdict(sched["feasible"],
                f"Schedule fits: {sched['required_h_per_cycle']:.1f} h required against "
                f"{sched['available_h_per_cycle']:.1f} h available per "
                f"{interval:g}-day cycle ({sched['utilisation_pct']:.0f} %).",
                f"Schedule does NOT fit. {sched['reason']}")

    with st.expander("📐 Detailed Calculations", expanded=False):
        st.markdown(
            f"- RAW = p·(FC − WP)·Zr·Pw = {wat['p']:.2f} × ({wat['fc']:.0f} − {wat['wp']:.0f}) "
            f"× {wat['zr']:.2f} × {em['pw']:.2f} = **{raw:.1f} mm**\n"
            f"- Maximum interval = RAW / ETc = {raw:.1f} / {wat['etc']:.2f} = "
            f"**{interval_max:.2f} d**\n"
            f"- Gross depth = ETc·I / Ea{' / (1 − LR)' if wat['lr'] > 0.1 else ''} = "
            f"**{d_gross:.1f} mm**\n"
            f"- Set time = gross depth / Ia = {d_gross:.1f} / {em['ia']:.2f} = **{t_set:.2f} h**\n"
            f"- Shifts = subunits packed so that no shift exceeds {setup['q_avail']:.1f} m³/h "
            f"→ **{n_shifts}** (the water alone would need "
            f"{math.ceil(sum(s['q_m3h'] for s in subunits) / setup['q_avail'])}).")

    with st.expander("📅 Irrigation Schedule Layout", expanded=True):
        order = list(range(1, n_shifts + 1))
        st.plotly_chart(PL.schedule_gantt(order, t_set, setup["hours_day"], interval),
                        width="stretch", key="op_gantt")
        if n_shifts:
            st_tabs = st.tabs([f"Shift {i}" for i in order])
            for i, tb in zip(order, st_tabs):
                with tb:
                    ids = [s for s in subunits if assignment.get(s["id"]) == i]
                    st.dataframe(pd.DataFrame([{
                        "Subunit": s["id"], "Block": s["block_name"],
                        "Flow (m³/h)": round(s["q_m3h"], 2),
                        "Area (ha)": round(s["area_ha"], 3)} for s in ids]),
                        hide_index=True, width="stretch")
                    st.caption(f"Total {sum(s['q_m3h'] for s in ids):.2f} m³/h over "
                               f"{sum(s['area_ha'] for s in ids):.2f} ha, "
                               f"{t_set:.2f} h per set.")

    with st.expander("🔧 Manual Shift Assignment Override", expanded=False):
        caption("Reassign subunits to shifts by hand, e.g. to keep one block on one "
                "valve group. Every shift is re-checked against the source discharge.")
        sig = _sig(subunits)
        ed = stable_editor(f"op_override_{sig}", lambda: pd.DataFrame(
            [{"Subunit": s["id"], "Flow (m³/h)": round(s["q_m3h"], 2),
              "Shift": int(assignment.get(s["id"], 1))} for s in subunits]),
            hide_index=True, width="stretch",
            column_config={"Subunit": st.column_config.TextColumn(disabled=True),
                           "Flow (m³/h)": st.column_config.NumberColumn(disabled=True),
                           "Shift": st.column_config.NumberColumn(min_value=1, max_value=50,
                                                                  step=1)})
        new_assign = {r["Subunit"]: int(r["Shift"]) for r in ed.to_dict("records")}
        new_loads = SU.shift_loads(subunits, new_assign)
        over = {k: v for k, v in new_loads.items() if v > setup["q_avail"] + 1e-9}
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Apply override", key="op_apply"):
                if over:
                    banner("bad", "Shift(s) " + ", ".join(f"{k} ({v:.1f} m³/h)" for k, v in
                                                           sorted(over.items()))
                           + " exceed the source discharge. Not applied.")
                else:
                    st.session_state["op_override"] = {"sig": sig, "assign": dict(new_assign)}
                    st.rerun()
        with c2:
            if override and st.button("Clear override", key="op_clear"):
                st.session_state["op_override"] = {"sig": sig, "assign": None}
                if S.get("operation"):
                    S["operation"].pop("override", None)
                    S["operation"].pop("override_sig", None)
                st.rerun()

    blocked = bool(alloc["oversize"]) or n_shifts == 0
    if blocked:
        banner("bad", "Saving is blocked: at least one subunit cannot be scheduled on the "
                      "source. Shorten the manifolds or the design run.")
    if st.button("💾 Save", type="primary", key="save_operation", disabled=blocked):
        area_total = sum(s["area_ha"] for s in subunits)
        emitters_total = sum(s["emitters"] for s in subunits)
        payload = {
            "raw": raw, "interval_max": interval_max, "interval": interval,
            "interval_ok": interval_ok, "d_net": d_net, "d_gross": d_gross, "t_set": t_set,
            "shifts": n_shifts, "q_shift": q_shift, "area_shift": area_total / max(n_shifts, 1),
            "emitters_shift": emitters_total / max(n_shifts, 1), "schedule": sched,
            "daily_volume": wat["etc"] / wat["ea"] * setup["area_ha"] * 10.0,
            "direction": direction, "bearing": bearing, "lateral_feed": feed,
            "design_run": design_run, "max_manifold": max_man, "manifold_inlet": man_inlet,
            "effective_manifold": eff_man, "auto_fit": auto_fit,
            "strategy": strategy, "min_shifts": int(min_shifts),
            "subunits": subunits, "assignment": assignment,
            "loads": {str(k): v for k, v in loads.items()}, "n_subunits": len(subunits),
            "geometry_source": geo["source"], "boundary_local": geo["boundary"],
            "water_source": geo.get("water_source"), "rect_L": geo.get("rect_L"),
            "area_geometry_ha": area_total, "q_total": sum(s["q_m3h"] for s in subunits),
        }
        if override:
            payload["override"] = dict(override)
            payload["override_sig"] = sig_now
        old_sig = prev.get("layout_sig")
        payload["layout_sig"] = _sig(subunits) + f"|{man_inlet}"
        save(S, "operation", payload)
        if old_sig != payload["layout_sig"]:
            for k in ("network", "lateral", "manifold", "hydraulic"):
                S.pop(k, None)
        st.success("✅ Operational design saved.")
        goto("network")
    dev_panel(S, "operation")


def _sig(subunits) -> str:
    import zlib
    txt = "|".join(f"{s['id']}:{s['q_m3h']:.3f}:{s['n_rows']}" for s in subunits)
    return str(zlib.crc32(txt.encode()))
