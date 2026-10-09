"""Versioned registry for the coupled lab's bounded existing representations.

Definitions are immutable canonical JSON; mutable physics remains in the world's
canonical arrays. This is not a general mesh compiler or a new material law.
"""
import copy
import hashlib
import json
import math
import re
import uuid
import numpy as np

SCHEMA='banjo.object-registry.v1'
CHECKPOINT_SCHEMA='banjo.coupled-checkpoint.v1'
CHECKPOINT_LIMIT=2_000_000
FLOAT_ENCODING='ieee754-binary64-hex-v1'
FAMILIES=('sleeping','rigid','articulated','reduced-solid','detailed-solid','flowing','thermal','chemical')

def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)

def digest(value):
    return hashlib.sha256(canonical(value).encode('utf8')).hexdigest()

def checkpoint_numbers(value,decode=False):
    # JSON.parse/stringify changes 1.0 to 1 and erases negative zero. Encode
    # binary64 explicitly so browser saving preserves type and every bit.
    if decode and isinstance(value,dict) and set(value)=={'$f64'}:
        text=value['$f64']
        if not isinstance(text,str) or len(text)>26:raise ValueError('Invalid binary64 checkpoint number')
        number=float.fromhex(text)
        if not math.isfinite(number) or number.hex()!=text:raise ValueError('Noncanonical binary64 checkpoint number')
        return number
    if not decode and isinstance(value,float):
        if not math.isfinite(value):raise ValueError('Nonfinite checkpoint number')
        return {'$f64':value.hex()}
    if isinstance(value,dict):return {k:checkpoint_numbers(v,decode) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [checkpoint_numbers(v,decode) for v in value]
    if not decode and isinstance(value,int) and not isinstance(value,bool) and abs(value)>2**53-1:raise ValueError('Checkpoint integer exceeds browser exact range')
    return value

def seal(value):
    result=checkpoint_numbers(value);result['floating_point_encoding']=FLOAT_ENCODING;result['content_sha256']=digest(result)
    if len(canonical(result).encode('utf8'))>CHECKPOINT_LIMIT:raise ValueError('Checkpoint exceeds the 2 MB lab limit')
    return result

def open_checkpoint(value):
    if not isinstance(value,dict) or value.get('schema')!=CHECKPOINT_SCHEMA:raise ValueError('Unknown checkpoint schema')
    result=copy.deepcopy(value);claimed=result.pop('content_sha256',None)
    if digest(result)!=claimed:raise ValueError('Checkpoint content checksum differs')
    if len(canonical(value).encode('utf8'))>CHECKPOINT_LIMIT:raise ValueError('Checkpoint exceeds the 2 MB lab limit')
    if result.pop('floating_point_encoding',None)!=FLOAT_ENCODING:raise ValueError('Unknown checkpoint number encoding')
    return checkpoint_numbers(result,decode=True)

def rotation(q):
    w,x,y,z=q
    return np.array([[1-2*(y*y+z*z),2*(x*y-w*z),2*(x*z+w*y)],
        [2*(x*y+w*z),1-2*(x*x+z*z),2*(y*z-w*x)],
        [2*(x*z-w*y),2*(y*z+w*x),1-2*(x*x+y*y)]])

def relative_quaternion(frame,q):
    w,x,y,z=np.asarray(frame)*[1,-1,-1,-1];a,b,c,d=q
    return [w*a-x*b-y*c-z*d,w*b+x*a+y*d-z*c,w*c-x*d+y*a+z*b,w*d+x*c-y*b+z*a]

def properties(cells):
    """Exact primitive volume/inertia and parallel-axis sum; gaps stay empty."""
    if any(c['shape']=='plane' for c in cells):
        if len(cells)!=1:raise ValueError('An infinite boundary cannot be occupied assembly matter')
        return dict(volume_m3=None,mass_kg=None,center_of_mass_m=None,inertia_kg_m2=None,scope='infinite externally prescribed boundary')
    masses=[];inertias=[]
    for c in cells:
        h=np.asarray(c['half_size_m']);density=c['density_kg_m3']
        if c['shape']=='sphere':
            volume=4*math.pi*h[0]**3/3;mass=density*volume;inertia=np.eye(3)*(.4*mass*h[0]**2)
        elif c['shape']=='cube':
            volume=8*np.prod(h);mass=density*volume
            inertia=np.diag(mass*np.array([h[1]**2+h[2]**2,h[0]**2+h[2]**2,h[0]**2+h[1]**2])/3)
        else:raise ValueError('Unknown occupied primitive')
        r=rotation(c['reference_quaternion_wxyz']);masses.append((mass,volume));inertias.append(r@inertia@r.T)
    total=sum(m for m,_ in masses);center=sum((m*np.asarray(c['reference_position_m']) for c,(m,_) in zip(cells,masses)),np.zeros(3))/total
    tensor=np.zeros((3,3))
    for c,(m,_),intrinsic in zip(cells,masses,inertias):
        d=np.asarray(c['reference_position_m'])-center;tensor+=intrinsic+m*(np.eye(3)*np.dot(d,d)-np.outer(d,d))
    return dict(volume_m3=float(sum(v for _,v in masses)),mass_kg=float(total),center_of_mass_m=center.tolist(),inertia_kg_m2=tensor.tolist(),scope='occupied primitives; full geometric inertia; solver still uses its declared isotropic-cell inertia')

class ObjectRegistry:
    def __init__(self,bodies,edges,meta,profiles,world_id=None):
        b=np.asarray(bodies);e=np.asarray(edges)
        if b.ndim!=2 or b.shape[1]!=30 or not 1<=len(b)<=32 or e.ndim!=2 or e.shape[1]!=70 or len(e)>128:raise ValueError('Registry array bounds')
        if not np.isfinite(b).all() or not np.isfinite(e).all() or len(meta)!=len(b):raise ValueError('Invalid registry arrays')
        self.world_id=world_id or uuid.uuid4().hex
        if not isinstance(self.world_id,str) or not re.fullmatch('[0-9a-f]{32}',self.world_id):raise ValueError('Invalid persistent world ID')
        parent=list(range(len(b)))
        def root(i):
            while parent[i]!=i:i=parent[i]
            return i
        for edge in e:
            a,c=edge[:2]
            if a!=int(a) or c!=int(c) or not 0<=a<len(b) or not 0<=c<len(b) or a==c:raise ValueError('Invalid stable interface endpoints')
            if edge[2] not in (0,1,2):raise ValueError('Unimplemented interface law')
            parent[root(int(c))]=root(int(a))
        groups={}
        for i in range(len(b)):groups.setdefault(root(i),[]).append(i)
        self._definitions={};self._instances=[];self._summary_base=[]
        for index,members in enumerate(groups.values()):
            cells=[];interfaces=[];edge_ids=[];local={i:j for j,i in enumerate(members)}
            for j,i in enumerate(members):
                row=b[i];m=meta[i]
                if m['material'] not in profiles:raise ValueError('Unregistered material coefficients')
                if row[0] not in (0,1,2) or row[1]<0 or row[2]<0 or np.any(row[4:7]<=0):raise ValueError('Invalid occupied body')
                if abs(np.linalg.norm(row[26:30])-1)>1e-10:raise ValueError('Invalid reference orientation')
                cells.append(dict(local_matter_id=f'cell-{j}',shape=('plane','cube','sphere')[int(row[0])],
                    half_size_m=row[4:7].tolist(),reference_position_m=row[20:23].tolist(),reference_quaternion_wxyz=row[26:30].tolist(),
                    density_kg_m3=profiles[m['material']]['density_kg_m3'],material=copy.deepcopy(profiles[m['material']]),
                    solver_mass_kg=float(row[1]),solver_isotropic_inertia_kg_m2=float(row[2]),prescribed=bool(row[1]==0)))
            for j,edge in enumerate(e):
                if int(edge[0]) not in members:continue
                edge_ids.append(j);coefficients=edge[:35].copy();coefficients[:2]=[local[int(x)] for x in edge[:2]]
                interfaces.append(dict(local_interface_id=f'interface-{len(interfaces)}',matter_ids=[f'cell-{local[int(x)]}' for x in edge[:2]],
                    law=('axial-cohesive-v1','six-mode-connector-plastic-v1','mixed-mode-cohesive-v1')[int(edge[2])],
                    reference_coefficients=coefficients.tolist(),native_initial_gap_m=edge[67:70].tolist()))
            world_properties=properties(cells);frame=cells[0]['reference_quaternion_wxyz']
            anchor=world_properties['center_of_mass_m'] or cells[0]['reference_position_m'];r=rotation(frame)
            for cell in cells:
                cell['reference_position_m']=(r.T@(np.asarray(cell['reference_position_m'])-anchor)).tolist()
                cell['reference_quaternion_wxyz']=relative_quaternion(frame,cell['reference_quaternion_wxyz'])
            single_sphere=len(cells)==1 and cells[0]['shape']=='sphere' and not cells[0]['prescribed']
            definition=dict(schema='banjo.object-definition.v1',version=1,units=dict(length='m',mass='kg',time='s',energy='J',force='N',stress='Pa',inertia='kg m^2'),
                cells=cells,interfaces=interfaces,mass_properties=properties([dict(c,density_kg_m3=c['material']['density_kg_m3']) for c in cells]),
                recipes=['rigid-primitive-v1'] if single_sphere else ['coupled-rigid-cell-graph-v1'],
                implemented_family='detailed-solid' if interfaces else 'rigid',
                unsupported_families=[f for f in FAMILIES if f not in ('rigid','detailed-solid')],
                limits='Existing lab rigid primitives/cell interfaces only; no detailed sphere, reduced modes, field law or adaptive remeshing')
            key=digest(definition);self._definitions[key]=canonical(definition)
            label='Sheet' if interfaces else 'Ball' if single_sphere else 'Ground boundary' if cells[0]['shape']=='plane' else 'Support'
            self._instances.append(dict(instance_id=f'{self.world_id}/object-{index}',definition_sha256=key,label=label,body_ids=members,
                matter_ids=[f'{self.world_id}/cell-{i}' for i in members],single_sphere=single_sphere,
                edge_ids=edge_ids,interface_ids=[f'{self.world_id}/interface-{j}' for j in edge_ids],
                reference_frame=dict(position_m=anchor,quaternion_wxyz=frame),
                family=definition['implemented_family'],solver_binding='coupled-world'))
            p=definition['mass_properties']
            self._summary_base.append(dict(instance_id=self._instances[-1]['instance_id'],definition_sha256=key,label=label,
                body_ids=members,matter_count=len(cells),interface_count=len(interfaces),family=definition['implemented_family'],
                occupied_volume_m3=p['volume_m3'],material_mass_kg=p['mass_kg'],prescribed=all(c['prescribed'] for c in cells)))
        self.time_s=0.;self.revision=0

    def binding_state(self):return dict(time_s=self.time_s,revision=self.revision,instances=copy.deepcopy(self._instances))

    def restore_bindings(self,state):
        if set(state)!={'time_s','revision','instances'} or type(state['time_s']) not in (int,float) or not math.isfinite(state['time_s']) or state['time_s']<0 or type(state['revision']) is not int or state['revision']<0:raise ValueError('Invalid registry continuation')
        candidates=copy.deepcopy(state['instances'])
        if len(candidates)!=len(self._instances):raise ValueError('Incomplete object ownership')
        for current,saved in zip(self._instances,candidates):
            if set(saved)!=set(current) or any(saved[k]!=current[k] for k in current if k!='solver_binding'):raise ValueError('Changed object definition or matter mapping')
            if saved['solver_binding'] not in ('coupled-world','isolated-rigid-flight'):raise ValueError('Unknown representation owner')
            if saved['solver_binding']=='isolated-rigid-flight' and not saved['single_sphere']:raise ValueError('Unsupported rigid reduction')
        self._instances=candidates;self.time_s=state['time_s'];self.revision=state['revision']

    def bind(self,time_s,sphere=None):
        if not math.isfinite(time_s) or time_s<self.time_s:raise ValueError('Registry time goes backwards')
        for instance in self._instances:
            selected=sphere is not None and instance['body_ids']==[sphere] and instance['single_sphere']
            instance['solver_binding']='isolated-rigid-flight' if selected else 'coupled-world'
        self.time_s=time_s;self.revision+=1

    def document(self):
        return dict(schema=SCHEMA,world_id=self.world_id,definitions={k:json.loads(v) for k,v in self._definitions.items()},continuation=self.binding_state())

    def restore_document(self,value):
        if not isinstance(value,dict) or set(value)!={'schema','world_id','definitions','continuation'} or value['schema']!=SCHEMA or value['world_id']!=self.world_id:raise ValueError('Unknown registry document')
        definitions=value['definitions']
        if set(definitions)!=set(self._definitions) or any(digest(v)!=k or canonical(v)!=self._definitions[k] for k,v in definitions.items()):raise ValueError('Stale or changed geometry/material/law definition')
        self.restore_bindings(value['continuation'])

    def summary(self):
        result=[dict(copy.deepcopy(base),solver_binding=instance['solver_binding']) for base,instance in zip(self._summary_base,self._instances)]
        return dict(schema=SCHEMA,world_id=self.world_id,time_s=self.time_s,revision=self.revision,objects=result,
            scope='Immutable geometry/law definitions; stable matter IDs; exact native arrays own mutable state. Unsupported families have no solver.')
