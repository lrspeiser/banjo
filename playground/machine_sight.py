"""What has been seen, and what has not (docs/machine-world.md, "What has been
seen").

A room answered about ground nobody had ever been near as readily as about the
ground a machine was standing on: every deposit in the spec was handed to every
machine's senses, and the page drew the whole basin from the first frame. A world
like that has nothing to find out.

So the room keeps what has been SEEN. It is a coarse grid, a metre a cell over
the ground the room covers, marked wherever a machine or a person has been, and
kept with the room, so a place stays known once someone has been there and a
reload does not forget it.

What reveals it is being there: a machine on the ground marks a circle round
itself, and a machine in the air marks a wider one, because seeing further is
what height is for and what a scout is for. Nothing else reveals anything. A
routine's places do not, a deposit declared in the spec does not, and neither
does anything the chat knows: a survey of somewhere nobody has been says it is
not known, and the senses that hand a machine the room's deposits hand it only
the ones in ground it knows.

The grid is kept as base64 of one byte a cell, and written into the spec only
once something has been seen: an empty block in every room's document would
change the word every saved world is checked against (machine_goods says the
same of its own).
"""
from __future__ import annotations

import base64
import math
from typing import Any

# A metre a cell. Fine enough that the edge of what is known follows a machine's
# path round a hill, coarse enough that a 60 m room is 3,600 bytes.
CELL_M = 1.0
# How far a machine sees from the ground, and how much further for every metre it
# is above it. Six metres on the ground is about a tenth of a 32 m room from one
# spot, so getting about is how a room is learned; a metre and a half of sight for
# every metre of height is what makes a drone worth flying high, since at 10 m up
# it sees 21 m -- twelve times the ground a rover does -- and somewhere above 16 m
# it takes in the whole room at once. Eight metres and three per metre up lit two
# thirds of a room from three standing spots, which is not a world with anything
# left to find out.
SIGHT_M = 6.0
SIGHT_PER_M_UP = 1.5
# The most any machine can reveal at once, however high it gets.
SIGHT_MOST_M = 30.0
# How far round a person, who is on foot and looking about.
PERSON_SIGHT_M = 6.0


def sight_m(height_m: float) -> float:
    """How far a machine sees, by how far above the ground it is."""
    return min(SIGHT_MOST_M, SIGHT_M + SIGHT_PER_M_UP * max(0.0, float(height_m or 0.0)))


class Sight:
    """The room's record of what has been seen. Reads its grid off the room's
    terrain, so what is known lines up with what there is."""

    def __init__(self, spec: dict[str, Any], grid: Any = None):
        """`grid` is the live terrain's own grid as the engine reports it
        (nx, nz, cell_m, x0_m, z0_m), so what is known lines up with what there
        is. A record already kept with the room keeps its own grid."""
        self.spec = spec if isinstance(spec, dict) else {}
        block = self.spec.get("sight")
        self.block = block if isinstance(block, dict) else {}
        self.cell_m = float(self.block.get("cell_m") or CELL_M)
        if self.block.get("nx"):
            self.nx, self.nz = int(self.block["nx"]), int(self.block["nz"])
            self.x0_m, self.z0_m = float(self.block.get("x0_m", 0.0)), float(self.block.get("z0_m", 0.0))
        elif isinstance(grid, dict) and grid.get("nx"):
            fine = float(grid.get("cell_m") or 0.25)
            self.x0_m, self.z0_m = float(grid.get("x0_m", 0.0)), float(grid.get("z0_m", 0.0))
            self.nx = max(1, math.ceil(int(grid["nx"]) * fine / self.cell_m))
            self.nz = max(1, math.ceil(int(grid.get("nz") or grid["nx"]) * fine / self.cell_m))
        else:
            # From the terrain the room declares. The engine lays a generated
            # field's grid on the origin with its VERTICES spanning
            # (n - 1) * cell, so the first one is at -(n - 1) * cell / 2:
            # tests/sight_tests.py opens a real room and fails if that is ever
            # not what the engine reports.
            made = self.spec.get("terrain") if isinstance(self.spec.get("terrain"), dict) else {}
            made = made.get("generate") if isinstance(made.get("generate"), dict) else {}
            fine, nx = float(made.get("cell_m") or 0.0), int(made.get("nx") or 0)
            nz = int(made.get("nz") or nx)
            if fine > 0.0 and nx > 0:
                self.x0_m = -0.5 * (nx - 1) * fine
                self.z0_m = -0.5 * (nz - 1) * fine
                self.nx = max(1, math.ceil((nx - 1) * fine / self.cell_m))
                self.nz = max(1, math.ceil((nz - 1) * fine / self.cell_m))
            else:
                # Nothing to lay it over: it covers nothing and knows nothing
                # until it is given a grid.
                self.nx = self.nz = 0
                self.x0_m = self.z0_m = 0.0
        seen = self.block.get("seen_b64")
        want = self.nx * self.nz
        self.seen = bytearray(base64.b64decode(seen)) if isinstance(seen, str) and seen else bytearray(want)
        if len(self.seen) != want:
            self.seen = bytearray(want)

    # ---- where a cell is -----------------------------------------------------
    def _cell(self, x: float, z: float) -> int | None:
        i = int(math.floor((float(x) - self.x0_m) / self.cell_m))
        j = int(math.floor((float(z) - self.z0_m) / self.cell_m))
        if 0 <= i < self.nx and 0 <= j < self.nz:
            return j * self.nx + i
        return None

    def middle_of(self, index: int) -> list[float]:
        """Where a cell's middle is, in the world."""
        i, j = index % self.nx, index // self.nx
        return [self.x0_m + (i + 0.5) * self.cell_m, self.z0_m + (j + 0.5) * self.cell_m]

    # ---- what is known -------------------------------------------------------
    def knows(self, x: float, z: float) -> bool:
        """Whether anyone has been near enough to this to have seen it. Ground
        outside the room counts as known: there is nothing there to find out."""
        cell = self._cell(x, z)
        return True if cell is None else bool(self.seen[cell])

    def share(self) -> float:
        """How much of the room has been seen, 0 to 1."""
        return (sum(1 for c in self.seen if c) / len(self.seen)) if self.seen else 1.0

    def known_cells(self) -> int:
        return sum(1 for c in self.seen if c)

    # ---- what reveals it -----------------------------------------------------
    def reveal(self, x: float, z: float, radius_m: float) -> int:
        """Mark everything within `radius_m` of a point as seen. Says how many
        cells that was the first sight of."""
        radius_m = max(0.0, float(radius_m))
        if radius_m <= 0.0 or not self.seen:
            return 0
        first = 0
        reach = radius_m + 0.5 * self.cell_m
        i0 = max(0, int(math.floor((x - reach - self.x0_m) / self.cell_m)))
        i1 = min(self.nx - 1, int(math.floor((x + reach - self.x0_m) / self.cell_m)))
        j0 = max(0, int(math.floor((z - reach - self.z0_m) / self.cell_m)))
        j1 = min(self.nz - 1, int(math.floor((z + reach - self.z0_m) / self.cell_m)))
        for j in range(j0, j1 + 1):
            for i in range(i0, i1 + 1):
                mx = self.x0_m + (i + 0.5) * self.cell_m
                mz = self.z0_m + (j + 0.5) * self.cell_m
                if math.hypot(mx - x, mz - z) > radius_m:
                    continue
                k = j * self.nx + i
                if not self.seen[k]:
                    self.seen[k] = 1
                    first += 1
        if first:
            self._kept()
        return first

    def looked(self, machines: dict[str, Any] | None, person: Any = None) -> int:
        """What every machine in the room, and the person if they are in it, can
        see from where they are. Says how many cells were seen for the first
        time, which is what a machine has just found out."""
        first = 0
        for program in ((machines or {}).get("programs") or []):
            at = program.get("at_m")
            if not isinstance(at, (list, tuple)) or len(at) < 3:
                continue
            first += self.reveal(float(at[0]), float(at[2]), sight_m(program.get("height_m")))
        standing = person.get("standing_m") if isinstance(person, dict) else None
        if isinstance(standing, (list, tuple)) and len(standing) >= 3:
            first += self.reveal(float(standing[0]), float(standing[2]), PERSON_SIGHT_M)
        return first

    # ---- what is kept and what is sent --------------------------------------
    def _kept(self) -> None:
        """The block into the room's spec, once something has been seen."""
        self.block.clear()
        self.block.update({"cell_m": self.cell_m, "x0_m": self.x0_m, "z0_m": self.z0_m,
                           "nx": self.nx, "nz": self.nz,
                           "seen_b64": base64.b64encode(bytes(self.seen)).decode("ascii")})
        if self.spec.get("sight") is not self.block:
            self.spec["sight"] = self.block

    def shown(self) -> dict[str, Any]:
        """What the page needs to draw the ground it knows and leave the rest
        dark: the grid and a byte a cell."""
        return {"cell_m": self.cell_m, "x0_m": self.x0_m, "z0_m": self.z0_m, "nx": self.nx, "nz": self.nz,
                "seen_b64": base64.b64encode(bytes(self.seen)).decode("ascii"),
                "known_cells": self.known_cells(), "cells": len(self.seen)}


def checked(given: Any) -> dict[str, Any]:
    """A sight block as a room declares it, checked. A room may start with
    nothing seen, or with a record a previous run left."""
    if not isinstance(given, dict):
        raise ValueError("sight is an object: cell_m, x0_m, z0_m, nx, nz, seen_b64")
    unknown = set(given) - {"cell_m", "x0_m", "z0_m", "nx", "nz", "seen_b64"}
    if unknown:
        raise ValueError("sight cannot say " + ", ".join(sorted(unknown)))
    out: dict[str, Any] = {}
    for key, low, high in (("cell_m", 0.1, 20.0), ("x0_m", -1.0e4, 1.0e4), ("z0_m", -1.0e4, 1.0e4)):
        if given.get(key) is not None:
            value = float(given[key])
            if not (low <= value <= high):
                raise ValueError(f"sight's {key} is out of range")
            out[key] = value
    for key in ("nx", "nz"):
        if given.get(key) is not None:
            count = int(given[key])
            if not (1 <= count <= 4000):
                raise ValueError(f"sight's {key} is 1 to 4000")
            out[key] = count
    if given.get("seen_b64") is not None:
        text = str(given["seen_b64"])
        try:
            raw = base64.b64decode(text, validate=True)
        except Exception as error:                                   # noqa: BLE001
            raise ValueError("sight's seen_b64 is not base64") from error
        if out.get("nx") and out.get("nz") and len(raw) != out["nx"] * out["nz"]:
            raise ValueError(f"sight's seen_b64 is {len(raw)} bytes, not the {out['nx'] * out['nz']} its grid needs")
        out["seen_b64"] = base64.b64encode(raw).decode("ascii")
    return out


# The record's one owner is the room's brains (rover_brain.Brains): they make it
# when a room opens, share it with every machine's senses, and reveal from it
# after every step, which is the one place that runs in the page's path and in a
# test's alike. Nothing else keeps one, so nothing else can disagree about what
# has been seen.
