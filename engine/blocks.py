"""
Crop blocks: cutting the field polygon into the areas that are designed.

A block is a part of the field with one crop and one irrigation decision. A
drip block is laid out and designed; an excluded block (a track, a building
plot, a pivot circle, an orchard left on flood) contributes nothing to the
net irrigated area.

Everything is in LOCAL METRES about the field centroid, the frame produced by
:func:`modules.layout.to_local`.

Splitting method
----------------
Blocks are cut with straight lines perpendicular to a chosen axis so that
every piece has the same AREA, not the same width. On a trapezoidal field an
equal-width cut gives blocks of different size and therefore shifts of
different duration — exactly what a block split is supposed to prevent.
The cut positions are found by bisection on the area of the polygon clipped
to a half-plane; Sutherland-Hodgman clipping against a half-plane is exact
for any simple polygon, convex or not.
"""

from __future__ import annotations

import math

__all__ = ["polygon_area", "polygon_centroid", "clip_halfplane", "clip_band",
           "split_equal_area", "BLOCK_COLOURS", "make_block", "blocks_summary"]

# Distinct, colour-vision-safe fills for up to ten blocks; cycles beyond that.
BLOCK_COLOURS = ["#0078d4", "#ff9f1c", "#2ec4b6", "#e63946", "#6f42c1",
                 "#00a86b", "#d4a017", "#8c564b", "#17becf", "#bc5090"]


def polygon_area(poly: list[list[float]]) -> float:
    """Unsigned shoelace area, m2."""
    n = len(poly)
    if n < 3:
        return 0.0
    s = 0.0
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def polygon_centroid(poly: list[list[float]]) -> tuple[float, float]:
    """Area centroid; falls back to the vertex mean for a degenerate ring."""
    n = len(poly)
    a = 0.0
    cx = cy = 0.0
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        cr = x1 * y2 - x2 * y1
        a += cr
        cx += (x1 + x2) * cr
        cy += (y1 + y2) * cr
    if abs(a) < 1e-12:
        return (sum(p[0] for p in poly) / max(n, 1),
                sum(p[1] for p in poly) / max(n, 1))
    return cx / (3.0 * a), cy / (3.0 * a)


def clip_halfplane(poly: list[list[float]], normal: tuple[float, float],
                   c: float) -> list[list[float]]:
    """
    The part of ``poly`` where normal . p <= c (Sutherland-Hodgman, one edge).
    """
    nx, ny = normal
    out: list[list[float]] = []
    n = len(poly)
    for i in range(n):
        p = poly[i]
        q = poly[(i + 1) % n]
        dp = nx * p[0] + ny * p[1] - c
        dq = nx * q[0] + ny * q[1] - c
        if dp <= 0:
            out.append([p[0], p[1]])
        if (dp < 0 < dq) or (dq < 0 < dp):
            t = dp / (dp - dq)
            out.append([p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])])
    return out


def clip_band(poly: list[list[float]], axis: tuple[float, float],
              lo: float, hi: float) -> list[list[float]]:
    """The part of ``poly`` with lo <= axis . p <= hi."""
    part = clip_halfplane(poly, axis, hi)
    return clip_halfplane(part, (-axis[0], -axis[1]), -lo)


def _axis_from_bearing(bearing_deg: float) -> tuple[float, float]:
    b = math.radians(bearing_deg)
    return (math.sin(b), math.cos(b))


def split_equal_area(poly: list[list[float]], bearing_deg: float,
                     parts: int) -> list[list[list[float]]]:
    """
    Cut ``poly`` into ``parts`` pieces of equal area with lines perpendicular
    to the bearing (so the pieces follow one another ALONG the bearing).
    """
    parts = int(parts)
    if parts < 1:
        raise ValueError(f"parts must be at least 1, got {parts}.")
    if len(poly) < 3:
        raise ValueError("A polygon needs at least 3 vertices.")
    if parts == 1:
        return [[list(p) for p in poly]]
    axis = _axis_from_bearing(bearing_deg)
    proj = [axis[0] * p[0] + axis[1] * p[1] for p in poly]
    lo, hi = min(proj), max(proj)
    total = polygon_area(poly)
    cuts = [lo]
    for k in range(1, parts):
        target = total * k / parts
        a, b = lo, hi
        for _ in range(80):                   # 2^-80 of the span: exact enough
            mid = 0.5 * (a + b)
            if polygon_area(clip_halfplane(poly, axis, mid)) < target:
                a = mid
            else:
                b = mid
        cuts.append(0.5 * (a + b))
    cuts.append(hi)
    pieces = []
    for k in range(parts):
        piece = clip_band(poly, axis, cuts[k], cuts[k + 1])
        if len(piece) >= 3 and polygon_area(piece) > 1e-6:
            pieces.append(piece)
    return pieces


def make_block(idx: int, polygon: list[list[float]], crop_idx: int = 0,
               crop_name: str = "", irrigation: str = "Drip",
               name: str | None = None) -> dict:
    return {
        "id": idx,
        "name": name or f"Block {idx}",
        "polygon_local": [[float(p[0]), float(p[1])] for p in polygon],
        "area_ha": polygon_area(polygon) / 10000.0,
        "crop_idx": int(crop_idx),
        "crop_name": crop_name,
        "irrigation": irrigation,
        "color": BLOCK_COLOURS[(idx - 1) % len(BLOCK_COLOURS)],
    }


def blocks_summary(blocks: list[dict], field_area_ha: float | None = None) -> dict:
    drip = [b for b in blocks if b.get("irrigation") == "Drip"]
    excl = [b for b in blocks if b.get("irrigation") != "Drip"]
    total = sum(b["area_ha"] for b in blocks)
    out = {
        "n_blocks": len(blocks),
        "n_drip": len(drip),
        "drip_area_ha": sum(b["area_ha"] for b in drip),
        "excluded_area_ha": sum(b["area_ha"] for b in excl),
        "block_area_ha": total,
    }
    if field_area_ha:
        out["coverage_pct"] = 100.0 * total / field_area_ha
    return out
