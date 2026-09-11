"""A live scene the panel can reach into, instead of a recording it plays.

`banjo_live_world_run` holds one world open and speaks JSON over stdin and stdout,
one object per line. This owns that process for the length of a session, keeps the
last state it reported, and closes it when the next one opens -- one live world at
a time, because each is a physics engine with the scene resident in it.

Every reply carries the whole world. That is only affordable because a body that
was authored as one shape is now drawn as one body: a bowling lane is 12 poses,
about a kilobyte, where the same scene as cells was 9,841.
"""
from __future__ import annotations

import json
import math
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import fracture_lab

# A scene bigger than this is refused rather than left to crawl. The rigid step
# itself is microseconds; what grows is the reply and the contact work.
MAX_BODIES = 250
# How long to wait for one line back. A step is sub-millisecond and a fracture is
# a few hundred milliseconds, so anything past this is a hang, not slowness.
REPLY_TIMEOUT_S = 60.0
# What a host may ask for in one call, so a slow client cannot ask for an hour of
# simulated time in a single request. A call costs about 0.9 ms of round trip and
# each step inside it about two microseconds, so this is a bound on how far the
# world can run without the host getting a look in -- a second of scene -- rather
# than a bound on cost. It matters because a browser throttles a tab it is not
# showing to about one tick a second, and a cap of 20 would have such a tab
# crawling at a fifth of real time for a reason that has nothing to do with the
# physics.
MAX_STEPS_PER_CALL = 120
MAX_DT_S = 1.0 / 30.0


class LiveError(ValueError):
    """Something the caller can fix: a bad scene, a body that cannot be moved."""


class Session:
    """One open world."""

    def __init__(self, engine_path: Path, spec: dict[str, Any], runs_path: Path) -> None:
        # Anything the panel can describe can be run live. A plate-and-ball spec
        # is translated into the objects it already is, rather than refused for
        # being the wrong shape.
        bodies = fracture_lab.as_objects(spec)
        if not bodies:
            raise LiveError("This scene has nothing in it to simulate.")
        spec = dict(spec, bodies=bodies)
        if len(bodies) > MAX_BODIES:
            raise LiveError(f"{len(bodies)} objects is more than a live world will hold "
                            f"({MAX_BODIES}).")
        exe = fracture_lab.executable(engine_path, "lattice").with_name(
            "banjo_live_world_run" + engine_path.suffix)
        if not exe.is_file():
            raise LiveError(f"the live engine is not built yet ({exe.name} is missing "
                            f"next to the engine)")
        self.id = uuid.uuid4().hex
        self.spec = spec
        directory = runs_path / ("live-" + self.id)
        directory.mkdir(parents=True, exist_ok=True)
        scene = directory / "scene.json"
        scene.write_text(json.dumps(fracture_lab.scene_document(spec), indent=1),
                         encoding="utf-8")
        self._lock = threading.Lock()
        self._process = subprocess.Popen(
            [str(exe), "--scene", str(scene), "--cell", f"{spec['cell_m']:.6g}"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", bufsize=1, cwd=str(directory))
        self.opened_at = time.time()
        self.state = self._read("opening the world")
        if not self.state.get("ok"):
            raise LiveError(self.state.get("error") or "the live world refused this scene")

    # -- the wire ----------------------------------------------------------
    def _read(self, what: str) -> dict[str, Any]:
        line = self._process.stdout.readline() if self._process.stdout else ""
        if not line:
            detail = ""
            if self._process.stderr:
                detail = self._process.stderr.read()[-400:].strip()
            raise LiveError(f"the live world stopped while {what}"
                            + (f": {detail}" if detail else ""))
        return json.loads(line)

    def send(self, **command: Any) -> dict[str, Any]:
        with self._lock:
            if self._process.poll() is not None:
                raise LiveError("this live world has closed; start a new one")
            assert self._process.stdin is not None
            self._process.stdin.write(json.dumps(command) + "\n")
            self._process.stdin.flush()
            state = self._read(f"handling {command.get('op')}")
        if not state.get("ok"):
            raise LiveError(state.get("error") or "the live world refused that")
        self.state = state
        return state

    def close(self) -> None:
        if self._process.poll() is not None:
            return
        try:
            assert self._process.stdin is not None
            self._process.stdin.write('{"op":"quit"}\n')
            self._process.stdin.flush()
            self._process.wait(timeout=5)
        except Exception:
            self._process.kill()


class Live:
    """The one open world, and the operations the panel can ask of it."""

    def __init__(self) -> None:
        self.session: Session | None = None
        self._lock = threading.Lock()

    def open(self, app: Any, body: Any) -> dict[str, Any]:
        if not isinstance(body, dict):
            raise LiveError("A live request must be an object")
        spec = fracture_lab.validate(body.get("spec") or {})
        with self._lock:
            if self.session is not None:
                self.session.close()
                self.session = None
            session = Session(app.engine_path, spec, app.runs_path)
            self.session = session
        return {"session": session.id, "spec": spec, **session.state}

    def _current(self, session_id: str) -> Session:
        session = self.session
        if session is None or session.id != session_id:
            raise LiveError("that live world is no longer open; start a new one")
        return session

    def act(self, body: Any) -> dict[str, Any]:
        if not isinstance(body, dict):
            raise LiveError("A live request must be an object")
        session = self._current(str(body.get("session", "")))
        op = str(body.get("op", ""))
        if op == "step":
            dt = min(float(body.get("dt", 1 / 60.0)), MAX_DT_S)
            count = max(1, min(int(body.get("n", 1)), MAX_STEPS_PER_CALL))
            if not dt > 0.0:
                raise LiveError("a step needs a positive dt")
            return session.send(op="step", dt=dt, n=count)
        if op == "grab":
            return session.send(op="grab", name=str(body.get("name", "")))
        if op == "move":
            to = body.get("to")
            if not isinstance(to, list) or len(to) != 3:
                raise LiveError("move needs a position of three numbers")
            return session.send(op="move", to=[float(v) for v in to])
        if op in ("release", "poses"):
            return session.send(op=op)
        if op == "pick":
            # A ray in world metres. Costs no step and changes nothing, so it is
            # not bounded the way a step is -- but it is still checked, because
            # a ray of NaNs would reach the engine otherwise.
            def ray(key: str) -> list[float]:
                value = body.get(key)
                if not isinstance(value, list) or len(value) != 3:
                    raise LiveError(f"pick needs {key} as three numbers")
                out = [float(v) for v in value]
                if not all(math.isfinite(v) for v in out):
                    raise LiveError(f"pick was given a {key} that is not a number")
                return out
            return session.send(op="pick", **{"from": ray("from"), "dir": ray("dir"),
                                              "max_m": float(body.get("max_m", 1000.0))})
        if op == "fracture":
            return session.send(op="fracture", name=str(body.get("name", "")),
                                window_s=float(body.get("window_s", 0.003)))
        if op == "close":
            with self._lock:
                session.close()
                if self.session is session:
                    self.session = None
            return {"ok": True, "closed": True}
        raise LiveError(f"unknown live operation: {op}")

    def shutdown(self) -> None:
        with self._lock:
            if self.session is not None:
                self.session.close()
                self.session = None
