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
# How fast it backs off, near enough to reckon a back-off by: measured on the
# mine's rover, which reversed 0.62 m in its second second of it.
BACK_OFF_M_S = 0.6
DIG_WIDTH_M = 0.5
DIG_DEPTH_M = 0.15
# Where the scoop bites when nothing says where: ahead of the machine's centre,
# clear of a caster at its front, which swings into a hole dug closer when the
# machine turns to leave (measured on the page: a rover turning in place at its
# own hole for a minute).
DIG_AHEAD_M = 1.3
# How far out it can reach a place it was sent to work, and how close it will
# let itself be to the spot it is about to bite. It will not dig the ground it
# is standing on, because it cannot drive out of what it digs: a scoop is 150 mm
# deep and a caster wheel 160 mm across, so any scoop of its own is a trap, and
# on a slope it does not even have to be a whole one.
DIG_REACH_M = 2.0
DIG_CLEAR_M = 1.2
# And where it stands to work a place: inside its reach, outside the working, and
# chosen for where a machine told to stop actually stops. Told to stop a metre
# off something, the mine's rover came to rest anywhere from 0.2 m to 1.0 m from
# it, because it rolls on while its brakes take hold; told to stand 2.0 m off, it
# came to rest 1.6 m off, inside the window between DIG_CLEAR_M and DIG_REACH_M
# that it may dig in. Nearer than that and it backs off before it digs.
DIG_STAND_M = 2.0
# How fresh the ground a bite goes into must be, and how wide the working may
# spread. Each spot is scooped ONCE: a bite only goes into ground still within
# this of the ground around it, so the working spreads across the place and no
# hole is ever deepened. Measured on the mine's rover: driven at one, it crosses
# a scoop 0.5 m wide and 150 mm deep without trouble, but scoop after scoop into
# the one spot sank a shaft 600 mm deep and 1.1 m across, and a machine on
# 160 mm wheels can only fall into that. Once every spot it can reach has been
# worked, the place is worked out and it says so.
DIG_FRESH_M = 0.03
# How far apart the spots it considers are, and how wide the working spreads
# where the place is not a deposit with a width of its own: a scoop's own
# width, so the spots cover the ground without overlapping much, and never
# narrower than one step or a place would have only its middle to give.
DIG_STEP_M = 0.5
DIG_SPREAD_M = DIG_STEP_M
DUMP_RADIUS_M = 0.6
# How long a machine stands still at a dock that has passed nothing, before it
# is asked again: a declared game constant, long enough that its reflexes do
# not drive it off between tries and short enough that a dock bounded in a few
# seconds gets several of them.
HOLD_AT_A_DOCK_S = 1.0


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
    transfer = getattr(ctx.ask, "transfer_ground", None)
    if command.get("op") in ("ground_withdraw", "ground_return") and callable(transfer):
        return transfer("machine:" + str(ctx.program["name"]), command)
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
    """Where a tool is pointed: a port of another machine, a named place the
    routine knows, the person, a point, or a bearing and distance from the
    machine's front."""
    if args.get("port"):
        # A mouth on another device (machine_ports), where it is NOW: a
        # machine sent to a port goes to the thing, not to a patch of ground,
        # so a smelter moved is still found.
        port = ctx.ports.by_name(str(args["port"])) if ctx.ports is not None else None
        if port is None:
            known = sorted(p.name for p in ctx.ports.ports) if ctx.ports is not None else []
            raise ValueError(f"it knows no port called {args['port']!r}; the room's ports are "
                             + (", ".join(known) if known else "none"))
        if not port.settled():
            raise ValueError(f"the port {port.name} has not been seen in the room yet")
        return [port.at_m[0], port.at_m[2]], f"the {port.name}"
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


def rise(ctx: senses.Context, call: Call) -> dict[str, Any]:
    """Up, while it is asked: a flying machine's height loop holds the height
    it reaches (LiveWorld::decideHover)."""
    if ctx.program.get("kind") != "hover":
        raise ValueError("it does not fly: only a machine on rotors rises or descends")
    return _behave(ctx, call, "rising", float(call.args.get("for_s", 2.0)))


def descend(ctx: senses.Context, call: Call) -> dict[str, Any]:
    """Down, while it is asked; held all the way, it sets itself on the ground."""
    if ctx.program.get("kind") != "hover":
        raise ValueError("it does not fly: only a machine on rotors rises or descends")
    return _behave(ctx, call, "descending", float(call.args.get("for_s", 2.0)))


def hold_still(ctx: senses.Context, call: Call) -> dict[str, Any]:
    return _behave(ctx, call, "waiting", float(call.args.get("for_s", 3.0)))


def face(ctx: senses.Context, call: Call) -> dict[str, Any]:
    point, name = _place(ctx, call.args)
    out = _behave(ctx, call, "facing", float(call.args.get("for_s", 0.0)), point)
    out["did"] = f"asked to face {name}"
    return out


def _flies(ctx: senses.Context) -> bool:
    """Whether this machine is in the air: a flyer is over the ground it works,
    not on it, so nothing it digs is under its wheels."""
    return str((ctx.program or {}).get("kind") or "") == "hover"


def stands_off_m(ctx: senses.Context) -> float:
    """How far from a place a machine stands to work it: nothing for one that
    flies, which hovers over it, and its own body-length and more for one on
    wheels, which must keep off what it digs."""
    return 0.0 if _flies(ctx) else DIG_STAND_M


def _short_of(ctx: senses.Context, point: list[float], stand_m: float) -> list[float]:
    """The point `stand_m` short of a place, on the line the machine is coming in
    on. A machine stops a metre off whatever it is aimed at, so to stand further
    out it is aimed a metre nearer than that. Already inside it, the point comes
    out behind the machine, and going to it takes it back out, which is what it
    needs."""
    short = max(0.0, stand_m - NEAR_M)
    if short <= 0.0:
        return list(point)
    ax, az = ctx.at()
    away = math.hypot(point[0] - ax, point[1] - az)
    if away <= 1e-6:
        return list(point)
    return [point[0] + (ax - point[0]) * short / away, point[1] + (az - point[1]) * short / away]


def go_to(ctx: senses.Context, call: Call) -> dict[str, Any]:
    """Asked to go to a place and stop a metre off it; `stop_at_m` stops it that
    far from the place instead, by aiming it at a point short of the place on the
    line it is coming in on.

    A machine working the ground needs this: the place it is sent to becomes the
    pit it digs, and "a metre off" is not clear of a pit -- told to stop a metre
    from the vein, the mine's rover rolled in to 0.1 m of it while its brakes
    took hold, into a 12 cm hole of its own, and could not get out. Standing
    short of its work, it can reach the pit without being in it."""
    point, name = _place(ctx, call.args)
    # A machine that flies hovers over what it works, so a stand-off asked of it
    # is nothing: it is not standing on anything.
    stand = max(0.0, float(call.args.get("stop_at_m", 0.0)))
    if _flies(ctx):
        stand = 0.0
    aim = _short_of(ctx, point, stand)
    out = _behave(ctx, call, "approaching", float(call.args.get("for_s", 60.0)), aim)
    out["did"] = (f"asked to go to {name}, and stand {stand:.1f} m off it" if stand > 0.0
                  else f"asked to go to {name}, and stop a metre off")
    out["target"] = aim
    out["place_at"] = point
    return out


def carry_on(ctx: senses.Context, call: Call) -> dict[str, Any]:
    """Asked nothing more: its reflexes, and its routine, have it back."""
    out = _behave(ctx, call, "", 0.0)
    if ctx.routine is not None:
        ctx.routine.resume()
    out["did"] = "let go on with its routine"
    return out


# ---- the ground --------------------------------------------------------------

def _around_m(ctx: senses.Context, middle: list[float], radius_m: float) -> float:
    """How high the ground stands round a place, read on a ring outside anything
    worked there: the middle of the ring's readings, so one reading on a slope or
    in a rut does not stand for the lot."""
    heights = []
    for i in range(8):
        turn = i * math.pi / 4.0
        x, z = middle[0] + radius_m * math.sin(turn), middle[1] + radius_m * math.cos(turn)
        here = ctx.survey(x, z) or {}
        if "ground_m" in here:
            heights.append(float(here["ground_m"] or 0.0))
    if not heights:
        return 0.0
    heights.sort()
    return heights[len(heights) // 2]


def _spread_m(ctx: senses.Context, middle: list[float]) -> float:
    """How wide the working may spread round a place: as wide as the deposit it
    is in, where it is in one, and otherwise a scoop or two.

    A spot gives one scoop, so how much a machine can take from a place before
    it is worked out is how many spots the place has. Held to half a metre, the
    mine's vein gave three loads and then the rover spent nine tenths of a
    twenty-minute run on a dig step it could not do; the vein is 3 m across, and
    working the width of it is both what a miner does and what keeps the machine
    busy."""
    if ctx.goods is None:
        return DIG_SPREAD_M
    deposit = ctx.goods.deposit_at(middle[0], middle[1])
    if deposit is None:
        return DIG_SPREAD_M
    return max(DIG_SPREAD_M, float(deposit.get("radius_m") or 0.0))


def _spots(ctx: senses.Context, middle: list[float]) -> list[list[float]]:
    """Where it could put this bite: the middle of the place and rings out to the
    spread, keeping only what the machine can reach without standing on it, and
    preferring the far side of the place to the near one.

    The far side is the ground it is not about to drive over. It comes at a place
    from wherever the depot happens to be that trip, so working away from itself
    keeps this trip's approach clean, and the side it worked last trip is behind
    it now."""
    ax, az = ctx.at()
    to_middle = math.hypot(middle[0] - ax, middle[1] - az)
    spread = _spread_m(ctx, middle)
    # A flyer is over its work, not on it, so no spot is under its wheels.
    clear = 0.0 if _flies(ctx) else DIG_CLEAR_M
    radii = [0.0]
    while radii[-1] + DIG_STEP_M <= spread + 1e-6:
        radii.append(round(radii[-1] + DIG_STEP_M, 3))
    near, far = [], []
    for radius in radii:
        turns = 1 if radius == 0.0 else max(8, int(2.0 * math.pi * radius / DIG_STEP_M))
        for i in range(turns):
            turn = i * 2.0 * math.pi / turns
            spot = [middle[0] + radius * math.sin(turn), middle[1] + radius * math.cos(turn)]
            off = math.hypot(spot[0] - ax, spot[1] - az)
            if clear <= off <= DIG_REACH_M:
                (far if off >= to_middle - 0.05 else near).append(spot)
    return far or near


def _bite(ctx: senses.Context, args: dict[str, Any]) -> dict[str, Any]:
    """Where a scoop bites, or why it does not.

    Told a place to work, it bites at the HIGHEST ground of that place it can
    reach without standing on it, and once even the highest is DIG_DEEPEST_M
    below the ground around, the place is worked out and it says so. Told
    nothing, it bites straight ahead of it, as a machine being driven by hand
    does.

    Both halves of that were learned in the mine (docs/machine-world.md, "When a
    machine cannot get out"). Biting at its own nose put a crater wherever the
    machine happened to stop and whichever way it was pointing: four trips to one
    vein left four holes 10 to 18 cm deep spread over 2 m, and on the fifth the
    rover stood on the rim of one and could not get out. Biting always at the
    middle of the place put every scoop in one spot instead: a shaft 600 mm deep
    and 1.1 m across, which a machine on 160 mm wheels can only fall into. Going
    for the high ground spreads the working out and keeps it shallow, the way an
    open pit is worked, and the cap means a machine never digs itself a hole it
    cannot drive out of.

    A machine that flies works the ground under it: it hovers over the place and
    scoops down, so it keeps no stand-off and nothing it digs is under its
    wheels. It keeps the rest -- the high ground, one scoop a spot, worked out
    said rather than scraped at -- because the hole it leaves is in everyone's
    way, not only its own.
    """
    if not args.get("place") and args.get("point") is None:
        return {"point": senses.point_ahead(ctx, float(args.get("ahead_m", DIG_AHEAD_M)))}
    middle, named = _place(ctx, args)
    ax, az = ctx.at()
    off = math.hypot(middle[0] - ax, middle[1] - az)
    clear = 0.0 if _flies(ctx) else DIG_CLEAR_M
    if off > DIG_REACH_M + 1e-6:
        # Drifted out of reach of the place it is working: it goes back to it.
        # Refusing outright left the routine sat on a dig step it could not do,
        # because the step that took the machine there is behind it -- measured
        # on a drone given a dig routine, which wandered 4.8 m off the vein and
        # said "it must go there first" for the rest of the run.
        return {"go_to": _short_of(ctx, middle, stands_off_m(ctx)),
                "why": f"{named} is {off:.1f} m off, beyond the {DIG_REACH_M:.1f} m it can reach, so it goes back"}
    if off < clear:
        # Standing over the place. Told to go somewhere, a machine on wheels
        # stops "a metre off" and then rolls on while its brakes take hold --
        # measured 0.2 m from the vein -- so where it stopped is no guide to what
        # it may dig, and it gets off the spot before working it.
        return {"back_off_m": clear + 0.3 - off,
                "why": f"it is {off:.1f} m from {named} and will not dig the ground under itself"}
    around = _around_m(ctx, middle, _spread_m(ctx, middle) + 0.5)
    best, high = None, None
    for spot in _spots(ctx, middle):
        here = ctx.survey(spot[0], spot[1]) or {}
        if "ground_m" not in here:
            continue
        ground = float(here["ground_m"] or 0.0)
        if high is None or ground > high:
            best, high = spot, ground
    if best is None:
        return {"why": f"it cannot reach any of {named} from where it stands"}
    down_mm = (around - high) * 1000.0
    if down_mm > DIG_FRESH_M * 1000.0:
        return {"why": f"{named} is worked out: the highest ground of it it can reach is {down_mm:.0f} mm down "
                       f"already, and it will not dig one hole deeper"}
    return {"point": best}


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
    bite = _bite(ctx, call.args)
    if bite.get("back_off_m"):
        _behave(ctx, call, "backing off", max(1.0, float(bite["back_off_m"]) / BACK_OFF_M_S))
        return {"did": f"dug nothing yet: {bite['why']}, so it backs off first", "load": r.load_reading()}
    if bite.get("go_to"):
        _behave(ctx, call, "approaching", 60.0, bite["go_to"])
        return {"did": f"dug nothing yet: {bite['why']}", "load": r.load_reading()}
    if not bite.get("point"):
        return {"did": f"dug nothing: {bite.get('why', 'there is nothing to dig there')}", "idle": True,
                "load": r.load_reading()}
    point = bite["point"]
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
        # Worked out, not broken: a spot gives about five loads and then
        # crumbs, so the machine stops scraping and goes on with what it has
        # (machine_routine reads `idle`). Someone who wants more moves the site.
        return {"did": "dug nothing: the ground here is worked out", "idle": True, "dug": dug,
                "load": r.load_reading()}
    room = r.load_room_kg()
    if kg > room + 1e-6:
        # More than the hopper holds: the rest goes back on the ground where it came from.
        share = room / kg
        back_sand, back_soil = sand * (1.0 - share), soil * (1.0 - share)
        reply = _act(ctx, op="deposit", at=point, radius_m=width, sand_m3=back_sand, soil_m3=back_soil,
                     from_carried=True)
        sand, soil, kg = sand * share, soil * share, room
    # Out of what is carried and into the hopper's account, clamped to what the
    # account holds: the scoop's reply is rounded and the account is exact, and
    # on a scoop of a few grams the rounding is the whole of it -- asking for a
    # hair more than is there refused the dig outright ("transfer needs positive
    # finite quantities already carried", Environment::withdrawCarried).
    carried = reply.get("carried")
    if isinstance(carried, dict):
        sand = min(sand, float(carried.get("sand_m3") or 0.0))
        soil = min(soil, float(carried.get("soil_m3") or 0.0))
        if sand + soil <= 0.0:
            return {"did": "dug nothing: the ground here is worked out", "idle": True, "dug": dug,
                    "load": r.load_reading()}
    if sand > 0.0 or soil > 0.0:
        received=_act(ctx, op="ground_withdraw", sand_m3=sand, soil_m3=soil)
        if received.get("material_packet"):
            contents=received["material_packet"]["contents"]
            sand=sum(p["volume_m3"] for p in contents if p["substance"]=="sand")
            soil=sum(p["volume_m3"] for p in contents if p["substance"]=="soil")
            kg=sum(p["mass_kg"] for p in contents)
    # What the scoop brought up from a deposit besides soil (machine_goods):
    # ore, at the deposit's grade of the scoop's mass. Its share of the
    # volume has left the ground for good -- exported, as a material packet
    # is -- so the hopper keeps only the rest of the soil to put back.
    ore = ctx.goods.dug(point[0], point[1], kg) if ctx.goods is not None else {}
    ore_share = min(1.0, sum(ore.values()) / kg) if ore else 0.0
    r.load_in(sand * (1.0 - ore_share), soil * (1.0 - ore_share), kg, ore)
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
    found = ", ".join(f"{v:.1f} kg of {k}" for k, v in ore.items())
    r.note(f"dug {kg:.1f} kg ({sand:.3f} m3 sand, {soil:.3f} m3 soil{', ' + found if found else ''}), "
           f"{drawn:.0f} J drawn")
    return {"did": f"dug {kg:.1f} kg into its hopper" + (f", {found} in it" if found else "")
                   + f", drawing {drawn:.0f} J, in {took_s:.1f} s",
            "dug": {"kg": round(kg, 2), "sand_m3": round(sand, 4), "soil_m3": round(soil, 4),
                    "goods_kg": {k: round(v, 3) for k, v in ore.items()}},
            "drawn_j": round(drawn), "load": r.load_reading()}


# How wide a survey looks by default, and the most it will take in at once: a
# machine says what is known of a patch of ground, not of the whole room.
SURVEY_M = 6.0
SURVEY_MOST_M = 20.0


def survey(ctx: senses.Context, call: Call) -> dict[str, Any]:
    """What is known of a place: the lie of the ground there, what is on it, and
    how much of it nobody has seen.

    This REPORTS; it does not reveal. What reveals ground is being there
    (machine_sight), so a machine asked about somewhere nobody has been says so
    rather than reading the answer out of the room's document -- which is the
    point of it, because a place worth going to is one it cannot answer about
    yet."""
    if call.args.get("place") or call.args.get("point") is not None or call.args.get("bearing_deg") is not None:
        middle, named = _place(ctx, call.args)
    else:
        ax, az = ctx.at()
        middle, named = [ax, az], "where it stands"
    radius = min(max(1.0, float(call.args.get("radius_m", SURVEY_M))), SURVEY_MOST_M)
    sight = ctx.sight if (ctx.sight is not None and ctx.sight.nx) else None
    step = max(0.5, radius / 3.0)
    across = int(2.0 * radius / step) + 1
    known, unseen, off_the_edge = 0, 0, 0
    surfaces: dict[str, int] = {}
    high = low = None
    steepest, deepest_water = 0.0, 0.0
    for j in range(across):
        for i in range(across):
            x = middle[0] - radius + i * step
            z = middle[1] - radius + j * step
            if math.hypot(x - middle[0], z - middle[1]) > radius:
                continue
            if sight is not None and not sight.knows(x, z):
                unseen += 1
                continue
            here = ctx.survey(x, z) or {}
            if "ground_m" not in here:
                off_the_edge += 1
                continue
            known += 1
            ground = float(here["ground_m"] or 0.0)
            high = ground if high is None else max(high, ground)
            low = ground if low is None else min(low, ground)
            surface = str(here.get("surface") or "soil")
            surfaces[surface] = surfaces.get(surface, 0) + 1
            steepest = max(steepest, float(here.get("slope_deg") or 0.0))
            deepest_water = max(deepest_water, float((here.get("water") or {}).get("depth_m") or 0.0))
    # What is in it, of what is known: the room's goods, and anything standing
    # there that is not part of this machine.
    deposits, heaps = [], []
    if ctx.goods is not None:
        for row in ctx.goods.deposits:
            at = row.get("at_m") or [0.0, 0.0]
            if math.hypot(float(at[0]) - middle[0], float(at[-1]) - middle[1]) > radius + float(row.get("radius_m") or 0.0):
                continue
            if sight is not None and not sight.knows(float(at[0]), float(at[-1])):
                continue
            deposits.append({"name": row.get("name"), "substance": row.get("substance"),
                             "left_kg": round(ctx.goods.reserve_kg(row), 1)})
        for row in ctx.goods.stockpiles:
            at = row.get("at_m") or [0.0, 0.0]
            if math.hypot(float(at[0]) - middle[0], float(at[-1]) - middle[1]) > radius:
                continue
            if sight is not None and not sight.knows(float(at[0]), float(at[-1])):
                continue
            heaps.append({"name": row.get("name"), "holds": {k: round(v, 1) for k, v in (row.get("holds") or {}).items()}})
    mine = set(ctx.program.get("parts") or []) | {ctx.program.get("body")}
    things = []
    for body in ctx.bodies or []:
        name = body.get("name")
        at = body.get("position_m")
        if not name or name in mine or not isinstance(at, (list, tuple)) or len(at) < 3:
            continue
        if math.hypot(float(at[0]) - middle[0], float(at[2]) - middle[1]) > radius:
            continue
        if sight is not None and not sight.knows(float(at[0]), float(at[2])):
            continue
        things.append({"what": name, "material": body.get("material")})
    cells = known + unseen + off_the_edge
    share = (known / (known + unseen)) if (known + unseen) else 1.0
    out: dict[str, Any] = {
        "place": named, "at_m": [round(middle[0], 2), round(middle[1], 2)], "radius_m": radius,
        "known_share": round(share, 2), "spots_read": known, "spots_not_seen": unseen,
        "deposits": deposits, "heaps": heaps, "things": things[:12],
    }
    if known:
        out["ground"] = {"surface": max(surfaces, key=surfaces.get) if surfaces else None,
                         "highest_m": round(high or 0.0, 2), "lowest_m": round(low or 0.0, 2),
                         "steepest_deg": round(steepest, 1),
                         "deepest_water_m": round(deepest_water, 3)}
    # And in words, because a person and a model read the same answer.
    if not known and unseen:
        out["did"] = f"surveyed {named}: nobody has been near it, so nothing is known of it"
    else:
        words = [f"surveyed {named}"]
        if out.get("ground"):
            g = out["ground"]
            words.append(f"{g['surface']} ground, {g['lowest_m']:.2f} to {g['highest_m']:.2f} m, "
                         f"steepest {g['steepest_deg']:.0f} deg")
            if g["deepest_water_m"] > 0.003:
                words.append(f"water up to {round(1000 * g['deepest_water_m'])} mm")
        if deposits:
            words.append("in it: " + ", ".join(f"{d['name']} ({d['left_kg']:.0f} kg of {d['substance']} left)"
                                               for d in deposits))
        if heaps:
            words.append("heaps: " + ", ".join(d["name"] for d in heaps))
        if things:
            words.append(f"{len(things)} thing{'' if len(things) == 1 else 's'} standing there")
        if unseen:
            words.append(f"{round(100 * (1.0 - share))}% of it not seen yet")
        out["did"] = "; ".join(words)
    return out


def _pile_for(ctx: senses.Context, args: dict[str, Any]) -> tuple[dict[str, Any] | None, list[float]]:
    """The stockpile a tool works: the one at the place named (a place the
    routine knows, such as "source": the stockpile is the one within half a
    metre of it), else the one within reach of the machine, else none; and
    the point the tool works at. A stockpile out of the machine's reach is
    refused: it must stand by it."""
    goods = ctx.goods
    ax, az = ctx.at()
    if args.get("place"):
        point, name = _place(ctx, args)
        # No stockpile at the place: a dump makes a heap there; a take says so.
        pile = goods.stockpile_near(point[0], point[1], reach_m=0.5)
    else:
        point = senses.point_ahead(ctx, float(args.get("ahead_m", DIG_AHEAD_M)))
        pile = goods.stockpile_near(ax, az)
    if pile is not None:
        at = pile["at_m"]
        off = math.hypot(ax - float(at[0]), az - float(at[1])) - float(pile.get("radius_m", 1.0))
        if off > machine_goods_reach():
            raise ValueError(f"{pile['name']} is {off:.1f} m beyond its reach; it must go there first")
        point = [float(at[0]), float(at[1])]
    return pile, point


def machine_goods_reach() -> float:
    import machine_goods
    return machine_goods.REACH_M


def dump(ctx: senses.Context, call: Call) -> dict[str, Any]:
    """Its hopper emptied ahead of it: the soil and sand back into what is
    carried and heaped on the ground there; the goods in it onto the
    stockpile within reach (the one named by `place`, if any, or the nearest,
    or a new heap), machine_goods.put."""
    r = ctx.routine
    if r is None or not r.carries():
        raise ValueError("it has no hopper to empty")
    sand, soil, kg = r.sand_m3, r.soil_m3, r.kg
    goods = {k: v for k, v in r.goods.items() if v > 0.0}
    if kg <= 0.0:
        return {"did": "dumped nothing: its hopper is empty"}
    point = senses.point_ahead(ctx, float(call.args.get("ahead_m", DIG_AHEAD_M)))
    if goods and ctx.goods is None:
        raise ValueError("it carries goods and the room keeps no account of goods")
    pile = None
    if ctx.goods is not None:
        pile, goods_point = _pile_for(ctx, call.args)
    else:
        goods_point = point
    # The ground takes its share back first; a hopper emptied before a
    # refusal read 0 of 20 kg while the load was still out of the ground
    # (the drone's first dump, 2026-09-25).
    if sand > 0.0 or soil > 0.0:
        _act(ctx, op="ground_return", sand_m3=sand, soil_m3=soil)
    onto = None
    if goods:
        put = ctx.goods.put(goods_point[0], goods_point[1], goods, named=pile["name"] if pile else None)
        onto = put["onto"]
    r.load_out()
    heaped = None
    if sand > 0.0 or soil > 0.0:
        reply = _act(ctx, op="deposit", at=point, radius_m=float(call.args.get("radius_m", DUMP_RADIUS_M)),
                     sand_m3=sand, soil_m3=soil, from_carried=True)
        heaped = reply.get("heaped")
    r.delivered(sand, soil, kg)
    _behave(ctx, call, "waiting", 2.0)
    words = ", ".join(f"{v:.1f} kg of {k}" for k, v in goods.items())
    r.note(f"dumped {kg:.1f} kg" + (f" ({words} onto {onto})" if goods else ""))
    return {"did": f"dumped {kg:.1f} kg" + (f", {words} onto {onto}" if goods else " on the ground ahead"),
            "heaped": heaped, "onto": onto, "load": r.load_reading()}


def take(ctx: senses.Context, call: Call) -> dict[str, Any]:
    """Goods off the stockpile within reach of it into its hopper: one
    substance if named, else whatever is there, up to the room its hopper has
    (machine_goods.take)."""
    r = ctx.routine
    if r is None or not r.carries():
        raise ValueError("it has no hopper to take into")
    if ctx.goods is None:
        raise ValueError("the room keeps no account of goods")
    room = r.load_room_kg()
    if room <= 1e-6:
        return {"did": "took nothing: its hopper is full", "load": r.load_reading()}
    pile, point = _pile_for(ctx, call.args)
    if pile is None:
        raise ValueError("there is no stockpile " + (f"at {call.args['place']}" if call.args.get("place")
                                                     else "within reach"))
    most = min(room, float(call.args["kg"])) if call.args.get("kg") is not None else room
    got = ctx.goods.take(point[0], point[1], most, substance=call.args.get("substance") or None,
                         named=pile["name"])
    taken = got["took"]
    if not taken:
        return {"did": f"took nothing: {got['from']} has none of "
                       + (str(call.args.get("substance")) if call.args.get("substance") else "anything")
                       + " on it", "load": r.load_reading(), "idle": True}
    r.load_in(0.0, 0.0, sum(taken.values()), taken)
    took_s = sum(taken.values()) * DIG_S_PER_KG
    _behave(ctx, call, "waiting", max(0.5, took_s))
    words = ", ".join(f"{v:.1f} kg of {k}" for k, v in taken.items())
    r.note(f"took {words} off {got['from']}")
    return {"did": f"took {words} off {got['from']}, in {took_s:.1f} s", "took": taken, "from": got["from"],
            "load": r.load_reading()}


#: A furnace's element rating when its design does not carry one. Every
#: furnace the Workshop builds does carry one (`element_w` on its program),
#: so this is only the fallback for a room that declared a chamber by hand.
HEATING_W = 5000.0
#: How long one spell of heating lasts. The element is switched on for this
#: long and nothing re-issues it until it has run out, because TWO
#: OVERLAPPING HEAT CALLS STACK: the engine adds their powers, so a furnace
#: told twice heats at double rate and settles at double the rise. Measured:
#: one call read heater_w = 5000, a second while it ran read 10000, and the
#: chamber went to 3353 C instead of 1686 -- past the thermal model's own
#: 3000 K validity ceiling, which it reports and does not refuse.
HEATING_S = 2.0
#: How near the mark counts as at it. The chamber loses heat to its lining
#: the whole time it is being heated, so holding an exact figure is not
#: something an element switching on and off can promise.
HEAT_SLACK_C = 15.0


def _chamber(ctx: senses.Context, name: str) -> dict[str, Any] | None:
    """What the engine says about this machine's chamber: the gas region its
    lining encloses. None when the room has no such region, which is a room
    whose furnace was declared wrong -- fracture_lab._chambers_exist refuses
    that before it can happen, so it means something built a spec by hand."""
    said = _act(ctx, op="thermo") or {}
    block = said.get("thermo") if isinstance(said.get("thermo"), dict) else said
    for region in (block.get("regions") or []):
        if region.get("name") == name:
            return region
    return None


def _how_hot(ctx: senses.Context, name: str) -> float | None:
    """What the engine says that chamber is at, in Celsius."""
    region = _chamber(ctx, name)
    t_k = (region or {}).get("temperature_k")
    return float(t_k) - 273.15 if isinstance(t_k, (int, float)) else None


def _needs_c(ctx: senses.Context, recipe: str) -> float:
    for row in (getattr(ctx.goods, "recipes", None) or []):
        if row.get("name") == recipe:
            return float(row.get("needs_c") or 0.0)
    return 0.0


def process(ctx: senses.Context, call: Call) -> dict[str, Any]:
    """One batch of its recipe: the inputs off its intake stockpile, the work
    drawn from its store, the outputs onto its output stockpile, and a wait
    for as long as the batch takes (machine_goods.convert). A machine that
    goes nowhere works this way; a machine with wheels can too, standing at
    a stockpile that is both its intake and its output."""
    r = ctx.routine
    if r is None:
        raise ValueError("it has no routine to say what it makes")
    if ctx.goods is None:
        raise ValueError("the room keeps no account of goods")
    recipe = str(call.args.get("recipe") or r.recipe or "")
    if not recipe:
        raise ValueError("it has no recipe: say which, or set one on its routine")
    ax, az = ctx.at()
    intake = ctx.goods.stockpile_near(ax, az, named=str(call.args.get("intake") or r.intake or "") or None)
    if intake is None:
        raise ValueError("its intake stockpile is not within reach")
    output_name = str(call.args.get("output") or r.output or "") or None
    output = ctx.goods.stockpile_near(ax, az, named=output_name) if output_name else intake
    if output is None:
        raise ValueError("its output stockpile is not within reach")
    store = senses._store(ctx)
    batch = float(call.args.get("kg") or r.batch_kg)

    # IT HAS TO BE HOT. A recipe that needs heat says what temperature its
    # process runs at, and the engine says what the chamber IS at -- not a
    # timer, not a flag. Below the mark the furnace heats instead of working:
    # it draws from its store and puts that into the gas its lining encloses.
    #
    # The lining leaks the whole time, which is why a furnace left alone goes
    # cold within a minute and why coming back to a cold one costs again.
    wants_c = _needs_c(ctx, recipe)
    chamber = r.chamber or ""
    if wants_c > 0.0 and not chamber:
        # SAID, NOT WORKED COLD. A recipe with a temperature needs something
        # to be hot IN, and a machine with no chamber has not got one. The
        # bench will not build that pairing and the generator will not stand
        # it, so reaching here means a room was written by hand -- and the
        # answer it deserves is the reason, not 1.5 kg of copper smelted in
        # the open air at twenty degrees.
        return {"did": f"cannot work {recipe}: it needs {wants_c:.0f} C and this machine has no "
                       f"chamber to make hot. That wants an electric furnace", "failed": True}
    # IS THERE ANYTHING TO WORK? Asked BEFORE the element is lit, because a
    # furnace warming an empty box is 5 kW spent on nothing, and it never
    # stops: it cannot reach its temperature and go quiet, it just heats, and
    # loses it, and heats again. Six of them doing that drained the yard's
    # whole farm in two minutes and left every machine in the valley dead.
    # The trial converts a copy and takes nothing, so asking is free.
    holds = intake.setdefault("holds", {})
    trial = ctx.goods.convert(recipe, dict(holds), batch)
    if not trial["made"]:
        return {"did": f"made nothing: {intake['name']} has no " + ", ".join(trial.get("missing") or []) + " on it",
                "idle": True}

    if wants_c > 0.0 and chamber:
        region = _chamber(ctx, chamber)
        if region is None:
            return {"did": f"cannot heat: this room has no chamber called {chamber!r}",
                    "failed": True}
        now_c = float(region.get("temperature_k") or 0.0) - 273.15
        if now_c < wants_c - HEAT_SLACK_C:
            watts = float(r.element_w or HEATING_W)
            # ONLY IF THE ELEMENT IS OFF. Heat calls stack -- a second one
            # issued while the first is still running adds its power to it --
            # so the engine's own reading of what the element is doing is
            # what decides, rather than a clock on this side that a paused
            # routine or a re-entered turn would get wrong.
            if float(region.get("heater_w") or 0.0) > 1e-6:
                return {"did": f"heating to work {recipe}: {now_c:.0f} C of {wants_c:.0f} C",
                        "idle": True}
            joules = watts * HEATING_S
            if store is not None:
                have = float(store.get("charge_j") or 0.0)
                if have + 1e-9 < joules:
                    return {"did": f"cannot heat: its battery has {have:.0f} J and a spell of "
                                   f"heating takes {joules:.0f} J", "failed": True}
                _act(ctx, op="draw", store=store["id"], joules=joules)
            _act(ctx, op="heat", target=chamber, power_w=watts, seconds=HEATING_S)
            r.note(f"heating for {recipe}: {now_c:.0f} C of {wants_c:.0f} C")
            return {"did": f"heating to work {recipe}: {now_c:.0f} C of {wants_c:.0f} C, "
                           f"{watts / 1000:.1f} kW drawn", "idle": True}

    # The work must be in the battery before anything is worked.
    if store is not None and trial["work_j"] > 0.0:
        have = float(store.get("charge_j") or 0.0)
        if have + 1e-9 < trial["work_j"]:
            scale = have / trial["work_j"]
            if scale * trial["kg_in"] < 0.01:
                return {"did": f"made nothing: its battery has {have:.0f} J and a batch takes "
                               f"{trial['work_j']:.0f} J", "failed": True}
            trial = ctx.goods.convert(recipe, dict(holds), trial["kg_in"] * scale * 0.999)
    made = ctx.goods.convert(recipe, holds, trial["kg_in"])
    drawn = 0.0
    if store is not None and made["work_j"] > 0.0:
        _act(ctx, op="draw", store=store["id"], joules=made["work_j"])
        drawn = made["work_j"]
    ctx.goods.put(float(output["at_m"][0]), float(output["at_m"][1]), made["made"], named=output["name"])
    r.made_kg += sum(made["made"].values())
    r.batches += 1
    # Somebody saw this happen, and that is how a recipe is learned.
    if getattr(ctx.goods, "on_made", None) is not None:
        ctx.goods.on_made(recipe, dict(made["made"]), dict(made["used"]))
    if callable(getattr(ctx.goods, "on_machine_made", None)):
        ctx.goods.on_machine_made(recipe, dict(made["made"]), dict(made["used"]),
                                  machine=ctx.program["name"], batch=r.batches,
                                  declaration=r.declaration_digest, drawn_j=drawn)
    took_s = max(0.5, made["took_s"])
    _behave(ctx, call, "waiting", min(60.0, took_s))
    words_in = ", ".join(f"{v:.2f} kg of {k}" for k, v in made["used"].items())
    words_out = ", ".join(f"{v:.2f} kg of {k}" for k, v in made["made"].items())
    r.note(f"{recipe}: {words_in} into {words_out}, {drawn:.0f} J")
    return {"did": f"worked {words_in} into {words_out} by {recipe}, drawing {drawn:.0f} J, in {took_s:.1f} s",
            "made": made["made"], "used": made["used"], "waste_kg": round(made.get("waste_kg", 0.0), 3),
            "drawn_j": round(drawn), "took_s": round(took_s, 1), "onto": output["name"]}


def dock(ctx: senses.Context, call: Call) -> dict[str, Any]:
    """Goods passed through a pair of mouths (docs/machine-world.md, "Devices
    that pair"): from one of this machine's ports into a port of another
    machine that it is docked to. Which of its ports, and which way the goods
    go, follows from the machine's own ports -- an `out` port gives, an `in`
    port takes -- so a rover standing at a smelter releases its ore without
    being told where the smelter's intake is.

    Nothing here is a place. A dock is to a THING: the two mouths have to be
    within machine_ports.DOCK_M of each other and turned towards each other,
    which is what the page draws in green. A dock that is not made says why and
    does nothing.

    It never answers `idle`, unlike `take` and `process`. An idle answer is one
    the runner asks again next tick without counting it, and a step that is
    only ever idle can never end -- a machine that has stopped a little too far
    off would stand at the dock for ever. So this answers plainly either way,
    and a routine bounds the step itself: `{"do": "dock", "until": 6,
    "repeat": true}` is "spend six seconds passing what you can, then go on"."""
    import machine_ports
    if ctx.ports is None or not ctx.ports:
        raise ValueError("this room has no ports on its machines")
    machine = str(ctx.program.get("name") or "")
    mine = [p for p in ctx.ports.of(machine) if p.settled()]
    if not mine:
        raise ValueError("this machine has no ports to dock with")
    wanted = str(call.args.get("port") or "")
    if wanted:
        # Told which mouth to work through: one of its own, or the other
        # machine's, in which case its own is whichever one could fit that.
        named = ctx.ports.by_name(wanted)
        if named is None:
            raise ValueError(f"the room has no port called {wanted!r}")
        mine = ([p for p in mine if p is named] if named.machine == machine
                else [p for p in mine if p.flow != named.flow])
        if not mine:
            raise ValueError(f"this machine has no port that fits {wanted!r}")
    said: list[str] = []
    for port in mine:
        docked, near, why, _ = ctx.ports.pair_of(port)
        if docked is None:
            said.append(f"{port.name} is docked to nothing"
                        + (f" ({near.name}: {why})" if near is not None and why else ""))
            continue
        if wanted and ctx.ports.by_name(wanted).machine != machine and docked.name != wanted:
            said.append(f"{port.name} is docked to {docked.name}, not to {wanted}")
            continue
        giving, taking = (port, docked) if port.flow == "out" else (docked, port)
        passed = machine_ports.pass_goods(ctx.ports, giving, taking,
                                          float(call.args["kg"]) if call.args.get("kg") is not None else None)
        if not passed["moved"]:
            said.append(f"{giving.name} passed nothing to {taking.name}: {passed['why']}")
            continue
        kg = sum(passed["moved"].values())
        words = ", ".join(f"{v:.1f} kg of {k}" for k, v in passed["moved"].items())
        # As long as a scoop of the same mass takes, so a dock is watchable
        # rather than instant: the same declared rate the dig and take tools use.
        took_s = max(0.5, kg * DIG_S_PER_KG)
        _behave(ctx, call, "waiting", took_s)
        if ctx.routine is not None:
            ctx.routine.note(f"docked {port.name} to {docked.name}: {words}")
        return {"did": f"passed {words} from {giving.name} into {taking.name}, in {took_s:.1f} s",
                "moved": passed["moved"], "from": giving.name, "into": taking.name,
                "load": ctx.routine.load_reading() if ctx.routine is not None and ctx.routine.carries() else None}
    # Nothing passed, and it stands still for a moment before it is asked
    # again. Without that its reflexes drive it off between tries and it
    # wanders away from the very mouth it came to (measured in the mine: the
    # rover was 5 m from the smelter by the end of its own dock step).
    _behave(ctx, call, "waiting", HOLD_AT_A_DOCK_S)
    return {"did": "passed nothing: " + "; ".join(said), "moved": {}}


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    run: Callable[[senses.Context, Call], dict[str, Any]]
    params: dict[str, Any]                       # JSON schema properties, for a model that fills them
    # Whether a decider may pick it when something happens (a routine's own
    # steps may use the rest).
    for_deciders: bool = True


# An argument a decider fills is asked as a question of its own in the same
# call: `levels` (ordered, low to high) makes it a score, `options` (a name
# for each value) a choice, and `options: "places"` a choice among the places
# the machine knows and the person. An argument with neither -- a point in
# the world -- a decider cannot fill; the routine and a person can.
_FOR_S = {"for_s": {"type": "number", "description": "for how many seconds",
                    "levels": [{"value": 1.5, "words": "a moment, a second and a half"},
                               {"value": 3.0, "words": "a few seconds, three"},
                               {"value": 6.0, "words": "a while, six seconds"},
                               {"value": 12.0, "words": "a good while, twelve seconds"}]}}
_WHERE = {"place": {"type": "string", "description": "a place it knows by name, or 'person'", "options": "places"},
          "port": {"type": "string", "description": "a port on another machine, by name: where it is now",
                   "options": "ports"},
          "point": {"type": "array", "items": {"type": "number"}, "description": "[x, z] in metres"},
          "bearing_deg": {"type": "number", "description": "degrees from its front, positive to its left",
                          "options": {"straight ahead": 0.0, "a little to its left": 30.0, "to its left": 90.0,
                                      "behind it, round to the left": 150.0, "behind it, round to the right": -150.0,
                                      "to its right": -90.0, "a little to its right": -30.0}},
          "distance_m": {"type": "number", "description": "how far, metres",
                         "levels": [{"value": 1.0, "words": "close, a metre"}, {"value": 3.0, "words": "a few metres"},
                                    {"value": 6.0, "words": "some way, six metres"}]}}
_SUBSTANCE = {"substance": {"type": "string", "description": "which substance to take, or none for whatever "
                                                             "is there", "options": "substances"}}
# How far off a machine told to approach something stops (LiveWorld, kNearM).
NEAR_M = 1.0
_SHORT = {"stop_at_m": {"type": "number", "description": "how far from the place to stop, metres, when a metre "
                                                         "is too close: ground it is working, or anything it "
                                                         "must reach without standing on"}}
_DIG = {"place": _WHERE["place"],
        "depth_m": {"type": "number", "description": "how deep the scoop bites, metres",
                    "levels": [{"value": 0.08, "words": "a shallow scrape"}, {"value": 0.15, "words": "a scoop"},
                               {"value": 0.3, "words": "a deep bite"}]}}

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
    Tool("rise", "Climb, if it flies: over something in the way, or to see further. It holds the height it "
                 "reaches. A machine on wheels cannot.", rise, _FOR_S),
    Tool("descend", "Come down, if it flies: to reach the ground, or under something. Held long enough it "
                    "lands. A machine on wheels cannot.", descend, _FOR_S),
    Tool("face", "Turn on the spot until its front is towards a place, the person, a point or a bearing.", face,
         {**_WHERE, **_FOR_S}),
    Tool("go_to", "Go to a place it knows, the person, a point or a bearing, and stop a metre off, or stand "
                  "further out if it is told how far off to stop.", go_to, {**_WHERE, **_FOR_S, **_SHORT}),
    Tool("dig", "Take one scoop into its hopper, drawing the work from its battery: at the place it is working, "
                "if it is given one, and otherwise straight ahead of it.", dig, _DIG),
    Tool("dump", "Empty its hopper ahead of it: soil onto the ground, goods onto the stockpile there (a "
                 "place it knows, or the nearest, or a new heap).", dump, {"place": _WHERE["place"]}),
    Tool("take", "Take goods off the stockpile within reach of it into its hopper: one substance, or "
                 "whatever is there.", take, {"place": _WHERE["place"], **_SUBSTANCE}),
    Tool("dock", "Pass goods through its port into the port of the machine it is standing at: its store "
                 "into the other's intake, or the other's outlet into its store. Their two mouths have to "
                 "be close and turned towards each other.", dock, {"port": _WHERE["port"]}),
    Tool("process", "Work one batch of its recipe: its intake stockpile's goods into its output "
                    "stockpile's, drawing the work from its battery.", process, {}, for_deciders=False),
    Tool("survey", "Say what is known of a place, or of where it stands: the ground there, what is on it, and "
                   "how much of it nobody has seen yet. It reports; going there is what reveals it.",
         survey, {**_WHERE, "radius_m": {"type": "number", "description": "how wide to look, metres"}}),
    Tool("carry_on", "Ask nothing more of it: its routine and its reflexes have it back.", carry_on, {}),
)}


def catalogue(for_deciders: bool = True) -> list[dict[str, Any]]:
    return [{"name": t.name, "description": t.description, "params": t.params}
            for t in TOOLS.values() if t.for_deciders or not for_deciders]


def argument_questions(places: dict[str, Any] | None = None,
                       substances: list[str] | None = None,
                       ports: list[str] | None = None) -> dict[str, Any]:
    """One typed question per argument a decider can fill, across the tools it
    may pick, keyed `arg_<name>`: asked in the same call as the tool, so a
    decider answers everything at once and only the picked tool's are read
    (a place is a choice among the places the machine knows and the person;
    `bearing_deg` a choice of directions; a duration or a depth a score)."""
    out: dict[str, Any] = {}
    for tool in TOOLS.values():
        if not tool.for_deciders:
            continue
        for name, spec in tool.params.items():
            key = f"arg_{name}"
            if key in out:
                continue
            uses = ", ".join(t.name for t in TOOLS.values() if t.for_deciders and name in t.params)
            if spec.get("options") == "places":
                names = [str(p) for p in (places or {})] + ["person"]
                out[key] = {"type": "choice",
                            "instructions": f"`{name}` for {uses}: where it should go or look, if that tool is "
                                            "picked. `senses.places` says how far and which way each lies.",
                            "criteria": {n: ("the person, where they stand" if n == "person" else f"the place called {n}")
                                         for n in names}}
            elif spec.get("options") == "substances":
                if not substances:
                    continue
                out[key] = {"type": "choice",
                            "instructions": f"`{name}` for {uses}: {spec.get('description', name)}, if that tool "
                                            "is picked. `senses.goods` says what each stockpile holds.",
                            "criteria": {s: f"the substance called {s}" for s in substances}}
            elif spec.get("options") == "ports":
                if not ports:
                    continue
                out[key] = {"type": "choice",
                            "instructions": f"`{name}` for {uses}: {spec.get('description', name)}, if that tool "
                                            "is picked. `senses.ports` says where each mouth is and what it takes.",
                            "criteria": {p: f"the port called {p}" for p in ports}}
            elif isinstance(spec.get("options"), dict):
                out[key] = {"type": "choice",
                            "instructions": f"`{name}` for {uses}: {spec.get('description', name)}, if that tool "
                                            "is picked.",
                            "criteria": {words: f"{name} = {value:g}" for words, value in spec["options"].items()}}
            elif spec.get("levels"):
                out[key] = {"type": "score",
                            "instructions": f"`{name}` for {uses}: {spec.get('description', name)}, if that tool "
                                            "is picked.",
                            "criteria": [level["words"] for level in spec["levels"]]}
    return out


def arguments_for(tool_name: str, answers: dict[str, Any], places: dict[str, Any] | None = None,
                  substances: list[str] | None = None, ports: list[str] | None = None) -> dict[str, Any]:
    """The picked tool's arguments, from the answers to its argument questions:
    a choice's value, a score's nearest level. An argument not answered is
    left to the tool's own default."""
    tool = TOOLS.get(tool_name)
    if tool is None:
        return {}
    args: dict[str, Any] = {}
    for name, spec in tool.params.items():
        answer = answers.get(f"arg_{name}")
        if not isinstance(answer, dict):
            continue
        if spec.get("options") == "places":
            choice = answer.get("choice")
            if choice == "person" or (places and choice in places):
                args[name] = choice
        elif spec.get("options") == "substances":
            choice = answer.get("choice")
            if substances and choice in substances:
                args[name] = choice
        elif spec.get("options") == "ports":
            choice = answer.get("choice")
            if ports and choice in ports:
                args[name] = choice
        elif isinstance(spec.get("options"), dict):
            choice = answer.get("choice")
            if choice in spec["options"]:
                args[name] = spec["options"][choice]
        elif spec.get("levels") and answer.get("score") is not None:
            levels = spec["levels"]
            try:
                index = min(len(levels) - 1, max(0, round(float(answer["score"]))))
            except (TypeError, ValueError):
                continue
            args[name] = levels[index]["value"]
    # A bearing without a place is a direction; a place or a port, being
    # somewhere already, makes the bearing moot.
    if "place" in args or "port" in args:
        args.pop("bearing_deg", None)
        args.pop("distance_m", None)
    if "port" in args:
        args.pop("place", None)
    return args


def described(tool_name: str, args: dict[str, Any]) -> str:
    """A call in a few words: "go to the person", "turn left for 3 s"."""
    words = tool_name.replace("_", " ")
    bits = []
    if args.get("port"):
        bits.append(f"the {args['port']}")
    elif args.get("place"):
        bits.append(f"the {args['place']}" if args["place"] == "person" else str(args["place"]))
    elif "bearing_deg" in args:
        bits.append(f"{args.get('distance_m', 3):g} m at {args['bearing_deg']:+g} deg")
    if "depth_m" in args:
        bits.append(f"{args['depth_m']:g} m deep")
    if args.get("substance"):
        bits.append(str(args["substance"]))
    if "for_s" in args:
        bits.append(f"for {args['for_s']:g} s")
    return words + (" " + ", ".join(bits) if bits else "")


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
