"""Strict, bounded composition of LLM-authored Banjo scene tests."""
from __future__ import annotations

import math
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "examples" / "authoring"))
from banjo_authoring import catalog, make_object, make_package


PRESETS = list(catalog()["object_presets"])


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


VECTOR = {
    "type": "array", "items": {"type": "number"},
    "minItems": 3, "maxItems": 3,
}
NULLABLE_VECTOR = {"anyOf": [VECTOR, {"type": "null"}]}
SCENE_SCHEMA = _object({
    "objects": {
        "type": "array", "minItems": 1, "maxItems": 12,
        "items": _object({
            "preset": {"type": "string", "enum": PRESETS},
            "position_m": VECTOR,
            "velocity_m_s": VECTOR,
            "dimensions_m": NULLABLE_VECTOR,
            "orientation_wxyz": {
                "anyOf": [{"type": "array", "items": {"type": "number"},
                           "minItems": 4, "maxItems": 4}, {"type": "null"}]},
            "spin_rad_s": NULLABLE_VECTOR,
            "representation": {"type": "string", "enum": ["network", "rigid"]},
            "resolution": {
                "anyOf": [{"type": "array", "items": {"type": "integer", "minimum": 2,
                                                         "maximum": 12},
                           "minItems": 3, "maxItems": 3}, {"type": "null"}]},
            "pin_boundary": {"anyOf": [{"type": "boolean"}, {"type": "null"}]},
        }),
    },
    "environment": _object({
        "gravity_m_s2": VECTOR,
        "ground": {"type": "boolean"},
        "ground_friction": {"type": "number", "minimum": 0, "maximum": 1},
    }),
})


def _number(value: Any, low: float, high: float, label: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{label} must be finite in [{low}, {high}]")
    return float(value)


def _vector(value: Any, low: float, high: float, label: str, length: int = 3) -> list[float]:
    if not isinstance(value, list) or len(value) != length:
        raise ValueError(f"{label} requires {length} components")
    return [_number(component, low, high, label) for component in value]


def validate_scene(spec: Any) -> Any:
    """Validate the exact scene-test language without modifying it."""
    if not isinstance(spec, dict) or set(spec) != {"objects", "environment"}:
        raise ValueError("Unknown or missing scene fields")
    objects = spec["objects"]
    if not isinstance(objects, list) or not 1 <= len(objects) <= 12:
        raise ValueError("Scene requires one to twelve objects")
    required = {"preset", "position_m", "velocity_m_s", "dimensions_m",
                "orientation_wxyz", "spin_rad_s", "representation", "resolution",
                "pin_boundary"}
    presets = catalog()["object_presets"]
    total_cells = 0
    for entry in objects:
        if not isinstance(entry, dict) or set(entry) != required:
            raise ValueError("Unknown or missing scene object fields")
        if entry["preset"] not in presets:
            raise ValueError("Unknown object preset")
        _vector(entry["position_m"], -10, 10, "position_m")
        _vector(entry["velocity_m_s"], -30, 30, "velocity_m_s")
        if entry["dimensions_m"] is not None:
            _vector(entry["dimensions_m"], .004, 2, "dimensions_m")
        quaternion = entry["orientation_wxyz"]
        if quaternion is not None:
            quaternion = _vector(quaternion, -1, 1, "orientation_wxyz", 4)
            if abs(math.sqrt(sum(component * component for component in quaternion)) - 1) > 1e-5:
                raise ValueError("orientation_wxyz must be a unit quaternion within 1e-5")
        if entry["spin_rad_s"] is not None:
            _vector(entry["spin_rad_s"], -100, 100, "spin_rad_s")
        # ``preset`` remains readable for plans authored before the schema made
        # the physical representation explicit. New model output cannot emit it.
        if entry["representation"] not in ("network", "rigid", "preset"):
            raise ValueError("representation must be network or rigid")
        resolution = entry["resolution"]
        pin = entry["pin_boundary"]
        if pin is not None and type(pin) is not bool:
            raise ValueError("pin_boundary must be a boolean or null")
        preset = presets[entry["preset"]]
        output_representation = preset["representation"] if entry["representation"] == "preset" else "rigid"
        if entry["representation"] == "network":
            output_representation = "network"
        shape = preset["shape"]
        if output_representation == "rigid" and (resolution is not None or pin is not None):
            raise ValueError("Rigid objects cannot declare resolution or pin_boundary")
        if output_representation == "rigid" and shape == "ellipsoid":
            raise ValueError("Ellipsoid objects require network representation")
        if output_representation == "network" and shape in ("sphere", "wedge"):
            raise ValueError(f"{shape} objects require rigid representation")
        if resolution is not None:
            if (not isinstance(resolution, list) or len(resolution) != 3 or
                    any(type(component) is not int or not 2 <= component <= 12
                        for component in resolution)):
                raise ValueError("resolution requires three integers in [2, 12]")
        if output_representation == "network":
            actual_resolution = resolution if resolution is not None else preset.get("resolution")
            if actual_resolution is None:
                raise ValueError("Network objects require a resolution")
            cells = math.prod(actual_resolution)
            if cells > 800:
                raise ValueError("Network object exceeds the native 800-cell budget")
            total_cells += cells
        if output_representation == "rigid" and shape == "sphere":
            dimensions = entry["dimensions_m"] or preset["dimensions_m"]
            tolerance = 1e-12 * max(1.0, *dimensions)
            if abs(dimensions[0] - dimensions[1]) > tolerance or abs(dimensions[0] - dimensions[2]) > tolerance:
                raise ValueError("Sphere dimensions must specify equal diameters")
    if total_cells > 850:
        raise ValueError("Scene exceeds the playground's 850-network-cell admission budget")
    environment = spec["environment"]
    if not isinstance(environment, dict) or set(environment) != {"gravity_m_s2", "ground", "ground_friction"}:
        raise ValueError("Unknown or missing environment fields")
    _vector(environment["gravity_m_s2"], -20, 20, "gravity_m_s2")
    if type(environment["ground"]) is not bool:
        raise ValueError("ground must be boolean")
    _number(environment["ground_friction"], 0, 1, "ground_friction")
    return spec


def compile_scene(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Compile a validated scene or a containing plan's ``scene`` field."""
    spec = plan.get("scene") if isinstance(plan, dict) and "scene" in plan else plan
    validate_scene(spec)
    objects = []
    for object_id, entry in enumerate(spec["objects"], 1):
        overrides = {"position_m": entry["position_m"], "velocity_m_s": entry["velocity_m_s"]}
        for field in ("dimensions_m", "orientation_wxyz", "spin_rad_s", "resolution", "pin_boundary"):
            if entry[field] is not None:
                overrides[field] = entry[field]
        if entry["representation"] != "preset":
            overrides["representation"] = entry["representation"]
        obj = make_object(entry["preset"], object_id, **overrides)
        if obj["representation"] == "rigid":
            for field in ("resolution", "pin_boundary", "grain_wxyz"):
                obj.pop(field, None)
        objects.append(obj)
    environment = spec["environment"]
    ground = None
    if environment["ground"]:
        ground = {"half_length_m": 4, "half_width_m": 4,
                  "friction": float(environment["ground_friction"])}
    name = plan.get("name", "Composed scene test") if isinstance(plan, dict) else "Composed scene test"
    damage_integration = None
    if any(obj["representation"] == "network" for obj in objects):
        damage_integration = {
            "maximum_depth": 2,
            "maximum_damage_increment": .05,
            "maximum_plastic_strain_increment": .002,
            "maximum_brittle_opening_overshoot": .05,
            "on_limit": "reject",
        }
    return [make_package(objects, name=name[:100], gravity_m_s2=environment["gravity_m_s2"],
                         ground=ground, damage_integration=damage_integration)]
