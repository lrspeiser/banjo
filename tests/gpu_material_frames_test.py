"""Finite-frame GPU constitutive-to-wrench bridge; not world admission."""
import argparse
import copy
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time
import cupy as cp
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from gpu_material_frames import ResidentFrames,write_physx_wrenches,source_hash
from gpu_material_laws import ResidentLaws

def quaternion(p):
    a=np.linalg.norm(p)
    return np.r_[np.cos(a/2),p*(np.sin(a/2)/a)] if a else np.array([1.,0,0,0])
def multiply(a,b):
    return np.r_[a[0]*b[0]-a[1:]@b[1:],a[0]*b[1:]+b[0]*a[1:]+np.cross(a[1:],b[1:])]
def rotate(q,v):
    t=2*np.cross(q[1:],v);return v+q[0]*t+np.cross(q[1:],t)
def pack(f):
    return dict(com=f[:3].tolist(),orientation=f[3:7].tolist(),anchor=f[7:10].tolist(),frame=f[10:14].tolist())

def main(args):
    process=subprocess.Popen([str(args.oracle)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,encoding='utf8')
    def oracle(command):
        process.stdin.write(json.dumps(command)+'\n');process.stdin.flush();out=json.loads(process.stdout.readline());assert out['ok'],out;return out
    try:
        rng=np.random.default_rng(6401);n=1024
        f=np.zeros((n,2,14));f[:,:,:3]=rng.normal(size=(n,2,3))*.1;f[:,:,7:10]=rng.normal(size=(n,2,3))*.02
        for i in range(n):
            for j in range(2):f[i,j,3:7]=quaternion(rng.normal(size=3)*.3);f[i,j,10:14]=quaternion(rng.normal(size=3)*.1)
        loads=rng.normal(size=(n,6))*np.array([1e3,2e3,3e3,4,5,6])
        gpu=ResidentFrames(n);q=cp.asnumpy(gpu.coordinates(f));w=cp.asnumpy(gpu.forces(loads))
        cpu=oracle({'op':'frames','lanes':[dict(a=pack(a),b=pack(b),loads=l.tolist()) for (a,b),l in zip(f,loads)]})['frames']
        cq=np.array([row['q'] for row in cpu]);cw=np.array([row['wrenches'] for row in cpu])
        qerr=float(np.max(abs(q-cq)));werr=float(np.max(abs(w-cw)))
        assert np.allclose(q,cq,rtol=1e-13,atol=3e-15) and np.allclose(w,cw,rtol=1e-12,atol=3e-11),(qerr,werr)
        linear=w[:,0]+w[:,2];angular_balance=np.cross(f[:,0,:3],w[:,0])+w[:,1]+np.cross(f[:,1,:3],w[:,2])+w[:,3]
        assert np.max(abs(linear))==0 and np.max(abs(angular_balance))<2e-12
        # Common rigid transform must rotate force/torque, leave q unchanged.
        common=quaternion(np.array([.4,-.7,.3]));transformed=f.copy()
        for i in range(n):
            for j in range(2):
                transformed[i,j,:3]=rotate(common,f[i,j,:3])+[2.,-.8,.4]
                transformed[i,j,3:7]=multiply(common,f[i,j,3:7])
        tq=cp.asnumpy(gpu.coordinates(transformed));tw=cp.asnumpy(gpu.forces(loads))
        expected=np.array([[rotate(common,v) for v in row] for row in w])
        assert np.allclose(tq,q,atol=3e-15,rtol=1e-13) and np.allclose(tw,expected,atol=1e-10,rtol=1e-12)
        # Virtual work / independent central difference of U(q) for finite
        # frames, offset anchors, anisotropic coefficients and fixed rest.
        gradient=ResidentFrames(1);coeff=np.array([2e5,4e5,7e5,20.,50.,90.]);rest=np.array([.01,-.02,.03,.04,-.05,.06]);eps=1e-6;max_gradient=0.
        for row in f[:24]:
            initial=row[None].copy();qi=cp.asnumpy(gradient.coordinates(initial))[0];wi=cp.asnumpy(gradient.forces((coeff*(qi-rest))[None]))[0]
            def energy(frames):
                coordinate=cp.asnumpy(gradient.coordinates(frames))[0]-rest
                return .5*np.sum(coeff*coordinate**2)
            for body in range(2):
                for axis in range(6):
                    plus=initial.copy();minus=initial.copy()
                    if axis<3:plus[0,body,axis]+=eps;minus[0,body,axis]-=eps
                    else:
                        turn=np.eye(3)[axis-3]*eps
                        plus[0,body,3:7]=multiply(quaternion(turn),initial[0,body,3:7])
                        minus[0,body,3:7]=multiply(quaternion(-turn),initial[0,body,3:7])
                    derivative=(energy(plus)-energy(minus))/(2*eps)
                    residual=abs(derivative+wi[2*body+(axis>=3),axis%3]);max_gradient=max(max_gradient,residual)
                    assert residual<2e-5*max(1.,abs(derivative)),(body,axis,residual,derivative)
        # Incorrect separate application anchors must be detected by the
        # angular/work oracle, rather than reducing this to a force-sum test.
        row=f[0];force=w[0,0];pa=row[0,:3]+rotate(row[0,3:7],row[0,7:10]);pb=row[1,:3]+rotate(row[1,3:7],row[1,7:10])
        missing=np.cross(pb-pa,force);assert np.linalg.norm(missing)>1
        for bad in [np.nan,2.]:
            invalid=f.copy();invalid[0,0,3]=bad
            try:gpu.coordinates(invalid);raise AssertionError('Invalid quaternion accepted')
            except ValueError:pass
        invalid=f.copy();invalid[0,0,3:7]=[1,0,0,0];invalid[0,0,10:14]=[1,0,0,0];invalid[0,1,3:7]=[0,1,0,0];invalid[0,1,10:14]=[1,0,0,0]
        try:gpu.coordinates(invalid);raise AssertionError('Pi branch accepted')
        except ValueError:pass
        # Actual GPU material history -> GPU loads -> GPU wrenches -> actual
        # PhysX forces/torques. This is one frozen-load delivery test, not an
        # integrated coupled material world. The rigid pair starts at 2/0 m/s.
        profiles=oracle({'op':'catalog'})['profiles'];controls=[]
        from physx_contact_world import PhysXContactWorld,wp
        for p in profiles:
            world=PhysXContactWorld(dict(experiment='pair',material=p['material'],ball_material=p['material'],dt_s=1/1920,restitution=0,friction=0))
            try:
                frame=ResidentFrames(1);law=ResidentLaws([p]);body=np.zeros((1,2,14));body[:,:,3]=1;body[:,:,10]=1
                body[0,:,:3]=world.last[:,:3];body[0,0,7:10]=[.2,.01,.02];body[0,1,7:10]=[-.2+5e-8,.01,.02]
                coordinates=frame.coordinates(body);initial_coordinates=cp.asnumpy(coordinates)[0].copy();law.update(coordinates);force=frame.material_forces(law)
                checked=np.array(oracle({'op':'advance','lanes':[dict(material=p['material'],model=p['display_model'],state=np.zeros(32).tolist(),coordinates=initial_coordinates.tolist())]})['states'])[0]
                assert np.array_equal(checked,law.host[0]),'Resident geometry-to-law route changed constitutive history'
                body_forces=cp.stack((cp.concatenate((force[0,0],force[0,1])),cp.concatenate((force[0,2],force[0,3]))))
                expected=cp.asnumpy(body_forces).astype(np.float32).astype(np.float64)
                before=world.last.copy();dt=world.d['dt_s'];started=time.perf_counter()
                for invalid_wrench in (np.zeros((2,6)),cp.full((2,6),np.nan),cp.full((2,6),1e100),cp.zeros((1,6))):
                    try:write_physx_wrenches(world,invalid_wrench);raise AssertionError('Invalid GPU/FP32 wrench accepted')
                    except ValueError:pass
                write_physx_wrenches(world,body_forces);world.sdk.step_sync(dt);world._observe(0);after=world.trace.numpy()[0].astype(np.float64)
                expected_v=before[:,7:10]+dt*expected[:,:3]/world.mass[:,None]
                expected_omega=before[:,10:13]+dt*expected[:,3:]/world.inertia[:,None]
                assert np.allclose(after[:,7:10],expected_v,rtol=3e-5,atol=2e-7),(p['material'],after,expected_v)
                assert np.allclose(after[:,10:13],expected_omega,rtol=3e-5,atol=2e-7),(p['material'],after,expected_omega)
                work=dt*np.sum(expected[:,:3]*(before[:,7:10]+after[:,7:10])/2+expected[:,3:]*(before[:,10:13]+after[:,10:13])/2)
                energy_change=world.energy(after)-world.energy(before);residual=float(energy_change-work)
                assert abs(residual)<3e-5*max(1.,abs(work)),(energy_change,work)
                p0=np.sum(world.mass[:,None]*before[:,7:10],axis=0);p1=np.sum(world.mass[:,None]*after[:,7:10],axis=0)
                def angular(s):return np.sum(np.cross(s[:,:3],world.mass[:,None]*s[:,7:10])+world.inertia[:,None]*s[:,10:13],axis=0)
                pres=float(np.linalg.norm(p1-p0));lres=float(np.linalg.norm(angular(after)-angular(before)))
                assert pres<2e-6 and lres<2e-6,(pres,lres)
                # The SDK accepting wrenches is NOT coupled material admission.
                # Independently evaluate end-frame material potential/history:
                # holding an initial stiff force for an entire rigid timestep
                # adds energy even though that force's own work ledger closes.
                ending=body.copy();ending[0,:,:3]=after[:,:3]
                ending[0,:,3:7]=np.c_[after[:,6],after[:,3:6]]
                end_q=cp.asnumpy(frame.coordinates(ending))[0]
                old=law.host[0].copy()
                candidate=np.array(oracle({'op':'advance','lanes':[dict(material=p['material'],model=p['display_model'],state=old.tolist(),coordinates=end_q.tolist())]})['states'])[0]
                plastic=p['display_model']=='connector-plastic'
                old_total=old[15]+old[12]+old[13] if plastic else old[3]+old[4]
                end_total=candidate[15]+candidate[12]+candidate[13] if plastic else candidate[3]+candidate[4]
                coupled_gain=float(energy_change+end_total-old_total)
                coupled_tolerance=1e-5*max(1.,abs(world.energy(before)+old_total))+1e-6
                assert coupled_gain>coupled_tolerance,'Unexpectedly changed the retained stiff-force coupled failure'
                assert np.array_equal(law.host[0],old),'Rejected hypothetical coupling changed accepted material history'
                world.sdk.step_sync(dt);world._observe(0);cleared=world.trace.numpy()[0].astype(np.float64)
                assert np.allclose(cleared[:,7:],after[:,7:],rtol=1e-6,atol=2e-7),'wrench not consumed/cleared'
                controls.append(dict(material=p['material'],model=p['display_model'],declared_opening_m=5e-8,actual_coordinates=initial_coordinates.tolist(),
                    material_force_n=expected[0,:3].tolist(),material_torque_n_m=expected[0,3:].tolist(),mass_kg=world.mass.tolist(),inertia_kg_m2=world.inertia.tolist(),
                    dt_s=dt,velocity_after_m_s=after[:,7:10].tolist(),omega_after_rad_s=after[:,10:13].tolist(),kinetic_change_j=energy_change,
                    frozen_load_work_j=float(work),work_residual_j=residual,P_residual_n_s=pres,L_residual_n_m_s=lres,probe_wall_ms=(time.perf_counter()-started)*1000,
                    material_history_dynamic=False,contact_count=int(world.contact_trace.numpy()[0,:,3].sum()),
                    coupled_candidate_admitted=False,coupled_end_coordinates=end_q.tolist(),coupled_energy_gain_j=coupled_gain,coupled_energy_tolerance_j=coupled_tolerance,
                    coupled_rejection='Frozen initial material force over full rigid dt creates energy; coupled implicit solve required'))
            finally:world.close()
        benchmarks=[]
        for count in (1024,4096,65536):
            resident=ResidentFrames(count);poses=cp.asarray(np.resize(f,(count,2,14)));actions=cp.asarray(np.resize(loads,(count,6)))
            times=[]
            for iteration in range(12):
                start=time.perf_counter();resident.coordinates(poses);resident.forces(actions);cp.cuda.get_current_stream().synchronize()
                if iteration>=3:times.append((time.perf_counter()-start)*1000)
            benchmarks.append(dict(interfaces=count,frame_wrench_median_ms=statistics.median(times),includes_gpu_finite_branch_checks=True,excludes_initial_upload_startup_and_full_readback=True,no_physics_time=True))
        result=dict(revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),source_sha256=source_hash(),gpu=cp.cuda.runtime.getDeviceProperties(0)['name'].decode(),
            compared_finite_frames=n,max_coordinate_error=qerr,max_wrench_error=werr,max_linear_residual=float(np.max(abs(linear))),max_angular_residual=float(np.max(abs(angular_balance))),
            max_energy_gradient_absolute_error=max_gradient,missing_frame_torque_mutation_n_m=float(np.linalg.norm(missing)),controls=controls,benchmarks=benchmarks,
            scope='Finite-frame law-to-wrench bridge and one frozen-load actual GPU SDK step; no dynamic fracture/plastic/contact world or realtime qualification',
            complete_physics_validated=False,realtime_qualified=False)
        args.report.parent.mkdir(parents=True,exist_ok=True);args.report.write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
        print('PASS: 1024 CPU/CUDA finite frames, objective energy gradients and four actual GPU material-wrench deliveries')
    finally:process.stdin.close();process.wait(timeout=10)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--oracle',type=Path,required=True);parser.add_argument('--report',type=Path,required=True);main(parser.parse_args())
