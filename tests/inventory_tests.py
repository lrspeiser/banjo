"""Inventory and two hands (docs/inventory-and-hands.md), below the page.

1. Every thing keeps who it is: an id given when it is made and kept through
   every change and every save, so an item in a hand is that item, not
   whatever has its name now.
"""
from __future__ import annotations

import hashlib
import os
import re
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "playground"))

import fracture_lab   # noqa: E402
import live_session   # noqa: E402
import room_world     # noqa: E402
import world_room     # noqa: E402

banjo_mcp = room_world.banjo_mcp
ID = re.compile(r"b-[0-9a-f]{10}")


def call(world_id: str, name: str, **args):
    answer = room_world.call(world_id, name, args)
    if "error" in answer:
        raise AssertionError(f"{name} refused: {answer['error']}")
    return answer


def cup(**more):
    return dict({"name": "oak cup", "shape": "box", "material": "oak",
                 "size_mm": [80, 80, 80], "center_mm": [0, 40, 0]}, **more)


class ThingsKeepWhoTheyAre(unittest.TestCase):
    """A name can be taken again by something new after the thing that had it
    is gone; an id cannot. The engine finds bodies by name and never reads the
    id: the room and the MCP world keep it."""

    def tearDown(self):
        for world_id in [w for w in banjo_mcp.WORLDS if w.startswith("room-")]:
            room_world.close_room(world_id)

    def test_a_thing_kept_from_before_ids_gets_one_from_its_name_the_same_every_time(self):
        first = fracture_lab.normalise_bodies([cup()], 0.04)[0]["id"]
        again = fracture_lab.normalise_bodies([cup()], 0.04)[0]["id"]
        self.assertEqual(first, again)
        self.assertEqual(first, "b-" + hashlib.sha1(b"oak cup").hexdigest()[:10])

    def test_an_id_is_kept_and_one_repeated_from_another_body_is_made_its_own(self):
        out = fracture_lab.normalise_bodies(
            [cup(id="b-0123456789"), cup(id="b-0123456789", name="oak bowl", center_mm=[400, 40, 0]),
             cup(id="not an id!", name="oak jug", center_mm=[800, 40, 0])], 0.04)
        self.assertEqual(out[0]["id"], "b-0123456789")
        self.assertRegex(out[1]["id"], ID)
        self.assertNotEqual(out[1]["id"], "b-0123456789")
        self.assertEqual(out[2]["id"], "b-" + hashlib.sha1(b"oak jug").hexdigest()[:10])

    def test_what_the_mcp_makes_gets_a_new_id_and_a_copy_gets_its_own(self):
        world_id = room_world.open_room(world_room.clearing())
        call(world_id, "add_object", object={"name": "oak cup", "shape": "box", "material": "oak",
                                              "size_m": [0.08, 0.08, 0.08], "position_m": [0.0, 1.2],
                                              "id": "b-chatfilled"})
        bodies = {b["name"]: b for b in banjo_mcp.WORLDS[world_id]["scene"]["bodies"]}
        made = bodies["oak cup"]["id"]
        self.assertRegex(made, ID, "the chat does not give ids: it fills every field it is shown")
        call(world_id, "duplicate", names=["oak cup"], prefix="second", offset_m=[0.4, 0.0, 0.0])
        bodies = {b["name"]: b for b in banjo_mcp.WORLDS[world_id]["scene"]["bodies"]}
        self.assertEqual(bodies["oak cup"]["id"], made)
        self.assertRegex(bodies["second oak cup"]["id"], ID)
        self.assertNotEqual(bodies["second oak cup"]["id"], made)

    def test_ids_come_through_the_room_and_back_unchanged(self):
        world_id = room_world.open_room(world_room.clearing())
        call(world_id, "build_recipe", recipe="pick", at_m=[0.0, 1.2])
        spec = room_world.export_spec(room_world.entry_of(world_id))
        ids = {b["name"]: b["id"] for b in spec["bodies"]}
        self.assertTrue(ids and all(ID.fullmatch(i) for i in ids.values()), ids)
        self.assertEqual(len(set(ids.values())), len(ids), "two things with one id")
        reopened = room_world.open_room(spec)
        again = {b["name"]: b["id"] for b in room_world.export_spec(room_world.entry_of(reopened))["bodies"]}
        self.assertEqual(again, ids)


ENGINE = (Path(os.environ["BANJO_BUILD_DIR"]) if os.environ.get("BANJO_BUILD_DIR")
          else ROOT / "build" / "integration" / "Release") / \
    ("banjo_platform_cli.exe" if os.name == "nt" else "banjo_platform_cli")


def floor_and_ball():
    return {"algorithm": "lattice", "cell_m": 0.02, "duration_s": 1.0,
            "bodies": [{"name": "floor", "shape": "box", "material": "oak",
                        "size_mm": [600, 40, 400], "center_mm": [0, 20, 0], "anchored": True},
                       {"name": "ball", "shape": "sphere", "material": "iron",
                        "size_mm": [100, 100, 100], "center_mm": [0, 600, 0]}]}


class AThingSetAsideThroughTheRoom(unittest.TestCase):
    """The room's own line to the engine (live_session, the runner's park and
    unpark): what the inventory's bag is made of. Set aside, a thing is out of
    the world a host is sent -- so the page stops drawing it -- and brought back
    it is the same thing, falling where it is put."""

    @classmethod
    def setUpClass(cls):
        if not ENGINE.is_file():
            raise unittest.SkipTest(f"{ENGINE.name} is not built")
        cls._temp = tempfile.TemporaryDirectory()
        cls.app = types.SimpleNamespace(engine_path=ENGINE, runs_path=Path(cls._temp.name))

    @classmethod
    def tearDownClass(cls):
        cls._temp.cleanup()

    def setUp(self):
        self.live = live_session.Live()
        self.addCleanup(self.live.shutdown)

    def names(self, session):
        return [b["name"] for b in self.live.act({"session": session, "op": "poses"})["bodies"]]

    def ball(self, session):
        state = self.live.act({"session": session, "op": "poses"})
        return next(b for b in state["bodies"] if b["name"] == "ball")

    def test_a_ball_set_aside_is_out_of_the_world_and_comes_back_where_it_is_put(self):
        session = self.live.open(self.app, {"spec": floor_and_ball()})["session"]
        for _ in range(20):
            self.live.act({"session": session, "op": "step", "dt": 1 / 120.0, "n": 12})
        self.live.act({"session": session, "op": "park", "name": "ball"})
        for _ in range(5):
            self.live.act({"session": session, "op": "step", "dt": 1 / 120.0, "n": 12})
        self.assertEqual(self.names(session), ["floor"], "the ball is still in the world set aside")
        with self.assertRaises(live_session.LiveError):
            self.live.act({"session": session, "op": "grab", "name": "ball"})

        self.live.act({"session": session, "op": "unpark", "name": "ball", "at": [0.1, 0.5, 0.0]})
        back = self.ball(session)["position_m"]
        self.assertAlmostEqual(back[0], 0.1, places=3)
        self.assertAlmostEqual(back[1], 0.5, places=3)
        for _ in range(20):
            self.live.act({"session": session, "op": "step", "dt": 1 / 120.0, "n": 12})
        landed = self.ball(session)["position_m"][1]
        self.assertLess(landed, 0.45, "the ball brought back did not fall")
        self.assertGreater(landed, 0.04, "the ball brought back fell through the floor")

    def test_what_cannot_be_set_aside_is_refused_in_words(self):
        session = self.live.open(self.app, {"spec": floor_and_ball()})["session"]
        with self.assertRaises(live_session.LiveError) as caught:
            self.live.act({"session": session, "op": "park", "name": "floor"})
        self.assertIn("fixed", str(caught.exception))
        with self.assertRaises(live_session.LiveError) as caught:
            self.live.act({"session": session, "op": "unpark", "name": "ball", "at": [0.1, 0.5]})
        self.assertIn("three numbers", str(caught.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
