"""Run the native simulations and browser journeys behind Banjo's test screens.

    python scripts/verify_screen_sim.py --mode smoke --build
    python scripts/verify_screen_sim.py --mode full

Each browser test starts an isolated server and room. Evidence and a machine-
readable summary go under build/screen-sim-verification, never into a user room.
Missing Chrome or native binaries fail before any test can silently skip. The
world browser suite has one named fixture skip; any other skip fails the run.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
SUFFIX = ".exe" if os.name == "nt" else ""
EXPECTED_SKIPS = {
    "world-browser": {"this class is for the break room"},
    "world-and-workshop-browser": {"this class is for the break room"},
}


def binary_folder(build_root: Path) -> Path:
    release = build_root / "Release"
    return release if release.is_dir() else build_root


def chrome_path(asked: str | None) -> Path | None:
    candidate = asked or os.environ.get("BANJO_CHROME")
    if candidate:
        return Path(candidate).expanduser().resolve()
    if os.name == "nt":
        return Path("C:/Program Files/Google/Chrome/Application/chrome.exe")
    found = next((shutil.which(name) for name in ("google-chrome", "chromium", "chromium-browser")
                  if shutil.which(name)), None)
    return Path(found).resolve() if found else None


def tests(file: str, *names: str) -> list[str]:
    return [sys.executable, str(ROOT / "tests" / file), *names, "-v"]


def steps(mode: str, fast: Path, evidence: Path) -> list[tuple[str, list[str]]]:
    material = [sys.executable, str(ROOT / "scripts" / "material_qa.py"),
                "--engine", str(fast), "--out", str(evidence / "material-triplet"),
                "--case", "glass-40mm-12mps", "--case", "oak-40mm-12mps",
                "--case", "iron-40mm-12mps"]
    if mode == "smoke":
        return [
            ("workshop-native-cards", tests("workshop_screen_sim_tests.py")),
            ("game-screen-navigation", tests("workshop_navigation_tests.py")),
            ("workshop-browser", tests(
                "workshop_browser_tests.py",
                "WorkshopBrowserRegression.test_the_test_tab_offers_one_test_for_everything_it_can_make",
                "WorkshopBrowserRegression.test_a_load_says_whether_it_held_and_by_how_much",
                "WorkshopBrowserRegression.test_no_simulation_response_is_a_visible_failure_not_a_success",
                "WorkshopBrowserRegression.test_debug_page_lists_all_qa_suites")),
            ("world-browser", tests(
                "world_page_journey_tests.py",
                "ARoomWhereThingsStandOnTheGround.test_the_room_is_lit_with_a_sun_that_casts")),
            ("material-qa-native", material),
            ("mechanics-qa-native", tests(
                "physics_trials_tests.py",
                "NativeProtocol.test_platform_tools_run_and_return_the_same_native_evidence")),
            ("tool-qa-native", tests(
                "tool_qa_tests.py",
                "Native.test_six_real_trials_show_motion_contact_and_accounted_rock_work")),
        ]
    return [
        ("workshop-native-cards", tests("workshop_screen_sim_tests.py")),
        ("game-screen-navigation", tests("workshop_navigation_tests.py")),
        ("workshop-bench", tests("workshop_bench_tests.py")),
        ("workshop-native-room", tests("workshop_test_room_tests.py")),
        # world_page_journey_tests imports WorkshopBrowserRegression and
        # unittest.main runs it too. Keep one browser pass, then assert below
        # that the imported Workshop cases really ran.
        ("world-and-workshop-browser", tests("world_page_journey_tests.py")),
        ("material-qa-contract", tests("material_qa_tests.py")),
        ("material-qa-native", material),
        ("mechanics-qa", tests("physics_trials_tests.py")),
        ("tool-qa", tests("tool_qa_tests.py")),
        ("fabrication-qa", tests("fabrication_qa_tests.py")),
    ]


def run(label: str, command: list[str], env: dict[str, str], evidence: Path,
        index: int) -> dict[str, object]:
    log = evidence / f"{index:02d}-{label}.log"
    print(f"\n[{label}] {' '.join(command)}", flush=True)
    started = time.monotonic()
    with log.open("w", encoding="utf-8") as output:
        process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                   errors="replace", bufsize=1)
        assert process.stdout is not None
        skipped: list[str] = []
        saw_workshop = False
        for line in process.stdout:
            output.write(line)
            # Windows terminals may use cp1252 even when a browser test prints
            # a Unicode replacement character. Keep the UTF-8 log complete and
            # make console progress loss-tolerant rather than aborting the run.
            console = sys.stdout.encoding or "utf-8"
            print(line.encode(console, errors="backslashreplace").decode(console),
                  end="", flush=True)
            match = re.search(r"\.\.\. skipped '([^']+)'", line)
            if match:
                skipped.append(match.group(1))
            if "workshop_browser_tests.WorkshopBrowserRegression" in line:
                saw_workshop = True
        code = process.wait()
    unexpected = [reason for reason in skipped if reason not in EXPECTED_SKIPS.get(label, set())]
    if code == 0 and unexpected:
        code = 3  # Missing tools and other unplanned skips are incomplete.
    if code == 0 and label == "world-and-workshop-browser" and not saw_workshop:
        code = 4  # The combined suite stopped including Workshop browser tests.
    elapsed = round(time.monotonic() - started, 2)
    print(f"[{label}] {'PASS' if code == 0 else 'FAIL'} in {elapsed} s", flush=True)
    return {"name": label, "command": command, "exit_code": code,
            "elapsed_s": elapsed, "log": str(log), "skips": skipped,
            "unexpected_skips": unexpected,
            "workshop_browser_included": saw_workshop if label == "world-and-workshop-browser" else None}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("smoke", "full"), default="smoke")
    parser.add_argument("--build-dir", type=Path, default=ROOT / "build" / "integration",
                        help="Configured CMake build directory (Release binaries on Windows)")
    parser.add_argument("--build", action="store_true", help="Build required native targets first")
    parser.add_argument("--chrome", help="Chrome executable; defaults to BANJO_CHROME or system Chrome")
    parser.add_argument("--out", type=Path, help="Evidence directory (default: timestamp under build/)")
    args = parser.parse_args()
    build_root = args.build_dir.resolve()
    if not (build_root / "CMakeCache.txt").is_file():
        parser.error(f"Configure a separate CMake build first: {build_root}")
    folder = binary_folder(build_root)
    binaries = {name: folder / f"{name}{SUFFIX}" for name in
                ("banjo_live_world_run", "banjo_platform_cli", "banjo_network_lab",
                 "banjo_fast_lattice_run")}
    library = folder / ("banjo.dll" if os.name == "nt" else "libbanjo.so")
    evidence = (args.out.resolve() if args.out else
                ROOT / "build" / "screen-sim-verification" / time.strftime("%Y%m%d-%H%M%S"))
    evidence.mkdir(parents=True, exist_ok=True)
    chrome = chrome_path(args.chrome)
    if chrome is None or not chrome.is_file():
        parser.error("Chrome is required for the screen checks; pass --chrome or BANJO_CHROME")

    env = {**os.environ, "BANJO_BUILD_DIR": str(folder),
           "BANJO_LIVE_ENGINE": str(binaries["banjo_live_world_run"]),
           "BANJO_TRIAL_ENGINE": str(binaries["banjo_live_world_run"]),
           "BANJO_CHROME": str(chrome), "BANJO_BROWSER_TESTS": "required",
           "OPENAI_API_KEY": "", "PYTHONIOENCODING": "utf-8"}
    if library.is_file():
        env["BANJO_LIBRARY"] = str(library)
    results: list[dict[str, object]] = []
    if args.build:
        command = ["cmake", "--build", str(build_root), "--config", "Release", "--parallel", "4",
                   "--target", "banjo_c", *binaries.keys()]
        results.append(run("native-build", command, env, evidence, 0))
        if results[-1]["exit_code"] != 0:
            return 1
    missing = [str(path) for path in (*binaries.values(), library) if not path.is_file()]
    if missing:
        parser.error("Build the native targets first (or pass --build): " + ", ".join(missing))
    env["BANJO_LIBRARY"] = str(library)
    for index, (label, command) in enumerate(steps(args.mode, binaries["banjo_fast_lattice_run"], evidence), 1):
        results.append(run(label, command, env, evidence, index))
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                              text=True, check=False).stdout.strip()
    report = {"schema": "banjo.screen-sim-verification.v1", "mode": args.mode,
              "revision": revision, "build_dir": str(build_root), "chrome": str(chrome),
              "results": results, "passed": all(row["exit_code"] == 0 for row in results)}
    summary = evidence / "summary.json"
    summary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"\nEvidence: {summary}", flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
