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
import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

# Bumped with the header. 13 added blades, the cuts they make and a hand that
# grips; 14 added heat, chemistry and gas. They were numbered apart on two
# branches so that, merged, one number means one header: a library at 14
# carries both. 15 added terrain and water, on top of both; 16 heat and
# strength; 17 the hand's own motions and the one-way fixing; 18 rolling
# resistance (materials(), World.rolling_report(), the survey's share); 20 tools
# that work the ground (make_tool_point, strike, ground_works); 21 one material
# state (a body's revision, what is left of it). No library was ever 19. 22
# a world that is kept (snapshot, restored); 23 machines -- a store of energy,
# a DC motor on a pin with a brake, a rope that winds onto a drum, and how hard
# a thing is to turn (energy_store, motor, drive_motor, drum, inertia_about).
# Checked for equality below, so this has to match exactly.
# 25 adds stateful shared DC/thermal circuits.
ABI_VERSION = 25

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
                ("rgba", ctypes.c_uint),
                ("mass_kg", ctypes.c_double),
                ("revision", ctypes.c_int)]


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
JOINT_DRUM = 6          # ABI 23: a rope that winds onto a turning drum


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
                ("stored_j", ctypes.c_double),
                # ABI 16: heat and strength
                ("member", ctypes.c_char_p),
                ("rated_tension_n", ctypes.c_double),
                ("rated_shear_n", ctypes.c_double),
                ("rated_breaks_at_n", ctypes.c_double),
                ("rated_stiffness_n_m", ctypes.c_double),
                ("capacity_fraction", ctypes.c_double),
                ("rechecks", ctypes.c_uint),
                ("parted_because", ctypes.c_char_p),
                ("parted_load_n", ctypes.c_double),
                ("parted_capacity_n", ctypes.c_double),
                # ABI 17: the one-way fixing
                ("comes_off_n", ctypes.c_double)]


class _Overload(ctypes.Structure):
    _fields_ = [("name", ctypes.c_char_p),
                ("carrying_n", ctypes.c_double),
                ("span_m", ctypes.c_double),
                ("stress_pa", ctypes.c_double),
                ("strength_pa", ctypes.c_double),
                ("capacity_fraction", ctypes.c_double),
                ("why", ctypes.c_char_p)]


class _Pick(ctypes.Structure):
    _fields_ = [("hit", ctypes.c_int),
                ("name", ctypes.c_char_p),
                ("distance_m", ctypes.c_double),
                ("point_m", ctypes.c_double * 3)]


class _Hand(ctypes.Structure):
    _fields_ = [("holding", ctypes.c_char_p),
                ("mode", ctypes.c_char_p),
                ("target_m", ctypes.c_double * 3),
                ("grip_m", ctypes.c_double * 3),
                ("grip_velocity_m_s", ctypes.c_double * 3),
                ("force_n", ctypes.c_double * 3),
                ("work_j", ctypes.c_double),
                ("stroking", ctypes.c_int),
                ("stroke_along_m", ctypes.c_double),
                ("stroke_length_m", ctypes.c_double),
                ("stroke_ended", ctypes.c_char_p),
                ("let_go_body", ctypes.c_char_p),
                ("let_go_velocity_m_s", ctypes.c_double * 3),
                ("let_go_at_s", ctypes.c_double),
                ("let_go_work_j", ctypes.c_double)]


class _Flight(ctypes.Structure):
    _fields_ = [("hit", ctypes.c_int),
                ("hit_name", ctypes.c_char_p),
                ("hit_point_m", ctypes.c_double * 3),
                ("hit_after_s", ctypes.c_double),
                ("hit_speed_m_s", ctypes.c_double),
                ("points", ctypes.c_int)]


class _StrokePreview(ctypes.Structure):
    _fields_ = [("possible", ctypes.c_int),
                ("why", ctypes.c_char_p),
                ("reaches_end", ctypes.c_int),
                ("stroke_s", ctypes.c_double),
                ("work_j", ctypes.c_double),
                ("let_go_at_m", ctypes.c_double * 3),
                ("let_go_velocity_m_s", ctypes.c_double * 3),
                ("flight", _Flight)]


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
        "numerical_j", "residual_j", "mass_residual_kg", "mechanical_j", "mechanical_in_j")]


class _BodyMechanics(ctypes.Structure):
    _fields_ = [("name", ctypes.c_char_p),
                ("material", ctypes.c_char_p),
                ("law", ctypes.c_char_p),
                ("provenance", ctypes.c_char_p),
                ("tracked", ctypes.c_int),
                ("surface_k", ctypes.c_double),
                ("core_k", ctypes.c_double),
                ("peak_surface_k", ctypes.c_double),
                ("peak_core_k", ctypes.c_double),
                ("remaining_fraction", ctypes.c_double),
                ("composition_factor", ctypes.c_double),
                ("dimensions_m", ctypes.c_double * 3),
                ("section_m", ctypes.c_double * 2),
                ("consumed_m", ctypes.c_double),
                ("char_m", ctypes.c_double),
                ("layer_m", ctypes.c_double),
                ("sound_section_m", ctypes.c_double * 2),
                ("stiffness", ctypes.c_double),
                ("tension", ctypes.c_double),
                ("compression", ctypes.c_double),
                ("shear", ctypes.c_double),
                ("bending", ctypes.c_double),
                ("tension_if_cooled", ctypes.c_double),
                ("shear_if_cooled", ctypes.c_double),
                ("bending_if_cooled", ctypes.c_double),
                ("supported", ctypes.c_int),
                # ABI 21: the compression side of the section, and what is
                # left of it, from the same state.
                ("bending_compression", ctypes.c_double),
                ("bending_compression_if_cooled", ctypes.c_double),
                ("reference_m", ctypes.c_double * 3),
                ("remaining_m", ctypes.c_double * 3),
                ("remaining_volume_m3", ctypes.c_double),
                ("mass_kg", ctypes.c_double),
                ("inertia_kg_m2", ctypes.c_double * 3),
                ("cells", ctypes.c_int),
                ("cells_burned", ctypes.c_int),
                ("bond_tension_min", ctypes.c_double),
                ("bond_tension_mean", ctypes.c_double),
                ("bond_stiffness_mean", ctypes.c_double),
                ("revision", ctypes.c_int)]


class _Blade(ctypes.Structure):
    _fields_ = [("id", ctypes.c_uint),
                ("body", ctypes.c_char_p),
                ("material", ctypes.c_char_p),
                ("heel_m", ctypes.c_double * 3),
                ("tip_m", ctypes.c_double * 3),
                ("facing", ctypes.c_double * 3),
                ("flat", ctypes.c_double * 3),
                ("grip_m", ctypes.c_double * 3),
                ("thickness_m", ctypes.c_double),
                ("edge_radius_m", ctypes.c_double),
                ("bevel_deg", ctypes.c_double),
                ("cut_area_m2", ctypes.c_double),
                ("cut_work_j", ctypes.c_double),
                ("cutting", ctypes.c_char_p),
                ("attached", ctypes.c_int)]


class _Cut(ctypes.Structure):
    _fields_ = [("blade", ctypes.c_char_p),
                ("target", ctypes.c_char_p),
                ("kind", ctypes.c_char_p),
                ("at_s", ctypes.c_double),
                ("speed_m_s", ctypes.c_double),
                ("into_m_s", ctypes.c_double),
                ("along_m_s", ctypes.c_double),
                ("across_m_s", ctypes.c_double),
                ("resistance_j_m2", ctypes.c_double),
                ("area_m2", ctypes.c_double),
                ("work_j", ctypes.c_double),
                ("bonds", ctypes.c_int),
                ("links", ctypes.c_int),
                ("separated", ctypes.c_int),
                ("pieces", ctypes.c_int),
                ("open", ctypes.c_int)]


class _ToolPoint(ctypes.Structure):
    _fields_ = [("id", ctypes.c_uint),
                ("body", ctypes.c_char_p),
                ("material", ctypes.c_char_p),
                ("tip_m", ctypes.c_double * 3),
                ("pointing", ctypes.c_double * 3),
                ("grip_m", ctypes.c_double * 3),
                ("width_m", ctypes.c_double),
                ("thickness_m", ctypes.c_double),
                ("angle_deg", ctypes.c_double),
                ("length_m", ctypes.c_double),
                ("in_", ctypes.c_char_p),
                ("depth_m", ctypes.c_double),
                ("attached", ctypes.c_int)]


class _GroundWork(ctypes.Structure):
    _fields_ = [("point", ctypes.c_uint),
                ("tool", ctypes.c_char_p),
                ("ground", ctypes.c_char_p),
                ("kind", ctypes.c_char_p),
                ("supported", ctypes.c_int),
                ("why", ctypes.c_char_p),
                ("at_s", ctypes.c_double),
                ("at_m", ctypes.c_double * 3),
                ("closing_speed_m_s", ctypes.c_double),
                ("depth_m", ctypes.c_double),
                ("sideways_m", ctypes.c_double),
                ("impulse_n_s", ctypes.c_double),
                ("peak_force_n", ctypes.c_double),
                ("work_j", ctypes.c_double),
                ("penetration_work_j", ctypes.c_double),
                ("breakout_work_j", ctypes.c_double),
                ("resistance_n", ctypes.c_double),
                ("passive_n", ctypes.c_double),
                ("loosened_sand_m3", ctypes.c_double),
                ("loosened_soil_m3", ctypes.c_double),
                ("loosened_kg", ctypes.c_double),
                ("tool_whole", ctypes.c_int),
                ("tool_dent_m", ctypes.c_double),
                ("model", ctypes.c_char_p),
                ("open", ctypes.c_int),
                ("dug", ctypes.c_int),
                ("dug_from_m", ctypes.c_double * 2),
                ("dug_to_m", ctypes.c_double * 2),
                ("dug_width_m", ctypes.c_double),
                ("dug_depth_m", ctypes.c_double)]


class _StrikeRequest(ctypes.Structure):
    _fields_ = [("target_m", ctypes.c_double * 3),
                ("shoulder_m", ctypes.c_double * 3),
                ("speed_m_s", ctypes.c_double),
                ("raise_deg", ctypes.c_double),
                ("lever", ctypes.c_int),
                ("lever_deg", ctypes.c_double),
                ("give_up_s", ctypes.c_double)]


# ---- machines (ABI 23) -------------------------------------------------------

class _EnergyStore(ctypes.Structure):
    _fields_ = [("id", ctypes.c_uint),
                ("name", ctypes.c_char_p),
                ("body", ctypes.c_char_p),
                ("capacity_j", ctypes.c_double),
                ("charge_j", ctypes.c_double),
                ("voltage_v", ctypes.c_double),
                ("max_power_w", ctypes.c_double),
                ("given_j", ctypes.c_double),
                ("short_j", ctypes.c_double)]


class _Motor(ctypes.Structure):
    _fields_ = [("id", ctypes.c_uint),
                ("joint", ctypes.c_uint),
                ("store", ctypes.c_uint),
                ("stall_torque_n_m", ctypes.c_double),
                ("no_load_rad_s", ctypes.c_double),
                ("brake_torque_n_m", ctypes.c_double),
                ("command", ctypes.c_double),
                ("brake", ctypes.c_int),
                ("state", ctypes.c_char_p),
                ("speed_rad_s", ctypes.c_double),
                ("torque_n_m", ctypes.c_double),
                ("current_a", ctypes.c_double),
                ("power_w", ctypes.c_double),
                ("turned_rad", ctypes.c_double),
                ("work_j", ctypes.c_double),
                ("heat_j", ctypes.c_double),
                ("drawn_j", ctypes.c_double),
                ("friction_heat_j", ctypes.c_double)]


class _Control(ctypes.Structure):
    _fields_ = [("id", ctypes.c_uint),
                ("name", ctypes.c_char_p),
                ("motor", ctypes.c_uint),
                ("rope", ctypes.c_uint),
                ("top_out_m", ctypes.c_double),
                ("bottom_out_m", ctypes.c_double),
                ("forward", ctypes.c_int),
                ("power", ctypes.c_int),
                ("direction", ctypes.c_int),
                ("setting", ctypes.c_double),
                ("sender", ctypes.c_char_p),
                ("seq", ctypes.c_ulonglong),
                ("command", ctypes.c_double),
                ("brake", ctypes.c_int),
                ("speed_rpm", ctypes.c_double),
                ("out_m", ctypes.c_double),
                ("rope_speed_m_s", ctypes.c_double),
                ("condition", ctypes.c_char_p)]


class _DrumRope(ctypes.Structure):
    _fields_ = [("id", ctypes.c_uint),
                ("drum", ctypes.c_char_p),
                ("load", ctypes.c_char_p),
                ("radius_m", ctypes.c_double),
                ("length_m", ctypes.c_double),
                ("out_m", ctypes.c_double),
                ("wound_m", ctypes.c_double),
                ("tension_n", ctypes.c_double),
                ("centre_m", ctypes.c_double * 3),
                ("axis", ctypes.c_double * 3),
                ("leaves_m", ctypes.c_double * 3),
                ("meets_m", ctypes.c_double * 3),
                ("attached", ctypes.c_int),
                ("winds", ctypes.c_int)]


@dataclass(frozen=True)
class ToolPoint:
    """A point on a body that can go into the ground. See docs/ground-work.md.

    Declared ON a body, as an edge is: the body supplies the matter, the
    material and where the mass is; the point adds where its tip is, which way
    it goes in, how wide and thick it is, how sharply it comes to its tip and
    how much of the tool is point. `in_` is what it is in right now ("soil",
    "sand", "loose soil" or "") and `depth_m` how far, along its own axis.
    """
    id: int
    body: str
    material: str
    tip_m: tuple[float, float, float]
    pointing: tuple[float, float, float]
    grip_m: tuple[float, float, float]
    width_m: float
    thickness_m: float
    angle_deg: float
    length_m: float
    in_: str
    depth_m: float
    attached: bool


@dataclass(frozen=True)
class GroundWork:
    """One meeting between a point and the ground, from first touch until it is out.

    `kind` is "in the ground" (open: the ground is resisting it), "broke out"
    (a pry broke ground out, and it came loose), "pulled out", "stopped" (ground
    at least as hard as the point), "glanced" (it met the ground side-on) or
    "not supported" (a regime ground-work-v1 does not cover: `supported` is
    False, and `why` says which). The work, impulse and peak force are measured
    from the solver; `resistance_n` and `passive_n` are the model's own at the
    deepest it went; `loosened_*` is what went out through the ground's dig and
    is carried.
    """
    point: int
    tool: str
    ground: str
    kind: str
    supported: bool
    why: str
    at_s: float
    at_m: tuple[float, float, float]
    closing_speed_m_s: float
    depth_m: float
    sideways_m: float
    impulse_n_s: float
    peak_force_n: float
    work_j: float
    penetration_work_j: float
    breakout_work_j: float
    resistance_n: float
    passive_n: float
    loosened_sand_m3: float
    loosened_soil_m3: float
    loosened_kg: float
    tool_whole: bool
    tool_dent_m: float
    model: str
    open: bool
    # Where what came loose went out through the ground's dig, as a dig edit
    # says it -- None when nothing did: {"from_m": [x, z], "to_m": [x, z],
    # "width_m": ..., "depth_m": ...}. A host that keeps the ground's edits
    # keeps this one, and the ground opened again from them has the same hole.
    dug: dict | None = None

    @property
    def loosened_m3(self) -> float:
        return self.loosened_sand_m3 + self.loosened_soil_m3


@dataclass(frozen=True)
class Blade:
    """An edge on a body, and what it has done. See docs/cutting-model.md.

    Declared ON a body: the body supplies the matter, the material and where
    the mass is; the blade adds the edge (heel to tip), the way it faces, how
    thick and how sharp it is, and where it is held.
    """
    id: int
    body: str
    material: str
    heel_m: tuple[float, float, float]
    tip_m: tuple[float, float, float]
    facing: tuple[float, float, float]
    flat: tuple[float, float, float]
    grip_m: tuple[float, float, float]
    thickness_m: float
    edge_radius_m: float
    bevel_deg: float
    # Everything it has cut, and what that cost as the solver applied it.
    cut_area_m2: float
    cut_work_j: float
    # What the edge is in right now, "" for nothing.
    cutting: str
    attached: bool


@dataclass(frozen=True)
class Cut:
    """One meeting between an edge and something, from first touch until they part.

    `kind` comes from geometry and motion, never from names: "edge", "slice"
    and "press" bit; "glancing", "flat" and "point" met the surface some other
    way and were ordinary contacts; "blunt" means the target is at least as hard
    as the blade, and "brittle" that it has no yield point and cracks instead.
    """
    blade: str
    target: str
    kind: str
    at_s: float
    speed_m_s: float
    into_m_s: float
    along_m_s: float
    across_m_s: float
    # R = G + H w for this edge in this material, J/m^2.
    resistance_j_m2: float
    area_m2: float
    work_j: float
    bonds: int
    links: int
    separated: bool
    pieces: int
    open: bool


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
    # What it weighs now: what a hand has to hold up and a throw has to
    # accelerate. Zero for anchored scenery, which the solver never moves.
    mass_kg: float = 0.0
    # How many times its shape has changed where it stands (ABI 21): burning
    # takes a box or a sphere in from every face -- `dimensions_m` is then what
    # is left -- and a piece whose cells burn away is rebuilt from the rest.
    revision: int = 0


@dataclass(frozen=True)
class Hand:
    """What the hand is doing, and what it has done. docs/interaction-profiles.md.

    `mode` is "carry" (placed exactly where it is put: no force, so no work),
    "haul" (pulled with a bounded force because it is attached to something),
    "grip" (wielded) or "" for an empty hand. `work_j` is measured -- the
    hand's force times its grip's own motion, step by kept step -- so it
    includes lifting and whatever the thing lost to what it rubbed on.
    `stroke_ended` is "", "reached", "let go", "blocked", "gave up" or
    "cancelled"; `let_go_*` describe the last stroke that opened the hand, and
    `let_go_at_s` is negative when none has.
    """
    holding: str
    mode: str
    target_m: tuple[float, float, float]
    grip_m: tuple[float, float, float]
    grip_velocity_m_s: tuple[float, float, float]
    force_n: tuple[float, float, float]
    work_j: float
    stroking: bool
    stroke_along_m: float
    stroke_length_m: float
    stroke_ended: str
    let_go_body: str
    let_go_velocity_m_s: tuple[float, float, float]
    let_go_at_s: float
    let_go_work_j: float


@dataclass(frozen=True)
class Flight:
    """Where something would go, stepped as the solver steps it -- gravity, then
    the flying body's own damping -- and checked against the solver's own shapes
    along the line of its centre. An empty `hit_name` with `hit` is the ground."""
    points_m: tuple[tuple[float, float, float], ...]
    hit: bool
    hit_name: str
    hit_point_m: tuple[float, float, float]
    hit_after_s: float
    hit_speed_m_s: float


@dataclass(frozen=True)
class StrokePreview:
    """What a stroke would do to what the hand holds -- the body alone, pulled
    by this hand along the path under gravity -- and where it would then fly.
    What it cannot know is anything the stroke would bump into on the way."""
    possible: bool
    why: str
    reaches_end: bool
    stroke_s: float
    work_j: float
    let_go_at_m: tuple[float, float, float]
    let_go_velocity_m_s: tuple[float, float, float]
    flight: Flight


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
    # "hinge", "slider", "link", "pulley", "fixing", "elastic" or (ABI 23)
    # "drum". Also the unit on the four numbers below: a pin has turned so many
    # DEGREES and grips in newton metres; a slide has moved so many METRES and
    # grips in newtons. A drum's rope is metres: `at` is how much of it is off
    # the drum and `upper` the whole rope, and `World.drum_ropes` says the rest.
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
    # Above zero, a ONE-WAY fixing: b sits on a the way an arrow's nock sits on
    # a string, and this is the most it holds b with along the axis, which
    # points the way b comes off. Zero for two-way fixings and other kinds.
    comes_off_n: float = 0.0
    # For an elastic: the declared linear model, and what it currently holds.
    #     force_n  = stiffness_n_m * (at - rest_m)
    #     stored_j = stiffness_n_m * (at - rest_m) ** 2 / 2
    rest_m: float = 0.0
    stiffness_n_m: float = 0.0
    damping_n_s_m: float = 0.0
    force_n: float = 0.0
    stored_j: float = 0.0
    # ABI 16 -- heat and strength (docs/thermal-mechanics.md). Which of the two
    # things the joint is MADE of (`World.joint_member`); "" when nothing was
    # named, and the joint is then exactly the numbers it was declared with.
    # With a member, holds_*, breaks_at_n and stiffness_n_m above are what it
    # has NOW and these rated_* are what it had cold.
    member: str = ""
    rated_tension_n: float = 0.0
    rated_shear_n: float = 0.0
    rated_breaks_at_n: float = 0.0
    rated_stiffness_n_m: float = 0.0
    # The share of that it still has; for a fixing, the lower of its two.
    capacity_fraction: float = 1.0
    # How many times heat changing the member made it be asked again whether
    # it holds, with both ends woken so the solver measured the load.
    rechecks: int = 0
    # Why it let go, once it has, and the two numbers that decided it.
    parted_because: str = ""
    parted_load_n: float = 0.0
    parted_capacity_n: float = 0.0


@dataclass(frozen=True)
class EnergyStore:
    """A store of energy: a battery (ABI 23, docs/machine-world.md).

    The joules in it and what it can hold, a voltage for the current it gives,
    and the most power it gives, 0 for no limit but its charge. Nothing goes
    back into it but from a declared source: a load driving a motor gives it
    nothing back. `given_j` is all it has given; `short_j` is what steps asked
    of it that it no longer had -- reported, never folded in anywhere.
    """
    id: int
    name: str
    body: str               # what it is in; "" for nothing
    capacity_j: float
    charge_j: float
    voltage_v: float
    max_power_w: float
    given_j: float
    short_j: float


@dataclass(frozen=True)
class Motor:
    """A DC motor on a pin, drawing on a store (ABI 23, docs/machine-world.md).

    Its line is the torque it stalls at and the speed it runs at unloaded, both
    at its store's voltage; `command` is the share of that voltage, -1 to 1.
    `state` is "driving", "coasting", "braking", "flat" (told to drive, and its
    store is empty) or "gone" (its pin is not in anything), said as soon as it is
    told; one with no brake, told to brake, is "coasting". The speed, torque,
    current and power are the last kept step's; the rest is since it was made:
    `turned_rad` is the whole turn, never wrapped, and its account is

        drawn_j = work_j + heat_j

    where work_j went into what it drives and heat_j is its windings' I^2 R and
    whatever a load driving it gave back. `friction_heat_j` is what the pin's
    friction took while it coasted or braked.
    """
    id: int
    joint: int              # the pin it is on (World.hinge)
    store: int              # what it draws on (World.energy_store)
    stall_torque_n_m: float
    no_load_rad_s: float
    brake_torque_n_m: float
    command: float
    brake: bool
    state: str
    speed_rad_s: float      # b's turn relative to a's, about the pin
    torque_n_m: float
    current_a: float
    power_w: float          # asked of the store
    turned_rad: float
    work_j: float
    heat_j: float
    drawn_j: float
    friction_heat_j: float


@dataclass(frozen=True)
class Control:
    """A machine's controller (ABI 24, docs/machine-world.md, "Operating a
    machine"): what a person or a program means -- power, a direction, a drive
    setting -- turned into its motor's command and brake before every step.

    A hoist's (`rope` a rope on a drum its motor's pin turns) slows for the two
    ends of its travel, `top_out_m` and `bottom_out_m` of rope out, and stops at
    them; it stops lowering when its load comes to rest on something. A motor
    driven into something that will not move for 1.5 s is stopped until it is
    told something again. `power`, `direction` (-1 lower or reverse, 0 stop, 1
    raise or forward) and `setting` (the share of the battery's voltage, 0 to 1)
    are what it was last told, by `sender` with its count `seq`; `command` and
    `brake` are what it has its motor doing; `speed_rpm` (the forward way),
    `out_m` and `rope_speed_m_s` (the rope coming in) are measured; `condition`
    says what stands in its way, "" when nothing does.
    """
    id: int
    name: str
    motor: int
    rope: int               # 0 for a shaft
    top_out_m: float
    bottom_out_m: float
    forward: int            # the sign of its motor's command that raises, or is forward
    power: bool
    direction: int
    setting: float
    sender: str
    seq: int
    command: float
    brake: bool
    speed_rpm: float
    out_m: float
    rope_speed_m_s: float
    condition: str


@dataclass(frozen=True)
class DrumRope:
    """A rope that winds onto a turning drum: the joint a hoist needs (ABI 23).

    `id` is the joint's, as `World.joints` lists it (kind "drum"). `out_m` is
    how much rope is off the drum -- the most the span to the load may be --
    and `wound_m` how much is on it; `centre_m` and `axis` are the drum's now,
    and `leaves_m` and `meets_m` where the rope leaves the drum and meets the
    load, for a host that draws it.
    """
    id: int
    drum: str
    load: str
    radius_m: float
    length_m: float
    out_m: float
    wound_m: float
    tension_n: float
    centre_m: tuple[float, float, float]
    axis: tuple[float, float, float]
    leaves_m: tuple[float, float, float]
    meets_m: tuple[float, float, float]
    attached: bool
    # +1 if the drum turning the positive way about its axle takes rope on, -1
    # if turning the other way does.
    winds: int


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
    # ABI 16. What its section can still take against the same beam cold -- 1
    # for anything heat has not touched; strength_pa is already scaled by it --
    # and why, in words.
    capacity_fraction: float = 1.0
    why: str = ""


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
    # ABI 16. Energy the mechanical side handed the network as heat: the elastic
    # energy a spring stopped holding when its member softened stretched. A
    # crossing, added to the right-hand side of the balance above.
    mechanical_in_j: float = 0.0


@dataclass(frozen=True)
class BodyMechanics:
    """What heat, composition and burning have done to what one body can carry.

    By a DECLARED LAW PER MATERIAL (docs/thermal-mechanics.md): oak by EN
    1995-1-2's softwood curves, iron by EN 1993-1-2's carbon steel, concrete by
    EN 1992-1-2; `law` is "" for a material with none, which heat does not
    change. The section is across the body's longest axis, and at most three
    rings: what burned away, the surface layer (char once past 300 degC), the
    core. Every factor is against the same section cold -- 1 is as it was -- and
    the *_if_cooled ones are what it would keep if it cooled now.
    """
    name: str
    material: str
    law: str
    provenance: str
    tracked: bool
    surface_k: float
    core_k: float
    peak_surface_k: float
    peak_core_k: float
    remaining_fraction: float
    composition_factor: float
    dimensions_m: tuple[float, float, float]
    section_m: tuple[float, float]
    consumed_m: float
    char_m: float
    layer_m: float
    sound_section_m: tuple[float, float]
    stiffness: float
    tension: float
    compression: float
    shear: float
    bending: float
    tension_if_cooled: float
    shear_if_cooled: float
    bending_if_cooled: float
    supported: bool
    # ---- ABI 21: one material state (docs/thermal-mechanics.md) ------------
    # The box its matter is measured against (as authored; `dimensions_m` is
    # this box) and the part of it not burned away, which is what collides and
    # what is drawn; the rigid body it is now; its cells; and what a fracture
    # run gives its lattice -- the weakest and mean tension factor over its
    # bonds and their mean stiffness factor, 1 cold -- from the same state.
    # bending_compression is the compression side of the section, which the
    # load survey reads beside the tension side (`bending`): the weaker governs.
    bending_compression: float = 1.0
    bending_compression_if_cooled: float = 1.0
    reference_m: tuple[float, float, float] = (0.0, 0.0, 0.0)
    remaining_m: tuple[float, float, float] = (0.0, 0.0, 0.0)
    remaining_volume_m3: float = 0.0
    mass_kg: float = 0.0
    inertia_kg_m2: tuple[float, float, float] = (0.0, 0.0, 0.0)
    cells: int = 0
    cells_burned: int = 0
    bond_tension_min: float = 1.0
    bond_tension_mean: float = 1.0
    bond_stiffness_mean: float = 1.0
    revision: int = 0


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
    lib.banjo_fix_one_way.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p,
                                      ctypes.c_double * 3, ctypes.c_double * 3,
                                      ctypes.c_double, ctypes.c_double]
    lib.banjo_fix_one_way.restype = ctypes.c_int
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
    # ABI 23: machines -- stores of energy, motors on pins, and drums.
    lib.banjo_make_energy_store.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p,
                                            ctypes.c_double, ctypes.c_double, ctypes.c_double,
                                            ctypes.c_double]
    lib.banjo_make_energy_store.restype = ctypes.c_int
    lib.banjo_energy_store_count.argtypes = [ctypes.c_void_p]
    lib.banjo_energy_store_count.restype = ctypes.c_int
    lib.banjo_energy_stores.argtypes = [ctypes.c_void_p, ctypes.POINTER(_EnergyStore), ctypes.c_int]
    lib.banjo_energy_stores.restype = ctypes.c_int
    lib.banjo_make_motor.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint,
                                     ctypes.c_double, ctypes.c_double, ctypes.c_double]
    lib.banjo_make_motor.restype = ctypes.c_int
    lib.banjo_drive_motor.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_double, ctypes.c_int]
    lib.banjo_drive_motor.restype = ctypes.c_int
    lib.banjo_motor_count.argtypes = [ctypes.c_void_p]
    lib.banjo_motor_count.restype = ctypes.c_int
    lib.banjo_motors.argtypes = [ctypes.c_void_p, ctypes.POINTER(_Motor), ctypes.c_int]
    lib.banjo_motors.restype = ctypes.c_int
    lib.banjo_make_circuit.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    lib.banjo_make_circuit.restype = ctypes.c_int
    lib.banjo_circuit_switch.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_char_p, ctypes.c_int]
    lib.banjo_circuit_switch.restype = ctypes.c_int
    lib.banjo_circuits.argtypes = [ctypes.c_void_p]
    lib.banjo_circuits.restype = ctypes.c_char_p
    lib.banjo_inertia_about.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_double * 3,
                                        ctypes.POINTER(ctypes.c_double)]
    lib.banjo_inertia_about.restype = ctypes.c_int
    lib.banjo_drum.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p,
                               ctypes.c_double * 3, ctypes.c_double * 3, ctypes.c_double,
                               ctypes.c_double * 3, ctypes.c_int, ctypes.c_double, ctypes.c_double]
    lib.banjo_drum.restype = ctypes.c_int
    lib.banjo_drum_rope_count.argtypes = [ctypes.c_void_p]
    lib.banjo_drum_rope_count.restype = ctypes.c_int
    lib.banjo_drum_ropes.argtypes = [ctypes.c_void_p, ctypes.POINTER(_DrumRope), ctypes.c_int]
    lib.banjo_drum_ropes.restype = ctypes.c_int
    # ABI 24: a machine's controller.
    lib.banjo_make_control.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint, ctypes.c_uint,
                                       ctypes.c_double, ctypes.c_double]
    lib.banjo_make_control.restype = ctypes.c_int
    lib.banjo_operate.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_char_p, ctypes.c_ulonglong,
                                  ctypes.c_int, ctypes.c_int, ctypes.c_double]
    lib.banjo_operate.restype = ctypes.c_int
    lib.banjo_control_count.argtypes = [ctypes.c_void_p]
    lib.banjo_control_count.restype = ctypes.c_int
    lib.banjo_controls.argtypes = [ctypes.c_void_p, ctypes.POINTER(_Control), ctypes.c_int]
    lib.banjo_controls.restype = ctypes.c_int
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
    # ABI 16: heat and strength
    lib.banjo_joint_member.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_char_p]
    lib.banjo_joint_member.restype = ctypes.c_int
    lib.banjo_body_mechanics_count.argtypes = [ctypes.c_void_p]
    lib.banjo_body_mechanics_count.restype = ctypes.c_int
    lib.banjo_bodies_mechanics.argtypes = [ctypes.c_void_p, ctypes.POINTER(_BodyMechanics),
                                           ctypes.c_int]
    lib.banjo_bodies_mechanics.restype = ctypes.c_int
    lib.banjo_mechanics_report.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.banjo_mechanics_report.restype = ctypes.c_char_p
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
    lib.banjo_cut_block.argtypes = [ctypes.c_void_p, ctypes.c_double * 2, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_double, ctypes.POINTER(_Block)]
    lib.banjo_cut_block.restype = ctypes.c_int
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
    lib.banjo_open_snapshot.argtypes = [ctypes.c_char_p, ctypes.c_double, ctypes.c_char_p]
    lib.banjo_open_snapshot.restype = ctypes.c_void_p
    lib.banjo_snapshot.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    lib.banjo_snapshot.restype = ctypes.c_char_p
    lib.banjo_restored.argtypes = [ctypes.c_void_p]
    lib.banjo_restored.restype = ctypes.c_char_p
    lib.banjo_survey.argtypes = [ctypes.c_void_p, ctypes.c_double, ctypes.c_double]
    lib.banjo_survey.restype = ctypes.c_char_p
    lib.banjo_materials.argtypes = []
    lib.banjo_materials.restype = ctypes.c_char_p
    lib.banjo_rolling_report.argtypes = [ctypes.c_void_p]
    lib.banjo_rolling_report.restype = ctypes.c_char_p
    lib.banjo_awake_bodies.argtypes = [ctypes.c_void_p]
    lib.banjo_awake_bodies.restype = ctypes.c_int
    lib.banjo_make_blade.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                                ctypes.c_double * 3, ctypes.c_double * 3, ctypes.c_double * 3,
                                ctypes.c_double, ctypes.c_double, ctypes.c_double,
                                ctypes.c_double * 3]
    lib.banjo_make_blade.restype = ctypes.c_int
    lib.banjo_blade_count.argtypes = [ctypes.c_void_p]
    lib.banjo_blade_count.restype = ctypes.c_int
    lib.banjo_blades.argtypes = [ctypes.c_void_p, ctypes.POINTER(_Blade), ctypes.c_int]
    lib.banjo_blades.restype = ctypes.c_int
    lib.banjo_cut_count.argtypes = [ctypes.c_void_p]
    lib.banjo_cut_count.restype = ctypes.c_int
    lib.banjo_cuts.argtypes = [ctypes.c_void_p, ctypes.POINTER(_Cut), ctypes.c_int]
    lib.banjo_cuts.restype = ctypes.c_int
    lib.banjo_forget_cuts.argtypes = [ctypes.c_void_p]
    lib.banjo_forget_cuts.restype = ctypes.c_int
    # Tools that work the ground (docs/ground-work.md).
    lib.banjo_make_tool_point.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_double * 3,
                                          ctypes.c_double * 3, ctypes.c_double, ctypes.c_double,
                                          ctypes.c_double, ctypes.c_double, ctypes.c_double * 3]
    lib.banjo_make_tool_point.restype = ctypes.c_int
    lib.banjo_tool_point_count.argtypes = [ctypes.c_void_p]
    lib.banjo_tool_point_count.restype = ctypes.c_int
    lib.banjo_tool_points.argtypes = [ctypes.c_void_p, ctypes.POINTER(_ToolPoint), ctypes.c_int]
    lib.banjo_tool_points.restype = ctypes.c_int
    lib.banjo_strike.argtypes = [ctypes.c_void_p, ctypes.POINTER(_StrikeRequest)]
    lib.banjo_strike.restype = ctypes.c_int
    lib.banjo_ground_work_count.argtypes = [ctypes.c_void_p]
    lib.banjo_ground_work_count.restype = ctypes.c_int
    lib.banjo_ground_works.argtypes = [ctypes.c_void_p, ctypes.POINTER(_GroundWork), ctypes.c_int]
    lib.banjo_ground_works.restype = ctypes.c_int
    lib.banjo_forget_ground_work.argtypes = [ctypes.c_void_p]
    lib.banjo_forget_ground_work.restype = ctypes.c_int
    lib.banjo_wield.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_double * 3]
    lib.banjo_wield.restype = ctypes.c_int
    lib.banjo_aim_held.argtypes = [ctypes.c_void_p, ctypes.c_double * 4]
    lib.banjo_aim_held.restype = ctypes.c_int
    lib.banjo_hand_strength.argtypes = [ctypes.c_void_p, ctypes.c_double]
    lib.banjo_hand_strength.restype = ctypes.c_int
    lib.banjo_hand_mass.argtypes = [ctypes.c_void_p, ctypes.c_double]
    lib.banjo_hand_mass.restype = ctypes.c_int
    # The hand's own motions and their previews.
    lib.banjo_stroke.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_double), ctypes.c_int,
                                 ctypes.c_double, ctypes.c_double, ctypes.c_double,
                                 ctypes.c_int, ctypes.c_double]
    lib.banjo_stroke.restype = ctypes.c_int
    lib.banjo_cancel_stroke.argtypes = [ctypes.c_void_p]
    lib.banjo_cancel_stroke.restype = ctypes.c_int
    lib.banjo_hand_state.argtypes = [ctypes.c_void_p, ctypes.POINTER(_Hand)]
    lib.banjo_hand_state.restype = ctypes.c_int
    lib.banjo_preview_flight.argtypes = [ctypes.c_void_p, ctypes.c_double * 3,
                                         ctypes.c_double * 3, ctypes.c_double, ctypes.c_char_p,
                                         ctypes.POINTER(ctypes.c_double), ctypes.c_int,
                                         ctypes.POINTER(_Flight)]
    lib.banjo_preview_flight.restype = ctypes.c_int
    lib.banjo_preview_stroke.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_double),
                                         ctypes.c_int, ctypes.c_double, ctypes.c_double,
                                         ctypes.c_double, ctypes.c_double, ctypes.c_double,
                                         ctypes.POINTER(ctypes.c_double), ctypes.c_int,
                                         ctypes.POINTER(_StrokePreview)]
    lib.banjo_preview_stroke.restype = ctypes.c_int
    lib.banjo_hand_torque.argtypes = [ctypes.c_void_p, ctypes.c_double]
    lib.banjo_hand_torque.restype = ctypes.c_int

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
                 library_path: str | os.PathLike[str] | None = None,
                 snapshot: dict[str, Any] | str | None = None) -> None:
        self._lib = library(library_path)
        # Why the last snapshot() was refused, in words.
        self.last_refusal = ""
        text = scene if isinstance(scene, str) else json.dumps(scene)
        if snapshot is None:
            handle = self._lib.banjo_open(text.encode("utf-8"), float(cell_size_m))
        else:
            # The scene opened again from a saved world (banjo_open_snapshot);
            # restored() says what came back.
            saved = snapshot if isinstance(snapshot, str) else json.dumps(snapshot)
            handle = self._lib.banjo_open_snapshot(text.encode("utf-8"), float(cell_size_m),
                                                   saved.encode("utf-8"))
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
            length_m: float = 0.0, breaking_tension_n: float = 0.0,
            member: str | None = None) -> int:
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

        `member`, one of the two names, says what the link is MADE of (see
        `joint_member`): a rope segment that heat can burn through.

        Returns the joint's id.
        """
        one = (ctypes.c_double * 3)(*(float(v) for v in at_a_m))
        two = (ctypes.c_double * 3)(*(float(v) for v in at_b_m))
        joint = self._check(
            self._lib.banjo_tie(self._alive(), a.encode("utf-8"), b.encode("utf-8"),
                                one, two, length_m, breaking_tension_n),
            f"tying {b!r} to {a!r}")
        if member:
            self.joint_member(joint, member)
        return joint

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
            holds_tension_n: float = 0.0, holds_shear_n: float = 0.0,
            member: str | None = None, comes_off_n: float = 0.0) -> int:
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

        `member`, one of the two names, says what the fixing is MADE of -- the
        peg -- so heat changes what it can take (see `joint_member`). With a
        member a strength of zero is the member's own section strength, not a
        weld.

        With `comes_off_n` above zero it is ONE-WAY along `axis`, which then
        points the way b comes off a: an arrow's nock on a string, a sling's
        ring on its release pin. Pushed back into a, b is in contact and takes
        whatever the push is; pulled along the axis it is held with up to
        `comes_off_n` newtons, and pulled harder it slides off by itself and
        the fixing reports `attached` False. It has no tension strength, so
        `holds_tension_n` must be zero with it.

        Returns the joint's id.
        """
        where = (ctypes.c_double * 3)(*(float(v) for v in at_m))
        along = (ctypes.c_double * 3)(*(float(v) for v in axis))
        if comes_off_n:
            if holds_tension_n:
                raise BanjoError("a one-way fixing has no tension strength: what pulls it "
                                 "off is comes_off_n")
            joint = self._check(
                self._lib.banjo_fix_one_way(self._alive(), a.encode("utf-8"),
                                            b.encode("utf-8"), where, along,
                                            comes_off_n, holds_shear_n),
                f"fixing {b!r} one way to {a!r}")
            if member:
                self.joint_member(joint, member)
            return joint
        joint = self._check(
            self._lib.banjo_fix(self._alive(), a.encode("utf-8"), b.encode("utf-8"),
                                where, along, holds_tension_n, holds_shear_n),
            f"fixing {b!r} to {a!r}")
        if member:
            self.joint_member(joint, member)
        return joint

    def spring(self, a: str, b: str, at_a_m: Any, at_b_m: Any,
               rest_m: float = 0.0, stiffness_n_m: float = 1000.0,
               damping_n_s_m: float = 0.0, member: str | None = None) -> int:
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

        `member`, one of the two names, says what the limb is MADE of: its
        stiffness then follows that body's modulus with temperature, and what
        a softening limb stops holding goes to the thermal ledger as heat.

        Returns the joint's id.
        """
        one = (ctypes.c_double * 3)(*(float(v) for v in at_a_m))
        two = (ctypes.c_double * 3)(*(float(v) for v in at_b_m))
        joint = self._check(
            self._lib.banjo_spring(self._alive(), a.encode("utf-8"), b.encode("utf-8"),
                                   one, two, rest_m, stiffness_n_m, damping_n_s_m),
            f"springing {a!r} to {b!r}")
        if member:
            self.joint_member(joint, member)
        return joint

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
                         strength_pa=out[i].strength_pa,
                         capacity_fraction=out[i].capacity_fraction,
                         why=(out[i].why or b"").decode("utf-8"))
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
                 JOINT_ELASTIC: "elastic", JOINT_DRUM: "drum", JOINT_HINGE: "hinge"}
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
                      comes_off_n=out[i].comes_off_n,
                      rest_m=out[i].rest_m,
                      stiffness_n_m=out[i].stiffness_n_m,
                      damping_n_s_m=out[i].damping_n_s_m,
                      force_n=out[i].force_n,
                      stored_j=out[i].stored_j,
                      member=(out[i].member or b"").decode("utf-8"),
                      rated_tension_n=out[i].rated_tension_n,
                      rated_shear_n=out[i].rated_shear_n,
                      rated_breaks_at_n=out[i].rated_breaks_at_n,
                      rated_stiffness_n_m=out[i].rated_stiffness_n_m,
                      capacity_fraction=out[i].capacity_fraction,
                      rechecks=int(out[i].rechecks),
                      parted_because=(out[i].parted_because or b"").decode("utf-8"),
                      parted_load_n=out[i].parted_load_n,
                      parted_capacity_n=out[i].parted_capacity_n)
                for i in range(written)]

    def joint_friction(self, joint: int, friction: float) -> None:
        """How hard a joint is to move: newton metres for a pin, newtons for a slide."""
        self._check(self._lib.banjo_joint_friction(self._alive(), joint, friction),
                    "stiffening a joint")

    def unhinge(self, joint: int) -> None:
        """Take the pin out. What was hanging on it falls."""
        self._check(self._lib.banjo_unhinge(self._alive(), joint), "taking a pin out")

    # -- machines: stores of energy, motors and drums (ABI 23) ---------------
    def circuit(self, declaration: dict[str, Any]) -> int:
        """Attach a banjo.circuit.v1 network to an existing store and its motors.

        Thermal state, fuse history and switching persist in world snapshots.
        Construction is additive; querying circuits() never resets the machine.
        """
        return self._check(self._lib.banjo_make_circuit(
            self._alive(), json.dumps(declaration, allow_nan=False).encode("utf-8")), "adding a circuit")

    def circuit_switch(self, circuit: int, branch: str, closed: bool) -> None:
        self._check(self._lib.banjo_circuit_switch(self._alive(), circuit, branch.encode("utf-8"),
                                                  int(closed)), "setting a circuit switch")

    def circuits(self) -> list[dict[str, Any]]:
        text = self._lib.banjo_circuits(self._alive())
        if text is None:
            raise RuntimeError("reading circuits failed")
        return json.loads(text.decode("utf-8"))

    def energy_store(self, name: str, body: str, capacity_j: float, charge_j: float,
                     voltage_v: float = 24.0, max_power_w: float = 0.0) -> int:
        """Put a store of energy -- a battery -- in a named body, or in nothing
        (`body` ""): what it can hold and what it holds, in joules; its voltage;
        and the most power it gives, 0 for no limit but its charge. A `name` of
        "" names it "store <id>". Nothing goes back into it but from a declared
        source. Returns the store's id (banjo_make_energy_store)."""
        return self._check(
            self._lib.banjo_make_energy_store(self._alive(), name.encode("utf-8"), body.encode("utf-8"),
                                              float(capacity_j), float(charge_j), float(voltage_v),
                                              float(max_power_w)),
            f"putting a store of energy in {body!r}")

    def energy_stores(self) -> list[EnergyStore]:
        """Every store of energy, with its charge and what it has given."""
        count = self._check(self._lib.banjo_energy_store_count(self._alive()), "counting the stores")
        if count <= 0:
            return []
        out = (_EnergyStore * count)()
        written = self._check(self._lib.banjo_energy_stores(self._alive(), out, count),
                              "reading the stores")
        return [EnergyStore(id=int(s.id), name=(s.name or b"").decode("utf-8"),
                            body=(s.body or b"").decode("utf-8"), capacity_j=s.capacity_j,
                            charge_j=s.charge_j, voltage_v=s.voltage_v, max_power_w=s.max_power_w,
                            given_j=s.given_j, short_j=s.short_j)
                for s in out[:written]]

    def motor(self, joint: int, store: int, stall_torque_n_m: float, no_load_rad_s: float,
              brake_torque_n_m: float = 0.0) -> int:
        """Put a DC motor on a pin (an id from `hinge`), drawing on a store.

        Its line is two numbers a maker gives: the torque it stalls at and the
        speed it runs at unloaded, both at the store's voltage. `brake_torque_n_m`
        is what its brake holds with, 0 for no brake. It starts coasting, told
        nothing. Refused for a joint that is not there or not a pin, a pin with
        a motor already, and a store that is not there. Returns the motor's id
        (banjo_make_motor).
        """
        return self._check(
            self._lib.banjo_make_motor(self._alive(), int(joint), int(store), float(stall_torque_n_m),
                                       float(no_load_rad_s), float(brake_torque_n_m)),
            f"putting a motor on joint {joint}")

    def drive_motor(self, motor: int, command: float, brake: bool = False) -> None:
        """What a motor is told, from the next step on: a command from -1 to 1,
        the share of its store's voltage and which way, and whether its brake
        is on. The brake is friction on the pin, so it holds only while the
        motor is not driving -- a command of 0 -- and holding draws nothing."""
        self._check(self._lib.banjo_drive_motor(self._alive(), int(motor), float(command),
                                                1 if brake else 0),
                    f"telling motor {motor} {command}")

    def motors(self) -> list[Motor]:
        """Every motor: what it is told, what it did in the last kept step, and
        its account since it was made. See `Motor`."""
        count = self._check(self._lib.banjo_motor_count(self._alive()), "counting the motors")
        if count <= 0:
            return []
        out = (_Motor * count)()
        written = self._check(self._lib.banjo_motors(self._alive(), out, count), "reading the motors")
        return [Motor(id=int(m.id), joint=int(m.joint), store=int(m.store),
                      stall_torque_n_m=m.stall_torque_n_m, no_load_rad_s=m.no_load_rad_s,
                      brake_torque_n_m=m.brake_torque_n_m, command=m.command, brake=bool(m.brake),
                      state=(m.state or b"").decode("utf-8"), speed_rad_s=m.speed_rad_s,
                      torque_n_m=m.torque_n_m, current_a=m.current_a, power_w=m.power_w,
                      turned_rad=m.turned_rad, work_j=m.work_j, heat_j=m.heat_j,
                      drawn_j=m.drawn_j, friction_heat_j=m.friction_heat_j)
                for m in out[:written]]

    def control(self, name: str, motor: int, rope: int = 0, top_out_m: float = 0.0,
                bottom_out_m: float = 0.0) -> int:
        """Put a controller on a motor (see `Control`): a hoist's when `rope` is
        a rope on a drum the motor's pin turns, its travel from `top_out_m` to
        `bottom_out_m` of rope out; a shaft's when `rope` is 0. It starts off,
        its motor stopped on its brake, and from then on it works the motor:
        `drive_motor` on that motor tells the controller. Returns its id
        (banjo_make_control)."""
        return self._check(
            self._lib.banjo_make_control(self._alive(), name.encode("utf-8"), int(motor), int(rope),
                                         float(top_out_m), float(bottom_out_m)),
            f"putting a controller on motor {motor}")

    def operate(self, control: int, sender: str = "", seq: int = 0, power: bool | None = None,
                direction: int | None = None, setting: float | None = None) -> bool:
        """Tell a controller what is meant, by a sender and its count: power,
        a direction (-1 lower or reverse, 0 stop, 1 raise or forward) and a
        drive setting (0 to 1), each only if given -- states are said outright,
        never toggled. True if it was applied; False if it was stale, a command
        from `sender` no newer than one already applied from it, and nothing
        changed. A `seq` of 0 is no count, applied as it comes (banjo_operate)."""
        answer = self._check(
            self._lib.banjo_operate(self._alive(), int(control), sender.encode("utf-8"), int(seq),
                                    -1 if power is None else (1 if power else 0),
                                    -2 if direction is None else int(direction),
                                    math.nan if setting is None else float(setting)),
            f"telling controller {control} what to do")
        return answer == 1

    def controls(self) -> list[Control]:
        """Every machine's controller: what it was told, what it has its motor
        doing, what it measured, and what stands in its way. See `Control`."""
        count = self._check(self._lib.banjo_control_count(self._alive()), "counting the controllers")
        if count <= 0:
            return []
        out = (_Control * count)()
        written = self._check(self._lib.banjo_controls(self._alive(), out, count), "reading the controllers")
        return [Control(id=int(c.id), name=(c.name or b"").decode("utf-8"), motor=int(c.motor),
                        rope=int(c.rope), top_out_m=c.top_out_m, bottom_out_m=c.bottom_out_m,
                        forward=int(c.forward), power=bool(c.power), direction=int(c.direction),
                        setting=c.setting, sender=(c.sender or b"").decode("utf-8"), seq=int(c.seq),
                        command=c.command, brake=bool(c.brake), speed_rpm=c.speed_rpm, out_m=c.out_m,
                        rope_speed_m_s=c.rope_speed_m_s, condition=(c.condition or b"").decode("utf-8"))
                for c in out[:written]]

    def inertia_about(self, name: str, axis: Any) -> float:
        """How hard a named thing is to turn about an axis through its centre of
        mass, kg m^2, from the inertia the solver uses: what a motor has to spin
        up. Infinite for anchored scenery, which the solver never turns."""
        out = ctypes.c_double()
        self._check(self._lib.banjo_inertia_about(self._alive(), name.encode("utf-8"), _triple(axis),
                                                  ctypes.byref(out)),
                    f"asking how hard {name!r} is to turn")
        return out.value

    def drum(self, drum: str, load: str, centre_m: Any, axis: Any, radius_m: float,
             load_at_m: Any, winds: int, length_m: float, out_m: float = 0.0) -> int:
        """Hang a named load from a rope that winds onto a drum -- a thing that
        turns on a pin of its own (`hinge`) -- made off on the load at
        `load_at_m`.

        The drum's centre, its axle and the radius the rope lies at are given as
        things stand now. `winds` is +1 if the drum turning the positive way
        about `axis` takes rope on, -1 if the other way does. `length_m` is the
        whole rope; `out_m` is how much of it is off the drum, and 0 means "as
        it hangs": exactly the span from the drum to the load. What is off the
        drum changes by the radius times the turn, for as many turns as there is
        rope, and it pulls and never pushes. Returns the joint's id (banjo_drum);
        `unhinge` takes it off.
        """
        return self._check(
            self._lib.banjo_drum(self._alive(), drum.encode("utf-8"), load.encode("utf-8"),
                                 _triple(centre_m), _triple(axis), float(radius_m), _triple(load_at_m),
                                 int(winds), float(length_m), float(out_m)),
            f"hanging {load!r} from a drum on {drum!r}")

    def drum_ropes(self) -> list[DrumRope]:
        """Every drum's rope: how much is out and on, what it carries, and where
        it leaves the drum and meets the load. See `DrumRope`."""
        count = self._check(self._lib.banjo_drum_rope_count(self._alive()), "counting the drums")
        if count <= 0:
            return []
        out = (_DrumRope * count)()
        written = self._check(self._lib.banjo_drum_ropes(self._alive(), out, count),
                              "reading the drums")
        return [DrumRope(id=int(r.id), drum=(r.drum or b"").decode("utf-8"),
                         load=(r.load or b"").decode("utf-8"), radius_m=r.radius_m,
                         length_m=r.length_m, out_m=r.out_m, wound_m=r.wound_m,
                         tension_n=r.tension_n, centre_m=tuple(r.centre_m), axis=tuple(r.axis),
                         leaves_m=tuple(r.leaves_m), meets_m=tuple(r.meets_m),
                         attached=bool(r.attached), winds=int(r.winds))
                for r in out[:written]]

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
                     anchored=bool(b.anchored), held=bool(b.held), rgba=int(b.rgba),
                     mass_kg=float(b.mass_kg), revision=int(b.revision))
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

    # -- blades (docs/cutting-model.md) -------------------------------------
    def blade(self, body: str, heel_m: Any, tip_m: Any, facing: Any,
              thickness_m: float, edge_radius_m: float = 0.0002,
              bevel_deg: float = 30.0, grip_m: Any = None) -> int:
        """Give a named body an edge. Returns the blade's id.

        Everything is given where it is in the world RIGHT NOW and kept in the
        body's own frame from then on. Both ends of the edge must lie on the
        body's matter; `facing` is squared up against the edge, so roughly
        perpendicular is enough. `edge_radius_m` is how sharp: 0.0002 is a
        working sword edge, 0.00005 a keen one. The grip defaults to the heel.
        """
        grip = heel_m if grip_m is None else grip_m
        return self._check(
            self._lib.banjo_make_blade(self._alive(), body.encode("utf-8"), _triple(heel_m),
                                  _triple(tip_m), _triple(facing), float(thickness_m),
                                  float(edge_radius_m), float(bevel_deg), _triple(grip)),
            f"giving {body!r} an edge")

    def blades(self) -> list[Blade]:
        count = self._check(self._lib.banjo_blade_count(self._alive()), "counting blades")
        if count <= 0:
            return []
        out = (_Blade * count)()
        written = self._check(self._lib.banjo_blades(self._alive(), out, count),
                              "reading blades")
        return [Blade(id=int(b.id), body=(b.body or b"").decode("utf-8"),
                      material=(b.material or b"").decode("utf-8"),
                      heel_m=tuple(b.heel_m), tip_m=tuple(b.tip_m),
                      facing=tuple(b.facing), flat=tuple(b.flat), grip_m=tuple(b.grip_m),
                      thickness_m=b.thickness_m, edge_radius_m=b.edge_radius_m,
                      bevel_deg=b.bevel_deg, cut_area_m2=b.cut_area_m2,
                      cut_work_j=b.cut_work_j, cutting=(b.cutting or b"").decode("utf-8"),
                      attached=bool(b.attached))
                for b in out[:written]]

    def cuts(self) -> list[Cut]:
        """Every edge contact since `forget_cuts`, including those that cut nothing."""
        count = self._check(self._lib.banjo_cut_count(self._alive()), "counting cuts")
        if count <= 0:
            return []
        out = (_Cut * count)()
        written = self._check(self._lib.banjo_cuts(self._alive(), out, count), "reading cuts")
        return [Cut(blade=(c.blade or b"").decode("utf-8"),
                    target=(c.target or b"").decode("utf-8"),
                    kind=(c.kind or b"").decode("utf-8"), at_s=c.at_s,
                    speed_m_s=c.speed_m_s, into_m_s=c.into_m_s, along_m_s=c.along_m_s,
                    across_m_s=c.across_m_s, resistance_j_m2=c.resistance_j_m2,
                    area_m2=c.area_m2, work_j=c.work_j, bonds=int(c.bonds),
                    links=int(c.links), separated=bool(c.separated),
                    pieces=int(c.pieces), open=bool(c.open))
                for c in out[:written]]

    def forget_cuts(self) -> None:
        self._check(self._lib.banjo_forget_cuts(self._alive()), "forgetting cuts")

    # -- tools that work the ground (docs/ground-work.md) --------------------
    def tool_point(self, body: str, tip_m: Any, pointing: Any, width_m: float = 0.04,
                   thickness_m: float = 0.04, angle_deg: float = 30.0, length_m: float = 0.15,
                   grip_m: Any = None) -> int:
        """Give a named body a point that can go into the ground. Returns its id.

        Everything is given where it is in the world RIGHT NOW and kept in the
        body's own frame. The tip has to be at the end of the body's matter and
        `pointing` has to run out of it there. `length_m` is how much of the tool
        is point: the rest of it meets the ground as a surface. From then on the
        body collides as its cells, so a pick's crook is open. The grip defaults
        to the tip.
        """
        grip = tip_m if grip_m is None else grip_m
        return self._check(
            self._lib.banjo_make_tool_point(self._alive(), body.encode("utf-8"), _triple(tip_m),
                                            _triple(pointing), float(width_m), float(thickness_m),
                                            float(angle_deg), float(length_m), _triple(grip)),
            f"giving {body!r} a point")

    def tool_points(self) -> list[ToolPoint]:
        count = self._check(self._lib.banjo_tool_point_count(self._alive()), "counting tool points")
        if count <= 0:
            return []
        out = (_ToolPoint * count)()
        written = self._check(self._lib.banjo_tool_points(self._alive(), out, count),
                              "reading tool points")

        def text(value: bytes | None) -> str:
            return (value or b"").decode("utf-8", "replace")

        return [ToolPoint(id=int(p.id), body=text(p.body), material=text(p.material),
                          tip_m=tuple(p.tip_m), pointing=tuple(p.pointing), grip_m=tuple(p.grip_m),
                          width_m=p.width_m, thickness_m=p.thickness_m, angle_deg=p.angle_deg,
                          length_m=p.length_m, in_=text(p.in_), depth_m=p.depth_m,
                          attached=bool(p.attached))
                for p in out[:written]]

    def strike(self, target_m: Any = None, shoulder_m: Any = None, speed_m_s: float = 4.0,
               raise_deg: float = 0.0, lever: bool = False, lever_deg: float = 40.0,
               give_up_s: float = 2.0) -> None:
        """A bounded tool action with what is wielded: the hand makes it at the
        step's own rate, and what it does to the ground is the ground's.

        A swing brings the tool's point down on `target_m`, a point on the
        ground, turning about `shoulder_m`; `raise_deg` above zero raises it back
        that far first. With `lever`, a point that is in the ground is pried,
        turned `lever_deg` about where it went in, and drawn up out of it.
        `hand()` says how it goes; step the world to let it happen.
        """
        request = _StrikeRequest()
        request.target_m = _triple(target_m if target_m is not None else (0.0, 0.0, 0.0))
        request.shoulder_m = _triple(shoulder_m if shoulder_m is not None else (0.0, 0.0, 0.0))
        request.speed_m_s = float(speed_m_s)
        request.raise_deg = float(raise_deg)
        request.lever = 1 if lever else 0
        request.lever_deg = float(lever_deg)
        request.give_up_s = float(give_up_s)
        self._check(self._lib.banjo_strike(self._alive(), ctypes.byref(request)),
                    "levering" if lever else "swinging")

    def ground_work(self) -> list[GroundWork]:
        """Every meeting of a point with the ground since `forget_ground_work`."""
        count = self._check(self._lib.banjo_ground_work_count(self._alive()), "counting ground work")
        if count <= 0:
            return []
        out = (_GroundWork * count)()
        written = self._check(self._lib.banjo_ground_works(self._alive(), out, count),
                              "reading ground work")

        def text(value: bytes | None) -> str:
            return (value or b"").decode("utf-8", "replace")

        return [GroundWork(point=int(w.point), tool=text(w.tool), ground=text(w.ground),
                           kind=text(w.kind), supported=bool(w.supported), why=text(w.why),
                           at_s=w.at_s, at_m=tuple(w.at_m), closing_speed_m_s=w.closing_speed_m_s,
                           depth_m=w.depth_m, sideways_m=w.sideways_m, impulse_n_s=w.impulse_n_s,
                           peak_force_n=w.peak_force_n, work_j=w.work_j,
                           penetration_work_j=w.penetration_work_j,
                           breakout_work_j=w.breakout_work_j, resistance_n=w.resistance_n,
                           passive_n=w.passive_n, loosened_sand_m3=w.loosened_sand_m3,
                           loosened_soil_m3=w.loosened_soil_m3, loosened_kg=w.loosened_kg,
                           tool_whole=bool(w.tool_whole), tool_dent_m=w.tool_dent_m,
                           model=text(w.model), open=bool(w.open),
                           dug=({"from_m": [w.dug_from_m[0], w.dug_from_m[1]],
                                 "to_m": [w.dug_to_m[0], w.dug_to_m[1]],
                                 "width_m": w.dug_width_m, "depth_m": w.dug_depth_m}
                                if w.dug else None))
                for w in out[:written]]

    def forget_ground_work(self) -> None:
        self._check(self._lib.banjo_forget_ground_work(self._alive()), "forgetting ground work")

    # -- the grip ---------------------------------------------------------
    def wield(self, name: str, grip_m: Any) -> None:
        """Take hold of a body at a point on it, with a bounded force and torque.

        Not `grab`: `grab` carries a loose body exactly where it is put, which is
        placement. A wielded body is pulled and turned towards where the hand
        wants it -- `move_held` and `aim_held` -- with what the hand has, and
        what it meets can slow it, turn it aside or stop it.
        """
        self._check(self._lib.banjo_wield(self._alive(), name.encode("utf-8"), _triple(grip_m)),
                    f"taking hold of {name}")

    def aim_held(self, orientation_wxyz: Any) -> None:
        values = [float(v) for v in orientation_wxyz]
        if len(values) != 4:
            raise BanjoError("an orientation is four numbers, w first")
        self._check(self._lib.banjo_aim_held(self._alive(), (ctypes.c_double * 4)(*values)),
                    "turning the hand")

    def hand_strength(self, newtons: float) -> None:
        self._check(self._lib.banjo_hand_strength(self._alive(), float(newtons)),
                    "setting the hand's strength")

    def hand_torque(self, newton_metres: float) -> None:
        self._check(self._lib.banjo_hand_torque(self._alive(), float(newton_metres)),
                    "setting the hand's torque")

    def hand_mass(self, kilograms: float) -> None:
        """The moving mass of the hand and arm: what the strength has to get
        going along with whatever a stroke throws. 2 kg unless told otherwise,
        a demonstration value."""
        self._check(self._lib.banjo_hand_mass(self._alive(), float(kilograms)),
                    "setting the hand's moving mass")

    # -- the hand's own motions (docs/interaction-profiles.md) ---------------
    @staticmethod
    def _path(path_m: Any) -> tuple[Any, int]:
        points = [list(p) for p in path_m]
        if not 2 <= len(points) <= 16 or any(len(p) != 3 for p in points):
            raise BanjoError("a stroke's path is two to sixteen points of three numbers")
        values = [float(v) for p in points for v in p]
        return (ctypes.c_double * len(values))(*values), len(points)

    def stroke(self, path_m: Any, speed_m_s: float, accel_m_s2: float, lead_m: float = 0.05,
               let_go: bool = False, give_up_s: float = 2.0) -> None:
        """A motion the hand makes by itself, at the step's own rate.

        Where the hand wants the grip travels along `path_m` (two to sixteen
        points) at up to `speed_m_s`, getting there at `accel_m_s2` -- and no
        faster than the strength can move the hand and the thing together --
        never more than `lead_m` ahead of the grip. The hand pulls with what it
        has, so a heavy thing falls behind and a light one keeps up: nothing
        gives the body a speed. With `let_go` the hand opens when the GRIP
        reaches the end, which is a throw. Needs something wielded, or hauled
        because it is attached; `move_held` takes the hand back.
        """
        flat, count = self._path(path_m)
        self._check(self._lib.banjo_stroke(self._alive(), flat, count, float(speed_m_s),
                                           float(accel_m_s2), float(lead_m),
                                           1 if let_go else 0, float(give_up_s)),
                    "making a stroke")

    def cancel_stroke(self) -> None:
        self._check(self._lib.banjo_cancel_stroke(self._alive()), "stopping a stroke")

    def hand(self) -> Hand:
        """What the hand is doing, and what it has done."""
        out = _Hand()
        self._check(self._lib.banjo_hand_state(self._alive(), ctypes.byref(out)),
                    "reading the hand")

        def text(value: bytes | None) -> str:
            return (value or b"").decode("utf-8", "replace")

        return Hand(holding=text(out.holding), mode=text(out.mode),
                    target_m=tuple(out.target_m), grip_m=tuple(out.grip_m),
                    grip_velocity_m_s=tuple(out.grip_velocity_m_s), force_n=tuple(out.force_n),
                    work_j=out.work_j, stroking=bool(out.stroking),
                    stroke_along_m=out.stroke_along_m, stroke_length_m=out.stroke_length_m,
                    stroke_ended=text(out.stroke_ended), let_go_body=text(out.let_go_body),
                    let_go_velocity_m_s=tuple(out.let_go_velocity_m_s),
                    let_go_at_s=out.let_go_at_s, let_go_work_j=out.let_go_work_j)

    # The engine writes a point every 1/60 s for at most ten seconds.
    _MOST_FLIGHT_POINTS = 601

    @staticmethod
    def _flight(out: Any, points: Any) -> Flight:
        return Flight(points_m=tuple((points[3 * i], points[3 * i + 1], points[3 * i + 2])
                                     for i in range(out.points)),
                      hit=bool(out.hit),
                      hit_name=(out.hit_name or b"").decode("utf-8", "replace"),
                      hit_point_m=tuple(out.hit_point_m), hit_after_s=out.hit_after_s,
                      hit_speed_m_s=out.hit_speed_m_s)

    def preview_flight(self, from_m: Any, velocity_m_s: Any, horizon_s: float = 3.0,
                       ignoring: str = "") -> Flight:
        """Where something would go, stepped as the solver steps it, against the
        solver's own shapes, never meeting the body named `ignoring` -- the thing
        itself, still in the hand, whose damping it flies with. Changes nothing."""
        points = (ctypes.c_double * (3 * self._MOST_FLIGHT_POINTS))()
        out = _Flight()
        self._check(self._lib.banjo_preview_flight(self._alive(), _triple(from_m),
                                                   _triple(velocity_m_s), float(horizon_s),
                                                   ignoring.encode("utf-8"), points,
                                                   self._MOST_FLIGHT_POINTS, ctypes.byref(out)),
                    "previewing a flight")
        return self._flight(out, points)

    def preview_stroke(self, path_m: Any, speed_m_s: float, accel_m_s2: float,
                       lead_m: float = 0.05, give_up_s: float = 2.0,
                       horizon_s: float = 3.0) -> StrokePreview:
        """What this stroke would do to what the hand holds -- the body alone,
        pulled by this hand along the path under gravity -- and where it would
        fly once let go at the end. Changes nothing."""
        flat, count = self._path(path_m)
        points = (ctypes.c_double * (3 * self._MOST_FLIGHT_POINTS))()
        out = _StrokePreview()
        self._check(self._lib.banjo_preview_stroke(self._alive(), flat, count, float(speed_m_s),
                                                   float(accel_m_s2), float(lead_m),
                                                   float(give_up_s), float(horizon_s), points,
                                                   self._MOST_FLIGHT_POINTS, ctypes.byref(out)),
                    "previewing a stroke")
        return StrokePreview(possible=bool(out.possible),
                             why=(out.why or b"").decode("utf-8", "replace"),
                             reaches_end=bool(out.reaches_end), stroke_s=out.stroke_s,
                             work_j=out.work_j, let_go_at_m=tuple(out.let_go_at_m),
                             let_go_velocity_m_s=tuple(out.let_go_velocity_m_s),
                             flight=self._flight(out.flight, points))

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

    # -- heat and strength (ABI 16) ----------------------------------------
    def joint_member(self, joint: int, member: str) -> None:
        """Say which of a joint's two bodies it is MADE of.

        Its strength (a fixing, a link) or stiffness (an elastic) then follows
        that body's material law, temperature and what is left of it. A
        declared strength of zero becomes the member's own section times its
        material's strength -- so with a member, zero is no longer a weld. ""
        goes back to the declared numbers. Refused for a pin, a slide or a
        pulley, and for a name that is not one of the joint's two ends.
        """
        self._check(self._lib.banjo_joint_member(self._alive(), int(joint), member.encode("utf-8")),
                    f"making joint {joint} of {member!r}")

    def body_mechanics(self) -> list[BodyMechanics]:
        """What heat has done to every body the thermal network holds, and to
        every body a joint is made of. See `BodyMechanics`."""
        handle = self._alive()
        count = self._check(self._lib.banjo_body_mechanics_count(handle),
                            "counting what heat has changed")
        if count <= 0:
            return []
        buffer = (_BodyMechanics * count)()
        written = self._check(self._lib.banjo_bodies_mechanics(handle, buffer, count),
                              "reading what heat has changed")
        return [BodyMechanics(name=(m.name or b"").decode("utf-8", "replace"),
                              material=(m.material or b"").decode("utf-8", "replace"),
                              law=(m.law or b"").decode("utf-8", "replace"),
                              provenance=(m.provenance or b"").decode("utf-8", "replace"),
                              tracked=bool(m.tracked), surface_k=m.surface_k, core_k=m.core_k,
                              peak_surface_k=m.peak_surface_k, peak_core_k=m.peak_core_k,
                              remaining_fraction=m.remaining_fraction,
                              composition_factor=m.composition_factor,
                              dimensions_m=tuple(m.dimensions_m), section_m=tuple(m.section_m),
                              consumed_m=m.consumed_m, char_m=m.char_m, layer_m=m.layer_m,
                              sound_section_m=tuple(m.sound_section_m), stiffness=m.stiffness,
                              tension=m.tension, compression=m.compression, shear=m.shear,
                              bending=m.bending, tension_if_cooled=m.tension_if_cooled,
                              shear_if_cooled=m.shear_if_cooled,
                              bending_if_cooled=m.bending_if_cooled, supported=bool(m.supported),
                              bending_compression=m.bending_compression,
                              bending_compression_if_cooled=m.bending_compression_if_cooled,
                              reference_m=tuple(m.reference_m), remaining_m=tuple(m.remaining_m),
                              remaining_volume_m3=m.remaining_volume_m3, mass_kg=m.mass_kg,
                              inertia_kg_m2=tuple(m.inertia_kg_m2), cells=int(m.cells),
                              cells_burned=int(m.cells_burned),
                              bond_tension_min=m.bond_tension_min,
                              bond_tension_mean=m.bond_tension_mean,
                              bond_stiffness_mean=m.bond_stiffness_mean,
                              revision=int(m.revision))
                for m in buffer[:written]]

    def mechanics_report(self, with_laws: bool = False) -> dict[str, Any]:
        """Heat and strength as the engine says it: the bodies, every joint made
        of a member with what it carries against what it can take, and with
        `with_laws` the laws, their sources and what is not modelled."""
        text = self._lib.banjo_mechanics_report(self._alive(), int(bool(with_laws))) or b"{}"
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

    def cut_block(self, at_m: Any, cells: tuple[int, int] = (4, 4), height_m: float = 0.4) -> Block:
        """Cut a block `height_m` tall out of bare rock. The ground loses it now;
        add it as a body -- with {"cut": {"at_m", "cells", "height_m"}} in the
        scene's edits -- in the world opened next. (Not a blade's cut: those
        are `cuts()`.)"""
        out = _Block()
        self._check(self._lib.banjo_cut_block(self._alive(), _xz(at_m), int(cells[0]), int(cells[1]),
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

    def snapshot(self, spec_digest: str = "") -> dict[str, Any] | None:
        """The whole of the world as it stands (banjo_snapshot), for
        World(scene, snapshot=...) once this one has gone. None while something
        is under way that a saved world cannot carry, with why in last_refusal."""
        text = self._lib.banjo_snapshot(self._alive(), spec_digest.encode("utf-8"))
        if not text:
            self.last_refusal = self._error()
            return None
        self.last_refusal = ""
        return json.loads(text.decode("utf-8"))

    def restored(self) -> dict[str, Any]:
        """What opening from a saved world gave back (banjo_restored): its tier,
        why it is not whole, what a saved world does not carry yet."""
        text = self._lib.banjo_restored(self._alive()) or b"{}"
        return json.loads(text.decode("utf-8"))

    def survey(self, x_m: float, z_m: float) -> dict[str, Any]:
        """Ground and water at a point."""
        text = self._lib.banjo_survey(self._alive(), float(x_m), float(z_m)) or b"{}"
        return json.loads(text.decode("utf-8"))

    def rolling_report(self) -> dict[str, Any]:
        """What rolling resistance is doing: every contact of a round body in the
        last step, with the solver's normal force, the pair's coefficient and
        whether the ball is held still, and the energy it has taken out of the
        motion, in all ("loss_j") and by ball."""
        text = self._lib.banjo_rolling_report(self._alive()) or b"{}"
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


def materials() -> dict[str, Any]:
    """The materials, the floor and the ground's surfaces, each with its friction
    and its own share of rolling resistance (a ball on a surface is resisted
    with its own share plus the surface's), whether that is sourced or a
    demonstration value, and where it came from -- without opening a world."""
    return json.loads((library().banjo_materials() or b"{}").decode("utf-8"))
