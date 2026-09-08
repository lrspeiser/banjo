"""Register a banjo_fast_lattice_run recording as a playground job.

The playground server lists a job from <runs>/<32 hex id>/job.json and serves
playback-NN.json next to it to the 3D tab. banjo_fast_lattice_run writes the
banjo.playback.v1 recording directly, so this creates the job record the server
expects (the same layout the other fracture lanes' importers write) and prints
the URL that opens it. Up to four recordings become the cases of one job.

    python scripts/fast-gpu-install-playback.py RECORDING.json [MORE.json ...]
        [--name NAME ...] [--runs C:/path/to/playground-runs] [--port 8765]

Nothing here alters a recording; its embedded report becomes the case report so
the results tab shows the numbers the tool measured.
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIMIT_BYTES = 64 * 1024 * 1024


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("recordings", nargs="+", type=Path)
    parser.add_argument("--name", action="append", default=[], help="case name, one per recording, in order")
    parser.add_argument("--runs", type=Path, default=ROOT / "build" / "playground-runs")
    parser.add_argument("--title", default="GPU-parallel explicit lattice fracture lane")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if len(args.recordings) > 4:
        print("the playground shows at most four cases per job", file=sys.stderr)
        return 2
    cases = []
    texts = []
    for index, path in enumerate(args.recordings):
        text = path.read_text(encoding="utf-8")
        if len(text.encode("utf-8")) > LIMIT_BYTES:
            print(f"{path} exceeds the 64 MiB playback budget", file=sys.stderr)
            return 2
        recording = json.loads(text)
        if recording.get("schema") != "banjo.playback.v1":
            print(f"{path} is not a banjo.playback.v1 recording", file=sys.stderr)
            return 2
        report = recording.get("report", {})
        name = args.name[index] if index < len(args.name) else path.stem
        cases.append({
            "index": index,
            "name": name,
            "status": recording.get("status", "complete"),
            "requested_steps": recording.get("requested_steps", 0),
            "playback_available": True,
            "native_scene": False,
            "package": {},
            "report": report,
            "error": recording.get("error", ""),
            "warnings": [],
            "wall_s": round(float(report.get("wall_total_s", 0.0)), 3),
            "lane": "fast-gpu explicit lattice",
        })
        texts.append(text)
    job_id = uuid.uuid4().hex
    directory = args.runs.resolve() / job_id
    directory.mkdir(parents=True, exist_ok=False)
    for index, text in enumerate(texts):
        (directory / f"playback-{index:02d}.json").write_text(text, encoding="utf-8")
    first = cases[0]["report"]
    job = {
        "id": job_id,
        "status": "complete",
        "message": (f"{args.title}: {first.get('simulated_total_s', 0.0):.3f} s simulated in "
                    f"{first.get('wall_total_s', 0.0):.3f} s wall ({first.get('realtime_ratio', 0.0):.3f}x realtime) "
                    f"for the first case. Open the 3D playback tab; bond lines are drawn for the lattice phase."),
        "plan": None,
        "request_text": args.title,
        "cases": cases,
        "warnings": ["Imported recording; the playground did not author or run this scene. "
                     "Impact and fracture run on the explicit bond lattice; the pieces then settle as rigid bodies "
                     "and do not fracture again. physical_response_validated is false."],
        "timing": {},
        "installed_by": "scripts/fast-gpu-install-playback.py",
    }
    (directory / "job.json").write_text(json.dumps(job, indent=2, allow_nan=False), encoding="utf-8")
    print(f"job {job_id} written to {directory}")
    print(f"open: http://127.0.0.1:{args.port}/?job={job_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
