"""Measure timestep and spatial-resolution convergence of the fracture pipeline.

This is a MEASUREMENT harness, not a fix and not a calibration benchmark.  It
drives `banjo_platform_cli` over declared timestep and mesh ladders and records
the discrete fracture answer, the reported conservation/ledger fields, the
engine's own spring temporal-resolution bound and the wall-clock cost of every
run.  Nothing here changes a material constant or a solver setting other than
`fixed_dt_s` and the per-object `resolution` under study.

Studies
-------
map    Zero-step `--validate` sweep: reports the engine's spring frequency
       bound, the required substeps and whether a run would be temporally
       resolved.  Costs no simulation time.
A      Timestep ladder on the documented three-panel glass/oak/iron fixture.
B      Mesh x timestep ladder on single-material panels.
D      Adaptive damage-integration depth ladder.  `fixed_dt_s` is schema-bounded
       to [1/4800, 1/240], so recursive bisection (`maximum_depth` 0..8, giving
       an effective step down to dt/256) is the only further temporal
       refinement the package format allows.
ctrl   Analytical rigid controls (free flight, zero gravity) over the same
       timestep ladder, as the converging counter-example.

Every study writes `runs.json` (one record per run) and `runs.csv`.
"""
from __future__ import annotations

import argparse
import json
import math
import platform
import subprocess
import time
from pathlib import Path
from typing import Any

from banjo_authoring import EngineCLI, EngineError, catalog, make_object, make_package, write_package

MATERIALS = ("glass", "oak", "iron")
PANEL_PRESET = {"glass": "glass_panel", "oak": "wood_panel", "iron": "iron_panel"}
PANEL_DIMENSIONS_M = [0.24, 0.36, 0.04]
# (nx, ny, nz) keeping the authored 2:3 in-plane aspect. Engine caps each axis
# at 16 and the whole world at 1024 cells.
MESH_LADDER = ([4, 6, 2], [6, 9, 2], [8, 12, 3], [10, 15, 4])
BASE_MESH = [6, 9, 2]

RECORD_KEYS = (
    "broken_links", "damaged_links", "connected_components", "cells", "links", "pinned_cells",
    "initial_energy_j", "mechanical_energy_j", "elastic_energy_j", "fracture_work_j",
    "plastic_work_j", "unseparated_energy_change_j", "unreleased_fracture_energy_j",
    "energy_residual_j", "maximum_observed_axial_strain",
    "maximum_reaction_geometric_extension_discrepancy_m", "summed_spring_impulse_n_s",
    "state_valid", "ticks",
)


def _panel_object(material: str, object_id: int, mesh: list[int], x: float, pin: bool) -> dict[str, Any]:
    return make_object(
        PANEL_PRESET[material], object_id,
        position_m=[x, 0.2, 0.0], dimensions_m=list(PANEL_DIMENSIONS_M),
        resolution=list(mesh), pin_boundary=pin,
    )


def _striker(object_id: int, x: float, z: float, speed: float) -> dict[str, Any]:
    return make_object("iron_ball", object_id, position_m=[x + 0.015, 0.21, z], velocity_m_s=[0.0, 0.0, -speed])


def _adaptive(depth: int | None) -> dict[str, Any] | None:
    """Force bisection to `depth` whenever any damage/plasticity/overshoot moves.

    `on_limit: report` keeps the run alive at the refinement floor instead of
    rolling the tick back, so the floor itself is measurable.
    """
    if depth is None:
        return None
    return {"maximum_depth": depth, "maximum_damage_increment": 1e-6,
            "maximum_plastic_strain_increment": 1e-8,
            "maximum_brittle_opening_overshoot": 1e-8, "on_limit": "report"}


def three_panel_scene(speed: float, dt: float, mesh: list[int] = BASE_MESH,
                      start_z: float = 0.2, pin: bool = True,
                      depth: int | None = None) -> dict[str, Any]:
    """The documented verify_physics.py panel fixture, with mesh/dt exposed."""
    objects: list[dict[str, Any]] = []
    for lane, (material, x) in enumerate((("glass", -0.4), ("oak", 0.0), ("iron", 0.4))):
        objects.append(_panel_object(material, 2 * lane + 1, mesh, x, pin))
        objects.append(_striker(2 * lane + 2, x, start_z, speed))
    return make_package(
        objects, materials=catalog()["materials"],
        name=f"Three-panel convergence fixture at {speed:g} m/s",
        fixed_dt_s=dt, gravity_m_s2=(0.0, -9.81, 0.0),
        ground={"half_length_m": 2.0, "half_width_m": 2.0, "friction": 0.4},
        damage_integration=_adaptive(depth),
    )


def single_panel_scene(material: str, speed: float, dt: float, mesh: list[int],
                       start_z: float = 0.2, pin: bool = True,
                       depth: int | None = None) -> dict[str, Any]:
    """One panel and one striker, so the mesh can be refined past the world cell budget."""
    objects = [_panel_object(material, 1, mesh, 0.0, pin), _striker(2, 0.0, start_z, speed)]
    return make_package(
        objects, materials=catalog()["materials"],
        name=f"Single {material} panel {mesh} at {speed:g} m/s",
        fixed_dt_s=dt, gravity_m_s2=(0.0, -9.81, 0.0),
        ground={"half_length_m": 2.0, "half_width_m": 2.0, "friction": 0.4},
        damage_integration=_adaptive(depth),
    )


def freeflight_scene(material: str, dt: float) -> dict[str, Any]:
    obj = make_object("iron_ball", 1, material=material, name=f"{material} analytical control",
                      position_m=[0.0, 2.0, 0.0], velocity_m_s=[0.0, 4.0, 0.0], spin_rad_s=[0.0, 0.0, 0.0])
    return make_package([obj], materials=[m for m in catalog()["materials"] if m["id"] == material],
                        name=f"Analytical rigid freeflight: {material}", fixed_dt_s=dt,
                        gravity_m_s2=(0.0, -9.81, 0.0), ground=None)


def zero_g_scene(dt: float) -> dict[str, Any]:
    objects = [
        make_object("iron_ball", index, material=material, name=f"{material} zero-g body",
                    position_m=[-1.0 + index, 2.0 + index * 0.2, 0.0],
                    velocity_m_s=[1.0 + index * 0.5, -0.2 * index, 0.25 * index], spin_rad_s=[0.0, 0.0, 0.0])
        for index, material in enumerate(MATERIALS, start=1)
    ]
    return make_package(objects, materials=[m for m in catalog()["materials"] if m["id"] in MATERIALS],
                        name="Zero-gravity rigid control", fixed_dt_s=dt,
                        gravity_m_s2=(0.0, 0.0, 0.0), ground=None)


def bounce_scene(material: str, dt: float, speed: float = 2.0) -> dict[str, Any]:
    """Rigid ball driven into the ground: contact response with no material network.

    Separates contact-solver timestep sensitivity from cohesive-network
    timestep sensitivity, because nothing here can fracture or deform.
    """
    obj = make_object("iron_ball", 1, material=material, name=f"{material} bounce control",
                      position_m=[0.0, 0.10, 0.0], velocity_m_s=[0.0, -speed, 0.0], spin_rad_s=[0.0, 0.0, 0.0])
    return make_package([obj], materials=[m for m in catalog()["materials"] if m["id"] == material],
                        name=f"Rigid contact bounce control: {material}", fixed_dt_s=dt,
                        gravity_m_s2=(0.0, -9.81, 0.0),
                        ground={"half_length_m": 2.0, "half_width_m": 2.0, "friction": 0.4})


def _summarize(report: dict[str, Any]) -> dict[str, Any]:
    events = report.get("fracture_events", []) or []
    record: dict[str, Any] = {key: report.get(key) for key in RECORD_KEYS}
    record["fracture_event_count"] = len(events)
    record["first_event_s"] = min((e["time_s"] for e in events), default=None)
    record["last_event_s"] = max((e["time_s"] for e in events), default=None)
    record["fracture_work_total_j"] = sum(e.get("fracture_work_j", 0.0) for e in events)
    temporal = report.get("temporal_resolution", {}) or {}
    for key in ("resolved", "maximum_frequency_bound_rad_s", "maximum_step_s", "required_substeps"):
        record[f"temporal_{key}"] = temporal.get(key)
    integration = report.get("damage_integration", {}) or {}
    for key in ("mode", "maximum_depth", "deepest_trial", "smallest_accepted_step_s",
                "accepted_substeps", "rejected_trials", "unresolved_substeps",
                "rolled_back_ticks", "accepted_maximum_brittle_opening_overshoot",
                "accepted_maximum_damage_increment"):
        record[f"adaptive_{key}"] = integration.get(key)
    performance = report.get("performance", {}) or {}
    for key in ("step_wall_total_ms", "step_p50_ms", "step_p95_ms", "step_max_ms", "realtime_ratio"):
        record[key] = performance.get(key)
    record["linear_momentum_z_kg_m_s"] = (report.get("linear_momentum_kg_m_s") or [None, None, None])[2]
    record["angular_momentum_norm"] = (
        math.sqrt(sum(c * c for c in report["angular_momentum_kg_m2_s"]))
        if report.get("angular_momentum_kg_m2_s") else None)
    per_object = []
    for item in report.get("material_results", report.get("objects", [])) or []:
        per_object.append({k: item.get(k) for k in (
            "id", "material", "name", "cells", "links", "broken_links", "damaged_links",
            "components", "largest_component_cells", "first_break_s", "first_damage_s",
            "position_m", "velocity_m_s", "step_times_pair_frequency",
            "max_isolated_pair_frequency_rad_s", "plastic_work_j")})
    record["objects"] = per_object
    return record


class Runner:
    def __init__(self, engine: Path, output: Path, timeout_s: float):
        self.engine = EngineCLI(engine, timeout_s=timeout_s)
        self.output = output
        self.packages = output / "packages"
        self.reports = output / "reports"
        self.packages.mkdir(parents=True, exist_ok=True)
        self.reports.mkdir(parents=True, exist_ok=True)
        self.records: list[dict[str, Any]] = []

    def _write(self, package: dict[str, Any], name: str) -> Path:
        path = self.packages / f"{name}.json"
        write_package(package, path)
        return path

    def validate(self, package: dict[str, Any], name: str, tags: dict[str, Any]) -> dict[str, Any]:
        path = self._write(package, name)
        try:
            report = self.engine.validate(path)
            status = "ok"
        except EngineError as error:
            report, status = error.report, f"rejected: {error}"
        (self.reports / f"{name}.validate.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
        record = {"name": name, "mode": "validate", "status": status, **tags, **_summarize(report)}
        self.records.append(record)
        return record

    def run(self, package: dict[str, Any], name: str, steps: int, tags: dict[str, Any]) -> dict[str, Any]:
        path = self._write(package, name)
        start = time.perf_counter()
        try:
            report = self.engine.run(path, steps)
            status = "ok"
        except EngineError as error:
            report = error.report
            status = f"engine_error: {error}"
        except subprocess.TimeoutExpired:
            report = {}
            status = "timeout"
        wall = (time.perf_counter() - start) * 1000.0
        (self.reports / f"{name}.run.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
        record = {"name": name, "mode": "run", "status": status, "steps": steps,
                  "process_wall_ms": round(wall, 1), **tags, **_summarize(report)}
        self.records.append(record)
        print(f"  {name}: {status} broken={record.get('broken_links')} "
              f"components={record.get('connected_components')} wall={wall:.0f} ms", flush=True)
        return record

    def write(self) -> None:
        (self.output / "runs.json").write_text(json.dumps(self.records, indent=1), encoding="utf-8")
        columns: list[str] = []
        for record in self.records:
            for key in record:
                if key != "objects" and key not in columns:
                    columns.append(key)
        lines = [",".join(columns)]
        for record in self.records:
            lines.append(",".join(json.dumps(record.get(c)) if isinstance(record.get(c), (list, dict))
                                  else str(record.get(c, "")) for c in columns))
        (self.output / "runs.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _steps_for(elapsed_s: float, dt: float) -> int:
    return round(elapsed_s / dt)


def study_map(runner: Runner) -> None:
    """Free `--validate` sweep of the engine's own spring resolution bound."""
    print("study map: spring temporal-resolution bound", flush=True)
    for material in MATERIALS:
        for mesh in MESH_LADDER:
            for divisor in (240, 480, 960, 1920, 3840, 4800):
                dt = 1.0 / divisor
                name = f"map_{material}_{mesh[0]}x{mesh[1]}x{mesh[2]}_dt{divisor}"
                runner.validate(single_panel_scene(material, 12.0, dt, mesh), name,
                                {"study": "map", "material": material, "mesh": "x".join(map(str, mesh)),
                                 "dt_divisor": divisor, "dt_s": dt})
    for divisor in (240, 480, 4800):
        runner.validate(three_panel_scene(12.0, 1.0 / divisor), f"map_threepanel_dt{divisor}",
                        {"study": "map", "material": "glass+oak+iron", "mesh": "6x9x2",
                         "dt_divisor": divisor, "dt_s": 1.0 / divisor})


def study_a(runner: Runner, elapsed_s: float, divisors: tuple[int, ...], speeds: tuple[float, ...]) -> None:
    print(f"study A: three-panel fixture, {elapsed_s} s elapsed", flush=True)
    for speed in speeds:
        for divisor in divisors:
            dt = 1.0 / divisor
            steps = _steps_for(elapsed_s, dt)
            if steps > 24000:
                print(f"  skip speed={speed} dt=1/{divisor}: {steps} steps exceeds the 24000 CLI cap", flush=True)
                continue
            runner.run(three_panel_scene(speed, dt), f"A_{speed:g}mps_dt{divisor}", steps,
                       {"study": "A", "material": "glass+oak+iron", "mesh": "6x9x2",
                        "speed_m_s": speed, "dt_divisor": divisor, "dt_s": dt, "elapsed_s": elapsed_s})


def study_b(runner: Runner, elapsed_s: float, divisors: tuple[int, ...], speed: float, pin: bool) -> None:
    tag = "pinned" if pin else "free"
    print(f"study B ({tag}): single-panel mesh x timestep, {elapsed_s} s elapsed", flush=True)
    for material in MATERIALS:
        for mesh in MESH_LADDER:
            for divisor in divisors:
                dt = 1.0 / divisor
                steps = _steps_for(elapsed_s, dt)
                if steps > 24000:
                    continue
                mesh_tag = "x".join(map(str, mesh))
                runner.run(single_panel_scene(material, speed, dt, mesh, pin=pin),
                           f"B_{tag}_{material}_{mesh_tag}_dt{divisor}", steps,
                           {"study": f"B_{tag}", "material": material, "mesh": mesh_tag,
                            "pin_boundary": pin, "speed_m_s": speed, "dt_divisor": divisor,
                            "dt_s": dt, "elapsed_s": elapsed_s})


def study_d(runner: Runner, elapsed_s: float, divisors: tuple[int, ...],
            depths: tuple[int, ...], mesh: list[int], speed: float) -> None:
    print(f"study D: adaptive bisection depth ladder, {elapsed_s} s elapsed", flush=True)
    mesh_tag = "x".join(map(str, mesh))
    for material in MATERIALS:
        for divisor in divisors:
            dt = 1.0 / divisor
            steps = _steps_for(elapsed_s, dt)
            if steps > 24000:
                continue
            for depth in depths:
                runner.run(single_panel_scene(material, speed, dt, mesh, depth=depth),
                           f"D_{material}_{mesh_tag}_dt{divisor}_depth{depth}", steps,
                           {"study": "D", "material": material, "mesh": mesh_tag, "speed_m_s": speed,
                            "depth": depth, "effective_min_dt_s": dt / (2 ** depth),
                            "dt_divisor": divisor, "dt_s": dt, "elapsed_s": elapsed_s})


def study_ctrl(runner: Runner, elapsed_s: float, divisors: tuple[int, ...]) -> None:
    print("study ctrl: analytical rigid controls", flush=True)
    for divisor in divisors:
        dt = 1.0 / divisor
        steps = _steps_for(elapsed_s, dt)
        if steps > 24000:
            continue
        for material in MATERIALS:
            runner.run(freeflight_scene(material, dt), f"ctrl_freefall_{material}_dt{divisor}", steps,
                       {"study": "ctrl_freefall", "material": material, "dt_divisor": divisor,
                        "dt_s": dt, "elapsed_s": elapsed_s})
        runner.run(zero_g_scene(dt), f"ctrl_zerog_dt{divisor}", steps,
                   {"study": "ctrl_zerog", "material": "glass+oak+iron", "dt_divisor": divisor,
                    "dt_s": dt, "elapsed_s": elapsed_s})
        for material in MATERIALS:
            runner.run(bounce_scene(material, dt), f"ctrl_bounce_{material}_dt{divisor}", steps,
                       {"study": "ctrl_bounce", "material": material, "dt_divisor": divisor,
                        "dt_s": dt, "elapsed_s": elapsed_s})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path, help="New output directory")
    parser.add_argument("--studies", default="map,A,B,D,ctrl")
    parser.add_argument("--timeout-s", type=float, default=3600.0)
    parser.add_argument("--a-elapsed-s", type=float, default=3.0)
    # 1/4800 s is the smallest fixed step the v2 package schema admits.
    parser.add_argument("--a-divisors", default="240,480,960,1920,3840,4800")
    parser.add_argument("--a-speeds", default="2,6,12,20")
    parser.add_argument("--b-elapsed-s", type=float, default=0.5)
    parser.add_argument("--b-divisors", default="240,480,960,1920,3840,4800")
    parser.add_argument("--b-speed", type=float, default=12.0)
    parser.add_argument("--d-elapsed-s", type=float, default=0.5)
    parser.add_argument("--d-divisors", default="480,4800")
    parser.add_argument("--d-depths", default="0,1,2,3,4,5,6,7,8")
    parser.add_argument("--d-mesh", default="6,9,2")
    parser.add_argument("--ctrl-elapsed-s", type=float, default=0.5)
    args = parser.parse_args()

    engine = args.engine.resolve()
    output = args.output.resolve()
    if not engine.is_file():
        parser.error(f"engine does not exist: {engine}")
    if output.exists():
        parser.error(f"output directory must be new: {output}")
    output.mkdir(parents=True)

    runner = Runner(engine, output, args.timeout_s)
    wanted = [s.strip() for s in args.studies.split(",") if s.strip()]
    ints = lambda text: tuple(int(v) for v in text.split(",") if v)
    floats = lambda text: tuple(float(v) for v in text.split(",") if v)
    started = time.perf_counter()
    if "map" in wanted:
        study_map(runner)
    if "A" in wanted:
        study_a(runner, args.a_elapsed_s, ints(args.a_divisors), floats(args.a_speeds))
    if "B" in wanted:
        study_b(runner, args.b_elapsed_s, ints(args.b_divisors), args.b_speed, pin=True)
    if "Bfree" in wanted:
        study_b(runner, args.b_elapsed_s, ints(args.b_divisors), args.b_speed, pin=False)
    if "D" in wanted:
        study_d(runner, args.d_elapsed_s, ints(args.d_divisors), ints(args.d_depths),
                [int(v) for v in args.d_mesh.split(",")], args.b_speed)
    if "ctrl" in wanted:
        study_ctrl(runner, args.ctrl_elapsed_s, ints(args.a_divisors))
    runner.write()
    meta = {"engine": str(engine), "studies": wanted, "host": platform.platform(),
            "python": platform.python_version(), "total_wall_s": round(time.perf_counter() - started, 1),
            "runs": len(runner.records)}
    (output / "environment.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    print(json.dumps(meta, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
