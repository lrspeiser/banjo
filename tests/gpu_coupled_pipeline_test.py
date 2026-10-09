"""Exact parallel/reference candidate, local Jacobian and physical-history parity."""
import argparse,json,sys,time
from pathlib import Path
import cupy as cp
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from gpu_coupled_world import GpuCoupledWorld,TrialFailure,source_hash
PUBLIC=('poses','residual','history','forces','ledger','faults')
def exact(a,b):
    a=cp.asnumpy(a) if isinstance(a,cp.ndarray) else np.asarray(a)
    b=cp.asnumpy(b) if isinstance(b,cp.ndarray) else np.asarray(b)
    assert a.dtype==b.dtype and a.shape==b.shape
    assert a.tobytes()==b.tobytes(),float(np.max(abs(a-b),initial=0))
def physical(s):
    return json.dumps({k:s[k] for k in ('time_s','dt_s','ticks','cells','history_arrays','diagnostics','substep_accounts')},sort_keys=True,separators=(',',':'))
def fault_precedence(kernel):
    # Exercise empty and partial blocks, row tails, multiple contribution
    # faults, and the exact reference order across unrelated error categories.
    cases=0
    for n in (1,13,32):
        for rows in (0,1,127,128,129,4097):
            batch=9;contribution=np.zeros((batch,rows),np.int32);body=np.zeros((batch,6*n),np.int32)
            poses=np.zeros((batch,7*n));ledger=np.zeros((batch,12))
            if rows:
                contribution[1,-1]=3;contribution[2,0]=4
                if rows>1:contribution[2,-1]=1
                contribution[3,-1]=contribution[4,-1]=contribution[7,-1]=6;contribution[8,-1]=2
            body[4,-1]=body[8,-1]=5;poses[5,-1]=poses[6,0]=poses[7,-1]=np.nan
            ledger[6,-1]=ledger[7,-1]=np.inf
            expected=[]
            for c,b,p,l in zip(contribution,body,poses,ledger):
                early=[f for f in c if f and f!=6]
                expected.append(int(early[0]) if early else 5 if np.any(b) else 6 if np.any(c==6) else 7 if not np.isfinite(p).all() else 8 if not np.isfinite(l).all() else 0)
            output=cp.empty(batch,dtype=cp.int32)
            kernel((batch,),(128,),(np.uint32(n),np.uint32(rows),np.uint32(batch),cp.asarray(contribution),cp.asarray(body),cp.asarray(poses),cp.asarray(ledger),output))
            assert np.array_equal(cp.asnumpy(output),expected),(n,rows)
            cases+=batch
    return cases
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
    faults=fault_precedence(p.eval.phases['collect_trial_faults'])
    # The diagnostic candidate is an actual private solve, not an estimate of
    # what should have happened. Observation must not mutate the physical input.
    w=GpuCoupledWorld(dict(experiment='freefall',height_m=.1,dt_s=1/240))
    before=w.eval.bodies.copy();edges=w.eval.edges.copy()
    try:w.eval.solve(1/240,maximum_iterations=1);raise AssertionError('Deliberate iteration limit was admitted')
    except TrialFailure as error:
        d=error.details;assert str(error)=='Coupled Newton iteration budget exceeded'
    exact(before,w.eval.bodies);exact(edges,w.eval.edges)
    assert len(d['iterations'])==1 and d['last_evaluated']['faults']==[0]
    assert len(d['initial_bodies'])==2 and d['initial_edges']==[] and d['dt_s']==1/240
    assert d['last_evaluated']['velocity'][0][-1][1]<0 and d['initial_bodies'][-1][15]==0
    assert len(d['jacobian_singular_values'])==6 and np.isfinite(d['jacobian']).all()
    result=dict(schema='banjo.cupy-parallel-parity.v1',source_sha256=source_hash(),candidate_trials=trial_count,localized_jacobian_trials=jacobian_count,
        exact_candidate_parity=True,exact_physical_history_parity=True,fault_precedence_cases=faults,private_refusal_diagnostics=True,comparisons=comparisons,realtime_qualified=False)
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);main(p.parse_args())
