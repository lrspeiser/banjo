"""Native execution optimization: full native state parity through material impacts."""
import argparse,copy,json,subprocess,time
from pathlib import Path

parser=argparse.ArgumentParser()
parser.add_argument('native')
parser.add_argument('baseline',nargs='?')
parser.add_argument('--dormant-spring-baseline',action='store_true',
    help='Exclude only the impulse-source diagnostics corrected by dormant spring scheduling')
args=parser.parse_args()
if args.dormant_spring_baseline and not args.baseline:
    parser.error('--dormant-spring-baseline requires a baseline executable')

def physical(reply):
    result=copy.deepcopy(reply)
    result['state']['diagnostics'].pop('profile')
    result['state']['diagnostics'].pop('max_step_wall_ms')
    if args.dormant_spring_baseline:
        result['state']['diagnostics'].pop('max_spring_solver_residual_n')
        result['state']['step_work']['measured'].pop('solver_angular_residual_n_m_s')
        result['state']['step_work']['measured'].pop('solver_linear_residual_n_s')
    elif args.baseline:result['state'].pop('step_work',None)
    return result

def differences(a,b,path=''):
    if type(a)!=type(b):return [path+': type differs']
    if isinstance(a,dict):
        if a.keys()!=b.keys():return [path+': keys differ']
        return [d for key in a for d in differences(a[key],b[key],path+'/'+key)]
    if isinstance(a,list):
        if len(a)!=len(b):return [path+': length differs']
        return [d for i,(x,y) in enumerate(zip(a,b)) for d in differences(x,y,path+'/'+str(i))]
    return [] if a==b else [path+': '+str(a)+' versus '+str(b)]

exe=Path(args.native).resolve()
reference_exe=Path(args.baseline).resolve() if args.baseline else exe
for material in ['glass','oak','iron','ice']:
    processes=[subprocess.Popen([str(binary),mode],stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,text=True) for binary,mode in [(exe,'--serve'),(reference_exe,'--serve-reference')]]
    timings=[0.,0.]
    def request(command):
        replies=[]
        for i,proc in enumerate(processes):
            start=time.perf_counter()
            proc.stdin.write(json.dumps(command)+'\n');proc.stdin.flush()
            replies.append(json.loads(proc.stdout.readline()))
            timings[i]+=time.perf_counter()-start
        delta=differences(physical(replies[0]),physical(replies[1]))
        assert not delta,'execution changed state: '+material+' at '+str(replies[0]['state']['time_s'])+' s: '+str(delta[:12])
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
        if args.baseline:print(json.dumps({'material':material,'new_step_work':state['step_work'],
            'excluded_corrected_diagnostics':(['max_spring_solver_residual_n','solver_angular_residual_n_m_s','solver_linear_residual_n_s']
                if args.dormant_spring_baseline else ['step_work'])}),flush=True)
    finally:
        for proc in processes:proc.terminate();proc.wait(timeout=5)
print('PASS glass/oak/iron/ice execution parity through 2 s native impacts',flush=True)
