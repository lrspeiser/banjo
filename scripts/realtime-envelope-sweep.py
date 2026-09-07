#!/usr/bin/env python3
"""Measure where each Banjo solver lane reaches 1x realtime.

Measurement only: this driver never passes a flag that changes solver
tolerances, material constants or acceptance budgets. It varies node count
(voxel size), timestep and material preset, and records what the probe
reports. Cells that exceed the per-cell wall budget are left empty rather
than extrapolated.

Usage:
  python scripts/realtime-envelope-sweep.py <phase> [--out DIR]

Phases: nodes | implicit | sustained | dtboundary | explicit | explicit_dt | duration
"""
import argparse
import csv
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROBE = os.path.join(ROOT, "build", "agent", "Release", "banjo_solver_probe.exe")
PLATFORM = os.path.join(ROOT, "build", "agent", "Release", "banjo_platform_cli.exe")

MATERIALS = ["glass", "oak", "iron"]
# Voxel sizes for the fixed 0.25 m sphere lattice; h alone sets node count.
# 0.16 is omitted: it samples the same 27-node lattice as 0.20.
VOXELS = [0.25, 0.20, 0.12, 0.10, 0.08, 0.06, 0.05, 0.04, 0.035, 0.03]
# Finer ladder for the sustained sweep, refined where the 1x crossing sits.
VOXELS_SUSTAINED = [0.20, 0.12, 0.10, 0.08, 0.075, 0.07, 0.065, 0.06, 0.055,
                    0.05, 0.045, 0.04]
# Frame-rate timesteps plus the 2 ms step used by the existing checkpoint.
TIMESTEPS = [
    ("1/30", 1.0 / 30.0),
    ("1/60", 1.0 / 60.0),
    ("1/120", 1.0 / 120.0),
    ("1/240", 1.0 / 240.0),
    ("2ms", 0.002),
    ("1/480", 1.0 / 480.0),
    ("1/960", 1.0 / 960.0),
]


def run_probe(material, h, dt, steps, timeout_s):
    """Run the probe once. Returns (record, raw_stdout) or (None, reason)."""
    cmd = [PROBE, "--material", material, "--voxel-size", repr(h),
           "--dt", repr(dt), "--steps", str(steps)]
    t0 = time.perf_counter()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return None, "timeout>%gs" % timeout_s
    wall = time.perf_counter() - t0
    nodes = bonds = None
    rows = []
    for line in p.stdout.splitlines():
        if line.startswith("nodes="):
            parts = dict(kv.split("=", 1) for kv in line.split() if "=" in kv)
            nodes, bonds = int(parts["nodes"]), int(parts["bonds"])
        elif line and line[0].isdigit() and "," in line:
            f = line.split(",")
            rows.append({"accepted": int(f[1]), "iters": int(f[2]),
                         "linear": int(f[3]), "resid": float(f[4]),
                         "wall_ms": float(f[6])})
    return {"cmd": " ".join(cmd), "exit": p.returncode, "nodes": nodes,
            "bonds": bonds, "rows": rows, "process_wall_s": wall}, p.stdout


def summarize(all_rows):
    w = sorted(r["wall_ms"] for r in all_rows)
    n = len(w)
    return {
        "n": n,
        "min_ms": w[0],
        "med_ms": statistics.median(w),
        "p95_ms": w[min(n - 1, int(0.95 * n))],
        "max_ms": w[-1],
    }


def phase_nodes(out):
    path = os.path.join(out, "envelope-lattice-sizes.csv")
    with open(path, "w", newline="") as fh:
        wr = csv.writer(fh)
        wr.writerow(["voxel_size_m", "nodes", "bonds"])
        for h in VOXELS:
            rec, _ = run_probe("glass", h, 1.0 / 240.0, 1, 600)
            wr.writerow([h, rec["nodes"], rec["bonds"]])
            print("h=%.3f nodes=%d bonds=%d" % (h, rec["nodes"], rec["bonds"]), flush=True)
    print("wrote", path)


def phase_implicit(out, steps, repeats, budget_s):
    path = os.path.join(out, "envelope-implicit-sweep.csv")
    with open(path, "w", newline="") as fh:
        wr = csv.writer(fh)
        wr.writerow(["material", "voxel_size_m", "nodes", "bonds", "dt_label", "dt_s",
                     "steps", "repeats", "accepted_steps", "outer_min", "outer_max",
                     "linear_min", "linear_max", "max_velocity_residual_m_s",
                     "wall_min_ms", "wall_med_ms", "wall_p95_ms", "wall_max_ms",
                     "realtime_ratio_med", "status"])
        for material in MATERIALS:
            for h in VOXELS:
                for label, dt in TIMESTEPS:
                    rows, exits, nodes, bonds = [], [], None, None
                    status = "ok"
                    for _rep in range(repeats):
                        rec, reason = run_probe(material, h, dt, steps, budget_s)
                        if rec is None:
                            status = "not-run:" + str(reason)
                            break
                        nodes, bonds = rec["nodes"], rec["bonds"]
                        exits.append(rec["exit"])
                        rows.extend(rec["rows"])
                        if rec["exit"] != 0:
                            break
                        # Stop repeating a cell that is already expensive; the
                        # 12 in-run steps still give a spread for it.
                        if rec["process_wall_s"] > 20.0:
                            status = "ok (repeats cut to %d for cost)" % (_rep + 1)
                            break
                    if not rows:
                        wr.writerow([material, h, nodes, bonds, label, dt, steps, repeats,
                                     "", "", "", "", "", "", "", "", "", "", "", status])
                        continue
                    acc = sum(r["accepted"] for r in rows)
                    s = summarize(rows)
                    if any(e != 0 for e in exits):
                        status = "rejected"
                    ratio = s["med_ms"] / (dt * 1000.0)
                    wr.writerow([material, h, nodes, bonds, label, dt, steps, repeats,
                                 "%d/%d" % (acc, len(rows)),
                                 min(r["iters"] for r in rows), max(r["iters"] for r in rows),
                                 min(r["linear"] for r in rows), max(r["linear"] for r in rows),
                                 "%.6g" % max(r["resid"] for r in rows),
                                 "%.4f" % s["min_ms"], "%.4f" % s["med_ms"],
                                 "%.4f" % s["p95_ms"], "%.4f" % s["max_ms"],
                                 "%.4g" % ratio, status])
                    print("%-5s h=%.3f n=%s %-6s med=%.3fms ratio=%.4g %s" %
                          (material, h, nodes, label, s["med_ms"], ratio, status), flush=True)
                    fh.flush()
    print("wrote", path)


def phase_sustained(out, sim_s, repeats, budget_s):
    """Realtime ratio measured over an identical simulated duration.

    Per-step solver work grows as internal elastic modes develop, so a fixed
    step count would flatter small timesteps (they cover less simulated time).
    Every cell here advances the same sim_s of simulated time from the same
    rigid initial state, and the ratio is summed solver wall time divided by
    simulated time: 1.0 is exactly realtime.
    """
    path = os.path.join(out, "envelope-implicit-sustained.csv")
    dts = [("1/60", 1.0 / 60.0), ("1/120", 1.0 / 120.0), ("1/240", 1.0 / 240.0),
           ("1/480", 1.0 / 480.0), ("1/960", 1.0 / 960.0)]
    with open(path, "w", newline="") as fh:
        wr = csv.writer(fh)
        wr.writerow(["material", "voxel_size_m", "nodes", "bonds", "dt_label", "dt_s",
                     "simulated_s", "steps", "repeats", "accepted_steps",
                     "outer_min", "outer_max", "linear_min", "linear_max",
                     "solver_wall_s_per_simulated_s_min", "solver_wall_s_per_simulated_s_med",
                     "solver_wall_s_per_simulated_s_max", "wall_med_ms_per_step",
                     "wall_p95_ms_per_step", "status"])
        for material in MATERIALS:
            for h in VOXELS_SUSTAINED:
                for label, dt in dts:
                    steps = max(1, int(round(sim_s / dt)))
                    ratios, rows, nodes, bonds = [], [], None, None
                    status, exits = "ok", []
                    for _rep in range(repeats):
                        rec, reason = run_probe(material, h, dt, steps, budget_s)
                        if rec is None:
                            status = "not-run:" + str(reason)
                            break
                        nodes, bonds = rec["nodes"], rec["bonds"]
                        exits.append(rec["exit"])
                        rows.extend(rec["rows"])
                        if rec["exit"] != 0:
                            status = "rejected"
                            break
                        ratios.append(sum(r["wall_ms"] for r in rec["rows"]) / 1000.0 / sim_s)
                        if rec["process_wall_s"] > 25.0:
                            status = "ok (repeats cut to %d for cost)" % (_rep + 1)
                            break
                    if not rows:
                        wr.writerow([material, h, nodes, bonds, label, dt, sim_s, steps,
                                     repeats] + [""] * 10 + [status])
                        fh.flush()
                        continue
                    w = sorted(r["wall_ms"] for r in rows)
                    acc = sum(r["accepted"] for r in rows)
                    wr.writerow([material, h, nodes, bonds, label, "%.6g" % dt, sim_s, steps,
                                 len(ratios) or 1, "%d/%d" % (acc, len(rows)),
                                 min(r["iters"] for r in rows), max(r["iters"] for r in rows),
                                 min(r["linear"] for r in rows), max(r["linear"] for r in rows),
                                 "%.4g" % min(ratios) if ratios else "",
                                 "%.4g" % statistics.median(ratios) if ratios else "",
                                 "%.4g" % max(ratios) if ratios else "",
                                 "%.4f" % statistics.median(w),
                                 "%.4f" % w[min(len(w) - 1, int(0.95 * len(w)))], status])
                    fh.flush()
                    print("%-5s h=%.3f n=%s %-6s steps=%d ratio=%s %s"
                          % (material, h, nodes, label, steps,
                             ("%.4g" % statistics.median(ratios)) if ratios else "-", status),
                          flush=True)
    print("wrote", path)


def accepts(material, h, dt, steps, budget_s):
    rec, _ = run_probe(material, h, dt, steps, budget_s)
    if rec is None:
        return None, None
    ok = rec["exit"] == 0 and rec["rows"] and all(r["accepted"] for r in rec["rows"])
    return ok, rec


def phase_dtboundary(out, steps, budget_s):
    """Bisect the largest accepted timestep for each (material, voxel size)."""
    path = os.path.join(out, "envelope-timestep-boundary.csv")
    with open(path, "w", newline="") as fh:
        wr = csv.writer(fh)
        wr.writerow(["material", "voxel_size_m", "nodes", "steps_required",
                     "largest_accepted_dt_s", "largest_accepted_hz",
                     "smallest_rejected_dt_s", "wall_ms_at_largest_accepted",
                     "outer_at_largest", "linear_at_largest", "status"])
        for material in MATERIALS:
            for h in VOXELS:
                # Search 1/3840 s (assumed accepted) up to 1/30 s; no
                # visualiser needs a step coarser than one 30 Hz frame.
                lo, hi = 1.0 / 3840.0, 1.0 / 30.0
                ok_lo, rec_lo = accepts(material, h, lo, steps, budget_s)
                if ok_lo is None or not ok_lo:
                    wr.writerow([material, h, rec_lo["nodes"] if rec_lo else "", steps,
                                 "", "", "", "", "", "",
                                 "no accepted step at 1/3840" if ok_lo is not None else "not-run"])
                    fh.flush()
                    continue
                nodes = rec_lo["nodes"]
                ok_hi, _ = accepts(material, h, hi, steps, budget_s)
                if ok_hi:
                    wr.writerow([material, h, nodes, steps, hi, 1.0 / hi, "", "", "", "",
                                 "accepted at the 1/30 s search ceiling"])
                    fh.flush()
                    continue
                best = (lo, rec_lo)
                for _ in range(7):  # ~4% bracket on the log scale
                    mid = (lo * hi) ** 0.5
                    ok, rec = accepts(material, h, mid, steps, budget_s)
                    if ok is None:
                        break
                    if ok:
                        lo, best = mid, (mid, rec)
                    else:
                        hi = mid
                dt_best, rec = best
                s = summarize(rec["rows"])
                wr.writerow([material, h, nodes, steps, "%.6g" % dt_best,
                             "%.4g" % (1.0 / dt_best), "%.6g" % hi,
                             "%.4f" % s["med_ms"],
                             max(r["iters"] for r in rec["rows"]),
                             max(r["linear"] for r in rec["rows"]), "ok"])
                fh.flush()
                print("%-5s h=%.3f n=%d largest accepted dt=%.6g s (%.1f Hz) "
                      "first rejected %.6g wall=%.3f ms"
                      % (material, h, nodes, dt_best, 1.0 / dt_best, hi, s["med_ms"]),
                      flush=True)
    print("wrote", path)


# ---------------------------------------------------------------------------
# Explicit lane
# ---------------------------------------------------------------------------
PANEL_MATERIALS = None  # filled from an existing asset so constants are unchanged


def load_reference_package():
    with open(os.path.join(ROOT, "assets", "material-showcase",
                           "01-clamped-panels-02mps.json")) as fh:
        return json.load(fh)


def make_panel_package(material, res, dt):
    """One clamped panel of the requested material, with the shipped material
    constants copied verbatim from the showcase package."""
    ref = load_reference_package()
    pkg = {k: v for k, v in ref.items() if k not in ("objects", "name")}
    pkg["name"] = "realtime envelope probe: %s panel %dx%dx%d" % ((material,) + tuple(res))
    pkg["fixed_dt_s"] = dt
    pkg["ground"] = None
    pkg["objects"] = [{
        "id": 1, "name": "panel", "material": material, "shape": "box",
        "dimensions_m": [0.24, 0.36, 0.04], "representation": "network",
        "position_m": [0, 0.2, 0], "orientation_wxyz": [1, 0, 0, 0],
        "velocity_m_s": [0, 0, 0], "spin_rad_s": [0, 0, 0],
        "resolution": list(res), "pin_boundary": True,
    }]
    return pkg


def run_platform(pkg_path, steps, timeout_s):
    t0 = time.perf_counter()
    try:
        p = subprocess.run([PLATFORM, "--run", pkg_path, str(steps)],
                           capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return None, None
    wall = time.perf_counter() - t0
    try:
        return json.loads(p.stdout), wall
    except json.JSONDecodeError:
        return None, wall


def phase_explicit(out, repeats, budget_s):
    """Per-step cost by differencing two step counts, so process start-up,
    package load and report serialization cancel out."""
    path = os.path.join(out, "envelope-explicit-sweep.csv")
    tmp = tempfile.mkdtemp(prefix="banjo-envelope-")
    cases = []
    for material in MATERIALS:
        for res in [(3, 4, 1), (4, 6, 2), (5, 7, 2), (6, 9, 2), (8, 12, 3),
                    (10, 15, 4), (12, 18, 4)]:
            cases.append((material, res, 1.0 / 480.0))
    # Does per-step cost depend on the timestep in this lane?
    for dt in [1.0 / 240.0, 1.0 / 960.0, 1.0 / 1920.0, 1.0 / 4800.0]:
        cases.append(("glass", (6, 9, 2), dt))
    with open(path, "w", newline="") as fh:
        wr = csv.writer(fh)
        wr.writerow(["material", "resolution", "cells", "links", "dt_s", "repeats",
                     "wall_per_step_ms", "wall_per_step_spread_ms",
                     "realtime_ratio_as_run", "max_pair_frequency_rad_s",
                     "step_times_pair_frequency", "resolved_max_step_s",
                     "required_substeps", "temporally_resolved", "status"])
        shipped = [
            ("assets/material-showcase/01-clamped-panels-02mps.json", "shipped 3 panels + 3 balls"),
            ("assets/runtime-v2/03-axe-oak-panel.json", "shipped axe + oak panel"),
            ("assets/runtime-v2/08-free-flight.json", "shipped 4 free-flight objects"),
        ]
        for rel, note in shipped:
            pkg_path = os.path.join(ROOT, *rel.split("/"))
            with open(pkg_path) as pf:
                dt = json.load(pf)["fixed_dt_s"]
            cases.append((note, None, dt, pkg_path))
        for entry in cases:
            if len(entry) == 4:
                material, res, dt, pkg_path = entry
                res_label = "shipped"
            else:
                material, res, dt = entry
                res_label = "x".join(map(str, res))
                pkg = make_panel_package(material, res, dt)
                pkg_path = os.path.join(tmp, "%s-%d%d%d-%g.json"
                                        % ((material,) + tuple(res) + (dt,)))
                with open(pkg_path, "w") as pf:
                    json.dump(pkg, pf, indent=1)
            lo_steps, hi_steps = 40, 1040
            per_step, report = [], None
            failed = ""
            for _ in range(repeats):
                r1, w1 = run_platform(pkg_path, lo_steps, budget_s)
                r2, w2 = run_platform(pkg_path, hi_steps, budget_s)
                if r1 is None or r2 is None or "error" in (r1 or {}) or "error" in (r2 or {}):
                    failed = (r1 or r2 or {}).get("error", "timeout")
                    break
                report = r2
                per_step.append(1000.0 * (w2 - w1) / (hi_steps - lo_steps))
            if not per_step:
                wr.writerow([material, res_label, "", "", dt, repeats,
                             "", "", "", "", "", "", "", "", "not-run:" + str(failed)[:60]])
                fh.flush()
                continue
            med = statistics.median(per_step)
            tr = report["temporal_resolution"]
            # Worst network object in the package sets the resolution demand.
            worst = max(report["objects"],
                        key=lambda o: o["max_isolated_pair_frequency_rad_s"])
            wr.writerow([material, res_label, report["cells"], report["links"],
                         dt, len(per_step), "%.4f" % med,
                         "%.4f" % (max(per_step) - min(per_step)),
                         "%.4g" % (med / (dt * 1000.0)),
                         "%.6g" % worst["max_isolated_pair_frequency_rad_s"],
                         "%.6g" % worst["step_times_pair_frequency"],
                         "%.6g" % tr["maximum_step_s"], tr["required_substeps"],
                         tr["resolved"], "ok"])
            fh.flush()
            print("%-22s %-8s cells=%d dt=%.6g per_step=%.4f ms ratio=%.4g substeps=%d"
                  % (material, res_label, report["cells"], dt, med, med / (dt * 1000.0),
                     tr["required_substeps"]), flush=True)
    shutil.rmtree(tmp, ignore_errors=True)
    print("wrote", path)


def phase_explicit_dt(out, repeats, budget_s):
    """Explicit-lane per-step cost over a *matched simulated window*.

    The step-count differencing used by phase_explicit compares different
    simulated windows when dt changes, which confounds a timestep comparison
    (Jolt bodies can fall asleep, and a coarse step reaches quiescence in fewer
    steps). Here every dt is measured over simulated time 0.1 s -> 0.5 s, and a
    second block walks three successive windows at one fixed dt to show how
    much of the cost is the scene going quiet.
    """
    path = os.path.join(out, "envelope-explicit-timestep.csv")
    tmp = tempfile.mkdtemp(prefix="banjo-envelope-dt-")
    dts = [1.0 / 240.0, 1.0 / 480.0, 1.0 / 960.0, 1.0 / 1920.0, 1.0 / 4800.0]
    windows = [(0.1, 0.5), (0.5, 1.0), (1.0, 2.0)]
    with open(path, "w", newline="") as fh:
        wr = csv.writer(fh)
        wr.writerow(["material", "resolution", "cells", "dt_s", "window_from_s",
                     "window_to_s", "steps_in_window", "repeats",
                     "wall_per_step_ms", "wall_per_step_spread_ms",
                     "realtime_ratio_as_run", "resolved_max_step_s",
                     "required_substeps", "status"])
        cases = [("glass", (6, 9, 2), dt, windows[0]) for dt in dts]
        cases += [("glass", (6, 9, 2), 1.0 / 480.0, w) for w in windows[1:]]
        cases += [(m, (6, 9, 2), 1.0 / 480.0, windows[0]) for m in ("oak", "iron")]
        # Cell-count ladder over the same awake window, so the explicit lane's
        # node-count scaling is not contaminated by Jolt putting cells to sleep.
        for m in MATERIALS:
            for res in [(4, 6, 2), (5, 7, 2), (8, 12, 3), (10, 15, 4), (10, 16, 5)]:
                cases.append((m, res, 1.0 / 480.0, windows[0]))
        for material, res, dt, (t0, t1) in cases:
            pkg = make_panel_package(material, res, dt)
            pkg_path = os.path.join(tmp, "%s-%d%d%d-%g-%g.json"
                                    % ((material,) + tuple(res) + (dt, t0)))
            with open(pkg_path, "w") as pf:
                json.dump(pkg, pf, indent=1)
            lo, hi = int(round(t0 / dt)), int(round(t1 / dt))
            per_step, report, failed = [], None, ""
            for _ in range(repeats):
                r1, w1 = run_platform(pkg_path, lo, budget_s)
                r2, w2 = run_platform(pkg_path, hi, budget_s)
                if r1 is None or r2 is None or "error" in (r1 or {}) or "error" in (r2 or {}):
                    failed = (r1 or r2 or {}).get("error", "timeout")
                    break
                report = r2
                per_step.append(1000.0 * (w2 - w1) / (hi - lo))
            if not per_step:
                wr.writerow([material, "x".join(map(str, res)), "", dt, t0, t1,
                             hi - lo, repeats, "", "", "", "", "",
                             "not-run:" + str(failed)[:60]])
                fh.flush()
                continue
            med = statistics.median(per_step)
            tr = report["temporal_resolution"]
            wr.writerow([material, "x".join(map(str, res)), report["cells"], "%.6g" % dt,
                         t0, t1, hi - lo, len(per_step), "%.4f" % med,
                         "%.4f" % (max(per_step) - min(per_step)),
                         "%.4g" % (med / (dt * 1000.0)),
                         "%.6g" % tr["maximum_step_s"], tr["required_substeps"], "ok"])
            fh.flush()
            print("%-5s dt=%.6g window %.1f-%.1f s: %.4f ms/step ratio=%.4g substeps=%d"
                  % (material, dt, t0, t1, med, med / (dt * 1000.0),
                     tr["required_substeps"]), flush=True)
    shutil.rmtree(tmp, ignore_errors=True)
    print("wrote", path)


def phase_duration(out, budget_s):
    """Does the implicit lane's per-step cost drift over a long run?

    The 0.2 s headline window is short. This advances the same configurations
    for 4 s of simulated time and reports the cost of each successive 0.5 s
    block, so the headline ratio can be checked against a sustained one.
    """
    path = os.path.join(out, "envelope-implicit-duration.csv")
    cases = [("glass", 0.065, 1.0 / 120.0), ("oak", 0.065, 1.0 / 120.0),
             ("iron", 0.065, 1.0 / 120.0), ("glass", 0.06, 1.0 / 120.0),
             ("glass", 0.04, 1.0 / 240.0),
             ("glass", 0.07, 1.0 / 120.0), ("oak", 0.07, 1.0 / 120.0),
             ("iron", 0.07, 1.0 / 120.0),
             ("glass", 0.075, 1.0 / 60.0), ("oak", 0.075, 1.0 / 60.0),
             ("iron", 0.075, 1.0 / 60.0),
             ("glass", 0.08, 1.0 / 60.0), ("oak", 0.08, 1.0 / 60.0),
             ("iron", 0.08, 1.0 / 60.0)]
    with open(path, "w", newline="") as fh:
        wr = csv.writer(fh)
        wr.writerow(["material", "voxel_size_m", "nodes", "dt_s", "simulated_s",
                     "block_from_s", "block_to_s", "block_ratio",
                     "block_wall_med_ms_per_step", "block_linear_min",
                     "block_linear_max", "whole_run_ratio", "accepted_steps", "status"])
        for material, h, dt in cases:
            total_s = 4.0
            steps = int(round(total_s / dt))
            rec, reason = run_probe(material, h, dt, steps, budget_s)
            if rec is None or rec["exit"] != 0:
                wr.writerow([material, h, rec["nodes"] if rec else "", "%.6g" % dt,
                             total_s, "", "", "", "", "", "", "", "",
                             "rejected" if rec else "not-run:" + str(reason)])
                fh.flush()
                continue
            rows = rec["rows"]
            whole = sum(r["wall_ms"] for r in rows) / 1000.0 / total_s
            block_steps = int(round(0.5 / dt))
            for b in range(0, len(rows), block_steps):
                chunk = rows[b:b + block_steps]
                if not chunk:
                    continue
                ratio = sum(r["wall_ms"] for r in chunk) / 1000.0 / (len(chunk) * dt)
                wr.writerow([material, h, rec["nodes"], "%.6g" % dt, total_s,
                             "%.3f" % (b * dt), "%.3f" % ((b + len(chunk)) * dt),
                             "%.4g" % ratio,
                             "%.4f" % statistics.median([r["wall_ms"] for r in chunk]),
                             min(r["linear"] for r in chunk),
                             max(r["linear"] for r in chunk),
                             "%.4g" % whole,
                             "%d/%d" % (sum(r["accepted"] for r in rows), len(rows)), "ok"])
            fh.flush()
            print("%-5s h=%.3f n=%d dt=%.6g  whole-run ratio over %.1f s = %.4g"
                  % (material, h, rec["nodes"], dt, total_s, whole), flush=True)
    print("wrote", path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=["nodes", "implicit", "sustained", "dtboundary",
                                     "explicit", "explicit_dt", "duration"])
    ap.add_argument("--sim", type=float, default=0.2, help="simulated seconds per sustained cell")
    ap.add_argument("--out", default=os.path.join(ROOT, "docs", "evidence"))
    ap.add_argument("--steps", type=int, default=12)
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--budget", type=float, default=120.0,
                    help="per-probe wall budget in seconds; over-budget cells stay empty")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    if a.phase == "nodes":
        phase_nodes(a.out)
    elif a.phase == "implicit":
        phase_implicit(a.out, a.steps, a.repeats, a.budget)
    elif a.phase == "sustained":
        phase_sustained(a.out, a.sim, a.repeats, a.budget)
    elif a.phase == "dtboundary":
        phase_dtboundary(a.out, a.steps, a.budget)
    elif a.phase == "explicit":
        phase_explicit(a.out, a.repeats, a.budget)
    elif a.phase == "explicit_dt":
        phase_explicit_dt(a.out, a.repeats, a.budget)
    else:
        phase_duration(a.out, a.budget)
    return 0


if __name__ == "__main__":
    sys.exit(main())
