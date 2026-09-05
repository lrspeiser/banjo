"""Reproducible live solver measurements, including unresolved fidelity results."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument('--exe', type=Path, required=True)
parser.add_argument('--out', type=Path, required=True)
parser.add_argument('--seconds', type=float, default=3)
parser.add_argument('--repeat', type=int, default=3)
parser.add_argument('--sweep', action='store_true')
args = parser.parse_args()
if not 0 < args.seconds <= 5 or not 1 <= args.repeat <= 5:
    parser.error('seconds must be (0,5], repeat 1..5')
root = Path(__file__).resolve().parents[1]
exe = args.exe.resolve()
out = args.out.resolve()
out.mkdir(parents=True, exist_ok=True)
cases = sorted((root / 'assets/runtime-v2').glob('*.json'))
summary = dict(executable_sha256=hashlib.sha256(exe.read_bytes()).hexdigest(),
               simulated_seconds=args.seconds, repeat=args.repeat,
               timing_scope='Physics steps only; excludes admission, rendering, reports and process startup',
               reports=[], fidelity_sweep=[])

def run(path, seconds, output_name):
    package = json.loads(path.read_text())
    assert package['backend'] == 'material-network-v2'
    steps = round(seconds / package['fixed_dt_s'])
    result = subprocess.run([str(exe), '--run', str(path), str(steps)],
                            capture_output=True, text=True, check=False)
    report = json.loads(result.stdout)
    if result.returncode or report.get('fault'):
        raise RuntimeError(f'{path.name}: {report}')
    (out / output_name).write_text(json.dumps(report, indent=2) + '\n')
    return dict(report=output_name, case=path.name,
                package_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                elapsed_s=report['elapsed_s'], performance=report['performance'],
                cells=report['cells'], objects=report['objects'],
                fracture_work_j=report['fracture_work_j'], plastic_work_j=report['plastic_work_j'],
                energy_residual_j=report['energy_residual_j'],
                unseparated_energy_change_j=report['unseparated_energy_change_j'],
                maximum_reaction_geometric_extension_discrepancy_m=report['maximum_reaction_geometric_extension_discrepancy_m'])

for case in cases:
    for repeat in range(args.repeat):
        summary['reports'].append(run(case, args.seconds, f'{case.stem}-run-{repeat + 1}.json'))
    runs = summary['reports'][-args.repeat:]
    timings = [r['performance']['step_wall_total_ms'] for r in runs]
    print(f'{case.name}: {min(timings):.2f}..{max(timings):.2f} CPU ms / {args.seconds}s simulated', flush=True)

if args.sweep:
    source = json.loads((root / 'assets/runtime-v2/04-soft-tissue-offset-cut.json').read_text())
    for label, dt, resolution in [('dt480', 1/480, [7,6,6]), ('dt960', 1/960, [7,6,6]),
                                  ('dt1920', 1/1920, [7,6,6]), ('coarse', 1/480, [5,5,5]),
                                  ('fine', 1/480, [9,8,8])]:
        package = copy.deepcopy(source)
        package['fixed_dt_s'] = dt
        package['objects'][0]['resolution'] = resolution
        path = out / f'sweep-{label}-package.json'
        path.write_text(json.dumps(package, indent=2) + '\n')
        r = run(path, 1, f'sweep-{label}-report.json')
        summary['fidelity_sweep'].append(r)
        target = r['objects'][0]
        print(f"sweep {label}: {target['broken_links']} broken / {target['links']} links, {target['components']} components", flush=True)

(out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
print(f'Wrote evidence to {out}', flush=True)
