"""Bounded operations an LLM may use inside Workshop Mode.

This module is deliberately pure. It can compose, inspect, fork, compare and
materialize Workshop designs, but it has no live-world, inventory, machine,
filesystem or external process-launch capability. A conversational adapter may
expose these operations to a model without also exposing Banjo's live authoring
tools.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from mcp.workshop import (
    WORKSHOP_SCHEMA,
    ComponentLibrary,
    WorkshopDesign,
    assemble,
    assemblies,
    assembly,
    feedback,
    materialize,
    variants,
)

AGENT_SCHEMA = "banjo.workshop-agent.v1"

OPERATIONS = (
    "list_component_families",
    "list_assemblies",
    "compose_design",
    "inspect_candidate",
    "measure_candidate",
    "change_parameters",
    "fork_variants",
    "compare_candidates",
    "materialize_candidate",
    "record_feedback",
)


def contract() -> dict[str, Any]:
    return {
        "schema": AGENT_SCHEMA,
        "workshop_schema": WORKSHOP_SCHEMA,
        "operations": list(OPERATIONS),
        "rules": [
            "All coordinates are local to the candidate assembly.",
            "Every geometry change rebuilds through mcp.workshop.",
            "Comparisons preserve tradeoffs; no single scalar best is invented.",
            "Materialization is a plan and never a live-world commit.",
            "No operation can access or mutate the live world or inventory.",
        ],
    }


def _object(value: Any, name: str = "request") -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a JSON object")
    return value


def _design(spec: dict[str, Any]) -> WorkshopDesign:
    kind = str(spec.get("kind") or "")
    if not kind:
        raise ValueError("candidate kind is required")
    params = spec.get("parameters") or {}
    if not isinstance(params, dict):
        raise ValueError("candidate parameters must be an object")
    return assemble(
        kind,
        design_id=str(spec.get("design_id") or kind),
        purpose=(str(spec["purpose"]) if spec.get("purpose") else None),
        parameters=params,
    )


def _wire(design: WorkshopDesign) -> dict[str, Any]:
    return design.wireframe()


def _metric(candidate: dict[str, Any], name: str) -> float:
    measured = candidate.get("measured") or {}
    if name == "mass_kg":
        return float(measured["mass_kg"])
    if name == "tip_angle_deg":
        return float(measured["tip_angle_deg"])
    if name == "tip_margin_m":
        return float(measured["smallest_tip_margin_m"])
    if name == "support_area_m2":
        w, d = measured["support_footprint_m"]
        return float(w) * float(d)
    if name == "part_count":
        return float(len(candidate.get("parts") or []))
    raise ValueError(
        "metric must be mass_kg, tip_angle_deg, tip_margin_m, "
        "support_area_m2 or part_count")


def _objective(value: Any) -> tuple[str, str]:
    if isinstance(value, str):
        name, direction = value, ("min" if value in {"mass_kg", "part_count"} else "max")
    elif isinstance(value, dict):
        name = str(value.get("metric") or "")
        direction = str(value.get("direction") or
                        ("min" if name in {"mass_kg", "part_count"} else "max"))
    else:
        raise ValueError("each objective must be a metric name or object")
    _metric({"measured": {
        "mass_kg": 1, "tip_angle_deg": 1, "smallest_tip_margin_m": 1,
        "support_footprint_m": [1, 1]}, "parts": [1]}, name)
    if direction not in {"min", "max"}:
        raise ValueError("objective direction must be min or max")
    return name, direction


def _pareto(rows: list[dict[str, Any]], objectives: list[tuple[str, str]]) -> list[str]:
    frontier: list[str] = []
    for i, row in enumerate(rows):
        dominated = False
        for j, other in enumerate(rows):
            if i == j:
                continue
            no_worse = True
            strictly_better = False
            for name, direction in objectives:
                a, b = row["metrics"][name], other["metrics"][name]
                if direction == "min":
                    if b > a:
                        no_worse = False
                        break
                    strictly_better |= b < a
                else:
                    if b < a:
                        no_worse = False
                        break
                    strictly_better |= b > a
            if no_worse and strictly_better:
                dominated = True
                break
        if not dominated:
            frontier.append(str(row["design_id"]))
    return frontier


def execute(operation: str, arguments: Any = None) -> dict[str, Any]:
    """Run one Workshop-only operation."""
    if operation not in OPERATIONS:
        raise KeyError(f"unknown Workshop operation {operation!r}; use {', '.join(OPERATIONS)}")
    args = _object(arguments or {}, "arguments")

    if operation == "list_component_families":
        return {"schema": AGENT_SCHEMA, "families": ComponentLibrary().described()}

    if operation == "list_assemblies":
        return {"schema": AGENT_SCHEMA, "assemblies": assemblies()}

    if operation == "compose_design":
        design = _design(args)
        return {"schema": AGENT_SCHEMA, "candidate": _wire(design)}

    if operation == "inspect_candidate":
        design = _design(args)
        spec = assembly(design.kind or "")
        return {
            "schema": AGENT_SCHEMA,
            "candidate": _wire(design),
            "assembly": spec.described(),
            "component_families": sorted(
                {p.family for p in design.parts if p.family}),
        }

    if operation == "measure_candidate":
        design = _design(args)
        return {"schema": AGENT_SCHEMA, "design_id": design.design_id,
                "measured": design.measure(), "tests": deepcopy(design.tests)}

    if operation == "change_parameters":
        design = _design(args)
        patch = args.get("changes") or {}
        if not isinstance(patch, dict) or not patch:
            raise ValueError("changes must be a non-empty object")
        changed = assemble(
            design.kind or "",
            design_id=str(args.get("new_design_id") or f"{design.design_id}-changed"),
            purpose=design.purpose,
            parameters={**design.parameters, **patch},
        )
        changed.lineage = {
            "parent": design.design_id,
            "changes": deepcopy(patch),
            "components": deepcopy(changed.lineage.get("components") or []),
        }
        return {"schema": AGENT_SCHEMA, "candidate": _wire(changed)}

    if operation == "fork_variants":
        design = _design(args)
        sweeps = args.get("sweeps") or {}
        if not isinstance(sweeps, dict) or not sweeps:
            raise ValueError("sweeps must be a non-empty object")
        made = variants(design, sweeps)
        limit = max(1, min(200, int(args.get("limit", 60))))
        if len(made) > limit:
            raise ValueError(f"variant sweep makes {len(made)} candidates; limit is {limit}")
        return {"schema": AGENT_SCHEMA, "parent": design.design_id,
                "candidates": [_wire(d) for d in made]}

    if operation == "compare_candidates":
        specs = args.get("candidates") or []
        if not isinstance(specs, list) or not 1 <= len(specs) <= 200:
            raise ValueError("candidates must contain 1 to 200 design specifications")
        objectives = [_objective(v) for v in
                      (args.get("objectives") or ["mass_kg", "tip_angle_deg"])]
        rows = []
        for spec in specs:
            candidate = _wire(_design(_object(spec, "candidate")))
            rows.append({
                "design_id": candidate["design_id"],
                "metrics": {name: _metric(candidate, name) for name, _ in objectives},
                "measured": candidate["measured"],
            })
        return {
            "schema": AGENT_SCHEMA,
            "objectives": [{"metric": n, "direction": d} for n, d in objectives],
            "candidates": rows,
            "pareto_design_ids": _pareto(rows, objectives),
        }

    if operation == "materialize_candidate":
        design = _design(args)
        cell = float(args.get("cell_size_m", 0.04))
        return {"schema": AGENT_SCHEMA, "plan": materialize(design, cell_size_m=cell)}

    if operation == "record_feedback":
        design = _design(args)
        rating = args.get("rating")
        if rating in ("", None):
            rating = None
        else:
            rating = int(rating)
        return {
            "schema": AGENT_SCHEMA,
            "feedback": feedback(
                design, rating=rating,
                selected=(bool(args["selected"]) if "selected" in args else None),
                note=str(args.get("note") or "")[:2000],
            ),
        }

    raise AssertionError(operation)
