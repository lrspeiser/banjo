"""Functional Workshop bench with generic visual playback recordings.

The tested bench implementation remains in ``workshop_bench_core``.  Engine
sessions are transparently wrapped while a test runs; the solver receives the
same calls and the result gains a browser-neutral playback timeline.
"""
from __future__ import annotations

import threading
from typing import Any

import workshop_bench_core as _core
from workshop_bench_core import *  # noqa: F401,F403
import workshop_recording

_BASE_SESSION = _core.live_session.Session
_record_lock = threading.RLock()


def catalog(kind: str | None = None) -> list[dict[str, Any]]:
    out = _core.catalog(kind)
    for item in out:
        name = str(item.get("test") or "")
        item["visual_playback"] = name in {"cart_roll", "kettle_heat", "machine_control"}
        if name in {"runtime_contract", "force_probe"}:
            item["visual_overlay"] = True
    return out


def run(app: Any, design, request: Any) -> dict[str, Any]:
    if not isinstance(request, dict):
        raise ValueError("bench_test must be an object")
    test = str(request.get("test") or "")
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
            requested=dict(result.get("requested") or request.get("config") or {}),
            limitations=list(result.get("limitations") or []))
    return result


# Preserve direct helpers for tests and specialist callers. API/MCP uses run().
run_contract = _core.run_contract
run_force = _core.run_force
run_cart = _core.run_cart
run_kettle = _core.run_kettle
run_machine = _core.run_machine
