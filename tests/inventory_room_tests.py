"""The room's side of what a person has (playground/inventory_room.py), on a
real running room: taking a thing sets it aside in the engine, holding it brings
it back into the hand in front of the person, stowing sets it aside again, and
putting it down brings it back where they can see it -- each change done once,
however often it is asked for.

It needs the live engine (build/integration, as live_session_tests does), and
skips without it.
"""
from __future__ import annotations

import math
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "playground"))

import inventory_room  # noqa: E402
import live_session    # noqa: E402

BUILD = Path(os.environ["BANJO_BUILD_DIR"]) if os.environ.get("BANJO_BUILD_DIR") else \
    ROOT / "build" / "integration" / "Release"
ENGINE = BUILD / ("banjo_platform_cli.exe" if os.name == "nt" else "banjo_platform_cli")

# Standing 0.8 m back from the middle of the floor, looking along -z, eyes at 1.66 m.
PERSON = {"standing_m": [0.0, 0.04, 0.8], "facing": [0.0, 0.0, -1.0], "eyes_m": [0.0, 1.66, 0.8]}


def spec():
    return {"algorithm": "lattice", "cell_m": 0.02, "duration_s": 1.0,
            "bodies": [{"id": "b-floor00001", "name": "floor", "shape": "box", "material": "oak",
                        "size_mm": [600, 40, 400], "center_mm": [0, 20, 0], "anchored": True},
                       {"id": "b-ball000001", "name": "ball", "shape": "sphere", "material": "iron",
                        "size_mm": [100, 100, 100], "center_mm": [0, 600, 0]}]}


class WhatTakingAndHoldingDoToTheThing(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not ENGINE.is_file():
            raise unittest.SkipTest(f"{ENGINE} is not built")
        cls._temp = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls):
        cls._temp.cleanup()

    def setUp(self):
        self.live = live_session.Live()
        self.addCleanup(self.live.shutdown)
        self.app = types.SimpleNamespace(engine_path=ENGINE, runs_path=Path(self._temp.name),
                                         live=self.live, room=types.SimpleNamespace(spec=spec()))
        self.session = self.live.open(self.app, {"spec": self.app.room.spec})["session"]
        self.steps(20)

    def steps(self, n):
        for _ in range(n):
            self.live.act({"session": self.session, "op": "step", "dt": 1 / 120.0, "n": 12})

    def bodies(self):
        return {b["name"]: b for b in self.live.act({"session": self.session, "op": "poses"})["bodies"]}

    def ask(self, request, revision, op, **more):
        return inventory_room.request(self.app, dict({"request": request, "revision": revision, "op": op,
                                                      "item": "ball", "person": PERSON}, **more))

    def test_taken_held_stowed_and_put_down_the_ball_is_one_ball_where_it_is_said_to_be(self):
        took = self.ask("t1", 0, "take")
        self.assertTrue(took["ok"], took)
        self.assertEqual(took["did"], "Ball added to inventory.")
        self.assertNotIn("ball", self.bodies(), "the ball is still in the world in the bag")
        again = self.ask("t1", 0, "take")
        self.assertEqual({k: v for k, v in again.items() if k != "shown"},
                         {k: v for k, v in took.items() if k != "shown"},
                         "a retry was not answered as the first time")
        self.assertEqual(again["shown"]["record"]["revision"], 1, "a retry changed the record again")
        self.assertEqual(took["shown"]["stowed"], [{"id": "b-ball000001", "name": "ball"}])

        held = self.ask("e1", 1, "equip")
        self.assertTrue(held["ok"], held)
        self.assertEqual(held["to"], "right")
        state = self.live.act({"session": self.session, "op": "poses"})
        self.assertEqual(state.get("held"), "ball", "the hand does not hold what the record says")
        at = self.bodies()["ball"]["position_m"]
        self.assertTrue(math.dist(at, [0.0, 1.31, 0.3]) < 0.05,
                        f"the ball came out of the bag at {at}, not in front of the person")

        stowed = self.ask("s1", 2, "stow")
        self.assertTrue(stowed["ok"], stowed)
        self.assertNotIn("ball", self.bodies())
        self.assertEqual(self.live.act({"session": self.session, "op": "poses"}).get("held"), "")

        down = self.ask("d1", 3, "drop")
        self.assertTrue(down["ok"], down)
        self.steps(20)
        landed = self.bodies()["ball"]["position_m"]
        self.assertTrue(abs(landed[2] - 0.1) < 0.1 and 0.04 < landed[1] < 0.2,
                        f"the ball put down in front of the person is at {landed}")
        self.assertEqual(down["record"]["stowed"], [])

    def test_a_room_opened_again_sets_the_bags_things_aside_and_empties_the_hand_into_the_bag(self):
        """A room opens from its spec -- after the chat changes it, or a restart
        -- so the bag's things open standing in it. They are set aside again
        before the page draws anything, and a thing in the hand goes to the bag,
        since the engine's hand is empty in a room just opened."""
        self.ask("t1", 0, "take")
        self.ask("e1", 1, "equip")
        opened = self.live.open(self.app, {"spec": self.app.room.spec})
        self.session = opened["session"]
        self.assertIn("ball", [b["name"] for b in opened["bodies"]])
        shown = inventory_room.after_open(self.app, opened)
        self.assertNotIn("ball", [b["name"] for b in opened["bodies"]],
                         "the page would draw the bag's ball in the room opened again")
        self.assertNotIn("ball", self.bodies(), "the bag's ball stands in the room opened again")
        self.assertIsNone(shown["hands"]["right"])
        self.assertEqual(shown["stowed"], [{"id": "b-ball000001", "name": "ball"}])

    def test_the_floor_is_not_taken_and_a_stale_revision_changes_nothing(self):
        floor = inventory_room.request(self.app, {"request": "f1", "revision": 0, "op": "take",
                                                  "item": "floor", "person": PERSON})
        self.assertFalse(floor["ok"])
        self.assertIn("fixed in place", floor["why"])
        self.assertIn("floor", self.bodies())
        stale = self.ask("t2", 5, "take")
        self.assertFalse(stale["ok"])
        self.assertIn("changed", stale["why"])
        self.assertIn("ball", self.bodies())

    def test_a_change_without_its_own_id_is_refused(self):
        with self.assertRaises(ValueError):
            inventory_room.request(self.app, {"revision": 0, "op": "take", "item": "ball", "person": PERSON})


if __name__ == "__main__":
    unittest.main(verbosity=2)
