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
        body = {"name": name, "shape": shape, "material": material,
                "dimensions_m": size, "center_m": centre, "velocity_m_s": speed,
                "anchored": bool(item.get("anchored"))}
        # What it contains and how hot it starts. Left out, a body is made of
        # what its material is made of -- which for oak is dry wood, moisture
        # and ash, and is the whole reason an oak log can burn.
        if item.get("contents") is not None:
            contents = item["contents"]
            if not isinstance(contents, dict) or not contents:
                raise Refused(f"{name}: contents are substances and mass fractions, like "
                              f"{{\"dry wood\": 0.8, \"moisture\": 0.2}}. list_substances "
                              f"says what there is.")
            body["contents"] = {str(k): _number(v, f"{name}: contents {k}", 0.0, 1000.0)
                                for k, v in contents.items()}
        if item.get("temperature_k") is not None:
            body["temperature_k"] = _number(item["temperature_k"], f"{name}: temperature_k",
                                            1.0, 3000.0)
        bodies.append(body)
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
    said = {"world_id": args.get("world_id"),
            "time_s": round(world.time_s, 3) if world is not None else 0.0,
            "objects": _describe(world) if world is not None else [],
            "joints": len(entry.get("joints", [])),
            "what_has_happened": entry["story"][-20:]}
    if _has_terrain(entry):
        report = world.environment_report()
        said["ground"] = _ground_said(report)
        said["water"] = _water_said(world, full=True)
    else:
        said["ground"] = "flat, at y = 0"
    return said


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
    heat = _heat_said(world, limit=10)
    if heat is not None:
        answer["heat"] = heat
    if _has_terrain(entry):
        water = _water_said(world)
        if water is not None:
            answer["water"] = water
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
    held = world.held
    world.move_held(to)
    # A loose thing is CARRIED: it is wherever it is put, and one step shows the
    # world where. A thing on a joint is HAULED -- pulled towards the hand with
    # what the hand has, 800 N -- and one step of that is 1/240 of a second of a
    # pull, which moves nothing. A model placed a winch handle a quarter turn
    # round, let go, read the wheel at 0.0 degrees and reported that the winch
    # did not work; the same winch, pulled for a second, lifts its gate 0.30 m.
    # So a hauled thing is pulled until it stops coming, or for a second.
    hauled = any(held in (r["args"].get("a"), r["args"].get("b"))
                 for r in entry.get("joints", []))
    steps, last, still = 0, None, 0
    while True:
        world.step(1.0 / 240.0)
        steps += 1
        if not hauled or steps >= 240:
            break
        body = world.body(held)
        here = list(body.position_m) if body else None
        if here is not None and last is not None:
            moved = math.sqrt(sum((a - b) ** 2 for a, b in zip(here, last)))
            still = still + 1 if moved < 1e-4 else 0
            if still >= 24:
                break
        last = here
    body = world.body(held)
    got = [round(v, 3) for v in body.position_m] if body else None
    entry["story"].append(f"moved {held} to [{to[0]:.2f}, {to[1]:.2f}, {to[2]:.2f}]")
    answer: dict[str, Any] = {"holding": held, "asked_for_m": [round(v, 3) for v in to],
                              "got_to_m": got}
    if hauled:
        answer["pulled_for_s"] = round(steps / 240.0, 3)
        answer["note"] = ("it is on a joint, so the hand PULLED it -- with at most "
                          "800 N -- rather than carrying it. got_to_m is as far as "
                          "that took it; read joints to see what moved.")
    return answer


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
    old = entry.get("world")
    if scene["bodies"]:
        # The water, carried: a world opened again from an edited scene holds
        # the same water it held, over whatever ground the edits leave -- a
        # reservoir filled behind a dam is still there when a log is added.
        # Not across a change of ground: a new valley is new water.
        opening = scene
        was = (entry["scene"].get("terrain") or {}).get("generate")
        now = (scene.get("terrain") or {}).get("generate")
        if old is not None and now is not None and was == now:
            try:
                state = old.environment_state()
            except banjo.BanjoError:
                state = {}
            if state.get("depth_b64"):
                opening = dict(scene, water=dict(scene.get("water") or {}, state=state))
        try:
            fresh = banjo.World(opening, cell_size_m=entry["cell_m"])
        except banjo.BanjoError as error:
            raise Refused(str(error))
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
    # And the edges, on the bodies now standing there (see tool_blade). One
    # that will not go on is dropped and said, like a joint.
    blades = list(scene.get("blades") or [])
    if blades:
        if fresh is None:
            lost += [f"the edge on {b['body']}: the world is empty" for b in blades]
            entry["scene"] = {k: v for k, v in scene.items() if k != "blades"}
        else:
            armed, dropped = _arm_blades(fresh, blades)
            lost += dropped
            if dropped:
                entry["scene"] = dict(scene, blades=armed)
    return lost


def _held_by(entry: dict[str, Any], name: str) -> list[dict[str, Any]]:
    return [r for r in entry.get("joints", [])
            if name in (r["args"].get("a"), r["args"].get("b"))]


def tool_add_object(args: dict[str, Any]) -> dict[str, Any]:
    world_id = str(args.get("world_id"))
    entry = _world(world_id)
    item = dict(args.get("object") or {})
    # position_m belongs inside the object, but a model often puts it beside
    # the object instead. What was meant is plain, so it is taken from there
    # -- measured, the refusal it used to get sent the model round in circles.
    if item.get("position_m") is None and args.get("position_m") is not None:
        item["position_m"] = args["position_m"]
    label = f"{str(item.get('name') or 'the object')[:60]}: position_m"
    where = item.get("position_m")
    if not isinstance(where, (list, tuple)) or len(where) not in (2, 3):
        raise Refused(f"{label} is {'missing' if where is None else str(where)[:60]}. Give "
                      f"it inside object: [x, z] sets the thing down on whatever is under "
                      f"that point, [x, y, z] puts its centre exactly there.")
    # [x, z] is "put it down there": its height is worked out below, once its
    # size is known, from what is under that point. [x, y, z] is exactly there.
    set_down = len(where) == 2
    if set_down:
        item["position_m"] = [_number(where[0], label, -50.0, 50.0), 0.0,
                              _number(where[1], label, -50.0, 50.0)]
    added = _scene([item], entry["cell_m"])["bodies"][0]
    # Names are how every joint and every later call finds a thing, so a second
    # "oak gate" is refused rather than quietly shadowing the first.
    if any(b["name"] == added["name"] for b in entry["scene"]["bodies"]):
        raise Refused(f"there is already something called {added['name']!r} here. "
                      f"Joints and every later call find things by name, so give it "
                      f"another one.")
    # On ground that is not flat, something asked for inside the ground is set
    # on top of it instead: the ground under a thing is the one height a caller
    # cannot work out for itself, and a body started inside a hill is thrown
    # out of it.
    rests = _set_down(entry, added) if set_down else None
    seated = None if set_down else _seat_on_ground(entry, added)
    held_up = None if set_down else _held_up(entry, added)
    scene = dict(entry["scene"], bodies=list(entry["scene"]["bodies"]) + [added])
    lost = _rebuild(entry, scene, world_id)
    answer: dict[str, Any] = {
        "added": added["name"], "objects": _describe(entry["world"]),
        "joints": len(entry["joints"]),
        "note": "A world is opened from a scene, so adding an object opens it again "
                "from the start: anything in flight is back where it was authored, "
                "and every joint is hung again."}
    if rests:
        answer["set_down"] = rests
    if seated:
        answer["seated_on_the_ground"] = seated
    if held_up:
        answer["in_the_air"] = held_up
    if _has_terrain(entry):
        here = entry["world"].survey(added["center_m"][0], added["center_m"][2])
        if here.get("water"):
            answer["in_water"] = {"depth_m": round(here["water"]["depth_m"], 3),
                                  "surface_m": round(here["water"]["surface_m"], 3),
                                  "flowing_m_s": round(here["water"]["speed_m_s"], 3),
                                  "note": "it is in the water: say so, unless that was asked for"}
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
    # A heater aimed at it, and a gas region that pushed on it, go with it --
    # said, like the joints, rather than left to refuse the next rebuild.
    block = _thermo_block(entry)
    regions = [r for r in block.get("gas_regions", [])
               if name in (r.get("piston"), r.get("container"))]
    gone = {r["name"] for r in regions}
    heaters = [h for h in block.get("heaters", [])
               if h.get("target") == name or h.get("target") in gone]
    block["gas_regions"] = [r for r in block.get("gas_regions", []) if r not in regions]
    block["heaters"] = [h for h in block.get("heaters", []) if h not in heaters]
    # And an edge on it.
    edges = [b for b in entry["scene"].get("blades") or [] if b.get("body") == name]
    scene = _with_thermo(dict(entry["scene"], bodies=kept,
                              blades=[b for b in entry["scene"].get("blades") or []
                                      if b.get("body") != name]), block)
    lost = _rebuild(entry, scene, world_id, joints)
    answer: dict[str, Any] = {"removed": name, "objects": _describe(entry["world"])}
    if held:
        answer["joints_removed_with_it"] = [_joint_words(r) for r in held]
    if edges:
        answer["edge_removed_with_it"] = f"the edge on {name}"
    if regions or heaters:
        answer["heat_removed_with_it"] = ([f"gas region {r['name']}" for r in regions] +
                                          [f"heater on {h['target']}" for h in heaters])
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
    scene = dict(entry["scene"], bodies=[])
    scene.pop("thermo", None)
    scene.pop("blades", None)
    entry["scene"] = scene
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


# ---------------------------------------------------------------------------
# Heat, chemistry and gas
# ---------------------------------------------------------------------------
#
# Declared in the scene document -- "contents" on a body, gas regions and heaters
# in a "thermo" block beside the bodies -- so a rebuild carries them the way it
# carries everything else authored, and the playground's room gets them in the
# spec it is opened from. What happens then is the engine's thermochemical
# network: nothing here sets a temperature, a burn time or a speed.

def _thermo_block(entry: dict[str, Any]) -> dict[str, Any]:
    block = dict(entry["scene"].get("thermo") or {})
    block["gas_regions"] = list(block.get("gas_regions") or [])
    block["heaters"] = list(block.get("heaters") or [])
    return block


def _with_thermo(scene: dict[str, Any], block: dict[str, Any]) -> dict[str, Any]:
    scene = dict(scene)
    kept = {k: v for k, v in block.items() if v}
    if kept:
        scene["thermo"] = kept
    else:
        scene.pop("thermo", None)
    return scene


def _heat_said(world: banjo.World, limit: int = 0) -> dict[str, Any] | None:
    """What is hot, what is burning, what the gas is doing -- or None if nothing."""
    report = world.thermo_report()
    ambient = (report.get("ambient") or {}).get("temperature_k", 293.15)
    bodies = []
    for b in sorted(report.get("bodies") or [],
                    key=lambda b: (not b["reacting"], -abs(b["temperature_k"] - ambient))):
        if not (b["reacting"] or b["heater_w"] > 0 or abs(b["temperature_k"] - ambient) > 1.0):
            continue
        said: dict[str, Any] = {"object": b["name"],
                                "surface_k": round(b["temperature_k"], 1),
                                "core_k": round(b["core_temperature_k"], 1),
                                "burning": bool(b["reacting"] and b["heat_release_w"] > 0)}
        # Drying takes heat rather than giving it: said as drying, because a
        # negative "heat release" reads as a fire going backwards.
        if b["reacting"] and b["heat_release_w"] >= 0.0:
            said["heat_release_kw"] = round(b["heat_release_w"] / 1000.0, 2)
        elif b["reacting"]:
            said["drying_kw"] = round(-b["heat_release_w"] / 1000.0, 2)
        if b["fuel_kg"] > 0:
            said["fuel_left_kg"] = round(b["fuel_kg"], 3)
        if b["reacting"] and b.get("remaining_s"):
            said["would_last_min_at_this_rate"] = round(b["remaining_s"] / 60.0, 1)
        if b["heater_w"] > 0:
            said["being_heated_kw"] = round(b["heater_w"] / 1000.0, 2)
        bodies.append(said)
    if limit:
        bodies = bodies[:limit]
    gas = []
    for r in report.get("regions") or []:
        said = {"name": r["name"], "temperature_k": round(r["temperature_k"], 1),
                "pressure_kpa": round(r["pressure_pa"] / 1000.0, 2),
                "volume_litres": round(r["volume_m3"] * 1000.0, 2)}
        if r.get("piston"):
            said.update({"piston": r["piston"], "pushed_it_m": round(r["stroke_m"], 4),
                         "force_on_it_n": round(r["force_n"], 1),
                         "work_done_on_bodies_j": round(r["work_to_bodies_j"], 2)})
        if r["heater_w"] > 0:
            said["being_heated_kw"] = round(r["heater_w"] / 1000.0, 2)
        gas.append(said)
    if not bodies and not gas:
        return None
    ledger = report.get("ledger") or {}
    return {"bodies": bodies, "gas": gas,
            "energy": {"heat_put_in_kj": round(ledger.get("heater_in_j", 0.0) / 1000.0, 2),
                       "heat_lost_to_surroundings_kj":
                           round(ledger.get("heat_to_surroundings_j", 0.0) / 1000.0, 2),
                       "unaccounted_j": ledger.get("residual_j", 0.0)}}


def tool_list_substances(_args: dict[str, Any]) -> dict[str, Any]:
    """What matter is made of, what reacts with what, and where the numbers came from."""
    everything = banjo.thermo_model()
    model = everything["model"]
    return {
        "substances": [{"name": s["id"], "phase": s["phase"],
                        "numbers_are": s["provenance"], "note": s["note"]}
                       for s in model["substances"]],
        "reactions": [{"name": r["id"], "version": r["version"], "numbers_are": r["provenance"],
                       "what_it_is": r["description"],
                       "uses": {t["substance"]: f"{t['kg_per_kg']:g} kg, from {t['from']}"
                                for t in r["reactants"]},
                       "makes": {t["substance"]: f"{t['kg_per_kg']:g} kg, {t['goes']}"
                                 for t in r["products"]},
                       "releases_mj_per_kg": round(r["heat_released_j_per_kg_at_298k"] / 1e6, 3),
                       "not_below_k": r["rate"]["minimum_temperature_k"]}
                      for r in model["reactions"]],
        "what_materials_are_made_of": model["compositions"],
        "not_modelled": everything.get("limitations", []),
        "note": "Burning is a result, not a property. A log burns because it contains dry "
                "wood and is hot enough, with air around it; how long it lasts is its fuel "
                "over the rate it burns, and that rate is the model's answer.",
    }


def tool_enclose_gas(args: dict[str, Any]) -> dict[str, Any]:
    """Fill a space with gas that pushes on a body: a cylinder under a piston."""
    world_id = str(args.get("world_id"))
    entry = _world(world_id)
    name = str(args.get("name") or "gas").strip()[:60]
    bodies = {b["name"]: b for b in entry["scene"]["bodies"]}
    block = _thermo_block(entry)
    if name in bodies or any(r["name"] == name for r in block["gas_regions"]):
        raise Refused(f"there is already something called {name!r} here; give the gas another name")
    region: dict[str, Any] = {"name": name}
    contents = args.get("contents") or {"argon": 1.0}
    if not isinstance(contents, dict):
        raise Refused("contents are gases and mass fractions, like {\"argon\": 1}")
    region["contents"] = {str(k): _number(v, f"contents {k}", 0.0, 1000.0) for k, v in contents.items()}
    piston = str(args.get("piston") or "")
    if piston:
        if piston not in bodies:
            raise Refused(f"there is nothing called {piston!r} for the gas to push on")
        if bodies[piston].get("anchored"):
            raise Refused(f"{piston} is anchored, so the gas could never move it")
        region["piston"] = piston
    if args.get("height_m") is not None:
        region["height_m"] = _number(args["height_m"], "height_m", 0.01, 20.0)
    elif args.get("volume_m3") is not None:
        region["volume_m3"] = _number(args["volume_m3"], "volume_m3", 1e-6, 100.0)
    else:
        raise Refused("say how tall the column of gas under the piston is (height_m), or its "
                      "volume (volume_m3)")
    if args.get("pressure_pa") is not None:
        region["pressure_pa"] = _number(args["pressure_pa"], "pressure_pa", 100.0, 1.0e8)
    elif piston:
        region["balance"] = True
    else:
        raise Refused("a gas with nothing to push on needs a pressure (pressure_pa)")
    if args.get("temperature_k") is not None:
        region["temperature_k"] = _number(args["temperature_k"], "temperature_k", 1.0, 3000.0)
    if args.get("axis") is not None:
        region["axis"] = _triple(args["axis"], "axis", -1e6, 1e6)
    for key, low, high in (("area_m2", 1e-6, 100.0), ("wall_conductance_w_k", 0.0, 1e6),
                           ("vent_area_m2", 0.0, 10.0)):
        if args.get(key) is not None:
            region[key] = _number(args[key], key, low, high)
    block["gas_regions"].append(region)
    lost = _rebuild(entry, _with_thermo(entry["scene"], block), world_id)
    entry["story"].append(f"filled {name} with gas" + (f" under {piston}" if piston else ""))
    answer: dict[str, Any] = {"gas_region": name, "heat": _heat_said(entry["world"]),
                              "note": "The world was opened again with the gas in it. Its "
                                      "temperature and pressure are worked out from what it "
                                      "holds and the space it has; heat it (`heat`) and it "
                                      "pushes harder, lets it cool and what it holds up comes "
                                      "back down."}
    if lost:
        answer["joints_lost"] = lost
    return answer


def tool_heat(args: dict[str, Any]) -> dict[str, Any]:
    """Put heat into a body or a gas region, from outside: kindling, a torch, a stove."""
    world_id = str(args.get("world_id"))
    entry = _world(world_id)
    target = str(args.get("target") or "")
    block = _thermo_block(entry)
    known = {b["name"] for b in entry["scene"]["bodies"]} | {r["name"] for r in block["gas_regions"]}
    if target not in known:
        raise Refused(f"there is nothing called {target!r} to heat. Heat a body by its name, or "
                      f"a gas region made with enclose_gas.")
    power = _number(args.get("power_w", 10000.0), "power_w", 1.0, 200000.0)
    seconds = _number(args.get("seconds", 60.0), "seconds", 0.1, 3600.0)
    start = _number(args.get("start_s", 0.0), "start_s", 0.0, 3600.0)
    block["heaters"].append({"target": target, "power_w": power, "seconds": seconds,
                             "start_s": start, "label": str(args.get("label") or "heater")[:40]})
    lost = _rebuild(entry, _with_thermo(entry["scene"], block), world_id)
    entry["story"].append(f"heating {target} at {power / 1000:g} kW for {seconds:g} s")
    answer: dict[str, Any] = {
        "heating": target, "power_w": power, "seconds": seconds, "from_s": start,
        "note": "The world was opened again with this heat in it, from when the world starts. "
                "Call run to see what it does -- it lights something only if it delivers "
                "enough, and thermal_state says how hot everything is."}
    if lost:
        answer["joints_lost"] = lost
    return answer


def tool_thermal_state(args: dict[str, Any]) -> dict[str, Any]:
    """How hot everything is, what is burning, what the gas is doing, and the ledger."""
    entry = _world(args.get("world_id"))
    world: banjo.World = _live(entry)
    said = _heat_said(world) or {"bodies": [], "gas": []}
    energy = world.energy()
    said["energy"] = {
        "stored_mj": round(energy.stored_j / 1e6, 4),
        "of_which_chemical_mj": round(energy.chemical_j / 1e6, 4),
        "of_which_thermal_mj": round(energy.thermal_j / 1e6, 4),
        "heat_put_in_kj": round(energy.heater_in_j / 1000.0, 3),
        "heat_lost_to_surroundings_kj": round(energy.heat_to_surroundings_j / 1000.0, 3),
        "carried_in_by_air_kj": round(energy.matter_in_j / 1000.0, 3),
        "carried_out_by_smoke_and_steam_kj": round(energy.matter_out_j / 1000.0, 3),
        "work_done_on_bodies_j": round(energy.work_to_bodies_j, 3),
        "unaccounted_j": energy.residual_j,
    }
    said["time_s"] = round(world.time_s, 3)
    said["note"] = ("would_last_min_at_this_rate is the fuel left over the rate it is burning "
                    "NOW: an estimate under current conditions, not a burn time. Chemical and "
                    "thermal are two parts of one stored energy.")
    return said


# ---------------------------------------------------------------------------
# Blades (docs/cutting-model.md)
# ---------------------------------------------------------------------------
#
# An edge is declared on a body that already exists, like a pin, so it is kept
# the way a pin is kept: in the scene document, where a rebuild puts it back
# (_rebuild) and the playground's room is opened with it. In the BODY's own
# frame, because the body may have been run, knocked over or moved since it was
# built, and an edge written down in world metres would be left behind in
# mid-air when the world is opened again.

def _qmul(a: list[float], b: list[float]) -> list[float]:
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return [aw * bw - ax * bx - ay * by - az * bz, aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx, aw * bz + ax * by - ay * bx + az * bw]


def _qconj(q: list[float]) -> list[float]:
    return [q[0], -q[1], -q[2], -q[3]]


def _qrot(q: list[float], v: list[float]) -> list[float]:
    return _qmul(_qmul(q, [0.0] + [float(x) for x in v]), _qconj(q))[1:]


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
    size = math.sqrt(sum(x * x for x in q))
    return [x / size for x in q]


def _vdot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _vcross(a: list[float], b: list[float]) -> list[float]:
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def _vunit(v: list[float], what: str) -> list[float]:
    size = math.sqrt(_vdot(v, v))
    if not size > 1e-9:
        raise Refused(f"{what} has no direction")
    return [x / size for x in v]


def _to_body(body: banjo.Body, point: Any) -> list[float]:
    return _qrot(_qconj(list(body.orientation_wxyz)),
                 [float(p) - c for p, c in zip(point, body.position_m)])


def _from_body(body: banjo.Body, local: Any) -> list[float]:
    return [c + r for c, r in zip(body.position_m, _qrot(list(body.orientation_wxyz), local))]


def _blade_record(world: banjo.World, blade_id: int) -> dict[str, Any] | None:
    """A blade as its body carries it: what a rebuild and the room need."""
    blade = next((b for b in world.blades() if b.id == blade_id), None)
    body = world.body(blade.body) if blade is not None else None
    if blade is None or body is None:
        return None
    inverse = _qconj(list(body.orientation_wxyz))
    return {"body": blade.body,
            "heel_local_m": [round(v, 6) for v in _to_body(body, blade.heel_m)],
            "tip_local_m": [round(v, 6) for v in _to_body(body, blade.tip_m)],
            "facing_local": [round(v, 6) for v in _qrot(inverse, list(blade.facing))],
            "grip_local_m": [round(v, 6) for v in _to_body(body, blade.grip_m)],
            "thickness_m": blade.thickness_m, "edge_radius_m": blade.edge_radius_m,
            "bevel_deg": blade.bevel_deg}


def _arm_blades(world: banjo.World,
                blades: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """Put every kept edge back on its body, where that body is now."""
    kept: list[dict[str, Any]] = []
    lost: list[str] = []
    for record in blades:
        body = world.body(str(record.get("body", "")))
        if body is None:
            lost.append(f"the edge on {record.get('body')}: there is nothing called that now")
            continue
        try:
            world.blade(record["body"], _from_body(body, record["heel_local_m"]),
                        _from_body(body, record["tip_local_m"]),
                        _qrot(list(body.orientation_wxyz), record["facing_local"]),
                        float(record["thickness_m"]), float(record["edge_radius_m"]),
                        float(record["bevel_deg"]), _from_body(body, record["grip_local_m"]))
        except banjo.BanjoError as error:
            lost.append(f"the edge on {record['body']}: {error}")
            continue
        kept.append(record)
    return kept, lost


def _blade_axes(world: banjo.World, blade: banjo.Blade) -> tuple[list[float], list[float]]:
    """The edge's direction and the way it faces, in its body's own frame."""
    body = world.body(blade.body)
    if body is None:
        raise Refused(f"{blade.body} is not in the world")
    inverse = _qconj(list(body.orientation_wxyz))
    along = _vunit(_qrot(inverse, [t - h for t, h in zip(blade.tip_m, blade.heel_m)]), "the edge")
    faced = _qrot(inverse, list(blade.facing))
    return along, _vunit([f - _vdot(faced, along) * a for f, a in zip(faced, along)],
                         "the edge's facing")


def _turn_for(axes: tuple[list[float], list[float]], pointing: Any, edge_facing: Any) -> list[float]:
    """The orientation that points the blade along `pointing`, edge facing `edge_facing`."""
    along, facing = axes
    want_along = _vunit([float(v) for v in pointing], "pointing")
    wish = [float(v) for v in edge_facing]
    across = [w - _vdot(wish, want_along) * a for w, a in zip(wish, want_along)]
    if math.sqrt(_vdot(across, across)) < 1e-6:
        raise Refused("edge_facing must be across the blade, not along pointing: an edge faces "
                      "sideways from the line of the blade")
    want_facing = _vunit(across, "edge_facing")
    have = [along, facing, _vcross(along, facing)]
    want = [want_along, want_facing, _vcross(want_along, want_facing)]
    return _qfrom([[sum(want[k][r] * have[k][c] for k in range(3)) for c in range(3)]
                   for r in range(3)])


def _stance(world: banjo.World, blade: banjo.Blade, pointing: Any, edge_facing: Any) -> list[float]:
    return _turn_for(_blade_axes(world, blade), _triple(pointing, "pointing", -1e6, 1e6),
                     _triple(edge_facing, "edge_facing", -1e6, 1e6))


def _swing_round(entry: dict[str, Any], world: banjo.World, held: str,
                 args: dict[str, Any]) -> dict[str, Any]:
    """A swing through a point, round a shoulder (see tool_swing)."""
    import time as clock
    blade = next((b for b in world.blades() if b.body == held and b.attached), None)
    if blade is None:
        raise Refused(f"{held} has no edge to swing; give it one with `blade`")
    through = _triple(args.get("through_m"), "through_m", -50.0, 50.0)
    if args.get("pointing") is None or args.get("edge_facing") is None:
        raise Refused("a swing through a point needs pointing (which way the blade points: "
                      "through what is to be cut) and edge_facing (the way the edge moves)")
    pointing = _vunit(_triple(args["pointing"], "pointing", -1e6, 1e6), "pointing")
    wish = _triple(args["edge_facing"], "edge_facing", -1e6, 1e6)
    across = [w - _vdot(wish, pointing) * p for w, p in zip(wish, pointing)]
    if math.sqrt(_vdot(across, across)) < 1e-6:
        raise Refused("edge_facing must be across the blade, not along pointing")
    facing_way = _vunit(across, "edge_facing")
    seconds = _number(args.get("seconds", 0.13), "seconds", 0.05, 2.0)
    settle = _number(args.get("then_s", 1.0), "then_s", 0.0, 5.0)
    axes = _blade_axes(world, blade)
    body = world.body(held)
    grip_local = _to_body(body, blade.grip_m)
    to_middle = [(h + t) / 2.0 - g for h, t, g in zip(_to_body(body, blade.heel_m),
                                                       _to_body(body, blade.tip_m), grip_local)]
    to_point = [t - g for t, g in zip(_to_body(body, blade.tip_m), grip_local)]
    # Which way the swing goes: the way the edge faces, if it leads; the flat
    # leads when the edge faces up or down, and then the swing goes the way the
    # edge would have faced had it been turned to lead.
    going = facing_way if abs(_vdot(facing_way, [0.0, 1.0, 0.0])) < 0.7 else \
        _vunit(_vcross([0.0, 1.0, 0.0], pointing), "the swing's direction")
    around = _vunit(_vcross(pointing, going), "the swing's axis")

    def turned(v: list[float], angle: float) -> list[float]:
        c, s = math.cos(angle), math.sin(angle)
        k_cross = _vcross(around, v)
        k_dot = _vdot(around, v)
        return [v[i] * c + k_cross[i] * s + around[i] * k_dot * (1.0 - c) for i in range(3)]

    reach = _vdot(_qrot(_turn_for(axes, pointing, facing_way), to_middle), pointing)
    shoulder = [t - (0.5 + reach) * p for t, p in zip(through, pointing)]

    def pose(angle: float) -> tuple[list[float], list[float]]:
        out = turned(pointing, angle)
        turn = _turn_for(axes, out, turned(facing_way, angle))
        edge_at = [s + (0.5 + reach) * o for s, o in zip(shoulder, out)]
        return [e - r for e, r in zip(edge_at, _qrot(turn, to_middle))], turn

    wide = math.radians(50.0)
    ready, turn = pose(-wide)
    events: list[dict[str, Any]] = []
    world.forget_cuts()
    began = clock.perf_counter()

    def go(a: list[float], b: list[float], turn_to: list[float], s: float) -> list[float]:
        world.aim_held(turn_to)
        steps = max(1, int(round(s * 240.0)))
        for i in range(1, steps + 1):
            world.move_held([a[k] + (b[k] - a[k]) * i / steps for k in range(3)])
            _step_answering(world, events)
        return b

    def along(p: list[float]) -> float:
        return _vdot(p, pointing)

    def at_depth(p: list[float], depth: float) -> list[float]:
        return [x + (depth - along(p)) * q for x, q in zip(p, pointing)]

    # Up off whatever it rests on; back until the point is 0.15 m short of the
    # line it will swing through; round to the side; in; then the swing.
    start = list(blade.grip_m)
    here = go(start, [start[0], start[1] + 0.3, start[2]], turn, 0.5)
    clear = along(through) - 0.15 - _vdot(_qrot(turn, to_point), pointing)
    depth = min(along(here), clear)
    here = go(here, at_depth(here, depth), turn, 0.6)
    here = go(here, at_depth(ready, depth), turn, 0.6)
    here = go(here, ready, turn, 0.5)
    here = go(here, here, turn, 0.5)
    steps = max(1, int(round(seconds * 240.0)))
    for i in range(1, steps + 1):
        here, turn = pose(-wide + 2.0 * wide * i / steps)
        world.aim_held(turn)
        world.move_held(here)
        _step_answering(world, events)
    here = go(here, here, turn, settle)
    cuts = world.cuts()
    cut_through = [c for c in cuts if c.separated or c.links > 0]
    entry["story"].append(
        f"swung {held} through [{through[0]:.2f}, {through[1]:.2f}, {through[2]:.2f}]"
        + (": cut through " + ", ".join(sorted({c.target for c in cut_through}))
           if cut_through else ""))
    return {"swung": held, "through_m": through, "over_s": round(seconds, 3),
            "cuts": [_cut_said(cut) for cut in cuts] or "the edge met nothing on the way",
            "what_broke": events or None,
            "objects": _describe(world),
            "computing_took_s": round(clock.perf_counter() - began, 2)}


def _cut_said(cut: banjo.Cut) -> dict[str, Any]:
    """One meeting between an edge and something, in words a model can use."""
    said: dict[str, Any] = {
        "blade": cut.blade, "met": cut.target, "kind": cut.kind,
        "at_s": round(cut.at_s, 3),
        "speed_m_s": round(cut.speed_m_s, 2),
        "into_m_s": round(cut.into_m_s, 2),
        "along_edge_m_s": round(cut.along_m_s, 2),
        "across_flats_m_s": round(cut.across_m_s, 2),
        "still_touching": cut.open}
    if cut.kind in ("edge", "slice", "press", "glancing") and cut.resistance_j_m2 > 0.0:
        said.update({
            "resistance_j_m2": round(cut.resistance_j_m2, 1),
            "cut_mm2": round(cut.area_m2 * 1e6, 1),
            "work_j": round(cut.work_j, 3),
            "bonds_severed": cut.bonds,
            "rope_links_cut": cut.links,
            "came_apart": cut.separated,
            "pieces": cut.pieces})
    return said


def _blade_said(blade: banjo.Blade) -> dict[str, Any]:
    return {"blade": blade.id, "body": blade.body, "material": blade.material,
            "heel_m": [round(v, 4) for v in blade.heel_m],
            "tip_m": [round(v, 4) for v in blade.tip_m],
            "facing": [round(v, 4) for v in blade.facing],
            "grip_m": [round(v, 4) for v in blade.grip_m],
            "thickness_mm": round(blade.thickness_m * 1000.0, 2),
            "edge_radius_mm": round(blade.edge_radius_m * 1000.0, 4),
            "bevel_deg": round(blade.bevel_deg, 1),
            "cut_mm2": round(blade.cut_area_m2 * 1e6, 1),
            "cut_work_j": round(blade.cut_work_j, 3),
            "cutting": blade.cutting or None,
            "attached": blade.attached}


def tool_blade(args: dict[str, Any]) -> dict[str, Any]:
    """Give a body an edge. docs/cutting-model.md is the declared model."""
    world_id = str(args.get("world_id"))
    entry = _world(world_id)
    world: banjo.World = _live(entry)
    name = str(args.get("body", ""))
    heel = _triple(args.get("heel_m"), "heel_m", -200.0, 200.0)
    try:
        blade = world.blade(
            name, heel,
            _triple(args.get("tip_m"), "tip_m", -200.0, 200.0),
            _triple(args.get("facing"), "facing", -1e6, 1e6),
            _number(args.get("thickness_m", 0.01), "thickness_m", 0.0005, 0.5),
            _number(args.get("edge_radius_m", 0.0002), "edge_radius_m", 1e-6, 0.01),
            _number(args.get("bevel_deg", 30.0), "bevel_deg", 1.0, 179.0),
            _triple(args.get("grip_m") or heel, "grip_m", -200.0, 200.0))
    except banjo.BanjoError as error:
        raise Refused(str(error))
    # Kept with the body, so a rebuild puts it back and the room is opened with it.
    record = _blade_record(world, blade)
    if record is not None:
        scene = dict(entry["scene"], blades=list(entry["scene"].get("blades") or []) + [record])
        check = entry.get("check")
        if check is not None:
            try:
                check(scene, entry.get("joints", []))
            except ValueError as problem:
                # The world has the edge and the document must not: open it again
                # from the document as it was.
                _rebuild(entry, entry["scene"], world_id)
                raise Refused(str(problem)) from None
        entry["scene"] = scene
    entry["story"].append(f"gave {name} an edge")
    return {"blade": blade,
            "note": f"{name} has an edge. It cuts what it bites into with "
                    "the edge leading and pressed in, at a cost per square metre set by "
                    "the target's own material; its flat and its point are ordinary "
                    "contacts. Take hold of it with `wield` and move it with `swing`."}


def tool_blades(args: dict[str, Any]) -> dict[str, Any]:
    world: banjo.World = _live(_world(args.get("world_id")))
    blades = world.blades()
    return {"blades": [_blade_said(blade) for blade in blades],
            "note": "no body in this world has an edge" if not blades else
                    "cut_work_j is measured from the solver's own friction impulses; "
                    "cut_mm2 is the area that bought at each material's resistance"}


def tool_cuts(args: dict[str, Any]) -> dict[str, Any]:
    world: banjo.World = _live(_world(args.get("world_id")))
    cuts = world.cuts()
    return {"cuts": [_cut_said(cut) for cut in cuts],
            "note": "nothing has met an edge" if not cuts else
                    "every meeting is listed, including the ones that cut nothing and why"}


def tool_wield(args: dict[str, Any]) -> dict[str, Any]:
    """Take hold of a body the way a person holds a sword."""
    entry = _world(args.get("world_id"))
    world: banjo.World = _live(entry)
    name = str(args.get("name", ""))
    grip = args.get("grip_m")
    if grip is None:
        blade = next((b for b in world.blades() if b.body == name and b.attached), None)
        if blade is None:
            raise Refused(f"give grip_m, or give {name!r} an edge with `blade` first -- a "
                          f"blade knows where it is held")
        grip = list(blade.grip_m)
    grip = _triple(grip, "grip_m", -200.0, 200.0)
    try:
        world.wield(name, grip)
    except banjo.BanjoError as error:
        raise Refused(str(error))
    entry["story"].append(f"took hold of {name}")
    return {"wielding": name, "grip_m": [round(v, 4) for v in grip],
            "note": "held at the grip by a hand with a bounded force (800 N) and a "
                    "bounded torque (60 N m). Move it with `swing`: the hand pulls "
                    "towards where it is sent and what the blade meets can slow it, "
                    "turn it aside or stop it. `let_go` lets go."}


def _step_answering(world: banjo.World, events: list[dict[str, Any]]) -> None:
    """One step, settling anything that breaks on the way -- as `run` does."""
    if world.step(1.0 / 240.0) != banjo.BREAK_PENDING:
        return
    for name in world.breakable():
        pieces = world.fracture(name)
        if world.last_outcome == "broke":
            events.append({"what": "broke", "object": name, "into_pieces": pieces})


def tool_swing(args: dict[str, Any]) -> dict[str, Any]:
    """Move the hand along a straight line, turning if asked, and report the cuts."""
    import time as clock
    entry = _world(args.get("world_id"))
    world: banjo.World = _live(entry)
    held = world.held
    if not held:
        raise Refused("nothing is held. Call wield first.")
    if args.get("through_m") is not None:
        return _swing_round(entry, world, held, args)
    if args.get("to_m") is None:
        raise Refused("say where: through_m for a swing (the middle of the edge passes "
                      "through it), or to_m to move the grip in a straight line")
    to = _triple(args.get("to_m"), "to_m", -50.0, 50.0)
    seconds = _number(args.get("seconds", 0.25), "seconds", 0.02, 5.0)
    settle = _number(args.get("then_s", 1.0), "then_s", 0.0, 5.0)
    facing = args.get("facing_wxyz")
    blade = next((b for b in world.blades() if b.body == held and b.attached), None)
    pointing, edge_facing = args.get("pointing"), args.get("edge_facing")
    if (pointing is None) != (edge_facing is None):
        raise Refused("give pointing and edge_facing together: which way the blade points "
                      "from the grip, and which way its edge faces")
    if pointing is not None:
        if blade is None:
            raise Refused(f"{held} has no edge to aim; give it one with `blade`")
        facing = _stance(world, blade, pointing, edge_facing)
    if facing is not None:
        if not isinstance(facing, (list, tuple)) or len(facing) != 4:
            raise Refused("facing_wxyz must be a quaternion of four numbers, w first")
        world.aim_held([_number(v, "facing_wxyz", -1.0, 1.0) for v in facing])
    body = world.body(held)
    start = list(blade.grip_m) if blade else list(body.position_m if body else to)
    world.forget_cuts()
    events: list[dict[str, Any]] = []
    began = clock.perf_counter()
    steps = max(1, int(round(seconds * 240.0)))
    for i in range(1, steps + 1):
        part = i / steps
        world.move_held([start[k] + part * (to[k] - start[k]) for k in range(3)])
        _step_answering(world, events)
    for _ in range(int(round(settle * 240.0))):
        if clock.perf_counter() - began > MAX_WALL_S:
            break
        _step_answering(world, events)
    cuts = world.cuts()
    cut_through = [c for c in cuts if c.separated or c.links > 0]
    entry["story"].append(
        f"swung {held} to [{to[0]:.2f}, {to[1]:.2f}, {to[2]:.2f}]"
        + (": cut through " + ", ".join(sorted({c.target for c in cut_through}))
           if cut_through else ""))
    return {"swung": held, "to_m": to, "over_s": round(seconds, 3),
            "cuts": [_cut_said(cut) for cut in cuts] or
                    "the edge met nothing on the way",
            "what_broke": events or None,
            "objects": _describe(world),
            "computing_took_s": round(clock.perf_counter() - began, 2)}


# ---------------------------------------------------------------------------
# Terrain and water
# ---------------------------------------------------------------------------
#
# Declared in the scene document -- a "terrain" block with what the ground was
# made from and every edit made to it since, a "water" block with any change to
# its rivers -- so a rebuild makes the same ground again and the playground's
# room gets it in the spec it opens from. What the ground is and what the water
# does is the engine's: nothing here sets a level, a speed or a slope.

TERRAIN_KINDS = ["valley", "basin", "channel", "flat"]
GROUND_DENSITY = {"sand": 1600.0, "soil": 1600.0}
PAIR = {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 3,
        "description": "[x, z] on the ground (or [x, y, z], y ignored)."}


def _has_terrain(entry: dict[str, Any]) -> bool:
    return bool(entry["scene"].get("terrain")) and entry.get("world") is not None


def _require_terrain(entry: dict[str, Any]) -> banjo.World:
    world = _live(entry)
    if not entry["scene"].get("terrain"):
        raise Refused("this world has flat ground and no water. make_terrain gives it a valley "
                      "with a river in it.")
    return world


def _xz(value: Any, what: str) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) not in (2, 3):
        raise Refused(f"{what} is [x, z] on the ground, like [2.5, -1]")
    point = [_number(v, what, -500.0, 500.0) for v in value]
    return [point[0], point[-1]]


def _ground_under(world: banjo.World, x: float, z: float, half_x: float, half_z: float) -> float:
    """The highest ground under a footprint."""
    top = -1.0e9
    for a in range(5):
        for b in range(5):
            here = world.survey(x - half_x + half_x * a / 2.0, z - half_z + half_z * b / 2.0)
            if here.get("on_the_ground"):
                top = max(top, here["ground_m"])
    return top


def _seat_on_ground(entry: dict[str, Any], body: dict[str, Any]) -> dict[str, Any] | None:
    """Lift a body asked for inside the ground to rest on top of it."""
    if not _has_terrain(entry):
        return None
    size = body["dimensions_m"]
    half = [size[0] / 2.0] * 3 if body["shape"] == "sphere" else [v / 2.0 for v in size]
    x, y, z = body["center_m"]
    ground = _ground_under(entry["world"], x, z, half[0], half[2])
    if ground < -1.0e8 or y - half[1] >= ground + 0.002:
        return None
    rest = round(ground + half[1] + 0.003, 4)
    body["center_m"] = [x, rest, z]
    return {"asked_for_y_m": round(y, 4), "ground_m": round(ground, 4), "now_y_m": rest,
            "note": "it was inside the ground, so it now stands on the highest point of the "
                    "ground under it"}


SET_DOWN_FROM_M = 60.0   # looked down from: above anything a room holds


IN_THE_AIR_M = 0.05     # further than this above what is under it, a thing will fall


def _half_height(body: dict[str, Any]) -> float:
    size = body["dimensions_m"]
    return size[0] / 2.0 if body["shape"] == "sphere" else size[1] / 2.0


def _under_footprint(entry: dict[str, Any],
                     body: dict[str, Any]) -> tuple[float, str, int, int]:
    """The top of what is under a body, and what that is: another object, the
    ground or the floor. Found the way the engine sees the world -- straight
    down from above, over the body's footprint -- so it is what it would land on.

    A sphere touches only under its centre; a box anywhere under its bottom, so
    the highest thing under nine points across its footprint carries it.
    """
    size = body["dimensions_m"]
    half = [size[0] / 2.0] * 3 if body["shape"] == "sphere" else [v / 2.0 for v in size]
    x, _, z = body["center_m"]
    spots = [(0.0, 0.0)] if body["shape"] == "sphere" else [
        (half[0] * a, half[2] * b) for a in (-0.9, 0.0, 0.9) for b in (-0.9, 0.0, 0.9)]
    # What each point looks down on; a point that meets nothing is over the floor.
    heights: list[tuple[float, str]] = []
    world = entry.get("world")
    for dx, dz in spots:
        found = (world.pick([x + dx, SET_DOWN_FROM_M, z + dz], [0.0, -1.0, 0.0])
                 if world is not None else None)
        heights.append((SET_DOWN_FROM_M - found.distance_m, found.name)
                       if found is not None and found.hit else (0.0, ""))
    top, name = max(heights, key=lambda h: h[0])
    under = name or ("the ground" if _has_terrain(entry) else "the floor")
    # How many of the points are on that top: fewer than all, and the thing
    # hangs over its edge.
    carried = sum(1 for height, _ in heights if height >= top - 0.01)
    return top, under, carried, len(spots)


def _set_down(entry: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    """Rest a body on whatever is under it (_under_footprint), and say when only
    part of it is over that: measured, a model set three 0.4 m crates 0.2 m
    apart, and the second and third went half on the first's top."""
    top, under, carried, of = _under_footprint(entry, body)
    x, _, z = body["center_m"]
    body["center_m"] = [x, round(top + _half_height(body) + 0.002, 4), z]
    said: dict[str, Any] = {"on": under, "its_top_m": round(top, 4),
                            "centre_y_m": body["center_m"][1]}
    if carried < of:
        said["overhangs"] = {
            "points_on_it": f"{carried} of {of}",
            "note": f"only part of it is over {under}, and it may tip off. Side by side, "
                    f"two things' centres must be at least half of each one's width apart, "
                    f"added together."}
    return said


def _held_up(entry: dict[str, Any], body: dict[str, Any]) -> dict[str, Any] | None:
    """How far above what is under it a body given [x, y, z] starts -- said, so
    a caller that meant it to rest finds out it will fall. Measured, a model
    gave [x, z, 0] for [x, z]: three crates started 1.5 m up at the wrong place,
    and its reply said they were resting on the floor."""
    top, under, _, _ = _under_footprint(entry, body)
    gap = body["center_m"][1] - _half_height(body) - top
    if gap <= IN_THE_AIR_M:
        return None
    return {"above_m": round(gap, 3), "over": under,
            "note": "it starts that far above what is under it and will fall; to set it "
                    "down there instead, give position_m as [x, z]"}


def _river_said(path: list[dict[str, Any]], every: int = 2) -> list[list[float]]:
    """Where the river runs: [x, z, level, depth, speed] every few metres."""
    return [[round(p["x_m"], 2), round(p["z_m"], 2), round(p["level_m"], 3), round(p["depth_m"], 3),
             round(p["speed_m_s"], 2)] for p in path[::max(1, every)]]


def _water_said(world: banjo.World, full: bool = False) -> dict[str, Any] | None:
    """What the water is doing, in words a model can act on."""
    try:
        report = world.environment_report()
    except banjo.BanjoError:
        return None
    if not report:
        return None
    water = report["water"]
    said: dict[str, Any] = {
        "time_s": round(water["time_s"], 2),
        "volume_m3": round(water["volume_m3"], 3),
        "rivers": [{"name": r["name"], "fed_m3_s": round(r["discharge_m3_s"], 3)} for r in water["rivers"]],
        "coming_in_m3_s": round(water["inflow_m3_s"], 3),
        "going_out_m3_s": round(water["outflow_m3_s"], 3),
        "ponds": [{"name": p["name"], "at_m": [round(v, 2) for v in p["at_m"]],
                   "level_m": round(p["level_m"], 3) if p.get("level_m") is not None else None,
                   "brim_m": round(p["brim_m"], 3), "depth_now_m": round(p.get("depth_now_m", 0.0), 3)}
                  for p in water["ponds"]],
        # What the water holds up against what each thing weighs. A block
        # sealed on the river bed has no water under it and is held up by the
        # bed, not the water -- which is right, and is what makes it a dam.
        "in_the_water": [{"object": b["name"], "floats": b["floats"],
                          "water_lifts_n": round(b["buoyancy_n"], 1),
                          "weighs_n": round(b["weight_n"], 1)} for b in water["bodies_in_water"]],
    }
    if full:
        said["the_river_runs"] = {"columns": ["x_m", "z_m", "level_m", "depth_m", "speed_m_s"],
                                  "every_2_m": _river_said(water["river_path"], 1)}
        said["ledger"] = {"came_in_m3": round(water["ledger"]["inflow_m3"], 3),
                          "went_out_m3": round(water["ledger"]["outflow_m3"], 3),
                          "unaccounted_m3": water["residual_m3"]}
        said["costs"] = {"columns_computed": water["active_cells"], "of": water["cells"],
                         "wet": water["wet_cells"]}
    return said


def _ground_said(report: dict[str, Any]) -> dict[str, Any]:
    grid = report["grid"]
    ground = report["ground"]
    said = {"kind": report["kind"],
            "from_m": [round(grid["x0_m"], 2), round(grid["z0_m"], 2)],
            "to_m": [round(grid["x0_m"] + grid["size_m"][0], 2), round(grid["z0_m"] + grid["size_m"][1], 2)],
            "column_m": grid["cell_m"],
            "lowest_m": round(ground["lowest_m"], 3), "highest_m": round(ground["highest_m"], 3),
            "stand_here_to_look": [round(v, 2) for v in report["view"]["eye_m"]],
            "looking_at": [round(v, 2) for v in report["view"]["look_m"]]}
    if ground.get("bare_rock"):
        said["bare_level_rock_at_m"] = [round(v, 2) for v in ground["bare_rock"]["at_m"]]
    return said


def tool_make_terrain(args: dict[str, Any]) -> dict[str, Any]:
    """Give the world ground that is not flat -- a valley with a river -- or take it away."""
    world_id = str(args.get("world_id"))
    entry = _world(world_id)
    kind = str(args.get("kind") or "valley")
    scene = dict(entry["scene"])
    scene.pop("water", None)
    if kind == "none":
        scene.pop("terrain", None)
        lost = _rebuild(entry, scene, world_id)
        entry["story"].append("the ground was made flat again")
        return {"ground": "flat, at y = 0, with no water", "joints_lost": lost} if lost else \
               {"ground": "flat, at y = 0, with no water"}
    if kind not in TERRAIN_KINDS:
        raise Refused(f"kind is one of {', '.join(TERRAIN_KINDS)} or none, not {kind!r}")
    generate: Any = kind
    extra: dict[str, Any] = {}
    if args.get("seed") is not None:
        extra["seed"] = int(_number(args["seed"], "seed", 0, 1e9))
    if args.get("discharge_m3_s") is not None:
        extra["discharge_m3_s"] = _number(args["discharge_m3_s"], "discharge_m3_s", 0.0, 5.0)
    if extra:
        generate = {"kind": kind, **extra}
    scene["terrain"] = {"generate": generate}
    if not scene["bodies"]:
        raise Refused("a world is opened from its objects and this one has none: add_object "
                      "something first (a marker stone out of the way will do)")
    lost = _rebuild(entry, scene, world_id)
    entry["story"].append(f"made the ground a {kind}")
    report = entry["world"].environment_report()
    answer: dict[str, Any] = {"ground": _ground_said(report)}
    water = _water_said(entry["world"], full=True)
    if water:
        answer["water"] = water
    answer["note"] = ("Made by physics once and saved: drainage decided where the river runs, "
                      "erosion wore its channel and laid sand along it. Heights here are not flat: "
                      "use survey to find the ground and the water anywhere, and every object added "
                      "is set ON the ground if it was asked for inside it. The river runs along x.")
    if lost:
        answer["joints_lost"] = lost
    return answer


def tool_survey(args: dict[str, Any]) -> dict[str, Any]:
    """The ground and the water at a point, or along a line."""
    entry = _world(args.get("world_id"))
    world = _require_terrain(entry)
    if args.get("from_m") is not None and args.get("to_m") is not None:
        a, b = _xz(args["from_m"], "from_m"), _xz(args["to_m"], "to_m")
        every = _number(args.get("every_m", 0.5), "every_m", 0.1, 10.0)
        length = math.dist(a, b)
        count = max(2, min(60, int(length / every) + 1))
        rows = []
        wet: list[list[float]] = []
        for k in range(count):
            t = k / (count - 1)
            x, z = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
            here = world.survey(x, z)
            if not here.get("on_the_ground"):
                continue
            water = here.get("water")
            rows.append([round(x, 2), round(z, 2), round(here["ground_m"], 3), here["surface"],
                         round(water["depth_m"], 3) if water else 0.0,
                         round(water["surface_m"], 3) if water else None,
                         round(water["speed_m_s"], 2) if water else 0.0])
            if water:
                if wet and wet[-1][1] == k - 1:
                    wet[-1][1] = k
                else:
                    wet.append([k, k])
        return {"from_m": a, "to_m": b,
                "columns": ["x_m", "z_m", "ground_m", "made_of", "water_depth_m", "water_level_m",
                            "flowing_m_s"],
                "along": rows,
                "water_between": [[rows[s][:2], rows[e][:2]] for s, e in wet if s < len(rows) and e < len(rows)],
                "note": "an object resting on the ground has its centre at ground_m plus half its "
                        "own height; one resting on a river bed, at the bed plus half its height"}
    at = _xz(args.get("at_m") or [0, 0], "at_m")
    here = world.survey(at[0], at[1])
    if not here.get("on_the_ground"):
        return {"at_m": at, "on_the_ground": False, "note": "that point is off the edge of the ground"}
    said = {"at_m": at, "ground_m": round(here["ground_m"], 4), "made_of": here["surface"],
            "slope_deg": round(here["slope_deg"], 1),
            "layers_m": {"sand": round(here["sand_m"], 3), "soil": round(here["soil_m"] + here["loose_soil_m"], 3),
                         "rock_starts_at_m": round(here["rock_top_m"], 3)}}
    if here.get("water"):
        w = here["water"]
        said["water"] = {"depth_m": round(w["depth_m"], 3), "level_m": round(w["surface_m"], 3),
                         "flowing_m_s": round(w["speed_m_s"], 3),
                         "flowing_towards": [round(v, 3) for v in w["velocity_m_s"]]}
    else:
        said["water"] = None
    return said


def tool_water_state(args: dict[str, Any]) -> dict[str, Any]:
    """The rivers and ponds: how much, where, how fast, and what is floating."""
    entry = _world(args.get("world_id"))
    world = _require_terrain(entry)
    said = _water_said(world, full=True) or {}
    said["note"] = ("A dam is things that sink resting on the river bed: water rises behind it "
                    "until it spills over or round. A new channel dug lower than the water lets it "
                    "out. What floats is what its density and the water it displaces make float.")
    return said


def _record_edit(entry: dict[str, Any], edit: dict[str, Any]) -> None:
    """An edit kept in the scene, so the world opened again has the same ground."""
    scene = dict(entry["scene"])
    terrain = dict(scene["terrain"])
    terrain["edits"] = list(terrain.get("edits") or []) + [edit]
    scene["terrain"] = terrain
    entry["scene"] = scene


def _carry(entry: dict[str, Any], material: str, cubic_metres: float) -> None:
    if cubic_metres <= 0.0:
        return
    have = entry["carried"].setdefault(material, {"kilograms": 0.0, "pieces": 0})
    have["kilograms"] += cubic_metres * GROUND_DENSITY[material]


def tool_dig(args: dict[str, Any]) -> dict[str, Any]:
    """Dig a trench or a pit. Loose material first, then soil; a spade stops on rock."""
    world_id = str(args.get("world_id"))
    entry = _world(world_id)
    world = _require_terrain(entry)
    start = _xz(args.get("from_m"), "from_m")
    end = _xz(args.get("to_m"), "to_m") if args.get("to_m") is not None else start
    width = _number(args.get("width_m", 0.8), "width_m", 0.25, 10.0)
    depth = _number(args.get("depth_m", 0.5), "depth_m", 0.05, 3.0)
    try:
        dug = world.dig(start, end, width, depth)
    except banjo.BanjoError as error:
        raise Refused(str(error))
    _record_edit(entry, {"dig": {"from_m": start, "to_m": end, "width_m": width, "depth_m": depth}})
    _carry(entry, "sand", dug.sand_m3)
    _carry(entry, "soil", dug.soil_m3)
    entry["story"].append(f"dug from {start} to {end}, {width:g} m wide and {depth:g} m deep")
    return {"dug_m3": round(dug.sand_m3 + dug.soil_m3, 3), "sand_m3": round(dug.sand_m3, 3),
            "soil_m3": round(dug.soil_m3, 3), "kilograms": round(dug.mass_kg, 1),
            "columns": dug.columns, "colliders_rebuilt": dug.chunks_rebuilt,
            "things_woken": dug.bodies_woken,
            "carried": {m: round(v["kilograms"], 1) for m, v in sorted(entry["carried"].items())},
            "note": "The ground is lower there now. Whatever stood on it was woken and falls if "
                    "nothing is under it any more; loose sides slump into the trench over the next "
                    "second; water finds it if it is lower than the water. Call run to let all of "
                    "that happen. What came out is carried -- fill puts it back somewhere."}


def tool_fill(args: dict[str, Any]) -> dict[str, Any]:
    """Heap carried sand or soil on the ground: an earth bank, a filled hole."""
    world_id = str(args.get("world_id"))
    entry = _world(world_id)
    world = _require_terrain(entry)
    at = _xz(args.get("at_m"), "at_m")
    radius = _number(args.get("radius_m", 1.0), "radius_m", 0.25, 5.0)
    volume = _number(args.get("volume_m3", 0.5), "volume_m3", 0.01, 50.0)
    material = str(args.get("material") or "soil")
    if material not in GROUND_DENSITY:
        raise Refused("fill with soil or sand: what digging gives you")
    have = entry["carried"].get(material, {}).get("kilograms", 0.0) / GROUND_DENSITY[material]
    if have + 1e-9 < volume:
        raise Refused(f"you are carrying {have:.3f} m^3 of {material}, and ground does not come from "
                      f"nowhere: dig {volume - have:.3f} m^3 more first, or fill with less")
    sand, soil = (volume, 0.0) if material == "sand" else (0.0, volume)
    try:
        heaped = world.deposit(at, radius, sand, soil)
    except banjo.BanjoError as error:
        raise Refused(str(error))
    _record_edit(entry, {"deposit": {"at_m": at, "radius_m": radius, "sand_m3": sand, "soil_m3": soil}})
    entry["carried"][material]["kilograms"] -= volume * GROUND_DENSITY[material]
    entry["story"].append(f"heaped {volume:g} m^3 of {material} at {at}")
    return {"heaped_m3": round(volume, 3), "of": material, "columns": heaped.columns,
            "colliders_rebuilt": heaped.chunks_rebuilt,
            "carried": {m: round(v["kilograms"], 1) for m, v in sorted(entry["carried"].items())},
            "note": "A heap settles to the steepest slope it can hold -- sand to about 32 degrees -- "
                    "over the next second: run to let it."}


def tool_cut_block(args: dict[str, Any]) -> dict[str, Any]:
    """Cut a block of stone out of bare rock; it becomes an ordinary loose object."""
    world_id = str(args.get("world_id"))
    entry = _world(world_id)
    world = _require_terrain(entry)
    name = str(args.get("name") or "cut stone")[:60]
    if any(b["name"] == name for b in entry["scene"]["bodies"]):
        raise Refused(f"there is already something called {name!r} here; give the block another name")
    at = _xz(args.get("at_m"), "at_m")
    size = _triple(args.get("size_m") or [1.0, 0.4, 1.0], "size_m", 0.05, 4.0)
    column = world.terrain().cell_m
    cells = (max(1, round(size[0] / column)), max(1, round(size[2] / column)))
    try:
        block = world.cut_block(at, cells, size[1])
    except banjo.BanjoError as error:
        raise Refused(str(error))
    body = {"name": name, "shape": "box", "material": "concrete",
            "dimensions_m": [round(v, 6) for v in block.size_m],
            "center_m": [round(v, 6) for v in block.center_m],
            "velocity_m_s": [0.0, 0.0, 0.0], "anchored": False}
    _record_edit(entry, {"cut": {"at_m": at, "cells": list(cells), "height_m": block.size_m[1]}})
    scene = dict(entry["scene"], bodies=list(entry["scene"]["bodies"]) + [body])
    lost = _rebuild(entry, scene, world_id)
    entry["story"].append(f"cut {name} out of the rock at {at}")
    answer: dict[str, Any] = {
        "cut": name, "size_m": body["dimensions_m"], "kilograms": round(block.mass_kg, 1),
        "volume_m3": round(block.volume_m3, 4),
        "note": "The ground lost exactly this much stone and the block is it -- the ground's "
                "ledger counts it as cut. It is an ordinary loose object now, made of the engine's "
                "stone (concrete): pick it up, drop it, build a dam with it."}
    if lost:
        answer["joints_lost"] = lost
    return answer


def tool_set_river(args: dict[str, Any]) -> dict[str, Any]:
    """How much water a river brings in, from now: a flood or a drought."""
    world_id = str(args.get("world_id"))
    entry = _world(world_id)
    world = _require_terrain(entry)
    report = world.environment_report()
    rivers = [r["name"] for r in report["water"]["rivers"]]
    if not rivers:
        raise Refused("this ground has no river")
    river = str(args.get("river") or rivers[0])
    if river not in rivers:
        raise Refused(f"there is no river called {river!r}: there is {', '.join(rivers)}")
    discharge = _number(args.get("discharge_m3_s", 0.35), "discharge_m3_s", 0.0, 5.0)
    try:
        world.set_discharge(river, discharge)
    except banjo.BanjoError as error:
        raise Refused(str(error))
    scene = dict(entry["scene"])
    water = dict(scene.get("water") or {})
    water["rivers"] = [r for r in (water.get("rivers") or []) if r.get("name") != river] + \
                      [{"name": river, "discharge_m3_s": discharge}]
    scene["water"] = water
    entry["scene"] = scene
    entry["story"].append(f"{river} now brings {discharge:g} m^3/s")
    return {"river": river, "discharge_m3_s": discharge,
            "note": "from now; run to see what it does downstream"}


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
        "contents": {"type": "object", "additionalProperties": {"type": "number"},
                     "description": "What it is made of inside, by mass fraction of its own "
                                    "mass, like {\"dry wood\": 0.8, \"moisture\": 0.18, "
                                    "\"ash\": 0.02}. Leave it out and it is made of what its "
                                    "material is made of: oak is dry wood, moisture and ash, "
                                    "which is what lets an oak log burn. list_substances says "
                                    "what there is."},
        "temperature_k": {"type": "number",
                          "description": "How hot it starts, in kelvin. Left out, it is at "
                                         "room temperature, 293 K."},
    },
    "required": ["shape", "material", "size_m"],
}

# add_object's place: [x, z] puts a thing DOWN there, on whatever is under that
# point; [x, y, z] puts its centre exactly there.
PLACED_OBJECT_SCHEMA = dict(OBJECT_SCHEMA, properties=dict(
    OBJECT_SCHEMA["properties"],
    position_m={"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 3,
                "description": "Where it goes. [x, z] sets it down on whatever is under "
                               "that point -- the ground, the floor or the top of what is "
                               "there -- and the answer's set_down says what it rests on: "
                               "this is how to put something somewhere. [x, y, z] puts its "
                               "centre exactly there instead, in the air if that is above "
                               "what is under it, to fall."}))

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
     "description": "Put another object into a world. position_m [x, z] sets it down on "
                    "whatever is under that point -- the ground, the floor or the top of "
                    "what is there -- and says what; [x, y, z] puts it exactly there. The "
                    "world is opened again from its scene, so anything in flight starts "
                    "over; every joint is hung again. Names must be different: joints and "
                    "every later call find things by name.",
     "inputSchema": {"type": "object", "required": ["world_id", "object"], "properties": {
         "world_id": {"type": "string"}, "object": PLACED_OBJECT_SCHEMA}}},
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
    {"name": "list_substances",
     "description": "What matter is made of here: the substances, the reactions between them "
                    "(with where every number came from -- most are demonstration values), and "
                    "what each material is made of. Oak is dry wood, moisture and ash, which is "
                    "why an oak log can burn; iron is iron and cannot. Read it before giving "
                    "anything contents.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "enclose_gas",
     "description": "Fill a space with gas that pushes on a body: a cylinder under a piston. "
                    "Build the cylinder from anchored walls, put a loose piston in it on a "
                    "`slide`, then name the piston here and say how tall the column of gas "
                    "under it is. The gas starts at the pressure that holds up the piston and "
                    "whatever rests on it, unless you give pressure_pa. Its temperature and "
                    "pressure are worked out from what it holds and the room it has: `heat` it "
                    "and it pushes harder and lifts what is on it; as it cools the load comes "
                    "back down and pushes on the gas. Nothing sets the piston's speed -- the "
                    "force is pressure times area.",
     "inputSchema": {"type": "object", "required": ["world_id", "name"], "properties": {
         "world_id": {"type": "string"},
         "name": {"type": "string", "description": "What to call the gas, like 'cylinder gas'."},
         "piston": {"type": "string", "description": "The loose body it pushes on."},
         "height_m": {"type": "number",
                      "description": "How tall the column of gas is, from the floor of the "
                                     "cylinder to the underside of the piston."},
         "volume_m3": {"type": "number", "description": "Instead of height_m: its volume."},
         "contents": {"type": "object", "additionalProperties": {"type": "number"},
                      "description": "Which gas, by mass fraction. Argon by default: "
                                     "{\"argon\": 1}. Air is nitrogen 0.755, oxygen 0.232, "
                                     "argon 0.013."},
         "pressure_pa": {"type": "number",
                         "description": "Leave out to start balanced against what it holds up."},
         "temperature_k": {"type": "number", "description": "Room temperature by default."},
         "axis": dict(VECTOR, description="Which way the gas pushes the piston. Up by default."),
         "area_m2": {"type": "number",
                     "description": "The area it pushes on. The piston's own cross-section "
                                    "by default."}}}},
    {"name": "heat",
     "description": "Put heat into a body or a gas region, from outside: kindling under a log, "
                    "a torch, a stove under a cylinder. It runs from when the world starts (or "
                    "start_s) for `seconds` at `power_w`, and the energy ledger counts it. "
                    "Whether it lights anything is the engine's answer: two oak logs on a stone "
                    "hearth light with about 10 kW under EACH for 90 s, and a log given much "
                    "less warms, dries and goes out. A gas that is heated expands against its "
                    "piston.",
     "inputSchema": {"type": "object", "required": ["world_id", "target", "power_w", "seconds"],
                     "properties": {
         "world_id": {"type": "string"},
         "target": {"type": "string", "description": "A body's name, or a gas region's."},
         "power_w": {"type": "number", "description": "Watts. Kindling is about 10000."},
         "seconds": {"type": "number", "description": "For how long."},
         "start_s": {"type": "number", "description": "When, after the world starts. 0 by default."}}}},
    {"name": "thermal_state",
     "description": "How hot everything is and what is happening to it: surface and core "
                    "temperatures, what is burning and how hard (kW), the fuel left, and an "
                    "ESTIMATE of how long it would last at the rate it is burning now; each gas "
                    "region's temperature, pressure and how far it has pushed its piston; and "
                    "the energy ledger. Call run first: this reads the world as it stands.",
     "inputSchema": {"type": "object", "required": ["world_id"],
                     "properties": {"world_id": {"type": "string"}}}},
    {"name": "blade",
     "description": "Give a body an EDGE, so it cuts. There is no cutting power: what "
                    "resists the edge is the target's own fracture energy and hardness, "
                    "R = G + H x (2 x edge radius) per square metre, applied in the "
                    "solver as friction. So an edge cuts only where it bites -- edge "
                    "leading, steeper than its own bevel, pressed in -- and only as far "
                    "as the push or the swing can pay for. A partial cut stays partial; "
                    "a cut through makes pieces with their own mass and momentum that "
                    "keep whatever joints they hold. The flat and the point are ordinary "
                    "contacts. Glass, ceramic, ice and concrete are brittle and are not "
                    "cut, and nothing as hard as the blade is. Ropes that can be cut are "
                    "runs of small bodies tied with `tie`. Points are where they are in the "
                    "world now; the edge is kept with its body from then on, through the "
                    "world being opened again, and the person's room has it.",
     "inputSchema": {"type": "object",
                     "required": ["world_id", "body", "heel_m", "tip_m", "facing"],
                     "properties": {
         "world_id": {"type": "string"},
         "body": {"type": "string", "description": "The body that carries the edge."},
         "heel_m": dict(VECTOR, description="Where the edge starts, on the body's surface."),
         "tip_m": dict(VECTOR, description="Where it ends: the point."),
         "facing": dict(VECTOR, description="Which way the edge faces, out of the body, "
                                            "roughly perpendicular to the edge."),
         "thickness_m": {"type": "number", "description": "Across the flats."},
         "edge_radius_m": {"type": "number",
                           "description": "How sharp: 0.0002 is a working sword edge, "
                                          "0.00005 a keen one, 0.001 blunt."},
         "bevel_deg": {"type": "number", "description": "Included angle of the edge, "
                                                        "30 by default."},
         "grip_m": dict(VECTOR, description="Where a hand holds it.")}}},
    {"name": "blades",
     "description": "Every edge in the world: where it is, how sharp, what it has cut "
                    "and what that cost, and what it is in right now.",
     "inputSchema": {"type": "object", "required": ["world_id"],
                     "properties": {"world_id": {"type": "string"}}}},
    {"name": "cuts",
     "description": "Every meeting between an edge and something since the last swing, "
                    "INCLUDING the ones that cut nothing, with what kind each was: "
                    "edge, slice or press (it bit), glancing, flat or point (an "
                    "ordinary contact), blunt (the target is as hard as the blade) or "
                    "brittle (it cracks instead).",
     "inputSchema": {"type": "object", "required": ["world_id"],
                     "properties": {"world_id": {"type": "string"}}}},
    {"name": "wield",
     "description": "Take hold of a body the way a person holds a sword: at its grip, "
                    "with a hand whose force (800 N) and torque (60 N m) are bounded, so "
                    "what it meets can slow it or stop it. Not `pick_up`, which carries "
                    "a loose thing exactly where it is put. grip_m defaults to the "
                    "blade's grip.",
     "inputSchema": {"type": "object", "required": ["world_id", "name"],
                     "properties": {"world_id": {"type": "string"},
                                    "name": {"type": "string"},
                                    "grip_m": VECTOR}}},
    {"name": "swing",
     "description": "Swing the wielded blade, as a person does, and report every edge "
                    "contact. Give `through_m`, a point the middle of the edge should pass "
                    "through -- the middle of a rope segment, say -- with `pointing`, the way "
                    "the blade points (THROUGH what is to be cut), and `edge_facing`, the way "
                    "the edge faces: across the swing to lead with the edge and cut, or up "
                    "or down to lead with the flat. The hand takes the blade up, back clear "
                    "and round to one side, then swings it round a shoulder half a metre "
                    "behind the grip through 100 degrees in `seconds` (0.13 by default), and "
                    "lets the world run `then_s` more. Or give `to_m` to move the grip in a "
                    "straight line, which is a press or a push, not a swing. The hand has "
                    "800 N and 60 N m and swings as fast as that allows. This is the copy "
                    "of the world you are building in -- the person swings for themselves "
                    "in theirs.",
     "inputSchema": {"type": "object", "required": ["world_id"],
                     "properties": {
         "world_id": {"type": "string"},
         "through_m": dict(VECTOR, description="A point the middle of the edge passes "
                                               "through: a swing."),
         "to_m": dict(VECTOR, description="Instead of through_m: where the grip should "
                                          "end up, moved in a straight line."),
         "seconds": {"type": "number", "description": "How long the swing, or the move, "
                                                      "takes."},
         "then_s": {"type": "number", "description": "How long to let things settle "
                                                     "after. 1 by default."},
         "pointing": dict(VECTOR, description="Which way the blade should point from "
                                              "the grip, in the world, like [0, 0, -1]."),
         "edge_facing": dict(VECTOR, description="Which way its edge should face, like "
                                                 "[-1, 0, 0]: the way the swing goes, for "
                                                 "a cut; up or down, for the flat."),
         "facing_wxyz": {"type": "array", "items": {"type": "number"},
                         "minItems": 4, "maxItems": 4,
                         "description": "Instead of pointing and edge_facing: which way the "
                                        "held body should face, as a quaternion, w first."}}}},
    {"name": "make_terrain",
     "description": "Give the world ground that is not flat: a VALLEY with a river running along "
                    "it (west to east, along x) and a pond beside it, made once by physics -- "
                    "drainage decided where the river runs, erosion wore its channel -- and saved. "
                    "Also a basin holding a lake, a straight sloping channel with a stream, flat "
                    "ground of soil over rock, or none (back to the flat floor). The ground is rock, "
                    "soil and sand; the water is real: it flows downhill, fills what it can, and "
                    "carries and lifts what is in it. Objects already in the world stay where they "
                    "are. Answers with where the ground and the river are.",
     "inputSchema": {"type": "object", "required": ["world_id"], "properties": {
         "world_id": {"type": "string"},
         "kind": {"type": "string", "enum": TERRAIN_KINDS + ["none"]},
         "seed": {"type": "integer", "description": "A different valley for a different number."},
         "discharge_m3_s": {"type": "number",
                            "description": "What the river brings in, cubic metres a second. "
                                           "0.35 by default: a stream about 2 m wide."}}}},
    {"name": "survey",
     "description": "The ground and the water at a point, or along a line between two points: "
                    "how high the ground is, what it is made of (rock, soil, sand) and how steep, "
                    "and how deep the water is there, its level and how fast it flows. Use it "
                    "before placing anything on uneven ground, and to find the river: survey "
                    "across the valley (along z) and the stretch with water in it is the river. "
                    "An object resting on the ground has its centre at the ground height plus "
                    "half its own height.",
     "inputSchema": {"type": "object", "required": ["world_id"], "properties": {
         "world_id": {"type": "string"},
         "at_m": dict(PAIR, description="One point: [x, z]."),
         "from_m": dict(PAIR, description="A line from here..."),
         "to_m": dict(PAIR, description="...to here."),
         "every_m": {"type": "number", "description": "Spacing along the line; 0.5 by default."}}}},
    {"name": "water_state",
     "description": "The rivers and ponds: how much water there is, what is coming in and going "
                    "out, each pond's level, where the river runs (every 2 m along it: x, z, "
                    "level, depth, speed), what is in the water and whether it floats, and the "
                    "water's ledger (in, out, and what is unaccounted for). Call run first to let "
                    "time pass; call this before and after to see a level rise or fall.",
     "inputSchema": {"type": "object", "required": ["world_id"],
                     "properties": {"world_id": {"type": "string"}}}},
    {"name": "dig",
     "description": "Dig a trench from one point to another (or a pit, at one point), width_m "
                    "wide and depth_m below the ground as it stands. Loose sand first, then soil; "
                    "a spade stops on rock. It is real: whatever stood on that ground loses its "
                    "support and falls if nothing else holds it up, loose banks slump into the "
                    "trench, and water flows into it if it is lower than the water -- dig from a "
                    "pond or a dammed river to lower ground and it drains. What comes out is "
                    "carried, and `fill` can put it back. Only the ground you dig, and what it "
                    "was holding, is disturbed.",
     "inputSchema": {"type": "object", "required": ["world_id", "from_m"], "properties": {
         "world_id": {"type": "string"},
         "from_m": dict(PAIR, description="Where the trench starts: [x, z]."),
         "to_m": dict(PAIR, description="Where it ends; leave out for a pit."),
         "width_m": {"type": "number", "description": "0.8 by default."},
         "depth_m": {"type": "number", "description": "Below the ground as it stands; 0.5 by "
                                                      "default. To drain water, dig below its "
                                                      "level all the way to somewhere lower."}}}},
    {"name": "fill",
     "description": "Heap sand or soil you have dug on the ground: fill a trench, bank up an "
                    "earth dam, make a mound. It settles to the steepest slope it can hold. Ground "
                    "does not come from nowhere: you can only fill with what digging has given "
                    "you (see the carried amounts dig reports).",
     "inputSchema": {"type": "object", "required": ["world_id", "at_m", "volume_m3"], "properties": {
         "world_id": {"type": "string"},
         "at_m": dict(PAIR, description="The middle of the heap: [x, z]."),
         "radius_m": {"type": "number", "description": "How far it spreads; 1 by default."},
         "volume_m3": {"type": "number"},
         "material": {"type": "string", "enum": ["soil", "sand"]}}}},
    {"name": "cut_block",
     "description": "Cut a block of stone out of bare rock (survey says where the ground is "
                    "made of rock -- the flat top of the rocky knoll is a quarry). The ground "
                    "loses exactly that much rock and the block becomes an ordinary loose object "
                    "of stone you can pick up, drop or build with. Its sides are whole numbers of "
                    "the ground's columns and of the world's cells: 1 m across works.",
     "inputSchema": {"type": "object", "required": ["world_id", "name", "at_m"], "properties": {
         "world_id": {"type": "string"},
         "name": {"type": "string"},
         "at_m": dict(PAIR, description="The middle of the block, on the rock: [x, z]."),
         "size_m": dict(VECTOR, description="Width, height, depth. [1, 0.4, 1] by default.")}}},
    {"name": "set_river",
     "description": "How much water a river brings in from now, cubic metres a second: a flood "
                    "or a drought. It takes time to arrive downstream -- run to see it.",
     "inputSchema": {"type": "object", "required": ["world_id", "discharge_m3_s"], "properties": {
         "world_id": {"type": "string"},
         "river": {"type": "string", "description": "Its name; the only one by default."},
         "discharge_m3_s": {"type": "number"}}}},
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
    if tool in ("tie", "spring"):
        # Made off in the air, an end rides on its body like the tip of a stiff
        # arm that is not there. A model hung a weight 0.24 m below the end of
        # its rope and tied it from under the last segment, and a blow to the
        # rope flung the weight about on that arm.
        what = "rope" if tool == "tie" else "rod"
        for end, name in (("at_a_m", args.get("a")), ("at_b_m", args.get("b"))):
            if args.get(end) is None:
                continue
            off = _off_body(entry, str(name or ""), args[end])
            if off is not None and off > cell:
                said.append(f"{end} is {off:.2f} m outside {name}. A {what} is made off ON "
                            f"what it holds, at a point in its matter: made off in the air, "
                            f"the point rides on {name} like the end of a stiff arm that is "
                            f"not there. Put the point on {name} -- for a rope of segments, "
                            f"0.02 m either side of the join, with the bodies touching.")
    return said


def _off_body(entry: dict[str, Any], name: str, point: Any) -> float | None:
    """How far a point lies outside a body's box, in metres: 0 on or in it."""
    world = entry.get("world")
    try:
        body = world.body(name) if world is not None else None
    except banjo.BanjoError:
        body = None
    if body is None:
        return None
    local = _to_body(body, [float(v) for v in point])
    outside = [max(0.0, abs(x) - d / 2.0) for x, d in zip(local, body.dimensions_m)]
    return math.sqrt(sum(o * o for o in outside))


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
    "list_substances": tool_list_substances,
    "enclose_gas": tool_enclose_gas,
    "heat": tool_heat,
    "thermal_state": tool_thermal_state,
    "blade": tool_blade,
    "blades": tool_blades,
    "cuts": tool_cuts,
    "wield": tool_wield,
    "swing": tool_swing,
    "make_terrain": tool_make_terrain,
    "survey": tool_survey,
    "water_state": tool_water_state,
    "dig": tool_dig,
    "fill": tool_fill,
    "cut_block": tool_cut_block,
    "set_river": tool_set_river,
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
