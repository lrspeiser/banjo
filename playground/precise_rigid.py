"""Live precise-rigid scene admission. No lattice resampling or failure verdict.

Exact rigid compounds -- boxes and cylinders, each turned as drawn and of its own
material if need be -- share a room with everything made of cells, with its
terrain and water, and with joints: a cart is three of them turning on pins.
What they cannot do yet is break inside, take heat, carry blades or tool points,
or drive a machine; those are refused rather than weakened. The engine is the
authority on their geometry: it counts overlapping parts once, re-centres each
body on its material's centre of mass, and asks Jolt's own shapes whether every
part meets another (src/fastlattice/PreciseRigidScene.cpp).
"""
from __future__ import annotations
from copy import deepcopy
import math
from typing import Any
from mcp import core_use

MODEL = "precise-rigid-v1"
MAX_BODIES = 32
MAX_SHAPES = 256
LIMITS = ("Precise rigid bodies: no internal deformation, fracture, heat, blades, tool points or inventory-funded fabrication. "
          "A breakable body they strike is judged against their material, and a break that would need them inside "
          "the lattice run is declined and reported rather than run.")
SHAPES = ("box", "cylinder")
MATERIALS = ("glass", "oak", "iron", "concrete")


def _vector(value: Any, limit: float, label: str) -> list[float]:
    if (not isinstance(value, list) or len(value) != 3 or
            any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > limit for v in value)):
        raise ValueError(f"{label} must contain three finite SI numbers within {limit:g}")
    return [float(v) for v in value]


def normalise(value: Any, spec: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > MAX_BODIES:
        raise ValueError(f"precise_rigid_bodies must be a list of at most {MAX_BODIES} bodies")
    if not value:
        return []
    if not spec.get("bodies"):
        raise ValueError("Precise rigid bodies need a room with at least one lattice body in it; use a yard")
    for key in ("thermo", "machines", "blades", "tool_points", "interactions"):
        if spec.get(key):
            raise ValueError(f"Precise rigid rooms do not yet support {key}; nothing was installed")
    # Saved core gestures use the existing rigid hand/contact path. Rich
    # machine/heat/action DSL remains unavailable in this deliberately narrow lane.
    actions = spec.get("actions", [])
    if not isinstance(actions, list):
        raise ValueError("Precise rigid actions must be a list")
    for action in actions:
        if not isinstance(action, dict):
            raise ValueError("Precise rigid actions need a saved core program")
        core_use.checked_program({k: action[k] for k in ("label", "steps") if k in action})
    if any(any(b.get(k) is not None for k in ("contents", "temperature_k", "layer_depth_m", "environment")) for b in spec["bodies"]):
        raise ValueError("Precise rigid rooms do not yet support thermal scenery declarations")
    names = {n for b in spec["bodies"] for n in (b.get("name"), b.get("join")) if n}
    out, total = [], 0
    allowed = {"name", "material", "parts", "position_m", "orientation_wxyz", "velocity_m_s", "spin_rad_s", "color_rgba"}
    for raw in value:
        if not isinstance(raw, dict) or set(raw) - allowed:
            raise ValueError("Unknown precise rigid body fields")
        name = raw.get("name")
        if (not isinstance(name, str) or not name or len(name.encode()) > 120 or name in names or
                any(ord(c) < 32 or ord(c) == 127 for c in name)):
            raise ValueError("Precise rigid body names must be unique, nonempty, at most 120 bytes, and contain no control characters")
        names.add(name)
        if raw.get("material") not in {"glass", "oak", "iron", "concrete"}:
            raise ValueError("Unsupported precise rigid material")
        b = {"name": name, "material": raw["material"],
             "position_m": _vector(raw.get("position_m"), 190, "position_m"),
             "velocity_m_s": _vector(raw.get("velocity_m_s", [0, 0, 0]), 20, "velocity_m_s"),
             "spin_rad_s": _vector(raw.get("spin_rad_s", [0, 0, 0]), 20, "spin_rad_s")}
        q = raw.get("orientation_wxyz", [1, 0, 0, 0])
        if (not isinstance(q, list) or len(q) != 4 or
                any(type(v) not in (float, int) or not math.isfinite(v) or abs(v) > 1 for v in q) or
                abs(sum(v*v for v in q)-1) > 1e-9):
            raise ValueError("Precise rigid orientation must be a normalized w,x,y,z quaternion")
        b["orientation_wxyz"] = list(q)
        color = raw.get("color_rgba", 0x9fd3ffff)
        if type(color) is not int or not 0 <= color <= 0xffffffff:
            raise ValueError("Precise rigid color must be an integer RGBA value")
        b["color_rgba"] = color
        parts = raw.get("parts")
        if not isinstance(parts, list) or not 1 <= len(parts) <= 64:
            raise ValueError("Each precise compound needs 1..64 parts")
        total += len(parts)
        if total > MAX_SHAPES:
            raise ValueError(f"Precise rigid room exceeds {MAX_SHAPES} collision parts")
        b["parts"] = [_part(part) for part in parts]
        # Overlaps, the centre of mass and whether every part meets another are
        # the engine's to settle: it counts a shared space once, as the part
        # listed first, re-centres the body on its material, and asks Jolt's own
        # shapes -- a turned cylinder is not a box this module could test.
        out.append(b)
    return out


def _part(part: Any) -> dict[str, Any]:
    allowed = {"shape", "dimensions_m", "center_local_m", "rotation_wxyz", "material", "name"}
    if not isinstance(part, dict) or set(part) - allowed or not {"dimensions_m", "center_local_m"} <= set(part):
        raise ValueError("Precise parts need dimensions_m and center_local_m, and may give shape, rotation_wxyz, material and name")
    shape = part.get("shape", "box")
    if shape not in SHAPES:
        raise ValueError("Precise part shape must be box or cylinder")
    d = _vector(part["dimensions_m"], 6, "dimensions_m")
    if min(d) < .001:
        raise ValueError("Precise part dimensions must be 1..6000 mm")
    if shape == "cylinder" and abs(d[0]-d[2]) > 1e-9*max(1.0, d[0]):
        raise ValueError("A precise cylinder is sized [diameter, length, diameter] about its own y axis")
    out = {"dimensions_m": d, "center_local_m": _vector(part["center_local_m"], 6, "center_local_m")}
    if shape != "box":
        out["shape"] = shape
    if "rotation_wxyz" in part:
        q = part["rotation_wxyz"]
        if (not isinstance(q, list) or len(q) != 4 or
                any(type(v) not in (float, int) or not math.isfinite(v) or abs(v) > 1 for v in q) or
                abs(sum(v*v for v in q)-1) > 1e-9):
            raise ValueError("A precise part's rotation must be a normalized w,x,y,z quaternion")
        out["rotation_wxyz"] = [float(v) for v in q]
    if "material" in part:
        if part["material"] not in MATERIALS:
            raise ValueError("Unsupported precise rigid material")
        out["material"] = part["material"]
    if "name" in part:
        name = part["name"]
        if (not isinstance(name, str) or not name or len(name.encode()) > 80 or
                any(ord(c) < 32 or ord(c) == 127 for c in name)):
            raise ValueError("Precise part names are 1..80 bytes with no control characters")
        out["name"] = name
    return out


def _turn(q: list[float]):
    w, x, y, z = q
    return ((1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)),
            (2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)),
            (2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)))


def bounds(parts: list[dict[str, Any]], position: list[float], q: list[float]):
    """World AABB of the actual turned parts, not a COM-centred hull: a box's
    corners, and a cylinder's two end discs, each part turned by its own
    rotation and then the body's."""
    body = _turn(q)
    lo, hi = [math.inf]*3, [-math.inf]*3
    for p in parts:
        own = _turn(p.get("rotation_wxyz", [1, 0, 0, 0]))
        r = [[sum(body[a][k]*own[k][c] for k in range(3)) for c in range(3)] for a in range(3)]
        d = p["dimensions_m"]
        for a in range(3):
            center = position[a] + sum(body[a][k]*p["center_local_m"][k] for k in range(3))
            if p.get("shape") == "cylinder":
                along = min(1.0, abs(r[a][1]))
                extent = d[1]/2*along + d[0]/2*math.sqrt(max(0.0, 1-along*along))
            else:
                extent = sum(abs(r[a][k])*d[k]/2 for k in range(3))
            lo[a] = min(lo[a], center-extent); hi[a] = max(hi[a], center+extent)
    if not all(math.isfinite(v) for v in lo+hi):
        raise ValueError("Invalid precise rigid collision bounds")
    return lo, hi


def colour(material: str) -> int:
    """An exact body's colour, as the engine takes it: its material's, the one
    fracture_lab gives a lattice body of that material. The glass blue every
    exact body used to carry drew an oak product as glass wherever a page
    colours by the body rather than by what it is made of (the Explorer)."""
    import fracture_lab
    return int(fracture_lab.MATERIAL_COLORS.get(material, "9fd3ffff"), 16)


def placement(artifact: dict[str, Any], root: str, xz: list[float]):
    translation = [xz[0], .002-artifact["bounds_m"][0][1], xz[1]]
    body = {"name": root, "material": artifact["material"],
            "parts": [{"dimensions_m": deepcopy(p["dimensions_m"]), "center_local_m": deepcopy(p["center_local_m"])} for p in artifact["components"]],
            "position_m": [a+b for a,b in zip(artifact["centre_of_mass_m"],translation)],
            "orientation_wxyz": [1,0,0,0], "velocity_m_s": [0,0,0], "spin_rad_s": [0,0,0],
            "color_rgba": colour(artifact["material"])}
    return body, translation


def verify(snapshot: dict[str, Any], artifact: dict[str, Any], root: str) -> None:
    matches = [b for b in snapshot.get("bodies", []) if b.get("name") == root]
    if len(matches) != 1:
        raise ValueError("Native precise rigid body is missing or duplicated")
    body = matches[0]
    if (body.get("mechanical_model") != MODEL or body.get("shape") != "compound" or
            body.get("nodes_b64") != "" or body.get("offsets_b64") != "" or
            body.get("precise_rigid_definition") != artifact["live_definition"]):
        raise ValueError("Native precise rigid geometry differs from the selected source")
    mass = body.get("precise_mass_kg")
    if (type(mass) not in (float, int) or not math.isfinite(mass) or
            not math.isclose(mass, artifact["mass_kg"], rel_tol=5e-6, abs_tol=1e-10)):
        raise ValueError("Native precise rigid mass differs from density times actual volume")
    expected = artifact["live_definition"]
    if (not all(math.isclose(float(v), float(w), abs_tol=1e-9, rel_tol=0) for v,w in zip(body["pose"]["com_m"], expected["position_m"])) or
            body["pose"]["q_wxyz"] != expected["orientation_wxyz"] or
            body["pose"]["v_m_s"] != [0,0,0] or body["pose"]["w_rad_s"] != [0,0,0]):
        raise ValueError("Native precise rigid initial placement or motion changed")
