"""Strict, bounded compiler for matched object-on-panel drop experiments.

This module only authors initial-state packages through the public Python API.
It adds no material law and makes no thin-plate or fracture-realism claim.
"""
from __future__ import annotations

import math
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "examples" / "authoring"))
from banjo_authoring import catalog, make_object, make_package, validate_network_geometry


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


_VECTOR3 = {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3}
_VECTOR2 = {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2}
DROP_SCHEMA = _object({
            "target_dimensions_m": _VECTOR3,
            "projectile": {"type": "string", "enum": ["iron_ball", "iron_cube"]},
            "projectile_dimensions_m": _VECTOR3,
            "support": {"type": "string", "enum": ["clamped_edges", "free_on_ground"]},
            "impact_offset_m": _VECTOR2,
            "heights_m": {"type": "array", "items": {"type": "number"}, "minItems": 1, "maxItems": 4},
            "representation": {"type": "string", "enum": ["network", "rigid"]},
            "resolution": {"type": "array", "items": {"type": "integer"}, "minItems": 3, "maxItems": 3,
                           "description": "For network targets: 0.49 * min(target_dimensions_m[i]/resolution[i]) >= 0.001 m. A 6 mm plate admits two layers; a 4 mm plate cannot admit two layers."},
        })

_FIELDS = set(DROP_SCHEMA["properties"])
_PANELS = ("glass_panel", "wood_panel", "iron_panel")
_MATERIALS = ("glass", "oak", "iron")


def _number(value: Any, low: float, high: float, label: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{label} must be finite in [{low}, {high}]")
    return float(value)


def _vector(value: Any, length: int, label: str) -> list[Any]:
    if not isinstance(value, list) or len(value) != length:
        raise ValueError(f"{label} requires exactly {length} entries")
    return value


def validate_drop(spec: Any) -> Any:
    """Validate a supplied drop specification and return it unchanged."""
    if not isinstance(spec, dict) or set(spec) != _FIELDS:
        raise ValueError("drop has unknown or missing fields")

    dimensions = _vector(spec["target_dimensions_m"], 3, "target_dimensions_m")
    _number(dimensions[0], .08, 1, "target_dimensions_m[0]")
    _number(dimensions[1], .08, 1, "target_dimensions_m[1]")
    _number(dimensions[2], .004, .15, "target_dimensions_m[2]")

    if spec["projectile"] not in ("iron_ball", "iron_cube"):
        raise ValueError("projectile must be iron_ball or iron_cube")
    projectile_dimensions = _vector(spec["projectile_dimensions_m"], 3, "projectile_dimensions_m")
    for index, value in enumerate(projectile_dimensions):
        _number(value, .012, .3, f"projectile_dimensions_m[{index}]")
    if spec["projectile"] == "iron_ball" and not (
            projectile_dimensions[0] == projectile_dimensions[1] == projectile_dimensions[2]):
        raise ValueError("iron_ball requires three equal projectile dimensions")

    if spec["support"] not in ("clamped_edges", "free_on_ground"):
        raise ValueError("unsupported drop support")
    if spec["representation"] not in ("network", "rigid"):
        raise ValueError("unsupported target representation")
    if spec["support"] == "clamped_edges" and spec["representation"] != "network":
        raise ValueError("clamped_edges requires the network representation")
    if spec["support"] == "free_on_ground" and spec["representation"] != "rigid":
        raise ValueError("free_on_ground currently requires the rigid representation")

    offset = _vector(spec["impact_offset_m"], 2, "impact_offset_m")
    _number(offset[0], -float(dimensions[0]) / 2, float(dimensions[0]) / 2, "impact_offset_m[0]")
    _number(offset[1], -float(dimensions[1]) / 2, float(dimensions[1]) / 2, "impact_offset_m[1]")

    heights = spec["heights_m"]
    if not isinstance(heights, list) or not 1 <= len(heights) <= 4:
        raise ValueError("heights_m requires one to four entries")
    for height in heights:
        _number(height, 0, 2, "heights_m")

    resolution = _vector(spec["resolution"], 3, "resolution")
    if any(type(value) is not int or not 2 <= value <= 12 for value in resolution):
        raise ValueError("resolution entries must be integers in [2, 12]")
    cell_count = 3 * math.prod(resolution)
    if spec["representation"] == "network" and cell_count > 850:
        raise ValueError(f"drop exceeds the 850-cell admission budget ({cell_count} target cells)")
    if spec["representation"] == "network":
        validate_network_geometry(dimensions, resolution)
    return spec


def compile_drop(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Compile a root playground plan's optional ``drop`` field into packages."""
    if not isinstance(plan, dict):
        raise ValueError("playground plan must be an object")
    spec = plan.get("drop")
    if spec is None:
        return []
    validate_drop(spec)
    if plan.get("experiment") != "drop_test":
        raise ValueError("a supplied drop specification requires experiment=drop_test")

    dimensions = spec["target_dimensions_m"]
    projectile_dimensions = spec["projectile_dimensions_m"]
    lane_spacing = max(.45, float(dimensions[0]) + .2)
    target_y = .18 if spec["support"] == "clamped_edges" else float(dimensions[2]) / 2
    materials = [item for item in catalog()["materials"] if item["id"] in _MATERIALS]
    if [item["id"] for item in materials] != list(_MATERIALS):
        raise ValueError("starter catalog must retain matched glass, oak and iron materials")

    packages = []
    for height in spec["heights_m"]:
        objects = []
        for lane, preset in enumerate(_PANELS):
            lane_x = (lane - 1) * lane_spacing
            target = make_object(
                preset, lane * 2 + 1,
                dimensions_m=dimensions,
                resolution=spec["resolution"],
                position_m=[lane_x, target_y, 0.0],
                orientation_wxyz=[math.sqrt(.5), math.sqrt(.5), 0.0, 0.0],
                representation=spec["representation"],
                pin_boundary=spec["support"] == "clamped_edges",
            )
            if spec["representation"] == "rigid":
                for field in ("resolution", "pin_boundary", "grain_wxyz"):
                    target.pop(field, None)
            projectile = make_object(
                spec["projectile"], lane * 2 + 2,
                dimensions_m=projectile_dimensions,
                position_m=[
                    lane_x + float(spec["impact_offset_m"][0]),
                    target_y + float(dimensions[2]) / 2 + float(projectile_dimensions[1]) / 2 + float(height),
                    float(spec["impact_offset_m"][1]),
                ],
                velocity_m_s=[0.0, 0.0, 0.0],
                spin_rad_s=[0.0, 0.0, 0.0],
            )
            objects.extend((target, projectile))
        packages.append(make_package(
            objects,
            materials=materials,
            name=f"{str(plan.get('name', 'Matched drop test'))[:90]} ({float(height):g} m)",
            ground={"half_length_m": 4.0, "half_width_m": 4.0, "friction": .4},
            damage_integration=None if spec["representation"] == "rigid" else {
                "maximum_depth": 2,
                "maximum_damage_increment": .05,
                "maximum_plastic_strain_increment": .002,
                "maximum_brittle_opening_overshoot": .05,
                "on_limit": "reject",
            },
        ))
    return packages
