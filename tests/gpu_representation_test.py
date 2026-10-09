"""GPU isolated flight, conservative activation and material-history ownership.

Same conditions for glass/oak/iron; ice retained. These gates qualify the
initial adapter, not detailed sphere fracture or full impact trajectories.
"""
import argparse
import copy
import json
from pathlib import Path
import sys
import time
import cupy as cp
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import gpu_coupled_world as coupled
from gpu_coupled_world import GpuCoupledWorld,TrialFailure,source_hash,declaration

def configure_velocity(w,speed):
    w.eval.bodies[-1,15]=-speed
    w.initial_energy=w.mechanics(cp.asnumpy(w.eval.bodies))[0]+w.stored_j+w.contact_j
    w.accepted=w._snapshot(cp.asnumpy(w.eval.bodies))

def main(output):
    comparisons=[]
    for material in ('glass','oak','iron','ice'):
        d=dict(material=material,height_m=10,dt_s=1/240)
        reference=GpuCoupledWorld(d);w=GpuCoupledWorld(d|dict(representation_policy='partitioned-flight'))
        # High-speed distant flight previously forces 32 global microsteps.
        for world in (reference,w):configure_velocity(world,14)
        start=cp.asnumpy(w.eval.bodies).copy();histories=cp.asnumpy(w.eval.edges[:,35:67]).copy()
        reference.advance(1);state=w.advance(1);t=state['time_s'];b=state['cells'][-1]
        assert state['representations']['mechanical_mode']=='rigid-free-flight'
        assert abs(b['position_m'][1]-(start[-1,8]-14*t-.5*9.81*t*t))<1e-12
        assert abs(b['velocity_m_s'][1]-(-14-9.81*t))<1e-12
        # Sheet remains live: its cells sag under the SAME gravity and supports.
        end=cp.asnumpy(w.eval.bodies)
        assert np.max(abs(end[3:-1,8]-start[3:-1,8]))>0
        assert all(a['representation']['island_travel_bound_m']==.002 for a in state['substep_accounts'])
        assert state['performance']['microsteps']<reference.snapshot()['performance']['microsteps']
        assert abs(state['diagnostics']['global_energy_residual_j'])<5e-9
        for a in state['substep_accounts']:
            assert abs(a['energy_residual_j'])<=a['energy_tolerance_j']
            assert np.linalg.norm(a['P_residual_n_s'])<=1e-9 and np.linalg.norm(a['L_residual_n_m_s'])<=1e-9
        assert len(state['history_arrays'])==len(histories)
        comparison=dict(material=material,conditions=state['declaration'],reference_performance=reference.snapshot()['performance'],
            partitioned_performance=state['performance'],diagnostics=state['diagnostics'],
            sheet_common_time_max_position_difference_m=float(np.max(abs(end[3:-1,7:10]-cp.asnumpy(reference.eval.bodies)[3:-1,7:10]))),
            transitions=state['representations']['transitions'])
        comparisons.append(comparison)
        print(material,'high-speed flight',comparison['reference_performance']['microsteps'],'->',state['performance']['microsteps'],flush=True)
        # Real supported low-energy impact: conservative bounding spheres may
        # activate early, but must never skip contact or alter the reference path.
        d=dict(material=material,height_m=.001,dt_s=1/240)
        a=GpuCoupledWorld(d);b=GpuCoupledWorld(d|dict(representation_policy='partitioned-flight'))
        for _ in range(5):
            sa=a.advance(1);sb=b.advance(1)
            assert np.array_equal(cp.asnumpy(a.eval.bodies),cp.asnumpy(b.eval.bodies)),material
            assert np.array_equal(cp.asnumpy(a.eval.edges),cp.asnumpy(b.eval.edges)),material
        assert sb['representations']['mechanical_mode']=='rigid-coupled-contact'
        assert sb['diagnostics']==sa['diagnostics']
    # GPU-only gravity control, including spin, all densities and rotated plane.
    for material in ('glass','oak','iron','ice'):
        w=GpuCoupledWorld(dict(experiment='freefall',ball_material=material,height_m=10,dt_s=1/240,representation_policy='partitioned-flight'))
        w.eval.bodies[-1,14:20]=cp.asarray([.2,-14,.1,.3,.2,-.4]);start=cp.asnumpy(w.eval.bodies)
        w.initial_energy=w.mechanics(start)[0];w.accepted=w._snapshot(start)
        assert w.snapshot()['render_schedule']['safe_rigid_flight_steps']==16
        s=w.advance(32);t=s['time_s'];end=cp.asnumpy(w.eval.bodies)
        assert s['performance']['nonlinear_iterations']==0 and s['performance']['microsteps']==32
        assert np.linalg.norm(end[-1,7:10]-(start[-1,7:10]+start[-1,14:17]*t+np.array([0,-.5*9.81*t*t,0])))<1e-12
        assert np.array_equal(end[-1,17:20],start[-1,17:20])
        assert abs(s['diagnostics']['global_energy_residual_j'])<5e-12
    w=GpuCoupledWorld(dict(experiment='freefall',height_m=10,representation_policy='partitioned-flight'))
    angle=np.pi/2;w.eval.bodies[0,10:14]=cp.asarray([np.cos(angle/2),0,0,np.sin(angle/2)])
    # Rotated plane crosses the ball at x=0: cannot call it isolated flight.
    assert w.representations.propose(1/240,.002) is None
    assert w.representations.safe_rigid_batch(1/240)==1
    near=GpuCoupledWorld(dict(experiment='freefall',height_m=.001,representation_policy='partitioned-flight'))
    assert near.snapshot()['render_schedule']['safe_rigid_flight_steps']==1
    # An intermediate collision must be detected even with clear endpoints.
    w=GpuCoupledWorld(dict(height_m=10,dt_s=1/240,representation_policy='partitioned-flight'))
    w.eval.bodies[-1,8]=w.eval.bodies[-1,21]=.2;w.eval.bodies[-1,15]=-100
    w.eval.bodies[0,8]=w.eval.bodies[0,21]=-10 # isolate the finite sheet as the intervening obstacle
    assert w.representations.propose(1/240,.002) is None
    # Proposals cannot mutate canonical state or histories, including refusals.
    w=GpuCoupledWorld(dict(material='oak',height_m=10,representation_policy='partitioned-flight',dt_s=1/240))
    bodies=w.eval.bodies.copy();edges=w.eval.edges.copy();initial=copy.deepcopy(w.snapshot())
    w.representations.propose(1/240,.002)
    assert bool(cp.array_equal(w.eval.bodies,bodies)) and bool(cp.array_equal(w.eval.edges,edges))
    solve=w.representations.island.solve;calls=0
    def fail(*args,**kwargs):
        nonlocal calls
        calls+=1
        if calls>1:raise TrialFailure('Deliberate island failure')
        return solve(*args,**kwargs)
    w.representations.island.solve=fail
    try:w.advance(2);raise AssertionError('Island failure admitted')
    except RuntimeError:pass
    assert bool(cp.array_equal(w.eval.bodies,bodies)) and bool(cp.array_equal(w.eval.edges,edges))
    rejected=w.snapshot();f=rejected.pop('rejected_candidate')
    assert rejected==initial and f['interval_rolled_back'] and f['failed_interval_substeps']>0
    assert w.representations.transitions==[] and w.time==0
    # Failure after all physical work and mode changes, while publishing the
    # accepted snapshot, must restore host time and mode history too.
    w=GpuCoupledWorld(dict(experiment='freefall',height_m=10,representation_policy='partitioned-flight'))
    initial=w.snapshot();bodies=w.eval.bodies.copy();edges=w.eval.edges.copy()
    def fail_snapshot(*args):raise RuntimeError('Deliberate publication failure')
    w._snapshot=fail_snapshot
    try:w.advance(1);raise AssertionError('Snapshot failure admitted')
    except RuntimeError:pass
    after=w.snapshot();after.pop('rejected_candidate')
    assert after==initial and w.time==0 and w.ticks==0 and w.microsteps==0 and w.step_s==0 and w.representations.transitions==[]
    assert bool(cp.array_equal(w.eval.bodies,bodies)) and bool(cp.array_equal(w.eval.edges,edges))
    try:declaration(dict(representation_policy='pretend-fire'));raise AssertionError('Unknown representation admitted')
    except ValueError:pass
    original_hash=coupled._disk_source_hash
    try:
        coupled._disk_source_hash=lambda:'changed'
        assert source_hash()==coupled.LOADED_SOURCE_SHA256
        try:GpuCoupledWorld({});raise AssertionError('Mixed-version scene admitted')
        except RuntimeError as error:assert 'restart the GPU worker' in str(error)
    finally:coupled._disk_source_hash=original_hash
    result=dict(schema='banjo.gpu-representation-evidence.v1',source_sha256=source_hash(),comparisons=comparisons,
        control_materials=['glass','oak','iron','ice'],swept_interior_and_rotated_plane=True,canonical_proposal_and_interval_rollback=True,
        low_energy_reference_impact_exact=True,complete_10m_impact_qualified=False,realtime_qualified=False)
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
    print('PASS isolated GPU flight, four-material live island/contact, sweep and whole-interval ownership rollback',flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);main(p.parse_args().output)
