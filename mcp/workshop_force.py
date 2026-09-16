"""Point-force probes for arbitrary Workshop products.

A click in the 3D view supplies an exact component and product-space point.  A
force pulse supplies direction, force and duration.  This module gives the
cheap evidence that is valid without a time-domain engine run:

* force vector and impulse;
* authored ProductGraph load paths from the hit component to ground supports;
* vertical rigid-support reactions when the pulse has a downward component.

It deliberately does not invent stress, deflection or failure.  Those require a
material/structural engine trial and can be attached as a second evidence layer.
"""
from __future__ import annotations

from collections import deque
from math import isfinite, sqrt
from typing import Any

from mcp import workshop_graph
from mcp.workshop import WorkshopDesign
from mcp.workshop_statics import G_M_S2, _reactions, _supports

FORCE_SCHEMA = "banjo.workshop-force-probe.v1"
TRANSMITS_FORCE = {"fixed", "bearing", "hinge", "slider", "supports", "rope", "pulley", "drum", "spring", "gear", "rack"}


def _finite_vec3(value: Any, name: str) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f"{name} must be three numbers")
    out = [float(v) for v in value]
    if not all(isfinite(v) for v in out):
        raise ValueError(f"{name} must be finite")
    return out


def _unit(value: Any) -> list[float]:
    out = _finite_vec3(value, "direction")
    length = sqrt(sum(v * v for v in out))
    if length <= 1e-12:
        raise ValueError("direction must not be zero")
    return [v / length for v in out]


def _paths(design: WorkshopDesign, start: str) -> list[dict[str, Any]]:
    graph = workshop_graph.product(design)
    standing = set(design.measure().get("standing_on") or [])
    adjacency: dict[str, list[tuple[str, str, str]]] = {c.component_id: [] for c in graph.components}
    for relation in graph.relationships:
        if relation.derived or relation.kind not in TRANSMITS_FORCE:
            continue
        adjacency[relation.a].append((relation.b, relation.relationship_id, relation.kind))
        adjacency[relation.b].append((relation.a, relation.relationship_id, relation.kind))
    if start not in adjacency:
        raise ValueError(f"there is no component {start!r} in this design")

    queue = deque([(start, [start], [])])
    seen_depth: dict[str, int] = {start: 0}
    found: list[dict[str, Any]] = []
    while queue and len(found) < 8:
        node, nodes, edges = queue.popleft()
        if node in standing and node != start:
            found.append({"support": node, "components": nodes, "relationships": edges})
            continue
        if len(nodes) > 20:
            continue
        for other, relation_id, kind in adjacency.get(node, []):
            if other in nodes:
                continue
            depth = len(nodes)
            if seen_depth.get(other, 999) < depth:
                continue
            seen_depth[other] = depth
            queue.append((other, nodes + [other], edges + [{"id": relation_id, "kind": kind}]))
    if start in standing:
        found.insert(0, {"support": start, "components": [start], "relationships": []})
    return found


def probe(design: WorkshopDesign, *, component_name: str, point_m: Any,
          direction: Any, force_n: float, duration_s: float) -> dict[str, Any]:
    design.validate()
    part = next((part for part in design.parts if part.name == component_name), None)
    if part is None:
        raise ValueError(f"there is no component {component_name!r}")
    point = _finite_vec3(point_m, "point_m")
    way = _unit(direction)
    force = float(force_n); duration = float(duration_s)
    if not isfinite(force) or not 0.0 < force <= 100000.0:
        raise ValueError("force_n must be between 0 and 100000")
    if not isfinite(duration) or not 0.001 <= duration <= 10.0:
        raise ValueError("duration_s must be between 0.001 and 10")
    vector = [force * v for v in way]
    impulse = [duration * v for v in vector]

    measured = design.measure()
    downward = max(0.0, -vector[1])
    reactions: list[dict[str, Any]] = []
    limitation = None
    if downward > 1e-9:
        try:
            supports = _supports(design)
            support_points = [(float(row["at_m"][0]), float(row["at_m"][1])) for row in supports]
            own_n = float(measured["mass_kg"]) * G_M_S2
            total_n = own_n + downward
            own_x, _, own_z = [float(v) for v in measured["centre_of_mass_m"]]
            load_x = (own_n * own_x + downward * point[0]) / total_n
            load_z = (own_n * own_z + downward * point[2]) / total_n
            solved = _reactions(support_points, total_n, load_x, load_z)
            reactions = [
                {**support, "reaction_n": round(value, 3)}
                for support, value in zip(supports, solved)
            ]
        except ValueError as problem:
            limitation = str(problem)

    paths = _paths(design, component_name)
    return {
        "schema": FORCE_SCHEMA,
        "evidence": "analytical-estimate",
        "design_id": design.design_id,
        "target": {"component": component_name, "role": part.role,
                   "point_m": [round(v, 6) for v in point]},
        "requested": {"force_n": round(force, 4), "duration_s": round(duration, 6),
                      "direction": [round(v, 6) for v in way]},
        "force_vector_n": [round(v, 4) for v in vector],
        "impulse_n_s": [round(v, 5) for v in impulse],
        "impulse_magnitude_n_s": round(force * duration, 5),
        "downward_force_n": round(downward, 4),
        "load_paths": paths,
        "support_reactions": reactions,
        "acceptance": {
            "status": "not-declared",
            "why": "This probe resolves force transmission and rigid support reactions; it does not invent a stress/deflection/failure limit.",
        },
        "limitations": [item for item in [
            limitation,
            "Dynamic deformation, stress concentration and fracture require a separate engine trial.",
        ] if item],
    }
