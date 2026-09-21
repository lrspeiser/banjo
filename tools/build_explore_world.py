#!/usr/bin/env python3
"""Compose the Explore valley: one of everything Banjo can make, in a place you
can walk around.

    BANJO_LIVE_ENGINE=.../banjo_live_world_run.exe python tools/build_explore_world.py

Writes playground/rooms/explore.json, which world_room serves as the `explore`
scene. Re-run it to rebuild the world from scratch; nothing is hand-edited in
the JSON, so the layout lives here where it can be read and argued with.

WHY A BUILDER AND NOT A HAND-WRITTEN ROOM. Three things have to be true of every
object, and none of them can be seen by reading the JSON:

  * it has to stand ON the ground, and the valley's ground is not a plane. A
    body placed at y=0 on flat terrain falls, because flat terrain's surface is
    at 0.80 m, not 0 (measured). So the heightfield is read from a live world
    and every object is seated on it.
  * it has to stand on ground flat ENOUGH, and dry. A table on a 20% slope
    topples in the first second, which is honest physics and a poor welcome.
    Each area is placed on the flattest patch near where the layout wants it
    that is not under the river or the pond.
  * it has to BE the thing at the room's cell size. A part no thicker than a
    cell can fall between cell centres and come out as no cells at all: drawn
    where the Workshop draws it, the chair's seat and the stool's top vanish at
    40 mm, and what stood in the valley was four loose sticks that fell over.
    Each product is sampled where it comes out whole (whole_matter), and the
    world is checked with the engine before it is written.

The budget it works inside ([[banjo-world-budget]]): 16,000 cells for the
scene, 120 objects, a body of at most 6 m, and cells costing the cube of the
cell size. At 40 mm all seven crafted products together are 3,381 cells, so
there is room for the material bank and the tools beside them.
"""
from __future__ import annotations

import base64
import dataclasses
import itertools
import json
import math
import os
import struct
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "playground")]

import fracture_lab            # noqa: E402
import live_session            # noqa: E402
import workshop_sparse_trial as sparse   # noqa: E402
from mcp import (core_use, engine_materials, interaction_points,  # noqa: E402
                 workshop_components, workshop_matter_metrics, workshop_visual)

# 60 mm loses the kettle entirely. 40 mm keeps the table and bench as drawn,
# keeps the chair, stool and shelf unit once they are sampled a few millimetres
# over (whole_matter), and still cannot keep the kettle's walls and handle or
# the cart's axles, wherever its grid falls.
CELL_M = 0.04
OUT = ROOT / "playground" / "rooms" / "explore.json"
# The river that runs through the valley, as the room declares it.
WATER = {"discharge_m3_s": 0.35}

# Jolt holds the ground to within this of the heightfield's samples
# (JoltWorld::addGroundPatch, max_error_m), so the surface a thing meets can
# stand this much above what the samples say.
GROUND_ERROR_M = 0.002
# How far a thing that has LANDED can rest inside the ground, as the engine
# rests things. Every product starts above the ground (checked strictly), but a
# joined body's cells sit on the room's 40 mm grid, so it starts up to a cell
# above the ground and falls the rest of the way when the world starts, and the
# landing leaves an overlap that depends on where in a step it lands. Jolt
# only pushes apart an overlap deeper than its 20 mm penetration slop
# (PhysicsSettings::mPenetrationSlop, which the engine leaves at Jolt's
# default), so a shallower one is kept for good. Measured against Jolt's own
# ground (a ray cast down in a bare valley): 0 to 3.8 mm for everything here,
# and 8 mm for the chair dropped from 7 cm instead. Deeper than the slop, the
# engine has let a thing INTO the ground rather than rested it on it.
LANDED_M = 0.02
# A product still standing leans a degree or so on the valley's gentle ground;
# one that has toppled has turned by tens of degrees.
STANDING_DEG = 10.0

# The eight the engine knows, in the order they are laid out along the bank.
# Scene spelling, not catalogue spelling: "alumina ceramic" is "ceramic" here.
MATERIALS = ["oak", "iron", "glass", "concrete", "ceramic", "ice", "aluminum", "rubber"]

# What each block is for, said in its name, because the name is what the room
# shows under the crosshair.
# The one thing each product is for, as a saved program (mcp/core_use.py). The
# four steps a portable program may use are inspect, place, strike and
# push_forward; anything richer belongs to the room's own action DSL.
PRIMARY_USE = {
    "table":      {"label": "Shove it along",   "steps": [{"do": "push_forward"}]},
    "bench":      {"label": "Shove it along",   "steps": [{"do": "push_forward"}]},
    "chair":      {"label": "Push it in",       "steps": [{"do": "push_forward"}]},
    "stool":      {"label": "Push it in",       "steps": [{"do": "push_forward"}]},
    "shelf-unit": {"label": "Shove it along",   "steps": [{"do": "push_forward"}]},
    "cart":       {"label": "Push the cart",    "steps": [{"do": "push_forward"}]},
    "kettle":     {"label": "Set it down",      "steps": [{"do": "place"}]},
}

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
    knows where the ground actually is -- and where the water is on it.

    The valley is opened with the room's own water, because the river and the
    pond are already full when the room opens, and the flattest ground in the
    valley is the bottom of the river: the first build stood the chair and the
    bench in it, their legs in the water."""
    spec = fracture_lab.validate({
        "algorithm": "lattice", "cell_m": CELL_M, "duration_s": 1.0,
        "terrain": {"generate": "valley"}, "water": dict(WATER),
        "bodies": [{"name": "sounding", "shape": "box", "material": "oak",
                    "size_mm": [100, 100, 100], "center_mm": [0, 8000, 0]}]})
    with tempfile.TemporaryDirectory() as tmp:
        session = live_session.Session(engine, spec, Path(tmp))
        try:
            terrain = session.send(op="terrain").get("terrain") or {}
            water = session.send(op="poses").get("water") or {}
        finally:
            session.close()
    ground = ground_of(terrain)
    ground["wet"] = wet_of(water)
    return ground


def ground_of(terrain: dict) -> dict:
    grid = terrain["grid"]
    raw = base64.b64decode(terrain["heights_b64"], validate=True)
    heights = struct.unpack("<" + "f" * (len(raw) // 4), raw)
    return {"nx": int(grid["nx"]), "nz": int(grid["nz"]), "cell": float(grid["cell_m"]),
            "x0": float(grid["x0_m"]), "z0": float(grid["z0_m"]), "h": heights, "wet": set()}


def wet_of(water: dict) -> set[tuple[int, int]]:
    """Which of the ground's samples stand under water, as the room's water
    reports it: a box of the terrain grid, [i0, j0, ni, nj], and in it the water
    surface of each cell in millimetres over `base_m`, 0 where it is dry (the
    way world.js reads it to draw the water)."""
    i0, j0, ni, nj = (water.get("box") or [0, 0, 0, 0])[:4]
    if not ni or not water.get("surface_mm_b64"):
        return set()
    raw = base64.b64decode(water["surface_mm_b64"], validate=True)
    mm = struct.unpack("<" + "H" * (len(raw) // 2), raw)
    return {(i0 + i, j0 + j) for j in range(nj) for i in range(ni) if mm[j * ni + i]}


def _sample(ground: dict, i: int, j: int) -> float:
    i = min(ground["nx"] - 1, max(0, i))
    j = min(ground["nz"] - 1, max(0, j))
    return ground["h"][j * ground["nx"] + i]


def height_at(ground: dict, x: float, z: float) -> float:
    return _sample(ground, int(round((x - ground["x0"]) / ground["cell"])),
                   int(round((z - ground["z0"]) / ground["cell"])))


def surface_at(ground: dict, x: float, z: float) -> float:
    """The ground as Jolt holds it, not the nearest sample to it: each square of
    the heightfield is two flat triangles split along its (i,j)-(i+1,j+1)
    diagonal (HeightFieldShape.cpp), so between samples it is a plane."""
    u, v = (x - ground["x0"]) / ground["cell"], (z - ground["z0"]) / ground["cell"]
    i, j = math.floor(u), math.floor(v)
    fx, fz = u - i, v - j
    h00, h10 = _sample(ground, i, j), _sample(ground, i + 1, j)
    h01, h11 = _sample(ground, i, j + 1), _sample(ground, i + 1, j + 1)
    if fz >= fx:
        return h00 + fz * (h01 - h00) + fx * (h11 - h01)
    return h00 + fx * (h10 - h00) + fz * (h11 - h10)


def ground_under(ground: dict, lo_xz, hi_xz) -> float:
    """The highest the ground gets anywhere under a footprint from lo to hi.

    Between its samples the ground is flat triangles, so it never rises above
    the corners of the squares it is made of: the highest sample of every square
    the footprint reaches bounds it everywhere, which is the install path's rule
    (workshop_install._terrain_floor). Anything less can start a thing INSIDE
    the ground, and the engine then leaves it there: Jolt only pushes out an
    overlap deeper than its 20 mm penetration slop, so a leg started 10 mm in
    stays 10 mm in for good.
    """
    i0 = math.floor((lo_xz[0] - ground["x0"]) / ground["cell"])
    i1 = math.ceil((hi_xz[0] - ground["x0"]) / ground["cell"])
    j0 = math.floor((lo_xz[1] - ground["z0"]) / ground["cell"])
    j1 = math.ceil((hi_xz[1] - ground["z0"]) / ground["cell"])
    return max(_sample(ground, i, j) for j in range(j0, j1 + 1)
               for i in range(i0, i1 + 1)) + GROUND_ERROR_M


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


def wet_near(ground: dict, x: float, z: float, radius_m: float) -> bool:
    """Whether any of the ground within `radius_m` of (x, z) is under water."""
    i0 = math.floor((x - radius_m - ground["x0"]) / ground["cell"])
    i1 = math.ceil((x + radius_m - ground["x0"]) / ground["cell"])
    j0 = math.floor((z - radius_m - ground["z0"]) / ground["cell"])
    j1 = math.ceil((z + radius_m - ground["z0"]) / ground["cell"])
    return any((i, j) in ground["wet"] for j in range(j0, j1 + 1) for i in range(i0, i1 + 1))


def flattest_near(ground: dict, want_xz, radius_m: float, taken, search_m: float = 2.5):
    """The flattest spot within `search_m` of where the layout wants this, that
    does not stand on top of anything already put down, or in the water.

    All three matter. Without the flatness a table is asked to stand on a
    hillside and topples in its first second; without the occupancy check the
    search happily walks two things onto the same ground, and the validator
    refuses the room -- "bench-2 and shelf-unit both claim 1 of the same cells"
    -- which is the owner's rule that nothing overlaps what is already there.
    And the water is there too: the flattest ground in a valley is the bed of
    its river, which is where the chair and the bench were stood until the
    search was told where the water is.

    Where that leaves nowhere within `search_m`, it looks further, the same
    distance again each time. The layout says where a thing is wanted, and the
    chair's and the bench's places turned out to be in the river.
    """
    step = ground["cell"]
    for reach in (search_m, 2 * search_m, 3 * search_m, 4 * search_m):
        best, best_score = None, math.inf
        n = int(reach / step)
        for a in range(-n, n + 1):
            for b in range(-n, n + 1):
                x, z = want_xz[0] + a * step, want_xz[1] + b * step
                if abs(x) > 17.0 or abs(z) > 13.0:
                    continue
                # A hand's width of daylight between one thing and the next,
                # and between a thing and the water's edge.
                if any(math.dist((x, z), (tx, tz)) < radius_m + tr + 0.25
                       for tx, tz, tr in taken):
                    continue
                if wet_near(ground, x, z, radius_m + 0.25):
                    continue
                lo, hi = flatness(ground, x, z, radius_m)
                score = 4.0 * (hi - lo) + 0.02 * math.dist((x, z), want_xz)
                if score < best_score:
                    best, best_score = (x, z), score
        if best is not None:
            lo, hi = flatness(ground, *best, radius_m)
            return best, hi - lo
    raise ValueError(f"nowhere dry and clear within {reach} m of {want_xz} to stand this")


# --------------------------------------------------------------------------
# What goes in it
# --------------------------------------------------------------------------

def _not_whole(design, matter) -> str:
    """Why these cells are not the design as ONE thing, or "" when they are.

    The install path's own test (workshop_matter_metrics: every part present,
    every cell joined face to face to the rest), and one material, because the
    room builds every box of a product from the same one."""
    try:
        got = workshop_matter_metrics.measure(
            matter, expected_components=[p.name for p in design.parts])["measured"]
    except ValueError as exc:            # no cells at all
        return str(exc)
    why = []
    if got["missing_components"]:
        why.append(", ".join(got["missing_components"]) + " vanish")
    if len(got["islands"]) != 1:
        why.append(f"it comes apart into {len(got['islands'])} pieces")
    if len({engine_materials.canonical(c["material"]) for c in matter["cells"]}) != 1:
        why.append("it is more than one material")
    return "; ".join(why)


def whole_matter(design, over):
    """The design's cells at the room's cell size, sampled where it comes out
    as the whole of itself -- and the design, moved to where it was sampled.

    Which cells a part fills depends on where the grid falls across it: a cell
    is the part's when the cell's centre is inside the part. A seat exactly one
    cell thick, drawn half a cell off the grid (the chair's, 420-460 mm up), has
    a cell centre on each of its faces and none inside it, so it comes out as no
    cells at all, and the chair as four loose sticks and a back floating over
    them. The grid is the room's; the design has no say where it falls. So
    slide the design across it, a few millimetres at a time, and take a place
    where every part is there and joined.

    As drawn, when that is whole (the table and bench are). Otherwise the whole
    sampling closest to the design's own volume, and then the least moved. When
    no sampling is whole, the design as drawn, and why it is not whole, so the
    caller can say so rather than stand it up silently. The kettle's 10 mm walls
    stand 250 and 210 mm apart, 6.25 and 5.25 cells, so no grid puts a cell
    centre inside both walls of a pair; the cart's iron axles either vanish or
    land in cells its oak already claims.
    """
    def sample(d):
        moved = dataclasses.replace(design, parts=[
            dataclasses.replace(p, center_m=tuple(p.center_m[a] + d[a] for a in range(3)))
            for p in design.parts])
        try:
            matter = workshop_visual.matter_document(moved, over, cell_size_m=CELL_M,
                                                     exterior_only=False)
        except ValueError as exc:        # two materials claiming one cell
            return moved, None, str(exc)
        return moved, matter, _not_whole(moved, matter)

    drawn = sample((0.0, 0.0, 0.0))
    if drawn[1] is not None and not drawn[2]:
        return drawn[0], drawn[1], (0.0, 0.0, 0.0), ""
    volume = sum(p.volume_m3() for p in design.parts) / CELL_M ** 3
    phases = [k * CELL_M / 8 for k in range(8)]
    best = None
    for d in itertools.product(phases, phases, phases):
        moved, matter, why = sample(d)
        if matter is None or why:
            continue
        score = (abs(matter["total_cells"] - volume), sum(v * v for v in d), d)
        if best is None or score < best[0]:
            best = (score, moved, matter, d)
    if best is None:
        if drawn[1] is None:
            raise ValueError(f"{design.design_id}: {drawn[2]}")
        return drawn[0], drawn[1], (0.0, 0.0, 0.0), drawn[2]
    return best[1], best[2], best[3], ""


def product_bodies(kind: str, root: str, at_xz, ground: dict, *, material=None):
    """A Workshop product as room bodies, seated on the ground at (x, z).

    The same decomposition the install path uses, and the same test that the
    cells are the whole product. Where the design as drawn is not whole at the
    room's cell size it is sampled a few millimetres over (whole_matter), which
    the install path does not yet do: it refuses such a design. The last thing
    returned says why a product is not whole when nothing could make it so.
    """
    params = {"material": material} if material else {}
    if kind in PRIMARY_USE:
        params["primary_use"] = PRIMARY_USE[kind]
    design, over = workshop_components.design_from_spec(
        {"kind": kind, "design_id": root, "parameters": params})
    design, matter, phase, broken = whole_matter(design, over)
    cells = sparse._grid_set(matter)
    if not cells:
        raise ValueError(f"{kind} resolves to nothing at {CELL_M} m cells")
    part_of = sparse._grid_parts(matter)
    lo = [min(g[a] for g in cells) for a in range(3)]
    hi = [max(g[a] for g in cells) for a in range(3)]
    # Seated on the HIGHEST ground under its whole footprint, not on the ground
    # under its middle. Seated at the middle, half a thing standing on a slope
    # starts inside the hill, and the engine does not push it out -- it falls
    # through, which is how the shelf unit vanished on the first build.
    # And seated on the cell ABOVE that ground, never the nearest cell: rounding
    # to the nearest put the chair's legs 7-10 mm, the cart 12 mm and the kettle
    # 15 mm inside the ground, where Jolt left them (ground_under).
    across = (round(at_xz[0] / CELL_M) - (lo[0] + hi[0]) // 2,
              round(at_xz[1] / CELL_M) - (lo[2] + hi[2]) // 2)
    floor = ground_under(ground,
                         ((lo[0] + across[0]) * CELL_M, (lo[2] + across[1]) * CELL_M),
                         ((hi[0] + 1 + across[0]) * CELL_M, (hi[2] + 1 + across[1]) * CELL_M))
    shift = (across[0], math.ceil(floor / CELL_M) - lo[1], across[1])
    placed = {tuple(g[a] + shift[a] for a in range(3)) for g in cells}
    if any(phase):
        print(f"    sampled {', '.join(f'{v * 1000:g}' for v in phase)} mm over, "
              f"where every part of it comes out and joins up ({len(cells)} cells)")
    labels = {tuple(g[a] + shift[a] for a in range(3)): f"{root}/{p}"
              for g, p in part_of.items()}
    material_name = engine_materials.canonical(next(iter(matter["cells"]))["material"])
    bodies = [sparse._box_body(root if i == 0 else f"{root}-{i}", box, CELL_M,
                               material_name, root, part)
              for i, (box, part) in enumerate(sparse.decompose_by_part(placed, labels))]
    # What it is for, and where a thing can be set down on it -- the same two
    # calls the install path makes (workshop_install.py), including its way of
    # taking the centre of mass from the placed cells, so a product standing
    # here behaves exactly like one the Workshop put here.
    # From the DESIGN's cells, not the placed ones. The points come out of
    # for_design in the design's own frame, so the centre they are rebased onto
    # has to be in that frame too. Taking it from the placed cells put the
    # bench's top 4.9 m away from the bench -- exactly the distance the bench
    # had been moved.
    com = [sum((g[a] + 0.5) * CELL_M for g in cells) / len(cells) for a in range(3)]
    return (bodies, core_use.installed(design, root),
            interaction_points.installed(design, root, com), broken)


def block(name: str, material: str, at_xz, ground: dict, side_mm: float = 200.0) -> dict:
    """One loose block of a material, sitting on the ground: something to pick
    up, throw, and find out what it does when it lands.

    200 mm, so that every one of them CAN be picked up. At 320 mm five of the
    eight weighed more than the 73 kg a hand lifts (banjo_mcp.HAND_LIFTS_KG) --
    glass 82, concrete 79, aluminium 88, ceramic 128, iron 258 kg -- and "take
    the glass block" was refused. At 200 mm the heaviest, iron, is 63 kg. It is
    also five whole 40 mm cells, which the room's validation asks of a box."""
    half = side_mm / 2000.0
    floor = ground_under(ground, (at_xz[0] - half, at_xz[1] - half),
                         (at_xz[0] + half, at_xz[1] + half))
    return {"name": name, "shape": "box", "material": material,
            "size_mm": [side_mm, side_mm, side_mm],
            "center_mm": [at_xz[0] * 1000.0, (floor + half) * 1000.0, at_xz[1] * 1000.0],
            "velocity_m_s": [0.0, 0.0, 0.0]}


def with_mace(spec: dict, at_xz) -> dict:
    """The mace, built into the room by the MCP's build_recipe -- the same oak
    handle, iron head, 0.2 m tie and "Swing it" as a mace the room's chat
    builds -- and the room taken back out of the MCP world, as server._stand
    does when it stands a thing up."""
    import room_world
    world_id = room_world.open_room(spec)
    try:
        answer = room_world.call(world_id, "build_recipe", {"recipe": "mace", "at_m": list(at_xz)})
        if "error" in answer:
            raise SystemExit(f"the mace would not build at {at_xz}: {answer['error']}")
        print(f"  mace           built at ({at_xz[0]:+6.2f}, {at_xz[1]:+6.2f}): "
              f"{', '.join(answer['parts'])}, tied")
        return room_world.export_spec(room_world.entry_of(world_id))
    finally:
        room_world.close_room(world_id)


def compose(ground: dict) -> tuple[dict, dict, tuple]:
    """The room, and which of its products are not whole at its cell size (and
    why), so the check after it can hold every other product to being one
    thing still standing."""
    bodies: list[dict] = []
    actions: list[dict] = []
    points: list[dict] = []
    taken: list[tuple[float, float, float]] = []
    apart: dict[str, str] = {}

    def stand(kind, root, at):
        got, use, where, broken = product_bodies(kind, root, at, ground)
        bodies.extend(got)
        actions.append(use)
        points.append(where)
        if broken:
            apart[root] = broken
            print(f"    NOT WHOLE at {CELL_M * 1000:g} mm cells, wherever the grid falls: "
                  f"{broken}. It stands as the pieces that are left.")

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
        # A metre apart: at 0.75 m there was nowhere between them to set down a
        # block taken from the next one, and every put-down there was refused.
        at = (bank[0] - 1.5 + (i % 4) * 1.0, bank[1] - 0.5 + (i // 4) * 1.0)
        name = BLOCK_NOTE[material]
        bodies.append(block(name, material, at, ground))
        # A block is the thing you carry, so its one use is setting it down --
        # which is the step that goes looking for somewhere to set it ON.
        actions.append({"body": name, "label": "Set it down", "primary": True,
                        "steps": [{"do": "place"}]})

    # 2. THE WORKSHOP YARD. The furniture family, standing as it would be used.
    for kind, want, radius in (("table", (0.0, 0.0), 1.1),
                               ("bench", (3.4, 0.8), 1.2),
                               ("chair", (-2.6, 1.4), 0.7),
                               ("stool", (-2.6, -1.4), 0.5),
                               ("shelf-unit", (3.2, -2.8), 0.9)):
        stand(kind, kind, area(kind, want, radius))

    # No cart and no kettle. At the valley's 40 mm cells neither can be built
    # whole -- the kettle's 10 mm walls, bottom and handle, and the cart's axles
    # and bearing mounts, get no cells wherever the grid falls -- so each stood
    # as the pieces that were left, and taking one up took a single panel. The
    # owner's call (2026-09-21): leave them out until they can be built whole.

    # 3. A MACE: the owner's own example of taking up the whole of a thing while
    #    its moving part still moves. Only its place is chosen here; it is built
    #    after the rest (with_mace), by the MCP's own build_recipe.
    mace_at = area("mace", (-4.0, -4.4), 0.6, " -- the mace")

    print(f"  {len(actions)} things have a use of their own; "
          f"{sum(1 for r in points for p in r['points'] if p['kind'] in ('surface', 'container'))}"
          f" places to set something down")
    return {"algorithm": "lattice", "cell_m": CELL_M, "plasticity": "on",
            "terrain": {"generate": "valley"},
            "water": dict(WATER),
            "bodies": bodies,
            "actions": actions,
            "interaction_points": points}, apart, mace_at


# --------------------------------------------------------------------------
# The check: every body as the engine holds it, against the ground under it
# --------------------------------------------------------------------------

def _turn(q, v):
    """v turned by the unit quaternion q = (w, x, y, z)."""
    w, x, y, z = q
    tx, ty, tz = 2 * (y * v[2] - z * v[1]), 2 * (z * v[0] - x * v[2]), 2 * (x * v[1] - y * v[0])
    return (v[0] + w * tx + y * tz - z * ty,
            v[1] + w * ty + z * tx - x * tz,
            v[2] + w * tz + x * ty - y * tx)


def lowest_gap(body: dict, ground: dict, cell: float) -> float:
    """How far a body's lowest corner stands above the ground right under that
    corner; negative is inside it.

    Every corner of every cell, turned as the engine has the body turned. A
    body's centre less half its height is not its underside once it leans:
    a 440 mm leg lying on its side has its centre 20 mm off the ground, and
    reading it as standing put it "200 mm in the ground"."""
    cells = body.get("cells_local_m") or []
    halves = [(cell / 2.0,) * 3] * len(cells)
    if not cells:                        # a body that carries no cells: its own box
        cells, halves = [[0.0, 0.0, 0.0]], [tuple(d / 2.0 for d in body["dimensions_m"])]
    q, p = body["orientation_wxyz"], body["position_m"]
    gap = math.inf
    for c, (hx, hy, hz) in zip(cells, halves):
        for corner in itertools.product((-hx, hx), (-hy, hy), (-hz, hz)):
            r = _turn(q, (c[0] + corner[0], c[1] + corner[1], c[2] + corner[2]))
            x, y, z = p[0] + r[0], p[1] + r[1], p[2] + r[2]
            gap = min(gap, y - surface_at(ground, x, z))
    return gap


def lean_deg(body: dict) -> float:
    """How far the body's own up has turned from straight up."""
    return math.degrees(math.acos(max(-1.0, min(1.0, _turn(body["orientation_wxyz"],
                                                            (0.0, 1.0, 0.0))[1]))))


def check(opened: dict, settled: dict, apart: dict) -> list[str]:
    """What is wrong with the room as it opens and once it has settled: the
    owner's rule that nothing is below the ground, and that every product the
    room could build whole is still one thing, standing."""
    faults = []
    ground = ground_of(opened["terrain"])
    cell = float(opened.get("cell_size_m") or CELL_M)
    at_open = {}
    for b in opened["bodies"]:
        gap = lowest_gap(b, ground, cell)
        at_open[b["name"]] = min(gap, at_open.get(b["name"], math.inf))
        if gap < 0.0:
            faults.append(f"{b['name']} starts {-gap * 1000:.1f} mm inside the ground")
    pieces = Counter(b["name"] for b in settled["bodies"])
    print(f"  {'':16s} {'pieces':>6s} {'lean':>9s}  lowest corner above the ground")
    print(f"  {'':16s} {'':>6s} {'':>9s}  {'as built':>9s} {'settled':>9s}")
    for name in sorted(pieces):
        mine = [b for b in settled["bodies"] if b["name"] == name]
        gap = min(lowest_gap(b, ground, cell) for b in mine)
        lean = max(lean_deg(b) for b in mine)
        note = f"  not whole: {apart[name]}" if name in apart else ""
        print(f"  {name:16s} {len(mine):6d} {lean:5.1f} deg  "
              f"{at_open.get(name, math.nan) * 1000:+7.1f} mm {gap * 1000:+7.1f} mm{note}")
        if gap < -LANDED_M:
            faults.append(f"{name} is {-gap * 1000:.1f} mm inside the ground after settling")
        if name not in apart:
            if len(mine) != 1:
                faults.append(f"{name} came apart into {len(mine)} pieces")
            elif lean > STANDING_DEG:
                faults.append(f"{name} fell over ({lean:.0f} degrees)")
    return faults


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
    spec, apart, mace_at = compose(ground)
    spec = with_mace(spec, mace_at)
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
            opened = session.send(op="poses")                 # as built, before a step
            session.send(op="step", dt=1 / 120, n=2)
            start = time.monotonic()
            session.send(op="step", dt=1 / 120, n=240)      # two seconds of world
            pace = 2.0 / (time.monotonic() - start)
            settled = session.send(op="poses")
            water = (session.send(op="environment").get("environment") or {}).get("water") or {}
        finally:
            session.close()
    print(f"  ran at {pace:.0f}x realtime with {len(settled.get('bodies') or [])} bodies in it")
    faults = check(opened, settled, apart)
    # The engine's own word on what stands in the river or the pond.
    for wet in water.get("bodies_in_water") or []:
        faults.append(f"{wet['name']} is standing in the water "
                      f"({wet['submerged_m3'] * 1000:.1f} litres of it under)")
    if faults:
        for fault in faults:
            print(f"  REFUSED: {fault}", file=sys.stderr)
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
