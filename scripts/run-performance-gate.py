#!/usr/bin/env python3
"""The performance gate: checks that are claims about the machine as much as
the engine, run apart, on a quiet machine, with the margin said.

    python scripts/run-performance-gate.py [--runs N] [--quiet-below PCT]
                                           [--wait S] LABEL=BUILD_DIR [LABEL=BUILD_DIR ...]

Today that is one check: a foreseen fracture's first run is finished inside
its warning (`banjo_live_world_tests --deadline`). For each build, given as
the directory that holds its Release programs (build/integration/Release on
Visual Studio, build/ci on Ninja), the check runs --runs times, interleaved
across the builds so a busy spell lands on all of them, each run in a fresh
process so its first run is the process's first. Before each run the machine
must be quiet -- total processor use under --quiet-below percent, waited for
up to --wait seconds -- or the run is not counted and the gate is
inconclusive (exit 2). The report says the machine, each build's compiler
and floating-point profile, and for every run the warning, the cold and warm
run costs and their margins. The requirement is the check's own and is not
changed here: exit 1 if any counted run misses it.

Compare builds only within one report: the margins belong to the machine and
the moment as much as to the build.
"""
import argparse
import json
import os
import platform
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path

LINE = re.compile(r"^\s+(1\.5 m, cold|6\.0 m|1\.5 m, warm): ([\d.eE+-]+) ms of warning, the run took "
                  r"([\d.eE+-]+) ms: margin ([\d.eE+-]+) ms")


def processor_busy(seconds=2.0):
    """Total processor use over `seconds`, in percent, or None if unknown."""
    if os.name == "nt":
        command = ("$c = Get-Counter '\\Processor(_Total)\\% Processor Time' "
                   f"-SampleInterval {max(1, int(seconds))} -MaxSamples 1; "
                   "[math]::Round($c.CounterSamples[0].CookedValue, 1)")
        try:
            out = subprocess.run(["powershell", "-NoProfile", "-Command", command],
                                 capture_output=True, text=True, timeout=30).stdout.strip()
            return float(out.splitlines()[-1])
        except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
            return None
    try:
        def sample():
            fields = [int(v) for v in Path("/proc/stat").read_text().splitlines()[0].split()[1:]]
            return sum(fields), fields[3] + (fields[4] if len(fields) > 4 else 0)
        total0, idle0 = sample()
        time.sleep(seconds)
        total1, idle1 = sample()
        return 100.0 * (1.0 - (idle1 - idle0) / max(1, total1 - total0))
    except (OSError, ValueError, IndexError):
        return None


def wait_until_quiet(limit, wait):
    start = time.time()
    busy = processor_busy()
    while busy is not None and busy >= limit and time.time() - start < wait:
        time.sleep(5)
        busy = processor_busy()
    return busy


def describe_build(release):
    profile = {}
    for candidate in (release / "banjo-fp-profile.json", release.parent / "banjo-fp-profile.json"):
        if candidate.is_file():
            profile = json.loads(candidate.read_text(encoding="utf-8"))
            break
    return profile


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("builds", nargs="+", help="LABEL=DIRECTORY holding banjo_live_world_tests")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--quiet-below", type=float, default=15.0)
    parser.add_argument("--wait", type=float, default=600.0)
    args = parser.parse_args(argv)

    builds = []
    for item in args.builds:
        label, _, directory = item.partition("=")
        release = Path(directory).resolve()
        exe = release / ("banjo_live_world_tests.exe" if os.name == "nt" else "banjo_live_world_tests")
        if not exe.is_file():
            print(f"{label}: no {exe}")
            return 2
        builds.append((label, release, exe, describe_build(release)))

    print("Performance gate: a foreseen fracture's first run is done inside its warning")
    print(f"  machine: {platform.processor() or platform.machine()}, {os.cpu_count()} hardware threads, "
          f"{platform.system()} {platform.release()}")
    for label, release, exe, profile in builds:
        said = (f"{profile.get('compiler_id', '?')} {profile.get('compiler_version', '?')}, "
                f"profile {profile.get('profile', '?')}" if profile
                else "no banjo-fp-profile.json: built without a floating-point profile")
        print(f"  {label}: {exe} ({said})")
    print(f"  {args.runs} runs each, interleaved; a run counts only when the machine is under "
          f"{args.quiet_below:g}% busy")

    results = {label: [] for label, *_ in builds}
    inconclusive = failed = False
    for run in range(args.runs):
        order = builds if run % 2 == 0 else list(reversed(builds))
        for label, release, exe, _ in order:
            busy = wait_until_quiet(args.quiet_below, args.wait)
            if busy is not None and busy >= args.quiet_below:
                print(f"  run {run} {label}: not counted, the machine stayed {busy:.0f}% busy")
                inconclusive = True
                continue
            done = subprocess.run([str(exe), "--deadline"], cwd=release, capture_output=True, text=True)
            margins = {m.group(1): (float(m.group(2)), float(m.group(3)), float(m.group(4)))
                       for m in map(LINE.match, done.stdout.splitlines()) if m}
            ok = done.returncode == 0
            failed |= not ok
            cold = margins.get("1.5 m, cold")
            warm = margins.get("1.5 m, warm")
            results[label].append({"ok": ok, "busy_before": busy, "cold": cold, "warm": warm,
                                   "high": margins.get("6.0 m")})
            print(f"  run {run} {label}: {'met' if ok else 'MISSED'}; machine {busy if busy is not None else '?'}% busy; "
                  + (f"cold {cold[1]:.0f} ms of {cold[0]:.0f} ms (margin {cold[2]:.0f} ms)" if cold else "no cold run read")
                  + (f", warm {warm[1]:.0f} ms (margin {warm[2]:.0f} ms)" if warm else ""))
            if not ok:
                print("    " + "\n    ".join(done.stdout.strip().splitlines()[-4:]))

    print("\n  build    runs   cold margin ms (min / median)   warm margin ms (min / median)")
    for label, rows in results.items():
        cold = [r["cold"][2] for r in rows if r["cold"]]
        warm = [r["warm"][2] for r in rows if r["warm"]]
        fmt = lambda v: f"{min(v):7.0f} / {statistics.median(v):7.0f}" if v else "      - /       -"
        print(f"  {label:8s} {len(rows):4d}   {fmt(cold)}              {fmt(warm)}")
    if failed:
        print("FAILED: a counted run missed the deadline")
        return 1
    if inconclusive:
        print("INCONCLUSIVE: some runs were not counted because the machine was busy")
        return 2
    print("OK: every counted run met the deadline")
    return 0


if __name__ == "__main__":
    sys.exit(main())
