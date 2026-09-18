"""Continuous-size, non-deformable Workshop compounds, not voxel encodings.

The supported geometry is a homogeneous, face-connected union of non-overlapping
axis-aligned boxes. Overlaps, curved members, rotated subparts and articulated
interfaces fail closed. Exact boxes stay exact boxes in the native rigid-v1
backend. Neither internal fracture nor attachment failure is implemented here.
"""
from __future__ import annotations

import hashlib
import json
from math import isfinite, prod
from typing import Any

from . import engine_materials, workshop_visual

SCHEMA = "banjo.workshop-rigid.v1"
MAX_BOXES = 64
MIN_DIMENSION_M = .001
MAX_DIMENSION_M = 6.0
_FIXED_ROLES = {"leg", "post", "beam", "brace", "apron", "stretcher", "top", "panel", "surface"}
LIMITATIONS = [
    "Explicit rigid model: no bending, yielding, crushing, internal fracture or attachment failure.",
    "Face contacts inside the compound are ideal fixed connections, not strength-validated joints.",
    "Only face-connected non-overlapping axis-aligned boxes in one material are supported.",
    "Available in the isolated bench and bounded live authoring with anchored scenery; dynamic lattice coupling, heat, joints and fabrication are unsupported.",
]


def checked_mechanics(value: Any) -> dict[str, str]:
    if value is None or value == {}:
        return {"model": "lattice"}
    if not isinstance(value, dict) or set(value) != {"model"}:
        raise ValueError("mechanics must contain exactly model (lattice or rigid)")
    if value["model"] not in ("lattice", "rigid"):
        raise ValueError("mechanics.model must be lattice or rigid; beam/sheet/cable solvers are not implemented")
    return {"model": value["model"]}


def requested_models(design, overrides=None) -> set[str]:
    if overrides is None:
        overrides = (design.lineage or {}).get("component_overrides") or {}
    return {checked_mechanics((overrides.get(p.name) or {}).get("mechanics"))["model"] for p in design.parts}


def require_lattice(design, operation: str) -> None:
    if requested_models(design) != {"lattice"}:
        raise ValueError(f"{operation} does not support the declared rigid/mixed mechanical model. "
                         "Use the precise rigid-motion bench, or explicitly change the model to lattice. "
                         "No automatic conversion or fracture result is permitted.")


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def compile_rigid(design, overrides=None, *, require_request=True) -> dict[str, Any]:
    design.validate()
    overrides = overrides if overrides is not None else (design.lineage or {}).get("component_overrides") or {}
    if require_request and requested_models(design, overrides) != {"rigid"}:
        raise ValueError("Choose precise rigid for the whole candidate before compiling it; mixed mechanics are not coupled yet")
    if not 1 <= len(design.parts) <= MAX_BOXES:
        raise ValueError(f"Precise rigid compilation supports 1..{MAX_BOXES} boxes")
    materials = {engine_materials.canonical(p.material) for p in design.parts}
    if len(materials) != 1:
        raise ValueError("Precise rigid compounds currently require one material; mixed-material interfaces are unsupported")
    material = next(iter(materials))
    if material not in {"oak", "glass", "iron", "concrete"}:
        raise ValueError("The rigid-v1 adapter does not support material " + material)
    density = engine_materials.density(material)
    skins = workshop_visual.skin_overrides(overrides)
    parts = []
    for p in design.parts:
        if p.role not in _FIXED_ROLES:
            raise ValueError(f"{p.name}: {p.role} is not a supported fixed structural role; do not weld a mechanism")
        skin = skins.get(p.name, {})
        box = (skin.get("profile") in {"block", "design"} and p.shape == "box") if skin.get("physical") else p.shape == "box"
        if skin.get("physical") and skin.get("profile") == "block":
            box = True  # An explicit physical block override defines a box.
        if not box or any(float(v) != 0 for v in p.rotation_deg):
            raise ValueError(f"{p.name}: precise rigid currently requires axis-aligned boxes; no bounding-box substitution")
        d, c = list(p.size_m), list(p.center_m)
        if any(not isfinite(v) or not MIN_DIMENSION_M <= v <= MAX_DIMENSION_M for v in d):
            raise ValueError(f"{p.name}: rigid dimensions must be 1..6000 mm")
        volume = prod(d)
        parts.append({"component":p.name, "dimensions_m":d, "center_m":c,
                      "volume_m3":volume, "mass_kg":density*volume})
    neighbors = [set() for _ in parts]
    for i, a in enumerate(parts):
        for j, b in enumerate(parts[:i]):
            overlap = [(a["dimensions_m"][k]+b["dimensions_m"][k])/2-abs(a["center_m"][k]-b["center_m"][k]) for k in range(3)]
            if all(v > 1e-10 for v in overlap):
                raise ValueError(f"{a['component']} overlaps {b['component']}; an exact solid union is required to avoid counting mass twice")
            if all(v >= -1e-10 for v in overlap) and sum(v > 1e-10 for v in overlap) >= 2:
                neighbors[i].add(j); neighbors[j].add(i)
    seen, queue = {0}, [0]
    for i in queue:
        for j in neighbors[i]-seen:
            seen.add(j); queue.append(j)
    if len(seen) != len(parts):
        raise ValueError("Precise rigid members must share faces; gaps and point/edge contacts need explicit physical joints")
    mass = sum(p["mass_kg"] for p in parts)
    com = [sum(p["center_m"][a]*p["mass_kg"] for p in parts)/mass for a in range(3)]
    inertia = [[0.0]*3 for _ in range(3)]
    for p in parts:
        c = [p["center_m"][a]-com[a] for a in range(3)]
        p["center_local_m"] = c
        if any(abs(v)>6 for v in c):
            raise ValueError("Precise compound local offsets exceed the 6 m bound")
        d, m = p["dimensions_m"], p["mass_kg"]
        for a in range(3):
            for b in range(3):
                inertia[a][b] += m*((sum(v*v for v in c) if a==b else 0)-c[a]*c[b])
            inertia[a][a] += m*sum(d[b]**2 for b in range(3) if b != a)/12
    lo = [min(p["center_m"][a]-p["dimensions_m"][a]/2 for p in parts) for a in range(3)]
    hi = [max(p["center_m"][a]+p["dimensions_m"][a]/2 for p in parts) for a in range(3)]
    if max(hi[a]-lo[a] for a in (0,2)) > 16:
        raise ValueError("Rigid test fixture supports a footprint up to 16 m")
    physical = {"model":"precise-rigid-box-compound-v1", "material":material,
                "density_kg_m3":density, "parts":[{"dimensions_m":p["dimensions_m"],"center_m":p["center_m"]} for p in parts]}
    return {"schema":SCHEMA, "design_id":design.design_id, "mechanical_model":"rigid", "material":material,
            "density_kg_m3":density, "components":parts, "mass_kg":mass, "centre_of_mass_m":com,
            "inertia_kg_m2":inertia, "bounds_m":[lo,hi], "physics_hash":_hash(physical),
            "source_geometry_preserved":True, "stored_cells":0, "collision_boxes":len(parts),
            "active_deformation_cells":0, "internal_fracture_supported":False,
            "attachment_failure_supported":False, "strength_certified":False,
            "live_installation_supported":True, "live_installation_scope":"anchored-scenery authoring only; native preview required", "limitations":list(LIMITATIONS)}


def package(artifact: dict[str, Any], *, drop_height_m: float = .2,
            horizontal_speed_m_s: float = 0.0, gravity_m_s2: float = -9.81) -> dict[str, Any]:
    height = workshop_visual._number(drop_height_m, "drop_height_m", 0, 2)
    speed = workshop_visual._number(horizontal_speed_m_s, "horizontal_speed_m_s", -2, 2)
    gravity = workshop_visual._number(gravity_m_s2, "gravity_m_s2", -20, 0)
    com = artifact["centre_of_mass_m"]
    return {"package_version":1, "physics_abi":"banjo-platform-1", "name":"Workshop precise rigid motion",
            "units":"SI", "backend":"rigid-v1", "required_capabilities":["precise-rigid-compound","gravity","finite-ground"],
            "fixed_dt_s":1/240, "max_steps_per_call":240, "gravity_m_s2":[0,gravity,0], "bowl":None,
            "ground":{"half_length_m":10, "half_width_m":10, "thickness_m":.2,"surface":"concrete"},
            "objects":[{"id":1, "shape":"compound", "material":artifact["material"],
                        "parts":[{"dimensions_m":p["dimensions_m"], "center_local_m":p["center_local_m"]} for p in artifact["components"]],
                        "position_m":[0, com[1]-artifact["bounds_m"][0][1]+height, 0],
                        "orientation_wxyz":[1,0,0,0], "velocity_m_s":[speed,0,0], "spin_rad_s":[0,0,0]}]}
