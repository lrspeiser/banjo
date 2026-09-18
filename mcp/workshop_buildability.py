"""Bounded, representation-aware Workshop admission diagnostics.

Source geometry is never inflated, snapped or replaced here. Geometry admission
is not a strength test. Preview, scene-cell and exact-box budgets are independent;
missing information is reported as unknown, not as a zero or a successful test.
"""
from __future__ import annotations

from typing import Any

from . import workshop_visual as visual, workshop_matter_metrics as metrics
from .workshop_cell_encoding import MAX_SCENE_CELLS, MAX_SCENE_BOXES, decompose_cells
from .workshop import WorkshopDesign

SCHEMA = "banjo.workshop-buildability.v1"


def design_feedback(design: WorkshopDesign, component_overrides: Any = None, *,
                    cell_size_m: float = .04) -> dict[str, Any]:
    """Cheap O(parts) feedback while editing; does not claim sampled occupancy."""
    cell = visual._number(cell_size_m, "cell_size_m", .005, .2)
    skins = visual.skin_overrides(component_overrides)
    components = []
    for part in design.parts:
        dims = list(part.size_m)
        ordered = sorted(dims)
        skin = skins.get(part.name, {})
        profile = visual._effective_profile(part, skin) if skin.get("physical") else part.shape
        if part.role in {"cable", "belt", "spring"}:
            form, recommendation = "flexible element", "cable/spring model (not implemented)"
        elif ordered[0] * 5 <= ordered[1]:
            form, recommendation = "thin sheet", "sheet model for bending; precise rigid for rigid motion only"
        elif ordered[1] * 5 <= ordered[2]:
            form, recommendation = "slender member", "beam model for bending; precise rigid for rigid motion only"
        else:
            form, recommendation = "bulk solid", "lattice for detailed fracture; precise rigid for rigid motion only"
        components.append({
            "component": part.name, "material": part.material, "size_m": dims,
            "physical_profile": profile, "form": form,
            "nominal_cells_across": [v/cell for v in dims],
            "subcell_axes": ["xyz"[a] for a, v in enumerate(dims) if v < cell-1e-12],
            "recommended_model": recommendation,
            "sampled_cells": None, "disappeared": None,
        })
    return {"schema": SCHEMA, "design_id": design.design_id, "cell_size_m": cell,
            "assessment": "dimensions-only", "components": components,
            "source_geometry_preserved": True, "strength_certified": False,
            "mechanical_resolution_validated": False,
            "limits": {"preview_cells": visual.MAX_PREVIEW_CELLS,
                       "scene_cells": MAX_SCENE_CELLS, "joined_boxes": MAX_SCENE_BOXES,
                       "scan_cells_per_component": visual.MAX_SCAN_CELLS},
            "opening_audit": "not yet sampled; dimensions alone cannot establish clearances"}


def _clearances(design, skins, full):
    """Audit opposing axis-aligned box faces, not arbitrary hole topology.

    Report a closure only where the component envelopes overlap in the other
    two axes. Rotated, curved and tapered clearances deliberately remain unknown.
    """
    sampled = {}
    for row in full["cells"]:
        for name in row["components"]:
            if name not in sampled:
                sampled[name] = [list(row["grid"]), list(row["grid"])]
            lo, hi = sampled[name]
            for a in range(3):
                lo[a] = min(lo[a], row["grid"][a]); hi[a] = max(hi[a], row["grid"][a])
    parts = [p for p in design.parts if p.shape == "box" and not any(p.rotation_deg)
             and not skins.get(p.name, {}).get("physical") and p.name in sampled]
    bounds = {p.name: ([p.center_m[a]-p.size_m[a]/2 for a in range(3)],
                       [p.center_m[a]+p.size_m[a]/2 for a in range(3)]) for p in parts}
    checks = []
    h = full["cell_size_m"]
    for i, p in enumerate(parts):
        for q in parts[i+1:]:
            for a in range(3):
                first, second = (p, q) if p.center_m[a] < q.center_m[a] else (q, p)
                flo, fhi = bounds[first.name]; slo, shi = bounds[second.name]
                gap = slo[a]-fhi[a]
                if not 1e-10 < gap < 2*h:
                    continue
                if not all(min(fhi[b],shi[b])-max(flo[b],slo[b]) > 1e-10
                           for b in range(3) if b != a):
                    continue
                represented = (sampled[second.name][0][a]-sampled[first.name][1][a]-1)*h
                checks.append({"components": [first.name, second.name], "axis": "xyz"[a],
                               "design_clearance_m": gap, "grid_clearance_m": represented,
                               "closed": represented <= 1e-10})
    return checks


def assess(design: WorkshopDesign, component_overrides: Any = None, *,
           cell_size_m: float = .04) -> tuple[dict[str, Any], dict | None, dict | None]:
    """Compile once and return report, full canonical cells and optional metrics.

    Failed/over-budget compilation leaves the design and cheap per-part feedback
    available to the editor. No truncated cell set or substituted resolution is
    returned. Consumers must not turn an incomplete report into a passing test.
    """
    report = design_feedback(design, component_overrides, cell_size_m=cell_size_m)
    report.update(assessment="sampled", compilation_ready=False,
                  installation_ready=False, requires_native_verification=True,
                  preview_complete=False, errors=[], warnings=[], missing_components=[],
                  costs={"stored_cells": None, "collision_boxes": None,
                         "active_deformation_cells": None, "fragment_count": None})
    try:
        full = visual.matter_document(design, component_overrides, cell_size_m=cell_size_m)
    except ValueError as exc:
        report["assessment"] = "compilation-blocked"
        report["errors"].append(str(exc))
        return report, None, None
    report["preview_complete"] = True
    report["physics_hash"] = full["physics_hash"]
    report["costs"]["stored_cells"] = full["total_cells"]
    missing = full["missing_components"]
    report["missing_components"] = missing
    for part in report["components"]:
        count = full["component_cell_counts"].get(part["component"], 0)
        part.update(sampled_cells=count, disappeared=count == 0)
    if missing:
        report["errors"].append("Components disappear at this resolution: " + ", ".join(missing))
    thin = [p["component"] for p in report["components"] if p["subcell_axes"]]
    if thin:
        report["warnings"].append("Subcell features may disappear or thicken with grid alignment: " + ", ".join(thin))
    if full["total_cells"] > MAX_SCENE_CELLS:
        report["errors"].append(f"{full['total_cells']:,} cells exceed the {MAX_SCENE_CELLS:,}-cell scene budget")
    summary = None
    if full["cells"]:
        summary = metrics.measure(full, expected_components=[p.name for p in design.parts])
        if not summary["measured"]["geometry_coherent"]:
            report["errors"].append("The sampled geometry is incomplete or disconnected; native installation is not admitted")
        # Native bridge decomposition is bounded separately from the preview.
        if full["total_cells"] <= MAX_SCENE_CELLS:
            boxes = decompose_cells({tuple(c["grid"]) for c in full["cells"]})
            report["costs"]["collision_boxes"] = len(boxes)
            if len(boxes) > MAX_SCENE_BOXES:
                report["errors"].append(f"{len(boxes)} joined boxes exceed the {MAX_SCENE_BOXES}-box exact bridge budget")
        materials = {c["material"] for c in full["cells"]}
        if len(materials) > 1:
            report["errors"].append("Mixed-material fixed interfaces are not supported by the current installation adapter")
    else:
        report["errors"].append("No physical cells exist at this resolution")
    report["clearance_checks"] = _clearances(design, visual.skin_overrides(component_overrides), full)
    report["opening_audit"] = "opposing axis-aligned box faces only; curved/rotated/internal holes are not verified"
    closed = [c for c in report["clearance_checks"] if c["closed"]]
    if closed:
        report["errors"].append("The selected grid closes " + str(len(closed)) + " checked component clearances")
    report["compilation_ready"] = not report["errors"]
    report["warnings"].append("Occupied geometry does not validate bending, fracture resolution or joint strength")
    full["engine_ready"] = report["compilation_ready"]
    full["readiness_scope"] = "geometry and bridge budgets only; installation requires native verification"
    return report, full, summary
