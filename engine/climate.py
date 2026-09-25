"""
Monthly climate, reference evapotranspiration and the crop-coefficient curve.

UI-free, like the rest of engine/. Everything here follows FAO Irrigation and
Drainage Paper 56 (Allen, Pereira, Raes and Smith, 1998); equation numbers in
the docstrings are FAO-56's.

Why a monthly module when the design needs one peak figure
----------------------------------------------------------
The hydraulic design is sized on the PEAK month, and version 1 asked for that
one figure directly. Two things were lost by doing so:

1. Which month is the peak. It depends on the planting date as much as on the
   weather: a late-planted crop reaches mid-season in a hotter month. A single
   typed ET0 with a mid-season Kc silently assumes the two coincide.
2. The season volume. The energy and water accounts on the pump and cost pages
   multiplied the peak daily demand by the season length, which overstates
   both — no crop runs at its peak for 150 days.

This module computes the month-by-month demand so the peak is found, not
assumed, and the seasonal volume is summed rather than extrapolated.
"""

from __future__ import annotations

import math

from . import kernels as K

__all__ = [
    "MONTHS", "mid_month_doy", "extraterrestrial_radiation", "daylight_hours",
    "solar_radiation_from_sunshine", "clear_sky_radiation", "net_longwave",
    "net_radiation", "soil_heat_flux_monthly", "et0_monthly",
    "kc_daily", "kc_monthly", "effective_rainfall", "monthly_requirement",
]

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
DAYS_IN_MONTH = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]

GSC = 0.0820            # solar constant, MJ m-2 min-1
SIGMA = 4.903e-9        # Stefan-Boltzmann, MJ K-4 m-2 day-1
ALBEDO = 0.23           # grass reference surface


def mid_month_doy(month: int) -> int:
    """Day of year at the middle of month 1..12. FAO-56 Annex 2 convention."""
    if not 1 <= int(month) <= 12:
        raise ValueError(f"month must be 1..12, got {month}")
    return int(30.4 * month - 15)


def _solar_geometry(lat_deg: float, doy: int) -> tuple[float, float, float, float]:
    phi = math.radians(lat_deg)
    dr = 1.0 + 0.033 * math.cos(2.0 * math.pi * doy / 365.0)          # Eq. 23
    delta = 0.409 * math.sin(2.0 * math.pi * doy / 365.0 - 1.39)       # Eq. 24
    x = -math.tan(phi) * math.tan(delta)
    x = max(-1.0, min(1.0, x))       # polar day / night, outside Egypt anyway
    ws = math.acos(x)                                                   # Eq. 25
    return phi, dr, delta, ws


def extraterrestrial_radiation(lat_deg: float, doy: int) -> float:
    """Ra, MJ m-2 day-1. FAO-56 Eq. 21."""
    phi, dr, delta, ws = _solar_geometry(lat_deg, doy)
    return (24.0 * 60.0 / math.pi) * GSC * dr * (
        ws * math.sin(phi) * math.sin(delta)
        + math.cos(phi) * math.cos(delta) * math.sin(ws))


def daylight_hours(lat_deg: float, doy: int) -> float:
    """N, hours. FAO-56 Eq. 34."""
    return 24.0 / math.pi * _solar_geometry(lat_deg, doy)[3]


def solar_radiation_from_sunshine(n_hours: float, N_hours: float, ra: float,
                                  a_s: float = 0.25, b_s: float = 0.50) -> float:
    """Rs from sunshine duration, Angstrom. FAO-56 Eq. 35."""
    if N_hours <= 0:
        return 0.0
    ratio = max(0.0, min(1.0, n_hours / N_hours))
    return (a_s + b_s * ratio) * ra


def clear_sky_radiation(ra: float, altitude_m: float) -> float:
    """Rso, MJ m-2 day-1. FAO-56 Eq. 37."""
    return (0.75 + 2.0e-5 * altitude_m) * ra


def net_longwave(t_max_c: float, t_min_c: float, ea_kpa: float,
                 rs: float, rso: float) -> float:
    """Rnl, MJ m-2 day-1. FAO-56 Eq. 39."""
    tk4 = ((t_max_c + 273.16) ** 4 + (t_min_c + 273.16) ** 4) / 2.0
    ratio = min(1.0, rs / rso) if rso > 0 else 1.0
    return SIGMA * tk4 * (0.34 - 0.14 * math.sqrt(max(ea_kpa, 0.0))) * (
        1.35 * ratio - 0.35)


def net_radiation(lat_deg: float, doy: int, t_max_c: float, t_min_c: float,
                  rh_mean_pct: float, altitude_m: float,
                  sunshine_h: float | None = None,
                  rs_mj: float | None = None) -> dict:
    """
    Rn = Rns - Rnl, with every intermediate term returned.

    Give either the sunshine duration (the usual station record in Egypt) or
    the measured solar radiation. With neither, this raises rather than
    estimating Rs: an ET0 computed on an invented radiation term looks exactly
    like one computed on a measured one.
    """
    ra = extraterrestrial_radiation(lat_deg, doy)
    N = daylight_hours(lat_deg, doy)
    if rs_mj is not None and rs_mj > 0:
        rs = float(rs_mj)
        source = "measured Rs"
    elif sunshine_h is not None:
        rs = solar_radiation_from_sunshine(sunshine_h, N, ra)
        source = "Angstrom from sunshine hours"
    else:
        raise ValueError("Give sunshine hours or measured solar radiation for "
                         "every month; radiation is not estimated silently.")
    rso = clear_sky_radiation(ra, altitude_m)
    es = (K.saturation_vapour_pressure(t_max_c)
          + K.saturation_vapour_pressure(t_min_c)) / 2.0
    ea = es * rh_mean_pct / 100.0
    rns = (1.0 - ALBEDO) * rs
    rnl = net_longwave(t_max_c, t_min_c, ea, rs, rso)
    return {"ra": ra, "N": N, "rs": rs, "rso": rso, "rns": rns, "rnl": rnl,
            "rn": rns - rnl, "ea": ea, "es": es, "rs_source": source}


def soil_heat_flux_monthly(t_prev_c: float, t_next_c: float | None = None,
                           t_this_c: float | None = None) -> float:
    """
    G for a monthly step, MJ m-2 day-1.

    FAO-56 Eq. 43 with both neighbours, Eq. 44 with only the previous month.
    """
    if t_next_c is not None:
        return 0.07 * (t_next_c - t_prev_c)
    if t_this_c is not None:
        return 0.14 * (t_this_c - t_prev_c)
    return 0.0


def et0_monthly(rows: list[dict], lat_deg: float, altitude_m: float) -> list[dict]:
    """
    ET0 for twelve months of station data.

    Each row: tmax, tmin, rh, wind (u2, m/s) and either sun (hours) or rs
    (MJ m-2 day-1). A row that already carries an ``et0`` value (for instance
    from a CLIMWAT or AQUASTAT export) is passed through unchanged and marked
    as such, so a published ET0 is never recomputed from partial weather.
    """
    if len(rows) != 12:
        raise ValueError(f"Twelve months are required, got {len(rows)}.")
    tmean = [((r.get("tmax") or 0.0) + (r.get("tmin") or 0.0)) / 2.0 for r in rows]
    out = []
    for i, r in enumerate(rows):
        doy = mid_month_doy(i + 1)
        given = r.get("et0")
        if given is not None and not _isnan(given) and given > 0:
            out.append({"month": MONTHS[i], "et0": float(given),
                        "source": "given", "rn": None, "g": None})
            continue
        for key in ("tmax", "tmin", "rh", "wind"):
            if r.get(key) is None or _isnan(r.get(key)):
                raise ValueError(f"{MONTHS[i]}: {key} is missing.")
        rad = net_radiation(lat_deg, doy, r["tmax"], r["tmin"], r["rh"], altitude_m,
                            sunshine_h=_num(r.get("sun")), rs_mj=_num(r.get("rs")))
        g = soil_heat_flux_monthly(tmean[i - 1], tmean[(i + 1) % 12])
        et0 = K.et0_penman_monteith(r["tmax"], r["tmin"], r["rh"], r["wind"],
                                    rad["rn"], altitude_m, g_mj_m2_d=g)
        out.append({"month": MONTHS[i], "et0": et0, "source": "Penman-Monteith",
                    "rn": rad["rn"], "ra": rad["ra"], "rs": rad["rs"], "g": g})
    return out


def _num(v):
    if v is None or _isnan(v):
        return None
    return float(v)


def _isnan(v) -> bool:
    try:
        return math.isnan(float(v))
    except (TypeError, ValueError):
        return True


# ---------------------------------------------------------------------------
# Crop coefficient curve — FAO-56 single coefficient, Fig. 25 / Eq. 66
# ---------------------------------------------------------------------------

def kc_daily(day_after_planting: float, kc_ini: float, kc_mid: float,
             kc_end: float, l_ini: int, l_dev: int, l_mid: int, l_late: int) -> float | None:
    """Kc on a given day of the season; None outside the season."""
    d = float(day_after_planting)
    if d < 0 or d > l_ini + l_dev + l_mid + l_late:
        return None
    if d <= l_ini:
        return kc_ini
    if d <= l_ini + l_dev:
        return kc_ini + (d - l_ini) / max(l_dev, 1) * (kc_mid - kc_ini)
    if d <= l_ini + l_dev + l_mid:
        return kc_mid
    return kc_mid + (d - l_ini - l_dev - l_mid) / max(l_late, 1) * (kc_end - kc_mid)


def kc_monthly(planting_month: int, planting_day: int, kc_ini: float, kc_mid: float,
               kc_end: float, stages: tuple[int, int, int, int]) -> list[dict]:
    """
    Mean Kc and the number of crop days in each calendar month.

    A month the crop occupies for 10 days contributes 10 days of demand, not a
    month's worth; the seasonal volume depends on getting that right.
    """
    l_ini, l_dev, l_mid, l_late = (int(s) for s in stages)
    season = l_ini + l_dev + l_mid + l_late
    start = sum(DAYS_IN_MONTH[:planting_month - 1]) + planting_day - 1
    acc = [[] for _ in range(12)]
    for d in range(season):
        doy = (start + d) % 365
        m = 0
        cum = 0
        for i, n in enumerate(DAYS_IN_MONTH):
            if doy < cum + n:
                m = i
                break
            cum += n
        kc = kc_daily(d, kc_ini, kc_mid, kc_end, l_ini, l_dev, l_mid, l_late)
        if kc is not None:
            acc[m].append(kc)
    return [{"month": MONTHS[i], "kc": (sum(v) / len(v)) if v else 0.0,
             "days": len(v)} for i, v in enumerate(acc)]


def effective_rainfall(p_month_mm: float, method: str = "usda") -> float:
    """
    Effective monthly rainfall, mm.

    ``usda``   USDA Soil Conservation Service formula as implemented in
               FAO CROPWAT: P(125 - 0.2P)/125 for P <= 250, 125 + 0.1P above.
    ``fixed``  80 % of rainfall.
    ``none``   zero — the usual design assumption for a peak month in Egypt.
    """
    p = max(0.0, float(p_month_mm or 0.0))
    if method == "none":
        return 0.0
    if method == "fixed":
        return 0.8 * p
    if p <= 250.0:
        return p * (125.0 - 0.2 * p) / 125.0
    return 125.0 + 0.1 * p


def monthly_requirement(et0_rows: list[dict], kc_rows: list[dict], kr: float,
                        rain_mm: list[float], ea: float, lr: float,
                        area_ha: float, rain_method: str = "usda") -> dict:
    """
    Month-by-month localised demand, net and gross requirement and volume.

    ETc,loc = ET0 x Kc x Kr (Keller & Bliesner). Net = ETc,loc x days - Peff
    (not below zero). Gross = net / Ea, inflated by 1/(1-LR) above LR 0.1 as
    in :func:`kernels.gross_depth`. The peak month is the one with the highest
    DAILY localised ETc among months the crop occupies — the design figure —
    which is not always the month with the largest monthly total.
    """
    rows = []
    for i in range(12):
        days = kc_rows[i]["days"]
        kc = kc_rows[i]["kc"]
        et0 = float(et0_rows[i]["et0"])
        etc_d = et0 * kc * kr if days else 0.0
        peff = effective_rainfall(rain_mm[i] if rain_mm else 0.0, rain_method)
        peff_crop = peff * days / DAYS_IN_MONTH[i]
        net = max(0.0, etc_d * days - peff_crop)
        gross = K.gross_depth(net, ea, lr) if net > 0 else 0.0
        rows.append({"month": MONTHS[i], "days": days, "et0": et0, "kc": kc,
                     "etc_loc_mm_d": etc_d, "peff_mm": peff_crop,
                     "net_mm": net, "gross_mm": gross,
                     "volume_m3": gross * 10.0 * area_ha})
    active = [r for r in rows if r["days"] > 0]
    peak = max(active, key=lambda r: r["etc_loc_mm_d"]) if active else None
    return {
        "rows": rows,
        "peak_month": peak["month"] if peak else None,
        "peak_etc_mm_d": peak["etc_loc_mm_d"] if peak else 0.0,
        "peak_et0_mm_d": peak["et0"] if peak else 0.0,
        "peak_kc": peak["kc"] if peak else 0.0,
        "season_net_mm": sum(r["net_mm"] for r in rows),
        "season_gross_mm": sum(r["gross_mm"] for r in rows),
        "season_volume_m3": sum(r["volume_m3"] for r in rows),
        "season_days": sum(r["days"] for r in rows),
    }
