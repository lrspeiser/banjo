"""Run Algorithm 2 and the explicit-lattice reference over the checkpoint's scenes.

Every case is run twice by this script: once through `banjo_fracture_algo2` and
once through `banjo_fracture_algo2 --reference`, which builds the reference
lane's scene from the same command line so the two cannot differ by a scene
detail. Both write a banjo.playback.v1 recording and a report with the same
keys; this script collects them into one JSON and prints the accuracy table.

Nothing here simulates anything or changes a tolerance.

    python scripts/algo2-accuracy-matrix.py --exe build/agent/Release/banjo_fracture_algo2.exe \
        --cache build/fracture-cache --out build/runs/algo2 [--only base,thicker]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

# plate (L, W, T), cell, ball diameter, speed, offset, note
SCENES: dict[str, dict] = {
    "base": dict(plate=(0.25, 0.20, 0.02), cell=0.01, ball=0.06, speed=6.264, offset=(0.0, 0.0),
                 note="1000 cells, 20 mm plate, 60 mm iron ball at 6.26 m/s (a 2.0 m drop)"),
    "thicker": dict(plate=(0.25, 0.20, 0.03), cell=0.01, ball=0.06, speed=6.264, offset=(0.0, 0.0),
                    note="1500 cells, 30 mm plate, same striker"),
    "faster": dict(plate=(0.25, 0.20, 0.02), cell=0.01, ball=0.06, speed=9.90, offset=(0.0, 0.0),
                   note="the base plate at 9.90 m/s (a 5.0 m drop)"),
    "offcentre": dict(plate=(0.25, 0.20, 0.02), cell=0.01, ball=0.06, speed=6.264, offset=(0.06, 0.04),
                      note="the base scene struck 60 mm along and 40 mm across from the centre"),
    "heavyslow": dict(plate=(0.25, 0.20, 0.02), cell=0.01, ball=0.20, speed=1.0, offset=(0.0, 0.0),
                      note="a 200 mm iron ball (32.9 kg, 13x the plate) at 1.0 m/s: the quasi-static regime"),
    "contract500": dict(plate=(0.25, 0.20, 0.01), cell=0.01, ball=0.06, speed=6.264, offset=(0.0, 0.0),
                        note="the shared 500-cell contract scene, one cell through the thickness"),
}

VARIANTS = {
    "algo2": [],
    "algo2-strain": ["--criterion", "strain"],
    "algo2-plate-mass": ["--contact-mass", "plate"],
    "reference": ["--reference"],
}


def command(exe: Path, scene: dict, extra: list[str], cache: Path, out: Path, duration: float) -> list[str]:
    L, W, T = scene["plate"]
    return [str(exe), "--plate", f"{L:.6g}", f"{W:.6g}", f"{T:.6g}", "--cell", f"{scene['cell']:.6g}",
            "--ball", f"{scene['ball']:.6g}", "--speed", f"{scene['speed']:.6g}",
            "--offset", f"{scene['offset'][0]:.6g}", f"{scene['offset'][1]:.6g}",
            "--support", "ledges", "--duration", f"{duration:.6g}",
            "--cache", str(cache), "--output", str(out)] + extra


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--duration", type=float, default=2.0)
    parser.add_argument("--only", default="", help="comma-separated scene names")
    parser.add_argument("--variants", default=",".join(VARIANTS))
    parser.add_argument("--timeout", type=float, default=900.0)
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    args.cache.mkdir(parents=True, exist_ok=True)
    names = [n for n in (args.only.split(",") if args.only else list(SCENES)) if n]
    variants = [v for v in args.variants.split(",") if v]
    results: dict[str, dict] = {}
    collected = args.out / "matrix.json"
    if collected.is_file():
        results = json.loads(collected.read_text(encoding="utf-8"))

    for name in names:
        scene = SCENES[name]
        results.setdefault(name, {"scene": {**scene, "plate": list(scene["plate"]), "offset": list(scene["offset"])}})
        for variant in variants:
            recording = args.out / f"{name}-{variant}.json"
            if recording.is_file():
                recording.unlink()
            argv = command(args.exe, scene, VARIANTS[variant], args.cache, recording, args.duration)
            started = time.perf_counter()
            try:
                finished = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                                          errors="replace", timeout=args.timeout, check=False)
            except subprocess.TimeoutExpired:
                results[name][variant] = {"status": "timeout", "wall_s": args.timeout, "argv": argv}
                print(f"{name:12s} {variant:16s} TIMEOUT after {args.timeout} s", flush=True)
                continue
            wall = time.perf_counter() - started
            if finished.returncode != 0:
                reason = (finished.stderr or finished.stdout).strip().splitlines()
                results[name][variant] = {"status": "refused", "returncode": finished.returncode,
                                          "reason": reason[-1] if reason else "", "wall_s": wall, "argv": argv}
                print(f"{name:12s} {variant:16s} REFUSED: {(reason[-1] if reason else '')[:110]}", flush=True)
                continue
            report = json.loads(finished.stdout)
            report["_process_wall_s"] = wall
            report["_argv"] = argv
            report["_recording"] = str(recording)
            report["status"] = "complete"
            results[name][variant] = report
            print(f"{name:12s} {variant:16s} bonds {report.get('broken_bonds'):>6} "
                  f"pieces {report.get('components'):>4} largest {report.get('largest_component_cells'):>5} "
                  f"energy {report.get('removed_energy_j'):>10.3f} J  wall {wall:7.2f} s", flush=True)
            collected.write_text(json.dumps(results, indent=1), encoding="utf-8")
    collected.write_text(json.dumps(results, indent=1), encoding="utf-8")
    print(f"\nwrote {collected}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
