"""Exact parallel/reference candidate, local Jacobian and physical-history parity."""
import argparse,json,sys,time
from pathlib import Path
import cupy as cp
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from gpu_coupled_world import GpuCoupledWorld,source_hash
PUBLIC=('poses','residual','history','forces','ledger','faults')
def exact(a,b):
    a=cp.asnumpy(a) if isinstance(a,cp.ndarray) else np.asarray(a)
    b=cp.asnumpy(b) if isinstance(b,cp.ndarray) else np.asarray(b)
    assert a.dtype==b.dtype and a.shape==b.shape
    assert a.tobytes()==b.tobytes(),float(np.max(abs(a-b),initial=0))
def physical(s):
    return json.dumps({k:s[k] for k in ('time_s','dt_s','ticks','cells','history_arrays','diagnostics','substep_accounts')},sort_keys=True,separators=(',',':'))
def main(args):
    rng=np.random.default_rng(4123);comparisons=[];trial_count=0;jacobian_count=0
    for material in ('glass','oak','iron','ice'):
        p=GpuCoupledWorld(dict(material=material,height_m=.001,dt_s=1/240,pipeline='parallel'))
        r=GpuCoupledWorld(dict(material=material,height_m=.001,dt_s=1/240,pipeline='serial-reference'))
        v=cp.asarray(rng.normal(size=(32,p.eval.n,6))*1e-5);v[:,:3]=0
        po=p.eval.evaluate(v,1/960);ro=r.eval.evaluate(v,1/960)
        for key in PUBLIC:exact(po[key],ro[key])
        assert not bool(cp.any(po['faults']));trial_count+=len(v)
        # Every single-DOF candidate has the same complete residual as a fresh
        # whole-scene evaluation, including all unchanged pair contributions.
        base=p.eval.evaluate(v[0],1/960);original=v[0].reshape(-1);y=original[p.eval.dynamic]*p.eval.active_weights;d=len(y)
        perturbed=cp.broadcast_to(original,(2*d,len(original))).copy();ids=cp.arange(d);columns=p.eval.dynamic
        epsilon=1e-12*cp.maximum(1.,abs(y));perturbed[ids,columns]+=epsilon/p.eval.active_weights;perturbed[d+ids,columns]-=epsilon/p.eval.active_weights
        localized=p.eval.evaluate(perturbed,1/960,_jacobian_base=base)
        saved={k:localized[k].copy() for k in PUBLIC};full=p.eval.evaluate(perturbed,1/960)
        for key in PUBLIC:exact(saved[key],full[key])
        jacobian_count+=2*d
        # A fresh base is regenerated after each real accepted state change.
        wall={'parallel':0.,'serial-reference':0.};microsteps=0
        for tick in range(10):
            t=time.perf_counter();ps=p.advance(1);wall['parallel']+=time.perf_counter()-t
            t=time.perf_counter();rs=r.advance(1);wall['serial-reference']+=time.perf_counter()-t
            assert physical(ps)==physical(rs),(material,tick,'changed physical trajectory/history')
            microsteps+=len(ps['substep_accounts'])
        comparisons.append(dict(material=material,physical_time_s=ps['time_s'],microsteps=microsteps,wall_s=wall,
            speedup=wall['serial-reference']/wall['parallel'],diagnostics=ps['diagnostics']))
        print(material,'entire trajectory bitwise equal',wall,flush=True)
    result=dict(schema='banjo.cupy-parallel-parity.v1',source_sha256=source_hash(),candidate_trials=trial_count,localized_jacobian_trials=jacobian_count,
        exact_candidate_parity=True,exact_physical_history_parity=True,comparisons=comparisons,realtime_qualified=False)
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);main(p.parse_args())
