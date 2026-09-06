import math
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "playground"))
from drop_builder import DROP_SCHEMA, compile_drop, validate_drop
sys.path.insert(0, str(ROOT / "examples" / "authoring"))
from banjo_authoring import EngineCLI, write_package


def spec(**changes):
    value = {
        "target_dimensions_m": [.24, .36, .04],
        "projectile": "iron_ball",
        "projectile_dimensions_m": [.08, .08, .08],
        "support": "clamped_edges",
        "impact_offset_m": [.015, -.02],
        "heights_m": [.25, 1.0],
        "representation": "network",
        "resolution": [6, 9, 2],
    }
    value.update(changes)
    return value


class DropBuilderTests(unittest.TestCase):
    def test_schema_is_strict_and_fully_required(self):
        self.assertEqual(DROP_SCHEMA["type"], "object")
        self.assertFalse(DROP_SCHEMA["additionalProperties"])
        self.assertEqual(set(DROP_SCHEMA["required"]), set(DROP_SCHEMA["properties"]))
        with self.assertRaisesRegex(ValueError, "unknown or missing"):
            validate_drop(None)
        bad = spec(extra=True)
        with self.assertRaisesRegex(ValueError, "unknown or missing"):
            validate_drop(bad)

    def test_validation_rejects_geometry_support_and_budget_before_authoring(self):
        bad_cases = [
            (spec(target_dimensions_m=[.079, .36, .04]), "target_dimensions"),
            (spec(target_dimensions_m=[.24, .36, .0039]), "target_dimensions"),
            (spec(projectile_dimensions_m=[.08, .081, .08]), "equal"),
            (spec(impact_offset_m=[.121, 0]), "impact_offset"),
            (spec(heights_m=[]), "one to four"),
            (spec(support="clamped_edges", representation="rigid"), "requires the network"),
            (spec(support="free_on_ground", representation="network"), "requires the rigid"),
            (spec(resolution=[12, 12, 2]), "850-cell"),
        ]
        for value, message in bad_cases:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                validate_drop(value)

    def test_network_compilation_preserves_matched_geometry_support_and_explicit_offset(self):
        packages = compile_drop({"experiment": "drop_test", "name": "General drop", "drop": spec()})
        self.assertEqual(len(packages), 2)
        for package, height in zip(packages, (.25, 1.0)):
            self.assertEqual([m["id"] for m in package["materials"]], ["glass", "oak", "iron"])
            targets = package["objects"][::2]
            projectiles = package["objects"][1::2]
            self.assertEqual([o["material"] for o in targets], ["glass", "oak", "iron"])
            for target, projectile in zip(targets, projectiles):
                self.assertEqual(target["dimensions_m"], [.24, .36, .04])
                self.assertEqual(target["resolution"], [6, 9, 2])
                self.assertTrue(target["pin_boundary"])
                self.assertEqual(target["position_m"][1], .18)
                self.assertAlmostEqual(projectile["position_m"][0] - target["position_m"][0], .015)
                self.assertEqual(projectile["position_m"][2], -.02)
                self.assertAlmostEqual(projectile["position_m"][1], .18 + .02 + .04 + height)
            self.assertIn("damage_integration", package)
            self.assertNotIn("fracture", package)
            self.assertLessEqual(3 * math.prod([6, 9, 2]), 850)

    def test_free_rigid_targets_touch_ground_and_have_material_derived_mass_inputs(self):
        rigid = spec(
            projectile="iron_cube", projectile_dimensions_m=[.06, .07, .08],
            support="free_on_ground", representation="rigid", resolution=[12, 12, 12],
            heights_m=[0], impact_offset_m=[0, 0])
        package = compile_drop({"experiment": "drop_test", "drop": rigid})[0]
        for target, projectile in zip(package["objects"][::2], package["objects"][1::2]):
            self.assertEqual(target["position_m"][1], .02)
            self.assertEqual(target["representation"], "rigid")
            for field in ("resolution", "pin_boundary", "grain_wxyz"):
                self.assertNotIn(field, target)
            self.assertEqual(projectile["position_m"][1], .02 + .02 + .035)
            self.assertNotIn("mass_kg", target)
            self.assertNotIn("mass_kg", projectile)
        self.assertNotIn("damage_integration", package)

    def test_null_drop_is_noop_and_mismatched_root_rejects(self):
        self.assertEqual(compile_drop({"experiment": "panel_impact", "drop": None}), [])
        with self.assertRaisesRegex(ValueError, "experiment=drop_test"):
            compile_drop({"experiment": "panel_impact", "drop": spec()})

    def test_compiled_network_and_rigid_packages_admit_natively_when_cli_exists(self):
        candidates = [
            ROOT / "build" / "ci" / "banjo_platform_cli",
            ROOT / "build" / "win-joint-double" / "Release" / "banjo_platform_cli.exe",
            ROOT / "build" / "win-integration" / "Release" / "banjo_platform_cli.exe",
        ]
        executable = next((path for path in candidates if path.exists()), None)
        if executable is None:
            self.skipTest("native platform CLI is not built")
        cases = [
            spec(target_dimensions_m=[.24, .36, .006], heights_m=[.05]),
            spec(support="free_on_ground", representation="rigid", heights_m=[.25]),
        ]
        with tempfile.TemporaryDirectory() as directory:
            for index, drop in enumerate(cases):
                package = compile_drop({"experiment": "drop_test", "drop": drop})[0]
                path = write_package(package, Path(directory) / f"drop-{index}.json")
                report = EngineCLI(executable).validate(path)
                self.assertEqual(len(report["objects"]), 6)
                self.assertTrue(all(item["mass_kg"] > 0 for item in report["objects"]))
                if index == 0:
                    # This checks executable network diagnostics only. A 6 mm
                    # volume network is not a shell or a calibrated thin plate.
                    result = EngineCLI(executable).run(path, 24)
                    self.assertEqual(result["ticks"], 24)
                    self.assertAlmostEqual(result["elapsed_s"], .05)
                    self.assertEqual(len(result["objects"]), 6)


if __name__ == "__main__":
    unittest.main()
