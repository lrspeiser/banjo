"""Discovery safety and missing-binary gates, independent of native builds."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("regression", ROOT / "scripts/regression.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class Discovery(unittest.TestCase):
    def test_missing_command_and_library_cannot_be_ready(self):
        report = runner.describe({"tests": [
            {"name": "native"}, {"name": "ffi", "command": [sys.executable],
             "properties": [{"name": "ENVIRONMENT", "value": ["BANJO_LIBRARY=/missing/banjo.dll"]}]}]})
        self.assertFalse(report["ready"])
        self.assertTrue(all(row["issues"] for row in report["selected"]))

    def test_profiles_and_filters_record_exclusions(self):
        tests = [{"name": name, "command": [sys.executable], "properties": [
            {"name": "LABELS", "value": labels}]} for name, labels in
            [("ordinary", []), ("capacity", ["long"]), ("timing", ["performance"])]]
        ordinary = runner.describe({"tests": tests})
        self.assertTrue(ordinary["ready"])
        self.assertEqual([r["name"] for r in ordinary["selected"]], ["ordinary"])
        self.assertEqual(len(runner.describe({"tests": tests}, include_all=True)["selected"]), 3)
        self.assertFalse(runner.describe({"tests": tests}, pattern="nothing")["ready"])

    def test_inline_cmake_environment_also_requires_native_artifacts(self):
        report = runner.describe({'tests':[{'name':'native-inline', 'command':[
            sys.executable, '-E', 'env', 'BANJO_LIVE_ENGINE=/missing/native.exe', sys.executable]}]})
        self.assertFalse(report['ready'])
        self.assertIn('BANJO_LIVE_ENGINE artifact is missing', report['selected'][0]['issues'])

    def test_list_only_calls_discovery_and_does_not_create_output(self):
        with tempfile.TemporaryDirectory() as temp:
            build = Path(temp)
            (build / "CMakeCache.txt").write_text("test fixture")
            with mock.patch.object(runner, "discover", return_value=runner.describe({"tests": []})) as discover, \
                    mock.patch.object(runner, "owned_run") as run, mock.patch("builtins.print"):
                self.assertEqual(runner.main(["--build-dir", temp, "--list"]), 0)
            discover.assert_called_once()
            run.assert_not_called()
            self.assertEqual([p.name for p in build.iterdir()], ["CMakeCache.txt"])

    def test_check_fails_without_running_or_building(self):
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp) / "CMakeCache.txt").write_text("test fixture")
            with mock.patch.object(runner, "discover", return_value=runner.describe({"tests": [{"name": "missing"}]})), \
                    mock.patch.object(runner, "owned_run") as run, mock.patch("builtins.print"):
                self.assertEqual(runner.main(["--build-dir", temp, "--check"]), 1)
            run.assert_not_called()

    def test_child_finishes_without_touching_an_unrelated_live_process(self):
        other = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(60)"])
        try:
            self.assertEqual(runner.owned_run([sys.executable, "-c", "pass"], env=None, cwd=ROOT), 0)
            self.assertIsNone(other.poll())
        finally:
            other.terminate()
            other.wait(timeout=5)

    def test_real_ctest_selection_records_failed_test_and_excludes_extended(self):
        with tempfile.TemporaryDirectory() as temp:
            build = Path(temp)
            (build / 'CMakeCache.txt').write_text('test fixture')
            python = Path(sys.executable).as_posix()
            (build / 'CTestTestfile.cmake').write_text(
                f'add_test(ordinary "{python}" "-c" "raise SystemExit(1)")\n'
                f'add_test(extended "{python}" "-c" "raise SystemExit(99)")\n'
                'set_tests_properties(extended PROPERTIES LABELS "long")\n')
            with mock.patch('builtins.print'):
                code = runner.main(['--build-dir', temp, '--no-build', '--output-dir', str(build/'report')])
            self.assertNotEqual(code, 0)
            report = json.loads((build/'report/discovery.json').read_text())
            self.assertEqual([r['name'] for r in report['selected']], ['ordinary'])
            self.assertTrue((build/'report/results.xml').is_file())
            self.assertEqual(json.loads((build/'report/run.json').read_text())['exit_code'], code)


if __name__ == "__main__":
    unittest.main()
