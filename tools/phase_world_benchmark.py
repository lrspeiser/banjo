"""Build and run bounded comparative thermal-world workloads.

The workload keeps 4,096 uniform chunks (16,777,216 represented voxels) while
varying active regions with 64 cells each. Cold chunks are storage only; this
is not a claim that the full represented world is simulated. Runs are
deliberately sequential so timing samples are not contaminated by parallel
processes.
"""

from __future__ import annotations

import argparse
import copy
import json
import pathlib
import platform
import statistics
import subprocess
from typing import Any


CHUNK_COUNT = 4096
CELLS_PER_REGION = 64
ACTIVE_COUNTS = (4, 16, 64, 256)
REPEATS = 3
FRAMES = 600
PACKAGE_LIMIT_BYTES = 4 * 1024 * 1024


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", required=True, type=pathlib.Path,
                        help="path to banjo_world_cli")
    parser.add_argument("--out", required=True, type=pathlib.Path,
                        help="directory for generated packages, raw reports, and summary.json")
    parser.add_argument("--source", type=pathlib.Path,
                        help="thermal package source (defaults to assets/world-v1/energy-phase.json)")
    return parser.parse_args()


def chunk_key(value: list[int] | tuple[int, int, int]) -> tuple[int, int, int]:
    return tuple(int(part) for part in value)


def chunk_coordinates() -> list[list[int]]:
    # A deterministic 64 x 64 plane gives 4,096 unique chunk addresses while
    # keeping coordinates small enough for the package/world bounds.
    return [[index % 64, index // 64, 0] for index in range(CHUNK_COUNT)]


def build_package(source: dict[str, Any], active_regions: int) -> tuple[dict[str, Any], list[int]]:
    if active_regions not in ACTIVE_COUNTS:
        raise ValueError(f"unsupported active region count: {active_regions}")

    package = copy.deepcopy(source)
    source_chunks = {chunk_key(chunk["position"]): chunk for chunk in source["chunks"]}
    source_regions = source["regions"]
    source_heaters = source.get("heaters", [])
    if len(source_regions) != 4 or len(source_chunks) != 4:
        raise ValueError("energy-phase source must contain four material coupon regions/chunks")

    coordinates = chunk_coordinates()
    active_coordinates = coordinates[:active_regions]
    material_ids = [int(material["id"]) for material in source["materials"]]
    if material_ids != [1, 2, 3, 4]:
        raise ValueError("expected glass/oak/iron/water material IDs 1..4")

    # Keep all cold storage explicit, cycling the four declared materials. An
    # active chunk below is overwritten with its coupon temperature/material.
    chunks: list[dict[str, Any]] = []
    for index, position in enumerate(coordinates):
        source_chunk = source_chunks[chunk_key(source["chunks"][index % 4]["position"])]
        chunks.append({
            "position": position,
            "material": int(source_chunk["material"]),
            "temperature_k": float(source_chunk["temperature_k"]),
        })

    regions: list[dict[str, Any]] = []
    heaters: list[dict[str, Any]] = []
    region_material_ids: list[int] = []
    for region_index in range(active_regions):
        template_index = region_index % 4
        template_region = source_regions[template_index]
        template_chunk = chunk_key(template_region["cells"][0]["chunk"])
        active_position = active_coordinates[region_index]
        region_material = int(source_chunks[template_chunk]["material"])
        region_material_ids.append(region_material)

        cells = []
        for source_cell in template_region["cells"]:
            if chunk_key(source_cell["chunk"]) != template_chunk:
                raise ValueError("source coupon region is not uniform")
            cells.append({"chunk": list(active_position), "local": list(source_cell["local"])})
        regions.append({
            "id": region_index + 1,
            "step_s": float(template_region["step_s"]),
            "cells": cells,
        })

        for source_heater in source_heaters:
            if chunk_key(source_heater["cell"]["chunk"]) != template_chunk:
                continue
            heater = copy.deepcopy(source_heater)
            heater["cell"]["chunk"] = list(active_position)
            heaters.append(heater)

    # Make active chunks agree with their region's source coupon. The first
    # four source temperatures are the material-cycle temperatures.
    for index, material_id in enumerate(region_material_ids):
        source_chunk = source_chunks[chunk_key(source_regions[index % 4]["cells"][0]["chunk"])]
        chunks[index]["material"] = material_id
        chunks[index]["temperature_k"] = float(source_chunk["temperature_k"])

    package["chunks"] = chunks
    package["regions"] = regions
    package["heaters"] = heaters
    encoded = json.dumps(package, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(encoded) > PACKAGE_LIMIT_BYTES:
        raise ValueError(f"generated package exceeds 4 MiB load bound: {len(encoded)} bytes")
    if len(chunks) != CHUNK_COUNT or len(regions) != active_regions:
        raise AssertionError("generated workload dimensions are incorrect")
    return package, region_material_ids


def read_report(path: pathlib.Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        report = json.load(handle)
    if report.get("last_budget", {}).get("error"):
        raise RuntimeError(f"world CLI reported an error: {report['last_budget']['error']}")
    return report


def material_states(report: dict[str, Any], region_material_ids: list[int],
                    material_names: dict[int, str]) -> list[dict[str, Any]]:
    grouped: dict[int, list[dict[str, Any]]] = {material_id: [] for material_id in material_names}
    for region, material_id in zip(report.get("regions", []), region_material_ids):
        mass = float(region.get("mass_kg", 0.0))
        liquid_mass = float(region.get("liquid_mass_kg", 0.0))
        grouped.setdefault(material_id, []).append({
            "region_id": int(region["id"]),
            "accepted_time_s": float(region["accepted_time_s"]),
            "temperature_min_k": float(region["temperature_min_k"]),
            "temperature_max_k": float(region["temperature_max_k"]),
            "fuel_kg": float(region["fuel_kg"]),
            "oxygen_kg": float(region["oxygen_kg"]),
            "liquid_mass_kg": liquid_mass,
            "liquid_fraction": liquid_mass / mass if mass else 0.0,
            "thermal_enthalpy_j": float(region.get("thermal_enthalpy_j", 0.0)),
        })
    states = []
    for material_id, name in material_names.items():
        rows = grouped.get(material_id, [])
        clocks = [row["accepted_time_s"] for row in rows]
        states.append({
            "material_id": material_id,
            "material": name,
            "region_count": len(rows),
            "accepted_clock_range_s": [min(clocks), max(clocks)] if clocks else None,
            "states": rows,
            "comparable_at_matched_time": bool(rows) and max(clocks) - min(clocks) <= 1.0e-12,
        })
    return states


def summarize_case(active_regions: int, region_material_ids: list[int],
                   material_names: dict[int, str], reports: list[dict[str, Any]]) -> dict[str, Any]:
    performance = [report["performance"] for report in reports]
    budgets = [report["last_budget"] for report in reports]
    clocks = [float(region["accepted_time_s"])
              for report in reports for region in report.get("regions", [])]
    residuals = [abs(float(report.get("combined_active_energy_residual_j", 0.0)))
                 for report in reports]
    return {
        "active_regions": active_regions,
        "active_cells": active_regions * CELLS_PER_REGION,
        "uniform_chunks": reports[0].get("uniform_chunks"),
        "represented_voxels": reports[0].get("represented_voxels"),
        "p95_ms_range": [min(item["advance_p95_ms"] for item in performance),
                         max(item["advance_p95_ms"] for item in performance)],
        "p99_ms_range": [min(item["advance_p99_ms"] for item in performance),
                         max(item["advance_p99_ms"] for item in performance)],
        "max_ms_range": [min(item["advance_max_ms"] for item in performance),
                         max(item["advance_max_ms"] for item in performance)],
        "final_max_lag_s": [budget["maximum_lag_s"] for budget in budgets],
        "peak_max_lag_s": [item["peak_lag_s"] for item in performance],
        "final_late_regions": [budget["regions_late"] for budget in budgets],
        "peak_late_regions": [item["peak_late_regions"] for item in performance],
        "final_energy_residual_j": [report.get("combined_active_energy_residual_j")
                                     for report in reports],
        "maximum_abs_energy_residual_j": max(residuals),
        "region_clock_range_s": [min(clocks), max(clocks)] if clocks else None,
        "matched_time_s": min(clocks) if clocks and max(clocks)-min(clocks)<=1.0e-12 else None,
        "material_states": [material_states(report, region_material_ids, material_names)
                             for report in reports],
        "limitations": [
            "cold chunks are storage only; this is not full-world simulation",
            "insulated thermal/reaction/phase workload with no mechanics, airflow, smoke, or full fluid flow",
            "material states are comparable at matched accepted clocks only; no interpolation is applied",
        ],
    }


def main() -> int:
    args = parse_args()
    root = pathlib.Path(__file__).resolve().parents[1]
    source_path = args.source or root / "assets" / "world-v1" / "energy-phase.json"
    with source_path.open(encoding="utf-8") as handle:
        source = json.load(handle)
    args.out.mkdir(parents=True, exist_ok=True)

    material_names = {int(material["id"]): str(material["name"])
                      for material in source["materials"]}
    cases = []
    for active_regions in ACTIVE_COUNTS:
        package, region_material_ids = build_package(source, active_regions)
        package_path = args.out / f"inputs-{active_regions}-regions.json"
        package_text=json.dumps(package, indent=2) + "\n"
        if len(package_text.encode("utf-8"))>PACKAGE_LIMIT_BYTES:
            raise ValueError("serialized package exceeds byte limit")
        package_path.write_text(package_text, encoding="utf-8")
        reports = []
        for repeat in range(1, REPEATS + 1):
            report_path = args.out / f"report-{active_regions}-regions-run-{repeat}.json"
            command = [str(args.exe), "--package", str(package_path.resolve()),
                       "--frames", str(FRAMES), "--output", str(report_path.resolve())]
            completed = subprocess.run(command, check=False, capture_output=True, text=True)
            (args.out / f"report-{active_regions}-regions-run-{repeat}.stdout.txt").write_text(
                completed.stdout, encoding="utf-8")
            (args.out / f"report-{active_regions}-regions-run-{repeat}.stderr.txt").write_text(
                completed.stderr, encoding="utf-8")
            if completed.returncode != 0:
                raise RuntimeError(f"world CLI failed for {active_regions} regions run {repeat}: "
                                   f"{completed.stderr.strip()}")
            reports.append(read_report(report_path))
        cases.append(summarize_case(active_regions, region_material_ids, material_names, reports))

    summary = {
        "schema": "banjo.phase-world-benchmark.v1",
        "source": str(source_path.resolve()),
        "platform": platform.platform(),
        "processor": platform.processor(),
        "frames": FRAMES,
        "repeats": REPEATS,
        "host_hz": 60,
        "thermal_step_s": 0.05,
        "stored_uniform_chunks": CHUNK_COUNT,
        "represented_voxels": CHUNK_COUNT * 4096,
        "active_cells_per_region": CELLS_PER_REGION,
        "sequential_runs": True,
        "package_limit_bytes": PACKAGE_LIMIT_BYTES,
        "limitations": [
            "Cold chunks are represented storage only; results are not a fully simulated world.",
            "The CLI workload is insulated thermal/reaction/phase work without mechanics, airflow, smoke, or full fluid transport.",
            "No result claims a realtime deadline, material realism, or cross-region frontier completion.",
        ],
        "cases": cases,
    }
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out.resolve()), "cases": len(cases), "summary": "summary.json"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
