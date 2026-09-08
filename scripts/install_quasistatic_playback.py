"""Install a banjo_quasistatic_probe recording as a playground job.

The playground lists a job from ``build/playground-runs/<id>/job.json`` and
serves ``playback-00.json`` next to it to the 3D tab. The probe writes the
recording directly (it does not go through banjo_platform_cli), so this script
creates the job record the server expects and prints the URL that opens it.

    python scripts/install_quasistatic_playback.py RECORDING.json [--report REPORT.json]
        [--name NAME] [--runs build/playground-runs] [--port 8765]

Nothing here alters the recording; the report the probe wrote is attached as
the case report so the results tab shows the same numbers the probe printed.
"""

from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recording", type=Path)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--name", default="Quasi-static fracture: glass tile struck by an iron ball")
    parser.add_argument("--runs", type=Path, default=ROOT / "build/playground-runs")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    recording_text = args.recording.read_text(encoding="utf-8")
    recording = json.loads(recording_text)
    if recording.get("schema") != "banjo.playback.v1":
        raise SystemExit("not a banjo.playback.v1 recording")
    if len(recording_text.encode("utf-8")) > 64 * 1024 * 1024:
        raise SystemExit("recording exceeds the 64 MiB playback budget")
    report = recording.get("report", {})
    if args.report is not None:
        report = {**report, "probe": json.loads(args.report.read_text(encoding="utf-8"))}
        # The event log is large and the results tab does not need it.
        report["probe"].get("quasistatic", {}).pop("event_log", None)
        if "reference" in report["probe"]:
            report["probe"]["reference"].pop("steps_log", None)

    job_id = uuid.uuid4().hex
    directory = args.runs / job_id
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "playback-00.json").write_text(recording_text, encoding="utf-8")
    realtime = report.get("realtime", {})
    case = {
        "index": 0,
        "name": args.name,
        "status": recording.get("status", "complete"),
        "requested_steps": recording.get("requested_steps", 0),
        "native_scene": False,
        "report": report,
        "playback_available": True,
        "wall_s": round(float(realtime.get("wall_with_recording_s", 0.0)), 3),
        "lane": "quasi-static",
    }
    if recording.get("error"):
        case["error"] = recording["error"]
    job = {
        "id": job_id,
        "status": "complete",
        "message": (f"Quasi-static fracture lane: {realtime.get('simulated_s', 0.0):.3f} s simulated in "
                    f"{realtime.get('wall_with_recording_s', 0.0):.3f} s wall "
                    f"({realtime.get('ratio_with_recording', 0.0):.3f}x realtime). Open the 3D playback tab."),
        "plan": None,
        "request_text": args.name,
        "cases": [case],
        "warnings": ["The quasi-static lane computes the crack pattern from static equilibrium; "
                     "the sub-frame transient is not simulated. Material realism is not validated."],
        "timing": {},
        "installed_by": "scripts/install_quasistatic_playback.py",
    }
    (directory / "job.json").write_text(json.dumps(job, indent=2, allow_nan=False), encoding="utf-8")
    print(f"installed job {job_id} in {directory}")
    print(f"open: http://127.0.0.1:{args.port}/?job={job_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
