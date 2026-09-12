"""Banjo from Python, through the C library.

This is the whole binding: ctypes against `banjo.h`, no build step, no compiled
extension, nothing to keep in sync but the ABI version -- which is checked on
load, because a header and a library that disagree will not tell you any other
way.

It exists as much to prove something as to be used: the point of the C face is
that anything able to call a C function can drive a world, and the shortest way
to show that is to drive one from a language that cannot read a C++ header.

    from banjo import World

    with World(scene, cell_size_m=0.02) as world:
        for _ in range(600):
            world.advance(1 / 120)
        for body in world.bodies():
            print(body.name, body.position_m)

`advance` settles whatever wants to break as it goes. `step` does not, and hands
back whether the world is waiting on a decision -- see the note on breaking in
`banjo.h`, because a caller that ignores that answer gets a world frozen at the
instant of the first impact.
"""
from __future__ import annotations

import ctypes
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

# Bumped with the header: the world reports what made it wait.
ABI_VERSION = 9

NOTHING, HELD, DENTED, BROKE = 0, 1, 2, 3
OUTCOMES = {0: "nothing", 1: "held", 2: "dented", 3: "broke"}

OK = 0
BREAK_PENDING = 1
ERROR = -1
BAD_ARGUMENT = -2

SHAPES = {0: "box", 1: "sphere", 2: "hull"}


class BanjoError(RuntimeError):
    """What the engine said, rather than a return code the caller has to look up."""


class _Body(ctypes.Structure):
    _fields_ = [("name", ctypes.c_char_p),
                ("material", ctypes.c_char_p),
                ("position_m", ctypes.c_double * 3),
                ("orientation_wxyz", ctypes.c_double * 4),
                ("velocity_m_s", ctypes.c_double * 3),
                ("dimensions_m", ctypes.c_double * 3),
                ("shape", ctypes.c_int),
                ("anchored", ctypes.c_int),
                ("held", ctypes.c_int),
                ("rgba", ctypes.c_uint)]


class _Delay(ctypes.Structure):
    _fields_ = [("at_s", ctypes.c_double),
                ("object", ctypes.c_char_p),
                ("kind", ctypes.c_char_p),
                ("lead_ms", ctypes.c_double),
                ("cost_ms", ctypes.c_double)]


class _Lot(ctypes.Structure):
    _fields_ = [("material", ctypes.c_char_p),
                ("kilograms", ctypes.c_double),
                ("pieces", ctypes.c_int),
                ("cells", ctypes.c_int)]


# What kind of joint, which is also the unit on its numbers.
JOINT_HINGE = 0
JOINT_SLIDER = 1
JOINT_LINK = 2
JOINT_PULLEY = 3


class _Joint(ctypes.Structure):
    _fields_ = [("id", ctypes.c_uint),
                ("kind", ctypes.c_int),
                ("a", ctypes.c_char_p),
                ("b", ctypes.c_char_p),
                ("at", ctypes.c_double),
                ("lower", ctypes.c_double),
                ("upper", ctypes.c_double),
                ("friction", ctypes.c_double),
                ("at_m", ctypes.c_double * 3),
                ("axis", ctypes.c_double * 3),
                ("attached", ctypes.c_int),
                ("tension_n", ctypes.c_double),
                ("breaks_at_n", ctypes.c_double),
                ("ratio", ctypes.c_double),
                ("over_a_m", ctypes.c_double * 3),
                ("over_b_m", ctypes.c_double * 3)]


class _Pick(ctypes.Structure):
    _fields_ = [("hit", ctypes.c_int),
                ("name", ctypes.c_char_p),
                ("distance_m", ctypes.c_double),
                ("point_m", ctypes.c_double * 3)]


class _Impact(ctypes.Structure):
    _fields_ = [("struck", ctypes.c_char_p),
                ("by", ctypes.c_char_p),
                ("closing_speed_m_s", ctypes.c_double),
                ("threshold_speed_m_s", ctypes.c_double),
                ("dent_speed_m_s", ctypes.c_double),
                ("energy_j", ctypes.c_double),
                ("would_break", ctypes.c_int),
                ("would_dent", ctypes.c_int)]


@dataclass(frozen=True)
class Body:
    """A body as it is right now. A copy, so it survives the next call."""
    name: str
    material: str
    shape: str
    position_m: tuple[float, float, float]
    orientation_wxyz: tuple[float, float, float, float]
    velocity_m_s: tuple[float, float, float]
    dimensions_m: tuple[float, float, float]
    anchored: bool
    held: bool
    rgba: int


@dataclass(frozen=True)
class Impact:
    struck: str
    by: str
    closing_speed_m_s: float
    # The speed below which nothing CAN break. Above it a break is possible,
    # never certain: the bound is deliberately generous, so clearing it is a
    # necessary condition and reading it as a promise reads it backwards.
    threshold_speed_m_s: float
    # The speed below which nothing can take a permanent set. Infinite for a
    # brittle material. Almost always the lower of the two, and the gap is
    # where most real damage lives.
    dent_speed_m_s: float
    energy_j: float
    would_break: bool
    would_dent: bool


@dataclass(frozen=True)
class Delay:
    """A moment the world waited, or was spared waiting."""
    at_s: float
    object: str
    # "blocked"      the caller asked and waited for the whole run
    # "foreseen"     a collision was seen coming (lead_ms is the warning); with
    #                a cost, a run started early and was then used, and lead_ms
    #                is how far out its predicted speed was, as a percentage
    # "guessing"     a run was started for a collision that has not happened yet
    # "guess-missed" what arrived was not what was guessed
    # "guess-wasted" a run started early and was thrown away
    # "queued"       a break arrived mid-run and was captured, not waited for
    # "precomputed"  the answer was ready before it was asked for
    # "held"         the pair was pinned while the answer was worked out
    kind: str
    lead_ms: float
    # What the RUN cost, never what it spent waiting for a worker.
    cost_ms: float


@dataclass(frozen=True)
class Lot:
    """One material's worth of what a sweep picked up.

    Added up by material rather than by shard: nobody wants forty entries called
    "glass plate 20mm piece 31", they want to know they have 400 g of glass.
    """
    material: str
    # The matter that was actually there: a piece's cells are its volume, and
    # volume times the material's density is what has been carried away.
    kilograms: float
    pieces: int
    cells: int


@dataclass(frozen=True)
class Joint:
    """A joint between two named things: a pin they turn about, or a line they
    slide along.

    Two NAMES rather than two bodies, because bodies do not survive breaking:
    everything in an island is destroyed and rebuilt when anything in it comes
    apart. A pin whose wood is smashed follows the piece it ends up inside, so
    `a` and `b` do change -- a gate hung on "post" can find itself hung on
    "post piece 3" -- and `attached` goes False when there is no wood left to
    hold it, which is a gate coming off its hinges.
    """
    id: int
    # "hinge" or "slider". Also the unit on the four numbers below: a pin has
    # turned so many DEGREES and grips in newton metres; a slide has moved so
    # many METRES and grips in newtons.
    kind: str
    a: str
    b: str
    # Where it has got to, from where it was made.
    at: float
    lower: float
    upper: float
    friction: float
    # Where the pin is and which way it runs, worked out from the body it is in
    # rather than remembered -- so a gate carried across the room reports its
    # hinge where the gate is.
    at_m: tuple[float, float, float]
    axis: tuple[float, float, float]
    attached: bool
    # For a link: what it is carrying, and what it takes to part it. Zero
    # tension on a pin or a slide, which have no tension in any useful sense;
    # zero breaking strength means a link that never parts.
    tension_n: float = 0.0
    breaks_at_n: float = 0.0
    # For a pulley: its mechanical advantage, and the two fixed points its rope
    # runs over. 1 and zeroes for every other kind.
    ratio: float = 1.0
    over_a_m: tuple[float, float, float] = (0.0, 0.0, 0.0)
    over_b_m: tuple[float, float, float] = (0.0, 0.0, 0.0)


@dataclass(frozen=True)
class Pick:
    hit: bool
    # Empty when the ray stopped on something that is not one of the scene's
    # bodies -- the ground. Not the same answer as meeting nothing.
    name: str
    distance_m: float
    point_m: tuple[float, float, float]


def _find_library(explicit: str | os.PathLike[str] | None = None) -> Path:
    """The built or installed library, wherever it is.

    Looked for rather than configured, so this file works out of a build tree
    during development and out of an install prefix afterwards without being
    edited in between.
    """
    if explicit:
        return Path(explicit)
    env = os.environ.get("BANJO_LIBRARY")
    if env:
        return Path(env)
    names = ["banjo.dll"] if sys.platform == "win32" else (
        ["libbanjo.dylib"] if sys.platform == "darwin" else ["libbanjo.so"])
    here = Path(__file__).resolve()
    roots = [here.parent, *here.parents]
    for root in roots:
        for where in ("build/integration/Release", "build/integration", "build/Release",
                      "build", "bin", "lib", "."):
            for name in names:
                candidate = root / where / name
                if candidate.is_file():
                    return candidate
    raise BanjoError(
        f"could not find {names[0]}. Build the banjo_c target, install the package, "
        f"or set BANJO_LIBRARY to the library's path.")


_lib: ctypes.CDLL | None = None


def library(path: str | os.PathLike[str] | None = None) -> ctypes.CDLL:
    """Load it once and describe every call, so ctypes stops guessing.

    Without argtypes and restype ctypes assumes int, which silently truncates
    every pointer on a 64-bit build -- the classic way a binding like this
    appears to work and then corrupts memory.
    """
    global _lib
    if _lib is not None and path is None:
        return _lib
    lib = ctypes.CDLL(str(_find_library(path)))

    lib.banjo_abi_version.restype = ctypes.c_int
    lib.banjo_version_string.restype = ctypes.c_char_p
    lib.banjo_last_error.restype = ctypes.c_char_p

    lib.banjo_open.argtypes = [ctypes.c_char_p, ctypes.c_double]
    lib.banjo_open.restype = ctypes.c_void_p
    lib.banjo_close.argtypes = [ctypes.c_void_p]
    lib.banjo_close.restype = None

    lib.banjo_step.argtypes = [ctypes.c_void_p, ctypes.c_double]
    lib.banjo_step.restype = ctypes.c_int
    lib.banjo_advance.argtypes = [ctypes.c_void_p, ctypes.c_double, ctypes.c_double]
    lib.banjo_advance.restype = ctypes.c_int
    lib.banjo_time.argtypes = [ctypes.c_void_p]
    lib.banjo_time.restype = ctypes.c_double

    lib.banjo_breakable_count.argtypes = [ctypes.c_void_p]
    lib.banjo_breakable_count.restype = ctypes.c_int
    lib.banjo_breakable_name.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.banjo_breakable_name.restype = ctypes.c_char_p
    lib.banjo_fracture.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_double]
    lib.banjo_fracture.restype = ctypes.c_int
    lib.banjo_decline_break.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    lib.banjo_begin_fracture.restype = ctypes.c_int
    lib.banjo_begin_fracture.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_double]
    lib.banjo_fracture_pending.restype = ctypes.c_int
    lib.banjo_fracture_pending.argtypes = [ctypes.c_void_p]
    lib.banjo_fracture_ready.restype = ctypes.c_int
    lib.banjo_fracture_ready.argtypes = [ctypes.c_void_p]
    lib.banjo_fracture_subject.restype = ctypes.c_char_p
    lib.banjo_fracture_subject.argtypes = [ctypes.c_void_p]
    lib.banjo_finish_fracture.restype = ctypes.c_int
    lib.banjo_finish_fracture.argtypes = [ctypes.c_void_p]
    lib.banjo_collect.restype = ctypes.c_int
    lib.banjo_collect.argtypes = [ctypes.c_void_p, ctypes.c_double * 3,
                                  ctypes.c_double, ctypes.c_int]
    lib.banjo_collected.restype = ctypes.c_int
    lib.banjo_collected.argtypes = [ctypes.c_void_p, ctypes.POINTER(_Lot), ctypes.c_int]
    lib.banjo_hinge.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p,
                                ctypes.c_double * 3, ctypes.c_double * 3,
                                ctypes.c_double, ctypes.c_double, ctypes.c_double]
    lib.banjo_hinge.restype = ctypes.c_int
    lib.banjo_slide.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p,
                                ctypes.c_double * 3, ctypes.c_double * 3,
                                ctypes.c_double, ctypes.c_double, ctypes.c_double]
    lib.banjo_slide.restype = ctypes.c_int
    lib.banjo_tie.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p,
                              ctypes.c_double * 3, ctypes.c_double * 3,
                              ctypes.c_double, ctypes.c_double]
    lib.banjo_tie.restype = ctypes.c_int
    lib.banjo_reeve.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p,
                                ctypes.c_double * 3, ctypes.c_double * 3,
                                ctypes.c_double * 3, ctypes.c_double * 3,
                                ctypes.c_double, ctypes.c_double]
    lib.banjo_reeve.restype = ctypes.c_int
    lib.banjo_joint_count.argtypes = [ctypes.c_void_p]
    lib.banjo_joint_count.restype = ctypes.c_int
    lib.banjo_joints.argtypes = [ctypes.c_void_p, ctypes.POINTER(_Joint), ctypes.c_int]
    lib.banjo_joints.restype = ctypes.c_int
    lib.banjo_joint_friction.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_double]
    lib.banjo_joint_friction.restype = ctypes.c_int
    lib.banjo_unhinge.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    lib.banjo_unhinge.restype = ctypes.c_int
    lib.banjo_decline_break.restype = ctypes.c_int
    lib.banjo_last_outcome.argtypes = [ctypes.c_void_p]
    lib.banjo_last_outcome.restype = ctypes.c_int

    lib.banjo_body_count.argtypes = [ctypes.c_void_p]
    lib.banjo_body_count.restype = ctypes.c_int
    lib.banjo_bodies.argtypes = [ctypes.c_void_p, ctypes.POINTER(_Body), ctypes.c_int]
    lib.banjo_bodies.restype = ctypes.c_int
    lib.banjo_impact_count.argtypes = [ctypes.c_void_p, ctypes.c_double]
    lib.banjo_impact_count.restype = ctypes.c_int
    lib.banjo_impacts.argtypes = [ctypes.c_void_p, ctypes.c_double,
                                  ctypes.POINTER(_Impact), ctypes.c_int]
    lib.banjo_impacts.restype = ctypes.c_int

    lib.banjo_grab.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    lib.banjo_grab.restype = ctypes.c_int
    lib.banjo_move_held.argtypes = [ctypes.c_void_p, ctypes.c_double * 3]
    lib.banjo_move_held.restype = ctypes.c_int
    lib.banjo_release.argtypes = [ctypes.c_void_p]
    lib.banjo_release.restype = ctypes.c_int
    lib.banjo_held.argtypes = [ctypes.c_void_p]
    lib.banjo_held.restype = ctypes.c_char_p

    lib.banjo_pick_ray.argtypes = [ctypes.c_void_p, ctypes.c_double * 3, ctypes.c_double * 3,
                                   ctypes.c_double, ctypes.POINTER(_Pick)]
    lib.banjo_pick_ray.restype = ctypes.c_int

    lib.banjo_delay_count.argtypes = [ctypes.c_void_p]
    lib.banjo_delay_count.restype = ctypes.c_int
    lib.banjo_delays.argtypes = [ctypes.c_void_p, ctypes.POINTER(_Delay), ctypes.c_int]
    lib.banjo_delays.restype = ctypes.c_int
    lib.banjo_forget_delays.argtypes = [ctypes.c_void_p]
    lib.banjo_forget_delays.restype = ctypes.c_int
    lib.banjo_foresee.argtypes = [ctypes.c_void_p, ctypes.c_double]
    lib.banjo_foresee.restype = ctypes.c_int

    found = lib.banjo_abi_version()
    if found != ABI_VERSION:
        raise BanjoError(f"this binding speaks ABI {ABI_VERSION}; the library speaks {found}")
    if path is None:
        _lib = lib
    return lib


def _triple(values: Any) -> ctypes.Array:
    seq = list(values)
    if len(seq) != 3:
        raise BanjoError("a point needs three numbers")
    return (ctypes.c_double * 3)(*[float(v) for v in seq])


class World:
    """One live world. Not thread-safe; it belongs to the thread that made it."""

    def __init__(self, scene: dict[str, Any] | str, cell_size_m: float = 0.02,
                 library_path: str | os.PathLike[str] | None = None) -> None:
        self._lib = library(library_path)
        text = scene if isinstance(scene, str) else json.dumps(scene)
        handle = self._lib.banjo_open(text.encode("utf-8"), float(cell_size_m))
        if not handle:
            raise BanjoError(self._error())
        self._handle = ctypes.c_void_p(handle)

    # -- lifetime ---------------------------------------------------------
    def __enter__(self) -> "World":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        if getattr(self, "_handle", None) is not None:
            self._lib.banjo_close(self._handle)
            self._handle = None

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def _error(self) -> str:
        return (self._lib.banjo_last_error() or b"").decode("utf-8", "replace")

    def _check(self, code: int, what: str) -> int:
        if code < 0:
            raise BanjoError(f"{what}: {self._error() or 'the engine refused'}")
        return code

    def _alive(self) -> ctypes.c_void_p:
        if getattr(self, "_handle", None) is None:
            raise BanjoError("this world has been closed")
        return self._handle

    # -- time -------------------------------------------------------------
    def advance(self, dt_s: float, window_s: float = 0.003) -> None:
        """Step, settling whatever wants to break. Cannot leave the world wedged."""
        self._check(self._lib.banjo_advance(self._alive(), float(dt_s), float(window_s)),
                    "advancing the world")

    def step(self, dt_s: float) -> int:
        """One step. Returns OK, or BREAK_PENDING if time could not move.

        BREAK_PENDING means the step was taken back because something is about
        to break, and nothing moves again until it is answered -- `fracture` on
        each name in `breakable()`, or `decline_break`. Use `advance` unless the
        decision is genuinely yours.
        """
        return self._check(self._lib.banjo_step(self._alive(), float(dt_s)), "stepping the world")

    @property
    def time_s(self) -> float:
        return self._lib.banjo_time(self._alive())

    # -- breaking ---------------------------------------------------------
    def breakable(self) -> list[str]:
        handle = self._alive()
        count = self._check(self._lib.banjo_breakable_count(handle), "asking what may break")
        out = []
        for i in range(count):
            name = self._lib.banjo_breakable_name(handle, i)
            if name:
                out.append(name.decode("utf-8", "replace"))
        return out

    def fracture(self, name: str, window_s: float = 0.003) -> int:
        """Put it back into the lattice at the impact. Returns pieces; 1 means it held."""
        return self._check(
            self._lib.banjo_fracture(self._alive(), name.encode("utf-8"), float(window_s)),
            f"breaking {name}")

    def begin_fracture(self, name: str, window_s: float = 0.0) -> bool:
        """Start working a break out without waiting for it.

        `fracture` blocks for the whole run -- a third of a second to a second --
        and because the caller drives time, the whole world stops with it. What
        somebody watching sees is the room freezing at the instant of an impact.

            if world.begin_fracture(name):
                while not world.fracture_ready():
                    world.step(dt)            # the world keeps running
                pieces = world.finish_fracture()

        The pair about to break is pinned while the answer is worked out: letting
        it carry on means it bounces off something that is in fact shattering.

        False means there was nothing to run -- anchored scenery, a name that is
        not there, something in a hand. The contact was still answered, so time
        can move; there is simply nothing to collect.
        """
        code = self._lib.banjo_begin_fracture(self._alive(), name.encode("utf-8"), window_s)
        if code == 0:
            return True
        if code == -2:
            return False
        self._check(code, f"starting a fracture of {name!r}")
        return False

    def fracture_pending(self) -> bool:
        """Whether something is being worked out. One at a time."""
        return bool(self._check(self._lib.banjo_fracture_pending(self._alive()),
                                "asking what is being worked out"))

    def fracture_ready(self) -> bool:
        """Whether the answer is in. Cheap, and safe to ask every step."""
        return bool(self._check(self._lib.banjo_fracture_ready(self._alive()),
                                "asking whether the answer is ready"))

    def fracture_subject(self) -> str:
        """What is being worked out, or "" if nothing is."""
        got = self._lib.banjo_fracture_subject(self._alive())
        return got.decode("utf-8") if got else ""

    def finish_fracture(self) -> int:
        """Take the answer and apply it, waiting only if it is not ready.

        Returns the piece count, exactly as `fracture` does: 1 means it held.
        """
        return self._check(self._lib.banjo_finish_fracture(self._alive()),
                           "collecting a fracture")

    def hinge(self, a: str, b: str, at_m: Any, axis: Any = (0.0, 1.0, 0.0),
              lower_deg: float = -180.0, upper_deg: float = 180.0,
              friction_n_m: float = 0.0) -> int:
        """Hang one named thing off another on a pin.

        The pin is given where it is in the world RIGHT NOW and is kept in both
        bodies' own frames from then on, which is what makes a mechanism go on
        working when the whole assembly is carried somewhere else or turned
        over.

        A door swings because a push off its centre line makes a torque about
        the pin, and stops because it meets its travel limit or runs out of
        momentum. Nothing plays an animation of a door opening.

        Limits are degrees either side of where it is hung: `lower_deg` from
        -180 to 0 and `upper_deg` from 0 to 180, so a door built shut swings
        0..90 and one built open swings -90..0. `friction_n_m` is what it takes
        to start it turning -- a stiff old hinge holds a door where it is left.

        Either end may be anchored scenery (a door on a wall is the ordinary
        case) but not both, or there is nothing for the pin to move.

        Returns the joint's id.
        """
        where = (ctypes.c_double * 3)(*(float(v) for v in at_m))
        along = (ctypes.c_double * 3)(*(float(v) for v in axis))
        return self._check(
            self._lib.banjo_hinge(self._alive(), a.encode("utf-8"), b.encode("utf-8"),
                                  where, along, lower_deg, upper_deg, friction_n_m),
            f"hanging {b!r} on {a!r}")

    def slide(self, a: str, b: str, at_m: Any, axis: Any = (0.0, 1.0, 0.0),
              lower_m: float = -1.0, upper_m: float = 1.0,
              friction_n: float = 0.0) -> int:
        """Let one named thing slide along a line fixed in another.

        The same idea as a pin, one degree of freedom the other way round: the
        two are locked in rotation and free to move along one axis. A portcullis
        in its grooves, a sliding door, a bolt going across a door.

        And, like a pin, nothing is played. A portcullis hauled up and let go
        FALLS -- gravity is still acting on a body free to move down its own
        axis -- and it stops on whatever is under it, at whatever height that
        thing happens to be. Nothing here knows what a portcullis is.

        Travel is metres either side of where it is built: `lower_m` zero or
        less, `upper_m` zero or more. `friction_n` is what it takes to start it
        moving, and it is the difference between a gate that stays where you
        leave it and one that drops the moment you stop hauling -- size it
        against the weight it has to hold, which for 1.5 x 1.8 x 0.1 m of iron
        is 20.8 kN.

        Returns the joint's id.
        """
        where = (ctypes.c_double * 3)(*(float(v) for v in at_m))
        along = (ctypes.c_double * 3)(*(float(v) for v in axis))
        return self._check(
            self._lib.banjo_slide(self._alive(), a.encode("utf-8"), b.encode("utf-8"),
                                  where, along, lower_m, upper_m, friction_n),
            f"putting {b!r} in a groove on {a!r}")

    def tie(self, a: str, b: str, at_a_m: Any, at_b_m: Any,
            length_m: float = 0.0, breaking_tension_n: float = 0.0) -> int:
        """Tie one named thing to another: up to `length_m` apart and no further.

        That one asymmetry is the whole of what makes a rope a rope: it PULLS
        and it does not PUSH. Below the length the link does nothing at all, so
        slack really is slack.

        A rope or a chain is made of these -- a run of small bodies, each tied
        to the next. There is no rope object and no rope solver, which is why it
        hangs in a catenary (its segments are heavy), drapes over what it
        touches (its segments collide), and can be cut anywhere along its length
        with `unhinge`.

        `length_m` of 0 means "as they stand": the distance between the two
        points given. `breaking_tension_n` of 0 means it never parts; anything
        else is a rope you can overload, and a parted link reports `attached`
        False. Read what it is carrying from `Joint.tension_n`.

        Returns the joint's id.
        """
        one = (ctypes.c_double * 3)(*(float(v) for v in at_a_m))
        two = (ctypes.c_double * 3)(*(float(v) for v in at_b_m))
        return self._check(
            self._lib.banjo_tie(self._alive(), a.encode("utf-8"), b.encode("utf-8"),
                                one, two, length_m, breaking_tension_n),
            f"tying {b!r} to {a!r}")

    def reeve(self, a: str, b: str, at_a_m: Any, at_b_m: Any,
              over_a_m: Any, over_b_m: Any, ratio: float = 1.0,
              length_m: float = 0.0) -> int:
        """Reeve a rope from one named thing, over two fixed points, to another.

        A hoist: pull one end down and the other comes up.

        This is the IDEAL pulley. What the engine holds is a relationship
        between lengths -- |a - over_a| + ratio * |b - over_b| <= length -- and
        nothing else. No wheel, so no wheel inertia and no bearing friction; no
        wrap, so the rope cannot slip or come off. The physical alternative is
        `tie`: a run of bodies draped over something, with real wrap and real
        friction, at a body per segment.

        `ratio` applies to B's RUN, and which end is not a detail. b moves
        1/ratio as far as a and feels ratio times the tension, so the advantage
        is on b's side: hang the LOAD at b and a counterweight of load/ratio
        balances it. With the load at `a` you have the same machine backwards
        and need TWICE the weight.

        `length_m` of 0 means "as it is rove". Returns the joint's id.
        """
        def three(values: Any) -> Any:
            return (ctypes.c_double * 3)(*(float(v) for v in values))
        return self._check(
            self._lib.banjo_reeve(self._alive(), a.encode("utf-8"), b.encode("utf-8"),
                                  three(at_a_m), three(at_b_m),
                                  three(over_a_m), three(over_b_m), ratio, length_m),
            f"reeving {a!r} to {b!r}")

    def joints(self) -> list[Joint]:
        """Every joint in the world, and where each has got to."""
        count = self._check(self._lib.banjo_joint_count(self._alive()),
                            "counting the pins")
        if count <= 0:
            return []
        out = (_Joint * count)()
        written = self._check(self._lib.banjo_joints(self._alive(), out, count),
                              "reading the pins")
        names = {JOINT_SLIDER: "slider", JOINT_LINK: "link",
                 JOINT_PULLEY: "pulley", JOINT_HINGE: "hinge"}
        return [Joint(id=int(out[i].id),
                      kind=names.get(out[i].kind, "hinge"),
                      a=(out[i].a or b"").decode("utf-8"),
                      b=(out[i].b or b"").decode("utf-8"),
                      at=out[i].at,
                      lower=out[i].lower,
                      upper=out[i].upper,
                      friction=out[i].friction,
                      at_m=tuple(out[i].at_m),
                      axis=tuple(out[i].axis),
                      attached=bool(out[i].attached),
                      tension_n=out[i].tension_n,
                      breaks_at_n=out[i].breaks_at_n,
                      ratio=out[i].ratio,
                      over_a_m=tuple(out[i].over_a_m),
                      over_b_m=tuple(out[i].over_b_m))
                for i in range(written)]

    def joint_friction(self, joint: int, friction: float) -> None:
        """How hard a joint is to move: newton metres for a pin, newtons for a slide."""
        self._check(self._lib.banjo_joint_friction(self._alive(), joint, friction),
                    "stiffening a joint")

    def unhinge(self, joint: int) -> None:
        """Take the pin out. What was hanging on it falls."""
        self._check(self._lib.banjo_unhinge(self._alive(), joint), "taking a pin out")

    def collect(self, at_m: Any, radius_m: float = 1.0,
                largest_cells: int = 0) -> list[Lot]:
        """Sweep up the loose pieces near a point, and say what they were.

        Only pieces -- a hull is what something becomes when it breaks or bends
        -- so authored objects, anchored scenery and whatever is in the hand all
        stay where they are. `largest_cells` is what counts as little (0 for the
        default): a shard of nine cells is debris, half a pane is not.

        This is also how a world that shatters keeps working: the reversible step
        a fracture needs cannot run past a couple of thousand bodies, and a room
        fills up faster than that.
        """
        place = (ctypes.c_double * 3)(*(float(v) for v in at_m))
        count = self._check(
            self._lib.banjo_collect(self._alive(), place, radius_m, largest_cells),
            "sweeping the floor")
        if count <= 0:
            return []
        out = (_Lot * count)()
        written = self._check(self._lib.banjo_collected(self._alive(), out, count),
                              "reading what was swept up")
        return [Lot(material=(out[i].material or b"").decode("utf-8"),
                    kilograms=out[i].kilograms,
                    pieces=out[i].pieces,
                    cells=out[i].cells)
                for i in range(written)]

    @property
    def last_outcome(self) -> str:
        """What the last fracture turned out to be: held, dented or broke."""
        return OUTCOMES.get(self._lib.banjo_last_outcome(self._alive()), "nothing")

    def decline_break(self, name: str) -> None:
        """Let this contact pass. Answering is what matters, not which way."""
        self._check(self._lib.banjo_decline_break(self._alive(), name.encode("utf-8")),
                    f"declining the break on {name}")

    # -- reading ----------------------------------------------------------
    def bodies(self) -> list[Body]:
        handle = self._alive()
        count = self._check(self._lib.banjo_body_count(handle), "counting bodies")
        if count == 0:
            return []
        buffer = (_Body * count)()
        written = self._check(self._lib.banjo_bodies(handle, buffer, count), "reading bodies")
        return [Body(name=(b.name or b"").decode("utf-8", "replace"),
                     material=(b.material or b"").decode("utf-8", "replace"),
                     shape=SHAPES.get(b.shape, "hull"),
                     position_m=tuple(b.position_m),
                     orientation_wxyz=tuple(b.orientation_wxyz),
                     velocity_m_s=tuple(b.velocity_m_s),
                     dimensions_m=tuple(b.dimensions_m),
                     anchored=bool(b.anchored), held=bool(b.held), rgba=int(b.rgba))
                for b in buffer[:written]]

    def body(self, name: str) -> Body | None:
        for body in self.bodies():
            if body.name == name:
                return body
        return None

    def impacts(self, quiet_speed_m_s: float = 0.5) -> list[Impact]:
        handle = self._alive()
        count = self._check(self._lib.banjo_impact_count(handle, float(quiet_speed_m_s)),
                            "counting impacts")
        if count == 0:
            return []
        buffer = (_Impact * count)()
        written = self._check(
            self._lib.banjo_impacts(handle, float(quiet_speed_m_s), buffer, count),
            "reading impacts")
        return [Impact(struck=(i.struck or b"").decode("utf-8", "replace"),
                       by=(i.by or b"").decode("utf-8", "replace"),
                       closing_speed_m_s=i.closing_speed_m_s,
                       threshold_speed_m_s=i.threshold_speed_m_s,
                       dent_speed_m_s=i.dent_speed_m_s,
                       energy_j=i.energy_j, would_break=bool(i.would_break),
                       would_dent=bool(i.would_dent))
                for i in buffer[:written]]

    # -- what made it wait ------------------------------------------------
    def delays(self) -> list[Delay]:
        """Every moment the world waited, or was spared waiting."""
        handle = self._alive()
        count = self._check(self._lib.banjo_delay_count(handle), "counting delays")
        if count == 0:
            return []
        buffer = (_Delay * count)()
        written = self._check(self._lib.banjo_delays(handle, buffer, count), "reading delays")
        return [Delay(at_s=d.at_s,
                      object=(d.object or b"").decode("utf-8", "replace"),
                      kind=(d.kind or b"").decode("utf-8", "replace"),
                      lead_ms=d.lead_ms, cost_ms=d.cost_ms)
                for d in buffer[:written]]

    def forget_delays(self) -> None:
        self._check(self._lib.banjo_forget_delays(self._alive()), "clearing delays")

    def foresee(self, horizon_s: float) -> None:
        """Look this far ahead for a collision that will need the lattice."""
        self._check(self._lib.banjo_foresee(self._alive(), float(horizon_s)),
                    "setting the lookahead")

    # -- the hand ---------------------------------------------------------
    def grab(self, name: str) -> None:
        self._check(self._lib.banjo_grab(self._alive(), name.encode("utf-8")),
                    f"picking up {name}")

    def move_held(self, to_m: Any) -> None:
        self._check(self._lib.banjo_move_held(self._alive(), _triple(to_m)), "carrying")

    def release(self) -> None:
        self._check(self._lib.banjo_release(self._alive()), "letting go")

    @property
    def held(self) -> str:
        return (self._lib.banjo_held(self._alive()) or b"").decode("utf-8", "replace")

    # -- asking where things are ------------------------------------------
    def pick(self, from_m: Any, direction: Any, max_m: float = 0.0) -> Pick:
        """What a ray meets first, against the shapes the solver really collides."""
        out = _Pick()
        self._check(self._lib.banjo_pick_ray(self._alive(), _triple(from_m), _triple(direction),
                                             float(max_m), ctypes.byref(out)), "casting a ray")
        return Pick(hit=bool(out.hit), name=(out.name or b"").decode("utf-8", "replace"),
                    distance_m=out.distance_m, point_m=tuple(out.point_m))


def version() -> str:
    return (library().banjo_version_string() or b"").decode("utf-8", "replace")
