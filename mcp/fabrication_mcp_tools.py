"""MCP adapters to the same persistent fabrication room used by the browser."""
from __future__ import annotations
from circuit_api import obj, NAME, validate
from expedition_mcp_tools import _post

COMMON = {"session": NAME, "scene": {"type":"string","description":"Current persistent room name returned by world_open_saved or fabrication_open."}}
TOKEN = {"type":"string","minLength":8,"maxLength":80}
REVISION = {"type":"integer","minimum":0}
JSON_OBJECT = {"type":"object"}
SETTINGS = obj({
    "mode":{"type":"string","enum":["authoring"]},
    "stock_kg":{"type":"object","description":"Catalog material -> 0..10000 kg; an empty map supplies nothing. Duplicate aliases refuse."},
    "energy_j":{"type":"number","minimum":0,"maximum":1e9},
    "power_w":{"type":"number","minimum":.001,"maximum":1e6},
    "work_j_kg":{"type":"number","minimum":.001,"maximum":1e9},
    "efficiency":{"type":"number","minimum":.001,"maximum":1,"default":1},
    "heat_capacity_j_k":{"type":"number","minimum":1,"maximum":1e9,"default":10000},
    "cooling_w_k":{"type":"number","minimum":0,"maximum":1e6,"default":0},
    "max_temperature_k":{"type":"number","minimum":293.16,"maximum":2000,"default":473.15},
},["mode","stock_kg","energy_j","power_w","work_j_kg"])
FIELDS = {
    "state": {}, "configure": {"settings":SETTINGS,"request_id":TOKEN},
    "quote": {"candidate":JSON_OBJECT,"stock_kg":{"type":"number","exclusiveMinimum":0}},
    "start": {"candidate":JSON_OBJECT,"stock_kg":{"type":"number","exclusiveMinimum":0},"request_id":TOKEN,"revision":REVISION},
    "pause": {"job_id":TOKEN,"request_id":TOKEN,"revision":REVISION},
    "resume": {"job_id":TOKEN,"request_id":TOKEN,"revision":REVISION},
    "recover": {"material":{"type":"string"},"mass_kg":{"type":"number","minimum":.000001,"maximum":10000},"request_id":TOKEN,"revision":REVISION},
    "retrieve_ground": {"lot_id":TOKEN,"sand_m3":{"type":"number","minimum":0,"maximum":10000},"soil_m3":{"type":"number","minimum":0,"maximum":10000},"request_id":TOKEN,"revision":REVISION},
    "store_ground": {"sand_m3":{"type":"number","minimum":0,"maximum":10000},"soil_m3":{"type":"number","minimum":0,"maximum":10000},"request_id":TOKEN,"revision":REVISION},
    "connect_energy": {"store":{"type":"integer","minimum":1,"maximum":4294967295},"store_hash":{"type":"string","minLength":64,"maxLength":64},"power_w":{"type":"number","minimum":.001,"maximum":1e6},"request_id":TOKEN,"revision":REVISION},
    "fund_energy": {"store_hash":{"type":"string","minLength":64,"maxLength":64},"joules":{"type":"number","minimum":.000001,"maximum":1e9},"request_id":TOKEN,"revision":REVISION},
    "fund_stock": {"material":{"type":"string"},"mass_kg":{"type":"number","minimum":.000001,"maximum":10000},"pool":{"type":"string","enum":["personal","shared"]},"rack_hash":{"type":"string","minLength":64,"maxLength":64},"request_id":TOKEN,"revision":REVISION},
    "fund_goods": {"material":{"type":"string","enum":["copper","copper wire"]},"mass_kg":{"type":"number","minimum":.000001,"maximum":10000},"pool":{"type":"string","enum":["personal","shared"]},"rack_hash":{"type":"string","minLength":64,"maxLength":64},"request_id":TOKEN,"revision":REVISION},
    "release_stock": {"reservation_id":TOKEN,"request_id":TOKEN},
    "plan_remake": {"source_item":NAME,"candidate":JSON_OBJECT},
    "start_remake": {"plan_id":TOKEN,"revision":REVISION,"request_id":TOKEN},
    "plan_make": {"candidate":JSON_OBJECT},
    "start_make": {"plan_id":TOKEN,"revision":REVISION,"request_id":TOKEN},
    "preview": {"job_id":TOKEN,"position_m":{"type":"array","items":{"type":"number"},"minItems":2,"maxItems":2}},
    "commit": {"job_id":TOKEN,"preview_id":TOKEN,"request_id":TOKEN},
    "wait": {"seconds":{"type":"integer","minimum":1,"maximum":10}},
}
DESCRIPTIONS = {
    "state": "Read finite stock, energy, workpieces, heat and ledger residuals without advancing time.",
    "configure": "Author the room's initial cold stock, finite isolated supply and declared process law once. Cannot refill, reset or change an existing station.",
    "quote": "Measure supported lattice matter or exact rigid assemblies/machines; calculate required material allocation, offcuts, declared work and initial battery charge. Does not spend anything; candidate must include primary_use. Exact machine quotes require the updated native material allocation export.",
    "start": "Atomically reserve each required material and initial product battery charge, then start a bounded process using a trusted compiled quote. Process energy advances with native time. revision prevents concurrent spending; request_id makes retries safe.",
    "pause": "Interrupt a job while keeping its actual reserved workpiece, work and heat; no refund.",
    "resume": "Continue a paused workpiece from its retained work. Needs a free station; spent energy is not restored.",
    "recover": "Transfer measured same-material cold offcuts back to available stock. No new material or refunded energy; excludes installed parts, workpieces and mined ground. revision prevents shared spending; request_id makes retries safe.",
    "retrieve_ground": "Atomically retrieve remaining sand/soil from one saved raw lot into native carrying, subject to the carrying limit. Read lot_id and remaining contents from fabrication_state raw_inventory. Returns a replacement session. Identical request_id retries do not spend twice. No conversion or thermal model is implied.",
    "store_ground": "Atomically move measured carried sand and soil into saved raw lots. Read carried_ground with fabrication_state. Native debit, lots and retry receipt save together. Returns the replacement session; use it for later calls. Raw substances remain unprocessed with unmodeled thermal state, not glass or solid stock. No object is consumed.",
    "connect_energy": "Connect one in-world native battery to the declared lumped charger. Read its ID and store_hash from fabrication_state energy_sources. power_w cannot exceed source or station limits. Begins a new time window with zero credit; reconnecting discards unused time. Saves identity and request receipt without spending energy. Not an electrical circuit model.",
    "fund_energy": "Transfer positive joules from the connected native battery into finite fabrication energy, bounded by accepted native time since connection/last transfer and declared power. Read current store_hash, transfer_available_j and revision from fabrication_state. Battery debit and process credit save atomically; identical request retries do not debit twice. Returns replacement session. No wallet debit, current waveform or calibrated repair claim.",
    "fund_stock": "Transfer actual catalog material from your personal rack or explicitly selected shared pool into SHARED fabrication stock. Read exact mass, pool and rack_hash from fabrication_state stock_sources. Source debit and durable reservation commit together; receiving save failure leaves recoverable escrow, visible in stock_reservations. State/retry finishes that credit once. Initial authorization checks revision/hash; recovery retains the original request. Cold inventory reference is an approximation, not native-body reclamation or measured thermal transport.",
    "fund_goods": "Transfer processed copper or copper wire from your personal goods inventory or explicitly selected shared pool into the finite assembly supplies. Read exact mass, pool and rack_hash from fabrication_state goods_sources. Uses the same durable debit/reservation/recovery and release rules as fund_stock. Raw material cannot replace processed goods. These assembly inputs are tracked separately from measured native geometry; constituent mass/mechanics remain unmodeled.",
    "release_stock": "Return your uncredited stock reservation to its exact source rack. Requires reservation_id from stock_reservations and a new request_id. Refuses if the receiving room already credited it, including a save whose acknowledgement failed. Release receipt is retry-safe. No refund of work, native products or credited material.",
    "plan_remake": "Review a frozen Lab candidate for an item currently in your hands or bag. Read-only; requires an already declared workbench process. Reports exact native material, energy/time costs, station shortages and original retained damage. No healing/reclamation or implicit resource grant. Other players cannot nominate your inventory.",
    "start_remake": "Start the reviewed plan_id with current revision and stable request_id. Source identity/topology/condition and the frozen design are bound to the job. Material is reserved and finite energy must cover its declared process cost. Retry unchanged after uncertainty. Original remains; preview/commit place a new product. Only the initiating player controls this remake.",
    "plan_make": "Review a new or saved design using the declared workbench process. Read-only exact native costs, stock/energy shortages and occupancy; no carried source is required and no resources are granted. Returns a frozen, player-owned plan_id.",
    "start_make": "Reserve real stock and start a reviewed new-item plan with enough finite energy. Use current revision and a stable request_id; retry unchanged after uncertainty. Owner-only control and placement persist with the frozen design. No original item is consumed or healed.",
    "preview": "Check native placement and state carry for a finished funded workpiece on native ground. Terrain and material accounts must carry unchanged; unsettled-ground edits can refuse. position_m is [x,z]. Preview never installs.",
    "commit": "Atomically transfer the finished workpiece into the native world, persist both ledgers and world, then acknowledge. Supports single-material fixed/bearing assemblies with primary_use_component and interaction_point_components bindings. Assemblies return root_bodies, component_to_body, source_joints and per-body thermal_transfers. Retry the same request_id after an uncertain result.",
    "wait": "Advance native physics and fabrication together for 1..10 seconds and save both. This is an elapsed-time action: after connection loss read state before repeating.",
}
TOOLS = [{"name":"fabrication_open","description":
    "Open or rejoin the persistent fabrication room in the local sim (BANJO_PLAYGROUND_URL). "
    "Keeps existing native and material state; never initializes stock automatically.",
    "inputSchema":obj({},[])}] + [
    {"name":"fabrication_"+op,"description":text,
     "inputSchema":obj({**COMMON,**FIELDS[op]},list(COMMON)+list(FIELDS[op]))}
    for op,text in DESCRIPTIONS.items()]
TOOLS += [
    {"name":"fabrication_qa_run","description":"Run the fixed native manufacturing, conservation, persistence and API/MCP regression in isolated temporary rooms; the live room is unchanged.","inputSchema":obj({},[])},
    {"name":"fabrication_qa_status","description":"Read a fabrication QA report; omit run_id to list recorded runs.","inputSchema":obj({"run_id":TOKEN},[])},
    {"name":"fabrication_qa_cancel","description":"Cancel this application's active isolated fabrication QA process and its owned children, retaining its report.","inputSchema":obj({"run_id":TOKEN},["run_id"])},
]

def call(name,args):
    if name.startswith("fabrication_qa_"):
        return _post("/api/fabrication-qa/"+name.removeprefix("fabrication_qa_"),args)
    if name == "fabrication_open":
        answer = _post("/api/world/open",{"scene":"fabrication"})
        return {"scene":"fabrication","session":answer["session"],
                "native_time_s":answer.get("t")}
    return _post("/api/world/fabrication/"+name.removeprefix("fabrication_"),args)

def register(core):
    for tool in TOOLS:
        def handler(args,tool=tool):
            try:
                validate(args,tool["inputSchema"],"arguments")
                return call(tool["name"],args)
            except (ValueError,OSError,KeyError) as exc:
                raise core.Refused(str(exc)) from None
        core.HANDLERS[tool["name"]] = handler
    core.TOOLS.extend(TOOLS)
