"""Author the same glass panel struck in different places at different speeds.

Everything here goes through the declared package language: only the striker's
position and velocity change between variants. The panel, its material, its mesh
and the timestep are identical, so any difference in the fracture pattern comes
from the engine responding to the declared impact rather than from the scene
being rebuilt.

Each variant is recorded with `banjo_playground_record`, so the output is the
engine's own per-cell states over time, suitable for playback.

Usage:
    python examples/authoring/shatter_sweep.py --recorder build/win-joint-double/Release/banjo_playground_record.exe
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))

from banjo_authoring import catalog, make_object, make_package, write_package

# One panel definition shared by every variant. Three cells through thickness is
# the minimum that can hold a piece which is not a single surface chip.
PANEL_DIMENSIONS_M = [0.24, 0.36, 0.08]
PANEL_RESOLUTION = [8, 12, 3]
PANEL_CENTRE_M = [0.0, 0.5, 0.0]
BALL_STANDOFF_M = 0.2
DT_S = 1.0 / 1920.0
DURATION_S = 0.10


def panel() -> dict:
    return make_object(
        "glass_panel", 1, material="glass", name="glass panel",
        dimensions_m=list(PANEL_DIMENSIONS_M), resolution=list(PANEL_RESOLUTION),
        position_m=list(PANEL_CENTRE_M), velocity_m_s=[0.0, 0.0, 0.0],
        spin_rad_s=[0.0, 0.0, 0.0], pin_boundary=True)


def striker(x_m: float, y_offset_m: float, speed_m_s: float) -> dict:
    """An 80 mm iron ball aimed along -z at the declared point on the panel face."""
    return make_object(
        "iron_ball", 2, material="iron", name="iron striker",
        position_m=[x_m, PANEL_CENTRE_M[1] + y_offset_m, BALL_STANDOFF_M],
        velocity_m_s=[0.0, 0.0, -speed_m_s], spin_rad_s=[0.0, 0.0, 0.0])


def variant(name: str, x_m: float, y_offset_m: float, speed_m_s: float) -> dict:
    materials = [m for m in catalog()["materials"] if m["id"] in ("glass", "iron")]
    package = make_package(
        [panel(), striker(x_m, y_offset_m, speed_m_s)], materials=materials,
        name=f"Glass panel: {name}", fixed_dt_s=DT_S,
        gravity_m_s2=(0.0, -9.81, 0.0),
        ground={"half_length_m": 2.0, "half_width_m": 2.0, "friction": 0.4})
    return {"id": name, "x_m": x_m, "y_offset_m": y_offset_m,
            "speed_m_s": speed_m_s, "package": package}


def build_variants() -> list[dict]:
    """Three strengths at the centre, then the same strength moved off centre.

    Half the panel's in-plane extent is 0.12 x 0.18 m, and the boundary ring is
    pinned, so 0.08 m out is still on free material while 0.10 x 0.14 m sits
    against the clamped edge.
    """
    return [
        variant("centre-6ms", 0.0, 0.0, 6.0),
        variant("centre-12ms", 0.0, 0.0, 12.0),
        variant("centre-25ms", 0.0, 0.0, 25.0),
        variant("offset-12ms", 0.08, 0.0, 12.0),
        variant("corner-12ms", 0.10, 0.14, 12.0),
    ]


def run(recorder: Path, outdir: Path, timeout_s: float) -> list[dict]:
    outdir.mkdir(parents=True, exist_ok=True)
    steps = max(1, round(DURATION_S / DT_S))
    records = []
    for index, case in enumerate(build_variants(), start=1):
        package_path = outdir / f"{case['id']}.package.json"
        package_path.unlink(missing_ok=True)
        write_package(case["package"], package_path)
        playback_path = outdir / f"{case['id']}.playback.json"
        print(f"[{index}/5] {case['id']:14} x={case['x_m']:+.2f} m "
              f"y={case['y_offset_m']:+.2f} m {case['speed_m_s']:>5.1f} m/s ... ",
              end="", flush=True)
        started = time.perf_counter()
        result = subprocess.run(
            [str(recorder), "--package", str(package_path),
             "--steps", str(steps), "--output", str(playback_path)],
            capture_output=True, text=True, timeout=timeout_s, check=False)
        wall = time.perf_counter() - started
        row = {**{k: v for k, v in case.items() if k != "package"},
               "wall_s": round(wall, 1), "steps": steps}
        if result.returncode or not playback_path.is_file():
            row["status"] = f"failed: {result.stdout.strip()[:160]}"
            print(row["status"])
        else:
            recording = json.loads(playback_path.read_text(encoding="utf-8"))
            report = recording.get("report", {})
            objects = [o for o in report.get("objects", []) if (o.get("cells") or 0) > 1]
            row.update({
                "status": recording.get("status"),
                "broken_links": report.get("broken_links"),
                "links": report.get("links"),
                "components": report.get("connected_components"),
                "largest_component_cells": objects[0].get("largest_component_cells") if objects else None,
                "cells": objects[0].get("cells") if objects else None,
                "fracture_work_j": report.get("fracture_work_j"),
                "state_valid": report.get("state_valid"),
                "substeps": (report.get("network_substepping") or {}).get("substeps_per_host_tick"),
                "refused": (report.get("reaction_reconstruction") or {}).get("inadmissible_bond_updates"),
            })
            print(f"broken={row['broken_links']} pieces={row['components']} "
                  f"largest={row['largest_component_cells']} ({wall:.0f}s)")
        records.append(row)
    (outdir / "sweep.json").write_text(json.dumps(records, indent=1), encoding="utf-8")
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--recorder", type=Path,
                        default=ROOT / "build/win-joint-double/Release/banjo_playground_record.exe")
    parser.add_argument("--output", type=Path, default=ROOT / "build/shatter-sweep")
    parser.add_argument("--timeout-s", type=float, default=3600.0)
    args = parser.parse_args()
    if not args.recorder.is_file():
        print(f"Recorder not found: {args.recorder}", file=sys.stderr)
        return 2
    records = run(args.recorder, args.output, args.timeout_s)
    print()
    print(f"{'variant':16} {'speed':>7} {'broken':>8} {'pieces':>7} {'largest':>8} {'work J':>9}")
    for r in records:
        print(f"{r['id']:16} {r['speed_m_s']:>6.1f} {str(r.get('broken_links')):>8} "
              f"{str(r.get('components')):>7} {str(r.get('largest_component_cells')):>8} "
              f"{r.get('fracture_work_j') if r.get('fracture_work_j') is None else format(r['fracture_work_j'], '.4f'):>9}")
    print(f"\nRecordings and sweep.json under {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
