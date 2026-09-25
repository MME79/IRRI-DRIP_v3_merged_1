"""
Pump Selection — OpenIrri's four tabs: System Requirements, Pump Matching,
Performance Curves, Power Analysis.

The difference from a sprinkler program is the system curve. Emitters impose
H ∝ Q^(1/x), so a drip system curve is far steeper than the parabola a
sprinkler program draws, and for pressure-compensating emitters it is nearly
vertical at the design flow. Pumps are matched on the curve the emitters
actually impose.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from engine import kernels as K
from engine import pumps as P
from modules import plots as PL
from modules.common import (page_header, sub_header, section, cards, banner, note,
                            caption, save, stage_guard, goto, dev_panel, context_strip)


def show(ctx):
    S = ctx["S"]
    page_header("Pump Selection",
                "Match a pump to the duty on the drip system curve, check its operating "
                "point and efficiency, and cost the season's energy.")
    if not stage_guard(S, "hydraulic", "Hydraulic Design", page_key="hydraulic"):
        return
    context_strip(S)
    setup, em, wat, hy = S["setup"], S["emitter"], S["water"], S["hydraulic"]
    prev = S.get("pump", {})
    sc = hy["system_curve"]
    sys_h = P.system_curve(sc["q_design"], sc["h_static"], sc["h_emitter"], sc["h_pipe"],
                           sc["h_other"], sc["x"])
    q_req, h_req = hy["q_duty"], hy["h_duty"]

    tabs = st.tabs(["📊 System Requirements", "🎯 Pump Matching", "📈 Performance Curves",
                    "⚡ Power Analysis"])

    with tabs[0]:
        sub_header("System Requirements")
        cards([("Duty flow", f"{q_req:.2f}", "m³/h", "accent"),
               ("Total dynamic head", f"{h_req:.2f}", "m", "accent"),
               ("Critical shift", f"{hy['critical_shift']}", "", "neutral"),
               ("Emitter exponent x", f"{sc['x']:.2f}", "", "neutral")])
        x_note = (f" (x = {sc['x']:.2f} is floored at 0.05 for the curve: a fully "
                  "vertical curve has no intersection)" if sc["x"] < 0.05 else "")
        with st.expander("📊 Data Linkage Status", expanded=True):
            st.markdown(
                f"- ✅ Duty from Hydraulic Design (shift envelope)\n"
                f"- ✅ System curve: static {sc['h_static']:.1f} m + emitter "
                f"{sc['h_emitter']:.1f} m·(Q/Qd)^(1/{max(sc['x'], 0.05):.2f})"
                f"{x_note}"
                " + pipes "
                f"{sc['h_pipe']:.1f} m·(Q/Qd)^1.85 + head control {sc['h_other']:.1f} m·(Q/Qd)²\n"
                f"- {'✅' if wat.get('monthly') else '⚠️'} Season volume "
                f"{wat.get('season_volume_m3', 0):,.0f} m³ "
                f"({'summed month by month' if wat.get('monthly') else 'peak extrapolated'})")
        note("A sprinkler program draws H = H<sub>static</sub> + K·Q². Here the emitter term "
             "scales with Q<sup>1/x</sup>: for x = 0.5 that is the same parabola, for a "
             "compensating emitter (x ≈ 0.05) the curve is nearly vertical and a pump "
             "matched on a parabola lands at the wrong point.")

    # --------------------------------------------------------- candidates ----
    generic = P.generic_catalogue(ctx["pumps"]["pumps"])
    with tabs[1]:
        sub_header("Pump Matching")
        source = st.radio("Pump data", ["Generic type curves (indicative)",
                                        "Custom pump from the manufacturer's curve"],
                          index=0 if prev.get("source", "generic") == "generic" else 1,
                          horizontal=True)
        custom = None
        if source.startswith("Custom"):
            cd = prev.get("custom") or {}
            st.markdown("Enter three points read from the manufacturer's published curve at "
                        "the impeller diameter and speed you will buy, plus its best-efficiency "
                        "point.")
            cols = st.columns(3)
            pts = []
            dq = [0.0, q_req, q_req * 1.4]
            dh = [h_req * 1.3, h_req * 1.05, h_req * 0.75]
            for i, c in enumerate(cols):
                with c:
                    qv = st.number_input(f"Q{i+1} (m³/h)", 0.0, 5000.0,
                                         float(cd.get("pts", [[dq[j], dh[j]] for j in range(3)])[i][0]),
                                         1.0, key=f"pc_q{i}")
                    hv = st.number_input(f"H{i+1} (m)", 0.0, 500.0,
                                         float(cd.get("pts", [[dq[j], dh[j]] for j in range(3)])[i][1]),
                                         0.5, key=f"pc_h{i}")
                    pts.append([qv, hv])
            c1, c2, c3 = st.columns(3)
            name = c1.text_input("Pump model", cd.get("name", "Custom pump"))
            qb = c2.number_input("BEP flow (m³/h)", 0.1, 5000.0,
                                 float(cd.get("q_bep", q_req)), 1.0)
            eb = c3.number_input("BEP efficiency (%)", 10.0, 92.0,
                                 float(cd.get("eta_bep", 72.0)), 1.0)
            try:
                a, b, c = P.fit_quadratic(pts)
                custom = P.PumpCurve(name, a, b, c, qb, eb / 100.0, source="manufacturer curve")
                cands = [custom]
            except ValueError as exc:
                banner("bad", f"These points do not define a pump curve: {exc}")
                cands = []
        else:
            banner("warn", "The generic curves are <b>shapes spanning the duty range, not "
                           "products</b>. Use them to see what class of pump fits; buy from "
                           "a manufacturer's published curve (Custom).")
            cands = generic
        ranked = P.match_pumps(cands, q_req, h_req, sys_h)
        good = [r for r in ranked if r["qualifies"]]
        if not ranked:
            return
        table = pd.DataFrame([{
            "Pump": r["pump"].name,
            "Q op (m³/h)": round(r["op"]["q_m3h"], 1) if r["op"] else None,
            "H op (m)": round(r["op"]["h_m"], 1) if r["op"] else None,
            "η at op (%)": round(100 * r["op"]["eta"], 1) if r["op"] else None,
            "Q/Q_BEP": round(r["op"]["bep_ratio"], 2) if r["op"] else None,
            "In POR": ("yes" if r.get("in_por") else "no") if r["op"] else "—",
            "Delivers duty": "✓" if r["qualifies"] else "✗"} for r in ranked[:12]])
        st.dataframe(table, hide_index=True, width="stretch")
        names = [r["pump"].name for r in (good or ranked)]
        default = prev.get("pump_name") if prev.get("pump_name") in names else names[0]
        chosen_name = st.selectbox("Selected pump", names, index=names.index(default))
        chosen = next(r for r in ranked if r["pump"].name == chosen_name)
        if not good:
            banner("bad", "No candidate delivers the duty on the system curve. Enter a "
                          "larger manufacturer's curve, or reduce the head (fewer filters "
                          "in series, a lower-loss injector, a larger mainline).")
        caption(f"Preferred operating region: {P.POR_LOW*100:.0f}–{P.POR_HIGH*100:.0f} % of "
                "best-efficiency flow (ANSI/HI 9.6.3).")

    op_pt = chosen["op"]
    with tabs[2]:
        sub_header("Performance Curves")
        show_n = [r for r in ranked[:4] if r["op"]] or [chosen]
        if chosen not in show_n:
            show_n = [chosen] + show_n[:3]
        q_max = max([q_req * 1.8] + [r["pump"].q_max for r in show_n])
        st.plotly_chart(PL.pump_curves([(r["pump"], r["op"]) for r in show_n], sys_h, q_req,
                                       h_req, q_max), width="stretch", key="pc_chart")
        with st.expander("ℹ️ Understanding the Charts"):
            st.markdown("The dashed line is the drip system curve for the critical shift. "
                        "Each pump's operating point is where its curve crosses it. The red "
                        "cross is the duty required; a qualifying pump crosses at or to the "
                        "right of it. The lower panel shows each pump's efficiency — the "
                        "operating point should sit near the top of that hump.")

    with tabs[3]:
        sub_header("Power Analysis")
        if op_pt is None:
            banner("bad", "The selected pump has no operating point on this system.")
            return
        c1, c2, c3 = st.columns(3)
        with c1:
            eta_motor = st.slider("Motor efficiency", 0.75, 0.96,
                                  float(prev.get("eta_motor", 0.90)), 0.01)
        with c2:
            tariff = st.number_input("Electricity tariff (EGP/kWh)", 0.0, 50.0,
                                     float(prev.get("tariff", 2.20)), 0.05,
                                     help="Placeholder — enter the applicable tariff")
        with c3:
            diesel_price = st.number_input("Diesel price (EGP/L)", 0.0, 200.0,
                                           float(prev.get("diesel_price", 15.0)), 0.5,
                                           help="Placeholder — enter the current price")
        eta_pump = max(0.05, op_pt["eta"])
        try:
            power = K.pump_power(op_pt["q_m3h"], op_pt["h_m"], eta_pump, eta_motor)
        except ValueError as exc:
            banner("bad", f"<b>No pump duty can be computed.</b> {exc}")
            return
        volume = float(wat.get("season_volume_m3", 0.0))
        hours = volume / max(op_pt["q_m3h"], 1e-9)
        kwh = power["motor_input_kw"] * hours
        cost_e = kwh * tariff
        diesel_l = P.diesel_fuel_lph(power["brake_kw"]) * hours
        cards([("Hydraulic power", f"{power['hydraulic_kw']:.2f}", "kW", "neutral"),
               ("Brake power", f"{power['brake_kw']:.2f}", "kW", "neutral"),
               ("Motor rating", f"{power['motor_rating_kw']:.1f}", "kW",
                "bad" if power["rating_off_scale"] else "ok"),
               ("Pump η at op", f"{100*eta_pump:.1f}", "%",
                "ok" if chosen.get("in_por") else "warn")])
        cards([("Pumping hours / season", f"{hours:,.0f}", "h", "neutral"),
               ("Energy / season", f"{kwh:,.0f}", "kWh", "neutral"),
               ("Electricity cost", f"{cost_e:,.0f}", "EGP", "accent"),
               ("Energy intensity", f"{kwh/max(volume,1e-9):.3f}", "kWh/m³", "accent")])
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("##### Diesel alternative")
            cards([("Fuel / season", f"{diesel_l:,.0f}", "L", "neutral"),
                   ("Fuel cost", f"{diesel_l*diesel_price:,.0f}", "EGP", "neutral")])
            caption("At 0.25 L per brake-kWh — an input range of 0.22–0.30 covers most "
                    "irrigation engines at part load.")
        with c2:
            st.markdown("##### Solar PV sizing")
            psh = st.number_input("Peak sun hours (kWh/m²/day)", 1.0, 9.0,
                                  float(prev.get("psh", 6.0)), 0.1,
                                  help="Enter the site value for the design month")
            peak_m3 = wat["etc"] / wat["ea"] * setup["area_ha"] * 10.0
            daily = peak_m3 / max(op_pt["q_m3h"], 1e-9) * power["motor_input_kw"]
            kwp = P.solar_array_kwp(daily, psh)
            cards([("Peak-day energy", f"{daily:,.0f}", "kWh", "neutral"),
                   ("PV array", f"{kwp:,.1f}", "kWp", "accent")])
            caption("Direct-drive array for the peak day at a performance ratio of 0.70. "
                    "Inverter, controller and storage are not sized here.")
        if power["rating_off_scale"]:
            banner("bad", f"The duty is off the top of the standard motor list: "
                          f"{power['required_rating_kw']:.1f} kW needed. Specify a custom "
                          "unit or split the system.")

    if st.button("💾 Save", type="primary", key="save_pump"):
        save(S, "pump", {
            "source": "custom" if custom else "generic",
            "custom": ({"pts": pts, "name": name, "q_bep": qb, "eta_bep": eb}
                       if custom else prev.get("custom")),
            "pump_name": chosen["pump"].name, "pump_curve": chosen["pump"].to_dict(),
            "operating_point": op_pt, "in_por": chosen.get("in_por", False),
            "qualifies": chosen["qualifies"],
            "eta_pump": eta_pump, "eta_motor": eta_motor, "minor": 0.0,
            "tdh": hy["tdh"], "q_duty": op_pt["q_m3h"], "h_duty_required": h_req,
            "q_duty_required": q_req, "power": power, "tariff": tariff,
            "diesel_price": diesel_price, "psh": psh,
            "season": wat.get("season_days", 150), "hours_season": hours, "kwh": kwh,
            "energy_cost": cost_e, "energy_per_m3": kwh / max(volume, 1e-9),
            "volume_season": volume, "diesel_l_season": diesel_l, "pv_kwp": kwp,
        })
        S.pop("cost", None)
        st.success("✅ Pump selection saved.")
        goto("cost")
    dev_panel(S, "pump")
