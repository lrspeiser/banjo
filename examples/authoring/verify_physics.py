"""Run a reproducible, headless smoke suite for generated material scenes.

This is an authoring/client check, not a calibration benchmark.  It keeps
analytical free-flight controls separate from experimental network outcomes.
The output directory must be new so that packages and reports are immutable
inputs for a later visual-studio review.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
from typing import Any

from banjo_authoring import EngineCLI, EngineError, catalog, make_object, make_package, write_package


MATERIAL_IDS = ("glass", "oak", "iron")
ANALYTICAL_DT = 1 / 480
ZERO_G_DT = 1 / 480
PANEL_DT = 1 / 480
REFINED_DT = 1 / 960
CONTROL_STEPS = 240
ZERO_G_STEPS = 240
SCENE_STEPS = 1440  # 3 seconds at the default 1/480 s authored step.
REFINEMENT_ELAPSED_S = 3.0


def _json_write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _material_records(ids: tuple[str, ...] | list[str] | None = None) -> list[dict[str, Any]]:
    wanted = set(ids or MATERIAL_IDS)
    return [material for material in catalog()["materials"] if material["id"] in wanted]


def _report_objects(report: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {int(item["id"]): item for item in report.get("objects", [])}


def _mass_sum(report: dict[str, Any]) -> float:
    return sum(float(item["mass_kg"]) for item in report.get("objects", []))


def _momentum_energy(report: dict[str, Any]) -> tuple[tuple[float, float, float], float]:
    momentum = [0.0, 0.0, 0.0]
    kinetic = 0.0
    for item in report.get("objects", []):
        mass = float(item["mass_kg"])
        velocity = _vec(item["velocity_m_s"])
        for axis in range(3):
            momentum[axis] += mass * velocity[axis]
        kinetic += 0.5 * mass * sum(component * component for component in velocity)
    return (momentum[0], momentum[1], momentum[2]), kinetic


def _object_state(report: dict[str, Any], object_id: int) -> dict[str, Any]:
    objects = _report_objects(report)
    _assert(object_id in objects, f"report has no object {object_id}")
    return objects[object_id]


def _vec(value: Any) -> tuple[float, float, float]:
    _assert(isinstance(value, list) and len(value) == 3, f"expected 3-vector, got {value!r}")
    return float(value[0]), float(value[1]), float(value[2])


def _vec_error(actual: tuple[float, float, float], expected: tuple[float, float, float]) -> float:
    return max(abs(a - b) for a, b in zip(actual, expected))


def _run_package(
    engine: EngineCLI,
    package: dict[str, Any],
    package_path: Path,
    report_path: Path,
    steps: int,
) -> dict[str, Any]:
    write_package(package, package_path)
    report = engine.run(package_path, steps)
    _json_write(report_path, report)
    _assert(report.get("fault", "") == "", f"engine fault for {package_path.name}: {report.get('fault')}")
    _assert(int(report.get("ticks", -1)) == steps, f"short run for {package_path.name}")
    return report


def _rigid_control(material_id: str, gravity: tuple[float, float, float]) -> dict[str, Any]:
    obj = make_object(
        "iron_ball",
        1,
        name=f"{material_id} analytical control",
        material=material_id,
        position_m=[0.0, 2.0, 0.0],
        velocity_m_s=[0.0, 4.0, 0.0],
        spin_rad_s=[0.0, 0.0, 0.0],
    )
    return make_package(
        [obj],
        materials=_material_records([material_id]),
        name=f"Analytical rigid freeflight: {material_id}",
        fixed_dt_s=ANALYTICAL_DT,
        gravity_m_s2=gravity,
        ground=None,
    )


def _zero_g_package() -> dict[str, Any]:
    objects = []
    for index, material_id in enumerate(MATERIAL_IDS, start=1):
        objects.append(
            make_object(
                "iron_ball",
                index,
                name=f"{material_id} zero-g body",
                material=material_id,
                position_m=[-1.0 + index, 2.0 + index * 0.2, 0.0],
                velocity_m_s=[1.0 + index * 0.5, -0.2 * index, 0.25 * index],
                spin_rad_s=[0.0, 0.0, 0.0],
            )
        )
    return make_package(
        objects,
        materials=_material_records(),
        name="Zero-gravity rigid freeflight and mass control",
        fixed_dt_s=ZERO_G_DT,
        gravity_m_s2=(0.0, 0.0, 0.0),
        ground=None,
    )


def _panel_scene(speed: float, fixed_dt_s: float = PANEL_DT) -> dict[str, Any]:
    objects = []
    for lane, (preset, x) in enumerate(
        (("glass_panel", -0.4), ("wood_panel", 0.0), ("iron_panel", 0.4))
    ):
        objects.append(make_object(preset, 2 * lane + 1, position_m=[x, 0.2, 0.0]))
        objects.append(
            make_object(
                "iron_ball",
                2 * lane + 2,
                position_m=[x + 0.015, 0.21, 0.2],
                velocity_m_s=[0.0, 0.0, -speed],
            )
        )
    return make_package(
        objects,
        materials=catalog()["materials"],
        name=f"Generated glass oak iron panels at {speed:g} m/s",
        fixed_dt_s=fixed_dt_s,
        gravity_m_s2=(0.0, -9.81, 0.0),
        ground={"half_length_m": 2.0, "half_width_m": 2.0, "friction": 0.4},
    )


def _knife_tomato_scene(fixed_dt_s: float = PANEL_DT) -> dict[str, Any]:
    tomato = make_object(
        "tomato_proxy", 1, position_m=[0.0, 0.085, 0.0], velocity_m_s=[0.0, 0.0, 0.0]
    )
    knife = make_object(
        "knife",
        2,
        # Keep the catalog fixture's lateral placement and authored height;
        # only launch it downward for the supported cutting experiment.
        velocity_m_s=[0.0, -4.0, 0.0],
    )
    return make_package(
        [tomato, knife],
        materials=catalog()["materials"],
        name="Generated knife and tomato proxy",
        fixed_dt_s=fixed_dt_s,
        gravity_m_s2=(0.0, -9.81, 0.0),
        ground={"half_length_m": 2.0, "half_width_m": 2.0, "friction": 0.4},
    )


def _analytical_controls(engine: EngineCLI, root: Path) -> dict[str, Any]:
    results: dict[str, Any] = {}
    acceleration = (0.0, -9.81, 0.0)
    elapsed = ANALYTICAL_DT * CONTROL_STEPS
    for material_id in MATERIAL_IDS:
        package = _rigid_control(material_id, acceleration)
        package_path = root / "controls" / f"freefall_{material_id}.json"
        report_path = root / "controls" / f"freefall_{material_id}.report.json"
        package_path.parent.mkdir(parents=True, exist_ok=True)
        report = _run_package(engine, package, package_path, report_path, CONTROL_STEPS)
        initial = (0.0, 2.0, 0.0)
        initial_velocity = (0.0, 4.0, 0.0)
        expected_position = tuple(
            initial[i] + initial_velocity[i] * elapsed + 0.5 * acceleration[i] * elapsed * elapsed
            for i in range(3)
        )
        expected_velocity = tuple(initial_velocity[i] + acceleration[i] * elapsed for i in range(3))
        state = _object_state(report, 1)
        position_error = _vec_error(_vec(state["position_m"]), expected_position)
        velocity_error = _vec_error(_vec(state["velocity_m_s"]), expected_velocity)
        # The tolerance includes a small reporting allowance and a first-order
        # fixed-step term, so changing dt makes the asserted bound explicit.
        position_tolerance = 1e-5 + 0.6 * max(map(abs, acceleration)) * elapsed * ANALYTICAL_DT
        velocity_tolerance = 1e-4
        expected_mass = _material_records([material_id])[0]["density_kg_m3"] * (4.0 / 3.0) * math.pi * 0.04**3
        mass_error = abs(float(state["mass_kg"]) - expected_mass)
        _assert(position_error <= position_tolerance, f"{material_id} freefall position error {position_error}")
        _assert(velocity_error <= velocity_tolerance, f"{material_id} freefall velocity error {velocity_error}")
        _assert(mass_error <= 1e-10 * max(1.0, expected_mass), f"{material_id} mass changed")
        results[material_id] = {
            "pass": True,
            "elapsed_s": elapsed,
            "position_error_m": position_error,
            "position_tolerance_m": position_tolerance,
            "velocity_error_m_s": velocity_error,
            "velocity_tolerance_m_s": velocity_tolerance,
            "mass_kg": state["mass_kg"],
            "expected_mass_kg": expected_mass,
            "fracture_count": len(report.get("fracture_events", [])),
        }
    return results


def _zero_g_control(engine: EngineCLI, root: Path) -> dict[str, Any]:
    package = _zero_g_package()
    package_path = root / "controls" / "zero_g.json"
    report_path = root / "controls" / "zero_g.report.json"
    package_path.parent.mkdir(parents=True, exist_ok=True)
    # Write explicitly before validate so the initial mass audit is from the
    # exact package consumed by both calls.
    write_package(package, package_path)
    initial_report = engine.validate(package_path)
    report = engine.run(package_path, ZERO_G_STEPS)
    _json_write(root / "controls" / "zero_g.initial.report.json", initial_report)
    _json_write(report_path, report)
    elapsed = ZERO_G_DT * ZERO_G_STEPS
    initial_by_id = _report_objects(initial_report)
    final_by_id = _report_objects(report)
    mass_initial = _mass_sum(initial_report)
    mass_final = _mass_sum(report)
    _assert(abs(mass_final - mass_initial) <= 1e-10 * max(1.0, mass_initial), "zero-g mass changed")
    initial_momentum, initial_kinetic = _momentum_energy(initial_report)
    final_momentum, final_kinetic = _momentum_energy(report)
    _assert(_vec_error(final_momentum, initial_momentum) <= 1e-10 * max(1.0, max(map(abs, initial_momentum))), "zero-g momentum changed")
    _assert(abs(final_kinetic - initial_kinetic) <= 1e-10 * max(1.0, initial_kinetic), "zero-g kinetic energy changed")
    bodies: dict[str, Any] = {}
    for index, material_id in enumerate(MATERIAL_IDS, start=1):
        p0 = _vec(initial_by_id[index]["position_m"])
        v0 = _vec(initial_by_id[index]["velocity_m_s"])
        expected = tuple(p0[i] + v0[i] * elapsed for i in range(3))
        actual = _vec(final_by_id[index]["position_m"])
        error = _vec_error(actual, expected)
        tolerance = 2e-5
        _assert(error <= tolerance, f"zero-g body {index} transport error {error}")
        _assert(_vec_error(_vec(final_by_id[index]["velocity_m_s"]), v0) <= 1e-10, f"zero-g body {index} velocity changed")
        bodies[material_id] = {"position_error_m": error, "position_tolerance_m": tolerance}
    return {
        "pass": True,
        "elapsed_s": elapsed,
        "mass_initial_kg": mass_initial,
        "mass_final_kg": mass_final,
        "mass_error_kg": abs(mass_final - mass_initial),
        "momentum_initial_kg_m_s": initial_momentum,
        "momentum_final_kg_m_s": final_momentum,
        "kinetic_initial_j": initial_kinetic,
        "kinetic_final_j": final_kinetic,
        "bodies": bodies,
        "fracture_count": len(report.get("fracture_events", [])),
    }


def _admit_presets(engine: EngineCLI, root: Path) -> dict[str, Any]:
    preset_root = root / "presets"
    report_root = root / "reports" / "presets"
    preset_root.mkdir(parents=True, exist_ok=True)
    report_root.mkdir(parents=True, exist_ok=True)
    results: dict[str, Any] = {}
    for index, preset_name in enumerate(catalog()["object_presets"], start=1):
        obj = make_object(preset_name, index)
        package = make_package(
            [obj], materials=catalog()["materials"], name=f"Preset admission: {preset_name}", ground=None
        )
        package_path = preset_root / f"{preset_name}.json"
        report_path = report_root / f"{preset_name}.report.json"
        write_package(package, package_path)
        initial_report = engine.validate(package_path)
        report = engine.run(package_path, 8)
        _json_write(report_root / f"{preset_name}.initial.report.json", initial_report)
        _json_write(report_path, report)
        _assert(abs(_mass_sum(report) - _mass_sum(initial_report)) <= 1e-10 * max(1.0, _mass_sum(initial_report)), f"mass changed for {preset_name}")
        _assert(int(report.get("ticks", -1)) == 8, f"short preset run for {preset_name}")
        results[preset_name] = {
            "pass": True,
            "mass_kg": _mass_sum(report),
            "fracture_count": len(report.get("fracture_events", [])),
            "cells": report.get("cells"),
            "links": report.get("links"),
        }
    return results


def _scene_run(
    engine: EngineCLI,
    package: dict[str, Any],
    package_root: Path,
    report_root: Path,
    name: str,
    steps: int,
    repeats: int = 1,
    write_package_file: bool = True,
) -> dict[str, Any]:
    package_root.mkdir(parents=True, exist_ok=True)
    report_root.mkdir(parents=True, exist_ok=True)
    package_path = package_root / f"{name}.json"
    if write_package_file:
        write_package(package, package_path)
    initial_report = engine.validate(package_path)
    _json_write(report_root / f"{name}.initial.report.json", initial_report)
    reports = []
    for run_index in range(repeats):
        report_path = report_root / f"{name}.run{run_index + 1}.report.json"
        try:
            report = engine.run(package_path, steps)
        except EngineError as error:
            _json_write(report_path, error.report)
            return {
                "status": "runtime_error",
                "package": str(package_path),
                "steps": steps,
                "fixed_dt_s": package["fixed_dt_s"],
                "requested_elapsed_s": steps * float(package["fixed_dt_s"]),
                "elapsed_s": None,
                "error": str(error),
                "mass_initial_kg": _mass_sum(initial_report),
                "fracture_count": None,
                "objects": [],
                "timings": [],
            }
        _json_write(report_path, report)
        _assert(int(report.get("ticks", -1)) == steps, f"short run for {name}")
        _assert(abs(_mass_sum(report) - _mass_sum(initial_report)) <= 1e-10 * max(1.0, _mass_sum(initial_report)), f"mass changed for {name}")
        reports.append(report)
    first = reports[0]
    discrete_keys = ("ticks", "cells", "links", "broken_links", "damaged_links", "connected_components")
    discrete = [{key: report.get(key) for key in discrete_keys} for report in reports]
    _assert(all(item == discrete[0] for item in discrete[1:]), f"repeated run discrete result changed for {name}")
    initial_objects = _report_objects(initial_report)
    final_objects = _report_objects(first)
    objects = []
    for object_id, final_object in sorted(final_objects.items()):
        initial_object = initial_objects[object_id]
        broken = int(final_object.get("broken_links", 0))
        damaged = int(final_object.get("damaged_links", 0))
        objects.append(
            {
                "id": object_id,
                "name": final_object.get("name"),
                "material": final_object.get("material"),
                "mass_initial_kg": initial_object.get("mass_kg"),
                "mass_final_kg": final_object.get("mass_kg"),
                "broken_links": broken,
                "softened_live_links": max(0, damaged - broken),
                "damaged_links_including_broken": damaged,
                "components": final_object.get("components", 1),
                "cells": final_object.get("cells", 1),
                "position_m": final_object.get("position_m"),
                "velocity_m_s": final_object.get("velocity_m_s"),
            }
        )
    performance = [report.get("performance", {}) for report in reports]
    return {
        "status": "ok",
        "package": str(package_path),
        "steps": steps,
        "fixed_dt_s": package["fixed_dt_s"],
        "elapsed_s": steps * float(package["fixed_dt_s"]),
        "mass_kg": _mass_sum(first),
        "mass_initial_kg": _mass_sum(initial_report),
        "fracture_count": len(first.get("fracture_events", [])),
        "broken_links": first.get("broken_links"),
        "damaged_links": first.get("damaged_links"),
        "objects": objects,
        "repeat_discrete_results": discrete,
        "timings": [
            {
                "step_p95_ms": item.get("step_p95_ms"),
                "step_wall_total_ms": item.get("step_wall_total_ms"),
                "sample_count": item.get("sample_count"),
            }
            for item in performance
        ],
    }


def _network_ball_drop_scene() -> dict[str, Any]:
    objects = []
    for index, (preset, x) in enumerate(
        (("glass_matter_ball", -0.20), ("wood_matter_ball", 0.0), ("iron_matter_ball", 0.20)),
        start=1,
    ):
        objects.append(
            make_object(
                preset,
                index,
                position_m=[x, 0.50, 0.0],
                velocity_m_s=[0.0, 0.0, 0.0],
                spin_rad_s=[0.0, 0.0, 0.0],
            )
        )
    return make_package(
        objects,
        materials=catalog()["materials"],
        name="Generated mixed glass oak iron network ball drop",
        fixed_dt_s=PANEL_DT,
        gravity_m_s2=(0.0, -9.81, 0.0),
        ground={"half_length_m": 2.0, "half_width_m": 2.0, "friction": 0.4},
    )


def _ground_rest_control_scene() -> dict[str, Any]:
    objects = []
    for index, (material_id, x) in enumerate(zip(MATERIAL_IDS, (-0.20, 0.0, 0.20)), start=1):
        objects.append(
            make_object(
                "iron_ball",
                index,
                material=material_id,
                name=f"{material_id.capitalize()} rigid ball",
                position_m=[x, 0.040, 0.0],
                velocity_m_s=[0.0, 0.0, 0.0],
                spin_rad_s=[0.0, 0.0, 0.0],
            )
        )
    return make_package(
        objects,
        materials=_material_records(),
        name="Ground-supported rigid rest control",
        fixed_dt_s=PANEL_DT,
        gravity_m_s2=(0.0, -0.01, 0.0),
        ground={"half_length_m": 2.0, "half_width_m": 2.0, "friction": 0.4},
    )


def _generated_scenes(engine: EngineCLI, root: Path) -> dict[str, Any]:
    scene_root = root / "scenes"
    report_root = root / "reports" / "scenes"
    scene_root.mkdir(parents=True, exist_ok=True)
    report_root.mkdir(parents=True, exist_ok=True)
    # This directory is intentionally created before the longer scene runs so
    # a visual-studio reviewer can inspect packages while the suite continues.
    print(f"GENERATED_SCENE_DIR={scene_root.resolve()}", flush=True)
    results: dict[str, Any] = {"panels": {}, "knife_tomato": {}, "refinement": {}}
    scene_packages = {
        "panels_2mps": _panel_scene(2.0),
        "panels_6mps": _panel_scene(6.0),
        "panels_12mps": _panel_scene(12.0),
        "knife_tomato": _knife_tomato_scene(),
        "network_ball_drop": _network_ball_drop_scene(),
        "ground_rest_control": _ground_rest_control_scene(),
    }
    for name, package in scene_packages.items():
        write_package(package, scene_root / f"{name}.json")
    for speed in (2.0, 6.0, 12.0):
        results["panels"][f"{speed:g}mps"] = _scene_run(
            engine, scene_packages[f"panels_{speed:g}mps"], scene_root, report_root, f"panels_{speed:g}mps", SCENE_STEPS, repeats=3, write_package_file=False
        )
    knife_package = scene_packages["knife_tomato"]
    results["knife_tomato"] = _scene_run(
        engine, knife_package, scene_root, report_root, "knife_tomato", SCENE_STEPS, repeats=3, write_package_file=False
    )
    results["network_ball_drop"] = _scene_run(
        engine,
        scene_packages["network_ball_drop"],
        scene_root,
        report_root,
        "network_ball_drop",
        SCENE_STEPS,
        repeats=3,
        write_package_file=False,
    )
    rest_result = _scene_run(
        engine,
        scene_packages["ground_rest_control"],
        scene_root,
        report_root,
        "ground_rest_control",
        SCENE_STEPS,
        repeats=1,
        write_package_file=False,
    )
    rest_initial_report = json.loads((report_root / "ground_rest_control.initial.report.json").read_text(encoding="utf-8"))
    rest_state = _object_state(rest_initial_report, 1)
    rest_height = float(_vec(rest_state["position_m"])[1])
    final_report = json.loads((report_root / "ground_rest_control.run1.report.json").read_text(encoding="utf-8"))
    final_heights = {
        str(object_id): float(_vec(item["position_m"])[1])
        for object_id, item in _report_objects(final_report).items()
    }
    support_tolerance = 2e-3
    _assert(all(height >= 0.04 - support_tolerance for height in final_heights.values()), "ground rest control penetrated the support")
    # The report is an observed support check; initial validation only confirms
    # the package's starting state and keeps the ground-material choice visible.
    rest_result["initial_center_y_m"] = rest_height
    rest_result["final_center_y_m"] = final_heights
    rest_result["support_clearance_m"] = {object_id: height - 0.04 for object_id, height in final_heights.items()}
    rest_result["support_tolerance_m"] = support_tolerance
    rest_result["ground_material_id"] = catalog()["materials"][0]["id"]
    results["ground_rest_control"] = rest_result

    for name, factory in (("panel12", lambda dt: _panel_scene(12.0, dt)), ("knife_tomato", _knife_tomato_scene)):
        refinements = {}
        for label, dt in (("1_480", PANEL_DT), ("1_960", REFINED_DT)):
            package = factory(dt)
            steps = round(REFINEMENT_ELAPSED_S / dt)
            refinements[label] = _scene_run(
                engine, package, root / "refinement", root / "reports" / "refinement", f"{name}_{label}", steps, repeats=1
            )
        coarse = refinements["1_480"]
        fine = refinements["1_960"]
        refinements["mass_delta_kg"] = abs(float(coarse["mass_kg"]) - float(fine["mass_kg"]))
        refinements["fracture_count_delta"] = int(fine["fracture_count"]) - int(coarse["fracture_count"])
        results["refinement"][name] = refinements
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", required=True, type=Path, help="Path to banjo_platform_cli")
    parser.add_argument("--output", required=True, type=Path, help="New output directory; must not exist")
    args = parser.parse_args()
    engine_path = args.engine.resolve()
    output = args.output.resolve()
    if not engine_path.is_file():
        parser.error(f"engine does not exist: {engine_path}")
    if output.exists():
        parser.error(f"output directory must be new: {output}")
    output.mkdir(parents=True)

    capabilities = engine_path
    engine = EngineCLI(capabilities)
    summary: dict[str, Any] = {
        "status": "PASS_ANALYTICAL_AND_ADMISSION_GATES_ONLY",
        "realism_status": "NOT_PASSED_EXPERIMENTAL_FRACTURE_CONVERGENCE",
        "engine": str(engine_path),
        "output": str(output),
        "catalog_source": str(Path(__file__).with_name("presets.json").resolve()),
        "analytical_controls": _analytical_controls(engine, output),
        "zero_gravity_control": _zero_g_control(engine, output),
        "preset_admission": _admit_presets(engine, output),
        "generated_scenes": _generated_scenes(engine, output),
        "realism_gaps": [
            "The network is an experimental central-force directional lattice, not a calibrated continuum.",
            "Contact stiffness is excluded from the temporal-resolution diagnostic; unresolved wave peaks remain possible.",
            "Cell-sphere contact proxies leave subcell gaps and blocky skins are derived render data.",
            "There is no fluid/pulp, skin pressure, full shear/compression damage, hinge failure, or thermal-mechanical coupling.",
            "Glass/oak fracture counts are observations of the current law and discretization, not real-world ranking claims.",
        ],
    }
    def runtime_failures(value: Any) -> list[str]:
        if not isinstance(value, dict):
            return []
        found = [value["package"]] if value.get("status") == "runtime_error" else []
        return found + [item for child in value.values() for item in runtime_failures(child)]
    failures = runtime_failures(summary["generated_scenes"])
    summary["runtime_failures"] = failures
    summary["runtime_status"] = "FAIL" if failures else "PASS"
    _json_write(output / "summary.json", summary)
    print(json.dumps({"summary": str(output / 'summary.json'), "status": summary["status"], "runtime_status": summary["runtime_status"], "realism_status": summary["realism_status"]}, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(json.dumps({"status": "FAIL", "error": str(error)}), file=sys.stderr)
        raise
