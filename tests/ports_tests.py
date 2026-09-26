"""Devices that pair (docs/machine-world.md, "Devices that pair"): the mouths
goods go into a device through and come out of, the rule that pairs two of
them, the transfer that runs between them, the room's spelling, and -- in the
real engine -- the mine's rover docking its store to the smelter's intake port
and releasing its ore there.

    BANJO_LIVE_ENGINE=.../banjo_live_world_run.exe python tests/ports_tests.py

Without BANJO_LIVE_ENGINE only the checks that need no engine run, unless
BANJO_ROVER_LIVE_TESTS=required, which ctest sets.
"""
from __future__ import annotations

from copy import deepcopy
import json
import math
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "playground")]
import fracture_lab, inventory, live_session, machine_goods, machine_ports  # noqa: E402
import machine_routine, machine_senses, machine_tools  # noqa: E402
import room_store, rover_brain  # noqa: E402

ENGINE = Path(os.environ["BANJO_LIVE_ENGINE"]).resolve() if os.environ.get("BANJO_LIVE_ENGINE") else None
DT = 1 / 240
MINE = ROOT / "playground" / "rooms" / "tests-mine.json"


def mouth(name, flow, body, at, normal, holds="hopper", goods=()):
    return {"name": name, "flow": flow, "body": body, "at_mm": [1000.0 * v for v in at],
            "normal": list(normal), "holds": holds, "goods": list(goods)}


def two_machines(giving, taking):
    """A room of two machines with one mouth each, already standing where they
    are put: the pairing rule on its own, with no engine."""
    ports = machine_ports.Ports({"machines": {"programs": [
        {"name": "rover", "ports": [machine_ports.checked([giving], "rover", {"rover"})[0]]},
        {"name": "smelter", "ports": [machine_ports.checked([taking], "smelter", {"smelter"})[0]]}]}})
    ports.follow([{"name": "rover", "position_m": [0, 0, 0], "orientation_wxyz": [1, 0, 0, 0]},
                  {"name": "smelter", "position_m": [0, 0, 0], "orientation_wxyz": [1, 0, 0, 0]}])
    return ports


class TheSpelling(unittest.TestCase):
    def test_a_port_is_checked_in_the_rooms_words(self):
        [port] = machine_ports.checked(
            [{"name": " smelter  intake ", "flow": "in", "body": "smelter", "at_mm": [-3000, 400, -9200],
              "normal": [0, 0, 2], "holds": "smelter intake", "goods": ["copper ore"]}], "smelter", {"smelter"})
        self.assertEqual(("smelter intake", "in", "goods", "smelter intake", ["copper ore"]),
                         (port["name"], port["flow"], port["fitting"], port["holds"], port["goods"]))
        self.assertEqual([0.0, 0.0, 1.0], port["normal"], "the way it looks is a unit vector")
        bare = machine_ports.checked([{"name": "store", "flow": "out", "body": "rover", "at_mm": [0, 0, 0],
                                       "normal": [0, 0, 1]}], "rover", {"rover"})
        self.assertEqual(("goods", "hopper", []), (bare[0]["fitting"], bare[0]["holds"], bare[0]["goods"]),
                         "a port that says none takes anything, out of its machine's own hopper")
        for broken, why in (
                ([{"name": "p", "flow": "both", "body": "rover", "at_mm": [0, 0, 0], "normal": [0, 0, 1]}], "flow is"),
                ([{"name": "p", "flow": "in", "body": "nowhere", "at_mm": [0, 0, 0], "normal": [0, 0, 1]}],
                 "not in this room"),
                ([{"name": "p", "flow": "in", "body": "rover", "at_mm": [0, 0], "normal": [0, 0, 1]}], "at_mm"),
                ([{"name": "p", "flow": "in", "body": "rover", "at_mm": [0, 0, 0], "normal": [0, 0, 0]}],
                 "must look some way"),
                ([{"name": "p", "flow": "in", "body": "rover", "at_mm": [0, 0, 0], "normal": [0, 0, 1],
                   "fitting": "steam"}], "its fitting is"),
                ([{"name": "p", "flow": "in", "body": "rover", "at_mm": [0, 0, 0], "normal": [0, 0, 1]},
                  {"name": "p", "flow": "out", "body": "rover", "at_mm": [0, 0, 0], "normal": [0, 0, 1]}],
                 "name of its own"),
                ([{"name": "p", "flow": "in", "body": "rover", "at_mm": [0, 0, 0], "normal": [0, 0, 1],
                   "hose": 1}], "cannot say")):
            with self.subTest(why=why), self.assertRaisesRegex(ValueError, why):
                machine_ports.checked(broken, "rover", {"rover"})
        self.assertEqual([], machine_ports.checked(None, "rover", {"rover"}))


class TheRuleThatPairsTwo(unittest.TestCase):
    """One gives, one takes, their fittings match, they are within a dock of
    each other, their faces are opposed within the allowance, and neither is
    behind the other."""

    def paired(self, giving_at, giving_normal, taking_at, taking_normal, **rest):
        ports = two_machines(mouth("rover store", "out", "rover", giving_at, giving_normal),
                             mouth("smelter intake", "in", "smelter", taking_at, taking_normal, **rest))
        docked, near, why, far = ports.pair_of(ports.by_name("rover store"))
        return (docked.name if docked else None), why

    def test_face_to_face_within_a_dock_pairs(self):
        name, why = self.paired((0, 0.4, 0), (0, 0, 1), (0, 0.4, 0.5), (0, 0, -1))
        self.assertEqual("smelter intake", name, why)

    def test_too_far_apart_does_not_pair_and_says_how_far(self):
        name, why = self.paired((0, 0.4, 0), (0, 0, 1), (0, 0.4, 2.0), (0, 0, -1))
        self.assertIsNone(name)
        self.assertIn("2.00 m apart", why)
        self.assertIn(f"{machine_ports.DOCK_M:g} m", why)
        # Just inside the dock, and just outside it.
        self.assertEqual("smelter intake",
                         self.paired((0, 0.4, 0), (0, 0, 1),
                                     (0, 0.4, machine_ports.DOCK_M - 0.01), (0, 0, -1))[0])
        self.assertIsNone(self.paired((0, 0.4, 0), (0, 0, 1),
                                      (0, 0.4, machine_ports.DOCK_M + 0.01), (0, 0, -1))[0])

    def test_turned_away_does_not_pair_and_says_by_how_much(self):
        # Near enough, but the taking mouth looks the same way as the giving
        # one: the ore would go past its back.
        name, why = self.paired((0, 0.4, 0), (0, 0, 1), (0, 0.4, 0.5), (0, 0, 1))
        self.assertIsNone(name)
        self.assertIn("deg from facing each other", why)
        # Just inside the allowance, and just outside it.
        inside = math.radians(machine_ports.FACING_DEG - 5.0)
        outside = math.radians(machine_ports.FACING_DEG + 5.0)
        self.assertEqual("smelter intake",
                         self.paired((0, 0.4, 0), (0, 0, 1), (0, 0.4, 0.5),
                                     (math.sin(inside), 0, -math.cos(inside)))[0])
        self.assertIsNone(self.paired((0, 0.4, 0), (0, 0, 1), (0, 0.4, 0.5),
                                      (math.sin(outside), 0, -math.cos(outside)))[0])

    def test_a_mouth_behind_the_other_does_not_pair_however_square_it_is(self):
        # The two faces are exactly opposed, but the taker is behind the giver:
        # a machine that has driven past does not go on unloading into it.
        name, why = self.paired((0, 0.4, 0), (0, 0, 1), (0, 0.4, -0.5), (0, 0, -1))
        self.assertIsNone(name)
        self.assertIn("behind", why)

    def test_a_mouth_offset_to_one_side_still_pairs(self):
        # The case the page found: a machine stops within a metre of a point,
        # which over half a metre of dock puts its mouth well off the line to
        # the other. Their faces are still opposed, so they pair.
        for across in (0.1, 0.2, 0.3, 0.4):
            with self.subTest(across_m=across):
                name, why = self.paired((across, 0.4, 0), (0, 0, 1), (0, 0.4, 0.5), (0, 0, -1))
                self.assertEqual("smelter intake", name, f"{across} m across: {why}")

    def test_a_device_does_not_feed_itself(self):
        ports = machine_ports.Ports({"machines": {"programs": [{"name": "smelter", "ports": machine_ports.checked(
            [mouth("smelter intake", "in", "smelter", (0, 0.4, 0.3), (0, 0, 1), holds="a"),
             mouth("smelter outlet", "out", "smelter", (-0.3, 0.4, 0), (-1, 0, 0), holds="b")],
            "smelter", {"smelter"})}]}})
        ports.follow([{"name": "smelter", "position_m": [0, 0, 0], "orientation_wxyz": [1, 0, 0, 0]}])
        docked, near, why, far = ports.pair_of(ports.by_name("smelter outlet"))
        self.assertIsNone(docked)
        self.assertIsNone(near, "its own other mouth is not even reported as near")
        self.assertEqual([], [r for r in ports.report() if r.get("near")])

    def test_two_mouths_the_same_way_round_never_pair(self):
        ports = two_machines(mouth("a", "out", "rover", (0, 0, 0), (0, 0, 1)),
                             mouth("b", "out", "smelter", (0, 0, 0.5), (0, 0, -1)))
        self.assertEqual((None, None, "", math.inf), ports.pair_of(ports.by_name("a")),
                         "two mouths that both give are not candidates at all")


class AMouthRidesItsBody(unittest.TestCase):
    def test_it_turns_with_the_machine_that_carries_it(self):
        ports = machine_ports.Ports({"machines": {"programs": [{"name": "rover", "ports": machine_ports.checked(
            [mouth("rover store", "out", "rover", (0.0, 0.45, 2.52), (0, 0, 1))], "rover", {"rover"})}]}})
        # As the room is made: the rover stands at (0, 0, 2) facing +z, so its
        # mouth is 0.52 m ahead of it.
        ports.follow([{"name": "rover", "position_m": [0.0, 0.0, 2.0], "orientation_wxyz": [1, 0, 0, 0]}])
        port = ports.by_name("rover store")
        self.assertAlmostEqual(2.52, port.at_m[2], places=6)
        # Turned half round and driven off to (5, 0, 5): its mouth is behind it
        # in the room's frame, and looks the other way.
        ports.follow([{"name": "rover", "position_m": [5.0, 0.0, 5.0], "orientation_wxyz": [0, 0, 1, 0]}])
        self.assertAlmostEqual(5.0 - 0.52, port.at_m[2], places=5)
        self.assertAlmostEqual(0.45, port.at_m[1], places=5)
        self.assertAlmostEqual(-1.0, port.normal[2], places=5)
        # A reply that does not carry the rover leaves it where it was: the
        # runner sends a body again only when its record changed.
        ports.follow([{"name": "post", "position_m": [1, 0, 1], "orientation_wxyz": [1, 0, 0, 0]}])
        self.assertAlmostEqual(5.0 - 0.52, port.at_m[2], places=5)

    def test_its_place_on_the_body_comes_from_the_spec_not_the_first_pose_seen(self):
        """The bug the page found: a room rejoined gives the bodies wherever
        they have got to, and a mouth carried into the body's frame from THERE
        lands wherever the machine has driven since."""
        spec = {"precise_rigid_bodies": [{"name": "rover", "position_m": [0.0, 0.0, -9.0],
                                          "orientation_wxyz": [1, 0, 0, 0]}],
                "machines": {"programs": [{"name": "rover", "ports": machine_ports.checked(
                    [mouth("rover store", "out", "rover", (0.0, 0.45, -8.48), (0, 0, 1))],
                    "rover", {"rover"})}]}}
        ports = machine_ports.Ports(spec)
        port = ports.by_name("rover store")
        self.assertTrue(port.settled(), "it takes its place on the body from the spec, before any pose arrives")
        # Now the room is rejoined: the rover is 3 m away and turned a quarter.
        ports.follow([{"name": "rover", "position_m": [3.0, 0.0, -9.0],
                       "orientation_wxyz": [math.cos(math.pi / 4), 0.0, math.sin(math.pi / 4), 0.0]}])
        self.assertAlmostEqual(0.52, math.dist([3.0, 0.0, -9.0], [port.at_m[0], 0.0, port.at_m[2]]), places=5,
                               msg="its mouth is still half a metre off its own deck")
        self.assertAlmostEqual(1.0, port.normal[0], places=5, msg="and looks the way the rover now faces")

    def test_a_quaternion_the_engine_rounded_is_normalised_first(self):
        # The runner rounds a quaternion to 1e-5, so one that should be a unit
        # arrives a little short. A mouth 1 m out must still read 1 m out.
        q = [round(math.cos(0.3), 5), 0.0, round(math.sin(0.3), 5), 0.0]
        turned = machine_ports._turn(q, [0.0, 0.0, 1.0])
        self.assertAlmostEqual(1.0, math.sqrt(sum(v * v for v in turned)), places=9)


class WhatPassesBetweenThem(unittest.TestCase):
    def setUp(self):
        self.goods = machine_goods.Goods({"goods": {"stockpiles": [
            {"name": "smelter intake", "at_m": [0.0, 0.5], "radius_m": 1.0, "holds": {}},
            {"name": "smelter output", "at_m": [-1.5, 0.0], "radius_m": 1.0, "holds": {"copper": 4.0}}]}})
        self.routine = machine_routine.Routine("rover", {"kind": "custom", "hopper_kg": 40.0,
                                                         "steps": [{"do": "hold_still", "until": 1}]})
        self.routine.load_in(0.01, 0.02, 40.0, {"copper ore": 12.0})

    def ports_for(self, *declared):
        programs = []
        for machine, one in declared:
            programs.append({"name": machine, "ports": machine_ports.checked([one], machine, {machine})})
        made = machine_ports.Ports({"machines": {"programs": programs}},
                                   holder_for=machine_ports.holders_over(
                                       self.goods, lambda name: self.routine))
        made.follow([{"name": m, "position_m": [0, 0, 0], "orientation_wxyz": [1, 0, 0, 0]}
                     for m, _ in declared])
        return made

    def test_a_hopper_passes_its_goods_into_a_heap_and_keeps_its_soil(self):
        ports = self.ports_for(("rover", mouth("rover store", "out", "rover", (0, 0.4, 0), (0, 0, 1))),
                               ("smelter", mouth("smelter intake", "in", "smelter", (0, 0.4, 0.5), (0, 0, -1),
                                                 holds="smelter intake", goods=["copper ore"])))
        passed = machine_ports.pass_goods(ports, ports.by_name("rover store"), ports.by_name("smelter intake"))
        self.assertEqual({"copper ore": 12.0}, passed["moved"])
        self.assertEqual({"copper ore": 12.0}, self.goods.by_name("smelter intake")["holds"])
        self.assertEqual({}, self.routine.goods, "the ore is gone out of the hopper")
        self.assertAlmostEqual(28.0, self.routine.kg, places=6,
                               msg="and the soil it came out of is still in it, to be tipped on the ground")
        self.assertAlmostEqual(0.02, self.routine.soil_m3, places=6)

    def test_a_heap_passes_into_a_hopper_and_no_more_than_it_holds(self):
        self.routine.load_out()
        self.routine.hopper_kg = 3.0
        ports = self.ports_for(("smelter", mouth("smelter outlet", "out", "smelter", (0, 0.4, 0), (0, 0, 1),
                                                 holds="smelter output")),
                               ("drone", mouth("drone store", "in", "drone", (0, 0.4, 0.5), (0, 0, -1))))
        passed = machine_ports.pass_goods(ports, ports.by_name("smelter outlet"), ports.by_name("drone store"))
        self.assertEqual({"copper": 3.0}, passed["moved"], "only what the hopper has room for")
        self.assertEqual({"copper": 1.0}, self.goods.by_name("smelter output")["holds"])
        self.assertEqual({"copper": 3.0}, self.routine.goods)

    def test_a_mouth_that_does_not_take_a_substance_passes_none_of_it(self):
        ports = self.ports_for(("rover", mouth("rover store", "out", "rover", (0, 0.4, 0), (0, 0, 1))),
                               ("mill", mouth("mill intake", "in", "mill", (0, 0.4, 0.5), (0, 0, -1),
                                              holds="smelter intake", goods=["copper"])))
        passed = machine_ports.pass_goods(ports, ports.by_name("rover store"), ports.by_name("mill intake"))
        self.assertEqual({}, passed["moved"])
        self.assertIn("does not take copper ore", passed["why"])
        self.assertAlmostEqual(40.0, self.routine.kg, places=6, msg="nothing left the hopper")

    def test_a_mouth_behind_a_heap_the_room_has_not_got_says_so(self):
        ports = self.ports_for(("rover", mouth("rover store", "out", "rover", (0, 0.4, 0), (0, 0, 1))),
                               ("mill", mouth("mill intake", "in", "mill", (0, 0.4, 0.5), (0, 0, -1),
                                              holds="a bin that is not there")))
        with self.assertRaisesRegex(ValueError, "a bin that is not there"):
            machine_ports.pass_goods(ports, ports.by_name("rover store"), ports.by_name("mill intake"))

    def test_the_dock_tool_works_out_its_own_mouth_and_says_why_when_it_cannot(self):
        ports = self.ports_for(("rover", mouth("rover store", "out", "rover", (0, 0.4, 0), (0, 0, 1))),
                               ("smelter", mouth("smelter intake", "in", "smelter", (0, 0.4, 3.0), (0, 0, -1),
                                                 holds="smelter intake")))
        ctx = machine_senses.Context(program={"name": "rover", "id": 1}, routine=self.routine, goods=self.goods,
                                     ports=ports, ask=lambda **c: {"program": {"doing": "waiting"}})
        did = machine_tools.run(ctx, machine_tools.Call("dock", {}, "test"))
        self.assertEqual({}, did["moved"], did["did"])
        self.assertIn("3.00 m apart", did["did"], "the nearest partner is named however far off it is")
        self.assertNotIn("idle", did, "a dock never answers idle: a step that is only idle can never end")
        # Brought alongside, the same call passes the ore, and never the soil.
        ports.by_name("smelter intake").at_m = [0.0, 0.4, 0.5]
        did = machine_tools.run(ctx, machine_tools.Call("dock", {}, "test"))
        self.assertEqual({"copper ore": 12.0}, did["moved"], did["did"])
        self.assertEqual("rover store", did["from"])
        self.assertEqual("smelter intake", did["into"])
        self.assertIn("in 3.0 s", did["did"], "12 kg at a quarter of a second the kilogram")


class TheRoomsSpelling(unittest.TestCase):
    def room(self):
        return {"algorithm": "lattice", "cell_m": 0.05,
                "bodies": [{"name": "smelter", "shape": "box", "material": "concrete", "anchored": True,
                            "size_mm": [600, 800, 600], "center_mm": [0, 400, 0]}],
                "machines": {"stores": [{"name": "smelter battery", "body": "smelter", "capacity_j": 1000.0,
                                         "charge_j": 500.0, "voltage_v": 24.0}],
                             "programs": [{"name": "smelter", "kind": "still", "body": "smelter",
                                           "store": "smelter battery",
                                           "ports": [mouth("smelter intake", "in", "smelter", (0, 0.4, 0.32),
                                                           (0, 0, 1), holds="smelter intake"),
                                                     mouth("smelter outlet", "out", "smelter", (-0.32, 0.4, 0),
                                                           (-1, 0, 0), holds="smelter output")],
                                           "routine": {"kind": "process", "recipe": "smelt copper",
                                                       "intake": "smelter intake", "output": "smelter output"}}]}}

    def test_a_program_declares_its_ports_and_they_reach_the_room(self):
        validated = fracture_lab.validate(self.room())
        [program] = validated["machines"]["programs"]
        self.assertEqual(["smelter intake", "smelter outlet"], [p["name"] for p in program["ports"]])
        self.assertEqual(["in", "out"], [p["flow"] for p in program["ports"]])
        self.assertEqual([-1.0, 0.0, 0.0], program["ports"][1]["normal"])

    def test_two_ports_of_one_name_and_a_step_that_names_no_port_are_refused(self):
        # Within one machine its own checker catches it; across two machines
        # the room does, because a port is named across the whole room.
        twice = self.room()
        twice["machines"]["programs"][0]["ports"][1]["name"] = "smelter intake"
        with self.assertRaisesRegex(ValueError, "name of its own"):
            fracture_lab.validate(twice)
        shared = self.room()
        shared["bodies"].append({"name": "mill", "shape": "box", "material": "concrete", "anchored": True,
                                 "size_mm": [600, 800, 600], "center_mm": [3000, 400, 0]})
        shared["machines"]["stores"].append({"name": "mill battery", "body": "mill", "capacity_j": 1000.0,
                                             "charge_j": 500.0, "voltage_v": 24.0})
        shared["machines"]["programs"].append(
            {"name": "mill", "kind": "still", "body": "mill", "store": "mill battery",
             "ports": [mouth("smelter intake", "in", "mill", (3, 0.4, 0.32), (0, 0, 1), holds="mill intake")]})
        with self.assertRaisesRegex(ValueError, "two ports are called"):
            fracture_lab.validate(shared)
        astray = self.room()
        astray["machines"]["programs"][0]["routine"] = {
            "kind": "custom", "steps": [{"do": "dock", "args": {"port": "the moon"}, "until": "done"}]}
        with self.assertRaisesRegex(ValueError, "names the port 'the moon'"):
            fracture_lab.validate(astray)
        ok = self.room()
        ok["machines"]["programs"][0]["routine"] = {
            "kind": "custom", "steps": [{"do": "dock", "args": {"port": "smelter intake"}, "until": "done"}]}
        self.assertEqual("smelter intake",
                         fracture_lab.validate(ok)["machines"]["programs"][0]["routine"]["steps"][0]["args"]["port"])

    def test_a_room_with_no_ports_is_exactly_as_it_was(self):
        plain = self.room()
        plain["machines"]["programs"][0].pop("ports")
        self.assertNotIn("ports", fracture_lab.validate(plain)["machines"]["programs"][0])


@unittest.skipUnless(ENGINE and ENGINE.is_file(), "BANJO_LIVE_ENGINE is required")
class TheMinesRoverDocksAtTheSmelter(unittest.TestCase):
    """The mine room, opened as the server opens it and stepped as the page
    steps it: the rover digs the vein, drives to the smelter's intake PORT --
    not to a patch of ground -- and releases its ore through its own store
    port, which the page is told about with every step."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.spec = json.loads(MINE.read_text(encoding="utf-8"))
        self.live = live_session.Live()
        self.addCleanup(self.live.shutdown)
        self.room = SimpleNamespace(scene="tests-mine", spec=self.spec, chat=[], inventory=inventory.Inventory(),
                                    workshop_installs=[])
        self.brains = rover_brain.Brains(lambda: None)
        self.landed: list[tuple[str, float]] = []
        self.brains.on_rack = lambda substance, kg: self.landed.append((substance, kg))
        self.app = SimpleNamespace(live=self.live, live_holder="world", room=self.room, engine_path=ENGINE,
                                   runs_path=root / "runs", store=room_store.RoomStore(root / "rooms"),
                                   brains=self.brains, api_key="", model="",
                                   on_live_reply=lambda session, reply: self.brains.listen(session, reply))
        opened = self.live.open(self.app, {"spec": self.spec})
        self.brains.opened(self.spec)
        self.brains.settle(opened)
        self.opened = opened
        self.assertNotIn("machine_problems", self.live.session.state, self.live.session.state.get("machine_problems"))

    def test_the_room_declares_the_three_mouths_and_the_page_is_told_where_they_are(self):
        rows = {r["name"]: r for r in self.opened["ports"]}
        self.assertEqual({"rover store", "smelter intake", "smelter outlet", "mill intake", "mill outlet"}, set(rows))
        self.assertEqual(("out", "hopper"), (rows["rover store"]["flow"], rows["rover store"]["holds"]))
        self.assertEqual(("in", "smelter intake"), (rows["smelter intake"]["flow"], rows["smelter intake"]["holds"]))
        self.assertEqual(("out", "smelter output"), (rows["smelter outlet"]["flow"], rows["smelter outlet"]["holds"]))
        # The smelter's intake looks out along +z, towards where the ore comes
        # from, and its outlet along -x, towards the heap it fills.
        self.assertAlmostEqual(1.0, rows["smelter intake"]["normal"][2], places=3)
        self.assertAlmostEqual(-1.0, rows["smelter outlet"]["normal"][0], places=3)
        self.assertTrue(all(r["docked"] is None for r in rows.values()), "nothing is alongside anything yet")

    def test_the_rover_drives_to_the_port_docks_and_its_ore_goes_into_the_smelter(self):
        programs = {p["name"]: p for p in self.live.session.send(op="step", dt=DT, n=1)["machines"]["programs"]}
        for seq, (name, p) in enumerate(programs.items(), 1):
            self.live.session.send(op="run", program=p["id"], sender="test", seq=seq, power=True)
        sid = self.live.session.id
        goods = self.brains.goods
        intake = goods.by_name("smelter intake")
        docked_at, passed_at, t, rows = None, None, 0.0, []
        for _ in range(5 * 240):                  # up to 300 s of the world
            body = {"session": sid, "op": "step", "dt": DT, "n": 60}
            self.brains.before(self.app, body)
            answer = self.live.act(body)
            self.brains.attach(body, answer)
            t = float(answer["t"])
            rows = {r["name"]: r for r in answer.get("ports") or []}
            if docked_at is None and rows.get("rover store", {}).get("docked"):
                docked_at = (t, dict(rows["rover store"]))
            if passed_at is None and float((intake.get("holds") or {}).get("copper ore", 0.0)) > 0.0:
                passed_at = (t, dict(intake["holds"]))
            if passed_at is not None and docked_at is not None:
                break
        notes = list(self.brains.of("rover").routine.notes)[-4:]
        print(f"\n    the rover's store docked to {docked_at and docked_at[1]['docked']} at "
              f"{docked_at and round(docked_at[0], 1)} s; the smelter's intake pile held "
              f"{passed_at and passed_at[1]} at {passed_at and round(passed_at[0], 1)} s; notes: {notes}")
        self.assertIsNotNone(docked_at, f"the rover never docked in {t:.0f} s; {notes}")
        self.assertEqual("smelter intake", docked_at[1]["docked"])
        self.assertIsNotNone(passed_at, f"nothing came through the port in {t:.0f} s; {notes}")
        self.assertGreater(passed_at[1]["copper ore"], 5.0, "a hopper of ore, not a crumb")
        self.assertTrue(any("docked rover store to smelter intake" in n for n in
                            self.brains.of("rover").routine.notes), notes)
        # It came through the ports, not through a dump onto a place: the
        # rover's own routine names no stockpile at all.
        steps = self.spec["machines"]["programs"][0]["routine"]["steps"]
        self.assertEqual("smelter intake", next(s for s in steps if s["do"] == "go_to" and "port" in s["args"])
                         ["args"]["port"])
        self.assertNotIn("smelter intake", json.dumps(self.spec["machines"]["programs"][0]["routine"]["places"]))

    def test_a_room_rejoined_mid_run_still_has_its_mouths_on_its_machines(self):
        """As a reload does: a second Brains over the same spec, given the
        bodies where they now stand rather than where the room put them."""
        programs = {p["name"]: p for p in self.live.session.send(op="step", dt=DT, n=1)["machines"]["programs"]}
        self.live.session.send(op="run", program=programs["rover"]["id"], sender="test", seq=1, power=True)
        sid = self.live.session.id
        for _ in range(80):
            body = {"session": sid, "op": "step", "dt": DT, "n": 60}
            self.brains.before(self.app, body)
            answer = self.live.act(body)
            self.brains.attach(body, answer)
        rejoined = rover_brain.Brains(lambda: None)
        rejoined.opened(self.spec)
        rejoined.settle(answer)
        deck = next(b for b in answer["bodies"] if b["name"] == "rover")["position_m"]
        store = rejoined.ports.by_name("rover store").at_m
        off = math.dist([deck[0], 0.0, deck[2]], [store[0], 0.0, store[2]])
        print(f"    rejoined {round(math.dist([0, 0], [deck[0], deck[2] + 9.0]), 2)} m from where the room put "
              f"the rover, its mouth is {off:.2f} m off the deck's middle")
        self.assertLess(off, 0.7, "its mouth is on its own deck, not where the room first put it")

    def test_a_mouth_the_room_has_moved_is_found_where_it_now_stands(self):
        # A port is on a body, not at a point of the room: the rover's own
        # mouth reads where the rover is, and moves as it drives.
        before = list(self.brains.ports.by_name("rover store").at_m)
        programs = {p["name"]: p for p in self.live.session.send(op="step", dt=DT, n=1)["machines"]["programs"]}
        self.live.session.send(op="run", program=programs["rover"]["id"], sender="test", seq=1, power=True)
        sid = self.live.session.id
        for _ in range(60):
            body = {"session": sid, "op": "step", "dt": DT, "n": 60}
            self.brains.before(self.app, body)
            self.brains.attach(body, self.live.act(body))
        after = list(self.brains.ports.by_name("rover store").at_m)
        moved = math.dist(before, after)
        print(f"    the rover's mouth moved {moved:.2f} m with it")
        self.assertGreater(moved, 0.5, "the mouth rides the rover")
        still = self.brains.ports.by_name("smelter intake").at_m
        self.assertLess(math.dist(still, [-3.0, still[1], -9.18]), 0.05, "and an anchored block's does not")


if __name__ == "__main__":
    if os.environ.get("BANJO_ROVER_LIVE_TESTS") == "required" and not (ENGINE and ENGINE.is_file()):
        raise RuntimeError("BANJO_LIVE_ENGINE must be built for the required live ports tests")
    unittest.main()
