"""Reproducible actual-CUDA phase measurements; no solver or gate shortcuts."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import time

from physx_contact_world import PhysXContactWorld, SOURCE_SHA256, wp

ROOT = Path(__file__).resolve().parents[1]


def run(raw, seconds, cuda_capture=False, observation_mode='bindings'):
    started = time.perf_counter()
    world = PhysXContactWorld(raw, observation_mode=observation_mode)
    startup_s = time.perf_counter()-started
    started = time.perf_counter()
    goal_ticks = round(seconds/world.d['dt_s'])
    peak_gain = None
    recorded = 0
    error = None
    capture_started = False
    try:
        if cuda_capture:
            # Optional external-profiler range, after SDK/kernel warmup. It
            # changes no step, read, law, iteration or admission gate.
            wp.cuda_profiler_start(world.device)
            capture_started = True
        while world.ticks < goal_ticks:
            try:
                state = world.advance(min(32, goal_ticks-world.ticks))
            except (ValueError, RuntimeError) as fault:
                error = str(fault)
                break
            records = state['substep_trace']['normal_accounts']
            recorded += len(records)
            gain = max(row['mechanical_change_j'] for row in records)
            peak_gain = gain if peak_gain is None else max(peak_gain, gain)
        elapsed = time.perf_counter()-started
        state = world.snapshot()
        assert recorded == state['ticks'], 'Missing intermediate substep audit'
        return dict(declaration=state['declaration'], requested_physical_s=seconds,
            scheduled_physical_s=goal_ticks*world.d['dt_s'], completed_physical_s=state['time_s'],
            startup_s=startup_s, run_wall_s=elapsed, cuda_capture=cuda_capture,
            measured_ratio=state['time_s']/elapsed if elapsed else None,
            audited_substeps=recorded, max_accepted_gain_j=peak_gain,
            performance=state['performance'], diagnostics=state['diagnostics'],
            final_cells=state['cells'], qualification=state['qualification'],
            error=error, rejected_candidate=state.get('rejected_candidate'))
    finally:
        try:
            if capture_started:
                wp.cuda_profiler_stop(world.device)
        finally:
            world.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', required=True, type=Path)
    parser.add_argument('--physical-seconds', type=float, default=2.)
    parser.add_argument('--step-hz', type=int, choices=(960, 1920), default=1920)
    parser.add_argument('--experiment', choices=('yard', 'floor', 'pair'), default='yard')
    parser.add_argument('--material', choices=('glass', 'oak', 'iron', 'ice'), action='append')
    parser.add_argument('--restitution', type=float, default=0.)
    parser.add_argument('--friction', type=float, default=0.)
    parser.add_argument('--cuda-capture', action='store_true',
        help='Issue CUDA profiler start/stop after warmup; use Nsight capture-range=cudaProfilerApi')
    parser.add_argument('--observation-mode', choices=('bindings','columns'), default='bindings',
        help='Compare resident bindings with the retained column reference; physical solver is unchanged')
    args = parser.parse_args()
    if not .02 <= args.physical_seconds <= 2.:
        parser.error('--physical-seconds must be between 0.02 and 2')
    if args.experiment == 'pair' and args.step_hz != 1920:
        parser.error('PhysX analytical pair requires --step-hz 1920')
    if args.cuda_capture and (not args.material or len(args.material) != 1):
        parser.error('--cuda-capture requires exactly one --material per trace')
    rows = []
    for material in args.material or ('glass', 'oak', 'iron', 'ice'):
        result = run(dict(experiment=args.experiment, material=material, ball_material='iron',
            height_m=10., ball_mass_kg=1., restitution=args.restitution,
            friction=args.friction, dt_s=1/args.step_hz), args.physical_seconds, args.cuda_capture, args.observation_mode)
        rows.append(result)
        print(material, result['completed_physical_s'], 'physical s /',
            round(result['run_wall_s'], 3), 'wall s', result['error'] or 'completed', flush=True)
    report = dict(scope='Experimental rigid PhysX GPU measurement. No constitutive or realtime qualification.',
        base_revision=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        source_sha256=SOURCE_SHA256, profiler_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        environment=dict(os=platform.platform(), python=platform.python_version()), results=rows)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, allow_nan=False), encoding='utf8')
    return int(any(row['error'] for row in rows))


if __name__ == '__main__':
    raise SystemExit(main())
