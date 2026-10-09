"""Experimental resident PhysX GPU comparator. No bonded material laws.

One process owns one SDK/stage. Never feed simulation output back into USD.
All later poses come from the solver; rejected state is stopped, not resumed.
"""
from __future__ import annotations
import contextlib
import copy
import hashlib
import math
import logging
import importlib.metadata
from pathlib import Path
import sys
import tempfile
import time
with contextlib.redirect_stdout(sys.stderr):
    import numpy as np
    import warp as wp
    import ovphysx
    import ovstage
    from ovphysx import PhysX, PhysXConfig, TensorType
    from ovphysx.types import SimObjectType, ObjectScope
from gpu_contact_world import DENSITY, declaration

SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
ATTRS = ('position', 'orientation', 'linearVelocity', 'angularVelocity')


@wp.kernel
def copy_column(src: wp.array2d[wp.float32], dst: wp.array3d[wp.float32],
                rows: wp.array[wp.int32], slot: int, column: int):
    i, j = wp.tid()
    dst[slot, rows[i], column+j] = src[i, j]


@wp.kernel
def copy_bound(pose: wp.array2d[wp.float32], velocity: wp.array2d[wp.float32],
               dst: wp.array3d[wp.float32], slot: int):
    i, j = wp.tid()
    if j < 7:
        dst[slot,i,j] = pose[i,j]
    else:
        dst[slot,i,j] = velocity[i,j-7]


@wp.kernel
def contact_summary(layout: wp.array2d[wp.int32], positions: wp.array2d[wp.float32],
                    normals: wp.array2d[wp.float32], forces: wp.array2d[wp.float32],
                    summary: wp.array3d[wp.float32], slot: int, capacity: int):
    i = wp.tid()
    count, start = layout[i, 0], layout[i, 1]
    torque = wp.vec3(0.0)
    for j in range(start, start+count):
        p = wp.vec3(positions[j, 0], positions[j, 1], positions[j, 2])
        f = forces[j, 0]*wp.vec3(normals[j, 0], normals[j, 1], normals[j, 2])
        torque += wp.cross(p, f)
    for k in range(3):
        summary[slot, i, k] = torque[k]
    summary[slot, i, 3] = float(count)


class PhysXContactWorld:
    def __init__(self, raw, *, observation_mode='bindings'):
        if (ovphysx.__version__, wp.__version__, np.__version__,importlib.metadata.version('ovstage')) != ('0.6.3', '1.18.0', '2.5.3','0.2.0.377349'):
            raise RuntimeError('Unverified PhysX runtime; install scripts/gpu-requirements.txt')
        self.d = declaration(raw)
        if observation_mode not in ('bindings', 'columns'):
            raise ValueError('Unknown PhysX observation mode')
        self.observation_mode = observation_mode
        self.pose_binding = self.velocity_binding = None
        if self.d['experiment']=='pair' and self.d['dt_s']>1/1920:
            raise ValueError('PhysX pair requires 1/1920 s: coarse iron pair fails the analytical bounce oracle')
        if self.d['device'] != 'cuda:0' or PhysX.get_cpu_mode():
            raise ValueError('PhysX comparator requires actual CUDA; CPU fallback prohibited')
        self.device = wp.get_device('cuda:0')
        self.gravity = 0. if self.d['experiment'] == 'pair' else -9.81
        self.ticks = 0
        self.total_step_s = self.last_batch_s = 0.
        self.phase_s = dict(sdk_step=0., gpu_observation=0., host_audit=0.)
        self.last_phase_s = dict(self.phase_s)
        self.max_contacts = self.last_steps = 0
        self.metadata = []
        self.paths = []
        self.initial_q = []
        self.initial_v = []
        self.sdk = self.stage = self.cb = self.pd = None
        self.temp = tempfile.TemporaryDirectory(prefix='banjo-physx-')
        self.capacity = 4096
        self.groups = {}
        self.sdk_faults = []
        try:
            self._create()
        except Exception:
            self.close()
            raise

    def _create(self):
        d = self.d
        # Native Carbonite output defaults to stdout. Preserve diagnostics on
        # stderr without corrupting the worker's bounded JSON-lines protocol.
        ovphysx.enable_default_log_output(False)
        logger=logging.getLogger('banjo.physx')
        if not logger.handlers:
            logger.addHandler(logging.StreamHandler(sys.stderr))
        logger.setLevel(logging.WARNING)
        owner=self
        class CapacityGuard(logging.Handler):
            def emit(self,record):
                message=record.getMessage()
                if record.levelno>=logging.ERROR or any(word in message.lower() for word in ('overflow','truncat','capacity','buffer too small','dropped contact')):
                    owner.sdk_faults.append(message[:2048])
        self.log_guard=CapacityGuard()
        logger.addHandler(self.log_guard)
        ovphysx.enable_python_logging('banjo.physx',min_severity=ovphysx.LogLevel.WARNING)
        pieces = ['''#usda 1.0
(metersPerUnit = 1
 upAxis = "Y"
 kilogramsPerUnit = 1)
def Xform "World" {
''', f'''def PhysicsScene "scene" (prepend apiSchemas = ["PhysxSceneAPI"]) {{
 vector3f physics:gravityDirection = (0, -1, 0)
 float physics:gravityMagnitude = {-self.gravity}
 bool physxScene:enableGPUDynamics = true
 token physxScene:broadphaseType = "GPU"
 token physxScene:solverType = "TGS"
 float physxScene:bounceThreshold = 0.000001
}}
def Material "contact" (prepend apiSchemas = ["PhysicsMaterialAPI", "PhysxMaterialAPI"]) {{
 float physics:staticFriction = {d['friction']}
 float physics:dynamicFriction = {d['friction']}
 float physics:restitution = {d['restitution']}
 token physxMaterial:frictionCombineMode = "average"
 token physxMaterial:restitutionCombineMode = "average"
}}
''']
        if d['experiment'] in ('floor', 'yard'):
            pieces.append('''def Plane "ground" (prepend apiSchemas = ["PhysicsCollisionAPI", "PhysxCollisionAPI", "MaterialBindingAPI"]) {
 uniform token axis = "Y"
 rel material:binding:physics = </World/contact>
 float physxCollision:contactOffset = 0.002
 float physxCollision:restOffset = 0
}
''')

        def body(material, shape, pos, mass, inertia, size, radius=0., velocity=(0., 0., 0.)):
            i = len(self.metadata)
            self.paths.append(f'/World/body{i:02}')
            self.metadata.append(dict(id=i, material=material, shape=shape, radius_m=radius,
                size_m=size, expected_mass_kg=mass, inertia_kg_m2=inertia))
            self.initial_q.append([*pos, 0., 0., 0., 1.])
            self.initial_v.append([*velocity, 0., 0., 0.])
            geom = f'double radius = {radius}' if shape == 'sphere' else f'double size = {size[0]}'
            pieces.append(f'''def {'Sphere' if shape == 'sphere' else 'Cube'} "body{i:02}" (prepend apiSchemas = ["PhysicsRigidBodyAPI", "PhysxRigidBodyAPI", "PhysicsMassAPI", "PhysicsCollisionAPI", "PhysxCollisionAPI", "PhysxContactReportAPI", "MaterialBindingAPI"]) {{
 {geom}
 double3 xformOp:translate = {tuple(pos)}
 uniform token[] xformOpOrder = ["xformOp:translate"]
 vector3f physics:velocity = {tuple(velocity)}
 float physics:mass = {mass}
 float3 physics:diagonalInertia = ({inertia}, {inertia}, {inertia})
 point3f physics:centerOfMass = (0, 0, 0)
 quatf physics:principalAxes = (1, 0, 0, 0)
 float physxRigidBody:linearDamping = 0
 float physxRigidBody:angularDamping = 0
 float physxRigidBody:sleepThreshold = 0
 float physxRigidBody:stabilizationThreshold = 0
 float physxRigidBody:maxAngularVelocity = 100000000
 int physxRigidBody:solverPositionIterationCount = 16
 int physxRigidBody:solverVelocityIterationCount = 4
 float physxContactReport:threshold = 0
 float physxCollision:contactOffset = 0.002
 float physxCollision:restOffset = 0
 rel material:binding:physics = </World/contact>
}}
''')

        def sphere(material, pos, velocity=(0., 0., 0.)):
            mass = d['ball_mass_kg']
            radius = (mass/(DENSITY[material]*4*math.pi/3))**(1/3)
            body(material, 'sphere', pos, mass, .4*mass*radius**2, [2*radius]*3, radius, velocity)
        if d['experiment'] == 'pair':
            sphere(d['ball_material'], (-.2, 0., d['offset_m']), (2., 0., 0.))
            sphere(d['material'], (.2, 0., 0.))
        else:
            top = 0.
            if d['experiment'] == 'yard':
                for level in range(3):
                    for x in range(-1, 2):
                        for z in range(-1, 2):
                            m = DENSITY[d['material']]*.12**3
                            body(d['material'], 'cube', (x*.1202, .06+level*.1202, z*.1202), m, m*.12**2/6, [.12]*3)
                top = .3604
            r = (d['ball_mass_kg']/(DENSITY[d['ball_material']]*4*math.pi/3))**(1/3)
            sphere(d['ball_material'], (d['offset_m'], top+r+d['height_m'], 0.))
        pieces.append('}\n')
        file = Path(self.temp.name)/'scene.usda'
        file.write_text(''.join(pieces), encoding='utf8')
        ovstage.population.register_usd_schemas([str(ovphysx.codeless_schema_root())])
        self.sdk = PhysX(active_cuda_gpus='0', config=PhysXConfig(
            carbonite_overrides={'/physics/suppressReadback': True}))
        self.stage = ovstage.Stage('banjo-physx-contact')
        ovstage.population.open_usd(self.stage, str(file), ordinal=1, domains=ovstage.PopulationDomain.PHYSICS)
        self.stage.advance_write_floor(ordinal=1).wait()
        self.sdk.attach_ovstage(self.stage, read_ordinal=1)
        self.sdk.wait_all()
        self.cb = self.sdk.create_contact_binding(sensor_patterns=self.paths,
            filters_per_sensor=0, max_contact_data_count=self.capacity)
        if self.cb.sensor_paths != self.paths:
            raise RuntimeError('Unqualified sensor ordering')
        self.sdk.warmup()  # library initialization, not physical elapsed time
        self.pd = ovstage.PathDictionary(self.stage)
        self.tokens = {self.pd.intern_token(attr): (index, sum((3,4,3,3)[:index])) for index, attr in enumerate(ATTRS)}
        n, c = len(self.paths), self.capacity
        self.trace = wp.zeros((32,n,13), dtype=wp.float32, device=self.device)
        self.force_trace = wp.zeros((32,n,3), dtype=wp.float32, device=self.device)
        self.contact_trace = wp.zeros((32,n,4), dtype=wp.float32, device=self.device)
        self.net = wp.zeros((n,3), dtype=wp.float32, device=self.device)
        self.raw_force = wp.zeros((c,1), dtype=wp.float32, device=self.device)
        self.raw_pos = wp.zeros((c,3), dtype=wp.float32, device=self.device)
        self.raw_normal = wp.zeros((c,3), dtype=wp.float32, device=self.device)
        self.raw_sep = wp.zeros((c,1), dtype=wp.float32, device=self.device)
        self.layout = wp.zeros((n,2), dtype=wp.int32, device=self.device)
        self.actor_ids = wp.zeros((c,2), dtype=wp.uint64, device=self.device)
        # Query actual solver mass/inertia; authored values alone are not evidence.
        actual = {}
        with self.sdk.read(SimObjectType.RIGID_BODY, ['mass','inertia'], scope=ObjectScope.ALL) as result:
            for g in result.groups:
                key = self.pd.token_to_string(g.attribute)
                names = self.pd.get_path_strings(g.prim_list)
                values = g.tensors[0].numpy()
                actual[key] = dict(zip(names, values))
        self.mass = np.array([actual['mass'][p] for p in self.paths], dtype=np.float64).reshape(n)
        inertia = np.array([actual['inertia'][p] for p in self.paths], dtype=np.float64).reshape(n,3,3)
        self.inertia = inertia[:,0,0]
        if not np.allclose(inertia, self.inertia[:,None,None]*np.eye(3), rtol=2e-6, atol=1e-12):
            raise ValueError('Non-isotropic inertia is unsupported')
        for i, row in enumerate(self.metadata):
            if not math.isclose(self.mass[i],row['expected_mass_kg'],rel_tol=2e-6) or not math.isclose(self.inertia[i],row['inertia_kg_m2'],rel_tol=2e-6):
                raise ValueError('Actual mass/inertia mismatch')
        # The SDK warmup integrates a tiny initialization step. Restore only
        # the authored starting conditions before the experiment clock begins.
        initial = np.c_[np.array(self.initial_q),np.array(self.initial_v)].astype(np.float32)
        for attr, offset, width in zip(ATTRS,(0,3,7,10),(3,4,3,3)):
            with self.sdk.write(SimObjectType.RIGID_BODY,attr,scope=ObjectScope.ALL) as write:
                for g in write.groups:
                    names=self.pd.get_path_strings(g.prim_list)
                    values=wp.array(np.ascontiguousarray(initial[[self.paths.index(p) for p in names],offset:offset+width]),dtype=wp.float32,device=self.device)
                    wp.copy(g.tensors[0],values)
                    wp.synchronize_device(self.device)
                    write.commit(g)
        self._observe(0, contacts=False)
        state = self.trace.numpy()[0].astype(np.float64)
        if not np.allclose(state[:,:7], self.initial_q, atol=2e-6) or not np.allclose(state[:,7:],self.initial_v,atol=2e-6):
            raise RuntimeError(f'Warmup changed initial conditions: pose {np.max(abs(state[:,:7]-self.initial_q))}, velocity {np.max(abs(state[:,7:]-self.initial_v))}')
        self.last = state
        self.last_energy = self.energy(state)
        self.initial_energy = self.last_energy
        self.cumulative_normal_impulse = np.zeros(3)
        self.max_normal_P_residual = 0.
        self.accepted_snapshot = self._snapshot([])

    def _observe(self, slot, contacts=True):
        if self.observation_mode == 'bindings':
            if self.pose_binding is None:
                # Pinned 0.6.3 compatibility path. Binding API is deprecated;
                # its removal must fail initialization, never use CPU staging
                # or silently drop observations. This world never reparses or
                # changes topology during a session; close destroys bindings
                # before the realized stage and SDK are destroyed.
                self.pose_binding = self.sdk.create_tensor_binding(prim_paths=self.paths,
                    tensor_type=TensorType.RIGID_BODY_POSE, raise_if_empty=True)
                self.velocity_binding = self.sdk.create_tensor_binding(prim_paths=self.paths,
                    tensor_type=TensorType.RIGID_BODY_VELOCITY, raise_if_empty=True)
                for binding, width in ((self.pose_binding,7),(self.velocity_binding,6)):
                    device = binding.native_device
                    if (binding.prim_paths != self.paths or binding.shape != (len(self.paths),width)
                        or binding.dtype_name != 'float32' or device.device_type.value != 2
                        or device.device_id != self.device.ordinal):
                        raise RuntimeError('Unqualified resident PhysX binding layout/order/device')
                self.bound_pose = wp.zeros(self.pose_binding.shape,dtype=wp.float32,device=self.device)
                self.bound_velocity = wp.zeros(self.velocity_binding.shape,dtype=wp.float32,device=self.device)
            self.pose_binding.read(self.bound_pose)
            self.velocity_binding.read(self.bound_velocity)
            wp.launch(copy_bound,dim=(len(self.paths),13),inputs=[self.bound_pose,self.bound_velocity,self.trace,slot],device=self.device)
        else:
            seen = set()
            with self.sdk.read(SimObjectType.RIGID_BODY, list(ATTRS), scope=ObjectScope.ALL) as result:
                for g in result.groups:
                    if g.is_delete or g.is_array or g.index_map is not None or g.prim_index_map is not None:
                        raise RuntimeError('Unsupported sparse/deleted state group')
                    if g.attribute not in self.tokens or len(g.tensors) != 1:
                        raise RuntimeError('Unexpected GPU state column')
                    src = g.tensors[0]
                    if not src.device.is_cuda or src.device.ordinal != self.device.ordinal:
                        raise RuntimeError('State read is not resident on the requested CUDA GPU')
                    key = (g.attribute, tuple(self.pd.get_path_strings(g.prim_list)))
                    if key not in self.groups:
                        self.groups[key] = wp.array([self.paths.index(p) for p in key[1]], dtype=wp.int32, device=self.device)
                    seen.update((g.attribute,p) for p in key[1])
                    wp.launch(copy_column, dim=src.shape, inputs=[src,self.trace,self.groups[key],slot,self.tokens[g.attribute][1]],device=self.device)
            if len(seen) != 4*len(self.paths):
                raise RuntimeError('Incomplete actual GPU state read')
        if contacts:
            self.cb.read_net_forces(self.net)
            wp.copy(self.force_trace,self.net,dest_offset=slot*len(self.paths)*3,count=len(self.paths)*3)
            self.cb.read_raw_contact_data(self.raw_force,self.raw_pos,self.raw_normal,self.raw_sep,self.layout,self.actor_ids)
            wp.launch(contact_summary,dim=len(self.paths),inputs=[self.layout,self.raw_pos,self.raw_normal,self.raw_force,self.contact_trace,slot,self.capacity],device=self.device)
        # SDK read views are owned until GPU copies finish. No borrowed view survives stepping.
        wp.synchronize_device(self.device)

    def energy(self, state):
        return float(.5*np.sum(self.mass[:,None]*state[:,7:10]**2)+
            .5*np.sum(self.inertia[:,None]*state[:,10:13]**2)-self.gravity*np.sum(self.mass*state[:,1]))

    def advance(self, steps):
        if hasattr(self,'rejected_candidate'):
            raise ValueError('Rejected PhysX experiment is stopped; reset required')
        if type(steps) is not int or not 1 <= steps <= 32 or self.ticks+steps > round(4/self.d['dt_s']):
            raise ValueError('Steps outside bounded experiment')
        start = time.perf_counter()
        phases = dict(sdk_step=0., gpu_observation=0., host_audit=0.)
        try:
            for slot in range(steps):
                phase_start = time.perf_counter()
                self.sdk.step_sync(self.d['dt_s'])
                phases['sdk_step'] += time.perf_counter()-phase_start
                phase_start = time.perf_counter()
                self._observe(slot)
                phases['gpu_observation'] += time.perf_counter()-phase_start
            ovphysx.flush_log()
        except Exception as error:
            self.rejected_candidate=dict(first_tick=self.ticks+1,max_gain_j=None,solver_stopped=True,
                hidden_solver_rollback_qualified=False,error=str(error))
            raise RuntimeError('PhysX SDK/read fault; solver stopped, last accepted scene retained') from error
        states = self.trace.numpy()[:steps].astype(np.float64)
        forces = self.force_trace.numpy()[:steps].astype(np.float64)
        contacts = self.contact_trace.numpy()[:steps].astype(np.float64)
        energies = np.array([self.energy(s) for s in states])
        previous = np.r_[self.last_energy,energies[:-1]]
        gains = energies-previous
        tolerance = 1e-5*np.maximum(1.,abs(previous))+1e-6
        counts = contacts[:,:,3].sum(axis=1).astype(int)
        if self.sdk_faults or not np.isfinite(states).all() or not np.isfinite(forces).all() or not np.isfinite(contacts).all() or np.any(counts>=self.capacity) or np.any(gains>tolerance):
            safe = lambda xs: [float(x) if math.isfinite(x) else None for x in xs]
            self.rejected_candidate = dict(first_tick=self.ticks+1, max_gain_j=float(gains.max()) if np.isfinite(gains).all() else None,
                energy_j=safe(energies),tolerance_j=safe(tolerance),contact_counts=counts.tolist(),
                solver_stopped=True, hidden_solver_rollback_qualified=False,sdk_faults=list(self.sdk_faults))
            raise ValueError('PhysX GPU candidate refused: finite/capacity/energy gate; last accepted scene retained, solver stopped')
        trace=[]
        previous_state = self.last
        dt=self.d['dt_s']
        for i,state in enumerate(states):
            p0=np.sum(self.mass[:,None]*previous_state[:,7:10],axis=0)
            p1=np.sum(self.mass[:,None]*state[:,7:10],axis=0)
            normal=forces[i].sum(axis=0)*dt
            residual=p1-p0-normal-np.array([0.,self.gravity*self.mass.sum()*dt,0.])
            l0=np.sum(np.cross(previous_state[:,:3],self.mass[:,None]*previous_state[:,7:10])+self.inertia[:,None]*previous_state[:,10:],axis=0)
            l1=np.sum(np.cross(state[:,:3],self.mass[:,None]*state[:,7:10])+self.inertia[:,None]*state[:,10:],axis=0)
            normal_torque=contacts[i,:,:3].sum(axis=0)*dt
            gravity_torque=np.cross(previous_state[:,:3],self.mass[:,None]*np.array([0.,self.gravity,0.])).sum(axis=0)*dt
            self.max_normal_P_residual=max(self.max_normal_P_residual,float(np.linalg.norm(residual)))
            self.cumulative_normal_impulse+=normal
            trace.append(dict(tick=self.ticks+i+1, mechanical_j=float(energies[i]), mechanical_change_j=float(gains[i]),
                normal_impulse_n_s=normal.tolist(),normal_only_P_residual_n_s=residual.tolist(),
                normal_torque_impulse_n_m_s=normal_torque.tolist(),
                normal_only_L_residual_start_gravity_n_m_s=(l1-l0-normal_torque-gravity_torque).tolist()))
            previous_state=state
        self.last=states[-1]
        self.ticks+=steps
        self.last_steps=steps
        self.last_energy=float(energies[-1])
        self.max_contacts=max(self.max_contacts,int(counts.max()))
        self.last_batch_s=time.perf_counter()-start
        # Disjoint synchronized wall phases. These are not GPU kernel timers.
        # Preserve the existing measured interval: snapshot/IPC/render cost is
        # outside step_s and remains in the gateway's end-to-end measurement.
        phases['host_audit'] = self.last_batch_s-phases['sdk_step']-phases['gpu_observation']
        self.last_phase_s = phases
        for phase, elapsed in phases.items():
            self.phase_s[phase] += elapsed
        self.total_step_s+=self.last_batch_s
        self.accepted_snapshot=self._snapshot(trace,states,counts)
        return self.snapshot()

    def _snapshot(self,account,states=None,counts=None):
        state=self.last
        energy=self.energy(state)
        potential=-self.gravity*np.sum(self.mass*state[:,1])
        p=np.sum(self.mass[:,None]*state[:,7:10],axis=0)
        angular=np.sum(np.cross(state[:,:3],self.mass[:,None]*state[:,7:10])+self.inertia[:,None]*state[:,10:13],axis=0)
        cells=[row | dict(mass_kg=float(self.mass[i]),position_m=state[i,:3].tolist(),
            quaternion_wxyz=[float(state[i,6]),*state[i,3:6].tolist()],velocity_m_s=state[i,7:10].tolist(),
            angular_velocity_rad_s=state[i,10:13].tolist(),fixed=False,component=i+1) for i,row in enumerate(self.metadata)]
        return dict(schema='banjo.physx-rigid-contact.v1',declaration=copy.deepcopy(self.d),time_s=self.ticks*self.d['dt_s'],
            ticks=self.ticks,dt_s=self.d['dt_s'],cells=cells,events=[],
            substep_trace=dict(first_tick=self.ticks-self.last_steps+1,transform_layout='xyz,xyzw',body_ids=list(range(len(cells))),
                transforms=states[:,:,:7].tolist() if states is not None else [],
                velocities_v_omega=states[:,:,7:].tolist() if states is not None else [],
                contact_counts=counts.tolist() if counts is not None else [],normal_accounts=account),
            diagnostics=dict(dynamic_mass_kg=float(self.mass.sum()),kinetic_j=float(energy-potential),potential_j=float(potential),
                mechanical_j=energy,mechanical_change_j=energy-self.initial_energy,momentum_n_s=p.tolist(),angular_momentum_n_m_s=angular.tolist(),
                contacts=int(counts[-1]) if counts is not None else 0,max_contacts=self.max_contacts,
                cumulative_normal_impulse_n_s=self.cumulative_normal_impulse.tolist(),max_normal_only_P_residual_n_s=self.max_normal_P_residual,
                reaction_account_complete=False,numerical_and_contact_losses_separated=False),
            performance=dict(step_s=self.total_step_s,last_batch_ms=self.last_batch_s*1000,
                phase_s=dict(self.phase_s),last_phase_ms={k:1000*v for k,v in self.last_phase_s.items()},
                timing_scope='Disjoint synchronized wall phases of accepted batches; not GPU kernel timings. Excludes startup, snapshot serialization, IPC, journal and rendering.',
                compute_ratio=self.ticks*self.d['dt_s']/self.total_step_s if self.total_step_s else None),
            qualification=dict(backend='physx-tgs',ovphysx=ovphysx.__version__,warp=wp.__version__,device=str(self.device),gpu=True,
                device_name=self.device.name,source_sha256=SOURCE_SHA256,dtype='float32',position_iterations=16,velocity_iterations=4,
                direct_gpu=True,angular_damping=0.,sleeping=False,solver_relaxation_applicable=False,
                observation_mode=self.observation_mode,binding_api_deprecated=self.observation_mode=='bindings',
                material_scope='Density-derived rigid mass/inertia, numeric global restitution/friction. No bonded fracture/plasticity/elastic/thermal laws. Contact force read is normal-only; friction is not in that ledger.',
                complete_physics_validated=False,realtime_qualified=False))

    def snapshot(self):
        result=copy.deepcopy(self.accepted_snapshot)
        if hasattr(self,'rejected_candidate'):
            result['rejected_candidate']=copy.deepcopy(self.rejected_candidate)
        return result

    def close(self):
        for name in ('pose_binding','velocity_binding'):
            binding = getattr(self,name,None)
            if binding is not None:
                binding.destroy();setattr(self,name,None)
        if self.cb is not None:
            self.cb.destroy();self.cb=None
        if self.pd is not None:
            self.pd.destroy();self.pd=None
        if self.sdk is not None:
            if self.stage is not None:
                self.sdk.detach_ovstage();self.stage.destroy();self.stage=None
            self.sdk.destroy();self.sdk=None
        self.temp.cleanup()
        if hasattr(self,'log_guard'):
            logging.getLogger('banjo.physx').removeHandler(self.log_guard)
