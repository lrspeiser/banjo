"""Adapt authoritative Workshop geometry into the generic ProductGraph.

Workshop owns geometry. This adapter adds reusable physics semantics,
interfaces, authored structural connections and conservative measured contacts.
The rules are component/relationship based rather than product-name based:
bearing mounts imply rotational support, matched wheel hubs can couple to an
axle, and containment surfaces define a liquid volume and thermal path.
"""
from __future__ import annotations

from math import sqrt
from typing import Any

from mcp.workshop import WorkshopDesign, WirePart, _axis_of, _rotate
from mcp.product_graph import ProductGraph, ProductComponent, component, interface, relationship

STRUT_ROLES = {"leg", "post", "beam", "brace", "apron", "stretcher", "axle", "handle", "bearing_mount"}
FIXED_STRUCTURE_ROLES = {
    "leg", "post", "beam", "brace", "apron", "stretcher", "top", "panel", "handle",
    "bearing_mount", "container_bottom", "container_wall",
}

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
    "bearing_mount": ("structural_member", "bearing_support", "load_path", "collision_member"),
    "container_bottom": ("container", "containment_surface", "thermal_surface", "plate", "collision_surface", "load_path"),
    "container_wall": ("container", "containment_surface", "plate", "collision_surface", "load_path"),
    "handle": ("manual_input", "load_input", "collision_member"),
}

ROLE_CAPABILITIES: dict[str, tuple[str, ...]] = {
    "wheel": ("rotates", "rolls"),
    "axle": ("supports_rotation", "rotates"),
    "bearing_mount": ("supports_rotation", "bearing"),
    "handle": ("human_input",),
    "top": ("supports_load",),
    "surface": ("supports_load",),
    "container_bottom": ("holds_contents", "heat_transfer"),
    "container_wall": ("holds_contents",),
}


def _local_interfaces(part: WirePart):
    """Reusable ports in the component's own canonical frame."""
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
    if part.role in {"container_bottom", "container_wall"}:
        ports.append(interface("contents", "contents", point_m=(0, 0, 0),
                               tags=("container", "fluid")))
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


def _distance(a, b) -> float:
    return sqrt(sum((float(a[i]) - float(b[i])) ** 2 for i in range(3)))


def _parallel(a, b) -> bool:
    dot = abs(sum(float(a[i]) * float(b[i]) for i in range(3)))
    return dot >= 0.98


def _container_semantics(design: WorkshopDesign) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    bottoms = [part for part in design.parts if part.role == "container_bottom"]
    walls = [part for part in design.parts if part.role == "container_wall"]
    if len(bottoms) != 1 or len(walls) < 4:
        return [], []
    bottom = bottoms[0]
    x_walls = sorted((p for p in walls if p.size_m[0] <= p.size_m[2]), key=lambda p: p.center_m[0])
    z_walls = sorted((p for p in walls if p.size_m[2] < p.size_m[0]), key=lambda p: p.center_m[2])
    if len(x_walls) < 2 or len(z_walls) < 2:
        return [], []
    left, right = x_walls[0], x_walls[-1]
    front, back = z_walls[0], z_walls[-1]
    inner_x = (right.center_m[0] - right.size_m[0] / 2) - (left.center_m[0] + left.size_m[0] / 2)
    inner_z = (back.center_m[2] - back.size_m[2] / 2) - (front.center_m[2] + front.size_m[2] / 2)
    floor_y = bottom.center_m[1] + bottom.size_m[1] / 2
    rim_y = min(p.center_m[1] + p.size_m[1] / 2 for p in walls)
    height = rim_y - floor_y
    capacity_m3 = max(0.0, inner_x) * max(0.0, inner_z) * max(0.0, height)
    if capacity_m3 <= 0:
        return [], []
    substances = sorted({str(test.get("substance")) for test in design.tests if test.get("substance")})
    contents = [{
        "id": "primary-contents", "kind": "liquid-volume",
        "container_components": [bottom.name] + [p.name for p in walls],
        "capacity_m3": round(capacity_m3, 8), "capacity_l": round(capacity_m3 * 1000, 4),
        "accepted_substances": substances or ["liquid"],
        "fill_state": "empty-until-filled-by-test-or-world",
    }]
    energy = [{
        "kind": "thermal_path", "from": "external-heat",
        "through_component": bottom.name, "to_contents": "primary-contents",
        "mode": "conduction", "evidence_required_for_runtime_reduction": True,
    }]
    return contents, energy


def product(design: WorkshopDesign, *, contact_tolerance_m: float = 0.003) -> ProductGraph:
    """Convert one Workshop candidate into a generic physical product graph."""
    design.validate()
    components = []
    by_name = {part.name: part for part in design.parts}
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
    contact_pairs: list[tuple[WirePart, WirePart, float]] = []
    serial = 0
    for i, left in enumerate(design.parts):
        for right in design.parts[i + 1:]:
            gap = _box_gap(left, right)
            if gap <= contact_tolerance_m:
                serial += 1
                contact_pairs.append((left, right, gap))
                relationships.append(relationship(
                    f"contact-{serial}", "physical-contact", left.name, right.name,
                    properties={"gap_m": round(gap, 6), "source": "geometry"}, derived=True))

    declared = 0
    existing = set()
    def add(kind: str, a: WirePart, b: WirePart, *, properties: dict[str, Any] | None = None,
            a_interface: str | None = None, b_interface: str | None = None) -> None:
        nonlocal declared
        key = (kind, *sorted((a.name, b.name)))
        if key in existing:
            return
        existing.add(key); declared += 1
        relationships.append(relationship(
            f"authored-{kind}-{declared}", kind, a.name, b.name,
            a_interface=a_interface, b_interface=b_interface,
            properties={"source": "workshop-authored-semantics", **(properties or {})}, derived=False))

    # Authored structural members that touch are fastened, not merely resting
    # next to one another. Mechanism roles are excluded and connected below.
    for left, right, gap in contact_pairs:
        if left.role in FIXED_STRUCTURE_ROLES and right.role in FIXED_STRUCTURE_ROLES:
            add("fixed", left, right, properties={"gap_m": round(gap, 6)})

    axles = [p for p in design.parts if p.role == "axle"]
    mounts = [p for p in design.parts if p.role == "bearing_mount"]
    wheels = [p for p in design.parts if p.role == "wheel"]
    mounted_axles: set[str] = set()
    for axle in axles:
        axis = _axis_of(axle.rotation_deg)
        for mount in mounts:
            if _box_gap(axle, mount) <= max(contact_tolerance_m, 0.006):
                add("bearing", mount, axle,
                    properties={"axis": [round(float(v), 6) for v in axis],
                                "friction_model": "bearing"})
                mounted_axles.add(axle.name)

    for wheel in wheels:
        wheel_axis = _axis_of(wheel.rotation_deg)
        best = None
        for axle in axles:
            axis = _axis_of(axle.rotation_deg)
            if not _parallel(wheel_axis, axis):
                continue
            ends = axle.ends_m()
            distance = min(_distance(wheel.center_m, ends[0]), _distance(wheel.center_m, ends[1]))
            if best is None or distance < best[0]:
                best = (distance, axle)
        if best and best[0] <= max(0.012, contact_tolerance_m * 4):
            axle = best[1]
            if axle.name in mounted_axles:
                add("fixed", axle, wheel,
                    properties={"coupling": "wheel fixed to rotating axle"})
            else:
                add("bearing", axle, wheel,
                    properties={"axis": [round(float(v), 6) for v in _axis_of(axle.rotation_deg)],
                                "coupling": "wheel rotates on stationary axle"})

    contents, energy = _container_semantics(design)
    return ProductGraph(
        product_id=design.design_id,
        purpose=design.purpose,
        components=components,
        relationships=relationships,
        contents=contents,
        energy=energy,
        tests=list(design.tests),
        metadata={"source": "workshop", "kind": design.kind,
                  "parameters": dict(design.parameters),
                  "contact_tolerance_m": contact_tolerance_m},
    ).validate()


def graph(design: WorkshopDesign, *, contact_tolerance_m: float = 0.003) -> dict[str, Any]:
    """JSON form; ``nodes`` remains a compatibility alias for early UI/tests."""
    doc = product(design, contact_tolerance_m=contact_tolerance_m).described()
    doc["design_id"] = design.design_id
    doc["nodes"] = doc["components"]
    doc["contact_tolerance_m"] = contact_tolerance_m
    doc["note"] = ("Geometry contacts remain visible evidence; authored fixed/bearing relationships "
                   "state which contacts actually constrain motion.")
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
