"""Run the fast explicit lattice lane over a matrix of scenes and tabulate.

Every row is one invocation of banjo_fast_lattice_run with its report JSON
kept under docs/evidence/fast-gpu/. Nothing here alters a solver setting; it
only varies scene size, material, backend and launch chunking, all existing
inputs of the tool.

    python scripts/fast-gpu-sweep.py [--exe PATH] [--only NAME,...] [--out DIR]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EXE = ROOT / "build" / "agent-cuda" / "Release" / "banjo_fast_lattice_run.exe"

# name -> extra arguments. The bridge scene is the headline; sizes scale the
# tile at a fixed cell, then refine the cell (the substep shrinks with it).
BASE = ["--layout", "bridge", "--ball-radius", "0.04", "--speed", "12"]
T192 = ["--tile", "0.24", "0.04", "0.16", "--cell", "0.02"]
T1536 = ["--tile", "0.24", "0.04", "0.16", "--cell", "0.01"]
MATRIX = {
    # Scale at a 20 mm cell: the same tile thickness, growing face.
    "bridge-96":    BASE + ["--tile", "0.12", "0.04", "0.16", "--cell", "0.02"],
    "bridge-192":   BASE + T192,
    "bridge-384":   BASE + ["--tile", "0.24", "0.04", "0.32", "--cell", "0.02"],
    "bridge-800":   BASE + ["--tile", "0.40", "0.04", "0.40", "--cell", "0.02"],
    # Refine the cell: the substep halves with it and the bond count grows 12x.
    "bridge-1536":  BASE + T1536,
    "bridge-1536-blocks4": BASE + T1536 + ["--blocks", "4"],
    "bridge-1536-blocks8": BASE + T1536 + ["--blocks", "8"],
    "bridge-3072-blocks8": BASE + ["--tile", "0.24", "0.04", "0.32", "--cell", "0.01", "--blocks", "8"],
    "bridge-6400-blocks8":  BASE + ["--tile", "0.40", "0.04", "0.40", "--cell", "0.01", "--blocks", "8"],
    "bridge-6400-blocks20": BASE + ["--tile", "0.40", "0.04", "0.40", "--cell", "0.01", "--blocks", "20"],
    "bridge-12288-blocks16": BASE + ["--tile", "0.24", "0.04", "0.16", "--cell", "0.005", "--blocks", "16"],
    # Materials under identical conditions.
    "bridge-192-oak":  BASE + T192 + ["--material", "oak"],
    "bridge-192-iron": BASE + T192 + ["--material", "iron"],
    "bridge-1536-oak-blocks8":  BASE + T1536 + ["--blocks", "8", "--material", "oak"],
    "bridge-1536-iron-blocks8": BASE + T1536 + ["--blocks", "8", "--material", "iron"],
    # Backend, precision and launch chunking on the headline scene.
    "bridge-192-cpu-float":   BASE + T192 + ["--backend", "cpu"],
    "bridge-192-cpu-double":  BASE + T192 + ["--backend", "cpu", "--precision", "double"],
    "bridge-192-gpu-double":  BASE + T192 + ["--precision", "double"],
    "bridge-192-launch1":     BASE + T192 + ["--steps-per-launch", "1"],
    "bridge-192-launch100":   BASE + T192 + ["--steps-per-launch", "100"],
    "bridge-192-launch1000":  BASE + T192 + ["--steps-per-launch", "1000"],
}


def run(exe: Path, name: str, extra: list[str], out: Path, timeout: float) -> dict | None:
    report = out / f"{name}.json"
    recording = out / f"{name}.playback.json"
    if recording.exists():
        recording.unlink()
    command = [str(exe), *extra, "--report", str(report), "--record", str(recording)]
    started = time.time()
    try:
        process = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        print(f"{name}: timed out after {timeout:.0f} s", file=sys.stderr)
        return None
    if process.returncode != 0:
        print(f"{name}: exit {process.returncode}\n{process.stdout[-800:]}\n{process.stderr[-800:]}", file=sys.stderr)
        return None
    data = json.loads(report.read_text(encoding="utf-8-sig"))
    data["_wall_process_s"] = time.time() - started
    return data


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, default=DEFAULT_EXE)
    parser.add_argument("--only", default="")
    parser.add_argument("--out", type=Path, default=ROOT / "docs" / "evidence" / "fast-gpu")
    parser.add_argument("--timeout", type=float, default=600.0)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    names = [n for n in args.only.split(",") if n] or list(MATRIX)
    rows = []
    for name in names:
        data = run(args.exe, name, MATRIX[name], args.out, args.timeout)
        if data is None:
            continue
        m = data["measurements"]
        lat, rig, hand = m["lattice"], m["rigid"], m["handoff"]
        us_per_step = 1e6 * lat["wall_s"] / max(1, lat["steps"])
        rows.append((name, m["backend"], m["cells"], m["bonds"], m["blocks"], m["colors"], m["dt_s"], lat["steps"],
                     lat["simulated_s"], lat["wall_s"], us_per_step, lat["bond_updates_per_s"], lat["launches"],
                     lat["broken_bonds"], lat["failure_rounds"], hand["components"], hand["largest_piece_mass_kg"],
                     lat["removed_energy_j"], rig["simulated_s"], rig["wall_s"], rig["came_to_rest"],
                     m["simulated_total_s"], m["wall_total_s"], m["realtime_ratio"], m["rule_met"]))
        print(f"{name}: {m['cells']} cells, {lat['steps']} steps, {us_per_step:.1f} us/step, "
              f"{lat['bond_updates_per_s']/1e6:.0f} M bond-updates/s, broken {lat['broken_bonds']}, "
              f"pieces {hand['components']}, ratio {m['realtime_ratio']:.3f}, rule {'met' if m['rule_met'] else 'NOT met'}",
              flush=True)
    header = ("name", "backend", "cells", "bonds", "blocks", "colors", "dt_s", "steps", "lattice_sim_s", "lattice_wall_s",
              "us_per_step", "bond_updates_per_s", "launches", "broken", "failure_rounds", "pieces", "largest_piece_kg",
              "removed_j", "rigid_sim_s", "rigid_wall_s", "rest", "sim_total_s", "wall_total_s", "ratio", "rule_met")
    with open(args.out / "summary.csv", "w", encoding="utf-8") as f:
        f.write(",".join(header) + "\n")
        for row in rows:
            f.write(",".join(str(v) for v in row) + "\n")
    print(f"wrote {args.out / 'summary.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
