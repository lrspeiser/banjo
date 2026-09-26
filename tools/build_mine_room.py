"""Compose the mine: raw materials into finished goods (docs/machine-world.md,
"Raw materials into finished goods").

    BANJO_LIVE_ENGINE=.../banjo_live_world_run.exe python tools/build_mine_room.py

Writes playground/rooms/tests-mine.json, which world_room serves as the
`tests-mine` scene. Open it at /world?scene=tests-mine and turn the four
machines on from the Room tab.

Four machines in the basin, and the room's account of goods between them:

  * A copper vein: a patch of ground by the dig site where three tenths of
    what a scoop brings up is copper ore, 400 kg of it in all.
  * The rover (tools/build_rover_room.py), with a routine of its own steps
    written in the routine language rather than a named kind: go to the
    vein, dig until its hopper is full, back off, go to the smelter's intake,
    dump there -- the soil onto the ground, the ore onto the intake stockpile.
  * The smelter: a machine that goes nowhere (a "still" program), a concrete
    block with a battery and a solar panel, working its intake into its
    output by the room's recipe "smelt copper": a kilogram of ore into 0.3 kg
    of copper, 2 kJ and 2 s a kilogram.
  * The drone (mcp/workshop_products, the Workshop's template), hauling:
    take what is on the smelter's output, fly it to the mill's intake, put it
    there.
  * The mill: another still machine, working copper into copper wire by
    "draw wire", onto a stockpile that is the Workshop's rack: what lands
    there goes onto the Workshop's goods rack, and a rover made on the bench
    takes 2.3 kg of copper wire and a kilogram of copper of it.

Before it writes the room, this opens it in the engine, turns everything on
and runs every routine as the server does before each step the page takes,
and refuses to write the room unless copper wire has reached the rack within
WATCH_S of the world's time, with the ground's carried account back at
nothing and every battery's account closed. Nothing is hand-edited in the
JSON.
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
import build_rover_room as rover_room   # noqa: E402
import fracture_lab                     # noqa: E402
import live_session                     # noqa: E402
import machine_goods                    # noqa: E402
import machine_routine                  # noqa: E402
import machine_senses                   # noqa: E402
import rigid_assembly                   # noqa: E402
import workshop_install                 # noqa: E402
import mcp                              # noqa: E402,F401
from mcp import workshop as w, workshop_components, workshop_machines  # noqa: E402

ROOMS = ROOT / "playground" / "rooms"
DT = rover_room.DT
PER_QUARTER = rover_room.PER_QUARTER
WATCH_S = 420.0

# Where everything stands, in the basin's metres (the lake's middle is the
# origin; the shore is 4.85 m out; the rover starts at (0, -9) facing +z).
VEIN_AT = (2.0, -6.5)
SMELTER_AT = (-3.0, -9.5)
SMELTER_INTAKE_AT = (-3.0, -8.0)
SMELTER_OUTPUT_AT = (-4.5, -9.5)
DRONE_AT = (-6.0, -9.0)
MILL_AT = (-6.0, -13.0)
MILL_INTAKE_AT = (-6.0, -11.5)
RACK_AT = (-6.0, -14.5)
BLOCK_M = (0.6, 0.8, 0.6)          # a still machine's concrete block: x, y, z

GOODS = {
    "deposits": [{"name": "copper vein", "substance": "copper ore", "at_m": list(VEIN_AT), "radius_m": 3.0,
                  "grade": 0.3, "reserve_kg": 400.0}],
    "stockpiles": [{"name": "smelter intake", "at_m": list(SMELTER_INTAKE_AT), "radius_m": 1.0},
                   {"name": "smelter output", "at_m": list(SMELTER_OUTPUT_AT), "radius_m": 1.0},
                   {"name": "mill intake", "at_m": list(MILL_INTAKE_AT), "radius_m": 1.0},
                   {"name": "workshop rack", "at_m": list(RACK_AT), "radius_m": 1.0, "rack": True}],
    "recipes": [{"name": "smelt copper", "in": {"copper ore": 1.0}, "out": {"copper": 0.3},
                 "work_j_per_kg": 2000.0, "s_per_kg": 2.0},
                {"name": "draw wire", "in": {"copper": 1.0}, "out": {"copper wire": 0.98},
                 "work_j_per_kg": 500.0, "s_per_kg": 1.0}],
}
# The rover's job, in the routine language: its own steps.
ROVER_ROUTINE = {
    "kind": "custom", "hopper_kg": 40.0,
    "places": {"vein": list(VEIN_AT), "smelter intake": list(SMELTER_INTAKE_AT)},
    "steps": [
        {"do": "go_to", "args": {"place": "vein"}, "until": "arrived", "retries": 3},
        {"do": "dig", "args": {}, "until": "load_full", "repeat": True},
        {"do": "back_off", "args": {"for_s": 1.5}, "until": "asked_done"},
        {"do": "go_to", "args": {"place": "smelter intake"}, "until": "arrived", "retries": 3},
        {"do": "dump", "args": {"place": "smelter intake"}, "until": "load_empty"},
    ],
}
DRONE_ROUTINE = {"kind": "haul", "hopper_kg": 20.0,
                 "places": {"source": list(SMELTER_OUTPUT_AT), "destination": list(MILL_INTAKE_AT)}}
STILL = {"capacity_j": 2.0e6, "charge_j": 2.0e6, "voltage_v": 48.0, "panel_area_m2": 0.3, "efficiency": 0.2}


def block(ground: dict, name: str, at: tuple[float, float]) -> tuple[dict, list[float]]:
    """A still machine's concrete block standing on the ground: the body and
    the middle of its top, for its panel."""
    x, z = at
    hx, hz = BLOCK_M[0] / 2.0, BLOCK_M[2] / 2.0
    base = grounds.ground_under(ground, (x - hx, z - hz), (x + hx, z + hz))
    centre = [x, base + BLOCK_M[1] / 2.0, z]
    body = {"name": name, "shape": "box", "material": "concrete", "anchored": True,
            "size_mm": [round(1000.0 * v, 1) for v in BLOCK_M],
            "center_mm": [round(1000.0 * v, 1) for v in centre]}
    return body, [x, base + BLOCK_M[1], z]


def drone(ground: dict, at: tuple[float, float]) -> tuple[list[dict], list[dict], dict]:
    """The Workshop's drone set down on the ground, as the install gate sets
    it down: its exact bodies, its pins and its machines, with its haul
    routine."""
    design = w.assemble("drone", design_id="drone")
    candidate = {"kind": "drone", "design_id": "drone", "parameters": {},
                 "component_overrides": design.lineage["component_overrides"]}
    design, overrides = workshop_components.design_from_spec(candidate)
    artifact = rigid_assembly.compile_design(design, overrides, root="drone")
    x, z = at
    flat = rigid_assembly.placed(artifact, [x, 0.0, z], 0.0, 0.0)
    lift = max(grounds.ground_under(ground, lo, hi) - low for low, lo, hi in rigid_assembly.footprint(flat))
    placed = rigid_assembly.placed(artifact, [x, lift, z], 0.0, 0.0)
    origin = [x, lift, z]
    frame = (lambda p: [float(p[k]) + origin[k] for k in range(3)], lambda d: [float(v) for v in d])
    made = workshop_machines.installed(design, artifact["component_to_body"], frame, DRONE_ROUTINE["places"])
    [program] = made["programs"]
    program["routine"] = dict(DRONE_ROUTINE)
    return rigid_assembly.scene_bodies(placed), rigid_assembly.scene_joints(placed), made


def compose(ground: dict) -> dict:
    spec = rover_room.compose(ground, "tests-dig")
    machines = spec["machines"]
    machines["programs"][0]["routine"] = ROVER_ROUTINE
    for name, at in (("smelter", SMELTER_AT), ("mill", MILL_AT)):
        body, top = block(ground, name, at)
        spec["bodies"].append(body)
        machines["stores"].append({"name": f"{name} battery", "body": name, "capacity_j": STILL["capacity_j"],
                                   "charge_j": STILL["charge_j"], "voltage_v": STILL["voltage_v"]})
        machines["panels"].append({"name": f"{name} panel", "body": name, "store": f"{name} battery",
                                   "at_mm": [round(1000.0 * v, 1) for v in top], "normal": [0.0, 1.0, 0.0],
                                   "area_m2": STILL["panel_area_m2"], "efficiency": STILL["efficiency"]})
        recipe, intake, output = (("smelt copper", "smelter intake", "smelter output") if name == "smelter"
                                  else ("draw wire", "mill intake", "workshop rack"))
        machines["programs"].append({"name": name, "kind": "still", "body": name, "store": f"{name} battery",
                                     "routine": {"kind": "process", "recipe": recipe, "intake": intake,
                                                 "output": output, "batch_kg": 5.0}})
    bodies, pins, made = drone(ground, DRONE_AT)
    # Its names apart from the rover's (its battery, its panel), as the
    # install gate keeps them.
    made = workshop_install._named_apart(machines, made)
    spec["precise_rigid_bodies"] += bodies
    spec["joints"] += pins
    for key in ("stores", "motors", "panels", "controls", "programs"):
        machines[key] = machines.get(key, []) + list(made.get(key) or [])
    spec["goods"] = json.loads(json.dumps(GOODS))
    return spec


def watch(engine: Path, validated: dict) -> list[str]:
    """Open the room as the playground does, turn every machine on, and run
    every routine over the room's goods as the server does before each step
    the page takes; copper wire must reach the rack within WATCH_S."""
    faults: list[str] = []
    landed: list[tuple[str, float]] = []
    goods = machine_goods.Goods(validated, on_rack=lambda substance, kg: landed.append((substance, kg)))
    with tempfile.TemporaryDirectory() as tmp:
        session = live_session.Session(engine, validated, Path(tmp))
        try:
            pins = validated.get("joints") or []
            hung = live_session.Live._hang(session, pins)
            made: dict = {}
            hung.update(live_session.Live._power(session, validated.get("machines") or {}, pins, made=made))
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
            began = {s["name"]: s["charge_j"] for s in validated["machines"]["stores"]}
            log: list[str] = []
            wall, seconds = time.monotonic(), WATCH_S
            for tick in range(int(WATCH_S / (PER_QUARTER * DT))):
                reply = session.send(op="step", dt=DT, n=PER_QUARTER)
                machines = reply.get("machines") or {}
                t = float(reply.get("t", 0.0))
                for name, program_id in made["programs"].items():
                    said = next((q for q in machines.get("programs") or [] if q.get("id") == program_id), None)
                    if said is None:
                        continue
                    ctx = machine_senses.Context(program=said, machines=machines, bodies=reply.get("bodies"),
                                                 ask=session.send, routine=routines[name], t=t, goods=goods)
                    did = routines[name].tick(ctx)
                    if did is not None:
                        log.append(f"{t:6.1f} s  {name}: {did.get('did', '')}")
                rack = goods.by_name("workshop rack") or {}
                if float((rack.get("holds") or {}).get("copper wire", 0.0)) >= 1.0:
                    seconds = (tick + 1) * PER_QUARTER * DT
                    break
            pace = seconds / (time.monotonic() - wall)
            reply = session.send(op="step", dt=DT, n=1)
            carried = session.send(op="ground_work").get("carried") or {}
            print(f"  ran the mine for {seconds:.0f} s at {pace:.0f}x realtime")
            for line in log[:60]:
                print("    " + line[:160])
            if len(log) > 60:
                print(f"    ... {len(log) - 60} more")
            for pile in goods.stockpiles:
                print(f"  {pile['name']}: " + (", ".join(f"{v:.2f} kg {k}" for k, v in (pile.get('holds') or {}).items())
                                                or "nothing"))
            vein = goods.deposits[0]
            print(f"  the vein: {goods.reserve_kg(vein):.1f} kg of {vein['substance']} left of {vein['reserve_kg']:g}")
            print(f"  onto the Workshop's goods rack: " + (", ".join(f"{kg:.2f} kg {s}" for s, kg in landed) or "nothing"))
            print(f"  the ground's carried account holds {carried.get('total_kg', 0):.2f} kg")
            for store in (reply.get("machines") or {}).get("stores") or []:
                closed = abs(store.get("charge_j", 0) - (began.get(store["name"], 0) + store.get("taken_j", 0)
                                                          - store.get("given_j", 0))) <= 1e-3
                print(f"  {store['name']}: {store.get('charge_j', 0):.0f} J, gave {store.get('given_j', 0):.0f} J, "
                      f"took in {store.get('taken_j', 0):.0f} J" + ("" if closed else "  DOES NOT CLOSE"))
                if not closed:
                    faults.append(f"the account of {store['name']} does not close")
            rack = goods.by_name("workshop rack") or {}
            if float((rack.get("holds") or {}).get("copper wire", 0.0)) < 1.0:
                faults.append(f"in {WATCH_S:.0f} s no copper wire reached the rack; the routines: "
                              + "; ".join(f"{n}: {r.summary()['doing']} ({', '.join(list(r.notes)[-2:])})"
                                          for n, r in routines.items()))
            if not any(s == "copper wire" for s, _ in landed):
                faults.append("what landed on the rack stockpile did not go onto the goods rack")
            if carried.get("total_kg", 0) > 0.5:
                faults.append(f"the ground's carried account holds {carried.get('total_kg'):.2f} kg")
        finally:
            session.close()
    return faults


def main() -> int:
    engine = os.environ.get("BANJO_LIVE_ENGINE")
    if not engine or not Path(engine).is_file():
        print("Set BANJO_LIVE_ENGINE to a built banjo_live_world_run", file=sys.stderr)
        return 2
    engine = Path(engine)
    print("Reading the basin's ground ...")
    ground = rover_room.read_ground(engine)
    print("Laying tests-mine out ...")
    spec = compose(ground)
    validated = fracture_lab.validate(spec)
    print(f"  {len(validated['machines']['programs'])} programs, {len(validated['goods']['stockpiles'])} stockpiles, "
          f"{len(validated['goods']['recipes'])} recipes")
    print("Opening it and running the chain ...")
    faults = watch(engine, validated)
    if faults:
        for fault in faults:
            print(f"  REFUSED: {fault}", file=sys.stderr)
        return 1
    out = ROOMS / "tests-mine.json"
    out.write_text(json.dumps(spec, indent=1, sort_keys=True), encoding="utf-8", newline="\n")
    print(f"Wrote {out.relative_to(ROOT)} ({out.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
