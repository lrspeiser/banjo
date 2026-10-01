"""Finite material/work bookkeeping for a declared, lumped fabrication cell.

This is a process operating model, not a cutting/contact solver. The station
spends explicitly seeded energy or metered imports from a native battery.
All supplied work ends in the station heat capacity or its ambient boundary.
Native installation is a separate, atomic transfer, verified by the room adapter.
"""
from __future__ import annotations
from copy import deepcopy
import hashlib
import json
import math
import re
from mcp import engine_materials

SCHEMA = "banjo.fabrication.v1"
AMBIENT_K = 293.15
MAX_JOBS = 128
TOKEN = re.compile(r"^[A-Za-z0-9_-]{8,80}$")
LIMITATIONS = [
    "Declared lumped shaping process; work coefficients are authored, not calibrated cutting laws.",
    "Initial cold stock and the isolated supply are explicitly supplied in authoring mode. They are not mined terrain or a second claim on a native battery.",
    "Native charging is a batched, power-bounded transfer into the finite supply, not an electrical circuit or continuous current simulation. Imported joules are debited from the source once; economic wallet claims are not a source.",
    "Only supported single-material fixed/bearing lattice products are transferable. No drilling contact, casting, repair or tool-wear claim.",
    "All process work heats the station; output stock stays at 293.15 K. Station cooling exchanges heat with a prescribed ambient reservoir.",
    "The ledger boundary is stock, workpieces, station and supply. Installed material is a measured transfer out, not a whole-world energy audit.",
]

def obj(value, allowed, required=()):
    if not isinstance(value, dict) or set(value)-set(allowed) or set(required)-set(value):
        raise ValueError("Allowed fields: " + ", ".join(sorted(allowed)) + "; required: " + ", ".join(sorted(required)))
    return value

def number(v, name, low=0, high=1e12):
    if type(v) not in (int, float) or not math.isfinite(v) or not low <= v <= high:
        raise ValueError(f"{name} must be finite in [{low}, {high}]")
    return float(v)

def token(v, name="request_id"):
    if not isinstance(v, str) or not TOKEN.fullmatch(v):
        raise ValueError(name + " must contain 8..80 letters, digits, _ or -")
    return v

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()

def config(value):
    obj(value, {"mode", "stock_kg", "energy_j", "power_w", "work_j_kg", "efficiency",
                "heat_capacity_j_k", "cooling_w_k", "max_temperature_k"},
        {"mode", "stock_kg", "energy_j", "power_w", "work_j_kg"})
    if value["mode"] != "authoring":
        raise ValueError("Initial stock and energy must be explicitly supplied in authoring mode")
    stocks = value["stock_kg"]
    if not isinstance(stocks, dict) or len(stocks) > len(engine_materials.MATERIALS):
        raise ValueError("stock_kg must map catalog materials to supplied mass")
    normalized = {}
    for material, mass in stocks.items():
        if not isinstance(material, str) or not engine_materials.known(material):
            raise ValueError("Unknown stock material")
        key = engine_materials.canonical(material)
        if key in normalized: raise ValueError("Duplicate material alias")
        normalized[key] = number(mass, "stock_kg", 0, 10000)
    result = {"mode": "authoring", "stock_kg": normalized}
    for name, default, low, high in [
        ("energy_j", None, 0, 1e9), ("power_w", None, .001, 1e6),
        ("work_j_kg", None, .001, 1e9), ("efficiency", 1, .001, 1),
        ("heat_capacity_j_k", 10000, 1, 1e9), ("cooling_w_k", 0, 0, 1e6),
        ("max_temperature_k", 473.15, AMBIENT_K+.01, 2000)]:
        result[name] = number(value.get(name, default), name, low, high)
    return result

def new(settings, time_s):
    c = config(settings)
    return {"schema": SCHEMA, "config": c, "time_s": number(time_s, "time_s"),
            "revision": 0, "stock_kg": deepcopy(c["stock_kg"]), "waste_kg": {},
            "energy_j": c["energy_j"], "station_heat_j": 0., "ambient_j": 0.,
            "spent_j": 0., "transferred_kg": {}, "jobs": {}, "receipts": {}}

def temperature(state):
    return AMBIENT_K + state["station_heat_j"] / state["config"]["heat_capacity_j_k"]

def audit(state):
    inputs = deepcopy(state["config"]["stock_kg"])
    imports = {}
    for packet in state.get("stock_imports", {}).values():
        m = packet["material"]; imports[m] = imports.get(m, 0.)+packet["mass_kg"]
        inputs[m] = inputs.get(m, 0.)+packet["mass_kg"]
    totals = deepcopy(state["stock_kg"])
    for key in ("waste_kg", "transferred_kg"):
        for material, mass in state[key].items():
            totals[material] = totals.get(material, 0.) + mass
    for job in state["jobs"].values():
        if job["status"] != "installed":
            mass = job["product_kg"] if job["status"] == "ready" else job["stock_kg"]
            totals[job["material"]] = totals.get(job["material"], 0.) + mass
    residuals = {m: inputs.get(m, 0.)-totals.get(m, 0.) for m in set(totals)|set(inputs)}
    imported = sum(p["joules"] for p in state.get("energy_imports", {}).values())
    return {"material_residual_kg": residuals,
            "rack_material_received_kg": imports,
            "native_energy_received_j": imported,
            "native_transfer_residual_j": sum(p["before"]["charge_j"]-p["after"]["charge_j"]-p["joules"]
                for p in state.get("energy_imports", {}).values()),
            "native_meter_residual_j": sum(p["after"]["given_j"]-p["before"]["given_j"]-p["joules"]
                for p in state.get("energy_imports", {}).values()),
            "energy_residual_j": state["config"]["energy_j"]+imported-state["energy_j"]
                -state["station_heat_j"]-state["ambient_j"],
            "work_residual_j": state["spent_j"]-sum(j["supplied_j"] for j in state["jobs"].values()),
            "boundary": "stock + workpieces + finite supply + station; installed outputs leave this boundary"}

def validate_state(state):
    if not isinstance(state, dict) or state.get("schema") != SCHEMA:
        raise ValueError("Unsupported fabrication save")
    lots=state.get("raw_lots",{})
    if not isinstance(lots,dict) or len(lots)>4096: raise ValueError("Invalid raw material lots")
    for ident,packet in lots.items():
        token(ident,"lot_id");bulk_packet(packet)
        if ident not in state["receipts"]: raise ValueError("Raw material lot has no receipt")
    raw_inventory(state)  # Validate return receipts and remaining quantities.
    if config(state["config"]) != state["config"]: raise ValueError("Invalid saved configuration")
    for key in ("time_s", "energy_j", "station_heat_j", "ambient_j", "spent_j"):
        number(state[key], key, 0, 1e12)
    if type(state["revision"]) is not int or state["revision"] < 0:
        raise ValueError("Invalid fabrication revision")
    if not isinstance(state["jobs"], dict) or len(state["jobs"]) > MAX_JOBS:
        raise ValueError("Invalid fabrication jobs")
    if not isinstance(state["receipts"], dict) or len(state["receipts"]) > 4096:
        raise ValueError("Invalid fabrication receipts")
    stocks = state.get("stock_imports", {})
    if not isinstance(stocks, dict) or len(stocks) > 4096: raise ValueError("Invalid fabrication stock imports")
    for ident, packet in stocks.items():
        token(ident); stock_packet(packet)
        if ident not in state["receipts"]: raise ValueError("Material import has no receipt")
    funded_materials = set(state["config"]["stock_kg"]) | {p["material"] for p in stocks.values()}
    imports = state.get("energy_imports", {})
    if not isinstance(imports, dict) or len(imports) > 4096:
        raise ValueError("Invalid native energy imports")
    for packet in imports.values(): energy_packet(packet)
    last = {}
    # JSON saves sort object keys; chronology follows native meter counters,
    # never dictionary insertion order or client request IDs.
    for ident, packet in sorted(imports.items(), key=lambda pair: pair[1].get("before", {}).get("given_j", -1)):
        token(ident)
        if ident not in state["receipts"]: raise ValueError("Energy import has no receipt")
        key = (packet["scene"], packet["before"]["id"])
        previous = last.get(key)
        if previous is not None and (packet["before"]["given_j"] < previous["after"]["given_j"]
                or packet["started_s"] < previous["time_s"]-1e-8):
            raise ValueError("Overlapping native energy transfers")
        last[key] = packet
    connection = state.get("energy_connection")
    if connection is not None:
        obj(connection, {"scene", "store", "name", "body", "power_w", "since_s", "given_j"},
            {"scene", "store", "name", "body", "power_w", "since_s", "given_j"})
        _energy_identity(connection["scene"], connection["store"], connection["name"], connection["body"])
        number(connection["power_w"], "charger power_w", .001, state["config"]["power_w"])
        number(connection["since_s"], "charger since_s", 0, state["time_s"]+1e-8)
        number(connection["given_j"], "charger given_j")
    for key in ("stock_kg", "waste_kg", "transferred_kg"):
        for material, mass in state[key].items():
            if material not in funded_materials: raise ValueError("Unfunded saved material")
            number(mass, key, 0, 10000)
    running = 0
    for ident, job in state["jobs"].items():
        token(ident, "job_id")
        if job.get("remake_source") is not None:
            remake_source(job["remake_source"])
            if job["remake_source"]["draft_hash"]!=digest(job["candidate"]):raise ValueError("Remake draft does not match its source binding")
        if job.get("make_source") is not None:
            make_source(job["make_source"])
            if job["make_source"]["draft_hash"]!=digest(job["candidate"]):raise ValueError("Make draft does not match its reviewed binding")
            if job.get("remake_source") is not None:raise ValueError("A job cannot have two source bindings")
        if job["material"] not in state["stock_kg"] or job["status"] not in ("running", "paused", "ready", "installed"):
            raise ValueError("Invalid workpiece")
        running += job["status"] == "running"
        for key in ("stock_kg", "product_kg", "required_j", "work_j", "supplied_j"):
            number(job[key], key, 0, 1e12)
        if job["stock_kg"] < job["product_kg"] or job["required_j"] <= 0 or job["work_j"] > job["required_j"] + 1e-7:
            raise ValueError("Invalid workpiece quantities")
        if abs(job["work_j"]-job["supplied_j"]*state["config"]["efficiency"]) > 1e-6*max(1,job["work_j"]):
            raise ValueError("Invalid workpiece work accounting")
        if job["status"] in ("ready", "installed") and abs(job["work_j"]-job["required_j"]) > 1e-7:
            raise ValueError("Incomplete saved output")
    if running > 1: raise ValueError("The station has one physical work position")
    a = audit(state)
    if any(abs(v) > 1e-7 for v in a["material_residual_kg"].values()) or abs(a["energy_residual_j"]) > 1e-6*max(1,state["config"]["energy_j"]+a["native_energy_received_j"]) or abs(a["work_residual_j"]) > 1e-6*max(1,state["spent_j"]):
        raise ValueError("Fabrication save fails its material or energy ledger")
    return state


def remake_source(packet):
    fields={"schema","owner","source_item","source_bodies","source_hash","native_hash","draft_hash","condition"}
    obj(packet,fields,fields)
    if packet["schema"]!="banjo.remake-source.v1":raise ValueError("Unsupported remake source binding")
    for key in ("owner","source_item"):
        if not isinstance(packet[key],str) or not 1<=len(packet[key])<=160:raise ValueError("Invalid remake source identity")
    for key in ("source_hash","native_hash","draft_hash"):
        if not isinstance(packet[key],str) or len(packet[key])!=64 or any(c not in "0123456789abcdef" for c in packet[key]):
            raise ValueError("Invalid remake source hash")
    names=packet["source_bodies"]
    if not isinstance(names,list) or not 1<=len(names)<=64 or any(not isinstance(n,str) or not 1<=len(n)<=160 for n in names) or len(set(names))!=len(names):
        raise ValueError("Invalid remake source bodies")
    rows=packet["condition"]
    if not isinstance(rows,list) or not 1<=len(rows)<=64 or any(not isinstance(r,dict) or r.get("name") not in names for r in rows):
        raise ValueError("Invalid remake source diagnostics")
    return packet


def make_source(packet):
    """An owned frozen design; it makes no claim about a carried physical item."""
    fields={"schema","owner","draft_hash"}
    obj(packet,fields,fields)
    if packet["schema"]!="banjo.make-source.v1":raise ValueError("Unsupported make binding")
    if not isinstance(packet["owner"],str) or not 1<=len(packet["owner"])<=160:
        raise ValueError("Invalid make owner")
    value=packet["draft_hash"]
    if not isinstance(value,str) or len(value)!=64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("Invalid make draft hash")
    return packet


def stock_packet(packet):
    fields = {"schema", "scene", "source_owner", "requested_by", "material", "mass_kg", "reference_state"}
    obj(packet, fields, fields)
    if packet["schema"] != "banjo.fabrication-stock-transfer.v1": raise ValueError("Unsupported stock transfer")
    for key in ("scene", "source_owner", "requested_by"):
        if not isinstance(packet[key], str) or not 1 <= len(packet[key]) <= 160:
            raise ValueError("Stock transfer needs source and requester identity")
    if not isinstance(packet["material"], str) or not engine_materials.known(packet["material"]) or engine_materials.canonical(packet["material"]) != packet["material"]:
        raise ValueError("Stock transfer needs a canonical catalog material")
    number(packet["mass_kg"], "mass_kg", .000001, 10000)
    if packet["reference_state"] != "cold-inventory-reservoir-v1":
        raise ValueError("Stock transfer needs an explicit reference-state approximation")
    return packet


def receive_stock(state, action, packet):
    """Trusted durable SQL reservation only; recovery may outlive its revision.

    The room adapter checks revision BEFORE reserving source stock. Recovery
    cannot spend again or run old work retroactively; it credits that existing
    escrow in the current receiving state, retaining the original request hash.
    """
    ident = token(action.get("request_id")); fingerprint = digest(action)
    existing = state["receipts"].get(ident)
    if existing:
        if existing != fingerprint or state.get("stock_imports", {}).get(ident) != packet:
            raise ValueError("Stock reservation does not match its accepted receipt")
        return deepcopy(state), True
    if len(state["receipts"]) >= 4096: raise ValueError("Receipt budget exhausted")
    stock_packet(packet)
    if action.get("op") != "fund_stock" or action.get("material") != packet["material"] or action.get("mass_kg") != packet["mass_kg"] or action.get("requested_by") != packet["requested_by"]:
        raise ValueError("Stock transfer does not match its authorized reservation")
    out = deepcopy(state); material = packet["material"]
    out.setdefault("stock_imports", {})[ident] = deepcopy(packet)
    out["stock_kg"][material] = out["stock_kg"].get(material, 0.)+packet["mass_kg"]
    out["receipts"][ident] = fingerprint; out["revision"] += 1
    validate_state(out)
    return out, False


def _energy_identity(scene, store, name, body):
    if type(store) is not int or not 1 <= store <= 4294967295:
        raise ValueError("Native energy store must be a positive integer ID")
    for value in (scene, name, body):
        if not isinstance(value, str) or not 1 <= len(value) <= 160:
            raise ValueError("Native energy source needs scene, name and body identity")


def energy_packet(packet):
    """A trusted adapter's measured transfer, with explicit timing and meters."""
    fields = {"schema", "scene", "started_s", "time_s", "given_started_j", "power_w", "joules", "before", "after"}
    obj(packet, fields, fields)
    if packet["schema"] != "banjo.fabrication-energy-transfer.v1":
        raise ValueError("Unsupported native energy transfer")
    started = number(packet["started_s"], "started_s")
    ended = number(packet["time_s"], "time_s", started)
    power = number(packet["power_w"], "power_w", .001, 1e6)
    joules = number(packet["joules"], "joules", .000001, 1e9)
    meters = {"id", "name", "body", "capacity_j", "charge_j", "voltage_v", "max_power_w", "given_j", "taken_j", "short_j"}
    before, after = packet["before"], packet["after"]
    for meter in (before, after):
        obj(meter, meters, meters)
        _energy_identity(packet["scene"], meter["id"], meter["name"], meter["body"])
        for field in meters-{"id", "name", "body"}: number(meter[field], field)
        if meter["charge_j"] > meter["capacity_j"]: raise ValueError("Native charge exceeds capacity")
    if any(before[k] != after[k] for k in meters-{"charge_j", "given_j"}):
        raise ValueError("Energy transfer changed unrelated source state")
    tolerance = 1e-8 + 1e-12*max(1, before["capacity_j"], after["given_j"])
    if before["charge_j"] <= after["charge_j"] or after["given_j"] <= before["given_j"]:
        raise ValueError("Native meters cannot resolve a positive transfer of this size")
    if (abs(before["charge_j"]-after["charge_j"]-joules) > tolerance
            or abs(after["given_j"]-before["given_j"]-joules) > tolerance):
        raise ValueError("Native energy debit does not match receiving joules")
    if before["max_power_w"] <= 0 or power > before["max_power_w"]:
        raise ValueError("Charging requires a declared positive source power limit")
    baseline = number(packet["given_started_j"], "given_started_j", 0, before["given_j"])
    if after["given_j"]-baseline > (ended-started)*before["max_power_w"]+1e-8:
        raise ValueError("Energy transfer and other loads exceed source power envelope")
    if joules > (ended-started)*power + 1e-8:
        raise ValueError("Energy transfer exceeds its elapsed-time power envelope")
    return packet


def receive_energy(state, body, packet):
    """Trusted adapter only; receiving credit and native debit save together."""
    if check_request(state, body): return deepcopy(state), True
    energy_packet(packet)
    connection = state.get("energy_connection")
    expected = {"scene": packet["scene"], "store": packet["before"]["id"],
        "name": packet["before"]["name"], "body": packet["before"]["body"],
        "power_w": packet["power_w"], "since_s": packet["started_s"], "given_j": packet["given_started_j"]}
    if connection != expected or abs(packet["time_s"]-state["time_s"]) > 1e-8:
        raise ValueError("Energy transfer does not match the current charger interval")
    if body.get("op") != "fund_energy" or body.get("joules") != packet["joules"] or body.get("store_hash") != digest(packet["before"]):
        raise ValueError("Energy transfer does not match its requested debit")
    out = deepcopy(state)
    out.setdefault("energy_imports", {})[body["request_id"]] = deepcopy(packet)
    out["energy_j"] += packet["joules"]
    out["energy_connection"]["since_s"] = packet["time_s"]
    out["energy_connection"]["given_j"] = packet["after"]["given_j"]
    out["receipts"][body["request_id"]] = digest(body)
    out["revision"] += 1
    validate_state(out)
    return out, False


def validate_energy_sources(state, snapshot, scene):
    """Reject a save whose native source no longer covers its imported receipts."""
    for packet in state.get("energy_imports", {}).values():
        if packet["scene"] != scene: raise ValueError("Energy receipt belongs to another room")
        meter = next((m for m in snapshot.get("energy_stores", []) if m["id"] == packet["after"]["id"]), None)
        if meter is None or any(meter[k] != packet["after"][k] for k in ("name", "body", "capacity_j", "voltage_v", "max_power_w")):
            raise ValueError("Imported energy source is missing or changed")
        if meter["given_j"] + 1e-8 < packet["after"]["given_j"]:
            raise ValueError("Native source meter is behind its receiving energy receipt")


def bulk_packet(packet):
    """Validate a source-produced material packet, never an object recipe."""
    obj(packet,{"schema","source","form","thermal_state","contents"},
        {"schema","source","form","thermal_state","contents"})
    if packet["schema"]!="banjo.bulk-material.v1" or packet["form"]!="granular" or packet["thermal_state"]!="unmodeled":
        raise ValueError("Unsupported bulk material state")
    if not isinstance(packet["source"],str) or not 1<=len(packet["source"])<=128:
        raise ValueError("Bulk material needs source provenance")
    contents=packet["contents"]
    if not isinstance(contents,list) or not 1<=len(contents)<=32: raise ValueError("Invalid bulk contents")
    seen=set()
    for item in contents:
        obj(item,{"substance","volume_m3","mass_kg"},{"substance","volume_m3","mass_kg"})
        substance=item["substance"]
        if not isinstance(substance,str) or not 1<=len(substance)<=80 or substance in seen:
            raise ValueError("Invalid or duplicate bulk substance")
        seen.add(substance)
        number(item["volume_m3"],"volume_m3",1e-12,1e6)
        number(item["mass_kg"],"mass_kg",1e-12,1e9)
    return packet


def receive_bulk(state,body,packet):
    """Trusted adapter only: the debit and this candidate must commit together."""
    if check_request(state,body): return deepcopy(state),True
    bulk_packet(packet)
    out=deepcopy(state)
    out.setdefault("raw_lots",{})[body["request_id"]]=deepcopy(packet)
    out["receipts"][body["request_id"]]=digest(body)
    out["revision"]+=1
    validate_state(out)
    return out,False


def raw_inventory(state):
    """Retain original receipts; derive the unspent contents of every raw lot."""
    remaining = {ident: {item["substance"]: deepcopy(item) for item in packet["contents"]}
                 for ident, packet in state.get("raw_lots", {}).items()}
    returns=state.get("raw_returns", {})
    if not isinstance(returns,dict) or len(returns)>4096: raise ValueError("Invalid raw material returns")
    for ident,record in returns.items():
        token(ident);obj(record,{"lot_id","packet"},{"lot_id","packet"})
        if ident not in state["receipts"]: raise ValueError("Raw return has no receipt")
        lot=record["lot_id"];token(lot,"lot_id")
        if lot not in remaining: raise ValueError("Raw return has no source lot")
        packet=bulk_packet(record["packet"])
        if packet["source"]!="excavated_ground" or state["raw_lots"][lot]["source"]!="excavated_ground":
            raise ValueError("Only excavated ground can return to carrying")
        for item in packet["contents"]:
            have=remaining[lot].get(item["substance"])
            if have is None or item["volume_m3"]>have["volume_m3"] or item["mass_kg"]>have["mass_kg"]:
                raise ValueError("Raw return exceeds source lot")
            if not math.isclose(item["mass_kg"],item["volume_m3"]*1600,rel_tol=1e-12,abs_tol=1e-10):
                raise ValueError("Raw return mass does not match native volume")
            have["volume_m3"]-=item["volume_m3"];have["mass_kg"]-=item["mass_kg"]
    return {ident:list(contents.values()) for ident,contents in remaining.items()}


def return_bulk(state,body):
    """Trusted transaction candidate; the native receipt must commit with it."""
    if check_request(state,body): return deepcopy(state),True
    lot=token(body["lot_id"],"lot_id")
    remaining=raw_inventory(state)
    if lot not in remaining or state["raw_lots"][lot]["source"]!="excavated_ground":
        raise ValueError("Choose an excavated raw lot")
    amounts={k:number(body[k],k,0,10000) for k in ("sand_m3","soil_m3")}
    if sum(amounts.values())<=0: raise ValueError("Choose a positive quantity to retrieve")
    available={v["substance"]:v for v in remaining[lot]}
    contents=[]
    for substance in ("sand","soil"):
        volume=amounts[substance+"_m3"]
        if volume>available.get(substance,{}).get("volume_m3",0): raise ValueError("Insufficient raw material in lot")
        if volume:
            # Full returns use the exact remainder, avoiding a rounding crumb.
            have=available[substance]
            mass=have["mass_kg"] if volume==have["volume_m3"] else volume*1600
            contents.append({"substance":substance,"volume_m3":volume,"mass_kg":mass})
    out=deepcopy(state)
    out.setdefault("raw_returns",{})[body["request_id"]]={"lot_id":lot,"packet":{
        "schema":"banjo.bulk-material.v1","source":"excavated_ground","form":"granular",
        "thermal_state":"unmodeled","contents":contents}}
    out["receipts"][body["request_id"]]=digest(body);out["revision"]+=1
    validate_state(out)
    return out,False


def validate_ground_stock(state,world,transfers=None):
    """The receiving account must match the native source's cumulative debit."""
    received={"sand_m3":0.,"soil_m3":0.,"rock_m3":0.}
    for packet in state.get("raw_lots",{}).values():
        if packet["source"]!="excavated_ground": continue
        for item in packet["contents"]:
            key=item["substance"]+"_m3"
            if key not in ("sand_m3","soil_m3"): raise ValueError("Unsupported excavated substance")
            # These are the declared native bulk densities, not solid presets.
            if not math.isclose(item["mass_kg"],item["volume_m3"]*1600,rel_tol=1e-12,abs_tol=1e-10):
                raise ValueError("Raw material mass does not match native volume")
            received[key]+=item["volume_m3"]
    returned={"sand_m3":0.,"soil_m3":0.,"rock_m3":0.}
    raw_inventory(state)
    for record in state.get("raw_returns",{}).values():
        for item in record["packet"]["contents"]:
            returned[item["substance"]+"_m3"]+=item["volume_m3"]
    from .ground_transfers import totals
    other = totals(transfers)
    for key in returned:
        returned[key] += other["returned"][key]
        received[key] += other["exported"][key]
    native_returns=(world.get("ground") or {}).get("returned",{})
    for key,total in returned.items():
        if not math.isclose(total,number(native_returns.get(key,0),"returned volume",0,1e12),rel_tol=1e-12,abs_tol=1e-10):
            raise ValueError("Raw returns do not match native ground receipts")
    exported=(world.get("ground") or {}).get("exported",{})
    for key,total in received.items():
        source=number(exported.get(key,0),"exported volume",0,1e12)
        if not math.isclose(total,source,rel_tol=1e-12,abs_tol=1e-10):
            raise ValueError("Raw stock does not match native ground exports")
    return received

def ground_audit(state, ground, transfers=None):
    """Read-only cross-boundary diagnostics from the current native report.

    Authored terrain deposits may include outside material. Without a separate
    import history their net contribution cannot be certified as conservation.
    """
    if not ground:
        return {"status": "unavailable", "substances": {},
                "boundary": "No live terrain report is available"}
    received = {"sand": [0., 0.], "soil": [0., 0.]}
    for packet in (state or {}).get("raw_lots", {}).values():
        bulk_packet(packet)
        if packet["source"] != "excavated_ground": continue
        for item in packet["contents"]:
            if item["substance"] not in received: raise ValueError("Unsupported excavated substance")
            amounts = received[item["substance"]]
            amounts[0] += item["volume_m3"]; amounts[1] += item["mass_kg"]
    for record in (state or {}).get("raw_returns",{}).values():
        for item in record["packet"]["contents"]:
            amounts=received[item["substance"]]
            amounts[0]-=item["volume_m3"];amounts[1]-=item["mass_kg"]
    from .ground_transfers import totals
    other=totals(transfers)
    for substance,amounts in received.items():
        delta=other["exported"][substance+"_m3"]-other["returned"][substance+"_m3"]
        amounts[0]+=delta; amounts[1]+=delta*1600
    rows = {}
    for substance, (volume, mass) in received.items():
        key = substance + "_m3"
        def quantity(account):
            return number(account[key], key, 0, 1e12)
        ledger = ground["ledger"]
        dug = quantity(ledger["dug"])
        deposited = quantity(ledger["deposited"])
        carried = quantity(ground.get("carried_all",ground["carried"]))
        exported = quantity(ground.get("exported", {"sand_m3": 0., "soil_m3": 0.}))
        returned = quantity(ground.get("returned", {"sand_m3":0.,"soil_m3":0.}))
        transfer_residual = exported - returned - volume
        density_residual = mass - volume * 1600.
        terrain_residual = ground["residual"][key]
        number(abs(terrain_residual), "terrain residual", 0, 1e12)
        # Positive means net outside input is needed to explain these accounts;
        # negative means excavated material has no recorded destination.
        external = deposited + carried + exported - returned - dug
        tolerance = 1e-10 + 1e-12 * max(dug, deposited, carried, exported)
        closed = abs(transfer_residual) <= tolerance and abs(density_residual) <= 1e-10 + 1e-12*mass
        rows[substance] = {"excavated_m3": dug, "deposited_m3": deposited,
            "carried_m3": carried, "exported_m3": exported, "returned_m3": returned,
            "stored_m3": volume, "stored_kg": mass,
            "transfer_residual_m3": transfer_residual,
            "density_residual_kg": density_residual,
            "terrain_residual_m3": terrain_residual,
            "net_external_or_untracked_m3": external,
            "transfer_closed": closed,
            "collection_status": "balanced" if abs(external) <= tolerance else
                "external_input_or_error" if external > 0 else "unaccounted_destination"}
    return {"status": "matched" if all(r["transfer_closed"] for r in rows.values()) else "mismatch",
        "substances": rows,
        "boundary": "Native excavated sand/soil, carried material, deposits and receiving raw lots; rock bodies, energy and thermal transport excluded",
        "qualification": "Matching exports and receipts is not whole-world conservation. Authored deposits lack independent import history; net external or untracked volume remains visible."}


def advance(state, time_s):
    """Exact constant-power thermal segments, driven only by accepted native time.

    dH/dt = P - G*H/C. Supply exhaustion, work completion and the thermal ceiling
    are event boundaries. At the ceiling a power limiter admits at most G*H/C.
    Calling with small or large native batches does not change the process law.
    """
    target = number(time_s, "time_s")
    if target < state["time_s"]-1e-8:
        raise ValueError("Fabrication time cannot rewind; restore the complete room")
    left = max(0., target-state["time_s"])
    c = state["config"]; cap = c["heat_capacity_j_k"]; g = c["cooling_w_k"]
    ceiling = cap*(c["max_temperature_k"]-AMBIENT_K)
    job = next((j for j in state["jobs"].values() if j["status"] == "running"), None)
    while left > 1e-10:
        heat = state["station_heat_j"]
        power = c["power_w"] if job is not None and state["energy_j"] > 0 else 0.
        if heat >= ceiling-max(1e-10,ceiling*1e-12):
            power = min(power, g*heat/cap)
        if power <= 0:
            lost = heat * -math.expm1(-g*left/cap)
            state["station_heat_j"] -= lost; state["ambient_j"] += lost
            break
        dt = min(left, state["energy_j"]/power,
                 max(0.,job["required_j"]-job["work_j"])/(c["efficiency"]*power))
        if heat < ceiling-max(1e-10,ceiling*1e-12):
            if g == 0:
                dt = min(dt,(ceiling-heat)/power)
            elif power*cap/g > ceiling:
                ratio = (ceiling-heat)/(power*cap/g-heat)
                if ratio < 1: dt = min(dt,-cap/g*math.log1p(-ratio))
        if dt <= 0: raise ValueError("Fabrication event failed to advance")
        supplied = min(state["energy_j"],power*dt)
        if g:
            change = -math.expm1(-g*dt/cap)
            new_heat = heat + (power*cap/g-heat)*change
        else: new_heat = heat+supplied
        state["ambient_j"] += max(0.,heat+supplied-new_heat)
        state["station_heat_j"] = new_heat
        state["energy_j"] -= supplied; state["spent_j"] += supplied
        job["supplied_j"] += supplied; job["work_j"] += supplied*c["efficiency"]
        left = max(0.,left-dt)
        if job["required_j"]-job["work_j"] <= 1e-10*max(1,job["required_j"]):
            job["work_j"] = job["required_j"]; job["status"] = "ready"
            waste = job["stock_kg"]-job["product_kg"]
            state["waste_kg"][job["material"]] = state["waste_kg"].get(job["material"],0.)+waste
            job = None
    state["time_s"] = target

def check_request(state, body):
    ident = token(body.get("request_id"))
    fingerprint = digest(body)
    receipt = state["receipts"].get(ident)
    if receipt:
        if receipt != fingerprint: raise ValueError("request_id already used for a different operation")
        return True
    if len(state["receipts"]) >= 4096: raise ValueError("Receipt budget exhausted; no old receipt may be forgotten")
    if type(body.get("revision")) is not int or body["revision"] != state["revision"]:
        raise ValueError("Fabrication revision changed; refresh before spending shared stock")
    return False

def mutate(state, body, *, quote=None):
    """Atomic candidate; the room persists this alongside the native snapshot."""
    if check_request(state, body): return deepcopy(state), True
    out = deepcopy(state); op = body["op"]
    if op == "start":
        if any(j["status"] == "running" for j in out["jobs"].values()):
            raise ValueError("The station is occupied; pause its current job first")
        if len(out["jobs"]) >= MAX_JOBS: raise ValueError("Workpiece budget exhausted")
        if quote is None: raise ValueError("A trusted compiled quote is required")
        material = quote["material"]; stock = quote["stock_kg"]
        if out["stock_kg"].get(material,0.)+1e-10 < stock:
            raise ValueError("Insufficient stock; no material was reserved")
        out["stock_kg"][material] = max(0.,out["stock_kg"][material]-stock)
        out["jobs"][body["request_id"]] = {**deepcopy(quote), "status": "running", "work_j": 0., "supplied_j": 0.}
    elif op == "recover":
        material = body.get("material")
        if not isinstance(material, str) or not engine_materials.known(material):
            raise ValueError("Unknown recovery material")
        material = engine_materials.canonical(material)
        mass = number(body.get("mass_kg"), "mass_kg", .000001, 10000)
        available = out["waste_kg"].get(material, 0.)
        if mass > available:
            raise ValueError("Insufficient offcuts; recovery cannot consume workpieces or installed parts")
        # Both bins contain the same cold material under this lumped process
        # law. Moving it between bins is not another manufacture or energy input.
        out["waste_kg"][material] = available - mass
        out["stock_kg"][material] = out["stock_kg"].get(material, 0.) + mass
    elif op in ("pause", "resume"):
        job = out["jobs"].get(token(body.get("job_id"),"job_id"))
        if job is None: raise ValueError("Unknown workpiece")
        if op == "pause":
            if job["status"] != "running": raise ValueError("Only running work may be paused")
            job["status"] = "paused"
        else:
            if job["status"] != "paused": raise ValueError("Only paused work may resume")
            if any(j["status"] == "running" for j in out["jobs"].values()):
                raise ValueError("The station is occupied")
            job["status"] = "running"
    else: raise ValueError("Unknown fabrication operation")
    out["revision"] += 1
    out["receipts"][body["request_id"]] = digest(body)
    validate_state(out)
    return out, False

def transfer(state, job_id, preview, request_id):
    """Internal room-commit operation; never accepts client mass or a verdict."""
    out = deepcopy(state)
    job = out["jobs"].get(token(job_id, "job_id"))
    if job is None or job["status"] != "ready": raise ValueError("That workpiece is not a finished, uninstalled output")
    if job["matter_physics_hash"] != preview["matter_physics_hash"] or abs(job["product_kg"]-preview["mass_kg"]) > 1e-8:
        raise ValueError("Installed matter differs from the funded workpiece")
    job.update(status="installed", root_body=preview["root_body"], install_request_id=request_id)
    if "root_bodies" in preview:
        job.update(root_bodies=deepcopy(preview["root_bodies"]), component_to_body=deepcopy(preview["component_to_body"]))
    m = job["material"]; out["transferred_kg"][m] = out["transferred_kg"].get(m,0.)+job["product_kg"]
    out["revision"] += 1
    validate_state(out)
    return out

def report(state):
    validate_state(state)
    out = deepcopy(state); out.pop("receipts")
    out["raw_inventory"] = raw_inventory(state)
    out["temperature_k"] = temperature(state)
    out["audit"] = audit(state); out["limitations"] = LIMITATIONS
    for job in out["jobs"].values():
        job["fraction"] = job["work_j"]/job["required_j"]
        job["condition"] = (job["status"] if job["status"] != "running" else
            "supply exhausted" if state["energy_j"] <= 1e-12 else
            "thermal limit" if temperature(state) >= state["config"]["max_temperature_k"]-1e-8 else "working")
    return out
