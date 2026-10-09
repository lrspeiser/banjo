"""Actual native CUDA LU, replayed commands, refusal and material histories."""
import argparse,copy,hashlib,json,sys,time
from pathlib import Path
import cupy as cp
import cupyx
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from gpu_linear_solve import ResidentLinearSolve
from gpu_coupled_world import CoupledEvaluator,GpuCoupledWorld,TrialFailure,source_hash
from gpu_coupled_pipeline_test import exact,physical

def reference(a,b):
    with cupyx.errstate(linalg='raise'):return cp.linalg.solve(a,b)

def matrices():
    rng=np.random.default_rng(4389);cases=0;maximum=0.
    for n in (1,2,3,6,12,31,60,96,127,192):
        solver=ResidentLinearSolve(n)
        for kind in ('dense','symmetric','scaled'):
            a=rng.normal(size=(n,n))
            a=a+n*np.eye(n) if kind=='dense' else a.T@a+np.eye(n) if kind=='symmetric' else np.diag(np.geomspace(1.,1e-12,n))
            x=rng.normal(size=n);b=a@x
            for layout in ('C','F','strided'):
                if layout=='strided':
                    ga=cp.zeros((2*n,2*n));gb=cp.zeros(2*n);ga[::2,::2]=cp.asarray(a);gb[::2]=cp.asarray(b);ga=ga[::2,::2];gb=gb[::2]
                else:ga=cp.array(a,order=layout);gb=cp.asarray(b)
                old_a=ga.copy();old_b=gb.copy();actual,status=solver.enqueue(ga,gb)
                assert np.array_equal(cp.asnumpy(status),[0,0,0]);exact(actual,reference(ga,gb));exact(ga,old_a);exact(gb,old_b)
                value=cp.asnumpy(actual);residual=np.linalg.norm(a@value-b,np.inf)/(np.linalg.norm(a,np.inf)*np.linalg.norm(value,np.inf)+np.linalg.norm(b,np.inf))
                assert residual<=64*n*np.finfo(float).eps;maximum=max(maximum,float(residual));cases+=1
        # Failure status cannot be silently accepted as a zero direction.
        singular=cp.eye(n);singular[-1,-1]=0;b=cp.ones(n);old=singular.copy();_,status=solver.enqueue(singular,b)
        assert int(status[0])==2 and int(status[1])==n;exact(singular,old)
        for target in ('matrix','rhs'):
            a=cp.eye(n);b=cp.ones(n)
            if target=='matrix':a[0,0]=cp.nan
            else:b[0]=cp.inf
            _,status=solver.enqueue(a,b);assert int(status[0])==1
        _,status=solver.enqueue(cp.eye(n),cp.ones(n));assert int(status[0])==0
        for bad in (cp.ones((n,n),dtype=cp.float32),cp.ones((n,n+1)),solver.factor):
            try:solver.enqueue(bad,cp.ones(n));raise AssertionError('Invalid linear input admitted')
            except ValueError:pass
    # Finite input that overflows its factor must refuse, not return a plausible
    # finite zero answer from an infinite diagonal. Original input is retained.
    e=ResidentLinearSolve(2);a=cp.asarray([[1e308,1e308],[-1e308,1e308]]);old=a.copy();_,s=e.enqueue(a,cp.ones(2));assert int(s[0])==3;exact(a,old)
    return dict(cases=cases,exact_cupy_results=True,max_relative_backward_error=maximum,input_factor_solution_faults_checked=True)

def captures():
    results=[];rng=np.random.default_rng(8991)
    for n in (6,60,192):
        stream=cp.cuda.Stream(non_blocking=True)
        with stream:
            e=ResidentLinearSolve(n);a=cp.eye(n);b=cp.ones(n);e.enqueue(a,b);stream.synchronize()
            stream.begin_capture();out,status=e.enqueue(a,b);graph=stream.end_capture()
            for index in range(4):
                # Replayed COMMANDS process different physical/numerical input.
                # No result or trajectory cache is used.
                new=rng.normal(size=(n,n))+n*np.eye(n);rhs=rng.normal(size=n)
                a[:]=cp.asarray(new);b[:]=cp.asarray(rhs);graph.launch();stream.synchronize()
                assert int(status[0])==0;exact(out,reference(a,b))
            a[:]=cp.eye(n);a[-1,-1]=0;graph.launch();stream.synchronize();assert int(status[0])==2
            a[:]=cp.eye(n);graph.launch();stream.synchronize();assert int(status[0])==0;exact(out,b)
            # Same native instance/arrays may not race across another stream.
            library=e.native
        try:e.enqueue(a,b);raise AssertionError('A different stream was admitted')
        except ValueError:pass
        results.append(dict(size=n,changed_input_replays=4,singular_and_recovery=True,native_library_version=library.version,native_library_sha256=hashlib.sha256(library.path.read_bytes()).hexdigest()))
    return results

def refusal():
    d=json.loads((ROOT/'docs/evidence/gpu-newton-diagnostics/glass-refusal.json').read_text())['refusal']['last_solver_failure'];rows=[]
    for backend in ('cupy-reference','native-cusolver'):
        e=CoupledEvaluator(np.array(d['initial_bodies']),np.array(d['initial_edges']),newton_strategy='single-reference',linear_backend=backend)
        try:e.solve(d['dt_s']);raise AssertionError('Recorded refusal was admitted')
        except TrialFailure as failure:
            assert str(failure)=='Coupled Newton line search did not reduce the equation residual';r=copy.deepcopy(failure.details)
        r.pop('linear_backend')
        for row in r['iterations']:
            status=row.pop('linear_status',None)
            if status:assert status==dict(reason=0,factor_info=0,solve_info=0)
        rows.append(r)
    assert rows[0]==rows[1]
    return True

def worlds():
    rows=[]
    for material in ('glass','oak','iron','ice'):
        for strong in (False,True):
            d=dict(material=material,height_m=.005 if strong else .001,ball_mass_kg=.1 if strong else .01,dt_s=1/960 if strong else 1/240)
            w=[GpuCoupledWorld(d|dict(linear_backend=b)) for b in ('cupy-reference','native-cusolver')];wall=[0.,0.];max_E=max_P=max_L=0.
            for solver in w:solver.eval.solve(d['dt_s']/4)
            for tick in range(100 if strong else 10):
                states=[None,None]
                for i in ([0,1] if tick%2==0 else [1,0]):
                    t=time.perf_counter();states[i]=w[i].advance(1);wall[i]+=time.perf_counter()-t
                assert physical(states[0])==physical(states[1]),(material,strong,tick);exact(w[0].eval.bodies,w[1].eval.bodies);exact(w[0].eval.edges,w[1].eval.edges)
                for account in states[1]['substep_accounts']:
                    assert abs(account['energy_residual_j'])<=account['energy_tolerance_j']
                    max_E=max(max_E,abs(account['energy_residual_j']));max_P=max(max_P,float(np.linalg.norm(account['P_residual_n_s'])));max_L=max(max_L,float(np.linalg.norm(account['L_residual_n_m_s'])))
                    assert max_P<=1e-9 and max_L<=1e-9
            rows.append(dict(conditions=d,physical_time_s=states[1]['time_s'],wall_s=dict(zip(('cupy-reference','native-cusolver'),wall)),exact_physical_history=True,max_E_residual_j=max_E,max_P_residual_n_s=max_P,max_L_residual_n_m_s=max_L,diagnostics=states[1]['diagnostics']))
            print(material,'strong' if strong else 'low','entire CUDA history identical',wall,flush=True)
    return rows

def main(args):
    result=dict(schema='banjo.resident-linear.v1',source_sha256=source_hash(),device=cp.cuda.runtime.getDeviceProperties(0)['name'].decode(),matrix_checks=matrices(),command_graphs=captures(),recorded_refusal_exact=refusal(),worlds=worlds(),nonlinear_loop_resident=False,realtime_qualified=False,material_trajectory_qualified=False)
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2)+'\n')
    print('Native device-status LU and actual command capture passed; full nonlinear residency remains open',flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);main(p.parse_args())
