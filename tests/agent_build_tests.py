"""The chat agent, asked to build the playground, and the engine asked whether it works.

Everything else in tests/ drives the physics directly, with scenes written by
hand. This drives the MODEL. A sentence a person might type into the room goes
to the real agent -- world_chat.ask, the function /api/world/ask calls, with the
MCP's own tools -- usually in an empty yard. The room it leaves behind is opened
in the real engine the way the server reopens it. And then the thing that was
asked for is USED: a gate is shoved, a wheel is turned by its handle, a sign is
left to hang, a grate is hauled up and let go. What happens is measured.

Nothing is preloaded. The playground's own rooms were laid out by hand, which
proves the engine CAN do a thing and says nothing about whether anyone can get
it built by asking -- and asking is how the playground is used.

A model is not deterministic, so a case can be tried several times and the
answer is a rate.

It costs money: every trial is a real conversation with the model named in the
local .env (up to world_chat.MAX_ROUNDS round trips). So it is not in ctest or
scripts/regression.sh. Run it on purpose:

    python tests/agent_build_tests.py                  every case, once
    python tests/agent_build_tests.py --trials 3       a pass rate per case
    python tests/agent_build_tests.py --cases wheel    cases whose id contains it
    python tests/agent_build_tests.py --list

Each run writes build/agent-regression/<time>/: summary.txt for a person, and
report.json with every tool call the model made, every answer it got back
(refusals included -- they are usually the reason), what the engine measured,
and why each check passed or failed.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import os
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "playground"))

import live_session  # noqa: E402
import world_chat    # noqa: E402
import world_room    # noqa: E402

ENGINE = next((p for p in [
    *([Path(os.environ["BANJO_LIVE_ENGINE"])] if os.environ.get("BANJO_LIVE_ENGINE") else []),
    ROOT / "build/integration/Release/banjo_live_world_run.exe",
    ROOT / "build/integration/banjo_live_world_run",
] if p.is_file()), None)

DT = 1 / 240.0              # what the room steps at

# What counts as a mechanism having moved when it was worked by hand.
HINGE_OPEN_DEG = 20.0
SLIDE_OPEN_M = 0.15
MOVE_OPEN_M = 0.20

GATE_WORDS = ("gate", "door", "portcullis", "grate", "drawbridge", "bridge", "leaf",
              "barrier", "hatch")
WHEEL_WORDS = ("wheel", "winch", "windlass", "capstan", "crank", "drum", "spindle",
               "reel", "tiller")
HANDLE_WORDS = ("handle", "grip", "spoke", "peg", "knob", "lever")


class App:
    engine_path = ENGINE
    runs_path = ROOT / "build/playground-runs"
    live_inprocess = False


# ---------------------------------------------------------------------------
# Vectors, because a hand going round an axle is a rotation
# ---------------------------------------------------------------------------

def add(a, b):
    return [a[0] + b[0], a[1] + b[1], a[2] + b[2]]


def sub(a, b):
    return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]


def scale(a, s):
    return [a[0] * s, a[1] * s, a[2] * s]


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def norm(a):
    return math.sqrt(dot(a, a))


def unit(a):
    n = norm(a)
    return scale(a, 1.0 / n) if n > 1e-12 else [0.0, 0.0, 0.0]


def rotate(v, axis, degrees):
    """Rodrigues: v turned about `axis` by `degrees`."""
    k = unit(axis)
    t = math.radians(degrees)
    c, s = math.cos(t), math.sin(t)
    return add(add(scale(v, c), scale(cross(k, v), s)), scale(k, dot(k, v) * (1.0 - c)))


# ---------------------------------------------------------------------------
# The room, as the server reopens it and the browser drives it
# ---------------------------------------------------------------------------

REALTIME_LIMIT = 1.1   # the owner's rule: no job more than 10% slower than it shows
GRACE_S = 1.0          # what the first steps of a new world may cost on top


class TooSlow(RuntimeError):
    """The engine fell behind the realtime rule, so the job stops there."""

    def __init__(self, simulated_s: float, stepping_s: float) -> None:
        super().__init__(
            f"the engine took {stepping_s:.1f} s to show {simulated_s:.2f} s "
            f"({stepping_s / max(simulated_s, 1e-9):.1f}x realtime), and no job may run "
            f"more than {REALTIME_LIMIT}x slower than what it shows")
        self.simulated_s, self.stepping_s = simulated_s, stepping_s


class World:
    def __init__(self, spec: dict[str, Any]) -> None:
        self.live = live_session.Live()
        self.opened = self.live.open(App(), {"spec": spec})
        self.session = self.live.session
        self.impacts: list[dict[str, Any]] = []
        self.cuts: list[dict[str, Any]] = []
        self.finished: list[str] = []
        # How much time the world was stepped through, and how long that took.
        # The owner's rule: no job may take more than 10% longer than realtime
        # of the interaction it runs, the settling down afterwards included.
        self.simulated_s = 0.0
        self.stepping_s = 0.0

    def close(self) -> None:
        try:
            self.live.shutdown()
        except Exception:
            pass

    def step(self, count: int = 1, hand: list[float] | None = None,
             hand_q: list[float] | None = None) -> None:
        """Advance, ANSWERING the break handshake.

        A step that would break something is taken back and the clock does not
        move until the host says what to do. A stepper that never answers stops
        the world at the first hard contact -- and a mechanism that is not moving
        looks exactly like one that cannot.

        `hand_q` is the turn the hand is to hold what it wields at; a swing is
        a grip and a turn sent a step at a time.
        """
        done = 0
        while done < count:
            n = 1 if hand is not None else min(8, count - done)
            extra = {"hand": [float(v) for v in hand]} if hand is not None else {}
            if hand is not None and hand_q is not None:
                extra["hand_q"] = [float(v) for v in hand_q]
            began = time.perf_counter()
            state = self.session.send(op="step", dt=DT, n=n, moved=True, **extra)
            self.impacts.extend(state.get("impacts") or [])
            self.cuts.extend(state.get("cuts") or [])
            if state.get("finished"):
                self.finished.append(str(state["finished"]))
            for name in state.get("breakable") or []:
                self.session.send(op="fracture", name=name, wait=False)
            done += n
            self.simulated_s += n * DT
            self.stepping_s += time.perf_counter() - began
            # The rule is enforced here, not just reported afterwards: a check
            # that goes on running a world four times slower than it shows is
            # itself the job the owner said never to run.
            if self.stepping_s > REALTIME_LIMIT * self.simulated_s + GRACE_S:
                raise TooSlow(self.simulated_s, self.stepping_s)

    def seconds(self, s: float, hand: list[float] | None = None) -> None:
        self.step(max(1, int(round(s / DT))), hand)

    def bodies(self) -> dict[str, dict[str, Any]]:
        return {b["name"]: b for b in self.session.state.get("bodies", [])}

    def body(self, name: str) -> dict[str, Any] | None:
        return self.bodies().get(name)

    def joints(self) -> list[dict[str, Any]]:
        return self.session.send(op="joints").get("joints") or []

    def joint(self, joint_id: int) -> dict[str, Any] | None:
        return next((j for j in self.joints() if j["id"] == joint_id), None)

    def anchored(self) -> dict[str, bool]:
        return {n: bool(b.get("anchored")) for n, b in self.bodies().items()}


REST_M_S = 0.05      # slower than this, nobody watching would call it moving
ESCAPED_M = 30.0     # further out than this, it has left the room


def settle(world: World, most_s: float = 10.0) -> dict[str, Any]:
    """Let go, let the room finish, and say how it looks once it has.

    The owner counts how everything looks at rest, when the interaction is
    over, as part of the interaction. So every check ends here: how long until
    nothing is moving, and whether anything has gone through the floor or off
    into the distance -- the two ways a room can look wrong after the thing that
    was asked for has been shown to work.
    """
    world.session.send(op="release")
    waited, moving = 0.0, []
    while True:
        moving = sorted(((norm(b.get("velocity_m_s") or [0.0, 0.0, 0.0]), n)
                         for n, b in world.bodies().items() if not b.get("anchored")),
                        reverse=True)
        moving = [(v, n) for v, n in moving if v > REST_M_S]
        if not moving or waited >= most_s:
            break
        world.seconds(1.0)
        waited += 1.0
    bodies = list(world.bodies().values())
    # An anchored body is where it was put and cannot have sunk: the valley's
    # marker stone is buried in its rock on purpose.
    return {"at_rest": not moving, "waited_s": waited,
            "still_moving": [[n, round(v, 3)] for v, n in moving[:3]],
            "sunk": [b["name"] for b in bodies
                     if b["position_m"][1] < -0.25 and not b.get("anchored")],
            "flew_off": [b["name"] for b in bodies
                         if max(abs(b["position_m"][0]), abs(b["position_m"][2])) > ESCAPED_M]}


def timing(world: World, check_s: float) -> dict[str, Any]:
    """The realtime rule, measured: the wall time a check took against the time
    it showed. Opening the engine counts; it is part of the job."""
    shown = max(world.simulated_s, 1e-9)
    return {"simulated_s": round(world.simulated_s, 2), "stepping_s": round(world.stepping_s, 2),
            "check_s": round(check_s, 2), "ratio": round(check_s / shown, 3),
            "within_rule": check_s <= 1.1 * shown}


def coordinate(joint: dict[str, Any] | None) -> float:
    """Degrees for a hinge, metres for anything else; 0 for a joint that is gone."""
    if joint is None:
        return 0.0
    return float(joint.get("degrees" if joint["kind"] == "hinge" else "metres", 0.0) or 0.0)


def moving_end(joint: dict[str, Any], anchored: dict[str, bool]) -> str | None:
    """The end of a joint that can move, when the other end is fixed scenery."""
    a, b = joint["a"], joint["b"]
    if anchored.get(a) and not anchored.get(b):
        return b
    if anchored.get(b) and not anchored.get(a):
        return a
    return None


def worded(name: str, words: tuple[str, ...]) -> bool:
    lower = name.lower()
    return any(w in lower for w in words)


def volume(body: dict[str, Any] | None) -> float:
    d = (body or {}).get("dimensions_m") or [0.0, 0.0, 0.0]
    return d[0] * d[1] * d[2]


def bottom(body: dict[str, Any]) -> float:
    return body["position_m"][1] - (body.get("dimensions_m") or [0, 0, 0])[1] / 2.0


def joints_in_words(joints: list[dict[str, Any]]) -> list[str]:
    return [f"{j['kind']} {j['a']} -> {j['b']}{'' if j.get('attached') else ' (off)'}"
            for j in joints]


def connected(joints: list[dict[str, Any]], sources: set[str], target: str,
              anchored: dict[str, bool]) -> bool:
    """Is there a chain of joints from any source to target?

    Not through fixed scenery: everything is connected through the ground, and
    a wheel on one post and a gate on another are not driving each other.
    """
    seen, frontier = set(sources), list(sources)
    while frontier:
        here = frontier.pop()
        for j in joints:
            if not j.get("attached") or here not in (j["a"], j["b"]):
                continue
            there = j["b"] if j["a"] == here else j["a"]
            if there == target:
                return True
            if there not in seen and not anchored.get(there):
                seen.add(there)
                frontier.append(there)
    return False


# ---------------------------------------------------------------------------
# Hands
# ---------------------------------------------------------------------------

def haul(world: World, name: str, towards: list[float], seconds: float = 1.5) -> None:
    """Take hold of `name` and draw the hand `towards` from where it is, then hold."""
    start = world.body(name)["position_m"]
    world.session.send(op="grab", name=name)
    steps = max(1, int(seconds / DT))
    for i in range(1, steps + 1):
        world.step(1, hand=add(start, scale(towards, i / steps)))
    world.step(int(0.4 / DT), hand=add(start, towards))


def turn(world: World, handle: str, pin: dict[str, Any], degrees: float, seconds: float,
         watch: Callable[[], Any]) -> tuple[list[Any], float]:
    """Take hold of `handle` and walk the hand round the pin's axle.

    The hand pulls on the middle of what it holds, so this moves the hand along
    the arc that middle would follow if the wheel turned -- which is what a
    person turning a handle does. Returns what `watch` saw, and the radius the
    hand was working at: nearly zero means the thing held is on the axle, and
    nothing a hand does to it can turn anything.
    """
    axle, axis = pin["at"], unit(pin["axis"])
    start = world.body(handle)["position_m"]
    arm = sub(start, axle)
    along = scale(axis, dot(arm, axis))
    radial = sub(arm, along)
    world.session.send(op="grab", name=handle)
    steps = max(1, int(seconds / DT))
    seen, target = [], start
    for i in range(1, steps + 1):
        target = add(add(axle, along), rotate(radial, axis, degrees * i / steps))
        world.step(1, hand=target)
        if i % 12 == 0:
            seen.append(watch())
    world.step(int(0.4 / DT), hand=target)
    seen.append(watch())
    return seen, norm(radial)


# ---------------------------------------------------------------------------
# What each request is checked against
# ---------------------------------------------------------------------------

@dataclass
class Verdict:
    ok: bool
    reason: str
    measured: dict[str, Any] = field(default_factory=dict)


@dataclass
class Built:
    room: world_room.Room
    world: World
    before: set[str]
    # What the agent said it did. A check can hold it to the engine: a reply
    # that says an iron bar is burning, over a room where nothing is, fails.
    reply: str = ""


def check_hinged_gate(built: Built) -> Verdict:
    world = built.world
    world.seconds(1.0)
    anchored = world.anchored()
    joints = world.joints()
    leaves = [(j, moving_end(j, anchored)) for j in joints
              if j["kind"] == "hinge" and j.get("attached")]
    leaves = [(j, m) for j, m in leaves if m]
    if not leaves:
        return Verdict(False, "nothing is on a hinge to anything anchored",
                       {"joints": joints_in_words(joints)})
    leaves.sort(key=lambda jm: (not worded(jm[1], GATE_WORDS), -volume(world.body(jm[1]))))
    pin, leaf = leaves[0]
    start = coordinate(world.joint(pin["id"]))
    best = 0.0
    for sign in (1.0, -1.0):
        size = world.body(leaf).get("dimensions_m") or [1, 1, 1]
        thin = [1.0, 0.0, 0.0] if size[0] <= size[2] else [0.0, 0.0, 1.0]
        haul(world, leaf, scale(thin, 0.6 * sign))
        world.session.send(op="release")
        world.seconds(0.3)
        best = max(best, abs(coordinate(world.joint(pin["id"])) - start))
        if best >= HINGE_OPEN_DEG:
            break
    measured = {"leaf": leaf, "turned_deg": round(best, 1)}
    if best >= HINGE_OPEN_DEG:
        return Verdict(True, f"{leaf} swung {best:.0f} degrees when shoved", measured)
    return Verdict(False, f"shoved both ways, {leaf} turned only {best:.1f} degrees",
                   measured)


def check_portcullis(built: Built) -> Verdict:
    world = built.world
    world.seconds(1.0)
    anchored = world.anchored()
    joints = world.joints()
    slides = [(j, moving_end(j, anchored)) for j in joints
              if j["kind"] == "slider" and j.get("attached")]
    slides = [(j, m) for j, m in slides if m]
    if not slides:
        return Verdict(False, "nothing slides on anything anchored",
                       {"joints": joints_in_words(joints)})
    slides.sort(key=lambda jm: (not worded(jm[1], GATE_WORDS), -volume(world.body(jm[1]))))
    pin, grate = slides[0]
    start = coordinate(world.joint(pin["id"]))
    axis = unit(pin["axis"])
    up = axis if axis[1] >= 0 else scale(axis, -1.0)
    haul(world, grate, scale(up, 0.6))
    raised = abs(coordinate(world.joint(pin["id"])) - start)
    # And down again: "up and down" is two directions, whatever friction the
    # grooves were given.
    haul(world, grate, scale(up, -0.6))
    world.session.send(op="release")
    world.seconds(1.5)
    after = abs(coordinate(world.joint(pin["id"])) - start)
    measured = {"grate": grate, "raised_m": round(raised, 3), "back_to_m": round(after, 3)}
    if raised < SLIDE_OPEN_M:
        return Verdict(False, f"hauled up, {grate} moved only {raised:.3f} m", measured)
    if after > 0.5 * raised:
        return Verdict(False, f"{grate} rose {raised:.2f} m and would not come back down "
                              f"(still {after:.2f} m up)", measured)
    return Verdict(True, f"{grate} rose {raised:.2f} m and came back down", measured)


def check_hanging_sign(built: Built) -> Verdict:
    world = built.world
    world.seconds(2.0)
    anchored = world.anchored()
    joints = world.joints()
    ropes = [j for j in joints if j["kind"] == "link" and j.get("attached")]
    count: dict[str, int] = {}
    for j in ropes:
        for end in (j["a"], j["b"]):
            if not anchored.get(end):
                count[end] = count.get(end, 0) + 1
    hung = [n for n, c in count.items() if c >= 2 and world.body(n)]
    if not hung:
        return Verdict(False, "nothing hangs from two ropes",
                       {"joints": joints_in_words(joints)})
    hung.sort(key=lambda n: ("sign" not in n.lower(), -volume(world.body(n))))
    sign = hung[0]
    body = world.body(sign)
    carrying = [j for j in ropes if sign in (j["a"], j["b"])
                and float(j.get("tension_n") or 0.0) > 1.0]
    measured = {"sign": sign, "bottom_m": round(bottom(body), 3),
                "ropes_carrying": len(carrying),
                "tensions_n": [round(float(j.get("tension_n") or 0.0), 1) for j in ropes
                               if sign in (j["a"], j["b"])]}
    if bottom(body) < 0.1:
        return Verdict(False, f"{sign} is down on the floor", measured)
    if len(carrying) < 2:
        return Verdict(False, f"only {len(carrying)} of the ropes on {sign} carry any "
                              f"load, so something else is holding it up", measured)
    return Verdict(True, f"{sign} hangs {bottom(body):.2f} m off the floor on "
                         f"{len(carrying)} ropes", measured)


def check_chain(built: Built) -> Verdict:
    world = built.world
    world.seconds(2.0)
    anchored = world.anchored()
    joints = world.joints()
    ropes = [j for j in joints if j["kind"] == "link" and j.get("attached")]
    near: dict[str, set[str]] = {}
    for j in ropes:
        near.setdefault(j["a"], set()).add(j["b"])
        near.setdefault(j["b"], set()).add(j["a"])
    best: list[str] = []

    def walk(path: list[str]) -> None:
        nonlocal best
        if len(path) - 1 > len(best):
            best = path[1:]
        for there in near.get(path[-1], ()):
            if there not in path and not anchored.get(there) and world.body(there):
                walk(path + [there])

    for fixed in [n for n in near if anchored.get(n)]:
        walk([fixed])
    measured = {"links_in_a_row": len(best), "chain": best}
    if len(best) < 4:
        return Verdict(False, f"the longest run of things tied one to the next and hung "
                              f"from anything fixed is {len(best)}", measured)
    lowest = min(bottom(world.body(n)) for n in best)
    measured["lowest_m"] = round(lowest, 3)
    if lowest < 0.02:
        return Verdict(False, "the chain is lying on the floor", measured)
    return Verdict(True, f"{len(best)} links hang in a row, the lowest {lowest:.2f} m "
                         f"off the floor", measured)


def check_loaded_shelf(built: Built) -> Verdict:
    world = built.world
    world.seconds(2.5)
    reply = world.session.send(op="overloaded")
    over = reply.get("overloaded") or []
    names = [str(o.get("name") or o.get("object") or "") for o in over]
    broke = list(world.finished)
    here = set(world.bodies())
    gone = [b["name"] for b in built.room.bodies()
            if b["name"] not in here and any(k.startswith(b["name"] + " piece") for k in here)]
    measured = {"overloaded": names, "fractured": broke, "in_pieces": gone}
    if names or broke or gone:
        what = names[0] if names else (broke[0] if broke else gone[0])
        return Verdict(True, f"{what} is carrying more than it can hold", measured)
    return Verdict(False, "after 2.5 s nothing reports being overloaded and nothing broke",
                   measured)


def check_drop_on_glass(built: Built) -> Verdict:
    world = built.world
    plate = "glass plate 20mm"
    new = [b for b in built.room.bodies()
           if b["name"] not in built.before and b["material"] == "iron"]
    if not new:
        return Verdict(False, "nothing new made of iron is in the room",
                       {"new": [b["name"] for b in built.room.bodies()
                                if b["name"] not in built.before]})
    ball = new[0]["name"]
    world.seconds(1.5)
    hits = [i for i in world.impacts
            if ball in (i.get("struck"), i.get("by"))
            and any(str(x or "").startswith(plate) for x in (i.get("struck"), i.get("by")))]
    measured = {"ball": ball, "impacts_with_the_plate": len(hits),
                "fastest_m_s": round(max((i.get("closing_speed_m_s", 0) for i in hits),
                                         default=0.0), 2)}
    if hits or any(n.startswith(plate) for n in world.finished):
        return Verdict(True, f"{ball} landed on the plate", measured)
    return Verdict(False, f"{ball} never touched the 20 mm glass plate", measured)


def check_castle_gate(built: Built) -> Verdict:
    """Turn the wheel by its handle; the gate must open, and close again."""
    world = built.world
    world.seconds(1.0)
    anchored = world.anchored()
    joints = [j for j in world.joints() if j.get("attached")]
    on_pins = [(j, moving_end(j, anchored)) for j in joints if j["kind"] == "hinge"]
    on_pins = [(j, m) for j, m in on_pins if m]
    wheels = [(j, m) for j, m in on_pins if worded(m, WHEEL_WORDS)]
    base = {"joints": joints_in_words(joints)}
    if not wheels:
        return Verdict(False, "nothing that turns on a pin is a wheel, winch, windlass, "
                              "capstan or crank",
                       {**base, "on_pins": [m for _, m in on_pins]})
    wheel_pin, wheel = wheels[0]
    handles = [other for j in joints if j["kind"] == "fixing" and wheel in (j["a"], j["b"])
               for other in (j["a"], j["b"]) if other != wheel and not anchored.get(other)]
    handles.sort(key=lambda n: not worded(n, HANDLE_WORDS))
    handle = handles[0] if handles else wheel
    movers = [(j, moving_end(j, anchored)) for j in joints if j["kind"] in ("hinge", "slider")]
    movers = [(j, m) for j, m in movers if m and m not in (wheel, handle)]
    if not movers:
        return Verdict(False, f"there is a wheel ({wheel}) but no gate: nothing else "
                              f"moves on a hinge or a slide", base)
    movers.sort(key=lambda jm: (not worded(jm[1], GATE_WORDS), -volume(world.body(jm[1]))))
    gate_pin, gate = movers[0]
    base.update({"wheel": wheel, "handle": handle, "gate": gate,
                 "gate_moves_on": gate_pin["kind"]})
    if not connected(joints, {wheel, handle}, gate, anchored):
        return Verdict(False, f"nothing connects {wheel} to {gate}: turning it cannot "
                              f"move the gate", base)

    start = coordinate(world.joint(gate_pin["id"]))
    centre = world.body(gate)["position_m"]
    wheel_start = coordinate(world.joint(wheel_pin["id"]))

    def watch():
        body = world.body(gate)
        return (abs(coordinate(world.joint(gate_pin["id"])) - start),
                norm(sub(body["position_m"], centre)) if body else 0.0)

    threshold = HINGE_OPEN_DEG if gate_pin["kind"] == "hinge" else SLIDE_OPEN_M
    seen, radius = turn(world, handle, wheel_pin, 150.0, 3.0, watch)
    most = max(s[0] for s in seen)
    moved = max(s[1] for s in seen)
    if most < threshold and moved < MOVE_OPEN_M:
        more, _ = turn(world, handle, wheel_pin, -300.0, 5.0, watch)
        most = max(most, max(s[0] for s in more))
        moved = max(moved, max(s[1] for s in more))
    wheel_turned = coordinate(world.joint(wheel_pin["id"])) - wheel_start
    # Back to where the wheel started, let go, and let it all settle.
    turn(world, handle, wheel_pin, -wheel_turned, 3.0, watch)
    world.session.send(op="release")
    world.seconds(2.0)
    end, _ = watch()
    unit_name = "degrees" if gate_pin["kind"] == "hinge" else "m"
    measured = {**base, "handle_radius_m": round(radius, 3),
                "wheel_turned_deg": round(wheel_turned, 1),
                "gate_opened": round(most, 3), "gate_centre_moved_m": round(moved, 3),
                "gate_after_turning_back": round(end, 3), "unit": unit_name}
    if most < threshold and moved < MOVE_OPEN_M:
        why = (f"turning {handle} round the axle moved {gate} only {most:.2f} {unit_name}"
               f" (its centre {moved:.2f} m)")
        if radius < 0.03:
            why += (f"; what was held is on the axle itself ({radius * 1000:.0f} mm off "
                    f"it), so pulling on it cannot turn the wheel -- it needs a handle")
        elif abs(wheel_turned) < 20:
            why += f"; the wheel itself turned only {wheel_turned:.0f} degrees"
        return Verdict(False, why, measured)
    if end > 0.5 * most and most >= threshold:
        return Verdict(False, f"{gate} opened {most:.2f} {unit_name}, and with the wheel "
                              f"turned back it stayed {end:.2f} {unit_name} open", measured)
    return Verdict(True, f"turning {handle} opened {gate} {most:.2f} {unit_name}; turned "
                         f"back, it closed to {end:.2f}", measured)


def _thermo(world: World) -> dict[str, Any]:
    return world.session.send(op="thermo")["thermo"]


def _heater_end_s(room: world_room.Room) -> float:
    heaters = (room.spec.get("thermo") or {}).get("heaters") or []
    return max((float(h.get("start_s") or 0.0) + float(h.get("seconds") or 0.0) for h in heaters),
               default=0.0)


def check_hearth(built: Built) -> Verdict:
    """Something burning, something warmed by it, and a burn time predicted.

    Burning is a result: nothing here asks whether a log is "on fire", it asks
    the engine what is releasing heat and what that heat reached.
    """
    world = built.world
    # Long enough for the kindling to finish and the fire to take or fail.
    world.seconds(max(120.0, _heater_end_s(built.room) + 45.0))
    report = _thermo(world)
    ambient = report["ambient"]["temperature_k"]
    burning = [b for b in report["bodies"]
               if b["reacting"] and b["heat_release_w"] > 1000.0 and b["fuel_kg"] > 0.0]
    hottest = sorted(report["bodies"], key=lambda b: -b["temperature_k"])[:4]
    measured = {"burning": [[b["name"], round(b["temperature_k"]), round(b["heat_release_w"] / 1000.0, 1)]
                            for b in burning],
                "hottest": [[b["name"], round(b["temperature_k"])] for b in hottest],
                "heater_in_kj": round(report["ledger"]["heater_in_j"] / 1000.0, 1),
                "ledger_residual_j": report["ledger"]["residual_j"]}
    if not burning:
        return Verdict(False, "nothing is burning once the kindling has finished", measured)
    warmed = [b for b in report["bodies"]
              if b["fuel_kg"] <= 0.0 and b["temperature_k"] > ambient + 2.0]
    lasting = min(b["remaining_s"] for b in burning if b.get("remaining_s"))
    measured.update(warmed=[[b["name"], round(b["temperature_k"] - ambient, 1)] for b in warmed],
                    would_last_min=round(lasting / 60.0, 1),
                    fire_kw=round(sum(b["heat_release_w"] for b in burning) / 1000.0, 1))
    if not warmed:
        return Verdict(False, f"{len(burning)} burning, but nothing that does not burn was warmed "
                              f"by it", measured)
    if abs(report["ledger"]["residual_j"]) > 1.0e-6 * abs(report["ledger"]["stored_j"]):
        return Verdict(False, "the energy ledger does not close", measured)
    return Verdict(True, f"{len(burning)} burning at {measured['fire_kw']} kW, "
                         f"estimated to last {measured['would_last_min']:.0f} min at this rate; "
                         f"warmed {', '.join(w[0] for w in measured['warmed'][:3])}", measured)


def check_heated_piston(built: Built) -> Verdict:
    """Heat the gas and what rests on the piston goes up; when the heat stops,
    it comes back down."""
    world = built.world
    # Everything is read from the opening state, at t = 0. The heater starts
    # with the world, so half a second in the gas has already lifted the load
    # about 24 mm -- a baseline taken there reads the rise short by exactly that
    # and calls a piston that came home "24 mm low".
    regions = [r for r in _thermo(world)["regions"] if r.get("piston")]
    if not regions:
        return Verdict(False, "no gas in the room pushes on anything",
                       {"regions": [r["name"] for r in _thermo(world)["regions"]]})
    region = regions[0]
    piston = region["piston"]
    body = world.body(piston)
    if body is None:
        return Verdict(False, f"the gas pushes on {piston}, which is not in the room", {})
    top = body["position_m"][1] + body["dimensions_m"][1] / 2.0
    riders = [b["name"] for b in world.bodies().values()
              if not b.get("anchored") and b["name"] != piston
              and abs((b["position_m"][1] - b["dimensions_m"][1] / 2.0) - top) < 0.03]
    start = {name: world.body(name)["position_m"][1] for name in [piston] + riders}
    heated_for = max(5.0, _heater_end_s(built.room))
    world.seconds(min(heated_for, 60.0))
    hot = next(r for r in _thermo(world)["regions"] if r["name"] == region["name"])
    rose = world.body(piston)["position_m"][1] - start[piston]
    lifted = {name: round(world.body(name)["position_m"][1] - start[name], 3) for name in riders}
    world.seconds(60.0)
    cool = next(r for r in _thermo(world)["regions"] if r["name"] == region["name"])
    back = world.body(piston)["position_m"][1] - start[piston]
    measured = {"gas": region["name"], "piston": piston, "load": riders,
                "rose_m": round(rose, 3), "load_rose_m": lifted, "hot_k": round(hot["temperature_k"]),
                "work_to_bodies_j": round(hot["work_to_bodies_j"], 1),
                "after_cooling_m": round(back, 3), "cooled_k": round(cool["temperature_k"])}
    if rose < 0.05:
        return Verdict(False, f"heated to {hot['temperature_k']:.0f} K, {piston} rose only "
                              f"{rose * 1000:.0f} mm", measured)
    if riders and min(lifted.values()) < 0.5 * rose:
        return Verdict(False, f"{piston} rose but what rests on it did not", measured)
    if back > 0.5 * rose:
        return Verdict(False, f"{piston} rose {rose:.2f} m and stayed {back:.2f} m up after the heat "
                              f"stopped", measured)
    return Verdict(True, f"heated to {hot['temperature_k']:.0f} K, the gas lifted {piston}"
                         + (f" and {', '.join(riders)}" if riders else "")
                         + f" {rose * 1000:.0f} mm; cooled, it came back to {back * 1000:.0f} mm",
                   measured)


# ---------------------------------------------------------------------------
# Blades: what an edge is swung through
# ---------------------------------------------------------------------------

def _qmul(a: list[float], b: list[float]) -> list[float]:
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return [aw * bw - ax * bx - ay * by - az * bz, aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx, aw * bz + ax * by - ay * bx + az * bw]


def _qrot(q: list[float], v: list[float]) -> list[float]:
    return _qmul(_qmul(q, [0.0] + list(v)), [q[0], -q[1], -q[2], -q[3]])[1:]


def _qfrom(m: list[list[float]]) -> list[float]:
    trace = m[0][0] + m[1][1] + m[2][2]
    if trace > 0:
        s = 0.5 / math.sqrt(trace + 1.0)
        q = [0.25 / s, (m[2][1] - m[1][2]) * s, (m[0][2] - m[2][0]) * s, (m[1][0] - m[0][1]) * s]
    elif m[0][0] > m[1][1] and m[0][0] > m[2][2]:
        s = 2.0 * math.sqrt(1.0 + m[0][0] - m[1][1] - m[2][2])
        q = [(m[2][1] - m[1][2]) / s, 0.25 * s, (m[0][1] + m[1][0]) / s, (m[0][2] + m[2][0]) / s]
    elif m[1][1] > m[2][2]:
        s = 2.0 * math.sqrt(1.0 + m[1][1] - m[0][0] - m[2][2])
        q = [(m[0][2] - m[2][0]) / s, (m[0][1] + m[1][0]) / s, 0.25 * s, (m[1][2] + m[2][1]) / s]
    else:
        s = 2.0 * math.sqrt(1.0 + m[2][2] - m[0][0] - m[1][1])
        q = [(m[1][0] - m[0][1]) / s, (m[0][2] + m[2][0]) / s, (m[1][2] + m[2][1]) / s, 0.25 * s]
    size = math.sqrt(sum(x * x for x in q))    # four numbers: unit() is for three
    return [x / size for x in q]


def _aim(blade: dict[str, Any], pointing: list[float], edge_facing: list[float]) -> list[float]:
    """The turn that points the blade along `pointing` with its edge facing `edge_facing`."""
    along = unit(sub(blade["tip_local"], blade["heel_local"]))
    faced = blade["facing_local"]
    facing = unit(sub(faced, scale(along, dot(faced, along))))
    want_along = unit(pointing)
    want_facing = unit(sub(edge_facing, scale(want_along, dot(edge_facing, want_along))))
    have = [along, facing, cross(along, facing)]
    want = [want_along, want_facing, cross(want_along, want_facing)]
    return _qfrom([[sum(want[k][r] * have[k][c] for k in range(3)) for c in range(3)]
                   for r in range(3)])


def _rope(world: World) -> tuple[list[str], str] | None:
    """A run of loose bodies tied end to end, from something fixed down to what hangs
    at the bottom: the rope's segments, top to bottom, and the thing on its end."""
    links = [j for j in world.joints() if j["kind"] == "link" and j.get("attached")]
    fixed = world.anchored()
    for top in links:
        if fixed.get(top["a"]) == fixed.get(top["b"]):
            continue
        here = top["b"] if fixed.get(top["a"]) else top["a"]
        chain, used = [here], {id(top)}
        while True:
            onward = next((j for j in links if id(j) not in used and here in (j["a"], j["b"])),
                          None)
            if onward is None:
                break
            used.add(id(onward))
            here = onward["b"] if onward["a"] == here else onward["a"]
            if fixed.get(here):
                break
            chain.append(here)
        if len(chain) >= 3:
            return chain[:-1], chain[-1]
    return None


def _swing_at(spec: dict[str, Any], edge_down: bool,
              locate: Callable[[World], tuple[list[float], dict[str, Any]] | str],
              counted: World | None = None) -> dict[str, Any]:
    """Open the room afresh, take its blade, and swing it through what `locate` names.

    The engine's own hand does it: the grip and the way the blade should face
    are sent a step at a time and the hand pulls and turns towards them with
    what it has. Up off the rest, back clear, out to one side, and then a swing
    round a shoulder half a metre behind the grip, through 100 degrees in
    0.13 s, the middle of the edge passing through the point `locate` gives --
    the blade pointing away from the person, and its edge leading, or
    (edge_down) facing the floor so that the flat leads. Nothing here says what
    is cut; the engine does. Returns what `locate` noted, the cuts, and every
    body and joint as the swing left them.

    Every step goes through World.step, so the swing is held to the realtime
    rule like anything else, and its time is added to `counted` -- the world
    the check is judged on -- so the report's realtime figure includes it.
    """
    world = World(spec)
    try:
        found = locate(world)
        if isinstance(found, str):
            return {"error": found}
        middle, noted = found
        blades = [b for b in world.session.send(op="blades").get("blades") or []
                  if b.get("attached", True)]
        if not blades:
            return {"error": "nothing in the room has an edge"}
        blade = blades[0]
        to_middle = sub(scale(add(blade["heel_local"], blade["tip_local"]), 0.5), blade["grip_local"])
        to_point = sub(blade["tip_local"], blade["grip_local"])
        reach = dot(_qrot(_aim(blade, [0.0, 0.0, -1.0], [-1.0, 0.0, 0.0]), to_middle),
                    [0.0, 0.0, -1.0])
        shoulder = [middle[0], middle[1], middle[2] + 0.5 + reach]

        def pose(angle: float) -> tuple[list[float], list[float]]:
            """The grip and the turn with the blade pointing out from the shoulder at
            `angle` (0 is straight through the target, positive to the right)."""
            out = [math.sin(angle), 0.0, -math.cos(angle)]
            going = [-math.cos(angle), 0.0, -math.sin(angle)]
            turn = _aim(blade, out, [0.0, -1.0, 0.0] if edge_down else going)
            edge_at = add(shoulder, scale(out, 0.5 + reach))
            return sub(edge_at, _qrot(turn, to_middle)), turn

        def step(hand: list[float], turn: list[float]) -> None:
            world.step(1, hand, turn)

        def go(a: list[float], b: list[float], turn: list[float], seconds: float) -> list[float]:
            n = max(1, int(round(seconds / DT)))
            for i in range(1, n + 1):
                step(add(a, scale(sub(b, a), i / n)), turn)
            return b

        wide = math.radians(50.0)
        ready, turn = pose(wide)
        before = {name: list(body["position_m"]) for name, body in world.bodies().items()}
        start = list(blade["grip"])
        world.session.send(op="wield", name=blade["body"], grip=start)
        # Far enough towards the person that the point stays 0.15 m short of the target.
        clear_z = middle[2] + 0.15 - _qrot(turn, to_point)[2]
        here = go(start, add(start, [0.0, 0.3, 0.0]), turn, 0.5)
        here = go(here, [here[0], middle[1], max(here[2], clear_z)], turn, 0.6)
        here = go(here, [ready[0], middle[1], max(here[2], clear_z)], turn, 0.6)
        here = go(here, ready, turn, 0.5)
        for _ in range(int(0.5 / DT)):
            step(here, turn)
        steps = int(round(0.13 / DT))
        for i in range(1, steps + 1):
            here, turn = pose(wide - 2.0 * wide * i / steps)
            step(here, turn)
        for _ in range(int(2.0 / DT)):
            step(here, turn)
        # A cut is reported on each step it goes on for; one entry per cut.
        cuts = {(c.get("blade"), c.get("target"), c.get("at_s")): c for c in world.cuts}
        met = [{"kind": c["kind"], "target": c["target"], "speed_m_s": round(c["speed_m_s"], 2),
                "area_mm2": round(c.get("area_mm2", 0.0), 1), "bonds": c.get("bonds", 0),
                "links": c.get("links", 0), "separated": bool(c.get("separated"))}
               for c in cuts.values()]
        bodies = world.bodies()
        return {**noted, "cuts": met, "joints": world.joints(),
                "before": before, "after": {n: list(b["position_m"]) for n, b in bodies.items()}}
    finally:
        if counted is not None:
            counted.simulated_s += world.simulated_s
            counted.stepping_s += world.stepping_s
        world.close()


def _rope_at(world: World) -> tuple[list[float], dict[str, Any]] | str:
    found = _rope(world)
    if found is None:
        return ("there is no rope: a run of loose bodies tied end to end, from something "
                "fixed down to what hangs on it")
    segments, weight = found
    struck = segments[len(segments) // 2]
    return list(world.body(struck)["position_m"]), {"segments": segments, "weight": weight,
                                                   "struck": struck}


def _swing_through(spec: dict[str, Any], edge_down: bool,
                   counted: World | None = None) -> dict[str, Any]:
    swung = _swing_at(spec, edge_down, _rope_at, counted)
    if "error" in swung:
        return swung
    links = [j for j in swung["joints"] if j["kind"] == "link"]
    weight = swung["weight"]
    return {"segments": swung["segments"], "weight": weight, "struck": swung["struck"],
            "fell_m": round(swung["before"][weight][1] - swung["after"][weight][1], 3),
            "cuts": swung["cuts"], "ties_off": sum(1 for j in links if not j.get("attached")),
            "links_cut": sum(c["links"] for c in swung["cuts"])}


def _panel_at(world: World) -> tuple[list[float], dict[str, Any]] | str:
    """A loose body held up by fixings to something fixed: what is to be cut."""
    fixed = world.anchored()
    held: dict[str, int] = {}
    for j in world.joints():
        if j["kind"] != "fixing" or not j.get("attached"):
            continue
        for a, b in ((j["a"], j["b"]), (j["b"], j["a"])):
            if fixed.get(a) and not fixed.get(b):
                held[b] = held.get(b, 0) + 1
    if not held:
        return "there is no panel: a loose body held up by fixings to something fixed"
    panel = max(held, key=lambda name: (held[name], volume(world.body(name))))
    return list(world.body(panel)["position_m"]), {"panel": panel}


def check_cut_panel(built: Built) -> Verdict:
    """A panel on fixings, cut in two by a person's swing through its middle: the
    lower piece falls and the upper keeps its fixings. The flat cuts nothing."""
    edge = _swing_at(built.room.spec, False, _panel_at, built.world)
    if "error" in edge:
        return Verdict(False, edge["error"], edge)
    panel = edge["panel"]
    flat = _swing_at(built.room.spec, True, _panel_at, built.world)
    pieces = sorted((n for n in edge["after"] if n.startswith(panel + " piece")),
                    key=lambda n: edge["after"][n][1])
    fixings = [j for j in edge["joints"] if j["kind"] == "fixing"]
    measured = {"panel": panel, "cuts": edge["cuts"], "pieces": {n: edge["after"][n] for n in pieces},
                "fixings": [[j["a"], j["b"], j.get("attached")] for j in fixings],
                "flat_cuts": flat.get("cuts")}
    bit = [c for c in edge["cuts"] if c["kind"] in ("edge", "slice") and c["bonds"] > 0]
    if not bit:
        return Verdict(False, f"swung edge-first through {panel}, the sword did not bite it: "
                              f"{edge['cuts']}", measured)
    if len(pieces) < 2:
        return Verdict(False, f"the sword cut {sum(c['area_mm2'] for c in bit):.0f} mm2 into "
                              f"{panel} and it held together", measured)
    lower, upper = pieces[0], pieces[-1]
    dropped = edge["before"][panel][1] - edge["after"][lower][1]
    if dropped < 0.3:
        return Verdict(False, f"{panel} came apart but its lower piece fell only {dropped:.2f} m",
                       measured)
    if not fixings or any(not j.get("attached") or upper not in (j["a"], j["b"]) for j in fixings):
        return Verdict(False, f"the fixings did not stay with the upper piece: {measured['fixings']}",
                       measured)
    if flat.get("error") or any(c["bonds"] > 0 for c in flat.get("cuts") or []):
        return Verdict(False, f"the flat of the same swing cut {panel}", measured)
    return Verdict(True, f"swung edge-first at {max(c['speed_m_s'] for c in bit):.1f} m/s the "
                         f"sword cut {panel} in two ({sum(c['area_mm2'] for c in bit):.0f} mm2): "
                         f"the lower piece fell {dropped:.2f} m, the upper is still on its "
                         f"{len(fixings)} fixings; the flat of the same swing cut nothing", measured)


def check_cut_rope(built: Built) -> Verdict:
    """The rope cut by a person's swing -- the engine's own hand, edge first -- and
    not by the flat of the same swing. Nothing here decides that anything is cut."""
    edge = _swing_through(built.room.spec, edge_down=False, counted=built.world)
    if "error" in edge:
        return Verdict(False, edge["error"], edge)
    flat = _swing_through(built.room.spec, edge_down=True, counted=built.world)
    measured = {"edge_first": edge, "flat_first": flat}
    bit = [c for c in edge["cuts"] if c["kind"] in ("edge", "slice") and c["bonds"] > 0]
    if not bit:
        return Verdict(False, f"swung edge-first through {edge['struck']}, the sword did not bite "
                              f"it: {edge['cuts']}", measured)
    if edge["fell_m"] < 0.3:
        return Verdict(False, f"the rope was cut into, but {edge['weight']} fell only "
                              f"{edge['fell_m']:.2f} m", measured)
    if edge["ties_off"] > edge["links_cut"]:
        return Verdict(False, "a tie came off that the edge never went through", measured)
    if flat.get("error"):
        return Verdict(False, flat["error"], measured)
    if any(c["bonds"] > 0 or c["links"] > 0 for c in flat["cuts"]):
        return Verdict(False, f"the flat of the same swing cut the rope: {flat['cuts']}", measured)
    if flat["fell_m"] > 0.2:
        return Verdict(False, f"under the flat, {flat['weight']} fell {flat['fell_m']:.2f} m",
                       measured)
    return Verdict(True, f"swung edge-first at {max(c['speed_m_s'] for c in bit):.1f} m/s the sword "
                         f"cut {sum(c['area_mm2'] for c in bit):.0f} mm2 of {edge['struck']} and "
                         f"{edge['weight']} fell {edge['fell_m']:.2f} m with every other tie on; "
                         f"the flat of the same swing cut nothing", measured)


@dataclass
class Case:
    id: str
    scene: str
    message: str
    check: Callable[[Built], Verdict]
    tests: str
    # When changing nothing is a right answer, what the reply must say for it to
    # count: the courtyard has no room for a gate, and an agent that says so is
    # doing better than one that clears a person's room unasked.
    accept_no_change: Callable[[str], bool] | None = None


# ---------------------------------------------------------------------------
# Terrain and water: what the valley does with what was built in it
# ---------------------------------------------------------------------------
#
# Every number here is the engine's: the river's level along its course, a
# pond's depth, what the water lifts against what a thing weighs. Nothing asks
# whether something "is a dam"; it asks whether the water rose behind it.

WATER_KG_M3 = 1000.0
MATERIAL_KG_M3 = {"iron": 7870.0, "aluminum": 2700.0, "glass": 2500.0, "ceramic": 3900.0,
                  "oak": 700.0, "rubber": 1100.0, "ice": 917.0, "concrete": 2400.0}


def _environment(world: World) -> dict[str, Any]:
    return world.session.send(op="environment")["environment"]


def _survey(world: World, x: float, z: float) -> dict[str, Any]:
    return world.session.send(op="survey", at=[x, z])["survey"]


def _river_at(report: dict[str, Any], x: float) -> dict[str, Any] | None:
    path = report["water"]["river_path"]
    return min(path, key=lambda p: abs(p["x_m"] - x)) if path else None


def _water_closes(report: dict[str, Any]) -> bool:
    """Mass conserved to rounding: volume - initial = in - out + numerical + residual,
    with the residual what is left once everything else is counted."""
    water = report["water"]
    return abs(water["residual_m3"]) <= 1.0e-9 * max(1.0, water["volume_m3"])


def check_dam(built: Built) -> Verdict:
    """Water rises behind a dam of ordinary things standing in the river."""
    world = built.world
    report = _environment(world)
    if not report or not report["water"]["river_path"]:
        return Verdict(False, "there is no river in this room", {})

    def in_river(body: dict[str, Any]) -> bool:
        x, _, z = body["position_m"]
        at = _river_at(report, x)
        return (abs(at["x_m"] - x) <= 1.5
                and at["wet_from_z_m"] - 0.75 <= z <= at["wet_to_z_m"] + 0.75)

    dam = [b for b in world.bodies().values()
           if not b.get("anchored") and MATERIAL_KG_M3.get(b.get("material"), 0.0) > WATER_KG_M3
           and in_river(b)]
    if not dam:
        return Verdict(False, "nothing that sinks stands in the river",
                       {"river_at_x0": _river_at(report, 0.0)})
    x_dam = sum(b["position_m"][0] for b in dam) / len(dam)
    up = _river_at(report, x_dam - 3.0)
    start = {b["name"]: list(b["position_m"]) for b in dam}
    world.seconds(30.0)
    after = _environment(world)
    up_after = min(after["water"]["river_path"], key=lambda p: abs(p["x_m"] - up["x_m"]))
    moved = max(norm(sub(world.body(n)["position_m"], start[n])) for n in start if world.body(n))
    rose = up_after["level_m"] - up["level_m"]
    measured = {"dam": sorted(start), "dam_x_m": round(x_dam, 2), "upstream_x_m": round(up["x_m"], 2),
                "upstream_level_m": [round(up["level_m"], 3), round(up_after["level_m"], 3)],
                "blocks_moved_most_m": round(moved, 3),
                "in_out_m3_s": [round(after["water"]["inflow_m3_s"], 3),
                                round(after["water"]["outflow_m3_s"], 3)],
                "unaccounted_m3": after["water"]["residual_m3"]}
    if not _water_closes(after):
        return Verdict(False, "the water's ledger does not close", measured)
    if rose < 0.05:
        return Verdict(False, f"3 m upstream of the dam the river rose only {rose * 1000:.0f} mm "
                              f"in 30 s", measured)
    return Verdict(True, f"3 m upstream of the {len(dam)}-piece dam the river rose from "
                         f"{up['level_m']:.2f} to {up_after['level_m']:.2f} m in 30 s", measured)


def _pond_level(world: World, pond: dict[str, Any]) -> tuple[float | None, float]:
    """A pond's level: the highest standing water within 1.5 m of its middle,
    and the lowest ground there, for a pond that has gone dry. Its middle alone
    will not do: a channel dug through it is deeper than the pond round it, and
    the water in it is the lowest, not the pond's level."""
    cx, cz = pond["at_m"]
    points = [(cx, cz)] + [(cx + r * math.cos(k * math.pi / 4.0), cz + r * math.sin(k * math.pi / 4.0))
                           for r in (0.75, 1.5) for k in range(8)]
    level, ground = None, math.inf
    for x, z in points:
        here = _survey(world, x, z)
        if not here.get("on_the_ground"):
            continue
        ground = min(ground, here["ground_m"])
        water = here.get("water") or {}
        if water.get("depth_m", 0.0) > 0.01:
            level = water["surface_m"] if level is None else max(level, water["surface_m"])
    return level, ground


def check_pond_drains(built: Built) -> Verdict:
    """A channel dug from a pond to lower ground lets the pond out."""
    world = built.world
    report = _environment(world)
    ponds = [p for p in (report or {}).get("water", {}).get("ponds", [])
             if p.get("depth_now_m", 0.0) > 0.05]
    if not ponds:
        return Verdict(False, "there is no pond with water in it", {})
    before = {p["name"]: _pond_level(world, p) for p in ponds}
    world.seconds(30.0)
    after_report = _environment(world)
    after = {p["name"]: _pond_level(world, p) for p in ponds}

    def fall(name: str) -> float:
        (was, _), (now, ground) = before[name], after[name]
        return 0.0 if was is None else was - (now if now is not None else ground)

    fell = {n: fall(n) for n in before}
    best = max(fell, key=fell.get)
    measured = {"pond_level_m": {n: [before[n][0] and round(before[n][0], 3),
                                     after[n][0] and round(after[n][0], 3)] for n in before},
                "out_m3_s": round(after_report["water"]["outflow_m3_s"], 3),
                "unaccounted_m3": after_report["water"]["residual_m3"]}
    if not _water_closes(after_report):
        return Verdict(False, "the water's ledger does not close", measured)
    if fell[best] < 0.1:
        return Verdict(False, f"in 30 s {best} went down only {fell[best] * 1000:.0f} mm", measured)
    return Verdict(True, f"{best} went down {fell[best]:.2f} m in 30 s", measured)


def check_log_floats(built: Built) -> Verdict:
    """Oak in the river floats and the current carries it: buoyancy from what it
    displaces, drag from how the water moves past it."""
    world = built.world
    logs = [b for b in world.bodies().values() if b.get("material") == "oak" and not b.get("anchored")]
    wet = []
    for b in logs:
        here = _survey(world, b["position_m"][0], b["position_m"][2])
        if (here.get("water") or {}).get("depth_m", 0.0) > 0.05:
            wet.append(b)
    if not wet:
        return Verdict(False, "no oak is in the water", {"oak": [b["name"] for b in logs]})
    start = {b["name"]: list(b["position_m"]) for b in wet}
    world.seconds(15.0)
    report = _environment(world)
    held = {a["name"]: a for a in report["water"]["bodies_in_water"]}
    drift = {n: world.body(n)["position_m"][0] - start[n][0] for n in start if world.body(n)}
    best = max(drift, key=drift.get)
    measured = {"start_m": start, "drifted_downstream_m": {n: round(d, 2) for n, d in drift.items()},
                "lifted_n_of_weight_n": {n: [round(held[n]["buoyancy_n"], 1), round(held[n]["weight_n"], 1)]
                                         for n in start if n in held}}
    if best not in held or not held[best]["floats"]:
        return Verdict(False, f"{best} is not floating", measured)
    if drift[best] < 1.0:
        return Verdict(False, f"{best} floats but went only {drift[best]:.2f} m downstream in 15 s",
                       measured)
    return Verdict(True, f"{best} floats -- the water holds up {held[best]['buoyancy_n']:.0f} N of "
                         f"its {held[best]['weight_n']:.0f} N -- and went {drift[best]:.1f} m "
                         f"downstream in 15 s", measured)


def check_boulder_falls(built: Built) -> Verdict:
    """Dig the ground from under a boulder and it falls: the changed ground's
    collider is rebuilt and what it held up is woken. The dig is the person's,
    made the way Dig here makes it: through the room, while it runs."""
    world = built.world
    world.seconds(2.0)   # let it come to rest where it was put
    resting = []
    for b in world.bodies().values():
        if b.get("anchored") or MATERIAL_KG_M3.get(b.get("material"), 0.0) <= WATER_KG_M3:
            continue
        here = _survey(world, b["position_m"][0], b["position_m"][2])
        if not here.get("on_the_ground") or (here.get("water") or {}).get("depth_m", 0.0) > 0.0:
            continue
        if abs(bottom(b) - here["ground_m"]) > 0.1:
            continue
        resting.append((volume(b) * MATERIAL_KG_M3[b["material"]], b))
    if not resting:
        return Verdict(False, "nothing heavy rests on dry ground", {})
    _, boulder = max(resting, key=lambda pair: pair[0])
    name = boulder["name"]
    x, y0, z = boulder["position_m"]
    width = max(boulder["dimensions_m"][0], boulder["dimensions_m"][2]) + 0.4
    dug = world.session.send(op="dig", **{"from": [x, z], "to": [x, z], "width_m": width,
                                          "depth_m": 0.5}).get("dug") or {}
    world.seconds(4.0)
    y1 = world.body(name)["position_m"][1]
    measured = {"boulder": name, "dug_m3": round(dug.get("sand_m3", 0.0) + dug.get("soil_m3", 0.0), 3),
                "colliders_rebuilt": dug.get("chunks_rebuilt"), "woken": dug.get("bodies_woken"),
                "fell_m": round(y0 - y1, 3)}
    if y0 - y1 < 0.15:
        return Verdict(False, f"dug under, {name} went down only {(y0 - y1) * 1000:.0f} mm", measured)
    return Verdict(True, f"dug under, {name} fell {y0 - y1:.2f} m into the pit", measured)


CASES = [
    Case("hinged-gate", "yard", "Build a wooden gate on a hinge between two stone posts.",
         check_hinged_gate, "a hinge placed so it can swing"),
    Case("portcullis", "yard",
         "Build a portcullis: an iron grate that slides up and down between two stone "
         "posts.", check_portcullis, "a slide, with travel both ways"),
    Case("hanging-sign", "yard", "Hang a wooden sign from a beam by two ropes.",
         check_hanging_sign, "ropes that carry a load"),
    Case("chain", "yard", "Hang a chain of six iron links from a wooden beam.",
         check_chain, "a run of bodies, each tied to the next"),
    Case("loaded-shelf", "yard",
         "Build a thin stone shelf across two piers and stack enough iron on it that it "
         "is carrying more than it can hold.", check_loaded_shelf,
         "sustained load, found from statics rather than from a hit"),
    Case("castle-gate", "yard", "Build a castle gate that opens and closes with a wheel.",
         check_castle_gate, "the request that did not make it: a wheel that drives a gate"),
    Case("castle-gate-courtyard", "courtyard",
         "Clear the courtyard and build a castle gate that opens and closes with a wheel.",
         check_castle_gate,
         "the courtyard cleared first -- the path that failed on its leftover joints"),
    Case("courtyard-full", "courtyard",
         "Build a castle gate that opens and closes with a wheel.", check_castle_gate,
         "the courtyard as it stands, 15,364 of 16,000 cells full: build a working gate, "
         "or change nothing and say why",
         accept_no_change=lambda reply: bool(re.search(
             r"\b(clear|fit|space|cells|yard)\b", reply, re.I))),
    Case("drop-on-glass", "bench",
         "Drop an iron ball onto the 20 mm glass plate from two metres up.",
         check_drop_on_glass, "placing something over a target"),
    Case("hearth", "yard",
         "Build a hearth of oak logs on a stone slab with an iron kettle beside it, and light it.",
         check_hearth, "fuel, ignition, heat reaching a physical object, and a predicted burn time"),
    Case("heated-piston", "yard",
         "Build a cylinder with an iron piston in it and a weight on the piston, with gas under "
         "the piston, and heat the gas so it lifts the weight.",
         check_heated_piston, "heat into gas into work: a pressure boundary on a real body"),
    Case("cut-rope", "yard",
         "Hang an iron weight from a beam by a rope, and put a sword where I can take it, so "
         "I can cut the rope.",
         check_cut_rope, "an edge that cuts what it is swung through, a load that falls, and "
         "a flat that does not cut"),
    Case("cut-panel", "yard",
         "Hang an oak panel from a beam on two fixings, and put a sword where I can take it, "
         "so I can cut the panel in two.",
         check_cut_panel, "a cut all the way through that makes pieces, with the fixings "
         "staying on the piece that holds them"),
    Case("dam-river", "valley", "Dam the river with stone blocks so the water backs up behind them.",
         check_dam, "a dam of ordinary objects backing a river up, with its water accounted for"),
    Case("drain-pond", "valley", "Dig a channel to drain the pond.",
         check_pond_drains, "a dug channel letting standing water out"),
    Case("log-river", "valley", "Put an oak log in the river.",
         check_log_floats, "floating by displaced volume, and drifting by drag"),
    Case("boulder-dug", "valley",
         "Put a big stone boulder on the river bank, where I can dig the ground out from under it.",
         check_boulder_falls, "ground dug from under something, and only what it held woken"),
]


# ---------------------------------------------------------------------------
# The builds the guide describes, as the MCP calls that make them
# ---------------------------------------------------------------------------
#
# Run with --recipes: each is built through the MCP on the case's own room and
# then faces the case's own check. If one of these fails, the guide is teaching
# the model something that does not work, and no amount of model will fix it.

def _box(name, material, size, at, anchored=False):
    return ("add_object", {"object": {"name": name, "shape": "box", "material": material,
                                      "size_m": size, "position_m": at,
                                      "anchored": anchored}})


RECIPES: dict[str, tuple[str, list[tuple[str, dict[str, Any]]]]] = {
    # A gate hung IN FRONT of its post, a cell clear of the floor, the pin at
    # the post's face and the leaf's own depth. The far post stands a cell past
    # the leaf's end, so nothing rubs.
    "hinged-gate": ("hinged-gate", [
        _box("stone post", "concrete", [0.16, 2.0, 0.16], [0.0, 1.0, 0.0], True),
        _box("far post", "concrete", [0.16, 2.0, 0.16], [1.44, 1.0, 0.0], True),
        _box("oak gate", "oak", [1.2, 1.6, 0.08], [0.68, 0.84, 0.16]),
        ("hinge", {"a": "stone post", "b": "oak gate", "at_m": [0.08, 0.84, 0.16],
                   "axis": [0, 1, 0], "lower_deg": 0, "upper_deg": 100,
                   "friction_n_m": 10}),
    ]),
    # A castle gate as a castle has one: a portcullis, raised by a winch. The
    # rope runs from the TOP of the wheel's rim over two pulleys to the top of
    # the grate, load at b, ratio 2 -- so turning the wheel either way carries
    # the rim point away from its pulley and the grate rises half as far.
    "castle-gate-winch": ("castle-gate", [
        _box("left post", "concrete", [0.16, 2.4, 0.16], [-0.72, 1.2, 0.0], True),
        _box("right post", "concrete", [0.16, 2.4, 0.16], [0.72, 1.2, 0.0], True),
        _box("lintel", "oak", [1.6, 0.12, 0.16], [0.0, 2.46, 0.0], True),
        _box("castle gate", "oak", [1.28, 1.04, 0.08], [0.0, 0.52, 0.16]),
        ("slide", {"a": "left post", "b": "castle gate", "at_m": [0.0, 0.52, 0.16],
                   "axis": [0, 1, 0], "lower_m": 0.0, "upper_m": 1.2,
                   "friction_n": 100}),
        _box("winch post", "concrete", [0.16, 1.2, 0.16], [1.6, 0.6, 0.0], True),
        _box("winch wheel", "oak", [0.64, 0.64, 0.08], [1.6, 1.0, 0.16]),
        ("hinge", {"a": "winch post", "b": "winch wheel", "at_m": [1.6, 1.0, 0.16],
                   "axis": [0, 0, 1], "lower_deg": -180, "upper_deg": 180,
                   "friction_n_m": 2}),
        _box("winch handle", "oak", [0.08, 0.08, 0.16], [1.6, 1.24, 0.28]),
        ("fix", {"a": "winch wheel", "b": "winch handle", "at_m": [1.6, 1.24, 0.2],
                 "axis": [0, 0, 1]}),
        ("reeve", {"a": "winch wheel", "b": "castle gate",
                   "at_a_m": [1.6, 1.32, 0.16], "at_b_m": [0.0, 1.04, 0.16],
                   "over_a_m": [1.6, 2.3, 0.16], "over_b_m": [0.0, 2.3, 0.16],
                   "ratio": 2}),
    ]),
    # A gate that SWINGS, worked by a capstan: a flat wheel on an upright axle,
    # a peg to push it round by, and a stiff spring from its rim to the gate as
    # a connecting rod. The capstan stands beyond the reach of the gate's swing.
    "castle-gate-capstan": ("castle-gate", [
        _box("stone post", "concrete", [0.16, 2.0, 0.16], [0.0, 1.0, 0.0], True),
        _box("far post", "concrete", [0.16, 2.0, 0.16], [1.44, 1.0, 0.0], True),
        _box("oak gate", "oak", [1.2, 1.6, 0.08], [0.68, 0.84, 0.16]),
        # Free BOTH ways. The capstan pulls the gate towards itself, and a gate
        # whose limit only lets it open the other way is pinned against its stop
        # -- which is exactly what a model did, copying this recipe with the
        # first recipe's limits. A leaf hung this way never crosses its own pin,
        # so swinging both ways cannot put it into its post.
        ("hinge", {"a": "stone post", "b": "oak gate", "at_m": [0.08, 0.84, 0.16],
                   "axis": [0, 1, 0], "lower_deg": -100, "upper_deg": 100,
                   "friction_n_m": 10}),
        _box("capstan post", "concrete", [0.16, 1.36, 0.16], [0.68, 0.68, 1.6], True),
        # A cell ABOVE its post, not sitting on it: a wheel resting on its post
        # rubs on it, which the hinge call says, and which this passed anyway only
        # because a hand is strong.
        _box("capstan wheel", "oak", [0.48, 0.08, 0.48], [0.68, 1.44, 1.6]),
        ("hinge", {"a": "capstan post", "b": "capstan wheel", "at_m": [0.68, 1.44, 1.6],
                   "axis": [0, 1, 0], "lower_deg": -180, "upper_deg": 180,
                   "friction_n_m": 2}),
        _box("capstan handle", "oak", [0.08, 0.16, 0.08], [0.88, 1.56, 1.6]),
        ("fix", {"a": "capstan wheel", "b": "capstan handle", "at_m": [0.88, 1.48, 1.6],
                 "axis": [0, 1, 0]}),
        ("spring", {"a": "capstan wheel", "b": "oak gate",
                    "at_a_m": [0.68, 1.44, 1.36], "at_b_m": [0.68, 1.44, 0.20],
                    "rest_m": 0.0, "stiffness_n_m": 20000, "damping_n_s_m": 200}),
    ]),
    # A hearth: two oak logs on a stone slab and one across them, an iron kettle
    # beside it, and kindling -- 10 kW under each of the bottom logs for 90 s.
    # Less than that on a stone slab warms the logs and goes out: the slab and
    # the cold log beside take the margin a lone log would have.
    "hearth": ("hearth", [
        _box("hearth stone", "concrete", [0.8, 0.08, 0.64], [0.0, 0.04, 0.0], True),
        _box("log 1", "oak", [0.12, 0.12, 0.48], [-0.08, 0.14, 0.0]),
        _box("log 2", "oak", [0.12, 0.12, 0.48], [0.08, 0.14, 0.0]),
        _box("log 3", "oak", [0.48, 0.12, 0.12], [0.0, 0.26, 0.0]),
        _box("kettle", "iron", [0.16, 0.16, 0.16], [0.36, 0.16, 0.0]),
        ("heat", {"target": "log 1", "power_w": 10000, "seconds": 90, "label": "kindling"}),
        ("heat", {"target": "log 2", "power_w": 10000, "seconds": 90, "label": "kindling"}),
    ]),
    # A heated piston: a cylinder of anchored walls with a glass front, an iron
    # piston on a slide over 0.4 m of argon, an iron weight on the piston, and
    # 800 W under the gas for 30 s.
    "heated-piston": ("heated-piston", [
        _box("cylinder base", "concrete", [0.48, 0.08, 0.48], [0.0, 0.04, 0.0], True),
        _box("cylinder wall left", "concrete", [0.08, 1.2, 0.48], [-0.2, 0.68, 0.0], True),
        _box("cylinder wall right", "concrete", [0.08, 1.2, 0.48], [0.2, 0.68, 0.0], True),
        _box("cylinder wall back", "concrete", [0.32, 1.2, 0.08], [0.0, 0.68, -0.2], True),
        _box("cylinder window", "glass", [0.32, 1.2, 0.08], [0.0, 0.68, 0.2], True),
        _box("piston", "iron", [0.24, 0.08, 0.24], [0.0, 0.52, 0.0]),
        _box("weight", "iron", [0.16, 0.16, 0.16], [0.0, 0.64, 0.0]),
        ("slide", {"a": "cylinder base", "b": "piston", "at_m": [0.0, 0.52, 0.0],
                   "axis": [0, 1, 0], "lower_m": -0.2, "upper_m": 0.6, "friction_n": 0}),
        ("enclose_gas", {"name": "cylinder gas", "piston": "piston", "height_m": 0.4,
                         "contents": {"argon": 1}}),
        ("heat", {"target": "cylinder gas", "power_w": 800, "seconds": 30}),
    ]),
    # A thin concrete shelf: 40 mm over an 840 mm span, about 900 N to break.
    # Two 200 mm iron blocks are 617 N each, and together they are too much.
    "loaded-shelf": ("loaded-shelf", [
        _box("left pier", "concrete", [0.16, 0.8, 0.16], [-0.5, 0.4, 0.0], True),
        _box("right pier", "concrete", [0.16, 0.8, 0.16], [0.5, 0.4, 0.0], True),
        _box("stone shelf", "concrete", [1.2, 0.04, 0.24], [0.0, 0.82, 0.0]),
        _box("iron block", "iron", [0.2, 0.2, 0.2], [-0.12, 0.94, 0.0]),
        _box("second iron block", "iron", [0.2, 0.2, 0.2], [0.12, 0.94, 0.0]),
    ]),
    # A rope that can be cut: six rubber segments, each tied to the next at the
    # join -- between the centres of the cells either side of it, so the tie
    # runs through matter an edge can go through -- from an oak beam down to 4 kg
    # of iron, 19 times a segment's mass. And a sword the person can take from
    # its rest: an aluminium bar with an edge along its far side, 2.8 kg, light
    # enough for an 800 N hand to swing at 10 m/s.
    "cut-rope": ("cut-rope", [
        _box("rope beam", "oak", [0.24, 0.08, 0.08], [-0.5, 2.04, 1.4], True),
        *[_box(f"rope {k}", "rubber", [0.04, 0.12, 0.04], [-0.5, 2.06 - 0.12 * k, 1.4])
          for k in range(1, 7)],
        _box("weight", "iron", [0.08, 0.08, 0.08], [-0.5, 1.24, 1.4]),
        ("tie", {"a": "rope beam", "b": "rope 1",
                 "at_a_m": [-0.5, 2.02, 1.4], "at_b_m": [-0.5, 1.98, 1.4]}),
        *[("tie", {"a": f"rope {k}", "b": f"rope {k + 1}",
                   "at_a_m": [-0.5, 2.02 - 0.12 * k, 1.4], "at_b_m": [-0.5, 1.98 - 0.12 * k, 1.4]})
          for k in range(1, 6)],
        ("tie", {"a": "rope 6", "b": "weight",
                 "at_a_m": [-0.5, 1.30, 1.4], "at_b_m": [-0.5, 1.26, 1.4]}),
        _box("sword rest left", "oak", [0.08, 0.08, 0.08], [-0.24, 0.96, 1.9], True),
        _box("sword rest right", "oak", [0.08, 0.08, 0.08], [0.24, 0.96, 1.9], True),
        _box("sword", "aluminum", [0.64, 0.04, 0.04], [0.0, 1.02, 1.9]),
        ("blade", {"body": "sword", "heel_m": [0.2, 1.02, 1.88], "tip_m": [-0.3, 1.02, 1.88],
                   "facing": [0, 0, -1], "thickness_m": 0.04, "edge_radius_m": 0.0002,
                   "bevel_deg": 30, "grip_m": [0.28, 1.02, 1.9]}),
    ]),
    # A panel to cut in two: 40 mm of oak -- the thinnest a 0.04 m room makes it
    # -- 0.32 m across and 0.24 m tall, hung under an anchored oak lintel on two
    # fixings where they meet, near its top corners. Across it that is
    # 12,800 mm2, and a keen edge (0.05 mm) meets oak at 4.5 kJ/m2: 58 J, which
    # one swing of the aluminium sword pays. With a working edge (0.2 mm,
    # 15 kJ/m2) it would be 192 J.
    "cut-panel": ("cut-panel", [
        _box("panel lintel", "oak", [0.48, 0.08, 0.08], [0.6, 1.76, 1.4], True),
        _box("oak panel", "oak", [0.32, 0.24, 0.04], [0.6, 1.60, 1.4]),
        ("fix", {"a": "panel lintel", "b": "oak panel", "at_m": [0.50, 1.72, 1.4],
                 "axis": [0, 1, 0]}),
        ("fix", {"a": "panel lintel", "b": "oak panel", "at_m": [0.70, 1.72, 1.4],
                 "axis": [0, 1, 0]}),
        _box("sword rest left", "oak", [0.08, 0.08, 0.08], [-0.24, 0.96, 1.9], True),
        _box("sword rest right", "oak", [0.08, 0.08, 0.08], [0.24, 0.96, 1.9], True),
        _box("sword", "aluminum", [0.64, 0.04, 0.04], [0.0, 1.02, 1.9]),
        ("blade", {"body": "sword", "heel_m": [0.2, 1.02, 1.88], "tip_m": [-0.3, 1.02, 1.88],
                   "facing": [0, 0, -1], "thickness_m": 0.04, "edge_radius_m": 0.00005,
                   "bevel_deg": 30, "grip_m": [0.28, 1.02, 1.9]}),
    ]),
    # The valley's own room, kept as it is: its ground and its river are the
    # generation call's, and what goes in them is these calls.
    #
    # A dam: nine concrete blocks side by side across the river at x 0.64,
    # where a survey finds it wet from z 1.5 to 4.5, and onto each bank. Each is
    # set on the bed or the bank under it. A block twelve cells wide has its
    # centre on the 0.04 m grid, so blocks 0.48 m apart touch and do not share
    # a cell: at 1.02 and 1.5 they did, and the room refused them. And 0.48 m
    # tall and 0.32 m through, 1,152 cells each: nine blocks 0.96 m tall are
    # 31,000 cells, twice what a room may hold and still run at realtime.
    "dam-river": ("dam-river", [
        _box(f"dam stone {k + 1}", "concrete", [0.32, 0.48, 0.48], [0.64, 0.5, round(1.04 + 0.48 * k, 2)])
        for k in range(9)], {"keep_room": True}),
    # A channel from the middle of the pond north to the low ground by the
    # river, 0.8 m wide and 0.7 m deep: below the pond's level all the way.
    "drain-pond": ("drain-pond", [
        ("dig", {"from_m": [4.77, -2.73], "to_m": [4.77, 2.27], "width_m": 0.8, "depth_m": 0.7}),
    ], {"keep_room": True}),
    # An oak log in the river where it runs at x -13, a little above the water.
    "log-river": ("log-river", [
        _box("oak log", "oak", [0.96, 0.24, 0.24], [-13.0, 0.92, 2.24]),
    ], {"keep_room": True}),
    # A concrete boulder on the sand of the bank, 1.5 m from the water.
    "boulder-dug": ("boulder-dug", [
        _box("boulder", "concrete", [0.48, 0.48, 0.48], [0.64, 1.04, 6.0]),
    ], {"keep_room": True}),
}


class RecipeRefused(RuntimeError):
    """A step of a recipe that the MCP would not take."""


def build_recipe(recipe_id: str, recipes: dict[str, Any] | None = None,
                 cases: list[Case] | None = None) -> tuple[world_room.Room, set[str], list[str]]:
    """Make a recipe through the MCP, in its case's room: the room as built, the
    names the room had before, and the warnings the tools gave on the way.

    A step is a tool call, or a function given the world's id, for a step that
    has to look before it acts: taking a bar off a gate needs the bar's joint
    id, which only the world knows. A recipe whose third element says
    `keep_room` starts from the room as it stands instead of clearing it.
    """
    import room_world
    entry = (recipes or RECIPES)[recipe_id]
    case_id, calls = entry[0], entry[1]
    keep_room = len(entry) > 2 and bool(entry[2].get("keep_room"))
    case = next(c for c in (cases or CASES) if c.id == case_id)
    room = world_room.Room(case.scene)
    before = {b["name"] for b in room.bodies()}
    world_id = room_world.open_room(room.spec)
    try:
        if not keep_room:
            room_world.call(world_id, "clear_world", {})
        warnings: list[str] = []
        for tool, args in calls:
            if callable(tool):
                answer = tool(world_id)
                tool = getattr(tool, "__name__", "a step")
            else:
                answer = room_world.call(world_id, tool, args)
            if "error" in answer:
                raise RecipeRefused(f"the recipe itself was refused at {tool}: {answer['error']}")
            warnings += answer.get("warnings", [])
        room.spec = room_world.export_spec(room_world.entry_of(world_id))
    finally:
        room_world.close_room(world_id)
    return room, before, warnings


def run_recipe(recipe_id: str, recipes: dict[str, Any] | None = None,
               cases: list[Case] | None = None, folder: Path | None = None) -> dict[str, Any]:
    """Build a recipe through the MCP, then give it the case's own check."""
    case_id = (recipes or RECIPES)[recipe_id][0]
    case = next(c for c in (cases or CASES) if c.id == case_id)
    record: dict[str, Any] = {"recipe": recipe_id, "case": case_id, "scene": case.scene,
                              "passed": False}
    try:
        room, before, warnings = build_recipe(recipe_id, recipes, cases)
    except RecipeRefused as refused:
        record["reason"] = str(refused)
        return record
    record["warnings"] = warnings
    if folder is not None:
        # Trial 0 is the recipe: the build the guide describes, kept so it can
        # be opened in the playground beside what the agent built.
        (folder / f"{recipe_id}-0.spec.json").write_text(json.dumps(room.spec), encoding="utf-8")
        record["spec"] = f"{recipe_id}-0.spec.json"
    began = time.perf_counter()
    world = World(room.spec)
    try:
        verdict = case.check(Built(room, world, before))
        record.update(passed=verdict.ok, reason=verdict.reason, measured=verdict.measured)
        record["rest"] = settle(world)
        record["realtime"] = timing(world, time.perf_counter() - began)
    except TooSlow as slow:
        record.update(passed=False, too_slow=True, reason=f"stopped: {slow}",
                      realtime=timing(world, time.perf_counter() - began))
    finally:
        world.close()
    return record


# ---------------------------------------------------------------------------
# Running a trial
# ---------------------------------------------------------------------------

def refusals(trace: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [{"tool": c["name"], "error": str(c["answer"].get("error"))[:400]}
            for r in trace for c in r.get("calls", [])
            if isinstance(c.get("answer"), dict) and "error" in c["answer"]]


def run_trial(case: Case, trial: int, api_key: str, model: str,
              folder: Path) -> dict[str, Any]:
    record: dict[str, Any] = {"case": case.id, "trial": trial, "scene": case.scene,
                              "message": case.message, "passed": False}
    room = world_room.Room(case.scene)
    before = {b["name"] for b in room.bodies()}
    trace: list[dict[str, Any]] = []
    asked = time.perf_counter()
    try:
        # The room as the server has it when the person asks: open and running.
        first = World(room.spec)
        try:
            first.seconds(0.25)
            live_state = first.session.state
            answer = world_chat.ask(api_key, model, room, live_state, case.message, [],
                                    trace=trace)
        finally:
            first.close()
    except Exception as failure:
        record.update(reason=f"the agent failed: {failure}", trace=trace,
                      refusals=refusals(trace), ask_s=round(time.perf_counter() - asked, 1))
        return record
    record.update(reply=answer.get("reply"), did=answer.get("did"),
                  rounds=answer.get("rounds"), usage=answer.get("usage"),
                  ask_s=round(time.perf_counter() - asked, 1), refusals=refusals(trace),
                  calls=[c["name"] for r in trace for c in r.get("calls", [])])
    (folder / f"{case.id}-{trial}.json").write_text(
        json.dumps({"case": case.id, "trial": trial, "message": case.message,
                    "answer": answer, "trace": trace}, indent=1, default=str),
        encoding="utf-8")
    if answer.get("changed"):
        # The room as the agent left it, so it can be opened again -- in the
        # playground, by anyone, to see and use what was built.
        (folder / f"{case.id}-{trial}.spec.json").write_text(json.dumps(room.spec),
                                                             encoding="utf-8")
        record["spec"] = f"{case.id}-{trial}.spec.json"
    if not answer.get("changed"):
        reply = str(answer.get("reply") or "")
        if case.accept_no_change is not None and case.accept_no_change(reply):
            record.update(passed=True,
                          reason="changed nothing, and said why: " + reply[:200])
        else:
            record["reason"] = "the agent changed nothing in the room"
        return record
    return judge(case, room, before, str(answer.get("reply") or ""), record)


def judge(case: Case, room: world_room.Room, before: set[str], reply: str,
          record: dict[str, Any]) -> dict[str, Any]:
    """Open the room the agent left in the real engine and USE it: the case's
    check, then the room let come to rest, all of it held to the realtime rule.
    Also how a finished run's rooms are judged again when a check is corrected
    (tests/qa.py --recheck): the build is the agent's, unchanged."""
    checked = time.perf_counter()
    try:
        world = World(room.spec)
    except Exception as failure:
        record["reason"] = f"the room the agent left would not open: {failure}"
        return record
    try:
        problems = world.opened.get("joint_problems")
        if problems:
            record["reason"] = f"joints that would not hang: {problems}"
            return record
        verdict = case.check(Built(room, world, before, reply))
        record.update(passed=verdict.ok, reason=verdict.reason, measured=verdict.measured)
        record["rest"] = settle(world)
        record["realtime"] = timing(world, time.perf_counter() - checked)
    except TooSlow as slow:
        record.update(passed=False, too_slow=True, reason=f"stopped: {slow}",
                      realtime=timing(world, time.perf_counter() - checked))
    except Exception:
        record["reason"] = "the check itself failed: " + traceback.format_exc()[-800:]
    finally:
        world.close()
        record["check_s"] = round(time.perf_counter() - checked, 1)
    return record


def summarise(records: list[dict[str, Any]], model: str,
              cases: list[Case] | None = None) -> str:
    lines = [f"agent build regression -- {model}", ""]
    by_case: dict[str, list[dict[str, Any]]] = {}
    for r in records:
        by_case.setdefault(r["case"], []).append(r)
    tokens_in = sum((r.get("usage") or {}).get("input_tokens", 0) for r in records)
    tokens_out = sum((r.get("usage") or {}).get("output_tokens", 0) for r in records)
    for case in (cases or CASES):
        rows = by_case.get(case.id)
        if not rows:
            continue
        passed = sum(1 for r in rows if r["passed"])
        lines.append(f"{case.id:24s} {passed}/{len(rows)}   {case.tests}")
        for r in rows:
            mark = "pass" if r["passed"] else "FAIL"
            lines.append(f"    trial {r['trial']}: {mark} -- {r.get('reason')}")
            if not r["passed"]:
                for refusal in (r.get("refusals") or [])[:4]:
                    lines.append(f"        refused {refusal['tool']}: "
                                 f"{refusal['error'][:200]}")
                if r.get("reply"):
                    lines.append(f"        said: {str(r['reply'])[:300]}")
            lines.append(f"        {r.get('rounds')} rounds, "
                         f"{len(r.get('calls') or [])} calls, {r.get('ask_s')} s asking, "
                         f"{r.get('check_s', '-')} s checking")
            rest, clock = r.get("rest") or {}, r.get("realtime") or {}
            if rest or clock:
                lines.append(
                    "        " + ("at rest" if rest.get("at_rest") else
                                  f"STILL MOVING {rest.get('still_moving')}")
                    + (f" after {rest['waited_s']:.0f} s" if rest.get("waited_s") else "")
                    + (f"; SUNK {', '.join(rest['sunk'])}" if rest.get("sunk") else "")
                    + (f"; FLEW OFF {', '.join(rest['flew_off'])}" if rest.get("flew_off") else "")
                    + f"; {clock.get('check_s')} s to show {clock.get('simulated_s')} s"
                    + ("" if clock.get("within_rule", True) else " -- SLOWER THAN THE REALTIME RULE"))
        lines.append("")
    total = sum(1 for r in records if r["passed"])
    lines.append(f"{total} of {len(records)} passed; {tokens_in} tokens in, "
                 f"{tokens_out} out")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--cases", default="", help="comma-separated parts of case ids")
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument("--jobs", type=int, default=3)
    parser.add_argument("--model", default=None, help="instead of OPENAI_MODEL")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--recipes", action="store_true",
                        help="build the guide's recipes through the MCP and check them "
                             "-- no model, no key, no cost")
    args = parser.parse_args(argv)

    wanted = [w.strip() for w in args.cases.split(",") if w.strip()]
    cases = [c for c in CASES if not wanted or any(w in c.id for w in wanted)]
    if args.list:
        for c in cases:
            print(f"{c.id:24s} [{c.scene}] {c.message}")
        return 0
    if ENGINE is None:
        print("no live engine: build banjo_live_world_run into build/integration first")
        return 2
    if args.recipes:
        failed = 0
        for recipe_id in RECIPES:
            if wanted and not any(w in recipe_id for w in wanted):
                continue
            record = run_recipe(recipe_id)
            failed += 0 if record["passed"] else 1
            print(f"{'pass' if record['passed'] else 'FAIL'}  {recipe_id}: "
                  f"{record.get('reason')}")
            for warning in record.get("warnings") or []:
                print(f"      warned: {warning[:160]}")
            if not record["passed"]:
                print(f"      measured: {json.dumps(record.get('measured'))[:600]}")
        return 1 if failed else 0
    import server   # the playground's own .env reader, so the same key and model
    api_key, model = server.local_configuration()
    model = args.model or model
    if not api_key:
        print("OPENAI_API_KEY is not configured in the local .env; these tests ask a "
              "real model and cannot run without one")
        return 2

    stamp = time.strftime("%Y%m%d-%H%M%S")
    folder = ROOT / "build" / "agent-regression" / stamp
    folder.mkdir(parents=True, exist_ok=True)
    print(f"{len(cases)} case(s) x {args.trials} trial(s) against {model}; "
          f"writing {folder}", flush=True)
    speaking = threading.Lock()
    records: list[dict[str, Any]] = []
    jobs = [(c, t) for c in cases for t in range(1, args.trials + 1)]
    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        futures = {pool.submit(run_trial, c, t, api_key, model, folder): (c, t)
                   for c, t in jobs}
        for future in as_completed(futures):
            case, trial = futures[future]
            try:
                record = future.result()
            except Exception:
                record = {"case": case.id, "trial": trial, "passed": False,
                          "reason": traceback.format_exc()[-800:]}
            records.append(record)
            with speaking:
                print(f"  {'pass' if record['passed'] else 'FAIL'}  {case.id} #{trial}: "
                      f"{record.get('reason')}", flush=True)
    records.sort(key=lambda r: ([c.id for c in CASES].index(r["case"]), r["trial"]))
    summary = summarise(records, model)
    (folder / "summary.txt").write_text(summary, encoding="utf-8")
    (folder / "report.json").write_text(json.dumps(records, indent=1, default=str),
                                        encoding="utf-8")
    print()
    print(summary)
    return 0 if all(r["passed"] for r in records) else 1


if __name__ == "__main__":
    sys.exit(main())
