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
hand while the page keeps the room running. Default ground tools use the shared
short contact path in mcp/tool_gestures.py. Clicks are sequential and repeat
without a flourish or fixed recovery sleep. An explicit gesture="swing" retains
the historical full-swing experiment below. A profile controls bounded hand
wishes, never penetration, resistance, resource yield or learning evidence.

"""
from __future__ import annotations

import math
import json
import sys
import time
import threading
from contextlib import nullcontext
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mcp"))
import interaction_profiles  # noqa: E402
import tool_gestures
import resource_previews

import world_chat  # noqa: E402  where the person is, as the page says and the chat is told
import live_session

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
# A stroke has "reached" when the hand's TARGET is at its end, and the tool,
# which the bounded hand drags after it, is still on its way: a mattock the
# chat gave a 9.8 m/s swing was 0.76 m in the air when its stroke ended in
# 0.28 s. The MCP's trial plays 0.5 s past a swing and 0.3 s past a pry before
# it reads what the ground did; so is waited here for a meeting, and for a pry
# to settle.
MEET_WAIT_S = 0.6
PRY_SETTLE_S = 0.3
# After a fresh lift/turn/lower, the most a contact tap waits for its point
# to come to rest at the ready clearance before it starts anyway.
READY_REST_S = 1.0
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
    holding = live_session.current_hand(session).get("holding") if session else None
    if not holding:
        return None
    return next((p for p in (app.room.spec.get("interactions") or [])
                 if p.get("template") == "swing-and-lever" and p.get("tool") == holding), None)


def resolve(app: Any, body: dict[str, Any]) -> dict[str, Any]:
    result = _resolve(app, body)
    result['feedback'] = resource_previews.tool_feedback(result)
    return result


def _resolve(app: Any, body: dict[str, Any]) -> dict[str, Any]:
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
                           "gesture": use["gesture"], "cadence_hz": use["cadence_hz"],
                           "ring": None, "target": None}
    if body.get('target_name') is not None:
        return _resolve_object(app,body,profile,use,out)
    carried = _carried(app)
    import world_goods
    piles = world_goods.auto_piles_enabled(app) and any(float(carried.get(s+'_m3') or 0)>0 for s in ('sand','soil','rock'))
    if (float(carried.get("limit_kg") or 0.0) > 0
            and float(carried.get("available_kg", 1.0)) <= 0.0005 and not piles):
        out["reason"] = "Load full · digging stopped. Point at clear ground and press H to heap carried sand or soil."
        out["carried"] = carried
        return out
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
    if use.get("gesture") == "contact" and cube_ground(app):
        # On cube ground a click strikes the cube at once (_strike_cell): no
        # swing has to land, so any cube within reach of the hand will do,
        # not only the 1.15 to 2 m band a pick comes down in (the owner,
        # 2026-10-04: "why can't I use the pickaxe on most areas?").
        least, most = CUBE_REACH_M
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
    runs = survey.get('runs') or []
    out['target']['material'] = runs[-1]['material'] if runs else surface
    point=_native_point(app,profile['tool'])
    out['gather']=resource_previews.ground_tool(survey,use,float((point or {}).get('length_m',.2)))
    if point is None:
        out['gather'].update(materials=[],state='unavailable',label='No attached tool point')
        ring['state']='no'
        out['reason']='This tool has no connected working point. Open it in Lab to inspect the head and handle.'
        return out
    if use['gesture']=='contact':
        if point and all(k in point for k in ('tip_local','grip_local','pointing_local')):
            out['ready']=tool_gestures.ready_pose(point,out['target']['at_m'],eyes)
    out["enabled"] = True
    if wet > WET_M:
        ring["state"] = "warn"
        out["reason"] = "Under water: wet ground is not modelled, and the engine will say so."
    elif surface == "rock" or cover < BARE_ROCK_M:
        ring["state"] = "warn"
        out["target"]["ground"] = "rock"
        out["reason"] = "Bare rock: a point no harder than the rock stops on it."
    return out


def _resolve_object(app,body,profile,use,out):
    """Recast the current native sight line; client names/points grant no contact."""
    out.update(label='Strike',gesture='object-contact',damage='Native joints',
               internal_fracture_supported=False,source_parts=list(profile.get('parts') or [profile['tool']]))
    name=body.get('target_name')
    if not isinstance(name,str) or not name or len(name.encode('utf-8'))>160:
        out['reason']='Aim at an item in the world.'
        return out
    person=world_chat.where_the_person_is(body.get('person'))
    if not person or not person.get('eyes_m') or not person.get('look_direction'):
        out['reason']='The page did not say where you are looking.'
        return out
    eyes=person['eyes_m'];direction=person['look_direction']
    session=app.live.session
    hit=app.live.act({'session':session.id,'op':'pick','from':eyes,'dir':direction,
                      'max_m':40,'past_held':True})
    if not hit.get('hit') or hit.get('name')!=name or _point(hit.get('point_m')) is None:
        out['reason']='The target moved or is behind something. Aim again.'
        return out
    at=_point(hit['point_m']);distance=math.dist(at,eyes)
    out['target']={'kind':'object','name':name,'at_m':at,'distance_m':distance,
                   'direction':direction}
    least,most=use['reach_m']
    if not least<=distance<=most:
        out['reason']='Move closer.' if distance>most else 'Step back.'
        return out
    point=_native_point(app,profile['tool'])
    if not point or not all(k in point for k in ('tip_local','grip_local','pointing_local')):
        out['reason']='No connected working point. Inspect the head and handle in Lab.'
        return out
    out['ready']=tool_gestures.ready_pose(point,at,eyes,direction)
    out['enabled']=True
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
                "done": [], "carried": said.get("carried") or _carried(app)}
    session = app.live.session
    actor = getattr(getattr(session, "_actor_local", None), "actor", "")
    busy_players = session.__dict__.setdefault("tool_busy_players", set()) if actor else set()
    profile = profile_held(app)
    use = interaction_profiles.tool_use(profile)
    tool = profile["tool"]
    eyes = [float(v) for v in world_chat.where_the_person_is(body.get("person"))["eyes_m"]]
    shoulder = [eyes[0], eyes[1] - SHOULDER_BELOW_EYES_M, eyes[2]]
    at = said["target"]["at_m"]
    heard: dict[Any, dict[str, Any]] = {}
    progress_rows={}

    def listen(_session: Any, reply: Any) -> None:
        for record in (reply or {}).get("ground_work") or []:
            if isinstance(record, dict) and record.get("tool", tool) == tool:
                heard[(record.get("point"), record.get("at_s"))] = record
                if actor and record.get('open') is False:
                    with use_lock:
                        progress_rows[(record.get('point'),record.get('at_s'))]=record
                        while len(progress_rows)>64:progress_rows.pop(next(iter(progress_rows)))

    listeners = getattr(app, "reply_listeners", None)
    use_lock=session.__dict__.setdefault('tool_use_lock',threading.Lock())
    with use_lock:
        busy=actor in busy_players if actor else getattr(session,'tool_busy',False)
        if busy:
            return {'action':label,'refused':'The hand is still busy with the last use.','done':[]}
        if actor: busy_players.add(actor)
        else: session.tool_busy=True
        if actor:session.__dict__.setdefault('tool_feedback',{})[actor]=progress_rows
    if listeners is not None:
        listeners.append(listen)
    done: list[str] = []
    record: dict[str, Any] | None = None
    short: str | None = None
    try:
        if said.get('gesture')=='object-contact':
            return _object_contact(app,said,use,tool,eyes,note)
        if use['gesture']=='contact':
            struck=_strike_cell(app,said,use,tool,heard,note,eyes)
            if struck is not None:return struck
            return _contact(app,said,use,tool,eyes,heard,note)
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
        waited = time.monotonic()
        while record is None and time.monotonic() - waited < MEET_WAIT_S:
            time.sleep(0.03)
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
                time.sleep(PRY_SETTLE_S)
                record = _latest(app, tool, since, heard, record)
                done.append(f"pried it: {record.get('kind')}, the stroke {ended}")
            if record.get("open"):
                grip = _grip(session)
                if grip is not None:
                    done.append(f"drew it out: the stroke {_pull(app, grip)}")
            record = _closed(app, tool, since, heard, record)
    finally:
        with use_lock:
            if actor:
                busy_players.discard(actor)
                session.tool_feedback.pop(actor,None)
            else: session.tool_busy = False
        if listeners is not None and listen in listeners:
            listeners.remove(listen)
    carried = _carried(app)
    kg = sum(float(carried.get(k) or 0.0) for k in ("soil_kg", "sand_kg"))
    return {"action": label, "did": [label], "done": done,
            "said": short if record is None and short else _said(record, use, kg),
            "detail": _detail(record), "result": record, "carried": carried,
            "repeat": use["repeat"]}


def feedback(app,actor):
    """Transient native receipts for this authenticated player's active use.
    A clock reader may consume the original native packet before the browser.
    Retain bounded display feedback; it grants neither inventory nor evidence.
    """
    session=app.live.session
    if session is None:return []
    with session.__dict__.setdefault('tool_use_lock',threading.Lock()):
        if actor not in getattr(session,'tool_busy_players',set()):return []
        return list((getattr(session,'tool_feedback',{}).get(actor) or {}).values())


def _object_contact(app,said,use,tool,eyes,note):
    """One short native push and withdrawal. No scripted damage or material yield."""
    session=app.live.session;target=said['target'];name=target['name']
    source=set(said.get('source_parts') or [tool])
    joints=app.live.act({'session':session.id,'op':'joints'}).get('joints') or []
    # A hit can fail a downstream connection in the same native assembly.
    # Follow the admitted graph before the stroke, not just the hit body.
    neighbors={}
    for joint in joints:
        a,b=joint.get('a'),joint.get('b')
        if joint.get('attached') and isinstance(a,str) and isinstance(b,str):
            neighbors.setdefault(a,set()).add(b);neighbors.setdefault(b,set()).add(a)
    target_parts=set();pending=[name]
    while pending:
        part=pending.pop()
        if part in target_parts:continue
        target_parts.add(part);pending.extend(neighbors.get(part,set())-target_parts)
    relevant={j['id'] for j in joints if j.get('attached') and
              (j.get('a') in source or j.get('b') in source or
               j.get('a') in target_parts or j.get('b') in target_parts)}
    impacts=[];parted={};overflow=False;seen_impacts=set()
    def listen(_session,reply):
        nonlocal overflow
        for index,event in enumerate((reply or {}).get('impacts') or []):
            if event.get('struck')==name and event.get('by') in source:
                # Reads can repeat the same native frame. The array index
                # preserves separate identical contacts within that frame.
                key=(reply.get('t'),index,json.dumps(event,sort_keys=True))
                if reply.get('t') is not None and key in seen_impacts:continue
                if len(impacts)<128:
                    impacts.append({**event,'at_s':reply.get('t')});seen_impacts.add(key)
                else: overflow=True
        for joint in (reply or {}).get('joints') or []:
            if joint.get('id') in relevant and joint.get('attached') is False and joint.get('parted_because'):
                parted[joint['id']]=dict(joint)
    listeners=getattr(app,'reply_listeners',None)
    if listeners is not None: listeners.append(listen)
    began=float(session.state.get('t') or 0)
    work_before=float(live_session.current_hand(session).get('work_j') or 0)
    ready=said['ready'];direction=target['direction'];done=[];phase='ready'
    def finish(refused=None):
        # Preparation can itself separate a real connection. Keep its work,
        # clock and failure history even when the selected target was not hit.
        listen(session,app.live.act({'session':session.id,'op':'joints'}))
        hand=live_session.current_hand(session)
        connected=hand.get('holding')==tool and _native_point(app,tool) is not None
        complete=not overflow and not hand.get('stroking')
        tool_failed=[j['id'] for j in parted.values() if j.get('a') in source or j.get('b') in source]
        target_failed=[j['id'] for j in parted.values() if j.get('a') in target_parts or j.get('b') in target_parts]
        outcome=('tool-and-target-connections-failed' if tool_failed and target_failed else
                 'tool-connection-failed' if tool_failed else
                 'target-connection-failed' if target_failed else 'contact-only' if impacts else 'no-contact')
        result={'schema':'banjo.object-strike.v1','target':name,'tool':tool,
                'from_s':began,'to_s':float(session.state.get('t') or began),
                'hand_work_j':float(hand.get('work_j') or 0)-work_before,
                'impacts':impacts,'parted_joints':list(parted.values()),'phase':phase,
                'outcome':outcome,'tool_connections_failed':tool_failed,'target_connections_failed':target_failed,
                'complete':complete,'working_point_connected':connected,
                'internal_fracture_supported':False,'wear_supported':False}
        said_result={'tool-and-target-connections-failed':'Tool and target connections failed.',
                     'tool-connection-failed':'Tool connection failed. Inspect it in Lab.',
                     'target-connection-failed':'Target connection failed.',
                     'contact-only':f'Hit {name}. No connection failure detected.',
                     'no-contact':'No contact with the selected item.'}[outcome]
        answer={'action':'Strike','did':['Strike'] if impacts or target_failed else [],'done':done,'said':said_result,
                'detail':'Internal fracture from held strikes is not available yet.',
                'result':result,'carried':_carried(app),
                'repeat':bool(not refused and use['repeat'] and connected and impacts and complete),
                'gesture':'object-contact','rest_hand_m':_grip(session)}
        if refused: answer['refused']=refused
        return answer
    try:
        # A wish, never a placement. The actor's normal world clock moves the
        # actual head/handle and can refuse readiness if an obstacle stops it.
        grip=_grip(session)
        if grip is not None and math.dist(grip,ready['hand'])>.1:
            point=_native_point(app,tool)
            if not point: return finish('The working point is disconnected. Inspect the tool in Lab.')
            survey=(app.live.act({'session':session.id,'op':'survey',
                                  'at':[point['tip'][0],point['tip'][2]]}) or {}).get('survey') or {}
            floor=survey.get('ground_m',survey.get('floor_m'))
            if floor is not None and point['tip'][1]<float(floor)+.45:
                phase='lift'
                high=[grip[0],grip[1]+.6,grip[2]]
                started=app.live.act({'session':session.id,'op':'stroke','path':[grip,high],
                    'speed_m_s':2.,'accel_m_s2':8.,'lead_m':tool_gestures.LEAD_M,
                    'give_up_s':2.,'let_go':False})
                done.append('lift: '+_stroke(app,started=bool(started.get('stroking'))))
                if live_session.current_hand(session).get('holding')!=tool:
                    return finish('The tool is no longer in your hand.')
                lifted=_native_point(app,tool)
                if not lifted:
                    return finish('The working point disconnected while lifting. Inspect the tool in Lab.')
                if lifted['tip'][1]<float(floor)+.45:
                    return finish('The tool cannot lift clear of the floor. Move to a clear spot.')
                grip=_grip(session)
            phase='ready'
            # Pickup can start far from the working pose. Move the wish along
            # a bounded path instead of giving idle feedback a large jump.
            # Turn the tool at a standoff behind the ready pose and come in
            # along the strike line: turning or sliding it beside the target
            # swept the head through it, so the strike was spent before it
            # began, depending only on how the clock fell.
            standoff=[ready['hand'][i]-tool_gestures.STANDOFF_M*direction[i] for i in range(3)]
            if math.dist(grip,standoff)>.02:
                started=app.live.act({'session':session.id,'op':'stroke','path':[grip,standoff],
                    'speed_m_s':2.,'accel_m_s2':8.,'lead_m':tool_gestures.LEAD_M,
                    'give_up_s':2.,'let_go':False})
                done.append('standoff: '+_stroke(app,started=bool(started.get('stroking'))))
                grip=_grip(session) or standoff
            app.live.act({'session':session.id,'op':'step','dt':1/240,'n':1,
                          'hand':grip,'hand_q':ready['hand_q']})
            # The wrist turns a heavy head slowly. Let it finish turning here,
            # clear of the target, so the last move is straight along the line.
            turn_from=float(session.state.get('t') or 0);wall=time.monotonic()+30
            while float(session.state.get('t') or 0)-turn_from<2 and time.monotonic()<wall:
                point=_native_point(app,tool)
                if not point:
                    return finish('The working point disconnected while turning. Inspect the tool in Lab.')
                if sum(point['pointing'][i]*direction[i] for i in range(3))>.98: break
                time.sleep(.005)
            grip=_grip(session) or grip
            started=app.live.act({'session':session.id,'op':'stroke','path':[grip,ready['hand']],
                'speed_m_s':2.,'accel_m_s2':8.,'lead_m':tool_gestures.LEAD_M,
                'give_up_s':2.,'let_go':False})
            done.append('ready: '+_stroke(app,started=bool(started.get('stroking'))))
        app.live.act({'session':session.id,'op':'step','dt':1/240,'n':1,
                      'hand':ready['hand'],'hand_q':ready['hand_q']})
        wanted=[target['at_m'][i]-tool_gestures.CLEARANCE_M*direction[i] for i in range(3)]
        # Two seconds of WORLD time, not wall time: a loaded machine steps the
        # world slower, and a wall deadline then refused a reachable contact.
        # The wall cap only stops a wait on a clock that has stopped.
        settle_from=float(session.state.get('t') or 0);wall=time.monotonic()+30
        while float(session.state.get('t') or 0)-settle_from<2 and time.monotonic()<wall:
            if live_session.current_hand(session).get('holding')!=tool:
                return finish('The tool is no longer in your hand.')
            point=_native_point(app,tool)
            if not point:
                return finish('The working point disconnected while positioning. Inspect the tool in Lab.')
            # Reach and aim only: the strike itself starts at rest from the
            # standoff below, and a head touching the target never rests here.
            if (math.dist(point['tip'],wanted)<.035 and
                sum(point['pointing'][i]*direction[i] for i in range(3))>.98): break
            time.sleep(.005)
        else:
            return finish('The tool cannot reach that contact from here.')
        # A blocked solid should receive a brief press, not a one-second hold.
        # Cadence sets the bounded wish duration, never force or contact outcome.
        duration=.5/use['cadence_hz']
        # Reach is confirmed at the ready point. Draw back along the line to
        # the standoff and strike from there: started at rest 6 cm short of
        # the target the head could not reach swing speed, so a strike was a
        # push, and only a head still moving from its approach ever broke
        # anything -- by chance of the clock.
        grip=_grip(session)
        ready_grip=list(grip)
        back=[grip[i]-tool_gestures.STANDOFF_M*direction[i] for i in range(3)]
        started=app.live.act({'session':session.id,'op':'stroke','path':[grip,back],
            'speed_m_s':1.,'accel_m_s2':8.,'lead_m':tool_gestures.LEAD_M,
            'give_up_s':2.,'let_go':False})
        done.append('draw back: '+_stroke(app,started=bool(started.get('stroking'))))
        rest_from=float(session.state.get('t') or 0);wall=time.monotonic()+30
        while float(session.state.get('t') or 0)-rest_from<1 and time.monotonic()<wall:
            if math.hypot(*(live_session.current_hand(session).get('grip_velocity_m_s') or [0,0,0]))<.05:break
            time.sleep(.005)
        if live_session.current_hand(session).get('holding')!=tool:
            return finish('The tool is no longer in your hand.')
        if _native_point(app,tool) is None:
            return finish('The working point disconnected while drawing back. Inspect the tool in Lab.')
        phase='press'
        grip=_grip(session) or back
        into=[ready_grip[i]+(tool_gestures.CLEARANCE_M+tool_gestures.BITE_M)*direction[i] for i in range(3)]
        # give_up_s is the stroke's whole time: the run-up, with the heavy head
        # trailing the hand (twice the hand's own time, and its acceleration),
        # then the brief press.
        reach=2*math.dist(grip,into)/max(.1,use['swing']['speed_m_s'])+.25
        started=app.live.act({'session':session.id,'op':'stroke','path':[grip,into],
            'speed_m_s':use['swing']['speed_m_s'],'accel_m_s2':tool_gestures.ACCEL_M_S2,
            'lead_m':tool_gestures.LEAD_M,'give_up_s':duration+reach,'let_go':False})
        if note: note(app,started)
        done.append('press: '+_stroke(app,started=bool(started.get('stroking'))))
        grip=_grip(session)
        hand=live_session.current_hand(session)
        if (grip is not None and hand.get('holding')==tool and not hand.get('stroking')
                and _native_point(app,tool) is not None):
            phase='withdraw'
            back=[grip[i]-tool_gestures.CLEARANCE_M*direction[i] for i in range(3)]
            started=app.live.act({'session':session.id,'op':'stroke','path':[grip,back],
                'speed_m_s':use['swing']['speed_m_s'],'accel_m_s2':tool_gestures.ACCEL_M_S2,
                'lead_m':tool_gestures.LEAD_M,'give_up_s':duration,'let_go':False})
            done.append('withdraw: '+_stroke(app,started=bool(started.get('stroking'))))
        return finish()
    finally:
        if listeners is not None and listen in listeners: listeners.remove(listen)


def _native_point(app,tool):
    session=app.live.session
    # The point and the handle pose must describe one native instant. A clock
    # step between them turns an old renderer pose into a wrong grip frame.
    with getattr(app.live,'_lock',nullcontext()):
        points=app.live.act({'session':session.id,'op':'tool_points'}).get('tool_points') or []
        point = next((p for p in points if (p.get('grip_body') or p.get('body'))==tool and
                      p.get('attached',True) and p.get('grip_connected',True)),None)
        if point and all(_point(point.get(k)) is not None for k in ('tip','grip','pointing')):
            poses=app.live.act({'session':session.id,'op':'poses'})
            pose = next((b for b in poses.get('bodies') or [] if b.get('name') == tool),None)
            if pose:
                hand=live_session.current_hand(session)
                grip=_point(hand.get('grip_m')) if hand.get('holding')==tool else None
                # The player can take a tool at a different point from its
                # authored grip. The bounded controller pulls there, so its
                # readiness frame must use that actual native hand position.
                point = {**point, **tool_gestures.local_frame(point['tip'],grip or point['grip'],point['pointing'],
                    pose['position_m'],pose['orientation_wxyz'])}
        return point


# How near and how far a click strikes a cube on cube ground, level from the eyes.
CUBE_REACH_M = (0.25, 4.0)
# How far back towards the eyes a struck point is taken before its column is
# found (_strike_cell): far less than a cube, far more than rounding.
STRIKE_BACK_M = 0.002


def cube_ground(app):
    """Whether the open room's ground is 25 cm cubes (the 'columns' surface)."""
    session=getattr(getattr(app,'live',None),'session',None)
    spec=getattr(session,'room_spec',None) or getattr(getattr(app,'room',None),'spec',None) or {}
    return isinstance(spec,dict) and (spec.get('terrain') or {}).get('surface')=='columns'


def _strike_cell(app,said,use,tool,heard,note,eyes=None):
    """On cube ground a swing's outcome is decided, not worked through: a whole
    cube of soil or sand, a share of clay or rock (ToolTerrain::strikeCell). So
    it is done at once, in one engine call, rather than with the hand's lift,
    turn, lower, settle and stroke -- 0.5 to 3 s a click that the owner felt as
    lag (2026-10-04). None where the ground is not cubes: swing it instead."""
    session=app.live.session
    if not cube_ground(app):
        return None
    since=float(session.state.get('t') or 0)
    if note:note(app,{'t':since})
    at=[float(v) for v in said['target']['at_m']]
    # A click that meets the wall of a hole takes the hole one cube deeper, not
    # the wall. Once a hole is a cube deep the line of sight into it meets its
    # far wall, exactly on the face two columns share, and the engine rounds
    # such a point to the column on the +x or +z side: looking east or south
    # it took the cube beyond the hole, so the hole grew away from the player
    # instead of down, and looking west or north it went down (the owner,
    # 2026-10-04: "holes that didn't deepen"; tests/player_regression_tests.py
    # digs facing east, south and north). Taken a hair back towards the eyes, the point
    # is in the column the line of sight came down into, whichever way it
    # faces; a point on top of a cube stays in that cube.
    if isinstance(eyes,(list,tuple)) and len(eyes)==3:
        dx,dz=at[0]-float(eyes[0]),at[2]-float(eyes[2])
        level=math.hypot(dx,dz)
        if level>1e-6:
            at[0]-=dx/level*STRIKE_BACK_M
            at[2]-=dz/level*STRIKE_BACK_M
    # Straight to the engine, as the hand's own commands go: not a /api/live/act
    # op a page could call without this route's reach and readiness checks.
    session.send(op='strike-cell',at_m=at)
    record=_latest(app,tool,since,heard)
    if record is None or record.get('kind')=='not supported':return None
    carried=_carried(app);kg=sum(float(carried.get(k) or 0) for k in ('soil_kg','sand_kg'))
    return {'action':said['label'],'did':[said['label']],'done':['struck the cube'],
            'said':_said(record,use,kg),'detail':_detail(record),'result':record,
            'carried':carried,'repeat':use['repeat'],'gesture':'contact','struck':True,
            'rest_hand_m':_grip(session),
            'results':[r for r in heard.values() if r.get('open') is False
                and float(r.get('at_s',since) or since)>=since-.05]}


def _contact(app,said,use,tool,eyes,heard,note):
    session=app.live.session
    # Lifting/turning/lowering are part of this native attempt. A meeting can
    # begin during readiness and close during the stroke; its entry timestamp
    # must not be discarded by starting the receipt window after readiness.
    since=float(session.state.get('t') or 0)
    ready=said.get('ready')
    if not ready:
        return {'action':said['label'],'refused':'This tool has no attached native point and grip frame','done':[]}
    at=said['target']['at_m']
    point=_native_point(app,tool)
    path=tool_gestures.lift_path(_grip(session),point['tip'],point['pointing'],at) if point else None
    if path:
        app.live.act({'session':session.id,'op':'stroke','path':path,'speed_m_s':2.0,
            'accel_m_s2':tool_gestures.ACCEL_M_S2,'lead_m':tool_gestures.LEAD_M,
            'give_up_s':2.0,'let_go':False})
        _stroke(app)
    point=_native_point(app,tool)
    lowered=False
    if point and point['pointing'][1]>-.98:
        # Turn above the terrain before lowering. Rotating and translating to
        # near-ground ready simultaneously can sweep the point through soil.
        high=[*ready['hand']];high[1]+=.6
        app.live.act({'session':session.id,'op':'stroke','path':[_grip(session),high],
            'speed_m_s':1.0,'accel_m_s2':8.0,'lead_m':tool_gestures.LEAD_M,
            'give_up_s':2.0,'let_go':False})
        _stroke(app)
        app.live.act({'session':session.id,'op':'step','dt':1/240,'n':1,
            'hand':high,'hand_q':ready['hand_q']})
        # Two seconds of world time to turn, as for the contact below: on a
        # loaded machine the world steps slower and a wall deadline refused.
        turn_from=float(session.state.get('t') or 0);wall=time.monotonic()+30
        while float(session.state.get('t') or 0)-turn_from<2 and time.monotonic()<wall:
            point=_native_point(app,tool)
            if (point and point['pointing'][1]<-.98 and
                math.dist(point['tip'],[at[0],at[1]+tool_gestures.CLEARANCE_M+.6,at[2]])<.035):break
            time.sleep(.005)
        else:
            return {'action':said['label'],'refused':'The tool is still turning into position','done':[]}
        app.live.act({'session':session.id,'op':'stroke','path':[_grip(session),ready['hand']],
            'speed_m_s':1.0,'accel_m_s2':8.0,'lead_m':tool_gestures.LEAD_M,
            'give_up_s':2.0,'let_go':False})
        _stroke(app)
        lowered=True
    # Establish a bounded wish once. The world clock, not this handler, moves
    # the tool to it. Do not insert settling sleeps between established taps.
    app.live.act({'session':session.id,'op':'step','dt':1/240,'n':1,
                  'hand':ready['hand'],'hand_q':ready['hand_q']})
    began=time.monotonic()
    point=_native_point(app,tool)
    while point and time.monotonic()-began<2:
        tip=point.get('tip') or []
        direction=point.get('pointing') or []
        # A lowering stroke "reaches" when the hand's target does; a heavy
        # head is still travelling (MEET_WAIT_S notes above) and sags below
        # the ready clearance before the bounded hand lifts it back. A contact
        # stroke started then begins centimetres above the soil, arrives
        # slowly and cannot work the ground. After a fresh lowering, give the
        # point up to READY_REST_S to rest at its ready clearance, as
        # established taps start; then proceed as before rather than refuse.
        ready_at=[at[0],at[1]+tool_gestures.CLEARANCE_M,at[2]]
        if (len(tip)==3 and len(direction)==3 and direction[1]<-.98
            and math.dist(tip,ready_at)<.035
            and (not lowered or time.monotonic()-began>READY_REST_S
                 or (math.dist(tip,ready_at)<.01 and _still(app,tool)))): break
        time.sleep(.005);point=_native_point(app,tool)
    else:
        return {'action':said['label'],'refused':'The tool is still moving into position','done':[]}
    grip=_grip(session)
    # The cube this swing is for: on cube ground, the one taken out.
    session.send(op='ground-aim',at_m=[float(v) for v in at])
    started=app.live.act({'session':session.id,'op':'stroke',
        'path':tool_gestures.contact_path(grip,use,eyes,at),
        'speed_m_s':use['swing']['speed_m_s'],'accel_m_s2':tool_gestures.ACCEL_M_S2,
        'lead_m':tool_gestures.LEAD_M,'give_up_s':1.0,'let_go':False})
    if note: note(app,started)
    ended=_stroke(app)
    record=_closed(app,tool,since,heard,_latest(app,tool,since,heard))
    done=[f'contact stroke: {ended}']
    if record and record.get('open') and record.get('tool_whole',True):
        grip=_grip(session)
        if grip is not None:
            done.append(f'withdrew the point: {_pull(app,grip)}')
            record=_closed(app,tool,since,heard,_latest(app,tool,since,heard,record))
    carried=_carried(app);kg=sum(float(carried.get(k) or 0) for k in ('soil_kg','sand_kg'))
    return {'action':said['label'],'did':[said['label']], 'done':done,
            'said':_said(record,use,kg),'detail':_detail(record),'result':record,
            'carried':carried,'repeat':use['repeat'],'gesture':'contact','rest_hand_m':_grip(session),
            'results':[r for r in heard.values() if r.get('open') is False
                and float(r.get('at_s',since) or since)>=since-.05]}


def _still(app: Any, tool: str) -> bool:
    """Whether the held tool is moving slower than STILL_M_S now."""
    body = next((b for b in (app.live.session.state or {}).get("bodies") or []
                 if b.get("name") == tool), None)
    speed = _point((body or {}).get("velocity_m_s"))
    return speed is None or math.sqrt(sum(v * v for v in speed)) < STILL_M_S


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


def _stroke(app: Any, started: bool = False) -> str:
    """Wait -- while the page keeps the room running -- for the hand's stroke to
    end, and say how: reached, blocked, gave up, cancelled; with how long it was
    waited for, and "never seen going" when the room never said it was under
    way (the end then said may be the last stroke's)."""
    began = time.monotonic()
    while time.monotonic() - began < STROKE_LIMIT_S:
        hand = live_session.current_hand(app.live.session)
        waited = time.monotonic() - began
        if hand.get("stroking"):
            started = True
        elif hand.get("stroke_ended") and (started or waited > STROKE_UNSEEN_S):
            return f"{hand['stroke_ended']} after {waited:.2f} s" + ("" if started else ", never seen going")
        time.sleep(0.02)
    return f"ran out of time after {STROKE_LIMIT_S:g} s"


def _grip(session: Any) -> list[float] | None:
    return _point(live_session.current_hand(session).get("grip_m"))


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
    point = next((p for p in points.get("tool_points") or [] if (p.get('grip_body') or p.get("body")) == tool), None)
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
    carried = live_session.current_carried(app.live.session)
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
    if kind == "breaking rock":
        # A share of the cube per swing (ToolTerrain::strikeCell): say how far.
        share = float(record.get("broken_share") or 0.0)
        ground_word = ground[:1].upper() + ground[1:]
        return (f"{ground_word}: {share:.0%} broken through. Keep striking the same cube: "
                f"it comes out whole when it is through.")
    loosened = record.get("loosened") or {}
    litres = 1000.0 * (float(loosened.get("sand_m3") or 0.0) + float(loosened.get("soil_m3") or 0.0))
    depth_cm = 100.0 * float(record.get("depth_m") or 0.0)
    if litres > 0.0:
        # Said with the profile's own word, whatever it is: "dug", or the chat's
        # "broke up the soil".
        past = use["past"]
        volume=f'{litres*1000:.0f} mL' if litres<.1 else f'{litres:.1f} L'
        mass=float(record.get('loosened_kg') or 0.0)
        weight=f'{mass*1000:.0f} g' if mass<1 else f'{mass:.1f} kg'
        return (f"{past[:1].upper()}{past[1:]}: {volume} of {ground} "
                f"({weight}) came loose; the point went "
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
