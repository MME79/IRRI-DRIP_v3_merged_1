"""
IRRI-DRIP — charts and schematics.

Palette and mark rules follow the validated reference instance:
categorical slots 1-3 (blue, orange, aqua) validated all-pairs, status colours
reserved and always paired with a label, one hue for magnitude comparisons,
never a dual axis, thin marks, recessive grid.
"""

import base64
import html

import altair as alt
import pandas as pd

# ---- palette -------------------------------------------------------------
SERIES_1 = "#2a78d6"      # blue   — primary quantity
SERIES_2 = "#eb6834"      # orange — second entity
SERIES_3 = "#1baf7a"      # aqua   — third entity (always direct-labelled)
SEQ_400 = "#3987e5"
SEQ_250 = "#86b6ef"
SEQ_600 = "#184f95"

GOOD = "#0ca30c"
WARNING = "#fab219"
CRITICAL = "#d03b3b"

# Light-mode surface colours. These four are resolved per render by skin(),
# because a chart is drawn ONTO the page: one that keeps a white ground on a
# dark page is a bright rectangle in the middle of the layout, and the
# schematic — a base64 image with its background baked in at generation time
# — was the worst offender. The DATA colours above do not change: they were
# validated for contrast and colour-vision deficiency as a set, and re-tuning
# them per mode would invalidate that validation.
INK = "#16242b"
MUTED = "#66787f"
GRID = "#e6ebed"
SURFACE = "#ffffff"
BAND = "#eef3f6"

_DARK = {"ink": "#e8edf0", "muted": "#9fb0b8", "grid": "#2a3441",
         "surface": "#1e2530", "band": "#243040"}
_LIGHT = {"ink": INK, "muted": MUTED, "grid": GRID,
          "surface": SURFACE, "band": BAND}

FONT = "Inter, system-ui, -apple-system, Segoe UI, Roboto, sans-serif"


def skin() -> dict:
    """Surface colours for the mode the page is currently in."""
    try:
        from modules import theme
        return _DARK if theme.is_dark() else _LIGHT
    except Exception:          # noqa: BLE001 — a chart must still render if
        return _LIGHT          # the theme module is unavailable


def _base(chart, height=260):
    K = skin()
    if height is not None:
        chart = chart.properties(height=height)
    return (chart
            .properties(background=K["surface"])
            .configure_view(stroke=None)
            .configure_axis(labelFont=FONT, titleFont=FONT, labelColor=K["muted"],
                            titleColor=K["ink"], labelFontSize=11, titleFontSize=11,
                            titleFontWeight=500, grid=True, gridColor=K["grid"],
                            gridWidth=1, domainColor=K["grid"], tickColor=K["grid"])
            .configure_legend(labelFont=FONT, titleFont=FONT, labelColor=K["ink"],
                              titleColor=K["muted"], labelFontSize=11, titleFontSize=11,
                              symbolType="stroke", symbolStrokeWidth=2)
            .configure_title(font=FONT, fontSize=12, fontWeight=600, color=K["ink"],
                             anchor="start", dy=-4))


# ---------------------------------------------------------------------------
# 1. Lateral hydraulic profile — two single-axis charts, never a dual axis
# ---------------------------------------------------------------------------

def lateral_profile_charts(uni, h_op, dh_allow, q_nominal, eu_target, length_m):
    """
    Head and discharge along the lateral.

    Two separate charts sharing the x axis rather than one dual-axis chart:
    head in metres and discharge in L/h have no common scale, and overlaying
    them on twin y-axes is the single most misleading thing a chart can do.

    The head chart carries the acceptable head band as a shaded reference so
    the reader sees compliance without reading a number, and marks the
    governing (minimum-discharge) point — which on a falling lateral sits
    inside the line, not at either end.
    """
    K = skin()
    df = pd.DataFrame(uni["profile"])
    df["q_lph"] = [p["q_lph"] for p in uni["profile"]]

    h_lo, h_hi = h_op - dh_allow, h_op
    band = pd.DataFrame({"lo": [h_lo], "hi": [h_hi]})
    crit = pd.DataFrame([{
        "distance_m": uni["distance_of_min_m"],
        "head_m": uni["h_min_m"],
        "q_lph": uni["q_min_lph"],
        "label": f"governing point · {uni['h_min_m']:.2f} m · {uni['q_min_lph']:.2f} L/h",
    }])

    x = alt.X("distance_m:Q", title="Distance along lateral (m)",
              scale=alt.Scale(nice=False, domainMin=0))

    head_band = alt.Chart(band).mark_rect(color=K["band"]).encode(
        y=alt.Y("lo:Q"), y2=alt.Y2("hi:Q"))
    head_line = alt.Chart(df).mark_line(color=SERIES_1, strokeWidth=2).encode(
        x=x, y=alt.Y("head_m:Q", title="Pressure head (m)",
                     scale=alt.Scale(zero=False, nice=True)),
        tooltip=[alt.Tooltip("distance_m:Q", title="Distance (m)", format=".1f"),
                 alt.Tooltip("head_m:Q", title="Head (m)", format=".3f"),
                 alt.Tooltip("q_lph:Q", title="Discharge (L/h)", format=".3f")])
    head_pt = alt.Chart(crit).mark_point(
        size=90, color=CRITICAL, filled=True, stroke=K["surface"], strokeWidth=2).encode(
        x=x, y="head_m:Q",
        tooltip=[alt.Tooltip("label:N", title="Governing point")])
    near_end = uni["distance_of_min_m"] > 0.6 * max(length_m, 1e-9)
    head_txt = alt.Chart(crit).mark_text(
        align="right" if near_end else "left",
        dx=-10 if near_end else 10, dy=-11,
        font=FONT, fontSize=10, color=CRITICAL).encode(
        x=x, y="head_m:Q", text="label:N")

    head = _base((head_band + head_line + head_pt + head_txt).properties(
        title=f"Pressure head along the lateral — shaded band is the "
              f"acceptable range, {h_lo:.2f} to {h_hi:.2f} m"), height=250)

    mean_rule = alt.Chart(pd.DataFrame({"y": [uni["q_avg_lph"]]})).mark_rule(
        color=K["muted"], strokeWidth=1, strokeDash=[4, 3]).encode(y="y:Q")
    q_line = alt.Chart(df).mark_line(color=SERIES_2, strokeWidth=2).encode(
        x=x, y=alt.Y("q_lph:Q", title="Emitter discharge (L/h)",
                     scale=alt.Scale(zero=False, nice=True)),
        tooltip=[alt.Tooltip("distance_m:Q", title="Distance (m)", format=".1f"),
                 alt.Tooltip("q_lph:Q", title="Discharge (L/h)", format=".3f")])
    q_pt = alt.Chart(crit).mark_point(
        size=90, color=CRITICAL, filled=True, stroke=K["surface"], strokeWidth=2).encode(
        x=x, y="q_lph:Q")

    disc = _base((mean_rule + q_line + q_pt).properties(
        title=f"Emitter discharge along the lateral — dashed line is the mean, "
              f"{uni['q_avg_lph']:.3f} L/h"), height=200)

    return head, disc


# ---------------------------------------------------------------------------
# 2. Emitter discharge curve
# ---------------------------------------------------------------------------

def emitter_curve_chart(k, x_exp, h_op, q_op, h_lo=None, h_hi=None):
    """q = k·H^x with the operating point and the working head band."""
    K = skin()
    heads = [h_op * f for f in [i / 100.0 for i in range(40, 161, 2)]]
    df = pd.DataFrame({"head_m": heads,
                       "q_lph": [k * (h ** x_exp) if h > 0 else 0.0 for h in heads]})
    layers = []
    if h_lo is not None and h_hi is not None and h_hi > h_lo:
        layers.append(alt.Chart(pd.DataFrame({"lo": [h_lo], "hi": [h_hi]}))
                      .mark_rect(color=K["band"]).encode(x="lo:Q", x2="hi:Q"))
    layers.append(alt.Chart(df).mark_line(color=SERIES_1, strokeWidth=2).encode(
        x=alt.X("head_m:Q", title="Operating head (m)",
                scale=alt.Scale(nice=False, zero=False)),
        y=alt.Y("q_lph:Q", title="Discharge (L/h)", scale=alt.Scale(zero=False)),
        tooltip=[alt.Tooltip("head_m:Q", title="Head (m)", format=".2f"),
                 alt.Tooltip("q_lph:Q", title="Discharge (L/h)", format=".3f")]))
    op = pd.DataFrame([{"head_m": h_op, "q_lph": q_op,
                        "label": f"design point · {h_op:.1f} m · {q_op:.2f} L/h"}])
    layers.append(alt.Chart(op).mark_point(size=100, color=SERIES_1, filled=True,
                                           stroke=K["surface"], strokeWidth=2)
                  .encode(x="head_m:Q", y="q_lph:Q"))
    layers.append(alt.Chart(op).mark_text(align="left", dx=9, dy=-9, font=FONT,
                                          fontSize=10, color=K["ink"])
                  .encode(x="head_m:Q", y="q_lph:Q", text="label:N"))
    return _base(alt.layer(*layers).properties(
        title="Emitter characteristic curve — flatter means less sensitive to pressure"),
        height=240)


# ---------------------------------------------------------------------------
# 3. Magnitude comparison — one hue, horizontal bars
# ---------------------------------------------------------------------------

def magnitude_bars(labels, values, value_title, title, unit="", height=None,
                   highlight=None, decimals=None):
    """
    Compare magnitudes with a single-hue horizontal bar chart.

    Sequential, not categorical: the reader's job here is "which is biggest",
    not "tell these entities apart", so one hue with darker = larger is the
    safe default. Every bar is direct-labelled, so nothing depends on colour.

    `decimals` defaults to a magnitude rule: money and other large quantities
    are shown whole, small ones to two places. "237,500.00 EGP" on a bill of
    quantities is false precision, and eight of them is a wall of digits.
    """
    K = skin()
    df = pd.DataFrame({"label": labels, "value": values})
    df = df[df["value"].abs() > 1e-12].reset_index(drop=True)
    if df.empty:
        df = pd.DataFrame({"label": ["(no non-zero components)"], "value": [0.0]})

    vmax = float(df["value"].max())
    if decimals is None:
        decimals = 0 if abs(vmax) >= 1000 else 2

    # The unit is carried by the largest bar only; the axis title already
    # states it, and repeating it on every row is ink without information.
    top = df["value"].idxmax()
    df["text"] = [
        f"{v:,.{decimals}f} {unit}".strip() if i == top else f"{v:,.{decimals}f}"
        for i, v in df["value"].items()]
    if highlight:
        df["emph"] = df["label"].map(lambda s: s in highlight)
    else:
        df["emph"] = False

    # Headroom on the right so the direct label of the longest bar cannot be
    # clipped by the container edge — the same defect already fixed on the
    # lateral profile chart, and present here for the same reason.
    vmin = min(0.0, float(df["value"].min()))
    pad = max(abs(vmax), abs(vmin)) * 0.22 or 1.0
    domain = [vmin - (pad if vmin < 0 else 0.0), vmax + pad]

    bars = alt.Chart(df).mark_bar(cornerRadiusEnd=4, height=20).encode(
        y=alt.Y("label:N", sort="-x", title=None,
                axis=alt.Axis(labelLimit=300, labelFontSize=11, labelOverlap=False,
                              labelPadding=6)),
        x=alt.X("value:Q", title=value_title,
                scale=alt.Scale(domain=domain, nice=False, clamp=True)),
        color=alt.Color("value:Q", scale=alt.Scale(range=[SEQ_250, SEQ_600]),
                        legend=None),
        tooltip=[alt.Tooltip("label:N", title=""),
                 alt.Tooltip("value:Q", title=value_title, format=",.3f")])
    labels_layer = alt.Chart(df).mark_text(
        align="left", dx=6, font=FONT, fontSize=10, color=K["ink"]).encode(
        y=alt.Y("label:N", sort="-x"), x="value:Q", text="text:N")
    # Band-step sizing rather than a fixed pixel height: with a fixed height
    # Vega silently drops y-axis labels that do not fit, and half the rows lost
    # their names. Found by screenshotting the rendered chart.
    # autosize fit-x, not the default fit: a discrete (step-sized) height and
    # a "fit" autosize are contradictory and Vega logs a warning on every draw.
    chart = (bars + labels_layer).properties(
        title=title, height=alt.Step(34),
        autosize=alt.AutoSizeParams(type="fit-x", contains="padding"))
    return _base(chart, height=None)


# ---------------------------------------------------------------------------
# 4. Schematics — inline SVG, no dependency
# ---------------------------------------------------------------------------

def _esc(t):
    return html.escape(str(t))


def _svg_img(svg_body: str, view_w: int, view_h: int, max_width: int = 940) -> str:
    """
    Wrap an SVG as a base64 data URI inside an <img>.

    Streamlit's markdown sanitiser keeps SVG shapes but STRIPS <text> elements,
    so an inline schematic came out as unlabelled blobs with its captions
    re-emitted as stray paragraphs underneath. Encoding the whole SVG as a data
    URI bypasses the sanitiser and preserves the labels. Found by screenshotting
    the rendered page — the failure is invisible in the HTML source.
    """
    K = skin()
    doc = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {view_w} {view_h}" '
           f'width="{view_w}" height="{view_h}">'
           f'<rect width="100%" height="100%" fill="{K["surface"]}"/>{svg_body}</svg>')
    b64 = base64.b64encode(doc.encode("utf-8")).decode("ascii")
    return (f'<div style="overflow-x:auto"><img alt="schematic" '
            f'src="data:image/svg+xml;base64,{b64}" '
            f'style="width:100%;max-width:{max_width}px;display:block"/></div>')


def system_schematic_svg(setup, em, op, man, lat, qual=None):
    """
    Flow-order schematic of the whole system.

    Not decoration: it is the drawing a reviewer asks for first, and it makes
    the shift structure and the head-control train visible at a glance.
    """
    K = skin()
    n_lat = int(man.get("n_lat", 10))
    shown = min(6, max(3, n_lat))
    filt = "filtration"
    if qual and qual.get("filtration", {}).get("train"):
        filt = " + ".join(t.split(" (")[0] for t in qual["filtration"]["train"])

    lat_y0, lat_dy = 92, 34
    laterals = []
    for i in range(shown):
        y = lat_y0 + i * lat_dy
        laterals.append(
            f'<line x1="640" y1="{y}" x2="880" y2="{y}" stroke="{SERIES_3}" '
            f'stroke-width="2.5" stroke-linecap="round"/>')
        for j in range(9):
            laterals.append(f'<circle cx="{660 + j*25}" cy="{y}" r="2.6" fill="{SERIES_3}"/>')
    if n_lat > shown:
        laterals.append(
            f'<text x="640" y="{lat_y0 + (shown-1)*lat_dy + 34}" text-anchor="start" '
            f'font-size="10.5" fill="{K["muted"]}" font-family="{FONT}">'
            f'{n_lat} laterals per manifold</text>')

    mid_y = lat_y0 + (shown - 1) * lat_dy / 2

    body = f"""
  <rect x="10" y="{mid_y-30}" width="86" height="60" rx="8" fill="{K["band"]}" stroke="{K["grid"]}"/>
  <text x="53" y="{mid_y-6}" text-anchor="middle" font-size="11" font-weight="600" fill="{K["ink"]}" font-family="{FONT}">Source</text>
  <text x="53" y="{mid_y+10}" text-anchor="middle" font-size="10" fill="{K["muted"]}" font-family="{FONT}">{_esc(f"{setup['q_avail']:.0f} m3/h")}</text>
  <line x1="96" y1="{mid_y}" x2="140" y2="{mid_y}" stroke="{SERIES_1}" stroke-width="4"/>
  <circle cx="140" cy="{mid_y}" r="24" fill="{K["surface"]}" stroke="{SERIES_1}" stroke-width="2.5"/>
  <text x="140" y="{mid_y+4}" text-anchor="middle" font-size="12" font-weight="700" fill="{SERIES_1}" font-family="{FONT}">P</text>
  <text x="140" y="{mid_y+44}" text-anchor="middle" font-size="10" fill="{K["muted"]}" font-family="{FONT}">pump</text>
  <line x1="164" y1="{mid_y}" x2="188" y2="{mid_y}" stroke="{SERIES_1}" stroke-width="4"/>
  <rect x="188" y="{mid_y-32}" width="140" height="64" rx="8" fill="{K["surface"]}" stroke="{SERIES_2}" stroke-width="2"/>
  <text x="258" y="{mid_y-10}" text-anchor="middle" font-size="11" font-weight="600" fill="{K["ink"]}" font-family="{FONT}">Head control</text>
  <text x="258" y="{mid_y+6}" text-anchor="middle" font-size="9.5" fill="{K["muted"]}" font-family="{FONT}">{_esc(filt)}</text>
  <text x="258" y="{mid_y+21}" text-anchor="middle" font-size="9.5" fill="{K["muted"]}" font-family="{FONT}">+ fertigation</text>
  <line x1="328" y1="{mid_y}" x2="600" y2="{mid_y}" stroke="{SERIES_1}" stroke-width="5" stroke-linecap="round"/>
  <text x="464" y="{mid_y-14}" text-anchor="middle" font-size="10.5" font-weight="600" fill="{SERIES_1}" font-family="{FONT}">mainline {_esc(f"{man['main_pipe']['nominal_mm']:.0f} mm {man['main_pipe']['material']}")}</text>
  <text x="464" y="{mid_y+20}" text-anchor="middle" font-size="10" fill="{K["muted"]}" font-family="{FONT}">{_esc(f"{op['q_shift']:.1f} m3/h  |  {op['shifts']} shifts x {op['t_set']:.2f} h")}</text>
  <line x1="600" y1="{lat_y0-16}" x2="600" y2="{lat_y0 + (shown-1)*lat_dy + 16}" stroke="{SERIES_2}" stroke-width="5" stroke-linecap="round"/>
  <text x="600" y="{lat_y0-28}" text-anchor="middle" font-size="10.5" font-weight="600" fill="{SERIES_2}" font-family="{FONT}">manifold {_esc(f"{man['manifold_pipe']['nominal_mm']:.0f} mm")}</text>
  {''.join(laterals)}
  <text x="890" y="{lat_y0-28}" text-anchor="end" font-size="10.5" font-weight="600" fill="{SERIES_3}" font-family="{FONT}">laterals {_esc(f"{lat['lateral']['nominal_mm']:.0f} mm, {lat['l_len']:.0f} m")}</text>
  <text x="890" y="{lat_y0 + (shown-1)*lat_dy + 52}" text-anchor="end" font-size="10.5" fill="{K["muted"]}" font-family="{FONT}">{_esc(f"emitters at {em['se']:.2f} m, {em['q_emitter']:.2f} L/h each")}</text>
"""
    return _svg_img(body, 940, int(lat_y0 + (shown-1)*lat_dy + 72))


def wetting_section_svg(em, soil_name):
    """
    Cross-section through two adjacent laterals showing the wetted strip.

    Pw is the number an experienced designer distrusts most, because it depends
    on a wetted diameter that is rarely measured. Drawing it makes the
    assumption visible instead of leaving it as a percentage.
    """
    K = skin()
    sl, dw, se = em["sl"], em["dw"], em["se"]
    pw = em["pw"]
    scale = 700.0 / max(2.0 * sl, 1e-6)
    w, h = 760, 220
    surface_y = 60
    x1, x2 = 40 + 0.5 * sl * scale, 40 + 1.5 * sl * scale
    rw = min(dw, sl) * scale / 2.0
    bulb_h = 78

    def bulb(cx):
        return (f'<ellipse cx="{cx}" cy="{surface_y + bulb_h*0.42}" rx="{rw}" '
                f'ry="{bulb_h*0.62}" fill="{SEQ_250}" opacity="0.55"/>'
                f'<line x1="{cx-rw}" y1="{surface_y}" x2="{cx+rw}" y2="{surface_y}" '
                f'stroke="{SERIES_1}" stroke-width="2.5"/>')

    body = f"""
  <rect x="20" y="{surface_y}" width="{w-40}" height="120" fill="#f4f1ec"/>
  <line x1="20" y1="{surface_y}" x2="{w-20}" y2="{surface_y}" stroke="#cbbfae" stroke-width="2"/>
  <text x="26" y="{surface_y-10}" font-size="11" fill="{K["muted"]}" font-family="{FONT}">soil surface - {_esc(soil_name)}</text>
  {bulb(x1)}{bulb(x2)}
  <circle cx="{x1}" cy="{surface_y-7}" r="5" fill="{SERIES_3}"/>
  <circle cx="{x2}" cy="{surface_y-7}" r="5" fill="{SERIES_3}"/>
  <line x1="{x1}" y1="{surface_y+150}" x2="{x2}" y2="{surface_y+150}" stroke="{K["muted"]}" stroke-width="1"/>
  <line x1="{x1}" y1="{surface_y+145}" x2="{x1}" y2="{surface_y+155}" stroke="{K["muted"]}"/>
  <line x1="{x2}" y1="{surface_y+145}" x2="{x2}" y2="{surface_y+155}" stroke="{K["muted"]}"/>
  <text x="{(x1+x2)/2}" y="{surface_y+143}" text-anchor="middle" font-size="11" fill="{K["ink"]}" font-family="{FONT}">lateral spacing Sl = {sl:.2f} m</text>
  <line x1="{x1-rw}" y1="{surface_y+122}" x2="{x1+rw}" y2="{surface_y+122}" stroke="{SERIES_1}" stroke-width="1.5"/>
  <text x="{x1}" y="{surface_y+116}" text-anchor="middle" font-size="11" fill="{SERIES_1}" font-family="{FONT}">Dw = {dw:.2f} m</text>
  <text x="{w-26}" y="{surface_y-10}" text-anchor="end" font-size="12" font-weight="700" fill="{K["ink"]}" font-family="{FONT}">Pw = {pw*100:.0f}% of the surface wetted</text>
  <text x="{w-26}" y="{surface_y+186}" text-anchor="end" font-size="10" fill="{K["muted"]}" font-family="{FONT}">emitters at {se:.2f} m along each lateral</text>
"""
    return _svg_img(body, w, h, max_width=w)
