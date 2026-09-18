"""Functional Workshop bench with generic visual playback recordings.

The tested bench implementation remains in ``workshop_bench_core``. Engine
sessions are transparently wrapped while a test runs; the solver receives the
same calls and the result gains a browser-neutral playback timeline.
"""
from __future__ import annotations

from typing import Any

import workshop_bench_core as _core
from workshop_bench_core import *  # noqa: F401,F403
import workshop_recording
import workshop_trials
from mcp import workshop_acceptance

_LOAD_KINDS = {"table", "stool", "bench", "chair", "shelf-unit", "cart"}


def catalog(kind: str | None = None) -> list[dict[str, Any]]:
    out = _core.catalog(kind)
    if kind in _LOAD_KINDS:
        out.append({
            "test": "declared_static_load", "name": "Load the product",
            "about": "Run this product's own declared static load in an isolated physics world and watch the bodies move, rotate or fracture.",
            "controls": [
                {"name": "duration_s", "label": "Run", "unit": "s", "type": "number", "default": 2.0, "min": 0.2, "max": 10.0, "step": 0.1},
                {"name": "cell_size_m", "label": "Matter resolution", "unit": "m", "type": "number", "default": 0.04, "min": 0.005, "max": 0.1, "step": 0.01},
                {"name": "evaluate_limits", "label": "Evaluate the limits below", "type": "boolean", "default": False},
                {"name": "max_displacement_m", "label": "Maximum end displacement", "unit": "m", "type": "number", "default": 0.01, "min": 0.0, "max": 10.0, "step": 0.001},
                {"name": "max_rotation_deg", "label": "Maximum end rotation", "unit": "deg", "type": "number", "default": 5.0, "min": 0.0, "max": 180.0, "step": 0.1},
                {"name": "max_fractures", "label": "Maximum fracture events", "type": "number", "default": 0, "min": 0, "max": 10000, "step": 1},
            ],
            "acceptance_limits": {key: {"metric": metric, "unit": unit, "operator": operator}
                                  for key, (metric, unit, operator) in workshop_acceptance.LIMITS.items()},
            "limitations": ["The load is the design's authored load case. If no acceptance tolerance is declared, the run remains measured evidence rather than an invented pass/fail."],
            "visual_playback": True,
        })
    for item in out:
        name = str(item.get("test") or "")
        if name == "machine_control":
            item["name"] = "Reference hoist controller"
            item["about"] = "Exercise the reference hoist's controller and energy path, not the selected product's geometry."
        item["visual_playback"] = bool(item.get("visual_playback")) or name in {
            "cart_roll", "kettle_heat", "machine_control", "declared_static_load"
        }
        if item["visual_playback"]:
            item.setdefault("controls", []).append({
                "name": "record_trace", "label": "Keep simulation trace for inspection",
                "type": "boolean", "default": True})
        if name in {"runtime_contract", "force_probe"}:
            item["visual_overlay"] = True
    return out


def run(app: Any, design, request: Any) -> dict[str, Any]:
    if not isinstance(request, dict):
        raise ValueError("bench_test must be an object")
    test = str(request.get("test") or "")
    config = request.get("config") or {}
    if not isinstance(config, dict):
        raise ValueError("bench_test.config must be an object")
    record_trace = config.get("record_trace", True)
    if not isinstance(record_trace, bool):
        raise ValueError("record_trace must be a boolean")
    selected_limits = config.get("evaluate_limits", False)
    if not isinstance(selected_limits, bool):
        raise ValueError("evaluate_limits must be a boolean")
    limits = workshop_acceptance.merge_limits(
        request.get("acceptance_limits"), config.get("acceptance_limits"))
    if selected_limits:
        names = ("max_displacement_m", "max_rotation_deg", "max_fractures")
        if any(name not in config for name in names):
            raise ValueError("evaluating limits requires explicit displacement, rotation and fracture limits")
        limits = workshop_acceptance.merge_limits(limits, {name: config[name] for name in names})
    if limits is not None and test != "declared_static_load":
        raise ValueError("acceptance_limits currently require the exact-Matter declared_static_load test")
    if test == "declared_static_load":
        return workshop_trials.run_declared_static_load(
            app, design,
            cell_size_m=float(config.get("cell_size_m", 0.04)),
            duration_s=float(config.get("duration_s", 2.0)), record_trace=record_trace,
            acceptance_limits=limits)

    recorders: list[workshop_recording.Recorder] = []

    def record(session):
        recorder = workshop_recording.wrap(session)
        recorders.append(recorder)
        return recorder

    result = _core.run(app, design, request, session_wrapper=record if record_trace else None)
    if recorders and isinstance(result, dict):
        recorder = recorders[-1]
        result["playback"] = recorder.recording(
            test=test,
            requested=dict(result.get("requested") or config),
            limitations=list(result.get("limitations") or []))
    return result


# Preserve direct helpers for tests and specialist callers. API/MCP uses run().
run_contract = _core.run_contract
run_force = _core.run_force
run_cart = _core.run_cart
run_kettle = _core.run_kettle
run_machine = _core.run_machine
_cart_spec = _core._cart_spec
