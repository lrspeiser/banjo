"""Engineering evidence attached to ProductGraph versions.

A measured run is not automatically a validation.  Only evidence with explicit
acceptance criteria and a passing result may expand the range where a reduced
runtime model is trusted.  Observations such as the first kettle/hoist bench
runs remain useful measurements without silently certifying anything.
"""
from __future__ import annotations

from math import isfinite
from typing import Any

EVIDENCE_SCHEMA = "banjo.product-evidence.v1"


def _range(value: Any, name: str) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"{name} range must be [low, high]")
    low, high = float(value[0]), float(value[1])
    if not isfinite(low) or not isfinite(high) or high < low:
        raise ValueError(f"{name} range must be finite and ordered")
    return [low, high]


def record(*, evidence_id: str, test: str, measured: dict[str, Any],
           conditions: dict[str, Any] | None = None,
           acceptance: dict[str, Any] | None = None,
           validated_range: dict[str, Any] | None = None,
           source: str = "workshop") -> dict[str, Any]:
    """Create one immutable evidence record.

    ``validated_range`` is allowed only when acceptance.status is ``passed``.
    This prevents an observed trial from becoming runtime authority merely
    because it produced numbers.
    """
    if not evidence_id or not test:
        raise ValueError("evidence needs an id and test name")
    if not isinstance(measured, dict):
        raise ValueError("measured evidence must be an object")
    accepted = dict(acceptance or {"status": "observed"})
    status = str(accepted.get("status") or "observed")
    if status not in {"observed", "passed", "failed", "unsupported"}:
        raise ValueError("acceptance status must be observed, passed, failed or unsupported")
    ranges = {}
    if validated_range:
        if status != "passed":
            raise ValueError("only passed evidence can establish a validated range")
        if not isinstance(validated_range, dict):
            raise ValueError("validated_range must be an object")
        for metric, bounds in validated_range.items():
            ranges[str(metric)] = _range(bounds, str(metric))
    return {
        "schema": EVIDENCE_SCHEMA,
        "id": str(evidence_id),
        "test": str(test),
        "source": str(source),
        "conditions": dict(conditions or {}),
        "measured": dict(measured),
        "acceptance": accepted,
        **({"validated_range": ranges} if ranges else {}),
    }


def from_bench(result: dict[str, Any], *, evidence_id: str) -> dict[str, Any]:
    """Preserve a Workshop bench result without promoting observations to proof."""
    if not isinstance(result, dict):
        raise ValueError("bench result must be an object")
    return record(
        evidence_id=evidence_id,
        test=str(result.get("test") or result.get("trial") or "bench"),
        measured=dict(result.get("measured") or {}),
        conditions=dict(result.get("requested") or {}),
        acceptance=dict(result.get("acceptance") or {"status": "observed"}),
        source=str(result.get("evidence") or "workshop-bench"),
    )


def envelope(evidence: list[dict[str, Any]]) -> dict[str, list[list[float]]]:
    """All separately validated intervals, without pretending gaps were tested."""
    out: dict[str, list[list[float]]] = {}
    for item in evidence:
        if not isinstance(item, dict):
            continue
        acceptance = item.get("acceptance") or {}
        if acceptance.get("status") != "passed":
            continue
        for metric, bounds in (item.get("validated_range") or {}).items():
            out.setdefault(str(metric), []).append(_range(bounds, str(metric)))
    for metric in out:
        out[metric].sort()
    return out
