"""Compile authored fixed/bearing construction into separate native cell bodies.

This compiler does not install or fund a product. Bearings use the existing
ideal hinge law; load rating, friction and manufacturing remain separate gates.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
import hashlib
import json
import math
import re

import fracture_lab
import workshop_sparse_trial as sparse
from mcp import engine_materials, joint_efficiency, workshop_construction, workshop_rigid, workshop_visual

SCHEMA = "banjo.workshop-articulation.v1"


def has_bearings(design):
    return any(j["kind"] == "bearing" for j in workshop_construction.joints(design))


def installed_interactions(design, artifact):
    """Resolve authored affordances onto independently moving native bodies."""
    from mcp import core_use, interaction_points
    mapping = artifact["component_to_body"]
    selected = design.parameters.get("primary_use_component")
    if not isinstance(selected, str) or selected not in mapping:
        raise ValueError("An assembly needs primary_use_component naming its operated component")
    points = interaction_points.for_design(design)
    bindings = design.parameters.get("interaction_point_components")
    if (not isinstance(bindings, dict) or set(bindings) != {p["id"] for p in points}
            or any(not isinstance(v, str) or v not in mapping for v in bindings.values())):
        raise ValueError("Bind every assembly interaction point to a known component in interaction_point_components")
    actions, records = [], []
    for group in artifact["groups"]:
        root = group["root_body"]
        actions.append(core_use.installed(design, root) if root == mapping[selected]
                       else dict(deepcopy(core_use.DEFAULT), body=root, primary=True))
        cells = sparse._grid_set(group["matter"])
        h = group["matter"]["cell_size_m"]
        com = [sum((g[a]+.5)*h for g in cells)/len(cells) for a in range(3)]
        local = []
        for point in points:
            if mapping[bindings[point["id"]]] != root: continue
            point = deepcopy(point)
            point["position_m"] = [point["position_m"][a]-com[a] for a in range(3)]
            local.append(point)
        records.append({"body":root, "points":interaction_points.checked(local)})
    return actions, records


def compile_design(design, overrides=None, *, cell_m=.04, root="assembly"):
    """Preserve fixed groups, bearing frames, cell ownership and material mass."""
    if not isinstance(root, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", root):
        raise ValueError("An assembly root needs 1..64 letters, digits, underscores or hyphens")
    if type(cell_m) not in (int, float) or not math.isfinite(cell_m) or not .005 <= cell_m <= .2:
        raise ValueError("Assembly cell_m must be finite and between .005 and .2")
    if workshop_rigid.requested_models(design, overrides) != {"lattice"}:
        raise ValueError("Articulated cell compilation requires the declared lattice model")
    names = {p.name for p in design.parts}
    joints = workshop_construction.joints(design)
    if not joints or not any(j["kind"] == "bearing" for j in joints):
        raise ValueError("Articulated construction needs an authored bearing")
    if any(j.get("open") for j in joints):
        raise ValueError("An authored joint is open; repair the construction before compiling")
    parent = {name: name for name in names}

    def find(name):
        while parent[name] != name:
            name = parent[name]
        return name

    for joint in joints:
        if joint["kind"] == "fixed":
            parent[find(joint["b"])] = find(joint["a"])
    components = defaultdict(list)
    for name in sorted(names):
        components[find(name)].append(name)
    groups = sorted(components.values())
    group_of = {name: i for i, group in enumerate(groups) for name in group}
    edges = defaultdict(set)
    for joint in joints:
        if joint["kind"] != "bearing":
            continue
        a, b = group_of[joint["a"]], group_of[joint["b"]]
        if a == b:
            raise ValueError("A bearing is locked by a fixed connection path")
        edges[a].add(b); edges[b].add(a)
    seen, pending = set(), [0]
    while pending:
        i = pending.pop()
        if i not in seen:
            seen.add(i); pending.extend(edges[i] - seen)
    if len(seen) != len(groups):
        raise ValueError("Every moving group must be connected by authored joints")

    matter = workshop_visual.matter_document(design, overrides, cell_size_m=cell_m, exterior_only=False)
    if not matter["cells"] or len(matter["cells"]) > 16000:
        raise ValueError("Assembly exceeds the native cell budget")
    rows = defaultdict(list)
    for cell in matter["cells"]:
        owners = {group_of[name] for name in cell["components"]}
        if len(owners) != 1:
            raise ValueError("Moving groups overlap in the cell grid; use explicit clearance or a finer grid")
        rows[owners.pop()].append(cell)
    if {cell["component"] for cell in matter["cells"]} != names:
        raise ValueError("Every component must retain its own occupied cells")

    bodies, compiled, component_to_body = [], [], {}
    material_mass = defaultdict(float)
    for i, group in enumerate(groups):
        cells = {tuple(c["grid"]) for c in rows[i]}
        reached, todo = set(), [next(iter(cells))]
        while todo:
            cell = todo.pop()
            if cell in reached: continue
            reached.add(cell)
            for axis in range(3):
                for direction in (-1, 1):
                    neighbor = list(cell); neighbor[axis] += direction; neighbor = tuple(neighbor)
                    if neighbor in cells and neighbor not in reached: todo.append(neighbor)
        if reached != cells:
            raise ValueError("A fixed group has disconnected native cells")
        materials = {engine_materials.canonical(c["material"]) for c in rows[i]}
        if len(materials) != 1:
            raise ValueError("A fixed group needs a supported mixed-material interface model")
        material = materials.pop()
        name = f"{root}-g{i}"
        parts = {tuple(c["grid"]): f"{root}/{c['component']}" for c in rows[i]}
        boxes = sparse.decompose_by_part(cells, parts)
        if sparse.cells_from_boxes([box for box, _ in boxes]) != cells:
            raise ValueError("Native group decomposition changed occupied matter")
        for k, (box, part) in enumerate(boxes):
            bodies.append(sparse._box_body(name if k == 0 else f"{name}-{k}", box, cell_m, material, name, part))
        mass = len(cells)*cell_m**3*engine_materials.density(material)
        material_mass[material] += mass
        compiled.append({"root_body":name,"components":group,"mass_kg":mass,
                         "matter":{"cell_size_m":cell_m,"cells":rows[i],"total_cells":len(cells),
                                   "source_physics_hash":matter["physics_hash"]}})
        component_to_body.update({part:name for part in group})
    if len(bodies) > sparse.MAX_SCENE_BOXES:
        raise ValueError("Assembly exceeds the native box budget")
    native_joints = []
    for joint in joints:
        if joint["kind"] != "bearing": continue
        interface = joint["interface"]
        # A source-space contact must still touch both compiled cell bodies.
        # Otherwise the constraint would act through an invented empty mount.
        pivot = interface["centre_m"]
        for component in (joint["a"], joint["b"]):
            if not any(all(c["grid"][a]*cell_m-1e-9 <= pivot[a] <= (c["grid"][a]+1)*cell_m+1e-9
                           for a in range(3)) for c in rows[group_of[component]]):
                raise ValueError("Bearing mount is absent from the compiled occupied cells")
        native_joints.append({"kind":"hinge","a":component_to_body[joint["a"]],
            "b":component_to_body[joint["b"]],"at_mm":[v*1000 for v in interface["centre_m"]],
            "axis":interface["axis"],"lower_deg":-180.,"upper_deg":180.,"friction_n_m":0.})
    interfaces = joint_efficiency.scene_interfaces(design, prefix=root+"/")
    if len(fracture_lab.standing_interfaces(bodies, interfaces)) != len(interfaces):
        raise ValueError("A fixed interface does not survive native cell compilation")
    native_joints = fracture_lab.normalise_joints(native_joints, bodies)
    physical = {"matter":matter["physics_hash"],"fixed_groups":groups,"joints":joints}
    return {"schema":SCHEMA,"bodies":bodies,"joints":native_joints,"interfaces":interfaces,"source_joints":joints,
            "groups":compiled,"component_to_body":component_to_body,"material_mass_kg":dict(material_mass),
            "mass_kg":sum(material_mass.values()),
            "physics_hash":hashlib.sha256(json.dumps(physical,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest(),
            "limitations":["Ideal native hinges: no bearing strength, wear or friction calibration.",
                           "Funded installation supports single-material assemblies with explicitly bound use and interaction points; whole-assembly bag storage is unsupported."]}
