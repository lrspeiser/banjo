"""Workshop visual representations: editable skins and canonical physical matter.

Wire geometry remains authoritative for design intent. A skin is a separate,
editable render description. Matter is different: it is compiled onto Banjo's
shared engine grid, with the same cell-centre convention used by VoxelRecipe:
cell (i,j,k) is centred at ((i+.5)h,(j+.5)h,(k+.5)h).

A physical skin edit changes that matter compilation. An appearance-only edit
does not. The returned integer grid coordinates are the canonical artifact used
by both the browser and Workshop physics adapters; no renderer-local voxel grid
is allowed to stand in for physics.
"""
from __future__ import annotations

import hashlib
import json
from math import ceil, cos, floor, isfinite, radians, sin, sqrt
from typing import Any

from mcp.workshop import WorkshopDesign, WirePart

SKIN_SCHEMA = "banjo.product-skin.v1"
MATTER_SCHEMA = "banjo.workshop-matter.v2"
MAX_PREVIEW_CELLS = 50000
MAX_SCAN_CELLS = 2_000_000

_FACE_DIRS = (
    ("+x", (1, 0, 0)), ("-x", (-1, 0, 0)),
    ("+y", (0, 1, 0)), ("-y", (0, -1, 0)),
    ("+z", (0, 0, 1)), ("-z", (0, 0, -1)),
)


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
        q = max(0.0, min(1.0, (y + h / 2) / h))
        scale = 1.0 - 0.6 * q
        return abs(y) <= h / 2 and abs(x) <= w * scale / 2 and abs(z) <= d * scale / 2
    return abs(x) <= w / 2 and abs(y) <= h / 2 and abs(z) <= d / 2


def _bounds(part: WirePart, skin: dict[str, Any]) -> tuple[float, float, float]:
    w, h, d = (float(v) for v in part.size_m)
    if skin.get("physical") and _effective_profile(part, skin) == "curve":
        descriptor = _skin_part(part, skin)
        radius = float(descriptor["radius_m"])
        points = descriptor["control_points_local_m"]
        xs = [float(p[0]) for p in points]
        ys = [float(p[1]) for p in points]
        zs = [float(p[2]) for p in points]
        return (max(xs) - min(xs) + 2 * radius,
                max(ys) - min(ys) + 2 * radius,
                max(zs) - min(zs) + 2 * radius)
    return w, h, d


def _inverse_rotate(rotation_deg, v: tuple[float, float, float]) -> tuple[float, float, float]:
    """World vector -> body local, matching TileImpactScene::rotateDegrees."""
    x, y, z = (float(q) for q in v)
    ax, ay, az = (radians(-float(q)) for q in rotation_deg)
    cx, sx = cos(ax), sin(ax)
    y, z = y * cx - z * sx, y * sx + z * cx
    cy, sy = cos(ay), sin(ay)
    x, z = x * cy + z * sy, -x * sy + z * cy
    cz, sz = cos(az), sin(az)
    x, y = x * cz - y * sz, x * sz + y * cz
    return x, y, z


def _part_grid_cells(part: WirePart, skin: dict[str, Any], cell: float) -> list[tuple[int, int, int]]:
    # Scan one world-grid bounding sphere, then ask the actual local solid. This
    # is intentionally the same strategy as TileImpactScene's primitive
    # voxelisation: global cell centre -> inverse body rotation -> inside test.
    bw, bh, bd = _bounds(part, skin)
    reach = 0.5 * sqrt(bw*bw + bh*bh + bd*bd) + cell
    lo = [floor((float(part.center_m[a]) - reach) / cell) for a in range(3)]
    hi = [ceil((float(part.center_m[a]) + reach) / cell) for a in range(3)]
    scanned = (hi[0] - lo[0] + 1) * (hi[1] - lo[1] + 1) * (hi[2] - lo[2] + 1)
    if scanned > MAX_SCAN_CELLS:
        raise ValueError(
            f"{part.name}: Matter scan would inspect {scanned:,} cells; use a coarser cell size")
    out: list[tuple[int, int, int]] = []
    for gx in range(lo[0], hi[0] + 1):
        wx = (gx + 0.5) * cell
        for gy in range(lo[1], hi[1] + 1):
            wy = (gy + 0.5) * cell
            for gz in range(lo[2], hi[2] + 1):
                wz = (gz + 0.5) * cell
                local = _inverse_rotate(part.rotation_deg,
                    (wx - float(part.center_m[0]), wy - float(part.center_m[1]), wz - float(part.center_m[2])))
                if _inside(part, skin, *local):
                    out.append((gx, gy, gz))
    return out


def _digest(cell: float, occupied: dict[tuple[int, int, int], dict[str, Any]], *, identity: bool) -> str:
    rows = []
    for grid in sorted(occupied):
        item = occupied[grid]
        row: list[Any] = [*grid, item["material"]]
        if identity:
            row.append(sorted(item["components"]))
        rows.append(row)
    payload = json.dumps({"cell_size_m": cell, "cells": rows}, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def matter_document(design: WorkshopDesign, component_overrides: Any = None, *,
                    cell_size_m: float = 0.04, exterior_only: bool = False) -> dict[str, Any]:
    cell = _number(cell_size_m, "cell_size_m", 0.005, 0.2)
    overrides = skin_overrides(component_overrides)
    occupied: dict[tuple[int, int, int], dict[str, Any]] = {}
    counts: dict[str, int] = {}
    physical_curves: list[str] = []

    for part in design.parts:
        skin = overrides.get(part.name, {})
        if skin.get("physical") and _effective_profile(part, skin) == "curve":
            physical_curves.append(part.name)
        grids = _part_grid_cells(part, skin, cell)
        counts[part.name] = len(grids)
        for grid in grids:
            existing = occupied.get(grid)
            if existing is None:
                occupied[grid] = {
                    "material": part.material,
                    "component": part.name,
                    "components": [part.name],
                }
            else:
                if existing["material"] != part.material:
                    raise ValueError(
                        f"Matter cell {grid} is claimed by both {existing['material']} and {part.material}; "
                        "cross-material overlap needs an explicit physical interface")
                if part.name not in existing["components"]:
                    existing["components"].append(part.name)
        if len(occupied) > MAX_PREVIEW_CELLS:
            raise ValueError(
                f"Matter has more than {MAX_PREVIEW_CELLS:,} cells at {cell*1000:g} mm; use a coarser cell")

    output: list[dict[str, Any]] = []
    for grid in sorted(occupied):
        item = occupied[grid]
        faces = [name for name, (dx, dy, dz) in _FACE_DIRS
                 if (grid[0] + dx, grid[1] + dy, grid[2] + dz) not in occupied]
        if exterior_only and not faces:
            continue
        output.append({
            "grid": list(grid),
            "component": item["component"],
            "components": sorted(item["components"]),
            "material": item["material"],
            "center_m": [round((grid[a] + 0.5) * cell, 9) for a in range(3)],
            "exposed": bool(faces),
            "exposed_faces": faces,
        })

    physics_hash = _digest(cell, occupied, identity=False)
    artifact_hash = _digest(cell, occupied, identity=True)
    return {
        "schema": MATTER_SCHEMA,
        "design_id": design.design_id,
        "grid_convention": "center=(index+0.5)*cell_size_m",
        "cell_size_m": cell,
        "cells": output,
        "component_cell_counts": counts,
        "total_cells": len(occupied),
        "shown_cells": len(output),
        "exterior_only": bool(exterior_only),
        "physical_curve_components": physical_curves,
        "physics_hash": physics_hash,
        "artifact_hash": artifact_hash,
        "surface_error_bound_m": round(sqrt(3.0) * cell / 2.0, 9),
        "engine_ready": True,
        "limitations": [
            "Matter is compiled on the engine's shared grid. Workshop's current exact-cell engine adapter may encode this set as joined grid-aligned boxes; a native sparse-body scene field remains a size/performance optimization."
        ],
    }
