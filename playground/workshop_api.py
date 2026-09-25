"""Workshop HTTP implementation with visual-matter and editable-skin extensions.

The mature API remains in ``workshop_api_core``.  This layer preserves every
existing response and adds the representations the visual Workshop needs:
separate skin descriptors, sparse physical-cell previews, and bounded skin
edits stored alongside component overrides.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

import workshop_api_core as _core
from workshop_api_core import *  # noqa: F401,F403
from mcp import workshop_components, workshop_visual, workshop_matter_metrics, workshop_buildability, workshop_rigid, workshop_debug


def _decorate(answer: dict[str, Any], source: dict[str, Any] | None = None) -> dict[str, Any]:
    source = source if isinstance(source, dict) else {}
    for candidate in answer.get("candidates") or []:
        if not isinstance(candidate, dict):
            continue
        try:
            design, overrides = workshop_components.design_from_spec(candidate)
            candidate["skin"] = workshop_visual.skin_document(design, overrides)
            candidate["buildability"] = workshop_buildability.design_feedback(design, overrides)
            models = workshop_rigid.requested_models(design, overrides)
            candidate["mechanical_model"] = next(iter(models)) if len(models) == 1 else "mixed"
            if models != {"lattice"}:
                candidate["analytical"] = {"static_loads": [], "limitations": list(workshop_rigid.LIMITATIONS)}
        except (ValueError, KeyError):
            # A malformed candidate must still fail at its authoritative API
            # boundary; decoration never invents substitute geometry.
            pass
    return answer


def open_workshop(app: Any, body: Any) -> dict[str, Any]:
    request = body if isinstance(body, dict) else {}
    return _decorate(_core.open_workshop(app, body), request)


def _targets(design, part_name: str, scope: str):
    part = next((p for p in design.parts if p.name == part_name), None)
    if part is None:
        raise ValueError(f"there is no component {part_name!r} in this candidate")
    if scope == "this":
        return [part]
    if scope == "similar":
        return [p for p in design.parts if p.role == part.role and p.family == part.family]
    if scope == "all":
        return list(design.parts)
    raise ValueError("skin scope must be this, similar or all")


def _skin_edit(app: Any, body: dict[str, Any]) -> dict[str, Any]:
    edit = body.get("skin_edit") or {}
    if not isinstance(edit, dict):
        raise ValueError("skin_edit must be an object")
    design, overrides = workshop_components.design_from_spec(body)
    part_name = str(edit.get("part_name") or "")
    scope = str(edit.get("scope") or "this")
    patch = edit.get("skin") or {}
    if not isinstance(patch, dict):
        raise ValueError("skin_edit.skin must be an object")
    changed: list[str] = []
    updated = deepcopy(overrides)
    for part in _targets(design, part_name, scope):
        current = dict((updated.get(part.name) or {}).get("skin") or {})
        current.update(patch)
        checked = workshop_visual.checked_skin(current)
        updated.setdefault(part.name, {})["skin"] = checked
        changed.append(part.name)
    # Rebuild only ordinary physical geometry; the visual compiler owns skin.
    base = _core.assemble(design.kind or "", design_id=design.design_id,
                          purpose=design.purpose, parameters=design.parameters)
    edited = workshop_components.apply_overrides(base, updated)
    answer = {
        "schema": _core.WORKSHOP_SCHEMA,
        "kind": str(edited.kind),
        "generation": _core._generation(body) + 1,
        "bench_tests": _core.workshop_bench.catalog(str(edited.kind)),
        "candidates": [_core._candidate(app, edited, _core.assembly(str(edited.kind)), updated)],
        "skin_edit": {"changed": changed, "scope": scope},
    }
    return _decorate(answer, body)


def _mechanics_edit(app: Any, body: dict[str, Any]) -> dict[str, Any]:
    edit = body["mechanics_edit"]
    model = workshop_rigid.checked_mechanics(edit)
    design, overrides = workshop_components.design_from_spec(body)
    updated = deepcopy(overrides)
    for part in design.parts:
        updated.setdefault(part.name, {})["mechanics"] = dict(model)
    base = _core.assemble(design.kind or "", design_id=design.design_id,
                          purpose=design.purpose, parameters=design.parameters)
    edited = workshop_components.apply_overrides(base, updated)
    return _decorate({"schema":_core.WORKSHOP_SCHEMA, "kind":str(edited.kind),
        "generation":_core._generation(body)+1, "bench_tests":_core.workshop_bench.catalog(str(edited.kind)),
        "candidates":[_core._candidate(app,edited,_core.assembly(str(edited.kind)),updated)]})


def candidates(app: Any, body: Any) -> dict[str, Any]:
    request = body if isinstance(body, dict) else {}
    if "mechanics_edit" in request:
        return _mechanics_edit(app, request)
    if isinstance(request.get("skin_edit"), dict):
        return _skin_edit(app, request)
    return _decorate(_core.candidates(app, body), request)


def more_like_this(app: Any, body: Any) -> dict[str, Any]:
    return _decorate(_core.more_like_this(app, body), body if isinstance(body, dict) else {})


def _candidate(design, overrides) -> dict[str, Any]:
    """The design as the installer takes it: what the little world is made from."""
    return {"kind": str(design.kind), "design_id": design.design_id, "purpose": design.purpose,
            "parameters": dict(design.parameters), "component_overrides": overrides or {}}


def plan(app: Any, body: Any) -> dict[str, Any]:
    request = body if isinstance(body, dict) else {}
    if "bench_preview" in request:
        import workshop_setup
        design, overrides = workshop_components.design_from_spec(request)
        return {"schema": _core.WORKSHOP_SCHEMA,
                "bench_preview": workshop_setup.preview(app, design, request["bench_preview"],
                                                        candidate=_candidate(design, overrides))}
    answer = _core.plan(app, body)
    design, overrides = workshop_components.design_from_spec(request)
    models = workshop_rigid.requested_models(design, overrides)
    answer["mechanical_model"] = next(iter(models)) if len(models) == 1 else "mixed"
    if models != {"lattice"}:
        # Never return the old snapped primitive list as this model's build plan.
        answer["wireframe_objects"] = answer.get("wireframe_objects", answer.get("objects", []))
        answer["objects"] = []
        answer["commit"]["requires"].append("precise rigid live-room installation adapter (not implemented)")
        try:
            answer["rigid"] = workshop_rigid.compile_rigid(design, overrides)
            answer["fingerprint"] = answer["rigid"]["physics_hash"]
            answer["geometry_basis"] = "precise-rigid-boxes"
        except ValueError as exc:
            answer["representation_error"] = str(exc)
    visual = request.get("visual")
    if visual:
        options = visual if isinstance(visual, dict) else {}
        design, overrides = workshop_components.design_from_spec(request)
        cell = options.get("cell_size_m", request.get("cell_size_m", 0.04))
        exterior = bool(options.get("exterior_only", False))
        answer["skin"] = workshop_visual.skin_document(design, overrides)
        report, full, summary = workshop_buildability.assess(design, overrides, cell_size_m=cell)
        report["requested_model"] = answer["mechanical_model"]
        if answer.get("rigid"):
            report["rigid"] = {"compilation_ready":True,"live_installation_supported":False,
                "stored_cells":0,"collision_boxes":answer["rigid"]["collision_boxes"],
                "internal_fracture_supported":False}
        if answer.get("representation_error"):
            report["representation_error"] = answer["representation_error"]
        answer["buildability"] = report
        if summary is not None:
            answer["matter_measured"] = summary["measured"]
            answer["matter_bom"] = _core.workshop_library.bill_of_materials(app, design, matter_summary=summary)
            answer["matter_component_mass_kg"] = summary["component_mass_kg"]
        # Build surfaces before display filtering; null stays unavailable, never
        # a substituted bounding box when canonical compilation was rejected.
        answer["cell_skin"] = workshop_debug.cell_skin_document(full) if full is not None else None
        if bool(options.get("debug", True)):
            answer["physics_debug"] = workshop_debug.debug_document(design)
        if full is not None and exterior:
            full["cells"] = [row for row in full["cells"] if row["exposed"]]
            full["shown_cells"] = len(full["cells"])
            full["exterior_only"] = True
        answer["matter"] = full
    return answer


# Keep storage/history behavior from the core; component_overrides now retain
# skin declarations, so saved designs automatically reopen with their skin.
library = _core.library
remember = _core.remember
remembered = _core.remembered
