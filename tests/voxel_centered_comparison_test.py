"""Centered full-world diagnostics. Refusal handling is tested, accuracy is OPEN.
A completed or safely refused comparison is not a passing conservation gate.
"""
import json,math,subprocess,sys,time
from pathlib import Path
def verify_rejected_twist(rejected,masses):
    worst=rejected['worst_twist_contact']
    assert worst and worst['twist_stationarity_gap_j']>0,'remaining failure lost its final-twist diagnosis'
    assert worst['a'] in masses and worst['b'] in masses,'failure witnesses do not name original constituent cells'
    assert worst['twist_cap_n_m_s']>=0 and worst['points']>1
    calculated=worst['twist_impulse_n_m_s']*worst['midpoint_spin_rad_s']
    assert abs(calculated-worst['twist_work_j'])<1e-12
    assert abs(calculated+worst['twist_cap_n_m_s']*abs(worst['midpoint_spin_rad_s'])-worst['twist_stationarity_gap_j'])<1e-12

native=Path(sys.argv[1]).resolve()
contact_law=sys.argv[2] if len(sys.argv)>2 else "resolved-deformation"
assert contact_law in ["resolved-deformation","midpoint-unilateral","midpoint-block-friction"]
rows=[]
for sheet,ball in [(m,'iron') for m in ['glass','oak','iron','ice']]+[('glass','glass')]:
    declaration={'sheet':sheet,'ball':ball,'contact_law':contact_law,'face_law':'centered-log-gradient'}
    proc=subprocess.Popen([str(native),'--serve'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
    def request(command):
        proc.stdin.write(json.dumps(command)+'\n');proc.stdin.flush()
        line=proc.stdout.readline()
        assert line,'native terminated during comparison'
        return json.loads(line)
    try:
        reply=request({'op':'create','declaration':declaration});assert reply['ok'],reply
        first=reply['state'];masses={c['id']:c['mass_kg'] for c in first['cells']}
        state=first;started=time.monotonic();refused=None
        while state['time_s']<2-1e-9:
            reply=request({'op':'advance','steps':16})
            state=reply['state']
            assert {c['id']:c['mass_kg'] for c in state['cells']}==masses
            assert state['qualification']['face_law']=='centered-log-gradient'
            assert state['qualification']['contact_law']==contact_law
            assert not state['qualification']['calibrated']
            assert all(math.isfinite(x) for c in state['cells'] for key in ['position_m','velocity_m_s','spin_rad_s'] for x in c[key])
            assert abs(state['step_work']['closure_residual_j'])<1e-7
            assert state['diagnostics']['spring_implicit_elastic_loss_j']==0
            if contact_law in ['midpoint-unilateral','midpoint-block-friction']:
                assert all(math.isfinite(x) for x in state['midpoint_boundary'].values())
                assert state['midpoint_boundary']['positive_normal_work_j']>=0
            if not reply['ok']:
                refused=reply['error'];assert 'energy gate refused' in refused
                rejected=state['step_work']['last_rejected_trial'];assert rejected and rejected['depth']==14
                if contact_law in ['midpoint-unilateral','midpoint-block-friction']:
                    verify_rejected_twist(rejected,masses)
                assert request({'op':'snapshot'})['state']==state,'refused candidate leaked into accepted state'
                break
        assert state['time_s']>1.4 and state['contact_audit']['point_samples']>0,'comparison missed impact'
        row={'declaration':declaration,'wall_s':time.monotonic()-started,'time_s':state['time_s'],'substeps':state['substeps'],'refused':refused,
             'objects':state['objects'],'diagnostics':state['diagnostics'],'step_work':state['step_work'],'contact_audit':state['contact_audit'],'midpoint_boundary':state.get('midpoint_boundary')}
        rows.append(row);print(json.dumps(row),flush=True)
    finally:proc.terminate();proc.wait(timeout=5)
print(json.dumps({'scope':'Five material/ball diagnostics; accepted-state retention and audits verified, NOT conservation/admission',
                  'accuracy_gate':'OPEN','completed':sum(not r['refused'] for r in rows),'refused':sum(bool(r['refused']) for r in rows)}),flush=True)
