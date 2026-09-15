"""A room with a machine in it, through the playground's live session and the
engine's own runner (docs/machine-world.md).

The engine's motors, batteries and drums are checked in tests/motor_tests.cpp.
This checks everything between a room and them:
- a room with a drum among its joints, and a battery and a motor under
  "machines", opens with nothing refused;
- every step reports the machines;
- the motor starts with its brake on, and the rope carries the crate;
- told to drive, the motor winds the crate up by the drum's radius times its
  turn, and the battery gives what the motor drew;
- stopped, it holds, and draws nothing more;
- the playground's action step finds the motor by the thing it turns;
- saved as the server saves it and opened again, as a restarted server opens
  it, it comes back braked with its battery as it was -- the world's own, not
  added again from the room's spec -- and the room's action winds it on.

    BANJO_LIVE_ENGINE=<build>/Release/banjo_live_world_run.exe python tests/machine_room_tests.py -v
"""
from __future__ import annotations

import math
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "playground"))

import live_session  # noqa: E402

ENGINE = next((p for p in [
    *([Path(os.environ["BANJO_LIVE_ENGINE"])] if os.environ.get("BANJO_LIVE_ENGINE") else []),
    ROOT / "build/integration/Release/banjo_live_world_run.exe",
    ROOT / "build/integration/banjo_live_world_run",
] if p.is_file()), None)

RADIUS_M = 0.1


def hoist_room() -> dict:
    """An iron post; an oak drum on an axle along z at 2 m; an iron crate
    hanging 1.5 m below the drum's right-hand side on 2 m of rope; a 5 kJ
    battery on the post; and a motor on the drum's pin with a brake."""
    return {
        "algorithm": "lattice",
        "cell_m": 0.05,
        "plasticity": "on",
        "bodies": [
            {"name": "post", "shape": "box", "material": "iron", "size_mm": [100, 2000, 100],
             "center_mm": [-400, 1000, 0], "anchored": True},
            {"name": "drum", "shape": "box", "material": "oak", "size_mm": [200, 200, 300],
             "center_mm": [0, 2000, 0]},
            {"name": "crate", "shape": "box", "material": "iron", "size_mm": [150, 150, 150],
             "center_mm": [100, 425, 0]},
        ],
        "joints": [
            {"kind": "hinge", "a": "post", "b": "drum", "at_mm": [0, 2000, 0], "axis": [0, 0, 1]},
            {"kind": "drum", "a": "drum", "b": "crate", "at_mm": [0, 2000, 0], "axis": [0, 0, 1],
             "radius_mm": RADIUS_M * 1000.0, "to_mm": [100, 500, 0], "winds": 1, "length_mm": 2000},
        ],
        "machines": {
            "stores": [{"name": "battery", "body": "post", "capacity_j": 5000}],
            # 95.5 turns a minute unloaded is 10 rad/s.
            "motors": [{"on": ["post", "drum"], "store": "battery", "stall_torque_n_m": 60,
                        "no_load_rpm": 95.5, "brake_torque_n_m": 200}],
        },
    }


@unittest.skipIf(ENGINE is None, "the live world runner is not built")
class AHoistInARoom(unittest.TestCase):

    def setUp(self):
        self.live = live_session.Live()
        self.addCleanup(self.live.shutdown)

        class App:
            engine_path = ENGINE
            runs_path = ROOT / "build/playground-runs"
            live_inprocess = False

        self.opened = self.live.open(App(), {"spec": hoist_room()})
        self.session = self.live.session

    def step(self, seconds: float) -> None:
        for _ in range(max(1, round(seconds / (8 / 240.0)))):
            self.session.send(op="step", dt=1 / 240.0, n=8)

    def machines(self) -> dict:
        return self.session.state.get("machines") or {}

    def crate(self) -> dict:
        return next(b for b in self.session.state["bodies"] if b["name"] == "crate")

    def rope(self) -> dict:
        return self.machines()["ropes"][0]

    def test_it_opens_with_its_machines_and_the_brake_on(self):
        self.assertFalse(self.opened.get("joint_problems"), self.opened.get("joint_problems"))
        self.assertFalse(self.opened.get("machine_problems"), self.opened.get("machine_problems"))
        self.step(0.5)
        machines = self.machines()
        self.assertEqual([s["name"] for s in machines["stores"]], ["battery"])
        motor = machines["motors"][0]
        self.assertEqual(motor["on"], ["post", "drum"])
        self.assertEqual(motor["state"], "braking")
        self.assertAlmostEqual(motor["no_load_rad_s"], 95.5 * math.pi / 30.0, places=3)
        self.assertEqual(machines["stores"][0]["given_j"], 0.0)
        # The rope carries the crate: its weight, to a hundredth.
        weight = self.crate()["mass_kg"] * 9.81
        self.assertAlmostEqual(self.rope()["tension_n"], weight, delta=0.01 * weight)

    def test_driven_it_winds_the_crate_up_and_stopped_it_holds(self):
        self.step(0.5)
        motor = self.machines()["motors"][0]
        y0, out0, turned0 = self.crate()["position_m"][1], self.rope()["out_m"], motor["turned_rad"]
        self.session.send(op="drive", motor=motor["id"], command=1.0)
        self.step(1.0)
        lifted = self.machines()["motors"][0]
        turned = lifted["turned_rad"] - turned0
        taken = out0 - self.rope()["out_m"]
        rise = self.crate()["position_m"][1] - y0
        print(f"\n   driven for a second: the drum turned {turned / (2 * math.pi):.2f} times, took on"
              f" {taken:.4f} m of rope (r x turn {RADIUS_M * turned:.4f} m), the crate rose {rise:.4f} m;"
              f" the battery gave {self.machines()['stores'][0]['given_j']:.1f} J", flush=True)
        self.assertEqual(lifted["state"], "driving")
        self.assertGreater(turned, math.pi)
        # The rope's and the turn's readings are rounded on the wire: a
        # millimetre.
        self.assertAlmostEqual(taken, RADIUS_M * turned, delta=0.001)
        self.assertAlmostEqual(rise, taken, delta=0.01 * taken)
        store = self.machines()["stores"][0]
        self.assertGreater(store["given_j"], 0.0)
        self.assertAlmostEqual(store["given_j"], lifted["drawn_j"], delta=0.01)
        # Stopped with the brake: it holds, and draws nothing more.
        self.session.send(op="drive", motor=motor["id"], command=0.0, brake=True)
        self.step(0.5)
        y1, drawn1 = self.crate()["position_m"][1], self.machines()["motors"][0]["drawn_j"]
        self.step(1.0)
        self.assertAlmostEqual(self.crate()["position_m"][1], y1, delta=0.002)
        self.assertEqual(self.machines()["motors"][0]["drawn_j"], drawn1)
        self.assertEqual(self.machines()["motors"][0]["state"], "braking")

    def test_the_rooms_own_action_winds_it_up_and_stops_it(self):
        """Through the server's own run_action, as the page's E runs it: the
        drive step goes through the live session's act, which has to know it."""
        import server  # noqa: E402 -- the playground server's own action runner
        self.step(0.5)
        spec = hoist_room()
        spec["actions"] = [{"body": "drum", "label": "Wind it up", "steps": [{"do": "drive", "command": 1.0}]},
                           {"body": "drum", "label": "Stop", "steps": [{"do": "drive", "command": 0.0}]}]
        live = self.live

        class Room:
            pass

        class App:
            pass

        room, app = Room(), App()
        room.spec = spec
        app.live, app.room = live, room
        answer = server.run_action(app, {"object": "drum", "action": 0})
        self.assertFalse(answer.get("refused"), answer)
        self.step(0.5)
        self.assertEqual(self.machines()["motors"][0]["state"], "driving")
        self.assertGreater(self.machines()["stores"][0]["given_j"], 0.0)
        answer = server.run_action(app, {"object": "drum", "action": 1})
        self.assertFalse(answer.get("refused"), answer)
        self.step(0.2)
        self.assertEqual(self.machines()["motors"][0]["state"], "braking")

    def test_an_action_finds_the_motor_by_what_it_turns(self):
        import server  # noqa: E402 -- the playground server's own lookup
        self.step(0.2)
        live = self.live

        class App:
            pass

        app = App()
        app.live = live
        self.assertEqual(server._motor_for(app, "drum")["on"], ["post", "drum"])
        with self.assertRaises(ValueError):
            server._motor_for(app, "crate")


@unittest.skipIf(ENGINE is None, "the live world runner is not built")
class AHoistRoomComesBackAfterARestart(unittest.TestCase):
    """The room saved as the server saves it (Live.snapshot), and opened again
    from what was saved, as a restarted server opens it."""

    def test_it_comes_back_braked_with_its_battery_and_the_rooms_action_winds_it_on(self):
        import server  # noqa: E402 -- the playground server's own action runner

        class App:
            engine_path = ENGINE
            runs_path = ROOT / "build/playground-runs"
            live_inprocess = False

        def step(session, seconds: float) -> None:
            for _ in range(max(1, round(seconds / (8 / 240.0)))):
                session.send(op="step", dt=1 / 240.0, n=8)

        def crate_of(state: dict) -> list:
            return next(b for b in state["bodies"] if b["name"] == "crate")["position_m"]

        first = live_session.Live()
        self.addCleanup(first.shutdown)
        first.open(App(), {"spec": hoist_room()})
        motor = first.session.state["machines"]["motors"][0]
        first.session.send(op="drive", motor=motor["id"], command=1.0)
        step(first.session, 0.5)
        first.session.send(op="drive", motor=motor["id"], command=0.0, brake=True)
        step(first.session, 0.5)
        was = first.session.state["machines"]
        crate_was = crate_of(first.session.state)
        saved, why = first.snapshot()
        self.assertIsNotNone(saved, why)

        again = live_session.Live()
        self.addCleanup(again.shutdown)
        opened = again.open(App(), {"spec": hoist_room(), "snapshot": saved})
        self.assertEqual(opened["restored"]["tier"], "whole", opened["restored"].get("why"))
        machines = opened.get("machines") or {}
        # One battery and one motor: the world's own, not added again from the
        # room's spec on top of them.
        self.assertEqual(len(machines.get("stores") or []), 1, machines)
        self.assertEqual(len(machines.get("motors") or []), 1, machines)
        store, kept = machines["stores"][0], machines["motors"][0]
        print(f"\n   opened again: the battery has given {store['given_j']:.1f} J ({was['stores'][0]['given_j']:.1f}"
              f" when saved), the motor is {kept['state']} ({was['motors'][0]['state']}), and"
              f" {machines['ropes'][0]['out_m']:.4f} m of rope is out ({was['ropes'][0]['out_m']:.4f})", flush=True)
        self.assertEqual((store["charge_j"], store["given_j"]),
                         (was["stores"][0]["charge_j"], was["stores"][0]["given_j"]))
        self.assertEqual((kept["state"], kept["drawn_j"], kept["turned_rad"]),
                         ("braking", was["motors"][0]["drawn_j"], was["motors"][0]["turned_rad"]))
        self.assertEqual(machines["ropes"][0]["out_m"], was["ropes"][0]["out_m"])
        self.assertEqual(crate_of(opened), crate_was)

        # The room's own action, as the page's E runs it, finds the motor in
        # the world that came back and winds the crate on up.
        class Room:
            pass

        class Server:
            pass

        room, app = Room(), Server()
        room.spec = dict(hoist_room(), actions=[
            {"body": "drum", "label": "Wind it up", "steps": [{"do": "drive", "command": 1.0}]}])
        app.live, app.room = again, room
        answer = server.run_action(app, {"object": "drum", "action": 0})
        self.assertFalse(answer.get("refused"), answer)
        step(again.session, 0.5)
        after = again.session.state["machines"]
        rise = crate_of(again.session.state)[1] - crate_was[1]
        print(f"   wound on for half a second: the crate rose {rise:.4f} m; the motor has drawn"
              f" {after['motors'][0]['drawn_j']:.1f} J in all and the battery has given"
              f" {after['stores'][0]['given_j']:.1f} J", flush=True)
        self.assertEqual(after["motors"][0]["state"], "driving")
        self.assertGreater(rise, 0.05, "opened again, the room's action did not wind the crate up")
        self.assertAlmostEqual(after["stores"][0]["given_j"], after["motors"][0]["drawn_j"], delta=0.01)


class TheTestRoomIsAHoist(unittest.TestCase):
    """The tests-machines room (playground/rooms/tests-machines.json), which
    the page opens by link: a hoist that the room's own checks take as it is."""

    def test_it_is_checked_with_its_machines_and_its_actions(self):
        import fracture_lab  # noqa: E402
        import world_room  # noqa: E402
        spec = fracture_lab.validate(world_room.SCENES["tests-machines"]())
        self.assertEqual([m["on"] for m in spec["machines"]["motors"]], [["hoist: post", "hoist: drum"]])
        self.assertTrue(spec["machines"]["motors"][0]["brake"], "the hoist's motor does not start braked")
        self.assertIn("drum", [j["kind"] for j in spec["joints"]])
        self.assertEqual([a["label"] for a in spec["actions"]], ["Wind it up", "Stop", "Let it down"])
        self.assertEqual([s["do"] for a in spec["actions"] for s in a["steps"]], ["drive"] * 3)


if __name__ == "__main__":
    unittest.main()
