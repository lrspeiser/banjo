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
    thermo = state.get("thermo")
    if isinstance(thermo, dict):
        result["thermo"] = deepcopy(thermo)
    machines = state.get("machines")
    if isinstance(machines, dict):
        result["machines"] = deepcopy(machines)
    return result


class Recorder:
    """Record states returned by an existing session-like object.

    It is a transparent proxy: solver calls and their answers are untouched.
    Duplicate timestamps are coalesced unless they carry a named event.
    """
    sample_period_s = 1.0 / 30.0

    def __init__(self, session: Any, *, max_frames: int = 600) -> None:
        self.session = session
        self.max_frames = max(2, int(max_frames))
        self.frames: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self.events_truncated = False
        self.thinned = False
        self.effective_period_s = self.sample_period_s
        self._tail = False
        self._next_sample_s = None
        self.capture(getattr(session, "state", None), event="start")

    def __getattr__(self, name: str) -> Any:
        return getattr(self.session, name)

    @property
    def state(self) -> Any:
        return getattr(self.session, "state", None)

    def close(self) -> Any:
        return self.session.close()

    def _event(self, t_s: float, event: str) -> None:
        if len(self.events) >= self.max_frames * 4:
            self.events_truncated = True
            self.events.pop(0)
        self.events.append({"t_s": t_s, "event": event})

    def capture(self, state: Any, *, event: str | None = None) -> None:
        item = frame(state, event=event)
        if item is None:
            return
        # Replies such as `joints` can carry only the queried subsystem. Never
        # replace a full pose frame with an empty-body reply at the same time.
        if not item["bodies"]:
            if self.frames and isinstance(state, dict):
                # Query replies often have no clock. Attach only at the current
                # session time, never make an empty pose frame at t=0.
                now = float(state.get("t", (self.state or {}).get("t", 0)))
                if abs(self.frames[-1]["t_s"] - now) < 1e-6:
                    for key in ("joints", "machines", "thermo"):
                        if key in state:
                            self.frames[-1][key] = deepcopy(state[key])
                    if event:
                        self._event(now, event)
            return
        if event:
            self._event(item["t_s"], event)
        if self.frames and self.frames[-1]["t_s"] == item["t_s"]:
            # Keep subsystem snapshots from a query when the next pose reply
            # carries no subsystem state of its own.
            self.frames[-1].update(item)
            return
        if not self.frames:
            self.frames.append(item)
            self._next_sample_s = item["t_s"] + self.effective_period_s
            return
        if item["t_s"] < self.frames[-1]["t_s"]:
            return  # A clockless subsystem reply is not an earlier pose.
        if self._tail:
            self.frames.pop()
        scheduled = item["t_s"] >= self._next_sample_s - 1e-6
        self.frames.append(item)  # Always preserve the latest actual state.
        self._tail = not scheduled
        if scheduled:
            self._next_sample_s = item["t_s"] + self.effective_period_s
        if len(self.frames) >= self.max_frames:
            self.thinned = True
            # Once capacity is reached, thin the entire time span and sample
            # future states at that same spacing. Repeatedly halving only the
            # old prefix otherwise destroys early detail exponentially.
            self.effective_period_s *= 2
            first, latest = self.frames[0], self.frames[-1]
            kept = [first]
            for saved in self.frames[1:-1]:
                if saved["t_s"] - kept[-1]["t_s"] >= self.effective_period_s - 1e-6:
                    kept.append(saved)
            if latest["t_s"] != kept[-1]["t_s"]:
                self._tail = latest["t_s"] - kept[-1]["t_s"] < self.effective_period_s - 1e-6
                kept.append(latest)
            else:
                self._tail = False
            self.frames = kept
            last_regular = kept[-2] if self._tail else kept[-1]
            self._next_sample_s = last_regular["t_s"] + self.effective_period_s

    def send(self, **command: Any) -> Any:
        answer = self.session.send(**command)
        op = str(command.get("op") or "")
        event = op if op in {"fracture", "operate", "heat", "stroke", "drive"} else None
        if op in {"step", "poses", "fracture", "operate", "heat", "stroke", "drive", "joints", "thermo"}:
            self.capture(answer, event=event)
        return answer

    def recording(self, *, test: str, requested: dict[str, Any] | None = None,
                  limitations: list[str] | None = None) -> dict[str, Any]:
        duration = self.frames[-1]["t_s"] - self.frames[0]["t_s"] if len(self.frames) > 1 else 0.0
        return {
            "schema": RECORDING_SCHEMA,
            "geometry_basis": "recorded-poses-with-reduced-collision-proxies",
            "test": str(test),
            "duration_s": round(duration, 6),
            "sampling": {"requested_period_s": self.sample_period_s,
                         "thinned": self.thinned,
                         "effective_period_s": self.effective_period_s,
                         "max_gap_s": max((b["t_s"] - a["t_s"]
                                           for a, b in zip(self.frames, self.frames[1:])), default=0.0)},
            "frames": self.frames,
            "events": self.events,
            "events_truncated": self.events_truncated,
            "requested": deepcopy(requested or {}),
            "limitations": list(limitations or []),
        }


def wrap(session: Any, *, max_frames: int = 600) -> Recorder:
    return Recorder(session, max_frames=max_frames)
