"""Bounded Banjo playground language; compiles through the public authoring API.

Model output is data. It cannot supply Python, shell commands, file paths,
material-law code, credentials, or executable names.
"""
from __future__ import annotations
from copy import deepcopy
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
from dynamic_material import IMPACT_SCHEMA, validate_impact, native_request
from thermal_material import THERMAL_EXPERIMENT_SCHEMA, validate_experiment
import network_admission
from network_admission import (Inadmissible, LIMITS, MAX_CELL_ASPECT, PLAYGROUND_CELL_BUDGET,
                               buildable_dimensions, cell_metrics, cost_estimate,
                               nearest_admissible_resolution)

KINDS = ["drop_test", "scene_test", "panel_impact", "plate_drop", "rigid_drop", "knife_cut", "custom_objects",
         "thermal_frontier", "material_state_reference", "continuum_pressure_reference", "dynamic_material_impact",
         "thermal_material_experiment", "glass_reference", "unsupported"]
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
RESOLUTION3 = {"anyOf": [{"type": "array", "items": {"type": "integer", "minimum": 2, "maximum": 12},
                          "minItems": 3, "maxItems": 3}, {"type": "null"}]}
LEGACY_FIELDS = set(SCHEMA["properties"])
SCHEMA["properties"].update({
    "fidelity": {"type":"string","enum":["experimental","calibrated"]},
    "drop": {"anyOf": [DROP_SCHEMA, {"type": "null"}]},
    "scene": {"anyOf": [SCENE_SCHEMA, {"type": "null"}]},
    "impact": {"anyOf": [IMPACT_SCHEMA, {"type": "null"}]},
    "thermal": {"anyOf": [THERMAL_EXPERIMENT_SCHEMA, {"type": "null"}]},
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
# Written by the server's admission pass, never by the model: the resolution the
# three matched panels of a legacy fixed-layout route actually run at once the
# requested panel dimensions have been checked against the engine's cubic-cell
# rule. Optional, so plans authored before this field still validate.
SCHEMA["properties"]["panel_resolution"] = RESOLUTION3
# Also server-authored: what the admission pass changed and why, kept on the
# plan so a repair survives being saved, re-read and re-run.
SCHEMA["properties"]["admission_notes"] = {"type": "array", "maxItems": 12, "items": obj({
    "limit": {"type": "string"}, "action": {"type": "string"}, "message": {"type": "string"}})}

# The model selects one typed setup. It never fills irrelevant legacy fields.
_SETUPS = [
    obj({"kind":{"type":"string","enum":["thermal_material_experiment"]},
         "thermal":THERMAL_EXPERIMENT_SCHEMA}),
    obj({"kind":{"type":"string","enum":["dynamic_material_impact"]},"impact":IMPACT_SCHEMA}),
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
    return validate_plan(_lower(proposal, repair_ui=repair_ui))

def lower_and_admit(proposal, *, repair_ui=True):
    """Lower a model proposal, then repair or refuse its network geometry.

    The strict validators reject a non-cubic mesh outright, which would turn a
    fixable resolution into a dead job, so admission runs on the lowered plan
    before that check rather than after it. What it changed is recorded in
    ``plan["admission_notes"]`` and never applied silently.
    """
    return admit_plan(_lower(proposal, repair_ui=repair_ui))[0]

def _lower(proposal, *, repair_ui=False):
    if not isinstance(proposal,dict) or set(proposal)!=set(PLANNER_SCHEMA["properties"]):
        raise ValueError("Unknown or missing planner proposal fields")
    setup=proposal["setup"]
    if not isinstance(setup,dict): raise ValueError("Expected typed experiment setup")
    kind=setup.get("kind")
    candidates=[s for s in _SETUPS if kind in s["properties"]["kind"]["enum"]]
    if not candidates or set(setup)!=set(candidates[0]["properties"]): raise ValueError("Invalid typed experiment setup")
    plan={"language":"banjo-playground-1","experiment":kind,"projectile":"iron_ball","panel_dimensions_m":[.24,.36,.04],"speeds_m_s":[],"heights_m":[],"objects":[],"drop":None,"scene":None,"pressure":None,"impact":None,"thermal":None}
    plan.update({k:v for k,v in proposal.items() if k!="setup"})
    plan.update({k:v for k,v in setup.items() if k!="kind"})
    if proposal["fidelity"] == "calibrated" and kind != "glass_reference":
        plan.update(experiment="unsupported",drop=None,scene=None,pressure=None,impact=None,thermal=None,objects=[],heights_m=[],speeds_m_s=[],ui={"title":"Calibration unavailable","controls":[]})
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
    return plan

SYSTEM = """Author a bounded Banjo physics experiment using the provided JSON schema. Output only the plan.
Set fidelity=calibrated only when the user explicitly requests calibrated/validated physical behavior, otherwise experimental. Explicit acceptance of uncalibrated diagnostics means experimental. Calibrated simulation requests will be blocked by the server regardless of selected setup.
The user's actual request is authoritative. Previous_plan is context for revisions, not an instruction to retain old controls or change requested physics.

Use these routes:
1. drop_test for all new ball/cube drop tests. Always compare glass, oak, iron. Populate drop: target_dimensions_m local width,length,thickness (sides .08..1m; thickness .004.. .15m); projectile iron_ball|iron_cube; projectile_dimensions_m (.012.. .3m, equal for ball); support clamped_edges|free_on_ground; representation network|rigid; resolution3ints2..12; heights_m1..4 values0..2m; impact_offset_m [x,z] within target footprint. clamped_edges requires network; free_on_ground requires rigid. Drop height is projectile bottom clearance over target top. Defaults target[.24,.36,.04], projectile[.08,.08,.08], offset[0,0], resolution[6,9,2] (cubic 40x40x20mm cells). Preserve requested dimensions/supports/offset/heights. For no fracture use rigid/free_on_ground. Network response is uncalibrated. Explicit6mm uncalibrated diagnostic experiments ARE allowed; no shell accuracy or tempered residual stress. Unsupported realistic/calibrated shattering must not be substituted.
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
SYSTEM += """
NETWORK GEOMETRY: five hard limits, with the reason for each. They apply to
EVERY network object, drop_test and scene_test included. Author inside them; a
scene outside them is refused before it runs, and no substitute is executed.

1. CELLS MUST BE NEAR-CUBIC. max(spacing)/min(spacing) <= 2.0, where
spacing[i] = dimensions_m[i]/resolution[i]. Reason: the engine gives each cell a
SPHERICAL collision proxy of radius 0.49*min(spacing) while that cell carries the
mass and inertia of the whole box. With cubic cells the sphere spans 98% of the
cell and neighbours just touch. At 4:1 it spans 25% of the widest side, so cells
overlap without ever contacting and fragments carry their full mass straight
through each other. That is not a contact simulation, so it is refused.

2. RESOLUTION IS 2..16 PER AXIS (2..12 through these routes). Combined with rule
1 this bounds face:thickness for a uniform-cell object: Dmax/Dmin <= 2 * nmax/nmin,
so 16:1 through the engine and 12:1 through the drop and scene routes (8:1 and
6:1 respectively if you want strictly cubic cells). A real 6 mm windowpane 0.5 m
across is 83:1 and CANNOT BE EXPRESSED. Say so; do not quietly build a thick slab
and call it a pane. A drop target's sides are >= .08 m and its three matched
lanes share a 283-cell budget, so the thinnest buildable target is .008 m at
.08 x .08 m sides, and .03 m at the default .24 x .36 m face.

3. CELL BUDGETS: 800 cells per object, 1024 in the world, 850 for the playground.
drop_test builds three matched lanes, so its target is capped near 283 cells.

4. COLLISION RADIUS: 0.49*min(spacing) >= 0.001 m, so every cell spacing must be
at least 0.00205 m. Raising resolution is therefore not always admissible.

5. COST IS SET BY THE SMALLEST CELL. The constraint solver subdivides each host
tick onto the lattice's own stability clock: substeps per tick =
ceil(omega*dt/0.2) with omega ~ 2.2*sqrt(E/rho)/spacing, capped at 8192. Halving
the smallest spacing roughly doubles the run time; a 192-cell glass plate with
4 mm cells needs 1587 internal solves per tick and takes about four minutes to
record 120 ticks. Prefer the coarsest resolution that answers the question, and
keep duration_s only as long as the event needs. The server shows the estimated
cost before the run, but a scene you author at 12x12x12 will simply be slow.

Rules 1 and 3 are enforced by snapping resolution to the nearest admissible
value, which is reported to the user; dimensions are never changed for you.
Rule 2 has no repair: it is refused. Preserve any thickness or resolution the
user explicitly supplies. Where the requested geometry cannot pass, mark it
unsupported with the numbers, and say what the nearest buildable object is.
None of this establishes stable or realistic fracture. If shattering is
explicitly required, record that the stable full-fracture gate remains open; do
not promise a successful shatter from geometric admission alone.
"""
SYSTEM += """

New route dynamic_material_impact supersedes the fixed-fixture restriction ONLY for
coupled small-strain sphere/brick impacts and property-authored materials. Prefer
this route for requests to demonstrate generated material laws, elastic response or
impact plasticity using the new material solver. It does not fracture, cut, model
finite-strain rubber, or establish a permanent unloaded dent. Do not substitute it
for a shattering, knife, thin sheet, arbitrary scene, or calibrated-realism request.
The user supplies a sphere above a rectangular solid clamped across its entire
bottom, with gravity 9.81 m/s2, passive contact, friction .15, and physical nodal
deformation. Dimensions are x width, y thickness, z depth in meters, each .01.. .2.
Sphere radius .002.. .03 m, density 1..30000 kg/m3, bottom clearance 0.. .005 m,
downward initial speed 0.. .2 m/s. offset_xz_m is measured from the center of the
brick; abs(offset)+radius must fit within half the respective side.
duration_s .001.. .1 (default .1), mesh_refinement1 or2 (default1), max_step_calls
3..200000 per material (default200000); energy_budget_j1e-9..1e-3 per .1 s
(default6e-6). Work/error limits can stop a run; never loosen requested tolerances
or change coefficients to force an outcome. Refinement is experimental and slow.
Materials are 1..3 explicit SI descriptors with one supported law and coefficients.
Choose at least two distinct materials by default; glass/oak/iron comparisons must
retain all three. When creating fictional materials, call them fictional and give
the coefficients explicitly; the laws are isotropic_elastic, orthotropic_elastic
and j2_plastic. No new equations or material-name special cases can be generated.
maximum_total_strain_norm <=.1; there is also a .1 displacement-gradient limit.
A known inexpensive diagnostic uses .08x.02x.08 m, sphere radius .012m and
density7870, clearance .0005m, offset [.007,.009], speed0, .1s, with two FICTIONAL
materials rho1000 E1e6 Pa nu.25 limit.08: isotropic_elastic and j2_plastic
yield1200Pa hardening20000Pa. Use it only when compatible with the request, and
change requested properties faithfully. Never call these coefficients rubber,
glass, or iron. Real glass/oak/iron stiffnesses can exhaust this CPU budget.
All pressure/stiffness/yield values are PASCALS, not MPa: 1 MPa is 1000000 Pa,
1.2 MPa is 1200000 Pa. For the diagnostic above write young_modulus_pa=1000000,
not 1. Before returning, check unit conversions and that the strain validity
range is compatible with the chosen load. Preserve explicit user numbers even
if they lead to a solver limit, and report that possibility. Native contact
evidence includes accepted impulse counts and energy totals, not full per-contact
force histories; do not promise fields which the recorder does not provide.
Dynamic controls: play_pause/reset/step_forward/step_back, components/reference,
playback_speed .1..4 and frame. No magnification or physical parameter controls
for this route yet; change physics via chat. The 3D view replays actual nodal and
sphere positions at computed timestamps, including partial failure records.
"""
SYSTEM += """

Use thermal_material_experiment for explicit bounded fixed-grid solid heat,
conduction, reaction, or phase-change requests. Populate thermal with 1..16 numeric
SI material descriptors and 1..16 explicit cells, one finite heater, fixed step and
horizon, and all four work limits. Set duration_s equal to thermal.horizon_s.
Material names are labels only. Reaction requires explicit fuel_fraction,
oxygen_per_kg_solid, activation_temperature_k, rate_per_s,
heat_of_combustion_j_kg and oxygen_per_kg_fuel. Inert materials omit reaction.
Do not infer glass, oak or iron coefficients from names. Cells in one compact chunk
must share their initial material, temperature and liquid fraction. This route is
insulated solid conduction: no airflow, smoke, radiation, moisture, mechanical
deformation, contact, fracture or thermal expansion coupling. Reaction and phase
change cannot be combined. Results are numeric frames and full ledgers; there is no
fixed-cell 3D playback renders accepted frames with a labeled temperature color
legend and cell inspection for fuel, oxygen, products, phase and energy values.
Cells remain at their authored positions; no flame, smoke or fake motion is added.
Work limits may return solver_limit. Use only display controls: play_pause, reset,
step_forward, step_back, playback_speed and frame. Change heater, material, cell or
time inputs through a newly authored typed request; no physical rerun controls exist.
"""

def number(value, low, high, label):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{label} must be finite in [{low}, {high}]")
    return float(value)

def vector(value, low, high, label):
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(f"{label} requires three SI components")
    return [number(x, low, high, label) for x in value]

def resolution(value, label):
    """Optional three-integer mesh resolution inside the routes' [2,12] bound."""
    if value is None: return None
    if not isinstance(value, list) or len(value) != 3 or any(
            type(v) is not int or not 2 <= v <= 12 for v in value):
        raise ValueError(f"{label} requires three integers in [2, 12]")
    return list(value)

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
    short = plan["experiment"] in ("dynamic_material_impact", "thermal_material_experiment", "unsupported")
    duration_max = 10 if plan["experiment"] == "thermal_material_experiment" else 3
    number(plan["duration_s"], .001 if short else .05, duration_max, "duration_s")
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
        # ``resolution`` is optional and server-authored: the admission pass adds
        # it when a preset's own resolution would make non-cubic cells at the
        # requested dimensions. The model never emits it.
        if not isinstance(entry, dict) or set(entry) - {"resolution"} != {"preset", "position_m", "velocity_m_s", "dimensions_m"}:
            raise ValueError("Unknown or missing object fields")
        if entry["preset"] not in PRESETS: raise ValueError("Unknown object preset")
        vector(entry["position_m"], -3, 3, "position_m")
        vector(entry["velocity_m_s"], -20, 20, "velocity_m_s")
        if entry["dimensions_m"] is not None: vector(entry["dimensions_m"], .012, 1, "dimensions_m")
        resolution(entry.get("resolution"), "object resolution")
    resolution(plan.get("panel_resolution"), "panel_resolution")
    admission_notes = plan.get("admission_notes")
    if admission_notes is not None:
        if not isinstance(admission_notes, list) or len(admission_notes) > 12:
            raise ValueError("Invalid admission notes")
        for item in admission_notes:
            if not isinstance(item, dict) or set(item) != {"limit", "action", "message"} or any(
                    not isinstance(item[k], str) or not 1 <= len(item[k]) <= 1000 for k in item):
                raise ValueError("Invalid admission note")
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
    for field, kind, validator in (("drop", "drop_test", validate_drop), ("scene", "scene_test", validate_scene), ("impact", "dynamic_material_impact", validate_impact), ("thermal", "thermal_material_experiment", validate_experiment)):
        value = plan.get(field)
        if plan["experiment"] == kind:
            if value is None: raise ValueError(f"{kind} requires {field}")
            validator(value)
            if plan["speeds_m_s"] or plan["heights_m"] or plan["objects"]:
                raise ValueError("Composable experiments require empty legacy arrays; use their dedicated specification")
        elif value is not None: raise ValueError(f"{field} is only used by {kind}")
    if plan["experiment"] == "dynamic_material_impact":
        native_request(plan["impact"], plan["duration_s"])
    if plan["experiment"] == "thermal_material_experiment" and abs(
            plan["duration_s"] - plan["thermal"]["horizon_s"]) > 1e-12:
        raise ValueError("Thermal duration_s must equal thermal.horizon_s")
    requirements = plan.get("requirements", [])
    if not isinstance(requirements, list) or len(requirements)>12: raise ValueError("Invalid requirement list")
    for item in requirements:
        if not isinstance(item,dict) or set(item)!={"description","status","reason"} or item["status"] not in ("supported","unsupported","needs_clarification"):
            raise ValueError("Invalid requirement status")
        if any(not isinstance(item[k],str) or len(item[k])>1000 for k in ("description","reason")): raise ValueError("Invalid requirement description")
    return plan

# ---------------------------------------------------------------------------
# Admission: repair what can be repaired, refuse the rest by name.
# ---------------------------------------------------------------------------
# The drop and scene specifications cap resolution at 12 rather than the
# engine's 16, so admission searches inside their bound, not the engine's.
ROUTE_RESOLUTION_MIN, ROUTE_RESOLUTION_MAX = 2, 12


def _repair_note(label, before, after, metrics_before, metrics_after):
    return {"limit": "cell_aspect_ratio", "action": "snapped",
            "message": (
                f"{label}: resolution {list(before)} would have made "
                f"{metrics_before['aspect_ratio']:.2f}:1 cells, and the engine gives every cell "
                f"a spherical collision proxy of radius 0.49 x the smallest spacing while it "
                f"carries the mass of the whole box, so those cells would have collided over "
                f"only {metrics_before['collision_coverage'] * 100:.0f}% of their widest side. "
                f"Snapped to {list(after)} ({metrics_after['aspect_ratio']:.2f}:1, "
                f"{metrics_after['cells']} cells). The requested dimensions were not changed.")}


def _refusal(label, dimensions, *, budget):
    """No resolution in range works: name the limit and the nearest thing that does."""
    repair = buildable_dimensions(dimensions, low=ROUTE_RESOLUTION_MIN, high=ROUTE_RESOLUTION_MAX)
    if repair["slenderness"] > repair["maximum_slenderness"]:
        raise Inadmissible(
            f"{label}: {list(dimensions)} m is {repair['slenderness']:.1f}:1 "
            f"face-to-thickness. Cells have to stay within {MAX_CELL_ASPECT:g}:1 of cubic to "
            f"collide correctly, and each axis takes {ROUTE_RESOLUTION_MIN}..{ROUTE_RESOLUTION_MAX} "
            f"cells, so a uniform-cell object cannot exceed {repair['maximum_slenderness']:g}:1 "
            f"({repair['cubic_slenderness']:g}:1 with strictly cubic cells). "
            f"The nearest buildable versions are {repair['thicken_to_m']:g} m thick at this face "
            f"size, or a {repair['shrink_face_to_m']:g} m face at this thickness. "
            f"No substitute geometry was run.",
            limit="slenderness_face_over_thickness", repair=repair)
    raise Inadmissible(
        f"{label}: no resolution in {ROUTE_RESOLUTION_MIN}..{ROUTE_RESOLUTION_MAX} per axis "
        f"gives near-cubic cells for {list(dimensions)} m within the {budget}-cell budget "
        f"(smallest admissible cell spacing is {LIMITS['minimum_cell_spacing_m'] * 1000:.4g} mm). "
        f"Change the dimensions or the cell budget; no substitute geometry was run.",
        limit="cell_aspect_ratio", repair=repair)


def _admit_box(label, dimensions, requested, *, budget, notes):
    """Return an admissible resolution for one network box, repairing if needed."""
    metrics = cell_metrics(dimensions, requested)
    if metrics["aspect_ratio"] <= MAX_CELL_ASPECT and metrics["radius_ok"] and metrics["cells"] <= budget:
        return list(requested)
    snapped = nearest_admissible_resolution(dimensions, requested, max_cells=budget,
                                            low=ROUTE_RESOLUTION_MIN, high=ROUTE_RESOLUTION_MAX)
    if snapped is None:
        _refusal(label, dimensions, budget=budget)
    notes.append(_repair_note(label, requested, snapped, metrics,
                              cell_metrics(dimensions, snapped)))
    return snapped


def _shrink_to_world_budget(entries, notes):
    """Bring the total cell count under the playground budget, largest object first.

    Each pass asks the same search for the nearest admissible resolution the
    object can have with strictly fewer cells than it has now, so the total
    decreases every iteration and the loop terminates.
    """
    while sum(cell_metrics(d, r)["cells"] for _, d, r in entries) > PLAYGROUND_CELL_BUDGET:
        index = max(range(len(entries)), key=lambda i: cell_metrics(entries[i][1], entries[i][2])["cells"])
        label, dimensions, current = entries[index]
        cells = cell_metrics(dimensions, current)["cells"]
        smaller = nearest_admissible_resolution(dimensions, current, max_cells=cells - 1,
                                                low=ROUTE_RESOLUTION_MIN, high=ROUTE_RESOLUTION_MAX)
        if smaller is None:
            raise Inadmissible(
                f"This scene needs more than the playground's {PLAYGROUND_CELL_BUDGET}-cell "
                f"budget and {label} cannot be coarsened further without leaving near-cubic "
                f"cells. Remove an object or shrink one; nothing was run.",
                limit="playground_cells")
        notes.append({"limit": "playground_cells", "action": "snapped",
                      "message": (f"{label}: coarsened to {smaller} to fit the playground's "
                                  f"{PLAYGROUND_CELL_BUDGET}-cell budget.")})
        entries[index] = (label, dimensions, smaller)
    return entries


def admit_plan(plan):
    """Make a plan admissible, or refuse it by name.

    Returns ``(plan, notes)``. The plan is a copy whose declared fields fully
    determine the packages `compile_plan` will build, so what the UI shows is
    what the engine runs. Notes describe every change and are also kept on the
    plan itself, so a repair survives being saved, re-read and re-run; nothing
    is snapped silently. This runs BEFORE the strict validators, because those
    reject a non-cubic mesh outright and a fixable mesh deserves a repair rather
    than a dead job. This is admission, not calibration: an admitted scene is
    one the engine will accept, not one whose material response has been
    validated.
    """
    if not isinstance(plan, dict):
        raise ValueError("Unknown or missing playground language fields")
    plan = deepcopy(plan)
    notes = list(plan.get("admission_notes") or [])
    kind = plan.get("experiment")
    presets = catalog()["object_presets"]
    try:
        _admit_geometry(plan, kind, presets, notes)
    except Inadmissible:
        raise
    except (ValueError, TypeError, KeyError, IndexError):
        # Structurally broken input: let the strict validator name the problem
        # instead of reporting it as a geometry refusal.
        pass
    # Absent rather than empty when nothing was repaired, so an untouched plan
    # is byte-identical to what the model authored.
    notes = notes[:12]
    if notes: plan["admission_notes"] = notes
    else: plan.pop("admission_notes", None)
    return validate_plan(plan), notes


def _admit_geometry(plan, kind, presets, notes):
    if kind == "drop_test" and plan["drop"]["representation"] == "network":
        spec = plan["drop"]
        budget = PLAYGROUND_CELL_BUDGET // 3  # three matched material lanes
        spec["resolution"] = _admit_box("Drop target", spec["target_dimensions_m"],
                                        spec["resolution"], budget=budget, notes=notes)
    elif kind == "scene_test":
        entries = []
        for index, entry in enumerate(plan["scene"]["objects"], 1):
            preset = presets[entry["preset"]]
            representation = (preset["representation"] if entry["representation"] == "preset"
                              else entry["representation"])
            if representation != "network":
                continue
            dimensions = entry["dimensions_m"] or preset["dimensions_m"]
            requested = entry["resolution"] or preset.get("resolution")
            if requested is None:
                raise Inadmissible(f"Scene object {index} ({entry['preset']}) is a network object "
                                   "with no resolution.", limit="resolution_per_axis")
            label = f"Scene object {index} ({entry['preset']})"
            entries.append([label, dimensions,
                            _admit_box(label, dimensions, requested,
                                       budget=min(LIMITS["object_cells"], PLAYGROUND_CELL_BUDGET),
                                       notes=notes), entry])
        packed = _shrink_to_world_budget([(a, b, c) for a, b, c, _ in entries], notes)
        for (_, _, chosen), original in zip(packed, entries):
            original[3]["resolution"] = list(chosen)
    elif kind in ("panel_impact", "plate_drop", "knife_cut"):
        # These fixed-layout routes build three matched panels from presets that
        # carry their own resolution, then override the dimensions, so the
        # authored resolution can stop matching the authored panel.
        requested = plan.get("panel_resolution") or presets["glass_panel"]["resolution"]
        plan["panel_resolution"] = _admit_box("Panel", plan["panel_dimensions_m"], requested,
                                              budget=PLAYGROUND_CELL_BUDGET // 3, notes=notes)
    elif kind == "custom_objects":
        entries = []
        for index, entry in enumerate(plan["objects"], 1):
            preset = presets[entry["preset"]]
            if preset["representation"] != "network":
                continue
            dimensions = entry["dimensions_m"] or preset["dimensions_m"]
            label = f"Object {index} ({entry['preset']})"
            entries.append([label, dimensions,
                            _admit_box(label, dimensions,
                                       entry.get("resolution") or preset["resolution"],
                                       budget=min(LIMITS["object_cells"], PLAYGROUND_CELL_BUDGET),
                                       notes=notes), entry])
        packed = _shrink_to_world_budget([(a, b, c) for a, b, c, _ in entries], notes)
        for (_, _, chosen), original in zip(packed, entries):
            original[3]["resolution"] = list(chosen)
    return validate_plan(plan), notes


def plan_cost(plan, packages):
    """Substeps per tick and estimated wall time for every compiled case."""
    cases = []
    for package in packages:
        steps = max(1, round(plan["duration_s"] / package["fixed_dt_s"]))
        estimate = cost_estimate(package, steps)
        estimate["name"] = package["name"]
        cases.append(estimate)
    total = sum(case["estimated_wall_s"] for case in cases)
    return {"cases": cases, "estimated_wall_s": total,
            "estimated_wall_text": network_admission.format_duration(total),
            "worst_substeps_per_tick": max((case["substeps_per_host_tick"] for case in cases),
                                           default=0),
            "basis": cases[0]["basis"] if cases else "No network case to cost."}


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
                "continuum_pressure_reference", "dynamic_material_impact", "thermal_material_experiment"):
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
                if entry.get("resolution") is not None and catalog()["object_presets"][
                        entry["preset"]]["representation"] == "network":
                    args["resolution"] = entry["resolution"]
                objects.append(make_object(entry["preset"], index+1, **args))
        else:
            dims = plan["panel_dimensions_m"]
            lane_spacing = max(.45, dims[0]+.2)
            for lane, preset in enumerate(("glass_panel", "wood_panel", "iron_panel")):
                x = (lane-1)*lane_spacing
                panel = make_object(preset, lane*2+1, dimensions_m=dims)
                if plan.get("panel_resolution") is not None and kind != "rigid_drop":
                    panel["resolution"] = list(plan["panel_resolution"])
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
