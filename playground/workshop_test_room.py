"""The Workshop's test room: a little world, with the world's own physics.

The owner: *"the test environment should have ground and gravity and operate the
same as the real world. It can also have the sun positioned in the sky or
nighttime and data about power loading in a battery via solar, and so forth.
Make sure it is all built out such that when we then put the product in the real
world it operates the same way."*

The bench used to answer "does it work?" with a static-load rig: the design's
cells floating in an empty spec with a weight set on top -- no ground, no sky,
nothing for it to stand on or drive over. A machine cannot be tested that way at
all, and nothing about the answer carried to the world.

So a test room here is a **room**, of the same shape a world room is: flat
ground of real soil, gravity, a sky with the sun somewhere in it (or below it),
and whatever else you want to stand there. Testing a thing is **installing** it
into that room -- through `workshop_install`, the same call the world uses, so
the same compiler draws it, the same placement seats it on the ground, and the
same machine declarations wire up its battery, its motors and its program. There
is no second physics and no second way of making a thing. What it does here is
what it does there, because it is the same code doing it.

What is different is only what a bench should be: the room is small, it is
thrown away when you are done, and nothing in it is stepped until you say so.

Four ways of trying a thing, and they are all the same room. A weight set on
it, a drop, a slide, a blow from a thrown block -- each is the room's spec
adjusted once after the thing is made and the room opened again from it. There
is no separate drop rig and no separate load rig, because a rig with no ground
under it cannot answer the question anyone is asking.
"""
from __future__ import annotations

from copy import deepcopy
import math
from pathlib import Path
import tempfile
from types import SimpleNamespace
from typing import Any

import inventory
import live_session
import precise_rigid
import rigid_assembly
import room_store
import workshop_install as install
import workshop_recording
import world_room

SCHEMA = "banjo.workshop-test-room.v1"

#: The ground's surface. Flat ground stands at the depth of its soil, not at
#: zero, and a thing set down at zero is buried in it.
GROUND_M = 0.4
#: The cell the bench checks at (workshop_chat), so a thing checked there is
#: drawn the same way here.
CELL_M = 0.04
#: The world page's own step.
DT = 1 / 240
#: Noon over a clear day, which is what a panel is rated against.
NOON = {"elevation_deg": 60.0, "azimuth_deg": 180.0, "irradiance_w_m2": 1000.0}
#: How far across the ground reaches (terrain 64 cells of 0.25 m), which is also
#: how big the slab a watcher sees under everything is.
GROUND_ACROSS_M = 16.0
#: Iron, for a weight and for a thrown block. Both are made of it because it is
#: dense: 50 kg of iron is a 185 mm cube, and 50 kg of oak is a 400 mm one that
#: would not fit on most things you would want to put it on.
IRON_KG_M3 = 7870.0
#: What a bench will do to a thing. Past these it is not a bench test.
MAX_LOAD_KG = 2000.0
MAX_DROP_M = 5.0
MAX_SPEED_M_S = 30.0
MAX_STRIKER_KG = 500.0
#: How far above the thing a weight is let go when you do not say. It has to be
#: clear of it -- two bodies started overlapping are a shove, not a load -- and
#: it has to be as small as that allows, because whatever it falls through it
#: arrives with. Say `from_m` and it is a thing DROPPED on it instead.
WEIGHT_GAP_M = 0.001
#: Turned further than this from how it was put down, a thing is not standing
#: any more. Two right angles would be upside down; half of one is already over.
FELL_OVER_DEG = 45.0
#: A break is worked out between steps and the engine can ask for several in a
#: row. More than this in one step is a runaway, not a result.
MAX_BREAKS_A_STEP = 64
#: How many things you may do to a machine in one run of the bench.
MAX_ORDERS = 24


def _box(name, material, size_m, at_m, anchored=False, shape="box"):
    return {"name": name, "shape": shape, "material": material, "anchored": bool(anchored),
            "size_mm": [round(v * 1000.0, 3) for v in size_m],
            "center_mm": [round(v * 1000.0, 3) for v in at_m]}


def _stool(name, at):
    """A stool: a 450 mm oak seat on four legs, its top 450 mm up, standing free."""
    parts = [{"name": "seat", "dimensions_m": [0.45, 0.04, 0.45], "center_local_m": [0.0, 0.43, 0.0]}]
    for i, (sx, sz) in enumerate(((1, 1), (1, -1), (-1, 1), (-1, -1))):
        parts.append({"name": f"leg {i}", "dimensions_m": [0.05, 0.41, 0.05],
                      "center_local_m": [sx * 0.18, 0.205, sz * 0.18]})
    body = {"name": name, "material": "oak", "position_m": [at[0], 0.0, at[1]],
            "_centre_m": [0.0, 0.35, 0.0], "parts": parts}
    one = rigid_assembly.placed({"bodies": [body], "joints": []}, [at[0], 0.0, at[1]])
    lift = GROUND_M + max(-low for low, _, _ in rigid_assembly.footprint(one))
    one = rigid_assembly.placed({"bodies": [deepcopy(body)], "joints": []}, [at[0], lift, at[1]])
    return {"precise_rigid_bodies": rigid_assembly.scene_bodies(one)}


#: What you can stand in the room beside the thing being tested. A person picks
#: from these by name, and so can the model: they are the things a product is
#: usually tested against -- something to sit on, something to push, something
#: to hit, something that will not move.
THINGS = {
    "stool": ("something to sit on: a 450 mm oak seat on four legs", _stool),
    "plank": ("an oak plank lying on the ground, 1.2 m by 200 mm",
              lambda name, at: {"bodies": [_box(name, "oak", (0.2, 0.05, 1.2),
                                                (at[0], GROUND_M + 0.025, at[1]))]}),
    "ball": ("a 200 mm iron ball",
             lambda name, at: {"bodies": [_box(name, "iron", (0.2, 0.2, 0.2),
                                               (at[0], GROUND_M + 0.1, at[1]), shape="sphere")]}),
    "post": ("a concrete post standing in the ground, 150 mm square and 900 mm tall",
             lambda name, at: {"bodies": [_box(name, "concrete", (0.15, 0.9, 0.15),
                                               (at[0], GROUND_M + 0.45, at[1]), anchored=True)]}),
}


#: What a thing written into the room may be made of. Four, because a tilted
#: thing has to be an exact body and an exact body takes only these; keeping the
#: list the same either way means a ramp and a block can be the same material.
AUTHORED_MATERIALS = ("oak", "iron", "concrete", "glass")
#: How many things may be written into one room, and how big each may be.
MAX_AUTHORED = 12
MIN_AUTHORED_M = 0.01
MAX_AUTHORED_M = 6.0
AUTHORED_SHAPES = ("box", "sphere", "cylinder")


def _turned(tilt_deg: Any) -> list[float]:
    """A quaternion from degrees about x, y and z, applied z first.

    The same order the engine builds rotation_deg in (Rx . Ry . Rz), so a thing
    written here and a thing written in a room spec tilt the same way.
    """
    if not tilt_deg:
        return [1.0, 0.0, 0.0, 0.0]
    if not isinstance(tilt_deg, (list, tuple)) or len(tilt_deg) != 3:
        raise ValueError("tilt_deg is three numbers: degrees about x, y and z")
    out = [1.0, 0.0, 0.0, 0.0]
    for axis, degrees in reversed(list(enumerate(tilt_deg))):
        half = math.radians(float(degrees)) / 2.0
        turn = [math.cos(half), 0.0, 0.0, 0.0]
        turn[axis + 1] = math.sin(half)
        w1, x1, y1, z1 = turn
        w2, x2, y2, z2 = out
        out = [w1*w2 - x1*x2 - y1*y2 - z1*z2,
               w1*x2 + x1*w2 + y1*z2 - z1*y2,
               w1*y2 - x1*z2 + y1*w2 + z1*x2,
               w1*z2 + x1*y2 - y1*x2 + z1*w2]
    length = math.sqrt(sum(v * v for v in out)) or 1.0
    return [v / length for v in out]


def written(thing: Any, index: int) -> tuple[str, dict[str, Any]]:
    """One thing the model wrote, as a body the room will take.

    The vocabulary is what somebody would say out loud: what it is made of, how
    big, where, which way up, how fast it is already going, and whether it is
    driven into the ground. Height is measured FROM THE GROUND, because flat
    ground stands at the depth of its soil and 0.4 is not a number anyone
    should have to know.

    Anything tilted is an exact body, because a lattice body is a box on the
    cell grid and cannot be turned. Everything else is cells, which is what the
    rest of the room is made of.
    """
    if not isinstance(thing, dict):
        raise ValueError("each thing written into the room is an object")
    unknown = set(thing) - {"name", "shape", "material", "size_m", "at_m", "tilt_deg",
                            "moving_m_s", "fixed"}
    if unknown:
        raise ValueError(f"a thing in the room has no {sorted(unknown)}; it has "
                         "name, shape, material, size_m, at_m, tilt_deg, moving_m_s, fixed")
    name = " ".join(str(thing.get("name") or f"thing {index + 1}").split())[:80]
    shape = str(thing.get("shape") or "box")
    if shape not in AUTHORED_SHAPES:
        raise ValueError(f"shape is one of {list(AUTHORED_SHAPES)}")
    material = str(thing.get("material") or "oak")
    if material not in AUTHORED_MATERIALS:
        raise ValueError(f"a thing written into the room is made of one of {list(AUTHORED_MATERIALS)}")
    size = thing.get("size_m")
    if not isinstance(size, (list, tuple)) or len(size) != 3:
        raise ValueError(f"{name}: size_m is three numbers in metres")
    size = [float(v) for v in size]
    if not all(MIN_AUTHORED_M <= v <= MAX_AUTHORED_M for v in size):
        raise ValueError(f"{name}: every side is {MIN_AUTHORED_M * 1000:.0f} mm to "
                         f"{MAX_AUTHORED_M:g} m; you asked for {size}")
    if shape == "sphere" and (max(size) - min(size)) > 1e-9:
        raise ValueError(f"{name}: a sphere is the same across every way")
    if shape == "cylinder" and abs(size[0] - size[2]) > 1e-9:
        raise ValueError(f"{name}: a cylinder is [across, along, across] about its own y")
    at = thing.get("at_m")
    if not isinstance(at, (list, tuple)) or len(at) != 3:
        raise ValueError(f"{name}: at_m is [x, height above the ground, z] in metres")
    at = [float(v) for v in at]
    if at[1] < 0.0:
        raise ValueError(f"{name}: at_m's middle number is the height ABOVE the ground, "
                         "so it cannot be negative")
    if max(abs(at[0]), abs(at[2])) > GROUND_ACROSS_M / 2.0 - 0.5:
        raise ValueError(f"{name}: the ground is {GROUND_ACROSS_M:g} m across, so it has to "
                         f"stand within {GROUND_ACROSS_M / 2.0 - 0.5:g} m of the middle")
    centre = [at[0], GROUND_M + at[1], at[2]]
    speed = thing.get("moving_m_s") or [0.0, 0.0, 0.0]
    if not isinstance(speed, (list, tuple)) or len(speed) != 3:
        raise ValueError(f"{name}: moving_m_s is three numbers in metres a second")
    speed = [float(v) for v in speed]
    if max(abs(v) for v in speed) > MAX_SPEED_M_S:
        raise ValueError(f"{name}: a bench starts a thing at up to {MAX_SPEED_M_S:g} m/s")
    fixed = bool(thing.get("fixed"))
    tilt = thing.get("tilt_deg")
    if tilt or shape == "cylinder":
        if fixed:
            raise ValueError(f"{name}: an exact body cannot be driven into the ground; "
                             "leave the tilt off to fix it, or let it rest where it lands")
        body = {"name": name, "material": material,
                "position_m": [round(v, 6) for v in centre],
                "orientation_wxyz": _turned(tilt),
                "velocity_m_s": speed,
                "parts": [{"name": name, "dimensions_m": size, "center_local_m": [0.0, 0.0, 0.0],
                           **({"shape": "cylinder"} if shape == "cylinder" else {})}]}
        return ("precise_rigid_bodies", body)
    body = _box(name, material, size, centre, anchored=fixed,
                shape="sphere" if shape == "sphere" else "box")
    if any(speed):
        body["velocity_m_s"] = speed
    return ("bodies", body)


def things() -> list[dict[str, str]]:
    """What can be put in the room, for a person or the model to choose from."""
    return [{"what": name, "says": says} for name, (says, _) in sorted(THINGS.items())]


def spec(*, sun: Any = None, day: Any = None, items: Any = (), add: Any = ()) -> dict[str, Any]:
    """A little room: flat ground of real soil, gravity, a sky, and what you put in it.

    `sun` puts it at a fixed place -- elevation, azimuth and irradiance -- and
    `day` gives it a day it crosses, so a machine can be tested at four in the
    afternoon or in the dark. Neither, and it is noon on a clear day, which is
    what a panel is rated against. `day` with an hour after sunset IS the night:
    nothing charges, and a machine that rests until morning will.
    """
    room: dict[str, Any] = {
        "algorithm": "lattice", "cell_m": CELL_M, "plasticity": "on",
        "terrain": {"generate": {"kind": "flat", "nx": 64, "nz": 64, "cell_m": 0.25,
                                 "soil_m": GROUND_M, "sand_m": 0.0}},
        # Every room of exact bodies needs one thing made of cells to size
        # itself by, and it is kept well out of the way.
        "bodies": [_box("marker", "concrete", (0.15, 0.15, 0.15), (7.0, GROUND_M + 0.075, -7.0), anchored=True)],
        "precise_rigid_bodies": [], "joints": [],
    }
    if day:
        room["sun"] = {"day_s": float(day.get("day_s", 240.0)),
                       "noon_elevation_deg": float(day.get("noon_elevation_deg", 60.0)),
                       "hour": float(day.get("hour", 12.0)),
                       "irradiance_w_m2": float(day.get("irradiance_w_m2", 1000.0))}
    else:
        room["sun"] = dict(sun or NOON)
    add = list(add or ())
    if len(add) > MAX_AUTHORED:
        raise ValueError(f"a room takes up to {MAX_AUTHORED} things written into it")
    seen = {"marker"}
    for i, thing in enumerate(add):
        where, body = written(thing, i)
        if body["name"] in seen:
            raise ValueError(f"two things in the room are both called {body['name']!r}")
        seen.add(body["name"])
        room.setdefault(where, []).append(body)
    for i, item in enumerate(items or ()):
        what = str(item.get("what") or "")
        if what not in THINGS:
            raise ValueError(f"nothing here is a {what!r}; the room can hold "
                             + ", ".join(sorted(THINGS)))
        at = item.get("at_m") or (0.0, 1.5)
        made = THINGS[what][1](str(item.get("name") or what), (float(at[0]), float(at[1])))
        for field, extra in made.items():
            room[field] = (room.get(field) or []) + extra
    return room


def _named(spec: dict[str, Any]) -> dict[str, tuple[str, dict[str, Any]]]:
    """Every body in the room by name, and which list it came out of."""
    out = {}
    for where in ("bodies", "precise_rigid_bodies"):
        for body in spec.get(where) or ():
            out[str(body.get("name") or "")] = (where, body)
    return out


def _body_box(where: str, body: dict[str, Any]):
    """A body's world box, exactly: (low xyz, high xyz).

    A lattice body is the box it declares. An exact compound is the box of its
    actual turned parts, which is not its centre of mass with the widest part
    around it -- a mace is mostly handle.
    """
    if where == "precise_rigid_bodies":
        return precise_rigid.bounds(body["parts"], body["position_m"],
                                    body.get("orientation_wxyz") or [1.0, 0.0, 0.0, 0.0])
    centre = [v / 1000.0 for v in body["center_mm"]]
    half = [v / 2000.0 for v in body["size_mm"]]
    return ([c - h for c, h in zip(centre, half)], [c + h for c, h in zip(centre, half)])


def _part_box(where: str, body: dict[str, Any], part_name: str):
    """The box of one named part of a body, or None if it has no such part."""
    if where != "precise_rigid_bodies":
        return None
    wanted = part_name.strip().lower()
    parts = [p for p in body["parts"] if str(p.get("name") or "").strip().lower() == wanted]
    if not parts:
        return None
    return precise_rigid.bounds(parts, body["position_m"],
                                body.get("orientation_wxyz") or [1.0, 0.0, 0.0, 0.0])


def _spanning(boxes) -> tuple[list[float], list[float]]:
    boxes = list(boxes)
    if not boxes:
        raise ValueError("nothing was made, so there is nothing to test")
    lo = [min(b[0][a] for b in boxes) for a in range(3)]
    hi = [max(b[1][a] for b in boxes) for a in range(3)]
    return lo, hi


def _iron_cube_m(mass_kg: float) -> float:
    return (float(mass_kg) / IRON_KG_M3) ** (1.0 / 3.0)


def _weight(name: str, mass_kg: float, over, gap_m: float, exact: bool) -> tuple[str, dict[str, Any]]:
    """An iron block of that mass, hanging just over the middle of `over`.

    It is a body, not a force: it falls the last millimetre onto the thing and
    then presses on it with its own weight through real contact, which is what a
    weight does. A declared downward force would hold steady through a collapse.
    """
    side = _iron_cube_m(mass_kg)
    lo, hi = over
    at = [(lo[0] + hi[0]) / 2.0, hi[1] + gap_m + side / 2.0, (lo[2] + hi[2]) / 2.0]
    if exact:
        return ("precise_rigid_bodies",
                {"name": name, "material": "iron", "position_m": [round(v, 6) for v in at],
                 "orientation_wxyz": [1.0, 0.0, 0.0, 0.0],
                 "parts": [{"name": "weight", "dimensions_m": [side, side, side],
                            "center_local_m": [0.0, 0.0, 0.0]}]})
    return ("bodies", _box(name, "iron", (side, side, side), at))


def _striker(name: str, mass_kg: float, speed_m_s: float, at_box, fraction: float,
             exact: bool) -> tuple[str, dict[str, Any]]:
    """An iron block thrown at the thing along +X, level with where you aimed.

    `fraction` is 0 at its feet and 1 at its top. It starts one of its own
    widths clear of the thing so that the first thing it touches is the thing.
    """
    side = _iron_cube_m(mass_kg)
    lo, hi = at_box
    y = lo[1] + max(0.0, min(1.0, fraction)) * (hi[1] - lo[1])
    y = max(GROUND_M + side / 2.0, min(y, hi[1]))
    at = [lo[0] - side, y, (lo[2] + hi[2]) / 2.0]
    speed = [float(speed_m_s), 0.0, 0.0]
    if exact:
        return ("precise_rigid_bodies",
                {"name": name, "material": "iron", "position_m": [round(v, 6) for v in at],
                 "orientation_wxyz": [1.0, 0.0, 0.0, 0.0], "velocity_m_s": speed,
                 "parts": [{"name": "striker", "dimensions_m": [side, side, side],
                            "center_local_m": [0.0, 0.0, 0.0]}]})
    return ("bodies", dict(_box(name, "iron", (side, side, side), at), velocity_m_s=speed))


#: The name of the cell-sized block every room of exact bodies needs to size
#: itself by. It stands 7 m out of the way and nothing can reach it; it is the
#: compiler's bookkeeping, not part of anybody's test, so a recording leaves it
#: out. Drawn, it would put the view 10 m back and make the thing a speck.
MARKER = "marker"


def _worth_watching(body: dict[str, Any]) -> bool:
    return str(body.get("name") or "") != MARKER


def _geometry(poses: dict[str, Any], cell_m: float) -> dict[str, Any]:
    """What each body actually looks like, from the engine rather than from us.

    A `poses` reply always carries geometry: a lattice body's own cells, and an
    exact compound's parts about its centre of mass. Keyed by name and revision,
    so a piece that breaks and is rebuilt is redrawn as the cells it now has.
    """
    out: dict[str, Any] = {}
    for body in poses.get("bodies") or ():
        name, revision = str(body.get("name") or ""), int(body.get("revision") or 0)
        if body.get("cells_local_m"):
            out[f"{name}#{revision}"] = {"revision": revision, "cell_size_m": cell_m,
                                         "offsets_m": body["cells_local_m"]}
        elif body.get("rigid_parts_local"):
            out[f"{name}#{revision}"] = {"revision": revision, "parts": body["rigid_parts_local"]}
    return out


def _turn_deg(a, b) -> float:
    """How far one orientation is from another, in degrees.

    Engine replies round to five decimals, so a quaternion that came back is not
    quite a unit one; normalising first is the difference between a still thing
    reading 0 degrees and reading half of one.
    """
    def unit(q):
        n = math.sqrt(sum(v * v for v in q)) or 1.0
        return [v / n for v in q]
    dot = abs(sum(x * y for x, y in zip(unit(a), unit(b))))
    return math.degrees(2.0 * math.acos(max(-1.0, min(1.0, dot))))


class Bench:
    """A room at the bench, open and stopped, with the thing in it.

    Nothing is stepped until `run` is called: time is frozen, which is what a
    bench is for.
    """

    def __init__(self, app: Any, *, sun: Any = None, day: Any = None, items: Any = (),
                 add: Any = ()):
        self._held = tempfile.TemporaryDirectory()
        root = Path(self._held.name)
        self.live = live_session.Live()
        self.room = world_room.Room("bench-test")
        self.room.spec = spec(sun=sun, day=day, items=items, add=add)
        self.room.inventory = inventory.Inventory()
        self.app = SimpleNamespace(live=self.live, live_holder="world", room=self.room,
                                   engine_path=getattr(app, "engine_path"),
                                   runs_path=root / "runs", store=room_store.RoomStore(root / "rooms"),
                                   workshop_owner_id=getattr(app, "workshop_owner_id", "owner"))
        # Trying a thing costs nothing. The room keeps a rack of its own, thrown
        # away with the room, because a person must be able to find out whether
        # a design works before they have the material to make it -- being
        # refused a test for want of stock is backwards. Making it in the WORLD
        # spends the world's rack, and that gate is untouched.
        import workshop_library
        for material in workshop_library.MATERIALS if hasattr(workshop_library, "MATERIALS") else (
                "oak", "iron", "concrete", "glass", "aluminum", "rubber", "ice", "alumina ceramic"):
            try:
                workshop_library.set_rack(self.app, material, 1000.0)
            except Exception:       # a material this build does not carry
                pass
        self.live.open(self.app, {"spec": self.room.spec})
        self.t_s = 0.0
        self.made: dict[str, Any] | None = None
        #: The names the room had before anything was made in it, so that what
        #: was made can be told from the scenery without trusting a receipt.
        self.was_here = set(_named(self.room.spec))
        self.its_bodies: list[str] = []
        #: Every failure run the engine asked for, and what became of the body
        #: it was asked about. `broke` and `dented` are the ones that are news.
        self.failures: list[dict[str, Any]] = []
        self.recorder: Any = None
        self.geometry: dict[str, Any] = {}
        self.at_the_start: dict[str, list[float]] = {}
        #: How many orders have been given, which is the sender's count the
        #: engine uses to ignore one that arrives out of order.
        self._orders = 0
        #: What was done to it and when, for the record.
        self.worked: list[dict[str, Any]] = []

    def close(self) -> None:
        try:
            self.live.shutdown()
        finally:
            self._held.cleanup()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
        return False

    def make(self, candidate: dict[str, Any], *, at_m=(0.0, 0.0)) -> dict[str, Any]:
        """Make the thing in the room -- the same call the world makes it with.

        Not a copy of the installer and not a simplified one: `workshop_install`
        itself, so the design is compiled by whichever compiler the world would
        choose, seated on the ground the way the world seats it, and its battery,
        motors and program declared the way the world declares them. That is the
        whole reason this answers for the world.
        """
        ctx = install.context(self.app, {})
        preview = install.preview(self.app, {"session": ctx["session"], "scene": self.room.scene,
                                             "mode": "authoring", "position_m": list(at_m),
                                             "candidate": candidate})
        self.made = install.commit(self.app, {"scene": self.room.scene, "session": ctx["session"],
                                              "preview_id": preview["preview_id"],
                                              "request_id": "bench-test-" + preview["preview_id"][:8]})
        # What the install put there, told from the room rather than from the
        # receipt: a receipt names the roots, and a design compiled into a group
        # of cells has bodies under those roots that must move with them.
        self.its_bodies = [n for n in _named(self.room.spec) if n not in self.was_here]
        return self.made

    def its_box(self, part: str = "") -> tuple[list[float], list[float]]:
        """The box the made thing stands in, or the box of one part of it."""
        here = _named(self.room.spec)
        mine = [here[n] for n in self.its_bodies if n in here]
        if part:
            only = [box for box in (_part_box(w, b, part) for w, b in mine) if box]
            if only:
                return _spanning(only)
        return _spanning(_body_box(w, b) for w, b in mine)

    def is_exact(self) -> bool:
        """Whether what was made is exact bodies rather than cells."""
        here = _named(self.room.spec)
        return any(here[n][0] == "precise_rigid_bodies" for n in self.its_bodies if n in here)

    def set_up(self, *, load_kg: float = 0.0, on: str = "top", from_m: float = 0.0,
               drop_m: float = 0.0, slide_m_s: float = 0.0, strike: Any = None) -> dict[str, Any]:
        """Do to the thing what the test says, and open the room again on it.

        Everything a bench does to a thing is a change to where it starts, how
        fast it starts, or what else is in the room with it -- so all of it is
        one edit of the room's own spec followed by one fresh open. The thing is
        already made by then and is carried in the spec as the compiler drew it,
        so nothing here is a second way of building anything.
        """
        if not self.its_bodies:
            raise ValueError("make something before setting a test up on it")
        did: dict[str, Any] = {}
        beside = [n for n in _named(self.room.spec) if n not in self.its_bodies and n != MARKER]
        if beside:
            did["written"] = ", ".join(sorted(beside))
        spec_now = deepcopy(self.room.spec)
        here = _named(spec_now)
        exact = self.is_exact()

        drop_m = float(drop_m or 0.0)
        if not 0.0 <= drop_m <= MAX_DROP_M:
            raise ValueError(f"a bench drops a thing from 0 to {MAX_DROP_M:g} m")
        slide_m_s = float(slide_m_s or 0.0)
        if abs(slide_m_s) > MAX_SPEED_M_S:
            raise ValueError(f"a bench slides a thing at up to {MAX_SPEED_M_S:g} m/s")
        for name in self.its_bodies:
            where, body = here[name]
            if drop_m:
                if where == "precise_rigid_bodies":
                    body["position_m"] = [body["position_m"][0], body["position_m"][1] + drop_m,
                                          body["position_m"][2]]
                else:
                    body["center_mm"] = [body["center_mm"][0], body["center_mm"][1] + drop_m * 1000.0,
                                         body["center_mm"][2]]
            if slide_m_s:
                body["velocity_m_s"] = [slide_m_s, 0.0, 0.0]
        if drop_m:
            did["drop_m"] = drop_m
        if slide_m_s:
            did["slide_m_s"] = slide_m_s

        load_kg = float(load_kg or 0.0)
        from_m = float(from_m or 0.0)
        if not 0.0 <= from_m <= MAX_DROP_M:
            raise ValueError(f"a bench drops a thing on it from 0 to {MAX_DROP_M:g} m")
        if load_kg:
            if not 0.0 < load_kg <= MAX_LOAD_KG:
                raise ValueError(f"a bench sets up to {MAX_LOAD_KG:g} kg on a thing")
            over = self.its_box(str(on or "").strip())
            # Set ON it, or DROPPED on it. There was no way to drop a thing onto
            # a thing at all: the only body that arrived with any speed was the
            # thrown block, which flies sideways, so "drop a 20 kg iron block on
            # it" came out as a 20 kg block thrown at its side.
            where, weight = _weight("the weight", load_kg, over, from_m or WEIGHT_GAP_M, exact)
            spec_now.setdefault(where, []).append(weight)
            did["load_kg"] = load_kg
            did["on"] = str(on or "top")
            did["weight_side_m"] = round(_iron_cube_m(load_kg), 4)
            if from_m:
                did["dropped_on_from_m"] = from_m

        if strike:
            how = strike if isinstance(strike, dict) else {}
            kg = float(how.get("kg", how.get("striker_kg", 5.0)))
            speed = float(how.get("speed_m_s", 8.0))
            fraction = float(how.get("height_fraction", 1.0))
            if not 0.0 < kg <= MAX_STRIKER_KG:
                raise ValueError(f"a bench throws up to {MAX_STRIKER_KG:g} kg at a thing")
            if not 0.0 < speed <= MAX_SPEED_M_S:
                raise ValueError(f"a bench throws it at up to {MAX_SPEED_M_S:g} m/s")
            where, block = _striker("the striker", kg, speed, self.its_box(), fraction, exact)
            spec_now.setdefault(where, []).append(block)
            did["strike"] = {"kg": kg, "speed_m_s": speed, "height_fraction": fraction}

        if did:
            # Opened again from the changed spec, not carried: a carry would put
            # the thing back exactly where the saved world left it, which is the
            # one thing a drop, a slide or a weight must not do.
            self.live.open(self.app, {"spec": spec_now})
            self.room.spec = spec_now
            self.t_s = 0.0
        return did

    def watch(self) -> None:
        """Record what happens from here, so it can be played back afterwards.

        A transparent wrapper round the session: the engine gets the same calls
        and gives the same answers, and the poses go into a timeline on the way
        past. Called after the thing is made, because installing replaces the
        session underneath it.
        """
        self.geometry = _geometry(self.live.session.send(op="poses"), float(self.room.spec["cell_m"]))
        self.recorder = workshop_recording.wrap(self.live.session)
        self.live.session = self.recorder

    def playback(self, *, test: str = "try_in_a_room") -> dict[str, Any] | None:
        """The timeline, with the ground in every frame and each body's shape."""
        if self.recorder is None or len(self.recorder.frames) < 2:
            return None
        out = self.recorder.recording(test=test)
        for frame in out["frames"]:
            frame["bodies"] = [b for b in frame["bodies"] if _worth_watching(b)]
        out["geometry"] = {k: v for k, v in self.geometry.items() if not k.startswith(MARKER + "#")}
        # Where the ground's surface is, for whoever draws the floor. Flat
        # terrain is 16 m of soil this deep; a slab that size drawn in the view
        # would put everything standing on it out of shot, so the page puts its
        # own floor at this height instead.
        out["ground_m"] = GROUND_M
        out["ground_across_m"] = GROUND_ACROSS_M
        # Every body is drawn as the engine's own shape for it: its cells where
        # it is made of cells, its exact parts where it is exact, and its
        # declared box where it is a box. Nothing here is a stand-in hull.
        out["geometry_basis"] = "recorded-native-shapes"
        out["fractures"] = list(self.failures)
        return out

    def broke(self) -> list[dict[str, Any]]:
        """The runs where the thing asked about actually came apart."""
        return [f for f in self.failures if f["outcome"] == "broke"]

    def dented(self) -> list[dict[str, Any]]:
        """The runs where it took a permanent set and stayed in one piece."""
        return [f for f in self.failures if f["outcome"] == "dented"]

    def remember_poses(self) -> None:
        """Where everything was pointing when the run began."""
        self.at_the_start = {b["name"]: list(b.get("orientation_wxyz") or [1.0, 0.0, 0.0, 0.0])
                             for b in self.live.session.send(op="poses").get("bodies") or ()}

    def works(self) -> dict[str, Any]:
        """Every control the made thing has, by name."""
        return {str(c["name"]): c for c in (self.reading()["controls"] or [])}

    def work(self, control: str, *, power: bool = True, direction: int = 1,
             setting: float = 1.0) -> dict[str, Any]:
        """Do to a control what a person does to it from its panel.

        The world has On/Off, a direction and a drive setting for every control
        on a machine; the bench had none of it, so a machine could be built here
        and never worked until it was out there. This is the same `operate` the
        world's own panel sends.
        """
        here = self.works()
        which = here.get(control)
        if which is None:
            raise ValueError(f"nothing here has a control called {control!r}; it has "
                             + (", ".join(sorted(here)) or "none"))
        if direction not in (-1, 0, 1):
            raise ValueError("a direction is -1, 0 or 1")
        setting = float(setting)
        if not 0.0 <= setting <= 1.0:
            raise ValueError("a drive setting is 0 to 1")
        self._orders += 1
        answer = self.live.session.send(op="operate", control=which["id"], sender="bench",
                                        seq=self._orders, power=bool(power),
                                        direction=int(direction), setting=setting)
        return answer.get("control") or {}

    def turn_on(self, name: str | None = None, *, power: bool = True) -> dict[str, Any]:
        """Set the thing's program running, as a person does from its panel."""
        said = self.reading()
        programs = said["programs"]
        if not programs:
            raise ValueError("nothing here has a program to turn on")
        which = next((p for p in programs if p["name"] == name), None) if name else programs[0]
        if which is None:
            raise ValueError(f"nothing here has a program called {name!r}")
        answer = self.live.session.send(op="run", program=which["id"], sender="bench",
                                        seq=int(self.t_s * 1000) + 1, power=bool(power))
        return answer.get("program") or {}

    def run(self, seconds: float, orders: Any = ()) -> dict[str, Any]:
        """Let the room run, a quarter of a second at a time, breaking what breaks.

        The engine does not break a thing behind your back: a step that has
        overloaded something comes back with it named in `breakable`, and the
        break is a separate call, because working out how a thing comes apart
        costs more than a step does. A test that never made that call would have
        watched a shelf hold up a load it cannot hold.
        """
        # A quarter of a second at a time is fine for a number at the end, but
        # a recording only gets a frame per reply, and four frames a second is
        # not something a person can watch. Recording, it goes a thirtieth of a
        # second at a time, which is what the recorder samples at anyway.
        stride = 8 if self.recorder is not None else 60
        # What to do to it, and when. Sorted, because a list written out of
        # order is a list somebody meant in order.
        waiting = sorted(list(orders or ()), key=lambda o: float(o.get("at_s") or 0.0))
        left = int(round(float(seconds) / DT))
        while left > 0:
            while waiting and float(waiting[0].get("at_s") or 0.0) <= self.t_s + 1e-9:
                order = waiting.pop(0)
                said = self.work(str(order.get("control") or ""),
                                 power=bool(order.get("power", True)),
                                 direction=int(order.get("direction", 1)),
                                 setting=float(order.get("setting", 1.0)))
                self.worked.append({"at_s": round(self.t_s, 3), "control": order.get("control"),
                                    "power": bool(order.get("power", True)),
                                    "direction": int(order.get("direction", 1)),
                                    "setting": float(order.get("setting", 1.0)),
                                    "said": said.get("condition") or ""})
            n = min(stride, left)
            state = self.live.session.send(op="step", dt=DT, n=n)
            self.t_s += n * DT
            left -= n
            asked = 0
            while state.get("breakable"):
                asked += 1
                if asked > MAX_BREAKS_A_STEP:
                    raise RuntimeError("it kept breaking without settling; no result is claimed")
                name = str(state["breakable"][0])
                state = self.live.session.send(op="fracture", name=name, window_s=0.003)
                # Being overloaded is not being broken. The engine names what
                # might give way and the run says what became of it: held,
                # dented, or broke. A count of one cannot tell those apart, so
                # the outcome is what is believed, not the count.
                self.failures.append({"name": name, "at_s": round(float(state.get("t", self.t_s)), 4),
                                      "outcome": str(state.get("outcome") or ""),
                                      "pieces": int(state.get("pieces") or 0)})
            if asked:
                # Whatever broke is different matter from here on, and a piece
                # that held comes back as "piece 1" of itself. Redraw it.
                self.geometry.update(_geometry(self.live.session.send(op="poses"),
                                               float(self.room.spec["cell_m"])))
        if waiting:
            raise ValueError(
                f"{len(waiting)} of what you asked for happens after the run ends: the first is at "
                f"{float(waiting[0].get('at_s') or 0.0):.1f} s and the run is {seconds:g} s long")
        return self.reading()

    def reading(self) -> dict[str, Any]:
        """What the room says now: where everything is, and what its machines read."""
        reply = self.live.session.send(op="step", dt=DT, n=1)
        self.t_s += DT
        machines = reply.get("machines") or {}
        poses = self.live.session.send(op="poses")
        # A sun with a day says where it has got to; a fixed one is only what
        # the room declared, so say that rather than nothing.
        return {"schema": SCHEMA, "t_s": round(self.t_s, 4),
                "sun": poses.get("sun") or reply.get("sun") or dict(self.room.spec.get("sun") or {}),
                # How far a thing has TURNED is the difference between a stool
                # that settled 3 mm and a stool lying on its side, and both of
                # those move about the same distance.
                "bodies": {b["name"]: {"at_m": [round(v, 5) for v in b["position_m"]],
                                       "speed_m_s": round(math.dist(b.get("velocity_m_s") or [0, 0, 0],
                                                                    [0, 0, 0]), 5),
                                       "turn_deg": round(_turn_deg(
                                           b.get("orientation_wxyz") or [1.0, 0.0, 0.0, 0.0],
                                           self.at_the_start.get(b["name"]) or [1.0, 0.0, 0.0, 0.0]), 3)}
                           for b in poses.get("bodies") or []},
                "broke": self.broke(), "dented": self.dented(), "failures": list(self.failures),
                "stores": machines.get("stores") or [],
                "panels": machines.get("panels") or [],
                "controls": machines.get("controls") or [],
                "programs": machines.get("programs") or []}


def try_it(app: Any, candidate: dict[str, Any], *, seconds: float = 10.0, sun: Any = None, day: Any = None,
           items: Any = (), add: Any = (), at_m=(0.0, 0.0), turn_on: bool = True, load_kg: float = 0.0,
           on: str = "top", from_m: float = 0.0, drop_m: float = 0.0, slide_m_s: float = 0.0,
           strike: Any = None, do: Any = (), record: bool = True) -> dict[str, Any]:
    """Make the thing in a little room, do a thing to it, and say what happened.

    One call: open the room, install the design into it the way the world
    installs it, set the test up on it, set any program of its own running, step
    it for `seconds`, and hand back what changed. The room is thrown away
    afterwards; the world is untouched throughout, because none of this is the
    world's session.

    `do` is a list of things to do to the thing's own controls while it runs --
    {"at_s", "control", "power", "direction", "setting"} -- which is what a
    person does at its panel in the world. A machine could be built at this
    bench and never worked until it was out there.

    The test is whichever of these you ask for, and they compose: `load_kg` on
    its `on` (a part's name, or the whole thing), and `from_m` to DROP that
    weight on it from a height rather than set it there; `drop_m` to let the
    THING go from a height; `slide_m_s` to start it moving at; and `strike` to
    throw a block at its side. Ask for none of them and it simply stands there,
    which is its own test.
    """
    seconds = float(seconds)
    if not 0.0 < seconds <= 120.0:
        raise ValueError("a test runs for up to 120 seconds")
    with Bench(app, sun=sun, day=day, items=items, add=add) as room:
        made = room.make(candidate, at_m=at_m)
        did = room.set_up(load_kg=load_kg, on=on, from_m=from_m, drop_m=drop_m,
                          slide_m_s=slide_m_s, strike=strike)
        if record:
            room.watch()
        room.remember_poses()
        began = room.reading()
        turned_on = None
        if turn_on and began["programs"]:
            turned_on = room.turn_on()
        orders = list(do or ())
        if len(orders) > MAX_ORDERS:
            raise ValueError(f"a bench does up to {MAX_ORDERS} things to a machine in one run")
        ended = room.run(seconds, orders)
        deck = made.get("root_body") or ""
        fell = ended["bodies"].get(deck, {}).get("turn_deg", 0.0) >= FELL_OVER_DEG
        answer = {"schema": SCHEMA, "made": {k: made.get(k) for k in
                                             ("root_body", "root_bodies", "mass_kg", "cells", "design_id")},
                  "ran_for_s": round(seconds, 3), "turned_on": bool(turned_on), "did": did,
                  "sky": ended["sun"],
                  "in_the_room": ([t["what"] for t in (items or ())]
                                  + [written(t, i)[1]["name"] for i, t in enumerate(add or ())]),
                  "worked": list(room.worked), "controls": ended["controls"],
                  "broke": room.broke(), "dented": room.dented(),
                  "failures": list(room.failures), "fell_over": bool(fell),
                  "began": began, "ended": ended,
                  "says": _says(made, began, ended, did, room.broke(), room.dented(), fell)}
        if record:
            answer["playback"] = room.playback()
        return answer


def _says(made: dict[str, Any], began: dict[str, Any], ended: dict[str, Any],
          did: dict[str, Any] | None = None, broke: Any = (), dented: Any = (),
          fell: bool = False) -> str:
    """What happened, in a sentence a person reads."""
    said = []
    did = did or {}
    if did.get("drop_m"):
        said.append(f"dropped from {did['drop_m']:.2f} m")
    if did.get("slide_m_s"):
        said.append(f"started sliding at {did['slide_m_s']:.1f} m/s")
    if did.get("load_kg"):
        said.append(f"{did['load_kg']:g} kg dropped on its {did.get('on') or 'top'} "
                    f"from {did['dropped_on_from_m']:.2f} m" if did.get("dropped_on_from_m")
                    else f"{did['load_kg']:g} kg set on its {did.get('on') or 'top'}")
    if did.get("strike"):
        said.append(f"hit by {did['strike']['kg']:g} kg at {did['strike']['speed_m_s']:g} m/s")
    if did.get("written"):
        said.append(f"in a room with {did['written']} in it")
    deck = made.get("root_body")
    body = ended["bodies"].get(deck or "")
    if body:
        was = began["bodies"].get(deck or "", {}).get("at_m") or body["at_m"]
        went = math.dist(body["at_m"], was)
        turned = body.get("turn_deg") or 0.0
        if fell:
            said.append(f"it went over: {turned:.0f} degrees from how it was put down, "
                        f"and it is {body['at_m'][1]:.2f} m up")
        elif went >= 0.01:
            said.append(f"it is {body['at_m'][1]:.2f} m up, has moved {went * 1000:.0f} mm "
                        f"and turned {turned:.1f} degrees")
        else:
            said.append(f"it stands where it was put, {body['at_m'][1]:.2f} m up, "
                        f"having turned {turned:.1f} degrees")
    broke, dented = list(broke or ()), list(dented or ())
    if broke:
        pieces = sum(b["pieces"] for b in broke)
        said.append(f"{len(broke)} of it broke, into {pieces} pieces, the first at {broke[0]['at_s']:.2f} s")
    elif dented:
        said.append(f"nothing broke, but {len(dented)} of it took a permanent dent, "
                    f"the first at {dented[0]['at_s']:.2f} s")
    else:
        said.append("nothing broke")
    for store, before in zip(ended["stores"], began["stores"]):
        change = store["charge_j"] - before["charge_j"]
        said.append(f"{store['name']} went {before['charge_j']:.0f} -> {store['charge_j']:.0f} J"
                    if abs(change) >= 1.0 else f"{store['name']} holds {store['charge_j']:.0f} J still")
    for panel in ended["panels"]:
        said.append(f"{panel['name']} is giving {panel['power_w']:.1f} W")
    for program in ended["programs"]:
        said.append(f"{program['name']} is {program['doing']}: {program['why']}")
    return "; ".join(said) or "nothing in it says anything"
