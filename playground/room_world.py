"""The room, held as an MCP world, so that the chat builds with the MCP's own tools.

The room used to have a second, smaller set of tools of its own -- add, move,
remove, clear -- written next to the chat and nowhere else. Every capability the
engine gained (hinges, slides, ropes, pulleys, fixings, springs) went into the C
API, the Python binding and the MCP server, and none of it reached the one
place a person in the playground actually asks for things. Asked for a castle
gate that opens with a wheel, the model had boxes and spheres and nothing to
join them with.

So there is one set of tools now, and it is the MCP server's. This module holds
the person's room as an MCP world: the MCP's scene and the MCP's joint records,
built by the MCP's own handlers. The chat is handed the MCP's own tool
definitions (see chat_tools) and every call it makes runs the MCP's own code.
A tool added to the MCP arrives here without anyone touching this file -- and a
tool that should NOT reach the room has to be named in NOT_FOR_THE_ROOM with a
reason, or tests/chat_tool_parity_tests.py fails.

What this file adds is only the translation between the MCP world (metres, the
engine's scene document) and the playground's room (millimetres, the spec the
live session is opened from), and the playground's own gate on every change:
the room refuses anything its lane could not open, at the call that did it, so
the model is told and can fix it rather than the person being told at reopen.
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

# The binding finds the library through BANJO_LIBRARY. The playground is started
# with an engine path rather than a library path, so the library next to that
# engine is the one to use -- the same build the live room runs on.
if not os.environ.get("BANJO_LIBRARY"):
    for candidate in (ROOT / "build/integration/Release/banjo.dll",
                      ROOT / "build/integration/libbanjo.so",
                      ROOT / "build/integration/Release/libbanjo.dylib"):
        if candidate.is_file():
            os.environ["BANJO_LIBRARY"] = str(candidate)
            break

sys.path.insert(0, str(ROOT / "mcp"))

import banjo_mcp     # noqa: E402  the MCP server, used as a library
import fracture_lab  # noqa: E402

# Everything the MCP offers reaches the chat except these, each for a reason
# that is about the ROOM rather than about the tool.
NOT_FOR_THE_ROOM = {
    "create_world": "the room already exists; clear_world empties it and "
                    "add_object builds it up again",
    "close_world": "the room is the person's and stays open",
    "collect": "sweeping debris into an inventory is something the person does by "
               "walking over it, in their own world",
    "carried": "the inventory belongs to the person, not to the room being built",
}

# The calls that change what the room IS, as opposed to trying things out in it.
# A room is reopened for the person only if one of these ran; running the world,
# picking something up or pulling on it changes the model's copy and nothing the
# person will be handed.
AUTHORING = {"add_object", "remove_object", "move_object", "clear_world", "drop",
             "hinge", "slide", "tie", "reeve", "fix", "spring", "unhinge",
             "hinge_friction"}

# How many objects a room may be built up to. See check() in open_room.
MAX_OBJECTS = 120

# The MCP's joint calls and the room's joint kinds, and which fields are lengths.
KIND_OF = {"hinge": "hinge", "slide": "slider", "tie": "link", "reeve": "pulley",
           "fix": "fixing", "spring": "elastic"}
TOOL_FOR = {kind: tool for tool, kind in KIND_OF.items()}


def _mm(v: Any) -> list[float]:
    return [round(float(x) * 1000.0, 3) for x in v]


def _m(v: Any) -> list[float]:
    return [float(x) / 1000.0 for x in v]


# ---------------------------------------------------------------------------
# Joints: the room's spelling and the MCP's
# ---------------------------------------------------------------------------

def joint_call(pin: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """A room joint (millimetres) as the MCP call that makes it (metres)."""
    kind = pin["kind"]
    ends = {"a": pin["a"], "b": pin["b"]}
    if kind == "hinge":
        return "hinge", {**ends, "at_m": _m(pin["at_mm"]), "axis": list(pin["axis"]),
                         "lower_deg": pin.get("lower_deg", -180.0),
                         "upper_deg": pin.get("upper_deg", 180.0),
                         "friction_n_m": pin.get("friction_n_m", 0.0)}
    if kind == "slider":
        return "slide", {**ends, "at_m": _m(pin["at_mm"]), "axis": list(pin["axis"]),
                         "lower_m": pin.get("lower_mm", 0.0) / 1000.0,
                         "upper_m": pin.get("upper_mm", 0.0) / 1000.0,
                         "friction_n": pin.get("friction_n", 0.0)}
    if kind == "link":
        return "tie", {**ends, "at_a_m": _m(pin["at_mm"]), "at_b_m": _m(pin["to_mm"]),
                       "length_m": pin.get("length_mm", 0.0) / 1000.0,
                       "breaks_at_n": pin.get("breaks_at_n", 0.0)}
    if kind == "pulley":
        return "reeve", {**ends, "at_a_m": _m(pin["at_mm"]), "at_b_m": _m(pin["to_mm"]),
                         "over_a_m": _m(pin["over_a_mm"]), "over_b_m": _m(pin["over_b_mm"]),
                         "ratio": pin.get("ratio", 1.0),
                         "length_m": pin.get("length_mm", 0.0) / 1000.0}
    if kind == "fixing":
        return "fix", {**ends, "at_m": _m(pin["at_mm"]), "axis": list(pin["axis"]),
                       "holds_tension_n": pin.get("holds_tension_n", 0.0),
                       "holds_shear_n": pin.get("holds_shear_n", 0.0)}
    if kind == "elastic":
        return "spring", {**ends, "at_a_m": _m(pin["at_mm"]), "at_b_m": _m(pin["to_mm"]),
                          "rest_m": pin.get("rest_mm", 0.0) / 1000.0,
                          "stiffness_n_m": pin.get("stiffness_n_m", 1000.0),
                          "damping_n_s_m": pin.get("damping_n_s_m", 0.0)}
    raise ValueError(f"{kind!r} is not a kind of joint the room knows")


def joint_spec(record: dict[str, Any]) -> dict[str, Any]:
    """An MCP joint record (the call that made it, in metres) as a room joint."""
    tool, args = record["tool"], record["args"]
    ends = {"kind": KIND_OF[tool], "a": str(args.get("a", "")), "b": str(args.get("b", ""))}
    if tool == "hinge":
        return {**ends, "at_mm": _mm(args["at_m"]), "axis": list(args.get("axis", [0, 1, 0])),
                "lower_deg": args.get("lower_deg", -180.0),
                "upper_deg": args.get("upper_deg", 180.0),
                "friction_n_m": args.get("friction_n_m", 0.0)}
    if tool == "slide":
        return {**ends, "at_mm": _mm(args["at_m"]), "axis": list(args.get("axis", [0, 1, 0])),
                # The MCP's default travel is a metre each way; the room's is none,
                # so the default is written out rather than left to disagree.
                "lower_mm": round(float(args.get("lower_m", -1.0)) * 1000.0, 3),
                "upper_mm": round(float(args.get("upper_m", 1.0)) * 1000.0, 3),
                "friction_n": args.get("friction_n", 0.0)}
    if tool == "tie":
        return {**ends, "at_mm": _mm(args["at_a_m"]), "to_mm": _mm(args["at_b_m"]),
                "length_mm": round(float(args.get("length_m", 0.0)) * 1000.0, 3),
                "breaks_at_n": args.get("breaks_at_n", 0.0)}
    if tool == "reeve":
        return {**ends, "at_mm": _mm(args["at_a_m"]), "to_mm": _mm(args["at_b_m"]),
                "over_a_mm": _mm(args["over_a_m"]), "over_b_mm": _mm(args["over_b_m"]),
                "ratio": args.get("ratio", 1.0),
                "length_mm": round(float(args.get("length_m", 0.0)) * 1000.0, 3)}
    if tool == "fix":
        return {**ends, "at_mm": _mm(args["at_m"]), "axis": list(args.get("axis", [0, 1, 0])),
                "holds_tension_n": args.get("holds_tension_n", 0.0),
                "holds_shear_n": args.get("holds_shear_n", 0.0)}
    return {**ends, "at_mm": _mm(args["at_a_m"]), "to_mm": _mm(args["at_b_m"]),
            "rest_mm": round(float(args.get("rest_m", 0.0)) * 1000.0, 3),
            "stiffness_n_m": args.get("stiffness_n_m", 1000.0),
            "damping_n_s_m": args.get("damping_n_s_m", 0.0)}


# ---------------------------------------------------------------------------
# The room as an MCP world, and back
# ---------------------------------------------------------------------------

# The fields a room body carries that the engine's scene document also carries,
# beyond the ones every body has. Passed through untouched both ways.
_PASSED = ("join", "rotation_deg", "subtract", "roll", "color_rgba")


def export_spec(entry: dict[str, Any], scene: dict[str, Any] | None = None,
                joints: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """The MCP world as the room spec the live session is opened from."""
    scene = entry["scene"] if scene is None else scene
    joints = entry.get("joints", []) if joints is None else joints
    bodies = []
    for body in scene["bodies"]:
        out = {"name": body["name"], "shape": body["shape"], "material": body["material"],
               "size_mm": _mm(body["dimensions_m"]), "center_mm": _mm(body["center_m"]),
               "velocity_m_s": list(body.get("velocity_m_s") or [0.0, 0.0, 0.0]),
               "anchored": bool(body.get("anchored"))}
        for key in _PASSED:
            if key in body:
                out[key] = body[key]
        bodies.append(out)
    return {**entry["room"], "bodies": bodies, "joints": [joint_spec(r) for r in joints]}


def open_room(spec: dict[str, Any]) -> str:
    """Hold a room spec as an MCP world; return the world's id.

    The joints go in through the MCP's own joint calls, so they are recorded
    exactly as a model's would be and carry the MCP's ids from the start.
    """
    validated = fracture_lab.validate(spec)
    document = fracture_lab.scene_document(validated)
    world_id = "room-" + uuid.uuid4().hex[:8]
    entry: dict[str, Any] = {
        "world": None, "scene": document, "cell_m": validated["cell_m"],
        "story": [], "carried": {}, "joints": [], "next_joint": 1,
        "room": {"algorithm": validated["algorithm"], "cell_m": validated["cell_m"],
                 "plasticity": validated.get("plasticity", "on")},
        "cells": validated.get("cells", 0),
        "max_cells": fracture_lab.ALGORITHMS[validated["algorithm"]]["max_cells"]}
    banjo_mcp.WORLDS[world_id] = entry
    try:
        lost = banjo_mcp._rebuild(entry, document, world_id, joints=[])
        assert not lost
        for pin in validated.get("joints", []):
            tool, args = joint_call(pin)
            banjo_mcp.HANDLERS[tool]({**args, "world_id": world_id})
    except Exception:
        close_room(world_id)
        raise

    # From here on, every change is held to the room's own standard. Installed
    # after the room is built rather than before, because the room as authored
    # was validated once already and checking it again per joint only costs.
    def check(scene: dict[str, Any], joints: list[dict[str, Any]]) -> None:
        if not scene["bodies"]:
            return
        # Past about 250 bodies the engine stops using the reversible trial and
        # fracture quietly stops working, and one plate coming apart can add
        # ninety. So a room may be BUILT up to 120, leaving room to break things.
        if len(scene["bodies"]) > MAX_OBJECTS:
            raise ValueError(f"the room would hold {len(scene['bodies'])} objects and "
                             f"it takes at most {MAX_OBJECTS}: past that there is no "
                             f"room left for anything to break into pieces")
        checked = fracture_lab.validate(export_spec(entry, scene, joints))
        entry["cells"] = checked.get("cells", 0)

    entry["check"] = check
    return world_id


def close_room(world_id: str) -> None:
    entry = banjo_mcp.WORLDS.pop(world_id, None)
    if entry is not None and entry.get("world") is not None:
        entry["world"].close()


def entry_of(world_id: str) -> dict[str, Any]:
    return banjo_mcp.WORLDS[world_id]


# ---------------------------------------------------------------------------
# The chat's view of the MCP
# ---------------------------------------------------------------------------

def chat_tools() -> list[dict[str, Any]]:
    """The MCP's tools, as the model's function definitions.

    The same names, the same descriptions and the same argument schemas the
    MCP server publishes, less the world_id -- the room is the only world the
    chat has -- and less NOT_FOR_THE_ROOM.
    """
    tools = []
    for tool in banjo_mcp.TOOLS:
        if tool["name"] in NOT_FOR_THE_ROOM:
            continue
        schema = dict(tool.get("inputSchema") or {"type": "object", "properties": {}})
        properties = {k: v for k, v in (schema.get("properties") or {}).items()
                      if k != "world_id"}
        required = [k for k in (schema.get("required") or []) if k != "world_id"]
        parameters = {"type": "object", "properties": properties}
        if required:
            parameters["required"] = required
        tools.append({"type": "function", "name": tool["name"],
                      "description": tool["description"], "parameters": parameters})
    return tools


def call(world_id: str, name: str, args: dict[str, Any]) -> dict[str, Any]:
    """One tool call from the chat, run by the MCP's own handler.

    A refusal comes back as {"error": ...} for the model to read and fix, which
    is what the MCP server itself does with it on the wire.
    """
    if name in NOT_FOR_THE_ROOM:
        return {"error": f"{name} is not available in the room: {NOT_FOR_THE_ROOM[name]}"}
    handler = banjo_mcp.HANDLERS.get(name)
    if handler is None:
        return {"error": f"there is no tool called {name}"}
    try:
        answer = handler({**{k: v for k, v in args.items() if k != "world_id"},
                          "world_id": world_id})
    except banjo_mcp.Refused as refusal:
        return {"error": str(refusal)}
    except Exception as failure:   # noqa: BLE001 - the model's side of the boundary
        return {"error": f"the engine failed: {failure}"}
    answer = banjo_mcp.json_safe(answer)
    if name == "clear_world":
        entry_of(world_id)["cells"] = 0
    if name in AUTHORING:
        # How much room is left, after every change that could spend it. A model
        # that knows it has 1,400 cells of 16,000 left does not try to add a
        # 3,000-cell gate and then wonder why it was refused.
        entry = entry_of(world_id)
        answer["cells_used"] = entry.get("cells", 0)
        answer["cells_left"] = max(0, entry.get("max_cells", 0) - entry.get("cells", 0))
    return answer
