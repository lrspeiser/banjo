"""Personal observation of source-attributed, durably saved machine batches.

Guests explicitly watch one machine. Avatar poses are client reports, as in
the rest of the world; distance and direction are checked, not physical eyes
or occlusion. Recipe ledger evidence is not chemistry certification.
"""
from __future__ import annotations

from copy import deepcopy
import logging
import math
import time
from typing import Any

import player_world
from mcp import progression
import world_access

REACH_M = 6.0
WINDOW_S = 120.0


def machines(app: Any) -> list[dict]:
    session = getattr(getattr(app, "live", None), "session", None)
    if session is None or getattr(app, "live_holder", None) != "world":
        return []
    state = session.state or {}
    bodies = {b["name"]: b for b in state.get("bodies") or []}
    native = {p["name"]: p for p in (state.get("machines") or {}).get("programs") or []}
    out = []
    for p in (app.room.spec.get("machines") or {}).get("programs") or []:
        live = native.get(p["name"])
        routine = p.get("routine") or {}
        recipe = routine.get("recipe") if routine.get("kind") == "process" else None
        if live is None or not recipe:
            continue
        parts = live.get("parts") or [p.get("body")]
        anchor = next((bodies[n] for n in parts if n in bodies and not bodies[n].get("parked")), None)
        if anchor is None or not isinstance(anchor.get("position_m"), list):
            continue
        out.append({"machine": p["name"], "recipe": recipe, "at_m": list(anchor["position_m"]),
                    "power": bool(live.get("power")), "program": p.get("kind")})
    return out


def _near(app: Any, owner: str, machine: dict) -> bool:
    profile = player_world.records(app).get(owner) or {}
    if time.time() - profile.get("seen_unix_s", 0) > player_world.ACTIVE_S:
        return False
    pose = profile.get("pose") or {}
    eyes, look = pose.get("eyes_m"), pose.get("look_direction") or pose.get("facing")
    if not eyes or not look:
        return False
    ray = [machine["at_m"][i] - eyes[i] for i in range(3)]
    distance = math.hypot(*ray)
    length = math.hypot(*look)
    return (.05 < distance <= REACH_M and length > .1
            and sum(ray[i]*look[i] for i in range(3)) / (distance*length) >= .5)


def request(app: Any, owner: str, body: Any, registry: Any) -> dict:
    if not isinstance(body, dict) or set(body) - {"session", "machine", "person"}:
        raise ValueError("Watch a selected machine with your current view")
    with world_access.state_lock(app), player_world.lock_of(app):
        machine = next((m for m in machines(app) if m["machine"] == body.get("machine")), None)
        if machine is None or progression.batch_design(registry, machine["recipe"]) is None:
            raise ValueError("This machine has no supported learning experiment")
        player_world.update_pose(app, owner, body.get("person"))
        if not _near(app, owner, machine):
            raise ValueError("Move within 6 m and face this machine to watch its next batch")
        if not machine["power"]:
            raise ValueError("Turn this machine on, then watch its next batch")
        if len(pending_of(app)) >= 1024:
            raise ValueError("Learning receipts are waiting for a save; retry after saving recovers")
        watched = app.__dict__.setdefault("machine_observers", {})
        watched[owner] = {"machine": machine["machine"],
                          "until_t": float(app.live.session.state.get("t") or 0) + WINDOW_S}
        return {"watching": machine["machine"], "recipe": machine["recipe"],
                "until_t": watched[owner]["until_t"],
                "said": "Stay nearby and face it. The next saved batch goes in your journal."}


def batch(app: Any, recipe: str, made: dict, used: dict, *, machine: str,
          batch: int, declaration: str, drawn_j: float, registry: Any) -> None:
    """Called by the trusted routine after its actual goods conversion."""
    with world_access.state_lock(app), player_world.lock_of(app):
        source = next((m for m in machines(app) if m["machine"] == machine and m["recipe"] == recipe), None)
        if source is None:
            return
        at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        evidence = progression.evidence_from_batch(recipe, made, used, registry=registry,
            session_id=f"{app.world_id}:{declaration}", machine=machine, at=at, batch=batch)
        if evidence is None:
            return
        evidence["result"]["drawn_j"] = drawn_j
        t = float(app.live.session.state.get("t") or 0)
        watchers = app.__dict__.setdefault("machine_observers", {})
        pending = pending_of(app)
        for owner, watch in list(watchers.items()):
            if watch["until_t"] < t:
                watchers.pop(owner, None)
            elif watch["machine"] == machine and _near(app, owner, source) and len(pending) < 1024:
                record = deepcopy(evidence)
                record["observer"] = {"player": owner, "pose": deepcopy(player_world.records(app)[owner]["pose"]),
                                      "machine_at_m": source["at_m"], "t_s": t,
                                      "rule": "explicit watch; fresh reported pose; within 6 m; view cone 120 degrees"}
                record["limitations"].append("avatar position is reported by the client; visibility occlusion is not checked")
                pending.append({"owner": owner, "machine": machine, "batch": batch,
                                "declaration": declaration, "evidence": record})
                watchers.pop(owner, None)


def saved(app: Any, journal_of: Any, registry: Any) -> None:
    """Publish knowledge only after the matching runtime/native save succeeds.

    Journal failures leave the pending receipt for retry. IDs come from the
    world, routine declaration, machine and persisted batch count; re-reading
    the receipt is idempotent across native session replacements.
    """
    pending = pending_of(app)
    for receipt in list(pending):
        runtime = (getattr(app.room, "machine_runtime", {}) or {}).get(receipt["machine"]) or {}
        if runtime.get("declaration") != receipt["declaration"] or runtime.get("batches", 0) < receipt["batch"]:
            continue
        try:
            journal = journal_of(app, receipt["owner"])
            journal.add_evidence(receipt["evidence"])
            progression.earn(journal, registry, receipt["evidence"]["at"])
        except (OSError, ValueError):
            logging.getLogger("banjo").exception("Machine learning receipt is waiting for journal save")
            continue
        pending.remove(receipt)


def pending_of(app: Any) -> list:
    if not isinstance(getattr(app.room, "machine_evidence_pending", None), list):
        app.room.machine_evidence_pending = []
    return app.room.machine_evidence_pending


def validate_pending(value: Any, runtime: dict, players: dict) -> None:
    import hashlib
    import json
    import re
    if value is None:
        return
    if not isinstance(value, list) or len(value) > 1024 or len(json.dumps(value, allow_nan=False)) > 2_000_000:
        raise ValueError("Invalid machine learning outbox")
    for receipt in value:
        if not isinstance(receipt, dict) or set(receipt) != {"owner", "machine", "batch", "declaration", "evidence"}:
            raise ValueError("Invalid machine learning receipt")
        if (not isinstance(receipt["owner"],str) or not isinstance(receipt["machine"],str)
                or not isinstance(receipt["evidence"],dict)):
            raise ValueError("Invalid machine learning source identity")
        source = (runtime or {}).get(receipt["machine"]) or {}
        evidence = receipt["evidence"]
        observer = evidence.get("observer")
        result = evidence.get("result")
        if (not isinstance(observer,dict) or not isinstance(result,dict)
                or any(not isinstance(evidence.get(k),str) or not evidence[k] or len(evidence[k])>2048
                       for k in ("id","run","at","design","object","test","action","said","claim","scope"))
                or not re.fullmatch(r"ev-[0-9a-f]{10}",evidence["id"])
                or evidence["id"] != "ev-"+hashlib.sha256(evidence["run"].encode()).hexdigest()[:10]
                or evidence.get("passes") is not True
                or not isinstance(evidence.get("models"),list) or not isinstance(evidence.get("limitations"),list)):
            raise ValueError("Invalid machine learning evidence")
        for k in ("made","used"):
            quantities = result.get(k)
            if not isinstance(quantities,dict) or not quantities or any(
                    not isinstance(n,str) or not n or type(v) not in (int,float) or not math.isfinite(v) or v <= 0
                    for n,v in quantities.items()):
                raise ValueError("Invalid machine learning quantities")
        for k in ("made_kg","used_kg","drawn_j"):
            if (type(result.get(k)) not in (int,float) or not math.isfinite(result[k])
                    or (result[k] < 0 if k == "drawn_j" else result[k] <= 0)):
                raise ValueError("Invalid machine learning measured total")
        if (receipt["owner"] not in (players or {})
                or not isinstance(receipt["declaration"], str) or not re.fullmatch(r"[0-9a-f]{64}", receipt["declaration"])
                or source.get("declaration") != receipt["declaration"]
                or type(receipt["batch"]) is not int or not 1 <= receipt["batch"] <= source.get("batches", 0)
                or not isinstance(evidence, dict) or evidence.get("source") != "watched"
                or evidence.get("machine") != receipt["machine"]
                or observer.get("player") != receipt["owner"]):
            raise ValueError("Machine learning receipt has no matching saved source and observer")
