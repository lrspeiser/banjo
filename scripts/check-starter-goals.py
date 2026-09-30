"""Run a bounded player agent in isolated generated maps and save its evidence."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
import starter_goals_tests as goals


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worlds", type=int, default=3)
    parser.add_argument("--out", type=Path, default=ROOT / "build/starter-goals/playthrough.json")
    args = parser.parse_args()
    if not 1 <= args.worlds <= 16: parser.error("--worlds must be 1..16")
    if not goals.hub.RUNNER.is_file() or not goals.hub.ENGINE.is_file():
        parser.error("Set BANJO_LIVE_ENGINE to the built native runner; skipped tests cannot certify a goal")
    report = {"schema": "banjo.goal-playthrough.v1", "environment": platform.platform(),
              "revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
              "dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip()),
              "planner": "bounded evidence-driven reference agent; not an LLM", "runs": []}
    client = goals.StarterGoals(); client.setUp()
    failed = False
    try:
        for index in range(args.worlds):
            started = time.monotonic()
            world = client.post("/api/worlds", {"name": f"Goal check {index + 1}"})["id"]
            player = client.join(world, "Goal checker")
            client.players = {world: player}
            opened = client.post("/api/world/open", {}, world)
            try:
                result = goals.play_first_camp(client, world, player["token"])
            except Exception as error:
                failed = True
                result = {"complete": False, "error": str(error)}
            report["runs"].append({"world": world, "terrain": opened["spec"].get("terrain"),
                                   "seconds": round(time.monotonic() - started, 3), **result})
            print(f"Map {index + 1}: {'PASS' if result['complete'] else 'FAIL'}")
    finally:
        client.tearDown()
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Evidence: {args.out}")
    return int(failed)


if __name__ == "__main__": sys.exit(main())
