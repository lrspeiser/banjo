"""Functional Workshop bench with generic visual playback recordings.

The tested bench implementation remains in ``workshop_bench_core``. Engine
sessions are transparently wrapped while a test runs; the solver receives the
same calls and the result gains a browser-neutral playback timeline.
"""
from __future__ import annotations

import threading
from typing import Any

import workshop_bench_core as _core
from workshop_bench_core import *  # noqa: F401,F403
import workshop_recording
import workshop_trials

_BASE_SESSION = _core.live_session.Session
_record_lock = threading.RLock()
_LOAD_KINDS = {"table", "stool", "bench", "chair", "shelf-unit", "cart"}


def catalog(kind: str | None = None) -> list[dict[str, Any]]:
    out = _core.catalog(kind)
    if kind in _LOAD_KINDS:
        out.append({
            "test": "declared_static_load", "name": "Load the product",
            "about": "Run this product's own declared static load in an isolated physics world and watch the bodies move, rotate or fracture.",
            "controls": [
                {"name": "duration_s", "label": "Run", "unit": "s", "type": "number", "default": 2.0, "min": 0.2, "max": 10.0, "step": 0.1},
                {"name": "cell_size_m", "label": "Matter resolution", "unit": "m", "type": "number", "default": 0.04, "min": 0.01, "max": 0.12, "step": 0.01},
            ],
            "limitations": ["The load is the design's authored load case. If no acceptance tolerance is declared, the run remains measured evidence rather than an invented pass/fail."],
            "visual_playback": True,
        })
    for item in out:
        name = str(item.get("test") or "")
        item["visual_playback"] = bool(item.get("visual_playback")) or name in {
            "cart_roll", "kettle_heat", "machine_control", "declared_static_load"
        }
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
    if test == "declared_static_load":
        return workshop_trials.run_declared_static_load(
            app, design,
            cell_size_m=float(config.get("cell_size_m", 0.04)),
            duration_s=float(config.get("duration_s", 2.0)))

    recorders: list[workshop_recording.Recorder] = []

    def factory(*args: Any, **kwargs: Any):
        recorder = workshop_recording.wrap(_BASE_SESSION(*args, **kwargs))
        recorders.append(recorder)
        return recorder

    # live_session is shared by Live.open and direct Session callers. Keep the
    # swap bounded to one test so ordinary room sessions never become Workshop
    # recordings. The current bench already serializes its scratch world work.
    with _record_lock:
        original = _core.live_session.Session
        _core.live_session.Session = factory
        try:
            result = _core.run(app, design, request)
        finally:
            _core.live_session.Session = original
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
