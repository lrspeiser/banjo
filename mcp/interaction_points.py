"""Authored affordances; coordinates are metres, never collision or power overrides."""
from __future__ import annotations
from copy import deepcopy
import math

KINDS = ("grip", "use", "surface", "container")
POINT_SCHEMA = {"type": "object", "additionalProperties": False,
    "required": ["id", "kind", "position_m"], "properties": {
        "id": {"type": "string", "maxLength": 60}, "label": {"type": "string", "maxLength": 80},
        "kind": {"type": "string", "enum": list(KINDS)},
        "position_m": {"type": "array", "minItems": 3, "maxItems": 3, "items": {"type": "number"}},
        "size_m": {"type": "array", "minItems": 3, "maxItems": 3, "items": {"type": "number"}},
        "yaw_deg": {"type": "number"}, "max_mass_kg": {"type": "number"}}}
LIST_SCHEMA = {"type": "array", "maxItems": 32, "items": POINT_SCHEMA}


def vector(value, label, positive=False, limit=100):
    if (not isinstance(value, (list, tuple)) or len(value) != 3 or
        any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > limit or
            (positive and v <= 0) for v in value)):
        raise ValueError(label + " needs three finite metre values" + (" greater than zero" if positive else ""))
    return list(map(float, value))


def checked(points):
    if not isinstance(points, list) or len(points) > 32:
        raise ValueError("interaction_points needs a list of at most 32 points")
    out, seen = [], set()
    for raw in points:
        if not isinstance(raw, dict) or set(raw) - set(POINT_SCHEMA["properties"]):
            raise ValueError("unknown interaction point fields")
        key = raw.get("id")
        if not isinstance(key, str) or not key.strip() or len(key) > 60 or key in seen or key == "ground":
            raise ValueError("interaction point ids must be unique, 1 to 60 characters; ground is reserved")
        seen.add(key)
        kind = raw.get("kind")
        if kind not in KINDS:
            raise ValueError("interaction point kind must be grip, use, surface or container")
        label = raw.get("label", key)
        if not isinstance(label, str) or not label.strip() or len(label) > 80:
            raise ValueError("interaction point label needs 1 to 80 characters")
        point = {"id": key, "kind": kind, "label": label, "position_m": vector(raw.get("position_m"), "position_m")}
        if kind in ("surface", "container"):
            point["size_m"] = vector(raw.get("size_m"), "size_m", True)
        elif any(k in raw for k in ("size_m", "max_mass_kg")):
            raise ValueError("only receiving points have size_m or max_mass_kg")
        for k, default, lo, hi in (("yaw_deg", 0, -360, 360), ("max_mass_kg", None, 0.001, 1e6)):
            value = raw.get(k, default)
            if value is None:
                continue
            if type(value) not in (int, float) or not math.isfinite(value) or not lo <= value <= hi:
                raise ValueError(k + " is outside its finite bounds")
            point[k] = float(value)
        out.append(point)
    # Passive and legacy objects still expose the common interaction contract.
    for kind in ("grip", "use"):
        if not any(p["kind"] == kind for p in out):
            key = kind
            while key in seen: key = "_" + key
            seen.add(key)
            out.append({"id": key, "kind": kind, "label": kind.title(),
                        "position_m": [0.0, 0.0, 0.0], "yaw_deg": 0.0})
    if len(out) > 32:
        raise ValueError("leave room for the required grip and use points (32 total)")
    return out


def normalise(records, bodies):
    if not isinstance(records, list):
        raise ValueError("interaction_points must be a list of {body, points}")
    names = {b["name"] for b in bodies}
    kept = {}
    for record in records:
        if not isinstance(record, dict) or set(record) != {"body", "points"}:
            raise ValueError("interaction_points records need body and points")
        name = record["body"]
        if not isinstance(name, str) or name not in names or name in kept:
            raise ValueError("interaction_points body is missing or duplicated")
        kept[name] = checked(record["points"])
    return [{"body": b["name"], "points": kept.get(b["name"], checked([]))} for b in bodies]


def for_design(design):
    if "interaction_points" in design.parameters:
        return checked(design.parameters["interaction_points"])
    points = []
    # Template surfaces are actual geometry. Never infer a cavity from a name.
    for part in design.parts:
        if part.name in ("deck", "top", "seat") and all(abs(v) < 1e-6 for v in part.rotation_deg):
            x, y, z = part.center_m
            w, h, d = part.size_m
            points.append({"id": part.name, "label": "Cargo deck" if part.name == "deck" else part.name.title(),
                           "kind": "surface", "position_m": [x, y+h/2, z],
                           "size_m": [w, 2.0, d]})
    # Put the template's common anchors on its handle when present, otherwise
    # at its material-weighted centre, not at the design's ground origin.
    handle = next((p for p in design.parts if p.name == "handle"), None)
    total = sum(p.mass_kg() for p in design.parts)
    centre = (list(handle.center_m) if handle else
              [sum(p.center_m[a]*p.mass_kg() for p in design.parts)/total for a in range(3)]
              if total else [0,0,0])
    for kind in ("grip", "use"):
        points.append({"id": kind, "kind": kind, "label": kind.title(), "position_m": centre})
    return checked(points)


def installed(design, root, com):
    points = deepcopy(for_design(design))
    for p in points:
        p["position_m"] = [p["position_m"][a] - com[a] for a in range(3)]
    return {"body": root, "points": points}
