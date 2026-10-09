"""Backend-independent ownership and swept admission for isolated rigid flight."""
import copy,math
import numpy as np
FAMILIES=('sleeping','rigid','articulated','reduced-solid','detailed-solid','flowing','thermal','chemical')

class FlightPartition:
    """One numerical owner per region; derived island buffers are private caches.

    No sleeping assumption, constitutive edits or cross-time outcome reuse.
    A positive swept bound is conditional on the unchanged island travel gate.
    """
    def __init__(self,evaluator,evaluator_type):
        self.world=evaluator;self.xp=evaluator.array_api;self.to_host=evaluator.to_host;host=self.to_host(evaluator.bodies);edges=self.to_host(evaluator.edges)
        attached=set(edges[:,:2].astype(int).ravel())
        candidates=[i for i,b in enumerate(host) if b[0]==2 and b[1]>0 and i not in attached]
        # A rotating infinite plane has no finite enclosing radius. Its future
        # orientation needs another bound; reject this reduction explicitly.
        admissible_shapes=np.isin(host[:,0],(0,1,2)).all()
        dynamic_plane=np.any((host[:,0]==0)&(host[:,1]>0))
        self.sphere=candidates[0] if len(candidates)==1 and admissible_shapes and not dynamic_plane else None
        self.island=None;self.bounds=self.xp.empty(evaluator.n,dtype=self.xp.float64);self.transitions=[]
        self.mode='rigid-coupled-contact';self.reason='No qualified isolated sphere'
        if self.sphere is not None:
            self.indices=np.array([i for i in range(evaluator.n) if i!=self.sphere],dtype=np.int32)
            self.device_indices=self.xp.asarray(self.indices);mapping={int(old):new for new,old in enumerate(self.indices)}
            island_edges=edges.copy()
            for edge in island_edges:edge[:2]=[mapping[int(edge[0])],mapping[int(edge[1])]]
            self.island=evaluator_type(host[self.indices],island_edges,pipeline=evaluator.pipeline,
                newton_strategy=evaluator.newton_strategy,line_search=evaluator.line_search,linear_backend=evaluator.linear_backend)
            self.reason='Awaiting swept separation proof'

    def propose(self,h,travel_bound,gravity=-9.81):
        if self.sphere is None:return None
        self.world.flight_bounds(self.sphere,h,gravity,travel_bound,self.bounds)
        clearance=float(self.xp.min(self.bounds))
        # A fixed numerical margin encloses FP64 geometric roundoff; changing
        # this activation margin never changes the contact/material law.
        margin=1e-10
        if not math.isfinite(clearance) or clearance<=margin:return None
        self.xp.copyto(self.island.bodies,self.world.bodies[self.device_indices])
        self.xp.copyto(self.island.edges,self.world.edges)
        # Endpoints use island-local indices; the canonical edges keep stable
        # world IDs. Refresh histories, then remap ONLY private cache endpoints.
        if self.island.m:
            endpoints=self.to_host(self.world.edges[:,:2]).astype(int)
            mapping={int(old):new for new,old in enumerate(self.indices)}
            self.island.edges[:,:2]=self.xp.asarray([[mapping[int(a)],mapping[int(b)]] for a,b in endpoints])
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
        merged={name:self.xp.empty((self.world.n,width),dtype=self.xp.float64) for name,width in (('poses',7),('residual',6),('forces',6))}
        full_velocity=self.xp.empty((self.world.n,6),dtype=self.xp.float64)
        for name in merged:merged[name][self.device_indices]=out[name]
        full_velocity[self.device_indices]=velocity
        p=self.xp.empty(7,dtype=self.xp.float64);v=self.xp.empty(6,dtype=self.xp.float64);f=self.xp.empty(6,dtype=self.xp.float64);r=self.xp.empty(6,dtype=self.xp.float64)
        self.world.flight_step(self.sphere,h,gravity,p,v,f,r)
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
        self.world.flight_bounds(self.sphere,maximum*dt,-9.81,0.,self.bounds)
        clearance=float(self.xp.min(self.bounds))
        return maximum if math.isfinite(clearance) and clearance>1e-10 else 1

    def snapshot(self):
        return dict(schema='banjo.object-representations.v1',policy='partitioned-flight',families=list(FAMILIES),
            sphere_id=self.sphere,mechanical_mode=self.mode,reason=self.reason,transitions=copy.deepcopy(self.transitions),
            ownership='canonical world arrays; derived island caches never own extra matter',
            implemented_scope='isolated isotropic rigid sphere plus continuously solved connected rigid-cell island',
            unsupported=['automatic equilibrium sleep','general articulated mapping','detailed sphere fracture','automatic damaged-fragment coarsening','reduced-solid modes','flowing','thermal','chemical'])
