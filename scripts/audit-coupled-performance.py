"""Read-only instrumented work audit of bounded pre-contact CUDA fixtures.

Initial downward speed is an explicit diagnostic input, not injected during
motion. Observation wrappers preserve the equations and verify exact accepted
state parity against an uninstrumented run. Timers overlap; do not add them.
"""
import argparse
import builtins
import copy
import hashlib
import json
import math
import time
from pathlib import Path

import cupy as cp
import numpy as np
import gpu_coupled_world as module
from gpu_coupled_world import GpuCoupledWorld,source_hash


def projection(state):
    state=copy.deepcopy(state)
    state.pop('performance')
    return state


def fixture(material,experiment,speed):
    world=GpuCoupledWorld(dict(material=material,experiment=experiment,
        height_m=10.,ball_material='iron',ball_mass_kg=.01,dt_s=1/240))
    # Defined initial condition for this separate diagnostic experiment.
    world.eval.bodies[-1,15]=-speed
    bodies=cp.asnumpy(world.eval.bodies)
    world.initial_energy=world.mechanics(bodies)[0]+world.stored_j+world.contact_j
    world.accepted=world._snapshot(bodies)
    world.eval.solve(1/960)  # warm private trial, no committed state update
    cp.cuda.get_current_stream().synchronize()
    return world


def measure(material,experiment,speed):
    reference=fixture(material,experiment,speed)
    t=time.perf_counter();expected=reference.advance(1)
    baseline_wall=time.perf_counter()-t
    world=fixture(material,experiment,speed);e=world.eval
    calls=[];linear=[];scalar=[];transfers=[];events=[]
    evaluate=e.evaluate;solve=e.solve;asnumpy=cp.asnumpy;linalg=cp.linalg.solve
    start_evaluations=e.evaluations
    def observed_evaluate(*a,**kw):
        start=cp.cuda.Event();end=cp.cuda.Event();start.record();t=time.perf_counter()
        out=evaluate(*a,**kw);end.record();calls.append((time.perf_counter()-t,len(out['faults'])))
        events.append((start,end));return out
    def observed_linear(*a,**kw):
        t=time.perf_counter();out=linalg(*a,**kw);linear.append(time.perf_counter()-t);return out
    def observed_transfer(value,*a,**kw):
        t=time.perf_counter();out=asnumpy(value,*a,**kw)
        transfers.append((time.perf_counter()-t,int(out.nbytes)));return out
    def convert(kind,value):
        t=time.perf_counter();out=kind(value)
        if isinstance(value,cp.ndarray):scalar.append((kind.__name__,time.perf_counter()-t))
        return out
    def observed_solve(*a,**kw):
        for kind in (builtins.float,builtins.int,builtins.bool):
            setattr(module,kind.__name__,lambda value,kind=kind:convert(kind,value))
        try:return solve(*a,**kw)
        finally:
            for name in ('float','int','bool'):delattr(module,name)
    e.evaluate=observed_evaluate;e.solve=observed_solve
    cp.asnumpy=observed_transfer;cp.linalg.solve=observed_linear
    t=time.perf_counter()
    try:state=world.advance(1)
    finally:
        cp.asnumpy=asnumpy;cp.linalg.solve=linalg;e.evaluate=evaluate;e.solve=solve
    cp.cuda.get_current_stream().synchronize();wall=time.perf_counter()-t
    assert projection(state)==projection(expected),'instrumentation altered accepted physics'
    accounts=state['substep_accounts'];peak={}
    for key in ('energy_residual_j','P_residual_n_s','L_residual_n_m_s'):
        peak[key]=max(math.hypot(*a[key]) if isinstance(a[key],list) else abs(a[key]) for a in accounts)
    # Diagnostic counters, not a timing claim about a rewritten scheduler.
    ball=np.array(state['cells'][-1]['position_m']);before_y=10.+(.035 if experiment=='sheet' else 0)+state['cells'][-1]['radius_m']
    expected_y=before_y-speed/240-.5*9.81*(1/240)**2
    return dict(material=material,experiment=experiment,initial_downward_speed_m_s=speed,
        physical_s=state['time_s'],baseline_wall_s=baseline_wall,instrumented_wall_s=wall,
        exact_physical_parity=True,body_count=e.n,dynamic_dof=len(e.dynamic),interfaces=e.m,
        all_pairs=e.pair_count,allocated_contribution_rows=e.rows,
        accepted_microsteps=len(accounts),microstep_dt_range_s=[min(a['dt_s'] for a in accounts),max(a['dt_s'] for a in accounts)],
        nonlinear_iterations=sum(a['iterations'] for a in accounts),
        evaluate_calls=len(calls),trial_candidates=e.evaluations-start_evaluations,
        evaluate_enqueue_s=sum(x[0] for x in calls),evaluate_cuda_event_s=sum(cp.cuda.get_elapsed_time(a,b)/1000 for a,b in events),
        linear_calls=len(linear),linear_host_s=sum(linear),scalar_observations=len(scalar),scalar_wait_s=sum(x[1] for x in scalar),
        array_observations=len(transfers),array_transfer_s=sum(x[0] for x in transfers),array_transfer_bytes=sum(x[1] for x in transfers),
        ball_gravity_oracle_position_error_m=abs(ball[1]-expected_y),peak_accepted_substep_residuals=peak,
        serialized_reply_bytes=len(json.dumps(dict(ok=True,state=state),separators=(',',':')).encode()))


def main(args):
    rows=[]
    for material,experiment,speed in [('glass','freefall',14.),
            *[(m,'sheet',v) for m in ('glass','oak','iron') for v in (0.,14.)]]:
        row=measure(material,experiment,speed);rows.append(row)
        print(material,experiment,speed,'m/s:',round(row['baseline_wall_s'],4),'s;',row['accepted_microsteps'],'microsteps;',row['trial_candidates'],'candidates',flush=True)
    report=dict(schema='banjo.coupled-performance-audit.v1',source_sha256=source_hash(),
        instrumentation_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        device=cp.cuda.runtime.getDeviceProperties(0)['name'].decode(),cupy=cp.__version__,numpy=np.__version__,
        rows=rows,scope='One warmed host tick per separate fixture, original physical laws/gates. Initial 14 m/s downward speed is declared for distant-ball diagnostic cases. No contact/fracture or realtime qualification. Timings are single samples with observation overhead; wait/device intervals overlap. Exact instrumented/reference accepted physical parity is checked for every row.')
    args.report.parent.mkdir(parents=True,exist_ok=True);args.report.write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',type=Path,required=True);main(p.parse_args())
