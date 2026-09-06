"""Measure material-network load growth and contact behavior without tuning physics.

The matrix uses the checked-in glass/oak/iron matter-ball fixtures at several
resolutions.  It writes every package and raw CLI report; this script does not
run automatically when imported.  The output directory must be new.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from banjo_authoring import EngineCLI, EngineError, catalog, make_object, make_package, write_package


MATERIALS = ("glass", "oak", "iron")
PRESETS = dict(zip(MATERIALS, ("glass_matter_ball", "wood_matter_ball", "iron_matter_ball")))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def objects(report: dict[str, Any]) -> list[dict[str, Any]]:
    return list(report.get("objects", []))


def mass(report: dict[str, Any]) -> float:
    return sum(float(item["mass_kg"]) for item in objects(report))


def package_for(resolution: int, sets: int, *, gravity: tuple[float, float, float], ground: bool) -> dict[str, Any]:
    declarations = []
    for group in range(sets):
        offset = -0.4 if group == 0 else 0.4
        for index, material in enumerate(MATERIALS):
            declarations.append(
                make_object(
                    PRESETS[material],
                    group * 3 + index + 1,
                    name=f"{material} load set {group + 1}",
                    position_m=[offset + (-0.2 + 0.2 * index), 0.45, 0.0],
                    velocity_m_s=[0.0, 0.0, 0.0],
                    spin_rad_s=[0.0, 0.0, 0.0],
                    resolution=[resolution, resolution, resolution],
                )
            )
    return make_package(
        declarations,
        materials=catalog()["materials"],
        name=f"Contact load matrix {'ground' if ground else 'zero-g'} r{resolution} sets{sets}",
        fixed_dt_s=1 / 480,
        gravity_m_s2=gravity,
        ground={"half_length_m": 2.0, "half_width_m": 2.0, "friction": 0.4} if ground else None,
    )


def frame_summary(report: dict[str, Any]) -> dict[str, Any]:
    resolution = report.get("temporal_resolution", {})
    performance = report.get("performance", {})
    contact_keys = (
        "ball_contact_callbacks",
        "ball_contact_events",
        "summed_spring_impulse_n_s",
        "maximum_reaction_geometric_extension_discrepancy_m",
    )
    contact = {key: report[key] for key in contact_keys if key in report}
    return {
        "status": "ok" if not report.get("fault") else "fault",
        "ticks": report.get("ticks"),
        "elapsed_s": report.get("elapsed_s"),
        "mass_kg": mass(report),
        "cells": report.get("cells"),
        "links": report.get("links"),
        "broken_links": report.get("broken_links"),
        "damaged_links": report.get("damaged_links"),
        "connected_components": report.get("connected_components"),
        "mechanical_energy_j": report.get("mechanical_energy_j"),
        "elastic_energy_j": report.get("elastic_energy_j"),
        "energy_residual_j": report.get("energy_residual_j"),
        "unseparated_energy_change_j": report.get("unseparated_energy_change_j"),
        "maximum_observed_axial_strain": report.get("maximum_observed_axial_strain"),
        "contact_diagnostics": contact,
        "contact_budget": report.get("contact_budget"),
        "temporal_resolution": resolution,
        "performance": {
            key: performance.get(key)
            for key in ("step_p95_ms", "step_wall_total_ms", "sample_count", "realtime_ratio")
            if key in performance
        },
        "objects": [
            {
                "id": item.get("id"),
                "material": item.get("material"),
                "mass_kg": item.get("mass_kg"),
                "cells": item.get("cells", 1),
                "links": item.get("links", 0),
                "components": item.get("components", 1),
                "broken_links": item.get("broken_links", 0),
                "damaged_links": item.get("damaged_links", 0),
                "position_m": item.get("position_m"),
                "velocity_m_s": item.get("velocity_m_s"),
            }
            for item in objects(report)
        ],
    }


def run_case(
    engine: EngineCLI,
    package: dict[str, Any],
    package_path: Path,
    report_root: Path,
    seconds: list[float],
    repeats: int,
    resolution: int,
    sets: int,
    variant: str,
) -> dict[str, Any]:
    write_package(package, package_path)
    admission_path = report_root / f"{package_path.stem}.admission.json"
    try:
        admission = engine.validate(package_path)
        write_json(admission_path, admission)
    except EngineError as error:
        write_json(admission_path, error.report)
        return {
            "status": "admission_failed",
            "variant": variant,
            "resolution": resolution,
            "sets": sets,
            "candidate_cells": sets * 3 * resolution**3,
            "error": str(error),
            "package": str(package_path),
        }

    baseline_mass = mass(admission)
    baseline = frame_summary(admission)
    stages = []
    for seconds_value in seconds:
        steps = round(seconds_value / float(package["fixed_dt_s"]))
        runs = []
        for repeat in range(1, repeats + 1):
            report_path = report_root / f"{package_path.stem}.{seconds_value:g}s.run{repeat}.json"
            try:
                report = engine.run(package_path, steps)
                write_json(report_path, report)
                run = frame_summary(report)
                run["mass_error_kg"] = abs(run["mass_kg"] - baseline_mass)
                run["mass_retained"] = run["mass_error_kg"] <= 1e-10 * max(1.0, baseline_mass)
                run["steps_requested"] = steps
                run["report"] = str(report_path)
            except EngineError as error:
                write_json(report_path, error.report)
                run = {"status": "runtime_error", "error": str(error), "report": str(report_path)}
            runs.append(run)
        stages.append({"seconds": seconds_value, "steps": steps, "runs": runs})
    return {
        "status": "completed" if all(run["status"] == "ok" for stage in stages for run in stage["runs"]) else "runtime_failed",
        "variant": variant,
        "resolution": resolution,
        "sets": sets,
        "candidate_cells": sets * 3 * resolution**3,
        "admission": baseline,
        "actual_cells": baseline.get("cells"),
        "actual_links": baseline.get("links"),
        "package": str(package_path),
        "stages": stages,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", required=True, type=Path, help="Path to banjo_platform_cli")
    parser.add_argument("--output", required=True, type=Path, help="New output directory; must not exist")
    parser.add_argument("--seconds", nargs="+", type=float, default=[0.05, 0.5], help="Durations to run (default: 0.05 0.5)")
    parser.add_argument("--repeats", type=int, default=3, help="Fresh CLI repeats per stage (default: 3)")
    args = parser.parse_args()
    engine_path = args.engine.resolve()
    output = args.output.resolve()
    if not engine_path.is_file():
        parser.error(f"engine does not exist: {engine_path}")
    if output.exists():
        parser.error(f"output directory must be new: {output}")
    if args.repeats < 1 or args.repeats > 10:
        parser.error("--repeats must be 1..10")
    if any(not math.isfinite(seconds) or seconds <= 0 or seconds > 60 or round(seconds * 480) < 1 for seconds in args.seconds):
        parser.error("--seconds values must be finite, <=60 and round to at least one 1/480 s step")
    if len({round(seconds * 480) for seconds in args.seconds}) != len(args.seconds):
        parser.error("--seconds values must round to distinct step counts")
    output.mkdir(parents=True)
    package_root = output / "packages"
    report_root = output / "reports"
    engine = EngineCLI(engine_path)
    cases = []
    for resolution in (3, 5, 7):
        sets = 2 if resolution < 7 else 1
        for variant, gravity, ground in (
            ("ground", (0.0, -9.81, 0.0), True),
            ("zero_g_no_ground", (0.0, 0.0, 0.0), False),
        ):
            package = package_for(resolution, sets, gravity=gravity, ground=ground)
            stem = f"{variant}_r{resolution}_sets{sets}"
            cases.append(
                run_case(
                    engine,
                    package,
                    package_root / f"{stem}.json",
                    report_root,
                    args.seconds,
                    args.repeats,
                    resolution,
                    sets,
                    variant,
                )
            )
    failures = sum(case["status"] != "completed" for case in cases)
    summary = {
        "status": "FAILED_CONTACT_LOAD_MATRIX" if failures else "COMPLETED_CONTACT_LOAD_MATRIX",
        "failed_cases": failures,
        "runtime_status": "FAIL" if failures else "PASS",
        "engine": str(engine_path),
        "fixed_dt_s": 1 / 480,
        "seconds": args.seconds,
        "repeats": args.repeats,
        "materials": list(MATERIALS),
        "ground_material_id": catalog()["materials"][0]["id"],
        "cases": cases,
        "interpretation": [
            "Ground and zero-g/no-ground packages use the same declared object frames per resolution stage.",
            "Candidate cells count ellipsoid grid candidates; actual cells/links come from admission reports.",
            "Fracture, contact, energy and timing fields are observations of the current experimental runtime.",
            "No material ordering, continuum realism, or fracture convergence claim is asserted by this matrix.",
        ],
    }
    write_json(output / "summary.json", summary)
    print(json.dumps({"summary": str(output / 'summary.json'), "status": summary["status"]}, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
