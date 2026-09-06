"""Typed-plan, saved evidence and archive tests for the new dynamic route."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "playground"))
sys.path.insert(0, str(ROOT / "tests"))
import experiment_language as language
from dynamic_material import native_request
from control_contract import default_ui
import server
from playground_tests import InlineExecutor


def proposal():
    return {"name": "Authored diagnostic", "explanation": "Two authored material laws.",
            "limitations": ["Small-strain experimental response."], "duration_s": .001,
            "ui": default_ui("dynamic_material_impact"), "requirements": [], "fidelity": "experimental",
            "setup": {"kind": "dynamic_material_impact", "impact": {
                "materials": [{"material_id": "a", "name": "Fictional A", "density_kg_m3": 1000,
                               "mechanical_law": "isotropic_elastic", "parameters": {
                                   "young_modulus_pa": 1e6, "poisson_ratio": .25,
                                   "maximum_total_strain_norm": .08}}],
                "dimensions_m": [.08, .02, .08], "mesh_refinement": 1,
                "sphere": {"radius_m": .012, "density_kg_m3": 7870, "clearance_m": .0005,
                           "offset_xz_m": [.007, .009], "speed_m_s": 0},
                "energy_budget_j": 6e-6, "max_step_calls": 200000}}}


def recording(request, limited=False):
    material = request["materials"][0]
    return {"schema": "banjo.dynamic-material-playback.v1", "physical_response_validated": False,
            "status": "solver_limit" if limited else "complete", "request": request,
            "cases": [{"material_id": material["material_id"], "material": material,
                       "status": "solver_limit" if limited else "complete", "mesh": {},
                       "frames": [{"time_s": 0}], "summary": {
                           "requested_duration_s": .001, "completed_duration_s": 0 if limited else .001,
                           "accepted_contacts": 0, "energy_budget_j": 6e-6,
                           "absolute_energy_residual_j": 0}}]}


class DynamicRouteTests(unittest.TestCase):
    def test_typed_plan_preserves_input_and_blocks_other_payloads(self):
        source = proposal()
        plan = language.lower_proposal(source)
        self.assertEqual(plan["impact"], source["setup"]["impact"])
        self.assertEqual(language.compile_plan(plan), [])
        for bad in (dict(plan, duration_s=.101), dict(plan, speeds_m_s=[1]),
                    dict(plan, experiment="material_state_reference"), dict(plan, impact=None)):
            with self.assertRaises(ValueError):
                language.validate_plan(bad)

    def test_calibrated_request_and_magnification_are_not_silently_admitted(self):
        raw = proposal()
        raw["fidelity"] = "calibrated"
        plan = language.lower_proposal(raw)
        self.assertEqual(plan["experiment"], "unsupported")
        self.assertIsNone(plan["impact"])
        self.assertTrue(language.request_blockers("calibrated", plan))
        raw = proposal()
        raw["ui"]["controls"].append({"id": "magnify", "label": "Magnify", "kind": "slider",
                                      "action": "magnification", "min": 1, "max": 100,
                                      "step": 1, "value": 10})
        with self.assertRaises(ValueError):
            language.lower_proposal(raw)

    def test_execution_and_archive_retain_recording_evidence_and_numeric_request(self):
        for limited in (False, True):
            with self.subTest(limited=limited), tempfile.TemporaryDirectory() as temp:
                base = Path(temp)
                engine = base / "engine.exe"
                engine.touch()
                plan = language.lower_proposal(proposal())
                expected = native_request(plan["impact"], plan["duration_s"])
                data = recording(expected, limited)
                with mock.patch.object(server, "local_configuration", return_value=("", "fake")):
                    app = server.Playground(engine, base / "studio.exe", base / "runs", planner=lambda *a: (deepcopy(plan), {}))
                app.pool.shutdown()
                app.pool = InlineExecutor()
                with mock.patch.object(server, "execute_impact", return_value=(data, {"request_sha256": "test"})) as run:
                    job_id = app.submit({"message": "Run the authored laws", "request_id": "test-request", "auto_open": False})["job_id"]
                job = app.get(job_id)
                self.assertEqual(job["status"], "complete", job)
                self.assertEqual(run.call_args.args[1], expected)
                self.assertFalse(job["cases"][0]["native_scene"])
                self.assertEqual(job["cases"][0]["status"], data["status"])
                self.assertNotIn("frames", job["cases"][0]["report"]["cases"][0])
                self.assertEqual(json.loads(app.playback(job_id, 0)), data)
                evidence = app.evidence(job_id, 0)
                self.assertEqual(evidence["diagnostics"]["source_schema"], data["schema"])
                self.assertLess(len(json.dumps(evidence).encode()), 65536)
                app.jobs.clear()
                app.playbacks.clear()
                restored = app.get(job_id)
                self.assertTrue(restored["restored_from_disk"])
                self.assertTrue(restored["cases"][0]["playback_available"])
                self.assertEqual(json.loads(app.playback(job_id, 0)), data)


if __name__ == "__main__":
    unittest.main()
