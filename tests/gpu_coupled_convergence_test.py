"""Analytical stiff motion, recorded refusal replay and comparative time refinement.

Controls can pass while measured material trajectories remain unqualified.
"""
import argparse,json,sys,time
from pathlib import Path
import cupy as cp
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from gpu_coupled_world import CoupledEvaluator,GpuCoupledWorld,TrialFailure,source_hash

def oscillator():
    b=np.zeros((2,30));b[:,0]=2;b[:,1]=1;b[:,2]=1e-6;b[:,3]=1;b[:,4:7]=.001
    b[:,7]=b[:,20]=[-.5,.5];b[:,10]=b[:,26]=1;b[:,14]=[-.01,.01]
    e=np.zeros((1,70));e[0,:4]=[0,1,1,1];e[0,4]=.5;e[0,7]=-.5;e[0,10]=e[0,14]=1
    e[0,23:29]=1e8;e[0,29:35]=1e9
    h=.01;a=2e8*h*h/4;expected=(1-a)/(1+a)*.02
    rows=[]
    for strategy in ('single-reference','ranked'):
        solver=CoupledEvaluator(b,e,newton_strategy=strategy)
        out,v,it,norm=solver.solve(h,gravity=0)
        velocity=cp.asnumpy(v);assert abs(velocity[1,0]-velocity[0,0]-expected)<1e-10
        assert np.linalg.norm(velocity[:,1:])<1e-10 and np.linalg.norm(velocity.sum(axis=0))<1e-10
        ledger=cp.asnumpy(out['ledger']);energy=.5*np.sum(velocity[:,:3]**2)+ledger[1]
        assert abs(energy-.0001)<1e-12 and it<24
        assert bool(cp.array_equal(solver.bodies,cp.asarray(b))) and bool(cp.array_equal(solver.edges,cp.asarray(e)))
        rows.append(dict(strategy=strategy,expected_relative_velocity_m_s=expected,relative_velocity_m_s=float(velocity[1,0]-velocity[0,0]),energy_residual_j=energy-.0001,iterations=it,start=solver.last_solve))
    return rows

def replay():
    record=json.loads((ROOT/'docs/evidence/gpu-newton-diagnostics/glass-refusal.json').read_text(encoding='utf8'))
    d=record['refusal']['last_solver_failure'];b=np.asarray(d['initial_bodies']);e=np.asarray(d['initial_edges']);h=d['dt_s']
    old=CoupledEvaluator(b,e,newton_strategy='single-reference')
    try:old.solve(h);raise AssertionError('Recorded single-start failure no longer reproduced')
    except TrialFailure as failure:assert str(failure)=='Coupled Newton line search did not reduce the equation residual'
    solver=CoupledEvaluator(b,e,newton_strategy='ranked');out,v,it,norm=solver.solve(h)
    ending=b.copy();ending[:,7:14]=cp.asnumpy(out['poses']);ending[:,14:20]=cp.asnumpy(v)
    E0,P0,L0=GpuCoupledWorld.mechanics(b);E1,P1,L1=GpuCoupledWorld.mechanics(ending)
    ledger=cp.asnumpy(out['ledger']);force=cp.asnumpy(out['forces']);fixed=b[:,1]==0;midpoint=(b[:,7:10]+ending[:,7:10])/2
    energy=E1-E0+ledger[1]-ledger[0]+ledger[2]+ledger[3]+ledger[5]-ledger[4]
    reaction=-h*force[fixed,:3].sum(axis=0);torque=-h*(np.cross(midpoint[fixed],force[fixed,:3])+force[fixed,3:]).sum(axis=0)
    P=P1-P0-reaction-[0,-9.81*b[:,1].sum()*h,0]
    L=L1-L0-torque-h*np.cross(midpoint,b[:,1,None]*[0,-9.81,0]).sum(axis=0)
    tolerance=1e-10+1e-8*max(abs(E0+ledger[0]+ledger[4]),1e-3)
    scale=np.min(2*b[b[:,0]!=0,4:7]);travel=np.max(np.linalg.norm(ending[:,7:10]-b[:,7:10],axis=1))
    turn=h*np.max(np.linalg.norm((ending[:,17:20]+b[:,17:20])/2,axis=1))
    assert abs(energy)<=tolerance and np.linalg.norm(P)<=1e-9 and np.linalg.norm(L)<=1e-9
    assert ledger[8]<=.2*scale and travel<=.25*scale and turn<=.25 and solver.last_solve['iteration_evaluations']<=24
    assert bool(cp.array_equal(solver.bodies,cp.asarray(b))) and bool(cp.array_equal(solver.edges,cp.asarray(e)))
    return dict(single_start_refusal_reproduced=True,ranked_root_accepted=True,iterations=it,equation_residual=norm,energy_residual_j=energy,P_residual_n_s=P.tolist(),L_residual_n_m_s=L.tolist(),start=solver.last_solve)

def frame(s):
    return dict(time_s=s['time_s'],poses_wxyz=[c['position_m']+c['quaternion_wxyz'] for c in s['cells']],velocities=[c['velocity_m_s']+c['angular_velocity_rad_s'] for c in s['cells']],history=s['history_arrays'],diagnostics=s['diagnostics'])

def main(args):
    result=dict(schema='banjo.gpu-coupled-start-refinement.v1',source_sha256=source_hash(),oscillator=oscillator(),recorded_refusal=replay(),comparisons=[],realtime_qualified=False,material_trajectory_qualified=False)
    for material in ('glass','oak','iron','ice'):
        runs=[]
        for hz in (960,1920):
            w=GpuCoupledWorld(dict(material=material,ball_mass_kg=.1,height_m=.005,dt_s=1/hz));started=time.perf_counter();frames=[];max_P=max_L=0.
            for tick in range(round(hz*100/960)):
                s=w.advance(1)
                for a in s['substep_accounts']:
                    assert abs(a['energy_residual_j'])<=a['energy_tolerance_j']
                    max_P=max(max_P,np.linalg.norm(a['P_residual_n_s']));max_L=max(max_L,np.linalg.norm(a['L_residual_n_m_s']))
                    assert a['newton_start']['iteration_evaluations']<=24
                if (tick+1)%(hz//48)==0:frames.append(frame(s))
            assert abs(s['time_s']-100/960)<1e-14 and max_P<=1e-9 and max_L<=1e-9
            assert abs(s['diagnostics']['global_energy_residual_j'])<5e-9 and len(frames)==5
            run=dict(conditions=s['declaration'],wall_s=time.perf_counter()-started,frames=frames,performance=s['performance'],diagnostics=s['diagnostics'],max_P_residual_n_s=float(max_P),max_L_residual_n_m_s=float(max_L));runs.append(run)
            print(material,hz,'completed',run['wall_s'],'wall seconds','separated',s['diagnostics']['separated_sites'],flush=True)
        position=velocity=opening=0.;damage_disagreement=0
        for a,b in zip(runs[0]['frames'],runs[1]['frames']):
            assert abs(a['time_s']-b['time_s'])<1e-14
            position=max(position,float(np.max(abs(np.asarray(a['poses_wxyz'])[:,:3]-np.asarray(b['poses_wxyz'])[:,:3]))))
            velocity=max(velocity,float(np.max(abs(np.asarray(a['velocities'])[:,:3]-np.asarray(b['velocities'])[:,:3]))))
            opening=max(opening,float(np.max(abs(np.asarray(a['history'])[:,22:25]-np.asarray(b['history'])[:,22:25]))))
            if material!='iron':damage_disagreement=max(damage_disagreement,int(np.sum((np.asarray(a['history'])[:,6]>0)!=(np.asarray(b['history'])[:,6]>0))))
        result['comparisons'].append(dict(material=material,runs=runs,common_time_max_position_difference_m=position,common_time_max_linear_velocity_difference_m_s=velocity,common_time_max_interface_coordinate_difference_m=opening,common_time_max_separation_disagreements=damage_disagreement))
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
    print('Analytical/replay/admission controls passed; material trajectory refinement remains unqualified',flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);main(p.parse_args())
