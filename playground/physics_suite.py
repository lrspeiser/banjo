"""Predict-then-measure regression suite for the Banjo physics engine.

The question this answers is not "did the code run" but "did the engine do what
physics says it should". Each case runs in four sealed stages:

  1. AUTHOR   the scene is built from a declared, checked-in specification.
  2. PREDICT  before the engine runs, the model is shown the scene and states
              what should happen, as machine-checkable assertions. The
              prediction is written to disk and hashed at this point, so it
              cannot be revised once the answer is known.
  3. MEASURE  the engine runs. An at-rest control of the same scene runs too,
              so a result can be marked contaminated rather than passed.
  4. GRADE    the sealed prediction is compared against the measurement.

Two independent verdicts are reported and never merged:

  * INVARIANTS are deterministic and need no model at all. Energy appearing in a
    scene that started at rest is wrong whatever any model believes. These are
    the real oracle.
  * PREDICTION is the model's expectation of the qualitative outcome. This
    catches "runs cleanly but behaves nothing like glass", which no invariant
    encodes.

A case passes only when both agree. A model that predicts wrongly, and a model
that grades its own wrong prediction generously, both show up as a disagreement
between the two columns, which is why they are kept apart.

Without an API key the suite still runs and reports the invariant column, which
is the half that does not depend on anyone's opinion.

Usage:
    python playground/physics_suite.py
    python playground/physics_suite.py --filter rest --no-model
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "examples" / "authoring"))

from banjo_authoring import EngineCLI, EngineError, catalog, make_object, make_package, write_package
from trust import at_rest_control_package, control_verdict, energy_verdict, resolution_verdict

PANEL_PRESET = {"glass": "glass_panel", "oak": "wood_panel", "iron": "iron_panel"}
NEGLIGIBLE_J = 1.0e-6
GROUND = {"half_length_m": 2.0, "half_width_m": 2.0, "friction": 0.4}


def rewrite_package(package, path):
    """write_package refuses to overwrite, so a re-run needs a clean slate."""
    path.unlink(missing_ok=True)
    write_package(package, path)


# --------------------------------------------------------------------------
# Scene construction
# --------------------------------------------------------------------------

def _panel(material, mesh, pin, object_id=1, position=(0.0, 0.5, 0.0)):
    return make_object(PANEL_PRESET[material], object_id, material=material,
                       name=f"{material} panel", position_m=list(position),
                       velocity_m_s=[0.0, 0.0, 0.0], spin_rad_s=[0.0, 0.0, 0.0],
                       resolution=mesh, pin_boundary=pin)


def _ball(object_id, material, position, velocity, spin=(0.0, 0.0, 0.0)):
    return make_object("iron_ball", object_id, material=material, name=f"{material} ball",
                       position_m=list(position), velocity_m_s=list(velocity),
                       spin_rad_s=list(spin))


def _package(objects, materials, name, dt, gravity, ground):
    return make_package(objects,
                        materials=[m for m in catalog()["materials"] if m["id"] in materials],
                        name=name, fixed_dt_s=dt, gravity_m_s2=tuple(gravity), ground=ground)


# --------------------------------------------------------------------------
# Deterministic invariants. These are the oracle; no model is consulted.
# Each returns (ok, detail); ok of None means the check does not apply.
# --------------------------------------------------------------------------

def inv_all_finite(report, control, spec):
    bad = [f"{k} is {v}" for k, v in report.items()
           if isinstance(v, float) and not math.isfinite(v)]
    return (not bad, "all reported quantities are finite" if not bad else "; ".join(bad))


def inv_no_energy_from_rest(report, control, spec):
    """A scene that starts at rest and is never driven must stay at zero energy."""
    if not spec.get("starts_at_rest"):
        return (None, "not applicable: this scene is driven")
    created = max(abs(report.get("elastic_energy_j") or 0.0),
                  abs(report.get("mechanical_energy_j") or 0.0))
    return (created <= NEGLIGIBLE_J, f"energy from rest = {created:.4g} J (limit {NEGLIGIBLE_J:g})")


def inv_no_breakage_from_rest(report, control, spec):
    if not spec.get("starts_at_rest"):
        return (None, "not applicable: this scene is driven")
    broken = report.get("broken_links") or 0
    return (broken == 0, f"{broken} bonds broke with nothing acting on the lattice")


def inv_breakage_bounded(report, control, spec):
    broken, links = report.get("broken_links"), report.get("links")
    if not isinstance(broken, (int, float)) or not isinstance(links, (int, float)) or not links:
        return (None, "no link counts reported")
    return (0 <= broken <= links, f"{broken} of {links} bonds broken")


def inv_state_valid(report, control, spec):
    value = report.get("state_valid")
    if value is None:
        return (None, "engine reported no state_valid flag")
    return (bool(value), f"state_valid = {value}")


def inv_control_clean(report, control, spec):
    """The paired at-rest control decides whether any of this is attributable."""
    if control is None:
        return (None, "rigid-only scene: no lattice to shake itself apart")
    return (control["clean"], control["summary"])


INVARIANTS = [
    ("all_finite", inv_all_finite),
    ("no_energy_from_rest", inv_no_energy_from_rest),
    ("no_breakage_from_rest", inv_no_breakage_from_rest),
    ("breakage_bounded", inv_breakage_bounded),
    ("state_valid", inv_state_valid),
    ("at_rest_control_clean", inv_control_clean),
]


# --------------------------------------------------------------------------
# The battery. Each case names what it probes, so a failure says something.
# --------------------------------------------------------------------------

def build_cases():
    cases = []

    # Group 1: the engine must do nothing when nothing is asked of it.
    for material in ("glass", "oak", "iron"):
        for mesh, label in (([6, 9, 2], "coarse"), ([10, 15, 4], "fine")):
            cases.append({
                "id": f"rest_{material}_{label}",
                "group": "at rest",
                "question": f"A {material} panel floats motionless in a vacuum. "
                            "There is no gravity, no ground and nothing touching it.",
                "starts_at_rest": True,
                "duration_s": 0.5,
                "build": lambda m=material, k=mesh: _package(
                    [_panel(m, k, pin=False)], [m], f"At rest {m}",
                    1.0 / 4800.0, (0.0, 0.0, 0.0), None),
            })

    # Group 2: rigid controls, where the engine is known to converge.
    cases.append({
        "id": "freefall_rigid",
        "group": "rigid control",
        "question": "An iron ball is released in gravity with no ground beneath it.",
        "starts_at_rest": False,
        "duration_s": 0.5,
        "build": lambda: _package([_ball(1, "iron", (0.0, 2.0, 0.0), (0.0, 0.0, 0.0))],
                                  ["iron"], "Rigid freefall", 1.0 / 960.0,
                                  (0.0, -9.81, 0.0), None),
    })
    cases.append({
        "id": "zero_g_drift",
        "group": "rigid control",
        "question": "Two iron balls drift apart in zero gravity. No forces act and they never touch.",
        "starts_at_rest": False,
        "duration_s": 0.5,
        "build": lambda: _package([_ball(1, "iron", (-0.5, 1.0, 0.0), (1.0, 0.0, 0.0)),
                                   _ball(2, "iron", (0.5, 2.0, 0.0), (-1.0, 0.0, 0.0))],
                                  ["iron"], "Zero-g drift", 1.0 / 960.0,
                                  (0.0, 0.0, 0.0), None),
    })
    cases.append({
        "id": "rigid_bounce",
        "group": "rigid control",
        "question": "An iron ball is driven down onto a solid ground plane at 2 m/s and rebounds.",
        "starts_at_rest": False,
        "duration_s": 1.0,
        "build": lambda: _package([_ball(1, "iron", (0.0, 0.3, 0.0), (0.0, -2.0, 0.0))],
                                  ["iron"], "Rigid bounce", 1.0 / 960.0,
                                  (0.0, -9.81, 0.0), GROUND),
    })

    # Group 3: material response under identical impact.
    for material in ("glass", "oak", "iron"):
        for speed in (2.0, 12.0):
            cases.append({
                "id": f"impact_{material}_{speed:g}ms",
                "group": "impact",
                "question": f"An 80 mm iron ball strikes a clamped {material} panel "
                            f"(0.24 x 0.36 x 0.04 m) at {speed:g} m/s.",
                "starts_at_rest": False,
                "duration_s": 0.3,
                "build": lambda m=material, s=speed: _package(
                    [_panel(m, [6, 9, 2], pin=True),
                     _ball(2, "iron", (0.0, 0.5, 0.2), (0.0, 0.0, -s))],
                    [m, "iron"], f"{m} impact at {s:g} m/s",
                    1.0 / 1920.0, (0.0, -9.81, 0.0), GROUND),
            })

    return cases


# --------------------------------------------------------------------------
# Model prediction and grading
# --------------------------------------------------------------------------

PREDICT_SYSTEM = (
    "You are a physicist reviewing a rigid-body and lattice-fracture simulation before it runs. "
    "You are given a scene description and the exact package the engine will execute. State what "
    "physics says should happen. Be decisive and quantitative where you can, and say plainly when "
    "a quantity is not determined by the setup. You will be graded on whether the engine matched "
    "you, so do not hedge into unfalsifiability."
)

PREDICT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "expectations"],
    "properties": {
        "summary": {"type": "string"},
        "expectations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["claim", "measurable", "confidence"],
                "properties": {
                    "claim": {"type": "string"},
                    "measurable": {"type": "string"},
                    "confidence": {"type": "string", "enum": ["certain", "likely", "uncertain"]},
                },
            },
        },
    },
}

GRADE_SYSTEM = (
    "You are grading a physics simulation against a prediction that was sealed before the run. "
    "You are given that prediction and the engine's measured report. For each expectation, say "
    "whether the measurement supports it, contradicts it, or does not determine it. Judge only "
    "what the numbers show. Do not excuse a contradiction because the engine is experimental, and "
    "do not credit an expectation the report does not actually address."
)

GRADE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["verdict", "reasoning", "judgements"],
    "properties": {
        "verdict": {"type": "string",
                    "enum": ["matched", "partly_matched", "contradicted", "undetermined"]},
        "reasoning": {"type": "string"},
        "judgements": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["claim", "outcome", "evidence"],
                "properties": {
                    "claim": {"type": "string"},
                    "outcome": {"type": "string",
                                "enum": ["supported", "contradicted", "undetermined"]},
                    "evidence": {"type": "string"},
                },
            },
        },
    },
}


def structured_call(api_key, model, system, user, schema, name, timeout_s=180):
    from urllib import error, request
    body = {
        "model": model,
        "input": [{"role": "system", "content": system},
                  {"role": "user", "content": user}],
        "text": {"format": {"type": "json_schema", "name": name,
                            "schema": schema, "strict": True}},
    }
    req = request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
    try:
        with request.urlopen(req, timeout=timeout_s) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        raise RuntimeError(f"model request failed: {exc.code} {exc.read()[:300]!r}") from exc
    except (error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"model request failed: {exc}") from exc
    for item in payload.get("output", []):
        for chunk in item.get("content", []):
            if chunk.get("type") == "output_text":
                return json.loads(chunk["text"])
    raise RuntimeError("model returned no structured output")


def report_digest(report):
    """The measured fields a grader should see, without the bulk."""
    keep = ("broken_links", "damaged_links", "links", "cells", "connected_components",
            "initial_energy_j", "mechanical_energy_j", "elastic_energy_j", "fracture_work_j",
            "plastic_work_j", "unseparated_energy_change_j", "energy_residual_j",
            "maximum_observed_axial_strain", "summed_spring_impulse_n_s", "state_valid", "ticks")
    digest = {k: report[k] for k in keep if k in report}
    if "temporal_resolution" in report:
        digest["temporal_resolution"] = report["temporal_resolution"]
    return digest


# --------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------

def run_case(case, engine, outdir, api_key, model):
    record = {"id": case["id"], "group": case["group"], "question": case["question"],
              "starts_at_rest": bool(case.get("starts_at_rest"))}
    package = case["build"]()
    steps = max(1, round(case["duration_s"] / package["fixed_dt_s"]))
    record["steps"] = steps
    package_path = outdir / f"{case['id']}.package.json"
    rewrite_package(package, package_path)

    # STAGE 2: seal the prediction before anything is measured.
    if api_key:
        try:
            prediction = structured_call(
                api_key, model, PREDICT_SYSTEM,
                json.dumps({"scene": case["question"], "duration_s": case["duration_s"],
                            "package": package}, indent=1),
                PREDICT_SCHEMA, "prediction")
        except (RuntimeError, json.JSONDecodeError) as exc:
            prediction = {"error": str(exc)}
    else:
        prediction = {"skipped": "no OPENAI_API_KEY; invariant column only"}
    sealed = json.dumps(prediction, sort_keys=True)
    record["prediction"] = prediction
    record["prediction_sha256"] = hashlib.sha256(sealed.encode("utf-8")).hexdigest()
    (outdir / f"{case['id']}.prediction.json").write_text(sealed, encoding="utf-8")

    # STAGE 3: measure.
    started = time.perf_counter()
    try:
        report = engine.run(package_path, steps)
        record["status"] = "complete"
    except EngineError as exc:
        report, record["status"] = exc.report, f"engine_error: {exc}"
    record["wall_s"] = round(time.perf_counter() - started, 2)
    record["report"] = report_digest(report)
    record["resolution"] = resolution_verdict(package, report)
    record["energy"] = energy_verdict(report)

    control = None
    try:
        control_package = at_rest_control_package(package)
        control_path = outdir / f"{case['id']}.control.json"
        rewrite_package(control_package, control_path)
        try:
            control_report = engine.run(control_path, steps)
        except EngineError as exc:
            control_report = exc.report
        control = control_verdict(control_report)
    except ValueError:
        control = None  # rigid-only scene: nothing that can shake itself apart
    record["at_rest_control"] = control

    # STAGE 4a: deterministic invariants.
    invariants = []
    for name, check in INVARIANTS:
        ok, detail = check(report, control, case)
        invariants.append({"name": name,
                           "result": "pass" if ok else "n/a" if ok is None else "FAIL",
                           "detail": detail})
    record["invariants"] = invariants
    failed = [i["name"] for i in invariants if i["result"] == "FAIL"]
    record["invariants_pass"] = not failed
    record["invariants_failed"] = failed

    # STAGE 4b: grade the sealed prediction.
    if api_key and "error" not in prediction and "skipped" not in prediction:
        try:
            record["grade"] = structured_call(
                api_key, model, GRADE_SYSTEM,
                json.dumps({"scene": case["question"], "sealed_prediction": prediction,
                            "measured_report": record["report"],
                            "at_rest_control": control}, indent=1),
                GRADE_SCHEMA, "grade")
        except (RuntimeError, json.JSONDecodeError) as exc:
            record["grade"] = {"verdict": "undetermined", "reasoning": str(exc), "judgements": []}
    else:
        record["grade"] = None
    return record


def load_api_key():
    env = ROOT / ".env"
    if env.is_file():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("OPENAI_API_KEY="):
                value = line.split("=", 1)[1].strip()
                if value:
                    return value
    return os.environ.get("OPENAI_API_KEY")


def main():
    parser = argparse.ArgumentParser(
        description="Predict-then-measure regression suite for the Banjo engine.")
    parser.add_argument("--engine", type=Path,
                        default=ROOT / "build/win-joint-double/Release/banjo_platform_cli.exe")
    parser.add_argument("--output", type=Path, default=ROOT / "build/physics-suite")
    parser.add_argument("--model", default="gpt-5-mini")
    parser.add_argument("--filter", default="", help="Only run cases whose id contains this")
    parser.add_argument("--no-model", action="store_true", help="Invariant column only")
    parser.add_argument("--timeout-s", type=float, default=300.0)
    args = parser.parse_args()

    if not args.engine.is_file():
        print(f"Engine not found: {args.engine}", file=sys.stderr)
        return 2
    api_key = None if args.no_model else load_api_key()

    args.output.mkdir(parents=True, exist_ok=True)
    engine = EngineCLI(args.engine, timeout_s=args.timeout_s)
    cases = [c for c in build_cases() if args.filter in c["id"]]
    print(f"Banjo physics suite: {len(cases)} case(s), "
          f"{'with' if api_key else 'WITHOUT'} model prediction\n", flush=True)

    records = []
    for index, case in enumerate(cases, start=1):
        print(f"[{index}/{len(cases)}] {case['id']:24} ", end="", flush=True)
        record = run_case(case, engine, args.output, api_key, args.model)
        records.append(record)
        grade = (record.get("grade") or {}).get("verdict", "-")
        state = "pass" if record["invariants_pass"] else "FAIL:" + ",".join(record["invariants_failed"])
        print(f"invariants={state:34} prediction={grade} ({record['wall_s']}s)", flush=True)

    (args.output / "suite.json").write_text(
        json.dumps(records, indent=1, allow_nan=False), encoding="utf-8")

    passed = sum(1 for r in records if r["invariants_pass"])
    graded = [r for r in records if r.get("grade")]
    matched = sum(1 for r in graded if r["grade"]["verdict"] == "matched")
    print("\n" + "=" * 78)
    print(f"INVARIANTS  {passed}/{len(records)} passed    (deterministic; no model involved)")
    if graded:
        print(f"PREDICTION  {matched}/{len(graded)} matched    (sealed model expectation vs measurement)")
    print("=" * 78)
    for record in records:
        if not record["invariants_pass"]:
            print(f"  FAIL {record['id']}: {', '.join(record['invariants_failed'])}")
    for record in graded:
        if record["grade"]["verdict"] in ("contradicted", "partly_matched"):
            print(f"  {record['grade']['verdict'].upper()} {record['id']}: "
                  f"{record['grade']['reasoning'][:160]}")
    print(f"\nFull results: {args.output / 'suite.json'}")
    print("\nThe system is ready when the invariant column is green. The prediction column\n"
          "says whether it also behaves like the material it claims to be.")
    return 0 if passed == len(records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
