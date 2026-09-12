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
                        # What has been swept up here, by material. Kept on the
                        # world because that is what it is a property of: the
                        # matter came out of this room and not another.
                        "carried": {}}
    return {"world_id": world_id, "cell_size_m": cell_m, "objects": _describe(world),
            "next": "Call run to let time pass. The floor is a plane at y = 0 and "
                    "gravity is on."}


def tool_describe_world(args: dict[str, Any]) -> dict[str, Any]:
    entry = _world(args.get("world_id"))
    return {"world_id": args.get("world_id"),
            "time_s": round(entry["world"].time_s, 3),
            "objects": _describe(entry["world"]),
            "what_has_happened": entry["story"][-20:]}


def tool_run(args: dict[str, Any]) -> dict[str, Any]:
    """Let time pass, settling whatever wants to break, and say what happened."""
    import time as clock
    entry = _world(args.get("world_id"))
    world: banjo.World = entry["world"]
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
    entry = _world(args.get("world_id"))
    world: banjo.World = entry["world"]
    fall = _number(args.get("fall_m", 2.0), "fall_m", 0.05, 40.0)
    over = _triple(args.get("over_m") or [0, 0, 0], "over_m", -50.0, 50.0)
    # What is under that point, and how far down, so the thing is placed to fall
    # exactly `fall_m` onto it rather than `fall_m` above the floor.
    found = world.pick([over[0], 40.0, over[2]], [0, -1, 0])
    top = 40.0 - found.distance_m if found.hit else 0.0
    item = dict(args.get("object") or {})
    size = _triple(item.get("size_m") or [0.1, 0.1, 0.1], "size_m", 0.005, 4.0)
    item["position_m"] = [over[0], top + size[1] / 2.0 + fall, over[2]]
    item.setdefault("name", f"{item.get('material', 'glass')} "
                            f"{'ball' if item.get('shape') == 'sphere' else 'block'}")
    scene = dict(entry["scene"])
    scene["bodies"] = list(entry["scene"]["bodies"]) + \
        _scene([item], entry["cell_m"])["bodies"]
    # A world is opened from a scene and that is the set of bodies it has, so
    # adding one means opening it again. Everything in flight starts over.
    try:
        fresh = banjo.World(scene, cell_size_m=entry["cell_m"])
    except banjo.BanjoError as error:
        raise Refused(str(error))
    entry["world"].close()
    entry["world"] = fresh
    entry["scene"] = scene
    entry["story"].append(f"dropped {item['name']} {fall:.2f} m onto "
                          f"{found.name or 'the floor'}")
    # Long enough to land from that height, and then some to settle.
    answer = tool_run({"world_id": args.get("world_id"),
                       "seconds": math.sqrt(2 * fall / 9.81) + 1.5})
    answer["dropped"] = {"object": item["name"], "fall_m": round(fall, 3),
                         "onto": found.name or "the floor"}
    return answer


def tool_pick_up(args: dict[str, Any]) -> dict[str, Any]:
    """Take hold of something that is already in the world.

    Until now the only way to put an object somewhere was to drop a NEW one from
    above, which meant a model could add to a scene but never rearrange it.
    """
    entry = _world(args.get("world_id"))
    world: banjo.World = entry["world"]
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
    world: banjo.World = entry["world"]
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
    world: banjo.World = entry["world"]
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
    world: banjo.World = entry["world"]
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


def tool_add_object(args: dict[str, Any]) -> dict[str, Any]:
    entry = _world(args.get("world_id"))
    scene = dict(entry["scene"])
    scene["bodies"] = list(entry["scene"]["bodies"]) + \
        _scene([args.get("object") or {}], entry["cell_m"])["bodies"]
    try:
        fresh = banjo.World(scene, cell_size_m=entry["cell_m"])
    except banjo.BanjoError as error:
        raise Refused(str(error))
    entry["world"].close()
    entry["world"], entry["scene"] = fresh, scene
    return {"added": scene["bodies"][-1]["name"], "objects": _describe(fresh),
            "note": "A world is opened from a scene, so adding an object opens it "
                    "again from the start. Anything that was in flight is back where "
                    "it was authored."}


def tool_remove_object(args: dict[str, Any]) -> dict[str, Any]:
    entry = _world(args.get("world_id"))
    name = str(args.get("name", ""))
    kept = [b for b in entry["scene"]["bodies"] if b["name"] != name]
    if len(kept) == len(entry["scene"]["bodies"]):
        raise Refused(f"there is nothing called {name!r} in this world")
    if not kept:
        raise Refused("that would empty the world, and a world needs something in it")
    scene = dict(entry["scene"], bodies=kept)
    fresh = banjo.World(scene, cell_size_m=entry["cell_m"])
    entry["world"].close()
    entry["world"], entry["scene"] = fresh, scene
    return {"removed": name, "objects": _describe(fresh)}


def tool_cast_ray(args: dict[str, Any]) -> dict[str, Any]:
    entry = _world(args.get("world_id"))
    found = entry["world"].pick(_triple(args.get("from_m"), "from_m", -200.0, 200.0),
                                _triple(args.get("direction"), "direction", -1e6, 1e6),
                                _number(args.get("max_m", 100.0), "max_m", 0.001, 500.0))
    if not found.hit:
        return {"hit": False, "note": "the ray reached its length without meeting anything"}
    return {"hit": True, "object": found.name or None,
            "is_the_floor": not found.name,
            "distance_m": round(found.distance_m, 4),
            "point_m": [round(v, 4) for v in found.point_m]}


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
                    "its scene, so anything in flight starts over.",
     "inputSchema": {"type": "object", "required": ["world_id", "object"], "properties": {
         "world_id": {"type": "string"}, "object": OBJECT_SCHEMA}}},
    {"name": "remove_object",
     "description": "Take an object out of a world. Like add_object, the world is "
                    "opened again from its scene, so anything in flight starts over.",
     "inputSchema": {"type": "object", "required": ["world_id", "name"], "properties": {
         "world_id": {"type": "string"}, "name": {"type": "string"}}}},
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

HANDLERS = {
    "list_materials": tool_list_materials,
    "create_world": tool_create_world,
    "run": tool_run,
    "drop": tool_drop,
    "describe_world": tool_describe_world,
    "add_object": tool_add_object,
    "remove_object": tool_remove_object,
    "pick_up": tool_pick_up,
    "place": tool_place,
    "let_go": tool_let_go,
    "collect": tool_collect,
    "carried": tool_carried,
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
