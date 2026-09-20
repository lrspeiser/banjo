"""Controlled native material impacts and durable, inspectable regression runs.

The fixed matrix exercises the detailed lattice lane, not LiveWorld's trigger.
No prescribed fragments or material-specific expected shatter counts.
"""
from __future__ import annotations

import atexit
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import threading
import time
import uuid

import fracture_lab

ROOT = Path(__file__).resolve().parents[1]
SUITE = "banjo.material-qa.v1"
THICKNESSES_MM = (20, 40, 80)
SPEEDS_M_S = (1, 4, 12, 30)
CASE_TIMEOUT_S = 90
MAX_BYTES = 64 * 1024 * 1024
BASELINE = ROOT / "docs/evidence/material-qa-baseline.json"
# Large changes must be reviewed; piece counts are descriptive, not a
# converged oracle. These are regression bands, not experimental uncertainty.
BANDS = {
    "tile_mass_kg": (1e-9, 1e-9),
    "ball_mass_kg": (1e-9, 1e-9),
    "broken_fraction": (0.03, 0.20),
    "largest_mass_fraction": (0.10, 0.15),
    "removed_energy_j": (0.03, 0.20),
    "impulse_n_s": (0.03, 0.20),
}
_MANAGER_LOCK = threading.Lock()


def cases():
    return [{"id": f"{m}-{t}mm-{v}mps", "material": m, "thickness_mm": t,
             "speed_m_s": v}
            for m in fracture_lab.MATERIALS for t in THICKNESSES_MM for v in SPEEDS_M_S]


def select(ids=None):
    all_cases = {c["id"]: c for c in cases()}
    if ids is None:
        return list(all_cases.values())
    if (not isinstance(ids, list) or not ids or len(ids) > len(all_cases)
            or any(not isinstance(i, str) or i not in all_cases for i in ids)
            or len(set(ids)) != len(ids)):
        raise ValueError("case_ids must be a nonempty, unique list from the material QA catalog")
    return [all_cases[i] for i in ids]


def spec(case):
    return fracture_lab.validate({
        "algorithm": "lattice", "material": case["material"], "striker": "iron",
        "plate_m": [.12, .12, case["thickness_mm"] / 1000],
        "cell_m": .01, "ball_m": .04, "speed_m_s": case["speed_m_s"],
        "support": "ledges", "clearance_m": .08, "duration_s": .35,
        "failure_law": "strain-threshold", "plasticity": "off",
        "energy_flat_ms": 3, "calm_ms": 5,
    })


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def manifest():
    return {
        "schema": SUITE, "materials": list(fracture_lab.MATERIALS),
        "thicknesses_mm": list(THICKNESSES_MM), "speeds_m_s": list(SPEEDS_M_S),
        "cases": cases(), "fixture": {
            "plate_plan_m": [.12, .12], "cell_m": .01,
            "striker_material": "iron", "striker_diameter_m": .04,
            "support": "two ledges", "ledge_height_m": .08, "ledge_width_m": .02,
            "initial_gap_m": .002, "rigid_aftermath_s": .35,
            "backend": "cpu-double", "dt_factor": .5, "horizon_cells": 2,
            "failure_law": "strain-threshold", "plasticity": "off",
            "energy_flat_ms": 3, "calm_ms": 5,
        },
        "case_timeout_s": CASE_TIMEOUT_S, "regression_bands": BANDS,
        "limitations": [
            "Experimental catalog laws; passing is not material calibration.",
            "This is the detailed fracture lane, not LiveWorld trigger or building qualification.",
            "Impact input is initial speed and striker mass, not prescribed force.",
            "Contact impulse is measured; peak contact force is not exposed.",
            "Plastic flow, fatigue, thermal damage, grain and repeated impacts are not covered.",
            "The energy report is partial; no full-world conservation claim.",
            "A 20 mm sample has only two cells through its thickness; resolution convergence is not established.",
        ],
    }


def catalog(engine_path=None):
    data = manifest()
    data["fixture_hash"] = digest(data)
    exe = binary(engine_path)
    data["engine_available"] = bool(exe and exe.is_file())
    data["baseline_available"] = BASELINE.is_file()
    return data


def binary(engine_path):
    if not engine_path:
        return None
    p = Path(engine_path)
    return p.with_name("banjo_fast_lattice_run" + (".exe" if p.suffix == ".exe" else ""))


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")
    tmp.replace(path)


def read_json(path):
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("QA artifact exceeds 64 MiB")
    return json.loads(path.read_text(encoding="utf-8"),
                      parse_constant=lambda s: (_ for _ in ()).throw(ValueError("Nonfinite JSON: " + s)))


def provenance(exe):
    def git(*args):
        try:
            return subprocess.check_output(["git", *args], cwd=ROOT, text=True,
                                           stderr=subprocess.DEVNULL, timeout=5).strip()
        except (OSError, subprocess.SubprocessError):
            return None
    return {"source_commit": git("rev-parse", "HEAD"),
            "source_dirty": (None if (status := git("status", "--porcelain")) is None else bool(status)),
            "engine_sha256": hashlib.sha256(exe.read_bytes()).hexdigest(),
            "platform": os.name, "engine_name": exe.name,
            "note": "Source checkout and executable hash recorded separately; no inferred build revision."}


def command(exe, case, directory):
    s = spec(case)
    argv = fracture_lab.command("lattice", s, exe, directory / "playback.json",
                                directory / "unused-cache", directory / "native-report.json")
    # Pin the reference backend and fixture settings explicitly. No solver
    # defaults may change unnoticed through the shared UI command builder.
    argv[argv.index("--backend") + 1] = "cpu"
    argv += ["--ledge-width", ".02", "--gap", ".002", "--dt-factor", ".5",
             "--horizon", "2", "--energy-audit", "--frames", "32", "--rigid-frames", "24"]
    return argv


def metrics(report, recording):
    lattice, handoff = report["lattice"], report["handoff"]
    contact = lattice["contact"]
    broken = lattice["broken_bonds"]
    outcome = "fragmented" if handoff["components"] > 1 else "cracked" if broken else "intact"
    return {
        "outcome": outcome, "cells": report["cells"], "bonds": report["bonds"],
        "dt_s": report["dt_s"], "tile_mass_kg": report["tile_mass_kg"],
        "ball_mass_kg": report["ball_mass_kg"],
        "initial_kinetic_j": lattice["energy"]["initial_kinetic_j"],
        "broken_bonds": broken, "broken_fraction": broken / max(1, report["bonds"]),
        "components": handoff["components"],
        "largest_mass_fraction": handoff["largest_piece_mass_kg"] / report["tile_mass_kg"],
        "removed_energy_j": lattice["removed_energy_j"],
        "impulse_n_s": math.dist(contact["impulse_to_material_n_s"], [0, 0, 0]),
        "contact_events": contact["impulse_contacts"], "peak_force_n": None,
        "maximum_penetration_m": contact["maximum_penetration_m"],
        "lattice_simulated_s": lattice["simulated_s"],
        "lattice_exit_reason": lattice["exit_reason"],
        "simulated_s": report["simulated_total_s"],
        "frame_count": len(recording["frames"]),
        "came_to_rest": report["rigid"]["came_to_rest"],
        "signed_striker_loss_j": lattice["dissipated_kinetic_energy_j"]["striker_contact"],
    }


def check_run(report, recording, case):
    """Structural/numerical regressions, not a material realism verdict."""
    problems = []
    def finite(v):
        if isinstance(v, float):
            return math.isfinite(v)
        if isinstance(v, dict):
            return all(finite(x) for x in v.values())
        if isinstance(v, list):
            return all(finite(x) for x in v)
        return True
    if not finite(report) or not finite(recording):
        problems.append("nonfinite native result")
    if recording.get("schema") != "banjo.playback.v1" or recording.get("status") != "complete":
        problems.append("native recording incomplete")
    m = metrics(report, recording)
    expected = 12 * 12 * (case["thickness_mm"] // 10)
    if m["cells"] != expected:
        problems.append("native cell count differs from the fixture")
    if m["tile_mass_kg"] <= 0 or m["ball_mass_kg"] <= 0:
        problems.append("nonpositive mass")
    if not math.isclose(m["initial_kinetic_j"], .5 * m["ball_mass_kg"] * case["speed_m_s"]**2,
                        rel_tol=1e-8, abs_tol=1e-9):
        problems.append("initial striker energy differs from the requested speed")
    if not 0 <= m["broken_bonds"] <= m["bonds"] or not 1 <= m["components"] <= expected:
        problems.append("invalid damage/topology counts")
    if not 0 < m["largest_mass_fraction"] <= 1 + 1e-8 or m["removed_energy_j"] < -1e-9:
        problems.append("invalid mass fraction or fracture energy")
    if not m["contact_events"]:
        problems.append("striker never contacted the specimen")
    if report["lattice"]["node_contact"]["pair_overflow"]:
        problems.append("node contact buffer overflow")
    frames = recording.get("frames", [])
    times = [f["time_s"] for f in frames]
    if len(times) < 2 or any(b < a for a, b in zip(times, times[1:])):
        problems.append("missing or unordered playback")
    expected_ids = {"cell:" + str(i) for i in range(expected)}
    # Every cell must survive the fracture/handoff. This checks identity and
    # represented material volume, not a total energy or momentum ledger.
    for frame in frames:
        poses = frame.get("poses", [])
        ids = [p["id"] for p in poses]
        if len(set(ids)) != len(ids) or not expected_ids.issubset(ids):
            problems.append("cell identity/volume lost or duplicated in playback")
            break
    return problems


def compare(current, before):
    changes = []
    if current["outcome"] != before["outcome"]:
        changes.append(f"outcome {before['outcome']} -> {current['outcome']}")
    for key, (absolute, relative) in BANDS.items():
        a, b = current[key], before[key]
        allowed = max(absolute, abs(b) * relative)
        if abs(a - b) > allowed:
            changes.append(f"{key}: {b:.8g} -> {a:.8g} (band {allowed:.3g})")
    return changes


def run_case(exe, case, directory, cancel):
    directory.mkdir()
    argv = command(exe, case, directory)
    write_json(directory / "request.json", {"case": case, "spec": spec(case), "argv": argv})
    started = time.monotonic()
    result = {**case, "status": "error", "issues": [], "changes": [], "warnings": []}
    with (directory / "stdout.txt").open("wb") as out, (directory / "stderr.txt").open("wb") as err:
        child = subprocess.Popen(argv, stdout=out, stderr=err)
        try:
            while child.poll() is None:
                if cancel.wait(.1):
                    raise InterruptedError("Cancelled")
                if time.monotonic() - started > CASE_TIMEOUT_S:
                    raise TimeoutError(f"Native case exceeded {CASE_TIMEOUT_S}s")
            if child.returncode:
                detail = (directory / "stderr.txt").read_text(encoding="utf-8", errors="replace")[-2000:]
                raise ValueError(f"Native exit {child.returncode}: {detail}")
        finally:
            if child.poll() is None:
                child.kill()
            child.wait()
    result["wall_s"] = time.monotonic() - started
    native = read_json(directory / "native-report.json")["measurements"]
    recording = read_json(directory / "playback.json")
    result["metrics"] = metrics(native, recording)
    result["issues"] = check_run(native, recording, case)
    if result["metrics"]["signed_striker_loss_j"] < 0:
        result["warnings"].append("Signed striker-loss diagnostic is negative; not a closed energy audit.")
    result["status"] = "failed" if result["issues"] else "passed"
    return result


def run_suite(engine_path, directory, ids=None, baseline_path=BASELINE, cancel=None):
    chosen = select(ids)
    exe = binary(engine_path)
    if not exe or not exe.is_file():
        raise ValueError("Build banjo_fast_lattice_run beside the configured engine")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    cancel = cancel or threading.Event()
    fixture = manifest()
    signature = digest(fixture)
    baseline = read_json(Path(baseline_path)) if baseline_path and Path(baseline_path).is_file() else None
    if baseline_path and baseline is None:
        raise ValueError("QA baseline is missing; use --no-baseline only for a measured first run")
    if baseline and baseline.get("fixture_hash") != signature:
        raise ValueError("Baseline fixture differs; measure and review a new baseline")
    previous = {r["id"]: r for r in baseline["results"]} if baseline else {}
    if baseline and any(c["id"] not in previous for c in chosen):
        raise ValueError("Baseline does not cover every selected case")
    report = {"schema": SUITE, "id": directory.name, "fixture_hash": signature,
              "fixture": fixture, "provenance": provenance(exe), "started_unix_s": time.time(),
              "status": "running", "total": len(chosen), "completed": 0,
              "baseline_checked": bool(baseline), "results": [], "active_case": None}
    def save():
        write_json(directory / "report.json", report)
    save()
    try:
        for case in chosen:
            if cancel.is_set():
                break
            report["active_case"] = case["id"]
            save()
            start = time.monotonic()
            try:
                result = run_case(exe, case, directory / case["id"], cancel)
                if result["status"] == "passed" and baseline:
                    result["changes"] = compare(result["metrics"], previous[case["id"]]["metrics"])
                    if result["changes"]:
                        result["status"] = "review_required"
            except InterruptedError:
                result = {**case, "status": "cancelled", "issues": ["Cancelled"], "changes": []}
            except Exception as exc:
                result = {**case, "status": "error", "issues": [str(exc)], "changes": []}
            result["wall_s"] = time.monotonic() - start
            write_json(directory / case["id"] / "result.json", result)
            report["results"].append(result)
            report["completed"] += 1
            save()
        if cancel.is_set():
            report["status"] = "cancelled"
        elif any(r["status"] in ("error", "failed") for r in report["results"]):
            report["status"] = "failed"
        elif any(r["status"] == "review_required" for r in report["results"]):
            report["status"] = "review_required"
        else:
            report["status"] = "passed"
    finally:
        report["active_case"] = None
        report["finished_unix_s"] = time.time()
        save()
    return report


class Manager:
    """One isolated suite per application; never takes over its live room."""
    def __init__(self, app):
        self.app = app
        self.root = Path(app.runs_path) / "material-qa"
        self.lock = threading.Lock()
        self.thread = None
        self.cancel_event = threading.Event()
        self.run_id = None
        self.pending = None
        atexit.register(self.shutdown)

    def shutdown(self):
        self.cancel_event.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5)

    def folder(self, run_id):
        if not isinstance(run_id, str) or not re.fullmatch(r"[0-9a-f]{32}", run_id):
            raise ValueError("Invalid QA run_id")
        return self.root / run_id

    def start(self, body):
        if not isinstance(body, dict) or set(body) - {"case_ids"}:
            raise ValueError("QA run accepts only case_ids (omit for the full suite)")
        chosen = select(body.get("case_ids"))
        if not binary(self.app.engine_path) or not binary(self.app.engine_path).is_file():
            raise ValueError("Build banjo_fast_lattice_run beside the configured engine")
        with self.lock:
            if self.thread and self.thread.is_alive():
                raise ValueError("A material QA suite is already running; inspect or cancel it first")
            self.run_id = uuid.uuid4().hex
            self.cancel_event = threading.Event()
            self.pending = {"id": self.run_id, "status": "starting", "total": len(chosen),
                            "completed": 0, "results": []}
            directory = self.folder(self.run_id)
            def work():
                try:
                    run_suite(self.app.engine_path, directory, [c["id"] for c in chosen],
                              cancel=self.cancel_event)
                except Exception as exc:
                    write_json(directory / "report.json",
                               {**self.pending, "status": "failed", "error": str(exc)})
            self.thread = threading.Thread(target=work, name="banjo-material-qa", daemon=True)
            self.thread.start()
            return dict(self.pending)

    def status(self, run_id):
        path = self.folder(run_id) / "report.json"
        if path.is_file():
            report = read_json(path)
            if report.get("status") == "running" and not (
                    run_id == self.run_id and self.thread and self.thread.is_alive()):
                report["status"] = "unattached"
                report["control_note"] = "This application does not own the runner; it may still be running elsewhere."
            return report
        if run_id == self.run_id and self.pending:
            return dict(self.pending)
        raise ValueError("Unknown QA run")

    def list_runs(self):
        entries = []
        if self.root.is_dir():
            for p in self.root.iterdir():
                if p.is_dir() and re.fullmatch(r"[0-9a-f]{32}", p.name):
                    try:
                        r = self.status(p.name)
                        entries.append({k: r.get(k) for k in
                                        ("id", "status", "total", "completed", "started_unix_s")})
                    except (ValueError, OSError):
                        continue
        return {"runs": sorted(entries, key=lambda r: r.get("started_unix_s") or 0, reverse=True)[:50]}

    def case(self, run_id, case_id, playback=False):
        select([case_id])
        folder = self.folder(run_id) / case_id
        return read_json(folder / ("playback.json" if playback else "result.json"))

    def cancel(self, run_id):
        self.folder(run_id)
        with self.lock:
            if run_id != self.run_id or not self.thread or not self.thread.is_alive():
                raise ValueError("That QA run is not active")
            self.cancel_event.set()
        return {"id": run_id, "status": "cancelling"}


def manager(app):
    with _MANAGER_LOCK:
        if not hasattr(app, "material_qa"):
            app.material_qa = Manager(app)
        return app.material_qa
