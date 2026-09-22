"""The rover that roams (docs/machine-world.md, "One autonomous creature"): the
room's declaration of a machine's program, checked and carried, and the
tests-rover room opened, set roaming and saved in the real engine.

    BANJO_LIVE_ENGINE=.../banjo_live_world_run.exe python tests/rover_room_tests.py

Without BANJO_LIVE_ENGINE only the checks that need no engine run, unless
BANJO_ROVER_LIVE_TESTS=required, which ctest sets.
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
DT = 1 / 120
ROVER = ("rover", "rover: left wheel", "rover: right wheel", "rover: caster", "rover: caster wheel")


def rover_room() -> dict:
    return world_room.SCENES["tests-rover"]()


class TheRoomDeclaresIt(unittest.TestCase):
    """What the room says of the rover's program, as validate() keeps it."""

    def test_the_program_works_the_two_wheels_controllers_on_the_deck(self):
        machines = fracture_lab.validate(rover_room())["machines"]
        [program] = machines["programs"]
        self.assertEqual({"name": "rover", "kind": "roam", "left": "left wheel", "right": "right wheel",
                          "body": "rover", "setting": 1.0, "climb_deg": 8.0, "power": False},
                         {k: v for k, v in program.items() if k != "sensors"})
        controls = {c["name"]: c for c in machines["controls"]}
        self.assertEqual(["rover", "rover: left wheel"], controls["left wheel"]["on"])
        self.assertEqual(["rover", "rover: right wheel"], controls["right wheel"]["on"])
        self.assertEqual(2, len(machines["motors"]))
        # Its sensors stop nothing themselves -- the program reads them -- and
        # sit ahead of it, one either side and wider than its wheels (at
        # +-0.41 m).
        left, right = program["sensors"]
        self.assertNotIn("stops", left)
        self.assertEqual((3.0, 3.0), (left["depth_mm"], right["depth_mm"]))
        self.assertGreater(left["at_mm"][0] - right["at_mm"][0], 1000.0)

    def test_a_program_the_engine_could_not_run_is_refused_here(self):
        def refused(change, message):
            room = rover_room()
            change(room["machines"], room["machines"]["programs"][0])
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                fracture_lab.validate(room)

        refused(lambda m, p: p.update(kind="hunt"), "only kind there is yet is 'roam'")
        refused(lambda m, p: p.update(left="front wheel"), "there is none")
        refused(lambda m, p: p.update(right="left wheel"), "are one")
        refused(lambda m, p: p.update(body="post"), "does not turn a wheel on 'post'")
        refused(lambda m, p: p.update(setting=0.0), "setting")
        refused(lambda m, p: p.update(climb_deg=75.0), "climb_deg")
        refused(lambda m, p: p.update(speed=2.0), "cannot say")
        refused(lambda m, p: p["sensors"][0].update(stops=1), "cannot say")
        refused(lambda m, p: m["programs"].append(dict(deepcopy(p), name="twin")), "worked by another program")
        refused(lambda m, p: m["programs"].append(dict(deepcopy(p))), "a name of its own")

    def test_a_room_without_programs_says_nothing_of_them(self):
        room = rover_room()
        room["machines"].pop("programs")
        self.assertNotIn("programs", fracture_lab.validate(room)["machines"])


class CarryingIt(unittest.TestCase):
    """A running world carried into a changed room (carry_plan): a program made
    the same way is kept, as it was told to run; told otherwise now, it is told
    so; made anew, it puts its sensors on where the room has them."""

    def room(self):
        room = fracture_lab.validate(rover_room())
        for i, pin in enumerate(room["joints"]):
            pin["id"] = i + 1
        return room

    def was(self, room, running=False):
        made = {"stores": {"rover battery": 1},
                "motors": {("rover", "rover: left wheel"): 1, ("rover", "rover: right wheel"): 2},
                "controls": {"left wheel": 1, "right wheel": 2}, "programs": {"rover": 1}}
        declared = live_session._declared(room, None, made)
        if running:
            declared["programs"] = [(made_as, True, ident) for made_as, _, ident in declared["programs"]]
        return declared

    def test_a_program_made_the_same_way_is_kept(self):
        room = self.room()
        plan = live_session.carry_plan(self.was(room), deepcopy(room))
        self.assertEqual([1], plan["engine"]["programs"])
        self.assertEqual({}, plan["told_programs"])
        self.assertEqual([], plan["engine"]["declared_anew"])

    def test_a_program_the_room_now_says_should_run_is_told_so(self):
        room = self.room()
        running = deepcopy(room)
        running["machines"]["programs"][0]["power"] = True
        plan = live_session.carry_plan(self.was(room), running)
        self.assertEqual([1], plan["engine"]["programs"])
        self.assertEqual({0: True}, plan["told_programs"])
        # And one running that the room has not changed is not told again.
        plan = live_session.carry_plan(self.was(room, running=True), running)
        self.assertEqual({}, plan["told_programs"])

    def test_a_sensor_moved_makes_it_anew(self):
        room = self.room()
        moved = deepcopy(room)
        moved["machines"]["programs"][0]["sensors"][0]["at_mm"][0] += 50.0
        plan = live_session.carry_plan(self.was(room), moved)
        self.assertEqual([], plan["engine"]["programs"])
        self.assertEqual(["rover"], plan["engine"]["declared_anew"])


@unittest.skipUnless(ENGINE and ENGINE.is_file(), "BANJO_LIVE_ENGINE is required")
class RoamingIt(unittest.TestCase):
    """The tests-rover room opened as the playground opens it (Live.open), its
    program turned on as its panel turns it on, and the world saved and opened
    again as a restart does."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.live = live_session.Live()
        self.addCleanup(self.live.shutdown)
        self.room = world_room.Room("tests-rover")
        self.app = SimpleNamespace(live=self.live, live_holder="world", room=self.room, engine_path=ENGINE,
                                   runs_path=root / "runs", store=room_store.RoomStore(root / "rooms"))
        self.opened = self.live.open(self.app, {"spec": self.room.spec})

    def program(self, reply=None):
        reply = reply or self.live.session.send(op="step", dt=DT, n=1)
        return next(p for p in reply["machines"]["programs"] if p["name"] == "rover")

    def run_it(self, power, seq):
        said = self.live.session.send(op="run", program=self.program()["id"], sender="test", seq=seq, power=power)
        self.assertEqual("applied", said["ran"])
        return said["program"]

    def pose(self, name):
        return next(b for b in self.live.session.send(op="poses")["bodies"] if b["name"] == name)

    def wettest(self):
        most = 0.0
        for name in ("rover: left wheel", "rover: right wheel", "rover: caster wheel"):
            at = self.pose(name)["position_m"]
            water = self.live.session.send(op="survey", at=[at[0], at[2]])["survey"].get("water")
            most = max(most, (water or {}).get("depth_m", 0.0))
        return most

    def roam(self, seconds):
        """Step it `seconds` of world, a quarter second at a time: how far its
        deck went and the most water under a wheel."""
        path, wet, was = 0.0, 0.0, self.pose("rover")["position_m"]
        for _ in range(int(seconds * 4)):
            self.live.session.send(op="step", dt=DT, n=30)
            at = self.pose("rover")["position_m"]
            path += math.dist(at, was)
            was = at
            wet = max(wet, self.wettest())
        return path, wet

    def test_it_opens_off_as_one_machine(self):
        self.assertNotIn("machine_problems", self.opened)
        program = self.program()
        self.assertEqual(("stopped", False), (program["doing"], program["power"]))
        # All of the rover is the machine: E on any of it, the caster's wheel on
        # its fork too, finds the program.
        self.assertEqual(set(ROVER), set(program["parts"]))
        self.assertEqual([1, -1], [s["side"] for s in program["sensors"]])
        self.assertFalse(any(s["sees"] for s in program["sensors"]))

    def test_turned_on_it_roams_the_shore_dry_and_turned_off_it_stops(self):
        self.live.session.send(op="step", dt=DT, n=240)       # settled
        self.assertEqual("going forward", self.run_it(True, 1)["doing"])
        path, wet = self.roam(30.0)
        program = self.program()
        print(f"\n    roamed for 30 s: {path:.1f} m, {program['turns']} turns away, at most {wet * 1000:.1f} mm "
              f"of water under a wheel; now {program['doing']}: {program['why']}")
        self.assertGreater(path, 8.0)
        self.assertGreaterEqual(program["turns"], 1)
        self.assertLessEqual(wet, 0.003)
        self.assertEqual("stopped", self.run_it(False, 2)["doing"])
        self.live.session.send(op="step", dt=DT, n=240)
        speed = math.sqrt(sum(v * v for v in self.pose("rover")["velocity_m_s"]))
        self.assertLess(speed, 0.02)
        stale = self.live.session.send(op="run", program=program["id"], sender="test", seq=2, power=True)
        self.assertEqual("stale", stale["ran"])

    def test_saved_and_opened_again_it_roams_on(self):
        self.live.session.send(op="step", dt=DT, n=240)
        self.run_it(True, 1)
        self.roam(12.0)
        before = self.program()
        saved, why = self.live.snapshot()
        self.assertIsNotNone(saved, why)
        self.live.shutdown()
        opened = self.live.open(self.app, {"spec": self.room.spec, "snapshot": saved})
        self.assertEqual("whole", opened["restored"]["tier"], opened["restored"].get("why"))
        after = self.program(opened) if "machines" in opened else self.program()
        self.assertTrue(after["power"])
        self.assertEqual((before["doing"], before["turns"]), (after["doing"], after["turns"]))
        path, wet = self.roam(12.0)
        self.assertGreater(path, 3.0)
        self.assertLessEqual(wet, 0.003)


if __name__ == "__main__":
    if os.environ.get("BANJO_ROVER_LIVE_TESTS") == "required" and not (ENGINE and ENGINE.is_file()):
        raise RuntimeError("BANJO_LIVE_ENGINE must be built for the required live rover tests")
    unittest.main()
