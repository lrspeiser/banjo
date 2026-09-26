"""What thinks for a machine on what it meets (docs/machine-world.md, "What
the rover decides by itself, and who it asks").

A rover roams by its reflexes: the engine's program (LiveProgram, "roam") reads
its sensors and its slope before every step and works its wheels. Those
reflexes are fast and never wrong about what they read, and they know nothing.
This layer asks Jev -- TypeSafe AI's decision model, which answers typed
questions about a state with calibrated probabilities in a fraction of a
second and cannot write a word -- what the rover should do for the next couple
of seconds whenever something happens to it: water seen ahead, its wheels
stalled, something struck it, its battery getting low. Jev's pick goes to the
program as an ask (LiveWorld::behave) that it does instead of deciding for
itself for a short while, and then its reflexes have it back. A pick Jev is
not confident of is left to the reflexes. Nothing here runs on the step: the
question is asked on a thread, and the answer is applied before the next step
the page takes, so the page's frame rate never waits on the network.

Who decides is a switch on the panel: the rover's reflexes alone; Jev; or the
chat's OpenAI model asked the same typed questions and made to answer in the
same shape (OpenAIDecider), which needs no heavy thinking for a pick among
five things and is set to its lightest reasoning. The keys are in the
environment or the local .env (the same files the room's chat reads):
TYPESAFE_API_KEY for Jev, with JEV_API_URL naming another host that speaks
the same API (a reseller, a proxy, a scripted stand-in for a test);
OPENAI_API_KEY for the model, with OPENAI_DECIDER_MODEL (else OPENAI_MODEL)
and OPENAI_DECIDER_EFFORT (minimal) choosing which and how hard it thinks.
BANJO_DECIDER (jev, openai or reflex) says which decides when a room opens;
without it, Jev when it has a key, else the model, else the reflexes.
"""
from __future__ import annotations

from collections import deque
import json
import logging
import os
from pathlib import Path
import threading
import time
from typing import Any, Callable
from urllib import error, request

import machine_routine as routines
import machine_senses as senses
import machine_tools as tools

_log = logging.getLogger("banjo")

JEV_URL = "https://api.typesafe.ai/v1/systemone"
JEV_MODEL = "jev-latest"
TIMEOUT_S = 8.0
# A pick Jev gives less confidence than this is left to the rover's reflexes.
CONFIDENCE_LEAST = 0.55
# The same thing happening again within this much of the world's time is not
# asked about again: a sensor that sees water for two seconds is one event.
AGAIN_S = 3.0
DECISIONS_KEPT = 12

# What is asked when something happens, whoever answers: which of the
# machine's TOOLS (machine_tools) it should use next -- a choice among their
# names, with their descriptions as the criteria -- and, in the same call,
# whether it is stuck and how urgent its battery is. The state it reads is
# its SENSES (machine_senses). Nothing here is a rover's: KINDS says only what
# each kind of program's machine is, in words, for the question's preamble.
KINDS: dict[str, str] = {
    "roam": "a small battery machine with a driven wheel on each side and a caster in front, working on its "
            "own by a lake",
    "hover": "a small battery machine that flies on four rotors, holding a height above the ground and moving "
             "by leaning, working on its own by a lake; it cannot roll, and off its rotors it falls",
    "still": "a battery machine that goes nowhere -- a smelter, a mill -- working what is put on its intake "
             "stockpile into goods on its output one by a recipe; it can only wait or work",
}
ALSO_QUESTIONS: dict[str, Any] = {
    "stuck": {
        "type": "noul",
        "instructions": "The machine is stuck: its wheels make no progress, or it keeps turning away from the "
                        "same thing over and over without getting anywhere.",
        "criteria": {"true": "It is making no progress, or the same trouble keeps coming back.",
                     "false": "It is getting about, and this is a new situation."},
    },
    "battery": {
        "type": "score",
        "instructions": "How urgently the machine needs to rest and charge, from its battery's share of full "
                        "and whether it is charging.",
        # A score's criteria are its levels in order, low to high (2 to 10); the
        # answer's legend maps each level's number back to its words.
        "criteria": ["fine: plenty of charge, no need to think about it",
                     "low: getting low, it should not go far from where it can charge",
                     "urgent: nearly flat, it should rest now"],
    },
}


def kind_of(kind: str) -> str:
    return KINDS.get(kind) or KINDS["roam"]


def questions_for(kind: str, places: dict[str, Any] | None = None,
                  substances: list[str] | None = None) -> dict[str, Any]:
    """The questions asked of a machine of this kind, in one call: which tool
    next, from the tools a decider may pick; each argument a decider can fill,
    as a question of its own (machine_tools.argument_questions); and the
    rest. Everything is asked at once and only the picked tool's arguments
    are read: one call, however the decision branches."""
    criteria = {t["name"]: t["description"] for t in tools.catalogue(for_deciders=True)}
    return {
        "next": {
            "type": "choice",
            "instructions": (f"The machine is {kind_of(kind)}. `event` is what just happened to it; `senses` is "
                             "everything it can sense now, with directions in degrees from its front (positive "
                             "to its left) and distances in metres; `routine` is what it was doing on its own. "
                             "Pick the one tool it should use next, for the next few seconds; carry_on leaves "
                             "it to its routine and its reflexes."),
            "criteria": criteria,
        },
        **tools.argument_questions(places, substances),
        **ALSO_QUESTIONS,
    }


# Kept for the tests and the docs: the tools a decider may pick, by name.
PICKS = {t["name"]: t["description"] for t in tools.catalogue(for_deciders=True)}
QUESTIONS = questions_for("roam")


def environment_setting(name: str, candidates: list[Path] | None = None) -> str:
    """A setting from the environment, or the first of the local .env files
    that names it. Never logged."""
    if os.environ.get(name):
        return os.environ[name]
    for path in candidates or []:
        try:
            if not path.is_file() or path.stat().st_size > 65536:
                continue
            for line in path.read_text(encoding="utf-8-sig").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = (s.strip() for s in line.split("=", 1))
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                    value = value[1:-1]
                if key == name and value:
                    return value
        except OSError:
            continue
    return ""


def environment_key(candidates: list[Path] | None = None) -> str:
    return environment_setting("TYPESAFE_API_KEY", candidates)


class JevClient:
    """One call to Jev: a state and the questions, the typed answers back.
    Raises ValueError with a reason that never carries the key or the body."""

    kind = "jev"
    label = "Jev"

    def __init__(self, api_key: str, url: str = JEV_URL, model: str = JEV_MODEL, timeout_s: float = TIMEOUT_S):
        self.api_key, self.url, self.model, self.timeout_s = api_key, url, model, timeout_s

    def ask(self, state: Any, questions: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps({"model": self.model, "state": state, "questions": questions},
                          allow_nan=False).encode()
        # A user agent: a gateway behind Cloudflare (thejevai.com) answers
        # Python's default one 403 before the request reaches anything.
        req = request.Request(self.url, data=body, method="POST",
                              headers={"Authorization": "Bearer " + self.api_key,
                                       "Content-Type": "application/json", "Accept": "application/json",
                                       "User-Agent": "banjo-playground/1.0"})
        try:
            with request.urlopen(req, timeout=self.timeout_s) as response:
                raw = response.read(1024 * 1024 + 1)
        except error.HTTPError as exc:
            # 429 and 529 are "back off"; anything else is a fault. The body
            # can echo the request, so it is not read into a message.
            raise ValueError(f"Jev answered HTTP {exc.code}") from None
        except (error.URLError, OSError, TimeoutError) as exc:
            raise ValueError(f"Jev could not be reached: {type(exc).__name__}") from None
        if len(raw) > 1024 * 1024:
            raise ValueError("Jev's answer exceeded the size budget")
        try:
            answer = json.loads(raw)
        except ValueError:
            raise ValueError("Jev's answer was not JSON") from None
        answers = answer.get("answers") if isinstance(answer, dict) else None
        if not isinstance(answers, dict):
            raise ValueError("Jev's answer had no answers")
        return answers


def client_from(candidates: list[Path] | None = None) -> JevClient | None:
    key = environment_key(candidates)
    url = environment_setting("JEV_API_URL", candidates) or JEV_URL
    return JevClient(key, url=url) if key else None


OPENAI_URL = "https://api.openai.com/v1/responses"
OPENAI_DECIDER_EFFORT = "minimal"
OPENAI_TIMEOUT_S = 20.0
OPENAI_INSTRUCTIONS = (
    "You are a decision function, not a writer. You are given STATE and QUESTIONS. Answer every question "
    "from the state alone, as calibrated probabilities: for a choice, a probability for each option that sum "
    "to 1; for a score, a probability for each level, numbered from 0 (the first, lowest) upward, that sum "
    "to 1; for a noul, the probability that the statement is true. Each question's instructions and "
    "criteria say what its options or levels mean. Output only the JSON asked for.")


def answer_schema(questions: dict[str, Any]) -> dict[str, Any]:
    """The JSON the model must produce for these questions: strict, so it can
    answer nothing else."""
    def number() -> dict[str, Any]:
        return {"type": "number"}

    def table(keys: list[str]) -> dict[str, Any]:
        return {"type": "object", "properties": {k: number() for k in keys}, "required": list(keys),
                "additionalProperties": False}

    properties: dict[str, Any] = {}
    for name, question in questions.items():
        kind = question.get("type")
        if kind == "choice":
            options = [str(o) for o in (question.get("criteria") or {})]
            properties[name] = {"type": "object",
                                "properties": {"choice": {"type": "string", "enum": options},
                                               "probabilities": table(options)},
                                "required": ["choice", "probabilities"], "additionalProperties": False}
        elif kind == "score":
            levels = [str(i) for i in range(len(question.get("criteria") or []))]
            properties[name] = {"type": "object", "properties": {"probabilities": table(levels)},
                                "required": ["probabilities"], "additionalProperties": False}
        elif kind == "noul":
            properties[name] = {"type": "object", "properties": {"noul": number()}, "required": ["noul"],
                                "additionalProperties": False}
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def answers_from(raw: dict[str, Any], questions: dict[str, Any]) -> dict[str, Any]:
    """The model's JSON in the shape Jev answers in: a choice with its
    probabilities, normalised, and a confidence that is the top probability; a
    score that is the probability-weighted level, with its legend; a noul."""
    answers: dict[str, Any] = {}
    for name, question in questions.items():
        got = raw.get(name) if isinstance(raw.get(name), dict) else {}
        kind = question.get("type")
        if kind == "choice":
            options = [str(o) for o in (question.get("criteria") or {})]
            probabilities = {o: max(0.0, float(got.get("probabilities", {}).get(o) or 0.0)) for o in options}
            total = sum(probabilities.values()) or 1.0
            probabilities = {o: round(p / total, 4) for o, p in probabilities.items()}
            choice = max(probabilities, key=probabilities.get) if probabilities else str(got.get("choice") or "")
            answers[name] = {"type": "choice", "choice": choice, "probabilities": probabilities,
                             "confidence": probabilities.get(choice, 0.0)}
        elif kind == "score":
            levels = [str(level) for level in (question.get("criteria") or [])]
            probabilities = {str(i): max(0.0, float(got.get("probabilities", {}).get(str(i)) or 0.0))
                             for i in range(len(levels))}
            total = sum(probabilities.values()) or 1.0
            probabilities = {k: round(p / total, 4) for k, p in probabilities.items()}
            answers[name] = {"type": "score", "score": round(sum(int(k) * p for k, p in probabilities.items()), 4),
                             "legend": {str(i): level for i, level in enumerate(levels)},
                             "probabilities": probabilities,
                             "confidence": max(probabilities.values()) if probabilities else 0.0}
        elif kind == "noul":
            answers[name] = {"type": "noul", "noul": min(1.0, max(0.0, float(got.get("noul") or 0.0)))}
    return answers


class OpenAIDecider:
    """The chat's model asked the same typed questions, made to answer in the
    same shape (Responses API, a strict JSON schema, its lightest reasoning).
    Raises ValueError with a reason that never carries the key or the body."""

    kind = "openai"

    def __init__(self, api_key: str, model: str, effort: str = OPENAI_DECIDER_EFFORT, url: str = OPENAI_URL,
                 timeout_s: float = OPENAI_TIMEOUT_S):
        self.api_key, self.model, self.effort, self.url, self.timeout_s = api_key, model, effort, url, timeout_s
        self.label = f"OpenAI ({model})"

    def payload(self, state: Any, questions: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {
            "model": self.model, "store": False, "max_output_tokens": 800,
            "instructions": OPENAI_INSTRUCTIONS,
            "input": json.dumps({"STATE": state, "QUESTIONS": questions}, allow_nan=False),
            "text": {"format": {"type": "json_schema", "name": "answers", "strict": True,
                                "schema": answer_schema(questions)}}}
        # Reasoning effort is a gpt-5 / o-series setting; another model would
        # refuse the field.
        if self.effort and (self.model.startswith("gpt-5") or self.model.startswith("o")):
            out["reasoning"] = {"effort": self.effort}
        return out

    def ask(self, state: Any, questions: dict[str, Any]) -> dict[str, Any]:
        req = request.Request(self.url, data=json.dumps(self.payload(state, questions), allow_nan=False).encode(),
                              method="POST", headers={"Authorization": "Bearer " + self.api_key,
                                                      "Content-Type": "application/json"})
        try:
            with request.urlopen(req, timeout=self.timeout_s) as response:
                raw = response.read(4 * 1024 * 1024 + 1)
        except error.HTTPError as exc:
            raise ValueError(f"the model answered HTTP {exc.code}") from None
        except (error.URLError, OSError, TimeoutError) as exc:
            raise ValueError(f"the model could not be reached: {type(exc).__name__}") from None
        try:
            answer = json.loads(raw)
        except ValueError:
            raise ValueError("the model's answer was not JSON") from None
        words = []
        for item in answer.get("output") or []:
            if item.get("type") != "message":
                continue
            for part in item.get("content") or []:
                if part.get("type") == "output_text" and part.get("text"):
                    words.append(str(part["text"]))
        if not words:
            status = str(answer.get("status") or "")
            details = answer.get("incomplete_details") if isinstance(answer.get("incomplete_details"), dict) else {}
            raise ValueError(f"the model said nothing ({status} {details.get('reason') or ''})".strip())
        try:
            parsed = json.loads("".join(words))
        except ValueError:
            raise ValueError("the model's answer was not the JSON asked for") from None
        return answers_from(parsed if isinstance(parsed, dict) else {}, questions)


MODES = ("reflex", "jev", "openai")


def deciders_from(candidates: list[Path] | None = None) -> tuple[dict[str, Any], str]:
    """Who can decide, by mode, from what is configured; and which decides
    when a room opens: BANJO_DECIDER, else Jev, else the model, else the
    reflexes."""
    deciders: dict[str, Any] = {}
    jev = client_from(candidates)
    if jev is not None:
        deciders["jev"] = jev
    key = environment_setting("OPENAI_API_KEY", candidates)
    if key:
        model = (environment_setting("OPENAI_DECIDER_MODEL", candidates)
                 or environment_setting("OPENAI_MODEL", candidates) or "gpt-5-mini")
        effort = environment_setting("OPENAI_DECIDER_EFFORT", candidates) or OPENAI_DECIDER_EFFORT
        deciders["openai"] = OpenAIDecider(key, model, effort)
    preferred = environment_setting("BANJO_DECIDER", candidates)
    if preferred in MODES and (preferred == "reflex" or preferred in deciders):
        default = preferred
    else:
        default = next((m for m in ("jev", "openai") if m in deciders), "reflex")
    return deciders, default


# ---- what the rover is, in words Jev reads ---------------------------------

def state_of(ctx: senses.Context, event: str, recent: list[dict[str, Any]]) -> dict[str, Any]:
    """The machine as a decider is told it: what happened, everything it
    senses, its routine, and the last few decisions. Curated by the senses,
    not the whole step: a decider reads a bounded state and is paid by the
    token."""
    return {
        "event": event,
        "senses": senses.read(ctx),
        "routine": ctx.routine.summary() if ctx.routine is not None else None,
        "recent_decisions": [{"event": d.get("event"), "tool": d.get("pick"), "confidence": d.get("confidence"),
                              "did": d.get("applied")} for d in recent[-4:]],
    }


situations = senses.situations
_side = senses._side


def decide(answers: dict[str, Any], event: str, kind: str = "roam", who: str = "Jev",
           places: dict[str, Any] | None = None, substances: list[str] | None = None) -> dict[str, Any]:
    """The answers as a decision: which tool to call, or none, and what the
    panel says of it. A choice under CONFIDENCE_LEAST is left to the reflexes
    and the routine; a score or a noul the answer lacks is simply not said."""
    choice = answers.get("next") if isinstance(answers.get("next"), dict) else {}
    pick = str(choice.get("choice") or "")
    confidence = float(choice.get("confidence") or 0.0)
    stuck = answers.get("stuck") if isinstance(answers.get("stuck"), dict) else {}
    battery = answers.get("battery") if isinstance(answers.get("battery"), dict) else {}
    out: dict[str, Any] = {"event": event, "pick": pick, "confidence": round(confidence, 2),
                           "stuck": round(float(stuck.get("noul") or 0.0), 2) if stuck else None,
                           "battery": (battery.get("legend") or {}).get(str(round(float(battery.get("score") or 0))),
                                                                        "").split(":")[0] or None
                           if battery else None,
                           "probabilities": choice.get("probabilities")}
    tool = tools.TOOLS.get(pick)
    if tool is None or not tool.for_deciders:
        out["call"] = None
        out["said"] = f"{who} gave no tool it has ({pick or 'nothing'}); its reflexes have it"
        return out
    args = tools.arguments_for(pick, answers, places, substances)
    words = tools.described(pick, args)
    out["args"] = args
    if confidence < CONFIDENCE_LEAST:
        out["call"] = None
        out["said"] = f"{who} would {words} ({round(100 * confidence)}% sure): too unsure, so its reflexes have it"
        return out
    out["call"] = {"tool": pick, "args": args,
                   "why": f"{who} said {words} ({round(100 * confidence)}% sure) when {event}"[:200]}
    out["said"] = f"{who}: {words} ({round(100 * confidence)}% sure) when {event}"
    return out


# ---- one brain per program ---------------------------------------------------

class Brain:
    """What thinks for one program, by its name (a program's id changes when
    the room is opened again; its name does not): its routine, the deciders
    it can ask, and what it decided lately."""

    def __init__(self, name: str, deciders: Any, mode: str, declared: dict[str, Any] | None = None):
        self.name = name
        # A single Jev client, or None, is taken as the deciders it amounts to.
        if deciders is None:
            deciders = {}
        elif not isinstance(deciders, dict):
            deciders = {getattr(deciders, "kind", "jev"): deciders}
        self.deciders: dict[str, Any] = deciders
        self.mode = mode if mode == "reflex" or mode in deciders else "reflex"
        self.routine = routines.Routine(name, declared)
        self.goods: Any = None                     # the room's goods ledger (machine_goods.Goods), shared
        self.before: dict[str, Any] | None = None
        self.machines: dict[str, Any] | None = None
        self.bodies: list[dict[str, Any]] | None = None
        self.impacts: list[dict[str, Any]] = []
        self.t = 0.0
        self.person: dict[str, Any] | None = None
        self.asked_at: dict[str, float] = {}       # event text -> world time it was asked at
        self.decisions: deque[dict[str, Any]] = deque(maxlen=DECISIONS_KEPT)
        self.talk: deque[dict[str, Any]] = deque(maxlen=24)
        self.thinking: str | None = None           # the event being asked about
        self._answer: dict[str, Any] | None = None
        self._lock = threading.Lock()
        self.seq = 0
        self.changed = True                        # the page should hear of it

    @property
    def client(self) -> Any:
        """Who decides in the mode it is in; None for the reflexes."""
        return self.deciders.get(self.mode)

    def decider(self) -> Any:
        """Who sorts what a person says: the mode's, else whoever is there."""
        return self.client or next(iter(self.deciders.values()), None)

    @property
    def who(self) -> str:
        return getattr(self.client, "label", "Jev") if self.client is not None else "its reflexes"

    def context(self, ask: Callable[..., dict[str, Any]] | None) -> senses.Context:
        """Its senses' view of the world as the last step left it."""
        return senses.Context(program=self.before or {}, machines=self.machines, bodies=self.bodies, ask=ask,
                              routine=self.routine, person=self.person, impacts=self.impacts, t=self.t,
                              goods=self.goods)

    def observe(self, program: dict[str, Any], machines: dict[str, Any] | None, impacts: list[dict[str, Any]],
                t: float, ask: Callable[[Any, dict[str, Any]], dict[str, Any]] | None = None,
                bodies: list[dict[str, Any]] | None = None,
                engine: Callable[..., dict[str, Any]] | None = None) -> None:
        events = situations(self.before, program, machines, impacts)
        self.before, self.machines, self.impacts, self.t = program, machines, impacts, t
        if bodies is not None:
            self.bodies = bodies
        if self.mode == "reflex" or self.client is None or not events:
            return
        asked_by = (program.get("asked") or {}).get("by") if isinstance(program.get("asked"), dict) else None
        if asked_by == "talk":
            return                                 # the person has it: nothing is asked while they talk
        with self._lock:
            if self.thinking is not None:
                return                             # one question at a time
            fresh = [e for e in events if t - self.asked_at.get(e, -1e9) >= AGAIN_S]
            if not fresh:
                return
            event = "; ".join(fresh)
            for e in fresh:
                self.asked_at[e] = t
            self.thinking = event
        # The senses are read now, on this thread, with the engine at hand:
        # the question goes on another, with the state in hand.
        state = state_of(self.context(engine), event, [d for d in self.decisions if d.get("said")])
        kind = str(program.get("kind") or "roam")
        places = dict(self.routine.places) if self.routine is not None else {}
        thread = threading.Thread(target=self._think,
                                  args=(state, event, kind, ask or self.client.ask, self.who, places),
                                  daemon=True, name=f"banjo-brain-{self.name}")
        thread.start()

    def _think(self, state: dict[str, Any], event: str, kind: str, ask: Callable[..., dict[str, Any]],
               who: str = "Jev", places: dict[str, Any] | None = None) -> None:
        began = time.monotonic()
        try:
            substances = self.goods.substances() if self.goods is not None else None
            answers = ask(state, questions_for(kind, places, substances))
            decision = decide(answers, event, kind, who, places, substances)
        except Exception as failed:               # a fault upstream never stops the room
            decision = {"event": event, "pick": None, "confidence": 0.0, "call": None,
                        "said": f"{who} was not asked to the end ({str(failed)[:80]}); its reflexes have it"}
            _log.warning("banjo: the brain of %s failed: %s", self.name, str(failed)[:160])
        decision["took_ms"] = round(1000.0 * (time.monotonic() - began))
        with self._lock:
            self._answer = decision
            self.thinking = None

    def take(self) -> dict[str, Any] | None:
        """The decision waiting to be applied, once."""
        with self._lock:
            answer, self._answer = self._answer, None
        return answer

    def record(self, decision: dict[str, Any], applied: str | None) -> None:
        decision = dict(decision)
        decision["applied"] = applied
        self.decisions.append(decision)
        self.changed = True
        _log.info("banjo: the brain of %s: %s%s", self.name, decision.get("said"),
                  f" -> {applied}" if applied else "")

    def summary(self) -> dict[str, Any]:
        return {"name": self.name, "mode": self.mode,
                "configured": {m: (m in self.deciders) for m in MODES if m != "reflex"},
                "labels": {m: getattr(d, "label", m) for m, d in self.deciders.items()},
                "thinking": self.thinking, "decisions": list(self.decisions)[-6:],
                "routine": self.routine.summary()}


class Brains:
    """All the programs' brains in the one open room, and the seams the server
    uses: every reply of the room comes through listen(); before() is called
    before each step the page takes, to apply what was decided and to move
    each routine on; attach() tells the page what changed."""

    def __init__(self, deciders: Callable[[], Any]):
        # deciders() gives (the deciders by mode, the default mode), as
        # deciders_from does; a single client or None is taken as it amounts to.
        self._deciders = deciders
        self.brains: dict[str, Brain] = {}
        self.modes: dict[str, str] = {}            # kept across rooms, by name
        self.spec: dict[str, Any] | None = None    # the room's, for what each program's routine is
        self.person: dict[str, Any] | None = None  # where the person last said they stood
        # The room's goods ledger (machine_goods.Goods), over the spec's own
        # block, shared by every brain; and what a stockpile marked as the
        # Workshop's rack does with what lands on it (the server sets it).
        self.goods: Any = None
        self.on_rack: Callable[[str, float], None] | None = None

    def _made(self) -> tuple[Any, str]:
        made = self._deciders()
        if isinstance(made, tuple):
            return made
        return made, ("jev" if made is not None else "reflex")

    def of(self, name: str) -> Brain:
        brain = self.brains.get(name)
        if brain is None:
            deciders, default = self._made()
            brain = self.brains[name] = Brain(name, deciders, self.modes.get(name, default),
                                              routines.declared_for(self.spec, name))
            brain.goods = self.goods
        return brain

    def opened(self, spec: dict[str, Any] | None = None) -> None:
        """A room opened: what was observed of the last one is forgotten, the
        modes are kept, and the room's spec says what each routine is."""
        for name, brain in self.brains.items():
            self.modes[name] = brain.mode
        self.brains.clear()
        self.spec = spec
        import machine_goods
        self.goods = machine_goods.Goods(spec, on_rack=self.on_rack) if isinstance(spec, dict) else None

    def _ask(self, app: Any, session_id: Any) -> Callable[..., dict[str, Any]]:
        return lambda **command: app.live.act({"session": session_id, **command})

    def listen(self, session: Any, reply: Any) -> None:
        """The reply listener (app.reply_listeners): every step's programs,
        with the room's machines, bodies and knocks."""
        if not isinstance(reply, dict):
            return
        machines = reply.get("machines")
        if not isinstance(machines, dict) or not machines.get("programs"):
            return
        impacts = [i for i in (reply.get("impacts") or []) if isinstance(i, dict)]
        bodies = reply.get("bodies") if isinstance(reply.get("bodies"), list) else None
        t = float(reply.get("t") or 0.0)
        # The engine, for the senses read when something happens: the
        # session's own send, which this listener is already inside of (its
        # lock is reentrant), so a survey costs one line each.
        engine = getattr(session, "send", None)
        for program in machines["programs"]:
            if isinstance(program, dict) and program.get("name"):
                brain = self.of(str(program["name"]))
                brain.person = self.person
                brain.observe(program, machines, impacts, t, bodies=bodies, engine=engine)

    def before(self, app: Any, body: Any) -> None:
        """Before a step the page takes: what was decided goes to the tools,
        and each routine takes its next step if it is its turn."""
        if not isinstance(body, dict) or body.get("op") != "step":
            return
        if isinstance(body.get("person"), dict):
            self.person = body["person"]
        ask = self._ask(app, body.get("session"))
        for brain in list(self.brains.values()):
            brain.person = self.person
            ctx = brain.context(ask)
            decision = brain.take()
            if decision is not None:
                call, applied = decision.get("call"), None
                if call and (brain.before or {}).get("id") is not None and brain.mode != "reflex":
                    did = tools.run(ctx, tools.Call(call["tool"], call.get("args") or {}, brain.mode, call.get("why", "")))
                    applied = "not applied: " + did["did"] if did.get("failed") else did.get("did", "applied")
                brain.record(decision, applied)
            if (brain.before or {}).get("id") is not None:
                try:
                    did = brain.routine.tick(ctx)
                except Exception as failed:       # a routine that fails never stops the room
                    _log.exception("banjo: the routine of %s failed", brain.name)
                    did = {"did": f"failed: {str(failed)[:120]}", "failed": True}
                if did is not None:
                    brain.changed = True
                    _log.info("banjo: the routine of %s: %s", brain.name, did.get("did"))

    def attach(self, body: Any, answer: Any) -> None:
        """On a step's answer, the brains the page has not heard the latest of."""
        if not isinstance(body, dict) or body.get("op") != "step" or not isinstance(answer, dict):
            return
        changed = [b for b in self.brains.values() if b.changed]
        if not changed:
            return
        answer["brains"] = [b.summary() for b in changed]
        for b in changed:
            b.changed = False

    def request(self, body: Any) -> dict[str, Any]:
        """POST /api/world/rover/brain: {program: name, mode?}. The mode set, if
        given, and the brain as it stands."""
        if not isinstance(body, dict) or not body.get("program"):
            raise ValueError("expected {program: its name, mode: 'reflex', 'jev' or 'openai'}")
        brain = self.of(str(body["program"]))
        if body.get("mode") is not None:
            mode = str(body["mode"])
            if mode not in MODES:
                raise ValueError("a brain's mode is 'reflex', 'jev' or 'openai'")
            if mode == "jev" and "jev" not in brain.deciders:
                raise ValueError("TYPESAFE_API_KEY is not configured in the local .env, so Jev cannot be asked; "
                                 "the rover has its reflexes")
            if mode == "openai" and "openai" not in brain.deciders:
                raise ValueError("OPENAI_API_KEY is not configured in the local .env, so the model cannot be "
                                 "asked; the rover has its reflexes")
            brain.mode = mode
            self.modes[brain.name] = mode
            brain.changed = True
        return brain.summary()

    def summaries(self) -> list[dict[str, Any]]:
        return [b.summary() for b in self.brains.values()]
