"""
Pump curves, the drip system curve, and the operating point.

UI-free.

The drip system curve is not a parabola
---------------------------------------
A sprinkler program (OpenIrri included) draws the system curve as
H = H_static + K Q^2. That is right for pipes and nearly right for sprinkler
nozzles (q ~ H^0.5 gives H ~ q^2). It is wrong for drip. The dominant term in
a drip system head is the emitter operating head, and an emitter obeys
q = k H^x with x anywhere from about 0.5 (turbulent orifice) down to 0.0
(pressure compensating). If the pump pushes more flow than designed, the
emitters must see a higher head by (Q/Qd)^(1/x):

    H_sys(Q) = H_static + h_emit (Q/Qd)^(1/x) + H_pipe (Q/Qd)^m + H_other (Q/Qd)^2

For x = 0.5 the emitter term is quadratic like a nozzle; for x = 0.1 it is a
tenth power and the curve is nearly vertical at the design flow. A pump
matched on a parabola to a pressure-compensated system will be selected at
the wrong point. This module draws the curve the emitters actually impose.
"""

from __future__ import annotations

import math

__all__ = ["PumpCurve", "fit_quadratic", "generic_catalogue", "system_curve",
           "operating_point", "match_pumps", "diesel_fuel_lph",
           "solar_array_kwp", "POR_LOW", "POR_HIGH"]

# Preferred operating region, fraction of best-efficiency flow. ANSI/HI 9.6.3
# gives 70-120 % of BEP flow as the preferred region for most centrifugal pumps.
POR_LOW = 0.70
POR_HIGH = 1.20


class PumpCurve:
    """
    H(Q) = a + b Q + c Q^2  (m, Q in m3/h)
    eta(Q) = eta_bep * (2 r - r^2), r = Q / Q_bep   (classic parabola, 0 at
    shut-off and at twice BEP flow — a shape approximation, not a measurement)
    """

    def __init__(self, name: str, a: float, b: float, c: float,
                 q_bep: float, eta_bep: float, q_max: float | None = None,
                 source: str = "", note: str = ""):
        self.name = name
        self.a, self.b, self.c = float(a), float(b), float(c)
        self.q_bep = float(q_bep)
        self.eta_bep = float(eta_bep)
        self.source = source
        self.note = note
        if q_max is None:
            q_max = self._zero_head_flow()
        self.q_max = float(q_max)

    def _zero_head_flow(self) -> float:
        a, b, c = self.a, self.b, self.c
        if abs(c) < 1e-12:
            return -a / b if b < 0 else 10.0 * max(self.q_bep, 1.0)
        disc = b * b - 4 * a * c
        if disc < 0:
            return 2.0 * self.q_bep
        r1 = (-b + math.sqrt(disc)) / (2 * c)
        r2 = (-b - math.sqrt(disc)) / (2 * c)
        pos = [r for r in (r1, r2) if r > 0]
        return max(pos) if pos else 2.0 * self.q_bep

    def head(self, q: float) -> float:
        return self.a + self.b * q + self.c * q * q

    def efficiency(self, q: float) -> float:
        if self.q_bep <= 0:
            return 0.0
        r = q / self.q_bep
        return max(0.0, self.eta_bep * (2.0 * r - r * r))

    def to_dict(self) -> dict:
        return {"name": self.name, "a": self.a, "b": self.b, "c": self.c,
                "q_bep": self.q_bep, "eta_bep": self.eta_bep,
                "q_max": self.q_max, "source": self.source, "note": self.note}

    @classmethod
    def from_dict(cls, d: dict) -> "PumpCurve":
        return cls(d["name"], d["a"], d["b"], d["c"], d["q_bep"], d["eta_bep"],
                   d.get("q_max"), d.get("source", ""), d.get("note", ""))


def fit_quadratic(points: list[tuple[float, float]]) -> tuple[float, float, float]:
    """
    H = a + b Q + c Q^2 through three manufacturer points (least squares if
    more are given). Raises if the points cannot define a falling curve.
    """
    pts = [(float(q), float(h)) for q, h in points]
    if len(pts) < 3:
        raise ValueError("Three or more (Q, H) points are needed.")
    if len({q for q, _ in pts}) < 3:
        raise ValueError("The points need three different flows.")
    # Normal equations for a 3-parameter polynomial.
    s = [sum(q ** k for q, _ in pts) for k in range(5)]
    t = [sum(h * q ** k for q, h in pts) for k in range(3)]
    M = [[s[0], s[1], s[2]], [s[1], s[2], s[3]], [s[2], s[3], s[4]]]
    a, b, c = _solve3(M, t)
    if c >= 0 and b >= 0:
        raise ValueError("These points do not describe a pump curve: head does "
                         "not fall with flow.")
    return a, b, c


def _solve3(M, y):
    import copy
    A = copy.deepcopy(M)
    v = list(y)
    n = 3
    for i in range(n):
        p = max(range(i, n), key=lambda r: abs(A[r][i]))
        if abs(A[p][i]) < 1e-15:
            raise ValueError("Degenerate points.")
        A[i], A[p] = A[p], A[i]
        v[i], v[p] = v[p], v[i]
        for r in range(i + 1, n):
            f = A[r][i] / A[i][i]
            for c in range(i, n):
                A[r][c] -= f * A[i][c]
            v[r] -= f * v[i]
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        x[i] = (v[i] - sum(A[i][c] * x[c] for c in range(i + 1, n))) / A[i][i]
    return x


def generic_catalogue(entries: list[dict]) -> list[PumpCurve]:
    """
    Generic type curves from data/pumps.json.

    Each entry gives the best-efficiency point and the shut-off-to-BEP head
    ratio; the curve is H = H0 - (H0 - Hbep)(Q/Qbep)^2. These are SHAPES that
    span the duty range, not products: a pump is bought from a manufacturer's
    published curve, which the Custom option takes directly.
    """
    out = []
    for e in entries:
        h0 = e["h_bep_m"] * e.get("shutoff_ratio", 1.25)
        c = -(h0 - e["h_bep_m"]) / (e["q_bep_m3h"] ** 2)
        out.append(PumpCurve(e["name"], h0, 0.0, c, e["q_bep_m3h"],
                             e.get("eta_bep", 0.72), source="generic type curve",
                             note=e.get("note", "")))
    return out


def system_curve(q_design: float, h_static: float, h_emitter: float,
                 h_pipe: float, h_other_quadratic: float, emitter_x: float,
                 pipe_exponent: float = 1.85):
    """
    Returns H_sys(Q) as a function, per the module docstring.

    ``h_other_quadratic`` collects terms that scale with Q^2: filters, the
    injector, valves and minor losses. ``h_pipe`` scales with the friction
    exponent of the pipes (about 1.75-2.0 for Darcy-Weisbach in plastic pipe).
    The emitter exponent is floored at 0.05: a perfectly compensating emitter
    would make the curve vertical, which no real emitter achieves and which
    no root-finder can intersect.
    """
    x = max(0.05, float(emitter_x))
    qd = max(q_design, 1e-9)

    def H(q: float) -> float:
        r = max(q, 0.0) / qd
        return (h_static + h_emitter * r ** (1.0 / x) + h_pipe * r ** pipe_exponent
                + h_other_quadratic * r * r)
    return H


def operating_point(pump: PumpCurve, sys_h, q_hi: float | None = None) -> dict | None:
    """Intersection of the pump and system curves by bisection."""
    lo, hi = 0.0, q_hi or pump.q_max
    f_lo = pump.head(lo) - sys_h(lo)
    f_hi = pump.head(hi) - sys_h(hi)
    if f_lo < 0:
        return None                 # pump cannot overcome static + emitter head
    if f_hi > 0:
        return None                 # no intersection inside the curve's range
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        if pump.head(mid) - sys_h(mid) > 0:
            lo = mid
        else:
            hi = mid
    q = 0.5 * (lo + hi)
    return {"q_m3h": q, "h_m": pump.head(q), "eta": pump.efficiency(q),
            "bep_ratio": q / pump.q_bep if pump.q_bep > 0 else 0.0}


DUTY_TOL = 0.005


def match_pumps(pumps: list[PumpCurve], q_req: float, h_req: float, sys_h) -> list[dict]:
    """
    Rank candidate pumps for a duty.

    A pump qualifies when its operating point on the drip system curve
    delivers at least the required flow (and therefore, on that curve, at
    least the required head). Ranked by efficiency at the operating point,
    with a penalty outside the preferred operating region, then by the flow
    surplus (a pump far larger than needed wastes energy through the
    regulating valves).
    """
    out = []
    for p in pumps:
        op = operating_point(p, sys_h)
        if op is None:
            out.append({"pump": p, "op": None, "qualifies": False,
                        "reason": "no intersection with the system curve"})
            continue
        # Both the flow AND the head at the operating point must reach the duty
        # (0.5 % allowance for the bisection and rounding). v2.0.0 accepted any
        # point within 2 % of the flow; on a compensating-emitter system curve,
        # which is nearly vertical, that let a pump 1.8 m (3.6 %) short of the
        # required head through as "delivers duty" — below the emitters'
        # regulation range.
        qualifies = (op["q_m3h"] >= q_req * (1 - DUTY_TOL)
                     and op["h_m"] >= h_req * (1 - DUTY_TOL))
        in_por = POR_LOW <= op["bep_ratio"] <= POR_HIGH
        score = op["eta"] - (0.0 if in_por else 0.10) - 0.05 * max(
            0.0, op["q_m3h"] / max(q_req, 1e-9) - 1.10)
        out.append({"pump": p, "op": op, "qualifies": qualifies,
                    "in_por": in_por, "score": score,
                    "reason": "" if qualifies else
                    f"delivers {op['q_m3h']:.1f} m3/h at {op['h_m']:.1f} m against "
                    f"{q_req:.1f} m3/h at {h_req:.1f} m required"})
    out.sort(key=lambda r: (not r["qualifies"], -(r.get("score") or -9)))
    return out


def diesel_fuel_lph(brake_kw: float, specific_fuel_l_per_kwh: float = 0.25) -> float:
    """Diesel consumption at the shaft duty, L/h. The specific consumption is
    an input: 0.22-0.30 L/kWh covers most irrigation engines at part load."""
    return max(0.0, brake_kw) * specific_fuel_l_per_kwh


def solar_array_kwp(daily_kwh: float, peak_sun_hours: float,
                    performance_ratio: float = 0.70) -> float:
    """PV array needed to supply the daily pumping energy directly."""
    if peak_sun_hours <= 0 or performance_ratio <= 0:
        return 0.0
    return daily_kwh / (peak_sun_hours * performance_ratio)
