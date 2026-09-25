"""What a machine can do (docs/machine-world.md, "A machine's senses and its
tools").

The tools are the one set of things a machine with a program can be told to
do, whoever tells it: its routine, working through them step by step; Jev or
the chat's model, picking one when something happens; a person talking to it.
Each tool is one named action with its arguments, a description a model can
read, what it does to the engine, and what to fill its arguments with when
whoever picks it gives none (Jev picks a name and nothing more). The engine
does the doing: an ask on the program (LiveWorld::behave) for anything to do
with going, the ground ops for digging and dumping, a draw on the battery for
the work of a scoop. A tool answers what it did, in words, and never invents
an outcome: what the machine then does is the world's answer, read back
through its senses.

Nothing here is a rover's. A tool that needs what a machine lacks -- a hopper,
a place it knows -- says so and does nothing. A new tool is one entry in
TOOLS.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Callable

import machine_senses as senses

# How a scoop's work is charged to the battery: declared, not derived. Lifting
# a kilogram of soil half a metre is 5 J; breaking it out of the ground is
# several times that (docs/ground-work.md measures the hand's tools). The
# routine may declare its own; this is the default.
WORK_J_PER_KG = 50.0
# How long a scoop takes, per kilogram, so a load of twenty takes five
# seconds: declared, so a dig is watchable rather than instant.
DIG_S_PER_KG = 0.25
DIG_WIDTH_M = 0.5
DIG_DEPTH_M = 0.15
# Where the scoop bites, ahead of the machine's centre: clear of a caster at
# its front, which swings into a hole dug closer when the machine turns to
# leave (measured on the page: a rover turning in place at its own hole for
# a minute).
DIG_AHEAD_M = 1.3
DUMP_RADIUS_M = 0.6


@dataclass
class Call:
    """One tool call as it is made: by whom, what, with what, and why."""
    tool: str
    args: dict[str, Any]
    by: str
    why: str = ""


def _act(ctx: senses.Context, **command: Any) -> dict[str, Any]:
    if ctx.ask is None:
        raise ValueError("this machine has no engine to act on")
    return ctx.ask(**command)


def _behave(ctx: senses.Context, call: Call, doing: str, for_s: float, toward: list[float] | None = None) -> dict[str, Any]:
    """An ask on the program, by the caller, with the world's y for the point."""
    command: dict[str, Any] = {"op": "behave", "program": ctx.program["id"], "sender": call.by,
                               "doing": doing, "for_s": float(for_s), "why": call.why[:200]}
    if toward is not None:
        y = float((ctx.program.get("at_m") or [0, 0, 0])[1])
        command["toward"] = [float(toward[0]), y, float(toward[1])]
    reply = _act(ctx, **command)
    program = reply.get("program") or {}
    return {"did": f"asked to be {doing or 'itself again'}" + (f" for {for_s:g} s" if for_s else ""),
            "doing": program.get("doing"), "why": program.get("why")}


def _place(ctx: senses.Context, args: dict[str, Any]) -> tuple[list[float], str]:
    """Where a tool is pointed: a named place the routine knows, the person,
    a point, or a bearing and distance from the machine's front."""
    if args.get("place"):
        places = (ctx.routine.places if ctx.routine is not None else {}) or {}
        if args["place"] == "person":
            at = (ctx.person or {}).get("standing_m") if isinstance(ctx.person, dict) else None
            if not isinstance(at, (list, tuple)) or len(at) != 3:
                raise ValueError("it does not know where the person is")
            return [float(at[0]), float(at[2])], "the person"
        xz = places.get(args["place"])
        if xz is None:
            raise ValueError(f"it knows no place called {args['place']!r}; it knows {sorted(places) or 'none'}")
        return [float(xz[0]), float(xz[1])], args["place"]
    if args.get("point") is not None:
        p = args["point"]
        if not isinstance(p, (list, tuple)) or len(p) not in (2, 3):
            raise ValueError("a point is [x, z] in metres")
        return [float(p[0]), float(p[-1])], f"({float(p[0]):.1f}, {float(p[-1]):.1f})"
    bearing = float(args.get("bearing_deg", 0.0))
    metres = float(args.get("distance_m", 3.0))
    return senses.point_ahead(ctx, metres, bearing), f"{metres:g} m at {bearing:+g} deg"


# ---- going -----------------------------------------------------------------

def go_forward(ctx: senses.Context, call: Call) -> dict[str, Any]:
    return _behave(ctx, call, "going forward", float(call.args.get("for_s", 2.0)))


def back_off(ctx: senses.Context, call: Call) -> dict[str, Any]:
    return _behave(ctx, call, "backing off", float(call.args.get("for_s", 1.5)))


def turn_left(ctx: senses.Context, call: Call) -> dict[str, Any]:
    return _behave(ctx, call, "turning left", float(call.args.get("for_s", 2.5)))


def turn_right(ctx: senses.Context, call: Call) -> dict[str, Any]:
    return _behave(ctx, call, "turning right", float(call.args.get("for_s", 2.5)))


def hold_still(ctx: senses.Context, call: Call) -> dict[str, Any]:
    return _behave(ctx, call, "waiting", float(call.args.get("for_s", 3.0)))


def face(ctx: senses.Context, call: Call) -> dict[str, Any]:
    point, name = _place(ctx, call.args)
    out = _behave(ctx, call, "facing", float(call.args.get("for_s", 0.0)), point)
    out["did"] = f"asked to face {name}"
    return out


def go_to(ctx: senses.Context, call: Call) -> dict[str, Any]:
    point, name = _place(ctx, call.args)
    out = _behave(ctx, call, "approaching", float(call.args.get("for_s", 60.0)), point)
    out["did"] = f"asked to go to {name}, and stop a metre off"
    out["target"] = point
    return out


def carry_on(ctx: senses.Context, call: Call) -> dict[str, Any]:
    """Asked nothing more: its reflexes, and its routine, have it back."""
    out = _behave(ctx, call, "", 0.0)
    if ctx.routine is not None:
        ctx.routine.resume()
    out["did"] = "let go on with its routine"
    return out


# ---- the ground --------------------------------------------------------------

def dig(ctx: senses.Context, call: Call) -> dict[str, Any]:
    """One scoop of the ground ahead of it into its hopper: the engine's dig,
    the volume moved out of what is carried into the hopper's account, the
    work drawn from its battery, and a wait for as long as the scoop takes."""
    r = ctx.routine
    if r is None or not r.carries():
        raise ValueError("it has no hopper to dig into")
    if r.load_full():
        return {"did": "dug nothing: its hopper is full", "load": r.load_reading()}
    store = senses._store(ctx)
    point = senses.point_ahead(ctx, float(call.args.get("ahead_m", DIG_AHEAD_M)))
    depth = min(float(call.args.get("depth_m", DIG_DEPTH_M)), 1.0)
    width = min(float(call.args.get("width_m", DIG_WIDTH_M)), 2.0)
    # The battery must have the work in it before the ground is touched: a
    # scoop's worth at the depth asked, at the ground's density.
    here = ctx.survey(point[0], point[1])
    if not here.get("on_the_ground", True) and "ground_m" not in here:
        return {"did": "dug nothing: the ground ahead is off the edge of the room"}
    reply = _act(ctx, op="dig", **{"from": point, "to": point}, width_m=width, depth_m=depth)
    dug = reply.get("dug") or {}
    kg = float(dug.get("kg") or 0.0)
    sand, soil = float(dug.get("sand_m3") or 0.0), float(dug.get("soil_m3") or 0.0)
    if kg <= 0.0:
        return {"did": "dug nothing: nothing came out of the ground there", "dug": dug}
    room = r.load_room_kg()
    if kg > room + 1e-6:
        # More than the hopper holds: the rest goes back on the ground where it came from.
        share = room / kg
        back_sand, back_soil = sand * (1.0 - share), soil * (1.0 - share)
        _act(ctx, op="deposit", at=point, radius_m=width, sand_m3=back_sand, soil_m3=back_soil, from_carried=True)
        sand, soil, kg = sand * share, soil * share, room
    # Out of what is carried, into the hopper's account.
    if sand > 0.0 or soil > 0.0:
        _act(ctx, op="ground_withdraw", sand_m3=sand, soil_m3=soil)
    r.load_in(sand, soil, kg)
    work_j = kg * float(r.work_j_per_kg)
    drawn = 0.0
    if store is not None and work_j > 0.0:
        have = float(store.get("charge_j") or 0.0)
        take = min(work_j, have)
        if take > 0.0:
            _act(ctx, op="draw", store=store["id"], joules=take)
            drawn = take
    took_s = kg * DIG_S_PER_KG
    _behave(ctx, call, "waiting", max(0.5, took_s))
    r.note(f"dug {kg:.1f} kg ({sand:.3f} m3 sand, {soil:.3f} m3 soil), {drawn:.0f} J drawn")
    return {"did": f"dug {kg:.1f} kg into its hopper, drawing {drawn:.0f} J, in {took_s:.1f} s",
            "dug": {"kg": round(kg, 2), "sand_m3": round(sand, 4), "soil_m3": round(soil, 4)},
            "drawn_j": round(drawn), "load": r.load_reading()}


def dump(ctx: senses.Context, call: Call) -> dict[str, Any]:
    """Its hopper emptied onto the ground ahead of it: the packet back into
    what is carried, then heaped there."""
    r = ctx.routine
    if r is None or not r.carries():
        raise ValueError("it has no hopper to empty")
    sand, soil, kg = r.load_out()
    if kg <= 0.0:
        return {"did": "dumped nothing: its hopper is empty"}
    point = senses.point_ahead(ctx, float(call.args.get("ahead_m", DIG_AHEAD_M)))
    _act(ctx, op="ground_return", sand_m3=sand, soil_m3=soil)
    reply = _act(ctx, op="deposit", at=point, radius_m=float(call.args.get("radius_m", DUMP_RADIUS_M)),
                 sand_m3=sand, soil_m3=soil, from_carried=True)
    r.delivered(sand, soil, kg)
    _behave(ctx, call, "waiting", 2.0)
    r.note(f"dumped {kg:.1f} kg")
    return {"did": f"dumped {kg:.1f} kg on the ground ahead", "heaped": reply.get("heaped"),
            "load": r.load_reading()}


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    run: Callable[[senses.Context, Call], dict[str, Any]]
    params: dict[str, Any]                       # JSON schema properties, for a model that fills them
    # Whether a decider may pick it when something happens (a routine's own
    # steps may use the rest).
    for_deciders: bool = True


_FOR_S = {"for_s": {"type": "number", "description": "for how many seconds, 0 for until asked otherwise"}}
_WHERE = {"place": {"type": "string", "description": "a place it knows by name, or 'person'"},
          "point": {"type": "array", "items": {"type": "number"}, "description": "[x, z] in metres"},
          "bearing_deg": {"type": "number", "description": "degrees from its front, positive to its left"},
          "distance_m": {"type": "number"}}

TOOLS: dict[str, Tool] = {t.name: t for t in (
    Tool("go_forward", "Keep going forward for a while: the way ahead is clear.", go_forward, _FOR_S),
    Tool("back_off", "Reverse for a moment: something is ahead or in its way, or it just struck something or "
                     "its wheels stalled.", back_off, _FOR_S),
    Tool("turn_left", "Turn on the spot to its left: the trouble is on its right or ahead and its left is clear.",
         turn_left, _FOR_S),
    Tool("turn_right", "Turn on the spot to its right: the trouble is on its left or ahead and its right is "
                       "clear.", turn_right, _FOR_S),
    Tool("hold_still", "Hold still on its brakes: it is unclear what is happening, a person is close, or moving "
                       "would make things worse.", hold_still, _FOR_S),
    Tool("face", "Turn on the spot until its front is towards a place, the person, a point or a bearing.", face,
         {**_WHERE, **_FOR_S}),
    Tool("go_to", "Go to a place it knows, the person, a point or a bearing, and stop a metre off.", go_to,
         {**_WHERE, **_FOR_S}),
    Tool("dig", "Take one scoop of the ground ahead into its hopper, drawing the work from its battery.", dig,
         {"depth_m": {"type": "number"}, "width_m": {"type": "number"}}),
    Tool("dump", "Empty its hopper onto the ground ahead of it.", dump, {}),
    Tool("carry_on", "Ask nothing more of it: its routine and its reflexes have it back.", carry_on, {}),
)}


def catalogue(for_deciders: bool = True) -> list[dict[str, Any]]:
    return [{"name": t.name, "description": t.description, "params": t.params}
            for t in TOOLS.values() if t.for_deciders or not for_deciders]


def run(ctx: senses.Context, call: Call) -> dict[str, Any]:
    """One tool, called; what it did, or why it could not: a tool that fails
    never stops the room."""
    tool = TOOLS.get(call.tool)
    if tool is None:
        return {"did": f"there is no tool called {call.tool!r}", "failed": True}
    try:
        return tool.run(ctx, call)
    except Exception as failed:
        return {"did": f"{call.tool} could not: {str(failed)[:160]}", "failed": True}
