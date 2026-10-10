"""Actual four-material CPU admission, analytical dynamics and atomic rollback."""
import argparse,json,os,sys,time
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from cpu_coupled_world import CpuCoupledWorld,CpuCoupledEvaluator,implementation_hash
from coupled_solver import TrialFailure

def tiny_contact_oracle():
    profiles=json.loads((ROOT/'client/voxel-lab/material-laws.json').read_text())['profiles'];rows=[]
    for p in profiles:
        for shift in (0.,1.,100.):
            b=np.zeros((2,30));b[:,4:7]=.005;b[:,10]=b[:,26]=1
            b[:,8]=b[:,21]=shift;b[0,3]=211e9
            b[1,0]=1;b[1,1]=p['density_kg_m3']*.01**3;b[1,2]=b[1,1]*.01**2/6;b[1,3]=p['young_pa']
            b[1,8]=shift+.005;b[1,24]=.005
            e=CpuCoupledEvaluator(b,[]);v=np.zeros((2,6));v[1,1]=-2e-18
            trial=e.evaluate(v,1.,gravity=0)
            # Four bottom-face samples, each with one-quarter of E_harmonic L.
            stiffness=2/(1/p['young_pa']+1/211e9)*.01
            expected_force=stiffness*.5e-18;expected_energy=.5*stiffness*1e-36
            assert not trial['faults'][0]
            force=trial['forces'][0,1,1];energy=trial['ledger'][0,5]
            assert abs(force/expected_force-1)<1e-12,(p['material'],shift,force,expected_force)
            assert abs(energy/expected_energy-1)<1e-12,(p['material'],shift,energy,expected_energy)
            assert np.linalg.norm(trial['forces'][0,:,:3].sum(axis=0))<1e-25
            assert np.array_equal(e.bodies,b),'Private contact changed authoritative matter'
            rows.append(dict(material=p['material'],translation_m=shift,displacement_m=-1e-18,force_n=float(force),contact_energy_j=float(energy)))
    return rows

def retained_glass_root():
    archive=json.loads((ROOT/'docs/evidence/gpu-representations/backend-performance.json').read_text())
    d=archive['glass_drop']['state']['rejected_candidate']['last_solver_failure']
    e=CpuCoupledEvaluator(d['initial_bodies'],d['initial_edges']);b=e.bodies.copy();edges=e.edges.copy()
    out,v,updates,residual=e.solve(d['dt_s'],d['gravity_m_s2'],maximum_iterations=24)
    assert updates<=24 and residual<=d['equation_tolerance'] and not out['faults']
    assert np.array_equal(e.bodies,b) and np.array_equal(e.edges,edges)
    ending=b.copy();ending[:,7:14]=out['poses'];ending[:,14:20]=v
    E0,P0,L0=CpuCoupledWorld.mechanics(b);E1,P1,L1=CpuCoupledWorld.mechanics(ending)
    h=d['dt_s'];ledger=out['ledger'];f=out['forces'];fixed=b[:,1]==0;mid=(b[:,7:10]+ending[:,7:10])/2
    energy=E1-E0+ledger[1]-ledger[0]+ledger[2]+ledger[3]+ledger[5]-ledger[4]
    P=P1-P0+h*f[fixed,:3].sum(axis=0)-[0,-9.81*b[:,1].sum()*h,0]
    L=L1-L0+h*(np.cross(mid[fixed],f[fixed,:3])+f[fixed,3:]).sum(axis=0)-h*np.cross(mid,b[:,1,None]*[0,-9.81,0]).sum(axis=0)
    tolerance=1e-10+1e-8*max(abs(E0+ledger[0]+ledger[4]),1e-3)
    assert abs(energy)<=tolerance and np.linalg.norm(P)<=1e-9 and np.linalg.norm(L)<=1e-9
    return dict(updates=updates,equation_residual=residual,original_tolerance=d['equation_tolerance'],energy_residual_j=float(energy),P_residual_n_s=P.tolist(),L_residual_n_m_s=L.tolist(),canonical_nonmutation=True)

def main(args):
    os.environ['BANJO_COUPLED_CPU_LIBRARY']=str(args.library.resolve());runs=[]
    tiny=tiny_contact_oracle();root=retained_glass_root()
    for material in ('glass','oak','iron','ice'):
        w=CpuCoupledWorld(dict(material=material,height_m=.001,dt_s=1/240,representation_policy='partitioned-flight'))
        initial=w.snapshot();start=time.perf_counter();contact=False;peak_load=0.
        previous=np.array([c['velocity_m_s']+c['angular_velocity_rad_s'] for c in initial['cells']])
        for _ in range(10):
            s=w.advance(1)
            assert not s['qualification']['gpu'] and s['qualification']['device']=='cpu'
            assert abs(s['diagnostics']['global_energy_residual_j'])<5e-9
            for a in s['substep_accounts']:
                load=np.array(a['interaction_wrench_n_nm']);assert load.shape==(len(s['cells']),6) and np.isfinite(load).all()
                # Independent per-body impulse check, not just a color fixture.
                velocity=np.array(a['velocities']);mass=np.array([c['mass_kg'] for c in s['cells']]);dynamic=mass>0
                impulse=(velocity[:,:3]-previous[:,:3])*mass[:,None]
                impulse[:,1]+=9.81*mass*a['dt_s']
                assert np.max(np.linalg.norm((impulse-a['dt_s']*load[:,:3])[dynamic],axis=1))<1e-9
                assert np.linalg.norm(load[:,:3].sum(axis=0))<1e-6,'internal interactions and fixed reaction must balance'
                assert np.linalg.norm(-a['dt_s']*load[~dynamic,:3].sum(axis=0)-a['ground_impulse_n_s'])<1e-12
                peak_load=max(peak_load,float(np.max(np.linalg.norm(load[:,:3],axis=1))));previous=velocity
                assert abs(a['energy_residual_j'])<=a['energy_tolerance_j']
                assert np.linalg.norm(a['P_residual_n_s'])<1e-9 and np.linalg.norm(a['L_residual_n_m_s'])<1e-9
                contact|=a['ledger'][8]>0
        ballistic=initial['cells'][-1]['position_m'][1]-.5*9.81*w.time**2
        assert contact and s['cells'][-1]['position_m'][1]>ballistic+1e-4
        r=CpuCoupledWorld.from_checkpoint(w.export_checkpoint());assert r.export_checkpoint()==w.export_checkpoint()
        assert np.array_equal(r.eval.bodies,w.eval.bodies) and np.array_equal(r.eval.edges,w.eval.edges)
        a=w.advance(1);b=r.advance(1)
        for field in ('cells','history_arrays','diagnostics','substep_accounts'):assert a[field]==b[field],field
        assert peak_load>0,'actual contact must publish a nonzero measured load'
        runs.append(dict(material=material,conditions=w.d,physical_s=w.time,wall_s=time.perf_counter()-start,diagnostics=a['diagnostics'],peak_interaction_load_n=peak_load,resume_exact=True))
        print(material,'CPU sheet control accepted',flush=True)
        # Malformed candidates refuse without modifying authoritative matter.
        original=w.eval.bodies.copy();v=original[:,14:20].copy();v[0,0]=np.nan
        try:w.eval.evaluate(v,1/240);raise AssertionError('Nonfinite candidate admitted')
        except ValueError:pass
        assert np.array_equal(w.eval.bodies,original)
        for raw in (dict(device='cuda:0'),dict(pipeline='parallel'),dict(linear_backend='cupy-reference')):
            try:CpuCoupledWorld(raw);raise AssertionError('Silent backend fallback')
            except ValueError:pass
    w=CpuCoupledWorld({});initial=w.snapshot();b=w.eval.bodies.copy();e=w.eval.edges.copy();solve=w.eval.solve;calls=0
    def fail(*a,**kw):
        nonlocal calls
        calls+=1
        if calls>1:raise TrialFailure('Injected CPU convergence refusal')
        return solve(*a,**kw)
    w.eval.solve=fail
    try:w.advance(2);raise AssertionError('Failed interval admitted')
    except RuntimeError:pass
    refused=w.snapshot();failure=refused.pop('rejected_candidate')
    assert refused==initial and failure['interval_rolled_back'] and failure['failed_interval_substeps']==1
    assert np.array_equal(w.eval.bodies,b) and np.array_equal(w.eval.edges,e)
    report=dict(schema='banjo.cpu-coupled-evidence.v1',implementation_sha256=implementation_hash(),numpy_version=np.__version__,runs=runs,sub_ulp_contact_oracle=tiny,retained_glass_root=root,atomic_rollback=True,full_fracture_qualified=False)
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print('PASS four-material CPU contacts / resume / refusal / rollback',flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--library',type=Path,required=True);p.add_argument('--output',type=Path,required=True);main(p.parse_args())
