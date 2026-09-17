"""Versioned Workshop/Product platform facade shared by API and MCP clients.

The browser reaches Workshop through ``/api/workshop/*``. This module names
that contract for non-browser clients and adds the generic product engineering
operations underneath Workshop (ProductGraph, PhysicsContract, deterministic
mating, runtime refinement and evidence).

Browser-visible behavior stays in ``playground/workshop_api.py``; MCP calls the
same functions rather than reimplementing Workshop.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PLAYGROUND = ROOT / "playground"
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
if str(PLAYGROUND) not in sys.path: sys.path.insert(0, str(PLAYGROUND))

from mcp import workshop_components, workshop_graph  # noqa: E402
from mcp.product_contract import CONTRACT_SCHEMA, compile_contract  # noqa: E402
from mcp.product_evidence import (EVIDENCE_SCHEMA, envelope as evidence_envelope,
                                  record as evidence_record)  # noqa: E402
from mcp.product_graph import (PRODUCT_SCHEMA, ProductGraph, component, interface,
                               relationship)  # noqa: E402
from mcp.product_mating import mate_component  # noqa: E402
from mcp.product_runtime import decision as refinement_decision  # noqa: E402

import workshop_api  # noqa: E402
import workshop_bench  # noqa: E402
import workshop_library  # noqa: E402

PLATFORM_SCHEMA = "banjo.workshop-platform.v1"

HTTP = {
    "open": "/api/workshop/open",
    "candidates": "/api/workshop/candidates",
    "more": "/api/workshop/more",
    "materialize_and_test": "/api/workshop/plan",
    "feedback": "/api/workshop/feedback",
    "remembered": "/api/workshop/remembered",
    "library": "/api/workshop/library",
}

OPERATIONS = (
    "catalog", "open", "edit", "variants", "materialize", "visual", "test",
    "library", "feedback", "remembered",
    "inspect_product", "mate_product", "runtime_decision",
    "record_evidence", "evidence_envelope",
)


def contract() -> dict[str, Any]:
    return {
        "schema": PLATFORM_SCHEMA,
        "workshop_schema": "banjo.workshop.v1",
        "product_graph_schema": PRODUCT_SCHEMA,
        "physics_contract_schema": CONTRACT_SCHEMA,
        "evidence_schema": EVIDENCE_SCHEMA,
        "skin_schema": "banjo.product-skin.v1",
        "matter_schema": "banjo.workshop-matter.v1",
        "physics_run_schema": "banjo.workshop-physics-run.v1",
        "operations": list(OPERATIONS),
        "http": dict(HTTP),
        "bench_tests": workshop_bench.catalog(),
        "rules": [
            "Browser-visible Workshop operations use the same workshop_api functions from HTTP and MCP.",
            "Scratch tests never advance or mutate the outside live world.",
            "Physical contact does not silently mean fixed.",
            "Observed evidence is not validation without explicit passed acceptance criteria.",
            "Appearance-only skin edits add no physical properties.",
            "A skin edit marked physical rebuilds the Workshop Matter preview.",
            "Materialization is a plan; it does not commit matter to a live world.",
        ],
    }


def _port(value: Any):
    if not isinstance(value, dict): raise ValueError("product interface must be an object")
    return interface(str(value.get("id") or ""), str(value.get("kind") or ""),
                     point_m=value.get("point_m"), axis=value.get("axis"), normal=value.get("normal"),
                     tags=value.get("tags") or (), properties=value.get("properties") or {})


def graph_from_document(value: Any) -> ProductGraph:
    if not isinstance(value, dict) or value.get("schema") != PRODUCT_SCHEMA:
        raise ValueError(f"product_graph must use schema {PRODUCT_SCHEMA}")
    components = []
    for item in value.get("components") or []:
        if not isinstance(item, dict): raise ValueError("product components must be objects")
        components.append(component(
            str(item.get("id") or ""), str(item.get("role") or ""),
            family=(str(item["family"]) if item.get("family") else None),
            material=(str(item["material"]) if item.get("material") else None),
            geometry=item.get("geometry") or {}, interfaces=[_port(p) for p in item.get("interfaces") or []],
            physics_tags=item.get("physics_tags") or (), capabilities=item.get("capabilities") or (),
            properties=item.get("properties") or {}))
    relationships = []
    for item in value.get("relationships") or []:
        if not isinstance(item, dict): raise ValueError("product relationships must be objects")
        relationships.append(relationship(
            str(item.get("id") or ""), str(item.get("kind") or ""),
            str(item.get("a") or ""), str(item.get("b") or ""),
            a_interface=(str(item["a_interface"]) if item.get("a_interface") else None),
            b_interface=(str(item["b_interface"]) if item.get("b_interface") else None),
            properties=item.get("properties") or {}, derived=bool(item.get("derived", False))))
    return ProductGraph(
        product_id=str(value.get("product_id") or ""), purpose=str(value.get("purpose") or "physical product"),
        components=components, relationships=relationships,
        energy=list(value.get("energy") or []), controls=list(value.get("controls") or []),
        contents=list(value.get("contents") or []), tests=list(value.get("tests") or []),
        evidence=list(value.get("evidence") or []), manufacturing=list(value.get("manufacturing") or []),
        metadata=dict(value.get("metadata") or {})).validate()


def _graph(args: dict[str, Any]) -> ProductGraph:
    if isinstance(args.get("product_graph"), dict): return graph_from_document(args["product_graph"])
    design, _ = workshop_components.design_from_spec(args)
    return workshop_graph.product(design)


def engineer(operation: str, args: dict[str, Any]) -> dict[str, Any]:
    if operation == "inspect_product":
        graph = _graph(args); contract_doc = compile_contract(graph)
        return {"schema": PLATFORM_SCHEMA, "product_graph": graph.described(),
                "physics_contract": contract_doc}
    if operation == "mate_product":
        graph = _graph(args); mate = args.get("mate") or {}
        if not isinstance(mate, dict): raise ValueError("mate must be an object")
        result, transform = mate_component(
            graph, moving_component=str(mate.get("moving_component") or ""),
            moving_interface=str(mate.get("moving_interface") or ""),
            target_component=str(mate.get("target_component") or ""),
            target_interface=str(mate.get("target_interface") or ""),
            relationship_kind=str(mate.get("relationship_kind") or "fixed"),
            relationship_id=(str(mate["relationship_id"]) if mate.get("relationship_id") else None))
        return {"schema": PLATFORM_SCHEMA, "product_graph": result.described(),
                "mate_transform": transform, "physics_contract": compile_contract(result)}
    if operation == "runtime_decision":
        contract_doc = args.get("physics_contract")
        if not isinstance(contract_doc, dict): contract_doc = compile_contract(_graph(args))
        event = args.get("event") or {}
        if not isinstance(event, dict): raise ValueError("event must be an object")
        return {"schema": PLATFORM_SCHEMA, "physics_contract": contract_doc,
                "decision": refinement_decision(contract_doc, event)}
    if operation == "record_evidence":
        item = args.get("evidence") or args
        if not isinstance(item, dict): raise ValueError("evidence must be an object")
        record = evidence_record(
            evidence_id=str(item.get("id") or item.get("evidence_id") or ""),
            test=str(item.get("test") or ""), measured=item.get("measured") or {},
            conditions=item.get("conditions") or {}, acceptance=item.get("acceptance") or None,
            validated_range=item.get("validated_range") or None,
            source=str(item.get("source") or "workshop"))
        return {"schema": PLATFORM_SCHEMA, "evidence": record}
    if operation == "evidence_envelope":
        evidence = args.get("evidence") or []
        if not isinstance(evidence, list): raise ValueError("evidence must be a list")
        return {"schema": PLATFORM_SCHEMA, "validated_envelope": evidence_envelope(evidence)}
    raise ValueError(f"unknown product engineering operation {operation!r}")


def call(app: Any, operation: str, args: Any = None) -> dict[str, Any]:
    """Invoke one named platform operation through the canonical implementation."""
    args = args if isinstance(args, dict) else {}
    if operation == "catalog": return workshop_api.library(app)
    if operation == "open": return workshop_api.open_workshop(app, args)
    if operation == "edit": return workshop_api.candidates(app, args)
    if operation == "variants":
        return workshop_api.more_like_this(app, args) if args.get("more_like_this") else workshop_api.candidates(app, args)
    if operation == "visual":
        options = args.get("visual") if isinstance(args.get("visual"), dict) else {}
        request = {**args, "visual": {
            "cell_size_m": options.get("cell_size_m", args.get("cell_size_m", 0.04)),
            "exterior_only": bool(options.get("exterior_only", args.get("exterior_only", False))),
        }}
        return workshop_api.plan(app, request)
    if operation in {"materialize", "test"}: return workshop_api.plan(app, args)
    if operation == "library":
        if args.get("action") == "search":
            tags = args.get("tags") or {}
            if not isinstance(tags, dict): raise ValueError("tags must be an object")
            return {"schema": "banjo.workshop.v1", "personal_library": workshop_library.find_items(
                app, tags=tags, item_type=(str(args["item_type"]) if args.get("item_type") else None),
                match_all=bool(args.get("match_all", True)), limit=max(1, min(500, int(args.get("limit", 200)))))}
        return workshop_api.library(app, args)
    if operation == "feedback": return workshop_api.remember(app, args)
    if operation == "remembered": return workshop_api.remembered(app, args)
    if operation in {"inspect_product", "mate_product", "runtime_decision", "record_evidence", "evidence_envelope"}:
        return engineer(operation, args)
    raise ValueError(f"unknown Workshop platform operation {operation!r}")
