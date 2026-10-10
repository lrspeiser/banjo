"""Private CPU vibration preparation from the installed native laws.

This compiles a local affine force model, not an admitted world continuation.
No state/history is reset to obtain a tangent and no eigenmode is discarded.
"""
import hashlib
import json
import math
import time
import numpy as np


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

    def envelope(self, h):
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
        return result


def _samples(evaluator, bodies, edges, delta):
    """Reach each private sample along a real native trial, then read its force.

    Assigning a perturbed pose while leaving old material history in place is
    invalid: it creates work with no motion. The first trial transfers history
    to that pose; the stationary trial reads the corresponding endpoint force.
    """
    e = evaluator; n = len(e.dynamic); velocities = np.repeat((-bodies[:, 14:20])[None], 2*n, axis=0)
    for j, dof in enumerate(e.dynamic):
        velocities[j, dof//6, dof%6] += 2*delta[j]/1e-6
        velocities[n+j, dof//6, dof%6] -= 2*delta[j]/1e-6
    path = e.evaluate(velocities, 1e-6)
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
            out = e.evaluate(e.bodies[:, 14:20], 1e-6)
            if out['faults'][0]: raise ValueError('Native stationary derivative sample refused')
            forces.append(out['forces'][0].ravel().copy())
    finally:
        e.bodies[:] = bodies; e.edges[:] = edges
    return np.asarray(forces), irreversible_changes


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
    rows=evaluator.contact_geometry();owner=rows[:,3].astype(int)
    if np.any(owner<0):raise ValueError('Affine contact envelope requires native surface sites; primitive pairs are not qualified')
    targets=np.where(owner==rows[:,0],rows[:,1],rows[:,0]).astype(int)
    width=translation[owner]+rotation[owner]*rows[:,9]+translation[targets]+rotation[targets]*np.linalg.norm(rows[:,6:9],axis=1)
    width+=64*np.finfo(float).eps*(abs(rows[:,4])+np.linalg.norm(rows[:,6:9],axis=1)+width)
    if not np.isfinite(width).all():raise ValueError('Nonfinite contact travel envelope')
    lower=np.nextafter(rows[:,4]-width,-np.inf);upper=np.nextafter(rows[:,4]+width,np.inf)
    clear=lower>0;compressed=upper<0;uncertain=~(clear|compressed)
    groups=[]
    for a,b in evaluator.pairs:
        selected=(rows[:,0]==a)&(rows[:,1]==b)
        count=int(np.sum(uncertain&selected))
        if count:groups.append(dict(world_body_ids=[basis.world_body_ids[int(a)],basis.world_body_ids[int(b)]],
            possible_site_changes=count,minimum_lower_gap_m=float(np.min(lower[selected])),maximum_upper_gap_m=float(np.max(upper[selected]))))
    summary=dict(horizon_s=h,native_sites=len(rows),always_separated_sites=int(clear.sum()),
        always_compressed_sites=int(compressed.sum()),possible_contact_changes=int(uncertain.sum()),
        body_translation_bound_m=translation.tolist(),body_rotation_chord_bound=rotation.tolist(),
        unresolved_pairs=groups,execution_admitted=False,
        scope='Native site signs conditional on all-mode affine/Cayley geometry; broad SAT, constitutive branches and nonlinear trajectory error not qualified',
        wall_s=time.perf_counter()-started)
    return dict(summary=summary,geometry=rows,lower_gap_m=lower,upper_gap_m=upper,envelope=bounds)


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
        continuous_contact_envelope=guard['summary'],
        execution_admitted=False,reason='Continuous branch/contact bounds, nonlinear trajectory error and full reaction/work transfers are not qualified',
        build_wall_s=time.perf_counter()-started)
    return basis, receipt
