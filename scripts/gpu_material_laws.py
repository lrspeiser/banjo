"""Shared C++ constitutive laws on resident CUDA arrays via CuPy.

Controlled interface loading, NOT a coupled world/contact integrator. No
trajectory, gravity, fracture impulse, heat or material-name outcome rule.
"""
from __future__ import annotations
import copy
import hashlib
import json
import math
from pathlib import Path
import time
import cupy as cp
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ('scripts/gpu_material_laws.py', 'src/physics/CohesiveInterfaceKernel.hpp',
           'src/material/ConnectorModeKernel.hpp', 'client/voxel-lab/material-laws.json',
           'src/material/MaterialCatalog.cpp', 'src/material/ConnectorPlasticity.cpp',
           'src/physics/CohesiveInterface.cpp')


def source_hash():
    h = hashlib.sha256()
    for name in SOURCES:
        h.update(name.encode()); h.update(b'\0'); h.update((ROOT/name).read_bytes())
    return h.hexdigest()


KERNEL = r'''
extern "C" __global__ void update_laws(const int* kinds,const double* laws,
    const double* coefficients,const double* before,const double* coordinates,
    double* after,int* faults,unsigned n,int unload){
    const unsigned i=blockDim.x*blockIdx.x+threadIdx.x;if(i>=n)return;
    const double* s=before+32*i;double* o=after+32*i;
    for(unsigned j=0;j<32;++j)o[j]=s[j];
    if(kinds[i]==0){
        const double* l=laws+5*i;
        const banjo::CohesiveInterfaceLaw law{l[0],l[1],l[2],l[3],l[4]};
        const auto r=banjo::advanceCohesiveInterfaceUnchecked(law,{s[0],s[1]},unload?0:coordinates[6*i]);
        o[0]=r.state.opening_m;o[1]=r.state.maximum_opening_m;
        o[2]=r.response.force_n;o[3]=r.response.stored_energy_j;
        o[4]=r.response.dissipated_energy_j;o[5]=r.response.damage;
        o[6]=r.response.separated?1:0;o[7]+=r.opening_work_j;
        o[8]=r.opening_work_j;o[9]=r.dissipated_increment_j;
        o[10]=r.balance_residual_j;o[11]=r.work_conjugate_force_n;
    }else{
        double work=0,stored=0,plastic=0,excess=0;bool yielded=false;
        for(unsigned j=0;j<6;++j){
            const double k=coefficients[12*i+j],y=coefficients[12*i+6+j];
            const double q=unload?s[j]:coordinates[6*i+j];
            const double prior=s[22+j]-s[j],trial=q-s[j];
            work+=(.5*k)*(trial+prior)*(trial-prior);
            const auto r=banjo::connectorModeReturnUnchecked(k,y,q,s[j],s[6+j]);
            o[j]=r.plastic_rest;o[6+j]=r.accumulated_flow;o[22+j]=q;
            plastic+=r.plastic_increment_j;excess+=r.return_excess_increment_j;
            stored+=r.stored_energy_j;yielded|=r.yielded;
        }
        o[12]+=plastic;o[13]+=excess;if(yielded)o[14]+=1;
        o[15]=stored;o[16]+=work;o[17]=work;
        o[18]=work-(stored-s[15])-plastic-excess;
        o[19]=coefficients[12*i]*(o[22]-o[0]);o[20]=plastic;o[21]=excess;
    }
    int fault=0;for(unsigned j=0;j<32;++j)if(!isfinite(o[j]))fault=1;
    faults[i]=fault;
}
'''


class ResidentLaws:
    """Arrays/immutable coefficients stay on CUDA until an explicit reset.

    Each accepted update swaps two resident history arrays. Failed finite/work
    gates leave both the accepted state and cumulative performance unchanged.
    """
    def __init__(self, profiles, models=None):
        if (cp.__version__, np.__version__) != ('13.5.1', '2.5.3'):
            raise RuntimeError('Unverified CuPy/NumPy runtime; install scripts/gpu-requirements.txt')
        self.device=cp.cuda.Device(0);self.device.use()
        if not 1 <= len(profiles) <= 65536:
            raise ValueError('Interface count must be 1-65536')
        self.profiles = copy.deepcopy(profiles)
        self.models = models or [p['display_model'] for p in profiles]
        if len(self.models) != len(profiles) or any(m not in ('normal-cohesive','connector-plastic') for m in self.models):
            raise ValueError('Invalid model declaration')
        kinds, laws, coeff = [], [], []
        for p, model in zip(profiles, self.models):
            l = p['cohesive_law']
            if len(l)!=5 or not all(type(x) in (float,int) and math.isfinite(x) for x in l) or min(l[:4])<=0 or l[4]<0 or 2*l[2]/l[1]<=l[1]/l[0]:
                raise ValueError('Invalid cohesive parameters')
            kinds.append(int(model=='connector-plastic')); laws.append(l)
            k,y = p.get('connector_stiffness',[1.]*6),p.get('connector_yield_load',[1.]*6)
            if model=='connector-plastic' and ('connector_stiffness' not in p or 'connector_yield_load' not in p):
                raise ValueError('Connector coefficients required')
            if len(k)!=6 or len(y)!=6 or any(type(x) not in (float,int) or not math.isfinite(x) or x<=0 for x in [*k,*y]):
                raise ValueError('Invalid connector coefficients')
            coeff.append([*k,*y])
        code = '\n'.join((ROOT/name).read_text(encoding='utf8').replace('#pragma once','') for name in SOURCES[1:3]) + '\n' + KERNEL
        # Embed complete shared headers, so CuPy's source cache invalidates on
        # actual constitutive edits rather than ignoring included-file changes.
        module = cp.RawModule(code=code,options=('--std=c++17','--fmad=false'))
        self.kernel = module.get_function('update_laws')
        self.kinds = cp.asarray(kinds,dtype=cp.int32)
        self.laws = cp.asarray(laws,dtype=cp.float64)
        self.coefficients = cp.asarray(coeff,dtype=cp.float64)
        self.state = cp.zeros((len(profiles),32),dtype=cp.float64)
        self.candidate = cp.empty_like(self.state)
        self.faults = cp.zeros(len(profiles),dtype=cp.int32)
        self.coordinates = cp.zeros((len(profiles),6),dtype=cp.float64)
        self.host = np.zeros((len(profiles),32))
        self.updates = 0; self.last_ms = 0.; self.total_s = 0.
        self.gpu_ms = 0.; self.readback_ms = 0.; self.audit_ms = 0.
        self.hash = source_hash()
        props=cp.cuda.runtime.getDeviceProperties(0)
        self.device_name=props['name'].decode() if isinstance(props['name'],bytes) else props['name']
        # Warm code/allocations; this zero-load calculation is not accepted
        # history, startup is explicitly excluded from per-control timings.
        self._launch(False); cp.cuda.get_current_stream().synchronize()

    def _launch(self, unload):
        self.kernel(((len(self.profiles)+127)//128,), (128,),
            (self.kinds,self.laws,self.coefficients,self.state,self.coordinates,
             self.candidate,self.faults,np.uint32(len(self.profiles)),np.int32(unload)))

    def update(self, coordinates, unload=False):
        self.device.use()
        q=np.asarray(coordinates,dtype=np.float64)
        if q.shape!=(len(self.profiles),6) or not np.isfinite(q).all() or np.max(np.abs(q[:,:3]))>.001 or np.max(np.abs(q[:,3:]))>.1:
            raise ValueError('Invalid bounded interface coordinates')
        if type(unload) is not bool:raise ValueError('Unload must be boolean')
        started=time.perf_counter(); self.coordinates.set(q)
        a,b=cp.cuda.Event(),cp.cuda.Event();a.record();self._launch(unload);b.record();b.synchronize()
        gpu_ms=cp.cuda.get_elapsed_time(a,b)
        before_read=time.perf_counter();candidate=cp.asnumpy(self.candidate);faults=cp.asnumpy(self.faults)
        before_audit=time.perf_counter()
        if np.any(faults) or not np.isfinite(candidate).all():
            raise RuntimeError('GPU material law produced nonfinite state; accepted history retained')
        cohesive=np.asarray([m=='normal-cohesive' for m in self.models]);plastic=~cohesive
        residual=np.where(cohesive,candidate[:,10],candidate[:,18])
        scale=np.where(cohesive,np.abs(candidate[:,8]),np.abs(candidate[:,17]))
        if np.any(np.abs(residual)>1e-11*np.maximum(1.,scale)):
            raise RuntimeError('Constitutive work gate refused; accepted GPU history retained')
        if np.any(candidate[cohesive,4]<self.host[cohesive,4]) or np.any(candidate[cohesive,1]<self.host[cohesive,1]) or np.any(candidate[plastic,12:14]<self.host[plastic,12:14]):
            raise RuntimeError('Irreversible history decreased; accepted GPU history retained')
        self.state,self.candidate=self.candidate,self.state
        self.host=candidate;self.updates+=1
        self.last_ms=(time.perf_counter()-started)*1000;self.total_s+=self.last_ms/1000
        self.gpu_ms=gpu_ms;self.readback_ms=(before_audit-before_read)*1000
        self.audit_ms=(time.perf_counter()-before_audit)*1000
        return candidate.copy()


class GpuMaterialWorld:
    def __init__(self, raw):
        if raw not in ({}, {'device':'cuda:0'}):
            raise ValueError('Material inspector accepts only the CUDA device declaration')
        self.profiles=json.loads((ROOT/'client/voxel-lab/material-laws.json').read_text(encoding='utf8'))['profiles']
        self.laws=ResidentLaws(self.profiles)

    def strain(self, opening_m=None, unload=False):
        if type(unload) is not bool:raise ValueError('Unload must be boolean')
        if unload:
            if opening_m is not None:raise ValueError('Unload has no target opening')
        elif type(opening_m) not in (float,int) or not math.isfinite(opening_m) or not 0<=opening_m<=.00005:
            raise ValueError('Opening must be 0-50 micrometres')
        q=np.zeros((4,6));q[:,0]=opening_m or 0
        self.laws.update(q,unload=unload)
        return self.snapshot()

    def snapshot(self):
        rows=[]
        for p,m,s in zip(self.profiles,self.laws.models,self.laws.host):
            plastic=m=='connector-plastic'
            rows.append(dict(material=p['material'],model=m,cell_size_m=p['cell_size_m'],
                mass_kg=2*p['density_kg_m3']*p['cell_size_m']**3,
                opening_m=float(s[22] if plastic else s[0]),
                permanent_rest_m=float(s[0] if plastic else 0),
                force_n=float(s[19] if plastic else s[2]),stored_energy_j=float(s[15] if plastic else s[3]),
                physical_dissipation_j=float(s[12] if plastic else s[4]),
                numerical_return_excess_j=float(s[13] if plastic else 0),
                loading_work_j=float(s[16] if plastic else s[7]),
                balance_residual_j=float(s[18] if plastic else s[10]),
                damage=float(0 if plastic else s[5]),separated=bool(not plastic and s[6]),yielded_updates=int(s[14]) if plastic else 0))
        return dict(schema='banjo.cupy-material-laws.v1',time_s=0.,dt_s=None,ticks=self.laws.updates,
            controlled_loading=True,coupons=rows,history_arrays=self.laws.host.tolist(),
            performance=dict(last_control_ms=self.laws.last_ms,kernel_ms=self.laws.gpu_ms,
                readback_ms=self.laws.readback_ms,audit_ms=self.laws.audit_ms,total_s=self.laws.total_s,
                excludes_startup=True,no_physical_time=True),
            qualification=dict(backend='cupy-material-laws',gpu=True,device='cuda:0',device_name=self.laws.device_name,
                source_sha256=self.laws.hash,dtype='float64',cupy=cp.__version__,shared_cpp=True,
                complete_physics_validated=False,realtime_qualified=False,
                scope='Controlled normal-opening law and six-mode perfect-plastic return; no coupled dynamics, collision, grain, heat, continuum plasticity or automatic fracture launch.'))
