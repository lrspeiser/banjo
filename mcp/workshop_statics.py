"""Cheap, explicit static-load estimates for Workshop candidates.

These are arithmetic checks, not engine trials.  The design's own weight and a
vertical declared load are distributed over the members that touch the floor by
the minimum-norm non-negative reaction solution satisfying vertical force and
the two horizontal moment balances.  That is a defined rigid support model; it
does not claim wood stiffness, joint compliance, buckling or fracture.
"""
from __future__ import annotations

from math import isfinite
from typing import Any

from mcp.workshop import WorkshopDesign

G_M_S2 = 9.80665
_EPS_N = 1.0e-7


def _solve3(matrix: list[list[float]], rhs: list[float]) -> list[float]:
    a = [list(row) + [float(value)] for row, value in zip(matrix, rhs)]
    for col in range(3):
        pivot = max(range(col, 3), key=lambda r: abs(a[r][col]))
        if abs(a[pivot][col]) < 1.0e-12:
            raise ValueError("the support layout cannot resolve vertical force and both tip moments")
        a[col], a[pivot] = a[pivot], a[col]
        scale = a[col][col]
        a[col] = [v / scale for v in a[col]]
        for row in range(3):
            if row == col:
                continue
            scale = a[row][col]
            a[row] = [v - scale * q for v, q in zip(a[row], a[col])]
    return [a[i][3] for i in range(3)]


def _reactions(points: list[tuple[float, float]], total_n: float,
               load_x: float, load_z: float) -> list[float]:
    """Minimum-norm non-negative support reactions satisfying Fz/Mx/Mz."""
    if len(points) < 3:
        raise ValueError("at least three non-collinear ground supports are needed")
    active = list(range(len(points)))
    reactions = [0.0] * len(points)
    while len(active) >= 3:
        cols = [(1.0, points[i][0], points[i][1]) for i in active]
        normal = [[sum(c[r] * c[k] for c in cols) for k in range(3)] for r in range(3)]
        y = _solve3(normal, [total_n, total_n * load_x, total_n * load_z])
        trial = [sum(c[r] * y[r] for r in range(3)) for c in cols]
        worst = min(range(len(trial)), key=lambda i: trial[i])
        if trial[worst] >= -_EPS_N:
            for slot, value in zip(active, trial):
                reactions[slot] = max(0.0, value)
            return reactions
        del active[worst]
    raise ValueError("the load lies outside the support polygon in this static model")


def _supports(design: WorkshopDesign) -> list[dict[str, Any]]:
    measured = design.measure()
    floor = float(measured["lowest_m"])
    standing = set(measured["standing_on"])
    result = []
    for part in design.parts:
        if part.name not in standing:
            continue
        contacts = part.ground_contacts_m()
        if not contacts:
            continue
        result.append({
            "name": part.name,
            "role": part.role,
            "family": part.family,
            "at_m": [sum(p[0] for p in contacts) / len(contacts),
                     sum(p[1] for p in contacts) / len(contacts)],
            "floor_m": floor,
        })
    return result


def _load_point(design: WorkshopDesign, on: str | None) -> tuple[float, float]:
    wanted = str(on or "top")
    named = next((p for p in design.parts if p.name == wanted), None)
    if named is None:
        named = next((p for p in design.parts if p.role == wanted), None)
    if named is None and wanted == "top":
        named = next((p for p in design.parts if p.name in {"top", "seat", "deck"}), None)
    if named is None:
        raise ValueError(f"the declared load names {wanted!r}, but that part/role is not in the design")
    return float(named.center_m[0]), float(named.center_m[2])


def static_load(design: WorkshopDesign, *, load_kg: float, on: str = "top") -> dict[str, Any]:
    load_kg = float(load_kg)
    if not isfinite(load_kg) or load_kg < 0:
        raise ValueError("load_kg must be a finite non-negative number")
    measured = design.measure()
    own_mass = float(measured["mass_kg"])
    own_x, _, own_z = (float(v) for v in measured["centre_of_mass_m"])
    load_x, load_z = _load_point(design, on)
    total_mass = own_mass + load_kg
    if total_mass <= 0:
        raise ValueError("the loaded design must have mass")
    combined_x = (own_mass * own_x + load_kg * load_x) / total_mass
    combined_z = (own_mass * own_z + load_kg * load_z) / total_mass
    supports = _supports(design)
    points = [(float(s["at_m"][0]), float(s["at_m"][1])) for s in supports]
    reaction = _reactions(points, total_mass * G_M_S2, combined_x, combined_z)
    rows = []
    for support, force in zip(supports, reaction):
        rows.append({**support,
                     "reaction_n": round(force, 3),
                     "equivalent_load_kg": round(force / G_M_S2, 3)})
    max_row = max(rows, key=lambda r: r["reaction_n"])
    return {
        "schema": "banjo.workshop-statics.v1",
        "kind": "static_load",
        "design_id": design.design_id,
        "external_load_kg": round(load_kg, 3),
        "load_on": on,
        "own_mass_kg": round(own_mass, 3),
        "combined_load_point_m": [round(combined_x, 4), round(combined_z, 4)],
        "supports": rows,
        "max_support": {"name": max_row["name"],
                        "reaction_n": max_row["reaction_n"],
                        "equivalent_load_kg": max_row["equivalent_load_kg"]},
        "equilibrium_error_n": round(abs(sum(reaction) - total_mass * G_M_S2), 9),
        "model": ("minimum-norm non-negative rigid support reactions; satisfies vertical force "
                  "and x/z moment balance; ignores member/joint compliance, buckling and failure"),
        "evidence": "analytical-estimate",
    }


def declared_statics(design: WorkshopDesign) -> list[dict[str, Any]]:
    """Run every static_load declaration the assembly carries."""
    out = []
    for trial in design.tests:
        if trial.get("kind") == "static_load":
            out.append(static_load(design, load_kg=float(trial.get("load_kg", 0)),
                                   on=str(trial.get("on") or "top")))
    return out
