"""
IRRI-DRIP — DXF export of the network layout.

A minimal, dependency-free writer for DXF R12 (AC1009), the oldest and most
widely readable DXF revision. Every CAD package in an Egyptian design office
opens R12 without complaint, and writing it directly avoids adding a library
to requirements.txt that would force a reinstall on every machine already
running the program.

WHAT THIS DRAWING IS AND IS NOT
-------------------------------
It is a DIMENSIONALLY CORRECT SCHEMATIC of the hydraulic layout the program
designed: real lateral lengths, real spacings, real manifold and mainline
lengths, drawn to scale in metres.

It is NOT a site plan. The program never asked for the field's shape, its
orientation, its boundaries, or where the water source physically sits, so
it cannot draw them and does not pretend to. It assumes ONE rectangular
block per shift, laterals fed from one side of a manifold, subunits laid
side by side along a straight mainline. That assumption is written into the
drawing itself as a note on the NOTES layer, so nobody downstream mistakes
it for surveyed geometry.

Coordinates are in metres, matching the design. Set your CAD units to
metres on import.
"""

from __future__ import annotations

# AutoCAD Colour Index values used on the layers below.
ACI = {
    "white": 7, "red": 1, "yellow": 2, "green": 3,
    "cyan": 4, "blue": 5, "magenta": 6, "grey": 8, "dark_grey": 250,
}

LAYERS = [
    ("IRR-MAINLINE", ACI["red"]),
    ("IRR-NOT-DESIGNED", ACI["dark_grey"]),
    ("IRR-MANIFOLD", ACI["blue"]),
    ("IRR-LATERAL", ACI["green"]),
    ("IRR-EMITTER", ACI["cyan"]),
    ("IRR-HEADWORKS", ACI["magenta"]),
    ("IRR-BLOCK", ACI["grey"]),
    ("IRR-TEXT", ACI["white"]),
    ("IRR-NOTES", ACI["yellow"]),
    ("IRR-TITLE", ACI["white"]),
    # Site plan (v2.0): the network on the real boundary.
    ("IRR-BOUNDARY", ACI["white"]),
    ("IRR-SUBMAIN", ACI["yellow"]),
    ("IRR-VALVE", ACI["magenta"]),
]


# ---------------------------------------------------------------------------
# The writer
# ---------------------------------------------------------------------------

class DxfDocument:
    """Accumulates R12 entities and serialises them."""

    def __init__(self):
        self._entities: list[str] = []
        self._xs: list[float] = []
        self._ys: list[float] = []

    # -- geometry ----------------------------------------------------------

    def _track(self, *pts):
        for x, y in pts:
            self._xs.append(x)
            self._ys.append(y)

    def line(self, layer, x1, y1, x2, y2):
        self._track((x1, y1), (x2, y2))
        self._entities.append(
            f"0\nLINE\n8\n{layer}\n"
            f"10\n{x1:.6f}\n20\n{y1:.6f}\n30\n0.0\n"
            f"11\n{x2:.6f}\n21\n{y2:.6f}\n31\n0.0\n")

    def rect(self, layer, x1, y1, x2, y2):
        self.line(layer, x1, y1, x2, y1)
        self.line(layer, x2, y1, x2, y2)
        self.line(layer, x2, y2, x1, y2)
        self.line(layer, x1, y2, x1, y1)

    def circle(self, layer, cx, cy, r):
        self._track((cx - r, cy - r), (cx + r, cy + r))
        self._entities.append(
            f"0\nCIRCLE\n8\n{layer}\n"
            f"10\n{cx:.6f}\n20\n{cy:.6f}\n30\n0.0\n40\n{r:.6f}\n")

    def text(self, layer, x, y, height, value, rotation=0.0):
        # R12 TEXT carries no encoding declaration, so the drawing is kept to
        # plain ASCII. Arabic would need a code page the receiving CAD may not
        # share, and would arrive unshaped; English labels are what a CAD
        # deliverable normally carries in any case.
        safe = _ascii(value)
        self._track((x, y))
        self._entities.append(
            f"0\nTEXT\n8\n{layer}\n"
            f"10\n{x:.6f}\n20\n{y:.6f}\n30\n0.0\n"
            f"40\n{height:.6f}\n1\n{safe}\n"
            + (f"50\n{rotation:.6f}\n" if rotation else ""))

    # -- serialisation -----------------------------------------------------

    def extents(self):
        if not self._xs:
            return (0.0, 0.0, 1.0, 1.0)
        return (min(self._xs), min(self._ys), max(self._xs), max(self._ys))

    def render(self) -> str:
        x0, y0, x1, y1 = self.extents()
        out = [
            "0\nSECTION\n2\nHEADER\n",
            "9\n$ACADVER\n1\nAC1009\n",
            "9\n$INSBASE\n10\n0.0\n20\n0.0\n30\n0.0\n",
            f"9\n$EXTMIN\n10\n{x0:.6f}\n20\n{y0:.6f}\n30\n0.0\n",
            f"9\n$EXTMAX\n10\n{x1:.6f}\n20\n{y1:.6f}\n30\n0.0\n",
            # 1 = metres, so a CAD package that honours it scales correctly.
            "9\n$INSUNITS\n70\n6\n",
            "0\nENDSEC\n",
            "0\nSECTION\n2\nTABLES\n",
            f"0\nTABLE\n2\nLAYER\n70\n{len(LAYERS)}\n",
        ]
        for name, colour in LAYERS:
            out.append(f"0\nLAYER\n2\n{name}\n70\n0\n62\n{colour}\n6\nCONTINUOUS\n")
        out.append("0\nENDTAB\n0\nENDSEC\n")
        out.append("0\nSECTION\n2\nENTITIES\n")
        out.extend(self._entities)
        out.append("0\nENDSEC\n0\nEOF\n")
        return "".join(out)


def _ascii(value: str) -> str:
    """R12 TEXT has no encoding declaration; keep it to plain ASCII."""
    return "".join(ch if 32 <= ord(ch) < 127 else "?" for ch in str(value))


# ---------------------------------------------------------------------------
# The layout
# ---------------------------------------------------------------------------

EMITTER_DRAW_LIMIT = 400        # per detail lateral, not per field


def build_layout(S: dict, max_emitters_drawn: int = EMITTER_DRAW_LIMIT) -> DxfDocument:
    """
    Draw the designed network from the saved project state.

    Layout model, stated here and repeated on the NOTES layer of the drawing:

        - one rectangular block per shift, laid side by side along X
        - within a block, the manifold runs along X at the block's near edge
        - laterals run in +Y from the manifold, spaced at the lateral spacing
        - the mainline runs along X below the blocks and rises to each
          manifold inlet
        - the head control (filter and fertigation) sits at the source end

    Real dimensions throughout. What the program does not know — field shape,
    orientation, true source position — is not invented.
    """
    d = DxfDocument()

    setup = S["setup"]
    em, op = S["emitter"], S["operation"]
    lat, man = S["lateral"], S["manifold"]

    l_len = float(lat["l_len"])                       # lateral length, m
    sl = float(em["sl"])                              # lateral spacing, m
    se = float(em["se"])                              # emitter spacing, m
    n_lat = int(man["n_lat"])                         # laterals per manifold
    m_len = float(man["m_len"])                       # manifold length, m
    main_len = float(man["main_len"])                 # mainline length, m
    shifts = max(1, int(op["shifts"]))

    lat_nom = lat["lateral"]["nominal_mm"]
    man_nom = man["manifold_pipe"]["nominal_mm"]
    man_mat = man["manifold_pipe"]["material"]
    main_nom = man["main_pipe"]["nominal_mm"]
    main_mat = man["main_pipe"]["material"]

    gap = max(5.0, 0.06 * m_len)                      # between blocks
    main_y = -max(8.0, 0.08 * l_len)                  # mainline standoff
    block_pitch = m_len + gap

    # ---- the blocks --------------------------------------------------------
    for s in range(shifts):
        x0 = s * block_pitch
        # block outline
        d.rect("IRR-BLOCK", x0, 0.0, x0 + m_len, l_len)
        # manifold
        d.line("IRR-MANIFOLD", x0, 0.0, x0 + m_len, 0.0)
        # laterals
        for i in range(n_lat):
            x = x0 + i * sl
            if x > x0 + m_len + 1e-9:
                break
            d.line("IRR-LATERAL", x, 0.0, x, l_len)
        # riser from the mainline to this manifold inlet
        d.line("IRR-MAINLINE", x0, main_y, x0, 0.0)
        # block label
        d.text("IRR-TEXT", x0 + 0.02 * m_len, l_len + 0.03 * l_len,
               max(1.0, 0.02 * l_len),
               f"BLOCK / SHIFT {s + 1} of {shifts}")
        d.text("IRR-TEXT", x0 + 0.02 * m_len, l_len + 0.03 * l_len - max(1.4, 0.028 * l_len),
               max(0.8, 0.016 * l_len),
               f"{n_lat} laterals @ {sl:.2f} m, {l_len:.1f} m long, "
               f"{lat_nom:.0f} mm")
        # manifold label
        d.text("IRR-TEXT", x0 + 0.02 * m_len, -max(1.6, 0.032 * l_len),
               max(0.8, 0.016 * l_len),
               f"MANIFOLD {man_nom:.0f} mm {man_mat}, {m_len:.1f} m")

    total_width = shifts * block_pitch - gap

    # ---- the mainline ------------------------------------------------------
    # The mainline is drawn at EXACTLY its designed length, source to the
    # first manifold inlet. An earlier draft ran one line from the source
    # across every block, which drew 475 m for a 200 m designed mainline —
    # a drawing contradicting the calculation it came from. The run that
    # continues along the blocks is real pipe, but the program was never
    # asked to size it, so it goes on its own layer and says so.
    source_x = -main_len
    d.line("IRR-MAINLINE", source_x, main_y, 0.0, main_y)
    d.text("IRR-TEXT", source_x + 0.02 * main_len, main_y - max(1.6, 0.032 * l_len),
           max(0.9, 0.018 * l_len),
           f"MAINLINE {main_nom:.0f} mm {main_mat}, {main_len:.1f} m AS DESIGNED, "
           f"{op['q_shift']:.1f} m3/h")

    if shifts > 1:
        d.line("IRR-NOT-DESIGNED", 0.0, main_y, total_width, main_y)
        d.text("IRR-NOT-DESIGNED", 0.0, main_y + max(1.2, 0.024 * l_len),
               max(0.9, 0.018 * l_len),
               f"DISTRIBUTION RUN ALONG THE BLOCKS, {total_width:.1f} m - "
               "NOT SIZED BY THIS PROGRAM, SIZE IT SEPARATELY")

    # ---- head control and source ------------------------------------------
    hw = max(4.0, 0.05 * m_len)
    d.rect("IRR-HEADWORKS", source_x - hw, main_y - hw / 2.0, source_x, main_y + hw / 2.0)
    d.text("IRR-TEXT", source_x - hw, main_y + hw / 2.0 + max(0.6, 0.012 * l_len),
           max(0.9, 0.018 * l_len), "HEAD CONTROL: FILTER + FERTIGATION + PUMP")
    d.circle("IRR-HEADWORKS", source_x - hw - hw / 2.0, main_y, hw / 3.0)
    d.text("IRR-TEXT", source_x - hw - hw / 2.0 - hw / 3.0,
           main_y - hw / 2.0 - max(1.0, 0.02 * l_len),
           max(0.9, 0.018 * l_len), f"SOURCE {setup['q_avail']:.1f} m3/h")

    # ---- one detail lateral with its emitters ------------------------------
    # Drawing every emitter in the field would be tens of thousands of circles
    # and would open slowly in any CAD package for no gain. One lateral is
    # drawn at true emitter spacing as a detail, and labelled as such.
    n_em_lat = int(round(l_len / se)) if se > 0 else 0
    det_y = -max(20.0, 0.22 * l_len) + main_y
    det_x = 0.0
    drawn = min(n_em_lat, int(max_emitters_drawn))
    d.line("IRR-LATERAL", det_x, det_y, det_x + l_len, det_y)
    r = max(0.15, 0.003 * l_len)
    for i in range(drawn):
        d.circle("IRR-EMITTER", det_x + (i + 0.5) * se, det_y, r)
    note = (f"DETAIL: ONE LATERAL, {n_em_lat} EMITTERS @ {se:.2f} m, "
            f"{em['q_emitter']:.2f} L/h EACH")
    if drawn < n_em_lat:
        note += f" (FIRST {drawn} SHOWN)"
    d.text("IRR-TEXT", det_x, det_y + max(1.2, 0.024 * l_len),
           max(0.9, 0.018 * l_len), note)

    # ---- notes -------------------------------------------------------------
    ny = det_y - max(6.0, 0.07 * l_len)
    nh = max(0.9, 0.018 * l_len)
    # A drawing outlives the screen that warned about it. If the design failed
    # its own checks, the drawing says so in its first two lines, not in a
    # footnote — a DXF gets forwarded to a contractor on its own.
    verdict = S.get("verdict") or {}
    stamp: list[str] = []
    if verdict and not verdict.get("passed", True):
        stamp = [
            "*** NOT PASSED - THIS DESIGN FAILED ITS OWN CHECKS ***",
            "DO NOT ISSUE, TENDER OR CONSTRUCT FROM THIS DRAWING.",
            "FAILED: " + _ascii("; ".join(verdict.get("failed_checks", [])) or "-").upper(),
            "",
        ]
    for i, line in enumerate(stamp + [
        "IRRI-DRIP - DRIP IRRIGATION NETWORK, DIMENSIONALLY CORRECT SCHEMATIC",
        "UNITS: METRES. SET CAD UNITS TO METRES ON IMPORT.",
        "",
        "THIS IS NOT A SITE PLAN. THE PROGRAM WAS NEVER GIVEN THE FIELD SHAPE,",
        "ITS ORIENTATION, ITS BOUNDARIES, OR THE TRUE POSITION OF THE SOURCE,",
        "SO NONE OF THOSE ARE DRAWN. THE LAYOUT ASSUMES ONE RECTANGULAR BLOCK",
        "PER SHIFT, LATERALS FED FROM ONE SIDE OF A MANIFOLD, AND BLOCKS SET",
        "SIDE BY SIDE ALONG A STRAIGHT MAINLINE.",
        "",
        "PIPE LENGTHS, LATERAL AND EMITTER SPACINGS ARE THE DESIGNED VALUES",
        "AND ARE DRAWN TO SCALE. FIT THEM TO THE SURVEYED BOUNDARY BEFORE USE.",
        "",
        "ANYTHING ON LAYER IRR-NOT-DESIGNED WAS NOT SIZED BY THIS PROGRAM.",
        "THE MAINLINE IS DRAWN AT ITS DESIGNED LENGTH FROM THE SOURCE TO THE",
        "FIRST MANIFOLD ONLY. THE RUN CONTINUING ALONG THE BLOCKS IS REAL PIPE",
        "BUT WAS NEVER PART OF THE HYDRAULIC CALCULATION - SIZE IT SEPARATELY.",
        "",
        "NO OUTPUT OF THIS PROGRAM MAY BE ISSUED AS AN EXECUTED DESIGN WITHOUT",
        "INDEPENDENT VERIFICATION BY A QUALIFIED IRRIGATION ENGINEER.",
    ]):
        if line:
            d.text("IRR-NOTES", 0.0, ny - i * nh * 1.6, nh, line)

    # ---- title block -------------------------------------------------------
    ty = ny - (16 + len(stamp)) * nh * 1.6
    th = nh * 1.2
    title = [
        # An absent verdict is not a pass. Claiming one would be worse than
        # saying nothing, so the three states stay distinct.
        "VERDICT: " + ("NOT RECORDED" if not verdict else
                       "PASSED ALL DESIGN CHECKS" if verdict.get("passed")
                       else "NOT PASSED"),
        f"PROJECT: {setup.get('name') or 'UNTITLED'}",
        f"LOCATION: {setup.get('location') or '-'}",
        f"CROP: {setup['crop']['name']}   SOIL: {setup['soil']['name']}",
        f"NET AREA: {setup['area_ha']:.2f} ha   SHIFTS: {shifts}",
        f"EMITTER: {em['name']}, {em['q_emitter']:.2f} L/h AT "
        f"{em['h_op']:.1f} m, k={em['k']:.3f} x={em['x']:.3f}",
        f"LATERAL: {lat_nom:.0f} mm, {l_len:.1f} m, {n_em_lat} EMITTERS, "
        f"HEAD SPREAD {lat['res'].get('spread_m', 0):.3f} m",
        f"EU: {lat['eu']:.1f} %   TDH: {S.get('pump', {}).get('tdh', {}).get('tdh_m', 0):.2f} m",
        f"GENERATED BY IRRI-DRIP - WATER MANAGEMENT RESEARCH INSTITUTE",
    ]
    for i, line in enumerate(title):
        d.text("IRR-TITLE", 0.0, ty - i * th * 1.6, th, line)

    return d


def network_dxf(S: dict) -> str:
    """Full DXF text for the designed network."""
    return build_layout(S).render()


# ---------------------------------------------------------------------------
# Site plan — v2.0
# ---------------------------------------------------------------------------

def site_plan(S: dict) -> "DxfDocument":
    """
    The designed network ON THE FIELD, in local metres about the boundary
    centroid (x east, y north).

    Unlike :func:`build_layout`, nothing here is schematic: the boundary is
    the drawn or uploaded one, the laterals are the clipped rows, the
    manifolds are drawn through their row feeds and labelled section by
    section with their telescoped sizes, and every mainline and submain pipe
    carries its sized diameter. If the boundary was an ASSUMED rectangle the
    title block says so.
    """
    d = DxfDocument()
    op = S["operation"]
    net = S["network"]
    man = S.get("manifold") or {}
    poly = op["boundary_local"]
    for a, b in zip(poly, poly[1:] + poly[:1]):
        d.line("IRR-BOUNDARY", a[0], a[1], b[0], b[1])
    span = max(max(p[0] for p in poly) - min(p[0] for p in poly),
               max(p[1] for p in poly) - min(p[1] for p in poly), 1.0)
    th = max(0.8, span / 250.0)

    for su in op["subunits"]:
        for seg in su.get("_segments", []):
            d.line("IRR-LATERAL", seg[0][0], seg[0][1], seg[1][0], seg[1][1])
    designs = man.get("designs") or {}
    for mf in net["manifolds"]:
        pts = mf["points"]
        for a, b in zip(pts, pts[1:]):
            d.line("IRR-MANIFOLD", a[0], a[1], b[0], b[1])
        dz = designs.get(mf["subunit"])
        if dz and dz.get("runs"):
            sizes = "/".join(f"{r['pipe']['nominal_mm']:.0f}" for r in dz["runs"]
                             if r["branch"] == 1)
            mid = pts[len(pts) // 2]
            d.text("IRR-TEXT", mid[0] + th, mid[1] + th, th,
                   f"{mf['subunit']} MANIFOLD {sizes} mm")
    edges = man.get("tree_edges")
    nodes = man.get("tree_nodes")
    sizing = man.get("tree_sizing") or {}
    if edges and nodes and sizing:
        for key, s in sizing.items():
            e = edges[int(key)]
            a, b = nodes[e["a"]], nodes[e["b"]]
            layer = "IRR-MAINLINE" if e["kind"] == "mainline" else "IRR-SUBMAIN"
            d.line(layer, a[0], a[1], b[0], b[1])
            d.text("IRR-TEXT", (a[0] + b[0]) / 2 + th, (a[1] + b[1]) / 2 + th, th * 0.9,
                   f"{s['pipe']['nominal_mm']:.0f} {s['pipe']['material']} "
                   f"{s['length_m']:.0f} m")
    else:
        for pp in net["pipes"]:
            layer = "IRR-MAINLINE" if pp["kind"] == "mainline" else "IRR-SUBMAIN"
            for a, b in zip(pp["points"], pp["points"][1:]):
                d.line(layer, a[0], a[1], b[0], b[1])
    for v in net["valves"]:
        x, y = v["xy"]
        d.circle("IRR-VALVE", x, y, th * 0.8)
        d.text("IRR-TEXT", x + th, y - th * 1.6, th * 0.9, v["id"])
    sx, sy = net["source"]
    d.rect("IRR-HEADWORKS", sx - 2 * th, sy - 2 * th, sx + 2 * th, sy + 2 * th)
    d.text("IRR-TEXT", sx + 2.5 * th, sy, th, "SOURCE / PUMP / HEAD CONTROL")

    x0 = min(p[0] for p in poly)
    y0 = min(p[1] for p in poly) - 6 * th
    verdict = S.get("verdict") or {}
    lines = []
    if verdict and not verdict.get("passed", True):
        lines += ["*** NOT PASSED - THIS DESIGN FAILED ITS OWN CHECKS ***",
                  "DO NOT ISSUE, TENDER OR CONSTRUCT FROM THIS DRAWING.",
                  "FAILED: " + _ascii("; ".join(verdict.get("failed_checks", [])) or "-").upper()]
    setup = S["setup"]
    hy = S.get("hydraulic") or {}
    lines += [
        "VERDICT: " + ("NOT RECORDED" if not verdict else
                       "PASSED ALL DESIGN CHECKS" if verdict.get("passed") else "NOT PASSED"),
        f"PROJECT: {setup.get('name') or 'UNTITLED'}   LOCATION: {setup.get('location') or '-'}",
        f"GEOMETRY: {str(op.get('geometry_source', '')).upper()}"
        + ("  - ASSUMED RECTANGLE, NOT A SURVEY" if "assumed" in str(op.get("geometry_source", "")) else ""),
        f"SUBUNITS: {op['n_subunits']}   SHIFTS: {op['shifts']}   "
        f"DUTY: {hy.get('q_duty', 0):.1f} m3/h AT {hy.get('h_duty', 0):.1f} m",
        "LOCAL METRES ABOUT THE FIELD CENTROID, X EAST, Y NORTH. SET CAD UNITS TO METRES.",
        "GENERATED BY IRRI-DRIP 3.0 - WATER MANAGEMENT RESEARCH INSTITUTE.",
        "NO OUTPUT MAY BE ISSUED WITHOUT INDEPENDENT VERIFICATION BY A QUALIFIED ENGINEER.",
    ]
    for i, ln in enumerate(lines):
        d.text("IRR-TITLE", x0, y0 - i * th * 1.8, th * 1.1, ln)
    return d


def site_plan_dxf(S: dict) -> str:
    return site_plan(S).render()
