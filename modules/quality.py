"""
Water Quality & Filtration — the one page with no counterpart in OpenIrri,
laid out in its idiom: Clogging Hazard, Filtration, Chemical Maintenance,
Fertigation.

Clogging is the failure mode that ends most drip systems in Egypt. It is a
design problem, not a maintenance problem: the filtration grade follows from
the emitter passage, the filter differential enters the pump head, and the
injector's head loss enters it too.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from engine import kernels as K
from modules.common import (page_header, sub_header, section, cards, banner, note,
                            caption, save, stage_guard, goto, dev_panel, context_strip)

HAZARD_ICON = {"slight": "🟢", "moderate": "🟡", "severe": "🔴", "unknown": "⚪"}
INJECTORS = ["Venturi", "Hydraulic (water-driven) pump", "Electric dosing pump",
             "Differential tank"]
INJ_LOSS = {"Venturi": 6.0, "Hydraulic (water-driven) pump": 2.0,
            "Electric dosing pump": 0.0, "Differential tank": 3.0}


# FAO-29 (Ayers & Westcot 1985): TDS (mg/L) ~ 640 x ECw (dS/m) for ECw < 5 dS/m.
TDS_PER_ECW = 640.0


def show(ctx):
    S = ctx["S"]
    page_header("Water Quality & Filtration",
                "Clogging hazard from the water analysis, the filtration train it "
                "requires, the chemical maintenance schedule, and the fertigation "
                "injector. Both the filter differential and the injector loss are "
                "carried into the pump head.")
    if not stage_guard(S, "emitter", "Emitter Selection", page_key="emitter"):
        return
    context_strip(S)
    setup, em = S["setup"], S["emitter"]
    op = S.get("operation") or {}
    prev = S.get("quality", {})
    prevf = S.get("fertigation", {})

    tabs = st.tabs(["🧪 Clogging Hazard", "🔽 Filtration", "🧴 Chemical Maintenance",
                    "🧬 Fertigation"])

    with tabs[0]:
        sub_header("Clogging Hazard")
        banner("warn", "Hazard thresholds follow the Bucks &amp; Nakayama classification as "
                       "reproduced in FAO and ASABE drip literature. <b>Verify them against "
                       "the original source</b> before quoting them in an official document.")
        c1, c2, c3 = st.columns(3)
        with c1:
            tss = st.number_input("Suspended solids (mg/L)", 0.0, 5000.0,
                                  float(prev.get("tss", 40.0)), 5.0)
            ecw = float((S.get("water") or {}).get("ecw", 0.0) or 0.0)
            tds_from_ecw = round(TDS_PER_ECW * ecw / 25.0) * 25.0 if ecw > 0 else 450.0
            tds = st.number_input("Dissolved solids TDS (mg/L)", 0.0, 20000.0,
                                  float(prev.get("tds", tds_from_ecw)), 25.0,
                                  help="Defaults to 640 × ECw, the FAO-29 conversion for "
                                       "ECw below 5 dS/m. Enter the laboratory value.")
            ph = st.number_input("pH", 3.0, 11.0, float(prev.get("ph", 7.8)), 0.1)
        with c2:
            fe = st.number_input("Iron (mg/L)", 0.0, 50.0, float(prev.get("fe", 0.15)), 0.05)
            mn = st.number_input("Manganese (mg/L)", 0.0, 50.0, float(prev.get("mn", 0.05)), 0.05)
        with c3:
            h2s = st.number_input("Hydrogen sulphide (mg/L)", 0.0, 50.0,
                                  float(prev.get("h2s", 0.1)), 0.05)
            bact = st.number_input("Bacterial population (no./mL)", 0.0, 1e7,
                                   float(prev.get("bact", 8000.0)), 1000.0)
        wq = {"suspended_solids_mg_l": tss, "dissolved_solids_mg_l": tds, "ph": ph,
              "iron_mg_l": fe, "manganese_mg_l": mn, "hydrogen_sulphide_mg_l": h2s,
              "bacterial_population_per_ml": bact}
        if ecw > 0 and abs(tds - TDS_PER_ECW * ecw) > 0.25 * TDS_PER_ECW * ecw:
            banner("warn", f"TDS {tds:,.0f} mg/L does not agree with the ECw of {ecw:g} dS/m "
                           f"entered on Crop Water Requirements (≈ {TDS_PER_ECW * ecw:,.0f} "
                           "mg/L at 640 mg/L per dS/m, FAO-29). One of the two is probably "
                           "wrong: the leaching requirement and the clogging hazard should "
                           "come from the same water analysis.")
        hz = K.clogging_hazard(wq)
        kind = {"slight": "ok", "moderate": "warn", "severe": "bad",
                "unknown": "accent"}[hz["overall"]]
        banner(kind, f"{HAZARD_ICON[hz['overall']]} Governing hazard: "
                     f"<b>{hz['overall'].upper()}</b> — the worst single parameter governs "
                     "the filtration grade and the chemical schedule.")
        labels = {"suspended_solids_mg_l": "Suspended solids",
                  "dissolved_solids_mg_l": "Dissolved solids", "ph": "pH",
                  "iron_mg_l": "Iron", "manganese_mg_l": "Manganese",
                  "hydrogen_sulphide_mg_l": "Hydrogen sulphide",
                  "bacterial_population_per_ml": "Bacterial population"}
        st.dataframe(pd.DataFrame([{
            "Parameter": labels.get(k, k), "Value": it["value"], "Unit": it["unit"],
            "Slight ≤": K.CLOGGING_CRITERIA[k]["slight"],
            "Moderate ≤": K.CLOGGING_CRITERIA[k]["moderate"],
            "Class": HAZARD_ICON[it["class"]] + " " + it["class"]}
            for k, it in hz["per_parameter"].items()]), hide_index=True, width="stretch")
        if hz.get("corrosion_note"):
            banner("warn", hz["corrosion_note"])

    rec = K.recommend_filtration(setup["source"], hz["overall"], em["passage"])
    sched = K.chemical_maintenance_schedule(hz)
    with tabs[1]:
        sub_header("Filtration")
        grade = rec["filtration_grade"]
        cards([("Emitter passage", f"{em['passage']:.2f}", "mm", "neutral"),
               ("Filtration aperture", f"{grade['aperture_micron']:.0f}", "µm", "accent"),
               ("Approx. mesh", f"{grade['mesh']}", "", "neutral"),
               ("Safety divisor", f"1/{grade['divisor']:.0f}", "", "neutral")])
        st.markdown("**Recommended filtration train** (in flow order):")
        for i, t in enumerate(rec["train"], 1):
            st.markdown(f"{i}. {t}")
        for n in rec["notes"]:
            st.caption("• " + n)
        c1, c2 = st.columns(2)
        with c1:
            filt_clean = st.number_input("Filter head loss, clean (m)", 0.0, 30.0,
                                         float(prev.get("filt_clean", 3.0)), 0.5)
        with c2:
            filt_dirty = st.number_input("Additional allowance before backflush (m)", 0.0,
                                         30.0, float(prev.get("filt_dirty", 4.0)), 0.5)
        caption("Sizing the pump on the clean-filter figure alone guarantees the system "
                "drops below design pressure before every backflush. The allowance is part "
                "of the design, not a contingency.")

    with tabs[2]:
        sub_header("Chemical Maintenance Schedule")
        st.dataframe(pd.DataFrame(sched), hide_index=True, width="stretch")
        caption("Doses are indicative practice ranges. Confirm against the emitter "
                "manufacturer's chemical-compatibility statement and Egyptian regulations "
                "before application. <b>Never inject acid and chlorine simultaneously.</b>")

    with tabs[3]:
        sub_header("Fertigation")
        area_shift = op.get("area_shift", setup["area_ha"])
        t_set = op.get("t_set", 2.0)
        c1, c2, c3 = st.columns(3)
        with c1:
            dose = st.number_input("Fertiliser dose per application (kg/ha)", 0.0, 1000.0,
                                   float(prevf.get("dose", 25.0)), 1.0)
        with c2:
            stock = st.number_input("Stock solution concentration (kg/L)", 0.01, 2.0,
                                    float(prevf.get("stock", 0.4)), 0.01)
        with c3:
            inj_time = st.number_input("Injection time per shift (h)", 0.1, 24.0,
                                       float(prevf.get("inj_time", min(2.0, t_set))), 0.1)
        injector = st.selectbox("Injector type", INJECTORS, index=prevf.get("inj_idx", 0))
        inj_loss = st.number_input("Head loss across the injector (m)", 0.0, 40.0,
                                   float(prevf.get("inj_loss", INJ_LOSS[injector])
                                         if prevf.get("injector") == injector
                                         else INJ_LOSS[injector]), 0.5)
        fres = K.fertigation_injection_rate(dose, area_shift, stock, inj_time)
        cards([("Fertiliser per shift", f"{fres['total_fertiliser_kg']:.1f}", "kg", "neutral"),
               ("Stock volume", f"{fres['stock_volume_l']:.0f}", "L", "neutral"),
               ("Injection rate", f"{fres['injection_rate_lph']:.0f}", "L/h", "accent"),
               ("Injector head loss", f"{inj_loss:.1f}", "m", "warn" if inj_loss >= 5 else "ok")])
        if injector == "Venturi":
            note("A venturi is cheap and needs no power, but it takes a substantial pressure "
                 "drop and its rate varies with system pressure. On a system already tight "
                 "on head, a hydraulic or electric injector is usually the better choice.")
        caption(f"Flush with clean water for at least 15–30 minutes after injection. At the "
                f"design set time of {t_set:.2f} h, inject in the middle of the set.")

    if st.button("💾 Save", type="primary", key="save_quality"):
        save(S, "quality", {"tss": tss, "tds": tds, "ph": ph, "fe": fe, "mn": mn,
                            "h2s": h2s, "bact": bact, "hazard": hz, "filtration": rec,
                            "schedule": sched, "filt_clean": filt_clean,
                            "filt_dirty": filt_dirty})
        save(S, "fertigation", {"dose": dose, "stock": stock, "inj_time": inj_time,
                                "injector": injector, "inj_idx": INJECTORS.index(injector),
                                "inj_loss": inj_loss, **fres})
        S.pop("hydraulic", None)
        st.success("✅ Water quality, filtration and fertigation saved.")
        goto("hydraulic")
    dev_panel(S, "quality")
