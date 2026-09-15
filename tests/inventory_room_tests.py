"""The room's side of what a person has (playground/inventory_room.py), on a
real running room: taking a thing sets it aside in the engine, holding it brings
it back into the hand in front of the person, stowing sets it aside again, and
putting it down brings it back where they can see it -- each change done once,
however often it is asked for. Taken up from where it lies, it is gripped there.

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
import world_room      # noqa: E402

# Resolved: CI gives the build as a relative path, and the live session starts
# the runner from the run's own folder, where a relative path means nothing.
BUILD = Path(os.environ["BANJO_BUILD_DIR"]).resolve() if os.environ.get("BANJO_BUILD_DIR") else \
    ROOT / "build" / "integration" / "Release"
ENGINE = BUILD / ("banjo_platform_cli.exe" if os.name == "nt" else "banjo_platform_cli")

# Standing 0.8 m back from the middle of the floor, looking along -z, eyes at 1.66 m.
PERSON = {"standing_m": [0.0, 0.04, 0.8], "facing": [0.0, 0.0, -1.0], "eyes_m": [0.0, 1.66, 0.8]}
BALL = {"id": "b-ball000001", "name": "ball", "material": "iron", "shape": "sphere"}


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

    def held(self):
        return self.live.act({"session": self.session, "op": "poses"}).get("held")

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
        self.assertEqual(took["shown"]["stowed"], [BALL])

        held = self.ask("e1", 1, "equip")
        self.assertTrue(held["ok"], held)
        self.assertEqual(held["to"], "right")
        self.assertEqual(held["shown"]["hands"]["right"], dict(BALL, slot=0),
                         "the hand's ball does not carry the slot its number puts it back in")
        self.assertEqual(held["shown"]["stowed"], [])
        state = self.live.act({"session": self.session, "op": "poses"})
        self.assertEqual(state.get("held"), "ball", "the hand does not hold what the record says")
        at = self.bodies()["ball"]["position_m"]
        self.assertTrue(math.dist(at, [0.0, 1.31, 0.3]) < 0.05,
                        f"the ball came out of the bag at {at}, not in front of the person")

        stowed = self.ask("s1", 2, "stow")
        self.assertTrue(stowed["ok"], stowed)
        self.assertNotIn("ball", self.bodies())
        self.assertEqual(self.held(), "")

        down = self.ask("d1", 3, "drop")
        self.assertTrue(down["ok"], down)
        self.steps(20)
        landed = self.bodies()["ball"]["position_m"]
        self.assertTrue(abs(landed[2] - 0.1) < 0.1 and 0.04 < landed[1] < 0.2,
                        f"the ball put down in front of the person is at {landed}")
        self.assertEqual(down["record"]["stowed"], [])

    def test_taken_up_the_ball_is_gripped_where_it_lies_and_let_go_it_is_the_worlds_again(self):
        """E on a loose thing: into the hand, not the bag (the owner, 2026-09-14).
        The engine's hand grips it where it lies -- or where the page says, a
        tool by its handle -- and put down, the record lets it go. The release
        does not wait on the engine's word that the hand holds it, which can be
        a step old: no poses are asked for between these."""
        lay = self.bodies()["ball"]["position_m"]
        took = self.ask("u1", 0, "take_up")
        self.assertTrue(took["ok"], took)
        self.assertEqual((took["to"], took["room"]["taken_up"]), ("right", "ball"))
        self.assertTrue(math.dist(took["room"]["grip_m"], lay) < 1e-3,
                        f"gripped at {took['room']['grip_m']}, not where it lay at {lay}")
        self.assertEqual(took["shown"]["hands"]["right"], BALL, "a thing from the world has no slot yet")
        down = self.ask("d1", 1, "drop")
        self.assertTrue(down["ok"], down)
        self.assertEqual(self.held(), "", "put down, the ball was still in the engine's hand")
        self.assertIn("ball", self.bodies())

        far = self.ask("u2", 2, "take_up", grip=[5.0, 0.5, 0.0])
        self.assertFalse(far["ok"])
        self.assertIn("not on it", far["why"])
        self.assertEqual(self.held(), "")
        near = [lay[0] + 0.03, lay[1], lay[2]]
        took = self.ask("u3", 2, "take_up", grip=near)
        self.assertTrue(took["ok"], took)
        self.assertEqual(took["room"]["grip_m"], [round(v, 4) for v in near])
        stowed = self.ask("s1", 3, "stow")
        self.assertTrue(stowed["ok"], stowed)
        self.assertEqual(stowed["shown"]["stowed"], [BALL])
        self.assertNotIn("ball", self.bodies())

    def test_a_room_opened_again_sets_the_bags_things_aside_and_empties_the_hand_into_the_bag(self):
        """A room opens from its spec -- after the chat changes it, or a restart
        -- so the bag's things open standing in it. They are set aside again
        before the page draws anything, and a thing in the hand goes to the bag,
        into the slot kept for it, since the engine's hand is empty in a room
        just opened."""
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
        self.assertEqual(shown["stowed"], [BALL])
        self.assertEqual(shown["record"]["home"], {})

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


class AReloadRejoinsTheRunningWorld(unittest.TestCase):
    """What a page gets when it opens the room that is already running here
    (live_session.Live.rejoin, which server.py uses for a reload): the world as
    it stands -- a thing still in the hand, pieces as they broke, with their
    cells -- under a new id, so the page that had it loses it."""

    @classmethod
    def setUpClass(cls):
        if not ENGINE.is_file():
            raise unittest.SkipTest(f"{ENGINE} is not built")
        cls._temp = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls):
        cls._temp.cleanup()

    def open(self, room_spec):
        live = live_session.Live()
        self.addCleanup(live.shutdown)
        app = types.SimpleNamespace(engine_path=ENGINE, runs_path=Path(self._temp.name), live=live,
                                    room=types.SimpleNamespace(spec=room_spec))
        return app, live.open(app, {"spec": room_spec})["session"]

    def test_the_hand_still_holds_what_it_held_and_the_old_page_is_refused(self):
        app, session = self.open(spec())
        for _ in range(20):
            app.live.act({"session": session, "op": "step", "dt": 1 / 120.0, "n": 12})
        app.live.act({"session": session, "op": "grab", "name": "ball"})
        for _ in range(5):
            app.live.act({"session": session, "op": "step", "dt": 1 / 120.0, "n": 12})
        before = app.live.act({"session": session, "op": "poses"})
        rejoined = app.live.rejoin(app)
        self.assertTrue(rejoined["rejoined"])
        self.assertNotEqual(rejoined["session"], session)
        self.assertEqual((rejoined.get("hand") or {}).get("holding"), "ball", rejoined.get("hand"))
        self.assertEqual(rejoined["t"], before["t"], "the world moved on while it was rejoined")
        self.assertEqual({b["name"]: b["position_m"] for b in rejoined["bodies"]},
                         {b["name"]: b["position_m"] for b in before["bodies"]})
        with self.assertRaises(live_session.LiveError):
            app.live.act({"session": session, "op": "step", "dt": 1 / 120.0, "n": 1})
        stepped = app.live.act({"session": rejoined["session"], "op": "step", "dt": 1 / 120.0, "n": 1})
        self.assertGreater(stepped["t"], before["t"])

    def test_what_broke_stays_broken_with_its_cells(self):
        room_spec = world_room.room()
        for body in room_spec["bodies"]:
            if body["name"] == "iron ball":
                # Over the 20 mm glass plate, its bottom 1.5 m above the plate's
                # top, which is 140 mm up (scratchpad measure_trial_clock.py).
                body["center_mm"] = [-2800, 140 + 60 + 1500, -1200]
        app, session = self.open(room_spec)
        app.live.act({"session": session, "op": "foresee", "horizon_s": 0.0})
        broke = None
        for _ in range(600):
            state = app.live.act({"session": session, "op": "step", "dt": 1 / 240.0, "n": 8})
            for name in state.get("breakable") or []:
                answer = app.live.act({"session": session, "op": "fracture", "name": name})
                if name == "glass plate 20mm":
                    broke = answer
            if broke is not None:
                break
        self.assertIsNotNone(broke, "the plate was never struck hard enough to ask")
        self.assertGreater(broke.get("pieces", 0), 1, broke)
        for _ in range(10):
            app.live.act({"session": session, "op": "step", "dt": 1 / 240.0, "n": 8})

        def shards(bodies):
            return {b["name"]: b for b in bodies if b["name"].startswith("glass plate 20mm piece")}
        before = shards(app.live.act({"session": session, "op": "poses"})["bodies"])
        rejoined = app.live.rejoin(app)
        now = shards(rejoined["bodies"])
        self.assertNotIn("glass plate 20mm", {b["name"] for b in rejoined["bodies"]},
                         "the plate came back whole")
        self.assertGreater(len(now), 1, sorted(b["name"] for b in rejoined["bodies"]))
        self.assertEqual(set(now), set(before))
        for name, piece in now.items():
            self.assertEqual(piece.get("cells_local_m"), before[name].get("cells_local_m"),
                             f"{name} came back with other cells than it has")
            self.assertTrue(piece.get("cells_local_m"), f"{name} came back without its cells")


class ARestartOpensTheRoomAsItStood(unittest.TestCase):
    """What a server started again does with the world it saved before it
    stopped (live_session.Live.snapshot, then Live.open with it): the world
    opened again whole, the ball still in the hand and the record's hand with
    it, and the bench plate's pieces with their own cells."""

    @classmethod
    def setUpClass(cls):
        if not ENGINE.is_file():
            raise unittest.SkipTest(f"{ENGINE} is not built")
        cls._temp = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls):
        cls._temp.cleanup()

    def open(self, room_spec, snapshot=None):
        live = live_session.Live()
        self.addCleanup(live.shutdown)
        app = types.SimpleNamespace(engine_path=ENGINE, runs_path=Path(self._temp.name), live=live,
                                    room=types.SimpleNamespace(spec=room_spec))
        return app, live.open(app, dict({"spec": room_spec}, **({"snapshot": snapshot} if snapshot else {})))

    def test_the_ball_in_the_hand_is_still_in_the_hand(self):
        app, opened = self.open(spec())
        session = opened["session"]
        for _ in range(20):
            app.live.act({"session": session, "op": "step", "dt": 1 / 120.0, "n": 12})
        took = inventory_room.request(app, {"request": "u1", "revision": 0, "op": "take_up", "item": "ball",
                                            "person": PERSON})
        self.assertTrue(took["ok"], took)
        for _ in range(5):
            app.live.act({"session": session, "op": "step", "dt": 1 / 120.0, "n": 12})
        saved, why = app.live.snapshot()
        self.assertIsNotNone(saved, why)
        self.assertEqual(saved["hand"]["holding"], "ball")
        self.assertTrue(saved["hand"]["wielding"])
        kept = inventory_room.inventory_of(app).record()
        before = app.live.act({"session": session, "op": "poses"})
        app.live.shutdown()                       # the server stops

        again, reopened = self.open(spec(), snapshot=saved)
        again.room.inventory_record = kept        # read back with the room (room_store)
        self.assertEqual(reopened["restored"]["tier"], "whole", reopened["restored"])
        self.assertEqual(reopened["t"], before["t"], "the world's clock did not come back")
        self.assertEqual((reopened.get("hand") or {}).get("holding"), "ball", reopened.get("hand"))
        self.assertEqual({b["name"]: b["position_m"] for b in reopened["bodies"]},
                         {b["name"]: b["position_m"] for b in before["bodies"]})
        shown = inventory_room.after_open(again, reopened)
        self.assertEqual(shown["hands"]["right"], BALL, "the record's hand let go of the ball")
        self.assertEqual(shown["stowed"], [])
        self.assertEqual(again.live.act({"session": reopened["session"], "op": "poses"}).get("held"), "ball")

    def test_the_plates_pieces_come_back_with_their_cells(self):
        room_spec = world_room.room()
        for body in room_spec["bodies"]:
            if body["name"] == "iron ball":
                body["center_mm"] = [-2800, 140 + 60 + 1500, -1200]   # as AReloadRejoinsTheRunningWorld
        app, opened = self.open(room_spec)
        session = opened["session"]
        app.live.act({"session": session, "op": "foresee", "horizon_s": 0.0})
        broke = None
        for _ in range(600):
            state = app.live.act({"session": session, "op": "step", "dt": 1 / 240.0, "n": 8})
            for name in state.get("breakable") or []:
                answer = app.live.act({"session": session, "op": "fracture", "name": name})
                if name == "glass plate 20mm":
                    broke = answer
            if broke is not None:
                break
        self.assertIsNotNone(broke, "the plate was never struck hard enough to ask")
        self.assertGreater(broke.get("pieces", 0), 1, broke)
        for _ in range(10):
            app.live.act({"session": session, "op": "step", "dt": 1 / 240.0, "n": 8})

        def shards(bodies):
            return {b["name"]: b for b in bodies if b["name"].startswith("glass plate 20mm piece")}
        before = shards(app.live.act({"session": session, "op": "poses"})["bodies"])
        saved, why = app.live.snapshot()
        self.assertIsNotNone(saved, why)
        app.live.shutdown()

        again, reopened = self.open(room_spec, snapshot=saved)
        self.assertEqual(reopened["restored"]["tier"], "whole", reopened["restored"])
        now = shards(reopened["bodies"])
        self.assertNotIn("glass plate 20mm", {b["name"] for b in reopened["bodies"]}, "the plate came back whole")
        self.assertEqual(set(now), set(before))
        for name, piece in now.items():
            self.assertTrue(piece.get("cells_local_m"), f"{name} came back without its cells")
            self.assertEqual(piece.get("cells_local_m"), before[name].get("cells_local_m"),
                             f"{name} came back with other cells than it had")
            self.assertEqual(piece["position_m"], before[name]["position_m"], f"{name} moved")


if __name__ == "__main__":
    unittest.main(verbosity=2)
