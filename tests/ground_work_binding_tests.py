"""Tools that work the ground, through the public C ABI and the Python binding.

tests/ground_work_tests.cpp pins the physics. This is the BOUNDARY: a program
holding nothing but banjo.h gives a one-piece oak pick a point, takes it by its
grip, swings it at soil and at rock, pries the soil, and reads back what the
ground did -- the same capability the playground reaches with a mouse, reached
from a C header. docs/ground-work.md.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bindings" / "python"))

import banjo  # noqa: E402

CELL_M = 0.04
DT = 1.0 / 240.0


def require(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"[FAIL] {message}")


def tick(world: banjo.World, steps: int = 1) -> None:
    """Step, answering a break by running it, as the room does."""
    for _ in range(steps):
        if world.step(DT) != banjo.BREAK_PENDING:
            continue
        for name in world.breakable():
            world.fracture(name)


def until_the_stroke_ends(world: banjo.World, most: int = 960, settle: int = 60) -> str:
    for _ in range(most):
        tick(world)
        if not world.hand().stroking:
            break
    ended = world.hand().stroke_ended
    if world.held:
        world.move_held(world.hand().grip_m)
    tick(world, settle)
    return ended


def clearing(soil_m: float) -> dict:
    """Level ground -- rock, then soil -- with a one-piece oak pick in the air
    above it: a handle along x and an arm hanging from its end, joined."""
    top = soil_m
    return {"terrain": {"generate": {"kind": "flat", "nx": 48, "nz": 48, "cell_m": 0.1,
                                     "soil_m": soil_m, "sand_m": 0.0, "discharge_m3_s": 0.0}},
            "bodies": [{"name": "pick", "shape": "box", "material": "oak", "join": "pick",
                        "dimensions_m": [0.8, 0.04, 0.04], "center_m": [0.0, top + 1.02, 0.02]},
                       {"name": "pick arm", "shape": "box", "material": "oak", "join": "pick",
                        "dimensions_m": [0.04, 0.28, 0.04], "center_m": [0.38, top + 0.86, 0.02]}]}


def swing(world: banjo.World, top: float) -> list[banjo.GroundWork]:
    grip = (-0.36, top + 1.02, 0.02)
    point = world.tool_point("pick", (0.38, top + 0.72, 0.02), (0.0, -1.0, 0.0), width_m=0.04,
                             thickness_m=0.04, angle_deg=30.0, length_m=0.2, grip_m=grip)
    require(point > 0, "the pick would not take a point")
    world.wield("pick", grip)
    world.strike(target_m=(0.3, top, 0.02), shoulder_m=(-0.9, top + 1.45, 0.02), speed_m_s=4.0,
                 raise_deg=110.0)
    until_the_stroke_ends(world, 480, 120)
    return world.ground_work()


def a_point_is_declared_and_reported_back() -> None:
    with banjo.World(clearing(0.4), cell_size_m=CELL_M) as world:
        point = world.tool_point("pick", (0.38, 1.12, 0.02), (0.0, -1.0, 0.0), width_m=0.04,
                                 thickness_m=0.04, angle_deg=30.0, length_m=0.2,
                                 grip_m=(-0.36, 1.42, 0.02))
        points = world.tool_points()
        require(len(points) == 1 and points[0].id == point and points[0].body == "pick",
                "the point was not reported back")
        p = points[0]
        require(p.material == "oak" and p.attached and p.in_ == "", "the point's state came back wrong")
        require(abs(p.length_m - 0.2) < 1e-12 and abs(p.width_m - 0.04) < 1e-12,
                "the point's shape came back wrong")
        require(abs(p.tip_m[1] - 1.12) < 1e-6 and p.pointing[1] < -0.999, "the tip is not where it was put")
        # A point in the air beside the body, or pointing back into it, is refused.
        try:
            world.tool_point("pick", (0.38, 0.9, 0.5), (0.0, -1.0, 0.0))
        except banjo.BanjoError as refused:
            require("matter" in str(refused), f"a point off the body was refused without saying why: {refused}")
        else:
            require(False, "a point off the body was accepted")
        try:
            world.tool_point("pick", (0.38, 1.12, 0.02), (0.0, 1.0, 0.0))
        except banjo.BanjoError as refused:
            # Pointing up from the end of the arm: there is no matter behind the
            # tip that way, and the matter it points into is the arm itself.
            require("no matter behind the tip" in str(refused) or "into the body" in str(refused),
                    f"a point facing in was refused without saying why: {refused}")
        else:
            require(False, "a point pointing back into its body was accepted")
        try:
            # The grip with its height and depth swapped, as the room's chat once
            # gave one: in the air, where no hand could take hold of the pick.
            world.tool_point("pick", (0.38, 1.12, 0.02), (0.0, -1.0, 0.0), grip_m=(-0.36, 0.02, 1.42))
        except banjo.BanjoError as refused:
            require("the grip is not on the body's matter" in str(refused),
                    f"a grip off the body was refused without saying why: {refused}")
        else:
            require(False, "a grip off the body was accepted")
        print(f"  declared: point {p.id} on {p.body} ({p.material}), tip at "
              f"[{p.tip_m[0]:.2f}, {p.tip_m[1]:.2f}, {p.tip_m[2]:.2f}]")


def a_swing_into_soil_goes_in_and_onto_rock_is_stopped() -> None:
    with banjo.World(clearing(0.4), cell_size_m=CELL_M) as world:
        work = swing(world, 0.4)
        require(work, "the swing into soil met nothing")
        w = work[0]
        print(f"  soil: {w.kind}, {w.ground}, closing {w.closing_speed_m_s:.2f} m/s, "
              f"{1000 * w.depth_m:.1f} mm in, {w.work_j:.2f} J, peak {w.peak_force_n:.0f} N, "
              f"model {w.model}")
        require(w.ground == "soil" and w.open and w.depth_m > 0.03 and w.work_j > 0.0,
                "the point did not go into the soil")
        require(w.model == "ground-work-v1", "the answer does not name its model")
        points = world.tool_points()
        require(points[0].in_ == "soil" and points[0].depth_m > 0.0,
                "the point does not say it is in the soil")
    with banjo.World(clearing(0.0), cell_size_m=CELL_M) as world:
        work = swing(world, 0.0)
        require(work, "the swing onto rock met nothing")
        w = work[0]
        print(f"  rock: {w.kind}, {w.ground}: {w.why}")
        require(w.kind == "stopped" and w.supported and w.loosened_m3 == 0.0,
                "an oak point on rock was not stopped")


def a_pry_breaks_soil_out_and_it_is_carried() -> None:
    with banjo.World(clearing(0.4), cell_size_m=CELL_M) as world:
        work = swing(world, 0.4)
        require(work and work[0].open, "the pick is not in the soil to pry with")
        before = world.environment_report()["ground"]["carried"]
        world.strike(shoulder_m=(-0.9, 1.85, 0.02), speed_m_s=1.2, lever=True, lever_deg=40.0)
        until_the_stroke_ends(world, 960, 30)
        if world.ground_work()[0].open:
            grip = world.hand().grip_m
            world.stroke([grip, (grip[0], grip[1] + 0.4, grip[2])], 0.6, 4.0, 0.05, False, 3.0)
            until_the_stroke_ends(world, 960, 30)
        w = world.ground_work()[0]
        after = world.environment_report()["ground"]["carried"]
        gained = (after["soil_m3"] - before["soil_m3"]) + (after["sand_m3"] - before["sand_m3"])
        print(f"  pried: {w.kind}, {1000 * w.sideways_m:.0f} mm sideways at {1000 * w.depth_m:.0f} mm, "
              f"{w.breakout_work_j:.2f} J of it prying; loosened {1000 * w.loosened_m3:.2f} L "
              f"({w.loosened_kg:.2f} kg); carried {1000 * gained:.2f} L more")
        require(not w.open and w.kind == "broke out" and w.loosened_m3 > 0.0,
                "the pry broke nothing out")
        require(abs(gained - w.loosened_m3) < 1e-12, "what is carried is not what the pry took out")
        # Read, then forgotten: a closed meeting goes, an open one would stay.
        world.forget_ground_work()
        require(world.ground_work() == [], "a closed meeting was not forgotten")


def a_lever_needs_a_point_in_the_ground() -> None:
    with banjo.World(clearing(0.4), cell_size_m=CELL_M) as world:
        grip = (-0.36, 1.42, 0.02)
        world.tool_point("pick", (0.38, 1.12, 0.02), (0.0, -1.0, 0.0), length_m=0.2, grip_m=grip)
        try:
            world.strike(shoulder_m=(-0.9, 1.85, 0.02), lever=True)
        except banjo.BanjoError as refused:
            require("wield" in str(refused), f"a lever with nothing held said: {refused}")
        else:
            require(False, "a lever with nothing in the hand was accepted")
        world.wield("pick", grip)
        try:
            world.strike(shoulder_m=(-0.9, 1.85, 0.02), lever=True)
        except banjo.BanjoError as refused:
            require("not in the ground" in str(refused), f"a lever in the air said: {refused}")
            print(f"  refused: {refused}")
        else:
            require(False, "a lever with the point in the air was accepted")


if __name__ == "__main__":
    for check in (a_point_is_declared_and_reported_back,
                  a_swing_into_soil_goes_in_and_onto_rock_is_stopped,
                  a_pry_breaks_soil_out_and_it_is_carried,
                  a_lever_needs_a_point_in_the_ground):
        print(check.__name__.replace("_", " "))
        check()
        print("  ok")
    print("all ground work binding checks passed")
