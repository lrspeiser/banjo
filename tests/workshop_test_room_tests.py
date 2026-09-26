"""The Workshop's test room: a little world with the world's own physics.

    BANJO_LIVE_ENGINE=.../banjo_live_world_run.exe python -m pytest tests/workshop_test_room_tests.py

Without BANJO_LIVE_ENGINE nothing here runs: every one of these needs the real
engine, because the whole point of the room is that it is the real one.
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
        # And the goods its power parts are made of: a machine's motors and
        # panels take copper and copper wire off the goods rack when it is made.
        for substance in ("copper", "copper wire"):
            workshop_library.set_goods(app, substance, 500.0)
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


    def test_a_machine_can_be_worked_by_hand_where_it_is_built(self):
        """The world has On/Off, a direction and a drive setting for every
        control on a machine. The bench had none of it, so a machine could be
        built here and never worked until it was out in the world.
        """
        room = self.opened()
        room.make(self.candidate())
        controls = room.works()
        print("\n    its controls: " + ", ".join(sorted(controls)))
        self.assertEqual({"left wheel", "right wheel"}, set(controls))

        stood = room.reading()["bodies"]
        # Both wheels driven the same way, which is forward.
        for name in sorted(controls):
            room.work(name, power=True, direction=1, setting=1.0)
        drove = room.run(4.0)
        deck = room.made["root_body"]
        went = math.dist(drove["bodies"][deck]["at_m"], stood["bodies"][deck]["at_m"]
                         if "bodies" in stood else stood[deck]["at_m"])
        print(f"      driven for 4 s it went {went:.3f} m")
        self.assertGreater(went, 0.05, "told to drive, it drove")

        # And switched off it stops, rather than coasting for ever.
        for name in sorted(controls):
            room.work(name, power=False, direction=0, setting=0.0)
        stopped = room.run(3.0)
        self.assertLess(stopped["bodies"][deck]["speed_m_s"], 0.05)
        print(f"      switched off it is doing {stopped['bodies'][deck]['speed_m_s']:.4f} m/s")

    def test_what_to_do_to_it_can_be_written_down_with_times(self):
        """One call: make it, drive it, stop it, and say what happened."""
        said = bench.try_it(
            self.app, self.candidate(), seconds=6.0, turn_on=False,
            do=[{"at_s": 0.0, "control": "left wheel", "direction": 1, "setting": 1.0},
                {"at_s": 0.0, "control": "right wheel", "direction": 1, "setting": 1.0},
                {"at_s": 3.0, "control": "left wheel", "power": False, "direction": 0},
                {"at_s": 3.0, "control": "right wheel", "power": False, "direction": 0}])
        print("    " + said["says"])
        self.assertEqual(4, len(said["worked"]))
        self.assertEqual([0.0, 0.0, 3.0, 3.0], [round(w["at_s"]) for w in said["worked"]])
        self.assertEqual({"left wheel", "right wheel"}, {w["control"] for w in said["worked"]})
        # It moved, and its own program was never started: this is by hand.
        deck = said["made"]["root_body"]
        went = math.dist(said["ended"]["bodies"][deck]["at_m"], said["began"]["bodies"][deck]["at_m"])
        print(f"      by hand it went {went:.3f} m, and turned_on is {said['turned_on']}")
        self.assertFalse(said["turned_on"])
        self.assertGreater(went, 0.05)

    def test_it_refuses_an_order_it_cannot_carry_out(self):
        room = self.opened()
        room.make(self.candidate())
        with self.assertRaises(ValueError) as caught:
            room.work("the handbrake")
        self.assertIn("left wheel, right wheel", str(caught.exception))
        for bad in ({"direction": 7}, {"setting": 4.0}):
            with self.assertRaises(ValueError):
                room.work("left wheel", **bad)
        # And an order timed after the end of the run is a mistake worth saying,
        # not one to carry out silently at the end.
        with self.assertRaises(ValueError) as caught:
            bench.try_it(self.app, self.candidate(), seconds=1.0, record=False,
                         do=[{"at_s": 30.0, "control": "left wheel"}])
        self.assertIn("after the run ends", str(caught.exception))

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


TABLE = {"kind": "table", "design_id": "bench-table", "purpose": "be stood on",
         "parameters": {}, "component_overrides": {}}


@unittest.skipUnless(ENGINE and ENGINE.is_file(), "BANJO_LIVE_ENGINE is required")
class TheFourWaysOfTryingAThing(unittest.TestCase):
    """A weight on it, a drop, a slide and a blow -- all in the one room.

    These were four separate rigs, none of which had any ground under them.
    They are settings now, and the thing they are done to is standing in a
    world, so what they measure is what it would do out there.
    """

    def setUp(self):
        self.app = SimpleNamespace(engine_path=ENGINE, workshop_owner_id="owner")

    def test_nothing_happens_to_a_thing_nothing_is_done_to(self):
        said = bench.try_it(self.app, TABLE, seconds=2.0)
        deck = said["ended"]["bodies"][said["made"]["root_body"]]
        print(f"\n    left alone: {said['says']}")
        self.assertEqual({}, said["did"])
        self.assertEqual([], said["broke"])
        self.assertFalse(said["fell_over"])
        self.assertLess(deck["turn_deg"], 1.0, "standing still is not turning")
        self.assertNotIn("the weight", said["ended"]["bodies"])
        self.assertNotIn("the striker", said["ended"]["bodies"])

    def test_a_weight_is_a_body_that_falls_onto_it_and_stays_there(self):
        """Not a declared downward force: a block of iron, with contact under it.

        A force would go on pushing at full strength through a collapse and
        never fall off the side. This is 120 kg of iron, and where it ends up
        is the answer.
        """
        said = bench.try_it(self.app, TABLE, seconds=2.0, load_kg=120.0)
        weight = said["ended"]["bodies"]["the weight"]
        deck = said["ended"]["bodies"][said["made"]["root_body"]]
        side = said["did"]["weight_side_m"]
        print(f"    {said['says']}")
        print(f"      the {120:g} kg weight is a {side * 1000:.0f} mm iron cube, resting at "
              f"{weight['at_m'][1]:.3f} m with the top of the table at {deck['at_m'][1]:.3f} m")
        self.assertGreater(weight["at_m"][1], bench.GROUND_M + side, "it is up on the table, not on the floor")
        self.assertLess(weight["speed_m_s"], 0.05, "it came to rest on it")
        self.assertEqual([], said["broke"], "a 27 kg oak table holds 120 kg")

    def test_a_weight_can_be_DROPPED_on_it_rather_than_only_set_on_it(self):
        """The one thing the room could not do.

        The owner asked the chat to "drop a 20 kg iron block on the bench" and
        watched it thrown at the side instead. Nothing here could drop a thing
        ONTO a thing: `drop_m` lets go of the THING, `strike` throws a block
        along the floor, and a weight was placed a millimetre above it. So the
        only body that ever arrived with any speed arrived sideways.
        """
        said = bench.try_it(self.app, TABLE, seconds=2.0, load_kg=20.0, from_m=2.0)
        weight = said["ended"]["bodies"]["the weight"]
        began = said["began"]["bodies"]["the weight"]
        print("\n    " + said["says"])
        print(f"      it was let go at {began['at_m'][1]:.2f} m and ended at {weight['at_m'][1]:.2f} m, "
              f"{abs(weight['at_m'][0]):.3f} m off the middle")
        self.assertEqual(2.0, said["did"]["dropped_on_from_m"])
        # It came from ABOVE: it started two metres over the table and it is
        # over the middle, not out to one side of it.
        self.assertGreater(began["at_m"][1], 3.0)
        self.assertLess(abs(weight["at_m"][0]), 0.35, "it landed on it, not beside it")
        self.assertLess(abs(weight["at_m"][2]), 0.35)
        self.assertGreater(weight["at_m"][1], bench.GROUND_M + 0.3, "it is on the table, not the floor")
        # And a weight with no height is still a weight SET on it, arriving
        # with nothing: the millimetre it falls is not a drop.
        gently = bench.try_it(self.app, TABLE, seconds=1.5, load_kg=20.0, record=False)
        self.assertNotIn("dropped_on_from_m", gently["did"])
        self.assertLess(gently["began"]["bodies"]["the weight"]["at_m"][1], 1.4)

    def test_dropped_it_falls_the_distance_asked_and_lands(self):
        said = bench.try_it(self.app, TABLE, seconds=2.0, drop_m=1.0)
        deck, was = said["ended"]["bodies"][said["made"]["root_body"]], said["began"]["bodies"][said["made"]["root_body"]]
        standing = bench.try_it(self.app, TABLE, seconds=2.0, record=False)
        rest = standing["ended"]["bodies"][standing["made"]["root_body"]]["at_m"][1]
        print(f"    {said['says']}")
        print(f"      it started {was['at_m'][1] - rest:.2f} m above where it rests and came back to "
              f"{deck['at_m'][1]:.3f} m against {rest:.3f} m standing")
        self.assertAlmostEqual(1.0, was["at_m"][1] - rest, delta=0.06)
        self.assertAlmostEqual(rest, deck["at_m"][1], delta=0.05, msg="it landed where it stands")
        # And it was in the air on the way. A metre takes 0.45 s to fall, so a
        # quarter of a second in it is still falling and well off the ground.
        began = said["playback"]["frames"][0]["t_s"]
        middle = min(said["playback"]["frames"], key=lambda f: abs(f["t_s"] - began - 0.25))
        flying = next(b for b in middle["bodies"] if b["name"] == said["made"]["root_body"])
        print(f"      a quarter of a second in it was {flying['position_m'][1] - rest:.2f} m up")
        self.assertGreater(flying["position_m"][1], rest + 0.4)

    def test_slid_it_runs_on_and_friction_stops_it(self):
        said = bench.try_it(self.app, TABLE, seconds=3.0, slide_m_s=3.0)
        deck, was = said["ended"]["bodies"][said["made"]["root_body"]], said["began"]["bodies"][said["made"]["root_body"]]
        went = deck["at_m"][0] - was["at_m"][0]
        print(f"    {said['says']}")
        print(f"      started at 3 m/s, ran {went:.2f} m and is doing {deck['speed_m_s']:.3f} m/s")
        self.assertGreater(went, 0.15, "it moved along the ground")
        self.assertLess(deck["speed_m_s"], 0.3, "the ground slowed it down")

    def test_hit_hard_enough_it_breaks_and_every_piece_is_drawn(self):
        said = bench.try_it(self.app, TABLE, seconds=2.0, strike={"kg": 40.0, "speed_m_s": 12.0})
        print(f"    {said['says']}")
        self.assertTrue(said["broke"], "40 kg of iron at 12 m/s breaks an oak table")
        self.assertGreaterEqual(said["broke"][0]["pieces"], 2)
        self.assertEqual("broke", said["broke"][0]["outcome"])
        last = said["playback"]["frames"][-1]
        pieces = [b["name"] for b in last["bodies"] if "piece" in b["name"]]
        self.assertGreaterEqual(len(pieces), 2)
        for name in pieces:
            self.assertIn(f"{name}#0", said["playback"]["geometry"],
                          "a piece with no shape recorded would be drawn as a box")

    def test_the_recording_is_watchable_and_says_where_the_ground_is(self):
        said = bench.try_it(self.app, TABLE, seconds=2.0, drop_m=0.5)
        play = said["playback"]
        gaps = [b["t_s"] - a["t_s"] for a, b in zip(play["frames"], play["frames"][1:])]
        print(f"    {len(play['frames'])} frames over {play['duration_s']:.2f} s, "
              f"the longest gap {max(gaps) * 1000:.0f} ms")
        self.assertGreater(len(play["frames"]), 30, "four frames a second is not watchable")
        self.assertLess(max(gaps), 0.1)
        # Where the floor goes, for whoever draws it.
        self.assertAlmostEqual(bench.GROUND_M, play["ground_m"])
        self.assertAlmostEqual(bench.GROUND_ACROSS_M, play["ground_across_m"])
        for frame in play["frames"]:
            self.assertNotIn(bench.MARKER, [b["name"] for b in frame["bodies"]],
                             "the compiler's own sizing block is not part of anybody's test")
        self.assertTrue(all(not k.startswith(bench.MARKER + "#") for k in play["geometry"]))

@unittest.skipUnless(ENGINE and ENGINE.is_file(), "BANJO_LIVE_ENGINE is required")
class EveryMaterialGivesWaySomewhere(unittest.TestCase):
    """One table, eight materials, three ways of loading it.

    Measured 2026-09-25, on the table the bench builds -- a 1.2 x 0.04 x 0.7 m
    top on four 60 mm legs, 1.1 m between leg centres:

        material    declared  the lattice  a weight on it   20 kg dropped
        oak            52 MPa    520 (10x)  held to 2000 kg  dented at 5 m
        iron          250        500  (2x)  held to 2000     dented at 5 m
        aluminum      250        500  (2x)  held to 2000     dented at 5 m
        glass          45         45  (1x)  held to 2000     BROKE at 2 m
        ceramic       300       3600 (12x)  held to 2000     held from 5 m
        rubber         15         30  (2x)  cannot say 1200  held from 5 m
        ice             1          2  (2x)  cannot say 100   BROKE at 2 m
        concrete        3          6  (2x)  cannot say 300   BROKE at 2 m

    Brittle breaks, ductile dents, and the resting load flags exactly the three
    materials weaker than the bending it puts in the top. Alumina ceramic is
    the one that does nothing, for the reason glass used to: a break multiplier
    of 12 nobody has measured.
    """

    #: What the top carries in bending with a weight set in the middle of it:
    #: W L / 4 over b d^2 / 6, the same the engine's own survey computes.
    SPAN, BREADTH, DEPTH = 1.1, 0.7, 0.04

    def setUp(self):
        self.app = SimpleNamespace(engine_path=ENGINE, workshop_owner_id="owner")

    @classmethod
    def bending_mpa(cls, load_kg):
        return (0.25 * load_kg * 9.80665 * cls.SPAN
                / (cls.BREADTH * cls.DEPTH ** 2 / 6.0) / 1e6)

    def a_table(self, material, tag):
        out = {"kind": "table", "design_id": f"{tag}-{material.replace(' ', '-')}",
               "purpose": "be stood on", "parameters": {}, "component_overrides": {}}
        from mcp import workshop_components
        design, _ = workshop_components.design_from_spec(out)
        out["component_overrides"] = {p.name: {"material": material} for p in design.parts}
        return out

    def test_a_resting_load_flags_exactly_what_it_is_too_heavy_for(self):
        """2,000 kg is 28.9 MPa of bending. Three of the eight cannot take that
        and five can, and the room says so for all eight -- which is the whole
        screening arithmetic checked against the whole catalogue at once."""
        from mcp import engine_materials
        heavy = self.bending_mpa(2000)
        self.assertAlmostEqual(28.9, heavy, places=1)
        for material in ("oak", "iron", "aluminum", "glass", "alumina ceramic",
                         "rubber", "ice", "concrete"):
            mech = engine_materials.MECHANICS[material]
            takes = min(mech.get("compressive_strength_pa", 1e30),
                        mech["tensile_strength_pa"]) / 1e6
            with self.subTest(material=material):
                did = bench.try_it(self.app, self.a_table(material, "rest"),
                                   load_kg=2000, seconds=1.0)
                outcome = bench._outcome(did)
                print(f"\n    {material:16} takes {takes:4.0f} MPa, carrying {heavy:.1f} -> {outcome}")
                if takes > heavy:
                    self.assertEqual("held", outcome,
                                     f"{material} takes {takes} MPa and was asked for {heavy:.1f}")
                else:
                    self.assertEqual("cannot say", outcome,
                                     f"{material} takes only {takes} MPa: it should not read as held")

    def test_brittle_breaks_and_ductile_dents(self):
        """A blow has to leave a mark on everything that is not ceramic."""
        for material, expected in (("glass", "broke"), ("ice", "broke"), ("concrete", "broke"),
                                   ("oak", "dented"), ("iron", "dented"), ("aluminum", "dented")):
            with self.subTest(material=material):
                did = bench.try_it(self.app, self.a_table(material, "blow"),
                                   load_kg=20, from_m=5.0, seconds=1.5)
                print(f"    20 kg from 5 m on {material:10} -> {bench._outcome(did)}")
                self.assertEqual(expected, bench._outcome(did))

    def test_alumina_ceramic_is_the_one_that_shrugs_it_off(self):
        """Not an accident and not yet fixed, so it is written down.

        Alumina breaks at 300 MPa and the lattice removes its bonds at TWELVE
        times that strain -- 3,600 MPa -- for the same reason glass sat at
        twice 45 until somebody looked. 20 kg from 5 m puts about 414 MPa of
        bending in that top by hand, which is over what alumina takes and
        nowhere near what this lattice asks of it. Nobody has measured a
        multiplier for alumina, so nobody has changed it.
        """
        did = bench.try_it(self.app, self.a_table("alumina ceramic", "shrug"),
                           load_kg=20, from_m=5.0, seconds=1.5)
        print(f"    20 kg from 5 m on alumina ceramic -> {bench._outcome(did)} (known, see #glass)")
        self.assertEqual("held", bench._outcome(did))
        self.assertEqual([], did["broke"])

    def test_nothing_bends_sags_or_buckles(self):
        """There is no folding-under in this world, and that is architecture.

        A body is rigid to the rigid solver; the lattice is consulted to break
        it or to dent it and for nothing else. So the answers are hold, dent
        and break, and "the legs went under it" is not among them. Rubber is
        the proof: 10 MPa of Young's modulus, two thousandths of oak's, and by
        hand its 60 mm legs squash 98 mm under two tonnes while Euler says they
        cannot carry the load at all. Measured, the top sits within 1.2 mm of
        where it sits empty.
        """
        empty = bench.try_it(self.app, self.a_table("rubber", "empty"), seconds=1.5)
        loaded = bench.try_it(self.app, self.a_table("rubber", "loaded"),
                              load_kg=2000, seconds=1.5)
        up = empty["ended"]["bodies"][empty["made"]["root_body"]]["at_m"][1]
        down = loaded["ended"]["bodies"][loaded["made"]["root_body"]]["at_m"][1]
        print(f"    a rubber table under two tonnes: {1000 * (up - down):+.2f} mm")
        self.assertLess(abs(up - down), 0.005,
                        "something deformed under load, which this engine does not do -- "
                        "if that has changed, this test is the place to say so")


@unittest.skipUnless(ENGINE and ENGINE.is_file(), "BANJO_LIVE_ENGINE is required")
class WhatItCannotSay(unittest.TestCase):
    """An ice table held two tonnes, and so did a concrete one.

    Not because the arithmetic was wrong -- the engine's own survey had it at
    29 MPa against the 1 MPa ice takes, and flagged it. The lattice solve
    underneath then reported the worst bond at 0.1% of failure and half a
    micron of deflection, where beam theory gives 17 mm. A bond is an axial
    spring, so a top one cell thick is a single sheet of nodes with nothing
    across it: the load stands on directions with no stiffness, the solver
    holds those still, and a section that CANNOT BEND is answered as one that
    cannot move.

    The room then reported all of that as "nothing broke", which is the worst
    of the three, because it is the only part a person reads.
    """

    def setUp(self):
        self.app = SimpleNamespace(engine_path=ENGINE, workshop_owner_id="owner")

    @staticmethod
    def a_table(material):
        out = {"kind": "table", "design_id": f"cannot-{material}", "purpose": "be stood on",
               "parameters": {}, "component_overrides": {}}
        from mcp import workshop_components
        design, _ = workshop_components.design_from_spec(out)
        out["component_overrides"] = {p.name: {"material": material} for p in design.parts}
        return out

    def test_a_run_that_could_not_say_is_not_a_run_that_held(self):
        did = bench.try_it(self.app, self.a_table("ice"), load_kg=2000, seconds=2.0)
        print("\n    " + did["says"])
        self.assertEqual([], did["broke"], "nothing came apart, and that is not the point")
        self.assertTrue(did["could_not_say"], "the run was offered this and could not answer")
        self.assertEqual("cannot say", bench._outcome(did))
        # The sums ARE the answer, as an estimate, and they are given.
        self.assertIn("carrying more than it can hold", did["says"])
        self.assertRegex(did["says"], r"bending [\d.]+ MPa against the [\d.]+ MPa")
        # And it is said which is which: an estimate is not a run.
        self.assertIn("arithmetic, not a run", did["says"])
        because = did["could_not_say"][0]["because"]
        self.assertIn("no bending in a section this thin", because["the_run"])

    def test_a_thing_the_lattice_can_bend_still_answers(self):
        """Oak takes 52 MPa on its compression side and this is 29: it holds,
        and it says so plainly, with none of the above."""
        did = bench.try_it(self.app, self.a_table("oak"), load_kg=2000, seconds=2.0)
        print("    " + did["says"])
        self.assertEqual([], did["could_not_say"])
        self.assertEqual("held", bench._outcome(did))
        self.assertIn("nothing broke", did["says"])
        self.assertNotIn("arithmetic", did["says"])


@unittest.skipUnless(ENGINE and ENGINE.is_file(), "BANJO_LIVE_ENGINE is required")
class FindingWhereItGivesWay(unittest.TestCase):
    """The owner: "the main point when we are testing is to find the breaking
    point or test how something works ... show how it can handle a weight under
    X, cracks at Y, and shatters at Z."

    One run says whether the number you guessed was over or under. That is not
    what anybody wanted to know.
    """

    def setUp(self):
        self.app = SimpleNamespace(engine_path=ENGINE, workshop_owner_id="owner")

    @staticmethod
    def a_table(material="oak"):
        out = {"kind": "table", "design_id": f"limit-{material}", "purpose": "be stood on",
               "parameters": {}, "component_overrides": {}}
        from mcp import workshop_components
        design, _ = workshop_components.design_from_spec(out)
        out["component_overrides"] = {p.name: {"material": material} for p in design.parts}
        return out

    def test_it_says_where_the_answer_changes(self):
        found = bench.sweep(self.app, self.a_table("oak"), changing="strike_kg",
                            over=[2, 10, 40, 160], seconds=1.5, strike_speed_m_s=12.0)
        print("\n    " + found["says"])
        for row in found["runs"]:
            print(f"      {row['strike_kg']:6.0f} kg -> {row['outcome']}")
        self.assertEqual([2, 10, 40, 160], found["over"])
        self.assertEqual(4, len(found["runs"]))
        # Every row is a real run in a real room, not a number worked out
        # between two other numbers.
        self.assertTrue(all(row["says"] for row in found["runs"]))
        if found["changed_at"] is not None:
            self.assertIn("at", found["says"])
            self.assertEqual(found["changed_at"], found["watching"])
        # And there is one run kept to watch: the one where it changed.
        self.assertGreater(len(found["playback"]["frames"]), 2)

    def test_when_it_holds_all_the_way_it_says_to_look_higher(self):
        found = bench.sweep(self.app, self.a_table("oak"), changing="load_kg",
                            over=[1, 2, 3], seconds=1.0)
        print("    " + found["says"])
        self.assertTrue(found["same_all_the_way"])
        self.assertIsNone(found["changed_at"])
        self.assertIn("try higher", found["says"])
        self.assertEqual(3, found["watching"], "the last one is the one worth watching")

    def test_when_it_gives_way_even_at_the_smallest_it_says_to_look_lower(self):
        """Which way to look is the whole value of the sentence.

        Glass struck at 10 m/s breaks at 5 kg, the least that was tried, so the
        answer is BELOW the range. Saying "past the end of what was tried"
        would send somebody looking in exactly the wrong direction.
        """
        found = bench.sweep(self.app, self.a_table("glass"), changing="strike_kg",
                            over=[5, 20, 80], seconds=1.5, strike_speed_m_s=10.0)
        print("    " + found["says"])
        self.assertTrue(found["same_all_the_way"])
        self.assertIn("try lower", found["says"])
        self.assertIn("even at 5", found["says"])

    def test_a_sweep_is_a_range_of_answers_not_only_a_breaking_point(self):
        """A panel gives nothing in the dark and a lot at noon."""
        found = bench.sweep(self.app, self.a_table("oak"), changing="hour",
                            over=[0, 6, 12], seconds=1.0)
        print("    " + found["says"])
        self.assertEqual([0, 6, 12], found["over"])
        self.assertEqual(3, len(found["runs"]))

    def test_what_a_sweep_refuses(self):
        for over, because in (([1], "2 to 12"), ([1] * 20, "2 to 12"), ([3, 1], "goes up")):
            with self.assertRaises(ValueError) as caught:
                bench.sweep(self.app, self.a_table(), changing="load_kg", over=over)
            self.assertIn(because, str(caught.exception))
        with self.assertRaises(ValueError) as caught:
            bench.sweep(self.app, self.a_table(), changing="the weather", over=[1, 2])
        self.assertIn("turns up one of", str(caught.exception))

    def test_a_sweep_takes_about_a_third_of_a_second_a_run(self):
        """It is only worth doing because it is cheap."""
        import time
        began = time.monotonic()
        bench.sweep(self.app, self.a_table("oak"), changing="load_kg", over=[10, 50, 100, 200],
                    seconds=1.0)
        took = time.monotonic() - began
        print(f"    four runs plus the one to watch took {took:.1f} s")
        self.assertLess(took, 20.0)


@unittest.skipUnless(ENGINE and ENGINE.is_file(), "BANJO_LIVE_ENGINE is required")
class ARoomSomebodyWrote(unittest.TestCase):
    """The owner: "why can't the llm write bits of code to run tests? does it
    need to always be prebuilt?"

    It did. There were four settings -- a weight, a drop, a slide, a thrown
    block -- and a question outside those four could not be asked at all. Now
    the room takes things written into it: what they are made of, how big,
    where, which way up and how fast they are already going.
    """

    def setUp(self):
        self.app = SimpleNamespace(engine_path=ENGINE, workshop_owner_id="owner")

    def test_a_ball_rolls_down_a_ramp_the_model_wrote_and_hits_the_thing(self):
        ramp = {"name": "the ramp", "material": "oak", "size_m": [1.6, 0.06, 0.5],
                "at_m": [-1.6, 0.42, 0.0], "tilt_deg": [0.0, 0.0, 20.0]}
        ball = {"name": "the ball", "shape": "sphere", "material": "iron",
                "size_m": [0.18, 0.18, 0.18], "at_m": [-2.2, 0.75, 0.0],
                "moving_m_s": [0.6, 0.0, 0.0]}
        said = bench.try_it(self.app, TABLE, seconds=4.0, add=[ramp, ball])
        where = said["ended"]["bodies"]
        began = said["began"]["bodies"]
        print("\n    " + said["says"])
        print(f"      the ball went from x={began['the ball']['at_m'][0]:.2f} "
              f"to x={where['the ball']['at_m'][0]:.2f}, "
              f"y={began['the ball']['at_m'][1]:.2f} -> {where['the ball']['at_m'][1]:.2f}")
        self.assertIn("the ramp", where)
        self.assertIn("the ball", where)
        self.assertIn("the ramp", said["in_the_room"])
        # It went downhill and along, which is what a ramp is for.
        self.assertGreater(where["the ball"]["at_m"][0], began["the ball"]["at_m"][0] + 0.3)
        self.assertLess(where["the ball"]["at_m"][1], began["the ball"]["at_m"][1])
        # And it is in the room as a real body, not a number in a config.
        self.assertIn("the ramp", said["says"])

    def test_a_wall_driven_into_the_ground_does_not_move_when_it_is_hit(self):
        wall = {"name": "the wall", "material": "concrete", "size_m": [0.2, 1.2, 1.6],
                "at_m": [1.4, 0.0, 0.0], "fixed": True}
        said = bench.try_it(self.app, TABLE, seconds=2.0, slide_m_s=4.0, add=[wall],
                            record=False)
        wall_now = said["ended"]["bodies"]["the wall"]
        print("    " + said["says"])
        self.assertEqual(0.0, wall_now["speed_m_s"], "driven in, it cannot be shoved")
        self.assertAlmostEqual(1.4, wall_now["at_m"][0], places=2)

    def test_height_is_measured_from_the_ground_not_from_zero(self):
        """0.4 m of soil is not a number anybody should have to know."""
        resting = {"name": "a block", "material": "oak", "size_m": [0.2, 0.2, 0.2],
                   "at_m": [2.0, 0.1, 0.0]}
        said = bench.try_it(self.app, TABLE, seconds=1.0, add=[resting], record=False)
        block = said["began"]["bodies"]["a block"]
        self.assertAlmostEqual(bench.GROUND_M + 0.1, block["at_m"][1], places=3)

    def test_what_it_refuses_says_why(self):
        for thing, because in (
            ({"name": "x", "size_m": [0.2, 0.2, 0.2], "at_m": [0, -1, 0]}, "ABOVE the ground"),
            ({"name": "x", "size_m": [0.2, 0.2, 0.2], "at_m": [0, 0, 0], "material": "cheese"}, "made of one of"),
            ({"name": "x", "size_m": [0.001, 0.2, 0.2], "at_m": [0, 0, 0]}, "every side is"),
            ({"name": "x", "size_m": [0.2, 0.2, 0.2], "at_m": [40, 0, 0]}, "ground is 16 m across"),
            ({"name": "x", "shape": "sphere", "size_m": [0.2, 0.3, 0.2], "at_m": [0, 0, 0]}, "same across"),
            ({"name": "x", "size_m": [0.2, 0.2, 0.2], "at_m": [0, 0, 0], "colour": "red"}, "has no"),
            ({"name": "x", "size_m": [0.2, 0.2, 0.2], "at_m": [0, 0, 0],
              "tilt_deg": [0, 0, 10], "fixed": True}, "cannot be driven into the ground"),
        ):
            with self.assertRaises(ValueError) as caught:
                bench.spec(add=[thing])
            self.assertIn(because, str(caught.exception))
        # And two things cannot share a name, or nothing can be told apart.
        one = {"name": "twin", "size_m": [0.2, 0.2, 0.2], "at_m": [0, 0, 0]}
        with self.assertRaises(ValueError) as caught:
            bench.spec(add=[one, dict(one, at_m=[1, 0, 0])])
        self.assertIn("both called", str(caught.exception))
        with self.assertRaises(ValueError) as caught:
            bench.spec(add=[dict(one, name=f"thing {i}") for i in range(bench.MAX_AUTHORED + 1)])
        self.assertIn("up to 12", str(caught.exception))

    def test_a_tilt_is_a_real_turn_and_it_is_z_first(self):
        """The same order the engine builds rotation_deg in (Rx . Ry . Rz)."""
        flat = bench._turned(None)
        self.assertEqual([1.0, 0.0, 0.0, 0.0], flat)
        quarter = bench._turned([0.0, 0.0, 90.0])
        self.assertAlmostEqual(0.70710678, quarter[0], places=6)
        self.assertAlmostEqual(0.70710678, quarter[3], places=6)
        # Two turns about different axes do not commute, and the order is the
        # engine's: z is applied first, so it is the rightmost factor. A quarter
        # about z then a quarter about x is qx . qz, which is this and not its
        # mirror -- the y term is negative, and the other order makes it
        # positive.
        both = bench._turned([90.0, 0.0, 90.0])
        self.assertAlmostEqual(1.0, sum(v * v for v in both), places=9)
        for wanted, got in zip([0.5, 0.5, -0.5, 0.5], both):
            self.assertAlmostEqual(wanted, got, places=6, msg=both)


    def test_a_bench_refuses_what_is_not_a_bench_test(self):
        for how, why in ((dict(drop_m=50.0), "5 m"), (dict(slide_m_s=90.0), "30 m/s"),
                         (dict(load_kg=9000.0), "2000 kg"),
                         (dict(strike={"kg": 9000.0, "speed_m_s": 1.0}), "500 kg")):
            with self.assertRaises(ValueError) as caught:
                bench.try_it(self.app, TABLE, seconds=1.0, **how)
            self.assertIn(why, str(caught.exception))

if __name__ == "__main__":
    unittest.main()
