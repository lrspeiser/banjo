"""Drop an iron ball onto edge-clamped glass plates of varying thickness and height.

A classic plate drop test, authored entirely through the declared package
language. Gravity points along -z and the plate is held on its x/y perimeter, so
the ball falls onto a horizontal pane held in a frame.

Drop height is converted to the impact speed it produces, v = sqrt(2gh), and the
ball is started just above the plate with that speed. Simulating the fall itself
would spend the entire substep budget on a body moving in a straight line, and
the plate cannot tell the difference: only the speed at contact matters.

Cost note: the substep bound is set by the smallest cell, and the smallest cell
is half the plate thickness. A thin plate is the expensive case -- 8 mm costs
roughly two and a half times what 20 mm costs for the same simulated window.

Usage:
    python examples/authoring/drop_sweep.py
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))

from banjo_authoring import catalog, make_object, make_package, write_package

GRAVITY = 9.81
PLATE_FACE_M = [0.24, 0.36]
PLATE_CENTRE_M = [0.0, 0.0, 0.5]
IN_PLANE_CELLS = [8, 12]
CELLS_THROUGH_THICKNESS = 2          # the engine's minimum
BALL_DIAMETER_M = 0.08
CLEARANCE_M = 0.015
DT_S = 1.0 / 1920.0
DURATION_S = 0.0625

THICKNESSES_M = [0.008, 0.012, 0.020]
DROP_HEIGHTS_M = [1.0, 4.0, 10.0]


def impact_speed(height_m: float) -> float:
    return math.sqrt(2.0 * GRAVITY * height_m)


def plate(thickness_m: float) -> dict:
    return make_object(
        "glass_panel", 1, material="glass", name=f"{thickness_m * 1000:.0f} mm glass plate",
        dimensions_m=[PLATE_FACE_M[0], PLATE_FACE_M[1], thickness_m],
        resolution=[IN_PLANE_CELLS[0], IN_PLANE_CELLS[1], CELLS_THROUGH_THICKNESS],
        position_m=list(PLATE_CENTRE_M), velocity_m_s=[0.0, 0.0, 0.0],
        spin_rad_s=[0.0, 0.0, 0.0], pin_boundary=True)


def ball(thickness_m: float, speed_m_s: float) -> dict:
    z = PLATE_CENTRE_M[2] + thickness_m / 2 + BALL_DIAMETER_M / 2 + CLEARANCE_M
    return make_object(
        "iron_ball", 2, material="iron", name="80 mm iron ball",
        position_m=[PLATE_CENTRE_M[0], PLATE_CENTRE_M[1], z],
        velocity_m_s=[0.0, 0.0, -speed_m_s], spin_rad_s=[0.0, 0.0, 0.0])


def package_for(thickness_m: float, height_m: float) -> dict:
    speed = impact_speed(height_m)
    return make_package(
        [plate(thickness_m), ball(thickness_m, speed)],
        materials=[m for m in catalog()["materials"] if m["id"] in ("glass", "iron")],
        name=f"{thickness_m * 1000:.0f} mm plate, {height_m:g} m drop ({speed:.2f} m/s)",
        fixed_dt_s=DT_S, gravity_m_s2=(0.0, 0.0, -GRAVITY), ground=None)


def run(recorder: Path, outdir: Path, timeout_s: float) -> list[dict]:
    outdir.mkdir(parents=True, exist_ok=True)
    steps = max(1, round(DURATION_S / DT_S))
    records = []
    total = len(THICKNESSES_M) * len(DROP_HEIGHTS_M)
    index = 0
    for thickness in THICKNESSES_M:
        for height in DROP_HEIGHTS_M:
            index += 1
            case_id = f"{thickness * 1000:.0f}mm-{height:g}m"
            speed = impact_speed(height)
            package_path = outdir / f"{case_id}.package.json"
            package_path.unlink(missing_ok=True)
            write_package(package_for(thickness, height), package_path)
            playback_path = outdir / f"{case_id}.playback.json"
            print(f"[{index}/{total}] {case_id:12} {thickness*1000:4.0f} mm, "
                  f"{height:5.1f} m drop = {speed:5.2f} m/s ... ", end="", flush=True)
            started = time.perf_counter()
            result = subprocess.run(
                [str(recorder), "--package", str(package_path), "--steps", str(steps),
                 "--output", str(playback_path)],
                capture_output=True, text=True, timeout=timeout_s, check=False)
            wall = time.perf_counter() - started
            row = {"id": case_id, "thickness_m": thickness, "height_m": height,
                   "speed_m_s": round(speed, 3), "wall_s": round(wall, 1), "steps": steps}
            if result.returncode or not playback_path.is_file():
                row["status"] = f"failed: {result.stdout.strip()[:160]}"
                print(row["status"])
            else:
                rec = json.loads(playback_path.read_text(encoding="utf-8"))
                report = rec.get("report", {})
                objects = [o for o in report.get("objects", []) if (o.get("cells") or 0) > 1]
                row.update({
                    "status": rec.get("status"),
                    "broken_links": report.get("broken_links"), "links": report.get("links"),
                    "components": report.get("connected_components"),
                    "largest": objects[0].get("largest_component_cells") if objects else None,
                    "cells": objects[0].get("cells") if objects else None,
                    "fracture_work_j": report.get("fracture_work_j"),
                    "unreleased_j": report.get("unreleased_fracture_energy_j"),
                    "initial_energy_j": report.get("initial_energy_j"),
                    "state_valid": report.get("state_valid"),
                    "substeps": (report.get("network_substepping") or {}).get("substeps_per_host_tick"),
                    "refused": (report.get("reaction_reconstruction") or {}).get("inadmissible_bond_updates"),
                })
                print(f"broken={row['broken_links']}/{row['links']} pieces={row['components']} "
                      f"largest={row['largest']} ({wall:.0f}s)")
            records.append(row)
            (outdir / "sweep.json").write_text(json.dumps(records, indent=1), encoding="utf-8")
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--recorder", type=Path,
                        default=ROOT / "build/win-joint-double/Release/banjo_playground_record.exe")
    parser.add_argument("--output", type=Path, default=ROOT / "build/drop-sweep")
    parser.add_argument("--timeout-s", type=float, default=3600.0)
    args = parser.parse_args()
    if not args.recorder.is_file():
        print(f"Recorder not found: {args.recorder}", file=sys.stderr)
        return 2
    records = run(args.recorder, args.output, args.timeout_s)
    print()
    print(f"{'plate':>8} {'drop':>7} {'speed':>8} {'broken':>10} {'pieces':>7} {'largest':>8}")
    for r in records:
        print(f"{r['thickness_m']*1000:>6.0f}mm {r['height_m']:>6.1f}m {r['speed_m_s']:>7.2f} "
              f"{str(r.get('broken_links')) + '/' + str(r.get('links')):>10} "
              f"{str(r.get('components')):>7} {str(r.get('largest')):>8}")
    print(f"\nRecordings under {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
