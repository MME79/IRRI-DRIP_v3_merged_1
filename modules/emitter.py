"""
Emitter Selection — the drip counterpart of OpenIrri's Sprinkler Selection,
with the same four tabs: Emitter Selection, Spacing Design, Application Rate,
Uniformity.

The uniformity tab is where the design's pressure budget is set: the target
emission uniformity fixes the allowable head variation in a subunit, and the
split of that allowance between lateral and manifold fixes how long a
lateral may run — which is what cuts the field into subunits on the next page.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from engine import kernels as K
from engine import network as N
from modules import graphics as G
from modules import plots as PL
from modules.common import (page_header, sub_header, section, cards, banner, note,
                            caption, save, stage_guard, goto, dev_panel, context_strip)


def show(ctx):
    S = ctx["S"]
    page_header("Emitter Selection",
                "Select the emitter and dripline, lay out the emitter and lateral "
                "spacing, check the application rate and set the uniformity budget. "
                "Emitter hydraulics follow q = k·H<sup>x</sup> — the exponent x has no "
                "counterpart in sprinkler design and governs how sensitive the system "
                "is to pressure.")
    if not stage_guard(S, "water", "Crop Water Requirements", page_key="water"):
        return
    context_strip(S)
    setup = S["setup"]
    cat = ctx["emitters"]["emitters"]
    lat_cat = ctx["pipes"]["laterals"]
    prev = S.get("emitter", {})

    tabs = st.tabs(["Emitter Selection", "Spacing Design", "Application Rate",
                    "Uniformity"])

    # ------------------------------------------------------------ tab 1 ----
    with tabs[0]:
        sub_header("Emitter and Dripline")
        banner("warn", "The bundled emitter catalogue is <b>indicative, not manufacturer "
                       "data</b>. Replace k, x, CV, flow passage and price with the "
                       "supplier's published figures before issuing any design.")
        names = [e["name"] for e in cat]
        c1, c2 = st.columns([2, 1])
        with c1:
            ename = st.selectbox("Emitter", names, index=prev.get("e_idx", 3))
            em = next(e for e in cat if e["name"] == ename)
        with c2:
            h_op = st.number_input("Operating head (m)", 1.0, 60.0,
                                   float(prev.get("h_op", em["h_nominal_m"])), 0.5)
        c1, c2, c3, c4, c5 = st.columns(5)
        with c1:
            k_val = st.number_input("k", value=float(prev.get("k", em["k"])),
                                    format="%.4f", step=0.01)
        with c2:
            x_val = st.number_input("x (exponent)", 0.0, 1.0,
                                    float(prev.get("x", em["x"])), 0.01, format="%.3f")
        with c3:
            cv = st.number_input("CV (manufacturing)", 0.0, 0.4,
                                 float(prev.get("cv", em["cv"])), 0.005, format="%.3f")
        with c4:
            passage = st.number_input("Flow passage (mm)", 0.1, 5.0,
                                      float(prev.get("passage", em["passage_mm"])), 0.05)
        with c5:
            le = st.number_input("Barb loss le (m)", 0.0, 1.0,
                                 float(prev.get("le_m", em.get("le_m", 0.15))), 0.01,
                                 format="%.3f",
                                 help="Equivalent length added per emitter for its "
                                      "local loss")
        labels = [f"{p['nominal_mm']:.0f} mm (ID {p['internal_mm']:.1f}, PN{p['pn_bar']:g})"
                  for p in lat_cat]
        lpick = st.selectbox("Dripline / lateral pipe", labels,
                             index=prev.get("l_idx", 0),
                             help="Internal diameter enters head loss to the fifth power: "
                                  "verify it against the supplier's table")
        lat_pipe = lat_cat[labels.index(lpick)]
        q_emitter = K.emitter_discharge(k_val, x_val, h_op)
        c1, c2 = st.columns([1, 1])
        with c1:
            st.plotly_chart(PL.emitter_curve(k_val, x_val, h_op, q_emitter),
                            width="stretch", key="em_curve")
        with c2:
            heads = [h_op * f for f in (0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3)]
            df = pd.DataFrame({
                "Head (m)": [round(h, 2) for h in heads],
                "Discharge (L/h)": [round(K.emitter_discharge(k_val, x_val, h), 3)
                                    for h in heads]})
            df["Deviation (%)"] = (100 * (df["Discharge (L/h)"] / q_emitter - 1)).round(1)
            st.dataframe(df, hide_index=True, width="stretch")
        cv_status = {"excellent": "ok", "average": "ok", "marginal": "warn",
                     "poor": "bad", "unacceptable": "bad"}[K.cv_class(cv)]
        cards([("Emitter discharge", f"{q_emitter:.2f}", "L/h", "accent"),
               ("Exponent x", f"{x_val:.2f}", "PC" if x_val <= 0.15 else "non-PC", "neutral"),
               ("CV class", K.cv_class(cv), "", cv_status),
               ("Dripline bore", f"{lat_pipe['internal_mm']:.1f}", "mm", "neutral")])
        if x_val <= 0.15:
            banner("ok", f"x = {x_val:.2f} — <b>pressure compensating</b>. Discharge is "
                         "nearly independent of head, which permits long laterals and "
                         "sloping ground at a higher unit price and minimum head.")
        else:
            q_lo = K.emitter_discharge(k_val, x_val, h_op * 0.8)
            note(f"x = {x_val:.2f} — <b>pressure sensitive</b>. A 20 % head drop reduces "
                 f"discharge from {q_emitter:.2f} to {q_lo:.2f} L/h "
                 f"({100*(1-q_lo/q_emitter):.1f} %). This is what the allowable head "
                 "variation on the Uniformity tab protects.")

    # ------------------------------------------------------------ tab 2 ----
    with tabs[1]:
        sub_header("Spacing Design")
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            se = st.number_input("Emitter spacing Se (m)", 0.05, 10.0,
                                 float(prev.get("se", 0.50)), 0.05)
        with c2:
            sl = st.number_input("Lateral spacing Sl (m)", 0.2, 20.0,
                                 float(prev.get("sl", 2.0)), 0.1)
        with c3:
            dw = st.number_input("Wetted diameter Dw (m)", 0.1, 6.0,
                                 float(prev.get("dw", setup["soil"]["wetted_diameter_ref_m"])),
                                 0.05, help="Rarely measured and the most influential "
                                            "input here — measure it in a field trial")
        with c4:
            lat_per_row = st.number_input("Laterals per crop row", 1, 4,
                                          int(prev.get("lat_per_row", 1)), 1)
        pw = K.wetted_fraction(dw, se, sl, lat_per_row)
        pw_class, pw_msg = K.wetting_verdict(pw)
        cards([("Wetted fraction Pw", f"{pw*100:.1f}", "%",
                "ok" if 0.20 <= pw <= 0.85 else "warn"),
               ("Emitters per ha", f"{10000.0/(se*sl)*lat_per_row:,.0f}", "", "neutral"),
               ("Dripline per ha", f"{10000.0/sl*lat_per_row:,.0f}", "m", "neutral")])
        st.markdown(G.wetting_section_svg({"sl": sl, "dw": dw, "se": se, "pw": pw},
                                          setup["soil"]["name"]), unsafe_allow_html=True)
        if pw_class != "ok":
            banner("bad" if pw_class in ("none", "saturated") else "warn",
                   f"Pw = {pw*100:.0f} % — {pw_msg}")

    # ------------------------------------------------------------ tab 3 ----
    ia = K.application_rate(q_emitter, se, sl) * lat_per_row
    emitters_per_ha = 10000.0 / (se * sl) * lat_per_row
    n_emitters_total = emitters_per_ha * setup["area_ha"]
    q_full_field = n_emitters_total * q_emitter / 1000.0
    with tabs[2]:
        sub_header("Application Rate")
        cards([("Application rate", f"{ia:.2f}", "mm/h", "accent"),
               ("Emitters, whole field", f"{n_emitters_total:,.0f}", "", "neutral"),
               ("Flow if all ran at once", f"{q_full_field:.1f}", "m³/h", "neutral"),
               ("Source available", f"{setup['q_avail']:.1f}", "m³/h",
                "ok" if setup["q_avail"] >= q_full_field else "warn")])
        wat = S["water"]
        # The same gross-depth rule as Operational Design and the season volume.
        d_peak = K.gross_depth(wat["etc"], wat["ea"], wat.get("lr", 0.0))
        cards([("Peak gross demand", f"{d_peak:.2f}", "mm/day", "neutral"),
               ("Hours/day to meet it", f"{d_peak/max(ia,1e-9):.2f}", "h at full field",
                "neutral"),
               ("Minimum shifts by water", f"{K.number_of_shifts(setup['q_avail'], q_full_field)}",
                "", "neutral")])
        caption("The equivalent application rate spreads each emitter's discharge over "
                "its Se × Sl rectangle. It sets the set time; the soil only sees the "
                "point discharge, so surface ponding is judged by the wetted bulb, not "
                "by this figure.")

    # ------------------------------------------------------------ tab 4 ----
    with tabs[3]:
        sub_header("Uniformity Budget")
        c1, c2 = st.columns(2)
        with c1:
            eu_target = st.number_input("Target emission uniformity EU (%)", 60.0, 99.0,
                                        float(prev.get("eu_target", 90.0)), 1.0,
                                        help="ASABE EP405: 90 % or more for most crops "
                                             "on level ground")
        with c2:
            share = st.slider("Share of the allowable variation given to the lateral",
                              0.3, 0.8, float(prev.get("share", 0.55)), 0.05,
                              help="The rest goes to the manifold")
        dh_sub = K.allowable_head_variation(h_op, x_val, eu_target, cv, 1)
        dh_lat = dh_sub * share
        dh_man = dh_sub * (1 - share)
        nu = K.kinematic_viscosity(25.0)
        rough = K.ROUGHNESS_MM.get(str(lat_pipe.get("material", "PE")).upper(), 0.007)
        runs = {}
        for slope_case in sorted({0.0, float(setup.get("slope", 0.0))}):
            runs[slope_case] = N.max_lateral_run(q_emitter, se, lat_pipe["internal_mm"], le,
                                                 slope_case, dh_lat, nu, rough)
        run = runs[float(setup.get("slope", 0.0))]
        cards([("Allowable subunit ΔH", f"{dh_sub:.2f}", "m", "accent"),
               ("To the lateral", f"{dh_lat:.2f}", "m", "neutral"),
               ("To the manifold", f"{dh_man:.2f}", "m", "neutral"),
               ("Max lateral run", f"{run['max_run_m']:.0f}", "m",
                "ok" if run["max_run_m"] >= 20 else "warn")])
        note(f"At EU {eu_target:.0f} % with CV {cv:.3f} and x {x_val:.2f}, the emitters of "
             f"one subunit may differ in head by <b>{dh_sub:.2f} m</b> "
             f"({100*dh_sub/h_op:.0f} % of the {h_op:.1f} m operating head). Giving "
             f"{share*100:.0f} % of it to the lateral, a {lat_pipe['nominal_mm']:.0f} mm "
             f"dripline can run <b>{run['max_run_m']:.0f} m</b> on a "
             f"{setup.get('slope', 0.0):+.1f} % slope before its head spread exceeds "
             f"{dh_lat:.2f} m (limited by {run['governed_by']}). That length is what cuts "
             "the field into subunits on the Operational Design page.")
        if len(runs) > 1:
            caption(f"On level ground the same dripline would reach "
                    f"{runs[0.0]['max_run_m']:.0f} m.")

    if st.button("💾 Save", type="primary", key="save_emitter"):
        old = dict(prev)
        save(S, "emitter", {
            "name": ename, "e_idx": names.index(ename), "h_op": h_op,
            "k": k_val, "x": x_val, "cv": cv, "passage": passage, "le_m": le,
            "q_emitter": q_emitter, "se": se, "sl": sl, "dw": dw,
            "lat_per_row": lat_per_row, "pw": pw, "ia": ia,
            "emitters_per_ha": emitters_per_ha, "n_emitters_total": n_emitters_total,
            "q_full_field": q_full_field,
            "price_egp": em.get("price_egp", 1.0),
            "l_idx": labels.index(lpick), "lateral_pipe": lat_pipe,
            "eu_target": eu_target, "share": share,
            "dh_allow_subunit": dh_sub, "dh_allow_lateral": dh_lat,
            "dh_allow_manifold": dh_man, "max_run_m": run["max_run_m"],
            "max_run_governed_by": run["governed_by"],
        })
        # Geometry-bearing results are stale only if what shapes the subunits
        # changed; a CV or price edit must not throw away a hand-edited network.
        new = S["emitter"]
        if any(abs(float(old.get(k, -1.0)) - float(new[k])) > 1e-9 for k in
               ("q_emitter", "se", "sl", "lat_per_row", "max_run_m", "h_op")):
            for k in ("operation", "network", "lateral", "manifold", "hydraulic"):
                S.pop(k, None)
        st.success("✅ Emitter selection saved.")
        goto("operation")
    dev_panel(S, "emitter")
