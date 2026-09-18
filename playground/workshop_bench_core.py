"""Functional and compilation benches for Workshop designs.

Every operation runs against the selected design.  There are no product-shaped
JavaScript animations: tests either compile the ProductGraph, perform an
explicit analytical calculation, or own an isolated LiveWorld scratch session.
The outside world never advances.
"""
from __future__ import annotations

from math import isfinite
from pathlib import Path
from typing import Any

import fracture_lab
import live_session
import workshop_trials
from mcp import engine_materials, product_breakscreen, workshop_force, workshop_graph
from mcp.product_contract import compile_contract
from mcp.workshop import WorkshopDesign

BENCH_SCHEMA = "banjo.workshop-bench.v1"


def catalog(kind: str | None = None) -> list[dict[str, Any]]:
    """The functional tests, narrowed to the product on the bench.

    Every test already says which kinds it is for; nothing read it, so a kettle
    was offered "Roll the cart" and a table was offered "Heat contained water".
    A test with no `kinds` is general and is offered for anything.
    """
    offered = _catalog()
    if not kind:
        return offered
    return [test for test in offered
            if not test.get("kinds") or kind in test["kinds"]]


def _catalog() -> list[dict[str, Any]]:
    return [
        {
            "test": "runtime_contract", "name": "Compile runtime physics",
            "about": "Compile this exact design into its ProductGraph and reduced real-time PhysicsContract.",
            "controls": [],
            "limitations": ["Only declared fixed relationships may collapse; contact alone never removes a degree of freedom."],
        },
        {
            "test": "force_probe", "name": "Point force probe",
            "about": "Click the product in 3D to push on that spot. The arrow shows where, which way and how hard. Below: what carries it, and for a design with joints of its own, how much of each joint's strength it uses and which would give way first.",
            "controls": [
                {"name": "force_n", "label": "Force", "unit": "N", "type": "range",
                 "default": 500.0, "min": 10.0, "max": 50000.0, "step": 10.0},
                {"name": "push", "label": "Pushing", "type": "select", "default": "down",
                 "choices": list(PUSHES), "choice_labels": [
                     "down", "up", "along +x (to the right)", "along -x (to the left)",
                     "along +z (towards the back)", "along -z (towards the front)"]},
                {"name": "standing", "label": "While it is", "type": "select", "default": "resting",
                 "choices": ["resting", "free"],
                 "choice_labels": ["standing on the floor", "struck in mid-air"]},
                {"name": "duration_s", "label": "Pulse", "unit": "s", "type": "range",
                 "default": 0.05, "min": 0.01, "max": 2.0, "step": 0.01},
            ],
            "limitations": ["The joint answer is a static-equivalent screen of rigid parts on elastic joints: between half and the whole of a joint's strength is uncertain, not safe. Whether the struck part itself dents or breaks needs an engine impact trial."],
        },
        {
            "test": "cart_roll", "name": "Roll the cart", "kinds": ["cart"],
            "about": "Give this cart an initial forward speed in an isolated world and verify that its axle bearings turn while the chassis moves.",
            "controls": [
                {"name": "speed_m_s", "label": "Starting speed", "unit": "m/s", "type": "number", "default": 0.8, "min": 0.1, "max": 3.0, "step": 0.1},
                {"name": "duration_s", "label": "Run", "unit": "s", "type": "number", "default": 0.5, "min": 0.1, "max": 1.0, "step": 0.1},
            ],
            "limitations": ["Until Workshop cell occupancy is passed into the live scene, each disc wheel uses a spherical rolling collision proxy of the same diameter; axle/bearing DOFs are real."],
        },
        {
            "test": "kettle_heat", "name": "Heat contained water", "kinds": ["kettle"],
            "about": "Fill this selected kettle from its measured interior volume, heat beneath its actual bottom, and measure kettle/water temperature and energy.",
            "controls": [
                {"name": "water_kg", "label": "Water", "unit": "kg", "type": "number", "default": 1.0, "min": 0.05, "max": 10.0, "step": 0.05},
                {"name": "heater_power_w", "label": "Heat below", "unit": "W", "type": "number", "default": 1800.0, "min": 100.0, "max": 10000.0, "step": 100.0},
                {"name": "duration_s", "label": "Run", "unit": "s", "type": "number", "default": 120.0, "min": 5.0, "max": 600.0, "step": 5.0},
            ],
            "limitations": ["Water has real thermal mass/chemistry but remains a contained thermal proxy; free-surface sloshing/pouring is not yet simulated."],
        },
        {
            "test": "machine_control", "name": "Operate a powered machine",
            "about": "Run the engine's battery-hoist controller and edit its command; retained as a general machine/control fixture.",
            "controls": [
                {"name": "power", "label": "Power", "type": "boolean", "default": True},
                {"name": "direction", "label": "Direction", "type": "select", "default": 1, "choices": [1, 0, -1], "choice_labels": ["Raise / forward", "Stop", "Lower / reverse"]},
                {"name": "setting", "label": "Drive setting", "unit": "%", "type": "number", "default": 100.0, "min": 0.0, "max": 100.0, "step": 5.0},
                {"name": "duration_s", "label": "Run", "unit": "s", "type": "number", "default": 1.5, "min": 0.1, "max": 10.0, "step": 0.1},
                {"name": "load_kg", "label": "Load", "unit": "kg", "type": "number", "default": 26.5, "min": 1.0, "max": 100.0, "step": 0.5},
            ], "limitations": [],
        },
    ]


def _number(config: dict[str, Any], name: str, default: float, low: float, high: float) -> float:
    try: value = float(config.get(name, default))
    except (TypeError, ValueError): raise ValueError(f"{name} must be a number")
    if not isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name} must be between {low:g} and {high:g}")
    return value


def _scratch(app: Any, label: str) -> tuple[Path, Path]:
    engine = Path(getattr(app, "engine_path"))
    runs = Path(getattr(app, "runs_path")) / "workshop-bench" / label
    runs.mkdir(parents=True, exist_ok=True)
    return engine, runs


def _advance(session: Any, duration_s: float, *, dt: float = 1 / 30.0, read_thermo: bool = False) -> dict[str, Any]:
    target = float((session.state or {}).get("t", 0.0)) + duration_s
    state = session.state; guard = 0
    while float(state.get("t", 0.0)) < target - 1e-9:
        guard += 1
        if guard > 100000: raise RuntimeError("Workshop bench stopped advancing")
        remaining = target - float(state.get("t", 0.0))
        # Only recordings request intermediate states. Keep the solver's dt
        # and total step count; reduce the transport batch, not the time step.
        sample = float(getattr(session, "sample_period_s", 120 * dt))
        cap = max(1, min(120, int(round(sample / dt))))
        n = max(1, min(cap, int(round(min(remaining, cap * dt) / dt))))
        state = session.send(op="step", dt=dt, n=n)
        while state.get("breakable"):
            state = session.send(op="fracture", name=str(state["breakable"][0]), window_s=0.003)
        if read_thermo:
            session.send(op="thermo")
    return state


def _thermo_body(report: dict[str, Any], name: str) -> dict[str, Any] | None:
    return next((b for b in report.get("bodies") or [] if b.get("name") == name), None)


def run_contract(design: WorkshopDesign) -> dict[str, Any]:
    product = workshop_graph.product(design); product_doc = product.described(); contract = compile_contract(product)
    detailed = len(product.components); runtime = len(contract["runtime_bodies"])
    return {
        "schema": BENCH_SCHEMA, "test": "runtime_contract", "evidence": "deterministic-compiler",
        "summary": {"detailed_components": detailed, "runtime_bodies": runtime,
                    "collision_zones": len(contract["collision_zones"]),
                    "mechanisms": len(contract["mechanisms"]), "reduced_by": detailed - runtime,
                    "mass_kg": contract["conserved"]["mass_kg"]},
        "product_graph": product_doc, "physics_contract": contract,
        "acceptance": {"status": "observed", "why": "Compilation exposes the proposed reduction; tests/evidence determine which ranges are validated."},
        "limitations": ["A contact is not a fixing. Only declared fixed relationships collapse into one runtime body."],
    }


#: Which way the probe pushes, in the product's axes (y is up).
PUSHES = {"down": (0.0, -1.0, 0.0), "up": (0.0, 1.0, 0.0), "+x": (1.0, 0.0, 0.0),
          "-x": (-1.0, 0.0, 0.0), "+z": (0.0, 0.0, 1.0), "-z": (0.0, 0.0, -1.0)}


def run_force(design: WorkshopDesign, config: dict[str, Any]) -> dict[str, Any]:
    # This probe pushes on ONE named component, and the card offers no control
    # to pick it: it expects the part to have been chosen in 3D first. Asked
    # with nothing chosen it passed "" down and the person got "there is no
    # component ''", which is the inside of the code talking rather than an
    # instruction. Say which part to click, and name the ones there are.
    component = str(config.get("component") or "").strip()
    if not component:
        names = [part.name for part in design.parts]
        raise ValueError(
            "Point force probe pushes on one part, so choose the part first: "
            "click it in the 3D view, or in the Components list. "
            "This " + (design.kind or "product") + " has "
            + ", ".join(names[:8]) + ("..." if len(names) > 8 else ""))
    part = next((p for p in design.parts if p.name == component), None)
    if part is None:
        raise ValueError(
            f"there is no component {component!r} on this "
            + (design.kind or "product") + "; it has "
            + ", ".join(p.name for p in design.parts[:8]))
    # Where to push, and which way, if the person has not dragged a point.
    # Pressing Run after clicking a part used to fail with "point_m must be
    # three numbers", which is the probe's argument check surfacing as the
    # whole answer. Push on the middle of the part that was chosen, straight
    # down, which is the load case these products are for -- and the probe
    # echoes the point and direction it used, so the default is visible in the
    # result rather than assumed silently.
    point = config.get("point_m") or list(part.center_m)
    push = str(config.get("push") or "down")
    if push not in PUSHES:
        raise ValueError("push must be one of " + ", ".join(PUSHES))
    direction = config.get("direction") or list(PUSHES[push])
    standing = str(config.get("standing") or "resting")
    if standing not in {"resting", "free"}:
        raise ValueError("standing must be resting or free")
    force = _number(config, "force_n", 500.0, 1.0, 100000.0)
    answer = {
        "schema": BENCH_SCHEMA, "test": "force_probe",
        **workshop_force.probe(
            design, component_name=component,
            point_m=point, direction=direction, force_n=force,
            duration_s=_number(config, "duration_s", 0.05, 0.001, 10.0)),
    }
    # The second layer: what each declared joint carries, and which gives first.
    # A template's joints are still implied by what touches, so there is nothing
    # declared to rate until the person has shown them in Build.
    try:
        answer["joint_screen"] = product_breakscreen.screen(
            design, component_name=component, point_m=point, direction=direction,
            force_n=force, resting=standing == "resting")
    except ValueError as problem:
        answer["joint_screen"] = {"available": False, "why": str(problem)}
    return answer


def _kettle_dimensions(design: WorkshopDesign) -> tuple[Any, list[Any], float, float, float, float]:
    bottom = next((p for p in design.parts if p.role == "container_bottom"), None)
    walls = [p for p in design.parts if p.role == "container_wall"]
    if bottom is None or len(walls) < 4:
        raise ValueError("this design does not declare a complete container bottom and walls")
    x_walls = sorted((p for p in walls if p.size_m[0] <= p.size_m[2]), key=lambda p: p.center_m[0])
    z_walls = sorted((p for p in walls if p.size_m[2] < p.size_m[0]), key=lambda p: p.center_m[2])
    if len(x_walls) < 2 or len(z_walls) < 2:
        raise ValueError("the container walls do not enclose a measurable interior")
    left, right = x_walls[0], x_walls[-1]; front, back = z_walls[0], z_walls[-1]
    x0 = left.center_m[0] + left.size_m[0] / 2; x1 = right.center_m[0] - right.size_m[0] / 2
    z0 = front.center_m[2] + front.size_m[2] / 2; z1 = back.center_m[2] - back.size_m[2] / 2
    floor = bottom.center_m[1] + bottom.size_m[1] / 2
    rim = min(p.center_m[1] + p.size_m[1] / 2 for p in walls)
    return bottom, walls, x1 - x0, z1 - z0, floor, rim


def kettle_setup(design: WorkshopDesign, config: dict[str, Any]) -> dict[str, Any]:
    product = workshop_graph.product(design)
    if not product.contents:
        raise ValueError("this design has no declared contained volume")
    water_kg = _number(config, "water_kg", 1.0, 0.05, 10.0)
    power = _number(config, "heater_power_w", 1800.0, 100.0, 10000.0)
    duration = _number(config, "duration_s", 120.0, 5.0, 600.0)
    bottom, walls, inner_w, inner_d, floor, rim = _kettle_dimensions(design)
    capacity_l = float(product.contents[0]["capacity_l"])
    material = engine_materials.canonical(bottom.material)
    if not engine_materials.known(material):
        raise ValueError(f"{bottom.material!r} has no engine material preset")

    plate_h = 0.02; shift_y = plate_h - float(design.measure()["lowest_m"])
    bodies: list[dict[str, Any]] = [{
        "name": "heater plate", "shape": "box", "material": "iron",
        "size_mm": [bottom.size_m[0] * 1000, plate_h * 1000, bottom.size_m[2] * 1000],
        "center_mm": [bottom.center_m[0] * 1000, plate_h * 500, bottom.center_m[2] * 1000],
        "anchored": True,
    }]
    for part in design.parts:
        bodies.append({
            "name": part.name, "shape": "box", "material": engine_materials.canonical(part.material),
            "size_mm": [v * 1000 for v in part.size_m],
            "center_mm": [part.center_m[0] * 1000, (part.center_m[1] + shift_y) * 1000, part.center_m[2] * 1000],
            "rotation_deg": [float(v) for v in part.rotation_deg], "join": "kettle shell",
        })

    # The ProductGraph's continuous interior volume is authoritative for vessel
    # capacity. The lattice trial needs a small additional clearance, though:
    # a liquid box whose mathematical face lands exactly on a wall face may
    # round into the wall's boundary voxel. Choose the shell's representable
    # cell first, move the proxy one cell inboard on X/Z, and increase its
    # height so the requested water mass remains unchanged.
    shell_cell = workshop_trials._effective_cell(0.02, bodies)
    safe_w = inner_w - 2.0 * shell_cell
    safe_d = inner_d - 2.0 * shell_cell
    if min(safe_w, safe_d) <= 0:
        raise ValueError("this kettle interior is too narrow for a cell-safe liquid proxy")
    # The floor needs the same clearance the sides get. Insetting X and Z only
    # left the proxy's underside sitting exactly on the vessel floor, where it
    # rounded into the bottom's boundary voxels: "kettle-bottom" and "water
    # charge" both claimed 352 of the same cells, which the placement check
    # refuses because nothing settles before a run.
    water_base = floor + shell_cell
    headroom = rim - water_base
    water_h = water_kg / engine_materials.density("ice") / (safe_w * safe_d)
    if water_h > headroom + 1e-9:
        safe_capacity_kg = safe_w * safe_d * max(0.0, headroom) * engine_materials.density("ice")
        raise ValueError(
            f"{water_kg:g} kg fits the continuous vessel but not this lattice-safe thermal proxy; "
            f"use at most about {safe_capacity_kg:.2f} kg at this test resolution")
    bodies.append({
        "name": "water charge", "shape": "box", "material": "ice",
        "size_mm": [safe_w * 1000, water_h * 1000, safe_d * 1000],
        "center_mm": [bottom.center_m[0] * 1000, (shift_y + water_base + water_h / 2) * 1000,
                      bottom.center_m[2] * 1000],
        "contents": {"moisture": 1.0}, "temperature_k": 293.15,
    })
    cell = workshop_trials._effective_cell(shell_cell, bodies)
    spec = fracture_lab.validate({
        "algorithm": "lattice", "cell_m": cell, "plasticity": "on", "bodies": bodies,
        "thermo": {"heaters": [{"target": "heater plate", "power_w": power,
                                  "start_s": 0.0, "seconds": duration, "label": "heat below kettle"}]},
    })
    return {"spec": spec, "bottom": bottom, "capacity_l": capacity_l, "cell": cell,
            "shell_cell": shell_cell, "water_kg": water_kg, "power": power, "duration": duration}


def run_kettle(app: Any, design: WorkshopDesign, config: dict[str, Any], *, session_wrapper=None) -> dict[str, Any]:
    setup = kettle_setup(design, config)
    spec, bottom, capacity_l = setup["spec"], setup["bottom"], setup["capacity_l"]
    cell, shell_cell = setup["cell"], setup["shell_cell"]
    water_kg, power, duration = setup["water_kg"], setup["power"], setup["duration"]
    engine, runs = _scratch(app, "kettle"); session = live_session.Session(engine, spec, runs)
    if session_wrapper is not None:
        session = session_wrapper(session)
    try:
        if session_wrapper is not None:
            session.sample_period_s = max(1/30, duration/500)
        initial = session.send(op="thermo"); _advance(session, duration, read_thermo=session_wrapper is not None); final = session.send(op="thermo")
    finally: session.close()
    before_report = initial.get("thermo") or {}; report = final.get("thermo") or {}
    before = _thermo_body(before_report, "water charge") or {}; after = _thermo_body(report, "water charge") or {}
    shell = _thermo_body(report, bottom.name) or {}; heater = _thermo_body(report, "heater plate") or {}
    return {
        "schema": BENCH_SCHEMA, "test": "kettle_heat", "evidence": "engine-trial",
        "requested": {"water_kg": water_kg, "heater_power_w": power, "duration_s": duration},
        "design": {"capacity_l": capacity_l, "material": bottom.material,
                   "bottom_m": [round(v, 5) for v in bottom.size_m], "cell_size_m": cell,
                   "fluid_proxy_inset_m": round(shell_cell, 6)},
        "measured": {"water_start_k": before.get("temperature_k"), "water_end_k": after.get("temperature_k"),
                     "water_end_c": (round(float(after["temperature_k"]) - 273.15, 2) if after.get("temperature_k") is not None else None),
                     "kettle_bottom_k": shell.get("temperature_k"), "heater_plate_k": heater.get("temperature_k"),
                     "water_contents_kg": after.get("contents_kg"), "ledger": report.get("ledger")},
        "acceptance": {"status": "observed", "why": "This measures the selected vessel; no target boil time was declared."},
        "limitations": ["Water is a contained thermal proxy kept one lattice cell inboard from the side walls; free-surface motion/sloshing is not yet simulated."],
    }


def _cart_spec(design: WorkshopDesign, speed: float) -> tuple[dict[str, Any], str, list[str]]:
    deck = next((p for p in design.parts if p.name == "deck"), None)
    axles = sorted((p for p in design.parts if p.role == "axle"), key=lambda p: p.name)
    wheels = sorted((p for p in design.parts if p.role == "wheel"), key=lambda p: p.name)
    if deck is None or len(axles) != 2 or len(wheels) != 4:
        raise ValueError("this cart needs one deck, two axles and four wheels")
    velocity = [0.0, 0.0, speed]
    bodies: list[dict[str, Any]] = []
    # Keep the chassis detail that does not occupy the bearing bore. Bearing
    # mounts remain in ProductGraph/load paths but are omitted from this reduced
    # collision proxy so a separate rotating axle does not start interpenetrating them.
    chassis = [p for p in design.parts if p.role not in {"axle", "wheel", "bearing_mount"}]
    for part in chassis:
        bodies.append({"name": part.name, "shape": "box", "material": engine_materials.canonical(part.material),
                       "size_mm": [v * 1000 for v in part.size_m], "center_mm": [v * 1000 for v in part.center_m],
                       "rotation_deg": [float(v) for v in part.rotation_deg], "velocity_m_s": velocity,
                       "join": "cart chassis"})
    joints: list[dict[str, Any]] = []
    for axle in axles:
        near = sorted((w for w in wheels if abs(w.center_m[2] - axle.center_m[2]) < 0.02), key=lambda w: w.center_m[0])
        if len(near) != 2: raise ValueError(f"{axle.name} does not line up with two wheels")
        wheel_d = float(near[0].size_m[0]); inner = abs(near[-1].center_m[0] - near[0].center_m[0]) - wheel_d
        live_length = max(0.05, inner)
        bodies.append({"name": axle.name, "shape": "box", "material": engine_materials.canonical(axle.material),
                       "size_mm": [axle.size_m[0] * 1000, live_length * 1000, axle.size_m[2] * 1000],
                       "center_mm": [v * 1000 for v in axle.center_m], "rotation_deg": [float(v) for v in axle.rotation_deg],
                       "velocity_m_s": velocity})
        joints.append({"kind": "hinge", "a": deck.name, "b": axle.name,
                       "at_mm": [v * 1000 for v in axle.center_m], "axis": [1, 0, 0],
                       "lower_deg": -180, "upper_deg": 180, "friction_n_m": 0.0})
        for wheel in near:
            bodies.append({"name": wheel.name, "shape": "sphere", "material": engine_materials.canonical(wheel.material),
                           "size_mm": [wheel_d * 1000] * 3, "center_mm": [v * 1000 for v in wheel.center_m],
                           "velocity_m_s": velocity, "roll": True})
            joints.append({"kind": "fixing", "a": axle.name, "b": wheel.name,
                           "at_mm": [v * 1000 for v in wheel.center_m], "axis": [1, 0, 0],
                           "holds_tension_n": 0, "holds_shear_n": 0})
    cell = workshop_trials._effective_cell(0.04, bodies)
    return fracture_lab.validate({"algorithm": "lattice", "cell_m": cell, "plasticity": "on",
                                  "bodies": bodies, "joints": joints}), deck.name, [a.name for a in axles]


def run_cart(app: Any, design: WorkshopDesign, config: dict[str, Any], *, session_wrapper=None) -> dict[str, Any]:
    speed = _number(config, "speed_m_s", 0.8, 0.1, 3.0); duration = _number(config, "duration_s", 0.5, 0.1, 1.0)
    spec, root, axle_names = _cart_spec(design, speed)
    engine, runs = _scratch(app, "cart"); session = live_session.Session(engine, spec, runs)
    if session_wrapper is not None:
        session = session_wrapper(session)
    # Hang the pins. Session() starts a world from the scene document alone;
    # only Live.open follows it with _hang(), which is where joints are actually
    # installed ("the pins go in afterwards"). Building the session directly
    # meant the cart's two axle hinges and four wheel fixings were never put in:
    # the trial reported joint_count 0 and no axle turns, and the chassis slid
    # rather than rolled -- which reads as broken physics rather than as a
    # missing step, exactly what _hang's own docstring warns about.
    try:
        hung = live_session.Live._hang(session, spec.get("joints") or [])
        refused = [note for note in (hung.get("refused") or [])]
        if refused:
            raise ValueError("the scratch cart could not hang its bearings: "
                             + "; ".join(str(note) for note in refused))
        start = session.send(op="poses"); before_joints = session.send(op="joints").get("joints") or []
        _advance(session, duration, dt=1 / 120.0)
        final = session.send(op="poses"); after_joints = session.send(op="joints").get("joints") or []
    finally: session.close()
    first = next(b for b in start.get("bodies", []) if b["name"] == root)
    last = next(b for b in final.get("bodies", []) if b["name"] == root)
    turned = []
    for joint in after_joints:
        if joint.get("kind") == "hinge" and joint.get("b") in axle_names:
            turned.append({"axle": joint.get("b"), "degrees": float(joint.get("degrees", 0.0) or 0.0)})
    return {
        "schema": BENCH_SCHEMA, "test": "cart_roll", "evidence": "engine-trial",
        "requested": {"speed_m_s": speed, "duration_s": duration},
        "design": {"wheel_diameter_m": float(next(p for p in design.parts if p.role == "wheel").size_m[0]),
                   "bearing_relationships": sum(1 for r in workshop_graph.product(design).relationships if r.kind == "bearing"),
                   "cell_size_m": spec["cell_m"]},
        "measured": {"chassis_delta_m": [round(float(last["position_m"][i]) - float(first["position_m"][i]), 5) for i in range(3)],
                     "axle_turns": turned, "joint_count": len(after_joints)},
        "acceptance": {"status": "observed", "why": "The selected cart's chassis motion and bearing rotation are measured; no minimum coast distance was declared."},
        "limitations": ["Disc wheels use same-diameter spherical collision proxies in this test until asset-compiler cell occupancy reaches the live scene; axle/bearing constraints are real."],
    }


def _hoist_spec(load_kg: float) -> dict[str, Any]:
    """The scratch hoist, UNVALIDATED on purpose.

    Its one caller hands this to live_session.Live.open, which validates the
    spec itself. fracture_lab.validate is not idempotent -- it enriches what it
    returns with cells, cells_per_axis, requested_plate_m, seated and snapped --
    so validating here made the second pass refuse its own output with
    "Unknown fracture lab fields". The kettle and cart benches build a spec and
    hand it to live_session.Session, which does not re-validate; this one goes
    through open(), so it must not pre-validate.
    """
    side = (load_kg / engine_materials.density("iron")) ** (1 / 3)
    return ({
        "algorithm": "lattice", "cell_m": 0.05, "plasticity": "on",
        "bodies": [
            {"name": "post", "shape": "box", "material": "iron", "size_mm": [100, 2000, 100], "center_mm": [-400, 1000, 0], "anchored": True},
            {"name": "drum", "shape": "box", "material": "oak", "size_mm": [200, 200, 300], "center_mm": [0, 2000, 0]},
            {"name": "load", "shape": "box", "material": "iron", "size_mm": [side * 1000] * 3, "center_mm": [100, 450, 0]},
        ],
        "joints": [
            {"kind": "hinge", "a": "post", "b": "drum", "at_mm": [0, 2000, 0], "axis": [0, 0, 1]},
            {"kind": "drum", "a": "drum", "b": "load", "at_mm": [0, 2000, 0], "axis": [0, 0, 1], "radius_mm": 100, "to_mm": [100, 500, 0], "winds": 1, "length_mm": 2000},
        ],
        "machines": {"stores": [{"name": "battery", "body": "post", "capacity_j": 5000}],
                     "motors": [{"on": ["post", "drum"], "store": "battery", "stall_torque_n_m": 60, "no_load_rpm": 95.5, "brake_torque_n_m": 200}],
                     "controls": [{"name": "hoist", "on": ["post", "drum"], "top_out_mm": 300.0, "bottom_out_mm": 1950.0}]},
    })


def run_machine(app: Any, config: dict[str, Any], *, session_wrapper=None) -> dict[str, Any]:
    duration = _number(config, "duration_s", 1.5, 0.1, 10.0); load_kg = _number(config, "load_kg", 26.5, 1.0, 100.0)
    setting_pct = _number(config, "setting", 100.0, 0.0, 100.0); power = bool(config.get("power", True))
    try: direction = int(config.get("direction", 1))
    except (TypeError, ValueError): raise ValueError("direction must be -1, 0 or 1")
    if direction not in {-1, 0, 1}: raise ValueError("direction must be -1, 0 or 1")
    spec = _hoist_spec(load_kg); scratch = live_session.Live()
    class App:
        engine_path = Path(getattr(app, "engine_path")); runs_path = Path(getattr(app, "runs_path")) / "workshop-bench" / "machine"
        live_inprocess = False; on_live_reply = None
    App.runs_path.mkdir(parents=True, exist_ok=True)
    opened = scratch.open(App(), {"spec": spec}); session = scratch.session; assert session is not None
    if session_wrapper is not None:
        session = session_wrapper(session)
    try:
        controls = (opened.get("machines") or {}).get("controls") or []
        if not controls: raise ValueError("the scratch machine opened without its controller")
        control = controls[0]; start_load = next(b for b in session.state.get("bodies", []) if b["name"] == "load")
        start_y = float(start_load["position_m"][1])
        ack = session.send(op="operate", control=int(control["id"]), sender="workshop-bench", seq=1,
                           power=power, direction=direction, setting=setting_pct / 100.0)
        _advance(session, duration, dt=1 / 120.0); state = session.send(op="poses")
        machines = session.state.get("machines") or state.get("machines") or {}
        end_load = next(b for b in session.state.get("bodies", []) if b["name"] == "load")
    finally: scratch.shutdown()
    control_now = (machines.get("controls") or [{}])[0]; motor = (machines.get("motors") or [{}])[0]
    store = (machines.get("stores") or [{}])[0]; rope = (machines.get("ropes") or [{}])[0]
    return {"schema": BENCH_SCHEMA, "test": "machine_control", "evidence": "engine-trial",
            "requested": {"power": power, "direction": direction, "setting": setting_pct, "duration_s": duration, "load_kg": load_kg},
            "measured": {"control": control_now, "motor": motor, "battery": store, "rope": rope,
                         "load_delta_y_m": round(float(end_load["position_m"][1]) - start_y, 5), "acknowledgement": ack.get("operated")},
            "acceptance": {"status": "observed", "why": "The controller command and resulting motion/energy are reported without inventing a target."}, "limitations": []}


def run(app: Any, design: WorkshopDesign, request: Any, *, session_wrapper=None) -> dict[str, Any]:
    if not isinstance(request, dict): raise ValueError("bench_test must be an object")
    name = str(request.get("test") or ""); config = request.get("config") or {}
    if not isinstance(config, dict): raise ValueError("bench_test.config must be an object")
    if name == "runtime_contract": result = run_contract(design)
    elif name == "force_probe": result = run_force(design, config)
    elif name == "cart_roll": result = run_cart(app, design, config, session_wrapper=session_wrapper)
    elif name == "kettle_heat": result = run_kettle(app, design, config, session_wrapper=session_wrapper)
    elif name == "machine_control": result = run_machine(app, config, session_wrapper=session_wrapper)
    else: raise ValueError("unknown Workshop bench test")
    result["source_design_id"] = design.design_id; result["source_kind"] = design.kind
    result["subject"] = "reference-hoist-fixture" if name == "machine_control" else "selected-product"
    if name == "machine_control":
        result["limitations"].append("This is the reference hoist controller fixture, not a physical test of the selected product.")
    return result