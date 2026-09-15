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
  added again from the room's spec -- and the room's action winds it on;
- changed through the server's own routes -- the room's chat adding a crate,
  with a scripted model in place of the paid one, or a thing's stand step --
  the room keeps everything the change did not touch: the hoist still wound up,
  its battery as it was, the ball where it was put.

    BANJO_LIVE_ENGINE=<build>/Release/banjo_live_world_run.exe python tests/machine_room_tests.py -v
"""
from __future__ import annotations

import json
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
# The C library, for the room held as an MCP world (room_world): what the
# room's chat builds with.
LIBRARY = next((p for p in [
    *([Path(os.environ["BANJO_LIBRARY"])] if os.environ.get("BANJO_LIBRARY") else []),
    ROOT / "build/integration/Release/banjo.dll",
    ROOT / "build/integration/libbanjo.so",
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
        # Braked as it opens, before any step: a page drawing the opening
        # shows the brake on, not the state of a step not yet taken.
        self.assertEqual(self.opened["machines"]["motors"][0]["state"], "braking")
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

    def test_the_chat_works_it_on_the_room_as_it_stands(self):
        """What the room's chat does to the room as it stands (server._chat_live,
        room_world.LIVE): its action pressed by label or by number, and its motor
        told, all on the running room -- the session is the same one afterwards,
        so nothing was opened again. The owner, 2026-09-15: "nothing should be
        resetting rooms"."""
        import server  # noqa: E402
        self.step(0.5)
        spec = hoist_room()
        spec["actions"] = [{"body": "drum", "label": "Wind it up", "steps": [{"do": "drive", "command": 1.0}]},
                           {"body": "drum", "label": "Stop", "steps": [{"do": "drive", "command": 0.0}]}]

        class Room:
            pass

        class App:
            pass

        room, app = Room(), App()
        room.spec = spec
        app.live, app.room = self.live, room
        session = self.live.session.id
        y0 = self.crate()["position_m"][1]
        said = server._chat_live(app, "use_action", {"name": "drum", "action": "wind it up"})
        self.assertNotIn("error", said, said)
        self.assertEqual(said["action"], "Wind it up")
        self.step(0.5)
        self.assertEqual(self.machines()["motors"][0]["state"], "driving")
        y1 = self.crate()["position_m"][1]
        print(f"\n   pressed by the chat, 'Wind it up' wound the crate up {y1 - y0:.4f} m in half a second",
              flush=True)
        self.assertGreater(y1 - y0, 0.05, "pressed by the chat, the hoist did not wind")
        said = server._chat_live(app, "use_action", {"name": "drum", "action": "2"})
        self.assertNotIn("error", said, said)
        self.step(0.2)
        self.assertEqual(self.machines()["motors"][0]["state"], "braking")
        said = server._chat_live(app, "drive", {"part": "drum", "command": 1.0, "brake": False})
        self.assertNotIn("error", said, said)
        self.step(0.2)
        self.assertEqual(self.machines()["motors"][0]["state"], "driving")
        refused = server._chat_live(app, "use_action", {"name": "drum", "action": "Fly"})
        self.assertIn("Wind it up, Stop", refused.get("error", ""))
        self.assertEqual(self.live.session.id, session, "working the hoist opened the room again")


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


CHAT_RADIUS_M = 0.08     # RECIPES["hoist"]'s drum, which the chat is also told to build


def a_bare_room() -> dict:
    """A room on the world's 0.04 m cells with nothing in it but a stone."""
    return {"algorithm": "lattice", "cell_m": 0.04, "plasticity": "on",
            "bodies": [{"name": "marker stone", "shape": "box", "material": "concrete",
                        "size_mm": [80, 80, 80], "center_mm": [2000, 40, 2000], "anchored": True}]}


class App:
    """What the live session and the room's own action runner ask of the server."""
    engine_path = ENGINE
    runs_path = ROOT / "build/playground-runs"
    live_inprocess = False


class Room:
    pass


@unittest.skipIf(ENGINE is None or LIBRARY is None, "the live world runner or the C library is not built")
class AHoistTheChatBuilds(unittest.TestCase):
    """A battery hoist built the way the room's chat builds one -- the MCP's own
    tools, one call at a time, through room_world -- handed to the room as the
    spec it keeps (export_spec), opened through the live session on the
    engine's runner, and worked by the actions it was given, as the page runs
    them (server.run_action)."""

    def build(self, then=None) -> tuple[dict, dict]:
        import room_world  # noqa: E402 -- the room as the chat's MCP world
        world_id = room_world.open_room(a_bare_room())
        said: dict = {}
        try:
            def call(tool: str, /, **args) -> dict:
                answer = room_world.call(world_id, tool, args)
                self.assertNotIn("error", answer, f"{tool}: {answer.get('error')}")
                said[tool] = answer
                return answer

            for part in ({"name": "post", "shape": "box", "material": "concrete", "size_m": [0.08, 2.4, 0.08],
                          "position_m": [0.0, 1.2, -0.2], "anchored": True},
                         {"name": "drum", "shape": "box", "material": "oak", "size_m": [0.16, 0.16, 0.24],
                          "position_m": [0.0, 2.0, 0.0]},
                         {"name": "crate", "shape": "box", "material": "iron", "size_m": [0.16, 0.16, 0.16],
                          "position_m": [0.08, 0.4, 0.0]},
                         {"name": "battery", "shape": "box", "material": "concrete",
                          "size_m": [0.24, 0.28, 0.16], "position_m": [-0.24, 0.14, -0.2], "anchored": True}):
                call("add_object", object=part)
            call("hinge", a="post", b="drum", at_m=[0.0, 2.0, 0.0], axis=[0, 0, 1])
            call("drum", a="drum", b="crate", at_m=[0.0, 2.0, 0.0], axis=[0, 0, 1], radius_m=CHAT_RADIUS_M,
                 at_b_m=[0.08, 0.48, 0.0], length_m=2.0)
            call("store", name="battery", body="battery", capacity_j=20000)
            call("motor", on=["post", "drum"], store="battery", stall_torque_n_m=60, no_load_rpm=95.5,
                 brake_torque_n_m=200)
            call("offer_actions", name="drum", actions=[
                {"label": "Wind it up", "steps": [{"do": "drive", "command": 1}]},
                {"label": "Stop", "steps": [{"do": "drive", "command": 0}]},
                {"label": "Let it down", "steps": [{"do": "drive", "command": -0.1}]}])
            if then is not None:
                then(call)
            spec = room_world.export_spec(room_world.entry_of(world_id))
        finally:
            room_world.close_room(world_id)
        return spec, said

    def open(self, spec: dict):
        live = live_session.Live()
        self.addCleanup(live.shutdown)
        App.runs_path.mkdir(parents=True, exist_ok=True)
        app, room = App(), Room()
        room.spec = spec
        app.live, app.room = live, room
        opened = live.open(app, {"spec": spec})
        self.assertFalse(opened.get("joint_problems"), opened.get("joint_problems"))
        self.assertFalse(opened.get("machine_problems"), opened.get("machine_problems"))
        return app, live.session

    @staticmethod
    def step(session, seconds: float) -> None:
        for _ in range(max(1, round(seconds / (8 / 240.0)))):
            session.send(op="step", dt=1 / 240.0, n=8)

    def test_what_the_tools_made_is_the_rooms_own_spelling(self):
        import fracture_lab  # noqa: E402
        spec, said = self.build()
        self.assertEqual(said["drum"]["winds"], 1, "a rope under the drum's +x rim is wound on by the +z turn")
        self.assertEqual([j for j in spec["joints"] if j["kind"] == "drum"],
                         [{"kind": "drum", "a": "drum", "b": "crate", "at_mm": [0.0, 2000.0, 0.0],
                           "axis": [0, 0, 1], "radius_mm": 80.0, "to_mm": [80.0, 480.0, 0.0], "winds": 1,
                           "length_mm": 2000.0, "out_mm": 0.0}])
        self.assertEqual(spec["machines"], {
            "stores": [{"name": "battery", "body": "battery", "capacity_j": 20000.0, "charge_j": 20000.0,
                        "voltage_v": 24.0, "max_power_w": 0.0}],
            "motors": [{"on": ["post", "drum"], "store": "battery", "stall_torque_n_m": 60.0,
                        "no_load_rpm": 95.5, "brake_torque_n_m": 200.0, "command": 0.0, "brake": True}]})
        self.assertEqual([a["steps"] for a in spec["actions"]],
                         [[{"do": "drive", "part": "drum", "command": 1.0}],
                          [{"do": "drive", "part": "drum", "command": 0.0, "brake": True}],
                          [{"do": "drive", "part": "drum", "command": -0.1}]])
        self.assertEqual(fracture_lab.validate(spec)["machines"], spec["machines"])

    def test_opened_it_winds_the_crate_up_by_the_drums_radius_times_its_turn(self):
        """Its own actions, pressed: the crate rises by the drum's radius times
        its turn to a hundredth, the battery gives what the motor drew, the brake
        holds it drawing nothing, and let down the battery gives nothing."""
        import server  # noqa: E402 -- the page's own action runner
        spec, _ = self.build()
        app, session = self.open(spec)

        def machines() -> dict:
            return session.state.get("machines") or {}

        def crate() -> dict:
            return next(b for b in session.state["bodies"] if b["name"] == "crate")

        def press(action: int) -> None:
            answer = server.run_action(app, {"object": "drum", "action": action})
            self.assertFalse(answer.get("refused"), answer)

        self.step(session, 0.5)
        held = machines()
        self.assertEqual(held["motors"][0]["state"], "braking")
        self.assertEqual(held["motors"][0]["drawn_j"], 0.0)
        weight = crate()["mass_kg"] * 9.81
        self.assertAlmostEqual(held["ropes"][0]["tension_n"], weight, delta=0.01 * weight)
        y0, out0, turned0 = crate()["position_m"][1], held["ropes"][0]["out_m"], held["motors"][0]["turned_rad"]
        press(0)                                  # Wind it up
        self.step(session, 1.0)
        wound = machines()
        turned = wound["motors"][0]["turned_rad"] - turned0
        taken = out0 - wound["ropes"][0]["out_m"]
        rise = crate()["position_m"][1] - y0
        print(f"\n   wound up for a second: the drum turned {turned / (2 * math.pi):.3f} times, took on "
              f"{taken:.4f} m of rope (r x turn {CHAT_RADIUS_M * turned:.4f} m), the crate rose {rise:.4f} m; "
              f"the battery gave {wound['stores'][0]['given_j']:.3f} J, the motor drew "
              f"{wound['motors'][0]['drawn_j']:.3f} J", flush=True)
        self.assertEqual(wound["motors"][0]["state"], "driving")
        self.assertGreater(turned, math.pi)
        self.assertAlmostEqual(taken, CHAT_RADIUS_M * turned, delta=0.001)
        self.assertAlmostEqual(rise, CHAT_RADIUS_M * turned, delta=0.01 * CHAT_RADIUS_M * turned)
        self.assertGreater(wound["stores"][0]["given_j"], 0.0)
        self.assertAlmostEqual(wound["stores"][0]["given_j"], wound["motors"][0]["drawn_j"], delta=0.01)
        press(1)                                  # Stop, the brake on
        self.step(session, 0.5)
        y1, drawn1 = crate()["position_m"][1], machines()["motors"][0]["drawn_j"]
        self.step(session, 1.0)
        self.assertAlmostEqual(crate()["position_m"][1], y1, delta=0.002)
        self.assertEqual(machines()["motors"][0]["drawn_j"], drawn1)
        self.assertEqual(machines()["motors"][0]["state"], "braking")
        press(2)                                  # Let it down
        self.step(session, 0.5)
        ya, given = crate()["position_m"][1], machines()["stores"][0]["given_j"]
        self.step(session, 0.5)
        self.assertGreater(ya - crate()["position_m"][1], 0.1, "let down, it did not come down")
        self.assertAlmostEqual(machines()["stores"][0]["given_j"], given, delta=0.01,
                               msg="letting it down drew on the battery")

    def test_a_motor_the_chat_left_running_runs_in_the_room(self):
        """drive is kept with the motor: the room opens with it doing what the
        chat last told it."""
        spec, said = self.build(then=lambda call: call("drive", part="drum", command=1))
        self.assertIn("rises", said["drive"]["does"])
        (motor,) = spec["machines"]["motors"]
        self.assertEqual((motor["command"], motor["brake"]), (1.0, False))
        _, session = self.open(spec)
        self.step(session, 0.5)
        self.assertEqual(session.state["machines"]["motors"][0]["state"], "driving")
        rose = next(b for b in session.state["bodies"] if b["name"] == "crate")["position_m"][1] - 0.4
        self.assertGreater(rose, 0.1, "opened with its motor told to wind, the crate did not rise")


@unittest.skipIf(LIBRARY is None, "the C library is not built")
class TheTestRoomComesBackFromTheTools(unittest.TestCase):
    """The tests-machines room held as the chat's MCP world, and handed back:
    its rope on the drum, its battery and its motor are what they were."""

    def test_its_drum_and_its_machines_are_what_went_in(self):
        import fracture_lab  # noqa: E402
        import room_world  # noqa: E402
        import world_room  # noqa: E402
        room = world_room.SCENES["tests-machines"]()
        original = fracture_lab.validate(room)
        world_id = room_world.open_room(room)
        try:
            again = room_world.export_spec(room_world.entry_of(world_id))
        finally:
            room_world.close_room(world_id)
        self.assertEqual(again["machines"], original["machines"])
        self.assertEqual([j for j in again["joints"] if j["kind"] == "drum"],
                         [j for j in original["joints"] if j["kind"] == "drum"])
        self.assertEqual([a["label"] for a in again["actions"]], ["Wind it up", "Stop", "Let it down"])


def a_room_to_change() -> dict:
    """The hoist, with an iron ball to be carried somewhere else and an oak
    plank lying down to be stood up."""
    room = hoist_room()
    room["bodies"] += [
        {"name": "ball", "shape": "sphere", "material": "iron", "size_mm": [100, 100, 100],
         "center_mm": [1000, 50, 1000]},
        {"name": "plank", "shape": "box", "material": "oak", "size_mm": [400, 100, 100],
         "center_mm": [-1000, 50, 1000]}]
    return room


def an_oak_crate_beside_the_hoist(rounds: list):
    """The room's model, scripted: asked for a crate, it adds one beside the
    hoist with the MCP's own add_object, and says so."""
    def model(api_key, model_name, conversation):
        rounds.append(len(conversation))
        if len(rounds) == 1:
            return {"status": "completed", "usage": {}, "output": [{
                "type": "function_call", "call_id": "c1", "name": "add_object",
                "arguments": json.dumps({"object": {"name": "new crate", "shape": "box", "material": "oak",
                                                    "size_m": [0.3, 0.3, 0.3], "position_m": [0.6, 0.6]}})}]}
        return {"status": "completed", "usage": {},
                "output": [{"type": "message",
                            "content": [{"type": "output_text", "text": "An oak crate is beside the hoist."}]}]}
    return model


@unittest.skipIf(ENGINE is None or LIBRARY is None, "the live world runner or the C library is not built")
class AChangeKeepsTheRoomAsItStood(unittest.TestCase):
    """The owner, 2026-09-15: "nothing should be resetting rooms". A room whose
    hoist has been wound up and whose ball has been carried somewhere else is
    changed through the server's own routes, and opened again carrying the
    world that was running (live_session.Live.open with a carry): the hoist is
    still up with its battery as it was, the ball where it was put, and the
    change is there. Before, both routes opened the room again from its spec,
    which put the crate back on the ground, the battery full and the ball where
    it was authored."""

    def setUp(self):
        import tempfile
        import threading
        from http.server import ThreadingHTTPServer
        from unittest import mock
        import room_store
        import server
        import world_room
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        folder = Path(temporary.name)
        with mock.patch.object(server, "local_configuration",
                               return_value=("a scripted model's key", "a scripted model")):
            app = server.Playground(ENGINE, ENGINE, folder / "runs")
        app.pool.shutdown(wait=False)
        app.store = room_store.RoomStore(folder / "rooms")
        self.addCleanup(app.live.shutdown)
        # The room, under a name of its own; the chat's transcript is not kept.
        for patcher in (mock.patch.dict(world_room.SCENES, {"tests-carry": a_room_to_change}),
                        mock.patch.object(server, "remember_chat")):
            patcher.start()
            self.addCleanup(patcher.stop)
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        httpd.app = app
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()

        def stop():
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=5)
        self.addCleanup(stop)
        self.app, self.port = app, httpd.server_port

    def post(self, path: str, body: dict) -> tuple[int, dict]:
        import http.client
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=180)
        try:
            connection.request("POST", path, body=json.dumps(body),
                               headers={"Content-Type": "application/json", "X-Banjo-Token": self.app.csrf_token})
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    @staticmethod
    def step(session, seconds: float) -> None:
        for _ in range(max(1, round(seconds / (8 / 240.0)))):
            session.send(op="step", dt=1 / 240.0, n=8)

    @staticmethod
    def as_it_stands(state: dict) -> dict:
        """What must not reset, as the room reports it."""
        bodies = {b["name"]: b for b in state["bodies"]}
        machines = state["machines"]
        return {"crate": bodies["crate"]["position_m"], "ball": bodies["ball"]["position_m"],
                "battery": (machines["stores"][0]["charge_j"], machines["stores"][0]["given_j"]),
                "motor": (machines["motors"][0]["state"], machines["motors"][0]["drawn_j"],
                          machines["motors"][0]["turned_rad"]),
                "rope": (machines["ropes"][0]["out_m"], machines["ropes"][0]["wound_m"])}

    def wound_up_and_moved(self):
        """The room opened, its hoist wound up for a second and braked there,
        and its ball carried a metre and put down."""
        status, opened = self.post("/api/world/open", {"scene": "tests-carry", "fresh": True})
        self.assertEqual(status, 200, opened)
        session = self.app.live.session
        self.step(session, 0.3)
        motor = session.state["machines"]["motors"][0]["id"]
        y0 = next(b for b in session.state["bodies"] if b["name"] == "crate")["position_m"][1]
        session.send(op="drive", motor=motor, command=1.0)
        self.step(session, 1.0)
        session.send(op="drive", motor=motor, command=0.0, brake=True)
        self.step(session, 0.5)
        session.send(op="grab", name="ball")
        session.send(op="move", to=[1.8, 0.3, 1.0])
        self.step(session, 0.5)
        session.send(op="release")
        self.step(session, 1.0)
        before = self.as_it_stands(session.state)
        self.assertGreater(before["crate"][1] - y0, 0.3, "the hoist did not wind the crate up")
        self.assertGreater(math.dist(before["ball"], [1.0, 0.05, 1.0]), 0.5, "the ball was not moved")
        return session, before

    def test_the_chats_change_keeps_the_hoist_up_and_the_ball_where_it_was(self):
        import world_chat
        from unittest import mock
        session, before = self.wound_up_and_moved()
        rounds: list = []
        with mock.patch.object(world_chat, "_call", an_oak_crate_beside_the_hoist(rounds)):
            status, answer = self.post("/api/world/ask",
                                       {"session": session.id, "message": "put an oak crate beside the hoist"})
        self.assertEqual(status, 200, answer)
        self.assertTrue(answer.get("reopened"), answer)
        state = answer["state"]
        restored = state["restored"]
        after = self.as_it_stands(state)
        print(f"\n   before the chat: the crate at {before['crate']}, the battery {before['battery']}, the ball at "
              f"{before['ball']}\n   after it: {restored['tier']}, {restored['bodies']} bodies as they were, "
              f"{restored['carried']}; the crate at {after['crate']}, the battery {after['battery']}, the ball at "
              f"{after['ball']}", flush=True)
        self.assertEqual(restored["tier"], "carried", restored.get("why"))
        self.assertEqual(restored["not_carried"], [], "something the chat did not touch was not carried")
        self.assertEqual(restored["carried"]["fresh"], 1, "not only the new crate is as the room has it")
        self.assertEqual(after, before, "the hoist, its battery or the ball is not as it stood")
        self.assertIn("new crate", {b["name"] for b in state["bodies"]}, "the chat's crate is not in the room")
        self.assertEqual(state["machines"]["motors"][0]["state"], "braking")
        # And it goes on: braked, the crate stays up; told to, the hoist winds on.
        live = self.app.live.session
        self.assertIsNot(live, session)
        self.step(live, 0.5)
        held = self.as_it_stands(live.state)
        self.assertLess(abs(held["crate"][1] - before["crate"][1]), 0.002, "opened again, the crate did not stay up")
        live.send(op="drive", motor=live.state["machines"]["motors"][0]["id"], command=1.0)
        self.step(live, 0.5)
        self.assertGreater(self.as_it_stands(live.state)["crate"][1] - held["crate"][1], 0.1,
                           "opened again, the hoist did not wind on")

    def test_a_stand_step_keeps_the_rest_of_the_room(self):
        session, before = self.wound_up_and_moved()
        status, answer = self.post("/api/world/action",
                                   {"session": session.id, "object": "plank", "builtin": "stand_upright"})
        self.assertEqual(status, 200, answer)
        self.assertFalse(answer.get("refused"), answer)
        self.assertTrue(answer.get("reopened"), answer)
        state = answer["state"]
        restored = state["restored"]
        after = self.as_it_stands(state)
        plank = next(b for b in state["bodies"] if b["name"] == "plank")
        print(f"\n   stood the plank up: {restored['tier']}, {restored['carried']}, {restored['not_carried']}; the "
              f"plank is {plank['dimensions_m']} facing {plank.get('orientation_wxyz')}", flush=True)
        self.assertEqual(restored["tier"], "carried", restored.get("why"))
        self.assertEqual(after, before, "the hoist, its battery or the ball is not as it stood")
        self.assertEqual(restored["carried"]["fresh"], 1, "not only the plank is as the room has it")
        self.assertEqual([line.split(":")[0] for line in restored["not_carried"]], ["the plank"])
        # Standing, it is tallest up and down, as the room now has it.
        w, x, y, z = plank.get("orientation_wxyz") or [1.0, 0.0, 0.0, 0.0]
        up = [2 * (x * y - w * z), 1 - 2 * (x * x + z * z), 2 * (y * z + w * x)]  # the plank's own y, in the world
        sizes = plank["dimensions_m"]
        tallest = max(range(3), key=lambda k: sizes[k])
        axes = [[1 - 2 * (y * y + z * z), 2 * (x * y + w * z), 2 * (x * z - w * y)], up,
                [2 * (x * z + w * y), 2 * (y * z - w * x), 1 - 2 * (x * x + y * y)]]
        self.assertGreater(abs(axes[tallest][1]), 0.99, "the plank is not standing")

    def test_a_motor_the_chat_set_going_and_e_stopped_stays_stopped_through_a_change(self):
        """The chat's drive works the room as it stands and writes what it said
        into the room too. Set winding by the chat and then stopped, as E stops
        it, the hoist stays stopped when the chat next changes the room: the
        carry does not tell it the chat's old command again
        (live_session.remember_told). Without that it did, and the hoist began
        winding again by itself."""
        import world_chat
        from unittest import mock
        session, _ = self.wound_up_and_moved()

        def wind_it(api_key, model_name, conversation):
            if not any(isinstance(item, dict) and item.get("type") == "function_call_output"
                       for item in conversation):
                return {"status": "completed", "usage": {}, "output": [{
                    "type": "function_call", "call_id": "d1", "name": "drive",
                    "arguments": json.dumps({"part": "drum", "command": 1})}]}
            return {"status": "completed", "usage": {},
                    "output": [{"type": "message", "content": [{"type": "output_text", "text": "Winding."}]}]}

        with mock.patch.object(world_chat, "_call", wind_it):
            status, answer = self.post("/api/world/ask", {"session": session.id, "message": "wind it up"})
        self.assertEqual(status, 200, answer)
        self.assertFalse(answer.get("reopened"), "telling the motor opened the room again")
        self.assertIs(self.app.live.session, session)
        self.step(session, 0.3)
        motor = session.state["machines"]["motors"][0]
        self.assertEqual(motor["state"], "driving", "the chat's drive did not reach the running room")
        # Stopped as E stops it: the running room's motor, braked. The room's
        # spec still says what the chat told it.
        session.send(op="drive", motor=motor["id"], command=0.0, brake=True)
        self.step(session, 0.5)
        before = self.as_it_stands(session.state)
        rounds: list = []
        with mock.patch.object(world_chat, "_call", an_oak_crate_beside_the_hoist(rounds)):
            status, answer = self.post("/api/world/ask",
                                       {"session": session.id, "message": "put an oak crate beside the hoist"})
        self.assertEqual(status, 200, answer)
        self.assertTrue(answer.get("reopened"), answer)
        state = answer["state"]
        self.assertEqual(state["restored"]["tier"], "carried", state["restored"].get("why"))
        self.assertEqual(state["machines"]["motors"][0]["state"], "braking",
                         "the change told the motor the chat's old command again")
        self.assertEqual(self.as_it_stands(state), before, "the hoist, its battery or the ball is not as it stood")


@unittest.skipIf(ENGINE is None, "the live world runner is not built")
class AMotorCommandLeavesTheHandAlone(unittest.TestCase):
    """The owner's review, 2026-09-15: run_action lets a drive action run while
    the hand holds something, and its cleanup then let go of whatever the hand
    held -- "Wind it up" pressed with a ball in the hand dropped the ball. An
    action lets go only of what it took hold of itself, or worked."""

    def test_winding_stopping_and_lowering_keep_what_the_hand_holds(self):
        import server  # noqa: E402 -- the page's own action runner

        class App:
            engine_path = ENGINE
            runs_path = ROOT / "build/playground-runs"
            live_inprocess = False

        def step(session, seconds: float) -> None:
            for _ in range(max(1, round(seconds / (8 / 240.0)))):
                session.send(op="step", dt=1 / 240.0, n=8)

        spec = hoist_room()
        spec["bodies"].append({"name": "ball", "shape": "sphere", "material": "rubber",
                               "size_mm": [120, 120, 120], "center_mm": [800, 60, 600]})
        spec["actions"] = [{"body": "drum", "label": "Wind it up", "steps": [{"do": "drive", "command": 1.0}]},
                           {"body": "drum", "label": "Stop", "steps": [{"do": "drive", "command": 0.0}]},
                           {"body": "drum", "label": "Let it down", "steps": [{"do": "drive", "command": -0.3}]}]
        live = live_session.Live()
        self.addCleanup(live.shutdown)
        live.open(App(), {"spec": spec})
        session = live.session
        step(session, 0.3)
        session.send(op="grab", name="ball")
        step(session, 0.3)
        self.assertEqual((session.state.get("hand") or {}).get("holding"), "ball", "the hand did not take the ball")

        class Room:
            pass

        class Server:
            pass

        room, app = Room(), Server()
        room.spec = spec
        app.live, app.room = live, room
        for index, state in ((0, "driving"), (1, "braking"), (2, "driving"), (1, "braking")):
            label = spec["actions"][index]["label"]
            answer = server.run_action(app, {"object": "drum", "action": index})
            self.assertFalse(answer.get("refused"), answer)
            step(session, 0.3)
            self.assertEqual(session.state["machines"]["motors"][0]["state"], state, f"{label} did not reach the motor")
            self.assertEqual((session.state.get("hand") or {}).get("holding"), "ball",
                             f"pressing {label!r} let go of the ball in the hand")


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
