"""Bounded ground-tool authoring in component frames, never outcome overrides.

The existing native ground-work model owns penetration, resistance and removal.
This declaration only locates the point and the person's grip and selects the
existing swing/lever controls. A native staging probe still admits the point.
"""
from __future__ import annotations
from copy import deepcopy
import math
from . import interaction_profiles

KEY = "ground_tool"
SCHEMA = "banjo.workshop-ground-tool.v1"
_VECTOR = {"type": "array", "minItems": 3, "maxItems": 3, "items": {"type": "number"}}
AUTHORING_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["point", "grip"],
    "properties": {
        "point": {"type": "object", "additionalProperties": False,
            "required": ["component", "tip_local_m", "direction_local", "width_m", "thickness_m", "angle_deg", "length_m"],
            "properties": {"component": {"type": "string"}, "tip_local_m": _VECTOR, "direction_local": _VECTOR,
                "width_m": {"type": "number", "minimum": .002, "maximum": .5},
                "thickness_m": {"type": "number", "minimum": .002, "maximum": .5},
                "angle_deg": {"type": "number", "minimum": 5, "maximum": 170},
                "length_m": {"type": "number", "minimum": .01, "maximum": 1}}},
        "grip": {"type": "object", "additionalProperties": False, "required": ["component", "position_local_m"],
            "properties": {"component": {"type": "string"}, "position_local_m": _VECTOR}}}}


def _name(value, label):
    if not isinstance(value, str) or not value.strip() or len(value) > 120:
        raise ValueError(label + " must name a component")
    return value


def _vector(value, label):
    if (not isinstance(value, (list, tuple)) or len(value) != 3 or
            any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 6 for v in value)):
        raise ValueError(label + " needs three finite component-frame numbers within 6 metres")
    return list(map(float, value))


def checked(value):
    if (not isinstance(value, dict) or set(value) - {"schema", "point", "grip", "use"} or
            value.get("schema", SCHEMA) != SCHEMA):
        raise ValueError("ground_tool needs the bounded point, grip and use declaration")
    point, grip = value.get("point"), value.get("grip")
    fields = {"component", "tip_local_m", "direction_local", "width_m", "thickness_m", "angle_deg", "length_m"}
    if not isinstance(point, dict) or set(point) != fields:
        raise ValueError("ground_tool.point needs " + ", ".join(sorted(fields)))
    if not isinstance(grip, dict) or set(grip) != {"component", "position_local_m"}:
        raise ValueError("ground_tool.grip needs component and position_local_m")
    out = {"schema": SCHEMA, "point": {"component": _name(point["component"], "point.component"),
        "tip_local_m": _vector(point["tip_local_m"], "tip_local_m"),
        "direction_local": _vector(point["direction_local"], "direction_local")},
        "grip": {"component": _name(grip["component"], "grip.component"),
                 "position_local_m": _vector(grip["position_local_m"], "position_local_m")}}
    direction = out["point"]["direction_local"]
    norm = math.sqrt(sum(v*v for v in direction))
    if norm <= 1e-9: raise ValueError("point.direction_local must have a direction")
    out["point"]["direction_local"] = [v/norm for v in direction]
    for key, low, high in (("width_m", .002, .5), ("thickness_m", .002, .5),
                           ("angle_deg", 5, 170), ("length_m", .01, 1)):
        number = point[key]
        if type(number) not in (int, float) or not math.isfinite(number) or not low <= number <= high:
            raise ValueError(f"point.{key} must be {low:g} to {high:g}")
        out["point"][key] = float(number)
    profile = interaction_profiles.check({"object": "ground tool", "template": "swing-and-lever",
        "parts": ["tool"], "tool": "tool", "use": value.get("use", {})}, {"tool"}, [], points={"tool"})
    out["use"] = profile.get("use", {})
    return out


def frame(design):
    value = (design.parameters or {}).get(KEY)
    if value is None: return None
    value = checked(value)
    parts = {p.name: p for p in design.parts}
    point, grip = value["point"], value["grip"]
    if point["component"] not in parts or grip["component"] not in parts:
        raise ValueError("ground_tool point and grip must refer to existing components")
    from . import workshop_construction as construction
    end, handle = parts[point["component"]], parts[grip["component"]]
    def on_part(part, local, label):
        # Native admission additionally checks sampled matter and outward tip.
        if any(abs(v) > .5*s + 1e-9 for v,s in zip(local, part.size_m)):
            raise ValueError(f"ground_tool {label} is outside component {part.name}")
        return construction.to_product(part, tuple(local))
    tip = on_part(end, point["tip_local_m"], "tip")
    at = on_part(handle, grip["position_local_m"], "grip")
    facing = construction._apply(construction.rotation_matrix(end.rotation_deg), tuple(point["direction_local"]))
    return {**value, "tip_m": list(tip), "grip_m": list(at), "pointing": list(facing)}


def installed(design, root, body_names, shift_m):
    value = frame(design)
    if value is None: return None
    point = value["point"]
    return {"point": {"body": root,
        "tip_mm": [1000*(v+s) for v,s in zip(value["tip_m"], shift_m)],
        "grip_mm": [1000*(v+s) for v,s in zip(value["grip_m"], shift_m)],
        "pointing": value["pointing"], "width_mm": 1000*point["width_m"],
        "thickness_mm": 1000*point["thickness_m"], "angle_deg": point["angle_deg"],
        "length_mm": 1000*point["length_m"]},
        "profile": {"object": design.purpose or "Ground tool", "template": "swing-and-lever",
                    "parts": list(body_names), "tool": root, "use": deepcopy(value["use"])}}
