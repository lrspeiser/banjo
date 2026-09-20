"""Material QA adapters for the platform MCP; same runner as the HTTP area."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "playground"))
import material_qa
from mcp import workshop_mcp_tools

def app():
    return workshop_mcp_tools.APP

def catalog(arguments):
    if arguments:
        raise ValueError("material_qa_catalog accepts no arguments")
    return material_qa.catalog(app().engine_path)

def run(arguments):
    return material_qa.manager(app()).start(arguments)

def status(arguments):
    if set(arguments) - {"run_id"}:
        raise ValueError("status accepts only run_id")
    manager = material_qa.manager(app())
    return manager.status(arguments["run_id"]) if arguments.get("run_id") else manager.list_runs()

def case(arguments):
    if set(arguments) != {"run_id", "case_id"}:
        raise ValueError("case requires run_id and case_id")
    return material_qa.manager(app()).case(arguments["run_id"], arguments["case_id"])

def cancel(arguments):
    if set(arguments) != {"run_id"}:
        raise ValueError("cancel requires run_id")
    return material_qa.manager(app()).cancel(arguments["run_id"])

def tool(name, description, properties, required=()):
    return {"name": name, "description": description, "inputSchema": {
        "type": "object", "properties": properties, "required": list(required), "additionalProperties": False}}

RUN_ID = {"type": "string", "pattern": "^[0-9a-f]{32}$"}
TOOLS = [
    tool("material_qa_catalog", "Describe the fixed native material impact range, limits and engine availability. No world mutation.", {}),
    tool("material_qa_run", "Start an isolated recorded QA suite. Omit case_ids for all materials, thicknesses and speeds. Poll material_qa_status; one active run.", {
        "case_ids": {"type": "array", "items": {"type": "string", "enum": [c["id"] for c in material_qa.cases()]},
                     "minItems": 1, "maxItems": len(material_qa.cases()), "uniqueItems": True}}),
    tool("material_qa_status", "Read QA progress/results, or list saved runs if run_id is omitted.", {"run_id": RUN_ID}),
    tool("material_qa_case", "Read measured outcome, invariant failures and baseline changes for a completed impact. Recordings are viewed in /qa.", {
        "run_id": RUN_ID, "case_id": {"type": "string"}}, ("run_id", "case_id")),
    tool("material_qa_cancel", "Cancel the active QA suite and stop its native child, preserving completed evidence.", {"run_id": RUN_ID}, ("run_id",)),
]
HANDLERS = {"material_qa_catalog": catalog, "material_qa_run": run,
            "material_qa_status": status, "material_qa_case": case, "material_qa_cancel": cancel}
