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

# Bumped with the header: banjo_body gained a material.
ABI_VERSION = 2

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
                ("energy_j", ctypes.c_double),
                ("would_break", ctypes.c_int)]


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
    energy_j: float
    would_break: bool


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
    lib.banjo_decline_break.restype = ctypes.c_int

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
                       energy_j=i.energy_j, would_break=bool(i.would_break))
                for i in buffer[:written]]

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
