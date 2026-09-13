"""The hand's own motions through the public C ABI and the Python binding.

tests/hand_stroke_tests.cpp pins the physics. This is the BOUNDARY: a program
holding nothing but banjo.h wields a ball and throws it, previews the throw
first, reads back what the ball left with and the work the hand put in, and
hauls a block against a spring until the hand's strength runs out -- the same
capability the playground reaches with a mouse. docs/interaction-profiles.md.
"""
from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bindings" / "python"))

import banjo  # noqa: E402

DT = 1.0 / 240.0
FROM, TO = (-0.8, 1.5, 0.0), (0.0, 1.5, 0.0)


def ball(material: str, diameter_m: float) -> dict:
    return {"bodies": [{"name": "ball", "shape": "sphere", "material": material,
                        "dimensions_m": [diameter_m] * 3, "center_m": list(FROM)}]}


def throw(world: banjo.World) -> banjo.Hand:
    """A full-effort throw along x over 0.8 m, stepped until the hand opens."""
    world.stroke([FROM, TO], speed_m_s=20.0, accel_m_s2=2000.0, let_go=True)
    for _ in range(480):
        if not world.held:
            break
        world.step(DT)
    return world.hand()


def speed(v: tuple[float, float, float]) -> float:
    return math.sqrt(sum(c * c for c in v))


class TheHandThrows(unittest.TestCase):
    def test_a_carried_ball_is_not_pushed_so_cannot_be_stroked(self):
        with banjo.World(ball("rubber", 0.07)) as world:
            world.grab("ball")
            self.assertEqual(world.hand().mode, "carry")
            with self.assertRaises(banjo.BanjoError) as caught:
                world.stroke([FROM, TO], 20.0, 2000.0, let_go=True)
            self.assertIn("carried", str(caught.exception))
            self.assertFalse(world.preview_stroke([FROM, TO], 20.0, 2000.0).possible)

    def test_the_same_throw_sends_a_heavier_ball_off_slower(self):
        left = {}
        for material, diameter in (("rubber", 0.07), ("iron", 0.1)):
            with banjo.World(ball(material, diameter)) as world:
                world.wield("ball", FROM)
                self.assertEqual(world.hand().mode, "grip")
                seen = world.preview_stroke([FROM, TO], 20.0, 2000.0)
                self.assertTrue(seen.possible and seen.reaches_end, seen.why)
                hand = throw(world)
                self.assertEqual(hand.stroke_ended, "let go")
                self.assertEqual(hand.let_go_body, "ball")
                self.assertEqual(world.held, "")
                went = speed(hand.let_go_velocity_m_s)
                self.assertAlmostEqual(went, speed(seen.let_go_velocity_m_s), delta=0.03 * went,
                                       msg="the preview of the throw disagrees with the throw")
                mass = world.body("ball").mass_kg
                self.assertGreater(mass, 0.0)
                self.assertAlmostEqual(hand.let_go_work_j, 0.5 * mass * went * went,
                                       delta=0.02 * hand.let_go_work_j + 0.05,
                                       msg="the hand's work is not what the ball got")
                left[material] = went
        self.assertGreater(left["rubber"], 1.1 * left["iron"])

    def test_a_lighter_arm_throws_the_same_ball_faster(self):
        """The hand's own moving mass is part of what the strength has to move."""
        went = {}
        for arm_kg in (2.0, 0.0):
            with banjo.World(ball("iron", 0.1)) as world:
                world.hand_mass(arm_kg)
                world.wield("ball", FROM)
                went[arm_kg] = speed(throw(world).let_go_velocity_m_s)
        self.assertGreater(went[0.0], 1.1 * went[2.0])

    def test_a_flight_preview_comes_down_and_moves_nothing(self):
        with banjo.World(ball("iron", 0.1)) as world:
            world.wield("ball", FROM)
            before = world.body("ball")
            flight = world.preview_flight(before.position_m, (5.0, 5.0, 0.0), 3.0, "ball")
            self.assertTrue(flight.hit)
            self.assertEqual(flight.hit_name, "", "a ball thrown up and out came down on the ground")
            self.assertGreater(len(flight.points_m), 10)
            self.assertEqual(world.body("ball").position_m, before.position_m)


class TheHandDraws(unittest.TestCase):
    def test_a_haul_against_a_spring_stops_where_the_strength_runs_out(self):
        scene = {"bodies": [
            {"name": "post", "shape": "box", "material": "oak", "dimensions_m": [0.1] * 3,
             "center_m": [0.0, 1.0, 0.0], "anchored": True},
            {"name": "block", "shape": "box", "material": "oak", "dimensions_m": [0.1] * 3,
             "center_m": [0.4, 1.0, 0.0]}]}
        with banjo.World(scene) as world:
            world.spring("post", "block", (0.05, 1.0, 0.0), (0.35, 1.0, 0.0),
                         rest_m=0.0, stiffness_n_m=4000.0, damping_n_s_m=20.0)
            world.grab("block")
            self.assertEqual(world.hand().mode, "haul")
            world.stroke([(0.4, 1.0, 0.0), (1.0, 1.0, 0.0)], speed_m_s=0.5, accel_m_s2=5.0,
                         give_up_s=4.0)
            for _ in range(1200):
                if not world.hand().stroking:
                    break
                world.step(DT)
            hand = world.hand()
            self.assertEqual(hand.stroke_ended, "blocked")
            self.assertEqual(world.held, "block")
            drawn = world.body("block").position_m[0] - 0.4
            self.assertAlmostEqual(drawn, 800.0 / 4000.0, delta=0.02,
                                   msg="the draw did not stop where 800 N balances the spring")
            self.assertGreater(hand.work_j, 0.95 * 0.5 * 4000.0 * drawn * drawn)


if __name__ == "__main__":
    unittest.main(verbosity=2)
