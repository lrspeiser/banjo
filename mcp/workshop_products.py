"""Functional built-in products layered onto the generic Workshop model.

The core :mod:`mcp.workshop` module owns wire geometry, component families and
assembly mechanics. This module registers richer products whose behavior is
important enough to deserve explicit component roles and tests, without
teaching the generic Workshop core what a cart or kettle is.

The product graph still decides physics from component semantics:

* cart: chassis + bearing mounts + axles + wheels + handle. Axles run through
  their wheel hubs so the graph can create real rotational relationships.
* kettle: a five-piece open vessel + physically attached handle. Container and
  heat-transfer roles let the graph describe liquid capacity and thermal
  behavior from geometry.
"""
from __future__ import annotations

import math
from typing import Any

from . import workshop as w

_INSTALLED = False


def _cart_trials(values: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"kind": "static_load", "on": "top", "load_kg": 150.0},
        {"kind": "cart_roll", "push_speed_m_s": 1.2, "duration_s": 1.5},
        {"kind": "tip", "direction": "x"},
        {"kind": "tip", "direction": "z"},
    ]


def _build_cart(library: w.ComponentLibrary, values: dict[str, Any]) -> list[w.WirePart]:
    material = values["material"]
    width, depth = float(values["width_m"]), float(values["depth_m"])
    wheel_d = float(values["wheel_diameter_m"])
    wheel_w = float(values["wheel_width_m"])
    deck_y = float(values["deck_height_m"])
    top_t = float(values["top_thickness_m"])
    axle_section = float(values["axle_section_m"])
    hub_y = wheel_d / 2.0
    under = deck_y - top_t
    if under <= hub_y + max(0.01, axle_section / 2.0):
        raise ValueError("cart deck_height_m must leave room above the wheel axle")

    deck = library.make(
        "surface", name="deck", material=material, at_m=(0.0, deck_y, 0.0),
        parameters={"width_m": width, "thickness_m": top_t,
                    "depth_m": depth, "profile": "square"})
    parts = list(deck.parts)
    half_w = width / 2.0
    axle_reach = half_w + wheel_w / 2.0
    mount_section = max(0.025, axle_section * 1.15)

    for i, sz in enumerate((-1, 1), 1):
        z = sz * (depth / 2.0 - float(values["axle_inset_m"]))
        axle = w.strut(
            name=f"axle-{i}", role="axle",
            from_m=(-axle_reach, hub_y, z), to_m=(axle_reach, hub_y, z),
            section_m=(axle_section, axle_section), material="iron",
            shape="cylinder", family="axle")
        parts.append(axle)

        for j, sx in enumerate((-1, 1), 1):
            x = sx * half_w * 0.55
            parts.append(w.strut(
                name=f"bearing-mount-{i}{j}", role="bearing_mount",
                from_m=(x, hub_y, z), to_m=(x, under, z),
                section_m=(mount_section, mount_section), material=material,
                family="bearing-mount"))

        for j, sx in enumerate((-1, 1), 1):
            wheel = library.make(
                "wheel", name=f"wheel-{i}{j}", material=material,
                at_m=(sx * axle_reach, hub_y, z),
                parameters={"diameter_m": wheel_d, "width_m": wheel_w})
            parts.extend(wheel.parts)

    reach = float(values["handle_reach_m"])
    bar_y, bar_z = deck_y + reach * 0.5, -depth / 2.0 - reach
    for j, sx in enumerate((-1, 1), 1):
        x = sx * half_w * 0.6
        parts.extend(library.make(
            "beam", name=f"handle-arm-{j}", material=material,
            from_m=(x, deck_y, -depth / 2.0), to_m=(x, bar_y, bar_z),
            parameters={"width_m": mount_section, "depth_m": mount_section}).parts)
    parts.extend(library.make(
        "handle", name="handle", material=material,
        from_m=(-half_w * 0.6, bar_y, bar_z),
        to_m=(half_w * 0.6, bar_y, bar_z), parameters={}).parts)
    return parts


# ---------------------------------------------------------------------------
# The rover (docs/machine-world.md, "The Workshop's robot parts"): the machine
# tools/build_rover_room.py hand-writes, assembled from the library's own
# components, with every joint authored and its machines declared, so the bench
# chat can open it, change it, and install it as exact bodies on pins.
# ---------------------------------------------------------------------------

ROVER_PARAMETERS = (
    w.Parameter("width_m", "m", 0.7, 0.3, 2.0),
    w.Parameter("depth_m", "m", 1.0, 0.4, 3.0),
    w.Parameter("deck_height_m", "m", 0.38, 0.2, 1.0, about="the deck's top above the floor"),
    w.Parameter("top_thickness_m", "m", 0.04, 0.01, 0.1),
    w.Parameter("wheel_diameter_m", "m", 0.32, 0.1, 1.0),
    w.Parameter("wheel_width_m", "m", 0.06, 0.02, 0.2),
    w.Parameter("wheel_inset_m", "m", 0.18, 0.05, 1.0, about="the drive wheels' axle forward of the back edge"),
    w.Parameter("capacity_j", "J", 100000.0, 100.0, 1e8),
    w.Parameter("charge_j", "J", 100000.0, 0.0, 1e8),
    w.Parameter("hopper_kg", "kg", 40.0, 1.0, 500.0),
    w.Parameter("material", "", "oak", choices=("oak", "iron")),
)
ROVER_MOTOR = {"stall_torque_n_m": 20.0, "no_load_rpm": 60.0, "brake_torque_n_m": 40.0}
ROVER_SENSOR_DEPTH_M = 0.003


def _build_rover(library: w.ComponentLibrary, values: dict[str, Any]) -> list[w.WirePart]:
    material = str(values["material"])
    width, depth = float(values["width_m"]), float(values["depth_m"])
    deck_y, top_t = float(values["deck_height_m"]), float(values["top_thickness_m"])
    wheel_d, wheel_w = float(values["wheel_diameter_m"]), float(values["wheel_width_m"])
    under = deck_y - top_t
    hub_y = wheel_d / 2.0
    axle_z = -depth / 2.0 + float(values["wheel_inset_m"])
    if under <= hub_y + 0.02:
        raise ValueError("rover deck_height_m must leave room above the wheels' axle")
    parts: list[w.WirePart] = []
    parts += library.make("surface", name="deck", material=material, at_m=(0.0, deck_y, 0.0),
                          parameters={"width_m": width, "thickness_m": top_t, "depth_m": depth,
                                      "profile": "square"}).parts
    mount_h = under - hub_y
    mount_x = width / 2.0 - 0.1575
    for side, sx in (("left", 1.0), ("right", -1.0)):
        parts += library.make("mount", name=f"{side} mount", material=material,
                              at_m=(sx * mount_x, under - mount_h / 2.0, axle_z),
                              parameters={"height_m": mount_h}).parts
        parts += library.make("drive-wheel", name=f"{side} wheel", material=material,
                              at_m=(sx * (mount_x + 0.1875), hub_y, axle_z),
                              parameters={"diameter_m": wheel_d, "width_m": wheel_w, "side": sx}).parts
    caster_z = depth / 2.0 - 0.12
    parts += library.make("mount", name="caster mount", material=material,
                          at_m=(0.0, under - 0.015, caster_z), parameters={"section_m": 0.10, "height_m": 0.03}).parts
    parts += library.make("caster", name="caster", material="iron", at_m=(0.0, under - 0.03, caster_z),
                          parameters={}).parts
    parts += library.make("solar-panel", name="solar panel", material="glass", at_m=(0.0, deck_y, -depth * 0.25),
                          parameters={"width_m": min(0.4, width - 0.1), "depth_m": min(0.4, depth * 0.4)}).parts
    parts += library.make("battery", name="battery", material=material, at_m=(0.0, deck_y, depth * 0.10),
                          parameters={}).parts
    parts += library.make("hopper", name="hopper", material=material, at_m=(0.0, deck_y, depth * 0.35),
                          parameters={}).parts
    return parts


def _rover_overrides(values: dict[str, Any], parts: list[w.WirePart]) -> dict[str, Any]:
    """Every joint, what drives it, and the exact model for every part."""
    from . import workshop_construction, workshop_machines
    joints = []

    def joint(kind, a, b):
        joints.append({"id": f"joint-{len(joints) + 1}", "kind": kind, "a": a, "b": b,
                       "method": "bearing" if kind == "bearing" else "bonded"})

    for name in ("solar panel", "left mount", "right mount", "caster mount", "battery", "hopper"):
        joint("fixed", "deck", name)
    for side in ("left", "right"):
        joint("bearing", f"{side} mount", f"{side} wheel stub")
        joint("fixed", f"{side} wheel stub", f"{side} wheel")
    joint("bearing", "caster mount", "caster swivel")
    joint("fixed", "caster swivel", "caster plate")
    joint("fixed", "caster plate", "caster left cheek")
    joint("fixed", "caster plate", "caster right cheek")
    joint("fixed", "caster left cheek", "caster pin")
    joint("fixed", "caster right cheek", "caster pin")
    joint("bearing", "caster pin", "caster wheel")
    construction = {"schema": workshop_construction.CONSTRUCTION_SCHEMA, "joints_authored": True,
                    "joints": joints, "added": [], "removed": []}
    depth = float(values["depth_m"])
    deck_y = float(values["deck_height_m"])
    machines = workshop_machines.checked({
        "stores": [{"name": "rover battery", "in": "battery", "capacity_j": values["capacity_j"],
                    "charge_j": values["charge_j"], "voltage_v": 24.0}],
        "motors": [{"name": f"{side} motor", "turns": [f"{side} mount", f"{side} wheel stub"],
                    "store": "rover battery", **ROVER_MOTOR} for side in ("left", "right")],
        "controls": [{"name": f"{side} wheel", "turns": [f"{side} mount", f"{side} wheel stub"]}
                     for side in ("left", "right")],
        "panels": [{"name": "solar panel", "on": "solar panel", "store": "rover battery", "area_m2": 0.2,
                    "efficiency": 0.2}],
        "programs": [{"kind": "roam", "left": "left wheel", "right": "right wheel", "setting": 1.0, "climb_deg": 8.0,
                      # Its water eyes: half a metre ahead of the deck, 0.55 m
                      # either side of the middle, as the room's rover has them.
                      "sensors": [{"kind": kind, "on": "deck", "at_m": [sx*.55,deck_y-.02,ahead],
                                   "depth_m": ROVER_SENSOR_DEPTH_M if kind=="water" else .12,"stops":watching}
                                  for kind in ("water","ground")
                                  for sx,ahead,watching in [(1,depth/2+.5,1),(0,depth/2+.5,1),(-1,depth/2+.5,1),
                                                            (1,-depth/2-.4,-1),(-1,-depth/2-.4,-1)]],
                      "routine": {"kind": "dig", "hopper_kg": values["hopper_kg"]}}],
    })
    out: dict[str, Any] = {workshop_construction.CONSTRUCTION_KEY: construction,
                           workshop_machines.MACHINES_KEY: machines}
    for part in parts:
        out[part.name] = {"mechanics": {"model": "rigid"}}
    return out


def _rover_trials(values: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"kind": "cart_roll", "push_speed_m_s": 1.0, "duration_s": 1.5}]


# ---------------------------------------------------------------------------
# The drone (docs/machine-world.md, "A rover that flies"): the rover's deck,
# battery, panel, hopper and water eyes on four rotors instead of wheels,
# assembled from the library's components, every joint authored and its
# machines declared, with a hover program and the same dig routine.
# ---------------------------------------------------------------------------

DRONE_PARAMETERS = (
    w.Parameter("deck_m", "m", 0.5, 0.3, 1.5, about="the square deck's side"),
    w.Parameter("deck_height_m", "m", 0.25, 0.1, 1.0, about="the deck's top above the floor, on its legs"),
    w.Parameter("top_thickness_m", "m", 0.03, 0.01, 0.1),
    w.Parameter("reach_m", "m", 0.6, 0.3, 2.0, about="each rotor's axis out from the middle"),
    w.Parameter("rotor_diameter_m", "m", 0.4, 0.1, 2.0),
    w.Parameter("hover_m", "m", 1.5, 0.3, 20.0),
    w.Parameter("capacity_j", "J", 2000000.0, 100.0, 1e9),
    w.Parameter("charge_j", "J", 2000000.0, 0.0, 1e9),
    w.Parameter("hopper_kg", "kg", 20.0, 1.0, 200.0),
    w.Parameter("material", "", "oak", choices=("oak", "iron")),
)
# The rotors, in order round the machine from above: front (+z), right (-x),
# back (-z), left (+x). Its thrust and drag are declared: 17 kg of machine
# needs 170 N, 43 N a rotor at 62 rad/s (k = 0.011); the induced power of
# 43 N on a 0.4 m disc is about 500 W (k' = 500 / 62^3 = 2.1e-3); a motor
# of 40 N m at stall and 1430 rpm unloaded gives that at six tenths of 48 V.
DRONE_ROTORS = (("front", (0.0, 1.0)), ("right", (-1.0, 0.0)), ("back", (0.0, -1.0)), ("left", (1.0, 0.0)))
DRONE_MOTOR = {"stall_torque_n_m": 40.0, "no_load_rpm": 1432.0, "brake_torque_n_m": 0.0,
               "rotor": {"thrust_n_per_rad2": 0.011, "drag_n_m_per_rad2": 0.0021}}


def _build_drone(library: w.ComponentLibrary, values: dict[str, Any]) -> list[w.WirePart]:
    material = str(values["material"])
    side = float(values["deck_m"])
    deck_y, top_t = float(values["deck_height_m"]), float(values["top_thickness_m"])
    reach = float(values["reach_m"])
    under = deck_y - top_t
    mount_y = deck_y - top_t / 2.0
    parts: list[w.WirePart] = []
    parts += library.make("surface", name="deck", material=material, at_m=(0.0, deck_y, 0.0),
                          parameters={"width_m": side, "thickness_m": top_t, "depth_m": side,
                                      "profile": "square"}).parts
    for name, (ux, uz) in DRONE_ROTORS:
        # An arm from the deck's edge out to the mount, in the deck's plane.
        parts += library.make("beam", name=f"{name} arm", material=material,
                              from_m=(ux * side / 2.0, mount_y, uz * side / 2.0),
                              to_m=(ux * (reach - 0.03), mount_y, uz * (reach - 0.03)),
                              parameters={"width_m": 0.03, "depth_m": 0.03}).parts
        parts += library.make("mount", name=f"{name} mount", material=material,
                              at_m=(ux * reach, mount_y, uz * reach), parameters={"section_m": 0.06, "height_m": 0.06}).parts
        parts += library.make("rotor", name=f"{name} rotor", material=material,
                              at_m=(ux * reach, mount_y, uz * reach),
                              parameters={"diameter_m": float(values["rotor_diameter_m"])}).parts
    for i, (sx, sz) in enumerate(((1, 1), (-1, 1), (1, -1), (-1, -1)), 1):
        parts.append(w.strut(name=f"leg-{i}", role="leg", from_m=(sx * side * 0.4, 0.0, sz * side * 0.4),
                             to_m=(sx * side * 0.4, under, sz * side * 0.4), section_m=(0.03, 0.03),
                             material=material, family="leg"))
    parts += library.make("battery", name="battery", material=material, at_m=(0.0, deck_y, side * 0.2),
                          parameters={"width_m": 0.2, "height_m": 0.06, "depth_m": 0.18}).parts
    parts += library.make("solar-panel", name="solar panel", material="glass", at_m=(0.0, deck_y, -side * 0.3),
                          parameters={"width_m": min(0.3, side - 0.1), "depth_m": min(0.15, side * 0.3)}).parts
    parts += library.make("hopper", name="hopper", material=material, at_m=(0.0, deck_y, -side * 0.05),
                          parameters={"width_m": 0.2, "height_m": 0.1, "depth_m": 0.2}).parts
    return parts


def _drone_overrides(values: dict[str, Any], parts: list[w.WirePart]) -> dict[str, Any]:
    from . import workshop_construction, workshop_machines
    joints = []

    def joint(kind, a, b):
        joints.append({"id": f"joint-{len(joints) + 1}", "kind": kind, "a": a, "b": b,
                       "method": "bearing" if kind == "bearing" else "bonded"})

    for name, _ in DRONE_ROTORS:
        joint("fixed", "deck", f"{name} arm")
        joint("fixed", f"{name} arm", f"{name} mount")
        joint("bearing", f"{name} mount", f"{name} rotor stub")
        joint("fixed", f"{name} rotor stub", f"{name} rotor")
        # Every blade on that hub. This template writes ITS OWN joints down and
        # nothing is worked out from what touches what afterwards (adopted()
        # returns early on joints_authored), so a blade the rotor family added
        # and this list did not name is a loose part held by no bearing, and the
        # whole drone is refused.
        for blade in parts:
            if blade.name.startswith(f"{name} rotor blade "):
                joint("fixed", f"{name} rotor", blade.name)
    for i in range(1, 5):
        joint("fixed", "deck", f"leg-{i}")
    for name in ("battery", "solar panel", "hopper"):
        joint("fixed", "deck", name)
    construction = {"schema": workshop_construction.CONSTRUCTION_SCHEMA, "joints_authored": True,
                    "joints": joints, "added": [], "removed": []}
    side, deck_y = float(values["deck_m"]), float(values["deck_height_m"])
    machines = workshop_machines.checked({
        "stores": [{"name": "drone battery", "in": "battery", "capacity_j": values["capacity_j"],
                    "charge_j": values["charge_j"], "voltage_v": 48.0}],
        "motors": [{"name": f"{name} motor", "turns": [f"{name} mount", f"{name} rotor stub"],
                    "store": "drone battery", **DRONE_MOTOR} for name, _ in DRONE_ROTORS],
        "controls": [{"name": f"{name} rotor", "turns": [f"{name} mount", f"{name} rotor stub"]}
                     for name, _ in DRONE_ROTORS],
        "panels": [{"name": "solar panel", "on": "solar panel", "store": "drone battery", "area_m2": 0.045,
                    "efficiency": 0.2}],
        "programs": [{"kind": "hover", "rotors": [f"{name} rotor" for name, _ in DRONE_ROTORS],
                      "hover_m": values["hover_m"], "setting": 1.0,
                      "sensors": [{"kind": "water", "on": "deck", "at_m": [sx * 0.3, deck_y - 0.02, side / 2.0 + 0.3],
                                   "depth_m": ROVER_SENSOR_DEPTH_M} for sx in (1.0, -1.0)],
                      "routine": {"kind": "dig", "hopper_kg": values["hopper_kg"]}}],
    })
    out: dict[str, Any] = {workshop_construction.CONSTRUCTION_KEY: construction,
                           workshop_machines.MACHINES_KEY: machines}
    for part in parts:
        out[part.name] = {"mechanics": {"model": "rigid"}}
    return out


def _drone_trials(values: dict[str, Any]) -> list[dict[str, Any]]:
    return []


# ---------------------------------------------------------------------------
# The processor (docs/machine-world.md, "Raw materials into finished goods"):
# a machine that goes nowhere and makes one thing of another. A deck on legs
# with an intake bin at its front and an output bin at its back, a battery
# and a solar panel, and a still program with a process routine. The recipe
# is a parameter, named as the room names it; a recipe the room lacks is
# declared on the routine (`recipes`) and the install gate gives it to the
# room, with the two bins as stockpiles.
# ---------------------------------------------------------------------------

PROCESSOR_PARAMETERS = (
    w.Parameter("deck_m", "m", 1.2, 0.6, 3.0, about="the square deck's side"),
    w.Parameter("deck_height_m", "m", 0.5, 0.2, 1.5),
    w.Parameter("top_thickness_m", "m", 0.04, 0.01, 0.1),
    w.Parameter("bin_m", "m", 0.5, 0.2, 1.5, about="each bin's side"),
    w.Parameter("capacity_j", "J", 2000000.0, 100.0, 1e9),
    w.Parameter("charge_j", "J", 2000000.0, 0.0, 1e9),
    w.Parameter("batch_kg", "kg", 5.0, 0.1, 500.0),
    # The cold half of the chain only. A deck on legs has no inside to make
    # hot, so a processor asked to smelt would stand at its bin for ever; the
    # bench does not offer a build that cannot work. Those recipes are the
    # electric furnace's.
    w.Parameter("recipe", "", "draw wire", choices=("draw wire", "mix concrete")),
    w.Parameter("material", "", "oak", choices=("oak", "iron")),
)
# Every recipe the Workshop's machines can be built to work, per kilogram in,
# so a machine made on the bench brings its chemistry to a room that has none.
# This is the game's chain -- playground/world_seed.CHAIN -- in the room's own
# words: `work_j_per_kg` is that chain's real specific energy taken down by its
# WORK_SCALE (20 MJ/kg of copper smelting becomes 2000 J/kg), and `needs_c` is
# the real temperature of the real process, which is what decides whether a
# recipe needs a furnace or only a bench.
#
# THE SAME EIGHT IN TWO PLACES, ON PURPOSE. world_seed belongs to the
# generator and cannot be imported from here: mcp/ does not sit on
# playground's path, and a lazy import would work in the server and fail on
# the bench, which is the worst of both. So the table is written out, and
# tests/workshop_recipe_tests.py pins every number in it to the chain. They
# cannot drift without a test saying which number moved.
CATALOGUE_RECIPES = {
    "smelt copper": {"name": "smelt copper", "in": {"copper ore": 1.0}, "out": {"copper": 0.3},
                     "work_j_per_kg": 2000.0, "s_per_kg": 2.0, "needs_c": 1085.0},
    "draw wire": {"name": "draw wire", "in": {"copper": 1.0}, "out": {"copper wire": 0.98},
                  "work_j_per_kg": 500.0, "s_per_kg": 1.0, "needs_c": 0.0},
    "smelt iron": {"name": "smelt iron", "in": {"iron ore": 1.0}, "out": {"iron": 0.62},
                   "work_j_per_kg": 2000.0, "s_per_kg": 2.5, "needs_c": 1538.0},
    "smelt aluminium": {"name": "smelt aluminium", "in": {"bauxite": 1.0}, "out": {"aluminum": 0.25},
                        "work_j_per_kg": 17000.0, "s_per_kg": 4.0, "needs_c": 960.0},
    "melt glass": {"name": "melt glass", "in": {"sand": 1.0}, "out": {"glass": 0.85},
                   "work_j_per_kg": 800.0, "s_per_kg": 3.0, "needs_c": 1400.0},
    "fire ceramic": {"name": "fire ceramic", "in": {"clay": 1.0}, "out": {"alumina ceramic": 0.70},
                     "work_j_per_kg": 1000.0, "s_per_kg": 4.0, "needs_c": 1200.0},
    "burn lime": {"name": "burn lime", "in": {"limestone": 1.0}, "out": {"cement": 0.56},
                  "work_j_per_kg": 400.0, "s_per_kg": 3.0, "needs_c": 900.0},
    "mix concrete": {"name": "mix concrete", "in": {"cement": 0.15, "sand": 0.85}, "out": {"concrete": 1.0},
                     "work_j_per_kg": 50.0, "s_per_kg": 0.5, "needs_c": 0.0},
}
#: What a processor can be built to work: the cold half of the chain. A hot
#: recipe wants a chamber to be hot IN, which a deck on legs has not got, so
#: it belongs to the electric furnace and the bench will not offer it here.
PROCESSOR_RECIPES = {name: row for name, row in CATALOGUE_RECIPES.items() if not row["needs_c"]}
#: And the hot half, which is what a furnace is for.
FURNACE_RECIPES = {name: row for name, row in CATALOGUE_RECIPES.items() if row["needs_c"]}


# ---------------------------------------------------------------------------
# The electric furnace: a box with a real inside.
#
# A processor makes one thing of another on a deck. A furnace has to make its
# INSIDE hot, and the inside is the point: a steel shell, a refractory lining,
# and the space the lining encloses, which is a real volume of real air in the
# thermal network. An element on the chamber floor puts the yard's electricity
# into that air, and the recipe will not run until the engine says the air is
# at the process temperature.
#
# WHAT THE LINING DECIDES. Heat leaves the chamber through the lining at
# U = k*A/t, and an element of P watts holds the chamber at ambient + P/U. So
# the lining is not decoration: a furnace with 25 mm of brick cannot smelt
# copper however long it is left, and one with 100 mm can smelt iron. That is
# the real relation, it is the same one a real furnace obeys, and it makes
# thickness a thing worth getting right rather than a number to fill in.
#
# WHAT THE LINING IS MADE OF, AND WHY ITS CONDUCTIVITY IS A PARAMETER. It is
# INSULATING FIREBRICK: alumina foamed to seventy-odd per cent porosity, laid
# up inside the shell, which is how a small furnace really is lined. So its
# parts are alumina ceramic -- the thing this very machine makes, by the
# `fire ceramic` recipe, which closes the chain on itself. (Until main's
# fcc5a6b an exact body could not be ceramic at all, and every Workshop
# machine compiles to exact bodies, so the lining was cast refractory
# concrete instead. Castable is a real lining too; ceramic is the better one.)
#
# Its conductivity is a parameter because it is the POROUS form's, about
# 0.2-0.3 W/m/K. The thermal model's alumina is the DENSE form at 30, which
# is right for a solid alumina part and catastrophic for a lining: it would
# need fifteen metres of wall to hold 1500 C. The number is declared here
# with its source so that nobody later "corrects" it to the dense value and
# quietly makes every furnace in the game useless.
#
# WHAT IS NOT REAL HERE, SAID PLAINLY. The chamber stores only its gas --
# 43 J/K for 50 litres of air. A real furnace's lining is 15-25 kg of
# refractory at about 1000 J/kg/K, so its heat capacity is several hundred
# times larger and a real box of this size takes HOURS to reach 1538 C, not
# the 35 seconds measured here. The steady state is a real furnace's; the
# warm-up is a game's. The honest way to slow it down is to give the lining
# thermal mass in the network, not to spoil the conductance.
# ---------------------------------------------------------------------------

ELECTRIC_FURNACE_PARAMETERS = (
    w.Parameter("chamber_w_m", "m", 0.4, 0.15, 1.2, about="the inside, across"),
    w.Parameter("chamber_d_m", "m", 0.4, 0.15, 1.2, about="the inside, front to back"),
    w.Parameter("chamber_h_m", "m", 0.3, 0.1, 1.0, about="the inside, floor to roof"),
    # 80 mm of insulating castable on a 0.8 m2 chamber is 3.0 W/K, which on a
    # 5 kW element tops out at 1686 C -- measured -- and so smelts iron with
    # about 150 C in hand. Thinner and it cannot: 40 mm reaches 853 C, which
    # will not even burn lime.
    w.Parameter("lining_m", "m", 0.08, 0.01, 0.3,
                about="the firebrick between the chamber and the shell: what it can reach"),
    w.Parameter("shell_m", "m", 0.01, 0.004, 0.05, about="the steel skin outside the lining"),
    w.Parameter("lining_k_w_m_k", "W/m/K", 0.3, 0.03, 2.0,
                about="insulating firebrick conducts about 0.3; dense alumina is 30"),
    w.Parameter("element_w", "W", 5000.0, 100.0, 50000.0, about="what its element puts into the chamber"),
    w.Parameter("capacity_j", "J", 2000000.0, 100.0, 1e9),
    w.Parameter("charge_j", "J", 2000000.0, 0.0, 1e9),
    w.Parameter("batch_kg", "kg", 5.0, 0.1, 500.0),
    w.Parameter("recipe", "", "smelt copper", choices=tuple(sorted(FURNACE_RECIPES))),
    # THE FITTINGS ONLY -- its bins and its battery case. The shell is steel
    # and the lining is refractory, and neither is a choice: a furnace with
    # an oak shell is not a cheaper furnace, it is a fire. What this picks is
    # what the two hoppers bolted to the outside are made of, and oak is the
    # sane default because the library's bin is a solid block, so an iron one
    # weighs 228 kg and costs more than the whole furnace around it.
    w.Parameter("material", "", "oak", choices=("oak", "iron"), about="its bins and battery case"),
)


def _furnace_chamber(values: dict[str, Any]) -> tuple[float, float, float]:
    """The chamber's volume, its inner surface, and how fast heat leaves it.

    All three fall out of the geometry a person chose on the bench, which is
    the point: make the box bigger and there is more of it to lose heat
    through, make the lining thicker and less gets out.
    """
    cw, cd, ch = (float(values["chamber_w_m"]), float(values["chamber_d_m"]),
                  float(values["chamber_h_m"]))
    lining = float(values["lining_m"])
    volume = cw * cd * ch
    area = 2.0 * (cw * cd) + 2.0 * (cw * ch) + 2.0 * (cd * ch)
    return volume, area, float(values["lining_k_w_m_k"]) * area / lining


def furnace_reaches_c(values: dict[str, Any], ambient_c: float = 20.0) -> float:
    """The hottest the chamber will ever get: ambient + P/U, the temperature
    at which the element and the lining's losses balance. Left running for
    ever it approaches this and never passes it, so a recipe hotter than this
    is one this furnace cannot work, whoever waits."""
    return ambient_c + float(values["element_w"]) / _furnace_chamber(values)[2]


def _build_electric_furnace(library: w.ComponentLibrary, values: dict[str, Any]) -> list[w.WirePart]:
    cw, cd, ch = (float(values["chamber_w_m"]), float(values["chamber_d_m"]),
                  float(values["chamber_h_m"]))
    lining, shell = float(values["lining_m"]), float(values["shell_m"])
    material = str(values["material"])
    # The lining's outside, then the shell's: each wraps the one within it.
    lw, ld, lh = cw + 2 * lining, cd + 2 * lining, ch + 2 * lining
    sw, sd = lw + 2 * shell, ld + 2 * shell
    floor = shell + lining                     # where the chamber's floor is
    roof = floor + ch                          # and its roof
    mid = floor + ch / 2.0                     # halfway up the chamber

    parts: list[w.WirePart] = []
    # THE LINING, six faces enclosing the chamber. Laid out as the kettle's
    # vessel is: floor and roof take the full footprint, the sides take the
    # full depth, and the front and back fit between the sides.
    parts += [
        w.WirePart("lining-floor", "container_bottom", (lw, lining, ld),
                   (0.0, shell + lining / 2.0, 0.0), material="alumina ceramic", family="lining"),
        w.WirePart("lining-roof", "container_bottom", (lw, lining, ld),
                   (0.0, roof + lining / 2.0, 0.0), material="alumina ceramic", family="lining"),
        w.WirePart("lining-left", "container_wall", (lining, ch, ld),
                   (-(cw + lining) / 2.0, mid, 0.0), material="alumina ceramic", family="lining"),
        w.WirePart("lining-right", "container_wall", (lining, ch, ld),
                   ((cw + lining) / 2.0, mid, 0.0), material="alumina ceramic", family="lining"),
        w.WirePart("lining-front", "container_wall", (cw, ch, lining),
                   (0.0, mid, -(cd + lining) / 2.0), material="alumina ceramic", family="lining"),
        w.WirePart("lining-back", "container_wall", (cw, ch, lining),
                   (0.0, mid, (cd + lining) / 2.0), material="alumina ceramic", family="lining"),
    ]
    # THE SHELL, six more outside those. Steel, and not the caller's choice:
    # it is what holds a 1500 C box together and it is what the lining is
    # cast against.
    parts += [
        w.WirePart("shell-floor", "container_bottom", (sw, shell, sd),
                   (0.0, shell / 2.0, 0.0), material="iron", family="shell"),
        w.WirePart("shell-roof", "container_bottom", (sw, shell, sd),
                   (0.0, roof + lining + shell / 2.0, 0.0), material="iron", family="shell"),
        w.WirePart("shell-left", "container_wall", (shell, lh, sd),
                   (-(lw + shell) / 2.0, shell + lh / 2.0, 0.0), material="iron", family="shell"),
        w.WirePart("shell-right", "container_wall", (shell, lh, sd),
                   ((lw + shell) / 2.0, shell + lh / 2.0, 0.0), material="iron", family="shell"),
        w.WirePart("shell-front", "container_wall", (lw, lh, shell),
                   (0.0, shell + lh / 2.0, -(ld + shell) / 2.0), material="iron", family="shell"),
        w.WirePart("shell-back", "container_wall", (lw, lh, shell),
                   (0.0, shell + lh / 2.0, (ld + shell) / 2.0), material="iron", family="shell"),
    ]
    # THE ELEMENT, lying on the chamber floor where it can be seen through an
    # open door. It is what turns the yard's charge into the chamber's heat.
    element_t = min(0.03, ch * 0.1)
    parts.append(w.WirePart("element", "container_bottom", (cw * 0.7, element_t, cd * 0.15),
                            (0.0, floor + element_t / 2.0, 0.0),
                            material="iron", family="element"))
    # THE BINS, outside where a rover can reach them: what goes in at the
    # front, what comes out at the back. The goods ledger moves the charge
    # between them; this is where a machine docks to load and unload.
    bin_m = min(0.5, min(cw, cd) * 1.1)
    # Intake ahead (+z) and output behind, the way a processor's stand, so a
    # machine that has learned to dock at one can dock at the other.
    for name, sign in (("intake bin", 1.0), ("output bin", -1.0)):
        parts += library.make("bin", name=name, material=material,
                              at_m=(0.0, shell, sign * (sd / 2.0 + bin_m / 2.0)),
                              parameters={"width_m": bin_m, "height_m": 0.15, "depth_m": bin_m}).parts
    # ITS BATTERY, on the cool side, with a panel on top of it so a furnace
    # built on its own still has somewhere to draw from.
    battery_w = min(0.25, sw * 0.5)
    parts += library.make("battery", name="battery", material=material,
                          parameters={"width_m": battery_w, "height_m": 0.12, "depth_m": battery_w},
                          at_m=(sw / 2.0 + battery_w / 2.0, shell + 0.06, 0.0)).parts
    parts += library.make("solar-panel", name="solar panel", material="glass",
                          parameters={"width_m": battery_w, "depth_m": battery_w},
                          at_m=(sw / 2.0 + battery_w / 2.0, shell + 0.12, 0.0)).parts
    return parts


def _electric_furnace_overrides(values: dict[str, Any], parts: list[w.WirePart]) -> dict[str, Any]:
    from . import workshop_construction, workshop_machines
    recipe = str(values["recipe"])
    if recipe not in FURNACE_RECIPES:
        cold = CATALOGUE_RECIPES.get(recipe)
        raise ValueError(
            f"an electric furnace does not work {recipe!r}: " +
            ("it is cold work and wants a processor, not a chamber" if cold else
             "the recipes it knows are " + ", ".join(sorted(FURNACE_RECIPES))))
    volume, _area, conductance = _furnace_chamber(values)
    # WILL IT EVER GET THERE? The chamber settles where the element and the
    # lining balance, so this is answerable on the bench, before anything is
    # built, and answering it here is worth far more than finding out by
    # watching a furnace sit at 900 C for an afternoon.
    reaches = furnace_reaches_c(values)
    wants = float(FURNACE_RECIPES[recipe]["needs_c"])
    if reaches < wants:
        raise ValueError(
            f"this furnace tops out at {reaches:.0f} C and {recipe} needs {wants:.0f} C: its "
            f"element puts in {float(values['element_w']):.0f} W and its lining loses "
            f"{conductance:.2f} W/K. Thicken the lining, shrink the chamber, or fit a bigger element")
    body = [p.name for p in parts if p.name not in ("shell-floor",)]
    joints = [{"id": f"joint-{i + 1}", "kind": "fixed", "a": "shell-floor", "b": b, "method": "bonded"}
              for i, b in enumerate(body)]
    construction = {"schema": workshop_construction.CONSTRUCTION_SCHEMA, "joints_authored": True,
                    "joints": joints, "added": [], "removed": []}
    machines = workshop_machines.checked({
        "stores": [{"name": "furnace battery", "in": "battery", "capacity_j": values["capacity_j"],
                    "charge_j": values["charge_j"], "voltage_v": 48.0}],
        "motors": [], "controls": [],
        "panels": [{"name": "solar panel", "on": "solar panel", "store": "furnace battery",
                    "area_m2": round(min(0.25, (float(values["chamber_w_m"]) + 2 * float(values["lining_m"])
                                                + 2 * float(values["shell_m"])) * 0.5) ** 2, 4),
                    "efficiency": 0.2}],
        "chambers": [{"name": "chamber", "in": "lining-floor", "volume_m3": round(volume, 6),
                      "wall_conductance_w_k": round(conductance, 4)}],
        "programs": [{"kind": "still", "store": "furnace battery",
                      "chamber": "chamber", "element_w": values["element_w"],
                      "routine": {"kind": "process", "recipe": recipe, "intake": "intake bin",
                                  "output": "output bin", "batch_kg": values["batch_kg"],
                                  "recipes": [dict(FURNACE_RECIPES[recipe])]}}],
    })
    out: dict[str, Any] = {workshop_construction.CONSTRUCTION_KEY: construction,
                           workshop_machines.MACHINES_KEY: machines}
    for part in parts:
        out[part.name] = {"mechanics": {"model": "rigid"}}
    return out


def _electric_furnace_trials(values: dict[str, Any]) -> list[dict[str, Any]]:
    del values
    return []


SOLAR_ARRAY_PARAMETERS = (
    w.Parameter("panels", "", 6.0, 1.0, 24.0, about="how many panels on the frame"),
    w.Parameter("panel_w_m", "m", 0.9, 0.2, 2.0, about="each panel across"),
    w.Parameter("panel_d_m", "m", 0.6, 0.2, 2.0, about="each panel deep"),
    w.Parameter("frame_height_m", "m", 0.6, 0.2, 2.5),
    # A store big enough to carry a yard through a night. The sun sets in
    # this world (docs, the sun's day), so a farm that holds only what it
    # makes in an hour stops everything it feeds at dusk.
    w.Parameter("capacity_j", "J", 2.0e7, 100.0, 1e10),
    w.Parameter("charge_j", "J", 2.0e6, 0.0, 1e10),
    w.Parameter("max_power_w", "W", 0.0, 0.0, 1e6,
                about="battery output rating; zero is unbounded authoring output"),
    w.Parameter("efficiency", "", 0.2, 0.05, 0.35,
                about="what share of the sunlight on a panel becomes power"),
    w.Parameter("material", "", "oak", choices=("oak", "iron")),
    # The glass of each panel. Module glass is 3-4 mm; the 10 mm default is
    # the yard array as it has always been built.
    w.Parameter("panel_thickness_m", "m", 0.01, 0.004, 0.05, about="each panel's glass"),
)


def _build_solar_array(library: w.ComponentLibrary, values: dict[str, Any]) -> list[w.WirePart]:
    """A frame on four legs with a FIELD of panels on it, and a battery under.

    Rows and columns, squared off. Six panels 0.9 m across in one row is a
    5.7 m frame and a surface is allowed 4 m, so a line stops being buildable
    at about four panels; a grid grows both ways and stays inside it.

    All facing up. The engine reads a panel's own normal against the sun, and
    tilting the frame would be claiming a tracking mount nobody has built.
    """
    material = str(values["material"])
    count = max(1, int(round(float(values["panels"]))))
    pw, pd = float(values["panel_w_m"]), float(values["panel_d_m"])
    high = float(values["frame_height_m"])
    gap = 0.06
    # As square as the count allows, then narrowed until the frame fits what
    # a surface may be. Refusing would be worse: a farm somebody asked for
    # twenty panels of is a farm four panels deep, not an error.
    bay = 0.5                                # a bay at one end for the battery
    across = max(1, math.ceil(math.sqrt(count)))
    while across > 1 and across * pw + (across - 1) * gap + bay + 0.12 > 3.9:
        across -= 1
    down = math.ceil(count / across)
    span = across * pw + (across - 1) * gap
    deep = down * pd + (down - 1) * gap
    wide = span + bay + 0.12
    under = high - 0.04                      # what the legs reach, as a processor's do
    parts: list[w.WirePart] = []
    parts += library.make("surface", name="frame", material=material, at_m=(0.0, high, 0.0),
                          parameters={"width_m": round(wide, 4), "thickness_m": 0.04,
                                      "depth_m": round(min(3.9, deep + 0.12), 4),
                                      "profile": "square"}).parts
    for i, (sx, sz) in enumerate(((1, 1), (-1, 1), (1, -1), (-1, -1)), 1):
        parts.append(w.strut(name=f"leg-{i}", role="leg",
                             from_m=(sx * wide * 0.45, 0.0, sz * deep * 0.45),
                             to_m=(sx * wide * 0.45, under, sz * deep * 0.45),
                             section_m=(0.05, 0.05), material=material, family="leg"))
    # The panels fill the frame from its left edge, leaving the bay clear.
    left = -wide / 2.0 + 0.06 + pw / 2.0
    front = -(deep - pd) / 2.0
    for i in range(count):
        row, column = divmod(i, across)
        parts += library.make("solar-panel", name=f"panel-{i + 1}", material="glass",
                              at_m=(left + column * (pw + gap), high, front + row * (pd + gap)),
                              parameters={"width_m": pw, "depth_m": pd,
                                          "thickness_m": float(values.get("panel_thickness_m", 0.01))}).parts
    # ON the frame, at its height, like everything else a frame carries. Hung
    # below it the compound had a part touching nothing and the engine
    # refused the whole scene: "precise compound parts must meet".
    parts += library.make("battery", name="battery", material=material,
                          at_m=(wide / 2.0 - bay / 2.0 - 0.06, high, 0.0),
                          parameters={"width_m": 0.4, "height_m": 0.25, "depth_m": 0.4}).parts
    return parts


def _solar_array_overrides(values: dict[str, Any], parts: list[w.WirePart]) -> dict[str, Any]:
    from . import workshop_construction, workshop_machines
    count = max(1, int(round(float(values["panels"]))))
    area = round(float(values["panel_w_m"]) * float(values["panel_d_m"]), 4)
    held = [f"leg-{i}" for i in range(1, 5)] + [f"panel-{i}" for i in range(1, count + 1)] + ["battery"]
    joints = [{"id": f"joint-{i + 1}", "kind": "fixed", "a": "frame", "b": b, "method": "bonded"}
              for i, b in enumerate(held)]
    machines = workshop_machines.checked({
        "stores": [{"name": "array battery", "in": "battery", "capacity_j": values["capacity_j"],
                    "charge_j": values["charge_j"], "voltage_v": 48.0,
                    "max_power_w":values["max_power_w"], "bank_reserve_fraction":0.05}],
        "motors": [], "controls": [], "programs": [],
        # Every panel on the one store. That is the whole point of a farm:
        # capacity where it is wanted, not a panel per machine.
        "panels": [{"name": f"panel-{i + 1}", "on": f"panel-{i + 1}", "store": "array battery",
                    "area_m2": area, "efficiency": float(values["efficiency"])}
                   for i in range(count)],
    })
    out: dict[str, Any] = {
        workshop_construction.CONSTRUCTION_KEY: {
            "schema": workshop_construction.CONSTRUCTION_SCHEMA, "joints_authored": True,
            "joints": joints, "added": [], "removed": []},
        workshop_machines.MACHINES_KEY: machines}
    for part in parts:
        out[part.name] = {"mechanics": {"model": "rigid"}}
    return out


def _solar_array_trials(values: dict[str, Any]) -> list[dict[str, Any]]:
    return []


MINE_LAMP_PARAMETERS = (
    w.Parameter("watts", "W", 20.0, 1.0, 500.0, about="what it asks for when it is switched on"),
    w.Parameter("efficacy_lm_w", "lm/W", 120.0, 5.0, 200.0,
                about="lumens for each watt it gets; an LED is about 120, a filament about 15"),
    w.Parameter("globe_m", "m", 0.12, 0.05, 0.3),
    w.Parameter("bracket_m", "m", 0.10, 0.04, 0.4),
    w.Parameter("foot_m", "m", 0.22, 0.10, 0.6, about="the plate it stands on"),
    w.Parameter("material", "", "iron", choices=("iron", "oak")),
)


def _build_mine_lamp(library: w.ComponentLibrary, values: dict[str, Any]) -> list[w.WirePart]:
    """A lamp on a foot: what you carry into a heading and stand on the floor.

    It comes out of the Workshop DARK. A lamp is a fitting, not a torch -- it
    lights when somebody runs a cable to it (docs/machine-world.md, "Light
    underground"), which is the whole reason for making the cable a real thing.
    """
    material = str(values["material"])
    foot = float(values["foot_m"])
    parts: list[w.WirePart] = []
    parts += library.make("surface", name="foot", material=material, at_m=(0.0, 0.03, 0.0),
                          parameters={"width_m": foot, "thickness_m": 0.03, "depth_m": foot,
                                      "profile": "square"}).parts
    parts += library.make("lamp", name="globe", material=material, at_m=(0.0, 0.03, 0.0),
                          parameters={"globe_m": float(values["globe_m"]),
                                      "bracket_m": float(values["bracket_m"])}).parts
    return parts


def _mine_lamp_overrides(values: dict[str, Any], parts: list[w.WirePart]) -> dict[str, Any]:
    from . import workshop_construction, workshop_machines
    joints = [{"id": f"joint-{i + 1}", "kind": "fixed", "a": "foot", "b": b, "method": "bonded"}
              for i, b in enumerate(["globe bracket", "globe"])]
    machines = workshop_machines.checked({
        "stores": [], "motors": [], "controls": [], "programs": [], "panels": [],
        # No store and no cable: unwired, and switched on so that it lights the
        # moment a run reaches it rather than needing a second thing done.
        "lamps": [{"name": "lamp", "on": "globe", "watts": values["watts"],
                   "efficacy_lm_w": values["efficacy_lm_w"], "on_at_first": True}],
    })
    out: dict[str, Any] = {
        workshop_construction.CONSTRUCTION_KEY: {
            "schema": workshop_construction.CONSTRUCTION_SCHEMA, "joints_authored": True,
            "joints": joints, "added": [], "removed": []},
        workshop_machines.MACHINES_KEY: machines}
    for part in parts:
        out[part.name] = {"mechanics": {"model": "rigid"}}
    return out


def _mine_lamp_trials(values: dict[str, Any]) -> list[dict[str, Any]]:
    return []


BREAKER_PARAMETERS = (
    # What it puts into the rock while its trigger is held. The room declares
    # the breaker itself (docs/machine-world.md, "Breaking rock with a machine")
    # and says this there; here it is what the bench shows you before you build.
    w.Parameter("watts", "W", 1500.0, 50.0, 20000.0,
                about="what it puts into the rock while its trigger is held"),
    w.Parameter("capacity_j", "J", 1.5e6, 1000.0, 1e9),
    w.Parameter("charge_j", "J", 1.5e6, 0.0, 1e9),
    w.Parameter("handle_m", "m", 0.55, 0.3, 1.2),
    w.Parameter("chisel_m", "m", 0.30, 0.1, 0.6),
    w.Parameter("material", "", "iron", choices=("iron",)),
)


def _build_breaker(library: w.ComponentLibrary, values: dict[str, Any]) -> list[w.WirePart]:
    """A powered breaker: a handle, a battery on it, and a chisel down the front.

    A pick swung by hand puts twenty-odd joules into rock a blow, and a cell of
    fresh rock costs 469 kJ (rock-work-v1), so a heading driven by arm alone is
    twenty thousand blows. This is the tool that makes a tunnel a thing a person
    can drive: it spends its battery into the rock at a declared rate, and when
    the battery is flat you go and charge it.
    """
    material = str(values["material"])
    handle = float(values["handle_m"])
    chisel = float(values["chisel_m"])
    parts: list[w.WirePart] = []
    # Lying along +z: the handle at the back, the chisel out in front of it.
    parts.append(w.WirePart(name="handle", role="post", size_m=(0.07, 0.07, handle),
                            center_m=(0.0, 0.0, -handle / 2.0), material=material, family="leg"))
    # 40 mm square, not 35: every side of a product has to be a whole number of
    # the room's cells, and 35 is not a multiple of the 10 and 20 mm rooms use.
    parts.append(w.WirePart(name="chisel", role="post", size_m=(0.04, 0.04, chisel),
                            center_m=(0.0, 0.0, chisel / 2.0), material=material, family="leg"))
    parts += library.make("battery", name="battery", material=material,
                          at_m=(0.0, 0.035, -handle * 0.55),
                          parameters={"width_m": 0.14, "height_m": 0.10, "depth_m": 0.20}).parts
    return parts


def _breaker_overrides(values: dict[str, Any], parts: list[w.WirePart]) -> dict[str, Any]:
    from . import workshop_construction, workshop_machines
    joints = [{"id": "joint-1", "kind": "fixed", "a": "handle", "b": "chisel", "method": "bonded"},
              {"id": "joint-2", "kind": "fixed", "a": "handle", "b": "battery", "method": "bonded"}]
    machines = workshop_machines.checked({
        "stores": [{"name": "breaker battery", "in": "battery", "capacity_j": values["capacity_j"],
                    "charge_j": values["charge_j"], "voltage_v": 48.0}],
        "motors": [], "controls": [], "programs": [], "panels": [], "lamps": [],
    })
    out: dict[str, Any] = {
        workshop_construction.CONSTRUCTION_KEY: {
            "schema": workshop_construction.CONSTRUCTION_SCHEMA, "joints_authored": True,
            "joints": joints, "added": [], "removed": []},
        workshop_machines.MACHINES_KEY: machines}
    for part in parts:
        out[part.name] = {"mechanics": {"model": "rigid"}}
    return out


def _breaker_trials(values: dict[str, Any]) -> list[dict[str, Any]]:
    return []


def _build_processor(library: w.ComponentLibrary, values: dict[str, Any]) -> list[w.WirePart]:
    material = str(values["material"])
    side, deck_y, top_t = float(values["deck_m"]), float(values["deck_height_m"]), float(values["top_thickness_m"])
    bin_m = min(float(values["bin_m"]), side * 0.45)
    under = deck_y - top_t
    parts: list[w.WirePart] = []
    parts += library.make("surface", name="deck", material=material, at_m=(0.0, deck_y, 0.0),
                          parameters={"width_m": side, "thickness_m": top_t, "depth_m": side,
                                      "profile": "square"}).parts
    for i, (sx, sz) in enumerate(((1, 1), (-1, 1), (1, -1), (-1, -1)), 1):
        parts.append(w.strut(name=f"leg-{i}", role="leg", from_m=(sx * side * 0.42, 0.0, sz * side * 0.42),
                             to_m=(sx * side * 0.42, under, sz * side * 0.42), section_m=(0.05, 0.05),
                             material=material, family="leg"))
    parts += library.make("bin", name="intake bin", material=material, at_m=(0.0, deck_y, side * 0.26),
                          parameters={"width_m": bin_m, "height_m": 0.15, "depth_m": bin_m}).parts
    parts += library.make("bin", name="output bin", material=material, at_m=(0.0, deck_y, -side * 0.26),
                          parameters={"width_m": bin_m, "height_m": 0.15, "depth_m": bin_m}).parts
    parts += library.make("battery", name="battery", material=material, at_m=(side * 0.3, deck_y, 0.0),
                          parameters={"width_m": 0.25, "height_m": 0.12, "depth_m": 0.25}).parts
    parts += library.make("solar-panel", name="solar panel", material="glass", at_m=(-side * 0.3, deck_y, 0.0),
                          parameters={"width_m": min(0.4, side * 0.3), "depth_m": min(0.6, side * 0.45)}).parts
    return parts


def _processor_overrides(values: dict[str, Any], parts: list[w.WirePart]) -> dict[str, Any]:
    from . import workshop_construction, workshop_machines
    joints = [{"id": f"joint-{i + 1}", "kind": "fixed", "a": "deck", "b": b, "method": "bonded"}
              for i, b in enumerate(["leg-1", "leg-2", "leg-3", "leg-4", "intake bin", "output bin", "battery",
                                     "solar panel"])]
    construction = {"schema": workshop_construction.CONSTRUCTION_SCHEMA, "joints_authored": True,
                    "joints": joints, "added": [], "removed": []}
    recipe = str(values["recipe"])
    if recipe not in PROCESSOR_RECIPES:
        # Said, not silently dropped. The recipe list used to be looked up with
        # a fallback to nothing, so a processor built for a recipe it did not
        # know came out perfectly formed, installed, powered up, and made
        # nothing for ever, with no line anywhere saying why.
        hot = CATALOGUE_RECIPES.get(recipe)
        raise ValueError(
            f"a processor cannot work {recipe!r}: " +
            (f"it needs {hot['needs_c']:.0f} C, and a processor has no chamber to make hot. "
             f"Build an electric furnace for it" if hot else
             f"the recipes it knows are " + ", ".join(sorted(PROCESSOR_RECIPES))))
    machines = workshop_machines.checked({
        "stores": [{"name": "processor battery", "in": "battery", "capacity_j": values["capacity_j"],
                    "charge_j": values["charge_j"], "voltage_v": 48.0}],
        "motors": [], "controls": [],
        "panels": [{"name": "solar panel", "on": "solar panel", "store": "processor battery",
                    "area_m2": round(min(0.4, float(values["deck_m"]) * 0.3) * min(0.6, float(values["deck_m"]) * 0.45), 4),
                    "efficiency": 0.2}],
        "programs": [{"kind": "still", "store": "processor battery",
                      "routine": {"kind": "process", "recipe": recipe, "intake": "intake bin", "output": "output bin",
                                  "batch_kg": values["batch_kg"],
                                  "recipes": [dict(PROCESSOR_RECIPES[recipe])]}}],
    })
    out: dict[str, Any] = {workshop_construction.CONSTRUCTION_KEY: construction,
                           workshop_machines.MACHINES_KEY: machines}
    for part in parts:
        out[part.name] = {"mechanics": {"model": "rigid"}}
    return out


def _processor_trials(values: dict[str, Any]) -> list[dict[str, Any]]:
    return []


def _kettle_capacity_l(values: dict[str, Any]) -> float:
    width = float(values["width_m"]); depth = float(values["depth_m"])
    height = float(values["vessel_height_m"]); wall = float(values["wall_thickness_m"])
    inner_w, inner_d = width - 2 * wall, depth - 2 * wall
    if min(inner_w, inner_d, height) <= 0:
        raise ValueError("kettle walls leave no interior volume")
    return inner_w * inner_d * height * 1000.0


def _kettle_trials(values: dict[str, Any]) -> list[dict[str, Any]]:
    capacity = _kettle_capacity_l(values)
    return [
        {"kind": "container_fill", "substance": "water", "capacity_l": round(capacity, 4)},
        {"kind": "kettle_heat", "substance": "water", "heater": "below",
         "capacity_l": round(capacity, 4)},
    ]


def _build_kettle(library: w.ComponentLibrary, values: dict[str, Any]) -> list[w.WirePart]:
    del library
    width = float(values["width_m"]); depth = float(values["depth_m"])
    height = float(values["vessel_height_m"]); wall = float(values["wall_thickness_m"])
    material = str(values["material"])
    if wall * 2 >= min(width, depth):
        raise ValueError("kettle wall_thickness_m is too large for its width/depth")

    base_y = wall / 2.0; wall_y = wall + height / 2.0
    parts = [
        w.WirePart("kettle-bottom", "container_bottom", (width, wall, depth),
                   (0.0, base_y, 0.0), material=material, family="vessel"),
        w.WirePart("kettle-left", "container_wall", (wall, height, depth),
                   (-width / 2 + wall / 2, wall_y, 0.0), material=material, family="vessel"),
        w.WirePart("kettle-right", "container_wall", (wall, height, depth),
                   (width / 2 - wall / 2, wall_y, 0.0), material=material, family="vessel"),
        w.WirePart("kettle-front", "container_wall", (width - 2 * wall, height, wall),
                   (0.0, wall_y, -depth / 2 + wall / 2), material=material, family="vessel"),
        w.WirePart("kettle-back", "container_wall", (width - 2 * wall, height, wall),
                   (0.0, wall_y, depth / 2 - wall / 2), material=material, family="vessel"),
    ]

    section = max(0.012, wall * 2)
    handle_gap = max(0.035, wall * 3); handle_x = width / 2 + handle_gap
    low_y = wall + height * 0.40; high_y = wall + height * 0.95
    for i, z in enumerate((-depth * 0.30, depth * 0.30), 1):
        parts.append(w.strut(
            name=f"handle-mount-{i}", role="handle",
            from_m=(width / 2, low_y, z), to_m=(handle_x, low_y, z),
            section_m=(section, section), material=material,
            shape="cylinder", family="handle"))
        parts.append(w.strut(
            name=f"handle-arm-{i}", role="handle",
            from_m=(handle_x, low_y, z), to_m=(handle_x, high_y, z),
            section_m=(section, section), material=material,
            shape="cylinder", family="handle"))
    parts.append(w.strut(
        name="handle", role="handle",
        from_m=(handle_x, high_y, -depth * 0.30), to_m=(handle_x, high_y, depth * 0.30),
        section_m=(section, section), material=material, shape="cylinder", family="handle"))
    return parts


FOUNDATION_PARAMETERS = (
    w.Parameter('width_m','m',.4,.4,3.), w.Parameter('depth_m','m',.4,.4,3.),
    w.Parameter('thickness_m','m',.05,.05,.3), w.Parameter('footing_section_m','m',.1,.1,.4),
    w.Parameter('material','','concrete',choices=('concrete','oak','iron','glass')),
    *(w.Parameter(f'footing_{i}_m','m',.05,.05,1.5) for i in range(1,5)),
)


def _build_foundation(library,values):
    width,depth,thickness = values['width_m'],values['depth_m'],values['thickness_m']
    section,material = values['footing_section_m'],values['material']
    if section*2>min(width,depth): raise ValueError('Footings need space within the platform')
    parts=[w.WirePart(name='platform',role='top',family='surface',shape='box',material=material,
        size_m=(width,thickness,depth),center_m=(0,-thickness/2,0))]
    for i,(sx,sz) in enumerate(((1,1),(-1,1),(1,-1),(-1,-1)),1):
        length=values[f'footing_{i}_m']
        parts.append(w.WirePart(name=f'footing-{i}',role='post',family='post',shape='box',material=material,
            size_m=(section,length,section),center_m=(sx*(width-section)/2,-thickness-length/2,
                                                       sz*(depth-section)/2)))
    return parts


def _foundation_overrides(values,parts):
    from . import workshop_construction,workshop_placement
    return {**{p.name:{'mechanics':{'model':'rigid'}} for p in parts},
        workshop_construction.CONSTRUCTION_KEY:{'schema':workshop_construction.CONSTRUCTION_SCHEMA,
            'joints_authored':True,'added':[],'removed':[],
            'joints':[{'id':f'footing-{i}','kind':'fixed','a':'platform','b':f'footing-{i}',
                       'method':'bonded'} for i in range(1,5)]},
        workshop_placement.KEY:{'schema':workshop_placement.SCHEMA,
            'support_components':[f'footing-{i}' for i in range(1,5)],'upright':True,
            'clearance_m':.15,'ports':[],'skills':[]}}


def install() -> None:
    global _INSTALLED
    if _INSTALLED: return
    existing = {assembly.name: assembly for assembly in w.ASSEMBLIES}
    existing['foundation-pad'] = w.Assembly('foundation-pad','support a level building surface',
        'A level platform on four individually sized footings. Free native rigid geometry; '
        'settling must be checked. Rigid connections have no internal or attachment failure model.',
        FOUNDATION_PARAMETERS,_build_foundation,lambda values:[],_foundation_overrides,
        uses={'primary_use':{'label':'Inspect foundation','steps':[{'do':'inspect'}]},
              'primary_use_component':'platform',
              'interaction_point_components':{'deck':'platform','grip':'platform','use':'platform'}})
    old_cart = existing.get("cart")
    if old_cart is not None:
        existing["cart"] = w.Assembly(
            "cart", old_cart.purpose,
            "A real chassis on two rotating axles and four wheels, with bearing mounts and a handle.",
            old_cart.parameters, _build_cart, _cart_trials)

    existing["kettle"] = w.Assembly(
        "kettle", "hold liquid and transfer heat into its contents",
        "An open five-piece metal vessel with a physically attached handle and heat-transfer bottom.",
        (
            w.Parameter("width_m", "m", 0.26, 0.10, 1.0),
            w.Parameter("depth_m", "m", 0.22, 0.10, 1.0),
            w.Parameter("vessel_height_m", "m", 0.18, 0.05, 0.8),
            # 10 mm is fine enough to read as a kettle wall while still fitting
            # the scratch thermomechanical lane at a 10 mm cell. Finer walls are
            # allowed for design, but a test may require a finer cell/budget.
            w.Parameter("wall_thickness_m", "m", 0.010, 0.005, 0.05),
            w.Parameter("material", "", "iron", choices=("iron", "aluminium", "steel")),
        ), _build_kettle, _kettle_trials)

    existing["rover"] = w.Assembly(
        "rover", "roam, dig and carry on its own",
        "A deck on two driven wheels and a caster, with a battery, a solar panel, a hopper and two water eyes: "
        "the room's rover, as exact bodies on pins, with its program and its dig routine.",
        ROVER_PARAMETERS, _build_rover, _rover_trials, _rover_overrides,
        uses={"primary_use":{"label":"Start rover","steps":[{"do":"machine_power","device":"program","power":True}]},
              "primary_use_component": "deck",
              "interaction_point_components": {"deck": "deck", "grip": "deck", "use": "deck"}})

    ordered, seen = [], set()
    for assembly in w.ASSEMBLIES:
        ordered.append(existing[assembly.name]); seen.add(assembly.name)
    if "kettle" not in seen: ordered.append(existing["kettle"])
    existing["drone"] = w.Assembly(
        "drone", "fly, dig and carry on its own",
        "The rover's deck, battery, panel, hopper and water eyes on four rotors instead of wheels: a machine "
        "that flies, as exact bodies on pins, with a hover program and the dig routine.",
        DRONE_PARAMETERS, _build_drone, _drone_trials, _drone_overrides,
        uses={"primary_use":{"label":"Start drone","steps":[{"do":"machine_power","device":"program","power":True}]},
              "primary_use_component": "deck",
              "interaction_point_components": {"deck": "deck", "grip": "deck", "use": "deck"}})
    existing["processor"] = w.Assembly(
        "processor", "make one thing of another, standing still",
        "A machine that goes nowhere: a deck on legs with an intake bin and an output bin, a battery and a "
        "panel, and a still program working the room's recipe from the one bin into the other.",
        PROCESSOR_PARAMETERS, _build_processor, _processor_trials, _processor_overrides,
        uses={"primary_use":{"label":"Start processing","steps":[{"do":"machine_power","device":"program","power":True}]},
              "primary_use_component": "deck",
              "interaction_point_components": {"deck": "deck", "grip": "deck", "use": "intake bin"}})
    if "rover" not in seen: ordered.append(existing["rover"])
    if "drone" not in seen: ordered.append(existing["drone"])
    existing["solar-array"] = w.Assembly(
        "solar-array", "make power for a whole yard",
        "A frame on four legs carrying a row of panels, with one battery under it that every panel charges "
        "and automatically banks collected sunlight above its reserve into its builder's energy wallet. "
        "Nearby machines can draw on the battery: the farm, as exact bodies, so a yard is not eight machines each "
        "carrying its own.",
        SOLAR_ARRAY_PARAMETERS, _build_solar_array, _solar_array_trials, _solar_array_overrides,
        uses={"primary_use":{"label":"Inspect power","steps":[{"do":"inspect"}]},
              "primary_use_component": "frame",
              "interaction_point_components": {"deck": "frame", "grip": "frame", "use": "battery"}})
    existing["electric-furnace"] = w.Assembly(
        "electric-furnace", "make the inside hot enough to smelt",
        "A steel shell around a refractory lining around a chamber of air, with an element on the chamber "
        "floor and a bin at either end. The chamber is a real volume in the thermal network: the element "
        "heats it, the lining decides how much of that stays in, and the recipe waits until the engine says "
        "it is at temperature.",
        ELECTRIC_FURNACE_PARAMETERS, _build_electric_furnace, _electric_furnace_trials,
        _electric_furnace_overrides,
        uses={"primary_use":{"label":"Start furnace","steps":[{"do":"machine_power","device":"program","power":True}]},
              "primary_use_component": "shell-floor",
              "interaction_point_components": {"deck": "shell-roof", "grip": "shell-left",
                                               "use": "intake bin"}})
    existing["mine-lamp"] = w.Assembly(
        "mine-lamp", "light a place that has no daylight in it",
        "A glass globe on an iron bracket, on a foot you stand on the floor. It comes out of the Workshop "
        "dark: a lamp is a fitting, and it lights when a cable is run to it.",
        MINE_LAMP_PARAMETERS, _build_mine_lamp, _mine_lamp_trials, _mine_lamp_overrides,
        uses={"primary_use":{"label":"Switch light on","steps":[{"do":"machine_power","device":"lamp","power":True}]},
              "primary_use_component": "foot",
              "interaction_point_components": {"deck": "foot", "grip": "globe bracket", "use": "globe"}})
    existing["breaker"] = w.Assembly(
        "breaker", "break rock out of a face faster than an arm can",
        "A powered breaker: a handle with a battery on it and a chisel down the front. Held against rock it "
        "spends its battery into the face at its own rate, and a cell of rock comes out when it has been "
        "paid for.",
        BREAKER_PARAMETERS, _build_breaker, _breaker_trials, _breaker_overrides,
        uses={"primary_use_component": "handle",
              "interaction_point_components": {"deck": "handle", "grip": "handle", "use": "chisel"}})
    if "processor" not in seen: ordered.append(existing["processor"])
    if "mine-lamp" not in seen: ordered.append(existing["mine-lamp"])
    if "breaker" not in seen: ordered.append(existing["breaker"])
    if "solar-array" not in seen: ordered.append(existing["solar-array"])
    if "electric-furnace" not in seen: ordered.append(existing["electric-furnace"])
    if 'foundation-pad' not in seen: ordered.append(existing['foundation-pad'])
    w.ASSEMBLIES = tuple(ordered)
    w._BY_NAME = {assembly.name: assembly for assembly in w.ASSEMBLIES}
    _INSTALLED = True
