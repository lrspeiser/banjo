"""Explicit NumPy/native CPU reference. Never imports CUDA or falls back to it."""
from pathlib import Path
import ctypes,hashlib,os
import numpy as np
from coupled_solver import CoupledNewton,TrialFailure
from coupled_world import CoupledWorld,declaration
from coupled_representations import FlightPartition
ROOT=Path(__file__).resolve().parents[1]
HEADERS=('src/physics/FiniteFrameKernel.hpp','src/physics/CohesiveInterfaceKernel.hpp',
 'src/material/ConnectorModeKernel.hpp','src/physics/MaterialHistoryKernel.hpp',
 'src/physics/NormalComplianceKernel.hpp','src/physics/CoupledGpuKernel.hpp','src/physics/CoupledFlightKernel.hpp')
SOURCES=('scripts/cpu_coupled_world.py','scripts/coupled_solver.py','scripts/coupled_world.py',
 'scripts/coupled_representations.py','scripts/object_registry.py','src/physics/CoupledCpuApi.cpp',
 *HEADERS,'client/voxel-lab/material-laws.json')
def disk_source_hash():
    h=hashlib.sha256()
    for name in SOURCES:h.update(name.encode());h.update(b'\0');h.update((ROOT/name).read_bytes().replace(b'\r\n',b'\n'))
    return h.hexdigest()
SOURCE=disk_source_hash()
LOADED_IMPLEMENTATION=None
def library_path():
    raw=os.environ.get('BANJO_COUPLED_CPU_LIBRARY')
    if not raw:raise RuntimeError('Configure BANJO_COUPLED_CPU_LIBRARY; no backend fallback')
    return Path(raw).resolve(strict=True)
def implementation_hash():
    global LOADED_IMPLEMENTATION
    # Compiler/platform binary differences make saved CPU scenes incompatible.
    h=hashlib.sha256();h.update(SOURCE.encode());h.update(library_path().read_bytes());h.update(np.__version__.encode())
    actual=h.hexdigest()
    if LOADED_IMPLEMENTATION is not None and actual!=LOADED_IMPLEMENTATION:raise RuntimeError('CPU binary changed; restart the process')
    LOADED_IMPLEMENTATION=actual
    return actual
def host(value):return np.asarray(value).copy()

class CpuCoupledEvaluator(CoupledNewton):
    array_api=np
    to_host=staticmethod(host)
    solve_linear=staticmethod(np.linalg.solve)
    def __init__(self,bodies,edges,pipeline='serial-reference',newton_strategy='ranked',line_search='batch-tail',linear_backend='numpy-reference'):
        self.n=len(bodies);self.m=len(edges)
        if not 1<=self.n<=32 or not 0<=self.m<=128:raise ValueError('Coupled scene exceeds reference capacity')
        if pipeline!='serial-reference' or linear_backend!='numpy-reference':raise ValueError('CPU reference requires serial-reference / numpy-reference')
        if newton_strategy not in ('ranked','single-reference') or line_search not in ('batch-tail','serial-reference'):raise ValueError('Unknown nonlinear strategy')
        self.bodies=np.ascontiguousarray(bodies,dtype=np.float64).reshape(self.n,30)
        self.edges=np.ascontiguousarray(edges,dtype=np.float64).reshape(self.m,70)
        if not np.isfinite(self.bodies).all() or not np.isfinite(self.edges).all():raise ValueError('Nonfinite coupled declaration')
        self.pipeline=pipeline;self.newton_strategy=newton_strategy;self.line_search=line_search;self.linear_backend=linear_backend;self.linear=None;self.last_solve=None;self.evaluations=0
        self.dynamic=np.flatnonzero(np.repeat(self.bodies[:,1]>0,6)).astype(np.int32)
        self.weights=np.sqrt(np.repeat(self.bodies[:,1:3],3,axis=1)).reshape(-1);self.active_weights=self.weights[self.dynamic]
        self.pairs=np.array([(a,b) for a in range(self.n) for b in range(a+1,self.n) if not self.bodies[a,1]==self.bodies[b,1]==0],dtype=np.uint32).reshape(-1,2)
        self.lib=ctypes.CDLL(str(library_path()))
        u=ctypes.c_uint;d=ctypes.c_double;p=np.ctypeslib.ndpointer(dtype=np.float64,flags='C_CONTIGUOUS');i=np.ctypeslib.ndpointer(dtype=np.int32,flags='C_CONTIGUOUS')
        self.lib.banjo_coupled_cpu_abi.restype=u
        if self.lib.banjo_coupled_cpu_abi()!=1:raise RuntimeError('Unknown CPU trial ABI')
        self.lib.banjo_coupled_cpu_trials.argtypes=[p,u,p,u,p,u,d,d,p,p,p,p,p,i];self.lib.banjo_coupled_cpu_trials.restype=ctypes.c_int
        self.lib.banjo_coupled_cpu_schedule.argtypes=[p,u,d,d,d,d,p];self.lib.banjo_coupled_cpu_schedule.restype=ctypes.c_int
        self.lib.banjo_coupled_cpu_flight.argtypes=[p,u,u,d,d,d,p,p,p,p,p];self.lib.banjo_coupled_cpu_flight.restype=ctypes.c_int
    def evaluate(self,velocity,h,gravity=-9.81,*,_jacobian_base=None):
        v=np.ascontiguousarray(velocity,dtype=np.float64).reshape(-1,self.n,6);batch=len(v)
        if not 1<=batch<=384:raise ValueError('Coupled trial batch exceeds reference bound')
        out=dict(poses=np.zeros((batch,self.n,7)),residual=np.zeros((batch,self.n,6)),history=np.zeros((batch,self.m,32)),forces=np.zeros((batch,self.n,6)),ledger=np.zeros((batch,12)),faults=np.zeros(batch,dtype=np.int32))
        code=self.lib.banjo_coupled_cpu_trials(self.bodies,self.n,self.edges,self.m,v,batch,h,gravity,*(out[k] for k in ('poses','residual','history','forces','ledger','faults')))
        if code:raise ValueError('Native CPU trial declaration refused')
        self.evaluations+=batch;return out
    def contact_schedule(self,h,phase,gravity=-9.81,velocity_tolerance=1e-4):
        if not len(self.pairs):return dict(step_s=h,frequency_rad_s=0.,excitation_m_s=0.,pair=None)
        out=np.zeros((len(self.pairs),3));code=self.lib.banjo_coupled_cpu_schedule(self.bodies,self.n,h,gravity,phase,velocity_tolerance,out)
        if code!=len(self.pairs) or not np.isfinite(out).all():raise TrialFailure('Native CPU contact schedule refused')
        idx=int(np.argmin(out[:,0]));row=out[idx]
        if not 0<row[0]<=h:raise TrialFailure('Invalid CPU contact timestep estimate')
        return dict(step_s=float(row[0]),frequency_rad_s=float(row[1]),excitation_m_s=float(row[2]),pair=self.pairs[idx].tolist(),velocity_tolerance_m_s=velocity_tolerance)
    def flight_bounds(self,sphere,h,gravity,travel_bound,bounds):
        buffers=[np.empty(n) for n in (7,6,6,6)]
        if self.lib.banjo_coupled_cpu_flight(self.bodies,self.n,sphere,h,gravity,travel_bound,bounds,*buffers):raise TrialFailure('CPU swept flight refused')
    def flight_step(self,sphere,h,gravity,poses,velocity,forces,residual):
        if self.lib.banjo_coupled_cpu_flight(self.bodies,self.n,sphere,h,gravity,0.,np.empty(self.n),poses,velocity,forces,residual):raise TrialFailure('CPU isolated flight refused')

class CpuCoupledWorld(CoupledWorld):
    array_api=np
    to_host=staticmethod(host)
    evaluator_type=CpuCoupledEvaluator
    flight_partition=FlightPartition
    declaration=staticmethod(lambda raw:declaration(raw,device='cpu',pipeline='serial-reference',linear='numpy-reference',pipelines=('serial-reference',),linears=('numpy-reference',)))
    source_hash=staticmethod(implementation_hash)
    device='cpu';gpu=False
    state_schema='banjo.cpu-coupled-finite-cells.v1'
    backend_name='cpu-implicit-body'
    @staticmethod
    def ensure_source_current():
        if disk_source_hash()!=SOURCE:raise RuntimeError('CPU implementation changed; restart the worker')
    @staticmethod
    def synchronize():pass
