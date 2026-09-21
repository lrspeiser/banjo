#!/usr/bin/env python3
"""Compose the Explore valley: one of everything Banjo can make, in a place you
can walk around.

    BANJO_LIVE_ENGINE=.../banjo_live_world_run.exe python tools/build_explore_world.py

Writes playground/rooms/explore.json, which world_room serves as the `explore`
scene. Re-run it to rebuild the world from scratch; nothing is hand-edited in
the JSON, so the layout lives here where it can be read and argued with.

WHY A BUILDER AND NOT A HAND-WRITTEN ROOM. Two things have to be true of every
object, and neither can be known without the engine:

  * it has to stand ON the ground, and the valley's ground is not a plane. A
    body placed at y=0 on flat terrain falls, because flat terrain's surface is
    at 0.80 m, not 0 (measured). So the heightfield is read from a live world
    and every object is seated on it.
  * it has to stand on ground flat ENOUGH. A table on a 20% slope topples in
    the first second, which is honest physics and a poor welcome. Each area is
    placed on the flattest patch near where the layout wants it.

The budget it works inside ([[banjo-world-budget]]): 16,000 cells for the
scene, 120 objects, a body of at most 6 m, and cells costing the cube of the
cell size. At 40 mm all seven crafted products together are 2,664 cells, so
there is room for the material bank and the tools beside them.
"""
from __future__ import annotations

import base64
import json
import math
import os
import struct
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "playground")]

import fracture_lab            # noqa: E402
import live_session            # noqa: E402
import workshop_sparse_trial as sparse   # noqa: E402
from mcp import engine_materials, workshop_components, workshop_visual  # noqa: E402

CELL_M = 0.04                  # 60 mm loses the kettle entirely; 40 mm keeps every part
OUT = ROOT / "playground" / "rooms" / "explore.json"

# The eight the engine knows, in the order they are laid out along the bank.
# Scene spelling, not catalogue spelling: "alumina ceramic" is "ceramic" here.
MATERIALS = ["oak", "iron", "glass", "concrete", "ceramic", "ice", "aluminum", "rubber"]

# What each block is for, said in its name, because the name is what the room
# shows under the crosshair.
BLOCK_NOTE = {
    "oak": "oak block", "iron": "iron block", "glass": "glass block",
    "concrete": "concrete block", "ceramic": "ceramic block", "ice": "ice block",
    "aluminum": "aluminium block", "rubber": "rubber block",
}


# --------------------------------------------------------------------------
# The ground
# --------------------------------------------------------------------------

def read_ground(engine: Path) -> dict:
    """Open a bare valley and read its heightfield, so everything after this
    knows where the ground actually is."""
    spec = fracture_lab.validate({
        "algorithm": "lattice", "cell_m": CELL_M, "duration_s": 1.0,
        "terrain": {"generate": "valley"},
        "bodies": [{"name": "sounding", "shape": "box", "material": "oak",
                    "size_mm": [100, 100, 100], "center_mm": [0, 8000, 0]}]})
    with tempfile.TemporaryDirectory() as tmp:
        session = live_session.Session(engine, spec, Path(tmp))
        try:
            terrain = session.send(op="terrain").get("terrain") or {}
        finally:
            session.close()
    grid = terrain["grid"]
    raw = base64.b64decode(terrain["heights_b64"], validate=True)
    heights = struct.unpack("<" + "f" * (len(raw) // 4), raw)
    return {"nx": int(grid["nx"]), "nz": int(grid["nz"]), "cell": float(grid["cell_m"]),
            "x0": float(grid["x0_m"]), "z0": float(grid["z0_m"]), "h": heights}


def height_at(ground: dict, x: float, z: float) -> float:
    i = min(ground["nx"] - 1, max(0, int(round((x - ground["x0"]) / ground["cell"]))))
    j = min(ground["nz"] - 1, max(0, int(round((z - ground["z0"]) / ground["cell"]))))
    return ground["h"][j * ground["nx"] + i]


def flatness(ground: dict, x: float, z: float, radius_m: float) -> tuple[float, float]:
    """The highest and lowest ground over a square patch. A small spread means a
    thing set down there stays where it was put."""
    step = ground["cell"]
    lo, hi = math.inf, -math.inf
    n = max(1, int(radius_m / step))
    for a in range(-n, n + 1):
        for b in range(-n, n + 1):
            v = height_at(ground, x + a * step, z + b * step)
            lo, hi = min(lo, v), max(hi, v)
    return lo, hi


def flattest_near(ground: dict, want_xz, radius_m: float, taken, search_m: float = 2.5):
    """The flattest spot within `search_m` of where the layout wants this, that
    does not stand on top of anything already put down.

    Both halves matter. Without the flatness a table is asked to stand on a
    hillside and topples in its first second; without the occupancy check the
    search happily walks two things onto the same ground, and the validator
    refuses the room -- "bench-2 and shelf-unit both claim 1 of the same cells"
    -- which is the owner's rule that nothing overlaps what is already there.
    """
    best, best_score = None, math.inf
    step = ground["cell"]
    n = int(search_m / step)
    for a in range(-n, n + 1):
        for b in range(-n, n + 1):
            x, z = want_xz[0] + a * step, want_xz[1] + b * step
            if abs(x) > 17.0 or abs(z) > 13.0:
                continue
            # A hand's width of daylight between one thing and the next.
            if any(math.dist((x, z), (tx, tz)) < radius_m + tr + 0.25
                   for tx, tz, tr in taken):
                continue
            lo, hi = flatness(ground, x, z, radius_m)
            score = 4.0 * (hi - lo) + 0.02 * math.dist((x, z), want_xz)
            if score < best_score:
                best, best_score = (x, z), score
    if best is None:
        raise ValueError(f"nowhere clear within {search_m} m of {want_xz} to stand this")
    lo, hi = flatness(ground, *best, radius_m)
    return best, hi - lo


# --------------------------------------------------------------------------
# What goes in it
# --------------------------------------------------------------------------

def product_bodies(kind: str, root: str, at_xz, ground: dict, *, material=None) -> list[dict]:
    """A Workshop product as room bodies, seated on the ground at (x, z).

    The same decomposition the install path uses, so a thing standing in the
    world is the same matter the Workshop measured and the bench broke.
    """
    params = {"material": material} if material else {}
    design, over = workshop_components.design_from_spec(
        {"kind": kind, "design_id": root, "parameters": params})
    matter = workshop_visual.matter_document(design, over, cell_size_m=CELL_M,
                                             exterior_only=False)
    cells = sparse._grid_set(matter)
    if not cells:
        raise ValueError(f"{kind} resolves to nothing at {CELL_M} m cells")
    part_of = sparse._grid_parts(matter)
    lo = [min(g[a] for g in cells) for a in range(3)]
    hi = [max(g[a] for g in cells) for a in range(3)]
    # Seated on the HIGHEST ground under its whole footprint, not on the ground
    # under its middle. Seated at the middle, half a thing standing on a slope
    # starts inside the hill, and the engine does not push it out -- it falls
    # through, which is how the shelf unit vanished on the first build. A
    # millimetre of daylight on top of that, because resting exactly on the
    # ground and resting one cell inside it read the same in a spec.
    reach = max(hi[0] - lo[0], hi[2] - lo[2]) * CELL_M / 2.0
    seat = flatness(ground, at_xz[0], at_xz[1], reach)[1] + 0.002
    shift = (round(at_xz[0] / CELL_M) - (lo[0] + hi[0]) // 2,
             round(seat / CELL_M) - lo[1],
             round(at_xz[1] / CELL_M) - (lo[2] + hi[2]) // 2)
    placed = {tuple(g[a] + shift[a] for a in range(3)) for g in cells}
    labels = {tuple(g[a] + shift[a] for a in range(3)): f"{root}/{p}"
              for g, p in part_of.items()}
    material_name = engine_materials.canonical(next(iter(matter["cells"]))["material"])
    return [sparse._box_body(root if i == 0 else f"{root}-{i}", box, CELL_M,
                             material_name, root, part)
            for i, (box, part) in enumerate(sparse.decompose_by_part(placed, labels))]


def block(name: str, material: str, at_xz, ground: dict, side_mm: float = 320.0) -> dict:
    """One loose block of a material, sitting on the ground: something to pick
    up, throw, and find out what it does when it lands."""
    return {"name": name, "shape": "box", "material": material,
            "size_mm": [side_mm, side_mm, side_mm],
            "center_mm": [at_xz[0] * 1000.0,
                          (flatness(ground, at_xz[0], at_xz[1], side_mm / 2000.0)[1]
                           + side_mm / 2000.0 + 0.002) * 1000.0,
                          at_xz[1] * 1000.0],
            "velocity_m_s": [0.0, 0.0, 0.0]}


def compose(ground: dict) -> dict:
    bodies: list[dict] = []
    taken: list[tuple[float, float, float]] = []

    def area(key, want, radius, note=""):
        at, spread = flattest_near(ground, want, radius, taken)
        taken.append((at[0], at[1], radius))
        print(f"  {key:14s} at ({at[0]:+6.2f}, {at[1]:+6.2f})  ground "
              f"{height_at(ground, *at):5.2f} m, falls {spread * 1000:4.0f} mm across it{note}")
        return at

    # 1. THE MATERIAL BANK. Eight blocks in a row, one of each thing the engine
    #    knows, so what a material IS can be found out by picking it up and
    #    throwing it at something rather than by reading a table.
    bank = area("bank", (-7.0, -4.0), 1.9, " -- the material bank")
    for i, material in enumerate(MATERIALS):
        at = (bank[0] - 1.1 + (i % 4) * 0.75, bank[1] - 0.4 + (i // 4) * 0.8)
        bodies.append(block(BLOCK_NOTE[material], material, at, ground))

    # 2. THE WORKSHOP YARD. The furniture family, standing as it would be used.
    for kind, want, radius in (("table", (0.0, 0.0), 1.1),
                               ("bench", (3.4, 0.8), 1.2),
                               ("chair", (-2.6, 1.4), 0.7),
                               ("stool", (-2.6, -1.4), 0.5),
                               ("shelf-unit", (3.2, -2.8), 0.9)):
        at = area(kind, want, radius)
        bodies += product_bodies(kind, kind, at, ground)

    # 3. THE CART, on its own so there is room to push it.
    bodies += product_bodies("cart", "cart", area("cart", (0.0, 5.4), 1.5), ground)

    # 4. THE KETTLE, which is the one iron thing among the oak.
    bodies += product_bodies("kettle", "kettle", area("kettle", (6.0, 3.8), 0.6), ground)

    spec = {"algorithm": "lattice", "cell_m": CELL_M, "plasticity": "on",
            "terrain": {"generate": "valley"},
            "water": {"discharge_m3_s": 0.35},
            "bodies": bodies}
    return spec


# --------------------------------------------------------------------------

def main() -> int:
    engine = os.environ.get("BANJO_LIVE_ENGINE")
    if not engine or not Path(engine).is_file():
        print("Set BANJO_LIVE_ENGINE to a built banjo_live_world_run", file=sys.stderr)
        return 2
    engine = Path(engine)

    print("Reading the valley's ground ...")
    ground = read_ground(engine)
    print(f"  {ground['nx']}x{ground['nz']} at {ground['cell']} m, "
          f"{min(ground['h']):.2f} m to {max(ground['h']):.2f} m")

    print("Laying the world out ...")
    spec = compose(ground)
    validated = fracture_lab.validate(spec)
    cells = sum(b.get("cells", 0) for b in validated["bodies"])
    print(f"  {len(validated['bodies'])} bodies, {cells:,} cells "
          f"({100 * cells / 16000:.0f}% of the 16,000 the lane allows)")
    if cells > 16000:
        print("  REFUSED: over the cell cap; use a coarser cell or fewer things", file=sys.stderr)
        return 1

    print("Opening it, and letting it settle ...")
    with tempfile.TemporaryDirectory() as tmp:
        session = live_session.Session(engine, validated, Path(tmp))
        try:
            session.send(op="step", dt=1 / 120, n=2)
            import time
            start = time.monotonic()
            session.send(op="step", dt=1 / 120, n=240)      # two seconds of world
            pace = 2.0 / (time.monotonic() - start)
            state = session.send(op="poses")
        finally:
            session.close()
    standing = state.get("bodies") or []
    sunk = [b["name"] for b in standing if b["position_m"][1] < -1.0]
    print(f"  ran at {pace:.0f}x realtime with {len(standing)} bodies in it")
    print(f"  below the ground: {sunk or 'none'}")
    if sunk:
        print("  REFUSED: something fell through; the seating is wrong", file=sys.stderr)
        return 1

    # The AUTHORED spec, not the validated one. validate() adds fields of its
    # own -- cells, cells_per_axis, seated, snapped, requested_plate_m -- and
    # then refuses a spec that arrives carrying them ("Unknown fracture lab
    # fields"), so a room saved from its own output cannot be opened. Validation
    # above is the check; this is the room.
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(spec, indent=1, sort_keys=True), encoding="utf-8", newline="\n")
    print(f"Wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
