"""Using a tool, the same way for every tool.

The owner, 2026-09-14, on the pick: "make sure this is designed to be a
generic capability, so if I build a hoe or an axe it will have the same
capabilities, meaning the llm can tap into these user experience capabilities
and even shape them". And the rule for all of it: automate the handling, not
the physical outcome.

So the page never knows a tool's steps. It asks here what the tool in the
person's hand does where the crosshair meets the ground (`resolve`): the action
and its label, whether it can be done there and why not, and the ring to draw.
A click asks for it to be done (`run`), and it is done here with the bounded
hand while the page keeps the room running: the tool held still, swung, pried
when the point is in, drawn back out -- and what came of it said in plain
words, with the engine's numbers beside them. How deep a point goes and what
comes loose are the ground's (docs/ground-work.md); what a profile's `use` may
shape is the handling (interaction_profiles.tool_use).

One template so far, swing-and-lever: the only tool motion the engine plans. A
hoe's draw through the soil and an axe's chop are not modelled yet; their
motions would come in here as templates, and the page would not change.

Measured with the pick before this (the scratchpad's headless_world_pick.py):
E took it only with the crosshair exactly on its 4 cm haft, a second left
click with the point in the ground dropped it, and one swing in three came back
"It met no ground" on plain sand.
"""
from __future__ import annotations

import math
import sys
import time
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mcp"))
import interaction_profiles  # noqa: E402

import world_chat  # noqa: E402  where the person is, as the page says and the chat is told

# The person's shoulder is 0.17 m under their eyes (1.62 m eyes, 1.45 m
# shoulder), as the page and the MCP's trial have it.
SHOULDER_BELOW_EYES_M = 0.17
# Held still before a swing. At least long enough for a step the page sent with
# the hand's ready pose to be done: one arriving after the swing began cancels
# it (LiveWorld moveHeld). Then until the tool has stopped swaying, as the MCP's
# trial holds it a second before every swing: the engine plans a swing from
# where the tool is, and a swing planned from a tool still moving joins its path
# part way.
SETTLE_LEAST_S, SETTLE_MOST_S = 0.35, 2.0
STILL_M_S = 0.25
# How long a stroke is waited for, and how long the hand keeps at a swing or a
# pry before giving up (the trial's 3 s: a slow swing of a heavy tool is long).
STROKE_LIMIT_S = 6.0
GIVE_UP_S = 3.0
# How long a stroke the room has not yet said is under way is waited for before
# an end it says is believed.
STROKE_UNSEEN_S = 1.5
# A pry that does not bring the point out by its own lift is drawn straight up.
PULL_M, PULL_SPEED_M_S = 0.4, 0.6
# How long the ground is given to say a meeting is over once the point is out:
# it closes it in the step after (ToolTerrain settle).
CLOSE_WAIT_S = 1.5
# Bare rock is rock with less than this over it, and water deeper than this is
# wet ground -- ground-work-v1's own lines (ToolTerrain judgeGround).
BARE_ROCK_M = 0.01
WET_M = 0.005


def _point(value: Any) -> list[float] | None:
    if (isinstance(value, (list, tuple)) and len(value) == 3
            and all(type(v) in (int, float) and math.isfinite(v) for v in value)):
        return [float(v) for v in value]
    return None


def profile_held(app: Any) -> dict[str, Any] | None:
    """The profile of the tool the hand holds, or None: the hand's `holding`,
    as the running room says it, is the body a tool profile names as its tool."""
    session = app.live.session
    holding = ((session.state or {}).get("hand") or {}).get("holding") if session else None
    if not holding:
        return None
    return next((p for p in (app.room.spec.get("interactions") or [])
                 if p.get("template") == "swing-and-lever" and p.get("tool") == holding), None)


def resolve(app: Any, body: dict[str, Any]) -> dict[str, Any]:
    """What the tool in the person's hand does where they look.

    `body` is what the page sends: `person` (where they are, as for the chat)
    and `at_m`, where the crosshair meets the ground, or None. The answer is the
    same for the page, the chat and the API: the action (`id`, `label`, the input
    that does it, the hands it needs, whether holding repeats it), whether it
    can be done there (`enabled`) and why not (`reason`), the `target` and the
    `ring` the page draws -- "ok" where it can work, "far" and "near" where it
    cannot reach, "warn" where the engine is likely to stop it (bare rock, wet
    ground: it may still be tried, and the engine says what happened), "no"
    where there is no ground. Looking never does anything: only `run` does."""
    profile = profile_held(app)
    if profile is None:
        return {"enabled": False, "reason": "Take up a tool first: look at it and press E.",
                "ring": None}
    use = interaction_profiles.tool_use(profile)
    out: dict[str, Any] = {"id": f"use:{profile['object']}", "object": profile["object"],
                           "tool": profile["tool"], "template": profile["template"],
                           "label": use["label"], "input": "primary", "hands": 1,
                           "repeat": use["repeat"], "enabled": False, "reason": None,
                           "ring": None, "target": None}
    at = _point(body.get("at_m"))
    if at is None:
        out["reason"] = "Point the crosshair at the ground: the point comes down where it meets it."
        return out
    person = world_chat.where_the_person_is(body.get("person"))
    if person is None or not person.get("eyes_m"):
        out["reason"] = "The page did not say where you are."
        return out
    eyes = [float(v) for v in person["eyes_m"]]
    level = math.hypot(at[0] - eyes[0], at[2] - eyes[2])
    least, most = use["reach_m"]
    ring = {"at_m": at, "state": "ok"}
    out["ring"] = ring
    out["target"] = {"at_m": at, "distance_m": round(level, 2)}
    if level > most:
        ring["state"] = "far"
        out["reason"] = (f"That is {level:.1f} m away: step closer. It comes down at most "
                         f"{most:g} m in front of you.")
        return out
    if level < least:
        ring["state"] = "near"
        out["reason"] = ("That is at your feet: aim a little further out." if level < 0.6 else
                         f"That is {level:.1f} m in front of you, too close to swing it down there:"
                         f" step back a little. It comes down {least:g} to {most:g} m in front of you.")
        return out
    try:
        survey = (app.live.act({"session": app.live.session.id, "op": "survey",
                                "at": [at[0], at[2]]}) or {}).get("survey") or {}
    except Exception as problem:     # the room says why it could not
        ring["state"] = "no"
        out["reason"] = f"The ground there could not be read: {problem}"
        return out
    if not survey.get("on_the_ground"):
        ring["state"] = "no"
        out["reason"] = "There is no ground there to work."
        return out
    ground_m = float(survey.get("ground_m", at[1]))
    ring["at_m"] = out["target"]["at_m"] = [at[0], ground_m, at[2]]
    cover = ground_m - float(survey.get("rock_top_m", ground_m - 1.0))
    water = survey.get("water")
    wet = float((water or {}).get("depth_m", 0.0) if isinstance(water, dict)
                else (water or 0.0))
    surface = str(survey.get("surface") or "ground")
    out["target"]["ground"] = surface
    out["enabled"] = True
    if wet > WET_M:
        ring["state"] = "warn"
        out["reason"] = "Under water: wet ground is not modelled, and the engine will say so."
    elif surface == "rock" or cover < BARE_ROCK_M:
        ring["state"] = "warn"
        out["target"]["ground"] = "rock"
        out["reason"] = "Bare rock: a point no harder than the rock stops on it."
    return out


def run(app: Any, body: dict[str, Any],
        note: Callable[[Any, dict[str, Any]], None] | None = None) -> dict[str, Any]:
    """One use of the tool in hand where the person looks: the whole of it, as
    their one click asks. Refused, with why, where `resolve` says it cannot be
    done; otherwise the tool is held still, swung at the ground there, pried if
    the point went in and the profile pries it, and drawn out -- each stroke the
    engine's, with the bounded hand. `note` is told of the swing, so what it does
    to the ground is credited to the person's notebook (server.note_strike).

    The ground's record of the meeting is heard from the room's replies while
    it is used (app.reply_listeners): a record that has closed is sent over in
    exactly one reply and then forgotten, so asking the room for it afterwards
    finds only the last open one -- which is how every use first said "it is
    still in" when the pry had broken out 5 L.

    Answers {action, did, done, said, detail, result, carried, repeat}, or
    {action, refused, done}: `said` in plain words, `detail` in the engine's
    numbers, `done` each stroke and how it ended, `result` the ground's record."""
    said = resolve(app, body)
    label = said.get("label") or "Use it"
    if not said.get("enabled"):
        return {"action": label, "refused": said.get("reason") or "It cannot be used there.",
                "done": []}
    session = app.live.session
    if getattr(session, "tool_busy", False):
        return {"action": label, "refused": "The hand is still busy with the last use.", "done": []}
    profile = profile_held(app)
    use = interaction_profiles.tool_use(profile)
    tool = profile["tool"]
    eyes = [float(v) for v in world_chat.where_the_person_is(body.get("person"))["eyes_m"]]
    shoulder = [eyes[0], eyes[1] - SHOULDER_BELOW_EYES_M, eyes[2]]
    at = said["target"]["at_m"]
    heard: dict[Any, dict[str, Any]] = {}

    def listen(_session: Any, reply: Any) -> None:
        for record in (reply or {}).get("ground_work") or []:
            if isinstance(record, dict) and record.get("tool", tool) == tool:
                heard[(record.get("point"), record.get("at_s"))] = record

    listeners = getattr(app, "reply_listeners", None)
    if listeners is not None:
        listeners.append(listen)
    session.tool_busy = True
    done: list[str] = []
    record: dict[str, Any] | None = None
    short: str | None = None
    try:
        if _point_in(app, tool):
            # A point still in the ground from before is drawn out first: a
            # swing planned from a tool the ground holds fast goes nowhere.
            grip = _grip(session)
            if grip is not None:
                done.append(f"drew it out of the ground first: {_pull(app, grip)}")
        if not _settle(app, tool):
            done.append(f"held {tool} as still as it would go")
        lever = use["lever"] or interaction_profiles.TOOL_USE_DEFAULTS["lever"]
        started = app.live.act({"session": session.id, "op": "strike", "at": at,
                                "shoulder": shoulder, "speed_m_s": use["swing"]["speed_m_s"],
                                "raise_deg": use["swing"]["raise_deg"], "lever": False,
                                "lever_deg": lever["lever_deg"], "give_up_s": GIVE_UP_S})
        if note is not None:
            note(app, started)
        since = float((started or {}).get("t") or 0.0)
        ended = _stroke(app)
        record = _latest(app, tool, since, heard)
        done.append(f"swung it: {record.get('kind') if record else 'it met no ground'}, "
                    f"the stroke {ended}")
        if record is None:
            # What there is to say of a swing that met nothing: where its point
            # ended, over what ground, against where it was sent.
            tip = _point(next((p.get("tip") for p in (app.live.act(
                {"session": session.id, "op": "tool_points"}) or {}).get("tool_points") or []
                if p.get("body") == tool), None))
            under = None
            if tip is not None:
                under = ((app.live.act({"session": session.id, "op": "survey", "at": [tip[0], tip[2]]})
                          or {}).get("survey") or {}).get("ground_m")
            done.append(f"heard since t={since:.3f}: "
                        + str([(r.get("kind"), r.get("at_s"), r.get("open")) for r in heard.values()])
                        + f"; sent at {[round(v, 3) for v in at]}, the point ended at "
                        + (f"{[round(v, 3) for v in tip]} over ground at {under}" if tip else "nowhere said"))
            if tip is not None and under is not None:
                # Said as it was measured: where the point stopped, against
                # where it was sent -- not "it met no ground" when the ground
                # was a centimetre under it.
                above_mm = 1000.0 * (tip[1] - float(under))
                before_cm = 100.0 * math.hypot(tip[0] - at[0], tip[2] - at[2])
                if 0.0 <= above_mm < 150.0:
                    close = said["target"].get("distance_m", 9.0) < 1.4
                    short = (f"The swing stopped short: its point ended {above_mm:.0f} mm above the "
                             f"ground, {before_cm:.0f} cm from where you aimed."
                             + (" Step back a little and swing again." if close else ""))
        if record is not None and record.get("open") and record.get("kind") in ("in the ground",
                                                                                "broke out"):
            if use["lever"] is not None:
                app.live.act({"session": session.id, "op": "strike", "lever": True,
                              "shoulder": shoulder, "speed_m_s": use["lever"]["speed_m_s"],
                              "raise_deg": 0.0, "lever_deg": use["lever"]["lever_deg"],
                              "give_up_s": GIVE_UP_S})
                ended = _stroke(app)
                record = _latest(app, tool, since, heard, record)
                done.append(f"pried it: {record.get('kind')}, the stroke {ended}")
            if record.get("open"):
                grip = _grip(session)
                if grip is not None:
                    done.append(f"drew it out: the stroke {_pull(app, grip)}")
            record = _closed(app, tool, since, heard, record)
    finally:
        session.tool_busy = False
        if listeners is not None and listen in listeners:
            listeners.remove(listen)
    carried = _carried(app)
    kg = sum(float(carried.get(k) or 0.0) for k in ("soil_kg", "sand_kg"))
    return {"action": label, "did": [label], "done": done,
            "said": short if record is None and short else _said(record, use, kg),
            "detail": _detail(record), "result": record, "carried": carried,
            "repeat": use["repeat"]}


def _settle(app: Any, tool: str) -> bool:
    """Wait for the tool to hang still in the hand: True once it does, False
    when it has swayed for SETTLE_MOST_S (and it is swung from there)."""
    began = time.monotonic()
    time.sleep(SETTLE_LEAST_S)
    while time.monotonic() - began < SETTLE_MOST_S:
        body = next((b for b in (app.live.session.state or {}).get("bodies") or []
                     if b.get("name") == tool), None)
        speed = _point((body or {}).get("velocity_m_s"))
        if speed is None or math.sqrt(sum(v * v for v in speed)) < STILL_M_S:
            return True
        time.sleep(0.05)
    return False


def _stroke(app: Any) -> str:
    """Wait -- while the page keeps the room running -- for the hand's stroke to
    end, and say how: reached, blocked, gave up, cancelled; with how long it was
    waited for, and "never seen going" when the room never said it was under
    way (the end then said may be the last stroke's)."""
    began = time.monotonic()
    started = False
    while time.monotonic() - began < STROKE_LIMIT_S:
        hand = (app.live.session.state or {}).get("hand") or {}
        waited = time.monotonic() - began
        if hand.get("stroking"):
            started = True
        elif hand.get("stroke_ended") and (started or waited > STROKE_UNSEEN_S):
            return f"{hand['stroke_ended']} after {waited:.2f} s" + ("" if started else ", never seen going")
        time.sleep(0.02)
    return f"ran out of time after {STROKE_LIMIT_S:g} s"


def _grip(session: Any) -> list[float] | None:
    return _point(((session.state or {}).get("hand") or {}).get("grip_m"))


def _pull(app: Any, grip: list[float]) -> str:
    app.live.act({"session": app.live.session.id, "op": "stroke",
                  "path": [grip, [grip[0], grip[1] + PULL_M, grip[2]]],
                  "speed_m_s": PULL_SPEED_M_S, "accel_m_s2": 4.0, "lead_m": 0.05,
                  "let_go": False, "give_up_s": GIVE_UP_S})
    return _stroke(app)


def _point_in(app: Any, tool: str) -> bool:
    """Whether the tool's point is in the ground now, as the room says."""
    try:
        points = (app.live.act({"session": app.live.session.id, "op": "tool_points"}) or {})
    except Exception:
        return False
    point = next((p for p in points.get("tool_points") or [] if p.get("body") == tool), None)
    return bool(point and (point.get("in") or float(point.get("depth_m") or 0.0) > 0.005))


def _latest(app: Any, tool: str, since: float, heard: dict[Any, dict[str, Any]],
            fallback: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """The latest record of this tool meeting the ground since the swing: from
    the replies heard while it was used, or -- where nothing listens (a room that
    hands its steps no ground work, the in-process lane) -- from the room's own
    list of what is still open."""
    records = [r for r in heard.values() if float(r.get("at_s", since) or since) >= since - 0.05]
    if not records and not heard:
        answer = app.live.act({"session": app.live.session.id, "op": "ground_work"}) or {}
        records = [r for r in answer.get("ground_work") or [] if isinstance(r, dict)
                   and r.get("tool", tool) == tool
                   and float(r.get("at_s", since) or since) >= since - 0.05]
    if not records:
        return fallback
    return max(records, key=lambda r: float(r.get("at_s") or 0.0))


def _closed(app: Any, tool: str, since: float, heard: dict[Any, dict[str, Any]],
            record: dict[str, Any] | None) -> dict[str, Any] | None:
    """The meeting once the ground has said it is over, or as it last stood."""
    began = time.monotonic()
    while record is not None and record.get("open") and time.monotonic() - began < CLOSE_WAIT_S:
        time.sleep(0.05)
        record = _latest(app, tool, since, heard, record)
    return record


def _carried(app: Any) -> dict[str, Any]:
    """What the person carries now: from the room's last reply, or asked."""
    carried = (app.live.session.state or {}).get("carried")
    if isinstance(carried, dict):
        return carried
    try:
        return (app.live.act({"session": app.live.session.id, "op": "ground_work"}) or {}
                ).get("carried") or {}
    except Exception:
        return {}


def _said(record: dict[str, Any] | None, use: dict[str, Any], carried_kg: float) -> str:
    """What came of it, in plain words."""
    if record is None:
        return "The swing met no ground."
    kind = str(record.get("kind") or "")
    ground = str(record.get("ground") or "ground")
    if kind in ("stopped", "glanced", "not supported"):
        why = str(record.get("why") or f"it {kind} on the {ground}")
        return why[:1].upper() + why[1:] + ("" if why.endswith(".") else ".")
    loosened = record.get("loosened") or {}
    litres = 1000.0 * (float(loosened.get("sand_m3") or 0.0) + float(loosened.get("soil_m3") or 0.0))
    depth_cm = 100.0 * float(record.get("depth_m") or 0.0)
    if litres > 0.0:
        past = use["past"]
        return (f"{past[:1].upper()}{past[1:]} {litres:.1f} L of {ground} "
                f"({float(record.get('loosened_kg') or 0.0):.1f} kg): the point went "
                f"{depth_cm:.0f} cm in."
                + (f" You carry {carried_kg:.1f} kg of ground; H heaps it." if carried_kg > 0.05 else ""))
    if record.get("open"):
        return f"The point went {depth_cm:.0f} cm into the {ground}, and it is still in."
    return f"The point went {depth_cm:.0f} cm into the {ground}, and came out without breaking any loose."


def _detail(record: dict[str, Any] | None) -> str:
    """The engine's numbers behind it (ground-work-v1)."""
    if not record or record.get("closing_speed_m_s") is None:
        return ""
    return (f"It arrived at {float(record['closing_speed_m_s']):.1f} m/s; the ground took "
            f"{float(record.get('work_j') or 0.0):.1f} J, at most "
            f"{float(record.get('peak_force_n') or 0.0):.0f} N.")
