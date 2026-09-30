"""One readiness contract for catalog and saved Workshop recipes.

A recipe is source geometry, not a promise that a chosen room can make it.
Both the Workshop test room and the destination world must accept the *same*
dimensions as drawn.  Placement, stock and a functional trial are later gates.
"""
from __future__ import annotations

from typing import Any

import workshop_fitting


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
        reason = "Dimensions and connections compile as drawn"
    return {"cell_size_m": cell_m, "as_drawn": bool(result["ok"] and not result["changes"]),
            "reason": reason, "changes": [c["says"] for c in result["changes"]]}


def assess(design: Any, overrides: Any = None, *, world_cell_m: float | None) -> dict[str, Any]:
    from workshop_test_room import CELL_M
    from mcp.workshop import assemble
    # Callers may hold an already-overridden design. check_validity applies
    # overrides itself, so always rebuild its clean source first.
    base = assemble(str(design.kind), design_id=design.design_id,
                    purpose=design.purpose, parameters=dict(design.parameters))
    workshop = _one(base, overrides, CELL_M)
    world = _one(base, overrides, world_cell_m) if world_cell_m is not None else None
    return {"schema": "banjo.workshop-recipe-readiness.v1",
            "workshop": workshop, "world": world,
            "ready_as_drawn": bool(workshop["as_drawn"] and world and world["as_drawn"]),
            "native_preview_required": True, "functional_test_required": True}
