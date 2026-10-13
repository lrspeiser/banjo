"""Export solution-blind observations and measure an assessor's native trials.

This is a geometry-assisted LLM probe, not a human usability stopwatch.
Export deliberately excludes hints, solutions, wrong placements and reference
manual inputs. The model chooses its own placements and field input.
"""
import argparse
import json
from pathlib import Path
import time

import machine_game as game
import machine_world as world


def packet(level):
    public = game.public(level)
    for key in ('hints', 'example', 'onboarding'):
        public.pop(key, None)
    compiled = world.compile_spec(game.compose(level, [], leave_out_goal=True)[0])
    keys = ('parts', 'joints', 'ground', 'sun', 'solar_panels', 'light', 'electrical', 'batteries', 'spouts')
    return dict(player=public, scene={k:compiled.get(k) for k in keys if compiled.get(k)},
                provenance='Public brief, tray controls, goal and starting geometry only; no hints/reference solutions.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=['export','try'])
    parser.add_argument('--out',required=True,type=Path)
    parser.add_argument('--proposal',type=Path)
    parser.add_argument('--engine',type=Path)
    args=parser.parse_args()
    if args.operation=='try' and (args.proposal is None or args.engine is None):
        parser.error('try requires --proposal and --engine')
    args.out.mkdir(parents=True,exist_ok=True)
    if args.operation=='export':
        rows=[packet(level) for level in game.load_levels()]
        for index in range(3):
            subset=rows[index::3]
            (args.out/f'blind-{index+1}.json').write_text(json.dumps(subset,indent=2),encoding='utf-8')
        print(json.dumps(dict(levels=len(rows),files=[f'blind-{i+1}.json' for i in range(3)])))
        return
    proposal=json.loads(args.proposal.read_text(encoding='utf-8'))
    results=[]
    for row in proposal if isinstance(proposal,list) else [proposal]:
        started=time.perf_counter()
        level=game.level_by_id(row['id'])
        logdir=args.out/row['id'];logdir.mkdir(exist_ok=True)
        try:
            # Match a newly added UI piece. Historical unversioned saves
            # deliberately use legacy defaults; fresh ghosts use defaults.
            trays={t['piece']:t for t in level['tray']}
            placements=[]
            for p in row['placements']:
                knobs=trays[p['piece']]['knobs']
                defaults={k:r.get('default',r.get('choices',[r.get('min')])[0]) for k,r in knobs.items()}
                placements.append(dict(defaults,**p))
            spec,_,_=game.compose(level,placements)
            compiled=world.compile_spec(spec)
            measured=world.rehearse(compiled,args.engine,logdir,
                seconds=level['time_s']+.5,wall_limit_s=45,handle_inputs=row.get('handle_inputs'))
            goal=(measured.get('stations') or [{}])[0]
            result=dict(id=row['id'],won=bool(goal.get('done') and goal.get('at_s') is not None and goal['at_s']<=level['time_s']),
                goal_at_s=goal.get('at_s'),error=measured.get('error'),
                final_readings=measured.get('readouts'),closest=measured.get('closest_approach'))
        except (ValueError,KeyError,StopIteration,game.LevelRefused,world.MachineRefused) as exc:
            result=dict(id=row['id'],won=False,error=str(exc))
        result['native_wall_s']=round(time.perf_counter()-started,3)
        results.append(result)
        print(json.dumps({k:v for k,v in result.items() if k!='final_readings'}),flush=True)
    target=args.out/(args.proposal.stem+'-results.json')
    target.write_text(json.dumps(results,indent=2),encoding='utf-8')


if __name__=='__main__':
    main()
