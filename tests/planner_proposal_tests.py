"""Tests for the typed planner proposal boundary.

The proposal lowering path is pure local validation; these tests never call
the planner or the OpenAI API.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "playground"))

from control_contract import default_ui  # noqa: E402
from experiment_language import lower_proposal, lower_and_admit  # noqa: E402
from network_admission import Inadmissible  # noqa: E402


def proposal(setup, *, experiment_ui=None, duration_s=1.0):
    kind = setup["kind"]
    return {
        "name": "Typed proposal test",
        "explanation": "A bounded proposal for a local schema test.",
        "limitations": ["Experimental fixture."],
        "duration_s": duration_s,
        "ui": default_ui(experiment_ui or kind),
        "requirements": [],
        "fidelity": "experimental",
        "setup": setup,
    }


def drop_setup(**changes):
    value = {
        "kind": "drop_test",
        "drop": {
            "target_dimensions_m": [.24, .36, .04],
            "projectile": "iron_ball",
            "projectile_dimensions_m": [.08, .08, .08],
            "support": "clamped_edges",
            "impact_offset_m": [.01, -.02],
            "heights_m": [.05, .25],
            "representation": "network",
            "resolution": [6, 9, 2],
        },
    }
    value["drop"].update(changes)
    return value


class PlannerProposalTests(unittest.TestCase):
    def test_drop_preserves_explicit_setup_and_clears_legacy_arrays(self):
        plan = lower_proposal(proposal(drop_setup()))
        self.assertEqual(plan["experiment"], "drop_test")
        self.assertEqual(plan["drop"]["target_dimensions_m"], [.24, .36, .04])
        self.assertEqual(plan["drop"]["impact_offset_m"], [.01, -.02])
        self.assertEqual(plan["drop"]["heights_m"], [.05, .25])
        self.assertEqual(plan["speeds_m_s"], [])
        self.assertEqual(plan["heights_m"], [])
        self.assertEqual(plan["objects"], [])
        self.assertEqual(plan["panel_dimensions_m"], [.24, .36, .04])
        self.assertEqual(plan["pressure"], None)

    def test_non_cubic_resolution_is_repaired_and_reported_not_run_as_asked(self):
        plan = lower_and_admit(proposal(drop_setup(resolution=[4, 4, 2])))
        self.assertEqual(plan["drop"]["resolution"], [6, 9, 2])
        self.assertEqual(plan["drop"]["target_dimensions_m"], [.24, .36, .04])
        note = plan["admission_notes"][0]
        self.assertEqual(note["limit"], "cell_aspect_ratio")
        self.assertEqual(note["action"], "snapped")
        self.assertIn("4.50:1", note["message"])
        self.assertIn("[6, 9, 2]", note["message"])

    def test_unbuildable_thin_plate_is_refused_by_name_with_a_workable_alternative(self):
        with self.assertRaises(Inadmissible) as caught:
            lower_and_admit(proposal(drop_setup(target_dimensions_m=[.24, .36, .006])))
        self.assertEqual(caught.exception.limit, "slenderness_face_over_thickness")
        message = str(caught.exception)
        self.assertIn("60.0:1", message)
        self.assertIn("0.03 m thick", message)
        self.assertIn("No substitute geometry was run.", message)

    def test_scene_preserves_gravity_orientation_and_spin(self):
        setup = {
            "kind": "scene_test",
            "scene": {
                "objects": [{
                    "preset": "iron_ball",
                    "position_m": [1.0, .5, -1.0],
                    "velocity_m_s": [.2, 0, -.3],
                    "dimensions_m": [.08, .08, .08],
                    "orientation_wxyz": [.9238795, 0, .3826834, 0],
                    "spin_rad_s": [0, 2.5, 0],
                    "representation": "preset",
                    "resolution": None,
                    "pin_boundary": None,
                }],
                "environment": {
                    "gravity_m_s2": [1.0, -9.0, .5],
                    "ground": True,
                    "ground_friction": .35,
                },
            },
        }
        plan = lower_proposal(proposal(setup))
        self.assertEqual(plan["scene"]["environment"]["gravity_m_s2"], [1.0, -9.0, .5])
        self.assertEqual(plan["scene"]["objects"][0]["spin_rad_s"], [0, 2.5, 0])
        self.assertEqual(plan["scene"]["objects"][0]["orientation_wxyz"], [.9238795, 0, .3826834, 0])
        self.assertEqual(plan["speeds_m_s"], [])
        self.assertEqual(plan["heights_m"], [])

    def test_pressure_setup_lowers_only_to_pressure_and_keeps_controls_compatible(self):
        setup = {
            "kind": "continuum_pressure_reference",
            "pressure": {
                "peak_pressure_pa": 200_000_000,
                "resolution": 8,
                "increments": 16,
                "profile": "smooth",
            },
        }
        plan = lower_proposal(proposal(setup))
        self.assertEqual(plan["experiment"], "continuum_pressure_reference")
        self.assertEqual(plan["pressure"]["resolution"], 8)
        self.assertEqual(plan["pressure"]["increments"], 16)
        self.assertEqual(plan["speeds_m_s"], [])
        self.assertEqual(plan["heights_m"], [])
        self.assertEqual(plan["objects"], [])

    def test_unsupported_setup_requires_empty_ui(self):
        setup = {"kind": "unsupported"}
        value = proposal(setup)
        value["ui"] = {"title": "Unsupported", "controls": []}
        plan = lower_proposal(value)
        self.assertEqual(plan["experiment"], "unsupported")
        self.assertEqual(plan["ui"]["controls"], [])

    def test_unknown_setup_kind_and_extra_setup_field_are_rejected(self):
        unknown = proposal(drop_setup())
        unknown["setup"] = {"kind": "fluids"}
        with self.assertRaisesRegex(ValueError, "Invalid typed experiment setup"):
            lower_proposal(unknown)

        extra = proposal(drop_setup())
        extra["setup"]["drop"]["seed"] = 17
        with self.assertRaisesRegex(ValueError, "drop has unknown or missing fields"):
            lower_proposal(extra)

        top_level = proposal(drop_setup())
        top_level["unexpected"] = True
        with self.assertRaisesRegex(ValueError, "Unknown or missing planner proposal fields"):
            lower_proposal(top_level)

    def test_calibrated_request_blocks_before_invalid_physics_setup(self):
        value = proposal(drop_setup())
        value["fidelity"] = "calibrated"
        value["setup"]["drop"]["resolution"] = [12,12,12]
        plan = lower_proposal(value)
        self.assertEqual(plan["experiment"], "unsupported")
        self.assertIsNone(plan["drop"])
        self.assertEqual(plan["requirements"][0]["status"], "unsupported")

    def test_optional_ui_repair_preserves_physics_and_discloses_fallback(self):
        value = proposal(drop_setup())
        value["ui"]["title"] = ""
        with self.assertRaisesRegex(ValueError, "UI title"):
            lower_proposal(value)
        plan = lower_proposal(value, repair_ui=True)
        self.assertEqual(plan["drop"], value["setup"]["drop"])
        self.assertIn("standard controls", plan["limitations"][-1])
        height = next(c for c in plan["ui"]["controls"] if c["action"] == "height_m")
        self.assertEqual(height["value"], plan["drop"]["heights_m"][0])

    def test_incompatible_controls_are_rejected_after_route_lowering(self):
        value = proposal(drop_setup(), experiment_ui="panel_impact")
        with self.assertRaisesRegex(ValueError, "unsupported for this experiment"):
            lower_proposal(value)


if __name__ == "__main__":
    unittest.main()
