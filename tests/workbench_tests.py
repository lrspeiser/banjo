"""The workbench: the lab's recorded runs, listed for the world page to play
back on a bench in the room.

    python tests/workbench_tests.py -v

The world page lists runs from GET /api/runs and sets one out with the two
calls the lab page already makes: GET /api/jobs/<id>, which registers the job's
recordings, then GET /api/jobs/<id>/playback/0 (playground/workbench.js). These
tests put job folders on disk the way the lab leaves them -- beside the live
rooms' folders, which are not runs -- and read them back through a server.
They also check that the lab page is told when the world page holds the one
live world, so that it does not take the room over by itself when it loads.
They hold a stand-in for the live world, so they need no engine and no model.
"""
from __future__ import annotations

import http.client
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import threading
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "playground"))

from playground_tests import PlaygroundTestCase, playground_server  # noqa: E402
from room_store_tests import StandInLive  # noqa: E402
import room_store  # noqa: E402

# A recording as the lab writes one: its bodies once, then frames of poses.
RECORDING = {
    "schema": "banjo.playback.v1", "units": "SI", "status": "complete",
    "bodies": [{"id": "whole:0", "shape": "box", "dimensions_m": [0.32, 0.04, 0.32],
                "color_rgba": 0x9FD3FFFF, "material_id": "glass panel (glass)",
                "element_id": 0, "object_id": 100}],
    "supports": [[[-1.0, 0.0, -1.0], [1.0, 0.0, -1.0], [1.0, 0.0, 1.0]],
                 [[-1.0, 0.0, -1.0], [1.0, 0.0, 1.0], [-1.0, 0.0, 1.0]]],
    "frames": [{"time_s": 0.0, "phase": "settle", "fracture_count": 0, "bonds": [],
                "poses": [{"id": "whole:0", "component_id": 0, "position_m": [0.0, 0.02, 0.0],
                           "orientation_wxyz": [1.0, 0.0, 0.0, 0.0]}]}],
}
MESSAGE = "Explicit lattice, parallel: 2496 cells in 0.444 s wall, 0.22x of the simulated interaction."


def put_job(runs, job_id, *, name="12 objects, 2496 cells at 20 mm: glass panel (glass)",
            status="complete", experiment=None, recorded=True, recording=True, when=None, cases=1):
    """A job folder as the lab leaves one: job.json, and each case's recording."""
    folder = runs / job_id
    folder.mkdir(parents=True)
    job = {"id": job_id, "status": status, "message": MESSAGE,
           "plan": {"experiment": experiment} if experiment else None,
           "cases": [{"index": i, "name": name if i == 0 else f"{name}, case {i}", "status": status,
                      "playback_available": recorded} for i in range(cases)],
           "warnings": [], "timing": {}}
    (folder / "job.json").write_text(json.dumps(job), encoding="utf-8")
    if recording:
        for i in range(cases):
            (folder / f"playback-{i:02d}.json").write_text(json.dumps(RECORDING), encoding="utf-8")
    if when is not None:
        os.utime(folder / "job.json", (when, when))
    return folder


class WorkbenchTestCase(PlaygroundTestCase):
    def start(self):
        """A server as `main` makes one, with a stand-in for the live world."""
        app = self.make_app(mock.Mock())
        app.store = room_store.RoomStore(self.base / "rooms")
        app.live = StandInLive()
        app.runs_path.mkdir(parents=True, exist_ok=True)
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), playground_server.Handler)
        httpd.app = app
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()

        def stop():
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=3)
        self.addCleanup(stop)
        app.port = httpd.server_port
        return app

    def request(self, app, method, path, body=None):
        connection = http.client.HTTPConnection("127.0.0.1", app.port, timeout=60)
        try:
            headers = {"X-Banjo-Token": app.csrf_token}
            if body is not None:
                headers["Content-Type"] = "application/json"
            connection.request(method, path, body=None if body is None else json.dumps(body),
                               headers=headers)
            response = connection.getresponse()
            return response.status, response.getheader("Content-Type") or "", response.read()
        finally:
            connection.close()

    def get(self, app, path):
        status, _, raw = self.request(app, "GET", path)
        self.assertEqual(status, 200, raw[:300])
        return json.loads(raw)

    def post(self, app, path, body):
        status, _, raw = self.request(app, "POST", path, body)
        self.assertEqual(status, 200, raw[:300])
        return json.loads(raw)


class TheRunsOnDisk(WorkbenchTestCase):
    def test_runs_are_listed_newest_first_with_what_the_bench_needs(self):
        app = self.start()
        put_job(app.runs_path, "a" * 32, when=1_700_000_000)
        newer = put_job(app.runs_path, "b" * 32, name="1 object: iron ball (iron)", when=1_700_000_600)
        runs = self.get(app, "/api/runs")["runs"]
        self.assertEqual([(run["id"], run["case"]) for run in runs], [("b" * 32, 0), ("a" * 32, 0)])
        self.assertEqual(runs[0]["title"], "1 object: iron ball (iron)")
        self.assertEqual(runs[0]["status"], "complete")
        self.assertEqual(runs[0]["saved_unix_s"], 1_700_000_600)
        self.assertEqual(runs[0]["recording_bytes"], (newer / "playback-00.json").stat().st_size)
        self.assertEqual(runs[0]["message"], MESSAGE)

    def test_what_is_not_a_run_of_bodies_moving_is_not_listed(self):
        app = self.start()
        put_job(app.runs_path, "c" * 32)                  # the one run
        live = app.runs_path / "live-20260913-120000-1"   # a live room's folder, beside the runs
        live.mkdir()
        (live / "job.json").write_text(json.dumps({"id": "live"}), encoding="utf-8")
        put_job(app.runs_path, "d" * 32, experiment="thermal_material_experiment")   # heat, not bodies
        put_job(app.runs_path, "e" * 32, recorded=False)  # the case recorded nothing
        put_job(app.runs_path, "f" * 32, recording=False)  # said it did, but the file is gone
        put_job(app.runs_path, "1" * 32, status="running")  # not finished
        broken = app.runs_path / ("2" * 32)
        broken.mkdir()
        (broken / "job.json").write_text("{ not json", encoding="utf-8")
        misnamed = put_job(app.runs_path, "3" * 32)
        job = json.loads((misnamed / "job.json").read_text(encoding="utf-8"))
        job["id"] = "4" * 32                              # a job file that is not this folder's
        (misnamed / "job.json").write_text(json.dumps(job), encoding="utf-8")
        self.assertEqual([run["id"] for run in self.get(app, "/api/runs")["runs"]], ["c" * 32])

    def test_each_recorded_case_is_a_run_of_its_own(self):
        app = self.start()
        job = "6" * 32
        put_job(app.runs_path, job, name="glass panel", cases=3)
        (app.runs_path / job / "playback-01.json").unlink()   # the second case recorded nothing
        runs = self.get(app, "/api/runs")["runs"]
        self.assertEqual([(run["id"], run["case"], run["title"]) for run in runs],
                         [(job, 0, "glass panel"), (job, 2, "glass panel, case 2")])
        self.get(app, f"/api/jobs/{job}")
        self.assertEqual(self.get(app, f"/api/jobs/{job}/playback/2")["schema"], "banjo.playback.v1")

    def test_with_no_runs_folder_there_are_no_runs(self):
        app = self.start()
        app.runs_path = self.base / "nowhere"
        self.assertEqual(self.get(app, "/api/runs"), {"runs": []})

    def test_a_listed_run_is_set_out_by_the_calls_the_lab_page_makes(self):
        app = self.start()
        put_job(app.runs_path, "5" * 32)
        run = self.get(app, "/api/runs")["runs"][0]
        job = self.get(app, f"/api/jobs/{run['id']}")
        self.assertTrue(job["cases"][0]["playback_available"])
        recording = self.get(app, f"/api/jobs/{run['id']}/playback/0")
        self.assertEqual(recording["schema"], "banjo.playback.v1")
        self.assertEqual([body["id"] for body in recording["bodies"]], ["whole:0"])

    def test_the_page_code_for_the_bench_is_served(self):
        app = self.start()
        status, kind, raw = self.request(app, "GET", "/workbench.js")
        self.assertEqual(status, 200)
        self.assertTrue(kind.startswith("text/javascript"), kind)
        self.assertIn(b"export function makeWorkbench", raw)


class TheLabPageLeavesTheWorldPagesRoom(WorkbenchTestCase):
    def test_the_status_says_when_the_world_page_holds_the_live_world(self):
        app = self.start()
        self.assertFalse(self.get(app, "/api/status")["world_room_open"])
        self.post(app, "/api/world/open", {"scene": "yard"})
        self.assertTrue(self.get(app, "/api/status")["world_room_open"])
        # The lab page taking the live world for its own stage: the room is not
        # the world page's any more, so a lab page loaded after it may go live.
        self.post(app, "/api/live/open", {"spec": {"bodies": []}})
        self.assertFalse(self.get(app, "/api/status")["world_room_open"])


if __name__ == "__main__":
    unittest.main()
