"""Resolve the curated learning graph against the current native world.

The abstract graph describes prerequisites. This adapter describes where an
implemented action is available now; neither names nor registry starting gifts
are evidence that equipment exists in this world.
"""
from __future__ import annotations

from typing import Any
import math
from mcp import progression, interaction_profiles, resource_previews
import machine_witness
import workshop_library
import inventory_room
import player_world


def _dry_ground(app, at, use=None, pose=None):
    """Nearby native columns, not an invented usable resource or path proof."""
    if not at or not getattr(app.live,'session',None): return None
    offsets=[(0,0),(1,0),(-1,0),(0,1),(0,-1)]
    if use and pose and pose.get('eyes_m'):
        at=pose['eyes_m']
        least,most=use['reach_m']
        face=pose.get('facing') or [0,0,1]
        heading=math.atan2(face[0],face[2])
        # Prefer a target already inside this tool's real reach, in front of
        # the player's current pose. The carried body's centre can be at the
        # feet and is not where the person should be told to dig.
        offsets=[(radius*math.sin(heading+angle),radius*math.cos(heading+angle))
                 for radius in ((least+most)/2,least+(most-least)/4,most+1.)
                 for angle in (0,math.pi/4,-math.pi/4,math.pi/2,-math.pi/2,
                               3*math.pi/4,-3*math.pi/4,math.pi)]
    session=app.live.session
    spec=getattr(session,'room_spec',None) or getattr(getattr(app,'room',None),'spec',None) or {}
    terrain=spec.get('terrain') or {}
    grid=((session.state or {}).get('terrain') or {}).get('grid') or {}
    cell=float(grid.get('cell_m',(terrain.get('generate') or {}).get('cell_m',.25)))
    for dx,dz in offsets:
        x,z=at[0]+dx,at[2]+dz
        if terrain.get('surface')=='columns' and all(k in grid for k in ('x0_m','z0_m')):
            # Advice points into the cell, rather than at a boundary where
            # the lateral working motion immediately leaves the selected
            # column. Actual pointer/touch targeting remains unsnapped.
            x,z=(float(grid[key])+math.floor((v-float(grid[key]))/cell+.5)*cell
                 for v,key in ((x,'x0_m'),(z,'z0_m')))
        survey=app.live.act({'session':session.id,'op':'survey','at':[x,z]}).get('survey') or {}
        if (survey.get('on_the_ground') and (survey.get('water') or {}).get('depth_m',0)<=.005
            and sum(float(survey.get(k,0)) for k in ('soil_m','sand_m','loose_soil_m'))>=.01
            and (not use or resource_previews.ground_tool(survey,use)['materials'])):
            return [survey['x_m'],survey['ground_m'],survey['z_m']]
    return None


def _tool_ground(app,owner,where,at,profile):
    use=interaction_profiles.tool_use(profile)
    pose=((player_world.records(app).get(owner) or {}).get('pose') or {}) if where in ('right','left','stowed') else None
    return _dry_ground(app,at,use,pose)


def tool_location(app, owner, name):
    """Current ordinary tool action, independent of whether its skill is known."""
    session=getattr(app.live,'session',None)
    if session is None:return None
    profile=next((p for p in app.room.spec.get('interactions',[]) if
                  p.get('template')=='swing-and-lever' and p.get('tool')==name),None)
    thing=inventory_room.item_holding(app,name)
    if profile is None or thing is None:return None
    where=inventory_room.inventory_of(app,owner).where(thing['id'])
    if any(ident!=owner and inventory_room.inventory_of(app,ident).where(thing['id'])!='world'
           for ident in player_world.records(app)):return None
    native=next((b for b in (session.state or {}).get('bodies',[]) if b['name']==name),{})
    at=(native.get('position_m') if where!='stowed' else None) or (
        (player_world.records(app).get(owner) or {}).get('pose') or {}).get('eyes_m')
    if at is None:return None
    return {'body':name,'where':where,'at_m':at,'ground_at_m':_tool_ground(app,owner,where,at,profile),
            'reach_m':interaction_profiles.tool_use(profile)['reach_m']}


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
        if profile.get('template')!='swing-and-lever': continue
        design = progression.design_of(registry, progression.construction_of(app.room.spec,profile))
        body = native.get(profile.get('tool'))
        thing=inventory_room.item_holding(app,profile.get('tool'))
        owners={ident:inventory_room.inventory_of(app,ident).where(thing['id'])
                for ident in player_world.records(app)} if thing and getattr(app,'world_id',None) else {}
        if any(ident!=owner and where!='world' for ident,where in owners.items()): continue
        where=owners.get(owner,'world')
        in_bag=where=='stowed'
        if design and ((body and not body.get('fragment') and not body.get('parked')) or in_bag):
            at=(body or {}).get('position_m') or ((player_world.records(app).get(owner) or {}).get('pose') or {}).get('eyes_m')
            examples.setdefault(design.split('@')[0],[]).append({'body':profile['tool'],
                'at_m':at, 'where':where,'tab':'inventory' if in_bag else 'world',
                'ground_at_m':_tool_ground(app,owner,where,at,profile),
                'reach_m':interaction_profiles.tool_use(profile)['reach_m']})
    for technique in techniques:
        for route in technique.get("earned_by") or []:
            locations, missing = [], []
            for condition in route.get("all_of") or []:
                if condition.get('done'): continue
                design = registry.designs.get(condition.get("design")) or {}
                label = design.get("name") or condition.get("design")
                ground_use=((design.get('interaction') or {}).get('template')=='swing-and-lever'
                            and condition.get('test')=='loosens-soil')
                study=condition.get('found') or condition.get('test')=='study-example'
                if study or ground_use:
                    found = examples.get(condition.get("design")) or []
                    if found:
                        ready=[]
                        for example in found:
                            if ground_use and not example['ground_at_m']: continue
                            ready.append({**example,'action':'tool/use' if ground_use else 'inspect',
                                'label':'Gather dry ground' if ground_use else 'Study held tool',
                                'instruction':(f'Equip {label}. Aim at dry soil or sand; use it until material comes loose.' if ground_use
                                               else 'Take/equip this tool, then choose Study tool or Inspect.')})
                        locations.extend(ready)
                        if not ready: missing.append(f'No dry soil or sand surveyed near {label}')
                    else:
                        missing.append(f"Missing example: {label}")
                        processes = [registry.processes[c['process']]
                                     for r in (design.get('routes') or {}).get('any_of') or []
                                     for c in r.get('all_of') or []
                                     if c.get('process') in registry.processes]
                        if processes and all(not p.get('supported') for p in processes):
                            missing.append(f'Making {label} is not available yet. You cannot unlock it by collecting supplies.')
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
                        source_locations=[]
                        for source in sources:
                            p = next(p for p in app.room.spec["machines"]["programs"] if p["name"] == source["machine"])
                            intake = piles.get(p["routine"].get("intake")) or {}
                            holds = intake.get("holds") or {}
                            inputs = recipes[recipe].get("in") or {}
                            absent = [name for name, share in inputs.items() if share > 0 and holds.get(name,0) <= 0]
                            source_locations.append({**source, "body": p.get("body"),
                                "action": "watch-machine", "label": "Watch next batch",
                                "needs": absent, "intake": intake.get("name"),
                                "instruction": "Turn on; stay nearby and face it until a batch is saved."})
                        available=[l for l in source_locations if not l['needs']]
                        locations.extend(available or source_locations)
                        if not available:
                            missing.extend(f"{l['machine']} intake needs: {', '.join(l['needs'])}" for l in source_locations)
            route["locations"], route["world_missing"] = locations, list(dict.fromkeys(missing))
            route["world_ready"] = bool(route.get("done")) or bool(locations) and not missing
            if not route.get("done"):
                directions = [f"{l.get('machine') or l['body']} " +
                              (f"({l['at_m'][0]:.1f}, {l['at_m'][2]:.1f})" if l.get('at_m') else '(your bag)') + f": {l['label']}"
                              for l in locations]
                route["says"] = "; ".join(directions + route["world_missing"]) or "No supported action in this world"
        technique["graph_ready"] = technique.get("within_reach", False)
        technique["within_reach"] = technique["graph_ready"] and any(
            r["world_ready"] for r in technique.get("earned_by") or [])
        # ANY route earns the skill. A missing alternative is not a blocker
        # for an available route, and never revokes personal saved knowledge.
        technique["world_missing"] = ([] if technique.get('known') or any(
            r['world_ready'] for r in technique.get('earned_by') or []) else
            list(dict.fromkeys(m for r in technique.get("earned_by") or []
                               for m in r["world_missing"])))
        for opened in technique.get("opens") or []:
            design = registry.designs.get(opened["id"]) or {}
            recipe = (design.get("machine") or {}).get("recipe")
            sources = [m for m in equipment if m["recipe"] == recipe]
            opened["locations"] = [dict(l) for r in technique.get("earned_by") or []
                                   for l in r["locations"] if l.get("recipe") == recipe]
            if not opened['locations']:
                for source in sources:
                    program = next((p for p in (app.room.spec.get('machines') or {}).get('programs') or []
                                    if p['name'] == source['machine']), {})
                    if program.get('body'):
                        opened['locations'].append(dict(source, body=program['body'], tab='world'))
            unsupported = [registry.processes[c["process"]].get("name", c["process"])
                           for r in (design.get("routes") or {}).get("any_of") or []
                           for c in r.get("all_of") or [] if c.get("process") in registry.processes
                           and not registry.processes[c["process"]].get("supported")]
            opened["availability"] = ("Equipment present" if sources else
                "Process unavailable: " + ", ".join(unsupported) if unsupported else "Equipment missing")
