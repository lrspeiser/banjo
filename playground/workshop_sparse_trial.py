"""Exact-cell Workshop engine trials.

Banjo's live scene already has a lossless path to an arbitrary occupied-cell set:
grid-aligned boxes with one join name are voxelised onto the shared scene grid,
unioned, and passed to generateVoxelLattice. This adapter decomposes the exact
banjo.workshop-matter.v2 artifact into those boxes, proves the union round-trips
to the same integer grid coordinates, and only then starts the engine.

The joined-box encoding is an ABI bridge, not a geometry approximation. A future
native sparse-body scene field can replace the encoding without changing the
canonical Matter artifact or its hashes.
"""
from __future__ import annotations

import base64
import struct
import time
from math import isfinite
from pathlib import Path
from typing import Any, Callable

import fracture_lab
import live_session
import workshop_trials_core as core
from mcp import engine_materials, joint_efficiency, workshop_visual, workshop_rigid
from mcp.workshop import WorkshopDesign

from mcp.workshop_cell_encoding import MAX_SCENE_BOXES, decompose_cells, cells_from_boxes
_LOAD_MATERIAL = "iron"

Grid = tuple[int, int, int]
Box = tuple[Grid, Grid]  # inclusive min/max grid coordinates


def _matter_overrides(design: WorkshopDesign) -> dict[str, Any]:
    lineage = design.lineage if isinstance(design.lineage, dict) else {}
    value = lineage.get("component_overrides") or {}
    return value if isinstance(value, dict) else {}


def _grid_set(matter: dict[str, Any]) -> set[Grid]:
    return set(_grid_parts(matter))


def _grid_parts(matter: dict[str, Any]) -> dict[Grid, str]:
    """Every cell and the component it belongs to.

    A cell two components both claim takes its primary one, which is the first
    that claimed it -- the same rule by which the engine builds it once. So the
    components partition the cells, and decomposing each on its own still
    reconstructs the whole set exactly.
    """
    out: dict[Grid, str] = {}
    for cell in matter.get("cells") or []:
        grid = cell.get("grid") if isinstance(cell, dict) else None
        if not isinstance(grid, list) or len(grid) != 3:
            raise ValueError("Matter artifact is missing canonical grid coordinates")
        out[(int(grid[0]), int(grid[1]), int(grid[2]))] = str(cell.get("component") or "")
    if len(out) != int(matter.get("total_cells", -1)):
        raise ValueError("Matter artifact cell count does not match its canonical grid set")
    return out


def decompose_by_part(cells: set[Grid], part_of: dict[Grid, str]) -> list[tuple[Box, str]]:
    """Boxes that know which component they are, by decomposing each on its own.

    A joint declared between two parts can only reach the engine if the cells
    still say which part they are, so the whole object is no longer decomposed
    as one heap of cells (#20). The union is unchanged: the components
    partition the cells, so the same set comes back.

    **Biggest box first**, which is not cosmetic: the first box is the one that
    takes the product's root name, and everything downstream calls that body the
    product -- the install, the bench's `root_body`, the page. Decomposing part
    by part in name order had quietly made a table's root `leg-1` instead of its
    top, because `leg-1` sorts first; the old whole-heap decomposition happened
    to put the top first because it is the largest run. Sorting by size restores
    that on purpose rather than by luck, and ties break on the part's name and
    then its corner so the order is the same every run.
    """
    grouped: dict[str, set[Grid]] = {}
    for cell in cells:
        grouped.setdefault(part_of.get(cell, ""), set()).add(cell)
    out: list[tuple[Box, str]] = []
    for part in sorted(grouped):
        out += [(box, part) for box in decompose_cells(grouped[part])]

    def bulk(entry: tuple[Box, str]) -> tuple[int, str, Box]:
        (lo, hi), part = entry
        run = 1
        for axis in range(3):
            run *= hi[axis] - lo[axis] + 1
        return (-run, part, lo)

    out.sort(key=bulk)
    return out


def _box_body(name: str, box: Box, cell: float, material: str, join: str,
              part: str = "") -> dict[str, Any]:
    lo, hi = box
    counts = [hi[a] - lo[a] + 1 for a in range(3)]
    # Grid cell i spans [i*h,(i+1)*h], so a rectangular run has an exact
    # boundary-aligned centre at (lo+hi+1)*h/2.
    centre = [(lo[a] + hi[a] + 1) * cell / 2.0 for a in range(3)]
    return {
        "name": name,
        "shape": "box",
        "material": engine_materials.scene_name(material),
        "size_mm": [counts[a] * cell * 1000.0 for a in range(3)],
        "center_mm": [centre[a] * 1000.0 for a in range(3)],
        "velocity_m_s": [0.0, 0.0, 0.0],
        "rotation_deg": [0.0, 0.0, 0.0],
        "anchored": False,
        "join": join,
        # Which part of the joined object it is, so a declared joint can name it.
        **({"part": part} if part and join else {}),
    }


def _compact_load_shape(load_kg: float, cell: float) -> tuple[int, int, int, float]:
    per_cell = engine_materials.density(_LOAD_MATERIAL) * cell ** 3
    target = max(1, round(load_kg / per_cell))
    best: tuple[float, tuple[int, int, int]] | None = None
    limit = max(2, round(target ** (1 / 3)) * 4 + 4)
    for a in range(1, limit + 1):
        for b in range(a, limit + 1):
            c = max(b, round(target / (a * b)))
            for cc in {max(b, c - 1), max(b, c), max(b, c + 1)}:
                n = a * b * cc
                score = abs(n - target) + 0.03 * (cc - a)
                if best is None or score < best[0]:
                    best = (score, (a, b, cc))
    assert best is not None
    a, b, c = best[1]
    return a, b, c, a * b * c * per_cell


def _target_name(design: WorkshopDesign, on: str) -> str:
    part = next((p for p in design.parts if p.name == on), None)
    if part is None:
        part = next((p for p in design.parts if p.role == on), None)
    if part is None and on == "top":
        part = next((p for p in design.parts if p.name in {"top", "seat", "deck"}), None)
    if part is None:
        raise ValueError(f"the static load names {on!r}, but no such component/role exists")
    return part.name


def prototype_scene(design: WorkshopDesign, *, load_kg: float, on: str = "top",
                    cell_size_m: float = core.DEFAULT_CELL_M) -> dict[str, Any]:
    design.validate()
    workshop_rigid.require_lattice(design, "This exact-cell experiment")
    load_kg = float(load_kg)
    cell = float(cell_size_m)
    if not isfinite(load_kg) or load_kg <= 0:
        raise ValueError("load_kg must be a finite positive number")
    if not isfinite(cell) or not 0.005 <= cell <= 0.1:
        raise ValueError("scratch trial cell_size_m must be 5 to 100 mm")

    matter = workshop_visual.matter_document(
        design, _matter_overrides(design), cell_size_m=cell, exterior_only=False)
    missing = [name for name, count in matter["component_cell_counts"].items() if count == 0]
    if missing:
        raise ValueError("Cannot simulate: " + ", ".join(missing) + f" disappear at {cell*1000:g} mm cells. Use a finer cell size or thicker parts; no substitute product was tested.")
    cells = _grid_set(matter)
    if not cells:
        raise ValueError("the selected design produced no physical Matter cells")

    materials = {engine_materials.canonical(str(c.get("material") or ""))
                 for c in matter.get("cells") or []}
    unsupported = sorted(m for m in materials if not engine_materials.known(m))
    if unsupported:
        raise ValueError("the engine has no Banjo material preset for " + ", ".join(unsupported))
    if len(materials) != 1:
        raise ValueError(
            "exact fused Workshop static-load testing currently requires one material; "
            "mixed-material fixed interfaces need per-cell interface laws rather than silently taking the first material")
    material = next(iter(materials))

    # Decomposed component by component, so every box still says which part of
    # the product it is and a declared joint has something to name (#20).
    labelled = decompose_by_part(cells, _grid_parts(matter))
    boxes = [box for box, _ in labelled]
    reconstructed = cells_from_boxes(boxes)
    if reconstructed != cells:
        raise RuntimeError("internal error: engine box decomposition changed the Matter cell set")
    if len(boxes) > MAX_SCENE_BOXES:
        raise ValueError(
            f"exact Matter needs {len(boxes)} joined grid boxes at {cell*1000:g} mm; "
            f"the current scene bridge allows {MAX_SCENE_BOXES}. Use a coarser cell until the native sparse-body field lands.")

    # Place the complete product, never individual decomposed runs, on the
    # scratch floor. An end cap can extend below the design's original origin.
    # An integer-grid translation preserves the canonical local occupancy.
    placement_grid = (0, -min(g[1] for g in cells), 0)
    placed_boxes = [((tuple(lo[a] + placement_grid[a] for a in range(3)),
                      tuple(hi[a] + placement_grid[a] for a in range(3))), part)
                    for (lo, hi), part in labelled]
    join = "workshop-matter-" + str(matter["physics_hash"])[:12]
    bodies = [_box_body(f"candidate/matter-{i+1}", box, cell, material, join, part)
              for i, (box, part) in enumerate(placed_boxes)]

    target = _target_name(design, on)
    target_cells = [c for c in matter.get("cells") or [] if target in (c.get("components") or [c.get("component")])]
    if not target_cells:
        raise ValueError(f"the exact Matter artifact has no cells for load target {target!r}")
    target_grids = [tuple(int(c["grid"][a]) + placement_grid[a] for a in range(3))
                    for c in target_cells]
    top_y = max(g[1] for g in target_grids)
    centre_x = round(sum(g[0] for g in target_grids) / len(target_grids))
    centre_z = round(sum(g[2] for g in target_grids) / len(target_grids))

    na, nb, nc, actual_load_kg = _compact_load_shape(load_kg, cell)
    x0 = centre_x - na // 2
    z0 = centre_z - nc // 2
    y0 = top_y + 1
    load_box: Box = ((x0, y0, z0), (x0 + na - 1, y0 + nb - 1, z0 + nc - 1))
    load_name = "workshop/test-load"
    load_body = _box_body(load_name, load_box, cell, _LOAD_MATERIAL, "")
    bodies.append(load_body)

    # What each declared joint leaves the bonds that cross it, so the product
    # breaks at its joints at the strength they were made to, not the wood's.
    declared = joint_efficiency.scene_interfaces(design)
    spec = fracture_lab.validate({
        "algorithm": "lattice",
        "cell_m": cell,
        "plasticity": "on",
        **({"interfaces": declared} if declared else {}),
        "bodies": bodies,
    })
    return {
        "spec": spec,
        "root_body": bodies[0]["name"],
        "load_body": load_name,
        "load_kg": load_kg,
        "actual_load_kg": actual_load_kg,
        "load_on": on,
        "requested_cell_size_m": cell,
        "cell_size_m": cell,
        "matter": matter,
        "placement_grid": list(placement_grid),
        "placement_offset_m": [v * cell for v in placement_grid],
        "matter_cells": len(cells),
        "matter_boxes": len(boxes),
        "matter_roundtrip_exact": True,
        "matter_physics_hash": matter["physics_hash"],
        "matter_artifact_hash": matter["artifact_hash"],
    }


def verify_engine_matter(snapshot: dict[str, Any], matter: dict[str, Any], root: str,
                         *, placement_grid=(0, 0, 0)) -> dict[str, Any]:
    """Check native compiled cells, not merely the Python box decomposition.

    The fresh-world snapshot carries each cell offset relative to the body's
    centre of mass. Reconstruct those positions and compare every native grid
    coordinate AND material with the canonical artifact before advancing time.
    """
    body = next((b for b in snapshot.get("bodies", []) if b.get("name") == root), None)
    if body is None:
        raise ValueError("the native engine did not produce the requested Matter body")
    try:
        raw = base64.b64decode(body["offsets_b64"], validate=True)
        if len(raw) % 24:
            raise ValueError("invalid native cell-offset encoding")
        offsets = list(struct.iter_unpack("<ddd", raw))
        pose = body["pose"]
        centre, q = pose["com_m"], pose["q_wxyz"]
        if len(centre) != 3 or len(q) != 4 or not all(isfinite(v) for v in [*centre, *q]):
            raise ValueError("invalid native body pose")
        if abs(sum(v*v for v in q)-1) > 1e-8:
            raise ValueError("invalid native body orientation")
        h = float(matter["cell_size_m"])
        native = set()
        w, x, y, z = q
        for v in offsets:
            # Quaternion rotation, with q stored as w,x,y,z.
            t = (2*(y*v[2]-z*v[1]), 2*(z*v[0]-x*v[2]), 2*(x*v[1]-y*v[0]))
            rotated = (v[0]+w*t[0]+y*t[2]-z*t[1],
                       v[1]+w*t[1]+z*t[0]-x*t[2],
                       v[2]+w*t[2]+x*t[1]-y*t[0])
            position = [centre[a]+rotated[a] for a in range(3)]
            grid = tuple(round(value/h-.5) for value in position)
            if any(abs(position[a]-(grid[a]+.5)*h) > max(1e-10, h*1e-7) for a in range(3)):
                raise ValueError("native Matter cell is not on the canonical grid")
            native.add(grid)
        if len(placement_grid) != 3 or any(type(v) is not int for v in placement_grid):
            raise ValueError("Matter placement must be an integer-grid translation")
        expected = {tuple(g[a] + placement_grid[a] for a in range(3))
                    for g in _grid_set(matter)}
        materials = {engine_materials.canonical(row["material"]) for row in matter["cells"]}
        if len(offsets) != len(native) or native != expected:
            raise ValueError("native engine cells differ from the canonical Matter artifact")
        if materials != {engine_materials.canonical(body["material"])}:
            raise ValueError("native engine material differs from the canonical Matter artifact")
    except (KeyError, TypeError, struct.error) as exc:
        raise ValueError("the native snapshot cannot verify the compiled Matter cells") from exc
    return {"engine_grid_verified": True, "engine_cells": len(native),
            "render_geometry": {root: {"revision": body.get("revision", 0),
                                        "cell_size_m": h, "offsets_m": offsets}}}


def piece_geometry(snapshot: Any, cell_size_m: float, known: dict[str, Any]) -> None:
    """Every body's own cells from a native snapshot, for the ones not drawn yet.

    Pieces are new bodies with new names, so a recording's one entry per name
    holds them. A name that comes back changed keeps its first shape under the
    plain name, which is what the frames before the change show, and the later
    one goes under name#revision.
    """
    for body in (snapshot or {}).get("bodies") or []:
        name, revision = str(body.get("name") or ""), int(body.get("revision") or 0)
        key = name if name not in known or int(known[name].get("revision") or 0) == revision else f"{name}#{revision}"
        if not name or key in known or not body.get("offsets_b64"):
            continue
        raw = base64.b64decode(body["offsets_b64"], validate=True)
        if len(raw) % 24:
            continue
        known[key] = {"revision": revision, "cell_size_m": cell_size_m,
                      "offsets_m": [list(v) for v in struct.iter_unpack("<ddd", raw)]}


class _LoadWatch:
    """Reads what the engine says about a load while the run goes on.

    A transparent proxy, like the recorder it wraps: the solver's calls and its
    answers are untouched. It keeps the survey's reading of the product the first
    time it is called overloaded, what each answer to that was, what statics
    said, and the cells of every body an answer left.
    """
    def __init__(self, session: Any, root: str, cell_size_m: float, geometry: dict[str, Any]) -> None:
        self.session, self.root, self.h, self.geometry = session, root, cell_size_m, geometry
        self.overload: dict[str, Any] | None = None
        self.answers: list[dict[str, Any]] = []
        self.statics: dict[str, Any] | None = None

    def __getattr__(self, name: str) -> Any:
        return getattr(self.session, name)

    def send(self, **command: Any) -> Any:
        answer = self.session.send(**command)
        if not isinstance(answer, dict):
            return answer
        for reading in answer.get("overloaded") or []:
            if self.overload is None and str(reading.get("name") or "") == self.root:
                self.overload = {key: reading.get(key) for key in
                                 ("carrying_n", "span_m", "stress_mpa", "holds_mpa", "capacity_fraction", "why")}
        for said in (answer.get("mechanics") or {}).get("statics") or []:
            if str(said.get("name") or "").startswith(self.root):
                self.statics = dict(said)
        if command.get("op") == "fracture":
            self.answers.append({"name": str(command.get("name") or ""), "at_s": round(float(answer.get("t", 0.0)), 6),
                                 "outcome": str(answer.get("outcome") or ""), "pieces": int(answer.get("pieces") or 0)})
            piece_geometry(self.session.send(op="snapshot").get("snapshot"), self.h, self.geometry)
        return answer


# Once the product has given, the question a load test asks is answered. The
# wreck is shown falling for this long, as the rigid pieces the break left.
AFTERMATH_S = 0.6
WORK_BUDGET_S = 30.0


def _run_loaded(watch: "_LoadWatch", target_s: float) -> dict[str, Any]:
    """Step the loaded product to `target_s`, answering what the world asks.

    Until the product gives, everything offered is answered, as it always was.
    After it has, nothing more is: a tabletop in pieces under a quarter of a
    tonne of iron offers a break on nearly every step, each one a lattice run
    over the load's thousands of cells, and that went on without end -- a run
    measured at 37 minutes of processor time and still going. Those are
    declined, so the pieces fall as the break left them, and the run stops
    AFTERMATH_S after the break. A wall-clock budget backs both.
    """
    state = watch.send(op="poses")
    deadline = time.monotonic() + WORK_BUDGET_S
    gave_at: float | None = None
    guard = 0
    while float(state.get("t", 0.0)) < (target_s if gave_at is None else min(target_s, gave_at + AFTERMATH_S)) - 1e-12:
        guard += 1
        if guard > 100000 or time.monotonic() > deadline:
            raise RuntimeError("The load test exceeded its work budget; no completed result is claimed.")
        state = watch.send(op="step", dt=1 / 120.0, n=1)
        while state.get("breakable"):
            if time.monotonic() > deadline:
                raise RuntimeError("The load test exceeded its work budget; no completed result is claimed.")
            name = str(state["breakable"][0])
            if gave_at is not None:
                state = watch.send(op="decline", name=name)
                continue
            state = watch.send(op="fracture", name=name, window_s=0.003)
            if state.get("outcome") == "broke" and name.startswith(watch.root):
                gave_at = float(state.get("t", 0.0))
    return state


def run_static_load(app: Any, design: WorkshopDesign, *, load_kg: float,
                    on: str = "top", cell_size_m: float = core.DEFAULT_CELL_M,
                    duration_s: float = core.DEFAULT_DURATION_S,
                    session_factory: Callable[..., Any] = live_session.Session) -> dict[str, Any]:
    duration = float(duration_s)
    if not isfinite(duration) or not 0.1 <= duration <= 10.0:
        raise ValueError("duration_s must be between 0.1 and 10 seconds")
    setup = prototype_scene(design, load_kg=load_kg, on=on, cell_size_m=cell_size_m)
    engine = Path(getattr(app, "engine_path"))
    runs = Path(getattr(app, "runs_path")) / "workshop-trials"
    runs.mkdir(parents=True, exist_ok=True)
    session = session_factory(engine, setup["spec"], runs)
    try:
        initial = session.send(op="poses")
        snapshot = session.send(op="snapshot").get("snapshot")
        if not isinstance(snapshot, dict):
            raise ValueError("the native engine could not snapshot Matter for geometry verification")
        verified = verify_engine_matter(snapshot, setup["matter"], setup["root_body"],
                                        placement_grid=setup["placement_grid"])
        geometry = dict(verified["render_geometry"])
        piece_geometry(snapshot, float(setup["cell_size_m"]), geometry)     # the load, which is no part of the product
        watch = _LoadWatch(session, setup["root_body"], float(setup["cell_size_m"]), geometry)
        final = _run_loaded(watch, duration)
    finally:
        session.close()
    pieces = [x for x in final.get("bodies") or [] if str(x.get("name") or "").startswith(setup["root_body"])]
    gave = [x for x in watch.answers if x["outcome"] == "broke" and x["name"].startswith(setup["root_body"])]
    # A run the engine made and could not answer is not a run that held. The
    # commonest reason is a section one cell thick, which has nothing across it
    # for the lattice to bend.
    unanswered = [x for x in watch.answers
                  if x["outcome"] == "could not say" and x["name"].startswith(setup["root_body"])]

    a = core._body(initial, setup["root_body"])
    b = core._body(final, setup["root_body"])
    load = core._body(final, setup["load_body"])
    moved = turned = None
    if a is not None and b is not None:
        pa, pb = a.get("position_m") or [0, 0, 0], b.get("position_m") or [0, 0, 0]
        moved = sum((float(pb[i]) - float(pa[i])) ** 2 for i in range(3)) ** 0.5
        turned = core._quat_angle_deg(a.get("orientation_wxyz") or [1, 0, 0, 0],
                                      b.get("orientation_wxyz") or [1, 0, 0, 0])

    return {
        "schema": core.TRIAL_SCHEMA,
        "evidence": "engine-trial",
        "trial": "static_load",
        "design_id": design.design_id,
        "requested": {"load_kg": round(float(load_kg), 4), "on": on,
                      "duration_s": duration, "cell_size_m": float(cell_size_m)},
        "prototype": {
            "root_body": setup["root_body"],
            "body_count": len(setup["spec"].get("bodies") or []),
            "one_material_join": True,
            "effective_cell_size_m": setup["cell_size_m"],
            "matter_cells": setup["matter_cells"],
            "matter_boxes": setup["matter_boxes"],
            "matter_roundtrip_exact": setup["matter_roundtrip_exact"],
            "matter_physics_hash": setup["matter_physics_hash"],
            "matter_artifact_hash": setup["matter_artifact_hash"],
            "engine_geometry": "joined-grid-boxes-exact-cell-union",
            "engine_grid_verified": verified["engine_grid_verified"],
            "engine_cells": verified["engine_cells"],
            "placement_grid": setup["placement_grid"],
            "placement_offset_m": setup["placement_offset_m"],
        },
        "measured": {
            "clock_s": round(float(final.get("t", 0.0)), 6),
            "prototype_present": b is not None,
            "load_present": load is not None,
            "prototype_displacement_m": round(moved, 6) if moved is not None else None,
            "prototype_rotation_change_deg": round(turned, 4) if turned is not None else None,
            "load_position_m": ([round(float(v), 6) for v in load.get("position_m", [])]
                                if load is not None else None),
            "fractures": watch.answers,
            # What became of it, in the engine's words: whether the load survey
            # ever called it overloaded and why, what statics then said, and
            # how many pieces of it there are at the end.
            "outcome": "broke" if gave else "could not say" if unanswered else "held",
            "pieces": len(pieces),
            "first_break_s": gave[0]["at_s"] if gave else None,
            "overload": watch.overload,
            "statics": watch.statics,
            "requested_load_kg": round(load_kg, 4),
            "actual_grid_load_kg": round(float(setup["actual_load_kg"]), 4),
        },
        "acceptance": {
            "status": "not-declared",
            "why": ("the assembly declares the load to try, but not a displacement/rotation/failure "
                    "tolerance; this result is evidence, not an invented pass/fail"),
        },
        "render_geometry": geometry,
        "limitations": [
            "The test mass is quantized to whole lattice cells; requested and actual grid load are both reported.",
            "The native scene schema still lacks a compact sparse-body field; joined grid boxes are a lossless encoding of the same cell artifact."
        ],
    }
