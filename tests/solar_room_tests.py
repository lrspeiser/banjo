"""Solar panels in a room (docs/machine-world.md, "Solar panels"): the room's sun
and its panels checked and carried, and the tests-solar room -- a rover whose
battery is nearly flat -- set going in the real engine, where it rests while
the sun charges it and roams on.

    BANJO_LIVE_ENGINE=.../banjo_live_world_run.exe python tests/solar_room_tests.py

Without BANJO_LIVE_ENGINE only the checks that need no engine run, unless
BANJO_SOLAR_LIVE_TESTS=required, which ctest sets.
"""
from __future__ import annotations

from copy import deepcopy
import math
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "playground")]
import fracture_lab, live_session, room_store, world_room   # noqa: E402

ENGINE = Path(os.environ["BANJO_LIVE_ENGINE"]).resolve() if os.environ.get("BANJO_LIVE_ENGINE") else None
DT = 1 / 240


def solar_room() -> dict:
    return world_room.SCENES["tests-solar"]()


class TheRoomDeclaresIt(unittest.TestCase):
    """The room's sun and its panel, as validate() keeps them."""

    def test_its_sun_its_panel_and_how_the_rover_rests(self):
        room = fracture_lab.validate(solar_room())
        self.assertEqual({"elevation_deg": 50.0, "azimuth_deg": 200.0, "irradiance_w_m2": 1000.0}, room["sun"])
        [panel] = room["machines"]["panels"]
        self.assertEqual(("solar panel", "rover", "rover battery", 0.2, 0.2),
                         (panel["name"], panel["body"], panel["store"], panel["area_m2"], panel["efficiency"]))
        self.assertGreater(panel["normal"][1], 0.99)                 # the deck's up, tipped to the shore
        [program] = room["machines"]["programs"]
        self.assertEqual((0.25, 0.6), (program["rest_below"], program["rest_until"]))
        [store] = room["machines"]["stores"]
        self.assertEqual((5000.0, 1400.0), (store["capacity_j"], store["charge_j"]))

    def test_a_sun_or_a_panel_the_engine_could_not_use_is_refused_here(self):
        def refused(change, message):
            room = solar_room()
            change(room)
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                fracture_lab.validate(room)

        refused(lambda r: r["sun"].update(elevation_deg=-3.0), "elevation_deg")
        refused(lambda r: r["sun"].update(irradiance_w_m2=2000.0), "irradiance_w_m2")
        refused(lambda r: r["sun"].update(colour="yellow"), "cannot say")
        panel = lambda r: r["machines"]["panels"][0]
        refused(lambda r: panel(r).update(store="spare battery"), "no store called")
        refused(lambda r: panel(r).update(body="nothing here"), "not in this room")
        refused(lambda r: panel(r).update(normal=[0, 0, 0]), "look some way")
        refused(lambda r: panel(r).update(area_m2=0.0), "area_m2")
        refused(lambda r: panel(r).update(efficiency=1.5), "efficiency")
        refused(lambda r: panel(r).update(tilt=10), "cannot say")
        refused(lambda r: r["machines"]["programs"][0].update(rest_until=0.1), "rest_until")

    def test_a_room_without_a_sun_says_nothing_of_one(self):
        room = solar_room()
        room.pop("sun")
        self.assertNotIn("sun", fracture_lab.validate(room))

    def test_the_azimuth_is_kept_round_the_circle(self):
        room = solar_room()
        room["sun"]["azimuth_deg"] = -90.0
        self.assertEqual(270.0, fracture_lab.validate(room)["sun"]["azimuth_deg"])


class CarryingIt(unittest.TestCase):
    """A panel made the same way is kept, as a store is; moved, it goes on anew
    and its part comes back as the room has it."""

    def room(self):
        room = fracture_lab.validate(solar_room())
        for i, pin in enumerate(room["joints"]):
            pin["id"] = i + 1
        return room

    def was(self, room):
        made = {"stores": {"rover battery": 1},
                "motors": {("rover", "rover: left wheel"): 1, ("rover", "rover: right wheel"): 2},
                "controls": {"left wheel": 1, "right wheel": 2}, "programs": {"rover": 1},
                "panels": {"solar panel": 1}}
        return live_session._declared(room, None, made)

    def test_a_panel_made_the_same_way_is_kept(self):
        room = self.room()
        plan = live_session.carry_plan(self.was(room), deepcopy(room))
        self.assertEqual([1], plan["engine"]["solar_panels"])
        self.assertEqual([], plan["engine"]["declared_anew"])

    def test_a_panel_moved_goes_on_anew(self):
        room = self.room()
        moved = deepcopy(room)
        moved["machines"]["panels"][0]["at_mm"][2] += 100.0
        plan = live_session.carry_plan(self.was(room), moved)
        self.assertEqual([], plan["engine"]["solar_panels"])
        self.assertEqual(["rover"], plan["engine"]["declared_anew"])


@unittest.skipUnless(ENGINE and ENGINE.is_file(), "BANJO_LIVE_ENGINE is required")
class ChargingIt(unittest.TestCase):
    """The tests-solar room opened as the playground opens it, the rover set
    going, and the world saved and opened again as a restart does."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.live = live_session.Live()
        self.addCleanup(self.live.shutdown)
        self.room = world_room.Room("tests-solar")
        self.app = SimpleNamespace(live=self.live, live_holder="world", room=self.room, engine_path=ENGINE,
                                   runs_path=root / "runs", store=room_store.RoomStore(root / "rooms"))
        self.opened = self.live.open(self.app, {"spec": self.room.spec})

    def machines(self, n=1):
        return self.live.session.send(op="step", dt=DT, n=n)["machines"]

    def test_it_opens_with_its_sun_up_and_its_panel_in_it(self):
        self.assertNotIn("sun_problem", self.opened)
        self.assertNotIn("machine_problems", self.opened)
        sun = self.opened["sun"]
        self.assertEqual(50.0, sun["elevation_deg"])
        self.assertAlmostEqual(math.sin(math.radians(50.0)), sun["toward"][1], places=5)
        [panel] = self.machines(240)["panels"]
        # The sun on its face: its irradiance, times its area, times the cosine
        # of the angle between its face and the sun; a fifth of that charges.
        self.assertFalse(panel["shaded"])
        self.assertAlmostEqual(1000.0 * 0.2 * panel["cos_incidence"], panel["sunlight_w"], places=2)
        self.assertAlmostEqual(0.2 * panel["sunlight_w"], panel["power_w"], places=2)

    def test_turned_on_it_rests_while_the_sun_charges_it_and_roams_on(self):
        self.live.session.send(op="step", dt=DT, n=480)
        program = self.machines()["programs"][0]
        said = self.live.session.send(op="run", program=program["id"], sender="test", seq=1, power=True)
        self.assertEqual("applied", said["ran"])
        order, rested_at = [], None
        for _ in range(4 * 150):                      # up to two and a half minutes of world
            machines = self.machines(60)
            program = machines["programs"][0]
            if not order or order[-1] != program["doing"]:
                order.append(program["doing"])
                if program["doing"] == "resting":
                    rested_at = machines["stores"][0]["charge_j"]
            if program["rests"] >= 1 and program["doing"] != "resting" and program["doing_s"] > 3.0:
                break
        store = machines["stores"][0]
        panel = machines["panels"][0]
        print(f"\n    {order}: rested at {rested_at:.0f} J; now {store['charge_j']:.0f} J, having taken in "
              f"{store['taken_j']:.0f} J and given {store['given_j']:.0f} J")
        self.assertIn("resting", order)
        self.assertNotEqual("resting", program["doing"], "it never roamed on")
        self.assertLess(rested_at, 0.25 * 5000.0 + 50.0)
        self.assertAlmostEqual(store["charge_j"], 1400.0 + store["taken_j"] - store["given_j"], places=3)
        self.assertAlmostEqual(store["taken_j"], panel["collected_j"], places=3)

    def test_saved_and_opened_again_its_sun_and_panel_come_back(self):
        self.live.session.send(op="step", dt=DT, n=960)
        before = self.machines()
        saved, why = self.live.snapshot()
        self.assertIsNotNone(saved, why)
        self.live.shutdown()
        opened = self.live.open(self.app, {"spec": self.room.spec, "snapshot": saved})
        self.assertEqual("whole", opened["restored"]["tier"], opened["restored"].get("why"))
        self.assertEqual(50.0, opened["sun"]["elevation_deg"])
        after = self.machines()
        self.assertEqual(len(before["panels"]), len(after["panels"]))
        self.assertGreaterEqual(after["panels"][0]["collected_j"], before["panels"][0]["collected_j"])
        self.assertGreater(after["panels"][0]["power_w"], 0.0)


if __name__ == "__main__":
    if os.environ.get("BANJO_SOLAR_LIVE_TESTS") == "required" and not (ENGINE and ENGINE.is_file()):
        raise RuntimeError("BANJO_LIVE_ENGINE must be built for the required live solar tests")
    unittest.main()
