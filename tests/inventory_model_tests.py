"""The inventory's record (playground/inventory.py), below the room: what the
room's things are, and the only way what a person has can change.

No engine here -- the room's physical part is a stand-in that does nothing or
refuses, so what is checked is the record's own rules:
- the same request is done once;
- a request against a stale revision is refused;
- an item is in one place;
- nothing is changed unless the room did its part.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "playground"))

import inventory  # noqa: E402


def body(name, bid, **more):
    return dict({"id": bid, "name": name, "shape": "box", "material": "oak",
                 "size_mm": [80, 80, 80], "center_mm": [0, 40, 0]}, **more)


ROOM = {"bodies": [body("oak cup", "b-cup0000001"),
                   body("pick haft", "b-pick000002", join="pick"),
                   body("pick arm", "b-pick000001", join="pick"),
                   body("gate post", "b-post000001", anchored=True),
                   body("oak gate", "b-gate000001"),
                   body("stool seat", "b-stool00001"),
                   body("stool leg", "b-stool00002")],
        "joints": [{"kind": "hinge", "a": "gate post", "b": "oak gate"},
                   {"kind": "fixing", "a": "stool seat", "b": "stool leg"}]}


def item_named(items, name):
    return next(i for i in items if name in i["bodies"])


class TheRoomsThingsAsAPersonCountsThem(unittest.TestCase):

    def test_a_join_group_is_one_item_named_after_its_first_part(self):
        items = inventory.items_of(ROOM)
        pick = item_named(items, "pick arm")
        self.assertEqual((pick["name"], pick["bodies"], pick["id"]),
                         ("pick haft", ["pick haft", "pick arm"], "b-pick000001"))
        self.assertTrue(pick["one_piece"])
        self.assertFalse(pick["installed"])

    def test_a_gate_on_its_post_is_installed_and_a_stool_is_one_thing(self):
        items = inventory.items_of(ROOM)
        gate = item_named(items, "oak gate")
        self.assertTrue(gate["installed"], "a gate hinged to an anchored post was portable")
        self.assertEqual(sorted(gate["bodies"]), ["gate post", "oak gate"])
        stool = item_named(items, "stool leg")
        self.assertEqual(sorted(stool["bodies"]), ["stool leg", "stool seat"])
        self.assertFalse(stool["installed"])
        self.assertFalse(stool["one_piece"], "a stool of joined parts cannot be set aside as one body yet")
        self.assertEqual(len(items), 4)


class WhatAPersonHasChangesOnlyByRequest(unittest.TestCase):

    def setUp(self):
        self.items = inventory.items_of(ROOM)
        self.inv = inventory.Inventory()
        self.done = []

    def act(self, plan):
        self.done.append((plan["op"], plan["item"], plan["to"]))
        return None

    def test_taking_a_cup_puts_it_in_the_inventory_once_whatever_the_retries(self):
        first = self.inv.request("r1", 0, "take", "b-cup0000001", self.items, self.act)
        self.assertTrue(first["ok"], first)
        self.assertEqual(first["did"], "Oak cup added to inventory.")
        self.assertEqual(self.inv.where("b-cup0000001"), "stowed")
        again = self.inv.request("r1", 0, "take", "b-cup0000001", self.items, self.act)
        self.assertIs(again, first, "a retry was not answered as the first time")
        self.assertEqual(len(self.done), 1, "a retry did the room's part twice")
        self.assertEqual(self.inv.revision, 1)

    def test_a_request_against_a_revision_that_has_moved_on_is_refused_with_the_record(self):
        self.inv.request("r1", 0, "take", "b-cup0000001", self.items, self.act)
        stale = self.inv.request("r2", 0, "take", "b-pick000001", self.items, self.act)
        self.assertFalse(stale["ok"])
        self.assertIn("changed", stale["why"])
        self.assertEqual(stale["record"]["stowed"], ["b-cup0000001"])
        self.assertEqual(self.inv.where("b-pick000001"), "world")

    def test_nothing_changes_when_the_room_could_not_do_its_part(self):
        def refuse(plan):
            raise ValueError("it is breaking: it cannot be set aside while it comes apart")
        answer = self.inv.request("r1", 0, "take", "b-cup0000001", self.items, refuse)
        self.assertFalse(answer["ok"])
        self.assertIn("breaking", answer["why"])
        self.assertEqual((self.inv.where("b-cup0000001"), self.inv.revision), ("world", 0))

    def test_installed_or_joined_things_are_not_taken(self):
        gate = self.inv.request("r1", None, "take", item_named(self.items, "oak gate")["id"],
                                self.items, self.act)
        self.assertFalse(gate["ok"])
        self.assertIn("fixed in place", gate["why"])
        stool = self.inv.request("r2", None, "take", item_named(self.items, "stool seat")["id"],
                                 self.items, self.act)
        self.assertFalse(stool["ok"])
        self.assertIn("joined", stool["why"])
        self.assertEqual(self.done, [])

    def test_a_tool_goes_to_the_dominant_hand_and_to_the_inventory_when_the_hands_are_full(self):
        took = self.inv.request("r1", None, "take_up", "b-pick000001", self.items, self.act)
        self.assertEqual((took["to"], took["did"]), ("right", "Took up pick haft in your right hand."))
        cup = self.inv.request("r2", None, "take_up", "b-cup0000001", self.items, self.act)
        self.assertEqual(cup["to"], "left")
        self.inv.request("r3", None, "stow", "b-cup0000001", self.items, self.act)
        self.inv.hands["left"] = "b-something"   # the other hand busy with something else
        full = self.inv.request("r4", None, "take_up", "b-cup0000001", self.items, self.act)
        self.assertFalse(full["ok"], "a stowed cup was taken up again from the world")
        self.inv.hands["left"] = None

    def test_equip_is_refused_with_both_hands_full_and_never_drops_what_they_hold(self):
        self.inv.request("r1", None, "take", "b-cup0000001", self.items, self.act)
        self.inv.hands = {"right": "b-pick000001", "left": "b-other000001"}
        full = self.inv.request("r2", None, "equip", "b-cup0000001", self.items, self.act)
        self.assertFalse(full["ok"])
        self.assertIn("both hands are full", full["why"])
        self.assertEqual(self.inv.hands, {"right": "b-pick000001", "left": "b-other000001"})

    def test_the_record_keeps_and_reads_back_and_an_item_is_in_one_place(self):
        self.inv.request("r1", None, "take", "b-cup0000001", self.items, self.act)
        self.inv.request("r2", None, "take_up", "b-pick000001", self.items, self.act)
        kept = self.inv.record()
        back = inventory.Inventory(kept)
        self.assertEqual(back.record(), kept)
        doubled = inventory.Inventory({"revision": 3, "hands": {"right": "b-cup0000001"},
                                       "stowed": ["b-cup0000001", "b-cup0000001"]})
        self.assertEqual(doubled.stowed, [], "an item in a hand was also kept in the inventory")


if __name__ == "__main__":
    unittest.main(verbosity=2)
