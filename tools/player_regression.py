"""Run the player regression (tests/player_regression_tests.py) and say what it found.

    python tools/player_regression.py                 # every journey
    python tools/player_regression.py dig walk        # the journeys whose names hold these words
    python tools/player_regression.py --build C:/cs/build/w/Release

It finds the engine for you: --build, else BANJO_BUILD_DIR, else BANJO_LIVE_ENGINE's
folder, else build/integration/Release. It needs banjo_live_world_run and
banjo_platform_cli there, and Chrome (BANJO_CHROME, or Chrome's usual place on
Windows). Each journey starts a server of its own on a free port, in this
process, and never touches anybody else's.

Run it on a machine that is not busy: the journeys measure what a player would
feel, and a server starved of the processor feels slow for reasons of its own.
A failure under load is not a finding until it fails again on its own.

Afterwards it prints each journey's problems from build/player-regression/,
where each journey also leaves its numbers (<journey>.json) and a picture of
the page as it ended (<journey>.png). See docs/player-regression.md.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build" / "player-regression"
SUFFIX = ".exe" if os.name == "nt" else ""
JOURNEYS = ("dig_in_one_spot", "walk", "operate_the_rover", "workshop_change_and_make", "point_and_click")


def find_build(given: str | None) -> Path | None:
    candidates = [given, os.environ.get("BANJO_BUILD_DIR"),
                  str(Path(os.environ["BANJO_LIVE_ENGINE"]).parent) if os.environ.get("BANJO_LIVE_ENGINE") else None,
                  str(ROOT / "build" / "integration" / "Release")]
    for folder in filter(None, candidates):
        if (Path(folder) / f"banjo_live_world_run{SUFFIX}").is_file():
            return Path(folder).resolve()
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("words", nargs="*", help="run only the journeys whose names hold these words")
    parser.add_argument("--build", help="the folder with banjo_live_world_run and banjo_platform_cli")
    args = parser.parse_args(argv)
    build = find_build(args.build)
    if build is None:
        print("No engine found: pass --build <folder with banjo_live_world_run>, or set BANJO_BUILD_DIR.")
        return 2
    chosen = [j for j in JOURNEYS if not args.words or any(w.lower() in j for w in args.words)]
    if not chosen:
        print(f"No journey matches {args.words}; the journeys are: {', '.join(JOURNEYS)}")
        return 2
    env = dict(os.environ, BANJO_LIVE_ENGINE=str(build / f"banjo_live_world_run{SUFFIX}"),
               BANJO_PLATFORM_ENGINE=str(build / f"banjo_platform_cli{SUFFIX}"), BANJO_BUILD_DIR=str(build),
               BANJO_BROWSER_TESTS=os.environ.get("BANJO_BROWSER_TESTS", "required"))
    library = build / ("banjo.dll" if os.name == "nt" else "libbanjo.so")
    if library.is_file():
        env.setdefault("BANJO_LIBRARY", str(library))
    began = time.monotonic()
    for journey in chosen:
        (OUT / f"{journey}.json").unlink(missing_ok=True)
    tests = [f"PlayerJourney.test_{j}" for j in chosen]
    print(f"Playing {len(chosen)} journey(s) on the engine in {build}", flush=True)
    code = subprocess.call([sys.executable, str(ROOT / "tests" / "player_regression_tests.py"), "-v", *tests],
                           cwd=str(ROOT), env=env)
    print(f"\nPlayer regression, {time.monotonic() - began:.0f} s in all:")
    for journey in chosen:
        path = OUT / f"{journey}.json"
        if not path.is_file():
            print(f"  {journey}: did not run (see the output above)")
            continue
        report = json.loads(path.read_text(encoding="utf-8"))
        problems = report.get("problems") or []
        if not report.get("passed") and not problems:
            problems = ["it stopped before the end: see the error above"]
        print(f"  {'ok  ' if report.get('passed') else 'FAIL'} {journey} ({report.get('wall_s')} s)")
        for problem in problems:
            print(f"         - {problem}")
    print(f"Numbers and pictures: {OUT}")
    return code


if __name__ == "__main__":
    sys.exit(main())
