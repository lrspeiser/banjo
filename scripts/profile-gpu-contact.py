"""Reproducible actual-CUDA phase measurements; no solver or gate shortcuts."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import time

from physx_contact_world import PhysXContactWorld, SOURCE_SHA256

ROOT = Path(__file__).resolve().parents[1]


def run(raw, seconds):
    started = time.perf_counter()
    world = PhysXContactWorld(raw)
    startup_s = time.perf_counter()-started
    started = time.perf_counter()
    goal_ticks = round(seconds/world.d['dt_s'])
    peak_gain = None
    recorded = 0
    error = None
    try:
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
            startup_s=startup_s, run_wall_s=elapsed,
            measured_ratio=state['time_s']/elapsed if elapsed else None,
            audited_substeps=recorded, max_accepted_gain_j=peak_gain,
            performance=state['performance'], diagnostics=state['diagnostics'],
            final_cells=state['cells'], qualification=state['qualification'],
            error=error, rejected_candidate=state.get('rejected_candidate'))
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
    args = parser.parse_args()
    if not .02 <= args.physical_seconds <= 2.:
        parser.error('--physical-seconds must be between 0.02 and 2')
    if args.experiment == 'pair' and args.step_hz != 1920:
        parser.error('PhysX analytical pair requires --step-hz 1920')
    rows = []
    for material in args.material or ('glass', 'oak', 'iron', 'ice'):
        result = run(dict(experiment=args.experiment, material=material, ball_material='iron',
            height_m=10., ball_mass_kg=1., restitution=args.restitution,
            friction=args.friction, dt_s=1/args.step_hz), args.physical_seconds)
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
