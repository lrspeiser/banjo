"""Bounded, declarative experiments over the existing native world operations.

Construction is a laboratory initial condition. Commands request bounded forces;
only the native solver changes body motion. No game-object names select behavior.
"""
from __future__ import annotations
from copy import deepcopy
import math
from pathlib import Path
import re
import threading
import time
from types import SimpleNamespace
import fracture_lab
import live_session
import material_qa as artifacts

SCHEMA = "banjo.physics-trial.v1"
DT = 1 / 240
MAX_CELLS = 4096
LIMITATIONS = [
    "Laboratory construction supplies initial geometry, materials and external actuator work; it is not resource-funded manufacture.",
    "This lane records native rigid motion and connection failure. Detailed material fracture is tested separately in the material range.",
    "A pending damage/refinement request stops the trial as unresolved; no substitute rigid outcome is accepted.",
    "Mass checks cover native dynamic-body masses (anchored bodies report zero); translational kinetic energy excludes rotation. Restart checks are partial invariants, not a closed world energy audit.",
    "No real-material calibration, bending capacity, fatigue, general repair or lazy refinement claim.",
]
COMMANDS = {
    "fix": ({"a", "b", "at", "axis", "holds_tension_n", "holds_shear_n"}, {"a", "b", "at"}),
    "hinge": ({"a", "b", "at", "axis", "lower_deg", "upper_deg", "friction_n_m"}, {"a", "b", "at", "axis"}),
    "slide": ({"a", "b", "at", "axis", "lower_m", "upper_m", "friction_n"}, {"a", "b", "at"}),
    "spring": ({"a", "b", "at_a", "at_b", "rest_m", "stiffness_n_m", "damping_n_s_m"}, {"a", "b", "at_a", "at_b"}),
    "tie": ({"a", "b", "at_a", "at_b", "length_m", "breaks_at_n"}, {"a", "b", "at_a", "at_b"}),
    "reeve": ({"a", "b", "at_a", "at_b", "over_a", "over_b", "length_m", "ratio"}, {"a", "b", "at_a", "at_b", "over_a", "over_b"}),
    "unhinge": ({"joint"}, {"joint"}),
    "sample": ({"label"}, {"label"}),
    "wield": ({"name", "grip"}, {"name"}),
    "move": ({"to"}, {"to"}),
    "release": (set(), set()),
    "advance": ({"duration_s"}, {"duration_s"}),
    "checkpoint": (set(), set()),
}
CONNECTIONS = {"fix", "hinge", "slide", "spring", "tie", "reeve"}
for _op in CONNECTIONS:
    COMMANDS[_op] = (COMMANDS[_op][0] | {"id"}, COMMANDS[_op][1])
JOINT_METRICS = {"joint_attached":"attached", "joint_tension_n":"tension_n",
                 "joint_span_m":"metres", "joint_length_m":"length_m",
                 "joint_ratio":"ratio", "joint_force_n":"force_n", "joint_stored_j":"stored_j"}
BODY_METRICS = {"mass_kg", "speed_m_s", "translational_kinetic_j"} | {
    prefix + axis + "_m" for prefix in ("position_", "displacement_") for axis in "xyz"}
GLOBAL_METRICS = {"elapsed_s", "dynamic_mass_residual_kg", "active_joints", "broken_joints",
                  "max_grip_force_n", "checkpoint_error", "checkpoints"}

def number(value, low, high, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{label} must be a finite number in [{low}, {high}]")
    return value

def obj(value, allowed, required, label):
    if not isinstance(value, dict) or set(value) - set(allowed) or set(required) - set(value):
        raise ValueError(f"{label}: allowed fields {sorted(allowed)}; required {sorted(required)}")
    return value

def vector(value, label, low=-10, high=10):
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(label + " needs three numbers")
    return [number(v, low, high, label) for v in value]

def validate(value):
    obj(value, {"schema", "title", "cell_m", "bodies", "actuator", "steps", "checks"},
        {"schema", "title", "cell_m", "bodies", "steps", "checks"}, "trial")
    if value["schema"] != SCHEMA: raise ValueError("Unsupported trial schema")
    if not isinstance(value["title"], str) or not 1 <= len(value["title"]) <= 160:
        raise ValueError("title must contain 1..160 characters")
    d = deepcopy(value)
    cell = number(d["cell_m"], .02, .1, "cell_m")
    if not isinstance(d["bodies"], list) or not 1 <= len(d["bodies"]) <= 16:
        raise ValueError("A trial needs 1..16 bodies")
    names = set(); cells = 0; native = []
    for b in d["bodies"]:
        obj(b, {"name", "shape", "material", "size_m", "position_m", "velocity_m_s", "anchored"},
            {"name", "shape", "material", "size_m", "position_m"}, "body")
        name = b["name"]
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9 _-]{0,47}", name) or name in names:
            raise ValueError("Body names must be unique, 1..48 letters/digits/spaces/_/-")
        names.add(name)
        if b["shape"] not in ("box", "sphere") or not isinstance(b["material"], str) or b["material"] not in fracture_lab.MATERIALS:
            raise ValueError("Use box/sphere and a catalog material")
        size = vector(b["size_m"], "size_m", cell, 2)
        if any(abs(v/cell - round(v/cell)) > 1e-7 for v in size):
            raise ValueError("Each dimension must be a whole number of cells")
        if b["shape"] == "sphere" and max(size) - min(size) > 1e-9:
            raise ValueError("A sphere has equal dimensions")
        cells += math.prod(round(v/cell) for v in size)
        at = vector(b["position_m"], "position_m")
        if at[1] < size[1]/2: raise ValueError("Start bodies above the floor")
        velocity = vector(b.get("velocity_m_s", [0, 0, 0]), "velocity_m_s", -10, 10)
        if type(b.get("anchored", False)) is not bool: raise ValueError("anchored must be boolean")
        native.append({"name": name, "shape": b["shape"], "material": b["material"],
                       "size_mm": [v*1000 for v in size], "center_mm": [v*1000 for v in at],
                       "velocity_m_s": velocity, "anchored": b.get("anchored", False)})
    if cells > MAX_CELLS: raise ValueError(f"Trial exceeds {MAX_CELLS} cell budget")
    # Reject initial interpenetration rather than injecting separation energy.
    for i, a in enumerate(d["bodies"]):
        for b in d["bodies"][i+1:]:
            if all(abs(a["position_m"][k]-b["position_m"][k]) <
                   (a["size_m"][k]+b["size_m"][k])/2 - 1e-8 for k in range(3)):
                raise ValueError("Initial bounding volumes overlap: " + a["name"] + ", " + b["name"])
    actuator = d.setdefault("actuator", {"strength_n": 100, "torque_n_m": 10, "mass_kg": 1})
    obj(actuator, {"strength_n", "torque_n_m", "mass_kg"}, {"strength_n", "torque_n_m", "mass_kg"}, "actuator")
    number(actuator["strength_n"], 0, 1000, "strength_n")
    number(actuator["torque_n_m"], 0, 100, "torque_n_m")
    number(actuator["mass_kg"], 0, 50, "mass_kg")
    steps = d["steps"]
    if not isinstance(steps, list) or not 1 <= len(steps) <= 48: raise ValueError("Use 1..48 steps")
    elapsed = 0; checkpoints = 0; wielded = False
    aliases = {}; samples = {}
    def identifier(v):
        if not isinstance(v,str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,47}",v):
            raise ValueError("Connection IDs and sample labels need 1..48 letters/digits/_/-")
        return v
    # Reuse the public operation validator before starting any native process.
    probe = live_session.Live()
    probe.session = SimpleNamespace(id="validation", send=lambda **kw: {"ok": True})
    for step in steps:
        if not isinstance(step, dict) or not isinstance(step.get("op"), str) or step.get("op") not in COMMANDS: raise ValueError("Unsupported physical operation")
        op = step["op"]; allowed, required = COMMANDS[op]
        obj(step, allowed | {"op"}, required | {"op"}, op)
        for key in ("a", "b", "name"):
            if key in step and (not isinstance(step[key], str) or step[key] not in names): raise ValueError("Unknown body: " + str(step[key]))
        for key in ("at", "at_a", "at_b", "over_a", "over_b", "grip", "to", "axis"):
            if key in step: vector(step[key], key)
        for key in allowed - {"a", "b", "name", "at", "at_a", "at_b", "over_a", "over_b", "grip", "to", "axis", "id", "joint", "label"}:
            if key in step: number(step[key], -1e9, 1e9, key)
        if op in CONNECTIONS:
            if elapsed: raise ValueError("Connections are initial construction, before advancing time")
            if step["a"] == step["b"]: raise ValueError("Connect two distinct bodies")
            if "id" in step:
                ident=identifier(step["id"])
                if ident in aliases: raise ValueError("Duplicate connection ID")
                aliases[ident]=op
        if op == "unhinge" and identifier(step["joint"]) not in aliases:
            raise ValueError("Release needs an earlier named connection")
        if op == "advance":
            duration = number(step["duration_s"], DT, 5, "duration_s")
            if abs(duration / DT - round(duration / DT)) > 1e-6:
                raise ValueError("duration_s must be a multiple of 1/240 second")
            elapsed += duration
        elif op == "sample":
            label=identifier(step["label"])
            if label in samples or len(samples)>=16: raise ValueError("Use at most 16 unique samples")
            samples[label]=set(aliases)
        elif op == "checkpoint":
            checkpoints += 1
            if checkpoints > 2 or wielded: raise ValueError("At most two checkpoints; release the grip first")
        else:
            if op == "wield": wielded = True
            if op == "move" and not wielded: raise ValueError("move needs a bounded wield grip first")
            if op == "release": wielded = False
            native_command={k:v for k,v in step.items() if k!="id"}
            if op == "unhinge": native_command["joint"]=1
            probe.act({"session": "validation", **native_command})
    if not DT <= elapsed <= 5: raise ValueError("Total simulation time must be 1/240..5 seconds")
    checks = d["checks"]
    if not isinstance(checks, list) or not 1 <= len(checks) <= 32: raise ValueError("Use 1..32 measured checks")
    for check in checks:
        obj(check, {"metric", "body", "joint", "sample", "min", "max"}, {"metric", "min", "max"}, "check")
        if "sample" in check and identifier(check["sample"]) not in samples:
            raise ValueError("Check needs an existing sample")
        metric = check["metric"]
        if not isinstance(metric, str): raise ValueError("metric must be a string")
        if metric in BODY_METRICS:
            if "joint" in check: raise ValueError("Body metric cannot name a joint")
            if not isinstance(check.get("body"), str) or check.get("body") not in names: raise ValueError("Body measurement needs an existing body")
        elif metric in JOINT_METRICS:
            if "body" in check or identifier(check.get("joint")) not in aliases:
                raise ValueError("Joint metric needs a named connection")
            if "sample" in check and check["joint"] not in samples[check["sample"]]:
                raise ValueError("Connection does not exist at the requested sample")
            kind=aliases[check["joint"]]
            supported={"joint_attached":CONNECTIONS,"joint_tension_n":{"fix","tie","reeve"},
                "joint_span_m":{"spring","slide","tie","reeve"},"joint_length_m":{"tie","reeve"},
                "joint_ratio":{"reeve"},"joint_force_n":{"spring"},"joint_stored_j":{"spring"}}
            if kind not in supported[metric]:raise ValueError("Metric is not available on this connection type")
        elif metric not in GLOBAL_METRICS or "body" in check or "joint" in check:
            raise ValueError("Unknown/global measurement with invalid body")
        lo = number(check["min"], -1e12, 1e12, "min")
        number(check["max"], lo, 1e12, "max")
    spec = fracture_lab.validate({"algorithm": "lattice", "cell_m": cell, "bodies": native,
                                  # This authoring cost field has a .2 s minimum;
                                  # actual native time is driven only by advance.
                                  "plasticity": "off", "duration_s": max(.2,elapsed)})
    return d, spec

class TrialSession(live_session.Session):
    """A watchdog includes startup and blocked reads, and reaps the owned child."""
    def __init__(self, *args, cancel, deadline, **kwargs):
        self.cancel = cancel; self.deadline = deadline
        self.finished = threading.Event(); self.watcher = None
        self.stopped_reason = None
        super().__init__(*args, **kwargs)

    def _read(self, what):
        if self.watcher is None:
            def watch():
                while not self.finished.wait(.05):
                    if self.cancel.is_set() or time.monotonic() >= self.deadline:
                        self.stopped_reason = "cancelled" if self.cancel.is_set() else "native trial deadline exceeded"
                        if self._process.poll() is None:
                            self._process.kill()
                        return
            self.watcher = threading.Thread(target=watch, daemon=True)
            self.watcher.start()
        try: return super()._read(what)
        except Exception:
            if self.stopped_reason: raise ValueError(self.stopped_reason) from None
            raise

    def close(self):
        # Keep watchdog alive until close/quit completes.
        try:
            super().close()
            self._process.wait(timeout=5)
        finally:
            self.finished.set()
            if self.watcher: self.watcher.join(timeout=1)

def _body_map(state):
    return {b["name"]: b for b in state["bodies"]}

def _mass(state):
    return sum(b["mass_kg"] for b in state["bodies"])

def run(engine, directory, document, *, cancel=None):
    d, spec = validate(document)
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    artifacts.write_json(directory/"request.json", d)
    started = time.monotonic(); deadline = started + 45
    cancel = cancel or threading.Event()
    frames = []; events = []; geometry = []; aliases = {}; samples = {}; released = set(); guides = []
    maximum_force = 0; checkpoint_error = 0; checkpoints = 0
    live = live_session.Live()
    def open_session(snapshot=None):
        session = TrialSession(Path(engine), spec, directory, snapshot=snapshot,
                               cancel=cancel, deadline=deadline)
        session.spec_digest = live_session.spec_digest(spec)
        live.session = session
        return session
    def act(command):
        if cancel.is_set(): raise ValueError("cancelled")
        answer = live.act({"session": live.session.id, **command})
        if answer.get("breakable") or answer.get("working_on") or answer.get("stepped_back"):
            raise ValueError("Unresolved material refinement; detailed fracture belongs in the material QA lane")
        return answer
    def capture():
        nonlocal maximum_force
        state = live.session.state
        if {b["name"] for b in state["bodies"]} != {b["name"] for b in d["bodies"]}:
            raise ValueError("Body identity changed during trial")
        if abs(_mass(state)-_mass(first)) > 1e-8:
            raise ValueError("Material mass changed during trial")
        # Never serialize nonfinite data as a passing observation.
        import json
        json.dumps(state, allow_nan=False)
        hand = state.get("hand") or {}
        force = hand.get("force_n") or [0, 0, 0]
        maximum_force = max(maximum_force, math.sqrt(sum(v*v for v in force)))
        frame = {"time_s": state["t"], "poses": [{"id": b["name"], "position_m": b["position_m"],
                 "orientation_wxyz": b["orientation_wxyz"]} for b in state["bodies"]]}
        # Connection guides follow actual poses. They are not rope contact
        # geometry, sag reconstruction, or a second simulation.
        def attached_point(name,point):
            b=_body_map(state)[name];initial=_body_map(first)[name]
            v=[point[k]-initial["position_m"][k] for k in range(3)]
            w,x,y,z=b["orientation_wxyz"];q=[x,y,z]
            cross=lambda a,b:[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]
            t=[2*c for c in cross(q,v)];u=cross(q,t)
            return [b["position_m"][k]+v[k]+w*t[k]+u[k] for k in range(3)]
        connections=[];joints={j["id"]:j for j in state.get("joints",[])}
        for ident,c in guides:
            a=attached_point(c["a"],c["at_a"]);b=attached_point(c["b"],c["at_b"])
            points=[a,c["over_a"],c["over_b"],b] if c["op"]=="reeve" else [a,b]
            j=joints.get(ident,{})
            for p1,p2 in zip(points,points[1:]):
                connections.append({"a_m":p1,"b_m":p2,"live":bool(j.get("attached")),"joint_id":ident})
        frame["connections"]=connections
        if frames and abs(frames[-1]["time_s"]-frame["time_s"]) < 1e-10: frames[-1] = frame
        else: frames.append(frame)
    result = {"schema": SCHEMA, "title": d["title"], "status": "failed",
              "request_hash": artifacts.digest(d), "limitations": LIMITATIONS}
    def observation():
        state=deepcopy(live.session.state)
        joints=act({"op":"joints"}).get("joints",[])
        measured={"elapsed_s":state["t"]-first["t"],"dynamic_mass_residual_kg":_mass(state)-_mass(first),
                  "max_grip_force_n":maximum_force,"checkpoint_error":checkpoint_error,"checkpoints":checkpoints,
                  "active_joints":sum(j["attached"] for j in joints),"broken_joints":sum(not j["attached"] for j in joints)}
        return {"bodies":state["bodies"],"joints":joints,"measured":measured,"released_joint_ids":sorted(released)}
    try:
        session = open_session()
        first = deepcopy(session.state)
        for b in first["bodies"]:
            geometry.append({"id": b["name"], "name": b["name"], "shape": b["shape"],
                             "dimensions_m": b["dimensions_m"], "material": b["material"],
                             "color_rgba": int(b["color_rgba"],16) if isinstance(b["color_rgba"],str) else b["color_rgba"]})
        capture()
        act({"op": "hand", **d["actuator"]})
        for index, command in enumerate(d["steps"]):
            op = command["op"]
            if op == "advance":
                remaining = round(command["duration_s"]/DT)
                while remaining:
                    n = 1
                    before_t = live.session.state["t"]
                    act({"op": "step", "dt": DT, "n": n})
                    if abs(live.session.state["t"] - before_t - DT*n) > 1e-7:
                        raise ValueError("Native time did not advance by the requested step")
                    capture(); remaining -= n
            elif op == "sample":
                samples[command["label"]]=observation()
            elif op == "checkpoint":
                before = deepcopy(live.session.state)
                before_joints = act({"op": "joints"})["joints"]
                saved, why = live.snapshot()
                if saved is None: raise ValueError("Checkpoint refused: " + why)
                artifacts.write_json(directory/f"checkpoint-{checkpoints}.json", saved)
                live.session.close()
                session = open_session(saved)
                restored_tier = session.state.get("restored", {}).get("tier")
                after_joints = act({"op": "joints"})["joints"]
                keys = ("id", "kind", "a", "b", "attached", "holds_tension_n", "holds_shear_n", "parted_because", "parted_capacity_n", "length_m", "ratio", "breaks_at_n", "over_a", "over_b")
                if [{k:j.get(k) for k in keys} for j in before_joints] != [{k:j.get(k) for k in keys} for j in after_joints]:
                    raise ValueError("Checkpoint changed connections or failure history")
                if restored_tier != "whole":
                    raise ValueError("Checkpoint did not restore the whole world")
                prior, after = _body_map(before), _body_map(session.state)
                if set(prior) != set(after): raise ValueError("Checkpoint changed body identities")
                differences = [abs(before["t"]-session.state["t"]), abs(_mass(before)-_mass(session.state))]
                for name in prior:
                    for field in ("position_m", "velocity_m_s", "orientation_wxyz"):
                        differences += [abs(a-b) for a,b in zip(prior[name][field], after[name][field])]
                checkpoint_error = max(checkpoint_error, *differences)
                if checkpoint_error > 1e-7: raise ValueError("Checkpoint changed physical state")
                checkpoints += 1
                capture()
            else:
                native_command={k:v for k,v in command.items() if k!="id"}
                if op == "unhinge":native_command["joint"]=aliases[command["joint"]]
                reply = act(native_command)
                if op in CONNECTIONS and "id" in command:aliases[command["id"]]=reply["joint"]
                if op in ("tie","reeve"):guides.append((reply["joint"],command))
                if op == "unhinge":released.add(native_command["joint"])
                events.append({"step": index, "command": command, "reply": reply})
                capture()
        final = deepcopy(live.session.state)
        joints = act({"op": "joints"}).get("joints", [])
        start_bodies = _body_map(first); end_bodies = _body_map(final)
        if set(start_bodies) != set(end_bodies): raise ValueError("Unexpected body replacement")
        mass_residual = _mass(final)-_mass(first)
        if abs(mass_residual) > 1e-8: raise ValueError("Material mass changed")
        if maximum_force > d["actuator"]["strength_n"] + 1e-5: raise ValueError("Actuator exceeded force limit")
        measured = {"elapsed_s": final["t"]-first["t"], "dynamic_mass_residual_kg": mass_residual,
                    "max_grip_force_n": maximum_force, "checkpoint_error": checkpoint_error,
                    "checkpoints": checkpoints,
                    "active_joints": sum(j["attached"] for j in joints),
                    "broken_joints": sum(not j["attached"] for j in joints)}
        checked = []
        for c in d["checks"]:
            metric = c["metric"]
            observed=samples[c["sample"]] if "sample" in c else {"bodies":final["bodies"],"joints":joints,"measured":measured,"released_joint_ids":released}
            if "body" in c:
                b = _body_map(observed)[c["body"]]; initial = start_bodies[c["body"]]
                speed2 = sum(v*v for v in b["velocity_m_s"])
                if metric == "mass_kg": value = b["mass_kg"]
                elif metric == "speed_m_s": value = math.sqrt(speed2)
                elif metric == "translational_kinetic_j": value = .5*b["mass_kg"]*speed2
                else:
                    axis = "xyz".index(metric.split("_")[1]); value = b["position_m"][axis]
                    if metric.startswith("displacement_"): value -= initial["position_m"][axis]
            elif "joint" in c:
                j=next((j for j in observed["joints"] if j["id"]==aliases[c["joint"]]),None)
                if j is None and metric=="joint_attached" and aliases[c["joint"]] in observed["released_joint_ids"]:
                    value=0.
                elif j is None or JOINT_METRICS[metric] not in j:raise ValueError("Requested joint observation is unavailable")
                else:value=float(j[JOINT_METRICS[metric]])
            else: value = observed["measured"][metric]
            checked.append({**c, "value": value, "passed": c["min"] <= value <= c["max"]})
        result.update(status="passed" if all(c["passed"] for c in checked) else "failed",
                      checks=checked, measured=measured, final_bodies=final["bodies"], joints=joints, samples=samples, connection_ids=aliases)
    except Exception as exc:
        result.update(status="cancelled" if cancel.is_set() else "failed", error=str(exc))
    finally:
        if live.session: live.session.close()
    result["wall_s"] = time.monotonic()-started
    artifacts.write_json(directory/"events.json", events)
    artifacts.write_json(directory/"playback.json", {"schema": "banjo.playback.v1",
        "geometry_basis": "native body dimensions and recorded poses; no deformation reconstruction",
        "bodies": geometry, "frames": frames, "supports": []})
    artifacts.write_json(directory/"result.json", result)
    return result

def catalog():
    return {"schema": SCHEMA, "operations": {name: {"fields": sorted(fields), "required": sorted(required)}
            for name, (fields, required) in COMMANDS.items()}, "body_metrics": sorted(BODY_METRICS),
            "joint_metrics": sorted(JOINT_METRICS),
            "global_metrics": sorted(GLOBAL_METRICS), "limits": {"bodies": 16, "cells": MAX_CELLS,
            "steps": 48, "simulated_s": 5, "dt_s": DT, "wall_s": 45},
            "limitations": LIMITATIONS}
