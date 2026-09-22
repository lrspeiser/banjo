"""What a break costs, in a room (docs/what-a-break-costs.md): the room's
failure law reaching the engine, and the account the world gives of a break --
the bonds it removed, the crack they stand for, the energy that left with them,
and what that is per square metre against the material's own.

    BANJO_LIVE_ENGINE=.../banjo_live_world_run.exe python tests/break_room_tests.py

Without BANJO_LIVE_ENGINE only the checks that need no engine run, unless
BANJO_BREAK_LIVE_TESTS=required, which ctest sets.
"""
from __future__ import annotations

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


def break_room() -> dict:
    return world_room.SCENES["tests-break"]()


class TheRoomDeclaresIt(unittest.TestCase):
    """The room's failure law, as validate() keeps it and as the engine is told
    it (scene_document)."""

    def test_the_room_asks_for_the_energy_scaled_law(self):
        room = fracture_lab.validate(break_room())
        self.assertEqual("energy-scaled", room["failure_law"])
        self.assertEqual("energy-scaled", fracture_lab.scene_document(room)["failure_law"])
        [plank] = [b for b in room["bodies"] if b["name"] == "plank"]
        self.assertEqual("oak", plank["material"])

    def test_a_room_that_says_nothing_runs_the_old_law(self):
        room = break_room()
        room.pop("failure_law")
        kept = fracture_lab.validate(room)
        self.assertEqual("strain-threshold", kept["failure_law"])
        self.assertEqual("strain-threshold", fracture_lab.scene_document(kept)["failure_law"])

    def test_a_law_that_is_not_a_law_is_refused(self):
        room = break_room()
        room["failure_law"] = "whatever-breaks"
        with self.assertRaisesRegex(ValueError, "failure_law"):
            fracture_lab.validate(room)


@unittest.skipUnless(ENGINE and ENGINE.is_file(), "BANJO_LIVE_ENGINE is required")
class BreakingIt(unittest.TestCase):
    """The tests-break room opened as the playground opens it: the ball lands,
    the plank is offered, and breaking it says what it cost."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.live = live_session.Live()
        self.addCleanup(self.live.shutdown)
        self.room = world_room.Room("tests-break")
        self.app = SimpleNamespace(live=self.live, live_holder="world", room=self.room, engine_path=ENGINE,
                                   runs_path=root / "runs", store=room_store.RoomStore(root / "rooms"))
        self.live.open(self.app, {"spec": self.room.spec})

    def break_the_plank(self) -> dict:
        for _ in range(200):
            reply = self.live.session.send(op="step", dt=DT, n=12)
            if "plank" in (reply.get("breakable") or []):
                return self.live.session.send(op="fracture", name="plank", wait=True)
        self.fail("the ball never hit the plank hard enough to break it")

    def test_the_break_says_what_it_cost(self):
        broke = self.break_the_plank()
        cost = broke.get("cost") or {}
        print(f"\n    {broke.get('outcome')} into {broke.get('pieces')} pieces: {cost.get('broken_bonds')} bonds "
              f"({cost.get('tensile_bonds')} pulled apart, {cost.get('compressive_bonds')} crushed, "
              f"{cost.get('shear_bonds')} sheared), {cost.get('removed_energy_j')} J over "
              f"{cost.get('crack_area_m2', 0) * 1e4:.0f} cm2: {cost.get('crack_energy_j_m2')} J/m2, "
              f"charged {cost.get('law_energy_j_m2')}", flush=True)
        self.assertEqual("broke", broke.get("outcome"))
        self.assertGreater(broke.get("pieces", 0), 1)
        self.assertEqual("oak", cost.get("material"))
        self.assertEqual("energy-scaled", cost.get("failure_law"))
        # The room charges what oak says a crack costs, because it asked for the
        # law that sets the charge from the material's own fracture energy.
        self.assertEqual(1000.0, cost["declared_energy_j_m2"])
        self.assertAlmostEqual(1000.0, cost["law_energy_j_m2"], places=6)
        self.assertFalse(cost["bounded_by_strength"])
        # And it says what the break actually took.
        self.assertGreater(cost["broken_bonds"], 0)
        self.assertGreater(cost["removed_energy_j"], 0.0)
        self.assertGreater(cost["crack_area_m2"], 0.0)
        self.assertAlmostEqual(cost["removed_energy_j"] / cost["crack_area_m2"], cost["crack_energy_j_m2"],
                               delta=0.01 * cost["crack_energy_j_m2"])
        self.assertEqual(cost["broken_bonds"],
                         cost["tensile_bonds"] + cost["compressive_bonds"] + cost["shear_bonds"])

    def test_a_room_without_the_law_is_charged_by_its_cell_size_instead(self):
        spec = break_room()
        spec.pop("failure_law", None)
        # The same plank under the old law needs 11 m/s to break, not the 2.7 it
        # takes under the energy-scaled one: the law decides what it takes to
        # break a thing as well as what breaking it costs. So the ball is
        # dropped from seven metres instead of a metre and a half.
        [ball] = [b for b in spec["bodies"] if b["name"] == "ball"]
        ball["center_mm"][1] = 7000.0
        self.live.shutdown()
        self.live = live_session.Live()
        self.addCleanup(self.live.shutdown)
        self.app.live = self.live
        self.live.open(self.app, {"spec": spec})            # the room opens it, law and all
        broke = self.break_the_plank()
        cost = broke.get("cost") or {}
        print(f"    without it: charged {cost.get('law_energy_j_m2')} J/m2 where oak takes "
              f"{cost.get('declared_energy_j_m2')}", flush=True)
        self.assertEqual("strain-threshold", cost.get("failure_law"))
        # 148,500 J/m2 at these 20 mm cells, and half that if the cells halved:
        # the charge is the grid's, not the oak's.
        self.assertGreater(cost["law_energy_j_m2"], 100.0 * cost["declared_energy_j_m2"])


if __name__ == "__main__":
    if os.environ.get("BANJO_BREAK_LIVE_TESTS") == "required" and not (ENGINE and ENGINE.is_file()):
        raise RuntimeError("BANJO_LIVE_ENGINE must be built for the required live break tests")
    unittest.main()
