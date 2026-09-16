from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mcp.workshop import assemble  # noqa: E402
from mcp.workshop_force import probe  # noqa: E402
from mcp.workshop_statics import G_M_S2  # noqa: E402


class PointForceProbe(unittest.TestCase):
    def setUp(self):
        self.design = assemble("table", design_id="force-table")
        self.top = next(part for part in self.design.parts if part.name == "top")

    def test_downward_pulse_reports_impulse_load_paths_and_support_reactions(self):
        answer = probe(
            self.design, component_name="top", point_m=self.top.center_m,
            direction=[0, -1, 0], force_n=100.0, duration_s=0.2)
        self.assertEqual("analytical-estimate", answer["evidence"])
        self.assertEqual([0.0, -100.0, 0.0], answer["force_vector_n"])
        self.assertEqual(20.0, answer["impulse_magnitude_n_s"])
        self.assertTrue(answer["load_paths"])
        self.assertEqual({"leg-1", "leg-2", "leg-3", "leg-4"},
                         {row["support"] for row in answer["load_paths"]})
        total = sum(row["reaction_n"] for row in answer["support_reactions"])
        expected = self.design.measure()["mass_kg"] * G_M_S2 + 100.0
        self.assertAlmostEqual(expected, total, places=2)

    def test_horizontal_pulse_does_not_invent_vertical_support_reactions(self):
        answer = probe(
            self.design, component_name="top", point_m=[0, self.top.center_m[1], 0],
            direction=[1, 0, 0], force_n=50.0, duration_s=0.1)
        self.assertEqual(0.0, answer["downward_force_n"])
        self.assertEqual([], answer["support_reactions"])
        self.assertIn("does not invent", answer["acceptance"]["why"])

    def test_bad_target_zero_direction_and_unbounded_force_are_refused(self):
        with self.assertRaisesRegex(ValueError, "no component"):
            probe(self.design, component_name="missing", point_m=[0, 0, 0],
                  direction=[0, -1, 0], force_n=10, duration_s=0.1)
        with self.assertRaisesRegex(ValueError, "must not be zero"):
            probe(self.design, component_name="top", point_m=[0, 0, 0],
                  direction=[0, 0, 0], force_n=10, duration_s=0.1)
        with self.assertRaisesRegex(ValueError, "between 0 and 100000"):
            probe(self.design, component_name="top", point_m=[0, 0, 0],
                  direction=[0, -1, 0], force_n=1e9, duration_s=0.1)


if __name__ == "__main__":
    unittest.main()
