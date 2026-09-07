"""Register a banjo.playback.v1 recording as a playground job so the 3D tab can play it.

The playground server discovers archived jobs under its --runs directory:
<runs>/<32 hex id>/job.json plus playback-NN.json per case. This writes exactly
that layout for one or more recordings produced by banjo_modal_fracture_record
(or any tool that emits banjo.playback.v1), and prints the URL to open.

    python scripts/import-playback.py --runs build/playground-runs \
        --name "Modal lane: 8x8x2 glass, 16 m/s" build/runs/headline/modal-8x8x2-16.json \
        --name "Implicit reference: 8x8x2 glass, 16 m/s" build/runs/headline/implicit-8x8x2-16.json

Nothing is simulated here; the recording is copied verbatim.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("recordings", nargs="+", type=Path)
    parser.add_argument("--name", action="append", default=[], help="case name, one per recording, in order")
    parser.add_argument("--runs", type=Path, default=ROOT / "build/playground-runs")
    parser.add_argument("--title", default="Precomputed-basis fracture lane")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if len(args.recordings) > 4:
        print("the playground shows at most four cases per job", file=sys.stderr)
        return 2
    job_id = uuid.uuid4().hex
    directory = args.runs.resolve() / job_id
    directory.mkdir(parents=True, exist_ok=False)
    cases = []
    for index, path in enumerate(args.recordings):
        recording = json.loads(path.read_text(encoding="utf-8"))
        if recording.get("schema") != "banjo.playback.v1":
            print(f"{path} is not a banjo.playback.v1 recording", file=sys.stderr)
            return 2
        target = directory / f"playback-{index:02d}.json"
        shutil.copyfile(path, target)
        report = recording.get("report", {})
        name = args.name[index] if index < len(args.name) else path.stem
        cases.append({
            "name": name,
            "status": recording.get("status", "complete"),
            "playback_available": True,
            "native_scene": False,
            "package": {},
            "report": report,
            "error": recording.get("error", ""),
            "warnings": [],
        })
    job = {
        "id": job_id,
        "status": "complete",
        "message": (f"{args.title}: imported recordings. Broken bonds, pieces and timings are in each case card; "
                    "physical_response_validated is false."),
        "plan": None,
        "cases": cases,
        "warnings": ["Imported recording; the playground did not author or run this scene."],
        "timing": {},
    }
    (directory / "job.json").write_text(json.dumps(job, indent=2, allow_nan=False), encoding="utf-8")
    print(f"job {job_id} written to {directory}")
    print(f"open http://127.0.0.1:{args.port}/?job={job_id} with the playground server started as")
    print(f"  python playground/server.py --runs {args.runs}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
