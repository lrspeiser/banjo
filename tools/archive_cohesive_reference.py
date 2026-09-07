"""Archive a native development reference in the existing playground.

This does not invoke an LLM or substitute for a user's glass-drop request.
Run banjo_cohesive_sphere_probe first and pass its recording here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "playground"))
from cohesive_playback import load_and_adapt
from control_contract import default_ui


def archive_reference(source: Path, runs: Path) -> str:
    playback = load_and_adapt(source)
    job_id = uuid.uuid4().hex
    directory = runs / job_id
    directory.mkdir(parents=True, exist_ok=False)
    title = "Computed cohesive separation: low and high impact"
    explanation = ("Native development reference: a launched sphere strikes a fictional SI material at "
        "0.03 and 1 m/s. Low impact completes intact; high impact separates components then reaches the "
        "small displacement-gradient model limit. This is not a calibrated glass drop or an LLM-authored request.")
    ui = default_ui("dynamic_material_impact")
    ui["title"] = title
    ui["controls"].append({"id": "timeline", "label": "Inspect the computed sequence", "kind": "slider",
                           "action": "frame", "min": 0, "max": 1, "step": .001, "value": 0})
    plan = {"name": title, "experiment": "cohesive_sphere_reference", "duration_s": .008,
        "explanation": explanation, "ui": ui, "requirements": [],
        "steps": ["Play at 0.001x or scrub the timeline.",
                  "Click a component to inspect separation, damage and fracture work.",
                  "The high-impact case retains its final accepted state after the solver stops."]}
    report = {**playback, "cases": [{key: value for key, value in case.items() if key not in {"frames", "mesh"}}
                                   for case in playback["cases"]]}
    provenance = {"source": "native_development_reference", "native_schema": playback["native_schema"],
                  "recording_sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
    job = {"id": job_id, "status": "complete", "authoring_source": "native_development_reference",
        "message": explanation, "request_text": explanation, "plan": plan,
        "warnings": [explanation], "timing": {"model": None, "source": "native reference; no model call"},
        "cases": [{"name": title, "status": playback["status"], "report": report,
            "package": {"schema": playback["native_schema"], "source_sha256": provenance["recording_sha256"]},
            "inner_cases": [{"material_id": case["material_id"], "status": case["status"],
                             "computed_frames": len(case["frames"])} for case in playback["cases"]],
            "wall_s": sum(case["summary"]["wall_ms"] for case in playback["cases"]) / 1000,
            "native_scene": False, "playback_available": True, "provenance": provenance}]}
    for name, value in (("playback-00.json", playback), ("plan.json", plan), ("job.json", job)):
        (directory / name).write_text(json.dumps(value, allow_nan=False), encoding="utf-8")
    event = {"schema": "banjo.experiment-event.v1", "job_id": job_id, "time_unix_s": time.time(),
             "event": "native_reference_archived", **provenance}
    (directory / "events.jsonl").write_text(json.dumps(event) + "\n", encoding="utf-8")
    return job_id


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--runs", type=Path, default=ROOT / "build/playground-runs")
    args = parser.parse_args()
    print(archive_reference(args.input, args.runs))
