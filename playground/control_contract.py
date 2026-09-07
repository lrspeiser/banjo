"""Declarative, bounded controls for the Banjo playground UI.

The UI is data only: controls contain no markup, code, commands, or callbacks.
"""
from __future__ import annotations

from copy import deepcopy
import math
import re
from typing import Any


_CONTROL_KEYS = {"id", "label", "kind", "action", "min", "max", "step", "value"}
_ID = re.compile(r"[a-z][a-z0-9_-]{0,39}\Z")
_KINDS = {"button", "slider", "toggle"}
_BUTTON_ACTIONS = {"play_pause", "reset", "step_forward", "step_back"}
_PHYSICAL = {"height_m", "speed_m_s", "pressure_pa"}
_EXPERIMENTS = {
    "drop_test", "scene_test", "panel_impact", "plate_drop", "rigid_drop", "knife_cut", "custom_objects",
    "thermal_frontier", "material_state_reference", "continuum_pressure_reference", "dynamic_material_impact",
    "thermal_material_experiment", "glass_reference", "unsupported",
}


def _number(value: Any, name: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def _text(value: Any, name: str, limit: int) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= limit:
        raise ValueError(f"Invalid {name}")
    # UI strings are deliberately plain text.  Reject markup-looking text and
    # all control characters (including newlines and bidi formatting marks).
    if any(ord(ch) < 32 or 127 <= ord(ch) < 160 for ch in value) or "<" in value or ">" in value:
        raise ValueError(f"Invalid {name}")
    return value


def _action_capability(action: str, experiment: str) -> tuple[float, float] | None:
    if action == "height_m" and experiment in {"plate_drop", "rigid_drop", "drop_test"}:
        return 0.0, 2.0
    if action == "speed_m_s" and experiment in {"panel_impact", "knife_cut"}:
        return 0.0, 20.0
    if action == "pressure_pa" and experiment == "continuum_pressure_reference":
        return 1.0, 1_000_000_000.0
    return None


def _validate_control(control: Any, experiment: str) -> dict[str, Any]:
    if not isinstance(control, dict) or set(control) != _CONTROL_KEYS:
        raise ValueError("Control must contain exactly id, label, kind, action, min, max, step, and value")
    if not isinstance(control["id"], str) or not _ID.fullmatch(control["id"]):
        raise ValueError("Invalid control id")
    _text(control["label"], "control label", 60)
    kind, action = control["kind"], control["action"]
    if kind not in _KINDS or not isinstance(action, str):
        raise ValueError("Invalid control kind or action")
    lo, hi = _number(control["min"], "min"), _number(control["max"], "max")
    step, value = _number(control["step"], "step"), _number(control["value"], "value")
    if not lo < hi or step <= 0 or step > hi - lo or not lo <= value <= hi:
        raise ValueError("Invalid control range or value")

    if action in _BUTTON_ACTIONS:
        if kind != "button" or (lo, hi, step, value) != (0.0, 1.0, 1.0, 0.0):
            raise ValueError("Playback controls must be zero-valued 0..1 buttons")
    elif action in {"components", "reference"}:
        if kind not in {"button", "toggle"} or (lo, hi, step) != (0.0, 1.0, 1.0) or value not in (0.0, 1.0):
            raise ValueError("Component/reference controls must be 0..1 buttons or toggles")
    elif action == "playback_speed":
        if kind != "slider" or lo < 0.1 or hi > 4:
            raise ValueError("Playback speed must be a 0.1..4 slider")
    elif action == "magnification":
        if experiment == "dynamic_material_impact" or kind != "slider" or lo < 1 or hi > 100:
            raise ValueError("Magnification must be a 1..100 slider")
    elif action == "frame":
        if kind != "slider" or lo < 0 or hi > 1:
            raise ValueError("Frame must be a 0..1 slider")
    elif action in _PHYSICAL:
        cap = _action_capability(action, experiment)
        if cap is None or kind not in {"slider", "button"} or lo < cap[0] or hi > cap[1]:
            raise ValueError("Physical control is unsupported for this experiment or out of bounds")
    else:
        raise ValueError("Unsupported control action")
    return control


UI_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "minLength": 1, "maxLength": 100},
        "controls": {"type": "array", "maxItems": 12, "items": {
            "type": "object", "properties": {
                "id": {"type": "string", "pattern": "^[a-z][a-z0-9_-]{0,39}$"},
                "label": {"type": "string", "minLength": 1, "maxLength": 60},
                "kind": {"type": "string", "enum": ["button", "slider", "toggle"]},
                "action": {"type": "string", "enum": sorted(_BUTTON_ACTIONS | {"components", "reference", "playback_speed", "magnification", "frame"} | _PHYSICAL)},
                "min": {"type": "number"}, "max": {"type": "number"},
                "step": {"type": "number"}, "value": {"type": "number"},
            }, "required": sorted(_CONTROL_KEYS), "additionalProperties": False,
        }},
    }, "required": ["title", "controls"], "additionalProperties": False,
}


def validate_ui(ui: Any, experiment: str) -> dict[str, Any]:
    if not isinstance(experiment, str) or experiment not in _EXPERIMENTS:
        raise ValueError("Unsupported experiment for UI controls")
    if not isinstance(ui, dict) or set(ui) != {"title", "controls"}:
        raise ValueError("UI must contain exactly title and controls")
    _text(ui["title"], "UI title", 100)
    controls = ui["controls"]
    if not isinstance(controls, list) or len(controls) > 12:
        raise ValueError("UI controls must contain at most twelve entries")
    ids = set()
    for control in controls:
        checked = _validate_control(control, experiment)
        if checked["id"] in ids:
            raise ValueError("Control ids must be unique")
        ids.add(checked["id"])
    return ui


def default_ui(experiment: str) -> dict[str, Any]:
    if not isinstance(experiment, str):
        raise ValueError("Unsupported experiment for UI controls")
    if experiment == "thermal_material_experiment":
        return validate_ui({"title": "Thermal cell playback", "controls": [
            {"id": "play-pause", "label": "Play / pause", "kind": "button", "action": "play_pause", "min": 0, "max": 1, "step": 1, "value": 0},
            {"id": "reset", "label": "Reset", "kind": "button", "action": "reset", "min": 0, "max": 1, "step": 1, "value": 0},
            {"id": "step-forward", "label": "Step forward", "kind": "button", "action": "step_forward", "min": 0, "max": 1, "step": 1, "value": 0},
            {"id": "step-back", "label": "Step back", "kind": "button", "action": "step_back", "min": 0, "max": 1, "step": 1, "value": 0},
            {"id": "playback-speed", "label": "Playback speed", "kind": "slider", "action": "playback_speed", "min": .1, "max": 4, "step": .1, "value": 1},
            {"id": "frame", "label": "Recorded frame", "kind": "slider", "action": "frame", "min": 0, "max": 1, "step": .01, "value": 0},
        ]}, experiment)
    controls = [
        {"id": "play-pause", "label": "Play / pause", "kind": "button", "action": "play_pause", "min": 0, "max": 1, "step": 1, "value": 0},
        {"id": "reset", "label": "Reset", "kind": "button", "action": "reset", "min": 0, "max": 1, "step": 1, "value": 0},
        {"id": "step-forward", "label": "Step forward", "kind": "button", "action": "step_forward", "min": 0, "max": 1, "step": 1, "value": 0},
        {"id": "components", "label": "Components", "kind": "toggle", "action": "components", "min": 0, "max": 1, "step": 1, "value": 0},
    ]
    if experiment in {"plate_drop", "rigid_drop", "drop_test"}:
        controls.append({"id": "height-m", "label": "Height (m)", "kind": "slider", "action": "height_m", "min": 0, "max": 2, "step": 0.01, "value": 0.25})
    elif experiment in {"panel_impact", "knife_cut"}:
        controls.append({"id": "speed-m-s", "label": "Speed (m/s)", "kind": "slider", "action": "speed_m_s", "min": 0, "max": 20, "step": 0.1, "value": 2})
    elif experiment == "continuum_pressure_reference":
        controls.append({"id": "pressure-pa", "label": "Peak pressure (Pa)", "kind": "slider", "action": "pressure_pa", "min": 1, "max": 1_000_000_000, "step": 1_000_000, "value": 800_000_000})
    ui = {"title": "Experiment controls", "controls": controls}
    return validate_ui(ui, experiment)


def apply_control(plan: dict[str, Any], action: str, value: Any, case_index: int = 0) -> dict[str, Any]:
    if not isinstance(plan, dict) or not isinstance(action, str) or action not in _PHYSICAL:
        raise ValueError("Only physical experiment controls can be applied")
    experiment = plan.get("experiment")
    declared_ui = plan.get("ui")
    ui = deepcopy(default_ui(experiment) if declared_ui is None else declared_ui)
    validate_ui(ui, experiment)
    numeric = _number(value, "control value")
    matching = [c for c in ui["controls"] if c["action"] == action]
    eligible = []
    for control in matching:
        if not control["min"] <= numeric <= control["max"]:
            continue
        if control["kind"] == "button" and numeric != control["value"]:
            continue
        eligible.append(control)
    if not eligible:
        raise ValueError("No declared physical control accepts this value")
    if type(case_index) is not int or not 0 <= case_index <= 3:
        raise ValueError("case_index must be an integer from 0 through 3")
    updated = deepcopy(plan)
    if action == "height_m":
        if experiment == "drop_test": updated["drop"]["heights_m"] = [value]
        else: updated["heights_m"] = [value]
        if "duration_s" in plan:
            # These drop routes use fixed -9.81 m/s² gravity. Allow the fall
            # plus half a second to observe contact/rebound. Legacy rigid
            # targets also fall from their initial elevated placement.
            target_fall = .18 if experiment == "rigid_drop" else 0
            observation_s = math.ceil((math.sqrt(2*(numeric+target_fall)/9.81)+.5)*100)/100
            updated["duration_s"] = max(plan["duration_s"], observation_s)
    elif action == "speed_m_s":
        updated["speeds_m_s"] = [value]
    else:
        pressure = updated.get("pressure")
        if pressure is None:
            pressure = {"peak_pressure_pa": 800_000_000, "resolution": 4, "increments": 32, "profile": "uniform"}
        if not isinstance(pressure, dict):
            raise ValueError("Plan pressure must be an object")
        pressure = deepcopy(pressure)
        pressure["peak_pressure_pa"] = value
        updated["pressure"] = pressure
    updated["ui"] = ui
    for item in updated["ui"]["controls"]:
        if item["action"] == action and item["kind"] == "slider" and item["min"] <= numeric <= item["max"]:
            item["value"] = value
    return updated
