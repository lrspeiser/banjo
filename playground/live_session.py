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
import logging
import math
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import fracture_lab
import live_inprocess

# A scene bigger than this is refused rather than left to crawl. The rigid step
# itself is microseconds; what grows is the reply and the contact work.
MAX_BODIES = 250
# How long to wait for one line back. A step is sub-millisecond and a fracture is
# a few hundred milliseconds, so anything past this is a hang, not slowness.
REPLY_TIMEOUT_S = 60.0
# How long closing a world waits for a call already inside the engine to come
# back. The server answers on many threads, so a call for the old room can still
# be in flight when the page opens a new one. Past this the engine is taken to
# be hung and is killed, which is what ends that call -- unbounded, one engine
# that stopped answering would hold every room shut behind it.
CLOSE_WAIT_S = 5.0
# What a call to a world that has gone is told, however it went.
_CLOSED = "this live world has closed; start a new one"
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

_log = logging.getLogger("banjo.live")


class LiveError(ValueError):
    """Something the caller can fix: a bad scene, a body that cannot be moved."""


def _three(value: Any, what: str) -> list[float]:
    """Three finite numbers, or a refusal that says which were wrong."""
    if not isinstance(value, list) or len(value) != 3:
        raise LiveError(f"{what} needs three numbers")
    out = [float(v) for v in value]
    if not all(math.isfinite(v) for v in out):
        raise LiveError(f"{what} was given something that is not a number")
    return out


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
        self._closed = False
        self._process = subprocess.Popen(
            [str(exe), "--scene", str(scene), "--cell", f"{spec['cell_m']:.6g}"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", bufsize=1, cwd=str(directory))
        self.opened_at = time.time()
        self.state: dict[str, Any] = {}
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
        line = json.dumps(command) + "\n"
        with self._lock:
            if self._closed or self._process.poll() is not None:
                raise LiveError(_CLOSED)
            assert self._process.stdin is not None
            # The pipes can still go out from under a call that got past that
            # check. An engine can die on its own; and close(), which takes this
            # lock so that it never shuts the pipes under a call it is waiting
            # for, frees one it has given up on by killing the engine. What that
            # looks like here depends on the moment -- EINVAL or a broken pipe
            # from the write, a ValueError from a file already shut, nothing or
            # half a line from the read -- and none of it is a stack trace for
            # the caller. Every caller already handles a world that has closed.
            try:
                self._process.stdin.write(line)
                self._process.stdin.flush()
                state = self._read(f"handling {command.get('op')}")
            except (OSError, ValueError) as error:
                # LiveError and a garbled reply are ValueErrors too, and each
                # says something of its own -- unless the world was closed under
                # this call, which is then the only thing worth saying.
                if not self._closed and isinstance(error, (LiveError,
                                                           json.JSONDecodeError)):
                    raise
                raise LiveError(_CLOSED) from error
        if not state.get("ok"):
            raise LiveError(state.get("error") or "the live world refused that")
        # Only a reply that describes the world replaces this side's picture of
        # it. `pick` and `collect` answer about one thing and carry no bodies at
        # all, and taking those as the world left `self.state` with no bodies in
        # it -- every caller on this side then saw an empty room.
        if "bodies" in state:
            self.state = self._whole(state)
        elif state.get("collected"):
            # A sweep carries no bodies, but it did change the world: it took
            # some away, and it names them. Applying that here keeps this side's
            # picture right without asking for the whole room back.
            went = {name for lot in state["collected"] for name in lot.get("took") or ()}
            if went and self.state.get("bodies"):
                self.state = {**self.state,
                              "bodies": [b for b in self.state["bodies"]
                                         if b["name"] not in went]}
        # Anything the world waited on goes to the server's log, so a run that
        # stalls leaves a trace behind rather than only an impression.
        for wait in state.get("waits") or ():
            kind = wait.get("kind", "?")
            if kind == "foreseen":
                _log.info("banjo: %s coming in %.0f ms (t=%.2f s)",
                          wait.get("object"), wait.get("lead_ms", 0.0), wait.get("at_s", 0.0))
            elif kind == "precomputed":
                # The run, and separately how long it sat waiting for a worker.
                # Rolling the two together made the log report a 30 ms fracture
                # as a 4 second one.
                queued = wait.get("lead_ms", 0.0)
                _log.info("banjo: %s %s, %.0f ms of run%s (t=%.2f s)",
                          kind, wait.get("object"), wait.get("cost_ms", 0.0),
                          f", {queued:.0f} ms queued" if queued >= 1.0 else "",
                          wait.get("at_s", 0.0))
            else:
                _log.info("banjo: %s %s, %.0f ms (t=%.2f s)",
                          kind, wait.get("object"), wait.get("cost_ms", 0.0),
                          wait.get("at_s", 0.0))
        return state

    def _whole(self, reply: dict[str, Any]) -> dict[str, Any]:
        """The world as it now stands, whichever way the reply arrived.

        A reply marked `partial` carries only the bodies that moved, because
        sending two hundred motionless ones thirty times a second was most of
        the cost of running the room. Everything on this side -- the tools, the
        tests, anything asking what the world looks like -- still wants all of
        them, so the last full picture is kept here and the changes folded in.
        """
        if not reply.get("partial"):
            return reply
        bodies = {body["name"]: body for body in (self.state or {}).get("bodies", ())}
        for name in reply.get("gone") or ():
            bodies.pop(name, None)
        for body in reply.get("bodies", ()):
            bodies[body["name"]] = body
        return {**reply, "bodies": list(bodies.values()), "partial": False}

    def close(self) -> None:
        """Quit the engine and shut the pipes -- never underneath a call.

        This takes the lock a call holds, so a call already inside the engine
        is let finish first, and anything arriving after is told the world has
        closed. Shutting the pipes without it turned a pick that was in flight
        when the page opened another room into "OSError: [Errno 22] Invalid
        argument" instead of a closed world.

        The wait is bounded by CLOSE_WAIT_S, because Live.open holds its own
        lock across this, and a call that a hung engine never answers would
        otherwise keep every room shut behind it. Past the bound the engine is
        killed, which is what brings that call back: its read comes up empty.
        """
        held = self._lock.acquire(timeout=CLOSE_WAIT_S)
        try:
            already = self._closed
            self._closed = True
            if already or self._process.poll() is not None:
                return
            if not held:
                # A quit would only queue up behind the call that is stuck.
                self._process.kill()
                return
            try:
                assert self._process.stdin is not None
                self._process.stdin.write('{"op":"quit"}\n')
                self._process.stdin.flush()
                self._process.wait(timeout=5)
            except Exception:
                self._process.kill()
        finally:
            self._shut()
            if held:
                self._lock.release()

    def _shut(self) -> None:
        """Close the pipes. They do not close themselves when the child goes.

        A server that opens a world per scene leaks three handles every time,
        which is invisible until a long session runs out of them.
        """
        for pipe in (self._process.stdin, self._process.stdout, self._process.stderr):
            try:
                if pipe is not None:
                    pipe.close()
            except Exception:
                pass


class Live:
    """The one open world, and the operations the panel can ask of it."""

    def __init__(self) -> None:
        self.session: Session | None = None
        self._lock = threading.Lock()

    def open(self, app: Any, body: Any) -> dict[str, Any]:
        if not isinstance(body, dict):
            raise LiveError("A live request must be an object")
        # Pins are part of the ROOM rather than of the engine's scene request:
        # a world is opened from a set of bodies and the pins go in afterwards,
        # against the bodies that are now standing there. They travel in the
        # spec all the same, so that saving a room and opening it again puts its
        # gates back on their hinges -- and they are CHECKED by the validator
        # alongside the bodies, where whoever wrote them can be told.
        spec = fracture_lab.validate(body.get("spec") or {})
        pins = spec.get("joints") or []
        with self._lock:
            if self.session is not None:
                self.session.close()
                self.session = None
            # Two ways to hold a world: a subprocess speaking the line protocol,
            # or the C library loaded here. They answer the same interface and
            # the tests run both against the same scenes, so the choice is about
            # where a crash lands, not about what the physics does.
            if getattr(app, "live_inprocess", False):
                session = live_inprocess.InProcessSession(spec)
            else:
                session = Session(app.engine_path, spec, app.runs_path)
            self.session = session
        hung = self._hang(session, pins)
        # And the edges, on bodies that are now standing there, for the same
        # reason the pins go in afterwards. docs/cutting-model.md.
        armed = self._arm(session, spec.get("blades") or [])
        return {"session": session.id, "spec": spec, **session.state, **hung, **armed}

    @staticmethod
    def _arm(session: "Session", blades: Any) -> dict[str, Any]:
        """Give every body the room says is a blade its edge.

        An edge that will not go on is said out loud, like a pin that will not
        hang: a sword that silently does not cut reads as the physics failing.
        """
        if not isinstance(blades, list):
            raise LiveError("a room's blades must be a list")
        problems: list[str] = []
        state: dict[str, Any] = {}
        for blade in blades:
            if not isinstance(blade, dict):
                problems.append("a blade that is not an object")
                continue
            try:
                answer = session.send(
                    op="blade", body=str(blade.get("body", "")),
                    heel=[float(v) / 1000.0 for v in (blade.get("heel_mm") or [])],
                    tip=[float(v) / 1000.0 for v in (blade.get("tip_mm") or [])],
                    facing=[float(v) for v in (blade.get("facing") or [0, 0, 1])],
                    thickness_m=float(blade.get("thickness_mm", 10.0)) / 1000.0,
                    edge_radius_m=float(blade.get("edge_radius_mm", 0.2)) / 1000.0,
                    bevel_deg=float(blade.get("bevel_deg", 30.0)),
                    grip=[float(v) / 1000.0
                          for v in (blade.get("grip_mm") or blade.get("heel_mm") or [])])
            except Exception as error:
                problems.append(f"{blade.get('body', '?')} would not take its edge: {error}")
                continue
            blade["id"] = answer.get("blade")
            if answer.get("blades") is not None:
                state["blades"] = answer["blades"]
        if problems:
            state["blade_problems"] = problems
        return state

    @staticmethod
    def _hang(session: "Session", pins: Any) -> dict[str, Any]:
        """Put every pin the room asks for into the world that just opened.

        A pin that will not hang is said out loud rather than dropped. Silence
        here would be a gate that simply does not swing, which reads as the
        physics being broken rather than as the room being wrong about where its
        own hinge is -- and telling those two apart from the outside took a day
        the last time something in this engine failed quietly.
        """
        if not isinstance(pins, list):
            raise LiveError("a room's joints must be a list")
        problems: list[str] = []
        state: dict[str, Any] = {}
        for pin in pins:
            if not isinstance(pin, dict):
                problems.append("a joint that is not an object")
                continue
            kind = str(pin.get("kind", "hinge"))
            if kind == "elastic":
                try:
                    answer = session.send(
                        op="spring", a=str(pin.get("a", "")), b=str(pin.get("b", "")),
                        at_a=[float(v) / 1000.0 for v in (pin.get("at_mm") or [])],
                        at_b=[float(v) / 1000.0 for v in (pin.get("to_mm") or [])],
                        rest_m=float(pin.get("rest_mm", 0.0)) / 1000.0,
                        stiffness_n_m=float(pin.get("stiffness_n_m", 1000.0)),
                        damping_n_s_m=float(pin.get("damping_n_s_m", 0.0)))
                except Exception as error:
                    problems.append(f"a spring would not go between "
                                    f"{pin.get('a', '?')} and {pin.get('b', '?')}: "
                                    f"{error}")
                    continue
                pin["id"] = answer.get("joint")
                if answer.get("joints") is not None:
                    state["joints"] = answer["joints"]
                continue
            if kind == "fixing":
                try:
                    answer = session.send(
                        op="fix", a=str(pin.get("a", "")), b=str(pin.get("b", "")),
                        at=[float(v) / 1000.0 for v in (pin.get("at_mm") or [])],
                        axis=[float(v) for v in (pin.get("axis") or [0, 1, 0])],
                        holds_tension_n=float(pin.get("holds_tension_n", 0.0)),
                        holds_shear_n=float(pin.get("holds_shear_n", 0.0)))
                except Exception as error:
                    problems.append(f"{pin.get('b', '?')} would not fix to "
                                    f"{pin.get('a', '?')}: {error}")
                    continue
                pin["id"] = answer.get("joint")
                if answer.get("joints") is not None:
                    state["joints"] = answer["joints"]
                continue
            if kind == "pulley":
                # Four places: where the rope is made off on each body, and the
                # two sheaves it runs over.
                try:
                    answer = session.send(
                        op="reeve", a=str(pin.get("a", "")), b=str(pin.get("b", "")),
                        at_a=[float(v) / 1000.0 for v in (pin.get("at_mm") or [])],
                        at_b=[float(v) / 1000.0 for v in (pin.get("to_mm") or [])],
                        over_a=[float(v) / 1000.0 for v in (pin.get("over_a_mm") or [])],
                        over_b=[float(v) / 1000.0 for v in (pin.get("over_b_mm") or [])],
                        ratio=float(pin.get("ratio", 1.0)),
                        length_m=float(pin.get("length_mm", 0.0)) / 1000.0)
                except Exception as error:
                    problems.append(f"{pin.get('a', '?')} and {pin.get('b', '?')} "
                                    f"would not reeve: {error}")
                    continue
                pin["id"] = answer.get("joint")
                if answer.get("joints") is not None:
                    state["joints"] = answer["joints"]
                continue
            if kind == "link":
                # A tie is the one joint with TWO places -- one on each body --
                # rather than one point the two share.
                far = pin.get("to_mm")
                if not isinstance(far, list) or len(far) != 3:
                    problems.append("a link needs to_mm as three numbers")
                    continue
                try:
                    answer = session.send(
                        op="tie", a=str(pin.get("a", "")), b=str(pin.get("b", "")),
                        at_a=[float(v) / 1000.0 for v in (pin.get("at_mm") or [])],
                        at_b=[float(v) / 1000.0 for v in far],
                        length_m=float(pin.get("length_mm", 0.0)) / 1000.0,
                        breaks_at_n=float(pin.get("breaks_at_n", 0.0)))
                except Exception as error:
                    problems.append(f"{pin.get('b', '?')} would not tie to "
                                    f"{pin.get('a', '?')}: {error}")
                    continue
                pin["id"] = answer.get("joint")
                if answer.get("joints") is not None:
                    state["joints"] = answer["joints"]
                continue
            if kind not in ("hinge", "slider"):     # link and pulley handled above
                problems.append(f"{kind!r} is not a kind of joint this room knows")
                continue
            at = pin.get("at_mm")
            if not isinstance(at, list) or len(at) != 3:
                problems.append(f"a {kind} needs at_mm as three numbers")
                continue
            try:
                common = {"a": str(pin.get("a", "")), "b": str(pin.get("b", "")),
                          "at": [float(v) / 1000.0 for v in at],
                          "axis": [float(v) for v in (pin.get("axis") or [0, 1, 0])]}
                # Millimetres in the room's own spelling, metres on the wire --
                # the room talks in millimetres everywhere else and a travel in
                # metres sitting next to a size in millimetres is how a 2 m lift
                # becomes 2 mm.
                answer = session.send(
                    op="slide", **common,
                    lower_m=float(pin.get("lower_mm", 0.0)) / 1000.0,
                    upper_m=float(pin.get("upper_mm", 0.0)) / 1000.0,
                    friction_n=float(pin.get("friction_n", 0.0))) \
                    if kind == "slider" else session.send(
                    op="hinge", **common,
                    lower_deg=float(pin.get("lower_deg", -180.0)),
                    upper_deg=float(pin.get("upper_deg", 180.0)),
                    friction_n_m=float(pin.get("friction_n_m", 0.0)))
            except Exception as error:      # the engine refused it
                problems.append(f"{pin.get('b', '?')} would not hang on "
                                f"{pin.get('a', '?')}: {error}")
                continue
            pin["id"] = answer.get("joint")
            if answer.get("joints") is not None:
                state["joints"] = answer["joints"]
        if problems:
            state["joint_problems"] = problems
        return state

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
            # A host that draws the room asks for only what moved: it keeps
            # its own copy of the scene and merges. One that does not gets the
            # whole world, as it always did.
            #
            # `hand` carries where whatever is being held should be before the
            # step runs. It is here rather than in its own `move` call because
            # the round trip costs thirty times what the step does, so sending
            # them separately halves the frame rate of anyone carrying anything.
            step: dict[str, Any] = {"op": "step", "dt": dt, "n": count,
                                    "moved": bool(body.get("moved", False))}
            hand = body.get("hand")
            if hand is not None:
                if not isinstance(hand, list) or len(hand) != 3:
                    raise LiveError("a step's hand needs three numbers")
                spot = [float(v) for v in hand]
                if not all(math.isfinite(v) for v in spot):
                    raise LiveError("a step was given a hand that is not a number")
                step["hand"] = spot
            # Which way a wielded body should face. The engine turns it there
            # with the torque the hand has, so this is a wish, not a pose.
            turn = body.get("hand_q")
            if turn is not None:
                if not isinstance(turn, list) or len(turn) != 4:
                    raise LiveError("a step's hand_q needs four numbers, w first")
                q = [float(v) for v in turn]
                if not all(math.isfinite(v) for v in q) or sum(v * v for v in q) < 1e-12:
                    raise LiveError("a step was given a hand_q that is not an orientation")
                step["hand_q"] = q
            return session.send(**step)
        if op == "wield":
            # A grip, with a bounded force and torque -- not a carry. Without a
            # grip given, a body with an edge is held where its blade says.
            command: dict[str, Any] = {"op": "wield", "name": str(body.get("name", ""))}
            if body.get("grip") is not None:
                command["grip"] = _three(body.get("grip"), "wield's grip")
            return session.send(**command)
        if op == "hand":
            command = {"op": "hand"}
            if body.get("strength_n") is not None:
                strength = float(body.get("strength_n"))
                if not 0.0 <= strength <= 1e5:
                    raise LiveError("the hand's strength is newtons, 0 to 100,000")
                command["strength_n"] = strength
            if body.get("torque_n_m") is not None:
                torque = float(body.get("torque_n_m"))
                if not 0.0 <= torque <= 1e4:
                    raise LiveError("the hand's torque is newton metres, 0 to 10,000")
                command["torque_n_m"] = torque
            return session.send(**command)
        if op == "blade":
            thickness = float(body.get("thickness_m", 0.01))
            radius = float(body.get("edge_radius_m", 0.0002))
            bevel = float(body.get("bevel_deg", 30.0))
            if not 0.0005 <= thickness <= 0.5:
                raise LiveError("a blade's thickness is 0.5 mm to half a metre")
            if not 1e-6 <= radius <= 0.01:
                raise LiveError("an edge radius is a micrometre to 10 mm")
            if not 1.0 <= bevel <= 179.0:
                raise LiveError("a bevel is an angle between 1 and 179 degrees")
            heel = _three(body.get("heel"), "a blade's heel")
            return session.send(op="blade", body=str(body.get("body", "")), heel=heel,
                                tip=_three(body.get("tip"), "a blade's tip"),
                                facing=_three(body.get("facing"), "a blade's facing"),
                                thickness_m=thickness, edge_radius_m=radius,
                                bevel_deg=bevel,
                                grip=_three(body.get("grip") or heel, "a blade's grip"))
        if op == "grab":
            return session.send(op="grab", name=str(body.get("name", "")))
        if op == "move":
            to = body.get("to")
            if not isinstance(to, list) or len(to) != 3:
                raise LiveError("move needs a position of three numbers")
            return session.send(op="move", to=[float(v) for v in to])
        if op == "collect":
            at = body.get("at")
            if not isinstance(at, list) or len(at) != 3:
                raise LiveError("collect needs a point of three numbers")
            spot = [float(v) for v in at]
            if not all(math.isfinite(v) for v in spot):
                raise LiveError("collect was given a point that is not a number")
            radius = float(body.get("radius_m", 1.0))
            if not 0.0 < radius <= 10.0:
                raise LiveError("collect needs a radius between 0 and 10 metres")
            return session.send(op="collect", at=spot, radius_m=radius,
                                largest_cells=int(body.get("largest_cells", 64)))
        if op == "foresee":
            horizon = float(body.get("horizon_s", 2.5))
            if not 0.0 <= horizon <= 10.0:
                raise LiveError("foresee needs a horizon between 0 and 10 seconds")
            return session.send(op="foresee", horizon_s=horizon)
        if op in ("release", "poses", "joints", "overloaded", "blades", "cuts"):
            return session.send(op=op)
        if op == "heat":
            # Kindling, a torch, a stove: external work into a body or a gas
            # region, from now. Whether it lights anything is the engine's
            # answer. Bounded here so a slip of the mouse is not a megawatt.
            target = str(body.get("target", ""))
            if not target:
                raise LiveError("heat needs a target: a body or a gas region")
            power = float(body.get("power_w", 0.0))
            seconds = float(body.get("seconds", 0.0))
            if not (math.isfinite(power) and 0.0 <= power <= 100000.0):
                raise LiveError("a heater's power is between 0 and 100 kW")
            if not (math.isfinite(seconds) and 0.0 < seconds <= 3600.0):
                raise LiveError("a heater runs for between 0 and 3600 seconds")
            return session.send(op="heat", target=target, power_w=power, seconds=seconds)
        if op == "thermo":
            # Everything about heat, chemistry and gas, and the ledger. Moves
            # nothing, so it answers on its own and carries no bodies.
            return session.send(op="thermo", model=bool(body.get("model", False)))
        # ---- the ground and the water ----------------------------------------
        def xz(key: str, fallback: Any = None) -> list[float]:
            value = body.get(key, fallback)
            if not isinstance(value, list) or len(value) not in (2, 3):
                raise LiveError(f"{key} needs [x, z] (or [x, y, z]) in metres")
            out = [float(v) for v in value]
            if not all(math.isfinite(v) for v in out):
                raise LiveError(f"{key} is not a number")
            return [out[0], out[-1]]
        if op == "dig":
            # A spade: the engine takes the ground down, rebuilds the colliders
            # it changed and wakes what they held. Bounded so a slip of the
            # mouse is not a quarry.
            width = float(body.get("width_m", 0.8))
            depth = float(body.get("depth_m", 0.4))
            if not (0.1 <= width <= 10.0 and 0.02 <= depth <= 5.0):
                raise LiveError("a dig is 0.1 to 10 m wide and 0.02 to 5 m deep")
            start = xz("from")
            return session.send(**{"op": "dig", "from": start, "to": xz("to", start),
                                   "width_m": width, "depth_m": depth})
        if op == "deposit":
            radius = float(body.get("radius_m", 1.0))
            sand = float(body.get("sand_m3", 0.0))
            soil = float(body.get("soil_m3", 0.0))
            if not (0.1 <= radius <= 10.0 and 0.0 <= sand <= 100.0 and 0.0 <= soil <= 100.0
                    and sand + soil > 0.0):
                raise LiveError("a heap is 0.1 to 10 m across and holds some sand or soil")
            return session.send(op="deposit", at=xz("at"), radius_m=radius, sand_m3=sand,
                                soil_m3=soil)
        if op == "survey":
            return session.send(op="survey", at=xz("at"))
        if op in ("environment", "environment_state", "terrain"):
            return session.send(op=op, full=bool(body.get("full", False)))
        if op == "discharge":
            discharge = float(body.get("discharge_m3_s", 0.0))
            if not 0.0 <= discharge <= 20.0:
                raise LiveError("a river's discharge is 0 to 20 cubic metres a second")
            return session.send(op="discharge", river=str(body.get("river", "")),
                                discharge_m3_s=discharge)
        if op == "vent":
            return session.send(op="vent", region=str(body.get("region", "")),
                                open=bool(body.get("open", True)))
        if op == "hinge":
            # Hang one named thing off another on a pin. Everything is checked
            # here rather than trusted: the engine refuses what it cannot hang,
            # but a NaN axis reaches it as a direction and comes back as a
            # constraint nobody can see.
            def spot(key: str) -> list[float]:
                value = body.get(key)
                if not isinstance(value, list) or len(value) != 3:
                    raise LiveError(f"a hinge needs {key} as three numbers")
                out = [float(v) for v in value]
                if not all(math.isfinite(v) for v in out):
                    raise LiveError(f"a hinge was given {key} that is not a number")
                return out
            axis = spot("axis")
            if not any(abs(v) > 1e-9 for v in axis):
                raise LiveError("a hinge needs an axis with a direction")
            lower = float(body.get("lower_deg", -180.0))
            upper = float(body.get("upper_deg", 180.0))
            if not -180.0 <= lower <= 0.0 <= upper <= 180.0:
                raise LiveError(
                    "hinge limits are degrees either side of where it is hung: "
                    "a lower from -180 to 0 and an upper from 0 to 180")
            friction = float(body.get("friction_n_m", 0.0))
            if not 0.0 <= friction <= 1e6:
                raise LiveError("hinge friction is newton metres, zero or more")
            return session.send(op="hinge", a=str(body.get("a", "")),
                                b=str(body.get("b", "")), at=spot("at"), axis=axis,
                                lower_deg=lower, upper_deg=upper,
                                friction_n_m=friction)
        if op == "slide":
            def spot(key: str, fallback: Any = None) -> list[float]:
                value = body.get(key, fallback)
                if not isinstance(value, list) or len(value) != 3:
                    raise LiveError(f"a slide needs {key} as three numbers")
                out = [float(v) for v in value]
                if not all(math.isfinite(v) for v in out):
                    raise LiveError(f"a slide was given {key} that is not a number")
                return out
            axis = spot("axis", [0.0, 1.0, 0.0])
            if not any(abs(v) > 1e-9 for v in axis):
                raise LiveError("a slide needs an axis with a direction")
            lower = float(body.get("lower_m", -1.0))
            upper = float(body.get("upper_m", 1.0))
            if not lower <= 0.0 <= upper:
                raise LiveError("slide travel is metres either side of where it is "
                                "built: a lower of zero or less and an upper of "
                                "zero or more")
            if upper - lower > 100.0:
                raise LiveError("a slide of more than 100 metres is not a mechanism")
            friction = float(body.get("friction_n", 0.0))
            if not 0.0 <= friction <= 1e9:
                raise LiveError("slide friction is newtons, zero or more")
            return session.send(op="slide", a=str(body.get("a", "")),
                                b=str(body.get("b", "")), at=spot("at"), axis=axis,
                                lower_m=lower, upper_m=upper, friction_n=friction)
        if op == "tie":
            def spot(key: str) -> list[float]:
                value = body.get(key)
                if not isinstance(value, list) or len(value) != 3:
                    raise LiveError(f"a tie needs {key} as three numbers")
                out = [float(v) for v in value]
                if not all(math.isfinite(v) for v in out):
                    raise LiveError(f"a tie was given {key} that is not a number")
                return out
            length = float(body.get("length_m", 0.0))
            if not 0.0 <= length <= 100.0:
                raise LiveError("a tie's length is zero (as they stand) to 100 metres")
            breaks = float(body.get("breaks_at_n", 0.0))
            if not 0.0 <= breaks <= 1e9:
                raise LiveError("breaking tension is newtons, zero (never parts) or more")
            return session.send(op="tie", a=str(body.get("a", "")),
                                b=str(body.get("b", "")), at_a=spot("at_a"),
                                at_b=spot("at_b"), length_m=length,
                                breaks_at_n=breaks)
        if op == "reeve":
            def spot(key: str) -> list[float]:
                value = body.get(key)
                if not isinstance(value, list) or len(value) != 3:
                    raise LiveError(f"a pulley needs {key} as three numbers")
                out = [float(v) for v in value]
                if not all(math.isfinite(v) for v in out):
                    raise LiveError(f"a pulley was given {key} that is not a number")
                return out
            ratio = float(body.get("ratio", 1.0))
            if not 0.0 < ratio <= 100.0:
                raise LiveError("a pulley's ratio is more than zero, up to 100")
            length = float(body.get("length_m", 0.0))
            if not 0.0 <= length <= 500.0:
                raise LiveError("a pulley's length is zero (as rove) to 500 metres")
            return session.send(op="reeve", a=str(body.get("a", "")),
                                b=str(body.get("b", "")), at_a=spot("at_a"),
                                at_b=spot("at_b"), over_a=spot("over_a"),
                                over_b=spot("over_b"), ratio=ratio,
                                length_m=length)
        if op == "spring":
            def spot(key: str) -> list[float]:
                value = body.get(key)
                if not isinstance(value, list) or len(value) != 3:
                    raise LiveError(f"a spring needs {key} as three numbers")
                out = [float(v) for v in value]
                if not all(math.isfinite(v) for v in out):
                    raise LiveError(f"a spring was given {key} that is not a number")
                return out
            stiffness = float(body.get("stiffness_n_m", 1000.0))
            if not 0.0 < stiffness <= 1e9:
                raise LiveError("a spring's stiffness is newtons per metre, above zero")
            damping = float(body.get("damping_n_s_m", 0.0))
            if not 0.0 <= damping <= 1e9:
                raise LiveError("spring damping is newton seconds per metre, zero or more")
            rest = float(body.get("rest_m", 0.0))
            if not 0.0 <= rest <= 100.0:
                raise LiveError("a spring's rest length is zero (as it stands) to 100 m")
            return session.send(op="spring", a=str(body.get("a", "")),
                                b=str(body.get("b", "")), at_a=spot("at_a"),
                                at_b=spot("at_b"), rest_m=rest,
                                stiffness_n_m=stiffness, damping_n_s_m=damping)
        if op == "fix":
            def spot(key: str, fallback: Any = None) -> list[float]:
                value = body.get(key, fallback)
                if not isinstance(value, list) or len(value) != 3:
                    raise LiveError(f"a fixing needs {key} as three numbers")
                out = [float(v) for v in value]
                if not all(math.isfinite(v) for v in out):
                    raise LiveError(f"a fixing was given {key} that is not a number")
                return out
            axis = spot("axis", [0.0, 1.0, 0.0])
            if not any(abs(v) > 1e-9 for v in axis):
                raise LiveError("a fixing needs an axis with a direction")
            holds = [float(body.get("holds_tension_n", 0.0)),
                     float(body.get("holds_shear_n", 0.0))]
            if not all(0.0 <= v <= 1e9 for v in holds):
                raise LiveError("a fixing's strengths are newtons, zero (never "
                                "lets go) or more")
            return session.send(op="fix", a=str(body.get("a", "")),
                                b=str(body.get("b", "")), at=spot("at"), axis=axis,
                                holds_tension_n=holds[0], holds_shear_n=holds[1])
        if op == "unhinge":
            return session.send(op="unhinge", joint=int(body.get("joint", 0)))
        if op == "joint_friction":
            # Newton metres for a pin, newtons for a slide. The joint knows
            # which it is, so either spelling arrives here and goes through.
            friction = float(body.get("friction_n", body.get("friction_n_m", 0.0)))
            if not 0.0 <= friction <= 1e9:
                raise LiveError("joint friction is zero or more: newton metres for "
                                "a pin, newtons for a slide")
            return session.send(op="joint_friction",
                                joint=int(body.get("joint", 0)),
                                friction_n=friction)
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
            # `wait` false starts the run on a worker and comes straight back.
            # The world keeps stepping and a later step carries the answer.
            return session.send(op="fracture", name=str(body.get("name", "")),
                                window_s=float(body.get("window_s", 0.003)),
                                wait=bool(body.get("wait", True)))
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
