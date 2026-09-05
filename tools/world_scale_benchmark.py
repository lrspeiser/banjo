"""Repeat bounded thermal-work benchmarks; cold storage is not full simulation.

Usage: python tools/world_scale_benchmark.py --exe path/to/banjo_world_cli --out dir
Runs sequentially to avoid contaminating timings with parallel test processes.
"""
import argparse
import json
import pathlib
import platform
import statistics
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument('--exe', required=True, type=pathlib.Path)
parser.add_argument('--out', required=True, type=pathlib.Path)
args = parser.parse_args()
args.out.mkdir(parents=True, exist_ok=True)
cases = [(256, 4), (4096, 4), (32768, 4), (4096, 16), (4096, 64), (4096, 256)]
results = []
for chunks, regions in cases:
    trials = []
    for repeat in range(3):
        path = args.out / f'chunks-{chunks}-regions-{regions}-run-{repeat + 1}.json'
        subprocess.run([str(args.exe.resolve()), '--chunks', str(chunks), '--regions', str(regions),
                        '--frames', '600', '--output', str(path.resolve())], check=True, capture_output=True)
        data = json.loads(path.read_text())
        assert not data['last_budget']['error'], data['last_budget']['error']
        trials.append(data)
    # Backlog can change accepted final times under a wall budget, so compare
    # only equal-time completed outcomes, never claim whole-run determinism.
    rows = [{k: r[k] for k in ('accepted_time_s', 'thermal_enthalpy_j', 'chemical_energy_j',
                               'fuel_kg', 'liquid_mass_kg')} for r in trials[0]['regions']]
    results.append({
        'chunks': chunks, 'represented_voxels': trials[0]['represented_voxels'],
        'active_cells': trials[0]['active_cells'], 'active_regions': regions,
        'payload_bytes_excluding_allocator': trials[0]['state_payload_bytes'],
        'p95_ms_range': [min(t['performance']['advance_p95_ms'] for t in trials), max(t['performance']['advance_p95_ms'] for t in trials)],
        'p99_ms_range': [min(t['performance']['advance_p99_ms'] for t in trials), max(t['performance']['advance_p99_ms'] for t in trials)],
        'max_ms_range': [min(t['performance']['advance_max_ms'] for t in trials), max(t['performance']['advance_max_ms'] for t in trials)],
        'maximum_final_lag_s': max(t['last_budget']['maximum_lag_s'] for t in trials),
        'maximum_observed_lag_s': max(t['performance']['peak_lag_s'] for t in trials),
        'peak_late_regions': max(t['performance']['peak_late_regions'] for t in trials),
        'late_regions': [t['last_budget']['regions_late'] for t in trials],
        'maximum_abs_energy_residual_j': max(abs(t['combined_active_energy_residual_j']) for t in trials),
        'load_ms_median': statistics.median(t['fixture']['load_ms'] for t in trials),
        'first_trial_states': rows,
    })
summary = {'platform': platform.platform(), 'processor': platform.processor(),
           'repeats': 3, 'frames': 600, 'host_hz': 60, 'thermal_hz': 20,
           'budget_ms': 4, 'maximum_jobs_per_frame': 64, 'work_budget': 32768,
           'limitations': ['insulated numerical thermal/reaction coupons only',
                           'cold stored voxels are not all actively simulated',
                           'no rendering, mechanics, airflow, automatic activation or cross-region flux',
                           'wall deadline checked between jobs; overload retains lag'], 'cases': results}
(args.out / 'summary.json').write_text(json.dumps(summary, indent=2))
for row in results:
    print({k: v for k, v in row.items() if k != 'first_trial_states'})
