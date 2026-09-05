"""Compare adaptive quality settings and a fixed-step reference at shared times.

Requires the same binary, physical inputs and initial node states. A fixed-step
trajectory is another approximation, not an exact oracle. Macro intervals are
reported separately from accepted physical substeps. Retains glass/oak/iron.
"""
import argparse
import csv
import importlib.util
import re
from pathlib import Path

spec=importlib.util.spec_from_file_location('trajectories',Path(__file__).with_name('compare-trajectories.py'))
trajectories=importlib.util.module_from_spec(spec)
spec.loader.exec_module(trajectories)


def write(path,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',encoding='utf-8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)


def read(row):
    run=trajectories.read_run(row)
    mode=re.search(r' step_mode=(\w+)',run['signature'][2])[1]
    if row['integrator']!=mode or mode not in ('compliant','adaptive'):
        raise ValueError('Incorrect integrator metadata')
    if mode=='adaptive':
        text=Path(row['log']).read_text(encoding='utf-8-sig')
        run['error_settings']=dict(re.findall(r'((?:error_\w+|m(?:in|ax)_trial_dt_s|maximum_trials))=([-+.\deE]+)',text))
        scale=float(row['error_scale'])
        for name,base in (('position_m',1e-7),('velocity_m_s',1e-3),('bond_strain',1e-6),('damping_work_j',1e-5)):
            actual=float(run['error_settings']['error_'+name])
            if scale<=0 or abs(actual-scale*base)>1e-10*scale*base:
                raise ValueError('Incorrect error-scale metadata')
        if any(float(s['max_accepted_error'])>1 for s in run['history'].values()):
            raise ValueError('Accepted adaptive error indicator exceeds its bound')
    return run


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('matrices',nargs='+',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    groups={}
    for matrix in args.matrices:
        with matrix.open(encoding='utf-8-sig',newline='') as stream:
            for row in csv.DictReader(stream):
                groups.setdefault((row['material'],row['damping_kg_s']),[]).append(row)
    if not {'glass','oak','iron'}.issubset({key[0] for key in groups}):
        raise ValueError('Retain glass, oak and iron in comparative material evidence')
    comparisons=[]; series=[]; summaries=[]
    for key,rows in sorted(groups.items()):
        fixed=[row for row in rows if row['integrator']=='compliant']
        adaptive=sorted((row for row in rows if row['integrator']=='adaptive'),key=lambda r:-float(r['error_scale']))
        if len(fixed)!=1 or len(adaptive)<2 or len({float(r['error_scale']) for r in adaptive})!=len(adaptive):
            raise ValueError('Each material needs one fixed reference and distinct adaptive quality settings')
        reference=read(fixed[0]); prior=None
        for current in [reference]+[read(row) for row in adaptive]:
            row=current['row']; steps=list(current['history'].values())
            summary=dict(material=key[0],experiment=row['experiment'],integrator=row['integrator'],error_scale=row['error_scale'],
                requested_interval_s=row['dt_s'],duration_s=max(current['states']),samples=len(current['states']),
                solver_wall_s=current['wall_s'],physical_steps=sum(int(s['substeps']) for s in steps),
                trials=sum(int(s['trials']) for s in steps),rejected_segments=sum(int(s['rejected_segments']) for s in steps),
                min_physical_step_s=min((float(s['min_accepted_step_s']) for s in steps if float(s['min_accepted_step_s'])>0),default=float(row['dt_s'])),
                max_accepted_error=max(float(s['max_accepted_error']) for s in steps),
                max_compression_m=max(float(s['modeled_compression_m']) for s in steps),
                max_interval_energy_residual_j=max(abs(float(s['energy_residual_j'])) for s in steps),
                final_energy_residual_j=current['summary']['balance-E'],final_linear_residual_kg_m_s=current['summary']['balance-P'],
                final_angular_residual_kg_m2_s=current['summary']['balance-L'],final_com_vy_m_s=current['summary']['final-COM-vy'],
                final_damping_work_j=current['summary']['compliance-loss'],executable_sha256=row['executable_sha256'],log=row['log'])
            # The fixed probe's substeps counter denotes a single raw step.
            summaries.append(summary)
            if row['integrator']=='compliant': continue
            if prior and any(current['error_settings'][k]!=prior['error_settings'][k] for k in
                ('error_reference_time_s','max_trial_dt_s','min_trial_dt_s','maximum_trials')):
                raise ValueError('Numerical bounds changed between adaptive quality settings')
            pairs=[('fixed_comparison',current,reference)]
            if prior: pairs.insert(0,('quality_refinement',prior,current))
            for kind,first,second in pairs:
                result,metrics=trajectories.compare(first,second,allow_compliant_adaptive=True)
                labels=dict(comparison=kind,first_experiment=first['row']['experiment'],second_experiment=second['row']['experiment'])
                # A macro interval is not an adaptive physical timestep.
                result['first_requested_interval_s']=result.pop('coarse_dt_s')
                result['second_requested_interval_s']=result.pop('fine_dt_s')
                comparisons.append(dict(**labels,**result))
                series.extend(dict(material=key[0],damping_kg_s=key[1],**labels,**metric) for metric in metrics)
                print(key,labels,'max node RMS velocity difference:',result['sampled_max_velocity_rms_m_s'],flush=True)
            prior=current
    write(args.output,comparisons)
    write(args.output.with_name(args.output.stem+'-times.csv'),series)
    write(args.output.with_name(args.output.stem+'-runs.csv'),summaries)
    print(f'Verified {len(summaries)} runs and {len(comparisons)} comparisons; no interpolation or exact-solution claim.')


if __name__=='__main__':
    main()
