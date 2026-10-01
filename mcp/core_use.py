"""Saved primary-use programs. No arbitrary code or prescribed body velocity."""
from __future__ import annotations

from copy import deepcopy
import math

# These additional hand primitives share validation between Workshop, saved
# rooms and MCP. Existing action primitives retain their richer MCP checks.
STEPS = ("inspect", "strike", "push_forward", "place", "machine_power")
DEFAULT = {"label": "Inspect", "steps": [{"do": "inspect"}]}


def checked_step(value):
    if not isinstance(value, dict) or value.get("do") not in STEPS:
        raise ValueError("core step must be inspect, strike, push_forward, place or machine_power")
    do = value["do"]
    allowed = ({"do", "device", "power"} if do == "machine_power" else
               {"do"} if do in ("inspect", "place") else {"do", "distance_m", "speed_m_s"})
    if set(value) - allowed:
        extra = sorted(set(value) - allowed)
        if do == "machine_power":
            raise ValueError("machine_power reads only do, device and power; unknown fields: "+", ".join(extra))
        raise ValueError(
            f"{do} cannot say {extra}: leave {' and '.join(extra)} out of this step and send "
            f'{{"do": "{do}"}} on its own. Only strike and push_forward carry a distance and a '
            "speed.")
    out = {"do": do}
    if do == "machine_power":
        if value.get("device") not in ("program", "lamp") or type(value.get("power")) is not bool:
            raise ValueError("machine_power needs device program or lamp and boolean power")
        return {"do":do,"device":value["device"],"power":value["power"]}
    if do not in ("inspect", "place"):
        limits = (0.05, 0.8, 0.35, 0.1, 5.0, 3.0) if do == "strike" else (0.05, 1.5, 0.4, 0.1, 1.5, 0.4)
        for key, low, high, default in (
                ("distance_m", *limits[:3]), ("speed_m_s", *limits[3:])):
            number = value.get(key, default)
            if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number) or not low <= number <= high:
                raise ValueError(f"{do} {key} must be finite, {low} to {high}")
            out[key] = float(number)
    return out


def checked_program(value):
    """Workshop's first portable program subset, referencing the product itself.

    Installed monolithic products have no independently addressable shafts.
    Room-authored primary actions can additionally use the full action DSL.
    """
    if not isinstance(value, dict) or set(value) - {"label", "steps"}:
        raise ValueError("primary_use must be {label, steps}")
    label = value.get("label")
    if not isinstance(label, str) or not label.strip() or len(label.strip()) > 60:
        raise ValueError("primary_use needs a label of 1 to 60 characters")
    steps = value.get("steps")
    if not isinstance(steps, list) or not 1 <= len(steps) <= 12:
        raise ValueError("primary_use needs 1 to 12 steps")
    kept = [checked_step(s) for s in steps]
    physical = {s["do"] for s in kept} - {"inspect"}
    if len(physical) > 1:
        raise ValueError("primary_use cannot mix different physical gestures")
    return {"label": label.strip(), "steps": kept}


def selected(actions):
    """Resolve one declaration; old rooms use their first offered program."""
    primary = [a for a in actions if a.get("primary") is True]
    if len(primary) > 1:
        raise ValueError("an object has exactly one primary action")
    return deepcopy(primary[0] if primary else actions[0] if actions else DEFAULT)


def installed(design, root):
    value = design.parameters.get("primary_use")
    program = checked_program(value) if value is not None else deepcopy(DEFAULT)
    for step in program["steps"]:
        if step["do"] == "machine_power":
            from mcp import workshop_machines
            machines = workshop_machines.of(design) or {}
            if len(machines.get(step["device"]+"s",[])) != 1:
                raise ValueError("machine_power needs exactly one declared "+step["device"]+" in this product")
    return dict(program, body=root, primary=True)
