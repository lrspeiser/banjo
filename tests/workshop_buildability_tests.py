"""Thin-part regressions: a valid drawing need not be an admissible simulation."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "playground")]
from mcp import workshop_buildability as build, workshop_components, workshop_visual
from mcp.workshop import WorkshopDesign, WirePart
import workshop_api

THIN = {"kind": "table", "parameters": {"top_thickness_m": .005, "leg_section_m": .015}}


class Buildability(unittest.TestCase):
    def test_thin_table_all_four_resolutions_and_no_mutation(self):
        design, overrides = workshop_components.design_from_spec(THIN)
        before = deepcopy(design.wireframe())
        for h, count, missing in ((.04, 0, 5), (.02, 0, 5), (.01, 1216, 1), (.005, 37224, 0)):
            with self.subTest(h=h):
                report, full, _ = build.assess(design, overrides, cell_size_m=h)
                self.assertEqual(count, report["costs"]["stored_cells"])
                self.assertEqual(missing, len(report["missing_components"]))
                self.assertFalse(report["compilation_ready"])
                self.assertFalse(report["installation_ready"])
                self.assertFalse(report["strength_certified"])
                self.assertFalse(full["engine_ready"])
                self.assertEqual(h, full["cell_size_m"])
                self.assertEqual(before, design.wireframe())

    def test_dimensions_only_are_not_an_occupancy_test(self):
        design, overrides = workshop_components.design_from_spec(THIN)
        with patch.object(workshop_visual, "matter_document", side_effect=AssertionError("not cheap")):
            report = build.design_feedback(design, overrides)
        self.assertEqual("dimensions-only", report["assessment"])
        self.assertTrue(all(p["sampled_cells"] is None for p in report["components"]))
        top = next(p for p in report["components"] if p["component"] == "top")
        self.assertEqual(["y"], top["subcell_axes"])
        self.assertIn("sheet", top["recommended_model"])
        self.assertFalse(report["mechanical_resolution_validated"])

    def test_budget_failure_returns_unknown_not_partial_or_success(self):
        design, overrides = workshop_components.design_from_spec(THIN)
        with patch.object(workshop_visual, "MAX_PREVIEW_CELLS", 100):
            report, full, measured = build.assess(design, overrides, cell_size_m=.005)
        self.assertIsNone(full); self.assertIsNone(measured)
        self.assertFalse(report["preview_complete"])
        self.assertIsNone(report["costs"]["stored_cells"])
        self.assertEqual("compilation-blocked", report["assessment"])
        self.assertTrue(report["source_geometry_preserved"])

    def test_joined_box_budget_is_independent(self):
        design, overrides = workshop_components.design_from_spec({"kind":"table"})
        with patch.object(build, "MAX_SCENE_BOXES", 1):
            report, _, _ = build.assess(design, overrides, cell_size_m=.02)
        self.assertGreater(report["costs"]["collision_boxes"], 1)
        self.assertLess(report["costs"]["stored_cells"], 16000)
        self.assertTrue(any("bridge budget" in e for e in report["errors"]))

    def test_closed_axis_aligned_clearance_is_reported(self):
        # Each 35-mm wide part occupies one 40-mm column; their 5-mm
        # design clearance lies between the touching column faces.
        design, _ = workshop_components.design_from_spec({"kind":"table"})
        design.parts = [WirePart("a", "panel", (.035, .08, .08), (.02, .04, .04)),
                        WirePart("b", "panel", (.035, .08, .08), (.06, .04, .04))]
        report, _, _ = build.assess(design, cell_size_m=.04)
        checks = report["clearance_checks"]
        self.assertEqual(1, len(checks)); self.assertTrue(checks[0]["closed"])
        self.assertAlmostEqual(.005, checks[0]["design_clearance_m"])
        self.assertEqual(0, checks[0]["grid_clearance_m"])
        self.assertFalse(report["compilation_ready"])
        self.assertIn("not verified", report["opening_audit"])

    def test_api_returns_editable_empty_preview_and_exterior_does_not_change_counts(self):
        with tempfile.TemporaryDirectory() as folder:
            app = SimpleNamespace(workshop_store=Path(folder))
            a = workshop_api.plan(app, {**THIN, "visual": {"cell_size_m":.04,"exterior_only":True}})
            self.assertEqual(0, a["matter"]["total_cells"])
            self.assertEqual(5, len(a["buildability"]["missing_components"]))
            self.assertNotIn("matter_measured", a)
            b = workshop_api.plan(app, {**THIN, "visual": {"cell_size_m":.01,"exterior_only":True}})
            c = workshop_api.plan(app, {**THIN, "visual": {"cell_size_m":.01,"exterior_only":False}})
            self.assertEqual(c["buildability"], b["buildability"])
            self.assertEqual(c["matter_measured"]["mass_kg"], b["matter_measured"]["mass_kg"])

    def test_invalid_resolution_never_falls_back(self):
        design, _ = workshop_components.design_from_spec(THIN)
        for value in (float("nan"), float("inf"), .0001, "tiny"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                build.assess(design, cell_size_m=value)

    def test_physical_skin_with_missing_cells_can_still_be_edited(self):
        with tempfile.TemporaryDirectory() as folder:
            app = SimpleNamespace(workshop_store=Path(folder))
            request = {**THIN, "component_overrides":{"top":{"skin":{"physical":True,"profile":"block"}}}}
            answer = workshop_api.candidates(app, request)
            self.assertTrue(answer["candidates"])
            preview = workshop_api.plan(app, {**request,"visual":{"cell_size_m":.04}})
            self.assertFalse(preview["buildability"]["compilation_ready"])
            self.assertEqual([], preview["objects"])


if __name__ == "__main__":
    unittest.main()
