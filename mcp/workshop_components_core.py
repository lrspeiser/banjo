"""Independent component edits on top of Workshop assemblies.

An assembly remains the deterministic source of its ordinary geometry. Edits to
one selected component are recorded as absolute, local component overrides keyed
by part name. Rebuilding starts from the current assembly recipe and reapplies
only the user's explicit component changes.
"""
from __future__ import annotations

from copy import deepcopy
from math import isfinite, sqrt
from typing import Any

from mcp.workshop import WorkshopDesign, WirePart, _component_counts, assemble
from mcp import workshop_construction
from mcp.workshop_construction import CONSTRUCTION_KEY

OVERRIDE_SCHEMA = "banjo.workshop-component-overrides.v1"
STRUT_ROLES = {"leg", "post", "beam", "brace", "apron", "stretcher", "axle", "handle"}
EDIT_ACTIONS = ("longer", "shorter", "thicker", "thinner", "wider", "narrower", "material")


def _three(value: Any, name: str) -> tuple[float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f"{name} must contain three numbers")
    out = tuple(float(v) for v in value)
    if not all(isfinite(v) for v in out):
        raise ValueError(f"{name} must contain finite numbers")
    return out  # type: ignore[return-value]


def checked_overrides(value: Any) -> dict[str, dict[str, Any]]:
    if value in (None, {}): return {}
    if not isinstance(value, dict) or len(value) > 250:
        raise ValueError("component_overrides must be an object with at most 250 parts")
    out: dict[str, dict[str, Any]] = {}
    for name, patch in value.items():
        if name == CONSTRUCTION_KEY:
            # Parts put in, parts taken off and declared joints travel with the
            # per-part edits, so every path that carries one carries the other.
            block = workshop_construction.checked(patch)
            if block: out[name] = block
            continue
        if not isinstance(name, str) or not name or len(name) > 120 or not isinstance(patch, dict):
            raise ValueError("each component override needs a short part name and an object")
        if set(patch) - {"size_m", "center_m", "rotation_deg", "material", "shape"}:
            raise ValueError(f"{name}: unknown component override field")
        clean: dict[str, Any] = {}
        if "size_m" in patch:
            size = _three(patch["size_m"], f"{name}.size_m")
            if any(v <= 0 or v > 20 for v in size): raise ValueError(f"{name}.size_m must be positive and at most 20 m")
            clean["size_m"] = list(size)
        if "center_m" in patch: clean["center_m"] = list(_three(patch["center_m"], f"{name}.center_m"))
        if "rotation_deg" in patch: clean["rotation_deg"] = list(_three(patch["rotation_deg"], f"{name}.rotation_deg"))
        if "material" in patch:
            material = str(patch["material"]).strip()
            if not material or len(material) > 80: raise ValueError(f"{name}.material is invalid")
            clean["material"] = material
        if "shape" in patch:
            shape = str(patch["shape"])
            if shape not in {"box", "tapered", "cylinder"}: raise ValueError(f"{name}.shape is unsupported")
            clean["shape"] = shape
        out[name] = clean
    return out


def _changed(part: WirePart, patch: dict[str, Any]) -> WirePart:
    return WirePart(name=part.name, role=part.role,
        size_m=tuple(patch.get("size_m", part.size_m)), center_m=tuple(patch.get("center_m", part.center_m)),
        material=str(patch.get("material", part.material)), rotation_deg=tuple(patch.get("rotation_deg", part.rotation_deg)),
        shape=str(patch.get("shape", part.shape)), family=part.family)


def apply_overrides(design: WorkshopDesign, overrides: Any) -> WorkshopDesign:
    patches = checked_overrides(overrides)
    built = workshop_construction.apply(design.parts, patches.get(CONSTRUCTION_KEY) or {})
    known = {part.name for part in built}; missing = sorted(set(patches) - known - {CONSTRUCTION_KEY})
    if missing: raise ValueError("component override names part(s) not in this design: " + ", ".join(missing))
    parts = [_changed(part, patches.get(part.name, {})) for part in built]
    lineage = {**deepcopy(design.lineage), "component_overrides": deepcopy(patches)}
    if CONSTRUCTION_KEY in patches: lineage["components"] = _component_counts(parts)
    return WorkshopDesign(design_id=design.design_id, purpose=design.purpose, parts=parts,
        parameters=deepcopy(design.parameters), lineage=lineage,
        tests=deepcopy(design.tests), notes=list(design.notes), kind=design.kind).validate()


def design_from_spec(spec: Any) -> tuple[WorkshopDesign, dict[str, dict[str, Any]]]:
    if not isinstance(spec, dict): raise ValueError("candidate must be an object")
    kind = str(spec.get("kind") or "")
    if not kind: raise ValueError("candidate kind is required")
    parameters = spec.get("parameters") or {}
    if not isinstance(parameters, dict): raise ValueError("candidate parameters must be an object")
    base = assemble(kind, design_id=str(spec.get("design_id") or kind),
        purpose=(str(spec["purpose"]) if spec.get("purpose") else None), parameters=parameters)
    overrides = checked_overrides(spec.get("component_overrides"))
    return apply_overrides(base, overrides), overrides


def _length_changed(part: WirePart, factor: float) -> tuple[list[float], list[float]]:
    old = float(part.size_m[1]); new = max(0.005, min(20.0, old * factor))
    size = [float(part.size_m[0]), new, float(part.size_m[2])]
    if part.role not in {"leg", "post"}: return size, list(part.center_m)
    a, b = part.ends_m()
    if part.role == "leg": anchor, other = (a, b) if a[1] >= b[1] else (b, a)
    else: anchor, other = (a, b) if a[1] <= b[1] else (b, a)
    dx, dy, dz = (other[i] - anchor[i] for i in range(3)); length = sqrt(dx * dx + dy * dy + dz * dz) or 1.0
    ux, uy, uz = dx / length, dy / length, dz / length
    end = (anchor[0] + ux * new, anchor[1] + uy * new, anchor[2] + uz * new)
    return size, [(anchor[i] + end[i]) / 2 for i in range(3)]


def _thickness(part: WirePart, factor: float) -> list[float]:
    size = [float(v) for v in part.size_m]
    if part.role in STRUT_ROLES:
        size[0] = max(0.003, min(10.0, size[0] * factor)); size[2] = max(0.003, min(10.0, size[2] * factor)); return size
    axis = min(range(3), key=lambda i: size[i]); size[axis] = max(0.003, min(10.0, size[axis] * factor)); return size


def _selected(design: WorkshopDesign, part_name: str, scope: str) -> list[WirePart]:
    part = next((p for p in design.parts if p.name == part_name), None)
    if part is None: raise ValueError(f"there is no component {part_name!r} in this candidate")
    if scope == "this": return [part]
    if scope == "similar": return [p for p in design.parts if p.family == part.family and p.role == part.role]
    if scope == "all": return list(design.parts)
    raise ValueError("scope must be this, similar or all")


def edit(spec: Any, *, part_name: str, action: str, scope: str = "this",
         amount: float = 0.12, material: str | None = None) -> tuple[WorkshopDesign, dict[str, dict[str, Any]], list[str]]:
    if action not in EDIT_ACTIONS: raise ValueError("action must be " + ", ".join(EDIT_ACTIONS))
    amount = float(amount)
    if not isfinite(amount) or not 0.01 <= amount <= 0.8: raise ValueError("amount must be between 0.01 and 0.8")
    design, overrides = design_from_spec(spec); targets = _selected(design, str(part_name), scope)
    changed_names: list[str] = []; updated = deepcopy(overrides)
    for part in targets:
        patch = dict(updated.get(part.name) or {})
        if action in {"longer", "shorter"}:
            factor = 1 + amount if action == "longer" else 1 - amount; size, center = _length_changed(part, factor); patch.update(size_m=size, center_m=center)
        elif action in {"thicker", "thinner"}:
            factor = 1 + amount if action == "thicker" else 1 - amount; patch["size_m"] = _thickness(part, factor)
        elif action in {"wider", "narrower"}:
            factor = 1 + amount if action == "wider" else 1 - amount; size = [float(v) for v in part.size_m]; size[0] = max(0.003, min(20.0, size[0] * factor)); patch["size_m"] = size
        elif action == "material":
            chosen = str(material or "").strip()
            if not chosen: raise ValueError("a material edit needs material")
            patch["material"] = chosen
        updated[part.name] = patch; changed_names.append(part.name)
    base = assemble(design.kind or "", design_id=design.design_id, purpose=design.purpose, parameters=design.parameters)
    edited = apply_overrides(base, updated)
    edited.lineage = {**edited.lineage, "parent": design.design_id,
                      "component_edit": {"parts": changed_names, "action": action, "scope": scope}}
    return edited, updated, changed_names


def component_recipe(design: WorkshopDesign, part_name: str) -> dict[str, Any]:
    part = next((p for p in design.parts if p.name == part_name), None)
    if part is None: raise ValueError(f"there is no component {part_name!r} in this candidate")
    # Keep the original coarse interface names for old consumers, and also keep
    # the full ProductGraph port/physics semantics so a component exported from
    # the library remains useful outside the assembly it came from.
    interfaces = ["start", "end"] if part.role in STRUT_ROLES else ["centre"]
    from mcp import workshop_graph
    semantic = workshop_graph.product(design).component(part.name)
    return {
        "schema": "banjo.workshop-component-recipe.v1",
        "source_design_id": design.design_id, "source_part_name": part.name,
        "family": part.family, "role": part.role, "shape": part.shape,
        "size_m": [float(v) for v in part.size_m], "material": part.material,
        "interfaces": interfaces,
        "ports": [port.described() for port in semantic.interfaces],
        "physics_tags": list(semantic.physics_tags),
        "capabilities": list(semantic.capabilities),
    }


def replace_with_recipe(spec: Any, *, part_name: str, recipe: Any,
                        scope: str = "this") -> tuple[WorkshopDesign, dict[str, dict[str, Any]], list[str]]:
    if not isinstance(recipe, dict) or recipe.get("schema") != "banjo.workshop-component-recipe.v1":
        raise ValueError("that library item is not a reusable Workshop component")
    design, overrides = design_from_spec(spec); targets = _selected(design, str(part_name), scope)
    role, family = str(recipe.get("role") or ""), recipe.get("family")
    compatible = [p for p in targets if p.role == role or (family and p.family == family)]
    if len(compatible) != len(targets): raise ValueError(f"saved {role or family} component is not compatible with the selected part")
    size = _three(recipe.get("size_m"), "saved component size_m"); updated = deepcopy(overrides); names: list[str] = []
    for part in targets:
        patch = dict(updated.get(part.name) or {}); new_size, center = list(size), list(part.center_m)
        if part.role in {"leg", "post"}:
            factor = new_size[1] / float(part.size_m[1]); new_size, center = _length_changed(part, factor); new_size[0], new_size[2] = size[0], size[2]
        patch.update(size_m=new_size, center_m=center,
                     material=str(recipe.get("material") or part.material), shape=str(recipe.get("shape") or part.shape))
        updated[part.name] = patch; names.append(part.name)
    base = assemble(design.kind or "", design_id=design.design_id, purpose=design.purpose, parameters=design.parameters)
    edited = apply_overrides(base, updated)
    edited.lineage = {**edited.lineage, "parent": design.design_id,
                      "reused_component": {"parts": names, "source": recipe.get("source_part_name")}}
    return edited, updated, names
