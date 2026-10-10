"""Private CPU vibration preparation from the installed native laws.

This compiles a local affine force model, not an admitted world continuation.
No state/history is reset to obtain a tangent and no eigenmode is discarded.
"""
import hashlib
import json
import math
import time
import numpy as np


def _observed_interval(eigen, f, v0, h):
    """One frequency's observed motion; combine exact degeneracies first."""
    eps=np.finfo(float).eps
    if eigen==0:
        def q(t):return v0*t+.5*f*t*t
        def v(t):return v0+f*t
        stationary=np.divide(-v0,f,out=np.zeros_like(f),where=f!=0)
        stationary=np.where((stationary>0)&(stationary<h),stationary,0)
        qr=np.array([q(0),q(h),q(stationary)]);vr=np.array([v(0),v(h)])
        qs=abs(v0)*h+.5*abs(f)*h*h;vs=abs(v0)+abs(f)*h
        response=(.5*h*h,h,h,1.)
    else:
        rate=math.sqrt(abs(eigen));angle=rate*h
        if eigen>0:
            def q(t):return v0*np.sin(rate*t)/rate+f*2*np.sin(rate*t/2)**2/eigen
            def v(t):return v0*np.cos(rate*t)+f*np.sin(rate*t)/rate
            if angle>=2*math.pi:
                center=f/eigen;amp=np.hypot(v0/rate,center);ampv=np.hypot(v0,f/rate)
                qr=np.array([center-amp,center+amp]);vr=np.array([-ampv,ampv])
            else:
                def candidates(a,b):
                    base=np.mod(np.arctan2(a,b),math.pi)
                    angles=np.array([base,base+math.pi,base+2*math.pi])
                    return [np.zeros_like(base),np.full_like(base,h),*np.where(angles<=angle+32*eps*max(1.,angle),angles/rate,0)]
                qr=np.array([q(t) for t in candidates(v0/rate,-f/eigen)])
                vr=np.array([v(t) for t in candidates(f/rate,v0)])
            qs=abs(v0)/rate*min(1.,angle)+abs(f/eigen)*min(2.,angle*angle/2)
            vs=abs(v0)+abs(f/rate)*min(1.,angle)
            response=(min(.5*h*h,2/eigen),min(h,1/rate),min(h,1/rate),1.)
        else:
            def q(t):return v0*np.sinh(rate*t)/rate+f*2*np.sinh(rate*t/2)**2/(-eigen)
            def v(t):return v0*np.cosh(rate*t)+f*np.sinh(rate*t)/rate
            def stationary(a,b):
                ratio=np.divide(-a,b,out=np.zeros_like(a),where=b!=0)
                ratio=np.where((ratio>0)&(ratio<1),ratio,0)
                t=np.arctanh(ratio)/rate
                return np.where(t<=h,t,0)
            qr=np.array([q(0),q(h),q(stationary(v0/rate,f/(-eigen)))])
            vr=np.array([v(0),v(h),v(stationary(f/rate,v0))])
            qs=abs(v0)/rate*math.sinh(angle)+abs(f/(-eigen))*2*math.sinh(angle/2)**2
            vs=abs(v0)*math.cosh(angle)+abs(f/rate)*math.sinh(angle)
            response=(2*math.sinh(angle/2)**2/(-eigen),math.sinh(angle)/rate,math.sinh(angle)/rate,math.cosh(angle))
    return (np.min(qr,axis=0)-64*eps*qs,np.max(qr,axis=0)+64*eps*qs,
        np.min(vr,axis=0)-64*eps*vs,np.max(vr,axis=0)+64*eps*vs,response)


class ModeBasis:
    """All modes of a declared M x'' = F0 - K x reference, including unstable ones."""
    def __init__(self, mass, stiffness, force, velocity):
        self.mass = np.asarray(mass, dtype=np.float64).copy()
        self.stiffness = np.asarray(stiffness, dtype=np.float64).copy()
        self.force = np.asarray(force, dtype=np.float64).copy()
        self.velocity = np.asarray(velocity, dtype=np.float64).copy()
        n = len(self.mass)
        if not 1 <= n <= 96 or self.stiffness.shape != (n, n) or any(a.shape != (n,) for a in (self.force, self.velocity)):
            raise ValueError('Mode preparation exceeds its 96-DOF bound')
        if not all(np.isfinite(a).all() for a in (self.mass, self.stiffness, self.force, self.velocity)) or np.any(self.mass <= 0):
            raise ValueError('Mode preparation needs finite positive represented mass/inertia')
        if not np.array_equal(self.stiffness, self.stiffness.T):
            raise ValueError('Affine reference stiffness must be explicitly symmetric')
        self.root = np.sqrt(self.mass)
        self.scaled = self.stiffness / self.root[:, None] / self.root[None, :]
        self.eigenvalues, self.vectors = np.linalg.eigh(self.scaled)
        self.modal_force = self.vectors.T @ (self.force / self.root)
        self.modal_velocity = self.vectors.T @ (self.root * self.velocity)

    def envelope(self, h, observations=None):
        """Continuous component bounds for this affine reference on [0,h].

        Includes interior extrema and every retained mode. Interval mapping
        deliberately loses mode correlations. This is NOT a nonlinear native
        trajectory bound, and cannot admit world execution by itself.
        """
        self.advance(h)  # same finite-time/unstable-mode refusal contract
        qlo=[]; qhi=[]; vlo=[]; vhi=[]
        eps=np.finfo(float).eps
        for eigen, f, v0 in zip(self.eigenvalues,self.modal_force,self.modal_velocity):
            tq=[0.,h];tv=[0.,h]
            if eigen == 0:
                if f and 0 < -v0/f < h: tq.append(-v0/f)
                q=lambda t:v0*t+.5*f*t*t
                v=lambda t:v0+f*t
                qscale=abs(v0)*h+.5*abs(f)*h*h
                vscale=abs(v0)+abs(f)*h
            else:
                rate=math.sqrt(abs(eigen));angle=rate*h
                if eigen > 0:
                    q=lambda t:v0*math.sin(rate*t)/rate+f*2*math.sin(rate*t/2)**2/eigen
                    v=lambda t:v0*math.cos(rate*t)+f*math.sin(rate*t)/rate
                    # A sin(theta)+B cos(theta)+C has stationary points
                    # atan2(A,B)+k*pi. At most three candidates for <2pi;
                    # complete cycles use exact global amplitude bounds.
                    def extrema(a,b):
                        base=math.atan2(a,b)%math.pi
                        return [x/rate for x in (base,base+math.pi,base+2*math.pi)
                            if x<=angle+32*eps*max(1.,angle)]
                    if angle >= 2*math.pi:
                        center=f/eigen;amp=math.hypot(v0/rate,center)
                        qr=[center-amp,center+amp]
                        ampv=math.hypot(v0,f/rate);vr=[-ampv,ampv]
                    else:
                        tq+=extrema(v0/rate,-f/eigen)
                        tv+=extrema(f/rate,v0)
                        qr=[q(t) for t in tq];vr=[v(t) for t in tv]
                    qscale=abs(v0)/rate*min(1.,angle)+abs(f/eigen)*min(2.,angle*angle/2)
                    vscale=abs(v0)+abs(f/rate)*min(1.,angle)
                else:
                    q=lambda t:v0*math.sinh(rate*t)/rate+f*2*math.sinh(rate*t/2)**2/(-eigen)
                    v=lambda t:v0*math.cosh(rate*t)+f*math.sinh(rate*t)/rate
                    # Hyperbolic extrema: tanh(theta)=-a/b. Monotone tanh
                    # gives at most one positive stationary point per mode.
                    for a,b,times in ((v0/rate,f/(-eigen),tq),(f/rate,v0,tv)):
                        ratio=-a/b if b else -1.
                        if 0 < ratio < 1:
                            t=math.atanh(ratio)/rate
                            if t<=h:times.append(t)
                    qscale=abs(v0)/rate*math.sinh(angle)+abs(f/(-eigen))*2*math.sinh(angle/2)**2
                    vscale=abs(v0)*math.cosh(angle)+abs(f/rate)*math.sinh(angle)
            if eigen <= 0:qr=[q(t) for t in tq];vr=[v(t) for t in tv]
            # Explicit arithmetic/libm roundoff allowance, then outward rounding.
            # This is measured FP64 coverage, not a formal directed-libm proof.
            qpad=64*eps*qscale;vpad=64*eps*vscale
            qlo.append(np.nextafter(min(qr)-qpad,-np.inf));qhi.append(np.nextafter(max(qr)+qpad,np.inf))
            vlo.append(np.nextafter(min(vr)-vpad,-np.inf));vhi.append(np.nextafter(max(vr)+vpad,np.inf))
        transform=self.vectors/self.root[:,None]
        if observations is not None:
            observations=np.asarray(observations,dtype=np.float64)
            if observations.ndim!=2 or observations.shape[1]!=len(self.mass) or not 1<=len(observations)<=32768 or not np.isfinite(observations).all():
                raise ValueError('Invalid bounded affine observation matrix')
            # Project each physical observation BEFORE taking modal intervals.
            # Bounding each body first loses common-motion cancellation.
            transform_pad=64*eps*(abs(observations)@abs(transform))
            transform=observations@transform
            # Equal frequencies share a time function. Sum their observed
            # coefficients before extrema; never merge merely close rates.
            xlo=np.zeros(len(observations));xhi=xlo.copy();ulo=xlo.copy();uhi=xlo.copy()
            scale_x=xlo.copy();scale_v=xlo.copy()
            for eigen in np.unique(self.eigenvalues):
                selected=self.eigenvalues==eigen;t=transform[:,selected]
                f=t@self.modal_force[selected];v=t@self.modal_velocity[selected]
                fpad=64*eps*(abs(t)@abs(self.modal_force[selected]))+transform_pad[:,selected]@abs(self.modal_force[selected])
                vpad=64*eps*(abs(t)@abs(self.modal_velocity[selected]))+transform_pad[:,selected]@abs(self.modal_velocity[selected])
                a,b,c,d,response=_observed_interval(float(eigen),f,v,h)
                dx=response[0]*fpad+response[1]*vpad;dv=response[2]*fpad+response[3]*vpad
                xlo+=a-dx;xhi+=b+dx;ulo+=c-dv;uhi+=d+dv
                scale_x+=np.maximum(abs(a),abs(b))+dx;scale_v+=np.maximum(abs(c),abs(d))+dv
            xlo=np.nextafter(xlo-64*eps*scale_x,-np.inf);xhi=np.nextafter(xhi+64*eps*scale_x,np.inf)
            ulo=np.nextafter(ulo-64*eps*scale_v,-np.inf);uhi=np.nextafter(uhi+64*eps*scale_v,np.inf)
            if not all(np.isfinite(a).all() for a in (xlo,xhi,ulo,uhi)):raise ValueError('Nonfinite projected affine envelope')
            return dict(horizon_s=h,displacement_lower=xlo,displacement_upper=xhi,velocity_lower=ulo,velocity_upper=uhi,
                scope='Continuous correlated observation reference with exact-frequency grouping; not certified nonlinear world motion')
        positive=np.maximum(transform,0);negative=np.minimum(transform,0)
        def mapped(lo,hi):
            lo=np.asarray(lo);hi=np.asarray(hi)
            pad=64*eps*(abs(transform)@np.maximum(abs(lo),abs(hi)))
            return (np.nextafter(positive@lo+negative@hi-pad,-np.inf),
                np.nextafter(positive@hi+negative@lo+pad,np.inf))
        xlo,xhi=mapped(qlo,qhi);ulo,uhi=mapped(vlo,vhi)
        if not all(np.isfinite(a).all() for a in (xlo,xhi,ulo,uhi)):raise ValueError('Nonfinite affine envelope')
        return dict(horizon_s=h,displacement_lower=xlo,displacement_upper=xhi,
            velocity_lower=ulo,velocity_upper=uhi,
            scope='Continuous all-mode affine reference only; FP64 allowance, not certified nonlinear world motion')

    def advance(self, h):
        if type(h) not in (int, float) or not math.isfinite(h) or not 0 <= h <= 2:
            raise ValueError('Affine prediction time must be between zero and two seconds')
        q = np.empty(len(self.mass)); v = np.empty_like(q); integrated = np.empty_like(q)
        for i, eigen in enumerate(self.eigenvalues):
            f = self.modal_force[i]; v0 = self.modal_velocity[i]
            if eigen == 0:
                q[i] = v0 * h + .5 * f * h * h; v[i] = v0 + f * h
                integrated[i] = .5*v0*h*h+f*h*h*h/6
            else:
                rate = math.sqrt(abs(eigen)); angle = rate * h
                if eigen > 0:
                    sn = math.sin(angle); cs = math.cos(angle)
                    # 1-cos loses tiny preload displacements near zero.
                    one_minus = 2 * math.sin(angle / 2) ** 2
                    q[i] = v0 * sn / rate + f * one_minus / eigen
                    v[i] = v0 * cs + f * sn / rate
                    difference=h*(angle*angle/6-angle**4/120+angle**6/5040) if abs(angle)<.001 else h-sn/rate
                    integrated[i]=(v0*one_minus+f*difference)/eigen
                else:
                    if angle > 50: raise ValueError('Unstable affine prediction exceeds its numerical bound')
                    sn = math.sinh(angle); cs = math.cosh(angle)
                    q[i] = v0 * sn / rate + f * (2 * math.sinh(angle / 2) ** 2) / (-eigen)
                    v[i] = v0 * cs + f * sn / rate
                    difference=h*(angle*angle/6+angle**4/120+angle**6/5040) if angle<.001 else sn/rate-h
                    integrated[i]=(v0*2*math.sinh(angle/2)**2+f*difference)/(-eigen)
        displacement = self.vectors @ q / self.root
        velocity = self.vectors @ v / self.root
        e0 = .5 * np.dot(self.mass * self.velocity, self.velocity)
        e1 = .5 * np.dot(self.mass * velocity, velocity) + .5 * np.dot(displacement, self.stiffness @ displacement) - np.dot(self.force, displacement)
        if not np.isfinite(displacement).all() or not np.isfinite(velocity).all() or not math.isfinite(e1):
            raise ValueError('Nonfinite affine prediction')
        result=dict(displacement=displacement, velocity=velocity, integrated_displacement=self.vectors@integrated/self.root,
            reference_energy_residual_j=float(e1-e0))
        if hasattr(self,'full_force'):
            result['affine_wrench_impulse']=self.full_force*h+self.full_force_tangent@result['integrated_displacement']
            result['affine_dynamic_impulse_residual']=result['affine_wrench_impulse'][self.dynamic_dofs]-self.mass*(velocity-self.velocity)
        return result


def _samples(evaluator, bodies, edges, delta, *, material_only=False):
    """Reach each private sample along a real native trial, then read its force.

    Assigning a perturbed pose while leaving old material history in place is
    invalid: it creates work with no motion. The first trial transfers history
    to that pose; the stationary trial reads the corresponding endpoint force.
    """
    e = evaluator; n = len(e.dynamic); velocities = np.repeat((-bodies[:, 14:20])[None], 2*n, axis=0)
    for j, dof in enumerate(e.dynamic):
        velocities[j, dof//6, dof%6] += 2*delta[j]/1e-6
        velocities[n+j, dof//6, dof%6] -= 2*delta[j]/1e-6
    evaluate=e.evaluate_material if material_only else e.evaluate
    path = evaluate(velocities, 1e-6)
    if np.any(path['faults']): raise ValueError('Native derivative path refused: '+str(path['faults'].tolist()))
    forces = []
    irreversible_changes = 0
    try:
        for k in range(2*n):
            j = k % n; dof = e.dynamic[j]; sign = 1 if k < n else -1
            e.bodies[:] = bodies; e.edges[:] = edges
            e.bodies[:, 7:14] = path['poses'][k]
            if dof%6 < 3: e.bodies[dof//6, 23+dof%6] += sign*delta[j]
            e.bodies[:, 14:20] = 0
            e.edges[:, 35:67] = path['history'][k]
            for i, edge in enumerate(edges):
                cols = slice(0, 12) if edge[2] == 1 else slice(5, 7)
                irreversible_changes += int(not np.array_equal(path['history'][k, i, cols], edge[35:67][cols]))
            out = evaluate(e.bodies[:, 14:20], 1e-6)
            if out['faults'][0]: raise ValueError('Native stationary derivative sample refused')
            force=out['forces'][0].copy()
            if material_only and dof%6>=3:
                # Pull world torques back into the frozen Cayley chart. A
                # world-wrench derivative is not a symmetric energy Hessian.
                turn=np.zeros(3);turn[dof%6-3]=sign*delta[j]
                jacobian=(np.eye(3)+.5*_skew(turn))/(1+np.dot(turn,turn)/4)
                force[dof//6,3:]=jacobian.T@force[dof//6,3:]
            forces.append(force.ravel().copy())
    finally:
        e.bodies[:] = bodies; e.edges[:] = edges
    return np.asarray(forces), irreversible_changes


def _skew(v):
    v=np.asarray(v);out=np.zeros(v.shape[:-1]+(3,3))
    out[...,0,1]=-v[...,2];out[...,0,2]=v[...,1];out[...,1,0]=v[...,2]
    out[...,1,2]=-v[...,0];out[...,2,0]=-v[...,1];out[...,2,1]=v[...,0]
    return out


def _rotation(q):
    w,x,y,z=q
    return np.array([[1-2*(y*y+z*z),2*(x*y-w*z),2*(x*z+w*y)],
        [2*(x*y+w*z),1-2*(x*x+z*z),2*(y*z-w*x)],
        [2*(x*z-w*y),2*(y*z+w*x),1-2*(x*x+y*y)]])


def _box_gap(q):
    return np.linalg.norm(np.maximum(q,0),axis=1)+np.minimum(np.max(q,axis=1),0)


def contact_gap_hessian(row,bodies):
    """Exact smooth face/plane gap Hessian in the frozen Cayley pose chart.

    This chart curvature is different from differentiating world torques.
    Box feature ties and primitive contacts refuse, not silently symmetrize.
    """
    a,b=int(row[0]),int(row[1]);owner=int(row[3])
    if owner not in (a,b):raise ValueError('Surface-site curvature requires native point/plane or point/box geometry')
    target=b if owner==a else a;shape=int(row[15])
    if shape not in (0,1):raise ValueError('Unsupported target curvature')
    if np.any(abs(np.sum(bodies[[owner,target],10:14]**2,axis=1)-1)>128*np.finfo(float).eps):
        raise ValueError('Curvature requires normalized native orientations')
    n=row[19:22] if owner==a else row[25:28];lever=row[6:9];relative=row[9:12]
    if shape==1:
        q=row[31:34];order=np.argsort(q);axis=int(order[-1])
        allowance=128*np.finfo(float).eps*(abs(q).sum()+np.linalg.norm(relative)+row[16:19].sum())
        if q[axis]>0 or q[axis]-q[order[-2]]<=allowance or abs(row[12+axis])<=allowance:
            raise ValueError('Nonsmooth/exterior box feature needs qualified curvature')
        declared=_rotation(bodies[target,10:14])[:,axis]*(-1 if row[12+axis]<0 else 1)
        if not np.allclose(n,declared,rtol=0,atol=128*np.finfo(float).eps):raise ValueError('Native target feature/gradient differs')
    h=np.zeros((12,12));eye=np.eye(3)
    def angular(v):return .5*(np.outer(n,v)+np.outer(v,n))-np.dot(n,v)*eye
    h[3:6,3:6]=angular(lever);h[9:12,9:12]=angular(relative)
    h[3:6,9:12]=np.dot(n,lever)*eye-np.outer(n,lever);h[9:12,3:6]=h[3:6,9:12].T
    h[:3,9:12]=-_skew(n);h[9:12,:3]=h[:3,9:12].T
    h[6:9,9:12]=_skew(n);h[9:12,6:9]=h[6:9,9:12].T
    if owner==b:
        order=np.r_[np.arange(6,12),np.arange(6)];h=h[np.ix_(order,order)]
    return h


def contact_branch_model(evaluator, *, touching):
    """Conditional endpoint-potential tangent, never a native world response.

    Open and closed choices at exact zero remain explicit. Already compressed
    sites retain their geometric preload curvature and current native force.
    Broad SAT and constitutive/event qualification are required separately.
    """
    if touching not in ('open','closed'):raise ValueError('Touching contact needs an explicit branch choice')
    rows=evaluator.contact_differential();stiffness=evaluator.contact_stiffness()
    if len(rows)!=len(stiffness):raise ValueError('Native contact stiffness mapping differs')
    size=evaluator.n*6;force=np.zeros(size);matrix=np.zeros((size,size));energy=0.;compressed=zero=0
    geometric_norm=0.
    for row,k in zip(rows,stiffness):
        if row[5]>0 or row[4]>0:continue
        gap=row[4]
        if gap==0:
            zero+=1
            if touching=='open':continue
        else:compressed+=1
        ids=np.r_[np.arange(int(row[0])*6,int(row[0])*6+6),np.arange(int(row[1])*6,int(row[1])*6+6)]
        g=row[19:31];h=contact_gap_hessian(row,evaluator.bodies)
        curvature=k*(np.outer(g,g)+gap*h)
        force[ids]+=-k*gap*g;matrix[np.ix_(ids,ids)]+=curvature;energy+=.5*k*gap*gap
        geometric_norm+=float(np.linalg.norm(k*gap*h))
    if not np.isfinite(matrix).all() or not np.isfinite(force).all() or not math.isfinite(energy):raise ValueError('Nonfinite branch potential')
    return dict(force=force,stiffness=matrix,energy_j=energy,compressed_sites=compressed,touching_sites=zero,
        touching_choice=touching,geometric_curvature_norm=geometric_norm,
        scope='Native smooth endpoint potential in frozen Cayley coordinates; explicit touching branch, not an accepted timestep')


def prepare_contact_branches(evaluator,bodies,edges,delta):
    """Separate native constitutive sampling from conditional contact Hessians."""
    started=time.perf_counter();e=evaluator
    baseline=e.evaluate_material(-bodies[:,14:20],1e-6)
    if baseline['faults'][0]:raise ValueError('Native material baseline refused')
    f=baseline['forces'][0].ravel();weights=e.active_weights;matrices=[];changed=0
    for factor in (1.,.5):
        samples,changes=_samples(e,bodies,edges,delta*factor,material_only=True);changed+=changes
        up=-(samples[:len(delta)]-f)/(delta[:,None]*factor);down=-(f-samples[len(delta):])/(delta[:,None]*factor)
        matrices.append(((up+down)/2).T)
    raw=matrices[-1]
    scaled=raw[e.dynamic]/weights[:,None]/weights[None,:]
    sides=(up-down).T[e.dynamic]/weights[:,None]/weights[None,:]
    norm=max(np.linalg.norm(scaled),1)
    result=dict(material_one_sided_defect=float(np.linalg.norm(sides)/norm),
        material_symmetry_defect=float(np.linalg.norm(scaled-scaled.T)/norm),
        material_refinement_relative=float(np.linalg.norm((matrices[0][e.dynamic]-raw[e.dynamic])/weights[:,None]/weights[None,:])/norm),
        material_irreversible_sample_changes=changed,material_force_rows=len(f),branches={},execution_admitted=False)
    # Keep both declared choices. Event continuation must choose a consistent
    # branch; these preparations do not choose it on the user's behalf.
    full=e.evaluate(-bodies[:,14:20],1e-6)
    if full['faults'][0]:raise ValueError('Native full baseline refused')
    for choice in ('open','closed'):
        contact=contact_branch_model(e,touching=choice)
        difference=f+contact['force']-full['forces'][0].ravel()
        energy_error=contact['energy_j']-full['ledger'][0,4]
        if np.linalg.norm(difference)>1e-9 or abs(energy_error)>1e-20+1e-12*abs(contact['energy_j']):
            raise ValueError('Separated endpoint potential does not reconstruct native stationary response')
        combined=raw+contact['stiffness'][:,e.dynamic]
        symmetric=(combined[e.dynamic]+combined[e.dynamic].T)/2
        basis=ModeBasis(np.repeat(bodies[:,1:3],3,axis=1).ravel()[e.dynamic],symmetric,
            f[e.dynamic]+contact['force'][e.dynamic],bodies[:,14:20].ravel()[e.dynamic])
        result['branches'][choice]=dict(compressed_sites=contact['compressed_sites'],touching_sites=contact['touching_sites'],
            geometric_curvature_norm=contact['geometric_curvature_norm'],
            stationary_force_residual_n_nm=float(np.linalg.norm(difference)),stationary_contact_energy_residual_j=float(energy_error),
            negative_modes=int(np.sum(basis.eigenvalues<0)),maximum_omega_squared_s2=float(np.max(basis.eigenvalues)))
    result.update(material_candidate_valid=changed==0 and result['material_one_sided_defect']<=1e-6 and result['material_symmetry_defect']<=1e-6 and result['material_refinement_relative']<=1e-6,
        full_reaction_maps_retained=False,broad_contact_events_qualified=False,wall_s=time.perf_counter()-started,
        scope='Private material/contact separation and explicit touching candidates; material branches, contact events and nonlinear transfers remain unqualified')
    return result


def contact_envelope(basis, evaluator, h):
    """Native site sign checks conditional on the continuous affine motion.

    Translation boxes and local Cayley rotation vectors map to point travel.
    The exact box signed-distance is 1-Lipschitz in its local coordinates;
    rotation travel is bounded by min(|theta|,2)*lever length. This covers
    interior times, including a close/reopen missed by endpoint-only checks.
    Broad SAT feature selection, constitutive branches and nonlinear error
    are separate gates and deliberately remain unqualified.
    """
    if not np.array_equal(evaluator.bodies,basis.native_bodies) or not np.array_equal(evaluator.edges,basis.native_edges):
        raise ValueError('Contact envelope needs the exact prepared native state/history')
    started=time.perf_counter();bounds=basis.envelope(h)
    absolute=np.maximum(abs(bounds['displacement_lower']),abs(bounds['displacement_upper']))
    travel=np.zeros((evaluator.n,6));travel.ravel()[basis.dynamic_dofs]=absolute
    translation=np.linalg.norm(travel[:,:3],axis=1)
    rotation=np.minimum(np.linalg.norm(travel[:,3:],axis=1),2.)
    if not np.isfinite(translation).all() or not np.isfinite(rotation).all():raise ValueError('Nonfinite affine body travel')
    rows=evaluator.contact_geometry();differential=evaluator.contact_differential();owner=rows[:,3].astype(int)
    if not np.array_equal(rows[:,:6],differential[:,:6]):raise ValueError('Native contact differential mapping differs')
    if np.any(owner<0):raise ValueError('Affine contact envelope requires native surface sites; primitive pairs are not qualified')
    targets=np.where(owner==rows[:,0],rows[:,1],rows[:,0]).astype(int)
    width=translation[owner]+rotation[owner]*rows[:,9]+translation[targets]+rotation[targets]*np.linalg.norm(rows[:,6:9],axis=1)
    width+=64*np.finfo(float).eps*(abs(rows[:,4])+np.linalg.norm(rows[:,6:9],axis=1)+width)
    if not np.isfinite(width).all():raise ValueError('Nonfinite contact travel envelope')
    legacy_lower=np.nextafter(rows[:,4]-width,-np.inf);legacy_upper=np.nextafter(rows[:,4]+width,np.inf)
    selected=np.flatnonzero(~((legacy_lower>0)|(legacy_upper<0)))
    if not len(selected):selected=np.arange(len(rows))
    details=differential[selected];local_owner=owner[selected];local_targets=targets[selected]
    # Correlated translation and world-turn observations at every native site.
    # These are bounds on the declared affine/Cayley path, not native dynamics.
    maps=np.zeros((evaluator.n*6,len(basis.dynamic_dofs)))
    maps[basis.dynamic_dofs,np.arange(len(basis.dynamic_dofs))]=1
    maps=maps.reshape(evaluator.n,6,-1)
    relative_maps=maps[local_owner,:3]-maps[local_targets,:3]
    lever=details[:,6:9];relative=details[:,9:12]
    local_maps=relative_maps-_skew(lever)@maps[local_owner,3:]+_skew(relative)@maps[local_targets,3:]
    rotations=np.array([_rotation(b[10:14]) for b in evaluator.bodies])
    norm_error=abs(np.sum(evaluator.bodies[:,10:14]**2,axis=1)-1)
    if np.any(norm_error>128*np.finfo(float).eps):raise ValueError('Correlated bounds require normalized native orientations')
    local_maps=rotations[local_targets].transpose(0,2,1)@local_maps
    projected=basis.envelope(h,np.concatenate((relative_maps.reshape(-1,len(basis.mass)),local_maps.reshape(-1,len(basis.mass)))))
    split=len(selected)*3
    relative_travel=np.linalg.norm(np.maximum(abs(projected['displacement_lower'][:split]),abs(projected['displacement_upper'][:split])).reshape(-1,3),axis=1)
    # Exact Cayley remainder: ||C(t)-I-[t]x|| <= |t|²/2,
    # ||C(t)-I|| <= min(|t|,2). Include the target-frame cross term.
    angles=np.linalg.norm(travel[:,3:],axis=1)
    remainder=.5*angles[local_owner]**2*np.linalg.norm(lever,axis=1)+.5*angles[local_targets]**2*np.linalg.norm(relative,axis=1)
    remainder+=np.minimum(angles[local_targets],2)*(relative_travel+np.minimum(angles[local_owner],2)*np.linalg.norm(lever,axis=1))
    coordinate=details[:,12:15];extent=details[:,16:19]
    pad=64*np.finfo(float).eps*(abs(coordinate)+extent+np.linalg.norm(relative,axis=1)[:,None]+remainder[:,None])
    pad+=4*(norm_error[local_owner]*np.linalg.norm(lever,axis=1)+norm_error[local_targets]*(np.linalg.norm(relative,axis=1)+relative_travel+2*np.linalg.norm(lever,axis=1)))[:,None]
    dlo=projected['displacement_lower'][split:].reshape(-1,3)-remainder[:,None]-pad
    dhi=projected['displacement_upper'][split:].reshape(-1,3)+remainder[:,None]+pad
    # Avoid subtracting nearly equal absolute coordinates/half extents: native
    # axial gaps retain sub-ULP compression in the origin/displacement state.
    sign=np.where(coordinate<0,-1.,1.);qlow=details[:,31:34]+np.minimum(sign*dlo,sign*dhi)
    qhigh=details[:,31:34]+np.maximum(sign*dlo,sign*dhi)
    crosses=(coordinate+dlo<=0)&(coordinate+dhi>=0)
    qlow=np.where(crosses,-extent,qlow)
    # If the interval crosses zero, its farther endpoint supplies the maximum.
    qhigh=np.where(crosses,np.maximum(abs(coordinate+dlo),abs(coordinate+dhi))-extent,qhigh)
    correlated_lower=_box_gap(qlow);correlated_upper=_box_gap(qhigh)
    plane=details[:,15]==0
    correlated_lower[plane]=rows[selected[plane],4]+dlo[plane,1]
    correlated_upper[plane]=rows[selected[plane],4]+dhi[plane,1]
    if np.any(~((details[:,15]==1)|plane)):raise ValueError('Correlated site bounds require native box or plane targets')
    lower=legacy_lower.copy();upper=legacy_upper.copy()
    lower[selected]=np.maximum(lower[selected],np.nextafter(correlated_lower,-np.inf));upper[selected]=np.minimum(upper[selected],np.nextafter(correlated_upper,np.inf))
    if not np.isfinite(lower).all() or not np.isfinite(upper).all() or np.any(lower>upper):raise ValueError('Inconsistent contact envelopes')
    clear=lower>0;compressed=upper<0;uncertain=~(clear|compressed)
    groups=[]
    for a,b in evaluator.pairs:
        pair_sites=(rows[:,0]==a)&(rows[:,1]==b)
        count=int(np.sum(uncertain&pair_sites))
        if count:groups.append(dict(world_body_ids=[basis.world_body_ids[int(a)],basis.world_body_ids[int(b)]],
            possible_site_changes=count,minimum_lower_gap_m=float(np.min(lower[pair_sites])),maximum_upper_gap_m=float(np.max(upper[pair_sites]))))
    summary=dict(horizon_s=h,native_sites=len(rows),always_separated_sites=int(clear.sum()),
        always_compressed_sites=int(compressed.sum()),possible_contact_changes=int(uncertain.sum()),
        legacy_possible_contact_changes=int(np.sum(~((legacy_lower>0)|(legacy_upper<0)))),
        correlated_sites_checked=len(selected),
        mean_gap_width_ratio=float(np.mean((upper[selected]-lower[selected])/(legacy_upper[selected]-legacy_lower[selected]))),
        bound_method='Correlated native local-point observations with finite Cayley remainder, intersected with absolute travel bounds',
        maximum_rotation_remainder_m=float(np.max(remainder,initial=0)),
        maximum_initial_gap_speed_m_s=float(np.max(abs(np.sum(differential[:,19:25]*evaluator.bodies[rows[:,0].astype(int),14:20]+differential[:,25:31]*evaluator.bodies[rows[:,1].astype(int),14:20],axis=1)),initial=0)),
        body_translation_bound_m=translation.tolist(),body_rotation_chord_bound=rotation.tolist(),
        unresolved_pairs=groups,execution_admitted=False,
        scope='Native site signs conditional on all-mode affine/Cayley geometry; broad SAT, constitutive branches and nonlinear trajectory error not qualified',
        wall_s=time.perf_counter()-started)
    return dict(summary=summary,geometry=rows,native_differential=differential,lower_gap_m=lower,upper_gap_m=upper,envelope=bounds)


def prepare(evaluator, *, source_identity, world_body_ids=None):
    """Compile privately, with an exact state key and an explicit non-admission receipt."""
    from cpu_coupled_world import CpuCoupledEvaluator
    if not isinstance(evaluator, CpuCoupledEvaluator): raise ValueError('Native CPU mode preparation only; no backend fallback')
    started = time.perf_counter(); bodies = evaluator.bodies.copy(); edges = evaluator.edges.copy()
    ids=list(range(evaluator.n)) if world_body_ids is None else list(world_body_ids)
    if len(ids)!=evaluator.n or len(set(ids))!=len(ids) or any(type(i)!=int or not 0<=i<32 for i in ids):raise ValueError('Invalid canonical body mapping')
    e = CpuCoupledEvaluator(bodies.copy(), edges.copy(), pipeline='serial-reference')
    if not 1 <= len(e.dynamic) <= 96: raise ValueError('No bounded dynamic material island to prepare')
    if not e.m: raise ValueError('Mode preparation requires material interfaces')
    baseline = e.evaluate(-bodies[:, 14:20], 1e-6)
    if baseline['faults'][0]: raise ValueError('Native stationary preparation refused')
    force = baseline['forces'][0].ravel(); weights = e.active_weights
    delta = np.array([1e-13 if dof%6 < 3 else 1e-11 for dof in e.dynamic])
    matrices=[]; defects=[]; irreversible=0
    for factor in (1., .5):
        samples, changed = _samples(e, bodies, edges, delta*factor); irreversible += changed
        upper = -(samples[:len(delta)]-force)/(delta[:,None]*factor)
        lower = -(force-samples[len(delta):])/(delta[:,None]*factor)
        matrix = ((upper+lower)/2).T
        matrices.append(matrix)
        scaled = matrix[e.dynamic] / weights[:,None] / weights[None,:]
        sides = (upper-lower).T[e.dynamic] / weights[:,None] / weights[None,:]
        defects.append(float(np.linalg.norm(sides)/max(np.linalg.norm(scaled),1)))
    raw = matrices[-1][e.dynamic]
    scaled = raw / weights[:,None] / weights[None,:]
    coarse = matrices[0][e.dynamic] / weights[:,None] / weights[None,:]
    norm = max(np.linalg.norm(scaled),1)
    symmetry = float(np.linalg.norm(scaled-scaled.T)/norm)
    refinement = float(np.linalg.norm(scaled-coarse)/norm)
    # This is an explicit approximate reference, not a silently modified law.
    symmetric = (raw+raw.T)/2
    represented_mass = np.repeat(bodies[:,1:3],3,axis=1).ravel()[e.dynamic]
    basis = ModeBasis(represented_mass, symmetric, force[e.dynamic], bodies[:,14:20].ravel()[e.dynamic])
    # Retain fixed-body reaction rows and the exact native prestress/history
    # mapping for later transfer work; the active eigensystem alone loses them.
    basis.full_force=force.copy();basis.full_force_tangent=-matrices[-1].copy()
    basis.native_bodies=bodies.copy();basis.native_edges=edges.copy();basis.dynamic_dofs=e.dynamic.copy();basis.world_body_ids=ids
    guard=contact_envelope(basis,e,1/240)
    branch_preparation=prepare_contact_branches(e,bodies,edges,delta)
    identity = hashlib.sha256()
    for a in (bodies,edges):identity.update(a.tobytes())
    identity.update(json.dumps(ids,separators=(',',':')).encode())
    identity.update(source_identity.encode());identity.update(b'banjo.native-mode-preparation.v1/1e-13m/1e-11rad/half')
    values=basis.eigenvalues; peak=float(max(np.max(abs(values)),1))
    uncertain = int(np.sum(abs(values)<=peak*max(refinement,symmetry,64*np.finfo(float).eps)))
    shape_residual = float(np.linalg.norm(basis.scaled@basis.vectors-basis.vectors*values)/max(np.linalg.norm(basis.scaled),1))
    orthogonal = float(np.linalg.norm(basis.vectors.T@basis.vectors-np.eye(len(values))))
    probe = basis.advance(1/240)
    receipt=dict(schema='banjo.native-mode-preparation.v1',state_key=identity.hexdigest(),source_identity=source_identity,
        world_body_ids=ids,dynamic_dofs=len(values),retained_modes=len(values),
        mass_kg=float(bodies[:,1].sum()),inertia_kg_m2=bodies[:,2].tolist(),
        physical_state_unchanged=True,reference='All-mode local affine native-force tangent; symmetrization measured explicitly',
        linearization_symmetry_relative=symmetry,derivative_refinement_relative=refinement,one_sided_derivative_defect=defects,
        derivative_irreversible_changes=irreversible,eigen_residual_relative=shape_residual,orthogonality_residual=orthogonal,
        uncertain_modes=uncertain,negative_eigenvalues=int(np.sum(values<0)),minimum_omega_squared_s2=float(values.min()),maximum_omega_squared_s2=float(values.max()),
        fastest_frequency_rad_s=math.sqrt(max(float(values.max()),0)),
        mass_scaled_force_norm_sqrt_j_per_s=float(np.linalg.norm(force[e.dynamic]/weights)),baseline_contact_energy_j=float(baseline['ledger'][0,4]),
        baseline_material_energy_j=float(baseline['ledger'][0,0]),
        affine_probe_dt_s=1/240,affine_reference_energy_residual_j=probe['reference_energy_residual_j'],
        affine_dynamic_impulse_residual_n_s=float(np.linalg.norm(probe['affine_dynamic_impulse_residual'])),
        contact_branch_preparation=branch_preparation,
        continuous_contact_envelope=guard['summary'],
        execution_admitted=False,reason='Continuous branch/contact bounds, nonlinear trajectory error and full reaction/work transfers are not qualified',
        build_wall_s=time.perf_counter()-started)
    return basis, receipt
