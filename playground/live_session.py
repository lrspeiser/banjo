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

import hashlib
import json
import logging
import math
import os
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


def _made_of(pin: Any) -> dict[str, Any]:
    """What a fixing, a tie or a spring is MADE of, when it says: one of its two
    ends, whose material and temperature then decide what it can take
    (docs/thermal-mechanics.md). Checked here, where whoever asked can be told."""
    member = str((pin or {}).get("member") or "")
    if not member:
        return {}
    if member not in (str(pin.get("a", "")), str(pin.get("b", ""))):
        raise LiveError(f"a joint is made of one of the two things it holds, and {member!r} "
                        f"is neither")
    return {"member": member}


def spec_digest(spec: Any) -> str:
    """The room's own word for the spec a world was opened from, which a saved
    world carries (LiveWorld::snapshot's `spec_digest`), so that it is only ever
    opened into the room it was saved from.

    A digest of the spec less what changes without changing what the world is
    made of: the ground's edits, which the world keeps in its ground and the
    room writes into its spec as they are made (server.remember_ground), and
    the water carried into a world opened again (server.with_water). What the
    chat builds changes it, so a world saved before the chat changed the room
    is not opened into the room it made."""
    if not isinstance(spec, dict):
        return ""
    plain = dict(spec)
    terrain = plain.get("terrain")
    if isinstance(terrain, dict) and "edits" in terrain:
        plain["terrain"] = {k: v for k, v in terrain.items() if k != "edits"}
    water = plain.get("water")
    if isinstance(water, dict) and "state" in water:
        plain["water"] = {k: v for k, v in water.items() if k != "state"}
    # A block left holding nothing says nothing: server.with_water gives a room
    # that declares no water a block holding only the water it carries, and a
    # room that had none must say the same as it did.
    for key in ("terrain", "water"):
        if isinstance(plain.get(key), dict) and not plain[key]:
            del plain[key]
    text = json.dumps(plain, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _plain(entry: Any) -> Any:
    """A declaration as the room writes it, less the id a world gave it."""
    return {k: v for k, v in entry.items() if k != "id"} if isinstance(entry, dict) else entry


def _made(motor: dict[str, Any]) -> dict[str, Any]:
    """A motor as it is made -- its pin, its store, its torque and speed and
    brake -- without what the room last told it (command and brake), which a
    world carried into a changed room keeps as it was told, unless the room
    tells it something else now."""
    return {k: v for k, v in motor.items() if k not in ("id", "command", "brake")}


def _told(motor: dict[str, Any]) -> tuple[Any, Any]:
    return motor.get("command"), motor.get("brake")


def _declared(spec: dict[str, Any], machines: Any = None,
              made: dict[str, Any] | None = None) -> dict[str, Any]:
    """What a world was given of the room's declarations, each as the room
    wrote it with the id the world has for it: its pins, edges and points (the
    ids _hang, _arm, _point and _adopt give them), and its stores and motors --
    by name, and by the two things a motor's pin joins -- from what the world
    says it has (`machines`) or what _power made (`made`). When the room is
    opened again from a spec the chat or an action has changed, what it still
    declares the same way is carried by these ids (carry_plan)."""
    def ided(key: str) -> list[tuple[Any, Any]]:
        return [(_plain(entry), entry["id"]) for entry in spec.get(key) or []
                if isinstance(entry, dict) and isinstance(entry.get("id"), int)]
    stores = dict((made or {}).get("stores") or {})
    motors = dict((made or {}).get("motors") or {})
    if isinstance(machines, dict):
        for store in machines.get("stores") or []:
            if isinstance(store.get("id"), int):
                stores.setdefault(str(store.get("name", "")), store["id"])
        for motor in machines.get("motors") or []:
            on = motor.get("on") or []
            if isinstance(motor.get("id"), int) and len(on) == 2:
                motors.setdefault((str(on[0]), str(on[1])), motor["id"])
    declared = spec.get("machines") or {}
    return {"joints": ided("joints"), "blades": ided("blades"), "tool_points": ided("tool_points"),
            "stores": [(_plain(s), stores[s["name"]]) for s in declared.get("stores") or []
                       if isinstance(s, dict) and stores.get(s.get("name")) is not None],
            "motors": [(_made(m), _told(m), motors[tuple(m["on"])]) for m in declared.get("motors") or []
                       if isinstance(m, dict) and motors.get(tuple(m.get("on") or ())) is not None]}


def carry_plan(was: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    """Which of what a running world was given (Session.declared) a changed
    spec still declares exactly the same way -- a pin at the same place between
    the same two things, a battery of the same make in the same thing -- by the
    ids the world has for them, for carrying the world into the room as it now
    is (the runner's --carry, LiveWorld::open with a LiveCarry). The rest of
    what the spec declares is new or changed and goes in afresh; and the things
    a new or changed pin, edge or point is on are named (`declared_anew`),
    because it is written against where they were made, so they come back as
    the room has them. A kept motor the room now tells something else is told
    so once it is back (`told`).

    Returns {"engine": what the runner is given, "pairs": for each list the
    spec's entry index -> the id it keeps, "told": motor index -> (command,
    brake)}."""
    engine: dict[str, Any] = {"joints": [], "energy_stores": [], "motors": [], "blades": [],
                              "tool_points": [], "declared_anew": []}
    pairs: dict[str, dict[int, Any]] = {"joints": {}, "stores": {}, "motors": {}, "blades": {},
                                        "tool_points": {}}
    told: dict[int, tuple[Any, Any]] = {}
    anew: set[str] = set()

    def keep(pool: list, want: Any) -> Any:
        for k, (have, ident) in enumerate(pool):
            if have == want:
                del pool[k]
                return ident
        return None

    pool = list(was.get("joints") or [])
    for i, pin in enumerate(spec.get("joints") or []):
        ident = keep(pool, _plain(pin)) if isinstance(pin, dict) else None
        if ident is None:
            if isinstance(pin, dict):
                anew.update(str(pin.get(end) or "") for end in ("a", "b"))
            continue
        pairs["joints"][i] = ident
        engine["joints"].append(ident)
    for key in ("blades", "tool_points"):
        pool = list(was.get(key) or [])
        for i, entry in enumerate(spec.get(key) or []):
            ident = keep(pool, _plain(entry)) if isinstance(entry, dict) else None
            if ident is None:
                if isinstance(entry, dict):
                    anew.add(str(entry.get("body") or ""))
                continue
            pairs[key][i] = ident
            engine[key].append(ident)
    machines = spec.get("machines") or {}
    pool = list(was.get("stores") or [])
    for i, store in enumerate(machines.get("stores") or []):
        ident = keep(pool, _plain(store)) if isinstance(store, dict) else None
        if ident is not None:
            pairs["stores"][i] = ident
            engine["energy_stores"].append(ident)
    motors = list(was.get("motors") or [])
    for i, motor in enumerate(machines.get("motors") or []):
        if not isinstance(motor, dict):
            continue
        for k, (made, told_then, ident) in enumerate(motors):
            if made == _made(motor):
                del motors[k]
                pairs["motors"][i] = ident
                engine["motors"].append(ident)
                if _told(motor) != tuple(told_then):
                    told[i] = _told(motor)
                break
    engine["declared_anew"] = sorted(name for name in anew if name)
    return {"engine": engine, "pairs": pairs, "told": told}


def remember_told(session: Any, motor: Any, command: float, brake: bool) -> None:
    """What a running world's motor has just been told by the room's chat
    (drive, which works the room as it stands and writes what it said into the
    spec too), kept as what the world was told (Session.declared), so a later
    carry does not tell it that again (carry_plan's `told`). Set winding by the
    chat and then stopped with E, a hoist in a room the chat changed next would
    otherwise have started winding again."""
    declared = getattr(session, "declared", None)
    if isinstance(declared, dict):
        declared["motors"] = [(made, (command, brake) if ident == motor else told, ident)
                              for made, told, ident in declared.get("motors") or []]


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

    def __init__(self, engine_path: Path, spec: dict[str, Any], runs_path: Path,
                 snapshot: dict[str, Any] | None = None,
                 carry: dict[str, Any] | None = None) -> None:
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
        command = [str(exe), "--scene", str(scene), "--cell", f"{spec['cell_m']:.6g}"]
        # A saved world to open the scene into (LiveWorld::snapshot), beside
        # the scene it was saved from. The opening reply says what came back
        # (`restored`): the whole world, whole things where they were left, or
        # the scene as it is.
        if snapshot is not None:
            saved = directory / "snapshot.json"
            saved.write_text(json.dumps(snapshot), encoding="utf-8")
            command += ["--snapshot", str(saved)]
            # Carried into a room that has changed since it was saved (Live.open
            # with a carry): what the room still declares the same way, by the
            # saved world's ids (carry_plan). The opening reply says, thing by
            # thing, what came back as it was and what is as the room has it.
            if carry is not None:
                asked = directory / "carry.json"
                asked.write_text(json.dumps(carry), encoding="utf-8")
                command += ["--carry", str(asked)]
        # A process group of its own (a session, on POSIX). Sharing the
        # server's, a Ctrl+C or Ctrl+Break meant for the server ended the world
        # with it, before the server could save the world on its way out
        # (server.keep_world). A server that dies still ends it: its pipe
        # closes and it stops reading.
        apart = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
                 else {"start_new_session": True})
        self._process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", bufsize=1, cwd=str(directory), **apart)
        self.opened_at = time.time()
        # Who hears every reply after it is read: the server's keeper of what
        # the person's own hand did (server.hear). None hears nothing.
        self.on_reply: Any = None
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
            # A lattice run says the step it was taken at and how many it took.
            ran = (f", {wait['steps']} steps of {wait.get('step_us', 0.0):.2f} us"
                   if wait.get("steps") else "")
            if kind == "foreseen":
                _log.info("banjo: %s coming in %.0f ms (t=%.2f s)",
                          wait.get("object"), wait.get("lead_ms", 0.0), wait.get("at_s", 0.0))
            elif kind == "precomputed":
                # The run, and separately how long it sat waiting for a worker.
                # Rolling the two together made the log report a 30 ms fracture
                # as a 4 second one.
                queued = wait.get("lead_ms", 0.0)
                _log.info("banjo: %s %s, %.0f ms of run%s%s (t=%.2f s)",
                          kind, wait.get("object"), wait.get("cost_ms", 0.0), ran,
                          f", {queued:.0f} ms queued" if queued >= 1.0 else "",
                          wait.get("at_s", 0.0))
            else:
                _log.info("banjo: %s %s, %.0f ms%s (t=%.2f s)",
                          kind, wait.get("object"), wait.get("cost_ms", 0.0), ran,
                          wait.get("at_s", 0.0))
        # Every reply, not only the page's steps: the engine hands a closed
        # ground-work record over in exactly one reply and then forgets it, and
        # the calls an action or an opening makes carry them too. A listener
        # that fails is logged and never stops the room.
        listener = self.on_reply
        if listener is not None:
            try:
                listener(self, state)
            except Exception:
                _log.exception("banjo: a reply's listener failed")
        return state

    def _whole(self, reply: dict[str, Any]) -> dict[str, Any]:
        """The world as it now stands, whichever way the reply arrived.

        A reply marked `partial` carries only the bodies that moved, because
        sending two hundred motionless ones thirty times a second was most of
        the cost of running the room. Everything on this side -- the tools, the
        tests, anything asking what the world looks like -- still wants all of
        them, so the last full picture is kept here and the changes folded in.
        What each elastic holds comes the same way: only the ones that changed.
        """
        if not reply.get("partial"):
            return reply
        bodies = {body["name"]: body for body in (self.state or {}).get("bodies", ())}
        for name in reply.get("gone") or ():
            bodies.pop(name, None)
        for body in reply.get("bodies", ()):
            bodies[body["name"]] = body
        whole = {**reply, "bodies": list(bodies.values()), "partial": False}
        springs = {e["id"]: e for e in (self.state or {}).get("elastics", ())}
        for reading in reply.get("elastics") or ():
            springs[reading["id"]] = reading
        if springs:
            whole["elastics"] = list(springs.values())
        return whole

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
        # A saved world to open the room into (Live.snapshot): the room as it
        # stood when it was saved, rather than as its spec authors it.
        snapshot = body.get("snapshot") if isinstance(body.get("snapshot"), dict) else None
        with self._lock:
            # With `carry`, the world that is running, saved a moment ago, is
            # carried into the room as the chat or an action has just changed it:
            # everything the change did not touch comes back as it stood. What
            # the running world was given of the room's pins, machines, edges
            # and points (Session.declared) says which of them the changed spec
            # still declares the same way (carry_plan). With no such record --
            # nothing of the room's is running -- what changed cannot be told
            # from what did not, and the room opens from its spec.
            plan = None
            if snapshot is not None and body.get("carry"):
                was = getattr(self.session, "declared", None) if self.session is not None else None
                if isinstance(was, dict):
                    plan = carry_plan(was, spec)
                else:
                    snapshot = None
            if self.session is not None:
                self.session.close()
                self.session = None
            # Two ways to hold a world: a subprocess speaking the line protocol,
            # or the C library loaded here. They answer the same interface and
            # the tests run both against the same scenes, so the choice is about
            # where a crash lands, not about what the physics does.
            if getattr(app, "live_inprocess", False):
                # The C library opens a saved world whole or not at all, and
                # cannot carry one into a changed room yet: there a room the
                # chat changed opens from its spec, as it always did.
                if plan is not None:
                    _log.info("the in-process lane cannot carry the running world into the changed room; "
                              "it opens from its spec")
                    snapshot, plan = None, None
                session = live_inprocess.InProcessSession(spec, snapshot=snapshot)
            else:
                session = Session(app.engine_path, spec, app.runs_path, snapshot=snapshot,
                                  carry=plan["engine"] if plan is not None else None)
            self.session = session
            # What the room calls the spec this world was opened from, which a
            # snapshot of it carries (spec_digest).
            session.spec_digest = spec_digest(body.get("spec"))
            # What the person's own hand does to the ground goes to their
            # notebook (server.hear), read against the room document this world
            # was opened from -- bodies as the room spells them, its tool points
            # and interactions. The in-process lane hands no ground work over on
            # its steps, so there it hears nothing.
            session.room_spec = spec
            session.on_reply = getattr(app, "on_live_reply", None)
        # What the world said as it opened. Only the opening carries the whole
        # of the ground and the water; every call that puts a pin, an edge or a
        # point in replaces the session's picture with its own reply, which
        # carries neither. Returned from here without them, a room on ground
        # with a pick in it opened with no ground drawn at all.
        opening = dict(session.state)
        restored = opening.get("restored")
        tier = restored.get("tier") if isinstance(restored, dict) else None
        if tier == "whole":
            # The world came back as it was saved, with its pins, edges and
            # points where they were -- a gate swung open, a pick carried across
            # the room. Declared again from the spec, each would go in where the
            # spec first put it in the world, which is no longer where its wood
            # is. The spec's own entries take the ids the world has for them.
            adopted = self._adopt(spec, opening)
            session.declared = _declared(spec, opening.get("machines"))
            return {"session": session.id, "spec": spec, **opening, **adopted}
        if tier == "carried" and plan is not None:
            return self._carried(session, spec, opening, plan)
        made: dict[str, Any] = {}
        hung = self._hang(session, pins)
        # And its batteries and the motors on its pins, which name the pins.
        hung.update(self._power(session, spec.get("machines") or {}, pins, made=made))
        # And the edges, on bodies that are now standing there, for the same
        # reason the pins go in afterwards. docs/cutting-model.md.
        armed = self._arm(session, spec.get("blades") or [])
        # And the points of tools that dig, likewise. docs/ground-work.md.
        tooled = self._point(session, spec.get("tool_points") or [])
        session.declared = _declared(spec, None, made)
        return {"session": session.id, "spec": spec, **opening, **session.state, **hung, **armed,
                **tooled}

    def _carried(self, session: Any, spec: dict[str, Any], opening: dict[str, Any],
                 plan: dict[str, Any]) -> dict[str, Any]:
        """The room opened carrying the world that was running (Live.open with
        a carry). What the world kept of what it had been given takes the id it
        has for it, as a world opened whole adopts its own (_adopt); everything
        else the spec declares -- new, changed, or on a thing the world could
        not carry -- goes in as it does into a room just opened (_hang, _power,
        _arm, _point). A kept motor the room now tells something else (the chat
        set it going) is told so.

        The opening's bodies are kept as they are: they carry the cells of every
        piece, which a later reply sends no more."""
        pairs = plan["pairs"]
        pins = spec.get("joints") or []
        have = {j.get("id") for j in opening.get("joints") or []}
        new_pins = []
        for i, pin in enumerate(pins):
            if isinstance(pin, dict) and pairs["joints"].get(i) in have:
                pin["id"] = pairs["joints"][i]
            else:
                new_pins.append(pin)
        hung = self._hang(session, new_pins)
        machines = spec.get("machines") or {}
        machines_now = opening.get("machines") or {}
        stores_now = {s.get("id") for s in machines_now.get("stores") or []}
        motors_now = {m.get("id") for m in machines_now.get("motors") or []}
        made: dict[str, Any] = {"stores": {}, "motors": {}}
        new_stores, new_motors, told = [], [], False
        for i, store in enumerate(machines.get("stores") or []):
            if pairs["stores"].get(i) in stores_now:
                made["stores"][str(store.get("name", ""))] = pairs["stores"][i]
            else:
                new_stores.append(store)
        for i, motor in enumerate(machines.get("motors") or []):
            ident = pairs["motors"].get(i)
            if ident not in motors_now:
                new_motors.append(motor)
                continue
            made["motors"][tuple(str(v) for v in motor.get("on") or [])] = ident
            if i in plan["told"]:
                command, brake = plan["told"][i]
                try:
                    session.send(op="drive", motor=ident, command=float(command), brake=bool(brake))
                    told = True
                except LiveError as error:
                    hung.setdefault("machine_problems", []).append(
                        f"the motor on {' and '.join(motor.get('on') or [])} would not take what it was "
                        f"told: {error}")
        if new_stores or new_motors:
            powered = self._power(session, {"stores": new_stores, "motors": new_motors}, pins, made=made)
            if powered.get("machine_problems"):
                hung.setdefault("machine_problems", []).extend(powered["machine_problems"])
        blades = [b for b in spec.get("blades") or []]
        have_blades = {b.get("id") for b in opening.get("blades") or []}
        new_blades = []
        for i, blade in enumerate(blades):
            if isinstance(blade, dict) and pairs["blades"].get(i) in have_blades:
                blade["id"] = pairs["blades"][i]
            else:
                new_blades.append(blade)
        armed = self._arm(session, new_blades)
        have_points = {p.get("id") for p in opening.get("tool_points") or []}
        new_points = []
        for i, point in enumerate(spec.get("tool_points") or []):
            if isinstance(point, dict) and pairs["tool_points"].get(i) in have_points:
                point["id"] = pairs["tool_points"][i]
            else:
                new_points.append(point)
        tooled = self._point(session, new_points)
        session.declared = _declared(spec, None, made)
        out = {"session": session.id, "spec": spec, **opening, **hung, **armed, **tooled}
        # Machines as they are now, when something was declared or told since
        # the opening said them.
        if (new_stores or new_motors or told) and isinstance(session.state.get("machines"), dict):
            out["machines"] = session.state["machines"]
        return out

    def rejoin(self, app: Any) -> dict[str, Any] | None:
        """The world that is running, for a page opening its room again.

        A reload is not a new room. Opening again from the room's spec put
        everything back as it was authored -- what the person had moved, what
        had broken, what their hand held -- because opening was the only way a
        page had to get the room to draw. The running world says the whole of
        itself instead: a poses reply carries every body with its cells, the
        pins, the edges, the tool points, the hand and the ground whole.

        The world takes a new id on the way. A page still holding the old one is
        told its room was opened again, as it was when opening replaced the room,
        rather than stepping this world as well as the page that rejoined it.

        None when there is nothing to rejoin, or when the lane cannot say the
        whole of its world -- the in-process one sends neither a piece's cells
        nor the ground -- and the caller opens the room as before."""
        with self._lock:
            session = self.session
            if session is None or isinstance(session, live_inprocess.InProcessSession):
                return None
            try:
                whole = session.send(op="poses")
            except LiveError:
                return None
            session.id = uuid.uuid4().hex
            return {"session": session.id, "spec": session.room_spec, **whole, "rejoined": True}

    def snapshot(self) -> tuple[dict[str, Any] | None, str]:
        """The whole of the running world, for opening the room again after the
        server has gone (LiveWorld::snapshot), carrying the room's word for the
        spec it was opened from. None, and why, while something is under way
        that a saved world cannot carry -- a break being worked out, a stroke of
        the hand, an edge in a cut, a point in the ground -- or with no world
        open: the caller keeps the last one it had, and asks again later."""
        session = self.session
        if session is None:
            return None, "no world is open"
        try:
            reply = session.send(op="snapshot", spec_digest=getattr(session, "spec_digest", ""))
        except LiveError as error:
            return None, str(error)
        saved = reply.get("snapshot")
        if not isinstance(saved, dict):
            return None, str(reply.get("refused") or "the world gave no snapshot")
        return saved, ""

    @staticmethod
    def _adopt(spec: dict[str, Any], opening: dict[str, Any]) -> dict[str, Any]:
        """The spec's pins, edges and points given the ids a world opened again
        from a saved one has for them, as declaring them would have (_hang,
        _arm, _point): the first of the world's with the same kind and the same
        two names for each pin, and the same body for an edge or a point. One
        whose thing broke, so the world has it under a piece's name, keeps
        none."""
        taken: set[Any] = set()
        for pin in spec.get("joints") or []:
            if not isinstance(pin, dict):
                continue
            for joint in opening.get("joints") or []:
                if (joint.get("id") not in taken and joint.get("kind") == str(pin.get("kind", "hinge"))
                        and joint.get("a") == pin.get("a") and joint.get("b") == pin.get("b")):
                    pin["id"] = joint.get("id")
                    taken.add(joint.get("id"))
                    break
        for key, listed in (("blades", "blades"), ("tool_points", "tool_points")):
            used: set[Any] = set()
            for entry in spec.get(key) or []:
                if not isinstance(entry, dict):
                    continue
                for have in opening.get(listed) or []:
                    if have.get("id") not in used and have.get("body") == entry.get("body"):
                        entry["id"] = have.get("id")
                        used.add(have.get("id"))
                        break
        return {}

    @staticmethod
    def _point(session: "Session", points: Any) -> dict[str, Any]:
        """Give every body the room says is a tool that digs its point.

        A point that will not go on is said out loud, like an edge: a pick that
        silently digs nothing reads as the physics failing.
        """
        if not isinstance(points, list):
            raise LiveError("a room's tool points must be a list")
        problems: list[str] = []
        state: dict[str, Any] = {}
        for point in points:
            if not isinstance(point, dict):
                problems.append("a tool point that is not an object")
                continue
            try:
                answer = session.send(
                    op="tool_point", body=str(point.get("body", "")),
                    tip=[float(v) / 1000.0 for v in (point.get("tip_mm") or [])],
                    pointing=[float(v) for v in (point.get("pointing") or [0, -1, 0])],
                    width_m=float(point.get("width_mm", 40.0)) / 1000.0,
                    thickness_m=float(point.get("thickness_mm", 40.0)) / 1000.0,
                    angle_deg=float(point.get("angle_deg", 30.0)),
                    length_m=float(point.get("length_mm", 150.0)) / 1000.0,
                    grip=[float(v) / 1000.0
                          for v in (point.get("grip_mm") or point.get("tip_mm") or [])])
            except Exception as error:
                problems.append(f"{point.get('body', '?')} would not take its point: {error}")
                continue
            point["id"] = answer.get("tool_point")
            if answer.get("tool_points") is not None:
                state["tool_points"] = answer["tool_points"]
        if problems:
            state["tool_point_problems"] = problems
        return state

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
    def _power(session: "Session", machines: Any, pins: Any,
               made: dict[str, Any] | None = None) -> dict[str, Any]:
        """The room's stores of energy and the motors on its pins
        (docs/machine-world.md), once the pins are in.

        A motor names its pin by the two things it joins -- the world numbers
        pins as they go in -- and its unloaded speed in turns a minute, as a
        maker gives it. One with a brake starts with it on, so a crate hanging
        on a hoist does not fall the moment the room opens. What will not go in
        is said, as a pin that will not hang is.

        `made`, when given, has the id of each store the world already has by
        name (a world carried into a changed room keeps its battery) and is
        given the id of each store and motor that goes in: stores by name,
        motors by the two things their pin joins."""
        if not machines:
            return {}
        if not isinstance(machines, dict):
            raise LiveError("a room's machines must be an object with stores and motors")
        problems: list[str] = []
        if made is not None:
            made.setdefault("stores", {})
            made.setdefault("motors", {})
        stores: dict[str, Any] = dict(made["stores"]) if made is not None else {}
        for store in machines.get("stores") or []:
            name = str(store.get("name", ""))
            try:
                answer = session.send(
                    op="store", name=name, body=str(store.get("body", "")),
                    capacity_j=float(store.get("capacity_j", 0.0)),
                    charge_j=float(store.get("charge_j", store.get("capacity_j", 0.0))),
                    voltage_v=float(store.get("voltage_v", 24.0)),
                    max_power_w=float(store.get("max_power_w", 0.0)))
            except Exception as error:
                problems.append(f"{name or 'a store'} would not go in: {error}")
                continue
            stores[name] = answer.get("store")
            if made is not None:
                made["stores"][name] = stores[name]
        hinges = {(str(p.get("a")), str(p.get("b"))): p.get("id")
                  for p in (pins or []) if isinstance(p, dict) and str(p.get("kind", "hinge")) == "hinge"}
        for motor in machines.get("motors") or []:
            on = [str(v) for v in (motor.get("on") or [])]
            joint = hinges.get(tuple(on)) if len(on) == 2 else None
            store = stores.get(str(motor.get("store", "")))
            if joint is None or store is None:
                problems.append(f"the motor on {' and '.join(on) or 'nothing'} has "
                                + ("no pin between those two" if joint is None
                                   else f"no store called {motor.get('store', '')!r}"))
                continue
            try:
                answer = session.send(
                    op="motor", joint=joint, store=store,
                    stall_torque_n_m=float(motor.get("stall_torque_n_m", 0.0)),
                    no_load_rad_s=float(motor.get("no_load_rpm", 0.0)) * 3.141592653589793 / 30.0,
                    brake_torque_n_m=float(motor.get("brake_torque_n_m", 0.0)))
                if made is not None and answer.get("motor") is not None:
                    made["motors"][tuple(on)] = answer.get("motor")
                brake = bool(motor.get("brake", float(motor.get("brake_torque_n_m", 0.0)) > 0.0))
                command = float(motor.get("command", 0.0))
                if brake or command:
                    session.send(op="drive", motor=answer.get("motor"), command=command, brake=brake)
            except Exception as error:
                problems.append(f"the motor on {on[0]} and {on[1]} would not go on: {error}")
        return {"machine_problems": problems} if problems else {}

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
                        damping_n_s_m=float(pin.get("damping_n_s_m", 0.0)),
                        **_made_of(pin))
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
                        holds_shear_n=float(pin.get("holds_shear_n", 0.0)),
                        comes_off_n=float(pin.get("comes_off_n", 0.0)),
                        **_made_of(pin))
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
                        breaks_at_n=float(pin.get("breaks_at_n", 0.0)),
                        **_made_of(pin))
                except Exception as error:
                    problems.append(f"{pin.get('b', '?')} would not tie to "
                                    f"{pin.get('a', '?')}: {error}")
                    continue
                pin["id"] = answer.get("joint")
                if answer.get("joints") is not None:
                    state["joints"] = answer["joints"]
                continue
            if kind == "drum":
                # A rope that winds onto a turning drum (docs/machine-world.md):
                # from the drum -- a thing on a pin of its own -- to a load, for
                # as many turns as there is rope. out_mm of nothing is "as it
                # hangs": the span from the drum to the load when it goes on.
                try:
                    answer = session.send(
                        op="drum", drum=str(pin.get("a", "")), load=str(pin.get("b", "")),
                        centre=[float(v) / 1000.0 for v in (pin.get("at_mm") or [])],
                        axis=[float(v) for v in (pin.get("axis") or [0, 0, 1])],
                        radius_m=float(pin.get("radius_mm", 0.0)) / 1000.0,
                        load_point=[float(v) / 1000.0 for v in (pin.get("to_mm") or [])],
                        winds=-1 if float(pin.get("winds", 1)) < 0 else 1,
                        length_m=float(pin.get("length_mm", 0.0)) / 1000.0,
                        out_m=float(pin.get("out_mm", 0.0)) / 1000.0)
                except Exception as error:
                    problems.append(f"the rope from {pin.get('a', '?')} to {pin.get('b', '?')} "
                                    f"would not go on its drum: {error}")
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
            if body.get("mass_kg") is not None:
                # The hand and arm the strength has to move along with a throw.
                mass = float(body.get("mass_kg"))
                if not 0.0 <= mass <= 50.0:
                    raise LiveError("the hand's moving mass is kilograms, 0 to 50")
                command["mass_kg"] = mass
            return session.send(**command)

        # ---- the hand's own motions (docs/interaction-profiles.md) ----------
        def stroke_command() -> dict[str, Any]:
            # Checked here as well as in the engine, so a bad request is told
            # what is wrong in words before it costs a round trip.
            path = body.get("path")
            if not isinstance(path, list) or not 2 <= len(path) <= 16:
                raise LiveError("a stroke's path is two to sixteen points")
            points = [_three(p, "a point on a stroke's path") for p in path]
            speed = float(body.get("speed_m_s", 0.0))
            accel = float(body.get("accel_m_s2", 0.0))
            lead = float(body.get("lead_m", 0.05))
            give_up = float(body.get("give_up_s", 2.0))
            if not 0.0 < speed <= 50.0:
                raise LiveError("a stroke's speed is more than 0 and at most 50 m/s")
            if not 0.0 < accel <= 5000.0:
                raise LiveError("a stroke's acceleration is more than 0 and at most 5000 m/s2")
            if not 0.001 <= lead <= 0.5:
                raise LiveError("a stroke's lead is 1 mm to half a metre")
            if not 0.0 < give_up <= 30.0:
                raise LiveError("a stroke gives up after more than 0 and at most 30 seconds")
            return {"path": points, "speed_m_s": speed, "accel_m_s2": accel, "lead_m": lead,
                    "let_go": bool(body.get("let_go", False)), "give_up_s": give_up}

        def horizon() -> float:
            value = float(body.get("horizon_s", 3.0))
            if not 0.0 <= value <= 10.0:
                raise LiveError("a preview looks 0 to 10 seconds ahead")
            return value

        if op == "stroke":
            return session.send(op="stroke", **stroke_command())
        if op == "cancel_stroke":
            return session.send(op="cancel_stroke")
        if op == "preview_stroke":
            # Always a throw, as banjo_preview_stroke is: a hand that keeps hold
            # at the end has no flight to show. Taken from the request, with
            # stroke's default of false, a preview asked without let_go was of a
            # hand slowing to arrive at the end -- and the room's aim arc was
            # drawn from it, at a third of the throw's speed.
            return session.send(op="preview_stroke", horizon_s=horizon(),
                                **{**stroke_command(), "let_go": True})
        if op == "preview_flight":
            return session.send(**{"op": "preview_flight",
                                   "from": _three(body.get("from"), "a flight's start"),
                                   "velocity": _three(body.get("velocity"), "a flight's velocity"),
                                   "horizon_s": horizon(),
                                   "ignoring": str(body.get("ignoring", ""))})
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
        # ---- tools that work the ground (docs/ground-work.md) ---------------
        if op == "tool_point":
            tip = _three(body.get("tip"), "a point's tip")
            sizes = {key: float(body.get(key, fallback)) for key, fallback in
                     (("width_m", 0.04), ("thickness_m", 0.04), ("length_m", 0.15))}
            angle = float(body.get("angle_deg", 30.0))
            if not all(0.002 <= v <= 1.0 for v in sizes.values()) or not 5.0 <= angle <= 170.0:
                raise LiveError("a point is 2 mm to 1 m across and long, at 5 to 170 degrees")
            return session.send(op="tool_point", body=str(body.get("body", "")), tip=tip,
                                pointing=_three(body.get("pointing"), "a point's pointing"),
                                angle_deg=angle, grip=_three(body.get("grip") or tip, "a point's grip"),
                                **sizes)
        if op == "strike":
            # A bounded tool action: the engine's hand makes it at the step's
            # own rate, and what it does to the ground is the ground's.
            lever = bool(body.get("lever", False))
            speed = float(body.get("speed_m_s", 4.0))
            raise_deg = float(body.get("raise_deg", 0.0))
            lever_deg = float(body.get("lever_deg", 40.0))
            # How long the hand keeps at it before giving up: the engine's own
            # 2 s unless said -- a slow swing of a heavy tool needs longer.
            give_up = float(body.get("give_up_s", 2.0))
            if not (0.3 <= speed <= 12.0 and 0.0 <= raise_deg <= 170.0 and 5.0 <= lever_deg <= 80.0
                    and 0.2 <= give_up <= 10.0):
                raise LiveError("a tool action goes at 0.3 to 12 m/s, raised up to 170 degrees, "
                                "levered 5 to 80 degrees, given up after 0.2 to 10 s")
            command = {"op": "strike", "shoulder": _three(body.get("shoulder"), "the shoulder"),
                       "speed_m_s": speed, "raise_deg": raise_deg, "lever": lever,
                       "lever_deg": lever_deg, "give_up_s": give_up}
            if not lever:
                command["at"] = _three(body.get("at"), "where the point comes down")
            return session.send(**command)
        if op in ("tool_points", "ground_work"):
            return session.send(op=op)
        if op == "grab":
            return session.send(op="grab", name=str(body.get("name", "")))
        if op == "park":
            # Set aside, out of the world, kept as it is (LiveWorld::park): the
            # inventory's bag. Refused, with why, for what cannot be.
            name = str(body.get("name", ""))
            if not name:
                raise LiveError("park needs the name of what to set aside")
            return session.send(op="park", name=name)
        if op == "unpark":
            # And back, at rest, at `at`, facing `q` (w, x, y, z; upright if not
            # said) -- as a reply's position_m and orientation_wxyz say a body is.
            name = str(body.get("name", ""))
            if not name:
                raise LiveError("unpark needs the name of what to bring back")
            at = body.get("at")
            if not isinstance(at, list) or len(at) != 3:
                raise LiveError("unpark needs where to put it: three numbers")
            q = body.get("q", [1.0, 0.0, 0.0, 0.0])
            if not isinstance(q, list) or len(q) != 4:
                raise LiveError("unpark's facing is four numbers, w x y z")
            spot = [float(v) for v in at]
            facing = [float(v) for v in q]
            size = math.sqrt(sum(v * v for v in facing))
            if not all(math.isfinite(v) for v in spot + facing) or not size > 0.0:
                raise LiveError("unpark was given a place or a facing that is not a number")
            return session.send(op="unpark", name=name, at=spot, q=[v / size for v in facing])
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
        if op == "drive":
            # A motor told what to do (docs/machine-world.md): a command from -1
            # to 1, the share of its voltage, and whether its brake is on. The
            # room's own action step (server.run_action) comes this way.
            try:
                motor = int(body.get("motor"))
                command = float(body.get("command", 0.0))
            except (TypeError, ValueError):
                raise LiveError("drive needs a motor's number and a command from -1 to 1") from None
            if not (math.isfinite(command) and -1.0 <= command <= 1.0):
                raise LiveError("a motor's command is from -1 to 1")
            return session.send(op="drive", motor=motor, command=command,
                                brake=bool(body.get("brake", False)))
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
        if op == "mechanics":
            # What heat has done to what everything can carry. Moves nothing.
            return session.send(op="mechanics", laws=bool(body.get("laws", False)))
        if op == "member":
            # Which of a joint's two ends it is made of; "" undoes it.
            return session.send(op="member", joint=int(body.get("joint", 0)),
                                member=str(body.get("member") or ""))
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
            # Heaped by the person, so made of what they carry: the engine
            # refuses a heap bigger than what has been dug and not put back.
            return session.send(op="deposit", at=xz("at"), radius_m=radius, sand_m3=sand,
                                soil_m3=soil, from_carried=True)
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
                                breaks_at_n=breaks, **_made_of(body))
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
                                stiffness_n_m=stiffness, damping_n_s_m=damping,
                                **_made_of(body))
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
            # One-way, like an arrow on a string: no tension strength, because
            # what pulls it off is comes_off_n.
            comes_off = float(body.get("comes_off_n", 0.0))
            if not 0.0 <= comes_off <= 1e9:
                raise LiveError("a one-way fixing comes off at newtons, zero (two-way) "
                                "or more")
            if comes_off > 0.0 and holds[0] > 0.0:
                raise LiveError("a one-way fixing has no tension strength: what pulls "
                                "it off is comes_off_n")
            return session.send(op="fix", a=str(body.get("a", "")),
                                b=str(body.get("b", "")), at=spot("at"), axis=axis,
                                holds_tension_n=holds[0], holds_shear_n=holds[1],
                                comes_off_n=comes_off, **_made_of(body))
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
        if op == "place_check":
            # Where a thing would go set down on a surface, and whether it fits
            # (LiveWorld::placement). Costs no step and changes nothing: the
            # page's see-through copy asks it while someone chooses where. Still
            # checked, because a point of NaNs would reach the engine otherwise.
            on = body.get("on")
            if not isinstance(on, list) or len(on) != 3:
                raise LiveError("a placement's point needs three numbers")
            point = [float(v) for v in on]
            yaw = float(body.get("yaw_deg", 0.0))
            if not all(math.isfinite(v) for v in point + [yaw]):
                raise LiveError("a placement was given a point or a turn that is not a number")
            # `onto`: what the point is on, as pick found it; empty is the ground.
            return session.send(op="place_check", name=str(body.get("name", "")), on=point,
                                yaw_deg=((yaw + 180.0) % 360.0) - 180.0,
                                onto=str(body.get("onto") or "")[:200])
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
