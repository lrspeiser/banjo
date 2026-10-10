"""Driving a thing at the bench with the keys (docs/workshop-mode.md, "Drive
it"): the little world kept open, stepped as the keys arrive, and every
frame sent back to be drawn as it happens.

The owner: "allow me to become the object and control it with the keys and
it should be able to turn and go etc." A precomputed run with orders at the
start is not that. This is: one little world (workshop_test_room.Bench) is
made and kept; each call of `step` says which keys are down and how much
time to let pass; the keys become an ask on the thing's program -- going
forward, backing off, turning left, turning right, waiting -- the same ask
a person's panel and Jev make in the world (LiveWorld::behave), or, for a
machine with wheels but no program, the wheels' own controls, the same
operate the panel sends; the room runs that long; and the frames it
recorded meanwhile come back. `stop` closes the room and hands back the
whole recording, which the bench keeps as a take.

One drive at a time to a server; a drive nobody has stepped for IDLE_S is
closed by the next start. The world is untouched throughout: none of this
is the world's session.
"""
from __future__ import annotations

import math
import time
from typing import Any

import workshop_recording
import workshop_test_room as rooms

IDLE_S = 90.0
STEP_MOST_S = 0.5
FRAMES_MOST = 12000                     # ten minutes at the recorder's thirtieth of a second
# The keys, in the order one wins over another: a machine does one thing at a
# time, and going up or down is the deliberate key, so it wins while it is
# held. Rising and descending are a flying machine's only (LiveWorld::behave
# refuses them to anything else), so they are skipped for the rest.
ASKS = (("up", "rising"), ("down", "descending"), ("left", "turning left"), ("right", "turning right"),
        ("forward", "going forward"), ("back", "backing off"))
FLIES_ONLY = {"rising", "descending"}
# Wheels, for a machine without a program: left and right, forward and back.
WHEELS = {"going forward": (1, 1), "backing off": (-1, -1), "turning left": (-1, 1), "turning right": (1, -1),
          "waiting": (0, 0)}


class Drive:
    def __init__(self, app: Any, candidate: dict[str, Any]):
        self.room = rooms.Bench(app)
        try:
            self.made = self.room.make(candidate)
            self.room.watch()
            self.room.recorder.max_frames = FRAMES_MOST
            self.room.remember_poses()
            began = self.room.reading()
            self.programs = list(began.get("programs") or [])
            self.controls = {str(c.get("name")): c for c in began.get("controls") or []}
            self.steers = "program" if self.programs else "wheels" if len(self.controls) >= 2 else "none"
            self.flies = bool(self.programs) and str(self.programs[0].get("kind") or "") == "hover"
            self.wheels: tuple[str, str] | None = None
            if self.steers == "wheels":
                names = list(self.controls)
                left = next((n for n in names if "left" in n.lower()), names[0])
                right = next((n for n in names if "right" in n.lower() and n != left), next(n for n in names if n != left))
                self.wheels = (left, right)
            if self.steers == "program":
                self.room.turn_on()
            self.asked: str | None = None
            self.seq = 0
            self.sent = 0
            self.touched = time.monotonic()
            self.t_s = 0.0
            self.ask("waiting")
            # Two frames, so the recording is a recording before the first step.
            self.room.run(2 * rooms.DT * 8)
        except Exception:
            self.room.close()
            raise

    @property
    def root(self) -> str:
        return str(self.made.get("root_body") or "")

    @staticmethod
    def energy(reading: dict[str, Any]) -> dict[str, Any] | None:
        """What the thing's battery holds and what it is spending right now
        (docs/machine-world.md): the store, what its motors are asking of it
        this step and what its panels are putting back. A machine switched
        off, or standing on the ground with its rotors stopped, asks for
        nothing, and this says so."""
        stores = reading.get("stores") or []
        if not stores:
            return None
        store = stores[0]
        ident = store.get("id")
        using = sum(float(m.get("power_w") or 0.0) for m in reading.get("motors") or []
                    if m.get("store") == ident)
        taking = sum(float(p.get("power_w") or 0.0) for p in reading.get("panels") or []
                     if p.get("store") == ident)
        charge, capacity = float(store.get("charge_j") or 0.0), float(store.get("capacity_j") or 0.0)
        net = using - taking
        return {"name": store.get("name"), "charge_j": round(charge, 1), "capacity_j": round(capacity, 1),
                "share": round(charge / capacity, 4) if capacity > 0 else None,
                "using_w": round(using, 1), "taking_w": round(taking, 1),
                "left_s": round(charge / net, 1) if net > 1e-6 else None}

    def ask(self, doing: str) -> None:
        """What the keys say, put to the thing once per change."""
        if doing == self.asked:
            return
        self.asked = doing
        if self.steers == "program":
            self.seq += 1
            # A person at the keys is a person ordering it (LiveProgram::
            # asked_by_person): what they steer it into is their business, and
            # its water reflex does not overrule them.
            self.room.live.session.send(op="behave", program=self.programs[0]["id"], sender="drive",
                                        seq=self.seq, doing=doing, for_s=0.0, by_person=True,
                                        why="the person at the keys")
        elif self.steers == "wheels" and self.wheels:
            left, right = WHEELS.get(doing, (0, 0))
            self.room.work(self.wheels[0], power=True, direction=left, setting=1.0)
            self.room.work(self.wheels[1], power=True, direction=right, setting=1.0)

    def step(self, keys: dict[str, Any], dt_s: float) -> dict[str, Any]:
        self.touched = time.monotonic()
        doing = "waiting"
        for key, ask in ASKS:
            if not keys.get(key):
                continue
            if ask in FLIES_ONLY and not self.flies:
                continue
            doing = ask
            break
        self.ask(doing)
        dt_s = max(rooms.DT, min(STEP_MOST_S, float(dt_s)))
        frames = self.room.recorder.frames
        before = len(frames)
        reading = self.room.run(dt_s)
        self.t_s += dt_s
        fresh = [f for f in frames[before:]]
        for frame in fresh:
            frame["bodies"] = [b for b in frame.get("bodies") or [] if rooms._worth_watching(b)]
        program = (reading.get("programs") or [None])[0]
        body = (reading.get("bodies") or {}).get(self.root) or {}
        return {"frames": fresh, "t_s": round(self.t_s, 3), "asked": self.asked,
                "energy": self.energy(reading),
                "doing": (program or {}).get("doing"), "why": (program or {}).get("why"),
                "at_m": body.get("at_m"), "speed_m_s": body.get("speed_m_s"), "turn_deg": body.get("turn_deg"),
                "fell_over": rooms.fell_over(body),
                "broke": reading.get("broke") or [], "frames_kept": len(frames)}

    def recording(self) -> dict[str, Any] | None:
        out = self.room.playback(test="drive")
        if out is not None:
            out["geometry_basis"] = "recorded-native-shapes"
        return out

    def close(self) -> None:
        self.room.close()


def _current(app: Any) -> Drive | None:
    return getattr(app, "workshop_drive", None)


def start(app: Any, body: dict[str, Any]) -> dict[str, Any]:
    candidate = body.get("candidate")
    if not isinstance(candidate, dict):
        raise ValueError("driving needs the design it is made from: candidate")
    old = _current(app)
    if old is not None:
        old.close()
        app.workshop_drive = None
    drive = Drive(app, candidate)
    app.workshop_drive = drive
    began = drive.recording()
    return {"schema": "banjo.workshop-drive.v1", "status": "driving", "steers": drive.steers,
            "flies": drive.flies,
            "kind": (drive.programs[0].get("kind") if drive.programs else None),
            "program": (drive.programs[0].get("name") if drive.programs else None),
            "wheels": list(drive.wheels) if drive.wheels else [],
            "root_body": drive.root, "recording": began, "energy": drive.energy(drive.room.reading()),
            "keys": {"forward": "W or up", "back": "S or down", "left": "A or left", "right": "D or right",
                     **({"up": "Space", "down": "Shift+Space"} if drive.flies else {})}}


def step(app: Any, body: dict[str, Any]) -> dict[str, Any]:
    drive = _current(app)
    if drive is None:
        raise ValueError("nothing is being driven: start first")
    keys = body.get("keys") if isinstance(body.get("keys"), dict) else {}
    return {"schema": "banjo.workshop-drive.v1", "status": "driving", **drive.step(keys, body.get("dt_s", 0.125))}


def stop(app: Any, body: dict[str, Any] | None = None) -> dict[str, Any]:
    drive = _current(app)
    if drive is None:
        return {"schema": "banjo.workshop-drive.v1", "status": "stopped", "recording": None}
    try:
        reading = drive.room.reading()
        recording = drive.recording()
        body_now = (reading.get("bodies") or {}).get(drive.root) or {}
        start_at = None
        if recording and recording.get("frames"):
            first = next((b for b in recording["frames"][0].get("bodies") or [] if b.get("name") == drive.root), None)
            start_at = first.get("position_m") if first else None
        moved = (math.dist(body_now.get("at_m") or [0, 0, 0], start_at) if start_at and body_now.get("at_m") else None)
        says = (f"driven for {drive.t_s:.1f} s" + (f", {moved:.2f} m from where it stood" if moved is not None else "")
                + (f", turned {body_now.get('turn_deg', 0):.0f} degrees" if body_now else "")
                + ("; it fell over" if rooms.fell_over(body_now) else ""))
    finally:
        drive.close()
        app.workshop_drive = None
    return {"schema": "banjo.workshop-drive.v1", "status": "stopped", "recording": recording,
            "driven_s": round(drive.t_s, 3), "moved_m": None if moved is None else round(moved, 4), "says": says}


def handle(app: Any, body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise ValueError("expected {action: start | step | stop, ...}")
    action = str(body.get("action") or "")
    if action == "start":
        return start(app, body)
    if action == "step":
        return step(app, body)
    if action == "stop":
        return stop(app, body)
    raise ValueError("action is start, step or stop")


def sweep(app: Any) -> None:
    """A drive nobody has stepped for a while is closed (the server, on a start)."""
    drive = _current(app)
    if drive is not None and time.monotonic() - drive.touched > IDLE_S:
        drive.close()
        app.workshop_drive = None
