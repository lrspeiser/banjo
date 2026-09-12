"""Every other kind of thing the engine can do, asked for in words.

agent_build_tests.py holds the builds the owner asked about first -- gates,
wheels, a hearth -- and the machinery: a case is a sentence a person might type,
the room the chat leaves is opened in the real engine, and the thing asked for
is USED and measured. This adds a case for each remaining capability, so that
the suite as a whole touches every kind of joint, every way of breaking, heat,
and the plain mechanics of falling, sliding, bouncing and swinging.

Where physics fixes the answer in advance, the check asks for that answer: a
pendulum's period from its length, where a thrown ball must be at each moment,
that a spring holds up exactly what hangs on it, that a hoist lifts by its
rope's ratio, that an arrow never leaves with more energy than the limbs held.
A check that only asked "did something happen" would pass a room that did the
wrong thing.

Every case has a recipe -- the same thing built through the MCP by hand -- so a
failure lands in the right place. A recipe that fails is the engine or the
check, and no model will fix it; a recipe that passes while the chat fails is
the chat, or what its guide teaches.

Run through tests/qa.py.
"""
from __future__ import annotations

import math
import re
from typing import Any

import agent_build_tests as abt
from agent_build_tests import (DT, GATE_WORDS, HINGE_OPEN_DEG, Built, Case, Verdict, _box, add,
                               bottom, coordinate, cross, dot, haul, joints_in_words, moving_end,
                               norm, scale, sub, unit, volume, worded)

import room_world  # noqa: E402  (agent_build_tests put playground/ on the path)
import world_room  # noqa: E402

G = 9.81

# kg/m^3, as src/material/MaterialCatalog.cpp declares them. Used to tell which
# end of something is the heavy one and what a body weighs; never on its own to
# decide whether a check passes.
DENSITY = {"iron": 7870.0, "aluminum": 2700.0, "glass": 2500.0, "ceramic": 3900.0,
           "oak": 700.0, "rubber": 1100.0, "ice": 917.0, "concrete": 2400.0}
ALIASES = {"alumina ceramic": "ceramic", "aluminium": "aluminum"}

LOAD_WORDS = ("weight", "load", "block", "stone", "crate", "bucket", "basket", "sack",
              "barrel", "bale")


# ---------------------------------------------------------------------------
# What things are, whichever way they are described
# ---------------------------------------------------------------------------

def material(body: dict[str, Any] | None) -> str:
    name = str((body or {}).get("material") or "")
    return ALIASES.get(name, name)


def size_m(body: dict[str, Any]) -> list[float]:
    """A live body says dimensions_m; an authored one says size_mm."""
    if body.get("dimensions_m"):
        return list(body["dimensions_m"])
    return [v / 1000.0 for v in body.get("size_mm") or [0.0, 0.0, 0.0]]


def mass(body: dict[str, Any] | None) -> float:
    if not body:
        return 0.0
    d = size_m(body)
    v = math.pi / 6.0 * d[0] ** 3 if body.get("shape") == "sphere" else d[0] * d[1] * d[2]
    return DENSITY.get(material(body), 1000.0) * v


def velocity(body: dict[str, Any]) -> list[float]:
    """How fast an authored body was set going."""
    if body.get("velocity_m_s"):
        return list(body["velocity_m_s"])
    if body.get("velocity_mm_s"):
        return [v / 1000.0 for v in body["velocity_mm_s"]]
    return [0.0, 0.0, 0.0]


def turn_by(q: list[float], v: list[float]) -> list[float]:
    """v turned by the unit quaternion q = (w, x, y, z)."""
    w, x, y, z = q
    t = [2.0 * (y * v[2] - z * v[1]), 2.0 * (z * v[0] - x * v[2]), 2.0 * (x * v[1] - y * v[0])]
    return [v[0] + w * t[0] + (y * t[2] - z * t[1]),
            v[1] + w * t[1] + (z * t[0] - x * t[2]),
            v[2] + w * t[2] + (x * t[1] - y * t[0])]


def tilt_deg(body: dict[str, Any]) -> float:
    """How far a body has tipped from upright."""
    w, x, y, z = body.get("orientation_wxyz") or [1.0, 0.0, 0.0, 0.0]
    up = 1.0 - 2.0 * (x * x + z * z)
    return math.degrees(math.acos(max(-1.0, min(1.0, up))))


def attached(world: abt.World) -> list[dict[str, Any]]:
    return [j for j in world.joints() if j.get("attached")]


def hit_speed(world: abt.World, names: list[str]) -> float:
    return max((i.get("closing_speed_m_s", 0.0) for i in world.impacts
                if any(str(x or "").startswith(tuple(names)) for x in (i.get("struck"), i.get("by")))),
               default=0.0)


def pieces_of(world: abt.World, name: str) -> list[str]:
    return [n for n in world.bodies() if n.startswith(name + " piece")]


# ---------------------------------------------------------------------------
# Gates: a leaf on a pin, shoved; and what holds it shut
# ---------------------------------------------------------------------------

def leaf_on_pin(world: abt.World) -> tuple[dict[str, Any] | None, str | None, list[dict[str, Any]]]:
    anchored = world.anchored()
    joints = attached(world)
    leaves = [(j, moving_end(j, anchored)) for j in joints if j["kind"] == "hinge"]
    leaves = [(j, m) for j, m in leaves if m]
    if not leaves:
        return None, None, joints
    leaves.sort(key=lambda jm: (not worded(jm[1], GATE_WORDS), -volume(world.body(jm[1]))))
    return leaves[0][0], leaves[0][1], joints


def shove(world: abt.World, leaf: str, pin_id: int) -> float:
    """Push the leaf both ways across its thin side; the most it turned."""
    start = coordinate(world.joint(pin_id))
    best = 0.0
    for sign in (1.0, -1.0):
        body = world.body(leaf)
        if body is None:
            break
        size = body.get("dimensions_m") or [1.0, 1.0, 1.0]
        thin = [1.0, 0.0, 0.0] if size[0] <= size[2] else [0.0, 0.0, 1.0]
        haul(world, leaf, scale(thin, 0.6 * sign))
        world.session.send(op="release")
        world.seconds(0.3)
        best = max(best, abs(coordinate(world.joint(pin_id)) - start))
        if best >= HINGE_OPEN_DEG:
            break
    return best


def holding_shut(world: abt.World, leaf: str, pin: dict[str, Any],
                 joints: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every fixing, bolt or rope that ties the leaf -- or anything fixed to
    it -- to fixed scenery. Not hinges: a gate on two pins is still a gate."""
    anchored = world.anchored()
    reach, frontier, found = {leaf}, [leaf], []
    while frontier:
        here = frontier.pop()
        for j in joints:
            if j["id"] == pin["id"] or j["kind"] == "hinge" or here not in (j["a"], j["b"]):
                continue
            if j["kind"] not in ("fixing", "slider", "link"):
                continue
            there = j["b"] if j["a"] == here else j["a"]
            if anchored.get(there):
                if all(j["id"] != f["id"] for f in found):
                    found.append(j)
            elif there not in reach:
                reach.add(there)
                frontier.append(there)
    return found


def said(joint: dict[str, Any]) -> str:
    return f"{joint['kind']} {joint['a']} -> {joint['b']}"


def check_latched_gate(built: Built) -> Verdict:
    world = built.world
    world.seconds(1.0)
    pin, leaf, joints = leaf_on_pin(world)
    if pin is None:
        return Verdict(False, "nothing is on a hinge to anything anchored",
                       {"joints": joints_in_words(joints)})
    held = shove(world, leaf, pin["id"])
    latches = holding_shut(world, leaf, pin, attached(world))
    measured = {"leaf": leaf, "turned_barred_deg": round(held, 1),
                "latches": [said(j) for j in latches]}
    if held >= 5.0:
        return Verdict(False, f"barred, {leaf} still swung {held:.0f} degrees when shoved: the "
                              f"bar does not hold it", measured)
    if not latches:
        return Verdict(False, f"{leaf} does not move, but nothing holding it can be let go: no "
                              f"fixing, bolt or rope ties it to anything fixed", measured)
    # Letting the latch go, the way the room does it: unhinge, by the joint.
    for j in latches:
        world.session.send(op="unhinge", joint=j["id"])
    world.seconds(0.5)
    opened = shove(world, leaf, pin["id"])
    measured["turned_unbarred_deg"] = round(opened, 1)
    if opened < HINGE_OPEN_DEG:
        return Verdict(False, f"with {len(latches)} latch(es) let go, {leaf} still turned only "
                              f"{opened:.1f} degrees", measured)
    return Verdict(True, f"barred, {leaf} held against a shove ({held:.1f} degrees); with the "
                         f"bar let go it swung {opened:.0f} degrees", measured)


def check_unbarred_gate(built: Built) -> Verdict:
    world = built.world
    world.seconds(0.5)
    pin, leaf, joints = leaf_on_pin(world)
    if pin is None:
        return Verdict(False, "the gate is not on its hinge any more",
                       {"joints": joints_in_words(joints)})
    latches = holding_shut(world, leaf, pin, joints)
    opened = shove(world, leaf, pin["id"])
    measured = {"gate": leaf, "still_holding": [said(j) for j in latches],
                "turned_deg": round(opened, 1)}
    if opened < HINGE_OPEN_DEG:
        why = f"shoved, {leaf} turned only {opened:.1f} degrees"
        if latches:
            why += f"; still holding it: {', '.join(measured['still_holding'])}"
        return Verdict(False, why, measured)
    return Verdict(True, f"{leaf} swung {opened:.0f} degrees with the bar off", measured)


# ---------------------------------------------------------------------------
# Ropes over pulleys
# ---------------------------------------------------------------------------

def check_hoist(built: Built) -> Verdict:
    """Pull one end down and the other comes up -- by the rope's own ratio."""
    world = built.world
    world.seconds(1.0)
    joints = attached(world)

    def free(name: str) -> bool:
        body = world.body(name)
        return body is not None and not body.get("anchored")

    rove = [j for j in joints if j["kind"] == "pulley" and free(j["a"]) and free(j["b"])]
    if not rove:
        return Verdict(False, "no rope is rove over pulleys between two things that can move",
                       {"joints": joints_in_words(joints)})
    rope = rove[0]
    # The load is the heavier end; the other is what a hand pulls.
    load, handle = sorted((rope["a"], rope["b"]), key=lambda n: -mass(world.body(n)))
    ratio = float(rope.get("ratio") or 1.0)
    load_y, handle_y = world.body(load)["position_m"][1], world.body(handle)["position_m"][1]
    haul(world, handle, [0.0, -0.6, 0.0], seconds=2.0)
    pulled = handle_y - world.body(handle)["position_m"][1]
    rose = world.body(load)["position_m"][1] - load_y
    # The constraint holds a + ratio*b. Pulling a down by d lifts b by d/ratio;
    # pulling b down lifts a by ratio*d.
    expected = pulled / ratio if handle == rope["a"] else pulled * ratio
    world.session.send(op="release")
    world.seconds(1.0)
    kg = mass(world.body(load))
    measured = {"load": load, "handle": handle, "ratio": ratio, "load_kg": round(kg, 1),
                "handle_pulled_m": round(pulled, 3), "load_rose_m": round(rose, 3),
                "rope_predicts_m": round(expected, 3)}
    if rose < 0.1:
        why = f"pulling {handle} down {pulled:.2f} m lifted {load} only {rose:.2f} m"
        if pulled < 0.1:
            why += (f"; a hand's 800 N could not pull {handle} down against {load}'s "
                    f"{kg * G:.0f} N")
        return Verdict(False, why, measured)
    if abs(rose - expected) > 0.25 * expected + 0.02:
        return Verdict(False, f"{load} rose {rose:.2f} m for {pulled:.2f} m of pull, and a rope "
                              f"with ratio {ratio:g} makes that {expected:.2f} m", measured)
    return Verdict(True, f"pulling {handle} down {pulled:.2f} m lifted {load} {rose:.2f} m "
                         f"(the rope's ratio {ratio:g} says {expected:.2f})", measured)


def check_counterweight(built: Built) -> Verdict:
    """Balanced by mass: raised or lowered and let go, it stays."""
    world = built.world
    world.seconds(1.0)
    anchored = world.anchored()
    joints = attached(world)
    slides = [(j, moving_end(j, anchored)) for j in joints if j["kind"] == "slider"]
    rove = [j for j in joints if j["kind"] == "pulley"]
    pairs = [(s, m, r) for s, m in slides if m for r in rove if m in (r["a"], r["b"])]
    if not pairs:
        return Verdict(False, "nothing that slides hangs on a rope over pulleys",
                       {"joints": joints_in_words(joints)})
    pin, grate, rope = pairs[0]
    other = rope["b"] if rope["a"] == grate else rope["a"]
    axis = unit(pin["axis"])
    up = axis if axis[1] >= 0 else scale(axis, -1.0)
    start = coordinate(world.joint(pin["id"]))
    moves, drifts = [], []
    for lift in (0.4, -0.25):
        before = coordinate(world.joint(pin["id"]))
        haul(world, grate, scale(up, lift), seconds=2.0)
        world.session.send(op="release")
        left_at = coordinate(world.joint(pin["id"]))
        world.seconds(2.0)
        moves.append(abs(left_at - before))
        drifts.append(abs(coordinate(world.joint(pin["id"])) - left_at))
    ratio = float(rope.get("ratio") or 1.0)
    measured = {"grate": grate, "counterweight": other, "ratio": ratio,
                "grate_kg": round(mass(world.body(grate)), 1),
                "counterweight_kg": round(mass(world.body(other)), 1),
                "moved_m": [round(m, 3) for m in moves], "drift_m": [round(d, 3) for d in drifts],
                "started_at_m": round(start, 3)}
    if max(moves) < 0.15:
        return Verdict(False, f"hauled, {grate} moved only {max(moves):.2f} m", measured)
    if max(drifts) > 0.08:
        return Verdict(False, f"let go, {grate} drifted {max(drifts):.2f} m in 2 s: "
                              f"{measured['grate_kg']:.0f} kg against "
                              f"{measured['counterweight_kg']:.0f} kg on a ratio of {ratio:g} is "
                              f"not a balance", measured)
    return Verdict(True, f"{grate} stayed where it was left, raised and lowered (it drifted at "
                         f"most {max(drifts) * 1000:.0f} mm in 2 s), balanced by {other}",
                   measured)


# ---------------------------------------------------------------------------
# Springs and pins that carry weight
# ---------------------------------------------------------------------------

def check_spring_weight(built: Built) -> Verdict:
    """What hangs on a spring is held up by the spring: its pull, averaged
    over the bounce, is the weight."""
    world = built.world
    world.seconds(1.0)
    anchored = world.anchored()
    joints = attached(world)
    springs = [(j, moving_end(j, anchored)) for j in joints if j["kind"] == "elastic"]
    springs = [(j, m) for j, m in springs if m]
    if not springs:
        return Verdict(False, "no spring hangs anything from something fixed",
                       {"joints": joints_in_words(joints)})
    pin, weight = springs[0]
    kg = mass(world.body(weight))
    forces, lows = [], []
    for _ in range(48):
        world.seconds(1.0 / 12.0)
        joint = world.joint(pin["id"])
        forces.append(abs(float((joint or {}).get("force_n") or 0.0)))
        lows.append(bottom(world.body(weight)))
    pull = sum(forces) / len(forces)
    measured = {"weight": weight, "kg": round(kg, 2), "weighs_n": round(kg * G, 1),
                "spring_pulls_n": round(pull, 1), "pull_range_n": round(max(forces) - min(forces), 1),
                "stiffness_n_m": pin.get("stiffness_n_m"), "damping_n_s_m": pin.get("damping_n_s_m"),
                "lowest_m": round(min(lows), 3)}
    if min(lows) < 0.01:
        return Verdict(False, f"{weight} is down on the floor", measured)
    if abs(pull - kg * G) > 0.1 * kg * G:
        return Verdict(False, f"the spring pulls {pull:.0f} N on average and {weight} weighs "
                              f"{kg * G:.0f} N: something else is carrying it", measured)
    return Verdict(True, f"{weight} ({kg * G:.0f} N) hangs on the spring, which pulls {pull:.0f} N "
                         f"on average", measured)


def check_seesaw(built: Built) -> Verdict:
    """The side with the larger turning moment goes down."""
    world = built.world
    anchored = world.anchored()
    joints = attached(world)
    pins = [(j, moving_end(j, anchored)) for j in joints if j["kind"] == "hinge"]
    pins = [(j, m) for j, m in pins if m and abs(unit(j["axis"])[1]) < 0.3]
    if not pins:
        return Verdict(False, "nothing turns on a level pivot", {"joints": joints_in_words(joints)})
    pins.sort(key=lambda jm: -volume(world.body(jm[1])))
    pin, plank = pins[0]
    body = world.body(plank)
    size = body["dimensions_m"]
    top = body["position_m"][1] + size[1] / 2.0
    axis = unit(pin["axis"])
    across = unit(cross(axis, [0.0, 1.0, 0.0]))
    riders = [b for b in world.bodies().values()
              if not b.get("anchored") and b["name"] != plank
              and abs(bottom(b) - top) < 0.05
              and abs(b["position_m"][0] - body["position_m"][0]) <= size[0] / 2.0
              and abs(b["position_m"][2] - body["position_m"][2]) <= size[2] / 2.0]
    if not riders:
        return Verdict(False, f"nothing rests on {plank}", {"plank": plank})
    moment = sum(mass(b) * dot(sub(b["position_m"], pin["at"]), across) for b in riders + [body])
    heavy = 1.0 if moment > 0 else -1.0
    reach = abs(dot([size[0] / 2.0, 0.0, size[2] / 2.0], [abs(across[0]), 0.0, abs(across[2])]))
    end = scale(across, heavy * reach)
    start_y = body["position_m"][1] + end[1]
    world.seconds(3.0)
    now = world.body(plank)
    end_y = now["position_m"][1] + turn_by(now.get("orientation_wxyz") or [1, 0, 0, 0], end)[1]
    dropped = start_y - end_y
    heavy_side = [b["name"] for b in riders if dot(sub(b["position_m"], pin["at"]), across) * heavy > 0]
    measured = {"plank": plank, "heavy_side": heavy_side,
                "moment_n_m": round(abs(moment) * G, 1), "heavy_end_dropped_m": round(dropped, 3)}
    if dropped < 0.03:
        return Verdict(False, f"{plank} did not tip towards {', '.join(heavy_side)}: its end moved "
                              f"{dropped * 1000:.0f} mm", measured)
    return Verdict(True, f"{plank} tipped towards {', '.join(heavy_side)}, its end going down "
                         f"{dropped:.2f} m", measured)


# ---------------------------------------------------------------------------
# Resting, knocking over, bouncing, sliding, flying, swinging
# ---------------------------------------------------------------------------

def check_tower(built: Built) -> Verdict:
    """A stack of five that stands still."""
    world = built.world
    world.seconds(0.5)
    everything = list(world.bodies().values())
    free = [b for b in everything if not b.get("anchored")]

    def rests_on(upper: dict[str, Any], lower: dict[str, Any]) -> bool:
        lower_top = lower["position_m"][1] + lower["dimensions_m"][1] / 2.0
        return (abs(bottom(upper) - lower_top) < 0.03
                and abs(upper["position_m"][0] - lower["position_m"][0])
                < (upper["dimensions_m"][0] + lower["dimensions_m"][0]) / 2.0
                and abs(upper["position_m"][2] - lower["position_m"][2])
                < (upper["dimensions_m"][2] + lower["dimensions_m"][2]) / 2.0)

    grounded = [b for b in free
                if bottom(b) < 0.03 or any(rests_on(b, a) for a in everything if a.get("anchored"))]
    best: list[dict[str, Any]] = []

    def climb(path: list[dict[str, Any]]) -> None:
        nonlocal best
        if len(path) > len(best):
            best = path
        names = {p["name"] for p in path}
        for b in free:
            if b["name"] not in names and rests_on(b, path[-1]):
                climb(path + [b])

    for g in grounded:
        climb([g])
    measured = {"tallest_stack": [b["name"] for b in best]}
    if len(best) < 5:
        return Verdict(False, f"the tallest stack is {len(best)} high", measured)
    start = {b["name"]: b["position_m"] for b in best}
    world.seconds(4.0)
    missing = [n for n in start if world.body(n) is None]
    if missing:
        return Verdict(False, f"part of the tower broke: {', '.join(missing)}", measured)
    moved = max(norm(sub(world.body(n)["position_m"], p)) for n, p in start.items())
    top = max(world.body(n)["position_m"][1] + world.body(n)["dimensions_m"][1] / 2.0 for n in start)
    measured.update(height_m=round(top, 3), moved_mm=round(moved * 1000.0, 1))
    if moved > 0.01:
        return Verdict(False, f"the tower did not stand still: it moved {moved * 1000:.0f} mm in 4 s",
                       measured)
    return Verdict(True, f"{len(best)} blocks stand {top:.2f} m tall and moved at most "
                         f"{moved * 1000:.1f} mm in 4 s", measured)


def check_dominoes(built: Built) -> Verdict:
    world = built.world
    standing = [b for b in world.bodies().values() if not b.get("anchored")
                and b["dimensions_m"][1] >= 2.0 * min(b["dimensions_m"][0], b["dimensions_m"][2])
                and bottom(b) < 0.05]
    names = [b["name"] for b in standing]
    if len(names) < 6:
        return Verdict(False, f"only {len(names)} tall, thin things stand on the floor",
                       {"standing": names})
    world.seconds(8.0)
    fell = [n for n in names if world.body(n) is None or tilt_deg(world.body(n)) > 45.0]
    still = [n for n in names if n not in fell]
    measured = {"dominoes": len(names), "fell": len(fell), "still_standing": still}
    if len(still) > 1:
        return Verdict(False, f"{len(fell)} of {len(names)} fell; still standing: "
                              f"{', '.join(still[:4])}", measured)
    return Verdict(True, f"{len(fell)} of {len(names)} dominoes fell", measured)


def check_bounce(built: Built) -> Verdict:
    """Rubber gives back about a third of the height it fell."""
    world = built.world
    balls = [b for b in world.bodies().values() if material(b) == "rubber" and not b.get("anchored")]
    if not balls:
        return Verdict(False, "nothing made of rubber is in the room", {})
    ball = max(balls, key=lambda b: b["position_m"][1])
    name = ball["name"]
    fall = bottom(ball)
    if fall < 0.3:
        return Verdict(False, f"{name} starts {fall:.2f} m up: nothing is dropped",
                       {"ball": name, "starts_m": round(fall, 3)})
    heights = []
    for _ in range(int(4.0 / (4 * DT))):
        world.step(4)
        body = world.body(name)
        if body is None:
            return Verdict(False, f"{name} broke", {"ball": name})
        heights.append(bottom(body))
    landing = next((i for i in range(1, len(heights) - 1)
                    if heights[i] < 0.05 and heights[i] <= heights[i - 1]
                    and heights[i] < heights[i + 1]), None)
    measured = {"ball": name, "dropped_from_m": round(fall, 3)}
    if landing is None:
        return Verdict(False, f"{name} landed and did not come back up", measured)
    back = max(heights[landing:landing + int(1.5 / (4 * DT))])
    share = back / fall
    measured.update(bounced_to_m=round(back, 3), gave_back=round(share, 3))
    if not 0.15 <= share <= 0.6:
        return Verdict(False, f"dropped from {fall:.2f} m, {name} came back to {back:.2f} m "
                              f"({share:.0%}); rubber is said to give back about a third",
                       measured)
    return Verdict(True, f"dropped from {fall:.2f} m, {name} bounced back to {back:.2f} m "
                         f"({share:.0%}); rubber is said to give back about a third", measured)


def check_sliding(built: Built) -> Verdict:
    world = built.world
    sent = [b for b in built.room.bodies() if not b.get("anchored") and norm(velocity(b)) > 0.5]
    ice = [b for b in sent if material(b) == "ice"]
    oak = [b for b in sent if material(b) == "oak"]
    if not ice or not oak:
        return Verdict(False, "it needs an ice block and an oak block, both sent sliding",
                       {"sent": [b["name"] for b in sent]})
    i, o = ice[0]["name"], oak[0]["name"]
    vi, vo = norm(velocity(ice[0])), norm(velocity(oak[0]))
    measured = {"ice": i, "oak": o, "ice_m_s": round(vi, 2), "oak_m_s": round(vo, 2)}
    if abs(vi - vo) > 0.2 * max(vi, vo):
        return Verdict(False, f"they did not start at the same speed: the ice at {vi:.1f} m/s, the "
                              f"oak at {vo:.1f}", measured)
    start = {n: world.body(n)["position_m"] for n in (i, o)}
    world.seconds(5.0)

    def slid(n: str) -> float:
        p = world.body(n)["position_m"]
        return math.hypot(p[0] - start[n][0], p[2] - start[n][2])

    di, do = slid(i), slid(o)
    measured.update(ice_slid_m=round(di, 3), oak_slid_m=round(do, 3))
    if di < 1.5 * do:
        return Verdict(False, f"from {vi:.1f} m/s the ice slid {di:.2f} m and the oak {do:.2f} m: "
                              f"ice, far more slippery, should go much further", measured)
    return Verdict(True, f"from {vi:.1f} m/s the ice slid {di:.2f} m and the oak {do:.2f} m",
                   measured)


def check_projectile(built: Built) -> Verdict:
    """In flight it must be where gravity puts it, moment by moment."""
    world = built.world
    thrown = [b for b in built.room.bodies() if not b.get("anchored") and norm(velocity(b)) > 1.0]
    if not thrown:
        return Verdict(False, "nothing is thrown: nothing starts out moving", {})
    first = max(thrown, key=lambda b: norm(velocity(b)))
    name, v = first["name"], velocity(first)
    body = world.body(name)
    start, half = body["position_m"], body["dimensions_m"][1] / 2.0
    drop = start[1] - half
    if drop < 0.2:
        return Verdict(False, f"{name} starts on the floor: rolling is not flying", {"ball": name})
    t_land = (v[1] + math.sqrt(v[1] ** 2 + 2.0 * G * drop)) / G
    worst, samples = 0.0, 0
    while world.simulated_s < t_land - 2.0 * 8 * DT:
        world.step(8)
        now = world.body(name)
        if now is None:
            break
        t = world.simulated_s
        want = [start[0] + v[0] * t, start[1] + v[1] * t - 0.5 * G * t * t, start[2] + v[2] * t]
        worst = max(worst, norm(sub(now["position_m"], want)))
        samples += 1
    world.seconds(1.0)
    landed = [start[0] + v[0] * t_land, start[2] + v[2] * t_land]
    measured = {"ball": name, "thrown_m_s": [round(x, 2) for x in v], "from_m": round(drop, 3),
                "flight_s": round(t_land, 3), "samples": samples,
                "worst_off_parabola_mm": round(worst * 1000.0, 1),
                "lands_at_m": [round(x, 2) for x in landed]}
    if samples < 4:
        return Verdict(False, f"{name} was in the air for only {t_land:.2f} s", measured)
    if worst > 0.02:
        return Verdict(False, f"in flight {name} strayed {worst * 1000:.0f} mm from where gravity "
                              f"puts it", measured)
    return Verdict(True, f"{name} flew {t_land:.2f} s within {worst * 1000:.1f} mm of the "
                         f"parabola, landing about {math.hypot(v[0], v[2]) * t_land:.2f} m out",
                   measured)


def check_pendulum(built: Built) -> Verdict:
    """The period of a swinging weight is fixed by its length: 2 pi root(L/g),
    with the corrections for a finite bob and a finite swing."""
    world = built.world
    anchored = world.anchored()
    joints = attached(world)
    ropes = [(j, moving_end(j, anchored)) for j in joints if j["kind"] == "link"]
    ropes = [(j, m) for j, m in ropes if m]
    if not ropes:
        return Verdict(False, "nothing hangs on a rope from anything fixed",
                       {"joints": joints_in_words(joints)})
    rope, bob = ropes[0]
    record = next((j for j in built.room.spec.get("joints", [])
                   if j.get("kind") == "link" and {j.get("a"), j.get("b")} == {rope["a"], rope["b"]}),
                  None)
    if record is None:
        return Verdict(False, "the rope is not in the room's own record", {})
    fixed_mm = record["at_mm"] if anchored.get(record["a"]) else record["to_mm"]
    pivot = [v / 1000.0 for v in fixed_mm]
    track = []
    for _ in range(int(8.0 / (8 * DT))):
        world.step(8)
        body = world.body(bob)
        if body is None:
            return Verdict(False, f"{bob} broke", {"bob": bob})
        track.append((world.simulated_s, body["position_m"]))
    offsets = [[p[0] - pivot[0], 0.0, p[2] - pivot[2]] for _, p in track]
    widest = max(offsets, key=norm)
    swing = norm(widest)
    measured = {"bob": bob, "pivot_m": [round(x, 3) for x in pivot], "swing_m": round(swing, 3)}
    if swing < 0.03:
        return Verdict(False, f"{bob} hangs still: nothing set it swinging", measured)
    way = unit(widest)
    s = [dot(o, way) for o in offsets]
    crossings = []
    for k in range(1, len(s)):
        if (s[k - 1] < 0.0) != (s[k] < 0.0):
            t0, t1 = track[k - 1][0], track[k][0]
            crossings.append(t0 + (t1 - t0) * (-s[k - 1]) / (s[k] - s[k - 1]))
    if len(crossings) < 3:
        return Verdict(False, f"{bob} did not swing through the middle often enough to time",
                       measured)
    period = 2.0 * (crossings[-1] - crossings[0]) / (len(crossings) - 1)
    length = sum(norm(sub(p, pivot)) for _, p in track) / len(track)
    size = world.body(bob)["dimensions_m"]
    if world.body(bob).get("shape") == "sphere":
        k2 = 0.1 * size[0] ** 2                      # 2/5 r^2
    else:
        across = max(range(3), key=lambda i: abs(way[i]))
        k2 = (size[across] ** 2 + size[1] ** 2) / 12.0
    theta = math.asin(min(1.0, max(abs(x) for x in s[: len(s) // 2]) / length))
    predicted = (2.0 * math.pi * math.sqrt((length * length + k2) / (G * length))
                 * (1.0 + theta ** 2 / 16.0 + 11.0 * theta ** 4 / 3072.0))
    error = (period - predicted) / predicted
    measured.update(length_m=round(length, 3), swing_deg=round(math.degrees(theta), 1),
                    period_s=round(period, 4), predicted_s=round(predicted, 4),
                    off_by=round(error, 4))
    if abs(error) > 0.05:
        return Verdict(False, f"{bob} swings with a period of {period:.3f} s; a {length:.2f} m "
                              f"pendulum has {predicted:.3f} s", measured)
    return Verdict(True, f"{bob} swings with a period of {period:.3f} s, and a {length:.2f} m "
                         f"pendulum should have {predicted:.3f} s ({error:+.1%})", measured)


# ---------------------------------------------------------------------------
# Breaking, bending, and holding when it should
# ---------------------------------------------------------------------------

def check_ice_breaks(built: Built) -> Verdict:
    world = built.world
    ice = [b["name"] for b in built.room.bodies() if material(b) == "ice"]
    if not ice:
        return Verdict(False, "nothing made of ice is in the room", {})
    fixed = [b["name"] for b in built.room.bodies() if material(b) == "ice" and b.get("anchored")]
    world.seconds(3.0)
    broken = [n for n in ice if world.body(n) is None or pieces_of(world, n) or n in world.finished]
    fastest = hit_speed(world, ice)
    measured = {"ice": ice, "broken": broken, "hardest_hit_m_s": round(fastest, 2)}
    if broken:
        return Verdict(True, f"{broken[0]} broke, struck at {fastest:.1f} m/s", measured)
    if fixed:
        return Verdict(False, f"{fixed[0]} is anchored, and anchored things cannot break", measured)
    return Verdict(False, f"the ice did not break: the hardest hit on it was {fastest:.1f} m/s",
                   measured)


def check_dent(built: Built) -> Verdict:
    world = built.world
    plates = [b["name"] for b in built.room.bodies() if material(b) == "aluminum"]
    if not plates:
        return Verdict(False, "nothing made of aluminium is in the room", {})
    world.seconds(3.0)
    here = world.bodies()
    dents = {n: float(here[n].get("dent_mm") or 0.0) for n in plates if n in here}
    broken = [n for n in plates if n not in here or pieces_of(world, n)]
    dented = [n for n, d in dents.items() if d > 0.0 and n not in broken]
    measured = {"aluminium": plates, "dent_mm": {n: round(d, 3) for n, d in dents.items()},
                "broken": broken, "hardest_hit_m_s": round(hit_speed(world, plates), 2)}
    if dented:
        return Verdict(True, f"{dented[0]} dented {dents[dented[0]]:.2f} mm and is still in one "
                             f"piece", measured)
    if broken:
        return Verdict(False, f"{broken[0]} broke instead of denting", measured)
    return Verdict(False, f"nothing dented: the hardest hit was {measured['hardest_hit_m_s']} m/s",
                   measured)


def check_pane_breaks(built: Built) -> Verdict:
    """When something on a pin breaks, the pin must follow the piece that
    holds it -- and that piece goes on hanging from it."""
    world = built.world
    anchored = world.anchored()
    joints = attached(world)
    pins = [(j, moving_end(j, anchored)) for j in joints if j["kind"] == "hinge"]
    pins = [(j, m) for j, m in pins if m and material(world.body(m)) == "glass"]
    if not pins:
        return Verdict(False, "no glass hangs on a hinge from anything fixed",
                       {"joints": joints_in_words(joints)})
    pin, pane = pins[0]
    world.seconds(3.0)
    pieces = pieces_of(world, pane)
    measured = {"pane": pane, "pieces": len(pieces), "hardest_hit_m_s": round(hit_speed(world, [pane]), 2)}
    if not pieces and world.body(pane) is not None:
        return Verdict(False, f"{pane} did not break: the hardest hit on it was "
                              f"{measured['hardest_hit_m_s']} m/s", measured)
    now = world.joint(pin["id"])
    measured["pin_holds"] = [now["a"], now["b"]] if now else None
    if now is None or not now.get("attached"):
        return Verdict(False, f"{pane} broke into {len(pieces)} pieces and the pin let go of all of "
                              f"them", measured)
    holder = now["b"] if anchored.get(now["a"]) else now["a"]
    body = world.body(holder)
    if not holder.startswith(pane + " piece"):
        return Verdict(False, f"the pin still names {holder}, which is not one of {pane}'s pieces",
                       measured)
    if body is None:
        return Verdict(False, f"the pin names {holder}, which is not in the world", measured)
    measured["holder_bottom_m"] = round(bottom(body), 3)
    if bottom(body) < 0.02:
        return Verdict(False, f"the pin holds {holder}, but it lies on the floor", measured)
    return Verdict(True, f"{pane} broke into {len(pieces)} pieces; the pin now holds {holder}, "
                         f"still hanging {bottom(body):.2f} m off the floor", measured)


def check_bridge_holds(built: Built) -> Verdict:
    """A load a plank can carry is carried: nothing breaks that should not."""
    world = built.world
    world.seconds(3.0)
    over = [str(o.get("name")) for o in (world.session.send(op="overloaded").get("overloaded") or [])]
    here = world.bodies()
    oak = sorted((b for b in built.room.bodies() if material(b) == "oak" and not b.get("anchored")),
                 key=lambda b: -max(size_m(b)))
    if not oak:
        return Verdict(False, "there is no oak plank", {})
    plank = oak[0]["name"]
    broken = [b["name"] for b in built.room.bodies() if b["name"] not in here]
    measured = {"plank": plank, "overloaded": over, "broken": broken}
    if plank not in here:
        return Verdict(False, f"{plank} broke", measured)
    body = here[plank]
    top = body["position_m"][1] + body["dimensions_m"][1] / 2.0
    loads = [b for b in here.values() if not b.get("anchored") and b["name"] != plank
             and material(b) == "iron" and abs(bottom(b) - top) < 0.05]
    if not loads:
        return Verdict(False, f"nothing made of iron rests on {plank}", measured)
    carried = sum(mass(b) for b in loads) * G
    measured.update(carrying_n=round(carried), plank_bottom_m=round(bottom(body), 3))
    if over or broken:
        return Verdict(False, f"{', '.join(over or broken)} gave way under {carried:.0f} N", measured)
    if bottom(body) < 0.05:
        return Verdict(False, f"{plank} is down on the floor", measured)
    return Verdict(True, f"{plank} carries {', '.join(b['name'] for b in loads)} ({carried:.0f} N) "
                         f"without breaking", measured)


# ---------------------------------------------------------------------------
# A bow: stored energy into flight, and no more than was stored
# ---------------------------------------------------------------------------

def check_bow(built: Built) -> Verdict:
    world = built.world
    world.seconds(1.0)
    anchored = world.anchored()
    joints = attached(world)
    limbs = [j for j in joints if j["kind"] == "elastic"]
    ropes = [j for j in joints if j["kind"] == "link"]
    base = {"joints": joints_in_words(joints)}
    if not limbs:
        return Verdict(False, "nothing elastic: a bow keeps its draw in its limbs", base)
    if not ropes:
        return Verdict(False, "no string: nothing is tied between the limbs", base)
    bodies = world.bodies()

    def slender(b: dict[str, Any]) -> float:
        d = sorted(b["dimensions_m"])
        return d[2] / max(d[1], 1e-6)

    arrows = sorted((b for b in bodies.values() if not b.get("anchored") and slender(b) >= 5.0),
                    key=lambda b: (not worded(b["name"], ("arrow", "bolt", "shaft")), -slender(b)))
    if not arrows:
        return Verdict(False, "no arrow: nothing long and thin that could fly", base)
    arrow = arrows[0]["name"]
    tied = {n for j in ropes for n in (j["a"], j["b"]) if not anchored.get(n)}
    nocks = [j for j in joints if j["kind"] == "fixing" and arrow in (j["a"], j["b"])]
    string = next((other for j in nocks
                   for other in [j["b"] if j["a"] == arrow else j["a"]] if other in tied), None)
    if string is None:
        named = sorted(n for n in tied if worded(n, ("string",)))
        string = named[0] if named else None
    if string is None:
        return Verdict(False, f"nothing holds {arrow} to a string", base)
    long_axis = max(range(3), key=lambda i: bodies[arrow]["dimensions_m"][i])
    forward = [0.0, 0.0, 0.0]
    forward[long_axis] = 1.0
    if dot(sub(bodies[string]["position_m"], bodies[arrow]["position_m"]), forward) > 0.0:
        forward = scale(forward, -1.0)
    kg = mass(bodies[arrow])
    s0, a0 = bodies[string]["position_m"], bodies[arrow]["position_m"]
    draw = 0.25
    world.session.send(op="grab", name=string)
    steps = int(draw / 0.002)
    for i in range(1, steps + 1):
        world.step(1, hand=add(s0, scale(forward, -draw * i / steps)))
    full = add(s0, scale(forward, -draw))
    for _ in range(300):
        world.step(1, hand=full)
    stored = sum(float(j.get("stored_j") or 0.0) for j in world.joints()
                 if j["kind"] == "elastic" and j.get("attached"))
    drawn = -dot(sub(world.body(string)["position_m"], s0), forward)
    world.session.send(op="release")
    # The room lets the nock go when the limbs stop pushing -- when the
    # string's speed along the shot stops rising. The same moment here.
    loosed, last, peak = not nocks, 0.0, 0.0
    for _ in range(int(0.6 / DT)):
        world.step(1)
        s = world.body(string)
        speed = dot((s or {}).get("velocity_m_s") or [0.0, 0.0, 0.0], forward)
        if not loosed and speed > 0.5 and speed <= last:
            for j in nocks:
                world.session.send(op="unhinge", joint=j["id"])
            loosed = True
        last = speed
        a = world.body(arrow)
        if a:
            peak = max(peak, dot(a.get("velocity_m_s") or [0.0, 0.0, 0.0], forward))
    world.seconds(1.0)
    a = world.body(arrow)
    flew = dot(sub(a["position_m"], a0), forward) if a else 0.0
    energy = 0.5 * kg * peak * peak
    measured = {"arrow": arrow, "string": string, "drawn_m": round(drawn, 3),
                "stored_j": round(stored, 2), "arrow_kg": round(kg, 3), "speed_m_s": round(peak, 2),
                "arrow_j": round(energy, 2), "flew_m": round(flew, 2)}
    if drawn < 0.1:
        return Verdict(False, f"the string came back only {drawn * 1000:.0f} mm under a hand's "
                              f"800 N: the limbs are too stiff to draw", measured)
    if stored < 0.5:
        return Verdict(False, f"drawn {drawn * 1000:.0f} mm, the limbs hold only {stored:.2f} J",
                       measured)
    if energy > 1.05 * stored + 0.05:
        return Verdict(False, f"the arrow left with {energy:.1f} J from {stored:.1f} J stored -- "
                              f"more than the limbs held", measured)
    if peak < 3.0 or flew < 1.0:
        return Verdict(False, f"loosed from a {drawn * 1000:.0f} mm draw holding {stored:.1f} J, "
                              f"{arrow} left at {peak:.1f} m/s and went {flew:.2f} m", measured)
    return Verdict(True, f"drawn {drawn * 1000:.0f} mm the limbs held {stored:.1f} J; {arrow} left "
                         f"at {peak:.1f} m/s ({energy:.1f} J, {energy / stored:.0%} of it) and flew "
                         f"{flew:.1f} m", measured)


# ---------------------------------------------------------------------------
# Heat: only what has fuel burns -- and the agent has to say so
# ---------------------------------------------------------------------------

SAID_IT_CANNOT = re.compile(
    r"(iron|metal)[^.]{0,80}\b(can(?:no|')t|won'?t|will not|does(?:n'?t| not)|isn'?t|is not)\b"
    r"[^.]{0,40}\b(burn|catch|light|ignite|combust)|no fuel|not (?:flammable|combustible)"
    r"|non-?flammable|incombustible", re.I)
FIRE_WORDS = re.compile(r"\b(burning|on fire|alight|ablaze|aflame|caught)\b", re.I)
NEGATION = re.compile(r"\b(not|no|never|n't|cannot|without)\b|n't\b", re.I)


def claims_iron_burns(reply: str) -> bool:
    for sentence in re.split(r"(?<=[.!?])\s+", reply or ""):
        if re.search(r"\b(iron|bar)\b", sentence, re.I) and FIRE_WORDS.search(sentence) \
                and not NEGATION.search(sentence):
            return True
    return False


def check_iron_wont_burn(built: Built) -> Verdict:
    world = built.world
    iron = [b["name"] for b in built.room.bodies() if material(b) == "iron"]
    world.seconds(max(60.0, abt._heater_end_s(built.room) + 30.0))
    report = abt._thermo(world)
    burning = [b for b in report["bodies"] if b["reacting"] and b["heat_release_w"] > 100.0]
    iron_burning = [b for b in burning if b["name"] in iron]
    measured = {"iron": [[b["name"], round(b["temperature_k"])] for b in report["bodies"]
                         if b["name"] in iron],
                "burning": [[b["name"], round(b["heat_release_w"])] for b in burning],
                "heaters": [h.get("target") for h in ((built.room.spec.get("thermo") or {})
                                                      .get("heaters") or [])]}
    if iron_burning:
        return Verdict(False, f"{iron_burning[0]['name']} is burning at "
                              f"{iron_burning[0]['heat_release_w'] / 1000:.1f} kW -- iron has no fuel",
                       measured)
    if claims_iron_burns(built.reply):
        return Verdict(False, "the reply says the iron is burning; in the engine nothing in it "
                              "reacts", {**measured, "reply": built.reply[:300]})
    hottest = max((t for _, t in measured["iron"]), default=0)
    return Verdict(True, f"the iron did not burn (it reached {hottest} K; nothing in it reacts)",
                   measured)


def check_tether(built: Built) -> Verdict:
    """A rope pulls and does not push: hauled away, the block stops at the
    rope's length; pushed back, the rope goes slack and lets it come."""
    world = built.world
    world.seconds(1.0)
    anchored = world.anchored()
    joints = attached(world)
    ropes = [(j, moving_end(j, anchored)) for j in joints if j["kind"] == "link"]
    ropes = [(j, m) for j, m in ropes if m]
    if not ropes:
        return Verdict(False, "nothing is tied to anything fixed", {"joints": joints_in_words(joints)})
    rope, block = ropes[0]
    length = float(rope.get("length_m") or 0.0)
    record = next((j for j in built.room.spec.get("joints", [])
                   if j.get("kind") == "link" and {j.get("a"), j.get("b")} == {rope["a"], rope["b"]}),
                  None)
    fixed = ([v / 1000.0 for v in (record["at_mm"] if anchored.get(record["a"]) else record["to_mm"])]
             if record else list(rope["at"]))
    here = world.body(block)["position_m"]
    away = unit([here[0] - fixed[0], 0.0, here[2] - fixed[2]])
    if norm(away) == 0.0:
        away = [1.0, 0.0, 0.0]
    haul(world, block, scale(away, length + 1.0), seconds=2.5)
    taut = world.joint(rope["id"]) or {}
    reach, tension = float(taut.get("metres") or 0.0), float(taut.get("tension_n") or 0.0)
    world.session.send(op="release")
    world.seconds(0.5)
    out = world.body(block)["position_m"]
    haul(world, block, scale(away, -0.4), seconds=1.0)
    came = dot(sub(world.body(block)["position_m"], out), scale(away, -1.0))
    slack = float((world.joint(rope["id"]) or {}).get("tension_n") or 0.0)
    world.session.send(op="release")
    measured = {"block": block, "rope_m": round(length, 3), "pulled_to_m": round(reach, 3),
                "tension_n": round(tension, 1), "pushed_back_m": round(came, 3),
                "slack_tension_n": round(slack, 1)}
    if length <= 0.0:
        return Verdict(False, "the rope has no length", measured)
    if reach > 1.05 * length + 0.02:
        return Verdict(False, f"hauled {length + 1:.1f} m out, the rope stretched to {reach:.2f} m; "
                              f"it is {length:.2f} m long", measured)
    if tension < 1.0:
        return Verdict(False, f"hauled {length + 1:.1f} m away, the rope carried nothing: {block} "
                              f"never reached its end", measured)
    if came < 0.25:
        return Verdict(False, f"pushed back towards the post, {block} moved only {came:.2f} m: the "
                              f"rope is pushing", measured)
    return Verdict(True, f"hauled away, {block} stopped at {reach:.2f} m on its {length:.2f} m rope, "
                         f"carrying {tension:.0f} N; pushed back it came {came:.2f} m, the rope "
                         f"slack", measured)


# ---------------------------------------------------------------------------
# The cases
# ---------------------------------------------------------------------------

CASES = [
    Case("hoist", "yard",
         "Build a hoist: a rope over two pulleys on a high beam, with an iron weight on one end "
         "and a wooden handle on the other, so pulling the handle down lifts the weight.",
         check_hoist, "a rope over pulleys: one end pulled down, the other rises by the ratio"),
    Case("counterweight", "yard",
         "Build a portcullis balanced by a counterweight on a rope over pulleys, so it stays "
         "wherever you leave it.",
         check_counterweight, "a slide balanced by mass: left anywhere, it stays"),
    Case("latched-gate", "yard", "Build a wooden gate on a hinge with a bar that locks it shut.",
         check_latched_gate, "a latch that holds against a shove, and lets go"),
    Case("courtyard-unbar", "courtyard",
         "Take the locking bar off the courtyard gate so it can swing open.",
         check_unbarred_gate, "changing a mechanism that is already in the room"),
    Case("seesaw", "yard",
         "Build a seesaw: an oak plank on a pivot, with a heavy iron block on one end and a small "
         "oak block on the other.",
         check_seesaw, "turning moment about a pin: the heavier side goes down"),
    Case("bow", "yard", "Build a bow on a stand with an arrow on the string, ready to draw.",
         check_bow, "energy stored in limbs, spent on an arrow -- and never more than was stored"),
    Case("tether", "yard", "Tie an iron block to a stone post with a one-metre rope.",
         check_tether, "a rope pulls and does not push"),
    Case("pendulum", "yard",
         "Hang an iron ball from a high beam on a one-metre rope and set it swinging.",
         check_pendulum, "a pendulum's period, fixed by its length"),
    Case("spring-weight", "yard", "Hang an iron weight from a wooden beam on a spring.",
         check_spring_weight, "a spring carries exactly what hangs on it"),
    Case("plank-bridge", "yard",
         "Lay a thick oak plank across two stone blocks as a bridge and put an iron block in the "
         "middle of it.",
         check_bridge_holds, "a load that can be carried is carried: nothing breaks that should not"),
    Case("ice-breaks", "yard", "Drop a heavy iron block onto a slab of ice so the ice breaks.",
         check_ice_breaks, "brittle fracture from an impact"),
    Case("dent", "yard",
         "Drop an iron ball onto an aluminium plate hard enough to dent it without breaking it.",
         check_dent, "a dent, short of breaking"),
    Case("pane-breaks", "yard",
         "Hang a glass pane from a stone post on a hinge, like a small door, and throw an iron "
         "ball at it to break it.",
         check_pane_breaks, "when what a pin holds breaks, the pin follows the piece that holds it"),
    Case("tower", "yard", "Stack five oak blocks into a tower.",
         check_tower, "resting contact: a stack that stands still"),
    Case("dominoes", "yard",
         "Stand eight wooden dominoes in a row and roll an iron ball into the first so they all "
         "fall over.",
         check_dominoes, "momentum passed along by contact"),
    Case("bounce", "yard", "Drop a rubber ball onto the floor from two metres up.",
         check_bounce, "restitution: rubber gives back about a third of its drop"),
    Case("sliding", "yard",
         "Slide an ice block and an oak block across the floor side by side, both starting at "
         "three metres a second.",
         check_sliding, "sliding friction: ice goes much further than oak"),
    Case("projectile", "yard",
         "Throw an iron ball across the yard at five metres a second from one metre up.",
         check_projectile, "free flight: where gravity must put it, moment by moment"),
    Case("iron-wont-burn", "yard", "Put an iron bar on a stone slab and set it on fire.",
         check_iron_wont_burn, "only what has fuel burns -- and the reply has to say so",
         accept_no_change=lambda reply: bool(SAID_IT_CANNOT.search(reply))),
]


# ---------------------------------------------------------------------------
# The same things, built by hand through the MCP
# ---------------------------------------------------------------------------

def _ball(name: str, stuff: str, diameter: float, at: list[float],
          moving: list[float] | None = None) -> tuple[str, dict[str, Any]]:
    obj: dict[str, Any] = {"name": name, "shape": "sphere", "material": stuff,
                           "size_m": [diameter] * 3, "position_m": at}
    if moving:
        obj["velocity_m_s"] = moving
    return ("add_object", {"object": obj})


def _sent(name: str, stuff: str, size: list[float], at: list[float],
          moving: list[float]) -> tuple[str, dict[str, Any]]:
    return ("add_object", {"object": {"name": name, "shape": "box", "material": stuff,
                                      "size_m": size, "position_m": at, "velocity_m_s": moving}})


def _bow() -> list[tuple[str, dict[str, Any]]]:
    """The courtyard's own bow as MCP calls: grips, cheeks, limb tips, string,
    arrow, and every joint between them. It stands where it stands there."""
    spec = world_room.courtyard()
    keep = {"bow grip upper", "bow grip lower", "bow grip near cheek", "bow grip far cheek",
            "upper limb tip", "lower limb tip", "bowstring", "arrow"}
    calls = [("add_object", {"object": {"name": b["name"], "shape": b["shape"],
                                        "material": b["material"],
                                        "size_m": [v / 1000.0 for v in b["size_mm"]],
                                        "position_m": [v / 1000.0 for v in b["center_mm"]],
                                        "anchored": bool(b.get("anchored"))}})
             for b in spec["bodies"] if b["name"] in keep]
    return calls + [room_world.joint_call(j) for j in spec["joints"]
                    if j["a"] in keep and j["b"] in keep]


def _unbar(world_id: str) -> dict[str, Any]:
    """Let the courtyard's locking bar go from its jamb, by the joint's id."""
    listed = room_world.call(world_id, "joints", {})
    for j in listed.get("joints") or []:
        if {j.get("a"), j.get("b")} == {"locking bar", "gate jamb left"}:
            # The MCP gives each joint a stable id under "joint", not the
            # engine's, which a rebuild renumbers.
            return room_world.call(world_id, "unhinge", {"joint": j["joint"]})
    return {"error": f"the locking bar is not fixed to its jamb: {str(listed)[:300]}"}


RECIPES: dict[str, tuple[Any, ...]] = {
    # Load on the floor, handle hanging, the rope taut between them: the handle
    # weighs 7 N against the weight's 316 N, so nothing moves until pulled.
    "hoist": ("hoist", [
        _box("hoist beam", "oak", [1.6, 0.12, 0.16], [0.0, 2.46, 0.0], True),
        _box("iron weight", "iron", [0.16, 0.16, 0.16], [-0.6, 0.08, 0.0]),
        _box("hoist handle", "oak", [0.08, 0.16, 0.08], [0.6, 1.2, 0.0]),
        ("reeve", {"a": "hoist handle", "b": "iron weight",
                   "at_a_m": [0.6, 1.28, 0.0], "at_b_m": [-0.6, 0.16, 0.0],
                   "over_a_m": [0.6, 2.36, 0.0], "over_b_m": [-0.6, 2.36, 0.0], "ratio": 1}),
    ]),
    # The courtyard's own proportions: 403 kg of grate against 403 kg of
    # counterweight, ratio 1, and 200 N of friction in the grooves.
    "counterweight": ("counterweight", [
        _box("left post", "concrete", [0.16, 2.4, 0.16], [-0.52, 1.2, 0.0], True),
        _box("right post", "concrete", [0.16, 2.4, 0.16], [0.52, 1.2, 0.0], True),
        _box("lintel", "concrete", [1.2, 0.12, 0.16], [0.0, 2.46, 0.0], True),
        _box("iron portcullis", "iron", [0.8, 0.8, 0.08], [0.0, 0.44, 0.0]),
        ("slide", {"a": "left post", "b": "iron portcullis", "at_m": [0.0, 0.44, 0.0],
                   "axis": [0, 1, 0], "lower_m": 0.0, "upper_m": 1.2, "friction_n": 200}),
        _box("counterweight", "iron", [0.4, 0.32, 0.4], [1.2, 1.2, 0.0]),
        ("reeve", {"a": "counterweight", "b": "iron portcullis",
                   "at_a_m": [1.2, 1.36, 0.0], "at_b_m": [0.0, 0.84, 0.0],
                   "over_a_m": [1.2, 2.36, 0.0], "over_b_m": [0.0, 2.36, 0.0], "ratio": 1}),
    ]),
    # The hinged gate, and an iron bar across its free end fixed to the gate
    # and to the far post: a latch is two fixings, one of which can be let go.
    "latched-gate": ("latched-gate", [
        _box("stone post", "concrete", [0.16, 2.0, 0.16], [0.0, 1.0, 0.0], True),
        _box("far post", "concrete", [0.16, 2.0, 0.16], [1.44, 1.0, 0.0], True),
        _box("oak gate", "oak", [1.2, 1.6, 0.08], [0.68, 0.84, 0.16]),
        ("hinge", {"a": "stone post", "b": "oak gate", "at_m": [0.08, 0.84, 0.16],
                   "axis": [0, 1, 0], "lower_deg": -100, "upper_deg": 100, "friction_n_m": 10}),
        _box("locking bar", "iron", [0.48, 0.08, 0.08], [1.28, 1.2, 0.28]),
        ("fix", {"a": "oak gate", "b": "locking bar", "at_m": [1.2, 1.2, 0.24], "axis": [0, 0, 1]}),
        ("fix", {"a": "far post", "b": "locking bar", "at_m": [1.44, 1.2, 0.24], "axis": [1, 0, 0]}),
    ]),
    "courtyard-unbar": ("courtyard-unbar", [(_unbar, None)], {"keep_room": True}),
    # A plank a cell above its pivot, so nothing rubs; iron on one end and oak
    # on the other, both 800 mm out.
    "seesaw": ("seesaw", [
        _box("pivot stone", "concrete", [0.16, 0.4, 0.16], [0.0, 0.2, 0.0], True),
        _box("oak plank", "oak", [2.0, 0.08, 0.24], [0.0, 0.48, 0.0]),
        ("hinge", {"a": "pivot stone", "b": "oak plank", "at_m": [0.0, 0.48, 0.0],
                   "axis": [0, 0, 1], "lower_deg": -25, "upper_deg": 25, "friction_n_m": 2}),
        _box("iron block", "iron", [0.16, 0.16, 0.16], [0.84, 0.6, 0.0]),
        _box("small oak block", "oak", [0.16, 0.16, 0.16], [-0.84, 0.6, 0.0]),
    ]),
    "bow": ("bow", _bow()),
    # The rope's two ends 0.68 m apart on a 1 m rope: slack to start with.
    "tether": ("tether", [
        _box("stone post", "concrete", [0.16, 1.2, 0.16], [0.0, 0.6, 0.0], True),
        _box("iron block", "iron", [0.16, 0.16, 0.16], [0.84, 0.08, 0.0]),
        ("tie", {"a": "stone post", "b": "iron block", "at_a_m": [0.08, 0.12, 0.0],
                 "at_b_m": [0.76, 0.12, 0.0], "length_m": 1.0}),
    ]),
    # Tied at the ball's centre, the rope as long as it is when built: about
    # 0.99 m, and 21 degrees out to start.
    "pendulum": ("pendulum", [
        _box("high beam", "oak", [0.4, 0.12, 0.16], [0.0, 2.46, 0.0], True),
        _ball("iron ball", "iron", 0.12, [0.36, 1.48, 0.0]),
        ("tie", {"a": "high beam", "b": "iron ball", "at_a_m": [0.0, 2.4, 0.0],
                 "at_b_m": [0.36, 1.48, 0.0]}),
    ]),
    # 32 kg on 2 kN/m: 158 mm of stretch, built at that length so it hangs still.
    "spring-weight": ("spring-weight", [
        _box("oak beam", "oak", [0.8, 0.12, 0.16], [0.0, 2.06, 0.0], True),
        _box("iron weight", "iron", [0.16, 0.16, 0.16], [0.0, 1.24, 0.0]),
        ("spring", {"a": "oak beam", "b": "iron weight", "at_a_m": [0.0, 2.0, 0.0],
                    "at_b_m": [0.0, 1.32, 0.0], "rest_m": 0.52, "stiffness_n_m": 2000,
                    "damping_n_s_m": 40}),
    ]),
    # 109 kg of iron on 120 mm of oak over 0.96 m: about 0.3 MPa against 90.
    "plank-bridge": ("plank-bridge", [
        _box("left block", "concrete", [0.24, 0.4, 0.48], [-0.6, 0.2, 0.0], True),
        _box("right block", "concrete", [0.24, 0.4, 0.48], [0.6, 0.2, 0.0], True),
        _box("oak plank", "oak", [1.6, 0.12, 0.4], [0.0, 0.46, 0.0]),
        _box("iron block", "iron", [0.24, 0.24, 0.24], [0.0, 0.64, 0.0]),
    ]),
    # 1.36 m of fall is 5.2 m/s onto ice that breaks at about 2.3.
    "ice-breaks": ("ice-breaks", [
        _box("ice slab", "ice", [0.64, 0.08, 0.64], [0.0, 0.04, 0.0]),
        _box("iron block", "iron", [0.16, 0.16, 0.16], [0.0, 1.52, 0.0]),
    ]),
    "dent": ("dent", [
        _box("aluminium plate", "aluminum", [0.4, 0.08, 0.4], [0.0, 0.04, 0.0]),
        _ball("iron ball", "iron", 0.12, [0.0, 0.4, 0.0], [0.0, -30.0, 0.0]),
    ]),
    # The pane a cell clear of its post, hung at its edge; the ball thrown at
    # its far half at 16 m/s. At 8 m/s the engine's first screen says it could
    # break (its threshold is 4.5 m/s) and the full solve says it holds: a pane
    # a cell thick is 40 mm of glass, the thinnest this grid can make, and
    # strong. At 16 m/s it goes into 13 pieces.
    "pane-breaks": ("pane-breaks", [
        _box("stone post", "concrete", [0.16, 1.6, 0.16], [0.0, 0.8, 0.0], True),
        _box("glass pane", "glass", [0.64, 0.64, 0.04], [0.4, 1.0, 0.14]),
        ("hinge", {"a": "stone post", "b": "glass pane", "at_m": [0.08, 1.0, 0.14],
                   "axis": [0, 1, 0], "lower_deg": -90, "upper_deg": 90, "friction_n_m": 1}),
        _ball("iron ball", "iron", 0.12, [0.6, 1.2, 0.44], [0.0, 0.0, -16.0]),
    ]),
    "tower": ("tower", [_box(f"oak block {i + 1}", "oak", [0.2, 0.2, 0.2], [0.0, 0.1 + 0.2 * i, 0.0])
                        for i in range(5)]),
    # 400 mm tall, 200 mm apart; the ball meets the first in its upper half.
    "dominoes": ("dominoes", [
        *[_box(f"domino {i + 1}", "oak", [0.04, 0.4, 0.24], [0.02 + 0.2 * i, 0.2, 0.0])
          for i in range(8)],
        _ball("iron ball", "iron", 0.12, [-0.5, 0.3, 0.0], [4.0, 0.0, 0.0]),
    ]),
    "bounce": ("bounce", [_ball("rubber ball", "rubber", 0.2, [0.0, 2.1, 0.0])]),
    "sliding": ("sliding", [
        _sent("ice block", "ice", [0.24, 0.24, 0.24], [0.0, 0.12, -0.4], [3.0, 0.0, 0.0]),
        _sent("oak block", "oak", [0.24, 0.24, 0.24], [0.0, 0.12, 0.4], [3.0, 0.0, 0.0]),
    ]),
    "projectile": ("projectile", [_ball("iron ball", "iron", 0.12, [0.0, 1.0, 0.0], [5.0, 0.0, 0.0])]),
    "iron-wont-burn": ("iron-wont-burn", [
        _box("stone slab", "concrete", [0.64, 0.08, 0.48], [0.0, 0.04, 0.0], True),
        _box("iron bar", "iron", [0.48, 0.08, 0.08], [0.0, 0.12, 0.0]),
        ("heat", {"target": "iron bar", "power_w": 10000, "seconds": 60, "label": "a torch"}),
    ]),
}


# How long the 3D pass lets each room run before its second picture: long
# enough for the thing to have happened, and for a hearth to have caught.
SHOW_S = {"hearth": 80.0, "heated-piston": 20.0, "iron-wont-burn": 10.0, "dominoes": 6.0,
          "pendulum": 6.0, "sliding": 5.0, "bounce": 4.0, "ice-breaks": 4.0, "pane-breaks": 4.0,
          "drop-on-glass": 4.0, "dent": 3.0, "projectile": 3.0}

# Cases whose room is right to be moving when the check is over, and why --
# said in the report instead of being flagged as a room that will not settle.
KEEPS_MOVING = {"pendulum": "a pendulum swings on: nothing in the engine damps it, no air"}

# How the report groups them.
GROUPS = [
    ("Mechanisms", ["hinged-gate", "portcullis", "castle-gate", "castle-gate-courtyard",
                    "courtyard-full", "hoist", "counterweight", "latched-gate", "seesaw", "bow"]),
    ("Ropes, chains and springs", ["hanging-sign", "chain", "tether", "pendulum", "spring-weight"]),
    ("Breaking, bending and holding", ["loaded-shelf", "plank-bridge", "drop-on-glass",
                                       "ice-breaks", "dent", "pane-breaks"]),
    ("Contact and motion", ["tower", "dominoes", "bounce", "sliding", "projectile"]),
    ("Heat, fire and gas", ["hearth", "heated-piston", "iron-wont-burn"]),
    ("Changing what is already there", ["courtyard-unbar"]),
]
