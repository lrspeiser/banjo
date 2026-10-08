"""Serve a native 3D test world and isolated CPU material diagnostics.

The browser replays exact samples; a run starts a fresh isolated CPU experiment,
never a game world or LLM. Named assets and bounded experiment/test endpoints exist. Run the
TypeScript build first; native build/output stay in build/, not the repository.
"""
from __future__ import annotations

import argparse
import os
import queue
import functools
import hashlib
import importlib.util
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
import re

ROOT = Path(__file__).resolve().parents[1]
FILES = {"index.html", "lab.css", "lab.js", "contract.js", "material.json", "manifest.json",
         "sheets.html", "sheets.js", "sheets.css", "sheet-observation.js", "drop.html", "drop.js", "drop-observation.js",
         "tests.html", "hub.css", "hub.js", "hub-contract.js", "world.html", "world.css", "world.js", "world-input.js", "world-impact.js",
         "three.module.js", "three.core.js", "three-LICENSE.txt"}
SCALES = (.25, .5, 1, 1.25)
MAX_RECORDING_BYTES = 10_000_000


def validate_request(value):
    if (not isinstance(value, dict) or set(value) != {"schema", "force_scale"}
            or value["schema"] != "banjo.material-lab-request.v1"
            or type(value["force_scale"]) not in (int, float)
            or value["force_scale"] not in SCALES):
        raise ValueError("Choose a supported load: 0.25, 0.5, 1 or 1.25")
    return {"schema": value["schema"], "force_scale": value["force_scale"]}


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Repeated request field")
        result[key] = value
    return result


class ExperimentBusy(Exception):
    pass


class ExperimentRunner:
    """One bounded subprocess at a time; no queue, outcome cache or world owner."""
    def __init__(self, native: Path):
        self.native = native.resolve(strict=True)
        self.gate = threading.BoundedSemaphore(1)

    def run(self, request):
        request = validate_request(request)
        if not self.gate.acquire(blocking=False):
            raise ExperimentBusy()
        try:
            started = time.perf_counter()
            binary_hash = hashlib.sha256(self.native.read_bytes()).hexdigest()
            request_bytes = json.dumps(request, sort_keys=True, separators=(",", ":")).encode("utf-8")
            with tempfile.TemporaryDirectory(prefix="banjo-material-") as directory:
                root = Path(directory)
                source, output = root / "request.json", root / "result.json"
                source.write_bytes(request_bytes)
                subprocess.run([str(self.native), "--request", str(source), str(output)],
                               check=True, capture_output=True, timeout=6)
                if output.stat().st_size > MAX_RECORDING_BYTES:
                    raise ValueError("Experiment exceeds viewer budget")
                encoded = output.read_bytes()
                recording = json.loads(encoded)
                if (recording.get("schema") != "banjo.material-lab-recording.v2"
                        or recording.get("request") != request
                        or hashlib.sha256(self.native.read_bytes()).hexdigest() != binary_hash):
                    raise ValueError("Experiment identity changed")
            return {"schema": "banjo.material-lab-result.v1", "status": "completed",
                    "execution_id": uuid.uuid4().hex, "request": request,
                    "elapsed_wall_s": time.perf_counter() - started,
                    "identity": {"native_sha256": binary_hash,
                                 "request_sha256": hashlib.sha256(request_bytes).hexdigest(),
                                 "recording_sha256": hashlib.sha256(encoded).hexdigest()},
                    "recording": recording}
        finally:
            self.gate.release()


def prepare(native: Path, output: Path):
    native = native.resolve(strict=True)
    output.mkdir(parents=True, exist_ok=True)
    compiled = ROOT / "build/material-lab/ui/lab.js"
    if not compiled.is_file():
        raise RuntimeError("Build the client first: npm ci && npm run build in client/")
    subprocess.run([str(native), str(output / "material.json")], check=True, timeout=120)
    for name in ("drop.html", "drop.js", "drop-observation.js", "sheets.html", "sheets.js", "sheets.css", "sheet-observation.js", "index.html", "lab.css", "tests.html", "hub.css", "world.html", "world.css", "world.js", "world-input.js", "world-impact.js"):
        shutil.copyfile(ROOT / "client/experiments" / name, output / name)
    for name in ("three.module.js", "three.core.js", "three-LICENSE.txt"):
        shutil.copyfile(ROOT / "playground/vendor" / name, output / name)
    if compiled.resolve() != (output / "lab.js").resolve():
        shutil.copyfile(compiled, output / "lab.js")
        shutil.copyfile(compiled.with_name("contract.js"), output / "contract.js")
    for name in ("hub.js", "hub-contract.js"):
        source = compiled.with_name(name)
        if source.resolve() != (output / name).resolve(): shutil.copyfile(source, output / name)
    sources = ["tools/drop_world_run.cpp", "src/platform/NetworkWorld.cpp", "scripts/drop-world.py", "client/experiments/drop.js", "client/experiments/drop.html", "tests/drop_world_tests.py", "tools/sheet_world_run.cpp", "src/fastlattice/SheetImpact.cpp", "src/fastlattice/SheetImpact.hpp", "scripts/sheet-world.py", "client/experiments/sheets.js", "client/experiments/sheets.html", "client/experiments/sheets.css", "tests/sheet_impact_tests.py", "tests/sheet_gateway_tests.py", "tools/material_lab_record.cpp", "src/fastlattice/SolidMatterPatch.cpp",
               "src/fastlattice/ConstituentPartition.cpp", "src/fastlattice/CpuLatticeBackend.cpp",
               "src/material/MaterialCatalog.cpp", "client/experiments/lab.ts", "client/experiments/contract.ts",
               "tests/material_surface_contact_tests.cpp", "src/fastlattice/NativeFixedContact.cpp",
               "src/fastlattice/MaterialContactRegion.cpp", "src/physics/MaterialContactStencil.cpp",
               "client/experiments/hub.ts", "client/experiments/hub-contract.ts", "scripts/lab-test-runner.py",
               "client/experiments/world.html", "client/experiments/world.css", "client/experiments/world.js", "client/experiments/world-input.js", "client/experiments/world-impact.js",
               "scripts/test-world.py", "runtime/src/main.rs", "runtime/src/world.rs", "runtime/src/native.rs"]
    sources += ["src/platform/PlatformWorld.cpp", "src/platform/WaterWheelWorld.cpp", "src/platform/WaterWheelWorld.hpp", "tests/water_wheel_tests.py", "client/experiments/drop-observation.js", "tests/drop_observation_tests.mjs", "client/experiments/sheet-observation.js", "tests/sheet_feedback_native_tests.py", "tests/sheet_observation_tests.mjs"]
    manifest = {
        "schema": "banjo.material-lab-manifest.v1",
        "source_revision": subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip(),
        "kind": "isolated CPU experiments; baseline and deliberate fresh execution",
        "identity_note": "Checkout revision/workspace hashes and actual binary fingerprint; revision alone does not prove artifact/source equivalence.",
        "native_sha256": hashlib.sha256(native.read_bytes()).hexdigest(),
        "source_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in sources},
        "assets_sha256": {name: hashlib.sha256((output / name).read_bytes()).hexdigest() for name in FILES if name != "manifest.json"},
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


class LabHandler(SimpleHTTPRequestHandler):
    def do_POST(self):
        self.close_connection = True
        if self.path not in {"/api/experiments", "/api/tests", "/api/world", "/api/sheets", "/api/drop"}:
            return self.reply(404, {"error": "No experiment endpoint at this path"})
        origin = f"http://127.0.0.1:{self.server.server_port}"
        if (self.headers.get("Host") != origin.removeprefix("http://")
                or self.headers.get("Origin") != origin
                or self.headers.get("Sec-Fetch-Site", "same-origin") != "same-origin"):
            return self.reply(403, {"error": "Use the same local lab page to run experiments"})
        try:
            if (self.headers.get_content_type() != "application/json"
                    or "Transfer-Encoding" in self.headers):
                raise ValueError("Send a small JSON experiment request")
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 1024:
                raise ValueError("Experiment request must be 1–1024 bytes")
            self.connection.settimeout(3)
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError("Incomplete request")
            request = json.loads(raw, object_pairs_hook=unique_object)
            if self.path == "/api/experiments": request = validate_request(request)
        except (ValueError, UnicodeError, TimeoutError):
            return self.reply(400, {"error": "Invalid experiment request; choose one of the four loads"})
        if self.path in {"/api/sheets", "/api/drop"}:
            runner = getattr(self.server, "drop_manager" if self.path=="/api/drop" else "sheet_manager", None)
            if runner is None: return self.reply(503, {"error":"Build banjo_sheet_world_run first"})
            try: result = runner.request(request)
            except (ValueError,TypeError,KeyError): return self.reply(400,{"error":"Invalid or expired specimen; hit the central working area or reset"})
            except (RuntimeError,OSError,subprocess.SubprocessError): return self.reply(502,{"error":"Native specimen stopped; reset to try again"})
            return self.reply(200,result)
        if self.path == "/api/world":
            runner = getattr(self.server, "world_manager", None)
            if runner is None: return self.reply(503, {"error": "Build the Rust runtime and native world target first"})
            try: result = runner.request(request)
            except (ValueError, TypeError, KeyError, StopIteration) as error:
                messages = {"expired":"This test world expired while inactive. Start a fresh test world.",
                            "stopped":"The native test world stopped. Start a fresh test world.",
                            "input_budget":"This bounded test session reached its input limit. Start a fresh test world."}
                code = getattr(error, "code", None)
                if code in messages:
                    return self.reply(409, {"code": code, "error": messages[code]})
                return self.reply(400, {"error": "Invalid or expired test world intention"})
            except (RuntimeError, OSError, subprocess.SubprocessError, queue.Empty):
                return self.reply(502, {"code":"stopped", "error": "Native world stopped or refused observation; start a fresh test world"})
            return self.reply(200, result)
        if self.path == "/api/tests":
            runner = getattr(self.server, "test_runner", None)
            if runner is None: return self.reply(503, {"error": "Test execution unavailable"})
            try: result = runner.start(request)
            except (ValueError, TypeError): return self.reply(400, {"error": "Choose a named test"})
            if result is None: return self.reply(429, {"error": "Another experiment or test is running"})
            return self.reply(202, result)
        runner = getattr(self.server, "experiment_runner", None)
        if runner is None:
            return self.reply(503, {"error": "Experiment execution is unavailable"})
        try:
            result = runner.run(request)
        except ExperimentBusy:
            return self.reply(429, {"error": "Another experiment is running"})
        except subprocess.TimeoutExpired:
            return self.reply(504, {"error": "Experiment exceeded its six-second execution budget"})
        except (OSError, ValueError, subprocess.CalledProcessError):
            return self.reply(502, {"error": "Solver did not return a complete experiment"})
        return self.reply(200, result)

    def do_GET(self):
        if self.path == "/api/tests":
            runner = getattr(self.server,"test_runner",None)
            return self.reply(200,{"checks":runner.catalog}) if runner else self.reply(503,{"error":"Tests unavailable"})
        match = re.fullmatch(r"/api/tests/([0-9a-f]{32})(/recording)?",self.path)
        if match:
            runner=getattr(self.server,"test_runner",None)
            if runner is None: return self.reply(503,{"error":"Tests unavailable"})
            value=runner.recorded(match[1]) if match[2] else runner.snapshot(match[1])
            if value is None: return self.reply(404,{"error":"No current result for this execution"})
            return self.reply_bytes(200,value) if match[2] else self.reply(200,value)
        return super().do_GET()

    def reply(self, code, value):
        encoded = json.dumps(value, separators=(",", ":"), allow_nan=False).encode("utf-8")
        return self.reply_bytes(code,encoded)

    def reply_bytes(self,code,encoded):
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        if code == 429:
            self.send_header("Retry-After", "1")
        self.end_headers()
        try:
            self.wfile.write(encoded)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass  # A disconnected observer cannot leave the execution slot locked.

    def guess_type(self, path):
        mime = super().guess_type(path)
        if mime.startswith("text/") or mime in {"application/javascript", "application/json"}:
            return mime + "; charset=utf-8"
        return mime

    def send_head(self):
        # No directory listing, arbitrary workspace paths or legacy world routes.
        name = self.path.split("?", 1)[0]
        if name == "/":
            self.path = "/world.html"
        elif name not in {"/" + item for item in FILES}:
            self.send_error(404, "No lab asset at this path")
            return None
        return super().send_head()

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'")
        super().end_headers()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "build/material-lab/ui")
    parser.add_argument("--port", type=int, default=18891)
    parser.add_argument("--generate-only", action="store_true")
    parser.add_argument("--runtime", type=Path, default=ROOT / "build/rust-runtime/debug" / ("banjo-runtime.exe" if os.name == "nt" else "banjo-runtime"))
    args = parser.parse_args()
    output = args.output.resolve()
    prepare(args.native, output)
    if args.generate_only:
        print(f"Generated lab in {output}")
        return
    server = ThreadingHTTPServer(("127.0.0.1", args.port), functools.partial(LabHandler, directory=str(output)))
    server.experiment_runner = ExperimentRunner(args.native)
    spec=importlib.util.spec_from_file_location("lab_tests",ROOT/"scripts/lab-test-runner.py")
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    server.test_runner=module.TestRunner(args.native.resolve().parent,server.experiment_runner.gate)
    sheet = args.native.resolve().with_name("banjo_sheet_world_run.exe" if os.name == "nt" else "banjo_sheet_world_run")
    if sheet.is_file():
        spec=importlib.util.spec_from_file_location("sheet_world",ROOT/"scripts/sheet-world.py")
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        server.sheet_manager=module.SheetManager(sheet)
    drop = args.native.resolve().with_name("banjo_drop_world_run.exe" if os.name == "nt" else "banjo_drop_world_run")
    if drop.is_file():
        spec=importlib.util.spec_from_file_location("drop_world",ROOT/"scripts/drop-world.py")
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        server.drop_manager=module.DropManager(drop)
    live = args.native.resolve().with_name("banjo_live_world_run.exe" if os.name == "nt" else "banjo_live_world_run")
    if live.is_file() and args.runtime.is_file():
        spec=importlib.util.spec_from_file_location("test_world", ROOT/"scripts/test-world.py")
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        server.world_manager=module.WorldManager(live,args.runtime)
    print(f"3D test world: http://127.0.0.1:{server.server_port}/world.html; diagnostics: /tests.html", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if hasattr(server,"world_manager"): server.world_manager.close()
        if hasattr(server,"sheet_manager"): server.sheet_manager.close()
        if hasattr(server,"drop_manager"): server.drop_manager.close()
        server.server_close()


if __name__ == "__main__":
    main()
