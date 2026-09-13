"""How a person uses a thing, checked against what is built.

A profile says which bodies are one object, which part a hand takes and which
way it is drawn, which joint lets go and which joints hold the draw -- and never
what the physics does. There is no speed in one anywhere, and a profile that
tries to say one is refused. docs/interaction-profiles.md.

Shared by the MCP server (mcp/banjo_mcp.py, in metres) and the playground's
room (playground/fracture_lab.py, in millimetres), so a profile is held to one
set of rules whoever wrote it: a model through the MCP's `interaction` tool, or
a room authored by hand. What the two spell differently -- how far the hand asks
to draw, and how fast -- each checks in its own units; everything here is names
and directions. Nothing here imports the engine.
"""
from __future__ import annotations

import math
from typing import Any

# The interaction templates the page knows how to drive. A profile names one;
# the controls are the page's and what happens is the engine's.
TEMPLATES = ("draw-and-release",)
KEYS = {"object", "template", "parts", "draw", "nock", "limbs", "projectile"}


def check(profile: Any, bodies: set[str], joints: list[dict[str, Any]],
          which: str = "the interaction") -> dict[str, Any]:
    """A profile's references, checked against a room's bodies and joints.

    `joints` are in the room's spelling: each has a `kind` ("fixing",
    "elastic", ...), its two ends `a` and `b`, and a fixing its `axis` and
    `comes_off_n`. Returns the object's name, its template and parts, the draw's
    part and unit axis, the nock, the limbs and the projectile. Raises
    ValueError saying what is wrong, where whoever wrote it can be told: a bow
    whose nock is named wrong is a bow that cannot be loosed, and that reads as
    the physics failing.
    """
    if not isinstance(profile, dict):
        raise ValueError(f"{which} is not an object")
    name = str(profile.get("object") or "").strip()[:80]
    if not name:
        raise ValueError(f"{which} needs an object: what the thing is called")
    unknown = set(profile) - KEYS
    if unknown:
        raise ValueError(f"{name}: {sorted(unknown)} are not part of a profile, which says "
                         f"how a thing is used and never what it does; it may have "
                         f"{sorted(KEYS)}")
    template = profile.get("template")
    if template not in TEMPLATES:
        raise ValueError(f"{name}: the template is one of {list(TEMPLATES)}, "
                         f"not {template!r}")
    parts = profile.get("parts")
    if (not isinstance(parts, list) or not parts or len(parts) > 64
            or not all(isinstance(p, str) for p in parts)):
        raise ValueError(f"{name}: parts is the list of the bodies it is made of")
    missing = [p for p in parts if p not in bodies]
    if missing:
        raise ValueError(f"{name}: {missing} {'is' if len(missing) == 1 else 'are'} "
                         f"not in this room")
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
    return {"object": name, "template": template, "parts": list(parts),
            "draw": {"part": part, "axis": [float(v) / size for v in axis]},
            "nock": {"a": nock["a"], "b": nock["b"]},
            "limbs": [list(pair) for pair in limbs],
            "projectile": projectile}
