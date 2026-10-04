"""Room transactions for the generic finite-stock fabrication operating model."""
from __future__ import annotations
from copy import deepcopy
from types import SimpleNamespace
import threading
import logging
from mcp import fabrication as model, engine_materials, workshop_components, workshop_visual, workshop_rigid, workshop_matter_metrics
import workshop_install as install
import workshop_sparse_trial as sparse
import workshop_articulation as articulation
import fabrication_stock as stock
import workshop_library

LOCK = threading.RLock()
COMMON = {"session", "scene"}

def starter_settings():
    """New-map process declaration. Supplies must be gathered and funded."""
    return model.config({'mode':'authoring','stock_kg':{},'energy_j':0.,
        'power_w':500.,'work_j_kg':100.,'efficiency':1.,
        'heat_capacity_j_k':10000.,'cooling_w_k':2.,'max_temperature_k':473.15})

def opened(app, answer):
    room=getattr(app,'room',None)
    declaration=getattr(app,'starter_workbench',None)
    if declaration is None or getattr(room,'fabrication_record',None) is not None:return False
    room.fabrication_record=model.new(declaration,float(answer['t']))
    room.fabrication_required=True
    return True

PLAYER_ROUTES = {'/api/world/open','/api/world/ask','/api/world/action','/api/world/placement','/api/world/construction',
    '/api/world/putdown','/api/world/inventory','/api/world/inventory/shown',
    '/api/world/machine','/api/world/watch-machine','/api/world/tool','/api/world/tool/use',
    '/api/world/goods/collect','/api/world/goods/deliver','/api/world/process','/api/world/rover/talk','/api/world/rover/brain',
    '/api/world/workshop/context','/api/world/workshop/what_made','/api/world/guidance',
    # A player's own native body (native_body): the host derives the actor.
    '/api/world/player/walk'}
PLAYER_NATIVE_OPS = {'step','poses','wield','grab','hand','move','release','stroke',
    'preview_stroke','preview_flight','joints','mechanics','thermo','pick','place_check',
    'survey','structure','condition','environment','environment_state','terrain','materials',
    'rolling','dig','deposit','tool_points','ground_work','collect','fracture','unhinge',
    'behave','lamp_switch','breaker_switch'}

def check_player_request(path,body):
    if not isinstance(body,dict):raise ValueError('Expected a JSON object')
    if path.startswith('/api/world/') and path not in PLAYER_ROUTES and not path.startswith('/api/world/fabrication/'):
        raise ValueError('Create or change designs in Lab, then fund and make them at the workbench')
    if path=='/api/live/act' and body.get('op') not in PLAYER_NATIVE_OPS:
        raise ValueError('This authoring operation is not allowed in the funded room')

#: Ground accounts a bulk transfer can be made against: one that counts what has
#: been taken out (v2 and after) and, to put any back, what has gone back (v3
#: and after). v4 is the same account with the beds of rock under the surface
#: added to it (docs/earth-and-mining-plan.md); v5 adds private carrier stocks.
#: Only v1, which counted neither,
#: is refused.
ACCOUNTED = ("banjo.ground-state.v2", "banjo.ground-state.v3", "banjo.ground-state.v4", "banjo.ground-state.v5")
RETURNS = ("banjo.ground-state.v3", "banjo.ground-state.v4", "banjo.ground-state.v5")
COMMAND_FIELDS = {
    "state": set(), "configure": {"settings", "request_id"},
    "quote": {"candidate", "stock_kg"},
    "start": {"candidate", "stock_kg", "request_id", "revision"},
    "pause": {"job_id", "request_id", "revision"},
    "resume": {"job_id", "request_id", "revision"},
    "recover": {"material", "mass_kg", "request_id", "revision"},
    "retrieve_ground": {"lot_id", "sand_m3", "soil_m3", "rock_m3", "request_id", "revision"},
    "store_ground": {"sand_m3", "soil_m3", "rock_m3", "request_id", "revision"},
    "recover_ground": {"sand_m3", "soil_m3", "rock_m3", "request_id", "revision"},
    "connect_energy": {"store", "store_hash", "power_w", "request_id", "revision"},
    "fund_energy": {"store_hash", "joules", "request_id", "revision"},
    "fund_stock": {"material", "mass_kg", "pool", "rack_hash", "request_id", "revision"},
    "fund_goods": {"material", "mass_kg", "pool", "rack_hash", "request_id", "revision"},
    "release_stock": {"reservation_id", "request_id"},
    "plan_remake": {"source_item", "candidate"},
    "start_remake": {"plan_id", "revision", "request_id"},
    "plan_make": {"candidate"},
    "start_make": {"plan_id", "revision", "request_id"},
    "review_plan": {"plan_id"},
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

def compile_quote(candidate, stock_kg, cell_m, state, *, app=None):
    """Cost the exact occupied matter, not the template's approximate BOM."""
    design, overrides = workshop_components.design_from_spec(candidate)
    from mcp import workshop_material_support
    blocker = workshop_material_support.fixed_lattice_blocker(design, overrides, cell_m=cell_m)
    if blocker:
        raise ValueError(blocker["message"])
    articulated = articulation.has_bearings(design)
    from mcp import workshop_tools
    models=workshop_rigid.requested_models(design,overrides)
    if workshop_tools.frame(design) and (articulated or models!={'lattice'}):
        raise ValueError("Ground tools require a fixed lattice solid; articulated tool points are not supported")
    from mcp import core_use,workshop_machines
    if not (design.parameters or {}).get("primary_use"):
        raise ValueError("Program the product primary_use before manufacture")
    core_use.installed(design, "fabrication-probe")
    machines=workshop_machines.of(design)
    output_energy=sum(s.get('charge_j',0.) for s in (machines or {}).get('stores',[]))
    model.number(output_energy,'initial battery energy',0,1e12)
    if models=={'rigid'}:
        if articulated or machines:
            if app is None:raise ValueError('Exact machine fabrication requires native material measurement')
            import rigid_assembly
            measured=rigid_assembly.measure_for_fabrication(app,design,overrides,cell_m)
            vector=measured['product_materials_kg'];physics_hash=measured['matter_physics_hash']
        else:
            artifact=workshop_rigid.compile_rigid(design,overrides)
            vector={engine_materials.canonical(artifact['material']):artifact['mass_kg']}
            physics_hash=artifact['physics_hash']
        mass=sum(vector.values());stock=model.number(stock_kg,'stock_kg',mass,10000)
        quote={'candidate':deepcopy(candidate),'material':max(vector,key=vector.get),'stock_kg':stock,
            'product_kg':mass,'product_materials_kg':vector,
            'stock_materials_kg':{m:kg*stock/mass for m,kg in vector.items()},
            'offcut_kg':stock-mass,'cell_m':cell_m,'cells':0,'matter_physics_hash':physics_hash,
            'mechanical_model':'precise-rigid-v1','thermal_state':'unmodeled', 'output_energy_j':output_energy}
        goods = workshop_library.goods_needed(design)
        if goods: quote['assembly_goods_kg'] = model.goods_quantities(goods)
        return cost_quote(quote,state)
    workshop_rigid.require_lattice(design,"Fabrication")
    if machines:
        raise ValueError('Machine fabrication requires explicit rigid mechanics for every component')
    if not articulated and any(p.role not in install._FIXED_ROLES for p in design.parts):
        raise ValueError("This process supports fixed monolithic solids only")
    # An operating product must carry a deliberate core function.
    matter = workshop_visual.matter_document(design, overrides, cell_size_m=cell_m, exterior_only=False)
    cells = sparse._grid_set(matter)
    if not cells or len(cells) > install.MAX_CELLS: raise ValueError("Product exceeds the native cell budget")
    measured = workshop_matter_metrics.measure(matter, expected_components=[p.name for p in design.parts])
    if not articulated and not measured["measured"]["geometry_coherent"]:
        raise ValueError("Product has disconnected or missing components")
    materials = {engine_materials.canonical(c["material"]) for c in matter["cells"]}
    if len(materials) != 1:
        from mcp import workshop_fixed_assembly
        artifact = workshop_fixed_assembly.layout(design, overrides, cell_m=cell_m, matter=matter)
        if app is None:
            raise ValueError('Mixed fixed fabrication requires native constituent measurement')
        native=install.measure_fixed_for_fabrication(app,design,overrides,cell_m)
        if native['physics_hash']!=artifact['physics_hash'] or native['material_mass_kg']!=artifact['material_mass_kg']:
            raise ValueError('Native fixed quote changed the requested material allocation')
        mass = artifact['mass_kg']
        if abs(mass-measured['measured']['mass_kg']) > 1e-8:
            raise ValueError('Compiled constituent mass does not close')
        stock = model.number(stock_kg, 'stock_kg', mass, 10000)
        vector = artifact['material_mass_kg']
        return cost_quote({'candidate': deepcopy(candidate), 'material': max(vector,key=vector.get),
            'stock_kg': stock, 'product_kg': mass, 'offcut_kg': stock-mass,
            'product_materials_kg': vector,
            'stock_materials_kg': {m: kg*stock/mass for m,kg in vector.items()},
            'cell_m': cell_m, 'cells': len(cells), 'matter_physics_hash': artifact['physics_hash'],
            'output_energy_j': output_energy, 'fixed_interfaces': artifact['connections'],
            'native_constituents_verified': True,
            'interface_limits': artifact['limitations']}, state)
    material = next(iter(materials))
    mass = len(cells)*cell_m**3*engine_materials.density(material)
    if abs(mass-measured["measured"]["mass_kg"]) > 1e-8:
        raise ValueError("Compiled material mass does not close")
    physics_hash = matter["physics_hash"]
    if articulated:
        artifact = articulation.compile_design(design, overrides, cell_m=cell_m)
        articulation.installed_interactions(design, artifact)
        if abs(artifact["mass_kg"]-mass) > 1e-8:
            raise ValueError("Assembly material mass does not close")
        physics_hash = artifact["physics_hash"]
    stock = model.number(stock_kg, "stock_kg", mass, 10000)
    return cost_quote({"candidate": deepcopy(candidate), "material": material, "stock_kg": stock,
            "product_kg": mass, "offcut_kg": stock-mass,"output_energy_j":output_energy,
            "cell_m": cell_m, "cells": len(cells), "matter_physics_hash": physics_hash},state)


def cost_quote(quote,state,*,minimum=False):
    quote=deepcopy(quote)
    if minimum:
        quote.update(stock_kg=quote['product_kg'],offcut_kg=0.)
        if quote.get('product_materials_kg') is not None:
            quote['stock_materials_kg']=deepcopy(quote['product_materials_kg'])
    required=quote['stock_kg']*state['config']['work_j_kg']
    model.number(required,'required_j',.000001,1e12)
    quote.update(required_j=required,
        minimum_duration_s=required/(state['config']['power_w']*state['config']['efficiency']),
        supply_required_j=required/state['config']['efficiency']+quote.get('output_energy_j',0.))
    return quote

def _persist(app, room, saved, state, *, recover_ack=False):
    model.validate_energy_sources(state, saved, room.scene)
    stock.validate(app, room.scene, state)
    record = SimpleNamespace(scene=room.scene, spec=room.spec, chat=deepcopy(room.chat),
        inventory_record=install._inventory(room), world_record=saved,
        workshop_installs=deepcopy(getattr(room,"workshop_installs",[])),
        gameplay_record=deepcopy(getattr(room,"gameplay_record",None)),
        fabrication_record=state,
        world_upgrades=deepcopy(getattr(room, "world_upgrades", {})))
    for field in ("player_records","player_inventories","player_lock","hand_owner","market_pending","ground_transfers","machine_evidence_pending","player_evidence_pending","goods_claims","goods_deliveries","goods_durable_deliveries"):
        if hasattr(room,field): setattr(record,field,getattr(room,field))
    brains=getattr(app,"brains",None)
    record.machine_runtime=brains.runtime() if brains is not None else getattr(room,"machine_runtime",None)
    save_error=None
    try:
        if not getattr(app, "store", None) or not app.store.save(record):
            raise ValueError("Fabrication requires a complete durable room save")
    except OSError as exc:
        if not recover_ack: raise
        # An atomic replacement can succeed before the caller loses its ack.
        # Only exact receiving/native evidence admits the staged world. Keeping
        # the old live world here would let shutdown overwrite the durable debit.
        try: durable=app.store.read_record(room.scene)
        except (OSError, ValueError): raise exc
        if (durable.get('world')!=saved or durable.get('fabrication')!=state
                or durable.get('spec')!=room.spec or durable.get('machine_runtime')!=record.machine_runtime
                or durable.get('goods_deliveries',[])!=getattr(record,'goods_deliveries',[])): raise
        save_error=exc
        record.persistence={'state':'saved','reason':'','saved_t_s':saved['t_s'],'attempted_t_s':saved['t_s']}
    room.fabrication_record = state
    room.world_record = saved
    room.world_saved_t = saved["t_s"]
    room.machine_runtime=record.machine_runtime
    room.persistence=getattr(record,"persistence",None)
    for field in ("market_durable_pending", "goods_durable_claims", "goods_durable_deliveries", "player_learning_durable_ids"):
        if hasattr(record, field): setattr(room, field, deepcopy(getattr(record, field)))
    if brains is not None: brains.rebind(room.spec)
    return save_error

def request(app, operation, body):
    if operation not in COMMAND_FIELDS: raise ValueError("Unknown fabrication operation")
    fields = COMMAND_FIELDS[operation]
    model.obj(body, COMMON|fields, (COMMON|fields)-{"rock_m3"})
    if operation in ("store_ground","retrieve_ground","recover_ground"): return transfer_ground(app,body,operation)
    if operation in ("connect_energy", "fund_energy"): return transfer_energy(app, body, operation)
    if operation in ("fund_stock", "fund_goods", "release_stock"): return transfer_stock(app, body, operation)
    if operation=='review_plan':
        import fabrication_remake
        return fabrication_remake.refresh(app,body)
    if operation in ("plan_remake", "start_remake", "plan_make", "start_make"):
        import fabrication_remake
        function=fabrication_remake.plan if operation.startswith("plan_") else fabrication_remake.start
        return function(app,body,making=operation.endswith("_make"))
    with install._world(app) as (room, live, old), LOCK:
        install._source(room, old, body)
        if room.scene not in install.world_room.SCENES:
            raise ValueError("Fabrication requires a persistently saved room")
        state = deepcopy(getattr(room, "fabrication_record", None))
        stock_recovery = {"state": "ready"}
        if state is not None:
            model.validate_state(state)
            model.advance(state, old.state["t"])
            stock.validate(app, room.scene, state)
            if operation == "state":
                try: state = stock.settle(app, room, live, state, _persist)
                except OSError as exc:
                    stock_recovery = {"state": "pending", "reason": str(exc)[:240]}
                    state = deepcopy(_state(room)); model.advance(state, old.state["t"])
        if operation == "state":
            ground=(old.send(op="environment").get("environment",{}).get("ground",{})
                    if old.spec.get("terrain") else {})
            carried=ground.get("carried",{})
            source_snapshot, source_reason = live.snapshot()
            reservations = stock.pending(app, room.scene)
            if reservations and stock_recovery["state"] == "ready":
                stock_recovery = {"state": "pending", "reason": source_reason or "Awaiting a complete durable world save"}
            return {"scene": room.scene, "session": old.id, "cell_m": old.spec["cell_m"], "configured": state is not None,
                    "energy_sources": energy_sources(state, source_snapshot, room.scene) if source_snapshot is not None else [],
                    "energy_source_status": {"state": "ready" if source_snapshot is not None else "unavailable",
                                             "reason": source_reason},
                    "stock_sources": stock.sources(app), "goods_sources": stock.sources(app, "goods"), "stock_reservations": reservations,
                    "stock_recovery_status": stock_recovery,
                    "carried_ground":carried, "ground_audit":model.ground_audit(state,ground,getattr(room,"ground_transfers",None)),
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
                quote = compile_quote(body["candidate"],body["stock_kg"],old.spec["cell_m"],state,app=app)
                required=model.materials(quote,'stock')
                available={m:state['stock_kg'].get(m,0.) for m in required}
                goods=quote.get('assembly_goods_kg',{})
                available_goods={n:state.get('goods_stock_kg',{}).get(n,0.) for n in goods}
                return {"quote": quote, "revision": state["revision"],
                        "available_kg": state["stock_kg"].get(quote["material"],0.),
                        "available_materials_kg":available,
                        "available_goods_kg":available_goods,
                        "affordable": all(available[m]>=kg for m,kg in required.items()) and all(available_goods[n]>=kg for n,kg in goods.items()),
                        "changes_world": False}
            action = {k:v for k,v in body.items() if k not in COMMON}
            action["op"] = operation
            if operation in ("pause","resume") and body["job_id"] in state["jobs"]:
                import fabrication_remake
                fabrication_remake.require_owner(app,state["jobs"][body["job_id"]])
            # Retries are checked before recompiling the candidate.
            replayed = model.check_request(state, action)
            if not replayed:
                quote = compile_quote(body["candidate"],body["stock_kg"],old.spec["cell_m"],state,app=app) if operation == "start" else None
                state, replayed = model.mutate(state, action, quote=quote)
        saved = install._snapshot(live)
        _persist(app, room, saved, state)
        return {"state": model.report(state), "replayed": replayed}


def transfer_stock(app, body, operation):
    with install._world(app) as (room, live, old), LOCK:
        if body["scene"] != room.scene: raise ValueError("The source room changed")
        state = deepcopy(_state(room)); model.advance(state, old.state["t"])
        stock.validate(app, room.scene, state)
        if operation == "release_stock":
            install._source(room, old, body)
            replayed = stock.release(app, room, state, body["reservation_id"], body["request_id"])
            return {"released": True, "replayed": replayed, "session": old.id,
                    "stock_sources": stock.sources(app), "goods_sources": stock.sources(app, "goods"), "stock_reservations": stock.pending(app, room.scene)}
        action = {k: v for k, v in body.items() if k not in COMMON}
        action.update(op=operation, requested_by=workshop_library.rack_owner_id(app))
        previous = stock.get(app, room.scene, body["request_id"])
        if previous is not None:
            if previous["action"] != action: raise ValueError("Stock request_id belongs to a different transfer or player")
            if previous["status"] == "released": raise ValueError("This stock reservation was released; use a new request_id")
            if previous["status"] == "applied":
                model.receive_stock(state, action, previous["packet"])
                return {"state": model.report(state), "session": old.id, "replayed": True}
            # A previously authorized source reservation may recover after
            # session/revision changes. Unpublished native spec edits still refuse.
            install._source(room, old, {"session": old.id, "scene": room.scene})
        else:
            install._source(room, old, body)
            model.check_request(state, action)
            stock.reserve(app, room.scene, state, action)
        state = stock.settle(app, room, live, state, _persist)
        if body["request_id"] not in state.get("stock_imports", {}):
            raise ValueError("Stock remains reserved until the native world is completely saveable")
        return {"state": model.report(state), "session": old.id, "replayed": previous is not None,
                "stock_sources": stock.sources(app), "goods_sources": stock.sources(app, "goods"), "stock_reservations": stock.pending(app, room.scene)}


def energy_sources(state, snapshot, scene):
    """Meter hashes bind writes to an actual native store, never a wallet claim."""
    connection = (state or {}).get("energy_connection")
    rows = []
    for meter in snapshot.get("energy_stores", []):
        connected = bool(connection and connection["scene"] == scene
            and connection["store"] == meter["id"] and connection["name"] == meter["name"]
            and connection["body"] == meter["body"])
        window = max(0., snapshot["t_s"]-connection["since_s"]) if connected else 0.
        limit = min(window*connection["power_w"], max(0., window*meter["max_power_w"]
            -(meter["given_j"]-connection["given_j"]))) if connected else 0.
        rows.append({**deepcopy(meter), "store_hash": model.digest(meter),
            "store_binding_hash": model.energy_source_binding(meter), "connected": connected,
            "elapsed_s": window, "transfer_available_j": min(meter["charge_j"], limit)})
    return rows


def transfer_energy(app, body, operation):
    """A coarse charger: bound accepted time, stage debit, save both ledgers."""
    with install._world(app) as (room, live, old), LOCK:
        if body["scene"] != room.scene: raise ValueError("The source room changed")
        state = deepcopy(_state(room)); model.advance(state, old.state["t"])
        stock.validate(app, room.scene, state)
        action = {k: v for k, v in body.items() if k not in COMMON}; action["op"] = operation
        if model.check_request(state, action):
            return {"state": model.report(state), "session": old.id, "replayed": True}
        install._source(room, old, body)
        before = install._snapshot(live)
        model.validate_energy_sources(state, before, room.scene)
        connection = state.get("energy_connection")
        ident = body.get("store") if operation == "connect_energy" else (connection or {}).get("store")
        if type(ident) is not int or not 1 <= ident <= 4294967295:
            raise ValueError("Connect a positive native energy store ID first")
        source = next((m for m in before.get("energy_stores", []) if m["id"] == ident), None)
        if source is None: raise ValueError("Native energy source is missing")
        if body["store_hash"] not in (model.digest(source), model.energy_source_binding(source)):
            raise ValueError("Native source changed; read energy_sources before spending")
        owned = {b["name"] for b in before.get("bodies", []) if b.get("parked")}
        for hand in (before.get("player_hands") or {}).values():
            owned.add(hand.get("holding", ""))
        owned.add((before.get("hand") or {}).get("holding", ""))
        if source["body"] in owned:
            raise ValueError("Put the battery in the world before connecting the station")
        if source["max_power_w"] <= 0:
            raise ValueError("Charging requires a declared positive source power limit")
        if operation == "connect_energy":
            power = model.number(body["power_w"], "power_w", .001,
                                 min(state["config"]["power_w"], source["max_power_w"]))
            state["energy_connection"] = {"scene": room.scene, "store": ident,
                "name": source["name"], "body": source["body"], "power_w": power,
                "since_s": before["t_s"], "given_j": source["given_j"]}
            state["receipts"][body["request_id"]] = model.digest(action)
            state["revision"] += 1
            model.validate_state(state)
            _persist(app, room, before, state)
            return {"state": model.report(state), "session": old.id, "replayed": False}
        if connection["scene"] != room.scene or any(connection[k] != source[k] for k in ("name", "body")):
            raise ValueError("Connected source identity changed; reconnect with current meters")
        joules = model.number(body["joules"], "joules", .000001, 1e9)
        if joules > source["charge_j"]: raise ValueError("Insufficient native source energy")
        if joules > (before["t_s"]-connection["since_s"])*connection["power_w"]+1e-8:
            raise ValueError("Charging power limit: wait for accepted native time")
        if (source["given_j"] < connection["given_j"] or
                source["given_j"]-connection["given_j"]+joules >
                (before["t_s"]-connection["since_s"])*source["max_power_w"]+1e-8):
            raise ValueError("Source power limit: other loads used this charging interval")
        staged = install.live_session.Live()
        try:
            opened = staged.open(SimpleNamespace(engine_path=app.engine_path, runs_path=app.runs_path),
                                 {"spec": deepcopy(room.spec), "snapshot": before})
            if opened.get("restored", {}).get("tier") != "whole":
                raise ValueError("Native world did not restore whole")
            install._preserved(before, install._snapshot(staged), set())
            staged.session.send(op="draw", store=ident, joules=joules)
            saved = install._snapshot(staged)
            after = next(m for m in saved["energy_stores"] if m["id"] == ident)
            expected = deepcopy(before)
            meter = next(m for m in expected["energy_stores"] if m["id"] == ident)
            meter["charge_j"] -= joules; meter["given_j"] += joules
            install._preserved(expected, saved, set())
            packet = {"schema": "banjo.fabrication-energy-transfer.v1", "scene": room.scene,
                "started_s": connection["since_s"], "time_s": saved["t_s"],
                "given_started_j": connection["given_j"],
                "power_w": connection["power_w"], "joules": joules,
                "before": deepcopy(source), "after": deepcopy(after)}
            state, _ = model.receive_energy(state, action, packet)
            _persist(app, room, saved, state)
            live.session = staged.session; staged.session = None
            live.session.on_reply = getattr(app, "on_live_reply", None)
            install._preview_cache(app).clear()
            try: old.close()
            except Exception: logging.getLogger("banjo").exception("Retired energy source did not close")
            return {"state": model.report(state), "session": live.session.id, "replayed": False}
        finally: staged.shutdown()


def transfer_ground(app,body,operation):
    """Stage the source debit; save source, receiving lots and receipt together."""
    with install._world(app) as (room,live,old),LOCK:
        if body["scene"]!=room.scene: raise ValueError("The source room changed")
        state=deepcopy(_state(room));model.advance(state,old.state["t"])
        stock.validate(app, room.scene, state)
        action={k:v for k,v in body.items() if k not in COMMON};action["op"]=operation
        actor=getattr(getattr(old,'_actor_local',None),'actor','')
        retrieving=operation=="retrieve_ground"
        recovering=operation=="recover_ground"
        if recovering and not actor: raise ValueError("Join as a player to recover unassigned ground")
        # Authorize before replay: a known receipt must never cross owners.
        if retrieving:
            owner=state.get('raw_lot_ownership',{}).get(body['lot_id'],{}).get('owner','')
            if owner and owner!=actor: raise ValueError("This raw material belongs to another player")
            if body['request_id'] in state.get('raw_returns',{}):
                if state.get('raw_return_owners',{}).get(body['request_id'],'')!=actor:
                    raise ValueError("This raw return belongs to another player")
        elif body['request_id'] in state.get('raw_lots',{}):
            if state.get('raw_lot_ownership',{}).get(body['request_id'],{}).get('owner','')!=actor:
                raise ValueError("This raw transfer belongs to another player")
        if model.check_request(state,action):
            return {"state":model.report(state),"session":old.id,"replayed":True}
        install._source(room,old,body)
        quantities={s+"_m3":model.number(body.get(s+"_m3",0),s+"_m3",0,10000) for s in model.GROUND_DENSITIES}
        if sum(quantities.values())<=0: raise ValueError("Choose a positive amount of carried ground")
        before=install._snapshot(live)
        ground=before.get("ground") or {}
        if ground.get("schema") not in ACCOUNTED: raise ValueError("Native runtime needs accounted bulk transfers")
        if quantities["rock_m3"] and ground["schema"] not in ("banjo.ground-state.v4", "banjo.ground-state.v5"):
            raise ValueError("Native runtime needs accounted broken-rock transfers")
        source_actor='' if recovering else actor
        carried=ground.get('carriers',{}).get(source_actor,{}) if source_actor else ground['carried']
        if retrieving and ground["schema"] not in RETURNS: raise ValueError("Native runtime needs accounted returns")
        model.validate_ground_stock(state,before,getattr(room,"ground_transfers",None))
        if retrieving:
            state,_=model.return_bulk(state,action)
        else:
            for key,amount in quantities.items():
                if amount>carried.get(key,0): raise ValueError("Insufficient carried ground")
        staged=install.live_session.Live()
        try:
            opened=staged.open(SimpleNamespace(engine_path=app.engine_path,runs_path=app.runs_path),
                {"spec":deepcopy(room.spec),"snapshot":before})
            if opened.get("restored",{}).get("tier")!="whole": raise ValueError("Native world did not restore whole")
            install._preserved(before,install._snapshot(staged),set())
            reply=staged.session.send(op="ground_return" if retrieving else "ground_withdraw",actor=source_actor,**quantities)
            saved=install._snapshot(staged)
            expected=deepcopy(before)
            target=expected['ground'].setdefault('carriers',{}).setdefault(source_actor,{'rock_m3':0.,'soil_m3':0.,'sand_m3':0.}) if source_actor else expected['ground']['carried']
            for key,amount in quantities.items():
                target[key]+=amount if retrieving else -amount
                expected["ground"]["returned" if retrieving else "exported"][key]+=amount
            install._preserved(expected,saved,set())
            if not retrieving: state,_=model.receive_bulk(state,action,reply["material_packet"])
            if retrieving: state.setdefault('raw_return_owners',{})[body['request_id']]=actor
            else: state.setdefault('raw_lot_ownership',{})[body['request_id']]={'owner':actor,'source_actor':source_actor}
            model.validate_state(state)
            model.validate_ground_stock(state,saved,getattr(room,"ground_transfers",None))
            save_error=_persist(app,room,saved,state,recover_ack=True)
            live.session=staged.session;staged.session=None
            live.session._actor_local.actor=actor
            live.session.on_reply=getattr(app,"on_live_reply",None)
            install._preview_cache(app).clear()
            try:old.close()
            except Exception:logging.getLogger("banjo").exception("Retired material source did not close")
            if save_error is not None: raise save_error
            return {"state":model.report(state),"session":live.session.id,"replayed":False}
        finally:staged.shutdown()

def preview(app, body):
    model.obj(body, COMMON|{"job_id","position_m"}, COMMON|{"job_id","position_m"})
    with install._world(app) as (room, live, old), LOCK:
        install._source(room,old,body)
        state = deepcopy(_state(room)); model.advance(state,old.state["t"])
        stock.validate(app, room.scene, state)
        job = state["jobs"].get(model.token(body["job_id"],"job_id"))
        if job is None or job["status"] != "ready": raise ValueError("Finish the workpiece before placing it")
        import fabrication_remake
        fabrication_remake.require_owner(app,job)
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
        stock.validate(app, room.scene, _state(room))
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
