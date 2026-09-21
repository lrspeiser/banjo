"""A Workshop design as exact rigid bodies on pins.

The owner's plan for products in the world (docs/product-framework.md): few
rigid bodies and real joints, each part its true shape and material, cells only
when something breaks. This compiles a design to that:

* its FIXED joints make its rigid groups, as the Workshop's product contract
  has always reduced them (the cart: a chassis and two wheelsets);
* each group is one exact compound (precise_rigid) made of the design's own
  parts -- boxes, and cylinders along their own y -- turned as drawn and each of
  its own material, so a 30 mm iron axle through oak wheels is exactly that, not
  a cell it does not fill;
* its BEARINGS are pins: one free hinge between each pair of groups a bearing
  joins, through the bearings' own pivots (two coaxial pins on one pair would
  only fight each other in the solver, and say nothing more).

The engine measures each body -- overlapping parts counted once, as the part
listed first, the Workshop's own rule for a shared space -- and re-centres it on
its centre of mass. Nothing here is voxelised, funded or installed; placing an
artifact in a room is `placed`.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
import math
import re
from typing import Any

from mcp import core_use, engine_materials, interaction_points, workshop_construction, workshop_visual

SCHEMA = "banjo.rigid-assembly.v1"
MATERIALS = ("glass", "oak", "iron", "concrete")


def _quaternion(m) -> list[float]:
    """w, x, y, z of a rotation matrix whose columns are a part's own axes."""
    trace = m[0][0] + m[1][1] + m[2][2]
    if trace > 0:
        s = math.sqrt(trace + 1.0) * 2
        q = [0.25 * s, (m[2][1] - m[1][2]) / s, (m[0][2] - m[2][0]) / s, (m[1][0] - m[0][1]) / s]
    elif m[0][0] > m[1][1] and m[0][0] > m[2][2]:
        s = math.sqrt(1.0 + m[0][0] - m[1][1] - m[2][2]) * 2
        q = [(m[2][1] - m[1][2]) / s, 0.25 * s, (m[0][1] + m[1][0]) / s, (m[0][2] + m[2][0]) / s]
    elif m[1][1] > m[2][2]:
        s = math.sqrt(1.0 + m[1][1] - m[0][0] - m[2][2]) * 2
        q = [(m[0][2] - m[2][0]) / s, (m[0][1] + m[1][0]) / s, 0.25 * s, (m[1][2] + m[2][1]) / s]
    else:
        s = math.sqrt(1.0 + m[2][2] - m[0][0] - m[1][1]) * 2
        q = [(m[1][0] - m[0][1]) / s, (m[0][2] + m[2][0]) / s, (m[1][2] + m[2][1]) / s, 0.25 * s]
    norm = math.sqrt(sum(v * v for v in q))
    q = [v / norm for v in q]
    return [-v for v in q] if q[0] < 0 else q


def _turn(q: list[float]):
    w, x, y, z = q
    return ((1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)),
            (2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)),
            (2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)))


def _apply(m, v):
    return [sum(m[a][k] * v[k] for k in range(3)) for a in range(3)]


def _part(part, skins) -> dict[str, Any]:
    """One Workshop part as an exact precise-rigid part, in the design's frame."""
    skin = skins.get(part.name, {})
    if skin.get("physical") and workshop_visual._effective_profile(part, skin) == "curve":
        raise ValueError(f"{part.name}: a curved physical skin is neither a box nor a cylinder")
    material = engine_materials.scene_name(part.material)
    if material not in MATERIALS:
        raise ValueError(f"{part.name}: an exact rigid part is glass, oak, iron or concrete, not {part.material}")
    size = [float(v) for v in part.size_m]
    out = {"name": part.name, "dimensions_m": size, "center_local_m": [float(v) for v in part.center_m],
           "material": material}
    if part.shape == "cylinder":
        # A Workshop cylinder runs along its own y and fills {w, h, d}; a
        # round one has w == d.
        if abs(size[0] - size[2]) > 1e-9 * max(1.0, size[0]):
            raise ValueError(f"{part.name}: an oval cylinder has no exact rigid shape")
        out["shape"] = "cylinder"
    q = _quaternion(workshop_construction.rotation_matrix(part.rotation_deg))
    if abs(q[0] - 1.0) > 1e-12:
        out["rotation_wxyz"] = q
    return out


def _mass(part) -> float:
    return float(part.volume_m3()) * engine_materials.density(engine_materials.scene_name(part.material))


def compile_design(design, overrides=None, *, root: str = "assembly") -> dict[str, Any]:
    """The design's rigid groups as exact compounds, and its bearings as pins,
    all in the design's own frame (its floor at y = 0)."""
    if not isinstance(root, str) or not re.fullmatch(r"[A-Za-z0-9 _-]{1,64}", root):
        raise ValueError("An assembly root needs 1..64 letters, digits, spaces, underscores or hyphens")
    parts = {p.name: p for p in design.parts}
    order = [p.name for p in design.parts]
    joints = workshop_construction.adopted(design)["joints"]
    parent = {name: name for name in parts}

    def find(name):
        while parent[name] != name:
            name = parent[name]
        return name

    for joint in joints:
        if joint["kind"] == "fixed":
            parent[find(joint["b"])] = find(joint["a"])
    groups = defaultdict(list)
    for name in order:
        groups[find(name)].append(name)
    group_list = sorted(groups.values(), key=lambda names: (-sum(_mass(parts[n]) for n in names), names[0]))
    group_of = {name: i for i, names in enumerate(group_list) for name in names}
    # The heaviest group carries the product's name: it is what the room calls
    # the product, the one its primary use is bound to.
    body_names = [root if i == 0 else f"{root}-{i}" for i in range(len(group_list))]
    pairs: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for joint in joints:
        if joint["kind"] != "bearing":
            continue
        a, b = group_of[joint["a"]], group_of[joint["b"]]
        if a == b:
            raise ValueError(f"The bearing between {joint['a']} and {joint['b']} is locked by a fixed path")
        found = workshop_construction.interface(parts[joint["a"]], parts[joint["b"]])
        if not found or "axis" not in found:
            raise ValueError(f"The bearing between {joint['a']} and {joint['b']} has no shaft to turn on")
        pairs[(min(a, b), max(a, b))].append({"joint": joint, "centre_m": list(found["centre_m"]),
                                               "axis": list(found["axis"])})
    # Every group must be held to the rest by a pin, or it is a loose part.
    reached, pending = {0}, [0]
    while pending:
        i = pending.pop()
        for a, b in pairs:
            for j in ((b,) if a == i else (a,) if b == i else ()):
                if j not in reached:
                    reached.add(j)
                    pending.append(j)
    if len(reached) != len(group_list):
        loose = sorted(n for i, names in enumerate(group_list) if i not in reached for n in names)
        raise ValueError("Every rigid group must be held by a bearing; loose: " + ", ".join(loose))

    import precise_rigid
    skins = workshop_visual.skin_overrides(overrides)
    bodies = []
    for i, names in enumerate(group_list):
        masses = defaultdict(float)
        for name in names:
            masses[engine_materials.scene_name(parts[name].material)] += _mass(parts[name])
        material = max(sorted(masses), key=lambda m: masses[m])
        drawn = []
        for name in names:
            part = _part(parts[name], skins)
            if part["material"] == material:
                del part["material"]
            drawn.append(part)
        total = sum(_mass(parts[n]) for n in names)
        centre = [sum(_mass(parts[n]) * float(parts[n].center_m[a]) for n in names) / total for a in range(3)]
        bodies.append({"name": body_names[i], "material": material, "position_m": [0.0, 0.0, 0.0],
                       "orientation_wxyz": [1.0, 0.0, 0.0, 0.0], "parts": drawn,
                       "color_rgba": precise_rigid.colour(material),
                       "_centre_m": centre, "_components": names})
    pins = []
    for (a, b), bearings in sorted(pairs.items()):
        axis = bearings[0]["axis"]
        # All one axle: the pivots' middle, on the shared axis.
        signed = [x if sum(x[k] * axis[k] for k in range(3)) >= 0 else [-v for v in x]
                  for x in (bg["axis"] for bg in bearings)]
        mean = [sum(x[k] for x in signed) for k in range(3)]
        norm = math.sqrt(sum(v * v for v in mean))
        pins.append({"kind": "hinge", "a": body_names[a], "b": body_names[b],
                     "at_mm": [1000.0 * sum(bg["centre_m"][k] for bg in bearings) / len(bearings) for k in range(3)],
                     "axis": [v / norm for v in mean], "lower_deg": -180.0, "upper_deg": 180.0, "friction_n_m": 0.0,
                     "stands_for": sorted(bg["joint"]["id"] for bg in bearings)})
    return {"schema": SCHEMA, "design_id": design.design_id, "root": root, "bodies": bodies, "joints": pins,
            "component_to_body": {name: body_names[group_of[name]] for name in order},
            "source_joints": joints,
            "limitations": ["Ideal pins: no bearing strength, wear or friction; the wheels' rolling resistance is the ground's and their own.",
                            "No internal failure: a blow that would break a lattice body against one of these is declined and reported."]}


def placed(artifact: dict[str, Any], origin_m: list[float], yaw_rad: float = 0.0) -> dict[str, Any]:
    """The artifact turned about y by `yaw_rad` and set down with its design
    origin at `origin_m`: bodies, pins and all."""
    q = [math.cos(yaw_rad / 2), 0.0, math.sin(yaw_rad / 2), 0.0]
    r = _turn(q)
    out = deepcopy(artifact)
    for body in out["bodies"]:
        body["position_m"] = [origin_m[k] for k in range(3)]
        body["orientation_wxyz"] = q
        body["_centre_m"] = [origin_m[k] + v for k, v in enumerate(_apply(r, body["_centre_m"]))]
    for pin in out["joints"]:
        pin["at_mm"] = [1000.0 * origin_m[k] + v for k, v in enumerate(_apply(r, pin["at_mm"]))]
        pin["axis"] = _apply(r, pin["axis"])
    return out


def footprint(artifact: dict[str, Any]):
    """Each part's lowest point and the box of ground under it, as placed:
    [(lowest y, (x_lo, z_lo), (x_hi, z_hi)), ...]."""
    import precise_rigid
    out = []
    for body in artifact["bodies"]:
        for part in body["parts"]:
            lo, hi = precise_rigid.bounds([part], body["position_m"], body["orientation_wxyz"])
            out.append((lo[1], (lo[0], lo[2]), (hi[0], hi[2])))
    return out


def room_entries(design, artifact: dict[str, Any]):
    """What the room needs besides the bodies: each body's use, and the
    design's interaction points on the body whose part is nearest each one --
    about that body's centre of mass, which is where the room puts it."""
    actions, records = [], []
    points = interaction_points.for_design(design)
    parts = {p.name: p for p in design.parts}
    owner = {}
    for point in points:
        at = point["position_m"]

        def distance(name):
            lo, hi = workshop_construction._bounds(parts[name])
            return sum(max(lo[k] - at[k], 0.0, at[k] - hi[k]) ** 2 for k in range(3))

        owner[point["id"]] = artifact["component_to_body"][min(parts, key=distance)]
    source = {b["name"]: b for b in compile_design(design, root=artifact["root"])["bodies"]}
    for body in artifact["bodies"]:
        name = body["name"]
        actions.append(core_use.installed(design, name) if name == artifact["root"]
                       else dict(deepcopy(core_use.DEFAULT), body=name, primary=True))
        centre = source[name]["_centre_m"]
        mine = []
        for point in points:
            if owner[point["id"]] != name:
                continue
            point = deepcopy(point)
            point["position_m"] = [point["position_m"][k] - centre[k] for k in range(3)]
            mine.append(point)
        records.append({"body": name, "points": interaction_points.checked(mine)})
    return actions, records


def scene_bodies(artifact: dict[str, Any]) -> list[dict[str, Any]]:
    """The precise_rigid_bodies entries, without the compiler's own notes."""
    return [{k: v for k, v in body.items() if not k.startswith("_")} for body in artifact["bodies"]]


def scene_joints(artifact: dict[str, Any]) -> list[dict[str, Any]]:
    return [{k: v for k, v in pin.items() if k != "stands_for"} for pin in artifact["joints"]]
