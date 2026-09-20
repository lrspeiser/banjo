"""Open a saved browser world through the same startup transaction as the UI."""
from circuit_api import obj, validate
from expedition_mcp_tools import _post

TOOLS = [{
    "name": "world_open_saved",
    "description": "Open or rejoin a saved local browser world, without requesting a reset. "
        "Default scene is world. Applies pending trusted starting-equipment additions only "
        "when native state can be preserved; returns receipts or pending reasons. "
        "Switches the browser server's active room and returns its current session. "
        "Uses BANJO_PLAYGROUND_URL, not the standalone MCP authoring world.",
    "inputSchema": obj({"scene": {"type": "string", "enum": [
        "world", "yard", "valley", "clearing", "courtyard", "bench", "armoury",
        "watershed", "expedition", "fabrication"]}}, [])
}]


def register(core):
    def open_saved(args):
        try:
            validate(args, TOOLS[0]["inputSchema"], "arguments")
            result = _post("/api/world/open", {"scene": args.get("scene", "world")})
            return {key: result[key] for key in ("scene", "session", "t", "world_upgrades",
                "restored", "kept_problem", "machines", "inventory") if key in result}
        except (ValueError, OSError, KeyError) as exc:
            raise core.Refused(str(exc)) from None
    core.TOOLS.extend(TOOLS)
    core.HANDLERS["world_open_saved"] = open_saved
