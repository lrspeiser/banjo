"""Compare exact prior phase kernels and measure the unresolved full-scene gate.

Run from the repository root with the pinned GPU Python runtime. Diagnostic
measurement is not a gameplay admission; --check-record explicitly fails when
the current complete glass experiment refuses or is slower than realtime.
"""
import argparse,ast,hashlib,json,subprocess,sys,time
from pathlib import Path
import cupy as cp
import numpy as np
sys.path.insert(0,str(Path.cwd()/'scripts'))
import gpu_coupled_world as g
def require_clock_gate(report):
    if report['source_sha256']!=g.source_hash():raise SystemExit('FAIL: measurement is not the current loaded physics source')
    current=next(r for r in report['glass_10m'] if r['path']=='current')
    if current['refusal'] or current['physical_s']<2-1e-12 or current['wall_s']>current['physical_s']:
        raise SystemExit('FAIL: full 10 m glass gate: %.6f physical s / %.6f wall s; %s' %
                         (current['physical_s'],current['wall_s'],current['refusal'] or 'not realtime'))
    print('PASS: scoped complete glass clock gate; other physics/platform qualifications remain separate')
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--check-record',type=Path,help='Check a saved current-source measurement; fail on incomplete/slow glass')
args=parser.parse_args()
if args.check_record:
    require_clock_gate(json.loads(args.check_record.read_text()))
    raise SystemExit(0)
baseline_revision='2747d8c1f798c36db8286cc7e8e455fccd359d4e'
tree=ast.parse(subprocess.check_output(['git','show',baseline_revision+':scripts/gpu_coupled_world.py'],text=True))
old_kernel=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='KERNEL' for t in n.targets))
code='\n'.join((g.ROOT/n).read_text().replace('#pragma once','') for n in g.HEADERS)+'\n'+old_kernel
old_module=cp.RawModule(code=code,options=('--std=c++17','--fmad=false'))
old_pairs=old_module.get_function('prepare_pairs');old_ledger=old_module.get_function('gather_ledger_trials')
def reference_phases(e):
    e.phases['prepare_initial_pairs']=lambda *a:None
    e.phases['prepare_pairs']=lambda grid,block,a:old_pairs(grid,block,a[:6]+a[7:])
    e.phases['gather_active_ledger_trials']=lambda grid,block,a:old_ledger(grid,block,(a[0],a[3],a[6],a[7]))
def world(material,reference=False):
    w=g.GpuCoupledWorld(dict(material=material,height_m=10,dt_s=1/240,representation_policy='partitioned-flight'))
    if reference:
        reference_phases(w.eval);reference_phases(w.representations.island)
    return w
def physical(w):
    s=w.snapshot();return json.dumps({k:s[k] for k in ('time_s','dt_s','ticks','cells','history_arrays','diagnostics','substep_accounts')},sort_keys=True,separators=(',',':')).encode()
comparisons=[]
for material in ('glass','oak','iron','ice'):
    old=world(material,True);new=world(material);wall=[0.,0.]
    for tick in range(24):
        for index,w in ([(0,old),(1,new)] if tick%2==0 else [(1,new),(0,old)]):
            start=time.perf_counter();w.advance(1);wall[index]+=time.perf_counter()-start
        assert physical(old)==physical(new),(material,tick,'physical change')
    r=dict(material=material,conditions=new.d,physical_s=new.time,reference_wall_s=wall[0],current_wall_s=wall[1],
           speedup=wall[0]/wall[1],exact_common_time_state=True,state_sha256=hashlib.sha256(physical(new)).hexdigest(),diagnostics=new.snapshot()['diagnostics'])
    comparisons.append(r);print(material,r['speedup'],flush=True)
full=[]
for reference in (False,True):
    w=world('glass',reference);start=time.perf_counter();refusal=None;chain=hashlib.sha256()
    for tick in range(480):
        try:w.advance(1);chain.update(physical(w))
        except RuntimeError as error:refusal=str(error);break
    wall=time.perf_counter()-start;s=w.snapshot();witness=s.get('rejected_candidate')
    record=dict(path='prior phase kernels' if reference else 'current',physical_s=w.time,wall_s=wall,refusal=refusal,
                accepted_state_chain_sha256=chain.hexdigest(),accepted_final_state_sha256=hashlib.sha256(physical(w)).hexdigest(),
                diagnostics=s['diagnostics'],microsteps=s['performance']['microsteps'],iterations=s['performance']['nonlinear_iterations'],
                refusal_witness_sha256=hashlib.sha256(json.dumps(witness,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
                refusal_counts={name:sum(r['error']==name for r in witness['subdivision_refusals']) for name in set(r['error'] for r in witness['subdivision_refusals'])} if witness else {},
                last_solver_error=witness.get('last_solver_failure',{}).get('iterations',[])[-1] if witness else None)
    full.append(record);print(record['path'],record['physical_s'],wall,refusal,flush=True)
    Path('build/gpu-representations/current-glass-'+str(reference)+'.json').write_text(json.dumps(s,indent=2))
assert full[0]['accepted_state_chain_sha256']==full[1]['accepted_state_chain_sha256']
assert full[0]['refusal_witness_sha256']==full[1]['refusal_witness_sha256']
result=dict(source_sha256=g.source_hash(),baseline_revision=baseline_revision,
            scope='Same shared laws and controller; baseline reconstructs only prior pair/ledger phase kernels. Complete Python advance/snapshot, excludes HTTP/render. Alternating-order four-material prefix and two complete glass attempts.',
            prefix=comparisons,glass_10m=full,whole_world_realtime=False,impact_complete=False)
Path('build/gpu-representations/active-graph-performance.json').write_text(json.dumps(result,indent=2)+'\n')
