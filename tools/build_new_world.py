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

import json
import math
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "playground"), str(ROOT / "tools")]

import build_explore_world as grounds   # noqa: E402
import build_mine_room as mine          # noqa: E402
import build_rover_room as rover_room   # noqa: E402
import fracture_lab                     # noqa: E402
import live_session                     # noqa: E402
import machine_goods                    # noqa: E402
import machine_routine                  # noqa: E402
import machine_senses                   # noqa: E402
import rigid_assembly                   # noqa: E402
import world_seed as ws                 # noqa: E402

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
#: The seed a new game starts from until somebody asks for another. The
#: generator re-seeds past a bad roll on its own, so this is where it starts
#: looking and not a promise that this one works.
SEED = 1


def compose(ground: dict, world: dict) -> dict:
    """The valley, the generated goods, and the two machines standing in it.

    The rover room's own composer is used for the rover, because it knows how
    to seat one on a slope so that all four wheels and the caster touch --
    which is a page of arithmetic nobody should write twice. It is told where
    to stand by MOVING ITS CONSTANTS, which is blunt but honest: they are a
    script's layout and this script wants a different layout. The valley's
    terrain replaces the basin's for the same reason.
    """
    goods = world["goods"]
    yard = {p["name"]: tuple(p["at_m"]) for p in goods["stockpiles"]}
    intake, rack = yard["smelter intake"], yard["workshop rack"]
    middle = ((intake[0] + rack[0]) / 2.0, (intake[1] + rack[1]) / 2.0)
    # The rover starts beside its own intake, on the far side from the smelter
    # that stands in the middle of the yard: the first thing it does is drive
    # away, and the last is come back. The post goes behind the rack for the
    # same reason -- the yard's middle belongs to the machine working in it.
    was = (rover_room.ROVER_AT, rover_room.POST_AT, rover_room.TERRAIN)
    rover_room.ROVER_AT = _clear_of(ground, intake, 2.0, away_from=middle)
    rover_room.POST_AT = _clear_of(ground, rack, 2.5, away_from=middle)
    rover_room.TERRAIN = {"generate": "valley"}
    try:
        spec = rover_room.compose(ground, "tests-dig")
    finally:
        rover_room.ROVER_AT, rover_room.POST_AT, rover_room.TERRAIN = was
    spec["water"] = dict(grounds.WATER)

    # The rover's job in the routine language: go to the nearest copper, dig
    # until the hopper is full, come back, tip it into the smelter's intake.
    vein = _nearest(goods["deposits"], "copper ore", intake)
    spec["machines"]["programs"][0]["routine"] = {
        "kind": "custom", "hopper_kg": 40.0,
        "places": {"vein": list(vein["at_m"]), "smelter intake": list(intake)},
        "steps": [
            {"do": "go_to", "args": {"place": "vein"}, "until": "arrived", "retries": 3},
            {"do": "dig", "args": {}, "until": "load_full", "repeat": True},
            {"do": "back_off", "args": {"for_s": 1.5}, "until": "asked_done"},
            {"do": "go_to", "args": {"place": "smelter intake"}, "until": "arrived", "retries": 3},
            {"do": "dump", "args": {"place": "smelter intake"}, "until": "load_empty"},
        ]}

    # The smelter: a block by its own intake, with a battery, a panel and the
    # program that works one recipe between two heaps.
    at = middle
    body, top = mine.block(ground, "smelter", at)
    spec["bodies"].append(body)
    still = mine.STILL
    spec["machines"]["stores"].append(
        {"name": "smelter battery", "body": "smelter", "capacity_j": still["capacity_j"],
         "charge_j": still["charge_j"], "voltage_v": still["voltage_v"]})
    spec["machines"]["panels"].append(
        {"name": "smelter panel", "body": "smelter", "store": "smelter battery",
         "at_mm": [round(1000.0 * v, 1) for v in top], "normal": [0.0, 1.0, 0.0],
         "area_m2": still["panel_area_m2"], "efficiency": still["efficiency"]})
    spec["machines"]["programs"].append(
        {"name": "smelter", "kind": "still", "body": "smelter", "store": "smelter battery",
         "routine": {"kind": "process", "recipe": "smelt copper", "intake": "smelter intake",
                     "output": "workshop rack", "batch_kg": 5.0}})

    spec["goods"] = json.loads(json.dumps(goods))
    return spec


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
                rack = goods.by_name("workshop rack") or {}
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
            rack = goods.by_name("workshop rack") or {}
            if float((rack.get("holds") or {}).get("copper", 0.0)) < 1.0:
                faults.append(
                    f"in {WATCH_S:.0f} s the rover and the smelter put no copper on the rack; "
                    + "; ".join(f"{n}: {r.summary()['doing']} ({', '.join(list(r.notes)[-2:])})"
                                for n, r in routines.items()))
            if not landed:
                faults.append("what reached the rack stockpile did not go onto the "
                              "Workshop's goods rack")
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
