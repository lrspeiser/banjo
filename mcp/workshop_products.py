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
        ROVER_PARAMETERS, _build_rover, _rover_trials, _rover_overrides)

    ordered, seen = [], set()
    for assembly in w.ASSEMBLIES:
        ordered.append(existing[assembly.name]); seen.add(assembly.name)
    if "kettle" not in seen: ordered.append(existing["kettle"])
    if "rover" not in seen: ordered.append(existing["rover"])
    w.ASSEMBLIES = tuple(ordered)
    w._BY_NAME = {assembly.name: assembly for assembly in w.ASSEMBLIES}
    _INSTALLED = True
