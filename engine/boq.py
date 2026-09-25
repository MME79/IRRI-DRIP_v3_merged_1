"""
Bill of quantities taken from the designed network. UI-free.

Version 1 priced the manifold as ``manifold length x number of shifts`` — the
one-manifold-per-shift assumption the Wadi El-Natrun layout test proved wrong:
the number of manifolds is set by the field, the number of shifts by the
water. Here every quantity is measured from the network that was actually
laid out and sized:

* dripline      the clipped row lengths of every subunit, not area / spacing
* manifolds     every telescoped section of every subunit, by size
* mainline      every sized pipe of the source-to-valve tree, by size
* valves        one per subunit, sized to the manifold inlet; a pressure
                regulator wherever the hydraulic solution shows a surplus
* fittings      one start connector and one end closure per lateral run

Quantities are measured; RATES are placeholders (data/unit_rates.json) and
the page says so.
"""

from __future__ import annotations

import math

__all__ = ["auto_boq", "boq_totals", "CATEGORY_LIFE"]

CATEGORY_LIFE = {
    "Dripline": "Dripline and emitters",
    "Manifolds": "Manifolds",
    "Mainline & submains": "Mainline and submains",
    "Valves & fittings": "Valves and fittings",
    "Head control": "Head control",
    "Pump set": "Pump set",
    "Civil & installation": "Civil works and installation",
}


def _item(cat, name, unit, qty, rate):
    return {"Category": cat, "Item": name, "Unit": unit,
            "Quantity": round(float(qty), 2), "Rate (EGP)": round(float(rate), 2),
            "Amount (EGP)": round(float(qty) * float(rate), 0)}


def auto_boq(subunits: list[dict], manifold_designs: dict, tree_sizing: dict,
             lateral_pipe: dict, emitter: dict, pump_kw: float, q_duty_m3h: float,
             n_regulators: int, area_ha: float, rates: dict,
             n_mainline_ends: int = 1) -> list[dict]:
    r = rates
    items: list[dict] = []
    waste_d = 1.0 + r.get("waste_pct_dripline", 0.0) / 100.0
    waste_p = 1.0 + r.get("waste_pct_pipe", 0.0) / 100.0

    # --- dripline ------------------------------------------------------------
    drip_m = sum(s["dripline_m"] for s in subunits) * waste_d
    se = max(float(emitter.get("se", 0.5)), 1e-6)
    drip_rate = float(lateral_pipe.get("price_egp_per_m", 0.0)) + float(
        emitter.get("price_egp", 0.0)) / se
    items.append(_item("Dripline",
                       f"Dripline {lateral_pipe.get('nominal_mm', 0):.0f} mm, "
                       f"{emitter.get('name', 'emitter')} at {se:.2f} m "
                       f"(+{r.get('waste_pct_dripline', 0):.0f} % waste)",
                       "m", drip_m, drip_rate))
    n_lat = sum(int(s["n_laterals"]) for s in subunits)
    items.append(_item("Dripline", "Start connector with grommet", "each",
                       n_lat, r.get("start_connector_each", 0.0)))
    items.append(_item("Dripline", "End closure", "each",
                       n_lat, r.get("end_closure_each", 0.0)))

    # --- manifolds, by size -------------------------------------------------
    by_size: dict[tuple, dict] = {}
    for sid, d in manifold_designs.items():
        for run in d.get("runs", []):
            p = run["pipe"]
            key = (p["nominal_mm"], p["material"], p["pn_bar"])
            e = by_size.setdefault(key, {"m": 0.0, "price": p.get("price", 0.0)})
            e["m"] += run["length_m"]
    for (dn, mat, pn), e in sorted(by_size.items()):
        items.append(_item("Manifolds", f"Manifold pipe {dn:.0f} mm {mat} PN{pn:g}",
                           "m", e["m"] * waste_p, e["price"]))
    manifold_total = sum(e["m"] for e in by_size.values())

    # --- mainline and submains, by size ----------------------------------------
    by_size = {}
    for eid, s in tree_sizing.items():
        p = s["pipe"]
        key = (p["nominal_mm"], p["material"], p["pn_bar"])
        e = by_size.setdefault(key, {"m": 0.0, "price": p.get("price", 0.0)})
        e["m"] += s["length_m"]
    for (dn, mat, pn), e in sorted(by_size.items(), reverse=True):
        items.append(_item("Mainline & submains",
                           f"Mainline / submain pipe {dn:.0f} mm {mat} PN{pn:g}",
                           "m", e["m"] * waste_p, e["price"]))
    main_total = sum(e["m"] for e in by_size.values())
    pipe_cost = sum(i["Amount (EGP)"] for i in items
                    if i["Category"] in ("Manifolds", "Mainline & submains"))

    # --- valves and fittings ---------------------------------------------------
    dn_valves = [max((run["pipe"]["nominal_mm"] for run in d.get("runs", [])),
                     default=50.0) for d in manifold_designs.values()]
    if dn_valves:
        mean_dn = sum(dn_valves) / len(dn_valves)
        items.append(_item("Valves & fittings",
                           f"Subunit control valve (mean DN {mean_dn:.0f} mm)",
                           "each", len(dn_valves),
                           r.get("subunit_valve_per_mm_dn", 0.0) * mean_dn))
        if n_regulators:
            items.append(_item("Valves & fittings",
                               f"Pressure regulator (mean DN {mean_dn:.0f} mm)",
                               "each", n_regulators,
                               r.get("pressure_regulator_per_mm_dn", 0.0) * mean_dn))
    n_air = len(subunits) + max(1, math.ceil(main_total / 400.0)) if subunits else 0
    items.append(_item("Valves & fittings",
                       "Air / vacuum release valve (one per manifold, one per "
                       "400 m of mainline)", "each", n_air,
                       r.get("air_valve_each", 0.0)))
    n_flush = sum(len(d.get("branches", [])) or 1 for d in manifold_designs.values()) \
        + int(n_mainline_ends)
    items.append(_item("Valves & fittings",
                       "Flushing valve (manifold and mainline ends)", "each",
                       n_flush, r.get("flushing_valve_each", 0.0)))
    items.append(_item("Valves & fittings",
                       f"Fittings allowance ({r.get('fittings_pct_of_pipe', 0):.0f} % "
                       "of pipe cost)", "lump", 1,
                       pipe_cost * r.get("fittings_pct_of_pipe", 0.0) / 100.0))

    # --- head control and pump ----------------------------------------------
    items.append(_item("Head control",
                       f"Filtration unit for {q_duty_m3h:.1f} m3/h", "set", 1,
                       r.get("filtration_base", 0.0)
                       + r.get("filtration_per_m3h", 0.0) * q_duty_m3h))
    items.append(_item("Head control", "Fertigation unit", "set", 1,
                       r.get("fertigation_unit", 0.0)))
    items.append(_item("Head control", "Water meter and pressure gauges", "set", 1,
                       r.get("meter_and_gauges", 0.0)))
    items.append(_item("Pump set", f"Pump and motor, {pump_kw:.1f} kW", "set", 1,
                       r.get("pump_per_kw", 0.0) * pump_kw))

    # --- civil and installation ---------------------------------------------
    items.append(_item("Civil & installation",
                       "Trenching and backfill for buried pipe (manifolds, "
                       "submains, mainline)", "m", manifold_total + main_total,
                       r.get("trenching_per_m", 0.0)))
    items.append(_item("Civil & installation", "Installation and commissioning",
                       "ha", area_ha, r.get("installation_per_ha", 0.0)))
    return items


def boq_totals(items: list[dict]) -> dict:
    cats: dict[str, float] = {}
    for i in items:
        cats[i["Category"]] = cats.get(i["Category"], 0.0) + float(i["Amount (EGP)"])
    return {"by_category": cats, "subtotal": sum(cats.values())}


# ---------------------------------------------------------------------------
# Pipe prices edited in the program (v2.0.1)
# ---------------------------------------------------------------------------
#
# The telescoped manifold sizing chooses between pipe sizes on price, so the
# price the BOQ uses and the price the sizing used must be the same number.
# Up to v2.0.0 the only way to change a pipe price was to edit
# data/pipes.json, which a user of the web version cannot reach. Prices are
# now overridden per project (S["pipe_prices"]) and applied to the catalogue
# BEFORE any page sees it, so sizing and cost always agree.

def pipe_key(p: dict) -> str:
    """A stable, readable identifier for a catalogue pipe, e.g. 'PE 32 PN6'."""
    return f"{p['material']} {p['nominal_mm']:g} PN{p['pn_bar']:g}"


def apply_pipe_prices(catalogue: dict, overrides: dict | None) -> dict:
    """A copy of the pipe catalogue with the project's prices applied."""
    import copy
    cat = copy.deepcopy(catalogue)
    for p in cat.get("pipes", []):
        k = pipe_key(p)
        if overrides and k in overrides and overrides[k] is not None:
            p["price_egp_per_m"] = float(overrides[k])
    return cat
