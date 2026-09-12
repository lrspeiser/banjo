#!/usr/bin/env python3
"""Banjo as a tool a model can use: an MCP server over the physics engine.

Speaks the Model Context Protocol on stdin and stdout, so Claude, ChatGPT or
anything else that can launch a subprocess can build a world out of real matter,
run it, and be told what actually happened -- rather than being asked to imagine
what would.

    claude mcp add banjo -- python /path/to/banjo/mcp/banjo_mcp.py

No dependencies. The protocol is JSON-RPC 2.0 over newline-delimited stdio and
is short enough to speak directly, which matters for something people are meant
to install: a server that needs a package installed first is a server that does
not get installed.

WHAT THIS IS FOR

A model asked "does a glass ball break if I drop it two metres onto concrete"
will give you a confident paragraph. This gives it a way to find out. The engine
is the same one behind everything else here: matter is cells joined by bonds,
bonds carry tension and compression, they yield and they fail, and what happens
to an object is worked out rather than looked up.

The tools are deliberately above the level of the C API. A model does not want
to take four hundred and eighty steps; it wants to set something up, run it, and
be told what broke. `run` does the whole break conversation itself, which is the
part of this engine that a caller can get wrong -- ignore it and the world
freezes at the first impact for ever.
"""
from __future__ import annotations

import json
import math
import sys
import traceback
import uuid
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bindings" / "python"))

import banjo  # noqa: E402

PROTOCOL_VERSION = "2024-11-05"
SERVER = {"name": "banjo", "version": "1.0.0"}

# How many worlds may be open at once. Each is a physics engine with its scene
# resident in it, and nothing here is a long-lived service.
MAX_WORLDS = 8
# The longest a single run may simulate, and the longest it may take. The engine
# is far faster than real time when nothing is breaking and far slower for the
# moments when something is, so both bounds are needed: the first stops a model
# asking for an hour, the second stops one scene of shattering concrete from
# never returning.
MAX_RUN_S = 20.0
MAX_WALL_S = 25.0

MATERIALS = ["iron", "aluminum", "glass", "ceramic", "oak", "rubber", "ice", "concrete"]

# Measured on this engine, not looked up. The numbers a caller actually needs in
# order to design an experiment that shows something.
MATERIAL_NOTES = {
    "iron":     "Dense and tough. Bends before it breaks: onto concrete it dents "
                "above 14.2 m/s and breaks above 35.6. The thing to reach for when "
                "you want to break something else.",
    "aluminum": "Bends above 26.4 m/s onto concrete, breaks above 47.8. A poor "
                "hammer: springy, so it transmits less of a blow than iron does.",
    "oak":      "Bends above 10.4 m/s, breaks above 13.7. A narrow range between "
                "the two.",
    "rubber":   "Bounces back about a third of the height it fell, the most of "
                "anything here. Did not break at any speed tried.",
    "glass":    "Brittle: no bending range at all, it is whole or it is in pieces. "
                "Twenty-two times stronger in compression than tension, which is "
                "why it shatters in bending and crushes hard.",
    "ceramic":  "Brittle and very tough -- needs about 265 m/s onto concrete. "
                "Hard to break by dropping.",
    "ice":      "Brittle and very weak. Breaks at about 2.3 m/s.",
    "concrete": "Brittle and weak in tension: 3 MPa against 35 in compression. "
                "Breaks at about 0.7 m/s and comes apart into a great many "
                "pieces, so keep concrete objects small.",
}


class Refused(ValueError):
    """Something the caller can fix, said in words rather than a stack trace."""


# ---------------------------------------------------------------------------
# The worlds
# ---------------------------------------------------------------------------

WORLDS: dict[str, dict[str, Any]] = {}


def _world(world_id: str) -> dict[str, Any]:
    entry = WORLDS.get(str(world_id))
    if entry is None:
        raise Refused(f"there is no world called {world_id!r}. Worlds open now: "
                      f"{', '.join(WORLDS) or 'none'}")
    return entry


def _live(entry: dict[str, Any]) -> banjo.World:
    """The running world, or a refusal that says why there is none.

    A world can be emptied (clear_world) and built up again, and while it is
    empty there is nothing to step, pick or hang anything on. Said in words,
    because the alternative was an AttributeError on None reported as "the
    engine failed".
    """
    world = entry.get("world")
    if world is None:
        raise Refused("this world is empty. Put something in it with add_object "
                      "first.")
    return world


def _number(value: Any, what: str, low: float, high: float) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        raise Refused(f"{what} must be a number, not {value!r}")
    if not math.isfinite(out):
        raise Refused(f"{what} must be a finite number")
    return max(low, min(high, out))


def _triple(value: Any, what: str, low: float, high: float) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise Refused(f"{what} must be three numbers, like [0, 2, 0]")
    return [_number(v, what, low, high) for v in value]


def _scene(objects: Any, cell_m: float) -> dict[str, Any]:
    """The scene document, checked so the engine's complaints arrive as words."""
    if not isinstance(objects, list) or not objects:
        raise Refused("a world needs a non-empty list of objects")
    if len(objects) > 60:
        raise Refused(f"{len(objects)} objects is more than this server will open at "
                      f"once; sixty is plenty for an experiment")
    cell_mm = cell_m * 1000.0
    bodies = []
    for index, item in enumerate(objects):
        if not isinstance(item, dict):
            raise Refused(f"object {index + 1} is not an object description")
        name = str(item.get("name") or f"object {index + 1}")[:60]
        shape = str(item.get("shape") or "box")
        if shape not in ("box", "sphere"):
            raise Refused(f"{name}: shape must be 'box' or 'sphere', not {shape!r}")
        material = str(item.get("material") or "glass")
        if material not in MATERIALS:
            raise Refused(f"{name}: {material!r} is not a material this engine has. "
                          f"Use one of: {', '.join(MATERIALS)}")
        size = _triple(item.get("size_m"), f"{name}: size_m", 0.005, 4.0)
        if shape == "sphere":
            size = [size[0], size[0], size[0]]
        # Matter is built out of cells, so a side has to be a whole number of
        # them. Rounding here rather than refusing, because "0.31 m is not a
        # whole number of 0.02 m cells" is a true thing to say and a useless one.
        size = [max(1, round(v * 1000.0 / cell_mm)) * cell_mm / 1000.0 for v in size]
        centre = _triple(item.get("position_m"), f"{name}: position_m", -50.0, 50.0)
        speed = _triple(item.get("velocity_m_s") or [0, 0, 0],
                        f"{name}: velocity_m_s", -200.0, 200.0)
        bodies.append({"name": name, "shape": shape, "material": material,
                       "dimensions_m": size, "center_m": centre, "velocity_m_s": speed,
                       "anchored": bool(item.get("anchored"))})
    seen: set[str] = set()
    for body in bodies:
        if body["name"] in seen:
            raise Refused(f"two objects are both called {body['name']!r}; names have "
                          f"to be different because everything else refers to them")
        seen.add(body["name"])
    # Plasticity on: without it nothing can hold a shape it was pushed into, so
    # nothing can dent, and the engine can only ever show you things intact or
    # in bits.
    return {"plasticity": True, "bodies": bodies}


def _describe(world: banjo.World) -> list[dict[str, Any]]:
    out = []
    for body in world.bodies():
        out.append({
            "name": body.name,
            "material": body.material,
            "shape": body.shape,
            "position_m": [round(v, 4) for v in body.position_m],
            "size_m": [round(v, 4) for v in body.dimensions_m],
            "speed_m_s": round(math.sqrt(sum(v * v for v in body.velocity_m_s)), 3),
            "anchored": body.anchored,
        })
    return out


# ---------------------------------------------------------------------------
# The tools
# ---------------------------------------------------------------------------

def tool_list_materials(_args: dict[str, Any]) -> dict[str, Any]:
    return {"materials": [{"name": m, "behaviour": MATERIAL_NOTES[m]} for m in MATERIALS],
            "note": "Every speed above was measured by dropping a 100 mm ball of that "
                    "material onto a concrete floor. A threshold is the speed below "
                    "which nothing CAN happen; above it, it is possible and not "
                    "certain, and only running it says."}


def tool_create_world(args: dict[str, Any]) -> dict[str, Any]:
    if len(WORLDS) >= MAX_WORLDS:
        raise Refused(f"{MAX_WORLDS} worlds are already open. Close one first.")
    cell_m = _number(args.get("cell_size_m", 0.02), "cell_size_m", 0.005, 0.1)
    scene = _scene(args.get("objects"), cell_m)
    try:
        world = banjo.World(scene, cell_size_m=cell_m)
    except banjo.BanjoError as error:
        raise Refused(str(error))
    world_id = uuid.uuid4().hex[:8]
    WORLDS[world_id] = {"world": world, "scene": scene, "cell_m": cell_m, "story": [],
                        # Every joint made in this world, as the call that made
                        # it, so a rebuild can hang it again. See _rebuild.
                        "joints": [], "next_joint": 1,
                        # What has been swept up here, by material. Kept on the
                        # world because that is what it is a property of: the
                        # matter came out of this room and not another.
                        "carried": {}}
    return {"world_id": world_id, "cell_size_m": cell_m, "objects": _describe(world),
            "next": "Call run to let time pass. The floor is a plane at y = 0 and "
                    "gravity is on."}


def tool_describe_world(args: dict[str, Any]) -> dict[str, Any]:
    entry = _world(args.get("world_id"))
    world = entry.get("world")
    return {"world_id": args.get("world_id"),
            "time_s": round(world.time_s, 3) if world is not None else 0.0,
            "objects": _describe(world) if world is not None else [],
            "joints": len(entry.get("joints", [])),
            "what_has_happened": entry["story"][-20:]}


def tool_run(args: dict[str, Any]) -> dict[str, Any]:
    """Let time pass, settling whatever wants to break, and say what happened."""
    import time as clock
    entry = _world(args.get("world_id"))
    world: banjo.World = _live(entry)
    seconds = _number(args.get("seconds", 2.0), "seconds", 0.001, MAX_RUN_S)
    dt = 1.0 / 480.0
    began = clock.perf_counter()
    started_at = world.time_s
    events: list[dict[str, Any]] = []
    hardest: dict[tuple[str, str], dict[str, Any]] = {}
    stopped_early = None

    while world.time_s - started_at < seconds:
        if clock.perf_counter() - began > MAX_WALL_S:
            stopped_early = (f"stopped after {MAX_WALL_S:.0f} seconds of computing, "
                             f"having simulated {world.time_s - started_at:.3f} s. "
                             f"Something in this scene is breaking a great deal.")
            break
        state = world.step(dt)
        for hit in world.impacts(0.3):
            key = (hit.struck, hit.by)
            best = hardest.get(key)
            if best is None or hit.closing_speed_m_s > best["at_m_s"]:
                hardest[key] = {
                    "struck": hit.struck, "by": hit.by or "the ground",
                    "at_m_s": round(hit.closing_speed_m_s, 2),
                    "breaks_above_m_s": round(hit.threshold_speed_m_s, 2)
                                        if math.isfinite(hit.threshold_speed_m_s) else None,
                    # Infinite for a brittle material, which has no bending
                    # range at all. json_safe turns that into null on the way out.
                    "bends_above_m_s": round(hit.dent_speed_m_s, 2)
                                       if math.isfinite(hit.dent_speed_m_s) else None,
                }
        if state != banjo.BREAK_PENDING:
            continue
        # Something is one step short of giving way and the world will not move
        # until it is answered. Answering is what this tool is for.
        for name in world.breakable():
            # The contact that is about to do it, read BEFORE the fracture --
            # afterwards the body is gone and its pieces report their own
            # collisions instead. Without this the answer is a list of shards
            # hitting each other and no sign of what actually happened.
            cause = max((h for h in world.impacts(0.2) if h.struck == name),
                        key=lambda h: h.closing_speed_m_s, default=None)
            pieces = world.fracture(name)
            outcome = world.last_outcome
            if outcome not in ("broke", "dented"):
                continue
            event: dict[str, Any] = {"what": outcome, "object": name}
            if outcome == "broke":
                event["into_pieces"] = pieces
            else:
                event["note"] = "still one piece, and no longer the shape it was"
            if cause is not None:
                event["because"] = {
                    "hit_by": cause.by or "the ground",
                    "at_m_s": round(cause.closing_speed_m_s, 2),
                    "breaks_above_m_s": round(cause.threshold_speed_m_s, 2)
                                        if math.isfinite(cause.threshold_speed_m_s) else None,
                }
            events.append(event)

    for event in events:
        entry["story"].append(f"{event['object']} {event['what']}"
                              + (f" into {event['into_pieces']} pieces"
                                 if event.get("into_pieces") else ""))

    # Only contacts on something the engine can actually say anything about. A
    # single loose cell has no bonds left to fail, so its threshold is infinite
    # and reporting it is noise -- and after a pane shatters there are eighty of
    # them knocking into each other, which is all a caller would see.
    contacts = [h for h in hardest.values() if h["breaks_above_m_s"] is not None]
    contacts = sorted(contacts, key=lambda h: -h["at_m_s"])[:8]
    answer: dict[str, Any] = {
        "simulated_s": round(world.time_s - started_at, 3),
        "computing_took_s": round(clock.perf_counter() - began, 2),
        "what_happened": events or "nothing broke or bent",
        "hardest_contacts": contacts or "nothing touched anything hard enough to mention",
        "objects": _describe(world),
    }
    if stopped_early:
        answer["stopped_early"] = stopped_early
    if not events and contacts:
        answer["why_nothing_happened"] = (
            "Every contact was under the speed it would have taken. Drop it from "
            "higher, or use something denser to do the hitting: a threshold "
            "depends on what is doing the striking as much as how fast it goes.")
    return answer


def tool_drop(args: dict[str, Any]) -> dict[str, Any]:
    """Put a new object above a point and let it fall. The common experiment."""
    world_id = str(args.get("world_id"))
    entry = _world(world_id)
    world = entry.get("world")
    fall = _number(args.get("fall_m", 2.0), "fall_m", 0.05, 40.0)
    over = _triple(args.get("over_m") or [0, 0, 0], "over_m", -50.0, 50.0)
    # What is under that point, and how far down, so the thing is placed to fall
    # exactly `fall_m` onto it rather than `fall_m` above the floor. An empty
    # world has nothing under anything: it lands on the floor.
    found = world.pick([over[0], 40.0, over[2]], [0, -1, 0]) if world is not None else None
    top = 40.0 - found.distance_m if found is not None and found.hit else 0.0
    under = (found.name if found is not None and found.hit else "") or "the floor"
    item = dict(args.get("object") or {})
    size = _triple(item.get("size_m") or [0.1, 0.1, 0.1], "size_m", 0.005, 4.0)
    item["position_m"] = [over[0], top + size[1] / 2.0 + fall, over[2]]
    item.setdefault("name", f"{item.get('material', 'glass')} "
                            f"{'ball' if item.get('shape') == 'sphere' else 'block'}")
    added = _scene([item], entry["cell_m"])["bodies"][0]
    if any(b["name"] == added["name"] for b in entry["scene"]["bodies"]):
        raise Refused(f"there is already something called {added['name']!r} here; "
                      f"give the dropped thing another name")
    # A world is opened from a scene and that is the set of bodies it has, so
    # adding one means opening it again. Everything in flight starts over, and
    # the joints are hung again.
    _rebuild(entry, dict(entry["scene"], bodies=list(entry["scene"]["bodies"]) + [added]),
             world_id)
    entry["story"].append(f"dropped {item['name']} {fall:.2f} m onto {under}")
    # Long enough to land from that height, and then some to settle.
    answer = tool_run({"world_id": args.get("world_id"),
                       "seconds": math.sqrt(2 * fall / 9.81) + 1.5})
    answer["dropped"] = {"object": item["name"], "fall_m": round(fall, 3),
                         "onto": under}
    return answer


def tool_pick_up(args: dict[str, Any]) -> dict[str, Any]:
    """Take hold of something that is already in the world.

    Until now the only way to put an object somewhere was to drop a NEW one from
    above, which meant a model could add to a scene but never rearrange it.
    """
    entry = _world(args.get("world_id"))
    world: banjo.World = _live(entry)
    name = str(args.get("name", ""))
    try:
        world.grab(name)
    except banjo.BanjoError as error:
        # The engine's own wording, not wrapped in more of ours: it already says
        # the name and what was wrong, and two layers of it read as a stutter.
        raise Refused(str(error))
    entry["story"].append(f"picked up {name}")
    body = world.body(name)
    return {"holding": name,
            "at_m": [round(v, 3) for v in body.position_m] if body else None,
            "next": "Call place to move it, then let_go. While it is held it is "
                    "carried exactly where it is put and gravity does not act on "
                    "it, but it still pushes whatever it runs into."}


def tool_place(args: dict[str, Any]) -> dict[str, Any]:
    """Move what is in the hand to a point, without letting go."""
    entry = _world(args.get("world_id"))
    world: banjo.World = _live(entry)
    if not world.held:
        raise Refused("nothing is being held. Call pick_up first.")
    to = _triple(args.get("to_m") or [0, 1, 0], "to_m", -50.0, 50.0)
    world.move_held(to)
    # One step, so the world sees it where it now is rather than where it was.
    world.step(1.0 / 240.0)
    entry["story"].append(f"moved {world.held} to "
                          f"[{to[0]:.2f}, {to[1]:.2f}, {to[2]:.2f}]")
    return {"holding": world.held, "at_m": [round(v, 3) for v in to]}


def tool_let_go(args: dict[str, Any]) -> dict[str, Any]:
    """Let go. It rejoins the world from rest and falls from where it was left."""
    entry = _world(args.get("world_id"))
    world: banjo.World = _live(entry)
    was = world.held
    if not was:
        raise Refused("nothing is being held.")
    world.release()
    entry["story"].append(f"let go of {was}")
    # Long enough to land from a couple of metres and settle, and the run
    # settles anything that breaks on the way.
    answer = tool_run({"world_id": args.get("world_id"), "seconds": 2.0})
    answer["let_go_of"] = was
    return answer


def tool_collect(args: dict[str, Any]) -> dict[str, Any]:
    """Sweep up the loose pieces near a point and say what they were made of.

    Two reasons this matters. It is where raw materials come from -- what comes
    back is added up by material and by weight, which is the form anything built
    out of them wants. And it is how a world that shatters keeps working: the
    reversible step a fracture needs cannot run past a couple of thousand
    bodies, and past that the room quietly stops being able to break anything.
    """
    entry = _world(args.get("world_id"))
    world: banjo.World = _live(entry)
    at = _triple(args.get("near_m") or [0, 0, 0], "near_m", -50.0, 50.0)
    radius = _number(args.get("radius_m", 1.5), "radius_m", 0.05, 10.0)
    before = len(world.bodies())
    try:
        haul = world.collect(at, radius_m=radius)
    except banjo.BanjoError as error:
        raise Refused(str(error))

    carried: dict[str, Any] = entry["carried"]
    picked = []
    for lot in haul:
        have = carried.setdefault(lot.material, {"kilograms": 0.0, "pieces": 0})
        have["kilograms"] += lot.kilograms
        have["pieces"] += lot.pieces
        picked.append({"material": lot.material,
                       "kilograms": round(lot.kilograms, 4),
                       "grams": round(lot.kilograms * 1000.0, 1),
                       "pieces": lot.pieces})
    if picked:
        entry["story"].append("swept up " + ", ".join(
            f"{p['grams']:.0f} g of {p['material']}" for p in picked))
    return {"picked_up": picked,
            "objects_before": before,
            "objects_now": len(world.bodies()),
            "carried": {m: {"kilograms": round(v["kilograms"], 4),
                            "grams": round(v["kilograms"] * 1000.0, 1),
                            "pieces": v["pieces"]}
                        for m, v in sorted(carried.items())},
            "note": "Only pieces that came OFF something are swept up. Anchored "
                    "scenery, whatever is in the hand, and anything still the "
                    "object it always was -- including something merely DENTED "
                    "-- stay where they are."
                    if not picked else
                    "Anchored scenery and anything still the object it always "
                    "was stay where they are."}


def tool_carried(args: dict[str, Any]) -> dict[str, Any]:
    """What has been swept up in this world, by material."""
    entry = _world(args.get("world_id"))
    carried = entry["carried"]
    return {"carried": {m: {"kilograms": round(v["kilograms"], 4),
                            "grams": round(v["kilograms"] * 1000.0, 1),
                            "pieces": v["pieces"]}
                        for m, v in sorted(carried.items())},
            "total_kilograms": round(sum(v["kilograms"] for v in carried.values()), 4)}


def _joint_words(record: dict[str, Any]) -> str:
    args = record["args"]
    return f"joint {record['id']}, the {record['tool']} from {args.get('a')} to {args.get('b')}"


def _rebuild(entry: dict[str, Any], scene: dict[str, Any], world_id: str,
             joints: list[dict[str, Any]] | None = None) -> list[str]:
    """Open the world again from `scene`, and hang its joints back on it.

    A world is opened from a scene, so adding, moving or removing an object
    means opening it again. The scene used to hold BODIES only -- so every
    joint silently vanished at the next edit: hinge a gate, add a ball, and the
    gate was lying loose on the floor with nothing to say it had ever been
    hung. Joints are part of what was built. Each is recorded as the call that
    made it and made again here, in order; one that cannot be made again is
    dropped and SAID, in the list this returns.

    Nothing is committed until the new world exists: a refused scene leaves the
    old world, its scene and its joints exactly as they were.
    """
    joints = list(entry.get("joints", [])) if joints is None else list(joints)
    # Whoever owns this world can add their own conditions -- the playground's
    # room refuses what its lane could not open, so that the model is told at
    # the call rather than the person at the reopen.
    check = entry.get("check")
    if check is not None:
        try:
            check(scene, joints)
        except ValueError as problem:
            raise Refused(str(problem)) from None
    fresh = None
    if scene["bodies"]:
        try:
            fresh = banjo.World(scene, cell_size_m=entry["cell_m"])
        except banjo.BanjoError as error:
            raise Refused(str(error))
    old = entry.get("world")
    entry["world"], entry["scene"] = fresh, scene
    if old is not None:
        old.close()
    kept: list[dict[str, Any]] = []
    lost: list[str] = []
    for record in joints:
        if fresh is None:
            lost.append(f"{_joint_words(record)}: the world is empty")
            continue
        try:
            answer = MAKE_JOINT[record["tool"]]({**record["args"], "world_id": world_id})
        except Refused as why:
            lost.append(f"{_joint_words(record)}: {why}")
            continue
        record["live"] = answer["joint"]
        kept.append(record)
    entry["joints"] = kept
    return lost


def _held_by(entry: dict[str, Any], name: str) -> list[dict[str, Any]]:
    return [r for r in entry.get("joints", [])
            if name in (r["args"].get("a"), r["args"].get("b"))]


def tool_add_object(args: dict[str, Any]) -> dict[str, Any]:
    world_id = str(args.get("world_id"))
    entry = _world(world_id)
    added = _scene([args.get("object") or {}], entry["cell_m"])["bodies"][0]
    # Names are how every joint and every later call finds a thing, so a second
    # "oak gate" is refused rather than quietly shadowing the first.
    if any(b["name"] == added["name"] for b in entry["scene"]["bodies"]):
        raise Refused(f"there is already something called {added['name']!r} here. "
                      f"Joints and every later call find things by name, so give it "
                      f"another one.")
    scene = dict(entry["scene"], bodies=list(entry["scene"]["bodies"]) + [added])
    lost = _rebuild(entry, scene, world_id)
    answer: dict[str, Any] = {
        "added": added["name"], "objects": _describe(entry["world"]),
        "joints": len(entry["joints"]),
        "note": "A world is opened from a scene, so adding an object opens it again "
                "from the start: anything in flight is back where it was authored, "
                "and every joint is hung again."}
    if lost:
        answer["joints_lost"] = lost
    return answer


def tool_remove_object(args: dict[str, Any]) -> dict[str, Any]:
    world_id = str(args.get("world_id"))
    entry = _world(world_id)
    name = str(args.get("name", ""))
    kept = [b for b in entry["scene"]["bodies"] if b["name"] != name]
    if len(kept) == len(entry["scene"]["bodies"]):
        raise Refused(f"there is nothing called {name!r} in this world")
    if not kept:
        raise Refused("that would empty the world. Use clear_world to start again "
                      "from nothing.")
    # What held it goes with it -- a hinge with nothing on one side is not a
    # joint -- and is listed, so nothing disappears unannounced.
    held = _held_by(entry, name)
    joints = [r for r in entry["joints"] if r not in held]
    lost = _rebuild(entry, dict(entry["scene"], bodies=kept), world_id, joints)
    answer: dict[str, Any] = {"removed": name, "objects": _describe(entry["world"])}
    if held:
        answer["joints_removed_with_it"] = [_joint_words(r) for r in held]
    if lost:
        answer["joints_lost"] = lost
    return answer


def tool_move_object(args: dict[str, Any]) -> dict[str, Any]:
    """Put an object somewhere else, at rest: an EDIT to the world, not a push.

    Kept apart from pick_up / place / let_go on purpose. Those are a hand doing
    things to the world, and they obey it -- a held body still shoves what it
    runs into. This is the world being re-authored: the object is simply
    somewhere else, as if it had been built there.
    """
    world_id = str(args.get("world_id"))
    entry = _world(world_id)
    name = str(args.get("name", ""))
    body = next((b for b in entry["scene"]["bodies"] if b["name"] == name), None)
    if body is None:
        raise Refused(f"there is nothing called {name!r} in this world")
    # A joint is made at points in the world, and those points belong to the
    # bodies it joins. Moving one of them would leave the pin where it was, in
    # mid-air -- a gate hinged to a post three metres away. Refused and said,
    # with what to do instead.
    held = _held_by(entry, name)
    if held:
        raise Refused(f"{name} is held by {len(held)} joint(s): "
                      f"{'; '.join(_joint_words(r) for r in held)}. A joint is made at "
                      f"fixed points, so moving it would leave them behind. unhinge "
                      f"them first, or put things where they belong before joining "
                      f"them.")
    to = _triple(args.get("position_m"), "position_m", -50.0, 50.0)
    moved = dict(body, center_m=to, velocity_m_s=[0.0, 0.0, 0.0])
    scene = dict(entry["scene"], bodies=[moved if b is body else b
                                         for b in entry["scene"]["bodies"]])
    lost = _rebuild(entry, scene, world_id)
    entry["story"].append(f"moved {name} to [{to[0]:.2f}, {to[1]:.2f}, {to[2]:.2f}]")
    answer: dict[str, Any] = {"moved": name, "to_m": [round(v, 4) for v in to],
                              "objects": _describe(entry["world"])}
    if lost:
        answer["joints_lost"] = lost
    return answer


def tool_clear_world(args: dict[str, Any]) -> dict[str, Any]:
    """Empty a world of everything, joints and all, to build it again."""
    entry = _world(args.get("world_id"))
    count = len(entry["scene"]["bodies"])
    joints = len(entry.get("joints", []))
    old = entry.get("world")
    entry["scene"] = dict(entry["scene"], bodies=[])
    entry["joints"] = []
    entry["world"] = None
    if old is not None:
        old.close()
    entry["story"].append("cleared")
    return {"cleared_objects": count, "cleared_joints": joints,
            "note": "The world is empty and still open under the same id. add_object "
                    "puts the first thing back; everything else needs something in "
                    "it first."}


def tool_cast_ray(args: dict[str, Any]) -> dict[str, Any]:
    entry = _world(args.get("world_id"))
    found = _live(entry).pick(_triple(args.get("from_m"), "from_m", -200.0, 200.0),
                                _triple(args.get("direction"), "direction", -1e6, 1e6),
                                _number(args.get("max_m", 100.0), "max_m", 0.001, 500.0))
    if not found.hit:
        return {"hit": False, "note": "the ray reached its length without meeting anything"}
    return {"hit": True, "object": found.name or None,
            "is_the_floor": not found.name,
            "distance_m": round(found.distance_m, 4),
            "point_m": [round(v, 4) for v in found.point_m]}


def tool_hinge(args: dict[str, Any]) -> dict[str, Any]:
    """Hang one named thing off another on a pin.

    This is the difference between a scene and a mechanism. A door on a hinge
    swings because a push off its centre line makes a torque about the pin, and
    stops because it meets its travel limit or runs out of momentum -- so a
    model that wants a gate to open pushes something into it, rather than asking
    for the gate to be moved.
    """
    entry = _world(args.get("world_id"))
    world: banjo.World = _live(entry)
    try:
        joint = world.hinge(
            str(args.get("a", "")), str(args.get("b", "")),
            _triple(args.get("at_m"), "at_m", -200.0, 200.0),
            _triple(args.get("axis", [0.0, 1.0, 0.0]), "axis", -1e6, 1e6),
            _number(args.get("lower_deg", -180.0), "lower_deg", -180.0, 0.0),
            _number(args.get("upper_deg", 180.0), "upper_deg", 0.0, 180.0),
            _number(args.get("friction_n_m", 0.0), "friction_n_m", 0.0, 1e6))
    except banjo.BanjoError as error:
        raise Refused(str(error))
    return {"joint": joint,
            "note": f"{args.get('b')} now turns about a pin in {args.get('a')}. "
                    "Push something into it to open it; it will not move on its own."}


def _said(joint: banjo.Joint) -> dict[str, Any]:
    """One joint, in the unit its kind is measured in.

    Spelled out in the key rather than left for the reader to infer from
    `kind`: a caller that reads a slider's 0.8 as degrees has a portcullis
    fifty-seven times too tall.
    """
    common = {"joint": joint.id, "kind": joint.kind, "a": joint.a, "b": joint.b,
              "at_m": [round(v, 4) for v in joint.at_m],
              "axis": [round(v, 4) for v in joint.axis],
              "attached": joint.attached}
    if joint.kind == "elastic":
        return {**common,
                "length_m": round(joint.at, 4),
                "rest_m": round(joint.rest_m, 4),
                "stiffness_n_m": round(joint.stiffness_n_m, 2),
                "damping_n_s_m": round(joint.damping_n_s_m, 3),
                "force_n": round(joint.force_n, 2),
                "stored_j": round(joint.stored_j, 3)}
    if joint.kind == "fixing":
        return {**common,
                "tension_n": round(joint.tension_now_n, 2),
                "shear_n": round(joint.shear_now_n, 2),
                "holds_tension_n": round(joint.holds_tension_n, 2),
                "holds_shear_n": round(joint.holds_shear_n, 2)}
    if joint.kind == "pulley":
        return {**common,
                "rope_m": round(joint.at, 4),
                "length_m": round(joint.upper, 4),
                "tension_n": round(joint.tension_n, 2),
                "ratio": round(joint.ratio, 4),
                "over_a_m": [round(v, 4) for v in joint.over_a_m],
                "over_b_m": [round(v, 4) for v in joint.over_b_m]}
    if joint.kind == "link":
        return {**common,
                "apart_m": round(joint.at, 4),
                "length_m": round(joint.upper, 4),
                "tension_n": round(joint.tension_n, 2),
                "parts_at_n": round(joint.breaks_at_n, 2)}
    if joint.kind == "slider":
        return {**common,
                "moved_m": round(joint.at, 4),
                "travels_from_m": round(joint.lower, 4),
                "travels_to_m": round(joint.upper, 4),
                "friction_n": round(joint.friction, 2)}
    return {**common,
            "degrees": round(joint.at, 3),
            "opens_from_deg": round(joint.lower, 1),
            "opens_to_deg": round(joint.upper, 1),
            "friction_n_m": round(joint.friction, 3)}


def tool_slide(args: dict[str, Any]) -> dict[str, Any]:
    """Let one named thing slide along a line fixed in another.

    A portcullis in its grooves, a sliding door, a bolt across a door. Nothing
    is played: a grate hauled up and let go falls, and stops on whatever is
    under it at whatever height that thing happens to be.
    """
    world: banjo.World = _live(_world(args.get("world_id")))
    try:
        joint = world.slide(
            str(args.get("a", "")), str(args.get("b", "")),
            _triple(args.get("at_m"), "at_m", -200.0, 200.0),
            _triple(args.get("axis", [0.0, 1.0, 0.0]), "axis", -1e6, 1e6),
            _number(args.get("lower_m", -1.0), "lower_m", -100.0, 0.0),
            _number(args.get("upper_m", 1.0), "upper_m", 0.0, 100.0),
            _number(args.get("friction_n", 0.0), "friction_n", 0.0, 1e9))
    except banjo.BanjoError as error:
        raise Refused(str(error))
    return {"joint": joint,
            "note": f"{args.get('b')} now slides along a line in {args.get('a')}. "
                    "Nothing holds it there: if it can fall along that line, it "
                    "will, and it stops on whatever is under it."}


def tool_tie(args: dict[str, Any]) -> dict[str, Any]:
    """Tie one named thing to another with a rope.

    It pulls and it does not push, which is the one asymmetry that makes a rope
    a rope. A chain is a run of small bodies each tied to the next -- there is
    no rope object here, which is why a chain hangs in a curve and can be cut
    anywhere along its length.
    """
    world: banjo.World = _live(_world(args.get("world_id")))
    try:
        joint = world.tie(
            str(args.get("a", "")), str(args.get("b", "")),
            _triple(args.get("at_a_m"), "at_a_m", -200.0, 200.0),
            _triple(args.get("at_b_m"), "at_b_m", -200.0, 200.0),
            _number(args.get("length_m", 0.0), "length_m", 0.0, 100.0),
            _number(args.get("breaks_at_n", 0.0), "breaks_at_n", 0.0, 1e9))
    except banjo.BanjoError as error:
        raise Refused(str(error))
    return {"joint": joint,
            "note": f"{args.get('b')} is tied to {args.get('a')}. The rope pulls "
                    "and cannot push, so it does nothing at all while there is "
                    "slack. Read tension_n from `joints` to see what it carries."}


def tool_reeve(args: dict[str, Any]) -> dict[str, Any]:
    """Reeve a rope from one named thing, over two fixed points, to another.

    A hoist: pull one end down and the other comes up. This is the ideal
    pulley -- a relationship between cable lengths, with no wheel and no rope
    wrapping. `tie` is the physical alternative if the rope itself matters.
    """
    world: banjo.World = _live(_world(args.get("world_id")))
    try:
        joint = world.reeve(
            str(args.get("a", "")), str(args.get("b", "")),
            _triple(args.get("at_a_m"), "at_a_m", -200.0, 200.0),
            _triple(args.get("at_b_m"), "at_b_m", -200.0, 200.0),
            _triple(args.get("over_a_m"), "over_a_m", -200.0, 200.0),
            _triple(args.get("over_b_m"), "over_b_m", -200.0, 200.0),
            _number(args.get("ratio", 1.0), "ratio", 0.001, 100.0),
            _number(args.get("length_m", 0.0), "length_m", 0.0, 500.0))
    except banjo.BanjoError as error:
        raise Refused(str(error))
    ratio = float(args.get("ratio", 1.0))
    return {"joint": joint,
            "note": f"{args.get('a')} and {args.get('b')} are rove together. Pull "
                    f"one end down and the other comes up. The advantage is on "
                    f"{args.get('b')}'s side: it moves {1 / ratio:.3g} times as "
                    f"far and feels {ratio:g} times the tension, so a "
                    f"counterweight of load/{ratio:g} balances a load hung there."}


def tool_overloaded(args: dict[str, Any]) -> dict[str, Any]:
    """Everything carrying more than it can hold up."""
    world: banjo.World = _live(_world(args.get("world_id")))
    sagging = world.overloaded()
    # The survey runs as the world runs. Asked of a world just opened -- which
    # every add_object makes it -- it has never looked, and "nothing is
    # overloaded" is an answer about nothing. A model asked that three times,
    # piled on more iron each time, and finally moved the piers until the shelf
    # fell off them.
    if not sagging and world.time_s < 0.5:
        return {"overloaded": [],
                "note": f"this world has run for only {world.time_s:.2f} s since it was "
                        f"last opened: nothing has settled onto what carries it yet, and "
                        f"the load survey runs as the world runs. Call run for a second "
                        f"or two, then ask again."}
    return {"overloaded": [
                {"object": load.name,
                 "carrying_n": round(load.carrying_n, 1),
                 "span_m": round(load.span_m, 3),
                 "stress_mpa": round(load.stress_pa / 1e6, 3),
                 "holds_mpa": round(load.strength_pa / 1e6, 3)}
                for load in sagging],
            "note": "nothing struck these -- they are carrying too much standing "
                    "still. Break one with `drop`-style fracture and it comes "
                    "apart under its own load; the threshold is necessary and "
                    "not sufficient, as everywhere else here."
                    if sagging else "nothing is carrying more than it can hold"}


def tool_fix(args: dict[str, Any]) -> dict[str, Any]:
    """Fix one named thing to another: a peg, a bracket, a catch, a locking bar."""
    world: banjo.World = _live(_world(args.get("world_id")))
    try:
        joint = world.fix(
            str(args.get("a", "")), str(args.get("b", "")),
            _triple(args.get("at_m"), "at_m", -200.0, 200.0),
            _triple(args.get("axis", [0.0, 1.0, 0.0]), "axis", -1e6, 1e6),
            _number(args.get("holds_tension_n", 0.0), "holds_tension_n", 0.0, 1e9),
            _number(args.get("holds_shear_n", 0.0), "holds_shear_n", 0.0, 1e9))
    except banjo.BanjoError as error:
        raise Refused(str(error))
    return {"joint": joint,
            "note": f"{args.get('b')} and {args.get('a')} are now one piece. "
                    "Release it with `unhinge` -- that is what a latch is, and "
                    "doing it changes what the assembly can do."}


def tool_spring(args: dict[str, Any]) -> dict[str, Any]:
    """Put an elastic element between two named things: a bow limb, a spring."""
    world: banjo.World = _live(_world(args.get("world_id")))
    try:
        joint = world.spring(
            str(args.get("a", "")), str(args.get("b", "")),
            _triple(args.get("at_a_m"), "at_a_m", -200.0, 200.0),
            _triple(args.get("at_b_m"), "at_b_m", -200.0, 200.0),
            _number(args.get("rest_m", 0.0), "rest_m", 0.0, 100.0),
            _number(args.get("stiffness_n_m", 1000.0), "stiffness_n_m", 0.001, 1e9),
            _number(args.get("damping_n_s_m", 0.0), "damping_n_s_m", 0.0, 1e9))
    except banjo.BanjoError as error:
        raise Refused(str(error))
    return {"joint": joint,
            "note": "an ideal linear spring: force is stiffness times extension "
                    "and stored energy is half that times the extension again. "
                    "Read stored_j from `joints` to see what it is holding -- "
                    "and anything you throw with it gets its speed from that, "
                    "not from a number you choose."}


def tool_joints(args: dict[str, Any]) -> dict[str, Any]:
    """Every pin in the world, and where each has turned to.

    `a` and `b` do change. A pin whose wood is smashed follows the piece it ends
    up inside, so a gate hung on "post" can find itself hung on "post piece 3" --
    and `attached` goes false when there is nothing left to hold it, which is a
    gate coming off its hinges.
    """
    entry = _world(args.get("world_id"))
    if entry.get("world") is None:
        return {"joints": [], "note": "the world is empty"}
    # The ids a caller was given, not the engine's. A rebuild hangs every joint
    # again and the engine numbers them afresh, so the engine's id for the gate's
    # hinge is not the one the caller was told -- and "unhinge joint 3" would
    # take out whatever happened to be made third this time.
    stable = {r["live"]: r["id"] for r in entry.get("joints", [])}
    pins = entry["world"].joints()
    said_now = []
    for pin in pins:
        said = _said(pin)
        said["joint"] = stable.get(pin.id, pin.id)
        said_now.append(said)
    return {"joints": said_now,
            "note": "nothing here is animated: a joint is a constraint, and what "
                    "is on it moves when something pushes it or when gravity does"
                    if pins else "there are no joints in this world"}


def tool_unhinge(args: dict[str, Any]) -> dict[str, Any]:
    """Take a pin out. What was hanging on it falls."""
    entry = _world(args.get("world_id"))
    world: banjo.World = _live(entry)
    joint = int(_number(args.get("joint", 0), "joint", 1, 1e9))
    record = next((r for r in entry.get("joints", []) if r["id"] == joint), None)
    try:
        world.unhinge(record["live"] if record is not None else joint)
    except banjo.BanjoError as error:
        raise Refused(str(error))
    # Out of the record too: a pin taken out is not one to hang again at the
    # next rebuild.
    if record is not None:
        entry["joints"].remove(record)
    return {"joint": joint, "note": "the pin is out; what hung on it is falling"}


def tool_hinge_friction(args: dict[str, Any]) -> dict[str, Any]:
    """How hard a joint is to move.

    Newton metres for a pin, newtons for a slide -- so a grate that has to hold
    itself up wants friction of the order of its own weight, which is thousands
    of newtons, while a door hinge wants tens of newton metres. One bound, wide
    enough for both, rather than a number that silently refuses a portcullis.
    """
    entry = _world(args.get("world_id"))
    world: banjo.World = _live(entry)
    joint = int(_number(args.get("joint", 0), "joint", 1, 1e9))
    friction = _number(args.get("friction_n_m", args.get("friction_n", 0.0)),
                       "friction_n_m", 0.0, 1e9)
    record = next((r for r in entry.get("joints", []) if r["id"] == joint), None)
    try:
        world.joint_friction(record["live"] if record is not None else joint, friction)
    except banjo.BanjoError as error:
        raise Refused(str(error))
    # And kept, so the next rebuild hangs it as stiff as it was left.
    if record is not None:
        key = "friction_n" if record["tool"] == "slide" else "friction_n_m"
        record["args"][key] = friction
    return {"joint": joint, "friction": friction}


def tool_close_world(args: dict[str, Any]) -> dict[str, Any]:
    world_id = str(args.get("world_id"))
    entry = _world(world_id)
    entry["world"].close()
    WORLDS.pop(world_id, None)
    return {"closed": world_id, "still_open": list(WORLDS)}


VECTOR = {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3}
OBJECT_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "What to call it, like 'glass ball'."},
        "shape": {"type": "string", "enum": ["box", "sphere"]},
        "material": {"type": "string", "enum": MATERIALS},
        "size_m": dict(VECTOR, description="Width, height, depth in metres. A sphere "
                                           "uses the first as its diameter. Rounded to "
                                           "a whole number of cells."),
        "position_m": dict(VECTOR, description="Its centre. y is up, the floor is y=0, "
                                               "so a thing resting on the floor has its "
                                               "centre at half its own height."),
        "velocity_m_s": dict(VECTOR, description="How fast it is already going. Leave "
                                                 "it out to place it at rest."),
        "anchored": {"type": "boolean", "description": "True makes it scenery: it does "
                                                       "not move and cannot break."},
    },
    "required": ["shape", "material", "size_m"],
}

TOOLS = [
    {"name": "list_materials",
     "description": "The eight materials this engine has and what each one actually "
                    "does -- which bend before breaking, which are brittle, which "
                    "bounce, and the measured speeds. Read this before designing an "
                    "experiment.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "create_world",
     "description": "Build a world out of real matter and return its id. The floor is "
                    "a plane at y = 0 and gravity is on. Objects rest ON the floor, so "
                    "an object's centre sits at half its own height.",
     "inputSchema": {"type": "object", "required": ["objects"], "properties": {
         "objects": {"type": "array", "items": OBJECT_SCHEMA},
         "cell_size_m": {"type": "number", "description":
             "How finely matter is divided. This is the most expensive number here: "
             "halving it costs about sixteen times as much. 0.02 is the usual answer "
             "and is also the thinnest an object can be."}}}},
    {"name": "run",
     "description": "Let time pass and say what happened: every break, every dent, and "
                    "the hardest contacts with the speeds they would have needed. This "
                    "handles the break conversation itself. Use it after building a "
                    "world or changing one.",
     "inputSchema": {"type": "object", "required": ["world_id"], "properties": {
         "world_id": {"type": "string"},
         "seconds": {"type": "number", "description":
             f"How much world time to simulate, up to {MAX_RUN_S:.0f}."}}}},
    {"name": "drop",
     "description": "The common experiment: put a new object a given distance above a "
                    "point, let it fall onto whatever is there, and report what "
                    "happened. The height is measured from what it lands ON, not from "
                    "the floor.",
     "inputSchema": {"type": "object", "required": ["world_id", "object", "fall_m"],
                     "properties": {
         "world_id": {"type": "string"},
         "object": OBJECT_SCHEMA,
         "fall_m": {"type": "number", "description":
             "How far it falls. A fall of h metres arrives at sqrt(2*9.81*h) m/s."},
         "over_m": dict(VECTOR, description="Where to drop it, as [x, y, z]. Only x "
                                            "and z are used; y is worked out.")}}},
    {"name": "describe_world",
     "description": "Every object in a world, where it is, how fast it is going, and "
                    "what has happened to it so far.",
     "inputSchema": {"type": "object", "required": ["world_id"],
                     "properties": {"world_id": {"type": "string"}}}},
    {"name": "add_object",
     "description": "Put another object into a world. The world is opened again from "
                    "its scene, so anything in flight starts over; every joint is "
                    "hung again. Names must be different: joints and every later "
                    "call find things by name.",
     "inputSchema": {"type": "object", "required": ["world_id", "object"], "properties": {
         "world_id": {"type": "string"}, "object": OBJECT_SCHEMA}}},
    {"name": "remove_object",
     "description": "Take an object out of a world. Like add_object, the world is "
                    "opened again from its scene, so anything in flight starts over. "
                    "Any joint that held it goes with it, and is listed.",
     "inputSchema": {"type": "object", "required": ["world_id", "name"], "properties": {
         "world_id": {"type": "string"}, "name": {"type": "string"}}}},
    {"name": "move_object",
     "description": "Put an object somewhere else, at rest. This EDITS the world -- "
                    "the object is simply somewhere else, as if it had been built "
                    "there -- and is not the same as pushing it: to move something "
                    "by force, use pick_up, place and let_go. An object held by a "
                    "joint cannot be moved this way, because a joint is made at "
                    "fixed points; unhinge it first, or put things where they belong "
                    "before joining them.",
     "inputSchema": {"type": "object", "required": ["world_id", "name", "position_m"],
                     "properties": {
         "world_id": {"type": "string"}, "name": {"type": "string"},
         "position_m": dict(VECTOR, description="Its new centre, in metres.")}}},
    {"name": "clear_world",
     "description": "Take everything out of a world, joints and all, to build it "
                    "again from nothing. The world stays open under the same id; "
                    "add_object puts the first thing back.",
     "inputSchema": {"type": "object", "required": ["world_id"],
                     "properties": {"world_id": {"type": "string"}}}},
    {"name": "pick_up",
     "description": "Take hold of something already in the world, so it can be "
                    "moved. While held it goes exactly where it is put and "
                    "gravity does not act on it, but it still pushes what it "
                    "runs into. Anchored scenery refuses.",
     "inputSchema": {"type": "object", "required": ["world_id", "name"],
                     "properties": {"world_id": {"type": "string"},
                                    "name": {"type": "string"}}}},
    {"name": "place",
     "description": "Move what is in the hand to a point, without letting go.",
     "inputSchema": {"type": "object", "required": ["world_id", "to_m"],
                     "properties": {"world_id": {"type": "string"},
                                    "to_m": {"type": "array", "items": {"type": "number"},
                                             "minItems": 3, "maxItems": 3}}}},
    {"name": "let_go",
     "description": "Let go of what is held. It falls from where it was left, "
                    "and whatever breaks on the way is settled and reported.",
     "inputSchema": {"type": "object", "required": ["world_id"],
                     "properties": {"world_id": {"type": "string"}}}},
    {"name": "collect",
     "description": "Sweep up the loose pieces near a point and say what they "
                    "were made of, by material and by weight. This is where raw "
                    "materials come from, and it is also how a world that has "
                    "shattered keeps working -- past a couple of thousand bodies "
                    "the room quietly stops being able to break anything.",
     "inputSchema": {"type": "object", "required": ["world_id", "near_m"],
                     "properties": {"world_id": {"type": "string"},
                                    "near_m": {"type": "array", "items": {"type": "number"},
                                               "minItems": 3, "maxItems": 3},
                                    "radius_m": {"type": "number",
                                                 "description": "How far the sweep "
                                                                "reaches. 1.5 m by default."}}}},
    {"name": "carried",
     "description": "What has been swept up in this world, by material.",
     "inputSchema": {"type": "object", "required": ["world_id"],
                     "properties": {"world_id": {"type": "string"}}}},
    {"name": "hinge",
     "description": "Hang one named thing off another on a pin, so it turns "
                    "about that pin instead of being loose. A door, a gate, a "
                    "hatch, a lever, a drawbridge. The pin is given where it is "
                    "in the world right now and is kept in both bodies' own "
                    "frames, so the mechanism goes on working if the assembly is "
                    "moved or turned over. Either end may be anchored scenery -- "
                    "a door on a wall is the ordinary case -- but not both. "
                    "Nothing is animated: to open it, push something into it.",
     "inputSchema": {"type": "object",
                     "required": ["world_id", "a", "b", "at_m"],
                     "properties": {
         "world_id": {"type": "string"},
         "a": {"type": "string", "description": "What it hangs FROM, usually the "
                                                "anchored side."},
         "b": {"type": "string", "description": "What swings."},
         "at_m": dict(VECTOR, description="Where the pin is, in world metres."),
         "axis": dict(VECTOR, description="Which way the pin runs. [0,1,0] for a "
                                          "door, [1,0,0] or [0,0,1] for a hatch "
                                          "or a drawbridge. Vertical by default."),
         "lower_deg": {"type": "number",
                       "description": "How far it may turn one way from where it "
                                      "is hung: -180 to 0. Use 0 for a door that "
                                      "only opens outward."},
         "upper_deg": {"type": "number",
                       "description": "How far the other way: 0 to 180."},
         "friction_n_m": {"type": "number",
                          "description": "What it takes to start it turning, in "
                                         "newton metres. Zero swings freely; a "
                                         "stiff hinge holds a door where it is "
                                         "left instead of rocking for ever."}}}},
    {"name": "slide",
     "description": "Let one named thing slide along a line fixed in another, so "
                    "it moves along that line and nothing else. A portcullis in "
                    "its grooves, a sliding door, a locking bolt. Nothing is "
                    "animated: a grate hauled up and let go FALLS, because "
                    "gravity is still acting on a body free to move down its own "
                    "axis, and it stops on whatever happens to be under it. Give "
                    "it friction if it should stay where it is put -- size that "
                    "against the weight it holds, which for 1.5 x 1.8 x 0.1 m of "
                    "iron is 20.8 kN.",
     "inputSchema": {"type": "object",
                     "required": ["world_id", "a", "b", "at_m"],
                     "properties": {
         "world_id": {"type": "string"},
         "a": {"type": "string", "description": "What it slides IN, usually the "
                                                "anchored side."},
         "b": {"type": "string", "description": "What moves."},
         "at_m": dict(VECTOR, description="Where the travel is measured from, in "
                                          "world metres: where the thing is now."),
         "axis": dict(VECTOR, description="Which way it may move. [0,1,0] for a "
                                          "portcullis. Vertical by default."),
         "lower_m": {"type": "number",
                     "description": "How far it may go the other way, in metres: "
                                    "zero or less. Use 0 for a grate resting on "
                                    "the ground that can only go up."},
         "upper_m": {"type": "number",
                     "description": "How far it may go along the axis: zero or "
                                    "more."},
         "friction_n": {"type": "number",
                        "description": "What it takes to start it moving, in "
                                       "newtons."}}}},
    {"name": "tie",
     "description": "Tie one named thing to another with a rope: they may be up "
                    "to `length_m` apart and no further. A rope PULLS and does "
                    "not PUSH -- below its length it does nothing at all, so "
                    "slack is really slack. Build a chain or a rope by putting a "
                    "run of small bodies in the world and tying each to the "
                    "next; there is no rope object, which is why a chain hangs "
                    "in a curve, drapes over what it touches, and can be cut "
                    "anywhere along its length with `unhinge`. Give it "
                    "`breaks_at_n` and it can be overloaded.",
     "inputSchema": {"type": "object",
                     "required": ["world_id", "a", "b", "at_a_m", "at_b_m"],
                     "properties": {
         "world_id": {"type": "string"},
         "a": {"type": "string", "description": "One end, usually the anchored side."},
         "b": {"type": "string", "description": "The other end."},
         "at_a_m": dict(VECTOR, description="Where it is tied on `a`, in world metres."),
         "at_b_m": dict(VECTOR, description="Where it is tied on `b`."),
         "length_m": {"type": "number",
                      "description": "How far apart they may get. 0 means 'as "
                                     "they stand': the distance between the two "
                                     "points given, which is what you want for a "
                                     "rope already laid out."},
         "breaks_at_n": {"type": "number",
                         "description": "What it takes to part it, in newtons. 0 "
                                        "never parts. A 200 mm iron cube weighs "
                                        "618 N, so size it against the load."}}}},
    {"name": "reeve",
     "description": "Reeve a rope from one named thing, over two fixed points, "
                    "to another: a HOIST. Pull one end down and the other comes "
                    "up, because the rope's length cannot change. This is the "
                    "IDEAL pulley -- a relationship between cable lengths, with "
                    "no wheel (so no wheel inertia or bearing friction) and no "
                    "rope wrapping (so it cannot slip or come off). Use `tie` "
                    "instead when the rope itself is what matters: a run of "
                    "bodies draped over something has real wrap and real "
                    "friction, at a body per segment. IMPORTANT: `ratio` applies "
                    "to B's run, so b moves 1/ratio as far as a and feels ratio "
                    "times the tension -- hang the LOAD at b and a counterweight "
                    "of load/ratio balances it. The load at `a` needs ratio "
                    "TIMES the weight, which is the same machine backwards.",
     "inputSchema": {"type": "object",
                     "required": ["world_id", "a", "b", "at_a_m", "at_b_m",
                                  "over_a_m", "over_b_m"],
                     "properties": {
         "world_id": {"type": "string"},
         "a": {"type": "string", "description": "One end. No advantage here."},
         "b": {"type": "string", "description": "The other end, where the "
                                                "mechanical advantage is."},
         "at_a_m": dict(VECTOR, description="Where the rope is made off on `a`."),
         "at_b_m": dict(VECTOR, description="Where it is made off on `b`."),
         "over_a_m": dict(VECTOR, description="The sheave above `a`. A fixed "
                                              "point in the world."),
         "over_b_m": dict(VECTOR, description="The sheave above `b`."),
         "ratio": {"type": "number",
                   "description": "Mechanical advantage on b's side. 1 is a "
                                  "plain redirect, 2 is a block and tackle."},
         "length_m": {"type": "number",
                      "description": "How long the rope is. 0 means 'as it is "
                                     "rove': what the two runs add up to now."}}}},
    {"name": "overloaded",
     "description": "Everything in the world carrying more than its material can "
                    "take, worked out from statics rather than from impacts. "
                    "This is the ONLY way a loaded shelf is ever noticed: a "
                    "thing at rest under a pile reports no contacts at all, so "
                    "nothing strikes it and nothing else would ever ask. Says "
                    "what it is carrying, how far apart its supports are, and "
                    "the bending stress against what the material holds.",
     "inputSchema": {"type": "object", "required": ["world_id"],
                     "properties": {"world_id": {"type": "string"}}}},
    {"name": "fix",
     "description": "Fix one named thing to another so they move as ONE PIECE: a "
                    "peg, a bracket, a nail, a door catch, a locking bar, a rope "
                    "anchor. All six degrees of freedom are held, and whatever "
                    "their relative pose is now is the pose they keep. Give it "
                    "strengths and it can fail: tension is along `axis` (pulling "
                    "the peg out) and shear is across it (a weight hanging on a "
                    "bracket), and they are separate because they fail at "
                    "different loads. Zero means a weld that never lets go on "
                    "its own. Release it with `unhinge` -- that is what a LATCH "
                    "is, and releasing one changes what the assembly can do.",
     "inputSchema": {"type": "object",
                     "required": ["world_id", "a", "b", "at_m"],
                     "properties": {
         "world_id": {"type": "string"},
         "a": {"type": "string"},
         "b": {"type": "string"},
         "at_m": dict(VECTOR, description="Where the fixing is, in world metres."),
         "axis": dict(VECTOR, description="The direction the peg points. Tension "
                                          "is along it, shear across it."),
         "holds_tension_n": {"type": "number",
                             "description": "What it takes to pull it apart "
                                            "along the axis, in newtons. 0 never "
                                            "lets go."},
         "holds_shear_n": {"type": "number",
                           "description": "What it takes to shear it across the "
                                          "axis. A 200 mm iron cube hanging on a "
                                          "bracket is 618 N of pure shear."}}}},
    {"name": "spring",
     "description": "Put an elastic element between two named things: a BOW LIMB, "
                    "a spring, a bent plank -- anything that stores energy by "
                    "being deformed and gives it back. A declared simplified "
                    "model: an ideal linear spring, force = stiffness x "
                    "extension, stored energy = half stiffness x extension "
                    "squared. It has no mass, no yield and no hysteresis. It "
                    "PUSHES as well as pulls, which is what tells it from a rope "
                    "(`tie`). Draw it and `joints` reports stored_j; whatever it "
                    "throws takes its speed from that energy and its own mass, "
                    "so changing the stiffness, the draw or the mass changes the "
                    "result.",
     "inputSchema": {"type": "object",
                     "required": ["world_id", "a", "b", "at_a_m", "at_b_m"],
                     "properties": {
         "world_id": {"type": "string"},
         "a": {"type": "string"},
         "b": {"type": "string"},
         "at_a_m": dict(VECTOR, description="Where it attaches on `a`, in world "
                                            "metres. A point, not a centre."),
         "at_b_m": dict(VECTOR, description="Where it attaches on `b`."),
         "rest_m": {"type": "number",
                    "description": "The length at which it stores nothing. 0 "
                                   "means 'as it stands'."},
         "stiffness_n_m": {"type": "number",
                           "description": "Newtons per metre. A 4 kN/m limb "
                                          "drawn 250 mm holds 125 J."},
         "damping_n_s_m": {"type": "number",
                           "description": "The declared loss, in newton seconds "
                                          "per metre. 0 gives 96% of the stored "
                                          "energy back as motion."}}}},
    {"name": "joints",
     "description": "Every pin in the world and where each has turned to. The two "
                    "names a pin holds can change -- a pin whose wood is smashed "
                    "follows the piece it ends up inside -- and it reports itself "
                    "unattached when there is nothing left to hold it, which is a "
                    "gate coming off its hinges.",
     "inputSchema": {"type": "object", "required": ["world_id"],
                     "properties": {"world_id": {"type": "string"}}}},
    {"name": "hinge_friction",
     "description": "Change how hard a joint is to move: newton metres for a pin, "
                    "newtons for a slide.",
     "inputSchema": {"type": "object", "required": ["world_id", "joint", "friction_n_m"],
                     "properties": {"world_id": {"type": "string"},
                                    "joint": {"type": "integer"},
                                    "friction_n_m": {"type": "number"}}}},
    {"name": "unhinge",
     "description": "Take a joint out. What it was holding up falls.",
     "inputSchema": {"type": "object", "required": ["world_id", "joint"],
                     "properties": {"world_id": {"type": "string"},
                                    "joint": {"type": "integer"}}}},
    {"name": "cast_ray",
     "description": "What a ray meets first, against the shapes the solver really "
                    "collides. Use it to ask what is above or below something, or what "
                    "is in the way. Costs nothing and changes nothing.",
     "inputSchema": {"type": "object", "required": ["world_id", "from_m", "direction"],
                     "properties": {
         "world_id": {"type": "string"}, "from_m": VECTOR, "direction": VECTOR,
         "max_m": {"type": "number"}}}},
    {"name": "close_world",
     "description": "Close a world and free it. Each open world is a physics engine "
                    "with its scene resident in it.",
     "inputSchema": {"type": "object", "required": ["world_id"],
                     "properties": {"world_id": {"type": "string"}}}},
]

# ---------------------------------------------------------------------------
# What a new joint is likely to get wrong, said at the call
# ---------------------------------------------------------------------------
#
# Each of these is a mechanism that is perfectly legal and does not work, and
# each one was built by a model that then described it as working:
#
#   a gate leaf standing on the floor -- held there by friction, it turned 0.3
#   degrees when shoved;
#   a leaf set between its posts touching both -- jammed against its own frame;
#   a rope pulling a gate on an upright hinge straight up, made off at the hinge
#   line -- no leverage at all, and the gate did not move while the wheel that
#   was meant to open it turned ninety degrees.
#
# None is refused: a caller may mean it. They come back as `warnings` with the
# reason, which is what a model needs in order to fix it on the next call.


def _box(entry: dict[str, Any], name: str) -> dict[str, Any] | None:
    return next((b for b in entry["scene"]["bodies"] if b["name"] == name), None)


def _unit3(v: Any) -> list[float]:
    n = math.sqrt(sum(float(x) * float(x) for x in v)) or 1.0
    return [float(x) / n for x in v]


def _faces_touching(one: dict[str, Any], two: dict[str, Any], slack: float) -> bool:
    """Do two boxes meet over an AREA -- overlapping on two axes and touching or
    overlapping on the third? A shared edge or corner is not rubbing; a shared
    face is."""
    overlaps = touches = 0
    for axis in range(3):
        a0 = one["center_m"][axis] - one["dimensions_m"][axis] / 2
        a1 = one["center_m"][axis] + one["dimensions_m"][axis] / 2
        b0 = two["center_m"][axis] - two["dimensions_m"][axis] / 2
        b1 = two["center_m"][axis] + two["dimensions_m"][axis] / 2
        depth = min(a1, b1) - max(a0, b0)
        if depth > slack:
            overlaps += 1
        elif depth > -slack:
            touches += 1
        else:
            return False
    return overlaps >= 2


def _hinge_of(entry: dict[str, Any], name: str) -> dict[str, Any] | None:
    return next((r for r in entry.get("joints", [])
                 if r["tool"] == "hinge" and r["args"].get("b") == name), None)


def _leverage_warnings(entry: dict[str, Any], name: str, made_off: Any,
                       pulling_towards: Any, what: str) -> list[str]:
    """A rope or rod pulling on something that turns on a hinge: can it turn it?"""
    hinge = _hinge_of(entry, name)
    if hinge is None:
        return []
    axis = _unit3(hinge["args"].get("axis", [0, 1, 0]))
    pin = [float(v) for v in hinge["args"].get("at_m", [0, 0, 0])]
    at = [float(v) for v in made_off]
    pull = _unit3([float(b) - float(a) for a, b in zip(at, pulling_towards)])
    said = []
    if abs(sum(p * q for p, q in zip(pull, axis))) > 0.8:
        said.append(f"this {what} pulls {name} along the axis of its hinge, and a pull "
                    f"along a hinge's axis cannot turn it. A gate on an upright hinge "
                    f"is swung by pulling SIDEWAYS on it -- a stiff spring from the "
                    f"wheel as a connecting rod, or a rope to a pulley beside the gate "
                    f"rather than above it.")
    offset = [a - p for a, p in zip(at, pin)]
    along = sum(o * q for o, q in zip(offset, axis))
    arm = math.sqrt(max(0.0, sum(o * o for o in offset) - along * along))
    if arm < 0.1:
        said.append(f"this {what} is made off {arm:.2f} m from the line {name} turns "
                    f"about, where a pull has almost no leverage. Make it off near "
                    f"{name}'s far edge.")
    return said


def _joint_warnings(entry: dict[str, Any], tool: str, args: dict[str, Any]) -> list[str]:
    cell = float(entry.get("cell_m", 0.02))
    said: list[str] = []
    if tool == "hinge":
        leaf = _box(entry, str(args.get("b", "")))
        axis = _unit3(args.get("axis", [0, 1, 0]))
        if leaf is not None and abs(axis[1]) > 0.7:
            low = leaf["center_m"][1] - leaf["dimensions_m"][1] / 2
            if low < 0.5 * cell:
                said.append(f"{leaf['name']} stands on the floor, and a leaf on the ground "
                            f"is held there by friction and will not swing. Raise it one "
                            f"cell, so its bottom is {cell:g} m up.")
        if leaf is not None:
            for other in entry["scene"]["bodies"]:
                if other is leaf or not _faces_touching(leaf, other, 0.25 * cell):
                    continue
                said.append(f"{leaf['name']} is up against {other['name']} face to face, "
                            f"so it will rub on it and may not turn freely. Leave a cell's "
                            f"gap between them -- a gate hangs in FRONT of its posts, not "
                            f"squeezed between them -- unless {other['name']} is meant to "
                            f"be one piece with it, in which case fix it to it.")
    if tool in ("reeve", "tie", "spring"):
        towards_b = args.get("over_b_m") if tool == "reeve" else args.get("at_a_m")
        towards_a = args.get("over_a_m") if tool == "reeve" else args.get("at_b_m")
        what = {"reeve": "rope", "tie": "rope", "spring": "rod"}[tool]
        if args.get("at_b_m") is not None and towards_b is not None:
            said += _leverage_warnings(entry, str(args.get("b", "")), args["at_b_m"],
                                       towards_b, what)
        if args.get("at_a_m") is not None and towards_a is not None:
            said += _leverage_warnings(entry, str(args.get("a", "")), args["at_a_m"],
                                       towards_a, what)
    return said


# The calls that make joints, unwrapped: what a rebuild uses to hang a
# recorded joint again on a fresh world.
MAKE_JOINT = {"hinge": tool_hinge, "slide": tool_slide, "tie": tool_tie,
              "reeve": tool_reeve, "fix": tool_fix, "spring": tool_spring}


def _recorded(tool_name: str):
    """The joining tool, keeping the call that made the joint.

    So that it survives a rebuild (see _rebuild), and so that the caller's id
    for it survives too: the engine numbers joints afresh in every world it
    opens, and a caller holding "joint 3" should still be holding the same pin.
    """
    make = MAKE_JOINT[tool_name]

    def record(args: dict[str, Any]) -> dict[str, Any]:
        entry = _world(args.get("world_id"))
        answer = make(args)
        made = {"id": entry.get("next_joint", 1), "tool": tool_name,
                "live": answer["joint"],
                "args": {k: v for k, v in args.items() if k != "world_id"}}
        entry["next_joint"] = made["id"] + 1
        entry.setdefault("joints", []).append(made)
        check = entry.get("check")
        if check is not None:
            try:
                check(entry["scene"], entry["joints"])
            except ValueError as problem:
                entry["joints"].remove(made)
                entry["world"].unhinge(made["live"])
                raise Refused(str(problem)) from None
        answer = {**answer, "joint": made["id"]}
        warnings = _joint_warnings(entry, tool_name, made["args"])
        if warnings:
            answer["warnings"] = warnings
        return answer

    record.__name__ = make.__name__
    record.__doc__ = make.__doc__
    return record


HANDLERS = {
    "list_materials": tool_list_materials,
    "create_world": tool_create_world,
    "run": tool_run,
    "drop": tool_drop,
    "describe_world": tool_describe_world,
    "add_object": tool_add_object,
    "remove_object": tool_remove_object,
    "move_object": tool_move_object,
    "clear_world": tool_clear_world,
    "pick_up": tool_pick_up,
    "place": tool_place,
    "let_go": tool_let_go,
    "collect": tool_collect,
    "carried": tool_carried,
    "hinge": _recorded("hinge"),
    "slide": _recorded("slide"),
    "tie": _recorded("tie"),
    "reeve": _recorded("reeve"),
    "fix": _recorded("fix"),
    "spring": _recorded("spring"),
    "overloaded": tool_overloaded,
    "joints": tool_joints,
    "hinge_friction": tool_hinge_friction,
    "unhinge": tool_unhinge,
    "cast_ray": tool_cast_ray,
    "close_world": tool_close_world,
}


# ---------------------------------------------------------------------------
# The protocol
# ---------------------------------------------------------------------------

def json_safe(value: Any) -> Any:
    """The same answer, with every number one JSON can carry.

    Infinity means something here and turns up honestly: a brittle material has
    no speed at which it bends, so its bending threshold IS infinite. But JSON
    has no way to write that, and Python refuses outright rather than inventing
    one -- so a perfectly correct answer about glass would come back as a crash.
    Nulled here, once, rather than guarded at each of the places a number is put
    into an answer, because that list only ever grows.
    """
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    return value


def handle(message: dict[str, Any]) -> dict[str, Any] | None:
    """One request in, one reply out. None for a notification, which gets none."""
    method = message.get("method", "")
    request_id = message.get("id")
    params = message.get("params") or {}

    def ok(result: Any) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    if method == "initialize":
        return ok({"protocolVersion": PROTOCOL_VERSION,
                   "capabilities": {"tools": {}},
                   "serverInfo": SERVER,
                   "instructions":
                       "Banjo simulates matter: objects are cells joined by bonds that "
                       "carry tension and compression, yield, and fail. Call "
                       "list_materials first -- what a thing is made of decides what "
                       "happens to it, and the numbers are not the ones you would "
                       "guess. Build with create_world, then run or drop. Never say "
                       "something broke unless a tool reported that it did."})
    if method in ("notifications/initialized", "notifications/cancelled"):
        return None
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": TOOLS})
    if method == "resources/list":
        return ok({"resources": []})
    if method == "prompts/list":
        return ok({"prompts": []})
    if method == "tools/call":
        name = params.get("name", "")
        handler = HANDLERS.get(name)
        if handler is None:
            return ok({"content": [{"type": "text",
                                    "text": f"There is no tool called {name!r}."}],
                       "isError": True})
        try:
            answer = handler(params.get("arguments") or {})
            text = json.dumps(json_safe(answer), indent=1, allow_nan=False)
        except Refused as refusal:
            # Something the caller can fix. Handed back as a result rather than
            # an error so the model reads it and tries again, which is the whole
            # point of saying what was wrong in words.
            return ok({"content": [{"type": "text", "text": str(refusal)}],
                       "isError": True})
        except Exception as failure:  # noqa: BLE001 - the boundary
            print(traceback.format_exc(), file=sys.stderr, flush=True)
            return ok({"content": [{"type": "text",
                                    "text": f"The engine failed: {failure}"}],
                       "isError": True})
        return ok({"content": [{"type": "text", "text": text}]})

    return {"jsonrpc": "2.0", "id": request_id,
            "error": {"code": -32601, "message": f"unknown method {method!r}"}}


def serve(stdin=None, stdout=None) -> None:
    source = stdin if stdin is not None else sys.stdin
    sink = stdout if stdout is not None else sys.stdout
    for line in source:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        reply = handle(message)
        if reply is None:
            continue
        sink.write(json.dumps(reply, allow_nan=False) + "\n")
        sink.flush()


def main() -> int:
    try:
        banjo.library()
    except banjo.BanjoError as error:
        print(f"banjo: {error}", file=sys.stderr, flush=True)
        print("Build the banjo_c target or set BANJO_LIBRARY to the library's path.",
              file=sys.stderr, flush=True)
        return 1
    try:
        serve()
    except KeyboardInterrupt:
        pass
    finally:
        for entry in WORLDS.values():
            try:
                entry["world"].close()
            except Exception:
                pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
