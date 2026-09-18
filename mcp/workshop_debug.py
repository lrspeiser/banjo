"""Canonical surfaces and explicitly declared Workshop design-contract views.

These are renderer-neutral views over existing physical/product state. They do
not invent collision, relationships or surfaces in JavaScript:

- CellSkin faces come directly from exposed faces in canonical Matter v2.
- Relationship/collision views come from ProductGraph + PhysicsContract.
"""
from __future__ import annotations

from typing import Any

from mcp import workshop_graph
from mcp.product_contract import compile_contract
from mcp.workshop import WorkshopDesign

CELL_SKIN_SCHEMA = "banjo.workshop-cell-skin.v1"
DEBUG_SCHEMA = "banjo.workshop-physics-debug.v1"

_FACE_AXIS = {
    "+x": (0, True), "-x": (0, False),
    "+y": (1, True), "-y": (1, False),
    "+z": (2, True), "-z": (2, False),
}


def cell_skin_document(matter: dict[str, Any]) -> dict[str, Any]:
    """Blocky CellSkin topology over the exact canonical Matter cells."""
    if not isinstance(matter, dict) or matter.get("schema") != "banjo.workshop-matter.v2":
        raise ValueError("CellSkin needs a banjo.workshop-matter.v2 artifact")
    faces: list[dict[str, Any]] = []
    cell = float(matter.get("cell_size_m") or 0.0)
    if cell <= 0:
        raise ValueError("Matter cell_size_m must be positive")
    for item in matter.get("cells") or []:
        if not isinstance(item, dict):
            continue
        grid = item.get("grid")
        if not isinstance(grid, list) or len(grid) != 3:
            continue
        for name in item.get("exposed_faces") or []:
            if name not in _FACE_AXIS:
                continue
            axis, positive = _FACE_AXIS[name]
            faces.append({
                "grid": [int(v) for v in grid],
                "axis": axis,
                "positive": positive,
                "component": item.get("component"),
                "components": list(item.get("components") or []),
                "material": item.get("material"),
                "fracture": False,
            })
    return {
        "schema": CELL_SKIN_SCHEMA,
        "matter_physics_hash": matter.get("physics_hash"),
        "matter_artifact_hash": matter.get("artifact_hash"),
        "cell_size_m": cell,
        "exposed_faces": len(faces),
        "triangle_count": len(faces) * 2,
        "faces": faces,
        "source": "canonical Matter exposed-face topology",
        "rules": [
            "The surface is render-only and cannot add matter or collision.",
            "Every face belongs to an exposed face of one canonical Matter cell.",
            "Fracture surfaces are added only from accepted failed physical interfaces."
        ],
    }


def debug_document(design: WorkshopDesign) -> dict[str, Any]:
    """ProductGraph relationships and PhysicsContract collision semantics."""
    from mcp.workshop_matter_metrics import has_physical_skin
    if has_physical_skin(design):
        # Physical edits have replaced the wire geometry. A decorative debug
        # view must never reinstate the old wireframe as collision evidence.
        return {"schema": DEBUG_SCHEMA, "status": "unavailable",
                "basis": "unavailable-physical-skin", "strength_certified": False,
                "reason": "Design-contract inspection does not consume physical skin cells. "
                          "Use canonical Matter/CellSkin and a supported exact-Matter test.",
                "components": [], "relationships": [], "collision_zones": [],
                "mechanisms": [], "load_paths": [], "component_to_body": {}, "runtime_bodies": []}
    graph = workshop_graph.product(design)
    product = graph.described()
    contract = compile_contract(graph)
    components = []
    for component in product.get("components") or []:
        geometry = component.get("geometry") or {}
        components.append({
            "id": component.get("id"),
            "role": component.get("role"),
            "family": component.get("family"),
            "material": component.get("material"),
            "center_m": list(geometry.get("center_m") or [0, 0, 0]),
            "size_m": list(geometry.get("size_m") or [0, 0, 0]),
            "rotation_deg": list(geometry.get("rotation_deg") or [0, 0, 0]),
            "shape": geometry.get("shape") or "box",
            "physics_tags": list(component.get("physics_tags") or []),
        })
    return {
        "schema": DEBUG_SCHEMA,
        "product_id": product.get("product_id"),
        "status": "available",
        "basis": "design-contract-not-native-collision",
        "strength_certified": False,
        "components": components,
        "relationships": list(product.get("relationships") or []),
        "collision_zones": list(contract.get("collision_zones") or []),
        "mechanisms": list(contract.get("mechanisms") or []),
        "load_paths": list(contract.get("load_paths") or []),
        "component_to_body": dict(contract.get("component_to_body") or {}),
        "runtime_bodies": list(contract.get("runtime_bodies") or []),
    }
