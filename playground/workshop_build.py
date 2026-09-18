"""Building a Workshop design part by part: the server side of the Build panel.

The model is ``mcp/workshop_construction.py``. This turns one request from the
page -- put this part there, take that one off, fasten these two -- into the
design's new overrides, and answers a preview without changing anything.
"""
from __future__ import annotations

from typing import Any

from mcp import workshop_components, workshop_construction as construction
import workshop_library

ACTIONS = ("preview", "add", "remove", "fasten", "unfasten", "adopt")


def _wire(part) -> dict[str, Any]:
    return {"name": part.name, "role": part.role, "family": part.family, "shape": part.shape,
            "size_m": [float(v) for v in part.size_m], "center_m": [float(v) for v in part.center_m],
            "rotation_deg": [float(v) for v in part.rotation_deg], "material": part.material,
            "mass_kg": round(part.mass_kg(), 4)}


def _placed(app: Any, design, request: dict[str, Any]):
    """The requested part, made and set against the part the person clicked."""
    asked = request.get("part")
    if not isinstance(asked, dict):
        raise ValueError("say which part to add: a family with its sizes, or a saved component")
    asked = dict(asked)
    if asked.get("library_item_id"):
        item = workshop_library.load_item(app, str(asked["library_item_id"]))
        if item["item_type"] != "component":
            raise ValueError("only a saved component can be added as one part")
        asked["recipe"] = item["payload"]
    stem = asked.get("family") or (asked.get("recipe") or {}).get("family") or "part"
    asked["name"] = str(asked.get("name") or "").strip() or construction.fresh_name(design, str(stem))
    new = construction.template_part(asked)
    onto = next((p for p in design.parts if p.name == str(request.get("onto") or "")), None)
    if onto is None:
        raise ValueError("click the part it goes against first")
    return construction.place(
        new, by=str(request.get("by") or "face-y-"), onto=onto, at_m=request.get("at_m") or [],
        twist_deg=float(request.get("twist_deg", 0.0)), depth_m=float(request.get("depth_m", 0.0)),
        snap=bool(request.get("snap", True))), onto


def construct(app: Any, spec: dict[str, Any], request: Any) -> dict[str, Any]:
    """Apply one Build request. Returns ``overrides`` (None for a preview) and a summary."""
    if not isinstance(request, dict):
        raise ValueError("construct must be an object")
    action = str(request.get("action") or "")
    if action not in ACTIONS:
        raise ValueError("construct action must be one of " + ", ".join(ACTIONS))
    design, overrides = workshop_components.design_from_spec(spec)

    if action in ("preview", "add"):
        placed, onto = _placed(app, design, request)
        how = construction.interface(placed, onto)
        touching = None if how is None else {
            "form": how["form"],
            **({"area_m2": round(how["area_m2"], 8), "mitred": how["mitred"]} if how["form"] == "planar"
               else {"diameter_m": round(how["diameter_m"], 6), "engaged_m": round(how["engaged_m"], 6)})}
        summary = {"action": action, "part": _wire(placed), "onto": onto.name, "touching": touching}
        if action == "preview":
            return {"overrides": None, "summary": summary}
        joint = request.get("joint")
        if joint is not None and not isinstance(joint, dict):
            raise ValueError("joint must be an object, or left out for a loose part")
        fasten = {"to": onto.name, **joint} if joint and joint.get("kind") else None
        return {"overrides": construction.add_part(design, overrides, part=placed, joint=fasten),
                "summary": {**summary, "fastened": bool(fasten)}, "select": placed.name}

    if action == "remove":
        name = str(request.get("part_name") or "")
        return {"overrides": construction.remove_part(design, overrides, name),
                "summary": {"action": action, "removed": name}}

    if action in ("fasten", "unfasten"):
        a, b = str(request.get("a") or ""), str(request.get("b") or "")
        kind = None if action == "unfasten" else str(request.get("kind") or "fixed")
        method = str(request["method"]) if request.get("method") else None
        return {"overrides": construction.set_joint(design, overrides, a=a, b=b, kind=kind, method=method),
                "summary": {"action": action, "a": a, "b": b, "kind": kind}}

    # adopt: write the template's connections down as joints of the person's own.
    adopted = construction.adopted(design)
    return {"overrides": construction._with(overrides, adopted),
            "summary": {"action": action, "joints": len(adopted.get("joints") or [])}}
