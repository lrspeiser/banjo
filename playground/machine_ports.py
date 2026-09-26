"""Where goods go into a device and where they come out (docs/machine-world.md,
"Devices that pair").

The owner, 2026-09-26: "devices that are paired should be defined that way when
built. for instance the smelter should have a port where new ore goes in and a
port where finished goods exit. the rover has a port for where it stores the ore
and those two ports match up so it can release its ore to the smelter. it should
be clear where the port is on a device with some indicator."

Until now a transfer was to a PLACE. A machine within two metres of a heap on
the ground could dump onto it or take off it (machine_goods), and that was all:
nothing on a machine said "ore goes in here", nothing said a rover's store and a
smelter's intake belonged together, and nothing was drawn, so a person watching
could not see why a transfer did or did not happen.

A port is a MOUTH on a device, declared with the machine it belongs to, on one
of its parts, so it moves with the machine:

    "ports": [{"name": "smelter intake", "flow": "in", "body": "smelter",
               "at_mm": [-3000, 1100, -9200], "normal": [0, 0, 1],
               "holds": "smelter intake pile", "goods": ["copper ore"]}]

  * `flow` is "in" (it takes goods) or "out" (it gives them).
  * `fitting` is the coupling. Two ports pair only when theirs match, the way
    a hose fits one tap and not another. "goods" is the only one so far, and it
    is what a port that says none is given.
  * `body`, `at_mm` and `normal` are where the mouth is and which way it looks,
    in the room's own millimetres as the room is made, exactly as a solar
    panel's are. Where that lies on the body is worked out from where the SPEC
    puts that body (`as_made`), and after that the mouth rides wherever the
    engine says the body has got to: a rover's port turns with the rover.
  * `holds` says what is BEHIND the mouth: "hopper", the machine's own load
    (machine_routine), or the name of one of the room's stockpiles
    (machine_goods).
  * `goods` are the substances it will take or give; none means anything.

**A port does not replace a stockpile. It docks to what one holds.** A heap on
the ground is still a heap: the smelter's intake pile is where the ore lies, a
person can still walk up and see it, the Workshop's rack still takes whatever
lands on it, the smelter's own recipe still works that pile into the next, and
every room that dumps and takes by place goes on working untouched. What the
port adds is the geometry and the contract -- where the mouth is, which way it
faces, what it will accept -- so that a transfer can be made to a THING rather
than to a patch of ground. Two things are separated on purpose: a port decides
WHETHER and WHERE, and a hopper or a heap is WHAT HOLDS.

**Two ports pair** when one gives and the other takes, their fittings match,
they are no further apart than DOCK_M, their two faces are opposed within
FACING_DEG of exactly mouth to mouth, and neither is behind the other. They
must belong to different machines: a device does not feed itself. `between`
has the rule and why it is written that way and not another.

**What is NOT modelled.** There is no chute, no pipe, no hose and no valve in
the physics. Nothing is drawn between two paired mouths, no body travels along
one, and the goods are simply booked out of one holder and into the other; the
mass leaves one account and arrives in the other in the same call. A port
carries goods only -- no force, no heat, no charge and no readings. It holds
nothing itself. It does not open or shut, it cannot be blocked or jammed, it
cannot leak, and nothing about it wears out. Two mouths that pair do so however
much of the machine stands between them: there is no check that the way is
clear.
"""
from __future__ import annotations

import math
from typing import Any, Callable, Iterable

# The coupling a port carries. Goods are the only thing that flows between
# machines today; power and heat are their own systems and go nowhere near
# here. A new one is a word in this tuple and a sense of what it moves.
FITTINGS = ("goods",)
# What a port says it is behind when what is behind it is the machine's own
# load rather than a heap of the room's.
HOPPER = "hopper"

# How near two mouths must be to pass anything. A DECLARED GAME CONSTANT, not a
# clearance measured off a real coupling; here is where the number comes from.
# It is set by what a machine can actually do: a machine told to go to a point
# stops about a metre short of it -- the `approaching` ask stops within a metre,
# and docs/machine-world.md measures 0.92 m, 0.98 m and 0.62 m in real rooms --
# so mouths that had to touch could never be brought together by a machine that
# drives to them. 1.2 m is that metre with a little over. A person can still
# carry two things closer than this by hand, and then they dock.
DOCK_M = 1.2
# How far from exactly mouth to mouth the two faces may be turned: a declared
# game constant. It is deliberately loose. A machine that drives at a thing
# stops about 3.4 degrees off square (measured in docs/machine-world.md) and
# lets itself drift 8 degrees off the line on the way, so anything past ten
# degrees is already slack -- but a mouth need not be on the machine's nose,
# and the ground it stands on is not level, so both add whatever they add. 60
# degrees is well clear of all of that and short of the 90 at which the two
# mouths are at right angles and nothing could pass between them. Tighter would
# mean a dock a machine can see and reach and still not make, which is the one
# thing a person watching cannot forgive.
FACING_DEG = 60.0
FACING = math.cos(math.radians(FACING_DEG))
# A port whose partner is within this much of docking is worth saying out loud
# ("it is near, but turned away"), so a person can see why nothing moved rather
# than only that nothing did. Twice the dock: near enough to be about it.
NEAR_M = 2.0 * DOCK_M
PORTS_MOST = 8
NAMES_MOST = 64


# ---- vectors -------------------------------------------------------------------

def _unit(v: Iterable[float]) -> list[float]:
    x, y, z = (float(c) for c in v)
    n = math.sqrt(x * x + y * y + z * z)
    return [x / n, y / n, z / n] if n > 1e-12 else [0.0, 0.0, 1.0]


def _turn(q: Iterable[float], v: Iterable[float]) -> list[float]:
    """A vector turned by a quaternion (w, x, y, z). The engine's replies are
    rounded to 1e-5, so the quaternion is normalised first: a still body read
    half a degree of turn when it was not."""
    w, x, y, z = (float(c) for c in q)
    n = math.sqrt(w * w + x * x + y * y + z * z)
    if n < 1e-12:
        return [float(c) for c in v]
    w, x, y, z = w / n, x / n, y / n, z / n
    vx, vy, vz = (float(c) for c in v)
    # v + 2 * q_vec x (q_vec x v + w v)
    tx, ty, tz = 2.0 * (y * vz - z * vy), 2.0 * (z * vx - x * vz), 2.0 * (x * vy - y * vx)
    return [vx + w * tx + (y * tz - z * ty),
            vy + w * ty + (z * tx - x * tz),
            vz + w * tz + (x * ty - y * tx)]


def _unturn(q: Iterable[float], v: Iterable[float]) -> list[float]:
    """The same the other way: a vector in the room's frame said in the body's."""
    w, x, y, z = (float(c) for c in q)
    return _turn((w, -x, -y, -z), v)


# ---- the room's spelling, checked ------------------------------------------------

def checked(given: Any, name: str, named: set[str]) -> list[dict[str, Any]]:
    """A machine's ports as the room declares them, checked, in the room's
    millimetres. Raises with what is wrong.

    `holds` is NOT checked against the room's stockpiles here, for the same
    reason a process routine's `intake` is not: the machines block is settled
    before the goods block is, and a room's heaps come and go while it runs. A
    port that names a heap the room has not got says so when something tries to
    use it, which is where a person can do anything about it."""
    if given in (None, []):
        return []
    if not isinstance(given, list) or len(given) > PORTS_MOST:
        raise ValueError(f"program {name!r}: ports is a list of at most {PORTS_MOST}")
    out: list[dict[str, Any]] = []
    for k, port in enumerate(given):
        what = f"program {name!r} port {k}"
        if not isinstance(port, dict):
            raise ValueError(f"{what} is an object: name, flow, fitting, body, at_mm, normal, holds, goods")
        keys = {"name", "flow", "fitting", "body", "at_mm", "normal", "holds", "goods"}
        unknown = set(port) - keys
        if unknown:
            raise ValueError(f"{what} cannot say {sorted(unknown)}: it holds {', '.join(sorted(keys))}")
        port_name = " ".join(str(port.get("name") or "").split())[:NAMES_MOST]
        if not port_name or any(o["name"] == port_name for o in out):
            raise ValueError(f"{what} needs a name of its own")
        flow = str(port.get("flow") or "")
        if flow not in ("in", "out"):
            raise ValueError(f"{what}: flow is 'in' (it takes goods) or 'out' (it gives them)")
        fitting = str(port.get("fitting") or FITTINGS[0])
        if fitting not in FITTINGS:
            raise ValueError(f"{what}: its fitting is {fitting!r}; the fittings there are: "
                             + ", ".join(repr(f) for f in FITTINGS))
        body = str(port.get("body") or "")
        if body not in named:
            raise ValueError(f"{what} is on {body!r}, which is not in this room")
        at, normal = port.get("at_mm"), port.get("normal")
        if not isinstance(at, (list, tuple)) or len(at) != 3:
            raise ValueError(f"{what} needs at_mm as three numbers: where the mouth is, in the room's millimetres")
        if not isinstance(normal, (list, tuple)) or len(normal) != 3:
            raise ValueError(f"{what} needs normal as three numbers: which way the mouth looks")
        normal = [_float(v, -1e6, 1e6, f"{what} normal") for v in normal]
        if math.sqrt(sum(v * v for v in normal)) < 1e-6:
            raise ValueError(f"{what}: its mouth must look some way")
        holds = " ".join(str(port.get("holds") or HOPPER).split())[:NAMES_MOST]
        goods = port.get("goods") or []
        if not isinstance(goods, (list, tuple)) or len(goods) > 16:
            raise ValueError(f"{what}: goods is a list of at most 16 substances, or none for anything")
        out.append({"name": port_name, "flow": flow, "fitting": fitting, "body": body,
                    "at_mm": [_float(v, -100000.0, 100000.0, f"{what} at_mm") for v in at],
                    "normal": _unit(normal), "holds": holds,
                    "goods": [" ".join(str(g).split())[:NAMES_MOST] for g in goods if str(g).strip()]})
    return out


def _float(v: Any, lo: float, hi: float, what: str) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{what} is a number") from None
    if not (lo <= f <= hi) or f != f:
        raise ValueError(f"{what} is between {lo:g} and {hi:g}")
    return f


# ---- what is behind a mouth --------------------------------------------------------

class Heap:
    """A port that names one of the room's stockpiles: what is behind it is
    that heap, worked through the ledger, so the Workshop's rack still hears
    what lands on it and the pile stays the room's own block."""

    def __init__(self, goods: Any, pile: dict[str, Any]):
        self.goods, self.pile = goods, pile
        self.what = str(pile.get("name") or "a heap")

    def holds(self) -> dict[str, float]:
        return {str(k): float(v) for k, v in (self.pile.get("holds") or {}).items() if float(v) > 0.0}

    def room_kg(self) -> float:
        return math.inf                       # a heap on the ground takes what it is given

    def take(self, substance: str, kg: float) -> dict[str, float]:
        at = self.pile["at_m"]
        return self.goods.take(float(at[0]), float(at[1]), kg, substance=substance,
                               named=self.what)["took"]

    def give(self, goods: dict[str, float]) -> None:
        at = self.pile["at_m"]
        self.goods.put(float(at[0]), float(at[1]), goods, named=self.what)


class Load:
    """A port that says "hopper": what is behind it is the machine's own load
    (machine_routine), which is an account and not a body in the room."""

    def __init__(self, routine: Any):
        self.routine = routine
        self.what = "its hopper"

    def holds(self) -> dict[str, float]:
        return {k: v for k, v in (self.routine.goods or {}).items() if v > 0.0}

    def room_kg(self) -> float:
        return float(self.routine.load_room_kg())

    def take(self, substance: str, kg: float) -> dict[str, float]:
        return self.routine.goods_out({substance: kg})

    def give(self, goods: dict[str, float]) -> None:
        self.routine.load_in(0.0, 0.0, sum(goods.values()), goods)


# ---- a port as it stands --------------------------------------------------------

class Port:
    """One declared port and where its mouth is now. Its point and its facing
    are declared in the room's frame as the room is made; they are carried into
    the body's own frame from where the SPEC puts that body (`as_made`), and
    after that they ride wherever the engine says the body has got to."""

    def __init__(self, machine: str, declared: dict[str, Any]):
        # Read with the same defaults `checked` fills in, because a room file
        # keeps the spec as it was written and only the open validates it: the
        # room's goods ledger is read the same forgiving way.
        self.machine = machine
        self.declared = declared
        self.name = " ".join(str(declared.get("name") or "").split())[:NAMES_MOST]
        self.flow = str(declared.get("flow") or "in")
        self.fitting = str(declared.get("fitting") or FITTINGS[0])
        self.body = str(declared.get("body") or "")
        self.holds_name = " ".join(str(declared.get("holds") or HOPPER).split())[:NAMES_MOST]
        self.goods = [str(g) for g in (declared.get("goods") or [])]
        self.at_m = [float(v) / 1000.0 for v in (declared.get("at_mm") or [0.0, 0.0, 0.0])]
        self.normal = _unit(declared.get("normal") or [0.0, 0.0, 1.0])
        self.local_m: list[float] | None = None
        self.local_normal: list[float] | None = None

    def settled(self) -> bool:
        return self.local_m is not None

    def settle(self, position: Iterable[float], orientation: Iterable[float]) -> None:
        """Its mouth said in its body's own frame, from where the body stands
        as the room is made (`as_made`)."""
        p = [float(v) for v in position]
        self.local_m = _unturn(orientation, [self.at_m[k] - p[k] for k in range(3)])
        self.local_normal = _unturn(orientation, self.normal)

    def ride(self, position: Iterable[float], orientation: Iterable[float]) -> None:
        if self.local_m is None or self.local_normal is None:
            self.settle(position, orientation)
            return
        p = [float(v) for v in position]
        turned = _turn(orientation, self.local_m)
        self.at_m = [p[k] + turned[k] for k in range(3)]
        self.normal = _unit(_turn(orientation, self.local_normal))

    def passes(self, substance: str) -> bool:
        return not self.goods or substance in self.goods

    def reading(self) -> dict[str, Any]:
        return {"name": self.name, "machine": self.machine, "flow": self.flow, "fitting": self.fitting,
                "body": self.body, "holds": self.holds_name,
                "goods": list(self.goods),
                "at_m": [round(v, 4) for v in self.at_m],
                "normal": [round(v, 4) for v in self.normal]}


def between(giving: Port, taking: Port) -> tuple[bool, str, float]:
    """Whether a giving mouth and a taking one are paired, and why not when they
    are not: the plain rule, in one place, so the tool, the sense and the page
    all say the same thing. Returns (paired, why, how far apart).

    "Turned towards each other" is TWO things, and the pair of them is what
    makes the rule work at the short range a dock actually happens at:

    - the two faces are OPPOSED, within FACING_DEG of exactly mouth to mouth.
      That is what a person means by two chutes brought together, and it does
      not care where the mouths are, only which way they look;
    - and neither mouth is BEHIND the other: each has the other somewhere in
      front of its face. That is the half turn, and it is what refuses a
      machine that has driven past.

    The first rule written here asked instead that each face look ALONG the
    line joining the two mouths, within the same angle. It was wrong, and the
    page showed it: the mine's rover came alongside the smelter with its mouth
    0.53 m from the intake and was refused at 69 degrees, because over half a
    metre a third of a metre of lateral offset -- which a machine that stops
    within a metre of a point has every right to -- swings that line by 30
    degrees, and both mouths swing. The line between two mouths is a bad
    measure of anything the closer they get; which way they look is not."""
    away = [taking.at_m[k] - giving.at_m[k] for k in range(3)]
    far = math.sqrt(sum(v * v for v in away))
    if giving.machine == taking.machine:
        return False, "they are two mouths of the one machine", far
    if giving.fitting != taking.fitting:
        return False, f"a {giving.fitting} mouth does not fit a {taking.fitting} one", far
    if far > DOCK_M:
        return False, f"they are {far:.2f} m apart, and a dock is {DOCK_M:g} m", far
    opposed = -sum(giving.normal[k] * taking.normal[k] for k in range(3))
    if opposed < FACING:
        off = math.degrees(math.acos(max(-1.0, min(1.0, opposed))))
        return False, (f"they are {far:.2f} m apart but their mouths are turned {off:.0f} deg from facing each "
                       f"other, and a dock allows {FACING_DEG:g}"), far
    if far > 1e-6:
        toward = [v / far for v in away]
        if sum(giving.normal[k] * toward[k] for k in range(3)) < 0.0:
            return False, f"{taking.name} is behind {giving.name}, not in front of its mouth", far
        if -sum(taking.normal[k] * toward[k] for k in range(3)) < 0.0:
            return False, f"{giving.name} is behind {taking.name}, not in front of its mouth", far
    return True, "", far


def as_made(spec: dict[str, Any] | None) -> dict[str, tuple[list[float], list[float]]]:
    """Where each of the room's things stands AS THE ROOM IS MADE, by name: the
    frame a port's at_mm and normal are written in, the same one a solar
    panel's and a pin's are.

    It has to come out of the SPEC and not out of the first pose the engine
    reports. A room opened fresh gives the two the same, but a room rejoined or
    opened again from a save gives the bodies wherever they have got to, and a
    mouth carried into a body's frame from there lands wherever the machine has
    driven since. Measured in the page: the rover's store came back 1.55 m off
    its own deck, and docked with nothing ever again.

    A thing the spec does not place -- one installed into a running room --
    has no pose here, and its mouths settle on the first pose seen instead,
    which for a thing just set down is where it was set down."""
    out: dict[str, tuple[list[float], list[float]]] = {}
    for body in (spec or {}).get("precise_rigid_bodies") or []:
        at = body.get("position_m") if isinstance(body, dict) else None
        if isinstance(at, (list, tuple)) and len(at) == 3 and body.get("name"):
            q = body.get("orientation_wxyz")
            out[str(body["name"])] = ([float(v) for v in at],
                                      [float(v) for v in q] if isinstance(q, (list, tuple)) and len(q) == 4
                                      else [1.0, 0.0, 0.0, 0.0])
    for body in (spec or {}).get("bodies") or []:
        at = body.get("center_mm") if isinstance(body, dict) else None
        if isinstance(at, (list, tuple)) and len(at) == 3 and body.get("name"):
            q = body.get("orientation_wxyz")
            out.setdefault(str(body["name"]), ([float(v) / 1000.0 for v in at],
                                               [float(v) for v in q]
                                               if isinstance(q, (list, tuple)) and len(q) == 4
                                               else [1.0, 0.0, 0.0, 0.0]))
    return out


class Ports:
    """Every machine's ports in the one open room: where each mouth is now, and
    which pair with which.

    The engine knows nothing of any of this. A port is declared on a program in
    the room's spec and lives here, exactly as a routine does; what the engine
    gives is the poses, which the mouths ride."""

    def __init__(self, spec: dict[str, Any] | None = None,
                 holder_for: Callable[[Port], Any] | None = None):
        self.ports: list[Port] = []
        self.poses: dict[str, tuple[list[float], list[float]]] = {}
        self.holder_for = holder_for
        made = as_made(spec)
        for program in ((spec or {}).get("machines") or {}).get("programs") or []:
            if not isinstance(program, dict):
                continue
            for declared in program.get("ports") or []:
                if not isinstance(declared, dict) or not declared.get("name"):
                    continue          # a room the validator has not been through yet
                port = Port(str(program.get("name") or ""), declared)
                stands = made.get(port.body)
                if stands is not None:
                    port.settle(*stands)
                self.ports.append(port)

    def __bool__(self) -> bool:
        return bool(self.ports)

    def of(self, machine: str) -> list[Port]:
        return [p for p in self.ports if p.machine == machine]

    def by_name(self, name: str) -> Port | None:
        return next((p for p in self.ports if p.name == name), None)

    def follow(self, bodies: Any) -> None:
        """The poses a reply carries, which are only the bodies that changed
        (the runner sends a body again only when its record differs), so they
        are merged into what is known rather than replacing it. Every mouth on
        a body that moved rides it. A mouth whose body the spec did not place
        takes its place on that body from the first pose it is given."""
        if not isinstance(bodies, list):
            return
        for body in bodies:
            if not isinstance(body, dict) or not body.get("name"):
                continue
            at, q = body.get("position_m"), body.get("orientation_wxyz")
            if not isinstance(at, (list, tuple)) or len(at) != 3:
                continue
            q = [float(v) for v in q] if isinstance(q, (list, tuple)) and len(q) == 4 else [1.0, 0.0, 0.0, 0.0]
            name = str(body["name"])
            self.poses[name] = ([float(v) for v in at], q)
            for port in self.ports:
                if port.body != name:
                    continue
                if port.settled():
                    port.ride(at, q)
                else:
                    port.settle(at, q)

    def pair_of(self, port: Port) -> tuple[Port | None, Port | None, str, float]:
        """The mouth this one is docked to, and failing that the nearest one it
        might have been docked to, why it is not, and how far off it is.

        The distance comes back so the caller can decide what to make of it:
        the page paints a mouth amber only for a partner within NEAR_M, since a
        ring lit for something five metres away says nothing, while the dock
        tool names the nearest partner however far off, because a person asking
        why nothing moved wants the answer whatever it is."""
        near: Port | None = None
        near_far, why = math.inf, ""
        for other in self.ports:
            # A device does not feed itself, so its own other mouth is not even
            # worth reporting as near: a smelter's intake and outlet stand less
            # than a dock apart, and the page would paint both amber for ever.
            if other is port or other.flow == port.flow or other.machine == port.machine:
                continue
            giving, taking = (port, other) if port.flow == "out" else (other, port)
            paired, said, far = between(giving, taking)
            if paired:
                return other, None, "", far
            if far < near_far:
                near, near_far, why = other, far, said
        return None, near, why, near_far

    def report(self) -> list[dict[str, Any]]:
        """Every mouth for the page: where it is, which way it looks, what is
        behind it, and whether it is docked -- or near and why not. This is what
        the indicator on the device is drawn from."""
        out = []
        for port in self.ports:
            if not port.settled():
                continue
            docked, near, why, far = self.pair_of(port)
            holder = self.holder_for(port) if self.holder_for is not None else None
            row = port.reading()
            row["docked"] = docked.name if docked is not None else None
            if docked is None and near is not None and far <= NEAR_M:
                row["near"] = near.name
                row["why"] = why
            if holder is not None:
                row["holds_kg"] = {k: round(v, 3) for k, v in holder.holds().items()}
            out.append(row)
        return out


def holders_over(goods: Any, routine_for: Callable[[str], Any]) -> Callable[[Port], Any]:
    """What is behind each mouth, over a room's goods ledger and a way to get a
    machine's routine by name: the one answer the server and the room builders
    both use, so a dock means the same thing wherever it is run. A port that
    names a heap the room has not got has nothing behind it, and whoever tries
    to use it is told so."""
    def holder(port: Port) -> Any:
        if port.holds_name == HOPPER:
            routine = routine_for(port.machine)
            return Load(routine) if routine is not None and routine.carries() else None
        pile = goods.by_name(port.holds_name) if goods is not None else None
        return Heap(goods, pile) if pile is not None else None
    return holder


def pass_goods(ports: Ports, giving: Port, taking: Port, kg_most: float | None = None) -> dict[str, Any]:
    """What one mouth passes to another, once they are paired: whatever the
    giver holds that it gives and the taker takes, as much as the taker has room
    for. Booked out of one holder and into the other in the one call -- nothing
    is in flight, because nothing travels (see "What is NOT modelled" above)."""
    if ports.holder_for is None:
        raise ValueError("nothing is behind these mouths to move anything between")
    out_holder, in_holder = ports.holder_for(giving), ports.holder_for(taking)
    if out_holder is None:
        raise ValueError(f"{giving.name} has no {giving.holds_name} behind it")
    if in_holder is None:
        raise ValueError(f"{taking.name} has no {taking.holds_name} behind it")
    have = out_holder.holds()
    if not have:
        return {"moved": {}, "why": f"{giving.name} has nothing behind it"}
    can = [s for s in sorted(have) if giving.passes(s) and taking.passes(s)]
    if not can:
        return {"moved": {}, "why": f"{taking.name} does not take " + ", ".join(sorted(have))}
    room = in_holder.room_kg()
    if kg_most is not None:
        room = min(room, float(kg_most))
    if room <= 1e-6:
        return {"moved": {}, "why": f"{taking.name} is full"}
    moved: dict[str, float] = {}
    for substance in can:
        if room <= 1e-6:
            break
        took = out_holder.take(substance, min(have[substance], room))
        for k, v in took.items():
            if v <= 0.0:
                continue
            moved[k] = moved.get(k, 0.0) + v
            room -= v
    if not moved:
        return {"moved": {}, "why": f"{giving.name} gave nothing"}
    in_holder.give(moved)
    return {"moved": moved, "into": in_holder.what, "out_of": out_holder.what, "why": ""}
