"""Bounded Banjo playground language; compiles through the public authoring API.

Model output is data. It cannot supply Python, shell commands, file paths,
material-law code, credentials, or executable names.
"""
from __future__ import annotations
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "examples" / "authoring"))
from banjo_authoring import catalog, make_object, make_package

KINDS = ["panel_impact", "plate_drop", "rigid_drop", "knife_cut", "custom_objects",
         "thermal_frontier", "material_state_reference", "continuum_pressure_reference",
         "glass_reference", "unsupported"]
PRESETS = list(catalog()["object_presets"])
LIMITATIONS = [
    "Network fracture is experimental: glass/oak/iron realism and timestep/contact convergence remain open.",
    "Strict damage limits halt unresolved mechanical trials instead of presenting unstable fragmentation as valid.",
    "Tempered-glass calibration, collision-driven metal dents and complete tomato slicing are not implemented.",
    "J2 plasticity, compact state/history and bounded property variation are reference modules, not live-world capabilities.",
    "Network studios execute a fresh simulation; continuum native viewing replays the solved load sequence."
]

def obj(properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}

VECTOR = {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3}
SCHEMA = obj({
    "language": {"type": "string", "enum": ["banjo-playground-1"]},
    "name": {"type": "string"},
    "experiment": {"type": "string", "enum": KINDS},
    "explanation": {"type": "string"},
    "limitations": {"type": "array", "items": {"type": "string"}},
    "speeds_m_s": {"type": "array", "items": {"type": "number"}},
    "heights_m": {"type": "array", "items": {"type": "number"}},
    "duration_s": {"type": "number"},
    "projectile": {"type": "string", "enum": ["iron_ball", "iron_cube", "knife", "axe_head"]},
    "panel_dimensions_m": VECTOR,
    "objects": {"type": "array", "items": obj({
        "preset": {"type": "string", "enum": PRESETS},
        "position_m": VECTOR, "velocity_m_s": VECTOR,
        "dimensions_m": {"anyOf": [VECTOR, {"type": "null"}]},
    })},
})

SYSTEM = """You author experiments in Banjo's bounded SI playground language.
Output ONLY the structured plan. Use the previous plan to understand revisions.
Capabilities: panel_impact compares iron projectile against glass/oak/iron clamped panels at 1..4 speeds (0..20 m/s).
plate_drop drops an iron ball/cube onto horizontal clamped glass/oak/iron panels at 1..4 heights (0..2 m).
rigid_drop drops the selected projectile onto unpinned rigid glass/oak/iron boxes under gravity with a ground plane. It disables fracture and has no clamps. If the user requests rigid controls or no fracture, choose rigid_drop directly, not plate_drop.
knife_cut is the existing coarse tomato tissue proxy plus a downward knife and separate glass/oak/iron panel controls. The different shapes/load directions are not a material-only matched comparison; partial damage, not calibrated slicing.
custom_objects accepts up to12 preset objects; position/velocity/dimensions only. Include material controls if comparing behavior.
thermal_frontier runs the existing glass/oak/iron/water-ice heat-frontier fixture (fixed parameters).
material_state_reference runs a prescribed-shear J2 coupon and compact save/reload/history benchmark (fixed parameters); NOT a spatial dent simulation.
continuum_pressure_reference runs the fixed spatial quasistatic glass/oak/iron pressure load-unload fixture: a 40x20x40mm P1 tetrahedral patch, bottom clamp, central 20x20mm pressure, resolution 4, 32 increments each way and 800MPa peak. It has no collision, inertia or fracture, uses illustrative uncalibrated laws, and oak may stop at a strict solver limit.
glass_reference shows the documented 6mm tempered pane 4.11kg steelball staircase experiment and missing validation gates; NOT a claimed recreation.
Unsupported requests use experiment=unsupported and explain the missing capability.
Never claim realistic/calibrated glass shattering, full wood grain, collision-driven metal dents, full tomato slicing, gameplay repair, live-world persistence, fire spreading through arbitrary geometry, or fluids. These are goals, not implemented capabilities.
Do not silently substitute a thick/annealed panel for a requested calibrated thin tempered-glass experiment: use glass_reference.
Default panel_dimensions_m=[0.24,0.36,0.04], duration_s=1, projectile=iron_ball. Duration must be .05..3s.
For every experiment except custom_objects, objects MUST be []: the compiler supplies the matched layout. Do not put unused object declarations into a template plan.
Network panel dimension bounds: first two .08..1m; thickness .012..0.15m. Thin glass reference is separate.
Use speeds [2] for a default panel test; heights [.25] for a default drop. Other unused arrays may be empty.
For continuum_pressure_reference set speeds_m_s=[], heights_m=[] and objects=[]. duration_s, projectile and panel_dimensions_m remain required banjo-playground-1 fields but are explicitly ignored and cannot alter the fixed native fixture.
Keep explanations concise and describe strict solver limits honestly. No fixture is calibrated. Do not invent supports, extra trials or scope. No material strength tuning or random forces.
"""

def number(value, low, high, label):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{label} must be finite in [{low}, {high}]")
    return float(value)

def vector(value, low, high, label):
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(f"{label} requires three SI components")
    return [number(x, low, high, label) for x in value]

def validate_plan(plan):
    if not isinstance(plan, dict) or set(plan) != set(SCHEMA["properties"]):
        raise ValueError("Unknown or missing playground language fields")
    if plan["language"] != "banjo-playground-1" or plan["experiment"] not in KINDS:
        raise ValueError("Unsupported playground language or experiment")
    for field, limit in [("name", 120), ("explanation", 2500)]:
        if not isinstance(plan[field], str) or not 1 <= len(plan[field]) <= limit:
            raise ValueError(f"Invalid {field}")
    if not isinstance(plan["limitations"], list) or len(plan["limitations"]) > 12 or any(
            not isinstance(x, str) or len(x) > 1000 for x in plan["limitations"]):
        raise ValueError("Invalid limitations")
    if plan["projectile"] not in ("iron_ball", "iron_cube", "knife", "axe_head"):
        raise ValueError("Unsupported projectile")
    number(plan["duration_s"], .05, 3, "duration_s")
    for field, upper in [("speeds_m_s", 20), ("heights_m", 2)]:
        if not isinstance(plan[field], list) or len(plan[field]) > 4:
            raise ValueError("At most four sweep cases are admitted")
        for value in plan[field]: number(value, 0, upper, field)
    dims = vector(plan["panel_dimensions_m"], .001, 1, "panel_dimensions_m")
    if plan["experiment"] in ("panel_impact", "plate_drop", "rigid_drop", "knife_cut") and (
            min(dims[:2]) < .08 or not .012 <= dims[2] <= .15):
        raise ValueError("Panel needs sides .08..1m and thickness .012..0.15m; thin tempered glass has a separate reference gate")
    if not isinstance(plan["objects"], list) or len(plan["objects"]) > 12:
        raise ValueError("At most twelve custom objects are admitted")
    for entry in plan["objects"]:
        if not isinstance(entry, dict) or set(entry) != {"preset", "position_m", "velocity_m_s", "dimensions_m"}:
            raise ValueError("Unknown or missing object fields")
        if entry["preset"] not in PRESETS: raise ValueError("Unknown object preset")
        vector(entry["position_m"], -3, 3, "position_m")
        vector(entry["velocity_m_s"], -20, 20, "velocity_m_s")
        if entry["dimensions_m"] is not None: vector(entry["dimensions_m"], .012, 1, "dimensions_m")
    required = "speeds_m_s" if plan["experiment"] in ("panel_impact", "knife_cut") else "heights_m"
    if plan["experiment"] in ("panel_impact", "plate_drop", "rigid_drop", "knife_cut") and not plan[required]:
        raise ValueError(f"{plan['experiment']} requires at least one {required} value")
    if plan["experiment"] == "custom_objects" and not plan["objects"]:
        raise ValueError("Custom experiment needs objects")
    if plan["experiment"] != "custom_objects" and plan["objects"]:
        raise ValueError("Template experiments require objects=[]; choose custom_objects to author an explicit layout")
    if plan["experiment"] in ("plate_drop", "rigid_drop") and plan["projectile"] not in ("iron_ball", "iron_cube"):
        raise ValueError("Drop trials currently admit an iron ball or cube")
    if plan["experiment"] == "continuum_pressure_reference" and (plan["speeds_m_s"] or plan["heights_m"]):
        raise ValueError("continuum_pressure_reference is fixed; speed and height sweeps must be empty")
    return plan

def compile_plan(plan):
    validate_plan(plan)
    kind = plan["experiment"]
    if kind in ("unsupported", "glass_reference", "thermal_frontier", "material_state_reference",
                "continuum_pressure_reference"):
        return []
    parameters = plan["speeds_m_s"] if kind in ("panel_impact", "knife_cut") else plan["heights_m"]
    if kind == "custom_objects": parameters = [None]
    packages = []
    for parameter in parameters:
        objects = []
        if kind == "custom_objects":
            for index, entry in enumerate(plan["objects"]):
                args = {k: entry[k] for k in ("position_m", "velocity_m_s")}
                if entry["dimensions_m"] is not None: args["dimensions_m"] = entry["dimensions_m"]
                objects.append(make_object(entry["preset"], index+1, **args))
        else:
            dims = plan["panel_dimensions_m"]
            lane_spacing = max(.45, dims[0]+.2)
            for lane, preset in enumerate(("glass_panel", "wood_panel", "iron_panel")):
                x = (lane-1)*lane_spacing
                panel = make_object(preset, lane*2+1, dimensions_m=dims)
                projectile = make_object(plan["projectile"], lane*2+2)
                if kind in ("plate_drop", "rigid_drop"):
                    panel.update(position_m=[x,.18,0], orientation_wxyz=[math.sqrt(.5),math.sqrt(.5),0,0])
                    if kind == "rigid_drop":
                        panel.update(representation="rigid")
                        panel.pop("resolution", None)
                        panel.pop("pin_boundary", None)
                        panel.pop("grain_wxyz", None)
                    half_projectile = projectile["dimensions_m"][1]/2
                    projectile.update(position_m=[x+.015,.18+dims[2]/2+half_projectile+parameter,0],velocity_m_s=[0,0,0])
                else:
                    panel["position_m"] = [x,dims[1]/2+.02,0]
                    projectile.update(position_m=[x+.015,dims[1]/2+.02,.25],velocity_m_s=[0,0,-parameter])
                objects += [panel,projectile]
            if kind == "knife_cut":
                x = 2*lane_spacing
                objects += [make_object("tomato_proxy",7,position_m=[x,.085,0]),
                            make_object("knife",8,position_m=[x+.035,.26,0],velocity_m_s=[0,-parameter,0])]
        name = plan["name"][:90] + (f" ({parameter:g})" if parameter is not None else "")
        package = make_package(objects, name=name,
            ground={"half_length_m": 4, "half_width_m": 4, "friction": .4},
            damage_integration=None if kind == "rigid_drop" else {"maximum_depth": 2,
                "maximum_damage_increment": .05, "maximum_plastic_strain_increment": .002,
                "maximum_brittle_opening_overshoot": .05, "on_limit": "reject"})
        # Conservative admission by enclosing-cell counts; occupied ellipsoids
        # use fewer cells. No automatic resolution change on budget failure.
        upper_cells = sum(math.prod(o.get("resolution",[1,1,1])) if o["representation"]=="network" else 1 for o in objects)
        if upper_cells > 850: raise ValueError("Experiment exceeds the playground's 850-cell admission budget")
        packages.append(package)
    return packages
