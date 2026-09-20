"""Versioned physical experiments; user-edited trials never replace QA fixtures."""
from copy import deepcopy
from pathlib import Path
import threading
import time
import uuid
import material_qa as artifacts
import physics_trials

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "examples/physics-trials/regression.json"
_LOCK = threading.Lock()

def cases():
    return artifacts.read_json(FIXTURES)["cases"]

def select(ids=None):
    known = {c["id"]: c for c in cases()}
    if ids is None: return list(known.values())
    if not isinstance(ids, list) or not ids or len(ids) > len(known) or any(not isinstance(i, str) or i not in known for i in ids) or len(set(ids)) != len(ids):
        raise ValueError("case_ids must be a unique nonempty list from the mechanics catalog")
    return [known[i] for i in ids]

def binary(engine):
    if engine is None: return None
    p = Path(engine)
    return p.with_name("banjo_live_world_run" + (".exe" if p.suffix == ".exe" else ""))

def catalog(engine):
    return {**physics_trials.catalog(), "cases": cases(), "suite_hash": artifacts.digest(cases()),
            "engine_available": bool(binary(engine) and binary(engine).is_file()),
            "acceptance": "Versioned physical invariants, not automatically learned outcomes. Custom checks are authored assertions, not qualification."}

def run_suite(engine, directory, chosen=None, *, document=None, cancel=None):
    selected = [{"id": "custom", "group": "Custom experiment", "document": document}] if document is not None else select(chosen)
    selected = deepcopy(selected)
    for c in selected: c["document"], _ = physics_trials.validate(c["document"])
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    report = {"schema": "banjo.mechanics-qa.v1", "id": directory.name, "status": "running",
              "kind": "custom" if document is not None else "regression", "total": len(selected),
              "completed": 0, "started_unix_s": time.time(), "results": [],
              "suite_hash": artifacts.digest(selected), "provenance": artifacts.provenance(binary(engine))}
    artifacts.write_json(directory/"report.json", report)
    for c in selected:
        if cancel and cancel.is_set(): break
        report["active_case"] = c["id"]
        artifacts.write_json(directory/"report.json", report)
        result = physics_trials.run(engine, directory/c["id"], c["document"], cancel=cancel)
        result.update(id=c["id"], group=c["group"])
        artifacts.write_json(directory/c["id"]/"result.json", result)
        report["results"].append(result); report["completed"] += 1
        artifacts.write_json(directory/"report.json", report)
    report.pop("active_case", None)
    report["status"] = ("cancelled" if cancel and cancel.is_set() else
                        "passed" if all(r["status"] == "passed" for r in report["results"]) else "failed")
    report["finished_unix_s"] = time.time()
    artifacts.write_json(directory/"report.json", report)
    return report

class Manager(artifacts.Manager):
    def __init__(self, app):
        super().__init__(app)
        self.root = Path(app.runs_path)/"mechanics-qa"

    def start(self, body):
        if not isinstance(body, dict) or set(body)-{"case_ids", "document"} or ("case_ids" in body and "document" in body):
            raise ValueError("Use case_ids or a document, not both")
        if "document" in body:
            document, _ = physics_trials.validate(body["document"])
            count = 1
        else:
            document = None; count = len(select(body.get("case_ids")))
        if not binary(self.app.engine_path) or not binary(self.app.engine_path).is_file(): raise ValueError("Build the native live world runner")
        with self.lock:
            if self.thread and self.thread.is_alive(): raise ValueError("A mechanics trial is already running")
            self.run_id = uuid.uuid4().hex; self.cancel_event = threading.Event()
            self.pending = {"id": self.run_id, "status": "starting", "total": count, "completed": 0,
                            "kind": "custom" if document is not None else "regression", "results": []}
            folder = self.folder(self.run_id)
            def work():
                try:
                    run_suite(self.app.engine_path, folder, body.get("case_ids"),
                              document=document, cancel=self.cancel_event)
                except Exception as exc:
                    artifacts.write_json(folder/"report.json", {**self.pending, "status": "failed", "error": str(exc)})
            self.thread = threading.Thread(target=work, name="banjo-mechanics-qa", daemon=True)
            self.thread.start()
            return dict(self.pending)

    def case(self, run_id, case_id, playback=False, request=False):
        if case_id not in {"custom"} | {c["id"] for c in cases()}: raise ValueError("Unknown mechanics case")
        filename = "request.json" if request else "playback.json" if playback else "result.json"
        return artifacts.read_json(self.folder(run_id)/case_id/filename)

def manager(app):
    with _LOCK:
        if not hasattr(app, "mechanics_qa"): app.mechanics_qa = Manager(app)
        return app.mechanics_qa
