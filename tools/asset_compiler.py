"""Compile a declared assembly of meshes into a Banjo blueprint.

A part is converted once, by the content of its geometry, and placed many times
by instance transform. What comes out carries the occupancy the lattice would be
built from, a box decomposition for the parts that need only to be collided
with, the mass properties the generator would compute, the capability flags the
part earned, and the failures it collected. A failure never repairs the part:
a slot too narrow to survive the bond horizon is refused, not widened, and a
plate thinner than a cell is refused, not thickened.

Nothing here imports the engine. `src/matter/Lattice.hpp` is not in the public
`include/` tree and no C API entry point takes a set of cells, so the grid
convention and the neighbour rule are REPRODUCED here and pinned by
tests/asset_compiler_tests.py against the numbers the C++ states.

Usage:

    python tools/asset_compiler.py path/to/assembly.json --out blueprint.json

See docs/asset-compiler.md for the pipeline and the categories.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any

BLUEPRINT_SCHEMA = "banjo.asset-blueprint.v1"
ASSEMBLY_SCHEMA = "banjo.asset-assembly.v1"

# Declared units only. A mesh file carries no unit, so guessing one is the most
# expensive mistake available here: a part authored in millimetres and read as
# metres is a 1e9 volume error, and every check downstream passes happily.
UNIT_M = {"m": 1.0, "cm": 0.01, "mm": 0.001, "in": 0.0254}

# The catalogue the engine compiles (src/material/MaterialCatalog.cpp), with the
# densities it uses. A name outside this list is not a material the lattice can
# be built from, so the part keeps visual and collision and loses the rest.
MATERIAL_DENSITY_KG_M3 = {
    "glass": 2500.0,      # soda_lime_glass
    "oak": 700.0,
    "iron": 7870.0,
    "concrete": 2400.0,
    "ceramic": 3900.0,    # alumina_ceramic
    "ice": 917.0,         # freshwater_ice
    "aluminum": 2700.0,   # aluminum_6061_t6
    "rubber": 1100.0,     # natural_rubber
}

# What the playground's lattice lane will accept for a whole scene
# (playground/fracture_lab.py, ALGORITHMS["lattice"]["max_cells"]). The
# generator's own refusal is 4,000,000 cells (src/matter/Lattice.cpp:350), which
# is a guard on the generator rather than a statement that such an object
# belongs in a live room, so the room's number is the default here.
ROOM_CELL_BUDGET = 16_000
LATTICE_NODE_BUDGET = 4_000_000

# The generator's default neighbour horizon (src/matter/Lattice.hpp:113).
DEFAULT_HORIZON_CELLS = 2

CAPABILITIES = ("visual", "static_collision", "movable_rigid", "editable_voxels",
                "articulated", "powered", "functionally_tested")

FAILURES = ("rights_unverified", "units_ambiguous", "invalid_solid", "feature_below_resolution",
            "required_gap_lost", "material_unknown", "connection_ambiguous",
            "physics_budget_exceeded", "functional_test_failed")

# A connection of one of these kinds means the parts are handed to ONE
# generateVoxelLattice call, as a join group is in playground/fracture_lab.py:
# the bonds cross the seam and the result is one object. The others leave two
# objects that meet through contact.
FUSED_KINDS = ("fixed",)
ARTICULATED_KINDS = ("hinge", "slider")
CONNECTION_KINDS = FUSED_KINDS + ARTICULATED_KINDS + ("contact",)

# Vertices closer together than this are one vertex when the mesh is checked for
# being closed. An OBJ exported per-face repeats every corner, and without the
# weld every edge of such a file looks unshared and every solid looks open.
WELD_M = 1.0e-9

# The transverse pair for each scan axis, cyclic so that the projected signed
# area of a triangle equals the scan-axis component of its normal. That identity
# is what makes the winding sign correct without a second cross product.
AXIS_PAIR = ((1, 2), (2, 0), (0, 1))

# Where the thin dimension is read off the span lengths. A curved surface always
# produces slivers at its silhouette, so the thinnest span in a part is not the
# part's thickness; the tenth percentile BY VOLUME is, because a sliver carries
# almost none of the volume and a genuinely thin wall carries all of it.
THICKNESS_PERCENTILE = 0.10


def _fail(category: str, detail: str) -> dict[str, str]:
    if category not in FAILURES:
        raise ValueError(f"unknown failure category {category!r}")
    return {"category": category, "detail": detail}


# ---------------------------------------------------------------- reading a mesh

def read_obj(path: Path) -> dict[str, Any]:
    """Vertices and triangles from a Wavefront OBJ. Nothing is inferred.

    Only `v` and `f` are read. Normals and texture coordinates are ignored: this
    is a solid compiler, and a declared normal that disagrees with the winding
    would only be a second opinion about which way is out.
    """
    vertices: list[tuple[float, float, float]] = []
    triangles: list[tuple[int, int, int]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        field = line.split()
        if not field or field[0].startswith("#"):
            continue
        if field[0] == "v":
            if len(field) < 4:
                raise ValueError(f"{path.name}:{number}: a v line needs three numbers")
            vertices.append((float(field[1]), float(field[2]), float(field[3])))
        elif field[0] == "f":
            if len(field) < 4:
                raise ValueError(f"{path.name}:{number}: a face needs at least three corners")
            corner = []
            for token in field[1:]:
                index = int(token.split("/")[0])
                # OBJ is 1-based; a negative index counts back from the last
                # vertex read so far, which is why this cannot be done after
                # the whole file is in.
                resolved = index - 1 if index > 0 else len(vertices) + index
                if not 0 <= resolved < len(vertices):
                    raise ValueError(f"{path.name}:{number}: vertex index {index} is out of range")
                corner.append(resolved)
            # A polygon is fanned. Every face the fixtures emit is a triangle
            # already; the fan is for files from elsewhere.
            for i in range(1, len(corner) - 1):
                triangles.append((corner[0], corner[i], corner[i + 1]))
    if not triangles:
        raise ValueError(f"{path.name}: no faces")
    return {"vertices": vertices, "triangles": triangles}


def scaled(mesh: dict[str, Any], unit: str) -> dict[str, Any]:
    """The same mesh in metres, by the unit the assembly DECLARED."""
    if unit not in UNIT_M:
        raise ValueError(f"unit must be one of {sorted(UNIT_M)}")
    factor = UNIT_M[unit]
    return {"vertices": [(x * factor, y * factor, z * factor) for x, y, z in mesh["vertices"]],
            "triangles": list(mesh["triangles"])}


def mesh_report(mesh: dict[str, Any]) -> dict[str, Any]:
    """Is this a closed solid, and what is its exact volume and area?

    Volume is the divergence theorem over the triangles, which is exact for any
    closed mesh and is the yardstick the occupancy is measured against. Closure
    is counted on welded vertex positions, not on file indices.
    """
    verts = mesh["vertices"]
    canonical: dict[tuple[int, int, int], int] = {}
    weld: list[int] = []
    for x, y, z in verts:
        key = (round(x / WELD_M), round(y / WELD_M), round(z / WELD_M))
        weld.append(canonical.setdefault(key, len(canonical)))

    directed: dict[tuple[int, int], int] = {}
    volume = 0.0
    area = 0.0
    degenerate = 0
    for a, b, c in mesh["triangles"]:
        pa, pb, pc = verts[a], verts[b], verts[c]
        cross = ((pb[1] - pa[1]) * (pc[2] - pa[2]) - (pb[2] - pa[2]) * (pc[1] - pa[1]),
                 (pb[2] - pa[2]) * (pc[0] - pa[0]) - (pb[0] - pa[0]) * (pc[2] - pa[2]),
                 (pb[0] - pa[0]) * (pc[1] - pa[1]) - (pb[1] - pa[1]) * (pc[0] - pa[0]))
        norm = math.sqrt(cross[0] ** 2 + cross[1] ** 2 + cross[2] ** 2)
        if norm == 0.0:
            degenerate += 1
            continue
        area += 0.5 * norm
        volume += (pa[0] * cross[0] + pa[1] * cross[1] + pa[2] * cross[2]) / 6.0
        for u, v in ((weld[a], weld[b]), (weld[b], weld[c]), (weld[c], weld[a])):
            directed[(u, v)] = directed.get((u, v), 0) + 1

    # A closed, oriented surface traverses every edge as often forwards as
    # backwards. Requiring exactly once each way would be manifoldness, which is
    # stronger than the scan needs and wrong for the ordinary case here: a part
    # built from several shells that touch shares an edge between four
    # triangles. The cup fixture reported twelve such edges as defects until
    # this counted the balance rather than the count.
    unpaired = sum(1 for (u, v), count in directed.items()
                   if count != directed.get((v, u), 0))
    lo = [min(v[axis] for v in verts) for axis in range(3)]
    hi = [max(v[axis] for v in verts) for axis in range(3)]
    return {"triangles": len(mesh["triangles"]), "vertices": len(verts), "welded_vertices": len(canonical),
            "degenerate_triangles": degenerate, "unpaired_edges": unpaired,
            "closed": unpaired == 0 and degenerate == 0,
            "volume_m3": volume, "surface_area_m2": area, "bounds_m": [lo, hi]}


# ------------------------------------------------------------------- occupancy

def _rows_inclusive(lo: float, hi: float, cell_m: float) -> range:
    """Cell indices whose centre lies in [lo, hi]."""
    return range(math.ceil(lo / cell_m - 0.5), math.floor(hi / cell_m - 0.5) + 1)


def _cells_in_span(start: float, end: float, cell_m: float) -> range:
    """Cell indices whose centre lies in [start, end): spans never share a cell."""
    return range(math.ceil(start / cell_m - 0.5), math.ceil(end / cell_m - 0.5))


def _forward(du: float, dv: float) -> bool:
    """One of the two triangles sharing an edge owns a point lying exactly on it.

    The two traverse the edge in opposite directions, so a predicate on the edge
    direction picks exactly one of them and a scan line through an edge is
    counted once rather than twice or not at all.
    """
    return dv > 0.0 or (dv == 0.0 and du < 0.0)


def _spans(mesh: dict[str, Any], cell_m: float, axis: int) -> dict[str, Any]:
    """Inside intervals along `axis` for every cell row, by winding number.

    Winding rather than parity, because the ordinary case here is a union of
    overlapping solids -- a handle inside a blade -- where parity would read the
    overlap as outside and hollow it out.
    """
    t0, t1 = AXIS_PAIR[axis]
    verts = mesh["vertices"]
    crossings: dict[tuple[int, int], list[tuple[float, int]]] = {}
    parallel = 0
    for tri in mesh["triangles"]:
        a, b, c = verts[tri[0]], verts[tri[1]], verts[tri[2]]
        area2 = ((b[t0] - a[t0]) * (c[t1] - a[t1]) - (c[t0] - a[t0]) * (b[t1] - a[t1]))
        if area2 == 0.0:
            # Edge-on to this scan direction: it carries no crossing. A closed
            # mesh is entered and left through the triangles that are not.
            parallel += 1
            continue
        # area2 is the scan-axis component of the normal, so a ray along +axis
        # LEAVES the solid through a triangle with a positive one.
        step = -1 if area2 > 0.0 else 1
        if area2 < 0.0:
            b, c = c, b
        # Counter-clockwise from here, so the fill rule below has one sign to
        # reason about; the entering/leaving sign was taken before the swap.
        n = ((b[1] - a[1]) * (c[2] - a[2]) - (b[2] - a[2]) * (c[1] - a[1]),
             (b[2] - a[2]) * (c[0] - a[0]) - (b[0] - a[0]) * (c[2] - a[2]),
             (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]))
        for iu in _rows_inclusive(min(a[t0], b[t0], c[t0]), max(a[t0], b[t0], c[t0]), cell_m):
            pu = (iu + 0.5) * cell_m
            for iv in _rows_inclusive(min(a[t1], b[t1], c[t1]), max(a[t1], b[t1], c[t1]), cell_m):
                pv = (iv + 0.5) * cell_m
                inside = True
                for p, q in ((a, b), (b, c), (c, a)):
                    edge = ((q[t0] - p[t0]) * (pv - p[t1]) - (q[t1] - p[t1]) * (pu - p[t0]))
                    if edge < 0.0 or (edge == 0.0 and not _forward(q[t0] - p[t0], q[t1] - p[t1])):
                        inside = False
                        break
                if not inside:
                    continue
                where = a[axis] - (n[t0] * (pu - a[t0]) + n[t1] * (pv - a[t1])) / n[axis]
                crossings.setdefault((iu, iv), []).append((where, step))

    spans: list[tuple[tuple[int, int], float, float]] = []
    unclosed_rows = 0
    for row, hits in crossings.items():
        hits.sort()
        winding = 0
        start = 0.0
        for where, step in hits:
            was = winding
            winding += step
            if was <= 0 and winding > 0:
                start = where
            elif was > 0 and winding <= 0:
                spans.append((row, start, where))
        if winding != 0:
            # The ray went in and never came out. Something is open, or a
            # triangle faces the wrong way; either way this row has no answer.
            unclosed_rows += 1
    return {"spans": spans, "unclosed_rows": unclosed_rows, "parallel_triangles": parallel}


def _thickness(lengths: list[float], fraction: float = THICKNESS_PERCENTILE) -> float:
    """The span length below which `fraction` of the represented volume lies.

    Each span of length L in a cell row represents L * h^2 of solid, so ordering
    the spans and accumulating their lengths weights this by volume.
    """
    if not lengths:
        return 0.0
    ordered = sorted(lengths)
    total = sum(ordered)
    seen = 0.0
    for length in ordered:
        seen += length
        if seen >= fraction * total:
            return length
    return ordered[-1]


def occupancy(mesh: dict[str, Any], cell_m: float, *, axes: tuple[int, ...] = (0, 1, 2)) -> dict[str, Any]:
    """Cells whose centre is inside the solid, on the engine's grid.

    Scanned once per axis and put to a majority vote, which costs three times
    one scan and at fixture size is milliseconds.

    Where the three disagree, a face lies exactly on a cell-centre plane and the
    centre is neither in nor out. Measured: the 300 mm tread against a 40 mm
    cell does this at 5 of its 40 cells, because 300 is 7.5 cells and the far
    face therefore lands on the centre plane of cell 7. That is a tie on the
    surface of a sound mesh, not a defect in it, so the count is reported and
    the majority settles it. The defect worth refusing is a row that is entered
    and never left, which is what invalid_solid is for.
    """
    if cell_m <= 0.0 or not math.isfinite(cell_m):
        raise ValueError("cell size must be a positive number of metres")
    votes: dict[tuple[int, int, int], int] = {}
    per_axis: dict[int, dict[str, Any]] = {}
    for axis in axes:
        scan = _spans(mesh, cell_m, axis)
        found: set[tuple[int, int, int]] = set()
        lengths: list[float] = []
        dropped: list[float] = []
        for (iu, iv), start, end in scan["spans"]:
            lengths.append(end - start)
            cells = _cells_in_span(start, end, cell_m)
            if not len(cells):
                # A feature thinner than a cell that missed every centre. It
                # would simply not be there, which is worth a number rather
                # than a silence.
                dropped.append(end - start)
            t0, t1 = AXIS_PAIR[axis]
            for index in cells:
                cell = [0, 0, 0]
                cell[axis], cell[t0], cell[t1] = index, iu, iv
                found.add((cell[0], cell[1], cell[2]))
        for cell in found:
            votes[cell] = votes.get(cell, 0) + 1
        per_axis[axis] = {"cells": len(found), "thickness_m": _thickness(lengths),
                          "dropped_spans": len(dropped), "dropped_volume_m3": sum(dropped) * cell_m ** 2,
                          "unclosed_rows": scan["unclosed_rows"]}

    majority = (len(axes) + 1) // 2
    cells = sorted(cell for cell, count in votes.items() if count >= majority)
    disagreements = sum(1 for count in votes.values() if 0 < count < len(axes))
    return {"cells": cells, "count": len(cells), "cell_size_m": cell_m,
            "volume_m3": len(cells) * cell_m ** 3,
            "thickness_m": min((per_axis[axis]["thickness_m"] for axis in axes), default=0.0),
            "axis_thickness_m": [per_axis[axis]["thickness_m"] if axis in per_axis else None
                                 for axis in range(3)],
            "dropped_spans": sum(per_axis[axis]["dropped_spans"] for axis in axes),
            "dropped_volume_m3": max((per_axis[axis]["dropped_volume_m3"] for axis in axes), default=0.0),
            "axis_disagreements": disagreements,
            "unclosed_rows": sum(per_axis[axis]["unclosed_rows"] for axis in axes)}


# --------------------------------------------------- what the generator would do

def horizon_offsets(horizon: int) -> list[tuple[int, int, int]]:
    """Every neighbour offset buildBonds would bond to, once per pair.

    The rule is src/matter/Lattice.cpp:113: every offset inside the horizon by
    GRID DISTANCE, in the positive half so each pair is visited once.
    """
    offsets = []
    for dz in range(-horizon, horizon + 1):
        for dy in range(-horizon, horizon + 1):
            for dx in range(-horizon, horizon + 1):
                if (dz, dy, dx) <= (0, 0, 0):
                    continue
                if math.sqrt(dx * dx + dy * dy + dz * dz) > horizon + 1.0e-9:
                    continue
                offsets.append((dx, dy, dz))
    return offsets


_INTERIOR_CACHE: dict[tuple[tuple[int, int, int], int], tuple[tuple[int, int, int], ...]] = {}


def interior_offsets(offset: tuple[int, int, int], samples: int = 64) -> tuple[tuple[int, int, int], ...]:
    """Cells whose INTERIOR the segment between two cells at this offset passes through.

    A pure function of the offset, so it is worked out once for each of the
    sixteen offsets a horizon of 2 allows rather than once per candidate bond.
    Sampling the segment per pair instead cost 10.5 s on the twelve-tread
    staircase against 73 ms this way.

    A segment that only grazes a corner is not a crossing, so a sample counts
    only where it lies strictly inside a cell rather than on its face. Measured:
    at a horizon of 2 only three of the sixteen offsets -- the two-cell steps
    along an axis -- cross anything at all, so the check skips the other
    thirteen outright.
    """
    key = (offset, samples)
    cached = _INTERIOR_CACHE.get(key)
    if cached is not None:
        return cached
    edge = 1.0e-6
    found: list[tuple[int, int, int]] = []
    for sample in range(1, samples):
        t = sample / samples
        index = []
        strict = True
        for axis in range(3):
            position = 0.5 + t * offset[axis]
            whole = math.floor(position)
            index.append(whole)
            if not edge < position - whole < 1.0 - edge:
                strict = False
        cell = (index[0], index[1], index[2])
        if strict and cell != (0, 0, 0) and cell != offset and cell not in found:
            found.append(cell)
    _INTERIOR_CACHE[key] = tuple(found)
    return _INTERIOR_CACHE[key]


def void_crossing_bonds(cells: set[tuple[int, int, int]], horizon: int,
                        samples: int = 64) -> list[tuple[tuple[int, int, int], tuple[int, int, int]]]:
    """Bonds the generator would build whose segment crosses an empty cell.

    buildBonds filters by grid distance alone; nothing tests whether the segment
    between two cells passes through the void. Material on the two sides of a
    slot narrower than the horizon is therefore welded together while still
    looking like a slot.
    """
    crossing = []
    spanning = [(offset, interior) for offset in horizon_offsets(horizon)
                for interior in (interior_offsets(offset, samples),) if interior]
    for cell in sorted(cells):
        for offset, interior in spanning:
            other = (cell[0] + offset[0], cell[1] + offset[1], cell[2] + offset[2])
            if other not in cells:
                continue
            if any((cell[0] + d[0], cell[1] + d[1], cell[2] + d[2]) not in cells for d in interior):
                crossing.append((cell, other))
    return crossing


def within_horizon(a: set[tuple[int, int, int]], b: set[tuple[int, int, int]], horizon: int) -> bool:
    """Would the generator bond anything in `a` to anything in `b`?"""
    offsets = horizon_offsets(horizon)
    for cell in a:
        for dx, dy, dz in offsets:
            if ((cell[0] + dx, cell[1] + dy, cell[2] + dz) in b
                    or (cell[0] - dx, cell[1] - dy, cell[2] - dz) in b):
                return True
    return False


def box_decomposition(cells: set[tuple[int, int, int]]) -> list[tuple[int, int, int, int, int, int]]:
    """Cover the occupancy with axis-aligned boxes, each cell in exactly one.

    A part that only has to be collided with does not need thousands of nodes.
    Greedy growth in x, then y, then z: the cover is exact, which is what the
    tests check, rather than minimal, which is NP-hard and not worth it.
    """
    remaining = set(cells)
    boxes = []
    for cell in sorted(remaining, key=lambda c: (c[2], c[1], c[0])):
        if cell not in remaining:
            continue
        i, j, k = cell
        width = 1
        while (i + width, j, k) in remaining:
            width += 1
        height = 1
        while all((x, j + height, k) in remaining for x in range(i, i + width)):
            height += 1
        depth = 1
        while all((x, y, k + depth) in remaining
                  for x in range(i, i + width) for y in range(j, j + height)):
            depth += 1
        for x in range(i, i + width):
            for y in range(j, j + height):
                for z in range(k, k + depth):
                    remaining.discard((x, y, z))
        boxes.append((i, j, k, width, height, depth))
    return boxes


def mass_properties(cells: list[tuple[int, int, int]], cell_m: float,
                    density_kg_m3: float) -> dict[str, Any]:
    """Mass, centre of mass and rest inertia, computed as Lattice.cpp does.

    Every cell is a full cell, so every node carries the same mass; the per-cell
    diagonal term m h^2 / 6 is the cube's own inertia about an axis through its
    centre, added exactly where calculateRestInertia adds it.
    """
    volume = cell_m ** 3
    node_mass = volume * density_kg_m3
    total = node_mass * len(cells)
    centres = [((i + 0.5) * cell_m, (j + 0.5) * cell_m, (k + 0.5) * cell_m) for i, j, k in cells]
    com = [sum(c[axis] for c in centres) / len(centres) for axis in range(3)]
    own = node_mass * cell_m * cell_m / 6.0
    inertia = [[0.0] * 3 for _ in range(3)]
    for centre in centres:
        r = [centre[axis] - com[axis] for axis in range(3)]
        inertia[0][0] += node_mass * (r[1] * r[1] + r[2] * r[2]) + own
        inertia[1][1] += node_mass * (r[0] * r[0] + r[2] * r[2]) + own
        inertia[2][2] += node_mass * (r[0] * r[0] + r[1] * r[1]) + own
        inertia[0][1] -= node_mass * r[0] * r[1]
        inertia[0][2] -= node_mass * r[0] * r[2]
        inertia[1][2] -= node_mass * r[1] * r[2]
    inertia[1][0], inertia[2][0], inertia[2][1] = inertia[0][1], inertia[0][2], inertia[1][2]
    return {"mass_kg": total, "center_of_mass_m": com, "inertia_kg_m2": inertia,
            "density_kg_m3": density_kg_m3}


# -------------------------------------------------------------------- instances

def rotation_matrix(rotation_deg: tuple[float, float, float]) -> list[list[int]]:
    """A quarter-turn rotation as integers, in the engine's order: x, then y, then z.

    That is the order rotateDegrees applies (src/fastlattice/TileImpactScene.cpp:53).
    Only multiples of 90 degrees: they map cell centres to cell centres, so an
    instance is an exact re-index of the part rather than a second voxelisation.
    """
    matrix = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    for axis, degrees in enumerate(rotation_deg):
        if degrees % 90 != 0:
            raise ValueError(
                f"instance rotation {degrees} degrees is not a quarter turn: a part can be "
                "re-indexed onto the shared grid only by quarter turns; anything else has to be "
                "voxelised again in world space and is a different cell count "
                "(docs/asset-compiler.md, 'What the engine does not have yet')")
        turns = int(degrees // 90) % 4
        cos, sin = ((1, 0), (0, 1), (-1, 0), (0, -1))[turns]
        step = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
        u, v = AXIS_PAIR[axis]
        step[u][u], step[u][v] = cos, -sin
        step[v][u], step[v][v] = sin, cos
        matrix = [[sum(step[r][t] * matrix[t][c] for t in range(3)) for c in range(3)]
                  for r in range(3)]
    return matrix


def place_instance(cells: list[tuple[int, int, int]], translation_cells: tuple[int, int, int],
                   rotation_deg: tuple[float, float, float]) -> list[tuple[int, int, int]]:
    """The part's cells on the shared world grid.

    A cell index i stands for a centre at (i + 0.5) h, and a quarter turn maps
    that to another half-integer multiple of h, so the placed index is exact
    integer arithmetic and the part is never converted twice.
    """
    matrix = rotation_matrix(rotation_deg)
    placed = []
    for cell in cells:
        centre = [2 * cell[axis] + 1 for axis in range(3)]  # in half-cells, so this stays integer
        turned = [sum(matrix[row][column] * centre[column] for column in range(3)) for row in range(3)]
        placed.append(tuple((turned[axis] - 1) // 2 + translation_cells[axis] for axis in range(3)))
    return sorted(placed)


# ------------------------------------------------------------------ conversion

def convert_part(mesh: dict[str, Any], *, unit: str, cell_m: float, material: str | None,
                 horizon: int = DEFAULT_HORIZON_CELLS,
                 budget: int = ROOM_CELL_BUDGET) -> dict[str, Any]:
    """One part, converted once: geometry, occupancy, proxies, flags and failures."""
    metres = scaled(mesh, unit)
    geometry = mesh_report(metres)
    failures: list[dict[str, str]] = []
    capabilities = {"visual"} if geometry["triangles"] else set()

    if not geometry["closed"]:
        failures.append(_fail("invalid_solid",
                              f"{geometry['unpaired_edges']} edges are not shared by exactly two "
                              f"triangles and {geometry['degenerate_triangles']} triangles have no area"))
    if geometry["volume_m3"] <= 0.0:
        failures.append(_fail("invalid_solid",
                              f"the signed volume is {geometry['volume_m3']:.6e} m3, so the surface is "
                              "inside out or not closed"))

    solid = not failures
    found = occupancy(metres, cell_m) if solid else {"cells": [], "count": 0, "volume_m3": 0.0,
                                                    "thickness_m": 0.0, "axis_thickness_m": [0.0] * 3,
                                                    "dropped_spans": 0, "dropped_volume_m3": 0.0,
                                                    "axis_disagreements": 0, "unclosed_rows": 0}
    if solid and found["unclosed_rows"]:
        # Disagreement between the axes is NOT this: it is a cell centre sitting
        # exactly on a face, which the majority vote settles. A row entered and
        # never left means a shell is open or a triangle faces the wrong way,
        # and no vote repairs that.
        failures.append(_fail("invalid_solid",
                              f"{found['unclosed_rows']} scan rows enter the solid and never leave it, "
                              "so a shell is open or a triangle faces the wrong way"))
    if solid and found["thickness_m"] < cell_m:
        failures.append(_fail("feature_below_resolution",
                              f"the thin dimension is {found['thickness_m'] * 1000:.3g} mm at the "
                              f"{THICKNESS_PERCENTILE:.0%} volume mark, below one {cell_m * 1000:g} mm "
                              f"cell; occupancy would say {found['volume_m3'] * 1e9:.0f} mm3 against "
                              f"{geometry['volume_m3'] * 1e9:.0f} mm3 of solid"))
    if solid and found["count"] > budget:
        failures.append(_fail("physics_budget_exceeded",
                              f"{found['count']} cells at {cell_m * 1000:g} mm against a budget of "
                              f"{budget}"))

    cell_set = set(found["cells"])
    crossing = void_crossing_bonds(cell_set, horizon) if cell_set else []
    if crossing:
        failures.append(_fail("required_gap_lost",
                              f"{len(crossing)} bonds would cross empty cells at a horizon of "
                              f"{horizon}, so a gap inside this part is welded shut"))

    density = MATERIAL_DENSITY_KG_M3.get(material) if material else None
    if density is None:
        failures.append(_fail("material_unknown",
                              f"{material!r} is not in the engine's catalogue "
                              f"{sorted(MATERIAL_DENSITY_KG_M3)}"))

    boxes = box_decomposition(cell_set)
    categories = {failure["category"] for failure in failures}
    if solid and not categories & {"invalid_solid"}:
        capabilities.add("static_collision")
        if density is not None:
            capabilities.add("movable_rigid")
            if not categories & {"feature_below_resolution", "required_gap_lost",
                                 "physics_budget_exceeded"} and found["count"]:
                capabilities.add("editable_voxels")

    volume_error = (found["volume_m3"] - geometry["volume_m3"]) / geometry["volume_m3"] \
        if geometry["volume_m3"] > 0.0 else 0.0
    # Centre sampling can be wrong by at most one cell of volume for each cell
    # the surface passes through, and the surface passes through about A / h^2
    # of them, so |dV| <= A h is the bound this reports against.
    bound = geometry["surface_area_m2"] * cell_m
    return {
        "geometry": geometry,
        "occupancy": {"count": found["count"], "cells": [list(cell) for cell in found["cells"]],
                      "volume_m3": found["volume_m3"], "volume_error": volume_error,
                      "volume_error_bound": bound / geometry["volume_m3"] if geometry["volume_m3"] else 0.0,
                      "thickness_m": found["thickness_m"],
                      "axis_thickness_m": found["axis_thickness_m"],
                      "dropped_spans": found["dropped_spans"],
                      "axis_disagreements": found["axis_disagreements"]},
        "collision": {"boxes": [list(box) for box in boxes], "count": len(boxes)},
        "bonds": {"horizon_cells": horizon, "void_crossing": len(crossing)},
        "material": material,
        "mass_properties": mass_properties(found["cells"], cell_m, density)
        if density is not None and found["cells"] else None,
        "capabilities": sorted(capabilities),
        "failures": failures,
    }


def content_key(mesh: dict[str, Any], unit: str, cell_m: float, horizon: int,
                material: str | None) -> str:
    """What makes two parts the same conversion.

    The geometry itself, not the part's name: a bolt exported twice under two
    names is one conversion. Positions are rounded to a nanometre, which is far
    below anything a cell size of millimetres can resolve and far above the
    float noise of an exporter.
    """
    digest = hashlib.sha256()
    digest.update(f"{unit}|{cell_m!r}|{horizon}|{material}|".encode())
    for vertex in mesh["vertices"]:
        digest.update(b"".join(int(round(value / WELD_M)).to_bytes(8, "big", signed=True)
                               for value in vertex))
    for triangle in mesh["triangles"]:
        digest.update(b"".join(index.to_bytes(4, "big") for index in triangle))
    return digest.hexdigest()[:16]


def compile_assembly(document: dict[str, Any], base: Path) -> dict[str, Any]:
    """The whole assembly: every unique part converted once, then placed."""
    if document.get("schema") != ASSEMBLY_SCHEMA:
        raise ValueError(f"assembly schema must be {ASSEMBLY_SCHEMA!r}")
    cell_m = float(document.get("cell_size_m", 0.0))
    if cell_m <= 0.0:
        raise ValueError("the assembly must declare a positive cell_size_m")
    horizon = int(document.get("neighbor_horizon_cells", DEFAULT_HORIZON_CELLS))
    budget = int(document.get("cell_budget", ROOM_CELL_BUDGET))
    parts = document.get("parts") or {}
    if not isinstance(parts, dict) or not parts:
        raise ValueError("the assembly must declare at least one part")

    failures: list[dict[str, str]] = []
    if not document.get("rights"):
        failures.append(_fail("rights_unverified",
                              "the assembly declares no rights record, so nothing here may be published"))

    conversions: dict[str, dict[str, Any]] = {}
    part_records: dict[str, dict[str, Any]] = {}
    for part_id, declared in parts.items():
        unit = declared.get("unit")
        if unit not in UNIT_M:
            failures.append(_fail("units_ambiguous",
                                  f"part {part_id!r} declares unit {unit!r}; it must be one of "
                                  f"{sorted(UNIT_M)}"))
            part_records[part_id] = {"conversion": None, "unit": unit,
                                     "material": declared.get("material"),
                                     "mesh": declared.get("mesh")}
            continue
        mesh = read_obj(base / declared["mesh"])
        material = declared.get("material")
        key = content_key(mesh, unit, cell_m, horizon, material)
        if key not in conversions:
            conversions[key] = convert_part(mesh, unit=unit, cell_m=cell_m, material=material,
                                            horizon=horizon, budget=budget)
            conversions[key]["source"] = {"mesh": declared["mesh"], "unit": unit}
        part_records[part_id] = {"conversion": key, "unit": unit, "material": material,
                                 "mesh": declared["mesh"]}

    instances = []
    placed: dict[str, set[tuple[int, int, int]]] = {}
    max_snap = 0.0
    for declared in document.get("instances") or []:
        part_id = declared["part"]
        if part_id not in part_records:
            raise ValueError(f"instance {declared.get('id')!r} names unknown part {part_id!r}")
        record = part_records[part_id]
        translation_m = [float(v) / 1000.0 for v in declared.get("translation_mm", [0, 0, 0])]
        cells_offset = tuple(round(v / cell_m) for v in translation_m)
        snap = max(abs(cells_offset[axis] * cell_m - translation_m[axis]) for axis in range(3))
        max_snap = max(max_snap, snap)
        rotation = tuple(float(v) for v in declared.get("rotation_deg", [0, 0, 0]))
        conversion = conversions.get(record["conversion"] or "")
        cells = [tuple(cell) for cell in (conversion["occupancy"]["cells"] if conversion else [])]
        world = place_instance(cells, cells_offset, rotation)
        placed[declared["id"]] = set(world)
        instances.append({"id": declared["id"], "part": part_id, "conversion": record["conversion"],
                          "translation_cells": list(cells_offset), "rotation_deg": list(rotation),
                          "placement_snap_m": snap, "cells": len(world)})

    connections = []
    fused: dict[str, str] = {}
    for declared in document.get("connections") or []:
        kind = declared.get("kind")
        if kind not in CONNECTION_KINDS:
            raise ValueError(f"connection kind must be one of {list(CONNECTION_KINDS)}")
        a, b = declared["a"], declared["b"]
        for side in (a, b):
            if side not in placed:
                raise ValueError(f"connection names unknown instance {side!r}")
        touching = bool(placed[a] & placed[b]) or _adjacent(placed[a], placed[b])
        # Fusing two parts hands both to one generateVoxelLattice call, which
        # bonds anything inside the horizon whether or not it touches -- that is
        # the hazard the gap check below counts, not an ambiguity. So a fused
        # pair is ambiguous only when NOTHING would join it.
        joined = touching or (kind in FUSED_KINDS and within_horizon(placed[a], placed[b], horizon))
        if not joined:
            failures.append(_fail("connection_ambiguous",
                                  f"the {kind} between {a!r} and {b!r} joins instances that share no "
                                  f"cell, no face and no bond inside {horizon} cells, so nothing would "
                                  "hold them together and where it acts is declared nowhere"))
        connections.append({"kind": kind, "a": a, "b": b, "touching": touching, "joined": joined})
        if kind in FUSED_KINDS:
            fused[_root(fused, b)] = _root(fused, a)

    declared_pairs = {frozenset((c["a"], c["b"])) for c in connections}
    identifiers = sorted(placed)
    for index, a in enumerate(identifiers):
        for b in identifiers[index + 1:]:
            if placed[a] & placed[b] and frozenset((a, b)) not in declared_pairs:
                failures.append(_fail("connection_ambiguous",
                                      f"{a!r} and {b!r} share {len(placed[a] & placed[b])} cells with no "
                                      "connection declared, so the compiler cannot tell a joint from an "
                                      "interference"))

    # A fused group is handed to ONE generateVoxelLattice call, so it is the set
    # the bond generator sees and the set a lost gap has to be looked for in.
    groups: dict[str, set[tuple[int, int, int]]] = {}
    members: dict[str, list[str]] = {}
    for identifier, cells in placed.items():
        root = _root(fused, identifier)
        groups.setdefault(root, set()).update(cells)
        members.setdefault(root, []).append(identifier)
    group_records = []
    for root, cells in sorted(groups.items()):
        crossing = void_crossing_bonds(cells, horizon)
        # A group of one instance has already had its own gaps counted in
        # convert_part, so reporting them again here would be the same defect
        # twice under one category.
        if crossing and len(members[root]) > 1:
            failures.append(_fail("required_gap_lost",
                                  f"{len(crossing)} bonds would cross the empty cells between the parts "
                                  f"fused as {root!r}: at a horizon of {horizon} cells the gap is welded "
                                  "shut and the assembly is one solid"))
        group_records.append({"root": root, "cells": len(cells), "void_crossing_bonds": len(crossing)})

    cells_total = sum(len(cells) for cells in placed.values())
    if cells_total > budget:
        failures.append(_fail("physics_budget_exceeded",
                              f"the assembly places {cells_total} cells at {cell_m * 1000:g} mm against "
                              f"a budget of {budget}; cost goes as the cube of one over the cell size"))

    # An intersection over nothing is everything, so an assembly whose every
    # part failed to convert -- an undeclared unit is enough -- would come back
    # claiming the lot. It has earned none of them.
    capabilities = (set(CAPABILITIES) - {"powered", "functionally_tested", "articulated"}
                    if conversions else set())
    for conversion in conversions.values():
        capabilities &= set(conversion["capabilities"])
    if any(c["kind"] in ARTICULATED_KINDS and c["touching"] for c in connections):
        capabilities.add("articulated")
    for failure in failures:
        if failure["category"] in ("required_gap_lost", "physics_budget_exceeded"):
            capabilities.discard("editable_voxels")

    return {
        "schema": BLUEPRINT_SCHEMA,
        "generated_by": "tools/asset_compiler.py",
        "cell_size_m": cell_m,
        "neighbor_horizon_cells": horizon,
        "cell_budget": budget,
        "rights": document.get("rights"),
        "conversions": conversions,
        "parts": part_records,
        "instances": instances,
        "connections": connections,
        "bond_groups": group_records,
        "validation": {
            "conversions_run": len(conversions),
            "instances": len(instances),
            "cells_total": cells_total,
            "max_placement_snap_m": max_snap,
            "capabilities": sorted(capabilities),
            "failures": failures + [failure for conversion in conversions.values()
                                    for failure in conversion["failures"]],
            "publishable": not any(f["category"] == "rights_unverified" for f in failures),
        },
    }


def _root(parent: dict[str, str], node: str) -> str:
    """The fused group `node` belongs to, following the chain to its end.

    Chains matter: fusing a to b and c to d and then b to c is one group of
    four, and a parent map read only one level deep would say three.
    """
    while parent.get(node, node) != node:
        node = parent[node]
    return node


def _adjacent(a: set[tuple[int, int, int]], b: set[tuple[int, int, int]]) -> bool:
    """Do these two occupancies share a face? Touching is what a joint acts across."""
    for cell in a:
        for axis in range(3):
            for step in (-1, 1):
                other = list(cell)
                other[axis] += step
                if (other[0], other[1], other[2]) in b:
                    return True
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("assembly", type=Path, help="the canonical assembly document")
    parser.add_argument("--out", type=Path, help="where to write the blueprint")
    parser.add_argument("--cell-mm", type=float, help="override the assembly's cell size")
    parser.add_argument("--budget", type=int, help="override the cell budget")
    parser.add_argument("--cells", action="store_true", help="keep every cell in the blueprint")
    args = parser.parse_args(argv)

    document = json.loads(args.assembly.read_text(encoding="utf-8"))
    if args.cell_mm:
        document["cell_size_m"] = args.cell_mm / 1000.0
    if args.budget:
        document["cell_budget"] = args.budget
    blueprint = compile_assembly(document, args.assembly.parent)
    if not args.cells:
        # The cells are the bulk of the file: a 1,920-cell part is 30 kB of
        # them. They are kept only when asked for, so reading a blueprint by eye
        # stays possible.
        for conversion in blueprint["conversions"].values():
            conversion["occupancy"].pop("cells", None)
    text = json.dumps(blueprint, indent=2)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    validation = blueprint["validation"]
    print(f"{validation['conversions_run']} conversions for {len(blueprint['parts'])} parts, "
          f"{validation['instances']} instances, {validation['cells_total']} cells")
    print(f"capabilities: {', '.join(validation['capabilities']) or 'none'}")
    for failure in validation["failures"]:
        print(f"  {failure['category']}: {failure['detail']}")
    if not args.out:
        print(text)
    return 1 if validation["failures"] else 0


if __name__ == "__main__":
    sys.exit(main())
