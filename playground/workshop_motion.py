"""Bounded drop/slide/strike experiments on the selected solid's exact native cells.

No reference fixture, scripted deformation, or force-path-only result. The
initial height/speed and the striker are declared; gravity, contact and failure
use LiveWorld. This adapter is for connected, single-material structural solids.

The ranges reach past every offered material's breaking bar on purpose. A drop
that tops out at 2 m lands at 6.3 m/s, under the 8.7 m/s at which the engine
says a glass table can first break and far under oak's 13.7 m/s, so every run
reported zero fractures whatever was chosen: the failure model was there and
no control could reach it.
"""
from __future__ import annotations

from math import dist, isfinite, sqrt
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
TESTS = {"drop_product", "slide_product", "impact_product"}
STRIKER = "workshop/striker"
STRIKER_MATERIAL = "iron"
GRAVITY_M_S2 = 9.81
# What a drop wants after it lands for the landing to be seen through.
SETTLE_S = 0.75
MAX_HEIGHT_M = 20.0
MAX_DURATION_S = 5.0


def number(config: dict, name: str, default: float, low: float, high: float) -> float:
    value = config.get(name, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name} must be a finite number between {low:g} and {high:g}")
    return float(value)


def catalog(kind: str | None) -> list[dict[str, Any]]:
    if kind and kind not in SOLID_KINDS:
        return []
    common = [
        {"name": "duration_s", "label": "Simulate", "unit": "s", "type": "number", "default": 1.5, "min": .1, "max": MAX_DURATION_S, "step": .1},
        {"name": "cell_size_m", "label": "Cell size", "unit": "m", "type": "number", "default": .04, "min": .005, "max": .1, "step": .005},
    ]
    out = []
    for test, title, about, controls in [
        ("drop_product", "Drop onto the floor", "Lift this solid and release it at rest. Watch gravity and contact act on the actual compiled object, and watch it come apart if it lands hard enough for what it is made of.",
         [{"name": "height_m", "label": "Drop height", "unit": "m", "type": "range", "default": .2, "min": .04, "max": MAX_HEIGHT_M, "step": .04}]),
        ("slide_product", "Slide across the floor", "Give this solid a declared starting speed along +X. Watch friction slow it; this is not a sustained push or motor.",
         [{"name": "speed_m_s", "label": "Starting speed", "unit": "m/s", "type": "number", "default": 1.0, "min": .1, "max": 3.0, "step": .1}]),
        ("impact_product", "Strike it with a weight", "Throw an iron block at this solid where it stands and watch what the blow does to it: shoved, tipped, dented, or broken into the pieces the engine actually computes.",
         [{"name": "striker_kg", "label": "Weight", "unit": "kg", "type": "range", "default": 5.0, "min": .5, "max": 200.0, "step": .5},
          {"name": "speed_m_s", "label": "Speed", "unit": "m/s", "type": "range", "default": 8.0, "min": .5, "max": 30.0, "step": .5},
          {"name": "height_fraction", "label": "Where (0 feet, 1 top)", "type": "range", "default": 1.0, "min": 0.0, "max": 1.0, "step": .05}]),
    ]:
        out.append({"test": test, "name": title, "about": about, "kinds": sorted(SOLID_KINDS),
                    "category": "simulation", "subject": "selected-product", "visual_playback": True,
                    "controls": [*controls, *[dict(c) for c in common]],
                    "limitations": ["One connected material volume; no articulated mechanisms. Sub-cell features must be resolved before running. Failure is the current engine model, not calibrated material certification."]})
    return out


def _striker(cells: set, h: float, mass_kg: float, fraction: float) -> tuple[sparse.Box, float]:
    """An iron block of whole cells beside the product, level with what it is to hit.

    It is aimed at matter, not at the middle of a bounding box: a table's middle
    is the air between its legs. Of the product's cells in the block's height
    band, it takes the nearest to the -X side and lines up on that one.
    """
    per_cell = engine_materials.density(STRIKER_MATERIAL) * h**3
    count = max(1, round(mass_kg / per_cell))
    side = max(1, round(count ** (1 / 3)))
    nx = ny = side
    nz = max(1, round(count / (nx * ny)))
    lo_y, hi_y = min(g[1] for g in cells), max(g[1] for g in cells)
    centre_y = lo_y + round((hi_y - lo_y) * fraction)
    y0 = max(lo_y, centre_y - ny // 2)     # never under the floor it stands on
    band = [g for g in cells if y0 <= g[1] <= y0 + ny - 1] or [g for g in cells if g[1] == centre_y] or list(cells)
    middle_z = (min(g[2] for g in cells) + max(g[2] for g in cells)) / 2
    first_x = min(g[0] for g in band)
    target = min((g for g in band if g[0] == first_x), key=lambda g: (abs(g[2] - middle_z), g[2]))
    z0 = target[2] - nz // 2
    # Three cells of air: clear of the product at the start, and short enough
    # that the block has not fallen out of line when it arrives.
    x1 = min(g[0] for g in cells) - 4
    return ((x1 - nx + 1, y0, z0), (x1, y0 + ny - 1, z0 + nz - 1)), nx * ny * nz * per_cell


def scene(design, test: str, config: dict[str, Any]) -> dict[str, Any]:
    if test not in TESTS:
        raise ValueError("Unknown motion experiment")
    h = number(config, "cell_size_m", .04, .005, .1)
    duration = number(config, "duration_s", 1.5, .1, MAX_DURATION_S)
    height = number(config, "height_m", .2, .04, MAX_HEIGHT_M) if test == "drop_product" else 0.0
    speed = number(config, "speed_m_s", 1.0, .1, 3.0) if test == "slide_product" else 0.0
    striker_kg = number(config, "striker_kg", 5.0, .5, 200.0) if test == "impact_product" else 0.0
    striker_speed = number(config, "speed_m_s", 8.0, .5, 30.0) if test == "impact_product" else 0.0
    fraction = number(config, "height_fraction", 1.0, 0.0, 1.0) if test == "impact_product" else 0.0
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
    striker = None
    if test == "impact_product":
        box, actual_kg = _striker(placed, h, striker_kg, fraction)
        block = sparse._box_body(STRIKER, box, h, STRIKER_MATERIAL, "")
        block["velocity_m_s"] = [striker_speed, 0.0, 0.0]
        bodies.append(block)
        striker = {"requested_kg": striker_kg, "actual_kg": actual_kg, "speed_m_s": striker_speed,
                   "height_fraction": fraction, "energy_j": .5 * actual_kg * striker_speed**2,
                   "size_m": [(box[1][a] - box[0][a] + 1) * h for a in range(3)]}
    # The declared time is the time simulated, as it always was: a short run is
    # how free fall is checked in mid-air. What a drop needs in order to land and
    # settle is reported beside it, so a run that ended in the air can say so.
    applied_height = lift * h
    fall = sqrt(2 * applied_height / GRAVITY_M_S2) if applied_height else 0.0
    spec = fracture_lab.validate({"algorithm": "lattice", "cell_m": h, "plasticity": "on", "bodies": bodies})
    return {"spec": spec, "matter": matter, "root": root, "shift": shift, "duration_s": duration,
            "height_m": height, "applied_height_m": applied_height, "fall_time_s": fall,
            "speed_m_s": speed, "striker": striker, "mass_kg": summary["measured"]["mass_kg"]}


_render_geometry = sparse.piece_geometry


def _hardest(impacts: Any, best: dict[str, Any] | None, root: str) -> dict[str, Any] | None:
    # The blow to the product as designed. What its pieces then do to one another
    # is in the recording, and is not a reading of the design: a one-cell shard
    # has no bond to break and reports a bar of zero.
    for impact in impacts or []:
        if str(impact.get("struck") or "") != root:
            continue
        if best is None or float(impact.get("closing_speed_m_s") or 0) > float(best.get("closing_speed_m_s") or 0):
            best = {key: impact.get(key) for key in ("by", "struck", "closing_speed_m_s", "threshold_speed_m_s",
                                                      "dent_speed_m_s", "energy_j", "would_break", "would_dent")}
    return best


def run(app: Any, design, test: str, config: dict[str, Any], *, session_factory=None) -> dict[str, Any]:
    setup = scene(design, test, config)
    engine = Path(app.engine_path)
    if not engine.is_file():
        raise ValueError("Physics runner is missing. Build banjo_live_world_run and restart the server with that engine; the test has not run.")
    runs = Path(app.runs_path) / "workshop-motion"
    runs.mkdir(parents=True, exist_ok=True)
    session = workshop_recording.wrap((session_factory or live_session.Session)(engine, setup["spec"], runs))
    fractures = []
    hardest = None
    h = float(setup["matter"]["cell_size_m"])
    deadline = time.monotonic() + 30.0
    try:
        initial = session.send(op="poses")
        snapshot = session.send(op="snapshot").get("snapshot")
        if not isinstance(snapshot, dict):
            raise ValueError("The native engine did not provide geometry verification. Rebuild the runtime before testing.")
        verified = sparse.verify_engine_matter(snapshot, setup["matter"], setup["root"], placement_grid=setup["shift"])
        geometry = dict(verified["render_geometry"])
        _render_geometry(snapshot, h, geometry)     # the striker, which is no part of the product
        state = initial
        while float(state.get("t", 0)) < setup["duration_s"] - 1e-9:
            if time.monotonic() > deadline:
                raise RuntimeError("The simulation exceeded its work budget; no completed result is claimed.")
            before = float(state.get("t", 0))
            state = session.send(op="step", dt=min(1/120, setup["duration_s"]-before), n=1)
            hardest = _hardest(state.get("impacts"), hardest, setup["root"])
            attempts = 0
            while state.get("breakable"):
                attempts += 1
                if attempts > 64 or time.monotonic() > deadline:
                    raise RuntimeError("Material failure did not finish within the test budget; no completed result is claimed.")
                name = str(state["breakable"][0])
                state = session.send(op="fracture", name=name, window_s=.003)
                fractures.append({"name": name, "at_s": float(state.get("t", 0)),
                                  "outcome": str(state.get("outcome") or ""), "pieces": int(state.get("pieces") or 0)})
            if attempts:
                # Whatever was asked about is a new body from here on, broken or
                # not -- one that held comes back as "piece 1" of itself -- and
                # is drawn as the cells it actually has.
                _render_geometry(session.send(op="snapshot").get("snapshot"), h, geometry)
            if not state.get("ok", True):
                raise RuntimeError(str(state.get("error") or "Native simulation refused this step"))
            if float(state.get("t", 0)) <= before and attempts == 0:
                raise RuntimeError("The native simulation stopped advancing; no completed result is claimed.")
        final = session.send(op="poses")
    finally:
        session.close()
    first = trials._body(initial, setup["root"])
    last = trials._body(final, setup["root"])
    pieces = [b for b in final.get("bodies", []) if str(b.get("name") or "").startswith(setup["root"])]
    broke = [f for f in fractures if f["outcome"] == "broke" and f["name"].startswith(setup["root"])]
    dented = [f for f in fractures if f["outcome"] == "dented" and f["name"].startswith(setup["root"])]
    measured = {"clock_s": float(final["t"]), "prototype_present": last is not None,
                "prototype_displacement_m": dist(first["position_m"], last["position_m"]) if first and last else None,
                "fracture_events": len(fractures), "body_count": len(final.get("bodies", [])),
                "outcome": "broke" if broke else "dented" if dented else "held",
                "pieces": len(pieces), "first_break_s": broke[0]["at_s"] if broke else None,
                "hardest_impact": hardest,
                "start_position_m": first.get("position_m") if first else None,
                "end_position_m": last.get("position_m") if last else None}
    limitations = ["Single-material structural solid at the reported grid resolution. A completed run is not a strength certificate."]
    requested = {"height_m": setup["height_m"], "applied_height_m": setup["applied_height_m"],
                 "speed_m_s": setup["speed_m_s"], "duration_s": setup["duration_s"], "cell_size_m": h}
    if test == "drop_product":
        # Whether the run was long enough to see the landing at all, and what would be.
        requested["fall_time_s"] = round(setup["fall_time_s"], 4)
        requested["settled_duration_s"] = round(min(MAX_DURATION_S, setup["fall_time_s"] + SETTLE_S), 2)
        measured["landed"] = hardest is not None
    if setup["striker"]:
        requested["striker"] = setup["striker"]
        requested["speed_m_s"] = setup["striker"]["speed_m_s"]
        limitations.append("The striker is a whole number of iron cells; its actual mass and energy are the ones reported.")
    playback = session.recording(test=test, requested=requested, limitations=limitations)
    playback["geometry"] = geometry
    playback["geometry_basis"] = "verified-native-cells-and-native-pieces"
    playback["fractures"] = fractures
    return {"schema": "banjo.workshop-bench.v1", "test": test, "evidence": "engine-trial", "subject": "selected-product",
            "design_id": design.design_id, "requested": requested, "measured": measured, "playback": playback,
            "prototype": {"root_body": setup["root"], "matter_physics_hash": setup["matter"]["physics_hash"],
                          "matter_cells": setup["matter"]["total_cells"], "engine_grid_verified": True},
            "acceptance": {"status": "observed", "why": "The engine completed this experiment; no pass/fail requirement was declared."},
            "limitations": limitations}
