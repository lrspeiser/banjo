"""Functional Workshop bench with generic visual playback recordings.

The tested bench implementation remains in ``workshop_bench_core``. Engine
sessions are transparently wrapped while a test runs; the solver receives the
same calls and the result gains a browser-neutral playback timeline.
"""
from __future__ import annotations

from copy import deepcopy
import math
from typing import Any

import workshop_bench_core as _core
from workshop_bench_core import *  # noqa: F401,F403
import workshop_recording
import workshop_trials
import workshop_motion
from mcp import workshop_acceptance, workshop_matter_metrics, workshop_rigid

_LOAD_KINDS = {"table", "stool", "bench", "chair", "shelf-unit", "cart"}

#: The rigs that had no ground under them. Each one floated the design's cells
#: in an empty spec: a load rig that pressed a weight onto nothing, and drop,
#: slide and strike rigs with a bare floor and no world around them. Every one
#: of them is now a setting of the one test that installs the thing into a
#: little world, so none of them is offered any more. The code still runs from
#: the API, because their unit tests are the record of what they measured.
RETIRED = {"declared_static_load", "drop_product", "slide_product", "impact_product", "rigid_motion"}

#: Which archetypes the installer can actually MAKE, and so which ones the
#: little world can be offered for. This is not a property of the test: it is
#: how far the Workshop's own compiler reaches today.
#:
#: - a cart and a kettle are refused outright -- "only fixed structural solids
#:   can be placed by this adapter; articulated machines and containers need
#:   their own interfaces";
#: - a chair, a stool and a shelf-unit come out of their template with
#:   "disconnected or missing physical components" and never compile at all,
#:   which is why the old catalogue offered them nothing either.
#:
#: Anything drawn part by part through the chat is kind "custom" and installs,
#: which is how the robot and the solar cart are tried. Making the rest of the
#: templates installable is real work and is on the list; it is not hidden by
#: offering a test that would fail.
CAN_BE_MADE = {"table", "bench", "custom"}

#: What a bench does to a thing, all of it in one grounded room.
LITTLE_WORLD = {
    "test": "try_in_a_room", "name": "Try it in a little world",
    "about": ("Make it in a small room with real ground, gravity and a sky, and do to it what you "
              "choose: set a weight on it, drop it, start it sliding, or throw a block at it. It is "
              "installed by the same call the world installs it with, so what happens here is what "
              "happens there."),
    "kinds": [], "category": "simulation", "subject": "selected-product",
    "required_model": "any", "visual_playback": True, "subject_kinds": "installable",
    "controls": [
        {"name": "seconds", "label": "Run", "unit": "s", "type": "number", "default": 6.0,
         "min": 0.5, "max": 60.0, "step": 0.5},
        {"name": "load_kg", "label": "Weight set on it (0 for none)", "unit": "kg", "type": "number",
         "default": 0.0, "min": 0.0, "max": 2000.0, "step": 1.0},
        {"name": "drop_m", "label": "Dropped from", "unit": "m", "type": "range",
         "default": 0.0, "min": 0.0, "max": 5.0, "step": 0.05},
        {"name": "slide_m_s", "label": "Started sliding at", "unit": "m/s", "type": "number",
         "default": 0.0, "min": -30.0, "max": 30.0, "step": 0.1},
        {"name": "strike_kg", "label": "Block thrown at it (0 for none)", "unit": "kg", "type": "range",
         "default": 0.0, "min": 0.0, "max": 500.0, "step": 0.5},
        {"name": "strike_speed_m_s", "label": "Thrown at", "unit": "m/s", "type": "range",
         "default": 8.0, "min": 0.5, "max": 30.0, "step": 0.5},
        {"name": "strike_height_fraction", "label": "Hit it (0 feet, 1 top)", "type": "range",
         "default": 1.0, "min": 0.0, "max": 1.0, "step": 0.05},
        {"name": "hour", "label": "Time of day", "unit": "h", "type": "number",
         "default": 12.0, "min": 0.0, "max": 24.0, "step": 0.5},
        {"name": "turn_on", "label": "Switch its program on", "type": "boolean", "default": True},
        # Opt-in limits. Without them a run is a measurement and says so; there
        # is no tolerance to be guessed from what a thing is called.
        {"name": "evaluate_limits", "label": "Judge it against the limits below",
         "type": "boolean", "default": False},
        {"name": "max_moved_m", "label": "Furthest it may move", "unit": "m", "type": "number",
         "default": 0.01, "min": 0.0, "max": 100.0, "step": 0.001},
        {"name": "max_turned_deg", "label": "Furthest it may turn", "unit": "deg", "type": "number",
         "default": 5.0, "min": 0.0, "max": 360.0, "step": 0.5},
        {"name": "max_breaks", "label": "Breaks allowed", "type": "number",
         "default": 0, "min": 0, "max": 1000, "step": 1},
    ],
    "limitations": [
        "Flat ground of 400 mm of soil, 16 m across. Weather, water and terrain shapes are not in it.",
        "The weight and the thrown block are iron cubes of the mass you ask for, and they are bodies "
        "in the room: they fall, they can miss, and they can bounce off.",
        "What breaks is the engine's failure model for the material, not a certified strength.",
    ],
}


def _how(config: dict[str, Any]) -> dict[str, Any]:
    """The little world's settings, out of the bench's flat control values."""
    strike = None
    if float(config.get("strike_kg") or 0.0) > 0.0:
        strike = {"kg": float(config["strike_kg"]),
                  "speed_m_s": float(config.get("strike_speed_m_s", 8.0)),
                  "height_fraction": float(config.get("strike_height_fraction", 1.0))}
    how: dict[str, Any] = {
        "seconds": float(config.get("seconds", 6.0)),
        "load_kg": float(config.get("load_kg") or 0.0),
        "on": str(config.get("on") or "top"),
        "drop_m": float(config.get("drop_m") or 0.0),
        "slide_m_s": float(config.get("slide_m_s") or 0.0),
        "strike": strike,
        "turn_on": bool(config.get("turn_on", True)),
        "items": config.get("items") or (),
    }
    hour = config.get("hour")
    if hour is not None and abs(float(hour) - 12.0) > 1e-9:
        how["day"] = {"day_s": 240.0, "hour": float(hour)}
    return how


def catalog(kind: str | None = None) -> list[dict[str, Any]]:
    out = _core.catalog(kind)
    if kind in _LOAD_KINDS:
        out.append({
            "test": "declared_static_load", "name": "Load the product",
            "about": "Run this product's own declared static load in an isolated physics world and watch the bodies move, rotate or fracture.",
            "controls": [
                {"name": "load_kg", "label": "Load (blank uses design load)", "unit": "kg", "type": "number", "default": "", "optional": True, "min": .1, "max": 1000.0, "step": .1},
                {"name": "duration_s", "label": "Run", "unit": "s", "type": "number", "default": 2.0, "min": 0.2, "max": 10.0, "step": 0.1},
                {"name": "cell_size_m", "label": "Matter resolution", "unit": "m", "type": "number", "default": 0.04, "min": 0.005, "max": 0.1, "step": 0.005},
                {"name": "evaluate_limits", "label": "Evaluate the limits below", "type": "boolean", "default": False},
                {"name": "max_displacement_m", "label": "Maximum end displacement", "unit": "m", "type": "number", "default": 0.01, "min": 0.0, "max": 10.0, "step": 0.001},
                {"name": "max_rotation_deg", "label": "Maximum end rotation", "unit": "deg", "type": "number", "default": 5.0, "min": 0.0, "max": 180.0, "step": 0.1},
                {"name": "max_fractures", "label": "Maximum fracture events", "type": "number", "default": 0, "min": 0, "max": 10000, "step": 1},
            ],
            "acceptance_limits": {key: {"metric": metric, "unit": unit, "operator": operator}
                                  for key, (metric, unit, operator) in workshop_acceptance.LIMITS.items()},
            "limitations": ["The load is the design's authored load case. If no acceptance tolerance is declared, the run remains measured evidence rather than an invented pass/fail."],
            "visual_playback": True,
        })
    out = workshop_motion.catalog(kind) + out
    if kind in workshop_motion.SOLID_KINDS:
        out.append({"test":"rigid_motion","name":"Precise rigid motion (no fracture)",
            "about":"Drop or slide this exact-size fixed compound in the native rigid engine; choose the rigid model explicitly first.",
            "controls":[{"name":"duration_s","label":"Run","unit":"s","type":"number","default":2,"min":.1,"max":5,"step":.1},
                        {"name":"drop_height_m","label":"Drop height","unit":"m","type":"number","default":.2,"min":0,"max":2,"step":.05},
                        {"name":"horizontal_speed_m_s","label":"Horizontal speed","unit":"m/s","type":"number","default":0,"min":-2,"max":2,"step":.1}],
            "limitations":list(workshop_rigid.LIMITATIONS),"visual_playback":True})
    for item in out:
        name = str(item.get("test") or "")
        item["category"] = "simulation" if name in workshop_motion.TESTS | {"cart_roll", "kettle_heat", "declared_static_load", "rigid_motion"} else "analysis"
        item["subject"] = "reference-fixture" if name == "machine_control" else "selected-product"
        item["required_model"] = "rigid" if name == "rigid_motion" else "lattice"
        # Never offer a fused-solid test for an articulated cart in the UI.
        if name == "declared_static_load" and kind not in workshop_motion.SOLID_KINDS:
            item["category"] = "analysis"
        if name == "machine_control":
            item["name"] = "Reference hoist controller"
            item["about"] = "Exercise the reference hoist's controller and energy path, not the selected product's geometry."
        item["visual_playback"] = bool(item.get("visual_playback")) or name in {
            "cart_roll", "kettle_heat", "machine_control", "declared_static_load"
        }
        if item["visual_playback"]:
            item.setdefault("controls", []).append({
                "name": "record_trace", "label": "Keep simulation trace for inspection",
                "type": "boolean", "default": True})
        if name in {"runtime_contract", "force_probe"}:
            item["visual_overlay"] = True
        # A rig with no ground under it is not offered. It stays runnable from
        # the API so its own tests still hold it to what it measured.
        if name in RETIRED:
            item["category"] = "retired"
            item["superseded_by"] = LITTLE_WORLD["test"]
    # Offered only where the thing can be made, and first where it is offered,
    # because everything else that could run there is retired.
    if kind is not None and kind not in CAN_BE_MADE:
        return out
    return [deepcopy(LITTLE_WORLD), *out]


#: What a person may hold a run in the little world to, and what it is measured
#: against. Three things it actually measures -- nothing inferred from what the
#: thing is called, and no claim about loads that were not applied.
ROOM_LIMITS = {
    "max_moved_m": ("moved_m", "m", "max"),
    "max_turned_deg": ("turned_deg", "deg", "max"),
    "max_breaks": ("breaks", "events", "max"),
}


def _judge(config: dict[str, Any], measured: dict[str, Any], seconds: float) -> dict[str, Any]:
    """Whether the run met the limits that were declared for it, if any were."""
    if not config.get("evaluate_limits"):
        return {"status": "not-declared", "scope": "this-exact-run", "checks": [],
                "why": "No limits were declared. The run is what was measured, not a pass."}
    missing = [name for name in ROOM_LIMITS if name not in config]
    if missing:
        raise ValueError("judging a run needs every limit given: " + ", ".join(sorted(missing)))
    checks = []

    def check(metric, actual, limit, unit, operator="max"):
        held = None if actual is None else (actual <= limit if operator == "max" else actual >= limit)
        checks.append({"metric": metric, "measured": actual, "operator": operator, "limit": limit,
                       "unit": unit, "status": "unsupported" if held is None
                       else "passed" if held else "failed"})

    # It has to have run the whole way for the numbers at the end to mean
    # anything: a run cut short is unsupported, not a pass.
    ran = measured.get("ran_for_s")
    checks.append({"metric": "ran_for_s", "measured": ran, "operator": "min", "limit": seconds,
                   "unit": "s", "status": "passed" if ran is not None and ran + 1e-6 >= seconds
                   else "unsupported"})
    values = {"moved_m": measured.get("moved_m"), "turned_deg": measured.get("turned_deg"),
              "breaks": len(measured.get("broke") or [])}
    for name, (metric, unit, operator) in ROOM_LIMITS.items():
        check(metric, values[metric], float(config[name]), unit, operator)
    statuses = {c["status"] for c in checks}
    return {"status": "failed" if "failed" in statuses else
                      "unsupported" if "unsupported" in statuses else "passed",
            "scope": "this-exact-run", "checks": checks,
            "criteria": {name: float(config[name]) for name in ROOM_LIMITS},
            "why": "The limits declared for this run, against what this run measured. "
                   "Not a strength rating, and nothing about loads that were not applied."}


def run_in_a_room(app: Any, candidate: Any, config: dict[str, Any]) -> dict[str, Any]:
    """The one test: the thing made in a little world and something done to it.

    Shaped like every other bench result -- a `test`, a `measured` and a
    `playback` -- so the bench's own run button, result box and player need to
    know nothing about it.
    """
    import workshop_test_room
    if candidate is None:
        raise ValueError("Trying a thing in a little world needs the design it is made from")
    how = _how(config)
    # Before anything expensive: a run asked to judge itself must be told what
    # to judge itself by, or it would run for six seconds and then refuse.
    if config.get("evaluate_limits") and not set(ROOM_LIMITS) <= set(config):
        raise ValueError("judging a run needs every limit given: "
                         + ", ".join(sorted(set(ROOM_LIMITS) - set(config))))
    said = workshop_test_room.try_it(app, candidate, **how)
    deck = said["made"].get("root_body") or ""
    body = said["ended"]["bodies"].get(deck, {})
    began = said["began"]["bodies"].get(deck, {})
    measured = {"ran_for_s": said["ran_for_s"], "mass_kg": said["made"].get("mass_kg"),
                "cells": said["made"].get("cells"),
                "stood_at_m": began.get("at_m"), "ended_at_m": body.get("at_m"),
                "moved_m": round(math.dist(body.get("at_m") or [0, 0, 0],
                                           began.get("at_m") or [0, 0, 0]), 5)
                if body.get("at_m") else None,
                "turned_deg": body.get("turn_deg"), "fell_over": said["fell_over"],
                "broke": said["broke"], "dented": said["dented"], "failures": said["failures"],
                "stores": said["ended"]["stores"],
                "panels": said["ended"]["panels"], "programs": said["ended"]["programs"]}
    return {"schema": workshop_test_room.SCHEMA, "test": "try_in_a_room", "status": "measured",
            "engine_backed": True, "mechanical_model": "as compiled", "says": said["says"],
            "requested": said["did"], "in_the_room": said["in_the_room"], "sky": said["sky"],
            "measured": measured, "acceptance": _judge(config, measured, how["seconds"]),
            "playback": said.get("playback"), "limitations": list(LITTLE_WORLD["limitations"])}


def run(app: Any, design, request: Any, *, candidate: Any = None) -> dict[str, Any]:
    if not isinstance(request, dict):
        raise ValueError("bench_test must be an object")
    test = str(request.get("test") or "")
    config = request.get("config") or {}
    if not isinstance(config, dict):
        raise ValueError("bench_test.config must be an object")
    # Before the retired rigs' own argument checking, which asks for limits
    # named after measurements the little world does not take.
    if test == "try_in_a_room":
        return run_in_a_room(app, candidate, config)
    record_trace = config.get("record_trace", True)
    if not isinstance(record_trace, bool):
        raise ValueError("record_trace must be a boolean")
    selected_limits = config.get("evaluate_limits", False)
    if not isinstance(selected_limits, bool):
        raise ValueError("evaluate_limits must be a boolean")
    limits = workshop_acceptance.merge_limits(
        request.get("acceptance_limits"), config.get("acceptance_limits"))
    if selected_limits:
        names = ("max_displacement_m", "max_rotation_deg", "max_fractures")
        if any(name not in config for name in names):
            raise ValueError("evaluating limits requires explicit displacement, rotation and fracture limits")
        limits = workshop_acceptance.merge_limits(limits, {name: config[name] for name in names})
    if limits is not None and test != "declared_static_load":
        raise ValueError("acceptance_limits currently require the exact-Matter declared_static_load test")
    if test == "rigid_motion":
        import workshop_rigid_trial
        return workshop_rigid_trial.run(app, design, config)
    workshop_rigid.require_lattice(design, "This Workshop test")
    if test in workshop_motion.TESTS:
        result = workshop_motion.run(app, design, test, config)
        if not record_trace:
            result.pop("playback", None)
        return result
    if test == "declared_static_load":
        if "load_kg" in config:
            load = workshop_motion.number(config, "load_kg", 25.0, .1, 1000.0)
            trial = next((t for t in design.tests if t.get("kind") == "static_load"), None)
            if trial is None:
                raise ValueError("This design has no supported load target")
            return workshop_trials.run_static_load(app, design, load_kg=load,
                on=str(trial.get("on") or "top"), cell_size_m=float(config.get("cell_size_m", .04)),
                duration_s=float(config.get("duration_s", 2.0)), record_trace=record_trace,
                acceptance_limits=workshop_acceptance.merge_limits(trial.get("acceptance_limits"), limits))
        return workshop_trials.run_declared_static_load(
            app, design,
            cell_size_m=float(config.get("cell_size_m", 0.04)),
            duration_s=float(config.get("duration_s", 2.0)), record_trace=record_trace,
            acceptance_limits=limits)

    if test in {"cart_roll", "kettle_heat"}:
        workshop_matter_metrics.require_wire_geometry(design, test)
    recorders: list[workshop_recording.Recorder] = []

    def record(session):
        recorder = workshop_recording.wrap(session)
        recorders.append(recorder)
        return recorder

    result = _core.run(app, design, request, session_wrapper=record if record_trace else None)
    if recorders and isinstance(result, dict):
        recorder = recorders[-1]
        result["playback"] = recorder.recording(
            test=test,
            requested=dict(result.get("requested") or config),
            limitations=list(result.get("limitations") or []))
    return result


# Preserve direct helpers for tests and specialist callers. API/MCP uses run().
run_contract = _core.run_contract
run_force = _core.run_force
run_cart = _core.run_cart
run_kettle = _core.run_kettle
run_machine = _core.run_machine
_cart_spec = _core._cart_spec
