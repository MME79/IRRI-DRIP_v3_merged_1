"""
Hydraulic Design — OpenIrri's two tabs, Pressure Requirements and System
Head, fed by the network solved on Pipe Network Design.

The total dynamic head is built per SHIFT, not for one assumed path: the
head needed at the network inlet differs from shift to shift (different
valves, different distances, different lifts), and the pump has to serve the
worst of them. The head-control terms — the filter differential with its
backflush allowance, the injector, the fittings and meter — are added once.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from engine import pumps as P
from modules import plots as PL
from modules.common import (page_header, sub_header, section, cards, banner, note,
                            caption, save, stage_guard, goto, dev_panel, context_strip)


def show(ctx):
    S = ctx["S"]
    page_header("Hydraulic Design",
                "Pressure required at every valve and the total dynamic head at the pump, "
                "shift by shift, with the head-control losses that sprinkler designs most "
                "often leave out.")
    if not stage_guard(S, "manifold", "Pipe Network Design", page_key="design"):
        return
    context_strip(S)
    setup, em, lat, man = S["setup"], S["emitter"], S["lateral"], S["manifold"]
    qual = S.get("quality") or {}
    fert = S.get("fertigation") or {}
    prev = S.get("hydraulic", {})
    if "hydraulics" not in man:
        banner("bad", "This network design was saved by an earlier version. Reopen Pipe "
                      "Network Design and press Save.")
        return

    with st.expander("📊 Data Source Status", expanded=False):
        st.markdown(
            f"- Static lift: **{setup['static_lift']:.1f} m** (Home › Project Setup)\n"
            f"- Filter differential: **{qual.get('filt_clean', 3.0) + qual.get('filt_dirty', 4.0):.1f} m** "
            f"({'Water Quality' if qual else 'NOT SET — default 3 + 4 m'})\n"
            f"- Injector: **{fert.get('inj_loss', 0.0):.1f} m** "
            f"({fert.get('injector', 'NOT SET — taken as 0 m')})\n"
            f"- Network inlet head per shift: Pipe Network Design, critical shift "
            f"{man['critical_shift']}")
    if not qual or not fert:
        banner("warn", "Water Quality &amp; Filtration has not been saved; default filter "
                       "losses (3 + 4 m) and no injector are assumed. A venturi alone "
                       "typically costs 6 m — often one motor frame size.")

    tabs = st.tabs(["Pressure Requirements", "System Head"])
    with tabs[0]:
        sub_header("Pressure Requirements")
        c1, c2 = st.columns(2)
        with c1:
            fittings = st.number_input("Head-control fittings, meter, check valve (m)", 0.0,
                                       20.0, float(prev.get("fittings_m", 1.5)), 0.1)
        with c2:
            suction = st.number_input("Suction-side friction (m)", 0.0, 20.0,
                                      float(prev.get("suction_m", 0.5)), 0.1)
        crit_v = man["hydraulics"][str(man["critical_shift"])]["critical_valve"]
        d = man["designs"][crit_v]
        chain = [
            ("Emitter operating head", em["h_op"]),
            ("Lateral: inlet above minimum emitter", lat["lateral_inlet_required_m"] - em["h_op"]),
            ("Manifold: inlet above minimum outlet", d["inlet_minus_min_m"]),
            ("Subunit valve and regulator", man["valve_loss"]),
        ]
        st.markdown(f"##### Pressure needed at the critical valve ({crit_v})")
        st.dataframe(pd.DataFrame([{"Component": c, "Head (m)": round(v, 2)} for c, v in chain]
                                  + [{"Component": "Required at the valve inlet",
                                      "Head (m)": round(sum(v for _, v in chain), 2)}]),
                     hide_index=True, width="stretch")
        st.markdown("##### Required head at every valve")
        st.dataframe(pd.DataFrame([{"Valve": v, "Required (m)": round(h, 2)}
                                   for v, h in sorted(man["h_req_valve"].items())]),
                     hide_index=True, width="stretch", height=260)

    head_ctrl = (qual.get("filt_clean", 3.0) + qual.get("filt_dirty", 4.0)
                 + fert.get("inj_loss", 0.0) + fittings)
    rows = []
    for sh, h in sorted(man["hydraulics"].items(), key=lambda kv: int(kv[0])):
        tdh = setup["static_lift"] + suction + h["h_source_m"] + head_ctrl
        rows.append({"Shift": int(sh), "Flow (m³/h)": h["q_m3h"],
                     "Network inlet (m)": h["h_source_m"], "TDH (m)": tdh,
                     "Critical valve": h["critical_valve"],
                     "Path friction (m)": h["critical_path_loss_m"],
                     "Lift (m)": h["critical_lift_m"]})
    crit_row = max(rows, key=lambda r: r["TDH (m)"])
    q_duty = max(r["Flow (m³/h)"] for r in rows)
    h_duty = crit_row["TDH (m)"]

    with tabs[1]:
        sub_header("System Head")
        st.plotly_chart(PL.shift_heads([r["Shift"] for r in rows], [r["TDH (m)"] for r in rows],
                                       [r["Flow (m³/h)"] for r in rows]),
                        width="stretch", key="hy_shifts")
        st.dataframe(pd.DataFrame([{k: (round(v, 2) if isinstance(v, float) else v)
                                    for k, v in r.items()} for r in rows]),
                     hide_index=True, width="stretch")
        parts = [("Static lift", setup["static_lift"]), ("Suction friction", suction),
                 ("Emitter head", em["h_op"]),
                 ("Lateral + manifold", lat["lateral_inlet_required_m"] - em["h_op"]
                  + d["inlet_minus_min_m"]),
                 ("Valve + regulator", man["valve_loss"]),
                 ("Mainline friction", crit_row["Path friction (m)"]),
                 ("Lift within the field", crit_row["Lift (m)"]),
                 ("Filters (clean + backflush)", qual.get("filt_clean", 3.0) + qual.get("filt_dirty", 4.0)),
                 ("Fertigation injector", fert.get("inj_loss", 0.0)),
                 ("Fittings and meter", fittings)]
        st.plotly_chart(PL.head_breakdown([p[0] for p in parts], [p[1] for p in parts],
                                          f"Total dynamic head — critical shift {crit_row['Shift']}"),
                        width="stretch", key="hy_bd")
        cards([("Duty flow", f"{q_duty:.2f}", "m³/h", "accent"),
               ("Total dynamic head", f"{h_duty:.2f}", "m", "accent"),
               ("Critical shift", f"{crit_row['Shift']}", "", "neutral"),
               ("Head control share", f"{100*head_ctrl/max(h_duty,1e-9):.0f}", "%", "neutral")])
        note(f"The duty is the envelope of the shifts: the largest flow "
             f"({q_duty:.1f} m³/h) at the largest head ({h_duty:.1f} m). One pump serves "
             "every shift; the shifts that need less head get it burned off by their "
             "regulators, which is the energy a variable-speed drive would recover.")
        filt = qual.get("filt_clean", 3.0) + qual.get("filt_dirty", 4.0)
        caption(f"Filtration is {100*filt/max(h_duty,1e-9):.0f} % of the head. That term is "
                "the one most often missing from a pump specification carried over from a "
                "sprinkler design.")

    # System curve for the pump page: terms by how they scale with flow.
    h_static = setup["static_lift"] + crit_row["Lift (m)"]
    h_emit = em["h_op"]
    h_pipe = (lat["lateral_inlet_required_m"] - em["h_op"] + d["inlet_minus_min_m"]
              + crit_row["Path friction (m)"] + suction)
    h_other = man["valve_loss"] + head_ctrl
    q_crit = crit_row["Flow (m³/h)"]

    if st.button("💾 Save", type="primary", key="save_hyd"):
        save(S, "hydraulic", {
            "fittings_m": fittings, "suction_m": suction, "per_shift": rows,
            "critical_shift": crit_row["Shift"], "q_duty": q_duty, "h_duty": h_duty,
            "head_control_m": head_ctrl,
            "system_curve": {"q_design": q_crit, "h_static": h_static, "h_emitter": h_emit,
                             "h_pipe": h_pipe, "h_other": h_other, "x": em["x"]},
            # v1-shaped breakdown, used by the report and the DXF title block
            "tdh": {"tdh_m": h_duty, "static_m": setup["static_lift"] + crit_row["Lift (m)"],
                    "emitter_head_m": em["h_op"],
                    "pipe_friction_m": h_pipe,
                    "minor_m": fittings + man["valve_loss"],
                    "filter_m": qual.get("filt_clean", 3.0) + qual.get("filt_dirty", 4.0),
                    "fertigation_m": fert.get("inj_loss", 0.0)},
        })
        S.pop("pump", None)
        st.success("✅ Hydraulic design saved.")
        goto("pump")
    dev_panel(S, "hydraulic")
