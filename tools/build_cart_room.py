#!/usr/bin/env python3
"""Compose the cart room: a battery cart that drives itself to a lake's edge.

    BANJO_LIVE_ENGINE=.../banjo_live_world_run.exe python tools/build_cart_room.py

Writes playground/rooms/tests-cart.json, which world_room serves as the
`tests-cart` scene. Open it at /world?scene=tests-cart, press E on the cart for
its panel, turn it on and press Forward.

The first step of the machine world's autonomous creature (docs/machine-world.md,
"One autonomous creature"): the Workshop's cart, as exact bodies turning on
pins, with

  * a 24 V battery holding 100 kJ, in its chassis;
  * a DC motor with a brake on the pin of its back wheels: 20 N m at a
    standstill and 60 turns a minute unloaded -- about 1 m/s on its 320 mm
    wheels -- and 40 N m of brake;
  * a controller with a water sensor that looks straight down at the ground
    0.6 m in front of the deck. Where the water there is more than a centimetre
    deep, the controller will not drive forward, and brakes.

It stands on the shore of a round lake: a basin 32 m across, its ground rising
from 0.2 m in the middle as 1.6 (d / 15.9 m)^2 m, soil to the surface, holding
water to 0.5 m -- a lake about 13.7 m across. The cart is 13.5 m out from the
middle, facing it, and tipped to sit square on the slope. Driven forward, it goes
about 6 m down the shore and stops with its front wheels on dry ground.

A room of exact bodies needs one thing made of cells (precise_rigid): a concrete
post, beside the cart's way down.

The machine's numbers are a demonstration machine's, declared by the room, not
measured from a real cart. Before it writes the room, this opens it in the
engine, lets it settle, drives the cart, and refuses to write it unless the cart
stops at the water's edge with its front wheels dry. Re-run it to rebuild the
room; nothing is hand-edited in the JSON.
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
from mcp import workshop_components     # noqa: E402

OUT = ROOT / "playground" / "rooms" / "tests-cart.json"
CELL_M = 0.05
LAKE_M = 0.5
TERRAIN = {"generate": {"kind": "basin", "nx": 128, "nz": 128, "cell_m": 0.25,
                        "lake_level_m": LAKE_M, "sand_m": 0.0}}
CART_AT = (0.0, -13.5)       # x, z: south of the lake's middle, facing it (+z)
POST_AT = (1.6, -11.5)       # beside the cart's way down, clear of its wheels
# The sensor, in the cart's own frame as the Workshop draws it: on the deck's
# centre line at the deck's height, 0.6 m beyond its front edge (the deck runs
# 0.5 m either side of the middle).
SENSOR_LOCAL_M = (0.0, 0.36, 1.1)
SENSOR_DEPTH_MM = 10.0
MACHINE = {"capacity_j": 100000.0, "voltage_v": 24.0,
           "stall_torque_n_m": 20.0, "no_load_rpm": 60.0, "brake_torque_n_m": 40.0}
DT = 1 / 120


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


def turned(q, v):
    """v turned by the unit quaternion q = (w, x, y, z)."""
    return grounds._turn(q, v)


def compose(ground: dict) -> dict:
    """The room: the post, the cart on the shore, and the cart's machine."""
    x, z = CART_AT
    # Tipped about its own x to the slope it faces down, so all four wheels meet
    # the ground: set level, it stood on its back wheels alone.
    fall = grounds.surface_at(ground, x, z + 0.5) - grounds.surface_at(ground, x, z - 0.5)
    pitch = math.atan(-fall)
    design, over = workshop_components.design_from_spec({"kind": "cart", "design_id": "cart", "parameters": {}})
    artifact = rigid_assembly.compile_design(design, over, root="cart")
    flat = rigid_assembly.placed(artifact, [x, 0.0, z], 0.0, pitch)
    lift = max(grounds.ground_under(ground, lo, hi) - low for low, lo, hi in rigid_assembly.footprint(flat))
    cart = rigid_assembly.placed(artifact, [x, lift, z], 0.0, pitch)
    bodies = rigid_assembly.scene_bodies(cart)
    pins = rigid_assembly.scene_joints(cart)
    uses, points = rigid_assembly.room_entries(design, cart)
    chassis = bodies[0]["name"]
    # The back wheels are the ones by the handle, whose pin is furthest back
    # along the cart's own z in the design.
    back = min(artifact["joints"], key=lambda j: j["at_mm"][2])["b"]
    q = bodies[0]["orientation_wxyz"]
    at = [bodies[0]["position_m"][k] + v for k, v in enumerate(turned(q, SENSOR_LOCAL_M))]
    print(f"  the cart at ({x:+.2f}, {z:+.2f}), tipped {math.degrees(pitch):.1f} deg to the shore; "
          f"its back wheels are {back}; its sensor looks down at ({at[0]:+.2f}, {at[2]:+.2f})")

    px, pz = POST_AT
    half = 0.075
    base = grounds.ground_under(ground, (px - half, pz - half), (px + half, pz + half))
    post = {"name": "post", "shape": "box", "material": "concrete", "anchored": True,
            "size_mm": [150.0, 900.0, 150.0],
            "center_mm": [round(px * 1000.0, 1), round((base + 0.45) * 1000.0, 1), round(pz * 1000.0, 1)]}
    machines = {
        "stores": [{"name": "cart battery", "body": chassis, "capacity_j": MACHINE["capacity_j"],
                    "voltage_v": MACHINE["voltage_v"]}],
        "motors": [{"on": [chassis, back], "store": "cart battery",
                    "stall_torque_n_m": MACHINE["stall_torque_n_m"], "no_load_rpm": MACHINE["no_load_rpm"],
                    "brake_torque_n_m": MACHINE["brake_torque_n_m"]}],
        "controls": [{"name": "cart", "on": [chassis, back],
                      "sensors": [{"kind": "water", "body": chassis,
                                   "at_mm": [round(v * 1000.0, 1) for v in at],
                                   "depth_mm": SENSOR_DEPTH_MM, "stops": 1}]}]}
    return {"algorithm": "lattice", "cell_m": CELL_M, "plasticity": "on",
            "terrain": TERRAIN,
            "bodies": [post],
            "precise_rigid_bodies": bodies,
            "joints": pins,
            "machines": machines,
            "actions": uses,
            "interaction_points": points}


def pose(poses: dict, name: str) -> dict:
    return next(b for b in poses.get("bodies") or [] if b.get("name") == name)


def drive(engine: Path, validated: dict) -> list[str]:
    """Open the room as the playground does, let it settle, send the cart
    forward and watch it: what is wrong, or nothing."""
    faults: list[str] = []
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
            control = made["controls"]["cart"]
            session.send(op="step", dt=DT, n=240)            # two seconds to settle, on its brake
            settled = session.send(op="poses")
            chassis, back = validated["machines"]["motors"][0]["on"]
            front = next(j["b"] for j in pins if j["a"] == chassis and j["b"] != back)
            start = pose(settled, chassis)
            for name in (b["name"] for b in validated["precise_rigid_bodies"]):
                gap = grounds.lowest_gap(pose(settled, name), GROUND, CELL_M)
                if gap < -0.02:
                    faults.append(f"{name} settled {-gap * 1000:.0f} mm into the ground")
            lean = grounds.lean_deg(start)
            if lean > 20.0:
                faults.append(f"the cart settled leaning {lean:.0f} degrees")
            session.send(op="operate", control=control, sender="builder", seq=1,
                         power=True, direction=1, setting=1.0)
            stopped, condition, reading, wall = None, "", 0.0, time.monotonic()
            for tick in range(150):                          # fifteen seconds of world at most
                reply = session.send(op="step", dt=DT, n=12)
                said = next((c for c in (reply.get("machines") or {}).get("controls") or []
                             if c.get("id") == control), {})
                condition = said.get("condition", "")
                if "water ahead" in condition:
                    stopped = (tick + 1) * 12 * DT
                    reading = (said.get("sensors") or [{}])[0].get("reading_m", 0.0)
                    break
            pace = (stopped or 15.0) / (time.monotonic() - wall)
            if stopped is None:
                faults.append(f"the cart never stopped for the water: \"{condition}\"")
                return faults
            session.send(op="step", dt=DT, n=240)            # to rest, on its brake
            rest = session.send(op="poses")
            end = pose(rest, chassis)
            wheels = pose(rest, front)
            wet = (session.send(op="survey", at=[wheels["position_m"][0], wheels["position_m"][2]])
                   .get("survey") or {}).get("water")
            driven = math.dist(start["position_m"], end["position_m"])
            speed = math.sqrt(sum(v * v for v in end.get("velocity_m_s") or [0, 0, 0]))
            edge = math.sqrt(max(0.0, (LAKE_M - 0.2) / 1.6)) * 0.5 * 127 * 0.25
            short = math.hypot(wheels["position_m"][0], wheels["position_m"][2]) - 0.16 - edge
            print(f"  driven forward, the sensor saw {reading * 1000:.0f} mm of water after {stopped:.2f} s; "
                  f"the cart came to rest {driven:.2f} m from where it started, its front wheels "
                  f"{short:.2f} m short of the water's edge; run at {pace:.0f}x realtime")
            print(f"  its controller: \"{condition}\"")
            machines = session.send(op="step", dt=DT, n=1).get("machines") or {}
            store, motor = (machines.get("stores") or [{}])[0], (machines.get("motors") or [{}])[0]
            print(f"  the battery gave {store.get('given_j', 0):.0f} J: the motor's work "
                  f"{motor.get('work_j', 0):.0f} J and its heat {motor.get('heat_j', 0):.0f} J")
            if wet:
                faults.append(f"its front wheels stopped in {wet.get('depth_m', 0) * 1000:.0f} mm of water")
            if speed > 0.02:
                faults.append(f"it is still moving at {speed:.3f} m/s")
            if driven < 3.0:
                faults.append(f"it went only {driven:.2f} m")
        finally:
            session.close()
    return faults


GROUND: dict = {}


def main() -> int:
    engine = os.environ.get("BANJO_LIVE_ENGINE")
    if not engine or not Path(engine).is_file():
        print("Set BANJO_LIVE_ENGINE to a built banjo_live_world_run", file=sys.stderr)
        return 2
    engine = Path(engine)
    print("Reading the basin's ground ...")
    GROUND.update(read_ground(engine))
    print(f"  {GROUND['nx']}x{GROUND['nz']} at {GROUND['cell']} m, "
          f"{min(GROUND['h']):.2f} m to {max(GROUND['h']):.2f} m")
    print("Laying the room out ...")
    spec = compose(GROUND)
    validated = fracture_lab.validate(spec)
    print("Opening it and driving the cart ...")
    faults = drive(engine, validated)
    if faults:
        for fault in faults:
            print(f"  REFUSED: {fault}", file=sys.stderr)
        return 1
    # The authored spec, not the validated one, which carries fields of
    # validate()'s own that it then refuses (build_explore_world.main).
    OUT.write_text(json.dumps(spec, indent=1, sort_keys=True), encoding="utf-8", newline="\n")
    print(f"Wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
