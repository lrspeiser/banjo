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
    "dig": "Dig here, take a scoop, dig for something, get some sand or soil.",
    "dump": "Dump it, empty your hopper, drop the load, put it down here.",
    "status": "What are you doing, where are you, how is your battery, what do your sensors see, report.",
    "why": "Why did you stop, why did you turn, why are you doing that, what happened, explain.",
    "other": "Anything else: a question about the world, chit-chat, an instruction it cannot take.",
}
INTENT_QUESTIONS = {
    "intent": {"type": "choice",
               "instructions": "The person is talking to a small wheeled rover in a physics sandbox. "
                               "`said` is what they typed. What do they mean it to do?",
               "criteria": INTENTS},
}
INTENT_LEAST = 0.5
# Plain words, for when Jev is not there to ask. First match wins: a question
# ("why did you stop?") before a command.
PLAIN = [
    ("why", r"\b(why|what happened|explain)\b"),
    ("stop", r"\b(stop|halt|wait|stay|hold|freeze|don'?t move)\b"),
    ("come_here", r"\b(come|approach|closer|over here|to me)\b"),
    ("turn_around", r"\b(turn (a)?round|turn around|about face|other way|turn back)\b"),
    ("back_off", r"\b(back (off|up|away)|reverse|get away)\b"),
    ("dump", r"\b(dump|empty|drop (it|the load)|unload)\b"),
    ("dig", r"\b(dig|scoop|shovel)\b"),
    ("go_on", r"\b(go on|carry on|continue|resume|go roam|back to work|get going|off you go|bye|goodbye)\b"),
    ("status", r"\b(what are you|where are you|how is|how'?s|battery|sensors?|report|status|doing)\b"),
]
TALK_TIMEOUT_S = 30.0
MAX_OUTPUT_TOKENS = 300


def classify(client: rover_brain.JevClient | None, said: str) -> tuple[str, float, str]:
    """What the person means: the intent, how sure, and who sorted it."""
    if client is not None:
        try:
            answers = client.ask({"said": said}, INTENT_QUESTIONS)
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


def _model_answer(app: Any, said: str, program: dict[str, Any]) -> str:
    """The chat's model, in the rover's voice, from its state alone."""
    api_key, model = getattr(app, "api_key", ""), getattr(app, "model", "")
    if not api_key:
        return ("I can take: stop, go on, come here, turn round, back off, or ask what I am doing and why. "
                "Nobody has given me words for anything else.")
    instructions = (
        "You are a small battery rover with two driven wheels and a caster, roaming a lake's shore in a "
        "physics sandbox. A person is talking to you. Answer in one or two short sentences, in the first "
        "person, from the STATE given and nothing else: never invent an event, a place or a number that is "
        "not in it. You cannot change anything by answering. If asked to do something you cannot do, say "
        "what you can take: stop, go on, come here, turn round, back off, or say what you are doing and why.")
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
        elif standing is not None:
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
        intent, confidence, sorted_by = classify(brain.decider(), said)
        if not program.get("power") and intent not in ("status", "why", "other"):
            reply = "I am switched off, so I cannot. Switch me on first."
        elif intent == "stop":
            did, program = _use(app, program, brain, body, "hold_still", {"for_s": 0.0}, "the person told it to stop")
            reply = "Stopping. I will hold here until you say."
        elif intent == "go_on":
            did, program = _use(app, program, brain, body, "carry_on", {}, "")
            reply = "Going on with my rounds."
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
        elif intent in ("dig", "dump"):
            did, program = _use(app, program, brain, body, intent, {}, f"the person asked it to {intent}")
            reply = did.get("did", "").capitalize() + "."
        elif intent in ("status", "why"):
            reply = describe(program)
            last = next((d for d in reversed(brain.decisions) if d.get("said")), None)
            if intent == "why" and last:
                reply += f" The last thing decided for me: {last['said']}."
        else:
            reply = _model_answer(app, said, program)
        say(name, reply, intent=intent, confidence=round(confidence, 2), sorted_by=sorted_by)
    return {"program": program, "reply": reply, "talk": list(brain.talk)}
