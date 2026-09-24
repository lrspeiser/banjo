"""The Workshop's test room: a little world with the world's own physics.

    BANJO_LIVE_ENGINE=.../banjo_live_world_run.exe python -m pytest tests/workshop_test_room_tests.py

Without BANJO_LIVE_ENGINE nothing here runs: every one of these needs the real
engine, because the whole point of the room is that it is the real one.
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
sys.path[:0] = [str(ROOT), str(ROOT / "playground"), str(ROOT / "tests")]

import inventory, live_session, room_store, workshop_library, world_room   # noqa: E402
import workshop_install as install                                         # noqa: E402
import workshop_test_room as bench                                         # noqa: E402
from mcp import workshop_machines                                          # noqa: E402
import workshop_fitting_tests   # noqa: E402  (the robot it builds; not bound here, or it is collected twice)

ENGINE = Path(os.environ["BANJO_LIVE_ENGINE"]).resolve() if os.environ.get("BANJO_LIVE_ENGINE") else None

MACHINES = {
    "stores": [{"name": "battery", "in": "deck", "capacity_j": 100000.0,
                "charge_j": 50000.0, "voltage_v": 24.0}],
    "motors": [{"name": "left motor", "turns": ["left mount", "left wheel"], "store": "battery",
                "stall_torque_n_m": 20.0, "no_load_rpm": 60.0, "brake_torque_n_m": 40.0},
               {"name": "right motor", "turns": ["right mount", "right wheel"], "store": "battery",
                "stall_torque_n_m": 20.0, "no_load_rpm": 60.0, "brake_torque_n_m": 40.0}],
    "controls": [{"name": "left wheel", "turns": ["left mount", "left wheel"]},
                 {"name": "right wheel", "turns": ["right mount", "right wheel"]}],
    "panels": [{"name": "solar panel", "on": "deck", "store": "battery",
                "area_m2": 0.25, "efficiency": 0.2}],
}


@unittest.skipUnless(ENGINE and ENGINE.is_file(), "BANJO_LIVE_ENGINE is required")
class ALittleWorldAtTheBench(unittest.TestCase):
    """A machine with a battery and a solar panel, made at the bench and let run."""

    def setUp(self):
        self.app = SimpleNamespace(engine_path=ENGINE, workshop_owner_id="owner")
        self.robot = workshop_fitting_tests.ARobotBuiltThroughTheChatsTools("run")
        self.robot.setUp()
        self.addCleanup(self.robot.doCleanups)

    def candidate(self):
        """The robot the chat builds, finalized, with a battery and a panel on it."""
        state = self.robot.state
        answer = state.execute("check_validity", {})
        self.assertTrue(answer["ok"], answer.get("summary"))
        overrides = deepcopy(state.overrides)
        overrides[workshop_machines.MACHINES_KEY] = workshop_machines.checked(MACHINES)
        for part in state.design.parts:
            overrides[part.name] = dict(overrides.get(part.name) or {}, mechanics={"model": "rigid"})
        return {"kind": "custom", "design_id": "solar-robot", "purpose": "stand in the sun",
                "parameters": dict(state.design.parameters), "component_overrides": overrides}

    def opened(self, **how):
        room = bench.Bench(self.app, **how)
        self.addCleanup(room.close)
        for material in ("oak", "iron", "concrete", "glass"):
            workshop_library.set_rack(room.app, material, 500.0)
        return room

    def test_it_stands_on_the_ground_and_gravity_holds_it_there(self):
        room = self.opened()
        receipt = room.make(self.candidate())
        first = room.reading()
        after = room.run(5.0)
        deck = receipt["root_body"]
        self.assertEqual(0, receipt["cells"], "finalized: nothing of it is cells")
        self.assertEqual(6, len(receipt["root_bodies"]))
        # It is standing on ground that is 400 mm up, not at zero and not
        # falling: flat ground's surface is the depth of its soil.
        for reading in (first, after):
            self.assertGreater(reading["bodies"][deck]["at_m"][1], bench.GROUND_M)
            self.assertLess(reading["bodies"][deck]["at_m"][1], bench.GROUND_M + 1.0)
        moved = abs(after["bodies"][deck]["at_m"][1] - first["bodies"][deck]["at_m"][1])
        print(f"\n    it stands at {after['bodies'][deck]['at_m'][1]:.3f} m on ground {bench.GROUND_M} m up, "
              f"and in 5 s it moved {moved * 1000:.2f} mm")
        self.assertLess(moved, 0.01)
        self.assertLess(after["bodies"][deck]["speed_m_s"], 0.02)

    def test_the_sun_charges_its_battery_and_the_night_does_not(self):
        day = self.opened()
        day.make(self.candidate())
        began = (day.reading()["stores"] or [{}])[0]["charge_j"]
        noon = day.run(10.0)
        charged = (noon["stores"] or [{}])[0]
        panel = (noon["panels"] or [{}])[0]
        print(f"    at noon: the panel gives {panel['power_w']:.2f} W and the battery goes "
              f"{began:.0f} -> {charged['charge_j']:.0f} J in 10 s")
        self.assertGreater(panel["power_w"], 1.0)
        self.assertGreater(charged["charge_j"], began + 100.0)
        self.assertAlmostEqual(charged["charge_j"] - began, charged["taken_j"], delta=1.0)

        night = self.opened(day={"day_s": 240.0, "hour": 23.0})
        night.make(self.candidate())
        was = (night.reading()["stores"] or [{}])[0]["charge_j"]
        dark = night.run(10.0)
        after = (dark["stores"] or [{}])[0]
        print(f"    at eleven at night the sun is {dark['sun']['elevation_deg']:.0f} degrees up and the "
              f"battery holds {after['charge_j']:.0f} J")
        self.assertLess(dark["sun"]["elevation_deg"], 0.0)
        self.assertEqual(0.0, (dark["panels"] or [{}])[0]["power_w"])
        self.assertEqual(0.0, after["taken_j"])
        self.assertAlmostEqual(was, after["charge_j"], delta=1e-6)

    def test_other_things_can_stand_in_the_room_with_it(self):
        room = self.opened(items=[{"what": "stool", "at_m": [1.2, 1.6]},
                                  {"what": "post", "at_m": [-2.0, 0.0]}])
        room.make(self.candidate())
        now = room.run(2.0)
        self.assertIn("stool", now["bodies"])
        self.assertIn("post", now["bodies"])
        # The stool stands on the ground of its own accord, and the post is
        # driven into it and does not move.
        self.assertGreater(now["bodies"]["stool"]["at_m"][1], bench.GROUND_M)
        self.assertEqual(0.0, now["bodies"]["post"]["speed_m_s"])
        self.assertTrue(any(t["what"] == "stool" for t in bench.things()))

    def test_it_does_the_same_thing_in_a_world_room(self):
        """The one that matters: the bench answers for the world.

        The same design, made the same way, in a room built by hand rather than
        by the bench -- the same install call, the same engine, the same sun.
        The battery has to take in the same joules, or the bench is telling a
        story about a world that does not exist.
        """
        room = self.opened()
        room.make(self.candidate())
        at_the_bench = (room.run(10.0)["stores"] or [{}])[0]["taken_j"]

        held = tempfile.TemporaryDirectory()
        self.addCleanup(held.cleanup)
        root = Path(held.name)
        live = live_session.Live()
        self.addCleanup(live.shutdown)
        out_there = world_room.Room("yard")
        out_there.spec = bench.spec()          # the same ground and the same sky
        out_there.inventory = inventory.Inventory()
        app = SimpleNamespace(live=live, live_holder="world", room=out_there, engine_path=ENGINE,
                              runs_path=root / "runs", store=room_store.RoomStore(root / "rooms"))
        for material in ("oak", "iron", "concrete", "glass"):
            workshop_library.set_rack(app, material, 500.0)
        live.open(app, {"spec": out_there.spec})
        ctx = install.context(app, {})
        preview = install.preview(app, {"session": ctx["session"], "scene": "yard", "mode": "authoring",
                                        "position_m": [0.0, 0.0], "candidate": self.candidate()})
        install.commit(app, {"scene": "yard", "session": ctx["session"],
                             "preview_id": preview["preview_id"], "request_id": "out-there"})
        live.session.send(op="step", dt=bench.DT, n=1)
        for _ in range(int(10.0 / (60 * bench.DT))):
            reply = live.session.send(op="step", dt=bench.DT, n=60)
        in_the_world = ((reply.get("machines") or {}).get("stores") or [{}])[0]["taken_j"]

        print(f"    the bench took in {at_the_bench:.1f} J and the world took in {in_the_world:.1f} J")
        self.assertGreater(at_the_bench, 100.0)
        self.assertAlmostEqual(at_the_bench, in_the_world, delta=max(1.0, 0.01 * at_the_bench))


    def test_one_call_makes_it_runs_it_and_says_what_happened(self):
        """try_it: what the chat's tool and the plan route both go through."""
        said = bench.try_it(self.app, self.candidate(), seconds=6.0,
                            items=[{"what": "stool", "at_m": [1.2, 1.6]}])
        print("\n    " + said["says"])
        self.assertEqual(0, said["made"]["cells"])
        self.assertEqual(6.0, said["ran_for_s"])
        self.assertIn("stool", said["in_the_room"])
        self.assertGreater(said["ended"]["panels"][0]["power_w"], 1.0)
        self.assertIn("W", said["says"])
        # And the world is untouched: the room was its own, and it is gone.
        self.assertGreater(said["ended"]["stores"][0]["charge_j"],
                           said["began"]["stores"][0]["charge_j"])

if __name__ == "__main__":
    unittest.main()
