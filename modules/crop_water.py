"""
Crop Water Requirements — Climate Data, ET₀ Calculation, Crop Coefficients,
Irrigation Requirements: OpenIrri's four tabs.

Two routes, both kept:

* Monthly (the OpenIrri route). Twelve months of station weather, or twelve
  published ET₀ values, a Kc curve on a planting date, and the demand month
  by month. The design month is FOUND as the month of highest localised
  daily ETc, and the season volume is SUMMED.
* Peak month only (the v1 route), for when only the design figure is known.
  The season volume is then an extrapolation and the pages that use it say so.
"""

from __future__ import annotations

import html
import io

import pandas as pd
import streamlit as st

from engine import climate as C
from engine import kernels as K
from modules import plots as PL
from modules.common import (page_header, sub_header, section, cards, banner, note,
                            caption, save, stage_guard, goto, dev_panel, context_strip,
                            stable_editor, reset_editor)

METHODS = ["Monthly weather (Penman–Monteith)", "Monthly ET₀ given (CLIMWAT / station)",
           "Peak month only"]
WEATHER_COLS = ["Tmax (°C)", "Tmin (°C)", "RH mean (%)", "Wind u2 (m/s)",
                "Sunshine n (h)", "Rs (MJ/m²/d)", "Rain (mm/month)"]


CROP_KEYS = ("kc_curve", "kc", "gc", "zr", "p", "ece", "ece_max")
SOIL_KEYS = ("fc", "wp")


def _S_water(S):
    """
    The saved crop-water inputs, minus those that belong to a crop or soil the
    project no longer has. v2.0.0 kept the old crop's Kc curve, root depth,
    depletion fraction and salinity limits after the crop was changed on
    Home, so an olive design silently ran on tomato coefficients.
    """
    w = dict(S.get("water") or {})
    setup = S.get("setup") or {}
    if w.get("crop_name") and w["crop_name"] != setup.get("crop", {}).get("name"):
        for k in CROP_KEYS:
            w.pop(k, None)
    if w.get("soil_name") and w["soil_name"] != setup.get("soil", {}).get("name"):
        for k in SOIL_KEYS:
            w.pop(k, None)
    return w


def _crop_changed_notice(S):
    w = S.get("water") or {}
    setup = S["setup"]
    msgs = []
    if w.get("crop_name") and w["crop_name"] != setup["crop"]["name"]:
        msgs.append(f"the crop changed from <b>{html.escape(w['crop_name'])}</b> to "
                    f"<b>{html.escape(setup['crop']['name'])}</b> — Kc curve, root depth, "
                    "depletion fraction and salinity limits are reset to the new crop's "
                    "defaults")
    if w.get("soil_name") and w["soil_name"] != setup["soil"]["name"]:
        msgs.append(f"the soil changed from <b>{html.escape(w['soil_name'])}</b> to "
                    f"<b>{html.escape(setup['soil']['name'])}</b> — FC and WP are reset")
    if msgs:
        banner("warn", "Since this page was saved, " + "; ".join(msgs) + ". Review and Save.")


def show(ctx):
    S = ctx["S"]
    page_header("Crop Water Requirements",
                "Calculate reference evapotranspiration (ET<sub>0</sub>) and crop water "
                "requirements using the FAO Penman-Monteith equation and the crop "
                "coefficient approach, reduced for localised (drip) irrigation by the "
                "Keller &amp; Bliesner factor.")
    if not stage_guard(S, "setup", "Project Setup (Home)", page_key="home"):
        return
    context_strip(S)
    _crop_changed_notice(S)
    crop_name = S["setup"]["crop"]["name"]
    if st.session_state.get("kc_draft_crop") != crop_name:
        # The Kc draft belongs to one crop; a new crop starts from its own table.
        if st.session_state.get("kc_draft_crop") is not None or \
                (S.get("water") or {}).get("crop_name") not in (None, crop_name):
            st.session_state.pop("kc_draft", None)
        st.session_state["kc_draft_crop"] = crop_name
    tabs = st.tabs(["Climate Data", "ET₀ Calculation", "Crop Coefficients",
                    "Irrigation Requirements"])
    with tabs[0]:
        climate_tab(S)
    with tabs[1]:
        et0_tab(S)
    with tabs[2]:
        kc_tab(S)
    with tabs[3]:
        requirement_tab(S)
    dev_panel(S, "water")


# ---------------------------------------------------------------- climate ---

def _latitude_default(S) -> float:
    lay = S.get("layout") or {}
    if lay.get("centre"):
        return float(lay["centre"][0])
    return float(_S_water(S).get("latitude", 30.0))


def climate_tab(S):
    sub_header("Climate Data Input")
    cw = st.session_state.setdefault("cw_draft", dict(_S_water(S).get("climate", {})))
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("#### Location Parameters")
        lat = st.number_input("Latitude (decimal degrees)", -90.0, 90.0,
                              float(cw.get("latitude", _latitude_default(S))), 0.01,
                              help="Positive north. Taken from the field boundary when "
                                   "one was drawn.")
        st.info(f"Altitude: {S['setup'].get('altitude', 0):.0f} m (from project settings)")
    with col2:
        st.markdown("#### Data Input Method")
        method = st.radio("Data Input Method", METHODS,
                          index=METHODS.index(cw.get("method", METHODS[0])),
                          label_visibility="collapsed")
    cw["latitude"] = lat
    cw["method"] = method

    if method == METHODS[2]:
        _peak_only_inputs(S, cw)
        return

    st.markdown("#### Monthly Climate Data")
    caption("Enter or paste station values for all twelve months, or upload a CSV. "
            "No climate is bundled with the program: an ET₀ computed on typical values "
            "for somewhere else looks exactly like one computed on your station's, so "
            "the table starts empty rather than pre-filled.")
    cols = (WEATHER_COLS if method == METHODS[0] else ["ET₀ (mm/day)", "Rain (mm/month)"])
    ekey = f"cw_table_{METHODS.index(method)}"

    def make(records=None):
        base = pd.DataFrame(records or cw.get("table") or [{}] * 12)
        for c in cols:
            if c not in base.columns:
                base[c] = None
        base = base[cols].astype("float64")
        base.index = C.MONTHS
        return base

    up = st.file_uploader("Upload CSV (Month, Tmax, Tmin, RH, Wind, Sun or Rs, Rain, "
                          "or Month, ET0, Rain)", type=["csv"], key="cw_csv")
    if up is not None and st.session_state.get("_cw_csv_done") != (up.name, up.size):
        try:
            reset_editor(ekey, make(_parse_csv(up.getvalue(), method).to_dict("records")))
            st.session_state["_cw_csv_done"] = (up.name, up.size)
            st.success(f"✅ Read {up.name}")
        except Exception as exc:                   # noqa: BLE001
            banner("bad", f"Could not read the CSV: {html.escape(str(exc))}")

    ed = stable_editor(ekey, make, width="stretch", num_rows="fixed")
    cw["table"] = ed.reset_index(drop=True).to_dict("records")

    tmpl = pd.DataFrame({"Month": C.MONTHS, **{c: [""] * 12 for c in cols}})
    st.download_button("📄 Download a blank CSV template", tmpl.to_csv(index=False),
                       file_name="IRRI-DRIP_climate_template.csv", mime="text/csv",
                       key="cw_tmpl")
    if method == METHODS[0]:
        caption("Radiation: give <b>sunshine hours n</b> (Angström, FAO-56 Eq. 35) or "
                "<b>measured Rs</b> for each month. Rs takes precedence where both are given. "
                "Wind is at 2 m; convert a 10 m reading with FAO-56 Eq. 47.")


def _peak_only_inputs(S, cw):
    st.markdown("#### Peak-month climate")
    mode = st.radio("Climate input", ["Enter ET₀ directly", "Compute ET₀ from weather"],
                    index=0 if cw.get("peak_mode", "Enter").startswith("Enter") else 1,
                    horizontal=True, key="cw_peak_mode")
    cw["peak_mode"] = mode
    if mode == "Enter ET₀ directly":
        cw["et0_peak"] = st.number_input("Peak-month ET₀ (mm/day)", 0.1, 25.0,
                                         float(cw.get("et0_peak", 7.0)), 0.1)
        cw["weather"] = None
    else:
        c1, c2, c3 = st.columns(3)
        w = cw.get("weather") or {}
        with c1:
            tmax = st.number_input("T max (°C)", value=float(w.get("tmax", 36.0)), step=0.5)
            tmin = st.number_input("T min (°C)", value=float(w.get("tmin", 22.0)), step=0.5)
        with c2:
            rh = st.number_input("Mean relative humidity (%)", 1.0, 100.0,
                                 float(w.get("rh", 45.0)), 1.0)
            wind = st.number_input("Wind speed at 2 m (m/s)", 0.0, 20.0,
                                   float(w.get("wind", 2.0)), 0.1)
        with c3:
            rn = st.number_input("Net radiation Rn (MJ/m²/day)", 0.0, 40.0,
                                 float(w.get("rn", 18.0)), 0.5)
        cw["weather"] = {"tmax": tmax, "tmin": tmin, "rh": rh, "wind": wind, "rn": rn}
        cw["et0_peak"] = K.et0_penman_monteith(tmax, tmin, rh, wind, rn,
                                               S["setup"]["altitude"])
        st.success(f"Computed ET₀ = **{cw['et0_peak']:.2f} mm/day**")
    cw["season_days"] = st.number_input("Irrigation season length (days)", 1, 365,
                                        int(cw.get("season_days", 150)), 5,
                                        help="Used only to extrapolate a season volume "
                                             "on this route")


def _parse_csv(data: bytes, method: str) -> pd.DataFrame:
    df = pd.read_csv(io.BytesIO(data))
    low = {c.lower().strip(): c for c in df.columns}

    def pick(*names):
        for n in names:
            for k, c in low.items():
                if k.startswith(n):
                    return df[c]
        return None
    if len(df) != 12:
        raise ValueError(f"expected 12 monthly rows, found {len(df)}")
    rain = pick("rain", "precip", "p ")
    if method == METHODS[0]:
        out = pd.DataFrame({
            "Tmax (°C)": pick("tmax", "t max", "max"),
            "Tmin (°C)": pick("tmin", "t min", "min"),
            "RH mean (%)": pick("rh", "humid"),
            "Wind u2 (m/s)": pick("wind", "u2"),
            "Sunshine n (h)": pick("sun", "n "),
            "Rs (MJ/m²/d)": pick("rs", "rad"),
            "Rain (mm/month)": rain,
        })
    else:
        out = pd.DataFrame({"ET₀ (mm/day)": pick("et0", "eto", "et₀"),
                            "Rain (mm/month)": rain})
    return out


def _monthly_rows(cw):
    """Engine rows from the editor table, or an explanation of what is missing."""
    tbl = cw.get("table") or []
    if len(tbl) != 12:
        return None, "Fill the twelve months on the Climate Data tab."
    rows = []
    for i, r in enumerate(tbl):
        if cw["method"] == METHODS[1]:
            v = r.get("ET₀ (mm/day)")
            if v is None or pd.isna(v):
                return None, f"{C.MONTHS[i]}: ET₀ is missing."
            rows.append({"et0": float(v)})
        else:
            def g(k):
                v = r.get(k)
                return None if v is None or pd.isna(v) else float(v)
            rows.append({"tmax": g("Tmax (°C)"), "tmin": g("Tmin (°C)"),
                         "rh": g("RH mean (%)"), "wind": g("Wind u2 (m/s)"),
                         "sun": g("Sunshine n (h)"), "rs": g("Rs (MJ/m²/d)")})
    rain = []
    for r in tbl:
        v = r.get("Rain (mm/month)")
        rain.append(0.0 if v is None or pd.isna(v) else float(v))
    return (rows, rain), ""


def _et0_result(S):
    cw = st.session_state.get("cw_draft") or {}
    if cw.get("method") == METHODS[2]:
        return {"peak_only": True, "et0_peak": cw.get("et0_peak")}, ""
    got, msg = _monthly_rows(cw)
    if got is None:
        return None, msg
    rows, rain = got
    try:
        et0 = C.et0_monthly(rows, float(cw["latitude"]), float(S["setup"]["altitude"]))
    except ValueError as exc:
        return None, str(exc)
    return {"peak_only": False, "et0_rows": et0, "rain": rain}, ""


def et0_tab(S):
    sub_header("Reference Evapotranspiration (ET₀)")
    res, msg = _et0_result(S)
    if res is None:
        st.info(f"💡 {msg}")
        return
    if res["peak_only"]:
        cards([("Peak-month ET₀", f"{res['et0_peak']:.2f}", "mm/day", "accent")])
        caption("Peak-month route: a single design value, no monthly curve.")
        return
    rows = res["et0_rows"]
    st.plotly_chart(PL.monthly_et0(rows), width="stretch", key="et0_chart")
    df = pd.DataFrame([{
        "Month": r["month"], "ET₀ (mm/day)": round(r["et0"], 2),
        "ET₀ (mm/month)": round(r["et0"] * C.DAYS_IN_MONTH[i], 1),
        "Rn (MJ/m²/d)": None if r.get("rn") is None else round(r["rn"], 2),
        "G (MJ/m²/d)": None if r.get("g") is None else round(r["g"], 2),
        "Source": r["source"]} for i, r in enumerate(rows)])
    st.dataframe(df, hide_index=True, width="stretch")
    annual = sum(r["et0"] * C.DAYS_IN_MONTH[i] for i, r in enumerate(rows))
    cards([("Annual ET₀", f"{annual:,.0f}", "mm/yr", "accent"),
           ("Highest month", max(rows, key=lambda r: r["et0"])["month"], "", "neutral"),
           ("Highest ET₀", f"{max(r['et0'] for r in rows):.2f}", "mm/day", "neutral")])
    if any(r["source"] == "Penman-Monteith" for r in rows):
        caption("FAO-56 Penman–Monteith, monthly step: Rn from Eq. 38–40 with Angström "
                "Rs (Eq. 35, a<sub>s</sub> = 0.25, b<sub>s</sub> = 0.50) unless Rs was "
                "measured; soil heat flux G by Eq. 43 from the neighbouring months.")


# -------------------------------------------------------------------- Kc ---

def kc_tab(S):
    sub_header("Crop Coefficients")
    crop = S["setup"]["crop"]
    prev = _S_water(S)
    kd = st.session_state.setdefault("kc_draft", dict(prev.get("kc_curve", {})))
    c1, c2, c3 = st.columns(3)
    with c1:
        kd["kc_ini"] = st.number_input("Kc ini", 0.1, 1.5, float(kd.get("kc_ini", crop["kc_ini"])), 0.05)
    with c2:
        kd["kc_mid"] = st.number_input("Kc mid", 0.1, 1.5, float(kd.get("kc_mid", crop["kc_mid"])), 0.05)
    with c3:
        kd["kc_end"] = st.number_input("Kc end", 0.1, 1.5, float(kd.get("kc_end", crop["kc_end"])), 0.05)
    st.markdown("#### Growth stages (days)")
    caption("Generic placeholders. Take the stage lengths for your crop and region from "
            "FAO-56 Table 11 or from station records — they move the peak month.")
    c = st.columns(4)
    st_def = kd.get("stages", [30, 40, 50, 30])
    stages = [c[i].number_input(lbl, 1, 250, int(st_def[i]), 1, key=f"kc_st{i}")
              for i, lbl in enumerate(["Initial", "Development", "Mid-season", "Late"])]
    kd["stages"] = stages
    c1, c2, c3 = st.columns(3)
    with c1:
        kd["plant_month"] = st.selectbox("Planting month", list(range(1, 13)),
                                         index=int(kd.get("plant_month", 3)) - 1,
                                         format_func=lambda m: C.MONTHS[m - 1])
    with c2:
        kd["plant_day"] = st.number_input("Planting day", 1, 28, int(kd.get("plant_day", 1)), 1)
    with c3:
        kd["gc"] = st.slider("Ground cover fraction at peak", 0.05, 1.0,
                             float(kd.get("gc", prev.get("gc", crop["ground_cover"]))), 0.05,
                             help="Enters Kr = GC/0.85 (Keller & Bliesner)")
    st.plotly_chart(PL.kc_curve(stages, kd["kc_ini"], kd["kc_mid"], kd["kc_end"]),
                    width="stretch", key="kc_chart")
    kr = K.ground_cover_reduction_factor(kd["gc"])
    cards([("Season length", f"{sum(stages)}", "days", "neutral"),
           ("Kr localisation", f"{kr:.2f}", "", "accent"),
           ("Kc mid × Kr", f"{kd['kc_mid'] * kr:.2f}", "", "neutral")])


# ------------------------------------------------------------ requirement ---

def requirement_tab(S):
    sub_header("Irrigation Requirements")
    setup = S["setup"]
    crop, soil = setup["crop"], setup["soil"]
    prev = _S_water(S)
    kd = st.session_state.get("kc_draft") or {}
    if not kd:
        st.info("💡 Open the Crop Coefficients tab once to set the Kc curve.")
        kd = st.session_state.setdefault("kc_draft", {
            "kc_ini": crop["kc_ini"], "kc_mid": crop["kc_mid"], "kc_end": crop["kc_end"],
            "stages": [30, 40, 50, 30], "plant_month": 3, "plant_day": 1,
            "gc": crop["ground_cover"]})

    st.markdown("#### Soil water and application")
    c1, c2, c3 = st.columns(3)
    with c1:
        fc = st.number_input("Field capacity (mm/m)", 20.0, 500.0,
                             float(prev.get("fc", soil["fc_mm_per_m"])), 5.0)
        wp = st.number_input("Wilting point (mm/m)", 5.0, 400.0,
                             float(prev.get("wp", soil["wp_mm_per_m"])), 5.0)
    with c2:
        zr = st.number_input("Effective root depth (m)", 0.05, 3.0,
                             float(prev.get("zr", crop["root_depth_m"])), 0.05)
        p = st.slider("Allowable depletion fraction p", 0.05, 0.80,
                      float(prev.get("p", crop["depletion_p"])), 0.05)
    with c3:
        ea = st.slider("Application efficiency Ea", 0.70, 0.98, float(prev.get("ea", 0.90)), 0.01)
        rain_method = st.selectbox("Effective rainfall", ["usda", "fixed", "none"],
                                   index=["usda", "fixed", "none"].index(
                                       prev.get("rain_method", "none")),
                                   format_func=lambda m: {"usda": "USDA-SCS (CROPWAT)",
                                                          "fixed": "80 % of rainfall",
                                                          "none": "Ignore (design)"}[m])
    c1, c2, c3 = st.columns(3)
    with c1:
        ecw = st.number_input("Irrigation water salinity ECw (dS/m)", 0.0, 20.0,
                              float(prev.get("ecw", 1.0)), 0.1)
    with c2:
        ece = st.number_input("Crop ECe threshold (dS/m)", 0.1, 30.0,
                              float(prev.get("ece", crop["ece_threshold_ds_m"])), 0.1,
                              help="Soil salinity at which yield decline BEGINS "
                                   "(FAO-29 Table 4, 100 % column).")
    with c3:
        ece_max = st.number_input(
            "Crop max ECe, zero yield (dS/m)", 0.0, 60.0,
            float(prev.get("ece_max", crop.get("ece_max_ds_m") or 0.0)), 0.1,
            help="Soil salinity at which yield falls to ZERO (FAO-29 Table 4, 0 % "
                 "column). The drip leaching requirement is ECw / (2 x max ECe). "
                 "Leave 0 when it is not known: FAO-29 eq. (9) is used on the threshold.")
    if ece_max > 0 and ece_max <= ece:
        banner("bad", "Max ECe (zero yield) must be greater than the threshold ECe. "
                      "Check both values against FAO-29 Table 4.")
    lr, lr_method = _leaching(ecw, ece, ece_max)
    kr = K.ground_cover_reduction_factor(kd["gc"])

    res, msg = _et0_result(S)
    if res is None:
        st.info(f"💡 {msg}")
        return
    if res["peak_only"]:
        et0 = float(res["et0_peak"])
        kc = float(kd["kc_mid"])
        etc = K.etc_localised(et0, kc, kr)
        cw = st.session_state.get("cw_draft") or {}
        season_days = int(cw.get("season_days", 150))
        # Same gross-depth rule as every other page (LR above 0.1 inflates it).
        season_vol = K.gross_depth(etc, ea, lr) * setup["area_ha"] * 10.0 * season_days
        monthly = None
        peak_month = "peak (given)"
        banner("warn", "Peak-month route: the season volume below is the PEAK demand "
                       f"extrapolated over {season_days} days, which overstates it. Use a "
                       "monthly table for a real seasonal account.")
    else:
        km = C.kc_monthly(int(kd["plant_month"]), int(kd["plant_day"]), kd["kc_ini"],
                          kd["kc_mid"], kd["kc_end"], tuple(kd["stages"]))
        monthly = C.monthly_requirement(res["et0_rows"], km, kr, res["rain"], ea, lr,
                                        setup["area_ha"], rain_method)
        et0 = monthly["peak_et0_mm_d"]
        kc = monthly["peak_kc"]
        etc = monthly["peak_etc_mm_d"]
        season_vol = monthly["season_volume_m3"]
        peak_month = monthly["peak_month"]
        st.plotly_chart(PL.monthly_requirement(monthly["rows"]), width="stretch",
                        key="req_chart")
        df = pd.DataFrame([{"Month": r["month"], "Crop days": r["days"],
                            "ET₀ (mm/d)": round(r["et0"], 2), "Kc": round(r["kc"], 2),
                            "ETc,loc (mm/d)": round(r["etc_loc_mm_d"], 2),
                            "Peff (mm)": round(r["peff_mm"], 1),
                            "Net (mm)": round(r["net_mm"], 1),
                            "Gross (mm)": round(r["gross_mm"], 1),
                            "Volume (m³)": round(r["volume_m3"], 0)}
                           for r in monthly["rows"]])
        st.dataframe(df, hide_index=True, width="stretch")

    section("Design values")
    cards([
        ("Design month", peak_month, "", "accent"),
        ("ET₀ in design month", f"{et0:.2f}", "mm/day", "neutral"),
        ("ETc,loc peak", f"{etc:.2f}", "mm/day", "accent"),
        ("Leaching requirement", f"{lr*100:.1f}", "%",
         "ok" if lr <= 0.10 else ("warn" if lr < K.LR_UNSUITABLE else "bad")),
    ])
    cards([
        ("Kc in design month", f"{kc:.2f}", "", "neutral"),
        ("Kr localisation", f"{kr:.2f}", "", "neutral"),
        ("Season gross volume", f"{season_vol:,.0f}", "m³", "neutral"),
        ("Per hectare", f"{season_vol / max(setup['area_ha'], 1e-9):,.0f}", "m³/ha", "neutral"),
    ])
    if kr < 1.0:
        note(f"Ground cover is {int(kd['gc']*100)} %, so Kr = {kr:.2f} reduces the demand "
             f"from {et0*kc:.2f} to <b>{etc:.2f} mm/day</b>. A sprinkler kernel would "
             "return the unreduced value and oversize the whole system.")
    lr_class, lr_msg = K.leaching_verdict(lr)
    if lr_class != "none":
        kind = {"absorbed": "ok", "applied": "warn", "severe": "warn",
                "unsuitable": "bad"}[lr_class]
        banner(kind, f"Leaching requirement {lr*100:.1f} % — {html.escape(lr_method)}. "
                     f"{lr_msg}")

    if st.button("💾 Save", type="primary", key="save_water"):
        cw = st.session_state.get("cw_draft") or {}
        save(S, "water", {
            "mode_idx": 0 if res["peak_only"] else 1,
            "method": cw.get("method"),
            "climate": {k: v for k, v in cw.items()},
            "kc_curve": dict(kd),
            "et0": et0, "weather": cw.get("weather"), "kc": kc, "gc": kd["gc"],
            "kr": kr, "etc": etc, "fc": fc, "wp": wp, "zr": zr, "p": p, "ea": ea,
            "crop_name": crop["name"], "soil_name": soil["name"],
            "ecw": ecw, "ece": ece, "ece_max": ece_max, "lr": lr, "lr_method": lr_method, "rain_method": rain_method,
            "peak_month": peak_month, "season_volume_m3": season_vol,
            "season_days": (monthly["season_days"] if monthly else
                            int((st.session_state.get("cw_draft") or {}).get("season_days", 150))),
            "monthly": monthly["rows"] if monthly else None,
            "latitude": cw.get("latitude"),
        })
        st.success("✅ Crop water requirement saved.")
        goto("emitter")


def _leaching(ecw: float, ece: float, ece_max: float) -> tuple[float, str]:
    """The leaching requirement and a one-line statement of how it was computed."""
    if ece_max > 0:
        return (K.leaching_requirement(ecw, ece_max),
                f"drip high-frequency form ECw / (2·max ECe) = {ecw:g} / (2 × {ece_max:g})")
    return (K.leaching_requirement_fao29(ecw, ece),
            f"FAO-29 eq. (9) ECw / (5·ECe − ECw) on the threshold {ece:g} dS/m "
            "(no zero-yield ECe given for this crop)")
