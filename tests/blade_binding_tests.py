"""Blades through the public C ABI and the Python binding.

tests/blade_tests.cpp pins the physics. This is the BOUNDARY: a program holding
nothing but banjo.h gives a body an edge, takes hold of it with a bounded hand,
swings it, and reads back what it cut -- the same capability the playground
reaches with a mouse, reached from a C header.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bindings" / "python"))

import banjo  # noqa: E402

CELL_M = 0.01


def require(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"[FAIL] {message}")


def tick(world: banjo.World, steps: int = 1) -> None:
    """Step, declining any break offered: a world waiting for an answer stops."""
    for _ in range(steps):
        if world.step(1.0 / 240.0) != banjo.BREAK_PENDING:
            continue
        for name in world.breakable():
            world.decline_break(name)


def rope_and_blade(flat: bool = False, speed: float = 16.0) -> dict:
    """Eight rubber segments hanging from an oak beam, an iron weight on the end,
    and an iron blade coming at the middle of the fifth segment."""
    bodies = [{"name": "beam", "shape": "box", "material": "oak",
               "dimensions_m": [0.2, 0.04, 0.04], "center_m": [0.0, 1.22, 0.0],
               "anchored": True}]
    for k in range(8):
        bodies.append({"name": f"rope {k}", "shape": "box", "material": "rubber",
                       "dimensions_m": [0.02, 0.06, 0.02],
                       "center_m": [0.0, 1.17 - 0.06 * k, 0.0]})
    bodies.append({"name": "weight", "shape": "box", "material": "iron",
                   "dimensions_m": [0.06, 0.06, 0.06], "center_m": [0.0, 0.69, 0.0]})
    size = [0.4, 0.03, 0.01] if flat else [0.4, 0.01, 0.03]
    bodies.append({"name": "blade", "shape": "box", "material": "iron",
                   "dimensions_m": size, "center_m": [0.0, 0.93, 0.1],
                   "velocity_m_s": [0.0, 0.0, -speed]})
    return {"bodies": bodies}


def tie_rope(world: banjo.World) -> tuple[int, int]:
    top = world.tie("beam", "rope 0", (0.0, 1.205, 0.0), (0.0, 1.195, 0.0))
    for k in range(7):
        above = 1.20 - 0.06 * k
        world.tie(f"rope {k}", f"rope {k + 1}", (0.0, above - 0.055, 0.0),
                  (0.0, above - 0.065, 0.0))
    bottom = world.tie("rope 7", "weight", (0.0, 0.725, 0.0), (0.0, 0.715, 0.0))
    return top, bottom


def an_edge_through_the_abi_cuts_the_rope() -> None:
    with banjo.World(rope_and_blade(), cell_size_m=CELL_M) as world:
        top, bottom = tie_rope(world)
        blade = world.blade("blade", (-0.15, 0.93, 0.085), (0.15, 0.93, 0.085),
                            (0.0, 0.0, -1.0), thickness_m=0.01, edge_radius_m=0.00005,
                            grip_m=(0.19, 0.93, 0.1))
        require(blade > 0, "the blade would not take an edge")
        edges = world.blades()
        require(len(edges) == 1 and edges[0].body == "blade" and edges[0].attached,
                "the edge was not reported back")
        require(abs(edges[0].thickness_m - 0.01) < 1e-12, "the thickness came back wrong")
        hung = world.body("weight").position_m[1]
        tick(world, 360)
        fell = world.body("weight").position_m[1]
        cuts = [c for c in world.cuts() if c.target.startswith("rope")]
        bit = [c for c in cuts if c.kind in ("edge", "slice", "press")]
        severed = sum(c.bonds for c in cuts) + sum(c.links for c in cuts)
        print(f"  an edge through the ABI at 16 m/s: {len(cuts)} contacts with the "
              f"rope, {severed} bonds and links cut; the weight went from "
              f"y={hung:.3f} to y={fell:.3f}")
        require(bit, "no contact with the rope bit")
        require(severed > 0, "the edge went through and cut nothing")
        require(fell < hung - 0.4, "the rope was cut and the weight did not fall")
        work = world.blades()[0].cut_work_j
        require(work > 0.0, "cutting the rope cost nothing")
        pins = {pin.id: pin for pin in world.joints()}
        require(pins[top].attached, "cutting the rope took it off the beam")
        require(pins[bottom].attached, "cutting the rope took the weight off its end")


def the_flat_through_the_abi_does_not() -> None:
    with banjo.World(rope_and_blade(flat=True), cell_size_m=CELL_M) as world:
        tie_rope(world)
        world.blade("blade", (-0.15, 0.915, 0.1), (0.15, 0.915, 0.1), (0.0, -1.0, 0.0),
                    thickness_m=0.01, edge_radius_m=0.00005, grip_m=(0.19, 0.93, 0.1))
        tick(world, 360)
        cuts = [c for c in world.cuts() if c.target.startswith("rope")]
        severed = sum(c.bonds for c in cuts) + sum(c.links for c in cuts)
        kinds = sorted({c.kind for c in cuts})
        print(f"  the flat through the ABI: contacts reported as {kinds}, "
              f"{severed} bonds and links cut")
        require(severed == 0, "the flat of the blade cut the rope")
        require("flat" in kinds, "a flat strike was not reported as one")
        require(all(pin.attached for pin in world.joints()),
                "the flat strike took something off the rope")


def a_wielded_blade_is_held_by_a_bounded_hand() -> None:
    scene = {"bodies": [{"name": "blade", "shape": "box", "material": "iron",
                         "dimensions_m": [0.01, 0.1, 0.25], "center_m": [0.0, 1.0, 0.0]}]}
    with banjo.World(scene, cell_size_m=CELL_M) as world:
        require(world.blade("blade", (0.0, 0.95, -0.12), (0.0, 1.05, -0.12), (0.0, 0.0, -1.0),
                            thickness_m=0.01, grip_m=(0.0, 1.0, 0.1)) > 0,
                "the blade would not take an edge")
        world.wield("blade", (0.0, 1.0, 0.1))
        require(world.held == "blade", "wielding did not take hold")
        # Held out in the air, it stays there: the hand carries its weight.
        tick(world, 240)
        y = world.body("blade").position_m[1]
        require(abs(y - 1.0) < 0.02, f"a wielded blade sagged or drifted to y={y:.3f}")
        # Turned a quarter about its own length, it turns.
        half = math.sqrt(0.5)
        world.aim_held((half, 0.0, 0.0, half))
        tick(world, 240)
        q = world.body("blade").orientation_wxyz
        angle = 2.0 * math.degrees(math.acos(min(1.0, abs(q[0]))))
        print(f"  a wielded blade held at y={y:.3f}; aimed a quarter turn round, it "
              f"turned {angle:.1f} degrees")
        require(abs(angle - 90.0) < 5.0, "the hand did not turn the blade where it was aimed")
        world.hand_strength(100.0)
        world.hand_torque(10.0)
        world.release()
        require(world.held == "", "letting go did not let go")


def a_blade_refuses_what_it_cannot_be() -> None:
    scene = {"bodies": [{"name": "bar", "shape": "box", "material": "iron",
                         "dimensions_m": [0.3, 0.01, 0.03], "center_m": [0.0, 1.0, 0.0]}]}
    with banjo.World(scene, cell_size_m=CELL_M) as world:
        for why, call in (
            ("a body that does not exist",
             lambda: world.blade("no such bar", (-0.1, 1.0, -0.015), (0.1, 1.0, -0.015),
                                 (0, 0, -1), 0.01)),
            ("an edge floating a metre off the body",
             lambda: world.blade("bar", (-0.1, 2.0, -0.015), (0.1, 2.0, -0.015),
                                 (0, 0, -1), 0.01)),
            ("a facing that runs along the edge",
             lambda: world.blade("bar", (-0.1, 1.0, -0.015), (0.1, 1.0, -0.015),
                                 (1, 0, 0), 0.01)),
            ("no thickness",
             lambda: world.blade("bar", (-0.1, 1.0, -0.015), (0.1, 1.0, -0.015),
                                 (0, 0, -1), 0.0)),
        ):
            try:
                call()
            except banjo.BanjoError:
                continue
            raise SystemExit(f"[FAIL] the engine accepted {why}")
        require(world.blades() == [], "a refused blade was recorded anyway")
        print("  a blade refuses a missing body, an edge off the body, a facing "
              "along the edge, and no thickness")


def main() -> int:
    require(banjo.ABI_VERSION >= 13, "this test needs ABI 13 or later")
    for run, what in (
        (an_edge_through_the_abi_cuts_the_rope, "an edge through the ABI cuts a rope"),
        (the_flat_through_the_abi_does_not, "the flat through the ABI does not"),
        (a_wielded_blade_is_held_by_a_bounded_hand, "a wielded blade is held by a bounded hand"),
        (a_blade_refuses_what_it_cannot_be, "a blade refuses what it cannot be"),
    ):
        run()
        print(f"[PASS] {what}")
    print("\nall blade binding tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
