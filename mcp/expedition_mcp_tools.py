"""MCP access to the SAME live browser expedition, through its local HTTP API."""
from __future__ import annotations
import json
import os
from urllib import request, error
from urllib.parse import urlsplit
from circuit_api import obj, NAME, validate

SESSION = {"session": NAME}
ACTION = obj({
    "action": {"type": "string", "enum": ["gather", "build", "load", "fuel", "light", "extinguish", "collect"]},
    "request_id": {"type": "string", "minLength": 1, "maxLength": 80},
    "at_m": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
    "node": NAME, "kg": {"type": "number", "exclusiveMinimum": 0, "maximum": 2}
}, ["action", "request_id", "at_m"])
TOOLS = [
    {"name": "expedition_wait", "description":
     "Advance the live expedition and its native water/mechanics by 1 to 30 seconds, "
     "one accepted second at a time. This operates on the browser session; pause browser "
     "stepping first to avoid also advancing in realtime. On a connection error read state "
     "before issuing another wait: accepted elapsed time is never rolled back.",
     "inputSchema": obj({**SESSION, "seconds": {"type": "integer", "minimum": 1, "maximum": 30}},
                        ["session", "seconds"])},
    {"name": "expedition_open", "description":
     "Open or rejoin the persistent personal expedition in the local playground. "
     "Returns its live session and finite resource/process state. Requires the "
     "playground server (BANJO_PLAYGROUND_URL, default http://127.0.0.1:8765). "
     "Never resets an existing expedition. This is the browser's world, not an MCP authoring copy.",
     "inputSchema": obj({}, [])},
    {"name": "expedition_state", "description":
     "Read the live expedition clock, remaining surface stocks, material pack, "
     "dryer contents/heat/damage and local conservation residuals without advancing time.",
     "inputSchema": obj(SESSION, ["session"])},
    {"name": "expedition_action", "description":
     "Gather nearby loose material, build the drying camp, load wet timber or dry fuel, "
     "light/extinguish, or collect cool dry output. Kilograms, coordinates in metres. "
     "Use a unique request_id; retry it unchanged after connection loss. Saves the "
     "native and gameplay states together before success. No free material or heating.",
     "inputSchema": obj({**SESSION, "action": ACTION}, ["session", "action"])}
]


def _post(path, body):
    url = os.environ.get("BANJO_PLAYGROUND_URL", "http://127.0.0.1:8765").rstrip("/")
    parsed = urlsplit(url)
    if parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost", "::1") or parsed.path or parsed.username:
        raise ValueError("BANJO_PLAYGROUND_URL must be a loopback HTTP origin")
    with request.urlopen(url + "/api/status", timeout=15) as response:
        token = json.load(response)["csrf_token"]
    req = request.Request(url + path, data=json.dumps(body, allow_nan=False).encode(),
                          headers={"Content-Type": "application/json", "X-Banjo-Token": token})
    try:
        with request.urlopen(req, timeout=120) as response:
            return json.load(response)
    except error.HTTPError as failure:
        detail = json.load(failure)
        raise ValueError(detail.get("error", "The playground refused this request")) from None


def register(core):
    def call(name, args):
        if name == "expedition_open":
            answer = _post("/api/world/open", {"scene": "expedition"})
            return {"session": answer["session"], "gameplay": answer["gameplay"]}
        if name == "expedition_wait":
            _post("/api/world/gameplay", {"session": args["session"], "op": "state"})
            for _ in range(args["seconds"]):
                answer = _post("/api/live/act", {"session": args["session"], "op": "step", "dt": 1/120, "n": 120})
            return {"gameplay": answer["gameplay"]}
        return _post("/api/world/gameplay", {**args, "op": "state" if name == "expedition_state" else "action"})
    for tool in TOOLS:
        def handler(args, tool=tool):
            try:
                validate(args, tool["inputSchema"], "arguments")
                return call(tool["name"], args)
            except (ValueError, OSError, KeyError) as exc:
                raise core.Refused(str(exc)) from None
        core.HANDLERS[tool["name"]] = handler
    core.TOOLS.extend(TOOLS)
