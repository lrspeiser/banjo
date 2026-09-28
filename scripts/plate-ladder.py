#!/usr/bin/env python3
"""A ball dropped on a plate one cell thick, at a ladder of drop heights.

This is the table in docs/plate-bending.md, and the point of it is the same as
scripts/drop-ladder.py: anyone can run it and get the same thing back. It needs
nothing but a built library.

    BANJO_LIBRARY=build/release/Release/banjo.dll python scripts/plate-ladder.py
    python scripts/plate-ladder.py --thickness-cells 2      # the control
    python scripts/plate-ladder.py --spanned                # bridged on piers
    python scripts/plate-ladder.py --material oak --heights 5 10

A sheet one cell thick is the case plate bending exists for: every node in it
has its neighbours in one plane, so before that term the strain it could state
was the stretching of that plane, and hitting it flat -- which loads it in
bending -- was very nearly invisible. Two controls are worth running beside it:
the same plate two cells thick, which measures its own bending and should be
untouched, and `--spanned`, which bridges it between two piers so the span
carries the blow in tension a coplanar neighbourhood could always see.

The plate lies on the ground with NOTHING under it but the ground, because a
plate backed by a rigid slab cannot bend and the blow is then a crushing one --
measured, bending on or off makes no difference to a plate lying on a slab. The
ball starts at the drop height and falls, so the height is a height and not a
label for a speed, and the run is long enough for the fall, the blow and the
pieces landing.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bindings" / "python"))

from banjo import World  # noqa: E402

CELL_M = 0.02
PLATE_M = 0.30
BALL_M = 0.10
PIER_H = 0.20
GRAVITY_M_S2 = 9.81
HEIGHTS_M = (3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0, 12.0)
STEP_S = 1.0 / 120.0
STEPS = 900          # 7.5 s: the fall, the blow, and the pieces coming to rest


def scene(material: str, height_m: float, thickness_cells: int, spanned: bool) -> dict:
    """The plate on the ground or bridged on piers, the ball up at its height."""
    thick = thickness_cells * CELL_M
    lift = PIER_H if spanned else 0.0
    bodies = [{"name": "plate", "shape": "box", "material": material,
               "dimensions_m": [PLATE_M, thick, PLATE_M],
               "center_m": [0.0, lift + 0.5 * thick, 0.0]}]
    if spanned:
        for sign in (-1, 1):
            bodies.append({"name": f"pier{sign}", "shape": "box", "material": "iron",
                           "dimensions_m": [0.04, PIER_H, PLATE_M],
                           "center_m": [sign * 0.13, 0.5 * PIER_H, 0.0], "anchored": True})
    bodies.append({"name": "ball", "shape": "sphere", "material": "iron",
                   "dimensions_m": [BALL_M, BALL_M, BALL_M],
                   "center_m": [0.0, height_m, 0.0]})
    return {"bodies": bodies}


def one(material: str, height_m: float, thickness_cells: int, spanned: bool) -> dict:
    with World(scene(material, height_m, thickness_cells, spanned),
               cell_size_m=CELL_M) as world:
        before = len(world.bodies())
        outcomes: set[str] = set()
        for _ in range(STEPS):
            world.advance(STEP_S)
            outcome = world.last_outcome
            if outcome and outcome != "nothing":
                outcomes.add(outcome)
        after = list(world.bodies())
        plate = [b for b in after if b.name.startswith("plate")]
        return {"material": material, "height_m": height_m,
                "arriving_m_s": round(math.sqrt(2.0 * GRAVITY_M_S2 * height_m), 6),
                "thickness_cells": thickness_cells, "spanned": spanned,
                "bodies_before": before, "bodies_after": len(after),
                "plate_pieces": len(plate),
                "plate_mass_kg": round(sum(b.mass_kg for b in plate), 4),
                "biggest_piece_kg": round(max((b.mass_kg for b in plate), default=0.0), 4),
                "broke": len(plate) > 1, "outcomes": sorted(outcomes)}


def word(row: dict) -> str:
    if row.get("error"):
        return "refused"
    if row["plate_pieces"] > 1:
        return f"{row['plate_pieces']} pieces"
    return "dent" if "dented" in row["outcomes"] else "whole"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--material", default="glass", help="the plate's material (default glass)")
    parser.add_argument("--thickness-cells", type=int, default=1,
                        help="how many cells thick the plate is (default 1)")
    parser.add_argument("--spanned", action="store_true",
                        help="bridge the plate between two iron piers instead of laying it down")
    parser.add_argument("--heights", type=float, nargs="*", default=None,
                        help="drop heights in metres (default 3 to 12)")
    parser.add_argument("--json", type=Path, help="also write every case to this file")
    args = parser.parse_args(argv)

    heights = args.heights or list(HEIGHTS_M)
    if args.thickness_cells < 1:
        parser.error("a plate is at least one cell thick")
    if not os.environ.get("BANJO_LIBRARY"):
        print("BANJO_LIBRARY is not set; the binding will look in build/integration/Release "
              "and the other usual places.", file=sys.stderr)

    print(f"{args.material} plate {PLATE_M * 1000:.0f} x {PLATE_M * 1000:.0f} mm, "
          f"{args.thickness_cells} cell(s) thick at {CELL_M * 1000:.0f} mm, "
          f"{'bridged on piers' if args.spanned else 'lying on the ground'}, "
          f"{BALL_M * 1000:.0f} mm iron ball dropped on it")
    print(f"{'dropped':>9s}  {'arriving':>11s}  {'outcome':>10s}  {'biggest piece':>14s}")
    rows = []
    for height in heights:
        try:
            row = one(args.material, height, args.thickness_cells, args.spanned)
        except Exception as exc:                          # a refused case is data too
            row = {"material": args.material, "height_m": height, "error": str(exc)[:160]}
        rows.append(row)
        speed = row.get("arriving_m_s")
        biggest = row.get("biggest_piece_kg")
        print(f"{height:8.0f}m  "
              f"{'' if speed is None else f'{speed:7.2f} m/s'}  {word(row):>10s}  "
              f"{'' if biggest is None else f'{biggest:8.3f} kg'}", flush=True)

    if args.json:
        args.json.write_text(json.dumps(rows, indent=1) + "\n", encoding="utf-8")
        print(f"\nevery case: {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
