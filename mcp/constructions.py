"""Constructions: what a structure built from language must do, and whether
what was built does it (docs/building-from-language.md).

The owner's review of 2026-09-15. Asked for "a long ski ramp", both of the
playground's chats built one tilted board, and both said they had built a ski
ramp. A board is valid geometry and a stable object, so the room accepted it.
Nothing asked whether it was what had been asked for.

So a structure is declared before it is built. The declaration gives its kind,
how the request was read, where it runs from, which way, and how big it is.
The kind brings what it must do, in numbers the engine can measure. A ski jump,
for instance, needs:
- a raised start;
- a run down;
- one surface along it, with no gap or step;
- a takeoff that rises at its end;
- every part fixed in place, and standing on the ground, on scenery or on
  another part;
- a clear runout.

A kind is a handful of measurements, not code of its own. The owner asked
(2026-09-15) whether this is "a general purpose llm toolset or just focused on
making a wooden board into a ski ramp". The measurements are the general part
-- the surface along a line and its width, its slopes, its gaps and steps, its
treads, how high it stands over the ground or the water, what stands in a
space beyond it, what holds up what -- and a ramp, a bridge and a staircase are
each a selection of them (KINDS).

What is built is measured against that from the world's own geometry: rays
cast straight down onto it along its line, the ground and the water under it,
and the bodies around it. A ray meets a body as the solver collides it -- a
tilted board as its exact box, not as a staircase of cells (measured: within
0.01 mm of the box's own top, with 40 mm cells). The answer gives each
requirement, what was required and what was measured.

It is judged by what it does, not by its shape: a board on four feet, two of
them taller, is as good a downhill ramp as boards laid end to end on posts --
and, as a ski jump, fails only its takeoff.

The requirements are kept apart from the builder. Declaring the construction
again may raise them, never lower them, so a repair cannot pass by giving up
the thing it failed.
"""
from __future__ import annotations

import math
from typing import Any, Callable

# What each kind of structure must do: the measurements it is held to, and its
# numbers. Lengths are in metres, and a requirement a declaration leaves out
# takes the kind's own. A "model" -- one the person asked to be small -- takes a
# tenth of each.
KINDS: dict[str, dict[str, Any]] = {
    "ski_jump": {
        "reading": "a ski jump: a raised start, a run down, and a takeoff that turns up at its end",
        "length_m": 12.0, "least_length_m": 6.0, "width_m": 1.5, "least_width_m": 0.6,
        # How high its start is: a share of its length, never less than the least.
        "start_height_share": 0.2, "least_start_height_m": 2.0,
        "takeoff_deg": 5.0, "runout_m": 3.0,
        "checks": ("length", "width", "start_height", "continuous", "descends", "takeoff", "fixed",
                   "supported", "runout")},
    "downhill_ramp": {
        "reading": "a downhill ramp: a raised start and a run down",
        "length_m": 8.0, "least_length_m": 3.0, "width_m": 1.2, "least_width_m": 0.4,
        "start_height_share": 0.15, "least_start_height_m": 1.0,
        "checks": ("length", "width", "start_height", "continuous", "descends", "fixed", "supported")},
    "access_ramp": {
        "reading": "an access ramp: a gentle slope up to a height",
        "length_m": 4.0, "least_length_m": 1.0, "width_m": 1.0, "least_width_m": 0.6,
        "rise_m": 0.5, "least_rise_m": 0.1, "steepest_deg": 7.2,     # one in eight
        "checks": ("length", "width", "rise", "gentle", "continuous", "fixed", "supported")},
    "bridge": {
        "reading": "a bridge: a walkable deck from one end to the other, clear of what it crosses",
        "length_m": 4.0, "least_length_m": 1.5, "width_m": 1.0, "least_width_m": 0.5,
        # How high its deck stands over the ground or water under its middle.
        "clearance_m": 0.3, "least_clearance_m": 0.1, "walkable_deg": 12.0,
        "checks": ("reaches", "width", "continuous", "walkable", "above", "fixed", "supported")},
    "staircase": {
        "reading": "a staircase: even steps up to a height",
        "width_m": 0.8, "least_width_m": 0.5, "rise_m": 1.0, "least_rise_m": 0.3,
        # Each step rises between these, goes at least this far (the top one,
        # a landing, as far as it likes), and its rises are this even.
        "step_rise_m": (0.10, 0.22), "least_going_m": 0.22, "even_m": 0.02, "going_m": 0.28,
        "checks": ("rise", "steps", "width", "fixed", "supported")},
    "structure": {
        "reading": "a structure",
        "length_m": 1.0, "least_length_m": 0.1, "width_m": 0.5, "least_width_m": 0.04,
        "checks": ("length", "width", "supported")},
}
SCALES = {"full": 1.0, "model": 0.1}

# How finely it is measured, and what counts as one surface. The lengths are a
# full-size structure's; a model's are a tenth, and never under a centimetre.
STATION_M = 0.01         # rays along its line, this far apart
STEP_M = 0.05            # a gap in it, or a rise or drop between two rays, bigger than this breaks it
TOUCH_M = 0.06           # parts this close count as touching, as the ground does
REACH_M = 0.3            # a bridge's deck starts and ends this close to its declared ends
TAKEOFF_OVER_M = 1.0     # the takeoff is its slope over its last metre
WINDOW_M = 0.5           # steepness is a slope over any half metre
CLEAR_HEIGHT_M = 2.5     # the runout is clear this high above the ground
LEVEL_M = 0.005          # a tread is level to this
# Upper limits, from the kind: declared again, they are what they were.
LIMITS = ("steepest_deg", "walkable_deg")


def _number(value: Any, what: str, default: float) -> float:
    if value is None:
        return default
    try:
        out = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{what} is a number, in metres") from None
    if not math.isfinite(out) or out <= 0.0:
        raise ValueError(f"{what} is a length above zero, in metres")
    return out


def _level(value: Any, what: str) -> tuple[float, float]:
    """A level direction [x, 0, z] or [x, z], as a unit (x, z)."""
    if not isinstance(value, (list, tuple)) or len(value) not in (2, 3):
        raise ValueError(f"{what} is a level direction, like the person's facing [x, 0, z]")
    x, z = (float(value[0]), float(value[-1]))
    size = math.hypot(x, z)
    if not math.isfinite(size) or size < 1e-6:
        raise ValueError(f"{what} needs a direction along the ground, not straight up or down")
    return x / size, z / size


def plan(existing: dict[str, Any] | None, args: dict[str, Any], names_now: set[str]) -> dict[str, Any]:
    """A construction as declared: its kind, how the request was read, where
    its line starts and which way it runs, and what it must do. Declared again,
    it keeps its parts and may raise what it must do, never lower it.

    Its line is given by start_m, where it starts on the ground -- a ramp's
    raised end, a staircase's foot, a bridge's near end -- or by middle_m, where
    its middle is, and facing, the level way it runs: a line across the
    person's view is code's to work out, not the model's."""
    kind = str(args.get("kind") or "").strip().lower()
    if kind not in KINDS:
        raise ValueError(f"kind is one of {', '.join(KINDS)}, not {kind!r}")
    scale = str(args.get("scale") or "full").strip().lower()
    if scale not in SCALES:
        raise ValueError("scale is full -- a person's size -- or model, when they asked for a small one")
    shape, factor = KINDS[kind], SCALES[scale]
    checks, called = shape["checks"], kind.replace("_", " ")
    reading = " ".join(str(args.get("reading") or "").split())[:240]
    if not reading:
        raise ValueError(f"reading is one sentence saying how you read the request, which the person "
                         f"sees -- like \"{shape['reading']}\"")
    facing = _level(args.get("facing"), "facing")
    # How high it rises, for what rises: an access ramp, a staircase.
    rise = None
    if "rise" in checks:
        rise = _number(args.get("height_m"), "height_m", shape["rise_m"] * factor)
        if rise < shape["least_rise_m"] * factor - 1e-9:
            raise ValueError(f"a {called} rises at least {shape['least_rise_m'] * factor:g} m")
    if "steps" in checks:
        # As many steps as its rise needs at the steepest, each going the least.
        steps = math.ceil(rise / (shape["step_rise_m"][1] * factor) - 1e-9)
        least_length = steps * shape["least_going_m"] * factor
        default_length = max(least_length,
                             math.ceil(rise / (0.18 * factor) - 1e-9) * shape["going_m"] * factor)
    else:
        least_length, default_length = shape["least_length_m"] * factor, shape["length_m"] * factor
    length = _number(args.get("length_m"), "length_m", default_length)
    width = _number(args.get("width_m"), "width_m", shape["width_m"] * factor)
    start, middle = args.get("start_m"), args.get("middle_m")
    for value, what in ((start, "start_m"), (middle, "middle_m")):
        if value is not None and (not isinstance(value, (list, tuple)) or len(value) not in (2, 3)
                                  or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in value)):
            raise ValueError(f"{what} is a point on the ground, [x, z]")
    if start is not None:
        start_xz = (float(start[0]), float(start[-1]))
    elif middle is not None:
        start_xz = (float(middle[0]) - facing[0] * length / 2.0, float(middle[-1]) - facing[1] * length / 2.0)
    else:
        raise ValueError("give where its line starts on the ground, start_m [x, z] -- for a ramp, its "
                         "raised end -- or where its middle is, middle_m [x, z]")
    if length < least_length - 1e-9:
        if "steps" in checks:
            raise ValueError(f"a staircase rising {rise:g} m is at least {least_length:.2f} m long: {steps} "
                             f"steps, each going at least {shape['least_going_m'] * factor:g} m")
        raise ValueError(f"a {called} is at least {least_length:g} m long"
                         + ("" if scale == "model" else ": for a small one, say scale model"))
    if width < shape["least_width_m"] * factor - 1e-9:
        raise ValueError(f"a {called} is at least {shape['least_width_m'] * factor:g} m wide")
    requirements: dict[str, float] = {"length_m": round(length, 3), "width_m": round(width, 3)}
    if "start_height" in checks:
        least = max(shape["least_start_height_m"] * factor, shape["start_height_share"] * length)
        height = _number(args.get("height_m"), "height_m", least)
        if height < least - 1e-9:
            raise ValueError(f"a {called} {length:g} m long starts at least {least:.2f} m up: a share of "
                             f"its length, and never less than {shape['least_start_height_m'] * factor:g} m")
        requirements["start_height_m"] = round(height, 3)
    if "takeoff" in checks:
        requirements["takeoff_deg"] = shape["takeoff_deg"]
    if "runout" in checks:
        requirements["runout_m"] = round(shape["runout_m"] * factor, 3)
    if rise is not None:
        requirements["rise_m"] = round(rise, 3)
    if "gentle" in checks:
        steepest = shape["steepest_deg"]
        if length < rise / math.tan(math.radians(steepest)) - 1e-6:
            raise ValueError(f"an access ramp rising {rise:g} m is at least "
                             f"{rise / math.tan(math.radians(steepest)):.2f} m long, to be no steeper "
                             f"than one in eight")
        requirements["steepest_deg"] = steepest
    if "above" in checks:
        clearance = _number(args.get("height_m"), "height_m", shape["clearance_m"] * factor)
        if clearance < shape["least_clearance_m"] * factor - 1e-9:
            raise ValueError(f"a bridge's deck stands at least {shape['least_clearance_m'] * factor:g} m over "
                             f"what it crosses")
        requirements["clearance_m"] = round(clearance, 3)
    if "walkable" in checks:
        requirements["walkable_deg"] = shape["walkable_deg"]
    if existing is not None:
        if existing["kind"] != kind:
            raise ValueError(f"it was declared a {existing['kind'].replace('_', ' ')}; to build something "
                             f"else, declare a construction of another name")
        lowered = [key for key, was in existing["requirements"].items()
                   if key not in LIMITS and requirements.get(key, was) < was - 1e-9]
        if lowered:
            raise ValueError("what it must do can be raised, never lowered: "
                             + ", ".join(f"{key} was {existing['requirements'][key]:g}" for key in lowered))
        # What it had stays what it has, unless raised.
        requirements = {**existing["requirements"], **requirements}
    return {"kind": kind, "scale": scale, "reading": reading,
            "start_m": [round(start_xz[0], 4), round(start_xz[1], 4)],
            "facing": [round(facing[0], 6), 0.0, round(facing[1], 6)],
            "requirements": requirements,
            "parts": list(existing["parts"]) if existing else [],
            # What was there when it was declared: everything added after it,
            # while this record stands, is one of its parts.
            "before": sorted(names_now)}


def parts_now(record: dict[str, Any], names_now: set[str]) -> list[str]:
    """Its parts as the world stands: those it was given and, while it is the
    record its declaration made, everything added since -- less what is gone. A
    construction the room opens again from its spec has no `before`, so nothing
    made in a later turn joins it unless it is declared again."""
    before = record.get("before")
    added = set(names_now) - set(before) if before is not None else set()
    return sorted((set(record.get("parts") or ()) | added) & set(names_now))


def said(record: dict[str, Any]) -> list[str]:
    """What it must do, in words."""
    req, out = record["requirements"], []
    shape = KINDS[record["kind"]]
    checks = shape["checks"]
    factor = SCALES.get(record.get("scale") or "full", 1.0)
    step = max(STEP_M * factor, 0.01)
    if "reaches" in checks:
        out.append(f"its deck from its start to {req['length_m']:g} m along its line, within "
                   f"{REACH_M * factor:g} m of each end")
    for key, words in (("length_m", "at least {:g} m long along its line"),
                       ("width_m", "at least {:g} m across"),
                       ("start_height_m", "its start at least {:g} m above the ground there"),
                       ("rise_m", "rising at least {:g} m from its foot to its top"),
                       ("steepest_deg", "no steeper than {:g} degrees over any half metre"),
                       ("walkable_deg", "no steeper than {:g} degrees over any half metre, to walk"),
                       ("clearance_m", "its deck at least {:g} m above the ground or water under its middle"),
                       ("takeoff_deg", "rising at least {:g} degrees over its last metre, to take off"),
                       ("runout_m", "{:g} m clear beyond its end")):
        if key in req and not (key == "length_m" and "reaches" in checks) and not (
                key == "length_m" and "steps" in checks):
            out.append(words.format(req[key]))
    if "steps" in checks:
        low, high = shape["step_rise_m"]
        out.append(f"even steps: each rising {low * factor:g} to {high * factor:g} m and going at least "
                   f"{shape['least_going_m'] * factor:g} m (the top one as far as it likes), their rises within "
                   f"{shape['even_m'] * factor * 100:g} cm of each other")
    if "continuous" in checks:
        out.append(f"one surface along it, with no gap or step of more than {step * 100:.0f} cm")
    if "descends" in checks:
        out.append("coming down from its start by at least half its start height")
    if "fixed" in checks:
        out.append("every part fixed in place (anchored)")
    if "supported" in checks:
        out.append("every part standing on the ground, on scenery or on another part, however high it is")
    return out


def summary(checked: dict[str, Any]) -> str:
    """One line: that it passed, or what failed and what it needed."""
    name = checked.get("construction") or "it"
    if checked.get("passed"):
        return f"{name} passes all {len(checked.get('results') or [])} of its checks"
    return f"{name}: " + "; ".join(f"{r['requirement']} {r['measured']} (needs {r['required']})"
                                   for r in checked.get("results") or [] if not r["passed"])


def _frame(body: Any) -> tuple[list[float], tuple[tuple[float, ...], ...], list[float]]:
    """A body's centre, its own three axes in the world, and its half sizes."""
    w, x, y, z = (float(v) for v in body.orientation_wxyz)
    axes = ((1 - 2 * (y * y + z * z), 2 * (x * y + w * z), 2 * (x * z - w * y)),
            (2 * (x * y - w * z), 1 - 2 * (x * x + z * z), 2 * (y * z + w * x)),
            (2 * (x * z + w * y), 2 * (y * z - w * x), 1 - 2 * (x * x + y * y)))
    half = [float(d) / 2.0 for d in body.dimensions_m]
    if body.shape == "sphere":
        half = [half[0]] * 3
    return [float(v) for v in body.position_m], axes, half


def _corners(body: Any) -> list[list[float]]:
    """A body's corners in the world, from its size, place and turn."""
    centre, axes, half = _frame(body)
    return [[centre[r] + sum(sign[i] * half[i] * axes[i][r] for i in range(3)) for r in range(3)]
            for sign in [(sx, sy, sz) for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]]


def _box(corners: list[list[float]]) -> tuple[list[float], list[float]]:
    return ([min(c[i] for c in corners) for i in range(3)], [max(c[i] for c in corners) for i in range(3)])


def _boxes_near(a: tuple[list[float], list[float]], b: tuple[list[float], list[float]], gap: float) -> bool:
    return all(a[0][i] <= b[1][i] + gap and b[0][i] <= a[1][i] + gap for i in range(3))


def _near(a: Any, b: Any, gap: float) -> bool:
    """Whether two bodies, as the boxes they are, come within `gap` of each
    other: the separating-axis test on the boxes grown by half the gap each. A
    level box round a tilted board is far bigger than the board, so a post a
    metre short of a ramp's underside would have counted as holding it up."""
    ca, axes_a, half_a = a
    cb, axes_b, half_b = b
    t = [cb[i] - ca[i] for i in range(3)]

    def dot(u: Any, v: Any) -> float:
        return u[0] * v[0] + u[1] * v[1] + u[2] * v[2]

    candidates = list(axes_a) + list(axes_b) + [
        (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
        for u in axes_a for v in axes_b]
    for axis in candidates:
        size = math.sqrt(dot(axis, axis))
        if size < 1e-9:
            continue
        n = [c / size for c in axis]
        reach_a = sum((half_a[i] + gap / 2.0) * abs(dot(axes_a[i], n)) for i in range(3))
        reach_b = sum((half_b[i] + gap / 2.0) * abs(dot(axes_b[i], n)) for i in range(3))
        if abs(dot(t, n)) > reach_a + reach_b:
            return False
    return True


def _slope(stations: list[float], height: dict[float, float]) -> float:
    """The rise over the run of the straight line that fits these best."""
    n = len(stations)
    if n < 2:
        return 0.0
    mean_s = sum(stations) / n
    mean_h = sum(height[s] for s in stations) / n
    spread = sum((s - mean_s) ** 2 for s in stations)
    return 0.0 if spread <= 0.0 else sum((s - mean_s) * (height[s] - mean_h) for s in stations) / spread


def _steepest(on: list[float], height: dict[float, float], window: float, first: float, last: float,
              factor: float) -> tuple[float, float]:
    """The steepest slope over any window along it, in degrees, and where."""
    steepest, where, begin = 0.0, first, first
    while True:
        span = [s for s in on if begin - 1e-9 <= s <= begin + window + 1e-9]
        if len(span) >= 3:
            degrees = abs(math.degrees(math.atan(_slope(span, height))))
            if degrees > steepest:
                steepest, where = degrees, begin
        if begin + window >= last:
            return steepest, where
        begin += 0.1 * factor


def _treads(on: list[float], height: dict[float, float], station: float, factor: float) -> list[list[float]]:
    """The level stretches of a profile -- a staircase's treads -- as [from_s,
    to_s, height], less slivers under 5 cm (where a ray met an edge)."""
    treads: list[list[float]] = []
    for s in on:
        if treads and abs(height[s] - treads[-1][2]) <= LEVEL_M and s - treads[-1][1] <= 1.5 * station:
            treads[-1][1] = s
        else:
            treads.append([s, s, height[s]])
    return [t for t in treads if t[1] - t[0] >= 0.05 * factor]


def check(record: dict[str, Any], world: Any, ground_at: Callable[[float, float], float],
          names_now: set[str], water_at: Callable[[float, float], float | None] | None = None) -> dict[str, Any]:
    """What was built, measured against what it must do: each requirement with
    what was required and what was measured, and whether all passed. water_at,
    where there is water, gives its surface over a point (None: dry)."""
    record["parts"] = parts_now(record, names_now)
    bodies = {name: world.body(name) for name in record["parts"]}
    bodies = {name: body for name, body in bodies.items() if body is not None}
    req = record["requirements"]
    shape = KINDS[record["kind"]]
    checks = shape["checks"]
    factor = SCALES.get(record.get("scale") or "full", 1.0)
    step_m = max(STEP_M * factor, 0.01)
    station = min(STATION_M, req["length_m"] / 400.0)
    ux, uz = record["facing"][0], record["facing"][2]
    lx, lz = -uz, ux
    x0, z0 = record["start_m"]
    results: list[dict[str, Any]] = []

    def result(what: str, required: str, measured: str, passed: bool) -> None:
        results.append({"requirement": what, "required": required, "measured": measured, "passed": bool(passed)})

    def verdict(**more: Any) -> dict[str, Any]:
        return {"construction": record.get("name"), "kind": record["kind"],
                "passed": bool(results) and all(r["passed"] for r in results),
                "failed": [r["requirement"] for r in results if not r["passed"]],
                "results": results, "parts": record["parts"], **more}

    def under(x: float, z: float) -> float:
        """The ground under a point, or the water over it."""
        ground = ground_at(x, z)
        water = water_at(x, z) if water_at is not None else None
        return ground if water is None else max(ground, water)

    if not bodies:
        result("parts", "something built after it was declared", "nothing", False)
        return verdict()
    corners = {name: _corners(body) for name, body in bodies.items()}
    top = max(c[1] for points in corners.values() for c in points) + 1.0

    def surface(s: float, across: float = 0.0) -> tuple[float, float, float | None]:
        """Where the line is at s along it and `across` to one side, and the
        height of the top of the construction there (None: none of it)."""
        x, z = x0 + ux * s + lx * across, z0 + uz * s + lz * across
        hit = world.pick([x, top, z], [0.0, -1.0, 0.0], top + 50.0)
        return x, z, (float(hit.point_m[1]) if hit.hit and hit.name in bodies else None)

    # From a little before its start to twice its length: a construction built
    # longer than declared is measured to its end, so its takeoff is its own.
    lead = 0.5 * factor
    count = int(round((2.0 * req["length_m"] + 2.0 * lead) / station))
    stations = [round(-lead + i * station, 4) for i in range(count + 1)]
    profile = {s: surface(s) for s in stations}
    on = [s for s in stations if profile[s][2] is not None]
    if not on:
        result("along its line", f"its surface under the line from {record['start_m']} facing {record['facing']}",
               "none of it lies under that line", False)
        return verdict()
    first, last = on[0], on[-1]
    height = {s: profile[s][2] for s in on}
    run = last - first
    start_height = max(height[s] - ground_at(profile[s][0], profile[s][1]) for s in on if s <= first + lead)

    if "reaches" in checks:
        close = REACH_M * factor
        result("reaches", f"its deck from within {close:g} m of its start to within {close:g} m of "
                          f"{req['length_m']:g} m along its line", f"from {first:.2f} m to {last:.2f} m",
               first <= close and last >= req["length_m"] - close)
    if "length" in checks:
        result("length", f"at least {req['length_m']:g} m along its line", f"{run:.2f} m",
               run >= req["length_m"] - 2.0 * station)
    if "width" in checks:
        # Across it at a quarter, the middle and three quarters of its run:
        # both edges of the width asked for must be on its surface.
        half = req["width_m"] / 2.0 - 0.02 * factor
        narrow = [s for s in (first + run * f for f in (0.25, 0.5, 0.75))
                  if surface(s, half)[2] is None or surface(s, -half)[2] is None]
        result("width", f"at least {req['width_m']:g} m across",
               "that wide all along it" if not narrow else
               "narrower than that at " + ", ".join(f"{s:.1f} m" for s in narrow), not narrow)
    if "start_height" in checks:
        result("start height", f"at least {req['start_height_m']:g} m above the ground at its start",
               f"{start_height:.2f} m", start_height >= req["start_height_m"] - 0.02 * factor)
    if "rise" in checks:
        foot = min(ground_at(profile[first][0], profile[first][1]), ground_at(profile[last][0], profile[last][1]))
        rise = max(height.values()) - foot
        result("rise", f"at least {req['rise_m']:g} m from its foot to its top", f"{rise:.2f} m",
               rise >= req["rise_m"] - 0.02 * factor)
    if "steps" in checks:
        treads = _treads(on, height, station, factor)
        if len(treads) >= 2 and treads[-1][2] < treads[0][2]:
            # Declared from its top: measured from its foot all the same.
            treads = [[-t[1], -t[0], t[2]] for t in reversed(treads)]
            foot = ground_at(profile[last][0], profile[last][1])
        else:
            foot = ground_at(profile[first][0], profile[first][1])
        levels = [foot] + [t[2] for t in treads]
        rises = [b - a for a, b in zip(levels, levels[1:])]
        goings = [t[1] - t[0] + station for t in treads[:-1]]
        low, high = (v * factor for v in shape["step_rise_m"])
        going, even = shape["least_going_m"] * factor, shape["even_m"] * factor
        wrong = [f"step {i} rises {r:.2f} m" for i, r in enumerate(rises, 1)
                 if not low - LEVEL_M <= r <= high + LEVEL_M]
        short = [f"step {i} goes {g:.2f} m" for i, g in enumerate(goings, 1) if g < going - 0.01 * factor]
        spread = max(rises) - min(rises) if rises else 0.0
        words = (f"{len(treads)} steps rising {min(rises):.2f} to {max(rises):.2f} m, going at least "
                 f"{min(goings):.2f} m" if len(treads) >= 2 else
                 f"{len(treads)} step{'' if len(treads) == 1 else 's'}")
        problems = wrong[:3] + short[:3] + ([f"their rises {spread * 100:.0f} cm apart"] if spread > even + LEVEL_M
                                            else [])
        result("steps", f"at least 2 steps, each rising {low:g} to {high:g} m and going at least {going:g} m, "
                        f"their rises within {even * 100:g} cm of each other",
               words + ("; " + "; ".join(problems) if problems else ""),
               len(treads) >= 2 and not problems)
    if "continuous" in checks:
        words = []
        gaps = [(a, b - a - station) for a, b in zip(on, on[1:]) if b - a - station > step_m]
        steps = [(abs(height[b] - height[a]), b) for a, b in zip(on, on[1:]) if b - a < 1.5 * station]
        worst = max(steps, default=(0.0, first))
        if gaps:
            words.append(", ".join(f"a gap of {wide * 100:.0f} cm at {at:.2f} m" for at, wide in gaps[:4]))
        if worst[0] > step_m:
            words.append(f"a step of {worst[0] * 100:.0f} cm at {worst[1]:.2f} m")
        result("one surface", f"no gap or step of more than {step_m * 100:.0f} cm along it",
               "; ".join(words) if words else f"no gap, and its biggest step {worst[0] * 100:.1f} cm",
               not gaps and worst[0] <= step_m)
    if "descends" in checks:
        drop = height[first] - min(height.values())
        wanted = 0.5 * req.get("start_height_m", 0.0)
        result("coming down", f"at least {wanted:.2f} m down from its start", f"{drop:.2f} m",
               drop >= wanted - 0.02 * factor)
    if "takeoff" in checks:
        tail = [s for s in on if s >= last - TAKEOFF_OVER_M * factor - 1e-9]
        degrees = math.degrees(math.atan(_slope(tail, height)))
        result("takeoff", f"rising at least {req['takeoff_deg']:g} degrees over its last metre",
               f"{'rising' if degrees >= 0 else 'falling'} {abs(degrees):.1f} degrees",
               degrees >= req["takeoff_deg"] - 0.2)
    if "gentle" in checks:
        steepest, where = _steepest(on, height, WINDOW_M * factor, first, last, factor)
        result("gentle", f"no steeper than {req['steepest_deg']:g} degrees over any half metre",
               f"{steepest:.1f} degrees at its steepest, from {where:.1f} m", steepest <= req["steepest_deg"] + 0.2)
    if "walkable" in checks:
        steepest, where = _steepest(on, height, WINDOW_M * factor, first, last, factor)
        result("walkable", f"no steeper than {req['walkable_deg']:g} degrees over any half metre",
               f"{steepest:.1f} degrees at its steepest, from {where:.1f} m", steepest <= req["walkable_deg"] + 0.2)
    if "above" in checks:
        # Over its middle half, every 5 cm: how high its top stands over the
        # ground or the water under it.
        middle = [s for s in on if first + run / 4.0 <= s <= last - run / 4.0][::5] or on[::5]
        lowest = min((height[s] - under(profile[s][0], profile[s][1]), s) for s in middle)
        result("clear of what it crosses",
               f"its deck at least {req['clearance_m']:g} m above the ground or water under its middle",
               f"{lowest[0]:.2f} m at its lowest, at {lowest[1]:.1f} m", lowest[0] >= req["clearance_m"] - 0.02 * factor)
    if "fixed" in checks:
        loose = sorted(name for name, body in bodies.items() if not body.anchored)
        result("fixed in place", "every part anchored",
               "all of them" if not loose else "loose: " + ", ".join(loose[:6]), not loose)
    if "supported" in checks:
        # Every part carries down to the ground, part by part, or rests on
        # scenery that does.
        frames = {name: _frame(body) for name, body in bodies.items()}
        boxes = {name: _box(points) for name, points in corners.items()}
        standing = {name for name, points in corners.items()
                    if min(c[1] - ground_at(c[0], c[2]) for c in points) <= TOUCH_M}
        for body in world.bodies():
            if body.name in bodies or not body.anchored:
                continue
            frame, box = _frame(body), _box(_corners(body))
            for name in frames:
                if name not in standing and _boxes_near(boxes[name], box, TOUCH_M) \
                        and _near(frames[name], frame, TOUCH_M):
                    standing.add(name)
        grown = True
        while grown:
            grown = False
            for name in frames:
                if name not in standing and any(_boxes_near(boxes[name], boxes[other], TOUCH_M)
                                                and _near(frames[name], frames[other], TOUCH_M)
                                                for other in standing):
                    standing.add(name)
                    grown = True
        floating = sorted(set(frames) - standing)
        result("supported", "every part standing on the ground, on scenery or on another part",
               "all of them" if not floating else "resting on nothing: " + ", ".join(floating[:6]), not floating)
    if "runout" in checks:
        # Beyond its end: a box as long as the runout, as wide as it and up to
        # above a person's head, from just over the ground there -- and what
        # stands in it, box against turned box. It was each body's level
        # bounds, widened by its longest side, and a board 3.2 m beyond a 3 m
        # runout was "in the way".
        runout, clear = req["runout_m"], CLEAR_HEIGHT_M * factor
        mx, mz = x0 + ux * (last + runout / 2.0), z0 + uz * (last + runout / 2.0)
        floor = ground_at(mx, mz) + 0.02 * factor
        space = ([mx, floor + clear / 2.0, mz], ((ux, 0.0, uz), (0.0, 1.0, 0.0), (lx, 0.0, lz)),
                 [runout / 2.0, clear / 2.0, req["width_m"] / 2.0])
        in_way = sorted(body.name for body in world.bodies()
                        if body.name not in bodies and _near(space, _frame(body), 0.0))
        result("runout", f"{runout:g} m clear beyond its end",
               "clear" if not in_way else "in the way: " + ", ".join(in_way[:6]), not in_way)
    return verdict(measured_along={"from_m": round(first, 2), "to_m": round(last, 2),
                                   "start_height_m": round(start_height, 3)})
