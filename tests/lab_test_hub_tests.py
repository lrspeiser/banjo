"""Actual compiled contact capture, HTTP execution and strict failure visibility."""
import functools
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
DIRECTORY=Path(sys.argv.pop(1)).resolve() if len(sys.argv)>1 and not sys.argv[1].startswith("-") else ROOT/"build/local-cell-tools/Release"
SUFFIX=".exe" if os.name=="nt" else ""
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value
LAB=module("material_lab",ROOT/"scripts/material-lab.py")
RUNNER=module("lab_runner",ROOT/"scripts/lab-test-runner.py")

class TestHub(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        cls.server=ThreadingHTTPServer(("127.0.0.1",0),functools.partial(LAB.LabHandler,directory=cls.temp.name))
        cls.server.experiment_runner=LAB.ExperimentRunner(DIRECTORY/("banjo_material_lab_record"+SUFFIX))
        cls.server.test_runner=RUNNER.TestRunner(DIRECTORY,cls.server.experiment_runner.gate)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.base=f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join(5);cls.temp.cleanup()

    def post(self,value,origin=None):
        request=urllib.request.Request(self.base+"/api/tests",data=json.dumps(value).encode(),headers={"Content-Type":"application/json","Origin":origin or self.base})
        with urllib.request.urlopen(request,timeout=4) as response:return json.load(response)

    def get(self,path):
        with urllib.request.urlopen(self.base+path,timeout=4) as response:return response.read()

    def wait(self,key):
        end=time.monotonic()+30
        while time.monotonic()<end:
            job=json.loads(self.get("/api/tests/"+key))
            if job["status"]=="completed":return job
            time.sleep(.05)
        self.fail("Actual compiled test did not finish")

    def test_contact_strict_failure_delivers_actual_recording_and_correct_identity(self):
        started=self.post({"check":"contact-gate"});job=self.wait(started["id"])
        check=job["checks"][0]
        encoded=self.get("/api/tests/"+job["id"]+"/recording")
        self.assertEqual(hashlib.sha256(encoded).hexdigest(),check["recording_sha256"])
        native=DIRECTORY/("banjo_material_surface_contact_tests"+SUFFIX)
        self.assertEqual(hashlib.sha256(native.read_bytes()).hexdigest(),check["artifact_sha256"])
        recording=json.loads(encoded)
        open_gates=recording["open_convergence_gates"]
        self.assertEqual(check["status"],"fail" if open_gates else "pass")
        self.assertEqual(check["exit_code"],1 if open_gates else 0)
        if open_gates:self.assertIn("acceptance remains open",check["output"])
        self.assertEqual(len(recording["experiments"]),12)
        metrics=[json.loads(line.split(" ",1)[1]) for line in check["output"].splitlines() if line.startswith("LIVE_GRAPH_CONTACT_EVIDENCE ")]
        self.assertEqual(len(metrics),12)
        for r,m in zip(recording["experiments"],metrics):
            self.assertEqual(len(r["frames"]),33)
            self.assertEqual(r["frames"][-1]["step"],r["accepted_steps"])
            self.assertAlmostEqual(r["frames"][-1]["time_s"],.0002048,places=15)
            self.assertEqual(r["frames"][-1]["broken_bonds"],m["broken_bonds"])
            self.assertAlmostEqual(r["detached_mass_kg"],m["detached_mass_kg"],places=9)
            self.assertEqual(r["contacts"],m["contacts"])
            self.assertLess(abs(r["attributed_energy_error_j"]),1e-10)
            initial,final=r["frames"][0],r["frames"][-1]
            self.assertNotEqual(initial["source"][0]["position_m"],final["source"][0]["position_m"])
            self.assertEqual(sum(n["clamped"] for n in final["nodes"]),9)
            self.assertAlmostEqual(sum(n["mass_kg"] for n in final["nodes"]),r["density_kg_m3"]*.001728,places=12)
        output=Path(self.temp.name)/"contract-recording.json";output.write_bytes(encoded)
        node=shutil.which("node")
        self.assertIsNotNone(node,"Node required for actual recording client contract")
        result=subprocess.run([node,str(ROOT/"tests/lab_test_hub_client_tests.mjs"),str(output)],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        # Capturing must not change the solver's actual response.
        baseline=subprocess.run([str(native)],capture_output=True,text=True,timeout=15)
        self.assertEqual(baseline.returncode,0)
        unrecorded=[json.loads(line.split(" ",1)[1]) for line in baseline.stdout.splitlines() if line.startswith("LIVE_GRAPH_CONTACT_EVIDENCE ")]
        for a,b in zip(metrics,unrecorded):
            for key in a:
                if key!="wall_s":self.assertEqual(a[key],b[key],f"Recording changed {key}")

    def test_named_commands_only_origin_and_result_isolation(self):
        self.assertEqual(len(json.loads(self.get("/api/tests"))["checks"]),15)
        for request in ({"check":"cmd.exe"},{"check":"all","args":["--anything"]},{"check":[]},{}):
            with self.assertRaises(urllib.error.HTTPError) as e:self.post(request)
            self.assertEqual(e.exception.code,400)
        with self.assertRaises(urllib.error.HTTPError) as e:self.post({"check":"all"},"http://other.invalid")
        self.assertEqual(e.exception.code,403)
        for path in ("/api/tests/"+"a"*32,"/api/tests/../.env","/api/tests/"+"a"*32+"/recording"):
            with self.assertRaises(urllib.error.HTTPError) as e:self.get(path)
            self.assertEqual(e.exception.code,404)
        gate=self.server.experiment_runner.gate;self.assertTrue(gate.acquire(False))
        try:
            with self.assertRaises(urllib.error.HTTPError) as e:self.post({"check":"registration"})
            self.assertEqual(e.exception.code,429)
        finally:gate.release()
        job=self.wait(self.post({"check":"registration"})["id"])
        self.assertEqual(job["checks"][0]["status"],"pass")
        self.assertIn("OK: every source",job["checks"][0]["output"])

    def test_timeout_and_missing_binary_never_pass_and_release_shared_slot(self):
        runner=self.server.test_runner
        runner.timeout_s=.05
        with patch.object(runner,"_command",return_value=([sys.executable,"-c","import time; time.sleep(3)"],{})):
            job=self.wait(self.post({"check":"registration"})["id"])
            self.assertEqual(job["checks"][0]["status"],"error")
        runner.timeout_s=60
        with patch.object(runner,"_command",return_value=([str(Path(self.temp.name)/"missing.exe")],{})):
            job=self.wait(self.post({"check":"registration"})["id"])
            self.assertEqual(job["checks"][0]["status"],"unavailable")
        job=self.wait(self.post({"check":"registration"})["id"])
        self.assertEqual(job["checks"][0]["status"],"pass")

    def test_drop_world_executes_native_suite_and_returns_complete_fingerprinted_job(self):
        job=self.wait(self.post({"check":"drop-world"})["id"])
        self.assertEqual(job["total"],1)
        self.assertEqual(len(job["checks"]),1)
        check=job["checks"][0]
        self.assertEqual(check["id"],"drop-world")
        self.assertEqual(check["status"],"pass",check["output"])
        native=DIRECTORY/("banjo_drop_world_run"+SUFFIX)
        self.assertEqual(check["dependencies_sha256"][str(native.relative_to(ROOT))],
                         hashlib.sha256(native.read_bytes()).hexdigest())

if __name__=="__main__":unittest.main()
