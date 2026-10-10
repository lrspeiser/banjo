"""Backend-independent canonical world, material state and admission transaction."""
from pathlib import Path
import copy,json,math,time
import numpy as np
from coupled_solver import TrialFailure
from object_registry import ObjectRegistry,CHECKPOINT_SCHEMA,open_checkpoint,seal
ROOT=Path(__file__).resolve().parents[1]

def declaration(raw,*,device="cuda:0",pipeline="parallel",linear="cupy-reference",pipelines=("parallel","serial-reference"),linears=("cupy-reference","native-cusolver"),representations=("coupled-reference","partitioned-flight")):
    defaults=dict(material='glass',ball_material='iron',ball_mass_kg=.01,height_m=.02,dt_s=1/960,experiment='sheet',device=device,pipeline=pipeline,newton_strategy='ranked',line_search='batch-tail',linear_backend=linear,contact_resolution='reference',representation_policy='coupled-reference')
    if not isinstance(raw,dict) or set(raw)-set(defaults):raise ValueError('Unknown coupled scene field')
    d=defaults|raw
    if d['device']!=device or d['experiment'] not in ('sheet','freefall'):raise ValueError('Only the explicit selected device and sheet/freefall experiments are admitted')
    if d['pipeline'] not in pipelines:raise ValueError('Unknown coupled trial pipeline')
    if d['newton_strategy'] not in ('ranked','single-reference'):raise ValueError('Unknown Newton starting strategy')
    if d['line_search'] not in ('batch-tail','serial-reference'):raise ValueError('Unknown Newton line search')
    if d['linear_backend'] not in linears:raise ValueError('Unknown coupled linear backend')
    if d['contact_resolution'] not in ('reference','phase-0.25','phase-0.125','phase-0.0625'):raise ValueError('Unknown contact timestep policy')
    if d['representation_policy'] not in representations:raise ValueError('Unknown representation policy')
    for name in ('material','ball_material'):
        if d[name] not in ('glass','oak','iron','ice'):raise ValueError('Unknown declared material')
    for name,lo,hi in (('ball_mass_kg',.001,1.),('height_m',.001,10.)):
        if type(d[name]) not in (float,int) or not math.isfinite(d[name]) or not lo<=d[name]<=hi:raise ValueError('Invalid '+name)
    if type(d['dt_s']) not in (float,int) or d['dt_s'] not in (1/240,1/480,1/960,1/1920):raise ValueError('Unadmitted coupled host timestep')
    return d

class CoupledWorld:
    def __init__(self,raw,*,world_id=None):
        self.ensure_source_current()
        self.d=self.declaration(raw);profiles=json.loads((ROOT/'client/voxel-lab/material-laws.json').read_text(encoding='utf8'))['profiles'];profiles={p['material']:p for p in profiles}
        self.meta=[];bodies=[];edges=[];cell=.01;material=profiles[self.d['material']]
        self.material_model=material['display_model']
        def body(shape,p,pos,half,mass=None,fixed=False):
            volume=4*math.pi*half[0]**3/3 if shape==2 else 8*np.prod(half)
            m=mass if mass is not None else p['density_kg_m3']*volume
            inertia=.4*m*half[0]**2 if shape==2 else m*(2*half[0])**2/6
            row=np.zeros(30);row[:4]=[shape,0 if fixed else m,0 if fixed else inertia,p['young_pa']];row[4:7]=half;row[7:10]=row[20:23]=pos;row[10]=row[26]=1
            i=len(bodies);bodies.append(row);self.meta.append(dict(id=i,shape=('plane','cube','sphere')[shape],material=p['material'],size_m=(2*np.array(half)).tolist(),radius_m=half[0] if shape==2 else 0,mass_kg=0 if fixed else m,fixed=fixed,component=i+1));return i
        body(0,profiles['iron'],[0,0,0],[.01]*3,fixed=True)
        if self.d['experiment']=='sheet':
            for x in (-.012,.012):body(1,profiles['iron'],[x,.0125,0],[.004,.0125,.022],fixed=True)
            indices={}
            for x in range(3):
                for z in range(3):indices[x,z]=body(1,material,[(x-1)*cell,.03,(z-1)*cell],[cell/2]*3)
            for (x,z),a in indices.items():
                for axis in (0,2):
                    neighbor=(x+1,z) if axis==0 else (x,z+1)
                    if neighbor not in indices:continue
                    b=indices[neighbor];frame=[1,0,0,0] if axis==0 else [math.sqrt(.5),0,-math.sqrt(.5),0]
                    sites=[(0.,0.)] if material['display_model']=='connector-plastic' else [(u*cell/(2*math.sqrt(3)),v*cell/(2*math.sqrt(3))) for u in (-1,1) for v in (-1,1)]
                    for u,v in sites:
                        row=np.zeros(70);row[:4]=[a,b,1 if material['display_model']=='connector-plastic' else 2,cell]
                        local_a=np.zeros(3);local_b=np.zeros(3);local_a[axis]=cell/2;local_b[axis]=-cell/2
                        local_a[1]=local_b[1]=u;local_a[2 if axis==0 else 0]=local_b[2 if axis==0 else 0]=v
                        row[4:7]=local_a;row[7:10]=local_b;row[10:14]=row[14:18]=frame;row[18:23]=material['cohesive_law'];row[21]/=len(sites)
                        if material['display_model']=='connector-plastic':row[23:29]=material['connector_stiffness'];row[29:35]=material['connector_yield_load']
                        else:row[23]=.5 # Explicit kt/kn experiment input, not grain or inferred bulk plasticity.
                        edges.append(row)
        p=profiles[self.d['ball_material']];radius=(3*self.d['ball_mass_kg']/(4*math.pi*p['density_kg_m3']))**(1/3)
        body(2,p,[0,(.035 if self.d['experiment']=='sheet' else 0)+radius+self.d['height_m'],0],[radius]*3,mass=self.d['ball_mass_kg'])
        self.eval=self.evaluator_type(bodies,edges,pipeline=self.d['pipeline'],newton_strategy=self.d['newton_strategy'],line_search=self.d['line_search'],linear_backend=self.d['linear_backend']);self.ticks=0;self.time=0.;self.step_s=0.;self.last_ms=0.;self.histories=np.zeros((len(edges),32))
        self.representations=self.flight_partition(self.eval,self.evaluator_type) if self.d['representation_policy']=='partitioned-flight' else None
        self.registry=ObjectRegistry(np.array(bodies),np.array(edges).reshape(-1,70),self.meta,profiles,world_id)
        self.unattached_spheres=[o['body_ids'][0] for o in self.registry.binding_state()['instances'] if o['single_sphere']]
        self.P_ground=np.zeros(3);self.L_ground=np.zeros(3);self.max_residual=0.;self.fracture=self.plastic=self.return_excess=0.;self.total_iterations=0;self.microsteps=0
        baseline=self.eval.evaluate(self.eval.bodies[:,14:20],1e-12,gravity=0)
        if int(baseline['faults'][0]):raise RuntimeError('Invalid initial coupled energy state')
        ledger=self.to_host(baseline['ledger'])[0];self.stored_j=float(ledger[0]);self.contact_j=float(ledger[4])
        self.initial_energy=self.mechanics(np.array(bodies))[0]+self.stored_j+self.contact_j
        self.last_accounts=[];self.rejected=None;self.hash=self.source_hash();self.accepted=self._snapshot(np.array(bodies))

    @staticmethod
    def mechanics(bodies):
        mass=bodies[:,1];energy=.5*np.sum(mass[:,None]*bodies[:,14:17]**2)+.5*np.sum(bodies[:,2,None]*bodies[:,17:20]**2)+9.81*np.sum(mass*bodies[:,8])
        p=np.sum(mass[:,None]*bodies[:,14:17],axis=0);l=np.sum(np.cross(bodies[:,7:10],mass[:,None]*bodies[:,14:17])+bodies[:,2,None]*bodies[:,17:20],axis=0)
        return float(energy),p,l

    def advance(self,steps):
        if self.rejected:raise ValueError('Refused coupled world is stopped; reset required')
        if type(steps) is not int or not 1<=steps<=32 or self.ticks+steps>round(2/self.d['dt_s']):raise ValueError('Invalid coupled advance')
        saved_b=self.eval.bodies.copy();saved_e=self.eval.edges.copy()
        # Publication is part of the transaction: a failure while constructing
        # the accepted snapshot must also restore clocks/accounts/mode history.
        host_keys=('histories','ticks','time','microsteps','total_iterations','fracture','plastic','return_excess',
            'P_ground','L_ground','max_residual','last_accounts','stored_j','contact_j','last_ms','step_s','accepted')
        saved_host={key:(getattr(self,key).copy() if isinstance(getattr(self,key),np.ndarray) else getattr(self,key)) for key in host_keys}
        saved_modes=(self.representations.mode,self.representations.reason,copy.deepcopy(self.representations.transitions)) if self.representations else None
        saved_registry=self.registry.binding_state()
        accounts=[];started=time.perf_counter();updates=0;trials=0;refusals=[];last_solver_failure=None;schedule=None
        try:
            for host_tick in range(steps):
                queue=[(self.d['dt_s'],0)]
                while queue:
                    trials+=1
                    if trials>128 or time.perf_counter()-started>30:raise TrialFailure('Coupled interval trial/time budget')
                    h,depth=queue.pop();schedule=None
                    if self.d['contact_resolution']!='reference':
                        schedule=self.eval.contact_schedule(h,float(self.d['contact_resolution'].split('-')[1]))
                        if schedule['step_s']<h:
                            remainder=h-schedule['step_s'];h=schedule['step_s']
                            if remainder>0:queue.append((remainder,depth))
                    before=self.to_host(self.eval.bodies);energy0,p0,l0=self.mechanics(before)
                    scale=float(np.min(2*before[before[:,0]!=0,4:7]));representation=None;coordinate_rebases=[]
                    try:
                        flight=self.representations.propose(h,.25*scale) if self.representations else None
                        if flight is None:
                            coordinate_rebases=self.local_primitive_origins(before)
                            out,velocity,iterations,equation=self.eval.solve(h)
                        else:
                            out,velocity,iterations,equation,representation=flight
                            self.eval.last_solve=copy.deepcopy(self.representations.island.last_solve)
                    except TrialFailure as error:
                        last_solver_failure=error.details
                        refusals.append(dict(trial=trials,dt_s=h,depth=depth,error=str(error),
                            private_elapsed_s=sum(a['dt_s'] for a in accounts),
                            equation_residual=(error.details.get('iterations') or [{}])[-1].get('equation_residual')))
                        if depth>=10:raise
                        queue.extend([(h/2,depth+1),(h/2,depth+1)]);continue
                    ending=before.copy();ending[:,7:14]=self.to_host(out['poses']);ending[:,14:20]=self.to_host(velocity)
                    ending[:,23:26]=before[:,23:26]+h*(before[:,14:17]+ending[:,14:17])/2
                    ledger=self.to_host(out['ledger']);forces=self.to_host(out['forces']);history=self.to_host(out['history']);energy1,p1,l1=self.mechanics(ending)
                    fixed=before[:,1]==0;reaction=-h*forces[fixed,:3].sum(axis=0)
                    midpoint=(before[:,7:10]+ending[:,7:10])/2
                    reaction_torque=-h*(np.cross(midpoint[fixed],forces[fixed,:3])+forces[fixed,3:]).sum(axis=0)
                    gravity_impulse=np.array([0,-9.81*before[:,1].sum()*h,0]);gravity_torque=h*np.cross(midpoint,before[:,1,None]*[0,-9.81,0]).sum(axis=0)
                    balance=energy1-energy0+ledger[1]-ledger[0]+ledger[2]+ledger[3]+ledger[5]-ledger[4]
                    pres=p1-p0-reaction-gravity_impulse;lres=l1-l0-reaction_torque-gravity_torque
                    tolerance=1e-10+1e-8*max(abs(energy0+ledger[0]+ledger[4]),1e-3)
                    displacements=np.linalg.norm(ending[:,7:10]-before[:,7:10],axis=1)
                    # The separated sphere has its own swept proof. The unchanged
                    # travel bound still applies to every coupled island member.
                    guarded=np.delete(displacements,self.representations.sphere) if representation else displacements
                    travel=float(np.max(guarded,initial=0))
                    angles=h*np.max(np.linalg.norm((ending[:,17:20]+before[:,17:20])/2,axis=1))
                    # Conservative displacement guard prevents the tiny sheet
                    # from being skipped; CCD/event location is not qualified.
                    if abs(balance)>tolerance or np.linalg.norm(pres)>1e-9 or np.linalg.norm(lres)>1e-9 or ledger[8]>.2*scale or travel>.25*scale or angles>.25:
                        refusals.append(dict(trial=trials,dt_s=h,depth=depth,error='Coupled finite/compression/travel/conservation gate',
                            private_elapsed_s=sum(a['dt_s'] for a in accounts),energy_residual_j=balance,energy_tolerance_j=tolerance,
                            P_residual_n_s=pres.tolist(),L_residual_n_m_s=lres.tolist(),compression_m=float(ledger[8]),
                            maximum_compression_m=.2*scale,travel_m=travel,maximum_travel_m=.25*scale,turn_rad=float(angles),maximum_turn_rad=.25))
                        if depth>=10:raise TrialFailure('Coupled finite/compression/travel/conservation gate')
                        queue.extend([(h/2,depth+1),(h/2,depth+1)]);continue
                    updates+=1
                    if updates>512 or time.perf_counter()-started>30:raise TrialFailure('Coupled interval work budget')
                    self.eval.bodies[:,23:26]+=h*(self.eval.bodies[:,14:17]+velocity[:,:3])/2
                    self.eval.bodies[:,7:14]=out['poses'];self.eval.bodies[:,14:20]=velocity
                    if self.eval.m:self.eval.edges[:,35:67]=out['history']
                    # Read-only visualization receipt from the accepted native
                    # midpoint wrench. Remove gravity, retaining contact AND
                    # interface resultants. This is not a resolved stress field.
                    interaction=forces.copy();interaction[:,1]+=9.81*before[:,1]
                    accounts.append(dict(dt_s=h,energy_residual_j=balance,energy_tolerance_j=tolerance,P_residual_n_s=pres.tolist(),L_residual_n_m_s=lres.tolist(),
                        interaction_wrench_n_nm=interaction.tolist(),
                        ground_impulse_n_s=reaction.tolist(),ground_torque_impulse_n_m_s=reaction_torque.tolist(),ledger=ledger.tolist(),iterations=iterations,equation_residual=equation,
                        poses_wxyz=ending[:,7:14].tolist(),velocities=ending[:,14:20].tolist(),material_history=history.tolist(),newton_start=copy.deepcopy(self.eval.last_solve),contact_schedule=schedule,
                        coordinate_rebases=coordinate_rebases,
                        **({'representation':representation} if self.representations else {})))
            self.histories=history;self.ticks+=steps;self.time+=steps*self.d['dt_s'];self.microsteps+=updates;self.total_iterations+=sum(a['iterations'] for a in accounts)
            self.fracture+=sum(a['ledger'][2] for a in accounts) if self.material_model!='connector-plastic' else 0
            self.plastic+=sum(a['ledger'][2] for a in accounts) if self.material_model=='connector-plastic' else 0
            self.return_excess+=sum(a['ledger'][3] for a in accounts)
            self.P_ground+=sum((np.array(a['ground_impulse_n_s']) for a in accounts),start=np.zeros(3));self.L_ground+=sum((np.array(a['ground_torque_impulse_n_m_s']) for a in accounts),start=np.zeros(3))
            self.max_residual=max(self.max_residual,max(abs(a['energy_residual_j']) for a in accounts));self.last_accounts=accounts
            self.stored_j=float(ledger[1]);self.contact_j=float(ledger[5])
            if self.representations:self.representations.commit_modes(accounts,self.time-steps*self.d['dt_s'])
            sphere=self.representations.sphere if self.representations and self.representations.mode=='rigid-free-flight' else None
            self.registry.bind(self.time,sphere)
            self.last_ms=(time.perf_counter()-started)*1000;self.step_s+=self.last_ms/1000;self.accepted=self._snapshot(ending);return self.snapshot()
        except Exception as error:
            restored=False
            try:self.array_api.copyto(self.eval.bodies,saved_b);self.array_api.copyto(self.eval.edges,saved_e);self.synchronize();restored=True
            except Exception:pass # A poisoned CUDA context cannot confirm GPU rollback.
            for key,value in saved_host.items():setattr(self,key,value)
            if saved_modes:self.representations.mode,self.representations.reason,self.representations.transitions=saved_modes
            self.registry.restore_bindings(saved_registry)
            self.rejected=dict(error=str(error),accepted_time_s=self.time,interval_rolled_back=restored,accepted_snapshot_preserved=True,
                failed_interval_substeps=updates,trial_attempts=trials,subdivision_refusals=refusals,
                last_solver_failure=last_solver_failure,last_trial_accounts=accounts[-4:],contact_timestep_policy=self.d['contact_resolution'],
                last_contact_schedule=schedule,failed_interval_physical_s=sum(a['dt_s'] for a in accounts))
            raise RuntimeError(str(error)) from error

    def local_primitive_origins(self,bodies):
        # A primitive without an interface has no material rest reference to
        # move. Recenter only its numerical translation basis; geometry,
        # motion, inertia, all histories and physical clocks remain identical.
        # Connected cells keep the native stable-coordinate reference intact.
        receipts=[]
        for i in self.unattached_spheres:
            b=bodies[i]
            if np.array_equal(b[20:23],b[7:10]) and not np.any(b[23:26]):continue
            receipts.append(dict(body_id=i,from_origin_m=b[20:23].tolist(),from_increment_m=b[23:26].tolist(),to_origin_m=b[7:10].tolist(),
                mapping='Identity physical state; unattached primitive translation basis only',mass_error_kg=0.,P_error_n_s=[0.,0.,0.],L_error_n_m_s=[0.,0.,0.],mechanical_error_j=0.,history_mapping='unchanged'))
            b[20:23]=b[7:10];b[23:26]=0
            self.eval.bodies[i,20:26]=self.array_api.asarray(b[20:26])
        return receipts

    def _snapshot(self,bodies):
        energy,p,l=self.mechanics(bodies);cells=[]
        for row,b in zip(self.meta,bodies):cells.append(row|dict(position_m=b[7:10].tolist(),quaternion_wxyz=b[10:14].tolist(),velocity_m_s=b[14:17].tolist(),angular_velocity_rad_s=b[17:20].tolist()))
        kinds=self.to_host(self.eval.edges[:,2]).astype(int) if self.eval.m else []
        separated=int(sum(s[6]>0 for k,s in zip(kinds,self.histories) if k!=1));yielded=int(sum(s[14]>0 for k,s in zip(kinds,self.histories) if k==1))
        return dict(schema=self.state_schema,declaration=copy.deepcopy(self.d),time_s=self.time,dt_s=self.d['dt_s'],ticks=self.ticks,cells=cells,history_arrays=self.histories.tolist(),objects=self.registry.summary(),
            diagnostics=dict(dynamic_mass_kg=float(bodies[:,1].sum()),mechanical_j=energy,material_stored_j=self.stored_j,contact_stored_j=self.contact_j,
                global_energy_residual_j=energy+self.stored_j+self.contact_j+self.fracture+self.plastic+self.return_excess-self.initial_energy,
                momentum_n_s=p.tolist(),angular_momentum_n_m_s=l.tolist(),
                fracture_work_j=self.fracture,plastic_work_j=self.plastic,numerical_return_excess_j=self.return_excess,separated_sites=separated,yielded_faces=yielded,interfaces=self.eval.m,
                maximum_energy_residual_j=self.max_residual,ground_impulse_n_s=self.P_ground.tolist(),ground_torque_impulse_n_m_s=self.L_ground.tolist()),
            substep_accounts=copy.deepcopy(self.last_accounts),performance=dict(pipeline=self.eval.pipeline,newton_strategy=self.eval.newton_strategy,line_search=self.eval.line_search,linear_backend=self.eval.linear_backend,contact_resolution=self.d['contact_resolution'],step_s=self.step_s,last_batch_ms=self.last_ms,compute_ratio=self.time/self.step_s if self.step_s else None,
                microsteps=self.microsteps,nonlinear_iterations=self.total_iterations,trial_evaluations=self.eval.evaluations+(self.representations.island.evaluations if self.representations and self.representations.island else 0)),
            **({'representations':self.representations.snapshot(),
                'render_schedule':dict(safe_rigid_flight_steps=self.representations.safe_rigid_batch(self.d['dt_s']),
                    scope='Swept collision-free rigid sphere with fixed surroundings only; coupled material worlds request one host tick')}
                if self.representations else {}),
            qualification=dict(backend=self.backend_name,gpu=self.gpu,device=self.device,dtype='float64',source_sha256=self.hash,complete_physics_validated=False,realtime_qualified=False,
                scope='Experimental finite rigid-cell isotropic inertia; declared mixed-mode cohesive/6-mode plastic interfaces and frictionless normal compliance. No calibrated bulk/grain/J2/thermal law or CCD qualification.'))

    def snapshot(self):
        out=copy.deepcopy(self.accepted)
        if self.rejected:out['rejected_candidate']=copy.deepcopy(self.rejected)
        return out

    CHECKPOINT_FIELDS=('histories','ticks','time','microsteps','total_iterations','fracture','plastic','return_excess',
        'P_ground','L_ground','max_residual','stored_j','contact_j','initial_energy','last_ms','step_s')

    def export_checkpoint(self):
        if self.rejected and not self.rejected['interval_rolled_back']:raise ValueError('Cannot save unconfirmed native rollback; retain the experiment journal')
        continuation={key:(getattr(self,key).tolist() if isinstance(getattr(self,key),np.ndarray) else getattr(self,key)) for key in self.CHECKPOINT_FIELDS}
        bindings=dict(mode=self.representations.mode,reason=self.representations.reason,transitions=copy.deepcopy(self.representations.transitions)) if self.representations else None
        stopped={k:copy.deepcopy(self.rejected[k]) for k in ('error','accepted_time_s','interval_rolled_back','accepted_snapshot_preserved')} if self.rejected else None
        return seal(dict(schema=CHECKPOINT_SCHEMA,source_sha256=self.hash,declaration=copy.deepcopy(self.d),registry=self.registry.document(),
            native=dict(bodies=self.to_host(self.eval.bodies).tolist(),edges=self.to_host(self.eval.edges).tolist()),continuation=continuation,
            representation=bindings,trial_evaluations=self.snapshot()['performance']['trial_evaluations'],stopped_failure=stopped,
            scope='Exact accepted native state; private caches rebuilt. Past render frames/full rejection witnesses remain in the original journal.'))

    @classmethod
    def from_checkpoint(cls,payload):
        saved=open_checkpoint(payload)
        expected={'schema','source_sha256','declaration','registry','native','continuation','representation','trial_evaluations','stopped_failure','scope'}
        if set(saved)!=expected or saved['source_sha256']!=cls.source_hash():raise ValueError('Checkpoint schema or physics source is stale')
        # Construct privately. The worker installs it after every check passes.
        candidate=cls(saved['declaration'],world_id=saved['registry']['world_id'])
        native=saved['native'];state=saved['continuation']
        if set(native)!={'bodies','edges'} or set(state)!=set(cls.CHECKPOINT_FIELDS):raise ValueError('Incomplete native continuation')
        b=np.asarray(native['bodies'],dtype=np.float64);e=np.asarray(native['edges'],dtype=np.float64).reshape(-1,70)
        initial_b=cls.to_host(candidate.eval.bodies);initial_e=cls.to_host(candidate.eval.edges)
        if b.shape!=initial_b.shape or e.shape!=initial_e.shape or not np.isfinite(b).all() or not np.isfinite(e).all():raise ValueError('Invalid native state arrays')
        immutable=[*range(7),*range(26,30)];referenced=[i for i in range(len(b)) if i not in candidate.unattached_spheres]
        if not np.array_equal(b[:,immutable],initial_b[:,immutable]) or not np.array_equal(b[referenced,20:23],initial_b[referenced,20:23]) or not np.array_equal(e[:,:35],initial_e[:,:35]) or not np.array_equal(e[:,67:],initial_e[:,67:]):raise ValueError('Checkpoint changes geometry, material, law or native rest mapping')
        fixed=b[:,1]==0
        if not np.array_equal(b[fixed,7:20],initial_b[fixed,7:20]) or np.max(abs(np.linalg.norm(b[:,10:14],axis=1)-1))>1e-10:raise ValueError('Invalid prescribed boundary or orientation')
        if np.max(abs(b[:,7:10]-(b[:,20:23]+b[:,23:26])))>1e-12:raise ValueError('Inconsistent native reference position')
        for edge in e:
            history=edge[35:67]
            if edge[2]==1:
                if np.any(history[6:16]<0) or history[14]!=int(history[14]):raise ValueError('Invalid plastic history')
            elif history[1]<max(0,history[0]) or np.any(history[3:5]<0) or not 0<=history[5]<=1 or history[6] not in (0,1):raise ValueError('Invalid cohesive history')
        for key in cls.CHECKPOINT_FIELDS:
            value=state[key]
            if key in ('histories','P_ground','L_ground'):
                value=np.asarray(value,dtype=float)
                if key=='histories':value=value.reshape(-1,32)
                shape=(e.shape[0],32) if key=='histories' else (3,)
                if value.shape!=shape or not np.isfinite(value).all():raise ValueError('Invalid continuation array')
            elif key in ('ticks','microsteps','total_iterations'):
                if type(value) is not int or value<0:raise ValueError('Invalid continuation counter')
            elif type(value) not in (int,float) or not math.isfinite(value):raise ValueError('Invalid continuation scalar')
            elif key not in ('initial_energy','stored_j','contact_j') and value<0:raise ValueError('Negative continuation account')
            setattr(candidate,key,value)
        if candidate.ticks>round(2/candidate.d['dt_s']) or abs(candidate.time-candidate.ticks*candidate.d['dt_s'])>1e-12:raise ValueError('Inconsistent accepted clock')
        if not np.array_equal(candidate.histories,e[:,35:67]):raise ValueError('Material history map differs')
        candidate.registry.restore_document(saved['registry'])
        if abs(candidate.registry.time_s-candidate.time)>1e-14:raise ValueError('Object/physics clocks differ')
        mode=saved['representation']
        if bool(mode)!=bool(candidate.representations):raise ValueError('Representation continuation differs')
        if mode:
            if set(mode)!={'mode','reason','transitions'} or mode['mode'] not in ('rigid-free-flight','rigid-coupled-contact') or not isinstance(mode['reason'],str) or not isinstance(mode['transitions'],list):raise ValueError('Unsupported representation continuation')
            candidate.representations.mode=mode['mode'];candidate.representations.reason=mode['reason'];candidate.representations.transitions=copy.deepcopy(mode['transitions'])
        sphere=candidate.representations.sphere if mode and mode['mode']=='rigid-free-flight' else None
        for instance in candidate.registry.binding_state()['instances']:
            owner='isolated-rigid-flight' if sphere is not None and instance['body_ids']==[sphere] else 'coupled-world'
            if instance['solver_binding']!=owner:raise ValueError('Representation has duplicate or mismatched matter owner')
        cls.array_api.copyto(candidate.eval.bodies,cls.array_api.asarray(b));cls.array_api.copyto(candidate.eval.edges,cls.array_api.asarray(e))
        baseline=candidate.eval.evaluate(candidate.eval.bodies[:,14:20],1e-12,gravity=0)
        if int(baseline['faults'][0]):raise ValueError('Restored native geometry/history refused')
        ledger=cls.to_host(baseline['ledger'])[0]
        if abs(ledger[0]-candidate.stored_j)>1e-10+1e-8*abs(candidate.stored_j) or abs(ledger[4]-candidate.contact_j)>1e-10+1e-8*abs(candidate.contact_j):raise ValueError('Restored storage account differs')
        evaluations=saved['trial_evaluations']
        if type(evaluations) is not int or evaluations<0:raise ValueError('Invalid solver continuation counter')
        candidate.eval.evaluations=evaluations
        if candidate.representations and candidate.representations.island:candidate.representations.island.evaluations=0
        stopped=saved['stopped_failure']
        if stopped is not None:
            if not isinstance(stopped,dict) or set(stopped)!={'error','accepted_time_s','interval_rolled_back','accepted_snapshot_preserved'} or not isinstance(stopped['error'],str) or stopped['accepted_time_s']!=candidate.time or stopped['interval_rolled_back'] is not True or stopped['accepted_snapshot_preserved'] is not True:raise ValueError('Invalid stopped-scene continuation')
        candidate.rejected=copy.deepcopy(stopped);candidate.last_accounts=[];candidate.accepted=candidate._snapshot(b)
        return candidate
