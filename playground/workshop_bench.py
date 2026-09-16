"""Functional test fixtures for Workshop designs.

These fixtures own their own live engine sessions. They never borrow ``app.live``
or mutate the outside room. The first two acceptance cases deliberately exercise
systems Banjo already has end to end:

* ``kettle_heat``: an iron/aluminium vessel sits on a heated plate with a
  contained-water thermal proxy inside it. Heat reaches the water through the
  engine's ordinary contact/conduction network and the result is the thermo
  report/ledger. Banjo does not yet simulate free liquid/sloshing, so the water
  proxy is said explicitly in the evidence.
* ``machine_control``: a battery hoist with the engine's real controller. The
  bench edits power, direction and setting, runs it, and reports the controller,
  motor, battery, rope and load motion.

A bench result is evidence, not a live-world commit and not an invented pass/fail.
"""
from __future__ import annotations

from math import isfinite
from pathlib import Path
from typing import Any

import fracture_lab
import live_session
from mcp import engine_materials
from mcp.workshop import WorkshopDesign

BENCH_SCHEMA = "banjo.workshop-bench.v1"


def catalog() -> list[dict[str, Any]]:
    return [
        {
            "test": "kettle_heat",
            "name": "Heat water in a kettle",
            "about": "Add a contained-water thermal charge, heat a plate below the kettle, and measure temperature and energy.",
            "controls": [
                {"name": "water_kg", "label": "Water", "unit": "kg", "type": "number", "default": 1.0, "min": 0.1, "max": 5.0, "step": 0.1},
                {"name": "heater_power_w", "label": "Heat below", "unit": "W", "type": "number", "default": 1800.0, "min": 100.0, "max": 10000.0, "step": 100.0},
                {"name": "duration_s", "label": "Run", "unit": "s", "type": "number", "default": 120.0, "min": 5.0, "max": 600.0, "step": 5.0},
                {"name": "kettle_material", "label": "Kettle material", "type": "select", "default": "iron", "choices": ["iron", "aluminum"]},
            ],
            "limitations": ["Water is currently a contained thermal proxy; free liquid flow/sloshing is not yet in Banjo."],
        },
        {
            "test": "machine_control",
            "name": "Operate a powered machine",
            "about": "Run a battery hoist through the engine's real controller and edit the panel command.",
            "controls": [
                {"name": "power", "label": "Power", "type": "boolean", "default": True},
                {"name": "direction", "label": "Direction", "type": "select", "default": 1, "choices": [1, 0, -1], "choice_labels": ["Raise / forward", "Stop", "Lower / reverse"]},
                {"name": "setting", "label": "Drive setting", "unit": "%", "type": "number", "default": 100.0, "min": 0.0, "max": 100.0, "step": 5.0},
                {"name": "duration_s", "label": "Run", "unit": "s", "type": "number", "default": 1.5, "min": 0.1, "max": 10.0, "step": 0.1},
                {"name": "load_kg", "label": "Load", "unit": "kg", "type": "number", "default": 26.5, "min": 1.0, "max": 100.0, "step": 0.5},
            ],
            "limitations": [],
        },
    ]


def _number(config: dict[str, Any], name: str, default: float, low: float, high: float) -> float:
    try:
        value = float(config.get(name, default))
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number")
    if not isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name} must be between {low:g} and {high:g}")
    return value


def _scratch(app: Any, label: str) -> tuple[Path, Path]:
    engine = Path(getattr(app, "engine_path"))
    runs = Path(getattr(app, "runs_path")) / "workshop-bench" / label
    runs.mkdir(parents=True, exist_ok=True)
    return engine, runs


def _advance(session: Any, duration_s: float, *, dt: float = 1 / 30.0) -> dict[str, Any]:
    target = float((session.state or {}).get("t", 0.0)) + duration_s
    state = session.state
    guard = 0
    while float(state.get("t", 0.0)) < target - 1e-9:
        guard += 1
        if guard > 100000:
            raise RuntimeError("Workshop bench stopped advancing")
        remaining = target - float(state.get("t", 0.0))
        n = max(1, min(120, int(round(min(remaining, 120 * dt) / dt))))
        state = session.send(op="step", dt=dt, n=n)
        while state.get("breakable"):
            state = session.send(op="fracture", name=str(state["breakable"][0]), window_s=0.003)
    return state


def _thermo_body(report: dict[str, Any], name: str) -> dict[str, Any] | None:
    return next((b for b in report.get("bodies") or [] if b.get("name") == name), None)


def run_kettle(app: Any, config: dict[str, Any]) -> dict[str, Any]:
    water_kg = _number(config, "water_kg", 1.0, 0.1, 5.0)
    power = _number(config, "heater_power_w", 1800.0, 100.0, 10000.0)
    duration = _number(config, "duration_s", 120.0, 5.0, 600.0)
    material = engine_materials.canonical(str(config.get("kettle_material") or "iron"))
    if material not in {"iron", "aluminum"}:
        raise ValueError("kettle_material must be iron or aluminum")

    # A compact 260 x 220 mm vessel. The shell is several boxes joined into one
    # material piece. The water is an ice-density rigid proxy whose thermo
    # contents are 100% moisture: its heat capacity/phase inventory is liquid
    # water, but mechanics do not yet claim liquid motion.
    width, depth, wall, vessel_h = 0.26, 0.22, 0.006, 0.18
    plate_h = 0.02
    base_bottom = plate_h
    water_area = (width - 2 * wall) * (depth - 2 * wall)
    water_h = water_kg / 917.0 / water_area
    if water_h > vessel_h - 2 * wall:
        raise ValueError("that much water does not fit in this kettle fixture")
    bodies = [
        {"name": "heater plate", "shape": "box", "material": "iron",
         "size_mm": [220, plate_h * 1000, 180], "center_mm": [0, plate_h * 500, 0], "anchored": True},
        {"name": "kettle bottom", "shape": "box", "material": material,
         "size_mm": [width * 1000, wall * 1000, depth * 1000],
         "center_mm": [0, (base_bottom + wall / 2) * 1000, 0], "join": "kettle shell"},
        {"name": "kettle left", "shape": "box", "material": material,
         "size_mm": [wall * 1000, vessel_h * 1000, depth * 1000],
         "center_mm": [(-width / 2 + wall / 2) * 1000, (base_bottom + wall + vessel_h / 2) * 1000, 0], "join": "kettle shell"},
        {"name": "kettle right", "shape": "box", "material": material,
         "size_mm": [wall * 1000, vessel_h * 1000, depth * 1000],
         "center_mm": [(width / 2 - wall / 2) * 1000, (base_bottom + wall + vessel_h / 2) * 1000, 0], "join": "kettle shell"},
        {"name": "kettle front", "shape": "box", "material": material,
         "size_mm": [(width - 2 * wall) * 1000, vessel_h * 1000, wall * 1000],
         "center_mm": [0, (base_bottom + wall + vessel_h / 2) * 1000, (-depth / 2 + wall / 2) * 1000], "join": "kettle shell"},
        {"name": "kettle back", "shape": "box", "material": material,
         "size_mm": [(width - 2 * wall) * 1000, vessel_h * 1000, wall * 1000],
         "center_mm": [0, (base_bottom + wall + vessel_h / 2) * 1000, (depth / 2 - wall / 2) * 1000], "join": "kettle shell"},
        {"name": "water charge", "shape": "box", "material": "ice",
         "size_mm": [(width - 2 * wall) * 1000, water_h * 1000, (depth - 2 * wall) * 1000],
         "center_mm": [0, (base_bottom + wall + water_h / 2) * 1000, 0],
         "contents": {"moisture": 1.0}, "temperature_k": 293.15},
    ]
    spec = fracture_lab.validate({
        "algorithm": "lattice", "cell_m": 0.02, "plasticity": "on", "bodies": bodies,
        "thermo": {"heaters": [{"target": "heater plate", "power_w": power,
                                  "start_s": 0.0, "seconds": duration, "label": "heat below kettle"}]},
    })
    engine, runs = _scratch(app, "kettle")
    session = live_session.Session(engine, spec, runs)
    try:
        initial = session.send(op="thermo")
        _advance(session, duration)
        final = session.send(op="thermo")
    finally:
        session.close()
    initial_report = initial.get("thermo") or {}
    report = final.get("thermo") or {}
    before = _thermo_body(initial_report, "water charge") or {}
    after = _thermo_body(report, "water charge") or {}
    shell = _thermo_body(report, "kettle bottom") or {}
    heater = _thermo_body(report, "heater plate") or {}
    return {
        "schema": BENCH_SCHEMA, "test": "kettle_heat", "evidence": "engine-trial",
        "requested": {"water_kg": water_kg, "heater_power_w": power,
                      "duration_s": duration, "kettle_material": material},
        "measured": {
            "water_start_k": before.get("temperature_k"),
            "water_end_k": after.get("temperature_k"),
            "water_end_c": (round(float(after["temperature_k"]) - 273.15, 2)
                            if after.get("temperature_k") is not None else None),
            "kettle_bottom_k": shell.get("temperature_k"),
            "heater_plate_k": heater.get("temperature_k"),
            "water_contents_kg": after.get("contents_kg"),
            "ledger": report.get("ledger"),
        },
        "acceptance": {"status": "observed", "why": "This fixture measures heat transfer; no target boil time was declared."},
        "limitations": ["Water is represented as a contained thermal proxy; free liquid flow/sloshing is not yet simulated."],
    }


def _hoist_spec(load_kg: float) -> dict[str, Any]:
    # Iron density determines the cube side so the requested test load is real
    # rigid mass, not a number painted onto the controller.
    side = (load_kg / engine_materials.density("iron")) ** (1 / 3)
    return fracture_lab.validate({
        "algorithm": "lattice", "cell_m": 0.05, "plasticity": "on",
        "bodies": [
            {"name": "post", "shape": "box", "material": "iron", "size_mm": [100, 2000, 100],
             "center_mm": [-400, 1000, 0], "anchored": True},
            {"name": "drum", "shape": "box", "material": "oak", "size_mm": [200, 200, 300],
             "center_mm": [0, 2000, 0]},
            {"name": "load", "shape": "box", "material": "iron",
             "size_mm": [side * 1000, side * 1000, side * 1000],
             "center_mm": [100, 450, 0]},
        ],
        "joints": [
            {"kind": "hinge", "a": "post", "b": "drum", "at_mm": [0, 2000, 0], "axis": [0, 0, 1]},
            {"kind": "drum", "a": "drum", "b": "load", "at_mm": [0, 2000, 0], "axis": [0, 0, 1],
             "radius_mm": 100, "to_mm": [100, 500, 0], "winds": 1, "length_mm": 2000},
        ],
        "machines": {
            "stores": [{"name": "battery", "body": "post", "capacity_j": 5000}],
            "motors": [{"on": ["post", "drum"], "store": "battery", "stall_torque_n_m": 60,
                        "no_load_rpm": 95.5, "brake_torque_n_m": 200}],
            "controls": [{"name": "hoist", "on": ["post", "drum"],
                          "top_out_mm": 300.0, "bottom_out_mm": 1950.0}],
        },
    })


def run_machine(app: Any, config: dict[str, Any]) -> dict[str, Any]:
    duration = _number(config, "duration_s", 1.5, 0.1, 10.0)
    load_kg = _number(config, "load_kg", 26.5, 1.0, 100.0)
    setting_pct = _number(config, "setting", 100.0, 0.0, 100.0)
    power = bool(config.get("power", True))
    try:
        direction = int(config.get("direction", 1))
    except (TypeError, ValueError):
        raise ValueError("direction must be -1, 0 or 1")
    if direction not in {-1, 0, 1}:
        raise ValueError("direction must be -1, 0 or 1")

    spec = _hoist_spec(load_kg)
    scratch = live_session.Live()
    class App:
        engine_path = Path(getattr(app, "engine_path"))
        runs_path = Path(getattr(app, "runs_path")) / "workshop-bench" / "machine"
        live_inprocess = False
        on_live_reply = None
    App.runs_path.mkdir(parents=True, exist_ok=True)
    opened = scratch.open(App(), {"spec": spec})
    session = scratch.session
    assert session is not None
    try:
        controls = (opened.get("machines") or {}).get("controls") or []
        if not controls:
            raise ValueError("the scratch machine opened without its controller")
        control = controls[0]
        start_load = next(b for b in session.state.get("bodies", []) if b["name"] == "load")
        start_y = float(start_load["position_m"][1])
        ack = session.send(op="operate", control=int(control["id"]), sender="workshop-bench", seq=1,
                           power=power, direction=direction, setting=setting_pct / 100.0)
        _advance(session, duration, dt=1 / 120.0)
        state = session.send(op="poses")
        machines = session.state.get("machines") or state.get("machines") or {}
        end_load = next(b for b in session.state.get("bodies", []) if b["name"] == "load")
    finally:
        scratch.shutdown()
    control_now = (machines.get("controls") or [{}])[0]
    motor = (machines.get("motors") or [{}])[0]
    store = (machines.get("stores") or [{}])[0]
    rope = (machines.get("ropes") or [{}])[0]
    return {
        "schema": BENCH_SCHEMA, "test": "machine_control", "evidence": "engine-trial",
        "requested": {"power": power, "direction": direction, "setting": setting_pct,
                      "duration_s": duration, "load_kg": load_kg},
        "measured": {
            "control": control_now,
            "motor": motor,
            "battery": store,
            "rope": rope,
            "load_delta_y_m": round(float(end_load["position_m"][1]) - start_y, 5),
            "acknowledgement": ack.get("operated"),
        },
        "acceptance": {"status": "observed", "why": "The controller command and resulting motion/energy are reported without inventing a target."},
        "limitations": [],
    }


def run(app: Any, design: WorkshopDesign, request: Any) -> dict[str, Any]:
    if not isinstance(request, dict):
        raise ValueError("bench_test must be an object")
    name = str(request.get("test") or "")
    config = request.get("config") or {}
    if not isinstance(config, dict):
        raise ValueError("bench_test.config must be an object")
    if name == "kettle_heat":
        result = run_kettle(app, config)
    elif name == "machine_control":
        result = run_machine(app, config)
    else:
        raise ValueError("unknown Workshop bench test")
    result["source_design_id"] = design.design_id
    result["source_kind"] = design.kind
    return result
