"""Drive banjo_modal_fracture_record over refinement ladders, sizes, materials and
basis truncations, and tabulate the modal lane against the implicit reference.

Every number printed here comes from the tool's own JSON report; this script
runs it, reads it back and compares. Nothing is simulated in Python.

    python scripts/modal-fracture-compare.py ladder   --exe build/agent/Release/banjo_modal_fracture_record.exe
    python scripts/modal-fracture-compare.py scale    --sizes 8x8x2,12x12x2,16x16x2
    python scripts/modal-fracture-compare.py materials
    python scripts/modal-fracture-compare.py truncation --fractions 1,0.75,0.5,0.25
    python scripts/modal-fracture-compare.py headline --settle 1

Results (the full tool reports) are written under --out as JSON so the tables
can be regenerated without re-running.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_tool(exe: Path, out_dir: Path, tag: str, **options) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    recording = out_dir / f"{tag}.json"
    if recording.exists():
        recording.unlink()
    args = [str(exe)]
    for key, value in options.items():
        args += [f"--{key.replace('_', '-')}", str(value)]
    args += ["--output", str(recording)]
    started = time.perf_counter()
    process = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", timeout=3600, check=False)
    wall = time.perf_counter() - started
    try:
        summary = json.loads(process.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        raise RuntimeError(f"tool produced no summary: {process.stdout}\n{process.stderr}")
    if summary.get("status") == "error":
        raise RuntimeError(f"tool error for {tag}: {summary.get('error')}")
    report = json.loads(recording.read_text(encoding="utf-8"))["report"]
    report["_summary"] = summary
    report["_process_wall_s"] = wall
    report["_args"] = args
    (out_dir / f"{tag}.report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    return report


def jaccard(a, b) -> float:
    a, b = set(a), set(b)
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def first_set(report: dict) -> list:
    first = report.get("first_failure")
    return list(first["bonds"]) if first else []


def first_time(report: dict) -> float:
    first = report.get("first_failure")
    return first["time_s"] if first else float("nan")


def row(report: dict, label: str, reference: dict | None = None) -> str:
    rt = report["realtime"]
    cells = [
        label,
        f"{first_time(report):.3e}",
        str(len(first_set(report))),
        str(report["round_count"]),
        str(report["broken_bonds"]),
        str(report["components"]),
        str(report["largest_component"]),
        f"{sum(r['removed_energy_j'] for r in report['rounds']):.3f}",
        f"{report['timings_s']['fracture_window']:.3f}",
        f"{rt['fracture_window_ratio']:.0f}",
    ]
    if reference is not None:
        cells += [
            f"{jaccard(first_set(report), first_set(reference)):.2f}",
            f"{jaccard(report['broken_bond_indices'], reference['broken_bond_indices']):.2f}",
        ]
    return "| " + " | ".join(cells) + " |"


HEADER = ("| run | first failure s | first set | rounds | broken | pieces | largest | removed J | window wall s | window ratio |",
          "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
HEADER_REF = ("| run | first failure s | first set | rounds | broken | pieces | largest | removed J | window wall s | window ratio | J(first) vs ref | J(final) vs ref |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")


def trigger_summary(report: dict) -> str:
    rounds = report["rounds"]
    if not rounds:
        return "no rounds"
    over = [r["trigger_over_threshold"] for r in rounds]
    few = [r["fewest_live_neighbours"] for r in rounds]
    inflated = sum(1 for o in over if o > 3.0)
    degenerate = sum(1 for f in few if f <= 4)
    return (f"{len(rounds)} rounds; trigger/threshold max {max(over):.2f}, median {sorted(over)[len(over)//2]:.2f}; "
            f"{inflated} rounds triggered >3x threshold; {degenerate} rounds at a node with <=4 live neighbours")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mode", choices=["ladder", "scale", "materials", "truncation", "headline"])
    parser.add_argument("--exe", type=Path, default=ROOT / "build/agent/Release/banjo_modal_fracture_record.exe")
    parser.add_argument("--out", type=Path, default=ROOT / "build/modal-compare")
    parser.add_argument("--cells", default="8x8x2")
    parser.add_argument("--speed", type=float, default=12.0)
    parser.add_argument("--window", type=float, default=2e-3)
    parser.add_argument("--reference-dts", default="4e-6,2e-6,1e-6,5e-7")
    parser.add_argument("--sample-dts", default="4e-6,2e-6,1e-6,5e-7")
    parser.add_argument("--sizes", default="8x8x2,12x12x2,16x16x2")
    parser.add_argument("--materials", default="glass,oak,iron")
    parser.add_argument("--fractions", default="1,0.75,0.5,0.25")
    parser.add_argument("--settle", type=int, default=0)
    parser.add_argument("--basis-mode", default="update")
    parser.add_argument("--max-duration", type=float, default=3.0)
    args = parser.parse_args()
    exe = args.exe.resolve()
    if not exe.is_file():
        print(f"missing tool: {exe}", file=sys.stderr)
        return 2
    common = {"cells": args.cells, "speed": args.speed, "window": args.window, "settle": args.settle,
              "max_duration": args.max_duration}

    if args.mode == "ladder":
        refs = []
        print(f"## Reference (implicit, StepRestart) refinement ladder, {args.cells}, {args.speed} m/s, {args.window} s\n")
        print(*HEADER, sep="\n")
        for dt in args.reference_dts.split(","):
            report = run_tool(exe, args.out, f"ladder-implicit-{dt}", lane="implicit", reference_dt=dt, **common)
            refs.append((float(dt), report))
            print(row(report, f"implicit dt={dt}"))
            print(f"  {report['status']} {report['stop_reason']} :: {trigger_summary(report)}")
        finest = refs[-1][1]
        print(f"\n## Modal lane sampling ladder against the finest reference (dt={refs[-1][0]:g})\n")
        print(*HEADER_REF, sep="\n")
        for dt in args.sample_dts.split(","):
            report = run_tool(exe, args.out, f"ladder-modal-{dt}", lane="modal", sample_dt=dt, basis_mode=args.basis_mode, **common)
            print(row(report, f"modal sample dt={dt}", finest))
            print(f"  {report['status']} {report['stop_reason']} :: {trigger_summary(report)}")
        print("\n## Reference self-spread: each reference step against the finest\n")
        print(*HEADER_REF, sep="\n")
        for dt, report in refs:
            print(row(report, f"implicit dt={dt:g}", finest))
        return 0

    if args.mode == "scale":
        print(f"## Size scaling, {args.speed} m/s, {args.window} s window, modal sample dt 1e-6 vs implicit dt 1e-6\n")
        print(*HEADER_REF, sep="\n")
        for size in args.sizes.split(","):
            opts = dict(common)
            opts["cells"] = size
            reference = run_tool(exe, args.out, f"scale-implicit-{size}", lane="implicit", reference_dt=1e-6, **opts)
            print(row(reference, f"implicit {size} ({reference['lattice']['free_dofs']} dofs)", reference))
            print(f"  {reference['status']} {reference['stop_reason']} :: {trigger_summary(reference)}")
            modal = run_tool(exe, args.out, f"scale-modal-{size}", lane="modal", sample_dt=1e-6, basis_mode=args.basis_mode, **opts)
            print(row(modal, f"modal {size} basis {modal['timings_s']['basis_build']:.2f} s", reference))
            t = modal["window"]["timings_s"]
            print(f"  {modal['status']} {modal['stop_reason']} :: {trigger_summary(modal)}")
            print(f"  modal stages s: " + ", ".join(f"{k} {v:.3f}" for k, v in t.items()))
        return 0

    if args.mode == "materials":
        print(f"## Materials under identical conditions, {args.cells}, {args.speed} m/s, {args.window} s\n")
        print(*HEADER_REF, sep="\n")
        for material in args.materials.split(","):
            reference = run_tool(exe, args.out, f"material-implicit-{material}", lane="implicit", material=material, reference_dt=1e-6, **common)
            modal = run_tool(exe, args.out, f"material-modal-{material}", lane="modal", material=material, sample_dt=1e-6, basis_mode=args.basis_mode, **common)
            print(row(reference, f"implicit {material}", reference))
            print(row(modal, f"modal {material}", reference))
            w = modal["window"]
            print(f"  modal {material}: peak tensile {w['maximum_tensile_stretch']:.3e} (break {modal['lattice']['tensile_break_strain']:.3e}), "
                  f"peak shear {w['maximum_shear_strain']:.3e} (break {modal['lattice']['shear_break_strain']:.3e}), "
                  f"peak compressive {w['maximum_compressive_strain']:.3e} (break {modal['lattice']['compression_break_strain']:.3e}); "
                  f"{trigger_summary(modal)}")
        return 0

    if args.mode == "truncation":
        exact = run_tool(exe, args.out, "trunc-modal-1", lane="modal", sample_dt=1e-6, modes_fraction=1, basis_mode=args.basis_mode, **common)
        print(f"## Basis truncation, {args.cells}, {args.speed} m/s: retained fraction of modes vs the exact basis\n")
        print(*HEADER_REF, sep="\n")
        print(row(exact, "modal fraction 1 (exact)", exact))
        for fraction in args.fractions.split(","):
            if float(fraction) >= 1.0:
                continue
            report = run_tool(exe, args.out, f"trunc-modal-{fraction}", lane="modal", sample_dt=1e-6, modes_fraction=fraction, basis_mode=args.basis_mode, **common)
            print(row(report, f"modal fraction {fraction} ({report['window']['modes']} modes)", exact))
            print(f"  ledger residual {report['window']['ledger']['residual_j']:.2e} J; {trigger_summary(report)}")
        return 0

    if args.mode == "headline":
        opts = dict(common)
        opts["settle"] = 1
        for lane, extra in (("modal", {"sample_dt": 1e-6, "basis_mode": args.basis_mode}), ("implicit", {"reference_dt": 1e-6})):
            report = run_tool(exe, args.out, f"headline-{lane}-{args.cells}", lane=lane, **extra, **opts)
            rt, t, st = report["realtime"], report["timings_s"], report["settle"]
            print(f"## {lane} {args.cells} {args.speed} m/s")
            print(f"- simulated {rt['simulated_s']:.3f} s (window {rt['window_simulated_s']:.4f} s + settle {rt['settle_simulated_s']:.3f} s); "
                  f"compute wall {rt['compute_wall_s']:.3f} s; ratio {rt['ratio']:.3f} (excluding basis build {rt['ratio_excluding_basis_build']:.3f}); meets 1.1x: {rt['meets_rule']}")
            print(f"- stages s: scene {t['scene_build']:.3f}, basis {t['basis_build']:.3f}, fracture window {t['fracture_window']:.3f}, handoff {t['handoff']:.3f}, settle {t['settle']:.3f}")
            print(f"- fracture: {report['round_count']} rounds, {report['broken_bonds']} bonds, {report['components']} pieces (largest {report['largest_component']} cells); "
                  f"{st['fragments']} fragments handed to Jolt as {st['collision_boxes']} boxes; settled {st['settled']} at {st['settled_time_s']:.3f} s; "
                  f"peak fragment speed {st['peak_fragment_speed_m_s']:.2f} m/s; coarsening loss {st['coarsening_kinetic_loss_j']:.3f} J")
            print(f"- {trigger_summary(report)}")
            print(f"- recording: {report['_summary']['output']} (json {report['_summary']['json_wall_s']:.2f} s)\n")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
