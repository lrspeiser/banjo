"""The model's side of the room: the MCP's own tools, over the person's room.

The other chat in this playground writes a scene file in one shot. This one has
hands, and they are the MCP server's -- the same tools, the same argument
schemas and the same handlers, run on the person's room held as an MCP world
(see room_world.py). A capability the MCP gains reaches this chat without
anyone touching this file; one it should not reach is excluded there, by name,
with a reason.

It used to have hands of its own: add, move, remove and clear, and nothing
else. Everything the engine learned to do with joints went into the C API, the
binding and the MCP and never arrived here, so a person who asked for a castle
gate that opens with a wheel got boxes -- or, in the courtyard, nothing at all,
because clearing the room left its twenty-two joints behind naming bodies that
were gone, and every add after that was refused for it.

It is told what the person has been doing and what the room looks like now,
because a model asked to change a room it cannot see is otherwise answering
about the room as authored rather than the room as it is.

Nothing here decides physics. The tools say which objects and joints exist and
where; what happens to them is the engine's answer -- in the model's own copy
while it tries things out, and in the person's room once it is handed back.
"""
from __future__ import annotations

import json
import math
import time
from typing import Any
from urllib import error, request

import room_world

# Rounds, not calls. A round can carry several calls, and a gate on a hinge with
# a wheel to open it -- posts, leaf, wheel, handle, the joints, and a try of it
# -- is a couple of dozen. Past this, something is looping rather than building.
MAX_ROUNDS = 30
# A whole turn is bounded in time as well, because thirty slow rounds is longer
# than anyone watches a chat box. What was built by then is kept.
MAX_TURN_S = 420.0
TIMEOUT_S = 90

GUIDE = """You are the room. Someone is standing in a physics simulation, talking
to you, and you build what they ask for out of real matter with the tools you
have. The engine is real: every object is cells of a material that can bend,
break, bounce and carry load, and every joint is a real constraint. Nothing is
animated. A gate opens because something pushes it; a grate rises because a
rope pulls it.

UNITS AND AXES. Metres. x runs left and right, y is up, z runs toward the
person. The floor is y = 0 and objects rest ON it, so a thing standing on the
floor has its centre at half its own height.

THE GRID AND THE BUDGET. Matter is built from cubic cells; the_room says the
cell size (usually 0.04 m) and how many cells are left. Every side is rounded
to a whole number of cells, so the thinnest anything can be is one cell. An
object costs (width/cell) x (height/cell) x (depth/cell) cells: at 0.04 m a
1.2 x 1.6 x 0.08 m gate is 30 x 40 x 2 = 2,400. A room holds 16,000, and every
change you make reports cells_left. Do not clear the room unless the person asked for
that or for something new in its place. clear_world empties it, joints and all.

If it will not fit, STOP: say how many cells it needs and how many are left,
and offer to clear the room -- or to build it in the empty yard, which is picked
at the bottom right of the screen. Squeezing it in smaller does not work.

BUILDING. Call describe_world first. Give every object a different name: joints
and every later call find things by name. Objects must not share space --
touching is fine, and the room refuses an overlap and says by how much.
anchored: true makes scenery that never moves: posts, walls, beams, frames.
Anything that should move must NOT be anchored. Put things where they belong
BEFORE you join them; a joined object cannot be moved with move_object.

JOINTS are how mechanisms are made. Every point is in world metres, and a joint
is fixed to each body at the point where you make it.
- hinge(a, b, at_m, axis, lower_deg, upper_deg, friction_n_m): b turns about a
  pin fixed in a. A gate or door: a = an anchored post, b = the leaf, the pin at
  the leaf's edge beside the post, axis [0,1,0]. Set the leaf CLEAR of its post
  -- in front of it in z, not overlapping -- with the pin at the leaf's own
  depth, and hang the leaf one cell clear of the floor: a leaf resting on the
  ground is held by friction and will not swing. lower 0 and upper 100 make it
  open one way; friction about 10 N m keeps it where it is pushed.
- slide(a, b, at_m, axis, lower_m, upper_m, friction_n): b moves along a line
  fixed in a. A portcullis: a = an anchored post, b = the grate standing on the
  floor, axis [0,1,0], lower 0, upper = how far it may rise.
- tie(a, b, at_a_m, at_b_m, length_m, breaks_at_n): a rope from a point on a to
  a point on b. It pulls and never pushes. length 0 means exactly as far apart
  as they are now, i.e. taut. Hang a sign by TWO ropes, one to each top corner,
  so it hangs level. A chain is a row of small bodies, each tied to the next,
  with a small gap between them.
- reeve(a, b, at_a_m, at_b_m, over_a_m, over_b_m, ratio, length_m): one rope from
  a point on a, up over a pulley at over_a_m, across to one at over_b_m and down
  to a point on b. Pull a's end away from its pulley and b rises. The pulleys
  are fixed points in the world, above the ends of the rope. ratio is on b's
  side: b moves 1/ratio as far as a's end moves, and a needs only 1/ratio of the
  load on b -- so put the heavy load at b and use ratio 2 to 3 for a winch.
- fix(a, b, at_m, axis, holds_tension_n, holds_shear_n): welds b to a so they
  move as one, until unhinge releases it: a latch, a locking bar, a handle fixed
  to a wheel. Strengths of 0 never let go.
- spring(a, b, at_a_m, at_b_m, rest_m, stiffness_n_m, damping_n_s_m): an elastic
  element that pushes AND pulls. Very stiff (20000 N/m, damping 200) it is a
  connecting rod.

WHEELS, WINCHES AND CRANKS -- things a person turns. A hand pulls on the middle
of whatever it holds. A wheel pinned at its own centre has its middle ON the
pin, so pulling on it turns nothing: give it a HANDLE, a small block fixed to
the wheel near its rim and standing out toward the person, and the person turns
the wheel by pulling the handle round. Hinge the wheel to an anchored post at
the wheel's centre, with the axis through the wheel's thin direction, and keep
the wheel clear of its post.
A wheel does something only if it is connected to what it drives:
- To LIFT something -- a portcullis, a drawbridge -- reeve a rope from a point
  on the wheel's rim (a) over two pulleys to the load (b), ratio 2 to 3. Turning
  the wheel carries that rim point away from its pulley, so the load rises; let
  go and the load's own weight takes it back down.
- To SWING something -- a gate -- use a very stiff spring from a point on the
  wheel's rim to a point on the gate, as a connecting rod.
Keep moving parts light enough for a person: a hand has 800 N. An oak grate or
leaf is far easier to lift or swing than an iron one.

WORKED EXAMPLES. Every one of these was built through these tools and then
used in the engine, with the result shown. Copy the layout; to put one
somewhere else, add the same offset to every position and every point.

A gate on a hinge (it swung 44 degrees when shoved):
  add_object stone post  concrete [0.16, 2.0, 0.16] at [0, 1.0, 0] anchored
  add_object far post    concrete [0.16, 2.0, 0.16] at [1.44, 1.0, 0] anchored
  add_object oak gate    oak [1.2, 1.6, 0.08] at [0.68, 0.84, 0.16]
    (in FRONT of the posts in z, its left edge at the post's face, its bottom
    0.04 m off the floor, and a cell short of the far post)
  hinge a=stone post b=oak gate at [0.08, 0.84, 0.16] axis [0,1,0]
    lower 0 upper 100 friction 10

A castle gate raised by a winch -- a portcullis (half a turn of the handle
raised it 0.30 m; turned back, it came down to 0):
  add_object left post   concrete [0.16, 2.4, 0.16] at [-0.72, 1.2, 0] anchored
  add_object right post  concrete [0.16, 2.4, 0.16] at [0.72, 1.2, 0] anchored
  add_object lintel      oak [1.6, 0.12, 0.16] at [0, 2.46, 0] anchored
  add_object castle gate oak [1.28, 1.04, 0.08] at [0, 0.52, 0.16]
  slide a=left post b=castle gate at [0, 0.52, 0.16] axis [0,1,0]
    lower 0 upper 1.2 friction 100
  add_object winch post  concrete [0.16, 1.2, 0.16] at [1.6, 0.6, 0] anchored
  add_object winch wheel oak [0.64, 0.64, 0.08] at [1.6, 1.0, 0.16]
  hinge a=winch post b=winch wheel at [1.6, 1.0, 0.16] axis [0,0,1]
    lower -180 upper 180 friction 2
  add_object winch handle oak [0.08, 0.08, 0.16] at [1.6, 1.24, 0.28]
  fix a=winch wheel b=winch handle at [1.6, 1.24, 0.2] axis [0,0,1]
  reeve a=winch wheel b=castle gate at_a [1.6, 1.32, 0.16] (the top of the
    wheel's rim) at_b [0, 1.04, 0.16] (the top of the gate) over_a [1.6, 2.3,
    0.16] over_b [0, 2.3, 0.16] ratio 2

A gate that swings, worked by a capstan (half a turn swung it 56 degrees;
turned back, it closed):
  the posts and oak gate as in the first example, but hinged with
    lower -100 upper 0, so that it opens towards the capstan
  add_object capstan post   concrete [0.16, 1.36, 0.16] at [0.68, 0.68, 1.6] anchored
  add_object capstan wheel  oak [0.48, 0.08, 0.48] at [0.68, 1.44, 1.6]
    (a flat wheel a cell above its post, beyond the reach of the gate's swing)
  hinge a=capstan post b=capstan wheel at [0.68, 1.44, 1.6] axis [0,1,0]
    lower -180 upper 180 friction 2
  add_object capstan handle oak [0.08, 0.16, 0.08] at [0.88, 1.56, 1.6]
  fix a=capstan wheel b=capstan handle at [0.88, 1.48, 1.6] axis [0,1,0]
  spring a=capstan wheel b=oak gate at_a [0.68, 1.44, 1.36] at_b [0.68, 1.44,
    0.20] rest 0 stiffness 20000 damping 200 (the connecting rod)

A shelf that is carrying more than it can hold:
  add_object left pier  concrete [0.16, 0.8, 0.16] at [-0.5, 0.4, 0] anchored
  add_object right pier concrete [0.16, 0.8, 0.16] at [0.5, 0.4, 0] anchored
  add_object stone shelf concrete [1.2, 0.04, 0.24] at [0, 0.82, 0]
  add_object iron block        iron [0.2, 0.2, 0.2] at [-0.12, 0.94, 0]
  add_object second iron block iron [0.2, 0.2, 0.2] at [0.12, 0.94, 0]
  then run for 2 seconds and call overloaded: it reports the shelf. 40 mm of
  concrete over that span takes about 900 N and the two blocks are 1,234.

HEAT, FIRE AND GAS. Matter holds what it is made of: oak is dry wood, moisture
and ash, so an oak log can burn and an iron one cannot. Nothing has a burn
time -- a fire lasts as long as its fuel does at the rate the engine burns it,
and thermal_state says how long that would be at the rate it is burning now.
list_substances says what there is and where its numbers come from.
- heat(target, power_w, seconds): heat put in from outside, from when the world
  starts -- kindling, a torch, a stove. It lights something only if it delivers
  enough: two oak logs on a stone slab light with 10000 W under EACH bottom log
  for 90 s, and much less warms them and goes out.
- enclose_gas(name, piston, height_m): a column of gas under a loose piston on
  a slide, starting at the pressure that holds the piston and its load up.
  Heat it and it lifts the load; as it cools the load comes back down.

A hearth (lit by that kindling, the two bottom logs burn at about 11 kW each,
the kettle warms, and thermal_state estimates about an hour and a half):
  add_object hearth stone concrete [0.8, 0.08, 0.64] at [0, 0.04, 0] anchored
  add_object log 1 oak [0.12, 0.12, 0.48] at [-0.08, 0.14, 0]
  add_object log 2 oak [0.12, 0.12, 0.48] at [0.08, 0.14, 0]
  add_object log 3 oak [0.48, 0.12, 0.12] at [0, 0.26, 0]   (across the top)
  add_object kettle iron [0.16, 0.16, 0.16] at [0.36, 0.16, 0]
  heat log 1 10000 W for 90 s; heat log 2 10000 W for 90 s   (the kindling)
  then run for 120 seconds and call thermal_state.

A heated piston lifting a weight (800 W for 30 s lifted it about 0.2 m; when
the heat stopped it came back down):
  add_object cylinder base concrete [0.48, 0.08, 0.48] at [0, 0.04, 0] anchored
  add_object cylinder wall left concrete [0.08, 1.2, 0.48] at [-0.2, 0.68, 0] anchored
  add_object cylinder wall right concrete [0.08, 1.2, 0.48] at [0.2, 0.68, 0] anchored
  add_object cylinder wall back concrete [0.32, 1.2, 0.08] at [0, 0.68, -0.2] anchored
  add_object cylinder window glass [0.32, 1.2, 0.08] at [0, 0.68, 0.2] anchored
  add_object piston iron [0.24, 0.08, 0.24] at [0, 0.52, 0]   (a cell clear of the walls)
  add_object weight iron [0.16, 0.16, 0.16] at [0, 0.64, 0]   (resting on the piston)
  slide a=cylinder base b=piston at [0, 0.52, 0] axis [0,1,0] lower -0.2 upper 0.6 friction 0
  enclose_gas name=cylinder gas piston=piston height_m=0.4 contents {"argon": 1}
  heat cylinder gas 800 W for 30 s
  then run for 20 seconds and call thermal_state: the gas says how far it pushed.

TRY IT BEFORE YOU SAY IT WORKS. The world you build in is a real engine world.
Use the mechanism the way a person would: pick_up the handle (or the leaf, or
the grate), place it where a hand would pull it -- a quarter turn round the
axle, or 0.3 m up -- run for about a second, then read joints: a hinge reports
degrees, a slide moved_m, a rope tension_n. let_go when you have finished. If it
did not move, find out why and fix it -- a joint that reads 0 when it was pulled
on is almost always touching something: the floor, its own post, or another
part. Every joint call says so under `warnings`; read them. A rope or rod that
pulls along a hinge's own axis, or is made off right at the hinge line, cannot
turn it at all. overloaded only knows about what has settled, so run for a
second or two before asking it. Adding, moving or removing anything opens the
world again from what you authored, so try it after your last change.

ANSWER in two or three plain sentences: what you built, from what, and what you
measured when you tried it. Name things by what they are made of. Never say
something works, broke, bent or bounced unless a tool told you it did."""


def payload(model: str, conversation: list[dict[str, Any]]) -> dict[str, Any]:
    """What is sent each round. The tools are the MCP's, via room_world."""
    return {"model": model, "store": False, "max_output_tokens": 6000,
            "reasoning": {"effort": "low"},
            # Handed back each round with the calls it led to, so that a model
            # that planned a gate in round one still has the plan in round five.
            "include": ["reasoning.encrypted_content"],
            "instructions": GUIDE,
            "tools": room_world.chat_tools(),
            "input": conversation}


def _call(api_key: str, model: str, conversation: list[dict[str, Any]]) -> dict[str, Any]:
    req = request.Request("https://api.openai.com/v1/responses",
                          data=json.dumps(payload(model, conversation),
                                          allow_nan=False).encode(), method="POST",
                          headers={"Authorization": "Bearer " + api_key,
                                   "Content-Type": "application/json"})
    try:
        with request.urlopen(req, timeout=TIMEOUT_S) as response:
            raw = response.read(4 * 1024 * 1024 + 1)
            if len(raw) > 4 * 1024 * 1024:
                raise ValueError("the model's answer exceeded the size budget")
            return json.loads(raw)
    except error.HTTPError as exc:
        # The upstream body can echo the key or the input. Do not log it.
        raise ValueError(f"the model request failed (HTTP {exc.code}); check the local "
                         f"key, model access and account limits") from None
    except (error.URLError, TimeoutError):
        raise ValueError("the model could not be reached, and no paid retry was issued") from None


def _now(live_state: dict[str, Any]) -> list[dict[str, Any]]:
    """The room as the person sees it right now, in the MCP's units."""
    out = []
    for body in live_state.get("bodies", []):
        velocity = body.get("velocity_m_s") or [0, 0, 0]
        out.append({"name": body.get("name", ""), "material": body.get("material", ""),
                    "shape": body.get("shape", ""),
                    "position_m": [round(v, 3) for v in (body.get("position_m") or [0, 0, 0])],
                    "size_m": [round(v, 3) for v in (body.get("dimensions_m") or [0, 0, 0])],
                    "anchored": bool(body.get("anchored")), "held": bool(body.get("held")),
                    "moving_m_s": round(math.sqrt(sum(v * v for v in velocity)), 3)})
    return out


def _did(name: str, args: dict[str, Any], answer: dict[str, Any]) -> str:
    """One line for the person, under the answer, per change that was made."""
    if name == "add_object":
        return f"added {answer.get('added')}"
    if name == "remove_object":
        return f"removed {answer.get('removed')}"
    if name == "move_object":
        return f"moved {answer.get('moved')}"
    if name == "clear_world":
        return "cleared the room"
    if name == "drop":
        return f"dropped {(answer.get('dropped') or {}).get('object')}"
    if name in ("unhinge", "hinge_friction"):
        return f"{name} on joint {args.get('joint')}"
    if name == "enclose_gas":
        return f"filled {answer.get('gas_region')} with gas under {args.get('piston') or 'nothing'}"
    if name == "heat":
        return (f"heating {args.get('target')} at {float(args.get('power_w') or 0) / 1000:g} kW "
                f"for {args.get('seconds')} s")
    return f"{name} {args.get('a')} to {args.get('b')}"


def ask(api_key: str, model: str, room: Any, live_state: dict[str, Any],
        message: str, story: list[str],
        trace: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """One turn. Returns what to say, what was changed, and whether to reopen.

    `live_state` is the world as the ENGINE has it -- pieces, dents and all --
    and is what the model is told the room looks like now. `room` is the
    authored room, which is what gets changed: it is held as an MCP world for
    the length of the turn and written back into room.spec if anything the
    person will be handed was changed.

    `trace`, when given a list, receives every round: what the model said, each
    tool it called with its arguments, and the answer it got back. The answers
    are the part worth having -- a refusal is the only record of WHY a request
    did not make it into the room.
    """
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not set in the local .env, so the room has "
                         "nobody to talk to. Add it and restart the server. Everything "
                         "else on this page works without it.")

    world_id = room_world.open_room(room.spec)
    entry = room_world.entry_of(world_id)
    started = time.perf_counter()
    try:
        opening = {"what_you_were_asked": message,
                   "what_the_person_has_been_doing": story[-24:] or ["nothing yet"],
                   "objects_now": _now(live_state),
                   "the_room": {"cell_size_m": entry["cell_m"],
                                "cells_used": entry["cells"],
                                "cells_left": max(0, entry["max_cells"] - entry["cells"]),
                                "joints": len(entry["joints"])}}
        conversation: list[dict[str, Any]] = [
            {"role": "user", "content": json.dumps(opening, allow_nan=False)}]
        did: list[str] = []
        changed = False
        usage = {"input_tokens": 0, "output_tokens": 0}
        reply = ""
        rounds = 0

        for turn in range(MAX_ROUNDS):
            if time.perf_counter() - started > MAX_TURN_S:
                reply = (f"I ran out of time after {turn} rounds. "
                         + ("What I had built by then is in the room." if changed
                            else "Nothing in the room was changed."))
                break
            result = _call(api_key, model, conversation)
            rounds = turn + 1
            spent = result.get("usage") or {}
            usage["input_tokens"] += int(spent.get("input_tokens") or 0)
            usage["output_tokens"] += int(spent.get("output_tokens") or 0)
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
            round_record: dict[str, Any] = {"round": rounds, "said": "".join(said).strip(),
                                            "calls": []}
            if trace is not None:
                trace.append(round_record)

            if not calls:
                reply = "".join(said).strip() or "Done."
                break

            # Carry the model's own turn forward -- its reasoning and its calls --
            # then answer each call. Dropping the call leaves the next request
            # describing an answer to a question that was never asked.
            conversation.extend(o for o in outputs
                                if o.get("type") in ("reasoning", "function_call"))
            for call in calls:
                name = call.get("name", "")
                try:
                    args = json.loads(call.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                if not isinstance(args, dict):
                    args = {}
                answer = room_world.call(world_id, name, args)
                if name in room_world.AUTHORING and "error" not in answer:
                    changed = True
                    did.append(_did(name, args, answer))
                round_record["calls"].append({"name": name, "arguments": args,
                                              "answer": answer})
                conversation.append({"type": "function_call_output",
                                     "call_id": call.get("call_id"),
                                     "output": json.dumps(answer, allow_nan=False)})
        else:
            reply = (f"I was still working after {MAX_ROUNDS} rounds. "
                     + ("What I had built by then is in the room." if changed
                        else "Nothing in the room was changed."))

        if changed:
            room.spec = room_world.export_spec(entry)
        return {"reply": reply, "did": did, "changed": changed,
                "wall_s": round(time.perf_counter() - started, 2), "rounds": rounds,
                "usage": usage}
    finally:
        room_world.close_room(world_id)
