"""One readiness contract for catalog and saved Workshop recipes.

A recipe is source geometry, not a promise that a chosen room can make it.
Both the Workshop test room and the destination world must accept the *same*
dimensions as drawn.  Placement, stock and a functional trial are later gates.
"""
from __future__ import annotations

import copy
import json
from collections import OrderedDict
from dataclasses import asdict
from typing import Any

import workshop_fitting
from mcp.workshop_recipe_contract import derive

# A recipe's readiness is a function of its source alone: kind, purpose,
# parameters, overrides and the cell size. Compiling every recipe takes about
# 1.5 s of Python, and the page asks for guidance every few seconds; while that
# ran, every walk and step of every player waited behind it (the walking
# stutter of 2026-10-04). So each answer is kept, keyed on that source.
_READY: OrderedDict[str, dict[str, Any]] = OrderedDict()
_READY_MOST = 512


def world_cell_size(app: Any) -> float | None:
    """Read the open native world's grid without starting or changing it."""
    session = getattr(getattr(app, "live", None), "session", None)
    spec = getattr(session, "spec", None)
    if isinstance(spec, dict) and spec.get("cell_m"):
        return float(spec["cell_m"])
    room = getattr(app, "room", None)
    spec = getattr(room, "spec", None)
    if isinstance(spec, dict) and spec.get("cell_m"):
        return float(spec["cell_m"])
    return None


def _one(design: Any, overrides: Any, cell_m: float) -> dict[str, Any]:
    result = workshop_fitting.check_validity(design, overrides, cell_m=cell_m)
    if not result["ok"]:
        reason = result["says"]
    elif result["changes"]:
        reason = "Needs a reviewed redraw: " + result["changes"][0]["says"]
    else:
        reason = result["says"]
    return {"cell_size_m": cell_m, "as_drawn": bool(result["ok"] and not result["changes"]),
            "reason": reason, "changes": [c["says"] for c in result["changes"]],
            **({"blocker": result["blocker"]} if result.get("blocker") else {})}


def by_source(what: str, design: Any, overrides: Any, work: Any, *extra: Any) -> Any:
    """``work()``, remembered for this design source (see _READY above)."""
    try:
        key = json.dumps([what, str(design.kind), design.design_id, design.purpose,
                          dict(design.parameters), [asdict(part) for part in design.parts],
                          design.tests, design.lineage.get("component_overrides"), overrides,
                          *extra], sort_keys=True, default=repr)
    except (TypeError, ValueError):
        return work()
    if key not in _READY:
        _READY[key] = work()
        while len(_READY) > _READY_MOST:
            _READY.popitem(last=False)
    _READY.move_to_end(key)
    return copy.deepcopy(_READY[key])


def contract(design: Any, overrides: Any = None, *, world_cell_m: float | None,
             manufacturing: Any = None, evidence: Any = None) -> dict[str, Any]:
    """The same derived report for built-in, saved and LLM-authored candidates."""
    from workshop_test_room import CELL_M
    if manufacturing is not None and not isinstance(manufacturing, dict):
        raise ValueError("manufacturing settings must be an object")
    settings = {"cell_size_m": world_cell_m, "workshop_cell_size_m": CELL_M,
                **(manufacturing or {})}
    return derive(design, overrides, manufacturing=settings, evidence=evidence)


def assess(design: Any, overrides: Any = None, *, world_cell_m: float | None,
           manufacturing: Any = None, evidence: Any = None) -> dict[str, Any]:
    return by_source("readiness", design, overrides,
                     lambda: _assess(design, overrides, world_cell_m=world_cell_m,
                                     manufacturing=manufacturing, evidence=evidence),
                     world_cell_m, manufacturing, evidence)


def _assess(design: Any, overrides: Any = None, *, world_cell_m: float | None,
            manufacturing: Any = None, evidence: Any = None) -> dict[str, Any]:
    from workshop_test_room import CELL_M
    from mcp.workshop import assemble
    # Callers may hold an already-overridden design. check_validity applies
    # overrides itself, so always rebuild its clean source first.
    base = assemble(str(design.kind), design_id=design.design_id,
                    purpose=design.purpose, parameters=dict(design.parameters))
    from mcp.workshop_components import apply_overrides
    effective_overrides = (base.lineage.get("component_overrides") or {}) if overrides is None else overrides
    resolved = apply_overrides(base, effective_overrides)
    workshop = _one(base, overrides, CELL_M)
    world = _one(base, overrides, world_cell_m) if world_cell_m is not None else None
    return {"schema": "banjo.workshop-recipe-readiness.v1",
            "workshop": workshop, "world": world,
            "ready_as_drawn": bool(workshop["as_drawn"] and world and world["as_drawn"]),
            "native_preview_required": True, "functional_test_required": True,
            "recipe_contract": contract(resolved, effective_overrides, world_cell_m=world_cell_m,
                                        manufacturing=manufacturing, evidence=evidence)}
