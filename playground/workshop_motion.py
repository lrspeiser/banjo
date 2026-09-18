"""Bounded drop/slide experiments on the selected solid's exact native cells.

No reference fixture, scripted deformation, or force-path-only result. The
initial height/speed are declared; gravity, contact and failure use LiveWorld.
This first adapter is for connected, single-material structural solids only.
"""
from __future__ import annotations

from math import dist, isfinite
from pathlib import Path
import time
from typing import Any

import fracture_lab
import live_session
import workshop_recording
import workshop_sparse_trial as sparse
import workshop_trials_core as trials
from mcp import engine_materials, workshop_matter_metrics, workshop_visual, workshop_rigid

SOLID_KINDS = {"table", "bench"}
STRUCTURAL_ROLES = {"leg", "post", "beam", "brace", "apron", "stretcher", "top", "panel", "surface"}
TESTS = {"drop_product", "slide_product"}


def number(config: dict, name: str, default: float, low: float, high: float) -> float:
    value = config.get(name, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name} must be a finite number between {low:g} and {high:g}")
    return float(value)


def catalog(kind: str | None) -> list[dict[str, Any]]:
    if kind and kind not in SOLID_KINDS:
        return []
    common = [
        {"name": "duration_s", "label": "Simulate", "unit": "s", "type": "number", "default": 1.5, "min": .1, "max": 3.0, "step": .1},
        {"name": "cell_size_m", "label": "Cell size", "unit": "m", "type": "number", "default": .04, "min": .005, "max": .1, "step": .005},
    ]
    out = []
    for test, title, about, control in [
        ("drop_product", "Drop onto the floor", "Lift this solid and release it at rest. Watch gravity and contact act on the actual compiled object.",
         {"name": "height_m", "label": "Drop height", "unit": "m", "type": "number", "default": .2, "min": .04, "max": 2.0, "step": .04}),
        ("slide_product", "Slide across the floor", "Give this solid a declared starting speed along +X. Watch friction slow it; this is not a sustained push or motor.",
         {"name": "speed_m_s", "label": "Starting speed", "unit": "m/s", "type": "number", "default": 1.0, "min": .1, "max": 3.0, "step": .1}),
    ]:
        out.append({"test": test, "name": title, "about": about, "kinds": sorted(SOLID_KINDS),
                    "category": "simulation", "subject": "selected-product", "visual_playback": True,
                    "controls": [control, *[dict(c) for c in common]],
                    "limitations": ["One connected material volume; no articulated mechanisms. Sub-cell features must be resolved before running. Failure is the current engine model, not calibrated material certification."]})
    return out


def scene(design, test: str, config: dict[str, Any]) -> dict[str, Any]:
    if test not in TESTS:
        raise ValueError("Unknown motion experiment")
    h = number(config, "cell_size_m", .04, .005, .1)
    duration = number(config, "duration_s", 1.5, .1, 3.0)
    height = number(config, "height_m", .2, .04, 2.0) if test == "drop_product" else 0.0
    speed = number(config, "speed_m_s", 1.0, .1, 3.0) if test == "slide_product" else 0.0
    design.validate()
    workshop_rigid.require_lattice(design, "This exact-cell experiment")
    if any(p.role not in STRUCTURAL_ROLES for p in design.parts):
        raise ValueError("Drop/slide supports structural solids, not moving assemblies or containers. Use the cart or kettle's own simulation.")
    matter = workshop_visual.matter_document(design, sparse._matter_overrides(design), cell_size_m=h, exterior_only=False)
    missing = [name for name, count in matter["component_cell_counts"].items() if count == 0]
    if missing:
        raise ValueError("Cannot simulate: " + ", ".join(missing) + f" disappear at {h*1000:g} mm cells. Use a finer cell size or thicker parts; no substitute object was tested.")
    summary = workshop_matter_metrics.measure(matter, expected_components=[p.name for p in design.parts])
    if not summary["measured"]["geometry_coherent"]:
        raise ValueError("Cannot simulate: compiled components are disconnected. Repair the design or its cell resolution first; no substitute object was tested.")
    cells = sparse._grid_set(matter)
    materials = {engine_materials.canonical(c["material"]) for c in matter["cells"]}
    if len(materials) != 1 or any(not engine_materials.known(m) for m in materials):
        raise ValueError("Drop/slide requires one supported material; mixed materials need explicit interfaces.")
    if len(cells) > int(fracture_lab.ALGORITHMS["lattice"]["max_cells"]):
        raise ValueError("This design exceeds the simulation cell budget. Use a coarser cell size only if every part remains resolved.")
    lift = max(1, round(height / h)) if height else 0
    shift = (0, -min(g[1] for g in cells) + lift, 0)
    placed = {tuple(g[a] + shift[a] for a in range(3)) for g in cells}
    boxes = sparse.decompose_cells(placed)
    if len(boxes) > sparse.MAX_SCENE_BOXES or sparse.cells_from_boxes(boxes) != placed:
        raise ValueError("The exact shape exceeds the scene adapter's complexity limit; no simpler shape was substituted.")
    root = "workshop/product"
    bodies = [sparse._box_body(root if i == 0 else f"{root}-{i}", box, h, next(iter(materials)), root)
              for i, box in enumerate(boxes)]
    for body in bodies:
        body["velocity_m_s"] = [speed, 0.0, 0.0]
    spec = fracture_lab.validate({"algorithm": "lattice", "cell_m": h, "plasticity": "on", "bodies": bodies})
    return {"spec": spec, "matter": matter, "root": root, "shift": shift, "duration_s": duration,
            "height_m": height, "applied_height_m": lift*h, "speed_m_s": speed,
            "mass_kg": summary["measured"]["mass_kg"]}


def run(app: Any, design, test: str, config: dict[str, Any], *, session_factory=None) -> dict[str, Any]:
    setup = scene(design, test, config)
    engine = Path(app.engine_path)
    if not engine.is_file():
        raise ValueError("Physics runner is missing. Build banjo_live_world_run and restart the server with that engine; the test has not run.")
    runs = Path(app.runs_path) / "workshop-motion"
    runs.mkdir(parents=True, exist_ok=True)
    session = workshop_recording.wrap((session_factory or live_session.Session)(engine, setup["spec"], runs))
    fractures = []
    deadline = time.monotonic() + 30.0
    try:
        initial = session.send(op="poses")
        snapshot = session.send(op="snapshot").get("snapshot")
        if not isinstance(snapshot, dict):
            raise ValueError("The native engine did not provide geometry verification. Rebuild the runtime before testing.")
        verified = sparse.verify_engine_matter(snapshot, setup["matter"], setup["root"], placement_grid=setup["shift"])
        state = initial
        while float(state.get("t", 0)) < setup["duration_s"] - 1e-9:
            if time.monotonic() > deadline:
                raise RuntimeError("The simulation exceeded its work budget; no completed result is claimed.")
            before = float(state.get("t", 0))
            state = session.send(op="step", dt=min(1/120, setup["duration_s"]-before), n=1)
            attempts = 0
            while state.get("breakable"):
                attempts += 1
                if attempts > 64 or time.monotonic() > deadline:
                    raise RuntimeError("Material failure did not finish within the test budget; no completed result is claimed.")
                name = str(state["breakable"][0])
                state = session.send(op="fracture", name=name, window_s=.003)
                fractures.append({"name": name, "at_s": float(state.get("t", 0))})
            if not state.get("ok", True):
                raise RuntimeError(str(state.get("error") or "Native simulation refused this step"))
            if float(state.get("t", 0)) <= before and attempts == 0:
                raise RuntimeError("The native simulation stopped advancing; no completed result is claimed.")
        final = session.send(op="poses")
    finally:
        session.close()
    first = trials._body(initial, setup["root"])
    last = trials._body(final, setup["root"])
    measured = {"clock_s": float(final["t"]), "prototype_present": last is not None,
                "prototype_displacement_m": dist(first["position_m"], last["position_m"]) if first and last else None,
                "fracture_events": len(fractures), "body_count": len(final.get("bodies", [])),
                "start_position_m": first.get("position_m") if first else None,
                "end_position_m": last.get("position_m") if last else None}
    limitations = ["Single-material structural solid at the reported grid resolution. A completed run is not a strength certificate."]
    requested = {"height_m": setup["height_m"], "applied_height_m": setup["applied_height_m"],
                 "speed_m_s": setup["speed_m_s"], "duration_s": setup["duration_s"], "cell_size_m": setup["matter"]["cell_size_m"]}
    playback = session.recording(test=test, requested=requested, limitations=limitations)
    playback["geometry"] = verified["render_geometry"]
    playback["geometry_basis"] = "verified-native-cells-until-topology-changes"
    return {"schema": "banjo.workshop-bench.v1", "test": test, "evidence": "engine-trial", "subject": "selected-product",
            "design_id": design.design_id, "requested": requested, "measured": measured, "playback": playback,
            "prototype": {"root_body": setup["root"], "matter_physics_hash": setup["matter"]["physics_hash"],
                          "matter_cells": setup["matter"]["total_cells"], "engine_grid_verified": True},
            "acceptance": {"status": "observed", "why": "The engine completed this experiment; no pass/fail requirement was declared."},
            "limitations": limitations}
