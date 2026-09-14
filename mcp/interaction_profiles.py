"""How a person uses a thing, checked against what is built.

A profile says which bodies are one object, which part a hand takes and which
way it is drawn, which joint lets go and which joints hold the draw -- and never
what the physics does. How deep a point goes and what comes loose are the
ground's, what a bow shoots with is its limbs'. What a tool's profile may say is
how the PERSON uses it (`use`): what their click is called, how the hand swings
and pries it, how far off it can be brought down and whether holding the button
keeps going -- each within the bounded hand's own limits. docs/interaction-profiles.md.

Two templates, each a way of using things the page knows how to drive:

    draw-and-release  a bow: a part drawn back against elastic joints and a
                      one-way nock that lets what is shot go by itself
    swing-and-lever   a pick: a tool with a point (a tool_point) swung so the
                      point comes down on the ground, and pried to break the
                      ground out (docs/ground-work.md)

Shared by the MCP server (mcp/banjo_mcp.py, in metres) and the playground's
room (playground/fracture_lab.py, in millimetres), so a profile is held to one
set of rules whoever wrote it: a model through the MCP's `interaction` tool, or
a room authored by hand. What the two spell differently -- how far the hand asks
to draw, and how fast -- each checks in its own units; everything here is names
and directions. Nothing here imports the engine.
"""
from __future__ import annotations

import math
from typing import Any, Iterable

# The interaction templates the page knows how to drive. A profile names one;
# the controls are the page's and what happens is the engine's.
TEMPLATES = ("draw-and-release", "swing-and-lever")
KEYS = {
    "draw-and-release": {"object", "template", "parts", "draw", "nock", "limbs", "projectile"},
    "swing-and-lever": {"object", "template", "parts", "tool", "use"},
}

# How a person uses a tool that works the ground, when its profile does not say:
# what the click is called and how a result is said; the swing -- raised back
# over the shoulder and brought down at the hand's speed -- and the pry after
# it, turned about where the point went in; how far in front of them it can be
# brought down (a haft and an arm at most, and not at their own feet); and
# whether holding the button goes on. One copy, read by the MCP's trial and by
# the playground's page and server alike, so what a trial measured is what the
# person gets. The bounds are the hand's: live_session's strike op refuses
# anything outside 0.3 to 12 m/s, a raise up to 170 degrees, a pry of 5 to 80.
# The nearest it comes down by default is 1.15 m: in the page, on untouched
# ground, every swing from 1.2 m to 1.84 m in front dug, while at 1.05-1.1 m
# about one in several stopped short -- its point 1 cm above the ground and 4 cm
# before the aim -- and the MCP's trial stands 1.2 m back (banjo_mcp STAND_BACK_M).
TOOL_USE_DEFAULTS = {"label": "Dig here", "past": "dug",
                     "swing": {"speed_m_s": 4.0, "raise_deg": 110.0},
                     "lever": {"speed_m_s": 1.2, "lever_deg": 40.0}, "pry": True,
                     "reach_m": [1.15, 2.0], "repeat": True}
_USE_KEYS = set(TOOL_USE_DEFAULTS)
# How fast the HAND moves along a swing; the point arrives two to three times
# faster (a 4 m/s swing brings the pick's point down at 9.2 m/s). Measured in
# the live room with the world's pick (the scratchpad's probe_swing_speed.py):
# at 4 and 5 m/s it dug; at 6 and 8 m/s the tool lagged the swing and stopped
# short above the ground; at 9.8 m/s -- the point speed the room's chat put
# here -- it met the sand side-on and glanced. So no faster than 5.
_SWING_BOUNDS = {"speed_m_s": (1.0, 5.0), "raise_deg": (30.0, 170.0)}
_LEVER_BOUNDS = {"speed_m_s": (0.3, 4.0), "lever_deg": (5.0, 80.0)}
REACH_BOUNDS_M = (0.3, 2.0)


def tool_use(profile: dict[str, Any] | None) -> dict[str, Any]:
    """What a tool's profile says of how it is used, with what it leaves unsaid
    filled in from TOOL_USE_DEFAULTS: `lever` is None for a tool that is only
    swung, never pried."""
    said = (profile or {}).get("use") or {}
    out = {"label": said.get("label", TOOL_USE_DEFAULTS["label"]),
           "past": said.get("past", TOOL_USE_DEFAULTS["past"]),
           "swing": {**TOOL_USE_DEFAULTS["swing"], **(said.get("swing") or {})},
           "lever": (None if said.get("pry") is False
                     else {**TOOL_USE_DEFAULTS["lever"], **(said.get("lever") or {})}),
           "reach_m": list(said.get("reach_m") or TOOL_USE_DEFAULTS["reach_m"]),
           "repeat": bool(said.get("repeat", TOOL_USE_DEFAULTS["repeat"]))}
    return out


def _use_checked(name: str, use: Any) -> dict[str, Any]:
    """A tool profile's `use`, held to the hand's bounds: only what was said
    is kept, so a profile says no more than its author did."""
    if not isinstance(use, dict):
        raise ValueError(f"{name}: use is an object: how the person uses it")
    unknown = set(use) - _USE_KEYS
    if unknown:
        raise ValueError(f"{name}: use has no {sorted(unknown)}; it may say {sorted(_USE_KEYS)}")
    out: dict[str, Any] = {}
    for key, most in (("label", 40), ("past", 24)):
        if key in use:
            words = use[key]
            if not isinstance(words, str) or not words.strip() or len(words.strip()) > most:
                raise ValueError(f"{name}: use {key} is a few words, at most {most} letters")
            out[key] = words.strip()
    for key, bounds in (("swing", _SWING_BOUNDS), ("lever", _LEVER_BOUNDS)):
        if key not in use:
            continue
        motion = use[key]
        if not isinstance(motion, dict) or not set(motion) <= set(bounds):
            raise ValueError(f"{name}: use {key} is {{{', '.join(sorted(bounds))}}}")
        checked: dict[str, float] = {}
        for field, (low, high) in bounds.items():
            if field not in motion:
                continue
            value = motion[field]
            if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"{name}: use {key} {field} is {low:g} to {high:g}, the hand's "
                                 f"own bounds, not {value!r}")
            checked[field] = float(value)
        out[key] = checked
    if "reach_m" in use:
        reach = use["reach_m"]
        low, high = REACH_BOUNDS_M
        if (not isinstance(reach, (list, tuple)) or len(reach) != 2
                or not all(type(v) in (int, float) and math.isfinite(v) for v in reach)
                or not low <= reach[0] < reach[1] <= high):
            raise ValueError(f"{name}: use reach_m is [nearest, furthest] in front of the person, "
                             f"between {low:g} and {high:g} m -- a haft and an arm at most")
        out["reach_m"] = [float(reach[0]), float(reach[1])]
    for key, meaning in (("repeat", "whether holding the button keeps going"),
                         ("pry", "whether the point is pried once it is in; false for a tool "
                                 "that is only swung")):
        if key in use:
            if not isinstance(use[key], bool):
                raise ValueError(f"{name}: use {key} is true or false: {meaning}")
            out[key] = use[key]
    return out


def check(profile: Any, bodies: set[str], joints: list[dict[str, Any]],
          which: str = "the interaction", points: Iterable[str] = ()) -> dict[str, Any]:
    """A profile's references, checked against a room's bodies and joints.

    `joints` are in the room's spelling: each has a `kind` ("fixing",
    "elastic", ...), its two ends `a` and `b`, and a fixing its `axis` and
    `comes_off_n`. `points` names the bodies that carry a point that can go
    into the ground (a tool_point). Returns the object's name, its template and
    parts, and what the template needs: a draw-and-release its draw's part and
    unit axis, the nock, the limbs and the projectile; a swing-and-lever its
    tool. Raises ValueError saying what is wrong, where whoever wrote it can be
    told: a bow whose nock is named wrong is a bow that cannot be loosed, and
    that reads as the physics failing.
    """
    if not isinstance(profile, dict):
        raise ValueError(f"{which} is not an object")
    name = str(profile.get("object") or "").strip()[:80]
    if not name:
        raise ValueError(f"{which} needs an object: what the thing is called")
    template = profile.get("template")
    if template not in TEMPLATES:
        raise ValueError(f"{name}: the template is one of {list(TEMPLATES)}, "
                         f"not {template!r}")
    unknown = set(profile) - KEYS[template]
    if unknown:
        raise ValueError(f"{name}: {sorted(unknown)} are not part of a {template} profile, "
                         f"which says how a thing is used and never what it does; it may have "
                         f"{sorted(KEYS[template])}")
    parts = profile.get("parts")
    if (not isinstance(parts, list) or not parts or len(parts) > 64
            or not all(isinstance(p, str) for p in parts)):
        raise ValueError(f"{name}: parts is the list of the bodies it is made of")
    missing = [p for p in parts if p not in bodies]
    if missing:
        raise ValueError(f"{name}: {missing} {'is' if len(missing) == 1 else 'are'} "
                         f"not in this room")
    if template == "swing-and-lever":
        return _swing_and_lever(name, profile, parts, set(points))
    return _draw_and_release(name, profile, parts, joints)


def _swing_and_lever(name: str, profile: dict[str, Any], parts: list[str],
                     points: set[str]) -> dict[str, Any]:
    """A tool swung at the ground and pried. The hand takes the tool by the
    grip its point was given with; what the swing and the pry do to the ground
    is ground-work-v1's, from the ground's own materials (docs/ground-work.md)."""
    tool = profile.get("tool")
    if tool not in parts:
        raise ValueError(f"{name}: the tool is the part the hand takes and swings -- one of its "
                         f"parts -- not {tool!r}")
    if tool not in points:
        raise ValueError(f"{name}: {tool!r} has no point that can go into the ground, so a swing "
                         f"could never dig anything: give it one first with tool_point")
    out = {"object": name, "template": "swing-and-lever", "parts": list(parts), "tool": tool}
    if profile.get("use") is not None:
        use = _use_checked(name, profile["use"])
        if use:
            out["use"] = use
    return out


def _draw_and_release(name: str, profile: dict[str, Any], parts: list[str],
                      joints: list[dict[str, Any]]) -> dict[str, Any]:
    draw = profile.get("draw")
    if not isinstance(draw, dict):
        raise ValueError(f"{name}: a draw-and-release needs a draw -- the part the hand "
                         f"takes and the way it comes back")
    part = draw.get("part")
    if part not in parts:
        raise ValueError(f"{name}: the draw's part is {part!r}, which is not one of its parts")
    axis = draw.get("axis")
    if (not isinstance(axis, (list, tuple)) or len(axis) != 3
            or not all(type(v) in (int, float) and math.isfinite(v) for v in axis)):
        raise ValueError(f"{name}: the draw's axis is three numbers, the way it comes back")
    size = math.sqrt(sum(float(v) * float(v) for v in axis))
    if size < 1e-9:
        raise ValueError(f"{name}: the draw's axis has no direction")

    def joint(kind: str, a: Any, b: Any) -> dict[str, Any] | None:
        return next((j for j in joints
                     if j.get("kind") == kind and {j.get("a"), j.get("b")} == {a, b}), None)

    nock = profile.get("nock") if isinstance(profile.get("nock"), dict) else {}
    seat = joint("fixing", nock.get("a"), nock.get("b"))
    if seat is None:
        raise ValueError(f"{name}: the nock is the fixing that seats what is loosed on what "
                         f"draws it, and there is no fixing between {nock.get('a')!r} and "
                         f"{nock.get('b')!r}")
    loosed = nock["b"] if nock["a"] == part else nock["a"]
    projectile = profile.get("projectile")
    if projectile != loosed or projectile == part:
        raise ValueError(f"{name}: the projectile is what the nock lets go of -- "
                         f"{loosed!r}, not {projectile!r}")
    # A nock is ONE-WAY: the string pushes the arrow, and the arrow comes off
    # it by itself. One that holds both ways would carry the arrow back to
    # brace and hold it there, and the only way to shoot would be for
    # something that is not the physics to let go of it at the right moment.
    if not float(seat.get("comes_off_n") or 0.0) > 0.0:
        raise ValueError(f"{name}: the nock holds {projectile!r} both ways, so it could "
                         f"never leave the string by itself; a nock is one-way -- give "
                         f"that fixing comes_off_n")
    # And it lets go the way the thing is SHOT, which is against the draw. The
    # fixing's axis points the way its b comes off its a: the arrow off the
    # string, or the string off the arrow, which is the other way.
    shot = [-float(v) / size for v in axis]
    wanted = shot if seat.get("b") == projectile else [-v for v in shot]
    seat_axis = [float(v) for v in seat.get("axis") or [0.0, 0.0, 0.0]]
    seat_size = math.sqrt(sum(v * v for v in seat_axis))
    if seat_size < 1e-9 or sum(w * v for w, v in zip(wanted, seat_axis)) < 0.9 * seat_size:
        raise ValueError(f"{name}: the nock lets {seat.get('b')!r} come off "
                         f"{seat.get('a')!r} along {seat_axis}, and for {projectile!r} "
                         f"to leave the way it is shot that has to be "
                         f"{[round(v, 3) for v in wanted]}")
    limbs = profile.get("limbs")
    if not isinstance(limbs, list) or not limbs:
        raise ValueError(f"{name}: limbs are the elastic joints that store the draw, each "
                         f"named by its two bodies")
    for pair in limbs:
        if (not isinstance(pair, (list, tuple)) or len(pair) != 2
                or not all(isinstance(end, str) for end in pair)
                or joint("elastic", pair[0], pair[1]) is None):
            raise ValueError(f"{name}: there is no elastic between {pair!r} to be a limb")
    return {"object": name, "template": "draw-and-release", "parts": list(parts),
            "draw": {"part": part, "axis": [float(v) / size for v in axis]},
            "nock": {"a": nock["a"], "b": nock["b"]},
            "limbs": [list(pair) for pair in limbs],
            "projectile": projectile}
