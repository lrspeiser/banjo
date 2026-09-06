from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "playground"))
from experiment_diagnostics import build_diagnostics


def fixture(*, status="complete", completed=.1, contacts=12, plastic=False):
    material = {"material_id": "sample", "name": "Fictional sample",
                "mechanical_law": "j2_plastic" if plastic else "isotropic_elastic",
                "density_kg_m3": 1000,
                "parameters": {"young_modulus_pa": 1e6, "poisson_ratio": .25,
                               "initial_yield_stress_pa": 1200 if plastic else 0}}
    request = {"duration_s": .1, "energy_budget_j": 3e-6, "max_step_calls": 200000,
               "materials": [material], "dimensions_m": [.08, .02, .08], "mesh_refinement": 1,
               "sphere": {"radius_m": .012, "density_kg_m3": 7870,
                          "clearance_m": .0005, "offset_xz_m": [.007, .009], "speed_m_s": 0}}
    frame = {"time_s": completed, "sphere_center_m": [0, .04, 0],
             "sphere_velocity_m_s": [0, .03, 0], "positions_m": [[0, 0, 0]],
             "maximum_equivalent_plastic_strain": .002 if plastic else 0,
             "plastic_dissipation_j": 7e-5 if plastic else 0}
    case = {"material_id": "sample", "material": material, "status": status,
            "frames": [frame], "summary": {"completed_duration_s": completed,
                "requested_duration_s": .1, "absolute_energy_residual_j": 2e-6,
                "energy_budget_j": 3e-6, "accepted_contacts": contacts, "step_calls": 1000,
                "wall_ms": 42, "plastic_dissipation_j": frame["plastic_dissipation_j"],
                "sampled_peak_upward_speed_m_s": .03, "sampled_peak_displacement_m": 6e-5}}
    if status == "solver_limit":
        case["error"] = "step-call budget exhausted"
    recording = {"schema": "banjo.dynamic-material-playback.v1", "status": status,
                 "physical_response_validated": False, "request": request, "cases": [case]}
    return {}, {"request_materials": request["materials"]}, recording


class DynamicMaterialDiagnosticsTests(unittest.TestCase):
    def test_complete_case_uses_native_contact_and_compact_evidence(self):
        result = build_diagnostics(*fixture())
        self.assertEqual(result["source_schema"], "banjo.dynamic-material-playback.v1")
        evidence = result["native_facts"]["cases"][0]
        self.assertEqual(evidence["accepted_contacts"], 12)
        self.assertEqual(evidence["contact_evidence"], "native_solver_counter")
        self.assertTrue(evidence["energy_budget_met"])
        self.assertNotIn("frames", evidence)
        self.assertEqual(result["checks"][0]["status"], "pass")
        self.assertEqual(result["validity"]["physical_response_validated"], False)
        self.assertLess(len(json.dumps(result)), 65536)

    def test_partial_solver_failure_preserves_native_reason_and_duration(self):
        result = build_diagnostics(*fixture(status="solver_limit", completed=.037))
        evidence = result["native_facts"]["cases"][0]
        self.assertEqual(evidence["status"], "solver_limit")
        self.assertEqual(evidence["error"], "step-call budget exhausted")
        self.assertAlmostEqual(evidence["completed_duration_s"], .037)
        self.assertEqual(result["checks"][0]["status"], "fail")

    def test_zero_native_contacts_is_not_replaced_by_proximity_inference(self):
        result = build_diagnostics(*fixture(contacts=0))
        contact = next(check for check in result["checks"] if check["check"].endswith("_contact"))
        self.assertEqual((contact["status"], contact["observation"]),
                         ("fail", "native_solver_reported_zero_contacts"))
        self.assertIn("sampled proximity is not used", contact["scope"])

    def test_plastic_history_is_observed_but_dent_is_unsupported(self):
        result = build_diagnostics(*fixture(plastic=True))
        evidence = result["native_facts"]["cases"][0]
        self.assertTrue(evidence["observed_plastic_response"])
        self.assertFalse(evidence["permanent_dent_supported"])
        self.assertTrue(any("does not establish a permanent dent" in item
                            for item in result["limitations"]))

    def test_label_rename_does_not_change_numeric_material_evidence(self):
        args = fixture(plastic=True)
        first = build_diagnostics(*args)
        renamed = copy.deepcopy(args)
        renamed[2]["request"]["materials"][0]["material_id"] = "renamed"
        renamed[2]["request"]["materials"][0]["name"] = "Different display label"
        renamed[2]["cases"][0]["material"]["material_id"] = "renamed"
        renamed[2]["cases"][0]["material"]["name"] = "Different display label"
        second = build_diagnostics(*renamed)
        a, b = first["native_facts"]["cases"][0], second["native_facts"]["cases"][0]
        for key in ("material_numeric_sha256", "absolute_energy_residual_j",
                    "accepted_contacts", "plastic_dissipation_j"):
            self.assertEqual(a[key], b[key])
        self.assertEqual(first["package"]["input_materials"][0]["sha256"],
                         second["package"]["input_materials"][0]["sha256"])

    def test_existing_recording_dispatch_is_preserved(self):
        result = build_diagnostics({}, {}, {"status": "complete", "frames": [], "report": {}})
        self.assertEqual(result["schema"], "banjo.experiment-diagnostics.v1")
        self.assertNotIn("source_schema", result)


if __name__ == "__main__":
    unittest.main()
