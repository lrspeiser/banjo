"""Compile a detailed ProductGraph into a behavior-preserving runtime contract.

The contract is deliberately product-agnostic.  It reduces declared rigidly
fixed components, never mere contacts; preserves mechanism degrees of freedom;
and records what is approximated, validated and worth refining when a live
interaction gets close to failure or leaves the tested envelope.
"""
from __future__ import annotations

from math import isfinite, pi
from typing import Any

from mcp.product_graph import PRODUCT_SCHEMA, ProductGraph

CONTRACT_SCHEMA = "banjo.physics-contract.v1"
MECHANISM_KINDS = {"hinge", "slider", "bearing", "rope", "pulley", "drum", "spring", "gear", "rack"}
LOAD_RELATIONS = {"fixed", "physical-contact", "supports", "hinge", "slider", "bearing", "rope", "pulley", "drum", "spring"}


class _UnionFind:
    def __init__(self, values: list[str]) -> None:
        self.parent = {value: value for value in values}

    def find(self, value: str) -> str:
        root = value
        while self.parent[root] != root: root = self.parent[root]
        while self.parent[value] != value:
            nxt = self.parent[value]; self.parent[value] = root; value = nxt
        return root

    def union(self, a: str, b: str) -> None:
        a, b = self.find(a), self.find(b)
        if a != b: self.parent[b] = a


def _doc(graph: ProductGraph | dict[str, Any]) -> dict[str, Any]:
    if isinstance(graph, ProductGraph):
        return graph.described()
    if not isinstance(graph, dict) or graph.get("schema") != PRODUCT_SCHEMA:
        raise ValueError("PhysicsContract needs a banjo.product-graph.v1 document")
    return graph


def _geometry(component: dict[str, Any]) -> dict[str, Any]:
    geometry = component.get("geometry") or {}
    if not isinstance(geometry, dict): raise ValueError("component geometry must be an object")
    return geometry


def _mass(component: dict[str, Any]) -> float:
    value = float(_geometry(component).get("mass_kg", 0.0))
    if not isfinite(value) or value < 0: raise ValueError(f"{component.get('id')}: invalid mass")
    return value


def _center(component: dict[str, Any]) -> list[float]:
    value = _geometry(component).get("center_m") or [0.0, 0.0, 0.0]
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f"{component.get('id')}: center_m needs three numbers")
    return [float(v) for v in value]


def _local_inertia(component: dict[str, Any]) -> list[float]:
    """Principal inertia of the component's occupied primitive, before rotation.

    Runtime compilation keeps the detailed source as provenance.  This first
    contract carries a conservative primitive mass model; the asset compiler can
    replace it with exact compiled mass properties without changing the schema.
    """
    geometry = _geometry(component); mass = _mass(component)
    size = geometry.get("size_m") or [0.0, 0.0, 0.0]
    if not isinstance(size, (list, tuple)) or len(size) != 3:
        return [0.0, 0.0, 0.0]
    x, y, z = (max(0.0, float(v)) for v in size)
    if geometry.get("shape") == "cylinder":
        # Workshop cylinders use local +y as their axis.
        radius = max(x, z) / 2.0
        return [mass * (3 * radius * radius + y * y) / 12.0,
                0.5 * mass * radius * radius,
                mass * (3 * radius * radius + y * y) / 12.0]
    return [mass * (y * y + z * z) / 12.0,
            mass * (x * x + z * z) / 12.0,
            mass * (x * x + y * y) / 12.0]


def _aggregate(components: list[dict[str, Any]], body_id: str) -> dict[str, Any]:
    mass = sum(_mass(component) for component in components)
    if mass > 0:
        center = [sum(_center(c)[axis] * _mass(c) for c in components) / mass for axis in range(3)]
    else:
        center = [sum(_center(c)[axis] for c in components) / len(components) for axis in range(3)]
    inertia = [0.0, 0.0, 0.0]
    for component in components:
        m = _mass(component); c = _center(component); local = _local_inertia(component)
        dx, dy, dz = c[0] - center[0], c[1] - center[1], c[2] - center[2]
        inertia[0] += local[0] + m * (dy * dy + dz * dz)
        inertia[1] += local[1] + m * (dx * dx + dz * dz)
        inertia[2] += local[2] + m * (dx * dx + dy * dy)
    return {
        "id": body_id,
        "components": sorted(str(component["id"]) for component in components),
        "mass_kg": round(mass, 6),
        "centre_of_mass_m": [round(v, 6) for v in center],
        "inertia_principal_kg_m2": [round(v, 8) for v in inertia],
        "mass_properties": "component primitives + parallel-axis; source geometry retained for refinement",
    }


def _collision_kind(component: dict[str, Any]) -> str | None:
    tags = set(component.get("physics_tags") or [])
    if "visual_only" in tags: return None
    if "blade" in tags or "cutter" in tags: return "blade"
    if "rotor" in tags or "rolling_contact" in tags: return "rotor"
    if "shaft" in tags: return "shaft"
    if "plate" in tags or "structural_surface" in tags: return "plate"
    if "beam" in tags or "structural_member" in tags: return "beam"
    if "collision_surface" in tags or "collision_member" in tags or "rigid_component" in tags:
        return "rigid-proxy"
    return None


def _failure_modes(component: dict[str, Any]) -> list[str]:
    tags = set(component.get("physics_tags") or [])
    modes = []
    if "plate" in tags or "structural_surface" in tags: modes += ["plate_bending", "local_punch_or_shear"]
    if "beam" in tags or "structural_member" in tags: modes += ["member_bending", "member_buckling_or_shear"]
    if "shaft" in tags: modes += ["shaft_bending", "shaft_torsion"]
    if "rotor" in tags: modes += ["bearing_or_hub_load", "rotor_overspeed"]
    if "blade" in tags or "cutter" in tags: modes += ["edge_or_mount_overload"]
    return sorted(set(modes))


def _validated_ranges(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranges = []
    for record in evidence:
        if not isinstance(record, dict): continue
        if isinstance(record.get("validated_range"), dict):
            ranges.append({"source": record.get("id") or record.get("test") or "evidence",
                           "range": record["validated_range"]})
    return ranges


def compile_contract(graph: ProductGraph | dict[str, Any], *,
                     performance_budget: dict[str, Any] | None = None) -> dict[str, Any]:
    """Reduce a product without inventing behavior that its graph did not declare."""
    document = _doc(graph)
    components = document.get("components") or []
    relationships = document.get("relationships") or []
    if not isinstance(components, list) or not components:
        raise ValueError("ProductGraph has no components")
    by_id = {str(c["id"]): c for c in components}
    if len(by_id) != len(components): raise ValueError("component ids must be unique")

    # Only a declared rigid/fixed relation permits collapse. Geometry contact is
    # a load/collision relation, not permission to erase a degree of freedom.
    groups = _UnionFind(list(by_id))
    for relation in relationships:
        if relation.get("kind") == "fixed": groups.union(str(relation["a"]), str(relation["b"]))
    clustered: dict[str, list[dict[str, Any]]] = {}
    for component_id, component in by_id.items():
        clustered.setdefault(groups.find(component_id), []).append(component)
    runtime_bodies = [_aggregate(items, f"body-{index + 1}")
                      for index, items in enumerate(clustered.values())]
    component_to_body = {component_id: body["id"] for body in runtime_bodies
                         for component_id in body["components"]}

    mechanisms = []
    for relation in relationships:
        if relation.get("kind") not in MECHANISM_KINDS: continue
        mechanisms.append({
            "id": relation.get("id"), "kind": relation.get("kind"),
            "a_body": component_to_body[str(relation["a"])],
            "b_body": component_to_body[str(relation["b"])],
            "a_component": relation.get("a"), "b_component": relation.get("b"),
            "properties": dict(relation.get("properties") or {}),
            "dof_preserved": True,
        })

    zones = []
    failures = []
    for component in components:
        kind = _collision_kind(component)
        if kind is not None:
            zones.append({
                "id": f"collision-{component['id']}", "kind": kind,
                "component": component["id"], "runtime_body": component_to_body[str(component["id"])],
                "geometry": _geometry(component),
                "response": "semantic reduced response; refine locally near failure/outside evidence",
            })
        for mode in _failure_modes(component):
            failures.append({"component": component["id"], "mode": mode,
                             "threshold": "from material/evidence at runtime; not invented by compiler"})

    load_paths = []
    reduction_candidates = []
    for relation in relationships:
        kind = str(relation.get("kind"))
        if kind in LOAD_RELATIONS:
            load_paths.append({"kind": kind, "a": relation.get("a"), "b": relation.get("b"),
                               "declared": not bool(relation.get("derived"))})
        if kind == "physical-contact":
            reduction_candidates.append({"components": [relation.get("a"), relation.get("b")],
                                         "candidate": "possible rigid reduction",
                                         "requires_validation": True,
                                         "why": "contact alone does not prove the parts move together"})

    total = _aggregate(components, "whole-product")
    budget = dict(performance_budget or {})
    validated = _validated_ranges(document.get("evidence") or [])
    physics_tags = document.get("physics_tags") or {}
    thermal = bool(set(physics_tags.get("physics") or []) & {"thermal", "heater", "heat_transfer", "container"})
    fluid = bool(document.get("contents"))
    return {
        "schema": CONTRACT_SCHEMA,
        "product_id": document.get("product_id"),
        "source_schema": document.get("schema"),
        "source_purpose": document.get("purpose"),
        "conserved": {
            "mass_kg": total["mass_kg"],
            "centre_of_mass_m": total["centre_of_mass_m"],
            "inertia_principal_kg_m2": total["inertia_principal_kg_m2"],
            "mass_properties": total["mass_properties"],
        },
        "runtime_bodies": runtime_bodies,
        "component_to_body": component_to_body,
        "collision_zones": zones,
        "mechanisms": mechanisms,
        "load_paths": load_paths,
        "failure_modes": failures,
        "energy": list(document.get("energy") or []),
        "controls": list(document.get("controls") or []),
        "contents": list(document.get("contents") or []),
        "validated_ranges": validated,
        "reduction_candidates": reduction_candidates,
        "fidelity": {
            "visual": "source-detail retained outside runtime physics",
            "collision": "semantic proxies by component physics role",
            "rigid_motion": "declared mechanism DOFs preserved",
            "mass_properties": "conserved from component primitives",
            "structural": "reduced load-path model with adaptive local refinement",
            "fracture": "adaptive fine simulation near failure or on demand",
            "thermal": "reduced semantic model" if thermal else "not required by current graph",
            "fluids": "contents semantics; free-fluid mechanics requires a supported model" if fluid else "not required",
        },
        "refinement_triggers": [
            "interaction leaves a validated test range",
            "a reduced structural or attachment failure mode approaches its threshold",
            "collision energy/local stress cannot be represented by the current semantic zone",
            "temperature leaves the validated material/evidence range",
            "a requested degree of freedom or contents behavior is unsupported by the reduced model",
            "the user explicitly asks for high-fidelity inspection",
        ],
        "performance_budget": budget,
        "compiler_guarantees": [
            "Only declared fixed relationships are collapsed into one runtime body.",
            "Geometry-derived contact never silently removes a degree of freedom.",
            "Mechanism relationships remain explicit runtime constraints.",
            "No numeric failure threshold is invented without material law or evidence.",
            "Detailed source component ids survive every reduction for local refinement.",
        ],
    }
