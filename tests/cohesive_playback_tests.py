import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "playground"))
from cohesive_playback import adapt_cohesive_playback


def frame(time, positions=None, exposed=None, components=None):
    return {
        "time_s": time,
        "sphere_center_m": [0.0, 0.04 - time, 0.0],
        "sphere_velocity_m_s": [0.0, -1.0, 0.0],
        "positions_m": positions or [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0],
                                     [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
        "contacts": 1 if time else 0,
        "maximum_damage": min(1.0, time * 100),
        "fully_separated_facets": 1 if time else 0,
        "components": len(set(components or [0])),
        "component_by_tetrahedron": components or [0],
        "newly_exposed_faces": exposed if exposed is not None else ([[0, 1, 2]] if time else []),
        "fracture_dissipation_j": time,
        "energy_residual_j": 1e-8,
    }


def case(status="complete"):
    completed = 0.008 if status == "complete" else 0.003
    frames = [frame(0.0), frame(completed,
                                [[0.0, 0.0, 0.0], [1.0 + completed, 0.0, 0.0],
                                 [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])]
    return {
        "name": "higher_impact",
        "scope": "fictional explicit SI cohesive impact",
        "bulk": {"law": "isotropic_elastic", "young_modulus_pa": 1e6,
                 "poisson_ratio": .25, "density_kg_m3": 1000.0},
        "interface": {"stiffness_pa_per_m": 1e9,
                      "tangential_stiffness_pa_per_m": 2e8,
                      "strength_pa": 1e4, "fracture_energy_j_m2": .1},
        "sphere": {"radius_m": .012, "density_kg_m3": 7870.0,
                   "mass_kg": .057, "initial_speed_m_s": 1.0},
        "requested_duration_s": .008,
        "stable_time_step_s": 1e-4,
        "time_step_s": 2e-5,
        "limitations": ["no calibrated material fracture claim"],
        "mesh": {"reference_positions_m": frames[0]["positions_m"],
                 "tetrahedra": [[0, 1, 2, 3]],
                 "boundary_triangles": [[0, 2, 1], [0, 1, 3]]},
        "frames": frames,
        "summary": {"status": status, "error": "step limit" if status != "complete" else "",
                    "completed_duration_s": completed, "steps": 12,
                    "accepted_contacts": 4, "maximum_damage": .5,
                    "maximum_fully_separated_facets": 1, "maximum_components": 1,
                    "newly_exposed_faces_final": 1, "geometry_queries": 20,
                    "geometry_iterations": 30, "cumulative_energy_residual_j": 1e-8,
                    "cumulative_absolute_energy_residual_j": 2e-8, "wall_ms": 3.0},
    }


class CohesivePlaybackTests(unittest.TestCase):
    def test_preserves_native_positions_trajectory_and_evolving_topology(self):
        source = {"schema": "banjo.cohesive-sphere-probe.v1", "cases": [case()]}
        original = copy.deepcopy(source)
        result = adapt_cohesive_playback(source)
        adapted = result["cases"][0]
        self.assertEqual(result["schema"], "banjo.dynamic-material-playback.v1")
        self.assertEqual(result["native_schema"], source["schema"])
        self.assertFalse(result["physical_response_validated"])
        self.assertEqual([f["positions_m"] for f in adapted["frames"]],
                         [f["positions_m"] for f in source["cases"][0]["frames"]])
        self.assertEqual([f["sphere_center_m"] for f in adapted["frames"]],
                         [f["sphere_center_m"] for f in source["cases"][0]["frames"]])
        self.assertEqual(adapted["frames"][-1]["boundary_triangles"],
                         source["cases"][0]["mesh"]["boundary_triangles"] +
                         source["cases"][0]["frames"][-1]["newly_exposed_faces"])
        self.assertEqual(source, original)

    def test_partial_high_case_remains_solver_limit(self):
        source = {"schema": "banjo.cohesive-sphere-probe.v1",
                  "cases": [case("solver_limit")]}
        result = adapt_cohesive_playback(source)
        adapted = result["cases"][0]
        self.assertEqual(result["status"], "solver_limit")
        self.assertEqual(adapted["status"], "solver_limit")
        self.assertEqual(adapted["completed_duration_s"], .003)
        self.assertEqual(adapted["error"], "step limit")
        self.assertEqual(adapted["summary"]["accepted_contacts"], 4)

    def test_rejects_nonmonotonic_time_and_bad_topology(self):
        bad = case()
        bad["frames"][1]["time_s"] = 0.0
        with self.assertRaisesRegex(ValueError, "times"):
            adapt_cohesive_playback({"schema": "banjo.cohesive-sphere-probe.v1",
                                      "cases": [bad]})
        bad = case()
        bad["frames"][1]["newly_exposed_faces"] = [[0, 1, 9]]
        with self.assertRaisesRegex(ValueError, "integer"):
            adapt_cohesive_playback({"schema": "banjo.cohesive-sphere-probe.v1",
                                      "cases": [bad]})

    def test_rejects_component_and_position_layout_changes(self):
        bad = case()
        bad["frames"][1]["positions_m"].pop()
        with self.assertRaisesRegex(ValueError, "node layout"):
            adapt_cohesive_playback({"schema": "banjo.cohesive-sphere-probe.v1",
                                      "cases": [bad]})
        bad = case()
        bad["frames"][1]["component_by_tetrahedron"] = []
        with self.assertRaisesRegex(ValueError, "component layout"):
            adapt_cohesive_playback({"schema": "banjo.cohesive-sphere-probe.v1",
                                      "cases": [bad]})


if __name__ == "__main__":
    unittest.main()
