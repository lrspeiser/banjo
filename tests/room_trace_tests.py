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
import interaction_trace
from types import SimpleNamespace
from unittest import mock


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

    def test_a_lost_server_is_said_ahead_of_the_clocks(self):
        """Nothing steps the world while the server cannot be reached.

        A room that lost the server for a second reads, in every other number,
        as a room running slow -- so that is said ahead of them, or the next
        reader goes looking in the solver for a lag that was a connection.
        """
        said = self.line(realtime_pct=74, lost_link={
            "times": 1, "longest_ms": 1052, "why": "Failed to fetch", "gave_up": False})
        self.assertTrue(said.startswith("LOST THE SERVER 1x, longest 1052 ms"),
                        f"the line begins {said[:40]!r}")
        self.assertIn("Failed to fetch", said)
        self.assertNotIn("GAVE UP", said)

    def test_a_room_that_gave_up_on_the_server_says_so(self):
        said = self.line(lost_link={"times": 1, "longest_ms": 1180,
                                    "why": "Failed to fetch", "gave_up": True})
        self.assertIn("GAVE UP", said)

    def test_nothing_drawn_is_still_said_before_a_lost_server(self):
        said = self.line(frames=0, fps=0.0, lost_link={
            "times": 2, "longest_ms": 310, "why": "HTTP 503", "gave_up": False})
        self.assertTrue(said.startswith("NOTHING WAS DRAWN"), f"the line begins {said[:40]!r}")
        self.assertIn("LOST THE SERVER 2x", said)


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

    def events(self):
        return [json.loads(line) for line in (self.where/'interaction-events.jsonl').read_text(encoding='utf-8').splitlines()]

    def test_click_and_refused_outcome_are_linked_and_keep_actual_native_coordinates(self):
        self.app.world_id='test-world'
        self.app.live=SimpleNamespace(session=SimpleNamespace(state={'t':12.5,
            'player_hands':{'owner':{'holding':'authored hoe','grip_m':[1,2,3]}},
            'native_players':{'owner':{'position_m':[1,1,3]}}}))
        with interaction_trace.attempt(self.app,'owner',{'interaction_id':'pressed-target-1','at_m':[1,0,4]}):
            interaction_trace.preflight({'enabled':True,'tool':'authored hoe','target':{'at_m':[1,0,4]},
                'ready':{'hand':[1,.5,4]},'ring':{'state':'ok'}})
            interaction_trace.outcome({'refused':'The tool is still moving into position',
                'diagnostics':{'phase':'position','tip_m':[1,.2,3],'tip_gap_m':1.},
                'timing':{'prepare_ms':2000}})
        server.Playground.trace(self.app,{'interactions':[{'event':'tool-press','id':'pressed-target-1',
            'input':'touch','from_m':[1,2,3],'direction':[0,-1,0]}]},'owner')
        rows=self.events()
        self.assertEqual([r['event'] for r in rows],['tool-request','tool-preflight','tool-result','tool-press'])
        self.assertEqual({r['id'] for r in rows},{'pressed-target-1'})
        self.assertEqual({r['actor'] for r in rows},{rows[0]['actor']})
        self.assertEqual(rows[2]['diagnostics']['tip_m'],[1,.2,3])
        self.assertEqual(rows[2]['hand']['holding'],'authored hoe')
        self.assertEqual(rows[3]['source'],'browser')
        self.assertEqual(rows[2]['source'],'server')

    def test_exception_is_logged_even_when_no_browser_response_arrives(self):
        with self.assertRaisesRegex(ValueError,'stale room'):
            with interaction_trace.attempt(self.app,'owner',{'interaction_id':'failed-request'}):
                raise ValueError('stale room')
        rows=self.events()
        self.assertEqual(rows[-1]['status'],'error')
        self.assertEqual(rows[-1]['reason'],'stale room')
        self.assertEqual(rows[-1]['id'],rows[0]['id'])

    def test_pickup_refusal_uses_inventory_request_id_and_keeps_grip(self):
        with interaction_trace.attempt(self.app,'owner',{'request':'pickup-1','op':'take_up',
                'item':'field pick','grip':[1,.8,2]},'inventory'):
            interaction_trace.outcome({'ok':False,'why':'Handle is out of reach'})
        rows=self.events()
        self.assertEqual([r['event'] for r in rows],['inventory-request','inventory-result'])
        self.assertEqual(rows[0]['id'],'pickup-1')
        self.assertEqual(rows[0]['grip_m'],[1,.8,2])
        self.assertEqual(rows[1]['why'],'Handle is out of reach')

    def test_disconnected_browser_preserves_finished_native_outcome(self):
        with self.assertRaises(ConnectionAbortedError):
            with interaction_trace.attempt(self.app,'owner',{'interaction_id':'lost-reply'}):
                interaction_trace.outcome({'result':{'loosened_kg':1.25},'said':'Released'})
                raise ConnectionAbortedError('browser closed')
        rows=self.events()
        self.assertEqual([r['event'] for r in rows],['tool-request','tool-result','tool-delivery-error'])
        self.assertEqual(rows[1]['result']['loosened_kg'],1.25)
        self.assertEqual(rows[2]['id'],rows[1]['id'])

    def test_browser_fields_cannot_spoof_provenance_or_write_secrets(self):
        self.send({'interactions':[{'event':'target-state','source':'server','actor':'spoof',
            'world':'spoof','headers':{'Authorization':'fixture secret'},'token':'fixture token',
            'reason':'Error sk-fixture-secret','diagnostics':{'token':'nested secret','tip_gap_m':.3},
            'elapsed_ms':float('nan'),'at_m':[0,float('inf'),1]}]})
        row=self.events()[0]
        self.assertEqual(row['source'],'browser')
        self.assertNotEqual(row['actor'],'spoof')
        self.assertIsNone(row['world'])
        self.assertEqual(row['reason'],'Error [redacted]')
        self.assertEqual(row['diagnostics'],{'tip_gap_m':.3})
        self.assertNotIn('elapsed_ms',row);self.assertNotIn('at_m',row)
        raw=(self.where/'room-frames.jsonl').read_text(encoding='utf-8')
        self.assertNotIn('interactions',raw);self.assertNotIn('secret',raw)

    def test_event_count_and_file_retention_are_bounded(self):
        self.send({'interactions':[{'event':'target-state','client_ms':i} for i in range(80)]})
        self.assertEqual(len(self.events()),64)
        with mock.patch.object(interaction_trace,'MAX_BYTES',1):
            self.send({'interactions':[{'event':'tool-press','id':'after-rotation'}]})
        self.assertEqual(len(self.events()),1)
        self.assertTrue((self.where/'interaction-events.previous.jsonl').exists())

    def test_failed_logging_does_not_cancel_gameplay_and_warns_once(self):
        with mock.patch.object(Path,'mkdir',side_effect=OSError('read only')):
            with self.assertLogs('banjo',level='WARNING') as logged:
                with interaction_trace.attempt(self.app,'owner',{}):
                    interaction_trace.outcome({'said':'Done'})
        self.assertEqual(len(logged.output),1)

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

    def test_a_lost_server_goes_in_the_log_even_when_the_room_kept_up(self):
        """A short outage leaves the room above 90% and would be filed quietly."""
        with self.assertLogs(level="INFO") as logged:
            self.send({"why": "routine", "watched": True, "frames": 240, "realtime_pct": 97,
                       "frame_ms": {"worst": 20.0}, "objects": 5,
                       "lost_link": {"times": 1, "longest_ms": 160,
                                     "why": "Failed to fetch", "gave_up": False}})
        self.assertTrue(any("LOST THE SERVER" in line for line in logged.output), logged.output)

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



class ChatTransportAccountingIsKept(unittest.TestCase):
    def test_saved_transcript_keeps_full_answers_and_separate_byte_counts(self):
        from tempfile import TemporaryDirectory
        from types import SimpleNamespace
        from unittest.mock import patch
        stats = {"original_json_bytes": 1000, "sent_json_bytes": 100,
                 "saved_json_bytes": 900, "delta_calls": 2}
        actual = {"objects": [{"name": "unchanged"}, {"name": "new"}], "added": "new"}
        trace = [{"calls": [{"name": "add_object", "arguments": {}, "answer": actual}]}]
        answer = {"reply": "Done", "rounds": 1, "tool_transport": stats}
        with TemporaryDirectory() as root, patch.object(server, "ROOT", Path(root)):
            server.remember_chat(SimpleNamespace(api_key=""), "Add one", trace, answer, None, .1)
            files = list((Path(root) / "build/playground-logs/chat").glob("*.json"))
            self.assertEqual(1, len(files))
            stored = json.loads(files[0].read_text())
        self.assertEqual(stats, stored["tool_transport"])
        self.assertEqual(actual, stored["rounds"][0]["calls"][0]["answer"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
