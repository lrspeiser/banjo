"""Generic visual recordings for isolated Workshop physics runs.

A Workshop test already receives authoritative LiveWorld states.  This module
captures those states without changing solver behavior, producing a compact
browser-neutral timeline the Workshop viewport can play, pause and scrub.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

RECORDING_SCHEMA = "banjo.workshop-physics-run.v1"


def _body(body: dict[str, Any]) -> dict[str, Any]:
    out = {
        "name": str(body.get("name") or ""),
        "position_m": [float(v) for v in body.get("position_m") or [0, 0, 0]],
        "orientation_wxyz": [float(v) for v in body.get("orientation_wxyz") or [1, 0, 0, 0]],
    }
    for key in ("dimensions_m", "material", "shape", "anchored", "revision"):
        if body.get(key) is not None:
            out[key] = deepcopy(body[key])
    return out


def frame(state: Any, *, event: str | None = None) -> dict[str, Any] | None:
    if not isinstance(state, dict):
        return None
    bodies = state.get("bodies") or []
    if not isinstance(bodies, list):
        bodies = []
    result: dict[str, Any] = {
        "t_s": round(float(state.get("t", 0.0) or 0.0), 6),
        "bodies": [_body(body) for body in bodies if isinstance(body, dict)],
    }
    if event:
        result["event"] = str(event)
    joints = state.get("joints")
    if isinstance(joints, list):
        result["joints"] = deepcopy(joints)
    machines = state.get("machines")
    if isinstance(machines, dict):
        result["machines"] = deepcopy(machines)
    return result


class Recorder:
    """Record states returned by an existing session-like object.

    It is a transparent proxy: solver calls and their answers are untouched.
    Duplicate timestamps are coalesced unless they carry a named event.
    """
    def __init__(self, session: Any, *, max_frames: int = 600) -> None:
        self.session = session
        self.max_frames = max(2, int(max_frames))
        self.frames: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self.capture(getattr(session, "state", None), event="start")

    def capture(self, state: Any, *, event: str | None = None) -> None:
        item = frame(state, event=event)
        if item is None:
            return
        if self.frames and self.frames[-1]["t_s"] == item["t_s"] and not event:
            self.frames[-1] = item
            return
        if len(self.frames) >= self.max_frames:
            # Preserve endpoints while thinning the interior deterministically.
            self.frames = [self.frames[0], *self.frames[2::2]]
        self.frames.append(item)
        if event:
            self.events.append({"t_s": item["t_s"], "event": event})

    def send(self, **command: Any) -> Any:
        answer = self.session.send(**command)
        op = str(command.get("op") or "")
        event = op if op in {"fracture", "operate", "heat", "stroke", "drive"} else None
        if op in {"step", "poses", "fracture", "operate", "heat", "stroke", "drive", "joints"}:
            self.capture(answer, event=event)
        return answer

    def recording(self, *, test: str, requested: dict[str, Any] | None = None,
                  limitations: list[str] | None = None) -> dict[str, Any]:
        duration = self.frames[-1]["t_s"] - self.frames[0]["t_s"] if len(self.frames) > 1 else 0.0
        return {
            "schema": RECORDING_SCHEMA,
            "test": str(test),
            "duration_s": round(duration, 6),
            "frames": self.frames,
            "events": self.events,
            "requested": deepcopy(requested or {}),
            "limitations": list(limitations or []),
        }


def wrap(session: Any, *, max_frames: int = 600) -> Recorder:
    return Recorder(session, max_frames=max_frames)
