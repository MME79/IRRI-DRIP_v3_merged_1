"""
IRRI-DRIP charts, drawn with Plotly as OpenIrri draws its own.

Same library, same template, same pipe colours (OpenIrri's CAD standard:
mainline red, submain orange, lateral teal), same graph-paper plan view. The
data colours follow OpenIrri's palette; status is always paired with a text
label, never carried by colour alone.
"""

from __future__ import annotations

import math

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from modules import theme
from modules.theme import COLORS

PIPE = {"mainline": COLORS["pipe_mainline"], "submain": COLORS["pipe_submain"],
        "manifold": "#3d5a80", "lateral": COLORS["pipe_lateral"]}
SHIFT_COLOURS = ["#e63946", "#0078d4", "#2ec4b6", "#ff9f1c", "#6f42c1",
                 "#00a86b", "#d4a017", "#8c564b", "#17becf", "#bc5090",
                 "#7f7f7f", "#1f3a93"]
FONT = "Inter, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"


def _dark() -> bool:
    try:
        return theme.is_dark()
    except Exception:           # noqa: BLE001 — a chart must render regardless
        return False


def style(fig, title: str = "", height: int = 380, x: str = "", y: str = "",
          legend: bool = True):
    d = _dark()
    # Text colours are set explicitly: st.plotly_chart applies Streamlit's own
    # (light) chart theme on top of the template, which in dark mode left the
    # legend and titles dark grey on a dark canvas (v2.0.0 review).
    ink = theme.tokens(d)["ink"]
    fig.update_layout(
        template="plotly_dark" if d else "plotly_white",
        # An empty dict, not None: Streamlit renders a None title as the word
        # "undefined" above the chart.
        title=dict(text=title or "", font=dict(size=15, color=ink), x=0, xanchor="left",
                   y=0.98, yanchor="top"),
        height=height, font=dict(family=FONT, size=12, color=ink),
        margin=dict(l=60, r=20, t=60 if title else 30, b=50),
        showlegend=legend,
        # Legend below the chart, anchored to the figure's bottom edge: a
        # legend that wraps to several rows on a half-width column then pushes
        # the plot up instead of climbing into the title.
        legend=dict(orientation="h", yref="container", yanchor="bottom", y=0.0,
                    xanchor="left", x=0, font=dict(color=ink)),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor=COLORS["bg_card_dark"] if d else "#ffffff",
    )
    if x:
        fig.update_xaxes(title_text=x)
    if y:
        fig.update_yaxes(title_text=y)
    return fig


# ---------------------------------------------------------------------------
# Plan view on graph paper
# ---------------------------------------------------------------------------

def _closed(pts):
    return list(pts) + [pts[0]] if pts else []


def plan_view(boundary=None, blocks=None, source=None, subunits=None,
              shift_of=None, rows_geometry=None, manifolds=None, pipes=None,
              valves=None, pipe_labels=None, drawing=None, snap_points=None,
              height=600, title=""):
    """
    The field in local metres on OpenIrri's graph paper: 10 m minor and 50 m
    major grid, equal axes so a right angle looks like one.
    """
    d = _dark()
    fig = go.Figure()
    if boundary:
        b = _closed(boundary)
        fig.add_trace(go.Scatter(x=[p[0] for p in b], y=[p[1] for p in b],
                                 mode="lines", name="Field boundary",
                                 line=dict(color="#1a1a2e" if not d else "#f8f9fa",
                                           width=2.5),
                                 hoverinfo="skip"))
    for blk in blocks or []:
        pts = _closed(blk["polygon_local"])
        excluded = blk.get("irrigation") != "Drip"
        fig.add_trace(go.Scatter(
            x=[p[0] for p in pts], y=[p[1] for p in pts], mode="lines",
            fill="toself", name=f"{blk['name']} ({blk.get('irrigation', '')})",
            line=dict(color=blk["color"], width=1.5, dash="dot" if excluded else "solid"),
            fillcolor=_rgba(blk["color"], 0.08 if excluded else 0.16),
            hovertext=f"{blk['name']}: {blk.get('crop_name', '')}, "
                      f"{blk['area_ha']:.2f} ha, {blk.get('irrigation', '')}",
            hoverinfo="text"))
    if subunits:
        for su in subunits:
            sh = (shift_of or {}).get(su["id"], 0)
            col = SHIFT_COLOURS[(sh - 1) % len(SHIFT_COLOURS)] if sh else "#999999"
            xs, ys = [], []
            for r in su.get("_segments", []):
                xs += [r[0][0], r[1][0], None]
                ys += [r[0][1], r[1][1], None]
            if xs:
                fig.add_trace(go.Scatter(
                    x=xs, y=ys, mode="lines", line=dict(color=col, width=1),
                    opacity=0.55, name=f"Shift {sh}" if sh else "Unassigned",
                    legendgroup=f"shift{sh}", showlegend=False, hoverinfo="skip"))
            c = su["centre"]
            fig.add_trace(go.Scatter(
                x=[c[0]], y=[c[1]], mode="markers+text",
                marker=dict(size=10, color=col, symbol="square"),
                text=[f"{su['id']}<br>S{sh}" if sh else su["id"]],
                textposition="top center", textfont=dict(size=10),
                name=f"Shift {sh}" if sh else "Unassigned", legendgroup=f"shift{sh}",
                hovertext=f"{su['id']} · shift {sh} · {su['q_m3h']:.1f} m³/h · "
                          f"{su['area_ha']:.2f} ha · {su['n_laterals']} laterals",
                hoverinfo="text", showlegend=False))
        for sh in sorted({(shift_of or {}).get(s["id"], 0) for s in subunits}):
            col = SHIFT_COLOURS[(sh - 1) % len(SHIFT_COLOURS)] if sh else "#999999"
            fig.add_trace(go.Scatter(x=[None], y=[None], mode="markers",
                                     marker=dict(size=10, color=col, symbol="square"),
                                     name=f"Shift {sh}" if sh else "Unassigned",
                                     legendgroup=f"shift{sh}"))
    if rows_geometry:
        xs, ys = [], []
        for seg in rows_geometry:
            xs += [seg[0][0], seg[1][0], None]
            ys += [seg[0][1], seg[1][1], None]
        fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines", name="Laterals",
                                 line=dict(color=PIPE["lateral"], width=0.8),
                                 opacity=0.6, hoverinfo="skip"))
    for mf in manifolds or []:
        pts = mf["points"]
        fig.add_trace(go.Scatter(x=[p[0] for p in pts], y=[p[1] for p in pts],
                                 mode="lines", line=dict(color=PIPE["manifold"], width=3),
                                 name="Manifolds", legendgroup="manifold",
                                 hovertext=mf.get("label", mf.get("subunit", "")),
                                 hoverinfo="text"))
    for pp in pipes or []:
        pts = pp["points"]
        kind = pp.get("kind", "mainline")
        lab = (pipe_labels or {}).get(pp["id"], pp["id"])
        fig.add_trace(go.Scatter(x=[p[0] for p in pts], y=[p[1] for p in pts],
                                 mode="lines", line=dict(color=PIPE.get(kind, "#e63946"),
                                                         width=4 if kind == "mainline" else 3),
                                 name=kind.capitalize(), legendgroup=kind,
                                 hovertext=lab, hoverinfo="text"))
    seen = set()
    for t in fig.data:
        g = t.legendgroup
        if g in ("mainline", "submain", "manifold"):
            t.showlegend = g not in seen
            seen.add(g)
    if valves:
        fig.add_trace(go.Scatter(
            x=[v["xy"][0] for v in valves], y=[v["xy"][1] for v in valves],
            mode="markers", name="Subunit valves",
            marker=dict(symbol="diamond", size=10, color="#6f42c1",
                        line=dict(color="white", width=1)),
            hovertext=[v["id"] for v in valves], hoverinfo="text"))
    if source:
        fig.add_trace(go.Scatter(x=[source[0]], y=[source[1]], mode="markers+text",
                                 name="Water source / pump",
                                 marker=dict(symbol="star", size=18, color="#0078d4",
                                             line=dict(color="white", width=1)),
                                 text=["Source"], textposition="bottom center"))
    if drawing:
        fig.add_trace(go.Scatter(x=[p[0] for p in drawing], y=[p[1] for p in drawing],
                                 mode="lines+markers", name="Line being drawn",
                                 line=dict(color="#ff6b35", width=3, dash="dash"),
                                 marker=dict(size=9, color="#ff6b35")))
    if snap_points:
        fig.add_trace(go.Scatter(x=[p[0] for p in snap_points],
                                 y=[p[1] for p in snap_points], mode="markers",
                                 name="Snap points", showlegend=False,
                                 marker=dict(size=7, color="rgba(0,120,212,0.10)"),
                                 hovertemplate="(%{x:.0f}, %{y:.0f}) m<extra></extra>"))
    grid = "#2a3441" if d else "#e0e6ed"
    grid_major = "#3d4a5c" if d else "#c8d1dc"
    fig.update_xaxes(showgrid=True, gridcolor=grid_major, dtick=50,
                     minor=dict(showgrid=True, gridcolor=grid, dtick=10),
                     zeroline=False, title_text="x (m, east)")
    fig.update_yaxes(showgrid=True, gridcolor=grid_major, dtick=50,
                     minor=dict(showgrid=True, gridcolor=grid, dtick=10),
                     zeroline=False, title_text="y (m, north)",
                     scaleanchor="x", scaleratio=1)
    style(fig, title, height)
    fig.update_layout(plot_bgcolor="#f8fafb" if not d else COLORS["bg_canvas_dark"],
                      dragmode="pan", hovermode="closest")
    return fig


def _rgba(hex_colour: str, alpha: float) -> str:
    h = hex_colour.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


# ---------------------------------------------------------------------------
# Crop water
# ---------------------------------------------------------------------------

def monthly_et0(rows):
    fig = go.Figure(go.Bar(x=[r["month"] for r in rows], y=[r["et0"] for r in rows],
                           marker_color=COLORS["primary"], name="ET₀",
                           hovertemplate="%{x}: %{y:.2f} mm/day<extra></extra>"))
    return style(fig, "Reference evapotranspiration ET₀ by month", 340, "", "ET₀ (mm/day)",
                 legend=False)


def kc_curve(stages, kc_ini, kc_mid, kc_end):
    from engine import climate as C
    l_ini, l_dev, l_mid, l_late = stages
    days = list(range(0, l_ini + l_dev + l_mid + l_late + 1))
    kcs = [C.kc_daily(d, kc_ini, kc_mid, kc_end, l_ini, l_dev, l_mid, l_late) for d in days]
    fig = go.Figure(go.Scatter(x=days, y=kcs, mode="lines", fill="tozeroy",
                               line=dict(color=COLORS["accent_green"], width=3),
                               fillcolor="rgba(0,200,83,0.12)", name="Kc"))
    for x, lab in ((l_ini, "Development"), (l_ini + l_dev, "Mid-season"),
                   (l_ini + l_dev + l_mid, "Late season")):
        fig.add_vline(x=x, line=dict(color="#adb5bd", dash="dot"),
                      annotation_text=lab, annotation_position="top")
    return style(fig, "Crop coefficient curve (FAO-56)", 320, "Days after planting", "Kc",
                 legend=False)


def monthly_requirement(rows):
    fig = make_subplots(specs=[[{"secondary_y": False}]])
    m = [r["month"] for r in rows]
    fig.add_trace(go.Bar(x=m, y=[r["gross_mm"] for r in rows], name="Gross requirement (mm)",
                         marker_color=COLORS["primary"]))
    fig.add_trace(go.Bar(x=m, y=[r["net_mm"] for r in rows], name="Net requirement (mm)",
                         marker_color=COLORS["pipe_lateral"]))
    fig.add_trace(go.Bar(x=m, y=[r["peff_mm"] for r in rows], name="Effective rain (mm)",
                         marker_color="#adb5bd"))
    fig.update_layout(barmode="group")
    return style(fig, "Monthly irrigation requirement", 360, "", "mm per month")


# ---------------------------------------------------------------------------
# Emitter and lateral
# ---------------------------------------------------------------------------

def emitter_curve(k, x, h_op, q_op, allowable_lo=None):
    from engine import kernels as K
    hs = [h_op * f / 20 for f in range(1, 41)]
    qs = [K.emitter_discharge(k, x, h) for h in hs]
    fig = go.Figure(go.Scatter(x=hs, y=qs, mode="lines", name="q = k·Hˣ",
                               line=dict(color=COLORS["primary"], width=3)))
    fig.add_trace(go.Scatter(x=[h_op], y=[q_op], mode="markers", name="Operating point",
                             marker=dict(size=12, color=COLORS["accent_orange"])))
    if allowable_lo:
        fig.add_vrect(x0=allowable_lo, x1=h_op, fillcolor="rgba(0,200,83,0.10)",
                      line_width=0, annotation_text="allowable range",
                      annotation_position="top left")
    return style(fig, "Emitter characteristic", 320, "Pressure head H (m)", "Discharge q (L/h)")


def lateral_profile(uni, h_op, dh_allow, q_nominal, length_m):
    prof = uni["profile"]
    dist = [p["distance_m"] for p in prof]
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08,
                        subplot_titles=("Pressure head along the lateral",
                                        "Emitter discharge along the lateral"))
    fig.add_trace(go.Scatter(x=dist, y=[p["head_m"] for p in prof], mode="lines",
                             name="Head (m)", line=dict(color=COLORS["primary"], width=3)),
                  row=1, col=1)
    fig.add_hline(y=h_op, line=dict(color="#adb5bd", dash="dot"), row=1, col=1,
                  annotation_text="inlet head", annotation_position="top right")
    fig.add_hline(y=h_op - dh_allow, line=dict(color=COLORS["status_error"], dash="dash"),
                  row=1, col=1, annotation_text="allowable minimum",
                  annotation_position="bottom right")
    fig.add_trace(go.Scatter(x=dist, y=[p["q_lph"] for p in prof], mode="lines",
                             name="q (L/h)", line=dict(color=COLORS["pipe_lateral"], width=3)),
                  row=2, col=1)
    fig.add_hline(y=q_nominal, line=dict(color="#adb5bd", dash="dot"), row=2, col=1)
    fig.update_xaxes(title_text="Distance from inlet (m)", row=2, col=1)
    fig.update_yaxes(title_text="H (m)", row=1, col=1)
    fig.update_yaxes(title_text="q (L/h)", row=2, col=1)
    return style(fig, "", 520, legend=False)


# ---------------------------------------------------------------------------
# Pipe sizing diagrams (OpenIrri "Variable Pipe Sizing Diagram")
# ---------------------------------------------------------------------------

_SIZE_COLOURS = ["#0078d4", "#2ec4b6", "#ff9f1c", "#e63946", "#6f42c1", "#00a86b"]


def pipe_sizing_diagram(runs, title="Variable pipe sizing diagram"):
    """Each telescoped run as a coloured band, width proportional to bore."""
    fig = go.Figure()
    sizes = sorted({r["pipe"]["nominal_mm"] for r in runs}, reverse=True)
    colour = {s: _SIZE_COLOURS[i % len(_SIZE_COLOURS)] for i, s in enumerate(sizes)}
    branches = sorted({r.get("branch", 1) for r in runs})
    for r in runs:
        b = r.get("branch", 1)
        y = 0 if len(branches) == 1 else (1 if b == 1 else -1)
        sign = 1 if b == 1 else -1
        x0, x1 = sign * r["from_m"], sign * r["to_m"]
        w = 4 + r["pipe"]["nominal_mm"] / 8
        fig.add_trace(go.Scatter(
            x=[x0, x1], y=[y, y], mode="lines",
            line=dict(color=colour[r["pipe"]["nominal_mm"]], width=w),
            name=f"{r['pipe']['nominal_mm']:.0f} mm {r['pipe']['material']}",
            legendgroup=str(r["pipe"]["nominal_mm"]),
            hovertext=(f"{r['pipe']['nominal_mm']:.0f} mm {r['pipe']['material']} · "
                       f"{r['length_m']:.1f} m · {r['q_in_m3h']:.2f} m³/h in · "
                       f"v ≤ {r['velocity_max_ms']:.2f} m/s"),
            hoverinfo="text"))
        fig.add_annotation(x=(x0 + x1) / 2, y=y, yshift=18, showarrow=False,
                           text=f"Ø{r['pipe']['nominal_mm']:.0f} · {r['length_m']:.0f} m",
                           font=dict(size=11))
    fig.add_trace(go.Scatter(x=[0], y=[0 if len(branches) == 1 else 0], mode="markers",
                             marker=dict(symbol="diamond", size=14, color="#6f42c1"),
                             name="Inlet valve"))
    seen = set()
    for t in fig.data:
        if t.legendgroup and t.legendgroup in seen:
            t.showlegend = False
        seen.add(t.legendgroup)
    fig.update_yaxes(visible=False, range=[-2, 2])
    return style(fig, title, 260, "Distance from inlet (m)")


def march_profile(res, allowable=None, title="Pressure along the manifold"):
    fig = go.Figure()
    for bi, br in enumerate(res["branches"]):
        sign = 1 if bi == 0 else -1
        xs = [0.0] + [sign * p["distance_m"] for p in br["profile"]]
        ys = [0.0] + [p["p_rel_m"] for p in br["profile"]]
        fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines+markers", marker=dict(size=4),
                                 name=f"Branch {bi + 1}",
                                 line=dict(color=_SIZE_COLOURS[bi], width=3)))
    if allowable is not None:
        top = res["p_max_rel_m"]
        fig.add_hrect(y0=top - allowable, y1=top, fillcolor="rgba(0,200,83,0.10)",
                      line_width=0, annotation_text="allowable band",
                      annotation_position="top left")
    return style(fig, title, 320, "Distance from inlet (m)", "Pressure relative to inlet (m)")


def segment_performance(segments, title="Flow, velocity and friction per segment"):
    fig = make_subplots(rows=1, cols=3, subplot_titles=("Flow (m³/h)", "Velocity (m/s)",
                                                        "Friction loss (m)"))
    x = list(range(1, len(segments) + 1))
    fig.add_trace(go.Bar(x=x, y=[s["q_m3h"] for s in segments],
                         marker_color=COLORS["primary"]), row=1, col=1)
    fig.add_trace(go.Bar(x=x, y=[s["velocity_ms"] for s in segments],
                         marker_color=COLORS["pipe_lateral"]), row=1, col=2)
    fig.add_trace(go.Bar(x=x, y=[s["hf_m"] for s in segments],
                         marker_color=COLORS["pipe_submain"]), row=1, col=3)
    fig.update_xaxes(title_text="Segment")
    return style(fig, title, 320, legend=False)


# ---------------------------------------------------------------------------
# Heads, pumps, costs
# ---------------------------------------------------------------------------

def head_breakdown(labels, values, title="Total dynamic head breakdown"):
    fig = go.Figure(go.Bar(y=labels, x=values, orientation="h",
                           marker_color=COLORS["primary"],
                           text=[f"{v:.2f} m" for v in values], textposition="outside",
                           cliponaxis=False))
    fig.update_yaxes(autorange="reversed")
    # Head room for the outside labels, so the longest bar's value is not cut.
    fig.update_xaxes(range=[0, max(values or [1]) * 1.22])
    return style(fig, title, 60 + 44 * len(labels), "Head (m)", legend=False)


def shift_heads(shifts, heads, flows):
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Bar(x=[f"Shift {s}" for s in shifts], y=heads, name="Head at source (m)",
                         marker_color=COLORS["primary"]), secondary_y=False)
    fig.add_trace(go.Scatter(x=[f"Shift {s}" for s in shifts], y=flows, name="Flow (m³/h)",
                             mode="lines+markers", line=dict(color=COLORS["accent_orange"],
                                                             width=3)), secondary_y=True)
    fig.update_yaxes(title_text="Head (m)", secondary_y=False)
    fig.update_yaxes(title_text="Flow (m³/h)", secondary_y=True)
    return style(fig, "Required head and flow, shift by shift", 340)


def pump_curves(pumps_ops, sys_h, q_req, h_req, q_max):
    qs = [q_max * i / 160 for i in range(161)]
    # A compensating emitter makes the system curve climb as (Q/Qd)^20; left
    # unclipped it puts the axis in the terametres and flattens every pump
    # curve onto the zero line. The view is capped just above the highest
    # shut-off head and the duty.
    h_top = 1.3 * max([h_req] + [p.head(0.0) for p, _ in pumps_ops])
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08,
                        row_heights=[0.65, 0.35],
                        subplot_titles=("Head–flow: pump and system curves",
                                        "Pump efficiency"))
    fig.add_trace(go.Scatter(x=qs, y=[sys_h(q) if sys_h(q) <= h_top else None for q in qs],
                             mode="lines", name="Drip system curve",
                             line=dict(color="#1a1a2e" if not _dark() else "#f8f9fa",
                                       width=3, dash="dash")), row=1, col=1)
    for i, (p, op) in enumerate(pumps_ops):
        col = _SIZE_COLOURS[i % len(_SIZE_COLOURS)]
        qq = [q for q in qs if q <= p.q_max]
        grp = f"pump{i}"
        fig.add_trace(go.Scatter(x=qq, y=[p.head(q) for q in qq], mode="lines",
                                 name=p.name, legendgroup=grp,
                                 line=dict(color=col, width=3)), row=1, col=1)
        eff = [100 * p.efficiency(q) for q in qq]
        fig.add_trace(go.Scatter(x=qq, y=[e if e > 0 else None for e in eff], mode="lines",
                                 name=f"η {p.name}", showlegend=False, legendgroup=grp,
                                 line=dict(color=col, width=2)), row=2, col=1)
        if op:
            # The operating point belongs to its pump: same colour, same legend
            # group, so hiding a pump hides its point too.
            fig.add_trace(go.Scatter(x=[op["q_m3h"]], y=[op["h_m"]], mode="markers",
                                     name=f"Operating point, {p.name}", showlegend=False,
                                     legendgroup=grp,
                                     hovertemplate="%{x:.1f} m³/h @ %{y:.1f} m"
                                                   "<extra>" + p.name + "</extra>",
                                     marker=dict(size=13, color=col, symbol="circle",
                                                 line=dict(color="white", width=2))),
                          row=1, col=1)
    if any(op for _, op in pumps_ops):
        fig.add_trace(go.Scatter(x=[None], y=[None], mode="markers",
                                 name="Operating point (pump colour)",
                                 marker=dict(size=12, color="#adb5bd", symbol="circle",
                                             line=dict(color="white", width=2))),
                      row=1, col=1)
    fig.add_trace(go.Scatter(x=[q_req], y=[h_req], mode="markers", name="Duty required",
                             marker=dict(size=14, symbol="x", color=COLORS["status_error"])),
                  row=1, col=1)
    fig.update_yaxes(title_text="Head (m)", row=1, col=1, range=[0, h_top])
    fig.update_yaxes(title_text="η (%)", row=2, col=1, range=[0, 100])
    fig.update_xaxes(title_text="Flow Q (m³/h)", row=2, col=1)
    style(fig, "", 640)
    fig.update_layout(legend=dict(orientation="v", yref="paper", x=1.02, xanchor="left", y=1.0,
                                  yanchor="top"), margin=dict(r=260))
    return fig


def cost_donut(by_category):
    labels = list(by_category)
    fig = go.Figure(go.Pie(labels=labels, values=[by_category[k] for k in labels],
                           hole=0.55, sort=False,
                           marker=dict(colors=_SIZE_COLOURS + SHIFT_COLOURS)))
    style(fig, "Capital cost by category", 400)
    # A pie has no axes to clear: the legend goes to the right, vertical, so
    # it never sits on the title the way the axis-chart default would.
    fig.update_layout(legend=dict(orientation="v", yref="paper", yanchor="middle", y=0.5,
                                  xanchor="left", x=1.02),
                      margin=dict(l=20, r=20, t=60, b=20))
    return fig


def cost_bars(items):
    items = sorted(items, key=lambda i: i["Amount (EGP)"])
    fig = go.Figure(go.Bar(y=[i["Item"][:48] for i in items],
                           x=[i["Amount (EGP)"] for i in items], orientation="h",
                           marker_color=COLORS["primary"]))
    return style(fig, "Cost by item (EGP)", 80 + 26 * len(items), "EGP", legend=False)


def cash_flow_chart(flows):
    cum = []
    c = 0.0
    for f in flows:
        c += f
        cum.append(c)
    yrs = list(range(len(flows)))
    fig = make_subplots(specs=[[{"secondary_y": False}]])
    fig.add_trace(go.Bar(x=yrs, y=flows, name="Net cash flow",
                         marker_color=[COLORS["status_error"] if f < 0 else COLORS["status_ok"]
                                       for f in flows]))
    fig.add_trace(go.Scatter(x=yrs, y=cum, name="Cumulative", mode="lines+markers",
                             line=dict(color=COLORS["primary"], width=3)))
    fig.add_hline(y=0, line=dict(color="#adb5bd"))
    return style(fig, "Cash flow over the analysis horizon", 360, "Year", "EGP")


def schedule_gantt(shift_list, t_set, hours_day, interval_d):
    """Shifts laid end to end over the cycle, wrapped at the working day."""
    fig = go.Figure()
    start = 0.0
    for sh in shift_list:
        day = int(start // hours_day)
        s_in_day = start - day * hours_day
        if s_in_day + t_set > hours_day + 1e-9:
            day += 1
            s_in_day = 0.0
            start = day * hours_day
        col = SHIFT_COLOURS[(sh - 1) % len(SHIFT_COLOURS)]
        fig.add_trace(go.Bar(x=[t_set], y=[f"Day {day + 1}"], base=[s_in_day],
                             orientation="h", name=f"Shift {sh}", marker_color=col,
                             text=[f"S{sh}"], textposition="inside",
                             hovertemplate=f"Shift {sh}: %{{base:.1f}}–%{{x:.1f}} h<extra></extra>"))
        start += t_set
    fig.add_vline(x=hours_day, line=dict(color=COLORS["status_error"], dash="dash"),
                  annotation_text=f"{hours_day:.0f} h working day")
    fig.update_layout(barmode="overlay")
    fig.update_yaxes(autorange="reversed")
    return style(fig, f"Irrigation cycle ({interval_d:g}-day interval)", 120 + 40 * max(
        1, int(math.ceil(len(shift_list) * t_set / max(hours_day, 1e-6)))),
        "Hour of the working day", legend=False)
