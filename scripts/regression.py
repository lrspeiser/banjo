"""Discover/build/run registered tests without killing unrelated processes.

List mode is read-only. Check mode fails on missing selected executables or
required native artifacts; neither mode runs a build or test. Actual execution
builds first unless --no-build is passed, writes a discovery manifest, and keeps
CTest's complete JUnit results. Long/performance tests require --all.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
LEGACY_LONG = {"banjo_material_showcase_tests", "banjo_contact_capacity_tests",
               "banjo_network_runtime_tests", "banjo_network_skin_tests"}
ARTIFACT_ENV = {"BANJO_LIBRARY", "BANJO_LIVE_ENGINE", "BANJO_TRIAL_ENGINE"}


def properties(test):
    return {p["name"]: p["value"] for p in test.get("properties", [])}


def describe(discovery, *, include_all=False, pattern=None):
    selected, excluded = [], []
    expression = re.compile(pattern) if pattern else None
    for test in discovery["tests"]:
        props = properties(test)
        labels = props.get("LABELS", [])
        reasons = []
        if expression and not expression.search(test["name"]):
            reasons.append("name filter")
        if not include_all and (test["name"] in LEGACY_LONG or set(labels) & {"long", "performance"}):
            reasons.append("extended profile")
        if props.get("DISABLED"):
            reasons.append("disabled by configuration")
        row = {"name": test["name"], "labels": labels, "command": test.get("command", []),
               "timeout_s": props.get("TIMEOUT"), "issues": []}
        command = row["command"]
        if not command:
            row["issues"].append("CTest did not resolve an executable; build the target")
        elif not Path(command[0]).is_file() and shutil.which(command[0]) is None:
            row["issues"].append("Test executable is missing")
        environment = list(props.get("ENVIRONMENT", []))
        if command[1:3] == ['-E', 'env']:
            environment.extend(command[3:])
        for entry in environment:
            name, _, value = entry.partition("=")
            if name in ARTIFACT_ENV and value and not Path(value).is_file():
                row["issues"].append(name + " artifact is missing")
        if reasons:
            row["excluded_because"] = reasons
            excluded.append(row)
        else:
            selected.append(row)
    return {"schema": "banjo.test-registry.v1", "profile": "all" if include_all else "ordinary",
            "selected": selected, "excluded": excluded,
            "ready": bool(selected) and not any(t["issues"] for t in selected)}


def discover(build, config, *, include_all=False, pattern=None):
    result = subprocess.run(["ctest", "--test-dir", str(build), "-C", config,
                             "--show-only=json-v1"], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", check=True)
    return describe(json.loads(result.stdout), include_all=include_all, pattern=pattern)


def owned_run(command, *, env, cwd):
    """Stop only the child tree created here, and only when interrupted."""
    apart = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    child = subprocess.Popen(command, env=env, cwd=cwd, **apart)
    try:
        return child.wait()
    except KeyboardInterrupt:
        if child.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(child.pid)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            else:
                try:
                    os.killpg(child.pid, signal.SIGTERM)
                    child.wait(timeout=5)
                except ProcessLookupError:
                    pass
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
            child.wait()
        return 130


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", type=Path, default=ROOT / "build/integration")
    parser.add_argument("--config", default="Release")
    parser.add_argument("--all", action="store_true", dest="include_all")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--list", action="store_true")
    mode.add_argument("--check", action="store_true")
    parser.add_argument("--no-build", action="store_true")
    parser.add_argument("--tests", help="CTest name regular expression")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    build = args.build_dir.resolve()
    env = os.environ.copy()
    if not (build / "CMakeCache.txt").is_file():
        parser.error("Configure a separate CMake build directory first: " + str(build))
    if args.tests:
        try:
            re.compile(args.tests)
        except re.error as error:
            parser.error(str(error))
    if not (args.list or args.check or args.no_build):
        code = owned_run(["cmake", "--build", str(build), "--config", args.config,
                          "--parallel", "4"], env=env, cwd=ROOT)
        if code:
            return code
    report = discover(build, args.config, include_all=args.include_all, pattern=args.tests)
    report.update(build_dir=str(build), configuration=args.config)
    if args.list or args.check:
        print(json.dumps(report, indent=2))
        return int(args.check and not report["ready"])
    output = (args.output_dir or (build / "regression" / str(time.time_ns()))).resolve()
    output.mkdir(parents=True, exist_ok=True)
    (output / "discovery.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if not report["ready"]:
        print("Tests are not ready; inspect " + str(output / "discovery.json"), file=sys.stderr)
        return 2
    library = next((p for p in (build / args.config / "banjo.dll", build / "banjo.dll",
                               build / "libbanjo.so", build / "libbanjo.dylib") if p.is_file()), None)
    if library:
        env["BANJO_LIBRARY"] = str(library)
    names = "^(" + "|".join(re.escape(t["name"]) for t in report["selected"]) + ")$"
    code = owned_run(["ctest", "--test-dir", str(build), "-C", args.config,
                      "--output-on-failure", "--no-tests=error", "-R", names,
                      "--output-junit", str(output / "results.xml")], env=env, cwd=ROOT)
    (output / "run.json").write_text(json.dumps({"exit_code": code,
        "selected": len(report["selected"]), "excluded": len(report["excluded"]),
        "full_profile": args.include_all and not args.tests,
        "junit": "results.xml"}) + "\n", encoding="utf-8")
    print("Regression artifacts: " + str(output))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
