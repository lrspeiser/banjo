"""Experimental unilateral-contact worlds; a completed run is not calibrated physics.

The default material-restitution world regression remains a separate required gate.
"""
import json,math,subprocess,sys,time
from pathlib import Path

native=Path(sys.argv[1]).resolve()
cases=[{'sheet':m,'ball':'iron'} for m in ['glass','oak','iron','ice']]
cases += [{'sheet':'glass','ball':'glass'},
          {'sheet':'glass','ball':'glass','dt_s':1/1920}]
rows=[]
for declaration in cases:
    declaration=dict(declaration,contact_law='resolved-deformation')
    proc=subprocess.Popen([str(native),'--serve'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
    def request(command):
        proc.stdin.write(json.dumps(command)+'\n');proc.stdin.flush()
        line=proc.stdout.readline()
        if not line:raise RuntimeError('native terminated: '+str(proc.wait(timeout=5)))
        reply=json.loads(line);assert reply['ok'],reply.get('error')
        return reply['state']
    try:
        first=request({'op':'create','declaration':declaration})
        masses={c['id']:c['mass_kg'] for c in first['cells']}
        assert first['qualification']['contact_law']=='resolved-deformation'
        assert not first['qualification']['calibrated']
        state=first;started=time.monotonic()
        while state['time_s']<2-1e-9:
            state=request({'op':'advance','steps':16})
            assert {c['id']:c['mass_kg'] for c in state['cells']}==masses
            assert state['diagnostics']['unclosed_energy_j']<=.10001
            assert all(math.isfinite(x) for c in state['cells']
                for k in ['position_m','velocity_m_s','spin_rad_s'] for x in c[k])
            assert abs(state['step_work']['closure_residual_j'])<1e-7
            assert state['step_work']['measured']['velocity_limit_work_j']<=1e-7
        assert abs(state['time_s']-2)<1e-8
        assert state['contact_audit']['point_samples']>0
        if declaration['sheet'] in ['glass','ice']:
            assert state['objects'][0]['broken_faces']>0 and state['objects'][0]['pieces']>1
        else:
            assert state['objects'][0]['broken_faces']==0 and state['objects'][0]['pieces']==1
        if declaration['ball']=='glass':
            assert state['objects'][1]['broken_faces']>0 and state['objects'][1]['pieces']>1
        row={'declaration':declaration,'time_s':state['time_s'],'wall_s':time.monotonic()-started,
             'substeps':state['substeps'],'objects':state['objects'],'diagnostics':state['diagnostics'],
             'step_work':state['step_work'],'contact_audit':state['contact_audit']}
        rows.append(row);print(json.dumps(row),flush=True)
    finally:
        proc.terminate();proc.wait(timeout=5)
coarse,fine=rows[-2:]
print(json.dumps({'glass_ball_dt_comparison':{
    'coarse_energy_deficit_j':coarse['diagnostics']['unclosed_energy_j'],
    'fine_energy_deficit_j':fine['diagnostics']['unclosed_energy_j'],
    'sheet_piece_counts':[coarse['objects'][0]['pieces'],fine['objects'][0]['pieces']],
    'ball_piece_counts':[coarse['objects'][1]['pieces'],fine['objects'][1]['pieces']],
    'converged':False,'scope':'Two declared dt values complete; no constitutive/continuum convergence claim'}}),flush=True)
print('PASS 6 experimental unilateral-contact worlds; energy accuracy, realism and useful speed remain OPEN',flush=True)
