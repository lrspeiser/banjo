"""Bounded autonomous guests using the same authenticated HTTP actions as people.

Model choices are plans, not success evidence. The native game, market and
personal goal evaluator decide what happened. No AI token is sent to viewers.
"""
from __future__ import annotations

from copy import deepcopy
import json
import logging
import math
import threading
import time
from typing import Any
from urllib import request, error
import uuid

import inventory_room
import player_world
import rover_brain
import world_access

MAX_DECISIONS = 24
MAX_AGENTS = 4
CADENCE_S = .8
CRITERIA = {
    "bank": "Bank 500 measured joules when energy is needed for the current goal or oak purchases.",
    "buy_oak": "Buy one oak lot at its current quote, if affordable and in stock, toward the personal supplies goal.",
    "build_stool": "Walk to the camp site, then preview and commit the declared Camp stool using paid stock.",
    "pack_stool": "Walk near the personally built stool, then put it in your own inventory.",
    "wait": "Stop and report a blocker when no offered action can make progress. Do not invent resources or success.",
}


def choices(goals: dict[str, Any], market: dict[str, Any]) -> list[str]:
    step = goals["next_goal"]
    if step == "bank-solar": return ["bank", "wait"]
    if step == "stock-oak":
        oak = next(o for o in market["offers"] if o["id"] == "oak-stock")
        left = max(0, math.ceil((3 - goals["goals"][1]["value"]) / oak["mass_kg"]))
        out = []
        if market["balance_j"] < left * oak["price_j"] * 1.1: out.append("bank")
        if oak["remaining"] > 0 and market["balance_j"] >= oak["price_j"]: out.append("buy_oak")
        return out + ["wait"]
    return {"build-camp": ["build_stool", "wait"], "carry-camp": ["pack_stool", "wait"]}.get(step, ["wait"])


def reference_pick(goals: dict[str, Any], offered: list[str]) -> str:
    desired = {"bank-solar": "bank", "stock-oak": "buy_oak", "build-camp": "build_stool",
               "carry-camp": "pack_stool"}.get(goals["next_goal"], "wait")
    return desired if desired in offered else "bank" if "bank" in offered else "wait"


class Manager:
    def __init__(self, app: Any, port: int, keep: Any, journal: Any, registry: Any):
        self.app, self.port, self.keep, self.journal, self.registry = app, port, keep, journal, registry
        self.lock = threading.RLock()
        self.workers: dict[str, tuple[threading.Thread, threading.Event]] = {}
        self.decider_factory = lambda: rover_brain.OpenAIDecider(app.api_key, app.model)
        self.cadence_s = CADENCE_S
        # Restart never silently resumes paid calls. Tokens, bags, journals,
        # evidence and history survive; an owner explicitly resumes play.
        for profile in player_world.records(app).values():
            ai = profile.get("ai")
            if isinstance(ai, dict) and ai.get("status") in ("running", "thinking", "walking"):
                profile["ai"] = {**ai, "status": "paused", "message": "Paused after server restart"}

    def _profile(self, ident: Any) -> dict[str, Any]:
        profile = player_world.records(self.app).get(str(ident))
        if profile is None or not isinstance(profile.get("ai"), dict):
            raise ValueError("This world has no AI character with that id")
        return profile

    def _save(self, profile: dict[str, Any], **updates: Any) -> None:
        with world_access.gate(self.app).enter(exclusive=True), world_access.state_lock(self.app):
            with player_world.lock_of(self.app):
                worker = self.workers.get(profile["id"])
                if worker and worker[1].is_set() and updates.get("status") in ("running", "thinking", "walking"):
                    updates.pop("status", None)
                    updates.pop("message", None)
                profile["ai"] = {**profile["ai"], **updates}
            if self.app.live.session and self.app.live_holder == "world":
                if not self.keep(self.app, "AI character checkpoint"):
                    raise ValueError("The AI character awaits a durable world save")
            elif not self.app.store.save(self.app.room):
                raise ValueError("The AI character could not be saved")

    def _post(self, profile: dict[str, Any], path: str, body: dict[str, Any], cookie: str) -> dict[str, Any]:
        headers = {"Content-Type": "application/json", "X-Banjo-Token": self.app.csrf_token,
                   "X-Banjo-World": self.app.world_id, "X-Banjo-Player": profile["token"]}
        if cookie: headers["Cookie"] = cookie
        req = request.Request(f"http://127.0.0.1:{self.port}" + path, method="POST", headers=headers,
                              data=json.dumps(body, allow_nan=False).encode())
        try:
            with request.urlopen(req, timeout=30) as response: return json.load(response)
        except error.HTTPError as exc:
            try: message = json.load(exc).get("error", f"Game refused HTTP {exc.code}")
            except (ValueError, OSError): message = f"Game refused HTTP {exc.code}"
            raise ValueError(message) from None

    def handle(self, owner: str, body: Any, cookie: str = "") -> dict[str, Any]:
        if not isinstance(body, dict) or set(body) - {"action", "id", "name", "mode", "full"}:
            raise ValueError("Expected an AI character action")
        action = body.get("action", "list")
        if action == "list":
            with player_world.lock_of(self.app):
                profiles = list(player_world.records(self.app).values())
            return {"schema": "banjo.ai-players.v1", "model_available": bool(self.app.api_key),
                    "characters": [self.summary(p, owner) for p in profiles
                                   if isinstance(p.get("ai"), dict)]}
        if "full" in body and not isinstance(body["full"], bool): raise ValueError("full must be true or false")
        if action == "watch": return self.watch(self._profile(body.get("id")), owner, body.get("full", False))
        if action not in ("start", "pause"): raise ValueError("Use list, start, pause or watch")
        with self.lock:
            if body.get("id"):
                profile = self._profile(body["id"])
                if profile["ai"]["controller"] != owner:
                    raise ValueError("Only this character's creator can start or pause it")
            else:
                if action != "start": raise ValueError("Name the character to pause")
                mode = body.get("mode", "openai")
                if mode not in ("openai", "reference"): raise ValueError("Use OpenAI or reference mode")
                if mode == "openai" and not self.app.api_key:
                    raise ValueError("Configure OPENAI_API_KEY to start an AI character, or select Reference bot")
                with player_world.lock_of(self.app):
                    count = sum(bool(p.get("ai")) for p in player_world.records(self.app).values())
                if count >= MAX_AGENTS:
                    raise ValueError("This world supports four AI characters")
                joined = player_world.join(self.app, name=body.get("name") or "Banjo explorer")
                profile = player_world.records(self.app)[joined["id"]]
                profile["ai"] = {"controller": owner, "mode": mode, "status": "paused", "decisions": 0,
                                 "history": [], "message": "Ready for the first-camp goals"}
                self._save(profile)
            old = self.workers.get(profile["id"])
            if action == "pause":
                if old: old[1].set()
                # An in-flight model call may finish, but its choice is checked
                # against the stop event before any game action is executed.
                self._save(profile, status="paused", message="Paused by its creator")
            elif not old or not old[0].is_alive():
                if profile["ai"]["mode"] == "openai" and not self.app.api_key:
                    raise ValueError("The configured model is unavailable")
                self._save(profile, status="running", decisions=0, message="Beginning the first-camp goals")
                stop = threading.Event()
                worker = threading.Thread(target=self._run, args=(profile, stop, cookie), daemon=True,
                                          name=f"banjo-ai-{profile['id'][:8]}")
                self.workers[profile["id"]] = (worker, stop)
                worker.start()
            elif old[1].is_set():
                raise ValueError("The character is finishing its current request; resume in a moment")
            return self.summary(profile, owner)

    def summary(self, profile: dict[str, Any], owner: str) -> dict[str, Any]:
        ai = profile["ai"]
        return {"id": profile["id"], "name": profile["name"], "pose": deepcopy(profile.get("pose")),
                "mode": ai["mode"], "status": ai["status"], "message": ai.get("message"),
                "decisions": ai["decisions"], "can_control": ai["controller"] == owner,
                "history": deepcopy(ai.get("history", [])[-12:])}

    def watch(self, profile: dict[str, Any], owner: str, full: bool = False) -> dict[str, Any]:
        if not self.app.live.session or self.app.live_holder != "world":
            raise ValueError("Start the character before watching its world")
        import starter_goals
        import progression
        ident = profile["id"]
        state = (self.app.live.rejoin(self.app, shared=True) if full else
                 self.app.live.act({"session": self.app.live.session.id, "op": "poses", "actor": ident}))
        if state is None: raise ValueError("The character's world could not be read")
        state["session"] = self.app.live.session.id
        state["scene"] = self.app.room.scene
        state["inventory"] = inventory_room.shown(self.app, ident)
        state["players"] = player_world.visible(self.app)
        player_world.personalize_hand(state, ident)
        state["notebook"] = progression.notebook(self.journal(self.app, ident), self.registry())
        goals = starter_goals.view(self.app, ident, {})
        return {"character": self.summary(profile, owner), "goals": goals,
                "skills": progression.tech_tree(self.journal(self.app, ident), self.registry()), "state": state}

    def _move(self, profile: dict[str, Any], stop: threading.Event, cookie: str, target: list[float]) -> None:
        self._save(profile, status="walking", message="Walking to the camp site")
        start = (profile.get("pose") or {}).get("eyes_m", [0, 1.62, 3])
        distance = math.hypot(target[0] - start[0], target[1] - start[2])
        steps = max(1, math.ceil(distance / .4))
        if steps > 40: raise ValueError("The camp site exceeds the bounded walking route")
        for step in range(1, steps + 1):
            if stop.is_set(): return
            opened = self._post(profile, "/api/world/open", {}, cookie)
            x = start[0] + (target[0] - start[0]) * step / steps
            z = start[2] + (target[1] - start[2]) * step / steps
            surveyed = self._post(profile, "/api/live/act", {"session": opened["session"], "op": "survey",
                                                          "at": [x, z]}, cookie)
            ground = surveyed.get("survey") or {}
            if not ground.get("on_the_ground"): raise ValueError("The camp route leaves the native terrain")
            person = {"eyes_m": [x, float(ground["ground_m"]) + 1.62, z], "facing": [3-x, 0, -z],
                      "look_direction": [3-x, -1.5, -z]}
            self._post(profile, "/api/live/act", {"session": opened["session"], "op": "step", "dt": 1/240,
                                               "n": 48, "person": person}, cookie)
            stop.wait(.2)
        if not stop.is_set(): self._save(profile, status="running", message="At the camp site")

    def _run(self, profile: dict[str, Any], stop: threading.Event, cookie: str) -> None:
        try:
            self._post(profile, "/api/world/open", {}, cookie)
            if profile.get("pose") is None:
                self._move(profile, stop, cookie, [0, 3])
            while not stop.is_set():
                goals = self._post(profile, "/api/workshop/goals", {}, cookie)
                if goals["complete"]:
                    self._save(profile, status="complete", message="First camp complete. Ready for another goal chain.")
                    return
                if profile["ai"]["decisions"] >= MAX_DECISIONS:
                    self._save(profile, status="blocked", message="The 24-decision budget was reached; inspect progress before resuming")
                    return
                market = self._post(profile, "/api/workshop/market", {}, cookie)
                offered = choices(goals, market)
                began = time.monotonic()
                self._save(profile, status="thinking", message="Choosing the next action")
                if profile["ai"]["mode"] == "openai":
                    questions = {"next": {"type": "choice", "instructions":
                        "Play this character's first-camp goals. Choose an offered action using current evidence. "
                        "Never claim completion, teach yourself, alter physics, or invent stock. Use wait only for a real blocker.",
                        "criteria": {key: CRITERIA[key] for key in offered}}}
                    decision = self.decider_factory().ask({"goals": goals["goals"], "next_goal": goals["next_goal"],
                        "balance_j": market["balance_j"], "oak": next(o for o in market["offers"] if o["id"] == "oak-stock"),
                        "inventory": inventory_room.shown(self.app, profile["id"]),
                        "tech_tree": self._tech_tree(profile["id"]),
                        "recent_actions": profile["ai"]["history"][-4:]}, questions)["next"]
                    pick, confidence = decision["choice"], decision["confidence"]
                else:
                    pick, confidence = reference_pick(goals, offered), None
                if stop.is_set(): return
                if pick not in offered: raise ValueError("The planner chose an unsupported action")
                ident = uuid.uuid4().hex
                entry = {"id": ident, "action": pick, "mode": profile["ai"]["mode"],
                         "model": self.app.model if confidence is not None else None, "confidence": confidence,
                         "seconds": round(time.monotonic() - began, 3), "goal": goals["next_goal"],
                         "result": "pending", "at_unix_s": time.time()}
                history = (profile["ai"]["history"] + [entry])[-64:]
                self._save(profile, status="running", decisions=profile["ai"]["decisions"] + 1,
                           history=history, message=CRITERIA[pick])
                if pick == "wait":
                    self._save(profile, status="blocked", history=history[:-1] + [{**entry, "result": "blocked"}],
                               message="Planner stopped for a blocker; inspect the current goals and Market")
                    return
                result = self._execute(profile, stop, cookie, pick, goals, market, ident)
                entry = {**entry, "result": "committed" if result else "cancelled", "receipt": result}
                self._save(profile, history=history[:-1] + [entry], message=f"Completed action: {pick}")
                if stop.is_set(): return
                stop.wait(self.cadence_s)
        except Exception as exc:
            if not stop.is_set():
                history = deepcopy(profile["ai"].get("history", []))
                if history and history[-1]["result"] == "pending":
                    history[-1].update(result="refused", error=str(exc)[:240])
                try: self._save(profile, status="blocked", message=str(exc)[:240], history=history)
                except Exception: logging.getLogger("banjo").exception("AI character checkpoint failed")

    def _tech_tree(self, ident):
        import progression
        return progression.tech_tree(self.journal(self.app, ident), self.registry())

    def _execute(self, profile, stop, cookie, pick, goals, market, ident):
        if pick == "bank":
            reply = self._post(profile, "/api/workshop/market", {"action": "bank", "joules": 500, "request_id": ident}, cookie)
            return {"balance_j": reply["balance_j"]}
        if pick == "buy_oak":
            oak = next(o for o in market["offers"] if o["id"] == "oak-stock")
            reply = self._post(profile, "/api/workshop/market", {"action": "buy", "item_id": oak["id"],
                "quoted_price_j": oak["price_j"], "request_id": ident}, cookie)
            return {"balance_j": reply["balance_j"], "paid_j": oak["price_j"]}
        self._move(profile, stop, cookie, [3, 1.2])
        if stop.is_set(): return {}
        source = self._post(profile, "/api/world/workshop/context", {}, cookie)
        if pick == "build_stool":
            preview = self._post(profile, "/api/world/workshop/preview", {"session": source["session"],
                "scene": source["scene"], "candidate": goals["recipe"], "mode": "authoring", "position_m": [3, 0]}, cookie)
            if stop.is_set(): return {}
            reply = self._post(profile, "/api/world/workshop/commit", {"session": preview["session"],
                "scene": preview["scene"], "preview_id": preview["preview_id"], "request_id": ident}, cookie)
            return {"body": reply["root_body"], "mass_kg": reply["mass_kg"], "resources_charged": reply["resources_charged"]}
        current = self._post(profile, "/api/workshop/goals", {}, cookie)
        reply = self._post(profile, "/api/world/inventory", {"session": source["session"], "op": "take",
            "item": current["camp_body"], "request": ident}, cookie)
        if not reply.get("ok"): raise ValueError(reply.get("why") or "Inventory refused the stool")
        return {"body": current["camp_body"], "revision": reply["record"]["revision"]}

    def shutdown(self) -> None:
        for _, stop in self.workers.values(): stop.set()
