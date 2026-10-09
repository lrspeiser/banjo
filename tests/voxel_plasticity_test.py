"""Live constitutive integration regression; not a calibrated plasticity gate."""
import argparse,json,math,subprocess,time
from pathlib import Path
parser=argparse.ArgumentParser()
parser.add_argument('native')
parser.add_argument('--results',type=Path)
args=parser.parse_args()
results=[]
for material,plastic,dt in [('glass',False,1/960),('oak',False,1/960),('iron',False,1/960),('iron',True,1/960),('iron',True,1/1920)]:
    p=subprocess.Popen([args.native,'--serve'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
    def request(command):
        p.stdin.write(json.dumps(command)+'\n');p.stdin.flush()
        reply=json.loads(p.stdout.readline())
        assert reply['ok'],reply.get('error')
        return reply['state']
    start=time.perf_counter()
    try:
        declaration={'sheet':material,'ball':'iron','mass_kg':5,'height_m':1,
                     'face_law':'centered-log-gradient','contact_law':'midpoint-block-friction','dt_s':dt}
        if plastic:declaration['sheet_plasticity']=True
        initial=request({'op':'create','declaration':declaration})
        state=initial
        for _ in range(round(.6/dt)//16):state=request({'op':'advance','steps':16})
        assert abs(state['time_s']-.6)<1e-9,'accepted clock mismatch'
        assert state['diagnostics']['dynamic_mass_kg']==initial['diagnostics']['dynamic_mass_kg'],'mass changed'
        assert all(math.isfinite(x) for c in state['cells'] for x in c['position_m']+c['velocity_m_s']+c['spin_rad_s'])
        response=state.get('plasticity')
        if plastic:
            assert response['yielded_connectors']>0 and response['plastic_work_j']>0,'heavy impact must cause yielding'
            assert response['return_excess_j']>=0,'projection loss cannot be negative'
            assert any(any(abs(x)>0 for x in h['plastic_rest']) for h in response['history']),'permanent rest missing'
            assert math.isclose(sum(h['plastic_work_j'] for h in response['history']),response['plastic_work_j'],rel_tol=1e-11,abs_tol=1e-10),'history/work mismatch'
            assert math.isclose(sum(h['return_excess_j'] for h in response['history']),response['return_excess_j'],rel_tol=1e-11,abs_tol=1e-10),'history/numerical loss mismatch'
            # Continued stepping must retain accumulated history; no visual-only dent.
            later=request({'op':'advance','steps':16})
            for before,after in zip(response['history'],later['plasticity']['history']):
                assert after['plastic_work_j']>=before['plastic_work_j']
                assert after['yielded_updates']>=before['yielded_updates']
        else:assert response is None,'elastic/brittle controls silently changed law'
        record={'material':material,'plastic':plastic,'dt_s':dt,'wall_s':time.perf_counter()-start,
                'initial':initial,'final':state,'continued':later if plastic else None}
        results.append(record)
        print(json.dumps({'material':material,'plastic':plastic,'dt_s':dt,'wall_s':record['wall_s'],
                          'substeps':state['substeps'],'unclosed_energy_j':state['diagnostics']['unclosed_energy_j'],
                          'yielded':response['yielded_connectors'] if response else 0,
                          'plastic_work_j':response['plastic_work_j'] if response else 0,
                          'return_excess_j':response['return_excess_j'] if response else 0}),flush=True)
        if args.results:args.results.write_text(json.dumps(results),encoding='utf-8')
    finally:
        p.stdin.close();p.wait()
print('PASS integrated yielding/history, matched glass/oak/iron controls and measured two-timestep results; full conservation/refinement and tearing remain unqualified')
