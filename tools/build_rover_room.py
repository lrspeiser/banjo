#!/usr/bin/env python3
"""Compose the rover rooms: a battery rover that roams a lake's shore by itself,
the same rover resting in the sun while its solar panel charges it, and the
same rover living through a night.

    BANJO_LIVE_ENGINE=.../banjo_live_world_run.exe python tools/build_rover_room.py [room ...]

Writes playground/rooms/tests-rover.json, tests-solar.json and tests-day.json
(or only the rooms named), which world_room serves as the `tests-rover`,
`tests-solar` and `tests-day` scenes. Open one at /world?scene=tests-rover,
press E on the rover for its panel, and turn it on.

The second step of the machine world's autonomous creature
(docs/machine-world.md, "One autonomous creature"): wheels it steers with, and
a program that decides where it goes.

  * Its body, exact bodies on pins: an oak deck; a 320 mm oak wheel on each
    side at the back, each on a pin of its own through a bearing mount; and at
    the front an iron caster fork on a swivel, its 160 mm iron wheel trailing
    60 mm behind the swivel's axis, so it swings round to follow.
  * Its machine: a 24 V battery of 100 kJ in the deck, and a DC motor with a
    brake on each back wheel -- 20 N m at a standstill and 60 turns a minute
    unloaded, about 1 m/s -- each worked by a controller of its own.
  * A solar panel on its deck, 0.4 m by 0.5 m, turning a fifth of the
    sunlight on it into charge, under a sun 50 degrees up shining 1000 W/m2
    (the owner, 2026-09-22: batteries are charged by solar panels).
  * Its program, "roam": a water sensor at each front corner, half a metre
    ahead of the deck and wider than the wheels, looking down for more than
    3 mm of water. It goes forward; where a sensor sees water it backs
    off, then turns away on the spot from the side that saw it, one wheel
    driving and the other backing; where the ground is steeper than 8
    degrees, rising ahead or falling away to one side, it turns towards the
    lower side; where its wheels stall it backs off and turns. It knows only
    what its sensors and its own slope tell it: nothing about where the lake
    is.

It stands on the shore of a round lake -- a basin 32 m across, its ground
rising from 0.2 m in the middle as 1.6 (d / 15.9 m)^2 m, soil to the surface,
holding water to 0.35 m, a lake 9.7 m across -- 9 m out from the middle,
facing it, tipped to sit square on the slope. A room of exact bodies needs one
thing made of cells (precise_rigid): a concrete post, in a far corner.

In tests-rover its battery holds 100 kJ and is full, and it roams all day. In
tests-solar the battery holds 5 kJ and is down to 28%, and the program rests
below a quarter until the panel has charged it to three fifths: roaming draws
more than the panel gives, so it runs down, stops where it is, rests in the sun,
and roams on.

In tests-day the sun has a day ("A day for the sun"): four minutes long, 60
degrees up at noon, and the room begins at four in the afternoon. The rover
roams through the evening on what its battery holds; the sun sets at six, and
after it the panel gives nothing; when the battery is down to a quarter the
rover rests until morning, and when the morning sun has charged it to two
fifths, it roams on.

The numbers are a demonstration machine's, declared by the room, not measured
from a real rover. Before it writes a room, this opens it in the engine, turns
the program on and watches: tests-rover must roam a minute, turning away again
and again, keeping to the basin and never with a wheel in the water;
tests-solar must run down, rest, be charged by the sun and roam on, dry, with
every joule of its battery accounted for; tests-day must run low after the
sun has set, take in nothing in the night, say it waits for the morning, and
wake only after the sun is up. Re-run it to rebuild the rooms;
nothing is hand-edited in the JSON.
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

import build_explore_world as grounds   # noqa: E402  the ground, and standing things on it
import fracture_lab                     # noqa: E402
import live_session                     # noqa: E402
import machine_routine                  # noqa: E402
import machine_senses                   # noqa: E402
import rigid_assembly                   # noqa: E402

ROOMS = ROOT / "playground" / "rooms"
CELL_M = 0.05
LAKE_M = 0.35
TERRAIN = {"generate": {"kind": "basin", "nx": 128, "nz": 128, "cell_m": 0.25,
                        "lake_level_m": LAKE_M, "sand_m": 0.0}}
ROVER_AT = (0.0, -9.0)       # x, z: south of the lake's middle, facing it (+z)
POST_AT = (13.0, 13.0)       # a far corner, beyond where the rover will climb
OAK = 3382733567             # the colour the Workshop's cart is drawn in
# Each water sensor, in the rover's own frame as drawn: half a metre ahead of the
# deck (it runs 0.5 m either side of the middle) and 0.55 m either side of the
# middle, looking for more than 3 mm of water, the depth the water itself calls
# wet. Wider than the wheels, and by more than they cut inside the line the
# front takes on a curve: set within them, and looking for a centimetre, a back
# wheel ran along the shore into water neither sensor had seen.
SENSORS_LOCAL_M = ((0.55, 0.36, 1.0), (-0.55, 0.36, 1.0))
SENSOR_DEPTH_MM = 3.0
MACHINE = {"capacity_j": 100000.0, "voltage_v": 24.0,
           "stall_torque_n_m": 20.0, "no_load_rpm": 60.0, "brake_torque_n_m": 40.0}
PROGRAM = {"setting": 1.0, "climb_deg": 8.0}
SUN = {"elevation_deg": 50.0, "azimuth_deg": 200.0, "irradiance_w_m2": 1000.0}
# The panel, in the rover's own frame: the top of the glass plate on its deck.
PANEL_AT_LOCAL_M = (0.0, 0.39, -0.05)
PANEL = {"area_m2": 0.2, "efficiency": 0.2}
# A sun with a day: four minutes of the world's time, so a night is two; 60
# degrees up at noon; the room begins at four in the afternoon.
DAY_SUN = {"day_s": 240.0, "noon_elevation_deg": 60.0, "hour": 16.0, "irradiance_w_m2": 1000.0}
# Each room's battery and how its program rests, and a sun of its own.
# The dig room's places, in the basin's metres: the dig site north-east of
# where the rover starts, on the floor short of the lake; the depot south-west
# of it. A 40 kg hopper, and a scoop's work at the default 50 J/kg.
DIG_ROUTINE = {"kind": "dig", "places": {"dig site": [2.0, -6.5], "depot": [-2.5, -9.5]}, "hopper_kg": 40.0}
DIG_WATCH_S = 300.0
ROOM_KINDS = {
    "tests-rover": {"capacity_j": 100000.0, "charge_j": 100000.0},
    "tests-dig": {"capacity_j": 100000.0, "charge_j": 100000.0, "routine": DIG_ROUTINE},
    "tests-solar": {"capacity_j": 5000.0, "charge_j": 1400.0, "rest_below": 0.25, "rest_until": 0.6},
    "tests-day": {"capacity_j": 5000.0, "charge_j": 3500.0, "rest_below": 0.25, "rest_until": 0.4,
                  "sun": DAY_SUN},
}
# How long the builder watches tests-day for its night and its morning, at most.
DAY_WATCH_S = 420.0
ROAM_S = 60.0
# The world page's own step (world.js LIVE_DT). At 1/120 s the caster's oak
# wheel, light under the rover's weight, sank into the ground -- 27 mm in three
# seconds -- and the rover stuck; at the page's step it did not.
DT = 1 / 240
PER_QUARTER = 60
ONTO_X = [math.sqrt(0.5), 0.0, 0.0, math.sqrt(0.5)]   # a cylinder's own y turned onto x


def _box(name, size, at, material=None):
    part = {"name": name, "dimensions_m": list(size), "center_local_m": list(at)}
    if material:
        part["material"] = material
    return part


def _across(name, diameter, width, at, material=None):
    part = {"name": name, "shape": "cylinder", "dimensions_m": [diameter, width, diameter],
            "center_local_m": list(at), "rotation_wxyz": ONTO_X}
    if material:
        part["material"] = material
    return part


def rover_artifact() -> dict:
    """The rover as rigid_assembly lays a product out: its bodies in its own
    frame -- the floor at y = 0, facing +z, its left the +x side -- and its
    pins, in millimetres."""
    def wheel(name, side):
        return {"name": name, "material": "oak", "color_rgba": OAK, "_centre_m": [side * 0.35, 0.16, -0.32],
                "parts": [_across("stub", 0.03, 0.20, (side * 0.26, 0.16, -0.32), "iron"),
                          _across("wheel", 0.32, 0.06, (side * 0.38, 0.16, -0.32))]}

    def pin(a, b, at_mm, axis):
        return {"kind": "hinge", "a": a, "b": b, "at_mm": list(at_mm), "axis": list(axis),
                "lower_deg": -180.0, "upper_deg": 180.0, "friction_n_m": 0.0}

    bodies = [
        {"name": "rover", "material": "oak", "color_rgba": OAK, "_centre_m": [0.0, 0.35, 0.0],
         "parts": [_box("deck", (0.7, 0.04, 1.0), (0.0, 0.36, 0.0)),
                   _box("solar panel", (0.4, 0.01, 0.5), (0.0, 0.385, -0.05), "glass"),
                   _box("left mount", (0.0345, 0.18, 0.0345), (0.1925, 0.25, -0.32)),
                   _box("right mount", (0.0345, 0.18, 0.0345), (-0.1925, 0.25, -0.32)),
                   _box("caster mount", (0.10, 0.03, 0.10), (0.0, 0.325, 0.38))]},
        wheel("rover: left wheel", 1.0),
        wheel("rover: right wheel", -1.0),
        {"name": "rover: caster", "material": "iron", "_centre_m": [0.0, 0.2, 0.35],
         "parts": [_box("top", (0.08, 0.02, 0.08), (0.0, 0.30, 0.38)),
                   _box("left cheek", (0.012, 0.22, 0.05), (0.035, 0.18, 0.335)),
                   _box("right cheek", (0.012, 0.22, 0.05), (-0.035, 0.18, 0.335)),
                   _across("pin", 0.012, 0.082, (0.0, 0.08, 0.32))]},
        # An iron caster wheel, as a real caster's is: the solver holds a heavy
        # machine up on a light wheel only at short steps -- at 1/120 s an oak
        # one sank 27 mm into the ground in three seconds, an iron one 1 mm.
        {"name": "rover: caster wheel", "material": "iron", "_centre_m": [0.0, 0.08, 0.32],
         "parts": [_across("wheel", 0.16, 0.04, (0.0, 0.08, 0.32))]},
    ]
    joints = [pin("rover", "rover: left wheel", (192.5, 160.0, -320.0), (1.0, 0.0, 0.0)),
              pin("rover", "rover: right wheel", (-192.5, 160.0, -320.0), (1.0, 0.0, 0.0)),
              pin("rover", "rover: caster", (0.0, 310.0, 380.0), (0.0, 1.0, 0.0)),
              pin("rover: caster", "rover: caster wheel", (0.0, 80.0, 320.0), (1.0, 0.0, 0.0))]
    return {"bodies": bodies, "joints": joints}


def read_ground(engine: Path) -> dict:
    """The basin's heightfield, and where its lake stands, from a live world."""
    spec = fracture_lab.validate({
        "algorithm": "lattice", "cell_m": CELL_M, "duration_s": 1.0, "terrain": TERRAIN,
        "bodies": [{"name": "sounding", "shape": "box", "material": "oak",
                    "size_mm": [100, 100, 100], "center_mm": [0, 8000, 0]}]})
    with tempfile.TemporaryDirectory() as tmp:
        session = live_session.Session(engine, spec, Path(tmp))
        try:
            terrain = session.send(op="terrain").get("terrain") or {}
            water = session.send(op="poses").get("water") or {}
        finally:
            session.close()
    ground = grounds.ground_of(terrain)
    ground["wet"] = grounds.wet_of(water)
    return ground


def compose(ground: dict, kind: str) -> dict:
    """The room: the post, the rover on the shore, its machine, its panel and
    its program, and the sun -- with the battery and the rest of `kind`."""
    battery = ROOM_KINDS[kind]
    x, z = ROVER_AT
    # Tipped about its own x to the slope it faces down, so its wheels and its
    # caster all meet the ground.
    fall = grounds.surface_at(ground, x, z + 0.5) - grounds.surface_at(ground, x, z - 0.5)
    pitch = math.atan(-fall)
    artifact = rover_artifact()
    flat = rigid_assembly.placed(artifact, [x, 0.0, z], 0.0, pitch)
    lift = max(grounds.ground_under(ground, lo, hi) - low for low, lo, hi in rigid_assembly.footprint(flat))
    rover = rigid_assembly.placed(artifact, [x, lift, z], 0.0, pitch)
    bodies = rigid_assembly.scene_bodies(rover)
    pins = rigid_assembly.scene_joints(rover)
    q = bodies[0]["orientation_wxyz"]
    sensors = [{"kind": "water", "body": "rover",
                "at_mm": [round((bodies[0]["position_m"][k] + v) * 1000.0, 1)
                          for k, v in enumerate(grounds._turn(q, local))],
                "depth_mm": SENSOR_DEPTH_MM} for local in SENSORS_LOCAL_M]
    print(f"  the rover at ({x:+.2f}, {z:+.2f}), tipped {math.degrees(pitch):.1f} deg to the shore; its sensors "
          f"look down at " + ", ".join(f"({s['at_mm'][0] / 1000:+.2f}, {s['at_mm'][2] / 1000:+.2f})" for s in sensors))

    px, pz = POST_AT
    half = 0.075
    base = grounds.ground_under(ground, (px - half, pz - half), (px + half, pz + half))
    post = {"name": "post", "shape": "box", "material": "concrete", "anchored": True,
            "size_mm": [150.0, 900.0, 150.0],
            "center_mm": [round(px * 1000.0, 1), round((base + 0.45) * 1000.0, 1), round(pz * 1000.0, 1)]}
    wheels = {"left": ["rover", "rover: left wheel"], "right": ["rover", "rover: right wheel"]}
    panel_at = [round((bodies[0]["position_m"][k] + v) * 1000.0, 1)
                for k, v in enumerate(grounds._turn(q, PANEL_AT_LOCAL_M))]
    facing = [round(v, 9) for v in grounds._turn(q, (0.0, 1.0, 0.0))]
    rest = {k: battery[k] for k in ("rest_below", "rest_until", "routine") if k in battery}
    machines = {
        "stores": [{"name": "rover battery", "body": "rover", "capacity_j": battery["capacity_j"],
                    "charge_j": battery["charge_j"], "voltage_v": MACHINE["voltage_v"]}],
        "motors": [{"on": on, "store": "rover battery", "stall_torque_n_m": MACHINE["stall_torque_n_m"],
                    "no_load_rpm": MACHINE["no_load_rpm"], "brake_torque_n_m": MACHINE["brake_torque_n_m"]}
                   for on in wheels.values()],
        "controls": [{"name": f"{side} wheel", "on": on} for side, on in wheels.items()],
        "programs": [{"name": "rover", "kind": "roam", "left": "left wheel", "right": "right wheel",
                      "body": "rover", "setting": PROGRAM["setting"], "climb_deg": PROGRAM["climb_deg"],
                      "sensors": sensors, **rest}],
        "panels": [{"name": "solar panel", "body": "rover", "store": "rover battery", "at_mm": panel_at,
                    "normal": facing, **PANEL}]}
    return {"algorithm": "lattice", "cell_m": CELL_M, "plasticity": "on",
            "terrain": TERRAIN,
            "sun": dict(battery.get("sun", SUN)),
            "bodies": [post],
            "precise_rigid_bodies": bodies,
            "joints": pins,
            "machines": machines}


def pose(poses: dict, name: str) -> dict:
    return next(b for b in poses.get("bodies") or [] if b.get("name") == name)


def dig(engine: Path, validated: dict) -> list[str]:
    """Open the dig room as the playground does and run the rover's routine
    over its program, as the server does before each step the page takes
    (rover_brain.Brains.before): it must reach its dig site, fill its hopper,
    carry the load to its depot and dump it within DIG_WATCH_S, dry, with
    the ground's carried account back at nothing and its battery's account
    closed, the scoop's work included."""
    faults: list[str] = []
    wheels = ("rover: left wheel", "rover: right wheel", "rover: caster wheel")
    declared = validated["machines"]["programs"][0]["routine"]
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
            program = made["programs"]["rover"]
            session.send(op="step", dt=DT, n=int(2.0 / DT))
            session.send(op="run", program=program, sender="builder", seq=1, power=True)
            routine = machine_routine.Routine("rover", declared)
            said: dict = {}
            wettest, wet_at, wall, seconds, order = 0.0, "", time.monotonic(), DIG_WATCH_S, []
            for tick in range(int(DIG_WATCH_S / (PER_QUARTER * DT))):
                reply = session.send(op="step", dt=DT, n=PER_QUARTER)
                machines = reply.get("machines") or {}
                said = next((q for q in machines.get("programs") or [] if q.get("id") == program), said)
                ctx = machine_senses.Context(program=said, machines=machines, bodies=reply.get("bodies"),
                                             ask=session.send, routine=routine, t=reply.get("t", 0.0))
                did = routine.tick(ctx)
                if did is not None:
                    order.append(did.get("did", ""))
                poses = session.send(op="poses")
                for name in wheels:
                    w = pose(poses, name)["position_m"]
                    water = (session.send(op="survey", at=[w[0], w[2]]).get("survey") or {}).get("water")
                    if water and water.get("depth_m", 0.0) > wettest:
                        wettest, wet_at = water["depth_m"], f"{name} while {said.get('doing')} ({said.get('why')})"
                if routine.trips >= 1 and routine.step % 4 == 1:
                    seconds = (tick + 1) * PER_QUARTER * DT
                    break
            pace = seconds / (time.monotonic() - wall)
            reply = session.send(op="step", dt=DT, n=1)
            store = ((reply.get("machines") or {}).get("stores") or [{}])[0]
            carried = (session.send(op="ground_work").get("carried") or {})
            load = routine.load_reading()
            print(f"  ran its routine for {seconds:.0f} s at {pace:.0f}x realtime: {load['trips']} trip(s), "
                  f"{load['delivered_kg']:.1f} kg delivered, {load['kg']:.1f} kg in its hopper now; the battery "
                  f"gave {store.get('given_j', 0):.0f} J; the ground's carried account holds "
                  f"{carried.get('total_kg', 0):.2f} kg; at most {wettest * 1000:.0f} mm of water under a wheel")
            print("  it did: " + "; ".join(o for o in order if o)[:900])
            print("  its notes: " + " | ".join(routine.notes))
            began = ROOM_KINDS["tests-dig"]["charge_j"]
            if abs(store.get("charge_j", 0) - (began + store.get("taken_j", 0) - store.get("given_j", 0))) > 1e-3:
                faults.append("its battery's account does not close")
            if routine.trips < 1:
                faults.append(f"in {DIG_WATCH_S:.0f} s it did not deliver a load: {routine.summary()}")
            if carried.get("total_kg", 0) > 0.5:
                faults.append(f"the ground's carried account holds {carried.get('total_kg'):.2f} kg after the dump")
            if wettest > 0.003:
                faults.append(f"it had {wettest * 1000:.0f} mm of water under its {wet_at}")
        finally:
            session.close()
    return faults


def roam(engine: Path, validated: dict, kind: str) -> list[str]:
    """Open the room as the playground does, let it settle, turn the program on
    and watch it: what is wrong, or nothing. tests-rover roams a minute;
    tests-solar goes on until it has rested and roamed on again, or three
    minutes have passed; tests-day until it has rested through the night and
    roamed on in the morning, or seven."""
    faults: list[str] = []
    wheels = ("rover: left wheel", "rover: right wheel", "rover: caster wheel")
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
            program = made["programs"]["rover"]
            session.send(op="step", dt=DT, n=int(2.0 / DT))   # two seconds to settle, on its brakes
            start = pose(session.send(op="poses"), "rover")["position_m"]
            session.send(op="run", program=program, sender="builder", seq=1, power=True)
            path, nearest, furthest, wettest, wet_at, doing_seen = 0.0, 1e9, 0.0, 0.0, "", set()
            was, wall = start, time.monotonic()
            said: dict = {}
            seconds = ROAM_S if kind == "tests-rover" else DAY_WATCH_S if kind == "tests-day" else 180.0
            order: list[str] = []
            # Its day: the hour and the battery at sunset, when it began to
            # rest and why, at sunrise, and when it woke.
            day: dict = {}
            sun: dict = {}
            for tick in range(int(seconds / (PER_QUARTER * DT))):   # a quarter of a second at a time
                reply = session.send(op="step", dt=DT, n=PER_QUARTER)
                said = next((q for q in (reply.get("machines") or {}).get("programs") or []
                             if q.get("id") == program), said)
                doing_seen.add(said.get("doing", ""))
                if not order or order[-1] != said.get("doing"):
                    order.append(said.get("doing"))
                if kind == "tests-day":
                    was_up, sun = sun.get("elevation_deg", 1.0) > 0.0, reply.get("sun") or sun
                    up = sun.get("elevation_deg", 0.0) > 0.0
                    stored = ((reply.get("machines") or {}).get("stores") or [{}])[0]
                    at = {"t": reply.get("t", 0.0), "hour": sun.get("hour", 0.0),
                          "charge_j": stored.get("charge_j", 0.0), "taken_j": stored.get("taken_j", 0.0)}
                    if was_up and not up and "sunset" not in day:
                        day["sunset"] = at
                    if not was_up and up and "sunset" in day and "sunrise" not in day:
                        day["sunrise"] = at
                    if said.get("doing") == "resting" and "rested" not in day:
                        day["rested"] = {**at, "why": said.get("why")}
                    if "rested" in day and said.get("doing") != "resting" and "woke" not in day:
                        day["woke"] = at
                    if "woke" in day and said.get("doing_s", 0.0) > 5.0:
                        seconds = (tick + 1) * PER_QUARTER * DT
                        break
                if (kind == "tests-solar" and said.get("rests", 0) >= 1 and said.get("doing") != "resting"
                        and said.get("doing_s", 0.0) > 5.0):
                    seconds = (tick + 1) * PER_QUARTER * DT
                    break
                poses = session.send(op="poses")
                at = pose(poses, "rover")["position_m"]
                path += math.dist(at, was)
                was = at
                out = math.hypot(at[0], at[2])
                nearest, furthest = min(nearest, out), max(furthest, out)
                for name in wheels:
                    w = pose(poses, name)["position_m"]
                    water = (session.send(op="survey", at=[w[0], w[2]]).get("survey") or {}).get("water")
                    if water and water.get("depth_m", 0.0) > wettest:
                        wettest, wet_at = water["depth_m"], f"{name} while {said.get('doing')} ({said.get('why')})"
            pace = seconds / (time.monotonic() - wall)
            machines = session.send(op="step", dt=DT, n=1).get("machines") or {}
            store = (machines.get("stores") or [{}])[0]
            panel = (machines.get("panels") or [{}])[0]
            edge = 0.5 * 127 * 0.25 * math.sqrt((LAKE_M - 0.2) / 1.6)
            print(f"  roamed for {seconds:.0f} s: {path:.1f} m, {said.get('turns', 0)} turns away, between "
                  f"{nearest:.2f} m and {furthest:.2f} m out (the lake's edge is {edge:.2f} m out); the battery "
                  f"gave {store.get('given_j', 0):.0f} J and took in {store.get('taken_j', 0):.0f} J from its "
                  f"panel ({panel.get('power_w', 0):.1f} W of {panel.get('sunlight_w', 0):.0f} W of sun now); run "
                  f"at {pace:.0f}x realtime (with a survey of its wheels every quarter second)")
            print(f"  it did: {', '.join(d for d in order if d)}; now \"{said.get('doing')}\": {said.get('why')}")
            if kind == "tests-day":
                def when(key):
                    at = day.get(key)
                    if not at:
                        return f"{key}: never"
                    hour = at["hour"] % 24.0
                    return (f"{key} at {int(hour):02d}:{int(hour % 1 * 60):02d} (t={at['t']:.0f} s), the battery "
                            f"{at['charge_j']:.0f} J, taken in {at['taken_j']:.0f} J")
                print("  " + "; ".join(when(k) for k in ("sunset", "rested", "sunrise", "woke")))
                if day.get("rested"):
                    print(f"  resting, it said: {day['rested']['why']}")
            began = ROOM_KINDS[kind]["charge_j"]
            if abs(store.get("charge_j", 0) - (began + store.get("taken_j", 0) - store.get("given_j", 0))) > 1e-3:
                faults.append("its battery's account does not close")
            if abs(store.get("taken_j", 0) - panel.get("collected_j", 0)) > 1e-3:
                faults.append("its battery took in something its panel did not give")
            if kind == "tests-solar" and (said.get("rests", 0) < 1 or said.get("doing") == "resting"):
                faults.append(f"in {seconds:.0f} s it did not rest and roam on: {order}")
            if kind == "tests-day":
                missing = [k for k in ("sunset", "rested", "sunrise", "woke") if k not in day]
                if missing:
                    faults.append(f"in {seconds:.0f} s its day did not come round: no {', '.join(missing)}")
                else:
                    if not day["sunset"]["t"] < day["rested"]["t"] < day["sunrise"]["t"]:
                        faults.append("it did not run low in the night")
                    if abs(day["sunrise"]["taken_j"] - day["sunset"]["taken_j"]) > 1e-6:
                        faults.append("its battery took something in during the night")
                    if not day["woke"]["t"] > day["sunrise"]["t"]:
                        faults.append("it woke before the sun was up")
                    if "sun is down" not in (day["rested"].get("why") or ""):
                        faults.append(f"resting in the night, it said: {day['rested'].get('why')}")
            if wettest > 0.003:
                faults.append(f"it had {wettest * 1000:.0f} mm of water under its {wet_at}")
            if path < (15.0 if kind == "tests-rover" else 5.0):
                faults.append(f"it roamed only {path:.1f} m")
            if kind == "tests-rover" and said.get("turns", 0) < 3:
                faults.append(f"it turned away only {said.get('turns', 0)} times")
            if furthest > 14.0:
                faults.append(f"it went {furthest:.1f} m out, near the basin's edge")
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
    ground = read_ground(engine)
    print(f"  {ground['nx']}x{ground['nz']} at {ground['cell']} m, "
          f"{min(ground['h']):.2f} m to {max(ground['h']):.2f} m")
    kinds = [k for k in sys.argv[1:] if k in ROOM_KINDS] or list(ROOM_KINDS)
    for kind in kinds:
        print(f"Laying {kind} out ...")
        spec = compose(ground, kind)
        validated = fracture_lab.validate(spec)
        print("Opening it and letting the rover go ...")
        faults = dig(engine, validated) if kind == "tests-dig" else roam(engine, validated, kind)
        if faults:
            for fault in faults:
                print(f"  REFUSED: {fault}", file=sys.stderr)
            return 1
        # The authored spec, not the validated one (build_explore_world.main).
        out = ROOMS / f"{kind}.json"
        out.write_text(json.dumps(spec, indent=1, sort_keys=True), encoding="utf-8", newline="\n")
        print(f"Wrote {out.relative_to(ROOT)} ({out.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
