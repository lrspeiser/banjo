"""What has been seen, and what has not (docs/machine-world.md, "What has been
seen"): the room's record of it, what reveals it, how a machine's senses are
held to it, and what a survey says of a place nobody has been.

    BANJO_LIVE_ENGINE=.../banjo_live_world_run.exe python tests/sight_tests.py
"""
from __future__ import annotations

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
import mcp  # noqa: E402,F401
import inventory, live_session, machine_senses, machine_sight, machine_tools  # noqa: E402
import machine_routine, room_store, rover_brain  # noqa: E402

ENGINE = Path(os.environ["BANJO_LIVE_ENGINE"]).resolve() if os.environ.get("BANJO_LIVE_ENGINE") else None
DT = 1 / 240
MINE = ROOT / "playground" / "rooms" / "tests-mine.json"


class TheRecord(unittest.TestCase):
    def room(self):
        return {"cell_m": 0.05, "bodies": [],
                "terrain": {"generate": {"kind": "basin", "cell_m": 0.25, "nx": 128, "nz": 128}}}

    def test_a_room_opens_knowing_nothing_and_learns_where_someone_has_been(self):
        spec = self.room()
        sight = machine_sight.Sight(spec)
        self.assertEqual((32, 32, 1.0), (sight.nx, sight.nz, sight.cell_m), "a metre a cell over the room")
        self.assertEqual(0, sight.known_cells(), "nobody has been anywhere")
        self.assertFalse(sight.knows(0.0, 0.0))
        self.assertTrue(sight.knows(400.0, 0.0), "ground outside the room has nothing to find out")
        self.assertNotIn("sight", spec, "and nothing is written into the room until something is seen")
        # Being somewhere is what reveals it, and only round there.
        first = sight.reveal(0.0, 0.0, machine_sight.SIGHT_M)
        self.assertGreater(first, 50)
        self.assertTrue(sight.knows(0.0, 0.0))
        self.assertTrue(sight.knows(5.0, 0.0))
        self.assertFalse(sight.knows(0.0, 9.0), "and no further than it can see")
        self.assertEqual(0, sight.reveal(0.0, 0.0, machine_sight.SIGHT_M), "seeing it again finds nothing new")
        self.assertIn("sight", spec, "what has been seen is kept with the room")

    def test_height_is_what_a_scout_is_for(self):
        on_the_ground = machine_sight.sight_m(0.3)
        hovering = machine_sight.sight_m(1.8)
        high = machine_sight.sight_m(10.0)
        self.assertLess(on_the_ground, hovering)
        self.assertLess(hovering, high)
        self.assertGreater(high / on_the_ground, 3.0, "ten metres up is worth flying to")
        self.assertEqual(machine_sight.sight_m(60.0), machine_sight.sight_m(200.0), "and there is a limit to it")
        self.assertGreater((high / on_the_ground) ** 2, 8.0, "and it takes in eight times the ground")
        # Which is the whole difference between a rover and a drone in the same
        # spot. Over a room only 32 m across a drone at ten metres takes in most
        # of it, so the count is compared inside the room it has.
        ground, air = machine_sight.Sight(self.room()), machine_sight.Sight(self.room())
        ground.reveal(0.0, 0.0, on_the_ground)
        air.reveal(0.0, 0.0, high)
        self.assertGreater(air.known_cells(), 6 * ground.known_cells())

    def test_what_a_room_has_seen_is_kept_and_read_back(self):
        spec = self.room()
        sight = machine_sight.Sight(spec)
        sight.reveal(4.0, -4.0, 5.0)
        known = sight.known_cells()
        # Through the checker the room's validator puts it through, as a room is
        # when it is opened again.
        carried = json.loads(json.dumps(spec))
        carried["sight"] = machine_sight.checked(carried["sight"])
        checked = carried
        again = machine_sight.Sight(checked)
        self.assertEqual(known, again.known_cells())
        self.assertTrue(again.knows(4.0, -4.0))
        self.assertFalse(again.knows(-10.0, 10.0))
        # And it is not part of what the world is MADE of: a world saved after
        # machines have learned the room still opens into that room.
        bare = {k: v for k, v in checked.items() if k != "sight"}
        self.assertEqual(live_session.spec_digest(bare), live_session.spec_digest(checked))

    def test_a_record_the_room_declares_badly_is_refused(self):
        for bad, why in (({"nx": 0}, "1 to 4000"), ({"cell_m": 99.0}, "out of range"),
                         ({"seen_b64": "not base64!"}, "not base64"),
                         ({"nx": 4, "nz": 4, "seen_b64": "AAAA"}, "bytes, not the")):
            with self.subTest(why=why), self.assertRaisesRegex(ValueError, why):
                machine_sight.checked(bad)


class WhatAMachineKnows(unittest.TestCase):
    """A machine's senses answer about ground someone has been to, and no more."""

    def context(self, sight):
        spec = {"goods": {"deposits": [{"name": "near vein", "at_m": [3.0, 0.0], "substance": "copper ore",
                                        "grade": 0.3, "reserve_kg": 100.0, "radius_m": 1.0},
                                       {"name": "far vein", "at_m": [40.0, 0.0], "substance": "iron ore",
                                        "grade": 0.3, "reserve_kg": 100.0, "radius_m": 1.0}],
                          "stockpiles": [{"name": "depot", "at_m": [-40.0, 0.0], "radius_m": 1.0}]}}
        import machine_goods
        goods = machine_goods.Goods(spec)
        program = {"id": 1, "power": True, "at_m": [0.0, 0.3, 0.0], "heading_deg": 0.0, "sensors": [],
                   "kind": "roam", "parts": [], "body": "rover"}
        return machine_senses.Context(program=program, goods=goods, sight=sight, bodies=[],
                                      ask=lambda **c: {"survey": {"on_the_ground": True, "ground_m": 0.5,
                                                                  "surface": "soil", "slope_deg": 2.0}})

    def test_the_senses_hand_it_only_the_goods_it_has_seen(self):
        spec = {"terrain": {"generate": {"cell_m": 0.5, "nx": 200, "nz": 200}}}
        sight = machine_sight.Sight(spec)
        ctx = self.context(sight)
        # Nothing seen: the room's document says there are three, and the machine
        # knows of none of them.
        blind = machine_senses.sense_goods(ctx)
        self.assertEqual(([], []), ([d["name"] for d in blind["deposits"]], [s["name"] for s in blind["stockpiles"]]))
        self.assertEqual((2, 1), (blind["deposits_not_seen"], blind["stockpiles_not_seen"]))
        self.assertEqual(0.0, blind["room_seen_share"])
        # Been there: the near one, and still not the far one.
        sight.reveal(0.0, 0.0, 8.0)
        knows = machine_senses.sense_goods(ctx)
        self.assertEqual(["near vein"], [d["name"] for d in knows["deposits"]])
        self.assertEqual(1, knows["deposits_not_seen"])
        self.assertEqual([], knows["stockpiles"], "the depot is 40 m off and still unknown")
        self.assertEqual(1, knows["stockpiles_not_seen"])
        self.assertGreater(knows["room_seen_share"], 0.0)
        # A room with no record at all is a room that keeps no fog: everything.
        open_book = machine_senses.sense_goods(self.context(None))
        self.assertEqual(2, len(open_book["deposits"]))
        self.assertNotIn("room_seen_share", open_book)

    def test_a_survey_says_what_is_known_of_a_place_and_what_is_not(self):
        spec = {"terrain": {"generate": {"cell_m": 0.5, "nx": 200, "nz": 200}}}
        sight = machine_sight.Sight(spec)
        ctx = self.context(sight)
        ctx.routine = machine_routine.Routine("rover", {"kind": "custom", "hopper_kg": 10.0,
                                                        "places": {"yonder": [30.0, 0.0]},
                                                        "steps": [{"do": "hold_still", "until": 1}]})
        # Where nobody has been: it says so, rather than reading the answer out
        # of the room's document.
        did = machine_tools.run(ctx, machine_tools.Call("survey", {"place": "yonder"}, "probe"))
        self.assertIn("nobody has been near it", did["did"])
        self.assertEqual(0, did["spots_read"])
        self.assertGreater(did["spots_not_seen"], 0)
        self.assertEqual([], did["deposits"])
        # Where it stands, once it has been standing there.
        sight.reveal(0.0, 0.0, 8.0)
        did = machine_tools.run(ctx, machine_tools.Call("survey", {}, "probe"))
        self.assertIn("surveyed where it stands", did["did"])
        self.assertEqual(1.0, did["known_share"])
        self.assertEqual("soil", did["ground"]["surface"])
        self.assertEqual(["near vein"], [d["name"] for d in did["deposits"]])
        self.assertIn("near vein", did["did"])
        # Surveying does not reveal: asking about somewhere far off leaves it
        # exactly as unknown as it was.
        was = sight.known_cells()
        machine_tools.run(ctx, machine_tools.Call("survey", {"place": "yonder", "radius_m": 10.0}, "probe"))
        self.assertEqual(was, sight.known_cells(), "a survey reports; going there is what reveals it")


@unittest.skipUnless(ENGINE and ENGINE.is_file(), "BANJO_LIVE_ENGINE must be built")
class InTheRealEngine(unittest.TestCase):
    """The record over a real room's real terrain, learned by real machines."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.spec = json.loads(MINE.read_text(encoding="utf-8"))
        self.live = live_session.Live()
        self.brains = rover_brain.Brains(lambda: None)
        self.room = SimpleNamespace(scene="tests-mine", spec=self.spec, chat=[],
                                    inventory=inventory.Inventory(), workshop_installs=[])
        self.app = SimpleNamespace(live=self.live, live_holder="world", room=self.room, engine_path=ENGINE,
                                   runs_path=root / "runs", store=room_store.RoomStore(root / "rooms"),
                                   brains=self.brains, api_key="", model="",
                                   on_live_reply=lambda session, reply: self.brains.listen(session, reply))

    def tearDown(self):
        self.live.shutdown()
        self.tmp.cleanup()

    def test_the_record_lies_over_the_grid_the_engine_reports(self):
        """The record works out its grid from the terrain the room declares, and
        the engine lays a generated field's vertices on the origin. If that ever
        stops being true, what is known would not line up with what there is."""
        opened = self.live.open(self.app, {"spec": self.spec})
        grid = (opened.get("terrain") or {}).get("grid") or {}
        sight = machine_sight.Sight(self.spec)
        self.assertAlmostEqual(float(grid["x0_m"]), sight.x0_m, places=6)
        self.assertAlmostEqual(float(grid["z0_m"]), sight.z0_m, places=6)
        span = (int(grid["nx"]) - 1) * float(grid["cell_m"])
        self.assertAlmostEqual(span, sight.nx * sight.cell_m, delta=sight.cell_m)

    def test_machines_uncover_the_room_as_they_get_about_it(self):
        self.live.open(self.app, {"spec": self.spec})
        self.brains.opened(self.spec)
        sight = self.brains.sight
        self.assertEqual(0, sight.known_cells(), "the mine opens with nobody having been anywhere")
        sid = self.live.session.id
        programs = self.live.session.send(op="step", dt=DT, n=1)["machines"]["programs"]
        for seq, p in enumerate(programs, 1):
            self.live.session.send(op="run", program=p["id"], sender="test", seq=seq, power=True)
        first, seen = None, []
        for _ in range(60 * 4):                      # a minute
            body = {"session": sid, "op": "step", "dt": DT, "n": 60}
            self.brains.before(self.app, body)
            answer = self.live.act(body)
            self.brains.attach(body, answer)
            if first is None:
                first = answer.get("sight")
            seen.append(sight.known_cells())
        print(f"\n    the mine: {seen[0]} cells known after a step, {seen[-1]} of {len(sight.seen)} after a minute "
              f"({100 * sight.share():.0f}% of the room)")
        self.assertGreater(seen[0], 100, "the machines see where they stand at once")
        self.assertGreater(seen[-1], seen[0], "and more of it as they get about")
        self.assertLess(sight.share(), 0.95, "a minute is not the whole room")
        # The answer carries it, so the page can draw the ground that is known.
        self.assertEqual({"cell_m", "x0_m", "z0_m", "nx", "nz", "seen_b64", "known_cells", "cells"},
                         set(first) - {"found_cells"})
        # And it is kept with the room.
        self.assertIn("sight", self.spec)
        again = machine_sight.Sight(json.loads(json.dumps(self.spec)))
        self.assertEqual(sight.known_cells(), again.known_cells())

    def test_a_machine_surveys_the_ground_it_is_working(self):
        self.live.open(self.app, {"spec": self.spec})
        self.brains.opened(self.spec)
        sid = self.live.session.id
        programs = self.live.session.send(op="step", dt=DT, n=1)["machines"]["programs"]
        for seq, p in enumerate(programs, 1):
            self.live.session.send(op="run", program=p["id"], sender="test", seq=seq, power=True)
        for _ in range(40):
            body = {"session": sid, "op": "step", "dt": DT, "n": 60}
            self.brains.before(self.app, body)
            answer = self.live.act(body)
            self.brains.attach(body, answer)
        ctx = self.brains.of("rover").context(lambda **c: self.live.act({"session": sid, **c}))
        here = machine_tools.run(ctx, machine_tools.Call("survey", {}, "test"))
        print(f"    {here['did'][:150]}")
        self.assertEqual(1.0, here["known_share"], "it has seen where it is standing")
        self.assertIn("ground", here)
        self.assertIn(here["ground"]["surface"], ("soil", "sand", "rock"))
        far = machine_tools.run(ctx, machine_tools.Call("survey", {"point": [-14.0, 14.0]}, "test"))
        print(f"    {far['did'][:150]}")
        self.assertEqual(0, far["spots_read"], "and not the far corner of the room")


if __name__ == "__main__":
    unittest.main()
