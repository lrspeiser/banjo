"""Regression tests for the browser control and playback API.

These tests reuse the pure fixtures from playground_tests.py and never launch a
native Banjo process.
"""
from __future__ import annotations

from copy import deepcopy
import http.client
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "playground"))

from playground_tests import (  # noqa: E402
    PlaygroundTestCase, FakeEngine, InlineExecutor, PRIVATE_KEY, continuum_process,
    continuum_report, plan_for, playground_server,
)
from control_contract import default_ui  # noqa: E402


class BrowserControlApiTests(PlaygroundTestCase):
    def test_optional_ui_is_validated_and_invalid_ui_never_reaches_engine(self):
        valid = plan_for("panel_impact")
        valid["ui"] = default_ui("panel_impact")
        planner = mock.Mock(return_value=(valid, {"model": "fake-model"}))
        app = self.make_app(planner)
        result = app.submit({"message": "with controls", "request_id": "ui_valid_01", "auto_open": False})
        self.assertEqual(app.get(result["job_id"])["plan"]["ui"], valid["ui"])

        invalid = plan_for("panel_impact")
        invalid["ui"] = deepcopy(default_ui("panel_impact"))
        invalid["ui"]["controls"][0]["action"] = "run_shell"
        bad = self.make_app(mock.Mock(return_value=(invalid, {"model": "fake-model"})))
        result = bad.submit({"message": "invalid controls", "request_id": "ui_bad_01", "auto_open": False})
        self.assertEqual(bad.get(result["job_id"])["status"], "error")
        self.assertEqual(bad.engine.call_order, [])

    def test_unsupported_requirement_blocks_before_compile_or_engine(self):
        plan = plan_for("panel_impact", requirements=[{
            "description": "calibrated fracture", "status": "unsupported", "reason": "not implemented",
        }])
        app = self.make_app(mock.Mock(return_value=(plan, {"model": "fake-model"})))
        result = app.submit({"message": "bounded impact", "request_id": "req_block_01", "auto_open": False})
        job = app.get(result["job_id"])
        self.assertEqual(job["status"], "blocked")
        self.assertIn("calibrated fracture", job["message"])
        self.assertEqual(app.engine.call_order, [])

    def test_thin_glass_request_cannot_fall_back_to_plate_fixture(self):
        plan = plan_for("plate_drop")
        app = self.make_app(mock.Mock(return_value=(plan, {"model": "fake-model"})))
        result = app.submit({"message": "thin tempered glass panel drop", "request_id": "thin_glass_01", "auto_open": False})
        job = app.get(result["job_id"])
        self.assertEqual(job["status"], "blocked")
        self.assertIn("no thicker panel was substituted", job["message"])
        self.assertEqual(app.engine.call_order, [])

    def test_height_rerun_uses_prepared_plan_without_planner_and_preserves_original(self):
        original = plan_for("plate_drop", heights_m=[.25])
        planner = mock.Mock(return_value=(original, {"model": "fake-model"}))
        app = self.make_app(planner)
        first = app.submit({"message": "drop", "request_id": "rerun_base_01", "auto_open": False})
        before = deepcopy(app.get(first["job_id"])["plan"])
        rerun = app.rerun(first["job_id"], {"case_index": 0, "action": "height_m", "value": .75, "request_id": "rerun_height_01"})
        self.assertEqual(planner.call_count, 1)
        self.assertEqual(app.get(first["job_id"])["plan"], before)
        rerun_job = app.get(rerun["job_id"])
        self.assertEqual(rerun_job["plan"]["heights_m"], [.75])
        self.assertEqual(len(app.engine.run_calls), 2)

    def test_pressure_rerun_forwards_changed_pressure_and_nullable_default(self):
        plan = plan_for("continuum_pressure_reference", pressure=None)
        app = self.make_app(mock.Mock(return_value=(plan, {"model": "fake-model"})))
        with mock.patch.object(playground_server.subprocess, "run", side_effect=continuum_process(continuum_report())):
            first = app.submit({"message": "pressure", "request_id": "pressure_base_01", "auto_open": False})
        app.engine.run_calls.clear()
        app.engine.call_order.clear()
        with mock.patch.object(playground_server.subprocess, "run", side_effect=continuum_process(continuum_report())) as run:
            rerun = app.rerun(first["job_id"], {"case_index": 0, "action": "pressure_pa", "value": 500_000_000, "request_id": "pressure_rerun_01"})
        args = run.call_args.args[0]
        self.assertIn("500000000", args)
        self.assertEqual(app.engine.run_calls, [])
        self.assertEqual(app.get(rerun["job_id"])["plan"]["pressure"]["peak_pressure_pa"], 500_000_000)

    def test_request_id_is_idempotent_for_chat_and_rerun(self):
        planner = mock.Mock(return_value=(plan_for("unsupported"), {"model": "fake-model"}))
        app = self.make_app(planner)
        body = {"message": "same", "request_id": "same_request_01", "auto_open": False}
        first = app.submit(body)
        self.assertEqual(app.submit(deepcopy(body)), first)
        self.assertEqual(planner.call_count, 1)

    def test_recorder_artifact_becomes_playback_without_second_engine_run(self):
        recorder = self.engine_path.with_name("banjo_playground_record.fake")
        recorder.touch()
        plan = plan_for("panel_impact", duration_s=.1)

        def record(args, **kwargs):
            output = Path(args[args.index("--output") + 1])
            output.write_text(json.dumps({"schema": "banjo.playback.v1", "status": "complete", "report": {"recorded": True}}), encoding="utf-8")
            return mock.Mock(returncode=0)

        app = self.make_app(mock.Mock(return_value=(plan, {"model": "fake-model"})))
        with mock.patch.object(playground_server.subprocess, "run", side_effect=record):
            result = app.submit({"message": "record", "request_id": "recording_01", "auto_open": False})
        job = app.get(result["job_id"])
        self.assertTrue(job["cases"][0]["playback_available"])
        self.assertEqual(app.engine.run_calls, [])
        self.assertIn((result["job_id"], 0), app.playbacks)
        self.assertEqual(app.playback(result["job_id"], 0), json.dumps({"schema": "banjo.playback.v1", "status": "complete", "report": {"recorded": True}}).encode())
        with self.assertRaisesRegex(ValueError, "no computed 3D recording"):
            app.playback(result["job_id"], 1)


class BrowserHttpApiTests(PlaygroundTestCase):
    def setUp(self):
        super().setUp()
        self.app = self.make_app(mock.Mock(return_value=(plan_for("unsupported"), {"model": "fake-model"})))
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), playground_server.Handler)
        self.httpd.app = self.app
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.port = self.httpd.server_port

    def stop_server(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=3)

    def request(self, method, path, body=None, headers=None):
        headers = dict(headers or {})
        payload = None if body is None else json.dumps(body, allow_nan=False).encode()
        if body is not None:
            headers.setdefault("Content-Type", "application/json")
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        try:
            connection.request(method, path, body=payload, headers=headers)
            response = connection.getresponse()
            raw = response.read()
            return response.status, dict(response.getheaders()), raw
        finally:
            connection.close()

    def test_rerun_requires_csrf_and_same_origin(self):
        job_id = "a" * 32
        body = {"case_index": 0, "action": "height_m", "value": .5, "request_id": "http_rerun_01"}
        status, _, _ = self.request("POST", f"/api/jobs/{job_id}/rerun", body)
        self.assertEqual(status, 403)
        status, _, _ = self.request("POST", f"/api/jobs/{job_id}/rerun", body, {"X-Banjo-Token": self.app.csrf_token, "Origin": "https://attacker.invalid"})
        self.assertEqual(status, 400)

    def test_playback_get_returns_bytes_and_checks_origin_and_registration(self):
        job_id = "b" * 32
        path = self.base / "playback.json"
        payload = b'{"schema":"banjo.playback.v1"}'
        path.write_bytes(payload)
        self.app.playbacks[(job_id, 0)] = path
        status, _, raw = self.request("GET", f"/api/jobs/{job_id}/playback/0")
        self.assertEqual(status, 200)
        self.assertEqual(raw, payload)
        status, _, _ = self.request("GET", f"/api/jobs/{job_id}/playback/1")
        self.assertEqual(status, 400)
        status, _, _ = self.request("GET", f"/api/jobs/{job_id}/playback/0", headers={"Origin": "https://attacker.invalid"})
        self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()
