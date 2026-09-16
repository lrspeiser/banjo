"""Natural-language adapter for the bounded Workshop component editor.

The model never receives live-world tools. It may only select one of the same
component operations the buttons expose, or choose one saved component to reuse.
A small deterministic fallback keeps common commands working when no model key
is configured (including CI/local development).
"""
from __future__ import annotations

import json
from typing import Any
from urllib import error, request

ACTIONS = ("longer", "shorter", "thicker", "thinner", "wider", "narrower", "material", "reuse", "none")

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["reply", "action", "scope", "material", "library_item_id"],
    "properties": {
        "reply": {"type": "string"},
        "action": {"type": "string", "enum": list(ACTIONS)},
        "scope": {"type": "string", "enum": ["this", "similar", "all"]},
        "material": {"type": ["string", "null"]},
        "library_item_id": {"type": ["string", "null"]},
    },
}

SYSTEM = """You edit one selected component inside Banjo Workshop.
You cannot change the live world. Choose exactly one bounded edit action.
- longer/shorter change the selected member's length.
- thicker/thinner change its section/thickness.
- wider/narrower change its x width.
- material requires one material from AVAILABLE MATERIALS.
- reuse chooses one compatible COMPONENT item from MY LIBRARY by item_id.
- none when the request cannot be expressed safely as one of these operations.
Scope 'this' changes one selected part; 'similar' changes same-family siblings;
'all' is only for an explicit whole-object request.
Keep reply concise and explain what you chose. Never invent a material or library item id.
"""


def fallback(message: str, *, materials: list[str], library: list[dict[str, Any]]) -> dict[str, Any]:
    lower = message.lower()
    action = "none"
    if any(w in lower for w in ("taller", "longer", "lengthen")): action = "longer"
    elif any(w in lower for w in ("shorter", "shorten")): action = "shorter"
    elif any(w in lower for w in ("thicker", "sturdier", "chunkier")): action = "thicker"
    elif any(w in lower for w in ("thinner", "slimmer")): action = "thinner"
    elif any(w in lower for w in ("wider", "broader")): action = "wider"
    elif "narrower" in lower: action = "narrower"
    material = next((m for m in materials if m.lower() in lower), None)
    if material: action = "material"
    selected_item = None
    for item in library:
        if item.get("item_type") == "component" and str(item.get("name") or "").lower() in lower:
            selected_item = str(item["item_id"]); action = "reuse"; break
    scope = "similar" if any(w in lower for w in ("all legs", "every leg", "all of them", "matching", "similar")) else "this"
    if any(w in lower for w in ("whole object", "everything", "entire object")): scope = "all"
    reply = (f"I'll make {scope} component(s) {action}." if action != "none"
             else "I can change length, thickness, width, material, or reuse a named component from My Library.")
    return {"reply": reply, "action": action, "scope": scope,
            "material": material, "library_item_id": selected_item}


def propose(app: Any, *, message: str, selected_part: dict[str, Any],
            candidate: dict[str, Any], materials: list[str], library: list[dict[str, Any]]) -> dict[str, Any]:
    message = " ".join(str(message).split())[:2000]
    if not message:
        raise ValueError("component chat needs a message")
    if not getattr(app, "api_key", ""):
        return fallback(message, materials=materials, library=library)
    context = {
        "request": message,
        "selected_component": selected_part,
        "candidate": {"kind": candidate.get("kind"), "purpose": candidate.get("purpose"),
                      "bom": candidate.get("bom")},
        "available_materials": materials,
        "my_library": [{k: item.get(k) for k in ("item_id", "item_type", "name", "family", "role")}
                       for item in library[:100]],
    }
    payload = {
        "model": getattr(app, "model", "gpt-5-mini"), "store": False,
        "max_output_tokens": 500, "reasoning": {"effort": "low"},
        "input": [{"role": "system", "content": SYSTEM},
                  {"role": "user", "content": json.dumps(context, allow_nan=False)}],
        "text": {"format": {"type": "json_schema", "name": "workshop_component_edit",
                            "strict": True, "schema": SCHEMA}},
    }
    req = request.Request("https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode(), method="POST",
        headers={"Authorization": "Bearer " + app.api_key, "Content-Type": "application/json"})
    try:
        with request.urlopen(req, timeout=45) as response:
            raw = response.read(256 * 1024 + 1)
    except error.HTTPError as exc:
        raise ValueError(f"Workshop chat failed (HTTP {exc.code})") from None
    except (error.URLError, TimeoutError):
        raise ValueError("Workshop chat connection failed or timed out") from None
    if len(raw) > 256 * 1024:
        raise ValueError("Workshop chat response exceeded its size budget")
    result = json.loads(raw)
    texts = []
    for output in result.get("output", []):
        for content in output.get("content", []):
            if content.get("type") == "output_text": texts.append(content.get("text", ""))
    answer = json.loads("".join(texts))
    if not isinstance(answer, dict) or answer.get("action") not in ACTIONS:
        raise ValueError("Workshop chat returned an invalid edit")
    if answer.get("material") not in (None, *materials):
        raise ValueError("Workshop chat chose a material outside the available pricebook")
    ids = {str(item.get("item_id")) for item in library if item.get("item_type") == "component"}
    if answer.get("library_item_id") is not None and str(answer["library_item_id"]) not in ids:
        raise ValueError("Workshop chat chose a component outside My Library")
    return answer
