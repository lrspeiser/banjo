"""Room transactions for the generic finite-stock fabrication operating model."""
from __future__ import annotations
from copy import deepcopy
from types import SimpleNamespace
import threading
from mcp import fabrication as model, engine_materials, workshop_components, workshop_visual, workshop_rigid, workshop_matter_metrics
import workshop_install as install
import workshop_sparse_trial as sparse

LOCK = threading.RLock()
COMMON = {"session", "scene"}
COMMAND_FIELDS = {
    "state": set(), "configure": {"settings", "request_id"},
    "quote": {"candidate", "stock_kg"},
    "start": {"candidate", "stock_kg", "request_id", "revision"},
    "pause": {"job_id", "request_id", "revision"},
    "resume": {"job_id", "request_id", "revision"},
    "recover": {"material", "mass_kg", "request_id", "revision"},
}

def active(app):
    room = getattr(app, "room", None)
    return getattr(app, "live_holder", None) == "world" and (
        getattr(room, "scene", None) == "fabrication" or
        getattr(room, "fabrication_required", False) or
        isinstance(getattr(room, "fabrication_record", None), dict))

def sync(app, answer=None):
    if getattr(app, "live_holder", None) != "world": return
    room = getattr(app, "room", None)
    with LOCK:
        state = getattr(room, "fabrication_record", None)
        if not isinstance(state, dict): return
        session = getattr(app.live, "session", None)
        if session is None: return
        time_s = (answer or session.state).get("t")
        if time_s is None: return
        # Always copy: a refused operation or a failed save must not leave a
        # partially advanced material record behind.
        candidate = deepcopy(state)
        model.advance(candidate, time_s)
        model.validate_state(candidate)
        room.fabrication_record = candidate

def _state(room):
    state = getattr(room, "fabrication_record", None)
    if state is None: raise ValueError("Declare initial stock and the finite supply first")
    return model.validate_state(state)

def compile_quote(candidate, stock_kg, cell_m, state):
    """Cost the exact occupied matter, not the template's approximate BOM."""
    design, overrides = workshop_components.design_from_spec(candidate)
    workshop_rigid.require_lattice(design, "Fabrication")
    if any(p.role not in install._FIXED_ROLES for p in design.parts):
        raise ValueError("This process supports fixed monolithic solids only")
    # An operating product must carry a deliberate core function.
    from mcp import core_use
    if not (design.parameters or {}).get("primary_use"):
        raise ValueError("Program the product primary_use before manufacture")
    core_use.installed(design, "fabrication-probe")
    matter = workshop_visual.matter_document(design, overrides, cell_size_m=cell_m, exterior_only=False)
    cells = sparse._grid_set(matter)
    if not cells or len(cells) > install.MAX_CELLS: raise ValueError("Product exceeds the native cell budget")
    measured = workshop_matter_metrics.measure(matter, expected_components=[p.name for p in design.parts])
    if not measured["measured"]["geometry_coherent"]:
        raise ValueError("Product has disconnected or missing components")
    materials = {engine_materials.canonical(c["material"]) for c in matter["cells"]}
    if len(materials) != 1: raise ValueError("Mixed-material fabrication needs explicit interfaces")
    material = next(iter(materials))
    mass = len(cells)*cell_m**3*engine_materials.density(material)
    if abs(mass-measured["measured"]["mass_kg"]) > 1e-8:
        raise ValueError("Compiled material mass does not close")
    stock = model.number(stock_kg, "stock_kg", mass, 10000)
    required = stock*state["config"]["work_j_kg"]
    model.number(required, "required_j", .000001, 1e12)
    return {"candidate": deepcopy(candidate), "material": material, "stock_kg": stock,
            "product_kg": mass, "offcut_kg": stock-mass, "required_j": required,
            "minimum_duration_s": required/(state["config"]["power_w"]*state["config"]["efficiency"]),
            "supply_required_j": required/state["config"]["efficiency"],
            "cell_m": cell_m, "cells": len(cells), "matter_physics_hash": matter["physics_hash"]}

def _persist(app, room, saved, state):
    record = SimpleNamespace(scene=room.scene, spec=room.spec, chat=deepcopy(room.chat),
        inventory_record=install._inventory(room), world_record=saved,
        workshop_installs=deepcopy(getattr(room,"workshop_installs",[])),
        gameplay_record=deepcopy(getattr(room,"gameplay_record",None)),
        fabrication_record=state,
        world_upgrades=deepcopy(getattr(room, "world_upgrades", {})))
    if not getattr(app, "store", None) or not app.store.save(record):
        raise ValueError("Fabrication requires a complete durable room save")
    room.fabrication_record = state
    room.world_record = saved
    room.world_saved_t = saved["t_s"]

def request(app, operation, body):
    if operation not in COMMAND_FIELDS: raise ValueError("Unknown fabrication operation")
    fields = COMMAND_FIELDS[operation]
    model.obj(body, COMMON|fields, COMMON|fields)
    with install._world(app) as (room, live, old), LOCK:
        install._source(room, old, body)
        if room.scene not in install.world_room.SCENES:
            raise ValueError("Fabrication requires a persistently saved room")
        state = deepcopy(getattr(room, "fabrication_record", None))
        if state is not None:
            model.validate_state(state)
            model.advance(state, old.state["t"])
        if operation == "state":
            return {"scene": room.scene, "session": old.id, "cell_m": old.spec["cell_m"], "configured": state is not None,
                    "state": model.report(state) if state is not None else None}
        if operation == "configure":
            model.token(body["request_id"])
            settings = model.config(body["settings"])
            if state is not None:
                if state.get("configuration_request_id") == body["request_id"] and state["config"] == settings:
                    return {"state": model.report(state), "replayed": True}
                raise ValueError("Initial resources were already supplied; reconfiguration cannot refill or cool the station")
            state = model.new(settings, old.state["t"])
            state["configuration_request_id"] = body["request_id"]
            replayed = False
        else:
            if state is None: raise ValueError("Declare initial stock and the finite supply first")
            if operation == "quote":
                quote = compile_quote(body["candidate"],body["stock_kg"],old.spec["cell_m"],state)
                return {"quote": quote, "revision": state["revision"],
                        "available_kg": state["stock_kg"].get(quote["material"],0.),
                        "affordable": state["stock_kg"].get(quote["material"],0.) >= quote["stock_kg"],
                        "changes_world": False}
            action = {k:v for k,v in body.items() if k not in COMMON}
            action["op"] = operation
            # Retries are checked before recompiling the candidate.
            replayed = model.check_request(state, action)
            if not replayed:
                quote = compile_quote(body["candidate"],body["stock_kg"],old.spec["cell_m"],state) if operation == "start" else None
                state, replayed = model.mutate(state, action, quote=quote)
        saved = install._snapshot(live)
        _persist(app, room, saved, state)
        return {"state": model.report(state), "replayed": replayed}

def preview(app, body):
    model.obj(body, COMMON|{"job_id","position_m"}, COMMON|{"job_id","position_m"})
    with install._world(app) as (room, live, old), LOCK:
        install._source(room,old,body)
        state = deepcopy(_state(room)); model.advance(state,old.state["t"])
        job = state["jobs"].get(model.token(body["job_id"],"job_id"))
        if job is None or job["status"] != "ready": raise ValueError("Finish the workpiece before placing it")
        candidate = deepcopy(job["candidate"])
    # The install preview itself acquires the same exclusive gate. Its commit
    # checks the current funded output again under that gate, before any debit.
    answer = install.preview(app, {**{k:body[k] for k in COMMON}, "mode":"authoring",
                                  "candidate":candidate,"position_m":body["position_m"]})
    answer.update(fabrication_job_id=body["job_id"], mode="fabrication")
    return answer

def commit(app, body):
    model.obj(body, COMMON|{"job_id","preview_id","request_id"}, COMMON|{"job_id","preview_id","request_id"})
    model.token(body["job_id"],"job_id")
    return install.commit(app,{k:v for k,v in body.items() if k!="job_id"}, funding_job=body["job_id"])

def wait(app, body):
    model.obj(body, COMMON|{"seconds"}, COMMON|{"seconds"})
    if type(body["seconds"]) is not int or not 1 <= body["seconds"] <= 10:
        raise ValueError("seconds must be an integer in 1..10")
    with install._world(app) as (room, live, old), LOCK:
        install._source(room, old, body)
        if room.scene not in install.world_room.SCENES: raise ValueError("Open a persistently saved room")
        _state(room)
        for _ in range(body["seconds"]*2):
            before_t = old.state["t"]
            answer = live.act({"session":old.id,"op":"step","dt":1/240,"n":120})
            sync(app, answer)
            if answer.get("working_on") or answer.get("breakable") or abs(old.state["t"]-before_t-.5) > 1e-7:
                raise ValueError("Native physics has not accepted the full interval; inspect the world before continuing")
        saved = install._snapshot(live)
        _persist(app, room, saved, deepcopy(room.fabrication_record))
        native = live.act({"session":old.id,"op":"poses"})
        return {"state":model.report(room.fabrication_record), "cell_m":old.spec["cell_m"], "native":native}
