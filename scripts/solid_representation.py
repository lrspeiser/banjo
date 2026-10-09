"""CPU reference for occupied-matter compilation and conservative state transfer.

This supplies geometry and mappings, NOT a deformable/contact solver. Cubes are
numerical matter elements, not precut shards. The detailed state retains every
element and interface; a rigid owner is admitted only without appreciable
nonrigid motion or elastic energy. Free flight below is uniform gravity only.
"""
import copy
import hashlib
import json
import math
import time
import uuid
from pathlib import Path

import numpy as np
from object_registry import digest, properties, rotation, relative_quaternion

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 'banjo.solid-representation.v1'
LIMIT = 4096


def source_hash():
    h = hashlib.sha256()
    for name in ('scripts/solid_representation.py', 'scripts/object_registry.py', 'client/voxel-lab/material-laws.json'):
        h.update(name.encode()); h.update(b'\0'); h.update((ROOT / name).read_bytes())
    return h.hexdigest()


LOADED_SOURCE_SHA = source_hash()


def definition_integrity(definition):
    d=dict(definition);claimed=d.pop('definition_sha256',None)
    if d.get('schema')!=SCHEMA or d.get('source_sha256')!=LOADED_SOURCE_SHA or digest(d)!=claimed:
        raise ValueError('Unknown or modified solid definition')


def vector(value, length=3):
    a = np.asarray(value, dtype=float)
    if a.shape != (length,) or not np.isfinite(a).all():
        raise ValueError('Invalid finite vector')
    return a


def quaternion(value):
    q = vector(value, 4)
    if abs(np.linalg.norm(q) - 1) > 1e-12:
        raise ValueError('Orientation must be a unit quaternion')
    return q


def multiply(a, b):
    w, x, y, z = a; p, q, r, s = b
    return np.array([w*p-x*q-y*r-z*s, w*q+x*p+y*s-z*r, w*r-x*s+y*p+z*q, w*s+x*r-y*q+z*p])


def compile_ball(radius_m, material, level=3):
    """Adaptive octree occupancy with a declared sphere approximation bound.

    Whole cubes strictly inside the requested sphere stop refining. Boundary
    cubes refine to the requested level, then center occupancy decides. Nothing
    is filled between disconnected occupied cells. No mass renormalization.
    """
    if source_hash()!=LOADED_SOURCE_SHA: raise ValueError('Representation source changed; restart the server')
    if isinstance(radius_m, bool) or not isinstance(radius_m, (int, float)) or not math.isfinite(radius_m) or not .001 <= radius_m <= 1:
        raise ValueError('Radius must be 0.001..1 m')
    if type(level) is not int or not 2 <= level <= 5:
        raise ValueError('Resolution level must be 2..5')
    profiles = {p['material']: p for p in json.loads((ROOT/'client/voxel-lab/material-laws.json').read_text())['profiles']}
    if material not in profiles:
        raise ValueError('Unknown installed material')
    profile = profiles[material]
    cells = []; n = 2**level; smallest = 2*radius_m/n
    def visit(lo, width, depth):
        center = -radius_m + smallest*(np.array(lo)+width/2)
        half = smallest*width/2
        near = np.maximum(np.abs(center)-half, 0)
        far = np.abs(center)+half
        if np.dot(near, near) >= radius_m**2:
            return
        inside = np.dot(far, far) <= radius_m**2
        if inside or depth == level:
            if inside or np.dot(center, center) < radius_m**2:
                cells.append(dict(id='cell-'+'.'.join(map(str, (*lo, width))), shape='cube', half_size_m=[half]*3,
                    reference_position_m=center.tolist(), reference_quaternion_wxyz=[1.,0.,0.,0.],
                    density_kg_m3=profile['density_kg_m3'], material=material, grid_lo=list(lo), grid_width=width))
            return
        w = width//2
        for x in (0,w):
            for y in (0,w):
                for z in (0,w): visit((lo[0]+x,lo[1]+y,lo[2]+z), w, depth+1)
    visit((0,0,0), n, 0)
    if not 1 <= len(cells) <= LIMIT:
        raise ValueError('Occupied matter exceeds the 4096-element compiler limit')
    # Finest-grid occupancy finds shared face area even for unequal leaf sizes.
    # The grid is a compiler index, not 32768 separately simulated elements.
    grid = {}
    for i,c in enumerate(cells):
        lo=c['grid_lo']; w=c['grid_width']
        for x in range(lo[0],lo[0]+w):
            for y in range(lo[1],lo[1]+w):
                for z in range(lo[2],lo[2]+w):
                    key=(x,y,z)
                    if key in grid: raise ValueError('Overlapping occupied matter')
                    grid[key]=i
    faces={}
    for key,a in grid.items():
        for axis in range(3):
            neighbor=list(key);neighbor[axis]+=1;b=grid.get(tuple(neighbor))
            if b is None or a==b: continue
            k=(a,b,axis); center=np.array(key,dtype=float)+.5;center[axis]+=.5
            count, summed=faces.get(k,(0,np.zeros(3)));faces[k]=(count+1,summed+center)
    interfaces=[]
    law='six-mode-connector-plastic-v1' if 'connector_stiffness' in profile else 'mixed-mode-cohesive-v1'
    for (a,b,axis),(count,summed) in sorted(faces.items()):
        interfaces.append(dict(id=f'face-{a}-{b}-{axis}', a=cells[a]['id'], b=cells[b]['id'], axis=axis,
            center_m=(-radius_m+smallest*summed/count).tolist(), area_m2=count*smallest**2,
            center_distance_m=abs(cells[a]['reference_position_m'][axis]-cells[b]['reference_position_m'][axis]),
            requested_law=law, solver_binding=None))
    p=properties(cells); analytic_volume=4*math.pi*radius_m**3/3
    definition=dict(schema=SCHEMA, units=dict(length='m', mass='kg', time='s', energy='J', inertia='kg m^2'),
        source_sha256=source_hash(), material_profile=profile, cells=cells, interfaces=interfaces, mass_properties=p,
        requested_geometry=dict(shape='sphere',radius_m=radius_m),
        geometry=dict(recipe='adaptive-center-occupancy-v1',level=level,finest_cell_m=smallest,
            boundary_distance_bound_m=math.sqrt(3)*smallest/2, nominal_volume_m3=analytic_volume,
            occupied_volume_error_m3=p['volume_m3']-analytic_volume,
            mass_policy='density times occupied volume; never rescale to the requested sphere mass'),
        supported=['occupied-geometry','conservative-rigid-detail-transfer','isolated-uniform-gravity'],
        unsupported=['internal-force-solve','contact','fracture','plastic-deformation','thermal','chemical','flowing'])
    definition['definition_sha256']=digest(definition)
    return definition


def validate_definition(definition):
    definition_integrity(definition);d=definition
    # Only recipes from this bounded compiler are admitted; a checksum alone
    # does not authorize arbitrary foreign geometry/material/law edits.
    expected=compile_ball(d['requested_geometry']['radius_m'], d['material_profile']['material'], d['geometry']['level'])
    if expected!=definition: raise ValueError('Definition differs from installed compiler recipe')


def initial_state(definition, position=(0,0,0), orientation=(1,0,0,0), velocity=(0,0,0), spin=(0,0,0)):
    validate_definition(definition)
    q=quaternion(orientation); r=rotation(q); p=vector(position); v=vector(velocity); w=vector(spin)
    state=dict(definition_sha256=definition['definition_sha256'],instance_id=uuid.uuid4().hex,time_s=0.,owner='detailed',cells=[],
        interfaces=[dict(id=i['id'],active=True,history=[0.]*32) for i in definition['interfaces']],
        elastic_energy_j=0.,retained_fields={})
    for c in definition['cells']:
        offset=r@np.asarray(c['reference_position_m'])
        state['cells'].append(dict(id=c['id'],position_m=(p+offset).tolist(),quaternion_wxyz=q.tolist(),
            velocity_m_s=(v+np.cross(w,offset)).tolist(),spin_rad_s=w.tolist()))
    return state


def validate_state(definition, state):
    definition_integrity(definition)
    if not isinstance(state.get('instance_id'),str) or len(state['instance_id'])!=32 or any(c not in '0123456789abcdef' for c in state['instance_id']):raise ValueError('Invalid persistent instance ID')
    if state['definition_sha256']!=definition['definition_sha256'] or state['owner']!='detailed': raise ValueError('Wrong detailed owner/definition')
    if [c['id'] for c in state['cells']]!=[c['id'] for c in definition['cells']]: raise ValueError('Incomplete or reordered matter mapping')
    if [i['id'] for i in state['interfaces']]!=[i['id'] for i in definition['interfaces']]: raise ValueError('Incomplete interface mapping')
    if not math.isfinite(state['time_s']) or state['time_s']<0 or not math.isfinite(state['elastic_energy_j']) or state['elastic_energy_j']<0: raise ValueError('Invalid clock/elastic energy')
    for c in state['cells']:
        for k in ('position_m','velocity_m_s','spin_rad_s'): vector(c[k])
        quaternion(c['quaternion_wxyz'])
    for i in state['interfaces']:
        if type(i['active']) is not bool: raise ValueError('Invalid interface connectivity')
        vector(i['history'],32)


def mechanics(definition, state, gravity=(0,-9.81,0)):
    validate_state(definition,state);g=vector(gravity)
    m=np.array([8*np.prod(c['half_size_m'])*c['density_kg_m3'] for c in definition['cells']])
    pos=np.array([c['position_m'] for c in state['cells']]); v=np.array([c['velocity_m_s'] for c in state['cells']]); w=np.array([c['spin_rad_s'] for c in state['cells']])
    inertia=np.array([np.eye(3)*mass*2*c['half_size_m'][0]**2/3 for c,mass in zip(definition['cells'],m)])
    mass=float(m.sum());center=np.sum(m[:,None]*pos,axis=0)/mass; offsets=pos-center
    tensor=np.sum(inertia,axis=0)
    for mi,d in zip(m,offsets): tensor+=mi*(np.eye(3)*np.dot(d,d)-np.outer(d,d))
    momentum=np.sum(m[:,None]*v,axis=0); angular=np.sum(np.cross(pos,m[:,None]*v)+np.einsum('nij,nj->ni',inertia,w),axis=0)
    kinetic=float(.5*np.sum(m*np.sum(v*v,axis=1))+.5*np.einsum('ni,nij,nj->',w,inertia,w))
    return dict(mass_kg=mass,center_m=center.tolist(),inertia_world_kg_m2=tensor.tolist(),
        momentum_n_s=momentum.tolist(),angular_momentum_n_m_s=angular.tolist(),kinetic_j=kinetic,
        gravity_j=float(-np.sum(m*(pos@g))),elastic_j=state['elastic_energy_j'])


def collapse(definition, state, energy_budget_j=1e-10):
    """Private candidate; rejection leaves caller state byte-for-byte untouched."""
    validate_state(definition,state)
    if not math.isfinite(energy_budget_j) or not 0<=energy_budget_j<=1e-10: raise ValueError('Invalid transfer energy budget')
    if state['elastic_energy_j']>energy_budget_j: raise ValueError('Elastic energy requires detailed/reduced continuation')
    if any(not i['active'] for i in state['interfaces']): raise ValueError('Split matter needs separate connected-component owners')
    before=mechanics(definition,state); mass=before['mass_kg']; center=vector(before['center_m']); tensor=np.array(before['inertia_world_kg_m2'])
    v=vector(before['momentum_n_s'])/mass
    # Avoid subtracting large orbital angular momenta to recover tiny spin,
    # and avoid subtracting total kinetic energies to screen relative motion.
    # Both quantities are evaluated directly about the measured COM.
    masses=np.array([8*np.prod(c['half_size_m'])*c['density_kg_m3'] for c in definition['cells']])
    inertias=np.array([m*2*c['half_size_m'][0]**2/3 for c,m in zip(definition['cells'],masses)])
    offsets=np.array([c['position_m'] for c in state['cells']])-center
    velocities=np.array([c['velocity_m_s'] for c in state['cells']]);spins=np.array([c['spin_rad_s'] for c in state['cells']])
    central=np.sum(np.cross(offsets,masses[:,None]*(velocities-v))+inertias[:,None]*spins,axis=0)
    w=np.linalg.solve(tensor,central)
    relative=velocities-v-np.cross(w,offsets)
    nonrigid=float(.5*np.sum(masses*np.sum(relative**2,axis=1))+.5*np.sum(inertias*np.sum((spins-w)**2,axis=1)))
    if abs(nonrigid)>energy_budget_j: raise ValueError('Nonrigid kinetic energy requires detailed/reduced continuation')
    q=quaternion(state['cells'][0]['quaternion_wxyz']); r=rotation(q)
    out=dict(definition_sha256=state['definition_sha256'],instance_id=state['instance_id'],time_s=state['time_s'],owner='rigid',
        mass_kg=mass,position_m=center.tolist(),quaternion_wxyz=q.tolist(),velocity_m_s=v.tolist(),spin_rad_s=w.tolist(),
        inertia_local_kg_m2=(r.T@tensor@r).tolist(),cells=[],interfaces=copy.deepcopy(state['interfaces']),
        elastic_energy_j=state['elastic_energy_j'],retained_fields=copy.deepcopy(state['retained_fields']))
    for c in state['cells']:
        out['cells'].append(dict(id=c['id'],offset_m=(r.T@(vector(c['position_m'])-center)).tolist(),
            quaternion_local_wxyz=relative_quaternion(q,c['quaternion_wxyz'])))
    expanded=expand(definition,out)
    after=mechanics(definition,expanded)
    receipt=dict(from_owner='detailed',to_owner='rigid',time_s=state['time_s'],nonrigid_energy_j=float(nonrigid),
        mass_residual_kg=after['mass_kg']-mass,momentum_residual_n_s=(vector(after['momentum_n_s'])-vector(before['momentum_n_s'])).tolist(),
        angular_residual_n_m_s=(vector(after['angular_momentum_n_m_s'])-vector(before['angular_momentum_n_m_s'])).tolist(),
        mechanical_energy_residual_j=after['kinetic_j']+after['gravity_j']-before['kinetic_j']-before['gravity_j'])
    if max(abs(receipt['mechanical_energy_residual_j']),np.linalg.norm(receipt['momentum_residual_n_s']),np.linalg.norm(receipt['angular_residual_n_m_s']))>1e-9:
        raise ValueError('Conservative mapping exceeds FP64 transfer budget')
    return out,receipt


def expand(definition, rigid):
    definition_integrity(definition)
    if rigid['owner']!='rigid' or rigid['definition_sha256']!=definition['definition_sha256']: raise ValueError('Wrong rigid owner/definition')
    if [c['id'] for c in rigid['cells']]!=[c['id'] for c in definition['cells']]: raise ValueError('Incomplete rigid matter mapping')
    q=quaternion(rigid['quaternion_wxyz']);r=rotation(q);p=vector(rigid['position_m']);v=vector(rigid['velocity_m_s']);w=vector(rigid['spin_rad_s'])
    out=dict(definition_sha256=rigid['definition_sha256'],instance_id=rigid['instance_id'],time_s=rigid['time_s'],owner='detailed',cells=[],
        interfaces=copy.deepcopy(rigid['interfaces']),elastic_energy_j=rigid['elastic_energy_j'],retained_fields=copy.deepcopy(rigid['retained_fields']))
    for c in rigid['cells']:
        offset=r@vector(c['offset_m'])
        out['cells'].append(dict(id=c['id'],position_m=(p+offset).tolist(),quaternion_wxyz=multiply(q,quaternion(c['quaternion_local_wxyz'])).tolist(),
            velocity_m_s=(v+np.cross(w,offset)).tolist(),spin_rad_s=w.tolist()))
    validate_state(definition,out)
    actual=mechanics(definition,out)
    measured_tensor=np.array(actual['inertia_world_kg_m2'])
    if abs(actual['mass_kg']-rigid['mass_kg'])>1e-12 or np.linalg.norm(r@np.array(rigid['inertia_local_kg_m2'])@r.T-measured_tensor)>2e-12*np.linalg.norm(measured_tensor):
        raise ValueError('Rigid mass/inertia differs from retained occupied matter')
    return out


def free_flight(definition, rigid, dt_s, gravity=(0,-9.81,0)):
    """Exact force-free spin for isotropic inertia; uniform-gravity translation.

    No contact response. Caller must prove empty swept space. Anisotropic spin
    is refused until a torque-free Euler integrator is qualified.
    """
    if not math.isfinite(dt_s) or not 0<dt_s<=2: raise ValueError('Flight duration must be 0..2 s')
    expand(definition,rigid);g=vector(gravity);p=vector(rigid['position_m']);v=vector(rigid['velocity_m_s']);w=vector(rigid['spin_rad_s'])
    tensor=np.array(rigid['inertia_local_kg_m2']);scale=float(np.trace(tensor)/3)
    if np.linalg.norm(w)>0 and np.linalg.norm(tensor-np.eye(3)*scale)>1e-11*scale: raise ValueError('Anisotropic free spin needs a qualified Euler integrator')
    return _flight_state(rigid,dt_s,g)


def _flight_state(rigid,dt_s,g):
    # Private constant-law evaluation after complete interval/isotropy
    # admission. Exact physical time and original occupied mapping are used;
    # no cached collision outcome or render interpolation is substituted.
    p=vector(rigid['position_m']);v=vector(rigid['velocity_m_s']);w=vector(rigid['spin_rad_s'])
    out=copy.deepcopy(rigid);out['position_m']=(p+dt_s*v+.5*dt_s**2*g).tolist();out['velocity_m_s']=(v+dt_s*g).tolist();out['time_s']+=dt_s
    speed=np.linalg.norm(w)
    if speed:
        angle=speed*dt_s/2;turn=np.r_[math.cos(angle),w*math.sin(angle)/speed]
        out['quaternion_wxyz']=multiply(turn,quaternion(rigid['quaternion_wxyz'])).tolist()
    return out


def experiment(declaration):
    allowed={'material','radius_m','level','height_m','spin_rad_s','frames'}
    if not isinstance(declaration,dict) or set(declaration)-allowed: raise ValueError('Unknown representation experiment setting')
    material=declaration.get('material','glass'); radius=declaration.get('radius_m',.05); level=declaration.get('level',3)
    height=declaration.get('height_m',10); frames=declaration.get('frames',24);spin=vector(declaration.get('spin_rad_s',[0,3,0]))
    if isinstance(height,bool) or not isinstance(height,(int,float)) or not math.isfinite(height) or not .2<=height<=10: raise ValueError('Height must be 0.2..10 m')
    if type(frames) is not int or not 1<=frames<=60 or np.linalg.norm(spin)>20: raise ValueError('Frame/spin bound exceeded')
    started=time.perf_counter();definition=compile_ball(radius,material,level)
    # Conservative enclosing sphere includes all occupied cube corners for all
    # rotations. Stop with 20 cm clearance: no ground collision is simulated.
    bound=max(np.linalg.norm(c['reference_position_m'])+np.linalg.norm(c['half_size_m']) for c in definition['cells'])
    detailed=initial_state(definition,position=[0,height+bound,0],spin=spin)
    rigid,receipt=collapse(definition,detailed);duration=math.sqrt(2*(height-.2)/9.81)
    # Qualify the complete empty-space interval once, then evaluate its same
    # analytical law at each requested time. State transfer is re-audited at
    # the actual ending time; render snapshots contain no extra physics owner.
    final_rigid=free_flight(definition,rigid,duration) if duration else copy.deepcopy(rigid)
    states=[rigid]
    for i in range(1,frames): states.append(_flight_state(rigid,duration*i/frames,np.array([0,-9.81,0])))
    states.append(final_rigid)
    final=expand(definition,states[-1]);initial_accounts=mechanics(definition,detailed);final_accounts=mechanics(definition,final)
    impulse=definition['mass_properties']['mass_kg']*duration*np.array([0,-9.81,0])
    residual=vector(final_accounts['momentum_n_s'])-vector(initial_accounts['momentum_n_s'])-impulse
    # Gravity torque about origin integrated along the exact COM parabola.
    initial_center=vector(initial_accounts['center_m']);initial_velocity=vector(rigid['velocity_m_s'])
    torque_impulse=np.cross(initial_center*duration+.5*initial_velocity*duration**2,definition['mass_properties']['mass_kg']*np.array([0,-9.81,0]))
    angular_residual=vector(final_accounts['angular_momentum_n_m_s'])-vector(initial_accounts['angular_momentum_n_m_s'])-torque_impulse
    visible_states=[{k:s[k] for k in ('time_s','owner','position_m','quaternion_wxyz','velocity_m_s','spin_rad_s')} for s in states]
    return dict(ok=True,source_sha256=source_hash(),definition=definition,initial=detailed,rigid_binding=rigid,rigid_states=visible_states,final=final,transfer=receipt,
        measured=dict(wall_s=time.perf_counter()-started,physical_s=duration,gravity_impulse_n_s=impulse.tolist(),
            momentum_residual_n_s=residual.tolist(),angular_residual_n_m_s=angular_residual.tolist(),
            energy_residual_j=final_accounts['kinetic_j']+final_accounts['gravity_j']-initial_accounts['kinetic_j']-initial_accounts['gravity_j']),
        scope='CPU geometry/transfer/free-flight reference. No material/contact solve. Stops at 0.2 m conservative ground clearance; no impact, cracks or dents.',
        compiler_binding='reference-only; not admitted to coupled CUDA impact solver')
