"""What a routine can watch for (docs/machine-world.md, "A routine that
responds"): named conditions read off a machine's senses, its hopper and
the room's goods, in words a person or a model writes.

A condition is a name with its arguments, or a combination:

    "hopper_full"                                  a bare name
    {"is": "battery_below", "share": 0.3}          a name with arguments
    {"is": "pile_has", "place": "source", "substance": "copper", "kg": 5}
    {"not": "person_near"}
    {"all": ["hopper_full", {"is": "at_place", "place": "depot"}]}
    {"any": [...]}

A routine puts one on a step (`when`: the step is skipped unless it holds;
`unless`: skipped while it holds) or in a `watch` (docs and
machine_routine): steps run the moment the condition comes to hold,
interrupting whatever the routine was doing, and then the routine goes on.
Every condition here reads the same senses the deciders read
(machine_senses); a new one is one entry in CONDITIONS. A condition that
needs what the machine lacks -- a hopper, a place -- is simply false.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Callable

import machine_senses as senses

PERSON_NEAR_M = 4.0
AT_PLACE_M = 1.5


@dataclass(frozen=True)
class Condition:
    name: str
    description: str
    holds: Callable[[senses.Context, dict[str, Any]], bool]
    params: dict[str, str]                       # argument name -> what it is, for a model


def _routine(ctx: senses.Context) -> Any:
    return ctx.routine


def _place_xz(ctx: senses.Context, args: dict[str, Any]) -> list[float] | None:
    r = _routine(ctx)
    place = args.get("place")
    if place == "person":
        at = (ctx.person or {}).get("standing_m") if isinstance(ctx.person, dict) else None
        return [float(at[0]), float(at[2])] if isinstance(at, (list, tuple)) and len(at) == 3 else None
    if r is None or not place or place not in (r.places or {}):
        return None
    return [float(v) for v in r.places[place]]


def _pile(ctx: senses.Context, args: dict[str, Any]) -> dict[str, Any] | None:
    """The stockpile a condition means: at a place it knows, by a stockpile's
    own name, or the one within reach of the machine."""
    if ctx.goods is None:
        return None
    if args.get("place"):
        xz = _place_xz(ctx, args)
        return ctx.goods.stockpile_near(xz[0], xz[1], reach_m=0.5) if xz else None
    if args.get("stockpile"):
        return ctx.goods.by_name(str(args["stockpile"]))
    ax, az = ctx.at()
    return ctx.goods.stockpile_near(ax, az)


def _kg_of(pile: dict[str, Any] | None, substance: str | None) -> float:
    holds = (pile or {}).get("holds") or {}
    if substance:
        return float(holds.get(substance, 0.0))
    return float(sum(float(v) for v in holds.values()))


def hopper_full(ctx, args):
    r = _routine(ctx)
    return r is not None and r.load_full()


def hopper_empty(ctx, args):
    r = _routine(ctx)
    return r is not None and r.carries() and r.kg <= 0.0


def hopper_has(ctx, args):
    r = _routine(ctx)
    if r is None:
        return False
    kg = float(args.get("kg", 0.0) or 0.0)
    if args.get("substance"):
        return float(r.goods.get(str(args["substance"]), 0.0)) > max(kg, 0.0)
    return r.kg > max(kg, 0.0)


def battery_below(ctx, args):
    return float(ctx.program.get("charge_share") or 0.0) < float(args.get("share", 0.3))


def battery_above(ctx, args):
    return float(ctx.program.get("charge_share") or 0.0) > float(args.get("share", 0.6))


def pile_empty(ctx, args):
    pile = _pile(ctx, args)
    return pile is not None and _kg_of(pile, args.get("substance")) <= 1e-9


def pile_has(ctx, args):
    pile = _pile(ctx, args)
    return pile is not None and _kg_of(pile, args.get("substance")) >= max(float(args.get("kg", 0.0) or 0.0), 1e-9)


def water_ahead(ctx, args):
    return any(s.get("sees") for s in ctx.program.get("sensors") or [])


def person_near(ctx, args):
    at = (ctx.person or {}).get("standing_m") if isinstance(ctx.person, dict) else None
    if not isinstance(at, (list, tuple)) or len(at) != 3:
        return False
    ax, az = ctx.at()
    return math.hypot(float(at[0]) - ax, float(at[2]) - az) <= float(args.get("m", PERSON_NEAR_M))


def at_place(ctx, args):
    xz = _place_xz(ctx, args)
    if xz is None:
        return False
    ax, az = ctx.at()
    return math.hypot(xz[0] - ax, xz[1] - az) <= float(args.get("within_m", AT_PLACE_M))


def night(ctx, args):
    sun = senses.sense_sun(ctx) if ctx.ask else {}
    return bool(sun.get("declared", True)) and "daylight" in sun and not sun["daylight"]


def day(ctx, args):
    sun = senses.sense_sun(ctx) if ctx.ask else {}
    return bool(sun.get("daylight"))


def stalled(ctx, args):
    controls = {c.get("id"): c for c in (ctx.machines or {}).get("controls") or []}
    ids = list(ctx.program.get("rotors") or []) or [ctx.program.get("left"), ctx.program.get("right")]
    return any(str((controls.get(i) or {}).get("condition") or "").startswith("stalled") for i in ids)


def struck(ctx, args):
    parts = set(ctx.program.get("parts") or [])
    return any(i.get("struck") in parts or i.get("by") in parts for i in ctx.impacts or [])


def resting(ctx, args):
    return ctx.program.get("doing") == "resting"


def asked_by_someone(ctx, args):
    asked = ctx.program.get("asked")
    return isinstance(asked, dict) and asked.get("by") not in (None, "routine")


CONDITIONS: dict[str, Condition] = {c.name: c for c in (
    Condition("hopper_full", "Its hopper is full (95% of what it carries).", hopper_full, {}),
    Condition("hopper_empty", "Its hopper is empty.", hopper_empty, {}),
    Condition("hopper_has", "Its hopper holds more than `kg` of `substance` (or of anything).", hopper_has,
              {"substance": "a substance, optional", "kg": "kilograms, optional"}),
    Condition("battery_below", "Its battery is below `share` of full.", battery_below, {"share": "0 to 1"}),
    Condition("battery_above", "Its battery is above `share` of full.", battery_above, {"share": "0 to 1"}),
    Condition("pile_empty", "The stockpile at `place` (or named `stockpile`, or the one within reach) holds "
                            "none of `substance` (or nothing at all).", pile_empty,
              {"place": "a place it knows", "stockpile": "a stockpile's name", "substance": "optional"}),
    Condition("pile_has", "The stockpile at `place` (or named `stockpile`, or within reach) holds at least "
                          "`kg` of `substance` (or of anything).", pile_has,
              {"place": "a place it knows", "stockpile": "a stockpile's name", "substance": "optional",
               "kg": "kilograms, optional"}),
    Condition("water_ahead", "One of its water sensors sees water.", water_ahead, {}),
    Condition("person_near", "A person is within `m` metres (4 by default).", person_near, {"m": "metres"}),
    Condition("at_place", "It is within `within_m` (1.5 m) of `place`.", at_place,
              {"place": "a place it knows, or person", "within_m": "metres"}),
    Condition("night", "The room's sun is down.", night, {}),
    Condition("day", "The room's sun is up.", day, {}),
    Condition("stalled", "A wheel or a rotor has stalled.", stalled, {}),
    Condition("struck", "Something struck it, or it ran into something, this step.", struck, {}),
    Condition("resting", "Its program is resting for want of charge.", resting, {}),
    Condition("asked_by_someone", "Someone other than its routine has it: a person, a decider.", asked_by_someone, {}),
)}


def catalogue() -> list[dict[str, Any]]:
    return [{"name": c.name, "description": c.description, "params": c.params} for c in CONDITIONS.values()]


def checked(given: Any, depth: int = 0) -> Any:
    """A condition as written, checked: a name the machines know with its
    arguments, or not/all/any over conditions. Raises with what is wrong."""
    if depth > 4:
        raise ValueError("a condition nests at most four deep")
    if isinstance(given, str):
        if given not in CONDITIONS:
            raise ValueError(f"there is no condition called {given!r}; the conditions are "
                             + ", ".join(sorted(CONDITIONS)))
        return given
    if not isinstance(given, dict) or not given:
        raise ValueError("a condition is a name, {is: name, ...arguments}, {not: c}, {all: [...]} or {any: [...]}")
    if "not" in given:
        if len(given) != 1:
            raise ValueError("{not: c} says nothing else")
        return {"not": checked(given["not"], depth + 1)}
    for key in ("all", "any"):
        if key in given:
            if len(given) != 1 or not isinstance(given[key], list) or not given[key] or len(given[key]) > 8:
                raise ValueError(f"{{{key}: [...]}} is a list of 1 to 8 conditions and nothing else")
            return {key: [checked(c, depth + 1) for c in given[key]]}
    name = given.get("is")
    if name not in CONDITIONS:
        raise ValueError(f"there is no condition called {name!r}; the conditions are " + ", ".join(sorted(CONDITIONS)))
    unknown = set(given) - {"is"} - set(CONDITIONS[name].params)
    if unknown:
        raise ValueError(f"{name} takes {sorted(CONDITIONS[name].params) or 'no arguments'}, not {sorted(unknown)}")
    out: dict[str, Any] = {"is": name}
    for key, value in given.items():
        if key == "is":
            continue
        if key in ("kg", "share", "m", "within_m"):
            try:
                out[key] = float(value)
            except (TypeError, ValueError):
                raise ValueError(f"{name}'s {key} is a number") from None
            if not (0.0 <= out[key] <= 1e6) or (key == "share" and out[key] > 1.0):
                raise ValueError(f"{name}'s {key} is out of range")
        else:
            out[key] = " ".join(str(value).split())[:64]
    return out


def holds(ctx: senses.Context, cond: Any) -> bool:
    """Whether a checked condition holds now. A fault in reading it is false,
    never a stopped room."""
    try:
        if isinstance(cond, str):
            return bool(CONDITIONS[cond].holds(ctx, {}))
        if "not" in cond:
            return not holds(ctx, cond["not"])
        if "all" in cond:
            return all(holds(ctx, c) for c in cond["all"])
        if "any" in cond:
            return any(holds(ctx, c) for c in cond["any"])
        return bool(CONDITIONS[cond["is"]].holds(ctx, {k: v for k, v in cond.items() if k != "is"}))
    except Exception:
        return False


def described(cond: Any) -> str:
    """A condition in a few words: "pile at source empty", "not person near"."""
    if isinstance(cond, str):
        return cond.replace("_", " ")
    if "not" in cond:
        return "not " + described(cond["not"])
    if "all" in cond:
        return " and ".join(described(c) for c in cond["all"])
    if "any" in cond:
        return " or ".join(described(c) for c in cond["any"])
    words = str(cond.get("is", "")).replace("_", " ")
    bits = [f"{k} {v}" for k, v in cond.items() if k != "is"]
    return words + (" (" + ", ".join(bits) + ")" if bits else "")
