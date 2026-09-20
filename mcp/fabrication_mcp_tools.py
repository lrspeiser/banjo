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
    "stock_kg":{"type":"object","description":"Catalog material -> .001..10000 kg; duplicate aliases refuse."},
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
    "store_ground": {"sand_m3":{"type":"number","minimum":0,"maximum":10000},"soil_m3":{"type":"number","minimum":0,"maximum":10000},"request_id":TOKEN,"revision":REVISION},
    "preview": {"job_id":TOKEN,"position_m":{"type":"array","items":{"type":"number"},"minItems":2,"maxItems":2}},
    "commit": {"job_id":TOKEN,"preview_id":TOKEN,"request_id":TOKEN},
    "wait": {"seconds":{"type":"integer","minimum":1,"maximum":10}},
}
DESCRIPTIONS = {
    "state": "Read finite stock, energy, workpieces, heat and ledger residuals without advancing time.",
    "configure": "Author the room's initial cold stock, finite isolated supply and declared process law once. Cannot refill, reset or change an existing station.",
    "quote": "Compile exact Workshop lattice matter and calculate stock, offcuts and declared work. Does not spend anything; candidate must include primary_use.",
    "start": "Reserve stock and start a bounded process using a trusted compiled quote. revision prevents concurrent spending; request_id makes retries safe.",
    "pause": "Interrupt a job while keeping its actual reserved workpiece, work and heat; no refund.",
    "resume": "Continue a paused workpiece from its retained work. Needs a free station; spent energy is not restored.",
    "recover": "Transfer measured same-material cold offcuts back to available stock. No new material or refunded energy; excludes installed parts, workpieces and mined ground. revision prevents shared spending; request_id makes retries safe.",
    "store_ground": "Atomically move measured carried sand and soil into saved raw lots. Read carried_ground with fabrication_state. Native debit, lots and retry receipt save together. Returns the replacement session; use it for later calls. Raw substances remain unprocessed with unmodeled thermal state, not glass or solid stock. No object is consumed.",
    "preview": "Check native placement and state carry for a finished funded workpiece on native ground. Terrain and material accounts must carry unchanged; unsettled-ground edits can refuse. position_m is [x,z]. Preview never installs.",
    "commit": "Atomically transfer the finished workpiece into the native world, persist both ledgers and world, then acknowledge. Retry the same request_id after an uncertain result.",
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
