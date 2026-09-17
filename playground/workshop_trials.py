"""Workshop isolated trials with visual playback.

The physics setup and measurements stay in ``workshop_trials_core``.  This layer
supplies a recording session factory so declared/static-load trials return the
same measured evidence plus a timeline the Workshop can render.
"""
from __future__ import annotations

from typing import Any

import workshop_trials_core as _core
from workshop_trials_core import *  # noqa: F401,F403
import workshop_recording

_BASE_RUN_STATIC = _core.run_static_load
_BASE_SESSION = _core.live_session.Session


def run_static_load(app: Any, design, *, load_kg: float, on: str = "top",
                    cell_size_m: float = _core.DEFAULT_CELL_M,
                    duration_s: float = _core.DEFAULT_DURATION_S,
                    session_factory=None) -> dict[str, Any]:
    base_factory = session_factory or _BASE_SESSION
    holder: list[workshop_recording.Recorder] = []

    def factory(*args: Any, **kwargs: Any):
        recorder = workshop_recording.wrap(base_factory(*args, **kwargs))
        holder.append(recorder)
        return recorder

    result = _BASE_RUN_STATIC(
        app, design, load_kg=load_kg, on=on,
        cell_size_m=cell_size_m, duration_s=duration_s,
        session_factory=factory)
    if holder:
        result["playback"] = holder[-1].recording(
            test="static_load", requested=dict(result.get("requested") or {}),
            limitations=list(result.get("limitations") or []))
    return result


# Core run_declared_static_load resolves core.run_static_load at runtime.
_core.run_static_load = run_static_load
run_declared_static_load = _core.run_declared_static_load
prototype_scene = _core.prototype_scene
