#!/usr/bin/env python3
"""Compose a new game's world: the valley, a seeded map of what is in its
ground, and the two machines a person arrives with.

    BANJO_LIVE_ENGINE=.../banjo_live_world_run.exe python tools/build_new_world.py

Writes playground/rooms/new-game.json, which world_room serves as the
`new-game` scene (open it at /world?scene=new-game), and the proof that went
with it to docs/evidence/new-game-proof.json.

WHAT THIS IS FOR. `playground/world_seed.py` seeds a map and proves you can
get from the start to every material the Workshop spends. That proof is a
walk over a graph: it says the copper is reachable, not that a rover ever
reached it. This builder is the other half -- it stands the machines up in
the world the generator made, runs them, and REFUSES TO WRITE THE ROOM unless
copper wire actually lands on the Workshop's rack. A world that proves out on
paper and then does nothing is the failure this catches.

The two machines are the bootstrap (world_seed, "how the circle is broken"):
a rover that digs and hauls, and a smelter on its block that works a recipe.
Everything else in the game is built from what those two bring in.
"""
from __future__ import annotations

from copy import deepcopy
import json
import math
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "playground"), str(ROOT / "tools")]

import build_explore_world as grounds   # noqa: E402
import build_mine_room as mine          # noqa: E402
import workshop_install                 # noqa: E402
import build_rover_room as rover_room   # noqa: E402
import fracture_lab                     # noqa: E402
import live_session                     # noqa: E402
import machine_goods                    # noqa: E402
import machine_routine                  # noqa: E402
import machine_senses                   # noqa: E402
import rigid_assembly                   # noqa: E402
import world_seed as ws                 # noqa: E402
from mcp import workshop as w, workshop_components, workshop_machines  # noqa: E402

ROOMS = ROOT / "playground" / "rooms"
#: The proof is evidence, not a room, and it does not live among the rooms.
PROOF = ROOT / "docs" / "evidence" / "new-game-proof.json"
DT, PER_QUARTER = rover_room.DT, rover_room.PER_QUARTER
#: Long enough for a rover to drive to a seam, fill its hopper, drive back and
#: for the smelter to work a batch, with room for the drive being longer than
#: the mine room's because the valley is not laid out for convenience.
WATCH_S = 600.0

#: Where a person arrives in the valley: the hill in the middle, which is
#: where world_room.valley puts them and what the drive map is measured from.
ARRIVE_AT = (0.0, 0.0)
# An explicit starter hardware rating, not a material/geometry-derived claim.
# The yard already powers a 5 kW furnace and its other declared loads; 10 kW
# leaves a bounded charger margin. Saved worlds retain their existing ratings.
STARTER_GRID_MAX_POWER_W = 10000.0
#: A works machine's block: smaller than the mine room's 0.6 x 0.8 x 0.6,
#: because there are eight of them here and there is one there. At this
#: room's 50 mm cells the mine's block is 2,304 cells and eight of those are
#: 18,432 against the lane's cap of 16,000 -- the room was refused outright.
#: This one is 10 x 13 x 10 = 1,300, so eight come to 10,400. Seventeen per
#: cent shorter in each direction, which is nothing to look at and everything
#: to the budget: that is what a cube law does.
WORKS_BLOCK_M = (0.5, 0.65, 0.5)

#: WHAT EACH THING STANDING IN A NEW GAME WAS BUILT FROM: its name in the
#: world against the Workshop kind it is an instance of. Declared rather
#: than inferred from the name, because "solar farm" is not a kind and
#: "clay kiln" is not either -- both are processors and a rover is a rover.
#: The rule the owner set ("nothing in the world that is not buildable in
#: the workshop") is checked against this, so anything stood here without
#: saying what built it fails the check rather than passing quietly.
def built_from() -> dict:
    import world_seed as seed
    made = {"rover": "rover", "solar farm": "solar-array", "field pick": "field-pick"}
    for works in seed.WORKS:
        made[works.machine] = "processor"
        if works.stands: made[works.machine+' foundation'] = 'foundation-pad'
    return made


#: The seed a new game starts from until somebody asks for another. The
#: generator re-seeds past a bad roll on its own, so this is where it starts
#: looking and not a promise that this one works.
SEED = 1


def compose(ground: dict, world: dict, terrain_seed: int | None = None, *, installations=None) -> dict:
    """The valley, the generated goods, and the two machines standing in it.

    The rover room's own composer is used for the rover, because it knows how
    to seat one on a slope so that all four wheels and the caster touch --
    which is a page of arithmetic nobody should write twice. It is told where
    to stand by MOVING ITS CONSTANTS, which is blunt but honest: they are a
    script's layout and this script wants a different layout. The valley's
    terrain replaces the basin's for the same reason.
    """
    # A copy, because the loan below is written into its heaps and the
    # generator's own block is what the proof was made against.
    goods = json.loads(json.dumps(world["goods"]))
    spec_goods = goods
    yard = {p["name"]: tuple(p["at_m"]) for p in goods["stockpiles"]}
    intake, rack = yard["smelter intake"], yard["smelter output"]
    middle = ((intake[0] + rack[0]) / 2.0, (intake[1] + rack[1]) / 2.0)
    # Start on the working side of its intake. Choosing the opposite side of
    # the processor could strand the rover between the processor and riverbank.
    vein = _nearest(goods["deposits"], "copper ore", intake)
    hauling=_hauling_reservations(intake,vein['at_m'])
    was = (rover_room.ROVER_AT, rover_room.POST_AT, rover_room.TERRAIN)
    rover_room.ROVER_AT = _rover_start(ground,intake,vein['at_m'])
    rover_room.POST_AT = _clear_of(ground, rack, 2.5, away_from=middle)
    rover_room.TERRAIN = {"generate": grounds.valley(terrain_seed, ground.get("cell", 0.25))}
    if ground.get('surface') in ('cuts','columns'):rover_room.TERRAIN['surface']=ground['surface']
    try:
        here=rover_room.ROVER_AT
        yaw=math.atan2(vein['at_m'][0]-here[0],vein['at_m'][1]-here[1])
        spec = rover_room.compose(ground, "tests-dig",yaw)
    finally:
        rover_room.ROVER_AT, rover_room.POST_AT, rover_room.TERRAIN = was
    spec["water"] = dict(grounds.WATER)
    spec["sun"] = {"day_s":600.0, "noon_elevation_deg":60.0, "hour":8.0, "irradiance_w_m2":1000.0}
    spec["goods"] = spec_goods
    # NOTHING STANDS HERE THAT THE WORKSHOP CANNOT BUILD (the owner,
    # 2026-09-26). The rover room's composer leaves a concrete post in every
    # room it makes -- a charging post from before batteries charged off
    # solar panels, which they have since the owner's own call. It was the
    # last thing in this world nobody could build, and it is not needed.
    #
    # A MARKER STONE TAKES ITS PLACE, buried, because a world is opened from
    # its bodies and a room with none of them is not a room: with the post
    # simply deleted the lab fell back to its default 10 mm plate, which is
    # not a whole number of this room's 50 mm cells, and refused the world.
    # The valley's own scene does exactly this and for the same reason
    # (world_room.valley: "one marker stone, anchored and buried in the rock
    # under the valley"). Buried is the point -- it is not a thing in the
    # world that cannot be built, it is the world's own footing.
    spec["bodies"] = [b for b in spec["bodies"] if b.get("name") != "post"]
    mx, mz = ARRIVE_AT
    under = grounds.ground_under(ground, (mx - 0.05, mz - 0.05), (mx + 0.05, mz + 0.05))
    spec["bodies"].append(
        {"name": "marker stone", "shape": "box", "material": "concrete", "anchored": True,
         "size_mm": [100.0, 100.0, 100.0],
         "center_mm": [round(mx * 1000.0, 1), round((under - 1.0) * 1000.0, 1),
                       round(mz * 1000.0, 1)]})

    # A hand tool beside arrival, compiled from the same editable recipe that
    # Recipes offers. It is a bootstrap gift, not a grant awarded by learning.
    # Terrain support uses its full occupied footprint; native open still
    # validates the point and actual connected matter.
    tool_at = _clear_of(ground, ARRIVE_AT, 1.2)
    plan, design = a_lattice_thing(ground, "field-pick", "field pick", tool_at,
                                 cell_m=spec["cell_m"])
    spec["bodies"] += plan["bodies"]
    spec["tool_points"] = spec.get("tool_points", []) + [plan["tool"]["point"]]
    spec["interactions"] = spec.get("interactions", []) + [plan["tool"]["profile"]]
    from mcp import core_use, interaction_points
    spec["actions"] = spec.get("actions", []) + [core_use.installed(design, "field pick")]
    com = [sum((g[a]+.5)*spec["cell_m"] for g in plan["cells"])/len(plan["cells"])
           for a in range(3)]
    spec["interaction_points"] = spec.get("interaction_points", []) + [
        interaction_points.installed(design, "field pick", com)]

    # The rover's job in the routine language: go to the nearest copper, dig
    # until the hopper is full, come back, tip it into the smelter's intake.
    vein = _nearest(goods["deposits"], "copper ore", intake)
    spec["machines"]["programs"][0]["routine"] = {
        "kind": "custom", "hopper_kg": 40.0,
        "places": {"vein": list(vein["at_m"]), "smelter intake": list(intake)},
        "steps": [
            {"do": "go_to", "args": {"place": "vein", "stop_at_m":2.0}, "until": "arrived", "retries": 3},
            {"do": "dig", "args": {"place":"vein"}, "until": "load_full", "repeat": True},
            {"do": "back_off", "args": {"for_s": 1.5}, "until": "asked_done"},
            {"do": "go_to", "args": {"place": "smelter intake"}, "until": "arrived", "retries": 3},
            {"do": "dump", "args": {"place": "smelter intake"}, "until": "load_empty"},
        ]}

    # EVERY WORKS GETS ITS YARD; TWO OF THEM GET A MACHINE. Each works has
    # its two heaps laid out and its intake charged, and the smelter and the
    # mill are stood in theirs. The other six yards wait with their ore
    # beside them for a machine you build.
    #
    # The ladder is still reachable and is reached a better way. Six of its
    # nine rungs are learned by WATCHING a machine work, and that still
    # happens -- you build the kiln, you run it, you learn firing. What you
    # no longer get is six techniques handed over by a world that stood the
    # machines for you. The bootstrap holds because a furnace is not its
    # recipe: the starting smelter's chamber reaches 1687 C, so it will smelt
    # iron at 1538 as readily as copper if that is what you feed it.
    heaps = {p["name"]: p for p in goods["stockpiles"]}

    grid_programs=[];grid_panels=[]

    for works in ws.WORKS:
        name = works.machine
        intake_name, output_name = ws.heaps_of(works)
        if intake_name not in heaps or output_name not in heaps:
            continue                      # the generator found no ground for it
        # ITS LOAN goes on the intake whether or not a machine stands over
        # it, so a yard you build into has its first few batches waiting.
        # Read off the recipe, in the proportions it takes: charging one
        # named substance gave the concrete mixer 10 kg of cement and no
        # sand, and mixing concrete takes 0.15 of one to 0.85 of the other,
        # so it sat on a full heap and made nothing. Every other recipe here
        # has a single input, which is why that showed up exactly once.
        #
        # The generator keeps this off the goods block on purpose -- a charge
        # is not a supply, and a proof that counted it said you could reach
        # everything without ever digging.
        takes = ws.CHAIN_BY_NAME[works.recipe].takes
        whole = sum(takes.values()) or 1.0
        if works.charge_kg > 0:
            holds = heaps[intake_name].setdefault("holds", {})
            for substance, share in takes.items():
                holds[substance] = round(works.charge_kg * share / whole, 3)
        if not works.stands:
            continue                      # its yard is laid out; you build the machine
        # BESIDE THE LINE BETWEEN ITS TWO HEAPS, never on it. Stood at the
        # midpoint a machine is exactly what anything driving from one heap to
        # the other runs into: the rover came back with a full hopper, met
        # 600 mm of concrete nose-first, and sat against it for 180 seconds
        # re-issuing the same order, because go_to steers straight at where it
        # is going and knows nothing of what is between. A metre and a quarter
        # to the side still reaches both heaps -- 1.95 m to each against
        # machine_goods' 2 m of reach past their 0.8 m edge.
        one, two = heaps[intake_name]["at_m"], heaps[output_name]["at_m"]
        mid = ((one[0] + two[0]) / 2.0, (one[1] + two[1]) / 2.0)
        span = math.hypot(two[0] - one[0], two[1] - one[1]) or 1.0
        side = (-(two[1] - one[1]) / span, (two[0] - one[0]) / span)
        beside = [(mid[0] + s * 1.25 * side[0], mid[1] + s * 1.25 * side[1]) for s in (1.0, -1.0)]
        dry = [p for p in beside if not ws.wet_near(ground, p[0], p[1], 0.8)]
        at = min(dry or beside, key=lambda p: ws.flatness(ground, p[0], p[1], 0.8))
        bodies, pins, made = a_works(
            ground, name, at,
            {"kind": "process", "recipe": works.recipe, "intake": intake_name,
             "output": output_name, "batch_kg": 5.0}, reserved=_standing_footprints(spec)+hauling,
            installations=installations, service_regions=[(heaps[n]['at_m'], machine_goods.REACH_M +
                              float(heaps[n].get('radius_m',1.))) for n in (intake_name,output_name)])
        # Its names kept apart from every other machine's, as the install gate
        # keeps them: eight processors all call their battery "battery", and
        # six furnaces all call their chamber "chamber". The same two helpers
        # the bench's own install path uses, so a machine stood here and a
        # machine built by hand land in the room the same way.
        made = workshop_install._named_apart(workshop_install.standing_names(spec), made)
        # ON THE FARM'S STORE, not its own. Its own battery is still built --
        # it is part of the processor the Workshop makes -- and it holds
        # nothing, which is the honest state of it: the engine has no way to
        # move charge from one store to another, so either the design wants a
        # variant with no battery or the engine wants a wire between stores.
        # Both are worth doing and neither is this change.
        grid_programs.extend(made.get("programs") or [])
        grid_panels.extend(made.get("panels") or [])
        # A FURNACE'S CHAMBER IS NOT MACHINERY: it is the space its lining
        # encloses, so it goes to the room as a gas region for the thermal
        # network to heat and leak. Taken out before the machines are merged,
        # because `machines` holds no such key.
        made = workshop_install.chambers_into(spec, made)
        spec["precise_rigid_bodies"] += bodies
        spec["joints"] += pins
        for key in ("stores", "motors", "panels", "controls", "programs"):
            spec["machines"][key] = spec["machines"].get(key, []) + list(made.get(key) or [])

    # Place service-bound processors first, then the yard power and camp light. The owner,
    # 2026-09-26: "we can add a solar farm next to these machines and also
    # provide battery charging that way for all devices."
    #
    # It stands clear of the yard's own heaps so nothing drives into it, and
    # every machine below is wired to ITS store rather than the one each
    # carries. There is no store-to-store transfer in the engine -- a panel
    # charges a store and that is all -- so one shared store is what "all
    # devices" can mean, and every panel in the yard charges it.
    farm_at = _clear_of(ground, middle, 4.0, away_from=intake)
    farm_bodies, farm_pins, farm_made, _ = a_built_thing(
        ground, "solar-array", "solar farm", farm_at,
        {"max_power_w":STARTER_GRID_MAX_POWER_W},reserved=_standing_footprints(spec)+hauling)
    farm_made = workshop_install._named_apart(spec["machines"], farm_made)
    spec["precise_rigid_bodies"] += farm_bodies
    spec["joints"] += farm_pins
    for key in ("stores", "motors", "panels", "controls", "programs"):
        spec["machines"][key] = spec["machines"].get(key, []) + list(farm_made.get(key) or [])
    the_grid = (farm_made.get("stores") or [{}])[0].get("name")

    # One buildable camp fitting. Native electrical losses and store demand
    # determine its light; the host controller only switches at dusk/dawn.
    lamp_at = _clear_of(ground, ARRIVE_AT, 2.5)
    light_bodies, light_pins, light_made, _ = a_built_thing(
        ground, "mine-lamp", "camp light", lamp_at, reserved=_standing_footprints(spec)+hauling,
        installations=installations)
    light_made = workshop_install._named_apart(workshop_install.standing_names(spec), light_made)
    for lamp in light_made.get("lamps", []):
        lamp["store"] = the_grid
        lamp["auto_night"] = True
    spec["precise_rigid_bodies"] += light_bodies
    spec["joints"] += light_pins
    for key in ("stores", "motors", "panels", "controls", "programs", "lamps"):
        spec["machines"][key] = spec["machines"].get(key, []) + list(light_made.get(key) or [])

    if the_grid:
        for program in grid_programs:program["store"]=the_grid
        for panel in grid_panels:panel["store"]=the_grid

    # BOTH MACHINES ARE RUNNING WHEN THE ROOM OPENS. A program that does not
    # say `power` opens stopped and waits to be switched on by hand, which is
    # right for a test room and wrong for a new game: the point of the world
    # clock is that you come back and find work has been done, and a rover
    # that was never turned on has done none. live_session._power runs a
    # program that asks for it, at open.
    for program in spec["machines"]["programs"]:
        program["power"] = True

    return spec


def a_lattice_thing(ground: dict, kind: str, name: str, at: tuple[float, float],
                    *, cell_m: float, parameters: dict | None = None) -> tuple[dict, Any]:
    """A fixed Workshop solid, using the live installation's occupied compiler."""
    design = w.assemble(kind, design_id=name, parameters=dict(parameters or {}))
    candidate = workshop_install.recipe_of(design, design.lineage.get("component_overrides", {}))
    design, overrides = workshop_components.design_from_spec(candidate)
    plan = workshop_install.fixed_lattice_plan(design, overrides, root=name,
        cell_m=cell_m, position_m=at, floor_of=lambda b: grounds.ground_under(
            ground, (b[0][0], b[0][2]), (b[1][0], b[1][2])))
    return plan, design


def _standing_footprints(spec):
    return [(lo,hi) for _,lo,hi in rigid_assembly.footprint(
        {'bodies':spec.get('precise_rigid_bodies') or []})]


def _rover_start(ground,intake,vein):
    """An authored starting pose on the working approach, with clear probes."""
    bearing=math.atan2(vein[0]-intake[0],vein[1]-intake[1])
    candidates=[];surface=grounds.surface_at;step=ground['cell']/2
    for offset in (0.,15.,-15.,30.,-30.):
        a=bearing+math.radians(offset)
        for distance in (2.5,3.,2.,3.5):
            x,z=intake[0]+distance*math.sin(a),intake[1]+distance*math.cos(a)
            if ws.wet_near(ground,x,z,.8):continue
            yaw=math.atan2(vein[0]-x,vein[1]-z);c,s=math.cos(yaw),math.sin(yaw)
            h=surface(ground,x,z)
            gx=(surface(ground,x+step,z)-surface(ground,x-step,z))/(2*step)
            gz=(surface(ground,x,z+step)-surface(ground,x,z-step))/(2*step)
            safe=True
            for ox,_,oz in (*rover_room.SENSORS_LOCAL_M,*rover_room.REAR_SENSORS_LOCAL_M):
                dx=ox*c+oz*s;dz=-ox*s+oz*c
                if ws.wet_near(ground,x+dx,z+dz,.1) or abs(h+gx*dx+gz*dz-surface(ground,x+dx,z+dz))>.10:
                    safe=False;break
            if safe:candidates.append((abs(offset)*.01+ws.flatness(ground,x,z,.8),(x,z)))
    if not candidates:raise ValueError('No dry rover starting approach has clear ground probes')
    return min(candidates)[1]


def _hauling_reservations(intake,vein):
    """Keep starter assemblies outside the first haul's working corridor.

    These are placement reservations, not terrain edits or a traversal proof.
    The 1 m half width plus the placement's 0.35 m gap leaves space around the
    stock rover's 0.675 m occupied radius for turning and braking.
    """
    length=math.hypot(vein[0]-intake[0],vein[1]-intake[1])
    if length<.01:return []
    direction=((vein[0]-intake[0])/length,(vein[1]-intake[1])/length)
    # The rover stops within the receiving region and beside the dig, rather
    # than driving through the processor or onto the excavated deposit centre.
    start=[intake[a]+direction[a]*min(2.5,length*.3) for a in range(2)]
    end=[vein[a]-direction[a]*min(1.5,length*.3) for a in range(2)]
    steps=max(1,math.ceil(math.dist(start,end)/.5))
    return [([x-1.,z-1.],[x+1.,z+1.]) for x,z in
            ((start[0]+(end[0]-start[0])*k/steps,
              start[1]+(end[1]-start[1])*k/steps) for k in range(steps+1))]


def _wet_footprint(ground,lo,hi):
    """Check the sampled terrain beneath this part's rectangular projection."""
    cell=ground['cell']
    i0=math.floor((lo[0]-ground['x0'])/cell);i1=math.ceil((hi[0]-ground['x0'])/cell)
    j0=math.floor((lo[1]-ground['z0'])/cell);j1=math.ceil((hi[1]-ground['z0'])/cell)
    wet=ground.get('wet') or set()
    return any((i,j) in wet for i in range(i0,i1+1) for j in range(j0,j1+1))


def _placement(ground, artifact, preferred, reserved, service_regions):
    """Reserve actual compiled parts; retain reach of each served stockpile."""
    candidates=[preferred]
    for radius in (.5,1.,1.5,2.,2.5,3.,4.,5.,6.):
        candidates.extend((preferred[0]+radius*math.cos(k*math.tau/24),
                           preferred[1]+radius*math.sin(k*math.tau/24)) for k in range(24))
    for x,z in candidates:
        flat=rigid_assembly.placed(artifact,[x,0.,z],0.,0.)
        root=next(b for b in flat['bodies'] if b['name']==artifact['root'])['_centre_m']
        if any(math.hypot(root[0]-p[0],root[2]-p[1])>reach-.2 for p,reach in service_regions):
            continue
        occupied=rigid_assembly.footprint(flat)
        if service_regions:
            occupied=[(low,[v-.1 for v in lo],[v+.1 for v in hi]) for low,lo,hi in occupied]
        if any(lo[0]<ground['x0'] or lo[1]<ground['z0'] or
               hi[0]>ground['x0']+(ground['nx']-1)*ground['cell'] or
               hi[1]>ground['z0']+(ground['nz']-1)*ground['cell'] for _,lo,hi in occupied):
            continue
        if any(_wet_footprint(ground,lo,hi) for _,lo,hi in occupied):
            continue
        if any(lo[0]<other_hi[0]+.35 and hi[0]>other_lo[0]-.35 and
               lo[1]<other_hi[1]+.35 and hi[1]>other_lo[1]-.35
               for _,lo,hi in occupied for other_lo,other_hi in reserved):
            continue
        return x,z
    raise ValueError(f"No dry placement keeps {artifact['root']} clear and its stockpiles within reach")


def a_built_thing(ground: dict, kind: str, name: str, at: tuple[float, float],
                  parameters: dict | None = None, *, reserved=None,
                  service_regions=(), installations=None) -> tuple[list[dict], list[dict], Any, Any]:
    """Any Workshop kind, stood on the ground where it goes.

    THE SAME PATH A PERSON'S BUILD TAKES: assemble the design, compile it to
    exact bodies, seat it on the highest ground under its whole footprint,
    and let workshop_machines read its stores, panels and programs off the
    design. Nothing here is made up for the world -- if the Workshop cannot
    build it, it cannot stand here either, which is the rule.
    """
    design = w.assemble(kind, design_id=name, parameters=dict(parameters or {}))
    candidate = {"kind": kind, "design_id": name, "parameters": dict(parameters or {}),
                 "component_overrides": design.lineage["component_overrides"]}
    design, overrides = workshop_components.design_from_spec(candidate)
    artifact = rigid_assembly.compile_design(design, overrides, root=name)
    if reserved is not None:
        at=_placement(ground,artifact,at,reserved,service_regions)
    x, z = at
    flat = rigid_assembly.placed(artifact, [x, 0.0, z], 0.0, 0.0)
    lift = max(grounds.ground_under(ground, lo, hi) - low
               for low, lo, hi in rigid_assembly.footprint(flat))
    foundation=[]
    if service_regions:
        foundation,lift = _foundation_for(ground,flat,name,installations=installations)
    stood = rigid_assembly.placed(artifact, [x, lift, z], 0.0, 0.0)
    origin = [x, lift, z]
    frame = (lambda p: [float(p[k]) + origin[k] for k in range(3)],
             lambda d: [float(v) for v in d])
    made = workshop_machines.installed(design, artifact["component_to_body"], frame, {})
    if installations is not None:
        installations.append({'status':'installed','design_id':design.design_id,'root_body':name,
            'component_to_body':dict(artifact['component_to_body']),'recipe':candidate,
            'presentation':{'label':name,'label_source':'generated-purpose'},
            'source':'Generated starter geometry'})
    return foundation+rigid_assembly.scene_bodies(stood), rigid_assembly.scene_joints(stood), made, design


def _foundation_for(ground,flat,name,*,installations=None):
    """A free, buildable platform with feet sized to actual terrain samples.

    The machine remains free on the platform. All mass/contact comes from the
    native compounds; no pose locking or friction override is applied. Exact
    rigid fixed joints currently have no failure law. This is starter geometry,
    not soil bearing/cement curing or a support-removal certification.
    """
    occupied=rigid_assembly.footprint(flat)
    lo=[min(row[1][a] for row in occupied)-.10 for a in range(2)]
    hi=[max(row[2][a] for row in occupied)+.10 for a in range(2)]
    width,depth=hi[0]-lo[0],hi[1]-lo[1]
    x,z=(lo[0]+hi[0])/2,(lo[1]+hi[1])/2
    section,thickness=.2,.1
    top=grounds.ground_under(ground,lo,hi)+thickness+.06
    parameters={'width_m':width,'depth_m':depth,'thickness_m':thickness,
                'footing_section_m':section,'material':'concrete'}
    for i,(sx,sz) in enumerate(((1,1),(-1,1),(1,-1),(-1,-1)),1):
        fx,fz=x+sx*(width-section)/2,z+sz*(depth-section)/2
        floor=grounds.ground_under(ground,(fx-section/2,fz-section/2),(fx+section/2,fz+section/2))
        parameters[f'footing_{i}_m']=top-thickness-floor
    design,overrides=workshop_components.design_from_spec({'kind':'foundation-pad',
        'design_id':name+' foundation','parameters':parameters})
    artifact=rigid_assembly.compile_design(design,overrides,root=name+' foundation')
    stood=rigid_assembly.placed(artifact,[x,top,z],0.,0.)
    if installations is not None:
        installations.append({'status':'installed','design_id':design.design_id,'root_body':name+' foundation',
            'component_to_body':dict(artifact['component_to_body']),
            'presentation':{'label':name+' foundation','label_source':'generated-purpose'},
            'recipe':{'kind':'foundation-pad','design_id':design.design_id,'parameters':parameters,
                      'component_overrides':deepcopy(overrides)},'source':'Generated starter geometry'})
    lowest=min(row[0] for row in occupied)
    return rigid_assembly.scene_bodies(stood),top-lowest


def a_works(ground: dict, name: str, at: tuple[float, float],
            routine: dict, *, reserved=None, service_regions=(), installations=None) -> tuple[list[dict], list[dict], dict]:
    """The machine that works this recipe, stood on the ground where it goes.

    WHICH MACHINE IS THE RECIPE'S TO SAY. A recipe with a temperature needs
    an inside to make hot, so it gets an electric furnace; cold work gets a
    processor, which is a deck on legs. Nothing here chooses by name or by a
    list kept in step by hand -- `needs_c` decides, so a recipe that gains or
    loses its heat moves to the other machine on its own.

    THE SAME PATH A PERSON'S BUILD TAKES: assemble the design, compile it to
    exact bodies, seat it on the highest ground under its whole footprint,
    and let workshop_machines read its battery, its panel and its program off
    the design. Nothing here is made up for the world -- if the Workshop
    cannot build it, it cannot stand here either, which is the rule.

    It is also what the cell budget wants. A plain box is latticed and the
    mine's block costs 2,304 cells at 50 mm; a compiled design is precise
    rigid bodies, which the lattice never sees.
    """
    recipe = str(routine.get("recipe") or "")
    needs_c = ws.CHAIN_BY_NAME[recipe].needs_c if recipe in ws.CHAIN_BY_NAME else 0.0
    kind = "electric-furnace" if needs_c > 0.0 else "processor"
    bodies, pins, made, _ = a_built_thing(ground, kind, name, at, {"recipe": recipe},
                                      reserved=reserved,service_regions=service_regions,installations=installations)
    for program in made.get("programs") or []:
        program["routine"] = dict(routine)
    return bodies, pins, made


def _nearest(deposits: list[dict], substance: str, to: tuple[float, float]) -> dict:
    here = [d for d in deposits if d["substance"] == substance]
    if not here:
        raise ValueError(f"the generated world has no {substance}, which the proof should have caught")
    return min(here, key=lambda d: math.dist(tuple(d["at_m"]), to))


def _clear_of(ground: dict, of: tuple[float, float], by: float,
              away_from: tuple[float, float] | None = None) -> tuple[float, float]:
    """A spot `by` metres from a heap, on the flattest side of it that is dry.

    Standing a machine ON its own stockpile is allowed by the goods ledger and
    looks like a mistake, so everything is set down beside its heap. With
    `away_from`, only the sides facing away from that point are considered --
    the flattest ground around the rack is toward the middle of the yard,
    which put the post 12 cm off the smelter's face and the rover 85 cm from
    it, close enough to be touching. The owner's rule is that nothing overlaps
    what is already there.
    """
    best, score = None, math.inf
    for turn in range(24):
        a = turn * math.tau / 24.0
        dx, dz = math.cos(a), math.sin(a)
        if away_from is not None:
            to = (away_from[0] - of[0], away_from[1] - of[1])
            if dx * to[0] + dz * to[1] > 0.0:      # this side faces the thing
                continue
        x, z = of[0] + by * dx, of[1] + by * dz
        if ws.wet_near(ground, x, z, 0.8):
            continue
        spread = ws.flatness(ground, x, z, 0.8)
        if spread < score:
            best, score = (round(x, 2), round(z, 2)), spread
    if best is None:
        raise ValueError(f"nowhere dry {by} m from {of} to stand anything")
    return best


def watch(engine: Path, validated: dict) -> list[str]:
    """Open the world and run it: does copper wire reach the rack?

    The generator's proof is a graph walk. This is the room, stepped, with the
    routines driving -- the only thing that can tell you the world it made is
    one somebody could play.
    """
    faults: list[str] = []
    landed: list[tuple[str, float]] = []
    goods = machine_goods.Goods(validated, on_rack=lambda s, kg: landed.append((s, kg)))
    with tempfile.TemporaryDirectory() as tmp:
        session = live_session.Session(engine, validated, Path(tmp))
        try:
            # Opened the way the playground opens a room: pins hung, machines
            # powered, the sun put up. Anything else is testing a world nobody
            # will ever be in.
            pins = validated.get("joints") or []
            hung = live_session.Live._hang(session, pins)
            made: dict = {}
            hung.update(live_session.Live._power(session, validated.get("machines") or {},
                                                 pins, made=made))
            hung.update(live_session.Live._sun(session, validated.get("sun")))
            for key in ("joint_problems", "machine_problems", "sun_problem"):
                value = hung.get(key)
                faults.extend(value if isinstance(value, list) else [value] if value else [])
            if faults:
                return faults
            routines = {name: machine_routine.Routine(name, machine_routine.declared_for(validated, name))
                        for name in made["programs"]}
            session.send(op="step", dt=DT, n=int(2.0 / DT))
            for seq, (name, program) in enumerate(made["programs"].items(), 1):
                session.send(op="run", program=program, sender="builder", seq=seq, power=True)

            log: list[str] = []
            wall, seconds = time.monotonic(), WATCH_S
            for tick in range(int(WATCH_S / (PER_QUARTER * DT))):
                reply = session.send(op="step", dt=DT, n=PER_QUARTER)
                machines = reply.get("machines") or {}
                t = float(reply.get("t", 0.0))
                for name, program in made["programs"].items():
                    said = next((q for q in machines.get("programs") or []
                                 if q.get("id") == program), None)
                    if said is None:
                        continue
                    ctx = machine_senses.Context(program=said, machines=machines,
                                                 bodies=reply.get("bodies"), ask=session.send,
                                                 routine=routines[name], t=t, goods=goods)
                    did = routines[name].tick(ctx)
                    if did is not None:
                        log.append(f"{t:6.1f} s  {name}: {did.get('did', '')}")
                rack = goods.by_name("smelter output") or {}
                if float((rack.get("holds") or {}).get("copper", 0.0)) >= 1.0:
                    seconds = (tick + 1) * PER_QUARTER * DT
                    break
            print(f"  ran the new world for {seconds:.0f} s at "
                  f"{seconds / max(1e-9, time.monotonic() - wall):.0f}x realtime")
            for line in log[:40]:
                print("    " + line[:150])
            if len(log) > 40:
                print(f"    ... {len(log) - 40} more")
            for pile in goods.stockpiles:
                print(f"  {pile['name']}: "
                      + (", ".join(f"{v:.2f} kg {k}" for k, v in (pile.get("holds") or {}).items())
                         or "nothing"))
            vein = _nearest(goods.deposits, "copper ore", (0.0, 0.0))
            print(f"  {vein['name']}: {goods.reserve_kg(vein):.1f} kg of "
                  f"{vein['substance']} left of {vein['reserve_kg']:g}")
            rack = goods.by_name("smelter output") or {}
            if float((rack.get("holds") or {}).get("copper", 0.0)) < 1.0:
                faults.append(
                    f"in {WATCH_S:.0f} s the rover and the smelter put no copper on the rack; "
                    + "; ".join(f"{n}: {r.summary()['doing']} ({', '.join(list(r.notes)[-2:])})"
                                for n, r in routines.items()))
            if landed:
                faults.append("New-world output was automatically banked; it must await nearby collection")
        finally:
            session.close()
    return faults


def main() -> int:
    engine = os.environ.get("BANJO_LIVE_ENGINE")
    if not engine or not Path(engine).is_file():
        print("Set BANJO_LIVE_ENGINE to a built banjo_live_world_run", file=sys.stderr)
        return 2
    engine = Path(engine)

    print("Reading the valley's ground ...")
    ground = grounds.read_ground(engine)
    print(f"  {ground['nx']}x{ground['nz']} at {ground['cell']} m, "
          f"{len(ground['wet'])} samples under water")

    print(f"Seeding a world from {SEED} and proving it ...")
    world = ws.new_world(ground, SEED, start_xz=ARRIVE_AT)
    proof = world["proof"]
    print(f"  seed {proof['seed']} after {proof['tries']} "
          f"{'try' if proof['tries'] == 1 else 'tries'}")
    for d in world["goods"]["deposits"]:
        print(f"    {d['name']:22} at {d['at_m'][0]:+7.1f},{d['at_m'][1]:+7.1f}  "
              f"r{d['radius_m']:.1f}  grade {d['grade']}  {d['reserve_kg']:.0f} kg")
    for s in world["goods"]["stockpiles"]:
        print(f"    {s['name']:22} at {s['at_m'][0]:+7.1f},{s['at_m'][1]:+7.1f}  "
              f"{s.get('holds') or ('the Workshop rack' if s.get('rack') else '')}")
    for substance, route in proof["can make it"]["reached"].items():
        print(f"    {substance:18} {route}")
    for substance, why in proof["can make it"]["not in the world"].items():
        print(f"    {substance:18} NOT IN THE WORLD: {why}")

    print("Standing the two machines a person starts with ...")
    spec = compose(ground, world)
    validated = fracture_lab.validate(spec)
    print(f"  {len(validated['machines']['programs'])} programs, "
          f"{len(validated['goods']['stockpiles'])} stockpiles, "
          f"{len(validated['goods']['recipes'])} recipes")

    print("Opening it and running the first chain ...")
    faults = watch(engine, json.loads(json.dumps(validated)))
    if faults:
        for fault in faults:
            print(f"  REFUSED: {fault}", file=sys.stderr)
        return 1

    # The SPEC, not what validate() gave back. Validation adds its own working
    # fields -- cells, cells_per_axis, requested_plate_m, seated, snapped --
    # and reading a room back in with them on it is refused: "Unknown fracture
    # lab fields". The other builders write the spec for the same reason.
    ROOMS.mkdir(parents=True, exist_ok=True)
    (ROOMS / "new-game.json").write_text(json.dumps(spec, indent=1, sort_keys=True),
                                         encoding="utf-8", newline="\n")
    PROOF.parent.mkdir(parents=True, exist_ok=True)
    PROOF.write_text(json.dumps(proof, indent=2), encoding="utf-8")
    print(f"Wrote {ROOMS / 'new-game.json'} and {PROOF}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
