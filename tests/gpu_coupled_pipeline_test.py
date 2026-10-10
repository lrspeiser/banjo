"""Exact parallel/reference candidate, local Jacobian and physical-history parity."""
import argparse,json,sys,time
from pathlib import Path
import cupy as cp
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from gpu_coupled_world import CoupledEvaluator,GpuCoupledWorld,TrialFailure,source_hash
PUBLIC=('poses','residual','history','forces','ledger','faults')

def rounded_surface_boundary():
    # Same measured zero-radius sample as the compiled native contact test.
    # The pre-repair world-space closest point loses its exterior displacement
    # and returns a NaN normal. This oracle is geometric, not material-specific.
    from gpu_coupled_world import HEADERS
    # Match the installed evaluator's explicit stack capacity for the shared
    # bounded shape-dispatch calls, including this standalone kernel oracle.
    cp.cuda.Device(0).use()
    if cp.cuda.runtime.deviceGetLimit(cp.cuda.runtime.cudaLimitStackSize)<16384:
        cp.cuda.runtime.deviceSetLimit(cp.cuda.runtime.cudaLimitStackSize,16384)
    code='\n'.join((ROOT/name).read_text().replace('#pragma once','') for name in HEADERS)+r'''
    extern "C" __global__ void boundary(double *out){
        double a[30]{},b[30]{};a[0]=b[0]=1;
        a[4]=a[5]=a[6]=b[4]=b[5]=b[6]=.0125;
        banjo::DGPose pa{{.012500000000000015,.06379968846241157,-.012500000000000164},
                        {1,5.225713013386706e-15,-5.027304629602819e-15,9.12335065991894e-15}};
        banjo::DGPose pb{{.012500000000000035,.0887996884624115,-.012499999999999954},
                        {1,3.3444898121104495e-15,-1.612270849281483e-15,1.935251965707791e-15}};
        const auto result=banjo::dgSurfaceContact(a,b,pa,pb,12);
        out[0]=result.gap;
        const banjo::FrameVector rows[]{result.gradient.force_a,result.gradient.torque_a,
                                      result.gradient.force_b,result.gradient.torque_b};
        for(unsigned i=0;i<4;++i){out[1+3*i]=rows[i].x;out[2+3*i]=rows[i].y;out[3+3*i]=rows[i].z;}
    }
    '''
    module=cp.RawModule(code=code,options=('--std=c++17','--fmad=false'))
    out=cp.empty(13,dtype=cp.float64);module.get_function('boundary')((1,),(1,),(out,))
    result=cp.asnumpy(out);assert np.isfinite(result).all()
    # Independent 80-digit arithmetic on the implemented rotated lever/axes
    # places the unrounded sample inside. The earlier positive distance was a
    # consequence of rounding the surface point into its world center first.
    assert abs(result[0]-(-4.760854624018894e-19))<1e-31
    assert abs(np.linalg.norm(result[1:4])-1)<1e-14
    assert np.linalg.norm(result[1:4]+result[7:10])<1e-14
    return dict(gap_m=float(result[0]),finite_normal=True,unit_normal=True,force_reaction=True)
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

def active_ledger_parity(evaluator):
    # Empty groups, inactive zero rows and sparse mixed-sign active work retain
    # the exact serial row order. Include overflow/nonfinite witnesses: this
    # optimization must not erase the original refusal condition.
    rng=np.random.default_rng(2871);cases=0
    for edges,sizes in ((0,[]),(1,[1]),(5,[24,48,1]),(48,[48]*75)):
        pairs=len(sizes);offsets=edges+np.r_[0,np.cumsum(sizes)].astype(np.uint32)
        rows=int(offsets[-1]);batch=17
        active=rng.integers(0,2,size=(batch,pairs),dtype=np.uint8)
        work=rng.normal(size=(batch,rows,12))*10**rng.uniform(-20,20,size=(batch,rows,12))
        for i in range(batch):
            for p in range(pairs):
                if not active[i,p]:work[i,offsets[p]:offsets[p+1]]=0
        if rows:
            if edges:
                work[-1,0,3]=np.nan
                if edges>1:work[-2,:2,4]=np.finfo(np.float64).max
        data=cp.asarray(work);out=cp.empty((batch,12));reference=cp.empty_like(out)
        args=(np.uint32(rows),np.uint32(batch),data,reference)
        evaluator.phases['gather_ledger_trials'](((batch*12+127)//128,),(128,),args)
        evaluator.phases['gather_active_ledger_trials'](((batch*12+127)//128,),(128,),
            (np.uint32(rows),np.uint32(edges),np.uint32(pairs),np.uint32(batch),cp.asarray(offsets),cp.asarray(active),data,out))
        exact(out,reference);cases+=batch
    return cases

def actual_final_update_replay():
    archive=json.loads((ROOT/'docs/evidence/gpu-representations/backend-performance.json').read_text())
    d=archive['glass_drop']['state']['rejected_candidate']['last_solver_failure']
    e=CoupledEvaluator(d['initial_bodies'],d['initial_edges'],pipeline='parallel',
        newton_strategy=d['newton_strategy'],line_search=d['line_search'],linear_backend=d['linear_backend'])
    bodies=e.bodies.copy();edges=e.edges.copy()
    out,_,updates,residual=e.solve(d['dt_s'],d['gravity_m_s2'],maximum_iterations=24)
    assert updates<=24 and residual<=d['equation_tolerance'] and int(out['faults'])==0
    exact(bodies,e.bodies);exact(edges,e.edges)
    return dict(updates=updates,equation_residual=residual,original_tolerance=d['equation_tolerance'],canonical_nonmutation=True)
def main(args):
    boundary=rounded_surface_boundary()
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
        # Initial-geometry flags are only reused inside the SAME Jacobian;
        # an accepted edit must recompute them before the next ordinary trial.
        initial=p.eval.bodies.copy();p.eval.bodies[1,7]+=.1;r.eval.bodies[1,7]+=.1
        po=p.eval.evaluate(v,1/960);ro=r.eval.evaluate(v,1/960)
        for key in PUBLIC:exact(po[key],ro[key])
        cp.copyto(p.eval.bodies,initial);cp.copyto(r.eval.bodies,initial)
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
    ledger_cases=active_ledger_parity(p.eval)
    # The diagnostic candidate is an actual private solve, not an estimate of
    # what should have happened. Observation must not mutate the physical input.
    # The reference's numerical derivative solves this gravity root in two
    # updates. The last permitted update must be admitted when its residual
    # passes the original tolerance, without an extra iteration or mutation.
    linear=GpuCoupledWorld(dict(experiment='freefall',height_m=.1,dt_s=1/240))
    original=linear.eval.bodies.copy()
    reference_out,reference_velocity,_,_=linear.eval.solve(1/240)
    out,velocity,updates,equation=linear.eval.solve(1/240,maximum_iterations=2)
    assert updates==2 and equation<=1e-10 and int(out['faults'])==0
    for key in PUBLIC:exact(out[key],reference_out[key])
    exact(velocity,reference_velocity)
    assert abs(float(velocity[-1,1])+9.81/240)<1e-10
    assert linear.eval.last_solve['converged_on_final_update']
    exact(original,linear.eval.bodies)
    # The nonlinear sheet still refuses an insufficient update budget; its
    # actual final candidate remains available for failure diagnosis.
    w=GpuCoupledWorld(dict(height_m=.001,dt_s=1/240))
    before=w.eval.bodies.copy();edges=w.eval.edges.copy()
    try:w.eval.solve(1/240,maximum_iterations=1);raise AssertionError('Deliberate iteration limit was admitted')
    except TrialFailure as error:
        d=error.details;assert str(error)=='Coupled Newton iteration budget exceeded'
    exact(before,w.eval.bodies);exact(edges,w.eval.edges)
    assert len(d['iterations'])==1 and d['last_evaluated']['faults']==[0]
    assert len(d['initial_bodies'])==13 and len(d['initial_edges'])==48 and d['dt_s']==1/240
    assert d['last_evaluated']['velocity'][0][-1][1]<0 and d['initial_bodies'][-1][15]==0
    assert len(d['jacobian_singular_values'])==60 and np.isfinite(d['jacobian']).all()
    result=dict(schema='banjo.cupy-parallel-parity.v1',source_sha256=source_hash(),candidate_trials=trial_count,localized_jacobian_trials=jacobian_count,
        exact_candidate_parity=True,exact_physical_history_parity=True,fault_precedence_cases=faults,private_refusal_diagnostics=True,comparisons=comparisons,realtime_qualified=False)
    result['active_ledger_exact_cases']=ledger_cases
    result['initial_geometry_edit_invalidation']=True
    result['final_permitted_update_convergence']=True
    result['actual_glass_final_update_replay']=actual_final_update_replay()
    result['rounded_surface_boundary']=boundary
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);main(p.parse_args())
