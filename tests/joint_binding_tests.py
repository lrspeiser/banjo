"""Joints through the public C ABI and the Python binding.

The engine's own tests (tests/hinge_tests.cpp) and the scene's
(tests/scene_joint_tests.cpp) already pin the physics. This is about the
BOUNDARY: an outside program, holding nothing but banjo.h, builds a gateway,
hangs a gate on it, pushes it open, and reads back where it got to.

That is the half of the goal that is not the browser. A medieval playground
people and programs can both build in means the same capability has to be
reachable from a C header as from a mouse, and this is the test that says it is.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bindings" / "python"))

import banjo  # noqa: E402


def require(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"[FAIL] {message}")


def doorway() -> dict:
    """A post with a gate beside it, and a block to shove the gate with.

    The gate is clear of the post in z rather than sharing its space -- a leaf
    overlapping its own frame is jammed against it, and jammed is exactly what a
    working hinge looks like from the outside -- and it hangs clear of the
    ground, because a gate resting on the floor is held by the floor.
    """
    # METRES. The library's scene schema is dimensions_m / center_m, not the
    # playground's millimetres -- and an unknown key is not an error, it is a
    # default, so the millimetre spelling opens quietly as three 100 mm cubes
    # all sitting at the origin. Which is what it did, and what it looked like
    # from outside was a hinge that did not hold.
    return {
        "bodies": [
            {"name": "post", "shape": "box", "material": "concrete",
             "dimensions_m": [0.16, 2.0, 0.16], "center_m": [-0.08, 1.0, 0.0],
             "anchored": True},
            {"name": "gate", "shape": "box", "material": "oak",
             "dimensions_m": [1.2, 1.6, 0.08], "center_m": [0.6, 1.0, 0.12]},
            {"name": "fist", "shape": "box", "material": "iron",
             "dimensions_m": [0.2, 0.2, 0.2], "center_m": [0.6, 1.0, 1.2]},
        ],
    }


# Every extent above is a whole number of these, which the library insists on.
CELL_M = 0.04


def tick(world: banjo.World, steps: int = 1) -> None:
    """Step, answering the break handshake.

    A step that would break something is taken back and the clock does not move
    until the caller says fracture or decline. A program that only steps and
    says nothing therefore STOPS TIME the moment anything is hit hard enough to
    matter, and what that looks like from outside is a gate that will not swing.
    """
    for _ in range(steps):
        if world.step(1.0 / 240.0) != banjo.BREAK_PENDING:
            continue
        for name in world.breakable():
            world.decline_break(name)


def shove(world: banjo.World, through_m: float) -> None:
    """Walk the fist into the gate at a centimetre a step, and let go.

    A centimetre because the gate is 80 mm thick and a kinematically carried
    body does not sweep: moved further than the gate is thick in one step, the
    fist goes straight through without touching it.
    """
    world.grab("fist")
    start = (0.6, 1.0, 1.2)
    world.move_held(start)
    tick(world)
    finish = (start[0], start[1], 0.12 - through_m)
    steps = int(abs(finish[2] - start[2]) / 0.01)
    for i in range(1, steps + 1):
        part = i / steps
        world.move_held((start[0], start[1],
                         start[2] + part * (finish[2] - start[2])))
        tick(world)
    world.release()


def pin_of(world: banjo.World, joint: int) -> banjo.Joint:
    for pin in world.joints():
        if pin.id == joint:
            return pin
    raise SystemExit(f"[FAIL] there is no joint {joint}")


def a_gate_hung_through_the_abi_swings() -> None:
    with banjo.World(doorway(), cell_size_m=CELL_M) as world:
        require(world.joints() == [], "a fresh world reported pins it does not have")
        pin = world.hinge("post", "gate", at_m=(0.0, 1.0, 0.12),
                          axis=(0.0, 1.0, 0.0), lower_deg=0.0, upper_deg=100.0)
        require(pin > 0, "the gate would not hang on the post")
        require(len(world.joints()) == 1, "the pin was not reported after hanging")

        shove(world, 0.5)
        tick(world, 360)
        turned = abs(pin_of(world, pin).at)
        gate = next(b for b in world.bodies() if b.name == "gate")
        out = math.dist(gate.position_m, (0.0, 1.0, 0.12))
        print(f"  shoved through the ABI, the gate swung {turned:.2f} degrees; "
              f"its middle is {out:.3f} m from the pin")
        require(turned > 10.0, "the gate did not turn on its pin")
        require(abs(out - 0.6) < 0.06,
                "the gate's middle is no longer half a leaf from the pin, so it came off")
        require(pin_of(world, pin).attached, "the pin reported itself gone")


def limits_are_degrees() -> None:
    with banjo.World(doorway(), cell_size_m=CELL_M) as world:
        pin = world.hinge("post", "gate", at_m=(0.0, 1.0, 0.12),
                          axis=(0.0, 1.0, 0.0), lower_deg=0.0, upper_deg=30.0)
        shove(world, 1.4)
        tick(world, 240)
        turned = abs(pin_of(world, pin).at)
        print(f"  a gate stopped at 30 degrees, shoved well past it, reached {turned:.2f}")
        require(turned <= 31.0, "the gate went past the stop it was given")
        require(turned > 12.0, "it never got near the stop, so the shove proved nothing")


def the_pin_is_body_local() -> None:
    """A pin reports where it IS, not where it was put.

    This is the property that makes mechanisms work anywhere: the pin is written
    down in each body's own frame, so it travels with the wood. A gate that has
    swung 30 degrees has carried its own half of the pin round with it, and the
    pin is still in the same place in the post.
    """
    with banjo.World(doorway(), cell_size_m=CELL_M) as world:
        pin = world.hinge("post", "gate", at_m=(0.0, 1.0, 0.12),
                          axis=(0.0, 1.0, 0.0), lower_deg=0.0, upper_deg=100.0)
        was = pin_of(world, pin).at_m
        shove(world, 0.5)
        tick(world, 240)
        now = pin_of(world, pin)
        moved = math.dist(now.at_m, was)
        print(f"  after a {abs(now.at):.1f} degree swing the pin has moved "
              f"{moved * 1000:.1f} mm")
        # The post is anchored, so the pin's place in the world cannot change at
        # all -- however far the gate has gone round it.
        require(moved < 0.001, "the pin wandered while the gate swung on it")
        require(abs(now.axis[1] - 1.0) < 1e-6, "the pin's axis turned with the gate")


def a_stiff_pin_holds_and_a_free_one_does_not() -> None:
    """Friction is what makes a gate stay where it is put.

    Measured with a THROWN mass, not a carried one. A hand is infinitely strong
    -- the held body is re-asserted into place every step -- so it opens any
    gate however stiff the hinge is, and both frictions reach exactly the angle
    the hand walked to. Which is what happened here first: 25.35 degrees free
    and 26.98 stiff, a difference that was noise.

    What friction actually changes is what happens to MOMENTUM. So the fist is
    thrown instead: the same blow into a free hinge and into a stiff one, and
    the gap is the work the friction took out.
    """
    watched = {}
    for friction in (0.0, 400.0):
        scene = doorway()
        fist = next(b for b in scene["bodies"] if b["name"] == "fist")
        fist["center_m"] = [0.6, 1.0, 0.52]
        fist["velocity_m_s"] = [0.0, 0.0, -6.0]
        with banjo.World(scene, cell_size_m=CELL_M) as world:
            pin = world.hinge("post", "gate", at_m=(0.0, 1.0, 0.12),
                              axis=(0.0, 1.0, 0.0), lower_deg=0.0, upper_deg=170.0,
                              friction_n_m=friction)
            furthest = 0.0
            for _ in range(720):      # three seconds: the blow, and after it
                tick(world)
                furthest = max(furthest, abs(pin_of(world, pin).at))
            watched[friction] = (furthest, abs(pin_of(world, pin).at))
    free_far, free_end = watched[0.0]
    stiff_far, stiff_end = watched[400.0]
    print(f"  the same blow: free, the gate reached {free_far:.2f} degrees and "
          f"ended at {free_end:.2f}; stiff (400 N m), {stiff_far:.2f} and {stiff_end:.2f}")
    require(free_far > 5.0, "the blow did not open the gate at all")
    # What friction gives you is a gate that stays where it is left. Comparing
    # the FURTHEST angles instead does not say much: the free one only reaches
    # about 3 degrees further, which is inside what one blow's worth of noise
    # covers. The difference that is unmistakable is what happens afterwards --
    # the free gate drifts 13 degrees back off its furthest point and the stiff
    # one moves 2.
    require(abs(free_far - free_end) > 3.0 * abs(stiff_far - stiff_end),
            "the stiff hinge let the gate wander as much after the blow as the "
            "free one did, so friction is not holding anything")


def taking_the_pin_out_drops_it() -> None:
    with banjo.World(doorway(), cell_size_m=CELL_M) as world:
        pin = world.hinge("post", "gate", at_m=(0.0, 1.0, 0.12), axis=(0.0, 1.0, 0.0))
        tick(world, 240)
        hung = next(b for b in world.bodies() if b.name == "gate").position_m[1]
        world.unhinge(pin)
        tick(world, 600)
        gate = next(b for b in world.bodies() if b.name == "gate")
        fell = gate.position_m[1]
        # It hangs with 200 mm of air under it, so 200 mm is the whole fall
        # available and landing uses all of it. Measured against the clearance
        # rather than against a round number, because those are the same thing
        # here and a threshold of "0.2" sits exactly on the answer.
        clearance = hung - gate.dimensions_m[1] / 2.0
        print(f"  pin taken out: the gate went from y={hung:.3f} to y={fell:.3f}, "
              f"which is {(hung - fell) * 1000:.0f} mm of the {clearance * 1000:.0f} mm "
              f"it was hanging clear of the floor")
        require(hung - fell > 0.95 * clearance,
                "the gate stayed in the air with no pin holding it")
        # And it stays standing on its own 80 mm edge, which is right: a level
        # slab on a level floor has nothing to tip it. It was tempting to assert
        # that it topples, and that would have been asserting a wobble the
        # engine has no reason to produce.
        require(world.joints() == [], "the pin is still listed after being taken out")


def a_pin_refuses_what_it_cannot_hold() -> None:
    with banjo.World(doorway(), cell_size_m=CELL_M) as world:
        for why, call in (
            ("a body that does not exist",
             lambda: world.hinge("post", "nothing at all", at_m=(0, 1, 0))),
            ("a body hung on itself",
             lambda: world.hinge("gate", "gate", at_m=(0, 1, 0))),
            ("an axis with no direction",
             lambda: world.hinge("post", "gate", at_m=(0, 1, 0.12), axis=(0, 0, 0))),
            ("limits the wrong way round",
             lambda: world.hinge("post", "gate", at_m=(0, 1, 0.12),
                                 lower_deg=90.0, upper_deg=-90.0)),
        ):
            try:
                call()
            except banjo.BanjoError:
                continue
            raise SystemExit(f"[FAIL] the engine accepted {why}")
        require(world.joints() == [], "a refused pin was recorded anyway")
        print("  a pin refuses a missing body, a body on itself, no axis, "
              "and backwards limits")


def gateway() -> dict:
    """A pair of jambs with an iron grate resting on the ground between them."""
    return {
        "bodies": [
            {"name": "left jamb", "shape": "box", "material": "concrete",
             "dimensions_m": [0.16, 3.0, 0.16], "center_m": [-0.8, 1.5, 0.0],
             "anchored": True},
            {"name": "right jamb", "shape": "box", "material": "concrete",
             "dimensions_m": [0.16, 3.0, 0.16], "center_m": [0.8, 1.5, 0.0],
             "anchored": True},
            {"name": "grate", "shape": "box", "material": "iron",
             "dimensions_m": [1.2, 1.6, 0.12], "center_m": [0.0, 0.8, 0.2]},
        ],
    }


# 1.2 x 1.6 x 0.12 m of iron is 0.2304 cubic metres at 7,870 kg/m3: 1,813 kg,
# and 17.8 kN of weight. Every friction below is sized against that, because a
# groove gripping at a tenth of what it holds reads as friction being broken.
GRATE_WEIGHT_N = 1.2 * 1.6 * 0.12 * 7870.0 * 9.81


def groove_of(world: banjo.World, joint: int) -> banjo.Joint:
    for held in world.joints():
        if held.id == joint:
            return held
    raise SystemExit(f"[FAIL] there is no joint {joint}")


def haul(world: banjo.World, by_m: float) -> None:
    """Pull the grate up by hand, a centimetre a step, and let go."""
    world.grab("grate")
    start = next(b for b in world.bodies() if b.name == "grate").position_m
    steps = max(1, int(by_m / 0.01))
    for i in range(1, steps + 1):
        world.move_held((start[0], start[1] + by_m * i / steps, start[2]))
        tick(world)
    world.release()


def a_raised_grate_falls_when_you_let_go() -> None:
    """The whole claim, through the public ABI.

    Nothing in the library knows what a portcullis is. The grate falls because
    it is 1.8 tonnes of iron free to move along a vertical line and there is
    nothing holding it up.
    """
    with banjo.World(gateway(), cell_size_m=CELL_M) as world:
        groove = world.slide("left jamb", "grate", at_m=(0.0, 0.8, 0.2),
                             axis=(0.0, 1.0, 0.0), lower_m=0.0, upper_m=1.5)
        require(groove > 0, "the grate would not go into its grooves")
        require(groove_of(world, groove).kind == "slider",
                "a slide came back calling itself something else")

        down = next(b for b in world.bodies() if b.name == "grate").position_m[1]
        haul(world, 1.2)
        up = next(b for b in world.bodies() if b.name == "grate").position_m[1]
        tick(world, 600)
        after = next(b for b in world.bodies() if b.name == "grate").position_m[1]
        print(f"  hauled from y={down:.3f} to y={up:.3f}; two and a half seconds "
              f"after letting go it is at y={after:.3f}")
        require(up > down + 1.0, "the haul did not lift it")
        require(after < down + 0.1, "it was let go over a metre up and stayed there")


def travel_is_metres_and_it_holds() -> None:
    with banjo.World(gateway(), cell_size_m=CELL_M) as world:
        groove = world.slide("left jamb", "grate", at_m=(0.0, 0.8, 0.2),
                             axis=(0.0, 1.0, 0.0), lower_m=0.0, upper_m=0.6)
        haul(world, 2.0)          # hauled well past the 600 mm it is allowed
        reached = groove_of(world, groove).at
        print(f"  a grate with 600 mm of travel, hauled 2 m, reached {reached:.3f} m")
        require(reached <= 0.62, "it went further than its grooves allow")
        require(reached > 0.5, "it barely moved, so the haul proved nothing")


def friction_is_what_makes_it_stay() -> None:
    left_at = {}
    for friction in (0.0, 2.0 * GRATE_WEIGHT_N):
        with banjo.World(gateway(), cell_size_m=CELL_M) as world:
            groove = world.slide("left jamb", "grate", at_m=(0.0, 0.8, 0.2),
                                 axis=(0.0, 1.0, 0.0), lower_m=0.0, upper_m=1.5,
                                 friction_n=friction)
            haul(world, 1.0)
            tick(world, 600)
            left_at[friction] = groove_of(world, groove).at
    free, stiff = left_at[0.0], left_at[2.0 * GRATE_WEIGHT_N]
    print(f"  the grate weighs {GRATE_WEIGHT_N / 1000:.1f} kN. Hauled 1 m and let "
          f"go: a free groove left it {free:.3f} m up, one gripping at twice its "
          f"weight left it {stiff:.3f} m up")
    require(stiff > free + 0.5,
            "the stiff groove let the grate drop as far as the free one, so "
            "friction is not holding anything")


def a_slide_only_moves_along_its_own_line() -> None:
    with banjo.World(gateway(), cell_size_m=CELL_M) as world:
        world.slide("left jamb", "grate", at_m=(0.0, 0.8, 0.2),
                    axis=(0.0, 1.0, 0.0), lower_m=0.0, upper_m=1.5)
        was = next(b for b in world.bodies() if b.name == "grate").position_m
        world.grab("grate")
        for i in range(1, 121):
            world.move_held((was[0] + 0.02 * i, was[1], was[2] + 0.02 * i))
            tick(world)
        world.release()
        tick(world, 240)
        now = next(b for b in world.bodies() if b.name == "grate").position_m
        print(f"  dragged 2.4 m sideways and 2.4 m forward, the grate moved "
              f"{abs(now[0] - was[0]) * 1000:.0f} mm in x and "
              f"{abs(now[2] - was[2]) * 1000:.0f} mm in z")
        require(abs(now[0] - was[0]) < 0.02, "it came out of its grooves sideways")
        require(abs(now[2] - was[2]) < 0.02, "it came out of its grooves forwards")


def a_slide_refuses_what_it_cannot_hold() -> None:
    with banjo.World(gateway(), cell_size_m=CELL_M) as world:
        for why, call in (
            ("a body that does not exist",
             lambda: world.slide("left jamb", "no such grate", at_m=(0, 1, 0))),
            ("a body sliding in itself",
             lambda: world.slide("grate", "grate", at_m=(0, 1, 0))),
            ("an axis with no direction",
             lambda: world.slide("left jamb", "grate", at_m=(0, 0.8, 0.2),
                                 axis=(0, 0, 0))),
            ("travel the wrong way round",
             lambda: world.slide("left jamb", "grate", at_m=(0, 0.8, 0.2),
                                 lower_m=1.0, upper_m=-1.0)),
        ):
            try:
                call()
            except banjo.BanjoError:
                continue
            raise SystemExit(f"[FAIL] the engine accepted {why}")
        require(world.joints() == [], "a refused slide was recorded anyway")
        print("  a slide refuses a missing body, a body in itself, no axis, "
              "and backwards travel")


def gantry() -> dict:
    """A beam overhead with a weight a metre under it, and nothing between."""
    return {
        "bodies": [
            {"name": "beam", "shape": "box", "material": "oak",
             "dimensions_m": [2.0, 0.2, 0.2], "center_m": [0.0, 4.0, 0.0],
             "anchored": True},
            {"name": "weight", "shape": "box", "material": "iron",
             "dimensions_m": [0.2, 0.2, 0.2], "center_m": [0.0, 3.0, 0.0]},
        ],
    }


# 0.2 m of iron is 8 litres at 7,870 kg/m3: 63 kg and 618 N. Every rope below is
# rated against that, because a rope's rating only means something next to what
# it is asked to hold.
WEIGHT_N = 0.2 ** 3 * 7870.0 * 9.81


def rope_of(world: banjo.World, joint: int) -> banjo.Joint:
    for held in world.joints():
        if held.id == joint:
            return held
    raise SystemExit(f"[FAIL] there is no joint {joint}")


def a_rope_pulls_but_does_not_push() -> None:
    """The one asymmetry that makes a rope a rope.

    Tied a metre under the beam it hangs -- so it pulls. Lifted up under the
    beam it falls -- so it does not push. A rod would do the first and not the
    second, and a rod is what a distance constraint is if you give it a minimum
    as well as a maximum.
    """
    with banjo.World(gantry(), cell_size_m=CELL_M) as world:
        rope = world.tie("beam", "weight", at_a_m=(0.0, 3.9, 0.0),
                         at_b_m=(0.0, 3.0, 0.0))
        require(rope > 0, "the weight would not tie to the beam")
        require(rope_of(world, rope).kind == "link",
                "a tie came back as the wrong kind of joint")
        tick(world, 720)
        hung = next(b for b in world.bodies() if b.name == "weight").position_m[1]
        require(hung > 2.9, f"the weight fell through its own rope, to {hung}")

        # Now lift it to just under the beam and let go.
        world.grab("weight")
        for i in range(1, 81):
            world.move_held((0.0, 3.0 + 0.01 * i, 0.0))
            tick(world)
        lifted = next(b for b in world.bodies() if b.name == "weight").position_m[1]
        world.release()
        tick(world, 480)
        fell = next(b for b in world.bodies() if b.name == "weight").position_m[1]
        print(f"  tied a metre down it hangs at y={hung:.3f}; lifted to "
              f"y={lifted:.3f} and released it falls back to y={fell:.3f}")
        require(lifted > 3.6, "the lift did not happen")
        require(fell < 3.1, "the weight did not fall: the rope is pushing it out")


def slack_carries_nothing() -> None:
    with banjo.World(gantry(), cell_size_m=CELL_M) as world:
        rope = world.tie("beam", "weight", at_a_m=(0.0, 3.9, 0.0),
                         at_b_m=(0.0, 3.0, 0.0), length_m=2.0)
        tick(world, 60)
        while_falling = rope_of(world, rope).tension_n
        tick(world, 720)
        caught = rope_of(world, rope)
        print(f"  with 2 m of rope on a 0.9 m drop, it carried "
              f"{while_falling:.2f} N on the way down and ended "
              f"{caught.at:.3f} m from its anchor")
        require(while_falling < 1.0,
                "the rope was pulling while it still had slack, so slack is not slack")
        require(abs(caught.at - 2.0) < 0.2,
                "it ended somewhere other than the end of its rope")


def tension_is_the_load() -> None:
    with banjo.World(gantry(), cell_size_m=CELL_M) as world:
        rope = world.tie("beam", "weight", at_a_m=(0.0, 3.9, 0.0),
                         at_b_m=(0.0, 3.0, 0.0))
        tick(world, 960)
        carrying = rope_of(world, rope).tension_n
        print(f"  the weight is {WEIGHT_N:.1f} N and the rope reports "
              f"{carrying:.1f} N")
        require(0.5 * WEIGHT_N < carrying < 2.0 * WEIGHT_N,
                "a rope holding a 618 N weight is not reporting anything like 618 N")


def a_rope_parts_when_overloaded() -> None:
    with banjo.World(gantry(), cell_size_m=CELL_M) as world:
        rope = world.tie("beam", "weight", at_a_m=(0.0, 3.9, 0.0),
                         at_b_m=(0.0, 3.0, 0.0), breaking_tension_n=0.25 * WEIGHT_N)
        tick(world, 480)
        after = next(b for b in world.bodies() if b.name == "weight").position_m[1]
        parted = rope_of(world, rope)
        print(f"  a {WEIGHT_N:.0f} N weight on a rope rated for "
              f"{0.25 * WEIGHT_N:.0f} N: it fell to y={after:.3f}, and the rope "
              f"reports attached={parted.attached}")
        require(after < 2.0, "the rope held four times what it was rated for")
        require(not parted.attached, "the rope parted but still says it is holding")
        require(parted.breaks_at_n > 0.0, "the rope forgot what it was rated for")


def a_chain_carries_what_hangs_below_each_link() -> None:
    """Eight links, and the tension is a staircase.

    This is the test that says a chain is made of bodies rather than being a
    chain-shaped object: each link carries everything below it, so the tensions
    step down by exactly one link's weight all the way to the bottom.
    """
    scene = gantry()
    for i in range(8):
        scene["bodies"].append(
            {"name": f"link {i + 1}", "shape": "box", "material": "iron",
             "dimensions_m": [0.08, 0.08, 0.08],
             "center_m": [0.5, 3.8 - 0.16 * i, 0.0]})
    with banjo.World(scene, cell_size_m=0.04) as world:
        ropes = []
        for i in range(8):
            above = "beam" if i == 0 else f"link {i}"
            top = 3.9 if i == 0 else 3.8 - 0.16 * (i - 1)
            ropes.append(world.tie(above, f"link {i + 1}",
                                   at_a_m=(0.5, top, 0.0),
                                   at_b_m=(0.5, 3.8 - 0.16 * i, 0.0)))
        require(all(r > 0 for r in ropes), "the chain would not tie together")
        tick(world, 960)
        carried = [rope_of(world, r).tension_n for r in ropes]
        print("  eight links, tension down the chain: "
              + ", ".join(f"{t:.0f}" for t in carried) + " N")
        for upper, lower in zip(carried, carried[1:]):
            require(upper > lower,
                    "a link lower down the chain is carrying more than the one "
                    "above it, which is not how hanging works")
        steps = [a - b for a, b in zip(carried, carried[1:])]
        spread = max(steps) - min(steps)
        require(spread < 0.15 * max(steps),
                f"the steps between links are not even ({steps}), so the links "
                f"are not each carrying one more link's weight")


def a_tie_refuses_what_it_cannot_hold() -> None:
    with banjo.World(gantry(), cell_size_m=CELL_M) as world:
        for why, call in (
            ("a body that does not exist",
             lambda: world.tie("beam", "no such weight", (0, 3.9, 0), (0, 3, 0))),
            ("a body tied to itself",
             lambda: world.tie("weight", "weight", (0, 3.9, 0), (0, 3, 0))),
            ("a negative breaking strength",
             lambda: world.tie("beam", "weight", (0, 3.9, 0), (0, 3, 0),
                               breaking_tension_n=-5.0)),
        ):
            try:
                call()
            except banjo.BanjoError:
                continue
            raise SystemExit(f"[FAIL] the engine accepted {why}")
        require(world.joints() == [], "a refused tie was recorded anyway")
        print("  a tie refuses a missing body, a body tied to itself, and a "
              "negative strength")


def hoist(load_m=(0.2, 0.2, 0.2), weight_m=(0.2, 0.2, 0.2)) -> dict:
    """A gantry with a load under one end and a counterweight under the other.

    BOXES rather than cubes, because mass goes as the cube of a side and every
    extent has to be a whole number of cells: a cube of half the mass has a side
    of 3.17 cells and does not exist. Flattening one axis gives exact ratios --
    4x4x4 is 64 cells and 4x2x4 is 32, which is exactly half however the engine
    rounds.
    """
    return {
        "bodies": [
            {"name": "beam", "shape": "box", "material": "oak",
             "dimensions_m": [3.0, 0.2, 0.2], "center_m": [0.0, 5.0, 0.0],
             "anchored": True},
            {"name": "load", "shape": "box", "material": "iron",
             "dimensions_m": list(load_m), "center_m": [-1.0, 3.0, 0.0]},
            {"name": "counterweight", "shape": "box", "material": "iron",
             "dimensions_m": list(weight_m), "center_m": [1.0, 3.0, 0.0]},
        ],
    }


OVER_LOAD = (-1.0, 4.9, 0.0)
OVER_WEIGHT = (1.0, 4.9, 0.0)


def a_hoist_lifts_the_other_end() -> None:
    with banjo.World(hoist(), cell_size_m=0.05) as world:
        rope = world.reeve("load", "counterweight", at_a_m=(-1.0, 3.0, 0.0),
                           at_b_m=(1.0, 3.0, 0.0), over_a_m=OVER_LOAD,
                           over_b_m=OVER_WEIGHT)
        require(rope > 0, "the rope would not reeve")
        held = next(j for j in world.joints() if j.id == rope)
        require(held.kind == "pulley", "a pulley came back as the wrong kind")

        load_was = next(b for b in world.bodies() if b.name == "load").position_m[1]
        world.grab("counterweight")
        for i in range(1, 81):
            world.move_held((1.0, 3.0 - 0.01 * i, 0.0))
            tick(world)
        world.release()
        tick(world, 120)
        load_now = next(b for b in world.bodies() if b.name == "load").position_m[1]
        rove = next(j for j in world.joints() if j.id == rope)
        print(f"  hauled the counterweight down, the load rose "
              f"{load_now - load_was:.3f} m; the rope is {rove.at:.3f} m of "
              f"{rove.upper:.3f}")
        require(load_now > load_was + 0.4, "the load did not come up")
        require(rove.at <= rove.upper + 0.02,
                "the rope got longer than it is, so the length relationship is "
                "not being held")


def mechanical_advantage_has_a_side() -> None:
    """The ratio applies to B's run, so B is the end with the advantage.

    Getting this backwards is easy and quiet: a 618 N load against a 309 N
    counterweight "at a ratio of 2" fell 2.9 m the first time, because in that
    arrangement the ratio asks for TWICE the weight rather than half.
    """
    # Load at b -- the advantaged end -- with half its weight opposing it.
    with banjo.World(hoist(load_m=(0.2, 0.1, 0.2), weight_m=(0.2, 0.2, 0.2)),
                     cell_size_m=0.05) as world:
        # "load" is the light one here; the heavy body is at a. Name them by
        # what they do rather than by the scene's labels.
        rope = world.reeve("load", "counterweight", at_a_m=(-1.0, 3.0, 0.0),
                           at_b_m=(1.0, 3.0, 0.0), over_a_m=OVER_LOAD,
                           over_b_m=OVER_WEIGHT, ratio=2.0)
        require(rope > 0, "the rope would not reeve")
        heavy_was = next(b for b in world.bodies()
                         if b.name == "counterweight").position_m[1]
        tick(world, 960)
        heavy_now = next(b for b in world.bodies()
                         if b.name == "counterweight").position_m[1]
        print(f"  a 618 N load at the advantaged end against a 309 N weight at "
              f"the other, ratio 2: it moved {abs(heavy_now - heavy_was) * 1000:.0f} mm")
        require(abs(heavy_now - heavy_was) < 0.08,
                "half the weight did not balance the load at a ratio of two, so "
                "the mechanical advantage is not there or is on the wrong side")


def a_hoist_refuses_what_it_cannot_reeve() -> None:
    with banjo.World(hoist(), cell_size_m=0.05) as world:
        for why, call in (
            ("a body that does not exist",
             lambda: world.reeve("beam", "nothing", (0, 4, 0), (0, 3, 0),
                                 OVER_LOAD, OVER_WEIGHT)),
            ("a body rove to itself",
             lambda: world.reeve("load", "load", (0, 4, 0), (0, 3, 0),
                                 OVER_LOAD, OVER_WEIGHT)),
            ("a ratio of zero",
             lambda: world.reeve("load", "counterweight", (0, 4, 0), (0, 3, 0),
                                 OVER_LOAD, OVER_WEIGHT, ratio=0.0)),
        ):
            try:
                call()
            except banjo.BanjoError:
                continue
            raise SystemExit(f"[FAIL] the engine accepted {why}")
        require(world.joints() == [], "a refused pulley was recorded anyway")
        print("  a pulley refuses a missing body, a body rove to itself, and a "
              "ratio of zero")


def loaded_shelf(crates: int, crate_m: float = 0.3) -> dict:
    """A stone shelf on two piers with crates stacked in the middle.

    Stone rather than oak: concrete takes 3 MPa in tension against oak's 90, so
    a shelf you can overload with a handful of crates is a stone one. In oak the
    same shelf would want eighteen tonnes.
    """
    scene = {
        "bodies": [
            {"name": "left pier", "shape": "box", "material": "iron",
             "dimensions_m": [0.2, 0.4, 0.3], "center_m": [-0.6, 0.2, 0.0],
             "anchored": True},
            {"name": "right pier", "shape": "box", "material": "iron",
             "dimensions_m": [0.2, 0.4, 0.3], "center_m": [0.6, 0.2, 0.0],
             "anchored": True},
            {"name": "shelf", "shape": "box", "material": "concrete",
             "dimensions_m": [1.4, 0.1, 0.3], "center_m": [0.0, 0.45, 0.0]},
        ],
    }
    for i in range(crates):
        scene["bodies"].append(
            {"name": f"crate {i + 1}", "shape": "box", "material": "iron",
             "dimensions_m": [crate_m] * 3,
             "center_m": [0.0, 0.5 + crate_m * (0.5 + i), 0.0]})
    return scene


def a_loaded_shelf_is_reported_without_being_struck() -> None:
    """The one kind of break the contact ledger cannot see.

    Nothing is dropped on the shelf. The crates are there when the world opens,
    they settle, and then nothing happens at all -- which is exactly the problem
    this answers: no contact, no impact, no reason for anything to ask.
    """
    with banjo.World(loaded_shelf(1, 0.2), cell_size_m=0.05) as world:
        tick(world, 480)
        require(world.overloaded() == [],
                "a shelf holding one crate was called overloaded")

    with banjo.World(loaded_shelf(5, 0.3), cell_size_m=0.05) as world:
        tick(world, 480)
        sagging = world.overloaded()
        require(len(sagging) == 1, f"expected one overloaded thing, got {sagging}")
        shelf = sagging[0]
        print(f"  the shelf carries {shelf.carrying_n:.0f} N over "
              f"{shelf.span_m:.2f} m: {shelf.stress_pa / 1e6:.2f} MPa against "
              f"concrete's {shelf.strength_pa / 1e6:.0f}")
        require(shelf.name == "shelf", "the wrong thing was reported")
        require(shelf.stress_pa > shelf.strength_pa,
                "it was reported without being over its strength")
        # It is offered for breaking through the ordinary door.
        require("shelf" in world.breakable(),
                "the shelf is overloaded but was never offered for breaking")
        # And it actually fails, with its load in the island.
        pieces = world.fracture("shelf")
        print(f"    put into the lattice under its load: {pieces} pieces")
        require(pieces > 1,
                "the lattice gave an overloaded shelf back whole, so the load is "
                "not reaching the island")


def bracket_on_a_wall(load_m=(0.2, 0.2, 0.2)) -> dict:
    return {
        "bodies": [
            {"name": "wall", "shape": "box", "material": "oak",
             "dimensions_m": [0.2, 3.0, 1.0], "center_m": [0.0, 1.5, 0.0],
             "anchored": True},
            {"name": "bracket", "shape": "box", "material": "iron",
             "dimensions_m": list(load_m),
             "center_m": [0.15 + load_m[0] / 2, 2.0, 0.0]},
        ],
    }


def a_fixing_tells_tension_from_shear() -> None:
    """The two are separate numbers because they fail at different loads.

    A bracket hanging off a wall puts its whole weight ACROSS the peg and
    nothing along it. So a peg with no tension strength at all holds it, and a
    peg with no shear strength gives way -- which could not come out both ways
    if the two were one number.
    """
    weight = 0.2 ** 3 * 7870.0 * 9.81      # 618 N of iron
    with banjo.World(bracket_on_a_wall(), cell_size_m=0.05) as world:
        peg = world.fix("wall", "bracket", at_m=(0.15, 2.0, 0.0),
                        axis=(1.0, 0.0, 0.0),
                        holds_tension_n=0.25 * weight, holds_shear_n=1.0e6)
        require(peg > 0, "the bracket would not peg to the wall")
        tick(world, 480)
        held = next(j for j in world.joints() if j.id == peg)
        print(f"  weak along the peg: it {'held' if held.attached else 'gave way'}, "
              f"carrying {held.tension_now_n:.2g} N of tension and "
              f"{held.shear_now_n:.1f} N of shear")
        require(held.kind == "fixing", "a fixing came back as the wrong kind")
        require(held.attached,
                "a peg with no tension strength gave way to a load that is "
                "entirely shear, so the two are not being told apart")
        require(held.shear_now_n > 0.5 * weight,
                "the peg is holding a 618 N bracket and reports almost no shear")

    with banjo.World(bracket_on_a_wall(), cell_size_m=0.05) as world:
        peg = world.fix("wall", "bracket", at_m=(0.15, 2.0, 0.0),
                        axis=(1.0, 0.0, 0.0),
                        holds_tension_n=1.0e6, holds_shear_n=0.25 * weight)
        require(peg > 0, "the bracket would not peg to the wall")
        tick(world, 480)
        gone = next(j for j in world.joints() if j.id == peg)
        fell = next(b for b in world.bodies() if b.name == "bracket").position_m[1]
        print(f"    weak across it: it {'held' if gone.attached else 'gave way'}, "
              f"and the bracket is at y={fell:.3f}")
        require(not gone.attached, "a peg rated for a quarter of the load held it")
        require(fell < 1.0, "the peg gave way but the bracket did not fall")


def a_latch_changes_what_the_assembly_is() -> None:
    """A weld holds, and letting it go is what makes it a latch."""
    with banjo.World(bracket_on_a_wall(), cell_size_m=0.05) as world:
        peg = world.fix("wall", "bracket", at_m=(0.15, 2.0, 0.0),
                        axis=(1.0, 0.0, 0.0))        # a weld
        tick(world, 480)
        hung = next(b for b in world.bodies() if b.name == "bracket").position_m[1]
        require(hung > 1.9, "the weld let go")
        world.unhinge(peg)
        tick(world, 480)
        fell = next(b for b in world.bodies() if b.name == "bracket").position_m[1]
        print(f"  a weld held the bracket at y={hung:.3f}; released, it fell to "
              f"y={fell:.3f}")
        require(fell < hung - 1.0, "releasing the fixing did not drop the bracket")
        require(world.joints() == [], "the released fixing is still listed")


def main() -> int:
    require(banjo.ABI_VERSION >= 11, "this test needs ABI 11 or later")
    for run, what in (
        (a_gate_hung_through_the_abi_swings, "a gate hung through the ABI swings"),
        (limits_are_degrees, "limits are degrees and they hold"),
        (the_pin_is_body_local, "the pin is written down in the bodies' own frames"),
        (a_stiff_pin_holds_and_a_free_one_does_not, "friction holds a gate where it is put"),
        (taking_the_pin_out_drops_it, "taking the pin out drops what hung on it"),
        (a_pin_refuses_what_it_cannot_hold, "a pin refuses what it cannot hold"),
        (a_raised_grate_falls_when_you_let_go,
         "a raised grate falls when you let go"),
        (travel_is_metres_and_it_holds, "travel is metres and it holds"),
        (friction_is_what_makes_it_stay, "friction is what makes a grate stay up"),
        (a_slide_only_moves_along_its_own_line,
         "a slide only moves along its own line"),
        (a_slide_refuses_what_it_cannot_hold,
         "a slide refuses what it cannot hold"),
        (a_rope_pulls_but_does_not_push, "a rope pulls but does not push"),
        (slack_carries_nothing, "slack carries nothing"),
        (tension_is_the_load, "tension is the load"),
        (a_rope_parts_when_overloaded, "a rope parts when it is overloaded"),
        (a_chain_carries_what_hangs_below_each_link,
         "a chain carries what hangs below each link"),
        (a_tie_refuses_what_it_cannot_hold, "a tie refuses what it cannot hold"),
        (a_hoist_lifts_the_other_end, "a hoist lifts the other end"),
        (mechanical_advantage_has_a_side, "mechanical advantage has a side"),
        (a_hoist_refuses_what_it_cannot_reeve,
         "a hoist refuses what it cannot reeve"),
        (a_loaded_shelf_is_reported_without_being_struck,
         "a loaded shelf is reported without being struck"),
        (a_fixing_tells_tension_from_shear,
         "a fixing tells tension from shear"),
        (a_latch_changes_what_the_assembly_is,
         "a latch changes what the assembly is"),
    ):
        run()
        print(f"[PASS] {what}")
    print("\nall joint binding tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
