"""The admissible parameter space, exposed directly.

The chat route asks a model to author a declaration. This route is for when you
already know what you want: material, target size, mesh resolution, projectile
size and impact speed, compiled through the same public authoring API and
checked against the same engine limits. The point is that a scene the engine
would refuse cannot be built here at all -- `describe` returns the refusal and
the repair before anything runs, and `compile_builder` raises rather than hand
the solver something it will reject.

No solver behaviour, material constant or tolerance is set here. Admission is
not calibration: an admitted scene is one the engine will run, not one whose
material response has been validated.
"""
from __future__ import annotations

import math
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "examples" / "authoring") not in sys.path:
    sys.path.insert(0, str(ROOT / "examples" / "authoring"))
from banjo_authoring import catalog, make_object, make_package  # noqa: E402
import network_admission as admission  # noqa: E402
from network_admission import Inadmissible  # noqa: E402

MATERIALS = [m["id"] for m in catalog()["materials"]]
PROJECTILES = {"iron_ball": "sphere", "iron_cube": "box", "none": None}
SUPPORTS = ("clamped_edges", "free_on_ground")
# The package schema's host-cadence bounds. Total cost barely depends on this:
# substeps per tick scale with dt, so ticks x substeps is nearly constant. It
# changes how finely the recording samples, not how long the run takes.
TICK_RATES_HZ = (240, 480, 960, 1920, 4800)

FIELDS = {"material", "dimensions_m", "resolution", "support", "projectile",
          "projectile_size_m", "impact_speed_m_s", "impact_offset_m",
          "duration_s", "tick_rate_hz"}

DEFAULT = {
    "material": "glass",
    "dimensions_m": [.24, .36, .04],
    # 40 x 40 x 20 mm cells: the most cubic mesh this box admits inside the
    # playground's budget, and the resolution the shipped panel presets use.
    "resolution": [6, 9, 2],
    "support": "clamped_edges",
    "projectile": "iron_ball",
    "projectile_size_m": .08,
    "impact_speed_m_s": 2.0,
    "impact_offset_m": [0.0, 0.0],
    "duration_s": .06,
    "tick_rate_hz": 1920,
}

BUILDER_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": sorted(FIELDS),
    "properties": {
        "material": {"type": "string", "enum": MATERIALS},
        "dimensions_m": {"type": "array", "items": {"type": "number", "minimum": .002,
                                                    "maximum": 1}, "minItems": 3, "maxItems": 3},
        "resolution": {"type": "array", "items": {"type": "integer",
                                                  "minimum": admission.RESOLUTION_MIN,
                                                  "maximum": admission.RESOLUTION_MAX},
                       "minItems": 3, "maxItems": 3},
        "support": {"type": "string", "enum": list(SUPPORTS)},
        "projectile": {"type": "string", "enum": sorted(PROJECTILES)},
        "projectile_size_m": {"type": "number", "minimum": .012, "maximum": .3},
        "impact_speed_m_s": {"type": "number", "minimum": 0, "maximum": 20},
        "impact_offset_m": {"type": "array", "items": {"type": "number"},
                            "minItems": 2, "maxItems": 2},
        "duration_s": {"type": "number", "minimum": .005, "maximum": 1},
        "tick_rate_hz": {"type": "integer", "enum": list(TICK_RATES_HZ)},
    },
}


def _number(value, low, high, label):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{label} must be a finite number in [{low}, {high}]")
    return float(value)


def validate_builder(spec: Any) -> dict[str, Any]:
    """Check every field against its bound. Returns a normalised copy."""
    if not isinstance(spec, dict):
        raise ValueError("Builder specification must be an object")
    unknown = set(spec) - FIELDS
    if unknown:
        raise ValueError(f"Unknown builder fields: {sorted(unknown)}")
    result = dict(DEFAULT)
    result.update(spec)
    if result["material"] not in MATERIALS:
        raise ValueError(f"material must be one of {MATERIALS}")
    dimensions = result["dimensions_m"]
    if not isinstance(dimensions, list) or len(dimensions) != 3:
        raise ValueError("dimensions_m requires three SI values")
    result["dimensions_m"] = [_number(v, .002, 1, "dimensions_m") for v in dimensions]
    resolution = result["resolution"]
    if (not isinstance(resolution, list) or len(resolution) != 3 or
            any(type(v) is not int or not admission.RESOLUTION_MIN <= v <= admission.RESOLUTION_MAX
                for v in resolution)):
        raise ValueError(f"resolution requires three integers in "
                         f"[{admission.RESOLUTION_MIN}, {admission.RESOLUTION_MAX}]")
    result["resolution"] = [int(v) for v in resolution]
    if result["support"] not in SUPPORTS:
        raise ValueError(f"support must be one of {list(SUPPORTS)}")
    if result["projectile"] not in PROJECTILES:
        raise ValueError(f"projectile must be one of {sorted(PROJECTILES)}")
    result["projectile_size_m"] = _number(result["projectile_size_m"], .012, .3, "projectile_size_m")
    result["impact_speed_m_s"] = _number(result["impact_speed_m_s"], 0, 20, "impact_speed_m_s")
    offset = result["impact_offset_m"]
    if not isinstance(offset, list) or len(offset) != 2:
        raise ValueError("impact_offset_m requires two SI values")
    half = [result["dimensions_m"][0] / 2, result["dimensions_m"][1] / 2]
    result["impact_offset_m"] = [_number(offset[0], -half[0], half[0], "impact_offset_m[0]"),
                                 _number(offset[1], -half[1], half[1], "impact_offset_m[1]")]
    result["duration_s"] = _number(result["duration_s"], .005, 1, "duration_s")
    if result["tick_rate_hz"] not in TICK_RATES_HZ:
        raise ValueError(f"tick_rate_hz must be one of {list(TICK_RATES_HZ)}")
    return result


def steps_for(spec: dict[str, Any]) -> int:
    """Host ticks the recorder is asked for, inside its own 1..1440 bound."""
    return max(1, min(1440, round(spec["duration_s"] * spec["tick_rate_hz"])))


def compile_builder(spec: Any) -> dict[str, Any]:
    """Turn a validated specification into a package the engine will accept.

    Raises `Inadmissible` rather than emitting a package the solver refuses, so
    the run button cannot start a scene that was never going to load.
    """
    spec = validate_builder(spec)
    report = describe_geometry(spec)
    if not report["admissible"]:
        first = report["problems"][0]
        raise Inadmissible(first["message"], limit=first["limit"],
                           repair=report.get("suggested_resolution"))
    dimensions = spec["dimensions_m"]
    thickness = dimensions[2]
    clamped = spec["support"] == "clamped_edges"
    # The target lies flat: a +90 degree rotation about x turns the box's local
    # thickness axis into the world vertical, matching the drop route's fixture.
    target_y = .18 if clamped else thickness / 2
    preset = {"glass": "glass_panel", "oak": "wood_panel", "iron": "iron_panel"}.get(
        spec["material"], "glass_panel")
    target = make_object(
        preset, 1, material=spec["material"], name=f"{spec['material']} target",
        dimensions_m=list(dimensions), resolution=list(spec["resolution"]),
        position_m=[0.0, target_y, 0.0],
        orientation_wxyz=[math.sqrt(.5), math.sqrt(.5), 0.0, 0.0],
        representation="network", velocity_m_s=[0.0, 0.0, 0.0], spin_rad_s=[0.0, 0.0, 0.0],
        pin_boundary=clamped)
    target.pop("grain_wxyz", None)
    objects = [target]
    if spec["projectile"] != "none":
        size = spec["projectile_size_m"]
        objects.append(make_object(
            spec["projectile"], 2, name="striker",
            dimensions_m=[size, size, size],
            position_m=[spec["impact_offset_m"][0],
                        target_y + thickness / 2 + size / 2 + .002,
                        spec["impact_offset_m"][1]],
            velocity_m_s=[0.0, -spec["impact_speed_m_s"], 0.0],
            spin_rad_s=[0.0, 0.0, 0.0]))
    package = make_package(
        objects,
        name=(f"{spec['material']} {int(dimensions[0]*1000)}x{int(dimensions[1]*1000)}x"
              f"{round(thickness*1000)} mm, {spec['resolution']}, "
              f"{spec['impact_speed_m_s']:g} m/s"),
        fixed_dt_s=1.0 / spec["tick_rate_hz"],
        ground={"half_length_m": 4.0, "half_width_m": 4.0, "friction": .4},
        damage_integration={"maximum_depth": 2, "maximum_damage_increment": .05,
                            "maximum_plastic_strain_increment": .002,
                            "maximum_brittle_opening_overshoot": .05, "on_limit": "reject"})
    return package


def describe_geometry(spec: Any) -> dict[str, Any]:
    """Admission verdict for the target box, before anything is compiled."""
    spec = validate_builder(spec)
    return admission.describe_geometry(
        spec["dimensions_m"], spec["resolution"], label="Target",
        max_cells=min(admission.OBJECT_CELL_BUDGET, admission.PLAYGROUND_CELL_BUDGET))


def describe(spec: Any) -> dict[str, Any]:
    """Everything the builder panel needs: verdict, repair and cost.

    Always returns; never raises for a well-formed but inadmissible setup, so
    the panel can show the reason and the nearest workable resolution instead of
    an error string.
    """
    spec = validate_builder(spec)
    steps = steps_for(spec)
    geometry = describe_geometry(spec)
    result = {"spec": spec, "steps": steps, "geometry": geometry,
              "admissible": geometry["admissible"], "problems": list(geometry["problems"]),
              "notes": []}
    if geometry["admissible"]:
        package = compile_builder(spec)
        result["package"] = package
        result["cost"] = admission.cost_estimate(package, steps)
        if result["cost"]["recording_over_budget"]:
            result["admissible"] = False
            result["problems"].append({
                "limit": "recording_bytes",
                "message": (
                    f"The recording would be about "
                    f"{result['cost']['estimated_recording_mb']:.0f} MB and the recorder refuses "
                    f"anything over 64 MB - after running the whole scene. Reduce the cell count "
                    f"or shorten the run.")})
        if result["cost"]["limited_by_budget"]:
            result["notes"].append({
                "limit": "maximum_substeps_per_tick",
                "message": (
                    f"This lattice needs {result['cost']['required_substeps']} internal solves "
                    f"per tick and the engine caps them at "
                    f"{admission.MAX_STABILITY_SUBSTEPS}. It will run and report itself as "
                    f"under-resolved; the material state is not trustworthy.")})
    else:
        suggestion = geometry.get("suggested_resolution")
        if suggestion:
            fixed = dict(spec, resolution=list(suggestion))
            result["repair"] = {"resolution": list(suggestion),
                                "cost": admission.cost_estimate(compile_builder(fixed),
                                                                steps_for(fixed))}
        else:
            result["repair"] = {"dimensions": admission.buildable_dimensions(spec["dimensions_m"])}
    return result
