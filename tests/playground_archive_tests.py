"""Regression tests for lazy loading of terminal playground jobs.

These tests only exercise the local archive and playback contract.  The
planner, engine and native process are mocked; no GPT request is made.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "playground"))

import server as playground_server  # noqa: E402


PRIVATE_KEY = "private-test-key-never-return"


def plan_for(experiment="panel_impact", **changes):
    plan = {
        "language": "banjo-playground-1", "name": "Archive test",
        "experiment": experiment, "explanation": "Archive test plan.",
        "limitations": [],
        "speeds_m_s": [2.0] if experiment in ("panel_impact", "knife_cut") else [],
        "heights_m": [0.25] if experiment in ("plate_drop", "rigid_drop") else [],
        "duration_s": 1.0, "projectile": "iron_ball",
        "panel_dimensions_m": [0.24, 0.36, 0.04], "objects": [],
    }
    plan.update(changes)
    return plan


class InlineExecutor:
    def submit(self, function, *args, **kwargs):
        function(*args, **kwargs)
        return object()

    def shutdown(self, wait=True, cancel_futures=False):
        return None


class ArchiveTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.engine_path = self.base / "banjo_platform_cli.fake"
        self.studio_path = self.base / "banjo_network_lab.fake"
        self.engine_path.touch()
        self.studio_path.touch()

    def make_app(self, planner):
        with mock.patch.object(playground_server, "local_configuration",
                               return_value=(PRIVATE_KEY, "fake-model")):
            app = playground_server.Playground(
                self.engine_path, self.studio_path, self.base / "runs",
                planner=planner)
        app.pool.shutdown(wait=True, cancel_futures=True)
        app.pool = InlineExecutor()
        self.addCleanup(app.pool.shutdown)
        return app


class PlaygroundArchiveTests(ArchiveTestCase):
    def archive(self, job_id: str, *, status: str = "complete", cases=None,
                **extra):
        directory = self.base / "runs" / job_id
        directory.mkdir(parents=True)
        saved = {
            "id": job_id,
            "status": status,
            "plan": plan_for("unsupported"),
            "cases": [] if cases is None else cases,
            "warnings": [],
            "timing": {},
            **extra,
        }
        (directory / "job.json").write_text(
            json.dumps(saved, allow_nan=False), encoding="utf-8")
        return directory

    def test_terminal_job_is_restored_lazily_and_playback_is_registered(self):
        job_id = "a" * 32
        directory = self.archive(job_id, cases=[{
            "index": 0, "status": "complete", "playback_available": True,
        }])
        payload = {"schema": "banjo.playback.v1", "status": "complete"}
        playback = directory / "playback-00.json"
        playback.write_text(json.dumps(payload), encoding="utf-8")

        app = self.make_app(mock.Mock())
        restored = app.get(job_id)

        self.assertTrue(restored["restored_from_disk"])
        self.assertTrue(restored["cases"][0]["playback_available"])
        self.assertFalse(restored["cases"][0]["native_scene"])
        self.assertEqual(app.playback(job_id, 0), playback.read_bytes())

    def test_invalid_id_is_rejected_before_archive_lookup(self):
        app = self.make_app(mock.Mock())
        with self.assertRaisesRegex(ValueError, "Unknown experiment"):
            app.get("not-a-job-id")

    def test_symlinked_archive_directory_is_rejected(self):
        runs = self.base / "runs"
        runs.mkdir()
        outside = self.base / "outside"
        outside.mkdir()
        job_id = "b" * 32
        (outside / "job.json").write_text(json.dumps({
            "id": job_id, "status": "complete", "cases": [],
        }), encoding="utf-8")
        link = runs / job_id
        try:
            link.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"directory symlinks unavailable: {exc}")
        app = self.make_app(mock.Mock())
        with self.assertRaisesRegex(ValueError, "Unknown experiment"):
            app.get(job_id)

    def test_archive_case_count_and_job_size_are_guarded(self):
        app = self.make_app(mock.Mock())
        too_many = "c" * 32
        self.archive(too_many, cases=[{"index": i} for i in range(5)])
        with self.assertRaisesRegex(ValueError, "Invalid archived experiment"):
            app.get(too_many)

        oversized = "d" * 32
        directory = self.base / "runs" / oversized
        directory.mkdir(parents=True)
        # The loader checks the job file size before parsing it.
        (directory / "job.json").write_bytes(b"{" + b"x" * (16 * 1024 * 1024) + b"}")
        with self.assertRaisesRegex(ValueError, "exceeds budget"):
            app.get(oversized)

    def test_missing_recording_disables_restored_playback(self):
        job_id = "e" * 32
        self.archive(job_id, cases=[{
            "index": 0, "status": "complete", "playback_available": True,
        }])
        app = self.make_app(mock.Mock())
        restored = app.get(job_id)
        self.assertFalse(restored["cases"][0]["playback_available"])
        with self.assertRaisesRegex(ValueError, "no computed 3D recording"):
            app.playback(job_id, 0)

    def test_failed_planner_persists_request_text_and_public_error(self):
        message = "planner failure should remain inspectable"
        planner = mock.Mock(side_effect=ValueError("planner exploded"))
        app = self.make_app(planner)
        result = app.submit({
            "message": message,
            "request_id": "archive_error_01",
            "auto_open": False,
        })
        job = app.get(result["job_id"])
        self.assertEqual(job["status"], "error")
        self.assertEqual(job["request_text"], message)
        self.assertEqual(job["error"], "planner exploded")
        archived = app.runs_path / result["job_id"] / "job.json"
        self.assertTrue(archived.is_file())
        self.assertEqual(json.loads(archived.read_text(encoding="utf-8"))["request_text"], message)


if __name__ == "__main__":
    unittest.main()
