"""
Design-state bookkeeping, UI-free: which saved results are still current,
and how a project is written to a file.

Why this module exists (v2.0.1)
-------------------------------
Every page stores its result in the project state ``S`` under one key. The
pages downstream read those results. Up to v2.0.0 nothing recorded WHICH
version of the upstream results a page was computed from, so an edit on Home
(for example the source discharge cut from 40 to 3 m³/h) left the network,
pump, cost and the report showing — and exporting — a design that no longer
followed from the inputs, under an "All checks passed" verdict.

The fix does not throw results away (a hand-drawn network is expensive to
redraw). Instead each save records a fingerprint of every upstream result it
used; a result whose recorded fingerprints no longer match — or whose
upstream is itself out of date — is STALE. The design checks turn any stale
stage into a failed check, so the verdict and every exported file say
NOT PASSED until the page is saved again.
"""

from __future__ import annotations

import hashlib
import json
import math

__all__ = ["DEPS", "STAGE_LABELS", "fingerprint", "stamp", "stamp_all",
           "stale_stages", "sanitize", "project_json"]

STAMPS_KEY = "_stamps"

# stage -> the stages whose saved results it reads. Transitive dependencies
# need not be listed: staleness propagates along the chain.
DEPS: dict[str, tuple[str, ...]] = {
    "water":       ("setup", "layout"),
    "emitter":     ("setup", "water"),
    "operation":   ("setup", "water", "emitter", "layout"),
    "network":     ("operation",),
    "lateral":     ("setup", "emitter", "operation", "network"),
    "manifold":    ("setup", "emitter", "operation", "network", "pipe_prices"),
    "quality":     ("setup", "water", "emitter", "operation"),
    "fertigation": ("setup", "emitter", "operation"),
    "hydraulic":   ("setup", "emitter", "lateral", "manifold", "quality", "fertigation"),
    "pump":        ("setup", "emitter", "water", "hydraulic"),
    "cost":        ("setup", "emitter", "operation", "manifold", "pump", "pipe_prices"),
}

# The page that re-saves each stage, for the messages.
STAGE_LABELS: dict[str, str] = {
    "setup": "Home › Project Setup", "layout": "Home › Field Layout & Blocks",
    "water": "Crop Water Requirements", "emitter": "Emitter Selection",
    "operation": "Operational Design", "network": "Pipe Network Layout",
    "lateral": "Pipe Network Design", "manifold": "Pipe Network Design",
    "quality": "Water Quality & Filtration", "fertigation": "Water Quality & Filtration",
    "hydraulic": "Hydraulic Design", "pump": "Pump Selection", "cost": "Cost Estimation",
    "pipe_prices": "Cost Estimation › pipe prices",
}

# Fields that change on every save without changing the design.
_VOLATILE = {"last_updated"}


def sanitize(obj):
    """Replace NaN / ±inf by None, recursively, and make the tree JSON-safe."""
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {str(k): sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize(v) for v in obj]
    if obj is None or isinstance(obj, (str, int, bool)):
        return obj
    try:                                   # numpy scalars and the like
        f = float(obj)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return str(obj)


def fingerprint(payload) -> str:
    if isinstance(payload, dict):
        payload = {k: v for k, v in payload.items() if k not in _VOLATILE}
    txt = json.dumps(sanitize(payload), sort_keys=True, ensure_ascii=True,
                     allow_nan=False)
    return hashlib.sha1(txt.encode("ascii")).hexdigest()[:16]


def stamp(S: dict, key: str) -> None:
    """Record the fingerprints of the upstream results ``S[key]`` was built from."""
    stamps = S.setdefault(STAMPS_KEY, {})
    stamps[key] = {d: (fingerprint(S[d]) if S.get(d) else None) for d in DEPS.get(key, ())}


def stamp_all(S: dict) -> None:
    """Stamp every stage present — for a project file written before v2.0.1,
    whose stages are taken as consistent at the moment it was saved."""
    for key in DEPS:
        if S.get(key):
            stamp(S, key)


def stale_stages(S: dict) -> dict[str, list[str]]:
    """
    {stage: [reasons]} for every stored stage that no longer follows from
    the current upstream results. A stage without a stamp (never saved
    through :func:`stamp`) is not judged.
    """
    stamps = S.get(STAMPS_KEY) or {}
    out: dict[str, list[str]] = {}
    fp_cache: dict[str, str | None] = {}

    def fp(d):
        if d not in fp_cache:
            fp_cache[d] = fingerprint(S[d]) if S.get(d) else None
        return fp_cache[d]

    # DEPS is written in pipeline order, so one pass settles propagation.
    for key, deps in DEPS.items():
        if not S.get(key) or key not in stamps:
            continue
        rec = stamps[key]
        why = []
        for d in deps:
            if rec.get(d) != fp(d):
                why.append(f"{STAGE_LABELS.get(d, d)} changed after this was saved")
            elif d in out:
                why.append(f"{STAGE_LABELS.get(d, d)} is itself out of date")
        if why:
            out[key] = why
    return out


def project_json(S: dict, version: str) -> str:
    """The project file: strict JSON (no NaN), readable by any JSON parser."""
    return json.dumps({"irri_drip_project": version, "S": sanitize(S)}, indent=1,
                      ensure_ascii=False, allow_nan=False)
