"""Functional built-in products layered onto the generic Workshop model.

The core :mod:`mcp.workshop` module owns wire geometry, component families and
assembly mechanics.  This module registers richer products whose behavior is
important enough to deserve explicit component roles and tests, without
teaching the generic Workshop core what a cart or kettle is.

The product graph still decides physics from component semantics:

* cart: chassis + bearing mounts + axles + wheels + handle.  Axles run through
  their wheel hubs so the graph can create real rotational relationships.
* kettle: a five-piece open vessel + handle.  Container and heat-transfer roles
  let the graph describe liquid capacity and thermal behavior from geometry.
"""
from __future__ import annotations

from math import isfinite
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
        # The shaft reaches the wheel HUBS, not merely the deck edges.  That is
        # what makes the geometric interfaces line up for a real bearing/fixing
        # relationship instead of four decorative discs beside a short rod.
        axle = w.strut(
            name=f"axle-{i}", role="axle",
            from_m=(-axle_reach, hub_y, z), to_m=(axle_reach, hub_y, z),
            section_m=(axle_section, axle_section), material="iron",
            shape="cylinder", family="axle")
        parts.append(axle)

        # Two bearing blocks support each axle and are structurally attached to
        # the deck.  Their distinct semantic role lets the product graph preserve
        # axle rotation while still collapsing the stationary chassis.
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


def _kettle_capacity_l(values: dict[str, Any]) -> float:
    width = float(values["width_m"])
    depth = float(values["depth_m"])
    height = float(values["vessel_height_m"])
    wall = float(values["wall_thickness_m"])
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
    del library  # This product is itself a reusable vessel family made of plates.
    width = float(values["width_m"])
    depth = float(values["depth_m"])
    height = float(values["vessel_height_m"])
    wall = float(values["wall_thickness_m"])
    material = str(values["material"])
    if wall * 2 >= min(width, depth):
        raise ValueError("kettle wall_thickness_m is too large for its width/depth")

    base_y = wall / 2.0
    wall_y = wall + height / 2.0
    parts = [
        w.WirePart("kettle-bottom", "container_bottom",
                   (width, wall, depth), (0.0, base_y, 0.0),
                   material=material, family="vessel"),
        w.WirePart("kettle-left", "container_wall",
                   (wall, height, depth), (-width / 2 + wall / 2, wall_y, 0.0),
                   material=material, family="vessel"),
        w.WirePart("kettle-right", "container_wall",
                   (wall, height, depth), (width / 2 - wall / 2, wall_y, 0.0),
                   material=material, family="vessel"),
        w.WirePart("kettle-front", "container_wall",
                   (width - 2 * wall, height, wall),
                   (0.0, wall_y, -depth / 2 + wall / 2),
                   material=material, family="vessel"),
        w.WirePart("kettle-back", "container_wall",
                   (width - 2 * wall, height, wall),
                   (0.0, wall_y, depth / 2 - wall / 2),
                   material=material, family="vessel"),
    ]

    # A U-shaped handle is visible geometry and a real load path, not a painted
    # UI affordance.  It sits behind the open vessel so the contents remain open
    # from the top for filling/testing.
    handle_gap = max(0.035, wall * 3)
    handle_x = width / 2 + handle_gap
    low_y = wall + height * 0.40
    high_y = wall + height * 0.95
    for i, z in enumerate((-depth * 0.30, depth * 0.30), 1):
        parts.append(w.strut(
            name=f"handle-arm-{i}", role="handle",
            from_m=(handle_x, low_y, z), to_m=(handle_x, high_y, z),
            section_m=(max(0.012, wall * 2), max(0.012, wall * 2)),
            material=material, shape="cylinder", family="handle"))
    parts.append(w.strut(
        name="handle", role="handle",
        from_m=(handle_x, high_y, -depth * 0.30),
        to_m=(handle_x, high_y, depth * 0.30),
        section_m=(max(0.012, wall * 2), max(0.012, wall * 2)),
        material=material, shape="cylinder", family="handle"))
    return parts


def install() -> None:
    """Register/replace functional built-ins once for every Workshop caller."""
    global _INSTALLED
    if _INSTALLED:
        return

    existing = {assembly.name: assembly for assembly in w.ASSEMBLIES}
    old_cart = existing.get("cart")
    if old_cart is not None:
        existing["cart"] = w.Assembly(
            "cart", old_cart.purpose,
            "A real chassis on two rotating axles and four wheels, with bearing mounts and a handle.",
            old_cart.parameters, _build_cart, _cart_trials)

    kettle = w.Assembly(
        "kettle", "hold liquid and transfer heat into its contents",
        "An open five-piece metal vessel with a real handle and a heat-transfer bottom.",
        (
            w.Parameter("width_m", "m", 0.26, 0.10, 1.0),
            w.Parameter("depth_m", "m", 0.22, 0.10, 1.0),
            w.Parameter("vessel_height_m", "m", 0.18, 0.05, 0.8),
            w.Parameter("wall_thickness_m", "m", 0.006, 0.003, 0.05),
            w.Parameter("material", "", "iron",
                        choices=("iron", "aluminium", "steel")),
        ),
        _build_kettle, _kettle_trials)
    existing["kettle"] = kettle

    # Preserve the old catalogue order and append genuinely new products.
    ordered = []
    seen = set()
    for assembly in w.ASSEMBLIES:
        ordered.append(existing[assembly.name])
        seen.add(assembly.name)
    for name in ("kettle",):
        if name not in seen:
            ordered.append(existing[name])
    w.ASSEMBLIES = tuple(ordered)
    w._BY_NAME = {assembly.name: assembly for assembly in w.ASSEMBLIES}
    _INSTALLED = True
