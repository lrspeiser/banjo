"""Adapt authoritative Workshop geometry into the generic ProductGraph.

Workshop still owns geometry. This module assigns reusable physics semantics,
interfaces and conservative measured contacts to that geometry. A contact is
not a fixing: mechanisms such as wheels and axles often touch specifically so
they can move relative to one another.
"""
from __future__ import annotations

from math import sqrt
from typing import Any

from mcp.workshop import WorkshopDesign, WirePart, _rotate
from mcp.product_graph import ProductGraph, ProductComponent, component, interface, relationship

STRUT_ROLES = {"leg", "post", "beam", "brace", "apron", "stretcher", "axle", "handle"}

ROLE_TAGS: dict[str, tuple[str, ...]] = {
    "leg": ("structural_member", "beam", "load_path", "collision_member"),
    "post": ("structural_member", "beam", "load_path", "collision_member"),
    "beam": ("structural_member", "beam", "load_path", "collision_member"),
    "brace": ("structural_member", "beam", "load_path", "collision_member"),
    "apron": ("structural_member", "beam", "load_path"),
    "stretcher": ("structural_member", "beam", "load_path"),
    "top": ("structural_surface", "plate", "support_surface", "collision_surface", "load_path"),
    "surface": ("structural_surface", "plate", "support_surface", "collision_surface", "load_path"),
    "panel": ("structural_surface", "plate", "collision_surface", "load_path"),
    "axle": ("shaft", "rotational_member", "load_path", "collision_member"),
    "wheel": ("rotor", "rolling_contact", "collision_surface"),
    "handle": ("manual_input", "load_input", "collision_member"),
}

ROLE_CAPABILITIES: dict[str, tuple[str, ...]] = {
    "wheel": ("rotates", "rolls"),
    "axle": ("supports_rotation",),
    "handle": ("human_input",),
    "top": ("supports_load",),
    "surface": ("supports_load",),
}


def _local_interfaces(part: WirePart):
    """Reusable ports in the component's own canonical frame.

    A library component must not carry the table/cart coordinates it happened to
    come from.  Canonical component-local +y is the member/cylinder axis.  A
    ProductGraph placement rotates/translates these ports into product space.
    """
    w, h, d = part.size_m
    ports = []
    for name, local, normal in (
        ("face-x-", (-w / 2, 0, 0), (-1, 0, 0)),
        ("face-x+", ( w / 2, 0, 0), ( 1, 0, 0)),
        ("face-y-", (0, -h / 2, 0), (0, -1, 0)),
        ("face-y+", (0,  h / 2, 0), (0,  1, 0)),
        ("face-z-", (0, 0, -d / 2), (0, 0, -1)),
        ("face-z+", (0, 0,  d / 2), (0, 0,  1)),
    ):
        ports.append(interface(name, "surface", point_m=local, normal=normal,
                               tags=("mate", "contact")))
    if part.role in STRUT_ROLES or part.shape == "cylinder":
        end_kind = "shaft" if part.role == "axle" else "end"
        ports += [
            interface("end-a", end_kind, point_m=(0, -h / 2, 0), axis=(0, 1, 0), tags=("mate",)),
            interface("end-b", end_kind, point_m=(0,  h / 2, 0), axis=(0, 1, 0), tags=("mate",)),
        ]
        if part.role == "axle":
            ports.append(interface("shaft-middle", "shaft", point_m=(0, 0, 0),
                                   axis=(0, 1, 0), tags=("rotation", "mate")))
    if part.role == "wheel":
        ports.append(interface("hub", "shaft", point_m=(0, 0, 0), axis=(0, 1, 0),
                               tags=("rotation", "mate")))
    return tuple(ports)


def template_component(part: WirePart, *, component_id: str | None = None) -> ProductComponent:
    """One reusable component at the origin, independent of its source assembly."""
    return component(
        component_id or part.name, part.role, family=part.family, material=part.material,
        geometry={"shape": part.shape, "size_m": [float(v) for v in part.size_m],
                  "center_m": [0.0, 0.0, 0.0], "rotation_deg": [0.0, 0.0, 0.0],
                  "mass_kg": float(part.mass_kg()), "source": "workshop-component-template"},
        interfaces=_local_interfaces(part),
        physics_tags=ROLE_TAGS.get(part.role, ("rigid_component", "collision_surface")),
        capabilities=ROLE_CAPABILITIES.get(part.role, ()))


def _interfaces(part: WirePart):
    """Canonical local ports placed into the candidate's product coordinates."""
    local = template_component(part)
    cx, cy, cz = part.center_m
    ports = []
    for port in local.interfaces:
        point = port.point_m
        placed = None
        if point is not None:
            offset = _rotate(part.rotation_deg, point)
            placed = (cx + offset[0], cy + offset[1], cz + offset[2])
        axis = _rotate(part.rotation_deg, port.axis) if port.axis is not None else None
        normal = _rotate(part.rotation_deg, port.normal) if port.normal is not None else None
        ports.append(interface(port.interface_id, port.kind, point_m=placed,
                               axis=axis, normal=normal, tags=port.tags,
                               properties=port.properties))
    return tuple(ports)


def _aabb(part: WirePart) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    corners = part.corners_m()
    return (tuple(min(p[i] for p in corners) for i in range(3)),
            tuple(max(p[i] for p in corners) for i in range(3)))


def _box_gap(a: WirePart, b: WirePart) -> float:
    alo, ahi = _aabb(a); blo, bhi = _aabb(b)
    gaps = []
    for i in range(3):
        if ahi[i] < blo[i]: gaps.append(blo[i] - ahi[i])
        elif bhi[i] < alo[i]: gaps.append(alo[i] - bhi[i])
        else: gaps.append(0.0)
    return sqrt(sum(g * g for g in gaps))


def product(design: WorkshopDesign, *, contact_tolerance_m: float = 0.003) -> ProductGraph:
    """Convert one Workshop candidate into a generic physical product graph."""
    design.validate()
    components = []
    for part in design.parts:
        template = template_component(part)
        geometry = dict(template.geometry)
        geometry.update({"center_m": [float(v) for v in part.center_m],
                         "rotation_deg": [float(v) for v in part.rotation_deg],
                         "source": "workshop-wireframe"})
        components.append(component(
            part.name, part.role, family=part.family, material=part.material,
            geometry=geometry, interfaces=_interfaces(part),
            physics_tags=template.physics_tags, capabilities=template.capabilities))

    relationships = []
    serial = 0
    for i, left in enumerate(design.parts):
        for right in design.parts[i + 1:]:
            gap = _box_gap(left, right)
            if gap <= contact_tolerance_m:
                serial += 1
                relationships.append(relationship(
                    f"contact-{serial}", "physical-contact", left.name, right.name,
                    properties={"gap_m": round(gap, 6), "source": "geometry"}, derived=True))

    return ProductGraph(
        product_id=design.design_id,
        purpose=design.purpose,
        components=components,
        relationships=relationships,
        tests=list(design.tests),
        metadata={"source": "workshop", "kind": design.kind,
                  "parameters": dict(design.parameters),
                  "contact_tolerance_m": contact_tolerance_m},
    ).validate()


def graph(design: WorkshopDesign, *, contact_tolerance_m: float = 0.003) -> dict[str, Any]:
    """JSON form; ``nodes`` is kept as a compatibility alias for the first UI/tests."""
    doc = product(design, contact_tolerance_m=contact_tolerance_m).described()
    doc["design_id"] = design.design_id
    doc["nodes"] = doc["components"]
    doc["contact_tolerance_m"] = contact_tolerance_m
    doc["note"] = ("Physical contacts are measured, not assumed fixed; explicit mates/joints "
                   "can refine the same graph.")
    for node in doc["nodes"]:
        for port in node.get("interfaces") or []:
            port["name"] = port["id"]
    for relation_doc in doc["relationships"]:
        if relation_doc["kind"] == "physical-contact":
            relation_doc["gap_m"] = relation_doc.get("properties", {}).get("gap_m", 0.0)
    return doc


def contacts_of(graph_doc: dict[str, Any], part_name: str) -> list[str]:
    out = []
    for relation_doc in graph_doc.get("relationships") or []:
        if relation_doc.get("kind") != "physical-contact": continue
        if relation_doc.get("a") == part_name: out.append(str(relation_doc.get("b")))
        elif relation_doc.get("b") == part_name: out.append(str(relation_doc.get("a")))
    return sorted(set(out))
