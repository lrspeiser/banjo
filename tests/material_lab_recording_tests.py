"""Actual bounded CPU experiments and local host contracts; no canned trajectory."""
import functools
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from http.server import ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]
NATIVE = Path(sys.argv.pop(1)).resolve() if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else None


class Recording(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if NATIVE is None or not NATIVE.is_file():
            raise RuntimeError("Compiled material lab recorder executable is required")
        cls.temp = tempfile.TemporaryDirectory()
        cls.output = Path(cls.temp.name) / "material.json"
        subprocess.run([str(NATIVE), str(cls.output)], check=True, timeout=120, capture_output=True)
        cls.data = json.loads(cls.output.read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_matched_materials_inputs_identity_and_clock(self):
        self.assertEqual(self.data["schema"], "banjo.material-lab-recording.v2")
        self.assertEqual(self.data["kind"], "solver-recording")
        self.assertEqual(len(self.data["experiments"]), 6)
        for run in self.data["experiments"]:
            self.assertEqual(run["force_n"], [0, 1e6, 0] if run["interaction"] == "pull" else [10000, -20000, 30000])
            self.assertEqual(run["dt_s"], 1e-7)
            self.assertEqual(len(run["bond_topology"]), 1261)
            self.assertEqual(len(run["frames"]), 21)
            for i, frame in enumerate(run["frames"]):
                self.assertEqual(frame["step"], i * 32)
                self.assertAlmostEqual(frame["time_s"], frame["step"] * run["dt_s"], delta=1e-15)
                self.assertEqual([cell["id"] for cell in frame["nodes"]], list(range(125)))
                self.assertAlmostEqual(sum(c["mass_kg"] for c in frame["nodes"]), frame["mass_kg"], delta=1e-10)
                self.assertEqual(sum(c["clamped"] for c in frame["nodes"]), 25)
                for cell in frame["nodes"]:
                    self.assertTrue(all(math.isfinite(v) for v in cell["position_m"] + cell["velocity_m_s"]))
                    if cell["clamped"]:
                        self.assertEqual(cell["displacement_m"], [0, 0, 0])
                        self.assertEqual(cell["velocity_m_s"], [0, 0, 0])

    def test_measured_damage_unloading_and_complete_patch_ledger(self):
        self.check_ledgers(self.data)

    def check_ledgers(self, data):
        for run in data["experiments"]:
            first, last = run["frames"][0], run["frames"][-1]
            self.assertEqual(first["broken_bonds"], 0)
            self.assertEqual(first["work_j"], 0)
            self.assertTrue(last["work_j"] > 0)
            self.assertLess(last["positive_work_j"], 50000)
            for frame in run["frames"]:
                self.assertEqual(len(frame["bond_state"]), len(run["bond_topology"]))
                self.assertEqual(sum(not b[0] for b in frame["bond_state"]), frame["broken_bonds"])
                self.assertAlmostEqual(frame["kinetic_j"] + frame["elastic_j"] + frame["removed_bond_energy_j"] -
                    frame["work_j"] - frame["integration_error_j"], frame["energy_residual_j"], delta=1e-10)
                self.assertLess(abs(frame["energy_residual_j"]), 1e-8)
                for key in ("momentum_residual_n_s", "angular_residual_kg_m2_s"):
                    self.assertLess(math.sqrt(sum(v*v for v in frame[key])), 1e-8)
                momentum = [sum(c["mass_kg"] * c["velocity_m_s"][a] for c in frame["nodes"]) for a in range(3)]
                angular = [0.0] * 3
                for cell in frame["nodes"]:
                    p = [cell["mass_kg"] * v for v in cell["velocity_m_s"]]
                    x = cell["position_m"]
                    for a in range(3):
                        angular[a] += x[(a+1)%3] * p[(a+2)%3] - x[(a+2)%3] * p[(a+1)%3]
                for a in range(3):
                    self.assertAlmostEqual(momentum[a] - frame["source_impulse_n_s"][a] - frame["support_impulse_n_s"][a] -
                        frame["bond_roundoff_impulse_n_s"][a], frame["momentum_residual_n_s"][a], delta=1e-10)
                    self.assertAlmostEqual(angular[a] - frame["source_angular_impulse_kg_m2_s"][a] - frame["support_angular_impulse_kg_m2_s"][a] -
                        frame["bond_roundoff_angular_kg_m2_s"][a], frame["angular_residual_kg_m2_s"][a], delta=1e-10)
                    self.assertAlmostEqual(frame["source_impulse_n_s"][a], run["force_n"][a] * min(frame["step"],512)*run["dt_s"], delta=1e-10)
            self.assertEqual(last["work_j"], run["frames"][16]["work_j"], "unloaded phase supplied extra work")
            self.assertEqual(last["source_impulse_n_s"], run["frames"][16]["source_impulse_n_s"])
            if run["interaction"] == "load":
                self.assertEqual(last["components"], 1)
                self.assertEqual(last["broken_bonds"], 0)
            elif data["request"]["force_scale"] == 1 and run["material"] in ("glass", "oak"):
                self.assertGreater(last["components"], 1)
                self.assertTrue(any(not cell["attached"] for cell in last["nodes"]))
            self.assertGreater(run["solver_wall_s"], 0)

    def test_every_supported_live_load_uses_fresh_matched_solver_state(self):
        request = Path(self.temp.name) / "request.json"
        for scale in (.25, .5, 1.25):
            request.write_text(json.dumps({"schema": "banjo.material-lab-request.v1", "force_scale": scale}), encoding="utf-8")
            subprocess.run([str(NATIVE), "--request", str(request), str(self.output)], check=True, capture_output=True, timeout=10)
            data = json.loads(self.output.read_text(encoding="utf-8"))
            self.assertEqual(data["request"]["force_scale"], scale)
            self.check_ledgers(data)
            for base, run in zip(self.data["experiments"], data["experiments"]):
                self.assertEqual(run["id"], base["id"])
                self.assertEqual(run["force_n"], [v * scale for v in base["force_n"]])
                for key in ("density_kg_m3", "young_modulus_pa", "cell_m", "dt_s", "bond_topology"):
                    self.assertEqual(run[key], base[key])
                self.assertEqual(run["frames"][0], base["frames"][0], "fresh experiment inherited earlier motion/damage")
                self.assertNotEqual(run["frames"][-1]["work_j"], base["frames"][-1]["work_j"], "returned unrelated cached outcome")

    def test_invalid_requests_refuse_before_overwriting_output(self):
        request, output = Path(self.temp.name) / "invalid.json", Path(self.temp.name) / "preserved.json"
        for raw in ('{}', '{"schema":"banjo.material-lab-request.v1","force_scale":true}',
                    '{"schema":"banjo.material-lab-request.v1","force_scale":2}',
                    '{"schema":"banjo.material-lab-request.v1","force_scale":1,"world":"other"}',
                    '{"schema":"banjo.material-lab-request.v1","force_scale":1,"force_scale":0.5}', ' '*1025):
            request.write_text(raw, encoding="utf-8")
            output.write_text("previous result", encoding="utf-8")
            result = subprocess.run([str(NATIVE), "--request", str(request), str(output)], capture_output=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(output.read_text(encoding="utf-8"), "previous result")

    def test_invalid_cli_does_not_write_a_recording(self):
        result = subprocess.run([str(NATIVE)], capture_output=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"usage:", result.stderr)


class ReadOnlyServer(unittest.TestCase):
    def test_only_named_assets_are_served_no_workspace_or_mutations(self):
        spec = importlib.util.spec_from_file_location("material_lab", ROOT / "scripts/material-lab.py")
        lab = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(lab)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "index.html").write_text("lab", encoding="utf-8")
            (root / "private.txt").write_text("unserved", encoding="utf-8")
            server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(lab.LabHandler, directory=directory))
            thread = threading.Thread(target=server.serve_forever, daemon=True);thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                with urllib.request.urlopen(base + "/") as response:
                    self.assertEqual(response.read(), b"lab")
                    self.assertEqual(response.headers["Cache-Control"], "no-store")
                    self.assertIn("charset=utf-8", response.headers["Content-Type"])
                for path in ("/private.txt", "/../AGENTS.md", "/%2e%2e/AGENTS.md", "/api/step"):
                    with self.assertRaises(urllib.error.HTTPError) as caught:
                        urllib.request.urlopen(base + path)
                    self.assertEqual(caught.exception.code, 404)
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(urllib.request.Request(base + "/", data=b"step", method="POST"))
                self.assertEqual(caught.exception.code, 404)
            finally:
                server.shutdown();server.server_close();thread.join(5)


class LiveServer(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("material_lab", ROOT / "scripts/material-lab.py")
        self.lab = importlib.util.module_from_spec(spec);spec.loader.exec_module(self.lab)
        self.temp = tempfile.TemporaryDirectory()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(self.lab.LabHandler, directory=self.temp.name))
        self.server.experiment_runner = self.lab.ExperimentRunner(NATIVE)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True);self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.request = {"schema": "banjo.material-lab-request.v1", "force_scale": .5}

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join(5);self.temp.cleanup()

    def post(self, body=None, origin=None, extra=None):
        headers = {"Content-Type": "application/json", "Origin": origin or self.base}
        headers.update(extra or {})
        raw = json.dumps(self.request).encode() if body is None else body
        with urllib.request.urlopen(urllib.request.Request(self.base + "/api/experiments", data=raw, headers=headers), timeout=10) as response:
            return json.load(response)

    def test_fresh_native_results_have_request_binary_and_execution_identity(self):
        first, second = self.post(), self.post()
        self.assertEqual(first["status"], "completed")
        self.assertNotEqual(first["execution_id"], second["execution_id"])
        self.assertEqual(first["request"], self.request)
        self.assertEqual(first["recording"]["request"], self.request)
        self.assertEqual(first["identity"]["native_sha256"], hashlib.sha256(NATIVE.read_bytes()).hexdigest())
        for a,b in zip(first["recording"]["experiments"],second["recording"]["experiments"]):
            self.assertEqual(a["frames"], b["frames"], "matched fresh deterministic CPU input differed")
        self.assertEqual(list(Path(self.temp.name).iterdir()), [], "job leaked temporary assets into served directory")

    def test_cross_origin_rebinding_invalid_and_oversize_requests_are_refused(self):
        for body,origin,extra,code in [(None,"http://example.invalid",None,403),
                (None,None,{"Host":"other.invalid"},403), (None,None,{"Sec-Fetch-Site":"cross-site"},403),
                (b'{}',None,None,400), (b'x'*1025,None,None,400),
                (b'{"schema":"banjo.material-lab-request.v1","force_scale":1,"force_scale":0.5}',None,None,400)]:
            with self.assertRaises(urllib.error.HTTPError) as caught:
                self.post(body,origin,extra)
            self.assertEqual(caught.exception.code,code)

    def test_busy_job_refuses_without_queue_and_slot_recovers_after_actual_run(self):
        started, release = threading.Event(), threading.Event()
        original = subprocess.run
        def delayed(*args, **kwargs):
            started.set()
            if not release.wait(3): raise RuntimeError("test release missing")
            return original(*args, **kwargs)
        with patch.object(self.lab.subprocess, "run", delayed), ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self.post)
            self.assertTrue(started.wait(3))
            try:
                with self.assertRaises(urllib.error.HTTPError) as caught: self.post()
                self.assertEqual(caught.exception.code,429)
            finally:
                release.set()
            self.assertEqual(future.result(timeout=10)["status"],"completed")
        self.assertEqual(self.post()["status"],"completed")

    def test_timeout_is_not_success_and_releases_execution_slot(self):
        with patch.object(self.lab.subprocess,"run",side_effect=subprocess.TimeoutExpired("lab",6)):
            with self.assertRaises(urllib.error.HTTPError) as caught: self.post()
            self.assertEqual(caught.exception.code,504)
        self.assertEqual(self.post()["status"],"completed")


if __name__ == "__main__":
    unittest.main()
