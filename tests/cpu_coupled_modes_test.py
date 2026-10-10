"""Native four-material preparation, affine oracles and no physical-state mutation."""
import argparse
import json
import math
import os
import sys
from unittest.mock import patch
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from coupled_modes import ModeBasis,prepare,contact_envelope
from cpu_coupled_world import CpuCoupledWorld,CpuCoupledEvaluator,implementation_hash


def refuse(fn):
    try:fn()
    except (ValueError,RuntimeError):return
    raise AssertionError('Unsupported preparation was accepted')


def main(args):
    os.environ['BANJO_COUPLED_CPU_LIBRARY']=str(args.library.resolve())
    # A complete oscillator cycle has identical endpoints but interior contact
    # travel. An endpoint-only envelope would wrongly declare zero motion.
    oscillator=ModeBasis([1.],[[16.]],[0.],[1.])
    box=oscillator.envelope(math.pi/2)
    assert box['displacement_lower'][0]<=-.25 and box['displacement_upper'][0]>=.25
    assert abs(box['displacement_lower'][0]+.25)<1e-12 and abs(box['displacement_upper'][0]-.25)<1e-12
    assert abs(oscillator.advance(math.pi/2)['displacement'][0])<1e-15
    # Loaded equilibrium offset, zero-mode turnaround and unstable turnaround.
    loaded=ModeBasis([1.],[[16.]],[8.],[0.]).envelope(math.pi/2)
    assert loaded['displacement_lower'][0]<=0 and 1<=loaded['displacement_upper'][0]<1+1e-12
    quadratic=ModeBasis([1.],[[0.]],[-2.],[1.]).envelope(1.)
    assert quadratic['displacement_lower'][0]<=0 and .25<=quadratic['displacement_upper'][0]<.25+1e-12
    unstable_box=ModeBasis([1.],[[-4.]],[-1.],[.2]).envelope(.4)
    peak=.2*math.sinh(math.atanh(.4))/2-.25*(math.cosh(math.atanh(.4))-1)
    assert peak<=unstable_box['displacement_upper'][0]<peak+1e-12
    # Full cycles do not cost O(frequency*h). Keep actual vibration at 1MHz.
    stiff=ModeBasis([1.],[[1e12]],[0.],[1.]).envelope(2.)
    assert stiff['displacement_lower'][0]<=-1e-6 and stiff['displacement_upper'][0]>=1e-6
    # Independent RK4 integration checks correlated mixed modes, including a
    # near-zero and an unstable eigenvalue. Interval mapping must enclose them.
    stiffness=np.array([[3.,-1.,.2],[-1.,.1,0.],[.2,0.,0.]])
    masses=np.array([1.,2.,3.]);force=np.array([.2,-.4,.1]);initial_v=np.array([.3,-.1,.2])
    mixed=ModeBasis(masses,stiffness,force,initial_v);bounds=mixed.envelope(.3)
    y=np.r_[np.zeros(3),initial_v];dt=.3/2000
    def rhs(s):return np.r_[s[3:],(force-stiffness@s[:3])/masses]
    for _ in range(2000):
        a=rhs(y);b=rhs(y+dt*a/2);c=rhs(y+dt*b/2);d=rhs(y+dt*c)
        y+=dt*(a+2*b+2*c+d)/6
        assert np.all(y[:3]>=bounds['displacement_lower']-1e-13) and np.all(y[:3]<=bounds['displacement_upper']+1e-13)
        assert np.all(y[3:]>=bounds['velocity_lower']-1e-13) and np.all(y[3:]<=bounds['velocity_upper']+1e-13)
    refuse(lambda:mixed.envelope(float('nan')))
    refuse(lambda:ModeBasis([1.],[[-1e4]],[0.],[1.]).envelope(1.))
    # A known oscillator retains a load-induced equilibrium and actual vibration.
    for frequency in (2.,1e6):
        mass=np.array([2.]);force=np.array([.3]);velocity=np.array([.17]);k=mass*frequency**2
        basis=ModeBasis(mass,k.reshape(1,1),force,velocity)
        for h in (0.,1e-12,1e-6,.001,1.):
            r=basis.advance(h);angle=frequency*h
            x=.17*math.sin(angle)/frequency+.3/(2*frequency**2)*2*math.sin(angle/2)**2
            v=.17*math.cos(angle)+.3/(2*frequency)*math.sin(angle)
            assert abs(r['displacement'][0]-x)<1e-13*max(1,abs(x))
            # Mass scaling perturbs frequency by roundoff; long stiff flights
            # amplify that phase error. Bound it explicitly, not by a fixed
            # tolerance unrelated to frequency and elapsed time.
            phase=abs(math.sqrt(basis.eigenvalues[0])-frequency)*h
            velocity_bound=8*np.finfo(float).eps+phase*(.17+.3/(2*frequency))
            assert abs(r['velocity'][0]-v)<=velocity_bound
            assert abs(r['reference_energy_residual_j'])<1e-13
            dv=(force*h-k*r['integrated_displacement'])/mass
            assert abs(dv[0]-(r['velocity'][0]-.17))<1e-13
    free=ModeBasis([2.],[[0.]],[4.],[3.]).advance(.7)
    assert abs(free['displacement'][0]-(3*.7+.7**2))<1e-14
    assert abs(free['velocity'][0]-4.4)<1e-14
    unstable=ModeBasis([2.],[[-8.]],[0.],[.1]).advance(.2)
    assert abs(unstable['velocity'][0]-.1*math.cosh(.4))<1e-14
    assert abs(unstable['reference_energy_residual_j'])<1e-13
    # Uncertain/negative modes are not silently zeroed or discarded.
    refuse(lambda:ModeBasis([2.],[[-8.]],[0.],[.1]).advance(100.))
    refuse(lambda:ModeBasis([1.],[[-10000.]],[0.],[.1]).advance(1.))
    pair=ModeBasis([1.,1.],[[4.,-4.],[-4.,4.]],[0.,0.],[1.,-1.]).advance(.3)
    omega=math.sqrt(8.)
    assert np.linalg.norm(pair['displacement']-[math.sin(omega*.3)/omega,-math.sin(omega*.3)/omega])<1e-14
    assert np.linalg.norm(pair['velocity']-[math.cos(omega*.3),-math.cos(omega*.3)])<1e-14
    refuse(lambda:ModeBasis([0.],[[1.]],[0.],[0.]))
    refuse(lambda:ModeBasis([1.,1.],[[1.,2.],[0.,1.]],[0.,0.],[0.,0.]))
    refuse(lambda:ModeBasis(np.ones(97),np.eye(97),np.zeros(97),np.zeros(97)))
    rows=[]
    for material in ('glass','oak','iron','ice'):
        close=CpuCoupledWorld(dict(material=material,height_m=.001,representation_policy='partitioned-flight'))
        close_saved=close.export_checkpoint();gaps=close.eval.current_sphere_gaps(close.eval.n-1)
        assert abs(np.min(gaps)-.001)<1e-15,'current surface gap must not be replaced by overlapping enclosing spheres'
        assert close.prepare_modes()['current_native_surface_gap_m']>0 and close.export_checkpoint()==close_saved
        w=CpuCoupledWorld(dict(material=material,ball_mass_kg=.1,height_m=10.,dt_s=1/240,pipeline='local-jacobian',representation_policy='partitioned-flight'))
        initial=w.export_checkpoint();r0=w.prepare_modes()
        assert w.export_checkpoint()==initial and r0['execution_admitted'] is False
        assert max(r0['one_sided_derivative_defect'])>.1,'unloaded unilateral contacts are not a smooth elastic reference'
        w.advance(1);before=w.export_checkpoint();r=w.prepare_modes();basis=w.prepared_modes[0]
        assert w.export_checkpoint()==before,'preparation changed canonical clock, motion, history, registry or counters'
        assert r['dynamic_dofs']==54 and r['retained_modes']==54 and not r['execution_admitted']
        assert r['eigen_residual_relative']<1e-12 and r['orthogonality_residual']<1e-12
        assert r['linearization_symmetry_relative']<1e-4 and r['derivative_refinement_relative']<1e-4
        represented=np.repeat(w.eval.bodies[:-1,1:3],3,axis=1).ravel()
        represented=represented[represented>0]
        assert np.array_equal(basis.mass,represented),'represented mass/inertia changed through sqrt roundtrip'
        assert r['baseline_contact_energy_j']>0,'support preload was discarded'
        assert r['baseline_material_energy_j']>0,'native material stored energy was discarded'
        assert np.linalg.norm(basis.velocity)>0,'actual vibration was frozen'
        assert np.array_equal(basis.native_edges[:,35:67],w.eval.edges[:,35:67]),'native prestress/plastic/damage/work history lost'
        assert basis.full_force_tangent.shape==(72,54),'fixed support reaction tangent lost'
        assert np.isfinite(basis.advance(1/240)['affine_wrench_impulse']).all()
        guard=contact_envelope(basis,CpuCoupledEvaluator(basis.native_bodies.copy(),basis.native_edges.copy()),1/240)
        assert r['continuous_contact_envelope']['native_sites']==len(guard['geometry'])
        assert guard['summary']['possible_contact_changes']>0,'touching branches must not be silently admitted'
        assert not guard['summary']['execution_admitted']
        # Evaluate actual native geometry along the explicitly declared affine
        # translation/Cayley path, not a canned endpoint or contact animation.
        geometry_eval=CpuCoupledEvaluator(basis.native_bodies.copy(),basis.native_edges.copy())
        for h in np.linspace(0,1/240,33):
            prediction=basis.advance(float(h));movement=np.zeros((geometry_eval.n,6))
            movement.ravel()[basis.dynamic_dofs]=prediction['displacement']
            geometry_eval.bodies[:]=basis.native_bodies
            geometry_eval.bodies[:,23:26]+=movement[:,:3]
            geometry_eval.bodies[:,7:10]=geometry_eval.bodies[:,20:23]+geometry_eval.bodies[:,23:26]
            for i,theta in enumerate(movement[:,3:]):
                w0,xyz=basis.native_bodies[i,10],basis.native_bodies[i,11:14]
                dq=np.r_[w0-np.dot(theta/2,xyz),xyz+w0*theta/2+np.cross(theta/2,xyz)]
                geometry_eval.bodies[i,10:14]=dq/np.linalg.norm(dq)
            sites=geometry_eval.contact_geometry()
            assert np.array_equal(sites[:,:4],guard['geometry'][:,:4])
            assert np.all(sites[:,4]>=guard['lower_gap_m']) and np.all(sites[:,4]<=guard['upper_gap_m']),material
        mutated=CpuCoupledEvaluator(basis.native_bodies.copy(),basis.native_edges.copy());mutated.edges[0,35]+=1e-15
        refuse(lambda:contact_envelope(basis,mutated,1/240))
        assert r['derivative_irreversible_changes']==0,'derivative crossed damage/plasticity'
        repeated=w.prepare_modes();assert repeated['state_key']==r['state_key']
        assert repeated['maximum_omega_squared_s2']==r['maximum_omega_squared_s2']
        with patch('coupled_modes._samples',side_effect=MemoryError('injected private allocation failure')):
            try:w.prepare_modes()
            except MemoryError:pass
            else:raise AssertionError('Injected preparation failure was swallowed')
        assert w.export_checkpoint()==before
        # The next accepted detailed step is unchanged, not replaced by this reference.
        reference=CpuCoupledWorld.from_checkpoint(before)
        w.advance(1);reference.advance(1)
        assert w.prepared_modes is None,'derived basis must invalidate after accepted motion/history'
        def differences(a,b,path=''):
            if type(a)!=type(b):return [path]
            if isinstance(a,dict):return sum((differences(a[k],b[k],path+'/'+k) for k in a),[])
            if isinstance(a,list):return sum((differences(x,y,path+'/'+str(i)) for i,(x,y) in enumerate(zip(a,b))),[])
            return [] if a==b else [path]
        changes=set(differences(w.export_checkpoint(),reference.export_checkpoint()))
        assert changes <= {'/continuation/last_ms/$f64','/continuation/step_s/$f64','/content_sha256'},changes
        assert w.prepare_modes()['state_key']!=r['state_key'],'stale tangent identity survived a motion/history change'
        # Private common-time comparisons expose the local affine approximation.
        # Select the actual prepared island from the retained accepted checkpoint.
        control=CpuCoupledWorld.from_checkpoint(before)
        control.prepare_modes();b=control.prepared_modes[0]
        indices=control.representations.indices
        edges=control.eval.edges.copy();edges[:,:2]=[[int(a),int(c)] for a,c in edges[:,:2]]
        e=CpuCoupledEvaluator(control.eval.bodies[indices],edges,pipeline='local-jacobian')
        original=e.bodies.copy();old=e.edges.copy();comparison=[]
        for h in (2e-7,1e-7,5e-8):
            e.bodies[:]=original;e.edges[:]=old
            out,v,it,res=e.solve(h)
            prediction=b.advance(h)
            dx=(h*(original[:,14:20]+v)/2).ravel()[e.dynamic]
            vr=v.ravel()[e.dynamic]
            comparison.append(dict(dt_s=h,equation_residual=res,
                mass_weighted_displacement_error_sqrt_kg_m=float(np.linalg.norm(e.active_weights*(prediction['displacement']-dx))),
                velocity_error_sqrt_j=float(np.linalg.norm(e.active_weights*(prediction['velocity']-vr))),
                affine_energy_residual_j=prediction['reference_energy_residual_j']))
        rows.append(dict(material=material,declaration=control.d,initial=r0,loaded=r,comparison=comparison))
        # Editing poses without transferring history is not an admissible sampler.
        bad=original.copy();bad[3,23]+=1e-9;bad[3,7]=bad[3,20]+bad[3,23]
        broken=CpuCoupledEvaluator(bad,old)
        assert broken.evaluate(-bad[:,14:20],1e-6)['faults'][0]!=0
        too_large=CpuCoupledEvaluator(np.vstack((original,original)),old)
        refuse(lambda:prepare(too_large,source_identity=implementation_hash()))
        refuse(lambda:prepare(e,source_identity=implementation_hash(),world_body_ids=[0]*e.n))
        # An overlapping striker cannot be removed from the coupled basis.
        # The loaded sheet has actually sagged; its nominal rest face is not
        # a valid touching witness. A 1 µm overlap encloses that tiny sag.
        control.eval.bodies[-1,8]=.035+control.eval.bodies[-1,4]-1e-6
        control.eval.bodies[-1,20:23]=control.eval.bodies[-1,7:10];control.eval.bodies[-1,23:26]=0
        refuse(control.prepare_modes)
        print('PASS',material,'native preparation / preload / all modes / unchanged next step',flush=True)
    free=CpuCoupledWorld(dict(experiment='freefall'));saved=free.export_checkpoint();refuse(free.prepare_modes);assert free.export_checkpoint()==saved
    # Independently known rotated-box face, then a refused request's buffers.
    box=control.eval.bodies[1].copy();ball=control.eval.bodies[-1].copy()
    box[7:10]=box[20:26]=0;box[10:14]=box[26:30]=[math.sqrt(.5),0,0,math.sqrt(.5)]
    ball[7:10]=ball[20:23]=[0,box[4]+ball[4]+.0007,0];ball[23:26]=0
    geometry=CpuCoupledEvaluator(np.array([box,ball]),[])
    assert abs(geometry.current_sphere_gaps(1)[0]-.0007)<1e-15
    protected=np.full(2,123.)
    assert geometry.lib.banjo_coupled_cpu_separation(geometry.bodies,2,2,protected)==-1 and np.all(protected==123)
    protected_sites=np.full((48,10),123.)
    assert geometry.lib.banjo_coupled_cpu_contact_geometry(geometry.bodies,2,0,protected_sites)==-1
    assert np.all(protected_sites==123),'invalid capacity mutated caller output'
    # Independent box/plane Gauss-site geometry: half the six faces lie above,
    # half below the cube center; do not query only broadphase-active pairs.
    plane=control.eval.bodies[0].copy();cube=control.eval.bodies[3].copy()
    cube[7:10]=cube[20:23]=[0,.1,0];cube[23:26]=0;cube[10:14]=cube[26:30]=[1,0,0,0]
    gp=CpuCoupledEvaluator(np.array([plane,cube]),[]).contact_geometry()
    expected=[]
    for face in range(6):
        for j in range(4):
            y=.1+((1 if face%2 else -1)*cube[5] if face//2==1 else (1 if (j%2 if face//2==0 else (j//2)%2) else -1)*cube[5]/math.sqrt(3))
            expected.append(y)
    assert len(gp)==24 and np.allclose(gp[:,4],expected,rtol=0,atol=2e-17)
    assert np.all(gp[:,5]>0),'separated broad pairs disappeared from the branch diagnostic'
    report=dict(schema='banjo.cpu-mode-preparation-evidence.v1',implementation_sha256=implementation_hash(),runs=rows,
        scope='Private affine preparation and analytical evolution; no world modal execution or full impact qualification')
    args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print('PASS native mode preparation, exact state/next-step retention and affine oracles')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--library',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    main(p.parse_args())
