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
                      "sensors": [{"kind": "water", "on": "deck", "at_m": [sx * 0.55, deck_y - 0.02, depth / 2.0 + 0.5],
                                   "depth_m": ROVER_SENSOR_DEPTH_M} for sx in (1.0, -1.0)],
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
    w.Parameter("recipe", "", "smelt copper", choices=("smelt copper", "draw wire")),
    w.Parameter("material", "", "oak", choices=("oak", "iron")),
)
# The recipes the template knows, per kilogram in, so a processor made on
# the bench brings its chemistry to a room that has none.
PROCESSOR_RECIPES = {
    "smelt copper": {"name": "smelt copper", "in": {"copper ore": 1.0}, "out": {"copper": 0.3},
                     "work_j_per_kg": 2000.0, "s_per_kg": 2.0},
    "draw wire": {"name": "draw wire", "in": {"copper": 1.0}, "out": {"copper wire": 0.98},
                  "work_j_per_kg": 500.0, "s_per_kg": 1.0},
}


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
    w.Parameter("efficiency", "", 0.2, 0.05, 0.35,
                about="what share of the sunlight on a panel becomes power"),
    w.Parameter("material", "", "oak", choices=("oak", "iron")),
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
                              parameters={"width_m": pw, "depth_m": pd}).parts
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
                    "charge_j": values["charge_j"], "voltage_v": 48.0}],
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
                                  "recipes": [dict(PROCESSOR_RECIPES[recipe])] if recipe in PROCESSOR_RECIPES else []}}],
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


def install() -> None:
    global _INSTALLED
    if _INSTALLED: return
    existing = {assembly.name: assembly for assembly in w.ASSEMBLIES}
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
        uses={"primary_use_component": "deck",
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
        uses={"primary_use_component": "deck",
              "interaction_point_components": {"deck": "deck", "grip": "deck", "use": "deck"}})
    existing["processor"] = w.Assembly(
        "processor", "make one thing of another, standing still",
        "A machine that goes nowhere: a deck on legs with an intake bin and an output bin, a battery and a "
        "panel, and a still program working the room's recipe from the one bin into the other.",
        PROCESSOR_PARAMETERS, _build_processor, _processor_trials, _processor_overrides,
        uses={"primary_use_component": "deck",
              "interaction_point_components": {"deck": "deck", "grip": "deck", "use": "intake bin"}})
    if "rover" not in seen: ordered.append(existing["rover"])
    if "drone" not in seen: ordered.append(existing["drone"])
    existing["solar-array"] = w.Assembly(
        "solar-array", "make power for a whole yard",
        "A frame on four legs carrying a row of panels, with one battery under it that every panel charges "
        "and anything nearby can draw on: the farm, as exact bodies, so a yard is not eight machines each "
        "carrying its own.",
        SOLAR_ARRAY_PARAMETERS, _build_solar_array, _solar_array_trials, _solar_array_overrides,
        uses={"primary_use_component": "frame",
              "interaction_point_components": {"deck": "frame", "grip": "frame", "use": "battery"}})
    if "processor" not in seen: ordered.append(existing["processor"])
    if "solar-array" not in seen: ordered.append(existing["solar-array"])
    w.ASSEMBLIES = tuple(ordered)
    w._BY_NAME = {assembly.name: assembly for assembly in w.ASSEMBLIES}
    _INSTALLED = True
