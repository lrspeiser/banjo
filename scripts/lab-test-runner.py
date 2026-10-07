"""Fixed, isolated local test catalog. Never accepts commands or paths from HTTP."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import subprocess
import signal
import sys
import tempfile
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
NATIVE_CHECKS = (
    ("surface", "Surface transfer & live regions", "banjo_material_surface_contact_tests"),
    ("coupling", "Native / material coupling", "banjo_native_lattice_contact_tests"),
    ("geometry", "Occupied cell contact geometry", "banjo_native_point_contact_tests"),
    ("verlet", "Material integration", "banjo_lattice_verlet_tests"),
    ("loads", "External work & reactions", "banjo_lattice_external_load_tests"),
    ("assembly", "Joined tool contacts", "banjo_fixed_assembly_contact_tests"),
    ("tools", "Pick, shovel, hoe & unfamiliar tool", "banjo_native_tool_use_tests"),
    ("admission", "Tool target readiness", "banjo_tool_use_admission_tests"),
)

class TestRunner:
    def __init__(self, native_directory: Path, gate):
        self.directory = native_directory.resolve()
        self.gate = gate
        self.lock = threading.Lock()
        self.job = None
        self.recording = None
        # The sandbox includes comparative stance and paired physical cycles.
        # Match its registered CTest wall budget; this is not a law tolerance.
        self.timeout_s = 120
        self.catalog = [{"id": key, "name": name, "kind": "bounded checks"} for key,name,_ in NATIVE_CHECKS]
        self.catalog += [
            {"id": "contact-gate", "name": "Sustained contact convergence + replay", "kind": "strict acceptance"},
            {"id": "repeat-gate", "name": "Repeated excavation", "kind": "strict acceptance"},
            {"id": "worker", "name": "Rust owner → actual native engine", "kind": "integration"},
            {"id": "sandbox", "name": "3D world intentions, geometry & pickup", "kind": "integration"},
            {"id": "rust", "name": "Rust command / state contracts", "kind": "contracts"},
            {"id": "registration", "name": "Every C++ source has a build target", "kind": "build guard"},
        ]

    def start(self, request):
        if (not isinstance(request,dict) or set(request)!={"check"}
                or request["check"] not in {"all", *(entry["id"] for entry in self.catalog)}):
            raise ValueError("Choose a named test")
        if not self.gate.acquire(blocking=False):
            return None
        with self.lock:
            key = uuid.uuid4().hex
            entries = self.catalog if request["check"]=="all" else [e for e in self.catalog if e["id"]==request["check"]]
            self.recording = None
            self.job = {"schema":"banjo.test-job.v1", "id":key, "status":"running",
                        "selection":request["check"], "total":len(entries), "checks":[], "current":entries[0]["name"]}
        thread = threading.Thread(target=self._run, args=(key,entries), daemon=True)
        try:
            thread.start()
        except Exception:
            self.gate.release()
            raise
        return self.snapshot(key)

    def snapshot(self, key):
        with self.lock:
            if self.job is None or key!=self.job["id"]: return None
            return json.loads(json.dumps(self.job,allow_nan=False))

    def recorded(self, key):
        with self.lock:
            if self.job is None or key!=self.job["id"]: return None
            return self.recording

    def _command(self, key, output):
        native = {k: executable for k,_,executable in NATIVE_CHECKS}
        extension = ".exe" if os.name=="nt" else ""
        if key in native:
            return [str(self.directory / (native[key]+extension))], {}
        if key=="contact-gate":
            return [str(self.directory/(native["surface"]+extension)),"--require-live-contact-convergence","--record",str(output)], {}
        if key=="repeat-gate":
            return [str(self.directory/(native["tools"]+extension)),"--require-repeat-yield"], {}
        runtime = ROOT/"build/rust-runtime/debug"/("banjo-runtime"+extension)
        if key in {"worker", "sandbox"}:
            test="runtime_native_tests.py" if key=="worker" else "test_world_tests.py"
            return [sys.executable,str(ROOT/"tests"/test),"-v"], {
                "BANJO_LIVE_ENGINE":str(self.directory/("banjo_live_world_run"+extension)),"BANJO_RUNTIME_ENGINE":str(runtime)}
        if key=="rust":
            cargo = Path.home()/".cargo/bin"/("cargo"+extension)
            return [str(cargo),"test","--locked","--offline","--manifest-path",str(ROOT/"runtime/Cargo.toml"),"--target-dir",str(ROOT/"build/rust-runtime")], {}
        if key=="registration":
            return [sys.executable,str(ROOT/"scripts/check-source-registration.py")], {}
        raise ValueError("Unknown catalog entry")

    def _run(self, key, entries):
        try:
            for entry in entries:
                with self.lock: self.job["current"] = entry["name"]
                result = {**entry,"status":"error","exit_code":None,"elapsed_s":0,"output":""}
                started = time.perf_counter()
                try:
                    with tempfile.TemporaryDirectory(prefix="banjo-test-") as directory:
                        output=Path(directory)/"recording.json"
                        command, variables = self._command(entry["id"],output)
                        artifact=Path(command[0])
                        if not artifact.is_file(): raise FileNotFoundError("Required executable is not built")
                        dependencies=[artifact]
                        if entry["id"] in {"worker", "sandbox"}: dependencies.extend(Path(v) for v in variables.values())
                        before={str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in dependencies}
                        env=os.environ.copy();env.update(variables)
                        # Log to a temporary file instead of accumulating unbounded pipe output.
                        with (Path(directory)/"console.txt").open("w+b") as log:
                            completed=self._execute(command,env,log)
                            log.seek(0,2);size=log.tell();log.seek(max(0,size-24000))
                            result["output"]=("[earlier output omitted]\n" if size>24000 else "")+log.read().decode("utf-8",errors="replace")
                        result["exit_code"]=completed.returncode
                        result["artifact_sha256"]=next(iter(before.values()))
                        result["dependencies_sha256"]=before
                        after={str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in dependencies}
                        if after!=before: raise ValueError("Executable changed during the test")
                        result["status"]="pass" if completed.returncode==0 else "fail"
                        if output.is_file():
                            if output.stat().st_size>10_000_000: raise ValueError("Recording exceeds viewer budget")
                            encoded=output.read_bytes();value=json.loads(encoded)
                            if value.get("schema")!="banjo.contact-recording.v1" or len(value.get("experiments",[]))!=12:
                                raise ValueError("Incomplete contact recording")
                            result["recording_sha256"]=hashlib.sha256(encoded).hexdigest()
                            with self.lock: self.recording=encoded
                except FileNotFoundError:
                    result.update(status="unavailable",output="Required executable is not built. See the test guide.")
                except subprocess.TimeoutExpired:
                    result.update(status="error",output="Test exceeded its 60-second execution budget; no passing result.")
                except (OSError,ValueError) as error:
                    result.update(status="error",output=str(error))
                result["elapsed_s"]=time.perf_counter()-started
                with self.lock: self.job["checks"].append(result)
        finally:
            with self.lock:
                self.job["status"]="completed";self.job["current"]=""
            self.gate.release()

    def _execute(self,command,env,log):
        # Worker checks own native children. On timeout, terminate only this
        # newly created process tree, never a user's World or another test host.
        process=subprocess.Popen(command,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,
                                 start_new_session=os.name!="nt",
                                 creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP|subprocess.CREATE_NO_WINDOW) if os.name=="nt" else 0)
        try:
            code=process.wait(timeout=self.timeout_s)
            return subprocess.CompletedProcess(command,code)
        except subprocess.TimeoutExpired:
            if os.name=="nt":
                try:
                    subprocess.run(["taskkill","/PID",str(process.pid),"/T","/F"],
                                   stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=5)
                finally:
                    if process.poll() is None: process.kill()
            else:
                try: os.killpg(process.pid,signal.SIGKILL)
                except ProcessLookupError: pass
            process.wait(timeout=5)
            raise
