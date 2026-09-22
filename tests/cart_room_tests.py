"""The cart that drives itself (docs/machine-world.md, "One autonomous creature"):
the room's declaration of a controller's sensors, checked, carried and put on,
and the tests-cart room opened and driven in the real engine.

    BANJO_LIVE_ENGINE=.../banjo_live_world_run.exe python tests/cart_room_tests.py

Without BANJO_LIVE_ENGINE only the checks that need no engine run, unless
BANJO_CART_LIVE_TESTS=required, which ctest sets.
"""
from __future__ import annotations

from copy import deepcopy
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
DT = 1 / 120


def cart_room() -> dict:
    return world_room.SCENES["tests-cart"]()


class TheRoomDeclaresIt(unittest.TestCase):
    """What the room says of the cart's machine, as validate() keeps it."""

    def test_the_battery_is_in_the_chassis_and_the_motor_on_the_back_wheels(self):
        room = fracture_lab.validate(cart_room())
        machines = room["machines"]
        [store], [motor], [control] = machines["stores"], machines["motors"], machines["controls"]
        self.assertEqual("cart", store["body"])                       # an exact body
        self.assertEqual(["cart", "cart-1"], motor["on"])
        self.assertEqual(motor["on"], control["on"])
        # The back wheels are the ones by the handle: their pin is behind the
        # middle of the cart, which faces the lake's middle (+z).
        pins = {j["b"]: j for j in room["joints"] if j["a"] == "cart"}
        self.assertLess(pins["cart-1"]["at_mm"][2], pins["cart-2"]["at_mm"][2])
        [sensor] = control["sensors"]
        self.assertEqual({"kind": "water", "body": "cart", "depth_mm": 10.0, "stops": 1},
                         {k: v for k, v in sensor.items() if k != "at_mm"})
        # In front of the cart: further towards the lake than its front pin.
        self.assertGreater(sensor["at_mm"][2], pins["cart-2"]["at_mm"][2] + 500.0)

    def test_a_sensor_the_engine_could_not_fit_is_refused_here(self):
        def refused(change, message):
            room = cart_room()
            sensor = room["machines"]["controls"][0]["sensors"][0]
            change(room, sensor)
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                fracture_lab.validate(room)

        refused(lambda r, s: s.update(kind="smoke"), "only kind there is yet is water")
        refused(lambda r, s: s.update(body="nothing here"), "not in this room")
        refused(lambda r, s: s.update(stops=0), "1 or -1")
        refused(lambda r, s: s.update(stops=True), "1 or -1")
        refused(lambda r, s: s.update(depth_mm=0.0), "depth_mm")
        refused(lambda r, s: s.update(depth_mm=20000.0), "depth_mm")
        refused(lambda r, s: s.update(at_mm=[0.0, 0.0]), "at_mm")
        refused(lambda r, s: s.update(range_mm=5.0), "cannot say")
        refused(lambda r, s: r["machines"]["controls"][0].update(sensors=[deepcopy(s)] * 9), "at most 8")

    def test_a_sensor_on_a_thing_made_of_cells_is_declared_the_same_way(self):
        room = cart_room()
        room["machines"]["controls"][0]["sensors"][0]["body"] = "post"
        self.assertEqual("post", fracture_lab.validate(room)["machines"]["controls"][0]["sensors"][0]["body"])

    def test_a_controller_without_sensors_says_nothing_of_them(self):
        room = cart_room()
        room["machines"]["controls"][0].pop("sensors")
        self.assertNotIn("sensors", fracture_lab.validate(room)["machines"]["controls"][0])


class CarryingIt(unittest.TestCase):
    """A running world carried into a changed room (carry_plan): a controller
    made the same way is kept with its sensors; one made anew puts its sensors
    on where the room has them, so the things they are on come back as the room
    has them, as a new pin's do."""

    def room(self):
        """The room as a world was given it: its pins with the ids _hang gives."""
        room = fracture_lab.validate(cart_room())
        for i, pin in enumerate(room["joints"]):
            pin["id"] = i + 1
        return room

    def was(self, room):
        made = {"stores": {"cart battery": 1}, "motors": {("cart", "cart-1"): 1}, "controls": {"cart": 1}}
        return live_session._declared(room, None, made)

    def test_a_controller_made_the_same_way_is_kept(self):
        room = self.room()
        plan = live_session.carry_plan(self.was(room), deepcopy(room))
        self.assertEqual([1], plan["engine"]["controls"])
        self.assertEqual([], plan["engine"]["declared_anew"])

    def test_a_sensor_moved_makes_it_anew_and_names_what_it_is_on(self):
        room = self.room()
        changed = deepcopy(room)
        changed["machines"]["controls"][0]["sensors"][0]["at_mm"][2] += 100.0
        plan = live_session.carry_plan(self.was(room), changed)
        self.assertEqual([], plan["engine"]["controls"])
        self.assertEqual(["cart"], plan["engine"]["declared_anew"])


@unittest.skipUnless(ENGINE and ENGINE.is_file(), "BANJO_LIVE_ENGINE is required")
class DrivingIt(unittest.TestCase):
    """The tests-cart room opened as the playground opens it (Live.open), the
    cart sent forward as its panel sends it, and the world saved and opened
    again as a restart does."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.live = live_session.Live()
        self.addCleanup(self.live.shutdown)
        self.room = world_room.Room("tests-cart")
        self.app = SimpleNamespace(live=self.live, live_holder="world", room=self.room, engine_path=ENGINE,
                                   runs_path=root / "runs", store=room_store.RoomStore(root / "rooms"))
        self.opened = self.live.open(self.app, {"spec": self.room.spec})

    def controller(self, reply):
        return next(c for c in reply["machines"]["controls"] if c["name"] == "cart")

    def step(self, n):
        return self.live.session.send(op="step", dt=DT, n=n)

    def pose(self, name):
        return next(b for b in self.live.session.send(op="poses")["bodies"] if b["name"] == name)

    def forward(self, seq, direction=1):
        return self.live.session.send(op="operate", control=self.controller(self.step(1))["id"], sender="test",
                                      seq=seq, power=True, direction=direction, setting=1.0)

    def drive_to_the_edge(self):
        self.step(240)                                   # settled on its brake
        self.forward(1)
        for tick in range(150):
            said = self.controller(self.step(12))
            if "water ahead" in said["condition"]:
                return (tick + 1) * 12 * DT, said
        self.fail(f"the cart never stopped for the water: {said['condition']!r}")

    def test_it_opens_as_one_machine_with_its_sensor_reading_dry(self):
        self.assertNotIn("machine_problems", self.opened)
        said = self.controller(self.step(1))
        # All of the cart is the machine: E on its front wheels finds it too.
        self.assertEqual({"cart", "cart-1", "cart-2"}, set(said["parts"]))
        [sensor] = said["sensors"]
        self.assertEqual(("water", "cart", 1, 0.01), (sensor["kind"], sensor["body"], sensor["stops"],
                                                      sensor["depth_m"]))
        self.assertFalse(sensor["sees"])
        self.assertEqual(0.0, sensor["reading_m"])
        declared = self.room.spec["machines"]["controls"][0]["sensors"][0]["at_mm"]
        for k in range(3):
            self.assertAlmostEqual(declared[k] / 1000.0, sensor["at_m"][k], delta=0.05)

    def test_driven_forward_it_stops_at_the_waters_edge_and_backs_away(self):
        start = self.pose("cart")["position_m"]
        stopped, said = self.drive_to_the_edge()
        self.assertTrue(said["sensors"][0]["sees"])
        self.assertGreater(said["sensors"][0]["reading_m"], 0.01)
        self.step(240)
        rest = self.pose("cart")
        wheels = self.pose("cart-2")["position_m"]
        wet = self.live.session.send(op="survey", at=[wheels[0], wheels[2]])["survey"].get("water")
        print(f"\n    stopped for {said['sensors'][0]['reading_m'] * 1000:.0f} mm of water after {stopped:.2f} s, "
              f"{rest['position_m'][2] - start[2]:.2f} m down the shore")
        self.assertGreater(rest["position_m"][2] - start[2], 3.0)
        self.assertIsNone(wet, "its front wheels stopped in the water")
        self.assertLess(abs(rest["velocity_m_s"][2]), 0.02)
        said = self.controller(self.step(1))
        self.assertTrue(said["brake"])
        self.assertEqual(0.0, said["command"])
        # Told forward again it will not go; told back, it goes.
        self.forward(2)
        self.step(120)
        self.assertLess(self.pose("cart")["position_m"][2] - rest["position_m"][2], 0.02)
        self.forward(3, direction=-1)
        self.step(240)
        self.assertGreater(rest["position_m"][2] - self.pose("cart")["position_m"][2], 0.5)

    def test_saved_and_opened_again_it_still_sees_the_water(self):
        self.drive_to_the_edge()
        self.step(120)
        saved, why = self.live.snapshot()
        self.assertIsNotNone(saved, why)
        self.live.shutdown()
        opened = self.live.open(self.app, {"spec": self.room.spec, "snapshot": saved})
        self.assertEqual("whole", opened["restored"]["tier"], opened["restored"].get("why"))
        said = self.controller(self.step(1))
        self.assertEqual(1, len(said["sensors"]))
        self.assertTrue(said["sensors"][0]["sees"])
        self.assertIn("water ahead", said["condition"])


if __name__ == "__main__":
    if os.environ.get("BANJO_CART_LIVE_TESTS") == "required" and not (ENGINE and ENGINE.is_file()):
        raise RuntimeError("BANJO_LIVE_ENGINE must be built for the required live cart tests")
    unittest.main()
