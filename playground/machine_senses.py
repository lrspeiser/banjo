"""What a machine can sense (docs/machine-world.md, "A machine's senses and
its tools").

A machine knows the world only through its senses, and whatever thinks for it
-- its routine, Jev, the chat's model, a person talking to it -- reads the
same readings. Each sense here is one named reading, in words and numbers a
program or a model can use directly: where it is and which way it faces;
which way is downhill and how steep; where the nearest water is; where the sun
stands; what its battery holds and what charges it; what its wheels are doing;
what it carries; how far and which way each place it knows is; what is near
it; what struck it. Directions are given RELATIVE to the machine's front, in
degrees, positive to its left, so "turn left 40" means the same to every
reader; distances in metres.

Nothing here is a rover's: a sense reads what the engine reports of any
machine with a program (the program's own report, its controllers, the room's
sun, the ground surveyed round it) and the routine's own bookkeeping. A new
sense is one entry in SENSES; a machine without what a sense needs simply
lacks that reading. Reading is on demand -- when something happens, when a
person asks -- not every step: the ground round it is surveyed with a dozen
calls to the engine, cheap once a second and wasteful sixty times.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Callable

# How far round it the ground is surveyed for the lie of the land and the
# water: rings at these distances, so many bearings each.
RING_M = (1.5, 3.0, 6.0)
RING_BEARINGS = 8
NEAR_M = 8.0


@dataclass
class Context:
    """What a sense reads from: the program as the engine reports it, the
    room's machines and bodies, a way to ask the engine (survey, sun), what
    the routine keeps (its places and its load), and who is near."""
    program: dict[str, Any]
    machines: dict[str, Any] | None = None
    bodies: list[dict[str, Any]] | None = None
    ask: Callable[..., dict[str, Any]] | None = None     # ask(op=..., ...) -> the engine's reply
    routine: Any = None                                  # machine_routine.Routine, or None
    person: dict[str, Any] | None = None                 # {standing_m: [x, y, z]} when someone is there
    impacts: list[dict[str, Any]] = field(default_factory=list)
    t: float = 0.0
    _surveys: dict[tuple[float, float], dict[str, Any]] = field(default_factory=dict)
    _sun: dict[str, Any] | None = None

    def at(self) -> tuple[float, float]:
        a = self.program.get("at_m") or [0.0, 0.0, 0.0]
        return float(a[0]), float(a[2])

    def heading(self) -> float:
        return float(self.program.get("heading_deg") or 0.0)

    def survey(self, x: float, z: float) -> dict[str, Any]:
        key = (round(x, 2), round(z, 2))
        if key not in self._surveys:
            reply = self.ask(op="survey", at=[x, z]) if self.ask else {}
            self._surveys[key] = (reply or {}).get("survey") or {}
        return self._surveys[key]

    def sun(self) -> dict[str, Any]:
        if self._sun is None:
            reply = self.ask(op="sun") if self.ask else {}
            self._sun = (reply or {}).get("sun") or {}
        return self._sun


def relative_bearing(heading_deg: float, dx: float, dz: float) -> float:
    """Which way a point lies from a machine's front: degrees, positive to its
    left, in (-180, 180]. Headings are round from +z towards +x."""
    absolute = math.degrees(math.atan2(dx, dz))
    off = absolute - heading_deg
    while off > 180.0:
        off -= 360.0
    while off <= -180.0:
        off += 360.0
    return round(off, 1)


def toward(ctx: Context, x: float, z: float) -> dict[str, Any]:
    """How far and which way a point in the world is from the machine."""
    ax, az = ctx.at()
    dx, dz = x - ax, z - az
    return {"distance_m": round(math.hypot(dx, dz), 2), "bearing_deg": relative_bearing(ctx.heading(), dx, dz)}


def point_ahead(ctx: Context, metres: float, bearing_deg: float = 0.0) -> list[float]:
    """The point so far ahead of the machine, so many degrees to its left."""
    ax, az = ctx.at()
    a = math.radians(ctx.heading() + bearing_deg)
    return [round(ax + metres * math.sin(a), 3), round(az + metres * math.cos(a), 3)]


def _ring(ctx: Context) -> list[dict[str, Any]]:
    """The ground surveyed on rings round the machine: each point with its
    distance, bearing, height and water depth."""
    out = []
    ax, az = ctx.at()
    for r in RING_M:
        for k in range(RING_BEARINGS):
            bearing = k * 360.0 / RING_BEARINGS
            a = math.radians(ctx.heading() + bearing)
            x, z = ax + r * math.sin(a), az + r * math.cos(a)
            s = ctx.survey(x, z)
            if not s.get("on_the_ground", True) and "ground_m" not in s:
                continue
            water = s.get("water") or {}
            out.append({"distance_m": r, "bearing_deg": relative_bearing(ctx.heading(), x - ax, z - az),
                        "ground_m": float(s.get("ground_m") or 0.0),
                        "water_m": float(water.get("depth_m") or 0.0), "surface": s.get("surface")})
    return out


def _controls(ctx: Context) -> dict[Any, dict[str, Any]]:
    return {c.get("id"): c for c in (ctx.machines or {}).get("controls") or []}


def _store(ctx: Context) -> dict[str, Any] | None:
    """The store the machine's wheels draw on."""
    controls = _controls(ctx)
    motors = {m.get("id"): m for m in (ctx.machines or {}).get("motors") or []}
    stores = {s.get("id"): s for s in (ctx.machines or {}).get("stores") or []}
    left = controls.get(ctx.program.get("left")) or {}
    motor = motors.get(left.get("motor")) or {}
    return stores.get(motor.get("store"))


def _panels_w(ctx: Context, store_id: Any) -> float:
    return round(sum(float(p.get("power_w") or 0.0) for p in (ctx.machines or {}).get("panels") or []
                     if p.get("store") == store_id), 1)


# ---- the senses ------------------------------------------------------------

def sense_position(ctx: Context) -> dict[str, Any]:
    ax, az = ctx.at()
    speed = 0.0
    for b in ctx.bodies or []:
        if b.get("name") == ctx.program.get("body"):
            v = b.get("velocity_m_s") or [0, 0, 0]
            speed = round(math.hypot(float(v[0]), float(v[2])), 2)
    return {"x_m": round(ax, 2), "z_m": round(az, 2), "heading_deg": round(ctx.heading(), 1), "speed_m_s": speed,
            "doing": ctx.program.get("doing"), "why": ctx.program.get("why"),
            "for_s": ctx.program.get("doing_s"), "asked": ctx.program.get("asked")}


def sense_slope(ctx: Context) -> dict[str, Any]:
    """Its own tilt, from the program; and the lie of the land round it, from
    the ground surveyed on a ring: which way is downhill and how steep."""
    out: dict[str, Any] = {"nose_up_deg": ctx.program.get("pitch_deg"),
                           "left_side_up_deg": ctx.program.get("roll_deg"),
                           "climbs_up_to_deg": ctx.program.get("climb_deg")}
    here = ctx.survey(*ctx.at())
    ring = [p for p in _ring(ctx) if p["distance_m"] == RING_M[0]]
    if here and ring:
        h0 = float(here.get("ground_m") or 0.0)
        low = min(ring, key=lambda p: p["ground_m"])
        high = max(ring, key=lambda p: p["ground_m"])
        out["downhill_bearing_deg"] = low["bearing_deg"]
        out["downhill_deg"] = round(math.degrees(math.atan2(h0 - low["ground_m"], low["distance_m"])), 1)
        out["uphill_bearing_deg"] = high["bearing_deg"]
        out["uphill_deg"] = round(math.degrees(math.atan2(high["ground_m"] - h0, high["distance_m"])), 1)
        out["ahead_rises_deg"] = round(math.degrees(math.atan2(
            next((p["ground_m"] for p in ring if abs(p["bearing_deg"]) < 1.0), h0) - h0, RING_M[0])), 1)
    return out


def sense_ground(ctx: Context) -> dict[str, Any]:
    s = ctx.survey(*ctx.at())
    water = s.get("water") or {}
    return {"surface": s.get("surface"), "sand_m": s.get("sand_m"), "soil_m": s.get("soil_m"),
            "loose_soil_m": s.get("loose_soil_m"), "slope_deg": s.get("slope_deg"),
            "water_under_it_m": water.get("depth_m", 0.0)}


def sense_water(ctx: Context) -> dict[str, Any]:
    """Its water sensors, and the nearest water on the rings round it."""
    sensors = [{"side": "left" if s.get("side", 0) > 0 else "right" if s.get("side", 0) < 0 else "middle",
                "water_under_it_mm": round(1000.0 * float(s.get("reading_m") or 0.0)), "sees_water": bool(s.get("sees"))}
               for s in ctx.program.get("sensors") or []]
    wet = [p for p in _ring(ctx) if p["water_m"] > 0.003]
    nearest = min(wet, key=lambda p: (p["distance_m"], abs(p["bearing_deg"]))) if wet else None
    return {"sensors": sensors,
            "nearest_water": ({"distance_m": nearest["distance_m"], "bearing_deg": nearest["bearing_deg"],
                               "depth_m": round(nearest["water_m"], 3)} if nearest else None),
            "dry_bearings_deg": sorted({p["bearing_deg"] for p in _ring(ctx)
                                        if p["distance_m"] == RING_M[1] and p["water_m"] <= 0.003})}


def sense_sun(ctx: Context) -> dict[str, Any]:
    sun = ctx.sun()
    if not sun:
        return {"declared": False}
    azimuth = float(sun.get("azimuth_deg") or 0.0)
    elevation = float(sun.get("elevation_deg") or 0.0)
    off = azimuth - ctx.heading()
    while off > 180.0:
        off -= 360.0
    while off <= -180.0:
        off += 360.0
    out = {"declared": True, "elevation_deg": round(elevation, 1), "bearing_deg": round(off, 1),
           "irradiance_w_m2": round(float(sun.get("irradiance_w_m2") or 0.0)), "daylight": elevation > 0.0}
    if sun.get("hour") is not None:
        out["hour"] = round(float(sun["hour"]), 2)
        out["day_s"] = sun.get("day_s")
    return out


def sense_battery(ctx: Context) -> dict[str, Any]:
    store = _store(ctx) or {}
    capacity = float(store.get("capacity_j") or 0.0)
    charge = float(store.get("charge_j") or 0.0)
    return {"share_of_full": round(charge / capacity, 3) if capacity else ctx.program.get("charge_share"),
            "charge_j": round(charge), "capacity_j": round(capacity),
            "charging_w": _panels_w(ctx, store.get("id")),
            "rests_below": ctx.program.get("rest_below"), "rests_until": ctx.program.get("rest_until"),
            "times_rested": ctx.program.get("rests")}


def sense_wheels(ctx: Context) -> dict[str, Any]:
    controls = _controls(ctx)
    out = []
    for side in ("left", "right"):
        c = controls.get(ctx.program.get(side)) or {}
        out.append({"side": side, "condition": c.get("condition", ""), "speed_rpm": c.get("speed_rpm", 0.0),
                    "told": {"power": c.get("power"), "direction": c.get("direction"), "setting": c.get("setting")}})
    return {"wheels": out, "stalled": [w["side"] for w in out if str(w["condition"]).startswith("stalled")],
            "times_turned_away": ctx.program.get("turns")}


def sense_load(ctx: Context) -> dict[str, Any]:
    r = ctx.routine
    if r is None:
        return {"carries": False}
    return {"carries": True, **r.load_reading()}


def sense_places(ctx: Context) -> dict[str, Any]:
    r = ctx.routine
    places = (r.places if r is not None else {}) or {}
    return {name: {**toward(ctx, float(xz[0]), float(xz[1])), "x_m": xz[0], "z_m": xz[1]}
            for name, xz in places.items()}


def sense_nearby(ctx: Context) -> dict[str, Any]:
    mine = set(ctx.program.get("parts") or []) | {ctx.program.get("body")}
    ax, az = ctx.at()
    out = []
    for b in ctx.bodies or []:
        name = b.get("name")
        if name in mine or not name:
            continue
        p = b.get("position_m") or [0, 0, 0]
        d = math.hypot(float(p[0]) - ax, float(p[2]) - az)
        if d > NEAR_M:
            continue
        v = b.get("velocity_m_s") or [0, 0, 0]
        out.append({"name": name, "material": b.get("material"), "distance_m": round(d, 2),
                    "bearing_deg": relative_bearing(ctx.heading(), float(p[0]) - ax, float(p[2]) - az),
                    "moving": math.hypot(float(v[0]), float(v[2])) > 0.05, "anchored": bool(b.get("anchored"))})
    out.sort(key=lambda e: e["distance_m"])
    return {"things": out[:12]}


def sense_person(ctx: Context) -> dict[str, Any]:
    at = (ctx.person or {}).get("standing_m") if isinstance(ctx.person, dict) else None
    if not isinstance(at, (list, tuple)) or len(at) != 3:
        return {"present": False}
    return {"present": True, **toward(ctx, float(at[0]), float(at[2]))}


def sense_struck(ctx: Context) -> dict[str, Any]:
    parts = set(ctx.program.get("parts") or [])
    hits = [{"struck": i.get("struck"), "by": i.get("by"), "closing_speed_m_s": i.get("closing_speed_m_s"),
             "energy_j": i.get("energy_j")}
            for i in ctx.impacts if i.get("struck") in parts or i.get("by") in parts]
    return {"hits": hits[:6]}


@dataclass(frozen=True)
class Sense:
    name: str
    description: str
    read: Callable[[Context], dict[str, Any]]
    # Whether reading it asks the engine (surveys, the sun): those are read on
    # demand, never every step.
    asks_engine: bool = False


SENSES: dict[str, Sense] = {s.name: s for s in (
    Sense("position", "Where it is (x, z), which way its front faces (heading, degrees round from +z), how fast "
                      "it is going, and what its program is doing and why.", sense_position),
    Sense("slope", "Its own tilt (nose up, left side up), and the lie of the land round it: which way is "
                   "downhill and uphill (bearing, degrees, positive to its left) and how steep; whether the "
                   "ground rises ahead.", sense_slope, asks_engine=True),
    Sense("ground", "The ground under it: its surface (sand, soil, rock), how deep the sand and soil are, "
                    "its slope, and any water on it.", sense_ground, asks_engine=True),
    Sense("water", "Its water sensors, the nearest water round it (distance, bearing, depth), and which "
                   "bearings are dry three metres out.", sense_water, asks_engine=True),
    Sense("sun", "Where the sun stands: its height, its bearing from the machine's front, how strongly it "
                 "shines, whether it is day, and the hour when the room has a day.", sense_sun, asks_engine=True),
    Sense("battery", "What its battery holds, as a share of full and in joules, what is charging it, and "
                     "when its program rests.", sense_battery),
    Sense("wheels", "What each wheel's controller is doing and reports, and whether either has stalled.",
          sense_wheels),
    Sense("load", "What it carries in its hopper, by material, against what it can carry.", sense_load),
    Sense("places", "How far and which way each place it knows lies: its dig site, its depot.", sense_places),
    Sense("nearby", "The things within eight metres of it: what they are, how far, which way, whether they "
                    "move.", sense_nearby),
    Sense("person", "Whether a person is with it, and how far and which way they stand.", sense_person),
    Sense("struck", "What struck it, or what it ran into, since the last step.", sense_struck),
)}


def catalogue() -> list[dict[str, str]]:
    """The senses, in words, for whoever is told what a machine can sense."""
    return [{"name": s.name, "description": s.description} for s in SENSES.values()]


def read(ctx: Context, names: list[str] | None = None, engine: bool = True) -> dict[str, Any]:
    """Every sense named, or all of them; with engine=False, only those that
    ask the engine nothing (for every step). A sense that fails reads as its
    failure, and never stops the rest."""
    out: dict[str, Any] = {}
    for name in names or list(SENSES):
        sense = SENSES.get(name)
        if sense is None or (not engine and sense.asks_engine):
            continue
        try:
            out[name] = sense.read(ctx)
        except Exception as failed:               # a reading that fails says so
            out[name] = {"failed": f"{type(failed).__name__}: {str(failed)[:80]}"}
    return out


# ---- what happened: the readings that count as events -----------------------

def _side(sensor: dict[str, Any]) -> str:
    side = sensor.get("side", 0)
    return "left" if side > 0 else "right" if side < 0 else "middle"


def situations(before: dict[str, Any] | None, now: dict[str, Any], machines: dict[str, Any] | None,
               impacts: list[dict[str, Any]]) -> list[str]:
    """What happened to the machine between two readings of its program, in
    the words its panel uses. Nothing while it is off; while it is asked by
    someone, only a knock."""
    if not now.get("power"):
        return []
    out: list[str] = []
    parts = set(now.get("parts") or [])
    for i in impacts:
        if i.get("struck") in parts and i.get("by") not in parts:
            out.append(f"{i.get('by')} struck it at {float(i.get('closing_speed_m_s') or 0.0):.1f} m/s")
        elif i.get("by") in parts and i.get("struck") not in parts:
            out.append(f"it ran into {i.get('struck')} at {float(i.get('closing_speed_m_s') or 0.0):.1f} m/s")
    if now.get("asked"):
        return out
    was = before or {}
    seen_was = {_side(s) for s in was.get("sensors") or [] if s.get("sees")}
    for s in now.get("sensors") or []:
        if s.get("sees") and _side(s) not in seen_was:
            out.append(f"water ahead on its {_side(s)}")
    controls = {c.get("id"): c for c in (machines or {}).get("controls") or []}
    for side, ident in (("left", now.get("left")), ("right", now.get("right"))):
        condition = str((controls.get(ident) or {}).get("condition") or "")
        if condition.startswith("stalled") and was.get("doing") == "going forward":
            out.append(f"its {side} wheel stalled")
    why, why_was = str(now.get("why") or ""), str(was.get("why") or "")
    if why != why_was and why.startswith("the ground here is steeper"):
        out.append("the ground ahead is steeper than it climbs")
    below = float(now.get("rest_below") or 0.0)
    share, share_was = float(now.get("charge_share") or 0.0), float(was.get("charge_share") or 1.0)
    if below > 0.0 and share < below + 0.1 <= share_was:
        out.append(f"its battery is getting low: {round(100 * share)}%")
    return out
