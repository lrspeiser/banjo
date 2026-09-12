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

    def step(self, count: int = 1, hand: list[float] | None = None) -> None:
        """Advance, ANSWERING the break handshake.

        A step that would break something is taken back and the clock does not
        move until the host says what to do. A stepper that never answers stops
        the world at the first hard contact -- and a mechanism that is not moving
        looks exactly like one that cannot.
        """
        done = 0
        while done < count:
            n = 1 if hand is not None else min(8, count - done)
            extra = {"hand": [float(v) for v in hand]} if hand is not None else {}
            began = time.perf_counter()
            state = self.session.send(op="step", dt=DT, n=n, moved=True, **extra)
            self.impacts.extend(state.get("impacts") or [])
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
    return {"at_rest": not moving, "waited_s": waited,
            "still_moving": [[n, round(v, 3)] for v, n in moving[:3]],
            "sunk": [b["name"] for b in bodies if b["position_m"][1] < -0.25],
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
}


def run_recipe(recipe_id: str, recipes: dict[str, Any] | None = None,
               cases: list[Case] | None = None, folder: Path | None = None) -> dict[str, Any]:
    """Build a recipe through the MCP, then give it the case's own check.

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
    record: dict[str, Any] = {"recipe": recipe_id, "case": case_id, "scene": case.scene,
                              "passed": False}
    room = world_room.Room(case.scene)
    before = {b["name"] for b in room.bodies()}
    world_id = room_world.open_room(room.spec)
    try:
        if not keep_room:
            room_world.call(world_id, "clear_world", {})
        warnings = []
        for tool, args in calls:
            if callable(tool):
                answer = tool(world_id)
                tool = getattr(tool, "__name__", "a step")
            else:
                answer = room_world.call(world_id, tool, args)
            if "error" in answer:
                record["reason"] = f"the recipe itself was refused at {tool}: {answer['error']}"
                return record
            warnings += answer.get("warnings", [])
        record["warnings"] = warnings
        room.spec = room_world.export_spec(room_world.entry_of(world_id))
    finally:
        room_world.close_room(world_id)
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
        verdict = case.check(Built(room, world, before, str(answer.get("reply") or "")))
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
