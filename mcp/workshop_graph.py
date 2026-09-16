"""Component-instance interfaces and relationships for Workshop designs.

Workshop geometry is still authored by ``mcp.workshop``. This module gives that
geometry an explicit graph the UI/agent can reason about: one node per part,
interfaces on the part, and measured physical-contact edges. It is deliberately
computed from the authoritative design, not a second source of geometry.

The first graph is conservative. It describes interfaces/contacts that exist;
future composition can add mate/hinge/slider/electrical/fluid relationships to
the same schema without teaching the LLM to invent XYZ coordinates.
"""
from __future__ import annotations

from math import sqrt
from typing import Any

from mcp.workshop import WorkshopDesign, WirePart

GRAPH_SCHEMA = "banjo.workshop-component-graph.v1"
STRUT_ROLES = {"leg", "post", "beam", "brace", "apron", "stretcher", "axle", "handle"}


def _round3(point: tuple[float, float, float]) -> list[float]:
    return [round(float(v), 5) for v in point]


def _faces(part: WirePart) -> list[dict[str, Any]]:
    # Interface points are descriptive handles, not collision geometry. End
    # points preserve a strut's useful axis; face centres give panels/surfaces a
    # general place to mate without family-specific coordinate arithmetic.
    cx, cy, cz = part.center_m
    w, h, d = part.size_m
    from mcp.workshop import _rotate  # one rotation convention, not another copy
    out = []
    for name, local, normal in (
        ("x-", (-w / 2, 0, 0), (-1, 0, 0)), ("x+", (w / 2, 0, 0), (1, 0, 0)),
        ("y-", (0, -h / 2, 0), (0, -1, 0)), ("y+", (0, h / 2, 0), (0, 1, 0)),
        ("z-", (0, 0, -d / 2), (0, 0, -1)), ("z+", (0, 0, d / 2), (0, 0, 1)),
    ):
        offset = _rotate(part.rotation_deg, local)
        facing = _rotate(part.rotation_deg, normal)
        out.append({"name": f"face-{name}", "kind": "surface",
                    "point_m": _round3((cx + offset[0], cy + offset[1], cz + offset[2])),
                    "normal": _round3(facing)})
    return out


def interfaces(part: WirePart) -> list[dict[str, Any]]:
    result = _faces(part)
    if part.role in STRUT_ROLES or part.shape == "cylinder":
        a, b = part.ends_m()
        kind = "shaft" if part.role in {"axle", "wheel"} else "end"
        result += [{"name": "end-a", "kind": kind, "point_m": _round3(a)},
                   {"name": "end-b", "kind": kind, "point_m": _round3(b)}]
        if part.role == "axle":
            result.append({"name": "shaft-middle", "kind": "shaft", "point_m": _round3(part.center_m)})
        if part.role == "wheel":
            result.append({"name": "hub", "kind": "shaft", "point_m": _round3(part.center_m)})
    return result


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


def graph(design: WorkshopDesign, *, contact_tolerance_m: float = 0.003) -> dict[str, Any]:
    design.validate()
    nodes = [{"id": part.name, "family": part.family, "role": part.role,
              "material": part.material, "interfaces": interfaces(part)}
             for part in design.parts]
    relationships = []
    for i, left in enumerate(design.parts):
        for right in design.parts[i + 1:]:
            gap = _box_gap(left, right)
            if gap <= contact_tolerance_m:
                relationships.append({"kind": "physical-contact", "a": left.name, "b": right.name,
                                      "gap_m": round(gap, 6), "derived": True})
    return {"schema": GRAPH_SCHEMA, "design_id": design.design_id,
            "nodes": nodes, "relationships": relationships,
            "contact_tolerance_m": contact_tolerance_m,
            "note": "Contacts are measured from current geometry; semantic mates/joints can refine them."}


def contacts_of(graph_doc: dict[str, Any], part_name: str) -> list[str]:
    out = []
    for relation in graph_doc.get("relationships") or []:
        if relation.get("kind") != "physical-contact": continue
        if relation.get("a") == part_name: out.append(str(relation.get("b")))
        elif relation.get("b") == part_name: out.append(str(relation.get("a")))
    return sorted(set(out))
