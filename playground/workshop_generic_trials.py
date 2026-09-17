"""Generic visual physics fixtures around exact Workshop Matter.

Fixtures are deliberately product-agnostic. The product under test is always the
canonical Matter v2 artifact encoded losslessly as joined grid boxes. A fixture
may be a simple floor or projectile; it never substitutes product geometry.
"""
from __future__ import annotations

from math import ceil, isfinite
from pathlib import Path
from typing import Any

import fracture_lab
import live_session
import workshop_bench_core as bench_core
import workshop_sparse_trial as sparse
from mcp import engine_materials, workshop_visual
from mcp.workshop import WorkshopDesign

GENERIC_SCHEMA = "banjo.workshop-generic-trial.v1"


def _number(config: dict[str, Any], name: str, default: float, low: float, high: float) -> float:
    try:
        value = float(config.get(name, default))
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number") from None
    if not isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name} must be between {low:g} and {high:g}")
    return value


def _exact_product(design: WorkshopDesign, cell: float, shift: tuple[int, int, int] = (0, 0, 0)) -> dict[str, Any]:
    matter = workshop_visual.matter_document(
        design, sparse._matter_overrides(design), cell_size_m=cell, exterior_only=False)
    cells = sparse._grid_set(matter)
    materials = {engine_materials.canonical(str(c.get("material") or "")) for c in matter.get("cells") or []}
    unsupported = sorted(m for m in materials if not engine_materials.known(m))
    if unsupported:
        raise ValueError("the engine has no Banjo material preset for " + ", ".join(unsupported))
    if len(materials) != 1:
        raise ValueError(
            "generic exact-Matter trials currently require one fused material; mixed-material assemblies need explicit interface laws")
    material = next(iter(materials))
    moved = {(g[0] + shift[0], g[1] + shift[1], g[2] + shift[2]) for g in cells}
    boxes = sparse.decompose_cells(moved)
    if sparse.cells_from_boxes(boxes) != moved:
        raise RuntimeError("internal error: generic fixture changed the exact Matter cell set")
    if len(boxes) > sparse.MAX_SCENE_BOXES:
        raise ValueError(
            f"exact Matter needs {len(boxes)} scene boxes at {cell*1000:g} mm; use a coarser cell")
    join = "workshop-matter-" + str(matter["physics_hash"])[:12]
    bodies = [sparse._box_body(f"candidate/matter-{i+1}", box, cell, material, join)
              for i, box in enumerate(boxes)]
    return {
        "matter": matter,
        "source_cells": cells,
        "scene_cells": moved,
        "boxes": boxes,
        "bodies": bodies,
        "root": bodies[0]["name"],
        "join": join,
        "material": material,
        "shift_grid": list(shift),
    }


def _bounds(cells: set[sparse.Grid]) -> tuple[sparse.Grid, sparse.Grid]:
    return ((min(g[0] for g in cells), min(g[1] for g in cells), min(g[2] for g in cells)),
            (max(g[0] for g in cells), max(g[1] for g in cells), max(g[2] for g in cells)))


def _floor_body(cells: set[sparse.Grid], cell: float) -> dict[str, Any]:
    lo, hi = _bounds(cells)
    margin = 4
    floor_box: sparse.Box = ((lo[0] - margin, lo[1] - 2, lo[2] - margin),
                             (hi[0] + margin, lo[1] - 1, hi[2] + margin))
    body = sparse._box_body("workshop/floor", floor_box, cell, "iron", "")
    body["anchored"] = True
    return body


def _session(app: Any, label: str, spec: dict[str, Any]):
    engine = Path(getattr(app, "engine_path"))
    runs = Path(getattr(app, "runs_path")) / "workshop-bench" / label
    runs.mkdir(parents=True, exist_ok=True)
    return live_session.Session(engine, spec, runs)


def _motion(start: dict[str, Any], final: dict[str, Any], root: str) -> dict[str, Any]:
    a = next((b for b in start.get("bodies") or [] if b.get("name") == root), None)
    b = next((b for b in final.get("bodies") or [] if b.get("name") == root), None)
    if a is None or b is None:
        return {"prototype_present": b is not None, "delta_m": None, "rotation_change_deg": None}
    pa, pb = a.get("position_m") or [0, 0, 0], b.get("position_m") or [0, 0, 0]
    delta = [float(pb[i]) - float(pa[i]) for i in range(3)]
    turned = sparse.core._quat_angle_deg(a.get("orientation_wxyz") or [1,0,0,0],
                                         b.get("orientation_wxyz") or [1,0,0,0])
    return {"prototype_present": True, "delta_m": [round(v, 6) for v in delta],
            "rotation_change_deg": round(float(turned), 4)}


def run_drop(app: Any, design: WorkshopDesign, config: dict[str, Any]) -> dict[str, Any]:
    cell = _number(config, "cell_size_m", 0.04, 0.01, 0.12)
    height = _number(config, "height_m", 0.5, 0.05, 3.0)
    duration = _number(config, "duration_s", 1.5, 0.2, 6.0)
    lift = max(1, int(ceil(height / cell)))
    product = _exact_product(design, cell, (0, lift, 0))
    floor = _floor_body(product["source_cells"], cell)
    spec = fracture_lab.validate({"algorithm": "lattice", "cell_m": cell, "plasticity": "on",
                                  "bodies": [*product["bodies"], floor]})
    session = _session(app, "drop", spec)
    try:
        start = session.send(op="poses")
        final = bench_core._advance(session, duration, dt=1/120.0)
        fractures = list(final.get("fractures") or [])
    finally:
        session.close()
    return {
        "schema": GENERIC_SCHEMA, "test": "drop_test", "evidence": "engine-trial",
        "requested": {"height_m": height, "duration_s": duration, "cell_size_m": cell},
        "prototype": {"matter_physics_hash": product["matter"]["physics_hash"],
                      "matter_artifact_hash": product["matter"]["artifact_hash"],
                      "matter_cells": product["matter"]["total_cells"],
                      "matter_boxes": len(product["boxes"]), "shift_grid": product["shift_grid"],
                      "matter_roundtrip_exact": True},
        "measured": {**_motion(start, final, product["root"]),
                     "clock_s": round(float(final.get("t", 0.0)), 6),
                     "breakable": list(final.get("breakable") or []), "fractures": fractures},
        "acceptance": {"status": "observed", "why": "Drop motion and damage are measured; the product declares no universal drop criterion."},
        "limitations": ["The product is translated by a whole number of cells for the fixture; its occupied-cell shape and Matter hash are unchanged."],
    }


def _projectile(load_kg: float, speed: float, cell: float, cells: set[sparse.Grid], height_fraction: float) -> tuple[dict[str, Any], float]:
    lo, hi = _bounds(cells)
    per_cell = engine_materials.density("iron") * cell**3
    n = max(1, round(load_kg / per_cell))
    side = max(1, round(n ** (1/3)))
    nx = side; ny = side; nz = max(1, round(n / max(1, nx*ny)))
    actual = nx*ny*nz*per_cell
    target_y = lo[1] + round((hi[1]-lo[1]) * height_fraction)
    x0 = lo[0] - nx - 3
    z0 = round((lo[2]+hi[2])/2) - nz//2
    box: sparse.Box = ((x0, target_y-ny//2, z0), (x0+nx-1, target_y-ny//2+ny-1, z0+nz-1))
    body = sparse._box_body("workshop/projectile", box, cell, "iron", "")
    body["velocity_m_s"] = [speed, 0.0, 0.0]
    return body, actual


def run_impact(app: Any, design: WorkshopDesign, config: dict[str, Any]) -> dict[str, Any]:
    cell = _number(config, "cell_size_m", 0.04, 0.01, 0.12)
    mass = _number(config, "mass_kg", 5.0, 0.1, 200.0)
    speed = _number(config, "speed_m_s", 3.0, 0.1, 30.0)
    height_fraction = _number(config, "height_fraction", 0.5, 0.0, 1.0)
    duration = _number(config, "duration_s", 1.0, 0.2, 5.0)
    product = _exact_product(design, cell)
    floor = _floor_body(product["scene_cells"], cell)
    projectile, actual_mass = _projectile(mass, speed, cell, product["scene_cells"], height_fraction)
    spec = fracture_lab.validate({"algorithm": "lattice", "cell_m": cell, "plasticity": "on",
                                  "bodies": [*product["bodies"], floor, projectile]})
    session = _session(app, "impact", spec)
    try:
        start = session.send(op="poses")
        final = bench_core._advance(session, duration, dt=1/120.0)
    finally:
        session.close()
    kinetic = 0.5 * actual_mass * speed * speed
    return {
        "schema": GENERIC_SCHEMA, "test": "impact_test", "evidence": "engine-trial",
        "requested": {"mass_kg": mass, "speed_m_s": speed, "height_fraction": height_fraction,
                      "duration_s": duration, "cell_size_m": cell},
        "prototype": {"matter_physics_hash": product["matter"]["physics_hash"],
                      "matter_artifact_hash": product["matter"]["artifact_hash"],
                      "matter_cells": product["matter"]["total_cells"],
                      "matter_boxes": len(product["boxes"]), "matter_roundtrip_exact": True},
        "fixture": {"actual_projectile_mass_kg": round(actual_mass, 6),
                    "initial_kinetic_j": round(kinetic, 4), "height_fraction": height_fraction},
        "measured": {**_motion(start, final, product["root"]),
                     "clock_s": round(float(final.get("t", 0.0)), 6),
                     "breakable": list(final.get("breakable") or [])},
        "acceptance": {"status": "observed", "why": "Impact, tip response and fracture indicators are measured; no universal limit is invented."},
        "limitations": ["Projectile mass is quantized to whole lattice cells; actual mass and impact energy are reported."],
    }
