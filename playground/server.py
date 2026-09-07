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

from experiment_language import ROOT, KINDS, LIMITATIONS, SCHEMA, PLANNER_SCHEMA, lower_proposal, lower_and_admit, SYSTEM, compile_plan, validate_plan, request_blockers, admit_plan, plan_cost
import builder
import network_admission
from network_admission import Inadmissible, LIMITS, describe_package
from control_contract import default_ui, apply_control
from trust import resolution_verdict, energy_verdict, substepping_verdict, at_rest_control_package, control_verdict
from experiment_diagnostics import build_diagnostics
from experiment_review import review_evidence
from dynamic_material import native_request, execute_impact
from thermal_material import native_request as thermal_native_request, execute_experiment
from banjo_authoring import EngineCLI, EngineError, write_package, validate_network_geometry

STATIC = Path(__file__).resolve().parent
ACTIVE = {"planning", "validating", "running"}


def describe_failure(plan, error, limit=None):
    """Explain current and archived admission failures without rewriting the run.

    ``limit`` is the named engine limit an `Inadmissible` refusal carried; a job
    restored from disk has only the message, so both paths are accepted.
    """
    message = str(error)
    limit = limit or getattr(error, "limit", None)
    if limit or "not cubic" in message or "face-to-thickness" in message:
        return {"code": f"network_{limit}" if limit else "network_geometry",
                "summary": "This geometry cannot be built from the engine's cells.",
                "detail": message,
                "scope": ("Setup refused before simulation. No substitute geometry was run, and "
                          "geometric admission does not validate fracture.")}
    if "network cells below collision resolution" not in message and "Network collision cells are too small" not in message:
        return {"code": "experiment_error", "summary": message,
                "detail": "The experiment did not produce a recording. Edit the request to review its setup.",
                "scope": "Execution failure; no computed playback is available."}
    detail = message
    drop = (plan or {}).get("drop")
    if isinstance(drop, dict):
        try:
            validate_network_geometry(drop.get("target_dimensions_m"), drop.get("resolution"))
        except ValueError as exc:
            detail = str(exc)
    return {"code": "network_collision_resolution",
            "summary": "The generated plate cells are too small for the collision engine.",
            "detail": detail,
            "scope": "Setup rejected before simulation. Collision-cell admission does not validate thin-glass fracture."}

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
        "text": {"format": {"type": "json_schema", "name": "banjo_experiment", "strict": True, "schema": PLANNER_SCHEMA}}}
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
    # The strict validators refuse a non-cubic mesh outright, so geometry is
    # admitted (repaired, or refused by name) while lowering rather than after.
    plan = lower_and_admit(strict_json("".join(texts)), repair_ui=True)
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
        self.jobs, self.requests, self.paths, self.playbacks = {}, {}, {}, {}
        self.lock = threading.RLock()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="banjo-playground")
        self.studios = []
        self.reviewing = set()

    def log_event(self, job_id, event, **fields):
        directory = self.runs_path / job_id
        if not directory.is_dir(): return
        record = {"schema":"banjo.experiment-event.v1","time_unix_s":time.time(),"job_id":job_id,"event":event,**fields}
        encoded=json.dumps(record,allow_nan=False)
        if self.api_key: encoded=encoded.replace(self.api_key,"[redacted]")
        with self.lock:
            with (directory/"events.jsonl").open("a",encoding="utf-8") as stream: stream.write(encoded+"\n")

    def status(self):
        return {"key_configured": bool(self.api_key), "model": self.model,
            "engine_ready": self.engine_path.is_file(), "studio_ready": self.studio_path.is_file(),
            "csrf_token": self.csrf_token, "capabilities": [kind for kind in KINDS if kind != "unsupported"], "limitations": LIMITATIONS,
            "examples": ["Use the new coupled material solver to compare two fictional elastic and plastic materials under a small iron-density sphere impact. Show their actual deformation and contact evidence in 3D.",
                "Compare an iron ball hitting glass, wood and iron panels at 2 m/s for 1 second.",
                "Drop an iron ball from 25 cm onto glass, wood and iron. Use a rigid control first.",
                "Compare the fixed spatial quasistatic pressure response of glass, oak and iron.",
                "Show the published 6 mm tempered-glass drop benchmark and what is missing.",
                "Run the permanent deformation and compact save/reload reference test.",
                "Show heat moving through glass, wood, iron and water/ice."]}

    def submit(self, body, *, prepared_plan=None):
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
            self.pool.submit(self.execute, job_id, message, previous, body.get("auto_open", True), prepared_plan)
            return {"job_id": job_id}

    def run_package(self, body):
        """Run an authored package directly, with no model in the path.

        The chat route asks a model to author a declaration, and the model does
        not know this engine's substep budget, so it can produce scenes the
        solver correctly refuses. An experiment that has already been authored
        against the engine's own limits needs a way in. The package is validated
        by the engine exactly as a generated one is; nothing here bypasses an
        audit, only the authoring step.
        """
        if not isinstance(body, dict) or set(body) - {"package", "builder", "name", "steps", "request_id"}:
            raise ValueError("Expected package or builder, plus name, steps and request_id")
        if ("package" in body) == ("builder" in body):
            raise ValueError("Supply exactly one of package or builder")
        steps = body.get("steps", 120)
        if "builder" in body:
            # The builder panel sends parameters, not a package, so the package
            # is compiled here from the same authoring API the model route uses
            # and checked against the same limits. An inadmissible setup raises
            # before a job exists.
            spec = builder.validate_builder(body["builder"])
            package = builder.compile_builder(spec)
            if steps is None: steps = builder.steps_for(spec)
        else:
            package = body.get("package")
            if not isinstance(package, dict): raise ValueError("package must be an object")
        request_id = body.get("request_id")
        if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", request_id):
            raise ValueError("Invalid request identity")
        if type(steps) is not int or not 1 <= steps <= 1440: raise ValueError("steps must be 1..1440")
        name = body.get("name") or package.get("name") or "Authored package"
        if not isinstance(name, str) or len(name) > 200: raise ValueError("name must be a short string")
        # Refuse the whole class of scenes the engine would reject, before the
        # job is created: a run that fails four minutes in is worse than one
        # that never starts.
        admission = describe_package(package, steps)
        if not admission["admissible"]:
            first = admission["problems"][0]
            raise Inadmissible(first["message"], limit=first["limit"])
        if admission["cost"]["recording_over_budget"]:
            raise Inadmissible(
                f"This run would record about {admission['cost']['estimated_recording_mb']:.0f} MB "
                f"and the recorder refuses anything over 64 MB, after doing all the work. "
                f"Reduce the cell count or shorten the run.", limit="recording_bytes")
        fingerprint = hashlib.sha256(json.dumps(body, sort_keys=True, allow_nan=False).encode()).hexdigest()
        with self.lock:
            if request_id in self.requests:
                old, job_id = self.requests[request_id]
                if old != fingerprint: raise ValueError("Request identity was already used for different content")
                return {"job_id": job_id}
            if any(j["status"] in ACTIVE for j in self.jobs.values()):
                raise ValueError("One experiment is already running; wait for its result")
            if not self.engine_path.is_file(): raise ValueError("Build banjo_platform_cli before running packages")
            job_id = uuid.uuid4().hex
            self.requests[request_id] = (fingerprint, job_id)
            self.jobs[job_id] = {"id": job_id, "status": "running",
                "message": (f"Running authored package: {name}. "
                            f"{admission['cost']['substeps_per_host_tick']} internal solves per "
                            f"tick; estimated {admission['cost']['estimated_wall_text']}."),
                "plan": None, "request_text": name,
                "admission": {"notes": [], "limits": LIMITS, "cost": {
                    "cases": [admission["cost"]],
                    "estimated_wall_s": admission["cost"]["estimated_wall_s"],
                    "estimated_wall_text": admission["cost"]["estimated_wall_text"],
                    "worst_substeps_per_tick": admission["cost"]["substeps_per_host_tick"],
                    "basis": admission["cost"]["basis"]}},
                "cases": [], "warnings": list(LIMITATIONS), "timing": {}}
        self.pool.submit(self.execute_package, job_id, name, package, steps, admission["cost"])
        return {"job_id": job_id}

    def execute_package(self, job_id, name, package, steps, estimate=None):
        directory = self.runs_path / job_id
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "package-00.json"
        path.write_text(json.dumps(package, indent=1, allow_nan=False), encoding="utf-8")
        case = {"index": 0, "name": name, "package": package, "status": "pending",
                "requested_steps": steps, "native_scene": True, "cost": estimate}
        started = time.perf_counter()
        try:
            self.engine.validate(path)
            recorder = self.engine_path.with_name("banjo_playground_record" + self.engine_path.suffix)
            if not recorder.is_file():
                raise ValueError("Build banjo_playground_record to record an authored package")
            playback = directory / "playback-00.json"
            self.log_event(job_id, "authored_package_started", steps=steps, name=name)
            result = subprocess.run(
                [str(recorder), "--package", str(path), "--steps", str(steps), "--output", str(playback)],
                capture_output=True, text=True, encoding="utf-8", timeout=7200, check=False)
            if result.returncode or not playback.is_file():
                raise ValueError(f"Recording failed: {result.stdout.strip()[:200]}")
            if playback.stat().st_size > 64*1024*1024:
                raise ValueError("Native recording exceeds browser byte budget")
            recording = strict_json(playback.read_text(encoding="utf-8"))
            if recording.get("schema") != "banjo.playback.v1" or recording.get("status") not in ("complete", "solver_limit"):
                raise ValueError("Native recording does not match browser contract")
            case["report"], case["status"] = recording.get("report", {}), recording.get("status", "complete")
            case["playback_available"] = True
            if recording.get("error"): case["error"] = recording["error"]
            case["trust"] = {"resolution": resolution_verdict(package, case["report"]),
                             "energy": energy_verdict(case["report"]),
                             "substepping": substepping_verdict(case["report"])}
            with self.lock: self.playbacks[(job_id, 0)] = playback
            with self.lock: self.paths[(job_id, 0)] = (path, "network")
            case["wall_s"] = round(time.perf_counter() - started, 1)
            # The estimate is only worth showing if it is checked against the
            # thing it predicted, so record both next to each other.
            if estimate:
                case["cost"] = {**estimate, "measured_wall_s": case["wall_s"],
                                "measured_substeps_per_tick": network_admission.measured_substeps(case["report"]),
                                "wall_error": (case["wall_s"] - estimate["estimated_wall_s"]) / max(1e-9, estimate["estimated_wall_s"])}
                self.log_event(job_id, "cost_measured", estimated_wall_s=estimate["estimated_wall_s"],
                               measured_wall_s=case["wall_s"],
                               estimated_substeps=estimate["substeps_per_host_tick"],
                               measured_substeps=case["cost"]["measured_substeps_per_tick"])
            self.update(job_id, status="complete", cases=[case],
                        message="Authored package finished. Open the 3D playback tab.")
            self.log_event(job_id, "authored_package_finished", status=case["status"],
                           broken_links=case["report"].get("broken_links"),
                           components=case["report"].get("connected_components"))
        except (ValueError, EngineError, subprocess.TimeoutExpired) as exc:
            case["status"], case["error"] = "error", str(exc)
            case["wall_s"] = round(time.perf_counter() - started, 1)
            self.update(job_id, status="error", error=str(exc)[:300], cases=[case], message=str(exc)[:300])
        (directory / "job.json").write_text(json.dumps(self.get(job_id), indent=2, allow_nan=False),
                                            encoding="utf-8")

    def update(self, job_id, **fields):
        with self.lock: self.jobs[job_id].update(fields)
        if "status" in fields: self.log_event(job_id,"state",status=fields["status"],message=fields.get("message",""))

    def get(self, job_id):
        with self.lock:
            if job_id not in self.jobs:
                if not isinstance(job_id,str) or not re.fullmatch(r"[0-9a-f]{32}",job_id): raise ValueError("Unknown experiment")
                directory = self.runs_path / job_id
                path = directory / "job.json"
                if directory.resolve().parent != self.runs_path or not path.is_file() or path.is_symlink() or path.stat().st_size > 16*1024*1024:
                    raise ValueError("Unknown experiment or archived report exceeds budget")
                saved = strict_json(path.read_text(encoding="utf-8"))
                if saved.get("id") != job_id or saved.get("status") not in ("complete","blocked","error") or not isinstance(saved.get("cases"),list) or len(saved["cases"])>4:
                    raise ValueError("Invalid archived experiment")
                if len(self.jobs)>=100: raise ValueError("Session history budget reached")
                for index,case in enumerate(saved["cases"]):
                    # A package job authored outside the chat route has no plan.
                    experiment = (saved.get("plan") or {}).get("experiment")
                    filename = ("reference-report.json" if experiment == "continuum_pressure_reference" else
                                "dynamic-playback.json" if experiment == "dynamic_material_impact" else f"playback-{index:02d}.json")
                    if experiment == "thermal_material_experiment": filename = "thermal-response.json"
                    recording = directory / filename
                    available = case.get("playback_available") and recording.is_file() and not recording.is_symlink() and recording.stat().st_size <= 64*1024*1024
                    case["playback_available"] = bool(available)
                    case["native_scene"] = False
                    if available: self.playbacks[(job_id,index)] = recording
                    package_file = directory / f"package-{index:02d}.json"
                    if saved.get("plan") is None and package_file.is_file() and not package_file.is_symlink():
                        self.paths[(job_id, index)] = (package_file, "network")
                        case["native_scene"] = True
                saved["restored_from_disk"] = True
                self.jobs[job_id] = saved
            result = deepcopy(self.jobs[job_id])
            if result.get("status") == "error":
                result["failure_detail"] = describe_failure(
                    result.get("plan"), result.get("error", result.get("message", "Experiment failed")),
                    result.get("admission_limit"))
            return result

    def execute(self, job_id, message, previous, auto_open, prepared_plan=None):
        start = time.perf_counter()
        directory = self.runs_path / job_id
        try:
            directory.mkdir(parents=True, exist_ok=False)
            self.log_event(job_id,"started",planning="model" if prepared_plan is None else "validated_control",engine_sha256=hashlib.sha256(self.engine_path.read_bytes()).hexdigest(),source_sha256={name:hashlib.sha256((STATIC/name).read_bytes()).hexdigest() for name in ("server.py","experiment_language.py","control_contract.py","experiment_diagnostics.py","dynamic_material.py","thermal_material.py","drop_builder.py","scene_composer.py")},authoring_api_sha256=hashlib.sha256((ROOT/"examples/authoring/banjo_authoring.py").read_bytes()).hexdigest())
            self.update(job_id,request_text=message)
            if prepared_plan is None:
                plan, timing = self.planner(self.api_key, self.model, message, previous)
            else:
                plan, timing = deepcopy(prepared_plan), {"planning_wall_s":0,"model":None,"source":"validated playground control; no model call"}
            validate_plan(plan)
            plan.setdefault("ui", default_ui(plan["experiment"]))
            # The model does not know the engine's cubic-cell rule, its cell
            # budgets or its stability clock, so an authored plan is checked
            # against them before anything is compiled. A repairable plan is
            # snapped to the nearest admissible mesh and the change is reported;
            # an unrepairable one is refused by name. Nothing is changed quietly
            # and no substitute geometry is ever run.
            plan, admission_notes = admit_plan(plan)
            self.update(job_id, plan=plan, timing=timing, status="validating", message=plan["explanation"],
                warnings=list(dict.fromkeys(LIMITATIONS + plan["limitations"] +
                                            [note["message"] for note in admission_notes])),
                admission={"notes": admission_notes, "limits": LIMITS})
            (directory / "plan.json").write_text(json.dumps(plan, indent=2, allow_nan=False), encoding="utf-8")
            if admission_notes:
                self.log_event(job_id, "admission_repaired", notes=admission_notes)
            blockers = request_blockers(message,plan)
            if blockers:
                self.update(job_id,status="blocked",message="Request not executed: "+" ".join(blockers))
                (directory/"job.json").write_text(json.dumps(self.get(job_id),indent=2,allow_nan=False),encoding="utf-8")
                return
            packages = compile_plan(plan)
            if packages:
                cost = plan_cost(plan, packages)
                self.update(job_id, admission={"notes": admission_notes, "limits": LIMITS,
                                               "cost": cost})
                self.log_event(job_id, "cost_estimated", estimated_wall_s=cost["estimated_wall_s"],
                               worst_substeps_per_tick=cost["worst_substeps_per_tick"])
            if plan["experiment"] in ("unsupported", "glass_reference"):
                if plan["experiment"] == "glass_reference":
                    reference = json.loads((ROOT/"assets/benchmarks/glass-drop-reference.json").read_text(encoding="utf-8"))
                    self.update(job_id, cases=[{"index":0,"name":"Published 6 mm tempered glass reference", "package":{},
                        "status":"reference_only","report":reference,"native_scene":False}])
                self.update(job_id, status="blocked", message=plan["explanation"] + " No substitute simulation was presented as this capability.")
            elif plan["experiment"] == "dynamic_material_impact":
                self.run_dynamic_impact(job_id, directory, plan)
            elif plan["experiment"] == "thermal_material_experiment":
                self.run_thermal_material(job_id, directory, plan)
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
                    cases.append({"index":index,"name":package["name"],"package":package,"report":None,"status":"validated","native_scene":True,
                                  "cost": cost["cases"][index]})
                self.update(job_id, cases=deepcopy(cases), status="running",
                    message=(f"Validated Banjo packages are running in the native engine. "
                             f"{len(cases)} case(s) at up to {cost['worst_substeps_per_tick']} internal "
                             f"solves per tick; estimated {cost['estimated_wall_text']} of computation."))
                for index, case in enumerate(cases):
                    path, _ = self.paths[(job_id,index)]
                    steps = max(1, round(plan["duration_s"]/case["package"]["fixed_dt_s"]))
                    case_start = time.perf_counter()
                    try:
                        recorder = self.engine_path.with_name("banjo_playground_record"+self.engine_path.suffix)
                        if recorder.is_file():
                            self.log_event(job_id,"native_execution_started",case_index=index,recorder_sha256=hashlib.sha256(recorder.read_bytes()).hexdigest(),requested_steps=steps)
                            playback = directory/f"playback-{index:02d}.json"
                            # The network runs on its own stability clock now, several hundred internal
                            # solves per host tick, so a recording that used to take seconds
                            # takes minutes. See docs/network-at-rest-stability-checkpoint.md.
                            result = subprocess.run([str(recorder),"--package",str(path),"--steps",str(steps),"--output",str(playback)],capture_output=True,text=True,encoding="utf-8",timeout=1800,check=False)
                            if result.returncode or not playback.is_file(): raise ValueError("Native browser recording failed; no substitute motion was generated")
                            if playback.stat().st_size > 64*1024*1024: raise ValueError("Native recording exceeds browser byte budget")
                            recording = strict_json(playback.read_text(encoding="utf-8"))
                            if recording.get("schema") != "banjo.playback.v1" or recording.get("status") not in ("complete","solver_limit"):
                                raise ValueError("Native recording does not match browser contract")
                            case["report"],case["status"] = recording["report"],recording["status"]
                            case["diagnostics"] = build_diagnostics(plan,case["package"],recording)
                            (directory/f"diagnostics-{index:02d}.json").write_text(json.dumps(case["diagnostics"],indent=2,allow_nan=False),encoding="utf-8")
                            self.log_event(job_id,"case_recorded",case_index=index,status=case["status"],completed_steps=recording.get("completed_steps"),requested_steps=steps,diagnostics_file=f"diagnostics-{index:02d}.json")
                            case["playback_available"] = True
                            if recording.get("error"): case["error"] = recording["error"]
                            with self.lock: self.playbacks[(job_id,index)] = playback
                        else:
                            case["report"] = self.engine.run(path, steps)
                            case["status"] = "complete"
                            case["playback_available"] = False
                            case["view_warning"] = "Build banjo_playground_record to enable embedded 3D viewing."
                        if case["report"].get("temporal_resolution",{}).get("resolved") is False:
                            case["assessment"] = "Numerically unresolved — recorded motion is diagnostic, not a reliable material outcome."
                        case["trust"] = {"resolution": resolution_verdict(case.get("package",{}),case["report"]),
                                         "energy": energy_verdict(case["report"]),
                                         "substepping": substepping_verdict(case["report"])}
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
                unresolved = any(case.get("assessment") for case in cases)
                self.update(job_id, status="complete", message=("Computation finished with solver limits or unresolved physics; inspect the diagnostic 3D recording and reports." if limited or unresolved else "Computation finished. Open the 3D playground to inspect the actual recorded engine states; material calibration remains experimental."))
            snapshot = self.get(job_id)
            snapshot["timing"]["total_wall_s"] = time.perf_counter()-start
            self.update(job_id, timing=snapshot["timing"])
            self.log_event(job_id,"finished",status=snapshot["status"],total_wall_s=snapshot["timing"]["total_wall_s"])
            (directory/"job.json").write_text(json.dumps(self.get(job_id),indent=2,allow_nan=False),encoding="utf-8")
        except Exception as exc:
            # Never expose arbitrary upstream HTTP bodies or secrets.
            public = str(exc) if isinstance(exc, (ValueError, EngineError)) else "The local experiment failed; inspect the bounded setup and build availability."
            if self.api_key: public = public.replace(self.api_key, "[redacted]")
            # Keep the named limit so the browser reports which rule refused it
            # rather than guessing from the message text.
            self.update(job_id, status="error", error=public, message=public,
                        admission_limit=getattr(exc, "limit", None))
            self.log_event(job_id,"error",message=public)
            if directory.is_dir():
                (directory/"job.json").write_text(json.dumps(self.get(job_id),indent=2,allow_nan=False),encoding="utf-8")

    def run_dynamic_impact(self, job_id, directory, plan):
        self.update(job_id, status="running", message="Solving the authored materials and recording accepted sphere and mesh states.")
        executable = self.engine_path.with_name("banjo_dynamic_material_cli" + self.engine_path.suffix)
        package = native_request(plan["impact"], plan["duration_s"])
        (directory / "dynamic-request.json").write_text(json.dumps(package, indent=2, allow_nan=False), encoding="utf-8")
        start = time.perf_counter()
        recording, provenance = execute_impact(executable, package)
        wall_s = time.perf_counter() - start
        path = directory / "dynamic-playback.json"
        path.write_text(json.dumps(recording, separators=(",", ":"), allow_nan=False), encoding="utf-8")
        provenance["saved_recording_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        report = {key: value for key, value in recording.items() if key != "cases"}
        report["cases"] = [{key: value for key, value in case.items() if key not in ("frames", "mesh")}
                           for case in recording["cases"]]
        inner = [{"material_id": case["material_id"], "status": case["status"],
                  "computed_frames": len(case["frames"]), "error": case.get("error", "")}
                 for case in recording["cases"]]
        diagnostics = build_diagnostics(plan, package, recording)
        self.log_event(job_id, "dynamic_material_recorded", provenance=provenance,
                       wall_s=wall_s, cases=inner, diagnostics=diagnostics)
        with self.lock:
            self.playbacks[(job_id, 0)] = path
        limited = [case["material_id"] for case in inner if case["status"] == "solver_limit"]
        message = ("The requested interval completed for every material." if not limited else
                   "Solver limits stopped: " + ", ".join(limited) + ". The recording retains their last accepted states.")
        self.update(job_id, status="complete", message=message + " Open the 3D playground to inspect the computed sphere and material motion.",
                    cases=[{"index": 0, "name": plan["name"], "package": package, "report": report,
                            "status": recording["status"], "inner_cases": inner, "wall_s": wall_s,
                            "provenance": provenance, "diagnostics": diagnostics,
                            "native_scene": False, "playback_available": True}])

    def run_thermal_material(self, job_id, directory, plan):
        self.update(job_id, status="running",
                    message="Running the authored fixed-grid solid thermal experiment.")
        executable = self.engine_path.with_name("banjo_thermal_experiment_cli" +
                                                self.engine_path.suffix)
        request_document = thermal_native_request(plan["thermal"])
        (directory / "thermal-request.json").write_text(
            json.dumps(request_document, indent=2, allow_nan=False), encoding="utf-8")
        start = time.perf_counter()
        recording, provenance = execute_experiment(executable, plan["thermal"])
        wall_s = time.perf_counter() - start
        path = directory / "thermal-response.json"
        path.write_text(json.dumps(recording, separators=(",", ":"), allow_nan=False),
                        encoding="utf-8")
        provenance["saved_response_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        evidence = {"status": recording["status"],
                    "completed_time_s": recording["completed_time_s"],
                    "requested_horizon_s": recording["requested_horizon_s"],
                    "remaining_duration_s": recording["remaining_duration_s"],
                    "scheduler_backlog_s": recording["scheduler_backlog_s"],
                    "computed_frames": len(recording["frames"]),
                    "work": deepcopy(recording["work"]),
                    "final_ledger": deepcopy(recording["final_ledger"]),
                    "error": recording.get("error", "")}
        diagnostics = build_diagnostics(plan, request_document, recording)
        (directory / "diagnostics-00.json").write_text(
            json.dumps(diagnostics, indent=2, allow_nan=False), encoding="utf-8")
        self.log_event(job_id, "thermal_material_recorded", provenance=provenance,
                       wall_s=wall_s, measured_evidence=evidence,
                       response_file="thermal-response.json", diagnostics=diagnostics)
        with self.lock:
            self.playbacks[(job_id, 0)] = path
        message = ("The requested thermal interval completed." if recording["status"] == "complete"
                   else "Solver limits stopped the thermal run; the full last accepted state and ledgers were retained.")
        self.update(job_id, status="complete", message=message +
                    " View the accepted fixed-grid cell states and temperature legend in the 3D playground.",
                    cases=[{"index": 0, "name": plan["name"], "package": request_document,
                            "report": recording, "status": recording["status"],
                            "measured_evidence": evidence, "wall_s": wall_s,
                            "provenance": provenance, "diagnostics": diagnostics,
                            "native_scene": False,
                            "playback_available": True,
                            "view_warning": "Thermal cells retain authored positions; color shows temperature. No flame, smoke or mechanical motion is generated."}])

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
            pressure = plan.get("pressure") or {"peak_pressure_pa":800000000,"resolution":4,"increments":32,"profile":"uniform"}
            package = {
                "reference":"fixed spatial quasistatic pressure load-unload; no collision, inertia or fracture",
                "physics_abi":"banjo-quasistatic-tet-1", "units":"SI",
                "fixture":{"dimensions_m":[.04,.02,.04],"resolution":[4,2,4],
                    "bottom_boundary":"fully clamped","loaded_top_area_m2":.0004,
                    "peak_pressure_pa":pressure["peak_pressure_pa"],"increments_per_load_or_unload":pressure["increments"],"pressure_profile":pressure["profile"]},
                "laws":{"glass":"isotropic-linear-elastic","oak":"orthotropic-linear-elastic",
                    "iron":"small-strain-isotropic-J2"},
                "ignored_plan_fields":["duration_s","projectile","panel_dimensions_m","speeds_m_s","heights_m","objects"],
                "native_view_mode":"solved_load_sequence_playback",
            }
            n=pressure["resolution"];package["fixture"]["resolution"]=[n,n//2,n]
            args = [str(executable),"--resolution",str(n),"--increments",str(pressure["increments"]),
                    "--peak-pressure-pa",str(pressure["peak_pressure_pa"]),"--pressure-profile",pressure["profile"],"--output",str(path)]
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
        with self.lock:
            self.paths[(job_id,0)] = (path,"continuum")
            self.playbacks[(job_id,0)] = path
        case_status = "reference_limited" if limited else "reference_complete"
        message = ("Continuum pressure reference completed; strict solver limits stopped: " +
            ", ".join(limited) + ". " if limited else "Continuum pressure reference completed. ") + \
            "The native view replays the computed load sequence; it does not run a fresh impact."
        self.update(job_id,cases=[{"index":0,"name":plan["name"],"package":package,"report":report,
            "native_cli_metadata":metadata,"inner_cases":inner_cases,"status":case_status,"native_scene":True,"playback_available":True}],
            status="complete",message=message)

    def playback(self, job_id, index):
        if (job_id,index) not in self.playbacks: self.get(job_id)
        with self.lock:
            if (job_id,index) not in self.playbacks: raise ValueError("This case has no computed 3D recording")
            path=self.playbacks[(job_id,index)]
        if path.stat().st_size > 64*1024*1024: raise ValueError("Playback exceeds browser byte budget")
        return path.read_bytes()

    def rerun(self, job_id, body):
        if not isinstance(body,dict) or set(body)!={"case_index","action","value","request_id"}:
            raise ValueError("Expected case_index, action, value and request_id")
        job=self.get(job_id); index=body["case_index"]
        if job["status"] != "complete" or type(index) is not int or not 0<=index<len(job["cases"]): raise ValueError("Choose a completed experiment case")
        plan=apply_control(job["plan"],body["action"],body["value"],index)
        plan["explanation"]=f"New native run from {job['plan']['name']}: {body['action']} = {body['value']}. Other declared settings are retained."
        if plan["duration_s"] != job["plan"]["duration_s"]:
            plan["explanation"] = f"New native run: {body['action']} = {body['value']}. Recording extended from {job['plan']['duration_s']:g} to {plan['duration_s']:g} seconds to include the estimated fall and 0.5 seconds of contact/rebound observation. Other physical settings are retained."
        validate_plan(plan)
        return self.submit({"message":f"Playground control from {job_id} case {index}: {body['action']}={body['value']}","request_id":body["request_id"],"auto_open":False},prepared_plan=plan)

    def evidence(self, job_id, index):
        job=self.get(job_id)
        if type(index) is not int or not 0<=index<len(job["cases"]): raise ValueError("Choose an experiment case")
        case=job["cases"][index]
        # A package job has no authored plan; describe it from the package.
        plan=job.get("plan") or {"name":case.get("name","Authored package"),
            "experiment":"authored_package","duration_s":(case.get("requested_steps") or 0)*
                float(case.get("package",{}).get("fixed_dt_s") or 0),
            "explanation":"Authored package run directly, with no model in the path.",
            "requirements":[]}
        diagnostics=case.get("diagnostics")
        if diagnostics is None or case.get("playback_available"):
            if case.get("playback_available"):
                recording=strict_json(self.playback(job_id,index))
                diagnostics=build_diagnostics(plan,case.get("package",{}),recording)
            else:
                diagnostics=build_diagnostics(plan,case.get("package",{}),{"status":case["status"],"report":case.get("report",{})})
        path=self.runs_path/job_id/"events.jsonl"
        events=[]
        if path.is_file() and path.stat().st_size<=256*1024:
            events=[strict_json(line) for line in path.read_text(encoding="utf-8").splitlines() if line][-64:]
        bundle={"job_id":job_id,"case_index":index,"request":job.get("request_text","Original request was not retained by this older job"),"plan":{"name":plan["name"],"experiment":plan["experiment"],"duration_s":plan["duration_s"],"explanation":plan["explanation"]},"case_wall_s":case.get("wall_s"),"cost":case.get("cost"),"admission":job.get("admission"),"response_scope":("Rigid drop: fracture and deformation are disabled regardless of material damage parameters" if (plan.get("drop") or {}).get("representation")=="rigid" else "Consult the authored representation and reported constitutive limits"),"requirements":plan.get("requirements",[]),"diagnostics_source_sha256":hashlib.sha256((STATIC/"experiment_diagnostics.py").read_bytes()).hexdigest(),"diagnostics":diagnostics,"events":events,"llm_review":case.get("llm_review")}
        return strict_json(json.dumps(bundle,allow_nan=False).replace(self.api_key,"[redacted]") if self.api_key else json.dumps(bundle,allow_nan=False))

    def analyze(self, job_id, body):
        if not isinstance(body,dict) or set(body)!={"case_index"}: raise ValueError("Expected case_index")
        index=body["case_index"]
        evidence=self.evidence(job_id,index)
        if self.get(job_id)["status"] not in {"complete","error"}: raise ValueError("Wait for the experiment to finish before analysis")
        if evidence["llm_review"] is not None: return evidence["llm_review"]
        key=(job_id,index)
        with self.lock:
            cached=self.jobs[job_id]["cases"][index].get("llm_review")
            if cached is not None: return cached
            if key in self.reviewing: raise ValueError("Analysis already running; wait for it to finish")
            self.reviewing.add(key)
        try:
            self.log_event(job_id,"review_started",case_index=index,model=self.model)
            (self.runs_path/job_id/f"review-evidence-{index:02d}.json").write_text(json.dumps(evidence,indent=2,allow_nan=False),encoding="utf-8")
            result=review_evidence(self.api_key,self.model,evidence)
            with self.lock:
                self.jobs[job_id]["cases"][index]["llm_review"]=result
                (self.runs_path/job_id/"job.json").write_text(json.dumps(self.jobs[job_id],indent=2,allow_nan=False),encoding="utf-8")
            self.log_event(job_id,"review_finished",case_index=index)
            return result
        except Exception:
            self.log_event(job_id,"review_failed",case_index=index)
            raise
        finally:
            with self.lock: self.reviewing.discard(key)

    def at_rest_control(self, job_id, index):
        """Re-run this case's own scene with nothing acting on it.

        Same materials, mesh, pinning, timestep and solver iterations; no
        gravity, no ground, no striker, zero velocity. The exact answer is that
        nothing happens, so anything this reports was manufactured by the
        solver rather than by the experiment.
        """
        job=self.get(job_id)
        if type(index) is not int or not 0<=index<len(job["cases"]): raise ValueError("Choose an experiment case")
        case=job["cases"][index]
        package=case.get("package")
        if not package: raise ValueError("This case has no package to control")
        control=at_rest_control_package(package)
        directory=self.runs_path/job_id
        directory.mkdir(parents=True,exist_ok=True)
        path=directory/f"at-rest-control-{index:02d}.json"
        path.write_text(json.dumps(control,indent=1,allow_nan=False),encoding="utf-8")
        steps=case.get("requested_steps") or 240
        self.log_event(job_id,"at_rest_control_started",case_index=index,steps=steps)
        try:
            report=self.engine.run(path,steps)
        except EngineError as exc:
            report=exc.report
        verdict=control_verdict(report)
        verdict["steps"]=steps
        verdict["package_file"]=path.name
        self.log_event(job_id,"at_rest_control_finished",case_index=index,clean=verdict["clean"],
                       broken_links=verdict["broken_links"],created_energy_j=verdict["created_energy_j"])
        with self.lock:
            stored=self.jobs[job_id]["cases"]
            if index<len(stored): stored[index]["at_rest_control"]=verdict
        return verdict

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
                case = self.jobs[job_id]["cases"][index]
                package = case["package"]
                plan = self.jobs[job_id].get("plan")
                # A package job carries its own step count instead of a plan.
                steps = (max(1, round(plan["duration_s"]/package["fixed_dt_s"])) if plan
                         else int(case.get("requested_steps") or 120))
                actual_duration = steps*package["fixed_dt_s"]
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
    timeout = 5
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
            if path=="/api/goal": return self.send({"markdown":(ROOT/"docs/project-goal-2026-09-06.md").read_text(encoding="utf-8") + "\n\n" + (ROOT/"docs/rules-engine-execution-plan.md").read_text(encoding="utf-8")})
            if path=="/api/goals": return self.send(strict_json((ROOT/"docs/execution-goals.json").read_text(encoding="utf-8")))
            if path=="/api/schema": return self.send({"language":"banjo-playground-1","schema":SCHEMA,"material_validation":"experimental; no calibrated fracture claim","limits":{"network_cells":850,"objects":12,"sweep_cases":4,"duration_s":3,"dynamic_material_duration_s":.1,"dynamic_material_cases":3,"dynamic_material_step_calls_per_case":200000,"recording_bytes":64*1024*1024,**LIMITS}})
            if path=="/api/builder": return self.send({
                "schema":builder.BUILDER_SCHEMA,"default":builder.DEFAULT,
                "materials":builder.MATERIALS,"projectiles":sorted(builder.PROJECTILES),
                "supports":list(builder.SUPPORTS),"tick_rates_hz":list(builder.TICK_RATES_HZ),
                "limits":LIMITS,
                "notes":["Cost is set by the smallest cell: halving a spacing roughly doubles the run.",
                         "Admission is not calibration. The engine reports physical_response_validated: false."]})
            match=re.fullmatch(r"/api/jobs/([0-9a-f]{32})/diagnostics/(\d+)",path)
            if match: return self.send(app.evidence(match[1],int(match[2])))
            match=re.fullmatch(r"/api/jobs/([0-9a-f]{32})/playback/(\d+)",path)
            if match: return self.send(app.playback(match[1],int(match[2])))
            match=re.fullmatch(r"/api/jobs/([0-9a-f]{32})(?:/package/(\d+))?",path)
            if match:
                job=app.get(match[1])
                if match[2] is not None:
                    index=int(match[2])
                    if index>=len(job["cases"]): raise ValueError("Unknown experiment case")
                    return self.send(job["cases"][index]["package"])
                return self.send(job)
            allowed={"/":"index.html","/index.html":"index.html","/app.js":"app.js","/style.css":"style.css","/scene.js":"scene.js",
                "/vendor/three.module.js":"vendor/three.module.js","/vendor/three.core.js":"vendor/three.core.js"}
            if path not in allowed: return self.send({"error":"Not found"},404)
            file=STATIC/allowed[path]
            mime="text/html" if file.suffix==".html" else "text/javascript" if file.suffix==".js" else "text/css"
            self.send(file.read_bytes(),content_type=mime+"; charset=utf-8")
        except (ValueError,FileNotFoundError) as exc: self.send({"error":str(exc)},400)
    def do_POST(self):
        try:
            length=int(self.headers.get("Content-Length","0"))
            if not 1<=length<=32768: raise ValueError("Request body exceeds bounds")
            # Consume the bounded body before rejecting headers. Closing with
            # unread POST bytes can reset the TCP connection on Windows and
            # discard the intended 400/403 response. No JSON is interpreted or
            # application action invoked until origin/session checks pass.
            raw_body=self.rfile.read(length)
            if len(raw_body)!=length: raise ValueError("Incomplete request body")
            self.trusted_host()
            if not secrets.compare_digest(self.headers.get("X-Banjo-Token",""),self.server.app.csrf_token):
                return self.send({"error":"Missing or invalid local session token"},403)
            if self.headers.get("Content-Type","").split(";")[0]!="application/json": raise ValueError("Expected application/json")
            body=strict_json(raw_body)
            path=urlsplit(self.path).path
            if path=="/api/chat": return self.send(self.server.app.submit(body),202)
            if path=="/api/packages/run": return self.send(self.server.app.run_package(body),202)
            # Pure computation: admission verdict, repair and cost for a builder
            # setup. Nothing is executed, so the panel can show what a run would
            # cost before anyone commits to waiting for it.
            if path=="/api/builder/preview": return self.send(builder.describe(body))
            match=re.fullmatch(r"/api/jobs/([0-9a-f]{32})/analyze",path)
            if match: return self.send(self.server.app.analyze(match[1],body))
            match=re.fullmatch(r"/api/jobs/([0-9a-f]{32})/rerun",path)
            if match: return self.send(self.server.app.rerun(match[1],body),202)
            match=re.fullmatch(r"/api/jobs/([0-9a-f]{32})/control",path)
            if match:
                if not isinstance(body,dict) or set(body)!={"case_index"}: raise ValueError("Expected case_index")
                return self.send(self.server.app.at_rest_control(match[1],body["case_index"]))
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
