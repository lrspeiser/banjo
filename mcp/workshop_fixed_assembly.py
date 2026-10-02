"""Reviewed fixed constituents, using occupied cells and finite native fixings.

Cells belong to one material and one body. Shared faces define the available
mount, never a material substitution or a bridge over absent matter. Capacities
use weaker-material strength over sampled area. Filled rectangular mounts
also compile maximum corner normal stress from measured force and moment;
adhesive quality, fatigue, torsion and this abrupt bending law are uncalibrated.
"""
from collections import defaultdict
import hashlib
import json
import math

from . import engine_materials, joint_efficiency, workshop_construction, workshop_visual

SCHEMA = "banjo.workshop-fixed-assembly.v1"
LIMITS = ("Fixed interfaces use catalog weaker-material strength over sampled face area. "
          "Filled rectangular mounts include axial and bending normal stress. "
          "Nonrectangular mounts remain force-only. Abrupt opening is uncalibrated; "
          "adhesive/fastener quality, fracture work, fatigue and torsional failure are unsupported.")


def layout(design, overrides=None, *, cell_m=.04, matter=None):
    """Return a root-independent, paid-reviewable allocation and fixing graph."""
    if type(cell_m) not in (int, float) or not math.isfinite(cell_m) or cell_m <= 0:
        raise ValueError("Fixed assembly needs a positive finite cell size")
    parts = {p.name: p for p in design.parts}
    authored = workshop_construction.of(design).get("joints_authored", False)
    joints = workshop_construction.joints(design)
    if any(j["kind"] != "fixed" or j.get("open") for j in joints):
        raise ValueError("Mixed fixed assembly needs closed fixed connections; bearings need their own adapter")
    matter = matter or workshop_visual.matter_document(design, overrides,
        cell_size_m=cell_m, exterior_only=False)
    rows = defaultdict(list)
    for cell in matter["cells"]:
        owners = cell["components"]
        if len({engine_materials.canonical(parts[n].material) for n in owners}) > 1:
            raise ValueError("Different materials overlap in the sampled grid; move the parts or use a finer grid")
        rows[cell["component"]].append(cell)
    if set(rows) != set(parts):
        raise ValueError("Every fixed constituent needs its own occupied cells")
    if not 0 < len(matter["cells"]) <= 16000:
        raise ValueError("Fixed assembly exceeds the native cell budget")
    grid = {tuple(c["grid"]): c for c in matter["cells"]}
    faces = defaultdict(list)
    for g, cell in grid.items():
        for axis in range(3):
            n = list(g); n[axis] += 1
            other = grid.get(tuple(n))
            if other is None or other["component"] == cell["component"]:
                continue
            pair = tuple(sorted((cell["component"], other["component"])))
            normal = [0., 0., 0.]
            normal[axis] = 1. if cell["component"] == pair[0] else -1.
            centre = [(g[a]+(.5 if a != axis else 1))*cell_m for a in range(3)]
            faces[pair].append((centre, normal))
    declared = {tuple(sorted((j["a"], j["b"]))): j for j in joints}
    if authored and any(pair not in faces for pair in declared):
        raise ValueError("A declared fixing has no shared sampled face; repair its mount before Make")
    connections = []
    graph = defaultdict(set)
    for pair, mount in sorted(faces.items()):
        if authored and pair not in declared:
            continue
        # A single fixing has one normal. A wrap-around mount requires a
        # separate interface model rather than an arbitrary averaged axis.
        if len({tuple(n) for _, n in mount}) != 1:
            raise ValueError("A fixed mount has multiple face directions; declare a planar contact")
        centre, normal = sorted(mount)[len(mount)//2]
        # A filled rectangular patch admits a section law. Its centroid and
        # dimensions come from occupied faces, including each cell's extent;
        # sparse/nonrectangular mounts retain the force-only boundary.
        normal_axis = next(i for i,n in enumerate(normal) if n)
        uv = [i for i in range(3) if i != normal_axis]
        counts = [len({round(c[i]/cell_m,8) for c,_ in mount}) for i in uv]
        lo = [min(c[i] for c,_ in mount) for i in uv]
        hi = [max(c[i] for c,_ in mount) for i in uv]
        rectangular = len({round(c[normal_axis]/cell_m,8) for c,_ in mount})==1 and len(mount)==counts[0]*counts[1] and all(
            math.isclose(hi[k]-lo[k],(counts[k]-1)*cell_m,abs_tol=1e-9) for k in range(2))
        section = {}
        if rectangular:
            centre = [math.fsum(c[i] for c,_ in mount)/len(mount) for i in range(3)]
            u = [float(i==uv[0]) for i in range(3)]
            section = {'section_u':u,'section_u_m':counts[0]*cell_m,'section_v_m':counts[1]*cell_m,
                       'section_law':'rectangular-max-normal-stress-v1'}
        area = len(mount)*cell_m**2
        a, b = (parts[n] for n in pair)
        strengths = [engine_materials.mechanics(p.material) for p in (a, b)]
        keeps = joint_efficiency.efficiency(declared[pair], a, b) if pair in declared else {
            "tension": 1., "shear": 1., "basis": "Implicit fixed sampled contact"}
        tension = min(s["tensile_strength_pa"] for s in strengths)*area*keeps["tension"]
        shear = min(s["shear_strength_pa"] for s in strengths)*area*keeps["shear"]
        if not all(math.isfinite(v) and 0 < v <= 1e9 for v in (tension, shear)):
            raise ValueError("Fixed mount needs positive finite catalog capacities within native limits")
        connections.append({"components": list(pair), "at_m": centre, "axis": normal,
            "area_m2": area, "holds_tension_n": tension, "holds_shear_n": shear,
            "basis": keeps, **section,
            "source": "authored fixed contact" if authored else "implicit fixed sampled contact"})
        graph[pair[0]].add(pair[1]); graph[pair[1]].add(pair[0])
    seen, pending = set(), [next(iter(parts))]
    while pending:
        name = pending.pop()
        if name in seen: continue
        seen.add(name); pending.extend(graph[name]-seen)
    if seen != set(parts):
        raise ValueError("Every constituent must be connected by supported fixed mounts")
    groups, mass = [], defaultdict(float)
    for name, cells in sorted(rows.items()):
        occupied = {tuple(c["grid"]) for c in cells}
        reached, pending = set(), [next(iter(occupied))]
        while pending:
            g = pending.pop()
            if g in reached: continue
            reached.add(g)
            for axis in range(3):
                for sign in (-1, 1):
                    n = list(g); n[axis] += sign; n = tuple(n)
                    if n in occupied and n not in reached: pending.append(n)
        if reached != occupied:
            raise ValueError("A fixed constituent has disconnected sampled cells")
        materials = {engine_materials.canonical(c["material"]) for c in cells}
        if len(materials) != 1:
            raise ValueError("A native constituent must retain exactly one material")
        material = materials.pop()
        kg = len(cells)*cell_m**3*engine_materials.density(material)
        mass[material] += kg
        groups.append({"component": name, "material": material, "mass_kg": kg,
            "matter": {"cell_size_m": cell_m, "cells": cells, "total_cells": len(cells)}})
    physical = {"matter": matter["physics_hash"], "connections": connections,
                "allocation": dict(mass), "adapter": SCHEMA}
    return {"schema": SCHEMA, "groups": groups, "connections": connections,
        "material_mass_kg": dict(mass), "mass_kg": math.fsum(mass.values()),
        "physics_hash": hashlib.sha256(json.dumps(physical, sort_keys=True,
            separators=(",", ":"), allow_nan=False).encode()).hexdigest(), "limitations": [LIMITS]}
