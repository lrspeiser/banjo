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
from copy import deepcopy
from unittest import mock
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

    def test_inventory_replies_track_shared_mass_without_double_counting(self):
        self.app.room.spec=spec()
        self.app.room.spec["terrain"]={"generate":{"kind":"flat","nx":32,"nz":32,
            "cell_m":.25,"soil_m":.2,"sand_m":.02}}
        self.session=self.live.open(self.app,{"spec":self.app.room.spec})["session"]
        taken=self.ask("shared-take",0,"take")
        self.assertTrue(taken["ok"],taken)
        mass=taken["shown"]["carried"]["objects_kg"]
        self.assertGreater(mass,0)
        self.assertAlmostEqual(taken["shown"]["carried"]["total_kg"],mass)
        self.assertEqual(taken["shown"]["carried"]["limit_kg"],80)
        held=self.ask("shared-equip",1,"equip")
        self.assertTrue(held["ok"],held)
        self.assertAlmostEqual(held["shown"]["carried"]["objects_kg"],mass)
        stowed=self.ask("shared-stow",2,"stow")
        self.assertTrue(stowed["ok"],stowed)
        self.assertAlmostEqual(stowed["shown"]["carried"]["objects_kg"],mass)
        dropped=self.ask("shared-drop",3,"drop")
        self.assertTrue(dropped["ok"],dropped)
        self.assertEqual(dropped["shown"]["carried"]["objects_kg"],0)

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

    def test_refused_stow_preserves_native_hand_and_inventory_facing(self):
        took=self.ask("take-before-refusal",0,"take_up")
        self.assertTrue(took["ok"],took)
        before=deepcopy(inventory_room.inventory_of(self.app).record())
        native=self.live.act
        def refuse_park(body):
            if body.get("op")=="park":
                raise ValueError("Native storage preflight refused")
            return native(body)
        with mock.patch.object(self.live,"act",side_effect=refuse_park):
            answer=self.ask("refused-stow",before["revision"],"stow")
        self.assertFalse(answer["ok"])
        self.assertEqual(inventory_room.inventory_of(self.app).record(),before)
        self.assertEqual(self.held(),"ball")


def mace_spec():
    """A mace whose iron head hangs on a short chain from its oak handle, as
    banjo_mcp.RECIPES["mace"] lays it out on a room's 40 mm cells, lying on a
    floor."""
    return {"algorithm": "lattice", "cell_m": 0.04, "duration_s": 1.0,
            "bodies": [{"id": "b-floor00001", "name": "floor", "shape": "box", "material": "oak",
                        "size_mm": [2000, 40, 2000], "center_mm": [0, 20, 0], "anchored": True},
                       {"id": "b-mace000001", "name": "mace", "shape": "box", "material": "oak",
                        "size_mm": [600, 40, 40], "center_mm": [0, 60, 0]},
                       {"id": "b-mace000002", "name": "mace head", "shape": "box", "material": "iron",
                        "size_mm": [80, 80, 80], "center_mm": [540, 80, 0]}],
            "joints": [{"kind": "link", "a": "mace", "b": "mace head",
                        "at_mm": [300, 60, 0], "to_mm": [500, 80, 0], "length_mm": 205}]}


# The chain, and from where it is tied on the head to the head's middle, and a
# cell's slack: past this the chain has let go.
CHAIN_WHOLE_M = 0.205 + 0.04 + 0.03


class AThingOfSeveralPartsIsTakenUpWhole(unittest.TestCase):
    """The owner, 2026-09-21: "when a user picks up something it can be for the
    entire product so that it doesn't break, but needs to still allow movement
    if part of the product, like swinging a mace". Taken up by either part, the
    hand grips that part and the rest comes on its chain -- which stays a chain:
    lifted, the head hangs; swung, it swings; let go, all of it lands, still
    tied. It weighs what all of it weighs, and it does not go in the bag."""

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
                                         live=self.live, room=types.SimpleNamespace(spec=mace_spec()))
        self.session = self.live.open(self.app, {"spec": self.app.room.spec})["session"]
        self.steps(20)

    def steps(self, n):
        for _ in range(n):
            self.live.act({"session": self.session, "op": "step", "dt": 1 / 120.0, "n": 12})

    def bodies(self):
        return {b["name"]: b for b in self.live.act({"session": self.session, "op": "poses"})["bodies"]}

    def held(self):
        return self.live.act({"session": self.session, "op": "poses"}).get("held")

    def ask(self, request, revision, op, item, **more):
        return inventory_room.request(self.app, dict({"request": request, "revision": revision, "op": op,
                                                      "item": item, "person": PERSON}, **more))

    def chain(self, bodies):
        """From where the chain is tied on the handle to the middle of the head."""
        handle, head = bodies["mace"], bodies["mace head"]
        w, x, y, z = handle["orientation_wxyz"]
        along = [1 - 2 * (y * y + z * z), 2 * (x * y + w * z), 2 * (x * z - w * y)]   # its own x
        tie = [handle["position_m"][k] + 0.3 * along[k] for k in range(3)]
        return math.dist(tie, head["position_m"])

    def stroke(self, path, speed):
        """The hand along a path, the room stepped until the stroke ends. How it
        ended, and the fastest the head went meanwhile."""
        self.live.act({"session": self.session, "op": "stroke", "path": path, "speed_m_s": speed,
                       "accel_m_s2": 6.0, "lead_m": 0.05, "let_go": False, "give_up_s": 6.0})
        fastest, longest = 0.0, 0.0
        for _ in range(400):
            got = self.live.act({"session": self.session, "op": "step", "dt": 1 / 120.0, "n": 4})
            now = {b["name"]: b for b in got["bodies"]}
            fastest = max(fastest, math.hypot(*(now["mace head"].get("velocity_m_s") or [0, 0, 0])))
            longest = max(longest, self.chain(now))
            hand = got.get("hand") or {}
            if not hand.get("stroking") and hand.get("stroke_ended"):
                return hand["stroke_ended"], fastest, longest
        return "ran out of steps", fastest, longest

    def test_taken_up_by_its_handle_all_of_it_comes_and_the_head_still_swings(self):
        took = self.ask("u1", 0, "take_up", "mace")
        self.assertTrue(took["ok"], took)
        self.assertEqual((took["to"], took["room"]["taken_up"]), ("right", "mace"))
        self.assertNotIn("by", took["room"], "taken up by its handle, the hand holds the handle")
        self.assertEqual(took["shown"]["hands"]["right"]["parts"], ["mace", "mace head"])
        self.assertEqual(self.held(), "mace")

        grip = took["room"]["grip_m"]
        ended, _, longest = self.stroke([grip, [grip[0], grip[1] + 0.9, grip[2]]], 0.8)
        self.assertEqual(ended, "reached")
        now = self.bodies()
        self.assertGreater(now["mace head"]["position_m"][1], 0.4,
                           f"lifted by its handle, the head stayed down: {now['mace head']['position_m']}")
        self.assertLess(longest, CHAIN_WHOLE_M, "the chain stretched: it came apart")

        top = [grip[0], grip[1] + 0.9, grip[2]]
        ended, fastest, longest = self.stroke([top, [top[0] - 1.0, top[1], top[2]]], 3.0)
        self.assertIn(ended, ("reached", "blocked"))
        self.assertGreater(fastest, 1.5, "swung, the head did not swing")
        self.assertLess(longest, CHAIN_WHOLE_M, "swung, the chain stretched: it came apart")

        down = self.ask("d1", 1, "drop", "mace")
        self.assertTrue(down["ok"], down)
        self.assertEqual(self.held(), "")
        self.steps(40)
        landed = self.bodies()
        self.assertLess(landed["mace head"]["position_m"][1], 0.2, landed["mace head"])
        self.assertLess(landed["mace"]["position_m"][1], 0.2, landed["mace"])
        self.assertLess(self.chain(landed), CHAIN_WHOLE_M, "let go, it landed in pieces")

    def test_taken_up_by_its_head_it_is_the_same_thing_and_the_bag_says_why_not(self):
        took = self.ask("u1", 0, "take_up", "mace head")
        self.assertTrue(took["ok"], took)
        self.assertEqual((took["room"]["taken_up"], took["room"]["by"]), ("mace", "mace head"))
        self.assertEqual(inventory_room.inventory_of(self.app).hands["right"], "b-mace000001",
                         "taken up by its head, the record holds something other than the mace")
        self.assertEqual(self.held(), "mace head")
        before = deepcopy(inventory_room.inventory_of(self.app).record())
        stowed = self.ask("s1", 1, "stow", "mace head")
        self.assertFalse(stowed["ok"])
        self.assertIn("cannot go in the bag", stowed["why"])
        self.assertEqual(inventory_room.inventory_of(self.app).record(), before)
        self.assertEqual(self.held(), "mace head", "refused the bag, it was dropped all the same")
        down = self.ask("d1", 1, "drop", "mace")
        self.assertTrue(down["ok"], down)
        self.assertEqual(self.held(), "", "put down by its name, the hand kept its head")

    def test_what_it_weighs_is_all_of_it(self):
        both = inventory_room.whole_kg(self.app, inventory_room.item_holding(self.app, "mace"))
        handle = self.bodies()["mace"]["mass_kg"]
        self.assertGreater(both, handle + 3.0, "the head's iron was not counted")
        # A lift the handle alone is under and the whole mace is over.
        with mock.patch.object(inventory_room.room_world.banjo_mcp, "HAND_LIFTS_KG", handle + 1.0):
            heavy = self.ask("u1", 0, "take_up", "mace")
        self.assertFalse(heavy["ok"])
        self.assertIn(f"weighs {both:.0f} kg", heavy["why"])
        self.assertEqual(self.held(), "")


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


class StoredMaterialState(unittest.TestCase):
    """Storage moves a native instance; it must not recreate its authored state."""

    @unittest.skipUnless(ENGINE.is_file(), "Native inventory regression requires BANJO_BUILD_DIR")
    def test_heated_material_state_survives_storage_restart_and_return(self):
        for material in ("glass", "oak", "iron"):
            with self.subTest(material=material), tempfile.TemporaryDirectory() as folder:
                room_spec=spec()
                room_spec["bodies"][1].update(name="crafted part",shape="box",material=material,
                    size_mm=[120,120,120],center_mm=[0,100,0],temperature_k=900)
                live=live_session.Live()
                app=types.SimpleNamespace(engine_path=ENGINE,runs_path=Path(folder),live=live,
                    room=types.SimpleNamespace(spec=room_spec))
                try:
                    sid=live.open(app,{"spec":room_spec})["session"]
                    for _ in range(20):
                        live.act({"session":sid,"op":"step","dt":1/240,"n":120})
                    before,why=live.snapshot();self.assertIsNotNone(before,why)
                    def heat(saved, rates=True):
                        lump=deepcopy(next(x for x in saved["heat"]["lumps"] if x["body"]=="crafted part"))
                        lump.pop("parked",None)
                        if not rates:
                            for key in ("fuel_use_kg_s","gained_w","lost_w","heat_release_w","heater_w"):
                                lump.pop(key,None)
                        return lump
                    expected=heat(before)
                    took=inventory_room.request(app,{"request":"store-material-0001","revision":0,
                        "op":"take","item":"crafted part","person":PERSON})
                    self.assertTrue(took["ok"],took)
                    stored,why=live.snapshot();self.assertIsNotNone(stored,why)
                    self.assertEqual(heat(stored),expected)
                    self.assertEqual(stored["material_geometry"],before["material_geometry"])
                    record=inventory_room.inventory_of(app).record()
                    live.shutdown()
                    app.room=types.SimpleNamespace(spec=room_spec,inventory_record=record)
                    opened=live.open(app,{"spec":room_spec,"snapshot":stored});sid=opened["session"]
                    self.assertEqual(opened["restored"]["tier"],"whole")
                    shown=inventory_room.after_open(app,opened)
                    self.assertEqual(shown["stowed"][0]["name"],"crafted part")
                    summary=live.act({"session":sid,"op":"poses"})["heat"]
                    stored_reading=next(b for b in summary["stored"] if b["name"]=="crafted part")
                    self.assertEqual(stored_reading["boundary"],"insulated-nonreacting")
                    self.assertGreater(stored_reading["t_k"],293.15)
                    self.assertGreater(stored_reading["core_k"],293.15)
                    self.assertNotIn("crafted part",[b["name"] for b in summary["bodies"]])
                    restored,why=live.snapshot();self.assertIsNotNone(restored,why)
                    self.assertEqual(heat(restored),expected)
                    self.assertEqual(restored["material_geometry"],stored["material_geometry"])
                    # Set aside, time stands still for it: nothing leaves it,
                    # nothing reacts, and its surface and core do not even out
                    # (ThermoWorld::park). Preservation, not a claim of
                    # physical bag cooling.
                    live.act({"session":sid,"op":"step","dt":1/240,"n":120})
                    summary=live.act({"session":sid,"op":"poses"})["heat"]
                    reading=next(b for b in summary["stored"] if b["name"]=="crafted part")
                    full=live.act({"session":sid,"op":"thermo"})["thermo"]
                    exact=next(b for b in full["bodies"] if b["name"]=="crafted part")
                    self.assertTrue(exact["set_aside"])
                    self.assertAlmostEqual(reading["t_k"],exact["temperature_k"],delta=.050001)
                    self.assertAlmostEqual(reading["core_k"],exact["core_temperature_k"],delta=.050001)
                    self.assertEqual(reading,stored_reading)
                    parked,_=live.snapshot();self.assertEqual(heat(parked,False),heat(before,False))
                    dropped=inventory_room.request(app,{"request":"return-material-0001",
                        "revision":shown["record"]["revision"],"op":"drop","item":"crafted part","person":PERSON})
                    self.assertTrue(dropped["ok"],dropped)
                    summary=live.act({"session":sid,"op":"poses"})["heat"]
                    self.assertNotIn("crafted part",[b["name"] for b in summary["stored"]])
                    returned,why=live.snapshot();self.assertIsNotNone(returned,why)
                    returned_heat=heat(returned,False)
                    expected_heat=heat(before,False)
                    # The part was on the floor and is now in free space:
                    # exposed area is a derived boundary, not stored material.
                    self.assertAlmostEqual(returned_heat.pop("exposed_area_m2"),6*.12**2)
                    self.assertAlmostEqual(expected_heat.pop("exposed_area_m2"),5*.12**2)
                    self.assertEqual(returned_heat,expected_heat)
                    self.assertEqual(returned["material_geometry"],stored["material_geometry"])
                    a=next(b for b in stored["bodies"] if b["name"]=="crafted part")
                    b=next(b for b in returned["bodies"] if b["name"]=="crafted part")
                    for field in set(a)-{"pose","parked"}:
                        self.assertEqual(a[field],b[field],field)
                finally:
                    live.shutdown()


if __name__ == "__main__":
    unittest.main(verbosity=2)
