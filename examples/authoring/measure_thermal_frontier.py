"""Measure sparse heat-frontier work at fixed active physics and growing storage.

Stores every package/report in a new directory. This tests bounded activation,
not an error bound for ignored cold faces or a coupled mechanical game world.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import statistics
import subprocess


def save(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def physical(report: dict) -> dict:
    return {key: report[key] for key in ("regions", "combined_active_energy_residual_j", "active_cells", "requested_time_s")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3, choices=range(1, 6))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    original = json.loads((Path(__file__).resolve().parents[2] / "assets/world-v1/thermal-frontier.json").read_text())
    rows = []
    expected = None
    for chunks, work in ((4, 32768), (256, 32768), (4096, 32768), (4096, 1000)):
        package = copy.deepcopy(original)
        for extra in range(chunks - 4):
            package["chunks"].append({"position": [1000 + extra, 0, 0], "material": 1, "temperature_k": 293.15})
        label = f"chunks{chunks}_work{work}"
        path = args.output / (label + ".json")
        save(path, package)
        initial_path = args.output / (label + ".initial.json")
        subprocess.run([str(args.engine.resolve()), "--package", str(path.resolve()), "--frames", "1", "--output", str(initial_path.resolve())], check=True, capture_output=True, timeout=120)
        initial = json.loads(initial_path.read_text())
        # One 1/60 s request is shorter than the declared .05 s thermal tick:
        # inspect the heater result before reaction, conduction or growth.
        for region, expected_temperature in zip(initial["regions"], (650., 650., 650., 363.15), strict=True):
            if region["accepted_time_s"] != 0 or region["cells"] != 4 or abs(region["temperature_max_k"] - expected_temperature) > 1e-9:
                raise AssertionError("declared matched initial heat seeds changed")
        if initial["reaction_heat_j"] != 0 or initial["active_cells"] != 16:
            raise AssertionError("initial seed validation must precede physical stepping")
        reports = []
        for repeat in range(args.repeats):
            output = args.output / f"{label}.run{repeat + 1}.json"
            subprocess.run([str(args.engine.resolve()), "--package", str(path.resolve()), "--frames", "600", "--work", str(work), "--output", str(output.resolve())], check=True, capture_output=True, timeout=120)
            report = json.loads(output.read_text())
            if report["last_budget"]["error"]:
                raise AssertionError(report["last_budget"]["error"])
            if report["last_budget"]["frontier_regions_budget_blocked"] > report["active_regions"]:
                raise AssertionError("blocked-region receipt counted a region more than once")
            if report["performance"]["cold_chunks_scanned_per_advance"] != 0:
                raise AssertionError("cold storage scan entered tick loop")
            if abs(report["combined_active_energy_residual_j"]) > 1e-7:
                raise AssertionError("thermal plus chemical energy did not close")
            reports.append(report)
        if work == 32768:
            if any(report["last_budget"]["regions_late"] for report in reports):
                raise AssertionError("normal frontier fixture fell behind")
            expected = expected or physical(reports[0])
            if any(physical(report) != expected for report in reports):
                raise AssertionError("distant cold storage changed accepted local physics")
        elif not all(report["last_budget"]["regions_late"] and report["last_budget"]["frontier_regions_budget_blocked"] for report in reports):
            raise AssertionError("overload must explicitly preserve/report backlog")
        rows.append({
            "case": label, "stored_voxels": chunks * 4096,
            "active_cells": reports[0]["active_cells"],
            "median_advance_p95_ms": statistics.median(r["performance"]["advance_p95_ms"] for r in reports),
            "median_advance_p99_ms": statistics.median(r["performance"]["advance_p99_ms"] for r in reports),
            "median_total_ms": statistics.median(r["performance"]["total_wall_ms"] for r in reports),
            "maximum_call_ms": max(r["performance"]["advance_max_ms"] for r in reports),
            "maximum_absolute_energy_residual_j": max(abs(r["combined_active_energy_residual_j"]) for r in reports),
            "last_budget": reports[0]["last_budget"], "regions": reports[0]["regions"],
        })
        print(label, "active", rows[-1]["active_cells"], "p95", rows[-1]["median_advance_p95_ms"], flush=True)
    save(args.output / "summary.json", {"schema": "banjo-frontier-comparison-1", "repeats": args.repeats, "requested_time_s": 10, "headless_only": True, "world_scale_mechanics_validated": False, "results": rows})


if __name__ == "__main__":
    main()
