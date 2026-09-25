"""
Economic analysis of the designed system. UI-free.

Capital is annualised component by component, because the components of a
drip system do not share a life: a dripline in Egyptian conditions lasts a
few seasons, a PVC mainline decades. Annualising the whole capital cost over
one "project life" — what a single CRF on the total does — understates the
yearly cost of the dripline and overstates that of the buried pipe.

Every rate and life here is an INPUT. The defaults on the Cost page are
placeholders for the designer to replace, not published figures.
"""

from __future__ import annotations

__all__ = ["crf", "annualised_cost", "cash_flows", "npv", "irr", "payback_year"]


def crf(rate: float, years: float) -> float:
    """Capital recovery factor i(1+i)^n / ((1+i)^n - 1); 1/n at zero rate."""
    n = max(float(years), 1e-9)
    i = float(rate)
    if abs(i) < 1e-12:
        return 1.0 / n
    g = (1.0 + i) ** n
    return i * g / (g - 1.0)


def annualised_cost(components: list[dict], rate: float) -> dict:
    """
    components: [{"name", "capital", "life_years"}]. Returns the annual
    equivalent of each and the total.
    """
    rows = []
    for c in components:
        cap = float(c.get("capital", 0.0))
        life = float(c.get("life_years", 1.0))
        a = cap * crf(rate, life)
        rows.append({**c, "crf": crf(rate, life), "annual": a})
    return {"rows": rows, "total_annual": sum(r["annual"] for r in rows),
            "total_capital": sum(float(c.get("capital", 0.0)) for c in components)}


def cash_flows(components: list[dict], horizon_years: int, annual_om: float,
               annual_energy: float, annual_benefit: float) -> list[float]:
    """
    Year-0 capital, then yearly net benefit minus replacements as each
    component reaches the end of its life. Salvage value is ignored, which
    is conservative.
    """
    flows = [0.0] * (int(horizon_years) + 1)
    for c in components:
        cap = float(c.get("capital", 0.0))
        life = max(1, int(round(float(c.get("life_years", 1.0)))))
        flows[0] -= cap
        y = life
        while y <= horizon_years - 1:
            flows[y] -= cap
            y += life
    for y in range(1, int(horizon_years) + 1):
        flows[y] += annual_benefit - annual_om - annual_energy
    return flows


def npv(rate: float, flows: list[float]) -> float:
    return sum(f / (1.0 + rate) ** t for t, f in enumerate(flows))


def irr(flows: list[float]) -> float | None:
    """Internal rate of return by bisection; None if it does not change sign."""
    lo, hi = -0.99, 5.0
    f_lo, f_hi = npv(lo, flows), npv(hi, flows)
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        f_mid = npv(mid, flows)
        if f_lo * f_mid <= 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return 0.5 * (lo + hi)


def payback_year(flows: list[float]) -> float | None:
    """Simple (undiscounted) payback, interpolated within the year."""
    cum = flows[0]
    for t in range(1, len(flows)):
        prev = cum
        cum += flows[t]
        if cum >= 0 > prev:
            return (t - 1) + (-prev / flows[t] if flows[t] else 0.0)
    return None
