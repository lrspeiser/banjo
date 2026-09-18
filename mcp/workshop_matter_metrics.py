"""Measurements of canonical occupied cells, not the unedited design primitives.

These are grid geometry/mass diagnostics, not an elastic solve or a certificate
of strength. Face-connected islands deliberately do not claim to be the engine's
bond graph. Unsupported gaps/joints must be validated in a detailed trial.
"""
from __future__ import annotations

from math import atan2, degrees, hypot, isfinite
from typing import Any

from mcp import engine_materials


def has_physical_skin(design: Any) -> bool:
    patches = (getattr(design, "lineage", None) or {}).get("component_overrides") or {}
    return any(isinstance(p, dict) and isinstance(p.get("skin"), dict)
               and p["skin"].get("physical") is True for p in patches.values())


def require_wire_geometry(design: Any, operation: str) -> None:
    if has_physical_skin(design):
        raise ValueError(f"{operation} does not yet consume physical skin cells. "
                         "Use the exact-Matter static-load trial; old wireframe "
                         "measurements cannot validate a physically edited product.")


def _hull(points):
    points = sorted(set(points))
    def cross(o, a, b):
        return (a[0]-o[0])*(b[1]-o[1]) - (a[1]-o[1])*(b[0]-o[0])
    if len(points) <= 1:
        return points
    halves = []
    for ordered in (points, list(reversed(points))):
        chain = []
        for point in ordered:
            while len(chain) >= 2 and cross(chain[-2], chain[-1], point) <= 0:
                chain.pop()
            chain.append(point)
        halves.append(chain[:-1])
    return halves[0] + halves[1]


def measure(matter: dict[str, Any], *, expected_components=()) -> dict[str, Any]:
    """Full-cell mass, inertia, support hull and conservative connectivity.

    The input must contain ALL canonical cells. An exterior-only rendering must
    never lower mass or discard internal connectivity. Cells shared by authored
    components count once globally; component mass is assigned to the canonical
    primary owner and explicitly labelled as such.
    """
    if matter.get("schema") != "banjo.workshop-matter.v2":
        raise ValueError("measurements require canonical Matter v2")
    rows = matter.get("cells") or []
    h = float(matter["cell_size_m"])
    if not isfinite(h) or h <= 0:
        raise ValueError("Matter cell size must be finite and positive")
    if any(not isinstance(row, dict) or not isinstance(row.get("grid"), list)
           or len(row["grid"]) != 3 or any(type(v) is not int for v in row["grid"])
           for row in rows):
        raise ValueError("Matter grid coordinates must be three integers")
    cells = {tuple(row["grid"]): row for row in rows}
    if len(cells) != len(rows) or len(cells) != matter.get("total_cells"):
        raise ValueError("measurements require the complete, unique Matter cell set")
    if not cells:
        raise ValueError("the design has no occupied Matter cells at this resolution")
    masses = {}
    by_part: dict[str, float] = {}
    by_material: dict[str, dict[str, Any]] = {}
    for grid, row in cells.items():
        material = engine_materials.canonical(row["material"])
        try:
            mass = engine_materials.density(material) * h**3
        except KeyError as exc:
            raise ValueError(str(exc)) from exc
        masses[grid] = mass
        name = str(row.get("component") or "")
        by_part[name] = by_part.get(name, 0.0) + mass
        item = by_material.setdefault(material, {"material": material, "mass_kg": 0.0,
                                                  "volume_m3": 0.0, "parts": set()})
        item["mass_kg"] += mass
        item["volume_m3"] += h**3
        item["parts"].update(row.get("components") or [name])
    total = sum(masses.values())
    com = [sum((g[a]+.5)*h*m for g, m in masses.items()) / total for a in range(3)]
    inertia = [[0.0]*3 for _ in range(3)]
    for grid, mass in masses.items():
        d = [(grid[a]+.5)*h-com[a] for a in range(3)]
        r2 = sum(v*v for v in d)
        for i in range(3):
            for j in range(3):
                inertia[i][j] += mass * ((r2+h*h/6 if i == j else 0)-d[i]*d[j])

    floor_index = min(g[1] for g in cells)
    floor = floor_index*h
    contacts = [g for g in cells if g[1] == floor_index]
    hull = _hull([(g[0]*h+dx*h, g[2]*h+dz*h)
                  for g in contacts for dx in (0,1) for dz in (0,1)])
    margins = {}
    for i, a in enumerate(hull):
        b = hull[(i+1) % len(hull)]
        dx, dz = b[0]-a[0], b[1]-a[1]
        margins[f"edge-{i}"] = (dx*(com[2]-a[1])-dz*(com[0]-a[0])) / hypot(dx,dz)
    margin = min(margins.values())

    # Strict shared-face connectivity is a geometry warning, not an invented
    # bond/interface law. It catches vanished/disconnected curved members.
    left = set(cells)
    islands = []
    adjacent = ((1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1))
    while left:
        start = min(left); left.remove(start); stack = [start]
        names = set(); count = 0; grounded = False
        while stack:
            g = stack.pop(); count += 1; grounded |= g[1] == floor_index
            row = cells[g]; names.update(row.get("components") or [row.get("component")])
            for offset in adjacent:
                neighbor = tuple(g[a]+offset[a] for a in range(3))
                if neighbor in left:
                    left.remove(neighbor); stack.append(neighbor)
        islands.append({"cells": count, "components": sorted(n for n in names if n),
                        "touches_ground": grounded})
    present = {name for row in rows for name in (row.get("components") or [row.get("component")])}
    missing = sorted(set(expected_components)-present)
    warnings = []
    if missing:
        warnings.append("Components vanished at this cell size: " + ", ".join(missing))
    if len(islands) != 1:
        warnings.append(f"Matter has {len(islands)} face-connected islands; connections require a physical test.")
    coherent = not missing and len(islands) == 1
    extents = [((max(g[a] for g in cells)+1)-min(g[a] for g in cells))*h for a in range(3)]
    span = [max(p[a] for p in hull)-min(p[a] for p in hull) for a in (0,1)]
    measured = {
        "basis": "canonical-matter-grid", "cell_size_m": h,
        "matter_physics_hash": matter["physics_hash"],
        "mass_kg": total, "centre_of_mass_m": com, "inertia_kg_m2": inertia,
        "lowest_m": floor, "bounding_box_m": extents,
        "standing_on": sorted({name for g in contacts for name in
                                (cells[g].get("components") or [cells[g].get("component")])}),
        "ground_contacts_m": [list(p) for p in hull], "support_polygon_m": [list(p) for p in hull],
        "support_footprint_m": span, "tip_margin_m": margins,
        "smallest_tip_margin_m": margin,
        "tip_angle_deg": degrees(atan2(margin, max(com[1]-floor, 1e-12))),
        "stands_up": coherent and margin > 0,
        "legs_not_under_the_top": [], "connectivity_verified": False,
        "geometry_coherent": coherent, "missing_components": missing, "islands": islands,
        "warnings": warnings,
        "limitations": ["Geometric balance assumes a rigid, connected assembly on a flat floor; no strength is validated.",
                        "Face connectivity is not the engine bond graph or a validation of authored joints.",
                        "Component masses allocate shared cells to their canonical primary owner."]}
    materials = []
    for material, row in sorted(by_material.items()):
        materials.append({**row, "parts": len(row["parts"])})
    return {"measured": measured, "component_mass_kg": by_part, "materials": materials}
