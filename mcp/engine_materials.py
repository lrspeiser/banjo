"""The Python-facing names and densities of Banjo's engine material presets.

The source of truth for physics remains ``src/material/MaterialCatalog.cpp``.
This small mirror exists so Workshop planning can use the same names and masses
before an engine is opened. The parity test pins every density here to the C++
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

#: What each preset is declared to take before it yields or fails, and how stiff
#: it is: the numbers src/material/MaterialCatalog.cpp gives the engine, copied
#: so that a joint's capacity can be worked out before an engine is opened
#: (mcp/product_joints.py). A strength is a declared material property, not a
#: validated failure model; ``yield_strength_pa`` is absent for a material the
#: catalogue declares brittle, which has no yield to reach. The parity test
#: reads the C++ and fails when either side moves alone.
MECHANICS: dict[str, dict[str, float]] = {
    "iron": {"young_modulus_pa": 211.0e9, "poisson_ratio": 0.29, "yield_strength_pa": 200.0e6,
             "tensile_strength_pa": 250.0e6, "compressive_strength_pa": 600.0e6,
             "shear_strength_pa": 170.0e6, "fracture_energy_j_m2": 100000.0},
    "aluminum": {"young_modulus_pa": 68.9e9, "poisson_ratio": 0.33, "yield_strength_pa": 276.0e6,
                 "tensile_strength_pa": 310.0e6, "compressive_strength_pa": 250.0e6,
                 "shear_strength_pa": 207.0e6, "fracture_energy_j_m2": 25000.0},
    "glass": {"young_modulus_pa": 70.0e9, "poisson_ratio": 0.22,
              "tensile_strength_pa": 45.0e6, "compressive_strength_pa": 1000.0e6,
              "shear_strength_pa": 35.0e6, "fracture_energy_j_m2": 8.0},
    "alumina ceramic": {"young_modulus_pa": 300.0e9, "poisson_ratio": 0.22,
                        "tensile_strength_pa": 300.0e6, "compressive_strength_pa": 2200.0e6,
                        "shear_strength_pa": 240.0e6, "fracture_energy_j_m2": 25.0},
    "oak": {"young_modulus_pa": 12.0e9, "poisson_ratio": 0.35, "yield_strength_pa": 45.0e6,
            "tensile_strength_pa": 90.0e6, "compressive_strength_pa": 52.0e6,
            "shear_strength_pa": 11.0e6, "fracture_energy_j_m2": 1000.0,
            "anisotropy_ratio": 8.0},
    "rubber": {"young_modulus_pa": 10.0e6, "poisson_ratio": 0.49, "yield_strength_pa": 6.0e6,
               "tensile_strength_pa": 20.0e6, "compressive_strength_pa": 15.0e6,
               "shear_strength_pa": 3.5e6, "fracture_energy_j_m2": 5000.0},
    "ice": {"young_modulus_pa": 9.0e9, "poisson_ratio": 0.33,
            "tensile_strength_pa": 1.0e6, "compressive_strength_pa": 5.0e6,
            "shear_strength_pa": 1.0e6, "fracture_energy_j_m2": 1.5},
    "concrete": {"young_modulus_pa": 30.0e9, "poisson_ratio": 0.20,
                 "tensile_strength_pa": 3.0e6, "compressive_strength_pa": 35.0e6,
                 "shear_strength_pa": 5.0e6, "fracture_energy_j_m2": 100.0},
}

ALIASES = {
    "aluminium": "aluminum",
    "aluminum_6061_t6": "aluminum",
    "soda_lime_glass": "glass",
    "alumina_ceramic": "alumina ceramic",
    # What a scene calls it (fracture_lab.MATERIALS), and so what a native
    # snapshot says a ceramic body is made of.
    "ceramic": "alumina ceramic",
    "natural_rubber": "rubber",
    "freshwater_ice": "ice",
}


def canonical(name: str) -> str:
    key = str(name).strip().lower()
    return ALIASES.get(key, key)


def known(name: str) -> bool:
    return canonical(name) in MATERIALS


def scene_name(name: str) -> str:
    """What a scene body must call this material.

    The scene vocabulary (fracture_lab.MATERIALS) is this catalogue's, except
    that it says "ceramic" where the catalogue says "alumina ceramic". Handing a
    scene the catalogue's name refused every ceramic product before it ran:
    "material must be one of [... 'ceramic' ...]".
    """
    key = canonical(name)
    return "ceramic" if key == "alumina ceramic" else key


def density(name: str) -> float:
    key = canonical(name)
    try:
        return float(MATERIALS[key]["density_kg_m3"])
    except KeyError as exc:
        raise KeyError(f"{name!r} is not an engine material preset") from exc


def mechanics(name: str) -> dict[str, float]:
    """The preset's declared stiffness and strengths, or a clear refusal."""
    key = canonical(name)
    try:
        # anisotropy_ratio is 1 unless the catalogue gives the material a grain,
        # exactly as MaterialDefinition declares it.
        return {"anisotropy_ratio": 1.0, **MECHANICS[key]}
    except KeyError as exc:
        raise KeyError(f"{name!r} is not an engine material preset, so it has no declared strength") from exc


def engine_name(name: str) -> str:
    """The scene spelling for a supported material, or a clear refusal."""
    key = canonical(name)
    if key not in MATERIALS:
        raise KeyError(f"{name!r} is not an engine material preset")
    # Scene JSON accepts the short preset spelling (oak, glass, aluminum...),
    # while engine_name in MATERIALS records the C++ catalogue definition name.
    return key


def described() -> list[dict[str, Any]]:
    return [{"material": name, **values} for name, values in MATERIALS.items()]


def synchronize_workshop_model() -> None:
    """Make Workshop's cheap mass arithmetic use the engine catalogue values.

    ``mcp.workshop`` now takes the catalogue's density for every engine preset
    its table names, so this changes none of those. What it still adds is the
    engine's own spellings that the table (whose names are also the bench's
    material choices) does not carry, ``aluminum`` and ``ice``. Unsupported
    display-only entries (pine, steel) are left present for old saved designs
    but are not made physically supported.
    """
    from mcp import workshop
    # Register EVERY engine name, not only the ones this table already had.
    # It previously updated existing keys only, and the table spells the metal
    # "aluminium" while the engine and the pricebook spell it "aluminum" -- so
    # the name the bench actually offers was never registered, and
    # WirePart.mass_kg's silent `.get(material, oak)` fallback costed an
    # aluminium leg at oak's 700 kg/m3 instead of 2700. Mass, centre of mass,
    # tip angle and support loads were all a factor of 3.9 out, with the part
    # list cheerfully reading "aluminum".
    for name, values in MATERIALS.items():
        workshop.DENSITY_KG_M3[name] = float(values["density_kg_m3"])
    # Keep the historical British spelling working for saved designs.
    workshop.DENSITY_KG_M3["aluminium"] = density("aluminum")
