#!/usr/bin/env python3
"""Run and summarise the energy-scaled criterion's convergence ladder.

Each row is one banjo_fast_lattice_run report. The script only launches the
tool and reads the JSON it writes; every number below comes from the run.
"""
import argparse, json, os, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
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
        args += ["--quiet-ms", "0", "--no-failure-ms", "0", "--min-ms", "0",
                 "--max-ms", str(window_ms)]
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


def summarise(name, path, meta=None):
    d = json.loads(Path(path).read_text())
    r = d["measurements"]
    lat = r["lattice"]
    ho = r["handoff"]
    ff = lat.get("first_failure", {})
    meta = meta or META.get(name, {})
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

LADDER_COLS = ("name,law,cell_mm,cells,bonds,dt_us,substeps,s_crit,G_lattice,"
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


WINDOW_MS = 6.0   # the fixed lattice window every ladder row runs for
SETTLE_S = 0.0    # the ladder measures the lattice phase and the handoff; the playground runs settle


STAGES = {
    "ladder-v8": lambda f: stage_ladder(f, speed=8.0),
    "ladder-v12": lambda f: stage_ladder(f, speed=12.0),
    "horizon3": lambda f: stage_ladder(f, speed=8.0, horizon=3, tag="-h3"),
    "materials": lambda f: [
        run(f"{m}-{short}-{mm}mm-v8", material=m, cell=c, speed=8.0, law=law, force=f,
            window_ms=WINDOW_MS, settle_s=SETTLE_S)
        for m in ("glass", "oak", "iron") for c, mm in ((0.02, 20), (0.01, 10))
        for law, short in (("strain-threshold", "old"), ("energy-scaled", "new"))],
    "dt-half": lambda f: [
        run(f"glass-{short}-10mm-v8-dt{d:g}", material="glass", cell=0.01, speed=8.0,
            law=law, dt_factor=d, force=f, window_ms=WINDOW_MS, settle_s=SETTLE_S)
        for law, short in (("strain-threshold", "old"), ("energy-scaled", "new"))
        for d in (0.5, 0.25)],
}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stage", action="append", default=[], help=f"one of {sorted(STAGES)}")
    ap.add_argument("--summarise", nargs="*", default=[], help="report names already on disk")
    ap.add_argument("--force", action="store_true", help="re-run rows whose report exists")
    ap.add_argument("--cols", default=LADDER_COLS)
    a = ap.parse_args()
    rows = []
    for st in a.stage:
        rows += STAGES[st](a.force)
    rows += [summarise(n, OUT / f"{n}.json") for n in a.summarise]
    print()
    print(table(rows, a.cols.split(",")))
