"""Compare matched node states at common times; no interpolation or COM-only proxy.

Usage: python scripts/compare-trajectories.py build/trajectory-matrix/matrix.csv
       --output build/trajectory-comparison.csv
Only the Python standard library is required. CSV errors are measured differences,
not an automatic convergence certificate or an error estimate against exact physics.
"""
import argparse
import csv
import io
import math
import re
from pathlib import Path


def norm2(v):
    return sum(x*x for x in v)


def mechanics(nodes):
    mass=sum(n[0] for n in nodes)
    velocity=[sum(n[0]*n[4+d] for n in nodes)/mass for d in range(3)]
    center=[sum(n[0]*n[1+d] for n in nodes)/mass for d in range(3)]
    # The fixed h=0.04 m fixture stores intrinsic isotropic cell spin (m*h²/6).
    internal=sum(.5*n[0]*(norm2([n[4+d]-velocity[d] for d in range(3)])+
                 .04**2/6*norm2(n[7:10])) for n in nodes)
    return mass,center,velocity,internal


def read_run(row):
    if int(row['exit_code'])!=0:
        raise ValueError(f"Rejected run cannot be a completed trajectory: {row['log']}")
    lines=Path(row['log']).read_text(encoding='utf-8-sig').splitlines()
    signature=(lines[0],re.sub(r' dt=\S+ requested_steps=\S+','',lines[1]),lines[2])
    if ' h=0.04 ' not in lines[1]:
        raise ValueError('This comparator currently requires the declared 0.04 m cell-inertia fixture')
    count=int(re.search(r'nodes=(\d+)',lines[1]).group(1))
    header=next(i for i,line in enumerate(lines) if line.startswith('step,accepted,'))
    samples=list(csv.DictReader(io.StringIO('\n'.join([lines[header]]+
        [line for line in lines[header+1:] if re.match(r'^\d+,',line)]))))
    if len(samples)!=int(row['steps']) or any(s['accepted']!='1' for s in samples):
        raise ValueError('Incomplete or rejected timestep series')
    dt=float(row['dt_s'])
    history={round((int(s['step'])+1)*dt,12):s for s in samples}
    states={}
    fields=('mass_kg','x_m','y_m','z_m','vx_m_s','vy_m_s','vz_m_s','wx_rad_s','wy_rad_s','wz_rad_s')
    with Path(row['trajectory']).open(encoding='utf-8-sig',newline='') as f:
        for sample in csv.DictReader(f):
            time=float(sample['time_s'])
            if not math.isfinite(time): raise ValueError('Nonfinite sample time')
            nodes=states.setdefault(round(time,12),[])
            if int(sample['node'])!=len(nodes): raise ValueError('Missing, duplicate or reordered node')
            state=tuple(float(sample[key]) for key in fields)
            if not all(math.isfinite(v) for v in state) or state[0]<=0:
                raise ValueError('Invalid node state')
            nodes.append(state)
    stride=int(row['sample_every']); steps=int(row['steps'])
    expected={0.0,round(steps*dt,12)} | {round(i*dt,12) for i in range(stride,steps+1,stride)}
    if set(states)!=expected or any(len(nodes)!=count for nodes in states.values()):
        raise ValueError('Incomplete trajectory output')
    initial=states[0]
    for time,nodes in states.items():
        if any(n[0]!=first[0] for n,first in zip(nodes,initial)):
            raise ValueError('Node mass changed')
        if time:
            _,center,velocity,internal=mechanics(nodes)
            s=history[time]
            if abs(center[1]-float(s['com_y_m']))>1e-10 or abs(velocity[1]-float(s['com_vy_m_s']))>1e-10:
                raise ValueError('Exported positions/velocities disagree with probe COM')
            if abs(internal-float(s['internal_kinetic_energy_j']))>1e-8:
                raise ValueError('Independent node kinetic energy disagrees with probe')
    summary=dict(re.findall(r'([\w-]+)=([-+.\deE]+)',row['summary']))
    return dict(row=row,states=states,history=history,signature=signature,summary=summary,
                wall_s=sum(float(s['wall_ms']) for s in samples)/1000)


def compare(coarse,fine,*,allow_compliant_adaptive=False):
    if not coarse['row'].get('executable_sha256') or coarse['row']['executable_sha256']!=fine['row'].get('executable_sha256'):
        raise ValueError('Refinement comparison requires the same recorded solver executable hash')
    signatures=[coarse['signature'],fine['signature']]
    if allow_compliant_adaptive:
        # Only these two integrators share the explicitly selected compliance
        # law. Never equate rigid/event contact or erase other physical inputs.
        for index,signature in enumerate(signatures):
            mode=re.search(r' step_mode=(\w+)',signature[2])
            if not mode or mode[1] not in ('compliant','adaptive'):
                raise ValueError('Mixed-integrator comparison requires the same compliant contact law')
            signatures[index]=(*signature[:2],re.sub(r' step_mode=(?:compliant|adaptive)\b',' step_mode=compliant',signature[2]))
    if signatures[0]!=signatures[1] or coarse['states'][0]!=fine['states'][0]:
        raise ValueError('Physical configuration or initial node state changed between rates')
    if set(coarse['states'])!=set(fine['states']):
        raise ValueError('Compare exact shared output times, without interpolation')
    metrics=[]
    for time in sorted(coarse['states']):
        a,b=coarse['states'][time],fine['states'][time]
        mass,center_a,v_a,k_a=mechanics(a)
        _,center_b,v_b,k_b=mechanics(b)
        dx=[norm2([x[1+d]-y[1+d] for d in range(3)]) for x,y in zip(a,b)]
        dv=[norm2([x[4+d]-y[4+d] for d in range(3)]) for x,y in zip(a,b)]
        value=dict(time_s=time,
            position_rms_m=math.sqrt(sum(n[0]*e for n,e in zip(a,dx))/mass),
            velocity_rms_m_s=math.sqrt(sum(n[0]*e for n,e in zip(a,dv))/mass),
            position_max_m=math.sqrt(max(dx)),velocity_max_m_s=math.sqrt(max(dv)),
            com_position_difference_m=math.sqrt(norm2([x-y for x,y in zip(center_a,center_b)])),
            com_velocity_difference_m_s=math.sqrt(norm2([x-y for x,y in zip(v_a,v_b)])),
            internal_kinetic_difference_j=abs(k_a-k_b),body_elastic_difference_j=0.0)
        if time:
            value['body_elastic_difference_j']=abs(float(coarse['history'][time]['body_elastic_energy_j'])-
                                                    float(fine['history'][time]['body_elastic_energy_j']))
        metrics.append(value)
    row=dict(material=coarse['row']['material'],damping_kg_s=coarse['row']['damping_kg_s'],
        coarse_dt_s=coarse['row']['dt_s'],fine_dt_s=fine['row']['dt_s'],
        samples=len(metrics),duration_s=metrics[-1]['time_s'])
    for key in metrics[-1]:
        if key=='time_s': continue
        row['final_'+key]=metrics[-1][key]
        row['sampled_max_'+key]=max(m[key] for m in metrics)
    row.update(coarse_wall_s=coarse['wall_s'],fine_wall_s=fine['wall_s'],
        coarse_final_com_vy_m_s=coarse['summary']['final-COM-vy'],fine_final_com_vy_m_s=fine['summary']['final-COM-vy'],
        damping_work_difference_j=abs(float(coarse['summary']['compliance-loss'])-float(fine['summary']['compliance-loss'])),
        coarse_log=coarse['row']['log'],fine_log=fine['row']['log'])
    return row,metrics


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('matrices',nargs='+',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    groups={}
    for file in args.matrices:
        with file.open(encoding='utf-8-sig',newline='') as f:
            for row in csv.DictReader(f):
                groups.setdefault((row['material'],row['damping_kg_s']),[]).append(row)
    if not {'glass','oak','iron'}.issubset({key[0] for key in groups}):
        raise ValueError('The comparison must retain glass, oak and iron')
    results=[]; time_series=[]
    for key,rows in sorted(groups.items()):
        rows.sort(key=lambda r:-float(r['dt_s']))
        if len(rows)<2 or len({float(r['dt_s']) for r in rows})!=len(rows):
            raise ValueError(f'Need distinct refinement rates for {key}')
        coarse=read_run(rows[0])
        for row in rows[1:]:
            fine=read_run(row)
            result,metrics=compare(coarse,fine)
            results.append(result)
            time_series.extend(dict(material=key[0],damping_kg_s=key[1],coarse_dt_s=coarse['row']['dt_s'],fine_dt_s=row['dt_s'],**m) for m in metrics)
            print(key,result['coarse_dt_s'],result['fine_dt_s'],
                'max RMS position/velocity:',result['sampled_max_position_rms_m'],result['sampled_max_velocity_rms_m_s'],flush=True)
            coarse=fine
    args.output.parent.mkdir(parents=True,exist_ok=True)
    for path,rows in ((args.output,results),(args.output.with_name(args.output.stem+'-times.csv'),time_series)):
        with path.open('w',encoding='utf-8',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    print(f'Verified and compared {len(results)} adjacent pairs; all nodes at each shared time, no interpolation.')


if __name__=='__main__':
    main()
