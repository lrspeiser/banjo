"""What the network engine will actually accept, and what it will cost.

The authoring layer used to know one of the engine's limits (the 1 mm collision
radius) and none of the others, so the playground could hand the solver a scene
it was always going to refuse, or one it would accept and then spend forty
minutes on. This module states every limit that constrains a network object in
one place, computes the same numbers the native code computes, and turns a
refusal into the nearest admissible setup rather than a dead end.

Nothing here changes solver behaviour, material constants or tolerances. It is
a mirror of `src/platform/NetworkWorld.cpp` and `src/physics/ResolutionBudget.cpp`,
kept honest by `tests/network_admission_tests.py`, which compares it against
recorded native reports.

Admission is not calibration. A scene this module admits is a scene the engine
will run; it is not a scene whose material response has been validated. The
native report still says `physical_response_validated: false`.
"""
from __future__ import annotations

import math
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "examples" / "authoring") not in sys.path:
    sys.path.insert(0, str(ROOT / "examples" / "authoring"))
from banjo_authoring import catalog, suggest_cubic_resolution  # noqa: E402

# ---------------------------------------------------------------------------
# The engine's own limits. Each entry cites the line that enforces it.
# ---------------------------------------------------------------------------
# NetworkWorld.cpp: integer(o["resolution"][i], 2, 16)
RESOLUTION_MIN, RESOLUTION_MAX = 2, 16
# NetworkWorld.cpp: require(nx*ny*nz <= 800, "network object cell budget")
OBJECT_CELL_BUDGET = 800
# NetworkWorld.cpp: require(w.nodes.size() < 1024, "world cell budget exceeded")
WORLD_CELL_BUDGET = 1024
# NetworkWorld.cpp: radius = .49 * min(spacing); require(radius >= .001)
COLLISION_RADIUS_FACTOR = .49
COLLISION_RADIUS_MIN_M = .001
MIN_CELL_SPACING_M = COLLISION_RADIUS_MIN_M / COLLISION_RADIUS_FACTOR  # 2.0408 mm
# banjo_authoring.validate_network_geometry: the proxy has to represent the cell
# whose mass it carries. Shipped presets run 1.0 to 2.0.
MAX_CELL_ASPECT = 2.0
# How slender a uniform-cell object can be. Strictly cubic cells would bound it
# at RESOLUTION_MAX / RESOLUTION_MIN = 8:1, but the admission rule tolerates
# cells up to MAX_CELL_ASPECT, and that tolerance multiplies:
#   Dmax/Dmin = (spacing_max * nmax) / (spacing_min * nmin) <= aspect * nmax/nmin
# so the real ceiling is 2 * 16/2 = 16:1 through the engine and 2 * 12/2 = 12:1
# through the drop and scene routes, which cap resolution at 12. A 6 mm pane
# 500 mm across is 83:1 and is not expressible either way.
CUBIC_SLENDERNESS = RESOLUTION_MAX / RESOLUTION_MIN
MAX_SLENDERNESS = MAX_CELL_ASPECT * RESOLUTION_MAX / RESOLUTION_MIN
# The playground's own admission budget, older and tighter than the engine's.
PLAYGROUND_CELL_BUDGET = 850
# ResolutionBudget.cpp / NetworkWorld.cpp stability clock.
STABILITY_PHASE_RAD = .2
MAX_STABILITY_SUBSTEPS = 8192

LIMITS = {
    "resolution_per_axis": [RESOLUTION_MIN, RESOLUTION_MAX],
    "object_cells": OBJECT_CELL_BUDGET,
    "world_cells": WORLD_CELL_BUDGET,
    "playground_cells": PLAYGROUND_CELL_BUDGET,
    "cell_aspect_ratio": MAX_CELL_ASPECT,
    "slenderness_face_over_thickness": MAX_SLENDERNESS,
    "slenderness_with_strictly_cubic_cells": CUBIC_SLENDERNESS,
    "collision_radius_m": COLLISION_RADIUS_MIN_M,
    "minimum_cell_spacing_m": MIN_CELL_SPACING_M,
    "stability_phase_rad": STABILITY_PHASE_RAD,
    "maximum_substeps_per_tick": MAX_STABILITY_SUBSTEPS,
}


class Inadmissible(ValueError):
    """A setup the engine would refuse, named limit and nearest fix included."""

    def __init__(self, message: str, *, limit: str, repair: dict[str, Any] | None = None):
        super().__init__(message)
        self.limit = limit
        self.repair = repair


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------
def cell_metrics(dimensions_m: Any, resolution: Any) -> dict[str, Any]:
    """Every number the engine derives from a box and its resolution.

    Raises for malformed input; returns a report (including failures) for input
    that is well formed but inadmissible, so a caller can render it.
    """
    if not isinstance(dimensions_m, (list, tuple)) or len(dimensions_m) != 3 or any(
            type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in dimensions_m):
        raise ValueError("Network dimensions require three positive finite SI values")
    if not isinstance(resolution, (list, tuple)) or len(resolution) != 3 or any(
            type(v) is not int or not RESOLUTION_MIN <= v <= RESOLUTION_MAX for v in resolution):
        raise ValueError(
            f"Network resolution requires three integers in "
            f"[{RESOLUTION_MIN}, {RESOLUTION_MAX}]")
    spacing = [float(d) / n for d, n in zip(dimensions_m, resolution)]
    aspect = max(spacing) / min(spacing)
    radius = COLLISION_RADIUS_FACTOR * min(spacing)
    cells = int(resolution[0] * resolution[1] * resolution[2])
    slenderness = max(dimensions_m) / min(dimensions_m)
    return {
        "dimensions_m": [float(d) for d in dimensions_m],
        "resolution": [int(n) for n in resolution],
        "spacing_m": spacing,
        "spacing_mm": [round(v * 1000, 4) for v in spacing],
        "cells": cells,
        "aspect_ratio": aspect,
        # With cubic cells the sphere spans 98% of the cell and neighbours just
        # touch. Across the widest axis it spans 0.98 / aspect of the cell it
        # carries the mass of.
        "collision_coverage": .98 / aspect,
        "collision_radius_m": radius,
        "slenderness": slenderness,
        "cubic": aspect <= MAX_CELL_ASPECT,
        "radius_ok": radius >= COLLISION_RADIUS_MIN_M,
        "cells_ok": cells <= OBJECT_CELL_BUDGET,
    }


def admissible_resolutions(dimensions_m: Any, *, max_cells: int = OBJECT_CELL_BUDGET,
                           low: int = RESOLUTION_MIN, high: int = RESOLUTION_MAX):
    """Every resolution in range whose cells are near-cubic, big enough and few enough."""
    found = []
    for nx in range(low, high + 1):
        for ny in range(low, high + 1):
            for nz in range(low, high + 1):
                if nx * ny * nz > max_cells:
                    continue
                spacing = [dimensions_m[0] / nx, dimensions_m[1] / ny, dimensions_m[2] / nz]
                if COLLISION_RADIUS_FACTOR * min(spacing) < COLLISION_RADIUS_MIN_M:
                    continue
                aspect = max(spacing) / min(spacing)
                if aspect <= MAX_CELL_ASPECT:
                    found.append(([nx, ny, nz], aspect, nx * ny * nz))
    return found


def nearest_admissible_resolution(dimensions_m: Any, requested=None, *,
                                  max_cells: int = OBJECT_CELL_BUDGET,
                                  low: int = RESOLUTION_MIN, high: int = RESOLUTION_MAX):
    """The admissible resolution closest to what was asked for, or None.

    Closest means the smallest change to the requested mesh, then the fewest
    cells, then the most cubic. Preferring the smallest change keeps a repair
    recognisable as the thing that was asked for; preferring fewer cells after
    that keeps a repair from quietly turning a one-minute run into a ten-minute
    one, since cost is set by the cell size.

    `suggest_cubic_resolution` in the authoring API answers a different
    question -- the single most cubic mesh -- and is what the engine-facing
    guard quotes. Both return None when the box is too slender to be built from
    uniform cells at all, which is the honest answer rather than a compromise.
    """
    candidates = admissible_resolutions(dimensions_m, max_cells=max_cells, low=low, high=high)
    if not candidates:
        return None
    if requested is None:
        return min(candidates, key=lambda item: (item[2], item[1]))[0]
    def distance(item):
        return sum((a - b) ** 2 for a, b in zip(item[0], requested))
    return min(candidates, key=lambda item: (distance(item), item[2], item[1]))[0]


def buildable_dimensions(dimensions_m, *, low: int = RESOLUTION_MIN, high: int = RESOLUTION_MAX):
    """The nearest box of the same face size that CAN be built from cubic cells.

    A refusal is only useful with a way forward. When face:thickness exceeds the
    ceiling, the two ways forward are a thicker object or a smaller face, so
    report both.
    """
    ratio = MAX_CELL_ASPECT * high / low
    thin = min(dimensions_m)
    face = max(dimensions_m)
    return {
        "slenderness": face / thin,
        "maximum_slenderness": ratio,
        "cubic_slenderness": high / low,
        # Rounded to 0.1 mm: an alternative geometry is a suggestion to type in,
        # not a value to carry sixteen digits of.
        "thicken_to_m": round(face / ratio, 4),
        "shrink_face_to_m": round(thin * ratio, 4),
    }


def describe_geometry(dimensions_m: Any, resolution: Any, *, label: str = "object",
                      max_cells: int = OBJECT_CELL_BUDGET,
                      low: int = RESOLUTION_MIN, high: int = RESOLUTION_MAX) -> dict[str, Any]:
    """Admission report for one network box: verdict, reason and repair."""
    metrics = cell_metrics(dimensions_m, resolution)
    metrics["label"] = label
    suggestion = nearest_admissible_resolution(dimensions_m, resolution, max_cells=max_cells,
                                               low=low, high=high)
    metrics["suggested_resolution"] = suggestion
    problems = []
    if not metrics["cells_ok"]:
        problems.append({
            "limit": "object_cells",
            "message": (f"{label}: {metrics['cells']} cells exceeds the engine's "
                        f"{OBJECT_CELL_BUDGET}-cell per-object budget.")})
    if not metrics["cubic"]:
        problems.append({
            "limit": "cell_aspect_ratio",
            "message": (
                f"{label}: cells are {metrics['aspect_ratio']:.2f}:1, not cubic "
                f"(spacing {metrics['spacing_mm']} mm). Every cell collides as a sphere of "
                f"radius 0.49 x the smallest spacing while carrying the mass and inertia of "
                f"the whole box, so across its widest axis the proxy spans only "
                f"{metrics['collision_coverage'] * 100:.0f}% of the cell and fragments pass "
                f"through each other. The limit is {MAX_CELL_ASPECT:g}:1.")})
    if not metrics["radius_ok"]:
        problems.append({
            "limit": "collision_radius_m",
            "message": (
                f"{label}: collision proxies would be "
                f"{metrics['collision_radius_m'] * 1000:.4g} mm in radius; the engine requires "
                f"at least {COLLISION_RADIUS_MIN_M * 1000:g} mm, so every cell spacing must be "
                f"at least {MIN_CELL_SPACING_M * 1000:.4g} mm.")})
    if problems and suggestion is None:
        metrics["dimension_repair"] = buildable_dimensions(dimensions_m, low=low, high=high)
    metrics["problems"] = problems
    metrics["admissible"] = not problems
    return metrics


# ---------------------------------------------------------------------------
# Cost: the network's own stability clock
# ---------------------------------------------------------------------------
def _directional_modulus(young_modulus_pa, direction) -> float:
    """NetworkMaterial.cpp harmonicDirectional, for a unit direction."""
    total = sum(d * d / e for d, e in zip(direction, young_modulus_pa))
    if not math.isfinite(total) or total <= 0:
        raise ValueError("invalid directional modulus")
    return 1.0 / total


_NEIGHBOURS = [(dx, dy, dz)
               for dx in (-1, 0, 1) for dy in (-1, 0, 1) for dz in (-1, 0, 1)
               if 0 < dx * dx + dy * dy + dz * dz <= 2]


def object_frequency(dimensions_m, resolution, material, *, shape: str = "box"):
    """max_i sum_j k_ij / m_i for one network object, and its cell/bond counts.

    Reproduces the lattice NetworkWorld builds: an 18-neighbour stencil (6 face,
    12 edge), bond stiffness E_dir * area / rest_length with area = volume^(2/3)/6,
    and cell mass = density * volume. The grain quaternion is treated as identity;
    the shipped oak preset uses identity grain, and a rotated grain only permutes
    which axis modulus a bond sees.
    """
    nx, ny, nz = (int(v) for v in resolution)
    hx, hy, hz = (float(d) / n for d, n in zip(dimensions_m, resolution))
    volume = hx * hy * hz
    area = volume ** (2.0 / 3.0) / 6.0
    mass = float(material["density_kg_m3"]) * volume
    modulus = material["young_modulus_pa"]

    occupied = {}
    for x in range(nx):
        for y in range(ny):
            for z in range(nz):
                if shape == "ellipsoid":
                    local = ((x + .5) * hx - dimensions_m[0] / 2,
                             (y + .5) * hy - dimensions_m[1] / 2,
                             (z + .5) * hz - dimensions_m[2] / 2)
                    if 4 * sum(c * c / (d * d) for c, d in zip(local, dimensions_m)) > 1:
                        continue
                occupied[(x, y, z)] = len(occupied)
    if not occupied:
        raise ValueError("empty occupied network")

    sums = [0.0] * len(occupied)
    bonds = 0
    for cell, a in occupied.items():
        for dx, dy, dz in _NEIGHBOURS:
            b = occupied.get((cell[0] + dx, cell[1] + dy, cell[2] + dz))
            if b is None or b <= a:
                continue
            rest = (dx * hx, dy * hy, dz * hz)
            length = math.sqrt(sum(v * v for v in rest))
            stiffness = _directional_modulus(modulus, [v / length for v in rest]) * area / length
            sums[a] += stiffness / mass
            sums[b] += stiffness / mass
            bonds += 1
    return {"maximum_stiffness_over_mass": max(sums), "cells": len(occupied), "bonds": bonds,
            "cell_mass_kg": mass, "spacing_m": [hx, hy, hz]}


def package_substeps(package: dict[str, Any]) -> dict[str, Any]:
    """Substeps per host tick the engine will choose for this package.

    Mirrors `assessSpringResolution(masses, links, dt, 8192, 0.2)`:
    omega = sqrt(2 max_i sum_j k_ij/m_i) and substeps = ceil(omega dt / 0.2),
    capped at the engine's internal budget. A run whose requirement exceeds the
    cap is under-resolved and the native report says so.
    """
    materials = {m["id"]: m for m in package.get("materials") or catalog()["materials"]}
    dt = float(package["fixed_dt_s"])
    worst = 0.0
    cells = bonds = 0
    rigid = 0
    detail = []
    for obj in package.get("objects", []):
        if obj.get("representation") != "network":
            rigid += 1
            continue
        material = materials.get(obj["material"])
        if material is None:
            raise ValueError(f"Package does not declare material {obj['material']!r}")
        result = object_frequency(obj["dimensions_m"], obj["resolution"], material,
                                  shape=obj.get("shape", "box"))
        worst = max(worst, result["maximum_stiffness_over_mass"])
        cells += result["cells"]
        bonds += result["bonds"]
        detail.append({"id": obj.get("id"), "name": obj.get("name"),
                       "material": obj["material"], "cells": result["cells"],
                       "bonds": result["bonds"]})
    if not detail:
        return {"substeps_per_host_tick": 1, "required_substeps": 1, "limited_by_budget": False,
                "maximum_frequency_bound_rad_s": 0.0, "internal_step_s": dt,
                "network_cells": 0, "bonds": 0, "rigid_bodies": rigid, "objects": detail}
    omega = math.sqrt(2 * worst)
    required = max(1, math.ceil(omega * dt / STABILITY_PHASE_RAD))
    used = min(required, MAX_STABILITY_SUBSTEPS)
    return {
        "substeps_per_host_tick": used,
        "required_substeps": required,
        "limited_by_budget": required > MAX_STABILITY_SUBSTEPS,
        "maximum_frequency_bound_rad_s": omega,
        "internal_step_s": dt / used,
        "network_cells": cells,
        "bonds": bonds,
        "rigid_bodies": rigid,
        "objects": detail,
    }


# ---------------------------------------------------------------------------
# Cost: wall time
# ---------------------------------------------------------------------------
# Measured on this machine (Windows, build/win-joint-double/Release, 2026-09-07)
# by timing four near-cubic glass recordings end to end and dividing by
# steps x substeps: 32 cells/148 bonds 25.2 s, 108/642 116.7 s, 125/780 135.0 s,
# 256/1704 253.5 s. Cost per internal solve is proportional to the cell count to
# within +-11% across that 8x range; adding a bond term makes the fit worse, so
# the one constant below is the whole model. It folds in process startup and
# playback serialisation. This is a throughput measurement of one machine, not a
# property of the physics.
#
# It over-predicts strongly anisotropic lattices -- the nine 7.5:1 to 3:1
# drop-sweep recordings come in 65-107% below it -- because non-cubic collision
# proxies never touch, so those scenes pay almost no cell-to-cell contact cost.
# The authoring layer now refuses that geometry, and being conservative about
# the scenes it does admit is the right direction to err.
SUBSTEP_PER_CELL_S = 1.118e-5
# Fragmentation and dense contact add work the static scene cannot predict, and
# repeated runs of one scene already vary. Quote a band, not a point.
COST_UNCERTAINTY = .35

# tools/playground_record.cpp strides so a recording never holds more than ~122
# frames, and every frame carries a pose per body and a line per bond. Measured
# on build/drop-sweep/8mm-1m.playback.json: 193 poses and 1092 bonds serialise
# to 201 kB once the numbers stop being round, i.e. about 165 bytes each. The
# recorder refuses a playback over 64 MiB, and it does that AFTER the whole run,
# so this has to be checked before starting.
RECORDER_MAX_FRAMES = 122
RECORDER_BYTES_PER_ENTRY = 170
RECORDER_MAX_BYTES = 64 * 1024 * 1024
RECORDER_MAX_BONDS = 20000


def cost_estimate(package: dict[str, Any], steps: int) -> dict[str, Any]:
    """What this package will cost before it is run.

    Cost is set by the smallest cell: the substep count scales as 1/h, so
    halving a plate's thickness roughly doubles the bill for the same simulated
    time. The estimate is a floor in the presence of heavy fragmentation.
    """
    if type(steps) is not int or steps < 1:
        raise ValueError("steps must be a positive integer")
    stepping = package_substeps(package)
    bodies = stepping["network_cells"] + stepping["rigid_bodies"]
    per_substep = SUBSTEP_PER_CELL_S * stepping["network_cells"]
    total = steps * stepping["substeps_per_host_tick"]
    wall = per_substep * total
    frames = min(RECORDER_MAX_FRAMES, steps + 1)
    recording_bytes = frames * RECORDER_BYTES_PER_ENTRY * (bodies + stepping["bonds"])
    return {
        **stepping,
        "steps": steps,
        "fixed_dt_s": float(package["fixed_dt_s"]),
        "simulated_s": steps * float(package["fixed_dt_s"]),
        "total_substeps": total,
        "estimated_wall_s": wall,
        "estimated_wall_low_s": wall * (1 - COST_UNCERTAINTY),
        "estimated_wall_high_s": wall * (1 + COST_UNCERTAINTY),
        "estimated_wall_text": format_duration(wall),
        "seconds_per_substep": per_substep,
        "recorded_frames": frames,
        "estimated_recording_mb": recording_bytes / (1024 * 1024),
        "recording_over_budget": recording_bytes > RECORDER_MAX_BYTES,
        "bonds_over_budget": stepping["bonds"] > RECORDER_MAX_BONDS,
        "basis": (f"{SUBSTEP_PER_CELL_S * 1e6:.2f} us per network cell per internal solve, "
                  f"measured on this build, times cells x substeps x steps. Fitted to four "
                  f"cubic recordings within +-11%; fragmentation and dense contact add work "
                  f"it cannot see."),
    }


def format_duration(seconds: float) -> str:
    if not math.isfinite(seconds) or seconds < 0:
        return "unknown"
    if seconds < 90:
        return f"{seconds:.0f} s"
    if seconds < 5400:
        return f"{seconds / 60:.0f} min"
    return f"{seconds / 3600:.1f} h"


def measured_substeps(report: dict[str, Any]):
    """The substep count the engine actually used, from a native report."""
    stepping = (report or {}).get("network_substepping")
    if not isinstance(stepping, dict):
        return None
    return stepping.get("substeps_per_host_tick")


# ---------------------------------------------------------------------------
# Whole-package admission
# ---------------------------------------------------------------------------
def describe_package(package: dict[str, Any], steps: int) -> dict[str, Any]:
    """Admission plus cost for a complete authored package."""
    reports, problems = [], []
    total_cells = 0
    for index, obj in enumerate(package.get("objects", [])):
        if obj.get("representation") != "network":
            continue
        report = describe_geometry(obj["dimensions_m"], obj["resolution"],
                                   label=str(obj.get("name") or f"object {obj.get('id', index)}"))
        reports.append(report)
        problems += report["problems"]
        total_cells += report["cells"]
    if total_cells > WORLD_CELL_BUDGET:
        problems.append({"limit": "world_cells",
                         "message": (f"{total_cells} network cells exceeds the engine's "
                                     f"{WORLD_CELL_BUDGET}-cell world budget.")})
    elif total_cells > PLAYGROUND_CELL_BUDGET:
        problems.append({"limit": "playground_cells",
                         "message": (f"{total_cells} network cells exceeds the playground's "
                                     f"{PLAYGROUND_CELL_BUDGET}-cell admission budget.")})
    result = {"objects": reports, "network_cells": total_cells,
              "problems": problems, "admissible": not problems}
    if not problems:
        result["cost"] = cost_estimate(package, steps)
    return result
