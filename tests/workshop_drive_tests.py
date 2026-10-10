"""Driving a thing at the bench with the keys (docs/workshop-mode.md, "Drive
it"; playground/workshop_drive.py): a little world kept open on the server,
the keys put to the thing's program as the asks a panel makes, stepped as
they arrive, every frame sent back, and the whole drive handed back as a
recording when the person lets go.

    BANJO_LIVE_ENGINE=.../banjo_live_world_run.exe python tests/workshop_drive_tests.py
"""
from __future__ import annotations

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
from mcp import workshop as w  # noqa: E402
import workshop_drive  # noqa: E402

ENGINE = Path(os.environ["BANJO_LIVE_ENGINE"]).resolve() if os.environ.get("BANJO_LIVE_ENGINE") else None


def candidate(kind: str) -> dict:
    design = w.assemble(kind, design_id=kind)
    return {"kind": kind, "design_id": kind, "parameters": {}, "component_overrides": design.lineage["component_overrides"]}


class TheHandler(unittest.TestCase):
    def test_a_step_or_a_stop_with_nothing_driven_says_so(self):
        app = SimpleNamespace(engine_path=ENGINE, runs_path=Path(tempfile.mkdtemp()) / "runs", workshop_owner_id="owner")
        with self.assertRaisesRegex(ValueError, "start first"):
            workshop_drive.step(app, {"keys": {"forward": True}})
        self.assertEqual("stopped", workshop_drive.stop(app)["status"])
        with self.assertRaisesRegex(ValueError, "start, step or stop"):
            workshop_drive.handle(app, {"action": "fly"})
        with self.assertRaisesRegex(ValueError, "candidate"):
            workshop_drive.start(app, {})


@unittest.skipUnless(ENGINE and ENGINE.is_file(), "BANJO_LIVE_ENGINE is required")
class DrivingTheRover(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = SimpleNamespace(engine_path=ENGINE, runs_path=Path(self.tmp.name) / "runs", workshop_owner_id="owner")
        self.addCleanup(lambda: workshop_drive.stop(self.app))

    def test_the_keys_move_it_and_the_drive_is_a_recording(self):
        began = workshop_drive.handle(self.app, {"action": "start", "candidate": candidate("rover")})
        self.assertEqual(("driving", "program", "roam"), (began["status"], began["steers"], began["kind"]))
        self.assertGreaterEqual(len(began["recording"]["frames"]), 2, "a recording before the first step")
        first = None
        for _ in range(16):                       # 2 s, forward
            said = workshop_drive.handle(self.app, {"action": "step", "keys": {"forward": True}, "dt_s": 0.125})
            first = first or said["at_m"]
        self.assertEqual(("going forward", "the person at the keys"), (said["doing"], said["why"]))
        self.assertGreater(len(said["frames"]), 0, "each step brings its frames")
        self.assertGreater(math.dist(said["at_m"], first), 1.0, "it went forward")
        heading_before = said["turn_deg"]
        for _ in range(16):                       # 2 s, turning
            said = workshop_drive.handle(self.app, {"action": "step", "keys": {"left": True}, "dt_s": 0.125})
        self.assertEqual("turning left", said["doing"])
        self.assertGreater(said["turn_deg"], heading_before + 5.0, "it turned")
        # Round past half a right angle on its wheels is still standing: it is
        # tipping that is falling over, not turning (it said "it fell over").
        for _ in range(48):
            if said["turn_deg"] > 60.0:
                break
            said = workshop_drive.handle(self.app, {"action": "step", "keys": {"left": True}, "dt_s": 0.125})
        self.assertGreater(said["turn_deg"], 60.0, "it turned round")
        self.assertFalse(said["fell_over"], "turned, not tipped")
        said = workshop_drive.handle(self.app, {"action": "step", "keys": {}, "dt_s": 0.125})
        self.assertEqual("waiting", said["asked"], "no keys: it holds")
        ended = workshop_drive.handle(self.app, {"action": "stop"})
        print(f"\n    {ended['says']}; {len(ended['recording']['frames'])} frames")
        self.assertEqual("stopped", ended["status"])
        self.assertNotIn("fell over", ended["says"])
        self.assertEqual("drive", ended["recording"]["test"])
        self.assertGreater(ended["moved_m"], 1.0)
        self.assertGreater(len(ended["recording"]["frames"]), 60)
        self.assertIsNone(getattr(self.app, "workshop_drive", None))
        # A second start after a stop is a fresh room.
        again = workshop_drive.handle(self.app, {"action": "start", "candidate": candidate("rover")})
        self.assertEqual("driving", again["status"])

    def test_the_drone_is_driven_by_the_same_asks_and_rises_on_the_up_key(self):
        began = workshop_drive.handle(self.app, {"action": "start", "candidate": candidate("drone")})
        self.assertEqual(("program", "hover", True), (began["steers"], began["kind"], began["flies"]))
        self.assertEqual(("Space", "Shift+Space"), (began["keys"]["up"], began["keys"]["down"]))
        for _ in range(24):                       # 3 s: it lifts, then goes
            said = workshop_drive.handle(self.app, {"action": "step", "keys": {"forward": True}, "dt_s": 0.125})
        self.assertEqual("going forward", said["doing"])
        self.assertGreater(said["at_m"][1], began["recording"]["frames"][0]["bodies"][0]["position_m"][1] + 0.5, "in the air")
        # Up: it climbs, and holds the height it got to when the key comes up.
        was = said["at_m"][1]
        for _ in range(24):                       # 3 s of Space
            said = workshop_drive.handle(self.app, {"action": "step", "keys": {"up": True}, "dt_s": 0.125})
        self.assertEqual("rising", said["doing"])
        rose = said["at_m"][1]
        self.assertGreater(rose, was + 1.0, "it climbed")
        for _ in range(12):
            said = workshop_drive.handle(self.app, {"action": "step", "keys": {}, "dt_s": 0.125})
        self.assertEqual("waiting", said["doing"])
        self.assertLess(abs(said["at_m"][1] - rose), 0.6, "it holds the height it rose to")
        # Down, and up beats forward while it is held.
        for _ in range(24):
            said = workshop_drive.handle(self.app, {"action": "step", "keys": {"down": True, "forward": True}, "dt_s": 0.125})
        self.assertEqual("descending", said["doing"])
        self.assertLess(said["at_m"][1], rose - 1.0, "it came down")

    def test_a_rover_is_not_asked_to_rise(self):
        """Rising is a flying machine's: the key does nothing to a rover, and
        the engine refuses the ask outright."""
        began = workshop_drive.handle(self.app, {"action": "start", "candidate": candidate("rover")})
        self.assertFalse(began["flies"])
        self.assertNotIn("up", began["keys"])
        said = workshop_drive.handle(self.app, {"action": "step", "keys": {"up": True}, "dt_s": 0.125})
        self.assertEqual("waiting", said["asked"], "the up key is nothing to a machine on wheels")
        said = workshop_drive.handle(self.app, {"action": "step", "keys": {"up": True, "forward": True}, "dt_s": 0.125})
        self.assertEqual("going forward", said["asked"], "and the keys under it still work")
        drive = getattr(self.app, "workshop_drive")
        with self.assertRaisesRegex(Exception, "only a machine that flies"):
            drive.room.live.session.send(op="behave", program=drive.programs[0]["id"], sender="test",
                                         seq=999, doing="rising", for_s=0.0, why="a rover cannot")


if __name__ == "__main__":
    if os.environ.get("BANJO_ROVER_LIVE_TESTS") == "required" and not (ENGINE and ENGINE.is_file()):
        raise RuntimeError("BANJO_LIVE_ENGINE must be built for the required live drive tests")
    unittest.main()
