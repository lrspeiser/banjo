"""A container holds matter, and tips it out.

The owner, 2026-09-27: *"so i can have a bucket that holds sand or a kettle
that holds water... turning the bucket over should pour the voxels out into
a different container. however if we don't want to model it we can convert
the voxels to a single mass when in a container."*

These check the second of those: a mass held by a body, that rides the body,
and that comes out when the body is turned over -- into another container if
one is under the mouth, onto the ground if not.

    python tests/vessels_tests.py
"""
from __future__ import annotations

import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "playground")]
import machine_goods  # noqa: E402
import vessels        # noqa: E402


def upright():
    return [1.0, 0.0, 0.0, 0.0]


def turned(degrees, axis=(0.0, 0.0, 1.0)):
    """A quaternion turning by `degrees` about an axis, w first."""
    half = math.radians(degrees) / 2.0
    s = math.sin(half)
    return [math.cos(half), axis[0] * s, axis[1] * s, axis[2] * s]


def room(*rows):
    return {"vessels": list(rows)}


def a_bucket(name, body, holds=None, **more):
    return {"name": name, "body": body, "capacity_kg": 20.0,
            "holds": holds or {}, "mouth_mm": [0, 150, 0], **more}


class TheRoomsSpelling(unittest.TestCase):
    def test_a_vessel_is_checked_in_the_rooms_own_words(self):
        [made] = vessels.checked([a_bucket("pail", "pail body", {"sand": 5.0})])
        self.assertEqual(("pail", "pail body", 20.0), (made["name"], made["body"], made["capacity_kg"]))
        self.assertEqual({"sand": 5.0}, made["holds"])
        self.assertEqual(vessels.POURS_PAST_DEG, made["pours_past_deg"], "a default it need not say")
        self.assertEqual([], vessels.checked(None))

    def test_what_is_wrong_is_said_by_name(self):
        for broken, why in (
                ([{"body": "b"}], "needs a name"),
                ([{"name": "a"}], "rides a body"),
                ([a_bucket("a", "b"), a_bucket("a", "c")], "name of its own"),
                ([dict(a_bucket("a", "b"), colour="red")], "cannot say"),
                ([dict(a_bucket("a", "b", {"sand": 50.0}))], "holds 50 kg and takes 20"),
                ([dict(a_bucket("a", "b"), capacity_kg=0.0)], "capacity_kg must be between")):
            with self.subTest(why=why), self.assertRaisesRegex(ValueError, why):
                vessels.checked(broken)

    def test_it_will_not_hold_more_than_it_takes_nor_what_it_does_not_accept(self):
        held = vessels.Vessels(room(a_bucket("pail", "pail", accepts=["sand"], capacity_kg=10.0)))
        pail = held.by_name("pail")
        self.assertEqual({"sand": 8.0}, pail.put({"sand": 8.0}))
        self.assertEqual({"sand": 2.0}, pail.put({"sand": 5.0}), "only what is left of its room")
        self.assertEqual(10.0, pail.held_kg())
        self.assertEqual({}, pail.put({"water": 1.0}), "it takes sand and says so by taking none")
        self.assertTrue(vessels.Vessels(room(a_bucket("any", "b"))).by_name("any").takes("anything"),
                        "a vessel that names no substances takes any")


class ItRidesItsBody(unittest.TestCase):
    def test_the_mouth_goes_where_the_body_goes(self):
        held = vessels.Vessels(room(a_bucket("pail", "pail")))
        held.follow([{"name": "pail", "position_m": [2.0, 0.5, -3.0], "orientation_wxyz": upright()}])
        pail = held.by_name("pail")
        self.assertEqual([2.0, 0.65, -3.0], [round(v, 4) for v in pail.mouth_m],
                         "150 mm up the body, and the body is at 0.5")
        self.assertAlmostEqual(0.0, pail.tilt_deg, places=6, msg="upright is no tilt")
        # Carried away and turned: the mouth turns with it.
        held.follow([{"name": "pail", "position_m": [0.0, 1.0, 0.0], "orientation_wxyz": turned(90)}])
        self.assertAlmostEqual(90.0, pail.tilt_deg, places=4)
        self.assertEqual([-0.15, 1.0, 0.0], [round(v, 4) for v in pail.mouth_m],
                         "on its side, the mouth points sideways")

    def test_a_body_that_did_not_move_keeps_where_it_was(self):
        held = vessels.Vessels(room(a_bucket("a", "a"), a_bucket("b", "b")))
        held.follow([{"name": "a", "position_m": [1.0, 0.0, 0.0], "orientation_wxyz": upright()},
                     {"name": "b", "position_m": [2.0, 0.0, 0.0], "orientation_wxyz": upright()}])
        # A step carries only what changed (machine_ports.follow reads the
        # same way): b is not in this one and must not be forgotten.
        held.follow([{"name": "a", "position_m": [9.0, 0.0, 0.0], "orientation_wxyz": upright()}])
        self.assertEqual(9.0, round(held.by_name("a").mouth_m[0], 4))
        self.assertEqual(2.0, round(held.by_name("b").mouth_m[0], 4))


class TurningItOver(unittest.TestCase):
    def test_upright_it_holds_and_over_it_pours(self):
        held = vessels.Vessels(room(a_bucket("pail", "pail", {"sand": 10.0})))
        held.follow([{"name": "pail", "position_m": [0.0, 1.0, 0.0], "orientation_wxyz": upright()}])
        self.assertEqual([], held.spill(1.0), "upright, nothing comes out")
        self.assertEqual(10.0, held.by_name("pail").held_kg())
        # Tipped past its angle it begins to pour, and harder the further over.
        held.follow([{"name": "pail", "position_m": [0.0, 1.0, 0.0], "orientation_wxyz": turned(50)}])
        self.assertEqual([], held.spill(1.0), "50 degrees is not past 60")
        held.follow([{"name": "pail", "position_m": [0.0, 1.0, 0.0], "orientation_wxyz": turned(120)}])
        [said] = held.spill(1.0)
        self.assertEqual("pail", said["from"])
        self.assertEqual("the ground", said["into"], "nothing under it to catch it")
        self.assertGreater(said["poured_kg"]["sand"], 0.0)
        self.assertLess(held.by_name("pail").held_kg(), 10.0)

    def test_a_pail_held_over_another_fills_it(self):
        """The owner's own example, and the whole point of the thing."""
        held = vessels.Vessels(room(
            a_bucket("upper", "upper", {"sand": 12.0}),
            a_bucket("lower", "lower")))
        held.follow([
            {"name": "upper", "position_m": [0.0, 1.2, 0.0], "orientation_wxyz": turned(150)},
            {"name": "lower", "position_m": [0.0, 0.3, 0.0], "orientation_wxyz": upright()}])
        for _ in range(40):                 # four seconds at a tenth each
            held.spill(0.1)
        upper, lower = held.by_name("upper"), held.by_name("lower")
        self.assertAlmostEqual(0.0, upper.held_kg(), places=6, msg="it emptied")
        self.assertAlmostEqual(12.0, lower.held_kg(), places=6,
                               msg="and every kilogram of it is in the other one")
        self.assertEqual({"sand": 12.0}, {k: round(v, 6) for k, v in lower.holds.items()})

    def test_what_the_lower_one_cannot_hold_lands_on_the_ground(self):
        goods = machine_goods.Goods({"goods": {"deposits": [], "stockpiles": [], "recipes": []}})
        held = vessels.Vessels(room(
            a_bucket("upper", "upper", {"sand": 12.0}),
            a_bucket("lower", "lower", capacity_kg=4.0)))
        held.follow([
            {"name": "upper", "position_m": [0.0, 1.2, 0.0], "orientation_wxyz": turned(180)},
            {"name": "lower", "position_m": [0.0, 0.3, 0.0], "orientation_wxyz": upright()}])
        for _ in range(40):
            held.spill(0.1, goods)
        self.assertAlmostEqual(4.0, held.by_name("lower").held_kg(), places=6, msg="it filled up")
        self.assertAlmostEqual(0.0, held.by_name("upper").held_kg(), places=6)
        on_the_floor = sum(sum((s.get("holds") or {}).values()) for s in goods.stockpiles)
        self.assertAlmostEqual(8.0, on_the_floor, places=6, msg="the rest missed and is on the ground")

    def test_it_pours_into_the_nearest_one_under_it_and_not_one_beside_it(self):
        held = vessels.Vessels(room(
            a_bucket("upper", "upper", {"sand": 6.0}),
            a_bucket("under", "under"),
            a_bucket("beside", "beside")))
        held.follow([
            {"name": "upper", "position_m": [0.0, 1.2, 0.0], "orientation_wxyz": turned(180)},
            {"name": "under", "position_m": [0.05, 0.3, 0.0], "orientation_wxyz": upright()},
            {"name": "beside", "position_m": [1.5, 0.3, 0.0], "orientation_wxyz": upright()}])
        for _ in range(30):
            held.spill(0.1)
        self.assertAlmostEqual(6.0, held.by_name("under").held_kg(), places=6)
        self.assertEqual(0.0, held.by_name("beside").held_kg(), "a pail beside it catches nothing")

    def test_two_substances_pour_together_in_proportion(self):
        held = vessels.Vessels(room(a_bucket("pail", "pail", {"sand": 6.0, "clay": 2.0})))
        held.follow([{"name": "pail", "position_m": [0.0, 1.0, 0.0], "orientation_wxyz": turned(180)}])
        [said] = held.spill(0.1)
        poured = said["poured_kg"]
        self.assertAlmostEqual(3.0, poured["sand"] / poured["clay"], places=4,
                               msg="three of sand to one of clay, as it holds them")

    def test_what_it_holds_is_kept_with_the_room(self):
        spec = room(a_bucket("pail", "pail", {"sand": 10.0}))
        held = vessels.Vessels(spec)
        held.follow([{"name": "pail", "position_m": [0.0, 1.0, 0.0], "orientation_wxyz": turned(180)}])
        held.spill(0.4)
        held.save()
        left = spec["vessels"][0]["holds"]["sand"]
        self.assertLess(left, 10.0)
        self.assertAlmostEqual(left, held.by_name("pail").holds["sand"], places=4,
                               msg="the room's own block says what the vessel says")
        # And a room opened from that block starts as full as it was left.
        self.assertAlmostEqual(left, vessels.Vessels(spec).by_name("pail").holds["sand"], places=6)

    def test_the_page_is_told_what_each_one_holds(self):
        held = vessels.Vessels(room(a_bucket("pail", "pail", {"sand": 3.0})))
        held.follow([{"name": "pail", "position_m": [1.0, 0.5, 2.0], "orientation_wxyz": upright()}])
        [slot] = held.holders()
        self.assertEqual(("pail", "pail", {"sand": 3.0}, 20.0), (slot["name"], slot["body"],
                                                                 slot["holds_kg"], slot["capacity_kg"]))
        self.assertEqual(0.0, slot["tilt_deg"])
        self.assertEqual(0.0, slot["pouring"])




class InTheRoomItself(unittest.TestCase):
    """The wiring, not just the module: a room declares a vessel, the room's
    own checks accept it, and the brains ride it and pour it every step."""

    def room_with_a_pail(self, holds):
        import world_room, fracture_lab
        spec = world_room.yard()
        body = spec["bodies"][0]["name"]
        spec["vessels"] = [{"name": "pail", "body": body, "capacity_kg": 20.0,
                            "holds": holds, "mouth_mm": [0, 150, 0]}]
        return fracture_lab.validate(spec), body

    def test_a_room_may_declare_one_and_it_is_checked_against_the_rooms_bodies(self):
        spec, body = self.room_with_a_pail({"sand": 8.0})
        self.assertEqual("pail", spec["vessels"][0]["name"])
        self.assertEqual(body, spec["vessels"][0]["body"])
        # And a vessel on a body the room has not got is refused by name.
        import world_room, fracture_lab
        bad = world_room.yard()
        bad["vessels"] = [{"name": "pail", "body": "no such thing", "capacity_kg": 1.0}]
        with self.assertRaisesRegex(ValueError, "no such body in the room"):
            fracture_lab.validate(bad)

    def test_the_brains_ride_it_and_pour_it_as_the_room_steps(self):
        import rover_brain
        spec, body = self.room_with_a_pail({"sand": 10.0})
        brains = rover_brain.Brains(lambda: None)
        brains.opened(spec)
        self.assertTrue(brains.vessels, "the room's containers are made when it opens")

        def step(t, q):
            brains.listen(None, {"t": t, "machines": {"programs": []},
                                 "bodies": [{"name": body, "position_m": [0.0, 1.0, 0.0],
                                             "orientation_wxyz": q}]})

        step(0.1, upright())
        self.assertEqual(10.0, brains.vessels.by_name("pail").held_kg(), "upright it keeps it")
        for i in range(1, 41):                      # four seconds, turned over
            step(0.1 + i * 0.1, turned(180))
        self.assertAlmostEqual(0.0, brains.vessels.by_name("pail").held_kg(), places=6,
                               msg="turned over as the room steps, it empties")
        # And what came out is on the ground, in the room's own goods ledger.
        on_the_floor = sum(sum((s.get("holds") or {}).values()) for s in brains.goods.stockpiles)
        self.assertAlmostEqual(10.0, on_the_floor, places=6)

    def test_the_page_is_sent_every_container_each_step(self):
        import rover_brain
        spec, body = self.room_with_a_pail({"sand": 2.0})
        brains = rover_brain.Brains(lambda: None)
        brains.opened(spec)
        brains.listen(None, {"t": 0.1, "machines": {"programs": []},
                             "bodies": [{"name": body, "position_m": [0.0, 1.0, 0.0],
                                         "orientation_wxyz": upright()}]})
        answer = {}
        brains.attach({"op": "step"}, answer)
        self.assertEqual(1, len(answer["vessels"]))
        self.assertEqual({"sand": 2.0}, answer["vessels"][0]["holds_kg"])


if __name__ == "__main__":
    unittest.main()
