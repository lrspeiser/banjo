"""Compose the tests-sit room: a robot told where a stool is, which goes to it
and puts its torso down on it (docs/machine-world.md, "Milestone 2, its third
step").

    python tools/build_sit_room.py --engine build/.../banjo_live_world_run.exe

The robot is the rover's parts drawn short, because the rover cannot hold a line
after a turn: its caster is 0.70 m in front of the axle its wheels turn about,
so a turn leaves the caster lying across the way it then wants to go and it
scrubs the machine about 20 degrees off for every metre. This one's caster is
0.27 m out. Three points on the ground and no more -- a caster at each end was
built and measured first, and could not turn at all, because four points on a
rigid deck are one too many and the casters took the weight.

Its torso is an oak bar on a pin on a mast 600 mm up, above the 450 mm seat it
is going to reach, because a bar swinging up from a pin below the seat catches
its near edge: every part of it between the pin and its end is lower than the
end.

The builder lays the room out, opens it in the real engine, turns the program on
and watches: the robot must come round onto the stool, drive at it, stop within
reach, and hold its torso on the seat -- short of the angle it was reaching for,
because the stool is carrying it. It writes the room only if that happened.
Nothing is hand-edited in the JSON.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "playground"), str(ROOT / "tools")]

import fracture_lab       # noqa: E402
import live_session       # noqa: E402
import rigid_assembly     # noqa: E402

ROOMS = ROOT / "playground" / "rooms"
CELL_M = 0.05
# Flat ground, 24 m across: this is about the machine and the stool, and a
# slope would only be the roaming rover's story told again. Flat ground's
# surface stands at its soil's depth, not at zero, so everything is set down on
# GROUND_M -- left at zero, the robot was buried 600 mm deep and could neither
# drive nor turn.
GROUND_M = 0.4
TERRAIN = {"generate": {"kind": "flat", "nx": 96, "nz": 96, "cell_m": 0.25,
                        "soil_m": GROUND_M, "sand_m": 0.0}}
OAK = 3382733567             # the colour the Workshop's cart is drawn in
ROBOT_AT = (0.0, -2.0)       # x, z
STOOL_AT = (1.5, 1.5)        # 3.8 m off and 23 degrees to the robot's left
SEAT_TOP_M = 0.45
CLOSE_M = 0.68               # its middle to the stool's, across the ground
POSE_DEG = 125.0             # past the seat: the seat is what stops it
DT = 1 / 240                 # the world page's own step (world.js LIVE_DT)
WATCH_S = 60.0
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


def robot_artifact() -> dict:
    """The robot as rigid_assembly lays a product out: its bodies in its own
    frame -- the floor at y = 0, facing +z, its left the +x side -- and its
    pins, in millimetres."""
    def wheel(name, side):
        return {"name": name, "material": "oak", "color_rgba": OAK,
                "_centre_m": [side * 0.30, 0.16, -0.20],
                "parts": [_across("stub", 0.03, 0.18, (side * 0.24, 0.16, -0.20), "iron"),
                          _across("wheel", 0.32, 0.06, (side * 0.33, 0.16, -0.20))]}

    def pin(a, b, at_mm, axis):
        return {"kind": "hinge", "a": a, "b": b, "at_mm": list(at_mm), "axis": list(axis),
                "lower_deg": -180.0, "upper_deg": 180.0, "friction_n_m": 0.0}

    bodies = [
        {"name": "robot", "material": "oak", "color_rgba": OAK, "_centre_m": [0.0, 0.32, -0.04],
         "parts": [_box("deck", (0.40, 0.06, 0.50), (0.0, 0.29, -0.05)),
                   _box("left mount", (0.03, 0.16, 0.03), (0.175, 0.20, -0.20)),
                   _box("right mount", (0.03, 0.16, 0.03), (-0.175, 0.20, -0.20)),
                   _box("caster mount", (0.08, 0.03, 0.08), (0.0, 0.245, 0.15)),
                   _box("mast", (0.10, 0.29, 0.10), (0.0, 0.465, 0.15))]},
        wheel("robot: left wheel", 1.0),
        wheel("robot: right wheel", -1.0),
        # An iron caster wheel, as a real caster's is: the solver holds a heavy
        # machine up on a light wheel only at short steps.
        {"name": "robot: caster", "material": "iron", "_centre_m": [0.0, 0.13, 0.12],
         "parts": [_box("top", (0.06, 0.02, 0.06), (0.0, 0.215, 0.15)),
                   _box("left cheek", (0.010, 0.17, 0.04), (0.026, 0.125, 0.115)),
                   _box("right cheek", (0.010, 0.17, 0.04), (-0.026, 0.125, 0.115)),
                   _across("pin", 0.010, 0.062, (0.0, 0.05, 0.115))]},
        {"name": "robot: caster wheel", "material": "iron", "_centre_m": [0.0, 0.05, 0.115],
         "parts": [_across("wheel", 0.10, 0.03, (0.0, 0.05, 0.115))]},
        {"name": "robot: torso", "material": "oak", "color_rgba": OAK, "_centre_m": [0.0, 0.85, 0.15],
         "parts": [_box("bar", (0.10, 0.50, 0.05), (0.0, 0.85, 0.15))]},
    ]
    joints = [pin("robot", "robot: left wheel", (175.0, 160.0, -200.0), (1.0, 0.0, 0.0)),
              pin("robot", "robot: right wheel", (-175.0, 160.0, -200.0), (1.0, 0.0, 0.0)),
              pin("robot", "robot: caster", (0.0, 220.0, 150.0), (0.0, 1.0, 0.0)),
              pin("robot: caster", "robot: caster wheel", (0.0, 50.0, 115.0), (1.0, 0.0, 0.0)),
              pin("robot", "robot: torso", (0.0, 600.0, 150.0), (1.0, 0.0, 0.0))]
    return {"bodies": bodies, "joints": joints}


def stool_body(at) -> dict:
    """A stool: a 450 mm oak seat on four legs, its top 450 mm up, standing
    free. Nothing holds it down, so leaning on it is a thing that can go
    wrong."""
    x, z = at
    return {"name": "stool", "material": "oak", "color_rgba": OAK,
            "_centre_m": [0.0, 0.35, 0.0],
            "parts": [_box("seat", (0.45, 0.04, 0.45), (0.0, 0.43, 0.0))] +
                     [_box(f"leg {i}", (0.05, 0.41, 0.05), (sx * 0.18, 0.205, sz * 0.18))
                      for i, (sx, sz) in enumerate(((1, 1), (1, -1), (-1, 1), (-1, -1)))]}


def compose() -> dict:
    """The room: the robot, the stool it goes to, and the machine and program
    that take it there."""
    rx, rz = ROBOT_AT
    robot = rigid_assembly.placed(robot_artifact(), [rx, 0.0, rz], 0.0, 0.0)
    lift = GROUND_M + max(-low for low, _, _ in rigid_assembly.footprint(robot))
    robot = rigid_assembly.placed(robot_artifact(), [rx, lift, rz], 0.0, 0.0)
    bodies = rigid_assembly.scene_bodies(robot)
    pins = rigid_assembly.scene_joints(robot)

    sx, sz = STOOL_AT
    stool = rigid_assembly.placed({"bodies": [stool_body(STOOL_AT)], "joints": []}, [sx, 0.0, sz], 0.0, 0.0)
    stool = rigid_assembly.placed(
        {"bodies": [stool_body(STOOL_AT)], "joints": []},
        [sx, GROUND_M + max(-low for low, _, _ in rigid_assembly.footprint(stool)), sz], 0.0, 0.0)
    bodies += rigid_assembly.scene_bodies(stool)

    away = math.hypot(sx - rx, sz - rz)
    off = math.degrees(math.atan2(sx - rx, sz - rz))
    print(f"  the robot at ({rx:+.2f}, {rz:+.2f}), the stool {away:.2f} m off and {off:.0f} degrees to its left; "
          f"it comes within {CLOSE_M:.2f} m and turns its torso to {POSE_DEG:.0f} degrees")

    turns = {"left": ["robot", "robot: left wheel"], "right": ["robot", "robot: right wheel"]}
    machines = {
        "stores": [{"name": "robot battery", "body": "robot", "capacity_j": 100000.0,
                    "charge_j": 100000.0, "voltage_v": 24.0}],
        "motors": [{"on": on, "store": "robot battery", "stall_torque_n_m": 20.0,
                    "no_load_rpm": 60.0, "brake_torque_n_m": 40.0} for on in turns.values()] +
                  # Slow and strong on the torso: 5.7 turns a minute unloaded,
                  # so it comes down over seconds rather than slamming.
                  [{"on": ["robot", "robot: torso"], "store": "robot battery", "stall_torque_n_m": 20.0,
                    "no_load_rpm": 5.73, "brake_torque_n_m": 40.0}],
        "controls": [{"name": f"{side} wheel", "on": on} for side, on in turns.items()] +
                    [{"name": "torso", "on": ["robot", "robot: torso"]}],
        "programs": [{"name": "robot", "kind": "sit", "left": "left wheel", "right": "right wheel",
                      "body": "robot", "setting": 1.0, "climb_deg": 8.0,
                      "toward": "stool", "close_m": CLOSE_M, "pose": "torso", "pose_deg": POSE_DEG}],
    }
    # The marker stone every room of exact bodies keeps, well out of the way:
    # a room of nothing but exact bodies has no lattice body to size itself by.
    marker = {"name": "marker", "shape": "box", "material": "concrete", "anchored": True,
              "size_mm": [150.0, 150.0, 150.0], "center_mm": [8000.0, 75.0, -8000.0]}
    return {"algorithm": "lattice", "cell_m": CELL_M, "plasticity": "on",
            "terrain": TERRAIN,
            "bodies": [marker],
            "precise_rigid_bodies": bodies,
            "joints": pins,
            "machines": machines}


def pose(poses: dict, name: str) -> dict:
    return next(b for b in poses.get("bodies") or [] if b.get("name") == name)


def watch(engine: Path, validated: dict) -> list[str]:
    """Open the room as the playground does, settle it, turn the program on and
    watch: what is wrong, or nothing."""
    faults: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        session = live_session.Session(engine, validated, Path(tmp))
        try:
            pins = validated.get("joints") or []
            hung = live_session.Live._hang(session, pins)
            made: dict = {}
            hung.update(live_session.Live._power(session, validated.get("machines") or {}, pins, made=made))
            for key in ("joint_problems", "machine_problems"):
                value = hung.get(key)
                faults.extend(value if isinstance(value, list) else [value] if value else [])
            if faults:
                return faults
            program = made["programs"]["robot"]
            session.send(op="step", dt=DT, n=int(2.0 / DT))   # two seconds to settle, on its brakes
            was = pose(session.send(op="poses"), "stool")["position_m"]
            session.send(op="run", program=program, sender="builder", seq=1, power=True)
            said, took_s, order = {}, 0.0, []
            for _ in range(int(WATCH_S / (60 * DT))):          # a quarter of a second at a time
                reply = session.send(op="step", dt=DT, n=60)
                took_s += 60 * DT
                said = next((q for q in (reply.get("machines") or {}).get("programs") or []
                             if q.get("id") == program), said)
                if not order or order[-1] != said.get("doing"):
                    order.append(said.get("doing"))
                if said.get("doing") == "sitting" and said.get("doing_s", 0.0) > 3.0:
                    break
            print("  " + " -> ".join(order))
            poses = session.send(op="poses")
            now = pose(poses, "stool")["position_m"]
            torso = pose(poses, "robot: torso")
            tip = [torso["position_m"][a] + _turn(torso["orientation_wxyz"], (0.0, 0.25, 0.0))[a] for a in range(3)]
            moved = math.dist(was, now)
            above = tip[1] - (GROUND_M + SEAT_TOP_M)
            aside = math.hypot(tip[0] - now[0], tip[2] - now[2])
            print(f"  in {took_s:.1f} s: {said['doing']} -- {said['why']}")
            print(f"  it stopped {said['toward_m']:.3f} m from the stool's middle, {said['bearing_deg']:+.1f} "
                  f"degrees off square, its torso at {said['pose_at_deg']:.1f} of the {POSE_DEG:.0f} it reached for")
            print(f"  the end of the torso is {above * 1000:.0f} mm above the seat and {aside * 1000:.0f} mm in "
                  f"from its middle; the stool moved {moved * 1000:.1f} mm")
            if said["doing"] != "sitting":
                faults.append(f"in {took_s:.0f} s it did not sit down: {said['doing']} -- {said['why']}")
            if said["pose_at_deg"] >= POSE_DEG - 5.0:
                faults.append("the seat did not stop its torso: nothing is carrying it")
            if abs(above) > 0.06:
                faults.append(f"the end of the torso is {above * 1000:.0f} mm off the seat")
            if aside > 0.225:
                faults.append(f"the end of the torso is {aside * 1000:.0f} mm from the seat's middle, over its edge")
            if moved > 0.15:
                faults.append(f"it pushed the stool {moved * 1000:.0f} mm")
        finally:
            session.close()
    return faults


def _turn(q, v):
    w, x, y, z = q
    t = (2 * (y * v[2] - z * v[1]), 2 * (z * v[0] - x * v[2]), 2 * (x * v[1] - y * v[0]))
    return (v[0] + w * t[0] + y * t[2] - z * t[1],
            v[1] + w * t[1] + z * t[0] - x * t[2],
            v[2] + w * t[2] + x * t[1] - y * t[0])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", required=True, type=Path)
    args = parser.parse_args(argv)
    engine = args.engine.resolve()

    print("tests-sit")
    room = compose()
    validated = fracture_lab.validate(room)
    faults = watch(engine, validated)
    if faults:
        for fault in faults:
            print(f"  WRONG: {fault}")
        return 1
    ROOMS.mkdir(parents=True, exist_ok=True)
    (ROOMS / "tests-sit.json").write_text(json.dumps(room, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"  wrote {ROOMS / 'tests-sit.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
