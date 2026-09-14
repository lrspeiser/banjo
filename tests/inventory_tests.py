"""Inventory and two hands (docs/inventory-and-hands.md), below the page.

1. Every thing keeps who it is: an id given when it is made and kept through
   every change and every save, so an item in a hand is that item, not
   whatever has its name now.
"""
from __future__ import annotations

import hashlib
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "playground"))

import fracture_lab   # noqa: E402
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
