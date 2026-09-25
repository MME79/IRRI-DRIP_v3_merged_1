"""
IRRI-DRIP — checks against values that exist outside this program.

Everything else in validation/ checks the program against itself: the
edge-case probe checks it does not contradict its own guards, the step
method checks one internal path against another internal path. Both are
necessary and neither can catch an error the whole program shares.

This file holds only checks whose reference value comes from OUTSIDE.
Where a reference could be confirmed, it is asserted and its source named.
Where it could not, the case is listed as UNVERIFIED and nothing is
asserted — an invented reference is worse than a missing one.

Run:  python validation/published_cases.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import kernels as K

CHECKS = []
UNVERIFIED = []


def check(name, got, expected, tol, source):
    ok = abs(got - expected) <= tol
    CHECKS.append((ok, name, got, expected, tol, source))
    return ok


def unverified(name, note):
    UNVERIFIED.append((name, note))


# ---------------------------------------------------------------------------
# 1. The Christiansen multiple-outlet factor, against its exact definition
# ---------------------------------------------------------------------------

def exact_christiansen(n: int, m: float) -> float:
    """
    The factor as originally DEFINED, not as approximated:

        F = (1^m + 2^m + ... + N^m) / N^(m+1)

    This is a closed definition with no fitted terms, so it is a genuine
    external reference for the three-term approximation the program uses:

        F ~ 1/(m+1) + 1/(2N) + sqrt(m-1)/(6N^2)

    Source for the summation form: Alazba et al., "Explicit Equations for
    Lateral Line Design in Pressurised Irrigation Systems", Water 12(3), 844
    (2020), which states G = (1^m + 2^m + ... + N^m) / N^(m+1) and notes
    "m = 2 in Darcy-Weisbach equation and m = 1.852 in Hazen-Williams
    equation".
    https://www.mdpi.com/2073-4441/12/3/844
    """
    return sum(i ** m for i in range(1, int(n) + 1)) / (float(n) ** (m + 1.0))


def section_christiansen():
    print("\n1. Christiansen F against its exact summation definition")
    print("   Source: Alazba et al., Water 12(3) 844 (2020)")
    print(f"   {'N':>6} {'m':>7} {'exact':>10} {'program':>10} {'diff %':>9}")
    worst = 0.0
    for n in (5, 10, 20, 50, 100, 160, 200, 300):
        for m in (1.75, 1.852, 2.0):
            e = exact_christiansen(n, m)
            a = K.christiansen_f(n, m)
            diff = 100.0 * (a - e) / e
            worst = max(worst, abs(diff))
            if n in (5, 10, 200):
                print(f"   {n:6d} {m:7.3f} {e:10.5f} {a:10.5f} {diff:8.3f}%")
            check(f"christiansen_f(N={n}, m={m})", a, e, 2e-4,
                  "exact summation, Alazba et al. 2020")
    print(f"   worst deviation over all 24 combinations: {worst:.4f} %")


# ---------------------------------------------------------------------------
# 2. Tabulated F values in wide circulation
# ---------------------------------------------------------------------------

def section_tabulated():
    print("\n2. Tabulated F values")
    print("   These two are the values the program's own test suite has")
    print("   asserted since v0.1, and they agree with the exact summation")
    print("   above, which is what makes them usable as a cross-check.")
    for n, m, ref in ((10, 2.0, 0.385), (10, 1.852, 0.402)):
        got = K.christiansen_f(n, m)
        print(f"   N=10, m={m:.3f}: program {got:.4f} vs tabulated {ref:.3f}")
        check(f"tabulated F (N=10, m={m})", got, ref, 0.001,
              "F tables in general circulation; confirmed against the exact sum")


# ---------------------------------------------------------------------------
# 3. Blasius, an equation with a fixed closed form
# ---------------------------------------------------------------------------

def section_blasius():
    print("\n3. Blasius smooth-pipe friction factor, f = 0.316 Re^-0.25")
    for re, ref in ((1.0e4, 0.0316), (1.0e5, 0.316 * (1.0e5 ** -0.25))):
        got = K.blasius_friction_factor(re)
        print(f"   Re={re:9.0f}: program {got:.6f} vs formula {ref:.6f}")
        check(f"Blasius at Re={re:.0e}", got, ref, 1e-9, "closed-form definition")

    print("\n   Blasius implies m = 1.75 exactly, since hf ~ f*Q^2 ~ Q^-0.25 * Q^2.")
    print("   The program MEASURES the exponent from Swamee-Jain instead of")
    print("   assuming it, so on a smooth pipe the two must nearly agree:")
    for re in (1.0e4, 3.0e4, 1.0e5):
        m = K.velocity_exponent(re, 0.0)
        print(f"   Re={re:9.0f}: measured m = {m:.4f}  (Blasius implies 1.7500)")
        check(f"measured exponent on a smooth pipe at Re={re:.0e}", m, 1.75, 0.06,
              "Blasius f ~ Re^-0.25 => m = 1.75, closed form")


# ---------------------------------------------------------------------------
# 4. FAO-56 Penman-Monteith — the one case with a published worked example
# ---------------------------------------------------------------------------

def section_fao56():
    """
    FAO Irrigation and Drainage Paper 56 (Allen et al., 1998), Chapter 4,
    Example 17 (monthly ET0, Bangkok, April) and Example 18 (daily ET0,
    Brussels, 6 July). https://www.fao.org/4/x0490e/x0490e08.htm

    The whole radiation chain is the program's own (Eq. 21-25, 34, 35, 37,
    39); only the actual vapour pressure is handed over as the relative
    humidity that reproduces FAO-56's stated ea, because the program takes
    mean RH where the examples state ea (Ex. 17) or RHmax/RHmin (Ex. 18).
    """
    from engine import climate as C
    print("\n4. FAO-56 Penman-Monteith, worked Examples 17 and 18")
    src = "FAO-56 (Allen et al. 1998) Ch. 4, "
    cases = [
        ("Ex.17 Bangkok April", 13 + 44 / 60, 2.0, C.mid_month_doy(4), 34.8, 25.6, 2.85,
         2.0, 8.5, C.soil_heat_flux_monthly(29.2, t_this_c=30.2),
         {"ra": 38.06, "N": 12.31, "rs": 22.65, "rns": 17.44, "rnl": 3.11, "rn": 14.33},
         0.14, 5.72),
        ("Ex.18 Brussels 6 July", 50 + 48 / 60, 100.0, 187, 21.5, 12.3, 1.409,
         2.078, 9.25, 0.0,
         {"ra": 41.09, "N": 16.1, "rs": 22.07, "rns": 17.00, "rnl": 3.71, "rn": 13.28},
         0.0, 3.88),
    ]
    for name, lat, alt, doy, tx, tn, ea, u2, n, g, ref, g_ref, et0_ref in cases:
        es = (K.saturation_vapour_pressure(tx) + K.saturation_vapour_pressure(tn)) / 2.0
        rh = 100.0 * ea / es
        r = C.net_radiation(lat, doy, tx, tn, rh, alt, sunshine_h=n)
        et0 = K.et0_penman_monteith(tx, tn, rh, u2, r["rn"], alt, g_mj_m2_d=g)
        print(f"   {name}")
        for k, v in ref.items():
            print(f"      {k:4s} program {r[k]:8.3f}   FAO-56 {v:8.3f}")
            # FAO-56 prints intermediate terms to 2 decimals and carries the
            # rounded values forward; 0.5 % covers that rounding.
            check(f"{name}: {k}", r[k], v, max(0.05, 0.005 * abs(v)), src + name)
        print(f"      G    program {g:8.3f}   FAO-56 {g_ref:8.3f}")
        check(f"{name}: G", g, g_ref, 0.005, src + name)
        print(f"      ET0  program {et0:8.3f}   FAO-56 {et0_ref:8.3f} mm/day")
        check(f"{name}: ET0", et0, et0_ref, 0.02, src + name)


# ---------------------------------------------------------------------------
# 4b. Crop salinity tolerance, FAO-29 Table 4
# ---------------------------------------------------------------------------

def section_fao29():
    """
    Ayers & Westcot (1985), FAO Irrigation and Drainage Paper 29 Rev. 1,
    Table 4: ECe at 100 % and at 0 % yield potential.
    https://www.fao.org/4/t0234e/t0234e03.htm

    The drip leaching requirement is computed from the 0 % (maximum) column;
    v2.0.0 used the 100 % (threshold) column in its place.
    """
    import json
    print("\n5. Crop salinity tolerance against FAO-29 Table 4")
    table4 = {  # crop in data/crops.json: (ECe 100 %, ECe 0 %)
        "Tomato (open field)": (2.5, 13), "Potato": (1.7, 10), "Cucumber": (2.5, 10),
        "Sweet pepper": (1.5, 8.6), "Onion (dry)": (1.2, 7.4), "Maize (grain)": (1.7, 10),
        "Wheat": (6.0, 20), "Cotton": (7.7, 27), "Sugar beet": (7.0, 24), "Alfalfa": (2.0, 16),
        "Table grape": (1.5, 12), "Citrus (with cover)": (1.7, 8.0), "Date palm": (4.0, 32)}
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "data", "crops.json"), encoding="utf-8") as fh:
        crops = {c["name"]: c for c in json.load(fh)["crops"]}
    src = "FAO-29 Rev.1 (Ayers & Westcot 1985) Table 4"
    for name, (thr, mx) in table4.items():
        c = crops[name]
        check(f"{name}: ECe threshold", c["ece_threshold_ds_m"], thr, 1e-9, src)
        check(f"{name}: ECe at zero yield", c["ece_max_ds_m"], mx, 1e-9, src)
    print(f"   {len(table4)} crops: threshold and zero-yield ECe match Table 4")
    lr = K.leaching_requirement(1.0, 13.0)
    print(f"   tomato, ECw 1.0: LR = ECw/(2 max ECe) = {lr*100:.2f} %  (v2.0.0 gave 20 %)")
    check("tomato LR, drip form ECw/(2 max ECe)", lr, 1.0 / 26.0, 1e-12,
          "Keller & Bliesner (1990) high-frequency form with FAO-29 Table 4 max ECe")
    lr9 = K.leaching_requirement_fao29(1.0, 2.5)
    print(f"   tomato, ECw 1.0: LR = ECw/(5 ECe - ECw) = {lr9*100:.2f} %  (FAO-29 eq. 9)")
    check("tomato LR, FAO-29 eq. 9", lr9, 1.0 / 11.5, 1e-12, "FAO-29 Rev.1 eq. (9)")


# ---------------------------------------------------------------------------
# 5. What is still outstanding
# ---------------------------------------------------------------------------

def section_outstanding():
    unverified(
        "Keller & Bliesner / ASABE EP405.1 lateral worked examples",
        "Could not be confirmed from an accessible source in this session. "
        "Both are printed standards behind paywalls. Until a copy is read, "
        "the program's lateral result is verified for INTERNAL consistency "
        "(step method, 0.05-0.74 %) but not against a published design.")
    unverified(
        "Choice of velocity exponent for a dripline",
        "A 2020 Water paper states 'm = 2 in Darcy-Weisbach equation and "
        "m = 1.852 in Hazen-Williams equation', which is the widespread "
        "convention and the one this program used until v0.5.0. The program "
        "now measures m from its own friction factor instead, giving about "
        "1.75 on a smooth dripline, because Swamee-Jain plus a constant-f "
        "exponent is internally contradictory. That reasoning is sound and "
        "reproducible, but the m = 1.75 choice for driplines was NOT "
        "confirmed against a named irrigation standard in this session. Both "
        "figures are reported on every lateral so the difference is visible.")
    unverified(
        "Field measurement",
        "No output has been compared with measured pressures or catch-can "
        "discharges from an Egyptian field. This is the only check that tests "
        "the program against reality rather than against arithmetic.")


def main():
    print("=" * 78)
    print("IRRI-DRIP — checks against references outside the program")
    print("=" * 78)

    section_christiansen()
    section_tabulated()
    section_blasius()
    section_fao56()
    section_fao29()
    section_outstanding()

    print("\n" + "=" * 78)
    print("RESULT")
    print("=" * 78)
    failed = [c for c in CHECKS if not c[0]]
    print(f"  {len(CHECKS) - len(failed)} of {len(CHECKS)} external checks passed.")
    for ok, name, got, exp, tol, src in failed:
        print(f"\n  [FAIL] {name}")
        print(f"         got {got!r}, expected {exp!r} +/- {tol!r}")
        print(f"         source: {src}")

    print(f"\n  {len(UNVERIFIED)} item(s) NOT verified — listed, not asserted:")
    for name, note in UNVERIFIED:
        print(f"\n  [UNVERIFIED] {name}")
        for line in _wrap(note, 68):
            print(f"      {line}")

    print("\n  Nothing in this file asserts a value that could not be traced to")
    print("  a source. The unverified list is the honest remainder.")
    return 1 if failed else 0


def _wrap(text, width):
    words, line, out = text.split(), "", []
    for w in words:
        if len(line) + len(w) + 1 > width:
            out.append(line)
            line = w
        else:
            line = (line + " " + w).strip()
    if line:
        out.append(line)
    return out


if __name__ == "__main__":
    sys.exit(main())
