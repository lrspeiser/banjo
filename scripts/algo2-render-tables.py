"""Render the checkpoint's measured tables straight out of the run JSON.

Keeps the document's numbers and the measurements the same object: nothing in
the checkpoint's tables is typed by hand.

    python scripts/algo2-render-tables.py --matrix build/runs/algo2/matrix.json \
        --cost build/runs/algo2-cost/cost.json --materials build/runs/algo2-materials
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

SCENE_TITLES = {
    "base": "base: 250 x 200 x 20 mm, 1,000 cells at 10 mm, 60 mm ball at 6.264 m/s, centre",
    "thicker": "thicker: 250 x 200 x 30 mm, 1,500 cells at 10 mm, same striker",
    "faster": "higher drop: the base plate at 9.90 m/s (5.0 m)",
    "offcentre": "off-centre: the base scene struck at (60, 40) mm",
    "heavyslow": "heavy slow striker: 200 mm iron ball (32.9 kg) at 1.0 m/s",
    "contract500": "the shared 500-cell contract scene, one cell through the thickness",
}
VARIANT_TITLES = {
    "reference": "reference (explicit lattice)",
    "algo2": "algo2, Griffith, footprint impulse",
    "algo2-strain": "algo2, shared strain criterion, footprint impulse",
    "algo2-plate-mass": "algo2, Griffith, whole-plate impulse",
}


def cell(entry, key, fmt="{}"):
    if entry.get("status") != "complete":
        return "-"
    value = entry.get(key)
    return "-" if value is None else fmt.format(value)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, default=Path("build/runs/algo2/matrix.json"))
    parser.add_argument("--cost", type=Path, default=Path("build/runs/algo2-cost/cost.json"))
    parser.add_argument("--materials", type=Path, default=Path("build/runs/algo2-materials"))
    args = parser.parse_args()

    if args.matrix.is_file():
        data = json.loads(args.matrix.read_text(encoding="utf-8"))
        print("### Accuracy table\n")
        print("| scene | lane | impulse N s | broken bonds | pieces | largest piece cells | removed energy J | wall s |")
        print("|---|---|---:|---:|---:|---:|---:|---:|")
        for name, title in SCENE_TITLES.items():
            scene = data.get(name)
            if not scene:
                continue
            for variant, vtitle in VARIANT_TITLES.items():
                entry = scene.get(variant)
                if entry is None:
                    continue
                if entry.get("status") != "complete":
                    print(f"| {title if variant == 'reference' else ''} | {vtitle} | "
                          f"refused: {str(entry.get('reason','')).replace('banjo_fracture_algo2: ','')[:150]} | | | | |")
                    continue
                impulse = (entry.get("contact") or {}).get("impulse_n_s")
                print(f"| {title if variant == 'reference' else ''} | {vtitle} | "
                      f"{impulse:.3f} | {entry.get('broken_bonds')} | {entry.get('components')} | "
                      f"{entry.get('largest_component_cells')} | {entry.get('removed_energy_j'):.3f} | "
                      f"{entry.get('_process_wall_s'):.2f} |")
            print("| | | | | | | |")

    if args.cost.is_file():
        cost = json.loads(args.cost.read_text(encoding="utf-8"))
        print("\n### Cost against plate size\n")
        print("| cells | bonds | free dofs | strike columns | cold precompute s | eigen / influence / peak s | "
              "tables MiB | warm process s | cascade s | events |")
        print("|---:|---:|---:|---|---:|---|---:|---:|---:|---:|")
        for name, entry in cost.items():
            cold, warm = entry.get("cold", {}), entry.get("warm", {})
            if cold.get("status") != "complete":
                print(f"| {name} | refused: {str(cold.get('reason',''))[:110]} | | | | | | | | |")
                continue
            p = cold["precompute"]
            print(f"| {cold['cells']} | {cold['bonds']} | {p['modes']} | "
                  f"{p['strike_cells_ready']}/{p['strike_cells']} | {cold['precompute_s']:.2f} | "
                  f"{p['eigen_s']:.2f} / {p['influence_s']:.2f} / {p['peak_s']:.2f} | "
                  f"{cold['precompute_bytes']/1048576:.0f} | {warm.get('_process_wall_s', float('nan')):.3f} | "
                  f"{warm.get('cascade_wall_s', float('nan')):.4f} | {warm.get('events')} |")

    if args.materials.is_dir():
        print("\n### Glass, oak and iron under identical conditions\n")
        print("| material | lane | broken bonds | pieces | largest piece cells | removed energy J | wall s |")
        print("|---|---|---:|---:|---:|---:|---:|")
        for material in ("glass", "oak", "iron"):
            for suffix, lane in (("", "algo2 (Griffith)"), ("-reference", "reference")):
                path = args.materials / f"{material}{suffix}.out.json"
                if not path.is_file() or path.stat().st_size == 0:
                    err = args.materials / f"{material}{suffix}.err"
                    reason = err.read_text(encoding="utf-8").strip().splitlines()[-1][:120] if err.is_file() and err.stat().st_size else "not run"
                    print(f"| {material} | {lane} | refused: {reason} | | | | |")
                    continue
                entry = json.loads(path.read_text(encoding="utf-8"))
                print(f"| {material} | {lane} | {entry.get('broken_bonds')} | {entry.get('components')} | "
                      f"{entry.get('largest_component_cells')} | {entry.get('removed_energy_j'):.3f} | "
                      f"{entry.get('compute_wall_s'):.2f} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
