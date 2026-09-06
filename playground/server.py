"""Local chat -> bounded Banjo language -> public authoring API -> native lab.

Run: python playground/server.py --port 8765
Credentials are read only on the server. Static serving is an explicit allowlist.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import re
import secrets
import subprocess
import threading
import time
from urllib import error, request
from urllib.parse import urlsplit
import uuid

from experiment_language import ROOT, KINDS, LIMITATIONS, SCHEMA, SYSTEM, compile_plan, validate_plan
from banjo_authoring import EngineCLI, EngineError, write_package

STATIC = Path(__file__).resolve().parent
ACTIVE = {"planning", "validating", "running"}

def strict_json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result: raise ValueError("Duplicate JSON field")
            result[key] = value
        return result
    def constant(_): raise ValueError("Nonfinite JSON value")
    return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)

def local_configuration():
    values = {}
    path = ROOT / ".env"
    if path.is_file():
        if path.stat().st_size > 65536: raise ValueError("Local environment file exceeds size budget")
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line: continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'": value = value[1:-1]
            if key in ("OPENAI_API_KEY", "OPENAI_MODEL"): values[key] = value
    return (os.environ.get("OPENAI_API_KEY") or values.get("OPENAI_API_KEY", ""),
            os.environ.get("OPENAI_MODEL") or values.get("OPENAI_MODEL", "gpt-5-mini"))

def request_plan(api_key, model, message, previous_plan=None):
    if not api_key: raise ValueError("OPENAI_API_KEY is not configured in the local .env")
    context = {"request": message, "previous_plan": previous_plan}
    payload = {"model": model, "store": False, "max_output_tokens": 3500,
        "reasoning": {"effort": "low"},
        "input": [{"role": "system", "content": SYSTEM},
                  {"role": "user", "content": json.dumps(context, allow_nan=False)}],
        "text": {"format": {"type": "json_schema", "name": "banjo_experiment", "strict": True, "schema": SCHEMA}}}
    req = request.Request("https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode(), method="POST",
        headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"})
    start = time.perf_counter()
    try:
        with request.urlopen(req, timeout=90) as response:
            raw = response.read(1024*1024+1)
            if len(raw) > 1024*1024: raise ValueError("GPT response exceeded size budget")
            result = strict_json(raw)
    except error.HTTPError as exc:
        # The upstream body may contain secrets or echoed inputs. Do not log it.
        raise ValueError(f"GPT request failed (HTTP {exc.code}); check local key, model access and account limits") from None
    except (error.URLError, TimeoutError):
        raise ValueError("GPT connection failed or timed out; no automatic paid retry was issued") from None
    if result.get("status") != "completed": raise ValueError("GPT did not complete a plan; submit a shorter request")
    texts = []
    for output in result.get("output", []):
        for content in output.get("content", []):
            if content.get("type") == "refusal": raise ValueError("GPT declined this request")
            if content.get("type") == "output_text": texts.append(content.get("text", ""))
    plan = validate_plan(strict_json("".join(texts)))
    return plan, {"planning_wall_s": time.perf_counter()-start,
                  "model": model, "usage": result.get("usage", {}), "response_id": result.get("id")}

class Playground:
    def __init__(self, engine_path, studio_path, runs_path, *, planner=request_plan):
        self.engine_path, self.studio_path = Path(engine_path).resolve(), Path(studio_path).resolve()
        self.engine = EngineCLI(self.engine_path, timeout_s=75)
        self.runs_path = Path(runs_path).resolve()
        self.api_key, self.model = local_configuration()
        self.planner = planner
        self.csrf_token = secrets.token_urlsafe(32)
        self.jobs, self.requests, self.paths = {}, {}, {}
        self.lock = threading.RLock()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="banjo-playground")
        self.studios = []

    def status(self):
        return {"key_configured": bool(self.api_key), "model": self.model,
            "engine_ready": self.engine_path.is_file(), "studio_ready": self.studio_path.is_file(),
            "csrf_token": self.csrf_token, "capabilities": [kind for kind in KINDS if kind != "unsupported"], "limitations": LIMITATIONS,
            "examples": ["Compare an iron ball hitting glass, wood and iron panels at 2 m/s for 1 second.",
                "Drop an iron ball from 25 cm onto glass, wood and iron. Use a rigid control first.",
                "Compare the fixed spatial quasistatic pressure response of glass, oak and iron.",
                "Show the published 6 mm tempered-glass drop benchmark and what is missing.",
                "Run the permanent deformation and compact save/reload reference test.",
                "Show heat moving through glass, wood, iron and water/ice."]}

    def submit(self, body):
        if not isinstance(body, dict) or set(body) - {"message", "previous_plan", "request_id", "auto_open"}:
            raise ValueError("Unknown chat request fields")
        message, request_id = body.get("message"), body.get("request_id")
        if not isinstance(message, str) or not 1 <= len(message.strip()) <= 4000: raise ValueError("Request must contain 1..4000 characters")
        if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", request_id): raise ValueError("Invalid request identity")
        if type(body.get("auto_open", True)) is not bool: raise ValueError("auto_open must be a boolean")
        previous = body.get("previous_plan")
        if previous is not None: validate_plan(previous)
        fingerprint = hashlib.sha256(json.dumps(body, sort_keys=True, allow_nan=False).encode()).hexdigest()
        with self.lock:
            if request_id in self.requests:
                old_hash, job_id = self.requests[request_id]
                if old_hash != fingerprint: raise ValueError("Request identity was already used for different content")
                return {"job_id": job_id}
            if any(j["status"] in ACTIVE for j in self.jobs.values()): raise ValueError("One experiment is already running; wait for its result")
            if len(self.jobs) >= 100: raise ValueError("Session reached its 100-job history budget; restart after saving results")
            if not self.engine_path.is_file(): raise ValueError("Build banjo_platform_cli before creating experiments")
            job_id = uuid.uuid4().hex
            self.requests[request_id] = (fingerprint, job_id)
            self.jobs[job_id] = {"id": job_id, "status": "planning", "message": "GPT is creating a bounded experiment declaration.",
                "plan": None, "cases": [], "warnings": list(LIMITATIONS), "timing": {}}
            self.pool.submit(self.execute, job_id, message, previous, body.get("auto_open", True))
            return {"job_id": job_id}

    def update(self, job_id, **fields):
        with self.lock: self.jobs[job_id].update(fields)

    def get(self, job_id):
        with self.lock:
            if job_id not in self.jobs: raise ValueError("Unknown experiment")
            return deepcopy(self.jobs[job_id])

    def execute(self, job_id, message, previous, auto_open):
        start = time.perf_counter()
        try:
            plan, timing = self.planner(self.api_key, self.model, message, previous)
            validate_plan(plan)
            self.update(job_id, plan=plan, timing=timing, status="validating", message=plan["explanation"],
                warnings=list(dict.fromkeys(LIMITATIONS + plan["limitations"])))
            directory = self.runs_path / job_id
            directory.mkdir(parents=True, exist_ok=False)
            (directory / "plan.json").write_text(json.dumps(plan, indent=2, allow_nan=False), encoding="utf-8")
            packages = compile_plan(plan)
            if plan["experiment"] in ("unsupported", "glass_reference"):
                if plan["experiment"] == "glass_reference":
                    reference = json.loads((ROOT/"assets/benchmarks/glass-drop-reference.json").read_text(encoding="utf-8"))
                    self.update(job_id, cases=[{"index":0,"name":"Published 6 mm tempered glass reference", "package":{},
                        "status":"reference_only","report":reference,"native_scene":False}])
                self.update(job_id, status="blocked", message=plan["explanation"] + " No substitute simulation was presented as this capability.")
            elif plan["experiment"] in ("thermal_frontier", "material_state_reference", "continuum_pressure_reference"):
                self.run_reference(job_id, directory, plan)
                if auto_open and plan["experiment"] == "continuum_pressure_reference":
                    try:
                        self.open_case(job_id, 0)
                        self.update(job_id, native_opened=True)
                    except ValueError as exc:
                        current = self.get(job_id)
                        self.update(job_id, native_opened=False, warnings=current["warnings"]+[str(exc)])
            else:
                cases = []
                for index, package in enumerate(packages):
                    path = write_package(package, directory/"scenes"/f"case-{index:02d}.json")
                    self.engine.validate(path)
                    with self.lock: self.paths[(job_id,index)] = (path,"network")
                    cases.append({"index":index,"name":package["name"],"package":package,"report":None,"status":"validated","native_scene":True})
                self.update(job_id, cases=deepcopy(cases), status="running", message="Validated Banjo packages are running in the native engine.")
                for index, case in enumerate(cases):
                    path, _ = self.paths[(job_id,index)]
                    steps = max(1, round(plan["duration_s"]/case["package"]["fixed_dt_s"]))
                    case_start = time.perf_counter()
                    try:
                        case["report"] = self.engine.run(path, steps)
                        case["status"] = "complete"
                    except EngineError as exc:
                        case["report"], case["error"], case["status"] = exc.report, str(exc), "solver_limit"
                    case["requested_steps"] = steps
                    case["wall_s"] = time.perf_counter()-case_start
                    (directory/f"report-{index:02d}.json").write_text(json.dumps(case, indent=2, allow_nan=False),encoding="utf-8")
                    self.update(job_id, cases=deepcopy(cases))
                limited = any(case["status"] != "complete" for case in cases)
                if auto_open and cases:
                    try:
                        self.open_case(job_id, 0)
                        self.update(job_id, native_opened=True)
                    except ValueError as exc:
                        current = self.get(job_id)
                        self.update(job_id, native_opened=False, warnings=current["warnings"]+[str(exc)])
                self.update(job_id, status="complete", message=("Experiment finished; a strict solver limit stopped one or more cases. Inspect the reports." if limited else "Experiment finished. Compare the reports and release the generated scene in the native studio."))
            snapshot = self.get(job_id)
            snapshot["timing"]["total_wall_s"] = time.perf_counter()-start
            self.update(job_id, timing=snapshot["timing"])
            (directory/"job.json").write_text(json.dumps(self.get(job_id),indent=2,allow_nan=False),encoding="utf-8")
        except Exception as exc:
            # Never expose arbitrary upstream HTTP bodies or secrets.
            public = str(exc) if isinstance(exc, (ValueError, EngineError)) else "The local experiment failed; inspect the bounded setup and build availability."
            if self.api_key: public = public.replace(self.api_key, "[redacted]")
            self.update(job_id, status="error", error=public, message=public)

    def run_reference(self, job_id, directory, plan):
        self.update(job_id,status="running")
        if plan["experiment"] == "material_state_reference":
            executable = self.engine_path.with_name("banjo_object_state_probe" + self.engine_path.suffix)
            args = [str(executable)]
            package = {"reference":"J2 material-point and compact numeric state; no spatial dent or world repair"}
        elif plan["experiment"] == "thermal_frontier":
            executable = self.engine_path.with_name("banjo_world_cli" + self.engine_path.suffix)
            source = ROOT/"assets/world-v1/thermal-frontier.json"
            package = json.loads(source.read_text(encoding="utf-8"))
            path = write_package(package,directory/"thermal.json")
            with self.lock: self.paths[(job_id,0)] = (path,"thermal")
            args = [str(executable),"--package",str(path),"--frames",str(round(plan["duration_s"]*60)),
                    "--work","32768","--jobs","64","--output",str(directory/"reference-report.json")]
        elif plan["experiment"] == "continuum_pressure_reference":
            executable = self.engine_path.with_name("banjo_continuum_cli" + self.engine_path.suffix)
            path = directory/"reference-report.json"
            package = {
                "reference":"fixed spatial quasistatic pressure load-unload; no collision, inertia or fracture",
                "physics_abi":"banjo-quasistatic-tet-1", "units":"SI",
                "fixture":{"dimensions_m":[.04,.02,.04],"resolution":[4,2,4],
                    "bottom_boundary":"fully clamped","loaded_top_area_m2":.0004,
                    "peak_pressure_pa":800000000,"increments_per_load_or_unload":32},
                "laws":{"glass":"isotropic-linear-elastic","oak":"orthotropic-linear-elastic",
                    "iron":"small-strain-isotropic-J2"},
                "ignored_plan_fields":["duration_s","projectile","panel_dimensions_m","speeds_m_s","heights_m","objects"],
                "native_view_mode":"solved_load_sequence_playback",
            }
            args = [str(executable),"--resolution","4","--increments","32",
                    "--peak-pressure-pa","800000000","--output",str(path)]
        else:
            raise ValueError("Unsupported native reference experiment")
        result = subprocess.run(args,capture_output=True,text=True,encoding="utf-8",timeout=75,check=False)
        if result.returncode: raise ValueError("Native reference process failed; the experiment was not accepted")
        if plan["experiment"] == "material_state_reference":
            report = strict_json(result.stdout)
        else:
            report = strict_json((directory/"reference-report.json").read_text(encoding="utf-8"))
        if plan["experiment"] != "continuum_pressure_reference":
            self.update(job_id,cases=[{"index":0,"name":plan["name"],"package":package,"report":report,"status":"reference_complete", "native_scene":plan["experiment"]=="thermal_frontier"}],
                status="complete",message="Reference test completed; its supported scope and measurements are in the report.")
            return
        metadata = strict_json(result.stdout)
        if not isinstance(metadata,dict) or metadata.get("cases") != 3 or metadata.get("physical_response_validated") is not False:
            raise ValueError("Native continuum metadata did not match the fixed reference contract")
        if not isinstance(report,dict) or report.get("schema") != "banjo.continuum-patch-trial.v1" or report.get("physical_response_validated") is not False:
            raise ValueError("Native continuum report did not match the fixed reference contract")
        source_cases = report.get("cases")
        if not isinstance(source_cases,list) or len(source_cases) != 3:
            raise ValueError("Native continuum report requires glass, oak and iron cases")
        inner_cases = []
        for expected, source_case in zip(("glass","oak","iron"),source_cases):
            if not isinstance(source_case,dict) or source_case.get("material_id") != expected or source_case.get("status") not in ("complete","solver_limit"):
                raise ValueError("Native continuum material case did not match the fixed reference contract")
            frames = source_case.get("frames")
            if not isinstance(frames,list) or not 1 <= len(frames) <= 256:
                raise ValueError("Native continuum material case has an invalid computed frame count")
            inner_cases.append({"material_id":expected,"status":source_case["status"],
                "computed_frames":len(frames),"error":source_case.get("error","")})
        limited = [case["material_id"] for case in inner_cases if case["status"] == "solver_limit"]
        with self.lock: self.paths[(job_id,0)] = (path,"continuum")
        case_status = "reference_limited" if limited else "reference_complete"
        message = ("Continuum pressure reference completed; strict solver limits stopped: " +
            ", ".join(limited) + ". " if limited else "Continuum pressure reference completed. ") + \
            "The native view replays the computed load sequence; it does not run a fresh impact."
        self.update(job_id,cases=[{"index":0,"name":plan["name"],"package":package,"report":report,
            "native_cli_metadata":metadata,"inner_cases":inner_cases,"status":case_status,"native_scene":True}],
            status="complete",message=message)

    def open_case(self, job_id, index):
        if type(index) is not int: raise ValueError("case_index must be an integer")
        with self.lock:
            if (job_id,index) not in self.paths: raise ValueError("This result has no native scene to open")
            path, kind = self.paths[(job_id,index)]
            self.studios = [p for p in self.studios if p.poll() is None]
            if len(self.studios) >= 4: raise ValueError("Four playground studio windows are open; close one before opening another")
            if kind == "network":
                executable = self.studio_path
                args = [str(executable),str(path.parent),path.name,"--studio"]
            elif kind == "thermal":
                executable = self.studio_path.with_name("banjo_world_lab"+self.studio_path.suffix)
                args = [str(executable),"--package",str(path)]
            elif kind == "continuum":
                executable = self.studio_path.with_name("banjo_continuum_lab"+self.studio_path.suffix)
                args = [str(executable),str(path)]
            else:
                raise ValueError("This result has an unknown native view")
            if not executable.is_file(): raise ValueError("Native studio is not built")
            if kind == "network":
                duration = self.jobs[job_id]["plan"]["duration_s"]
                package = self.jobs[job_id]["cases"][index]["package"]
                actual_duration = max(1,round(duration/package["fixed_dt_s"]))*package["fixed_dt_s"]
                native_reports = path.parent.parent/"native"
                native_reports.mkdir(exist_ok=True)
                args += ["--duration-s",str(actual_duration),"--live-report",str(native_reports/(uuid.uuid4().hex+".json"))]
            # Explicit user-visible native lab, no shell and no generated command.
            startup = None
            if os.name == "nt":
                startup = subprocess.STARTUPINFO()
                startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startup.wShowWindow = 1 # SW_SHOWNORMAL, override the hidden local server.
            process = subprocess.Popen(args,cwd=path.parent,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,startupinfo=startup)
            try:
                process.wait(timeout=.2)
                raise ValueError("Native studio exited during startup; this scene was not opened")
            except subprocess.TimeoutExpired:
                pass
            self.studios.append(process)
            return {"opened":True}

class Handler(BaseHTTPRequestHandler):
    server_version = "BanjoPlayground/1"
    def log_message(self, *_): pass # No prompts, credentials or response bodies in access logs.
    def send(self, value, status=200, content_type="application/json; charset=utf-8"):
        data = json.dumps(value,allow_nan=False).encode() if isinstance(value,(dict,list)) else value
        self.send_response(status)
        self.send_header("Content-Type",content_type)
        self.send_header("Content-Length",str(len(data)))
        self.send_header("Cache-Control","no-store")
        self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("Content-Security-Policy","default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
        self.end_headers(); self.wfile.write(data)
    def trusted_host(self):
        allowed = {f"127.0.0.1:{self.server.server_port}",f"localhost:{self.server.server_port}"}
        if self.headers.get("Host") not in allowed: raise ValueError("Unexpected local Host header")
        origin = self.headers.get("Origin")
        if origin and origin not in {"http://"+host for host in allowed}: raise ValueError("Cross-origin requests are not permitted")
    def do_GET(self):
        try:
            self.trusted_host()
            path=urlsplit(self.path).path
            app=self.server.app
            if path=="/api/status": return self.send(app.status())
            if path=="/api/goal": return self.send({"markdown":(ROOT/"docs/project-goal-2026-09-06.md").read_text(encoding="utf-8")})
            match=re.fullmatch(r"/api/jobs/([0-9a-f]{32})(?:/package/(\d+))?",path)
            if match:
                job=app.get(match[1])
                if match[2] is not None:
                    index=int(match[2])
                    if index>=len(job["cases"]): raise ValueError("Unknown experiment case")
                    return self.send(job["cases"][index]["package"])
                return self.send(job)
            allowed={"/":"index.html","/index.html":"index.html","/app.js":"app.js","/style.css":"style.css"}
            if path not in allowed: return self.send({"error":"Not found"},404)
            file=STATIC/allowed[path]
            mime="text/html" if file.suffix==".html" else "text/javascript" if file.suffix==".js" else "text/css"
            self.send(file.read_bytes(),content_type=mime+"; charset=utf-8")
        except (ValueError,FileNotFoundError) as exc: self.send({"error":str(exc)},400)
    def do_POST(self):
        try:
            self.trusted_host()
            if not secrets.compare_digest(self.headers.get("X-Banjo-Token",""),self.server.app.csrf_token):
                return self.send({"error":"Missing or invalid local session token"},403)
            if self.headers.get("Content-Type","").split(";")[0]!="application/json": raise ValueError("Expected application/json")
            length=int(self.headers.get("Content-Length","0"))
            if not 1<=length<=32768: raise ValueError("Request body exceeds bounds")
            body=strict_json(self.rfile.read(length))
            path=urlsplit(self.path).path
            if path=="/api/chat": return self.send(self.server.app.submit(body),202)
            match=re.fullmatch(r"/api/jobs/([0-9a-f]{32})/open",path)
            if match:
                if not isinstance(body,dict) or set(body)!={"case_index"}: raise ValueError("Expected case_index")
                return self.send(self.server.app.open_case(match[1],body["case_index"]))
            self.send({"error":"Not found"},404)
        except (ValueError,UnicodeError) as exc: self.send({"error":str(exc)},400)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port",type=int,default=8765)
    binary=ROOT/"build/win-joint-double/Release"
    parser.add_argument("--engine",type=Path,default=binary/"banjo_platform_cli.exe")
    parser.add_argument("--studio",type=Path,default=binary/"banjo_network_lab.exe")
    parser.add_argument("--runs",type=Path,default=ROOT/"build/playground-runs")
    args=parser.parse_args()
    if not 1024<=args.port<=65535: parser.error("Use a port in 1024..65535")
    app=Playground(args.engine,args.studio,args.runs)
    server=ThreadingHTTPServer(("127.0.0.1",args.port),Handler);server.app=app
    print(f"Banjo playground: http://127.0.0.1:{args.port}",flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close();app.pool.shutdown(wait=False,cancel_futures=True)

if __name__=="__main__": main()
