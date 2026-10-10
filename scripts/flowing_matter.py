"""Bounded native hydrostatic flow reference; no synthetic render motion."""
import ctypes
import hashlib
import math
import json
import uuid
import copy
from pathlib import Path
import time
from object_registry import checkpoint_numbers, canonical, digest, FLOAT_ENCODING

ROOT = Path(__file__).resolve().parents[1]
FIELDS = ['time_s','mass_kg','momentum_x_n_s','momentum_z_n_s','angular_y_n_m_s','mechanical_energy_j',
          'wall_impulse_x_n_s','wall_impulse_z_n_s','wall_angular_impulse_y_n_m_s','numerical_angular_y_n_m_s',
          'numerical_energy_j','mass_residual_kg','momentum_x_residual_n_s','momentum_z_residual_n_s',
          'angular_y_residual_n_m_s','energy_residual_j','substeps','reserved']

def source_hash():
    digest = hashlib.sha256()
    for name in ['src/flow/FlowReference.hpp','src/flow/FlowReference.cpp','src/flow/FlowCpuApi.cpp','scripts/flowing_matter.py','scripts/object_registry.py']:
        digest.update(name.encode()); digest.update((ROOT/name).read_bytes())
    return digest.hexdigest()

LOADED_SOURCE_SHA=source_hash()
LIBRARIES={}

def _open_checkpoint(value):
    if not isinstance(value,dict):raise ValueError('Invalid flow checkpoint')
    if len(canonical(value).encode())>2_000_000:raise ValueError('Flow checkpoint exceeds 2 MB')
    encoded=copy.deepcopy(value);claimed=encoded.pop('content_sha256',None)
    if digest(encoded)!=claimed or encoded.pop('floating_point_encoding',None)!=FLOAT_ENCODING:raise ValueError('Flow checkpoint checksum/encoding mismatch')
    decoded=checkpoint_numbers(encoded,decode=True)
    if set(decoded)!={'schema','source_sha256','native_sha256','declaration','instance','cells','initial_cells','continuation'} or decoded['schema']!='banjo.flow-checkpoint.v1':raise ValueError('Unknown flow checkpoint schema')
    return decoded

def _seal_checkpoint(value):
    encoded=checkpoint_numbers(value);encoded['floating_point_encoding']=FLOAT_ENCODING;encoded['content_sha256']=digest(encoded)
    if len(canonical(encoded).encode())>2_000_000:raise ValueError('Flow checkpoint exceeds 2 MB')
    return encoded

def run(declaration, library=None, checkpoint=None):
    start = time.perf_counter()
    if source_hash()!=LOADED_SOURCE_SHA:raise ValueError('Flow physics source changed; restart the server')
    saved=None
    if checkpoint is not None:
        saved=_open_checkpoint(checkpoint)
        if not isinstance(saved['declaration'],dict) or set(saved['declaration'])!={'nx','nz','dx_m','density_kg_m3','gravity_m_s2'}:raise ValueError('Invalid saved flow definition')
        if not isinstance(declaration,dict) or set(declaration)-{'duration_s','frames'}:raise ValueError('Continue permits duration/frames only; physical definitions cannot change')
        declaration={**saved['declaration'],**declaration,'initial':saved['cells']}
    if not isinstance(declaration, dict) or set(declaration)-{'nx','nz','dx_m','density_kg_m3','gravity_m_s2','duration_s','frames','initial','left_depth_m','right_depth_m','split_fraction'}:
        raise ValueError('Unknown flow declaration fields')
    def numeric(name, default, low, high, integer=False):
        value=declaration.get(name,default)
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not low<=value<=high or (integer and int(value)!=value):
            raise ValueError('Bounded flow field refused: '+name)
        return int(value) if integer else float(value)
    nx=numeric('nx',48,2,128,True);nz=numeric('nz',24,2,128,True)
    if nx*nz>4096: raise ValueError('Flow reference admits at most 4096 columns')
    dx=numeric('dx_m',0.1,0.01,1);rho=numeric('density_kg_m3',1000,1,20000);gravity=numeric('gravity_m_s2',9.81,0,20)
    duration=numeric('duration_s',2,0.000001,5);frames=numeric('frames',121,2,241,True)
    if nx*nz*frames>300000:raise ValueError('Flow render receipt admits at most 300000 column frames')
    left=numeric('left_depth_m',0.2,0,2);right=numeric('right_depth_m',0,0,2);split=numeric('split_fraction',1/3,0,1)
    initial=declaration.get('initial')
    if initial is None: initial=[[left if i<nx*split else right,0,0] for j in range(nz) for i in range(nx)]
    if not isinstance(initial,list) or len(initial)!=nx*nz: raise ValueError('Initial flow grid size mismatch')
    flat=[]
    for cell in initial:
        if not isinstance(cell,list) or len(cell)!=3 or any(isinstance(v,bool) or not isinstance(v,(float,int)) or not math.isfinite(v) for v in cell): raise ValueError('Initial flow cell must be finite [depth_m, discharge_x_m2_s, discharge_z_m2_s]')
        h,qx,qz=cell
        max_depth=2 if saved is None else 2*nx*nz
        if not 0<=h<=max_depth or (h==0 and (qx or qz)) or (h>0 and math.hypot(qx,qz)/h>20):raise ValueError('Flow cell positivity/speed/state-volume limit')
        flat.extend(cell)
    if library is None: raise ValueError('Verified native flow library path required')
    library=Path(library).resolve()
    if not library.is_file():raise ValueError('Native flow library unavailable; compile banjo_flow_cpu')
    binary_hash=hashlib.sha256(library.read_bytes()).hexdigest();source=LOADED_SOURCE_SHA
    key=str(library)
    if key in LIBRARIES and LIBRARIES[key][0]!=binary_hash:raise ValueError('Flow native binary changed; restart the server')
    if key not in LIBRARIES:LIBRARIES[key]=(binary_hash,ctypes.CDLL(key))
    native=LIBRARIES[key][1]
    ptr=ctypes.POINTER(ctypes.c_double);native.banjo_flow_continue.argtypes=[ptr,ptr,ptr,ptr,ptr,ptr];native.banjo_flow_continue.restype=ctypes.c_int
    continuation=None
    if saved is not None:
        if saved['source_sha256']!=source or saved['native_sha256']!=binary_hash:raise ValueError('Flow checkpoint source/binary mismatch')
        if not isinstance(saved['continuation'],list) or len(saved['continuation'])!=12 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in saved['continuation']):raise ValueError('Invalid native flow continuation')
        instance=saved['instance']
        if not isinstance(instance,dict) or set(instance)!={'id','matter_ids','control_volume_ids'} or not isinstance(instance['id'],str):raise ValueError('Invalid persistent flow identity')
        try: uuid.UUID(instance['id'])
        except (ValueError,AttributeError):raise ValueError('Invalid persistent flow UUID')
        if instance['matter_ids']!=[instance['id']+'/matter-0'] or instance['control_volume_ids']!=[instance['id']+'/column-'+str(i) for i in range(nx*nz)]:raise ValueError('Changed stable flow matter mapping')
        old_initial=saved['initial_cells']
        if not isinstance(old_initial,list) or len(old_initial)!=nx*nz or any(not isinstance(c,list) or len(c)!=3 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in c) for c in old_initial):raise ValueError('Invalid initial flow reference state')
        baseline=[0.]*5
        for i,c in enumerate(old_initial):
            h,qx,qz=c
            if h<0 or h>2 or (h==0 and(qx or qz)) or (h>0 and math.hypot(qx,qz)/h>20):raise ValueError('Invalid initial flow reference state')
            x=(i%nx+.5)*dx;z=(i//nx+.5)*dx;area=dx*dx
            values=[rho*area*h,rho*area*qx,rho*area*qz,rho*area*(z*qx-x*qz),rho*area*(.5*gravity*h*h+(.5*(qx*qx+qz*qz)/h if h else 0))]
            baseline=[a+b for a,b in zip(baseline,values)]
        if any(abs(a-b)>1e-10*max(1,abs(a)) for a,b in zip(baseline,saved['continuation'][:5])):raise ValueError('Flow initial reference budget mismatch')
        continuation=(ctypes.c_double*12)(*saved['continuation'])
    else:
        key=str(uuid.uuid4());instance={'id':key,'matter_ids':[key+'/matter-0'],'control_volume_ids':[key+'/column-'+str(i) for i in range(nx*nz)]}
        old_initial=copy.deepcopy(initial)
    config=(ctypes.c_double*7)(nx,nz,dx,rho,gravity,duration,frames);inp=(ctypes.c_double*len(flat))(*flat)
    states=(ctypes.c_double*(frames*nx*nz*3))();accounts=(ctypes.c_double*(frames*18))()
    continued=(ctypes.c_double*12)()
    compute=time.perf_counter();status=native.banjo_flow_continue(config,inp,continuation,states,accounts,continued);compute_s=time.perf_counter()-compute
    if status:
        reason={-1:'invalid bounded state or allocation',-2:'positivity/finite/speed gate',-3:'numerical energy creation gate',-4:'bounded work or CFL interval',-5:'mass/momentum conservation account'}.get(status,'unknown native status')
        raise ValueError('Native flow refused: '+reason+'; initial scene unchanged')
    result=[]
    for f in range(frames):
        state=[[states[(f*nx*nz+i)*3+k] for k in range(3)] for i in range(nx*nz)]
        account={name:accounts[f*18+k] for k,name in enumerate(FIELDS) if name!='reserved'}
        result.append({'cells':state,'account':account})
    next_checkpoint=_seal_checkpoint({'schema':'banjo.flow-checkpoint.v1','source_sha256':source,'native_sha256':binary_hash,'declaration':{'nx':nx,'nz':nz,'dx_m':dx,'density_kg_m3':rho,'gravity_m_s2':gravity},'instance':instance,'cells':result[-1]['cells'],'initial_cells':old_initial,'continuation':list(continued)})
    return {'ok':True,'family':'flowing-matter','law':'flat-bed-saint-venant-rusanov-v1','source_sha256':source,'native_sha256':binary_hash,'checkpoint':next_checkpoint,
            'definition':{'id':hashlib.sha256(json.dumps([source,nx,nz,dx,rho,gravity],separators=(',',':')).encode()).hexdigest(),'material':{'density_kg_m3':rho,'phase':'liquid','law':'hydrostatic-depth-average-v1'},'grid':{'nx':nx,'nz':nz,'dx_m':dx},'gravity_m_s2':gravity},
            'instance':{**instance,'representation':'conservative-depth-columns','accepted_time_s':continued[5],'lineage_scope':'One conserved liquid volume; Eulerian columns are not persistent particles'},
            'frames':result,'measured':{'native_compute_s':compute_s,'request_compute_s':time.perf_counter()-start,'physical_s':duration,'native_realtime_ratio':duration/compute_s if compute_s else None},
            'limits':['Depth-averaged horizontal flow on flat fixed bed; columns are volumes, not rigid cubes.','No vertical jets, splashes, turbulence, viscosity, capillarity, solid-fluid wheel coupling or phase transfer.','Rusanov numerical energy/ angular transport reported separately; not physical heat or environmental drag.','Density controls inertia and hydrostatic pressure; entering glass/oak/iron density does not implement their liquid laws.']}
