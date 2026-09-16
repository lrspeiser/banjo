"""Workshop functional bench through the same API surface the browser uses."""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "playground"))

import workshop_api  # noqa: E402


class App:
    def __init__(self, root: Path) -> None:
        self.workshop_store = root / "workshop"
        self.workshop_db = root / "banjo.db"
        self.runs_path = root / "runs"
        self.engine_path = root / "engine"
        self.api_key = ""


class BenchAPI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = App(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_opening_workshop_describes_functional_tests_and_saved_presets(self):
        opened = workshop_api.open_workshop(self.app, {"kind": "table"})
        self.assertEqual({"kettle_heat", "machine_control"},
                         {test["test"] for test in opened["bench_tests"]})
        self.assertEqual([], opened["bench_presets"])

        saved = workshop_api.library(self.app, {
            "action": "save_bench_preset", "name": "Gentle lift",
            "test": "machine_control", "config": {"setting": 35, "direction": 1},
        })
        self.assertEqual("Gentle lift", saved["bench_preset"]["name"])
        again = workshop_api.open_workshop(self.app, {"kind": "table"})
        self.assertEqual("Gentle lift", again["bench_presets"][0]["name"])

    def test_plan_runs_requested_bench_fixture_and_keeps_normal_materialization(self):
        evidence = {"schema": "banjo.workshop-bench.v1", "test": "machine_control",
                    "evidence": "engine-trial", "measured": {"load_delta_y_m": 0.2}}
        with mock.patch.object(workshop_api.workshop_bench, "run", return_value=evidence) as run:
            answer = workshop_api.plan(self.app, {
                "kind": "table", "design_id": "candidate",
                "bench_test": {"test": "machine_control", "config": {"setting": 50}},
            })
        self.assertEqual("not-committed", answer["commit"]["status"])
        self.assertEqual(evidence, answer["bench"])
        self.assertEqual("candidate", run.call_args.args[1].design_id)
        self.assertEqual("machine_control", run.call_args.args[2]["test"])


if __name__ == "__main__":
    unittest.main()
