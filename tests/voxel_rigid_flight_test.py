"""Actual disconnected-cell flight, retained source mass and later contact.

Default controls compare full low-drop physical records with the detailed mode.
--full also completes four 10m impacts and checks native recontact after flight.
This tests lifecycle and failure gates, not calibrated fracture or realtime.
"""
import argparse, copy, json, math, subprocess, time
from pathlib import Path
parser=argparse.ArgumentParser()
parser.add_argument('native',type=Path)
parser.add_argument('--full',action='store_true')
parser.add_argument('--output',type=Path)
parser.add_argument('--dt',type=float,default=1/960)
args=parser.parse_args();results=[]

def physical(s):
    s=copy.deepcopy(s);s['declaration'].pop('local_rigid_flight',None);s.pop('rigid_flight',None)
    s['diagnostics'].pop('profile');s['diagnostics'].pop('max_step_wall_ms');return s

def run(material,flight,height,end):
    proc=subprocess.Popen([str(args.native.resolve()),'--serve'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
    def call(command):
        proc.stdin.write(json.dumps(command)+'\n');proc.stdin.flush();r=json.loads(proc.stdout.readline())
        assert r['ok'],r.get('error');return r['state']
    try:
        begin=time.perf_counter()
        state=call({'op':'create','declaration':{'sheet':material,'height_m':height,'local_rigid_flight':flight,'dt_s':args.dt}})
        original={c['id']:c['mass_kg'] for c in state['cells']};frames=[]
        ticks=round(end/args.dt)
        for n in range(0,ticks,16):
            state=call({'op':'advance','steps':min(16,ticks-n)})
            assert {c['id']:c['mass_kg'] for c in state['cells']}==original
            assert len(state['cells'])==107 and all(math.isfinite(x) for c in state['cells'] for x in c['position_m'])
            frames.append(physical(state))
        elapsed=time.perf_counter()-begin
        f=state.get('rigid_flight')
        if f:
            assert sum(x['accepted_intervals'] for x in f['flown_cells'])==f['accepted_cell_intervals']
            flown={x['body'] for x in f['flown_cells']}
            assert set(f['returned_contact_cells'])<=flown
            assert all(body in original for body in flown)
        row={'material':material,'height_m':height,'dt_s':args.dt,'time_s':state['time_s'],'wall_s':elapsed,
             'substeps':state['substeps'],'sheet_pieces':state['objects'][0]['pieces'],
             'broken_faces':state['objects'][0]['broken_faces'],'flight':f,
             'unclosed_energy_j':state['diagnostics']['unclosed_energy_j'],
             'linear_residual_n_s':state['contact_audit']['linear_momentum_residual_n_s'],
             'angular_residual_n_m_s':state['step_work']['full_angular_residual_n_m_s']}
        return row,frames
    finally:proc.stdin.close();proc.wait(timeout=5)

for material in ['glass','oak','iron','ice']:
    reference,a=run(material,False,.1,.3);experiment,b=run(material,True,.1,.3)
    assert a==b,material+': conservative no-flight control changed a physical/work record'
    assert experiment['flight']['accepted_cell_intervals']==0
    print(material+': low-drop detailed physical/work parity at every output',flush=True)
if args.full:
    for material in ['glass','oak','iron','ice']:
        row,_=run(material,True,10,2);results.append(row)
        if material in ['oak','iron']:assert row['flight']['accepted_cell_intervals']==0 and row['broken_faces']==0
        if material=='ice':
            assert row['flight']['accepted_cell_intervals']>0
            assert row['flight']['peak_free_surface_travel_m']>.004*.05, 'did not actually leave old global motion budget'
            assert row['flight']['returned_contact_cells'], 'must test actual later native collision after free flight'
        print(json.dumps(row),flush=True)
if args.output:args.output.write_text(json.dumps(results,indent=2),encoding='utf-8')
print('PASS native lifecycle and detailed controls; accuracy/refinement/realtime are separate gates')
