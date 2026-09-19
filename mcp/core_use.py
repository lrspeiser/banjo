"""Saved primary-use programs. No arbitrary code or prescribed body velocity."""
from __future__ import annotations

from copy import deepcopy
import math

# These additional hand primitives share validation between Workshop, saved
# rooms and MCP. Existing action primitives retain their richer MCP checks.
STEPS = ("inspect", "strike", "push_forward")
DEFAULT = {"label": "Inspect", "steps": [{"do": "inspect"}]}


def checked_step(value):
    if not isinstance(value, dict) or value.get("do") not in STEPS:
        raise ValueError("core step must be inspect, strike or push_forward")
    do = value["do"]
    allowed = {"do"} if do == "inspect" else {"do", "distance_m", "speed_m_s"}
    if set(value) - allowed:
        raise ValueError(f"{do} cannot say {sorted(set(value) - allowed)}")
    out = {"do": do}
    if do != "inspect":
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
        raise ValueError("primary_use cannot mix held strikes with an empty-hand push")
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
    return dict(program, body=root, primary=True)
