"""Ordered CUDA probe batching: exact histories, refusal evidence and timings.

This is solver scheduling parity, not material realism or realtime admission.
"""
import argparse,copy,json,statistics,sys,time
from pathlib import Path
import cupy as cp
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from gpu_coupled_world import CoupledEvaluator,GpuCoupledWorld,TrialFailure,declaration,source_hash
from gpu_coupled_pipeline_test import exact,physical

MODES=('serial-reference','batch-tail')

def audit(state):
    for a in state['substep_accounts']:
        assert abs(a['energy_residual_j'])<=a['energy_tolerance_j']
        assert np.linalg.norm(a['P_residual_n_s'])<=1e-9
        assert np.linalg.norm(a['L_residual_n_m_s'])<=1e-9
        assert a['newton_start']['iteration_evaluations']<=24

def compare_scene(d,steps):
    worlds=[GpuCoupledWorld(d|dict(line_search=m)) for m in MODES]
    # Compile/allocate private solve paths without advancing physical input.
    for w in worlds:w.eval.solve(d['dt_s']/4)
    wall=[0.,0.];maximum_P=maximum_L=maximum_E=0.;microsteps=0
    for tick in range(steps):
        states=[None,None]
        # Alternate the measured execution order; no simultaneous GPU work.
        for i in ([0,1] if tick%2==0 else [1,0]):
            t=time.perf_counter();states[i]=worlds[i].advance(1);wall[i]+=time.perf_counter()-t
            audit(states[i])
        assert physical(states[0])==physical(states[1]),(d,tick,'changed accepted physical history')
        exact(worlds[0].eval.bodies,worlds[1].eval.bodies);exact(worlds[0].eval.edges,worlds[1].eval.edges)
        for a in states[1]['substep_accounts']:
            maximum_P=max(maximum_P,float(np.linalg.norm(a['P_residual_n_s'])))
            maximum_L=max(maximum_L,float(np.linalg.norm(a['L_residual_n_m_s'])))
            maximum_E=max(maximum_E,abs(a['energy_residual_j']))
        microsteps+=len(states[1]['substep_accounts'])
    s=states[1]
    return dict(conditions=d,physical_time_s=s['time_s'],microsteps=microsteps,
        wall_s=dict(zip(MODES,wall)),speedup=wall[0]/wall[1],exact_physical_history=True,
        max_P_residual_n_s=maximum_P,max_L_residual_n_m_s=maximum_L,max_E_residual_j=maximum_E,
        diagnostics=s['diagnostics'],performance=[w.snapshot()['performance'] for w in worlds])

def refusal():
    record=json.loads((ROOT/'docs/evidence/gpu-newton-diagnostics/glass-refusal.json').read_text(encoding='utf8'))
    d=record['refusal']['last_solver_failure'];b=np.asarray(d['initial_bodies']);edges=np.asarray(d['initial_edges']);results=[]
    for mode in MODES:
        e=CoupledEvaluator(b,edges,newton_strategy='single-reference',line_search=mode)
        try:e.solve(d['dt_s']);raise AssertionError('Recorded refusal was admitted')
        except TrialFailure as error:
            assert str(error)=='Coupled Newton line search did not reduce the equation residual'
            witness=copy.deepcopy(error.details);assert witness.pop('line_search')==mode
        exact(e.bodies,cp.asarray(b));exact(e.edges,cp.asarray(edges));results.append(witness)
    assert results[0]==results[1],'Batched evaluation changed refusal inputs, considered probes or actual candidate'
    assert len(results[1]['last_evaluated']['faults'])==1
    return dict(exact_considered_probe_trace=True,exact_last_candidate=True,resident_input_unchanged=True,
        iterations=results[1]['iterations'],last_candidate_faults=results[1]['last_evaluated']['faults'])

def rollback():
    w=GpuCoupledWorld(dict(line_search='batch-tail'));before=physical(w.snapshot());b=w.eval.bodies.copy();edges=w.eval.edges.copy();solve=w.eval.solve;calls=0
    def stop(*a,**kw):
        nonlocal calls
        calls+=1
        if calls>1:raise TrialFailure('Deliberate batch-probe rollback')
        return solve(*a,**kw)
    w.eval.solve=stop
    try:w.advance(2);raise AssertionError('Failed interval admitted')
    except RuntimeError as error:assert str(error)=='Deliberate batch-probe rollback'
    s=w.snapshot();assert physical(s)==before and s['rejected_candidate']['failed_interval_substeps']==1
    exact(b,w.eval.bodies);exact(edges,w.eval.edges)
    return True

def main(args):
    for bad in ('automatic',None,8):
        try:declaration(dict(line_search=bad));raise AssertionError('Invalid probe policy admitted')
        except ValueError:pass
    result=dict(schema='banjo.gpu-line-search-parity.v1',source_sha256=source_hash(),
        device=cp.cuda.runtime.getDeviceProperties(0)['name'].decode(),cuda_driver=cp.cuda.runtime.driverGetVersion(),
        cupy=cp.__version__,numpy=np.__version__,refusal=refusal(),whole_interval_rollback=rollback(),
        low_energy=[],stronger=[],isolated_contact=[],realtime_qualified=False,material_trajectory_qualified=False)
    for material in ('glass','oak','iron','ice'):
        d=dict(material=material,height_m=.001,dt_s=1/240)
        runs=[compare_scene(d,10) for _ in range(3)]
        medians={m:statistics.median(r['wall_s'][m] for r in runs) for m in MODES}
        result['low_energy'].append(dict(material=material,runs=runs,median_wall_s=medians,
            median_speedup=medians[MODES[0]]/medians[MODES[1]]))
        print(material,'three paired histories identical; median walls',medians,flush=True)
        for hz in (960,1920):
            row=compare_scene(dict(material=material,ball_mass_kg=.1,height_m=.005,dt_s=1/hz),round(hz*100/960))
            result['stronger'].append(row);print(material,hz,'entire stronger history identical',row['wall_s'],flush=True)
        row=compare_scene(dict(experiment='freefall',ball_material=material,ball_mass_kg=.1,height_m=.02,dt_s=1/240,contact_resolution='phase-0.25'),24)
        result['isolated_contact'].append(row)
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
    print('Ordered batching parity passed; no change to acceptance tolerances or physical laws',flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);main(p.parse_args())
