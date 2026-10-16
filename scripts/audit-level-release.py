"""Measure authored solutions and negative controls on the release engine.

Simulation time and automated wall time are not novice completion times. This
audit deliberately labels its reference-solution knowledge; use the separate
audit-level-onboarding.py workflow for solution-blind proposals.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time

import machine_game as game
import machine_world as world


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--level', action='append', help='restrict a diagnostic rerun')
    parser.add_argument('--examples-only', action='store_true')
    args = parser.parse_args()
    engine = args.engine.resolve()
    args.out.mkdir(parents=True, exist_ok=True)
    report = dict(engine_sha256=hashlib.sha256(engine.read_bytes()).hexdigest(),
                  method='Authored solutions, two 1.5 mm nudges, physical negative controls, and 1 s of setup gravity.',
                  limitation='Not a timed human study or a solution-blind assessment.', levels=[])
    started = time.perf_counter()
    for level in game.load_levels():
        if args.examples_only:break
        if args.level and level['id'] not in args.level:
            continue
        logs = args.out / level['id']
        logs.mkdir(exist_ok=True)
        row = dict(id=level['id'], title=level['title'])
        clock = time.perf_counter()
        try:
            inputs = dict(handle_inputs=level.get('solution_inputs'), release_inputs=level.get('solution_releases'))
            row['solution'] = game.trial(level, level['solution'], engine, logs, runs=3, **inputs)
            try:
                row['empty'] = game.trial(level, [], engine, logs, runs=1)
            except game.LevelRefused as exc:
                row['empty'] = dict(worked=0, refused_missing_goal_piece=str(exc))
            if level.get('wrong') is not None:
                wrong_inputs = {} if level['wrong'] == level['solution'] else inputs
                row['misplaced'] = game.trial(level, level['wrong'], engine, logs, runs=1, **wrong_inputs)
                if not wrong_inputs and inputs:
                    row['negative_action'] = 'No manual activation of the switch/latch.'
            compiled = world.compile_spec(game.compose(level, level['solution'])[0])
            graph = compiled.get('electrical', {})
            if graph.get('wires') or graph.get('power_cables') or any(c.get('leads') for c in compiled['circuits']):
                row['after_setup_gravity'] = game.trial(level, level['solution'], engine, logs, runs=3, setup_s=1, **inputs)
            row['passed'] = (row['solution']['worked'] == 3 and not row['empty']['worked']
                             and not row.get('misplaced', {}).get('worked', 0)
                             and row.get('after_setup_gravity', {'worked':3})['worked'] == 3
                             and not any(r.get('error') for key in ('solution','empty','misplaced','after_setup_gravity')
                                         for r in row.get(key, {}).get('results', [])))
        except Exception as exc:
            row.update(passed=False, error=str(exc))
        row['automated_wall_s'] = round(time.perf_counter() - clock, 3)
        report['levels'].append(row)
        report['wall_s'] = round(time.perf_counter() - started, 3)
        report['passed'] = all(r['passed'] for r in report['levels'])
        (args.out/'results.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(row), flush=True)
    if not args.level:
        report['examples']=[]
        for example in game.sandbox_templates():
            logs=args.out/('example-'+example['name'].replace(' ','-'))
            logs.mkdir(exist_ok=True)
            row=dict(name=example['name'])
            clock=time.perf_counter()
            try:
                level=game.requested_level(dict(level='free',base=example['base']))
                compiled=world.compile_spec(game.compose(level,example['placements'])[0])
                subjects=[p['name'] for p in compiled['parts'] if p['name'] in ('flag','river gate')]
                r=world.rehearse(compiled,engine,logs,seconds=30 if example['name']=='Chain reaction' else 6,
                                 wall_limit_s=120,track=subjects,setup_s=1)
                row['error']=r.get('error')
                row['stations']=r['stations']
                # Tracked points are [time, x, y, z].
                row['movement_m']={name:max(p[2] for p in r['paths'][name]['points'])-r['paths'][name]['points'][0][2]
                                   for name in subjects}
                row['capacitors']=[dict(name=d['name'],stored_j=d['stored_j'])
                                   for d in (r['readouts'].get('electrical') or {}).get('devices',[]) if d['kind']=='capacitor']
                row['passed']=(not r.get('error') and all(s['done'] for s in r['stations'])
                               and all(v>.05 for v in row['movement_m'].values())
                               and all(c['stored_j']>0 for c in row['capacitors']))
            except Exception as exc:row.update(passed=False,error=str(exc))
            row['automated_wall_s']=round(time.perf_counter()-clock,3)
            report['examples'].append(row)
            print(json.dumps(row),flush=True)
        report['passed']=all(r['passed'] for r in report['levels']+report['examples'])
        report['wall_s']=round(time.perf_counter()-started,3)
        (args.out/'results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
