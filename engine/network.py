"""
The pipe network: layout, tree hydraulics, and telescoped pipe sizing.

UI-free. Everything is in local metres about the field centroid (x east,
y north), the frame of engine/fieldnet.py.

Three things live here that version 1 did not have at all.

1. A NETWORK. Version 1 sized one lateral, one manifold and one straight
   mainline "from the source to the first manifold", and drew the rest of the
   distribution run on a layer called IRR-NOT-DESIGNED because nothing had
   sized it. Here the mainline and submains form a tree from the source to
   every subunit valve, every pipe in it is sized, and the head required at
   the source is computed for every shift, not for one assumed path.

2. TELESCOPING. A manifold carries its full flow only in its first segment;
   by the last outlet it carries one row's worth. Sizing it on the inlet flow
   over its whole length is what version 1 did, and what most spreadsheets
   do. Here each manifold is built from up to three sizes, stepped down as
   the flow falls, and the step-down is chosen by cost per metre of head
   spread saved — never below the velocity limit, never above the allowable
   spread.

3. A STEP METHOD FOR MANIFOLDS. The Christiansen factor assumes equal outlet
   flows at equal spacing on one diameter. A manifold on a real boundary has
   none of the three: short corner rows draw less, the first outlet is not a
   full spacing from the inlet, and a telescoped manifold changes diameter.
   The manifold is therefore marched outlet by outlet with the actual flows,
   using the same Darcy-Weisbach / Swamee-Jain friction as the rest of the
   program. On the idealised case the march agrees with the Christiansen
   calculation (see tests/test_network.py), which is what licenses using it
   on the non-ideal one.
"""

from __future__ import annotations

import heapq
import math

from . import kernels as K
from . import fieldnet as FN

__all__ = [
    "auto_network", "build_tree", "size_tree", "tree_hydraulics",
    "telescoped_manifold", "manifold_march", "max_lateral_run",
    "polyline_length", "pipe_catalogue",
]


# ---------------------------------------------------------------------------
# Small geometry helpers
# ---------------------------------------------------------------------------

def _dist(a, b) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def polyline_length(points) -> float:
    return sum(_dist(a, b) for a, b in zip(points, points[1:]))


def pipe_catalogue(rows: list[dict]) -> list[K.PipeOption]:
    """Catalogue rows (data/pipes.json) as PipeOption, smallest bore first."""
    opts = [K.PipeOption(p["nominal_mm"], p["internal_mm"], p["material"],
                         p["pn_bar"], p.get("price_egp_per_m", 0.0)) for p in rows]
    return sorted(opts, key=lambda o: (o.internal_mm, o.price_egp_per_m))


def _pipe_dict(p: K.PipeOption) -> dict:
    return {"nominal_mm": p.nominal_mm, "internal_mm": p.internal_mm,
            "material": p.material, "pn_bar": p.pn_bar,
            "price": p.price_egp_per_m}


# ---------------------------------------------------------------------------
# 1. Automatic layout
# ---------------------------------------------------------------------------

def auto_network(subunits: list[dict], source_xy, bearing_deg: float,
                 manifold_inlet: str = "end") -> dict:
    """
    A comb layout from the source to every subunit valve.

    Manifolds run ACROSS the lateral direction, one per subunit, through the
    feed points of its rows. Its valve sits at the manifold end nearer the
    source (``manifold_inlet="end"``) or at its middle (``"middle"``, which
    halves the manifold run and its head spread).

    A submain runs ALONG the lateral direction through the valves of one
    column of subunits, nearest band first. A header joins the heads of the
    submains in a block, and the mainline joins the source to each block's
    header — blocks in the order of a greedy nearest-connection (Prim) tree,
    so a second block is connected to whichever pipe is nearest, not
    necessarily to the source.

    This is a starting layout, not an optimum. The Pipe Network Layout page
    lets the designer redraw any of it, and the hydraulics are taken from the
    network as drawn.
    """
    if manifold_inlet not in ("end", "middle"):
        raise ValueError("manifold_inlet must be 'end' or 'middle'.")
    along, across = FN.unit_vectors(bearing_deg)
    sx, sy = float(source_xy[0]), float(source_xy[1])
    u_src = sx * along[0] + sy * along[1]
    v_src = sx * across[0] + sy * across[1]

    def uv(p):
        return (p[0] * along[0] + p[1] * along[1],
                p[0] * across[0] + p[1] * across[1])

    pipes: list[dict] = []
    valves: list[dict] = []
    manifolds: list[dict] = []
    columns: dict[tuple, list[tuple]] = {}
    for su in subunits:
        feeds = su["feeds"]
        if manifold_inlet == "middle":
            k = len(feeds) // 2
        else:
            v_first = uv(feeds[0])[1]
            v_last = uv(feeds[-1])[1]
            k = 0 if abs(v_first - v_src) <= abs(v_last - v_src) else len(feeds) - 1
        valve = list(feeds[k])
        valves.append({"id": su["id"], "xy": valve})
        manifolds.append({"subunit": su["id"], "points": [list(p) for p in feeds],
                          "inlet_index": k})
        columns.setdefault((su["block_id"], su["part"]), []).append(
            (abs(uv(valve)[0] - u_src), valve, su["id"]))

    heads_by_block: dict[int, list] = {}
    for (block_id, part), items in sorted(columns.items()):
        items.sort(key=lambda t: t[0])
        pts = [it[1] for it in items]
        if len(pts) >= 2:
            pipes.append({"id": f"SM-{block_id}.{part}", "kind": "submain",
                          "points": [list(p) for p in pts]})
        heads_by_block.setdefault(block_id, []).append(pts[0])

    block_nodes: dict[int, list] = {}
    for block_id, heads in heads_by_block.items():
        heads = sorted(heads, key=lambda p: uv(p)[1])
        if len(heads) >= 2:
            pipes.append({"id": f"HD-{block_id}", "kind": "mainline",
                          "points": [list(p) for p in heads]})
        nodes = list(heads)
        for pp in pipes:
            if pp["id"].startswith(f"SM-{block_id}."):
                nodes.extend(pp["points"])
        block_nodes[block_id] = nodes

    # Greedy nearest-connection of blocks to the growing tree, from the source.
    connected = [[sx, sy]]
    remaining = dict(block_nodes)
    n_link = 0
    while remaining:
        best = None
        for bid, nodes in remaining.items():
            for a in connected:
                for b in nodes:
                    d = _dist(a, b)
                    if best is None or d < best[0]:
                        best = (d, bid, a, b)
        _, bid, a, b = best
        n_link += 1
        if _dist(a, b) > 1e-6:
            pipes.append({"id": f"ML-{n_link}", "kind": "mainline",
                          "points": [list(a), list(b)]})
        connected.extend(remaining.pop(bid))

    return {"source": [sx, sy], "pipes": pipes, "valves": valves,
            "manifolds": manifolds, "manifold_inlet": manifold_inlet,
            "bearing_deg": bearing_deg}


# ---------------------------------------------------------------------------
# 2. Tree from arbitrary drawn pipes
# ---------------------------------------------------------------------------

def _project(p, a, b):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 < 1e-12:
        return 0.0, (ax, ay), _dist(p, a)
    t = ((p[0] - ax) * dx + (p[1] - ay) * dy) / L2
    t = max(0.0, min(1.0, t))
    q = (ax + t * dx, ay + t * dy)
    return t, q, _dist(p, q)


def build_tree(pipes: list[dict], source_xy, valves: list[dict],
               merge_tol_m: float = 1.0, attach_tol_m: float = 25.0) -> dict:
    """
    Turn drawn polylines into a tree rooted at the source.

    Endpoints within ``merge_tol_m`` are one node. A valve or the source that
    does not sit on a node is attached to the nearest pipe within
    ``attach_tol_m`` by splitting that pipe at the foot of the perpendicular —
    so a hand-drawn mainline that passes a valve at a few metres still feeds
    it. Shortest paths from the source (Dijkstra on length) define the flow
    direction; a drawn loop is therefore opened, not solved, and the pipes it
    leaves unused are reported rather than priced.
    """
    nodes: list[list[float]] = []

    def node_of(p):
        for i, q in enumerate(nodes):
            if _dist(p, q) <= merge_tol_m:
                return i
        nodes.append([float(p[0]), float(p[1])])
        return len(nodes) - 1

    edges: list[dict] = []
    for pp in pipes:
        if pp.get("kind") not in ("mainline", "submain"):
            continue
        pts = pp["points"]
        for a, b in zip(pts, pts[1:]):
            if _dist(a, b) < 1e-6:
                continue
            edges.append({"a": node_of(a), "b": node_of(b), "pipe_id": pp["id"],
                          "kind": pp["kind"]})

    def attach(p):
        for i, q in enumerate(nodes):
            if _dist(p, q) <= merge_tol_m:
                return i
        best = None
        for ei, e in enumerate(edges):
            t, q, d = _project(p, nodes[e["a"]], nodes[e["b"]])
            if d <= attach_tol_m and (best is None or d < best[0]):
                best = (d, ei, t, q)
        if best is None:
            return None
        d, ei, t, q = best
        e = edges[ei]
        if t <= 1e-9:
            n_id = e["a"]
        elif t >= 1 - 1e-9:
            n_id = e["b"]
        else:
            nodes.append([q[0], q[1]])
            n_id = len(nodes) - 1
            edges.append({"a": n_id, "b": e["b"], "pipe_id": e["pipe_id"],
                          "kind": e["kind"]})
            e["b"] = n_id
        if d > merge_tol_m:
            # The valve is off the pipe by d metres: a short connecting run.
            nodes.append([float(p[0]), float(p[1])])
            tail = len(nodes) - 1
            edges.append({"a": n_id, "b": tail, "pipe_id": "tap", "kind": "submain"})
            return tail
        return n_id

    source_node = attach(source_xy)
    valve_nodes = {}
    unattached = []
    for v in valves:
        n_id = attach(v["xy"])
        if n_id is None:
            unattached.append(v["id"])
        else:
            valve_nodes[v["id"]] = n_id

    for i, e in enumerate(edges):
        e["id"] = i
        e["length_m"] = _dist(nodes[e["a"]], nodes[e["b"]])

    adj: dict[int, list] = {}
    for e in edges:
        adj.setdefault(e["a"], []).append((e["b"], e["id"]))
        adj.setdefault(e["b"], []).append((e["a"], e["id"]))

    dist = {}
    parent_edge = {}
    if source_node is not None:
        dist[source_node] = 0.0
        heap = [(0.0, source_node)]
        while heap:
            d, n = heapq.heappop(heap)
            if d > dist.get(n, math.inf) + 1e-12:
                continue
            for m, eid in adj.get(n, []):
                nd = d + edges[eid]["length_m"]
                if nd < dist.get(m, math.inf) - 1e-12:
                    dist[m] = nd
                    parent_edge[m] = eid
                    heapq.heappush(heap, (nd, m))

    paths = {}
    for vid, n_id in list(valve_nodes.items()):
        if n_id not in dist:
            unattached.append(vid)
            valve_nodes.pop(vid)
            continue
        path = []
        cur = n_id
        while cur != source_node:
            eid = parent_edge[cur]
            e = edges[eid]
            path.append(eid)
            cur = e["a"] if e["b"] == cur else e["b"]
        paths[vid] = list(reversed(path))

    used = {eid for p in paths.values() for eid in p}
    # Orient every used edge from upstream to downstream.
    for e in edges:
        if e["id"] in used and dist.get(e["a"], math.inf) > dist.get(e["b"], math.inf):
            e["a"], e["b"] = e["b"], e["a"]
    return {
        "nodes": nodes, "edges": edges, "source_node": source_node,
        "valve_nodes": valve_nodes, "paths": paths,
        "unattached": sorted(set(unattached)),
        "used_edges": sorted(used),
        "unused_edges": [e["id"] for e in edges if e["id"] not in used],
        "distance_m": {k: v for k, v in dist.items()},
    }


# ---------------------------------------------------------------------------
# 3. Sizing the tree and solving it shift by shift
# ---------------------------------------------------------------------------

def _edge_flows(tree: dict, open_valves, q_valve: dict) -> dict:
    flows: dict[int, float] = {}
    for vid in open_valves:
        for eid in tree["paths"].get(vid, []):
            flows[eid] = flows.get(eid, 0.0) + q_valve.get(vid, 0.0)
    return flows


def size_tree(tree: dict, shifts: dict, q_valve: dict,
              candidates: list[K.PipeOption], v_max_ms: float = 1.5,
              j_max_m_per_100m: float | None = 2.0, nu: float = K.NU_20C) -> dict:
    """
    Size every used pipe for the largest flow it carries in any shift.

    The design flow of a pipe is not the system flow: it is the sum of the
    valves downstream of it that are open together, maximised over the
    shifts. A pipe beyond the last valve of the balanced schedule may never
    carry more than one subunit.

    Criterion: the smallest bore with mean velocity <= ``v_max_ms`` and, if
    given, friction gradient <= ``j_max_m_per_100m``. The second limit is
    what keeps a long mainline from spending the whole pressure budget on
    friction while every velocity still looks acceptable.
    """
    if not candidates:
        raise ValueError("Pipe catalogue is empty.")
    cands = sorted(candidates, key=lambda o: (o.internal_mm, o.price_egp_per_m))
    design_q: dict[int, float] = {}
    for sh, vids in shifts.items():
        for eid, q in _edge_flows(tree, vids, q_valve).items():
            design_q[eid] = max(design_q.get(eid, 0.0), q)
    sizing = {}
    for eid, q in design_q.items():
        L = tree["edges"][eid]["length_m"]
        chosen, ok = None, False
        for opt in cands:
            r = K.head_loss_darcy(q, opt.internal_mm, max(L, 1e-6), nu, opt.roughness_mm)
            j = 100.0 * r["hf_m"] / max(L, 1e-6)
            if r["velocity_ms"] <= v_max_ms and (j_max_m_per_100m is None
                                                 or j <= j_max_m_per_100m):
                chosen, ok = opt, True
                break
        if chosen is None:
            chosen = cands[-1]
        r = K.head_loss_darcy(q, chosen.internal_mm, max(L, 1e-6), nu, chosen.roughness_mm)
        sizing[eid] = {"q_design_m3h": q, "pipe": _pipe_dict(chosen),
                       "velocity_ms": r["velocity_ms"], "hf_m": r["hf_m"],
                       "j_m_per_100m": 100.0 * r["hf_m"] / max(L, 1e-6),
                       "length_m": L, "satisfied": ok,
                       "cost": L * chosen.price_egp_per_m}
    return sizing


def tree_hydraulics(tree: dict, sizing: dict, shifts: dict, q_valve: dict,
                    h_req_valve: dict, z_of=None, nu: float = K.NU_20C) -> dict:
    """
    Head needed at the source in every shift, and the pressure each open
    valve then receives.

    For shift s:  H_s = max over open valves i of
                        [ h_req,i + (z_i - z_source) + friction source->i ]
    and every other open valve gets H_s minus its own path loss and lift. The
    surplus is what a pressure-regulating valve at that subunit must burn
    off; a large surplus is the signature of an unbalanced layout.
    """
    z_of = z_of or (lambda xy: 0.0)
    nodes = tree["nodes"]
    z_src = z_of(nodes[tree["source_node"]]) if tree["source_node"] is not None else 0.0
    per_shift = {}
    for sh, vids in shifts.items():
        vids = [v for v in vids if v in tree["paths"]]
        flows = _edge_flows(tree, vids, q_valve)
        hf = {}
        for eid, q in flows.items():
            p = sizing.get(eid, {}).get("pipe")
            if p is None:
                continue
            L = tree["edges"][eid]["length_m"]
            rough = K.ROUGHNESS_MM.get(str(p["material"]).upper(), 0.007)
            hf[eid] = K.head_loss_darcy(q, p["internal_mm"], max(L, 1e-6), nu, rough)["hf_m"]
        need = {}
        for v in vids:
            loss = sum(hf.get(e, 0.0) for e in tree["paths"][v])
            dz = z_of(nodes[tree["valve_nodes"][v]]) - z_src
            need[v] = (h_req_valve.get(v, 0.0) + dz + loss, loss, dz)
        if not need:
            continue
        crit = max(need, key=lambda v: need[v][0])
        H = need[crit][0]
        valves = {v: {"path_loss_m": need[v][1], "lift_m": need[v][2],
                      "pressure_m": H - need[v][1] - need[v][2],
                      "required_m": h_req_valve.get(v, 0.0),
                      "surplus_m": H - need[v][0]} for v in vids}
        per_shift[sh] = {"q_m3h": sum(q_valve.get(v, 0.0) for v in vids),
                         "h_source_m": H, "critical_valve": crit,
                         "critical_path_loss_m": need[crit][1],
                         "critical_lift_m": need[crit][2],
                         "valves": valves, "edge_flows": flows, "edge_hf": hf}
    if not per_shift:
        return {"per_shift": {}, "critical_shift": None, "max_flow_shift": None}
    crit_shift = max(per_shift, key=lambda s: per_shift[s]["h_source_m"])
    max_q_shift = max(per_shift, key=lambda s: per_shift[s]["q_m3h"])
    return {"per_shift": per_shift, "critical_shift": crit_shift,
            "max_flow_shift": max_q_shift,
            "h_source_max_m": per_shift[crit_shift]["h_source_m"],
            "q_max_m3h": per_shift[max_q_shift]["q_m3h"]}


# ---------------------------------------------------------------------------
# 4. Manifold march and telescoping
# ---------------------------------------------------------------------------

def manifold_march(branches: list[list[tuple[float, float]]], sizes: list[list[int]],
                   candidates: list[K.PipeOption], slopes_pct: list[float],
                   nu: float = K.NU_20C, _cache: dict | None = None,
                   inlet_outlet: bool = False) -> dict:
    """
    Outlet-by-outlet pressure along a manifold, relative to its inlet.

    ``branches``  one list per direction leaving the inlet (one for an
                  end-fed manifold, two for a mid-fed one) of
                  (distance from inlet in m, outlet flow in m3/h), ascending.
    ``sizes``     for each branch, the catalogue index of each segment;
                  segment k runs from outlet k-1 (or the inlet) to outlet k.
    ``slopes_pct`` ground slope along each branch in the direction of flow,
                  positive uphill.
    """
    out_branches = []
    all_p = [0.0] if inlet_outlet else []
    v_max = 0.0
    friction = 0.0
    for bi, br in enumerate(branches):
        q_rem = sum(q for _, q in br)
        pos = 0.0
        p = 0.0
        prof = []
        segs = []
        for k, (s, q_out) in enumerate(br):
            L = max(0.0, s - pos)
            opt = candidates[sizes[bi][k]]
            key = (bi, k, sizes[bi][k])
            r = _cache.get(key) if _cache is not None else None
            if r is None:
                r = K.head_loss_darcy(q_rem, opt.internal_mm, max(L, 1e-9), nu,
                                      opt.roughness_mm) if L > 0 else {
                    "hf_m": 0.0, "velocity_ms": K.velocity(q_rem, opt.internal_mm)}
                if _cache is not None:
                    _cache[key] = r
            dz = slopes_pct[bi] / 100.0 * L
            p = p - r["hf_m"] - dz
            friction += r["hf_m"]
            v_max = max(v_max, r["velocity_ms"])
            segs.append({"from_m": pos, "to_m": s, "length_m": L, "q_m3h": q_rem,
                         "index": sizes[bi][k], "velocity_ms": r["velocity_ms"],
                         "hf_m": r["hf_m"]})
            prof.append({"distance_m": s, "p_rel_m": p, "q_out_m3h": q_out})
            all_p.append(p)
            q_rem -= q_out
            pos = s
        out_branches.append({"segments": segs, "profile": prof})
    p_max = max(all_p) if all_p else 0.0
    p_min = min(all_p) if all_p else 0.0
    last = out_branches[0]["profile"][-1]["p_rel_m"] if out_branches and out_branches[0]["profile"] else 0.0
    return {"branches": out_branches, "spread_m": p_max - p_min,
            "inlet_minus_min_m": 0.0 - p_min, "p_min_rel_m": p_min,
            "p_max_rel_m": p_max, "max_velocity_ms": v_max,
            "friction_m": friction, "total_dh_m": -last}


def _polish(branches, sizes, res, cands, evaluate, allowable, v_max, max_sizes):
    """
    Local search after the size count has been cut to ``max_sizes``.

    Merging sizes can push a design that met the allowance back over it —
    on a falling manifold, merging UP removes friction the design was using
    to cancel the elevation gain. This pass moves single segments up or down
    by one size, keeping diameters non-increasing downstream, velocities
    under the limit and the size count within the cap, and takes the move
    that most reduces the spread (then the cost) until the allowance is met
    or no move helps.
    """
    def distinct(sz):
        return sorted({i for idx in sz for i in idx})

    for _ in range(400):
        if res["spread_m"] <= allowable + 1e-9:
            break
        used = distinct(sizes)
        free = len(used) < max_sizes
        best = None
        base_cost = _cost(branches, sizes, cands)
        for bi, idx in enumerate(sizes):
            for k in range(len(idx)):
                cur = idx[k]
                ups = [i for i in used if i > cur][:1]
                downs = [i for i in used if i < cur][-1:]
                if free:
                    ups = sorted(set(ups + ([cur + 1] if cur + 1 < len(cands) else [])))
                    downs = sorted(set(downs + ([cur - 1] if cur > 0 else [])))
                for new in ups + downs:
                    trial = [list(x) for x in sizes]
                    if new > cur:
                        for j in range(0, k + 1):
                            trial[bi][j] = max(trial[bi][j], new)
                    else:
                        for j in range(k, len(trial[bi])):
                            trial[bi][j] = min(trial[bi][j], new)
                    if len(distinct(trial)) > max_sizes:
                        continue
                    r = evaluate(trial)
                    if r["max_velocity_ms"] > v_max + 1e-9:
                        continue
                    gain = res["spread_m"] - r["spread_m"]
                    if gain <= 1e-9:
                        continue
                    dc = _cost(branches, trial, cands) - base_cost
                    key = (gain / dc) if dc > 1e-9 else 1e9 + gain
                    if best is None or key > best[0]:
                        best = (key, trial, r)
        if best is None:
            break
        sizes, res = best[1], best[2]
    return sizes, res


def _metric(res) -> float:
    depth = sum(-min((pt["p_rel_m"] for pt in br["profile"]), default=0.0)
                for br in res["branches"])
    return res["spread_m"] + 0.05 * depth


def _cost(branches, sizes, candidates):
    c = 0.0
    for bi, br in enumerate(branches):
        pos = 0.0
        for k, (s, _) in enumerate(br):
            c += max(0.0, s - pos) * candidates[sizes[bi][k]].price_egp_per_m
            pos = s
    return c


def telescoped_manifold(branches: list[list[tuple[float, float]]],
                        candidates: list[K.PipeOption], allowable_spread_m: float,
                        v_max_ms: float = 2.0, slopes_pct: list[float] | None = None,
                        nu: float = K.NU_20C, max_sizes: int = 3,
                        inlet_outlet: bool = False) -> dict:
    """
    Least-cost telescoped manifold under a head-spread limit.

    1. Every segment starts at the smallest bore that keeps its velocity
       under the limit, then diameters are made non-increasing downstream (a
       manifold that widens after narrowing is not built).
    2. While the spread exceeds the allowance, the single upgrade — one
       segment and everything upstream of it to the next size — with the
       greatest spread reduction per pound spent is taken.
    3. If more than ``max_sizes`` diameters are in use, the size with the
       least total length is merged into the next larger one; three sizes is
       the practical limit for fittings stock and for site work.

    On a falling manifold a larger pipe can INCREASE the spread (less friction
    to cancel the elevation gain). Step 2 only accepts upgrades that reduce
    the spread, so it stops there and reports that the limit is unmet rather
    than paying for pipe that makes the design worse.
    """
    if not candidates:
        raise ValueError("Pipe catalogue is empty.")
    cands = sorted(candidates, key=lambda o: (o.internal_mm, o.price_egp_per_m))
    slopes = list(slopes_pct) if slopes_pct is not None else [0.0] * len(branches)
    branches = [sorted(br) for br in branches if br]
    if not branches:
        # A one-row subunit: the row sits on the valve tee and there is no
        # manifold pipe to size.
        return {"branches": [], "spread_m": 0.0, "inlet_minus_min_m": 0.0,
                "p_min_rel_m": 0.0, "p_max_rel_m": 0.0, "max_velocity_ms": 0.0,
                "friction_m": 0.0, "total_dh_m": 0.0, "sizes": [], "runs": [],
                "cost": 0.0, "satisfied": True, "allowable_spread_m": allowable_spread_m,
                "v_max_ms": v_max_ms, "attainable": True, "min_achievable_spread_m": 0.0,
                "n_sizes": 0, "single_size_pipe": None, "single_size_cost": 0.0,
                "single_size_spread_m": 0.0, "length_m": 0.0}

    def min_idx(q):
        for i, o in enumerate(cands):
            if K.velocity(q, o.internal_mm) <= v_max_ms:
                return i
        return len(cands) - 1

    sizes = []
    for br in branches:
        q_rem = sum(q for _, q in br)
        idx = []
        for _, q_out in br:
            idx.append(min_idx(q_rem))
            q_rem -= q_out
        for k in range(len(idx) - 2, -1, -1):
            idx[k] = max(idx[k], idx[k + 1])
        sizes.append(idx)

    cache: dict = {}

    def evaluate(sz):
        return manifold_march(branches, sz, cands, slopes, nu, _cache=cache,
                              inlet_outlet=inlet_outlet)

    res = evaluate(sizes)
    path = [(sizes, res)]
    guard = 0
    while res["spread_m"] > allowable_spread_m + 1e-12 and guard < 2000:
        guard += 1
        best = None
        base_cost = _cost(branches, sizes, cands)
        moves = []
        for bi, idx in enumerate(sizes):
            for k in range(len(idx)):
                if idx[k] < len(cands) - 1:
                    moves.append(((bi,), k))
        if len(sizes) > 1:
            # The same step on every branch at once. A mid-fed manifold is
            # symmetric more often than not, and a one-sided upgrade raises
            # the near-inlet pressure on that side while the other side still
            # sets the minimum — so no single-branch move helps and the search
            # would stall at a failing design with a cheap fix available.
            for k in range(max(len(i) for i in sizes)):
                moves.append((tuple(range(len(sizes))), k))
        for bis, k in moves:
                trial = [list(x) for x in sizes]
                changed = False
                for bi in bis:
                    if k >= len(trial[bi]) or trial[bi][k] >= len(cands) - 1:
                        continue
                    new = trial[bi][k] + 1
                    for j in range(0, k + 1):
                        trial[bi][j] = max(trial[bi][j], new)
                    changed = True
                if not changed:
                    continue
                r = evaluate(trial)
                # Judged on the spread plus a small share of each branch's own
                # depth. The spread alone is flat under a one-branch upgrade of
                # a symmetric mid-fed manifold (the other branch still sets the
                # minimum), so a pure-spread greedy stalls there with the
                # allowance unmet and a cheap solution available.
                gain = _metric(res) - _metric(r)
                if gain <= 1e-9:
                    continue
                dc = max(_cost(branches, trial, cands) - base_cost, 1e-6)
                score = gain / dc
                if best is None or score > best[0]:
                    best = (score, trial, r)
        if best is None:
            break
        sizes, res = best[1], best[2]
        path.append((sizes, res))
        # Diminishing returns: once fifteen upgrades in a row have bought
        # less than 5 mm of spread between them, the remaining gap is
        # elevation, not friction, and more pipe will not close it.
        if len(path) > 15 and path[-16][1]["spread_m"] - res["spread_m"] < 0.005:
            break

    min_seen = min(r["spread_m"] for _, r in path)
    attainable = min_seen <= allowable_spread_m + 1e-12
    if not attainable:
        # No sequence of upgrades meets the allowance — an uphill manifold
        # whose rise alone exceeds it. More pipe cannot fix that; it only buys
        # bore from the top of the catalogue for a design that still fails.
        # Keep the first state whose spread is within one allowance of the
        # best the pipe could do, i.e. hold the FRICTION part to the budget,
        # and report the elevation part as the unmet remainder.
        # A single size is used here: when the design fails anyway, a
        # telescoped answer is only noise for the designer to read around.
        best_single = None
        for i in range(len(cands)):
            sz = [[i] * len(br) for br in branches]
            r = evaluate(sz)
            if r["max_velocity_ms"] > v_max_ms + 1e-9:
                continue
            if r["spread_m"] <= min_seen + allowable_spread_m + 1e-12:
                c = _cost(branches, sz, cands)
                if best_single is None or c < best_single[0]:
                    best_single = (c, sz, r)
        if best_single is not None:
            sizes, res = best_single[1], best_single[2]
        else:
            for sz, r in path:
                if r["spread_m"] <= min_seen + allowable_spread_m + 1e-12:
                    sizes, res = sz, r
                    break
    min_achievable = min_seen

    def distinct(sz):
        return sorted({i for idx in sz for i in idx})

    while len(distinct(sizes)) > max_sizes:
        # Merge one size into a neighbouring size. Up is the obvious choice,
        # but on a falling manifold a larger bore RAISES the spread (less
        # friction left to cancel the elevation gain), so both directions are
        # tried and the merge that keeps the design inside the allowance at
        # the least cost wins.
        used = distinct(sizes)
        options = []
        for pos_i, drop in enumerate(used):
            for to in (used[pos_i + 1] if pos_i + 1 < len(used) else None,
                       used[pos_i - 1] if pos_i > 0 else None):
                if to is None:
                    continue
                trial = [[to if i == drop else i for i in idx] for idx in sizes]
                for idx in trial:                       # keep non-increasing
                    for k in range(len(idx) - 2, -1, -1):
                        idx[k] = max(idx[k], idx[k + 1])
                r = evaluate(trial)
                ok = (r["spread_m"] <= allowable_spread_m + 1e-9
                      and r["max_velocity_ms"] <= v_max_ms + 1e-9)
                options.append((not ok, r["spread_m"] if not ok else 0.0,
                                _cost(branches, trial, cands), trial, r))
        options.sort(key=lambda o: (o[0], o[1], o[2]))
        sizes, res = options[0][3], options[0][4]

    if res["spread_m"] > allowable_spread_m + 1e-9 and attainable:
        sizes, res = _polish(branches, sizes, res, cands, evaluate,
                             allowable_spread_m, v_max_ms, max_sizes)

    runs = []
    for bi, br in enumerate(res["branches"]):
        cur = None
        for seg in br["segments"]:
            if cur and cur["index"] == seg["index"]:
                cur["to_m"] = seg["to_m"]
                cur["length_m"] += seg["length_m"]
                cur["q_out_m3h"] = seg["q_m3h"]
                cur["hf_m"] += seg["hf_m"]
                cur["velocity_max_ms"] = max(cur["velocity_max_ms"], seg["velocity_ms"])
            else:
                if cur:
                    runs.append(cur)
                cur = {"branch": bi + 1, "index": seg["index"],
                       "pipe": _pipe_dict(cands[seg["index"]]),
                       "from_m": seg["from_m"], "to_m": seg["to_m"],
                       "length_m": seg["length_m"], "q_in_m3h": seg["q_m3h"],
                       "q_out_m3h": seg["q_m3h"], "hf_m": seg["hf_m"],
                       "velocity_max_ms": seg["velocity_ms"]}
        if cur:
            runs.append(cur)
    cost = _cost(branches, sizes, cands)
    single = [[max(distinct(sizes))] * len(br) for br in branches]
    single_res = evaluate(single)
    return {
        **res, "sizes": sizes, "runs": runs, "cost": cost,
        "satisfied": res["spread_m"] <= allowable_spread_m + 1e-9
        and res["max_velocity_ms"] <= v_max_ms + 1e-9,
        "allowable_spread_m": allowable_spread_m, "v_max_ms": v_max_ms,
        "attainable": attainable, "min_achievable_spread_m": min_achievable,
        "n_sizes": len(distinct(sizes)),
        "single_size_pipe": _pipe_dict(cands[max(distinct(sizes))]),
        "single_size_cost": _cost(branches, single, cands),
        "single_size_spread_m": single_res["spread_m"],
        "length_m": sum(br[-1][0] for br in branches),
    }


def manifold_branches(feeds: list, outlets: list[dict], inlet_index: int):
    """
    Outlet positions along a manifold polyline, split at the inlet.

    Returns the branch lists for :func:`telescoped_manifold`: distances are
    measured ALONG the polyline from the inlet, so a manifold that bends at a
    boundary corner is marched over its real length.

    The row AT the valve is fed straight off the valve tee: its flow never
    passes through manifold pipe, so it is left out of the branches (it must
    not size a zero-length segment — it once put a 110 mm stub on a 90 mm
    manifold). Its pressure is the inlet pressure; pass ``inlet_outlet=True``
    to the march so the spread still counts it.
    """
    cum = [0.0]
    for a, b in zip(feeds, feeds[1:]):
        cum.append(cum[-1] + _dist(a, b))
    s0 = cum[inlet_index]
    fwd = [(cum[i] - s0, outlets[i]["q_m3h"]) for i in range(inlet_index + 1, len(feeds))]
    back = [(s0 - cum[i], outlets[i]["q_m3h"]) for i in range(inlet_index - 1, -1, -1)]
    fwd = [(max(s, 1e-3), q) for s, q in fwd]
    back = [(max(s, 1e-3), q) for s, q in back]
    return [b for b in (fwd, back) if b]


# ---------------------------------------------------------------------------
# 5. Maximum lateral run for a head-spread allowance
# ---------------------------------------------------------------------------

def max_lateral_run(q_emitter_lph: float, emitter_spacing_m: float, d_mm: float,
                    le_m: float, slope_pct: float, allowable_spread_m: float,
                    nu: float = K.NU_20C, roughness_mm: float = 0.007,
                    step_m: float = 1.0, limit_m: float = 600.0) -> dict:
    """
    The longest lateral that stays inside the allowable head spread and the
    velocity limit, scanned in ``step_m`` increments.

    A scan, not a bisection: on a falling lateral the spread is not monotone
    in length — it can fall as the elevation gain starts to cancel friction,
    then rise again — and a bisection would happily return a length beyond a
    failing stretch. The answer is the last length before the FIRST failure.
    """
    last_ok = 0.0
    L = step_m
    reason = "limit reached"
    while L <= limit_m + 1e-9:
        n = max(1, int(round(L / emitter_spacing_m)))
        q = n * q_emitter_lph / 1000.0
        r = K.lateral_head_loss(q, d_mm, L, n, le_m, slope_pct, nu, roughness_mm)
        if r["spread_m"] > allowable_spread_m or not r["velocity_ok"]:
            reason = ("head spread" if r["spread_m"] > allowable_spread_m
                      else "velocity")
            break
        last_ok = L
        L += step_m
    return {"max_run_m": last_ok, "governed_by": reason}
