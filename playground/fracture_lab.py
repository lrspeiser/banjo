"""Fracture lab: instant reruns of the fast fracture lanes on a thin plate.

The owner's test: change the plate's dimensions or the ball's drop height and
see the plate break in 3D again at once. Each lane is a native executable that
follows one CLI contract (plate, cell, ball, drop or speed, offset, support,
duration, output) and writes a banjo.playback.v1 recording whose `report`
carries the lane's own timing. This module maps the panel's parameters to that
contract, runs the executable synchronously under a timeout, registers the
recording as a playground job exactly as scripts/import-playback.py does, and
returns what the panel shows.

The explicit lattice (`banjo_fast_lattice_run`) is offered as the reference
lane so the panel works before the fast lanes exist; it is a comparison
instrument, capped at a few hundred cells and timed, not the product path.

Nothing here changes any solver, criterion or tolerance.
"""
from __future__ import annotations

import json
import math
import re
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

GRAVITY_M_S2 = 9.81
REALTIME_LIMIT = 1.1

# Lanes, in the order the panel lists them. `exe` is looked up next to the
# engine binary; a lane whose executable is absent is shown but disabled.
ALGORITHMS: dict[str, dict[str, Any]] = {
    "algo1": {"exe": "banjo_fracture_algo1", "title": "Algorithm 1: impulse library + Woodbury crack updates",
              "max_cells": 4000, "timeout_s": 60, "contract": "lane"},
    "algo2": {"exe": "banjo_fracture_algo2", "title": "Algorithm 2: Griffith event cascade (no time stepping)",
              "max_cells": 4000, "timeout_s": 60, "contract": "lane"},
    "algo3": {"exe": "banjo_fracture_algo3", "title": "Algorithm 3: precomputed propagators + causal cones (exact)",
              "max_cells": 4000, "timeout_s": 60, "contract": "lane"},
    "lattice": {"exe": "banjo_fast_lattice_run", "title": "Explicit lattice, parallel: every substep, the shared criterion",
                "max_cells": 16000, "timeout_s": 300, "contract": "fast_lattice"},
}

MATERIALS = ("glass", "oak", "iron")
# The strain threshold is what every result before 2026-09-08 used; the
# energy-scaled law derives the critical stretch from the declared fracture
# energy, the horizon and the cell size, so a crack costs the same per unit
# area at every resolution (docs/criterion-energy-scaled-checkpoint.md).
FAILURE_LAWS = ("strain-threshold", "energy-scaled")
# Plastic flow is off by default: with it off every earlier measurement
# reproduces exactly, and the materials that declare a yield strength (iron
# and, as the catalogue actually has it, oak) only deform when it is asked for.
PLASTICITY = ("off", "on")
# Re-fracture after the rigid handoff is off by default, exactly as plastic flow
# is: with it off the lane is what it was, bit for bit, and the panel's existing
# scenarios reproduce their measured numbers.
REFRACTURE = ("off", "on")
SUPPORTS = ("ledges", "flat", "clamped")

DEFAULT: dict[str, Any] = {
    "algorithm": "lattice",
    "material": "glass",
    "failure_law": "strain-threshold",
    "plasticity": "off",
    "clearance_m": 0.5,
    # Empty means the plate-and-ball scene. A non-empty list is a many-object
    # scene and the plate and ball fields below are not read at all.
    "bodies": [],
    "striker": "iron",
    "plate_m": [0.25, 0.20, 0.01],
    "cell_m": 0.01,
    "ball_m": 0.06,
    "drop_m": 2.0,
    "speed_m_s": None,
    "offset_m": [0.0, 0.0],
    "support": "ledges",
    "duration_s": 2.0,
    # The second strike. `second_speed_m_s` 0 means there is no second ball and
    # no flag is passed, so the command line is what it has always been.
    "refracture": "off",
    "second_speed_m_s": 0.0,
    "second_ball_m": 0.1,
    "second_offset_m": [0.0, 0.0],
    # How long to wait for the first strike's pieces to come to rest before
    # dropping the second ball anyway.
    "second_wait_s": 1.0,
}

# Every scenario here has been run and its headline measured, so the panel can
# offer a whole setup in one click and say what it did before it is run again.
# `expect` is what was measured on 2026-09-08, not a promise about this run.
SCENARIOS = [
    {"id": "glass-pane", "title": "1 m glass pane shatters",
     "expect": "38 pieces, 0.18x realtime",
     "spec": {"material": "glass", "striker": "iron", "failure_law": "strain-threshold", "plasticity": "off",
              "plate_m": [1.0, 1.0, 0.0625], "cell_m": 0.0625, "ball_m": 0.3, "speed_m_s": 20.0,
              "offset_m": [0.0, 0.0], "support": "ledges", "duration_s": 2.0, "clearance_m": 1.5}},
    {"id": "oak-pane-rest", "title": "1 m oak pane, breaks into boards and settles",
     "expect": "25 pieces, comes to rest, 0.15x realtime",
     "spec": {"material": "oak", "striker": "iron", "failure_law": "energy-scaled", "plasticity": "off",
              "plate_m": [1.0, 1.0, 0.0625], "cell_m": 0.0625, "ball_m": 0.3, "speed_m_s": 20.0,
              "offset_m": [0.0, 0.0], "support": "ledges", "duration_s": 2.0, "clearance_m": 1.5}},
    {"id": "glass-pulverise", "title": "The same glass pane under the energy-scaled law",
     "expect": "190 pieces, largest 8 cells: glass is deep in the pulverisation regime",
     "spec": {"material": "glass", "striker": "iron", "failure_law": "energy-scaled", "plasticity": "off",
              "plate_m": [1.0, 1.0, 0.0625], "cell_m": 0.0625, "ball_m": 0.3, "speed_m_s": 20.0,
              "offset_m": [0.0, 0.0], "support": "ledges", "duration_s": 2.0, "clearance_m": 1.5}},
    {"id": "glass-plate", "title": "250 mm glass plate, 500 cells",
     "expect": "49 pieces, 0.99x realtime",
     "spec": {"material": "glass", "striker": "iron", "failure_law": "strain-threshold", "plasticity": "off",
              "plate_m": [0.25, 0.20, 0.01], "cell_m": 0.01, "ball_m": 0.06, "drop_m": 2.0,
              "offset_m": [0.0, 0.0], "support": "ledges", "duration_s": 2.0, "clearance_m": 0.5}},
    # The pair that shows what a cell through the thickness is worth. Same pane,
    # same tap, only the cell size differs. Measured 2026-09-08: 5.10 mm of
    # centre deflection at one layer against 0.91 mm at two, neither breaking a
    # bond. Beam theory puts the surface strain at one layer 16x above what the
    # criterion reads there, because one layer of nodes sits on the mid-plane
    # where bending strain is zero. See docs/one-cell-is-not-a-plate.md.
    # Many-object scenes. Every object here is lattice: the ball that falls can
    # dent and break like the thing it lands on, which the rigid striker never
    # could. Cell size is shared, because the solver's contact radius is one
    # number for the whole lattice. Only the three materials this lane has
    # measured appear: glass, oak and iron.
    # The scene the tilt, the anchor and the seating were built for. The lane is
    # held in place and tilted six degrees; every pin and the ball name it as
    # what they stand on and are seated on its surface, which is a different
    # height for each of them along the slope. The ball is released at rest and
    # rolls: measured 1.2 per cent slip on an 8 degree ramp and an acceleration
    # of 0.97 m/s^2 against the 0.974 a rolling solid sphere gives.
    # A bowl, which union alone cannot make: an oak sphere with a smaller sphere
    # and a lid cut out of it, all three in one join group. Anchored, so it is
    # scenery, and anchored scenery collides as its own cells rather than as a
    # convex hull, which is what lets a bead fall into it instead of landing on
    # the rim.
    {"id": "scene-bowl", "title": "Three beads dropped into a bowl",
     "expect": "a hollow bowl cut from a sphere; the beads fall in and settle in the bottom",
     "spec": {"algorithm": "lattice", "failure_law": "strain-threshold", "plasticity": "off",
              "cell_m": 0.02, "duration_s": 2.5, "bodies": [
              {"name": "bowl", "shape": "sphere", "material": "oak", "size_mm": [400, 400, 400], "center_mm": [0, 200, 0], "join": "bowl", "anchored": True},
              {"name": "cavity", "shape": "sphere", "material": "oak", "size_mm": [320, 320, 320], "center_mm": [0, 220, 0], "join": "bowl", "subtract": True},
              {"name": "open top", "shape": "box", "material": "oak", "size_mm": [600, 200, 600], "center_mm": [0, 420, 0], "join": "bowl", "subtract": True},
              {"name": "glass bead", "shape": "sphere", "material": "glass", "size_mm": [60, 60, 60], "center_mm": [-110, 460, 0], "velocity_m_s": [0.5, 0.0, 0.0]},
              {"name": "oak bead", "shape": "sphere", "material": "oak", "size_mm": [60, 60, 60], "center_mm": [110, 460, 0], "velocity_m_s": [-0.5, 0.0, 0.0]},
              {"name": "iron bead", "shape": "sphere", "material": "iron", "size_mm": [60, 60, 60], "center_mm": [0, 460, -110], "velocity_m_s": [0.0, 0.0, 0.5]}]}},
    {"id": "scene-alley", "title": "A bowling alley on a tilted lane",
     "expect": "the ball is released at rest at the top and rolls the length of the lane into the pins",
     "spec": {"algorithm": "lattice", "failure_law": "strain-threshold", "plasticity": "off",
              "cell_m": 0.02, "duration_s": 2.5, "bodies": [{"name": "lane", "shape": "box", "material": "oak", "size_mm": [2000, 60, 300], "center_mm": [0, 220, 0], "rotation_deg": [0, 0, -6], "anchored": True},
              {"name": "pin1", "shape": "box", "material": "glass", "size_mm": [40, 120, 40], "center_mm": [680, 0, 0], "rest_on": "lane"},
              {"name": "pin2", "shape": "box", "material": "glass", "size_mm": [40, 120, 40], "center_mm": [760, 0, -50], "rest_on": "lane"},
              {"name": "pin3", "shape": "box", "material": "glass", "size_mm": [40, 120, 40], "center_mm": [760, 0, 50], "rest_on": "lane"},
              {"name": "pin4", "shape": "box", "material": "glass", "size_mm": [40, 120, 40], "center_mm": [840, 0, -100], "rest_on": "lane"},
              {"name": "pin5", "shape": "box", "material": "glass", "size_mm": [40, 120, 40], "center_mm": [840, 0, 0], "rest_on": "lane"},
              {"name": "pin6", "shape": "box", "material": "glass", "size_mm": [40, 120, 40], "center_mm": [840, 0, 100], "rest_on": "lane"},
              {"name": "pin7", "shape": "box", "material": "glass", "size_mm": [40, 120, 40], "center_mm": [920, 0, -150], "rest_on": "lane"},
              {"name": "pin8", "shape": "box", "material": "glass", "size_mm": [40, 120, 40], "center_mm": [920, 0, -50], "rest_on": "lane"},
              {"name": "pin9", "shape": "box", "material": "glass", "size_mm": [40, 120, 40], "center_mm": [920, 0, 50], "rest_on": "lane"},
              {"name": "pin10", "shape": "box", "material": "glass", "size_mm": [40, 120, 40], "center_mm": [920, 0, 150], "rest_on": "lane"},
              {"name": "ball", "shape": "sphere", "material": "iron", "size_mm": [100, 100, 100], "center_mm": [-700, 0, 0], "rest_on": "lane"}]}},
    {"id": "scene-shelf", "title": "A ball dropped on a glass shelf between two piers",
     "expect": "255 bonds broken, 45 pieces: the shelf gives way under the ball and the oak block rides it down",
     "spec": {"algorithm": "lattice", "failure_law": "strain-threshold", "plasticity": "off",
              "cell_m": 0.02, "duration_s": 1.0, "bodies": [{"name": "left pier", "shape": "box", "material": "iron", "size_mm": [60, 80, 160], "center_mm": [-90, 40, 0], "velocity_m_s": [0.0, 0.0, 0.0]},
              {"name": "right pier", "shape": "box", "material": "iron", "size_mm": [60, 80, 160], "center_mm": [90, 40, 0], "velocity_m_s": [0.0, 0.0, 0.0]},
              {"name": "glass shelf", "shape": "box", "material": "glass", "size_mm": [240, 20, 160], "center_mm": [0, 90, 0], "velocity_m_s": [0.0, 0.0, 0.0]},
              {"name": "oak block", "shape": "box", "material": "oak", "size_mm": [60, 60, 60], "center_mm": [-80, 130, 40], "velocity_m_s": [0.0, 0.0, 0.0]},
              {"name": "iron ball", "shape": "sphere", "material": "iron", "size_mm": [60, 60, 60], "center_mm": [20, 132, 0], "velocity_m_s": [0.0, -12.0, 0.0]}]}},
    {"id": "scene-stack", "title": "A tower of oak and glass struck from above",
     "expect": "one drop meets three blocks of two materials in a column",
     "spec": {"algorithm": "lattice", "failure_law": "strain-threshold", "plasticity": "off",
              "cell_m": 0.02, "duration_s": 1.2, "bodies": [{"name": "iron base", "shape": "box", "material": "iron", "size_mm": [200, 40, 160], "center_mm": [0, 20, 0], "velocity_m_s": [0.0, 0.0, 0.0]},
              {"name": "oak block", "shape": "box", "material": "oak", "size_mm": [80, 60, 80], "center_mm": [0, 70, 0], "velocity_m_s": [0.0, 0.0, 0.0]},
              {"name": "glass block", "shape": "box", "material": "glass", "size_mm": [80, 60, 80], "center_mm": [0, 130, 0], "velocity_m_s": [0.0, 0.0, 0.0]},
              {"name": "oak cap", "shape": "box", "material": "oak", "size_mm": [80, 60, 80], "center_mm": [0, 190, 0], "velocity_m_s": [0.0, 0.0, 0.0]},
              {"name": "iron ball", "shape": "sphere", "material": "iron", "size_mm": [80, 80, 80], "center_mm": [10, 262, 0], "velocity_m_s": [0.0, -9.0, 0.0]}]}},
    {"id": "scene-skittles", "title": "A ball rolled sideways into three glass pins",
     "expect": "a horizontal strike: what falls is whatever the ball reaches",
     "spec": {"algorithm": "lattice", "failure_law": "strain-threshold", "plasticity": "off",
              "cell_m": 0.02, "duration_s": 1.2, "bodies": [{"name": "oak floor", "shape": "box", "material": "oak", "size_mm": [400, 40, 240], "center_mm": [0, 20, 0], "velocity_m_s": [0.0, 0.0, 0.0]},
              {"name": "glass pin", "shape": "box", "material": "glass", "size_mm": [40, 120, 40], "center_mm": [-80, 100, 0], "velocity_m_s": [0.0, 0.0, 0.0]},
              {"name": "glass pin", "shape": "box", "material": "glass", "size_mm": [40, 120, 40], "center_mm": [0, 100, 0], "velocity_m_s": [0.0, 0.0, 0.0]},
              {"name": "glass pin", "shape": "box", "material": "glass", "size_mm": [40, 120, 40], "center_mm": [80, 100, 0], "velocity_m_s": [0.0, 0.0, 0.0]},
              {"name": "iron ball", "shape": "sphere", "material": "iron", "size_mm": [80, 80, 80], "center_mm": [-142, 100, 0], "velocity_m_s": [12.0, 0.0, 0.0]}]}},
    {"id": "bend-one-cell", "title": "A gentle tap on a pane one cell thick",
     "expect": "it bows 5.1 mm and springs back unbroken: five times too far, because one layer has no bending stiffness",
     "spec": {"material": "glass", "striker": "iron", "failure_law": "strain-threshold", "plasticity": "off",
              "plate_m": [0.25, 0.20, 0.01], "cell_m": 0.01, "ball_m": 0.06, "speed_m_s": 0.5,
              "offset_m": [0.0, 0.0], "support": "ledges", "duration_s": 0.4, "clearance_m": 0.5}},
    {"id": "bend-two-cells", "title": "The same tap on the same pane, two cells thick",
     "expect": "0.91 mm, eight times stiffer for eight times the cells and sixteen times the wall clock",
     "spec": {"material": "glass", "striker": "iron", "failure_law": "strain-threshold", "plasticity": "off",
              "plate_m": [0.25, 0.20, 0.01], "cell_m": 0.005, "ball_m": 0.06, "speed_m_s": 0.5,
              "offset_m": [0.0, 0.0], "support": "ledges", "duration_s": 0.4, "clearance_m": 0.5}},
    {"id": "glass-punch", "title": "The same plate hit three times as fast",
     "expect": "a local hole instead of a shatter: most of the plate survives",
     "spec": {"material": "glass", "striker": "iron", "failure_law": "strain-threshold", "plasticity": "off",
              "plate_m": [0.25, 0.20, 0.01], "cell_m": 0.01, "ball_m": 0.06, "speed_m_s": 20.0,
              "offset_m": [0.0, 0.0], "support": "ledges", "duration_s": 2.0, "clearance_m": 0.5}},
    {"id": "glass-offcentre", "title": "The same plate struck off centre",
     "expect": "the crack pattern follows the strike, not the geometry",
     "spec": {"material": "glass", "striker": "iron", "failure_law": "strain-threshold", "plasticity": "off",
              "plate_m": [0.25, 0.20, 0.01], "cell_m": 0.01, "ball_m": 0.06, "drop_m": 2.0,
              "offset_m": [0.07, 0.04], "support": "ledges", "duration_s": 2.0, "clearance_m": 0.5}},
    {"id": "bullet-through", "title": "400 m/s through oak: it perforates, it does not bounce",
     "expect": "exits at 371 m/s downward, 3 m of clearance so the floor is out of the way",
     "spec": {"material": "oak", "striker": "iron", "failure_law": "energy-scaled", "plasticity": "off",
              "plate_m": [1.0, 1.0, 0.0625], "cell_m": 0.0625, "ball_m": 0.3, "speed_m_s": 400.0,
              "offset_m": [0.0, 0.0], "support": "ledges", "duration_s": 0.5, "clearance_m": 3.0}},
    {"id": "bullet-low-clearance", "title": "The same 400 m/s strike, target 120 mm off the floor",
     "expect": "it perforates and then bounces off the floor: the rebound is the ground, not the pane",
     "spec": {"material": "oak", "striker": "iron", "failure_law": "energy-scaled", "plasticity": "off",
              "plate_m": [1.0, 1.0, 0.0625], "cell_m": 0.0625, "ball_m": 0.3, "speed_m_s": 400.0,
              "offset_m": [0.0, 0.0], "support": "ledges", "duration_s": 0.5, "clearance_m": 0.12}},
    {"id": "iron-dent", "title": "Iron plate dents and keeps the dent",
     "expect": "plastic flow on: permanent deformation, plastic work dissipated",
     "spec": {"material": "iron", "striker": "iron", "failure_law": "strain-threshold", "plasticity": "on",
              "plate_m": [0.15, 0.12, 0.01], "cell_m": 0.005, "ball_m": 0.06, "speed_m_s": 6.0,
              "offset_m": [0.0, 0.0], "support": "ledges", "duration_s": 2.0, "clearance_m": 0.5}},
    {"id": "iron-elastic", "title": "The same iron plate with plastic flow off",
     "expect": "the elastic control: it springs back flat",
     "spec": {"material": "iron", "striker": "iron", "failure_law": "strain-threshold", "plasticity": "off",
              "plate_m": [0.15, 0.12, 0.01], "cell_m": 0.005, "ball_m": 0.06, "speed_m_s": 6.0,
              "offset_m": [0.0, 0.0], "support": "ledges", "duration_s": 2.0, "clearance_m": 0.5}},
    {"id": "glass-twice", "title": "Hit it twice: a second ball on the broken plate",
     "expect": "the first strike breaks 523 bonds into 55 pieces; the second breaks 507 more, one piece into 77",
     "spec": {"material": "glass", "striker": "iron", "failure_law": "strain-threshold", "plasticity": "off",
              "plate_m": [0.25, 0.20, 0.01], "cell_m": 0.01, "ball_m": 0.06, "speed_m_s": 6.26424,
              "offset_m": [0.0, 0.0], "support": "ledges", "duration_s": 1.5,
              "refracture": "on", "second_speed_m_s": 8.0, "second_ball_m": 0.1,
              "second_offset_m": [0.09, 0.0], "second_wait_s": 0.6}},
    {"id": "glass-twice-before", "title": "The same second strike with re-fracture off",
     "expect": "the control: the second ball bounces off, 0 bonds, still 55 pieces",
     "spec": {"material": "glass", "striker": "iron", "failure_law": "strain-threshold", "plasticity": "off",
              "plate_m": [0.25, 0.20, 0.01], "cell_m": 0.01, "ball_m": 0.06, "speed_m_s": 6.26424,
              "offset_m": [0.0, 0.0], "support": "ledges", "duration_s": 1.5,
              "refracture": "off", "second_speed_m_s": 8.0, "second_ball_m": 0.1,
              "second_offset_m": [0.09, 0.0], "second_wait_s": 0.6}},
    {"id": "glass-twice-harder", "title": "Hit it again harder",
     "expect": "the same second strike at 20 m/s: 948 bonds and 151 pieces out of one",
     "spec": {"material": "glass", "striker": "iron", "failure_law": "strain-threshold", "plasticity": "off",
              "plate_m": [0.25, 0.20, 0.01], "cell_m": 0.01, "ball_m": 0.06, "speed_m_s": 6.26424,
              "offset_m": [0.0, 0.0], "support": "ledges", "duration_s": 1.5,
              "refracture": "on", "second_speed_m_s": 20.0, "second_ball_m": 0.1,
              "second_offset_m": [0.09, 0.0], "second_wait_s": 0.6}},
    {"id": "oak-ground", "title": "Oak plate lying on the ground, not on ledges",
     "expect": "the support changes what breaks: no span to bend across",
     "spec": {"material": "oak", "striker": "iron", "failure_law": "strain-threshold", "plasticity": "off",
              "plate_m": [0.25, 0.20, 0.01], "cell_m": 0.01, "ball_m": 0.06, "drop_m": 2.0,
              "offset_m": [0.0, 0.0], "support": "flat", "duration_s": 2.0, "clearance_m": 0.5}},
]

LIMITS = {
    "plate_m": {"min": 0.03, "max": 1.0}, "thickness_m": {"min": 0.002, "max": 0.1},
# The striker scales with the target: a 200 mm ball is a large projectile
# for a 250 mm plate and a pebble against a metre of glass. The cell bound
# rises with it so metre-scale objects can still be meshed coarsely.
    "cell_m": {"min": 0.002, "max": 0.15}, "ball_m": {"min": 0.01, "max": 0.5},
    # A bullet is ~350 m/s and a dropped tool is a few m/s; the engine should
    # cover both, and refusing to try is how a wrong answer stays hidden.
    "drop_m": {"min": 0.0, "max": 500.0}, "speed_m_s": {"min": 0.0, "max": 600.0},
    # How far the target sits above the floor. The default scene puts it 120 mm
    # up, so anything that punches through hits the floor at once and bounces
    # off that -- which reads as the projectile bouncing off the target.
    "clearance_m": {"min": 0.05, "max": 5.0},
    "duration_s": {"min": 0.2, "max": 6.0},
    "second_speed_m_s": {"min": 0.0, "max": 40.0}, "second_ball_m": {"min": 0.01, "max": 0.5},
    "second_wait_s": {"min": 0.05, "max": 5.0},
}

FIELDS = {"algorithm", "ball_m", "bodies", "cell_m", "clearance_m", "drop_m", "duration_s",
          "failure_law", "material", "offset_m", "plasticity", "plate_m", "refracture",
          "request_id", "second_ball_m", "second_offset_m", "second_speed_m_s",
          "second_wait_s", "speed_m_s", "striker", "support"}


def _number(value: Any, low: float, high: float, label: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        # Say what was given, not only what was wanted. A caller told the bound
        # but not the value has to guess which of its numbers was the problem.
        raise ValueError(f"{label} is {value!r}, and must be a finite number "
                         f"between {low:g} and {high:g}")
    return float(value)


# What a body of each material looks like in the 3D tab. Colour follows the
# material rather than being chosen per object, so two oak blocks always read as
# the same stuff and the panel has one fewer control.
# Only the lattice phase can break anything and it ends about this long after
# the last failure. Anything that arrives later can push but not crack.
FRACTURE_WINDOW_S = 0.02
# Errors are listed one per line so a reader, human or model, sees them all.
NEWLINE = chr(10)
MATERIAL_COLORS = {"glass": "9fd3ffff", "oak": "c9a06aff", "iron": "d0d4dcff",
                   "concrete": "8a8f99ff", "ceramic": "efe6d8ff", "ice": "bfe9f5ff"}
SHAPES = {"box": "a rectangular block", "sphere": "a ball",
          "cone": "a round shape, top diameter by height by bottom diameter"}
# A scene is capped by objects and by total cells: the cells are what costs, the
# object count is what keeps a scene readable and the Jolt handoff inside its
# contact caches.
BODY_LIMITS = {"bodies": 250, "size_mm": (5.0, 6000.0), "center_mm": (-8000.0, 8000.0),
               "velocity_m_s": (-600.0, 600.0), "name": 40}


def body_cells(body: dict[str, Any], cell_m: float) -> int:
    """Cells this body will occupy, the same way the generators count them."""
    sx, sy, sz = (v / 1000.0 for v in body["size_mm"])
    if body["shape"] == "sphere":
        radius = 0.5 * sx
        # The sphere generator samples occupancy in a cell-sized grid; the ball
        # volume over the cell volume is that count to within the surface layer.
        return max(1, round(4.0 / 3.0 * math.pi * radius ** 3 / cell_m ** 3))
    return max(1, round(sx / cell_m)) * max(1, round(sy / cell_m)) * max(1, round(sz / cell_m))


def normalise_bodies(bodies: Any, cell_m: float) -> list[dict[str, Any]]:
    """Check every object against its bound; return the list the engine will get."""
    if not isinstance(bodies, list):
        raise ValueError("bodies must be a list of objects")
    if len(bodies) > BODY_LIMITS["bodies"]:
        raise ValueError(f"a scene holds at most {BODY_LIMITS['bodies']} objects; this one has {len(bodies)}")
    out: list[dict[str, Any]] = []
    for index, body in enumerate(bodies):
        if not isinstance(body, dict):
            raise ValueError(f"object {index + 1} is not an object")
        name = str(body.get("name", f"object {index + 1}"))[:BODY_LIMITS["name"]].strip() or f"object {index + 1}"
        shape = body.get("shape", "box")
        if shape not in SHAPES:
            raise ValueError(f"{name}: shape must be one of {list(SHAPES)}")
        material = body.get("material", "glass")
        if material not in MATERIALS:
            raise ValueError(f"{name}: material must be one of {list(MATERIALS)}")
        def triple(key: str, low: float, high: float) -> list[float]:
            value = body.get(key)
            if not isinstance(value, list) or len(value) != 3:
                raise ValueError(f"{name}: {key} needs three numbers")
            return [_number(v, low, high, f"{name} {key}") for v in value]
        low = 0.0 if shape == "cone" else BODY_LIMITS["size_mm"][0]
        size = triple("size_mm", low, BODY_LIMITS["size_mm"][1])
        if shape == "sphere":
            size = [size[0], size[0], size[0]]
        if shape == "cone" and not (size[1] > 0 and max(size[0], size[2]) > 0):
            raise ValueError(f"{name}: a cone needs a height and at least one end with a width")
        center = triple("center_mm", *BODY_LIMITS["center_mm"])
        # Most objects are at rest, so an absent velocity means at rest rather
        # than an error.
        velocity = (triple("velocity_m_s", *BODY_LIMITS["velocity_m_s"])
                    if "velocity_m_s" in body else [0.0, 0.0, 0.0])
        # Tilt, in degrees about the body's own centre. Without it a ramp has to
        # be a staircase of boxes, which collide with each other and with
        # whatever stands on them.
        rotation = triple("rotation_deg", -180.0, 180.0) if "rotation_deg" in body else [0.0, 0.0, 0.0]
        # Scenery: a ramp, a table or a wall has nothing under it and otherwise
        # falls to the ground taking whatever rested on it.
        anchored = bool(body.get("anchored", False))
        # What this stands on, by name. Its height is then computed from that
        # object's actual surface underneath it, which is the one number a
        # caller cannot work out for a tilted or stepped surface.
        rest_on = str(body.get("rest_on", ""))[:BODY_LIMITS["name"]].strip()
        # Cut this shape out of its join group rather than adding it. Union alone
        # makes only shapes that bulge; a bowl is a sphere with a cavity and a
        # lid taken out of it.
        subtract = bool(body.get("subtract", False))
        # An extent that is not a whole number of cells is refused by the
        # generator, so it is snapped here and the panel is told what will run.
        built = [max(1, round(v / 1000.0 / cell_m)) * cell_m * 1000.0 for v in size]
        if shape in ("sphere", "cone"):
            # A round shape is cut from cells rather than tiled by them, so its
            # dimensions are used as given and never snapped.
            built = list(size)
        for axis, (want, got) in enumerate(zip(size, built)):
            if abs(got - want) > 0.2 * want:
                raise ValueError(
                    f"{name}: a {want:.0f} mm side is not a whole number of {cell_m * 1000:g} mm cells, "
                    f"and the nearest whole number is {got:.0f} mm - too far to substitute.")
        join = str(body.get("join", ""))[:40].strip()
        # Nothing in either phase turns sliding into rolling: friction slows a body
        # and applies no torque. A sphere sent along the ground with no spin slides
        # the whole way, measured at 2 degrees of turn over 10.4 m where a true roll
        # is 10,041. So a sphere with a horizontal velocity rolls, decided here
        # rather than asked of the caller, and said out loud in the summary.
        horizontal = math.hypot(velocity[0], velocity[2])
        rolls = bool(body.get("roll", False)) or (shape == "sphere" and horizontal > 0.0)
        out.append({"name": name, "shape": shape, "material": material, "join": join,
                    "roll": rolls, "rotation_deg": rotation, "anchored": anchored,
                    "rest_on": rest_on, "subtract": subtract,
                    "size_mm": [round(v, 3) for v in built],
                    "requested_size_mm": [round(v, 3) for v in size],
                    "center_mm": center, "velocity_m_s": velocity,
                    "color_rgba": MATERIAL_COLORS.get(material, "9fd3ffff"),
                    "cells": body_cells({"shape": shape, "size_mm": built}, cell_m)})
    return out


def _overlap_mm(a: dict[str, Any], b: dict[str, Any]) -> float:
    """How far two objects start inside each other, in mm. Zero if they only touch."""
    def half(body):
        return [v / 2 for v in body["size_mm"]]

    ca, cb = a["center_mm"], b["center_mm"]
    ha, hb = half(a), half(b)
    if a["shape"] == "sphere" and b["shape"] == "sphere":
        distance = math.dist(ca, cb)
        return max(0.0, ha[0] + hb[0] - distance)
    if a["shape"] == "sphere" or b["shape"] == "sphere":
        ball, block = (a, b) if a["shape"] == "sphere" else (b, a)
        centre, radius = ball["center_mm"], half(ball)[0]
        box_c, box_h = block["center_mm"], half(block)
        # Nearest point of the block to the ball's centre.
        near = [min(max(centre[k], box_c[k] - box_h[k]), box_c[k] + box_h[k]) for k in range(3)]
        return max(0.0, radius - math.dist(centre, near))
    # Two blocks: they intersect only where they overlap on all three axes, and
    # the shallowest axis is how far one would have to move to be clear.
    gaps = [min(ca[k] + ha[k], cb[k] + hb[k]) - max(ca[k] - ha[k], cb[k] - hb[k]) for k in range(3)]
    return max(0.0, min(gaps))


def _rotate(v: list[float], degrees: list[float], inverse: bool = False) -> list[float]:
    """x then y then z, degrees. The inverse undoes them in the opposite order."""
    order = [2, 1, 0] if inverse else [0, 1, 2]
    p = list(v)
    for axis in order:
        a = math.radians(-degrees[axis] if inverse else degrees[axis])
        c, s = math.cos(a), math.sin(a)
        if axis == 0:
            p = [p[0], p[1] * c - p[2] * s, p[1] * s + p[2] * c]
        elif axis == 1:
            p = [p[0] * c + p[2] * s, p[1], -p[0] * s + p[2] * c]
        else:
            p = [p[0] * c - p[1] * s, p[0] * s + p[1] * c, p[2]]
    return p


def body_cell_set(body: dict[str, Any], cell_mm: float) -> set[tuple[int, int, int]]:
    """The cells this body covers, by the rule the engine builds it with.

    A cell belongs to a body when its centre lies inside the body's shape, tested
    in the body's own frame so a tilt keeps the true extents and only moves the
    cells. This is the same question the engine asks, so what is counted here is
    what will actually be built.
    """
    half = [v / 2 for v in body["size_mm"]]
    centre = body["center_mm"]
    rotation = body.get("rotation_deg") or [0.0, 0.0, 0.0]
    sphere = body["shape"] == "sphere"
    cone = body["shape"] == "cone"
    radius = half[0]
    if cone:
        widest = max(body["size_mm"][0], body["size_mm"][2]) / 2
        half = [widest, half[1], widest]
    reach = radius if sphere else math.dist(half, [0, 0, 0])
    cells: set[tuple[int, int, int]] = set()
    ranges = []
    for k in range(3):
        ranges.append((math.floor((centre[k] - reach) / cell_mm),
                       math.ceil((centre[k] + reach) / cell_mm)))
    for i in range(ranges[0][0], ranges[0][1] + 1):
        for j in range(ranges[1][0], ranges[1][1] + 1):
            for k in range(ranges[2][0], ranges[2][1] + 1):
                point = [(i + 0.5) * cell_mm - centre[0],
                         (j + 0.5) * cell_mm - centre[1],
                         (k + 0.5) * cell_mm - centre[2]]
                local = _rotate(point, rotation, inverse=True) if any(rotation) else point
                if sphere:
                    inside = math.dist(local, [0, 0, 0]) <= radius
                elif cone:
                    # Width runs from the bottom diameter to the top one, so an
                    # upside-down cone is simply a wider top.
                    height = body["size_mm"][1]
                    inside = False
                    if abs(local[1]) <= height / 2:
                        t = (local[1] + height / 2) / height if height else 0.0
                        r = (body["size_mm"][2] + t * (body["size_mm"][0] - body["size_mm"][2])) / 2
                        inside = math.hypot(local[0], local[2]) <= r
                else:
                    inside = all(abs(local[m]) <= half[m] for m in range(3))
                if inside:
                    cells.add((i, j, k))
    return cells


def _lowest_cell_mm(body: dict[str, Any], cell_mm: float) -> float:
    """The bottom of the body's lowest cell, which is what the ground sees."""
    cells = body_cell_set(body, cell_mm)
    return min(j for _, j, _ in cells) * cell_mm if cells else 0.0


def seat_bodies(bodies: list[dict[str, Any]], cell_m: float) -> list[str]:
    """Place every body that names what it stands on, and say what moved.

    The height an object needs is decided by the surface directly beneath it,
    which on a tilted or stepped surface is different for every object on it.
    Working that out is the job of whatever knows the cells, which is here.
    """
    cell_mm = cell_m * 1000
    by_name = {b["name"]: b for b in bodies}
    moved: list[str] = []
    # Several passes so a thing resting on a thing resting on the floor settles
    # in the right order, however the list was written.
    for _ in range(len(bodies)):
        changed = False
        for body in bodies:
            target = body.get("rest_on")
            if not target:
                continue
            members = [b for b in bodies if b["name"] == target or (b.get("join") or "") == target]
            members = [b for b in members if b is not body and not b.get("subtract")]
            if not members:
                known = sorted({b["name"] for b in bodies if b is not body}
                               | {b["join"] for b in bodies if b.get("join")})
                raise ValueError(
                    f"\"{body['name']}\" rests on \"{target}\", which is not in the scene. "
                    f"Use one of: {', '.join(known)}.")
            support = members[0]
            if support.get("rest_on"):
                # Seat the support first.
                continue
            # A join group is one object, so resting on it means resting on all
            # of it, minus whatever the group cuts away.
            support_cells: set[tuple[int, int, int]] = set()
            for member in members:
                support_cells |= body_cell_set(member, cell_mm)
            if members[0].get("join"):
                for other in bodies:
                    if other.get("subtract") and (other.get("join") or "") == members[0]["join"]:
                        support_cells -= body_cell_set(other, cell_mm)
            if not support_cells:
                continue
            # The columns this body stands in, from its footprint rather than
            # from its cells, so the answer does not depend on where it is now.
            reach = [v / 2 for v in body["size_mm"]]
            if any(body.get("rotation_deg") or [0, 0, 0]):
                span = math.dist(reach, [0, 0, 0])
                reach = [span, span, span]
            columns = set()
            for i in range(math.floor((body["center_mm"][0] - reach[0]) / cell_mm),
                           math.ceil((body["center_mm"][0] + reach[0]) / cell_mm) + 1):
                for k in range(math.floor((body["center_mm"][2] - reach[2]) / cell_mm),
                               math.ceil((body["center_mm"][2] + reach[2]) / cell_mm) + 1):
                    columns.add((i, k))
            tops = [j for i, j, k in support_cells if (i, k) in columns]
            if not tops:
                raise ValueError(
                    f"\"{body['name']}\" rests on \"{target}\" but stands nowhere over it. "
                    f"Move it so it is above \"{target}\" in x and z.")
            surface = (max(tops) + 1) * cell_mm
            # Its own lowest point below its centre, which a tilt deepens.
            probe = dict(body)
            probe["center_mm"] = [body["center_mm"][0], 0.0, body["center_mm"][2]]
            drop = -_lowest_cell_mm(probe, cell_mm)
            wanted = round(surface + drop, 3)
            if abs(wanted - body["center_mm"][1]) > 1e-6:
                body["center_mm"] = [body["center_mm"][0], wanted, body["center_mm"][2]]
                moved.append(f"{body['name']} to {wanted:.0f} mm on {target}")
                changed = True
        if not changed:
            break
    return moved


def scene_cell_count(bodies: list[dict[str, Any]], cell_m: float) -> int:
    """How many cells the engine will actually build.

    Counting each body's own cells over-reports a scene badly: a bowl is a
    sphere with a smaller sphere and a lid cut out of it, and adding the three
    together says fifteen thousand cells where the engine builds under two. The
    cap is a cost bound, so it has to be applied to what is built.
    """
    cell_mm = cell_m * 1000
    groups: dict[str, list[dict[str, Any]]] = {}
    loose = 0
    for body in bodies:
        name = body.get("join") or ""
        if name:
            groups.setdefault(name, []).append(body)
        elif not body.get("subtract"):
            loose += len(body_cell_set(body, cell_mm))
    total = loose
    for members in groups.values():
        add: set[tuple[int, int, int]] = set()
        cut: set[tuple[int, int, int]] = set()
        for body in members:
            (cut if body.get("subtract") else add).update(body_cell_set(body, cell_mm))
        total += len(add - cut)
    return total


def check_scene(bodies: list[dict[str, Any]], cell_m: float) -> list[dict[str, Any]]:
    """Everything wrong with a scene, at once, in the terms it was written in.

    Nothing settles before a run and nothing is repaired behind the caller's
    back, so a scene that is wrong stays wrong and usually detonates. Every
    fault is reported together rather than one per round trip, because whoever
    is fixing them -- a person or a model -- pays for each trip.

    Severity "error" stops the run. "warning" does not: it is a thing worth
    knowing that is nonetheless a legitimate scene.
    """
    cell_mm = cell_m * 1000
    tolerance = max(0.05, cell_mm * 0.01)
    report: list[dict[str, Any]] = []

    for body in bodies:
        bottom = _lowest_cell_mm(body, cell_mm)
        if bottom < -tolerance:
            # The height that fixes it is measured from the body's own lowest
            # cell, so a tilted body is told about the corner that actually dips
            # rather than about half its height, which is only right when it is
            # sitting square.
            needed = body["center_mm"][1] - bottom
            tilted = any(body.get("rotation_deg") or [0.0, 0.0, 0.0])
            report.append({
                "severity": "error", "code": "below_ground", "object": body["name"],
                "message": f"\"{body['name']}\" reaches {-bottom:.0f} mm below the ground, which is at "
                           f"y = 0. Raise it to a height of {needed:.0f} mm."
                           + (" It is tilted, so its low corner dips further than half its thickness."
                              if tilted else ""),
                "fix": {"object": body["name"], "center_mm_y": needed}})

    # A subtracted shape is a hole, not an object. It is meant to be inside what
    # it cuts, so it takes no part in the overlap, ground or support checks.
    solid = [b for b in bodies if not b.get("subtract")]
    covered = [body_cell_set(b, cell_mm) for b in solid]
    bodies = solid
    for i in range(len(bodies)):
        for j in range(i + 1, len(bodies)):
            a, b = bodies[i], bodies[j]
            shared = covered[i] & covered[j]
            cells = len(shared)
            if cells == 0:
                continue
            joined = a.get("join") and a.get("join") == b.get("join")
            # How far one has to rise to clear the other, measured column by
            # column so a tilted surface gives a different answer under each
            # object rather than one number for all of them.
            columns = {(i2, k2) for i2, _, k2 in covered[j]}
            under = [j2 for i2, j2, k2 in covered[i] if (i2, k2) in columns]
            top_of_a = (max(under) + 1) * cell_mm if under else 0.0
            bottom_of_b = min(j2 for _, j2, _ in covered[j]) * cell_mm
            depth = top_of_a - bottom_of_b
            if joined:
                report.append({
                    "severity": "info", "code": "joined_overlap", "object": a["name"], "other": b["name"],
                    "message": f"\"{a['name']}\" and \"{b['name']}\" share {cells} cells and are "
                               f"joined as \"{a['join']}\", so the shared cells are built once and the "
                               f"two become one bonded object."})
                continue
            lift = b["center_mm"][1] + max(depth, cell_mm)
            report.append({
                "severity": "error", "code": "overlap", "object": a["name"], "other": b["name"],
                "message": f"\"{a['name']}\" and \"{b['name']}\" both claim {cells} of the same "
                           f"cells. Nothing settles before a run, so they blow apart "
                           f"on the first step. Either raise \"{b['name']}\" to a height of {lift:.0f} mm "
                           f"so it rests on top, or give both the same \"join\" name to fuse them into "
                           f"one object with the shared cells removed.",
                "fix": {"object": b["name"], "center_mm_y": lift, "or_join": True}})

    # Anything with nothing under it starts by falling, which is legitimate but
    # is usually a placement mistake rather than an intention.
    for body in bodies:
        if any(v for v in body["velocity_m_s"]):
            continue
        bottom = body["center_mm"][1] - body["size_mm"][1] / 2
        if bottom <= tolerance:
            continue
        supported = False
        for other in bodies:
            if other is body:
                continue
            top = other["center_mm"][1] + other["size_mm"][1] / 2
            if abs(top - bottom) > cell_mm * 0.5:
                continue
            if all(abs(body["center_mm"][k] - other["center_mm"][k])
                   <= (body["size_mm"][k] + other["size_mm"][k]) / 2 for k in (0, 2)):
                supported = True
                break
        if not supported:
            report.append({
                "severity": "warning", "code": "unsupported", "object": body["name"],
                "message": f"\"{body['name']}\" has nothing under it and is not moving, so it starts "
                           f"{bottom:.0f} mm up and falls. Rest it on something or lower it to the ground."})

    # One cell through a dimension has no bending stiffness at all.
    for body in bodies:
        if body["shape"] == "sphere":
            continue
        thin = min(body["size_mm"])
        if thin < cell_mm * 1.5:
            report.append({
                "severity": "warning", "code": "one_cell_thick", "object": body["name"],
                "message": f"\"{body['name']}\" is one cell through its thinnest side, so it has no "
                           f"bending stiffness: it flexes about six times too far and reads bending strain "
                           f"about sixteen times low. Make that side {cell_mm * 2:.0f} mm, or halve the cell."})

    # A striker that arrives after the fracture window can only push.
    for body in bodies:
        speed = math.sqrt(sum(v * v for v in body["velocity_m_s"]))
        if speed <= 0:
            continue
        # The clear distance to the nearest thing in the way, measured between
        # the two bodies' cells rather than between guessed boxes, and only
        # counting what the body is actually heading into.
        axis = max(range(3), key=lambda k: abs(body["velocity_m_s"][k]))
        forward = 1 if body["velocity_m_s"][axis] > 0 else -1
        mine = covered[bodies.index(body)]
        others = [(k, (0, 1, 2)[k]) for k in range(3) if k != axis]
        my_span = {tuple(sorted((c[o[0]] for o in others))) for c in
                   [(x, y, z) for x, y, z in mine]} if False else {
            (c[others[0][0]], c[others[1][0]]) for c in mine}
        my_edge = (max(c[axis] for c in mine) if forward > 0 else min(c[axis] for c in mine))
        gap = None
        for index, other in enumerate(bodies):
            if other is body:
                continue
            theirs = covered[index]
            ahead = [c[axis] for c in theirs
                     if (c[others[0][0]], c[others[1][0]]) in my_span
                     and (c[axis] - my_edge) * forward > 0]
            if not ahead:
                continue
            near = min(ahead) if forward > 0 else max(ahead)
            clearance = abs(near - my_edge) * cell_mm - cell_mm
            if gap is None or clearance < gap:
                gap = max(0.0, clearance)
        if gap is None:
            continue
        arrival = gap / 1000.0 / speed
        if arrival > FRACTURE_WINDOW_S:
            report.append({
                "severity": "warning", "code": "late_strike", "object": body["name"],
                "message": f"\"{body['name']}\" has {gap:.0f} mm to cross at {speed:.1f} m/s, so it "
                           f"arrives at about {arrival * 1000:.0f} ms, after the {FRACTURE_WINDOW_S * 1000:.0f} ms "
                           f"window in which anything can break. It will push things over and break "
                           f"nothing. Start it closer or send it faster."})
    return report


def check_placement(bodies: list[dict[str, Any]], cell_m: float) -> None:
    """The hard gate: raise on the first thing that would make a run worthless."""
    report = check_scene(bodies, cell_m)
    errors = [item for item in report if item["severity"] == "error"]
    if not errors:
        return
    # Every error, not the first one. Each carries the height that fixes it, so
    # a caller with all of them can repair the scene in one pass; a caller given
    # one at a time pays a round trip per object, and with a tilted surface
    # there is an error per object by construction.
    shown = errors[:16]
    lines = [f"{len(errors)} placement error(s):"] + [f"  - {item['message']}" for item in shown]
    if len(errors) > len(shown):
        lines.append(f"  - and {len(errors) - len(shown)} more of the same kind.")
    raise ValueError(NEWLINE.join(lines))


def scene_document(spec: dict[str, Any]) -> dict[str, Any]:
    """The --scene file: metres, the engine's units, nothing the panel added."""
    return {"bodies": [{"name": b["name"], "shape": b["shape"], "material": b["material"],
                        "dimensions_m": [v / 1000.0 for v in b["size_mm"]],
                        "center_m": [v / 1000.0 for v in b["center_mm"]],
                        "velocity_m_s": b["velocity_m_s"],
                        # Bodies sharing a join name are voxelised onto the shared grid and
                        # unioned: a cell both claim is built once and bonds cross the seam.
                        "join": b["join"],
                        "rotation_deg": b["rotation_deg"],
                        "anchored": b["anchored"],
                        "subtract": b["subtract"],
                        # Nothing turns sliding into rolling, so a ball that should roll is
                        # given the spin that goes with its speed.
                        "roll": b["roll"],
                        "color_rgba": b["color_rgba"]}
                       for b in spec["bodies"]]}


def cell_counts(plate_m: list[float], cell_m: float) -> tuple[int, int, int]:
    length, width, thickness = plate_m
    return (max(1, round(length / cell_m)), max(1, round(width / cell_m)), max(1, round(thickness / cell_m)))


def validate(spec: Any) -> dict[str, Any]:
    """Check every field against its bound; return a normalised copy with derived values."""
    if not isinstance(spec, dict):
        raise ValueError("Fracture lab request must be an object")
    unknown = set(spec) - FIELDS
    if unknown:
        raise ValueError(f"Unknown fracture lab fields: {sorted(unknown)}")
    result = dict(DEFAULT)
    result.update({k: v for k, v in spec.items() if k != "request_id"})
    if result["algorithm"] not in ALGORITHMS:
        raise ValueError(f"algorithm must be one of {list(ALGORITHMS)}")
    result["cell_m"] = _number(result["cell_m"], LIMITS["cell_m"]["min"], LIMITS["cell_m"]["max"], "cell size")
    if result.get("bodies"):
        # A many-object scene: every object is lattice, there is no rigid
        # striker, and what falls is whatever object was given a velocity. The
        # plate and ball fields are not read.
        result["bodies"] = normalise_bodies(result["bodies"], result["cell_m"])
        result["duration_s"] = _number(result["duration_s"], LIMITS["duration_s"]["min"],
                                       LIMITS["duration_s"]["max"], "duration")
        result["seated"] = seat_bodies(result["bodies"], result["cell_m"])
        check_placement(result["bodies"], result["cell_m"])
        result["cells"] = scene_cell_count(result["bodies"], result["cell_m"])
        result["cells_per_axis"] = [0, 0, 0]
        result["plate_m"] = [0.0, 0.0, 0.0]
        result["requested_plate_m"] = [0.0, 0.0, 0.0]
        result["snapped"] = any(
            abs(a - b) > 1e-6 for body in result["bodies"]
            for a, b in zip(body["size_mm"], body["requested_size_mm"]))
        if result["algorithm"] != "lattice":
            raise ValueError("only the explicit lattice lane runs a many-object scene")
        lane = ALGORITHMS[result["algorithm"]]
        if result["cells"] > lane["max_cells"]:
            raise ValueError(f"{result['cells']} cells exceeds this lane's cap of {lane['max_cells']}; "
                             f"use larger cells or smaller objects.")
        return result
    plate = result["plate_m"]
    if not isinstance(plate, list) or len(plate) != 3:
        raise ValueError("plate_m requires length, width and thickness in metres")
    result["plate_m"] = [_number(plate[0], LIMITS["plate_m"]["min"], LIMITS["plate_m"]["max"], "plate length"),
                         _number(plate[1], LIMITS["plate_m"]["min"], LIMITS["plate_m"]["max"], "plate width"),
                         _number(plate[2], LIMITS["thickness_m"]["min"], LIMITS["thickness_m"]["max"], "plate thickness")]
    result["ball_m"] = _number(result["ball_m"], LIMITS["ball_m"]["min"], LIMITS["ball_m"]["max"], "ball diameter")
    if result.get("speed_m_s") is not None:
        result["speed_m_s"] = _number(result["speed_m_s"], LIMITS["speed_m_s"]["min"], LIMITS["speed_m_s"]["max"], "impact speed")
        result["drop_m"] = result["speed_m_s"] ** 2 / (2 * GRAVITY_M_S2)
    else:
        result["drop_m"] = _number(result["drop_m"], LIMITS["drop_m"]["min"], LIMITS["drop_m"]["max"], "drop height")
        result["speed_m_s"] = math.sqrt(2 * GRAVITY_M_S2 * result["drop_m"])
    offset = result["offset_m"]
    if not isinstance(offset, list) or len(offset) != 2:
        raise ValueError("offset_m requires two values")
    # Bound the offset by the requested plate; the snap below moves the edges by
    # less than one cell, and clamping after it would reject a strike the caller
    # placed legitimately near the rim.
    half = [result["plate_m"][0] / 2, result["plate_m"][1] / 2]
    result["offset_m"] = [_number(offset[0], -half[0], half[0], "offset x"), _number(offset[1], -half[1], half[1], "offset z")]
    if result["support"] not in SUPPORTS:
        raise ValueError(f"support must be one of {list(SUPPORTS)}")
    if result["material"] not in MATERIALS:
        raise ValueError(f"material must be one of {list(MATERIALS)}")
    if result["striker"] not in MATERIALS:
        raise ValueError(f"striker must be one of {list(MATERIALS)}")
    if result["failure_law"] not in FAILURE_LAWS:
        raise ValueError(f"failure_law must be one of {list(FAILURE_LAWS)}")
    if result["plasticity"] not in PLASTICITY:
        raise ValueError(f"plasticity must be one of {list(PLASTICITY)}")
    if result["refracture"] not in REFRACTURE:
        raise ValueError(f"refracture must be one of {list(REFRACTURE)}")
    result["second_speed_m_s"] = _number(result["second_speed_m_s"], LIMITS["second_speed_m_s"]["min"],
                                         LIMITS["second_speed_m_s"]["max"], "second strike speed")
    result["second_ball_m"] = _number(result["second_ball_m"], LIMITS["second_ball_m"]["min"],
                                      LIMITS["second_ball_m"]["max"], "second ball diameter")
    second_offset = result["second_offset_m"]
    if not isinstance(second_offset, list) or len(second_offset) != 2:
        raise ValueError("second_offset_m requires two values")
    result["second_offset_m"] = [_number(second_offset[0], -0.5, 0.5, "second offset x"),
                                 _number(second_offset[1], -0.5, 0.5, "second offset z")]
    result["second_wait_s"] = _number(result["second_wait_s"], LIMITS["second_wait_s"]["min"],
                                      LIMITS["second_wait_s"]["max"], "second strike wait")
    result["duration_s"] = _number(result["duration_s"], LIMITS["duration_s"]["min"], LIMITS["duration_s"]["max"], "duration")
    result["clearance_m"] = _number(result["clearance_m"], LIMITS["clearance_m"]["min"],
                                    LIMITS["clearance_m"]["max"], "clearance under the target")
    # `generateBoxTileLattice` refuses an extent that is not a whole number of
    # cells (BoxLattice.cpp cellCount, tolerance 1e-6 relative), so the plate is
    # snapped here rather than accepted and refused four layers down. What was
    # asked for is kept alongside what will run, and the panel shows both.
    nx, ny, nz = cell_counts(result["plate_m"], result["cell_m"])
    result["requested_plate_m"] = list(result["plate_m"])
    result["plate_m"] = [nx * result["cell_m"], ny * result["cell_m"], nz * result["cell_m"]]
    result["snapped"] = any(abs(a - b) > 1e-9 for a, b in zip(result["plate_m"], result["requested_plate_m"]))
    # Rounding moves an extent by at most half a cell, which is nothing on a
    # 250 mm plate and everything on a 4 mm one: asking for a 4 mm plate with
    # 10 mm cells would otherwise hand back a 10 mm plate. Refuse rather than
    # deliver a different object than the one described.
    for axis, (want, got) in enumerate(zip(result["requested_plate_m"], result["plate_m"])):
        if abs(got - want) > 0.2 * want:
            name = ("length", "width", "thickness")[axis]
            raise ValueError(
                f"A {want * 1000:.0f} mm {name} is not a whole number of {result['cell_m'] * 1000:g} mm cells, "
                f"and the nearest whole number is {got * 1000:.0f} mm - too far to substitute. "
                f"Use a cell size that divides it, such as {want / max(1, round(want / result['cell_m'])) * 1000:.3g} mm.")
    result["cells_per_axis"] = [nx, ny, nz]
    result["cells"] = nx * ny * nz
    aspect = max(result["plate_m"][i] / result["cells_per_axis"][i] for i in range(3)) / min(
        result["plate_m"][i] / result["cells_per_axis"][i] for i in range(3))
    result["cell_aspect"] = aspect
    result["offset_m"] = [max(-result["plate_m"][0] / 2, min(result["plate_m"][0] / 2, result["offset_m"][0])),
                          max(-result["plate_m"][1] / 2, min(result["plate_m"][1] / 2, result["offset_m"][1]))]
    if aspect > 2.0:
        raise ValueError(f"Cells would be {aspect:.1f}:1; the engine assumes cubic cells (aspect <= 2:1). "
                         f"Choose a cell size that divides the thickness.")
    lane = ALGORITHMS[result["algorithm"]]
    if result["cells"] > lane["max_cells"]:
        raise ValueError(f"{result['cells']} cells exceeds this lane's instant-run cap of {lane['max_cells']}; "
                         f"use larger cells or a smaller plate.")
    return result


def executable(engine_path: Path, algorithm: str) -> Path:
    return engine_path.with_name(ALGORITHMS[algorithm]["exe"] + engine_path.suffix)


def describe(engine_path: Path) -> dict[str, Any]:
    """What the panel needs: lanes and whether each is built, defaults, limits."""
    lanes = []
    for key, lane in ALGORITHMS.items():
        path = executable(engine_path, key)
        lanes.append({"id": key, "title": lane["title"], "available": path.is_file(), "max_cells": lane["max_cells"],
                      "timeout_s": lane["timeout_s"], "executable": path.name})
    return {"algorithms": lanes, "default": DEFAULT, "limits": LIMITS, "supports": list(SUPPORTS),
            "scenarios": SCENARIOS,
            "materials": list(MATERIALS), "failure_laws": list(FAILURE_LAWS),
            "plasticity": list(PLASTICITY), "refracture": list(REFRACTURE),
            "shapes": SHAPES, "material_colors": MATERIAL_COLORS, "body_limits": BODY_LIMITS,
            "realtime_limit": REALTIME_LIMIT}


def command(algorithm: str, spec: dict[str, Any], engine_path: Path, output: Path, cache_dir: Path,
            report_path: Path) -> list[str]:
    exe = executable(engine_path, algorithm)
    lane = ALGORITHMS[algorithm]
    L, W, T = spec["plate_m"]
    if lane["contract"] == "lane":
        return [str(exe), "--plate", f"{L:.6g}", f"{W:.6g}", f"{T:.6g}", "--cell", f"{spec['cell_m']:.6g}",
                "--ball", f"{spec['ball_m']:.6g}", "--speed", f"{spec['speed_m_s']:.6g}",
                "--offset", f"{spec['offset_m'][0]:.6g}", f"{spec['offset_m'][1]:.6g}",
                "--support", spec["support"], "--duration", f"{spec['duration_s']:.6g}",
                "--cache", str(cache_dir), "--output", str(output)]
    # The explicit lattice runner: --tile X Y Z with Y the thickness, a ball
    # radius, and a layout that is either two ledges or the ground. It has no
    # pinned-perimeter support, so `clamped` is refused rather than silently
    # run as something else.
    if spec["support"] == "clamped":
        raise ValueError("This lane supports the target on two ledges or on the ground, not clamped edges")
    if spec.get("bodies"):
        # Many objects: the geometry is a file, not a tile, and the ground is
        # the only support. The lane keeps its own failure law and plasticity.
        scene_path = report_path.with_name("scene.json")
        scene_path.write_text(json.dumps(scene_document(spec), indent=1), encoding="utf-8")
        return [str(exe), "--scene", str(scene_path), "--cell", f"{spec['cell_m']:.6g}",
                "--layout", "flat", "--settle-s", f"{spec['duration_s']:.6g}",
                "--failure-law", spec["failure_law"], "--plasticity", spec["plasticity"],
                "--backend", "parallel", "--precision", "double",
                "--record", str(output), "--report", str(report_path)]
    argv = [str(exe), "--material", spec["material"], "--ball-material", spec["striker"],
            "--tile", f"{L:.6g}", f"{T:.6g}", f"{W:.6g}", "--cell", f"{spec['cell_m']:.6g}",
            "--ball-radius", f"{spec['ball_m'] / 2:.6g}", "--speed", f"{spec['speed_m_s']:.6g}",
            "--offset", f"{spec['offset_m'][0]:.6g}", f"{spec['offset_m'][1]:.6g}",
            "--layout", "bridge" if spec["support"] == "ledges" else "flat",
            "--ledge-height", f"{spec['clearance_m']:.6g}",
            "--settle-s", f"{spec['duration_s']:.6g}",
            # The parallel backend is the same sweep in the same order with the
            # colour stages spread within a stage, so it is bit-identical to the
            # serial one (1,982 bonds, 295 pieces, 3.3813 J on the default scene)
            # at 2.9x the speed: 3.5x realtime instead of 10.1x.
            "--failure-law", spec["failure_law"],
            "--plasticity", spec["plasticity"],
            "--backend", "parallel", "--precision", "double",
            "--record", str(output), "--report", str(report_path)]
    # Nothing below is emitted unless it is asked for, so the default command
    # line is byte for byte the one this lane has always run.
    if spec.get("refracture") == "on":
        argv += ["--refracture", "on"]
    if spec.get("second_speed_m_s"):
        argv += ["--second-ball", f"{spec['second_ball_m'] / 2:.6g}",
                 "--second-speed", f"{spec['second_speed_m_s']:.6g}",
                 "--second-offset", f"{spec['second_offset_m'][0]:.6g}", f"{spec['second_offset_m'][1]:.6g}",
                 "--second-material", spec["striker"],
                 "--second-wait", f"{spec['second_wait_s']:.6g}"]
    return argv


def _pick(report: dict[str, Any], *paths: str) -> Any:
    for path in paths:
        node: Any = report
        for key in path.split("."):
            node = node.get(key) if isinstance(node, dict) else None
            if node is None:
                break
        if isinstance(node, (int, float)) and math.isfinite(node):
            return node
    return None


def summary(report: dict[str, Any], wall_s: float, spec: dict[str, Any]) -> dict[str, Any]:
    """The rows the panel shows, read from whichever names the lane uses."""
    simulated = _pick(report, "realtime.simulated_s", "simulated_total_s", "simulated_s", "elapsed_s")
    compute = _pick(report, "realtime.compute_wall_s", "compute_wall_s", "wall_total_s")
    ratio = _pick(report, "realtime.ratio", "realtime_ratio")
    if ratio is None and simulated:
        ratio = wall_s / simulated
    window_ratio = _pick(report, "realtime.fracture_window_ratio")
    lattice_wall = _pick(report, "lattice.wall_s"); lattice_sim = _pick(report, "lattice.simulated_s")
    if window_ratio is None and lattice_wall is not None and lattice_sim:
        window_ratio = lattice_wall / lattice_sim
    return {
        "plate_mm": [round(v * 1000, 1) for v in spec["plate_m"]],
        # A many-object scene has no single target material and no striker; the
        # bodies list below is what it had instead.
        "material": None if spec.get("bodies") else spec["material"],
        "striker": None if spec.get("bodies") else spec["striker"],
        "ball_mm": None if spec.get("bodies") else round(spec["ball_m"] * 1000, 1),
        "speed_m_s": None if spec.get("bodies") else round(spec["speed_m_s"], 3),
        "cell_mm": round(spec["cell_m"] * 1000, 3),
        # Cells through the thickness. One layer samples only the mid-plane,
        # where bending strain is zero, so the plate has neither the stiffness
        # to resist bending nor the strain to fail on it.
        "thickness_cells": spec["cells_per_axis"][2],
        "bodies": [{"name": b["name"], "shape": b["shape"], "material": b["material"],
                    "size_mm": b["size_mm"], "cells": b["cells"],
                    "join": b.get("join", ""), "roll": b.get("roll", False),
                    "rotation_deg": b.get("rotation_deg", [0,0,0]), "anchored": b.get("anchored", False),
                    "speed_m_s": round(max(abs(v) for v in b["velocity_m_s"]), 3)}
                   for b in spec.get("bodies", [])],
        "snapped_from_mm": ([round(v * 1000, 1) for v in spec["requested_plate_m"]] if spec.get("snapped") else None),
        "cells": _pick(report, "cells") or spec["cells"],
        "bonds": _pick(report, "bonds", "lattice.bonds"),
        "precompute_s": _pick(report, "precompute_s"),
        "precompute_cached": report.get("precompute_cached"),
        "compute_wall_s": compute,
        "server_wall_s": wall_s,
        "simulated_s": simulated,
        "realtime_ratio": ratio,
        "realtime_limit": REALTIME_LIMIT,
        "fracture_window_ratio": window_ratio,
        "broken_bonds": _pick(report, "broken_bonds", "lattice.broken_bonds"),
        "components": _pick(report, "components", "handoff.components", "rigid.pieces", "lattice.components"),
        "largest_component_cells": _pick(report, "largest_component_cells", "handoff.largest_piece_cells"),
        "removed_energy_j": _pick(report, "removed_energy_j", "lattice.removed_energy_j"),
        "first_failure_time_s": _pick(report, "first_failure.time_s", "lattice.first_failure_s"),
        "rank_deficient_nodes": _pick(report, "rank_deficient_nodes"),
        "peak_tensile_stretch": _pick(report, "max_tensile_stretch"),
        "came_to_rest": (report.get("rigid") or {}).get("came_to_rest"),
        # The second strike is a separate phase, so its damage is not in the
        # first lattice run`s counts. Reporting only the first phase is how a
        # working re-fracture looked like nothing happening.
        "refracture": ({"admitted": (report.get("refracture") or {}).get("admitted"),
                        "contacts_tested": (report.get("refracture") or {}).get("contacts_tested"),
                        "broken_bonds": (report.get("refracture") or {}).get("broken_bonds"),
                        "pieces_created": (report.get("refracture") or {}).get("pieces_created"),
                        "removed_energy_j": (report.get("refracture") or {}).get("removed_energy_j"),
                        "wall_s": (report.get("refracture") or {}).get("wall_s")}
                       if (report.get("refracture") or {}).get("enabled") else None),
        "contact_impulse_n_s": _pick(report, "contact.impulse_n_s", "lattice.contact.impulse_n_s"),
    }


def run(app: Any, body: Any) -> dict[str, Any]:
    """Validate, run the lane, register the recording as a job, return the summary.

    `app` is the playground application: it provides runs_path, engine_path,
    lock, jobs and playbacks, which is all a job needs to exist.
    """
    if not isinstance(body, dict):
        raise ValueError("Expected a fracture lab request object")
    request_id = body.get("request_id")
    if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", request_id):
        raise ValueError("Invalid request identity")
    spec = validate(body)
    algorithm = spec["algorithm"]
    lane = ALGORITHMS[algorithm]
    exe = executable(app.engine_path, algorithm)
    if not exe.is_file():
        raise ValueError(f"{lane['title']} is not built yet ({exe.name} is missing next to the engine)")
    job_id = uuid.uuid4().hex
    directory = app.runs_path / job_id
    directory.mkdir(parents=True, exist_ok=False)
    cache_dir = app.runs_path.parent / "fracture-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    playback = directory / "playback-00.json"
    report_path = directory / "lane-report.json"
    argv = command(algorithm, spec, app.engine_path, playback, cache_dir, report_path)
    (directory / "fracture-request.json").write_text(json.dumps({"spec": spec, "argv": argv}, indent=1), encoding="utf-8")
    if spec.get("bodies"):
        # A many-object scene has no plate and no striker to name it by; what
        # identifies it is what is in it and what is moving.
        moving = [b for b in spec["bodies"] if any(v for v in b["velocity_m_s"])]
        name = (f"{len(spec['bodies'])} objects, {spec['cells']} cells at {spec['cell_m']*1000:g} mm: "
                + ", ".join(f"{b['name']} ({b['material']})" for b in spec["bodies"])
                + (f"; {moving[0]['name']} starts moving" if moving else "; nothing is moving"))
    else:
        nx, ny, nz = spec["cells_per_axis"]
        name = (f"{spec['material']} {spec['plate_m'][0]*1000:.0f}x{spec['plate_m'][1]*1000:.0f}x"
                f"{spec['plate_m'][2]*1000:.0f} mm, {nx}x{ny}x{nz} = {spec['cells']} cells, "
                f"{spec['ball_m']*1000:.0f} mm {spec['striker']} ball at {spec['speed_m_s']:.2f} m/s, "
                f"{spec['support']}, {spec['failure_law']}")
    started = time.perf_counter()
    case: dict[str, Any] = {"index": 0, "name": name, "package": {}, "status": "pending", "native_scene": False,
                            "playback_available": False, "warnings": [], "error": ""}
    job: dict[str, Any] = {"id": job_id, "status": "running", "message": "Fracture lab run in progress.", "plan": None,
                           "cases": [case], "warnings": [], "timing": {},
                           "fracture": {"algorithm": algorithm, "lane": lane["title"], "spec": spec}}
    try:
        result = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                timeout=lane["timeout_s"], check=False)
        wall = time.perf_counter() - started
        if result.returncode or not playback.is_file():
            reason = (result.stderr or result.stdout).strip().splitlines()
            raise ValueError(f"{lane['title']} refused or failed: {reason[-1][:300] if reason else 'no output'}")
        if playback.stat().st_size > 64 * 1024 * 1024:
            raise ValueError("The recording exceeds the browser's 64 MB budget; shorten the duration or coarsen the plate")
        recording = json.loads(playback.read_text(encoding="utf-8"))
        if recording.get("schema") != "banjo.playback.v1":
            raise ValueError("The lane did not write a banjo.playback.v1 recording")
        report = recording.get("report") or {}
        if not report and report_path.is_file():
            report = json.loads(report_path.read_text(encoding="utf-8"))
        case.update({"status": recording.get("status", "complete"), "report": report, "playback_available": True,
                     "wall_s": round(wall, 3), "error": recording.get("error", "")})
        job["fracture"]["summary"] = summary(report, wall, spec)
        job["fracture"]["wall_s"] = round(wall, 3)
        job["status"] = "complete"
        ratio = job["fracture"]["summary"].get("realtime_ratio")
        job["message"] = (f"{lane['title']}: {spec['cells']} cells in {wall:.3f} s wall"
                          + (f", {ratio:.2f}x of the simulated interaction (limit {REALTIME_LIMIT}x)" if ratio else "")
                          + ". Open the 3D playback tab.")
        with app.lock:
            app.playbacks[(job_id, 0)] = playback
    except subprocess.TimeoutExpired:
        wall = time.perf_counter() - started
        case.update({"status": "error", "error": f"Timed out after {lane['timeout_s']} s", "wall_s": round(wall, 3)})
        job.update({"status": "error", "message": case["error"], "error": case["error"]})
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        wall = time.perf_counter() - started
        case.update({"status": "error", "error": str(exc)[:4000], "wall_s": round(wall, 3)})
        job.update({"status": "error", "message": str(exc)[:4000], "error": str(exc)[:4000]})
    (directory / "job.json").write_text(json.dumps(job, indent=2, allow_nan=False), encoding="utf-8")
    with app.lock:
        app.jobs[job_id] = job
    return {"job_id": job_id, "status": job["status"], "message": job["message"], "wall_s": round(wall, 3),
            "fracture": job["fracture"], "error": job.get("error", "")}
