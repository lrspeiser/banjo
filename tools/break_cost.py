#!/usr/bin/env python3
"""What a break costs in the world, measured (docs/what-a-break-costs.md).

    BANJO_LIVE_ENGINE=.../banjo_live_world_run.exe python tools/break_cost.py

The same strike, in the world's own lane, at three cell sizes under each of the
two failure laws. An iron ball is dropped on a plate lying on the ground; when
the world offers the plate as breakable it is broken, and the run reports what
that cost: the bonds the lattice removed, the crack area they stand for, the
elastic energy that left with them, and the energy per square metre of new
crack that implies -- against the material's own fracture energy.

The point of the table is the third column. A crack in oak should cost oak's
1,000 J/m2 whatever size the cells are. Under the strain-threshold law the
charge goes with the cell size, because that law has no length in it; under the
energy-scaled law the removal stretch is set from the material's fracture
energy, so the charge is the material's own.

Prints a Markdown table and, with --json PATH, writes the runs to a file.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "playground")]

import fracture_lab      # noqa: E402
import live_session      # noqa: E402

CELLS_MM = (20.0, 10.0, 5.0)
LAWS = ("strain-threshold", "energy-scaled")
MATERIALS = ("glass", "oak")
DT = 1 / 240
# The plate, and the ball that breaks it: a 60 mm iron ball at 30 m/s, straight
# down onto the middle of a plate lying on the ground. Small on purpose -- the
# 5 mm run is 30 x 12 x 30 cells, and a room is capped at 16,000 -- and three
# cells thick at the coarsest, because a plate one cell thick has almost no
# bending stiffness (docs/one-cell-is-not-a-plate.md).
PLATE_MM = (150.0, 60.0, 150.0)
BALL_MM = 60.0
SPEED_M_S = 30.0


def room(material: str, cell_mm: float, law: str) -> dict:
    """A plate of `material` on the ground with an iron ball above it, falling."""
    plate_y = PLATE_MM[1] / 2.0
    ball_y = PLATE_MM[1] + BALL_MM / 2.0 + 10.0
    return {"algorithm": "lattice", "cell_m": cell_mm / 1000.0, "failure_law": law, "plasticity": "off",
            "duration_s": 1.0,
            "bodies": [
                {"name": "plate", "shape": "box", "material": material,
                 "size_mm": list(PLATE_MM), "center_mm": [0.0, plate_y, 0.0]},
                {"name": "ball", "shape": "sphere", "material": "iron",
                 "size_mm": [BALL_MM, BALL_MM, BALL_MM], "center_mm": [0.0, ball_y, 0.0],
                 "velocity_m_s": [0.0, -SPEED_M_S, 0.0]}]}


def strike(engine: Path, material: str, cell_mm: float, law: str) -> dict:
    """Open the room, let the ball land, break what the world offers, and
    report what it cost."""
    spec = fracture_lab.validate(room(material, cell_mm, law))
    began = time.monotonic()
    with tempfile.TemporaryDirectory() as tmp:
        session = live_session.Session(engine, spec, Path(tmp))
        try:
            broke = None
            for _ in range(int(0.6 / (DT * 12))):        # up to 0.6 s of world
                reply = session.send(op="step", dt=DT, n=12)
                offered = [n for n in reply.get("breakable") or [] if n == "plate"]
                if not offered:
                    continue
                broke = session.send(op="fracture", name="plate", wait=True)
                break
            if broke is None:
                return {"material": material, "cell_mm": cell_mm, "law": law, "outcome": "never offered"}
            cost = broke.get("cost") or {}
            return {"material": material, "cell_mm": cell_mm, "law": law,
                    "outcome": broke.get("outcome"), "pieces": broke.get("pieces"),
                    "wall_s": round(time.monotonic() - began, 1), **cost}
        finally:
            session.close()


def table(runs: list[dict]) -> str:
    head = ("| Material | Cells | Law | Charge for a crack (J/m2) | The material's own (J/m2) | "
            "Pieces | Bonds (pulled/crushed/sheared) | Energy out (J) | Crack (mm2) | Measured (J/m2) |")
    rule = "|---|---:|---|---:|---:|---:|---|---:|---:|---:|"
    rows = []
    for r in runs:
        if r.get("outcome") in (None, "never offered"):
            rows.append(f"| {r['material']} | {r['cell_mm']:.0f} mm | {r['law']} | "
                        f"(the world never offered it to break) | | | | | | |")
            continue
        rows.append(
            f"| {r['material']} | {r['cell_mm']:.0f} mm | {r['law']} | {r.get('law_energy_j_m2', 0):,.0f} | "
            f"{r.get('declared_energy_j_m2', 0):,.0f} | {r.get('pieces', 0)} | {r.get('broken_bonds', 0)} "
            f"({r.get('tensile_bonds', 0)}/{r.get('compressive_bonds', 0)}/{r.get('shear_bonds', 0)}) | "
            f"{r.get('removed_energy_j', 0):,.2f} | {r.get('crack_area_m2', 0) * 1e6:,.0f} | "
            f"{r.get('crack_energy_j_m2', 0):,.0f} |")
    return "\n".join([head, rule, *rows])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, help="write the runs here")
    parser.add_argument("--material", action="append", choices=MATERIALS, help="just these")
    parser.add_argument("--cell-mm", action="append", type=float, help="just these cell sizes")
    args = parser.parse_args()
    engine = os.environ.get("BANJO_LIVE_ENGINE")
    if not engine or not Path(engine).is_file():
        print("Set BANJO_LIVE_ENGINE to a built banjo_live_world_run", file=sys.stderr)
        return 2
    engine = Path(engine)
    runs = []
    for material in args.material or MATERIALS:
        for cell_mm in args.cell_mm or CELLS_MM:
            for law in LAWS:
                run = strike(engine, material, cell_mm, law)
                runs.append(run)
                print(f"  {material} {cell_mm:.0f} mm {law}: {run.get('outcome')} "
                      f"{run.get('pieces', 0)} pieces, {run.get('broken_bonds', 0)} bonds, "
                      f"{run.get('removed_energy_j', 0):.2f} J, "
                      f"{run.get('crack_energy_j_m2', 0):,.0f} J/m2 measured, "
                      f"{run.get('law_energy_j_m2', 0):,.0f} J/m2 charged "
                      f"(its own {run.get('declared_energy_j_m2', 0):,.0f}); bonds pulled apart "
                      f"{run.get('tensile_bonds', 0)}, crushed {run.get('compressive_bonds', 0)}, sheared "
                      f"{run.get('shear_bonds', 0)}; {run.get('wall_s', 0)} s",
                      flush=True)
    print()
    print(table(runs))
    if args.json:
        args.json.write_text(json.dumps(runs, indent=1), encoding="utf-8", newline="\n")
        print(f"\nWrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
