"""Independent normal-contact clock oracle and bounded scheduling regression.

Single normal collisions can pass these checks without qualifying an assembly,
its material modes, CCD, fracture, plasticity or realtime.
"""
import argparse,copy,json,math,subprocess,sys,time
from pathlib import Path
import cupy as cp
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from gpu_coupled_world import CoupledEvaluator,GpuCoupledWorld,TrialFailure,source_hash

def oracle_state(t,height,omega):
    g=9.81;speed=math.sqrt(2*g*height);entry=speed/g
    contact=(math.pi+2*math.atan(g/(speed*omega)))/omega
    if t<=entry:return height-.5*g*t*t,-g*t
    tau=t-entry
    if tau<=contact:
        return g/omega**2*(math.cos(omega*tau)-1)-speed/omega*math.sin(omega*tau),-g/omega*math.sin(omega*tau)-speed*math.cos(omega*tau)
    tau-=contact
    assert tau<2*entry,'Oracle interval extends to another collision'
    return speed*tau-.5*g*tau*tau,speed-g*tau

def isolated(p):
    mass=.1;radius=(3*mass/(4*math.pi*p['density_kg_m3']))**(1/3)
    k=2/(1/p['young_pa']+1/211e9)*min(.01,2*radius);omega=math.sqrt(k/mass);rows=[]
    for phase in (4.,.25,.0625):
        b=np.zeros((2,30));b[:,3]=[211e9,p['young_pa']];b[:,10]=b[:,26]=1;b[:,4:7]=.01
        b[1,:3]=[2,mass,.4*mass*radius**2];b[1,4:7]=radius;b[1,8]=b[1,21]=radius;b[1,15]=-.3
        solver=CoupledEvaluator(b,np.zeros((0,70)));h=phase/omega;count=round(4/phase);max_energy=0.;trace=[]
        for tick in range(count):
            out,v,it,norm=solver.solve(h,gravity=0);before=cp.asnumpy(solver.bodies)
            solver.bodies[:,23:26]+=h*(solver.bodies[:,14:17]+v[:,:3])/2
            solver.bodies[:,7:14]=out['poses'];solver.bodies[:,14:20]=v
            bodies=cp.asnumpy(solver.bodies);ledger=cp.asnumpy(out['ledger']);force=cp.asnumpy(out['forces'])
            energy=.5*mass*bodies[1,15]**2+ledger[5]
            max_energy=max(max_energy,abs(energy-.5*mass*.3**2))
            assert abs(mass*(bodies[1,15]-before[1,15])+h*force[0,1])<1e-9
            trace.append([h*(tick+1),bodies[1,8]-radius,bodies[1,15]])
        gap=float(bodies[1,8]-radius);exact_gap=.3*(4-math.pi)/omega
        error=abs(gap-exact_gap)
        assert max_energy<1e-9
        if phase==4:assert error>exact_gap and bodies[1,15]<.2,'Coarse energy closure must not be called accurate motion'
        else:assert error<exact_gap*(.02 if phase==.25 else .0013) and abs(bodies[1,15]-.3)<1e-7
        rows.append(dict(h_omega=phase,dt_s=h,expected_gap_m=exact_gap,gap_m=gap,position_error_m=error,vy_m_s=float(bodies[1,15]),maximum_energy_residual_j=max_energy,trace=trace))
    assert rows[2]['position_error_m']<rows[1]['position_error_m']/10
    return dict(material=p['material'],density_kg_m3=p['density_kg_m3'],young_pa=p['young_pa'],ball_mass_kg=mass,ball_radius_m=radius,normal_stiffness_n_m=k,frequency_rad_s=omega,runs=rows)

def main(args):
    profiles=json.loads((ROOT/'client/voxel-lab/material-laws.json').read_text(encoding='utf8'))['profiles']
    process=subprocess.Popen([str(args.oracle)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
    result=dict(schema='banjo.gpu-contact-timing.v1',source_sha256=source_hash(),isolated=[],freefall=[],assemblies=[],schedule_cpu_cuda_cases=0,full_material_trajectory_qualified=False,realtime_qualified=False)
    try:
        for p in profiles:
            exact=isolated(p);result['isolated'].append(exact);runs=[]
            for height in (.001,.02):
                duration=1/24 if height==.001 else .1
                for hz in (240,960):
                    for mode in ('reference','phase-0.25','phase-0.125'):
                        w=GpuCoupledWorld(dict(experiment='freefall',ball_material=p['material'],ball_mass_kg=.1,height_m=height,dt_s=1/hz,contact_resolution=mode))
                        started=time.perf_counter();max_P=max_L=max_x=max_v=0.;frames=[]
                        for tick in range(round(hz*duration)):
                            # Compare the independent compiled CPU policy with all
                            # resident GPU pair estimates, before accepted stepping.
                            b=cp.asnumpy(w.eval.bodies);v=b[:,14:20].copy();v[b[:,1]>0,1]-=9.81/hz
                            command=dict(op='contact_schedule',bodies=b.tolist(),edges=[],velocity=v.tolist(),dt_s=1/hz,gravity=[0,-9.81,0],phase=.25,velocity_tolerance_m_s=1e-4)
                            process.stdin.write(json.dumps(command)+'\n');process.stdin.flush();reply=json.loads(process.stdout.readline());assert reply['ok'],reply
                            planned=w.eval.contact_schedule(1/hz,.25)
                            cpu=reply['trial']['schedules'][0]
                            assert planned['pair']==cpu['pair']
                            assert all(abs(planned[k]-cpu[k])<=2e-12*max(1,abs(cpu[k])) for k in ('step_s','frequency_rad_s','excitation_m_s'))
                            result['schedule_cpu_cuda_cases']+=1
                            s=w.advance(1);ball=s['cells'][-1];gap=ball['position_m'][1]-exact['ball_radius_m']
                            x,v=oracle_state(s['time_s'],height,exact['frequency_rad_s'])
                            max_x=max(max_x,abs(gap-x));max_v=max(max_v,abs(ball['velocity_m_s'][1]-v))
                            for a in s['substep_accounts']:
                                assert abs(a['energy_residual_j'])<=a['energy_tolerance_j']
                                max_P=max(max_P,np.linalg.norm(a['P_residual_n_s']));max_L=max(max_L,np.linalg.norm(a['L_residual_n_m_s']))
                                assert a['newton_start']['iteration_evaluations']<=24
                                if mode!='reference':assert a['contact_schedule']['step_s']==a['dt_s']
                            if (tick+1)%(hz//240)==0:frames.append(dict(time_s=s['time_s'],gap_m=gap,vy_m_s=ball['velocity_m_s'][1],expected_gap_m=x,expected_vy_m_s=v))
                        assert abs(s['time_s']-duration)<1e-14 and max_P<1e-9 and max_L<1e-9
                        assert abs(s['diagnostics']['global_energy_residual_j'])<1e-9
                        if mode!='reference':assert max_x<(1e-7 if height==.001 else 5e-7) and max_v<8e-6,(p['material'],hz,mode,max_x,max_v)
                        run=dict(conditions=s['declaration'],wall_s=time.perf_counter()-started,maximum_position_error_m=max_x,maximum_velocity_error_m_s=max_v,max_P_residual_n_s=float(max_P),max_L_residual_n_m_s=float(max_L),frames=frames,performance=s['performance'],diagnostics=s['diagnostics']);runs.append(run)
                        print(p['material'],hz,mode,'position / velocity error',max_x,max_v,flush=True)
                for hz in (240,960):
                    reference,coarse,fine=[r for r in runs if r['conditions']['dt_s']==1/hz and r['conditions']['height_m']==height]
                    assert coarse['maximum_position_error_m']<reference['maximum_position_error_m']/1000
                    assert fine['maximum_position_error_m']<coarse['maximum_position_error_m']/2
                    assert fine['maximum_velocity_error_m_s']<coarse['maximum_velocity_error_m_s']/2
            result['freefall'].append(dict(material=p['material'],runs=runs))
        # Real connected-scene attempts are NOT an admission gate that passes
        # when nothing happens. Record completion or the actual bounded refusal
        # separately, and require both host and resident whole-interval rollback.
        for material in ('glass','oak','iron','ice'):
            w=GpuCoupledWorld(dict(material=material,ball_mass_kg=.1,height_m=.005,dt_s=1/960,contact_resolution='phase-0.25'));started=time.perf_counter();refusal=None
            for tick in range(100):
                previous=w.snapshot();saved_b=w.eval.bodies.copy();saved_e=w.eval.edges.copy()
                try:s=w.advance(1)
                except RuntimeError:
                    retained=w.snapshot();refusal=retained.pop('rejected_candidate')
                    assert retained==previous and refusal['interval_rolled_back']
                    assert bool(cp.array_equal(w.eval.bodies,saved_b)) and bool(cp.array_equal(w.eval.edges,saved_e))
                    assert refusal['error']=='Coupled interval trial/time budget' and refusal['trial_attempts']==129
                    assert refusal['contact_timestep_policy']=='phase-0.25' and refusal['last_contact_schedule']['step_s']>0
                    break
                for a in s['substep_accounts']:
                    assert abs(a['energy_residual_j'])<=a['energy_tolerance_j']
                    assert np.linalg.norm(a['P_residual_n_s'])<=1e-9 and np.linalg.norm(a['L_residual_n_m_s'])<=1e-9
            row=dict(conditions=w.d,completed=refusal is None,time_s=w.time,wall_s=time.perf_counter()-started,refusal=refusal)
            result['assemblies'].append(row);print(material,'assembly',row['completed'],'accepted time',w.time,flush=True)
        # Refinement never publishes a partial interval after solver failure.
        w=GpuCoupledWorld(dict(experiment='freefall',height_m=.001,contact_resolution='phase-0.25'));initial=w.snapshot();b=w.eval.bodies.copy();e=w.eval.edges.copy();solve=w.eval.solve;calls=0
        def refuse_after_first(*a,**kw):
            nonlocal calls
            calls+=1
            if calls>1:raise TrialFailure('Deliberate refined interval refusal')
            return solve(*a,**kw)
        w.eval.solve=refuse_after_first
        try:w.advance(2);raise AssertionError('Failed interval admitted')
        except RuntimeError:pass
        failed=w.snapshot();witness=failed.pop('rejected_candidate');assert failed==initial and witness['interval_rolled_back'] and witness['failed_interval_substeps']==1
        assert bool(cp.array_equal(w.eval.bodies,b)) and bool(cp.array_equal(w.eval.edges,e))
        result['refined_whole_interval_rollback']=True
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
        print('Analytical contact timing and bounded policy controls passed; assemblies/realtime remain open',flush=True)
    finally:process.stdin.close();process.wait(timeout=10)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--oracle',type=Path,required=True);p.add_argument('--output',type=Path,required=True);main(p.parse_args())
