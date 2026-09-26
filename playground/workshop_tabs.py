"""The Workshop's other three tabs (docs/workshop-mode.md, "Lab, Inventory,
Skills and Recipes"): what a person has, what they know how to do, and what
each thing they could make would take. The Lab is the bench itself; these
read beside it and spend nothing.

  * Inventory: the material rack (oak, iron, glass...), the goods rack
    (copper, copper wire...), the component families a design is built
    from, and the components and designs saved in the personal library.
  * Recipes: for every template the bench can make, what it takes -- its
    parts, its materials by mass against the rack, the goods its machines
    take -- and what it can do; and the recipes the open room knows (how one
    substance is made into another, machine_goods) with what works them.
  * Skills: what the person's notebook says they know (mcp/progression), the
    techniques the world has that they do not yet, what they have
    demonstrated, and what is blocked and why.
"""
from __future__ import annotations

from typing import Any

import workshop_library
from mcp import workshop as w, workshop_machines


def inventory(app: Any) -> dict[str, Any]:
    rack = workshop_library.rack(app)
    goods = workshop_library.goods_rack(app)
    items = workshop_library.list_items(app, limit=200)
    families = [{"name": f.name, "role": f.role, "about": f.about, "offers": list(f.offers),
                 "parameters": [{"name": p.name, "unit": p.unit, "default": p.default} for p in f.parameters]}
                for f in w.LIBRARY_FAMILIES]
    return {"materials": rack.get("materials", []), "goods": goods.get("goods", []),
            "components": [i for i in items if i.get("item_type") == "component"],
            "designs": [i for i in items if i.get("item_type") == "assembly"],
            "families": families}


def _can_do(record: dict[str, Any], made: w.Assembly) -> list[str]:
    """What a template can do, in words: from its program and its routine."""
    out: list[str] = []
    for program in record.get("programs") or []:
        kind = program.get("kind")
        out.append({"roam": "drives itself and turns away from water", "hover": "flies, holding a height",
                    "still": "works where it stands"}.get(kind, f"runs a {kind} program"))
        routine = program.get("routine") or {}
        if routine.get("kind") == "dig":
            out.append("digs at a site and carries the load to a depot")
        elif routine.get("kind") == "haul":
            out.append("hauls goods from one stockpile to another")
        elif routine.get("kind") == "process":
            out.append(f"works the recipe {routine.get('recipe')!r} from its intake to its output")
        elif routine.get("kind") == "custom":
            out.append(f"runs {len(routine.get('steps') or [])} steps of its own")
        if program.get("sensors"):
            out.append(f"sees water with {len(program['sensors'])} eyes")
    if record.get("panels"):
        out.append("charges its battery from the sun")
    if not out:
        out.append(made.purpose)
    return out


def recipes(app: Any) -> dict[str, Any]:
    held = {r["material"]: float(r["mass_kg"]) for r in workshop_library.rack(app)["materials"]}
    held_goods = {r["substance"]: float(r["mass_kg"]) for r in workshop_library.goods_rack(app)["goods"]}
    templates = []
    for made in w.ASSEMBLIES:
        try:
            design = w.assemble(made.name, design_id=made.name)
        except Exception as failed:               # a template that will not assemble is listed as such
            templates.append({"name": made.name, "purpose": made.purpose, "problem": str(failed)[:160]})
            continue
        bom = workshop_library.bill_of_materials(app, design)
        materials = [{"material": r["material"], "kg": round(float(r["mass_kg"]), 2),
                      "held_kg": round(held.get(r["material"], 0.0), 2),
                      "enough": held.get(r["material"], 0.0) + 5e-5 >= float(r["mass_kg"])} for r in bom["materials"]]
        goods = [{"substance": s, "kg": kg, "held_kg": round(held_goods.get(s, 0.0), 2),
                  "enough": held_goods.get(s, 0.0) + 5e-5 >= kg}
                 for s, kg in sorted(workshop_library.goods_needed(design).items())]
        record = workshop_machines.of(design)
        templates.append({"name": made.name, "purpose": made.purpose, "about": made.about,
                          "parts": len(design.parts), "families": sorted({p.family for p in design.parts if p.family}),
                          "materials": materials, "goods": goods,
                          "enough": all(m["enough"] for m in materials) and all(g["enough"] for g in goods),
                          "can_do": _can_do(record, made),
                          "machines": workshop_machines.described(design)["says"] if record else None})
    room = getattr(getattr(app, "room", None), "spec", None) or {}
    block = room.get("goods") if isinstance(room, dict) else None
    room_recipes = []
    if isinstance(block, dict):
        programs = ((room.get("machines") or {}).get("programs") or [])
        for recipe in block.get("recipes") or []:
            worked_by = [p.get("name") for p in programs
                         if (p.get("routine") or {}).get("recipe") == recipe.get("name")]
            room_recipes.append({**recipe, "worked_by": worked_by})
        deposits = [{"name": d.get("name"), "substance": d.get("substance"),
                     "left_kg": round(float(d.get("reserve_kg", 0.0)) - float(d.get("taken_kg", 0.0)), 1)}
                    for d in block.get("deposits") or []]
    else:
        deposits = []
    return {"templates": templates, "room_recipes": room_recipes, "deposits": deposits,
            "goods_per": {k: {"substance": v[0], "per": v[1], "rate": v[2], "least_kg": v[3]}
                          for k, v in workshop_library.GOODS_PER.items()}}


def skills(app: Any) -> dict[str, Any]:
    """The notebook (server.knowledge_view, through app.knowledge) read as
    achievements: each technique the world has, known or not, with what it
    opens; what has been demonstrated; what is blocked and why."""
    notebook = app.knowledge() if callable(getattr(app, "knowledge", None)) else {}
    try:
        import progression
    except ImportError:
        from mcp import progression  # type: ignore
    registry = app.registry() if callable(getattr(app, "registry", None)) else progression.Registry()
    known = {t["id"] for t in notebook.get("techniques") or []}
    opens: dict[str, list[str]] = {}
    for design in registry.designs.values():
        for route in design["routes"]["any_of"]:
            for need in route.get("all_of") or []:
                if isinstance(need, dict) and need.get("technique"):
                    opens.setdefault(need["technique"], []).append(design["name"])
    techniques = []
    for ident, t in registry.techniques.items():
        needs = [n for n in (t.get("prerequisites") or {}).get("all_of") or []]
        techniques.append({"id": ident, "name": t["name"], "describes": t.get("describes", ""),
                           "known": ident in known,
                           "within_reach": ident not in known and all(n in known for n in needs),
                           "needs": [registry.techniques.get(n, {}).get("name", n) for n in needs],
                           "opens": sorted(set(opens.get(ident, []))),
                           "learn_from": t.get("learn_from", [])})
    return {"techniques": techniques, "designs": notebook.get("designs") or [],
            "blocked": notebook.get("blocked") or [], "not_modelled": notebook.get("not_modelled") or [],
            "revision": notebook.get("revision"), "known": len(known), "of": len(registry.techniques)}
