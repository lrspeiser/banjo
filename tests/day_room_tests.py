"""A day for the sun in a room (docs/machine-world.md, "A day for the sun"): the
room's day checked, and the tests-day room -- the rover at four in the
afternoon, under a sun whose day is four minutes long -- set going in the real
engine, where it roams on into the night, rests until morning and roams on; and
its day saved and carried, going on from the hour it had got to.

    BANJO_LIVE_ENGINE=.../banjo_live_world_run.exe python tests/day_room_tests.py

Without BANJO_LIVE_ENGINE only the checks that need no engine run, unless
BANJO_DAY_LIVE_TESTS=required, which ctest sets.
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


def day_room() -> dict:
    return world_room.SCENES["tests-day"]()


class TheRoomDeclaresIt(unittest.TestCase):
    """The room's day, as validate() keeps it."""

    def test_its_sun_has_a_day(self):
        room = fracture_lab.validate(day_room())
        self.assertEqual({"day_s": 240.0, "noon_elevation_deg": 60.0, "hour": 16.0, "irradiance_w_m2": 1000.0},
                         room["sun"])
        [program] = room["machines"]["programs"]
        self.assertEqual((0.25, 0.4), (program["rest_below"], program["rest_until"]))
        [store] = room["machines"]["stores"]
        self.assertEqual((5000.0, 3500.0), (store["capacity_j"], store["charge_j"]))

    def test_a_day_the_engine_could_not_keep_is_refused_here(self):
        def refused(change, message):
            room = day_room()
            change(room)
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                fracture_lab.validate(room)

        refused(lambda r: r["sun"].update(day_s=5.0), "day_s")
        refused(lambda r: r["sun"].update(noon_elevation_deg=0.0), "noon_elevation_deg")
        refused(lambda r: r["sun"].update(noon_elevation_deg=95.0), "noon_elevation_deg")
        refused(lambda r: r["sun"].update(hour=25.0), "hour")
        refused(lambda r: r["sun"].update(irradiance_w_m2=1500.0), "irradiance_w_m2")
        refused(lambda r: r["sun"].update(elevation_deg=30.0), "cannot say")

    def test_the_hour_of_24_is_midnight(self):
        room = day_room()
        room["sun"]["hour"] = 24.0
        self.assertEqual(0.0, fracture_lab.validate(room)["sun"]["hour"])


@unittest.skipUnless(ENGINE and ENGINE.is_file(), "BANJO_LIVE_ENGINE is required")
class ItsDay(unittest.TestCase):
    """The tests-day room opened as the playground opens it, the rover set
    going, and the world saved and opened again as a restart does, and carried
    into a changed room as the chat's change does."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.live = live_session.Live()
        self.addCleanup(self.live.shutdown)
        self.room = world_room.Room("tests-day")
        self.app = SimpleNamespace(live=self.live, live_holder="world", room=self.room, engine_path=ENGINE,
                                   runs_path=root / "runs", store=room_store.RoomStore(root / "rooms"))
        self.opened = self.live.open(self.app, {"spec": self.room.spec})

    def step(self, n=1):
        return self.live.session.send(op="step", dt=DT, n=n)

    def test_it_opens_at_four_in_the_afternoon_and_the_sun_sets_at_six(self):
        self.assertNotIn("sun_problem", self.opened)
        sun = self.opened["sun"]
        self.assertEqual((240.0, 60.0, 1000.0),
                         (sun["day_s"], sun["noon_elevation_deg"], sun["zenith_irradiance_w_m2"]))
        self.assertAlmostEqual(16.0, sun["hour"], places=4)
        # In the west, and as high as four hours after noon puts it at a
        # latitude of 30 degrees: sin(elevation) = cos(30) cos(60).
        self.assertAlmostEqual(math.degrees(math.asin(math.cos(math.radians(30.0)) * 0.5)),
                               sun["elevation_deg"], places=3)
        self.assertLess(sun["toward"][0], 0.0)
        reply = self.step(240)                        # a second of the world: six minutes of its day
        self.assertAlmostEqual(16.1, reply["sun"]["hour"], places=4)
        self.assertGreater(reply["machines"]["panels"][0]["power_w"], 0.0)
        reply = self.step(20 * 240)                   # past six
        print(f"\n    at {reply['sun']['hour']:.2f} o'clock the sun is {reply['sun']['elevation_deg']:.1f} degrees "
              f"up; the panel gives {reply['machines']['panels'][0]['power_w']} W", flush=True)
        self.assertLess(reply["sun"]["elevation_deg"], 0.0)
        self.assertEqual(0.0, reply["sun"]["irradiance_w_m2"])
        [panel] = reply["machines"]["panels"]
        self.assertEqual((0.0, 0.0), (panel["power_w"], panel["sunlight_w"]))

    def test_it_roams_into_the_night_rests_until_morning_and_roams_on(self):
        self.step(480)
        program = self.step()["machines"]["programs"][0]
        said = self.live.session.send(op="run", program=program["id"], sender="test", seq=1, power=True)
        self.assertEqual("applied", said["ran"])
        day, sun, order = {}, {}, []
        for i in range(4 * 300):                      # up to five minutes of world, a quarter second at a time
            reply = self.step(60)
            machines = reply["machines"]
            program, store = machines["programs"][0], machines["stores"][0]
            was_up, sun = sun.get("elevation_deg", 1.0) > 0.0, reply["sun"]
            up = sun["elevation_deg"] > 0.0
            if not order or order[-1] != program["doing"]:
                order.append(program["doing"])
            at = {"i": i, "hour": sun["hour"], "taken_j": store["taken_j"], "charge_j": store["charge_j"],
                  "why": program["why"]}
            if was_up and not up:
                day.setdefault("sunset", at)
            if not was_up and up and "sunset" in day:
                day.setdefault("sunrise", at)
            if program["doing"] == "resting":
                day.setdefault("rested", at)
            if "rested" in day and program["doing"] != "resting":
                day.setdefault("woke", at)
            if "woke" in day and program["doing_s"] > 3.0:
                break
        print("\n    " + "; ".join(f"{k} at {v['hour']:.2f} o'clock with {v['charge_j']:.0f} J" for k, v in day.items())
              + f"\n    it did: {order}", flush=True)
        self.assertEqual({"sunset", "rested", "sunrise", "woke"}, set(day), f"its day did not come round: {order}")
        self.assertLess(day["sunset"]["i"], day["rested"]["i"], "it rested before the sun set")
        self.assertLess(day["rested"]["i"], day["sunrise"]["i"], "it did not run low in the night")
        self.assertLess(day["sunrise"]["i"], day["woke"]["i"], "it woke before the sun was up")
        self.assertEqual("its battery is low and the sun is down, so it rests until morning", day["rested"]["why"])
        self.assertEqual(day["sunset"]["taken_j"], day["sunrise"]["taken_j"], "its battery took in sunlight at night")
        self.assertGreater(day["woke"]["charge_j"], 0.4 * 5000.0 - 100.0, "it woke before it was charged")
        store, panel = reply["machines"]["stores"][0], reply["machines"]["panels"][0]
        self.assertAlmostEqual(store["charge_j"], 3500.0 + store["taken_j"] - store["given_j"], places=3)
        self.assertAlmostEqual(store["taken_j"], panel["collected_j"], places=3)

    def test_saved_and_opened_again_its_day_goes_on_from_its_hour(self):
        self.step(10 * 240)                           # to five o'clock
        saved, why = self.live.snapshot()
        self.assertIsNotNone(saved, why)
        self.live.shutdown()
        opened = self.live.open(self.app, {"spec": self.room.spec, "snapshot": saved})
        self.assertEqual("whole", opened["restored"]["tier"], opened["restored"].get("why"))
        self.assertAlmostEqual(17.0, opened["sun"]["hour"], places=4)
        self.assertAlmostEqual(17.1, self.step(240)["sun"]["hour"], places=4)

    def test_carried_into_a_changed_room_its_day_goes_on_and_a_new_day_starts_at_the_rooms_hour(self):
        self.step(10 * 240)
        saved, why = self.live.snapshot()
        self.assertIsNotNone(saved, why)
        changed = deepcopy(self.room.spec)
        changed["bodies"][0]["center_mm"][0] -= 100.0          # the post, in its far corner
        opened = self.live.open(self.app, {"spec": changed, "snapshot": saved, "carry": True})
        self.assertEqual("carried", opened["restored"]["tier"], opened["restored"].get("why"))
        self.assertAlmostEqual(17.0, opened["sun"]["hour"], places=4)
        # A room whose day is not the one the world had begins its own at the
        # room's hour.
        saved, why = self.live.snapshot()
        self.assertIsNotNone(saved, why)
        new_day = deepcopy(changed)
        new_day["sun"]["noon_elevation_deg"] = 45.0
        opened = self.live.open(self.app, {"spec": new_day, "snapshot": saved, "carry": True})
        self.assertEqual((45.0, 16.0), (opened["sun"]["noon_elevation_deg"], round(opened["sun"]["hour"], 4)))


if __name__ == "__main__":
    if os.environ.get("BANJO_DAY_LIVE_TESTS") == "required" and not (ENGINE and ENGINE.is_file()):
        raise RuntimeError("BANJO_LIVE_ENGINE must be built for the required live day tests")
    unittest.main()
