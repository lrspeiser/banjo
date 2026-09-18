"""MCP tool adapter for the shared Workshop/Product platform facade.

The tools here contain no Workshop business logic. They translate model-sized
arguments into :mod:`mcp.workshop_platform` operations, so MCP uses the same
Workshop API functions as the browser for design, library, testing,
visual compilation and materialization.
"""
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

from mcp import workshop_platform

ROOT = Path(__file__).resolve().parents[1]


def _first_file(candidates: list[Path]) -> Path | None:
    return next((p.resolve() for p in candidates if p and p.is_file()), None)


def default_app() -> Any:
    """Persistent Workshop context for one MCP process."""
    home = Path(os.environ.get("BANJO_WORKSHOP_HOME") or (ROOT / "build" / "mcp-workshop")).resolve()
    runs = home / "runs"; store = home / "workshop"
    runs.mkdir(parents=True, exist_ok=True); store.mkdir(parents=True, exist_ok=True)
    engine = _first_file([
        Path(os.environ["BANJO_LIVE_ENGINE"]) if os.environ.get("BANJO_LIVE_ENGINE") else Path(),
        ROOT / "build" / "integration" / "Release" / "banjo_live_world_run.exe",
        ROOT / "build" / "integration" / "banjo_live_world_run",
        ROOT / "build" / "linux" / "banjo_live_world_run",
    ])
    return SimpleNamespace(
        runs_path=runs,
        workshop_store=store,
        workshop_db=home / "banjo.db",
        workshop_owner_id=os.environ.get("BANJO_WORKSHOP_OWNER", "mcp"),
        engine_path=engine,
        api_key=os.environ.get("OPENAI_API_KEY", ""),
        model=os.environ.get("OPENAI_MODEL", "gpt-5-mini"),
        live=None,
    )


APP = default_app()
ENGINE_TESTS = {"cart_roll", "kettle_heat", "machine_control"}

JSON_OBJECT = {"type": "object", "additionalProperties": True}
DESIGN_FIELDS = {
    "kind": {"type": "string", "description": "Workshop product kind, such as table, cart or kettle."},
    "design_id": {"type": "string"},
    "purpose": {"type": "string"},
    "parameters": JSON_OBJECT,
    "component_overrides": JSON_OBJECT,
}
PRODUCT_GRAPH = {"type": "object", "description": "A banjo.product-graph.v1 document."}
SKIN = {
    "type": "object",
    "description": "Editable banjo.product-skin.v1 component patch. Appearance-only edits do not change matter; physical=true recompiles Matter.",
    "properties": {
        "profile": {"type": "string", "enum": ["design", "block", "round", "curve"]},
        "bend_m": {"type": "number"},
        "physical": {"type": "boolean"},
        "roughness": {"type": "number", "minimum": 0, "maximum": 1},
        "metalness": {"type": "number", "minimum": 0, "maximum": 1},
        "color": {"type": "string"},
    },
}


def _schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": properties, **({"required": required} if required else {})}


TOOLS = [
    {"name": "workshop_catalog",
     "description": "List the Workshop product/component catalog, functional test catalog, personal physics-tagged library, material pricebook and the versioned Workshop platform contract.",
     "inputSchema": _schema({})},
    {"name": "workshop_open",
     "description": "Open a Workshop product, saved design or personal-library assembly and return measured candidates plus all catalogs needed by a client to render the design workspace. Candidates include their editable skin representation. kind=custom with first_part={family, parameters, material} starts a design built from nothing.",
     "inputSchema": _schema({**DESIGN_FIELDS, "first_part": JSON_OBJECT,
         "saved_design_id": {"type": "string"}, "library_item_id": {"type": "string"},
         "world_revision": {"type": "string"}, "target": {"type": "string"}})},
    {"name": "workshop_edit",
     "description": "Edit a Workshop candidate through the same bounded operations as the sim: resize/change material, edit a component skin (including a physical curved skin), reuse a saved component, or optionally ask the Workshop assistant to apply a conversational edit.",
     "inputSchema": _schema({**DESIGN_FIELDS,
         "part_name": {"type": "string"},
         "action": {"type": "string", "enum": ["longer", "shorter", "thicker", "thinner", "material"]},
         "scope": {"type": "string", "enum": ["this", "similar", "all"]},
         "amount": {"type": "number"}, "material": {"type": "string"},
         "skin": SKIN,
         "library_item_id": {"type": "string"}, "message": {"type": "string"}}, ["kind", "part_name"])},
    {"name": "workshop_build",
     "description": "Build a Workshop design part by part. add: put a family part (part={family, parameters, material, length_m for a strut}) or a saved component (part={library_item_id}) against the part named `onto`, by the new part's face `by` (face-y- is its bottom), on `onto_face` at `offset_m` [x, y, z] from that face's middle (or at the product point `at_m`), turned by twist_deg and sunk in by depth_m, fastened with joint_kind fixed|bearing or left loose. preview answers where it would go and what it would meet without changing anything. remove takes part_name off with its joints. fasten/unfasten declare or remove the joint between parts a and b. adopt writes a template's implied connections down as joints. Answers the built candidate with construction.joints measured from the geometry. Start from nothing with workshop_open kind=custom and first_part.",
     "inputSchema": _schema({**DESIGN_FIELDS,
         "action": {"type": "string", "enum": ["preview", "add", "remove", "fasten", "unfasten", "adopt"]},
         "part": JSON_OBJECT,
         "by": {"type": "string", "enum": ["face-x-", "face-x+", "face-y-", "face-y+", "face-z-", "face-z+"]},
         "onto": {"type": "string"},
         "onto_face": {"type": "string", "enum": ["face-x-", "face-x+", "face-y-", "face-y+", "face-z-", "face-z+"]},
         "offset_m": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3,
                      "description": "From the middle of onto_face, in the product's x, y, z; the part of it that leaves the face is ignored."},
         "at_m": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
         "twist_deg": {"type": "number"}, "depth_m": {"type": "number"}, "snap": {"type": "boolean"},
         "joint_kind": {"type": "string", "enum": ["fixed", "bearing", "none"]},
         "joint_method": {"type": "string", "enum": ["bonded", "pressed", "bearing"]},
         "part_name": {"type": "string"}, "a": {"type": "string"}, "b": {"type": "string"}},
         ["kind", "action"])},
    {"name": "workshop_variants",
     "description": "Generate bounded Workshop variants from product parameters, or ask for the six deterministic more-like-this variants around one chosen candidate.",
     "inputSchema": _schema({**DESIGN_FIELDS,
         "sweeps": JSON_OBJECT, "more_like_this": {"type": "boolean"}}, ["kind"])},
    {"name": "workshop_inspect",
     "description": "Compile an exact Workshop design or supplied ProductGraph into banjo.product-graph.v1 and banjo.physics-contract.v1, including relationships and runtime bodies.",
     "inputSchema": _schema({**DESIGN_FIELDS, "product_graph": PRODUCT_GRAPH})},
    {"name": "workshop_test",
     "description": "Run a Workshop product test without touching the outside world: runtime contract, point-force probe, cart roll, kettle heat, machine control, or the assembly's declared static-load engine trial. Engine-backed tests may return banjo.workshop-physics-run.v1 playback frames.",
     "inputSchema": _schema({**DESIGN_FIELDS,
         "test": {"type": "string", "description": "One test from workshop_catalog; use declared_static_load for the assembly's authored load."},
         "config": JSON_OBJECT,
         "cell_size_m": {"type": "number"}, "duration_s": {"type": "number"},
         "evidence_id": {"type": "string"}}, ["kind", "test"])},
    {"name": "workshop_materialize",
     "description": "Compile a selected Workshop candidate to a materialization plan and BOM. With visual=true, also return banjo.product-skin.v1 plus the sparse banjo.workshop-matter.v1 physical-cell preview used by the Workshop Matter view. This never mutates the live world.",
     "inputSchema": _schema({**DESIGN_FIELDS,
         "cell_size_m": {"type": "number"},
         "visual": {"type": "boolean"},
         "exterior_only": {"type": "boolean", "description": "Visual Matter only: return surface cells rather than all occupied cells."}}, ["kind"])},
    {"name": "workshop_library",
     "description": "Use the persistent physics-tagged Workshop library: list, load, semantic tag search, save a component or Workshop design, set material price, or save a functional-test preset.",
     "inputSchema": _schema({**DESIGN_FIELDS,
         "action": {"type": "string", "enum": ["list", "load", "search", "save_component", "save_design", "set_price", "save_test_preset"]},
         "item_id": {"type": "string"}, "name": {"type": "string"}, "part_name": {"type": "string"},
         "tags": JSON_OBJECT,
         "item_type": {"type": "string", "enum": ["component", "assembly"]},
         "match_all": {"type": "boolean"}, "limit": {"type": "integer"},
         "material": {"type": "string"}, "price_per_kg": {"type": "number"}, "currency": {"type": "string"},
         "test": {"type": "string"}, "config": JSON_OBJECT, "preset_id": {"type": "string"}}, ["action"])},
    {"name": "workshop_history",
     "description": "Read the Workshop's saved feedback/history together with saved designs, personal library, prices and functional-test presets through the same remembered surface the sim uses.",
     "inputSchema": _schema({})},
    {"name": "workshop_mate",
     "description": "Deterministically mate two interfaces in an arbitrary ProductGraph and declare the physical relationship, returning the transform, updated graph and PhysicsContract.",
     "inputSchema": _schema({"product_graph": PRODUCT_GRAPH,
         "moving_component": {"type": "string"}, "moving_interface": {"type": "string"},
         "target_component": {"type": "string"}, "target_interface": {"type": "string"},
         "relationship_kind": {"type": "string"}, "relationship_id": {"type": "string"}},
         ["product_graph", "moving_component", "moving_interface", "target_component", "target_interface"])},
    {"name": "workshop_runtime",
     "description": "Ask the adaptive runtime policy whether a reduced PhysicsContract is valid for an event or must refine locally because evidence or required semantics are outside the validated envelope.",
     "inputSchema": _schema({**DESIGN_FIELDS, "product_graph": PRODUCT_GRAPH,
         "physics_contract": {"type": "object"}, "event": JSON_OBJECT}, ["event"])},
    {"name": "workshop_evidence",
     "description": "Create an immutable product evidence record or aggregate separately validated ranges; observations cannot silently become validation without passed acceptance criteria.",
     "inputSchema": _schema({"action": {"type": "string", "enum": ["record", "envelope"]},
         "evidence": {}, "id": {"type": "string"}, "test": {"type": "string"},
         "measured": JSON_OBJECT, "conditions": JSON_OBJECT, "acceptance": JSON_OBJECT,
         "validated_range": JSON_OBJECT, "source": {"type": "string"}}, ["action"])},
    {"name": "workshop_feedback",
     "description": "Save Workshop feedback and optionally persist the selected design into the same personal library used by the sim and Workshop MCP tools.",
     "inputSchema": _schema({**DESIGN_FIELDS, "rating": {"type": "integer", "minimum": 1, "maximum": 5},
         "selected": {"type": "boolean"}, "note": {"type": "string"},
         "save_design": {"type": "boolean"}, "label": {"type": "string"}}, ["kind"])},
]


def _require_engine(test: str, *, always: bool = False) -> None:
    if (always or test in ENGINE_TESTS) and (APP.engine_path is None or not Path(APP.engine_path).is_file()):
        raise ValueError(
            f"{test} needs banjo_live_world_run. Build that target and set BANJO_LIVE_ENGINE; "
            "runtime_contract, force_probe and visual Matter/Skin compilation remain available without it.")


def tool_catalog(_args: dict[str, Any]) -> dict[str, Any]:
    answer = workshop_platform.call(APP, "catalog", {})
    answer["platform"] = workshop_platform.contract()
    return answer


def tool_open(args: dict[str, Any]) -> dict[str, Any]:
    answer = workshop_platform.call(APP, "open", args)
    answer["platform"] = workshop_platform.contract()
    return answer


def tool_edit(args: dict[str, Any]) -> dict[str, Any]:
    request = {k: v for k, v in args.items()
               if k not in {"part_name", "action", "scope", "amount", "material", "skin", "library_item_id", "message"}}
    part = str(args.get("part_name") or "")
    if isinstance(args.get("skin"), dict):
        request["skin_edit"] = {"part_name": part, "scope": str(args.get("scope") or "this"),
                                "skin": args["skin"]}
    elif args.get("message"):
        request["component_chat"] = {"part_name": part, "message": str(args["message"])}
    elif args.get("library_item_id"):
        request["reuse_library_item"] = {"item_id": str(args["library_item_id"]), "part_name": part,
                                          "scope": str(args.get("scope") or "this")}
    else:
        request["component_edit"] = {"part_name": part, "action": str(args.get("action") or ""),
                                     "scope": str(args.get("scope") or "this"),
                                     "amount": float(args.get("amount", 0.12)),
                                     **({"material": str(args["material"])} if args.get("material") else {})}
    return workshop_platform.call(APP, "edit", request)


_BUILD_FIELDS = {"action", "part", "by", "onto", "onto_face", "offset_m", "at_m", "twist_deg", "depth_m",
                 "snap", "joint_kind", "joint_method", "part_name", "a", "b"}


def tool_build(args: dict[str, Any]) -> dict[str, Any]:
    request = {k: v for k, v in args.items() if k not in _BUILD_FIELDS}
    construct = {k: args[k] for k in _BUILD_FIELDS - {"joint_kind", "joint_method"} if k in args}
    joint_kind = str(args.get("joint_kind") or "fixed")
    if construct.get("action") in {"add", "preview"} and joint_kind != "none":
        construct["joint"] = {"kind": joint_kind,
                              **({"method": str(args["joint_method"])} if args.get("joint_method") else {})}
    if construct.get("action") == "fasten":
        construct["kind"] = joint_kind
        if args.get("joint_method"):
            construct["method"] = str(args["joint_method"])
    request["construct"] = construct
    return workshop_platform.call(APP, "edit", request)


def tool_variants(args: dict[str, Any]) -> dict[str, Any]:
    return workshop_platform.call(APP, "variants", args)


def tool_inspect(args: dict[str, Any]) -> dict[str, Any]:
    return workshop_platform.call(APP, "inspect_product", args)


def tool_test(args: dict[str, Any]) -> dict[str, Any]:
    test = str(args.get("test") or "")
    request = {k: v for k, v in args.items() if k not in {"test", "config"}}
    if test == "declared_static_load":
        _require_engine("declared_static_load", always=True)
        # Route through the same bench catalog path as the browser so the result
        # has the same visual playback schema.
        request["bench_test"] = {"test": test, "config": args.get("config") or {
            "cell_size_m": args.get("cell_size_m", 0.04),
            "duration_s": args.get("duration_s", 2.0)}}
    else:
        _require_engine(test)
        request["bench_test"] = {"test": test, "config": args.get("config") or {}}
    return workshop_platform.call(APP, "test", request)


def tool_materialize(args: dict[str, Any]) -> dict[str, Any]:
    if bool(args.get("visual")):
        return workshop_platform.call(APP, "visual", args)
    return workshop_platform.call(APP, "materialize", args)


def tool_library(args: dict[str, Any]) -> dict[str, Any]:
    action = str(args.get("action") or "list")
    if action == "list": return workshop_platform.call(APP, "library", {})
    if action == "search": return workshop_platform.call(APP, "library", {**args, "action": "search"})
    translated = {"save_test_preset": "save_bench_preset"}.get(action, action)
    return workshop_platform.call(APP, "library", {**args, "action": translated})


def tool_history(args: dict[str, Any]) -> dict[str, Any]:
    return workshop_platform.call(APP, "remembered", args)


def tool_mate(args: dict[str, Any]) -> dict[str, Any]:
    mate = {k: args.get(k) for k in ("moving_component", "moving_interface", "target_component",
                                      "target_interface", "relationship_kind", "relationship_id")
            if args.get(k) is not None}
    return workshop_platform.call(APP, "mate_product", {"product_graph": args.get("product_graph"), "mate": mate})


def tool_runtime(args: dict[str, Any]) -> dict[str, Any]:
    return workshop_platform.call(APP, "runtime_decision", args)


def tool_evidence(args: dict[str, Any]) -> dict[str, Any]:
    action = str(args.get("action") or "")
    if action == "envelope":
        return workshop_platform.call(APP, "evidence_envelope", {"evidence": args.get("evidence") or []})
    evidence = args.get("evidence")
    if not isinstance(evidence, dict):
        evidence = {k: args.get(k) for k in ("id", "test", "measured", "conditions", "acceptance",
                                              "validated_range", "source") if args.get(k) is not None}
    return workshop_platform.call(APP, "record_evidence", {"evidence": evidence})


def tool_feedback(args: dict[str, Any]) -> dict[str, Any]:
    return workshop_platform.call(APP, "feedback", args)


HANDLERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "workshop_catalog": tool_catalog,
    "workshop_open": tool_open,
    "workshop_edit": tool_edit,
    "workshop_build": tool_build,
    "workshop_variants": tool_variants,
    "workshop_inspect": tool_inspect,
    "workshop_test": tool_test,
    "workshop_materialize": tool_materialize,
    "workshop_library": tool_library,
    "workshop_history": tool_history,
    "workshop_mate": tool_mate,
    "workshop_runtime": tool_runtime,
    "workshop_evidence": tool_evidence,
    "workshop_feedback": tool_feedback,
}
