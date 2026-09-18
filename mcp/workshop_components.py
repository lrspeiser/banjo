"""Workshop component API with persisted skin and mechanical-model overrides.

The tested component implementation remains in ``workshop_components_core``.
This compatibility layer widens component overrides with orthogonal
``skin`` and ``mechanics`` fields.  Core geometry ignores those fields; the Workshop visual compiler
uses it for appearance and, only when explicitly marked physical, matter
recompilation.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from . import workshop_components_core as _core
from .workshop_components_core import *  # noqa: F401,F403
from .workshop_visual import checked_skin
from .workshop_rigid import checked_mechanics

_BASE_CHECKED = _core.checked_overrides
_BASE_CHANGED = _core._changed


def checked_overrides(value: Any) -> dict[str, dict[str, Any]]:
    if value in (None, {}):
        return {}
    if not isinstance(value, dict) or len(value) > 250:
        raise ValueError("component_overrides must be an object with at most 250 parts")
    stripped: dict[str, dict[str, Any]] = {}
    skins: dict[str, dict[str, Any]] = {}
    mechanics: dict[str, dict[str, str]] = {}
    for name, patch in value.items():
        if not isinstance(patch, dict):
            raise ValueError("each component override needs a short part name and an object")
        stripped[str(name)] = {k: deepcopy(v) for k, v in patch.items() if k not in {"skin", "mechanics"}}
        if "mechanics" in patch:
            mechanics[str(name)] = checked_mechanics(patch["mechanics"])
        if "skin" in patch:
            skins[str(name)] = checked_skin(patch.get("skin"))
    checked = _BASE_CHECKED(stripped)
    for name, skin in skins.items():
        checked.setdefault(name, {})["skin"] = skin
    for name, model in mechanics.items():
        checked.setdefault(name, {})["mechanics"] = model
    return checked


def _changed(part, patch):
    return _BASE_CHANGED(part, {k: v for k, v in patch.items() if k not in {"skin", "mechanics"}})


# The core functions resolve these globals at call time, so both direct callers
# and old imports automatically accept/preserve skin and mechanical overrides.
_core.checked_overrides = checked_overrides
_core._changed = _changed

# Re-export the public core functions explicitly after the monkey-patch.
apply_overrides = _core.apply_overrides
design_from_spec = _core.design_from_spec
edit = _core.edit
component_recipe = _core.component_recipe
replace_with_recipe = _core.replace_with_recipe
