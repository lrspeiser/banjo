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

from copy import deepcopy
from typing import Any

import workshop_library
import workshop_recipe
import workshop_store
from mcp import workshop as w, workshop_machines


# What a bench design can be made of. A world body may be a sphere; a design
# part may not (mcp.workshop.WirePart takes box, tapered or cylinder only), so
# a round thing opens as the nearest thing the bench can hold and says so
# rather than quietly becoming a crate.
_BENCH_SHAPE = {"box": "box", "cylinder": "cylinder", "tapered": "tapered",
                "sphere": "cylinder", "capsule": "cylinder"}


def carried(app: Any, player_id: str = "") -> list[dict[str, Any]]:
    """What the person has in their hands and their bag, for the bench to show.

    The bench used to know nothing about it: the Inventory tab read the rack,
    the goods, the library and what had been installed, so a thing you had just
    picked up was nowhere in the Workshop. Each entry carries enough to draw it
    and enough to open it: where it is being carried, what it is made of, how
    big, what colour, and whether the bench itself made it.
    """
    try:
        import inventory_room
        room = getattr(app, "room", None)
        if room is None or not getattr(room, "spec", None):
            return []
        shown = inventory_room.shown(app, player_id)
        spec = room.spec
        bodies = {str(b["name"]): b for b in (spec.get("bodies") or [])
                  if isinstance(b, dict) and b.get("name")}
        bodies.update({str(b["name"]): b for b in (spec.get("precise_rigid_bodies") or [])
                       if isinstance(b, dict) and b.get("name")})
        # Which design made what, so a thing built on the bench opens its own
        # design rather than a fresh copy of its shape.
        made = {}
        import workshop_install
        for receipt in workshop_install.made_here(app):
            for name in receipt["bodies"]:
                made[name] = str(receipt["design_id"])

        def one(entry: dict[str, Any] | None, where: str) -> dict[str, Any] | None:
            if not entry:
                return None
            name = str(entry.get("name") or "")
            first = bodies.get(name) or {}
            size = [float(v) for v in (first.get("size_mm") or [])] or None
            out = {"where": where, "id": entry.get("id"), "name": name,
                   "label": entry.get("label") or name, "next_use":entry.get("next_use",[]),
                   "recipe":entry.get("recipe"),
                   "material": str(first.get("material") or entry.get("material") or ""),
                   "shape": str(first.get("shape") or entry.get("shape") or "box"),
                   "parts": list(entry.get("parts") or [name]),
                   "color_rgba": str(first.get("color_rgba") or ""),
                    "design_id": (made.get(name) or None) if not entry.get('separated') else None,
                    "separated": bool(entry.get('separated'))}
            if entry.get("thumbnail_rev"):
                out["thumbnail_rev"] = entry["thumbnail_rev"]
            out["bench_shape"] = _BENCH_SHAPE.get(out["shape"], "box")
            out["same_shape"] = out["bench_shape"] == out["shape"]
            if first.get('parts') and not out['design_id']:
                out['lab_problem']='This compound has no retained editable recipe. Its World geometry is unchanged.'
            if size:
                out["size_mm"] = size
            thing = next((i for i in inventory_room.items_of(app) if i["id"] == entry.get("id")), None)
            kg = inventory_room.whole_kg(app, thing) if thing else None
            out['mass_source']='Live native reading' if kg is not None else 'Unreported'
            # Pose replies omit parked bodies. Their saved native checkpoint
            # retains the mass; label that source instead of treating a missing
            # pose as zero mass or substituting a recipe estimate.
            if kg is None and thing and where.startswith('bag '):
                snapshot=getattr(room,'world_record',None) or {}
                parked={}
                for body in snapshot.get('bodies',[]):
                    if body.get('name') not in thing['bodies'] or not body.get('parked'):continue
                    stored=body['parked'] if isinstance(body['parked'],dict) else body
                    if stored.get('mass_kg') is not None:parked[body['name']]=float(stored['mass_kg'])
                if set(parked)==set(thing['bodies']):
                    kg=sum(parked.values())
                    out['mass_source']='Saved native checkpoint'
                    out['mass_saved_t_s']=snapshot.get('t_s')
            if kg is not None:
                out["kg"] = float(kg)
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
        # The native query includes parked bodies; a missing reading is never
        # replaced with an invented 100%. Query batches stay bounded.
        names=list(dict.fromkeys(n for thing in out for n in thing['parts']))
        readings={}
        if names and getattr(getattr(app,'live',None),'session',None) is not None:
            try:
                for start in range(0,len(names),64):
                    answer=app.live.act({'session':app.live.session.id,'op':'condition','names':names[start:start+64]})
                    readings.update({r['name']:r for r in answer['condition']['bodies']})
            except (ValueError,KeyError,OSError):
                readings={}
        for thing in out:
            rows=[readings.get(n,{'name':n,'state':'unavailable','fraction':None}) for n in thing['parts']]
            covered={n for row in rows if row['state']!='unavailable' for n in row.get('source_parts',[])}
            # A joined head/handle can be one native body. Only native-reported
            # source membership covers an absent authored component name.
            thing['condition']=[r for r in rows if r['state']!='unavailable' or r['name'] not in covered]
        return out
    except Exception:
        # The bench is worth showing even when the room cannot say what is in a
        # hand; an empty list reads as "carrying nothing", which is what the
        # tab said before this existed.
        return []


def inventory(app: Any, player_id: str = "") -> dict[str, Any]:
    import inventory_room,live_session
    session=getattr(getattr(app,"live",None),"session",None)
    ground_load=inventory_room._carried(app,player_id) if session is not None else {}
    unassigned=live_session.current_carried(session,"") if player_id else {}
    rack = workshop_library.rack(app)
    goods = workshop_library.goods_rack(app)
    items = workshop_library.list_items(app, limit=200)
    families = [{"name": f.name, "role": f.role, "about": f.about, "offers": list(f.offers),
                 "parameters": [{"name": p.name, "unit": p.unit, "default": p.default} for p in f.parameters]}
                for f in w.LIBRARY_FAMILIES]
    # The products built: standing in the world (the room's install receipts),
    # and saved on the bench (workshop_store).
    room = getattr(app, "room", None)
    import product_labels
    labels=product_labels.body_labels(app) if room is not None else {}
    in_world = []
    for receipt in getattr(room, "workshop_installs", None) or []:
        if not isinstance(receipt, dict) or receipt.get("status") != "installed":
            continue
        kind = receipt.get("kind") or (receipt.get("candidate") or {}).get("kind") or receipt.get("design_id") or "?"
        in_world.append({"name": receipt.get("root_body") or kind, "kind": str(kind).split("-")[0],
                         "label":labels.get(receipt.get('root_body'),'Built item'),
                         "design_id": receipt.get("design_id"), "scene": receipt.get("scene"),
                         "at": receipt.get("request_id")})
    saved = []
    try:
        import workshop_store
        from workshop_api_core import _store
        saved = workshop_store.list_saved(_store(app))
    except Exception:
        saved = []
    import fabrication_stock
    reservations = fabrication_stock.pending(app, room.scene) if room is not None else []
    import world_goods
    from mcp import fabrication
    raw = getattr(room, 'fabrication_record', None) or {}
    stored_ground=[]
    for lot, contents in fabrication.raw_inventory(raw).items():
        provenance=raw.get('raw_lot_ownership',{}).get(lot,{})
        owner=provenance.get('owner','')
        if owner and owner!=player_id: continue
        for item in contents:
            if item['mass_kg'] <= 1e-9: continue
            stored_ground.append({**item, 'lot_id':lot, 'pool':'personal' if owner else 'shared',
                'recovered':bool(owner and not provenance.get('source_actor'))})
    return {"materials": rack.get("materials", []), "goods": goods.get("goods", []),
            "fabrication_reservations": reservations,
            "delivery_reservations": world_goods.pending_deliveries(app,player_id),
            "components": [i for i in items if i.get("item_type") == "component"],
            "designs": [i for i in items if i.get("item_type") == "assembly"],
            "families": families, "in_world": in_world, "saved": saved,
            "carried": carried(app, player_id),"ground_load":ground_load,"unassigned_ground":unassigned,
            "stored_ground":stored_ground}


def _can_do(record: dict[str, Any], made: w.Assembly, design=None) -> list[str]:
    """Declared use from a template's program and routine, not a test result."""
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
    if design is not None:
        from mcp import workshop_tools
        if workshop_tools.frame(design) is not None:
            out.extend(['gathers dry soil or sand','study its construction'])
    if not out:
        out.append(made.purpose)
    return out


def _capabilities(record: dict[str, Any], design: Any) -> list[dict[str, str]]:
    """Short badges for what a design is declared to do, from its machinery.

    Each badge names behaviour the design's own declaration supports; a part
    that only LOOKS like a panel or lamp, with no machine record behind it, is
    reported as a shape so a player is not told a block of glass makes power.
    These remain declarations: whether the made product works is its trial.
    """
    out: list[dict[str, str]] = []
    def add(label: str, detail: str) -> None:
        if all(c["label"] != label for c in out):
            out.append({"label": label, "detail": detail})
    record = record or {}
    if record.get("lamps"):
        lamp = record["lamps"][0]
        add("Light", f"{lamp['watts']:g} W lamp" + (f" on {lamp['store']}" if lamp.get("store") else ""))
    for store in record.get("stores") or []:
        add("Battery", f"stores {store['capacity_j'] / 3600:.2g} Wh")
    if record.get("panels"):
        n = len(record["panels"])
        add("Solar power", f"{n} panel{'s' if n != 1 else ''} charge its battery")
    if record.get("motors"):
        n = len(record["motors"])
        add("Motor", f"{n} driven joint{'s' if n != 1 else ''}")
    if record.get("chambers"):
        add("Heat", "a heated chamber")
    for program in record.get("programs") or []:
        kind = program.get("kind")
        if kind == "roam": add("Drives", "drives itself and turns away from water")
        elif kind == "hover": add("Flies", "holds a height")
        routine = program.get("routine") or {}
        if routine.get("kind") == "dig": add("Digs", "digs at a site and carries the load to a depot")
        elif routine.get("kind") == "haul": add("Hauls", "carries goods between stockpiles")
        elif routine.get("kind") == "process": add("Processes", f"works {routine.get('recipe')!r}")
        elif routine.get("kind") == "custom": add("Program", f"{len(routine.get('steps') or [])} steps")
        if program.get("sensors"): add("Senses", f"{len(program['sensors'])} probes")
    if design is not None:
        from mcp import workshop_tools
        if workshop_tools.frame(design) is not None:
            add("Gathers", "dry soil or sand")
        use = (design.parameters or {}).get("primary_use") or {}
        furniture = {"stool": ("Seat", "seats one person"), "chair": ("Seat", "seats one person, with a back"),
                     "bench": ("Seat", "seats two or three people"), "table": ("Surface", "a stable work surface"),
                     "shelf-unit": ("Storage", "holds things on several levels"), "cart": ("Wheels", "carries a load on wheels"),
                     "foundation-pad": ("Foundation", "a level pad to build on")}
        # The starter work table is built from the bench assembly; its own
        # declared use, not the assembly it came from, says what it is for.
        if not out and "surface" in str(use.get("label", "")).lower():
            add("Surface", use["label"])
        if not out and design.kind in furniture:
            add(*furniture[design.kind])
        families = {p.family for p in design.parts if p.family}
        if "solar-panel" in families and not record.get("panels"):
            add("Shape only", "panel shape with no declared power")
        if "lamp" in families and not record.get("lamps"):
            add("Shape only", "lamp shape with no declared light")
    return out


def recipes(app: Any) -> dict[str, Any]:
    stock = {r["material"]: r for r in workshop_library.rack(app)["materials"]}
    goods_stock = {r["substance"]: r for r in workshop_library.goods_rack(app)["goods"]}
    held = {name: float(r["mass_kg"]) for name,r in stock.items()}
    from mcp import matter_fabrication
    native_raw=matter_fabrication.available_materials(
        getattr(getattr(app,'room',None),'fabrication_record',None) or {},workshop_library.rack_owner_id(app))
    for material,kg in native_raw.items():held[material]=held.get(material,0.)+kg
    held_goods = {name: float(r["mass_kg"]) for name,r in goods_stock.items()}
    world_cell_m = workshop_recipe.world_cell_size(app)
    templates = []
    def add(design: w.WorkshopDesign, made: w.Assembly, *, name: str,
            source: str, saved_design_id: str | None = None) -> None:
        overrides = design.lineage.get("component_overrides", {})
        bom = workshop_library.bill_of_materials(app, design)
        materials = [{"material": r["material"], "kg": float(r["mass_kg"]),
                      "held_kg": held.get(r["material"], 0.0),
                      "personal_kg": stock.get(r["material"],{}).get("personal_kg",0)+native_raw.get(r['material'],0.),
                      "native_raw_kg":native_raw.get(r['material'],0.),
                      "shared_kg": stock.get(r["material"],{}).get("shared_kg",0),
                      "enough": held.get(r["material"], 0.0) + 5e-5 >= float(r["mass_kg"])} for r in bom["materials"]]
        goods = [{"substance": s, "kg": kg, "held_kg": held_goods.get(s, 0.0),
                  "personal_kg": goods_stock.get(s,{}).get("personal_kg",0),
                  "shared_kg": goods_stock.get(s,{}).get("shared_kg",0),
                  "enough": held_goods.get(s, 0.0) + 5e-5 >= kg}
                 for s, kg in sorted(workshop_library.goods_needed(design).items())]
        for line in [*materials,*goods]:
            line['debit_personal_kg']=min(line['kg'],line['personal_kg'])
            line['debit_shared_kg']=min(max(0.,line['kg']-line['debit_personal_kg']),line['shared_kg'])
        record = workshop_machines.of(design)
        from mcp import workshop_placement
        templates.append({"name": name, "purpose": design.purpose, "about": made.about,
                          "source": source, "saved_design_id": saved_design_id,
                          "kind": design.kind, "parameters": dict(design.parameters),
                          "component_overrides": overrides,
                          "installation":workshop_recipe.by_source(
                              "installation", design, overrides, lambda: workshop_placement.for_design(design)),
                          "parts": len(design.parts), "families": sorted({p.family for p in design.parts if p.family}),
                          "materials": materials, "goods": goods,
                          "matter_source_note":matter_fabrication.source_note(
                              getattr(getattr(app,'room',None),'fabrication_record',None) or {},
                              workshop_library.rack_owner_id(app),{r['material']:r['kg'] for r in materials}),
                          "enough": all(m["enough"] for m in materials) and all(g["enough"] for g in goods),
                          **_shortfall(materials, goods),
                          "can_do": _can_do(record, made, design),
                          "capabilities": _capabilities(record, design),
                          "machines": workshop_machines.described(design)["says"] if record else None,
                          "readiness": workshop_recipe.assess(design, overrides, world_cell_m=world_cell_m)})

    # The tutorial uses the same recipe/readiness pipeline as other builds.
    from mcp import workshop_components
    import product_labels
    for label,recipe in product_labels.named_sources():
        design,_=workshop_components.design_from_spec(recipe)
        add(design,w.assembly(design.kind),name=label,source="built-in")
    for made in w.ASSEMBLIES:
        try:
            design = w.assemble(made.name, design_id=made.name)
            add(design, made, name=made.name, source="built-in")
            if made.name in product_labels.RECOMMENDED_OVER:
                templates[-1]["variant_of"] = product_labels.RECOMMENDED_OVER[made.name]
        except Exception as failed:               # a template that will not assemble is listed as such
            templates.append({"name": made.name, "purpose": made.purpose, "problem": str(failed)[:160]})
    # A design saved by the Workshop assistant is a recipe too. Rebuild it from
    # source on every listing; old readiness and stock claims cannot go stale.
    import workshop_api_core
    root = workshop_api_core._store(app)
    for saved in workshop_store.list_saved(root, limit=50):
        try:
            record, design = workshop_store.load(root, saved["design_id"])
            add(design, w.assembly(design.kind), name=record["label"], source="saved",
                saved_design_id=record["design_id"])
        except (OSError, ValueError, KeyError) as failed:
            templates.append({"name": saved.get("label") or saved["design_id"],
                              "source": "saved", "problem": str(failed)[:160]})
    room = getattr(getattr(app, "room", None), "spec", None) or {}
    # Mutable process choices live in machine runtime, separate from the
    # original declarations used to validate saved execution history.
    room=deepcopy(room)
    brains=getattr(getattr(app,'brains',None),'brains',{})
    for program in (room.get('machines') or {}).get('programs',[]):
        brain=brains.get(program.get('name'))
        if brain is not None and brain.routine is not None and brain.routine.kind=='process':
            program['routine']['recipe']=brain.routine.recipe
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
    holders = getattr(getattr(app, 'brains', None), 'goods', None)
    quantities = holders.holders() if holders is not None else {}
    piles = quantities.get('stockpiles', [])
    if holders is not None:
        deposits = quantities['deposits']
    import market
    traded = {lot[3]: lot[0] for lot in market.LOTS}
    programs = ((room.get('machines') or {}).get('programs') or [])
    import machine_routine
    def machine_process_options(brain):
        if brain is None or brain.routine is None: return set()
        return {r['name'] for r in machine_routine.process_options(room, brain.routine)}
    def acquire(substance, needed, path=(), remaining=None):
        # Facts and stoichiometric estimates, not a simulated future batch.
        # Authored recipes may contain cycles; bound each expanded line.
        remaining = remaining if remaining is not None else [128]
        if substance in path:
            return [{'kind':'blocked', 'reason':'Supply cycle: ' + ' → '.join((*path, substance))}]
        if len(path) >= 6 or remaining[0] <= 0:
            return [{'kind':'blocked', 'reason':'Long supply chain · inspect World processes'}]
        remaining[0] -= 1
        routes = []
        for pile in piles:
            kg = pile['holds_kg'].get(substance, 0)
            if kg <= 0 or pile.get('rack'): continue
            input_to = [p['name'] for p in programs if (p.get('routine') or {}).get('intake') == pile['name']]
            routes.append({'kind':'pile', 'name':pile['name'], 'at_m':pile['at_m'],
                           'available_kg':kg, 'input_to':input_to})
        for deposit in deposits:
            if deposit['substance'] != substance or deposit['left_kg'] <= 0: continue
            diggers = [p['name'] for p in programs if p.get('kind') == 'roam' and
                ((p.get('routine') or {}).get('kind') == 'mine-haul' or
                 any(step.get('do') == 'dig' for step in (p.get('routine') or {}).get('steps', [])))]
            routes.append({'kind':'deposit', **deposit, 'equipment':diggers})
        for process in room_recipes:
            yield_per_unit = float((process.get('out') or {}).get(substance, 0))
            if yield_per_unit <= 0: continue
            def input_lines(intake):
                lines = []
                for s, share in (process.get('in') or {}).items():
                    if share <= 0: continue
                    target = needed * share / yield_per_unit
                    have = intake.get('holds_kg', {}).get(s, 0)
                    gap = max(0., target - have)
                    lines.append({'substance':s, 'share':share, 'kg':target,
                        'held_kg':have, 'short_kg':gap, 'supply':True,
                        'acquisition':acquire(s, gap, (*path, substance), remaining)})
                return lines
            machines = []
            for program in programs:
                routine = program.get('routine') or {}
                # A machine running another recipe it can also run is a source
                # too: the furnace that smelts copper melts glass once the
                # player selects Melt Glass on it (machine_process).
                switch = None
                if routine.get('recipe') != process['name']:
                    brain = brains.get(program.get('name'))
                    able = machine_process_options(brain)
                    if process['name'] not in able: continue
                    switch = process['name']
                intake = next((p for p in piles if p['name'] == routine.get('intake')), {})
                machines.append({'name':program['name'], 'body':program.get('body'),
                    'intake':routine.get('intake'), 'output':routine.get('output'),
                    'select_recipe':switch, 'inputs':input_lines(intake)})
            routes.append({'kind':'process', 'name':process['name'], 'inputs':process.get('in') or {},
                           'machines':machines, 'input_supplies':input_lines({}) if not machines else []})
        if substance in traded: routes.append({'kind':'market', 'offer_id':traded[substance]})
        return routes
    for template in templates:
        for line in [*template.get('materials', []), *template.get('goods', [])]:
            line['acquisition'] = acquire(line.get('material') or line.get('substance'), line.get('short_kg', 0))
    return {"templates": templates, "room_recipes": room_recipes, "deposits": deposits, "stockpiles": piles,
            "goods_per": {k: {"substance": v[0], "per": v[1], "rate": v[2], "least_kg": v[3]}
                          for k, v in workshop_library.GOODS_PER.items()}}


def _shortfall(materials: list[dict[str, Any]], goods: list[dict[str, Any]]) -> dict[str, Any]:
    """How much of what a recipe asks for you have not got, as a share.

    The owner asked for "how much is missing like 20%". `enough` alone made a
    recipe you have 99% of look the same as one you have none of.

    By MASS over every line, not by counting lines: a recipe wanting 80 kg of
    iron and 20 g of wire is not half done because you have the wire. A line
    you have more than enough of counts as met and no more -- a mountain of
    oak does not make up for having no copper.
    """
    wants = 0.0
    short = 0.0
    missing: list[dict[str, Any]] = []
    for line in [*materials, *goods]:
        asked = float(line.get("kg") or 0.0)
        have = float(line.get("held_kg") or 0.0)
        if asked <= 0.0:
            continue
        wants += asked
        gap = max(0.0, asked - have)
        # Per line too, so a tag can say which one is holding it up.
        line["short_kg"] = gap
        if gap > 0.0:
            short += gap
            missing.append({"what": line.get("material") or line.get("substance"),
                            "short_kg": gap,
                            "share": round(gap / asked, 4)})
    share = (short / wants) if wants > 0.0 else 0.0
    missing.sort(key=lambda m: -m["short_kg"])
    return {"short_share": round(share, 4),
            "short_kg": round(short, 3),
            "wants_kg": round(wants, 3),
            "missing": missing}


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
    if getattr(app,"world_id",None):
        import learning_routes
        import world_access
        with world_access.state_lock(app):
            learning_routes.resolve(app,registry,techniques)
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
