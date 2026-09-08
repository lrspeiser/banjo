#!/usr/bin/env python3
"""Run and summarise the energy-scaled criterion's convergence ladder.

Each row is one banjo_fast_lattice_run report. The script only launches the
tool and reads the JSON it writes; every number below comes from the run.
"""
import argparse, json, os, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Nominal constants of the reference materials (src/material/MaterialCatalog.cpp),
# needed only for the derived columns below.
MATERIALS = {
    "glass": dict(E=70.0e9, rho=2500.0, Gc=8.0, sigma=45.0e6),
    "oak": dict(E=12.0e9, rho=700.0, Gc=1000.0, sigma=90.0e6),
    "iron": dict(E=211.0e9, rho=7870.0, Gc=100000.0, sigma=250.0e6),
    "ceramic": dict(E=300.0e9, rho=3900.0, Gc=25.0, sigma=300.0e6),
    "ice": dict(E=9.0e9, rho=917.0, Gc=1.5, sigma=1.0e6),
    "concrete": dict(E=30.0e9, rho=2400.0, Gc=100.0, sigma=3.0e6),
}


def horizon_geometry(m):
    """N_100 = sum |o_x| and sum n_x^4 over the half offsets, as
    latticeHorizonGeometry computes them in C++."""
    import math
    n100 = nx4 = 0.0
    bonds = 0
    for dz in range(-m, m + 1):
        for dy in range(-m, m + 1):
            for dx in range(-m, m + 1):
                if not (dz > 0 or (dz == 0 and dy > 0) or (dz == 0 and dy == 0 and dx > 0)):
                    continue
                d2 = dx * dx + dy * dy + dz * dz
                if math.sqrt(d2) > m + 1e-9:
                    continue
                bonds += 1
                n100 += abs(dx)
                nx4 += (dx * dx / d2) ** 2
    return dict(bonds=bonds, n100=n100, nx4=nx4)
EXE = ROOT / "build" / "agent" / "Release" / "banjo_fast_lattice_run.exe"
OUT = ROOT / "docs" / "evidence" / "criterion"
META = {}

FIELDS = [
    "name", "law", "material", "cell_mm", "horizon", "speed", "dt_factor",
    "cells", "bonds", "dt_us", "substeps", "lattice_ms", "wall_s",
    "s_crit", "s_energy", "s_strength", "bound", "G_lattice",
    "broken", "rounds", "pieces", "p1pct", "p5pct", "largest_kg",
    "removed_j", "first_s", "first_bonds", "first_depth_mm", "first_radius_mm",
    "tensile", "shear", "compressive", "rest",
]


def run(name, *, material="glass", cell=0.02, horizon=2, speed=8.0, law="strain-threshold",
        dt_factor=0.5, tile=(0.24, 0.04, 0.16), window_ms=None, settle_s=None,
        record=False, extra=(), force=False):
    """One ladder row.

    window_ms fixes the lattice phase to exactly that many milliseconds of
    simulated time at every resolution (quiet/no-failure exits disabled), so
    levels of the ladder are compared over the same physical window rather
    than over whatever adaptive window each resolution happened to take.
    """
    OUT.mkdir(parents=True, exist_ok=True)
    report = OUT / f"{name}.json"
    args = [str(EXE), "--layout", "bridge", "--ball-radius", "0.04",
            "--speed", str(speed), "--tile", *[str(v) for v in tile],
            "--cell", str(cell), "--horizon", str(horizon), "--material", material,
            "--backend", "cpu", "--precision", "double", "--dt-factor", str(dt_factor),
            "--failure-law", law, "--report", str(report)]
    if window_ms is not None:
        # Same exit RULE at every level: run until the cascade has been quiet
        # for QUIET_MS, or until window_ms, whichever comes first. A fixed
        # duration is not comparable across resolutions (the fine levels are
        # still breaking bonds when a window sized for the coarse one closes);
        # the quiet rule asks the same question of every level, "what is the
        # tile when it stops coming apart", and the achieved window and exit
        # reason are reported per row so truncation stays visible.
        args += ["--quiet-ms", str(QUIET_MS), "--no-failure-ms", str(QUIET_MS),
                 "--min-ms", "0", "--max-ms", str(window_ms)]
    if settle_s is not None:
        args += ["--settle-s", str(settle_s)]
    if record:
        args += ["--record", str(OUT / f"{name}.playback.json")]
    args += list(extra)
    META[name] = dict(material=material, horizon=horizon, speed=speed, dt_factor=dt_factor,
                      window_ms=window_ms)
    if report.exists() and not force:
        print(f"[skip] {name} (report exists)")
    else:
        print(f"[run ] {name}: {' '.join(args[1:])}", flush=True)
        t0 = time.time()
        proc = subprocess.run(args, capture_output=True, text=True)
        if proc.returncode != 0:
            print(proc.stdout[-4000:]); print(proc.stderr[-4000:])
            raise SystemExit(f"{name} failed with {proc.returncode}")
        print(f"[done] {name} in {time.time() - t0:.1f} s", flush=True)
    return summarise(name, report)


def meta_from_name(name):
    """Recover the run parameters from a row name written by run().

    Rows are named <material>-<old|new>-<cell>mm-v<speed>[-<tag>], so a report
    already on disk can be summarised without re-running it.
    """
    import re
    match = re.match(r"([a-z]+)-(old|new)-([\d.]+)mm-v([\d.]+)(.*)$", name)
    if not match:
        return {}
    material, _, _, speed, tag = match.groups()
    meta = dict(material=material, speed=float(speed), horizon=2, dt_factor=0.5)
    if "-h3" in tag:
        meta["horizon"] = 3
    dt = re.search(r"-dt([\d.]+)", tag)
    if dt:
        meta["dt_factor"] = float(dt.group(1))
    window = re.search(r"-w([\d.]+)", tag)
    if window:
        meta["window_ms"] = float(window.group(1))
    return meta


def summarise(name, path, meta=None):
    d = json.loads(Path(path).read_text())
    r = d["measurements"]
    lat = r["lattice"]
    ho = r["handoff"]
    ff = lat.get("first_failure", {})
    meta = meta or META.get(name) or meta_from_name(name)
    cell = r.get("cell_size_m", 0.0)
    row = {
        "name": name,
        "law": "old" if lat.get("failure_law") == "strain-threshold" else "new",
        "failure_law": lat.get("failure_law", "?"),
        "material": meta.get("material", "?"),
        "cell_mm": round(cell * 1000.0, 4),
        "horizon": meta.get("horizon", 0),
        "speed": meta.get("speed", 0.0),
        "dt_factor": meta.get("dt_factor", 0.0),
        "window_ms": meta.get("window_ms", 0.0),
        "exit": {0: "in-flight", 1: "quiet", 2: "no-failure", 3: "capped"}.get(
            lat.get("exit_reason", -1), "?"),
        "last_ms": lat.get("last_failure_s", -1.0) * 1e3,
        "cells": r.get("cells", 0),
        "bonds": r.get("bonds", 0),
        "dt_us": r.get("dt_s", 0.0) * 1e6,
        "substeps": lat.get("steps", 0),
        "lattice_ms": lat.get("simulated_s", 0.0) * 1e3,
        "wall_s": r.get("wall_total_s", 0.0),
        "lattice_wall_s": lat.get("wall_s", 0.0),
        "s_crit": lat.get("critical_stretch", 0.0),
        "s_energy": lat.get("energy_scaled_stretch", 0.0),
        "s_strength": lat.get("strength_stretch", 0.0),
        "bound": "strength" if lat.get("strength_bound_active") else "energy",
        "G_lattice": lat.get("lattice_crack_energy_j_m2", 0.0),
        "broken": lat.get("broken_bonds", 0),
        "rounds": lat.get("failure_rounds", 0),
        "pieces": ho.get("components", 0),
        "p1pct": ho.get("pieces_over_1pct", 0),
        "p5pct": ho.get("pieces_over_5pct", 0),
        "dust": ho.get("mass_fraction_under_1pct", 0.0),
        "largest_kg": ho.get("largest_piece_mass_kg", 0.0),
        "largest_frac": (ho.get("largest_piece_mass_kg", 0.0) / r["tile_mass_kg"]) if r.get("tile_mass_kg") else 0.0,
        "removed_j": lat.get("removed_energy_j", 0.0),
        "first_s": lat.get("first_failure_s", -1.0),
        "first_ms": lat.get("first_failure_s", -1.0) * 1e3,
        "first_bonds": ff.get("bonds", 0),
        "first_depth_mm": ff.get("depth_below_top_m", -1.0) * 1000.0,
        "first_radius_mm": ff.get("radius_from_strike_m", -1.0) * 1000.0,
        "tensile": lat.get("tensile_failures", 0),
        "shear": lat.get("shear_failures", 0),
        "compressive": lat.get("compressive_failures", 0),
        "rest": r.get("rigid", {}).get("came_to_rest", False),
        "ratio": r.get("realtime_ratio", 0.0),
        "tile_mass_kg": r.get("tile_mass_kg", 0.0),
        "exit_reason": lat.get("exit_reason", -1),
    }
    # Derived columns.
    #
    # measured_gc: the energy the criterion actually removed, per unit of crack
    # area counted in the criterion's own accounting (broken bonds x h^2/N_100).
    # Under the energy-scaled law the design value is Gc; the excess is the
    # discrete overshoot (a bond breaks somewhere past its threshold, and the
    # energy removed is its own extension, not the resolved node strain that
    # triggered it).
    #
    # pulverisation: R = (v / c_L) / s_c, the strain the impact puts into the
    # material divided by the stretch at which a bond leaves. R >> 1 means the
    # passing wave takes every bond it touches over the threshold, so damage is
    # diffuse and the fragment size is below the cell size: no piece count can
    # converge there whatever the criterion. R^2 = N_100 rho v^2 h / (2 Gc
    # sum n_x^4), i.e. the kinetic energy in a cell-deep layer over the crack
    # energy of its area, and it FALLS as h^1/2 under refinement.
    mat = MATERIALS.get(row["material"])
    g = horizon_geometry(row["horizon"]) if row["horizon"] else None
    if mat and g and cell > 0.0:
        area = row["broken"] * cell * cell / g["n100"]
        row["crack_area_m2"] = area
        row["measured_gc"] = row["removed_j"] / area if area > 0 else 0.0
        row["measured_over_design"] = (row["measured_gc"] / row["G_lattice"]
                                       if row["G_lattice"] > 0 else 0.0)
        c_long = (mat["E"] * g["nx4"] / row["horizon"] / mat["rho"]) ** 0.5
        row["c_long"] = c_long
        row["pulverisation"] = ((row["speed"] / c_long) / row["s_crit"]
                                if row["s_crit"] > 0 else 0.0)
        row["broken_frac"] = row["broken"] / row["bonds"] if row["bonds"] else 0.0
    return row


def table(rows, cols):
    head = "| " + " | ".join(cols) + " |"
    rule = "|" + "|".join("---" for _ in cols) + "|"
    body = []
    for row in rows:
        cells = []
        for c in cols:
            v = row.get(c, "")
            if isinstance(v, float):
                v = f"{v:.6g}"
            cells.append(str(v))
        body.append("| " + " | ".join(cells) + " |")
    return "\n".join([head, rule, *body])



# ---------------------------------------------------------------------------
# Stages. Each is a named list of rows; `--stage NAME` runs it and prints the
# table. Rows already on disk are reused unless --force is given.
# ---------------------------------------------------------------------------

LADDER_COLS = ("name,law,cell_mm,cells,bonds,dt_us,substeps,lattice_ms,exit,s_crit,G_lattice,"
               "broken,pieces,p1pct,largest_kg,largest_frac,removed_j,first_ms,last_ms,"
               "first_depth_mm,first_radius_mm,lattice_wall_s,wall_s")


def stage_ladder(force, speed=8.0, cells=(0.02, 0.01, 0.005), horizon=2, material="glass",
                 tag=""):
    rows = []
    for law, short in (("strain-threshold", "old"), ("energy-scaled", "new")):
        for cell in cells:
            mm = f"{cell * 1000:g}"
            name = f"{material}-{short}-{mm}mm-v{speed:g}{tag}"
            rows.append(run(name, material=material, cell=cell, speed=speed, law=law,
                            horizon=horizon, force=force,
                            window_ms=WINDOW_MS, settle_s=SETTLE_S))
    return rows


WINDOW_MS = 12.0  # hard cap on the lattice window (5 mm cells: about 8 minutes)
QUIET_MS = 2.0    # exit this long after the last bond failure
SETTLE_S = 0.0    # the ladder measures the lattice phase and the handoff; the playground runs settle


STAGES = {
    "ladder-v8": lambda f: stage_ladder(f, speed=8.0),
    "ladder-v12": lambda f: stage_ladder(f, speed=12.0),
    # Oak is the material whose fragment scale the ladder's cell sizes can
    # resolve: its Gc is 125x glass's, so the same strike opens far less crack
    # area and the pieces stay many cells wide. See section 6 of the checkpoint.
    "ladder-oak-v8": lambda f: stage_ladder(f, speed=8.0, material="oak"),
    "ladder-oak-v12": lambda f: stage_ladder(f, speed=12.0, material="oak"),
    "horizon3": lambda f: stage_ladder(f, speed=8.0, horizon=3, cells=(0.02, 0.01),
                                       material="oak", tag="-h3"),
    "window": lambda f: [
        run(f"oak-{short}-10mm-v8-w{w:g}", material="oak", cell=0.01, speed=8.0, law=law,
            force=f, window_ms=w, settle_s=SETTLE_S)
        for law, short in (("strain-threshold", "old"), ("energy-scaled", "new"))
        for w in (12.0, 24.0)],
    "materials": lambda f: [
        run(f"{m}-{short}-{mm}mm-v8", material=m, cell=c, speed=8.0, law=law, force=f,
            window_ms=WINDOW_MS, settle_s=SETTLE_S)
        for m in ("glass", "oak", "iron") for c, mm in ((0.02, 20), (0.01, 10))
        for law, short in (("strain-threshold", "old"), ("energy-scaled", "new"))],
    # The watchable rows: the same ladder runs with a recording and a full
    # rigid settling phase, so the playground can play them through to rest.
    # Only resolutions whose piece count the rigid world can take are here; the
    # 5 mm energy-scaled row overflows Jolt's contact capacity on handoff
    # (section 6.4), which is itself a measurement.
    "record": lambda f: [
        run(f"rec-{material}-{short}-{mm}mm-v8", material=material, cell=c, speed=8.0,
            law=law, force=f, window_ms=WINDOW_MS, settle_s=6.0, record=True,
            extra=("--frames", "40", "--rigid-frames", "60"))
        for material, c, mm in (("glass", 0.02, 20), ("glass", 0.01, 10),
                                ("oak", 0.02, 20), ("oak", 0.01, 10))
        for law, short in (("strain-threshold", "old"), ("energy-scaled", "new"))],
    "dt-half": lambda f: [
        run(f"oak-{short}-10mm-v8-dt{d:g}", material="oak", cell=0.01, speed=8.0,
            law=law, dt_factor=d, force=f, window_ms=WINDOW_MS, settle_s=SETTLE_S)
        for law, short in (("strain-threshold", "old"), ("energy-scaled", "new"))
        for d in (0.5, 0.25)],
}


def convergence(rows, keys=("pieces", "largest_kg", "removed_j", "broken", "first_ms")):
    """Relative change between successive ladder levels.

    The gate the brief sets is that removed energy, largest piece and piece
    count approach a limit as the cells shrink, so what matters is |x(h/2) -
    x(h)| / |x(h)| falling from one level to the next. Rows must be one law and
    one material, coarse to fine.
    """
    out = []
    for previous, current in zip(rows, rows[1:]):
        line = {"from": f"{previous['cell_mm']:g} mm", "to": f"{current['cell_mm']:g} mm"}
        for key in keys:
            a, b = previous.get(key, 0.0), current.get(key, 0.0)
            line[key] = f"{b - a:+.4g} ({(b - a) / a * 100:+.0f}%)" if a else f"{b:+.4g} (n/a)"
        out.append(line)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stage", action="append", default=[], help=f"one of {sorted(STAGES)}")
    ap.add_argument("--summarise", nargs="*", default=[], help="report names already on disk")
    ap.add_argument("--force", action="store_true", help="re-run rows whose report exists")
    ap.add_argument("--cols", default=LADDER_COLS)
    ap.add_argument("--converge", action="store_true",
                    help="also print the level-to-level relative change, per law")
    a = ap.parse_args()
    rows = []
    for st in a.stage:
        rows += STAGES[st](a.force)
    rows += [summarise(n, OUT / f"{n}.json") for n in a.summarise]
    print()
    print(table(rows, a.cols.split(",")))
    if a.converge:
        groups = {}
        for row in rows:
            groups.setdefault((row["material"], row["law"], row["speed"], row["horizon"],
                               row["dt_factor"]), []).append(row)
        for key, group in groups.items():
            group.sort(key=lambda r: -r["cell_mm"])
            lines = convergence(group)
            if not lines:
                continue
            print("")
            print(f"level-to-level change - {key[0]}, {key[1]} law, {key[2]:g} m/s, "
                  f"horizon {key[3]}, dt factor {key[4]:g}")
            print(table(lines, list(lines[0].keys())))
