"""
Subunits and the shift schedule, derived from the field geometry.

A SUBUNIT is the hydraulic unit of a drip system: one manifold, the laterals
it feeds, and the valve (with its pressure regulator, where one is fitted) at
its inlet. A SHIFT is the set of subunits whose valves open together.

Version 1 had neither. It computed one lateral and one manifold and assumed
one manifold per shift, so the number of manifolds was the number of shifts
— which the field-layout test on the Wadi El-Natrun plot showed to be a
confusion of two independent quantities. The number of subunits is set by
GEOMETRY (how far one lateral can run and how long one manifold can be);
the number of shifts is set by WATER (how much of the field the source can
irrigate at once). This module computes the first from the polygon and then
packs the subunits into shifts under the second.

All geometry is in local metres (see engine/fieldnet.py). Rows come from
:func:`fieldnet.network_geometry`, clipped to the real boundary, so a short
row near a corner carries a short lateral and a smaller flow.
"""

from __future__ import annotations

import math

from . import fieldnet as FN

__all__ = ["subunits_for_block", "allocate_shifts", "rectangle_polygon",
           "SHIFT_STRATEGIES"]

SHIFT_STRATEGIES = ("balanced", "contiguous")


def rectangle_polygon(length_m: float, width_m: float) -> list[list[float]]:
    """
    A rectangle centred on the origin with its LONG side north-south.

    Used only when no boundary was drawn. The caller labels everything built on
    it as an assumed rectangle; nothing here pretends it is a site plan.
    """
    a, b = float(length_m) / 2.0, float(width_m) / 2.0
    return [[-b, -a], [b, -a], [b, a], [-b, a]]


def _feed_point(row: dict, along, feed: str):
    if feed == "middle":
        return row["feed_point"]
    main = max(row["segments"], key=lambda s: math.hypot(s[1][0] - s[0][0],
                                                         s[1][1] - s[0][1]))
    ua = main[0][0] * along[0] + main[0][1] * along[1]
    ub = main[1][0] * along[0] + main[1][1] * along[1]
    return main[0] if ua <= ub else main[1]


def _straight_manifold(rows: list[dict], along, across):
    """
    Feed points for a mid-fed band on ONE straight manifold.

    fieldnet feeds each row at the midpoint of its own run. On a slanted
    boundary those midpoints step sideways from row to row, and a manifold
    drawn through them zig-zags: on the Wadi El-Natrun plot a 98 m band came
    out as a 131 m manifold. A built manifold is straight. It is placed at
    the median midpoint, and each row then has two UNEQUAL arms; the
    hydraulic run of the row is the longer one.
    """
    spans = []
    for r in rows:
        main = max(r["segments"], key=lambda s: math.hypot(s[1][0] - s[0][0],
                                                           s[1][1] - s[0][1]))
        ua = main[0][0] * along[0] + main[0][1] * along[1]
        ub = main[1][0] * along[0] + main[1][1] * along[1]
        spans.append((min(ua, ub), max(ua, ub), r["offset_m"]))
    mids = sorted((a + b) / 2.0 for a, b, _ in spans)
    u_m = mids[len(mids) // 2]
    feeds, runs = [], []
    for a, b, v in spans:
        u = min(max(u_m, a), b)
        feeds.append([u * along[0] + v * across[0], u * along[1] + v * across[1]])
        runs.append(max(u - a, b - u))
    return feeds, runs


def subunits_for_block(poly: list[list[float]], bearing_deg: float,
                       lateral_spacing_m: float, design_run_m: float,
                       emitter_spacing_m: float, q_emitter_lph: float,
                       lateral_feed: str = "end", max_manifold_m: float = 120.0,
                       laterals_per_row: int = 1, block_id: int = 1,
                       block_name: str = "Block 1") -> dict:
    """
    Cut one block into subunits.

    Bands along the lateral direction come from the design run length (a
    lateral cannot be longer than the hydraulics allow); within a band the
    rows are split across into manifolds no longer than ``max_manifold_m``.
    Returns the subunits and the underlying row geometry.
    """
    if max_manifold_m <= 0:
        raise ValueError("Maximum manifold length must be positive.")
    if emitter_spacing_m <= 0 or q_emitter_lph <= 0:
        raise ValueError("Emitter spacing and discharge must be positive.")
    g = FN.network_geometry(poly, bearing_deg, lateral_spacing_m, design_run_m,
                            feed=lateral_feed)
    along, across = FN.unit_vectors(bearing_deg)
    subunits = []
    for band in range(1, g["bands"] + 1):
        rows = sorted((r for r in g["rows"] if r["band"] == band),
                      key=lambda r: r["offset_m"])
        if not rows:
            continue
        v0 = rows[0]["offset_m"]
        v1 = rows[-1]["offset_m"]
        width = v1 - v0 + lateral_spacing_m
        parts = max(1, math.ceil(width / max_manifold_m - 1e-9))
        step = width / parts
        groups: list[list[dict]] = [[] for _ in range(parts)]
        for r in rows:
            k = min(parts - 1, int((r["offset_m"] - v0 + lateral_spacing_m / 2.0) // step))
            groups[k].append(r)
        for part, grp in enumerate(groups, start=1):
            if not grp:
                continue
            if lateral_feed == "middle":
                feeds, runs = _straight_manifold(grp, along, across)
            else:
                feeds = [list(_feed_point(r, along, "end")) for r in grp]
                runs = [r["run_length_m"] for r in grp]
            man_len = sum(math.hypot(b[0] - a[0], b[1] - a[1])
                          for a, b in zip(feeds, feeds[1:]))
            dripline = sum(r["row_length_m"] for r in grp) * laterals_per_row
            emitters = dripline / emitter_spacing_m
            q = emitters * q_emitter_lph / 1000.0
            n_lat = len(grp) * laterals_per_row * (2 if lateral_feed == "middle" else 1)
            # Each manifold outlet feeds the laterals of one row. Its flow is
            # the row's own flow, so short rows near a corner draw less.
            outlets = [{"xy": f, "q_m3h": r["row_length_m"] * laterals_per_row
                        / emitter_spacing_m * q_emitter_lph / 1000.0,
                        "row": r["index"], "run_m": run}
                       for f, r, run in zip(feeds, grp, runs)]
            subunits.append({
                "id": f"B{block_id}-S{len(subunits) + 1}",
                "block_id": block_id, "block_name": block_name,
                "band": band, "part": part,
                "rows": [r["index"] for r in grp],
                "n_rows": len(grp), "n_laterals": n_lat,
                "feeds": feeds, "outlets": outlets,
                "manifold_m": man_len,
                "dripline_m": dripline, "emitters": emitters, "q_m3h": q,
                "area_ha": sum(r["row_length_m"] for r in grp) * lateral_spacing_m / 10000.0,
                "max_run_m": max(runs),
                "centre": [sum(p[0] for p in feeds) / len(feeds),
                           sum(p[1] for p in feeds) / len(feeds)],
            })
    return {"subunits": subunits, "geometry": g}


def allocate_shifts(subunits: list[dict], q_avail_m3h: float,
                    strategy: str = "balanced", source_xy=None,
                    min_shifts: int = 1) -> dict:
    """
    Pack subunits into shifts so that no shift draws more than the source.

    ``balanced``    longest-processing-time packing: largest subunit first,
                    into the currently lightest shift that still has room.
                    Shift flows come out nearly equal, which keeps the pump
                    at one duty point.
    ``contiguous``  subunits ordered by distance from the source, farthest
                    first, filled shift by shift. Neighbouring valves open
                    together, which is simpler to operate by hand but
                    concentrates the flow and needs larger far-end pipes.

    The number of shifts starts at the minimum the water allows and rises
    only if the packing fails. A subunit that alone exceeds the source cannot
    be scheduled at all; it is reported, not silently split.
    """
    if strategy not in SHIFT_STRATEGIES:
        raise ValueError(f"strategy must be one of {SHIFT_STRATEGIES}")
    if q_avail_m3h <= 0:
        raise ValueError("Available source discharge must be greater than zero.")
    if not subunits:
        return {"n_shifts": 0, "assignment": {}, "loads": [], "oversize": [],
                "feasible": False, "strategy": strategy}
    oversize = [s["id"] for s in subunits if s["q_m3h"] > q_avail_m3h + 1e-9]
    total = sum(s["q_m3h"] for s in subunits)
    n = max(int(min_shifts), 1, math.ceil(total / q_avail_m3h - 1e-9))
    fit = [s for s in subunits if s["id"] not in oversize]

    def pack(n_sh):
        loads = [0.0] * n_sh
        assign = {}
        if strategy == "balanced":
            for s in sorted(fit, key=lambda s: -s["q_m3h"]):
                order = sorted(range(n_sh), key=lambda i: loads[i])
                for i in order:
                    if loads[i] + s["q_m3h"] <= q_avail_m3h + 1e-9:
                        loads[i] += s["q_m3h"]
                        assign[s["id"]] = i + 1
                        break
                else:
                    return None
        else:
            sx, sy = source_xy if source_xy is not None else (0.0, 0.0)
            ordered = sorted(fit, key=lambda s: -math.hypot(s["centre"][0] - sx,
                                                          s["centre"][1] - sy))
            target = sum(s["q_m3h"] for s in fit) / n_sh
            i = 0
            for s in ordered:
                if (loads[i] > 0 and (loads[i] + s["q_m3h"] > q_avail_m3h + 1e-9
                                      or loads[i] >= target - 1e-9)
                        and i < n_sh - 1):
                    i += 1
                if loads[i] + s["q_m3h"] > q_avail_m3h + 1e-9:
                    return None
                loads[i] += s["q_m3h"]
                assign[s["id"]] = i + 1
        return loads, assign

    result = None
    while result is None and n <= len(fit) + 1:
        result = pack(n)
        if result is None:
            n += 1
    if result is None:              # cannot happen while every subunit fits
        return {"n_shifts": 0, "assignment": {}, "loads": [], "oversize": oversize,
                "feasible": False, "strategy": strategy}
    loads, assign = result
    return {
        "n_shifts": n, "assignment": assign, "loads": loads,
        "max_load_m3h": max(loads), "min_load_m3h": min(loads),
        "mean_load_m3h": sum(loads) / n,
        "balance_pct": 100.0 * min(loads) / max(loads) if max(loads) > 0 else 0.0,
        "oversize": oversize, "feasible": not oversize and all(l > 0 for l in loads),
        "strategy": strategy, "q_avail_m3h": q_avail_m3h,
    }


def shift_loads(subunits: list[dict], assignment: dict) -> dict:
    """Flows per shift for an arbitrary (e.g. hand-edited) assignment."""
    loads: dict[int, float] = {}
    for s in subunits:
        sh = int(assignment.get(s["id"], 0))
        if sh > 0:
            loads[sh] = loads.get(sh, 0.0) + s["q_m3h"]
    return loads
