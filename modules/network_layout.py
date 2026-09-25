"""
Pipe Network Layout — OpenIrri's CAD page for drip.

The network is generated from the subunits (a comb: mainline, submains,
manifolds, one valve per subunit), then edited by hand on the graph-paper
plan: click-to-click drawing on a snap grid, exactly as OpenIrri draws its
mainlines and submains. Whatever is drawn is what the Pipe Network Design
page sizes — the hydraulic tree is rebuilt from the drawn lines every time,
and a valve the drawn pipes do not reach is reported, not assumed connected.
"""

from __future__ import annotations

import copy
import math

import pandas as pd
import streamlit as st

from engine import network as N
from modules import plots as PL
from modules.common import (page_header, sub_header, section, cards, banner, note,
                            caption, save, stage_guard, goto, dev_panel, context_strip,
                            stable_editor)

MODES = ["🔴 Mainline", "🟠 Submain", "💧 Move source", "🔷 Move valve", "👁️ View only"]
DRAFT = "nw_draft"


def _draft(S):
    """The network being edited; seeded from the saved one or generated."""
    op = S["operation"]
    d = st.session_state.get(DRAFT)
    if d is None or d.get("_sig") != op.get("layout_sig"):
        saved = S.get("network")
        if saved and saved.get("_sig") == op.get("layout_sig"):
            d = copy.deepcopy(saved)
        else:
            d = _generate(S)
        st.session_state[DRAFT] = d
    return d


def _default_source(op):
    poly = op["boundary_local"]
    xs, ys = [p[0] for p in poly], [p[1] for p in poly]
    return [min(xs) - 15.0, min(ys) - 15.0]


def _generate(S):
    op = S["operation"]
    src = op.get("water_source") or _default_source(op)
    net = N.auto_network(op["subunits"], src, op["bearing"], op.get("manifold_inlet", "end"))
    net["_sig"] = op.get("layout_sig")
    net["generated"] = True
    return net


def _snap_points(op, d, step):
    poly = op["boundary_local"]
    xs = [p[0] for p in poly] + [d["source"][0]]
    ys = [p[1] for p in poly] + [d["source"][1]]
    x0, x1 = math.floor((min(xs) - 20) / step) * step, math.ceil((max(xs) + 20) / step) * step
    y0, y1 = math.floor((min(ys) - 20) / step) * step, math.ceil((max(ys) + 20) / step) * step
    pts = [[x, y] for x in _frange(x0, x1, step) for y in _frange(y0, y1, step)]
    pts += [v["xy"] for v in d["valves"]]
    pts += [p for pp in d["pipes"] for p in pp["points"]]
    pts.append(d["source"])
    return pts


def _frange(a, b, s):
    n = int(round((b - a) / s))
    return [a + i * s for i in range(n + 1)]


def show(ctx):
    S = ctx["S"]
    page_header("🔧 CAD - Pipe Network Layout",
                "Mainline, submains, manifolds and subunit valves on the field plan. "
                "Generate the network from the subunits, then redraw any part of it by "
                "clicking points on the graph paper. The Pipe Network Design page sizes "
                "the network exactly as drawn here.")
    if not stage_guard(S, "operation", "Operational Design", page_key="operation"):
        return
    context_strip(S)
    op = S["operation"]
    d = _draft(S)

    st.info("💡 **Operational Design Overlay Active**: subunits are coloured by shift. "
            "Each diamond is a subunit valve; every valve must be reached by a mainline "
            "or submain for the design to size it.")

    # ---------------------------------------------------------------- toolbar
    c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
    with c1:
        mode = st.radio("Drawing mode", MODES, horizontal=True, key="nw_mode")
    with c2:
        span = max(max(p[0] for p in op["boundary_local"]) - min(p[0] for p in op["boundary_local"]),
                   max(p[1] for p in op["boundary_local"]) - min(p[1] for p in op["boundary_local"]))
        auto_step = max(5, int(5 * math.ceil(span / 60.0 / 5)))
        step = st.number_input("Snap grid (m)", 1, 100, int(st.session_state.get("nw_step", auto_step)),
                               1, key="nw_step")
    with c3:
        show_laterals = st.checkbox("Show laterals", value=True, key="nw_lat")
    with c4:
        if st.button("⚡ Regenerate network", key="nw_regen",
                     help="Discard hand edits and rebuild the comb layout from the subunits"):
            st.session_state[DRAFT] = _generate(S)
            st.session_state["nw_points"] = []
            st.rerun()

    pts_key = "nw_points"
    drawing = st.session_state.setdefault(pts_key, [])
    counter = st.session_state.setdefault("nw_click", 0)

    tree = N.build_tree(d["pipes"], d["source"], d["valves"])
    rows = [s for su in op["subunits"] for s in su.get("_segments", [])] if show_laterals else None
    fig = PL.plan_view(boundary=op["boundary_local"], rows_geometry=rows,
                       manifolds=d["manifolds"], pipes=d["pipes"], valves=d["valves"],
                       source=d["source"], drawing=drawing,
                       snap_points=_snap_points(op, d, step) if mode != MODES[-1] else None,
                       height=680, title="")
    event = st.plotly_chart(fig, width="stretch", on_select="rerun",
                            selection_mode="points", key=f"nw_map_{counter}")
    clicked = None
    try:
        sel = event.selection.points if event and event.selection else []
        if sel:
            clicked = [float(sel[0]["x"]), float(sel[0]["y"])]
    except Exception:                         # noqa: BLE001 — no selection support
        clicked = None

    if clicked is not None and mode != MODES[-1]:
        st.session_state["nw_click"] = counter + 1
        if mode in (MODES[0], MODES[1]):
            if not drawing or drawing[-1] != clicked:
                drawing.append(clicked)
        elif mode == MODES[2]:
            d["source"] = clicked
        elif mode == MODES[3]:
            st.session_state["nw_valve_target"] = clicked
        st.rerun()

    # ------------------------------------------------------- drawing actions
    if mode in (MODES[0], MODES[1]):
        kind = "mainline" if mode == MODES[0] else "submain"
        c1, c2, c3, c4 = st.columns(4)
        c1.markdown(f"**Points:** {len(drawing)}"
                    + (f" · length {N.polyline_length(drawing):.1f} m" if len(drawing) > 1 else ""))
        with c2:
            if st.button("✅ Finish line", type="primary", key="nw_finish",
                         disabled=len(drawing) < 2):
                n = sum(1 for p in d["pipes"] if p["kind"] == kind) + 1
                d["pipes"].append({"id": f"{'ML' if kind == 'mainline' else 'SM'}-D{n}",
                                   "kind": kind, "points": [list(p) for p in drawing]})
                d["generated"] = False
                st.session_state[pts_key] = []
                st.rerun()
        with c3:
            if st.button("↩ Undo point", key="nw_undo", disabled=not drawing):
                drawing.pop()
                st.rerun()
        with c4:
            if st.button("✖ Cancel line", key="nw_cancel", disabled=not drawing):
                st.session_state[pts_key] = []
                st.rerun()
        caption("Click snap points on the plan one after another; each click adds a "
                "vertex. A line only needs to pass within a few metres of a valve: the "
                "valve is tapped onto the nearest pipe.")
    elif mode == MODES[3]:
        target = st.session_state.get("nw_valve_target")
        vids = [v["id"] for v in d["valves"]]
        c1, c2 = st.columns([2, 1])
        with c1:
            vid = st.selectbox("Valve to move", vids, key="nw_vsel")
        with c2:
            st.write("")
            if st.button("Move to the clicked point", disabled=target is None, key="nw_vmove"):
                for v in d["valves"]:
                    if v["id"] == vid:
                        v["xy"] = list(target)
                d["generated"] = False
                st.rerun()
        caption("Click a snap point, pick the valve, then move it. The manifold keeps its "
                "row feeds; the valve position sets where the manifold is fed.")

    # ------------------------------------------------------- tree validation
    section("Network check")
    used = len(tree["used_edges"])
    cards([
        ("Valves reached", f"{len(tree['paths'])} / {len(d['valves'])}", "",
         "ok" if not tree["unattached"] else "bad"),
        ("Pipe segments used", f"{used}", "", "neutral"),
        ("Unused segments", f"{len(tree['unused_edges'])}", "",
         "warn" if tree["unused_edges"] else "ok"),
        ("Source attached", "yes" if tree["source_node"] is not None else "NO", "",
         "ok" if tree["source_node"] is not None else "bad"),
    ])
    if tree["unattached"]:
        banner("bad", "Valve(s) " + ", ".join(tree["unattached"]) + " are not reached by "
                      "any mainline or submain from the source. Draw a line to them, or "
                      "regenerate the network.")
    if tree["unused_edges"]:
        banner("warn", f"{len(tree['unused_edges'])} drawn pipe segment(s) carry no flow "
                       "to any valve (a loop or a dead end). They are shown but not sized "
                       "or priced.")

    # ------------------------------------------------------------ inventory
    mains = [p for p in d["pipes"] if p["kind"] == "mainline"]
    subs = [p for p in d["pipes"] if p["kind"] == "submain"]
    with st.expander(f"🔴 Mainlines ({len(mains)})", expanded=False):
        _pipe_table(d, "mainline")
    with st.expander(f"🟠 Submains ({len(subs)})", expanded=False):
        _pipe_table(d, "submain")
    with st.expander(f"🟣 Manifolds ({len(d['manifolds'])})", expanded=False):
        st.dataframe(pd.DataFrame([{
            "Subunit": m["subunit"], "Outlets": len(m["points"]),
            "Length (m)": round(N.polyline_length(m["points"]), 1),
            "Valve at outlet": m["inlet_index"] + 1} for m in d["manifolds"]]),
            hide_index=True, width="stretch")
    with st.expander(f"🟢 Laterals ({sum(s['n_laterals'] for s in op['subunits'])})",
                     expanded=False):
        st.dataframe(pd.DataFrame([{
            "Subunit": s["id"], "Laterals": s["n_laterals"],
            "Dripline (m)": round(s["dripline_m"]), "Longest run (m)": round(s["max_run_m"], 1)}
            for s in op["subunits"]]), hide_index=True, width="stretch")
    with st.expander(f"🔵 Valves ({len(d['valves'])})", expanded=False):
        st.dataframe(pd.DataFrame([{
            "Valve": v["id"], "x (m)": round(v["xy"][0], 1), "y (m)": round(v["xy"][1], 1),
            "Reached": "yes" if v["id"] in tree["paths"] else "NO",
            "Path length (m)": round(sum(tree["edges"][e]["length_m"] for e in
                                         tree["paths"].get(v["id"], [])), 1)}
            for v in d["valves"]]), hide_index=True, width="stretch")
    with st.expander("💧 Water source", expanded=False):
        c1, c2 = st.columns(2)
        sx = c1.number_input("Source x (m)", value=float(d["source"][0]), step=1.0, key="nw_sx")
        sy = c2.number_input("Source y (m)", value=float(d["source"][1]), step=1.0, key="nw_sy")
        if (sx, sy) != tuple(d["source"]):
            d["source"] = [sx, sy]
            st.rerun()

    total_main = sum(N.polyline_length(p["points"]) for p in mains)
    total_sub = sum(N.polyline_length(p["points"]) for p in subs)
    total_man = sum(N.polyline_length(m["points"]) for m in d["manifolds"])
    cards([("Mainline", f"{total_main:,.0f}", "m", "neutral"),
           ("Submains", f"{total_sub:,.0f}", "m", "neutral"),
           ("Manifolds", f"{total_man:,.0f}", "m", "neutral"),
           ("Dripline", f"{sum(s['dripline_m'] for s in op['subunits']):,.0f}", "m", "neutral")])

    if st.button("💾 Save", type="primary", key="save_network",
                 disabled=bool(tree["unattached"]) or tree["source_node"] is None):
        payload = copy.deepcopy(d)
        payload.update({"total_mainline_m": total_main, "total_submain_m": total_sub,
                        "total_manifold_m": total_man, "n_valves": len(d["valves"]),
                        "unused_edges": len(tree["unused_edges"])})
        old = S.get("network")
        save(S, "network", payload)
        if old != payload:
            for k in ("lateral", "manifold", "hydraulic"):
                S.pop(k, None)
        st.success("✅ Network layout saved.")
        goto("design")
    if tree["unattached"]:
        caption("Saving is disabled until every valve is reached from the source.")
    dev_panel(S, "network")


def _pipe_table(d, kind):
    pipes = [p for p in d["pipes"] if p["kind"] == kind]
    if not pipes:
        st.caption("None drawn.")
        return
    df = pd.DataFrame([{"Delete": False, "Pipe": p["id"], "Vertices": len(p["points"]),
                        "Length (m)": round(N.polyline_length(p["points"]), 1)}
                       for p in pipes])
    ed = st.data_editor(df, hide_index=True, width="stretch", key=f"nw_tbl_{kind}_"
                        f"{len(pipes)}_{sum(len(p['points']) for p in pipes)}",
                        column_config={"Pipe": st.column_config.TextColumn(disabled=True),
                                       "Vertices": st.column_config.NumberColumn(disabled=True),
                                       "Length (m)": st.column_config.NumberColumn(disabled=True)})
    kill = {r["Pipe"] for r in ed.to_dict("records") if r["Delete"]}
    if kill and st.button(f"🗑️ Delete {len(kill)} selected", key=f"nw_del_{kind}"):
        d["pipes"] = [p for p in d["pipes"] if p["id"] not in kill]
        d["generated"] = False
        st.rerun()
