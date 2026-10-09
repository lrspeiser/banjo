"""Actual endpoint block impacts, retained refusal, and original-cell work records.
Completion here is a regression gate, not a material calibration/conservation pass.
"""
import json, math, subprocess, sys, time
from pathlib import Path

native=Path(sys.argv[1]).resolve()

def run(declaration, expected_refusal=False):
    proc=subprocess.Popen([str(native),'--serve'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
    def request(command):
        proc.stdin.write(json.dumps(command)+'\n');proc.stdin.flush()
        line=proc.stdout.readline();assert line,'native terminated during impact'
        return json.loads(line)
    begin=time.perf_counter()
    try:
        reply=request({'op':'create','declaration':declaration});assert reply['ok'],reply
        first=reply['state'];masses={c['id']:c['mass_kg'] for c in first['cells']}
        assert len(masses)==107
        while reply['ok'] and reply['state']['time_s']<2-1e-9:
            reply=request({'op':'advance','steps':16});s=reply['state']
            assert {c['id']:c['mass_kg'] for c in s['cells']}==masses
            assert all(math.isfinite(x) for c in s['cells'] for key in ['position_m','velocity_m_s','spin_rad_s'] for x in c[key])
            assert s['qualification']['contact_law']==declaration['contact_law']
            assert s['qualification']['face_law']=='native-motor' and not s['qualification']['calibrated']
            assert abs(s['step_work']['closure_residual_j'])<1e-7
            assert s['diagnostics']['unclosed_energy_j']<=.10001
        s=reply['state']
        if expected_refusal:
            assert not reply['ok'] and 'energy gate refused' in reply['error']
            rejected=s['step_work']['last_rejected_trial'];sources=rejected['contact_sources']
            assert rejected['depth']==14 and sources['native_contact_count']>0
            measured=rejected['work']['contact_work_j']
            assert abs(sources['sum_j']-measured)<1e-10
            assert abs(sum(sources[k] for k in ['normal_j','friction_j','twist_j'])-measured)<1e-10
            assert sources['twist_j']>0 and sources['normal_j']<0 and sources['friction_j']<0
            strongest=max(sources['contacts'],key=lambda c:c['twist_j'])
            dot=lambda a,b:sum(x*y for x,y in zip(a,b))
            impulse=dot(strongest['twist_impulse_n_m_s'],strongest['normal'])
            assert impulse*dot(strongest['free_spin_rad_s'],strongest['normal'])>0
            assert impulse*dot(strongest['solved_spin_rad_s'],strongest['normal'])>0
            # Independent torque/velocity work identity, not a post-hoc energy correction.
            assert abs(dot(strongest['twist_impulse_n_m_s'],strongest['common_spin_rad_s'])-strongest['twist_j'])<1e-12
        else:
            assert reply['ok'],reply.get('error')
            assert abs(s['time_s']-2)<1e-8 and s['contact_audit']['point_samples']>0
            obj=s['objects'][0]
            if declaration['sheet'] in ['glass','ice']:assert obj['pieces']>1 and obj['broken_faces']>0
            else:assert obj['pieces']==1 and obj['broken_faces']==0
        row={'declaration':declaration,'completed':reply['ok'],'time_s':s['time_s'],
             'wall_s':time.perf_counter()-begin,'substeps':s['substeps'],'objects':s['objects'],
             'diagnostics':s['diagnostics'],'step_work':s['step_work'],
             'scope':'Original-cell completion/refusal and signed work. Full accuracy, heat and realtime remain open.'}
        print(json.dumps(row),flush=True)
    finally:
        proc.stdin.close();proc.wait(timeout=10)

run({'sheet':'glass','ball':'iron','dt_s':1/1920,'contact_law':'material-restitution'},True)
for dt in [1/960,1/1920]:
    for material in ['glass','oak','iron','ice']:
        run({'sheet':material,'ball':'iron','dt_s':dt,'contact_law':'material-block-friction'})
print('PASS retained reference refusal and eight complete endpoint block impacts; calibration/convergence/realtime OPEN',flush=True)
