"""
The design report as a self-contained HTML document. UI-free.

One file, no external assets: the plan is an inline SVG drawn from the same
geometry the design used, the styling is embedded, and the document prints
to PDF from any browser. The verdict opens the report, for the same reason
it opens the workbook: a report is forwarded on its own.
"""

from __future__ import annotations

import html
import math
from datetime import date

from . import checks as CH

__all__ = ["design_report_html", "plan_svg"]

CSS = """
body{font-family:Inter,Segoe UI,Arial,sans-serif;color:#1a1a2e;margin:0;background:#fff}
.wrap{max-width:980px;margin:0 auto;padding:28px 36px}
h1{font-size:26px;margin:0 0 4px;color:#0078d4}
h2{font-size:18px;margin:26px 0 8px;padding-bottom:6px;border-bottom:2px solid #0078d4}
h3{font-size:14px;margin:16px 0 6px}
.sub{color:#6c757d;font-size:13px}
table{border-collapse:collapse;width:100%;font-size:12.5px;margin:6px 0 10px}
th{background:#1a1a2e;color:#f8f9fa;text-align:left;padding:6px 8px;font-weight:600}
td{border-bottom:1px solid #e0e6ed;padding:5px 8px;vertical-align:top}
.kpis{display:flex;flex-wrap:wrap;gap:10px;margin:10px 0}
.kpi{flex:1 1 150px;border:1px solid #e0e6ed;border-radius:8px;padding:10px}
.kpi .k{font-size:11px;text-transform:uppercase;color:#6c757d;letter-spacing:.5px}
.kpi .v{font-size:20px;font-weight:700;font-family:Consolas,monospace}
.box{border-left:4px solid #0078d4;background:#f0f7fd;padding:10px 14px;border-radius:6px;margin:10px 0;font-size:13px}
.bad{border-left-color:#f44336;background:#fdecea}
.ok{border-left-color:#00c853;background:#e8f8ee}
.warn{border-left-color:#ff9800;background:#fff6e6}
.pass{color:#0a8a3a;font-weight:700}.fail{color:#c62828;font-weight:700}
.foot{margin-top:30px;font-size:11px;color:#6c757d}
@media print{.wrap{padding:0}h2{page-break-after:avoid}}
"""


def _e(x) -> str:
    return html.escape(str(x))


def _table(rows: list[dict]) -> str:
    if not rows:
        return "<p class='sub'>None.</p>"
    cols = list(rows[0].keys())
    head = "".join(f"<th>{_e(c)}</th>" for c in cols)
    body = "".join("<tr>" + "".join(f"<td>{_e(r.get(c, ''))}</td>" for c in cols) + "</tr>"
                   for r in rows)
    return f"<table><tr>{head}</tr>{body}</table>"


def _kpis(items) -> str:
    return "<div class='kpis'>" + "".join(
        f"<div class='kpi'><div class='k'>{_e(k)}</div><div class='v'>{_e(v)}</div></div>"
        for k, v in items) + "</div>"


def plan_svg(S: dict, width: int = 900) -> str:
    op = S.get("operation") or {}
    net = S.get("network") or {}
    man = S.get("manifold") or {}
    poly = op.get("boundary_local")
    if not poly:
        return ""
    pts = list(poly) + ([net["source"]] if net.get("source") else [])
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    x0, x1, y0, y1 = min(xs) - 10, max(xs) + 10, min(ys) - 10, max(ys) + 10
    sc = width / max(x1 - x0, 1e-6)
    h = (y1 - y0) * sc

    def P(p):
        return f"{(p[0]-x0)*sc:.1f},{(y1-p[1])*sc:.1f}"
    out = [f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 {width} {h:.0f}' "
           f"width='100%' style='max-height:620px;background:#f8fafb;border:1px solid "
           f"#c8d4e0;border-radius:6px'>"]
    out.append(f"<polygon points='{' '.join(P(p) for p in poly)}' fill='none' "
               f"stroke='#1a1a2e' stroke-width='2'/>")
    for su in op.get("subunits", []):
        for seg in su.get("_segments", []):
            out.append(f"<line x1='{P(seg[0]).split(',')[0]}' y1='{P(seg[0]).split(',')[1]}' "
                       f"x2='{P(seg[1]).split(',')[0]}' y2='{P(seg[1]).split(',')[1]}' "
                       f"stroke='#2ec4b6' stroke-width='0.6' opacity='0.6'/>")
    for mf in net.get("manifolds", []):
        out.append(f"<polyline points='{' '.join(P(p) for p in mf['points'])}' fill='none' "
                   f"stroke='#3d5a80' stroke-width='3'/>")
    edges, nodes, sizing = man.get("tree_edges"), man.get("tree_nodes"), man.get("tree_sizing")
    if edges and nodes and sizing:
        for key, s in sizing.items():
            e = edges[int(key)]
            col = "#e63946" if e["kind"] == "mainline" else "#ff9f1c"
            a, b = nodes[e["a"]], nodes[e["b"]]
            out.append(f"<polyline points='{P(a)} {P(b)}' stroke='{col}' stroke-width='4' fill='none'/>")
    else:
        for pp in net.get("pipes", []):
            col = "#e63946" if pp["kind"] == "mainline" else "#ff9f1c"
            out.append(f"<polyline points='{' '.join(P(p) for p in pp['points'])}' "
                       f"stroke='{col}' stroke-width='4' fill='none'/>")
    for v in net.get("valves", []):
        x, y = P(v["xy"]).split(",")
        out.append(f"<rect x='{float(x)-4}' y='{float(y)-4}' width='8' height='8' "
                   f"fill='#6f42c1' transform='rotate(45 {x} {y})'/>")
    if net.get("source"):
        x, y = P(net["source"]).split(",")
        out.append(f"<circle cx='{x}' cy='{y}' r='7' fill='#0078d4'/>"
                   f"<text x='{float(x)+10}' y='{float(y)+4}' font-size='12'>Source</text>")
    out.append("</svg>")
    return "".join(out)


def design_report_html(S: dict, version: str = "3.0.0") -> str:
    setup, wat, em = S.get("setup", {}), S.get("water", {}), S.get("emitter", {})
    op, lat, man = S.get("operation", {}), S.get("lateral", {}), S.get("manifold", {})
    qual, fert = S.get("quality", {}), S.get("fertigation", {})
    hy, pump, cost = S.get("hydraulic", {}), S.get("pump", {}), S.get("cost", {})
    checks = CH.design_checks(S)
    failed = [c for c in checks if not c[1]]
    verdict = ("<div class='box ok'><b>✓ PASSED</b> — all "
               f"{len(checks)} design checks passed. Independent verification against "
               "site-measured data and manufacturer specifications is still required "
               "before issue.</div>") if not failed else (
               f"<div class='box bad'><b>✗ NOT PASSED</b> — {len(failed)} of {len(checks)} "
               "design checks failed: " + _e("; ".join(c[0] for c in failed)) +
               ". This design must not be issued, tendered or constructed in this state.</div>")
    parts = [f"<!doctype html><html><head><meta charset='utf-8'><title>IRRI-DRIP design "
             f"report — {_e(setup.get('name') or 'untitled')}</title><style>{CSS}</style>"
             "</head><body><div class='wrap'>"]
    parts.append(f"<h1>Drip Irrigation System Design Report</h1><div class='sub'>"
                 + " · ".join(_e(t) for t in (
                     setup.get('name') or 'Untitled project', setup.get('location'),
                     f"IRRI-DRIP {version}", date.today().isoformat()) if t)
                 + "</div>")
    parts.append(verdict)

    parts.append("<h2>1. Executive summary</h2>")
    parts.append(_kpis([
        ("Net area", f"{setup.get('area_ha', 0):.2f} ha"),
        ("Crop", setup.get("crop", {}).get("name", "—")),
        ("Peak ETc,loc", f"{wat.get('etc', 0):.2f} mm/d"),
        ("Subunits / shifts", f"{op.get('n_subunits', 0)} / {op.get('shifts', 0)}"),
        ("Duty", f"{hy.get('q_duty', 0):.1f} m³/h @ {hy.get('h_duty', 0):.1f} m"),
        ("Motor", f"{pump.get('power', {}).get('motor_rating_kw', 0):.1f} kW"),
        ("Capital cost", f"{cost.get('total', 0):,.0f} EGP"),
        ("Per hectare", f"{cost.get('per_ha', 0):,.0f} EGP/ha"),
    ]))
    svg = plan_svg(S)
    if svg:
        parts.append("<h3>Network plan</h3>" + svg +
                     "<p class='sub'>Red: mainline · orange: submain · dark blue: manifolds · "
                     "teal: laterals · purple: subunit valves. Local metres about the field "
                     f"centroid; geometry: {_e(op.get('geometry_source', ''))}.</p>")

    parts.append("<h2>2. Crop water requirement</h2>")
    parts.append(_table([
        {"Item": "Method", "Value": wat.get("method") or "—"},
        {"Item": "Design month", "Value": wat.get("peak_month", "—")},
        {"Item": "ET₀ in design month", "Value": f"{wat.get('et0', 0):.2f} mm/day"},
        {"Item": "Kc / Kr", "Value": f"{wat.get('kc', 0):.2f} / {wat.get('kr', 0):.2f}"},
        {"Item": "Peak localised ETc", "Value": f"{wat.get('etc', 0):.2f} mm/day"},
        {"Item": "Leaching requirement", "Value": f"{wat.get('lr', 0)*100:.1f} %"
                                                  + (f" ({wat['lr_method']})"
                                                     if wat.get("lr_method") else "")},
        {"Item": "Season gross volume", "Value": f"{wat.get('season_volume_m3', 0):,.0f} m³"},
    ]))
    if wat.get("monthly"):
        parts.append(_table([{"Month": r["month"], "Days": r["days"],
                              "ET₀ mm/d": f"{r['et0']:.2f}", "Kc": f"{r['kc']:.2f}",
                              "ETc,loc mm/d": f"{r['etc_loc_mm_d']:.2f}",
                              "Gross mm": f"{r['gross_mm']:.1f}",
                              "Volume m³": f"{r['volume_m3']:,.0f}"}
                             for r in wat["monthly"] if r["days"]]))

    parts.append("<h2>3. Emitter, spacing and operation</h2>")
    parts.append(_table([
        {"Item": "Emitter", "Value": em.get("name", "—")},
        {"Item": "q = k·Hˣ", "Value": f"k {em.get('k', 0):.3f}, x {em.get('x', 0):.3f}, "
                                      f"{em.get('q_emitter', 0):.2f} L/h at {em.get('h_op', 0):.1f} m"},
        {"Item": "Spacing Se × Sl", "Value": f"{em.get('se', 0):.2f} × {em.get('sl', 0):.2f} m"},
        {"Item": "Wetted fraction Pw", "Value": f"{em.get('pw', 0)*100:.1f} %"},
        {"Item": "Application rate", "Value": f"{em.get('ia', 0):.2f} mm/h"},
        {"Item": "Interval / gross depth / set time",
         "Value": f"{op.get('interval', 0):.2f} d / {op.get('d_gross', 0):.1f} mm / "
                  f"{op.get('t_set', 0):.2f} h"},
        {"Item": "Subunits / shifts", "Value": f"{op.get('n_subunits', 0)} / {op.get('shifts', 0)}"},
        {"Item": "Schedule utilisation",
         "Value": f"{op.get('schedule', {}).get('utilisation_pct', 0):.0f} %"},
    ]))

    parts.append("<h2>4. Pipe network</h2><h3>Lateral</h3>")
    res = lat.get("res", {})
    parts.append(_table([
        {"Item": "Dripline", "Value": f"{lat.get('lateral', {}).get('nominal_mm', 0):.0f} mm "
                                       f"(ID {lat.get('lateral', {}).get('internal_mm', 0):.1f})"},
        {"Item": "Governing length", "Value": f"{lat.get('l_len', 0):.1f} m"},
        {"Item": "Head spread / allowable",
         "Value": f"{res.get('spread_m', 0):.3f} / {lat.get('dh_allow_lateral', 0):.3f} m"},
        {"Item": "Emission uniformity", "Value": f"{lat.get('eu', 0):.1f} %"},
        {"Item": "Velocity exponent m", "Value": f"{res.get('velocity_exponent', 0):.3f} "
                                                 f"({lat.get('exponent_mode', 'measured')})"},
    ]))
    parts.append("<h3>Manifolds (telescoped)</h3>")
    parts.append(_table([{
        "Subunit": sid, "Length m": f"{d['length_m']:.0f}",
        "Sections": " → ".join(f"{r['pipe']['nominal_mm']:.0f}×{r['length_m']:.0f}m"
                               for r in d["runs"]),
        "Spread m": f"{d['spread_m']:.3f}", "Valve head m": f"{d.get('valve_head_m', 0):.2f}",
        "OK": "✓" if d["satisfied"] else "✗"} for sid, d in (man.get("designs") or {}).items()]))
    parts.append("<h3>Mainline and submains</h3>")
    edges = man.get("tree_edges") or []
    parts.append(_table([{
        "Pipe": f"E{k}", "Kind": edges[int(k)]["kind"] if edges else "",
        "Length m": f"{s['length_m']:.1f}", "Design Q m³/h": f"{s['q_design_m3h']:.2f}",
        "Size": f"{s['pipe']['nominal_mm']:.0f} mm {s['pipe']['material']} PN{s['pipe']['pn_bar']:g}",
        "v m/s": f"{s['velocity_ms']:.2f}"} for k, s in sorted(
            (man.get("tree_sizing") or {}).items(), key=lambda kv: int(kv[0]))]))

    parts.append("<h2>5. Water quality, filtration, fertigation</h2>")
    parts.append(_table([
        {"Item": "Clogging hazard", "Value": qual.get("hazard", {}).get("overall", "not assessed")},
        {"Item": "Filtration aperture",
         "Value": f"{qual.get('filtration', {}).get('filtration_grade', {}).get('aperture_micron', 0):.0f} µm"},
        {"Item": "Filtration train", "Value": "; ".join(qual.get("filtration", {}).get("train", []))},
        {"Item": "Filter loss (clean + backflush)",
         "Value": f"{qual.get('filt_clean', 0) + qual.get('filt_dirty', 0):.1f} m"},
        {"Item": "Injector", "Value": f"{fert.get('injector', '—')}, {fert.get('inj_loss', 0):.1f} m"},
    ]))

    parts.append("<h2>6. Hydraulics and pump</h2>")
    parts.append(_table([{"Shift": r["Shift"], "Flow m³/h": f"{r['Flow (m³/h)']:.2f}",
                          "Network inlet m": f"{r['Network inlet (m)']:.2f}",
                          "TDH m": f"{r['TDH (m)']:.2f}", "Critical valve": r["Critical valve"]}
                         for r in hy.get("per_shift", [])]))
    opp = pump.get("operating_point") or {}
    parts.append(_table([
        {"Item": "Pump", "Value": pump.get("pump_name", "—")},
        {"Item": "Operating point", "Value": f"{opp.get('q_m3h', 0):.1f} m³/h at {opp.get('h_m', 0):.1f} m, "
                                             f"η {opp.get('eta', 0)*100:.0f} %"},
        {"Item": "Brake power / motor", "Value": f"{pump.get('power', {}).get('brake_kw', 0):.2f} / "
                                                 f"{pump.get('power', {}).get('motor_rating_kw', 0):.1f} kW"},
        {"Item": "Season energy", "Value": f"{pump.get('kwh', 0):,.0f} kWh, "
                                           f"{pump.get('energy_per_m3', 0):.3f} kWh/m³"},
    ]))

    parts.append("<h2>7. Cost</h2>")
    parts.append(_table([{"Category": k, "Amount EGP": f"{v:,.0f}"}
                         for k, v in (cost.get("by_category") or {}).items()]))
    parts.append(_kpis([("Subtotal", f"{cost.get('subtotal', 0):,.0f} EGP"),
                        ("Total with margins", f"{cost.get('total', 0):,.0f} EGP"),
                        ("Annual cost", f"{cost.get('annual_cost', 0):,.0f} EGP/yr"),
                        ("Cost per m³", f"{cost.get('cost_per_m3', 0):.2f} EGP/m³")]))

    parts.append("<h2>8. Design checks</h2>")
    parts.append("<table><tr><th>Check</th><th>Result</th><th>Measured</th><th>Criterion</th></tr>"
                 + "".join(f"<tr><td>{_e(n)}</td><td class='{'pass' if ok else 'fail'}'>"
                           f"{'✓ pass' if ok else '✗ FAIL'}</td><td>{_e(m)}</td><td>{_e(c)}</td></tr>"
                           for n, ok, m, c in sorted(checks, key=lambda c: c[1])) + "</table>")

    parts.append("<h2>9. Methods, assumptions and limits</h2><ul style='font-size:13px'>"
                 "<li>Head loss: Darcy–Weisbach with the Swamee–Jain friction factor for every "
                 "pipe; Hazen–Williams is not used.</li>"
                 "<li>Lateral: Christiansen multi-outlet factor at the velocity exponent measured "
                 "from the friction factor; judged on the head spread over the whole line.</li>"
                 "<li>Manifolds: marched outlet by outlet with the real row flows, telescoped in up "
                 "to three sizes.</li>"
                 "<li>Mainline: the drawn tree, each pipe sized for its largest shift flow, solved "
                 "shift by shift.</li>"
                 "<li>ET₀: FAO-56 Penman–Monteith; localisation Kr = GC/0.85 (Keller &amp; Bliesner); "
                 "leaching requirement by the drip high-frequency form ECw/(2·max ECe), max ECe "
                 "being the zero-yield salinity of FAO-29 Table 4 (FAO-29 eq. 9 on the "
                 "threshold where no zero-yield value is known).</li>"
                 "<li>Emitter, pipe, pump and unit-rate catalogues are INDICATIVE and must be "
                 "replaced with supplier data.</li>"
                 "<li>Clogging thresholds follow Bucks &amp; Nakayama as reproduced in FAO/ASABE "
                 "literature — verify against the original source.</li>"
                 "<li>No field calibration: nothing here has been compared with measured "
                 "pressures or discharges on site.</li></ul>")
    parts.append("<div class='box warn'><b>Disclaimer.</b> IRRI-DRIP is a design-support tool. "
                 "No output may be issued as an executed design without independent verification "
                 "by a qualified irrigation engineer against site-measured data and manufacturer "
                 "specifications.</div>")
    parts.append("<div class='foot'>Generated by IRRI-DRIP — Water Management Research Institute, "
                 "National Water Research Center. Drip counterpart to OpenIrri (PY-IRRI).</div>")
    parts.append("</div></body></html>")
    return "".join(parts)
