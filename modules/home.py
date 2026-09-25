"""
Home — Project Setup, Field Layout & Blocks, Design Workflow.

The three tabs of OpenIrri's home page, in the same order and with the same
names. The drip specifics live inside them: the water source carries its
available discharge and static lift, the field layout carries the boundary,
the water source position and the crop blocks the network is laid on.
"""

from __future__ import annotations

import html
import json
import os
import zlib
from datetime import datetime

import pandas as pd
import streamlit as st

from engine import blocks as B
from modules import layout as LAY
from modules import plots as PL
from modules.common import (page_header, sub_header, section, cards, banner, note,
                            caption, save, welcome, goto, dev_panel, clear_drafts,
                            stable_editor)

SOURCES = ["Nile / canal (surface)", "Agricultural drain (surface)", "Deep well",
           "Shallow well", "Pressurised municipal supply", "Reservoir / pond"]
QUALITY = ["Good", "Moderate", "Poor"]

WORKFLOW = [
    ("1️⃣", "Field Layout", "Draw the field boundary, mark the water source and cut the "
                           "crop blocks — Home › Field Layout & Blocks."),
    ("2️⃣", "Crop Water Requirements", "Monthly ET₀ by FAO-56 Penman–Monteith, the Kc "
                                       "curve, localisation Kr, leaching, peak month."),
    ("3️⃣", "Emitter Selection", "Emitter q = k·Hˣ, spacing and wetted fraction, "
                                 "application rate, the uniformity budget."),
    ("4️⃣", "Operational Design", "Depth, interval and set time; subunits cut from the "
                                  "field; subunits packed into shifts."),
    ("5️⃣", "Pipe Network Layout", "Mainline, submains, manifolds and valves on the "
                                   "field plan — generated, then edited by hand."),
    ("6️⃣", "Pipe Network Design", "Lateral hydraulics, telescoped manifolds, the "
                                   "mainline tree sized shift by shift."),
    ("7️⃣", "Water Quality & Filtration", "Clogging hazard, filtration train, chemical "
                                          "maintenance and fertigation."),
    ("8️⃣", "Hydraulic Design", "Pressure at every valve, head at the source in every "
                                "shift, the drip system curve."),
    ("9️⃣", "Pump Selection", "Pump matched on the drip system curve, operating point, "
                              "power and seasonal energy."),
    ("🔟", "Cost Estimation", "Bill of quantities measured from the network, capital "
                              "cost and economic analysis."),
    ("📊", "Reports & Export", "Design checks, report, workbook, DXF, KML and the "
                              "project file."),
]


def show(ctx):
    S = ctx["S"]
    page_header("Drip Irrigation System Design")
    welcome("Welcome! 👋",
            "IRRI-DRIP designs a complete drip irrigation system based on FAO "
            "standards and the methods drip actually needs — Darcy–Weisbach "
            "friction, emission uniformity, the wetted fraction in the soil store, "
            "telescoped manifolds and a mainline sized shift by shift. Start by "
            "setting up your project and defining your field layout.")
    _user_guide_button()

    tabs = st.tabs(["📋 Project Setup", "🗺️ Field Layout & Blocks", "📊 Design Workflow"])
    with tabs[0]:
        project_setup_tab(ctx)
    with tabs[1]:
        field_layout_tab(ctx)
    with tabs[2]:
        design_workflow_tab(ctx)
    dev_panel(S, "setup")


# ===========================================================================
# TAB 1 — Project Setup
# ===========================================================================

def net_area_ha(S) -> tuple[float, str]:
    """Net irrigated area and where it came from: drip blocks > boundary > typed."""
    lay = S.get("layout") or {}
    blocks = lay.get("blocks") or []
    drip = [b for b in blocks if b.get("irrigation") == "Drip"]
    if drip:
        return sum(b["area_ha"] for b in drip), f"{len(drip)} drip block(s)"
    if lay.get("area_ha"):
        return float(lay["area_ha"]), ("assumed rectangle" if lay.get("assumed_rectangle")
                                       else "field boundary")
    return 0.0, ""


def project_setup_tab(ctx):
    S = ctx["S"]
    crops = ctx["crops"]
    saved = S.get("setup", {})
    # Unsaved edits live in a draft, so leaving the page and coming back does
    # not silently discard them (v2.0.0 lost a typed project name that way).
    draft = st.session_state.get("setup_draft") or {}
    prev = {**saved, **draft}
    sub_header("Project Setup")

    crop_names = [c["name"] for c in crops["crops"]]
    soil_names = [s["name"] for s in crops["soils"]]
    measured, measured_src = net_area_ha(S)

    col1, col2 = st.columns(2)
    with col1:
        name = st.text_input("Project Name", prev.get("name", ""),
                             help="Enter a unique name for your irrigation project")
        location = st.text_input("Location", prev.get("location", ""),
                                 help="Project location (station, governorate)")
        default_area = prev.get("area_ha", measured if measured > 0 else 5.0)
        area_ha = st.number_input("Total Area (hectares)", min_value=0.01,
                                  max_value=10000.0, value=float(default_area), step=0.1,
                                  help="Net irrigated area. Taken from the drip blocks or "
                                       "the boundary when they exist.")
        altitude = st.number_input("Altitude (m above sea level)", min_value=-200.0,
                                   max_value=3000.0, value=float(prev.get("altitude", 20.0)),
                                   step=1.0, help="Enters the psychrometric constant of "
                                                  "FAO-56 Penman–Monteith")
    with col2:
        crop_name = st.selectbox("Primary Crop Type", crop_names,
                                 index=prev.get("crop_idx", 0),
                                 help="IRRI-DRIP designs one crop per project")
        soil_name = st.selectbox("Soil Type", soil_names, index=prev.get("soil_idx", 2))
        source = st.selectbox("Water Source", SOURCES, index=prev.get("source_idx", 0))
        wq = st.selectbox("Water Quality", QUALITY,
                          index=QUALITY.index(prev.get("water_quality", "Good")),
                          help="A first indication. The clogging assessment on the "
                               "Water Quality page replaces it with measured values.")

    if measured > 0:
        if abs(area_ha - measured) <= 0.005:
            caption(f"Area taken from the {measured_src}: <b>{measured:.3f} ha</b>.")
        else:
            banner("warn",
                   f"<b>This area does not match the field layout.</b> The "
                   f"{measured_src} measure{'s' if 'block' not in measured_src else ''} "
                   f"<b>{measured:.3f} ha</b>; this page is set to <b>{area_ha:.3f} ha</b> "
                   f"({100*abs(area_ha-measured)/max(measured,1e-9):.1f} % different). "
                   "Overriding is legitimate — headlands, tracks and buildings come "
                   "out of the net area — but it should be deliberate.")

    section("💧 Water Source & Operating Hours")
    c1, c2, c3 = st.columns(3)
    with c1:
        q_avail = st.number_input("Available discharge (m³/h)", min_value=0.1,
                                  max_value=100000.0, value=float(prev.get("q_avail", 40.0)),
                                  step=1.0, help="What the source can deliver continuously")
    with c2:
        static_lift = st.number_input("Static lift, suction + delivery (m)", min_value=0.0,
                                      max_value=500.0,
                                      value=float(prev.get("static_lift", 8.0)), step=0.5,
                                      help="From the water level at the source to the pump "
                                           "outlet datum")
    with c3:
        hours_day = st.number_input("Maximum operating hours per day", min_value=1.0,
                                    max_value=24.0, value=float(prev.get("hours_day", 18.0)),
                                    step=0.5)

    section("⛰️ Terrain")
    c1, c2 = st.columns(2)
    with c1:
        slope = st.number_input("Ground slope along the laterals (%) — positive uphill "
                                "from the manifold", min_value=-15.0, max_value=15.0,
                                value=float(prev.get("slope", 0.0)), step=0.1)
    with c2:
        slope_across = st.number_input("Ground slope along the manifolds (%) — positive "
                                       "uphill from the valve", min_value=-15.0,
                                       max_value=15.0,
                                       value=float(prev.get("slope_across", 0.0)), step=0.1)

    crop = next(c for c in crops["crops"] if c["name"] == crop_name)
    soil = next(s for s in crops["soils"] if s["name"] == soil_name)
    note(f"<b>{html.escape(crop_name)}</b> defaults — Kc mid {crop['kc_mid']}, root depth "
         f"{crop['root_depth_m']} m, depletion p {crop['depletion_p']}, ECe threshold "
         f"{crop['ece_threshold_ds_m']} dS/m, mature ground cover "
         f"{int(crop['ground_cover']*100)} %. <b>{html.escape(soil_name)}</b> — FC "
         f"{soil['fc_mm_per_m']} mm/m, WP {soil['wp_mm_per_m']} mm/m, reference wetted "
         f"diameter {soil['wetted_diameter_ref_m']} m. All editable on the next pages; "
         "the bundled tables are indicative, not measured for your site.")

    st.session_state["setup_draft"] = {
        "name": name, "location": location, "area_ha": area_ha, "altitude": altitude,
        "crop_idx": crop_names.index(crop_name), "soil_idx": soil_names.index(soil_name),
        "source_idx": SOURCES.index(source), "water_quality": wq, "q_avail": q_avail,
        "static_lift": static_lift, "hours_day": hours_day, "slope": slope,
        "slope_across": slope_across}
    if saved and any(saved.get(k) != v for k, v in st.session_state["setup_draft"].items()):
        banner("warn", "<b>Unsaved changes.</b> The values above differ from the saved "
                       "project information; the other pages still use the saved values "
                       "until you press <b>Save Project Information</b>.")

    col_save1, col_save2 = st.columns(2)
    with col_save1:
        if st.button("💾 Save Project Information", type="primary", key="save_setup"):
            save(S, "setup", {
                "name": name, "location": location, "altitude": altitude,
                "area_ha": area_ha, "source": source, "source_idx": SOURCES.index(source),
                "water_quality": wq,
                "area_from_map": measured > 0 and abs(area_ha - measured) <= 0.005,
                "area_measured_ha": measured or None,
                "q_avail": q_avail, "static_lift": static_lift, "hours_day": hours_day,
                "crop": crop, "crop_idx": crop_names.index(crop_name),
                "soil": soil, "soil_idx": soil_names.index(soil_name),
                "slope": slope, "slope_across": slope_across,
                "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            })
            st.success("✅ Project information saved to the current session!")
            st.rerun()
    with col_save2:
        if not name:
            st.info("💡 Enter a project name to enable saving the project file")
        else:
            from engine import state as STATE
            snap = STATE.project_json(S, ctx["version"])
            from engine import kernels as K
            st.download_button("📥 Download project file (.json)", snap.encode("utf-8"),
                               file_name=f"IRRI-DRIP_{K.safe_filename(name)}_project.json",
                               mime="application/json", key="dl_project")

    st.markdown("---")
    st.markdown("### 📂 Project File Manager")
    caption("Nothing is stored on a server. A project lives in this session until you "
            "download its file; opening a file restores every page exactly as it was "
            "saved, so the design can be reproduced by a third party.")
    c1, c2 = st.columns([3, 1])
    with c1:
        up = st.file_uploader("Open a saved IRRI-DRIP project (.json)", type=["json"],
                              key="open_project")
    with c2:
        st.write("")
        if st.button("🆕 New project", key="new_project"):
            clear_drafts()
            st.session_state.S = {}
            st.session_state.page = "home"
            st.rerun()
    if up is not None:
        try:
            doc = json.loads(up.getvalue().decode("utf-8"))
            data = doc.get("S") if isinstance(doc, dict) and "S" in doc else doc
            if not isinstance(data, dict):
                raise ValueError("not an IRRI-DRIP project file")
            if st.button(f"📂 Load “{up.name}” (replaces the current session)",
                         type="primary", key="load_project"):
                clear_drafts()
                if "_stamps" not in data:
                    # A file written before v2.0.1: take its stages as consistent
                    # at the moment it was saved, and track changes from here on.
                    from engine import state as STATE
                    STATE.stamp_all(data)
                st.session_state.S = data
                st.session_state.page = "home"
                st.rerun()
            ver = doc.get("irri_drip_project") if isinstance(doc, dict) else None
            # 2.x files carry the same state layout as 3.0 and open unchanged;
            # only a 1.x file predates it.
            if ver and ver.split(".")[0].isdigit() and int(ver.split(".")[0]) < 2:
                banner("warn", f"This file was written by IRRI-DRIP {ver}. Pages whose "
                               "stored results predate version 2 will ask to be "
                               "recomputed.")
        except Exception as exc:                  # noqa: BLE001
            banner("bad", f"This file could not be read as a project: {html.escape(str(exc))}")


# ===========================================================================
# TAB 2 — Field Layout & Blocks
# ===========================================================================

def _workflow_step(S) -> int:
    lay = S.get("layout") or {}
    if not lay.get("boundary_local"):
        return 0
    if not lay.get("source_local"):
        return 1
    if not lay.get("blocks"):
        return 2
    if any(not b.get("irrigation") for b in lay["blocks"]):
        return 3
    return 4


def _progress(step: int):
    steps = [("Draw Boundary", "📐"), ("Water Source", "💧"), ("Create Blocks", "🌱"),
             ("Assign Irrigation", "🚿"), ("Ready", "✅")]
    cols = st.columns(5)
    for i, (nm, ic) in enumerate(steps):
        if i < step:
            bg, icon, op, fw = "#28a745", "✓", 1.0, "normal"
        elif i == step:
            bg, icon, op, fw = "#007bff", ic, 1.0, "bold"
        else:
            bg, icon, op, fw = "#6c757d", ic, 0.5, "normal"
        cols[i].markdown(
            f'<div class="idr-step" style="background:{bg};opacity:{op}">'
            f'<div class="ic">{icon}</div><div class="nm" style="font-weight:{fw}">{nm}'
            f'</div></div>', unsafe_allow_html=True)


def field_layout_tab(ctx):
    S = ctx["S"]
    sub_header("🗺️ Field Layout Workflow")
    _progress(_workflow_step(S))
    st.markdown("---")
    t = st.tabs(["1️⃣ Draw Field Boundary", "2️⃣ Mark Water Source",
                 "3️⃣ Create Crop Blocks", "4️⃣ Assign Irrigation", "5️⃣ Review & Continue"])
    with t[0]:
        LAY.boundary_step(S)
    with t[1]:
        water_source_step(S)
    with t[2]:
        create_blocks_step(ctx)
    with t[3]:
        assign_irrigation_step(ctx)
    with t[4]:
        review_step(ctx)


def water_source_step(S):
    st.markdown("### 💧 Mark Water Source Location")
    lay = S.get("layout") or {}
    if not lay.get("boundary_local"):
        st.warning("⚠️ Please complete Step 1 (Draw Field Boundary) first.")
        return
    has_gps = bool(lay.get("boundary_gps")) and bool(lay.get("centre"))
    st.markdown(
        '<div class="info-box"><b>Instructions:</b><ol>'
        '<li>Place the source where the pump and head control will stand — well, '
        'canal intake, reservoir.</li>'
        '<li>It may be inside or outside the boundary; the mainline is routed from it.</li>'
        '<li>Coordinates are local metres from the field centre (x east, y north)'
        + (', or latitude / longitude.' if has_gps else '.') + '</li></ol></div>',
        unsafe_allow_html=True)

    cur = lay.get("source_local")
    poly = lay["boundary_local"]
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    default = cur or [min(xs) - 20.0, min(ys) - 20.0]

    col1, col2 = st.columns([2, 1])
    with col2:
        st.markdown("#### Water Source Info")
        mode = st.radio("Enter the position as",
                        (["Local metres", "Latitude / longitude"] if has_gps
                         else ["Local metres"]), horizontal=False, key="ws_mode")
        if mode == "Local metres":
            sx = st.number_input("x (m, east of centre)", value=float(default[0]),
                                 step=5.0, key="ws_x")
            sy = st.number_input("y (m, north of centre)", value=float(default[1]),
                                 step=5.0, key="ws_y")
            new_local = [sx, sy]
        else:
            g0 = LAY.to_gps([default], tuple(lay["centre"]))[0]
            la = st.number_input("Latitude", value=float(g0[0]), format="%.6f",
                                 step=0.0001, key="ws_lat")
            lo = st.number_input("Longitude", value=float(g0[1]), format="%.6f",
                                 step=0.0001, key="ws_lon")
            new_local = _gps_to_local([la, lo], tuple(lay["centre"]))
        if cur:
            st.success("✅ Water source marked!")
            st.caption(f"📍 local ({cur[0]:.1f}, {cur[1]:.1f}) m")
        if st.button("✅ Save Water Source", type="primary", key="ws_save"):
            lay["source_local"] = [float(new_local[0]), float(new_local[1])]
            if has_gps:
                lay["source_gps"] = LAY.to_gps([lay["source_local"]], tuple(lay["centre"]))[0]
            for k in ("network", "hydraulic"):
                S.pop(k, None)
            st.rerun()
        if cur and st.button("🗑️ Remove Water Source", key="ws_clear"):
            lay.pop("source_local", None)
            lay.pop("source_gps", None)
            st.rerun()
    with col1:
        fig = PL.plan_view(boundary=poly, blocks=lay.get("blocks"),
                           source=new_local, height=460,
                           title="Field plan (local metres)")
        st.plotly_chart(fig, width="stretch", key="ws_plan")


def _gps_to_local(latlon, centre):
    """One point to local metres about the SAME centre the boundary used."""
    import math
    lat0, lon0 = centre
    mx = LAY.M_PER_DEG_LAT * math.cos(math.radians(lat0))
    return [(latlon[1] - lon0) * mx, (latlon[0] - lat0) * LAY.M_PER_DEG_LAT]


def create_blocks_step(ctx):
    S = ctx["S"]
    crops = ctx["crops"]
    st.markdown("### 🌱 Create Crop/Tree Blocks")
    lay = S.get("layout") or {}
    if not lay.get("boundary_local"):
        st.warning("⚠️ Please complete Step 1 (Draw Field Boundary) first.")
        return
    st.markdown(
        '<div class="info-box"><b>Create internal blocks:</b><ul>'
        '<li>Each block is a distinct crop zone or management unit.</li>'
        '<li>Blocks are cut by equal AREA, not equal width, so shifts come out of '
        'similar duration on an irregular field.</li>'
        '<li>A block can be excluded from the drip design — a track, a building plot, '
        'or an area to be designed for sprinklers in OpenIrri.</li></ul></div>',
        unsafe_allow_html=True)

    blocks = lay.get("blocks") or []
    if blocks:
        st.markdown("#### 📊 Existing Blocks")
        cols = st.columns(min(3, len(blocks)))
        for i, blk in enumerate(blocks):
            icon = "💧" if blk.get("irrigation") == "Drip" else "🌧️"
            cols[i % 3].markdown(
                f'<div style="background:{blk["color"]}33;border:2px solid {blk["color"]};'
                f'padding:15px;border-radius:10px;margin-bottom:10px;">'
                f'<h4 style="margin:0;color:{blk["color"]};">{html.escape(blk["name"])}</h4>'
                f'<p style="margin:5px 0;">🌱 {html.escape(blk.get("crop_name", ""))}</p>'
                f'<p style="margin:5px 0;">📐 {blk["area_ha"]:.2f} ha</p>'
                f'<p style="margin:5px 0;">{icon} {blk.get("irrigation", "")}</p></div>',
                unsafe_allow_html=True)
        st.metric("Total Block Area", f"{sum(b['area_ha'] for b in blocks):.2f} ha",
                  delta=f"{sum(b['area_ha'] for b in blocks) - lay.get('area_ha', 0):.2f} ha "
                        "vs. boundary")
        st.markdown("---")

    st.markdown("#### ➕ Create Blocks")
    method = st.radio("How would you like to create the blocks?",
                      ["🟦 Whole field as one block", "✂️ Split into equal-area blocks",
                       "📝 Manual block coordinates"], horizontal=True, key="blk_method")
    crop_names = [c["name"] for c in crops["crops"]]
    primary = (S.get("setup") or {}).get("crop_idx", 0)
    if method.startswith("🟦"):
        if st.button("Create one block from the whole field", type="primary",
                     key="blk_whole"):
            lay["blocks"] = [B.make_block(1, lay["boundary_local"], primary,
                                          crop_names[primary], "Drip", "Block 1")]
            _clear_downstream(S)
            st.rerun()
    elif method.startswith("✂️"):
        c1, c2 = st.columns(2)
        with c1:
            n = st.number_input("Number of blocks", 2, 20, 3, 1, key="blk_n")
        with c2:
            axis = st.selectbox("Cut", ["Across the long axis (blocks follow one "
                                        "another along the laterals)",
                                        "Along the long axis (blocks side by side)"],
                                key="blk_axis")
        bearing = float(lay.get("bearing_deg", 0.0))
        cut_bearing = bearing if axis.startswith("Across") else bearing + 90.0
        pieces = B.split_equal_area(lay["boundary_local"], cut_bearing, int(n))
        preview = [B.make_block(i + 1, p, primary, crop_names[primary]) for i, p in
                   enumerate(pieces)]
        st.plotly_chart(PL.plan_view(boundary=lay["boundary_local"], blocks=preview,
                                     source=lay.get("source_local"), height=420,
                                     title="Preview"), width="stretch", key="blk_prev")
        if st.button(f"Create {len(pieces)} blocks", type="primary", key="blk_split"):
            lay["blocks"] = preview
            _clear_downstream(S)
            st.rerun()
    else:
        caption("One vertex per line as <code>x, y</code> in local metres (x east, y "
                "north of the field centre).")
        txt = st.text_area("Block vertices", height=120, key="blk_txt",
                           placeholder="-50, -60\n50, -60\n50, 0\n-50, 0")
        bname = st.text_input("Block name", f"Block {len(blocks) + 1}", key="blk_name")
        if st.button("➕ Add block", key="blk_add"):
            try:
                pts = [[float(a) for a in ln.replace(";", ",").split(",")[:2]]
                       for ln in txt.strip().splitlines() if ln.strip()]
                if len(pts) < 3:
                    raise ValueError("at least three vertices are needed")
                blocks.append(B.make_block(len(blocks) + 1, pts, primary,
                                           crop_names[primary], "Drip", bname))
                lay["blocks"] = blocks
                _clear_downstream(S)
                st.rerun()
            except Exception as exc:              # noqa: BLE001
                banner("bad", f"Could not read the vertices: {html.escape(str(exc))}")

    if blocks:
        st.markdown("---")
        st.markdown("#### 🔧 Manage Blocks")
        c1, c2 = st.columns(2)
        with c1:
            sel = st.selectbox("Select block to delete",
                               [f"{b['id']}: {b['name']}" for b in blocks], key="blk_del_sel")
        with c2:
            st.write("")
            if st.button("🗑️ Delete Selected Block", key="blk_del"):
                bid = int(sel.split(":")[0])
                lay["blocks"] = [b for b in blocks if b["id"] != bid]
                _clear_downstream(S)
                st.rerun()


def _clear_downstream(S):
    for k in ("operation", "network", "lateral", "manifold", "hydraulic"):
        S.pop(k, None)


def assign_irrigation_step(ctx):
    S = ctx["S"]
    crops = ctx["crops"]
    st.markdown("### 🚿 Assign Irrigation System Type")
    lay = S.get("layout") or {}
    blocks = lay.get("blocks") or []
    if not blocks:
        st.warning("⚠️ Please create crop blocks in Step 3 first.")
        return
    st.markdown(
        '<div class="info-box"><b>Choose the system for each block:</b><ul>'
        '<li><b>💧 Drip:</b> designed here. Trees, orchards, vegetables, and any crop '
        'where water is scarce or saline.</li>'
        '<li><b>🌧️ Sprinkler:</b> excluded from this design — design it in OpenIrri, '
        'the sprinkler companion program.</li></ul></div>', unsafe_allow_html=True)

    c1, c2 = st.columns(2)
    with c1:
        if st.button("💧 All Drip", width="stretch", key="all_drip"):
            for b in blocks:
                b["irrigation"] = "Drip"
            _clear_downstream(S)
            st.rerun()
    with c2:
        if st.button("🌧️ All Sprinkler (OpenIrri)", width="stretch", key="all_spr"):
            for b in blocks:
                b["irrigation"] = "Sprinkler"
            _clear_downstream(S)
            st.rerun()

    st.markdown("#### Individual Block Assignment")
    crop_names = [c["name"] for c in crops["crops"]]
    sig = "|".join(f"{b['id']}:{b['area_ha']:.4f}" for b in blocks)
    ed = stable_editor(
        f"blk_assign_{zlib.crc32(sig.encode())}",
        lambda: pd.DataFrame([{"Block": b["name"], "Area (ha)": round(b["area_ha"], 3),
                               "Crop": b.get("crop_name") or crop_names[0],
                               "Irrigation": b.get("irrigation") or "Drip"} for b in blocks]),
        hide_index=True, width="stretch",
        column_config={
            "Block": st.column_config.TextColumn(disabled=False),
            "Area (ha)": st.column_config.NumberColumn(disabled=True, format="%.3f"),
            "Crop": st.column_config.SelectboxColumn(options=crop_names),
            "Irrigation": st.column_config.SelectboxColumn(options=["Drip", "Sprinkler"]),
        })
    if st.button("💾 Save assignment", type="primary", key="blk_assign_save"):
        for b, row in zip(blocks, ed.to_dict("records")):
            b["name"] = row["Block"]
            b["crop_name"] = row["Crop"]
            b["crop_idx"] = crop_names.index(row["Crop"])
            b["irrigation"] = row["Irrigation"]
        _clear_downstream(S)
        st.success("✅ Assignment saved.")
        st.rerun()

    drip = [b for b in blocks if b.get("irrigation") == "Drip"]
    spr = [b for b in blocks if b.get("irrigation") != "Drip"]
    st.markdown("#### 📊 Assignment Summary")
    c1, c2 = st.columns(2)
    c1.metric("💧 Drip Irrigation", f"{len(drip)} blocks",
              f"{sum(b['area_ha'] for b in drip):.2f} ha")
    c2.metric("🌧️ Sprinkler (OpenIrri)", f"{len(spr)} blocks",
              f"{sum(b['area_ha'] for b in spr):.2f} ha")
    primary = (S.get("setup") or {}).get("crop", {}).get("name")
    other = sorted({b.get("crop_name") for b in drip} - {primary})
    if primary and other:
        banner("warn", f"Drip blocks carry crops other than the primary crop "
                       f"(<b>{html.escape(primary)}</b>): {html.escape(', '.join(other))}. "
                       "IRRI-DRIP sizes the system on ONE crop's peak demand. If the "
                       "other crop peaks higher, design with it as the primary crop, or "
                       "run one project per crop.")


def review_step(ctx):
    S = ctx["S"]
    st.markdown("### ✅ Review & Continue")
    lay = S.get("layout") or {}
    if not lay.get("boundary_local"):
        st.warning("⚠️ Please complete Step 1 (Draw Field Boundary) first.")
        return
    blocks = lay.get("blocks") or []
    summ = B.blocks_summary(blocks, lay.get("area_ha"))
    cards([
        ("Field area", f"{lay.get('area_ha', 0):.3f}", "ha", "accent"),
        ("Drip area", f"{summ['drip_area_ha']:.3f}", "ha", "ok" if summ["n_drip"] else "warn"),
        ("Blocks", f"{summ['n_blocks']}", "", "neutral"),
        ("Long-axis bearing", f"{lay.get('bearing_deg', 0):.0f}", "° from N", "neutral"),
    ])
    st.plotly_chart(PL.plan_view(boundary=lay["boundary_local"], blocks=blocks,
                                 source=lay.get("source_local"), height=520,
                                 title="Field layout"), width="stretch", key="rev_plan")
    missing = []
    if not lay.get("source_local"):
        missing.append("the water source position (step 2)")
    if not blocks:
        missing.append("the blocks (step 3) — the whole field will be treated as one block")
    if not S.get("setup"):
        missing.append("the Project Setup tab")
    if missing:
        banner("warn", "Still to do: " + "; ".join(missing) + ".")
    if lay.get("assumed_rectangle"):
        banner("warn", "The field is an <b>assumed rectangle</b>, not a surveyed boundary.")
    if st.button("✅ Continue to Crop Water Requirements →", type="primary",
                 key="rev_next"):
        goto("water")


# ===========================================================================
# TAB 3 — Design Workflow
# ===========================================================================

def completion(S, pages) -> dict:
    done = [key for key, _l, _m, state in pages if S.get(state)]
    return {"completed": len(done), "total": len(pages),
            "overall": int(round(100 * len(done) / max(1, len(pages)))), "done": done}


def design_workflow_tab(ctx):
    S = ctx["S"]
    sub_header("Design Workflow")
    lay = S.get("layout") or {}
    blocks = lay.get("blocks") or []
    if lay.get("boundary_local"):
        summ = B.blocks_summary(blocks)
        st.success(f"✅ **Field layout defined** — "
                   f"{'assumed rectangle' if lay.get('assumed_rectangle') else 'boundary'} "
                   f"{lay.get('area_ha', 0):.2f} ha; {summ['n_blocks']} block(s), drip "
                   f"{summ['drip_area_ha']:.2f} ha.")
    else:
        st.warning("⚠️ Please complete the **Field Layout & Blocks** tab to define your "
                   "field before starting design. Without a boundary the program works "
                   "on an assumed rectangle.")

    cols = st.columns(2)
    for i, (icon, title, desc) in enumerate(WORKFLOW):
        with cols[i % 2]:
            st.markdown(f'<div class="info-box"><h4>{icon} {title}</h4><p>{desc}</p></div>',
                        unsafe_allow_html=True)

    if (S.get("setup") or {}).get("name"):
        st.markdown("---")
        sub_header("Project Status")
        prog = completion(S, ctx["pages"])
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Overall Progress", f"{prog['overall']}%")
        c2.metric("Modules Completed", f"{prog['completed']}/{prog['total']}")
        c3.metric("Project Area", f"{S['setup'].get('area_ha', 0):.2f} ha")
        c4.metric("Last Updated", (S["setup"].get("last_updated") or "—").split()[0])
        st.progress(prog["overall"] / 100)

    with st.expander("📐 What this program does differently from a sprinkler design"):
        for head, body in [
            ("Darcy–Weisbach with Swamee–Jain, not Hazen–Williams.",
             "The Hazen–Williams C is calibrated for mains in rough turbulent flow; a "
             "16 mm dripline runs smooth-turbulent where C is not defined."),
            ("The velocity exponent is measured, not assumed.",
             "The multi-outlet factor uses the exponent the friction factor actually "
             "implies; the conventional m = 2 answer is reported beside it."),
            ("Head SPREAD, not the difference between the two ends.",
             "On a falling line the head dips and recovers; the check is on the range."),
            ("Emission uniformity, not Christiansen's CU.",
             "EU combines manufacturing variation with hydraulic variation."),
            ("The wetted fraction is inside the soil store.",
             "Only the wetted volume holds plant-available water under drip."),
            ("Subunits from geometry, shifts from water.",
             "The number of manifolds comes from the field; the number of shifts from "
             "the source. Version 1 confused the two."),
            ("A drip system curve, not a parabola.",
             "Emitters impose H ∝ Q^(1/x); for compensating emitters the curve is "
             "nearly vertical and a parabola picks the wrong pump."),
        ]:
            st.markdown(f"**{head}** {body}")
        banner("warn", "<b>Design-support tool.</b> Catalogues, unit rates and several "
                       "coefficients are indicative. No output may be issued as an "
                       "executed design without independent verification by a qualified "
                       "irrigation engineer against site-measured data and manufacturer "
                       "specifications.")


GUIDE_PDF = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "docs", "IRRI-DRIP_User_Guide_AR.pdf")


@st.cache_data(show_spinner=False)
def _guide_bytes(path: str, mtime: float) -> bytes:
    with open(path, "rb") as fh:
        return fh.read()


def _user_guide_button():
    """The Arabic step-by-step user guide (docs/), offered on the Home page."""
    if not os.path.exists(GUIDE_PDF):
        return
    c1, c2 = st.columns([1, 2])
    with c1:
        st.download_button("📖 دليل المستخدم بالعربية (PDF)",
                           _guide_bytes(GUIDE_PDF, os.path.getmtime(GUIDE_PDF)),
                           file_name="IRRI-DRIP_User_Guide_AR.pdf", mime="application/pdf",
                           key="dl_user_guide", width="stretch")
    with c2:
        caption("A detailed step-by-step guide in Arabic, written for a first-time "
                "user: every page, every field, with annotated screenshots and a "
                "worked example.")
