#!/usr/bin/env python3
"""A 100 mm ball of each material onto a concrete floor, at a ladder of speeds.

This is the table in the README under "Eight materials, and what they actually
do", and the point of it is that anyone can run it and get the same thing. It
drives the engine through the Python binding, so it needs nothing but a built
library:

    BANJO_LIBRARY=build/release/Release/banjo.dll python scripts/drop-ladder.py
    python scripts/drop-ladder.py ceramic ice        # just the two you want

Each case starts the ball 40 mm above a concrete slab already moving downward
at the speed named, cuts both at 20 mm cells (what `/world?scene=bench` uses),
and runs half a second of world time. What it reports per case is what the
engine said: "held", "dent" (the lattice ran and left a permanent set), or the
number of pieces the ball came apart into.

Starting the ball at a speed rather than dropping it from a height is
deliberate -- it makes the speed at the contact exact, so the ladder is the
same on every machine. It is not the same method as the per-material thresholds
in docs/api/materials.md, which bisect a drop height, so the two are not
expected to agree to the last digit.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bindings" / "python"))

from banjo import World  # noqa: E402

CELL_M = 0.02
BALL_M = 0.10
SPEEDS_M_S = (5.0, 10.0, 20.0, 40.0, 80.0)
MATERIALS = ("iron", "aluminium", "oak", "rubber", "glass", "ceramic", "concrete", "ice")
RUN_S = 0.5
STEP_S = 1.0 / 240.0


def scene(material: str, speed_m_s: float) -> dict:
    """The ball just above an anchored concrete slab, already coming down."""
    return {"bodies": [
        {"name": "floor", "shape": "box", "material": "concrete",
         "dimensions_m": [1.2, 0.2, 1.2], "center_m": [0.0, -0.1, 0.0], "anchored": True},
        {"name": "ball", "shape": "sphere", "material": material,
         "dimensions_m": [BALL_M, BALL_M, BALL_M], "center_m": [0.0, 0.14, 0.0],
         "velocity_m_s": [0.0, -speed_m_s, 0.0]},
    ]}


def one(material: str, speed_m_s: float) -> dict:
    with World(scene(material, speed_m_s), cell_size_m=CELL_M) as world:
        before = len(world.bodies())
        outcomes: set[str] = set()
        for _ in range(int(RUN_S / STEP_S)):
            world.advance(STEP_S)
            outcome = world.last_outcome
            if outcome and outcome != "nothing":
                outcomes.add(outcome)
        after = list(world.bodies())
        pieces = len([b for b in after if b.name.startswith("ball")])
        return {"material": material, "speed_m_s": speed_m_s,
                "bodies_before": before, "bodies_after": len(after),
                "ball_pieces": pieces, "broke": len(after) > before,
                "outcomes": sorted(outcomes)}


def word(row: dict) -> str:
    if row.get("error"):
        return "refused"
    if row["broke"]:
        return f"{row['ball_pieces']} pieces"
    return "dent" if "dented" in row["outcomes"] else "held"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("materials", nargs="*", default=None,
                        help=f"which to run; all eight by default ({', '.join(MATERIALS)})")
    parser.add_argument("--json", type=Path, help="also write every case to this file")
    args = parser.parse_args(argv)

    wanted = args.materials or list(MATERIALS)
    unknown = [m for m in wanted if m not in MATERIALS]
    if unknown:
        parser.error(f"not a material in the catalogue: {', '.join(unknown)}")
    if not os.environ.get("BANJO_LIBRARY"):
        print("BANJO_LIBRARY is not set; the binding will look in build/integration/Release "
              "and the other usual places.", file=sys.stderr)

    rows = []
    header = f"{'':11s}" + "".join(f"{f'{s:g} m/s':>12s}" for s in SPEEDS_M_S)
    print(header)
    for material in wanted:
        cells = []
        for speed in SPEEDS_M_S:
            try:
                row = one(material, speed)
            except Exception as exc:                      # a refused case is data too
                row = {"material": material, "speed_m_s": speed, "error": str(exc)[:160]}
            rows.append(row)
            cells.append(word(row))
        print(f"{material:11s}" + "".join(f"{c:>12s}" for c in cells), flush=True)

    if args.json:
        args.json.write_text(json.dumps(rows, indent=1) + "\n", encoding="utf-8")
        print(f"\nevery case: {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
