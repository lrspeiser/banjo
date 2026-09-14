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
# Beside this file: the rules for how a person uses a thing, which the
# playground's room holds its own profiles to as well.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import banjo  # noqa: E402
import interaction_profiles  # noqa: E402
import progression  # noqa: E402

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
        # One piece: every object given the same join name is built as ONE
        # body -- their cells unioned on the shared grid and bonded across the
        # seam -- so a pick's haft and its arm are one tool, not two things
        # touching. The world names the piece after the first of them.
        if item.get("join") is not None and str(item["join"]).strip():
            body["join"] = str(item["join"]).strip()[:60]
        # How it is turned, as the engine turns it (_turn_matrix: z first about
        # the room's axes). Any angle is taken, as the same turn within +-180.
        if item.get("rotation_deg") is not None:
            turn = [(a + 180.0) % 360.0 - 180.0 for a in
                    _triple(item["rotation_deg"], f"{name}: rotation_deg", -1.0e6, 1.0e6)]
            if any(abs(a) > 1e-9 for a in turn):
                body["rotation_deg"] = [round(a, 6) for a in turn]
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
            # What it weighs, from the engine: whether a person's 800 N hand can
            # hold it up and turn it is decided by this, and a model building a
            # thing for them to handle cannot see it any other way.
            "mass_kg": round(body.mass_kg, 2),
            "speed_m_s": round(math.sqrt(sum(v * v for v in body.velocity_m_s)), 3),
            "anchored": body.anchored,
        })
        # How a box stands, when it is not square to the room: the rotation_deg
        # that would build it so. A model that leaned a plank can see it did.
        turned = _turned(body.shape, body.orientation_wxyz)
        if turned:
            out[-1]["rotation_deg"] = turned
    return out


# ---------------------------------------------------------------------------
# The tools
# ---------------------------------------------------------------------------

def _engine_materials() -> dict[str, Any]:
    """What the engine says each material and surface rolls like -- asked of the
    engine (banjo_materials), not written down here a second time."""
    try:
        said = banjo.materials()
    except Exception:   # no library: the notes above still stand on their own
        return {"materials": {}, "surfaces": [], "law": {}}
    return {"materials": {m["name"]: m for m in said.get("materials", [])},
            "surfaces": said.get("surfaces", []), "law": said.get("rolling_resistance", {})}


def _rolling_said(entry: dict[str, Any]) -> dict[str, Any]:
    """One material's or surface's rolling resistance, and whether a table or a
    measurement gives it or it is a demonstration value."""
    return {"rolling_resistance": entry["rolling_resistance"],
            "rolling_resistance_is": ("sourced" if entry.get("rolling_resistance_sourced")
                                      else "a demonstration value"),
            "rolling_resistance_basis": entry.get("rolling_resistance_basis", "")}


def tool_list_materials(_args: dict[str, Any]) -> dict[str, Any]:
    engine = _engine_materials()
    materials = []
    for m in MATERIALS:
        said: dict[str, Any] = {"name": m, "behaviour": MATERIAL_NOTES[m]}
        if m in engine["materials"]:
            said.update(_rolling_said(engine["materials"][m]))
        materials.append(said)
    answer: dict[str, Any] = {
        "materials": materials,
        "note": "Every speed above was measured by dropping a 100 mm ball of that "
                "material onto a concrete floor. A threshold is the speed below "
                "which nothing CAN happen; above it, it is possible and not "
                "certain, and only running it says."}
    if engine["surfaces"]:
        answer["surfaces"] = [dict(name=s["name"], made_of=s["made_of"], **_rolling_said(s))
                              for s in engine["surfaces"]]
        answer["rolling"] = (
            "A ball is resisted by a couple M = c N r at what it rolls on: c is the ball's own "
            "rolling resistance PLUS the surface's. It stays put on any slope whose tangent is "
            "below c, rolls down any steeper one, and on the level slows at 5/7 c g, stopping "
            "in v^2 / (2 * 5/7 c g): a rubber ball rolled at 1 m/s runs about 6.5 m on the "
            "floor (c = 0.011) and stops within 0.2 m on sand (c = 0.31), which holds it on "
            "slopes up to 17 degrees; an iron ball on the floor (c = 0.0015) runs about 50 m. "
            "Boxes do not roll. run and describe_world say what it took, in joules.")
    return answer


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
    if entry.get("interactions"):
        said["things_a_person_uses"] = [_use_said(p) for p in entry["interactions"]]
    if _has_terrain(entry):
        report = world.environment_report()
        said["ground"] = _ground_said(report)
        said["water"] = _water_said(world, full=True)
    else:
        said["ground"] = "flat, at y = 0"
    return said


def _rolling_loss(world: banjo.World) -> float:
    try:
        return float(world.rolling_report().get("loss_j", 0.0))
    except banjo.BanjoError:
        return 0.0


def _rolling_now(world: banjo.World, since_j: float = 0.0) -> dict[str, Any] | None:
    """What rolling resistance is doing: which balls it holds still, which are
    rolling against it, and the energy it has taken -- a declared loss, like a
    cut's work. None when nothing round is touching anything."""
    try:
        report = world.rolling_report()
    except banjo.BanjoError:
        return None
    contacts = report.get("contacts") or []
    taken = float(report.get("loss_j", 0.0)) - since_j
    if not contacts and taken <= 1e-9:
        return None
    held = sorted({c["ball"] for c in contacts if c.get("held")})
    return {"held_still": held,
            "rolling_against_it": sorted({c["ball"] for c in contacts if c["ball"] not in held}),
            "on": {c["ball"]: {"what": c["on"], "c": round(c["coefficient"], 4)} for c in contacts},
            "took_j": round(taken, 4)}


def tool_run(args: dict[str, Any]) -> dict[str, Any]:
    """Let time pass, settling whatever wants to break, and say what happened."""
    import time as clock
    entry = _world(args.get("world_id"))
    world: banjo.World = _live(entry)
    seconds = _number(args.get("seconds", 2.0), "seconds", 0.001, MAX_RUN_S)
    dt = 1.0 / 480.0
    began = clock.perf_counter()
    started_at = world.time_s
    rolling_before = _rolling_loss(world)
    events: list[dict[str, Any]] = []
    hardest: dict[tuple[str, str], dict[str, Any]] = {}
    stopped_early = None
    # Which joints were holding when the run began: one that lets go during it
    # is something that happened, and says why (a fixing made of a member that
    # heat weakened, a rope overloaded).
    holding_at_start = {j.id for j in world.joints() if j.attached}

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

    stable = {r["live"]: r["id"] for r in entry.get("joints", [])}
    for pin in world.joints():
        if pin.id in holding_at_start and not pin.attached and pin.parted_because:
            events.append({"what": "gave way", "object": f"{pin.b} from {pin.a}",
                           "joint": stable.get(pin.id, pin.id),
                           "because": pin.parted_because})

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
    rolling = _rolling_now(world, since_j=rolling_before)
    if rolling is not None:
        answer["rolling_resistance"] = rolling
    heat = _heat_said(world, limit=10)
    if heat is not None:
        answer["heat"] = heat
    strength = _strength_said(world)
    if strength is not None:
        answer["strength"] = strength
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
    """What has been swept up in this world, by material, and the sand and soil
    dug out of its ground and not put back."""
    entry = _world(args.get("world_id"))
    carried = _all_carried(entry)

    def said(have: dict[str, float]) -> dict[str, Any]:
        out: dict[str, Any] = {"kilograms": round(have["kilograms"], 4),
                               "grams": round(have["kilograms"] * 1000.0, 1)}
        if "pieces" in have:
            out["pieces"] = have["pieces"]
        if "cubic_metres" in have:
            out["cubic_metres"] = round(have["cubic_metres"], 4)
        return out

    return {"carried": {m: said(v) for m, v in sorted(carried.items())},
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
    # Where every body stands as the world opens: a point declared on one is
    # kept in its own frame, and the room is told where that is as built.
    entry["poses"] = ({b.name: (list(b.position_m), list(b.orientation_wxyz)) for b in fresh.bodies()}
                      if fresh is not None else {})
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
    # And the points of tools that dig (see tool_tool_point), the same way.
    points = list(scene.get("tool_points") or [])
    if points:
        if fresh is None:
            lost += [f"the point on {p['body']}: the world is empty" for p in points]
            entry["scene"] = {k: v for k, v in entry["scene"].items() if k != "tool_points"}
        else:
            armed, dropped = _arm_tool_points(fresh, points)
            lost += dropped
            if dropped:
                entry["scene"] = dict(entry["scene"], tool_points=armed)
    # And how the things in it are used, held to what is built now.
    _recheck_interactions(entry)
    return lost


def _held_by(entry: dict[str, Any], name: str) -> list[dict[str, Any]]:
    return [r for r in entry.get("joints", [])
            if name in (r["args"].get("a"), r["args"].get("b"))]


# What one hand can take up and turn. The engine's hand pulls with 800 N
# (LiveWorld's hand_strength_n) and has to hold a thing up with a tenth of that
# still over to move it: the playground's own rule for what it takes by the grip
# (playground/interaction.js, throwable). Heavier, a person can carry a thing --
# which is placement -- and cannot turn it by hand. A model building something
# for a person to handle cannot see its mass unless it is told; it was, in
# objects, and still made a 73.7 kg pillar twice, so it is said at the call.
HAND_STRENGTH_N = 800.0
HAND_LIFTS_KG = 0.9 * HAND_STRENGTH_N / 9.80665


def _by_hand(world: banjo.World | None, name: str) -> dict[str, Any] | None:
    body = world.body(name) if world is not None else None
    if body is None or body.anchored or body.mass_kg < HAND_LIFTS_KG:
        return None
    return {"mass_kg": round(body.mass_kg, 1), "a_hand_lifts_kg": round(HAND_LIFTS_KG, 1),
            "note": "too heavy for a person's 800 N hand to hold up and turn: they can carry "
                    "it, but not turn it by hand. If it is for them to pick up and handle, "
                    "make it lighter. turn_object is not held to this: it stands up or lays "
                    "down anything that will stay as it is put, however heavy."}


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
    # Wholly inside the ground -- a height worked out as if the ground were at 0,
    # where it is not -- it is set down on whatever is under it, as [x, z] would.
    # Measured, the room's chat gave a pot and a log heights of 0.24 and 0.14 on
    # ground at 0.6, and lifted onto the bare ground there they were refused six
    # times for overlapping the hearth stone that stood on it.
    buried = not set_down and _buried(entry, added)
    rests = _set_down(entry, added) if (set_down or buried) else None
    if buried:
        rests["note"] = ("it was given a height wholly inside the ground -- the ground here is "
                         "not at 0 -- so it was set down on what is under it, as [x, z] does")
    # A part of a piece set down on top of another part of the same piece is
    # never where a part goes. Measured, the playground's chat gave a pick's arm
    # [x, z] twice, the arm went onto its own haft, and the hand then held the
    # pick by its head, so every swing met no ground. Refused before the world
    # changes, with what to give instead.
    if rests is not None and added.get("join"):
        own = {b["name"] for b in entry["scene"]["bodies"] if b.get("join") == added["join"]}
        if rests["on"] in own:
            raise Refused(f"{added['name']} is part of the piece {added['join']!r}, and given "
                          f"[x, z] it would be set down on top of {rests['on']}, another part of "
                          f"that piece. Give every part of one piece its exact [x, y, z], side "
                          f"by side as they join: on the ground, its centre at half its own "
                          f"height; otherwise where it meets the part before it.")
    seated = None if (set_down or buried) else _seat_on_ground(entry, added)
    held_up = None if (set_down or buried) else _held_up(entry, added)
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
    # How it stands as the engine built it, in the words a plank is asked for in.
    # Measured, a model asked for a ramp "rising 15 degrees and leaning 10" gave
    # rotation_deg [15, 10, 0] and said it had: the plank rose 2.6 and leaned 14.8.
    built = entry["world"].body(added["name"])
    stands = _stands(added["shape"], built.orientation_wxyz) if built is not None else None
    if stands:
        answer["stands"] = stands
    heavy = _by_hand(entry["world"], added["name"])
    if heavy:
        answer["too_heavy_for_a_hand"] = heavy
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


def _stands(shape: str, orientation_wxyz: Any) -> dict[str, float] | None:
    """How a box stands, as a plank is described: how far its x side rises above
    the level (its +x end up is positive), how far its z side leans (its +z edge
    up is positive), and which way its x side faces about the vertical, as
    rotation_deg's y turns it. None for a box square to the room, or a ball."""
    if _turned(shape, orientation_wxyz) is None:
        return None
    w, x, y, z = (float(v) for v in orientation_wxyz)
    along = [1 - 2 * (y * y + z * z), 2 * (x * y + w * z), 2 * (x * z - w * y)]    # its own x
    across = [2 * (x * z + w * y), 2 * (y * z - w * x), 1 - 2 * (x * x + y * y)]   # its own z

    def degrees(a: float) -> float:
        return round(math.degrees(a), 1) + 0.0

    return {"x_side_rises_deg": degrees(math.asin(max(-1.0, min(1.0, along[1])))),
            "z_side_leans_deg": degrees(math.asin(max(-1.0, min(1.0, across[1])))),
            "x_side_faces_deg": degrees(math.atan2(-along[2], along[0]))}


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
    # And an edge on it, and a point.
    edges = [b for b in entry["scene"].get("blades") or [] if b.get("body") == name]
    points = [p for p in entry["scene"].get("tool_points") or [] if p.get("body") == name]
    scene = _with_thermo(dict(entry["scene"], bodies=kept,
                              blades=[b for b in entry["scene"].get("blades") or []
                                      if b.get("body") != name],
                              tool_points=[p for p in entry["scene"].get("tool_points") or []
                                           if p.get("body") != name]), block)
    lost = _rebuild(entry, scene, world_id, joints)
    answer: dict[str, Any] = {"removed": name, "objects": _describe(entry["world"])}
    if held:
        answer["joints_removed_with_it"] = [_joint_words(r) for r in held]
    if edges:
        answer["edge_removed_with_it"] = f"the edge on {name}"
    if points:
        answer["point_removed_with_it"] = f"the point on {name}"
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


# ---------------------------------------------------------------------------
# Turning a thing: stood on end, or laid down
# ---------------------------------------------------------------------------
#
# A pose EDIT, like move_object -- the thing is simply standing there, as if it
# had been built so -- that the engine holds to what the world would do with
# it: nothing may share its space, it is set on whatever is under it, and then
# the world is RUN until it is still. It has to be standing as it was put when
# it is. A pillar stood on a slope it cannot stand on, or half over an edge,
# falls in that run, and the edit is taken back and said, with what happened.
#
# The thing is turned by giving it new sides and a heading, never a tilt: a
# box stood on end is the same box with its long side up, and its own axes
# stay the world's up to one turn about the vertical.

TURN_SETTLE_S = 4.0     # at most this long, world time, to come to rest
TURN_STILL_S = 0.5      # still for this long is at rest
TURN_STILL_M_S = 0.01   # ... moving slower than this
TURN_STILL_RAD_S = 0.05  # ... and turning slower than this
STAYS_M = 0.02          # where it was put: it moved less than this while it settled
STAYS_DEG = 5.0         # ... and turned less than this
TRY_TILT_DEG = 0.35     # the settling run starts this far off, about each level axis
SQUARE_DEG = 0.5        # a box turned less than this, about every axis, is square


def _turn_matrix(rotation_deg: Any) -> list[list[float]]:
    """A body's authored rotation as a matrix, the way the ENGINE builds it
    (TileImpactScene's rotationQuaternion, qx * qy * qz: z turns first)."""
    x, y, z = (math.radians(float(v)) for v in (rotation_deg or [0.0, 0.0, 0.0]))
    cx, sx, cy, sy, cz, sz = (math.cos(x), math.sin(x), math.cos(y), math.sin(y),
                              math.cos(z), math.sin(z))
    rx = [[1.0, 0.0, 0.0], [0.0, cx, -sx], [0.0, sx, cx]]
    ry = [[cy, 0.0, sy], [0.0, 1.0, 0.0], [-sy, 0.0, cy]]
    rz = [[cz, -sz, 0.0], [sz, cz, 0.0], [0.0, 0.0, 1.0]]

    def times(a: list[list[float]], b: list[list[float]]) -> list[list[float]]:
        return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]

    return times(rx, times(ry, rz))


def _rotation_of(orientation_wxyz: Any) -> list[float]:
    """The rotation_deg that turns a body to this orientation: _turn_matrix
    undone. R = Rx Ry Rz has R[0][2] = sin y, R[1][2] = -sin x cos y,
    R[2][2] = cos x cos y, R[0][1] = -cos y sin z and R[0][0] = cos y cos z."""
    w, x, y, z = (float(v) for v in orientation_wxyz)
    r00, r01, r02 = 1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)
    r11, r12 = 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)
    r21, r22 = 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)
    cos_y = math.hypot(r00, r01)
    if cos_y > math.sin(math.radians(SQUARE_DEG)):
        turn = [math.atan2(-r12, r22), math.atan2(r02, cos_y), math.atan2(-r01, r00)]
    else:
        # Its own z within half a degree of the room's x -- a thing turned a
        # quarter about the vertical, which is common. x and z are then one turn
        # about the same axis, so all of it is put on x: a pillar laid along z
        # reads [0, -90, 0], not something like [37, -89.99, -37].
        turn = [math.atan2(r21, r11), math.copysign(math.pi / 2, r02), 0.0]
    return [math.degrees(a) for a in turn]


def _turned(shape: str, orientation_wxyz: Any) -> list[float] | None:
    """How a box stands now, as the rotation_deg that would build it so, to a
    tenth of a degree; None when it is square to the room (SQUARE_DEG) -- a box
    that settles on the floor turns by hundredths -- and for a ball or a piece."""
    if shape != "box":
        return None
    turn = [round(a, 1) + 0.0 for a in _rotation_of(orientation_wxyz)]
    return turn if any(abs(a) >= SQUARE_DEG for a in turn) else None


def _sides_now(body: dict[str, Any]) -> list[list[float]]:
    """Which way each of a scene body's own sides points in the world."""
    turn = _turn_matrix(body.get("rotation_deg"))
    return [[turn[r][i] for r in range(3)] for i in range(3)]


def _stood(body: dict[str, Any], stand: str, along: Any) -> tuple[list[float], float] | None:
    """The sides and the heading (degrees about the vertical) that stand a box
    on end, or lay it down. None for a cube, which has no long side.

    Upright: its longest side up -- of two as long, the one nearer vertical
    already -- and the other two as level as they were, so it keeps the way it
    faces. Lying: its longest side level, along `along` or the way it runs now,
    and its thinnest other side up, which is how a plank lies flat."""
    dims = [float(v) for v in body["dimensions_m"]]
    longest = max(dims)
    if longest - min(dims) < 1e-6:
        return None
    sides = _sides_now(body)
    level = lambda v: (v[0], v[2])                      # noqa: E731
    size = lambda v: math.hypot(v[0], v[1])             # noqa: E731
    longs = [i for i in range(3) if longest - dims[i] < 1e-6]
    if stand == "upright":
        up = max(longs, key=lambda i: abs(sides[i][1]))
        a, b = (i for i in range(3) if i != up)
        ha, hb = level(sides[a]), level(sides[b])
        # The heading that keeps whichever of the two is more level where it is:
        # the new x side along `a`, or the new z side along `b`.
        heading = math.atan2(-ha[1], ha[0]) if size(ha) >= size(hb) else math.atan2(hb[0], hb[1])
        return [dims[a], dims[up], dims[b]], math.degrees(heading)
    long = min(longs, key=lambda i: abs(sides[i][1]))
    thin, wide = sorted((i for i in range(3) if i != long), key=lambda i: dims[i])
    if along is not None:
        run = _triple(along, "along", -1e6, 1e6)
        run = (run[0], run[2])
    else:
        run = level(sides[long]) if size(level(sides[long])) > 1e-3 else level(sides[wide])
    if size(run) < 1e-6:
        run = (1.0, 0.0)
    return [dims[long], dims[thin], dims[wide]], math.degrees(math.atan2(-run[1], run[0]))


def _half_up(dims: list[float], orientation_wxyz: Any) -> float:
    """How far a box reaches below its middle, turned as it is."""
    w, x, y, z = (float(v) for v in orientation_wxyz)
    # Row y of the rotation matrix: how far up each of its own sides points.
    row = [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)]
    return sum(abs(r) * d / 2.0 for r, d in zip(row, dims))


def _under_turned(entry: dict[str, Any], body: dict[str, Any],
                  past: str) -> tuple[float, str, list[tuple[float, float, float]]]:
    """The top of what is under a box turned to `heading`, what that is, and
    each of nine points of its footprint as (across, along, height) -- looking
    straight down past `past`, the thing being turned, which still stands
    where it was."""
    world = _live(entry)
    half_x, half_z = body["dimensions_m"][0] / 2.0, body["dimensions_m"][2] / 2.0
    heading = math.radians(body["rotation_deg"][1])
    ex = (math.cos(heading), -math.sin(heading))     # its own x side, level
    ez = (math.sin(heading), math.cos(heading))      # its own z side, level
    x, _, z = body["center_m"]
    old = world.body(past)
    old_bottom = (old.position_m[1] - _half_up(list(old.dimensions_m), old.orientation_wxyz)
                  if old is not None else None)
    points: list[tuple[float, float, float, str]] = []
    for a in (-0.9, 0.0, 0.9):
        for b in (-0.9, 0.0, 0.9):
            px = x + ex[0] * half_x * a + ez[0] * half_z * b
            pz = z + ex[1] * half_x * a + ez[1] * half_z * b
            top, found = SET_DOWN_FROM_M, world.pick([px, SET_DOWN_FROM_M, pz], [0.0, -1.0, 0.0])
            if found.hit and found.name == past and old_bottom is not None:
                # Through it: what is under it is what it stands on after.
                top = old_bottom - 0.001
                found = world.pick([px, top, pz], [0.0, -1.0, 0.0])
            points.append((a, b, top - found.distance_m, found.name) if found.hit
                          else (a, b, 0.0, ""))
    _, _, top, name = max(points, key=lambda p: p[2])
    under = name or ("the ground" if _has_terrain(entry) else "the floor")
    return top, under, [(a, b, h) for a, b, h, _ in points]


def _box_of(body: dict[str, Any]) -> tuple[list[float], list[list[float]], list[float]]:
    return ([float(v) for v in body["center_m"]], _sides_now(body),
            [float(v) / 2.0 for v in body["dimensions_m"]])


def _dot3(a: Any, b: Any) -> float:
    return sum(float(p) * float(q) for p, q in zip(a, b))


def _overlap_depth(one: dict[str, Any], two: dict[str, Any]) -> float:
    """How deep two scene bodies share space, metres; zero or less when they do
    not. A box against a box by their fifteen separating axes, a ball by its
    distance from a box's faces or from another ball."""
    if one["shape"] == "sphere" and two["shape"] == "sphere":
        return (one["dimensions_m"][0] + two["dimensions_m"][0]) / 2.0 - math.dist(
            one["center_m"], two["center_m"])
    if one["shape"] == "sphere" or two["shape"] == "sphere":
        ball, box = (one, two) if one["shape"] == "sphere" else (two, one)
        centre, sides, half = _box_of(box)
        local = [_dot3([p - c for p, c in zip(ball["center_m"], centre)], s) for s in sides]
        outside = math.sqrt(sum(max(0.0, abs(l) - h) ** 2 for l, h in zip(local, half)))
        radius = ball["dimensions_m"][0] / 2.0
        if outside > 0.0:
            return radius - outside
        return radius + min(h - abs(l) for l, h in zip(local, half))
    c1, a1, h1 = _box_of(one)
    c2, a2, h2 = _box_of(two)
    gap = [q - p for p, q in zip(c1, c2)]
    tests = a1 + a2 + [[u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2],
                        u[0] * v[1] - u[1] * v[0]] for u in a1 for v in a2]
    least = math.inf
    for axis in tests:
        n = math.sqrt(_dot3(axis, axis))
        if n < 1e-9:
            continue
        axis = [v / n for v in axis]
        reach = (sum(h * abs(_dot3(s, axis)) for h, s in zip(h1, a1)) +
                 sum(h * abs(_dot3(s, axis)) for h, s in zip(h2, a2)))
        depth = reach - abs(_dot3(gap, axis))
        if depth <= 0.0:
            return depth
        least = min(least, depth)
    return least


def _settle(entry: dict[str, Any], name: str, put: dict[str, Any]) -> dict[str, Any]:
    """Run the world until `name` is still, and say how far it went from where
    it was put, and how far it turned."""
    world = _live(entry)
    heading = math.radians(put["rotation_deg"][1])
    q_put = [math.cos(heading / 2.0), 0.0, math.sin(heading / 2.0), 0.0]
    dt, per_look = 1.0 / 240.0, 4
    events: list[dict[str, Any]] = []
    t = still = 0.0
    last = None
    while t < TURN_SETTLE_S:
        for _ in range(per_look):
            _step_answering(world, events)
        t += per_look * dt
        body = world.body(name)
        if body is None:
            return {"stays": False, "after_s": round(t, 3), "why": f"{name} broke as it settled",
                    "events": events}
        q = list(body.orientation_wxyz)
        spin = (2.0 * math.acos(min(1.0, abs(_dot3(q, last)))) / (per_look * dt)
                if last is not None else math.inf)
        last = q
        speed = math.sqrt(_dot3(body.velocity_m_s, body.velocity_m_s))
        still = still + per_look * dt if speed < TURN_STILL_M_S and spin < TURN_STILL_RAD_S else 0.0
        if still >= TURN_STILL_S:
            break
    body = world.body(name)
    q = list(body.orientation_wxyz)
    moved = math.dist(body.position_m, put["center_m"])
    turned = math.degrees(2.0 * math.acos(min(1.0, abs(_dot3(q, q_put)))))
    w, x, y, z = q
    up_now = [2 * (x * y - w * z), 1 - 2 * (x * x + z * z), 2 * (y * z + w * x)]   # its own y side
    long_now = [1 - 2 * (y * y + z * z), 2 * (x * y + w * z), 2 * (x * z - w * y)]  # its own x side
    said = {"after_s": round(t, 3), "at_rest": still >= TURN_STILL_S,
            "moved_m": round(moved, 4), "turned_deg": round(turned, 2),
            "position_m": [round(v, 4) for v in body.position_m]}
    if put.get("_stand") == "upright":
        said["long_side_from_vertical_deg"] = round(math.degrees(math.acos(min(1.0, abs(up_now[1])))), 2)
    else:
        said["long_side_from_level_deg"] = round(math.degrees(math.asin(min(1.0, abs(long_now[1])))), 2)
    said["stays"] = said["at_rest"] and moved < STAYS_M and turned < STAYS_DEG
    if events:
        said["events"] = events
    return said


def tool_turn_object(args: dict[str, Any]) -> dict[str, Any]:
    """Stand a thing on end, or lay it down, and set it down at a point -- an
    edit the engine holds to what the world would do with it (see above)."""
    world_id = str(args.get("world_id"))
    entry = _world(world_id)
    _live(entry)
    name = str(args.get("name", ""))
    body = next((b for b in entry["scene"]["bodies"] if b["name"] == name), None)
    if body is None:
        raise Refused(f"there is nothing called {name!r} in this world")
    if body["shape"] != "box":
        raise Refused(f"{name} is a ball: it has no long side to stand it on")
    held = _held_by(entry, name)
    if held:
        raise Refused(f"{name} is held by {len(held)} joint(s): "
                      f"{'; '.join(_joint_words(r) for r in held)}. A joint is made at "
                      f"fixed points, so turning it would leave them behind. unhinge them "
                      f"first, or stand things how they belong before joining them.")
    if body.get("join"):
        raise Refused(f"{name} is built into one piece with everything joined as "
                      f"{body['join']!r}: it cannot be turned on its own")
    if any(b.get("body") == name for b in entry["scene"].get("blades") or []):
        raise Refused(f"{name} has an edge, and the edge is where it is on it: take it by "
                      f"its grip with wield to hold it another way")
    if any(p.get("body") == name for p in entry["scene"].get("tool_points") or []):
        raise Refused(f"{name} has a point that digs, and the point is where it is on it: take "
                      f"it by its grip with wield to hold it another way")
    stand = str(args.get("stand") or "upright").strip().lower()
    if stand not in ("upright", "lying"):
        raise Refused(f"stand is 'upright' (its longest side vertical) or 'lying' (its "
                      f"longest side level), not {stand!r}")
    turned = _stood(body, stand, args.get("along"))
    if turned is None:
        raise Refused(f"{name} is a cube: every side is as long as the others, so it stands "
                      f"the same whichever way up it is. move_object puts it somewhere else.")
    dims, heading = turned
    where = args.get("at_m")
    if where is None:
        x, z = float(body["center_m"][0]), float(body["center_m"][2])
    else:
        if not isinstance(where, (list, tuple)) or len(where) not in (2, 3):
            raise Refused("at_m is where to set it down, [x, z]")
        x = _number(where[0], "at_m", -50.0, 50.0)
        z = _number(where[-1], "at_m", -50.0, 50.0)
    put = dict(body, dimensions_m=dims, rotation_deg=[0.0, round(heading, 4), 0.0],
               center_m=[x, 0.0, z], velocity_m_s=[0.0, 0.0, 0.0])
    top, under, points = _under_turned(entry, put, name)
    # What it stands on has to be under its middle on every side. A thing on
    # the point of a ball, or half over an edge, is not standing on anything,
    # whatever an exactly centred run makes of it: a pillar stood dead on top
    # of a ball balanced there for the whole run, which no ball would allow.
    # "On it" allows the tilt settling may have, STAYS_DEG across the footprint.
    across = 1.8 * max(dims[0], dims[2]) / 2.0
    on = [(a, b) for a, b, h in points
          if h >= top - (0.01 + across * math.tan(math.radians(STAYS_DEG)))]
    carried, of = len(on), len(points)
    if not (any(a < 0 for a, _ in on) and any(a > 0 for a, _ in on)
            and any(b < 0 for _, b in on) and any(b > 0 for _, b in on)):
        raise Refused(f"{name} would not stand {stand} at [{x:.2f}, {z:.2f}]: only {carried} "
                      f"of {of} points under it are on {under}, which is not under its "
                      f"middle on every side, so it would tip off. Nothing was changed. Try "
                      f"level ground, clear of edges -- survey says how steep the ground is.")
    # And it has to rest on a FACE, not on a point or a ridge. Under a flat base
    # on level or sloping ground, each two points opposite each other average to
    # the height under its middle; on the top of a ball they are both lower, and
    # the base would sit on the one point between them and tip off it -- which a
    # run cannot always show: rolling resistance held a loose rubber ball still
    # under a pillar started a third of a degree off, for the whole run.
    height = {(a, b): h for a, b, h in points}
    peak = max(height[(0.0, 0.0)] - (height[(-a, -b)] + height[(a, b)]) / 2.0
               for a, b in ((0.9, 0.0), (0.0, 0.9), (0.9, 0.9), (0.9, -0.9)))
    if peak > 0.003:
        raise Refused(f"{name} would not stand {stand} at [{x:.2f}, {z:.2f}]: {under} rises "
                      f"to a point or a ridge under its middle, {peak * 1000:.0f} mm above "
                      f"either side of it, so it would rest on that and tip off. Nothing was "
                      f"changed. Stand it on something flat.")
    put["center_m"] = [x, round(top + dims[1] / 2.0 + 0.002, 4), z]
    # What it stands on was looked at where it IS, settled a millimetre or two
    # into what is under it; what is rebuilt is where it was BUILT. Lifted clear
    # of that, so standing on a thing is never taken for being in it.
    support = next((b for b in entry["scene"]["bodies"]
                    if b["name"] == under and b is not body), None)
    if support is not None:
        depth = _overlap_depth(put, support)
        if 0.0 < depth < 0.005:
            put["center_m"][1] = round(put["center_m"][1] + depth + 0.001, 4)
    # Nothing may share its space: every other thing in the world as built.
    for other in entry["scene"]["bodies"]:
        if other is body or other.get("subtract"):
            continue
        depth = _overlap_depth(put, other)
        if depth > 0.001:
            raise Refused(f"{name} would overlap {other['name']} by {depth * 1000:.0f} mm "
                          f"standing there. Pick a point at least that much further from "
                          f"it; nothing was changed.")
    before = entry["scene"]
    # Run from a hair off how it is put -- a third of a degree about each level
    # axis -- so that a balance only an exactly centred run can keep is found
    # out. A pillar stood dead on top of a ball stayed there for the whole of a
    # run started exactly upright. A thing that stands rocks back and stays; one
    # on a point falls, within about a second. What is written is the pose as
    # put: the tilt is only where the run starts.
    tried = dict(put, rotation_deg=[TRY_TILT_DEG, put["rotation_deg"][1], TRY_TILT_DEG])
    scene = dict(before, bodies=[tried if b is body else b for b in before["bodies"]])
    lost = _rebuild(entry, scene, world_id)
    settled = _settle(entry, name, dict(put, _stand=stand))
    if not settled["stays"]:
        _rebuild(entry, before, world_id)
        how = settled.get("why") or (
            f"after {settled['after_s']} s it had moved {settled['moved_m']} m and turned "
            f"{settled['turned_deg']} degrees from how it was put"
            + ("" if settled["at_rest"] else ", and it was still moving"))
        raise Refused(f"{name} would not stay {stand} on {under} at [{x:.2f}, {z:.2f}]: "
                      f"{how}. It is back as it was. "
                      + ("Only part of it was over what is under it. " if carried < of else "")
                      + "Try level ground, clear of edges -- survey says how steep the "
                        "ground is.")
    # What the world IS from here: the pose as it was put, not the run's tilt --
    # held to the world's own conditions as well (the playground's room checks
    # every cell), since what they were asked about was the run's pose.
    entry["scene"] = dict(entry["scene"], bodies=[put if b["name"] == name else b
                                                  for b in entry["scene"]["bodies"]])
    check = entry.get("check")
    if check is not None:
        try:
            check(entry["scene"], entry.get("joints", []))
        except ValueError as problem:
            _rebuild(entry, before, world_id)
            raise Refused(f"{problem}. It is back as it was.") from None
    entry["story"].append(f"stood {name} {stand} at [{x:.2f}, {z:.2f}]")
    answer: dict[str, Any] = {
        "turned": name, "stands": stand,
        "at_m": put["center_m"], "size_m_as_it_stands": dims,
        "heading_deg": round(heading, 2), "on": under,
        "settled": {k: v for k, v in settled.items() if k != "stays"},
        "objects": _describe(entry["world"]),
        "note": "An EDIT, like move_object: it is standing there as if it had been built "
                "so. The world was then run until it was still, and it stayed as it was "
                "put; anything else in flight started over, and every joint is hung again."}
    if carried < of:
        answer["overhangs"] = {"points_on_it": f"{carried} of {of}",
                               "note": f"only part of it is over {under}"}
    if lost:
        answer["joints_lost"] = lost
    return answer


# ---------------------------------------------------------------------------
# A thing's actions: what a person does with it, one key each
# ---------------------------------------------------------------------------
#
# The owner, 2026-09-13: looking at a thing shows all your options, and the
# model making it works out what a person would need to do with it -- "a bow
# and arrow would have different actions than a chair" -- and is "given the
# ability to program the execution of it". So whoever makes a thing offers its
# actions: each a label and a short program of steps, every step something the
# engine already does. The room shows them when the person looks at the thing,
# one per number key, and runs the program when the key is pressed: the hand's
# steps in the running room with the hand's own bounded strength, a stand step
# as turn_object with all of its checks. Nothing here moves anything: what
# happens is the engine's answer when the key is pressed.

MAX_ACTIONS = 9             # one per number key
MAX_STEPS = 12
ACTION_LABEL_CHARS = 60
ACTION_STEPS = ("stand", "take_hold", "carry_to", "put_down", "let_go", "push", "turn", "slide",
                "heat", "wait")
# Where a turn or a slide ends, by name: the joint's far stop, half way there,
# its near stop, or where it was when the room was made.
ACTION_STOPS = ("all_the_way", "half_way", "all_the_way_back", "back_to_start")
# What the page already offers everything it applies to (world.js builtinsFor;
# server.py BUILTIN_ACTIONS and JOINT_LABELS -- actions_tests ties the three).
# Offered again as a thing's own, it is the same thing twice on its menu: the
# room's chat spent three rounds programming "Release the latch" onto a latch
# bar, and the third was a program that did nothing a person needs.
PAGE_OFFERS = frozenset({
    "put it on the ground in front of me", "stand it upright", "lay it down where i'm facing",
    "turn it all the way", "turn it half way", "turn it all the way back",
    "turn it back to where it started", "slide it all the way", "slide it half way",
    "slide it all the way back", "slide it back to where it started", "release the latch"})
ACTION_ALONG = ("facing", "across", "x", "z")
ACTION_WHERE = ("here", "in_front")
ACTION_SIDES = ("near", "far", "left", "right")
# Where a step takes the hand, as the model is told it.
ACTION_PLACE = {
    "type": "object", "required": ["kind"],
    "description": "Where the hand goes. kind says which, and only that kind's fields are "
                   "read: in_front -- in_front_m metres in front of the person when the key "
                   "is pressed, its bottom height_m above the ground there (0, or none, is "
                   "resting on it); on "
                   "-- a thing to put it on top of; beside -- a thing to put it next to, with "
                   "side near (between it and the person), far, left or right as the person "
                   "sees it, and gap_m; from -- a thing, with offset_m [dx, dy, dz] from its "
                   "middle.",
    "properties": {"kind": {"type": "string", "enum": ["in_front", "on", "beside", "from"]},
                   "in_front_m": {"type": "number"}, "height_m": {"type": "number"},
                   "on": {"type": "string"}, "beside": {"type": "string"},
                   "side": {"type": "string", "enum": list(ACTION_SIDES)},
                   "gap_m": {"type": "number"}, "from": {"type": "string"},
                   "offset_m": {"type": "array", "items": {"type": "number"},
                                "minItems": 3, "maxItems": 3}}}


def _action_number(value: Any, what: str, low: float, high: float,
                   default: float | None = None) -> float:
    if value is None:
        if default is None:
            raise Refused(f"{what} is needed")
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise Refused(f"{what} is a number from {low:g} to {high:g}") from None
    if not (math.isfinite(number) and low <= number <= high):
        raise Refused(f"{what} is from {low:g} to {high:g}, not {value!r}")
    return number


# What each kind of step, and each kind of place, reads. The room's chat fills
# every field it is shown -- a pick was sent a bow's fields made of its own
# parts, 2026-09-13 ([[banjo-chat-fills-every-field]]) -- and answers a refusal
# by changing values, never by leaving any out: offered a table and a stool, it
# sent every step every field six times over and gave up. So a step reads only
# its kind's fields and a place only its kind's, and the rest is set aside and
# said, as the interaction profiles do.
STEP_FIELDS = {"stand": ("stand", "along", "where"), "take_hold": ("part",),
               "carry_to": ("to", "speed_m_s"), "put_down": (), "let_go": (),
               "push": ("part", "toward", "distance_m", "speed_m_s"),
               "turn": ("part", "degrees", "stop"), "slide": ("part", "distance_m", "stop"),
               "heat": ("part", "power_w", "seconds"), "wait": ("seconds",)}


def _worked_by(entry: dict[str, Any], part: str, tool: str) -> bool:
    """Whether part -- or anything fixed to it, as a winch's handle is to its
    wheel -- turns on a hinge or slides on a slide in this world: what a turn or
    a slide step works it by."""
    records = entry.get("joints", [])
    group, these = {part}, [part]
    while these:
        n = these.pop()
        for r in records:
            a, b = r["args"].get("a"), r["args"].get("b")
            if r.get("tool") == "fix" and n in (a, b):
                other = b if a == n else a
                if other not in group:
                    group.add(other)
                    these.append(other)
    return any(r.get("tool") == tool
               and (r["args"].get("a") in group) != (r["args"].get("b") in group) for r in records)
PLACE_FIELDS = {"in_front": ("in_front_m", "height_m"), "on": ("on",),
                "beside": ("beside", "side", "gap_m"), "from": ("from", "offset_m")}


def _given(value: Any) -> bool:
    return value not in (None, "", [], {})


def _action_place(place: Any, where: str, names: set[str], aside: list[str]) -> dict[str, Any]:
    """A place a step takes the hand to, in the form it is kept in. Its kind
    says which fields are read; without a kind, exactly one kind may be given."""
    if not isinstance(place, dict):
        raise Refused(f"{where}: a place is {{kind, ...}}, kind in_front, on, beside or from")
    kind = place.get("kind")
    if _given(kind):
        kind = str(kind).strip().lower()
        if kind not in PLACE_FIELDS:
            raise Refused(f"{where}: kind is one of {', '.join(PLACE_FIELDS)}, not {kind!r}")
    else:
        present = [k for k in ("in_front_m", "on", "beside", "from") if _given(place.get(k))]
        if len(present) != 1:
            raise Refused(f"{where}: say which kind of place it is -- kind in_front, on, beside "
                          f"or from -- since {' and '.join(present) or 'none of them'} "
                          f"{'was' if len(present) == 1 else 'were'} given")
        kind = "in_front" if present[0] == "in_front_m" else present[0]
    extra = sorted(k for k, v in place.items()
                   if k != "kind" and k not in PLACE_FIELDS[kind] and _given(v))
    if extra:
        aside.append(f"{where}: {', '.join(extra)} (a place {kind} has none)")
    if kind == "in_front":
        out: dict[str, Any] = {"kind": kind, "in_front_m": _action_number(
            place.get("in_front_m"), f"{where}: in_front_m", 0.3, 3.0)}
        if _given(place.get("height_m")):
            out["height_m"] = _action_number(place["height_m"], f"{where}: height_m", 0.0, 2.5)
        return out
    other = str(place.get(kind) or "")
    if other not in names:
        raise Refused(f"{where}: there is nothing called {other!r}")
    if kind == "on":
        return {"kind": kind, "on": other}
    if kind == "beside":
        side = str(place.get("side") or "near").strip().lower()
        if side not in ACTION_SIDES:
            raise Refused(f"{where}: side is one of {', '.join(ACTION_SIDES)}, as the person "
                          f"sees it")
        return {"kind": kind, "beside": other, "side": side,
                "gap_m": _action_number(place.get("gap_m"), f"{where}: gap_m", 0.0, 2.0, 0.3)}
    offset = place.get("offset_m")
    if not isinstance(offset, (list, tuple)) or len(offset) != 3:
        raise Refused(f"{where}: from needs offset_m, [dx, dy, dz] in metres")
    return {"kind": kind, "from": other,
            "offset_m": [_action_number(v, f"{where}: offset_m", -5.0, 5.0) for v in offset]}


def _masses(entry: dict[str, Any]) -> dict[str, float]:
    """What each thing weighs, as the engine has it."""
    if entry.get("world") is None:
        return {}
    return {o["name"]: float(o.get("mass_kg") or 0.0) for o in _describe(entry["world"])}


def _unturnable(entry: dict[str, Any], body: dict[str, Any]) -> str | None:
    """Why turn_object could never turn this thing, or None: what would make
    every set-up offered for it a refusal."""
    name = body["name"]
    if body["shape"] != "box":
        return f"{name} is a ball: it has no long side to stand it on"
    if _held_by(entry, name):
        return f"{name} is held by a joint, and a joint is made at fixed points"
    if body.get("join"):
        return f"{name} is built into one piece with everything joined as {body['join']!r}"
    if any(b.get("body") == name for b in entry["scene"].get("blades") or []):
        return f"{name} has an edge: it is held by its grip, with wield"
    if any(p.get("body") == name for p in entry["scene"].get("tool_points") or []):
        return f"{name} has a point that digs: it is held by its grip, with wield"
    dims = [float(v) for v in body["dimensions_m"]]
    if max(dims) - min(dims) < 1e-6:
        return f"{name} is a cube: it stands the same whichever way up it is"
    return None


def _action_checked(entry: dict[str, Any], name: str, action: Any, names: set[str],
                    masses: dict[str, float], aside: list[str]) -> dict[str, Any]:
    """One action in the form it is kept in, or Refused with why. Checked the
    way the room will run it: the hand holds one thing at a time, and the
    person's hand is free again when the program ends."""
    if not isinstance(action, dict):
        raise Refused("each action is {label, steps}")
    label = " ".join(str(action.get("label") or "").split())
    if not label or len(label) > ACTION_LABEL_CHARS:
        raise Refused(f"each action needs a label of at most {ACTION_LABEL_CHARS} characters, "
                      f"the way a person would say it: {label[:80]!r}")
    if label.lower() in PAGE_OFFERS:
        raise Refused(f"{label!r} is on the page's own menu already, for everything it applies "
                      f"to: offer what the page does not, named for what the thing is for")
    steps = action.get("steps")
    if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_STEPS:
        raise Refused(f"{label!r}: steps is a list of 1 to {MAX_STEPS} steps")
    body = next(b for b in entry["scene"]["bodies"] if b["name"] == name)
    holding: str | None = None
    kept: list[dict[str, Any]] = []
    for i, step in enumerate(steps):
        where = f"{label!r} step {i + 1}"
        if not isinstance(step, dict):
            raise Refused(f"{where}: a step is {{do, ...}}")
        do = str(step.get("do") or "").strip().lower()
        if do not in ACTION_STEPS:
            raise Refused(f"{where}: do is one of {', '.join(ACTION_STEPS)}, not {do!r}")
        named = ("take_hold", "push", "turn", "slide", "heat")
        part = str(step.get("part") or name) if do in named else name
        if do in named and part not in names:
            raise Refused(f"{where}: there is nothing called {part!r}")
        extra = {k for k, v in step.items() if k != "do" and k not in STEP_FIELDS[do] and _given(v)}
        if (do == "stand" and str(step.get("stand") or "upright").strip().lower() != "lying"
                and _given(step.get("along"))):
            extra.add("along")      # upright, its long side is vertical: no way along
        if extra:
            aside.append(f"{where}: {', '.join(sorted(extra))} (a {do} step has none)")
        out: dict[str, Any] = {"do": do}
        if do == "stand":
            if holding:
                raise Refused(f"{where}: stand is not done with {holding} in the hand: "
                              f"put_down or let_go first")
            why = _unturnable(entry, body)
            if why:
                raise Refused(f"{where}: {why}")
            stand = str(step.get("stand") or "upright").strip().lower()
            if stand not in ("upright", "lying"):
                raise Refused(f"{where}: stand is 'upright' or 'lying', not {stand!r}")
            out["stand"] = stand
            if stand == "lying" and _given(step.get("along")):
                along = str(step["along"]).strip().lower()
                if along not in ACTION_ALONG:
                    raise Refused(f"{where}: along is one of {', '.join(ACTION_ALONG)}, not "
                                  f"{along!r}")
                out["along"] = along
            place = str(step.get("where") or "here").strip().lower()
            if place not in ACTION_WHERE:
                raise Refused(f"{where}: where is 'here' or 'in_front', not {place!r}")
            out["where"] = place
        elif do in ("take_hold", "push"):
            if holding:
                raise Refused(f"{where}: the hand already has {holding}: put_down or let_go "
                              f"first")
            target = next(b for b in entry["scene"]["bodies"] if b["name"] == part)
            if target.get("anchored"):
                raise Refused(f"{where}: {part} is fixed in place, and a hand cannot move it")
            kg = masses.get(part)
            if do == "take_hold" and kg is not None and kg > HAND_LIFTS_KG:
                raise Refused(f"{where}: {part} weighs {kg:.0f} kg, more than the "
                              f"{HAND_LIFTS_KG:.0f} kg a hand can hold up: give it a stand "
                              f"step instead")
            out["part"] = part
            if do == "take_hold":
                holding = part
            else:
                out["toward"] = _action_place(step.get("toward"), where, names, aside)
                out["distance_m"] = _action_number(step.get("distance_m"),
                                                   f"{where}: distance_m", 0.05, 1.5, 0.3)
                out["speed_m_s"] = _action_number(step.get("speed_m_s"),
                                                  f"{where}: speed_m_s", 0.1, 1.5, 0.4)
        elif do == "carry_to":
            if not holding:
                raise Refused(f"{where}: carry_to needs something in the hand: take_hold first")
            out["to"] = _action_place(step.get("to"), where, names, aside)
            out["speed_m_s"] = _action_number(step.get("speed_m_s"),
                                              f"{where}: speed_m_s", 0.1, 1.5, 0.5)
        elif do in ("put_down", "let_go"):
            if not holding:
                raise Refused(f"{where}: {do} needs something in the hand")
            holding = None
        elif do in ("turn", "slide"):
            # The hand takes hold of what stands off the pin (for a groove, the
            # part) and carries it round or along -- so the hand must be free,
            # and there must be a pin or a groove to work it by.
            if holding:
                raise Refused(f"{where}: a {do} takes hold itself, and the hand already has "
                              f"{holding}: put_down or let_go first")
            tool = "hinge" if do == "turn" else "slide"
            if not _worked_by(entry, part, tool):
                raise Refused(f"{where}: {part} does not "
                              f"{'turn on a pin' if do == 'turn' else 'slide in a groove'}, and "
                              f"nothing it is fixed to does: give it a {tool} first")
            out["part"] = part
            stop = str(step.get("stop") or "").strip().lower()
            amount = "degrees" if do == "turn" else "distance_m"
            if stop:
                if stop not in ACTION_STOPS:
                    raise Refused(f"{where}: stop is one of {', '.join(ACTION_STOPS)}, not {stop!r}")
                out["stop"] = stop
                if _given(step.get(amount)):
                    aside.append(f"{where}: {amount} (a stop was given, and it says how far)")
            elif do == "turn":
                out["degrees"] = _action_number(step.get("degrees"), f"{where}: degrees",
                                                -360.0, 360.0)
            else:
                out["distance_m"] = _action_number(step.get("distance_m"),
                                                   f"{where}: distance_m", -3.0, 3.0)
            holding = part
        elif do == "heat":
            out["part"] = part
            out["power_w"] = _action_number(step.get("power_w"), f"{where}: power_w",
                                            100.0, 10000.0, 2000.0)
            out["seconds"] = _action_number(step.get("seconds"), f"{where}: seconds",
                                            1.0, 60.0, 10.0)
        elif do == "wait":
            out["seconds"] = _action_number(step.get("seconds"), f"{where}: seconds",
                                            0.1, 10.0, 1.0)
        kept.append(out)
    # Only a last turn or slide may end holding what it worked: that keeps what
    # it raised up until the person lets go.
    if holding and kept[-1]["do"] not in ("turn", "slide"):
        raise Refused(f"{label!r} ends with {holding} still in the hand: end it with put_down "
                      f"or let_go, so the person's hand is free (only a last turn or slide "
                      f"keeps hold, so what it raised stays up)")
    return {"label": label, "steps": kept}


def tool_offer_actions(args: dict[str, Any]) -> dict[str, Any]:
    """Give a thing the actions a person takes with it, kept with it (above)."""
    world_id = str(args.get("world_id"))
    entry = _world(world_id)
    name = str(args.get("name", ""))
    if not any(b["name"] == name for b in entry["scene"]["bodies"]):
        raise Refused(f"there is nothing called {name!r} in this world")
    actions = args.get("actions")
    if not isinstance(actions, list):
        raise Refused("actions is a list, [{label, steps: [...]}, ...]; an empty list takes "
                      "a thing's actions away")
    if len(actions) > MAX_ACTIONS:
        raise Refused(f"at most {MAX_ACTIONS} actions, one per number key: {len(actions)} "
                      f"were given")
    names = {b["name"] for b in entry["scene"]["bodies"]}
    masses = _masses(entry) if actions else {}
    aside: list[str] = []
    kept = [_action_checked(entry, name, action, names, masses, aside) for action in actions]
    labels = [action["label"].lower() for action in kept]
    if len(set(labels)) != len(labels):
        raise Refused("two actions have the same label, and the person has to be able to "
                      "tell them apart. Nothing was changed.")
    offered = {k: v for k, v in (entry.get("actions") or {}).items() if k != name}
    if kept:
        offered[name] = kept
    entry["actions"] = offered
    entry["story"].append(f"offered {len(kept)} action(s) for {name}")
    answer: dict[str, Any] = {
        "offered": name,
        "actions": [{"key": i + 1, **action} for i, action in enumerate(kept)],
        "note": "Shown when the person looks at it, one per number key. Each program runs "
                "when its key is pressed: the hand's steps in the running room with the "
                "hand's own 800 N, a stand step as turn_object with all its checks. What "
                "happens is the engine's answer then, and a step that cannot be done stops "
                "the action with why."}
    if aside:
        answer["not_read"] = ("; ".join(aside) + ". Set aside: a step reads only its own "
                              "kind's fields, and a place only its kind's.")
    return answer


# ---------------------------------------------------------------------------
# What a person knows (docs/knowledge-and-progression.md, increment 2)
# ---------------------------------------------------------------------------
#
# The knowledge layer sits above the physics and never inside it: nothing here
# changes a world, and no tool can add to what a person knows. A world can carry
# the journal of the person it belongs to -- the playground attaches its
# person's, read-only, to the chat's copy of their room -- and a world that
# carries none knows nothing yet.

_REGISTRY: progression.Registry | None = None


def _registry() -> progression.Registry:
    """The curated graph, loaded -- and checked -- the first time it is asked
    for. A graph that does not hold together is refused here, with why, rather
    than served; the rest of the MCP works without it."""
    global _REGISTRY
    if _REGISTRY is None:
        try:
            _REGISTRY = progression.Registry()
        except progression.DefinitionError as failure:
            raise Refused(f"the knowledge graph does not load: {failure}") from None
    return _REGISTRY


def tool_read_knowledge(args: dict[str, Any]) -> dict[str, Any]:
    """What the person this world belongs to knows. Spends nothing."""
    entry = _world(str(args.get("world_id")))
    journal = entry.get("journal")
    if not isinstance(journal, progression.Journal):
        journal = progression.Journal()
    said = progression.notebook(journal, _registry())
    said["note"] = ("What this person knows and what the engine measured their things doing, "
                    "each claim scoped to what was tried. No tool can add to it: it grows only "
                    "from engine results of their own hand in their own world. A design "
                    "demonstrated here is demonstrated only for the use and the ground named.")
    return said


def tool_clear_world(args: dict[str, Any]) -> dict[str, Any]:
    """Empty a world of everything, joints and all, to build it again."""
    entry = _world(args.get("world_id"))
    count = len(entry["scene"]["bodies"])
    joints = len(entry.get("joints", []))
    old = entry.get("world")
    scene = dict(entry["scene"], bodies=[])
    scene.pop("thermo", None)
    scene.pop("blades", None)
    scene.pop("tool_points", None)
    entry["scene"] = scene
    entry["joints"] = []
    # And how anything in it was used: there is nothing left to use.
    if entry.get("interactions"):
        entry.setdefault("withdrawn", []).extend(
            {"object": p["object"], "why": "the world was cleared"}
            for p in entry["interactions"])
        entry["interactions"] = []
    # Nor anything left to do anything with.
    entry.pop("actions", None)
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
    # What it is made of and how much of its cold strength is left, when it
    # was made of something (docs/thermal-mechanics.md); and, once it has let
    # go, why -- the load the solver measured against what it could still take.
    if joint.member:
        common["made_of"] = joint.member
        common["strength_left_pct"] = round(100.0 * joint.capacity_fraction, 1)
    if joint.parted_because:
        common["why_it_let_go"] = joint.parted_because
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
                "holds_shear_n": round(joint.holds_shear_n, 2),
                **({"comes_off_n": round(joint.comes_off_n, 2)}
                   if joint.comes_off_n > 0.0 else {})}
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
    member = _member(args)
    try:
        joint = world.tie(
            str(args.get("a", "")), str(args.get("b", "")),
            _triple(args.get("at_a_m"), "at_a_m", -200.0, 200.0),
            _triple(args.get("at_b_m"), "at_b_m", -200.0, 200.0),
            _number(args.get("length_m", 0.0), "length_m", 0.0, 100.0),
            _number(args.get("breaks_at_n", 0.0), "breaks_at_n", 0.0, 1e9),
            member=member)
    except banjo.BanjoError as error:
        raise Refused(str(error))
    answer = {"joint": joint,
              "note": f"{args.get('b')} is tied to {args.get('a')}. The rope pulls "
                      "and cannot push, so it does nothing at all while there is "
                      "slack. Read tension_n from `joints` to see what it carries."}
    if member:
        answer["made_of"] = _made_of_said(world, joint, member)
    return answer


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
                 "holds_mpa": round(load.strength_pa / 1e6, 3),
                 # 100 for anything heat has not touched: what its heated section
                 # can still take, against the same beam cold.
                 "section_strength_left_pct": round(100.0 * load.capacity_fraction, 1),
                 "why": load.why}
                for load in sagging],
            "note": "nothing struck these -- they are carrying too much standing "
                    "still. Break one with `drop`-style fracture and it comes "
                    "apart under its own load; the threshold is necessary and "
                    "not sufficient, as everywhere else here."
                    if sagging else "nothing is carrying more than it can hold"}


def tool_fix(args: dict[str, Any]) -> dict[str, Any]:
    """Fix one named thing to another: a peg, a bracket, a catch, a locking bar."""
    world: banjo.World = _live(_world(args.get("world_id")))
    member = _member(args)
    comes_off = _number(args.get("comes_off_n", 0.0), "comes_off_n", 0.0, 1e9)
    try:
        joint = world.fix(
            str(args.get("a", "")), str(args.get("b", "")),
            _triple(args.get("at_m"), "at_m", -200.0, 200.0),
            _triple(args.get("axis", [0.0, 1.0, 0.0]), "axis", -1e6, 1e6),
            _number(args.get("holds_tension_n", 0.0), "holds_tension_n", 0.0, 1e9),
            _number(args.get("holds_shear_n", 0.0), "holds_shear_n", 0.0, 1e9),
            member=member, comes_off_n=comes_off)
    except banjo.BanjoError as error:
        raise Refused(str(error))
    if comes_off > 0.0:
        note = (f"{args.get('b')} sits on {args.get('a')} ONE WAY: pushed back into "
                f"it, it takes whatever the push is; pulled along the axis it is held "
                f"with up to {comes_off:g} N, and harder than that it comes off by "
                f"itself. That is how an arrow leaves a string -- nothing lets it go.")
    else:
        note = (f"{args.get('b')} and {args.get('a')} are now one piece. "
                "Release it with `unhinge` -- that is what a latch is, and "
                "doing it changes what the assembly can do.")
    answer = {"joint": joint, "note": note}
    if member:
        answer["made_of"] = _made_of_said(world, joint, member)
    return answer


def tool_spring(args: dict[str, Any]) -> dict[str, Any]:
    """Put an elastic element between two named things: a bow limb, a spring."""
    world: banjo.World = _live(_world(args.get("world_id")))
    member = _member(args)
    try:
        joint = world.spring(
            str(args.get("a", "")), str(args.get("b", "")),
            _triple(args.get("at_a_m"), "at_a_m", -200.0, 200.0),
            _triple(args.get("at_b_m"), "at_b_m", -200.0, 200.0),
            _number(args.get("rest_m", 0.0), "rest_m", 0.0, 100.0),
            _number(args.get("stiffness_n_m", 1000.0), "stiffness_n_m", 0.001, 1e9),
            _number(args.get("damping_n_s_m", 0.0), "damping_n_s_m", 0.0, 1e9),
            member=member)
    except banjo.BanjoError as error:
        raise Refused(str(error))
    answer = {"joint": joint,
              "note": "an ideal linear spring: force is stiffness times extension "
                      "and stored energy is half that times the extension again. "
                      "Read stored_j from `joints` to see what it is holding -- "
                      "and anything you throw with it gets its speed from that, "
                      "not from a number you choose."}
    if member:
        answer["made_of"] = _made_of_said(world, joint, member)
    return answer


# ---------------------------------------------------------------------------
# Things a person uses (docs/interaction-profiles.md)
# ---------------------------------------------------------------------------
#
# A bow here is a grip, two limbs, a string and a nock, and every one of them is
# an ordinary joint. What makes it a BOW to a person is what they do with it:
# take it up, draw the string back, let go. That is its profile -- which bodies
# are the object, which part the hand draws and which way, which joint lets go,
# which joints hold the draw -- and never what the physics does. Declared with
# `interaction`, it is held to the rules against what is built, kept through
# every rebuild, withdrawn with the reason when what it names is taken away, and
# TRIED: drawn with a person's hand and loosed in a scratch world, so whoever
# made it is told what it stored and what it shot with before anybody picks it
# up.

# The joining calls, and the room's names for the joints they make.
JOINT_KINDS = {"hinge": "hinge", "slide": "slider", "tie": "link", "reeve": "pulley",
               "fix": "fixing", "spring": "elastic"}

# A trial steps as the playground's room does (playground/world.js, LIVE_DT),
# with the engine's own hand, which is the person's.
TRIAL_STEP_S = 1.0 / 240.0


def _authored_joints(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The joints as they were BUILT, from the calls that made them -- not what
    the world is doing now. A nock an arrow has just come off, in a run or a
    trial, is still the nock the bow was built with."""
    return [{"kind": JOINT_KINDS.get(r["tool"], r["tool"]),
             "a": r["args"].get("a"), "b": r["args"].get("b"),
             "axis": list(r["args"].get("axis") or [0.0, 1.0, 0.0]),
             "comes_off_n": float(r["args"].get("comes_off_n") or 0.0)}
            for r in records]


def _profile_checked(entry: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    """A profile held to the rules against what is built. Raises ValueError."""
    return interaction_profiles.check(profile, {b["name"] for b in entry["scene"]["bodies"]},
                                      _authored_joints(entry.get("joints", [])),
                                      points={p.get("body") for p in
                                              entry["scene"].get("tool_points") or []})


def _use_said(profile: dict[str, Any]) -> dict[str, Any]:
    """A thing a person uses, in a line: what it is, how, and what it is made of."""
    said = {"object": profile["object"], "template": profile["template"], "parts": profile["parts"]}
    if profile["template"] == "swing-and-lever":
        return {**said, "swings": profile["tool"]}
    return {**said, "draws": profile["draw"]["part"], "shoots": profile["projectile"]}


def _recheck_interactions(entry: dict[str, Any]) -> None:
    """After what is built has changed: a profile that names a part or a joint
    that is gone is withdrawn, and why is kept for the answer to the call that
    did it (see _saying_what_was_withdrawn). A bow whose arrow was taken away is
    not a bow anyone can loose, and saying nothing would leave it looking like
    one until somebody tried."""
    kept, gone = [], []
    for profile in entry.get("interactions", []):
        try:
            _profile_checked(entry, profile)
            kept.append(profile)
        except ValueError as problem:
            gone.append({"object": profile["object"], "why": str(problem)})
    if gone:
        entry["interactions"] = kept
        entry.setdefault("withdrawn", []).extend(gone)


def _saying_what_was_withdrawn(handler: Any) -> Any:
    """The tool, with anything its change withdrew said in its answer."""
    def run(args: dict[str, Any]) -> Any:
        answer = handler(args)
        entry = WORLDS.get(str(args.get("world_id")))
        gone = entry.pop("withdrawn", None) if entry is not None else None
        if gone and isinstance(answer, dict):
            answer = {**answer, "interactions_withdrawn": gone}
        return answer

    run.__name__ = getattr(handler, "__name__", "tool")
    run.__doc__ = handler.__doc__
    return run


# The fields only one kind of use has. A caller that fills in every field it is
# offered -- a model whose function calls carry every property -- sends the
# other kind's too. Measured in the room, asked for a pick: once the chat sent
# a swing-and-lever with a blank draw, nock, limbs and projectile, and was
# refused twelve times; once it filled them with the pick's own parts -- the
# haft drawn along no axis, nocked to the arm -- and, refused, sent them again
# with new numbers, twelve times, never once leaving them out. A template said
# is what the caller means: what the other kind has and it has not is set
# aside, and the answer says so -- unless it would make a working thing of the
# other kind, a real nock and real limbs, when the call says two things and is
# refused. With no template said a profile is a draw-and-release, and a tool
# may be the only sign a pick was meant: there blanks are dropped, and a field
# that says something is held to the rules, and refused.
_ONLY_IN = {"draw-and-release": ("draw", "nock", "limbs", "projectile"),
            "swing-and-lever": ("tool", "use")}


def _blank(value: Any) -> bool:
    if value is None or (isinstance(value, bool) and not value):
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value == 0
    if isinstance(value, (list, tuple)):
        return all(_blank(v) for v in value)
    if isinstance(value, dict):
        return all(_blank(v) for v in value.values())
    return False


def _set_aside(entry: dict[str, Any], profile: dict[str, Any],
               said: bool) -> tuple[dict[str, Any], list[str]]:
    """A profile less the other kind's fields, and which of them said something.

    Blanks always go. With the template said the rest go too, unless they would
    make a working profile of the other kind, which raises ValueError; with none
    said they stay, to be held to the rules."""
    out = dict(profile)
    if out.get("template") not in interaction_profiles.TEMPLATES:
        return out, []
    aside: list[str] = []
    for kind, fields in _ONLY_IN.items():
        if kind == out["template"]:
            continue
        for field in fields:
            if field in out and _blank(out[field]):
                del out[field]
        sent = [field for field in fields if field in out]
        if not said or not sent:
            continue
        try:
            _profile_checked(entry, {"object": out.get("object"), "template": kind,
                                     "parts": out.get("parts"),
                                     **{field: out[field] for field in sent}})
        except (ValueError, TypeError, KeyError, AttributeError):
            # Whatever keeps it from being one: it says nothing that works.
            for field in sent:
                del out[field]
            aside += sent
            continue
        name = str(out.get("object") or "it").strip()[:80]
        raise ValueError(f"{name}: said to be a {out['template']}, but its {', '.join(sent)} "
                         f"make a working {kind} -- say which it is: template {kind}, or "
                         f"{', '.join(sent)} left empty")
    return out, sorted(aside)


def tool_interaction(args: dict[str, Any]) -> dict[str, Any]:
    """Say how a person uses a thing, hold it to what is built, and try it."""
    entry = _world(args.get("world_id"))
    profile = {k: v for k, v in args.items() if k not in ("world_id", "trial")}
    if isinstance(profile.get("use"), dict):
        # The chat fills every field it is shown, and an empty one says nothing:
        # left in, a 0 m/s swing would be refused, and it answers a refusal by
        # changing values, never by leaving one out.
        use = {k: v for k, v in profile["use"].items() if isinstance(v, bool) or not _blank(v)}
        for key in ("swing", "lever"):
            if isinstance(use.get(key), dict):
                use[key] = {f: v for f, v in use[key].items() if not _blank(v)}
                if not use[key]:
                    del use[key]
        if use:
            profile["use"] = use
        else:
            del profile["use"]
    said = bool(profile.get("template"))
    if not said:
        profile["template"] = "draw-and-release"
    try:
        profile, aside = _set_aside(entry, profile, said)
        checked = _profile_checked(entry, profile)
    except ValueError as problem:
        raise Refused(str(problem)) from None
    if checked["template"] == "draw-and-release":
        draw = profile["draw"]
        checked["draw"]["max_m"] = _number(draw.get("max_m", 0.45), "draw max_m", 0.02, 3.0)
        checked["draw"]["speed_m_s"] = _number(draw.get("speed_m_s", 0.4), "draw speed_m_s",
                                               0.01, 5.0)
    # One profile to an object, and one to a tool: said again -- under a new
    # name too, a pick built by recipe and then called "the mattock" -- it is
    # what it says now. Left, the page found the old one first.
    entry["interactions"] = [p for p in entry.get("interactions", [])
                             if p["object"] != checked["object"]
                             and not (checked["template"] == "swing-and-lever"
                                      and p.get("template") == "swing-and-lever"
                                      and p.get("tool") == checked.get("tool"))] + [checked]
    answer: dict[str, Any] = dict(checked)
    if aside:
        answer["not_read"] = (f"{', '.join(aside)}: a {checked['template']} has none, so what "
                              f"was sent for them was set aside")
    if checked["template"] == "swing-and-lever":
        use = interaction_profiles.tool_use(checked)
        then = ("pries it -- turned about where it went in -- and draws it out, breaking out "
                "what the pry can, and what comes loose is carried" if use["lever"] else
                "draws it straight back out: this one is only swung, never pried")
        answer["how_a_person_uses_it"] = (
            f"In the playground a person takes {checked['object']} up with E near any of its "
            f"parts, by the grip its point was given with. A ring on the ground shows where it "
            f"will come down -- green where it can work, amber when that is too far or too "
            f"near (it comes down {use['reach_m'][0]:g} to {use['reach_m'][1]:g} m in front of "
            f"them), red on bare rock -- and one click of the left mouse button, "
            f"'{use['label']}', does the whole of it: the hand raises it back over their "
            f"shoulder and brings the point down there at {use['swing']['speed_m_s']:g} m/s, "
            f"with an 800 N hand and a 60 N m wrist, the ground decides how far it goes in, "
            f"and the hand {then}."
            + (" Holding the button keeps going; the right button stops it." if use["repeat"]
               else "")
            + " E puts it down.")
        if args.get("trial", True):
            answer["trial"] = _trial_swing(entry, checked)
        return answer
    answer["how_a_person_uses_it"] = (
        f"In the playground a person takes {checked['object']} up with E on any of its "
        f"parts, holds the left mouse button to draw {checked['draw']['part']} back -- with "
        f"an 800 N hand, which stops where the limbs balance it or at "
        f"{checked['draw']['max_m']:g} m -- and lets go to shoot; the right mouse button "
        f"lets it down again.")
    if args.get("trial", True):
        answer["trial"] = _trial(entry, checked)
    return answer


def _trial(entry: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    """Draw it with a person's hand and loose it, in a scratch world.

    Never the world it was built in: a scratch world opened from what was
    built, holding the object and whatever is joined to it -- a bow on a stand
    is a bow and its stand -- so what is tried is the object as built, and
    nothing a caller holds is touched. Drawn the way the playground draws it:
    the draw's part taken, stroked back along the draw at the draw's speed
    until the limbs balance the hand or it gets to max_m, held a moment, and
    let go.
    """
    import time as clock
    began = clock.perf_counter()
    names = set(profile["parts"])
    grew = True
    while grew:
        grew = False
        for record in entry.get("joints", []):
            ends = {record["args"].get("a"), record["args"].get("b")}
            if ends & names and not ends <= names:
                names |= ends
                grew = True
    scene = {k: v for k, v in entry["scene"].items()
             if k not in ("bodies", "blades", "thermo", "terrain", "water", "tool_points")}
    scene["bodies"] = [b for b in entry["scene"]["bodies"] if b["name"] in names]
    try:
        world = banjo.World(scene, cell_size_m=entry["cell_m"])
    except banjo.BanjoError as error:
        return {"tried": False, "why": f"it would not open on its own: {error}"}
    scratch = "trial-" + uuid.uuid4().hex[:8]
    WORLDS[scratch] = {"world": world, "scene": scene, "cell_m": entry["cell_m"],
                       "story": [], "joints": [], "next_joint": 1, "carried": {}}
    try:
        for record in entry.get("joints", []):
            if {record["args"].get("a"), record["args"].get("b")} <= names:
                MAKE_JOINT[record["tool"]]({**record["args"], "world_id": scratch})
        said = _draw_and_loose(world, profile)
    except (Refused, banjo.BanjoError) as problem:
        said = {"tried": False, "why": str(problem)}
    finally:
        WORLDS.pop(scratch, None)
        world.close()
    said["computing_took_s"] = round(clock.perf_counter() - began, 2)
    return said


def _trial_swing(entry: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    """Swing it at the ground and pry it, as a person would, in a scratch world.

    Never the world it was built in: a scratch world opened from what was
    built -- the tool, whatever is joined to it, and the ground with every edit
    made to it -- so what is tried is the tool as built on the ground as it is,
    and nothing a caller holds is touched. The hand takes it by its grip, holds
    it ready in front of a person, swings its point down on the nearest level
    soil and pries it out, then swings it at the nearest level bare rock: what
    the ground did each time is ground-work-v1's, measured off the solver.
    """
    import time as clock
    began = clock.perf_counter()
    if not entry["scene"].get("terrain"):
        return {"tried": False,
                "why": "there is no ground here to swing it at: make_terrain gives the world "
                       "ground, and a clearing has soil and rock side by side"}
    names = set(profile["parts"])
    joins = {b.get("join") for b in entry["scene"]["bodies"] if b["name"] in names and b.get("join")}
    names |= {b["name"] for b in entry["scene"]["bodies"] if b.get("join") and b["join"] in joins}
    grew = True
    while grew:
        grew = False
        for record in entry.get("joints", []):
            ends = {record["args"].get("a"), record["args"].get("b")}
            if ends & names and not ends <= names:
                names |= ends
                grew = True
    scene = {k: v for k, v in entry["scene"].items()
             if k not in ("bodies", "blades", "thermo", "water", "tool_points")}
    scene["bodies"] = [b for b in entry["scene"]["bodies"] if b["name"] in names]
    points = [p for p in entry["scene"].get("tool_points") or [] if p.get("body") in names]
    try:
        world = banjo.World(scene, cell_size_m=entry["cell_m"])
    except banjo.BanjoError as error:
        return {"tried": False, "why": f"it would not open on its own: {error}"}
    scratch = "trial-" + uuid.uuid4().hex[:8]
    WORLDS[scratch] = {"world": world, "scene": scene, "cell_m": entry["cell_m"],
                       "story": [], "joints": [], "next_joint": 1, "carried": {}}
    try:
        for record in entry.get("joints", []):
            if {record["args"].get("a"), record["args"].get("b")} <= names:
                MAKE_JOINT[record["tool"]]({**record["args"], "world_id": scratch})
        _, dropped = _arm_tool_points(world, points)
        said = ({"tried": False, "why": "; ".join(dropped)} if dropped
                else _swing_and_pry(world, profile["tool"], interaction_profiles.tool_use(profile)))
    except (Refused, banjo.BanjoError) as problem:
        said = {"tried": False, "why": str(problem)}
    finally:
        WORLDS.pop(scratch, None)
        world.close()
    said["computing_took_s"] = round(clock.perf_counter() - began, 2)
    return said


def _trial_targets(world: banjo.World, near: list[float]) -> dict[str, list[float] | None]:
    """The nearest level soil deep enough for a point to go into, and the
    nearest level bare rock, to `near` -- each the same for a quarter metre all
    round, so a swing at one does not land on the step between them. Within
    4 m, and not right under it. None where there is none."""
    def kind(here: dict[str, Any]) -> str | None:
        if not here.get("on_the_ground") or here.get("water") or here.get("slope_deg", 90.0) > 5.0:
            return None
        if here.get("surface") == "rock":
            return "rock"
        return "soil" if float(here["ground_m"]) - float(here["rock_top_m"]) >= 0.3 else None

    found: dict[str, list[float] | None] = {"soil": None, "rock": None}
    spots = sorted(((near[0] + 0.2 * i, near[2] + 0.2 * j) for i in range(-20, 21)
                    for j in range(-20, 21)),
                   key=lambda s: (math.hypot(s[0] - near[0], s[1] - near[2]), s))
    for x, z in spots:
        distance = math.hypot(x - near[0], z - near[2])
        if distance < 0.6 or distance > 4.0:
            continue
        here = world.survey(x, z)
        what = kind(here)
        if what is None or found[what] is not None:
            continue
        if all(kind(world.survey(x + dx, z + dz)) == what
               for dx, dz in ((0.25, 0.0), (-0.25, 0.0), (0.0, 0.25), (0.0, -0.25))):
            found[what] = [round(x, 3), float(here["ground_m"]), round(z, 3)]
        if found["soil"] is not None and found["rock"] is not None:
            break
    return found


def _swing_and_pry(world: banjo.World, tool: str,
                   use: dict[str, Any] | None = None) -> dict[str, Any]:
    """The trial, measured off the engine: into soil and pried out, then onto
    rock -- each swung from where a person would stand, with the hand the room
    gives them, the way the tool's profile says it is used (use: swing, lever;
    interaction_profiles.tool_use) -- the same numbers the playground swings it
    with."""
    use = use or interaction_profiles.tool_use(None)
    swing = use["swing"]
    lever = use["lever"]
    events: list[dict[str, Any]] = []
    dt = TRIAL_STEP_S
    passed = 0.0

    def advance(seconds: float) -> None:
        nonlocal passed
        for _ in range(int(round(seconds / dt))):
            _step_answering(world, events)
            passed += dt

    # Standing, as a room has stood before anyone walks up to it.
    advance(0.5)
    point = next((p for p in world.tool_points() if p.body == tool and p.attached), None)
    body = world.body(tool)
    if point is None or body is None:
        return {"tried": False, "why": f"{tool} is not there to try"}
    targets = _trial_targets(world, list(point.grip_m))
    if targets["soil"] is None and targets["rock"] is None:
        return {"tried": False, "why": "there is no level soil or bare rock within 4 m of it to "
                                       "swing it at"}
    world.wield(tool, list(point.grip_m))
    said: dict[str, Any] = {"tried": True, "tool": tool, "mass_kg": round(body.mass_kg, 3)}
    for what in ("soil", "rock"):
        at = targets[what]
        if at is None:
            said[f"into_{what}"] = f"there is no level {what} within 4 m of it to try"
            continue
        shoulder = _shoulder_for(world, at, list(world.hand().grip_m))
        ux, uz = at[0] - shoulder[0], at[2] - shoulder[2]
        size = math.hypot(ux, uz) or 1.0
        # Taken up and held ready in front of the shoulder, as a person does.
        world.move_held([shoulder[0] + READY_OUT_M * ux / size, shoulder[1] - READY_DOWN_M,
                         shoulder[2] + READY_OUT_M * uz / size])
        advance(1.0)
        world.forget_ground_work()
        try:
            world.strike(at, shoulder, swing["speed_m_s"], swing["raise_deg"], False,
                         (lever or interaction_profiles.TOOL_USE_DEFAULTS["lever"])["lever_deg"], 3.0)
        except banjo.BanjoError as error:
            said[f"into_{what}"] = f"the swing was refused: {error}"
            continue
        took, ended = _play_stroke(world, events, 6.0, 0.5)
        passed += took
        trial: dict[str, Any] = {"at_m": at, "standing_m": [round(shoulder[0], 3), round(shoulder[2], 3)],
                                 "stroke_ended": ended}
        work = world.ground_work()
        trial["swung"] = [_ground_work_said(w) for w in work] or "its point met no ground"
        if what == "soil" and any(w.open for w in work):
            if lever:
                world.strike(None, shoulder, lever["speed_m_s"], 0.0, True, lever["lever_deg"], 3.0)
                took, trial["lever_ended"] = _play_stroke(world, events, 6.0, 0.3)
                passed += took
            if world.held and any(w.open for w in world.ground_work()):
                passed += _pull_out(world, events)
                trial["then"] = "drawn straight up out of the ground"
            trial["levered" if lever else "drawn_out"] = [_ground_work_said(w)
                                                          for w in world.ground_work()]
        said[f"into_{what}"] = trial
    body = world.body(tool)
    said["tool_whole"] = body is not None
    said["what_broke"] = events or None
    said["simulated_s"] = round(passed, 2)
    return said


def _draw_and_loose(world: banjo.World, profile: dict[str, Any]) -> dict[str, Any]:
    """The trial, measured off the engine: how far the hand drew it, how hard it
    pulled, what the limbs held, and what the projectile left with at the step
    the nock let it go -- with `sound` false, and why, when the shot is not one
    the engine followed.

    At the step it comes off, and not the fastest it is ever seen: on the
    courtyard's bow the string and the arrow ran together at 8.59 m/s, the
    nock's grip took 0.29 m/s back over the two steps the arrow slid off it,
    and it flew free at 8.30.
    """
    dt = TRIAL_STEP_S

    def advance(seconds: float, until: Any = None) -> float:
        passed = 0.0
        while passed < seconds - 1e-9:
            # Something about to break is answered, as `run` answers it, or the
            # world waits at that step for ever.
            if world.step(dt) == banjo.BREAK_PENDING:
                for name in world.breakable():
                    world.fracture(name)
            passed += dt
            if until is not None and until():
                break
        return passed

    draw = profile["draw"]
    part, axis, projectile = draw["part"], draw["axis"], profile["projectile"]
    shot = [-v for v in axis]
    limbs = [frozenset(pair) for pair in profile["limbs"]]
    nock = frozenset((profile["nock"]["a"], profile["nock"]["b"]))

    def seated() -> bool:
        return any(j.kind == "fixing" and j.attached and frozenset((j.a, j.b)) == nock
                   for j in world.joints())

    def along(v: Any) -> float:
        return sum(float(v[k]) * shot[k] for k in range(3))

    # Standing, as a room has stood before anyone walks up to it.
    advance(0.5)
    string, arrow = world.body(part), world.body(projectile)
    if string is None or arrow is None:
        return {"tried": False,
                "why": f"{part if string is None else projectile} is not there to try"}
    kg = arrow.mass_kg
    brace = list(string.position_m)
    world.grab(part)
    world.stroke([brace, [brace[i] + axis[i] * draw["max_m"] for i in range(3)]],
                 draw["speed_m_s"], 2.0, 0.05, False, 30.0)
    advance(draw["max_m"] / draw["speed_m_s"] + 4.0, until=lambda: not world.hand().stroking)
    advance(0.25)    # held a moment, as a person holds a draw
    hand = world.hand()
    string = world.body(part)
    if string is None:
        return {"tried": False, "why": f"{part} did not survive being drawn"}
    held = sum(j.stored_j for j in world.joints()
               if j.kind == "elastic" and j.attached and frozenset((j.a, j.b)) in limbs)
    said: dict[str, Any] = {
        "tried": True,
        "drawn_m": round(along([brace[i] - string.position_m[i] for i in range(3)]), 3),
        "hand_pulled_n": round(math.sqrt(sum(f * f for f in hand.force_n)), 1),
        "draw_ended": ("the limbs balanced the hand before it got to max_m"
                       if hand.stroke_ended == "blocked" else
                       "it got to max_m" if hand.stroke_ended == "reached" else
                       hand.stroke_ended or "the hand was still drawing"),
        "limbs_held_j": round(held, 2),
        "projectile_kg": round(kg, 3)}
    on = seated()
    # While it is on the string nothing can slow it much faster than the nock's
    # grip, what it rubs on and gravity can: the grip is comes_off_n at most,
    # gravity along the shot at most its weight, and a rest rubbing it -- which
    # the nock can press it onto -- a few times its weight. A step that takes
    # three times that off it is not friction; it is the engine failing to
    # follow the shot. Measured on this kind of bow: a slow shot lost 0.18 m/s
    # in one step to the grip and the rest together, where the bound below is
    # 0.55; and a false sweep hit, before every edge was made round (see
    # JoltWorld's kSweepRadiusM), took an arrow from 5.58 m/s to -2.54 in one.
    grip = max((j.comes_off_n for j in world.joints()
                if j.kind == "fixing" and frozenset((j.a, j.b)) == nock), default=0.0)
    most = 3.0 * dt * (grip / max(kg, 1e-6) + 9.81 * (1.0 + abs(shot[1]))) + 0.05
    world.release()
    if not on:
        said.update(sound=False, why=[f"{projectile} was not on {part} when it was loosed"])
        return said
    came_off, left, passed, was, lurch = None, None, 0.0, 0.0, None
    while passed < 1.0:
        passed += advance(dt)
        body = world.body(projectile)
        now = along(body.velocity_m_s) if body is not None else 0.0
        if not seated():
            came_off, left = passed, (body.velocity_m_s if body is not None else (0.0, 0.0, 0.0))
            break
        if lurch is None and was - now > most:
            lurch = (f"{projectile} went from {was:.2f} to {now:.2f} m/s along the shot in "
                     f"one step while still on {part}, {passed:.3f} s after the loose -- "
                     f"more than its nock's {grip:g} N grip, what it rubs on and gravity "
                     f"could take off it")
        was = now
    if came_off is None:
        said.update(sound=False, why=[f"{projectile} did not come off {part} within a "
                                      f"second of the loose"] + ([lurch] if lurch else []))
        return said
    speed, forward = math.sqrt(sum(v * v for v in left)), along(left)
    share = 0.5 * kg * speed * speed / held if held > 1e-6 else 0.0
    said.update({"came_off_after_s": round(came_off, 3),
                 "left_m_s": round(speed, 2),
                 "left_along_the_shot_m_s": round(forward, 2),
                 "share_of_what_the_limbs_held_pct": round(100.0 * share, 1)})
    # Then a moment more. Clear of the bow, nothing should act on it but
    # gravity, which along a shot aimed downwards adds a little.
    struck, fastest = False, forward
    for _ in range(int(round(0.15 / dt))):
        advance(dt)
        struck = struck or any({h.struck, h.by} == {projectile, part} for h in world.impacts(0.05))
        body = world.body(projectile)
        if body is not None:
            fastest = max(fastest, along(body.velocity_m_s))
    fall = max(0.0, -9.81 * shot[1]) * 0.15
    why = [lurch] if lurch else []
    # Backwards and meaning it. Drawn only a little, an arrow barely moves, and
    # the string coming back past brace can drag it back a hair before it slides
    # off -- measured, 147 mm on 6 kN/m came off at -0.03 m/s. A weak shot, and a
    # physical one.
    if forward < -0.1:
        why.append(f"{projectile} came off moving backwards, {forward:.2f} m/s along the shot")
    if share > 1.05:
        why.append(f"{projectile} left with {100.0 * share:.0f}% of what the limbs held, "
                   f"which is more than there was")
    if struck:
        why.append(f"{part} struck {projectile} after it had come off")
    if fastest > forward + fall + 0.05 * max(1.0, abs(forward)):
        why.append(f"something drove {projectile} on after it came off: it was doing "
                   f"{fastest:.2f} m/s along the shot within 0.15 s")
    said["sound"] = not why
    if why:
        said["why"] = why
        said["note"] = ("an unsound trial is the engine not following this shot, not what "
                        "the thing does: do not give its speed as the thing's")
    return said


# ---------------------------------------------------------------------------
# Another one like it
# ---------------------------------------------------------------------------
#
# Asked for "a second bow beside the courtyard's, but stiffer", a model has to
# add one offset to forty numbers, and it does not. Measured: the playground's
# chat put the copy's tips 0.2 m from where the recipe had them, the string's
# centre where one of its ropes was made off, and the whole bow in the first
# one's line of fire with its arrow inside the gate -- and stopped halfway. A
# copy made here is exact, and what should differ is said as a change rather
# than worked out again.

# The arguments of a joining call that are points in the world, and move with
# the copy. Lengths, limits and strengths do not.
_POINT_ARGS = ("at_m", "at_a_m", "at_b_m", "over_a_m", "over_b_m")


def tool_duplicate(args: dict[str, Any]) -> dict[str, Any]:
    """Make another of something already built, somewhere else: its bodies, the
    joints between them, their edges, and how a person uses them."""
    world_id = str(args.get("world_id"))
    entry = _world(world_id)
    names = args.get("names")
    if not isinstance(names, list) or not names or not all(isinstance(n, str) for n in names):
        raise Refused("names is the list of the bodies to copy -- a bow's are listed under "
                      "things_a_person_uses in describe_world")
    names = list(dict.fromkeys(names))
    bodies = {b["name"]: b for b in entry["scene"]["bodies"]}
    missing = [n for n in names if n not in bodies]
    if missing:
        raise Refused(f"{missing} {'is' if len(missing) == 1 else 'are'} not in this world")
    prefix = str(args.get("prefix") or "").strip()[:30]
    if not prefix:
        raise Refused("give the copies a prefix for their names, like 'stiff': names are how "
                      "every joint and every later call finds a thing")
    renamed = {n: f"{prefix} {n}"[:60] for n in names}
    taken = [new for new in renamed.values() if new in bodies]
    if taken:
        raise Refused(f"there is already something called {taken[0]!r} here: choose another "
                      f"prefix")
    changes = args.get("changes") or {}
    if not isinstance(changes, dict) or not all(isinstance(v, dict) for v in changes.values()):
        raise Refused("changes is what should differ, by kind of joint, like "
                      "{\"spring\": {\"stiffness_n_m\": 8000}}")
    unknown = sorted(k for k in changes if k not in MAKE_JOINT)
    if unknown:
        raise Refused(f"changes are by kind of joint -- {sorted(MAKE_JOINT)} -- and "
                      f"{unknown} is not one")
    # Whole cells, or the grid cuts the copy differently from the original and
    # it is not the same shape.
    cell = float(entry["cell_m"])
    asked = _triple(args.get("offset_m"), "offset_m", -50.0, 50.0)
    offset = [round(v / cell) * cell for v in asked]

    def moved(point: Any) -> list[float]:
        return [float(v) + o for v, o in zip(point, offset)]

    copies = []
    for name in names:
        body = dict(bodies[name], name=renamed[name], center_m=moved(bodies[name]["center_m"]),
                    velocity_m_s=[0.0, 0.0, 0.0])
        # Bodies sharing a join name are built as one piece: the copies are
        # one piece with each other, not with the originals.
        if body.get("join"):
            body["join"] = f"{prefix} {body['join']}"
        copies.append(body)
    was_scene = entry["scene"]
    scene = dict(was_scene, bodies=list(was_scene["bodies"]) + copies)
    edges = [dict(b, body=renamed[b["body"]]) for b in was_scene.get("blades") or []
             if b.get("body") in renamed]
    if edges:
        scene["blades"] = list(was_scene.get("blades") or []) + edges
    # And the points of tools that dig: kept in their bodies' own frames, so a
    # copy's point is where the original's is on it. Where it is as built moves
    # with the copy.
    points = [dict(p, body=renamed[p["body"]],
                   tip_m=moved(p["tip_m"]), grip_m=moved(p["grip_m"]))
              for p in was_scene.get("tool_points") or [] if p.get("body") in renamed]
    if points:
        scene["tool_points"] = list(was_scene.get("tool_points") or []) + points
    lost = _rebuild(entry, scene, world_id)

    made: list[dict[str, Any]] = []
    tried: list[dict[str, Any]] = []
    try:
        for record in list(entry.get("joints", [])):
            a, b = record["args"].get("a"), record["args"].get("b")
            if a not in renamed or b not in renamed:
                continue
            call = dict(record["args"], a=renamed[a], b=renamed[b], world_id=world_id)
            if call.get("member") in renamed:
                call["member"] = renamed[call["member"]]
            for key in _POINT_ARGS:
                if isinstance(call.get(key), (list, tuple)) and len(call[key]) == 3:
                    call[key] = moved(call[key])
            call.update(changes.get(record["tool"], {}))
            answer = HANDLERS[record["tool"]](call)
            made.append({"joint": answer["joint"], "tool": record["tool"],
                         "a": call["a"], "b": call["b"]})
        for profile in list(entry.get("interactions", [])):
            if not set(profile["parts"]) <= set(renamed):
                continue
            call = {"world_id": world_id,
                    "object": str(args.get("call_it") or f"{profile['object']} ({prefix})")[:80],
                    "template": profile["template"],
                    "parts": [renamed[p] for p in profile["parts"]],
                    "trial": args.get("trial", True)}
            if profile["template"] == "swing-and-lever":
                # A tool: its point came across with its body (tool_points below
                # are copied with the bodies), and how it is used is the same.
                call["tool"] = renamed[profile["tool"]]
                if profile.get("use"):
                    call["use"] = json.loads(json.dumps(profile["use"]))
            else:
                call.update(draw=dict(profile["draw"], part=renamed[profile["draw"]["part"]]),
                            nock={"a": renamed[profile["nock"]["a"]], "b": renamed[profile["nock"]["b"]]},
                            limbs=[[renamed[x], renamed[y]] for x, y in profile["limbs"]],
                            projectile=renamed[profile["projectile"]])
            tried.append(tool_interaction(call))
    except Refused:
        # Nothing half made: the copies go, and every joint made on them.
        copied = set(renamed.values())
        entry["joints"] = [r for r in entry.get("joints", [])
                           if r["args"].get("a") not in copied and r["args"].get("b") not in copied]
        entry["interactions"] = [p for p in entry.get("interactions", [])
                                 if not set(p["parts"]) & copied]
        _rebuild(entry, was_scene, world_id)
        raise
    answer = {"copied": [renamed[n] for n in names], "offset_m": [round(v, 4) for v in offset],
              "joints": made, "objects": _describe(entry["world"])}
    if any(abs(a - o) > 1e-9 for a, o in zip(asked, offset)):
        answer["offset_note"] = (f"moved by whole {cell:g} m cells, so the copy is cut from the "
                                 f"grid as the original is")
    if changes:
        answer["changed"] = changes
    if tried:
        answer["things_a_person_uses"] = tried
    if lost:
        answer["joints_lost"] = lost
    return answer


# ---------------------------------------------------------------------------
# Recipes: mechanisms built exactly, at a place
# ---------------------------------------------------------------------------
#
# The playground's chat, 2026-09-14, given a gate as a recipe of seven calls with
# every point an offset from the place: it gave the parts [x, z], so each was set
# down on the ground and the gate dragged on it; it put the pin 0.22 m inside the
# gate's edge instead of 0.52; and its latch bar lay 0.36 m off, on the ground.
# So a mechanism the engine has been tried on is built here, number for number,
# at a place the caller names: the ground's height there is surveyed, everything
# is laid on the room's cells, and its actions are offered under its parts' real
# names. Each was built in the playground's world and worked by the engine's hand
# (tests/world_room_tests.py TheWorldsThingsOnJoints). A tuple is an offset from
# the place [px, pz] and the ground y0; a list is as it stands.
RECIPES: dict[str, dict[str, Any]] = {
    "gate": {
        "title": "a gate between two posts, held shut by a latch bar",
        "tried": "held shut by its latch; the latch let go of, it opened 89 degrees and shut",
        "parts": [
            {"name": "gate post", "shape": "box", "material": "concrete",
             "size_m": [0.08, 1.6, 0.08], "position_m": (-0.64, 0.8, 0.0), "anchored": True},
            {"name": "gate far post", "shape": "box", "material": "concrete",
             "size_m": [0.08, 1.6, 0.08], "position_m": (0.64, 0.8, 0.0), "anchored": True},
            {"name": "oak gate", "shape": "box", "material": "oak",
             "size_m": [1.12, 1.2, 0.04], "position_m": (0.0, 0.72, 0.02)},
            {"name": "gate latch bar", "shape": "box", "material": "iron",
             "size_m": [0.24, 0.04, 0.04], "position_m": (0.6, 1.02, 0.1)}],
        "joints": [
            ("hinge", {"a": "gate post", "b": "oak gate", "at_m": (-0.52, 0.72, 0.02),
                       "axis": [0, 1, 0], "lower_deg": 0, "upper_deg": 90, "friction_n_m": 5}),
            ("fix", {"a": "oak gate", "b": "gate latch bar", "at_m": (0.52, 1.02, 0.06),
                     "axis": [0, 0, 1]}),
            ("fix", {"a": "gate far post", "b": "gate latch bar", "at_m": (0.64, 1.02, 0.06),
                     "axis": [0, 0, 1]})],
        "actions": {"oak gate": [
            {"label": "Open the gate", "steps": [{"do": "turn", "stop": "all_the_way"}]},
            {"label": "Close the gate", "steps": [{"do": "turn", "stop": "all_the_way_back"}]}]},
        "use": "the page gives the gate \"Release the latch\" too, and it opens only once the "
               "latch is let go of (that, or R)",
    },
    "portcullis": {
        "title": "a portcullis in a gateway, raised by a winch beside it",
        "tried": "half a turn of the handle raised it 0.64 m, and turned back it came down",
        "parts": [
            {"name": "gateway left post", "shape": "box", "material": "concrete",
             "size_m": [0.08, 2.0, 0.08], "position_m": (-0.68, 1.0, -0.08), "anchored": True},
            {"name": "gateway right post", "shape": "box", "material": "concrete",
             "size_m": [0.08, 2.0, 0.08], "position_m": (0.68, 1.0, -0.08), "anchored": True},
            {"name": "gateway lintel", "shape": "box", "material": "oak",
             "size_m": [1.44, 0.08, 0.08], "position_m": (0.0, 2.04, -0.08), "anchored": True},
            {"name": "portcullis", "shape": "box", "material": "oak",
             "size_m": [1.28, 1.04, 0.04], "position_m": (0.0, 0.56, 0.02)},
            {"name": "winch post", "shape": "box", "material": "concrete",
             "size_m": [0.08, 1.2, 0.08], "position_m": (1.6, 0.6, -0.08), "anchored": True},
            {"name": "winch wheel", "shape": "box", "material": "oak",
             "size_m": [0.64, 0.64, 0.08], "position_m": (1.6, 1.0, 0.04)},
            {"name": "winch handle", "shape": "box", "material": "oak",
             "size_m": [0.08, 0.08, 0.16], "position_m": (1.6, 1.24, 0.16)}],
        "joints": [
            ("slide", {"a": "gateway left post", "b": "portcullis", "at_m": (0.0, 0.56, 0.02),
                       "axis": [0, 1, 0], "lower_m": 0.0, "upper_m": 1.0, "friction_n": 100}),
            ("hinge", {"a": "winch post", "b": "winch wheel", "at_m": (1.6, 1.0, 0.04),
                       "axis": [0, 0, 1], "lower_deg": -180, "upper_deg": 180, "friction_n_m": 2}),
            ("fix", {"a": "winch wheel", "b": "winch handle", "at_m": (1.6, 1.24, 0.08),
                     "axis": [0, 0, 1]}),
            ("reeve", {"a": "winch wheel", "b": "portcullis", "at_a_m": (1.6, 1.32, 0.04),
                       "at_b_m": (0.0, 1.08, 0.02), "over_a_m": (1.6, 1.96, 0.04),
                       "over_b_m": (0.0, 1.96, 0.02), "ratio": 1})],
        "actions": {"winch handle": [
            {"label": "Raise the portcullis", "steps": [{"do": "turn", "stop": "all_the_way"}]},
            {"label": "Lower the portcullis", "steps": [{"do": "turn", "stop": "back_to_start"}]}]},
        "use": "the hand keeps hold of the handle after a turn, so the portcullis stays up until "
               "they let go; the winch has no ratchet, so let go of it comes down",
    },
    "door": {
        "title": "a door in a frame that shuts itself on a spring",
        "tried": "opened 89 degrees by the hand, and let go of it was shut within a second",
        "parts": [
            {"name": "door hinge post", "shape": "box", "material": "oak",
             "size_m": [0.08, 2.2, 0.08], "position_m": (-0.48, 1.1, 0.0), "anchored": True},
            {"name": "door latch post", "shape": "box", "material": "oak",
             "size_m": [0.08, 2.2, 0.08], "position_m": (0.48, 1.1, 0.0), "anchored": True},
            {"name": "door lintel", "shape": "box", "material": "oak",
             "size_m": [1.04, 0.08, 0.08], "position_m": (0.0, 2.24, 0.0), "anchored": True},
            {"name": "oak door", "shape": "box", "material": "oak",
             "size_m": [0.8, 2.0, 0.04], "position_m": (0.0, 1.08, 0.02)}],
        "joints": [
            ("hinge", {"a": "door hinge post", "b": "oak door", "at_m": (-0.36, 1.08, 0.02),
                       "axis": [0, 1, 0], "lower_deg": 0, "upper_deg": 90, "friction_n_m": 2}),
            ("spring", {"a": "door hinge post", "b": "oak door", "at_a_m": (-0.06, 1.9, 0.42),
                        "at_b_m": (0.04, 1.9, 0.02), "rest_m": 0.4123, "stiffness_n_m": 300,
                        "damping_n_s_m": 40})],
        "actions": {"oak door": [
            {"label": "Open the door", "steps": [{"do": "turn", "stop": "all_the_way"}]}]},
        "use": "let go of, its spring shuts it",
    },
    "bell": {
        "title": "a bell on a rope from a frame",
        "tried": "it hangs still at its rope's length",
        "parts": [
            {"name": "bell post", "shape": "box", "material": "oak",
             "size_m": [0.08, 2.4, 0.08], "position_m": (-0.48, 1.2, 0.0), "anchored": True},
            {"name": "bell far post", "shape": "box", "material": "oak",
             "size_m": [0.08, 2.4, 0.08], "position_m": (0.48, 1.2, 0.0), "anchored": True},
            {"name": "bell beam", "shape": "box", "material": "oak",
             "size_m": [1.04, 0.08, 0.08], "position_m": (0.0, 2.44, 0.0), "anchored": True},
            {"name": "iron bell", "shape": "sphere", "material": "iron",
             "size_m": [0.16, 0.16, 0.16], "position_m": (0.0, 1.6, 0.0)}],
        "joints": [
            ("tie", {"a": "bell beam", "b": "iron bell", "at_a_m": (0.0, 2.4, 0.0),
                     "at_b_m": (0.0, 1.68, 0.0), "length_m": 0.72})],
        "actions": {"iron bell": [
            {"label": "Ring the bell", "steps": [
                {"do": "push", "part": "iron bell",
                 "toward": {"kind": "from", "from": "iron bell", "offset_m": [0.0, 0.0, -0.5]},
                 "distance_m": 0.3}]}]},
        "use": "taken hold of, it swings on its rope",
    },
    # The courtyard's own bow, number for number (the room's guide carries it
    # too): tried there, drawn 0.44 m by 214 N it held 42 J.
    "bow": {
        "title": "a bow on its stand with an arrow on the string, ready to draw",
        "tried": "drawn 0.44 m by 214 N it held 42 J, and the arrow left at 8.3 m/s",
        "parts": [
            {"name": "bow grip upper", "shape": "box", "material": "oak",
             "size_m": [0.04, 0.16, 0.12], "position_m": (0.0, 1.40, 0.0), "anchored": True},
            {"name": "bow grip lower", "shape": "box", "material": "oak",
             "size_m": [0.04, 0.16, 0.12], "position_m": (0.0, 1.12, 0.0), "anchored": True},
            {"name": "bow grip near cheek", "shape": "box", "material": "oak",
             "size_m": [0.04, 0.04, 0.04], "position_m": (0.0, 1.22, 0.06), "anchored": True},
            {"name": "bow grip far cheek", "shape": "box", "material": "oak",
             "size_m": [0.04, 0.04, 0.04], "position_m": (0.0, 1.22, -0.06), "anchored": True},
            {"name": "upper limb tip", "shape": "box", "material": "oak",
             "size_m": [0.04, 0.04, 0.04], "position_m": (-0.16, 1.62, 0.0)},
            {"name": "lower limb tip", "shape": "box", "material": "oak",
             "size_m": [0.04, 0.04, 0.04], "position_m": (-0.16, 0.82, 0.0)},
            {"name": "bowstring", "shape": "box", "material": "oak",
             "size_m": [0.04, 0.16, 0.04], "position_m": (-0.16, 1.22, 0.0)},
            {"name": "arrow", "shape": "box", "material": "oak",
             "size_m": [0.6, 0.04, 0.04], "position_m": (0.2, 1.22, 0.0)}],
        "joints": [
            ("hinge", {"a": "bow grip upper", "b": "upper limb tip", "at_m": (0.0, 1.34, 0.0),
                       "axis": [0, 0, 1], "lower_deg": -60, "upper_deg": 60, "friction_n_m": 0}),
            ("hinge", {"a": "bow grip lower", "b": "lower limb tip", "at_m": (0.0, 1.10, 0.0),
                       "axis": [0, 0, 1], "lower_deg": -60, "upper_deg": 60, "friction_n_m": 0}),
            ("spring", {"a": "bow grip upper", "b": "upper limb tip", "at_a_m": (0.36, 1.34, 0.0),
                        "at_b_m": (-0.16, 1.62, 0.0), "rest_m": 0, "stiffness_n_m": 6000,
                        "damping_n_s_m": 20}),
            ("spring", {"a": "bow grip lower", "b": "lower limb tip", "at_a_m": (0.36, 1.10, 0.0),
                        "at_b_m": (-0.16, 0.82, 0.0), "rest_m": 0, "stiffness_n_m": 6000,
                        "damping_n_s_m": 20}),
            ("tie", {"a": "upper limb tip", "b": "bowstring", "at_a_m": (-0.16, 1.62, 0.0),
                     "at_b_m": (-0.16, 1.30, 0.0), "length_m": 0}),
            ("tie", {"a": "lower limb tip", "b": "bowstring", "at_a_m": (-0.16, 0.82, 0.0),
                     "at_b_m": (-0.16, 1.14, 0.0), "length_m": 0}),
            ("fix", {"a": "bowstring", "b": "arrow", "at_m": (-0.13, 1.22, 0.0), "axis": [1, 0, 0],
                     "comes_off_n": 20})],
        "then": [
            ("interaction", {"object": "the bow", "template": "draw-and-release",
                             "parts": ["bow grip upper", "bow grip lower", "bow grip near cheek",
                                       "bow grip far cheek", "upper limb tip", "lower limb tip",
                                       "bowstring", "arrow"],
                             "draw": {"part": "bowstring", "axis": [-1, 0, 0], "max_m": 0.45},
                             "nock": {"a": "bowstring", "b": "arrow"},
                             "limbs": [["bow grip upper", "upper limb tip"],
                                       ["bow grip lower", "lower limb tip"]],
                             "projectile": "arrow"})],
        "actions": {},
        "use": "it shoots along +x. E on any part takes it up; they hold the left mouse to draw "
               "and let go to shoot, and the right mouse lets the string down",
    },
    # The tools that work the ground (pick, mattock, hoe) are added below, from
    # TOOL_KINDS by _tool_recipe. Light enough to take hold of, and a few hundred cells rather than the
    # 4,172 two solid blocks cost: a top and a seat on legs fixed to them, every
    # face on the room's 0.04 m cells.
    "table": {
        "title": "a small oak table with a chair drawn up to it",
        "tried": "it stood on its legs, and the hand pulled the chair out and pushed it back in",
        "parts": [
            {"name": "oak table top", "shape": "box", "material": "oak",
             "size_m": [0.8, 0.04, 0.56], "position_m": (0.0, 0.74, 0.0)},
            {"name": "table leg 1", "shape": "box", "material": "oak",
             "size_m": [0.04, 0.72, 0.04], "position_m": (-0.38, 0.36, -0.26)},
            {"name": "table leg 2", "shape": "box", "material": "oak",
             "size_m": [0.04, 0.72, 0.04], "position_m": (0.38, 0.36, -0.26)},
            {"name": "table leg 3", "shape": "box", "material": "oak",
             "size_m": [0.04, 0.72, 0.04], "position_m": (-0.38, 0.36, 0.26)},
            {"name": "table leg 4", "shape": "box", "material": "oak",
             "size_m": [0.04, 0.72, 0.04], "position_m": (0.38, 0.36, 0.26)},
            {"name": "oak chair seat", "shape": "box", "material": "oak",
             "size_m": [0.4, 0.04, 0.4], "position_m": (0.0, 0.46, 0.56)},
            {"name": "chair leg 1", "shape": "box", "material": "oak",
             "size_m": [0.04, 0.44, 0.04], "position_m": (-0.18, 0.22, 0.38)},
            {"name": "chair leg 2", "shape": "box", "material": "oak",
             "size_m": [0.04, 0.44, 0.04], "position_m": (0.18, 0.22, 0.38)},
            {"name": "chair leg 3", "shape": "box", "material": "oak",
             "size_m": [0.04, 0.44, 0.04], "position_m": (-0.18, 0.22, 0.74)},
            {"name": "chair leg 4", "shape": "box", "material": "oak",
             "size_m": [0.04, 0.44, 0.04], "position_m": (0.18, 0.22, 0.74)},
            {"name": "chair back", "shape": "box", "material": "oak",
             "size_m": [0.4, 0.44, 0.04], "position_m": (0.0, 0.70, 0.74)}],
        "joints": [
            ("fix", {"a": "oak table top", "b": "table leg 1", "at_m": (-0.38, 0.72, -0.26), "axis": [0, 1, 0]}),
            ("fix", {"a": "oak table top", "b": "table leg 2", "at_m": (0.38, 0.72, -0.26), "axis": [0, 1, 0]}),
            ("fix", {"a": "oak table top", "b": "table leg 3", "at_m": (-0.38, 0.72, 0.26), "axis": [0, 1, 0]}),
            ("fix", {"a": "oak table top", "b": "table leg 4", "at_m": (0.38, 0.72, 0.26), "axis": [0, 1, 0]}),
            ("fix", {"a": "oak chair seat", "b": "chair leg 1", "at_m": (-0.18, 0.44, 0.38), "axis": [0, 1, 0]}),
            ("fix", {"a": "oak chair seat", "b": "chair leg 2", "at_m": (0.18, 0.44, 0.38), "axis": [0, 1, 0]}),
            ("fix", {"a": "oak chair seat", "b": "chair leg 3", "at_m": (-0.18, 0.44, 0.74), "axis": [0, 1, 0]}),
            ("fix", {"a": "oak chair seat", "b": "chair leg 4", "at_m": (0.18, 0.44, 0.74), "axis": [0, 1, 0]}),
            ("fix", {"a": "oak chair seat", "b": "chair back", "at_m": (0.0, 0.48, 0.74), "axis": [0, 1, 0]})],
        "actions": {"oak chair seat": [
            {"label": "Pull the chair out", "steps": [
                {"do": "take_hold"},
                {"do": "carry_to", "to": {"kind": "beside", "beside": "oak table top", "side": "near",
                                          "gap_m": 0.4}},
                {"do": "put_down"}]},
            {"label": "Push the chair in", "steps": [
                {"do": "take_hold"},
                {"do": "carry_to", "to": {"kind": "beside", "beside": "oak table top", "side": "near",
                                          "gap_m": 0.05}},
                {"do": "put_down"}]}]},
        "use": "the chair is drawn up on the table's +z side, the side to stand on",
    },
}


# ---------------------------------------------------------------------------
# Tools that work the ground, by recipe
# ---------------------------------------------------------------------------
#
# gpt-5-mini cannot lay a tool out by hand. Asked in the page for "a mattock for
# breaking up hard soil", it put the head off the room's 0.04 m cells and the tip
# 14 cm past it, had tool_point refused three times, and offered a "Dig here"
# action that only carried it (317,000 tokens); told to use the pick's recipe
# and shape it, it laid one by hand again (691,000). So a tool is a recipe with
# a name, laid out here exactly -- every face on the cells, the tip on the head's
# end face, the grip a cell in from the haft's far end -- and what makes it the
# tool the person asked for is options (build_recipe `tool`): its name, its head,
# its haft, its point and how it is used. The point's shape is what the ground
# answers (ground-work-v1: its width and angle set how hard the ground resists
# it and what a pry breaks out); `use` is the handling (interaction_profiles).

# A tool is ONE piece, joined, and a joined piece is one material: an "iron"
# head on an oak haft was built all of oak (1.344 kg, oak's weight for its
# size), so a tool has one material, and says so.
TOOL_KINDS: dict[str, dict[str, Any]] = {
    # The guide's pick, number for number: one piece of oak, the haft first.
    "pick": {"title": "an oak pick lying on the ground, to dig with",
             "tried": "swung, it went 120 mm into the soil at 9.2 m/s; levered, it broke out "
                      "5.6 L of soil; the rock stopped it",
             "head_name": "arm", "material": "oak",
             "haft": {"length_m": 0.8},
             "head": {"length_m": 0.28, "width_m": 0.04},
             "point": {"width_m": 0.04, "thickness_m": 0.04, "angle_deg": 30.0, "length_m": 0.2},
             "use": {}},
    "mattock": {"title": "an oak mattock -- a broad flat blade on its haft, one piece -- lying on "
                         "the ground, to break up hard soil",
                "tried": "swung, it went 130 mm into the soil at 8.2 m/s; pried, it broke out "
                         "9.6 L of soil",
                "head_name": "head", "material": "oak",
                "haft": {"length_m": 0.8},
                "head": {"length_m": 0.2, "width_m": 0.08},
                "point": {"width_m": 0.08, "thickness_m": 0.02, "angle_deg": 25.0, "length_m": 0.16},
                "use": {"label": "Break up the soil", "past": "broke up"}},
    "hoe": {"title": "an oak hoe -- a thin broad blade on its haft, one piece -- lying on the "
                     "ground, to chop the soil loose (its draw through the soil is not modelled: "
                     "it chops in and is pried)",
            "tried": "swung, its broad thin blade went 74 mm into the soil at 9.5 m/s; pried, it "
                     "broke out 1.5 L -- the ground resists a broad blade more than a point",
            "head_name": "blade", "material": "oak",
            # The pick's 0.8 m: with 0.96 its trial, standing 1.2 m back as the
            # engine's swing is measured, met no ground.
            "haft": {"length_m": 0.8},
            "head": {"length_m": 0.12, "width_m": 0.12},
            "point": {"width_m": 0.12, "thickness_m": 0.01, "angle_deg": 20.0, "length_m": 0.1},
            "use": {"label": "Hoe the soil", "past": "hoed", "lever": {"lever_deg": 25.0}}},
}
_TOOL_BOUNDS = {"haft": {"length_m": (0.48, 1.44)},
                "head": {"length_m": (0.08, 0.48), "width_m": (0.04, 0.2)},
                "point": {"width_m": (0.01, 0.2), "thickness_m": (0.005, 0.04),
                          "angle_deg": (10.0, 120.0), "length_m": (0.05, 0.4)}}


def _unblanked(value: Any) -> Any:
    """What a caller said, less the blanks: the chat fills every field it is
    shown, and an empty one says nothing. true and false say something."""
    if isinstance(value, dict):
        out = {k: _unblanked(v) for k, v in value.items() if isinstance(v, bool) or not _blank(v)}
        return {k: v for k, v in out.items() if isinstance(v, bool) or v not in ({}, [], None, "")}
    return value


def _tool_recipe(kind: str, options: dict[str, Any] | None = None,
                 cell: float = 0.04) -> dict[str, Any]:
    """A tool of this kind as a recipe (RECIPES' form), with what `options`
    change of it: call_it, material (the whole piece's), head {length_m,
    width_m}, haft {length_m}, point {width_m, thickness_m, angle_deg,
    length_m}, use (as interaction's). Refused, saying which, for what is out
    of bounds."""
    base = TOOL_KINDS[kind]
    options = options or {}
    unknown = set(options) - {"call_it", "material", "head", "haft", "point", "use"}
    if unknown:
        raise Refused(f"tool has no {sorted(unknown)}; it may say call_it, material, head, haft, "
                      f"point and use")
    material = options.get("material", base["material"])
    if material not in MATERIALS:
        raise Refused(f"tool material is one of {MATERIALS}, not {material!r}")
    sizes: dict[str, dict[str, Any]] = {}
    for part in ("haft", "head", "point"):
        said = options.get(part) or {}
        if not isinstance(said, dict):
            raise Refused(f"tool {part} is an object")
        if "material" in said:
            raise Refused(f"a tool is one piece, and a piece is all one material: say tool "
                          f"material, not its {part}'s")
        if set(said) - set(_TOOL_BOUNDS[part]):
            raise Refused(f"tool {part} has no {sorted(set(said) - set(_TOOL_BOUNDS[part]))}; it may "
                          f"say {sorted(_TOOL_BOUNDS[part])}")
        out = dict(base[part])
        for field, (low, high) in _TOOL_BOUNDS[part].items():
            if field in said:
                value = said[field]
                if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
                    raise Refused(f"tool {part} {field} is {low:g} to {high:g}, not {value!r}")
                out[field] = float(value)
        sizes[part] = out
    name = str(options.get("call_it") or f"the {kind}").strip()[:40]
    stem = name[4:] if name.lower().startswith("the ") else name
    stem = (stem[2:] if stem.lower().startswith("a ") else stem).strip() or kind
    head_name = base["head_name"]

    def cells(value: float, step: float) -> float:
        return round(max(step, round(value / step) * step), 4)

    # Both ends of the haft on the cells, so it is laid out from its middle. The
    # head goes along -z from the haft's last cell, touching it, one cell thick
    # along the haft (a thinner part is lost from the grid) and as broad as it is
    # ACROSS the swing: up, as it lies. The engine takes a point's width as square
    # to the point and to the handle. A head laid broad along the haft was a
    # different tool from the point it was declared as: coming in tilted, its end
    # led with a corner, 2-3 cm below its tip, and that corner met the ground
    # first, so the swing stopped short (a hoe from 6 stand-backs of 8). A pick's
    # head is a cell square, the same either way.
    length = cells(sizes["haft"]["length_m"], 2 * cell)
    head_length = cells(sizes["head"]["length_m"], cell)
    head_width = cells(sizes["head"]["width_m"], cell)
    half, t = length / 2.0, cell
    hx = round(half - t / 2.0, 4)
    hy = round(head_width / 2.0, 4)
    haft, head = f"{stem} haft", f"{stem} {head_name}"
    point = sizes["point"]
    # The point is the whole of the head's working edge unless its width is
    # said. The ends of an edge broader than its point are not point: they meet
    # the ground as a surface, and a 0.12 m head the chat made on an 0.08 m
    # point stopped 29 mm above the ground.
    if "width_m" not in (options.get("point") or {}):
        point["width_m"] = head_width
    # Whether it is pried is the kind's: the chat fills every field, and a
    # mattock it made said pry false.
    use = dict(base["use"], **{k: v for k, v in (options.get("use") or {}).items() if k != "pry"})
    then: list[tuple[str, dict[str, Any]]] = [
        ("tool_point", {"body": haft, "tip_m": (hx, hy, -head_length), "pointing": [0, 0, -1],
                        "grip_m": (round(-half + cell, 4), t / 2, t / 2),
                        # No point broader than its head, or longer.
                        "width_m": min(point["width_m"], head_width),
                        "thickness_m": point["thickness_m"], "angle_deg": point["angle_deg"],
                        "length_m": min(point["length_m"], head_length)}),
        ("interaction", {"object": name, "template": "swing-and-lever", "parts": [haft, head],
                         "tool": haft, **({"use": use} if use else {})})]
    label = use.get("label") or interaction_profiles.TOOL_USE_DEFAULTS["label"]
    return {"title": base["title"] if not options else
                     f"{name}: one piece of {material}, a {head_width:g} m by {head_length:g} m "
                     f"{head_name} on a {length:g} m haft, lying on the ground",
            "tried": base["tried"] if not options else None,
            "parts": [{"name": haft, "shape": "box", "material": material,
                       "size_m": [length, t, t], "position_m": (0.0, t / 2, t / 2), "join": stem},
                      {"name": head, "shape": "box", "material": material,
                       "size_m": [t, head_width, head_length],
                       "position_m": (hx, hy, round(-head_length / 2, 4)), "join": stem}],
            "joints": [], "then": then, "actions": {},
            "use": f"they press E near it and it is held ready by its grip, point down; a ring on "
                   f"the ground shows where it will come down; a click does '{label}' -- swung, "
                   f"pried and drawn out -- and holding the button goes on"}


RECIPES.update({kind: _tool_recipe(kind) for kind in TOOL_KINDS})

# How the person uses a tool, as a tool call says it (interaction's `use`, and
# build_recipe's `tool` `use`): interaction_profiles checks it.
TOOL_USE_SCHEMA = {
    "type": "object",
    "description": "swing-and-lever only, and optional: how the PERSON uses the tool -- the "
                   "playground gives every tool the same ring, one click that does the whole of "
                   "it (swing, pry, draw out) and holding to keep going. label: what the click is "
                   "called ('Break up the soil'); past: how a result is said ('broke up'); swing "
                   "and lever: how the hand moves it, within its bounds; pry false for a tool "
                   "only swung and drawn out; reach_m: [nearest, furthest] in front of the person "
                   "it comes down; repeat: whether holding goes on. Say only what differs from "
                   "the defaults: Dig here, dug, a 4 m/s swing raised 110 degrees, a 40 degree "
                   "pry at 1.2 m/s, 1.15 to 2 m, repeating. How deep it goes and what comes loose "
                   "stay the ground's.",
    "properties": {
        "label": {"type": "string", "description": "What the click is called, at most 40 letters."},
        "past": {"type": "string", "description": "How a result is said, in the past, at most 24 letters."},
        "swing": {"type": "object",
                  "description": "speed_m_s 1 to 5: how fast the HAND moves along the swing -- "
                                 "the point arrives two to three times faster, so a trial's "
                                 "9 m/s point is a 4 m/s swing; raise_deg 30 to 170.",
                  "properties": {"speed_m_s": {"type": "number"}, "raise_deg": {"type": "number"}}},
        "lever": {"type": "object", "description": "speed_m_s 0.3 to 4, lever_deg 5 to 80.",
                  "properties": {"speed_m_s": {"type": "number"}, "lever_deg": {"type": "number"}}},
        "pry": {"type": "boolean", "description": "false: swung and drawn out, never pried."},
        "reach_m": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2,
                    "description": "[nearest, furthest], within 0.3 to 2 m."},
        "repeat": {"type": "boolean", "description": "false: holding the button does not go on."}}}


def tool_build_recipe(args: dict[str, Any]) -> dict[str, Any]:
    """A mechanism the engine has been tried on, built exactly at a place: its
    parts, its joints and its actions, or nothing at all."""
    world_id = str(args.get("world_id"))
    entry = _world(world_id)
    which = str(args.get("recipe") or "").strip().lower()
    if which not in RECIPES:
        raise Refused(f"recipe is one of {', '.join(RECIPES)}, not {which!r}")
    recipe = RECIPES[which]
    cell = float(entry["cell_m"])
    # What makes a tool the one the person asked for (_tool_recipe), less the
    # blanks the chat fills in.
    options = _unblanked(args.get("tool")) if isinstance(args.get("tool"), dict) else None
    if options:
        if which not in TOOL_KINDS:
            raise Refused(f"tool shapes a tool that works the ground -- {', '.join(TOOL_KINDS)} -- "
                          f"not the {which}")
        recipe = _tool_recipe(which, options, cell)
    px, pz = (round(v / cell) * cell for v in _xz(args.get("at_m"), "at_m"))
    # The ground there, up to the next whole cell, so nothing starts inside it:
    # 0 on a floor.
    y0 = 0.0
    if _has_terrain(entry):
        here = entry["world"].survey(px, pz)
        if not here.get("on_the_ground"):
            raise Refused(f"[{px:g}, {pz:g}] is off the edge of the ground")
        if here.get("water"):
            raise Refused(f"[{px:g}, {pz:g}] is in the water: build it on dry ground")
        y0 = math.ceil(float(here["ground_m"]) / cell - 1e-9) * cell
    # Its parts' names, all numbered when another thing has one of them already
    # -- and with them its pieces' join names and what a person calls it, so a
    # second pick is a piece of its own.
    then = recipe.get("then", [])
    taken = {b["name"] for b in entry["scene"]["bodies"]}
    own = [p["name"] for p in recipe["parts"]]
    also = sorted({p["join"] for p in recipe["parts"] if p.get("join")}
                  | {call["object"] for _, call in then if "object" in call})
    number = 1
    while any((n if number == 1 else f"{n} {number}") in taken for n in own):
        number += 1
    renamed = {n: (n if number == 1 else f"{n} {number}") for n in own + also}

    def made(value: Any) -> Any:
        if isinstance(value, tuple):
            return [round(px + value[0], 4), round(y0 + value[1], 4), round(pz + value[2], 4)]
        if isinstance(value, str):
            return renamed.get(value, value)
        if isinstance(value, list):
            return [made(v) for v in value]
        if isinstance(value, dict):
            return {k: made(v) for k, v in value.items()}
        return value

    was_scene = entry["scene"]
    joints: list[dict[str, Any]] = []
    offered: dict[str, list[str]] = {}
    said: dict[str, Any] = {}
    try:
        for part in recipe["parts"]:
            tool_add_object({"world_id": world_id, "object": made(part)})
        for tool, call in recipe["joints"]:
            answer = HANDLERS[tool]({"world_id": world_id, **made(call)})
            joints.append({"joint": answer.get("joint"), "tool": tool,
                           "a": renamed[call["a"]], "b": renamed[call["b"]]})
        # Its point, and how a person uses it -- which tries it, and says what
        # the try measured.
        for tool, call in then:
            answer = HANDLERS[tool]({"world_id": world_id, **made(call)})
            said[tool] = {k: v for k, v in answer.items() if k != "objects"}
            # A tool the wrist cannot hold level droops and misses every swing:
            # not built at all, and the answer says what to change.
            if tool == "tool_point" and answer.get("too_heavy_to_swing"):
                raise Refused(f"{answer.get('body')}, {answer.get('mass_kg')} kg: "
                              f"{answer['too_heavy_to_swing']}")
        for thing, actions in recipe["actions"].items():
            answer = tool_offer_actions({"world_id": world_id, "name": renamed[thing],
                                         "actions": made(actions)})
            offered[renamed[thing]] = [a["label"] for a in answer["actions"]]
    except Refused:
        # Nothing half made: its parts go, and every joint, point, use and action
        # made on them.
        mine = set(renamed.values())
        entry["joints"] = [r for r in entry.get("joints", [])
                           if r["args"].get("a") not in mine and r["args"].get("b") not in mine]
        entry["interactions"] = [p for p in entry.get("interactions", [])
                                 if not set(p.get("parts") or []) & mine]
        entry["actions"] = {k: v for k, v in (entry.get("actions") or {}).items() if k not in mine}
        _rebuild(entry, was_scene, world_id)
        raise
    answer = {"built": recipe["title"], "at_m": [round(px, 4), round(pz, 4)],
              "ground_y_m": round(y0, 4), "parts": [renamed[n] for n in own], "joints": joints,
              "actions_offered": offered, "use": made(recipe["use"]),
              "say": "Say what was built and where, what they can do with it, and that they can "
                     "click on it to see its actions.",
              "objects": _describe(entry["world"])}
    if recipe["tried"]:
        answer["tried"] = recipe["tried"]
    if said:
        answer["and"] = said
    return answer


# ---------------------------------------------------------------------------
# Heat and strength (docs/thermal-mechanics.md)
# ---------------------------------------------------------------------------
#
# A fixing, a tie or a spring can say what it is MADE of -- one of its own two
# ends -- and then heat changes what it can take, by that body's material law.
# Nothing here decides a strength: the engine's law does, and the engine's
# solver measures the load it is held against.

def _member(args: dict[str, Any]) -> str | None:
    """The `member` of a joining call: one of its own two ends, or nothing."""
    member = str(args.get("member") or "").strip()
    if not member:
        return None
    if member not in (str(args.get("a", "")), str(args.get("b", ""))):
        raise Refused(f"a joint is made of one of the two things it holds: {member!r} is "
                      f"neither {args.get('a')!r} nor {args.get('b')!r}")
    return member


def _made_of_said(world: banjo.World, joint: int, member: str) -> dict[str, Any]:
    """What a joint made of a member can take cold, and what law decides it."""
    pin = next((j for j in world.joints() if j.id == joint), None)
    state = next((m for m in world.body_mechanics() if m.name == member), None)
    said: dict[str, Any] = {"member": member}
    if pin is not None:
        if pin.kind == "fixing":
            said.update({"holds_shear_n_cold": round(pin.rated_shear_n, 1),
                         "holds_tension_n_cold": round(pin.rated_tension_n, 1)})
        elif pin.kind == "link":
            said["parts_at_n_cold"] = round(pin.rated_breaks_at_n, 1)
        else:
            said["stiffness_n_m_cold"] = round(pin.rated_stiffness_n_m, 1)
    if state is not None and state.law:
        said["law"] = f"{state.law} ({state.provenance})"
    elif state is not None:
        said["law"] = (f"none: {state.material} has no law for heat, so heat will not change "
                       f"what this joint can take")
    said["note"] = ("heat the member (`heat`) and what this joint can take follows its law as "
                    "it heats, chars and burns; it parts when the load the solver measures "
                    "passes what is left. A strength you left at 0 is the member's own "
                    "section, not a weld.")
    return said


def _strength_said(world: banjo.World) -> dict[str, Any] | None:
    """What heat has done to what things can carry: each heated body with a law,
    and every joint made of a member, with its load against what it can take."""
    bodies = []
    for m in world.body_mechanics():
        if not m.law or not m.tracked:
            continue
        said: dict[str, Any] = {
            "object": m.name, "law": m.law,
            "tension_left_pct": round(100.0 * m.tension, 1),
            "shear_left_pct": round(100.0 * m.shear, 1),
            "bending_left_pct": round(100.0 * m.bending, 1),
            "stiffness_left_pct": round(100.0 * m.stiffness, 1),
            "char_mm": round(1000.0 * m.char_m, 1),
            "burned_away_mm": round(1000.0 * m.consumed_m, 2),
            "sound_section_mm": [round(1000.0 * v, 1) for v in m.sound_section_m],
            "of_section_mm": [round(1000.0 * v, 1) for v in m.section_m],
            "would_keep_if_cooled_pct": round(100.0 * min(m.tension_if_cooled,
                                                          m.shear_if_cooled), 1),
            # What is left of it, from the same state (docs/thermal-mechanics.md,
            # "One material state"): what collides and is drawn, what it weighs,
            # its cells, and what a fracture run gives its lattice.
            "now_mm": [round(1000.0 * v, 1) for v in m.remaining_m],
            "as_built_mm": [round(1000.0 * v, 1) for v in m.reference_m],
            "mass_kg": round(m.mass_kg, 3),
            "cells": m.cells, "cells_burned_away": m.cells_burned,
            "lattice_tension_left_pct": {"weakest_bond": round(100.0 * m.bond_tension_min, 1),
                                         "mean": round(100.0 * m.bond_tension_mean, 1)}}
        if not m.supported:
            said["outside_what_the_law_supports"] = True
        bodies.append(said)
    report = world.mechanics_report()
    statics = [{"object": s["name"], "answer": s["stop"], "load_n": round(s["load_n"], 1),
                "its_bonds_at_pct_of_what_breaks_them": round(100.0 * s["first_failure_ratio"], 1),
                "bonds_broken": s["bonds_removed"], "pieces": s["pieces"]}
               for s in report.get("statics", [])]
    burned = [{"object": b["name"], "at_s": round(b["time_s"], 1),
               "residue_kg": round(b["residue_kg"], 3), "why": b["why"]}
              for b in report.get("burned_away", [])]
    held = []
    for j in world.joints():
        if not j.member:
            continue
        said = {"joint": j.id, "kind": j.kind, "a": j.a, "b": j.b, "made_of": j.member,
                "attached": j.attached, "strength_left_pct": round(100.0 * j.capacity_fraction, 1)}
        if j.kind == "fixing":
            said.update({"carrying_shear_n": round(j.shear_now_n, 1),
                         "holds_shear_n": round(j.holds_shear_n, 1),
                         "held_cold_shear_n": round(j.rated_shear_n, 1),
                         "carrying_tension_n": round(j.tension_now_n, 1),
                         "holds_tension_n": round(j.holds_tension_n, 1)})
        elif j.kind == "link":
            said.update({"carrying_n": round(j.tension_n, 1), "parts_at_n": round(j.breaks_at_n, 1),
                         "parted_at_n_cold": round(j.rated_breaks_at_n, 1)})
        else:
            said.update({"stiffness_n_m": round(j.stiffness_n_m, 1),
                         "stiffness_n_m_cold": round(j.rated_stiffness_n_m, 1)})
        if j.parted_because:
            said["why_it_let_go"] = j.parted_because
        held.append(said)
    if not bodies and not held and not statics and not burned:
        return None
    out: dict[str, Any] = {"bodies": bodies, "attachments": held}
    # What statics said about a body carrying a sustained load: offered by the
    # survey (beam theory at the declared strength), answered by its lattice.
    if statics:
        out["under_load"] = statics
    if burned:
        out["burned_away"] = burned
    return out


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
        _recheck_interactions(entry)
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
        # What heat does to what each material can CARRY: the law, its source,
        # what does not come back when it cools, and where it stops applying.
        "what_heat_does_to_strength": [
            {"material": law["material"], "law": law["id"], "numbers_are": law["provenance"],
             "from": law["source"], "chars_at_k": law["char_k"] or None,
             "gets_its_strength_back_when_cooled": law["recovers_on_cooling"],
             "supported_k": law["supported_k"], "not_modelled": law["not_modelled"]}
            for law in model.get("mechanical_laws", [])],
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
    said["energy"]["handed_over_by_softening_springs_j"] = round(energy.mechanical_in_j, 4)
    strength = _strength_said(world)
    if strength is not None:
        said["strength"] = strength
    said["time_s"] = round(world.time_s, 3)
    said["note"] = ("would_last_min_at_this_rate is the fuel left over the rate it is burning "
                    "NOW: an estimate under current conditions, not a burn time. Chemical and "
                    "thermal are two parts of one stored energy. `strength` is what heat has "
                    "left of each heated body's section by its material's law (oak by EN "
                    "1995-1-2's softwood curves, iron by EN 1993-1-2, concrete by EN 1992-1-2; "
                    "other materials have none), and every joint made of a member with the "
                    "load it carries against what it can still take.")
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
# Tools that work the ground (docs/ground-work.md)
# ---------------------------------------------------------------------------
#
# A point on a body -- a pick's, a stake's -- that can go into the ground. What
# the ground does about it is ground-work-v1, a DECLARED model from the ground's
# own materials and the point's shape, applied in the solver: nothing here says
# how deep anything goes or how much comes loose. Kept with its body like an
# edge, so a rebuild puts it back and the room is opened with it.

# Where a person swinging a pick has their shoulder: 1.45 m over the ground they
# stand on (the room's eyes are at 1.62 m), standing 1.2 m back from where the
# point comes down -- an 0.8 m haft at arm's length, as the engine's own swing
# is measured (tests/ground_work_tests.cpp). And where the grip is held ready in
# front of that shoulder before a swing: 0.54 m out and 0.43 m down.
SHOULDER_M = 1.45
STAND_BACK_M = 1.2
READY_OUT_M, READY_DOWN_M = 0.54, 0.43
# The wrist a swing is made with: LiveWorld's hand torque.
HAND_TORQUE_N_M = 60.0


def _one_piece(entry: dict[str, Any], name: str) -> str:
    """The body a scene object is part of: itself, or -- joined -- the one piece
    its join group is built as, which the world names after its first part."""
    body = next((b for b in entry["scene"]["bodies"] if b["name"] == name), None)
    if body is None or not body.get("join"):
        return name
    return next(b["name"] for b in entry["scene"]["bodies"] if b.get("join") == body["join"])


def _tool_point_record(entry: dict[str, Any], world: banjo.World,
                       point_id: int) -> dict[str, Any] | None:
    """A point as its body carries it -- in the body's own frame, for a rebuild
    -- and where that is on the body as it was built, for the room."""
    point = next((p for p in world.tool_points() if p.id == point_id), None)
    body = world.body(point.body) if point is not None else None
    if point is None or body is None:
        return None
    turn = list(body.orientation_wxyz)
    inverse = _qconj(turn)
    tip = _to_body(body, point.tip_m)
    pointing = _qrot(inverse, list(point.pointing))
    grip = _to_body(body, point.grip_m)
    at, facing = (entry.get("poses") or {}).get(point.body) or (list(body.position_m), turn)

    def built(local: list[float]) -> list[float]:
        return [round(c + r, 6) for c, r in zip(at, _qrot(facing, local))]

    return {"body": point.body,
            "tip_local_m": [round(v, 6) for v in tip],
            "pointing_local": [round(v, 6) for v in pointing],
            "grip_local_m": [round(v, 6) for v in grip],
            "tip_m": built(tip), "pointing": [round(v, 6) for v in _qrot(facing, pointing)],
            "grip_m": built(grip),
            "width_m": point.width_m, "thickness_m": point.thickness_m,
            "angle_deg": point.angle_deg, "length_m": point.length_m}


def _arm_tool_points(world: banjo.World,
                     points: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """Put every kept point back on its body, where that body is now."""
    kept: list[dict[str, Any]] = []
    lost: list[str] = []
    for record in points:
        body = world.body(str(record.get("body", "")))
        if body is None:
            lost.append(f"the point on {record.get('body')}: there is nothing called that now")
            continue
        try:
            world.tool_point(record["body"], _from_body(body, record["tip_local_m"]),
                             _qrot(list(body.orientation_wxyz), record["pointing_local"]),
                             float(record["width_m"]), float(record["thickness_m"]),
                             float(record["angle_deg"]), float(record["length_m"]),
                             _from_body(body, record["grip_local_m"]))
        except banjo.BanjoError as error:
            lost.append(f"the point on {record['body']}: {error}")
            continue
        kept.append(record)
    return kept, lost


def _tool_point_said(point: banjo.ToolPoint) -> dict[str, Any]:
    return {"id": point.id, "body": point.body, "material": point.material,
            "tip_m": [round(v, 4) for v in point.tip_m],
            "pointing": [round(v, 4) for v in point.pointing],
            "grip_m": [round(v, 4) for v in point.grip_m],
            "width_mm": round(1000.0 * point.width_m, 1),
            "thickness_mm": round(1000.0 * point.thickness_m, 1),
            "angle_deg": round(point.angle_deg, 1),
            "length_mm": round(1000.0 * point.length_m, 1),
            "in": point.in_ or "nothing",
            "depth_mm": round(1000.0 * point.depth_m, 1),
            "attached": point.attached}


def _ground_work_said(w: banjo.GroundWork) -> dict[str, Any]:
    """One meeting of a point with the ground, in words and the engine's numbers."""
    said: dict[str, Any] = {"tool": w.tool, "ground": w.ground, "what_happened": w.kind,
                            "supported": w.supported, "at_m": [round(v, 3) for v in w.at_m],
                            "arrived_m_s": round(w.closing_speed_m_s, 2), "model": w.model}
    if w.why:
        said["why"] = w.why
    if w.kind in ("stopped", "glanced", "not supported"):
        return said
    said.update({
        "went_in_mm": round(1000.0 * w.depth_m, 1),
        "sideways_mm": round(1000.0 * w.sideways_m, 1),
        # Measured off the solver: the ground's push on the point, all of it.
        "work_j": round(w.work_j, 3),
        "of_it_going_in_j": round(w.penetration_work_j, 3),
        "of_it_prying_j": round(w.breakout_work_j, 3),
        "impulse_n_s": round(w.impulse_n_s, 3),
        "peak_force_n": round(w.peak_force_n, 1),
        # The model's own numbers at the deepest it went.
        "the_ground_resisted_it_going_in_n": round(w.resistance_n, 1),
        "a_pry_there_meets_n": round(w.passive_n, 1),
        "loosened_litres": round(1000.0 * w.loosened_m3, 3),
        "loosened_kg": round(w.loosened_kg, 3),
        "still_in_the_ground": w.open,
        "tool_whole": w.tool_whole,
        "tool_dent_mm": round(1000.0 * w.tool_dent_m, 2)})
    return said


def _ground_work_words(w: banjo.GroundWork) -> str:
    """One meeting, in a few words: for the story, and for the person."""
    if w.kind in ("stopped", "glanced", "not supported"):
        return f"{w.kind} on {w.ground}"
    out = f"went {1000.0 * w.depth_m:.0f} mm into the {w.ground}"
    if w.loosened_m3 > 0.0:
        out += f" and broke out {1000.0 * w.loosened_m3:.2f} L ({w.loosened_kg:.2f} kg)"
    return out


def _shoulder_for(world: banjo.World, towards: list[float], grip: list[float],
                  standing: Any = None) -> list[float]:
    """The shoulder of a person using a tool on `towards`: SHOULDER_M over the
    ground where they stand -- `standing` [x, z], or STAND_BACK_M back from
    `towards` on the way to the grip."""
    if standing is not None:
        sx, sz = _xz(standing, "standing_m")
    else:
        dx, dz = towards[0] - grip[0], towards[2] - grip[2]
        size = math.hypot(dx, dz)
        ux, uz = (dx / size, dz / size) if size > 0.05 else (1.0, 0.0)
        sx, sz = towards[0] - STAND_BACK_M * ux, towards[2] - STAND_BACK_M * uz
    here = world.survey(sx, sz)
    ground = float(here["ground_m"]) if here.get("on_the_ground") else float(towards[1])
    return [sx, ground + SHOULDER_M, sz]


def _play_stroke(world: banjo.World, events: list[dict[str, Any]], most_s: float,
                 then_s: float) -> tuple[float, str]:
    """Step until the hand's stroke is over; then hold the grip where it is -- as
    a person stops pushing once the blow has landed -- and run `then_s` more.
    Returns the seconds stepped and how the stroke ended."""
    dt = 1.0 / 240.0
    passed = 0.0
    while passed < most_s and world.hand().stroking:
        _step_answering(world, events)
        passed += dt
    ended = world.hand().stroke_ended
    if world.held:
        world.move_held(list(world.hand().grip_m))
    for _ in range(int(round(then_s / dt))):
        _step_answering(world, events)
        passed += dt
    return passed, ended


def _pull_out(world: banjo.World, events: list[dict[str, Any]]) -> float:
    """Draw what is held straight up out of the ground, 0.4 m, the way a person
    pulls a pick out when the lever's own lift did not bring it out."""
    grip = list(world.hand().grip_m)
    world.stroke([grip, [grip[0], grip[1] + 0.4, grip[2]]], 0.6, 4.0, 0.05, False, 3.0)
    return _play_stroke(world, events, 4.0, 0.3)[0]


def tool_tool_point(args: dict[str, Any]) -> dict[str, Any]:
    """Give a body a point that can go into the ground. docs/ground-work.md."""
    world_id = str(args.get("world_id"))
    entry = _world(world_id)
    world: banjo.World = _live(entry)
    asked = str(args.get("body", ""))
    name = _one_piece(entry, asked)
    tip = _triple(args.get("tip_m"), "tip_m", -200.0, 200.0)
    pointing = _triple(args.get("pointing"), "pointing", -1e6, 1e6)
    grip = _triple(args.get("grip_m") or tip, "grip_m", -200.0, 200.0)
    sizes = (_number(args.get("width_m", 0.04), "width_m", 0.002, 0.5),
             _number(args.get("thickness_m", 0.04), "thickness_m", 0.002, 0.5),
             _number(args.get("angle_deg", 30.0), "angle_deg", 5.0, 170.0),
             _number(args.get("length_m", 0.15), "length_m", 0.01, 1.0))
    had = [p for p in entry["scene"].get("tool_points") or [] if p.get("body") == name]
    others = [p for p in entry["scene"].get("tool_points") or [] if p.get("body") != name]
    # How the things here are used, as they stand before this call. Taking the
    # old point off opens the world again without it, and that rebuild holds
    # every profile to what is built -- a pick with no point is no pick -- so
    # it withdrew the pick's controls in the middle of giving it its new point.
    # The tool is never without a point once this call is over, so that
    # moment is not kept: the profiles are put back and held to what is built
    # at the end.
    uses_before = list(entry.get("interactions", []))
    withdrawn_before = list(entry.get("withdrawn", []))

    def uses_as_they_were() -> None:
        entry["interactions"] = list(uses_before)
        if withdrawn_before:
            entry["withdrawn"] = list(withdrawn_before)
        else:
            entry.pop("withdrawn", None)

    if had:
        # One point to a tool: said again, it is what it says now. The old one
        # comes off by opening the world again without it.
        _rebuild(entry, dict(entry["scene"], tool_points=others), world_id)
        world = _live(entry)
    try:
        point_id = world.tool_point(name, tip, pointing, *sizes, grip)
    except banjo.BanjoError as error:
        if had:
            _rebuild(entry, dict(entry["scene"], tool_points=others + had), world_id)
            uses_as_they_were()
        raise Refused(str(error)) from None
    record = _tool_point_record(entry, world, point_id)
    if record is not None:
        scene = dict(entry["scene"], tool_points=others + [record])
        check = entry.get("check")
        if check is not None:
            try:
                check(scene, entry.get("joints", []))
            except ValueError as problem:
                # The world has the point and the document must not.
                _rebuild(entry, dict(entry["scene"], tool_points=others + had), world_id)
                uses_as_they_were()
                raise Refused(str(problem)) from None
        entry["scene"] = scene
    if had:
        uses_as_they_were()
        _recheck_interactions(entry)
    entry["story"].append(f"gave {name} a point that can go into the ground")
    point = next(p for p in world.tool_points() if p.id == point_id)
    answer: dict[str, Any] = {"tool_point": point_id, **_tool_point_said(point)}
    if asked != name:
        answer["one_piece"] = (f"{asked} is built as one piece with everything joined with it, and "
                               f"the world calls that piece {name}: the point is on {name}")
    body = world.body(name)
    if body is not None:
        # What a hand makes of it: the engine's own mass, and its weight's pull
        # about the grip with the haft held level -- which the wrist has to hold.
        lever = math.dist(point.grip_m, body.position_m)
        about = body.mass_kg * 9.80665 * lever
        answer["mass_kg"] = round(body.mass_kg, 3)
        answer["its_weight_about_the_grip_n_m"] = round(about, 2)
        if about > HAND_TORQUE_N_M or body.mass_kg >= HAND_LIFTS_KG:
            answer["too_heavy_to_swing"] = (
                f"held level by its grip its weight pulls {about:.0f} N m, and the hand's wrist "
                f"holds {HAND_TORQUE_N_M:g} N m with {HAND_STRENGTH_N:g} N: a swing would droop "
                f"and miss. Make it lighter, or the haft shorter.")
    # A point is not controls. Without a swing-and-lever profile the person can
    # carry the tool and nothing more -- and the room's chat, measured, gave a
    # pick its point, told the person they could swing it, and never declared
    # how. So the one step left is said as the call to make.
    if not any(p.get("template") == "swing-and-lever" and p.get("tool") == name
               for p in entry.get("interactions", [])):
        lead = next((b for b in entry["scene"]["bodies"] if b["name"] == name), None)
        parts = ([b["name"] for b in entry["scene"]["bodies"]
                  if lead is not None and lead.get("join") and b.get("join") == lead["join"]]
                 or [name])
        answer["next"] = (f"A person cannot swing it yet: a point is not controls. Give them its "
                          f"controls now with interaction, object=\"<what it is called>\", "
                          f"template=\"swing-and-lever\", parts={json.dumps(parts)}, "
                          f"tool={json.dumps(name)} -- its trial swings it into soil and onto "
                          f"rock, and its numbers are what to tell them.")
    answer["note"] = (f"{name} has a point. Swung point first into soil it goes in as far as the "
                      f"soil's bearing resistance lets the swing's energy take it; pried, it "
                      f"breaks the soil out, and what comes loose is carried. Rock at least as "
                      f"hard as the point stops it. That is ground-work-v1, a declared model "
                      f"from the ground's own density, friction angle and cohesion "
                      f"(docs/ground-work.md). From now on the body collides as its cells. "
                      f"Take it by the grip with `wield` and use `strike`; `interaction` with "
                      f"template swing-and-lever gives a person its controls.")
    return answer


def tool_strike(args: dict[str, Any]) -> dict[str, Any]:
    """Swing the wielded tool's point down on the ground, or lever it out."""
    import time as clock
    world_id = str(args.get("world_id"))
    entry = _world(world_id)
    world = _require_terrain(entry)
    held = world.held
    if not held:
        raise Refused("nothing is held: take the tool by its grip with wield first")
    point = next((p for p in world.tool_points() if p.body == held and p.attached), None)
    if point is None:
        raise Refused(f"{held} has no point that can go into the ground: give it one with "
                      f"tool_point")
    lever = bool(args.get("lever"))
    grip = list(world.hand().grip_m)
    target = None
    if lever:
        towards = list(point.tip_m)
    else:
        if point.in_:
            raise Refused(f"the point of {held} is in the {point.in_}: lever it out first "
                          f"(strike with lever true)")
        at = _xz(args.get("at_m"), "at_m")
        here = world.survey(at[0], at[1])
        if not here.get("on_the_ground"):
            raise Refused("that point is off the edge of the ground")
        target = [at[0], float(here["ground_m"]), at[1]]
        towards = target
    shoulder = _shoulder_for(world, towards, grip, args.get("standing_m"))
    speed = _number(args.get("speed_m_s", 1.2 if lever else 4.0), "speed_m_s", 0.3, 12.0)
    raise_deg = _number(args.get("raise_deg", 0.0 if lever else 110.0), "raise_deg", 0.0, 170.0)
    lever_deg = _number(args.get("lever_deg", 40.0), "lever_deg", 5.0, 80.0)
    world.forget_ground_work()
    try:
        world.strike(target, shoulder, speed, raise_deg, lever, lever_deg, 3.0)
    except banjo.BanjoError as error:
        raise Refused(str(error)) from None
    events: list[dict[str, Any]] = []
    began = clock.perf_counter()
    simulated, ended = _play_stroke(world, events, 6.0, 0.5)
    pulled = False
    if lever and world.held and any(w.open for w in world.ground_work()):
        simulated += _pull_out(world, events)
        pulled = True
    work = world.ground_work()
    # What came loose went out through the ground's own dig: kept as the edit it
    # was, so the world opened again has the same hole and carries the same.
    for w in work:
        if w.dug is not None and not w.open:
            _record_edit(entry, {"dig": dict(w.dug)})
    entry["story"].append(
        (f"levered {held}" if lever else f"swung {held} at [{target[0]:.2f}, {target[2]:.2f}]")
        + (": " + "; ".join(_ground_work_words(w) for w in work) if work else ": it met no ground"))
    answer: dict[str, Any] = {"levered" if lever else "struck": held}
    if target is not None:
        answer["at_m"] = [round(v, 3) for v in target]
    answer.update({
        "shoulder_m": [round(v, 3) for v in shoulder],
        "stroke_ended": ended,
        "ground_work": [_ground_work_said(w) for w in work] or "its point met no ground",
        "carried": {m: round(v["kilograms"], 3) for m, v in sorted(_all_carried(entry).items())},
        "what_broke": events or None,
        "simulated_s": round(simulated, 3),
        "computing_took_s": round(clock.perf_counter() - began, 2)})
    if pulled:
        answer["then"] = ("the lever's own lift did not bring the point out, so the hand drew it "
                          "straight up out of the ground")
    answer["note"] = ("work, impulse and peak force are measured off the solver; what the ground "
                      "resisted with is ground-work-v1's own number (declared, docs/ground-work.md). "
                      "This is your copy: the person swings for themselves in theirs.")
    return answer


def tool_ground_work(args: dict[str, Any]) -> dict[str, Any]:
    world: banjo.World = _live(_world(args.get("world_id")))
    work = world.ground_work()
    points = world.tool_points()
    return {"ground_work": [_ground_work_said(w) for w in work] or
                           "no point has met the ground since the last strike",
            "tool_points": [_tool_point_said(p) for p in points] or
                           "no body in this world has a point that can go into the ground",
            "note": "every meeting is listed, including the ones that did nothing and why; work "
                    "and forces are measured off the solver, resistances are ground-work-v1's own "
                    "(declared, docs/ground-work.md)"}


# ---------------------------------------------------------------------------
# Terrain and water
# ---------------------------------------------------------------------------
#
# Declared in the scene document -- a "terrain" block with what the ground was
# made from and every edit made to it since, a "water" block with any change to
# its rivers -- so a rebuild makes the same ground again and the playground's
# room gets it in the spec it opens from. What the ground is and what the water
# does is the engine's: nothing here sets a level, a speed or a slope.

TERRAIN_KINDS = ["valley", "basin", "channel", "flat", "clearing"]
# What a spade takes out of the ground and a heap puts back. How much of each is
# carried is the ground's own account, kept by the engine: see _ground_carried.
GROUND_MATERIALS = ("sand", "soil")
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


def _reach(body: dict[str, Any]) -> list[float]:
    """How far a scene body reaches from its centre along each of the room's
    axes, turned as it is built (rotation_deg): a ball, its radius every way."""
    size = body["dimensions_m"]
    if body["shape"] == "sphere":
        return [size[0] / 2.0] * 3
    turn = _turn_matrix(body.get("rotation_deg"))
    return [sum(abs(turn[i][j]) * size[j] / 2.0 for j in range(3)) for i in range(3)]


def _buried(entry: dict[str, Any], body: dict[str, Any]) -> bool:
    """Whether a body asked for at [x, y, z] is wholly inside the ground: its top
    below the ground's highest point under it."""
    if not _has_terrain(entry):
        return False
    half = _reach(body)
    x, y, z = body["center_m"]
    ground = _ground_under(entry["world"], x, z, half[0], half[2])
    return ground > -1.0e8 and y + half[1] < ground


def _seat_on_ground(entry: dict[str, Any], body: dict[str, Any]) -> dict[str, Any] | None:
    """Lift a body asked for inside the ground to rest on top of it."""
    if not _has_terrain(entry):
        return None
    half = _reach(body)
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
    """How far a body reaches below its centre, turned as it is built."""
    return _reach(body)[1]


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
    spots: list[tuple[float, float]] = [(0.0, 0.0)] if body["shape"] == "sphere" else []
    if body["shape"] != "sphere":
        # Points through the box as it is turned, seen from above: square to
        # the room, the nine across its bottom; turned, up to 27, so that
        # wherever any of it is over something, that is looked at.
        turn = _turn_matrix(body.get("rotation_deg"))
        for a in (-0.9, 0.0, 0.9):
            for c in (-0.9, 0.0, 0.9):
                for b in (-0.9, 0.0, 0.9):
                    local = (half[0] * a, half[1] * c, half[2] * b)
                    spot = (round(sum(turn[0][k] * local[k] for k in range(3)), 9),
                            round(sum(turn[2][k] * local[k] for k in range(3)), 9))
                    if spot not in spots:
                        spots.append(spot)
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
    and its reply said they were resting on the floor. And measured the other
    way: told only that it would fall, a model took the peg it was about to fix
    into its post and set it down on the post's top, where nothing held it in
    the post -- so the note says that a joint made next is what holds it up."""
    top, under, _, _ = _under_footprint(entry, body)
    gap = body["center_m"][1] - _half_height(body) - top
    if gap <= IN_THE_AIR_M:
        return None
    return {"above_m": round(gap, 3), "over": under,
            "note": "it starts that far above what is under it and will fall unless a "
                    "joint holds it: if you are about to hang it (fix, hinge, slide, tie, "
                    "reeve or spring), leave it here; to set it down there instead, give "
                    "position_m as [x, z]"}


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
    shed = report.get("watershed")
    if shed:
        # The river network beyond the edges: its basins and junctions, what
        # each river is carrying where it starts, in its middle and where it
        # ends, and what crosses the valley's own edges -- all decided by the
        # water along it, either way.
        def pool(b: dict[str, Any]) -> dict[str, Any]:
            return {"name": b["name"], "level_m": round(b["level_m"], 3), "volume_m3": round(b["volume_m3"], 2),
                    "fed_m3_s": round(b["fed_m3_s"], 3), "let_out_m3_s": round(b["out_m3_s"], 3),
                    "sending_into_the_valley_m3_s": round(-b["across_m3_s"], 3)}
        said["beyond_the_edges"] = {
            "basins": [pool(b) for b in shed["basins"]],
            "junctions": [pool(j) for j in shed.get("junctions", [])],
            "rivers": [{"name": r["name"], "from": r["from"], "to": r["to"],
                        "carrying_m3_s": {"where_it_starts": round(r["in_m3_s"], 3),
                                          "in_its_middle": round(r["middle_m3_s"], 3),
                                          "where_it_ends": round(r["out_m3_s"], 3)},
                        "level_m": {"where_it_starts": round(r["level_m"][0], 3),
                                    "where_it_ends": round(r["level_m"][-1], 3)},
                        "froude": round(r["froude_now"], 2)}
                       for r in shed.get("reaches", [])],
            "connections": [{"at": c["name"], "to": c["to"],
                             "into_this_valley_m3_s": round(c["into_this_region_m3_s"], 3)}
                            for c in shed["connections"]],
            "unaccounted_m3": shed["unaccounted_m3"]}
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
    # Dug out and not yet put back, whoever dug it -- in the playground's room
    # the person's own spade included: what fill can heap.
    carried = ground.get("carried") or {}
    have = {m: round(float(carried.get(f"{m}_m3", 0.0)), 3) for m in GROUND_MATERIALS}
    if any(v > 0.0 for v in have.values()):
        said["carried_m3"] = {m: v for m, v in have.items() if v > 0.0}
    return said


def _watershed_for(report: dict[str, Any]) -> dict[str, Any] | None:
    """The river network beyond a ground's edges, from its own report
    (docs/watershed.md): beyond where its river comes in, 24 m of river coming
    down from a reservoir fed the river's own discharge; beyond its mouth, 20 m
    of river to a confluence where a brook from a spring joins it, and 20 m more
    to a lake that lets water go over its outlet. Each reach meets the ground's
    edge across the river's own span -- as wide as it, on the river's own bed
    there -- falls 1 in 200 (a brook 1 in 120), gently enough to stay
    subcritical, and starts at Manning's normal depth for what it carries. None
    for ground with no river coming in and going out."""
    water = report.get("water") or {}
    rivers, mouths = water.get("rivers") or [], water.get("mouths") or []
    path = [p for p in (water.get("river_path") or []) if p.get("level_m") is not None]
    if not rivers or not mouths or len(path) < 2:
        return None
    grid = report["grid"]
    x0, z0, cell = grid["x0_m"], grid["z0_m"], grid["cell_m"]
    x1, z1 = x0 + grid["size_m"][0], z0 + grid["size_m"][1]
    outward = {"west": (-1.0, 0.0), "east": (1.0, 0.0), "south": (0.0, -1.0), "north": (0.0, 1.0)}

    def span(edge: str, cells: list[int]) -> tuple[tuple[float, float], tuple[float, float], float]:
        """The middle of a span of an edge, which way is out of the ground there, and how wide it is."""
        mid = (cells[0] + cells[1]) / 2 * cell
        at = {"west": (x0, z0 + mid), "east": (x1, z0 + mid), "south": (x0 + mid, z0), "north": (x0 + mid, z1)}
        return at[edge], outward[edge], (cells[1] - cells[0] + 1) * cell

    def along(p: tuple[float, float], d: tuple[float, float], s: float) -> list[float]:
        return [round(p[0] + d[0] * s, 3), round(p[1] + d[1] * s, 3)]

    def normal_depth(q_m3_s: float, width_m: float, slope: float) -> float:
        return round((0.03 * (q_m3_s / width_m) / math.sqrt(slope)) ** 0.6, 3)

    river, mouth = rivers[0], mouths[0]
    q = float(river["discharge_m3_s"])
    slope, above, below, brook = 0.005, 24.0, 20.0, 24.0
    source, into_ground, source_w = span(river["enters_from"], river["cells"])
    out_at, out_of_ground, mouth_w = span(mouth["leaves_by"], mouth["cells"])
    conf_side, lake_side, spring_side, reservoir_side = math.sqrt(30.0), 30.0, 5.0, 20.0
    first_bed, last_bed = round(path[0]["bed_m"], 3), round(path[-1]["bed_m"], 3)
    above_top = round(first_bed + slope * above, 3)
    above_depth = normal_depth(q, source_w, slope)
    below_bottom = round(last_bed - slope * below, 3)
    lake_edge_bed = round(below_bottom - slope * below, 3)
    brook_bottom, brook_top = round(below_bottom + 0.05, 3), round(below_bottom + 0.25, 3)
    confluence = along(out_at, out_of_ground, below + conf_side / 2)
    aside = (-out_of_ground[1], out_of_ground[0])     # the brook comes in from one side
    return {
        "basins": [
            {"name": "the upstream reservoir", "bed_m": round(above_top - 0.35, 3), "area_m2": 400.0,
             "level_m": round(above_top + above_depth + 0.06, 3),
             "at_m": along(source, into_ground, above + reservoir_side / 2)},
            {"name": "the spring", "bed_m": round(brook_top - 0.15, 3), "area_m2": 25.0,
             "level_m": round(brook_top + 0.2, 3), "fed_m3_s": 0.1,
             "at_m": along(tuple(confluence), aside, conf_side / 2 + brook + spring_side / 2)},
            {"name": "the lake", "bed_m": round(lake_edge_bed - 0.8, 3), "area_m2": 900.0,
             "level_m": round(lake_edge_bed - 0.05, 3),
             "outlet": {"crest_m": round(lake_edge_bed + 0.05, 3), "width_m": 4.0},
             "at_m": along(out_at, out_of_ground, below + conf_side + below + lake_side / 2)}],
        "junctions": [
            {"name": "the confluence", "bed_m": round(below_bottom - 0.2, 3), "area_m2": 30.0,
             "level_m": round(below_bottom + 0.13, 3), "at_m": confluence}],
        "reaches": [
            {"name": "the river above the valley", "from": "the upstream reservoir",
             "to": {"connection": river["name"]}, "width_m": source_w, "bed_from_m": above_top,
             "bed_to_m": first_bed, "cells": 4, "depth_m": above_depth, "discharge_m3_s": q,
             "path_m": [along(source, into_ground, above), along(source, into_ground, 0.0)]},
            {"name": "the river below the valley", "from": {"connection": mouth["name"]}, "to": "the confluence",
             "width_m": mouth_w, "bed_from_m": last_bed, "bed_to_m": below_bottom, "cells": 4,
             "depth_m": normal_depth(q, mouth_w, slope), "discharge_m3_s": q,
             "path_m": [along(out_at, out_of_ground, 0.0), along(out_at, out_of_ground, below)]},
            {"name": "the brook", "from": "the spring", "to": "the confluence", "width_m": 1.0,
             "bed_from_m": brook_top, "bed_to_m": brook_bottom, "cells": 4,
             "depth_m": normal_depth(0.1, 1.0, (brook_top - brook_bottom) / brook), "discharge_m3_s": 0.1,
             "path_m": [along(tuple(confluence), aside, conf_side / 2 + brook),
                        along(tuple(confluence), aside, conf_side / 2)]},
            {"name": "the river to the lake", "from": "the confluence", "to": "the lake", "width_m": mouth_w,
             "bed_from_m": below_bottom, "bed_to_m": lake_edge_bed, "cells": 4,
             "depth_m": normal_depth(q + 0.1, mouth_w, slope), "discharge_m3_s": round(q + 0.1, 3),
             "path_m": [along(out_at, out_of_ground, below + conf_side),
                        along(out_at, out_of_ground, below + conf_side + below)]}]}


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
    if args.get("beyond_the_edges") and kind not in ("valley", "channel"):
        raise Refused(f"a {kind} has no river coming in and going out for regions beyond its edges "
                      f"to stand at: make a valley or a channel")
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
    if args.get("beyond_the_edges"):
        # The regions beyond its edges (docs/watershed.md), placed from where
        # this ground's own river comes in and leaves -- read off the engine,
        # not written down -- and the world opened again with them.
        shed = _watershed_for(entry["world"].environment_report())
        if shed is None:
            raise Refused(f"a {kind} has no river coming in and going out for regions beyond its "
                          f"edges to stand at: make a valley or a channel")
        lost = _rebuild(entry, dict(entry["scene"], water={"watershed": shed}), world_id) or lost
        entry["story"].append("stood a river network beyond the edges: a reservoir the river comes down "
                              "to it from, and below its mouth a confluence, a brook from a spring and a lake")
    entry["story"].append(f"made the ground a {kind}")
    report = entry["world"].environment_report()
    answer: dict[str, Any] = {"ground": _ground_said(report)}
    water = _water_said(entry["world"], full=True)
    if water:
        answer["water"] = water
    if kind == "clearing":
        answer["note"] = ("Level and dry: the soil's surface is at y = 0, 0.4 m of soil over rock, "
                          f"and a slab of bare rock stands {0.12:g} m proud of it, 1.6 m by 1.2 m, "
                          "centred at [1.6, -1.2]. survey says which is which anywhere. A point that "
                          "goes into the ground (tool_point) goes into the soil and is stopped by "
                          "the rock; every object added is set ON the ground if it was asked for "
                          "inside it.")
    else:
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
    if "rolling_resistance" in here:
        # The ground's own share; a ball adds its own, and rests here when the
        # sum is more than the tangent of the slope.
        ground = here["rolling_resistance"]
        steep = math.tan(math.radians(here["slope_deg"]))
        own = {m: e["rolling_resistance"] for m, e in _engine_materials()["materials"].items()}
        said["rolling_resistance"] = ground
        said["a_ball_rests_here"] = {
            "if": f"its own rolling resistance plus the ground's {ground:g} is more than "
                  f"tan(slope) = {steep:.3f}",
            **({"these_rest": sorted(m for m, c in own.items() if c + ground > steep),
                "these_roll": sorted(m for m, c in own.items() if c + ground <= steep)} if own else {})}
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


def _ground_carried(entry: dict[str, Any]) -> dict[str, dict[str, float]]:
    """The sand and soil out of this world's ground and not put back, as the
    engine counts them: every dig among its edits, less every heap made from
    them. A rebuild replays the edits, so it carries the same -- and a room
    opened from the playground's spec carries what the person's spade dug."""
    if entry.get("world") is None or not entry["scene"].get("terrain"):
        return {}
    carried = (entry["world"].environment_report().get("ground") or {}).get("carried") or {}
    out: dict[str, dict[str, float]] = {}
    for material in GROUND_MATERIALS:
        cubic = float(carried.get(f"{material}_m3", 0.0))
        if cubic > 0.0:
            out[material] = {"cubic_metres": cubic,
                             "kilograms": float(carried.get(f"{material}_kg", 0.0))}
    return out


def _all_carried(entry: dict[str, Any]) -> dict[str, dict[str, float]]:
    """Everything carried here: what was swept up, by material, and the ground."""
    return {**{m: dict(v) for m, v in entry["carried"].items()}, **_ground_carried(entry)}


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
    entry["story"].append(f"dug from {start} to {end}, {width:g} m wide and {depth:g} m deep")
    return {"dug_m3": round(dug.sand_m3 + dug.soil_m3, 3), "sand_m3": round(dug.sand_m3, 3),
            "soil_m3": round(dug.soil_m3, 3), "kilograms": round(dug.mass_kg, 1),
            "columns": dug.columns, "colliders_rebuilt": dug.chunks_rebuilt,
            "things_woken": dug.bodies_woken,
            "carried": {m: round(v["kilograms"], 1) for m, v in sorted(_all_carried(entry).items())},
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
    if material not in GROUND_MATERIALS:
        raise Refused("fill with soil or sand: what digging gives you")
    have = _ground_carried(entry).get(material, {}).get("cubic_metres", 0.0)
    if have + 1e-9 < volume:
        raise Refused(f"you are carrying {have:.3f} m^3 of {material}, and ground does not come from "
                      f"nowhere: dig {volume - have:.3f} m^3 more first, or fill with less")
    sand, soil = (volume, 0.0) if material == "sand" else (0.0, volume)
    try:
        heaped = world.deposit(at, radius, sand, soil)
    except banjo.BanjoError as error:
        raise Refused(str(error))
    _record_edit(entry, {"deposit": {"at_m": at, "radius_m": radius, "sand_m3": sand, "soil_m3": soil}})
    entry["story"].append(f"heaped {volume:g} m^3 of {material} at {at}")
    return {"heaped_m3": round(volume, 3), "of": material, "columns": heaped.columns,
            "colliders_rebuilt": heaped.chunks_rebuilt,
            "carried": {m: round(v["kilograms"], 1) for m, v in sorted(_all_carried(entry).items())},
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
    # A river whose source became a connection to the network beyond the edge
    # is fed through what stands at the top of it -- the reservoir its reach
    # comes down from: its name still sets the discharge, and the engine says no
    # to a mouth's. A basin, spring or junction out there is fed by its own
    # name (docs/watershed.md).
    shed = report.get("watershed") or {}
    rivers += [c["name"] for c in shed.get("connections", [])]
    rivers += [b["name"] for b in shed.get("basins", []) + shed.get("junctions", [])]
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
# What a fixing, a tie or a spring is MADE of (docs/thermal-mechanics.md).
MEMBER = {"type": "string",
          "description": "Which of the two (`a` or `b`) it is MADE of: the peg, the rope "
                         "segment, the limb. Heat that body and what the joint can take "
                         "follows its material's law -- oak chars and loses its strength, "
                         "iron keeps its below 400 degC, a material with no law is not "
                         "changed -- and it gives way when the load passes what is left. "
                         "With a member a strength left at 0 is the member's own section, "
                         "not a weld. Leave it out and the joint is exactly the numbers you "
                         "give it, whatever heats it."}
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
        "rotation_deg": dict(VECTOR, description=(
            "How it is turned about its own centre, degrees [x, y, z]. On its own, x leans "
            "it about its x side, y turns it about the vertical and z tilts its x side up. "
            "Together they turn it about its own x axis first, then its own y as that has "
            "turned, then its own z -- the same as z, then y, then x about the room's fixed "
            "axes. Leave it out for a thing square to the room. Give a thing its length "
            "along x: [0, 30, 12] turns it 30 degrees about the vertical and tilts its x "
            "side up 12 degrees, a ramp rising along its length, facing 30 degrees round; "
            "[10, 0, 15] leans it 10 degrees about its x side and then tilts that side up "
            "15 degrees, so against the level it rises 14.8. size_m is its own size, before "
            "it is turned; set down with position_m [x, z], its lowest corner rests on what "
            "is under it, and the answer's stands says how it stands as built.")),
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
        "join": {"type": "string",
                 "description": "Build it into ONE PIECE with every other object given the same "
                                "join name: their cells are unioned and bonded across the seam, so "
                                "a pick's haft and its arm are one body that moves, and breaks, as "
                                "one. Give the first part the join name too; the world calls the "
                                "piece by the FIRST part's name. Parts that only touch are two "
                                "things."},
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
    {"name": "turn_object",
     "description": "Stand an object upright -- its longest side vertical -- or lay it "
                    "down with its longest side level, and set it down at at_m [x, z] on "
                    "whatever is under that point (where it is, when at_m is left out). "
                    "An EDIT, like move_object -- it stands there as if it had been built "
                    "so -- that the engine holds to what the world would do with it: it "
                    "must not overlap anything, it is set on what is under it, and the "
                    "world is then run until it is still, and it must still stand as it "
                    "was put. Stood on a slope it cannot stand on, or half over an edge, it "
                    "falls in that run: the edit is refused with what happened and nothing "
                    "changes. The answer says what it stands on and what the run measured: "
                    "how far its long side is from vertical, and how far it moved. \"Turn "
                    "this upright and set it in front of me\" is this call -- for anything, "
                    "however heavy: the 73 kg a person's hand can turn does not hold it. A "
                    "ball, a cube or anything held by a joint cannot be turned this way.",
     "inputSchema": {"type": "object", "required": ["world_id", "name"], "properties": {
         "world_id": {"type": "string"}, "name": {"type": "string"},
         "stand": {"type": "string", "enum": ["upright", "lying"],
                   "description": "upright (the default): its longest side vertical. "
                                  "lying: its longest side level and its thinnest side up, "
                                  "the way a plank lies flat."},
         "at_m": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2,
                  "description": "Where to set it down, [x, z]: on whatever is under that "
                                 "point. Left out, where it is now."},
         "along": dict(VECTOR, description="Lying only: the level direction its longest "
                                           "side runs, like [1, 0, 0]. Left out, the way it "
                                           "runs now.")}}},
    {"name": "offer_actions",
     "description": "Give an object you made the actions a person would take with it: each "
                    "a label and a short program the room runs when they click on the object, "
                    "which lists its actions by number, and press one. Think about what the "
                    "thing is FOR. A chair is "
                    "pulled out from its table and pushed back in; a door is pushed open and "
                    "shut; a beam is stood upright or laid where you face; a pot is heated; "
                    "anything loose can be brought to the person. Every step is something the "
                    "engine does: stand (turn_object, with all its checks), take_hold (the "
                    "hand grips a part with its own 800 N -- at most 73 kg), carry_to a place, "
                    "put_down (lowered onto what is under it and let go), let_go, push a part "
                    "a distance toward a place (for things on joints: a door, a gate, a "
                    "lever), turn a part round the pin it turns on -- its own, or that of "
                    "what it is fixed to, as a winch's handle is to its wheel -- by degrees "
                    "or to a stop (all_the_way, half_way, all_the_way_back, back_to_start), "
                    "slide a part along its groove the same way, heat a part, and wait. A "
                    "winch's \"Raise the gate\" is a turn of its handle, stop all_the_way. "
                    "A place is relative to the person when the "
                    "key is pressed (in_front_m) or to a thing (on, beside with a side as the "
                    "person sees it, from with an offset). A program ends with the hand "
                    "empty, unless its last step is a turn or a slide, which keeps hold so "
                    "what it raised stays up, and its programs that begin with a turn or a "
                    "slide run from that hold. Each step reads only the fields of its kind, "
                    "and each place only "
                    "those of its kind. Checked when offered -- the parts exist, a hand can "
                    "move them -- "
                    "and done for real when pressed, where everything is then: a step that "
                    "cannot be done stops the action, with why. At most 9 actions; calling it "
                    "again replaces an object's actions, and an empty list takes them away.",
     "inputSchema": {"type": "object", "required": ["world_id", "name", "actions"], "properties": {
         "world_id": {"type": "string"}, "name": {"type": "string"},
         "actions": {"type": "array", "maxItems": MAX_ACTIONS, "items": {
             "type": "object", "required": ["label", "steps"], "properties": {
                 "label": {"type": "string",
                           "description": "What the person reads beside the key, like \"Pull "
                                          "it out from the table\": at most 60 characters."},
                 "steps": {"type": "array", "minItems": 1, "maxItems": MAX_STEPS, "items": {
                     "type": "object", "required": ["do"], "properties": {
                         "do": {"type": "string", "enum": list(ACTION_STEPS)},
                         "part": {"type": "string",
                                  "description": "take_hold, push, turn, slide, heat: which "
                                                 "thing; the object itself when left out."},
                         "degrees": {"type": "number",
                                     "description": "turn: how far, -360 to 360, right-handed "
                                                    "about the pin's axis -- or give stop "
                                                    "instead."},
                         "stop": {"type": "string", "enum": list(ACTION_STOPS),
                                  "description": "turn, slide: all_the_way (to its far "
                                                 "stop), half_way (half way there), "
                                                 "all_the_way_back (to its near stop) or "
                                                 "back_to_start (where it was when the room "
                                                 "was made). The hand keeps hold after a "
                                                 "last turn or slide, so what it raised "
                                                 "stays up until the person lets go."},
                         "stand": {"type": "string", "enum": ["upright", "lying"],
                                   "description": "stand: as turn_object."},
                         "along": {"type": "string", "enum": list(ACTION_ALONG),
                                   "description": "stand lying: facing -- where the person "
                                                  "faces when they press the key; across -- "
                                                  "square to that; or the room's x or z."},
                         "where": {"type": "string", "enum": list(ACTION_WHERE),
                                   "description": "stand: here (where it is then) or "
                                                  "in_front (1.2 m in front of the person)."},
                         "to": dict(ACTION_PLACE, description="carry_to: "
                                    + ACTION_PLACE["description"]),
                         "toward": dict(ACTION_PLACE, description="push: the way to push, "
                                        "toward this place. " + ACTION_PLACE["description"]),
                         "distance_m": {"type": "number",
                                        "description": "push: how far, 0.05 to 1.5 m. slide: "
                                                       "how far along its groove, -3 to 3 m "
                                                       "-- or give stop instead."},
                         "speed_m_s": {"type": "number",
                                       "description": "carry_to, push: how fast the hand "
                                                      "goes, 0.1 to 1.5 m/s."},
                         "power_w": {"type": "number", "description": "heat: 100 to 10,000 W."},
                         "seconds": {"type": "number",
                                     "description": "heat: 1 to 60 s; wait: 0.1 to 10 s."}}}}}}}}}},
    {"name": "read_knowledge",
     "description": "What the person knows, from their notebook: the techniques they know; "
                    "each design by its standing -- found, built, demonstrated for a stated "
                    "use -- with the evidence it rests on, which is the engine's own numbers "
                    "for what their tool did, scoped to what was tried and with the model's "
                    "limitations; and what is blocked and by what (a technique not known, a "
                    "process the engine does not run yet, no workbench). Read it before you "
                    "say what they can make or do. It spends nothing and changes nothing, and "
                    "no tool can add to it: it grows only from what the engine measured their "
                    "own hand doing in their own world.",
     "inputSchema": {"type": "object", "required": ["world_id"],
                     "properties": {"world_id": {"type": "string"}}}},
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
     "description": "What has been swept up in this world, by material, and the sand and soil "
                    "dug out of its ground and not put back (in cubic metres as well as kilograms).",
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
                                        "618 N, so size it against the load."},
         "member": MEMBER}}},
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
                    "is, and releasing one changes what the assembly can do. "
                    "Say what it is MADE of (`member`: the peg, the bracket) and "
                    "heat changes what it can take: heat the member and its "
                    "strength follows that material's law as it heats, chars "
                    "and burns, and it gives way when the load the solver "
                    "measures passes what is left -- not at a temperature, not "
                    "on a timer. Rate it at least twice what it holds: a scene "
                    "starts with every load suddenly applied. "
                    "Give it comes_off_n and it is ONE-WAY instead -- an arrow's "
                    "nock on a string: b comes off along `axis` by itself when "
                    "pulled harder than that, and takes any push the other way.",
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
                                          "bracket is 618 N of pure shear."},
         "member": MEMBER,
         "comes_off_n": {"type": "number",
                         "description": "Above 0 the fixing is ONE-WAY along `axis`, "
                                        "which then points the way b comes off a: an "
                                        "arrow's nock on a string, a sling's ring on "
                                        "its release pin. Pushed back into a, b takes "
                                        "whatever the push is; pulled along the axis "
                                        "it is held with up to this many newtons and "
                                        "slides off by itself past that. Leave "
                                        "holds_tension_n at 0 with it. 0, the "
                                        "default, is an ordinary two-way fixing."}}}},
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
                                          "energy back as motion."},
         "member": MEMBER}}},
    {"name": "interaction",
     "description": "Say how a PERSON USES something you built, so the playground gives "
                    "them its controls -- and try it. Two kinds. draw-and-release: a bow, "
                    "or anything whose energy is stored by drawing one part back against "
                    "elastic joints and spent when the hand lets go. Name its parts, the "
                    "part the hand draws and the way it comes back, the ONE-WAY fixing "
                    "(`fix` with comes_off_n) that holds what is shot, the elastics "
                    "(`spring`) that store the draw, and the projectile. swing-and-lever: "
                    "a pick, or any tool with a point (`tool_point`) swung so the point "
                    "comes down on the ground and pried to break the ground out. Name its "
                    "parts and the `tool`, the body with the point. Never a speed: what a "
                    "bow shoots with comes out of its limbs, and how far a point goes in "
                    "is the ground's. It is checked against what is built -- a part that "
                    "is not there, a nock that holds both ways or lets go backwards, a limb "
                    "that is not an elastic, a tool with no point are refused -- and then "
                    "TRIED in a scratch world with a person's 800 N hand: a bow drawn, held "
                    "and loosed, with what the limbs held and what the projectile left with "
                    "(`sound` false and why when the engine did not follow the shot); a "
                    "tool swung into the nearest level soil and pried out, then onto the "
                    "nearest bare rock, with how deep, the work, what came loose and what "
                    "stopped it. It is kept through every change to the world and "
                    "withdrawn, with the reason, if what it names is taken away.",
     "inputSchema": {"type": "object",
                     "required": ["world_id", "object", "parts"],
                     "properties": {
         "world_id": {"type": "string"},
         "object": {"type": "string",
                    "description": "What it is called, like 'the stiff bow' or 'the pick'. "
                                   "Said again for the same object, it replaces what was "
                                   "said."},
         "template": {"type": "string", "enum": ["draw-and-release", "swing-and-lever"],
                      "description": "How it is used: draw-and-release (the default) or "
                                     "swing-and-lever."},
         "parts": {"type": "array", "items": {"type": "string"},
                   "description": "Every body it is made of. A person takes it up by "
                                  "any of them."},
         "tool": {"type": "string",
                  "description": "swing-and-lever only: the part with the point, which the "
                                 "hand takes by its grip and swings."},
         "use": TOOL_USE_SCHEMA,
         "draw": {"type": "object", "required": ["part", "axis"],
                  "description": "draw-and-release only: what the hand draws, and how.",
                  "properties": {
             "part": {"type": "string",
                      "description": "The part the hand takes and draws: the string."},
             "axis": dict(VECTOR, description="The way it comes back when drawn: from "
                                              "the grip towards the archer, like [-1, 0, "
                                              "0]. What is shot leaves the other way."),
             "max_m": {"type": "number",
                       "description": "The most the hand asks to draw it; 0.45 by "
                                      "default. An 800 N hand stops sooner where the "
                                      "limbs balance it."},
             "speed_m_s": {"type": "number",
                           "description": "How fast the hand draws; 0.4 by default."}}},
         "nock": {"type": "object", "required": ["a", "b"],
                  "description": "draw-and-release only: the ONE-WAY fixing that holds "
                                 "what is shot on what draws it, by its two ends: a = the "
                                 "string, b = the arrow.",
                  "properties": {"a": {"type": "string"}, "b": {"type": "string"}}},
         "limbs": {"type": "array",
                   "items": {"type": "array", "items": {"type": "string"},
                             "minItems": 2, "maxItems": 2},
                   "description": "draw-and-release only: each elastic that stores the "
                                  "draw, by its two ends, like [[\"bow grip upper\", "
                                  "\"upper limb tip\"], [\"bow grip lower\", \"lower limb "
                                  "tip\"]]."},
         "projectile": {"type": "string",
                        "description": "draw-and-release only: what is shot, the one the "
                                       "nock lets go of."},
         "trial": {"type": "boolean",
                   "description": "Try it once in a scratch world: a bow drawn and loosed, "
                                  "a tool swung at soil, pried, and swung at rock. True by "
                                  "default."}}}},
    {"name": "duplicate",
     "description": "Make ANOTHER of something already built, somewhere else, exactly: "
                    "the bodies you name, every joint between them with its points moved "
                    "with it, their edges, and how a person uses them -- a second gate, a "
                    "bow beside the first. Say what should differ as `changes`, by kind of "
                    "joint: {\"spring\": {\"stiffness_n_m\": 8000}} gives a bow's limbs 8 "
                    "kN/m. Use this rather than building the same thing again, number by "
                    "number. The offset is rounded to whole cells, so the copy is the same "
                    "shape. Where the world refuses things that overlap -- the playground's "
                    "room does -- a copy that would overlap anything is refused, with the "
                    "reason, and nothing is left half made. A copied bow is tried like one "
                    "given its `interaction`.",
     "inputSchema": {"type": "object",
                     "required": ["world_id", "names", "offset_m", "prefix"],
                     "properties": {
         "world_id": {"type": "string"},
         "names": {"type": "array", "items": {"type": "string"},
                   "description": "The bodies to copy. A bow's are listed under "
                                  "things_a_person_uses."},
         "offset_m": dict(VECTOR, description="Where the copy goes, from the original, in "
                                              "metres: [dx, dy, dz]. Beside a bow is across "
                                              "its line of fire -- in z for one that shoots "
                                              "along x -- never along it."),
         "prefix": {"type": "string",
                    "description": "Put in front of every copied name, like 'stiff'."},
         "changes": {"type": "object",
                     "description": "What differs, by kind of joint (hinge, slide, tie, "
                                    "reeve, fix, spring): {\"spring\": {\"stiffness_n_m\": "
                                    "8000}}."},
         "call_it": {"type": "string",
                     "description": "What to call the copy of a thing a person uses, like "
                                    "'the stiff bow'."},
         "trial": {"type": "boolean",
                   "description": "Try a copied bow. True by default."}}}},
    {"name": "build_recipe",
     "description": "Build a mechanism the engine has been tried on, exactly, at a place: "
                    "every part, every joint and the actions a person takes with it, under "
                    "its parts' real names. The ground's height there is surveyed and "
                    "everything is laid on the room's cells, so nothing overlaps and nothing "
                    "floats. Use it for these rather than making their parts one by one: "
                    + "; ".join(f"{k}: {r['title']}" for k, r in RECIPES.items())
                    + ". It is built along x from the place. A second one's parts are "
                    "numbered. If any part would overlap what is there, nothing is built and "
                    "the answer says why.",
     "inputSchema": {"type": "object",
                     "required": ["world_id", "recipe", "at_m"],
                     "properties": {
         "world_id": {"type": "string"},
         "recipe": {"type": "string", "enum": list(RECIPES)},
         "at_m": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2,
                  "description": "The place, [x, z] on the ground: for something asked for "
                                 "near the person, the first of put_new_things_m."},
         "tool": {"type": "object",
                  "description": "For a tool that works the ground (" + ", ".join(TOOL_KINDS)
                                 + "), and optional: what makes it the tool the person asked "
                                   "for. call_it, its name ('the grub hoe'); material, the whole "
                                   "tool's -- it is one piece, and a piece is all one material "
                                   "(oak unless said; iron that size is too heavy to swing); "
                                   "head and haft, laid on the room's cells; point, the shape "
                                   "that goes into "
                                   "the ground -- a broad flat point is resisted more and breaks "
                                   "out more than a narrow one; use, how the person uses it "
                                   "(interaction's use). Leave out what should be the recipe's. "
                                   "A tool the hand's 60 N m wrist cannot hold level is not "
                                   "built, and the answer says why.",
                  "properties": {
             "call_it": {"type": "string", "description": "Its name, like 'the grub hoe'."},
             "material": {"type": "string", "enum": MATERIALS,
                          "description": "The whole tool's: it is one piece."},
             "head": {"type": "object", "description": "The part with the point: length_m 0.08 "
                                                       "to 0.48, width_m 0.04 to 0.2.",
                      "properties": {"length_m": {"type": "number"}, "width_m": {"type": "number"}}},
             "haft": {"type": "object", "description": "What the hand holds: length_m 0.48 to "
                                                       "1.44 (0.8 is the length its swing is "
                                                       "measured at).",
                      "properties": {"length_m": {"type": "number"}}},
             "point": {"type": "object", "description": "width_m 0.01 to 0.2, thickness_m 0.005 "
                                                        "to 0.04, angle_deg 10 to 120, length_m "
                                                        "0.05 to 0.4 (no broader or longer than "
                                                        "its head).",
                       "properties": {"width_m": {"type": "number"}, "thickness_m": {"type": "number"},
                                      "angle_deg": {"type": "number"}, "length_m": {"type": "number"}}},
             # Pried or not is the recipe's kind (a pick, a mattock and a hoe are
             # all pried): offered here, the chat filled it false.
             "use": {**TOOL_USE_SCHEMA,
                     "properties": {k: v for k, v in TOOL_USE_SCHEMA["properties"].items()
                                    if k != "pry"}}}}}}},
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
                    "piston. Heat a body a joint is made of (its `member`) and what the joint "
                    "can take follows the body's material law: a 40 mm oak peg given 2 kW "
                    "chars and loses its shear strength within a minute, while an iron one "
                    "given the same loses none below 400 degC. A heated BEAM carrying a load "
                    "is asked about when either side of its section can no longer take the "
                    "bending (oak gives on its compression side first) and answered by statics "
                    "on its own heated lattice: thermal_state's `strength.under_load` says held "
                    "or broke and how near its bonds came. What burns leaves the shape: a box "
                    "burns in from every face, what rests on it settles, a joint on burned-away "
                    "wood lets go, and a body whose wood is all gone leaves the world. Oak burns "
                    "away slowly -- about 0.4 mm a minute -- so a beam loses its strength to heat "
                    "long before it burns through.",
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
                    "region's temperature, pressure and how far it has pushed its piston; the "
                    "energy ledger; and STRENGTH -- what heat has left of each heated body's "
                    "section (char, what burned away, the share of its tension, shear and "
                    "bending strength left, and what it would keep if it cooled) and every "
                    "joint made of a member with the load it carries against what it can "
                    "still take. Call run first: this reads the world as it stands.",
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
    {"name": "tool_point",
     "description": "Give a body a POINT that can go into the ground -- a pick's, a stake's -- so "
                    "it digs. There is no digging power: what the ground does is ground-work-v1, "
                    "a declared model from the ground's own density, friction angle and cohesion "
                    "and the point's shape -- Terzaghi's bearing resistance to the point going "
                    "in, Rankine's passive resistance to it being pried -- applied in the solver. "
                    "So a point goes into soil only as far as the swing's energy pays for, a pry "
                    "breaks out the soil it can and what comes loose is carried, and rock at "
                    "least as hard as the point stops it. The tip must be at the very end of the "
                    "body's matter and `pointing` must run out of the body there; `length_m` is "
                    "how much of the tool is point. Points are where they are in the world now; "
                    "the point is kept with its body from then on, through the world being "
                    "opened again, and the person's room has it. A joined part is taken as its "
                    "whole piece. The answer says the tool's mass and its weight's pull about "
                    "the grip, which the hand's 60 N m wrist has to hold. Take it by the grip "
                    "with `wield` and use `strike`; `interaction` with template swing-and-lever "
                    "gives a person its controls.",
     "inputSchema": {"type": "object", "required": ["world_id", "body", "tip_m", "pointing"],
                     "properties": {
         "world_id": {"type": "string"},
         "body": {"type": "string", "description": "The body that carries the point: the tool."},
         "tip_m": dict(VECTOR, description="Where the tip is: at the very end of the body's "
                                           "matter, on the face the point comes out of."),
         "pointing": dict(VECTOR, description="The way the point goes in, out of the body at "
                                              "the tip, like [0, -1, 0] for a point hanging "
                                              "straight down."),
         "grip_m": dict(VECTOR, description="Where a hand holds it: the end of the haft."),
         "width_m": {"type": "number", "description": "Across the point's broad face; 0.04 by "
                                                      "default."},
         "thickness_m": {"type": "number", "description": "Through it where it is thickest; "
                                                          "0.04 by default."},
         "angle_deg": {"type": "number", "description": "How sharply it comes to its tip: the "
                                                        "included angle of its wedge, 30 by "
                                                        "default."},
         "length_m": {"type": "number", "description": "How much of the tool is point, back "
                                                       "from the tip; 0.15 by default. The rest "
                                                       "meets the ground as a surface."}}}},
    {"name": "strike",
     "description": "Use the wielded tool's point on the ground, as a person does. A swing: give "
                    "`at_m`, [x, z] on the ground, and the hand raises the tool back over a "
                    "shoulder 1.45 m above the ground 1.2 m back from there (or above "
                    "`standing_m`) and swings it round that shoulder so its point comes down on "
                    "at_m along its own axis -- with an 800 N hand and a 60 N m wrist, so how fast "
                    "it arrives is the hand's strength against the tool's mass, never a speed you "
                    "give it. How far it goes in, and whether rock stops it, is the ground's. "
                    "With `lever`, a point that is in the ground is pried -- turned about where it "
                    "went in, the haft coming back towards the person -- and drawn up out of it: "
                    "what the pry breaks out is carried, and the ground keeps the hole. Reports "
                    "every meeting of the point with the ground: how deep, the work and peak force "
                    "measured off the solver, the model's own resistances, what came loose and "
                    "whether the tool is whole. This is the copy of the world you are building in "
                    "-- the person strikes for themselves in theirs.",
     "inputSchema": {"type": "object", "required": ["world_id"], "properties": {
         "world_id": {"type": "string"},
         "at_m": dict(PAIR, description="Where the point comes down: [x, z] on the ground. "
                                        "Needed for a swing."),
         "lever": {"type": "boolean", "description": "Pry the point that is in the ground and "
                                                     "draw it out, instead of a swing."},
         "standing_m": dict(PAIR, description="Where the person stands, [x, z]: 1.2 m back from "
                                              "at_m towards the tool by default."),
         "speed_m_s": {"type": "number", "description": "As fast as the hand may take the grip: 4 "
                                                        "for a swing and 1.2 for a lever by "
                                                        "default. The tool goes as fast as the "
                                                        "hand can make it go."},
         "raise_deg": {"type": "number", "description": "How far back it is raised before the "
                                                        "swing: 110 by default."},
         "lever_deg": {"type": "number", "description": "How far a lever turns it: 40 by "
                                                        "default."}}}},
    {"name": "ground_work",
     "description": "Every meeting of a point with the ground since the last strike, INCLUDING "
                    "the ones that did nothing and why -- stopped by rock, glanced off, or not "
                    "supported by the model (wet ground, a point harder than the rock) -- and "
                    "every tool's point and what it is in right now.",
     "inputSchema": {"type": "object", "required": ["world_id"],
                     "properties": {"world_id": {"type": "string"}}}},
    {"name": "make_terrain",
     "description": "Give the world ground that is not flat: a VALLEY with a river running along "
                    "it (west to east, along x) and a pond beside it, made once by physics -- "
                    "drainage decided where the river runs, erosion wore its channel -- and saved. "
                    "Also a basin holding a lake, a straight sloping channel with a stream, flat "
                    "ground of soil over rock, a CLEARING -- level dry ground at y = 0, 8 m square, "
                    "0.4 m of soil over rock, with a slab of bare rock 1.6 m by 1.2 m standing 0.12 m "
                    "proud of it at [1.6, -1.2]: soil and rock side by side, to try a tool that digs "
                    "on both -- or none (back to the flat floor). The ground is rock, "
                    "soil and sand; the water is real: it flows downhill, fills what it can, and "
                    "carries and lifts what is in it. Objects already in the world stay where they "
                    "are. Answers with where the ground and the river are.",
     "inputSchema": {"type": "object", "required": ["world_id"], "properties": {
         "world_id": {"type": "string"},
         "kind": {"type": "string", "enum": TERRAIN_KINDS + ["none"]},
         "seed": {"type": "integer", "description": "A different valley for a different number."},
         "discharge_m3_s": {"type": "number",
                            "description": "What the river brings in, cubic metres a second. "
                                           "0.35 by default: a stream about 2 m wide."},
         "beyond_the_edges": {"type": "boolean",
                              "description": "A valley or a channel only. Instead of the river being "
                                             "handed its discharge at the west edge and let go over the "
                                             "east one, stand a river network beyond the edges: a reach "
                                             "coming down onto where the river comes in from a reservoir "
                                             "fed at the river's own discharge, and beyond its mouth a "
                                             "reach to a confluence, where a brook from a spring joins it, "
                                             "and another on to a lake that lets water go over its weir. "
                                             "What crosses each edge is the water on both sides, either "
                                             "way: dam the river and the reservoir fills, and less goes "
                                             "on down. water_state reports them under beyond_the_edges; "
                                             "set_river sets the reservoir's feed, or the spring's by name."}}}},
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
                    "water's ledger (in, out, and what is unaccounted for). Where the river goes "
                    "on beyond the ground's edges -- a reach down from a reservoir, reaches on to a "
                    "confluence and a lake -- also, under beyond_the_edges, each basin's and "
                    "junction's level, volume, feed, what it lets out and what it sends into the "
                    "valley (below zero when it takes from it), and what each river is carrying "
                    "where it starts, in its middle and where it ends. Call run first to let time "
                    "pass; call this before and after to see a level rise or fall.",
     "inputSchema": {"type": "object", "required": ["world_id"],
                     "properties": {"world_id": {"type": "string"}}}},
    {"name": "dig",
     "description": "Dig a trench from one point to another (or a pit, at one point), width_m "
                    "wide and depth_m below the ground as it stands. Loose sand first, then soil; "
                    "a spade stops on rock. It is real: whatever stood on that ground loses its "
                    "support and falls if nothing else holds it up, loose banks slump into the "
                    "trench, and water flows into it if it is lower than the water -- dig from a "
                    "pond or a dammed river to lower ground and it drains. What comes out is "
                    "carried -- the ground keeps the account, so opening the world again carries "
                    "the same -- and `fill` can put it back. Only the ground you dig, and what it "
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
                    "you (the carried amounts dig reports -- in the playground's room, what the "
                    "person dug with their own spade too).",
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
                    "or a drought. It takes time to arrive downstream -- run to see it. Where the "
                    "river comes down from a reservoir beyond the edge, this is what feeds the "
                    "reservoir; a basin or spring beyond the edges is fed by its own name.",
     "inputSchema": {"type": "object", "required": ["world_id", "discharge_m3_s"], "properties": {
         "world_id": {"type": "string"},
         "river": {"type": "string", "description": "Its name, or a basin's or spring's beyond the "
                                                    "edges; the only river by default."},
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
            # Not a spring made off on scenery: an anchored body never moves, so a
            # point on it is a fixed point in the world wherever it is, and an
            # arm that does not move is no arm. A bow's limb springs are made off
            # 0.36 m forward of their riser -- that is their lever -- and this
            # used to tell the chat to put them back on it.
            if tool == "spring" and (_box(entry, str(name or "")) or {}).get("anchored"):
                continue
            off = _off_body(entry, str(name or ""), args[end])
            if off is not None and off > cell:
                said.append(f"{end} is {off:.2f} m outside {name}. A {what} is made off ON "
                            f"what it holds, at a point in its matter: made off in the air, "
                            f"the point rides on {name} like the end of a stiff arm that is "
                            f"not there. Put the point on {name} -- for a rope of segments, "
                            f"0.02 m either side of the join, with the bodies touching.")
    if tool == "fix":
        # A fixing joins two things at a point in both of them: a peg in its
        # post and in what it carries. Measured, a model set a peg down on top
        # of its post and fixed it at the post's face 0.2 m below: the joint
        # held the peg there like the end of a stiff arm, and when heat parted
        # it nothing fell, because the peg was sitting on the post.
        for name in (args.get("a"), args.get("b")):
            off = _off_body(entry, str(name or ""), args.get("at_m") or [0.0, 0.0, 0.0])
            if off is not None and off > cell:
                said.append(f"at_m is {off:.2f} m outside {name}. A fixing joins two things "
                            f"at a point in both of them -- a peg in its post -- so at_m "
                            f"belongs on or in {name}: made off in the air, it holds {name} "
                            f"like the end of a stiff arm that is not there. If {name} is not "
                            f"where you meant it, take it out and add it again where it goes.")
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
    "turn_object": tool_turn_object,
    "offer_actions": tool_offer_actions,
    "read_knowledge": tool_read_knowledge,
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
    "interaction": tool_interaction,
    "duplicate": tool_duplicate,
    "build_recipe": tool_build_recipe,
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
    "tool_point": tool_tool_point,
    "strike": tool_strike,
    "ground_work": tool_ground_work,
    "make_terrain": tool_make_terrain,
    "survey": tool_survey,
    "water_state": tool_water_state,
    "dig": tool_dig,
    "fill": tool_fill,
    "cut_block": tool_cut_block,
    "set_river": tool_set_river,
    "close_world": tool_close_world,
}
# And every one of them says in its answer what its change withdrew: a bow that
# can no longer be loosed, and why (see _recheck_interactions).
HANDLERS = {name: _saying_what_was_withdrawn(handler) for name, handler in HANDLERS.items()}


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
