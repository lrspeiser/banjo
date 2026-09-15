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


class TheBagKeepsItsSlots(unittest.TestCase):
    """The page numbers the bag's slots 1 to 9, and the number that took a thing
    out puts it back (the owner, 2026-09-14): a thing keeps its slot while a hand
    holds it, and nothing else is put there meanwhile."""

    def setUp(self):
        names = ("cup", "jug", "bowl", "pan")
        self.room = {"bodies": [body(n, f"b-{n}{i:06d}", center_mm=[200 * i, 40, 0])
                                for i, n in enumerate(names)]}
        self.items = inventory.items_of(self.room)
        self.ids = {i["name"]: i["id"] for i in self.items}
        self.inv = inventory.Inventory()
        self.asked = 0

    def ask(self, op, name):
        self.asked += 1
        answer = self.inv.request(f"r{self.asked}", None, op, self.ids[name], self.items,
                                  lambda plan: None)
        self.assertTrue(answer["ok"], answer)
        return answer

    def slots(self, *names):
        return [self.ids[n] if n else None for n in names]

    def test_a_thing_held_from_its_slot_goes_back_to_it_and_its_slot_is_kept_meanwhile(self):
        for name in ("cup", "jug", "bowl"):
            self.ask("take", name)
        self.assertEqual(self.inv.stowed, self.slots("cup", "jug", "bowl"))
        self.ask("equip", "jug")
        self.assertEqual(self.inv.stowed, self.slots("cup", None, "bowl"))
        self.assertEqual(self.inv.slot_of(self.ids["jug"]), 1)
        self.ask("take", "pan")
        self.assertEqual(self.inv.stowed, self.slots("cup", None, "bowl", "pan"),
                         "a thing taken in took the slot kept for the jug in the hand")
        self.ask("stow", "jug")
        self.assertEqual(self.inv.stowed, self.slots("cup", "jug", "bowl", "pan"))
        self.assertEqual(self.inv.home, {})

    def test_a_thing_put_down_from_the_hand_frees_its_slot_for_the_next(self):
        self.ask("take", "cup")
        self.ask("take", "jug")
        self.ask("equip", "cup")
        self.ask("drop", "cup")
        self.assertEqual((self.inv.stowed, self.inv.home), (self.slots(None, "jug"), {}))
        self.ask("take", "bowl")
        self.assertEqual(self.inv.stowed, self.slots("bowl", "jug"))

    def test_a_thing_taken_up_from_the_world_has_no_slot_until_it_is_stowed_in_the_first_free(self):
        for name in ("cup", "jug", "bowl"):
            self.ask("take", name)
        self.ask("equip", "jug")
        self.ask("drop", "jug")
        took = self.ask("take_up", "pan")
        self.assertEqual(took["to"], "right")
        self.assertIsNone(self.inv.slot_of(self.ids["pan"]))
        self.ask("stow", "pan")
        self.assertEqual(self.inv.stowed, self.slots("cup", "pan", "bowl"))

    def test_a_room_opened_again_puts_the_hands_thing_back_in_its_own_slot(self):
        for name in ("cup", "jug", "bowl"):
            self.ask("take", name)
        self.ask("equip", "cup")
        kept = inventory.Inventory(self.inv.record())
        self.assertEqual(kept.home, {self.ids["cup"]: 0})
        self.assertTrue(kept.back_to_bag("right"))
        self.assertEqual(kept.stowed, self.slots("cup", "jug", "bowl"))
        self.assertEqual((kept.hands["right"], kept.home), (None, {}))
        self.assertFalse(kept.back_to_bag("right"), "an empty hand put something back")

    def test_slots_with_gaps_keep_and_read_back_and_a_record_from_before_reads_the_same(self):
        for name in ("cup", "jug", "bowl"):
            self.ask("take", name)
        self.ask("equip", "jug")
        self.ask("drop", "jug")
        kept = self.inv.record()
        self.assertEqual(kept["stowed"], self.slots("cup", None, "bowl"))
        self.assertEqual(inventory.Inventory(kept).record(), kept)
        before = inventory.Inventory({"revision": 2, "stowed": ["b-a", "b-b"]})
        self.assertEqual((before.stowed, before.home), (["b-a", "b-b"], {}))

    def test_a_broken_piece_is_refused_as_not_one_of_the_rooms_things(self):
        piece = self.inv.request("x1", None, "take_up", "cup piece 3", self.items, lambda plan: None)
        self.assertFalse(piece["ok"])
        self.assertTrue(piece.get("unknown"), "a broken piece read as a thing that cannot be taken")
        gone = self.inv.request("x2", None, "take", self.ids["cup"], self.items,
                                lambda plan: (_ for _ in ()).throw(ValueError("it is breaking")))
        self.assertFalse(gone["ok"])
        self.assertNotIn("unknown", gone)


class WhatAPersonHasIsKeptWithTheRoom(unittest.TestCase):
    """room_store keeps the record with the room, so a server restart -- the sims
    are restarted whenever work lands -- does not hand the bag's things back."""

    def test_the_room_store_keeps_the_record_and_reads_it_back(self):
        import tempfile
        import room_store
        import world_room
        with tempfile.TemporaryDirectory() as folder:
            store = room_store.RoomStore(folder)
            room = world_room.Room("world")
            room.inventory = inventory.Inventory({"revision": 2, "stowed": ["b-cup0000001"],
                                                  "facing": {"b-cup0000001": [1, 0, 0, 0]}})
            self.assertTrue(store.save(room))
            back = store.load("world")
            self.assertEqual(back.inventory_record, room.inventory.record())
            self.assertEqual(inventory.Inventory(back.inventory_record).stowed, ["b-cup0000001"])

    def test_a_room_kept_before_there_was_an_inventory_reads_as_a_person_with_nothing(self):
        import tempfile
        import room_store
        import world_room
        with tempfile.TemporaryDirectory() as folder:
            store = room_store.RoomStore(folder)
            self.assertTrue(store.save(world_room.Room("world")))
            back = store.load("world")
            self.assertIsNone(back.inventory_record)
            nothing = inventory.Inventory(back.inventory_record)
            self.assertEqual((nothing.stowed, nothing.hands), ([], {"right": None, "left": None}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
