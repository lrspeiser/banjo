"""The C library, driven from Python.

Two things are being checked here. The first is the binding: ctypes gets no help
from the compiler, so a wrong argtype is a silent pointer truncation rather than
an error, and only running it finds that out.

The second is the claim the C face exists to make -- that a language which
cannot read a C++ header can still drive a world. Every physical result below is
one the C++ tests also check, so if the two ever disagree the boundary is what
broke, not the physics.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bindings" / "python"))

import banjo  # noqa: E402


def pane_and_ball(drop_m: float) -> dict:
    """The same scene the C++ tests use: a glass pane with an iron ball above it."""
    return {"bodies": [
        {"name": "pane", "shape": "box", "material": "glass",
         "dimensions_m": [0.3, 0.04, 0.3], "center_m": [0.0, 0.02, 0.0]},
        {"name": "ball", "shape": "sphere", "material": "iron",
         "dimensions_m": [0.1, 0.1, 0.1], "center_m": [0.0, 0.04 + 0.05 + drop_m, 0.0]},
    ]}


class TheLibraryLoads(unittest.TestCase):
    def test_the_abi_matches_the_binding(self):
        self.assertEqual(banjo.library().banjo_abi_version(), banjo.ABI_VERSION)

    def test_a_bad_scene_says_what_is_wrong_instead_of_crashing(self):
        with self.assertRaises(banjo.BanjoError) as caught:
            banjo.World("not json at all")
        self.assertTrue(str(caught.exception),
                        "the engine failed without saying why")

    def test_a_closed_world_refuses_rather_than_using_a_dead_handle(self):
        world = banjo.World(pane_and_ball(0.1))
        world.close()
        with self.assertRaises(banjo.BanjoError):
            world.advance(1 / 120)
        world.close()   # closing twice is not an error


class AWorldRunsFromPython(unittest.TestCase):
    def test_stepping_is_gravity(self):
        with banjo.World(pane_and_ball(1.0), cell_size_m=0.02) as world:
            start = world.body("ball").position_m[1]
            for _ in range(480):
                world.advance(1 / 240)
            end = world.body("ball").position_m[1]
            self.assertLess(end, start - 0.5, "the ball did not fall")
            self.assertGreater(end, 0.0, "the ball fell through the floor")

    def test_a_ray_names_what_it_meets(self):
        with banjo.World(pane_and_ball(1.0)) as world:
            down = world.pick([0, 6, 0], [0, -1, 0])
            self.assertTrue(down.hit)
            self.assertEqual(down.name, "ball")
            self.assertGreater(down.distance_m, 4.0)
            # On the ray, not somewhere near it.
            self.assertAlmostEqual(down.point_m[1], 6.0 - down.distance_m, places=6)

            beside = world.pick([3, 6, 0], [0, -1, 0])
            self.assertTrue(beside.hit, "a ray beside the scene met nothing at all")
            self.assertEqual(beside.name, "", "the ground should be a hit with no name")

            self.assertFalse(world.pick([0, 6, 0], [0, 1, 0]).hit,
                             "a ray fired at the sky hit something")

    def test_a_hard_enough_hit_breaks_it_and_says_how_many_pieces(self):
        with banjo.World(pane_and_ball(10.0)) as world:
            pieces = 0
            for _ in range(900):
                if world.step(1 / 240) != banjo.BREAK_PENDING:
                    continue
                waiting = world.breakable()
                self.assertIn("pane", waiting)
                pieces = world.fracture("pane")
                break
            self.assertGreater(pieces, 1, "a 13.9 m/s iron ball did not break a glass pane")
            # The count reported is the count in the world.
            present = sum(1 for b in world.bodies() if b.name.startswith("pane"))
            self.assertEqual(pieces, present,
                             "fracture reported a different number than the world holds")

    def test_the_threshold_is_necessary_and_not_sufficient(self):
        """1.5 m clears the bar and still holds. Reading the bar as a promise
        reads the derivation backwards, so this pins the distinction."""
        with banjo.World(pane_and_ball(1.5)) as world:
            cleared = False
            for _ in range(900):
                if world.step(1 / 240) != banjo.BREAK_PENDING:
                    continue
                hit = [i for i in world.impacts() if i.struck == "pane"]
                self.assertTrue(hit, "the world stopped for a break it could not describe")
                self.assertGreater(hit[0].closing_speed_m_s, hit[0].threshold_speed_m_s)
                cleared = True
                self.assertLessEqual(world.fracture("pane"), 1,
                                     "the marginal drop broke it after all")
                break
            self.assertTrue(cleared, "the drop never cleared the threshold")

    def test_advance_never_leaves_the_world_wedged(self):
        """A step that would break something is taken back and time stops until
        the host answers. advance() answers, so the clock has to keep moving."""
        with banjo.World(pane_and_ball(10.0)) as world:
            for _ in range(900):
                world.advance(1 / 240)
            self.assertGreater(world.time_s, 3.0,
                               "the world stopped advancing: it is wedged on a break")
            self.assertGreater(len(world.bodies()), 2, "nothing broke, so this proves nothing")

    def test_declining_a_break_also_lets_time_move(self):
        with banjo.World(pane_and_ball(10.0)) as world:
            declined = False
            for _ in range(900):
                if world.step(1 / 240) != banjo.BREAK_PENDING:
                    continue
                for name in world.breakable():
                    world.decline_break(name)
                declined = True
                break
            self.assertTrue(declined, "nothing ever asked to break")
            stopped_at = world.time_s
            for _ in range(240):
                world.step(1 / 240)
            self.assertGreater(world.time_s, stopped_at,
                               "declining the break did not let time move again")
            self.assertEqual(len(world.bodies()), 2, "something broke after being declined")

    def test_lifting_something_and_letting_it_go(self):
        with banjo.World(pane_and_ball(0.06)) as world:
            for _ in range(1200):       # let it settle, and go to sleep
                world.advance(1 / 240)
            settled = world.body("ball").position_m[1]

            world.grab("ball")
            self.assertEqual(world.held, "ball")
            for i in range(1, 61):
                world.move_held([0.0, settled + i / 60.0, 0.0])
                world.advance(1 / 240)
            lifted = world.body("ball").position_m[1]
            self.assertAlmostEqual(lifted, settled + 1.0, places=2)

            world.release()
            self.assertEqual(world.held, "")
            for _ in range(480):
                world.advance(1 / 240)
            self.assertAlmostEqual(world.body("ball").position_m[1], settled, places=2,
                                   msg="it was let go a metre up and did not come back down")

    def test_anchored_scenery_and_missing_names_are_refused_clearly(self):
        scene = pane_and_ball(1.0)
        scene["bodies"][0]["anchored"] = True
        with banjo.World(scene) as world:
            with self.assertRaises(banjo.BanjoError):
                world.grab("pane")
            with self.assertRaises(banjo.BanjoError):
                world.grab("no such thing")
            self.assertEqual(world.held, "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
