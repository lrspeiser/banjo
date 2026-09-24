"""Compose the tests-motor room: three turntables that answer one question.

    python tools/build_motor_room.py --engine build/.../banjo_live_world_run.exe

The question is the owner's: when a motor runs, does it understand the weight of
each part, so that the lighter part moves and the heavier one does not?

A motor on a pin puts equal and opposite torques on the two bodies it joins, so
what decides is not weight but how hard each is to TURN -- a moment of inertia,
which goes as the mass times the square of the size. Each station here is a
block on the ground with a second block on a vertical pin above it and a motor
between them. The pin is upright so that gravity pulls on neither end of the
turn, and the top hangs 40 mm clear so that nothing rubs. Walk up to one, press
E, and turn it on.

Each pair stands on a pedestal, held up by a free pin, so that BOTH ends are
free to come round and the only thing deciding which does is how hard each is to
turn. (Set straight on the ground instead, all three look the same -- the top
spins 720 degrees and the base does not move at all -- because the ground holds
the base, whatever it is made of. True, and a different lesson: it is why a
rover's wheels turn and its chassis does not.)

  1. A heavy iron base and a light oak top. The top whirls and the base barely
     stirs.
  2. A big oak base and a SMALL IRON top -- which is the HEAVIER of the two, and
     still the one that comes round, because a moment goes as the square of the
     size. A motor that only knew mass would have this backwards.
  3. Two of exactly the same, which turn equally and oppositely.

The builder lays it out, opens it in the real engine, turns each station on and
watches, and writes the room only if each one turned the way it says. Nothing in
the room file is hand-edited.
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

ROOMS = ROOT / "playground" / "rooms"
CELL_M = 0.05
GROUND_M = 0.4
CLEAR_M = 0.04
#: What a bearing costs to turn. The pedestal's is small, so that it holds the
#: base up without holding it still and the split stays the thing on show; the
#: motored one is a working bearing, so that switching the motor off lets the
#: turntable run down instead of coasting for ever.
PEDESTAL_FRICTION_N_M = 0.05
BEARING_FRICTION_N_M = 0.5
POST_TOP_M = 1.0      # the pedestal's top: about waist height        # the top hangs clear of the base: a bearing is not a rub
DT = 1 / 240
WATCH_S = 4.0
DENSITY = {"oak": 700.0, "iron": 7800.0}
OAK = 3382733567
TERRAIN = {"generate": {"kind": "flat", "nx": 96, "nz": 96, "cell_m": 0.25,
                        "soil_m": GROUND_M, "sand_m": 0.0}}

#: Each station: where it stands, and the base and top it is made of.
STATIONS = [
    {"name": "heavy base", "at_x": -3.0,
     "base": ("iron", 0.50, 0.40), "top": ("oak", 0.25, 0.25),
     "says": "a heavy iron base and a light oak top"},
    {"name": "heavy top", "at_x": 0.0,
     "base": ("oak", 0.60, 0.40), "top": ("iron", 0.25, 0.25),
     "says": "a big oak base and a small iron top, which is the heavier of the two"},
    {"name": "same both", "at_x": 3.0,
     "base": ("oak", 0.40, 0.40), "top": ("oak", 0.40, 0.40),
     "says": "two of exactly the same"},
]


def _mass_and_moment(material, across, tall):
    mass = DENSITY[material] * across * across * tall
    return mass, mass * 2.0 * across * across / 12.0


def _block(name, material, across, tall, at):
    return {"name": name, "material": material, "color_rgba": OAK if material == "oak" else None,
            "position_m": [at[0], at[1], at[2]], "orientation_wxyz": [1.0, 0.0, 0.0, 0.0],
            "parts": [{"name": "block", "dimensions_m": [across, tall, across],
                       "center_local_m": [0.0, 0.0, 0.0]}]}


def compose() -> dict:
    """The three stations, each on a pedestal of its own."""
    posts, bodies, joints, stores, motors, controls = [], [], [], [], [], []
    for station in STATIONS:
        tag, x = station["name"], station["at_x"]
        (bm, ba, bt), (tm, ta, tt) = station["base"], station["top"]
        base, top = f"{tag}: base", f"{tag}: top"
        # A concrete post driven into the ground, and the base hanging on a free
        # pin above it: it carries the weight and holds nothing against turning.
        posts.append({"name": f"{tag}: post", "shape": "box", "material": "concrete", "anchored": True,
                      "size_mm": [200.0, (POST_TOP_M - GROUND_M + 0.4) * 1000.0, 200.0],
                      "center_mm": [x * 1000.0, (POST_TOP_M - (POST_TOP_M - GROUND_M + 0.4) / 2) * 1000.0, 0.0]})
        base_y = POST_TOP_M + CLEAR_M + bt / 2
        top_y = base_y + bt / 2 + CLEAR_M + tt / 2
        for body in (_block(base, bm, ba, bt, (x, base_y, 0.0)),
                     _block(top, tm, ta, tt, (x, top_y, 0.0))):
            bodies.append({k: v for k, v in body.items() if v is not None})
        joints.append({"kind": "hinge", "a": f"{tag}: post", "b": base,
                       "at_mm": [x * 1000.0, (POST_TOP_M + CLEAR_M / 2) * 1000.0, 0.0],
                       "axis": [0.0, 1.0, 0.0], "lower_deg": -180.0, "upper_deg": 180.0,
                       "friction_n_m": PEDESTAL_FRICTION_N_M})
        joints.append({"kind": "hinge", "a": base, "b": top,
                       "at_mm": [x * 1000.0, (base_y + bt / 2 + CLEAR_M / 2) * 1000.0, 0.0],
                       "axis": [0.0, 1.0, 0.0], "lower_deg": -180.0, "upper_deg": 180.0,
                       "friction_n_m": BEARING_FRICTION_N_M})
        stores.append({"name": f"{tag} battery", "body": base, "capacity_j": 1000000.0,
                       "charge_j": 1000000.0, "voltage_v": 24.0})
        motors.append({"on": [base, top], "store": f"{tag} battery", "stall_torque_n_m": 40.0,
                       "no_load_rpm": 30.0, "brake_torque_n_m": 0.0})
        controls.append({"name": tag, "on": [base, top]})
        base_mass, base_moment = _mass_and_moment(bm, ba, bt)
        top_mass, top_moment = _mass_and_moment(tm, ta, tt)
        station["share"] = base_moment / top_moment
        print(f"  {tag}: base {base_mass:6.1f} kg / {base_moment:6.3f} kg m2, "
              f"top {top_mass:6.1f} kg / {top_moment:6.3f} kg m2 "
              f"-- the top is {station['share']:.1f}x easier to turn")
    return {"algorithm": "lattice", "cell_m": CELL_M, "plasticity": "on", "terrain": TERRAIN,
            "bodies": posts + [{"name": "marker", "shape": "box", "material": "concrete", "anchored": True,
                                "size_mm": [150.0, 150.0, 150.0],
                                "center_mm": [8000.0, (GROUND_M + 0.075) * 1000.0, -8000.0]}],
            "precise_rigid_bodies": bodies, "joints": joints,
            "machines": {"stores": stores, "motors": motors, "controls": controls}}


def _spin(q):
    w, x, y, z = q
    return math.degrees(math.atan2(2 * (w * y + z * x), 1 - 2 * (y * y + z * z)))


def watch(engine: Path, validated: dict) -> list[str]:
    """Turn each station on and see which end of it comes round."""
    faults: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        session = live_session.Session(engine, validated, Path(tmp))
        try:
            pins = validated["joints"]
            hung = live_session.Live._hang(session, pins)
            made: dict = {}
            hung.update(live_session.Live._power(session, validated["machines"], pins, made=made))
            for key in ("joint_problems", "machine_problems"):
                value = hung.get(key)
                faults.extend(value if isinstance(value, list) else [value] if value else [])
            if faults:
                return faults
            session.send(op="step", dt=DT, n=int(1.0 / DT))      # settle on the ground
            poses = {b["name"]: b for b in session.send(op="poses")["bodies"]}
            was = {n: _spin(b["orientation_wxyz"]) for n, b in poses.items()}
            for station in STATIONS:
                session.send(op="operate", control=made["controls"][station["name"]],
                             sender="builder", seq=1, power=True, direction=1, setting=1.0)
            # Sampled and added up, not measured end to end: a top at 30 turns a
            # minute comes round 720 degrees in 4 s, and an angle read once at
            # the end wraps at 180 and says it hardly moved.
            turned_by = {name: 0.0 for name in was}
            for _ in range(int(WATCH_S / (24 * DT))):
                session.send(op="step", dt=DT, n=24)
                poses = {b["name"]: b for b in session.send(op="poses")["bodies"]}
                for name, body in poses.items():
                    if name not in was:
                        continue
                    now = _spin(body["orientation_wxyz"])
                    turned_by[name] += (now - was[name] + 540) % 360 - 180
                    was[name] = now
            for station in STATIONS:
                tag = station["name"]
                turned = {end: turned_by[f"{tag}: {end}"] for end in ("base", "top")}
                print(f"  {tag}: in {WATCH_S:.0f} s the base came round {turned['base']:+7.2f} deg "
                      f"and the top {turned['top']:+7.2f}")
                if abs(turned["top"]) < 90.0:
                    faults.append(f"{tag}: the top hardly moved ({turned['top']:+.1f} deg)")
                if turned["base"] * turned["top"] > 0:
                    faults.append(f"{tag}: both ends came round the same way; a motor pushes both ways")
                # Each end takes the share of the turn the other one's moment
                # gives it: the ratio should be the moments the other way about.
                if abs(turned["base"]) > 1e-6:
                    share = abs(turned["top"] / turned["base"])
                    print(f"    the top came round {share:.1f}x as far, where its moment is "
                          f"{station['share']:.1f}x the smaller")
                    if not 0.5 * station["share"] <= share <= 2.0 * station["share"]:
                        faults.append(f"{tag}: the ends split the turn {share:.1f} to 1, and their moments "
                                      f"say {station['share']:.1f} to 1")
            # Switched off, a real bearing brings it to rest. Every pin in every
            # machine room in this repo is frictionless, so nothing a motor
            # turns has ever stopped by itself; these have working bearings.
            for station in STATIONS:
                session.send(op="operate", control=made["controls"][station["name"]],
                             sender="builder", seq=2, power=False, direction=0, setting=1.0)
            # How far each still turns in a quarter of a second, until none of
            # them turns as much as a degree: a pose says where a thing is, not
            # how fast it is going, so this is measured from the angle itself.
            ran_down, went_on = 0.0, {}
            for _ in range(int(60.0 / (24 * DT))):
                session.send(op="step", dt=DT, n=24)
                ran_down += 24 * DT
                poses = {b["name"]: b for b in session.send(op="poses")["bodies"]}
                fastest = 0.0
                for name in was:
                    now = _spin(poses[name]["orientation_wxyz"])
                    step = (now - was[name] + 540) % 360 - 180
                    was[name] = now
                    went_on.setdefault(name, 0.0)
                    went_on[name] += step
                    fastest = max(fastest, abs(step))
                if fastest < 1.0:
                    break
            print(f"  switched off, everything came to rest in {ran_down:.1f} s, "
                  + ", ".join(f"{st['name']} turning {went_on[st['name'] + ': top']:+.0f} deg more"
                              for st in STATIONS))
            if ran_down >= 59.0:
                faults.append("switched off, it was still turning after a minute: the bearings do nothing")
        finally:
            session.close()
    return faults


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", required=True, type=Path)
    args = parser.parse_args(argv)

    print("tests-motor")
    room = compose()
    validated = fracture_lab.validate(room)
    faults = watch(args.engine.resolve(), validated)
    if faults:
        for fault in faults:
            print(f"  WRONG: {fault}")
        return 1
    ROOMS.mkdir(parents=True, exist_ok=True)
    (ROOMS / "tests-motor.json").write_text(json.dumps(room, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"  wrote {ROOMS / 'tests-motor.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
