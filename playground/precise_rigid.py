"""Live precise-rigid scene admission. No lattice resampling or failure verdict.

The initial live lane admits explicit rigid compounds alongside anchored scenery.
Dynamic lattice coupling, thermal mechanics, joints, and fabrication are refused
rather than weakened when a precise rigid body is present.
"""
from __future__ import annotations
from copy import deepcopy
import math
from typing import Any
from mcp import core_use

MODEL = "precise-rigid-v1"
MAX_BODIES = 32
MAX_SHAPES = 256
LIMITS = ("Precise rigid authoring: no internal deformation, fracture, heat, attachments or inventory-funded fabrication. "
          "Currently requires flat-floor anchored scenery; dynamic lattice contact coupling is unavailable.")


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
    if not spec.get("bodies") or any(not b.get("anchored") for b in spec["bodies"]):
        raise ValueError("Precise rigid bodies currently require anchored scenery, not dynamic lattice bodies; use an empty yard")
    for key in ("terrain", "water", "thermo", "joints", "machines", "blades", "tool_points", "interactions"):
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
            raise ValueError("Each precise compound needs 1..64 boxes")
        total += len(parts)
        if total > MAX_SHAPES:
            raise ValueError(f"Precise rigid room exceeds {MAX_SHAPES} collision boxes")
        b["parts"] = []
        for part in parts:
            if not isinstance(part, dict) or set(part) != {"dimensions_m", "center_local_m"}:
                raise ValueError("Precise boxes require exactly dimensions_m and center_local_m")
            d = _vector(part["dimensions_m"], 6, "dimensions_m")
            if min(d) < .001:
                raise ValueError("Precise box dimensions must be 1..6000 mm")
            b["parts"].append({"dimensions_m": d, "center_local_m": _vector(part["center_local_m"], 6, "center_local_m")})
        volumes = [math.prod(p["dimensions_m"]) for p in b["parts"]]
        com = [sum(v*p["center_local_m"][a] for v, p in zip(volumes,b["parts"]))/sum(volumes) for a in range(3)]
        if math.sqrt(sum(v*v for v in com)) > 1e-9:
            raise ValueError("Precise boxes must use their material-derived centre of mass as the local origin")
        neighbors = [set() for _ in parts]
        for i, p in enumerate(b["parts"]):
            for k, other in enumerate(b["parts"][:i]):
                overlap = [(p["dimensions_m"][a]+other["dimensions_m"][a])/2-abs(p["center_local_m"][a]-other["center_local_m"][a]) for a in range(3)]
                if all(v > 1e-10 for v in overlap):
                    raise ValueError("Precise compound boxes overlap; an exact solid union is required")
                if all(v >= -1e-10 for v in overlap) and sum(v > 1e-10 for v in overlap) >= 2:
                    neighbors[i].add(k); neighbors[k].add(i)
        seen, queue = {0}, [0]
        for i in queue:
            for other in neighbors[i]-seen:
                seen.add(other); queue.append(other)
        if len(seen) != len(parts):
            raise ValueError("Precise rigid members must be face connected; separate parts need joints")
        out.append(b)
    return out


def bounds(parts: list[dict[str, Any]], position: list[float], q: list[float]):
    """Conservative world AABB of actual rotated boxes, not a COM-centred hull."""
    w, x, y, z = q
    r = ((1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)),
         (2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)),
         (2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)))
    lo, hi = [math.inf]*3, [-math.inf]*3
    for p in parts:
        for a in range(3):
            center = position[a] + sum(r[a][k]*p["center_local_m"][k] for k in range(3))
            extent = sum(abs(r[a][k])*p["dimensions_m"][k]/2 for k in range(3))
            lo[a] = min(lo[a], center-extent); hi[a] = max(hi[a], center+extent)
    if not all(math.isfinite(v) for v in lo+hi):
        raise ValueError("Invalid precise rigid collision bounds")
    return lo, hi


def placement(artifact: dict[str, Any], root: str, xz: list[float]):
    translation = [xz[0], .002-artifact["bounds_m"][0][1], xz[1]]
    body = {"name": root, "material": artifact["material"],
            "parts": [{"dimensions_m": deepcopy(p["dimensions_m"]), "center_local_m": deepcopy(p["center_local_m"])} for p in artifact["components"]],
            "position_m": [a+b for a,b in zip(artifact["centre_of_mass_m"],translation)],
            "orientation_wxyz": [1,0,0,0], "velocity_m_s": [0,0,0], "spin_rad_s": [0,0,0],
            "color_rgba": 0x9fd3ffff}
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
