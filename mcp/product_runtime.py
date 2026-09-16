"""Decide whether a reduced PhysicsContract still covers a live interaction.

This is policy over the compiled contract, not a physics solver.  It keeps the
main world cheap while making unsupported extrapolation explicit: stay reduced
inside the tested envelope; request local refinement when an event leaves it,
approaches a failure mode, needs unsupported behavior or explicitly asks for
fine inspection.
"""
from __future__ import annotations

from math import isfinite
from typing import Any

from mcp.product_contract import CONTRACT_SCHEMA
from mcp.product_evidence import envelope

DECISION_SCHEMA = "banjo.physics-refinement-decision.v1"


def _contains(intervals: list[list[float]], value: float) -> bool:
    return any(float(bounds[0]) <= value <= float(bounds[1]) for bounds in intervals)


def decision(contract: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(contract, dict) or contract.get("schema") != CONTRACT_SCHEMA:
        raise ValueError("runtime refinement needs a banjo.physics-contract.v1")
    if not isinstance(event, dict):
        raise ValueError("event must be an object")

    reasons: list[str] = []
    local = sorted({str(v) for v in (event.get("components") or []) if str(v)})
    if bool(event.get("high_fidelity")):
        reasons.append("high-fidelity inspection was explicitly requested")
    unsupported = [str(v) for v in (event.get("unsupported") or []) if str(v)]
    if unsupported:
        reasons.append("reduced model does not support: " + ", ".join(sorted(unsupported)))

    try:
        failure_fraction = float(event.get("failure_fraction", 0.0))
    except (TypeError, ValueError):
        raise ValueError("failure_fraction must be a number")
    if not isfinite(failure_fraction) or failure_fraction < 0:
        raise ValueError("failure_fraction must be finite and nonnegative")
    threshold = float(event.get("refine_at_failure_fraction", 0.8))
    if failure_fraction >= threshold:
        reasons.append(f"reduced failure indicator {failure_fraction:.3g} reached refinement threshold {threshold:.3g}")

    # Contracts currently retain validated ranges as individual evidence records.
    # Convert them to a metric -> interval list without joining untested gaps.
    synthetic = [{"acceptance": {"status": "passed"}, "validated_range": row.get("range") or {}}
                 for row in (contract.get("validated_ranges") or []) if isinstance(row, dict)]
    ranges = envelope(synthetic)
    requested_metrics = event.get("metrics") or {}
    if not isinstance(requested_metrics, dict):
        raise ValueError("event.metrics must be an object")
    require = {str(v) for v in (event.get("require_validated") or requested_metrics.keys())}
    for metric, raw in requested_metrics.items():
        try:
            value = float(raw)
        except (TypeError, ValueError):
            raise ValueError(f"event metric {metric} must be a number")
        if not isfinite(value):
            raise ValueError(f"event metric {metric} must be finite")
        intervals = ranges.get(str(metric), [])
        if str(metric) in require and not intervals:
            reasons.append(f"{metric} has no validated runtime range")
        elif intervals and not _contains(intervals, value):
            reasons.append(f"{metric}={value:g} is outside validated ranges {intervals}")

    # A caller can identify a semantic collision/load zone. If it cannot, an
    # interaction that explicitly says it needs one must refine instead of
    # falling back to a whole-object generic collision guess.
    zone = event.get("collision_zone")
    if event.get("requires_collision_zone"):
        known = {str(row.get("id")) for row in (contract.get("collision_zones") or [])}
        if not zone or str(zone) not in known:
            reasons.append("interaction has no supported semantic collision zone")

    return {
        "schema": DECISION_SCHEMA,
        "product_id": contract.get("product_id"),
        "decision": "refine" if reasons else "stay-reduced",
        "scope": "local" if reasons and local else ("product" if reasons else "none"),
        "components": local,
        "reasons": reasons,
        "validated_ranges": ranges,
    }
