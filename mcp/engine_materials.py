"""The Python-facing names and densities of Banjo's engine material presets.

The source of truth for physics remains ``src/material/MaterialCatalog.cpp``.
This small mirror exists so Workshop planning can use the same names and masses
before an engine is opened.  The parity test pins every density here to the C++
catalogue values; adding a material requires changing both deliberately.
"""
from __future__ import annotations

from typing import Any

MATERIALS: dict[str, dict[str, Any]] = {
    "iron": {"engine_name": "iron", "density_kg_m3": 7870.0},
    "aluminum": {"engine_name": "aluminum_6061_t6", "density_kg_m3": 2700.0},
    "glass": {"engine_name": "soda_lime_glass", "density_kg_m3": 2500.0},
    "alumina ceramic": {"engine_name": "alumina_ceramic", "density_kg_m3": 3900.0},
    "oak": {"engine_name": "oak", "density_kg_m3": 700.0},
    "rubber": {"engine_name": "natural_rubber", "density_kg_m3": 1100.0},
    "ice": {"engine_name": "freshwater_ice", "density_kg_m3": 917.0},
    "concrete": {"engine_name": "concrete", "density_kg_m3": 2400.0},
}

ALIASES = {
    "aluminium": "aluminum",
    "aluminum_6061_t6": "aluminum",
    "soda_lime_glass": "glass",
    "alumina_ceramic": "alumina ceramic",
    "natural_rubber": "rubber",
    "freshwater_ice": "ice",
}


def canonical(name: str) -> str:
    key = str(name).strip().lower()
    return ALIASES.get(key, key)


def known(name: str) -> bool:
    return canonical(name) in MATERIALS


def density(name: str) -> float:
    key = canonical(name)
    try:
        return float(MATERIALS[key]["density_kg_m3"])
    except KeyError as exc:
        raise KeyError(f"{name!r} is not an engine material preset") from exc


def engine_name(name: str) -> str:
    key = canonical(name)
    try:
        # Scene JSON accepts the preset spelling, not the long definition name.
        return key
    except KeyError as exc:
        raise KeyError(f"{name!r} is not an engine material preset") from exc


def described() -> list[dict[str, Any]]:
    return [{"material": name, **values} for name, values in MATERIALS.items()]


def synchronize_workshop_model() -> None:
    """Make Workshop's cheap mass arithmetic use the engine catalogue values.

    This is a migration bridge while ``mcp.workshop`` still owns its historical
    display-material table. Unsupported display-only entries (pine, steel) are
    left present for old saved designs but are not made physically supported.
    """
    from mcp import workshop
    for name, values in MATERIALS.items():
        if name in workshop.DENSITY_KG_M3:
            workshop.DENSITY_KG_M3[name] = float(values["density_kg_m3"])
    if "aluminium" in workshop.DENSITY_KG_M3:
        workshop.DENSITY_KG_M3["aluminium"] = density("aluminum")
