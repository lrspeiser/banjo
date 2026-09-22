#!/usr/bin/env python3
"""Compose the rover room: a battery rover that roams a lake's shore by itself.

    BANJO_LIVE_ENGINE=.../banjo_live_world_run.exe python tools/build_rover_room.py

Writes playground/rooms/tests-rover.json, which world_room serves as the
`tests-rover` scene. Open it at /world?scene=tests-rover, press E on the rover
for its panel, and turn it on.

The second step of the machine world's autonomous creature
(docs/machine-world.md, "One autonomous creature"): wheels it steers with, and
a program that decides where it goes.

  * Its body, exact bodies on pins: an oak deck; a 320 mm oak wheel on each
    side at the back, each on a pin of its own through a bearing mount; and at
    the front an iron caster fork on a swivel, its 160 mm oak wheel trailing
    60 mm behind the swivel's axis, so it swings round to follow.
  * Its machine: a 24 V battery of 100 kJ in the deck, and a DC motor with a
    brake on each back wheel -- 20 N m at a standstill and 60 turns a minute
    unloaded, about 1 m/s -- each worked by a controller of its own.
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

The numbers are a demonstration machine's, declared by the room, not measured
from a real rover. Before it writes the room, this opens it in the engine,
turns the program on and lets it roam for a minute, and refuses to write it
unless the rover roamed, turned away again and again, kept to the basin, and
never had a wheel in the water. Re-run it to rebuild the room; nothing is
hand-edited in the JSON.
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
import rigid_assembly                   # noqa: E402

OUT = ROOT / "playground" / "rooms" / "tests-rover.json"
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
ROAM_S = 60.0
DT = 1 / 120
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
        {"name": "rover: caster wheel", "material": "oak", "color_rgba": OAK, "_centre_m": [0.0, 0.08, 0.32],
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


def compose(ground: dict) -> dict:
    """The room: the post, the rover on the shore, its machine and its program."""
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
    machines = {
        "stores": [{"name": "rover battery", "body": "rover", "capacity_j": MACHINE["capacity_j"],
                    "voltage_v": MACHINE["voltage_v"]}],
        "motors": [{"on": on, "store": "rover battery", "stall_torque_n_m": MACHINE["stall_torque_n_m"],
                    "no_load_rpm": MACHINE["no_load_rpm"], "brake_torque_n_m": MACHINE["brake_torque_n_m"]}
                   for on in wheels.values()],
        "controls": [{"name": f"{side} wheel", "on": on} for side, on in wheels.items()],
        "programs": [{"name": "rover", "kind": "roam", "left": "left wheel", "right": "right wheel",
                      "body": "rover", "setting": PROGRAM["setting"], "climb_deg": PROGRAM["climb_deg"],
                      "sensors": sensors}]}
    return {"algorithm": "lattice", "cell_m": CELL_M, "plasticity": "on",
            "terrain": TERRAIN,
            "bodies": [post],
            "precise_rigid_bodies": bodies,
            "joints": pins,
            "machines": machines}


def pose(poses: dict, name: str) -> dict:
    return next(b for b in poses.get("bodies") or [] if b.get("name") == name)


def roam(engine: Path, validated: dict) -> list[str]:
    """Open the room as the playground does, let it settle, turn the program on
    and watch it roam: what is wrong, or nothing."""
    faults: list[str] = []
    wheels = ("rover: left wheel", "rover: right wheel", "rover: caster wheel")
    with tempfile.TemporaryDirectory() as tmp:
        session = live_session.Session(engine, validated, Path(tmp))
        try:
            pins = validated.get("joints") or []
            hung = live_session.Live._hang(session, pins)
            made: dict = {}
            hung.update(live_session.Live._power(session, validated.get("machines") or {}, pins, made=made))
            for key in ("joint_problems", "machine_problems"):
                faults.extend(hung.get(key) or [])
            if faults:
                return faults
            program = made["programs"]["rover"]
            session.send(op="step", dt=DT, n=240)            # two seconds to settle, on its brakes
            start = pose(session.send(op="poses"), "rover")["position_m"]
            session.send(op="run", program=program, sender="builder", seq=1, power=True)
            path, nearest, furthest, wettest, wet_at, doing_seen = 0.0, 1e9, 0.0, 0.0, "", set()
            was, wall = start, time.monotonic()
            said: dict = {}
            for _ in range(int(ROAM_S / (30 * DT))):          # a quarter of a second at a time
                reply = session.send(op="step", dt=DT, n=30)
                said = next((q for q in (reply.get("machines") or {}).get("programs") or []
                             if q.get("id") == program), said)
                doing_seen.add(said.get("doing", ""))
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
            pace = ROAM_S / (time.monotonic() - wall)
            machines = session.send(op="step", dt=DT, n=1).get("machines") or {}
            given = sum(s.get("given_j", 0.0) for s in machines.get("stores") or [])
            edge = 0.5 * 127 * 0.25 * math.sqrt((LAKE_M - 0.2) / 1.6)
            print(f"  roamed for {ROAM_S:.0f} s: {path:.1f} m, {said.get('turns', 0)} turns away, between "
                  f"{nearest:.2f} m and {furthest:.2f} m out (the lake's edge is {edge:.2f} m out); the battery "
                  f"gave {given:.0f} J; run at {pace:.0f}x realtime (with a survey of its wheels every quarter "
                  f"second)")
            print(f"  it did: {', '.join(sorted(d for d in doing_seen if d))}; now \"{said.get('doing')}\": "
                  f"{said.get('why')}")
            if wettest > 0.003:
                faults.append(f"it had {wettest * 1000:.0f} mm of water under its {wet_at}")
            if path < 15.0:
                faults.append(f"it roamed only {path:.1f} m")
            if said.get("turns", 0) < 3:
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
    print("Laying the room out ...")
    spec = compose(ground)
    validated = fracture_lab.validate(spec)
    print("Opening it and letting the rover roam ...")
    faults = roam(engine, validated)
    if faults:
        for fault in faults:
            print(f"  REFUSED: {fault}", file=sys.stderr)
        return 1
    # The authored spec, not the validated one (build_explore_world.main).
    OUT.write_text(json.dumps(spec, indent=1, sort_keys=True), encoding="utf-8", newline="\n")
    print(f"Wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
