"""
Reports & Export — OpenIrri's five tabs: Project Dashboard, Design Report,
Technical Specs, Export Data, Data Inspector.

The verdict travels with every file (v0.8.2 rule): the workbook opens on a
Verdict sheet, every drawing carries a NOT PASSED stamp when a check failed,
file names end in _NOT-PASSED, and the report opens on the verdict. The
checks themselves live in engine/checks.py, where they are tested.
"""

from __future__ import annotations

import io
import json

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from engine import kernels as K
from engine import dxf as DXF
from engine import report as REP
from engine import fieldnet as FN
from engine import kml as KML
from engine import checks as CH
from engine import report_doc as RD
from engine import state as STATE
from engine import APP_VERSION
from modules import layout as LAY
from modules import plots as PL
from modules.common import (page_header, sub_header, section, cards, banner, note,
                            caption, save, stage_guard, require, goto, dev_panel, context_strip)


def show(ctx):
    S = ctx["S"]
    page_header("Reports & Export",
                "The design at a glance, the full report, the technical specification, "
                "every export, and the raw project data.")
    _completeness(S, ctx["pages"])
    if not require(S, ("setup", "water", "emitter", "operation", "network", "lateral",
                       "manifold", "hydraulic", "pump", "cost")):
        return
    context_strip(S)

    checks = CH.design_checks(S)
    vd = REP.verdict_from_checks(checks)
    S["verdict"] = vd

    tabs = st.tabs(["📊 Project Dashboard", "📝 Design Report", "📋 Technical Specs",
                    "📥 Export Data", "🔍 Data Inspector"])
    with tabs[0]:
        _dashboard(S, checks, vd)
    with tabs[1]:
        _report(S, ctx, vd)
    with tabs[2]:
        _specs(S)
    with tabs[3]:
        _exports(S, checks, vd)
    with tabs[4]:
        _inspector(S)


def _completeness(S, pages):
    done = [(label, bool(S.get(state))) for key, label, _m, state in pages if key != "report"]
    n = sum(1 for _, ok in done if ok)
    with st.expander(f"📋 Data completeness — {n} of {len(done)} modules saved",
                     expanded=n < len(done)):
        cols = st.columns(2)
        for i, (label, ok) in enumerate(done):
            cols[i % 2].markdown(f"{'✅' if ok else '⬜'} {label}")


# ------------------------------------------------------------------ dashboard

def _dashboard(S, checks, vd):
    sub_header("Project Dashboard")
    setup, op, hy, pump, cost = S["setup"], S["operation"], S["hydraulic"], S["pump"], S["cost"]
    n_fail = vd["checks_failed"]
    if n_fail:
        banner("bad", f"<b>NOT PASSED — {n_fail} of {vd['checks_applied']} design checks "
                      f"failed:</b> {'; '.join(vd['failed_checks'])}.")
    else:
        banner("ok", f"<b>All {vd['checks_applied']} design checks passed.</b>")
    cards([("Net area", f"{setup['area_ha']:.2f}", "ha", "accent"),
           ("Subunits / shifts", f"{op['n_subunits']} / {op['shifts']}", "", "neutral"),
           ("Duty", f"{hy['q_duty']:.1f} m³/h @ {hy['h_duty']:.1f}", "m", "neutral"),
           ("Motor", f"{pump['power']['motor_rating_kw']:.1f}", "kW", "neutral")])
    cards([("Capital cost", f"{cost['total']:,.0f}", "EGP", "accent"),
           ("Per hectare", f"{cost['per_ha']:,.0f}", "EGP/ha", "neutral"),
           ("Season energy", f"{pump['kwh']:,.0f}", "kWh", "neutral"),
           ("Cost per m³", f"{cost.get('cost_per_m3', 0):.2f}", "EGP/m³", "neutral")])
    net, man = S["network"], S["manifold"]
    labels, pipes = {}, []
    edges, nodes = man.get("tree_edges") or [], man.get("tree_nodes") or []
    for k, s in (man.get("tree_sizing") or {}).items():
        e = edges[int(k)]
        pid = f"E{k}"
        pipes.append({"id": pid, "kind": e["kind"], "points": [nodes[e["a"]], nodes[e["b"]]]})
        labels[pid] = f"{s['pipe']['nominal_mm']:.0f} mm {s['pipe']['material']}"
    c1, c2 = st.columns([3, 2])
    with c1:
        st.plotly_chart(PL.plan_view(boundary=op["boundary_local"], subunits=op["subunits"],
                                     shift_of=op["assignment"], manifolds=net["manifolds"],
                                     pipes=pipes, pipe_labels=labels, valves=net["valves"],
                                     source=net["source"], height=540, title="Designed network"),
                        width="stretch", key="dash_plan")
    with c2:
        st.plotly_chart(PL.cost_donut(cost.get("by_category") or {}), width="stretch",
                        key="dash_cost")
        t = hy["tdh"]
        st.plotly_chart(PL.head_breakdown(
            ["Static + lift", "Emitter", "Pipes", "Valves & fittings", "Filters", "Injector"],
            [t["static_m"], t["emitter_head_m"], t["pipe_friction_m"], t["minor_m"],
             t["filter_m"], t["fertigation_m"]], "TDH breakdown"), width="stretch",
            key="dash_tdh")


# --------------------------------------------------------------------- report

def _report(S, ctx, vd):
    sub_header("Design Report")
    doc = RD.design_report_html(S, ctx["version"])
    stem = REP.stamped_filename(K.safe_filename(S["setup"].get("name", "")), vd)
    st.download_button("⬇ Download the design report (.html — prints to PDF)",
                       doc.encode("utf-8"), file_name=f"IRRI-DRIP_{stem}_report.html",
                       mime="text/html", key="dl_report")
    caption("A single self-contained file: open it in any browser and print to PDF. The "
            "verdict opens the document.")
    if hasattr(st, "iframe"):
        st.iframe(doc, height=900)
    else:                                          # Streamlit before 1.50
        components.html(doc, height=900, scrolling=True)


# ---------------------------------------------------------------------- specs

def _specs(S):
    sub_header("Technical Specifications")
    em, lat, man, op = S["emitter"], S["lateral"], S["manifold"], S["operation"]
    qual, pump = S.get("quality", {}), S["pump"]
    section("Dripline")
    st.dataframe(pd.DataFrame([
        {"Item": "Emitter", "Specification": em["name"]},
        {"Item": "Discharge", "Specification": f"{em['q_emitter']:.2f} L/h at {em['h_op']:.1f} m "
                                               f"(k {em['k']:.3f}, x {em['x']:.3f}, CV {em['cv']:.3f})"},
        {"Item": "Emitter spacing", "Specification": f"{em['se']:.2f} m"},
        {"Item": "Dripline", "Specification": f"{lat['lateral']['nominal_mm']:.0f} mm, ID "
                                              f"{lat['lateral']['internal_mm']:.1f} mm, PN{lat['lateral']['pn_bar']:g}"},
        {"Item": "Lateral spacing", "Specification": f"{em['sl']:.2f} m, {em.get('lat_per_row', 1)} per row"},
        {"Item": "Flow passage / filtration",
         "Specification": f"{em['passage']:.2f} mm / {qual.get('filtration', {}).get('filtration_grade', {}).get('aperture_micron', 0):.0f} µm"},
    ]), hide_index=True, width="stretch")
    section("Manifold schedule")
    st.dataframe(pd.DataFrame([{
        "Subunit": sid, "Section": f"{r['from_m']:.0f}–{r['to_m']:.0f} m (branch {r['branch']})",
        "Pipe": f"{r['pipe']['nominal_mm']:.0f} mm {r['pipe']['material']} PN{r['pipe']['pn_bar']:g}",
        "Length (m)": round(r["length_m"], 1)} for sid, d in man["designs"].items()
        for r in d["runs"]]), hide_index=True, width="stretch", height=300)
    section("Mainline and submain schedule")
    by = {}
    for s in (man.get("tree_sizing") or {}).values():
        k = f"{s['pipe']['nominal_mm']:.0f} mm {s['pipe']['material']} PN{s['pipe']['pn_bar']:g}"
        by[k] = by.get(k, 0.0) + s["length_m"]
    st.dataframe(pd.DataFrame([{"Pipe": k, "Length (m)": round(v, 1)} for k, v in by.items()]),
                 hide_index=True, width="stretch")
    section("Valves and head control")
    st.dataframe(pd.DataFrame([
        {"Item": "Subunit control valves", "Quantity": str(len(S["network"]["valves"]))},
        {"Item": "Pressure regulators", "Quantity": str(len(man.get("regulators", [])))},
        {"Item": "Filtration train", "Quantity": "; ".join(qual.get("filtration", {}).get("train", []))},
        {"Item": "Fertigation", "Quantity": f"{S.get('fertigation', {}).get('injector', '—')}"},
    ]), hide_index=True, width="stretch")
    section("Pump")
    opp = pump["operating_point"]
    st.dataframe(pd.DataFrame([
        {"Item": "Pump", "Value": pump["pump_name"]},
        {"Item": "Duty required", "Value": f"{pump['q_duty_required']:.1f} m³/h at {pump['h_duty_required']:.1f} m"},
        {"Item": "Operating point", "Value": f"{opp['q_m3h']:.1f} m³/h at {opp['h_m']:.1f} m"},
        {"Item": "Efficiency at operating point", "Value": f"{opp['eta']*100:.1f} %"},
        {"Item": "Motor", "Value": f"{pump['power']['motor_rating_kw']:.1f} kW"},
    ]), hide_index=True, width="stretch")


# -------------------------------------------------------------------- exports

def _exports(S, checks, vd):
    sub_header("Export Data")
    setup, wat, em = S["setup"], S["water"], S["emitter"]
    op, lat, man = S["operation"], S["lateral"], S["manifold"]
    qual, pump, cost = S.get("quality", {}), S["pump"], S["cost"]

    section("Design checks")
    # Failures first: the reader must not have to hunt for them.
    ordered = sorted(checks, key=lambda c: c[1])
    cdf = pd.DataFrame([{"Check": c, "Result": "✓ pass" if ok else "✗ FAIL",
                         "Measured": val, "Criterion": crit}
                        for c, ok, val, crit in ordered])
    view = pd.DataFrame([{"Check": r["Check"], "Result": r["Result"],
                          "Measured vs criterion": f"{r['Measured']}   ({r['Criterion']})"}
                         for r in cdf.to_dict("records")])
    st.dataframe(view, hide_index=True, width="stretch", height=38 + 35 * len(view))
    if vd["checks_failed"]:
        banner("bad", f"<b>{vd['checks_failed']} of {vd['checks_applied']} design checks "
                      f"failed:</b> {'; '.join(vd['failed_checks'])}. Resolve them before "
                      "issuing this design.")
        banner("warn", "<b>These files are marked as not passed.</b> The workbook opens on a "
                       "Verdict sheet, the drawings carry a NOT PASSED stamp and the file "
                       "names end in <code>_NOT-PASSED</code>.")
    else:
        banner("ok", f"<b>All {vd['checks_applied']} design checks passed.</b>")

    summary = _summary_rows(S)
    df = pd.DataFrame(summary, columns=["Quantity", "Value", "Unit"])
    vrows = REP.verdict_rows(vd)
    xbuf = io.BytesIO()
    with pd.ExcelWriter(xbuf, engine="openpyxl") as xw:
        # First sheet, so the verdict is what opens.
        pd.DataFrame(vrows).to_excel(xw, sheet_name="Verdict", index=False)
        df.to_excel(xw, sheet_name="Design summary", index=False)
        cdf.to_excel(xw, sheet_name="Design checks", index=False)
        pd.DataFrame([{k: v for k, v in s.items() if not k.startswith("_") and
                       k not in ("feeds", "outlets", "rows", "centre")}
                      for s in op["subunits"]]).to_excel(xw, sheet_name="Subunits", index=False)
        pd.DataFrame([{"Subunit": sid, "Branch": r["branch"], "From (m)": r["from_m"],
                       "To (m)": r["to_m"], "Length (m)": r["length_m"],
                       "Pipe": f"{r['pipe']['nominal_mm']:.0f} {r['pipe']['material']}",
                       "Q in (m3/h)": r["q_in_m3h"]}
                      for sid, d in man["designs"].items() for r in d["runs"]]
                     ).to_excel(xw, sheet_name="Manifolds", index=False)
        pd.DataFrame([{"Pipe": f"E{k}", "Length (m)": s["length_m"],
                       "Design Q (m3/h)": s["q_design_m3h"],
                       "Pipe size": f"{s['pipe']['nominal_mm']:.0f} {s['pipe']['material']}",
                       "v (m/s)": s["velocity_ms"]}
                      for k, s in (man.get("tree_sizing") or {}).items()]
                     ).to_excel(xw, sheet_name="Mainline", index=False)
        pd.DataFrame(cost["items"]).to_excel(xw, sheet_name="Bill of quantities", index=False)
        if wat.get("monthly"):
            pd.DataFrame(wat["monthly"]).to_excel(xw, sheet_name="Monthly demand", index=False)
        if qual.get("schedule"):
            pd.DataFrame(qual["schedule"]).to_excel(xw, sheet_name="Maintenance", index=False)
        pd.DataFrame([
            {"Assumption": "Head loss method",
             "Value": "Darcy-Weisbach (not Hazen-Williams: the C coefficient is not defined "
                      "for the Reynolds range of a dripline)"},
            {"Assumption": "Multi-outlet factor",
             "Value": REP.exponent_assumption(lat["res"], lat.get("n_em", 1))},
            {"Assumption": "Manifolds", "Value": "Outlet-by-outlet march with real row flows, "
                                                 "telescoped in up to three sizes"},
            {"Assumption": "Mainline", "Value": "Drawn tree sized for the largest shift flow per "
                                                "pipe; solved shift by shift"},
            {"Assumption": "Friction factor", "Value": "Swamee-Jain (explicit Colebrook-White), "
                                                       "roughness by material"},
            {"Assumption": "Emitter local loss", "Value": f"equivalent length {lat['le']:.3f} m per emitter"},
            {"Assumption": "Uniformity criterion", "Value": "Keller & Karmeli emission uniformity EU"},
            {"Assumption": "Leaching requirement",
             "Value": wat.get("lr_method") or "Rhoades high-frequency form ECw/(2 max ECe)"},
            {"Assumption": "Localisation factor", "Value": "Keller & Bliesner Kr = GC/0.85"},
            {"Assumption": "System curve", "Value": "Emitter term scales as (Q/Qd)^(1/x)"},
            {"Assumption": "Emitter catalogue", "Value": "INDICATIVE - replace with manufacturer data"},
            {"Assumption": "Pipe catalogue", "Value": "INDICATIVE - verify internal diameters with supplier"},
            {"Assumption": "Pump curves", "Value": "Generic type curves unless a manufacturer curve was entered"},
            {"Assumption": "Unit rates", "Value": "PLACEHOLDERS - not quotations"},
            {"Assumption": "Clogging thresholds",
             "Value": "Bucks & Nakayama as reproduced in FAO/ASABE literature - verify against source"},
        ]).to_excel(xw, sheet_name="Assumptions", index=False)
    stem = REP.stamped_filename(K.safe_filename(setup.get("name", "")), vd)
    tag = "" if vd["passed"] else "  — NOT PASSED"
    c1, c2 = st.columns(2)
    with c1:
        st.download_button(f"⬇  Design workbook (.xlsx){tag}", xbuf.getvalue(),
                           file_name=f"IRRI-DRIP_{stem}.xlsx", key="dl_xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        try:
            st.download_button(f"⬇  Site plan drawing (.dxf){tag}",
                               DXF.site_plan_dxf(S).encode("ascii", errors="replace"),
                               file_name=f"IRRI-DRIP_{stem}_site_plan.dxf", mime="application/dxf",
                               key="dl_dxf_site")
        except Exception as exc:                  # noqa: BLE001
            banner("warn", f"The site-plan DXF could not be generated: {exc}")
        try:
            st.download_button(f"⬇  Hydraulic schematic (.dxf){tag}",
                               DXF.network_dxf(S).encode("ascii", errors="replace"),
                               file_name=f"IRRI-DRIP_{stem}_schematic.dxf",
                               mime="application/dxf", key="dl_dxf")
        except Exception as exc:                  # noqa: BLE001
            banner("warn", f"The schematic DXF could not be generated: {exc}")
    with c2:
        _network_kml(S, stem, tag)
        snapshot = STATE.project_json(S, APP_VERSION)
        st.download_button("⬇  Project file (.json)", snapshot.encode("utf-8"),
                           file_name=f"IRRI-DRIP_{stem}.json", mime="application/json",
                           key="dl_json")
    caption("The site plan is the network on the real field, in local metres, every pipe "
            "labelled with its size. The schematic is the v1 drawing of one subunit per "
            "shift. The project file reopens the whole design on Home › Project File Manager.")
    banner("bad", "<b>Disclaimer.</b> IRRI-DRIP is a design-support tool. Its catalogues, "
                  "unit rates and several coefficients are indicative. No output may be issued "
                  "as an executed design without independent verification by a qualified "
                  "irrigation engineer against site-measured data and manufacturer "
                  "specifications.")


def _network_kml(S, stem, tag):
    """The designed network, georeferenced — only when a real boundary exists."""
    lay = S.get("layout") or {}
    op, net, man = S["operation"], S["network"], S["manifold"]
    centre = lay.get("centre")
    gps = lay.get("boundary_gps")
    if not (centre and gps) or lay.get("assumed_rectangle"):
        st.caption("No georeferenced boundary, so no KML of the network.")
        return
    laterals = []
    for su in op["subunits"]:
        for seg in su.get("_segments", []):
            laterals.append({"name": f"Lateral ({su['id']})",
                             "points": LAY.to_gps(list(seg), tuple(centre)),
                             "over": False, "description": su["id"]})
    edges, nodes = man.get("tree_edges") or [], man.get("tree_nodes") or []
    main_pts = []
    for k, s in (man.get("tree_sizing") or {}).items():
        e = edges[int(k)]
        main_pts.append(LAY.to_gps([nodes[e["a"]], nodes[e["b"]]], tuple(centre)))
    first_man = net["manifolds"][0]["points"] if net["manifolds"] else None
    kml = KML.network_kml(stem, gps, laterals,
                          manifold_latlon=LAY.to_gps(first_man, tuple(centre)) if first_man else None,
                          summary=f"IRRI-DRIP {APP_VERSION} network: {op['n_subunits']} subunits, "
                                  f"{op['shifts']} shifts.")
    st.download_button(f"⬇  Network on the real field (.kml){tag}", kml.encode("utf-8"),
                       file_name=f"IRRI-DRIP_{stem}_network.kml",
                       mime="application/vnd.google-earth.kml+xml", key="dl_kml")


def _summary_rows(S):
    setup, wat, em = S["setup"], S["water"], S["emitter"]
    op, lat, man = S["operation"], S["lateral"], S["manifold"]
    qual, pump, cost, hy = S.get("quality", {}), S["pump"], S["cost"], S["hydraulic"]
    return [
        ("Project", setup["name"] or "—", ""), ("Location", setup["location"] or "—", ""),
        ("Net area", f"{setup['area_ha']:.2f}", "ha"), ("Crop", setup["crop"]["name"], ""),
        ("Soil", setup["soil"]["name"], ""), ("Design month", str(wat.get("peak_month")), ""),
        ("Peak ET0", f"{wat['et0']:.2f}", "mm/day"),
        ("Kc / Kr", f"{wat['kc']:.2f} / {wat['kr']:.2f}", ""),
        ("Peak ETc", f"{wat['etc']:.2f}", "mm/day"),
        ("Leaching requirement", f"{wat['lr']*100:.1f}", "%"),
        ("Season gross volume", f"{wat.get('season_volume_m3', 0):,.0f}", "m3"),
        ("Emitter", em["name"], ""), ("Emitter k / x", f"{em['k']:.3f} / {em['x']:.3f}", ""),
        ("Emitter discharge", f"{em['q_emitter']:.2f}", "L/h"),
        ("Spacing Se x Sl", f"{em['se']:.2f} x {em['sl']:.2f}", "m"),
        ("Wetted fraction Pw", f"{em['pw']*100:.1f}", "%"),
        ("Application rate", f"{em['ia']:.2f}", "mm/h"),
        ("RAW", f"{op['raw']:.1f}", "mm"), ("Interval", f"{op['interval']:.2f}", "days"),
        ("Gross depth", f"{op['d_gross']:.1f}", "mm"), ("Set time", f"{op['t_set']:.2f}", "h"),
        ("Subunits", f"{op['n_subunits']}", ""), ("Shifts", f"{op['shifts']}", ""),
        ("Schedule feasible", "yes" if op["schedule"]["feasible"] else "NO", ""),
        ("Lateral length checked", f"{lat['l_len']:.1f}", "m"),
        ("Lateral pipe", f"{lat['lateral']['nominal_mm']:.0f} mm (ID {lat['lateral']['internal_mm']:.1f})", ""),
        ("Lateral head spread", f"{lat['res']['spread_m']:.3f}", "m"),
        ("Emission uniformity EU", f"{lat['eu']:.1f}", "%"),
        ("Manifolds within limit", f"{sum(d['satisfied'] for d in man['designs'].values())} / "
                                   f"{len(man['designs'])}", ""),
        ("Pressure regulators", f"{len(man.get('regulators', []))}", ""),
        ("Clogging hazard", qual.get("hazard", {}).get("overall", "not assessed"), ""),
        ("Duty flow", f"{hy['q_duty']:.2f}", "m3/h"), ("TDH", f"{hy['h_duty']:.2f}", "m"),
        ("Pump", pump["pump_name"], ""),
        ("Motor rating", f"{pump['power']['motor_rating_kw']:.1f}", "kW"),
        ("Energy intensity", f"{pump['energy_per_m3']:.3f}", "kWh/m3"),
        ("Capital cost", f"{cost['total']:,.0f}", "EGP"),
        ("Capital cost per ha", f"{cost['per_ha']:,.0f}", "EGP/ha"),
    ]


# ------------------------------------------------------------------ inspector

def _inspector(S):
    sub_header("Data Inspector")
    keys = [k for k in S.keys()]
    st.markdown(" · ".join(f"`{k}`" for k in keys))
    pick = st.selectbox("Inspect", keys, key="insp_key")
    with st.expander("📋 All Project Data Keys", expanded=True):
        data = S.get(pick)
        txt = json.dumps(data, indent=1, default=str, ensure_ascii=False)
        st.code(txt[:60000] + ("\n… (truncated)" if len(txt) > 60000 else ""), language="json")
