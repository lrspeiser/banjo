"""Materials admitted to the playable game, separate from research presets.

This is a product boundary, not a new material law. Historical oak/rubber
experiments remain available outside named worlds and the new-game scene.
Coal is a raw resource; this module does not invent a native coal body preset.
"""
from __future__ import annotations

from typing import Any
from copy import deepcopy
from mcp import engine_materials

POLICY = "inorganic-v1"
_BODIES = ("iron", "aluminum", "glass", "alumina ceramic", "ice", "concrete")
_RAW = frozenset(_BODIES) | frozenset({
    "soil", "sand", "clay", "rock", "water", "coal", "carbon", "limestone",
    "copper", "copper ore", "copper wire", "iron ore", "bauxite", "silica",
    "quartz", "alumina", "cement", "steel", "aluminum wire",
})


def active(app: Any) -> bool:
    return bool(getattr(app, "world_id", None) or
                getattr(getattr(app, "room", None), "scene", None) == "new-game")


def body_materials() -> tuple[str, ...]:
    return _BODIES


def recipe_spec(app: Any, spec: dict[str, Any]) -> dict[str, Any]:
    """Supply game defaults for a new source, retaining explicit user values."""
    if not active(app):
        return deepcopy(spec)
    import playable_recipes
    require_payload(app, spec)
    result = playable_recipes.recipe(spec["kind"], design_id=spec.get("design_id"),
                                     parameters=deepcopy(spec.get("parameters") or {}))
    overrides = result.setdefault("component_overrides", {})
    for name, changes in (spec.get("component_overrides") or {}).items():
        if isinstance(changes, dict) and isinstance(overrides.get(name), dict):
            overrides[name] = {**overrides[name], **deepcopy(changes)}
        else:
            overrides[name] = deepcopy(changes)
    if spec.get("purpose") is not None: result["purpose"] = spec["purpose"]
    require_payload(app, result)
    return result


def allowed(name: Any) -> bool:
    return engine_materials.canonical(name) in _RAW


def require_material(app: Any, name: Any, *, body: bool = True) -> None:
    if not active(app):
        return
    material = engine_materials.canonical(name)
    if material not in (_BODIES if body else _RAW):
        raise ValueError(f"{name!r} is unavailable in the game. Use metal or an "
                         "inorganic material; organic material physics is deferred.")


def require_design(app: Any, design: Any) -> None:
    if active(app):
        for part in design.parts:
            require_material(app, part.material)


def require_item(app: Any, payload: Any, item_type: str) -> None:
    require_payload(app, payload)
    if not active(app):
        return
    if item_type == "assembly":
        from mcp import workshop_components
        design, _ = workshop_components.design_from_spec(payload)
        require_design(app, design)
    elif item_type == "component":
        from mcp.workshop_construction import template_part
        part = template_part({"name": "material-policy-check", "recipe": payload})
        require_material(app, part.material)


def item_allowed(app: Any, payload: Any, item_type: str) -> bool:
    try:
        require_item(app, payload, item_type)
        return True
    except (ValueError, KeyError, TypeError):
        return False


def saved_designs(app: Any, folder: Any, *, limit: int = 200) -> list[dict[str, Any]]:
    """Leave retired source files intact, while excluding them from game picks."""
    import workshop_store
    rows = workshop_store.list_saved(folder, limit=limit)
    if not active(app):
        return rows
    result = []
    for row in rows:
        try:
            _, design = workshop_store.load(folder, row["design_id"])
            require_design(app, design)
            result.append(row)
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return result


def require_payload(app: Any, payload: Any) -> None:
    """Check declared materials before a library/chat write has side effects."""
    if not active(app):
        return
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key == "material" and isinstance(value, str):
                require_material(app, value)
            else:
                require_payload(app, value)
    elif isinstance(payload, (list, tuple)):
        for value in payload:
            require_payload(app, value)


def require_spec(spec: dict[str, Any]) -> None:
    """Refuse a legacy organic world without rewriting its physical history."""
    invalid = set()
    def body_materials_in(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "material" and isinstance(child, str):
                    yield engine_materials.canonical(child)
                else:
                    yield from body_materials_in(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                yield from body_materials_in(child)
    for key in ("bodies", "precise_rigid_bodies"):
        for body in spec.get(key) or []:
            invalid.update(m for m in body_materials_in(body) if m not in _BODIES)
    goods = spec.get("goods") or {}
    for pile in goods.get("stockpiles") or []:
        invalid.update(m for m in (pile.get("holds") or {}) if not allowed(m))
    for deposit in goods.get("deposits") or []:
        if not allowed(deposit.get("substance")):
            invalid.add(str(deposit.get("substance")))
    if invalid:
        raise ValueError("This saved world uses retired materials (" +
                         ", ".join(sorted(invalid)) + "). Its save is preserved. "
                         "Choose New game for a world made of inorganic materials.")


def instructions() -> str:
    return ("PLAYABLE MATERIAL POLICY: use only iron, aluminum, glass, alumina ceramic, "
            "ice or concrete for physical components. No wood, oak, rubber, plastics, "
            "leather or other organic components. Coal remains an allowed raw resource; "
            "do not substitute wood or claim a native coal body/combustion law. Use "
            "actual preset density and suitable geometry for metal tools. If an organic "
            "design is requested, explain the restriction and propose an inorganic version.")
