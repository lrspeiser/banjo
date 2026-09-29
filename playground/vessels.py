"""A container holds matter, and tips it out.

The owner, 2026-09-27: *"ideally a container can hold the voxels of any
material including water. so i can have a bucket that holds sand or a kettle
that holds water. that should be built and work. turning the bucket over
should pour the voxels out into a different container. however if we don't
want to model it we can convert the voxels to a single mass when in a
container."*

This is the second of those. A vessel holds a MASS of each substance, not
grains: turning it over moves that mass out, into a vessel under its mouth if
there is one and onto the ground if there is not. Nothing here simulates a
falling stream, and a person watching sees the same thing either way -- the
bucket empties, the other one fills.

**IN KILOGRAMS, not litres.** The Workshop knows a vessel's capacity in litres
(`workshop_graph`'s contents: the kettle is 8.64 l) because it has the
geometry, but the room's goods ledger is in kilograms throughout and the goods
themselves have no density: `engine_materials` knows iron and oak and ice,
and knows nothing of sand, clay, water or copper ore. Declaring litres here
would mean inventing a density table for goods, which is a second source of
truth for the mass of everything in the game. So a vessel says what it holds
in kilograms, and whoever declares one converts if they have a density to
convert with.

**A vessel is not a stockpile.** A heap on the ground is a place
(`machine_goods`); a vessel is goods held BY A BODY, and it rides that body
the way a port's mouth does (`machine_ports`). Drive the cart and its bucket
goes with it, full. Tip the bucket and what it holds comes out where its mouth
is pointing, not where the bucket was declared.

**What it holds has a temperature**, and pouring MIXES: hot water into a cold
pail comes out between the two, weighted by heat capacity. The contents follow
the temperature of the body that holds them -- ONE WAY, and that is the honest
limit: the body does not cool for having warmed them, because its heat is the
engine's and nothing outside can take heat out of a lump in the thermal
network. Making that conserve means the contents being a lump in it too, which
is the same change that would let them boil.

**What it is not, yet:** a stream you can see between the two, a vessel that
fills partly and sloshes, a lid, a substance that will not pour (a bucket of
set concrete tips out as readily as sand), boiling and steam, and a vessel
whose contents warm the vessel back.
"""
from __future__ import annotations

import math
from typing import Any, Iterable

NAMES_MOST = 60
#: How far a vessel may be turned from upright before what it holds begins to
#: come out. Sixty degrees is past the point where a real open pail spills:
#: below it the rim is still above the level of what is in it for anything but
#: a brim-full one, and this holds no notion of how full a vessel is.
POURS_PAST_DEG = 60.0
#: How fast a fully inverted vessel empties, per kilogram it holds. Declared,
#: not derived: a real rate depends on the mouth's area, the stuff's angle of
#: repose and how full it is, and none of those are modelled here. Five a
#: second empties a 20 kg bucket in about four seconds, which is what tipping
#: one looks like.
POURS_KG_S = 5.0
#: How near a mouth must be, across the ground, to catch what another pours,
#: and how far below. A pail held over another catches; one beside it does not.
CATCH_M = 0.45
CATCH_BELOW_M = 1.5
#: The room's own temperature when nothing says otherwise, in kelvin: the
#: thermal network's, so a vessel nobody has heated reads the same as the air
#: round it.
AMBIENT_K = 293.15
#: How fast heat crosses from the body into what it holds, in watts per kelvin
#: of difference, when a vessel does not say. Declared, not derived: a real
#: figure is the wetted area over the wall's resistance, and a vessel here has
#: no wall -- it has a body somewhere near it and a mass in a ledger. Twenty
#: takes a pail of water most of the way to a hot plate's temperature in a
#: couple of minutes, which is what watching a kettle looks like.
WARMS_W_K = 20.0
#: What a kilogram of each substance takes to warm by a kelvin, J/kg/K, at
#: room temperature. Handbook values: water 4182, dry sand 830, clay 920,
#: limestone 910, hematite 650, bauxite 850, Portland cement 880, copper 385,
#: soda-lime glass 840, concrete 880, alumina 880, aluminium 897, iron 449,
#: dry oak about 2000.
#:
#: WHY A TABLE HERE AND NOT THE THERMAL MODEL'S. The engine's model knows the
#: substances BODIES are made of -- iron, alumina, ice, dry wood -- and knows
#: nothing of the goods the ledger moves: there is no "sand", no "clay", no
#: "copper ore" in it, because none of those has ever been a body. Reading it
#: would answer for a third of this list and raise for the rest.
SPECIFIC_HEAT_J_KG_K = {
    "water": 4182.0, "sand": 830.0, "clay": 920.0, "limestone": 910.0,
    "iron ore": 650.0, "bauxite": 850.0, "cement": 880.0, "copper": 385.0,
    "copper wire": 385.0, "copper ore": 700.0, "glass": 840.0,
    "concrete": 880.0, "alumina ceramic": 880.0, "aluminum": 897.0,
    "iron": 449.0, "oak": 2000.0, "soil": 800.0, "sand and soil": 800.0,
}
#: And for anything not in it: a middling mineral, so an unnamed substance
#: warms at a believable rate rather than instantly or never.
DEFAULT_SPECIFIC_HEAT_J_KG_K = 800.0


def specific_heat(substance: str) -> float:
    return SPECIFIC_HEAT_J_KG_K.get(substance, DEFAULT_SPECIFIC_HEAT_J_KG_K)


def _turn(q: Iterable[float], v: Iterable[float]) -> list[float]:
    """A vector turned by a quaternion (w, x, y, z), normalised first because
    the engine's replies are rounded to 1e-5 and a still body otherwise reads
    a fraction of a degree of turn (machine_ports does the same)."""
    w, x, y, z = (float(c) for c in q)
    n = math.sqrt(w * w + x * x + y * y + z * z)
    if n < 1e-12:
        return [float(c) for c in v]
    w, x, y, z = w / n, x / n, y / n, z / n
    vx, vy, vz = (float(c) for c in v)
    tx, ty, tz = 2.0 * (y * vz - z * vy), 2.0 * (z * vx - x * vz), 2.0 * (x * vy - y * vx)
    return [vx + w * tx + (y * tz - z * ty),
            vy + w * ty + (z * tx - x * tz),
            vz + w * tz + (x * ty - y * tx)]


def _number(value: Any, low: float, high: float, what: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{what} must be a number")
    if not math.isfinite(out) or out < low or out > high:
        raise ValueError(f"{what} must be between {low:g} and {high:g}")
    return out


def checked(given: Any) -> list[dict[str, Any]]:
    """A room's vessels, in the room's own words and kilograms."""
    if given in (None, []):
        return []
    if not isinstance(given, list) or len(given) > 64:
        raise ValueError("vessels is a list of at most 64")
    out: list[dict[str, Any]] = []
    for i, vessel in enumerate(given):
        if not isinstance(vessel, dict):
            raise ValueError(f"vessel {i} is not an object")
        unknown = set(vessel) - {"name", "body", "capacity_kg", "accepts", "holds",
                                 "pours_past_deg", "pours_kg_s", "mouth_mm",
                                 "temperature_k", "warms_w_k"}
        if unknown:
            raise ValueError(f"a vessel cannot say {sorted(unknown)}: it holds name, body, "
                             f"capacity_kg, accepts, holds, pours_past_deg, pours_kg_s, "
                             f"mouth_mm, temperature_k and warms_w_k")
        name = " ".join(str(vessel.get("name") or "").split())[:NAMES_MOST]
        if not name or any(o["name"] == name for o in out):
            raise ValueError(f"vessel {i} needs a name of its own")
        body = " ".join(str(vessel.get("body") or "").split())[:NAMES_MOST]
        if not body:
            raise ValueError(f"vessel {name!r} rides a body: say which")
        holds = vessel.get("holds") or {}
        if not isinstance(holds, dict):
            raise ValueError(f"vessel {name!r}: holds is a substance to a mass in kilograms")
        made = {
            "name": name, "body": body,
            "capacity_kg": _number(vessel.get("capacity_kg", 20.0), 0.001, 1e6,
                                   f"vessel {name!r} capacity_kg"),
            "accepts": [" ".join(str(s).split())[:NAMES_MOST] for s in (vessel.get("accepts") or [])],
            "holds": {" ".join(str(k).split())[:NAMES_MOST]: _number(v, 0.0, 1e6, f"{name!r} holds {k}")
                      for k, v in holds.items() if float(v) > 0.0},
            "pours_past_deg": _number(vessel.get("pours_past_deg", POURS_PAST_DEG), 1.0, 179.0,
                                      f"vessel {name!r} pours_past_deg"),
            "pours_kg_s": _number(vessel.get("pours_kg_s", POURS_KG_S), 0.001, 1e4,
                                  f"vessel {name!r} pours_kg_s"),
            "mouth_mm": [float(v) for v in (vessel.get("mouth_mm") or [0.0, 0.0, 0.0])],
            "temperature_k": _number(vessel.get("temperature_k", AMBIENT_K), 1.0, 5000.0,
                                     f"vessel {name!r} temperature_k"),
            "warms_w_k": _number(vessel.get("warms_w_k", WARMS_W_K), 0.0, 1e5,
                                 f"vessel {name!r} warms_w_k"),
        }
        held = sum(made["holds"].values())
        if held > made["capacity_kg"] + 1e-9:
            raise ValueError(f"vessel {name!r} holds {held:g} kg and takes {made['capacity_kg']:g}")
        out.append(made)
    return out


class Vessel:
    """One container: what it holds, where its mouth is now, and how far from
    upright it has been turned."""

    def __init__(self, declared: dict[str, Any]):
        self.declared = declared
        self.name = str(declared["name"])
        self.body = str(declared["body"])
        self.capacity_kg = float(declared["capacity_kg"])
        self.accepts = list(declared.get("accepts") or [])
        self.holds: dict[str, float] = dict(declared.get("holds") or {})
        self.pours_past_deg = float(declared["pours_past_deg"])
        self.pours_kg_s = float(declared["pours_kg_s"])
        self.mouth_local_m = [float(v) / 1000.0 for v in declared["mouth_mm"]]
        #: What is IN it is at this temperature -- one figure for the lot,
        #: because a vessel holds a mass and not a body with an inside.
        self.temperature_k = float(declared["temperature_k"])
        self.warms_w_k = float(declared["warms_w_k"])
        #: Where the mouth is in the room, and how far the vessel is from
        #: upright. Both are None until a step has said where its body is.
        self.mouth_m: list[float] | None = None
        self.tilt_deg: float | None = None

    # ---- what it holds ---------------------------------------------------

    def held_kg(self) -> float:
        return sum(self.holds.values())

    def heat_capacity_j_k(self) -> float:
        """What it takes to warm everything in it by a kelvin."""
        return sum(kg * specific_heat(what) for what, kg in self.holds.items())

    def warms(self, dt_s: float, toward_k: float) -> float:
        """Heat crossing from the body it rides into what it holds, for that
        long. Answers the joules that went.

        ONE WAY, and this is the honest limit of it: the contents follow the
        body's temperature and the BODY DOES NOT COOL for having warmed them.
        The body's heat is the engine's -- it is a lump in the thermal network
        with its own mass and its own losses -- and nothing outside can take
        heat out of it; the `heat` op only puts external work IN.

        WATER NO LONGER COMES THROUGH HERE. Making this conserve meant the
        contents being a lump in that network too, which is the same change
        that lets them boil, and that is done: a vessel holding water is
        declared to the engine as what its body CARRIES
        (fracture_lab._vessel_water_is_carried), and `Vessels.warm` reads the
        engine's kilograms and temperature back instead of calling this. What
        still comes through here is everything the model has no
        thermochemistry for -- sand, clay, ore -- for which this remains the
        rule until it has.
        """
        capacity = self.heat_capacity_j_k()
        if capacity <= 0.0 or self.warms_w_k <= 0.0 or dt_s <= 0.0:
            return 0.0
        gap = float(toward_k) - self.temperature_k
        joules = self.warms_w_k * gap * float(dt_s)
        # Never past the body's own temperature in one step: a big step and a
        # small capacity would otherwise overshoot and swing about, which is
        # the difference between a kettle warming and a kettle ringing.
        most = abs(gap) * capacity
        if abs(joules) > most:
            joules = most if joules > 0.0 else -most
        self.temperature_k += joules / capacity
        return joules

    def room_kg(self) -> float:
        return max(0.0, self.capacity_kg - self.held_kg())

    def takes(self, substance: str) -> bool:
        """Whether it will have that substance at all. A vessel that names
        none takes anything, the way a port that names no goods does."""
        return not self.accepts or substance in self.accepts

    def put(self, load: dict[str, float], at_k: float | None = None) -> dict[str, float]:
        """As much of that as will go in, in the order given. Answers what
        actually went, so a caller can see what it still has.

        `at_k` is how hot what is arriving is, and the two MIX: the vessel
        comes out at the heat-capacity-weighted mean of what it had and what
        it got, which is what mixing is. Pouring boiling water into a cold
        pail warms the pail's water and cools the boiling, in one figure.
        An empty vessel simply takes the arriving temperature.
        """
        arriving_capacity = (sum(kg * specific_heat(what) for what, kg in load.items())
                             if at_k is not None else 0.0)
        had_capacity = self.heat_capacity_j_k()
        went: dict[str, float] = {}
        for substance, kg in load.items():
            kg = float(kg)
            if kg <= 0.0 or not self.takes(substance):
                continue
            room = self.room_kg()
            if room <= 1e-12:
                break
            took = min(kg, room)
            self.holds[substance] = self.holds.get(substance, 0.0) + took
            went[substance] = went.get(substance, 0.0) + took
        if at_k is not None and went:
            # Only what actually went in mixes; what missed never arrived.
            share = (sum(kg * specific_heat(what) for what, kg in went.items())
                     / arriving_capacity if arriving_capacity > 0.0 else 0.0)
            came = arriving_capacity * share
            if had_capacity + came > 0.0:
                self.temperature_k = ((self.temperature_k * had_capacity + float(at_k) * came)
                                      / (had_capacity + came))
        return went

    def take(self, kg: float, substance: str | None = None) -> dict[str, float]:
        """That much out of it, off one substance or off everything in
        proportion, so tipping a bucket of two things pours both."""
        kg = float(kg)
        if kg <= 0.0 or not self.holds:
            return {}
        if substance is not None:
            have = self.holds.get(substance, 0.0)
            took = min(kg, have)
            if took <= 0.0:
                return {}
            self._drop(substance, took)
            return {substance: took}
        held = self.held_kg()
        share = min(1.0, kg / held) if held > 0.0 else 0.0
        out: dict[str, float] = {}
        for name in list(self.holds):
            took = self.holds[name] * share
            if took > 0.0:
                self._drop(name, took)
                out[name] = took
        return out

    def _drop(self, substance: str, kg: float) -> None:
        left = self.holds.get(substance, 0.0) - kg
        if left <= 1e-9:
            self.holds.pop(substance, None)
        else:
            self.holds[substance] = left

    # ---- where it is -----------------------------------------------------

    def rides(self, at: list[float], q: list[float]) -> None:
        """Its body has moved: the mouth goes with it, and how far the vessel
        is from upright is read off the same turn. A vessel's own up is its
        body's y; the angle is between that and the room's."""
        self.mouth_m = [a + b for a, b in zip(at, _turn(q, self.mouth_local_m))]
        up = _turn(q, [0.0, 1.0, 0.0])
        self.tilt_deg = math.degrees(math.acos(max(-1.0, min(1.0, up[1]))))

    def pouring(self) -> float:
        """How hard it is pouring, 0 upright to 1 upside down. Nothing until
        it is past its angle, then more the further it goes over."""
        if self.tilt_deg is None or self.tilt_deg <= self.pours_past_deg:
            return 0.0
        span = 180.0 - self.pours_past_deg
        return min(1.0, (self.tilt_deg - self.pours_past_deg) / span) if span > 1e-9 else 1.0

    def report(self) -> dict[str, Any]:
        return {"name": self.name, "body": self.body,
                "holds_kg": {k: round(v, 3) for k, v in self.holds.items()},
                "capacity_kg": round(self.capacity_kg, 3),
                "temperature_k": round(self.temperature_k, 2),
                "temperature_c": round(self.temperature_k - 273.15, 2),
                "at_m": [round(v, 4) for v in self.mouth_m] if self.mouth_m else None,
                "tilt_deg": round(self.tilt_deg, 1) if self.tilt_deg is not None else None,
                "pouring": round(self.pouring(), 3)}


class Vessels:
    """Every container in the one open room: what each holds, where its mouth
    has got to, and what comes out of the ones that have been turned over."""

    def __init__(self, spec: dict[str, Any] | None):
        declared = ((spec or {}).get("vessels") or []) if isinstance(spec, dict) else []
        self.vessels = [Vessel(v) for v in checked(declared)]
        self.by_body: dict[str, list[Vessel]] = {}
        for vessel in self.vessels:
            self.by_body.setdefault(vessel.body, []).append(vessel)
        self.spec = spec

    def __bool__(self) -> bool:
        return bool(self.vessels)

    def by_name(self, name: str) -> Vessel | None:
        return next((v for v in self.vessels if v.name == name), None)

    def on_body(self, body: str) -> list[Vessel]:
        return list(self.by_body.get(body) or [])

    def follow(self, bodies: Any) -> None:
        """The poses a step carries -- only the bodies that moved, so they are
        read and not replaced. Every vessel on one that moved rides it."""
        if not isinstance(bodies, list):
            return
        for body in bodies:
            if not isinstance(body, dict) or not body.get("name"):
                continue
            riders = self.by_body.get(str(body["name"]))
            if not riders:
                continue
            at = body.get("position_m")
            if not isinstance(at, (list, tuple)) or len(at) != 3:
                continue
            q = body.get("orientation_wxyz")
            q = [float(v) for v in q] if isinstance(q, (list, tuple)) and len(q) == 4 else [1.0, 0.0, 0.0, 0.0]
            for vessel in riders:
                vessel.rides([float(v) for v in at], q)

    def catcher(self, pourer: Vessel) -> Vessel | None:
        """The vessel a pour lands in: the nearest mouth under this one and
        close enough across the ground, and not one that is itself pouring."""
        if pourer.mouth_m is None:
            return None
        best, nearest = None, CATCH_M
        for other in self.vessels:
            if other is pourer or other.mouth_m is None or other.pouring() > 0.0:
                continue
            drop = pourer.mouth_m[1] - other.mouth_m[1]
            if drop <= 0.0 or drop > CATCH_BELOW_M:
                continue
            across = math.dist((pourer.mouth_m[0], pourer.mouth_m[2]),
                               (other.mouth_m[0], other.mouth_m[2]))
            if across < nearest:
                best, nearest = other, across
        return best

    def warm(self, dt_s: float, heat: Any = None, ambient_k: float = AMBIENT_K) -> None:
        """Every vessel's contents, toward the temperature of the body that
        holds it, for that long.

        `heat` is the block a step carries (`reply["heat"]`). A body within a
        kelvin of ambient is NOT in it -- the engine leaves those out, and
        there are at most 48 -- so a body that is not named is a body at the
        room's own temperature, which is exactly what a vessel standing in a
        cold room should follow.
        """
        if dt_s <= 0.0:
            return
        hot: dict[str, float] = {}
        # What the ENGINE is carrying for each body, where it is carrying
        # anything: {body: (kilograms by substance, its temperature)}.
        carried: dict[str, tuple[dict[str, float], float]] = {}
        if isinstance(heat, dict):
            for body in (heat.get("bodies") or []):
                if not isinstance(body, dict) or body.get("name") is None:
                    continue
                name = str(body["name"])
                t_k = body.get("t_k")
                if isinstance(t_k, (int, float)):
                    hot[name] = float(t_k)
                kg = body.get("carrying_kg")
                at_c = body.get("carrying_c")
                if isinstance(kg, dict) and kg and isinstance(at_c, (int, float)):
                    carried[name] = ({str(k): float(v) for k, v in kg.items()},
                                     float(at_c) + 273.15)
        for vessel in self.vessels:
            # WHERE THE ENGINE IS CARRYING IT, the engine is right and this is
            # only reading. Water declared to the thermal network is a lump in
            # it: the engine warms it through the body's wall, holds it at its
            # boiling point, and boils it away, none of which the rule below
            # can do. So take its kilograms and its temperature and do not
            # relax toward anything.
            #
            # Anything else in the same vessel rides that one temperature, the
            # way it always has -- a vessel holds a mass, not a body with an
            # inside.
            engine = carried.get(vessel.body)
            if engine is not None:
                kg, at_k = engine
                for what, amount in kg.items():
                    if what in vessel.holds or amount > 0.0:
                        vessel.holds[what] = amount
                for what in [w for w, a in vessel.holds.items()
                             if w in kg and not (a > 0.0)]:
                    vessel.holds.pop(what, None)
                vessel.temperature_k = at_k
                continue
            vessel.warms(dt_s, hot.get(vessel.body, float(ambient_k)))

    def spill(self, dt_s: float, goods: Any = None) -> list[dict[str, Any]]:
        """What came out of everything that has been turned over, this step.

        Into a vessel under the mouth if there is one, onto the ground if
        there is not -- and if there is no goods ledger to put a heap on, it
        is gone, which is what tipping a bucket into a river does.
        """
        moved: list[dict[str, Any]] = []
        for vessel in self.vessels:
            share = vessel.pouring()
            if share <= 0.0 or not vessel.holds:
                continue
            poured = vessel.take(vessel.pours_kg_s * share * max(0.0, float(dt_s)))
            if not poured:
                continue
            caught = self.catcher(vessel)
            # What the catcher would not have -- it is full, or will not take
            # that substance -- misses it and goes on the ground.
            missed = dict(poured)
            if caught is not None:
                # What pours carries its temperature with it, and mixes into
                # whatever is already in the other one.
                went = caught.put(poured, at_k=vessel.temperature_k)
                missed = {k: v - went.get(k, 0.0) for k, v in poured.items()
                          if v - went.get(k, 0.0) > 1e-9}
            if missed and goods is not None and vessel.mouth_m is not None:
                goods.put(vessel.mouth_m[0], vessel.mouth_m[2], missed)
            moved.append({
                "from": vessel.name,
                "into": caught.name if caught is not None else "the ground",
                "poured_kg": {k: round(v, 4) for k, v in poured.items()},
                "missed_kg": {k: round(v, 4) for k, v in missed.items()} if caught is not None and missed else {},
                "tilt_deg": round(vessel.tilt_deg or 0.0, 1),
            })
        return moved

    def holders(self) -> list[dict[str, Any]]:
        """What every container holds, for the page's slots."""
        return [v.report() for v in self.vessels]

    def save(self) -> None:
        """What each holds, written back into the room's own block, so a room
        that is put away and opened again is as full as it was left."""
        if not isinstance(self.spec, dict):
            return
        declared = self.spec.get("vessels")
        if not isinstance(declared, list):
            return
        for vessel in self.vessels:
            for row in declared:
                if isinstance(row, dict) and str(row.get("name") or "") == vessel.name:
                    row["holds"] = {k: round(v, 4) for k, v in vessel.holds.items()}
                    row["temperature_k"] = round(vessel.temperature_k, 4)
