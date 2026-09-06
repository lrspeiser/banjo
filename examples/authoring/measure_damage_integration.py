"""Compare bounded damage trials with uniform steps; never a realism verdict.

Runs serially, preserves each input/report, and compares equal physical time.
Use a new output directory. No display names or material constants are changed.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import statistics

from banjo_authoring import EngineCLI


def save(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3, choices=range(1, 6))
    parser.add_argument("--seconds", type=float, default=3.)
    args = parser.parse_args()
    if not 0 < args.seconds <= 10:
        parser.error("seconds must be >0 and <=10")
    args.output.mkdir(parents=True, exist_ok=False)
    engine = EngineCLI(args.engine)
    root = Path(__file__).resolve().parents[2]
    fixtures = {
        "panels_12mps": "03-clamped-panels-12mps.json",
        "knife_tomato": "04-tomato-proxy-knife-cut.json",
    }
    rows = []
    for name, filename in fixtures.items():
        original = json.loads((root / "assets/material-showcase" / filename).read_text())
        for frequency, depth in ((480, None), (480, 0), (480, 2), (480, 4), (960, None), (960, 4)):
            label = f"{name}_dt{frequency}_depth{depth if depth is not None else 'off'}"
            source = copy.deepcopy(original)
            source["fixed_dt_s"] = 1 / frequency
            if depth is not None:
                source["damage_integration"] = {"maximum_depth": depth, "on_limit": "report"}
                source["required_capabilities"].append("adaptive-damage-integration")
            steps = round(args.seconds * frequency)
            if abs(steps / frequency - args.seconds) > 1e-10:
                parser.error("seconds must represent an integer step count at both 480 and 960 Hz")
            path = args.output / (label + ".json")
            save(path, source)
            reports = []
            for repeat in range(args.repeats):
                report = engine.run(path, steps)
                save(args.output / f"{label}.run{repeat + 1}.json", report)
                reports.append(report)
            first = reports[0]
            for report in reports[1:]:
                for field in ("objects", "fracture_events", "damage_integration", "elastic_energy_j", "fracture_work_j", "plastic_work_j"):
                    if report[field] != first[field]:
                        raise AssertionError(f"same-build repeat mismatch: {label}/{field}")
            rows.append({
                "case": label, "elapsed_s": first["elapsed_s"],
                "cells": first["cells"], "objects": first["objects"],
                "integration": first["damage_integration"],
                "median_step_total_ms": statistics.median(r["performance"]["step_wall_total_ms"] for r in reports),
                "median_step_p95_ms": statistics.median(r["performance"]["step_p95_ms"] for r in reports),
                "maximum_step_ms": max(r["performance"]["step_max_ms"] for r in reports),
                "fracture_work_j": first["fracture_work_j"],
                "unreleased_fracture_energy_j": first["unreleased_fracture_energy_j"],
                "unseparated_energy_change_j": first["unseparated_energy_change_j"],
                "energy_residual_j": first["energy_residual_j"],
            })
            print(label, "broken", [o["broken_links"] for o in first["objects"]],
                  "unresolved", first["damage_integration"]["unresolved_substeps"], flush=True)
    save(args.output / "summary.json", {
        "schema": "banjo-damage-integration-comparison-1", "repeats": args.repeats,
        "physical_response_validated": False, "headless_only": True,
        "limits": "Damage criteria do not estimate missed elastic/contact peaks or close the full work ledger.",
        "results": rows,
    })


if __name__ == "__main__":
    main()
