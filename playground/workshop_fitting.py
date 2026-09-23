"""Check Validity: are the concepts there, and can it be redrawn so it works?

A person puts the idea of a machine together -- a deck, wheels, the shaft they
turn on, the mounts that hold it -- and the sizes they happen to choose are not
the sizes a room's cell grid can carry.  This says whether the concepts are
there, and then redraws the parts until the machine compiles into separate
bodies that keep their joints and stay breakable, listing every change and why.

What it may change is how big a part is, where it sits, and whether one long
shaft is drawn as a stub per bearing.  What it may NOT do is invent a concept
that is missing: a wheel with nothing to turn on is refused and said plainly,
because guessing there would be designing on the person's behalf.

The three redraws each answer a refusal the articulated compiler actually
gives, and they are tried in this order because each can create the next:

    nothing thinner than two cells   "Every component must retain its own
                                      occupied cells"
    a shaft becomes stubs            "Moving groups overlap in the cell grid"
                                     "... is claimed by both <a> and <b>"

A shaft threaded THROUGH its mount can never compile, at any cell size: a
lattice body cannot carry a hole for another body to turn inside, and the
overlap survives 40, 20 and 10 mm cells alike.  The grid-legal bearing is a
stub that meets its mount face to face, which is how the rover's wheels are
built in the world today.
"""
from __future__ import annotations

from copy import deepcopy
import math
from typing import Any

from mcp import workshop_components
from mcp import workshop_construction as construction
from mcp.workshop import WirePart, strut as workshop_strut
import workshop_articulation

SCHEMA = "banjo.workshop-validity.v1"
MIN_CELLS = 2
MAX_PASSES = 8


# --------------------------------------------------------------------------
# Are the concepts there?
# --------------------------------------------------------------------------
def _graph(design: Any) -> tuple[list[dict[str, Any]], dict[str, set[str]]]:
    joints = construction.joints(design)
    touching: dict[str, set[str]] = {p.name: set() for p in design.parts}
    for joint in joints:
        touching.setdefault(joint["a"], set()).add(joint["b"])
        touching.setdefault(joint["b"], set()).add(joint["a"])
    return joints, touching


def concepts(design: Any) -> list[dict[str, Any]]:
    """What the assembly has to be before any redrawing is worth trying."""
    joints, touching = _graph(design)
    names = [p.name for p in design.parts]
    bearings = [j for j in joints if j["kind"] == "bearing"]
    turning = {name for joint in bearings for name in (joint["a"], joint["b"])}
    loose = sorted(name for name in names if not touching.get(name))
    said: list[dict[str, Any]] = []

    said.append({"concept": "every part is fastened to another",
                 "ok": not loose,
                 "says": "all fastened" if not loose else
                         "nothing holds " + ", ".join(loose)})

    wheels = [p.name for p in design.parts if p.role == "wheel"]
    unborne = sorted(w for w in wheels if not (touching.get(w, set()) | {w}) & turning
                     and w not in turning)
    said.append({"concept": "every wheel has something to turn on",
                 "ok": not wheels or not unborne,
                 "says": "no wheels" if not wheels else
                         "all borne" if not unborne else
                         ", ".join(unborne) + " turns on nothing"})

    still = [name for name in names if name not in turning]
    said.append({"concept": "something stands still for the rest to move against",
                 "ok": bool(still) or not bearings,
                 "says": "nothing is fixed; it is all moving parts" if not still and bearings
                         else f"{len(still)} part(s) make the frame"})

    said.append({"concept": "a joint holds two parts that are both here",
                 "ok": all(j["a"] in touching and j["b"] in touching for j in joints),
                 "says": f"{len(joints)} joint(s), {len(bearings)} of them turning"})

    open_joints = [j for j in joints if j.get("open")]
    said.append({"concept": "no joint hangs open",
                 "ok": not open_joints,
                 "says": "all closed" if not open_joints else open_joints[0].get("why", "a joint is open")})
    return said


# --------------------------------------------------------------------------
# Geometry the redraws need
# --------------------------------------------------------------------------
def _world_axis(part: WirePart) -> tuple[int, int, float]:
    """Which world axis the part is longest along: (world axis, local axis, half length)."""
    matrix = construction.rotation_matrix(part.rotation_deg)
    local = max(range(3), key=lambda i: part.size_m[i])
    column = construction._column(matrix, local)
    world = max(range(3), key=lambda i: abs(column[i]))
    return world, local, part.size_m[local] / 2.0


def _span(part: WirePart, axis: int) -> tuple[float, float]:
    matrix = construction.rotation_matrix(part.rotation_deg)
    reach = sum(abs(construction._column(matrix, i)[axis]) * part.size_m[i] / 2.0 for i in range(3))
    return part.center_m[axis] - reach, part.center_m[axis] + reach


def _overlaps(a: WirePart, b: WirePart) -> bool:
    for axis in range(3):
        lo_a, hi_a = _span(a, axis)
        lo_b, hi_b = _span(b, axis)
        if hi_a <= lo_b + 1e-9 or hi_b <= lo_a + 1e-9:
            return False
    return True


def _readopt(base: Any, overrides: dict[str, Any]) -> dict[str, Any]:
    """Read the connections off the parts as they now stand, keeping their kinds.

    Joints adopted before a redraw hang open the moment anything moves, so a
    redraw has to adopt again -- and adopting works connections out from what
    touches what, which would quietly turn every authored bearing back into a
    bond. What the person declared is intent and survives the redraw; only the
    drawing changes. Within one spec the construction is applied BEFORE the
    per-part patches, so this cannot be done in a single pass either.
    """
    was = overrides.get(construction.CONSTRUCTION_KEY) or {}
    kinds = {tuple(sorted((j["a"], j["b"]))): j["kind"] for j in (was.get("joints") or [])}
    # Apply the whole record, added and removed parts included: the joints it
    # carries are measured against the old geometry and may read open, which is
    # exactly why they are thrown away and worked out again from the result.
    fitted = workshop_components.apply_overrides(base, overrides)
    fresh = construction.adopted(fitted)
    for key in ("added", "removed"):
        if was.get(key):
            fresh[key] = deepcopy(was[key])
    for joint in fresh.get("joints") or []:
        kind = kinds.get(tuple(sorted((joint["a"], joint["b"]))))
        if kind and kind != joint["kind"]:
            joint["kind"] = kind
    merged = dict(overrides)
    merged[construction.CONSTRUCTION_KEY] = fresh
    return merged


def _built(base: Any, overrides: dict[str, Any]) -> Any:
    return workshop_components.apply_overrides(base, overrides)


def _why_not(design: Any, overrides: dict[str, Any], cell_m: float, root: str) -> str | None:
    try:
        workshop_articulation.compile_design(design, overrides, cell_m=cell_m, root=root)
    except ValueError as problem:
        return str(problem)
    return None


# --------------------------------------------------------------------------
# The redraws
# --------------------------------------------------------------------------
def _grow_to_whole_cells(base: Any, design: Any, overrides: dict[str, Any], cell_m: float) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Nothing thinner than two cells, or the grid loses it between its neighbours."""
    floor = MIN_CELLS * cell_m
    # The construction rides along: it carries the parts a redraw has added.
    patch = {k: deepcopy(v) for k, v in overrides.items()}
    said: list[dict[str, Any]] = []
    parts = {p.name: p for p in design.parts}
    _, touching = _graph(design)
    for part in design.parts:
        size = list(part.size_m)
        grown = [max(v, floor) if v < floor else v for v in size]
        if grown == size:
            continue
        # A part grows AWAY from what it is joined to. Growing about the centre
        # walks its faces through its neighbours, and every bonded joint that
        # used to touch there hangs open.
        thicker = WirePart(name=part.name, role=part.role, size_m=tuple(grown),
                           center_m=tuple(part.center_m), material=part.material,
                           rotation_deg=tuple(part.rotation_deg), shape=part.shape,
                           family=part.family)
        centre = list(part.center_m)
        for axis in range(3):
            was_lo, was_hi = _span(part, axis)
            now_lo, now_hi = _span(thicker, axis)
            growth = (now_hi - now_lo) - (was_hi - was_lo)
            if growth <= 1e-9:
                continue
            below = above = False
            for other in touching.get(part.name, ()):  # noqa: B007
                mate = parts.get(other)
                if mate is None:
                    continue
                lo, hi = _span(mate, axis)
                if hi <= was_lo + 1e-6:
                    below = True
                elif lo >= was_hi - 1e-6:
                    above = True
            if below and not above:
                centre[axis] += growth / 2.0
            elif above and not below:
                centre[axis] -= growth / 2.0
        patch.setdefault(part.name, {})["size_m"] = grown
        if [round(v, 9) for v in centre] != [round(v, 9) for v in part.center_m]:
            patch[part.name]["center_m"] = centre
        thin = [f"{round(v * 1000)} mm" for v in size if v < floor]
        said.append({"rule": "nothing thinner than two cells", "part": part.name,
                     "says": f"{part.name} was {' and '.join(thin)} across, under two "
                             f"{round(cell_m * 1000)} mm cells; drawn at "
                             f"{round(floor * 1000)} mm, grown away from what it is joined to"})
    if not said:
        return overrides, []
    return _readopt(base, patch), said


def _shaft_stubs(base: Any, design: Any, overrides: dict[str, Any], cell_m: float) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """A shaft threaded through its mounts becomes one stub per bearing.

    The concept is untouched -- the wheels still turn on something the frame
    holds -- but a stub butts against its mount instead of passing through it,
    which is the only bearing a cell grid can carry.
    """
    parts = {p.name: p for p in design.parts}
    joints = construction.joints(design)
    bearings = [j for j in joints if j["kind"] == "bearing"]
    said: list[dict[str, Any]] = []
    work = dict(overrides)
    current = design

    shafts: dict[str, list[str]] = {}
    for joint in bearings:
        for shaft_name, mount_name in ((joint["a"], joint["b"]), (joint["b"], joint["a"])):
            shaft, mount = parts.get(shaft_name), parts.get(mount_name)
            if shaft is None or mount is None or not _overlaps(shaft, mount):
                continue
            # The shaft is the one that runs THROUGH: it is longer along the
            # axis they share than the part it passes into.
            axis, _, half = _world_axis(shaft)
            lo_m, hi_m = _span(mount, axis)
            if half * 2 > (hi_m - lo_m) + 1e-9:
                shafts.setdefault(shaft_name, []).append(mount_name)

    for shaft_name, mounts in shafts.items():
        if len(mounts) < 2:
            continue
        shaft = parts[shaft_name]
        axis, local, half = _world_axis(shaft)
        fixed_to = [j for j in joints if j["kind"] == "fixed" and shaft_name in (j["a"], j["b"])]
        riders = [j["b"] if j["a"] == shaft_name else j["a"] for j in fixed_to]
        overrides_now = dict(work)
        for index, mount_name in enumerate(sorted(mounts, key=lambda n: parts[n].center_m[axis])):
            mount = parts[mount_name]
            side = 1.0 if mount.center_m[axis] >= shaft.center_m[axis] else -1.0
            rider = min((parts[r] for r in riders if r in parts
                         and (parts[r].center_m[axis] - shaft.center_m[axis]) * side > 0),
                        key=lambda p: abs(p.center_m[axis] - mount.center_m[axis]), default=None)
            lo_m, hi_m = _span(mount, axis)
            start = hi_m if side > 0 else lo_m
            if rider is not None:
                # Butt against the wheel's near face. A stub driven INTO it would
                # put oak and iron in one cell, which no cell can carry.
                lo_r, hi_r = _span(rider, axis)
                end = lo_r if side > 0 else hi_r
            else:
                end = shaft.center_m[axis] + side * half
            length = abs(end - start)
            if length < cell_m:
                length = MIN_CELLS * cell_m
                end = start + side * length
            size = list(shaft.size_m)
            size[local] = length
            centre = list(shaft.center_m)
            centre[axis] = (start + end) / 2.0
            stub = WirePart(name=f"{shaft_name}-stub-{index + 1}", role=shaft.role,
                            size_m=tuple(size), center_m=tuple(centre), material=shaft.material,
                            rotation_deg=tuple(shaft.rotation_deg), shape=shaft.shape,
                            family=shaft.family)
            overrides_now = construction.add_part(current, overrides_now, part=stub,
                                                  joint={"to": mount_name, "kind": "bearing"})
            current = _built(base, overrides_now)
            if rider is not None:
                overrides_now = construction.set_joint(current, overrides_now, a=stub.name,
                                                       b=rider.name, kind="fixed")
                current = _built(base, overrides_now)
        overrides_now = construction.remove_part(current, overrides_now, shaft_name)
        current = _built(base, overrides_now)
        work = overrides_now
        said.append({"rule": "a shaft through its mounts becomes stubs", "part": shaft_name,
                     "says": f"{shaft_name} ran through {len(mounts)} mounts, and no lattice body "
                             f"can hold a turning shaft inside it; drawn as {len(mounts)} stubs "
                             f"butted to their mounts, which turn the same way"})
    if not said:
        return overrides, []
    return work, said


def _one_material_to_a_group(base: Any, design: Any, overrides: dict[str, Any], cell_m: float) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Parts fastened rigidly into one moving group are made of one material.

    The compiler carries a group as one lattice body, and a body is one
    material. The group takes the material of most of its bulk, so a small
    iron stub bonded into an oak wheel becomes oak rather than the wheel
    becoming iron.
    """
    parts = {p.name: p for p in design.parts}
    joints = construction.joints(design)
    parent = {name: name for name in parts}

    def find(name: str) -> str:
        while parent[name] != name:
            parent[name] = parent[parent[name]]
            name = parent[name]
        return name

    for joint in joints:
        if joint["kind"] == "fixed" and joint["a"] in parent and joint["b"] in parent:
            parent[find(joint["b"])] = find(joint["a"])

    groups: dict[str, list[str]] = {}
    for name in parts:
        groups.setdefault(find(name), []).append(name)

    # The construction rides along: it carries the parts a redraw has added.
    patch = {k: deepcopy(v) for k, v in overrides.items()}
    said: list[dict[str, Any]] = []
    for members in groups.values():
        bulk: dict[str, float] = {}
        for name in members:
            part = parts[name]
            bulk[part.material] = bulk.get(part.material, 0.0) + math.prod(part.size_m)
        if len(bulk) < 2:
            continue
        winner = max(bulk, key=bulk.get)
        changed = [n for n in members if parts[n].material != winner]
        for name in changed:
            patch.setdefault(name, {})["material"] = winner
        said.append({"rule": "one material to a moving group", "part": ", ".join(sorted(changed)),
                     "says": f"{', '.join(sorted(changed))} moved as one body with "
                             f"{len(members) - len(changed)} {winner} part(s), and a body is one "
                             f"material; drawn in {winner}, which is weaker or stronger than "
                             f"you drew it"})
    if not said:
        return overrides, []
    # Only materials changed, so nothing moved and the construction still holds.
    merged = dict(overrides)
    merged.update({k: v for k, v in patch.items() if k != construction.CONSTRUCTION_KEY})
    return merged, said


def _snap_to_the_grid(base: Any, design: Any, overrides: dict[str, Any], cell_m: float) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Every face lands on a cell boundary, so no part is rounded out of existence.

    A part whose faces fall inside a cell shares that cell with whatever else
    reaches into it, and the compiler hands the cell to one of them. Snapping
    each face out to the nearest boundary gives every part whole cells that are
    unarguably its own.
    """
    # The construction rides along: it carries the parts a redraw has added.
    patch = {k: deepcopy(v) for k, v in overrides.items()}
    said: list[dict[str, Any]] = []
    for part in design.parts:
        matrix = construction.rotation_matrix(part.rotation_deg)
        # Only what stands square to the room can have its faces on the grid. A
        # raked strut is left as drawn: snapping its local sides as if they were
        # world axes swings its ends off whatever it was joined to.
        if any(abs(abs(v) - round(abs(v))) > 1e-6 for row in matrix for v in row):
            continue
        size, centre = list(part.size_m), list(part.center_m)
        moved = False
        for local in range(3):
            column = construction._column(matrix, local)
            axis = max(range(3), key=lambda i: abs(column[i]))
            half = part.size_m[local] / 2.0
            # NEAREST boundary, not outward: two parts butted on a face round to
            # the same line and go on touching. Rounding both outward makes them
            # overlap by a cell, and every joint between them reads open.
            lo = round(round((part.center_m[axis] - half) / cell_m, 6)) * cell_m
            hi = round(round((part.center_m[axis] + half) / cell_m, 6)) * cell_m
            if hi - lo < MIN_CELLS * cell_m:
                middle = (lo + hi) / 2.0
                lo = middle - MIN_CELLS * cell_m / 2.0
                hi = middle + MIN_CELLS * cell_m / 2.0
            if abs((hi - lo) - part.size_m[local]) > 1e-9 or abs((lo + hi) / 2.0 - part.center_m[axis]) > 1e-9:
                moved = True
            size[local], centre[axis] = hi - lo, (lo + hi) / 2.0
        if moved:
            patch.setdefault(part.name, {})["size_m"] = size
            patch[part.name]["center_m"] = centre
            said.append({"rule": "every face on a cell boundary", "part": part.name,
                         "says": f"{part.name} had faces inside a cell, where the grid gives the "
                                 f"cell to whichever part reaches furthest; snapped out to whole "
                                 f"{round(cell_m * 1000)} mm cells"})
    if not said:
        return overrides, []
    return _readopt(base, patch), said


def _strutlike(part: WirePart, joined: set[str]) -> bool:
    """A member that spans two things: long, slender, and fastened at both ends."""
    if len(joined) != 2:
        return False
    sizes = sorted(part.size_m)
    return sizes[2] > 2.5 * max(sizes[1], 1e-9)


def _ends(part: WirePart) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    matrix = construction.rotation_matrix(part.rotation_deg)
    local = max(range(3), key=lambda i: part.size_m[i])
    column = construction._column(matrix, local)
    half = part.size_m[local] / 2.0
    lo = tuple(part.center_m[i] - column[i] * half for i in range(3))
    hi = tuple(part.center_m[i] + column[i] * half for i in range(3))
    return lo, hi


def _rebuild_struts(base: Any, design: Any, overrides: dict[str, Any], cell_m: float) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """A strut is its two anchors, so after a redraw it is rebuilt between them.

    Everything else here resizes a part where it stands. That cannot work for a
    member that spans two things: the moment either end moves, a resized strut
    is the wrong length and pointing the wrong way, and the joints at both ends
    hang open. The template builds these from their endpoints, and so does this.
    """
    was = _built(base, _readopt(base, {}))
    original = {p.name: p for p in was.parts}
    _, touching_then = _graph(was)
    now = {p.name: p for p in design.parts}
    _, touching_now = _graph(design)
    open_pairs = {tuple(sorted((j["a"], j["b"]))) for j in construction.joints(design) if j.get("open")}
    if not open_pairs:
        return overrides, []

    patch = {k: deepcopy(v) for k, v in overrides.items()}
    said: list[dict[str, Any]] = []
    for name, part in original.items():
        mates = touching_then.get(name, set())
        if not _strutlike(part, mates) or name not in now:
            continue
        if not any(tuple(sorted((name, mate))) in open_pairs for mate in mates):
            continue
        anchors = []
        lo, hi = _ends(part)
        for mate in sorted(mates):
            other_then, other_now = original.get(mate), now.get(mate)
            if other_then is None or other_now is None:
                break
            end = min((lo, hi), key=lambda e: sum((e[i] - other_then.center_m[i]) ** 2 for i in range(3)))
            # Where it holds the other part, as a fraction of that part rather
            # than in metres: an end on the deck's top face has to stay on the
            # top face when the deck is drawn thicker, not end up buried in it.
            local = construction.to_local(other_then, end)
            share = [local[i] / max(other_then.size_m[i] / 2.0, 1e-9) for i in range(3)]
            moved = [share[i] * other_now.size_m[i] / 2.0 for i in range(3)]
            anchors.append(construction.to_product(other_now, moved))
        if len(anchors) != 2:
            continue
        here = now[name]
        section = sorted(here.size_m)[:2]
        try:
            rebuilt = workshop_strut(name=name, role=here.role, from_m=anchors[0], to_m=anchors[1],
                                     section_m=(section[1], section[0]), material=here.material,
                                     shape=here.shape, family=here.family)
        except ValueError:
            continue
        patch.setdefault(name, {})
        patch[name]["size_m"] = list(rebuilt.size_m)
        patch[name]["center_m"] = list(rebuilt.center_m)
        patch[name]["rotation_deg"] = list(rebuilt.rotation_deg)
        said.append({"rule": "a strut is rebuilt between its anchors", "part": name,
                     "says": f"{name} spans two things that the redraw moved; rebuilt between "
                             f"where it holds them now, at "
                             f"{round(max(rebuilt.size_m) * 1000)} mm long"})
    if not said:
        return overrides, []
    return _readopt(base, patch), said


RULES = (
    ("retain its own occupied cells", _grow_to_whole_cells),
    ("absent from the compiled occupied cells", _snap_to_the_grid),
    ("authored joint is open", _rebuild_struts),
    ("no longer touch", _rebuild_struts),
    ("Moving groups overlap", _shaft_stubs),
    ("is claimed by both", _shaft_stubs),
    ("mixed-material interface", _one_material_to_a_group),
)


def _rule_for(problem: str):
    for marker, rule in RULES:
        if marker in problem:
            return rule
    return None


# --------------------------------------------------------------------------
def check_validity(design: Any, overrides: Any = None, *, cell_m: float = 0.04,
                   root: str = "assembly") -> dict[str, Any]:
    """Whether this assembly is a machine, and what it took to make it one.

    ``design`` is the assembly as the person left it. Everything after this is
    built back from it, so a redraw is always the template plus one set of
    overrides rather than a design patched on top of a patched design.
    """
    base = design
    overrides = dict(overrides or {})
    if construction.CONSTRUCTION_KEY not in overrides:
        overrides = _readopt(base, overrides)
    current = _built(base, overrides)

    said = concepts(current)
    missing = [c for c in said if not c["ok"]]
    if missing:
        return {"schema": SCHEMA, "ok": False, "stage": "concepts", "concepts": said,
                "changes": [], "overrides": overrides,
                "says": "It is not a machine yet: " + "; ".join(c["says"] for c in missing)}

    changes: list[dict[str, Any]] = []
    tried: set[str] = set()
    for _ in range(MAX_PASSES):
        problem = _why_not(current, overrides, cell_m, root)
        if problem is None:
            return {"schema": SCHEMA, "ok": True, "stage": "ready", "concepts": said,
                    "changes": changes, "overrides": overrides,
                    "says": "It works as drawn." if not changes else
                            f"Redrawn in {len(changes)} place(s) so it works: "
                            + "; ".join(c["says"] for c in changes)}
        rule = _rule_for(problem)
        if rule is None or problem in tried:
            return {"schema": SCHEMA, "ok": False, "stage": "drawing", "concepts": said,
                    "changes": changes, "overrides": overrides, "why": problem,
                    "says": "The concepts are there, but it cannot be drawn to work: " + problem}
        tried.add(problem)
        overrides, made = rule(base, current, overrides, cell_m)
        if not made:
            return {"schema": SCHEMA, "ok": False, "stage": "drawing", "concepts": said,
                    "changes": changes, "overrides": overrides, "why": problem,
                    "says": "The concepts are there, but nothing here answers: " + problem}
        changes.extend(made)
        current = _built(base, overrides)
    return {"schema": SCHEMA, "ok": False, "stage": "drawing", "concepts": said,
            "changes": changes, "overrides": overrides,
            "why": "still refused after redrawing",
            "says": "Redrawn several times and it still will not compile."}
