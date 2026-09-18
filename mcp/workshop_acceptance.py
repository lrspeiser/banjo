"""Explicit limits for one exact-Matter static-load test, never certification.

No tolerances are inferred from a product name. A passing endpoint test says
nothing about unmeasured peak deflection, other loads, or other designs.
"""
from __future__ import annotations

from copy import deepcopy
from math import isfinite
from typing import Any

LIMITS = {
    "max_displacement_m": ("prototype_displacement_m", "m", "max"),
    "max_rotation_deg": ("prototype_rotation_change_deg", "deg", "max"),
    "max_fractures": ("fracture_events", "events", "max"),
    "min_actual_load_kg": ("actual_grid_load_kg", "kg", "min"),
}


def checked_limits(value: Any) -> dict[str, float | int] | None:
    """Validate before starting an expensive engine session."""
    if value is None:
        return None
    if not isinstance(value, dict) or not value:
        raise ValueError("acceptance_limits must be a nonempty object, or omitted")
    unknown = set(value) - LIMITS.keys()
    if unknown:
        raise ValueError("unknown acceptance limit(s): " + ", ".join(sorted(map(str, unknown))))
    out: dict[str, float | int] = {}
    for key, raw in value.items():
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise ValueError(f"{key} must be a finite nonnegative number")
        try:
            number = float(raw)
        except OverflowError:
            raise ValueError(f"{key} must be a finite nonnegative number") from None
        if not isfinite(number) or number < 0:
            raise ValueError(f"{key} must be a finite nonnegative number")
        if key == "max_fractures" and number != int(number):
            raise ValueError("max_fractures must be a whole number of fracture events")
        out[key] = int(number) if key == "max_fractures" else number
    return out


def merge_limits(declared: Any, requested: Any) -> dict[str, float | int] | None:
    """An extra test request can tighten a design's declared limits, not relax them."""
    left, right = checked_limits(declared), checked_limits(requested)
    if left is None:
        return right
    if right is None:
        return left
    out = dict(left)
    for key, value in right.items():
        if key not in out:
            out[key] = value
        else:
            out[key] = (min if LIMITS[key][2] == "max" else max)(out[key], value)
    return out


def _finite(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return isfinite(value)
    except OverflowError:
        return False


def evaluate(result: dict[str, Any], limits: Any) -> dict[str, Any]:
    """Evaluate reported endpoint measurements and required run-integrity checks.

    Missing/nonfinite data are unsupported, not zero. The native geometry must
    be verified, both bodies must survive, and the requested time must finish.
    These checks do not establish a constitutive law or a validated load range.
    """
    bounds = checked_limits(limits)
    if bounds is None:
        return deepcopy(result.get("acceptance") or {"status": "not-declared"})
    measured = result.get("measured") or {}
    prototype = result.get("prototype") or {}
    requested = result.get("requested") or {}
    checks: list[dict[str, Any]] = []

    def check(name: str, actual: Any, expected: Any, passed: bool | None,
              *, operator: str = "equals", unit: str | None = None) -> None:
        checks.append({"metric": name, "measured": actual,
                       "operator": operator, "limit": expected,
                       "status": "unsupported" if passed is None else "passed" if passed else "failed",
                       **({"unit": unit} if unit else {})})

    check("evidence", result.get("evidence"), "engine-trial",
          result.get("evidence") == "engine-trial")
    check("engine_grid_verified", prototype.get("engine_grid_verified"), True,
          prototype.get("engine_grid_verified") is True)
    digest = prototype.get("matter_physics_hash")
    hash_ok = isinstance(digest, str) and len(digest) == 64 and all(c in "0123456789abcdef" for c in digest)
    check("matter_physics_hash", digest, "SHA-256", hash_ok)
    for name in ("prototype_present", "load_present"):
        actual = measured.get(name)
        check(name, actual if type(actual) is bool else None, True,
              actual if type(actual) is bool else None)
    elapsed, duration = measured.get("clock_s"), requested.get("duration_s")
    complete = None
    if _finite(elapsed) and _finite(duration) and duration > 0 and elapsed >= 0:
        # The engine report rounds its clock to six decimal places.
        complete = elapsed + 0.000001 >= duration
    check("clock_s", elapsed if _finite(elapsed) else None,
          duration if _finite(duration) else None, complete, operator="min", unit="s")

    for name, limit in bounds.items():
        metric, unit, operator = LIMITS[name]
        if name == "max_fractures":
            events = measured.get("fractures")
            actual = len(events) if isinstance(events, list) else None
        else:
            actual = measured.get(metric)
        passed = None
        if _finite(actual) and actual >= 0:
            passed = actual <= limit if operator == "max" else actual >= limit
        else:
            actual = None
        check(metric, actual, limit, passed, operator=operator, unit=unit)

    statuses = {item["status"] for item in checks}
    status = "failed" if "failed" in statuses else "unsupported" if "unsupported" in statuses else "passed"
    return {
        "status": status,
        "scope": "this-exact-run",
        "criteria": dict(bounds),
        "checks": checks,
        "subject": "selected-product",
        "basis": {
            "matter_physics_hash": digest if hash_ok else None,
            "cell_size_m": prototype.get("effective_cell_size_m"),
            "actual_grid_load_kg": measured.get("actual_grid_load_kg"),
            "requested_duration_s": duration,
        },
        "why": "Explicit endpoint limits and run-integrity checks; not peak-deflection, material, or load-range certification.",
    }
