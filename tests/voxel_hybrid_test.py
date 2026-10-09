"""Native free-flight handoff and actual later contact; not a realtime gate."""
import argparse, json, math, subprocess, time
from pathlib import Path
parser=argparse.ArgumentParser()
parser.add_argument('native',type=Path)
parser.add_argument('--full',action='store_true')
parser.add_argument('--output',type=Path)
args=parser.parse_args()
results=[]
for material in ['glass','oak','iron','ice']:
    proc=subprocess.Popen([str(args.native.resolve()),'--serve'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
    def call(command):
        proc.stdin.write(json.dumps(command)+'\n');proc.stdin.flush()
        r=json.loads(proc.stdout.readline())
        assert r['ok'],r.get('error')
        return r['state']
    try:
        start=time.perf_counter()
        first=call({'op':'create','declaration':{'sheet':material,'height_m':10 if args.full else .1,'hybrid_free_flight':True}})
        assert first['hybrid']['collapsed'] and first['hybrid']['active_native_bodies']==76
        original={c['id']:c['mass_kg'] for c in first['cells']}
        seen_coast=False
        for _ in range(120 if args.full else 18):
            state=call({'op':'advance','steps':16})
            seen_coast|=state['hybrid']['collapsed']
            assert {c['id']:c['mass_kg'] for c in state['cells']}==original
            assert len(state['cells'])==107, 'render must retain original cells while native representation changes'
        elapsed=time.perf_counter()-start
        h=state['hybrid']
        assert seen_coast and not h['collapsed'] and h['active_native_bodies']==107
        assert 0<h['coast_time_s']<state['time_s']
        assert len(h['transfers'])==2 and h['transfers'][1]['action']=='prospective contact'
        for t in h['transfers']:
            assert t['admitted'] and t['measured'] and abs(t['energy_change_j'])<1e-5 and abs(t['mass_change_kg'])<1e-6
            assert math.hypot(*t['linear_change_n_s'])<1e-5 and math.hypot(*t['angular_change_n_m_s'])<1e-5
        assert state['contact_audit']['point_samples']>0
        if args.full and material in ['glass','ice']:
            assert state['objects'][0]['broken_faces']>0, 'restored material connections must actually break under this drop'
        row={'material':material,'time_s':state['time_s'],'wall_s':elapsed,'coast_time_s':h['coast_time_s'],
             'substeps':state['substeps'],'sheet_pieces':state['objects'][0]['pieces'],
             'broken_faces':state['objects'][0]['broken_faces'],'transfers':h['transfers'],
             'energy_j':state['diagnostics']['unclosed_energy_j'],
             'linear_residual_n_s':state['contact_audit']['linear_momentum_residual_n_s'],
             'angular_residual_n_m_s':state['step_work']['full_angular_residual_n_m_s']}
        results.append(row);print(json.dumps(row),flush=True)
    finally:
        proc.stdin.close();proc.wait(timeout=5)
# A command arriving during coast must not queue forces on parked source IDs.
proc=subprocess.Popen([str(args.native.resolve()),'--serve'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
try:
    state=call({'op':'create','declaration':{'hybrid_free_flight':True,'face_law':'centered-log-gradient','height_m':.1}})
    assert state['hybrid']['collapsed']
    call({'op':'advance','steps':16})
    call({'op':'accelerate_object','object':2,'acceleration_m_s2':[0,20,0]})
    state=call({'op':'advance','steps':16})
    assert not state['hybrid']['collapsed'] and state['hybrid']['transfers'][1]['action']=='external loading'
    assert abs(state['time_s']-1/30)<1e-8
    assert math.hypot(*state['actuation']['force_phase_impulse_residual_n_s'])<1e-5
    print('PASS command during coast restores detailed cells before actual native force',flush=True)
finally:
    proc.stdin.close();proc.wait(timeout=5)
if args.output:args.output.write_text(json.dumps(results,indent=2),encoding='utf-8')
print('PASS original cells/restored native contact across glass/oak/iron/ice; material accuracy and realtime remain separate gates')
