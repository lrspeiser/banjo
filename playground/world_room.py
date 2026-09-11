"""The room, and a model that can reach into it.

Two things live here. The first is the room itself: a set of objects chosen so
that the three things matter can do -- shatter, dent, bounce -- are all reachable
by hand, from a standing start, without anyone having to know what speed to aim
for. The second is the model's side of the chat: real tools over the live world,
so "put a glass ball on the iron plate" is a query and a change rather than a
guess at a scene file.

The model never touches physics. It says which objects should exist and where;
the engine decides what happens to them.
"""
from __future__ import annotations

import json
import math
import urllib.error
import urllib.request
from typing import Any

import fracture_lab

# Every material in the catalogue, by the name the engine uses for it.
MATERIALS = ["iron", "aluminum", "glass", "ceramic", "oak", "rubber", "ice", "concrete"]
SHAPES = ["box", "sphere"]

# What a person calls the thing, as opposed to what it is made of. A label that
# says "alumina ceramic" and nothing else tells you the substance and not the
# object; both together is how anyone actually describes a thing.
COMMON_NAMES = {
    "iron": "iron", "aluminum": "aluminium", "glass": "glass",
    "ceramic": "alumina ceramic", "oak": "oak", "rubber": "rubber",
    "ice": "ice", "concrete": "concrete",
}

# How big a thing may be, and how far out. The room is 60 m of drawn floor; the
# engine's ground is much larger, but nothing useful happens 100 m away and a
# body that size costs cells nobody asked for.
# The object cap is about what the engine can still fracture, not about tidiness.
# Past 250 bodies the reversible trial stops being used and fracture quietly
# stops working, and a single plate coming apart can add ninety. The room starts
# at 58, so this leaves room for a couple of shatters on top of whatever gets
# built.
LIMITS = {"size_mm": (10.0, 2000.0), "position_mm": (-12000.0, 12000.0),
          "speed_m_s": 60.0, "objects": 120}


def room() -> dict[str, Any]:
    """The room as authored.

    Laid out so that everything is within reach of someone standing at the
    origin and turning round: a bench of things to pick up, a pair of anvils to
    drop them onto, and a thin pane bridged between two piers, which is the one
    arrangement in the room that will shatter at hand-held speeds.

    Sizes are deliberately mixed. A 40 mm marble and a 600 mm slab behave
    nothing alike and the difference is most of what there is to notice.
    """
    bodies: list[dict[str, Any]] = []

    def add(name, shape, material, size_mm, center_mm, **rest):
        body = {"name": name, "shape": shape, "material": material,
                "size_mm": list(size_mm), "center_mm": list(center_mm)}
        body.update(rest)
        bodies.append(body)

    # Every side is a whole number of 20 mm cells, because matter here is built
    # out of cells and a 30 mm side is not a thing the engine can make. That is
    # also the floor on how thin a plate can be: one cell, 20 mm. Real window
    # glass is 4 to 6 mm and is not reachable without a finer grid, which costs
    # about h^-4 -- eight times the cells and twice the substeps for each
    # halving -- so 20 mm is the thin end here and it is structural glass.
    #
    # Every loose object rests ON the floor, so its centre sits at half its own
    # height; putting it at y = 0 buries half of it.

    # ---- the targets: something of everything, at two thicknesses -----------
    #
    # Laid out as a grid you can walk between. Each plate bridges two short
    # piers, unsupported in the middle, because that is the arrangement that
    # breaks: the same plate lying flat on the floor is held everywhere and
    # will not.
    #
    # Thickness matters, though not in the way it first looks. The admission
    # bound is a stress-wave argument and does not depend on geometry at all:
    # a 20 mm and an 80 mm glass plate are admitted at the same 4.5 m/s. What
    # thickness changes is what the lattice then DOES -- measured, a 120 mm iron
    # ball dropped 1.5 m breaks the 20 mm glass and is held by the 40 mm.
    #
    # Plates are kept small on purpose. A 600 x 200 mm concrete plate comes
    # apart into 291 pieces and an 80 mm one exceeded Jolt's contact budget
    # outright; past 250 bodies the reversible trial stops being used and
    # fracture quietly stops working. A 240 x 160 plate is at most 96 cells, so
    # at most 96 pieces.
    TARGETS = ["glass", "ceramic", "ice", "concrete", "oak", "aluminum", "iron", "rubber"]
    for column, material in enumerate(TARGETS):
        x = -2800 + column * 800
        for row, thick in enumerate((20, 40)):
            z = -1200 - row * 800
            rest = 120                      # how high the plate is carried
            add(f"{material} pier {column}{row}L", "box", "iron", [40, rest, 160],
                [x - 100, rest // 2, z], anchored=True)
            add(f"{material} pier {column}{row}R", "box", "iron", [40, rest, 160],
                [x + 100, rest // 2, z], anchored=True)
            add(f"{material} plate {thick}mm", "box", material,
                [240, thick, 160], [x, rest + thick // 2, z])

    # ---- an anvil, for the things that need something immovable ------------
    add("iron anvil", "box", "iron", [300, 160, 240], [0, 80, -3200], anchored=True)

    # ---- a bench of things to pick up and drop -----------------------------
    #
    # Eight materials, sizes from a marble to a slab, because a 40 mm marble and
    # a 400 mm slab behave nothing alike and that difference is most of what
    # there is to notice.
    add("iron ball", "sphere", "iron", [120, 120, 120], [-900, 60, 0])
    add("aluminium ball", "sphere", "aluminum", [140, 140, 140], [-600, 70, 0])
    add("glass marble", "sphere", "glass", [60, 60, 60], [-350, 30, 0])
    add("rubber ball", "sphere", "rubber", [180, 180, 180], [-100, 90, 0])
    add("oak block", "box", "oak", [200, 200, 200], [200, 100, 0])
    add("ice cube", "box", "ice", [160, 160, 160], [500, 80, 0])
    add("concrete brick", "box", "concrete", [240, 120, 120], [800, 60, 0])
    add("ceramic cup", "box", "ceramic", [120, 140, 120], [1060, 70, 0])
    add("iron marble", "sphere", "iron", [40, 40, 40], [-1250, 20, 0])

    return {
        "algorithm": "lattice",
        "cell_m": 0.02,
        # A dent needs a material that can hold a shape it was pushed into, and
        # that is off unless a scene asks for it. "on"/"off" is the panel's
        # spelling of it; scene_document turns it into the boolean the engine
        # reads.
        "plasticity": "on",
        "bodies": bodies,
    }


def describe(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Every object and where it is, in the words the model is asked to use."""
    out = []
    for body in state.get("bodies", []):
        position = body.get("position_m") or [0, 0, 0]
        size = body.get("dimensions_m") or [0, 0, 0]
        out.append({
            "name": body.get("name", ""),
            "material": body.get("material", ""),
            "shape": body.get("shape", ""),
            "position_mm": [round(v * 1000.0, 1) for v in position],
            "size_mm": [round(v * 1000.0, 1) for v in size],
            "anchored": bool(body.get("anchored")),
            "held": bool(body.get("held")),
            "moving_m_s": round(math.sqrt(sum(v * v for v in (body.get("velocity_m_s") or [0, 0, 0]))), 3),
        })
    return out


# ---------------------------------------------------------------------------
# The model's side
# ---------------------------------------------------------------------------

TOOLS = [
    {"type": "function", "name": "list_objects",
     "description": "Every object in the room right now: name, material, shape, "
                    "position in millimetres, size in millimetres, whether it is "
                    "anchored scenery, and how fast it is moving. Call this first "
                    "whenever the answer depends on where anything is.",
     "parameters": {"type": "object", "properties": {}, "additionalProperties": False,
                    "required": []}},
    {"type": "function", "name": "add_object",
     "description": "Put a new object in the room. Use it for 'drop a ...', "
                    "'add a ...', 'put a ... above the ...'. Give it a downward "
                    "speed to make it arrive hard rather than be placed.",
     "parameters": {"type": "object", "additionalProperties": False,
                    "required": ["name", "shape", "material", "size_mm", "position_mm",
                                 "velocity_m_s", "anchored"],
                    "properties": {
                        "name": {"type": "string",
                                 "description": "What a person would call it, like "
                                                "'glass ball' or 'oak plank'."},
                        "shape": {"type": "string", "enum": SHAPES},
                        "material": {"type": "string", "enum": MATERIALS},
                        "size_mm": {"type": "array", "items": {"type": "number"},
                                    "description": "Three numbers. A sphere uses the "
                                                   "first as its diameter."},
                        "position_mm": {"type": "array", "items": {"type": "number"},
                                        "description": "Its centre: x across, y up, "
                                                       "z toward the viewer."},
                        "velocity_m_s": {"type": "array", "items": {"type": "number"},
                                         "description": "How fast it is already going. "
                                                        "[0,0,0] to just place it."},
                        "anchored": {"type": "boolean",
                                     "description": "True makes it scenery: it does not "
                                                    "move and cannot be picked up."}}}},
    {"type": "function", "name": "move_object",
     "description": "Put an existing object somewhere else, at rest.",
     "parameters": {"type": "object", "additionalProperties": False,
                    "required": ["name", "position_mm"],
                    "properties": {"name": {"type": "string"},
                                   "position_mm": {"type": "array",
                                                   "items": {"type": "number"}}}}},
    {"type": "function", "name": "remove_object",
     "description": "Take an object out of the room.",
     "parameters": {"type": "object", "additionalProperties": False,
                    "required": ["name"],
                    "properties": {"name": {"type": "string"}}}},
    {"type": "function", "name": "clear_room",
     "description": "Empty the room of everything, for building a scene from nothing.",
     "parameters": {"type": "object", "properties": {}, "additionalProperties": False,
                    "required": []}},
]

GUIDE = """You are the room. Someone is standing in a physics simulation and
talking to you about it. The engine is real: every object is matter with a
material, and it can shatter, dent or bounce depending on what it is and how
hard it is hit.

Axes, in millimetres: x runs left and right, y is up, z runs toward the person.
The floor is y = 0 and things rest ON it, so an object's centre sits at half its
height. Putting something at y = 0 buries half of it.

Call list_objects before answering anything that depends on where things are.
Then make the changes with add_object, move_object, remove_object or clear_room,
and say in one or two plain sentences what you did and what is likely to happen.

The room has a grid of plates to drop things on: every material in the
catalogue, at 20 mm and 40 mm, each bridged between two short iron piers. The
20 mm row is nearer the viewer. There is also a bench of loose objects to pick
up and an iron anvil.

What actually breaks things, measured on this engine and worth knowing:

- A thin brittle plate with a span under it is what shatters. The same plate
  lying flat on the floor is held everywhere and will not break however hard it
  is hit.
- Thickness matters, but not to whether a hit COUNTS -- the bar is the same for
  a 20 mm and an 80 mm plate. It matters to what happens next: measured, a
  120 mm iron ball dropped 1.5 m shatters the 20 mm glass plate and is held by
  the 40 mm one.
- What is doing the hitting matters as much as how fast. A glass plate needs
  4.5 m/s from an iron ball and 6.7 m/s from an aluminium one, because
  aluminium is springier and transmits less of the blow. Iron is the thing to
  reach for when you want something to break.
- Mass does not help. A 111 kg iron ball and a 0.9 kg one arriving at the same
  speed are judged identically, and a heavy thing resting on a plate will never
  break it -- the engine judges the blow, not the load.
- Metals dent rather than shatter, and only when they are hit hard -- tens of
  metres a second, not a hand-drop.
- Rubber bounces about a third of the height it fell. Concrete bounces least.
- Dropping something from higher is the reliable way to make more happen. A
  fall of h metres arrives at sqrt(2*9.81*h) metres a second; to drop something
  from four metres, put it at y = 4000 with no velocity.

Name a thing after what it is actually made of. If you make it out of aluminium
it is an aluminium tile, not a ceramic one, whatever you were asked for -- and
if you could not use the material that was asked for, say which one you used
instead. Every tool call is shown to the person underneath your answer, so an
answer that does not match what you did is one they can see is wrong.

Never claim something broke, dented or bounced. You are arranging the room; the
engine decides what happens, and the person is watching it happen."""


def _bounded(value: Any, low: float, high: float, what: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{what} is not a number")
    if not math.isfinite(number):
        raise ValueError(f"{what} is not a finite number")
    return max(low, min(high, number))


def _triple(values: Any, low: float, high: float, what: str) -> list[float]:
    if not isinstance(values, list) or len(values) != 3:
        raise ValueError(f"{what} needs three numbers")
    return [_bounded(v, low, high, what) for v in values]


class Room:
    """The room's current bodies, and the tools that change them.

    Held as a plain list of authored bodies rather than as whatever the engine
    last reported, because those are different things: the engine reports pieces
    and dents, and rebuilding a room out of two hundred shards is not what
    anyone means by "add a ball to it".
    """

    def __init__(self) -> None:
        self.spec = room()

    def bodies(self) -> list[dict[str, Any]]:
        return self.spec["bodies"]

    def checked(self, change):
        """Make a change, and undo it if the engine would not accept the room.

        The same check the world is opened with, run here rather than when the
        room is rebuilt. What matters is WHO gets told. A complaint raised at
        rebuild time arrives after the model's turn has ended, so the person
        reads a validator message about overlapping cells and the model never
        learns it did anything wrong. Raised here, it comes back as the answer
        to the tool call and the model fixes it on the next round.

        That is not hypothetical: the first time this was tried, the model laid
        a tile across two piers overlapping them by 18 cells, the room refused
        to rebuild, and nobody could tell the one thing that could move it.
        """
        before = [dict(body) for body in self.bodies()]
        try:
            note = change()
            # An empty room has nothing to check, and checking it anyway asks
            # the validator about a scene with no bodies -- which it reads as
            # the single-tile lane and complains about a plate nobody mentioned.
            # Emptying is almost always the first half of "clear this and build
            # me ...", and the half that follows is what gets checked.
            if self.bodies():
                fracture_lab.validate({**self.spec,
                                       "bodies": [dict(body) for body in self.bodies()]})
            return note
        except ValueError:
            self.spec["bodies"] = before
            raise

    def find(self, name: str) -> dict[str, Any] | None:
        wanted = str(name or "").strip().lower()
        for body in self.bodies():
            if body["name"].lower() == wanted:
                return body
        # A piece of something is still that something as far as a request goes.
        for body in self.bodies():
            if wanted.startswith(body["name"].lower()):
                return body
        return None

    # -- the tools --------------------------------------------------------
    def add_object(self, args: dict[str, Any]) -> str:
        return self.checked(lambda: self._add_object(args))

    def _add_object(self, args: dict[str, Any]) -> str:
        if len(self.bodies()) >= LIMITS["objects"]:
            raise ValueError(f"the room already holds {LIMITS['objects']} objects")
        name = str(args.get("name", "")).strip()[:60] or "thing"
        if self.find(name):
            name = f"{name} {sum(1 for b in self.bodies() if b['name'].startswith(name)) + 1}"
        shape = str(args.get("shape", "box"))
        if shape not in SHAPES:
            raise ValueError(f"{shape} is not a shape this room can build")
        material = str(args.get("material", "glass"))
        if material not in MATERIALS:
            raise ValueError(f"{material} is not a material this engine has")
        size = _triple(args.get("size_mm"), *LIMITS["size_mm"], "size_mm")
        if shape == "sphere":
            size = [size[0], size[0], size[0]]
        center = _triple(args.get("position_mm"), *LIMITS["position_mm"], "position_mm")
        speed = _triple(args.get("velocity_m_s") or [0, 0, 0],
                        -LIMITS["speed_m_s"], LIMITS["speed_m_s"], "velocity_m_s")
        self.bodies().append({"name": name, "shape": shape, "material": material,
                              "size_mm": size, "center_mm": center,
                              "velocity_m_s": speed,
                              "anchored": bool(args.get("anchored"))})
        return (f"added {name}, made of {material}, "
                f"{size[0]:.0f}x{size[1]:.0f}x{size[2]:.0f} mm "
                f"at {center[0]:.0f}, {center[1]:.0f}, {center[2]:.0f} mm")

    def move_object(self, args: dict[str, Any]) -> str:
        return self.checked(lambda: self._move_object(args))

    def _move_object(self, args: dict[str, Any]) -> str:
        body = self.find(args.get("name", ""))
        if body is None:
            raise ValueError(f"there is nothing here called {args.get('name')!r}")
        body["center_mm"] = _triple(args.get("position_mm"), *LIMITS["position_mm"],
                                    "position_mm")
        body["velocity_m_s"] = [0.0, 0.0, 0.0]
        return f"moved {body['name']} to {body['center_mm'][0]:.0f}, " \
               f"{body['center_mm'][1]:.0f}, {body['center_mm'][2]:.0f} mm"

    def remove_object(self, args: dict[str, Any]) -> str:
        return self.checked(lambda: self._remove_object(args))

    def _remove_object(self, args: dict[str, Any]) -> str:
        body = self.find(args.get("name", ""))
        if body is None:
            raise ValueError(f"there is nothing here called {args.get('name')!r}")
        self.bodies().remove(body)
        return f"removed {body['name']}"

    def clear_room(self, args: dict[str, Any]) -> str:
        return self.checked(lambda: self._clear_room(args))

    def _clear_room(self, _args: dict[str, Any]) -> str:
        count = len(self.bodies())
        self.spec["bodies"] = []
        return f"emptied the room of {count} objects"
