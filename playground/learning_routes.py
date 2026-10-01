"""Resolve the curated learning graph against the current native world.

The abstract graph describes prerequisites. This adapter describes where an
implemented action is available now; neither names nor registry starting gifts
are evidence that equipment exists in this world.
"""
from __future__ import annotations

from typing import Any
from mcp import progression
import machine_witness
import workshop_library


def resolve(app: Any, registry: Any, techniques: list[dict]) -> None:
    session = getattr(getattr(app, "live", None), "session", None)
    state = (getattr(session, "state", None) or {})
    native = {b["name"]: b for b in state.get("bodies") or []}
    equipment = machine_witness.machines(app)
    goods = app.room.spec.get("goods") or {}
    recipes = {r["name"]: r for r in goods.get("recipes") or []}
    piles = {p["name"]: p for p in goods.get("stockpiles") or []}
    owner = workshop_library.REQUEST_OWNER.get()
    examples = {}
    for profile in app.room.spec.get("interactions") or []:
        design = progression.design_of(registry, progression.construction_of(app.room.spec,profile))
        body = next((native[p] for p in profile.get("parts") or [] if p in native), None)
        if design and body and (not body.get("parked") or (body.get("parked_by") == owner and owner)):
            examples.setdefault(design.split("@")[0], []).append({"body": body["name"],
                "at_m": body["position_m"], "action": "inspect", "label": "Inspect the tool"})
    for technique in techniques:
        for route in technique.get("earned_by") or []:
            locations, missing = [], []
            for condition in route.get("all_of") or []:
                design = registry.designs.get(condition.get("design")) or {}
                label = design.get("name") or condition.get("design")
                if condition.get("found"):
                    found = examples.get(condition.get("design")) or []
                    if found:
                        locations.extend(found)
                        missing.append("Personal tool study receipts are not implemented yet")
                    else:
                        missing.append(f"Missing example: {label}")
                elif condition.get("demonstrated"):
                    recipe = (design.get("machine") or {}).get("recipe")
                    test = progression.batch_design(registry,recipe) if recipe else None
                    sources = [m for m in equipment if m["recipe"] == recipe
                               and m["program"] == (design.get("machine") or {}).get("program")]
                    if not test or test[1]["id"] != condition.get("test"):
                        missing.append(f"No supported learning action: {label}")
                    elif not sources:
                        missing.append(f"Missing equipment: {label}")
                    elif recipe not in recipes:
                        missing.append(f"Missing recipe: {recipe}")
                    else:
                        for source in sources:
                            p = next(p for p in app.room.spec["machines"]["programs"] if p["name"] == source["machine"])
                            intake = piles.get(p["routine"].get("intake")) or {}
                            holds = intake.get("holds") or {}
                            inputs = recipes[recipe].get("in") or {}
                            absent = [name for name, share in inputs.items() if share > 0 and holds.get(name,0) <= 0]
                            if absent:
                                missing.append(f"{source['machine']} intake needs: {', '.join(absent)}")
                            locations.append({**source, "body": p.get("body"),
                                "action": "watch-machine", "label": "Watch next batch",
                                "needs": absent, "intake": intake.get("name"),
                                "instruction": "Turn on; stay nearby and face it until a batch is saved."})
            route["locations"], route["world_missing"] = locations, list(dict.fromkeys(missing))
            route["world_ready"] = bool(route.get("done")) or bool(locations) and not missing
            if not route.get("done"):
                directions = [f"{l.get('machine') or l['body']} ({l['at_m'][0]:.1f}, {l['at_m'][2]:.1f}): {l['label']}"
                              for l in locations]
                route["says"] = "; ".join(directions + route["world_missing"]) or "No supported action in this world"
        technique["graph_ready"] = technique.get("within_reach", False)
        technique["within_reach"] = technique["graph_ready"] and any(
            r["world_ready"] for r in technique.get("earned_by") or [])
        technique["world_missing"] = list(dict.fromkeys(m for r in technique.get("earned_by") or []
                                                         for m in r["world_missing"]))
        for opened in technique.get("opens") or []:
            design = registry.designs.get(opened["id"]) or {}
            recipe = (design.get("machine") or {}).get("recipe")
            sources = [m for m in equipment if m["recipe"] == recipe]
            opened["locations"] = [dict(l) for r in technique.get("earned_by") or []
                                   for l in r["locations"] if l.get("recipe") == recipe]
            unsupported = [registry.processes[c["process"]].get("name", c["process"])
                           for r in (design.get("routes") or {}).get("any_of") or []
                           for c in r.get("all_of") or [] if c.get("process") in registry.processes
                           and not registry.processes[c["process"]].get("supported")]
            opened["availability"] = ("Equipment present" if sources else
                "Process unavailable: " + ", ".join(unsupported) if unsupported else "Equipment missing")
