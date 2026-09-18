"""Workshop isolated trials with visual playback.

The compatibility trial implementation remains in ``workshop_trials_core`` for
specialist callers, but the Workshop product path now runs through
``workshop_sparse_trial``: the same canonical Matter cells shown in the viewport
are losslessly decomposed into joined grid-aligned boxes and handed to the live
engine. The recording wrapper is still transparent to solver behavior.
"""
from __future__ import annotations

from typing import Any

import workshop_trials_core as _core
from workshop_trials_core import *  # noqa: F401,F403
import workshop_recording
import workshop_sparse_trial
from mcp import workshop_acceptance, workshop_rigid

_BASE_RUN_STATIC = workshop_sparse_trial.run_static_load
_BASE_SESSION = _core.live_session.Session


def run_static_load(app: Any, design, *, load_kg: float, on: str = "top",
                    cell_size_m: float = _core.DEFAULT_CELL_M,
                    duration_s: float = _core.DEFAULT_DURATION_S,
                    session_factory=None, record_trace: bool = True,
                    acceptance_limits: Any = None) -> dict[str, Any]:
    workshop_rigid.require_lattice(design, "Static-load fracture testing")
    if not isinstance(record_trace, bool):
        raise ValueError("record_trace must be a boolean")
    limits = workshop_acceptance.checked_limits(acceptance_limits)
    base_factory = session_factory or _BASE_SESSION
    holder: list[workshop_recording.Recorder] = []

    def factory(*args: Any, **kwargs: Any):
        recorder = workshop_recording.wrap(base_factory(*args, **kwargs))
        holder.append(recorder)
        return recorder

    result = _BASE_RUN_STATIC(
        app, design, load_kg=load_kg, on=on,
        cell_size_m=cell_size_m, duration_s=duration_s,
        session_factory=factory if record_trace else base_factory)
    if limits is not None:
        result["acceptance"] = workshop_acceptance.evaluate(result, limits)
    geometry = result.pop("render_geometry", {})
    if holder:
        result["playback"] = holder[-1].recording(
            test="static_load", requested=dict(result.get("requested") or {}),
            limitations=list(result.get("limitations") or []))
        result["playback"]["geometry"] = geometry
        # Every piece a load leaves is drawn as its own cells, like a blow's.
        result["playback"]["geometry_basis"] = "verified-native-cells-and-native-pieces"
        result["playback"]["fractures"] = list((result.get("measured") or {}).get("fractures") or [])
    return result


def run_declared_static_load(app: Any, design, **options: Any) -> dict[str, Any]:
    trial = next((t for t in design.tests if t.get("kind") == "static_load"), None)
    if trial is None:
        raise ValueError("this design declares no static_load trial")
    options["acceptance_limits"] = workshop_acceptance.merge_limits(
        trial.get("acceptance_limits"), options.get("acceptance_limits"))
    return run_static_load(app, design, load_kg=float(trial.get("load_kg", 0)),
                           on=str(trial.get("on") or "top"), **options)


# Product-facing scene preview is now the exact Matter scene. Keep the old
# private grid helpers because kettle setup and regression tests already consume
# them and they remain useful for legacy primitive fixtures.
prototype_scene = workshop_sparse_trial.prototype_scene
_fits_cell = _core._fits_cell
_effective_cell = _core._effective_cell
