"""Experimental FP64 CUDA implicit finite-cell assembly and compliant contact.

CPU/CUDA trial equations share C++ source. Rendering never enters the solve.
Every trial is private; a whole requested interval rolls back on refusal.
"""
from pathlib import Path
import copy
import hashlib
import json
import math
import time
import cupy as cp
import cupyx
import numpy as np
from gpu_representations import FlightPartition, KERNEL as REPRESENTATION_KERNEL
from coupled_solver import CoupledNewton,TrialFailure
from coupled_world import CoupledWorld,declaration
ROOT=Path(__file__).resolve().parents[1]
HEADERS=('src/physics/FiniteFrameKernel.hpp','src/physics/CohesiveInterfaceKernel.hpp',
 'src/material/ConnectorModeKernel.hpp','src/physics/MaterialHistoryKernel.hpp',
 'src/physics/NormalComplianceKernel.hpp','src/physics/CoupledGpuKernel.hpp','src/physics/CoupledFlightKernel.hpp')
SOURCES=('scripts/coupled_representations.py','scripts/coupled_solver.py','scripts/coupled_world.py','scripts/gpu_coupled_world.py','scripts/gpu_linear_solve.py','scripts/gpu_representations.py','scripts/object_registry.py',*HEADERS,'client/voxel-lab/material-laws.json')
def _disk_source_hash():
    h=hashlib.sha256()
    for name in SOURCES:h.update(name.encode());h.update(b'\0');h.update((ROOT/name).read_bytes())
    return h.hexdigest()

# Evidence identifies the loaded implementation, even if source files change
# while a long experiment is running. New worlds refuse a mixed-version worker.
LOADED_SOURCE_SHA256=_disk_source_hash()
def source_hash():return LOADED_SOURCE_SHA256

KERNEL=r'''
extern "C" __global__ void plan_contact_steps(const double *bodies,const unsigned *pairs,unsigned count,double h,double gy,
    double phase,double velocity_tolerance,double *output){
    const unsigned i=blockDim.x*blockIdx.x+threadIdx.x;if(i>=count)return;
    const double *a=bodies+30*pairs[2*i],*b=bodies+30*pairs[2*i+1];double va[6],vb[6];
    for(unsigned j=0;j<6;++j){va[j]=a[14+j];vb[j]=b[14+j];}
    if(a[1]>0)va[1]+=h*gy;if(b[1]>0)vb[1]+=h*gy;
    const auto fa=banjo::dgPrepareTrial(a,va,h),fb=banjo::dgPrepareTrial(b,vb,h);
    const auto r=banjo::dgContactSchedule(a,b,fa.initial,fb.initial,fa.ending,fb.ending,h,phase,velocity_tolerance);
    output[3*i]=r.step_s;output[3*i+1]=r.frequency_rad_s;output[3*i+2]=r.excitation_m_s;
}
extern "C" __global__ void coupled_trials(const double *bodies,unsigned n,const double *edges,unsigned m,
    const double *velocity,unsigned batch,double h,double gy,double *poses,double *residual,
    double *histories,double *forces,double *ledger,int *faults){
    const unsigned i=blockDim.x*blockIdx.x+threadIdx.x;if(i>=batch)return;
    faults[i]=banjo::coupledTrialUnchecked(bodies,n,edges,m,velocity+6*n*i,h,{0,gy,0},
        poses+7*n*i,residual+6*n*i,histories+32*m*i,forces+6*n*i,ledger+12*i);
}
extern "C" __global__ void prepare_trials(const double *bodies,unsigned n,const double *velocity,unsigned batch,double h,
    banjo::DGTrialBody *prepared,double *poses){
    const unsigned k=blockDim.x*blockIdx.x+threadIdx.x;if(k>=n*batch)return;const unsigned body=k%n;
    const auto p=banjo::dgPrepareTrial(bodies+30*body,velocity+6*k,h);prepared[k]=p;
    banjo::dgWrite3(poses+7*k,p.ending.p);banjo::dgWrite4(poses+7*k+3,p.ending.q);
}
extern "C" __global__ void prepare_initial_pairs(const double *bodies,const unsigned *pairs,unsigned pair_count,
    const banjo::DGTrialBody *prepared,unsigned char *initial_active){
    const unsigned pair=blockDim.x*blockIdx.x+threadIdx.x;if(pair>=pair_count)return;
    const unsigned a=pairs[2*pair],b=pairs[2*pair+1];
    const auto before=banjo::dgContact(bodies+30*a,bodies+30*b,prepared[a].initial,prepared[b].initial);
    initial_active[pair]=before.gap>0?0:1;
}
extern "C" __global__ void prepare_pairs(const double *bodies,unsigned n,const unsigned *pairs,unsigned pair_count,unsigned batch,
    const banjo::DGTrialBody *prepared,const unsigned char *initial_active,unsigned char *active,int localized,const int *changed_body,const unsigned char *base_active){
    const unsigned k=blockDim.x*blockIdx.x+threadIdx.x;if(k>=pair_count*batch)return;
    const unsigned candidate=k/pair_count,pair=k%pair_count,a=pairs[2*pair],b=pairs[2*pair+1];
    if(localized&&a!=static_cast<unsigned>(changed_body[candidate])&&b!=static_cast<unsigned>(changed_body[candidate])){active[k]=base_active[pair];return;}
    if(initial_active[pair]){active[k]=1;return;}
    const auto p=prepared+n*candidate;
    const auto after=banjo::dgContact(bodies+30*a,bodies+30*b,p[a].ending,p[b].ending);
    active[k]=after.gap>0?0:1;
}
extern "C" __global__ void contribution_trials(const double *bodies,unsigned n,const double *edges,unsigned m,
    const unsigned *jobs,unsigned rows,unsigned pair_count,unsigned batch,const banjo::DGTrialBody *prepared,const unsigned char *pair_active,double h,
    banjo::FiniteFrameWrenches *wrenches,double *ledgers,double *history,unsigned char *active,int *faults,
    int localized,const int *changed_body,const banjo::FiniteFrameWrenches *base_wrenches,const double *base_ledger,
    const double *base_history,const unsigned char *base_active,const int *base_faults){
    const unsigned k=blockDim.x*blockIdx.x+threadIdx.x;if(k>=rows*batch)return;
    const unsigned candidate=k/rows,row=k%rows;double *ledger=ledgers+12*k;for(unsigned j=0;j<12;++j)ledger[j]=0;
    unsigned a,b;if(row<m){const double *edge=edges+70*row;a=static_cast<unsigned>(edge[0]);b=static_cast<unsigned>(edge[1]);}
    else {const unsigned *job=jobs+4*(row-m);a=job[0];b=job[1];}
    if(localized&&a!=static_cast<unsigned>(changed_body[candidate])&&b!=static_cast<unsigned>(changed_body[candidate])){
        // Within ONE Jacobian, all unaffected pairs have exactly the same two
        // poses, velocities, histories, material law and dt as the fresh base.
        // Reuse their exact contributions; final gathering/order is unchanged.
        // This is not cross-time outcome caching or approximate fracture reuse.
        wrenches[k]=base_wrenches[row];active[k]=base_active[row];faults[k]=base_faults[row];
        for(unsigned j=0;j<12;++j)ledger[j]=base_ledger[12*row+j];
        if(row<m)for(unsigned j=0;j<32;++j)history[32*(candidate*m+row)+j]=base_history[32*row+j];
        return;
    }
    banjo::FiniteFrameWrenches w{};int fault=0;bool touched=false;const auto p=prepared+n*candidate;
    if(row<m){const double *edge=edges+70*row;
        double *s=history+32*(candidate*m+row);
        fault=banjo::dgMaterialTrial(bodies+30*a,bodies+30*b,edge,p[a],p[b],s,w,ledger);touched=true;
        if(!fault)for(unsigned j=0;j<32;++j)if(!banjo::dgFinite(s[j])){fault=6;break;}
    }else {const unsigned *job=jobs+4*(row-m);
        if(pair_active[candidate*pair_count+job[3]])fault=banjo::dgContactTrial(bodies+30*a,bodies+30*b,p[a],p[b],job[2],h,w,ledger,touched,true);
    }
    wrenches[k]=w;active[k]=touched?1:0;faults[k]=fault;
}
extern "C" __global__ void gather_body_trials(const double *bodies,unsigned n,unsigned rows,unsigned batch,
    const unsigned *offsets,const unsigned *incidence,const double *velocity,const double *wrenches,const unsigned char *active,
    double h,double gy,double *forces,double *residual,int *faults){
    const unsigned k=blockDim.x*blockIdx.x+threadIdx.x;if(k>=6*n*batch)return;const unsigned candidate=k/(6*n),body=(k/6)%n,column=k%6;
    const double *b=bodies+30*body,*v=velocity+k-column;const auto gravity=banjo::frameScale({0,gy,0},b[1]);
    const double initial[6]{gravity.x,gravity.y,gravity.z,0,0,0};double f=initial[column];
    for(unsigned i=offsets[body];i<offsets[body+1];++i){const unsigned code=incidence[i],row=code/2,side=code%2;
        const unsigned record=candidate*rows+row;if(!active[record])continue;
        const double *w=wrenches+12*record+6*side;f+=w[column];
    }
    const double mass=column<3?b[1]:b[2],root=sqrt(mass);
    const double r=mass>0?(v[column]-b[14+column])*root-h*f/root:0;forces[k]=f;residual[k]=r;
    faults[k]=!banjo::dgFinite(f)||!banjo::dgFinite(r)?5:0;
}
extern "C" __global__ void gather_ledger_trials(unsigned rows,unsigned batch,const double *input,double *ledger){
    const unsigned k=blockDim.x*blockIdx.x+threadIdx.x;if(k>=12*batch)return;const unsigned candidate=k/12,column=k%12;
    double total=0;for(unsigned row=0;row<rows;++row){const double value=input[12*(candidate*rows+row)+column];
        if(column==8){if(value>total)total=value;}else total+=value;
    }ledger[k]=total;
}
extern "C" __global__ void gather_active_ledger_trials(unsigned rows,unsigned edges,unsigned pairs,unsigned batch,
    const unsigned *pair_offsets,const unsigned char *pair_active,const double *input,double *ledger){
    const unsigned k=blockDim.x*blockIdx.x+threadIdx.x;if(k>=12*batch)return;
    const unsigned candidate=k/12,column=k%12;double total=0;
    // Constitutive rows are always present, including failed private trials.
    // Contact rows are contiguous in the reference pair/site order. A pair
    // rejected by prepare_pairs has exactly zero work for every site; only
    // those zeros are omitted. Keep all nonzero additions and max operations
    // in their original order: this is no reordered floating reduction.
    for(unsigned row=0;row<edges;++row){const double value=input[12*(candidate*rows+row)+column];
        if(column==8){if(value>total)total=value;}else total+=value;
    }
    for(unsigned pair=0;pair<pairs;++pair){if(!pair_active[candidate*pairs+pair])continue;
        for(unsigned row=pair_offsets[pair];row<pair_offsets[pair+1];++row){
            const double value=input[12*(candidate*rows+row)+column];
            if(column==8){if(value>total)total=value;}else total+=value;
        }
    }ledger[k]=total;
}
extern "C" __global__ void collect_trial_faults(unsigned n,unsigned rows,unsigned batch,const int *contributions,
    const int *body_faults,const double *poses,const double *ledger,int *faults){
    const unsigned candidate=blockIdx.x;if(candidate>=batch)return;
    // Integer minimum preserves reference fault precedence and the earliest
    // contribution row. This is NOT a reordered floating force/work reduction.
    __shared__ unsigned first;if(threadIdx.x==0)first=rows+4;__syncthreads();
    for(unsigned r=threadIdx.x;r<rows;r+=blockDim.x){const int f=contributions[candidate*rows+r];
        if(f)atomicMin(&first,f==6?rows+1:r);
    }
    for(unsigned j=threadIdx.x;j<6*n;j+=blockDim.x)if(body_faults[candidate*6*n+j])atomicMin(&first,rows);
    for(unsigned j=threadIdx.x;j<7*n;j+=blockDim.x)if(!banjo::dgFinite(poses[7*n*candidate+j]))atomicMin(&first,rows+2);
    for(unsigned j=threadIdx.x;j<12;j+=blockDim.x)if(!banjo::dgFinite(ledger[12*candidate+j]))atomicMin(&first,rows+3);
    __syncthreads();
    if(threadIdx.x==0)faults[candidate]=first<rows?contributions[candidate*rows+first]:first==rows?5:first==rows+1?6:first==rows+2?7:first==rows+3?8:0;
}
'''
class CoupledEvaluator(CoupledNewton):
    array_api=cp
    to_host=staticmethod(cp.asnumpy)
    @staticmethod
    def solve_linear(matrix,rhs):
        with cupyx.errstate(linalg="raise"):return cp.linalg.solve(matrix,rhs)

    def __init__(self,bodies,edges,pipeline='parallel',newton_strategy='ranked',line_search='batch-tail',linear_backend='cupy-reference'):
        if (cp.__version__,np.__version__)!=('13.5.1','2.5.3'):raise RuntimeError('Unverified coupled runtime')
        cp.cuda.Device(0).use()
        # Shared finite contact dispatch has bounded two-level calls and local
        # 32-body arrays. The CUDA default 1 KiB call stack is insufficient.
        # Explicit capacity, no CPU fallback or silent recursion truncation.
        if cp.cuda.runtime.deviceGetLimit(cp.cuda.runtime.cudaLimitStackSize)<16384:
            cp.cuda.runtime.deviceSetLimit(cp.cuda.runtime.cudaLimitStackSize,16384)
        self.n=len(bodies);self.m=len(edges)
        if not 1<=self.n<=32 or not 0<=self.m<=128:raise ValueError('Coupled scene exceeds declared reference capacity')
        self.bodies=cp.asarray(bodies,dtype=cp.float64).reshape(self.n,30)
        self.edges=cp.asarray(edges,dtype=cp.float64).reshape(self.m,70)
        if not bool(cp.isfinite(self.bodies).all()) or not bool(cp.isfinite(self.edges).all()):raise ValueError('Nonfinite coupled declaration')
        code='\n'.join((ROOT/name).read_text(encoding='utf8').replace('#pragma once','') for name in HEADERS)+'\n'+KERNEL+REPRESENTATION_KERNEL
        self.module=cp.RawModule(code=code,options=('--std=c++17','--fmad=false'))
        if pipeline not in ('parallel','serial-reference'):raise ValueError('Unknown coupled trial pipeline')
        if newton_strategy not in ('ranked','single-reference'):raise ValueError('Unknown Newton starting strategy')
        if line_search not in ('batch-tail','serial-reference'):raise ValueError('Unknown Newton line search')
        self.line_search=line_search
        self.newton_strategy=newton_strategy;self.last_solve=None
        self.pipeline=pipeline;self.kernel=self.module.get_function('coupled_trials');self.storage={};self.evaluations=0
        self.phases={name:self.module.get_function(name) for name in ('prepare_trials','prepare_initial_pairs','prepare_pairs','contribution_trials','gather_body_trials','gather_ledger_trials','gather_active_ledger_trials','collect_trial_faults')}
        host_b=np.asarray(bodies);jobs=[];pairs=[]
        for a in range(self.n):
            for b in range(a+1,self.n):
                if host_b[a,1]==host_b[b,1]==0:continue
                pair=len(pairs);pairs.append((a,b))
                sa=host_b[a,0]==1 and host_b[b,0]!=2;sb=host_b[b,0]==1 and host_b[a,0]!=2
                for site in range(48 if sa and sb else 24 if sa or sb else 1):jobs.append((a,b,site,pair))
        self.jobs=cp.asarray(np.array(jobs,dtype=np.uint32).reshape(-1,4));self.rows=self.m+len(jobs)
        self.pairs=cp.asarray(np.array(pairs,dtype=np.uint32).reshape(-1,2));self.pair_count=len(pairs)
        # Symbolic row groups only; contact activity is recomputed on CUDA for
        # every private candidate, including every derivative perturbation.
        pair_sizes=np.bincount(np.array(jobs,dtype=np.uint32).reshape(-1,4)[:,3],minlength=self.pair_count)
        self.pair_offsets=cp.asarray(self.m+np.r_[0,np.cumsum(pair_sizes)],dtype=cp.uint32)
        self.plan_kernel=self.module.get_function('plan_contact_steps');self.plan_buffer=cp.empty((self.pair_count,3),dtype=cp.float64)
        incidence=[[] for _ in range(self.n)]
        for row,edge in enumerate(np.asarray(edges).reshape(self.m,70)):
            incidence[int(edge[0])].append(2*row);incidence[int(edge[1])].append(2*row+1)
        for index,(a,b,_,_) in enumerate(jobs):
            incidence[a].append(2*(self.m+index));incidence[b].append(2*(self.m+index)+1)
        self.offsets=cp.asarray(np.r_[0,np.cumsum([len(row) for row in incidence])],dtype=cp.uint32)
        self.incidence=cp.asarray([code for row in incidence for code in row],dtype=cp.uint32)
        self.dynamic=cp.asarray(np.flatnonzero(np.repeat(np.asarray(bodies)[:,1]>0,6)),dtype=cp.int32)
        self.jacobian_changed=cp.tile(self.dynamic//6,2)
        self.weights=cp.sqrt(cp.repeat(self.bodies[:,1:3],3,axis=1)).reshape(-1)
        self.active_weights=self.weights[self.dynamic]
        if linear_backend not in ('cupy-reference','native-cusolver'):raise ValueError('Unknown coupled linear backend')
        self.linear_backend=linear_backend;self.linear=None
        if linear_backend=='native-cusolver' and len(self.dynamic):
            from gpu_linear_solve import ResidentLinearSolve
            self.linear=ResidentLinearSolve(len(self.dynamic))

    def flight_bounds(self,sphere,h,gravity,travel_bound,bounds):
        self.module.get_function('isolated_sphere_bounds')(((self.n+127)//128,),(128,),
            (self.bodies,np.uint32(self.n),np.uint32(sphere),np.float64(h),np.float64(gravity),np.float64(travel_bound),bounds))

    def flight_step(self,sphere,h,gravity,poses,velocity,forces,residual):
        self.module.get_function('isolated_sphere_step')((1,),(1,),
            (self.bodies,np.uint32(sphere),np.float64(h),np.float64(gravity),poses,velocity,forces,residual))

    def contact_schedule(self,h,phase,gravity=-9.81,velocity_tolerance=1e-4):
        if not self.pair_count:return dict(step_s=h,frequency_rad_s=0.,excitation_m_s=0.,pair=None)
        self.plan_kernel(((self.pair_count+127)//128,),(128,),
            (self.bodies,self.pairs,np.uint32(self.pair_count),np.float64(h),np.float64(gravity),np.float64(phase),np.float64(velocity_tolerance),self.plan_buffer))
        if not bool(cp.isfinite(self.plan_buffer).all()):raise TrialFailure('Nonfinite contact timestep estimate')
        index=int(cp.argmin(self.plan_buffer[:,0]));row=cp.asnumpy(self.plan_buffer[index])
        if not 0<row[0]<=h:raise TrialFailure('Invalid contact timestep estimate')
        return dict(step_s=float(row[0]),frequency_rad_s=float(row[1]),excitation_m_s=float(row[2]),pair=cp.asnumpy(self.pairs[index]).tolist(),velocity_tolerance_m_s=velocity_tolerance)

    def evaluate(self,velocity,h,gravity=-9.81,*,_jacobian_base=None):
        velocity=cp.ascontiguousarray(velocity,dtype=cp.float64).reshape(-1,self.n,6);batch=len(velocity)
        if not 1<=batch<=384:raise ValueError('Coupled trial batch exceeds reference bound')
        if batch not in self.storage:
            self.storage[batch]=dict(poses=cp.zeros((batch,self.n,7),dtype=cp.float64),residual=cp.zeros((batch,self.n,6),dtype=cp.float64),
                history=cp.zeros((batch,self.m,32),dtype=cp.float64),forces=cp.zeros((batch,self.n,6),dtype=cp.float64),ledger=cp.zeros((batch,12),dtype=cp.float64),faults=cp.zeros(batch,dtype=cp.int32))
            if self.pipeline=='parallel':self.storage[batch].update(prepared=cp.empty((batch,self.n,36),dtype=cp.float64),
                contributions=cp.empty((batch,self.rows,12),dtype=cp.float64),work=cp.empty((batch,self.rows,12),dtype=cp.float64),
                active=cp.empty((batch,self.rows),dtype=cp.uint8),pair_active=cp.empty((batch,self.pair_count),dtype=cp.uint8),
                initial_pair_active=cp.empty(self.pair_count,dtype=cp.uint8),
                contribution_faults=cp.empty((batch,self.rows),dtype=cp.int32),body_faults=cp.empty((batch,self.n,6),dtype=cp.int32))
        out=self.storage[batch]
        n,m,rows,b,h,gy=np.uint32(self.n),np.uint32(self.m),np.uint32(self.rows),np.uint32(batch),np.float64(h),np.float64(gravity)
        def launch(name,count,args):self.phases[name](((count+127)//128,),(128,),args)
        if self.pipeline=='serial-reference':
            self.kernel(((batch+31)//32,),(32,),(self.bodies,n,self.edges,m,velocity,b,h,gy,out['poses'],out['residual'],out['history'],out['forces'],out['ledger'],out['faults']))
        else:
            launch('prepare_trials',batch*self.n,(self.bodies,n,velocity,b,h,out['prepared'],out['poses']))
            base=_jacobian_base or out;localized=_jacobian_base is not None
            if localized and batch!=len(self.jacobian_changed):raise ValueError('Only the current single-DOF Jacobian batch can reuse contributions')
            if self.pair_count:
                # All candidates share the same accepted initial geometry.
                # Within one Jacobian use its freshly calculated base only;
                # ordinary trials recompute this geometry after any edit/step.
                if not localized:launch('prepare_initial_pairs',self.pair_count,(self.bodies,self.pairs,np.uint32(self.pair_count),out['prepared'],out['initial_pair_active']))
                launch('prepare_pairs',batch*self.pair_count,(self.bodies,n,self.pairs,np.uint32(self.pair_count),b,out['prepared'],base['initial_pair_active'],out['pair_active'],np.int32(localized),self.jacobian_changed,base['pair_active']))
            if self.rows:launch('contribution_trials',batch*self.rows,(self.bodies,n,self.edges,m,self.jobs,rows,np.uint32(self.pair_count),b,out['prepared'],out['pair_active'],h,out['contributions'],out['work'],out['history'],out['active'],out['contribution_faults'],np.int32(localized),self.jacobian_changed,base['contributions'],base['work'],base['history'],base['active'],base['contribution_faults']))
            launch('gather_body_trials',batch*self.n*6,(self.bodies,n,rows,b,self.offsets,self.incidence,velocity,out['contributions'],out['active'],h,gy,out['forces'],out['residual'],out['body_faults']))
            launch('gather_active_ledger_trials',batch*12,(rows,m,np.uint32(self.pair_count),b,self.pair_offsets,out['pair_active'],out['work'],out['ledger']))
            self.phases['collect_trial_faults']((batch,),(128,),(n,rows,b,out['contribution_faults'],out['body_faults'],out['poses'],out['ledger'],out['faults']))
        self.evaluations+=batch;return out


class GpuCoupledWorld(CoupledWorld):
    array_api=cp
    to_host=staticmethod(cp.asnumpy)
    evaluator_type=CoupledEvaluator
    flight_partition=FlightPartition
    declaration=staticmethod(declaration)
    source_hash=staticmethod(source_hash)
    device='cuda:0'
    gpu=True
    state_schema='banjo.cupy-coupled-finite-cells.v1'
    backend_name='cupy-implicit-body'
    @staticmethod
    def ensure_source_current():
        if _disk_source_hash()!=LOADED_SOURCE_SHA256:raise RuntimeError('Coupled implementation changed; restart the GPU worker before creating a scene')
    @staticmethod
    def synchronize():cp.cuda.get_current_stream().synchronize()
