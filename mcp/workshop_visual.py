"""Workshop visual representations: editable skins and sparse physical-cell previews.

Wire geometry remains authoritative for design intent.  A skin is a separate,
editable render description.  When a skin edit is marked ``physical`` the same
deterministic parametric solid is sampled onto Banjo's cell grid for the Matter
preview; appearance-only edits never change matter.

This module deliberately does not run physics.  Engine trials remain in
``playground/workshop_bench.py``/``workshop_trials.py``.  The output here is the
bridge that lets the browser show what will be handed to a detailed material
solver once sparse compiled bodies are accepted by the live scene ABI.
"""
from __future__ import annotations

from math import floor, isfinite, sqrt
from typing import Any, Iterable

from mcp.workshop import WorkshopDesign, WirePart, _rotate

SKIN_SCHEMA = "banjo.product-skin.v1"
MATTER_SCHEMA = "banjo.workshop-matter.v1"
MAX_PREVIEW_CELLS = 50000


def _number(value: Any, name: str, low: float, high: float) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number") from None
    if not isfinite(out) or not low <= out <= high:
        raise ValueError(f"{name} must be between {low:g} and {high:g}")
    return out


def checked_skin(value: Any) -> dict[str, Any]:
    if value in (None, {}):
        return {}
    if not isinstance(value, dict):
        raise ValueError("skin must be an object")
    allowed = {"profile", "bend_m", "physical", "roughness", "metalness", "color"}
    unknown = set(value) - allowed
    if unknown:
        raise ValueError("unknown skin field(s): " + ", ".join(sorted(unknown)))
    profile = str(value.get("profile") or "design")
    if profile not in {"design", "block", "round", "curve"}:
        raise ValueError("skin profile must be design, block, round or curve")
    out: dict[str, Any] = {"profile": profile, "physical": bool(value.get("physical", False))}
    out["bend_m"] = _number(value.get("bend_m", 0.0), "skin.bend_m", -5.0, 5.0)
    out["roughness"] = _number(value.get("roughness", 0.72), "skin.roughness", 0.0, 1.0)
    out["metalness"] = _number(value.get("metalness", 0.0), "skin.metalness", 0.0, 1.0)
    if value.get("color") is not None:
        color = str(value["color"]).strip()
        if len(color) > 32:
            raise ValueError("skin.color is too long")
        out["color"] = color
    return out


def skin_overrides(component_overrides: Any) -> dict[str, dict[str, Any]]:
    if component_overrides in (None, {}):
        return {}
    if not isinstance(component_overrides, dict):
        raise ValueError("component_overrides must be an object")
    return {str(name): checked_skin(patch.get("skin"))
            for name, patch in component_overrides.items()
            if isinstance(patch, dict) and patch.get("skin") is not None}


def _effective_profile(part: WirePart, skin: dict[str, Any]) -> str:
    profile = str(skin.get("profile") or "design")
    if profile != "design":
        return profile
    return "round" if part.shape == "cylinder" else "block"


def _skin_part(part: WirePart, skin: dict[str, Any]) -> dict[str, Any]:
    profile = _effective_profile(part, skin)
    w, h, d = (float(v) for v in part.size_m)
    descriptor: dict[str, Any] = {
        "component": part.name,
        "profile": profile,
        "physical": bool(skin.get("physical", False)),
        "center_m": [float(v) for v in part.center_m],
        "rotation_deg": [float(v) for v in part.rotation_deg],
        "size_m": [w, h, d],
        "material": part.material,
        "roughness": float(skin.get("roughness", 0.72)),
        "metalness": float(skin.get("metalness", 0.0)),
    }
    if skin.get("color"):
        descriptor["color"] = str(skin["color"])
    if profile == "curve":
        bend = float(skin.get("bend_m", 0.0))
        descriptor.update({
            "kind": "bezier_tube",
            "radius_m": max(0.0015, min(w, d) / 2.0),
            "control_points_local_m": [
                [0.0, -h / 2.0, 0.0],
                [bend, -h / 6.0, 0.0],
                [bend, h / 6.0, 0.0],
                [0.0, h / 2.0, 0.0],
            ],
        })
    elif profile == "round":
        descriptor.update({"kind": "cylinder", "radius_m": max(0.0015, min(w, d) / 2.0)})
    else:
        descriptor["kind"] = "box"
    return descriptor


def skin_document(design: WorkshopDesign, component_overrides: Any = None) -> dict[str, Any]:
    overrides = skin_overrides(component_overrides)
    return {
        "schema": SKIN_SCHEMA,
        "design_id": design.design_id,
        "components": [_skin_part(part, overrides.get(part.name, {})) for part in design.parts],
        "rules": {
            "appearance_only_has_no_physics": True,
            "physical_skin_recompiles_matter": True,
        },
    }


def _bezier(points: list[list[float]], t: float) -> tuple[float, float, float]:
    u = 1.0 - t
    weights = (u*u*u, 3*u*u*t, 3*u*t*t, t*t*t)
    return tuple(sum(weights[i] * float(points[i][axis]) for i in range(4))
                 for axis in range(3))  # type: ignore[return-value]


def _segment_distance_sq(point: tuple[float, float, float], a, b) -> float:
    ab = tuple(float(b[i]) - float(a[i]) for i in range(3))
    ap = tuple(float(point[i]) - float(a[i]) for i in range(3))
    den = sum(v*v for v in ab)
    t = 0.0 if den <= 1e-18 else max(0.0, min(1.0, sum(ap[i]*ab[i] for i in range(3)) / den))
    closest = tuple(float(a[i]) + t * ab[i] for i in range(3))
    return sum((float(point[i]) - closest[i]) ** 2 for i in range(3))


def _curve_samples(descriptor: dict[str, Any], count: int = 32):
    points = descriptor["control_points_local_m"]
    return [_bezier(points, i / count) for i in range(count + 1)]


def _inside(part: WirePart, skin: dict[str, Any], x: float, y: float, z: float) -> bool:
    w, h, d = (float(v) for v in part.size_m)
    profile = _effective_profile(part, skin) if skin.get("physical") else (
        "round" if part.shape == "cylinder" else "block")
    if profile == "round":
        rx, rz = max(w / 2, 1e-9), max(d / 2, 1e-9)
        return abs(y) <= h / 2 and (x / rx) ** 2 + (z / rz) ** 2 <= 1.0
    if profile == "curve":
        descriptor = _skin_part(part, skin)
        samples = _curve_samples(descriptor)
        radius = float(descriptor["radius_m"])
        return min(_segment_distance_sq((x, y, z), a, b)
                   for a, b in zip(samples, samples[1:])) <= radius * radius
    if part.shape == "tapered" and not skin.get("physical"):
        # Match the design's frustum intent: narrower toward +Y, never thinner
        # than 40% of its base dimensions.
        q = max(0.0, min(1.0, (y + h / 2) / h))
        scale = 1.0 - 0.6 * q
        return abs(y) <= h / 2 and abs(x) <= w * scale / 2 and abs(z) <= d * scale / 2
    return abs(x) <= w / 2 and abs(y) <= h / 2 and abs(z) <= d / 2


def _bounds(part: WirePart, skin: dict[str, Any]) -> tuple[float, float, float]:
    w, h, d = (float(v) for v in part.size_m)
    if skin.get("physical") and _effective_profile(part, skin) == "curve":
        bend = abs(float(skin.get("bend_m", 0.0)))
        return w + 2*bend, h, d
    return w, h, d


def _local_cells(part: WirePart, skin: dict[str, Any], cell: float) -> tuple[list[tuple[int,int,int]], tuple[float,float,float]]:
    bw, bh, bd = _bounds(part, skin)
    nx, ny, nz = (max(1, int((v / cell) + 0.999999)) for v in (bw, bh, bd))
    origin = (-nx * cell / 2, -ny * cell / 2, -nz * cell / 2)
    cells: list[tuple[int,int,int]] = []
    for i in range(nx):
        x = origin[0] + (i + 0.5) * cell
        for j in range(ny):
            y = origin[1] + (j + 0.5) * cell
            for k in range(nz):
                z = origin[2] + (k + 0.5) * cell
                if _inside(part, skin, x, y, z):
                    cells.append((i, j, k))
    return cells, origin


def matter_document(design: WorkshopDesign, component_overrides: Any = None, *,
                    cell_size_m: float = 0.04, exterior_only: bool = False) -> dict[str, Any]:
    cell = _number(cell_size_m, "cell_size_m", 0.005, 0.2)
    overrides = skin_overrides(component_overrides)
    output: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    physical_curves: list[str] = []
    total = 0
    neighbors = ((1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1))
    for part in design.parts:
        skin = overrides.get(part.name, {})
        if skin.get("physical") and _effective_profile(part, skin) == "curve":
            physical_curves.append(part.name)
        local, origin = _local_cells(part, skin, cell)
        occupied = set(local)
        counts[part.name] = len(local)
        total += len(local)
        if total > MAX_PREVIEW_CELLS:
            raise ValueError(
                f"Matter preview has more than {MAX_PREVIEW_CELLS:,} cells at {cell*1000:g} mm; use a coarser preview cell")
        for i, j, k in local:
            exposed = any((i+di, j+dj, k+dk) not in occupied for di,dj,dk in neighbors)
            if exterior_only and not exposed:
                continue
            local_point = (origin[0] + (i+0.5)*cell,
                           origin[1] + (j+0.5)*cell,
                           origin[2] + (k+0.5)*cell)
            ox, oy, oz = _rotate(part.rotation_deg, local_point)
            output.append({
                "component": part.name,
                "material": part.material,
                "center_m": [round(part.center_m[0] + ox, 6),
                             round(part.center_m[1] + oy, 6),
                             round(part.center_m[2] + oz, 6)],
                "exposed": exposed,
            })
    return {
        "schema": MATTER_SCHEMA,
        "design_id": design.design_id,
        "cell_size_m": cell,
        "cells": output,
        "component_cell_counts": counts,
        "total_cells": total,
        "shown_cells": len(output),
        "exterior_only": bool(exterior_only),
        "physical_curve_components": physical_curves,
        "surface_error_bound_m": round(sqrt(3.0) * cell / 2.0, 6),
        "limitations": [
            "This is the deterministic Workshop physical-cell preview. Curved physical skins are voxelized here, but current scratch engine scenes still use their existing primitive/reduced body adapters until the sparse-body scene ABI is added."
        ],
    }
