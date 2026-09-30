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


# What a bench design can be made of. A world body may be a sphere; a design
# part may not (mcp.workshop.WirePart takes box, tapered or cylinder only), so
# a round thing opens as the nearest thing the bench can hold and says so
# rather than quietly becoming a crate.
_BENCH_SHAPE = {"box": "box", "cylinder": "cylinder", "tapered": "tapered",
                "sphere": "cylinder", "capsule": "cylinder"}


def carried(app: Any) -> list[dict[str, Any]]:
    """What the person has in their hands and their bag, for the bench to show.

    The bench used to know nothing about it: the Inventory tab read the rack,
    the goods, the library and what had been installed, so a thing you had just
    picked up was nowhere in the Workshop. Each entry carries enough to draw it
    and enough to open it: where it is being carried, what it is made of, how
    big, what colour, and whether the bench itself made it.
    """
    try:
        import inventory_room
        from inventory import items_of
        room = getattr(app, "room", None)
        if room is None or not getattr(room, "spec", None):
            return []
        shown = inventory_room.shown(app)
        spec = room.spec
        bodies = {str(b["name"]): b for b in (spec.get("bodies") or [])
                  if isinstance(b, dict) and b.get("name")}
        bodies.update({str(b["name"]): b for b in (spec.get("precise_rigid_bodies") or [])
                       if isinstance(b, dict) and b.get("name")})
        # Which design made what, so a thing built on the bench opens its own
        # design rather than a fresh copy of its shape.
        made = {}
        for receipt in getattr(room, "workshop_installs", None) or []:
            if isinstance(receipt, dict) and receipt.get("design_id"):
                made[str(receipt.get("root_body") or "")] = str(receipt["design_id"])

        def one(entry: dict[str, Any] | None, where: str) -> dict[str, Any] | None:
            if not entry:
                return None
            name = str(entry.get("name") or "")
            first = bodies.get(name) or {}
            size = [float(v) for v in (first.get("size_mm") or [])] or None
            out = {"where": where, "id": entry.get("id"), "name": name,
                   "material": str(first.get("material") or entry.get("material") or ""),
                   "shape": str(first.get("shape") or entry.get("shape") or "box"),
                   "parts": list(entry.get("parts") or [name]),
                   "color_rgba": str(first.get("color_rgba") or ""),
                   "design_id": made.get(name) or None}
            out["bench_shape"] = _BENCH_SHAPE.get(out["shape"], "box")
            out["same_shape"] = out["bench_shape"] == out["shape"]
            if size:
                out["size_mm"] = size
            thing = next((i for i in items_of(spec) if i["id"] == entry.get("id")), None)
            kg = inventory_room.whole_kg(app, thing) if thing else None
            if kg is not None:
                out["kg"] = round(float(kg), 3)
            return out

        out = []
        for hand, entry in (shown.get("hands") or {}).items():
            got = one(entry, f"{hand} hand")
            if got:
                out.append(got)
        for i, entry in enumerate(shown.get("stowed") or []):
            got = one(entry, f"bag {i + 1}")
            if got:
                out.append(got)
        return out
    except Exception:
        # The bench is worth showing even when the room cannot say what is in a
        # hand; an empty list reads as "carrying nothing", which is what the
        # tab said before this existed.
        return []


def inventory(app: Any) -> dict[str, Any]:
    rack = workshop_library.rack(app)
    goods = workshop_library.goods_rack(app)
    items = workshop_library.list_items(app, limit=200)
    families = [{"name": f.name, "role": f.role, "about": f.about, "offers": list(f.offers),
                 "parameters": [{"name": p.name, "unit": p.unit, "default": p.default} for p in f.parameters]}
                for f in w.LIBRARY_FAMILIES]
    # The products built: standing in the world (the room's install receipts),
    # and saved on the bench (workshop_store).
    room = getattr(app, "room", None)
    in_world = []
    for receipt in getattr(room, "workshop_installs", None) or []:
        if not isinstance(receipt, dict) or receipt.get("status") != "installed":
            continue
        kind = receipt.get("kind") or (receipt.get("candidate") or {}).get("kind") or receipt.get("design_id") or "?"
        in_world.append({"name": receipt.get("root_body") or kind, "kind": str(kind).split("-")[0],
                         "design_id": receipt.get("design_id"), "scene": receipt.get("scene"),
                         "at": receipt.get("request_id")})
    saved = []
    try:
        import workshop_store
        from workshop_api_core import _store
        saved = workshop_store.list_saved(_store(app))
    except Exception:
        saved = []
    return {"materials": rack.get("materials", []), "goods": goods.get("goods", []),
            "components": [i for i in items if i.get("item_type") == "component"],
            "designs": [i for i in items if i.get("item_type") == "assembly"],
            "families": families, "in_world": in_world, "saved": saved,
            "carried": carried(app)}


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
    # THE TREE, from progression itself. This used to be walked here by hand,
    # which meant `needs` listed things you already knew and `learn_from` --
    # the same four words on every technique -- was served and never read.
    journal = app.journal_now() if callable(getattr(app, "journal_now", None)) else None
    techniques = (progression.tech_tree(journal, registry) if journal is not None
                  else _tree_from_known(progression, registry, known))
    return {"techniques": techniques, "designs": notebook.get("designs") or [],
            "blocked": notebook.get("blocked") or [], "not_modelled": notebook.get("not_modelled") or [],
            "revision": notebook.get("revision"), "known": len(known), "of": len(registry.techniques),
            "ranks": max((t["rank"] for t in techniques), default=0) + 1}


def _tree_from_known(progression: Any, registry: Any, known: set[str]) -> list[dict[str, Any]]:
    """The tree without a journal: shape and names, and nothing about what has
    been demonstrated.

    A caller that only handed us a notebook still gets a drawable tree -- the
    graph does not depend on anybody -- but every route reads as not done,
    because with no journal there is nothing to ask.
    """
    rank = progression.ranks_of(registry)
    named = {ident: t["name"] for ident, t in registry.techniques.items()}
    leads: dict[str, list[str]] = {ident: [] for ident in registry.techniques}
    for ident, t in registry.techniques.items():
        for need in (t.get("prerequisites") or {}).get("all_of") or []:
            if need in leads:
                leads[need].append(ident)
    out = []
    for ident, t in registry.techniques.items():
        needs = list((t.get("prerequisites") or {}).get("all_of") or [])
        unmet = [n for n in needs if n not in known]
        routes = [{"id": r.get("id"), "says": r.get("says", ""), "done": False,
                   "all_of": [dict(c) for c in r.get("all_of") or []]}
                  for r in (t.get("earned_by") or {}).get("any_of") or []]
        out.append({"id": ident, "name": t["name"], "describes": t.get("describes", ""),
                    "rank": rank.get(ident, 0), "known": ident in known,
                    "within_reach": ident not in known and not unmet and bool(routes),
                    "taught_only": ident not in known and not unmet and not routes,
                    "needs": [{"id": n, "name": named.get(n, n), "known": n in known} for n in needs],
                    "unmet": unmet,
                    "leads_to": [{"id": n, "name": named.get(n, n), "known": n in known}
                                 for n in sorted(leads.get(ident, []))],
                    "earned_by": routes, "opens": progression.opened_by(registry, ident)})
    out.sort(key=lambda row: (row["rank"], row["name"]))
    return out
