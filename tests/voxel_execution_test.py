"""Native execution optimization: full native state parity through material impacts."""
import argparse,copy,json,math,subprocess,time
from pathlib import Path

parser=argparse.ArgumentParser()
parser.add_argument('native')
parser.add_argument('baseline',nargs='?')
parser.add_argument('--dormant-spring-baseline',action='store_true',
    help='Exclude only the impulse-source diagnostics corrected by dormant spring scheduling')
parser.add_argument('--contact-model-baseline',action='store_true',
    help='Exclude only the new contact model qualification label, retaining every work field')
parser.add_argument('--friction-fastpath-baseline',action='store_true',
    help='Five coupled-friction drops; compare both inline binaries, retaining every physical and work field')
parser.add_argument('--strict-inline-baseline',action='store_true',
    help='Compare inline binaries and retain every physical/work field; only wall profiling is excluded')
parser.add_argument('--alternate-request-order',action='store_true',
    help='Alternate which binary calculates first, limiting order bias in paired timing')
parser.add_argument('--case',choices=['glass-iron','oak-iron','iron-iron','ice-iron','glass-glass'],
    help='Run one declared material pair for diagnosis')
parser.add_argument('--host-ticks',type=int,default=1920,
    help='Bounded duration, 16-tick multiples up to the full two-second experiment')
parser.add_argument('--witness-path',type=Path,help='Write both actual replies and the command on a parity failure')
args=parser.parse_args()
if args.strict_inline_baseline and (not args.baseline or args.contact_model_baseline or args.dormant_spring_baseline):
    parser.error('--strict-inline-baseline requires a baseline and no diagnostic exclusions')
if not 16<=args.host_ticks<=1920 or args.host_ticks%16:
    parser.error('--host-ticks must be a multiple of 16 in [16,1920]')
if args.case=='glass-glass' and not args.friction_fastpath_baseline:
    parser.error('glass-glass comparison requires --friction-fastpath-baseline')
if args.friction_fastpath_baseline and (not args.baseline or args.contact_model_baseline or args.dormant_spring_baseline):
    parser.error('--friction-fastpath-baseline requires a baseline and no diagnostic exclusions')
if args.dormant_spring_baseline and not args.baseline:
    parser.error('--dormant-spring-baseline requires a baseline executable')
if args.contact_model_baseline and (not args.baseline or args.dormant_spring_baseline):
    parser.error('--contact-model-baseline requires a baseline and cannot combine with dormant audit exclusion')

def physical(reply):
    result=copy.deepcopy(reply)
    result['state']['diagnostics'].pop('profile')
    result['state']['diagnostics'].pop('max_step_wall_ms')
    if args.contact_model_baseline:
        result['state']['qualification'].pop('contact_law',None)
    elif args.dormant_spring_baseline:
        result['state']['diagnostics'].pop('max_spring_solver_residual_n')
        result['state']['step_work']['measured'].pop('solver_angular_residual_n_m_s')
        result['state']['step_work']['measured'].pop('solver_linear_residual_n_s')
    elif args.baseline and not (args.friction_fastpath_baseline or args.strict_inline_baseline):result['state'].pop('step_work',None)
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
cases=[(m,'iron') for m in ['glass','oak','iron','ice']]
if args.friction_fastpath_baseline:cases.append(('glass','glass'))
if args.case:cases=[pair for pair in cases if '-'.join(pair)==args.case]
for material,ball in cases:
    reference_mode='--serve' if args.friction_fastpath_baseline or args.strict_inline_baseline else '--serve-reference'
    processes=[subprocess.Popen([str(binary),mode],stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,text=True) for binary,mode in [(exe,'--serve'),(reference_exe,reference_mode)]]
    timings=[0.,0.]
    def request(command):
        replies=[None,None]
        order=[1,0] if args.alternate_request_order and request.counter%2 else [0,1]
        request.counter+=1
        for i in order:
            proc=processes[i]
            start=time.perf_counter()
            proc.stdin.write(json.dumps(command)+'\n');proc.stdin.flush()
            replies[i]=json.loads(proc.stdout.readline())
            timings[i]+=time.perf_counter()-start
        delta=differences(physical(replies[0]),physical(replies[1]))
        if delta and args.witness_path:
            args.witness_path.write_text(json.dumps({'declaration':declaration,'command':command,
                'native':str(exe),'baseline':str(reference_exe),'differences':delta,
                'actual_replies':replies},indent=2),encoding='utf-8')
        assert not delta,'execution changed state: '+material+' at '+str(replies[0]['state']['time_s'])+' s: '+str(delta[:12])
        assert replies[0]['ok'],replies[0].get('error')
        state=replies[0]['state'];profile=state['diagnostics']['profile'];stages=profile.get('execution')
        if stages:
            assert stages['enabled'] and stages['step_calls']==state['substeps']+state['rejected_trials']
            assert stages['trial_calls']==stages['step_calls'] and stages['trial_restores']==state['rejected_trials']
            assert all(math.isfinite(v) and v>=0 for key,v in stages.items() if key.endswith('_ms'))
            step_sum=sum(stages[key] for key in ['step_prepare_ms','native_update_ms','contact_observation_ms','post_step_ms'])
            assert step_sum<=profile['native_step_ms']+1e-3,'disjoint native stage time exceeds its enclosing measurement'
        return replies[0]['state']
    request.counter=0
    try:
        declaration={'sheet':material}
        if args.friction_fastpath_baseline:
            declaration.update(ball=ball,contact_law='midpoint-block-friction',face_law='centered-log-gradient')
        first=request({'op':'create','declaration':declaration})
        for _ in range(args.host_ticks//16):state=request({'op':'advance','steps':16})
        assert abs(state['time_s']-args.host_ticks/960)<1e-8
        assert {c['id']:c['mass_kg'] for c in state['cells']}=={c['id']:c['mass_kg'] for c in first['cells']}
        print(json.dumps({'material':material,'ball':ball,'ticks':state['ticks'],'substeps':state['substeps'],
            'scene_s':timings[0],'reference_s':timings[1],
            'speedup':timings[1]/timings[0], 'pieces':state['objects'][0]['pieces'],
            'request_order':'alternating' if args.alternate_request_order else 'scene then baseline',
            'unclosed_energy_j':state['diagnostics']['unclosed_energy_j'],
            'profile':state['diagnostics']['profile'],
            'linear_momentum_residual_n_s':state['contact_audit']['linear_momentum_residual_n_s'],
            'parity':'exact at every 16 host ticks; profiler excluded'}),flush=True)
        if args.baseline:print(json.dumps({'material':material,'ball':ball,'new_step_work':state['step_work'],
            'excluded_corrected_diagnostics':(['max_spring_solver_residual_n','solver_angular_residual_n_m_s','solver_linear_residual_n_s']
                if args.dormant_spring_baseline else ['qualification/contact_law'] if args.contact_model_baseline else [] if args.friction_fastpath_baseline or args.strict_inline_baseline else ['step_work'])}),flush=True)
    finally:
        for proc in processes:proc.terminate();proc.wait(timeout=5)
print('PASS '+(args.case or ('five coupled-friction' if args.friction_fastpath_baseline else 'glass/oak/iron/ice'))+
      ' execution parity through '+str(args.host_ticks/960)+' s native experiment',flush=True)
