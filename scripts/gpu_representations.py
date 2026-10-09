"""Bounded GPU representation adapter; all mutable matter stays in the host world.

Initial supported reduction: an unattached isotropic sphere under uniform
gravity. The coupled material island remains awake. Swept separation uses
the existing accepted island travel bound; unsupported cases stay coupled.
"""
import copy
import math
import cupy as cp
import numpy as np

FAMILIES=('sleeping','rigid','articulated','reduced-solid','detailed-solid','flowing','thermal','chemical')

KERNEL=r'''
extern "C" __global__ void isolated_sphere_bounds(const double *bodies,unsigned n,unsigned sphere,
    double h,double gy,double accepted_other_travel,double *bounds){
    const unsigned i=blockDim.x*blockIdx.x+threadIdx.x;if(i>=n)return;
    if(i==sphere){bounds[i]=1e300;return;}
    const double *a=bodies+30*sphere,*b=bodies+30*i;
    double v[6];for(unsigned j=0;j<6;++j)v[j]=a[14+j];v[1]+=h*gy;
    const auto p=banjo::dgPrepareTrial(a,v,h);
    const auto d=banjo::dgSub(p.ending.p,p.initial.p);
    const double curve=fabs(gy)*h*h/8; // parabola's deviation from its chord
    const double other_travel=b[1]>0?accepted_other_travel:0;
    if(static_cast<int>(b[0])==0){
        const auto normal=banjo::frameRotate(banjo::dgRead4(b+10),{0,1,0});
        const double first=banjo::frameDot(banjo::dgSub(p.initial.p,banjo::dgRead3(b+7)),normal);
        const double last=banjo::frameDot(banjo::dgSub(p.ending.p,banjo::dgRead3(b+7)),normal);
        bounds[i]=(first<last?first:last)-a[4]-curve-other_travel;return;
    }
    const auto relative=banjo::dgSub(banjo::dgRead3(b+7),p.initial.p);
    const double length2=banjo::frameDot(d,d);
    double t=length2>0?banjo::frameDot(relative,d)/length2:0;t=t<0?0:t>1?1:t;
    const auto closest=banjo::frameAdd(p.initial.p,banjo::frameScale(d,t));
    // An enclosing sphere covers a box at every orientation, including
    // rotations beyond the current angular gate. It does not supply response.
    const double radius=static_cast<int>(b[0])==2?b[4]:sqrt(b[4]*b[4]+b[5]*b[5]+b[6]*b[6]);
    bounds[i]=banjo::dgLength(banjo::dgSub(closest,banjo::dgRead3(b+7)))-a[4]-radius-curve-other_travel;
}
extern "C" __global__ void isolated_sphere_step(const double *bodies,unsigned sphere,double h,double gy,
    double *poses,double *velocity,double *forces,double *residual){
    if(threadIdx.x||blockIdx.x)return;const double *a=bodies+30*sphere;
    double v[6];for(unsigned j=0;j<6;++j)v[j]=a[14+j];v[1]+=h*gy;
    const auto p=banjo::dgPrepareTrial(a,v,h);
    banjo::dgWrite3(poses,p.ending.p);banjo::dgWrite4(poses+3,p.ending.q);
    for(unsigned j=0;j<6;++j){velocity[j]=v[j];forces[j]=j==1?a[1]*gy:0;
        const double mass=j<3?a[1]:a[2];residual[j]=(v[j]-a[14+j])*sqrt(mass)-h*forces[j]/sqrt(mass);}
}
'''

class FlightPartition:
    """One numerical owner per region; derived island buffers are private caches.

    No sleeping assumption, constitutive edits or cross-time outcome reuse.
    A positive swept bound is conditional on the unchanged island travel gate.
    """
    def __init__(self,evaluator,evaluator_type):
        self.world=evaluator;host=cp.asnumpy(evaluator.bodies);edges=cp.asnumpy(evaluator.edges)
        attached=set(edges[:,:2].astype(int).ravel())
        candidates=[i for i,b in enumerate(host) if b[0]==2 and b[1]>0 and i not in attached]
        # A rotating infinite plane has no finite enclosing radius. Its future
        # orientation needs another bound; reject this reduction explicitly.
        admissible_shapes=np.isin(host[:,0],(0,1,2)).all()
        dynamic_plane=np.any((host[:,0]==0)&(host[:,1]>0))
        self.sphere=candidates[0] if len(candidates)==1 and admissible_shapes and not dynamic_plane else None
        self.island=None;self.bounds=cp.empty(evaluator.n,dtype=cp.float64);self.transitions=[]
        self.mode='rigid-coupled-contact';self.reason='No qualified isolated sphere'
        self.bound_kernel=None;self.flight_kernel=None
        if self.sphere is not None:
            self.indices=np.array([i for i in range(evaluator.n) if i!=self.sphere],dtype=np.int32)
            self.device_indices=cp.asarray(self.indices);mapping={int(old):new for new,old in enumerate(self.indices)}
            island_edges=edges.copy()
            for edge in island_edges:edge[:2]=[mapping[int(edge[0])],mapping[int(edge[1])]]
            self.island=evaluator_type(host[self.indices],island_edges,pipeline=evaluator.pipeline,
                newton_strategy=evaluator.newton_strategy,line_search=evaluator.line_search,linear_backend=evaluator.linear_backend)
            # Both modules compile the shared physical trial definitions.
            self.bound_kernel=evaluator.module.get_function('isolated_sphere_bounds')
            self.flight_kernel=evaluator.module.get_function('isolated_sphere_step')
            self.reason='Awaiting swept separation proof'

    def propose(self,h,travel_bound,gravity=-9.81):
        if self.sphere is None:return None
        self.bound_kernel(((self.world.n+127)//128,),(128,),
            (self.world.bodies,np.uint32(self.world.n),np.uint32(self.sphere),np.float64(h),np.float64(gravity),np.float64(travel_bound),self.bounds))
        clearance=float(cp.min(self.bounds))
        # A fixed numerical margin encloses FP64 geometric roundoff; changing
        # this activation margin never changes the contact/material law.
        margin=1e-10
        if not math.isfinite(clearance) or clearance<=margin:return None
        cp.copyto(self.island.bodies,self.world.bodies[self.device_indices])
        cp.copyto(self.island.edges,self.world.edges)
        # Endpoints use island-local indices; the canonical edges keep stable
        # world IDs. Refresh histories, then remap ONLY private cache endpoints.
        if self.island.m:
            endpoints=cp.asnumpy(self.world.edges[:,:2]).astype(int)
            mapping={int(old):new for new,old in enumerate(self.indices)}
            self.island.edges[:,:2]=cp.asarray([[mapping[int(a)],mapping[int(b)]] for a,b in endpoints])
        if len(self.island.dynamic):
            try:out,velocity,iterations,equation=self.island.solve(h,gravity)
            except RuntimeError as error:
                if hasattr(error,'details'):
                    error.details['representation']=dict(mode='material-island',world_body_ids=self.indices.tolist(),sphere_id=self.sphere,separation_lower_bound_m=clearance)
                raise
        else:
            velocity=self.island.bodies[:,14:20].copy();trial=self.island.evaluate(velocity,h,gravity)
            if int(trial['faults'][0]):raise RuntimeError('Fixed island trial refused')
            out={k:trial[k][0].copy() for k in ('poses','residual','history','forces','ledger','faults')}
            iterations=0;equation=0.;self.island.last_solve=dict(strategy='fixed-island',iteration_evaluations=1)
        merged={name:cp.empty((self.world.n,width),dtype=cp.float64) for name,width in (('poses',7),('residual',6),('forces',6))}
        full_velocity=cp.empty((self.world.n,6),dtype=cp.float64)
        for name in merged:merged[name][self.device_indices]=out[name]
        full_velocity[self.device_indices]=velocity
        p=cp.empty(7,dtype=cp.float64);v=cp.empty(6,dtype=cp.float64);f=cp.empty(6,dtype=cp.float64);r=cp.empty(6,dtype=cp.float64)
        self.flight_kernel((1,),(1,),(self.world.bodies,np.uint32(self.sphere),np.float64(h),np.float64(gravity),p,v,f,r))
        merged['poses'][self.sphere]=p;merged['forces'][self.sphere]=f;merged['residual'][self.sphere]=r;full_velocity[self.sphere]=v
        for name in ('history','ledger','faults'):merged[name]=out[name]
        proof=dict(mode='rigid-free-flight',sphere_id=self.sphere,island_body_ids=self.indices.tolist(),
            separation_lower_bound_m=clearance,activation_margin_m=margin,island_travel_bound_m=travel_bound,
            reason='Swept sphere is separated throughout the candidate interval; material island continues solving',
            integration='constant gravity midpoint; reference isotropic-spin Cayley update')
        return merged,full_velocity,iterations,equation,proof

    def commit_modes(self,accounts,start_time):
        elapsed=start_time
        for account in accounts:
            proof=account.get('representation') or dict(mode='rigid-coupled-contact',reason='Swept isolation unavailable; shared contact/material solve')
            if proof['mode']!=self.mode:
                self.transitions.append(dict(time_s=elapsed,from_mode=self.mode,to_mode=proof['mode'],reason=proof['reason'],
                    sphere_id=self.sphere,state_mapping='identity: same matter, poses, velocities and histories; no topology change',
                    topology_transfer=False,audit='No material-state remapping; full accepted substep P/L/energy accounts measure this integration handoff'))
            self.mode=proof['mode'];self.reason=proof['reason'];elapsed+=account['dt_s']

    def safe_rigid_batch(self,dt,maximum=16):
        # Fixed surroundings only; awake material islands have separate work
        # and oscillation budgets that this scheduling hint cannot certify.
        if self.sphere is None or len(self.island.dynamic):return 1
        self.bound_kernel(((self.world.n+127)//128,),(128,),
            (self.world.bodies,np.uint32(self.world.n),np.uint32(self.sphere),np.float64(maximum*dt),np.float64(-9.81),np.float64(0.),self.bounds))
        clearance=float(cp.min(self.bounds))
        return maximum if math.isfinite(clearance) and clearance>1e-10 else 1

    def snapshot(self):
        return dict(schema='banjo.object-representations.v1',policy='partitioned-flight',families=list(FAMILIES),
            sphere_id=self.sphere,mechanical_mode=self.mode,reason=self.reason,transitions=copy.deepcopy(self.transitions),
            ownership='canonical world arrays; derived island caches never own extra matter',
            implemented_scope='isolated isotropic rigid sphere plus continuously solved connected rigid-cell island',
            unsupported=['automatic equilibrium sleep','general articulated mapping','detailed sphere fracture','automatic damaged-fragment coarsening','reduced-solid modes','flowing','thermal','chemical'])
