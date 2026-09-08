"""Every scene the re-fracture checkpoint reports, and the numbers it quotes.

Runs `banjo_fast_lattice_run` over five groups and writes one JSON per run under
`docs/evidence/refracture/` plus a `summary.json`:

  unchanged   every panel scenario, this binary against the 078ae24 binary,
              every measurement key compared (the first strike must not move)
  twice       the 500-cell glass plate broken, then struck again, with
              re-fracture off and on: the before and the after
  harder      the same second strike swept over speed
  landing     fragments dropped from a height onto concrete, for glass, oak and
              iron under identical conditions: the trigger decides which of them
              can break when they land
  materials   glass, oak and iron struck twice under identical geometry, strike
              and second strike
  cost        what re-fracture costs on a scene that triggers it and on one
              that does not

Nothing here changes a solver, a criterion or a tolerance; it runs the binary.

    python scripts/refracture-scenes.py --group all
    python scripts/refracture-scenes.py --group twice --group harder
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/evidence/refracture"

# Keys that are wall-clock or machine-dependent and cannot be part of an
# equality claim about the physics.
TIMING = {
    "wall_s", "wall_total_s", "bond_updates_per_s", "kernel_s", "phase_seconds",
    "recording_wall_s", "realtime_ratio", "rule_met", "launches",
}
# Keys that differ between backends by documented design, not by physics: the
# parallel and CUDA backends do not record the first-failure SET, and the
# rank-deficiency counter counts recomputations, not results.
BACKEND_ONLY = {"backend", "first_failure", "rank_deficient_nodes", "shared_memory_bytes",
                "shared_memory_positions", "blocks", "colors", "boundary_bonds"}

PLATE = ["--tile", "0.25", "0.01", "0.2", "--cell", "0.01", "--ball-radius", "0.03"]
TILE192 = ["--tile", "0.24", "0.04", "0.16", "--cell", "0.02", "--ball-radius", "0.04"]


def flatten(node: Any, prefix: str = "", skip: set[str] = frozenset()) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(node, dict):
        for key, value in node.items():
            if key in skip:
                continue
            out.update(flatten(value, f"{prefix}.{key}" if prefix else key, skip))
    elif isinstance(node, list):
        out[prefix] = json.dumps(node)
    else:
        out[prefix] = node
    return out


def run(exe: Path, name: str, argv: list[str], record: Path | None = None) -> dict[str, Any]:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    report = EVIDENCE / f"{name}.json"
    command = [str(exe), *argv, "--report", str(report)]
    if record is not None:
        command += ["--record", str(record)]
    started = time.perf_counter()
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    wall = time.perf_counter() - started
    if result.returncode != 0:
        raise SystemExit(f"{name} failed: {result.stderr[-2000:]}")
    payload = json.loads(report.read_text(encoding="utf-8"))
    payload["_command"] = command
    payload["_wall_s"] = wall
    report.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    return payload["measurements"]


PANEL = {
    "glass-pane": ["--material", "glass", "--tile", "1", "0.0625", "1", "--cell", "0.0625",
                   "--ball-radius", "0.15", "--speed", "20", "--layout", "bridge", "--settle-s", "2"],
    "oak-pane": ["--material", "oak", "--tile", "1", "0.0625", "1", "--cell", "0.0625",
                 "--ball-radius", "0.15", "--speed", "20", "--layout", "bridge", "--settle-s", "2",
                 "--failure-law", "energy-scaled"],
    "glass-plate": ["--material", "glass", *PLATE, "--speed", "6.26424", "--layout", "bridge", "--settle-s", "2"],
    "glass-punch": ["--material", "glass", *PLATE, "--speed", "20", "--layout", "bridge", "--settle-s", "2"],
    "glass-offcentre": ["--material", "glass", *PLATE, "--speed", "6.26424", "--offset", "0.07", "0.04",
                        "--layout", "bridge", "--settle-s", "2"],
    "iron-dent": ["--material", "iron", "--tile", "0.15", "0.01", "0.12", "--cell", "0.005",
                  "--ball-radius", "0.03", "--speed", "6", "--layout", "bridge", "--settle-s", "2",
                  "--plasticity", "on"],
    "oak-ground": ["--material", "oak", *PLATE, "--speed", "6.26424", "--layout", "flat", "--settle-s", "2"],
    "tile192": ["--material", "glass", *TILE192, "--speed", "8", "--layout", "bridge", "--settle-s", "2"],
}
COMMON = ["--ball-material", "iron", "--backend", "cpu", "--precision", "double"]


def group_unchanged(exe: Path, reference: Path) -> dict[str, Any]:
    rows = []
    for name, argv in PANEL.items():
        new = run(exe, f"unchanged-{name}-new", [*argv, *COMMON])
        old = run(reference, f"unchanged-{name}-078ae24", [*argv, *COMMON])
        a, b = flatten(new, skip={"refracture"}), flatten(old, skip={"refracture"})
        def is_timing(key: str) -> bool:
            return key.startswith("phase_seconds.") or any(
                key == t or key.endswith("." + t) for t in TIMING)
        common = sorted(k for k in set(a) & set(b) if not is_timing(k))
        differing = [k for k in common if a[k] != b[k]]
        rows.append({"scene": name, "common_keys": len(common), "differing": differing,
                     "broken_bonds": new["lattice"]["broken_bonds"], "pieces": new["handoff"]["components"]})
        print(f"  {name:16s} {len(common):3d} keys, {len(differing)} differing"
              f"  ({new['lattice']['broken_bonds']} bonds, {new['handoff']['components']} pieces)")
    return {"rows": rows}


SECOND = ["--second-ball", "0.05", "--second-material", "iron", "--second-offset", "0.09", "0",
          "--second-at", "rest", "--second-wait", "0.6"]
TWICE_BASE = ["--material", "glass", *PLATE, "--speed", "6.26424", "--layout", "bridge",
              "--settle-s", "1.5", "--ball-material", "iron", "--backend", "parallel",
              "--precision", "double", "--cpu-threads", "8"]


def group_twice(exe: Path) -> dict[str, Any]:
    rows = []
    for state in ("off", "on"):
        record = EVIDENCE / f"twice-{state}.playback.json"
        m = run(exe, f"twice-{state}", [*TWICE_BASE, "--refracture", state,
                                        *SECOND, "--second-speed", "8"], record)
        rows.append(summarise(f"second strike 8 m/s, re-fracture {state}", m))
        print("  " + json.dumps(rows[-1]))
    return {"rows": rows}


def group_harder(exe: Path) -> dict[str, Any]:
    rows = []
    for speed in (4, 6, 8, 12, 16, 20):
        for state in ("off", "on"):
            m = run(exe, f"harder-{speed}-{state}",
                    [*TWICE_BASE, "--refracture", state, *SECOND, "--second-speed", str(speed)],
                    EVIDENCE / f"harder-{speed}-{state}.playback.json" if speed in (8, 20) else None)
            rows.append(summarise(f"{speed} m/s, {state}", m) | {"speed_m_s": speed, "refracture": state})
            print("  " + json.dumps(rows[-1]))
    return {"rows": rows}


LANDING = ["--tile", "0.24", "0.04", "0.16", "--cell", "0.02", "--ball-radius", "0.04",
           "--speed", "12", "--layout", "bridge", "--ledge-height", "5.5", "--settle-s", "2.5",
           "--ball-material", "iron", "--backend", "parallel", "--precision", "double",
           "--cpu-threads", "8", "--refracture", "on"]


def group_landing(exe: Path) -> dict[str, Any]:
    rows = []
    for material in ("glass", "oak", "iron"):
        record = EVIDENCE / f"landing-{material}.playback.json"
        m = run(exe, f"landing-{material}", ["--material", material, *LANDING], record)
        f = m["refracture"]
        rows.append({
            "material": material,
            "first_strike_bonds": m["lattice"]["broken_bonds"],
            "first_strike_pieces": m["handoff"]["components"],
            "impact_speed_m_s": math.sqrt(2 * 9.81 * 5.5),
            "max_closing_speed_m_s": f["rejected"]["max_closing_speed_m_s"],
            "threshold_speed_m_s": (f["events"][0]["trigger"]["threshold_speed_m_s"] if f["events"] else None),
            "max_margin": f["rejected"]["max_margin"],
            "admitted": f["admitted"],
            "landing_bonds_broken": f["broken_bonds"],
            "pieces_at_end": m["rigid"]["pieces_at_end"],
            "realtime_ratio": m["realtime_ratio"],
        })
        print("  " + json.dumps(rows[-1]))
    return {"rows": rows}


MATERIALS = ["--tile", "0.24", "0.04", "0.16", "--cell", "0.02", "--ball-radius", "0.04",
             "--speed", "12", "--layout", "bridge", "--settle-s", "1.0",
             "--ball-material", "iron", "--backend", "parallel", "--precision", "double",
             "--cpu-threads", "8", "--second-ball", "0.04", "--second-material", "iron",
             "--second-speed", "20", "--second-offset", "0.08", "0",
             "--second-at", "rest", "--second-wait", "0.35"]


def group_materials(exe: Path) -> dict[str, Any]:
    """Glass, oak and iron under identical geometry, strike and second strike."""
    rows = []
    for material in ("glass", "oak", "iron"):
        for state in ("off", "on"):
            m = run(exe, f"materials-{material}-{state}",
                    ["--material", material, *MATERIALS, "--refracture", state],
                    EVIDENCE / f"materials-{material}-{state}.playback.json" if state == "on" else None)
            f = m["refracture"]
            rows.append({
                "material": material, "refracture": state,
                "first_strike_bonds": m["lattice"]["broken_bonds"],
                "first_strike_pieces": m["handoff"]["components"],
                "threshold_speed_m_s": (f["events"][0]["trigger"]["threshold_speed_m_s"] if f["events"] else None),
                "max_closing_speed_m_s": f["rejected"]["max_closing_speed_m_s"],
                "max_margin": f["rejected"]["max_margin"],
                "admitted": f["admitted"],
                "second_strike_bonds": f["broken_bonds"],
                "removed_energy_j": round(f["removed_energy_j"], 4),
                "pieces_at_end": m["rigid"]["pieces_at_end"],
                "realtime_ratio": round(m["realtime_ratio"], 4),
            })
            print("  " + json.dumps(rows[-1]))
    return {"rows": rows}


def group_cost(exe: Path) -> dict[str, Any]:
    scenes = {
        "plate-500": ["--material", "glass", *PLATE, "--speed", "6.26424", "--layout", "bridge",
                      "--settle-s", "2"],
        "pane-1m": ["--material", "glass", "--tile", "1", "0.0625", "1", "--cell", "0.0625",
                    "--ball-radius", "0.15", "--speed", "20", "--layout", "bridge", "--settle-s", "2"],
    }
    rows = []
    for name, argv in scenes.items():
        for state in ("off", "on"):
            m = run(exe, f"cost-{name}-{state}",
                    [*argv, "--ball-material", "iron", "--backend", "parallel", "--precision", "double",
                     "--cpu-threads", "8", "--refracture", state])
            f = m["refracture"]
            rows.append({"scene": name, "refracture": state,
                         "simulated_s": m["simulated_total_s"], "wall_s": m["wall_total_s"],
                         "realtime_ratio": m["realtime_ratio"], "rule_met": m["rule_met"],
                         "contacts_tested": f["contacts_tested"], "trial_steps": f["trial_steps"],
                         "rollbacks": f["rollbacks"], "admitted": f["admitted"],
                         "refracture_wall_s": f["wall_s"], "refracture_substeps": f["substeps"]})
            print("  " + json.dumps(rows[-1]))
    return {"rows": rows}


def summarise(label: str, m: dict[str, Any]) -> dict[str, Any]:
    f = m["refracture"]
    return {
        "case": label,
        "first_strike_bonds": m["lattice"]["broken_bonds"],
        "first_strike_pieces": m["handoff"]["components"],
        "second_strike_bonds": f["broken_bonds"],
        "second_strike_events": len(f["events"]),
        "pieces_at_end": m["rigid"]["pieces_at_end"],
        "contacts_tested": f["contacts_tested"],
        "admitted": f["admitted"],
        "max_closing_speed_m_s": round(f["rejected"]["max_closing_speed_m_s"], 4),
        "removed_energy_j": round(f["removed_energy_j"], 4),
        "realtime_ratio": round(m["realtime_ratio"], 4),
        "wall_total_s": round(m["wall_total_s"], 4),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--exe", type=Path, default=ROOT / "build/agent/Release/banjo_fast_lattice_run.exe")
    parser.add_argument("--reference", type=Path,
                        default=ROOT / "build/ref-078ae24/build/ref/Release/banjo_fast_lattice_run.exe")
    parser.add_argument("--group", action="append", default=[],
                        choices=["all", "unchanged", "twice", "harder", "landing", "materials", "cost"])
    args = parser.parse_args()
    groups = args.group or ["all"]
    if "all" in groups:
        groups = ["unchanged", "twice", "harder", "landing", "materials", "cost"]
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    summary: dict[str, Any] = {}
    for group in groups:
        print(f"[{group}]")
        if group == "unchanged":
            summary[group] = group_unchanged(args.exe, args.reference)
        elif group == "twice":
            summary[group] = group_twice(args.exe)
        elif group == "harder":
            summary[group] = group_harder(args.exe)
        elif group == "landing":
            summary[group] = group_landing(args.exe)
        elif group == "materials":
            summary[group] = group_materials(args.exe)
        elif group == "cost":
            summary[group] = group_cost(args.exe)
    path = EVIDENCE / "summary.json"
    existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    existing.update(summary)
    path.write_text(json.dumps(existing, indent=1), encoding="utf-8")
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
