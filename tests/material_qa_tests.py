"""QA coverage, native protocol, failure handling, persistence and API parity."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "playground"), str(ROOT / "tests")]
import material_qa as qa
from workbench_tests import WorkbenchTestCase
from mcp import material_qa_tools, workshop_mcp_tools

def fixture():
    native = {
        "cells": 288, "bonds": 1000, "dt_s": 1e-6, "tile_mass_kg": .72, "ball_mass_kg": .25,
        "simulated_total_s": .351,
        "lattice": {"broken_bonds": 0, "removed_energy_j": 0, "simulated_s": .001,
                    "exit_reason": 5, "energy": {"initial_kinetic_j": .125},
                    "contact": {"impulse_to_material_n_s": [0, -.25, 0], "impulse_contacts": 1,
                                "maximum_penetration_m": .00001},
                    "node_contact": {"pair_overflow": 0},
                    "dissipated_kinetic_energy_j": {"striker_contact": .01}},
        "handoff": {"components": 1, "largest_piece_mass_kg": .72},
        "rigid": {"came_to_rest": False},
    }
    poses = [{"id": "cell:" + str(i), "position_m": [0, .1, 0],
              "orientation_wxyz": [1, 0, 0, 0]} for i in range(288)]
    recording = {"schema": "banjo.playback.v1", "status": "complete",
                 "frames": [{"time_s": 0, "poses": poses}, {"time_s": .351, "poses": deepcopy(poses)}],
                 "report": native}
    return native, recording

class Contracts(unittest.TestCase):
    def test_all_materials_thicknesses_speeds_and_resolved_layers(self):
        rows = qa.select()
        self.assertEqual(len(rows), 96)
        self.assertEqual(len({r["id"] for r in rows}), 96)
        self.assertEqual({r["material"] for r in rows}, set(qa.fracture_lab.MATERIALS))
        for row in rows:
            spec = qa.spec(row)
            self.assertEqual(spec["cells_per_axis"][2], row["thickness_mm"] // 10)
            self.assertGreaterEqual(spec["cells_per_axis"][2], 2)
            self.assertEqual(spec["cells"], 144 * row["thickness_mm"] // 10)

    def test_committed_baseline_covers_the_whole_current_fixture(self):
        baseline = qa.read_json(qa.BASELINE)
        self.assertEqual(baseline["fixture_hash"], qa.digest(qa.manifest()))
        self.assertEqual({r["id"] for r in baseline["results"]}, {c["id"] for c in qa.cases()})
        self.assertTrue(all(r["status"] == "passed" for r in baseline["results"]))

    def test_unowned_running_report_does_not_claim_the_process_stopped(self):
        with tempfile.TemporaryDirectory() as raw:
            manager = qa.Manager(mock.Mock(runs_path=Path(raw), engine_path=None))
            run_id = "c" * 32
            qa.write_json(manager.folder(run_id) / "report.json", {"id": run_id, "status": "running"})
            self.assertEqual(manager.status(run_id)["status"], "unattached")
            self.assertEqual(qa.read_json(manager.folder(run_id) / "report.json")["status"], "running")

    def test_bad_ids_and_unbounded_inputs_are_refused(self):
        for ids in ([], ["../report"], ["glass-20mm-1mps"] * 2, "all", [None], [True]):
            with self.assertRaises(ValueError): qa.select(ids)
        with tempfile.TemporaryDirectory() as raw:
            manager = qa.Manager(mock.Mock(runs_path=Path(raw), engine_path=None))
            for run_id in ("../other", "/absolute", "", "g" * 32):
                with self.assertRaises(ValueError): manager.folder(run_id)
            with self.assertRaises(ValueError): manager.start({"command": ["dangerous"]})

    def test_cell_loss_duplicate_nan_no_contact_and_overflow_fail(self):
        case = qa.cases()[0]
        self.assertEqual(qa.check_run(*fixture(), case), [])
        for mutate, expected in (
            (lambda n, r: r["frames"][-1]["poses"].pop(), "cell identity"),
            (lambda n, r: r["frames"][-1]["poses"].append(r["frames"][-1]["poses"][0]), "cell identity"),
            (lambda n, r: n.update(dt_s=float("nan")), "nonfinite"),
            (lambda n, r: n["lattice"]["contact"].update(impulse_contacts=0), "never contacted"),
            (lambda n, r: n["lattice"]["node_contact"].update(pair_overflow=1), "overflow"),
            (lambda n, r: n["lattice"]["energy"].update(initial_kinetic_j=9), "initial striker"),
        ):
            n, r = fixture()
            mutate(n, r)
            self.assertTrue(any(expected in e for e in qa.check_run(n, r, case)), expected)

    def test_baseline_flags_physical_changes_not_exact_piece_count(self):
        metrics = qa.metrics(*fixture())
        same = deepcopy(metrics)
        self.assertEqual(qa.compare(same, metrics), [])
        same["components"] = 7
        self.assertEqual(qa.compare(same, metrics), [])
        same["removed_energy_j"] = 5
        self.assertTrue(qa.compare(same, metrics))
        same["outcome"] = "fragmented"
        self.assertTrue(any("outcome" in x for x in qa.compare(same, metrics)))

    def test_native_wrapper_is_parsed_and_recording_checked(self):
        n, r = fixture()
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw) / "case"
            def command(*_):
                code = ("import pathlib; p=pathlib.Path(" + repr(str(folder)) + ");"
                        "(p/'native-report.json').write_text(" + repr(json.dumps({"measurements": n})) + ");"
                        "(p/'playback.json').write_text(" + repr(json.dumps(r)) + ")")
                script = folder.parent / "fake-native.py"
                script.write_text(code, encoding="utf-8")
                return [sys.executable, str(script)]
            with mock.patch.object(qa, "command", side_effect=command):
                row = qa.run_case(Path(sys.executable), qa.cases()[0], folder, threading.Event())
            self.assertEqual(row["status"], "passed")
            self.assertEqual(row["metrics"]["cells"], 288)
            self.assertIsNone(row["metrics"]["peak_force_n"])

    def test_timeout_and_cancel_reap_the_native_child(self):
        real_popen = subprocess.Popen
        for cancelled in (False, True):
            with self.subTest(cancelled=cancelled), tempfile.TemporaryDirectory() as raw:
                children = []
                def launch(*args, **kwargs):
                    child = real_popen(*args, **kwargs); children.append(child); return child
                event = threading.Event()
                if cancelled: event.set()
                with mock.patch.object(qa, "command", return_value=[sys.executable, "-c", "import time;time.sleep(30)"]), \
                     mock.patch.object(qa.subprocess, "Popen", side_effect=launch), \
                     mock.patch.object(qa, "CASE_TIMEOUT_S", .05):
                    with self.assertRaises(InterruptedError if cancelled else TimeoutError):
                        qa.run_case(Path(sys.executable), qa.cases()[0], Path(raw) / "case", event)
                self.assertIsNotNone(children[0].poll())

    def test_missing_baseline_and_fixture_drift_cannot_pass(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw); exe = root / "banjo_fast_lattice_run"; exe.touch()
            with self.assertRaisesRegex(ValueError, "missing"):
                qa.run_suite(exe, root / "missing", [qa.cases()[0]["id"]], root / "absent.json")
            qa.write_json(root / "bad.json", {"fixture_hash": "different"})
            with self.assertRaisesRegex(ValueError, "differs"):
                qa.run_suite(exe, root / "drift", [qa.cases()[0]["id"]], root / "bad.json")

    def test_manager_rejects_concurrency_and_keeps_cancelled_evidence(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw); exe = root / "banjo_fast_lattice_run"; exe.touch()
            app = mock.Mock(runs_path=root, engine_path=exe)
            manager = qa.Manager(app); entered = threading.Event()
            def run(engine, directory, ids, cancel):
                qa.write_json(directory / "report.json", {"id": directory.name, "status": "running"})
                entered.set(); cancel.wait(5)
                qa.write_json(directory / "report.json", {"id": directory.name, "status": "cancelled"})
            with mock.patch.object(qa, "run_suite", side_effect=run):
                first = manager.start({"case_ids": [qa.cases()[0]["id"]]})
                self.assertTrue(entered.wait(2))
                with self.assertRaisesRegex(ValueError, "already running"): manager.start({})
                manager.cancel(first["id"]); manager.shutdown()
            self.assertEqual(manager.status(first["id"])["status"], "cancelled")
            self.assertEqual(qa.Manager(app).status(first["id"])["status"], "cancelled")

class Api(WorkbenchTestCase):
    def test_routes_and_mcp_read_identical_saved_evidence(self):
        app = self.start()
        self.assertEqual(len(self.get(app, "/api/material-qa")["cases"]), 96)
        manager = qa.manager(app)
        run_id, case_id = "a" * 32, qa.cases()[0]["id"]
        folder = manager.folder(run_id)
        qa.write_json(folder / "report.json", {"id": run_id, "status": "passed", "results": []})
        qa.write_json(folder / case_id / "result.json", {"id": case_id, "status": "passed", "measured": 123})
        qa.write_json(folder / case_id / "playback.json", fixture()[1])
        qa.write_json(folder / case_id / "native-report.json", {"measurements": fixture()[0]})
        base = "/api/material-qa/runs/" + run_id
        with mock.patch.object(workshop_mcp_tools, "APP", app):
            self.assertEqual(self.get(app, base), material_qa_tools.status({"run_id": run_id}))
            self.assertEqual(self.get(app, base + "/" + case_id), material_qa_tools.case({"run_id": run_id, "case_id": case_id}))
            self.assertEqual(self.get(app, "/api/material-qa/runs"), material_qa_tools.status({}))
        self.assertEqual(self.get(app, base + "/" + case_id + "/playback")["schema"], "banjo.playback.v1")
        self.assertIn("measurements", self.get(app, base + "/" + case_id + "/native"))
        status, mime, html = self.request(app, "GET", "/qa")
        self.assertEqual(status, 200); self.assertIn("text/html", mime); self.assertIn(b"Hold crack frames", html)

    def test_http_mutations_do_not_touch_world_and_validate_ids(self):
        app = self.start(); live = app.live
        with mock.patch.object(qa.Manager, "start", return_value={"id": "b" * 32, "status": "starting"}) as start:
            status, _, raw = self.request(app, "POST", "/api/material-qa/run", {"case_ids": [qa.cases()[0]["id"]]})
            self.assertEqual(status, 202, raw); self.assertEqual(start.call_count, 1)
        status, _, raw = self.request(app, "POST", "/api/material-qa/cancel", {"run_id": "../bad"})
        self.assertEqual(status, 400, raw); self.assertIs(app.live, live)
        status, _, _ = self.request(app, "GET", "/api/material-qa/runs/" + "a" * 32 + "/unlisted")
        self.assertEqual(status, 400)

if __name__ == "__main__": unittest.main()
