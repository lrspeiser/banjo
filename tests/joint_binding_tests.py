"""Pins through the public C ABI and the Python binding.

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
        turned = abs(pin_of(world, pin).degrees)
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
        turned = abs(pin_of(world, pin).degrees)
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
        print(f"  after a {abs(now.degrees):.1f} degree swing the pin has moved "
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
                furthest = max(furthest, abs(pin_of(world, pin).degrees))
            watched[friction] = (furthest, abs(pin_of(world, pin).degrees))
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


def main() -> int:
    require(banjo.ABI_VERSION >= 6, "this test needs ABI 6 or later")
    for run, what in (
        (a_gate_hung_through_the_abi_swings, "a gate hung through the ABI swings"),
        (limits_are_degrees, "limits are degrees and they hold"),
        (the_pin_is_body_local, "the pin is written down in the bodies' own frames"),
        (a_stiff_pin_holds_and_a_free_one_does_not, "friction holds a gate where it is put"),
        (taking_the_pin_out_drops_it, "taking the pin out drops what hung on it"),
        (a_pin_refuses_what_it_cannot_hold, "a pin refuses what it cannot hold"),
    ):
        run()
        print(f"[PASS] {what}")
    print("\nall joint binding tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
