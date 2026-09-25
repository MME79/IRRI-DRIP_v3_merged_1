"""
Cost Estimation — OpenIrri's four tabs: Unit Costs, Auto BOQ, Cost Summary,
Economic Analysis.

Quantities are MEASURED from the designed network (engine/boq.py); rates are
placeholders the user replaces. The economic analysis annualises each
component over its own life, because a dripline and a PVC mainline do not
share one.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from engine import boq as BQ
from engine import economics as E
from modules import plots as PL
from modules.common import (page_header, sub_header, section, cards, banner, note,
                            caption, save, stage_guard, require, goto, dev_panel, context_strip,
                            stable_editor, reset_editor)

FEDDAN_M2 = 4200.83


# Plain-language meaning of each unit rate, shown beside the code name.
RATE_MEANING = {
    "start_connector_each": "Start connector joining a dripline to the manifold (EGP each)",
    "end_closure_each": "End plug closing each dripline (EGP each)",
    "subunit_valve_per_mm_dn": "Subunit control valve, EGP per mm of valve diameter",
    "pressure_regulator_per_mm_dn": "Pressure regulator, EGP per mm of diameter",
    "air_valve_each": "Air / vacuum release valve (EGP each)",
    "flushing_valve_each": "Flushing valve at a manifold end (EGP each)",
    "filtration_base": "Filter station, fixed part (EGP)",
    "filtration_per_m3h": "Filter station, EGP per m3/h of flow",
    "fertigation_unit": "Fertiliser injection unit (EGP)",
    "meter_and_gauges": "Water meter and pressure gauges (EGP)",
    "pump_per_kw": "Pump set, EGP per kW of motor",
    "trenching_per_m": "Trenching and backfill for buried pipe (EGP per m)",
    "installation_per_ha": "Installation labour (EGP per hectare)",
    "fittings_pct_of_pipe": "Fittings (elbows, tees...) as % of pipe cost",
    "waste_pct_dripline": "Extra dripline for cutting and waste (%)",
    "waste_pct_pipe": "Extra pipe for cutting and waste (%)",
}


def show(ctx):
    S = ctx["S"]
    page_header("Cost Estimation",
                "Bill of quantities measured from the designed network, capital cost, and "
                "an economic analysis with component lives.")
    if not require(S, ("setup", "emitter", "operation", "network", "manifold", "pump")):
        return
    context_strip(S)
    setup, em, op, man, pump = S["setup"], S["emitter"], S["operation"], S["manifold"], S["pump"]
    prev = S.get("cost", {})
    banner("warn", "Unit rates are <b>placeholders, not quotations</b>. Replace every rate "
                   "with a current supplier price before this table is used for budgeting "
                   "or tendering.")

    tabs = st.tabs(["💰 Unit Costs", "📊 Auto BOQ", "📈 Cost Summary", "💵 Economic Analysis"])

    # ------------------------------------------------------------ rates ----
    with tabs[0]:
        sub_header("Unit Costs")
        base_rates = dict(ctx["rates"]["rates"])
        base_rates.update(prev.get("rates") or {})
        ed = stable_editor("cost_rates", lambda: pd.DataFrame(
            [{"Rate": k, "What it is": RATE_MEANING.get(k, ""), "Value": float(v)}
             for k, v in base_rates.items()]),
            hide_index=True, width="stretch",
            column_config={"Rate": st.column_config.TextColumn(disabled=True),
                           "What it is": st.column_config.TextColumn(disabled=True)})
        rates = {r["Rate"]: float(r["Value"]) for r in ed.to_dict("records")}
        c1, c2 = st.columns(2)
        with c1:
            drip_price = st.number_input("Dripline pipe price (EGP/m)", 0.0, 1000.0,
                                         float(prev.get("drip_price", em["lateral_pipe"].get(
                                             "price_egp_per_m", 4.5))), 0.1)
        with c2:
            em_price = st.number_input("Emitter price (EGP each)", 0.0, 100.0,
                                       float(prev.get("em_price", em.get("price_egp", 1.0))), 0.05)
        _pipe_price_editor(S, ctx)
        if st.button("↺ Restore catalogue rates", key="cost_reset"):
            reset_editor("cost_rates", pd.DataFrame(
                [{"Rate": k, "What it is": RATE_MEANING.get(k, ""), "Value": float(v)}
                 for k, v in ctx["rates"]["rates"].items()]))
            st.rerun()

    # -------------------------------------------------------------- BOQ ----
    tree_sizing = man.get("tree_sizing", {})
    items = BQ.auto_boq(
        op["subunits"], man.get("designs", {}), tree_sizing,
        {"nominal_mm": em["lateral_pipe"]["nominal_mm"], "price_egp_per_m": drip_price},
        {"se": em["se"], "price_egp": em_price, "name": em["name"]},
        pump["power"]["motor_rating_kw"], pump["q_duty"], len(man.get("regulators", [])),
        setup["area_ha"], rates)
    with tabs[1]:
        sub_header("Auto BOQ")
        with st.expander("📋 Design Data Status", expanded=False):
            st.markdown(
                f"- Subunits: **{op['n_subunits']}**, laterals "
                f"**{sum(s['n_laterals'] for s in op['subunits']):,}**\n"
                f"- Telescoped manifolds: **{len(man.get('designs', {}))}**\n"
                f"- Sized mainline / submain pipes: **{len(tree_sizing)}**\n"
                f"- Pump: **{pump['power']['motor_rating_kw']:.1f} kW**, "
                f"regulators **{len(man.get('regulators', []))}**")
        sig = "|".join(f"{i['Item']}:{i['Quantity']}:{i['Rate (EGP)']}" for i in items)
        import zlib
        ed_boq = stable_editor(f"boq_{zlib.crc32(sig.encode())}",
                               lambda: pd.DataFrame(items), hide_index=True,
                               width="stretch", num_rows="dynamic",
                               column_config={"Amount (EGP)": st.column_config.NumberColumn(
                                   disabled=True, format="%.0f")})
        ed_boq = ed_boq.fillna({"Quantity": 0.0, "Rate (EGP)": 0.0, "Category": "Other",
                                "Item": "", "Unit": ""})
        ed_boq["Amount (EGP)"] = (ed_boq["Quantity"].astype(float)
                                  * ed_boq["Rate (EGP)"].astype(float)).round(0)
        caption("Quantities are measured from the network: dripline from the clipped rows, "
                "manifolds by telescoped section, mainline by sized pipe. Edit any cell or "
                "add rows; the totals follow.")
        with st.expander("📐 Pipe Quantity Calculation Details", expanded=False):
            st.markdown(
                f"- Dripline: Σ clipped row length × laterals per row = "
                f"{sum(s['dripline_m'] for s in op['subunits']):,.0f} m, "
                f"+{rates.get('waste_pct_dripline', 0):.0f} % waste\n"
                "- Manifolds: every telescoped run of every subunit, by size, "
                f"+{rates.get('waste_pct_pipe', 0):.0f} % waste\n"
                "- Mainline and submains: every pipe of the source-to-valve tree, by size\n"
                "- Version 1 priced the manifold as length × number of shifts; that "
                "assumption was withdrawn in 2.0.")

    items_ed = ed_boq.to_dict("records")
    tot = BQ.boq_totals(items_ed)
    with tabs[2]:
        sub_header("Cost Summary")
        c1, c2 = st.columns(2)
        with c1:
            contingency = st.slider("Contingency (%)", 0, 30, int(prev.get("contingency", 10)))
        with c2:
            overhead = st.slider("Overhead and profit (%)", 0, 30, int(prev.get("overhead", 12)))
        subtotal = tot["subtotal"]
        total = subtotal * (1 + contingency / 100.0) * (1 + overhead / 100.0)
        per_ha = total / max(setup["area_ha"], 1e-9)
        cards([("Subtotal", f"{subtotal:,.0f}", "EGP", "neutral"),
               ("Total with margins", f"{total:,.0f}", "EGP", "accent"),
               ("Cost per hectare", f"{per_ha:,.0f}", "EGP/ha", "accent"),
               ("Cost per feddan", f"{per_ha * FEDDAN_M2 / 10000.0:,.0f}", "EGP/fed", "neutral")])
        c1, c2 = st.columns([1, 1])
        with c1:
            st.plotly_chart(PL.cost_donut(tot["by_category"]), width="stretch", key="c_donut")
        with c2:
            st.dataframe(pd.DataFrame([{"Category": k, "Amount (EGP)": round(v),
                                        "Share (%)": round(100 * v / max(subtotal, 1e-9), 1)}
                                       for k, v in tot["by_category"].items()]),
                         hide_index=True, width="stretch")
        st.plotly_chart(PL.cost_bars(items_ed), width="stretch", key="c_bars")
        for cat, amt in tot["by_category"].items():
            with st.expander(f"**{cat}** - EGP {amt:,.0f}", expanded=False):
                st.dataframe(pd.DataFrame([i for i in items_ed if i["Category"] == cat]),
                             hide_index=True, width="stretch")

    # ------------------------------------------------------- economics ----
    with tabs[3]:
        sub_header("Economic Analysis")
        banner("warn", "Every figure on this tab is an <b>input</b>: interest rate, lives, "
                       "O&amp;M and the benefit. The defaults are placeholders to show the "
                       "method, not an appraisal.")
        c1, c2, c3 = st.columns(3)
        with c1:
            rate = st.number_input("Discount rate (%)", 0.0, 50.0,
                                   float(prev.get("disc_rate", 12.0)), 0.5) / 100.0
            horizon = st.number_input("Analysis horizon (years)", 5, 40,
                                      int(prev.get("horizon", 20)), 1)
        with c2:
            om_pct = st.number_input("O&M per year (% of capital)", 0.0, 20.0,
                                     float(prev.get("om_pct", 3.0)), 0.5)
            energy = float(pump.get("energy_cost", 0.0))
            cards([("Energy per year (from Pump Selection)", f"{energy:,.0f}", "EGP/yr",
                    "neutral")], columns=1)
        with c3:
            benefit_ha = st.number_input("Incremental net benefit (EGP/ha/yr)", 0.0, 1e7,
                                         float(prev.get("benefit_ha", 0.0)), 1000.0,
                                         help="Yield and water-saving benefit against the "
                                              "present system. Leave 0 for a cost-only "
                                              "analysis.")
        lives = dict(ctx["rates"]["lives_years"])
        lives.update(prev.get("lives") or {})
        led = stable_editor("cost_lives", lambda: pd.DataFrame(
            [{"Component": k, "Life (years)": float(v)} for k, v in lives.items()]),
            hide_index=True, width="stretch",
            column_config={"Component": st.column_config.TextColumn(disabled=True)})
        lives = {r["Component"]: max(1.0, float(r["Life (years)"])) for r in led.to_dict("records")}
        factor = (1 + contingency / 100.0) * (1 + overhead / 100.0)
        comps = [{"name": BQ.CATEGORY_LIFE.get(cat, cat), "capital": amt * factor,
                  "life_years": lives.get(BQ.CATEGORY_LIFE.get(cat, cat), 10.0)}
                 for cat, amt in tot["by_category"].items()]
        ann = E.annualised_cost(comps, rate)
        om = total * om_pct / 100.0
        benefit = benefit_ha * setup["area_ha"]
        flows = E.cash_flows(comps, int(horizon), om, energy, benefit)
        npv = E.npv(rate, flows)
        irr = E.irr(flows) if benefit > 0 else None
        pb = E.payback_year(flows) if benefit > 0 else None
        vol = float(pump.get("volume_season", 0.0))
        annual_cost = ann["total_annual"] + om + energy
        cards([("Annualised capital", f"{ann['total_annual']:,.0f}", "EGP/yr", "neutral"),
               ("Annual cost (capital + O&M + energy)", f"{annual_cost:,.0f}", "EGP/yr", "accent"),
               ("Cost per m³ applied", f"{annual_cost / max(vol, 1e-9):.2f}", "EGP/m³", "accent"),
               ("Cost per ha per year", f"{annual_cost / max(setup['area_ha'], 1e-9):,.0f}",
                "EGP/ha", "neutral")])
        st.dataframe(pd.DataFrame([{"Component": r["name"], "Capital (EGP)": round(r["capital"]),
                                    "Life (yr)": r["life_years"], "CRF": round(r["crf"], 4),
                                    "Annual (EGP)": round(r["annual"])} for r in ann["rows"]]),
                     hide_index=True, width="stretch")
        if benefit > 0:
            cards([("NPV", f"{npv:,.0f}", "EGP", "ok" if npv >= 0 else "bad"),
                   ("IRR", f"{irr*100:.1f}" if irr is not None else "—", "%", "neutral"),
                   ("Simple payback", f"{pb:.1f}" if pb is not None else "beyond horizon",
                    "years" if pb is not None else "", "neutral"),
                   ("B/C (annual)", f"{benefit / max(annual_cost, 1e-9):.2f}", "", "neutral")])
            st.plotly_chart(PL.cash_flow_chart(flows), width="stretch", key="c_cash")
        else:
            note("Enter the incremental net benefit per hectare to see NPV, IRR and payback. "
                 "The annual cost and cost per cubic metre above do not depend on it.")

    if st.button("💾 Save", type="primary", key="save_cost"):
        save(S, "cost", {
            "items": items_ed, "subtotal": subtotal, "contingency": contingency,
            "overhead": overhead, "total": total, "per_ha": per_ha,
            "by_category": tot["by_category"], "rates": rates, "drip_price": drip_price,
            "em_price": em_price, "disc_rate": rate * 100.0, "horizon": int(horizon),
            "om_pct": om_pct, "benefit_ha": benefit_ha, "lives": lives,
            "annualised_capital": ann["total_annual"], "annual_cost": annual_cost,
            "cost_per_m3": annual_cost / max(vol, 1e-9), "npv": npv if benefit > 0 else None,
            "irr": irr, "payback": pb, "cash_flows": flows,
        })
        st.success("✅ Cost estimate saved.")
        goto("report")
    dev_panel(S, "cost")


def _pipe_price_editor(S, ctx):
    """Manifold / mainline pipe prices, per project (see engine/boq.py)."""
    section("Pipe prices — manifolds, mainline and submains")
    caption("The telescoped manifold sizing chooses between pipe sizes on price, so these "
            "prices are used by the <b>Pipe Network Design</b> page as well as by the bill "
            "of quantities. After saving new prices, open Pipe Network Design and the pages "
            "after it and press Save again: until then they are marked out of date.")
    cat = ctx["pipes_catalogue"]["pipes"]
    over = S.get("pipe_prices") or {}

    def make():
        return pd.DataFrame([{"Pipe": BQ.pipe_key(p), "Use": p.get("role", ""),
                              "Inner Ø (mm)": p["internal_mm"],
                              "Catalogue (EGP/m)": float(p["price_egp_per_m"]),
                              "Your price (EGP/m)": float(over.get(BQ.pipe_key(p),
                                                                   p["price_egp_per_m"]))}
                             for p in cat])
    ed = stable_editor("pipe_prices", make, hide_index=True, width="stretch",
                       column_config={
                           "Pipe": st.column_config.TextColumn(disabled=True),
                           "Use": st.column_config.TextColumn(disabled=True),
                           "Inner Ø (mm)": st.column_config.NumberColumn(disabled=True),
                           "Catalogue (EGP/m)": st.column_config.NumberColumn(disabled=True),
                           "Your price (EGP/m)": st.column_config.NumberColumn(
                               min_value=0.0, max_value=100000.0, step=0.5, format="%.2f")})
    new = {r["Pipe"]: float(r["Your price (EGP/m)"]) for r in ed.to_dict("records")
           if r["Your price (EGP/m)"] is not None}
    changed = {k: v for k, v in new.items()
               if abs(v - next(float(p["price_egp_per_m"]) for p in cat
                               if BQ.pipe_key(p) == k)) > 1e-9}
    c1, c2 = st.columns(2)
    with c1:
        if st.button("💾 Save pipe prices", key="save_pipe_prices",
                     disabled=(changed == over)):
            if changed:
                save(S, "pipe_prices", changed)
            else:
                S.pop("pipe_prices", None)
            st.rerun()
    with c2:
        if over and st.button("↺ Restore catalogue pipe prices", key="reset_pipe_prices"):
            S.pop("pipe_prices", None)
            reset_editor("pipe_prices", pd.DataFrame())
            st.session_state.pop("_base_pipe_prices", None)
            st.rerun()
    if over:
        banner("accent", f"{len(over)} pipe price(s) differ from the catalogue for this project.")
