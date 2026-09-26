"""Talking to a machine (docs/machine-world.md, "Talking to the rover").

The person clicks the rover and opens its panel; "Talk to it" opens a chat
with it. The rover stops what it is doing and turns to face them (an ask on
its program, LiveWorld::behave, by the sender "talk"), and the chat opens with
what it was doing. What the person types is sorted into what they mean by Jev
-- a typed choice in a fraction of a second: stop, go on, come here, turn
round, back off, or asking what it is doing or why -- and each of those is
done at once, to the program, and answered in a sentence drawn from the
rover's own state, never invented. Anything else goes to the chat's model
(OPENAI_MODEL, the same one the room's chat uses), told to answer in the
rover's voice from that state alone and to change nothing. Without a Jev key
the sorting falls back to plain words; without an OpenAI key the rover says
what it can take. Closing the chat lets it go on: the ask is lifted and its
reflexes, and whatever thinks for it, have it back.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any
from urllib import error, request

import machine_tools as tools
import rover_brain

INTENTS = {
    "stop": "Stop, halt, wait, stay, hold still, do not move.",
    "go_on": "Carry on, go on, resume, continue, get back to work, go roam, you may go, goodbye.",
    "come_here": "Come here, come to me, come over, approach me, come closer.",
    "turn_around": "Turn around, turn round, about face, turn back, go the other way.",
    "back_off": "Back off, back up, reverse, go back a bit, get away from that.",
    "dig": "Dig here, take a scoop, dig for something, get some sand, soil or ore.",
    "dump": "Dump it, empty your hopper, drop the load, put it down here, unload onto the pile.",
    "take": "Take that, load up, pick up the ore, take some copper off the pile, fill your hopper from the heap.",
    "make": "Make a batch, process it, smelt, work the recipe, get to work on what is on your intake.",
    "order": "A job to do, then go back to its rounds: bring something somewhere, go and dig at a place, "
             "fetch goods from one pile to another, make so many batches, go somewhere and wait.",
    "cancel": "Never mind, forget it, cancel that, drop the order, stop what I told you.",
    "status": "What are you doing, where are you, how is your battery, what do your sensors see, report.",
    "why": "Why did you stop, why did you turn, why are you doing that, what happened, explain.",
    "other": "Anything else: a question about the world, chit-chat, an instruction it cannot take.",
}
INTENT_QUESTIONS = {
    "intent": {"type": "choice",
               "instructions": "The person is talking to a machine in a physics sandbox: `machine` says what "
                               "kind. `said` is what they typed. What do they mean it to do?",
               "criteria": INTENTS},
}
INTENT_LEAST = 0.5
# Plain words, for when Jev is not there to ask. First match wins: a question
# ("why did you stop?") before a command.
PLAIN = [
    ("why", r"\b(why|what happened|explain)\b"),
    ("cancel", r"\b(never mind|forget it|cancel|drop (that|the order))\b"),
    ("order", r"\b(bring|fetch|carry|haul|go (to|and)|then|dig .*\b(dump|bring|take)\b|from .*\bto\b)"),
    ("stop", r"\b(stop|halt|wait|stay|hold|freeze|don'?t move)\b"),
    ("come_here", r"\b(come|approach|closer|over here|to me)\b"),
    ("turn_around", r"\b(turn (a)?round|turn around|about face|other way|turn back)\b"),
    ("back_off", r"\b(back (off|up|away)|reverse|get away)\b"),
    ("dump", r"\b(dump|empty|drop (it|the load)|unload)\b"),
    ("take", r"\b(take|load up|pick up|fill your hopper)\b"),
    ("make", r"\b(make|process|smelt|work the|batch)\b"),
    ("dig", r"\b(dig|scoop|shovel)\b"),
    ("go_on", r"\b(go on|carry on|continue|resume|go roam|back to work|get going|off you go|bye|goodbye)\b"),
    ("status", r"\b(what are you|where are you|how is|how'?s|battery|sensors?|report|status|doing)\b"),
]
TALK_TIMEOUT_S = 30.0
MAX_OUTPUT_TOKENS = 300


def classify(client: rover_brain.JevClient | None, said: str, kind: str = "roam") -> tuple[str, float, str]:
    """What the person means: the intent, how sure, and who sorted it."""
    if client is not None:
        try:
            answers = client.ask({"said": said, "machine": rover_brain.kind_of(kind)}, INTENT_QUESTIONS)
            choice = answers.get("intent") if isinstance(answers.get("intent"), dict) else {}
            intent, confidence = str(choice.get("choice") or "other"), float(choice.get("confidence") or 0.0)
            who = getattr(client, "kind", "jev")
            if intent in INTENTS and confidence >= INTENT_LEAST:
                return intent, confidence, who
            return "other", confidence, who
        except Exception:
            pass                                   # fall back to plain words
    lowered = said.lower()
    for intent, pattern in PLAIN:
        if re.search(pattern, lowered):
            return intent, 1.0, "words"
    return "other", 0.0, "words"


def describe(program: dict[str, Any], machines: dict[str, Any] | None = None) -> str:
    """What the rover says of itself, from its program as the engine reports
    it: what it is doing and why, its battery, what its sensors see."""
    doing, why = str(program.get("doing") or "stopped"), str(program.get("why") or "")
    if not program.get("power"):
        first = "I am switched off."
    elif doing == "waiting":
        first = f"I am holding still: {why}." if why else "I am holding still."
    else:
        first = f"I am {doing}" + (f": {why}." if why else ".")
    battery = f"My battery is at {round(100 * float(program.get('charge_share') or 0.0))}%"
    below = float(program.get("rest_below") or 0.0)
    if below > 0:
        battery += f"; I rest below {round(100 * below)}%"
    battery += "."
    seen = [rover_brain._side(s) for s in program.get("sensors") or [] if s.get("sees")]
    water = (f"I see water ahead on my {' and '.join(seen)}." if seen
             else "My sensors see no water ahead." if program.get("sensors") else "")
    turns = int(program.get("turns") or 0)
    turned = f"I have turned away from things {turns} time{'' if turns == 1 else 's'}."
    return " ".join(s for s in (first, battery, water, turned) if s)


def _program(app: Any, body: dict[str, Any]) -> dict[str, Any]:
    session = app.live.session
    if session is None:
        raise ValueError("the room is not open")
    machines = (session.state or {}).get("machines") or {}
    want = body.get("program")
    for p in machines.get("programs") or []:
        if p.get("id") == want or p.get("name") == want:
            return p
    raise ValueError(f"there is no machine with a program called {want!r} in the room")


def _standing(body: dict[str, Any]) -> list[float] | None:
    person = body.get("person")
    at = person.get("standing_m") if isinstance(person, dict) else None
    if not isinstance(at, list) or len(at) != 3:
        return None
    try:
        point = [float(v) for v in at]
    except (TypeError, ValueError):
        return None
    return point if all(v == v and abs(v) < 1000.0 for v in point) else None


def _ask(app: Any, program: dict[str, Any], brain: rover_brain.Brain, doing: str, for_s: float, why: str,
         toward: list[float] | None = None) -> dict[str, Any]:
    brain.seq += 1
    command: dict[str, Any] = {"session": app.live.session.id, "op": "behave", "program": program["id"],
                               "sender": "talk", "seq": brain.seq, "doing": doing, "for_s": for_s, "why": why}
    if toward is not None:
        command["toward"] = toward
    said = app.live.act(command)
    return said.get("program") or program


def _use(app: Any, program: dict[str, Any], brain: rover_brain.Brain, body: dict[str, Any], tool: str,
         args: dict[str, Any], why: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """One of the machine's tools, used for the person (machine_tools): what
    it did, and the program as it now stands."""
    brain.before = program
    brain.person = body.get("person") if isinstance(body.get("person"), dict) else brain.person
    session_id = app.live.session.id
    ctx = brain.context(lambda **command: app.live.act({"session": session_id, **command}))
    did = tools.run(ctx, tools.Call(tool, args, "talk", why))
    now = _program(app, {"program": program.get("name")})
    return did, now


# ---- standing requests --------------------------------------------------------------
# An order (docs/machine-world.md, "Standing requests"): what a person asks
# for, turned into steps of the routine language, run before the machine's
# own round and reported when done. The chat's model writes the steps from
# the machine's places, substances and recipes (ORDER_SCHEMA); without a key,
# plain words cover the common shapes.
ORDER_INSTRUCTIONS = (
    "A person gives a machine in a physics sandbox a job. Write it as steps in the routine language, or say "
    "why it cannot be done. Each step is one tool: go_to {place}, dig {}, dump {place}, take {place, substance?, "
    "kg?}, process {}, back_off {for_s}, hold_still {for_s}, face {place}, go_forward {for_s}, turn_left/right "
    "{for_s}; `until` is arrived (after go_to), load_full (dig or take, with repeat true), load_empty (after "
    "dump), asked_done (after back_off, hold_still, face, go_forward, turns, process), or done. A place must be "
    "one of PLACES or 'person'; a substance one of SUBSTANCES. Digging ore means go_to the deposit's place, "
    "dig until load_full, then go_to and dump where asked. Say nothing the machine cannot do: a machine that "
    "goes nowhere can only process, hold_still.")
ORDER_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["steps", "say", "cannot"],
    "properties": {
        "steps": {"type": "array", "maxItems": 12, "items": {
            "type": "object", "additionalProperties": False, "required": ["do", "args", "until", "repeat"],
            "properties": {"do": {"type": "string"},
                           "args": {"type": "object", "additionalProperties": False,
                                    "required": ["place", "substance", "kg", "for_s"],
                                    "properties": {"place": {"type": ["string", "null"]},
                                                   "substance": {"type": ["string", "null"]},
                                                   "kg": {"type": ["number", "null"]},
                                                   "for_s": {"type": ["number", "null"]}}},
                           "until": {"type": "string"}, "repeat": {"type": "boolean"}}}},
        "say": {"type": "string", "description": "what the machine says it will do, one sentence, first person"},
        "cannot": {"type": ["string", "null"], "description": "why it cannot, or null"}}}
ORDER_PLAIN = [
    # "bring/fetch/carry/haul <substance> from <a> to <b>"
    (r"\b(?:bring|fetch|carry|haul|take)\s+(?:some\s+|the\s+)?(?P<sub>[a-z ]+?)\s+from\s+(?:the\s+)?(?P<a>[a-z ]+?)\s+to\s+(?:the\s+)?(?P<b>[a-z ]+?)\s*$",
     lambda m, ctx: [{"do": "go_to", "args": {"place": m["a"]}, "until": "arrived"},
                     {"do": "take", "args": {"place": m["a"], "substance": m["sub"]}, "until": "load_full", "repeat": True},
                     {"do": "go_to", "args": {"place": m["b"]}, "until": "arrived"},
                     {"do": "dump", "args": {"place": m["b"]}, "until": "load_empty"}]),
    # "dig at <a> and dump/bring it to <b>"
    (r"\bdig\s+(?:at\s+)?(?:the\s+)?(?P<a>[a-z ]+?)\s+(?:and\s+)?(?:dump|bring|take)\s+(?:it\s+)?(?:to\s+|at\s+)?(?:the\s+)?(?P<b>[a-z ]+?)\s*$",
     lambda m, ctx: [{"do": "go_to", "args": {"place": m["a"]}, "until": "arrived"},
                     {"do": "dig", "args": {}, "until": "load_full", "repeat": True},
                     {"do": "back_off", "args": {"for_s": 1.5}, "until": "asked_done"},
                     {"do": "go_to", "args": {"place": m["b"]}, "until": "arrived"},
                     {"do": "dump", "args": {"place": m["b"]}, "until": "load_empty"}]),
    # "go to <a> (and wait)"
    (r"\bgo\s+to\s+(?:the\s+)?(?P<a>[a-z ]+?)(?:\s+and\s+wait)?\s*$",
     lambda m, ctx: [{"do": "go_to", "args": {"place": m["a"]}, "until": "arrived"}]),
    # "make <n> batches"
    (r"\bmake\s+(?P<n>\d+)\s+batch(?:es)?\b",
     lambda m, ctx: [{"do": "process", "args": {}, "until": "asked_done"}] * max(1, min(20, int(m["n"])))),
]


def _places_of(brain: rover_brain.Brain) -> dict[str, Any]:
    return dict(brain.routine.places) if brain.routine is not None else {}


def plain_order(said: str, places: dict[str, Any], substances: list[str]) -> list[dict[str, Any]] | None:
    """An order from plain words, for when no model can write one: a few
    shapes, over the places and substances the machine knows."""
    lowered = " ".join(said.lower().replace("?", "").replace(".", "").split())
    known = {p.lower(): p for p in places} | {"person": "person", "me": "person"}
    subs = {s.lower(): s for s in substances}
    for pattern, build in ORDER_PLAIN:
        m = re.search(pattern, lowered)
        if not m:
            continue
        steps = build(m, None)
        ok = True
        for step in steps:
            args = step.get("args") or {}
            if args.get("place") is not None:
                place = args["place"].strip()
                if place not in known:
                    ok = False
                    break
                args["place"] = known[place]
            if args.get("substance") is not None:
                sub = args["substance"].strip()
                if sub in ("goods", "it", "everything", "anything"):
                    args.pop("substance")
                elif sub not in subs:
                    ok = False
                    break
                else:
                    args["substance"] = subs[sub]
        if ok:
            return steps
    return None


def model_order(app: Any, said: str, program: dict[str, Any], places: dict[str, Any],
                substances: list[str], recipes: list[str]) -> dict[str, Any] | None:
    """The chat's model writing an order as steps, or saying why it cannot;
    None without a key or on a fault."""
    api_key, model = getattr(app, "api_key", ""), getattr(app, "model", "")
    if not api_key:
        return None
    payload = {"model": model, "store": False, "max_output_tokens": 600, "instructions": ORDER_INSTRUCTIONS,
               "input": json.dumps({"machine": rover_brain.kind_of(str(program.get("kind") or "roam")),
                                    "PLACES": sorted(places), "SUBSTANCES": substances, "RECIPES": recipes,
                                    "carries_kg": (program.get("routine") or {}).get("hopper_kg"),
                                    "the person said": said}, allow_nan=False),
               "text": {"format": {"type": "json_schema", "name": "order", "strict": True, "schema": ORDER_SCHEMA}}}
    if model.startswith("gpt-5") or model.startswith("o"):
        payload["reasoning"] = {"effort": "low"}
    req = request.Request("https://api.openai.com/v1/responses", data=json.dumps(payload).encode(), method="POST",
                          headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"})
    try:
        with request.urlopen(req, timeout=TALK_TIMEOUT_S) as response:
            answer = json.loads(response.read(1024 * 1024))
        text = "".join(part.get("text", "") for item in answer.get("output") or [] if item.get("type") == "message"
                       for part in item.get("content") or [] if part.get("type") == "output_text")
        out = json.loads(text)
    except (error.URLError, OSError, ValueError, KeyError):
        return None
    steps = []
    for step in out.get("steps") or []:
        args = {k: v for k, v in (step.get("args") or {}).items() if v is not None}
        made = {"do": step.get("do"), "args": args, "until": step.get("until") or "done"}
        if step.get("repeat"):
            made["repeat"] = True
        steps.append(made)
    return {"steps": steps, "say": str(out.get("say") or ""), "cannot": out.get("cannot")}


def give_order(app: Any, brain: rover_brain.Brain, program: dict[str, Any], said: str) -> str:
    """An order given: written as steps (by the model, or from plain words),
    checked against the routine language and the places it knows, queued on
    the routine, and answered."""
    import machine_routine
    if program.get("kind") == "still" and not re.search(r"(make|batch|batches|wait|hold)", said.lower()):
        return "I go nowhere: I can only make batches or wait."
    places = _places_of(brain)
    substances = brain.goods.substances() if brain.goods is not None else []
    recipes = [r.get("name") for r in brain.goods.recipes] if brain.goods is not None else []
    written = model_order(app, said, program, places, substances, recipes)
    if written is None:
        steps = plain_order(said, places, substances)
        if steps is None:
            return ("I could not make a job of that. I can take: bring <substance> from <place> to <place>, dig "
                    "at <place> and dump it at <place>, go to <place>, make <n> batches. I know the places "
                    + (", ".join(sorted(places)) or "none") + ".")
        say = ""
    elif written.get("cannot") or not written.get("steps"):
        return f"I cannot: {written.get('cannot') or 'there is nothing in that for me to do'}."
    else:
        steps, say = written["steps"], written["say"]
    try:
        steps = machine_routine.checked_steps(steps)
        for step in steps:
            place = step["args"].get("place")
            if place and place != "person" and place not in places:
                raise ValueError(f"I know no place called {place}")
    except ValueError as wrong:
        return f"I cannot: {str(wrong)[:160]}."
    if program.get("kind") == "still" and any(s["do"] not in ("process", "hold_still") for s in steps):
        return "I go nowhere: I can only make batches or wait."
    given = brain.routine.order(said, steps)
    brain.orders_given[given["order"]] = said
    brain.changed = True
    plan = "; ".join(tools.described(s["do"], s["args"]) for s in steps)
    behind = f" after the {given['queued_behind']} I have already" if given["queued_behind"] else ""
    return (say or "Will do") + f": {plan}{behind}. Then back to my rounds."


def _model_answer(app: Any, said: str, program: dict[str, Any]) -> str:
    """The chat's model, in the rover's voice, from its state alone."""
    api_key, model = getattr(app, "api_key", ""), getattr(app, "model", "")
    if not api_key:
        return ("I can take: stop, go on, come here, turn round, back off, or ask what I am doing and why. "
                "Nobody has given me words for anything else.")
    instructions = (
        f"You are {rover_brain.kind_of(str(program.get('kind') or 'roam'))}, in a physics sandbox. A person is "
        "talking to you. Answer in one or two short sentences, in the first person, from the STATE given and "
        "nothing else: never invent an event, a place or a number that is not in it. You cannot change "
        "anything by answering. If asked to do something you cannot do, say what you can take: stop, go on, "
        "come here, turn round, back off, dig, dump, take, make, or say what you are doing and why.")
    payload = {"model": model, "store": False, "max_output_tokens": MAX_OUTPUT_TOKENS,
               "reasoning": {"effort": "low"}, "instructions": instructions,
               "input": f"STATE: {json.dumps(program, allow_nan=False)}\n\nThe person said: {said}"}
    req = request.Request("https://api.openai.com/v1/responses", data=json.dumps(payload).encode(), method="POST",
                          headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"})
    try:
        with request.urlopen(req, timeout=TALK_TIMEOUT_S) as response:
            answer = json.loads(response.read(1024 * 1024))
    except error.HTTPError as exc:
        return f"(the chat's model answered HTTP {exc.code}, so I have nothing to say to that)"
    except (error.URLError, OSError, ValueError):
        return "(the chat's model could not be reached, so I have nothing to say to that)"
    words = []
    for item in answer.get("output") or []:
        if item.get("type") != "message":
            continue
        for part in item.get("content") or []:
            if part.get("type") == "output_text" and part.get("text"):
                words.append(str(part["text"]))
    return " ".join(words).strip() or "(the chat's model had nothing to say)"


def talk(app: Any, body: Any) -> dict[str, Any]:
    """POST /api/world/rover/talk: {program, open | said | close, person}.

    open: the rover stops and turns to face the person, and says what it was
    doing. said: what the person typed, sorted and done, and the rover's
    answer. close: the rover goes on. Every answer carries the program as it
    now stands and the conversation so far."""
    if not isinstance(body, dict):
        raise ValueError("expected {program, open | said | close, person}")
    program = _program(app, body)
    brain = app.brains.of(str(program["name"]))
    standing = _standing(body)
    name = str(program.get("name") or "the machine")
    reply: str

    def say(who: str, words: str, **more: Any) -> None:
        brain.talk.append({"who": who, "said": words, "at": time.time(), **more})
        brain.changed = True

    if body.get("open"):
        if not program.get("power"):
            reply = f"{describe(program)} Switch me on and I will talk."
        elif standing is not None and program.get("kind") != "still":
            program = _ask(app, program, brain, "facing", 0.0, "the person came to talk to it", standing)
            reply = describe(program)
        else:
            program = _ask(app, program, brain, "waiting", 0.0, "the person came to talk to it")
            reply = describe(program)
        say(name, reply, opened=True)
    elif body.get("close"):
        asked = program.get("asked") if isinstance(program.get("asked"), dict) else None
        if asked and asked.get("by") == "talk":
            did, program = _use(app, program, brain, body, "carry_on", {}, "")
        reply = "Going on." if program.get("power") else "Still off."
        say(name, reply, closed=True)
    else:
        said = str(body.get("said") or "").strip()[:500]
        if not said:
            raise ValueError("say something: {said: ...}")
        say("you", said)
        intent, confidence, sorted_by = classify(brain.decider(), said, str(program.get("kind") or "roam"))
        if not program.get("power") and intent not in ("status", "why", "other"):
            reply = "I am switched off, so I cannot. Switch me on first."
        elif intent == "stop":
            did, program = _use(app, program, brain, body, "hold_still", {"for_s": 0.0}, "the person told it to stop")
            reply = "Stopping. I will hold here until you say."
        elif intent == "go_on":
            did, program = _use(app, program, brain, body, "carry_on", {}, "")
            reply = "Going on with my rounds."
        elif intent in ("come_here", "turn_around", "back_off") and program.get("kind") == "still":
            reply = "I go nowhere: I stand where I was built."
        elif intent == "come_here":
            if standing is None:
                reply = "I do not know where you are standing."
            else:
                did, program = _use(app, program, brain, body, "go_to", {"place": "person", "for_s": 30.0},
                                    "the person asked it to come")
                reply = "Coming to you. I will stop a metre off."
        elif intent == "turn_around":
            did, program = _use(app, program, brain, body, "turn_left", {"for_s": 5.0},
                                "the person asked it to turn round")
            reply = "Turning round."
        elif intent == "back_off":
            did, program = _use(app, program, brain, body, "back_off", {"for_s": 2.5},
                                "the person asked it to back off")
            reply = "Backing off."
        elif intent in ("dig", "dump", "take", "make"):
            tool = "process" if intent == "make" else intent
            did, program = _use(app, program, brain, body, tool, {}, f"the person asked it to {intent}")
            reply = did.get("did", "").capitalize() + "."
        elif intent == "order":
            reply = give_order(app, brain, program, said)
        elif intent == "cancel":
            gone = brain.routine.cancel_orders()
            brain.orders_given.clear()
            brain.changed = True
            reply = (f"Dropped {gone} order{'' if gone == 1 else 's'}. Back to my rounds." if gone
                     else "I had no orders to drop.")
        elif intent in ("status", "why"):
            reply = describe(program)
            orders = brain.routine.orders()
            if orders:
                reply += f" I have {len(orders)} order{'' if len(orders) == 1 else 's'} to do" + (
                    f": {brain.orders_given.get(orders[0]['order'], '')}." if brain.orders_given.get(orders[0]["order"]) else ".")
            last = next((d for d in reversed(brain.decisions) if d.get("said")), None)
            if intent == "why" and last:
                reply += f" The last thing decided for me: {last['said']}."
        else:
            # Anything else: a job it can make of, else the model's answer.
            written = give_order(app, brain, program, said) if not getattr(app, "api_key", "") else None
            if written is not None and not written.startswith("I could not make a job"):
                reply = written
            else:
                reply = _model_answer(app, said, program)
        say(name, reply, intent=intent, confidence=round(confidence, 2), sorted_by=sorted_by)
    return {"program": program, "reply": reply, "talk": list(brain.talk)}
