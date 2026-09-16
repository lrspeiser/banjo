"""Deterministic interface-to-interface mating for arbitrary ProductGraphs.

The model/user chooses *which* interfaces should meet and what physical
relationship they mean.  This module solves the rigid transform.  It does not
ask a language model for coordinates.

The first operation moves one unconnected component.  Moving an already-linked
subassembly will be added as a graph transform once component groups are first-
class; silently tearing existing relationships apart is refused now.
"""
from __future__ import annotations

from copy import deepcopy
from math import acos, isfinite, sqrt
from typing import Any

from mcp.product_graph import (ProductComponent, ProductGraph, ProductInterface,
                               RELATION_KINDS, relationship)


def _v(value: Any, name: str) -> tuple[float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f"{name} needs three numbers")
    out = tuple(float(x) for x in value)
    if not all(isfinite(x) for x in out):
        raise ValueError(f"{name} needs finite numbers")
    return out  # type: ignore[return-value]


def _add(a, b): return (a[0] + b[0], a[1] + b[1], a[2] + b[2])
def _sub(a, b): return (a[0] - b[0], a[1] - b[1], a[2] - b[2])
def _scale(a, s): return (a[0] * s, a[1] * s, a[2] * s)
def _dot(a, b): return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
def _cross(a, b): return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])
def _norm(a): return sqrt(_dot(a, a))


def _unit(a, name="direction"):
    n = _norm(a)
    if n <= 1e-12: raise ValueError(f"{name} must not be zero")
    return _scale(a, 1.0 / n)


def _quat_normalize(q):
    n = sqrt(sum(float(x) * float(x) for x in q))
    if n <= 1e-12: return (1.0, 0.0, 0.0, 0.0)
    return tuple(float(x) / n for x in q)


def _quat_between(source, target):
    """Shortest wxyz rotation taking one unit direction onto another."""
    a, b = _unit(source), _unit(target)
    d = max(-1.0, min(1.0, _dot(a, b)))
    if d > 1.0 - 1e-12: return (1.0, 0.0, 0.0, 0.0)
    if d < -1.0 + 1e-12:
        # Choose a deterministic perpendicular axis.
        helper = (1.0, 0.0, 0.0) if abs(a[0]) < 0.8 else (0.0, 1.0, 0.0)
        axis = _unit(_cross(a, helper))
        return (0.0, axis[0], axis[1], axis[2])
    axis = _cross(a, b)
    return _quat_normalize((1.0 + d, axis[0], axis[1], axis[2]))


def rotate(q, point):
    """Rotate a vector by a wxyz unit quaternion."""
    w, x, y, z = _quat_normalize(q)
    px, py, pz = point
    # q * p * q^-1, expanded.
    tx, ty, tz = 2 * (y*pz - z*py), 2 * (z*px - x*pz), 2 * (x*py - y*px)
    return (px + w*tx + (y*tz - z*ty),
            py + w*ty + (z*tx - x*tz),
            pz + w*tz + (x*ty - y*tx))


def transform_point(transform: dict[str, Any], point) -> tuple[float, float, float]:
    q = tuple(transform["rotation_wxyz"]); t = tuple(transform["translation_m"])
    return _add(rotate(q, point), t)


def _interface(value: ProductInterface | dict[str, Any]) -> dict[str, Any]:
    if isinstance(value, ProductInterface): return value.described()
    if not isinstance(value, dict): raise ValueError("interface must be an object")
    return value


def _direction(port: dict[str, Any]):
    if port.get("axis") is not None: return _v(port["axis"], "interface axis"), "axis"
    if port.get("normal") is not None: return _v(port["normal"], "interface normal"), "normal"
    return None, None


def compatible(source: ProductInterface | dict[str, Any], target: ProductInterface | dict[str, Any]) -> bool:
    a, b = _interface(source), _interface(target)
    ka, kb = str(a.get("kind")), str(b.get("kind"))
    if ka == kb: return True
    # A generic strut end may mate to a surface; shafts require shaft semantics.
    return {ka, kb} == {"end", "surface"}


def solve_mate(source: ProductInterface | dict[str, Any], target: ProductInterface | dict[str, Any]) -> dict[str, Any]:
    """Rigid transform that puts source port on target port with compatible facing."""
    a, b = _interface(source), _interface(target)
    if not compatible(a, b):
        raise ValueError(f"cannot mate {a.get('kind')} to {b.get('kind')}")
    if a.get("point_m") is None or b.get("point_m") is None:
        raise ValueError("mating interfaces need points")
    ap, bp = _v(a["point_m"], "source point"), _v(b["point_m"], "target point")
    ad, ak = _direction(a); bd, bk = _direction(b)
    q = (1.0, 0.0, 0.0, 0.0)
    rule = "points-only"
    if ad is not None and bd is not None:
        # Surface normals oppose; shaft/axis directions align. Shaft sign is
        # physically equivalent, so choose the nearer of +axis and -axis.
        desired = bd
        if ak == "normal" and bk == "normal":
            desired = _scale(bd, -1.0); rule = "opposed-surface-normals"
        else:
            if _dot(_unit(ad), _unit(bd)) < 0: desired = _scale(bd, -1.0)
            rule = "aligned-axes"
        q = _quat_between(ad, desired)
    translation = _sub(bp, rotate(q, ap))
    return {"rotation_wxyz": [round(v, 12) for v in q],
            "translation_m": [round(v, 12) for v in translation],
            "alignment": rule,
            "source_interface": a.get("id") or a.get("name"),
            "target_interface": b.get("id") or b.get("name")}


def _port(component: ProductComponent, interface_id: str) -> ProductInterface:
    for port in component.interfaces:
        if port.interface_id == interface_id: return port
    raise KeyError(f"{component.component_id} has no interface {interface_id!r}")


def _transformed_port(port: ProductInterface, transform: dict[str, Any]) -> ProductInterface:
    q = tuple(transform["rotation_wxyz"]); t = tuple(transform["translation_m"])
    point = _add(rotate(q, port.point_m), t) if port.point_m is not None else None
    axis = rotate(q, port.axis) if port.axis is not None else None
    normal = rotate(q, port.normal) if port.normal is not None else None
    return ProductInterface(port.interface_id, port.kind, point, axis, normal,
                            port.tags, dict(port.properties)).validate()


def transform_component(component: ProductComponent, transform: dict[str, Any]) -> ProductComponent:
    geometry = deepcopy(component.geometry)
    if geometry.get("center_m") is not None:
        geometry["center_m"] = list(transform_point(transform, _v(geometry["center_m"], "center_m")))
    geometry["placement_wxyz"] = list(transform["rotation_wxyz"])
    geometry["placement_translation_m"] = list(transform["translation_m"])
    return ProductComponent(component.component_id, component.role, component.family,
        component.material, geometry,
        tuple(_transformed_port(port, transform) for port in component.interfaces),
        component.physics_tags, component.capabilities, deepcopy(component.properties)).validate()


def mate_component(graph: ProductGraph, *, moving_component: str, moving_interface: str,
                   target_component: str, target_interface: str,
                   relationship_kind: str = "fixed",
                   relationship_id: str | None = None) -> tuple[ProductGraph, dict[str, Any]]:
    """Place one currently-unconnected component and declare how the ports relate."""
    if relationship_kind not in RELATION_KINDS or relationship_kind == "physical-contact":
        raise ValueError("mating needs an explicit semantic relationship such as fixed, hinge, bearing or slider")
    source = graph.component(moving_component); target = graph.component(target_component)
    for relation_doc in graph.relationships:
        if moving_component in {relation_doc.a, relation_doc.b} and not relation_doc.derived:
            raise ValueError("moving component already has declared relationships; move its subassembly instead")
    transform = solve_mate(_port(source, moving_interface), _port(target, target_interface))
    moved = transform_component(source, transform)
    result = deepcopy(graph)
    result.components = [moved if c.component_id == moving_component else c for c in result.components]
    rid = relationship_id or f"mate-{len(result.relationships) + 1}"
    result.relationships.append(relationship(
        rid, relationship_kind, moving_component, target_component,
        a_interface=moving_interface, b_interface=target_interface,
        properties={"mate_transform": transform}, derived=False))
    result.validate()
    return result, transform
