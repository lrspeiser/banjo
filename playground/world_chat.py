"""The model's side of the room: real tools over a live world.

The other chat in this playground writes a scene file in one shot. This one has
hands. It can ask what is in the room and where, and it can put things in, move
them and take them out -- and it is told what the person has been doing, because
a model asked to change a room it cannot see is otherwise answering about the
room as authored rather than the room as it is now.

Nothing here decides physics. The tools say which objects exist and where; what
happens to them is the engine's answer, and the person is watching it happen.
"""
from __future__ import annotations

import json
import time
from typing import Any
from urllib import error, request

import world_room

# How many times the model may call tools before an answer is expected. A
# request like "clear the room and build a tower of six blocks" is one list and
# seven changes, so the bound has to be above that; past it, something is
# looping rather than working.
MAX_ROUNDS = 12
# Two minutes is already a long time to watch a chat box. Each round is one
# model round trip and nothing else.
TIMEOUT_S = 60


def _call(api_key: str, model: str, conversation: list[dict[str, Any]]) -> dict[str, Any]:
    payload = {"model": model, "store": False, "max_output_tokens": 4000,
               "reasoning": {"effort": "low"},
               "instructions": world_room.GUIDE,
               "tools": world_room.TOOLS,
               "input": conversation}
    req = request.Request("https://api.openai.com/v1/responses",
                          data=json.dumps(payload, allow_nan=False).encode(), method="POST",
                          headers={"Authorization": "Bearer " + api_key,
                                   "Content-Type": "application/json"})
    try:
        with request.urlopen(req, timeout=TIMEOUT_S) as response:
            raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise ValueError("the model's answer exceeded the size budget")
            return json.loads(raw)
    except error.HTTPError as exc:
        # The upstream body can echo the key or the input. Do not log it.
        raise ValueError(f"the model request failed (HTTP {exc.code}); check the local "
                         f"key, model access and account limits") from None
    except (error.URLError, TimeoutError):
        raise ValueError("the model could not be reached, and no paid retry was issued") from None


def ask(api_key: str, model: str, room: world_room.Room, live_state: dict[str, Any],
        message: str, story: list[str]) -> dict[str, Any]:
    """One turn. Returns what to say, what was changed, and whether to reopen.

    `live_state` is the world as the ENGINE has it -- pieces, dents and all --
    which is what list_objects answers from. `room` is the authored set, which
    is what the changes are made to. They are different on purpose: a room that
    has been rebuilt from two hundred shards is not what anyone means when they
    ask to add a ball to it.
    """
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not set in the local .env, so the room has "
                         "nobody to talk to. Add it and restart the server. Everything "
                         "else on this page works without it.")

    opening = {"what_you_were_asked": message,
               "what_the_person_has_been_doing": story[-24:] or ["nothing yet"],
               "objects_now": world_room.describe(live_state)}
    conversation: list[dict[str, Any]] = [
        {"role": "user", "content": json.dumps(opening, allow_nan=False)}]

    did: list[str] = []
    changed = False
    started = time.perf_counter()

    for _ in range(MAX_ROUNDS):
        result = _call(api_key, model, conversation)
        if result.get("status") != "completed":
            raise ValueError("the model did not finish an answer; try a shorter request")

        outputs = result.get("output", [])
        calls = [o for o in outputs if o.get("type") == "function_call"]
        said: list[str] = []
        for output in outputs:
            for content in output.get("content", []) or []:
                if content.get("type") == "refusal":
                    raise ValueError("the model declined this request")
                if content.get("type") == "output_text":
                    said.append(content.get("text", ""))

        if not calls:
            return {"reply": "".join(said).strip() or "Done.", "did": did,
                    "changed": changed, "wall_s": round(time.perf_counter() - started, 2)}

        # Carry the model's own turn forward, then answer each call. Both are
        # required: dropping the call itself leaves the next request describing
        # an answer to a question that was never asked.
        conversation.extend(calls)
        for call in calls:
            name = call.get("name", "")
            try:
                args = json.loads(call.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            try:
                if name == "list_objects":
                    answer = {"objects": world_room.describe(live_state)}
                elif name in ("add_object", "move_object", "remove_object", "clear_room"):
                    note = getattr(room, name)(args)
                    did.append(note)
                    changed = True
                    # The whole record back, not just a yes. A model that is
                    # about to describe what it built should be describing the
                    # thing that exists rather than the thing it meant.
                    answer = {"ok": True, "did": note,
                              "room_now": [{"name": b["name"], "material": b["material"],
                                            "position_mm": b["center_mm"]}
                                           for b in room.bodies()]}
                else:
                    answer = {"error": f"there is no tool called {name}"}
            except ValueError as problem:
                # Handed back rather than raised: a bad argument is something
                # the model can fix on the next round, and a room that stops
                # dead because one number was out of range is worse than one
                # that says so.
                answer = {"error": str(problem)}
            conversation.append({"type": "function_call_output",
                                 "call_id": call.get("call_id"),
                                 "output": json.dumps(answer, allow_nan=False)})

    raise ValueError(f"the model was still working after {MAX_ROUNDS} rounds; "
                     f"ask for one change at a time")
