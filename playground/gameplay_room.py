"""Bind expedition bookkeeping to the live world's clock and atomic room save."""
from __future__ import annotations
from copy import deepcopy
import threading
import gameplay

LOCK = threading.RLock()


def active(app):
    return (getattr(getattr(app, "room", None), "scene", None) == "expedition"
            and getattr(app, "live_holder", None) == "world")


def opened(app, answer):
    if not active(app):
        return
    room = app.room
    state = getattr(room, "gameplay_record", None)
    t = float(answer.get("t", 0.0))
    if state is None:
        if getattr(room, "world_record", None):
            raise ValueError("Saved expedition is missing its gameplay state; refusing to reset resources")
        state = gameplay.new(answer["terrain"], t, water=answer.get("water"))
        room.gameplay_record = state
    elif state.get("version") != gameplay.VERSION:
        raise ValueError("Unsupported expedition save version")
    gameplay.advance(state, t)
    answer["gameplay"] = gameplay.report(state)


def sync(app, answer):
    if not active(app) or not isinstance(answer, dict):
        return
    state = getattr(app.room, "gameplay_record", None)
    if state is not None and isinstance(answer.get("t"), (int, float)):
        gameplay.advance(state, answer["t"])
        answer["gameplay"] = gameplay.report(state)


def request(app, body, keep_world):
    if not isinstance(body, dict) or set(body)-{"session", "op", "action"}:
        raise ValueError("Expected session, op and optional action")
    if not active(app) or app.live_holder != "world":
        raise ValueError("Open the expedition scene first")
    session = app.live.session
    if session is None or body.get("session") != session.id:
        raise ValueError("This expedition session is stale; reopen it")
    state = app.room.gameplay_record
    sync(app, {"t": session.state.get("t", state["time_s"])})
    op = body.get("op", "state")
    if op == "state":
        return {"gameplay": gameplay.report(state)}
    action = body.get("action")
    if op != "action":
        raise ValueError("op must be state or action; wait uses normal live steps")
    candidate = gameplay.action(state, action)
    previous_snapshot = getattr(app.room, "world_record", None)
    app.room.gameplay_record = candidate
    try:
        if not keep_world(app, "expedition action"):
            raise ValueError("The whole world could not be saved; action was not committed")
    except Exception:
        app.room.gameplay_record = state
        app.room.world_record = previous_snapshot
        raise
    return {"gameplay": gameplay.report(candidate)}
