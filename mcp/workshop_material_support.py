"""Read-only admission of constituent materials in fixed lattice groups.

Mixed fixed products use separate material bodies and reviewed native fixings.
Preserve a draft when its sampled mounts cannot be represented.
"""
from . import engine_materials, workshop_construction, workshop_machines, workshop_rigid


def fixed_lattice_blocker(design, overrides=None, *, cell_m=.04):
    if workshop_rigid.requested_models(design, overrides) != {"lattice"}:
        return None
    parts = {p.name: p for p in design.parts}
    parent = {name: name for name in parts}

    def find(name):
        while parent[name] != name:
            name = parent[name]
        return name

    joints = workshop_construction.joints(design)
    # Non-articulated solids are compiled as one body, even without an authored
    # joint graph (for example, a ground tool joined by occupied matter).
    if not any(j["kind"] == "bearing" for j in joints) and not workshop_machines.of(design):
        groups = [list(parts)]
    else:
        for joint in joints:
            if joint["kind"] == "fixed" and joint["a"] in parts and joint["b"] in parts:
                parent[find(joint["b"])] = find(joint["a"])
        groups_by_root = {}
        for name in parts:
            groups_by_root.setdefault(find(name), []).append(name)
        groups = list(groups_by_root.values())
    blocked = []
    for members in groups:
        materials = {name: engine_materials.canonical(parts[name].material) for name in members}
        if len(set(materials.values())) > 1:
            blocked.append({"components": sorted(members), "materials": materials})
    if not blocked:
        return None
    if not any(j["kind"] == "bearing" for j in joints) and not workshop_machines.of(design):
        from . import workshop_fixed_assembly
        try:
            workshop_fixed_assembly.layout(design, overrides, cell_m=cell_m)
            return None
        except ValueError as error:
            reason = str(error)
    else:
        reason = "Mixed fixed groups within articulated machines need their own native adapter"
    first = blocked[0]
    names = ", ".join(f"{name} ({first['materials'][name]})" for name in first["components"])
    return {"code": "mixed_lattice_interface_unsupported", "groups": blocked,
            "can_save_design": True,
            "message": f"Cannot make {names}: {reason}. You can save the design."}
