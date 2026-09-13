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

# Bumped with the header: heat, chemistry and gas (14), terrain and water (15).
# (13 is another branch's.)
ABI_VERSION = 15

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
JOINT_FIXING = 4
JOINT_ELASTIC = 5


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
                ("over_b_m", ctypes.c_double * 3),
                ("tension_now_n", ctypes.c_double),
                ("shear_now_n", ctypes.c_double),
                ("holds_tension_n", ctypes.c_double),
                ("holds_shear_n", ctypes.c_double),
                ("rest_m", ctypes.c_double),
                ("stiffness_n_m", ctypes.c_double),
                ("damping_n_s_m", ctypes.c_double),
                ("force_n", ctypes.c_double),
                ("stored_j", ctypes.c_double)]


class _Overload(ctypes.Structure):
    _fields_ = [("name", ctypes.c_char_p),
                ("carrying_n", ctypes.c_double),
                ("span_m", ctypes.c_double),
                ("stress_pa", ctypes.c_double),
                ("strength_pa", ctypes.c_double)]


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


class _BodyHeat(ctypes.Structure):
    _fields_ = [("name", ctypes.c_char_p),
                ("material", ctypes.c_char_p),
                ("temperature_k", ctypes.c_double),
                ("core_temperature_k", ctypes.c_double),
                ("mass_kg", ctypes.c_double),
                ("fuel_kg", ctypes.c_double),
                ("heat_release_w", ctypes.c_double),
                ("fuel_use_kg_s", ctypes.c_double),
                ("remaining_s", ctypes.c_double),
                ("heater_w", ctypes.c_double),
                ("gained_w", ctypes.c_double),
                ("lost_w", ctypes.c_double),
                ("reacting", ctypes.c_int),
                ("declared", ctypes.c_int)]


class _GasRegion(ctypes.Structure):
    _fields_ = [("name", ctypes.c_char_p),
                ("piston", ctypes.c_char_p),
                ("temperature_k", ctypes.c_double),
                ("pressure_pa", ctypes.c_double),
                ("volume_m3", ctypes.c_double),
                ("mass_kg", ctypes.c_double),
                ("moles", ctypes.c_double),
                ("base_m", ctypes.c_double * 3),
                ("axis", ctypes.c_double * 3),
                ("area_m2", ctypes.c_double),
                ("height_m", ctypes.c_double),
                ("stroke_m", ctypes.c_double),
                ("force_n", ctypes.c_double),
                ("work_to_bodies_j", ctypes.c_double),
                ("work_to_atmosphere_j", ctypes.c_double),
                ("heater_w", ctypes.c_double),
                ("wall_loss_w", ctypes.c_double),
                ("vent_open", ctypes.c_int)]


class _Energy(ctypes.Structure):
    _fields_ = [(field, ctypes.c_double) for field in (
        "chemical_j", "thermal_j", "stored_j", "mass_kg", "initial_j", "heater_in_j",
        "heat_to_surroundings_j", "matter_in_j", "matter_in_kg", "matter_out_j",
        "matter_out_kg", "joined_j", "left_j", "work_to_bodies_j", "work_to_atmosphere_j",
        "numerical_j", "residual_j", "mass_residual_kg", "mechanical_j")]


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
    # For a fixing: what it is carrying along its axis and across it, and what
    # it can take of each. A peg pulled straight out and a peg sheared sideways
    # fail at different loads, so these are two numbers and not one.
    tension_now_n: float = 0.0
    shear_now_n: float = 0.0
    holds_tension_n: float = 0.0
    holds_shear_n: float = 0.0
    # For an elastic: the declared linear model, and what it currently holds.
    #     force_n  = stiffness_n_m * (at - rest_m)
    #     stored_j = stiffness_n_m * (at - rest_m) ** 2 / 2
    rest_m: float = 0.0
    stiffness_n_m: float = 0.0
    damping_n_s_m: float = 0.0
    force_n: float = 0.0
    stored_j: float = 0.0


@dataclass(frozen=True)
class Overload:
    """A thing carrying more than it can hold up.

    The OTHER way something breaks here, and it exists because the first way
    cannot see it. Every other break starts from a blow; a shelf with too much
    stacked on it is struck by nothing at all, and reports no contacts
    whatsoever once it has settled. So this is asked from statics: what is
    resting on it, how far apart its supports are, and what bending that puts in
    it.

    Like every bound in this engine, past `strength_pa` is NECESSARY AND NOT
    SUFFICIENT -- it says the lattice is worth running.
    """
    name: str
    # What is stacked on it, not counting its own weight.
    carrying_n: float
    # How far apart its supports are. A beam supported along its whole length
    # has no span and cannot be bent -- the honest reason a plate lying flat on
    # the floor will not break however much is piled on it.
    span_m: float
    stress_pa: float
    strength_pa: float


@dataclass(frozen=True)
class Pick:
    hit: bool
    # Empty when the ray stopped on something that is not one of the scene's
    # bodies -- the ground. Not the same answer as meeting nothing.
    name: str
    distance_m: float
    point_m: tuple[float, float, float]


@dataclass(frozen=True)
class BodyHeat:
    """What one body holds and how hot it is.

    `temperature_k` is the surface -- what glows, burns and radiates -- and
    `core_temperature_k` the rest of it. `remaining_s` is the fuel left over the
    rate it is being used now: an estimate under current conditions, infinite
    when nothing is burning. Nothing here has a burn time; a fire lasts as long
    as its fuel does at the rate the model burns it.
    """
    name: str
    material: str
    temperature_k: float
    core_temperature_k: float
    mass_kg: float
    fuel_kg: float
    heat_release_w: float
    fuel_use_kg_s: float
    remaining_s: float
    heater_w: float
    gained_w: float
    lost_w: float
    reacting: bool
    declared: bool


@dataclass(frozen=True)
class GasRegion:
    """A volume of gas, and the body it pushes on.

    Temperature and pressure are derived from what the gas holds and the
    volume it has, never assigned. `work_to_bodies_j` is the boundary work
    delivered to bodies, net of pushing the atmosphere back -- exactly the
    force that was applied times how far the body went.
    """
    name: str
    piston: str
    temperature_k: float
    pressure_pa: float
    volume_m3: float
    mass_kg: float
    moles: float
    base_m: tuple[float, float, float]
    axis: tuple[float, float, float]
    area_m2: float
    height_m: float
    stroke_m: float
    force_n: float
    work_to_bodies_j: float
    work_to_atmosphere_j: float
    heater_w: float
    wall_loss_w: float
    vent_open: bool


@dataclass(frozen=True)
class Energy:
    """The ledger. Chemical and thermal are two views of ONE stored energy.

        stored - initial = heater_in - heat_to_surroundings + matter_in
                           - matter_out + joined - left - work_to_bodies
                           - work_to_atmosphere + numerical + residual
    """
    chemical_j: float
    thermal_j: float
    stored_j: float
    mass_kg: float
    initial_j: float
    heater_in_j: float
    heat_to_surroundings_j: float
    matter_in_j: float
    matter_in_kg: float
    matter_out_j: float
    matter_out_kg: float
    joined_j: float
    left_j: float
    work_to_bodies_j: float
    work_to_atmosphere_j: float
    numerical_j: float
    residual_j: float
    mass_residual_kg: float
    mechanical_j: float


# ---- terrain and water (ABI 15) ---------------------------------------------

class _Terrain(ctypes.Structure):
    _fields_ = [("nx", ctypes.c_int), ("nz", ctypes.c_int),
                ("cell_m", ctypes.c_double), ("origin_m", ctypes.c_double * 2),
                ("chunks_x", ctypes.c_int), ("chunks_z", ctypes.c_int),
                ("lowest_m", ctypes.c_double), ("highest_m", ctypes.c_double),
                ("floor_m", ctypes.c_double),
                ("rock_m3", ctypes.c_double), ("soil_m3", ctypes.c_double),
                ("sand_m3", ctypes.c_double),
                ("dug_m3", ctypes.c_double), ("cut_m3", ctypes.c_double),
                ("deposited_m3", ctypes.c_double), ("slumped_m3", ctypes.c_double),
                ("residual_m3", ctypes.c_double),
                ("unsettled_columns", ctypes.c_int), ("chunks_rebuilt", ctypes.c_int),
                ("rebuild_ms_worst", ctypes.c_double)]


class _Water(ctypes.Structure):
    _fields_ = [("time_s", ctypes.c_double),
                ("volume_m3", ctypes.c_double), ("wet_area_m2", ctypes.c_double),
                ("cells", ctypes.c_int), ("wet_cells", ctypes.c_int),
                ("active_cells", ctypes.c_int),
                ("inflow_m3_s", ctypes.c_double), ("outflow_m3_s", ctypes.c_double),
                ("initial_m3", ctypes.c_double), ("inflow_m3", ctypes.c_double),
                ("outflow_m3", ctypes.c_double), ("numerical_m3", ctypes.c_double),
                ("residual_m3", ctypes.c_double),
                ("substeps", ctypes.c_double), ("last_substep_s", ctypes.c_double),
                ("wave_speed_m_s", ctypes.c_double),
                ("bodies_in_water", ctypes.c_int),
                ("water_ms_worst", ctypes.c_double), ("coupling_ms_worst", ctypes.c_double),
                ("step_ms_worst", ctypes.c_double)]


class _Dug(ctypes.Structure):
    _fields_ = [("sand_m3", ctypes.c_double), ("soil_m3", ctypes.c_double),
                ("mass_kg", ctypes.c_double), ("columns", ctypes.c_int),
                ("chunks_rebuilt", ctypes.c_int), ("rebuild_ms", ctypes.c_double),
                ("bodies_woken", ctypes.c_int)]


class _Block(ctypes.Structure):
    _fields_ = [("center_m", ctypes.c_double * 3), ("size_m", ctypes.c_double * 3),
                ("volume_m3", ctypes.c_double), ("mass_kg", ctypes.c_double)]


@dataclass(frozen=True)
class Terrain:
    """The ground: its grid, what it is made of, and what has crossed its boundary."""
    nx: int
    nz: int
    cell_m: float
    origin_m: tuple[float, float]
    chunks_x: int
    chunks_z: int
    lowest_m: float
    highest_m: float
    floor_m: float
    rock_m3: float
    soil_m3: float
    sand_m3: float
    dug_m3: float
    cut_m3: float
    deposited_m3: float
    slumped_m3: float
    residual_m3: float
    unsettled_columns: int
    chunks_rebuilt: int
    rebuild_ms_worst: float


@dataclass(frozen=True)
class Water:
    """The water: how much, where, what crosses its edges, and what it costs.

    volume - initial = inflow - outflow + numerical + residual."""
    time_s: float
    volume_m3: float
    wet_area_m2: float
    cells: int
    wet_cells: int
    active_cells: int
    inflow_m3_s: float
    outflow_m3_s: float
    initial_m3: float
    inflow_m3: float
    outflow_m3: float
    numerical_m3: float
    residual_m3: float
    substeps: float
    last_substep_s: float
    wave_speed_m_s: float
    bodies_in_water: int
    water_ms_worst: float
    coupling_ms_worst: float
    step_ms_worst: float


@dataclass(frozen=True)
class Dug:
    """What a dig or a heap moved, and what it cost the world."""
    sand_m3: float
    soil_m3: float
    mass_kg: float
    columns: int
    chunks_rebuilt: int
    rebuild_ms: float
    bodies_woken: int


@dataclass(frozen=True)
class Block:
    """A block cut out of bare rock: the box and the matter it is."""
    center_m: tuple[float, float, float]
    size_m: tuple[float, float, float]
    volume_m3: float
    mass_kg: float


def _xz(point: Any) -> ctypes.Array:
    """A point on the ground: [x, z], or [x, y, z] with y ignored."""
    seq = [float(v) for v in point]
    if len(seq) == 2:
        return (ctypes.c_double * 2)(seq[0], seq[1])
    if len(seq) == 3:
        return (ctypes.c_double * 2)(seq[0], seq[2])
    raise BanjoError("a point on the ground needs [x, z] or [x, y, z]")


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
    lib.banjo_fix.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p,
                              ctypes.c_double * 3, ctypes.c_double * 3,
                              ctypes.c_double, ctypes.c_double]
    lib.banjo_fix.restype = ctypes.c_int
    lib.banjo_spring.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p,
                                 ctypes.c_double * 3, ctypes.c_double * 3,
                                 ctypes.c_double, ctypes.c_double, ctypes.c_double]
    lib.banjo_spring.restype = ctypes.c_int
    lib.banjo_overload_count.argtypes = [ctypes.c_void_p]
    lib.banjo_overload_count.restype = ctypes.c_int
    lib.banjo_overloaded.argtypes = [ctypes.c_void_p, ctypes.POINTER(_Overload),
                                     ctypes.c_int]
    lib.banjo_overloaded.restype = ctypes.c_int
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

    lib.banjo_declare.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    lib.banjo_declare.restype = ctypes.c_int
    lib.banjo_heat.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_double, ctypes.c_double]
    lib.banjo_heat.restype = ctypes.c_int
    lib.banjo_vent.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    lib.banjo_vent.restype = ctypes.c_int
    lib.banjo_body_heat_count.argtypes = [ctypes.c_void_p]
    lib.banjo_body_heat_count.restype = ctypes.c_int
    lib.banjo_bodies_heat.argtypes = [ctypes.c_void_p, ctypes.POINTER(_BodyHeat), ctypes.c_int]
    lib.banjo_bodies_heat.restype = ctypes.c_int
    lib.banjo_gas_region_count.argtypes = [ctypes.c_void_p]
    lib.banjo_gas_region_count.restype = ctypes.c_int
    lib.banjo_gas_regions.argtypes = [ctypes.c_void_p, ctypes.POINTER(_GasRegion), ctypes.c_int]
    lib.banjo_gas_regions.restype = ctypes.c_int
    lib.banjo_energy_ledger.argtypes = [ctypes.c_void_p, ctypes.POINTER(_Energy)]
    lib.banjo_energy_ledger.restype = ctypes.c_int
    lib.banjo_thermo_report.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.banjo_thermo_report.restype = ctypes.c_char_p
    lib.banjo_thermo_model.argtypes = []
    lib.banjo_thermo_model.restype = ctypes.c_char_p
    lib.banjo_terrain_info.argtypes = [ctypes.c_void_p, ctypes.POINTER(_Terrain)]
    lib.banjo_terrain_info.restype = ctypes.c_int
    lib.banjo_water_info.argtypes = [ctypes.c_void_p, ctypes.POINTER(_Water)]
    lib.banjo_water_info.restype = ctypes.c_int
    lib.banjo_dig.argtypes = [ctypes.c_void_p, ctypes.c_double * 2, ctypes.c_double * 2,
                              ctypes.c_double, ctypes.c_double, ctypes.POINTER(_Dug)]
    lib.banjo_dig.restype = ctypes.c_int
    lib.banjo_deposit.argtypes = [ctypes.c_void_p, ctypes.c_double * 2, ctypes.c_double,
                                  ctypes.c_double, ctypes.c_double, ctypes.POINTER(_Dug)]
    lib.banjo_deposit.restype = ctypes.c_int
    lib.banjo_cut.argtypes = [ctypes.c_void_p, ctypes.c_double * 2, ctypes.c_int, ctypes.c_int,
                              ctypes.c_double, ctypes.POINTER(_Block)]
    lib.banjo_cut.restype = ctypes.c_int
    lib.banjo_set_discharge.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_double]
    lib.banjo_set_discharge.restype = ctypes.c_int
    lib.banjo_terrain_heights.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_float), ctypes.c_int]
    lib.banjo_terrain_heights.restype = ctypes.c_int
    lib.banjo_water_surface.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_double), ctypes.c_int]
    lib.banjo_water_surface.restype = ctypes.c_int
    lib.banjo_environment_report.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.banjo_environment_report.restype = ctypes.c_char_p
    lib.banjo_environment_state.argtypes = [ctypes.c_void_p]
    lib.banjo_environment_state.restype = ctypes.c_char_p
    lib.banjo_survey.argtypes = [ctypes.c_void_p, ctypes.c_double, ctypes.c_double]
    lib.banjo_survey.restype = ctypes.c_char_p
    lib.banjo_awake_bodies.argtypes = [ctypes.c_void_p]
    lib.banjo_awake_bodies.restype = ctypes.c_int

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

    def fix(self, a: str, b: str, at_m: Any, axis: Any = (0.0, 1.0, 0.0),
            holds_tension_n: float = 0.0, holds_shear_n: float = 0.0) -> int:
        """Fix one named thing to another: a peg, a bracket, a catch, a bar.

        All six degrees of freedom are held, so the two move as one piece, and
        whatever their relative pose is now is the pose they keep -- which is
        what "defined alignment" means here.

        TWO strengths, because a peg pulled straight out and a peg sheared
        sideways fail at different loads. `axis` is the direction the peg
        points: tension is along it, shear is across it. Either exceeded and it
        parts, reporting `attached` False.

        Zero means it never lets go on its own -- a weld. Releasing it on
        purpose is `unhinge`, which is what a latch does, and doing so changes
        what the assembly IS.

        Returns the joint's id.
        """
        where = (ctypes.c_double * 3)(*(float(v) for v in at_m))
        along = (ctypes.c_double * 3)(*(float(v) for v in axis))
        return self._check(
            self._lib.banjo_fix(self._alive(), a.encode("utf-8"), b.encode("utf-8"),
                                where, along, holds_tension_n, holds_shear_n),
            f"fixing {b!r} to {a!r}")

    def spring(self, a: str, b: str, at_a_m: Any, at_b_m: Any,
               rest_m: float = 0.0, stiffness_n_m: float = 1000.0,
               damping_n_s_m: float = 0.0) -> int:
        """Put an elastic element between two named things.

        A bow limb, a spring, a bent plank -- anything that stores energy by
        being deformed. This is a DECLARED simplified model: an ideal linear
        spring, force = stiffness * (length - rest), stored = half of that times
        the extension. No mass of its own, no yield, no hysteresis.

        It is validated rather than asserted: tests/elastic_tests.cpp integrates
        the work actually done drawing it against the energy claimed, and
        measures what comes back. 95.86% with no damping declared.

        It pushes as well as pulls; a thing that only pulls is `tie`.

        `rest_m` of 0 means "as it stands". `damping_n_s_m` is the declared loss.

        Returns the joint's id.
        """
        one = (ctypes.c_double * 3)(*(float(v) for v in at_a_m))
        two = (ctypes.c_double * 3)(*(float(v) for v in at_b_m))
        return self._check(
            self._lib.banjo_spring(self._alive(), a.encode("utf-8"), b.encode("utf-8"),
                                   one, two, rest_m, stiffness_n_m, damping_n_s_m),
            f"springing {a!r} to {b!r}")

    def overloaded(self) -> list[Overload]:
        """Everything carrying more than its material can take.

        From statics rather than impacts -- see `Overload`. These names also
        turn up in `breakable()`, because from the outside they are the same
        question. `fracture` on one puts it into the lattice WITH ITS LOAD on
        it, which is what makes it actually fail; `decline_break` silences it,
        and that matters more here than for a blow, because a load does not go
        away by itself.
        """
        count = self._check(self._lib.banjo_overload_count(self._alive()),
                            "asking what is overloaded")
        if count <= 0:
            return []
        out = (_Overload * count)()
        written = self._check(self._lib.banjo_overloaded(self._alive(), out, count),
                              "reading what is overloaded")
        return [Overload(name=(out[i].name or b"").decode("utf-8"),
                         carrying_n=out[i].carrying_n,
                         span_m=out[i].span_m,
                         stress_pa=out[i].stress_pa,
                         strength_pa=out[i].strength_pa)
                for i in range(written)]

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
                 JOINT_PULLEY: "pulley", JOINT_FIXING: "fixing",
                 JOINT_ELASTIC: "elastic", JOINT_HINGE: "hinge"}
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
                      over_b_m=tuple(out[i].over_b_m),
                      tension_now_n=out[i].tension_now_n,
                      shear_now_n=out[i].shear_now_n,
                      holds_tension_n=out[i].holds_tension_n,
                      holds_shear_n=out[i].holds_shear_n,
                      rest_m=out[i].rest_m,
                      stiffness_n_m=out[i].stiffness_n_m,
                      damping_n_s_m=out[i].damping_n_s_m,
                      force_n=out[i].force_n,
                      stored_j=out[i].stored_j)
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

    # -- heat, chemistry and gas -------------------------------------------
    def declare(self, declaration: dict[str, Any] | str) -> None:
        """Declare contents, gas regions or heaters into the running world.

            world.declare({"heaters": [{"target": "log", "power_w": 10000,
                                        "seconds": 60}]})

        A heater declared here starts now. A key the network does not know is
        refused by name.
        """
        text = declaration if isinstance(declaration, str) else json.dumps(declaration)
        self._check(self._lib.banjo_declare(self._alive(), text.encode("utf-8")),
                    "declaring heat, chemistry or gas")

    def heat(self, target: str, power_w: float, seconds: float) -> int:
        """Heat a body or a gas region from now: external work, in the ledger.

        Enough of it lights a log and less does not -- burning is a result.
        Returns the heater's id.
        """
        return self._check(self._lib.banjo_heat(self._alive(), target.encode("utf-8"),
                                                float(power_w), float(seconds)),
                           f"heating {target!r}")

    def vent(self, region: str, open_: bool = True) -> None:
        self._check(self._lib.banjo_vent(self._alive(), region.encode("utf-8"), int(bool(open_))),
                    f"venting {region!r}")

    def heat_states(self) -> list[BodyHeat]:
        """Every body the thermochemical network holds, and how hot it is."""
        handle = self._alive()
        count = self._check(self._lib.banjo_body_heat_count(handle), "counting hot bodies")
        if count <= 0:
            return []
        buffer = (_BodyHeat * count)()
        written = self._check(self._lib.banjo_bodies_heat(handle, buffer, count),
                              "reading hot bodies")
        return [BodyHeat(name=(b.name or b"").decode("utf-8", "replace"),
                         material=(b.material or b"").decode("utf-8", "replace"),
                         temperature_k=b.temperature_k,
                         core_temperature_k=b.core_temperature_k, mass_kg=b.mass_kg,
                         fuel_kg=b.fuel_kg, heat_release_w=b.heat_release_w,
                         fuel_use_kg_s=b.fuel_use_kg_s, remaining_s=b.remaining_s,
                         heater_w=b.heater_w, gained_w=b.gained_w, lost_w=b.lost_w,
                         reacting=bool(b.reacting), declared=bool(b.declared))
                for b in buffer[:written]]

    def gas_regions(self) -> list[GasRegion]:
        """Every volume of gas, derived state and all."""
        handle = self._alive()
        count = self._check(self._lib.banjo_gas_region_count(handle), "counting gas regions")
        if count <= 0:
            return []
        buffer = (_GasRegion * count)()
        written = self._check(self._lib.banjo_gas_regions(handle, buffer, count),
                              "reading gas regions")
        return [GasRegion(name=(g.name or b"").decode("utf-8", "replace"),
                          piston=(g.piston or b"").decode("utf-8", "replace"),
                          temperature_k=g.temperature_k, pressure_pa=g.pressure_pa,
                          volume_m3=g.volume_m3, mass_kg=g.mass_kg, moles=g.moles,
                          base_m=tuple(g.base_m), axis=tuple(g.axis), area_m2=g.area_m2,
                          height_m=g.height_m, stroke_m=g.stroke_m, force_n=g.force_n,
                          work_to_bodies_j=g.work_to_bodies_j,
                          work_to_atmosphere_j=g.work_to_atmosphere_j,
                          heater_w=g.heater_w, wall_loss_w=g.wall_loss_w,
                          vent_open=bool(g.vent_open))
                for g in buffer[:written]]

    def energy(self) -> Energy:
        """The ledger: where the energy is and everything that crossed."""
        out = _Energy()
        self._check(self._lib.banjo_energy_ledger(self._alive(), ctypes.byref(out)),
                    "reading the energy ledger")
        return Energy(**{name: getattr(out, name) for name, _ in _Energy._fields_})

    def thermo_report(self, with_model: bool = False) -> dict[str, Any]:
        """Everything about heat, chemistry and gas, as the engine says it."""
        text = self._lib.banjo_thermo_report(self._alive(), int(bool(with_model))) or b"{}"
        return json.loads(text.decode("utf-8"))

    # -- terrain and water ------------------------------------------------
    def terrain(self) -> Terrain:
        """The ground: grid, volumes by material, and its ledger."""
        out = _Terrain()
        self._check(self._lib.banjo_terrain_info(self._alive(), ctypes.byref(out)), "reading the ground")
        fields = {name: getattr(out, name) for name, _ in _Terrain._fields_}
        fields["origin_m"] = tuple(out.origin_m)
        return Terrain(**fields)

    def water(self) -> Water:
        """The water: volume, where it is, what crosses its edges, what it costs."""
        out = _Water()
        self._check(self._lib.banjo_water_info(self._alive(), ctypes.byref(out)), "reading the water")
        return Water(**{name: getattr(out, name) for name, _ in _Water._fields_})

    @staticmethod
    def _dug(out: "_Dug") -> Dug:
        return Dug(**{name: getattr(out, name) for name, _ in _Dug._fields_})

    def dig(self, from_m: Any, to_m: Any | None = None, width_m: float = 1.0,
            depth_m: float = 0.5) -> Dug:
        """Dig a trench from one point to another ([x, z] or [x, y, z]), or a pit.

        Loose material first, then soil; a spade stops on rock. Only the
        colliders that changed are rebuilt, and whatever they held up is woken.
        """
        out = _Dug()
        self._check(self._lib.banjo_dig(self._alive(), _xz(from_m), _xz(to_m if to_m is not None else from_m),
                                        float(width_m), float(depth_m), ctypes.byref(out)), "digging")
        return self._dug(out)

    def deposit(self, at_m: Any, radius_m: float = 1.0, sand_m3: float = 0.0,
                soil_m3: float = 0.0) -> Dug:
        """Heap sand and soil around a point; it settles to what it can hold."""
        out = _Dug()
        self._check(self._lib.banjo_deposit(self._alive(), _xz(at_m), float(radius_m), float(sand_m3),
                                            float(soil_m3), ctypes.byref(out)), "heaping")
        return self._dug(out)

    def cut(self, at_m: Any, cells: tuple[int, int] = (4, 4), height_m: float = 0.4) -> Block:
        """Cut a block `height_m` tall out of bare rock. The ground loses it now;
        add it as a body -- with {"cut": {"at_m", "cells", "height_m"}} in the
        scene's edits -- in the world opened next."""
        out = _Block()
        self._check(self._lib.banjo_cut(self._alive(), _xz(at_m), int(cells[0]), int(cells[1]),
                                        float(height_m), ctypes.byref(out)), "cutting")
        return Block(center_m=tuple(out.center_m), size_m=tuple(out.size_m),
                     volume_m3=out.volume_m3, mass_kg=out.mass_kg)

    def set_discharge(self, river: str, discharge_m3_s: float) -> None:
        """A river's discharge from now: a flood, a drought."""
        self._check(self._lib.banjo_set_discharge(self._alive(), river.encode("utf-8"),
                                                  float(discharge_m3_s)), f"changing {river!r}")

    def terrain_heights(self) -> list[float]:
        """The ground's heights, nx * nz, row by row (j outer)."""
        info = self.terrain()
        buffer = (ctypes.c_float * (info.nx * info.nz))()
        written = self._check(self._lib.banjo_terrain_heights(self._alive(), buffer, len(buffer)),
                              "reading the ground's heights")
        return list(buffer[:written])

    def water_surface(self) -> list[float | None]:
        """The water's surface, nx * nz, None where a column is dry."""
        info = self.terrain()
        buffer = (ctypes.c_double * (info.nx * info.nz))()
        written = self._check(self._lib.banjo_water_surface(self._alive(), buffer, len(buffer)),
                              "reading the water's surface")
        return [v if v == v else None for v in buffer[:written]]

    def environment_report(self, full: bool = False) -> dict[str, Any]:
        """Everything about the ground and the water, as the engine says it."""
        text = self._lib.banjo_environment_report(self._alive(), int(bool(full))) or b"{}"
        return json.loads(text.decode("utf-8"))

    def environment_state(self) -> dict[str, Any]:
        """The water as it stands, for "water": {"state": ...} in a scene opened again."""
        text = self._lib.banjo_environment_state(self._alive()) or b"{}"
        return json.loads(text.decode("utf-8"))

    def survey(self, x_m: float, z_m: float) -> dict[str, Any]:
        """Ground and water at a point."""
        text = self._lib.banjo_survey(self._alive(), float(x_m), float(z_m)) or b"{}"
        return json.loads(text.decode("utf-8"))

    def awake_bodies(self) -> int:
        """How many bodies the rigid solver is stepping right now."""
        return self._check(self._lib.banjo_awake_bodies(self._alive()), "counting awake bodies")


def version() -> str:
    return (library().banjo_version_string() or b"").decode("utf-8", "replace")


def thermo_model() -> dict[str, Any]:
    """The substances, reactions and compositions a world starts with, and
    where every number came from -- without opening a world."""
    return json.loads((library().banjo_thermo_model() or b"{}").decode("utf-8"))
