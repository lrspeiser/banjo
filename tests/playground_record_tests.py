"""Native integration checks for the bounded browser playback recorder.

Run from the repository root after building Release:
    python tests/playground_record_tests.py -v

The report parity check deliberately excludes host timing/compiler metadata,
per-step profiling, and derived skin-query counters. Those fields can change
between otherwise identical native processes and do not describe physics state.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "playground"))
import experiment_language as language


def plan_for(experiment: str) -> dict:
    return {
        "language": "banjo-playground-1",
        "name": f"Native recorder {experiment} integration",
        "experiment": experiment,
        "explanation": "An uncalibrated native integration fixture.",
        "limitations": ["This fixture checks recording fidelity, not material realism."],
        "speeds_m_s": [],
        "heights_m": [0.25],
        "duration_s": 2.0,
        "projectile": "iron_ball",
        "panel_dimensions_m": [0.24, 0.36, 0.04],
        "objects": [],
    }


def json_stdout(process: subprocess.CompletedProcess[str]) -> dict:
    try:
        return json.loads(process.stdout)
    except json.JSONDecodeError as error:
        raise AssertionError(
            f"native command returned invalid JSON\nstdout: {process.stdout}\nstderr: {process.stderr}"
        ) from error


def physics_report(report: dict) -> dict:
    result = deepcopy(report)
    # Added only by banjo_platform_cli around PlatformWorld's authoritative report.
    result.pop("load_wall_ms", None)
    result.pop("compiler", None)
    # Wall-clock samples differ between processes and are explicitly non-rendering.
    result.pop("performance", None)
    # Recorder queries render instances/bonds, while skin counters describe derived
    # visualization work rather than accepted physical state.
    result.pop("skin", None)
    return result


class PlaygroundRecordIntegrationTests(unittest.TestCase):
    _default_binary = ROOT / "build" / "win-joint-double" / "Release"
    recorder = _default_binary / "banjo_playground_record.exe"
    engine = _default_binary / "banjo_platform_cli.exe"

    @classmethod
    def setUpClass(cls) -> None:
        for binary in (cls.recorder, cls.engine):
            if not binary.is_file():
                raise unittest.SkipTest(f"native binary not built: {binary}")

    def native(self, *arguments: object) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(arguments[0]), *(str(value) for value in arguments[1:])],
            cwd=ROOT, text=True, capture_output=True, timeout=180, check=False,
        )

    def write_package(self, directory: Path, experiment: str) -> Path:
        packages = language.compile_plan(plan_for(experiment))
        self.assertEqual(len(packages), 1)
        path = directory / f"{experiment}.json"
        path.write_text(json.dumps(packages[0]), encoding="utf-8")
        return path

    def record(self, package: Path, output: Path, steps: int) -> dict:
        process = self.native(
            self.recorder, "--package", package, "--steps", steps, "--output", output
        )
        message = json_stdout(process)
        self.assertEqual(process.returncode, 0, message)
        self.assertTrue(output.is_file(), message)
        return json.loads(output.read_text(encoding="utf-8"))

    def assert_recording_contract(self, artifact: dict, requested_steps: int) -> None:
        self.assertEqual(artifact["schema"], "banjo.playback.v1")
        self.assertEqual(artifact["mode"], "network")
        self.assertEqual(artifact["units"], "SI")
        self.assertFalse(artifact["physical_response_validated"])
        self.assertEqual(artifact["requested_steps"], requested_steps)
        self.assertEqual(artifact["sampling"]["interpolation"], "none")
        self.assertEqual(artifact["sampling"]["maximum_frames"], 122)
        self.assertLessEqual(len(artifact["frames"]), 122)
        self.assertEqual(artifact["frames"][0]["time_s"], 0)
        ids = {body["id"] for body in artifact["bodies"]}
        self.assertEqual(len(ids), len(artifact["bodies"]))
        for endpoint in (artifact["frames"][0], artifact["frames"][-1]):
            pose_ids = [pose["id"] for pose in endpoint["poses"]]
            self.assertEqual(len(pose_ids), len(set(pose_ids)))
            self.assertLessEqual(set(pose_ids), ids)

    def test_rigid_matched_drop_records_motion_and_matches_headless_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            package = self.write_package(directory, "rigid_drop")
            artifact = self.record(package, directory / "rigid.playback.json", 240)
            self.assert_recording_contract(artifact, 240)
            self.assertEqual(artifact["status"], "complete")
            self.assertEqual(artifact["completed_steps"], 240)
            self.assertEqual(artifact["error"], "")
            self.assertEqual(len(artifact["supports"]), 2)
            materials = {body["material_id"].lower() for body in artifact["bodies"]}
            self.assertTrue(any("glass" in material for material in materials))
            self.assertTrue(any("oak" in material for material in materials))
            self.assertTrue(any("iron" in material for material in materials))
            initial = {pose["id"]: pose["position_m"] for pose in artifact["frames"][0]["poses"]}
            final = {pose["id"]: pose["position_m"] for pose in artifact["frames"][-1]["poses"]}
            self.assertTrue(any(initial[body_id] != final[body_id] for body_id in initial))

            run = self.native(self.engine, "--run", package, 240)
            run_report = json_stdout(run)
            self.assertEqual(run.returncode, 0, run_report)
            self.assertEqual(physics_report(artifact["report"]), physics_report(run_report))

    def test_plate_drop_480_preserves_all_authored_cells_and_actual_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            package = self.write_package(directory, "plate_drop")
            artifact = self.record(package, directory / "plate.playback.json", 480)
            self.assert_recording_contract(artifact, 480)
            self.assertIn(artifact["status"], ("complete", "solver_limit"))
            self.assertEqual(len(artifact["frames"][0]["poses"]), artifact["report"]["cells"])
            self.assertEqual(len(artifact["bodies"]), artifact["report"]["cells"])
            self.assertEqual(artifact["frames"][-1]["time_s"], artifact["report"]["elapsed_s"])
            self.assertEqual(
                artifact["frames"][-1]["fracture_count"], artifact["report"]["broken_links"]
            )
            if artifact["status"] == "solver_limit":
                self.assertTrue(artifact["error"])
                self.assertLess(artifact["completed_steps"], 480)

    def test_output_guards_and_step_bound_reject_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            package = self.write_package(directory, "rigid_drop")
            original = package.read_bytes()

            same = self.native(
                self.recorder, "--package", package, "--steps", 1, "--output", package
            )
            self.assertNotEqual(same.returncode, 0)
            self.assertIn("error", json_stdout(same))
            self.assertEqual(package.read_bytes(), original)

            existing = directory / "existing.json"
            existing.write_text("sentinel", encoding="utf-8")
            occupied = self.native(
                self.recorder, "--package", package, "--steps", 1, "--output", existing
            )
            self.assertNotEqual(occupied.returncode, 0)
            self.assertIn("error", json_stdout(occupied))
            self.assertEqual(existing.read_text(encoding="utf-8"), "sentinel")

            excessive = directory / "excessive.json"
            rejected = self.native(
                self.recorder, "--package", package, "--steps", 1441, "--output", excessive
            )
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("error", json_stdout(rejected))
            self.assertFalse(excessive.exists())


def parse_arguments() -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(add_help=False)
    binary = ROOT / "build" / "win-joint-double" / "Release"
    parser.add_argument("--recorder", type=Path, default=binary / "banjo_playground_record.exe")
    parser.add_argument("--engine", type=Path, default=binary / "banjo_platform_cli.exe")
    return parser.parse_known_args()


if __name__ == "__main__":
    options, unittest_arguments = parse_arguments()
    PlaygroundRecordIntegrationTests.recorder = options.recorder.resolve()
    PlaygroundRecordIntegrationTests.engine = options.engine.resolve()
    unittest.main(argv=[sys.argv[0], *unittest_arguments])
