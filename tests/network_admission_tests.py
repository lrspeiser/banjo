"""The playground's model of what the engine accepts, and what it costs.

Two claims are under test. The first is that the limits mirrored in
`playground/network_admission.py` are the engine's actual limits, which is
checked against the native CLI's own report wherever the build exists. The
second is that an inadmissible setup is either repaired and reported or refused
by name, and never silently turned into a different experiment.

Admission is not calibration. Nothing here claims a material response is right.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "playground"))
sys.path.insert(0, str(ROOT / "examples" / "authoring"))

import builder  # noqa: E402
import network_admission as admission  # noqa: E402
import experiment_language as language  # noqa: E402
from banjo_authoring import EngineCLI, make_object, make_package  # noqa: E402
from control_contract import default_ui  # noqa: E402

ENGINES = [ROOT / "build/win-joint-double/Release/banjo_platform_cli.exe",
           ROOT / "build/win-integration/Release/banjo_platform_cli.exe",
           ROOT / "build/ci/banjo_platform_cli"]


def engine():
    return next((path for path in ENGINES if path.is_file()), None)


def glass_package(dimensions, resolution, *, dt=1 / 1920):
    panel = make_object("glass_panel", 1, dimensions_m=list(dimensions),
                        resolution=list(resolution), position_m=[0, .3, 0], pin_boundary=True)
    return make_package([panel], name="admission fixture", fixed_dt_s=dt)


def drop_proposal(**drop):
    spec = {"target_dimensions_m": [.24, .36, .04], "projectile": "iron_ball",
            "projectile_dimensions_m": [.08, .08, .08], "support": "clamped_edges",
            "impact_offset_m": [0, 0], "heights_m": [.05], "representation": "network",
            "resolution": [6, 9, 2]}
    spec.update(drop)
    return {"name": "Admission fixture", "explanation": "A bounded local test.",
            "limitations": [], "duration_s": .1, "ui": default_ui("drop_test"),
            "requirements": [], "fidelity": "experimental",
            "setup": {"kind": "drop_test", "drop": spec}}


class LimitMirrorTests(unittest.TestCase):
    def test_limits_match_the_values_the_native_source_enforces(self):
        source = (ROOT / "src/platform/NetworkWorld.cpp").read_text(encoding="utf-8")
        self.assertIn('integer(o["resolution"][0],2,16)', source.replace(" ", ""))
        self.assertIn("require(nx*ny*nz<=800", source.replace(" ", ""))
        self.assertIn("require(w.nodes.size()<1024", source.replace(" ", ""))
        self.assertIn("require(radius>=.001", source.replace(" ", ""))
        self.assertIn("constexprdoublekStabilityPhaseRadians=.2", source.replace(" ", ""))
        self.assertIn("constexprunsignedkMaximumStabilitySubsteps=8192", source.replace(" ", ""))
        self.assertEqual([admission.RESOLUTION_MIN, admission.RESOLUTION_MAX], [2, 16])
        self.assertEqual(admission.OBJECT_CELL_BUDGET, 800)
        self.assertEqual(admission.WORLD_CELL_BUDGET, 1024)
        self.assertEqual(admission.COLLISION_RADIUS_MIN_M, .001)
        self.assertEqual(admission.STABILITY_PHASE_RAD, .2)
        # 16 cells on the long axis and 2 on the short one, times the 2:1 cell
        # tolerance, is the whole reason a uniform-cell object stops at 16:1.
        self.assertEqual(admission.CUBIC_SLENDERNESS, 8)
        self.assertEqual(admission.MAX_SLENDERNESS, 16)
        # And that ceiling is reachable: a 16:1 box really does have a mesh.
        self.assertIsNotNone(admission.nearest_admissible_resolution([.32, .32, .02]))
        self.assertIsNone(admission.nearest_admissible_resolution([.34, .34, .02]))

    def test_cell_metrics_report_spacing_aspect_coverage_and_radius(self):
        metrics = admission.cell_metrics([.24, .36, .04], [6, 9, 2])
        self.assertEqual(metrics["spacing_mm"], [40, 40, 20])
        self.assertEqual(metrics["cells"], 108)
        self.assertAlmostEqual(metrics["aspect_ratio"], 2.0)
        self.assertAlmostEqual(metrics["collision_radius_m"], .0098)
        self.assertAlmostEqual(metrics["collision_coverage"], .49)
        self.assertTrue(metrics["cubic"] and metrics["radius_ok"] and metrics["cells_ok"])
        slender = admission.cell_metrics([.24, .36, .04], [4, 4, 2])
        self.assertAlmostEqual(slender["aspect_ratio"], 4.5)
        self.assertFalse(slender["cubic"])

    def test_malformed_geometry_is_rejected_rather_than_reported(self):
        for dimensions, resolution in (([.1, .1], [2, 2, 2]), ([.1, .1, 0], [2, 2, 2]),
                                       ([.1, .1, .1], [1, 2, 2]), ([.1, .1, .1], [2, 2, 17]),
                                       ([.1, .1, .1], [2, True, 2])):
            with self.subTest(dimensions=dimensions, resolution=resolution):
                with self.assertRaises(ValueError):
                    admission.cell_metrics(dimensions, resolution)


class SubstepModelTests(unittest.TestCase):
    """The substep count decides the bill, so it has to be the engine's own."""

    # Measured from native reports: build/drop-sweep/*.playback.json (the 8, 12
    # and 20 mm plates) and the four cubic calibration recordings of 2026-09-07.
    RECORDED = [
        ([.24, .36, .008], [8, 12, 2], 1 / 1920, 1587),
        ([.24, .36, .012], [8, 12, 2], 1 / 1920, 1377),
        ([.24, .36, .020], [8, 12, 2], 1 / 1920, 1176),
        ([.08, .08, .04], [4, 4, 2], 1 / 1920, 1299),
        ([.16, .16, .08], [8, 8, 4], 1 / 1920, 1514),
        ([.12, .12, .06], [6, 6, 3], 1 / 1920, 1514),
        ([.10, .10, .10], [5, 5, 5], 1 / 1920, 1514),
    ]

    def test_model_reproduces_every_recorded_substep_count_exactly(self):
        for dimensions, resolution, dt, expected in self.RECORDED:
            with self.subTest(dimensions=dimensions, resolution=resolution):
                # These geometries are what the engine ran; several are no
                # longer authorable, so build them directly rather than through
                # the guard.
                package = {"fixed_dt_s": dt, "materials": None,
                           "objects": [{"representation": "network", "material": "glass",
                                        "shape": "box", "dimensions_m": dimensions,
                                        "resolution": resolution}]}
                package["materials"] = json.loads(
                    (ROOT / "examples/authoring/presets.json").read_text(encoding="utf-8"))["materials"]
                self.assertEqual(
                    admission.package_substeps(package)["substeps_per_host_tick"], expected)

    def test_substeps_scale_inversely_with_the_smallest_cell(self):
        coarse = admission.package_substeps(glass_package([.24, .24, .24], [6, 6, 6]))
        fine = admission.package_substeps(glass_package([.12, .12, .12], [6, 6, 6]))
        self.assertAlmostEqual(fine["substeps_per_host_tick"] /
                               coarse["substeps_per_host_tick"], 2.0, delta=.02)

    def test_native_engine_agrees_with_the_model(self):
        executable = engine()
        if executable is None:
            self.skipTest("native platform CLI is not built")
        package = glass_package([.08, .08, .04], [2, 2, 2], dt=1 / 1920)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "package.json"
            path.write_text(json.dumps(package), encoding="utf-8")
            report = EngineCLI(executable, timeout_s=180).run(path, 1)
        native = report["network_substepping"]["substeps_per_host_tick"]
        self.assertEqual(admission.package_substeps(package)["substeps_per_host_tick"], native)
        self.assertEqual(admission.measured_substeps(report), native)

    def test_cost_estimate_carries_its_basis_and_the_recorder_byte_ceiling(self):
        estimate = admission.cost_estimate(glass_package([.24, .36, .04], [6, 9, 2]), 120)
        self.assertGreater(estimate["estimated_wall_s"], 0)
        self.assertLess(estimate["estimated_wall_low_s"], estimate["estimated_wall_s"])
        self.assertGreater(estimate["estimated_wall_high_s"], estimate["estimated_wall_s"])
        self.assertIn("us per network cell", estimate["basis"])
        self.assertFalse(estimate["recording_over_budget"])
        huge = admission.cost_estimate(glass_package([.6, .6, .6], [12, 12, 12]), 1440)
        self.assertTrue(huge["recording_over_budget"])
        self.assertGreater(huge["estimated_recording_mb"], 64)


class RepairTests(unittest.TestCase):
    def test_nearest_admissible_resolution_prefers_the_smallest_change(self):
        self.assertEqual(
            admission.nearest_admissible_resolution([.24, .36, .04], [4, 4, 2]), [6, 9, 2])
        # Without a request it answers the cheapest admissible mesh instead.
        self.assertEqual(admission.nearest_admissible_resolution([.24, .36, .04]), [6, 9, 2])
        self.assertIsNone(admission.nearest_admissible_resolution([.24, .36, .006], [6, 9, 2]))

    def test_drop_plan_is_snapped_and_the_change_is_reported_on_the_plan(self):
        plan = language.lower_and_admit(drop_proposal(resolution=[4, 4, 2]))
        self.assertEqual(plan["drop"]["resolution"], [6, 9, 2])
        self.assertEqual(plan["drop"]["target_dimensions_m"], [.24, .36, .04])
        self.assertEqual(len(plan["admission_notes"]), 1)
        note = plan["admission_notes"][0]
        self.assertEqual((note["limit"], note["action"]), ("cell_aspect_ratio", "snapped"))
        self.assertIn("4.50:1", note["message"])
        self.assertIn("The requested dimensions were not changed.", note["message"])
        # And the repaired plan is what actually compiles.
        target = language.compile_plan(plan)[0]["objects"][0]
        self.assertEqual(target["resolution"], [6, 9, 2])

    def test_an_already_admissible_plan_is_left_exactly_as_authored(self):
        plan = language.lower_and_admit(drop_proposal())
        self.assertNotIn("admission_notes", plan)
        self.assertEqual(plan["drop"]["resolution"], [6, 9, 2])

    def test_panel_routes_repair_the_preset_mesh_against_the_requested_panel(self):
        proposal = {"name": "Panel", "explanation": "A bounded local test.", "limitations": [],
                    "duration_s": .1, "ui": default_ui("panel_impact"), "requirements": [],
                    "fidelity": "experimental",
                    "setup": {"kind": "panel_impact", "speeds_m_s": [2.0],
                              "projectile": "iron_ball", "panel_dimensions_m": [.6, .3, .12]}}
        plan = language.lower_and_admit(proposal)
        # The shipped panel presets carry [6,9,2], which is 3:1 at this panel size.
        self.assertAlmostEqual(admission.cell_metrics([.6, .3, .12], [6, 9, 2])["aspect_ratio"], 3.0)
        self.assertNotEqual(plan["panel_resolution"], [6, 9, 2])
        metrics = admission.cell_metrics([.6, .3, .12], plan["panel_resolution"])
        self.assertLessEqual(metrics["aspect_ratio"], admission.MAX_CELL_ASPECT)
        self.assertTrue(plan["admission_notes"])
        for package in language.compile_plan(plan):
            for obj in package["objects"]:
                if obj["representation"] == "network":
                    self.assertEqual(obj["resolution"], plan["panel_resolution"])

    def test_scene_objects_are_repaired_individually_and_kept_in_budget(self):
        entry = {"preset": "glass_panel", "position_m": [0, .3, 0], "velocity_m_s": [0, 0, 0],
                 "dimensions_m": [.3, .2, .04], "orientation_wxyz": None, "spin_rad_s": None,
                 "representation": "network", "resolution": [3, 4, 5], "pin_boundary": True}
        proposal = {"name": "Scene", "explanation": "A bounded local test.", "limitations": [],
                    "duration_s": .1, "ui": default_ui("scene_test"), "requirements": [],
                    "fidelity": "experimental",
                    "setup": {"kind": "scene_test", "scene": {"objects": [entry],
                              "environment": {"gravity_m_s2": [0, -9.81, 0], "ground": True,
                                              "ground_friction": .3}}}}
        plan = language.lower_and_admit(proposal)
        chosen = plan["scene"]["objects"][0]["resolution"]
        self.assertLessEqual(
            admission.cell_metrics([.3, .2, .04], chosen)["aspect_ratio"], admission.MAX_CELL_ASPECT)
        self.assertLessEqual(chosen[0] * chosen[1] * chosen[2], admission.PLAYGROUND_CELL_BUDGET)
        self.assertTrue(plan["admission_notes"])


class RefusalTests(unittest.TestCase):
    def test_a_windowpane_is_refused_by_name_with_both_ways_out(self):
        with self.assertRaises(admission.Inadmissible) as caught:
            language.lower_and_admit(drop_proposal(target_dimensions_m=[.24, .36, .006]))
        self.assertEqual(caught.exception.limit, "slenderness_face_over_thickness")
        message = str(caught.exception)
        self.assertIn("60.0:1", message)
        self.assertIn("cannot exceed 12:1", message)
        self.assertIn("6:1 with strictly cubic cells", message)
        self.assertIn("0.03 m thick", message)
        self.assertIn("0.072 m face", message)
        self.assertIn("No substitute geometry was run.", message)

    def test_the_refusal_reaches_the_browser_as_a_named_failure(self):
        detail = __import__("server").describe_failure(
            None, admission.Inadmissible("Target: 60.0:1 face-to-thickness.",
                                         limit="slenderness_face_over_thickness"))
        self.assertEqual(detail["code"], "network_slenderness_face_over_thickness")
        self.assertIn("60.0:1", detail["detail"])
        self.assertIn("No substitute geometry was run", detail["scope"])


class BuilderTests(unittest.TestCase):
    def test_the_shipped_default_is_admissible_and_priced(self):
        result = builder.describe({})
        self.assertTrue(result["admissible"])
        self.assertEqual(result["geometry"]["spacing_mm"], [40, 40, 20])
        self.assertAlmostEqual(result["geometry"]["aspect_ratio"], 2.0)
        self.assertEqual(result["cost"]["network_cells"], 108)
        self.assertGreater(result["cost"]["estimated_wall_s"], 0)
        self.assertFalse(result["cost"]["recording_over_budget"])

    def test_an_inadmissible_setup_is_described_not_raised_and_offers_the_repair(self):
        result = builder.describe({"resolution": [4, 4, 2]})
        self.assertFalse(result["admissible"])
        self.assertEqual(result["problems"][0]["limit"], "cell_aspect_ratio")
        self.assertEqual(result["repair"]["resolution"], [6, 9, 2])
        self.assertGreater(result["repair"]["cost"]["estimated_wall_s"], 0)
        self.assertNotIn("package", result)

    def test_an_unbuildable_object_offers_dimensions_instead_of_a_resolution(self):
        result = builder.describe({"dimensions_m": [.5, .5, .006], "resolution": [6, 9, 2]})
        self.assertFalse(result["admissible"])
        self.assertIsNone(result["geometry"]["suggested_resolution"])
        self.assertAlmostEqual(result["repair"]["dimensions"]["slenderness"], 83.333, places=2)
        self.assertAlmostEqual(result["repair"]["dimensions"]["maximum_slenderness"], 16)
        self.assertAlmostEqual(result["repair"]["dimensions"]["thicken_to_m"], .0312)

    def test_compiling_an_inadmissible_setup_raises_rather_than_emitting_a_package(self):
        with self.assertRaises(admission.Inadmissible) as caught:
            builder.compile_builder({"resolution": [4, 4, 2]})
        self.assertEqual(caught.exception.limit, "cell_aspect_ratio")

    def test_the_compiled_package_matches_what_was_asked_for(self):
        package = builder.compile_builder({"material": "oak", "impact_speed_m_s": 3.5,
                                           "projectile": "iron_cube", "projectile_size_m": .05})
        target, striker = package["objects"]
        self.assertEqual(target["material"], "oak")
        self.assertEqual(target["dimensions_m"], [.24, .36, .04])
        self.assertEqual(target["resolution"], [6, 9, 2])
        self.assertTrue(target["pin_boundary"])
        self.assertEqual(striker["velocity_m_s"], [0, -3.5, 0])
        self.assertEqual(striker["dimensions_m"], [.05, .05, .05])
        # Clear of the target's top face by the declared 2 mm, not intersecting it.
        self.assertAlmostEqual(striker["position_m"][1], .18 + .02 + .025 + .002)

    def test_every_field_is_bounded(self):
        for change in ({"material": "unobtainium"}, {"resolution": [1, 4, 4]},
                       {"resolution": [4, 4, 17]}, {"dimensions_m": [.24, .36]},
                       {"impact_speed_m_s": 25}, {"projectile_size_m": .4},
                       {"tick_rate_hz": 300}, {"duration_s": 2}, {"support": "floating"},
                       {"impact_offset_m": [.2, 0]}, {"unknown": 1}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                builder.validate_builder(change)

    def test_native_engine_accepts_every_admissible_builder_setup_it_is_offered(self):
        executable = engine()
        if executable is None:
            self.skipTest("native platform CLI is not built")
        cli = EngineCLI(executable, timeout_s=180)
        setups = [{}, {"material": "iron", "dimensions_m": [.08, .08, .04], "resolution": [2, 2, 2]},
                  {"material": "oak", "support": "free_on_ground", "projectile": "none"}]
        with tempfile.TemporaryDirectory() as directory:
            for index, setup in enumerate(setups):
                described = builder.describe(setup)
                self.assertTrue(described["admissible"], described.get("problems"))
                path = Path(directory) / f"builder-{index}.json"
                path.write_text(json.dumps(described["package"]), encoding="utf-8")
                report = cli.validate(path)
                with self.subTest(setup=setup):
                    self.assertTrue(all(item["mass_kg"] > 0 for item in report["objects"]))


if __name__ == "__main__":
    unittest.main()
