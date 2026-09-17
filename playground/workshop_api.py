"""Workshop HTTP implementation with visual matter, skins and physics-debug views.

The mature API remains in ``workshop_api_core``. This layer preserves existing
responses and adds renderer-neutral representations used by both the browser
and MCP-facing platform adapters.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

import workshop_api_core as _core
from workshop_api_core import *  # noqa: F401,F403
from mcp import workshop_components, workshop_debug, workshop_visual


def _decorate(answer: dict[str, Any], source: dict[str, Any] | None = None) -> dict[str, Any]:
    source = source if isinstance(source, dict) else {}
    for candidate in answer.get("candidates") or []:
        if not isinstance(candidate, dict):
            continue
        try:
            design, overrides = workshop_components.design_from_spec(candidate)
            candidate["skin"] = workshop_visual.skin_document(design, overrides)
        except (ValueError, KeyError):
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


def candidates(app: Any, body: Any) -> dict[str, Any]:
    request = body if isinstance(body, dict) else {}
    if isinstance(request.get("skin_edit"), dict):
        return _skin_edit(app, request)
    return _decorate(_core.candidates(app, body), request)


def more_like_this(app: Any, body: Any) -> dict[str, Any]:
    return _decorate(_core.more_like_this(app, body), body if isinstance(body, dict) else {})


def plan(app: Any, body: Any) -> dict[str, Any]:
    request = body if isinstance(body, dict) else {}
    answer = _core.plan(app, body)
    visual = request.get("visual")
    if visual:
        options = visual if isinstance(visual, dict) else {}
        design, overrides = workshop_components.design_from_spec(request)
        cell = options.get("cell_size_m", request.get("cell_size_m", 0.04))
        exterior = bool(options.get("exterior_only", False))
        answer["skin"] = workshop_visual.skin_document(design, overrides)
        # CellSkin must see all canonical cells so display filtering can never
        # erase topology. The client may still choose which individual cells to
        # render from a separately filtered request later.
        matter = workshop_visual.matter_document(
            design, overrides, cell_size_m=float(cell), exterior_only=exterior)
        answer["matter"] = matter
        answer["cell_skin"] = workshop_debug.cell_skin_document(matter)
        if bool(options.get("debug", True)):
            answer["physics_debug"] = workshop_debug.debug_document(design)
    return answer


library = _core.library
remember = _core.remember
remembered = _core.remembered
