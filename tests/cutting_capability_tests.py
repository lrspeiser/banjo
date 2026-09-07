import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUTHORING = ROOT / "examples" / "authoring"
sys.path.insert(0, str(AUTHORING))

from banjo_authoring import EngineCLI  # noqa: E402
from verify_physics import _knife_tomato_scene  # noqa: E402


def native_path() -> Path:
    configured = os.environ.get("BANJO_PLATFORM_CLI")
    if configured:
        return Path(configured)
    candidates = [
        ROOT / "build" / "ci" / "banjo_platform_cli",
        ROOT / "build" / "win-joint-double" / "Release" / "banjo_platform_cli.exe",
        ROOT / "build" / "win-integration" / "Release" / "banjo_platform_cli.exe",
    ]
    return next((path for path in candidates if path.is_file()), candidates[0])


class CuttingCapabilityTests(unittest.TestCase):
    @unittest.skipUnless(native_path().is_file(), "native platform CLI is not built")
    def test_public_knife_route_executes_computed_local_separation(self):
        package = _knife_tomato_scene()
        self.assertEqual(package["backend"], "material-network-v2")
        tomato = next(item for item in package["objects"] if item["id"] == 1)
        knife = next(item for item in package["objects"] if item["id"] == 2)
        self.assertEqual((tomato["shape"], tomato["representation"]),
                         ("ellipsoid", "network"))
        self.assertEqual((knife["shape"], knife["representation"]),
                         ("wedge", "rigid"))
        self.assertEqual(knife["velocity_m_s"], [0.0, -4.0, 0.0])

        control = json.loads(json.dumps(package))
        control["objects"] = [item for item in control["objects"] if item["id"] == 1]
        refined = _knife_tomato_scene(fixed_dt_s=1 / 960)

        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            engine = EngineCLI(native_path(), timeout_s=75)
            def execute(name, authored, steps):
                path = directory / f"{name}.json"
                path.write_text(json.dumps(authored), encoding="utf-8")
                return engine.run(path, steps)

            initial_path = directory / "initial.json"
            initial_path.write_text(json.dumps(package), encoding="utf-8")
            initial = engine.validate(initial_path)
            result = execute("knife-coarse", package, 192)
            absent_result = execute("blade-absent-control", control, 192)
            refined_result = execute("knife-refined", refined, 384)

        initial_tomato = next(item for item in initial["objects"] if item["id"] == 1)
        final_tomato = next(item for item in result["objects"] if item["id"] == 1)
        self.assertGreater(final_tomato["damaged_links"], 0)
        self.assertGreater(final_tomato["broken_links"], 0)
        self.assertLess(final_tomato["broken_links"], final_tomato["links"])
        self.assertGreater(result["fracture_work_j"], 0.0)
        self.assertEqual(final_tomato["cells"], initial_tomato["cells"])
        self.assertAlmostEqual(final_tomato["mass_kg"], initial_tomato["mass_kg"], places=12)
        self.assertGreaterEqual(final_tomato["largest_component_cells"] * 4,
                                final_tomato["cells"] * 3)
        self.assertTrue(result["fracture_events"])
        self.assertIn("wedge sharpness below cell spacing unresolved",
                      " ".join(result["limitations"]))

        absent_tomato = next(item for item in absent_result["objects"] if item["id"] == 1)
        refined_tomato = next(item for item in refined_result["objects"] if item["id"] == 1)
        self.assertEqual(absent_tomato["damaged_links"], 0)
        self.assertEqual(absent_tomato["broken_links"], 0)
        self.assertEqual(absent_result["fracture_work_j"], 0.0)
        for observed in (final_tomato, refined_tomato):
            self.assertGreater(observed["damaged_links"], absent_tomato["damaged_links"])
            self.assertGreater(observed["broken_links"], absent_tomato["broken_links"])
            self.assertLess(observed["broken_links"], observed["links"])
            self.assertEqual(observed["components"], 1)
            self.assertEqual(observed["largest_component_cells"], observed["cells"])
            self.assertAlmostEqual(observed["mass_kg"], initial_tomato["mass_kg"], places=12)
        self.assertGreater(refined_result["fracture_work_j"], 0.0)


if __name__ == "__main__":
    unittest.main()
