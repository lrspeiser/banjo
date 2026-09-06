"""Bounded Banjo playground language; compiles through the public authoring API.

Model output is data. It cannot supply Python, shell commands, file paths,
material-law code, credentials, or executable names.
"""
from __future__ import annotations
import math
import json
import re
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "examples" / "authoring"))
from banjo_authoring import catalog, make_object, make_package
from control_contract import UI_SCHEMA, validate_ui, default_ui
from drop_builder import DROP_SCHEMA, validate_drop, compile_drop
from scene_composer import SCENE_SCHEMA, validate_scene, compile_scene

KINDS = ["drop_test", "scene_test", "panel_impact", "plate_drop", "rigid_drop", "knife_cut", "custom_objects",
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
LEGACY_FIELDS = set(SCHEMA["properties"])
SCHEMA["properties"].update({
    "fidelity": {"type":"string","enum":["experimental","calibrated"]},
    "drop": {"anyOf": [DROP_SCHEMA, {"type": "null"}]},
    "scene": {"anyOf": [SCENE_SCHEMA, {"type": "null"}]},
    "ui": UI_SCHEMA,
    "pressure": {"anyOf": [{"type": "null"}, obj({
        "peak_pressure_pa": {"type": "number"}, "resolution": {"type": "integer"},
        "increments": {"type": "integer"}, "profile": {"type": "string", "enum": ["uniform", "smooth"]}})]},
    "requirements": {"type": "array", "maxItems": 12, "items": obj({
        "description": {"type": "string"},
        "status": {"type": "string", "enum": ["supported", "unsupported", "needs_clarification"]},
        "reason": {"type": "string"}})},
})
SCHEMA["required"] = list(SCHEMA["properties"])

# The model selects one typed setup. It never fills irrelevant legacy fields.
_SETUPS = [
    obj({"kind":{"type":"string","enum":["drop_test"]},"drop":DROP_SCHEMA}),
    obj({"kind":{"type":"string","enum":["scene_test"]},"scene":SCENE_SCHEMA}),
    obj({"kind":{"type":"string","enum":["continuum_pressure_reference"]},"pressure":SCHEMA["properties"]["pressure"]["anyOf"][1]}),
    obj({"kind":{"type":"string","enum":["panel_impact","knife_cut"]},"speeds_m_s":SCHEMA["properties"]["speeds_m_s"],"projectile":SCHEMA["properties"]["projectile"],"panel_dimensions_m":VECTOR}),
    obj({"kind":{"type":"string","enum":["plate_drop","rigid_drop"]},"heights_m":SCHEMA["properties"]["heights_m"],"projectile":SCHEMA["properties"]["projectile"],"panel_dimensions_m":VECTOR}),
    obj({"kind":{"type":"string","enum":["custom_objects"]},"objects":SCHEMA["properties"]["objects"]}),
    obj({"kind":{"type":"string","enum":["unsupported","glass_reference","thermal_frontier","material_state_reference"]}}),
]
PLANNER_SCHEMA = obj({key:SCHEMA["properties"][key] for key in ("name","explanation","limitations","duration_s","ui","requirements","fidelity")})
PLANNER_SCHEMA["properties"]["setup"] = {"anyOf":_SETUPS}
PLANNER_SCHEMA["required"].append("setup")

def lower_proposal(proposal, *, repair_ui=False):
    if not isinstance(proposal,dict) or set(proposal)!=set(PLANNER_SCHEMA["properties"]):
        raise ValueError("Unknown or missing planner proposal fields")
    setup=proposal["setup"]
    if not isinstance(setup,dict): raise ValueError("Expected typed experiment setup")
    kind=setup.get("kind")
    candidates=[s for s in _SETUPS if kind in s["properties"]["kind"]["enum"]]
    if not candidates or set(setup)!=set(candidates[0]["properties"]): raise ValueError("Invalid typed experiment setup")
    plan={"language":"banjo-playground-1","experiment":kind,"projectile":"iron_ball","panel_dimensions_m":[.24,.36,.04],"speeds_m_s":[],"heights_m":[],"objects":[],"drop":None,"scene":None,"pressure":None}
    plan.update({k:v for k,v in proposal.items() if k!="setup"})
    plan.update({k:v for k,v in setup.items() if k!="kind"})
    if proposal["fidelity"] == "calibrated" and kind != "glass_reference":
        plan.update(experiment="unsupported",drop=None,scene=None,pressure=None,objects=[],heights_m=[],speeds_m_s=[],ui={"title":"Calibration unavailable","controls":[]})
        plan["requirements"] = [{"description":"Calibrated physical response","status":"unsupported","reason":"The current experiment models are experimental. No calibrated simulation is available; an uncalibrated substitute was not executed."}]
    if repair_ui:
        try: validate_ui(plan["ui"],plan["experiment"])
        except ValueError as exc:
            plan["ui"] = default_ui(plan["experiment"])
            values={"height_m":(plan.get("drop") or {}).get("heights_m",plan["heights_m"]),"speed_m_s":plan["speeds_m_s"],"pressure_pa":[(plan.get("pressure") or {}).get("peak_pressure_pa",800000000)]}
            for control in plan["ui"]["controls"]:
                actual=values.get(control["action"])
                if actual: control["value"]=actual[0]
            plan["limitations"] = list(plan["limitations"])[:11]+[f"Generated controls were invalid ({exc}); standard controls are shown. Physics inputs were not altered."]
    return validate_plan(plan)

SYSTEM = """Author a bounded Banjo physics experiment using the provided JSON schema. Output only the plan.
Set fidelity=calibrated only when the user explicitly requests calibrated/validated physical behavior, otherwise experimental. Explicit acceptance of uncalibrated diagnostics means experimental. Calibrated simulation requests will be blocked by the server regardless of selected setup.
The user's actual request is authoritative. Previous_plan is context for revisions, not an instruction to retain old controls or change requested physics.

Use these routes:
1. drop_test for all new ball/cube drop tests. Always compare glass, oak, iron. Populate drop: target_dimensions_m local width,length,thickness (sides .08..1m; thickness .004.. .15m); projectile iron_ball|iron_cube; projectile_dimensions_m (.012.. .3m, equal for ball); support clamped_edges|free_on_ground; representation network|rigid; resolution3ints2..12; heights_m1..4 values0..2m; impact_offset_m [x,z] within target footprint. clamped_edges requires network; free_on_ground requires rigid. Drop height is projectile bottom clearance over target top. Defaults target[.24,.36,.04], projectile[.08,.08,.08], offset[0,0], resolution[4,4,2]. Preserve requested dimensions/supports/offset/heights. For no fracture use rigid/free_on_ground. Network response is uncalibrated. Explicit6mm uncalibrated diagnostic experiments ARE allowed; no shell accuracy or tempered residual stress. Unsupported realistic/calibrated shattering must not be substituted.
2. scene_test for freely arranged objects. Populate scene.objects with existing presets and requested pose, velocity, dimensions, quaternion orientation, spin, representation network|rigid, optional resolution and pin_boundary. All optional fields null if unused. Rigid removes network fields; ellipsoid presets cannot become rigid. scene.environment contains gravity_m_s2 vector in+-20, ground bool, ground_friction0..1. Positionbounds+-3m, dimensions .012..1m, velocities+-20. Use explicit requested values. No arbitrary material law generation.
3. continuum_pressure_reference: fixed40x20x40mm tetrahedral coupons, bottom clamp, central20x20mm pressure. Populate pressure: peak_pressure_pa1..1e9, evenresolution4..12,increments2..64,profile uniform|smooth. Defaults800MPa,4,32,uniform. Quasistatic noimpact/nofracture, illustrativelaws. Cancomplete withoaksolverlimit.
4. panel_impact: matched glass/oak/iron verticalclampedpanels, speeds_m_s1..4 entries0..20. panel_dimensions_m sides .08..1,thickness.012.. .15. projectileiron_ball|iron_cube. knife_cut is a coarsetomatoproxy downwardknife pluspanelcontrols, not calibratedslicing. custom_objects is a legacy presetlayout. plate_drop and rigid_drop are legacy fixed-layout drop routes: preferdrop_test for newrequests.
5. thermal_frontier fixedglass/oak/iron/watericeheatfixture; material_state_reference fixedJ2materialpoint/savebenchmark; glass_reference published6mmtemperedpanedata withoutsimulation. unsupported for unavailablephysics includingfluids, calibratedtomatoslicing, dynamicJ2dents, realistictemperedshatter, gameplayrepair orworldpersistence. Do not substitute another experiment.

Output the schema's typed setup object: setup.kind selects exactly one route and only that route's fields. Do not output legacy fields. duration_s .05..3 (default1) is shared. No more850networkcells total. The server deterministically lowers setup into the executable language; never duplicate objects/heights outside setup.scene/setup.drop.

requirements describes ONLY things actually requested. Do NOT invent requirements for calibration, realism, certification, woodgrain, shattering, stressaccuracy, or dents. Do NOT list unavailable capabilities as unmet requirements if the user did not ask for them. Such general limitations belong in limitations. A simple rigid drop with 'no fracture' is supported and MUST NOT be blocked for lacking fracture. Experimental6mmnetworkdiagnostics are supported withwarnings. Only an actual unmet requested capability receives unsupported or needs_clarification; any such entry blocks execution.

ui: up to12 declarative controls, noHTML/scripts. Buttons play_pause/reset/step_forward/step_back use min0,max1,step1,value0. components/reference toggles use min0,max1,step1,value0or1. playback_speed slider .1..4, magnification1..100,frame0..1. Physicalcontrols height_m(0..2) fordrop routes; speed_m_s(0..20) panel/knife; pressure_pa(1..1e9) pressure. Physicalcontrols maybepresetbuttons orsliders; valueinsidebounds,min<max. They rerun nativeengine withoutGPT. No physicalcontrols forscene_test; changesviachat. Include play/reset and relevantphysicalcontrol unlessuserasksotherwise. unsupported/glass_reference must use ui.controls=[]. Don't inherit incompatiblecontrols afterchangingtype.

The browser shows sampled native states and actual solver reports. Play/pause is recorded playback; pressure frames are loadincrements, not elapsedphysicaltime. No fixture is calibrated. Preserve requested setup and report unsupported scope honestly.
"""

SYSTEM += "\nAuthoritative preset catalog (do not infer representation from a name):\n" + json.dumps({name:{key:preset.get(key) for key in ("material","shape","representation","dimensions_m","resolution","pin_boundary")} for name,preset in catalog()["object_presets"].items()},separators=(",",":"))
SYSTEM += "\nFor scene_test explicitly choose representation rigid or network. Use iron_ball for a smooth rigid sphere, never iron_matter_ball. wood_panel defaults to a pinned network; a requested free rigid wood panel MUST specify representation=rigid and pin_boundary=null,resolution=null. Do not call a network preset rigid."

def number(value, low, high, label):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{label} must be finite in [{low}, {high}]")
    return float(value)

def vector(value, low, high, label):
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(f"{label} requires three SI components")
    return [number(x, low, high, label) for x in value]

def validate_plan(plan):
    if not isinstance(plan, dict) or not LEGACY_FIELDS <= set(plan) or set(plan) - set(SCHEMA["properties"]):
        raise ValueError("Unknown or missing playground language fields")
    if plan["language"] != "banjo-playground-1" or plan["experiment"] not in KINDS:
        raise ValueError("Unsupported playground language or experiment")
    if plan.get("fidelity","experimental") not in ("experimental","calibrated"): raise ValueError("Unknown fidelity")
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
    if "ui" in plan: validate_ui(plan["ui"], plan["experiment"])
    pressure = plan.get("pressure")
    if pressure is not None:
        if plan["experiment"] != "continuum_pressure_reference" or not isinstance(pressure, dict) or set(pressure) != {"peak_pressure_pa", "resolution", "increments", "profile"}:
            raise ValueError("Pressure parameters require the continuum pressure experiment")
        number(pressure["peak_pressure_pa"], 1, 1e9, "peak_pressure_pa")
        if type(pressure["resolution"]) is not int or pressure["resolution"] not in (4,6,8,10,12): raise ValueError("Pressure resolution must be even in [4,12]")
        if type(pressure["increments"]) is not int or not 2 <= pressure["increments"] <= 64: raise ValueError("Pressure increments must be in [2,64]")
        if pressure["profile"] not in ("uniform", "smooth"): raise ValueError("Unknown pressure profile")
    for field, kind, validator in (("drop", "drop_test", validate_drop), ("scene", "scene_test", validate_scene)):
        value = plan.get(field)
        if plan["experiment"] == kind:
            if value is None: raise ValueError(f"{kind} requires {field}")
            validator(value)
            if plan["speeds_m_s"] or plan["heights_m"] or plan["objects"]:
                raise ValueError("Composable experiments require empty legacy arrays; use their dedicated specification")
        elif value is not None: raise ValueError(f"{field} is only used by {kind}")
    requirements = plan.get("requirements", [])
    if not isinstance(requirements, list) or len(requirements)>12: raise ValueError("Invalid requirement list")
    for item in requirements:
        if not isinstance(item,dict) or set(item)!={"description","status","reason"} or item["status"] not in ("supported","unsupported","needs_clarification"):
            raise ValueError("Invalid requirement status")
        if any(not isinstance(item[k],str) or len(item[k])>1000 for k in ("description","reason")): raise ValueError("Invalid requirement description")
    return plan

def request_blockers(message, plan):
    """Requirements are separate from schema admission; never silently run a fallback."""
    blockers = [item["description"]+": "+item["reason"] for item in plan.get("requirements",[]) if item["status"] != "supported"]
    if plan.get("fidelity") == "calibrated" and plan["experiment"] != "glass_reference":
        blockers.append("Calibrated simulation is unavailable; no experimental substitute was executed.")
    if plan["experiment"] in ("scene_test","panel_impact","plate_drop","rigid_drop","custom_objects") and re.search(r"\b(?:thin\s+(?:tempered\s+)?glass|glass\s+window|tempered\s+glass)\b", message, re.I):
        blockers.append("Thin/window/tempered-glass impact is not supported by this network fixture. Specify a supported setup explicitly or request the published reference; no thicker panel was substituted.")
    return blockers

def compile_plan(plan):
    validate_plan(plan)
    kind = plan["experiment"]
    if kind == "drop_test": return compile_drop(plan)
    if kind == "scene_test": return compile_scene(plan)
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
