"""Local chat -> bounded Banjo language -> public authoring API -> native lab.

Run: python playground/server.py --port 8765
Credentials are read only on the server. Static serving is an explicit allowlist.
"""
from __future__ import annotations
from contextlib import nullcontext
import base64
import binascii
import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import logging
import json
import math
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
import threading
import time
from urllib import error, request
from urllib.parse import urlsplit
import uuid

from experiment_language import ROOT, KINDS, LIMITATIONS, SCHEMA, PLANNER_SCHEMA, lower_proposal, lower_and_admit, SYSTEM, compile_plan, validate_plan, request_blockers, admit_plan, plan_cost
import builder
import fracture_lab
import material_qa
import mechanics_qa
import physics_trials
import physics_trial_planner
import live_session
import live_inprocess
import world_chat
import world_room
import room_world
import progression  # noqa: E402  (mcp/, put on the path by room_world)
import room_store
import inventory_room
import gameplay_room
import fabrication_room
import fabrication_qa
import gameplay_capabilities
import tool_use
import placement
import access_gate
import workshop_api
import workshop_install
import world_upgrades
import world_access
import scene_chat
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
# The server's own log. live_water and remember_ground already wrote to a
# module-level `log` that did not exist, so their warnings were NameErrors.
log = logging.getLogger("banjo")

# Rooms the QA suite saved: every chat trial's finished room, as the spec a live
# world is opened from, at <run>/<case>-<trial>.spec.json. Opened by id, so a
# build the chat made can be looked at in 3D from a link: /world?qa=<id>.
QA_ROOT = ROOT / "build" / "agent-regression"
# fullmatch, and ASCII: `$` would also accept a trailing newline and `\d` any
# Unicode digit. Nothing that is not exactly this ever becomes part of a path.
QA_ID = re.compile(r"\d{8}-\d{6}/[a-z0-9-]+-\d+", re.ASCII)
QA_SPEC_BYTES = 8 * 1024 * 1024


def qa_path(qa_id):
    """Where a QA trial's room is saved, for an id that is exactly one; else ValueError."""
    if not isinstance(qa_id, str) or not QA_ID.fullmatch(qa_id):
        raise ValueError(f"{str(qa_id)[:80]!r} is not a QA build: a QA build is named "
                         "<run>/<case>-<trial>, like 20260912-101201/hinged-gate-1")
    folder = QA_ROOT.resolve()
    path = (folder / f"{qa_id}.spec.json").resolve()
    # The pattern already rules out anything that could leave the folder. Checked
    # again on the resolved path, because this is the one place a request names a file.
    if folder not in path.parents:
        raise ValueError(f"{qa_id!r} is not a QA build")
    return path


def qa_spec(qa_id):
    """The room a QA trial saved, by its id; FileNotFoundError when there is none."""
    path = qa_path(qa_id)
    if not path.is_file():
        raise FileNotFoundError(f"there is no saved QA build {qa_id}: "
                                f"build/agent-regression/{qa_id}.spec.json does not exist")
    if path.stat().st_size > QA_SPEC_BYTES:
        raise ValueError(f"QA build {qa_id} is larger than a room can be")
    spec = strict_json(path.read_text(encoding="utf-8"))
    if not isinstance(spec, dict) or not isinstance(spec.get("bodies"), list):
        raise ValueError(f"QA build {qa_id} is not a room: it has no list of bodies")
    return spec


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

def _environment_files():
    """Where to look for OPENAI_API_KEY, nearest first.

    An agent worktree is a separate directory and `.env` is untracked, so a
    worktree never receives the key the checkout it was made from holds. The
    server then reports the key as unconfigured while the file plainly exists,
    which is confusing and sends people looking in the wrong place. A worktree's
    own `.env` still wins; this only adds the main checkout as a fallback.
    """
    candidates = [ROOT / ".env"]
    marker = ROOT / ".git"
    try:
        if marker.is_file():
            # A worktree's .git is a file holding "gitdir: <repo>/.git/worktrees/<name>".
            line = marker.read_text(encoding="utf-8").strip()
            if line.startswith("gitdir:"):
                git_dir = Path(line.split(":", 1)[1].strip())
                for parent in [git_dir, *git_dir.parents]:
                    if parent.name == ".git":
                        candidates.append(parent.parent / ".env")
                        break
    except OSError:
        pass
    return candidates


def local_configuration():
    values = {}
    for path in _environment_files():
        if not path.is_file(): continue
        if path.stat().st_size > 65536: raise ValueError("Local environment file exceeds size budget")
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line: continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'": value = value[1:-1]
            # First file wins, so a worktree can override the checkout it came
            # from by having its own.
            if key in ("OPENAI_API_KEY", "OPENAI_MODEL") and key not in values: values[key] = value
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

# Owner's rule, 2026-09-07: no job may take more than 10% longer than the
# simulated duration of the whole interaction, through to rest. Enforced before
# a job exists, so a 90-minute scene is refused rather than announced.
REALTIME_LIMIT = 1.1

def realtime_refusal(estimated_wall_s, simulated_s, duration_s):
    """None if the run fits the rule; otherwise the refusal text with a fix.

    The fix is the longest duration that would pass at this scene's cost rate,
    because duration is the one lever that costs nothing to see: an impact is
    over in milliseconds and the rest of a long window is aftermath.
    """
    if not simulated_s or simulated_s <= 0:
        return None
    ratio = estimated_wall_s / simulated_s
    if ratio <= REALTIME_LIMIT:
        return None
    longest = duration_s * REALTIME_LIMIT / ratio
    return (f"Refused: projected {ratio:,.0f}x realtime ({estimated_wall_s:,.0f} s of computing "
            f"for {simulated_s:.3g} s of simulated interaction); the limit is {REALTIME_LIMIT}x. "
            f"At this scene's cost the longest run that passes is {longest:.4g} s, "
            f"and cost falls roughly as the fourth power of cell size, so coarser cells "
            f"buy far more than a shorter window. No substitute scene was run.")

class Playground:
    def __init__(self, engine_path, studio_path, runs_path, *, planner=request_plan):
        self.engine_path, self.studio_path = Path(engine_path).resolve(), Path(studio_path).resolve()
        self.engine = EngineCLI(self.engine_path, timeout_s=75)
        self.runs_path = Path(runs_path).resolve()
        self.api_key, self.model = local_configuration()
        self.planner = planner
        self.csrf_token = secrets.token_urlsafe(32)
        self.jobs, self.requests, self.paths, self.playbacks = {}, {}, {}, {}
        # The one open live world. A recording is a file the panel can replay at
        # will; a live world is a running physics engine with a scene resident
        # in it, so there is one at a time and opening another closes the first.
        self.live = live_session.Live()
        # Which page opened it: "world" (the room on /world, and the chat
        # opening it again) or "lab" (the lab page's stage), for /api/status.
        self.live_holder = None
        # The room on /world, held as the set of objects it was authored with
        # rather than as whatever the engine last reported. Those are different
        # things once something has broken: rebuilding a room out of two
        # hundred shards is not what anyone means by "add a ball to it".
        self.room = world_room.Room("world")
        self.lock = threading.RLock()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="banjo-playground")
        self.studios = []
        self.reviewing = set()
        # The person's notebook (journal_of), and what hears every reply of their
        # live room for it (hear): docs/knowledge-and-progression.md. And
        # whoever else listens for a while (heard): a tool's use, for the
        # ground-work record the engine sends over in exactly one reply
        # (tool_use.run).
        self.journal = None
        self.reply_listeners = []
        self.on_live_reply = lambda session, reply: heard(self, session, reply)

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
            # Whether the one live world is the world page's room. Opening
            # another closes it, so the lab page does not take it over by
            # itself when it loads while this is true (app.js).
            "world_room_open": self.live.session is not None and self.live_holder == "world",
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
        refusal = realtime_refusal(admission["cost"]["estimated_wall_s"],
                                   admission["cost"].get("simulated_s") or steps * package.get("fixed_dt_s", 0),
                                   steps * package.get("fixed_dt_s", 0))
        if refusal:
            raise Inadmissible(refusal, limit="realtime")
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
            case["wall_s"] = round(time.perf_counter() - started, 3)
            # The estimate is only worth showing if it is checked against the
            # thing it predicted, so record both next to each other.
            if estimate:
                simulated = estimate.get("simulated_s") or steps * package.get("fixed_dt_s", 0)
                case["cost"] = {**estimate, "measured_wall_s": case["wall_s"],
                                "simulated_s": simulated,
                                "realtime_ratio": case["wall_s"] / simulated if simulated else None,
                                "realtime_limit": REALTIME_LIMIT,
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
            case["wall_s"] = round(time.perf_counter() - started, 3)
            self.update(job_id, status="error", error=str(exc)[:300], cases=[case], message=str(exc)[:300])
        (directory / "job.json").write_text(json.dumps(self.get(job_id), indent=2, allow_nan=False),
                                            encoding="utf-8")

    def update(self, job_id, **fields):
        with self.lock: self.jobs[job_id].update(fields)
        if "status" in fields: self.log_event(job_id,"state",status=fields["status"],message=fields.get("message",""))

    # The lab's recorded runs on disk, newest first: what the world page's
    # workbench lists, to play one back on a bench in the room (workbench.js).
    # A run is a case of a job -- a folder named by its id -- that recorded
    # bodies moving; the live rooms' folders beside them are not runs. Nothing is
    # registered here -- GET /api/jobs/<id> does that when one is chosen -- and
    # only the newest `limit` job files are read.
    def runs(self, limit=40):
        try:
            folders=[entry for entry in self.runs_path.iterdir()
                     if re.fullmatch(r"[0-9a-f]{32}",entry.name) and entry.is_dir() and not entry.is_symlink()]
        except FileNotFoundError: return {"runs":[]}
        stamped=[]
        for folder in folders:
            try: stamped.append(((folder/"job.json").stat().st_mtime,folder))
            except OSError: continue
        runs=[]
        for stamp,folder in sorted(stamped,key=lambda pair:pair[0],reverse=True):
            if len(runs)>=limit: break
            path=folder/"job.json"
            try:
                if path.is_symlink() or path.stat().st_size>16*1024*1024: continue
                saved=strict_json(path.read_text(encoding="utf-8"))
                cases=saved.get("cases")
                # The other kinds of experiment record heat, pressure or one
                # material's response, not bodies moving: nothing to set out.
                experiment=(saved.get("plan") or {}).get("experiment")
                if (saved.get("id")!=folder.name or saved.get("status") not in ("complete","blocked","error")
                        or not isinstance(cases,list) or not 1<=len(cases)<=4
                        or experiment in ("continuum_pressure_reference","dynamic_material_impact","thermal_material_experiment")):
                    continue
            except (OSError,ValueError,AttributeError,TypeError): continue
            # Each case the job recorded is a run of its own: a comparison of
            # three materials is three runs to set out.
            for index,case in enumerate(cases):
                recording=folder/f"playback-{index:02d}.json"
                try:
                    if (not isinstance(case,dict) or not case.get("playback_available")
                            or not recording.is_file() or recording.is_symlink()): continue
                    size=recording.stat().st_size
                except OSError: continue
                if size>64*1024*1024 or len(runs)>=limit: continue
                runs.append({"id":folder.name,"case":index,"title":str(case.get("name") or "a recorded run")[:240],
                             "message":str(saved.get("message") or "")[:400],"status":saved["status"],
                             "saved_unix_s":stamp,"recording_bytes":size})
        return {"runs":runs}

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
                # Every case is its own interaction and they run one after
                # another, so the budget is the sum of their simulated windows.
                refusal = realtime_refusal(cost["estimated_wall_s"],
                                           plan["duration_s"] * len(packages), plan["duration_s"])
                if refusal:
                    self.log_event(job_id, "realtime_refused", estimated_wall_s=cost["estimated_wall_s"],
                                   simulated_s=plan["duration_s"] * len(packages))
                    self.update(job_id, status="blocked", message="Request not executed: " + refusal)
                    (directory/"job.json").write_text(json.dumps(self.get(job_id),indent=2,allow_nan=False),encoding="utf-8")
                    return
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

    def trace(self,body):
        """What the room saw, from the room.

        Every lag in this engine so far has been invisible from this side: the
        world clock stopping while the wall clock ran, and the pieces of a
        broken pane arriving most of a second after the impact, both while
        every server-side number looked perfect. Only the page can see its own
        frames, so the page sends them here and they go in the log.

        The report is written by the browser, so it is treated as numbers to
        record rather than anything to act on, and it is capped.
        """
        if not isinstance(body,dict): raise ValueError("a frame report must be an object")
        raw=json.dumps(body,separators=(",",":"))
        if len(raw)>64*1024: raise ValueError("that frame report is too big")
        stamp=time.strftime("%Y-%m-%dT%H:%M:%S",time.gmtime())
        line=trace_line(body)
        # Said out loud when somebody pressed L, when the room was visibly not
        # keeping up, or when it lost the server for a moment. Otherwise it is
        # on the file and not in the way.
        why=str(body.get("why","routine"))[:60]
        # Only a report from a room that was actually being drawn says anything
        # about how the room looked.
        watched=bool(body.get("frames")) and body.get("watched") is not False
        # And only a clock that ran forward says the room fell behind. One that
        # went back is two worlds in one report (see clock_went_back), not a
        # room running at less than nothing.
        behind=(watched and not clock_went_back(body)
                and isinstance(body.get("realtime_pct"),(int,float)) and body["realtime_pct"]<90)
        worst=((body.get("frame_ms") or {}).get("worst") or 0) if watched else 0
        if why!="routine" or behind or body.get("lost_link") or (isinstance(worst,(int,float)) and worst>100):
            logging.info("banjo room (%s): %s",why,line)
        else:
            logging.debug("banjo room: %s",line)
        try:
            self.runs_path.mkdir(parents=True,exist_ok=True)
            with (self.runs_path/"room-frames.jsonl").open("a",encoding="utf-8") as out:
                out.write(json.dumps({"at":stamp,**body},separators=(",",":"))+"\n")
        except OSError:
            pass    # a report that cannot be filed is not worth failing a request over
        return {"ok":True}

    def capture(self, body):
        """Write a viewer frame to disk and return where it went.

        The image is produced by the viewer's own renderer, so what is written
        is the rendering the owner is looking at rather than a redraw by some
        other code path.
        """
        if not isinstance(body, dict) or set(body) - {"job_id","case_index","frame","data_url","label"}:
            raise ValueError("Expected job_id, case_index, frame, data_url and an optional label")
        job_id = body.get("job_id","")
        if not re.fullmatch(r"[0-9a-f]{32}", str(job_id)): raise ValueError("Invalid job identity")
        case_index = body.get("case_index",0)
        if type(case_index) is not int or not 0 <= case_index <= 15: raise ValueError("case_index must be 0..15")
        frame = body.get("frame",0)
        if type(frame) is not int or not 0 <= frame <= 100000: raise ValueError("frame must be 0..100000")
        label = str(body.get("label",""))[:60]
        if label and not re.fullmatch(r"[A-Za-z0-9 _.-]*", label): raise ValueError("label must be plain text")
        data_url = body.get("data_url","")
        prefix = "data:image/png;base64,"
        if not isinstance(data_url,str) or not data_url.startswith(prefix):
            raise ValueError("data_url must be a base64 PNG")
        try: image = base64.b64decode(data_url[len(prefix):], validate=True)
        except (ValueError, binascii.Error) as exc: raise ValueError(f"Undecodable image: {exc}") from exc
        if not image.startswith(b"\x89PNG\r\n\x1a\n"): raise ValueError("Not a PNG")
        if len(image) > 32*1024*1024: raise ValueError("Frame exceeds 32 MB")
        directory = self.runs_path.parent / "playground-captures" / job_id
        directory.mkdir(parents=True, exist_ok=True)
        stem = f"case{case_index:02d}-frame{frame:05d}" + (f"-{label.replace(' ','_')}" if label else "")
        path = directory / f"{stem}.png"
        path.write_bytes(image)
        self.log_event(job_id, "frame_captured", case_index=case_index, frame=frame, bytes=len(image), path=str(path))
        return {"path": str(path), "bytes": len(image)}

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
    # HTTP/1.1, so the page's connections stay open between steps. Under 1.0
    # every reply closed its connection, and the room opened a new one for every
    # step, many times a second. On Windows that ran the machine out of socket
    # buffers during a long look -- net::ERR_NO_BUFFER_SPACE, "Failed to fetch"
    # -- and the room stopped with a hearth halfway to catching. Every reply
    # goes through send(), which always sets Content-Length, which is what
    # keeping a connection open needs.
    protocol_version = "HTTP/1.1"
    timeout = 5
    def log_message(self, *_): pass # No prompts, credentials or response bodies in access logs.
    def send(self, value, status=200, content_type="application/json; charset=utf-8"):
        data = json.dumps(value,allow_nan=False).encode() if isinstance(value,(dict,list)) else value
        self.send_response(status)
        self.send_header("Content-Type",content_type)
        self.send_header("Content-Length",str(len(data)))
        # Said when this is the last reply on the connection, so the other end
        # does not send its next request down one that is being closed.
        if self.close_connection: self.send_header("Connection","close")
        self.send_header("Cache-Control","no-store")
        self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("Content-Security-Policy","default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
        self.end_headers(); self.wfile.write(data)
    def trusted_host(self):
        allowed = {f"127.0.0.1:{self.server.server_port}",f"localhost:{self.server.server_port}"}
        origins = {"http://"+host for host in allowed}
        # Hosted (docs/deploy.md): the one public name it is reached by, over HTTPS.
        public = getattr(self.server.app,"public_host",None)
        if public: allowed.add(public); origins.add("https://"+public)
        if self.headers.get("Host") not in allowed: raise ValueError("Unexpected local Host header")
        origin = self.headers.get("Origin")
        if origin and origin not in origins: raise ValueError("Cross-origin requests are not permitted")
    def do_GET(self):
        try:
            self.trusted_host()
            # Behind a password nothing is served without a session (access_gate).
            if access_gate.answered(self,"GET"): return
            path=urlsplit(self.path).path
            app=self.server.app
            if path=="/api/status": return self.send(app.status())
            if path=="/api/runs": return self.send(app.runs())
            if path=="/api/knowledge": return self.send(knowledge_view(app))
            if path=="/api/goal": return self.send({"markdown":(ROOT/"docs/project-goal-2026-09-06.md").read_text(encoding="utf-8") + "\n\n" + (ROOT/"docs/rules-engine-execution-plan.md").read_text(encoding="utf-8")})
            if path=="/api/goals": return self.send(strict_json((ROOT/"docs/execution-goals.json").read_text(encoding="utf-8")))
            if path=="/api/schema": return self.send({"language":"banjo-playground-1","schema":SCHEMA,"material_validation":"experimental; no calibrated fracture claim","limits":{"network_cells":850,"objects":12,"sweep_cases":4,"duration_s":3,"dynamic_material_duration_s":.1,"dynamic_material_cases":3,"dynamic_material_step_calls_per_case":200000,"recording_bytes":64*1024*1024,**LIMITS}})
            if path=="/api/gameplay/capabilities": return self.send(gameplay_capabilities.catalog())
            if path=="/api/fabrication-qa/runs": return self.send(fabrication_qa.manager(app).list_runs())
            fabrication_match=re.fullmatch(r"/api/fabrication-qa/runs/([0-9a-f]{32})",path)
            if fabrication_match: return self.send(fabrication_qa.manager(app).status(fabrication_match[1]))
            if path=="/api/mechanics-qa": return self.send(mechanics_qa.catalog(app.engine_path))
            if path=="/api/mechanics-qa/runs": return self.send(mechanics_qa.manager(app).list_runs())
            match=re.fullmatch(r"/api/mechanics-qa/runs/([0-9a-f]{32})(?:/([a-z0-9-]+)(?:/(playback|request))?)?",path)
            if match:
                qa=mechanics_qa.manager(app)
                if not match[2]: return self.send(qa.status(match[1]))
                return self.send(qa.case(match[1],match[2],playback=match[3]=="playback",request=match[3]=="request"))
            if path=="/api/material-qa": return self.send(material_qa.catalog(app.engine_path))
            if path=="/api/material-qa/runs": return self.send(material_qa.manager(app).list_runs())
            match=re.fullmatch(r"/api/material-qa/runs/([0-9a-f]{32})(?:/([a-z0-9-]+)(?:/(playback|native))?)?",path)
            if match:
                qa=material_qa.manager(app)
                if not match[2]: return self.send(qa.status(match[1]))
                material_qa.select([match[2]])
                if match[3]=="native":
                    return self.send(material_qa.read_json(qa.folder(match[1])/match[2]/"native-report.json"))
                return self.send(qa.case(match[1],match[2],playback=match[3]=="playback"))
            if path=="/api/fracture": return self.send(fracture_lab.describe(self.server.app.engine_path))
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
            allowed={"/fabrication":"fabrication.html","/fabrication.js":"fabrication.js","/fabrication.css":"fabrication.css","/mechanics-qa":"mechanics-qa.html","/mechanics-qa.js":"mechanics-qa.js","/mechanics-qa.css":"mechanics-qa.css","/qa":"material-qa.html","/material-qa.js":"material-qa.js","/material-qa.css":"material-qa.css",
                "/":"index.html","/index.html":"index.html","/app.js":"app.js","/style.css":"style.css","/scene.js":"scene.js",
                "/world":"world.html","/world.html":"world.html","/world.js":"world.js","/gameplay.js":"gameplay.js","/world.css":"world.css",
                "/workshop.js":"workshop.js","/workshop.css":"workshop.css",
                "/blades.js":"blades.js","/interaction.js":"interaction.js","/tools.js":"tools.js","/workbench.js":"workbench.js",
                "/vendor/three.module.js":"vendor/three.module.js","/vendor/three.core.js":"vendor/three.core.js"}
            if path not in allowed: return self.send({"error":"Not found"},404)
            file=STATIC/allowed[path]
            mime="text/html" if file.suffix==".html" else "text/javascript" if file.suffix==".js" else "text/css"
            self.send(file.read_bytes(),content_type=mime+"; charset=utf-8")
        except (ValueError,FileNotFoundError) as exc: self.send({"error":str(exc)},400)
    def do_POST(self):
        # The connection is kept for another request only once this one's body
        # has been read to its end. Refused before that, whatever is left of the
        # body would be read as the next request, so the connection is closed.
        keep=not self.close_connection
        self.close_connection=True
        try:
            length=int(self.headers.get("Content-Length","0"))
            capture = urlsplit(self.path).path == "/api/capture"
            # A rendered frame is a PNG data URL, far past the bound the
            # small JSON routes share, so it gets its own.
            if not 1<=length<=(48*1024*1024 if capture else 32768):
                raise ValueError("Request body exceeds bounds")
            # Consume the bounded body before rejecting headers. Closing with
            # unread POST bytes can reset the TCP connection on Windows and
            # discard the intended 400/403 response. No JSON is interpreted or
            # application action invoked until origin/session checks pass.
            raw_body=self.rfile.read(length)
            if len(raw_body)!=length: raise ValueError("Incomplete request body")
            self.close_connection=not keep
            self.trusted_host()
            # Behind a password: logging in, and nothing else without a session
            # (access_gate). Before the page's token, which the login form has not got.
            if access_gate.answered(self,"POST",raw_body): return
            if not secrets.compare_digest(self.headers.get("X-Banjo-Token",""),self.server.app.csrf_token):
                return self.send({"error":"Missing or invalid local session token"},403)
            if self.headers.get("Content-Type","").split(";")[0]!="application/json": raise ValueError("Expected application/json")
            body=strict_json(raw_body)
            path=urlsplit(self.path).path
            # Authenticate before a request can hold world access.
            return self._dispatch_POST(path,body)
        except (ValueError,UnicodeError) as exc: self.send({"error":str(exc)},400)

    def _dispatch_POST(self,path,body):
        world_call = path.startswith(("/api/world/", "/api/live/")) and not path.startswith(("/api/world/workshop/", "/api/world/fabrication/"))
        # Normal world calls share access; explicit installation is exclusive.
        # Keep ordinary requests concurrent and perform authentication first.
        with (world_access.gate(self.server.app).enter(exclusive=path in ("/api/world/open", "/api/live/open")) if world_call else nullcontext()), \
             (gameplay_room.LOCK if world_call and (gameplay_room.active(self.server.app)
                 or fabrication_room.active(self.server.app)
                 or path in ("/api/world/open", "/api/live/open")) else nullcontext()):
            if fabrication_room.active(self.server.app):
                allowed_world = {"/api/world/open", "/api/world/action", "/api/world/placement", "/api/world/inventory", "/api/world/inventory/shown"}
                if path.startswith("/api/world/") and path not in allowed_world and not path.startswith("/api/world/fabrication/"):
                    raise ValueError("The fabrication room accepts funded outputs; edit designs in Workshop")
                if not isinstance(body, dict): raise ValueError("Expected a JSON object")
                if path == "/api/live/act" and body.get("op") not in {"step","poses","wield","hand","move","release","joints","mechanics","thermo","pick","place_check"}:
                    raise ValueError("This authoring operation is not allowed in the funded room")
            if path.startswith("/api/world/fabrication/"):
                operation = path.rsplit("/",1)[-1]
                try:
                    if operation == "preview": answer = fabrication_room.preview(self.server.app,body)
                    elif operation == "commit": answer = fabrication_room.commit(self.server.app,body)
                    elif operation == "wait": answer = fabrication_room.wait(self.server.app,body)
                    else: answer = fabrication_room.request(self.server.app,operation,body)
                except OSError as exc:
                    return self.send({"error":"Fabrication save was not acknowledged. Read state before retrying: "+str(exc)},503)
                return self.send(answer)
            if gameplay_room.active(self.server.app):
                if world_call and not isinstance(body, dict):
                    raise ValueError("Expected a JSON object")
                if path.startswith("/api/world/") and path not in ("/api/world/open", "/api/world/gameplay"):
                    raise ValueError("Expedition resources use the gameplay panel; sandbox authoring belongs in other scenes")
                if path == "/api/live/act" and body.get("op") not in ("step", "poses", "environment", "terrain", "survey"):
                    raise ValueError("This operation is not part of the bounded expedition")
            if path == "/api/world/gameplay":
                try:
                    answer = gameplay_room.request(self.server.app, body, keep_world)
                except OSError as exc:
                    return self.send({"error": "Expedition action was not saved: " + str(exc)}, 503)
                return self.send(answer)
            if path=="/api/chat": return self.send(self.server.app.submit(body),202)
            if path=="/api/packages/run": return self.send(self.server.app.run_package(body),202)
            # Pure computation: admission verdict, repair and cost for a builder
            # setup. Nothing is executed, so the panel can show what a run would
            # cost before anyone commits to waiting for it.
            if path=="/api/builder/preview": return self.send(builder.describe(body))
            # The Workshop bench (docs/workshop-mode.md, docs/workshop-next.md).
            # Every one of these is pure computation over mcp/workshop.py: no
            # engine, no room, no inventory. The page renders what they return
            # and decides no geometry of its own.
            if path=="/api/workshop/open": return self.send(workshop_api.open_workshop(self.server.app,body))
            if path=="/api/workshop/candidates": return self.send(workshop_api.candidates(self.server.app,body))
            if path=="/api/workshop/more": return self.send(workshop_api.more_like_this(self.server.app,body))
            if path=="/api/workshop/plan": return self.send(workshop_api.plan(self.server.app,body))
            if path=="/api/workshop/feedback": return self.send(workshop_api.remember(self.server.app,body))
            if path=="/api/workshop/remembered": return self.send(workshop_api.remembered(self.server.app,body))
            if path=="/api/workshop/library": return self.send(workshop_api.library(self.server.app,body))
            # The fracture lab runs a lane executable synchronously under its
            # timeout and registers the recording as a job, so a changed plate
            # or drop height is watchable as soon as the lane returns.
            if path=="/api/mechanics-qa/plan":
                return self.send(physics_trial_planner.propose(self.server.app,body))
            if path=="/api/fabrication-qa/run":
                return self.send(fabrication_qa.manager(self.server.app).start(body),202)
            if path=="/api/fabrication-qa/status":
                physics_trials.obj(body,{"run_id"},set(),"status")
                manager=fabrication_qa.manager(self.server.app)
                return self.send(manager.status(body["run_id"]) if "run_id" in body else manager.list_runs())
            if path=="/api/fabrication-qa/cancel":
                physics_trials.obj(body,{"run_id"},{"run_id"},"cancel")
                return self.send(fabrication_qa.manager(self.server.app).cancel(body["run_id"]))
            if path=="/api/mechanics-qa/validate":
                physics_trials.obj(body, {"document"}, {"document"}, "validate")
                document,_=physics_trials.validate(body["document"])
                return self.send({"valid":True,"document":document})
            if path=="/api/mechanics-qa/run":
                return self.send(mechanics_qa.manager(self.server.app).start(body),202)
            if path=="/api/mechanics-qa/cancel":
                physics_trials.obj(body, {"run_id"}, {"run_id"}, "cancel")
                return self.send(mechanics_qa.manager(self.server.app).cancel(body["run_id"]))
            if path=="/api/material-qa/run":
                return self.send(material_qa.manager(self.server.app).start(body),202)
            if path=="/api/material-qa/cancel":
                if not isinstance(body,dict) or set(body)!={"run_id"}:
                    raise ValueError("QA cancel requires only run_id")
                return self.send(material_qa.manager(self.server.app).cancel(body["run_id"]))
            if path=="/api/fracture/run": return self.send(fracture_lab.run(self.server.app,body))
            # Words in, a validated scene spec out. The model fills the same
            # fields the manual controls do and nothing skips fracture_lab.validate.
            if path=="/api/scene/chat": return self.send(scene_chat.plan(self.server.app,body))
            # A live world, instead of a recording. /open starts one from a
            # validated scene; /act steps it, takes hold of an object, moves it,
            # lets go, or puts something back into the lattice to be broken.
            if path.startswith("/api/world/workshop/"):
                operations = {"/api/world/workshop/context": workshop_install.context,
                              "/api/world/workshop/preview": workshop_install.preview,
                              "/api/world/workshop/commit": workshop_install.commit}
                if path in operations:
                    try:
                        answer = operations[path](self.server.app,body)
                    except OSError as exc:
                        return self.send({"error": "Installation could not be saved; the original world is unchanged: " + str(exc)}, 503)
                    return self.send(answer)
            if path=="/api/world/open":
                app=self.server.app
                # Which room. The bench is the materials room this playground
                # opened with; the courtyard is the one with things that swing.
                # Each room is kept, with whatever the chat has built in it.
                # Opening a room used to author it from scratch every time, so
                # "Start the room again" -- or a page reload, or switching away
                # and back -- threw away a castle gate the chat had just built.
                # Starting again now replays the room as it was last authored,
                # and the chat's changes ARE authoring; asking the chat to clear
                # it is how to get the original back.
                if not isinstance(body,dict): raise ValueError("Expected a JSON object")
                rooms=getattr(app,"rooms",None)
                if rooms is None: rooms=app.rooms={}
                # Or a room a QA trial saved, by its id: {"qa": "<run>/<case>-<trial>"}.
                # Kept like the others, under "qa:<id>", so a reload opens it as
                # the chat has left it since; "fresh" reads the saved file again.
                # Nothing is kept, and the room already open is left alone,
                # unless the new world actually opens.
                if "qa" in body:
                    if (gameplay_room.active(app) or fabrication_room.active(app)) and not keep_world(app, "opening QA room"):
                        raise ValueError("Save the expedition before opening the QA room")
                    qa=body["qa"]
                    qa_path(qa)   # anything that is not exactly an id stops here
                    key="qa:"+qa
                    room=None if body.get("fresh") else rooms.get(key)
                    if room is None:
                        try: spec=qa_spec(qa)
                        except FileNotFoundError as missing: return self.send({"error":str(missing)},404)
                        room=world_room.Room("yard")
                        room.scene,room.spec=key,spec
                    opened=app.live.open(app,{"spec":room.spec})
                    app.live_holder="world"
                    rooms[key]=app.room=room
                    opened["inventory"]=inventory_room.after_open(app,opened)
                    opened["scene"]=key
                    opened["scenes"]=sorted(world_room.SCENES)
                    return self.send(opened)
                switching_room = (getattr(app, "live_holder", None) == "world" and
                    app.live.session is not None and getattr(getattr(app,"room",None),"scene",None) != str(body.get("scene","world")))
                if gameplay_room.active(app) or fabrication_room.active(app) or switching_room:
                    if not keep_world(app, "leaving a room or reopening a funded room"):
                        raise ValueError("The current room could not be saved; finish its pending physics before leaving")
                scene=str(body.get("scene","world"))
                if scene in ("expedition", "fabrication"):
                    if body.get("fresh"):
                        raise ValueError("This room is persistent; fresh would erase its material history")
                    body.pop("again", None)
                if scene not in world_room.SCENES: scene="world"
                # Kept on disk as well (room_store): a room this server has not
                # opened since it started is read back as it was left, so a
                # restart -- the sims are restarted whenever work lands -- keeps
                # what anyone built. Fresh is the room as first made, kept as
                # that once it has opened, so a fresh room that will not open
                # never costs the one that was kept.
                # A page opening the room that is running here already -- a
                # reload, or the same room in a second tab -- joins it as it
                # stands, rather than putting it back as it was authored. The
                # page's "Start the room again" says `again`: that one opens it
                # again from what it is held as, which is the way out of a room
                # that has stopped.
                if not body.get("fresh") and not body.get("again"):
                    rejoined=_rejoin(app,scene)
                    if rejoined is not None: return self.send(rejoined)
                room,kept=room_store.room_for(app,scene,rooms.get(scene),bool(body.get("fresh")))
                rooms[scene]=app.room=room
                # The running world as this server last saved it (keep_world),
                # for a room read back from disk or revisited in this process:
                # open it as it stood. Explicit again/fresh still restart an
                # authoring room. Only use a world saved from its current spec:
                # chat's changes are a new spec, and a world saved before them is
                # not the room they made.
                carry_kept = kept or scene in ("expedition","fabrication") or not (body.get("again") or body.get("fresh"))
                world=getattr(room,"world_record",None) if carry_kept else None
                if not carry_kept: room.world_record=None
                if world is not None and world.get("spec_digest")!=live_session.spec_digest(room.spec):
                    log.info("rooms: the world kept with %s was saved from another spec; the room opens from its spec",
                             scene)
                    if scene in ("expedition","fabrication"):
                        raise ValueError("Funded room spec changed; refusing to reset its clock or inventories")
                    room.world_record=world=None
                world_problem=None
                try:
                    try:
                        opened=app.live.open(app,{"spec":room.spec,**({"snapshot":world} if world else {})})
                    except Exception as failed:
                        if world is None or scene in ("expedition","fabrication"): raise
                        # A saved world the engine would not open at all: set
                        # aside, never deleted, and the room opens from its spec.
                        world_problem=str(failed)[:300]
                        app.store.set_aside_world(room,world_problem)
                        world=None
                        opened=app.live.open(app,{"spec":room.spec})
                except Exception as problem:
                    if not kept or scene in ("expedition","fabrication"): raise
                    # A kept room that no longer opens -- kept by an older build,
                    # say -- is set aside, never deleted, and the room opens as
                    # it was first made.
                    app.store.set_aside(scene,str(problem)[:300])
                    room,kept=world_room.Room(scene),False
                    rooms[scene]=app.room=room
                    opened=app.live.open(app,{"spec":room.spec})
                    opened["kept_problem"]=(f"the room kept from before would not open "
                                            f"({str(problem)[:200]}); it was set aside and the "
                                            f"room opened as first made")
                # Opened, but not as it stood: the engine said why (its
                # `restored`). Set aside with that, and said.
                restored=opened.get("restored") if world is not None else None
                if scene in ("expedition","fabrication") and world is not None and (
                        not isinstance(restored, dict) or restored.get("tier") != "whole"):
                    raise ValueError("A complete native restore is required for this funded room")
                if isinstance(restored,dict) and restored.get("tier")!="whole":
                    if scene == "expedition":
                        raise ValueError("A complete native restore is required for an expedition")
                    world_problem=str(restored.get("why") or "the engine could not put it back")[:300]
                    app.store.set_aside_world(room,world_problem)
                if world_problem:
                    placed=(int(restored.get("bodies") or 0)
                            if isinstance(restored,dict) and restored.get("tier")=="poses" else 0)
                    opened["kept_problem"]=("the room as it stood when the server stopped could not be put back ("
                                            +world_problem+"); it was set aside and the room opened from what it "
                                            "is held as"+(f", with {placed} whole things put back where they "
                                                          "were left" if placed else ""))
                app.live_holder="world"
                # What the person has is put back where the record says: the
                # bag's things are set aside again (inventory_room.after_open).
                opened["inventory"]=inventory_room.after_open(app,opened)
                if body.get("fresh"): room_store.keep(app,room)
                opened=world_upgrades.apply(app,opened)
                # Saved now, so what a restart gives back is this world from
                # here on -- the one just opened again, or the one just opened
                # from its spec, which a restart must not trade for an older one.
                gameplay_room.opened(app, opened)
                saved_now = keep_world(app,"the room opened")
                if (gameplay_room.active(app) or fabrication_room.active(app)) and not saved_now:
                    raise ValueError("The funded room could not be saved")
                opened["scene"]=app.room.scene
                opened["scenes"]=sorted(world_room.SCENES)
                opened["kept"]=kept
                if kept: opened["kept_since_unix_s"]=getattr(room,"kept_since",None)
                # The conversation so far in this room, so the page shows it again
                # rather than a blank panel beside a room the chat has built in.
                opened["chat"]=room.chat[-20:]
                return self.send(opened)
            if path=="/api/world/ask":
                app=self.server.app
                _this_pages_room(app,body)
                session=app.live.session
                message=str(body.get("message",""))[:2000]
                trace=[]
                from time import perf_counter as _now
                began=_now()
                # The ground the room stands on now, and the water on it: the
                # chat builds in a copy of the room as it IS -- the pond as low
                # as a channel has let it fall -- and the room opened again
                # afterwards on the same ground keeps the same water.
                ground_was=json.dumps((app.room.spec.get("terrain") or {}).get("generate"),sort_keys=True)
                # Where the person is standing and what they are looking at, so
                # "near me" and "over there" mean somewhere. Checked, since it
                # arrives over HTTP, and kept with the turn's log.
                person=world_chat.where_the_person_is(body.get("person"))
                # The conversation so far in this room goes with the request, so
                # "confirmed" answers what the room asked; this turn is kept for
                # the next, failed or not.
                room=app.room
                try:
                    answer=world_chat.ask(app.api_key,app.model,room,session.state,message,
                                          [str(s)[:200] for s in (body.get("story") or [])][-24:],
                                          trace=trace,water_state=live_water(session,room.spec),
                                          person=person,history=room.chat,journal=journal_of(app),
                                          # Working what is in the room -- a thing's action
                                          # pressed, a motor told -- happens to the room as
                                          # it stands.
                                          live=lambda name,args:_chat_live(app,name,args,body.get("person")))
                except Exception as failure:
                    world_chat.remember_turn(room.chat,message,None,failure=str(failure)[:300])
                    room_store.keep(app,room)
                    remember_chat(app,message,trace,None,failure,_now()-began,person)
                    raise
                world_chat.remember_turn(room.chat,message,answer)
                # What the chat built is in room.spec now (export_spec) and the
                # turn is in room.chat: both are kept, so a restart has them.
                room_store.keep(app,room)
                remember_chat(app,message,trace,answer,None,_now()-began,person)
                # What the chat worked on the room after changing it, held back
                # until the change is in it (world_chat.HELD_BACK).
                held=answer.pop("deferred",None) or []
                if answer.pop("changed",False):
                    if app.room.bodies():
                        # Objects cannot be added to or taken out of a running
                        # world: a world is opened from a scene and that is the
                        # set of bodies it has. So a change means opening the
                        # room again from what it has become -- carrying the
                        # world that was running into it (world_to_carry), so
                        # that everything the change did not touch is as it
                        # stood. What did not come back as it was is said, thing
                        # by thing, in the opening's `restored`.
                        spec=with_water(session,app.room.spec,ground_was)
                        saved,_=world_to_carry(app,session)
                        opened=app.live.open(app,{"spec":spec,**({"snapshot":saved,"carry":True} if saved else {})})
                        app.live_holder="world"
                        opened["inventory"]=inventory_room.after_open(app,opened)
                        # The world the chat's room is now, kept with it.
                        keep_world(app,"the chat changed the room")
                        answer["reopened"]=True
                        answer["session"]=opened["session"]
                        answer["state"]=opened
                        # Joints that would not hang are said, not dropped: a
                        # gate that does not swing reads as broken physics.
                        if opened.get("joint_problems"):
                            answer["joint_problems"]=opened["joint_problems"]
                        # Now it is: done on the room with the change in it.
                        then=[]
                        for call in held:
                            try: done=_chat_live(app,call["name"],call["args"],body.get("person"))
                            except Exception as failure: done={"error":str(failure)[:300]}
                            then.append({"name":call["name"],**done})
                        if then: answer["then"]=then
                    else:
                        # Nothing left to open, and a world needs at least one
                        # body. The running one stays up rather than being
                        # replaced by nothing, and the reply says so instead of
                        # the page quietly showing a room nobody is describing.
                        answer["reply"]=(answer.get("reply","")
                                         +" The room is empty now, so what is still on"
                                         " screen is the last one. Ask for something to"
                                         " be added and it will be built.").strip()
                return self.send(answer)
            if path=="/api/world/placement":
                _this_pages_room(self.server.app,body)
                return self.send(placement.resolve(self.server.app,body))
            if path=="/api/world/action":
                # One of a thing's actions (offer_actions), run step by step --
                # no model is asked: the room's chat wrote the program when it
                # made the thing. See run_action. Only on the room the page
                # has open (_this_pages_room).
                _this_pages_room(self.server.app,body)
                return self.send(run_action(self.server.app,body))
            if path=="/api/world/machine":
                # A machine worked from its panel (operate_machine): power, a
                # direction, a drive setting, by the page's own count, straight
                # to its controller. Only on the room the page has open.
                _this_pages_room(self.server.app,body)
                return self.send(operate_machine(self.server.app,body))
            if path=="/api/world/tool":
                # What the tool in the person's hand does where they look
                # (tool_use.resolve): its action, whether it can be done there
                # and why not, and the ring the page draws. Asking does nothing.
                _this_pages_room(self.server.app,body)
                return self.send(tool_use.resolve(self.server.app,body))
            if path=="/api/world/tool/use":
                # And doing it: the whole of it, with the bounded hand, while
                # the page keeps the room running (tool_use.run). The swing is
                # the person's, so what it does is credited to their notebook.
                _this_pages_room(self.server.app,body)
                return self.send(tool_use.run(self.server.app,body,note=note_strike))
            if path=="/api/world/inventory":
                # One change to what the person has (inventory_room.request):
                # taken into the bag, held, stowed or put down -- done once
                # however often it is asked, only on the room the page has
                # open, and kept with the room when it is done.
                app=self.server.app
                _this_pages_room(app,body)
                answer=inventory_room.request(app,body)
                # Kept with the world as it now stands -- the thing in the hand
                # or in the bag in the engine as the record says -- or, with a
                # world that will not be saved just now, on its own.
                if answer.get("ok") and not keep_world(app,"what the person has changed"):
                    room_store.keep(app,app.room)
                return self.send(answer)
            if path=="/api/world/inventory/shown":
                # And what the person has now, as the page shows it.
                _this_pages_room(self.server.app,body)
                return self.send(inventory_room.shown(self.server.app))
            if path=="/api/live/open":
                if (gameplay_room.active(self.server.app) or fabrication_room.active(self.server.app)) and not keep_world(self.server.app, "opening laboratory"):
                    raise ValueError("Save the expedition before opening the laboratory")
                opened=self.server.app.live.open(self.server.app,body)
                # The lab page's stage now: the world page's room was closed by it.
                self.server.app.live_holder="lab"
                return self.send(opened)
            if path=="/api/live/act":
                # The notebook revision the page has shown: the answer carries
                # the notebook when the server's is newer (with_notebook).
                seen=body.pop("notebook_seen",None) if isinstance(body,dict) else None
                answer=self.server.app.live.act(body)
                gameplay_room.sync(self.server.app, answer)
                fabrication_room.sync(self.server.app, answer)
                remember_ground(self.server.app,body,answer)
                if isinstance(body,dict) and body.get("op")=="strike": note_strike(self.server.app,answer)
                self.send(with_notebook(self.server.app,answer,seen))
                # After the page has its answer: the running world kept with
                # the room when a break is done, and every few seconds of it.
                keep_world_after(self.server.app,body,answer)
                return
            # Save the frame the 3D viewer is showing. The page cannot write
            # a file and cannot reach any other origin, so the one way a
            # result leaves the tab it was rendered in is through here.
            if path=="/api/capture": return self.send(self.server.app.capture(body))
            if path=="/api/trace": return self.send(self.server.app.trace(body))
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

def clock_went_back(report):
    """Whether the world's clock ran backwards inside one frame report.

    A world's clock only runs forward. Less than nothing means the report
    spanned two worlds: "Start the room again", or the chat rebuilding the room,
    put in a new world whose clock started nearer zero, and a page that kept its
    old baseline took the old world's clock from the new one's. That measures
    neither world, and printed as a percentage it reads as a measurement:
    "room: -358% of realtime". The seconds are checked as well as the
    percentage, because a little less than nothing rounds to 0% -- the figure
    that means the clock stopped.
    """
    return any(isinstance(report.get(key),(int,float)) and report.get(key)<0
               for key in ("world_s","realtime_pct"))


def trace_line(report):
    """One readable line for the log, out of a frame report from the room.

    Three numbers, because each of them has caught a lag that the other two
    missed. How much of the scene's clock went by against how much real time
    (a world that has stopped reads 0% while everything else looks perfect).
    The worst frame (what the eye sees). And how long a break took from the
    contact to the pieces, which is the one a person actually complains about
    and the one no server-side measurement can see at all.
    """
    frame=report.get("frame_ms") or {}
    clocks=("the world was replaced during this report" if clock_went_back(report)
            else f"{report.get('realtime_pct')}% of realtime")
    parts=[f"room: {clocks}",
           f"{report.get('fps')} fps",
           f"worst frame {frame.get('worst')} ms",
           f"{report.get('objects')} objects"]
    # Ahead of the clocks, because it is what they mean: nothing steps the world
    # while the server cannot be reached, and a room that was out of reach for
    # a second reads in every other number as a room running slow.
    lost=report.get("lost_link")
    if isinstance(lost,dict) and lost.get("times"):
        parts.insert(0,f"LOST THE SERVER {lost.get('times')}x, longest {lost.get('longest_ms')} ms"
                       + (", and GAVE UP" if lost.get("gave_up") else "")
                       + (f" ({str(lost.get('why'))[:80]})" if lost.get("why") else ""))
    # Said first, because it changes what every other number means.
    #
    # Nothing drawn at all is the honest test. `document.hidden` is the obvious
    # one and it is not enough: a pane can be off screen in a way that stops the
    # drawing without ever setting it, which reads as a catastrophic lag and is
    # nothing of the kind. It cost this project two wrong diagnoses.
    if not report.get("frames"):
        parts.insert(0,"NOTHING WAS DRAWN (not on screen, or the tab was throttled "
                       "-- the frame numbers below mean nothing)")
    elif report.get("watched") is False:
        parts.insert(0,"NOT ON SCREEN")
    breaks=report.get("breaks") or []
    for one in breaks:
        gap=one.get("impact_to_pieces_ms")
        parts.append(f"{one.get('name')} {one.get('outcome')} into {one.get('pieces')}"
                     + (f" {gap} ms after the impact" if gap is not None else ""))
    slow=report.get("slow_frames") or []
    if slow:
        worst=max(slow,key=lambda s:s.get("ms",0))
        parts.append(f"{len(slow)} slow frames, worst {worst.get('ms')} ms while "
                     f"{worst.get('doing')}")
    return "  ".join(str(p) for p in parts)


def remember_chat(app, message, trace, answer, failure, wall_s, person=None):
    """A chat turn, in the log and on disk.

    A request that "did not make it" used to leave nothing behind: the model's
    calls and the refusals it got back existed for one round trip and were
    gone, so there was no way to say afterwards which of a dozen calls was
    refused, or what for. Now every turn is one line in the log and one file
    under build/playground-logs/chat/, with every call and every answer.
    """
    log = logging.getLogger("banjo")
    calls = [c for r in trace for c in r.get("calls", [])]
    refused = [c for c in calls
               if isinstance(c.get("answer"), dict) and "error" in c["answer"]]
    if failure is not None:
        log.warning("chat: %r failed after %d rounds and %d calls: %s",
                    message[:120], len(trace), len(calls), failure)
    else:
        usage = answer.get("usage") or {}
        log.info("chat: %r -> %d rounds, %d calls, %d refused, %s changed, %s in / %s out "
                 "tokens, %.1f s", message[:120], answer.get("rounds", len(trace)),
                 len(calls), len(refused), "room" if answer.get("changed") else "nothing",
                 usage.get("input_tokens"), usage.get("output_tokens"), wall_s)
    for call in refused[:8]:
        log.info("chat refused %s: %s", call.get("name"),
                 str(call["answer"].get("error"))[:240])
    try:
        folder = ROOT / "build" / "playground-logs" / "chat"
        folder.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        record = {"message": message, "wall_s": round(wall_s, 2),
                  "failure": str(failure) if failure is not None else None,
                  "reply": (answer or {}).get("reply"), "did": (answer or {}).get("did"),
                  "usage": (answer or {}).get("usage"),
                  "tool_transport": (answer or {}).get("tool_transport"),
                  "the_person": (answer or {}).get("the_person") or person,
                  "rounds": trace}
        text = json.dumps(record, indent=1, default=str)
        if app.api_key:
            text = text.replace(app.api_key, "[redacted]")
        (folder / f"{stamp}-{abs(hash(message)) % 10000:04d}.json").write_text(
            text, encoding="utf-8")
    except OSError as problem:
        log.warning("chat: could not keep the transcript: %s", problem)


def live_water(session,spec):
    """The water in the running room, for the next world opened on the same
    ground: the chat's copy, or the room opened again after the chat. None
    when the room has no ground or its water cannot be read."""
    if not isinstance(spec,dict) or not spec.get("terrain") or session is None: return None
    try:
        state=session.send(op="environment_state").get("state")
    except Exception as problem:
        log.warning("water: could not read the running room's water: %s",problem)
        return None
    return state if isinstance(state,dict) and state.get("depth_b64") else None


def with_water(session,spec,ground_was):
    """The room's spec with the running room's water in it, when the world is
    about to open on the ground that water stands on -- a new valley is new
    water. Handed to the world being opened and never kept in the room: what
    the room IS is its ground and what stands on it."""
    if json.dumps((spec.get("terrain") or {}).get("generate"),sort_keys=True)!=ground_was: return spec
    state=live_water(session,spec)
    if state is None: return spec
    return dict(spec,water=dict(spec.get("water") or {},state=state))


# How long a chat change or a stand step waits for the running world to be one
# a saved world can carry -- a break being worked out, a stroke of the hand, an
# edge in a cut -- before it carries the one kept last (keep_world). The page
# steps the world meanwhile, and each of those is over in well under a second
# of its time.
CARRY_WAIT_S=2.0


def world_to_carry(app,session):
    """The room's running world as it stands, saved, for opening the room again
    from a spec the chat or an action has just changed with everything the
    change did not touch carried into it (Live.open with `carry`): what was
    moved, what broke and how, dents, a gate swung open, a hoist's crate wound
    up and its battery's charge, what the hand holds, heat. Opened again from
    the spec alone, every one of those went back as it was authored.

    `session` is the world the change was asked of; one opened since, by another
    page, is not this room's to carry. While something is under way that a
    saved world cannot carry, the world is asked again until CARRY_WAIT_S has
    gone, and then the one kept last (keep_world) is carried if it was saved
    from this world's spec. (None, why) when there is nothing to carry, and the
    room opens from its spec as it did before."""
    if session is None or app.live.session is not session or getattr(app,"live_holder",None)!="world":
        return None,"the room's world is not the one running"
    snapshot=getattr(app.live,"snapshot",None)
    if snapshot is None: return None,"this live world cannot be saved"
    deadline=time.monotonic()+CARRY_WAIT_S
    while True:
        saved,refused=snapshot()
        if saved is not None: return saved,""
        if time.monotonic()>=deadline: break
        time.sleep(0.1)
    kept=getattr(getattr(app,"room",None),"world_record",None)
    if isinstance(kept,dict) and kept.get("spec_digest")==getattr(session,"spec_digest",None):
        log.info("rooms: the running world would not be saved (%s); the one kept at %.1f s is carried",
                 refused,float(kept.get("t_s") or 0.0))
        return kept,refused
    log.info("rooms: the running world would not be saved (%s), and none kept is its own; the room opens "
             "from its spec",refused)
    return None,refused


# How far in front of the person a stand step puts a thing it sets "in_front".
ACTION_AHEAD_M=1.2
# How long a hand's stroke may take before the action says it did not get there.
ACTION_STROKE_S=6.0
# What anything loose can have done to it without the room's chat having
# thought of it (the owner: "there is also things like place on ground that are
# missing"). Programs like the chat's, run by run_action; the page offers each
# only where the engine could do it.
BUILTIN_ACTIONS={
    "put_on_ground":{"label":"Put it on the ground in front of me","steps":[
        {"do":"take_hold"},{"do":"carry_to","to":{"kind":"in_front","in_front_m":1.0}},
        {"do":"put_down"}]},
    "stand_upright":{"label":"Stand it upright","steps":[{"do":"stand","stand":"upright"}]},
    "lay_down":{"label":"Lay it down where I'm facing","steps":[
        {"do":"stand","stand":"lying","along":"facing"}]}}


def _live_body(app,name):
    """A thing as the running room has it now: where it is, its sides, its turn."""
    body=next((b for b in (app.live.session.state or {}).get("bodies",[]) if b.get("name")==name),None)
    if body is None: raise ValueError(f"{name} is not in the room as it runs: it may have broken")
    return body


def _reach(body,direction):
    """How far a box or a ball reaches from its middle along a direction,
    turned as it is."""
    dims=[float(v) for v in body.get("dimensions_m") or [0.0,0.0,0.0]]
    if body.get("shape")=="sphere": return dims[0]/2.0
    w,x,y,z=(float(v) for v in (body.get("orientation_wxyz") or [1.0,0.0,0.0,0.0]))
    turn=[[1-2*(y*y+z*z),2*(x*y-w*z),2*(x*z+w*y)],
          [2*(x*y+w*z),1-2*(x*x+z*z),2*(y*z-w*x)],
          [2*(x*z-w*y),2*(y*z+w*x),1-2*(x*x+y*y)]]
    return sum(abs(sum(turn[r][i]*direction[r] for r in range(3)))*dims[i]/2.0 for i in range(3))


def _action_point(app,place,person,moving):
    """Where a step takes the middle of what the hand moves, in the room as it
    is now: in front of the person, on a thing, beside it on a side as the
    person sees it (near is between it and them), or at an offset from it."""
    mover=_live_body(app,moving)
    here=[float(v) for v in mover.get("position_m") or [0.0,0.0,0.0]]
    up=[0.0,1.0,0.0]
    if "in_front_m" in place:
        if person is None: raise ValueError("the page did not say where you are")
        sx,sy,sz=person["standing_m"]
        fx,_,fz=person["facing"]
        ahead=float(place["in_front_m"])
        # With no height, carried clear of the ground -- 5 cm above the height
        # it rests at now -- and put_down lowers it onto what is there. Where
        # the engine keeps a thing is its centre of mass: for a piece of
        # several parts that is not the middle of its box, and worked out from
        # the box, a joined stool was carried with its legs 9 cm in the ground
        # and the hand's stroke was blocked.
        # height_m is how far its bottom is above the ground there, as the MCP
        # says it; 0 is resting on it, and is carried clear like none. Taken as
        # its middle's height, "on the ground in front of me" (height_m 0)
        # carried a crate half into the terrace, and the stroke was blocked.
        rest=sy+_reach(mover,up)+0.02
        high=float(place.get("height_m") or 0.0)
        y=rest+high if high>0.0 else max(here[1]+0.05,rest)
        return [sx+ahead*fx,y,sz+ahead*fz]
    other=_live_body(app,place.get("on") or place.get("beside") or place.get("from"))
    at=[float(v) for v in other.get("position_m") or [0.0,0.0,0.0]]
    if "on" in place:
        return [at[0],at[1]+_reach(other,up)+_reach(mover,up)+0.02,at[2]]
    if "from" in place:
        return [at[k]+float(place["offset_m"][k]) for k in range(3)]
    if person is None: raise ValueError("the page did not say where you are")
    sx,_,sz=person["standing_m"]
    fx,_,fz=person["facing"]
    tx,tz=sx-at[0],sz-at[2]
    size=math.hypot(tx,tz)
    nx,nz=(tx/size,tz/size) if size>1e-6 else (-fx,-fz)
    side=place.get("side","near")
    if side=="far": nx,nz=-nx,-nz
    elif side=="left": nx,nz=fz,-fx
    elif side=="right": nx,nz=-fz,fx
    way=[nx,0.0,nz]
    out=_reach(other,way)+float(place.get("gap_m",0.3))+_reach(mover,way)
    return [at[0]+nx*out,max(here[1],at[1]-_reach(other,up)+_reach(mover,up))+0.02,at[2]+nz*out]


def _stroke_to(app,target,speed,start):
    """Move what the hand holds to a point with the hand's own stroke, and wait
    -- while the page keeps the room running -- for the engine to say how the
    stroke ended: reached, blocked or gave up. The force is the hand's."""
    return _stroke_along(app,[start,target],speed)


def _stroke_along(app,path,speed):
    """The same along a path of up to sixteen points: round a pin, for a turn."""
    app.live.act({"session":app.live.session.id,"op":"stroke","path":[list(p) for p in path],"speed_m_s":float(speed),
                  "accel_m_s2":2.0,"lead_m":0.05,"let_go":False,"give_up_s":ACTION_STROKE_S})
    began=time.monotonic()
    started=False
    while time.monotonic()-began<ACTION_STROKE_S+3.0:
        hand=(app.live.session.state or {}).get("hand") or {}
        if hand.get("stroking"): started=True
        elif (started or time.monotonic()-began>0.5) and hand.get("stroke_ended"):
            return str(hand["stroke_ended"])
        time.sleep(0.03)
    return "ran out of time"


def _stand(app,room,name,step,person):
    """A stand step: turn_object on the room as it is -- where the thing stands
    in the running room, or in front of the person -- and then the room opened
    again from what it has become. (None, why) when it could not stand there."""
    session=app.live.session
    args={"name":name,"stand":step["stand"]}
    along=step.get("along")
    if along in ("facing","across"):
        if person is None: raise ValueError("the page did not say which way you face")
        fx,_,fz=person["facing"]
        args["along"]=[fx,0.0,fz] if along=="facing" else [fz,0.0,-fx]
    elif along=="x": args["along"]=[1.0,0.0,0.0]
    elif along=="z": args["along"]=[0.0,0.0,1.0]
    if step.get("where")=="in_front":
        if person is None: raise ValueError("the page did not say where you are")
        sx,_,sz=person["standing_m"]
        fx,_,fz=person["facing"]
        args["at_m"]=[round(sx+ACTION_AHEAD_M*fx,3),round(sz+ACTION_AHEAD_M*fz,3)]
    else:
        at=_live_body(app,name).get("position_m") or [0.0,0.0,0.0]
        args["at_m"]=[round(float(at[0]),3),round(float(at[2]),3)]
    ground_was=json.dumps((room.spec.get("terrain") or {}).get("generate"),sort_keys=True)
    world_id=room_world.open_room(room.spec,water_state=live_water(session,room.spec))
    try:
        answer=room_world.call(world_id,"turn_object",args)
        if "error" in answer: return None,answer["error"]
        room.spec=room_world.export_spec(room_world.entry_of(world_id))
    finally:
        room_world.close_room(world_id)
    room_store.keep(app,room)
    # Opened again carrying the world that was running, so that everything else
    # in the room is as it stood (world_to_carry); the thing stood up is as the
    # room now has it.
    spec=with_water(session,room.spec,ground_was)
    saved,_=world_to_carry(app,session)
    opened=app.live.open(app,{"spec":spec,**({"snapshot":saved,"carry":True} if saved else {})})
    app.live_holder="world"
    # The bag's things open standing in the room again: set aside once more.
    opened["inventory"]=inventory_room.after_open(app,opened)
    # And the room as it now stands is what a restart gives back.
    keep_world(app,"a thing was stood up")
    return opened,f"stood {name} {answer.get('stands')} on {answer.get('on')}"


# Turning a thing on a pin, or sliding it in a groove, by hand: what the page
# offers everything on a joint, in every room, and what a chat's program asks
# for with a turn or a slide step. The owner, 2026-09-14: clicking the castle
# gate's winch gave no "Turn the winch half way", and that is to be so for all
# things, always. The hand takes hold of whatever stands off the pin furthest --
# a winch's handle, not its wheel's middle -- and carries it round the pin's
# axis with its own stroke, so how far it goes is the engine's answer to the
# hand's 800 N against all the pin turns: the gate on the winch's rope with it.
# A hinge's degrees count right-handed about the axis it reports: measured, a
# winch's handle carried 30 degrees that way read +26.6, a gate carried 20 +18.1.
TURN_STEP_DEG=12.0          # between the points of a turn's arc
TURN_SPEED_M_S=0.4          # a person working a handle round
SLIDE_SPEED_M_S=0.3
JOINT_STOPS=("all_the_way","half_way","all_the_way_back","back_to_start")
JOINT_LABELS={("turn","all_the_way"):"Turn it all the way",("turn","half_way"):"Turn it half way",
              ("turn","all_the_way_back"):"Turn it all the way back",
              ("turn","back_to_start"):"Turn it back to where it started",
              ("slide","all_the_way"):"Slide it all the way",("slide","half_way"):"Slide it half way",
              ("slide","all_the_way_back"):"Slide it all the way back",
              ("slide","back_to_start"):"Slide it back to where it started"}


def _unit(v):
    size=math.sqrt(sum(float(x)*float(x) for x in v)) or 1.0
    return [float(x)/size for x in v]


def _governing(joints,part,kind):
    """The pin ("hinge") or groove ("slider") that part turns or slides on --
    its own, or that of what it is fixed to -- and the bodies that go with it:
    part and everything fixed to it. (None, those) when there is none."""
    group,these={part},[part]
    while these:
        n=these.pop()
        for j in joints:
            if j.get("attached") and j.get("kind")=="fixing" and n in (j.get("a"),j.get("b")):
                other=j["b"] if j.get("a")==n else j["a"]
                if other not in group:
                    group.add(other)
                    these.append(other)
    for j in joints:
        if j.get("attached") and j.get("kind")==kind and (j.get("a") in group)!=(j.get("b") in group):
            return j,group
    return None,group


def _joint_target(now,lo,hi,step,whole):
    """Where a turn (degrees; whole is a full turn) or a slide (metres; whole is
    None) is asked to end: at a stop by name, or an amount from where it is --
    a hair inside the joint's own stops, which the hand would only push on."""
    stop=step.get("stop")
    span=whole or 0.0
    if stop=="all_the_way": target=float(hi) if hi is not None else now+span
    elif stop=="half_way": target=now+((float(hi)-now)/2 if hi is not None else span/2)
    elif stop=="all_the_way_back": target=float(lo) if lo is not None else now-span
    elif stop=="back_to_start": target=0.0
    else: target=now+float(step.get("degrees" if whole else "distance_m") or 0.0)
    inset=1.0 if whole else 0.01
    if lo is not None: target=max(target,float(lo)+inset)
    if hi is not None: target=min(target,float(hi)-inset)
    return target


def _goes_right_round(lo,hi):
    """A wheel: a pin with no stops, or with stops a whole turn apart -- which
    the engine reads from -180 to 180 degrees, joined half a turn round."""
    return lo is None or hi is None or float(hi)-float(lo)>=359.0


def _wrapped(degrees):
    """The same turn, from -180 to 180 degrees."""
    return degrees-360.0*math.ceil((degrees-180.0)/360.0)


def _round_target(now,step):
    """(where a wheel is, where it is asked to go). Its far stop is half a turn
    from where it started, the way its degrees count, and its near stop half a
    turn the other way -- the same place -- so at the join it is taken to be all
    the way round, and pressing "all the way" again finds it there rather than a
    whole turn off. A named stop is reached the short way; an amount of degrees
    is turned as asked, a whole turn if so."""
    if now<=-178.0: now+=360.0
    stop=step.get("stop")
    if stop=="all_the_way": target=179.0
    elif stop=="half_way": target=now+(179.0-now)/2
    elif stop=="all_the_way_back": target=-179.0
    elif stop=="back_to_start": target=0.0
    else: return now,now+float(step.get("degrees") or 0.0)
    amount=target-now
    if abs(amount)>180.5: amount=_wrapped(amount)
    return now,now+amount


def _rotated(p,axis,at,angle):
    """p turned by angle (radians, right-handed) about the line through at along axis."""
    r=[p[k]-at[k] for k in range(3)]
    c,s=math.cos(angle),math.sin(angle)
    cross=[axis[1]*r[2]-axis[2]*r[1],axis[2]*r[0]-axis[0]*r[2],axis[0]*r[1]-axis[1]*r[0]]
    along=sum(axis[k]*r[k] for k in range(3))
    return [at[k]+r[k]*c+cross[k]*s+axis[k]*along*(1-c) for k in range(3)]


def _off_axis(p,axis,at):
    r=[p[k]-at[k] for k in range(3)]
    along=sum(axis[k]*r[k] for k in range(3))
    return math.sqrt(max(0.0,sum(v*v for v in r)-along*along))


def _positions(app):
    return {b["name"]:[float(v) for v in b.get("position_m") or [0.0,0.0,0.0]]
            for b in (app.live.session.state or {}).get("bodies",[])}


def _joined(group,joints,things):
    """The worked thing and everything joined to it -- by a pin, a groove, a
    rope over a pulley, a spring or a fixing -- going on through things that
    move and stopping at anything fixed in place: all that working it can move."""
    reach,these=set(group),list(group)
    while these:
        n=these.pop()
        for j in joints:
            if not j.get("attached") or n not in (j.get("a"),j.get("b")): continue
            other=j.get("b") if j.get("a")==n else j.get("a")
            if other and other not in reach and not (things.get(other) or {}).get("anchored"):
                reach.add(other)
                these.append(other)
    return reach


def _what_else_moved(before,after,group,joined=None):
    """What moved most besides what was worked -- the gate a winch raised --
    in plain words, or None when nothing else moved 2 cm. Only among what is
    joined to it, when that is given: measured on the world, a bell still
    swinging on the far terrace from being rung was said to have moved 0.28 m
    with a turn of the bow."""
    best=None
    for name,p0 in before.items():
        if name in group or name not in after: continue
        if joined is not None and name not in joined: continue
        d=[after[name][k]-p0[k] for k in range(3)]
        size=math.sqrt(sum(v*v for v in d))
        if size>=0.02 and (best is None or size>best[1]): best=(name,size,d)
    if best is None: return None
    name,size,d=best
    if abs(d[1])>=0.7*size: return f"{name} {'rose' if d[1]>0 else 'came down'} {abs(d[1]):.2f} m"
    return f"{name} moved {size:.2f} m"


def _worked(app,part,step,kind,holding=None):
    """A turn ("hinge") or a slide ("slider") step: the hand takes hold of what
    stands off the pin (for a groove, the part) -- going on from holding, when
    that is part of the same thing -- carries it round the pin or along the
    groove with its own strokes, and keeps hold. Returns (what it did, what it
    holds, why it fell short or None); ValueError when it cannot begin."""
    turning=kind=="hinge"
    joints=app.live.act({"session":app.live.session.id,"op":"joints"})["joints"]
    joint,group=_governing(joints,part,kind)
    if joint is None:
        raise ValueError(f"{part} does not {'turn on a pin' if turning else 'slide in a groove'},"
                         f" and nothing it is fixed to does")
    if holding and holding not in group:
        raise ValueError(f"the hand already has {holding}: let go of it first")
    # Fixed to something that does not move -- a gate's latch bar to its post --
    # it is held fast, and the hand would only be pulling on the post.
    things={b.get("name"):b for b in (app.live.session.state or {}).get("bodies",[])}
    fast=next((n for n in sorted(group) if (things.get(n) or {}).get("anchored")),None)
    if fast is not None:
        raise ValueError(f"{part} is held fast to {fast}: release the latch first"
                         f" (R, or the right mouse)")
    axis=_unit(joint.get("axis") or [0.0,1.0,0.0])
    at=[float(v) for v in joint.get("at") or [0.0,0.0,0.0]]
    now=float(joint.get("degrees" if turning else "metres") or 0.0)
    lo=joint.get("lower_deg" if turning else "lower_m")
    hi=joint.get("upper_deg" if turning else "upper_m")
    wheel=turning and _goes_right_round(lo,hi)
    if wheel: now,target=_round_target(now,step)
    else: target=_joint_target(now,lo,hi,step,360.0 if turning else None)
    amount=target-now
    if abs(amount)<(2.0 if turning else 0.02):
        raise ValueError(f"{part} is already there, at {now:.0f} degrees" if turning
                         else f"{part} is already there, {now:.2f} m along its groove")
    before=_positions(app)
    moving=joint["b"] if joint.get("b") in group else joint["a"]
    if turning:
        grip=max((n for n in group if n in before),key=lambda n:_off_axis(before[n],axis,at),default=None)
        if grip is None or _off_axis(before[grip],axis,at)<0.05:
            raise ValueError(f"nothing of {part} stands off its pin far enough for a hand to turn it by")
        start=before[grip]
        count=max(1,math.ceil(abs(amount)/TURN_STEP_DEG))
        path=[_rotated(start,axis,at,math.radians(amount*k/count)) for k in range(1,count+1)]
        speed=TURN_SPEED_M_S
    else:
        grip=part if part in before else moving
        start=before[grip]
        path=[[start[k]+axis[k]*amount for k in range(3)]]
        speed=SLIDE_SPEED_M_S
    # Taken hold of as the page's E takes hold of a thing on a joint: hauled,
    # with the hand's 800 N at its middle and no wrist. Wielded, the wrist held
    # the winch's handle square while the wheel had to turn it, and the hand
    # stalled at 36 of the 179 degrees asked.
    app.live.act({"session":app.live.session.id,"op":"grab","name":grip})
    here=start
    for i in range(0,len(path),15):
        chunk=path[i:i+15]
        ended=_stroke_along(app,[here]+chunk,speed)
        here=chunk[-1]
        if ended!="reached": break
    joints=app.live.act({"session":app.live.session.id,"op":"joints"})["joints"]
    reached=next((float(j.get("degrees" if turning else "metres") or 0.0) for j in joints
                  if j.get("id")==joint.get("id")),now)
    # Measured, a winch's wheel taken half a turn to 179 degrees came to rest a
    # degree past, and read -180: read where it was asked to go, not across the join.
    if wheel: reached=target+_wrapped(reached-target)
    went=reached-now
    moved=_what_else_moved(before,_positions(app),group,_joined(group,joints,things))
    said=(f"turned {moving} {went:+.0f} degrees, to {reached:.0f}" if turning
          else f"slid {moving} {went:+.2f} m, to {reached:.2f} m")+(f"; {moved}" if moved else "")
    if abs(reached-target)>(10.0 if turning else 0.05):
        return said,grip,(f"the hand turned it {went:+.0f} of the {amount:+.0f} degrees asked, and could turn it no further"
                          if turning else
                          f"the hand slid it {went:+.2f} of the {amount:+.2f} m asked, and could move it no further")
    return said,grip,None


# How much of the world's own time may go by, while the page steps it, between
# saving the running world with its room (keep_world): a restart gives back the
# room as it stood at most this long before the server stopped.
KEEP_WORLD_EVERY_S=5.0
# And after a save the engine refused -- something under way that a saved world
# cannot carry -- how long before it is asked again: not on every step.
KEEP_WORLD_RETRY_S=0.5


def keep_world(app,why=""):
    """Save the running world with its room (room_store v2, `world`), so a
    restart gives back the room as it stood rather than as it was authored:
    where everything is and how it moves or rests, what broke into what, dents
    and cuts, joints at their angles, what is set aside, what the hand holds.

    Asked for after an accepted change to what the person has, after a break is
    worked out, every KEEP_WORLD_EVERY_S of the world's time while the page steps
    it, after the ground changes, after the room opens and as the server stops.
    Only for the world page's own room, and only a room that is kept. A world
    that will not be saved now -- something under way that a saved world cannot
    carry: a break, a stroke of the hand, an edge in a cut, a point in the
    ground -- keeps the last one saved, and says why in the log. True when the
    world and its room were written."""
    room=getattr(app,"room",None)
    if room is None or getattr(room,"scene",None) not in world_room.SCENES: return False
    if getattr(app,"live_holder",None)!="world" or app.live.session is None: return False
    snapshot=getattr(app.live,"snapshot",None)
    if snapshot is None: return False
    lock=getattr(app,"world_lock",None)
    if lock is None: lock=app.world_lock=threading.Lock()
    with gameplay_room.LOCK, lock:
        saved,refused=snapshot()
        if saved is None:
            log.info("rooms: the running world was not saved (%s): %s; the last one saved is kept",why,refused)
            return False
        gameplay_room.sync(app, {"t": float(saved.get("t_s") or 0.0)})
        fabrication_room.sync(app, {"t": float(saved.get("t_s") or 0.0)})
        room.world_record=saved
        if gameplay_room.active(app) or fabrication_room.active(app):
            store = getattr(app, "store", None)
            if store is None or not store.save(room):
                return False
        else:
            room_store.keep(app,room)
        room.world_saved_t=float(saved.get("t_s") or 0.0)
    return True


def keep_world_after(app,body,answer):
    """What a page's own act asks of the room kept with the server: the world
    saved once a break has been worked out (a reply that says `finished`), and
    every KEEP_WORLD_EVERY_S of the world's time while the page steps it."""
    if not isinstance(body,dict) or not isinstance(answer,dict): return
    room=getattr(app,"room",None)
    if room is None: return
    t=answer.get("t")
    due=bool(answer.get("finished"))
    if not due and body.get("op")=="step" and isinstance(t,(int,float)):
        # Either way round: a world opened again starts its clock over.
        due=(abs(float(t)-float(getattr(room,"world_saved_t",-1.0e9)))>=KEEP_WORLD_EVERY_S
             and abs(float(t)-float(getattr(room,"world_refused_t",-1.0e9)))>=KEEP_WORLD_RETRY_S)
    if not due: return
    if not keep_world(app,"a break was worked out" if answer.get("finished") else "the world moved on") \
            and isinstance(t,(int,float)):
        room.world_refused_t=float(t)


def _rejoin(app,scene):
    """The room this server is running, for a page that opens it again: every
    body where it is and as it is now -- moved, broken, dented -- the hand still
    holding what it held, and the bag as the record has it. A reload used to open
    the room again from its spec, which put all of that back as authored and
    emptied the hand. None when the room asked for is not the one running here
    (another scene, the lab's world, nothing open), and the room is opened as
    before."""
    room=getattr(app,"room",None)
    if (room is None or room.scene!=scene or getattr(app,"live_holder",None)!="world"
            or app.live.session is None):
        return None
    rejoin=getattr(app.live,"rejoin",None)
    opened=rejoin(app) if rejoin is not None else None
    if opened is None: return None
    opened=world_upgrades.apply(app,opened)
    gameplay_room.opened(app, opened)
    opened["inventory"]=inventory_room.shown(app)
    opened["scene"]=room.scene
    opened["scenes"]=sorted(world_room.SCENES)
    # Not read back from disk: this server holds it (kept means that).
    opened["kept"]=False
    opened["chat"]=room.chat[-20:]
    return opened


def _this_pages_room(app,body):
    """A page acts on the room it has open, and on no other. The playground runs
    one room at a time, so a page whose room was opened again -- in another tab,
    by another person, by the lab -- no longer has one. Measured 2026-09-14 on
    8781: a checker's page that had lost its room to the owner's went on
    pressing "Put it on the ground in front of me", and each press carried the
    oak plank about in the owner's room, from where the checker stood."""
    session=app.live.session
    if session is None: raise ValueError("the room is not open")
    asked=str(body.get("session") or "") if isinstance(body,dict) else ""
    if asked!=session.id:
        raise ValueError("this page no longer has the room: it was opened again, in another tab or"
                         " page, so nothing was done here. Reload the page to take the room back")


def _motor_for(app,part):
    """The motor that turns `part`, from the machines the last step reported
    (docs/machine-world.md): a motor is known by the two things its pin joins.
    Two motors on pins of one thing -- two drums on one frame -- are not
    guessed between, as the first that matched was: the thing a motor turns
    names it, and the frame they share names neither."""
    state=(app.live.session.state or {}) if app.live.session else {}
    found=[m for m in ((state.get("machines") or {}).get("motors") or []) if part in (m.get("on") or [])]
    if len(found)>1:
        turning=[m for m in found if (m.get("on") or [None,None])[1]==part]
        if len(turning)==1: return turning[0]
        raise ValueError(f"{len(found)} motors are on pins of {part}, between "
                         +"; ".join(" and ".join(m.get("on") or []) for m in found)
                         +": name the thing the one you mean turns")
    if found: return found[0]
    raise ValueError(f"nothing turns {part} with a motor")

def _control_for(app,which):
    """A machine's controller in the running room, by its name or by a part of
    it that is in one machine only, from the machines the last step reported."""
    state=(app.live.session.state or {}) if app.live.session else {}
    controls=(state.get("machines") or {}).get("controls") or []
    named=[c for c in controls if c.get("name")==which]
    if named: return named[0]
    found=[c for c in controls if which in (c.get("parts") or [])]
    if len(found)>1:
        raise ValueError(f"{which} is part of {len(found)} machines, "
                         +", ".join(str(c.get("name","")) for c in found)+": name the one you mean")
    if found: return found[0]
    raise ValueError(f"there is no machine called {which!r} in the room")

def operate_machine(app,body):
    """One command to a machine's controller (docs/machine-world.md, "Operating
    a machine"), from the page's panel (POST /api/world/machine) or the room's
    chat (operate): {control, sender, seq, power, direction, setting}, each of
    the last three only if given. It goes straight to the controller -- not
    through a thing's actions, the chat's model or the hand -- and what the
    engine said comes back: "applied", or "stale" for a command no newer than
    one it has applied from that sender, with the controller as it now stands.
    That answer is the acknowledgement the panel waits for; what the machine
    then does comes with every step."""
    if app.live.session is None: raise ValueError("the room is not open")
    if not isinstance(body,dict): raise ValueError("expected {control, sender, seq, power, direction, setting}")
    command={"session":app.live.session.id,"op":"operate","control":body.get("control"),
             "sender":str(body.get("sender") or "")[:64],"seq":body.get("seq",0)}
    for key in ("power","direction","setting"):
        if body.get(key) is not None: command[key]=body[key]
    said=app.live.act(command)
    # Kept with the world as it now stands, so a restart finds the machine as
    # it was told.
    if said.get("operated")=="applied": keep_world(app,"a machine was told what to do")
    return {"operated":said.get("operated"),"control":said.get("control")}

def _chat_live(app,name,args,person=None):
    """What the room's chat does to the room as it stands (room_world.LIVE): one
    of a thing's actions pressed, as the page's E presses it, or its motor told
    what to do. The running room takes it, and nothing is opened again -- the
    owner, 2026-09-15: "nothing should be resetting rooms". What it did, or
    {"error": why}, for the model."""
    try:
        if name=="use_action":
            thing=str(args.get("name",""))[:200]
            offered=[a for a in (app.room.spec.get("actions") or []) if a.get("body")==thing]
            if args.get("primary") is True:
                said = run_action(app, {"object": thing, "primary": True, "person": person})
                if said.get("refused"):
                    return {"error": said["refused"], "done": said.get("done", [])}
                return {"used": thing, **said}
            if not offered: raise ValueError(f"{thing or 'that'} has no actions in this room: offer_actions gives it some")
            which=args.get("action")
            labels=[str(a.get("label","")) for a in offered]
            index=next((i for i,label in enumerate(labels) if label.lower()==str(which).strip().lower()),None)
            key=str(which).strip()
            if index is None and key.isdigit() and 1<=int(key)<=len(offered):
                index=int(key)-1
            if index is None: raise ValueError(f"{thing} has no action {which!r}: its actions are {', '.join(labels)}")
            said=run_action(app,{"object":thing,"action":index,"person":person})
            if said.get("refused"): return {"error":said["refused"],"done":said.get("done",[])}
            return {"used":thing,"action":said["action"],"done":said["done"],
                    "in_the_room":"done to the room as it stands, as the person's E does it; nothing was opened again"}
        if name=="drive":
            part=str(args.get("part") or "")
            motor=_motor_for(app,part)
            command=max(-1.0,min(1.0,float(args.get("command",0.0))))
            brake=bool(args.get("brake",command==0.0))
            app.live.act({"session":app.live.session.id,"op":"drive","motor":motor["id"],
                          "command":command,"brake":brake})
            # What the chat said is written into the room as well: kept as told
            # here, so a room it changes later carries the motor as it is then
            # rather than telling it this again.
            live_session.remember_told(app.live.session,motor["id"],command,brake)
            # A motor with a controller is worked by it, and the engine hands
            # it what drive said: power on, the command's way and size. The
            # chat's copy writes that into the room's controller too, so it is
            # kept as told as well -- or a later change would tell it again
            # over whatever the person's panel or E did since.
            # A controller told nothing of its own passes on the motor's, which
            # remember_told has just kept.
            state=app.live.session.state or {}
            control=next((c for c in ((state.get("machines") or {}).get("controls") or [])
                          if c.get("motor")==motor["id"]),None)
            declared=getattr(app.live.session,"declared",None) or {}
            told=next((t for _,t,i in declared.get("controls") or [] if control is not None and i==control["id"]),None)
            if control is not None and told is not None and told[0] is not None:
                way=0 if command==0.0 else (1 if command*int(control.get("forward",1))>0 else -1)
                live_session.remember_operated(app.live.session,control["id"],True,way,
                                               abs(command) if command else float(control.get("setting",1.0)))
            return {"in_the_room":f"the running room's motor turning {part} was told it too; nothing was opened again"}
        if name=="operate":
            # A machine worked from its controller, as the person's panel works
            # it: what the model's copy made of the words, told to the running
            # room's machine, and kept as what it was told (remember_operated).
            control=_control_for(app,str(args.get("machine") or ""))
            said=operate_machine(app,{"control":control["id"],"sender":"chat","seq":0,
                                      **{k:args[k] for k in ("power","direction","setting") if args.get(k) is not None}})
            live_session.remember_operated(app.live.session,control["id"],args.get("power"),args.get("direction"),
                                           args.get("setting"))
            now=said.get("control") or {}
            return {"in_the_room":f"the running room's {control.get('name')} was told it too; nothing was opened again",
                    **({"condition_now":now.get("condition")} if now.get("condition") else {})}
        return {"error":f"{name} is not something done to the room as it stands"}
    except Exception as failure:
        return {"error":str(failure)}

def _core_hand_step(app, name, step, person):
    """Execute a declared gesture, never prescribe an object trajectory."""
    from mcp import core_use
    step = core_use.checked_step(step)
    target = _live_body(app, name)
    if step["do"] == "inspect":
        state = {k: target[k] for k in ("position_m", "mass_kg", "dimensions_m", "anchored", "temperature_k") if k in target}
        return f"inspected {name}: " + json.dumps(state, allow_nan=False), None
    if person is None:
        raise ValueError("Use needs the person's position and facing")
    if target.get("anchored"):
        raise ValueError(f"{name} is fixed in place")
    hand = (app.live.session.state or {}).get("hand") or {}
    held = (hand.get("name") or hand.get("holding")) if hand.get("holding") else None
    at = [float(v) for v in target["position_m"]]
    if step["do"] == "strike":
        if held != name:
            raise ValueError(f"pick up {name} before striking")
        start = list(hand.get("grip_m") or at)
        way = person.get("look_direction") or person["facing"]
        end = [start[k] + way[k] * step["distance_m"] for k in range(3)]
        ended = _stroke_to(app, end, step["speed_m_s"], start)
        if ended not in ("reached", "blocked"):
            app.live.act({"session": app.live.session.id, "op": "cancel_stroke"})
            return "", f"{name} stroke {ended}"
        # A stopped stroke can be contact; it is not proof of a successful hit.
        grip = ((app.live.session.state or {}).get("hand") or {}).get("grip_m") or start
        returned = _stroke_to(app, start, min(step["speed_m_s"], 1.0), grip)
        if returned not in ("reached", "blocked"):
            app.live.act({"session": app.live.session.id, "op": "cancel_stroke"})
            return f"swung {name}; stroke {ended}", f"return stroke {returned}"
        return f"swung {name}; stroke {ended}", None
    if held:
        raise ValueError("put down what you are holding before pushing")
    eyes = person.get("eyes_m") or person["standing_m"]
    if math.dist(at, eyes) > 3.0:
        raise ValueError("move within 3 m of the product to use it")
    way = person["facing"]
    end = [at[k] + way[k] * step["distance_m"] for k in range(3)]
    app.live.act({"session": app.live.session.id, "op": "wield", "name": name, "grip": at})
    try:
        ended = _stroke_to(app, end, step["speed_m_s"], at)
    finally:
        app.live.act({"session": app.live.session.id, "op": "release"})
    now = _live_body(app, name)["position_m"]
    moved = sum((now[k] - at[k]) * way[k] for k in range(3))
    if moved < 0.02:
        return "", f"{name} did not move forward: blocked or beyond the hand's force"
    return f"pushed {name} forward {moved:.2f} m (stroke {ended})", None


def run_action(app, body):
    # A product cannot start overlapping programs on the same physical hand.
    # setdefault is not available on the app Namespace; initialize under GIL.
    lock = app.__dict__.setdefault("action_lock", threading.Lock())
    if not lock.acquire(blocking=False):
        raise ValueError("a Use action is already running")
    try:
        return _run_action(app, body)
    finally:
        lock.release()


def _run_action(app,body):
    """One of a thing's actions, pressed on the page (POST /api/world/action).

    An action is a short program the room's chat kept with the thing when it
    made it (offer_actions), and it runs here step by step on the room as it is
    NOW. The hand's steps go to the running room as the engine's own
    operations -- a grip with the hand's 800 N, strokes, letting go, heat --
    while the page keeps the room running and draws what they do. A stand step
    is turn_object on the room, which is then opened again. A step that cannot
    be done stops the action with why: the hand is opened if it held anything,
    and what was done stays done."""
    if app.live.session is None: raise ValueError("the room is not open")
    if not isinstance(body,dict): raise ValueError("expected {object, action, person}")
    room=app.room
    name=str(body.get("object",""))[:200]
    if "primary" in body and not isinstance(body["primary"], bool):
        raise ValueError("primary must be true or false")
    if body.get("primary"):
        from mcp import core_use
        _live_body(app, name)
        action = core_use.selected([a for a in room.spec.get("actions", []) if a.get("body") == name])
    elif body.get("builtin") is not None:
        key=str(body.get("builtin"))
        if key in ("turn","slide"):
            # Everything on a pin or in a groove has these, to the joint's stops.
            stop=str(body.get("stop") or "")
            if stop not in JOINT_STOPS:
                raise ValueError(f"a built-in {key} stops {', '.join(JOINT_STOPS)}, not {stop!r}")
            action={"label":JOINT_LABELS[(key,stop)],"steps":[{"do":key,"stop":stop}]}
        elif key in BUILTIN_ACTIONS: action=BUILTIN_ACTIONS[key]
        else: raise ValueError(f"there is no built-in action {key!r}")
    else:
        offered=[action for action in (room.spec.get("actions") or []) if action.get("body")==name]
        try: index=int(body.get("action"))
        except (TypeError,ValueError): raise ValueError("action is the number of one of the thing's actions, from 0") from None
        if not 0<=index<len(offered): raise ValueError(f"{name or 'that'} has no action {index+1}")
        action=offered[index]
    person=world_chat.where_the_person_is(body.get("person"))
    # The hand may already hold what a turn or a slide works -- a winch kept
    # turned, its gate up: "Lower the gate" goes on from that hold, since
    # letting go first would drop the gate. Anything else needs the hand free.
    hand = (app.live.session.state or {}).get("hand") or {}
    held = (hand.get("name") or hand.get("holding")) if hand.get("holding") else None
    if held and action["steps"][0]["do"] not in ("turn","slide","drive","strike","inspect","place"):
        raise ValueError("put down what you are holding first: the action needs your hand")
    done,opened,holding,problem,index=[],None,held or None,None,0
    # What the hand held before the action: the action lets go only of what it
    # took hold of itself (below).
    before=holding
    try:
        for index,step in enumerate(action["steps"]):
            do=step["do"]
            if do == "place":
                line, problem = placement.execute(app, name, person, _stroke_along, body.get("placement_target"))
                if line: done.append(line)
                if problem: break
                holding = None
            elif do in ("inspect", "strike", "push_forward"):
                line, problem = _core_hand_step(app, name, step, person)
                if line: done.append(line)
                if problem: break
            elif do=="stand":
                now,said=_stand(app,room,name,step,person)
                if now is None:
                    problem=said
                    break
                opened=now
                done.append(said)
            elif do=="take_hold":
                part=step.get("part") or name
                held=_live_body(app,part)
                # What the running room says of it now: the MCP checked the
                # chat's actions when it offered them, and nothing checked a
                # built-in one, and a thing can have changed since.
                if held.get("anchored"):
                    problem=f"{part} is fixed in place, and a hand cannot move it"
                    break
                kg=held.get("mass_kg")
                if kg is not None and float(kg)>room_world.banjo_mcp.HAND_LIFTS_KG:
                    problem=(f"{part} weighs {float(kg):.0f} kg, more than the "
                             f"{room_world.banjo_mcp.HAND_LIFTS_KG:.0f} kg a hand can hold up")
                    break
                at=[float(v) for v in held.get("position_m")]
                app.live.act({"session":app.live.session.id,"op":"wield","name":part,"grip":at})
                holding=part
                done.append(f"took hold of {part}")
            elif do=="carry_to":
                target=_action_point(app,step["to"],person,holding)
                here=[float(v) for v in _live_body(app,holding).get("position_m")]
                ended=_stroke_to(app,target,step.get("speed_m_s",0.5),here)
                if ended!="reached":
                    problem=f"{holding} did not get there: the hand's stroke {ended}"
                    break
                done.append(f"carried {holding}")
            elif do=="put_down":
                # Lowered straight down until what is under it stops it.
                here=[float(v) for v in _live_body(app,holding).get("position_m")]
                _stroke_to(app,[here[0],here[1]-2.0,here[2]],0.4,here)
                app.live.act({"session":app.live.session.id,"op":"release"})
                done.append(f"put {holding} down")
                holding=None
            elif do=="let_go":
                app.live.act({"session":app.live.session.id,"op":"release"})
                done.append(f"let go of {holding}")
                holding=None
            elif do=="push":
                part=step.get("part") or name
                at=[float(v) for v in _live_body(app,part).get("position_m")]
                toward=_action_point(app,step["toward"],person,part)
                way=[toward[k]-at[k] for k in range(3)]
                size=math.sqrt(sum(v*v for v in way))
                if size<1e-6:
                    problem=f"{part} is already there"
                    break
                end=[at[k]+way[k]/size*min(float(step.get("distance_m",0.3)),size) for k in range(3)]
                app.live.act({"session":app.live.session.id,"op":"wield","name":part,"grip":at})
                holding=part
                ended=_stroke_to(app,end,step.get("speed_m_s",0.4),at)
                app.live.act({"session":app.live.session.id,"op":"release"})
                holding=None
                # Said by how far it went, not by what was asked: a 151 kg oak
                # table the chat built as one block did not move at all under
                # the hand's 800 N, and the action said "pushed" all the same.
                now=[float(v) for v in _live_body(app,part).get("position_m")]
                moved=math.sqrt(sum((now[k]-at[k])**2 for k in range(3)))
                if moved<0.02:
                    problem=(f"{part} did not move: the hand's 800 N could not push it"
                             if ended in ("gave up","ran out of time")
                             else f"{part} did not move: something is in its way")
                    break
                done.append(f"pushed {part} {moved:.2f} m"
                            +("" if ended=="reached" else ", until something stopped it"))
            elif do in ("turn","slide"):
                line,grip,short=_worked(app,step.get("part") or name,step,
                                        "hinge" if do=="turn" else "slider",holding)
                holding=grip
                done.append(line)
                if short:
                    problem=short
                    break
            elif do=="heat":
                part=step.get("part") or name
                app.live.act({"session":app.live.session.id,"op":"heat","target":part,"power_w":float(step.get("power_w",2000.0)),
                              "seconds":float(step.get("seconds",10.0))})
                done.append(f"heating {part}")
            elif do=="drive":
                # A motor told what to do (docs/machine-world.md): a command
                # from -1 to 1 and its brake -- on by default when it is told to
                # stop. It is the motor that turns the part; the hand is not
                # needed, so it may be holding something.
                part=step.get("part") or name
                motor=_motor_for(app,part)
                command=max(-1.0,min(1.0,float(step.get("command",0.0))))
                brake=bool(step.get("brake",command==0.0))
                app.live.act({"session":app.live.session.id,"op":"drive","motor":motor["id"],
                              "command":command,"brake":brake})
                done.append(f"stopped the motor turning {part}"+(" and put its brake on" if brake else "")
                            if command==0.0 else
                            f"set the motor turning {part} going {'back ' if command<0 else ''}"
                            f"at {round(100*abs(command))}%")
            elif do=="wait":
                time.sleep(float(step.get("seconds",1.0)))
                done.append(f"waited {float(step.get('seconds',1.0)):g} s")
    except ValueError as failure:
        problem=str(failure)
    # A program that ends on a turn or a slide keeps hold -- there, short of it,
    # or already there -- so what it raised stays up until the person lets go:
    # the page takes the hold over. Anything else the hand has is let go of.
    ends_working=action["steps"][-1]["do"] in ("turn","slide")
    kept=bool(holding and ends_working and (not problem or index==len(action["steps"])-1))
    # A turn or a slide that failed part way may hold what it took hold of.
    worked=any(step["do"] in ("turn","slide") for step in action["steps"][:index+1])
    # Only what the action itself took hold of, or worked, is let go of. What
    # the hand held before it and the action never touched -- a ball carried
    # while a motor is told what to do -- stays in the hand: it was let go of
    # too, so "Wind it up" pressed with a ball in the hand dropped the ball.
    acquired=bool(holding) and holding!=before
    if not kept and (acquired or worked):
        try: app.live.act({"session":app.live.session.id,"op":"release"})
        except ValueError: pass
    said={"action":action["label"],"done":done}
    if problem: said["refused"]=problem
    else: said["did"]=[action["label"]]
    if kept or (before and not acquired and not worked): said["holding"]=holding
    if opened is not None: said.update(reopened=True,session=opened["session"],state=opened)
    return said


# What a person knows (docs/knowledge-and-progression.md, increment 2). Their
# notebook, kept beside their rooms, grows only from what the engine measured
# their own hand doing in their own room: every reply of the live world passes
# through hear (live_session.Session.on_reply), and nothing else writes to it --
# not the chat, whose tools only read it, and not the page.
_REGISTRY=None


def registry():
    """The curated graph, loaded and checked once (mcp/progression.py)."""
    global _REGISTRY
    if _REGISTRY is None: _REGISTRY=progression.Registry()
    return _REGISTRY


def journal_of(app):
    """The person's notebook: one to a server, in its rooms' folder, so it
    outlives every rebuild of a room and every restart. In memory only when the
    server keeps no rooms."""
    journal=getattr(app,"journal",None)
    if journal is None:
        store=getattr(app,"store",None)
        journal=app.journal=progression.Journal(Path(store.folder)/"journal.json" if store is not None else None)
    return journal


def heard(app,session,reply):
    """Every reply of the person's live room: to their notebook (hear), and to
    whoever listens for a while (app.reply_listeners, a tool's use). A listener
    that fails is logged and never stops the room."""
    hear(app,session,reply)
    for listener in list(getattr(app,"reply_listeners",None) or ()):
        try: listener(session,reply)
        except Exception: logging.getLogger("banjo").exception("banjo: a reply's listener failed")


def hear(app,session,reply):
    """One reply of the person's live room. Each ground-work record in it that
    has closed is the engine's measurement of their own tool meeting the ground:
    evidence where it is evidence, a note where the engine says the regime is not
    modelled, and nothing where it is neither -- once per result, however often
    the same reply is read."""
    records=reply.get("ground_work") if isinstance(reply,dict) else None
    spec=getattr(session,"room_spec",None)
    if not records or not isinstance(spec,dict): return
    journal=journal_of(app)
    at=time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime())
    strikes=list(getattr(session,"strikes",None) or [])
    for record in records:
        if not isinstance(record,dict) or record.get("open"): continue
        # Only what one of their strikes did: a tool put down or knocked
        # into the ground meets it too, and that tests nothing it is for.
        if not progression.from_a_strike(record,strikes): continue
        why=progression.not_modelled(record)
        if why:
            journal.add_note(progression.result_key(session.id,record),why)
            continue
        evidence=progression.evidence_from(record,session_id=session.id,spec=spec,registry=registry(),at=at)
        if evidence is not None: journal.add_evidence(evidence)


def note_strike(app,answer):
    """When one of the person's strikes began, in the world's own clock (the
    reply's t): what their tool does to the ground within its stroke is theirs
    to be credited with (hear)."""
    session=app.live.session
    if session is None or not isinstance(answer,dict) or answer.get("t") is None: return
    strikes=getattr(session,"strikes",None)
    if strikes is None: strikes=session.strikes=[]
    strikes.append(float(answer["t"]))
    del strikes[:-32]


def knowledge_view(app):
    """The person's notebook as read_knowledge says it (GET /api/knowledge)."""
    return progression.notebook(journal_of(app),registry())


def with_notebook(app,answer,seen):
    """An act's answer, with the notebook in it when the server's is newer than
    the one the page says it has shown -- and only then."""
    if isinstance(seen,int) and isinstance(answer,dict) and journal_of(app).data["revision"]>seen:
        answer=dict(answer,notebook=knowledge_view(app))
    return answer


# As many as a room's terrain may hold; see fracture_lab.normalise_terrain.
MAX_GROUND_EDITS=400


def remember_ground(app,body,answer=None):
    """A spade -- or a pick -- in the person's hand changes the ground for good.

    The ground is part of what the room IS, not something in flight in it: a
    pit dug with Dig here is still a pit when the room is opened again -- after
    the chat changes something, or on a reload -- and the chat's own copy of the
    room has it too. So a dig or a heap the engine made is written into the
    room's terrain edits, as the engine was asked for it. Asking the chat to
    make the valley again gives the untouched ground back.

    And what a pick's pry broke loose went out through the ground's own dig:
    each meeting of a point with the ground that did says where, in the answer
    that reports it over (ground_work's "dug", unrounded), and it is kept as the
    dig edit it was -- made again from those numbers, it takes out the same
    (docs/ground-work.md)."""
    new=[]
    if isinstance(body,dict) and body.get("op") in ("dig","deposit"):
        def xz(key,default=None):
            value=body.get(key,default)
            return [float(value[0]),float(value[-1])]
        if body["op"]=="dig":
            start=xz("from")
            # As deep as it WENT, which is less than was asked when no more
            # could be carried (the engine's "dug" says, unrounded). Kept as
            # asked, the room opened again dug the whole pit and carried the lot.
            depth=float(body.get("depth_m",0.5))
            went=(answer.get("dug") or {}).get("depth_m") if isinstance(answer,dict) else None
            if isinstance(went,(int,float)) and not isinstance(went,bool) and math.isfinite(went): depth=float(went)
            if depth>0.0:
                new.append({"dig":{"from_m":start,"to_m":xz("to",start),
                                   "width_m":float(body.get("width_m",1.0)),"depth_m":depth}})
        else:
            new.append({"deposit":{"at_m":xz("at"),"radius_m":float(body.get("radius_m",1.0)),
                                   "sand_m3":float(body.get("sand_m3",0.0)),"soil_m3":float(body.get("soil_m3",0.0))}})
    if isinstance(answer,dict):
        for work in answer.get("ground_work") or []:
            dug=work.get("dug") if isinstance(work,dict) else None
            # Nothing came out (the person carries all they can): not an edit.
            if isinstance(dug,dict) and not float(dug.get("depth_m") or 0.0)>0.0: continue
            if isinstance(dug,dict) and not work.get("open"):
                new.append({"dig":{"from_m":[float(v) for v in dug["from_m"]],"to_m":[float(v) for v in dug["to_m"]],
                                   "width_m":float(dug["width_m"]),"depth_m":float(dug["depth_m"])}})
    if not new: return
    room=getattr(app,"room",None)
    spec=getattr(room,"spec",None)
    if not isinstance(spec,dict) or not spec.get("terrain"): return
    terrain=dict(spec["terrain"])
    edits=list(terrain.get("edits") or [])
    if len(edits)+len(new)>MAX_GROUND_EDITS:
        log.warning("ground: the room already holds %d edits; what does not fit stays in the running world only",
                    len(edits))
        new=new[:max(0,MAX_GROUND_EDITS-len(edits))]
        if not new: return
    terrain["edits"]=edits+new
    room.spec=dict(spec,terrain=terrain)
    # The ground is part of what the room is, so it is kept with it (room_store),
    # and with the world standing on it as it is now.
    if not keep_world(app,"the ground changed"): room_store.keep(app,room)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port",type=int,default=8765)
    binary=ROOT/"build/win-joint-double/Release"
    parser.add_argument("--engine",type=Path,default=binary/"banjo_platform_cli.exe")
    parser.add_argument("--studio",type=Path,default=binary/"banjo_network_lab.exe")
    parser.add_argument("--runs",type=Path,default=ROOT/"build/playground-runs")
    # Where this server keeps its rooms (room_store): a folder to a port by
    # default, because the three sims share one checkout.
    parser.add_argument("--rooms",type=Path,default=None,
                        help="where rooms are kept (default build/playground-rooms/<port>)")
    # Hold the world in this process, through the C library, instead of in a
    # subprocess speaking the line protocol. Same engine, same scenes, same
    # replies -- one process boundary fewer. Off by default because a world that
    # falls over takes the server with it here, and the server is what is on
    # screen.
    parser.add_argument("--live-inprocess",action="store_true",
                        default=os.environ.get("BANJO_LIVE_INPROCESS")=="1",
                        help="drive live worlds through the C library in this process")
    # Where to listen. Anything but loopback lets anyone reach the room and
    # spend the model credits, so it needs BANJO_PASSWORD (access_gate,
    # docs/deploy.md); BANJO_PUBLIC_HOST is then the one name it answers to.
    parser.add_argument("--host",default="127.0.0.1",
                        help="where to listen (anything but 127.0.0.1 needs BANJO_PASSWORD)")
    args=parser.parse_args()
    if not 1024<=args.port<=65535: parser.error("Use a port in 1024..65535")
    password=os.environ.get("BANJO_PASSWORD","")
    refused=access_gate.refusal(args.host,password)
    if refused: parser.error(refused)
    # The valley is made once by physics and kept: every world that opens on it
    # -- the room's and the chat's -- reads the same saved ground rather than
    # making it again. Under build/, beside everything else this server writes.
    os.environ.setdefault("BANJO_TERRAIN_CACHE",str(ROOT/"build"/"terrain-cache"))
    # Whatever the engine says it waited on goes to the log, at the level the
    # rest of the server uses.
    logging.basicConfig(level=logging.INFO,format="%(asctime)s %(message)s")
    app=Playground(args.engine,args.studio,args.runs)
    app.store=room_store.RoomStore(args.rooms or ROOT/"build"/"playground-rooms"/str(args.port))
    print(f"rooms are kept in {app.store.folder}",flush=True)
    app.live_inprocess=args.live_inprocess
    if args.live_inprocess:
        ok,why=live_inprocess.available()
        if not ok: parser.error(f"--live-inprocess needs the C library: {why}")
        print("live worlds run in this process, through the C library",flush=True)
    # Behind a password when there is one (access_gate), and answering to the one
    # public name, besides localhost, when it is hosted.
    app.password=password or None
    app.public_host=os.environ.get("BANJO_PUBLIC_HOST") or None
    # One saved world at a time (keep_world): two request threads saving at once
    # could put the older world on disk last.
    app.world_lock=threading.Lock()
    server=ThreadingHTTPServer((args.host,args.port),Handler);server.app=app
    print(f"Banjo playground: http://127.0.0.1:{args.port}"
          +(f" -- listening on {args.host}, behind a password" if app.password else ""),flush=True)
    # Asked to stop -- a host redeploying, a service manager -- the server stops
    # the way Ctrl+C stops it, so the running world is saved on the way out.
    def asked_to_stop(*_):
        raise KeyboardInterrupt
    for name in ("SIGTERM","SIGBREAK"):
        if hasattr(signal,name):
            try: signal.signal(getattr(signal,name),asked_to_stop)
            except (ValueError,OSError): pass
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally:
        server.server_close()
        # The room as it stands now, for the server that starts next.
        try: keep_world(app,"the server stopped")
        except Exception: log.exception("rooms: the running world could not be saved as the server stopped")
        if hasattr(app,"material_qa"): app.material_qa.shutdown()
        if hasattr(app,"mechanics_qa"): app.mechanics_qa.shutdown()
        if hasattr(app,"fabrication_qa"): app.fabrication_qa.shutdown()
        app.live.shutdown();app.pool.shutdown(wait=False,cancel_futures=True)

if __name__=="__main__": main()
