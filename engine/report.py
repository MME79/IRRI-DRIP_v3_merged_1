"""
Export-side reporting helpers. UI-free, so they can be tested directly.

These live outside modules/plant.py deliberately. The defect that created this
file was found by a user running the program, not by 179 passing tests: the
report page showed "1 of 15 design checks failed" and then exported a workbook,
a drawing and a snapshot that carried no mark of the failure on any face a
reader would open. The page-level smoke test could not have caught it, because
it renders the report page with an empty state and therefore stops at the stage
guard, never reaching the export block at all.

The rule that follows: anything whose correctness a reviewer would care about
does not live inside a Streamlit page body, where the only way to exercise it
is to render a complete design.
"""

from __future__ import annotations

import math

from . import kernels as K

__all__ = ["verdict_from_checks", "verdict_rows", "exponent_assumption",
           "stamped_filename"]


def verdict_from_checks(checks) -> dict:
    """
    Reduce the design-check table to the verdict that travels with the files.

    ``checks`` is the page's list of ``(name, ok, measured, criterion)`` tuples.
    Only the name and the boolean are used here.
    """
    checks = list(checks)
    failed = [c[0] for c in checks if not c[1]]
    return {
        "passed": not failed,
        "checks_applied": len(checks),
        "checks_failed": len(failed),
        "failed_checks": failed,
    }


def verdict_rows(verdict: dict) -> list[dict]:
    """
    The first sheet of the exported workbook.

    It opens on the verdict because the sheet a reader opens is the first one,
    and a failure recorded only on a later sheet is a failure that gets missed.
    """
    passed = bool(verdict.get("passed"))
    rows = [
        {"Item": "Design verdict", "Value": "PASSED" if passed else "NOT PASSED"},
        {"Item": "Checks applied", "Value": verdict.get("checks_applied", 0)},
        {"Item": "Checks failed", "Value": verdict.get("checks_failed", 0)},
    ]
    rows += [{"Item": "Failed check", "Value": name}
             for name in verdict.get("failed_checks", [])]
    rows.append({"Item": "Status of this file", "Value": (
        "All design checks passed. Independent verification against site-measured "
        "data and manufacturer specifications is still required before issue."
        if passed else
        "THIS DESIGN DID NOT PASS ITS OWN CHECKS. It must not be issued, tendered "
        "or constructed in this state. See the Design checks sheet for the measured "
        "value and the criterion of every failed check.")})
    return rows


def exponent_assumption(res: dict, n_emitters: int) -> str:
    """
    The Christiansen line of the exported Assumptions sheet.

    It must state the exponent the design ACTUALLY used. Until v0.8.2 this was
    the literal string "velocity exponent m = 2", left behind when the exponent
    became measured — the same class of defect as the Blasius/Swamee-Jain
    contradiction corrected earlier. An exported assumption that is false is
    worse than one that is missing, because it is read as a record of method.
    """
    m = res.get("velocity_exponent", float("nan"))
    mode = res.get("exponent_mode", K.EXPONENT_MODE_DEFAULT)
    n = max(1, int(n_emitters))
    f_used = K.christiansen_f(n, m) if math.isfinite(m) else float("nan")
    f_two = K.christiansen_f(n, 2.0)
    m_txt = f"{m:.3f}" if math.isfinite(m) else "not recorded"
    f_txt = f"{f_used:.4f}" if math.isfinite(f_used) else "not recorded"
    return (f"Christiansen F with velocity exponent m = {m_txt} ({mode}), "
            f"F = {f_txt} over {n} outlets. For comparison m = 2.000 would give "
            f"F = {f_two:.4f}.")


def stamped_filename(stem: str, verdict: dict) -> str:
    """A failed design must be recognisable from the file name alone."""
    return stem if verdict.get("passed") else f"{stem}_NOT-PASSED"
