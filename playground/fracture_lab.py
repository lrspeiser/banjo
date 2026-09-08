"""Fracture lab: instant reruns of the fast fracture lanes on a thin plate.

The owner's test: change the plate's dimensions or the ball's drop height and
see the plate break in 3D again at once. Each lane is a native executable that
follows one CLI contract (plate, cell, ball, drop or speed, offset, support,
duration, output) and writes a banjo.playback.v1 recording whose `report`
carries the lane's own timing. This module maps the panel's parameters to that
contract, runs the executable synchronously under a timeout, registers the
recording as a playground job exactly as scripts/import-playback.py does, and
returns what the panel shows.

The explicit lattice (`banjo_fast_lattice_run`) is offered as the reference
lane so the panel works before the fast lanes exist; it is a comparison
instrument, capped at a few hundred cells and timed, not the product path.

Nothing here changes any solver, criterion or tolerance.
"""
from __future__ import annotations

import json
import math
import re
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

GRAVITY_M_S2 = 9.81
REALTIME_LIMIT = 1.1

# Lanes, in the order the panel lists them. `exe` is looked up next to the
# engine binary; a lane whose executable is absent is shown but disabled.
ALGORITHMS: dict[str, dict[str, Any]] = {
    "algo1": {"exe": "banjo_fracture_algo1", "title": "Algorithm 1: impulse library + Woodbury crack updates",
              "max_cells": 4000, "timeout_s": 60, "contract": "lane"},
    "algo2": {"exe": "banjo_fracture_algo2", "title": "Algorithm 2: Griffith event cascade (no time stepping)",
              "max_cells": 4000, "timeout_s": 60, "contract": "lane"},
    "algo3": {"exe": "banjo_fracture_algo3", "title": "Algorithm 3: precomputed propagators + causal cones (exact)",
              "max_cells": 4000, "timeout_s": 60, "contract": "lane"},
    "lattice": {"exe": "banjo_fast_lattice_run", "title": "Explicit lattice, parallel: every substep, the shared criterion",
                "max_cells": 2400, "timeout_s": 240, "contract": "fast_lattice"},
}

MATERIALS = ("glass", "oak", "iron")
# The strain threshold is what every result before 2026-09-08 used; the
# energy-scaled law derives the critical stretch from the declared fracture
# energy, the horizon and the cell size, so a crack costs the same per unit
# area at every resolution (docs/criterion-energy-scaled-checkpoint.md).
FAILURE_LAWS = ("strain-threshold", "energy-scaled")
# Plastic flow is off by default: with it off every earlier measurement
# reproduces exactly, and the materials that declare a yield strength (iron
# and, as the catalogue actually has it, oak) only deform when it is asked for.
PLASTICITY = ("off", "on")
SUPPORTS = ("ledges", "flat", "clamped")

DEFAULT: dict[str, Any] = {
    "algorithm": "lattice",
    "material": "glass",
    "failure_law": "strain-threshold",
    "plasticity": "off",
    "striker": "iron",
    "plate_m": [0.25, 0.20, 0.01],
    "cell_m": 0.01,
    "ball_m": 0.06,
    "drop_m": 2.0,
    "speed_m_s": None,
    "offset_m": [0.0, 0.0],
    "support": "ledges",
    "duration_s": 2.0,
}

LIMITS = {
    "plate_m": {"min": 0.03, "max": 1.0}, "thickness_m": {"min": 0.002, "max": 0.1},
# The striker scales with the target: a 200 mm ball is a large projectile
# for a 250 mm plate and a pebble against a metre of glass. The cell bound
# rises with it so metre-scale objects can still be meshed coarsely.
    "cell_m": {"min": 0.002, "max": 0.15}, "ball_m": {"min": 0.01, "max": 0.5},
    "drop_m": {"min": 0.0, "max": 5.0}, "speed_m_s": {"min": 0.0, "max": 20.0},
    "duration_s": {"min": 0.2, "max": 6.0},
}

FIELDS = {"algorithm", "material", "striker", "failure_law", "plasticity", "plate_m", "cell_m", "ball_m", "drop_m", "speed_m_s",
          "offset_m", "support", "duration_s", "request_id"}


def _number(value: Any, low: float, high: float, label: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{label} must be a finite number in [{low}, {high}]")
    return float(value)


def cell_counts(plate_m: list[float], cell_m: float) -> tuple[int, int, int]:
    length, width, thickness = plate_m
    return (max(1, round(length / cell_m)), max(1, round(width / cell_m)), max(1, round(thickness / cell_m)))


def validate(spec: Any) -> dict[str, Any]:
    """Check every field against its bound; return a normalised copy with derived values."""
    if not isinstance(spec, dict):
        raise ValueError("Fracture lab request must be an object")
    unknown = set(spec) - FIELDS
    if unknown:
        raise ValueError(f"Unknown fracture lab fields: {sorted(unknown)}")
    result = dict(DEFAULT)
    result.update({k: v for k, v in spec.items() if k != "request_id"})
    if result["algorithm"] not in ALGORITHMS:
        raise ValueError(f"algorithm must be one of {list(ALGORITHMS)}")
    plate = result["plate_m"]
    if not isinstance(plate, list) or len(plate) != 3:
        raise ValueError("plate_m requires length, width and thickness in metres")
    result["plate_m"] = [_number(plate[0], LIMITS["plate_m"]["min"], LIMITS["plate_m"]["max"], "plate length"),
                         _number(plate[1], LIMITS["plate_m"]["min"], LIMITS["plate_m"]["max"], "plate width"),
                         _number(plate[2], LIMITS["thickness_m"]["min"], LIMITS["thickness_m"]["max"], "plate thickness")]
    result["cell_m"] = _number(result["cell_m"], LIMITS["cell_m"]["min"], LIMITS["cell_m"]["max"], "cell size")
    result["ball_m"] = _number(result["ball_m"], LIMITS["ball_m"]["min"], LIMITS["ball_m"]["max"], "ball diameter")
    if result.get("speed_m_s") is not None:
        result["speed_m_s"] = _number(result["speed_m_s"], LIMITS["speed_m_s"]["min"], LIMITS["speed_m_s"]["max"], "impact speed")
        result["drop_m"] = result["speed_m_s"] ** 2 / (2 * GRAVITY_M_S2)
    else:
        result["drop_m"] = _number(result["drop_m"], LIMITS["drop_m"]["min"], LIMITS["drop_m"]["max"], "drop height")
        result["speed_m_s"] = math.sqrt(2 * GRAVITY_M_S2 * result["drop_m"])
    offset = result["offset_m"]
    if not isinstance(offset, list) or len(offset) != 2:
        raise ValueError("offset_m requires two values")
    half = [result["plate_m"][0] / 2, result["plate_m"][1] / 2]
    result["offset_m"] = [_number(offset[0], -half[0], half[0], "offset x"), _number(offset[1], -half[1], half[1], "offset z")]
    if result["support"] not in SUPPORTS:
        raise ValueError(f"support must be one of {list(SUPPORTS)}")
    if result["material"] not in MATERIALS:
        raise ValueError(f"material must be one of {list(MATERIALS)}")
    if result["striker"] not in MATERIALS:
        raise ValueError(f"striker must be one of {list(MATERIALS)}")
    if result["failure_law"] not in FAILURE_LAWS:
        raise ValueError(f"failure_law must be one of {list(FAILURE_LAWS)}")
    if result["plasticity"] not in PLASTICITY:
        raise ValueError(f"plasticity must be one of {list(PLASTICITY)}")
    result["duration_s"] = _number(result["duration_s"], LIMITS["duration_s"]["min"], LIMITS["duration_s"]["max"], "duration")
    nx, ny, nz = cell_counts(result["plate_m"], result["cell_m"])
    result["cells_per_axis"] = [nx, ny, nz]
    result["cells"] = nx * ny * nz
    aspect = max(result["plate_m"][i] / result["cells_per_axis"][i] for i in range(3)) / min(
        result["plate_m"][i] / result["cells_per_axis"][i] for i in range(3))
    result["cell_aspect"] = aspect
    if aspect > 2.0:
        raise ValueError(f"Cells would be {aspect:.1f}:1; the engine assumes cubic cells (aspect <= 2:1). "
                         f"Choose a cell size that divides the thickness.")
    lane = ALGORITHMS[result["algorithm"]]
    if result["cells"] > lane["max_cells"]:
        raise ValueError(f"{result['cells']} cells exceeds this lane's instant-run cap of {lane['max_cells']}; "
                         f"use larger cells or a smaller plate.")
    return result


def executable(engine_path: Path, algorithm: str) -> Path:
    return engine_path.with_name(ALGORITHMS[algorithm]["exe"] + engine_path.suffix)


def describe(engine_path: Path) -> dict[str, Any]:
    """What the panel needs: lanes and whether each is built, defaults, limits."""
    lanes = []
    for key, lane in ALGORITHMS.items():
        path = executable(engine_path, key)
        lanes.append({"id": key, "title": lane["title"], "available": path.is_file(), "max_cells": lane["max_cells"],
                      "timeout_s": lane["timeout_s"], "executable": path.name})
    return {"algorithms": lanes, "default": DEFAULT, "limits": LIMITS, "supports": list(SUPPORTS),
            "materials": list(MATERIALS), "failure_laws": list(FAILURE_LAWS),
            "plasticity": list(PLASTICITY),
            "realtime_limit": REALTIME_LIMIT}


def command(algorithm: str, spec: dict[str, Any], engine_path: Path, output: Path, cache_dir: Path,
            report_path: Path) -> list[str]:
    exe = executable(engine_path, algorithm)
    lane = ALGORITHMS[algorithm]
    L, W, T = spec["plate_m"]
    if lane["contract"] == "lane":
        return [str(exe), "--plate", f"{L:.6g}", f"{W:.6g}", f"{T:.6g}", "--cell", f"{spec['cell_m']:.6g}",
                "--ball", f"{spec['ball_m']:.6g}", "--speed", f"{spec['speed_m_s']:.6g}",
                "--offset", f"{spec['offset_m'][0]:.6g}", f"{spec['offset_m'][1]:.6g}",
                "--support", spec["support"], "--duration", f"{spec['duration_s']:.6g}",
                "--cache", str(cache_dir), "--output", str(output)]
    # The explicit lattice runner: --tile X Y Z with Y the thickness, a ball
    # radius, and a layout that is either two ledges or the ground. It has no
    # pinned-perimeter support, so `clamped` is refused rather than silently
    # run as something else.
    if spec["support"] == "clamped":
        raise ValueError("This lane supports the target on two ledges or on the ground, not clamped edges")
    return [str(exe), "--material", spec["material"], "--ball-material", spec["striker"],
            "--tile", f"{L:.6g}", f"{T:.6g}", f"{W:.6g}", "--cell", f"{spec['cell_m']:.6g}",
            "--ball-radius", f"{spec['ball_m'] / 2:.6g}", "--speed", f"{spec['speed_m_s']:.6g}",
            "--offset", f"{spec['offset_m'][0]:.6g}", f"{spec['offset_m'][1]:.6g}",
            "--layout", "bridge" if spec["support"] == "ledges" else "flat",
            "--settle-s", f"{spec['duration_s']:.6g}",
            # The parallel backend is the same sweep in the same order with the
            # colour stages spread within a stage, so it is bit-identical to the
            # serial one (1,982 bonds, 295 pieces, 3.3813 J on the default scene)
            # at 2.9x the speed: 3.5x realtime instead of 10.1x.
            "--failure-law", spec["failure_law"],
            "--plasticity", spec["plasticity"],
            "--backend", "parallel", "--precision", "double",
            "--record", str(output), "--report", str(report_path)]


def _pick(report: dict[str, Any], *paths: str) -> Any:
    for path in paths:
        node: Any = report
        for key in path.split("."):
            node = node.get(key) if isinstance(node, dict) else None
            if node is None:
                break
        if isinstance(node, (int, float)) and math.isfinite(node):
            return node
    return None


def summary(report: dict[str, Any], wall_s: float, spec: dict[str, Any]) -> dict[str, Any]:
    """The rows the panel shows, read from whichever names the lane uses."""
    simulated = _pick(report, "realtime.simulated_s", "simulated_total_s", "simulated_s", "elapsed_s")
    compute = _pick(report, "realtime.compute_wall_s", "compute_wall_s", "wall_total_s")
    ratio = _pick(report, "realtime.ratio", "realtime_ratio")
    if ratio is None and simulated:
        ratio = wall_s / simulated
    window_ratio = _pick(report, "realtime.fracture_window_ratio")
    lattice_wall = _pick(report, "lattice.wall_s"); lattice_sim = _pick(report, "lattice.simulated_s")
    if window_ratio is None and lattice_wall is not None and lattice_sim:
        window_ratio = lattice_wall / lattice_sim
    return {
        "cells": _pick(report, "cells") or spec["cells"],
        "bonds": _pick(report, "bonds", "lattice.bonds"),
        "precompute_s": _pick(report, "precompute_s"),
        "precompute_cached": report.get("precompute_cached"),
        "compute_wall_s": compute,
        "server_wall_s": wall_s,
        "simulated_s": simulated,
        "realtime_ratio": ratio,
        "realtime_limit": REALTIME_LIMIT,
        "fracture_window_ratio": window_ratio,
        "broken_bonds": _pick(report, "broken_bonds", "lattice.broken_bonds"),
        "components": _pick(report, "components", "handoff.components", "rigid.pieces", "lattice.components"),
        "largest_component_cells": _pick(report, "largest_component_cells", "handoff.largest_piece_cells"),
        "removed_energy_j": _pick(report, "removed_energy_j", "lattice.removed_energy_j"),
        "first_failure_time_s": _pick(report, "first_failure.time_s", "lattice.first_failure_s"),
        "rank_deficient_nodes": _pick(report, "rank_deficient_nodes"),
        "peak_tensile_stretch": _pick(report, "max_tensile_stretch"),
        "came_to_rest": (report.get("rigid") or {}).get("came_to_rest"),
        "contact_impulse_n_s": _pick(report, "contact.impulse_n_s", "lattice.contact.impulse_n_s"),
    }


def run(app: Any, body: Any) -> dict[str, Any]:
    """Validate, run the lane, register the recording as a job, return the summary.

    `app` is the playground application: it provides runs_path, engine_path,
    lock, jobs and playbacks, which is all a job needs to exist.
    """
    if not isinstance(body, dict):
        raise ValueError("Expected a fracture lab request object")
    request_id = body.get("request_id")
    if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", request_id):
        raise ValueError("Invalid request identity")
    spec = validate(body)
    algorithm = spec["algorithm"]
    lane = ALGORITHMS[algorithm]
    exe = executable(app.engine_path, algorithm)
    if not exe.is_file():
        raise ValueError(f"{lane['title']} is not built yet ({exe.name} is missing next to the engine)")
    job_id = uuid.uuid4().hex
    directory = app.runs_path / job_id
    directory.mkdir(parents=True, exist_ok=False)
    cache_dir = app.runs_path.parent / "fracture-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    playback = directory / "playback-00.json"
    report_path = directory / "lane-report.json"
    argv = command(algorithm, spec, app.engine_path, playback, cache_dir, report_path)
    (directory / "fracture-request.json").write_text(json.dumps({"spec": spec, "argv": argv}, indent=1), encoding="utf-8")
    nx, ny, nz = spec["cells_per_axis"]
    name = (f"{spec['material']} {spec['plate_m'][0]*1000:.0f}x{spec['plate_m'][1]*1000:.0f}x"
            f"{spec['plate_m'][2]*1000:.0f} mm, {nx}x{ny}x{nz} = {spec['cells']} cells, "
            f"{spec['ball_m']*1000:.0f} mm {spec['striker']} ball at {spec['speed_m_s']:.2f} m/s, "
            f"{spec['support']}, {spec['failure_law']}")
    started = time.perf_counter()
    case: dict[str, Any] = {"index": 0, "name": name, "package": {}, "status": "pending", "native_scene": False,
                            "playback_available": False, "warnings": [], "error": ""}
    job: dict[str, Any] = {"id": job_id, "status": "running", "message": "Fracture lab run in progress.", "plan": None,
                           "cases": [case], "warnings": [], "timing": {},
                           "fracture": {"algorithm": algorithm, "lane": lane["title"], "spec": spec}}
    try:
        result = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                timeout=lane["timeout_s"], check=False)
        wall = time.perf_counter() - started
        if result.returncode or not playback.is_file():
            reason = (result.stderr or result.stdout).strip().splitlines()
            raise ValueError(f"{lane['title']} refused or failed: {reason[-1][:300] if reason else 'no output'}")
        if playback.stat().st_size > 64 * 1024 * 1024:
            raise ValueError("The recording exceeds the browser's 64 MB budget; shorten the duration or coarsen the plate")
        recording = json.loads(playback.read_text(encoding="utf-8"))
        if recording.get("schema") != "banjo.playback.v1":
            raise ValueError("The lane did not write a banjo.playback.v1 recording")
        report = recording.get("report") or {}
        if not report and report_path.is_file():
            report = json.loads(report_path.read_text(encoding="utf-8"))
        case.update({"status": recording.get("status", "complete"), "report": report, "playback_available": True,
                     "wall_s": round(wall, 3), "error": recording.get("error", "")})
        job["fracture"]["summary"] = summary(report, wall, spec)
        job["fracture"]["wall_s"] = round(wall, 3)
        job["status"] = "complete"
        ratio = job["fracture"]["summary"].get("realtime_ratio")
        job["message"] = (f"{lane['title']}: {spec['cells']} cells in {wall:.3f} s wall"
                          + (f", {ratio:.2f}x of the simulated interaction (limit {REALTIME_LIMIT}x)" if ratio else "")
                          + ". Open the 3D playback tab.")
        with app.lock:
            app.playbacks[(job_id, 0)] = playback
    except subprocess.TimeoutExpired:
        wall = time.perf_counter() - started
        case.update({"status": "error", "error": f"Timed out after {lane['timeout_s']} s", "wall_s": round(wall, 3)})
        job.update({"status": "error", "message": case["error"], "error": case["error"]})
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        wall = time.perf_counter() - started
        case.update({"status": "error", "error": str(exc)[:300], "wall_s": round(wall, 3)})
        job.update({"status": "error", "message": str(exc)[:300], "error": str(exc)[:300]})
    (directory / "job.json").write_text(json.dumps(job, indent=2, allow_nan=False), encoding="utf-8")
    with app.lock:
        app.jobs[job_id] = job
    return {"job_id": job_id, "status": job["status"], "message": job["message"], "wall_s": round(wall, 3),
            "fracture": job["fracture"], "error": job.get("error", "")}
