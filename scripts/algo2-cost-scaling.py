"""Measure Algorithm 2's precompute and per-rerun cost against plate size.

Each size is run twice: cold (an empty cache directory of its own, so the
precompute is really paid) and warm (the same directory again, so the run is a
table read plus the cascade). Nothing is simulated differently between the two.

    python scripts/algo2-cost-scaling.py --exe build/agent/Release/banjo_fracture_algo2.exe \
        --cache build/fracture-cache-cost --out build/runs/algo2-cost
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

# name -> plate (L, W, T), cell, cells, extra flags
SIZES = [
    ("240", (0.24, 0.20, 0.04), 0.02, []),
    ("500", (0.25, 0.10, 0.02), 0.01, []),
    ("1000", (0.25, 0.20, 0.02), 0.01, []),
    ("1500", (0.25, 0.20, 0.03), 0.01, []),
    ("2000", (0.25, 0.20, 0.04), 0.01, ["--single-strike", "--max-bytes", "2600"]),
]


def run(exe: Path, plate, cell, cache: Path, out: Path, extra: list[str], timeout: float):
    L, W, T = plate
    argv = [str(exe), "--plate", f"{L:.6g}", f"{W:.6g}", f"{T:.6g}", "--cell", f"{cell:.6g}",
            "--ball", "0.06", "--speed", "6.264", "--offset", "0", "0", "--support", "ledges",
            "--duration", "2.0", "--cache", str(cache), "--output", str(out)] + extra
    if out.is_file():
        out.unlink()
    started = time.perf_counter()
    try:
        done = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "wall_s": timeout, "argv": argv}
    wall = time.perf_counter() - started
    if done.returncode != 0:
        reason = (done.stderr or done.stdout).strip().splitlines()
        return {"status": "refused", "reason": reason[-1] if reason else "", "wall_s": wall, "argv": argv}
    report = json.loads(done.stdout)
    report["_process_wall_s"] = wall
    report["status"] = "complete"
    report["_argv"] = argv
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=1200.0)
    parser.add_argument("--only", default="")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    wanted = set(args.only.split(",")) if args.only else None
    results = {}
    collected = args.out / "cost.json"
    if collected.is_file():
        results = json.loads(collected.read_text(encoding="utf-8"))

    for name, plate, cell, extra in SIZES:
        if wanted and name not in wanted:
            continue
        cache = args.cache / name
        if cache.exists():
            shutil.rmtree(cache)
        cache.mkdir(parents=True, exist_ok=True)
        cold = run(args.exe, plate, cell, cache, args.out / f"{name}-cold.json", extra, args.timeout)
        warm = run(args.exe, plate, cell, cache, args.out / f"{name}-warm.json", extra, args.timeout)
        results[name] = {"plate": list(plate), "cell": cell, "cold": cold, "warm": warm}
        if cold.get("status") == "complete":
            p = cold["precompute"]
            print(f"{name:>6} cells={cold['cells']:>5} bonds={cold['bonds']:>6} modes={p['modes']:>6} "
                  f"strikes={p['strike_cells_ready']}/{p['strike_cells']} "
                  f"cold={cold['_process_wall_s']:8.2f}s (eigen {p['eigen_s']:7.2f} infl {p['influence_s']:7.2f} "
                  f"peak {p['peak_s']:7.2f}) bytes={cold['precompute_bytes']/1048576:8.1f}MiB "
                  f"warm={warm.get('_process_wall_s', float('nan')):6.3f}s "
                  f"cascade={warm.get('cascade_wall_s', float('nan')):7.4f}s "
                  f"events={warm.get('events')}", flush=True)
        else:
            print(f"{name:>6} {cold.get('status')}: {str(cold.get('reason'))[:120]}", flush=True)
        collected.write_text(json.dumps(results, indent=1), encoding="utf-8")
    print(f"\nwrote {collected}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
