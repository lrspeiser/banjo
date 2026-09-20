"""MCP access to the same bounded physics experiments as the local lab."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"playground"))
import mechanics_qa
import physics_trials
import gameplay_capabilities
from mcp import workshop_mcp_tools
from mcp.material_qa_tools import tool, RUN_ID

def catalog(args):
    if args: raise ValueError("physics_trial_catalog takes no arguments")
    return mechanics_qa.catalog(workshop_mcp_tools.APP.engine_path)

def validate(args):
    physics_trials.obj(args, {"document"}, {"document"}, "validate")
    doc, _ = physics_trials.validate(args["document"])
    return {"valid": True, "document": doc, "limitations": physics_trials.LIMITATIONS}

def run(args):
    return mechanics_qa.manager(workshop_mcp_tools.APP).start(args)

def status(args):
    physics_trials.obj(args, {"run_id"}, set(), "status")
    manager=mechanics_qa.manager(workshop_mcp_tools.APP)
    return manager.status(args["run_id"]) if args.get("run_id") else manager.list_runs()

def case(args):
    physics_trials.obj(args, {"run_id", "case_id", "artifact"}, {"run_id", "case_id"}, "case")
    artifact = args.get("artifact", "result")
    if artifact not in ("result", "request", "playback"): raise ValueError("Unknown case artifact")
    return mechanics_qa.manager(workshop_mcp_tools.APP).case(args["run_id"], args["case_id"],
        playback=artifact == "playback", request=artifact == "request")

def cancel(args):
    physics_trials.obj(args, {"run_id"}, {"run_id"}, "cancel")
    return mechanics_qa.manager(workshop_mcp_tools.APP).cancel(args["run_id"])

def gameplay_status(args):
    if args: raise ValueError("physics_gameplay_status takes no arguments")
    return gameplay_capabilities.catalog()

DOCUMENT={"type":"object", "description":"banjo.physics-trial.v1 document; call physics_trial_catalog for executable examples, SI fields, operations and limits. Initial bodies plus bounded physical operations and measured assertions.",
          "properties":{"schema":{"type":"string","enum":[physics_trials.SCHEMA]},
              "title":{"type":"string"}, "cell_m":{"type":"number"},
              "bodies":{"type":"array","items":{"type":"object"}},
              "actuator":{"type":"object"}, "steps":{"type":"array","items":{"type":"object"}},
              "checks":{"type":"array","items":{"type":"object"}}},
          "required":["schema","title","cell_m","bodies","steps","checks"], "additionalProperties":False}
TOOLS=[
 tool("physics_trial_catalog","Get editable native experiment examples, SI operations, measurement names and limits. Mechanics are compositions of bodies and constraints, not game-feature scripts.",{}),
 tool("physics_trial_validate","Validate a proposed experiment before starting the engine. Does not execute or change the live world.",{"document":DOCUMENT},("document",)),
 tool("physics_trial_run","Run an isolated native experiment. Pass document for edited experiments, case_ids for regression cases, or neither for the full mechanics suite. Poll status. Custom checks never replace regression acceptance.",{
     "document":DOCUMENT,"case_ids":{"type":"array","items":{"type":"string"},"uniqueItems":True}}),
 tool("physics_trial_status","Read experiment status, measurements, provenance and failed checks; omit run_id to list saved runs.",{"run_id":RUN_ID}),
 tool("physics_trial_case","Inspect one recorded case, including native joint-failure reasons and actual measurements.",{"run_id":RUN_ID,"case_id":{"type":"string"},"artifact":{"type":"string","enum":["result","request","playback"]}},("run_id","case_id")),
 tool("physics_trial_cancel","Stop this application's active mechanics experiment, retaining its completed evidence.",{"run_id":RUN_ID},("run_id",)),
 tool("physics_gameplay_status","Read all 30 player capabilities in priority order, completion counts, partial evidence and remaining acceptance gates. No physics is run and no completion is inferred from a demonstration.",{}),
]
HANDLERS=dict(zip((t["name"] for t in TOOLS),(catalog,validate,run,status,case,cancel,gameplay_status)))
