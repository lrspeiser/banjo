"""Native execution optimization: full native state parity through material impacts."""
import copy,json,subprocess,sys,time
from pathlib import Path

def physical(reply):
    result=copy.deepcopy(reply)
    result['state']['diagnostics'].pop('profile')
    result['state']['diagnostics'].pop('max_step_wall_ms')
    return result

exe=Path(sys.argv[1]).resolve()
for material in ['glass','oak','iron','ice']:
    processes=[subprocess.Popen([str(exe),mode],stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,text=True) for mode in ['--serve','--serve-reference']]
    timings=[0.,0.]
    def request(command):
        replies=[]
        for i,proc in enumerate(processes):
            start=time.perf_counter()
            proc.stdin.write(json.dumps(command)+'\n');proc.stdin.flush()
            replies.append(json.loads(proc.stdout.readline()))
            timings[i]+=time.perf_counter()-start
        assert physical(replies[0])==physical(replies[1]),'execution changed physical state: '+material
        assert replies[0]['ok'],replies[0].get('error')
        return replies[0]['state']
    try:
        first=request({'op':'create','declaration':{'sheet':material}})
        for _ in range(120):state=request({'op':'advance','steps':16})
        assert abs(state['time_s']-2)<1e-8
        assert {c['id']:c['mass_kg'] for c in state['cells']}=={c['id']:c['mass_kg'] for c in first['cells']}
        print(json.dumps({'material':material,'ticks':state['ticks'],'substeps':state['substeps'],
            'scene_s':timings[0],'reference_s':timings[1],
            'speedup':timings[1]/timings[0], 'pieces':state['objects'][0]['pieces'],
            'unclosed_energy_j':state['diagnostics']['unclosed_energy_j'],
            'linear_momentum_residual_n_s':state['contact_audit']['linear_momentum_residual_n_s'],
            'parity':'exact at every 16 host ticks; profiler excluded'}),flush=True)
    finally:
        for proc in processes:proc.terminate();proc.wait(timeout=5)
print('PASS glass/oak/iron/ice execution parity through 2 s native impacts',flush=True)
