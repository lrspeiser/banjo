"""Turn the Algorithm 2 accuracy matrix into the checkpoint's tables.

Reads build/runs/algo2/matrix.json (written by algo2-accuracy-matrix.py) and
prints, per scene, the reference against each Algorithm 2 variant: first-failure
set overlap, broken bonds, pieces, largest piece, removed energy and wall time.
Bond indices are directly comparable because both lanes build the same lattice
(tests/griffith_cascade_tests.cpp proves it bond for bond).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

VARIANTS = ["reference", "algo2", "algo2-strain", "algo2-plate-mass"]


def get(node: dict, *path, default=None):
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    return node


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--matrix", type=Path, default=Path("build/runs/algo2/matrix.json"))
    args = parser.parse_args()
    data = json.loads(args.matrix.read_text(encoding="utf-8"))

    for name, scene in data.items():
        note = get(scene, "scene", "note", default="")
        print(f"\n=== {name}: {note} ===")
        reference = scene.get("reference", {})
        ref_ff = set(get(reference, "first_failure", "bond_indices", default=[]) or [])
        header = (f"{'variant':<17}{'status':<9}{'bonds':>7}{'pieces':>8}{'largest':>9}{'mass kg':>10}"
                  f"{'energy J':>12}{'wall s':>10}{'cascade s':>11}{'ff |A|':>8}{'ff cap':>8}{'ff Jac':>8}")
        print(header)
        print("-" * len(header))
        for variant in VARIANTS:
            entry = scene.get(variant)
            if entry is None:
                continue
            if entry.get("status") != "complete":
                print(f"{variant:<17}{entry.get('status','?'):<9} {str(entry.get('reason',''))[:96]}")
                continue
            ff = set(get(entry, "first_failure", "bond_indices", default=[]) or [])
            cap = len(ff & ref_ff) if ref_ff else 0
            jaccard = (cap / len(ff | ref_ff)) if (ff | ref_ff) else float("nan")
            print(f"{variant:<17}{'ok':<9}"
                  f"{entry.get('broken_bonds', 0):>7}"
                  f"{entry.get('components', 0):>8}"
                  f"{entry.get('largest_component_cells', 0):>9}"
                  f"{entry.get('largest_component_mass_kg', 0.0):>10.3f}"
                  f"{entry.get('removed_energy_j', 0.0):>12.3f}"
                  f"{entry.get('_process_wall_s', 0.0):>10.2f}"
                  f"{entry.get('cascade_wall_s', float('nan')):>11.4f}"
                  f"{len(ff):>8}{cap:>8}{jaccard:>8.2f}")
        # Cost detail for the Algorithm 2 run.
        algo2 = scene.get("algo2", {})
        if algo2.get("status") == "complete":
            p = algo2.get("precompute", {})
            print(f"  algo2 precompute: {algo2.get('precompute_s', 0):.2f} s "
                  f"(cached {algo2.get('precompute_cached')}), {algo2.get('precompute_bytes', 0)/1048576:.0f} MiB, "
                  f"{p.get('modes')} modes, {p.get('strike_cells_ready')}/{p.get('strike_cells')} strike columns, "
                  f"eigen {p.get('eigen_s', 0):.2f} s, influence {p.get('influence_s', 0):.2f} s, "
                  f"peak {p.get('peak_s', 0):.2f} s")
            c = algo2.get("contact", {})
            print(f"  algo2 contact:    J = {c.get('impulse_n_s', 0):.4f} N s over "
                  f"{c.get('footprint_cells')} cells (effective mass {c.get('footprint_effective_mass_kg', 0)*1000:.1f} g), "
                  f"budget {c.get('energy_budget_j', 0):.3f} J, spent {algo2.get('energy_spent_j', 0):.4f} J")
            ref_c = reference.get("contact", {})
            if ref_c:
                print(f"  reference contact: J = {ref_c.get('impulse_n_s', 0):.4f} N s accumulated over the "
                      f"whole lattice phase, dissipated {ref_c.get('energy_budget_j', 0):.3f} J")
    return 0


if __name__ == "__main__":
    sys.exit(main())
