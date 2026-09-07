"""Native reference provenance and honest analysis survive playground restore."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "playground"), str(ROOT / "tests")]
from archive_cohesive_reference import archive_reference
from cohesive_playback_tests import case
from experiment_diagnostics import build_diagnostics
from playground_tests import PlaygroundTestCase, playground_server


class CohesiveReferenceArchiveTests(PlaygroundTestCase):
    def test_native_archive_preserves_provenance_limits_and_separation_evidence(self):
        native = {"schema": "banjo.cohesive-sphere-probe.v1", "cases": [case(), case("solver_limit")]}
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "native.json"
            source.write_text(json.dumps(native), encoding="utf-8")
            runs = Path(temp) / "runs"
            job_id = archive_reference(source, runs)
            planner = mock.Mock(side_effect=AssertionError("Native archive must not call GPT"))
            app = self.make_app(planner)
            app.runs_path = runs
            job = app.get(job_id)
            self.assertEqual(job["authoring_source"], "native_development_reference")
            self.assertIsNone(job["timing"]["model"])
            self.assertEqual(job["cases"][0]["status"], "solver_limit")
            self.assertTrue(job["cases"][0]["playback_available"])
            recording = playground_server.strict_json(app.playback(job_id, 0))
            diagnostics = build_diagnostics(job["plan"], job["cases"][0]["package"], recording)
            self.assertEqual(diagnostics["source_schema"], native["schema"])
            self.assertFalse(diagnostics["validity"]["physical_response_validated"])
            measured = diagnostics["native_facts"]["cases"][1]
            self.assertEqual(measured["summary"]["maximum_fully_separated_facets"], 1)
            self.assertEqual(measured["requested_duration_s"], .008)
            self.assertEqual(measured["completed_duration_s"], .003)
            self.assertTrue(any(check["status"] == "fail" for check in diagnostics["checks"]))
            self.assertFalse(any("does not model fracture" in text for text in diagnostics["limitations"]))


if __name__ == "__main__":
    unittest.main()
