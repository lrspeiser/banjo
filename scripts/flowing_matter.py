"""Bounded native hydrostatic flow reference; no synthetic render motion."""
import ctypes
import hashlib
import math
import json
import uuid
from pathlib import Path
import time

ROOT = Path(__file__).resolve().parents[1]
FIELDS = ['time_s','mass_kg','momentum_x_n_s','momentum_z_n_s','angular_y_n_m_s','mechanical_energy_j',
          'wall_impulse_x_n_s','wall_impulse_z_n_s','wall_angular_impulse_y_n_m_s','numerical_angular_y_n_m_s',
          'numerical_energy_j','mass_residual_kg','momentum_x_residual_n_s','momentum_z_residual_n_s',
          'angular_y_residual_n_m_s','energy_residual_j','substeps','reserved']

def source_hash():
    digest = hashlib.sha256()
    for name in ['src/flow/FlowReference.hpp','src/flow/FlowReference.cpp','src/flow/FlowCpuApi.cpp','scripts/flowing_matter.py']:
        digest.update(name.encode()); digest.update((ROOT/name).read_bytes())
    return digest.hexdigest()

def run(declaration, library=None):
    start = time.perf_counter()
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
        if not 0<=h<=2 or (h==0 and (qx or qz)) or (h>0 and math.hypot(qx,qz)/h>20):raise ValueError('Initial flow cell positivity/speed limit')
        flat.extend(cell)
    if library is None: raise ValueError('Verified native flow library path required')
    library=Path(library).resolve()
    if not library.is_file():raise ValueError('Native flow library unavailable; compile banjo_flow_cpu')
    binary_hash=hashlib.sha256(library.read_bytes()).hexdigest();source=source_hash();native=ctypes.CDLL(str(library))
    ptr=ctypes.POINTER(ctypes.c_double);native.banjo_flow_run.argtypes=[ptr,ptr,ptr,ptr];native.banjo_flow_run.restype=ctypes.c_int
    config=(ctypes.c_double*7)(nx,nz,dx,rho,gravity,duration,frames);inp=(ctypes.c_double*len(flat))(*flat)
    states=(ctypes.c_double*(frames*nx*nz*3))();accounts=(ctypes.c_double*(frames*18))()
    compute=time.perf_counter();status=native.banjo_flow_run(config,inp,states,accounts);compute_s=time.perf_counter()-compute
    if status:
        reason={-1:'invalid bounded state or allocation',-2:'positivity/finite/speed gate',-3:'numerical energy creation gate',-4:'bounded work or CFL interval',-5:'mass/momentum conservation account'}.get(status,'unknown native status')
        raise ValueError('Native flow refused: '+reason+'; initial scene unchanged')
    result=[]
    for f in range(frames):
        state=[[states[(f*nx*nz+i)*3+k] for k in range(3)] for i in range(nx*nz)]
        account={name:accounts[f*18+k] for k,name in enumerate(FIELDS) if name!='reserved'}
        result.append({'cells':state,'account':account})
    return {'ok':True,'family':'flowing-matter','law':'flat-bed-saint-venant-rusanov-v1','source_sha256':source,'native_sha256':binary_hash,
            'definition':{'id':hashlib.sha256(json.dumps([source,nx,nz,dx,rho,gravity],separators=(',',':')).encode()).hexdigest(),'material':{'density_kg_m3':rho,'phase':'liquid','law':'hydrostatic-depth-average-v1'},'grid':{'nx':nx,'nz':nz,'dx_m':dx},'gravity_m_s2':gravity},
            'instance':{'id':str(uuid.uuid4()),'representation':'conservative-depth-columns','matter_ids':['water-volume-0'],'control_volume_ids':['flow-column-'+str(i) for i in range(nx*nz)],'accepted_time_s':duration,'lineage_scope':'One conserved liquid volume; Eulerian columns are not persistent particles'},
            'frames':result,'measured':{'native_compute_s':compute_s,'request_compute_s':time.perf_counter()-start,'physical_s':duration,'native_realtime_ratio':duration/compute_s if compute_s else None},
            'limits':['Depth-averaged horizontal flow on flat fixed bed; columns are volumes, not rigid cubes.','No vertical jets, splashes, turbulence, viscosity, capillarity, solid-fluid wheel coupling or phase transfer.','Rusanov numerical energy/ angular transport reported separately; not physical heat or environmental drag.','Density controls inertia and hydrostatic pressure; entering glass/oak/iron density does not implement their liquid laws.']}
