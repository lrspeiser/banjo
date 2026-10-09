"""Opt-in GPU compatibility/primitive benchmark; NOT a complete world solver.

Run from a VS x64 developer environment (nvcc needs cl on Windows):
python scripts/cupy-physics-probe.py --report build/cupy-probe/results.json
No physics implementation is copied: RawModule compiles LatticePhysics.hpp.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
KERNEL = r'''
#include "fastlattice/LatticePhysics.hpp"
extern "C" __global__ void bonds(const double* inputs, double* outputs, unsigned n) {
    const unsigned i = blockDim.x * blockIdx.x + threadIdx.x;
    if (i >= n) return;
    const double* p = inputs + 18 * i;
    double u[6] = {p[3], p[4], p[5], p[6], p[7], p[8]};
    const double edge[3] = {p[0], p[1], p[2]};
    const double inv_mass[2] = {p[9], p[10]};
    const double rest[1] = {p[11]}, compliance[1] = {p[12]};
    double plastic[1] = {p[13]};
    const double rest_sq_minus[1] = {p[0]*p[0] + p[1]*p[1] + p[2]*p[2] - p[11]*p[11]};
    const std::uint32_t a[1] = {0}, b[1] = {1};
    std::uint8_t alive[1] = {static_cast<std::uint8_t>(p[16])};
    double lambda[1] = {p[15]};
    banjo::fastlattice::LatticeArrays<double> state{};
    state.u = u; state.inv_mass = inv_mass; state.rest_edge = edge;
    state.rest_length = rest; state.compliance = compliance;
    state.plastic_extension = plastic; state.rest_length_sq_minus = rest_sq_minus;
    state.bond_a = a; state.bond_b = b; state.alive = alive; state.accumulated_lambda = lambda;
    banjo::fastlattice::bondSolve(state, 0, p[14], false, p[17] != 0);
    for (unsigned k = 0; k < 6; ++k) outputs[7*i+k] = u[k];
    outputs[7*i+6] = lambda[0];
}
'''


def inputs(np, count, density, young):
    rng = np.random.default_rng(98217)
    p = np.zeros((count, 18), dtype=np.float64)
    direction = rng.normal(size=(count, 3))
    direction /= np.linalg.norm(direction, axis=1)[:, None]
    length = 0.02
    p[:, :3] = length * direction
    p[:, 3:9] = rng.uniform(-0.001, 0.001, (count, 6))
    p[:, 9:11] = 1 / (density * length**3)
    p[:, 11] = length
    # Explicit coupon assumption k = E*A/L. This is an axial coupon, not a
    # replacement for the catalog's horizon-weighted or six-mode interface.
    p[:, 12] = length / (young * length**2)
    p[:, 14] = 1 / 1920
    p[:, 16:18] = 1
    p[::11, 13] = 0.0002  # retained plastic rest, not a metal constitutive claim
    p[::7, 16] = 0  # dead bonds must do nothing
    p[::13, 9] = 0  # fixed endpoint; do not claim closed-system COM here
    p[::17, 17] = 0
    p[::17, 15] = 1e-7  # accumulated XPBD multiplier, kg*m
    if count > 1:
        p[1, :3] = 0
        p[1, 3:9] = 0  # zero-length early return
    return p


def oracle(np, p):
    out = np.column_stack((p[:, 3:9], p[:, 15]))
    d = p[:, :3] + p[:, 6:9] - p[:, 3:6]
    length = np.linalg.norm(d, axis=1)
    use = (p[:, 16] != 0) & (length > 1e-12)
    q = p[use]
    # Independent length-form XPBD oracle; the shared source uses a
    # cancellation-resistant difference-of-squares displacement expression.
    c = length[use] - q[:, 11] - q[:, 13]
    alpha = q[:, 12] / q[:, 14]**2
    previous = np.where(q[:, 17] != 0, 0, q[:, 15])
    dl = (-c - alpha * previous) / (q[:, 9] + q[:, 10] + alpha)
    impulse = dl[:, None] * d[use] / length[use, None]
    out[use, :3] -= q[:, 9, None] * impulse
    out[use, 3:6] += q[:, 10, None] * impulse
    out[use, 6] = previous + dl
    return out


def run(report_path):
    # CuPy 13.5 splits its default absolute nvcc path at spaces on Windows.
    # The developer environment already supplies the correctly resolved PATH.
    if platform.system() == "Windows":
        os.environ.setdefault("NVCC", "nvcc")
    import cupy as cp
    import numpy as np

    props = cp.cuda.runtime.getDeviceProperties(0)
    header_hash = hashlib.sha256((ROOT/"src/fastlattice/LatticePhysics.hpp").read_bytes()).hexdigest()
    # CuPy caches the top-level source, not changes to #included project files.
    module = cp.RawModule(code=KERNEL + f"\n// shared-source-sha256: {header_hash}\n", backend="nvcc", options=(
        "--std=c++17", "--fmad=false", f"-I{ROOT / 'src'}"))
    kernel = module.get_function("bonds")  # compilation excluded from warm timings
    rows = []
    for material, density, young in (
        ("glass", 2500., 70e9), ("oak", 700., 12e9),
        ("iron", 7870., 211e9), ("ice", 917., 9e9),
    ):
        for count in (128, 4096, 65536):
            host = inputs(np, count, density, young)
            expected = oracle(np, host)
            device = cp.asarray(host)
            output = cp.empty((count, 7), dtype=cp.float64)
            launch = lambda: kernel(((count + 127)//128,), (128,),
                                    (device, output, np.uint32(count)))
            launch()
            cp.cuda.get_current_stream().synchronize()
            actual = cp.asnumpy(output)
            pose_error = float(np.max(np.abs(actual[:, :6] - expected[:, :6])))
            lambda_error = float(np.max(np.abs(actual[:, 6] - expected[:, 6])))
            assert np.isfinite(actual).all()
            assert pose_error < 1e-12 and lambda_error < 1e-12, (material, count, pose_error, lambda_error)
            free = (host[:, 9] > 0) & (host[:, 10] > 0)
            delta = actual[:, :6] - host[:, 3:9]
            weighted_shift = (delta[free, :3] / host[free, 9, None]
                              + delta[free, 3:] / host[free, 10, None])
            com_numerator = float(np.max(np.abs(weighted_shift)))
            assert com_numerator < 1e-14  # kg*m, local pair only
            first = (host[:, 17] != 0) & (host[:, 16] != 0)
            before_extension = np.linalg.norm(host[:, :3] + host[:, 6:9] - host[:, 3:6], axis=1) - host[:, 11] - host[:, 13]
            after_extension = np.linalg.norm(host[:, :3] + actual[:, 3:6] - actual[:, :3], axis=1) - host[:, 11] - host[:, 13]
            energy_change = (after_extension**2 - before_extension**2) / (2*host[:, 12])
            max_elastic_gain = float(np.max(energy_change[first]))
            assert max_elastic_gain < 1e-10  # J; projection energy, not a dynamics audit
            gpu_ms, total_ms, numpy_ms = [], [], []
            for _ in range(9):
                start, end = cp.cuda.Event(), cp.cuda.Event()
                start.record()
                for _ in range(100):
                    launch()  # independent evaluations, not 100 simulated steps
                end.record()
                end.synchronize()
                gpu_ms.append(cp.cuda.get_elapsed_time(start, end) / 100)
                before = time.perf_counter()
                uploaded = cp.asarray(host)
                kernel(((count + 127)//128,), (128,), (uploaded, output, np.uint32(count)))
                cp.asnumpy(output)  # includes upload, launch, download and synchronization
                total_ms.append((time.perf_counter() - before) * 1000)
                before = time.perf_counter()
                oracle(np, host)
                numpy_ms.append((time.perf_counter() - before) * 1000)
            rows.append(dict(material=material, density_kg_m3=density, young_pa=young,
                             independent_bonds=count, dt_s=1/1920, dtype="float64",
                             max_pose_error_m=pose_error, max_lambda_error_kg_m=lambda_error,
                             max_pair_com_numerator_kg_m=com_numerator,
                             max_first_projection_elastic_gain_j=max_elastic_gain,
                             gpu_resident_median_ms=statistics.median(gpu_ms),
                             gpu_upload_run_download_median_ms=statistics.median(total_ms),
                             numpy_oracle_median_ms=statistics.median(numpy_ms)))
    result = dict(scope="Shared axial bond primitive; no world/contact/fracture speed qualification",
                  full_world_gpu=False, realtime_qualified=False,
                  revision=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                  platform=platform.platform(), cupy=cp.__version__, gpu=props["name"].decode(),
                  runtime=cp.cuda.runtime.runtimeGetVersion(), driver=cp.cuda.runtime.driverGetVersion(),
                  compute_capability=cp.cuda.Device().compute_capability,
                  source_sha256=header_hash,
                  iterations_per_measurement=100, repeats=9, cases=rows)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"PASS: {len(rows)} shared-source GPU/analytical coupon cases; {result['gpu']}")
    print(f"Report: {report_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=ROOT/"build/cupy-probe/results.json")
    run(parser.parse_args().report)
