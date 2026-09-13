"""The room writes down what it saw, and the log says the part that matters.

Every lag in this engine so far has been invisible from the server's side. The
world clock stopped while the wall clock ran; the pieces of a broken pane turned
up most of a second after the impact. Both times every server-side number looked
perfect, because every server-side number was measuring the clock.

Only the page can see its own frames, so the page sends them here. These check
that the line written to the log carries the three things that have each caught
a lag the other two missed -- and, just as important, that a report from a room
nobody was looking at says so first, because a browser throttles a tab it is not
showing and that reads exactly like a catastrophic lag.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "playground"))

import server  # noqa: E402


class TheLineWrittenToTheLog(unittest.TestCase):
    def line(self, **over) -> str:
        report = {
            "why": "routine", "watched": True, "wall_s": 4.0, "world_s": 4.0,
            "realtime_pct": 100, "frames": 240, "fps": 60.0,
            "frame_ms": {"median": 16.6, "p95": 18.0, "worst": 21.0},
            "slow_frames": [], "step_ms": {"median": 4.0, "p95": 9.0, "worst": 12.0},
            "reply_kb": 0.2, "worst_reply_kb": 42, "breaks": [], "objects": 58,
        }
        report.update(over)
        return server.trace_line(report)

    def test_it_carries_the_two_clocks(self):
        """A world that has stopped reads 0% while everything else looks fine.

        This is the pair that caught the stalled clock: how much of the scene's
        own time went by against how much real time did.
        """
        said = self.line(realtime_pct=38)
        self.assertIn("38% of realtime", said)

    def test_a_clock_that_went_back_is_not_printed_as_a_percentage(self):
        """A world's clock only runs forward.

        Less than nothing means the report spanned two worlds: the room was
        started again, or the chat rebuilt it, and a page that kept its old
        baseline took the old world's clock from the new one's. The log said
        "room: -358% of realtime", which reads as a measurement and is not one.
        """
        said = self.line(world_s=-14.33, realtime_pct=-358)
        self.assertTrue(said.startswith("room: the world was replaced during this report"),
                        f"the line begins {said[:60]!r}")
        self.assertNotIn("-358", said)
        self.assertNotIn("% of realtime", said)

    def test_a_clock_that_went_back_a_little_is_not_a_stopped_one(self):
        """A little less than nothing rounds to 0%, the figure for a stopped clock.

        The seconds say which it was.
        """
        said = self.line(world_s=-0.01, realtime_pct=0)
        self.assertIn("the world was replaced during this report", said)
        self.assertNotIn("0% of realtime", said)

    def test_it_carries_the_worst_frame(self):
        said = self.line(frame_ms={"median": 16.6, "p95": 40.0, "worst": 310.0})
        self.assertIn("worst frame 310.0 ms", said)

    def test_it_carries_how_late_a_break_was(self):
        """The one a person actually complains about.

        The room can run at 99% of real time and still take most of a second
        between the thing landing and the thing coming apart. No measurement on
        the server's side can see that at all.
        """
        said = self.line(breaks=[{"name": "glass plate 20mm", "outcome": "broke",
                                  "pieces": 74, "impact_to_pieces_ms": 856}])
        self.assertIn("glass plate 20mm broke into 74", said)
        self.assertIn("856 ms after the impact", said)

    def test_a_break_with_no_time_still_gets_named(self):
        said = self.line(breaks=[{"name": "pane", "outcome": "held", "pieces": 1,
                                  "impact_to_pieces_ms": None}])
        self.assertIn("pane held into 1", said)
        self.assertNotIn("after the impact", said)

    def test_it_names_the_worst_slow_frame_and_what_was_happening(self):
        said = self.line(slow_frames=[
            {"ms": 70, "at_s": 1.0, "objects": 58, "fading": 0, "doing": "carrying something"},
            {"ms": 240, "at_s": 2.0, "objects": 132, "fading": 0,
             "doing": "a break is being worked out"}])
        self.assertIn("2 slow frames", said)
        self.assertIn("worst 240 ms", said)
        self.assertIn("a break is being worked out", said)

    def test_a_room_nobody_was_looking_at_says_so_first(self):
        """Nothing drawn means the frame numbers mean nothing.

        `document.hidden` is the obvious test and it is not enough: a pane can
        be off screen in a way that stops the drawing without ever setting it.
        Zero frames is the honest one, and it has to be the FIRST thing said or
        somebody reads the numbers after it and chases a lag that never
        happened. That cost this project two wrong diagnoses.
        """
        said = self.line(frames=0, fps=0.0,
                         frame_ms={"median": None, "p95": None, "worst": 10205.6})
        self.assertTrue(said.startswith("NOTHING WAS DRAWN"),
                        f"the line begins {said[:40]!r}, so the warning is not first")
        self.assertIn("mean nothing", said)


class TheEndpointThatReceivesThem(unittest.TestCase):
    class Fake:
        """Just enough of the app for trace() -- it only files and logs."""
        def __init__(self, where: Path) -> None:
            self.runs_path = where

    def setUp(self) -> None:
        import tempfile
        self._dir = tempfile.TemporaryDirectory()
        self.where = Path(self._dir.name)
        self.app = self.Fake(self.where)

    def tearDown(self) -> None:
        self._dir.cleanup()

    def send(self, body):
        return server.Playground.trace(self.app, body)

    def test_a_report_is_filed_where_it_can_be_read_back(self):
        self.assertEqual(self.send({"why": "routine", "frames": 10, "objects": 5}), {"ok": True})
        filed = (self.where / "room-frames.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(filed), 1)
        row = json.loads(filed[0])
        self.assertEqual(row["objects"], 5)
        self.assertIn("at", row, "a report with no time on it cannot be lined up with anything")

    def test_reports_accumulate_rather_than_replacing_each_other(self):
        for i in range(3):
            self.send({"why": "routine", "objects": i})
        filed = (self.where / "room-frames.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual([json.loads(r)["objects"] for r in filed], [0, 1, 2])

    def test_it_refuses_what_is_not_a_report(self):
        with self.assertRaises(ValueError):
            self.send("frames were slow")

    def test_it_refuses_one_too_big_to_be_worth_having(self):
        """The page writes this, so it is capped like anything else the page sends."""
        with self.assertRaises(ValueError):
            self.send({"why": "routine", "slow_frames": ["x" * 200] * 1000})

    def test_a_room_that_fell_behind_is_said_out_loud(self):
        """Under 90% of realtime, while somebody was watching, is a lag."""
        with self.assertLogs(level="INFO") as logged:
            self.send({"why": "routine", "watched": True, "frames": 240, "realtime_pct": 74,
                       "world_s": 2.96, "frame_ms": {"worst": 20.0}, "objects": 58})
        self.assertTrue(any("74% of realtime" in line for line in logged.output), logged.output)

    def test_a_replaced_world_is_not_said_out_loud_as_a_room_falling_behind(self):
        """Less than nothing is not "under 90%": it is two worlds in one report.

        It is filed like any other report, and kept out of the line that is
        said out loud for a room that is really running slow -- which is where
        "-358% of realtime" turned up.
        """
        with self.assertNoLogs(level="INFO"):
            self.send({"why": "routine", "watched": True, "frames": 240, "realtime_pct": -358,
                       "world_s": -14.33, "frame_ms": {"worst": 20.0}, "objects": 58})
        filed = (self.where / "room-frames.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(json.loads(filed[-1])["realtime_pct"], -358, "filed as it was sent")


if __name__ == "__main__":
    unittest.main(verbosity=2)
