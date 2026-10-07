"""Actual CPU export and read-only serving contracts; no canned frame fixture."""
import functools
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
        self.assertEqual(self.data["schema"], "banjo.material-lab-recording.v1")
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
        for run in self.data["experiments"]:
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
            elif run["material"] in ("glass", "oak"):
                self.assertGreater(last["components"], 1)
                self.assertTrue(any(not cell["attached"] for cell in last["nodes"]))
            self.assertGreater(run["solver_wall_s"], 0)

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
                self.assertEqual(caught.exception.code, 501)
            finally:
                server.shutdown();server.server_close();thread.join(5)


if __name__ == "__main__":
    unittest.main()
