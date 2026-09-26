"""The Workshop's server side: one design model and isolated test benches.

Ordinary Workshop operations are pure design computation. Explicit physical
trials and functional bench tests own separate scratch LiveWorld sessions; they
never borrow the outside room. Personal component/design recipes, test presets
and the material pricebook live in ``workshop_library``.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import threading
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp import engine_materials, workshop_components, workshop_construction, workshop_visual, workshop_matter_metrics  # noqa: E402
from mcp.workshop import (  # noqa: E402
    WORKSHOP_SCHEMA, ComponentLibrary, WorkshopSession, assemble, assemblies,
    assembly, feedback, materialize, variants,
)
from mcp.workshop_statics import declared_statics  # noqa: E402
import workshop_bench  # noqa: E402
import workshop_chat  # noqa: E402
import workshop_library  # noqa: E402
import workshop_store  # noqa: E402

_lock = threading.Lock()

SEED_SWEEPS: dict[str, dict[str, list[Any]]] = {
    "table": {"leg_style": ["straight", "splayed", "tapered"], "leg_section_m": [0.045, 0.065]},
    "stool": {"leg_style": ["straight", "splayed", "tapered"], "leg_section_m": [0.032, 0.045]},
    "bench": {"leg_style": ["straight", "splayed", "tapered"], "leg_section_m": [0.04, 0.06]},
    "chair": {"leg_style": ["straight", "splayed", "tapered"], "back_height_m": [0.38, 0.5]},
    "shelf-unit": {"shelves": [3, 4, 5], "side_thickness_m": [0.015, 0.025]},
    "cart": {"wheel_diameter_m": [0.22, 0.32, 0.42], "deck_height_m": [0.3, 0.42]},
}
NUDGES: dict[str, list[tuple[str, list[float]]]] = {
    "table": [("leg_section_m", [-0.015, -0.007, 0.0, 0.007, 0.015, 0.025]), ("splay_deg", [0.0, 3.0, 6.0, 9.0, 12.0, 15.0])],
    "stool": [("leg_section_m", [-0.01, -0.005, 0.0, 0.005, 0.01, 0.016]), ("splay_deg", [0.0, 4.0, 7.0, 10.0, 13.0, 16.0])],
    "bench": [("leg_section_m", [-0.012, -0.006, 0.0, 0.006, 0.012, 0.02]), ("splay_deg", [0.0, 3.0, 6.0, 9.0, 12.0, 15.0])],
    "chair": [("back_height_m", [-0.08, -0.04, 0.0, 0.04, 0.08, 0.14]), ("splay_deg", [0.0, 3.0, 6.0, 9.0, 12.0, 15.0])],
    "shelf-unit": [("height_m", [-0.4, -0.2, 0.0, 0.2, 0.4, 0.6]), ("shelves", [0.0, 0.0, 0.0, 1.0, 1.0, 2.0])],
    "cart": [("wheel_diameter_m", [-0.08, -0.04, 0.0, 0.04, 0.08, 0.14]), ("deck_height_m", [-0.06, -0.03, 0.0, 0.03, 0.06, 0.1])],
}


def _store(app: Any) -> Path:
    explicit = getattr(app, "workshop_store", None)
    if explicit:
        where = Path(explicit)
    elif getattr(app, "runs_path", None) is not None:
        where = Path(app.runs_path).resolve().parent / "workshop"
    else:
        where = ROOT / "build" / "workshop"
    where.mkdir(parents=True, exist_ok=True)
    return where


def _object(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise ValueError("Expected a JSON object")
    return body


def _kind(body: dict[str, Any], fallback: str = "table") -> str:
    kind = body.get("kind", fallback)
    if not isinstance(kind, str):
        raise ValueError("kind must be the name of an assembly")
    assembly(kind)
    return kind


def _parameters(body: dict[str, Any]) -> dict[str, Any]:
    given = body.get("parameters") or {}
    if not isinstance(given, dict):
        raise ValueError("parameters must be a JSON object")
    return given


def _generation(body: dict[str, Any]) -> int:
    try:
        return max(0, min(9999, int(body.get("generation", 0))))
    except (TypeError, ValueError):
        return 0


def _label(kind: str, values: dict[str, Any], spec: Any) -> str:
    known, bits = {p.name for p in spec.parameters}, []
    if "leg_style" in known:
        bits += [str(values["leg_style"]), "%d mm legs" % round(values["leg_section_m"] * 1000)]
        if values.get("splay_deg"):
            bits.append("%g deg splay" % values["splay_deg"])
    elif kind == "shelf-unit":
        bits += ["%d shelves" % round(values["shelves"]), "%d mm sides" % round(values["side_thickness_m"] * 1000)]
    elif kind == "cart":
        bits += ["%d mm wheels" % round(values["wheel_diameter_m"] * 1000), "deck at %.2f m" % values["deck_height_m"]]
    return " · ".join(bits) or kind


def _candidate(app: Any, design: Any, spec: Any, overrides: Any = None) -> dict[str, Any]:
    engine_materials.synchronize_workshop_model()
    # A template with joints and machines of its own (Assembly.overrides)
    # opens with them, unless the person's own overrides are given.
    if overrides in (None, {}) and (design.lineage or {}).get("component_overrides"):
        overrides = design.lineage["component_overrides"]
    wire = design.wireframe()
    wire["label"] = _label(design.kind, design.parameters, spec)
    wire["component_overrides"] = workshop_components.checked_overrides(overrides)
    # How its parts are fastened, measured from the parts as they stand. A
    # template with no joints of its own still answers, with none declared.
    wire["construction"] = workshop_construction.described(design)
    if workshop_construction.CONSTRUCTION_KEY in wire["component_overrides"]:
        count = len(design.parts)
        wire["label"] = f"{count} part{'' if count == 1 else 's'} · built part by part"
    try:
        wire["analytical"] = {"static_loads": declared_statics(design), "limitations": []}
    except ValueError as problem:
        wire["analytical"] = {"static_loads": [], "limitations": [str(problem)]}
    wire["bom"] = workshop_library.bill_of_materials(app, design)
    # What making it would take against the rack. Carried on every candidate so
    # the bench can say what is short without a second round trip; it never
    # stops a candidate being drawn, measured or tried.
    wire["needs"] = workshop_library.what_it_needs(app, design)
    wire["measured"]["basis"] = "wireframe-estimate"
    if workshop_matter_metrics.has_physical_skin(design):
        wire["design_measured"] = wire["measured"]
        wire["evidence_status"] = "requires-retest"
        wire["analytical"] = {"static_loads": [], "limitations": [
            "Wireframe load paths are invalid after physical skin edits. Run the exact-Matter trial."]}
        try:
            matter = workshop_visual.matter_document(design, overrides, cell_size_m=0.04)
            summary = workshop_matter_metrics.measure(matter, expected_components=[p.name for p in design.parts])
        except ValueError as problem:
            wire["measured"]["basis"] = "wireframe-estimate-physical-preview-unavailable"
            wire["notes"].append("Physical preview unavailable: " + str(problem))
        else:
            wire["measured"] = summary["measured"]
            for part in wire["parts"]:
                part["mass_kg"] = summary["component_mass_kg"].get(part["name"], 0.0)
            wire["bom"] = workshop_library.bill_of_materials(app, design, matter_summary=summary)
            wire["needs"] = workshop_library.what_it_needs(app, design, matter_summary=summary)
            wire["notes"] += summary["measured"]["warnings"]
    return wire


def _spread(app: Any, kind: str, base: dict[str, Any], sweeps: dict[str, list[Any]],
            generation: int, purpose: str | None = None, overrides: Any = None) -> list[dict[str, Any]]:
    spec = assembly(kind)
    root = assemble(kind, design_id=f"{kind}-g{generation}", purpose=purpose, parameters=base)
    checked = workshop_components.checked_overrides(overrides)
    # A template with joints and machines of its own (Assembly.overrides) is
    # spread with them when the person gives none: a machine's template says
    # how it is fastened and what drives it, and that is what is opened.
    if not checked and (root.lineage or {}).get("component_overrides"):
        checked = workshop_components.checked_overrides(root.lineage["component_overrides"])
    # Parts a person put in stand where they were put. Sweeping the template's
    # numbers would move the template out from under them, so a built design is
    # one candidate, changed part by part.
    if workshop_construction.CONSTRUCTION_KEY in checked:
        sweeps = {}
    made = variants(root, sweeps) if sweeps else [root]
    out = []
    for index, design in enumerate(made, 1):
        design.design_id = f"{kind}-g{generation}-v{index}"
        design = workshop_components.apply_overrides(design, checked)
        out.append(_candidate(app, design, spec, checked))
    return out


def library(app: Any = None, body: Any = None,
            kind: str | None = None) -> dict[str, Any]:
    body = body if isinstance(body, dict) else {}
    if app is not None:
        action = body.get("action")
        if action == "inspect_component":
            from mcp.workshop_construction import template_part
            from mcp.workshop import WorkshopDesign
            item = workshop_library.load_item(app, str(body.get("item_id") or ""))
            if item["item_type"] != "component":
                raise ValueError("Choose a saved component to inspect")
            part = template_part({"name": "inspected-component", "recipe": item["payload"]})
            design = WorkshopDesign(design_id=item["item_id"], purpose=item["name"], parts=[part])
            skin = item["payload"].get("skin")
            overrides = {part.name: {"skin": skin}} if skin else {}
            return {"schema": WORKSHOP_SCHEMA, "library_item": item,
                    "component_preview": {**design.wireframe(),
                        "skin": workshop_visual.skin_document(design, overrides)},
                    "read_only": True}
        if action == "load":
            return {"schema": WORKSHOP_SCHEMA,
                    "library_item": workshop_library.load_item(app, str(body.get("item_id") or ""))}
        if action == "set_price":
            return {"schema": WORKSHOP_SCHEMA,
                    "pricebook": workshop_library.set_price(
                        app, str(body.get("material") or ""), float(body.get("price_per_kg")),
                        str(body.get("currency") or "credits"))}
        if action == "set_rack":
            return {"schema": WORKSHOP_SCHEMA,
                    "rack": workshop_library.set_rack(
                        app, str(body.get("material") or ""), float(body.get("mass_kg")))}
        if action == "check_validity":
            import workshop_fitting
            kind = _kind(body, "custom")
            base = assemble(kind, design_id=str(body.get("design_id") or kind),
                            purpose=(str(body["purpose"]) if body.get("purpose") else None),
                            parameters=_parameters(body))
            answer = workshop_fitting.check_validity(
                base, workshop_components.checked_overrides(body.get("component_overrides")),
                cell_m=float(body.get("cell_size_m") or 0.04), root=str(body.get("design_id") or kind))
            out = {"schema": WORKSHOP_SCHEMA, "validity": {k: v for k, v in answer.items()
                                                           if k != "overrides"}}
            if answer["ok"]:
                out["candidate"] = _candidate(app, workshop_components.apply_overrides(base, answer["overrides"]),
                                              assembly(kind), answer["overrides"])
            return out
        if action == "needs":
            design, _ = workshop_components.design_from_spec(body)
            return {"schema": WORKSHOP_SCHEMA, "needs": workshop_library.what_it_needs(app, design),
                    "rack": workshop_library.rack(app)}
        if action == "save_component":
            design, _ = workshop_components.design_from_spec(body)
            recipe = workshop_components.component_recipe(design, str(body.get("part_name") or ""))
            item = workshop_library.save_item(
                app, item_type="component", name=str(body.get("name") or body.get("part_name") or "component"),
                payload=recipe, family=recipe.get("family"), role=recipe.get("role"),
                item_id=(str(body["item_id"]) if body.get("item_id") else None))
            return {"schema": WORKSHOP_SCHEMA, "library_item": item,
                    "personal_library": workshop_library.list_items(app),
                    "pricebook": workshop_library.pricebook(app)}
        if action == "save_design":
            design, overrides = workshop_components.design_from_spec(body)
            payload = {"schema": "banjo.workshop-assembly-recipe.v1", "kind": design.kind,
                       "design_id": design.design_id, "purpose": design.purpose,
                       "parameters": dict(design.parameters), "component_overrides": overrides}
            item = workshop_library.save_item(
                app, item_type="assembly", name=str(body.get("name") or design.design_id), payload=payload,
                item_id=(str(body["item_id"]) if body.get("item_id") else None))
            return {"schema": WORKSHOP_SCHEMA, "library_item": item,
                    "personal_library": workshop_library.list_items(app),
                    "pricebook": workshop_library.pricebook(app)}
        if action == "save_bench_preset":
            config = body.get("config") or {}
            if not isinstance(config, dict):
                raise ValueError("bench preset config must be an object")
            preset = workshop_library.save_bench_preset(
                app, name=str(body.get("name") or body.get("test") or "Workshop test"),
                test_name=str(body.get("test") or ""), config=config,
                preset_id=(str(body["preset_id"]) if body.get("preset_id") else None))
            return {"schema": WORKSHOP_SCHEMA, "bench_preset": preset,
                    "bench_presets": workshop_library.list_bench_presets(app)}
    return {
        "schema": WORKSHOP_SCHEMA,
        "families": ComponentLibrary().described(),
        "assemblies": assemblies(),
        "seeds": {k: sorted(v) for k, v in SEED_SWEEPS.items()},
        "saved_designs": workshop_store.list_saved(_store(app)) if app is not None else [],
        "personal_library": workshop_library.list_items(app) if app is not None else [],
        "pricebook": workshop_library.pricebook(app) if app is not None else {},
        "rack": workshop_library.rack(app) if app is not None else {},
        "bench_tests": workshop_bench.catalog(kind),
        "bench_presets": workshop_library.list_bench_presets(app) if app is not None else [],
    }


def open_workshop(app: Any, body: Any) -> dict[str, Any]:
    body = _object(body)
    generation, saved_id, library_id = _generation(body), body.get("saved_design_id"), body.get("library_item_id")
    saved = library_item = None
    if library_id:
        library_item = workshop_library.load_item(app, str(library_id))
        if library_item["item_type"] != "assembly":
            raise ValueError("only an assembly library item can open as the whole Workshop design")
        design, overrides = workshop_components.design_from_spec(library_item["payload"])
        kind = str(design.kind)
        candidates_out = [_candidate(app, design, assembly(kind), overrides)]
        revision, target = "personal-library", library_item["name"]
    elif saved_id:
        saved, design = workshop_store.load(_store(app), str(saved_id))
        kind = str(saved["kind"])
        candidates_out = [_candidate(app, design, assembly(kind), design.lineage.get("component_overrides", {}))]
        revision = str(body.get("world_revision") or saved.get("world_revision") or "unopened-world")
        target = str(body.get("target") or saved.get("label") or design.design_id)
    else:
        kind = _kind(body)
        revision, target = str(body.get("world_revision") or "unopened-world"), str(body.get("target") or kind)
        # A design built from nothing arrives with its first part already in it.
        overrides = body.get("component_overrides")
        if body.get("first_part") is not None:
            if kind != "custom":
                raise ValueError("first_part starts a new build; a template already has its parts")
            import workshop_build
            overrides = workshop_build.starting_overrides(app, body["first_part"])
        candidates_out = _spread(app, kind, _parameters(body), SEED_SWEEPS.get(kind, {}), generation,
                                 overrides=overrides)
    session = WorkshopSession(
        session_id=str(body.get("session_id") or f"bench-{int(time.time()*1000)}"),
        world_revision=revision, target=target)
    return {"schema": WORKSHOP_SCHEMA, "session": session.described(), **library(app, kind=kind),
            "kind": kind, "generation": generation, "candidates": candidates_out,
            **({"saved_design": saved} if saved else {}),
            **({"library_item": library_item} if library_item else {})}


def candidates(app: Any, body: Any) -> dict[str, Any]:
    body, generation = _object(body), _generation(_object(body))
    kind = _kind(body)
    current = {"kind": kind, "design_id": str(body.get("design_id") or f"{kind}-g{generation}"),
               "purpose": body.get("purpose"), "parameters": _parameters(body),
               "component_overrides": body.get("component_overrides") or {}}
    if isinstance(body.get("component_chat"), dict):
        chat, part_name = body["component_chat"], str(body["component_chat"].get("part_name") or "")
        design, overrides = workshop_components.design_from_spec(current)
        wire = _candidate(app, design, assembly(kind), overrides)
        part = next((p for p in wire["parts"] if p["name"] == part_name), None)
        if part is None:
            raise ValueError("component chat needs a selected part")
        book, items = workshop_library.pricebook(app), workshop_library.list_items(app)
        proposal = workshop_chat.propose(
            app, message=str(chat.get("message") or ""), selected_part=part, candidate=wire,
            materials=[m["material"] for m in book["materials"]], library=items)
        action = proposal["action"]
        if action == "none":
            return {"schema": WORKSHOP_SCHEMA, "kind": kind,
            "bench_tests": workshop_bench.catalog(kind), "generation": generation,
                    "candidates": [wire], "workshop_chat": proposal}
        if action == "reuse":
            item = workshop_library.load_item(app, str(proposal.get("library_item_id") or ""))
            if item["item_type"] != "component":
                raise ValueError("Workshop chat chose an assembly where a component is required")
            changed, new_overrides, names = workshop_components.replace_with_recipe(
                current, part_name=part_name, recipe=item["payload"], scope=proposal["scope"])
        else:
            changed, new_overrides, names = workshop_components.edit(
                current, part_name=part_name, action=action, scope=proposal["scope"], amount=0.12,
                material=(str(proposal["material"]) if proposal.get("material") else None))
        return {"schema": WORKSHOP_SCHEMA, "kind": kind,
            "bench_tests": workshop_bench.catalog(kind), "generation": generation + 1,
                "candidates": [_candidate(app, changed, assembly(kind), new_overrides)],
                "workshop_chat": {**proposal, "changed": names}}
    if isinstance(body.get("construct"), dict):
        import workshop_build
        built = workshop_build.construct(app, current, body["construct"])
        if built["overrides"] is None:       # a preview: the design is not changed
            return {"schema": WORKSHOP_SCHEMA, "kind": kind, "generation": generation,
                    "construct": built["summary"]}
        design, overrides = workshop_components.design_from_spec({**current, "component_overrides": built["overrides"]})
        return {"schema": WORKSHOP_SCHEMA, "kind": kind,
                "bench_tests": workshop_bench.catalog(kind), "generation": generation + 1,
                "candidates": [_candidate(app, design, assembly(kind), overrides)],
                "construct": {**built["summary"], **({"select": built["select"]} if built.get("select") else {})}}
    if isinstance(body.get("component_edit"), dict):
        edit = body["component_edit"]
        design, overrides, names = workshop_components.edit(
            current, part_name=str(edit.get("part_name") or ""), action=str(edit.get("action") or ""),
            scope=str(edit.get("scope") or "this"), amount=float(edit.get("amount", 0.12)),
            material=(str(edit["material"]) if edit.get("material") else None))
        return {"schema": WORKSHOP_SCHEMA, "kind": kind,
            "bench_tests": workshop_bench.catalog(kind), "generation": generation + 1,
                "candidates": [_candidate(app, design, assembly(kind), overrides)],
                "component_edit": {"changed": names, "action": edit.get("action")}}
    if isinstance(body.get("reuse_library_item"), dict):
        reuse = body["reuse_library_item"]
        item = workshop_library.load_item(app, str(reuse.get("item_id") or ""))
        if item["item_type"] != "component":
            raise ValueError("drag a component library item onto a selected component")
        design, overrides, names = workshop_components.replace_with_recipe(
            current, part_name=str(reuse.get("part_name") or ""), recipe=item["payload"],
            scope=str(reuse.get("scope") or "this"))
        return {"schema": WORKSHOP_SCHEMA, "kind": kind,
            "bench_tests": workshop_bench.catalog(kind), "generation": generation + 1,
                "candidates": [_candidate(app, design, assembly(kind), overrides)],
                "reused_library_item": {"item_id": item["item_id"], "changed": names}}
    sweeps = body.get("sweeps")
    if sweeps is not None and not isinstance(sweeps, dict):
        raise ValueError("sweeps must be a JSON object of parameter to values")
    return {"schema": WORKSHOP_SCHEMA, "kind": kind,
            "bench_tests": workshop_bench.catalog(kind), "generation": generation,
            "candidates": _spread(app, kind, _parameters(body),
                                  sweeps if sweeps is not None else SEED_SWEEPS.get(kind, {}),
                                  generation, overrides=body.get("component_overrides"))}


def more_like_this(app: Any, body: Any) -> dict[str, Any]:
    body, kind = _object(body), _kind(_object(body))
    spec, base = assembly(kind), assembly(kind).checked(_parameters(body))
    overrides, generation = workshop_components.checked_overrides(body.get("component_overrides")), _generation(body) + 1
    if workshop_construction.CONSTRUCTION_KEY in overrides:
        raise ValueError("This design has parts you put in or took off. Variants change the template's "
                         "sizes underneath them, so they are not offered; change its parts directly.")
    known, made = {p.name: p for p in spec.parameters}, []
    for index in range(6):
        values = dict(base)
        for name, steps in NUDGES.get(kind, []):
            if name not in known:
                continue
            parameter = known[name]
            moved = float(base[name]) + steps[index] if name != "splay_deg" else steps[index]
            if parameter.low is not None:
                moved = max(parameter.low, moved)
            if parameter.high is not None:
                moved = min(parameter.high, moved)
            values[name] = moved
        if kind in {"table", "stool", "bench", "chair"} and values.get("splay_deg"):
            values["leg_style"] = "splayed" if base["leg_style"] == "straight" else base["leg_style"]
        design = workshop_components.apply_overrides(
            assemble(kind, design_id=f"{kind}-g{generation}-v{index+1}", parameters=values), overrides)
        made.append(_candidate(app, design, spec, overrides))
    return {"schema": WORKSHOP_SCHEMA, "kind": kind,
            "bench_tests": workshop_bench.catalog(kind), "generation": generation, "candidates": made}


def plan(app: Any, body: Any) -> dict[str, Any]:
    body, kind = _object(body), _kind(_object(body))
    design, _ = workshop_components.design_from_spec(
        {"kind": kind, "design_id": str(body.get("design_id") or kind), "parameters": _parameters(body),
         "component_overrides": body.get("component_overrides") or {}})
    try:
        cell = float(body.get("cell_size_m", 0.04))
    except (TypeError, ValueError):
        raise ValueError("cell_size_m must be a number")
    if not 0.002 <= cell <= 0.5:
        raise ValueError("cell_size_m must be between 2 mm and 500 mm")
    answer = materialize(design, cell_size_m=cell)
    answer["bom"] = workshop_library.bill_of_materials(app, design)
    # What making it would take, against the rack. A design is never refused
    # for want of material; only MAKING it is (workshop_library.what_it_needs).
    answer["needs"] = workshop_library.what_it_needs(app, design)
    answer["rack"] = workshop_library.rack(app)
    if workshop_matter_metrics.has_physical_skin(design):
        overrides = design.lineage.get("component_overrides") or {}
        answer["wireframe_fingerprint"] = answer["fingerprint"]
        answer["wireframe_objects"] = answer.pop("objects")
        answer["objects"] = []
        answer["commit"]["requires"].append("exact-Matter installation adapter for physical skin edits")
        try:
            matter = workshop_visual.matter_document(design, overrides, cell_size_m=cell)
            summary = workshop_matter_metrics.measure(matter, expected_components=[p.name for p in design.parts])
        except ValueError as problem:
            answer["geometry_basis"] = "physical-preview-unavailable"
            answer["physical_preview_error"] = str(problem)
            answer["measured"]["basis"] = "wireframe-estimate-physical-preview-unavailable"
            answer["commit"]["requires"].append("resolve physical preview: " + str(problem))
        else:
            answer["measured"] = summary["measured"]
            answer["bom"] = workshop_library.bill_of_materials(app, design, matter_summary=summary)
            answer["needs"] = workshop_library.what_it_needs(app, design, matter_summary=summary)
            answer["fingerprint"] = matter["physics_hash"]
            answer["geometry_basis"] = "canonical-matter-grid"
            answer["matter_physics_hash"] = matter["physics_hash"]
    if body.get("run_trial"):
        import workshop_trials
        try:
            duration = float(body.get("duration_s", 2.0))
        except (TypeError, ValueError):
            raise ValueError("duration_s must be a number")
        answer["trial"] = workshop_trials.run_declared_static_load(
            app, design, cell_size_m=cell, duration_s=duration, record_trace=body.get("record_trace", True))
    if body.get("bench_test") is not None:
        answer["bench"] = workshop_bench.run(app, design, body.get("bench_test"))
    return answer


def remember(app: Any, body: Any) -> dict[str, Any]:
    body, kind = _object(body), _kind(_object(body))
    design_id = workshop_store.safe_design_id(body.get("design_id") or kind)
    design, overrides = workshop_components.design_from_spec(
        {"kind": kind, "design_id": design_id, "parameters": _parameters(body),
         "component_overrides": body.get("component_overrides") or {}})
    rating = body.get("rating")
    if rating not in (None, "") and int(rating) not in range(1, 6):
        raise ValueError("rating must be 1 through 5")
    note = str(body.get("note", ""))[:2000]
    wants_feedback = rating not in (None, "") or bool(note) or "selected" in body
    record, where = None, _store(app) / "feedback.jsonl"
    if wants_feedback:
        record = feedback(design, rating=int(rating) if rating not in (None, "") else None,
                          selected=bool(body.get("selected", True)), note=note)
        record["saved_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        record["fingerprint"] = materialize(design)["fingerprint"]
        from mcp import workshop_rigid
        models = workshop_rigid.requested_models(design)
        if workshop_matter_metrics.has_physical_skin(design) or models != {"lattice"}:
            record["evidence_status"] = "requires-retest"
            try:
                record["fingerprint"] = (workshop_rigid.compile_rigid(design)["physics_hash"]
                    if models != {"lattice"} else workshop_visual.matter_document(design, overrides)["physics_hash"])
            except ValueError as exc:
                record["physical_preview_error"] = str(exc)
                record["evidence_status"] = "source-only-physical-preview-unavailable"
        with _lock:
            with where.open("a", encoding="utf-8") as out:
                out.write(json.dumps(record, sort_keys=True) + "\n")
    saved_design = library_item = None
    if body.get("save_design"):
        saved_design = workshop_store.save(
            _store(app), design, label=str(body.get("label") or design_id),
            parent_design_id=(str(body["parent_design_id"]) if body.get("parent_design_id") else None),
            world_revision=(str(body["world_revision"]) if body.get("world_revision") else None))
        payload = {"schema": "banjo.workshop-assembly-recipe.v1", "kind": kind,
                   "design_id": design_id, "purpose": design.purpose,
                   "parameters": dict(design.parameters), "component_overrides": overrides}
        library_item = workshop_library.save_item(
            app, item_type="assembly", name=str(body.get("label") or design_id), payload=payload,
            item_id=(str(body["library_item_id"]) if body.get("library_item_id") else None))
    kept = 0
    if where.exists():
        with _lock:
            with where.open(encoding="utf-8") as back:
                kept = sum(1 for line in back if line.strip())
    designs = workshop_store.list_saved(_store(app))
    return {"schema": WORKSHOP_SCHEMA, "saved": record, "design": saved_design,
            "library_item": library_item, "kept": kept, "designs_kept": len(designs),
            "saved_designs": designs, "personal_library": workshop_library.list_items(app),
            "bench_presets": workshop_library.list_bench_presets(app)}


def remembered(app: Any, body: Any = None) -> dict[str, Any]:
    where, rows = _store(app) / "feedback.jsonl", []
    if where.exists():
        with _lock:
            for line in where.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
    rows.reverse()
    designs = workshop_store.list_saved(_store(app))
    return {"schema": WORKSHOP_SCHEMA, "kept": len(rows), "feedback": rows[:200],
            "designs_kept": len(designs), "saved_designs": designs,
            "personal_library": workshop_library.list_items(app),
            "pricebook": workshop_library.pricebook(app),
            # No product is selected on this path, so the catalog is not narrowed.
            "bench_tests": workshop_bench.catalog(),
            "bench_presets": workshop_library.list_bench_presets(app)}
