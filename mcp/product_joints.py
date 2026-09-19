"""What a declared joint can carry: material strength over measured contact.

A joint of a built design (mcp/workshop_construction.py) says which two parts
it holds, what it does to their motion and how it is made. This module gives it
numbers, and only ones that follow from something declared elsewhere:

* the contact is measured from the parts as they stand -- an area with its
  second moments, or a shaft's diameter and how much of it lies in the bore;
* the strengths are the engine catalogue's, of the WEAKER of the two materials
  (mcp/engine_materials.py, pinned to src/material/MaterialCatalog.cpp).

* what the joint itself keeps of that material, by how it was made
  (:mod:`mcp.joint_efficiency`) -- a glue line is not the wood it joins.

So a joint is taken to hold, over the whole contact, the weaker material's
strength times what its own making leaves of it, with stress uniform under
direct load and linear under bending. Without the third term that is the
engine's own rule for a fixing made of a member (``tensile_strength_pa * area``,
``shear_strength_pa * area``; LiveWorld ``setJointMember``), extended to
bending, which a fixing does not check. The engine reads the same third term
as a scene ``interfaces`` block, so the bench and the world agree.

Not modelled, and said in every answer: glue or weld metal weaker or stronger
than the parts, fasteners, stress concentration at a corner, fatigue, and a
bearing's hold along its own axis.
"""
from __future__ import annotations

from math import hypot, pi
from typing import Any

from mcp import engine_materials, joint_efficiency
from mcp.workshop import WirePart

CAPACITY_SCHEMA = "banjo.joint-capacity.v1"

NOT_MODELLED = (
    "an adhesive, weld or fastener weaker or stronger than the parts it joins",
    "stress concentration at corners and edges",
    "fatigue and creep",
)


def _weaker(a: WirePart, b: WirePart) -> dict[str, Any]:
    ma, mb = engine_materials.mechanics(a.material), engine_materials.mechanics(b.material)
    out: dict[str, Any] = {}
    for key in ("tensile_strength_pa", "compressive_strength_pa", "shear_strength_pa"):
        weaker = a if ma[key] <= mb[key] else b
        out[key] = min(ma[key], mb[key])
        out[key.replace("_strength_pa", "_governed_by")] = f"{weaker.name} ({engine_materials.canonical(weaker.material)})"
    return out


def capacity(joint: dict[str, Any], a: WirePart, b: WirePart) -> dict[str, Any]:
    """The loads a closed joint can carry, in newtons and newton metres.

    ``joint`` is a row of ``workshop_construction.joints(design)``; ``a`` and
    ``b`` are its two parts. An open joint carries nothing and is refused.
    """
    if joint.get("open") or not joint.get("interface"):
        raise ValueError(f"joint {joint.get('id')} is open: its parts do not touch, so it carries nothing")
    how = joint["interface"]
    try:
        strength = _weaker(a, b)
    except KeyError as problem:
        return {"schema": CAPACITY_SCHEMA, "joint": joint["id"], "rated": False,
                "why": str(problem).strip("'\"")}
    # What the joint's own making leaves of the material it joins. The engine is
    # handed these same three numbers and leaves the bonds crossing the joint
    # with exactly that share, so neither side can drift.
    keeps = joint_efficiency.efficiency(joint, a, b)
    tensile = strength["tensile_strength_pa"] * keeps["tension"]
    crushing = strength["compressive_strength_pa"] * keeps["compression"]
    shear = strength["shear_strength_pa"] * keeps["shear"]
    out: dict[str, Any] = {"schema": CAPACITY_SCHEMA, "joint": joint["id"], "rated": True,
                           "kind": joint["kind"], "method": joint["method"], "form": how["form"],
                           "strength": strength, "efficiency": keeps,
                           "not_modelled": list(NOT_MODELLED) + list(keeps["not_modelled"])}

    if how["form"] == "planar":
        if joint["kind"] == "bearing":
            # A flat turning joint needs a pivot this model does not have.
            return {**out, "rated": False,
                    "why": "a turning joint on a flat face has no pivot to rate; run a shaft into the part instead"}
        area, i_uu, i_vv = float(how["area_m2"]), float(how["i_uu_m4"]), float(how["i_vv_m4"])
        half_u, half_v = float(how["half_u_m"]), float(how["half_v_m"])
        reach = hypot(half_u, half_v)
        out.update({
            "area_m2": area,
            "tension_n": tensile * area, "compression_n": crushing * area, "shear_n": shear * area,
            # Bending about the patch's u axis loads its far edge in v, and the other way about.
            "bending_u_n_m": tensile * i_uu / half_v if half_v > 0 else 0.0,
            "bending_v_n_m": tensile * i_vv / half_u if half_u > 0 else 0.0,
            "torsion_n_m": shear * (i_uu + i_vv) / reach if reach > 0 else 0.0,
            "crush_over_tension": crushing / tensile,
            "engine_fixing": {"axis": list(how["normal"]), "holds_tension_n": tensile * area,
                              "holds_shear_n": shear * area,
                              "unchecked_by_the_engine": ["bending", "torsion", "crushing"]},
            "assumes": "a bond as strong as the weaker material over the whole contact; stress uniform "
                       "under direct load and linear under bending",
        })
        return out

    diameter, engaged = float(how["diameter_m"]), float(how["engaged_m"])
    shaft = a if how["shaft"] == a.name else b
    shaft_shear = (engine_materials.mechanics(shaft.material)["shear_strength_pa"]
                   * keeps["shear"] * pi * diameter ** 2 / 4.0)
    bearing_on_bore = crushing * diameter * engaged
    out.update({
        "diameter_m": diameter, "engaged_m": engaged,
        "radial_n": min(bearing_on_bore, shaft_shear),
        "radial_governed_by": ("the shaft shearing across" if shaft_shear < bearing_on_bore
                               else "the bore crushing under the shaft"),
        "prying_n_m": crushing * diameter * engaged ** 2 / 6.0,
        "assumes": "bearing pressure uniform over the projected area d x L under a radial load and linear "
                   "along the bore under prying; the shaft in single shear",
    })
    if joint["kind"] == "bearing":
        out.update({"axial_n": None, "torque_n_m": 0.0,
                    "not_modelled": list(NOT_MODELLED) + ["what holds a turning shaft along its own axis"]})
    else:
        grip = shear * pi * diameter * engaged
        out.update({"axial_n": grip, "torque_n_m": grip * diameter / 2.0,
                    "engine_fixing": {"axis": list(how["axis"]), "holds_tension_n": grip,
                                      "holds_shear_n": out["radial_n"],
                                      "unchecked_by_the_engine": ["prying", "twisting loose"]}})
    return out


def utilisation(rated: dict[str, Any], load: dict[str, float]) -> dict[str, Any]:
    """How much of a joint's capacity a load uses, and what would give first.

    ``load`` is what the joint transmits, in the joint's own frame:
    ``axial_n`` (positive pulls the parts apart), ``shear_n``, and for a flat
    joint ``moment_u_n_m``, ``moment_v_n_m``, ``torsion_n_m``; for a shaft
    ``prying_n_m`` and ``torsion_n_m``. One is all of the capacity.
    """
    if not rated.get("rated"):
        return {"rated": False, "why": rated.get("why")}
    axial, across = float(load.get("axial_n", 0.0)), abs(float(load.get("shear_n", 0.0)))
    twist = abs(float(load.get("torsion_n_m", 0.0)))
    modes: dict[str, float] = {}
    if rated["form"] == "planar":
        bend = (abs(float(load.get("moment_u_n_m", 0.0))) / rated["bending_u_n_m"] if rated["bending_u_n_m"] else 0.0) + \
               (abs(float(load.get("moment_v_n_m", 0.0))) / rated["bending_v_n_m"] if rated["bending_v_n_m"] else 0.0)
        # The far fibre's stress over the strength: direct load plus bending,
        # which is exact for a linear stress distribution.
        modes["pulled apart"] = max(0.0, axial) / rated["tension_n"] + bend
        modes["crushed"] = max(0.0, -axial) / rated["compression_n"] + bend / rated["crush_over_tension"]
        modes["sheared"] = across / rated["shear_n"] + (twist / rated["torsion_n_m"] if rated["torsion_n_m"] else 0.0)
    else:
        pry = abs(float(load.get("prying_n_m", 0.0)))
        modes["sheared across the shaft" if rated["radial_governed_by"].startswith("the shaft")
              else "crushed in its bore"] = across / rated["radial_n"] + (pry / rated["prying_n_m"] if rated["prying_n_m"] else 0.0)
        if rated.get("axial_n"):
            modes["pulled out"] = abs(axial) / rated["axial_n"]
            modes["twisted loose"] = twist / rated["torque_n_m"] if rated["torque_n_m"] else 0.0
    worst = max(modes, key=lambda name: modes[name])
    return {"rated": True, "utilisation": modes[worst], "would_be": worst,
            "modes": {name: round(value, 6) for name, value in modes.items()}}
