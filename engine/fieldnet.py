"""
The designed network laid onto the REAL field boundary.

Everything this program drew until now assumed a rectangle. The DXF says so on
its face — "THIS IS NOT A SITE PLAN" — and that disclaimer was honest, but it
left the most consequential question unanswered: the hydraulic design sizes one
lateral length and applies it to every row, and on a real boundary the rows are
not all that length.

That is not a cosmetic gap. Lateral head loss rises as roughly L^(m+1) once the
multi-outlet factor is folded in, so a row 20 % longer than the design length
carries far more than 20 % more head loss. A design that passes its head-spread
check at the nominal length can fail on a third of its rows and the program
would never have said so.

This module answers it geometrically: it lays the lateral rows across the true
polygon at the design spacing, clips each one to the boundary, and reports what
the rows actually measure. The result feeds two things — a KML that opens over
the satellite image, and a table of rows that exceed the length the hydraulics
were computed for.

All geometry here is in LOCAL METRES (x east, y north) about the field
centroid, the same frame :func:`modules.layout.to_local` produces. Nothing here
touches latitude or longitude; the caller converts back with ``to_gps``.
"""

from __future__ import annotations

import math

__all__ = ["unit_vectors", "point_in_polygon", "clip_segment",
           "lateral_rows", "network_geometry", "bands_needed", "FEED_MODES"]

FEED_MODES = ("end", "middle")

# Segments shorter than this are dropped. A lateral row clipped to a few
# centimetres in a corner of the polygon is a geometric artefact, not pipe.
_MIN_RUN_M = 1.0

# Parametric tolerance for merging near-duplicate crossings at a vertex.
_EPS = 1e-9


def unit_vectors(bearing_deg: float) -> tuple[tuple[float, float],
                                              tuple[float, float]]:
    """
    (along, across) unit vectors for a bearing clockwise from north.

    In the local frame x is east and y is north, so a bearing b gives
    along = (sin b, cos b). The across vector is that rotated by 90 degrees.
    They are orthonormal, so a point is recovered exactly as
    ``u * along + v * across``.
    """
    b = math.radians(bearing_deg)
    along = (math.sin(b), math.cos(b))
    across = (math.cos(b), -math.sin(b))
    return along, across


def point_in_polygon(pt: tuple[float, float],
                     poly: list[list[float]]) -> bool:
    """
    Ray casting. Handles a non-convex boundary, which a real field often is.

    Points exactly on an edge are not guaranteed either way, which is why the
    caller tests interval MIDPOINTS rather than endpoints.
    """
    x, y = pt
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xin = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < xin:
                inside = not inside
    return inside


def clip_segment(p1: tuple[float, float], p2: tuple[float, float],
                 poly: list[list[float]]) -> list[tuple[tuple[float, float],
                                                        tuple[float, float]]]:
    """
    The parts of segment p1->p2 that lie inside ``poly``.

    Returns a list because a concave boundary can cut one row into several
    runs — an L-shaped field is the ordinary case, not an exotic one, and
    silently returning only the first run would under-report the pipe.

    Method: collect the parameters t where the segment crosses any edge, add
    the endpoints, sort, then keep each interval whose midpoint is inside. The
    midpoint test is what makes this correct through vertices and along edges,
    where an endpoint test is ambiguous.
    """
    x1, y1 = p1
    x2, y2 = p2
    dx, dy = x2 - x1, y2 - y1
    ts = [0.0, 1.0]
    n = len(poly)
    for i in range(n):
        x3, y3 = poly[i]
        x4, y4 = poly[(i + 1) % n]
        den = dx * (y4 - y3) - dy * (x4 - x3)
        if abs(den) < 1e-14:                 # parallel or degenerate
            continue
        t = ((x3 - x1) * (y4 - y3) - (y3 - y1) * (x4 - x3)) / den
        s = ((x3 - x1) * dy - (y3 - y1) * dx) / den
        if 0.0 <= t <= 1.0 and 0.0 <= s <= 1.0:
            ts.append(t)
    ts.sort()
    runs = []
    for a, b in zip(ts, ts[1:]):
        if b - a < _EPS:
            continue
        tm = 0.5 * (a + b)
        if point_in_polygon((x1 + dx * tm, y1 + dy * tm), poly):
            runs.append(((x1 + dx * a, y1 + dy * a),
                         (x1 + dx * b, y1 + dy * b)))
    return runs


def _length(seg) -> float:
    (ax, ay), (bx, by) = seg
    return math.hypot(bx - ax, by - ay)


def bands_needed(span_m: float, design_run_m: float, feed: str = "end") -> int:
    """
    How many manifold bands the field must be cut into along the lateral axis.

    This is the number the program never computed and the DXF quietly assumed
    to be the shift count. They are not the same thing. The shift count comes
    from the water supply and the operating hours; the band count comes from
    GEOMETRY — a field 267 m long cannot be served by 65 m laterals from one
    manifold, whatever the pump can deliver.

    A mid-fed band is twice as long as an end-fed one for the same hydraulic
    run, which is why mid-feed halves the number of manifolds as well as the
    head loss.
    """
    if design_run_m <= 0:
        raise ValueError("design_run_m must be positive.")
    reach = design_run_m * (2.0 if feed == "middle" else 1.0)
    return max(1, math.ceil(span_m / reach - 1e-9))


def lateral_rows(poly: list[list[float]], bearing_deg: float,
                 spacing_m: float, feed: str = "end",
                 bands: int = 1) -> list[dict]:
    """
    Lay lateral rows across the polygon at ``spacing_m`` and clip each to it.

    Rows are placed half a spacing in from the first edge, which is what a
    contractor does: the first dripline does not sit on the boundary line.

    ``feed`` selects where the manifold meets the row:

    ``"end"``
        one run per row, fed from the low-u end. The hydraulic run length is
        the whole clipped length.
    ``"middle"``
        the row is fed at its midpoint and runs both ways. The hydraulic run
        length is the LONGER arm, not half the row: on a clipped row the two
        arms are rarely equal, and sizing on the average would under-design
        the long one.

    Each row dict carries the geometry and the run length the hydraulics must
    be judged against.
    """
    if feed not in FEED_MODES:
        raise ValueError(f"feed must be one of {FEED_MODES}, got {feed!r}")
    if spacing_m <= 0:
        raise ValueError(f"Lateral spacing must be positive, got {spacing_m}.")
    if len(poly) < 3:
        raise ValueError("A boundary needs at least 3 vertices.")

    along, across = unit_vectors(bearing_deg)
    us = [p[0] * along[0] + p[1] * along[1] for p in poly]
    vs = [p[0] * across[0] + p[1] * across[1] for p in poly]
    u_lo, u_hi = min(us) - 1.0, max(us) + 1.0
    v_lo, v_hi = min(vs), max(vs)

    if bands < 1:
        raise ValueError(f"bands must be at least 1, got {bands}.")
    band_w = (u_hi - u_lo) / bands

    rows: list[dict] = []
    n_rows = max(0, int(math.floor((v_hi - v_lo) / spacing_m)))
    for k in range(n_rows):
        v = v_lo + spacing_m * (k + 0.5)
        if v > v_hi:
            break
        for j in range(bands):
            ua = u_lo + j * band_w
            ub = ua + band_w
            p1 = (ua * along[0] + v * across[0], ua * along[1] + v * across[1])
            p2 = (ub * along[0] + v * across[0], ub * along[1] + v * across[1])
            _append_row(rows, clip_segment(p1, p2, poly), v, j + 1, feed)
    return rows


def _append_row(rows: list[dict], raw, v: float, band: int, feed: str) -> None:
    runs = [r for r in raw if _length(r) >= _MIN_RUN_M]
    if runs:
        row = {"index": len(rows) + 1, "band": band, "offset_m": v,
               "segments": runs, "row_length_m": sum(_length(r) for r in runs),
               "n_runs": len(runs)}
        if feed == "end":
            row["run_length_m"] = max(_length(r) for r in runs)
            row["arms_m"] = [_length(r) for r in runs]
        else:
            # Feed at the midpoint of the LONGEST run. A concave row fed at
            # the midpoint of its total length can have its feed point outside
            # the field, which is not a pipe layout anyone can build.
            main = max(runs, key=_length)
            half = _length(main) / 2.0
            row["arms_m"] = [half, half]
            row["run_length_m"] = half
            row["feed_point"] = ((main[0][0] + main[1][0]) / 2.0,
                                 (main[0][1] + main[1][1]) / 2.0)
        rows.append(row)


def network_geometry(poly: list[list[float]], bearing_deg: float,
                     spacing_m: float, design_run_m: float,
                     feed: str = "end", bands: int | None = None) -> dict:
    """
    Rows, manifold, and the comparison against the designed run length.

    ``design_run_m`` is the lateral length the hydraulics were computed for.
    Every row whose run exceeds it is flagged: those rows carry more head loss
    than the design check allowed for, and the emission uniformity computed on
    the nominal length does not apply to them.
    """
    along, across = unit_vectors(bearing_deg)
    us = [p[0] * along[0] + p[1] * along[1] for p in poly]
    span_m = max(us) - min(us)
    auto_bands = bands_needed(span_m, design_run_m, feed)
    if bands is None:
        bands = auto_bands

    rows = lateral_rows(poly, bearing_deg, spacing_m, feed, bands)

    runs = [r["run_length_m"] for r in rows]
    over = [r for r in rows if r["run_length_m"] > design_run_m + 1e-9]
    total_lateral_m = sum(r["row_length_m"] for r in rows)

    # One manifold per band, not one for the whole field. Each is the polyline
    # through the feed points of the rows in that band, which is what it is on
    # the ground.
    manifolds: list[list[tuple[float, float]]] = []
    for band in range(1, bands + 1):
        line: list[tuple[float, float]] = []
        for r in rows:
            if r["band"] != band:
                continue
            if feed == "middle":
                line.append(r["feed_point"])
            else:
                main = max(r["segments"], key=_length)
                u_a = main[0][0] * along[0] + main[0][1] * along[1]
                u_b = main[1][0] * along[0] + main[1][1] * along[1]
                line.append(main[0] if u_a <= u_b else main[1])
        if len(line) >= 2:
            manifolds.append(line)

    manifold = [pt for line in manifolds for pt in line]
    return {
        "feed": feed,
        "spacing_m": spacing_m,
        "bearing_deg": bearing_deg,
        "design_run_m": design_run_m,
        "span_m": span_m,
        "bands": bands,
        "bands_needed": auto_bands,
        "rows": rows,
        "manifolds": manifolds,
        "manifold": manifold,
        "n_laterals": len(rows),
        "n_rows_across": len({r["offset_m"] for r in rows}),
        "total_lateral_m": total_lateral_m,
        "manifold_m": sum(
            math.hypot(b[0] - a[0], b[1] - a[1])
            for line in manifolds for a, b in zip(line, line[1:])),
        "max_run_m": max(runs) if runs else 0.0,
        "min_run_m": min(runs) if runs else 0.0,
        "mean_run_m": (sum(runs) / len(runs)) if runs else 0.0,
        "n_laterals_over_design": len(over),
        "worst_overrun_m": (max(r["run_length_m"] for r in over) - design_run_m
                            if over else 0.0),
        "laterals_over_design": [r["index"] for r in over],
    }
