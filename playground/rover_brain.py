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

The key is TYPESAFE_API_KEY, in the environment or the local .env (the same
files the OpenAI key is read from); JEV_API_URL there names another host that
speaks the same API (a reseller, a proxy, a scripted stand-in for a test) in
place of TypeSafe's. Without a key the rover has its reflexes, and its panel
says so.
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

# What Jev is asked, by the KIND of program (LiveProgram::kind): what the
# machine is, in words; what Jev can pick for it, and what the program is
# asked for each pick -- what to do, for how long, and the words the panel and
# the chat use; and the other questions worth asking of it in the same call.
# A new kind of machine -- one that digs, say -- is a new entry here, with the
# asks its program takes: nothing else in this file knows what a rover is.
KINDS: dict[str, dict[str, Any]] = {
    "roam": {
        "what": ("a small battery rover with a driven wheel on each side and a caster in front, roaming a "
                 "lake's shore on its own"),
        "picks": {
            "go_on": ("going forward", 2.0, "keep going",
                      "Keep going forward: the way ahead is clear and nothing just went wrong."),
            "back_off": ("backing off", 1.5, "back off",
                         "Reverse for a moment: something is ahead or in its way, or it just struck something "
                         "or its wheels stalled."),
            "turn_left": ("turning left", 2.5, "turn left",
                          "Turn on the spot to its left: the trouble (water, a slope, a thing) is on its right "
                          "or straight ahead and its left is the clear side."),
            "turn_right": ("turning right", 2.5, "turn right",
                           "Turn on the spot to its right: the trouble is on its left or straight ahead and "
                           "its right is the clear side."),
            "wait": ("waiting", 3.0, "hold still",
                     "Hold still on its brakes: it is unclear what is happening, a person is close to it, or "
                     "moving at all would make things worse."),
        },
        "also": {
            "stuck": {
                "type": "noul",
                "instructions": "The machine is stuck: its wheels make no progress, or it keeps turning away "
                                "from the same thing over and over without getting anywhere.",
                "criteria": {"true": "It is making no progress, or the same trouble keeps coming back.",
                             "false": "It is getting about, and this is a new situation."},
            },
            "battery": {
                "type": "score",
                "instructions": "How urgently the machine needs to rest and charge, from its battery's share "
                                "of full and whether it is charging.",
                # A score's criteria are its levels in order, low to high (2 to
                # 10); the answer's legend maps each level's number back to
                # its words.
                "criteria": ["fine: plenty of charge, no need to think about it",
                             "low: getting low, it should not go far from where it can charge",
                             "urgent: nearly flat, it should rest now"],
            },
        },
    },
}


def kind_of(kind: str) -> dict[str, Any]:
    return KINDS.get(kind) or KINDS["roam"]


def questions_for(kind: str) -> dict[str, Any]:
    """The questions Jev is asked of a machine of this kind, in one call."""
    k = kind_of(kind)
    return {
        "next": {
            "type": "choice",
            "instructions": (f"The machine is {k['what']}. `event` is what just happened to it; `machine` is "
                             "how it stands now. Pick what it should do for the next two seconds or so."),
            "criteria": {pick: words[3] for pick, words in k["picks"].items()},
        },
        **k["also"],
    }


# Kept for the tests and the docs: the rover's picks.
PICKS = {pick: words[:3] for pick, words in KINDS["roam"]["picks"].items()}
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

    def __init__(self, api_key: str, url: str = JEV_URL, model: str = JEV_MODEL, timeout_s: float = TIMEOUT_S):
        self.api_key, self.url, self.model, self.timeout_s = api_key, url, model, timeout_s

    def ask(self, state: Any, questions: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps({"model": self.model, "state": state, "questions": questions},
                          allow_nan=False).encode()
        req = request.Request(self.url, data=body, method="POST",
                              headers={"Authorization": "Bearer " + self.api_key,
                                       "Content-Type": "application/json"})
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


# ---- what the rover is, in words Jev reads ---------------------------------

def _side(sensor: dict[str, Any]) -> str:
    side = sensor.get("side", 0)
    return "left" if side > 0 else "right" if side < 0 else "middle"


def state_of(program: dict[str, Any], machines: dict[str, Any] | None, impacts: list[dict[str, Any]],
             event: str, recent: list[dict[str, Any]]) -> dict[str, Any]:
    """The rover as Jev is told it: the program as the engine reports it, its
    wheels' controllers, what just struck it, and what was decided lately.
    Curated, not the whole step: Jev reads 32k tokens and is paid by the one."""
    controls = {c.get("id"): c for c in (machines or {}).get("controls") or []}
    wheels = []
    for side, ident in (("left", program.get("left")), ("right", program.get("right"))):
        c = controls.get(ident) or {}
        wheels.append({"side": side, "condition": c.get("condition", ""), "speed_rpm": c.get("speed_rpm", 0.0),
                       "told": {"power": c.get("power"), "direction": c.get("direction"),
                                "setting": c.get("setting")}})
    parts = set(program.get("parts") or [])
    struck = [{"struck": i.get("struck"), "by": i.get("by"), "closing_speed_m_s": i.get("closing_speed_m_s"),
               "energy_j": i.get("energy_j")}
              for i in impacts if i.get("struck") in parts or i.get("by") in parts]
    return {
        "event": event,
        "machine": {
            "kind": program.get("kind"),
            "name": program.get("name"),
            "doing": program.get("doing"),
            "why": program.get("why"),
            "doing_for_s": program.get("doing_s"),
            "slope": {"nose_up_deg": program.get("pitch_deg"), "left_side_up_deg": program.get("roll_deg"),
                      "climbs_up_to_deg": program.get("climb_deg")},
            "battery": {"share_of_full": program.get("charge_share"), "rests_below": program.get("rest_below"),
                        "times_rested": program.get("rests")},
            "times_turned_away": program.get("turns"),
            "water_sensors": [{"side": _side(s), "water_under_it_mm": round(1000.0 * float(s.get("reading_m") or 0.0)),
                               "sees_water": bool(s.get("sees"))} for s in program.get("sensors") or []],
            "wheels": wheels,
            "asked": program.get("asked"),
        },
        "struck": struck[:6],
        "recent_decisions": recent[-4:],
    }


def situations(before: dict[str, Any] | None, now: dict[str, Any], machines: dict[str, Any] | None,
               impacts: list[dict[str, Any]]) -> list[str]:
    """What happened to the rover between two readings of its program, in the
    words its panel uses. Nothing while it is off or asked by someone."""
    if not now.get("power"):
        return []
    out: list[str] = []
    parts = set(now.get("parts") or [])
    for i in impacts:
        if i.get("struck") in parts and i.get("by") not in parts:
            out.append(f"{i.get('by')} struck it at {float(i.get('closing_speed_m_s') or 0.0):.1f} m/s")
        elif i.get("by") in parts and i.get("struck") not in parts:
            out.append(f"it ran into {i.get('struck')} at {float(i.get('closing_speed_m_s') or 0.0):.1f} m/s")
    if now.get("asked"):
        return out
    was = before or {}
    seen_was = {_side(s) for s in was.get("sensors") or [] if s.get("sees")}
    for s in now.get("sensors") or []:
        if s.get("sees") and _side(s) not in seen_was:
            out.append(f"water ahead on its {_side(s)}")
    controls = {c.get("id"): c for c in (machines or {}).get("controls") or []}
    for side, ident in (("left", now.get("left")), ("right", now.get("right"))):
        condition = str((controls.get(ident) or {}).get("condition") or "")
        if condition.startswith("stalled") and was.get("doing") == "going forward":
            out.append(f"its {side} wheel stalled")
    why, why_was = str(now.get("why") or ""), str(was.get("why") or "")
    if why != why_was and why.startswith("the ground here is steeper"):
        out.append("the ground ahead is steeper than it climbs")
    below = float(now.get("rest_below") or 0.0)
    share, share_was = float(now.get("charge_share") or 0.0), float(was.get("charge_share") or 1.0)
    if below > 0.0 and share < below + 0.1 <= share_was:
        out.append(f"its battery is getting low: {round(100 * share)}%")
    return out


def decide(answers: dict[str, Any], event: str, kind: str = "roam") -> dict[str, Any]:
    """Jev's answers as a decision: what to ask the program, or nothing, and
    what the panel says of it. A choice under CONFIDENCE_LEAST is left to the
    reflexes; a score or a noul the answer lacks is simply not said."""
    picks = kind_of(kind)["picks"]
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
    if pick not in picks:
        out["ask"] = None
        out["said"] = f"Jev gave no pick it knows ({pick or 'nothing'}); its reflexes have it"
        return out
    doing, for_s, words = picks[pick][:3]
    if confidence < CONFIDENCE_LEAST:
        out["ask"] = None
        out["said"] = f"Jev would {words} ({round(100 * confidence)}% sure): too unsure, so its reflexes have it"
        return out
    out["ask"] = {"doing": doing, "for_s": for_s,
                  "why": f"Jev said {words} ({round(100 * confidence)}% sure) when {event}"[:200]}
    out["said"] = f"Jev: {words} ({round(100 * confidence)}% sure) when {event}"
    return out


# ---- one brain per program ---------------------------------------------------

class Brain:
    """What thinks for one program, by its name (a program's id changes when
    the room is opened again; its name does not)."""

    def __init__(self, name: str, client: JevClient | None, mode: str):
        self.name = name
        self.client = client
        self.mode = mode if client is not None else "reflex"
        self.before: dict[str, Any] | None = None
        self.asked_at: dict[str, float] = {}       # event text -> world time it was asked at
        self.decisions: deque[dict[str, Any]] = deque(maxlen=DECISIONS_KEPT)
        self.talk: deque[dict[str, Any]] = deque(maxlen=24)
        self.thinking: str | None = None           # the event being asked about
        self._answer: dict[str, Any] | None = None
        self._lock = threading.Lock()
        self.seq = 0
        self.changed = True                        # the page should hear of it

    def observe(self, program: dict[str, Any], machines: dict[str, Any] | None, impacts: list[dict[str, Any]],
                t: float, ask: Callable[[Any, dict[str, Any]], dict[str, Any]] | None = None) -> None:
        events = situations(self.before, program, machines, impacts)
        self.before = program
        if self.mode != "jev" or self.client is None or not events:
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
        state = state_of(program, machines, impacts, event, [d for d in self.decisions if d.get("said")])
        kind = str(program.get("kind") or "roam")
        thread = threading.Thread(target=self._think, args=(state, event, kind, ask or self.client.ask),
                                  daemon=True, name=f"banjo-brain-{self.name}")
        thread.start()

    def _think(self, state: dict[str, Any], event: str, kind: str, ask: Callable[..., dict[str, Any]]) -> None:
        began = time.monotonic()
        try:
            answers = ask(state, questions_for(kind))
            decision = decide(answers, event, kind)
        except Exception as failed:               # a fault upstream never stops the room
            decision = {"event": event, "pick": None, "confidence": 0.0, "ask": None,
                        "said": f"Jev was not asked to the end ({str(failed)[:80]}); its reflexes have it"}
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
        return {"name": self.name, "mode": self.mode, "configured": self.client is not None,
                "thinking": self.thinking, "decisions": list(self.decisions)[-6:]}


class Brains:
    """All the programs' brains in the one open room, and the two seams the
    server uses: every reply of the room comes through listen(), and before()
    is called before each step the page takes, to apply what was decided."""

    def __init__(self, client: Callable[[], JevClient | None]):
        self._client = client
        self.brains: dict[str, Brain] = {}
        self.modes: dict[str, str] = {}            # kept across rooms, by name
        self.default_mode = "jev"

    def of(self, name: str) -> Brain:
        brain = self.brains.get(name)
        if brain is None:
            brain = self.brains[name] = Brain(name, self._client(), self.modes.get(name, self.default_mode))
        return brain

    def opened(self) -> None:
        """A room opened: what was observed of the last one is forgotten, the
        modes are kept."""
        for name, brain in self.brains.items():
            self.modes[name] = brain.mode
        self.brains.clear()

    def listen(self, session: Any, reply: Any) -> None:
        """The reply listener (app.reply_listeners): every step's programs."""
        if not isinstance(reply, dict):
            return
        machines = reply.get("machines")
        if not isinstance(machines, dict) or not machines.get("programs"):
            return
        impacts = [i for i in (reply.get("impacts") or []) if isinstance(i, dict)]
        t = float(reply.get("t") or 0.0)
        for program in machines["programs"]:
            if isinstance(program, dict) and program.get("name"):
                self.of(str(program["name"])).observe(program, machines, impacts, t)

    def before(self, app: Any, body: Any) -> None:
        """Before a step the page takes: what Jev decided goes to the program."""
        if not isinstance(body, dict) or body.get("op") != "step":
            return
        for brain in list(self.brains.values()):
            decision = brain.take()
            if decision is None:
                continue
            ask, applied = decision.get("ask"), None
            program = brain.before or {}
            if ask and program.get("id") is not None and brain.mode == "jev":
                brain.seq += 1
                try:
                    said = app.live.act({"session": body.get("session"), "op": "behave", "program": program["id"],
                                         "sender": "jev", "seq": brain.seq, **ask})
                    applied = str(said.get("asked"))
                except Exception as failed:
                    applied = f"not applied: {str(failed)[:120]}"
            brain.record(decision, applied)

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
            raise ValueError("expected {program: its name, mode: 'reflex' or 'jev'}")
        brain = self.of(str(body["program"]))
        if body.get("mode") is not None:
            mode = str(body["mode"])
            if mode not in ("reflex", "jev"):
                raise ValueError("a brain's mode is 'reflex' or 'jev'")
            if mode == "jev" and brain.client is None:
                raise ValueError("TYPESAFE_API_KEY is not configured in the local .env, so Jev cannot be asked; "
                                 "the rover has its reflexes")
            brain.mode = mode
            self.modes[brain.name] = mode
            brain.changed = True
        return brain.summary()

    def summaries(self) -> list[dict[str, Any]]:
        return [b.summary() for b in self.brains.values()]
