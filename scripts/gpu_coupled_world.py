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
ROOT=Path(__file__).resolve().parents[1]
HEADERS=('src/physics/FiniteFrameKernel.hpp','src/physics/CohesiveInterfaceKernel.hpp',
 'src/material/ConnectorModeKernel.hpp','src/physics/MaterialHistoryKernel.hpp',
 'src/physics/NormalComplianceKernel.hpp','src/physics/CoupledGpuKernel.hpp')
SOURCES=('scripts/gpu_coupled_world.py',*HEADERS,'client/voxel-lab/material-laws.json')
def source_hash():
    h=hashlib.sha256()
    for name in SOURCES:h.update(name.encode());h.update(b'\0');h.update((ROOT/name).read_bytes())
    return h.hexdigest()

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
extern "C" __global__ void prepare_pairs(const double *bodies,unsigned n,const unsigned *pairs,unsigned pair_count,unsigned batch,
    const banjo::DGTrialBody *prepared,unsigned char *active,int localized,const int *changed_body,const unsigned char *base_active){
    const unsigned k=blockDim.x*blockIdx.x+threadIdx.x;if(k>=pair_count*batch)return;
    const unsigned candidate=k/pair_count,pair=k%pair_count,a=pairs[2*pair],b=pairs[2*pair+1];
    if(localized&&a!=static_cast<unsigned>(changed_body[candidate])&&b!=static_cast<unsigned>(changed_body[candidate])){active[k]=base_active[pair];return;}
    const auto p=prepared+n*candidate;const auto before=banjo::dgContact(bodies+30*a,bodies+30*b,p[a].initial,p[b].initial);
    const auto after=banjo::dgContact(bodies+30*a,bodies+30*b,p[a].ending,p[b].ending);
    active[k]=before.gap>0&&after.gap>0?0:1;
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
class TrialFailure(RuntimeError):
    def __init__(self,message,details=None):
        super().__init__(message);self.details=details or {}

class CoupledEvaluator:
    def __init__(self,bodies,edges,pipeline='parallel',newton_strategy='ranked'):
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
        code='\n'.join((ROOT/name).read_text(encoding='utf8').replace('#pragma once','') for name in HEADERS)+'\n'+KERNEL
        self.module=cp.RawModule(code=code,options=('--std=c++17','--fmad=false'))
        if pipeline not in ('parallel','serial-reference'):raise ValueError('Unknown coupled trial pipeline')
        if newton_strategy not in ('ranked','single-reference'):raise ValueError('Unknown Newton starting strategy')
        self.newton_strategy=newton_strategy;self.last_solve=None
        self.pipeline=pipeline;self.kernel=self.module.get_function('coupled_trials');self.storage={};self.evaluations=0
        self.phases={name:self.module.get_function(name) for name in ('prepare_trials','prepare_pairs','contribution_trials','gather_body_trials','gather_ledger_trials','collect_trial_faults')}
        host_b=np.asarray(bodies);jobs=[];pairs=[]
        for a in range(self.n):
            for b in range(a+1,self.n):
                if host_b[a,1]==host_b[b,1]==0:continue
                pair=len(pairs);pairs.append((a,b))
                sa=host_b[a,0]==1 and host_b[b,0]!=2;sb=host_b[b,0]==1 and host_b[a,0]!=2
                for site in range(48 if sa and sb else 24 if sa or sb else 1):jobs.append((a,b,site,pair))
        self.jobs=cp.asarray(np.array(jobs,dtype=np.uint32).reshape(-1,4));self.rows=self.m+len(jobs)
        self.pairs=cp.asarray(np.array(pairs,dtype=np.uint32).reshape(-1,2));self.pair_count=len(pairs)
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
            if self.pipeline=='parallel':self.storage[batch].update(prepared=cp.empty((batch,self.n,27),dtype=cp.float64),
                contributions=cp.empty((batch,self.rows,12),dtype=cp.float64),work=cp.empty((batch,self.rows,12),dtype=cp.float64),
                active=cp.empty((batch,self.rows),dtype=cp.uint8),pair_active=cp.empty((batch,self.pair_count),dtype=cp.uint8),
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
            if self.pair_count:launch('prepare_pairs',batch*self.pair_count,(self.bodies,n,self.pairs,np.uint32(self.pair_count),b,out['prepared'],out['pair_active'],np.int32(localized),self.jacobian_changed,base['pair_active']))
            if self.rows:launch('contribution_trials',batch*self.rows,(self.bodies,n,self.edges,m,self.jobs,rows,np.uint32(self.pair_count),b,out['prepared'],out['pair_active'],h,out['contributions'],out['work'],out['history'],out['active'],out['contribution_faults'],np.int32(localized),self.jacobian_changed,base['contributions'],base['work'],base['history'],base['active'],base['contribution_faults']))
            launch('gather_body_trials',batch*self.n*6,(self.bodies,n,rows,b,self.offsets,self.incidence,velocity,out['contributions'],out['active'],h,gy,out['forces'],out['residual'],out['body_faults']))
            launch('gather_ledger_trials',batch*12,(rows,b,out['work'],out['ledger']))
            self.phases['collect_trial_faults']((batch,),(128,),(n,rows,b,out['contribution_faults'],out['body_faults'],out['poses'],out['ledger'],out['faults']))
        self.evaluations+=batch;return out

    def solve(self,h,gravity=-9.81,maximum_iterations=24):
        original=self.bodies[:,14:20].reshape(-1);y=original[self.dynamic]*self.active_weights
        count=len(y);tolerance=1e-10*max(1.,float(cp.linalg.norm(y)))
        trace=[];last_trial=None;jacobian=None;jacobian_point=None;self.last_solve=None
        fractions=(1.,.1,.01) if self.newton_strategy=='ranked' else (1.,)
        guesses=None;order=[0];start_index=0;start_scores=None
        def refuse(message):
            # Failure-only observations never replace an accepted physical state.
            # Retain the actual last evaluated candidate, rather than inferring
            # the cause from the timestep at which subdivision eventually stops.
            details=dict(dt_s=h,gravity_m_s2=gravity,equation_tolerance=tolerance,iterations=trace,
                initial_bodies=cp.asnumpy(self.bodies).tolist(),initial_edges=cp.asnumpy(self.edges).tolist(),
                iterate_weighted_velocity=cp.asnumpy(y).tolist(),finite_difference_weighted_scale=1e-12,
                finite_difference_displacement_floor_kg_half_m=1e-16,
                newton_strategy=self.newton_strategy,starting_fractions=list(fractions),starting_scores=start_scores,
                attempted_fractions=[fractions[i] for i in order[:start_index+1]])
            if last_trial is not None:
                result,values,velocity=last_trial
                details['last_evaluated']=dict(weighted_velocity=cp.asnumpy(values).tolist(),
                    velocity=cp.asnumpy(velocity).tolist(),poses_wxyz=cp.asnumpy(result['poses']).tolist(),
                    residual=cp.asnumpy(result['residual']).tolist(),forces=cp.asnumpy(result['forces']).tolist(),
                    ledger=cp.asnumpy(result['ledger']).tolist(),faults=cp.asnumpy(result['faults']).tolist(),
                    material_history=cp.asnumpy(result['history']).tolist())
            if jacobian is not None:
                matrix=cp.asnumpy(jacobian)
                if np.isfinite(matrix).all():
                    singular=np.linalg.svd(matrix,compute_uv=False)
                    details['jacobian_singular_values']=singular.tolist();details['jacobian']=matrix.tolist()
                    details['jacobian_weighted_velocity']=cp.asnumpy(jacobian_point).tolist()
            raise TrialFailure(message,details)
        def trials(values,base=None):
            nonlocal last_trial
            values=values.reshape(-1,count);velocity=cp.broadcast_to(original,(len(values),len(original))).copy()
            velocity[:,self.dynamic]=values/self.active_weights
            result=self.evaluate(velocity,h,gravity,_jacobian_base=base if self.pipeline=='parallel' else None)
            last_trial=result,values,velocity.reshape(-1,self.n,6)
            return result,result['residual'].reshape(len(values),-1)[:,self.dynamic],velocity.reshape(-1,self.n,6)
        if self.newton_strategy=='ranked':
            # Numerical starting guesses only: contract the candidate midpoint
            # motion toward zero. No accepted velocity or history is assigned.
            # A stiff implicit root can be close to that limit even when the
            # original velocity guess enters a different softening branch.
            guesses=cp.asarray([2*f-1 for f in fractions])[:,None]*y[None]
            probe,r,_=trials(guesses)
            scores=cp.where(probe['faults']==0,cp.linalg.norm(r,axis=1),cp.inf)
            host_scores=cp.asnumpy(scores);start_scores=[float(x) if np.isfinite(x) else None for x in host_scores]
            order=np.argsort(host_scores,kind='stable').tolist()
            if start_scores[order[0]] is None:refuse('All Newton starting trials refused')
            y=guesses[order[0]].copy()
        for iteration in range(maximum_iterations):
            out,residual,velocity=trials(y)
            if int(out['faults'][0]):refuse('Coupled trial fault '+str(int(out['faults'][0])))
            norm=float(cp.linalg.norm(residual[0]))
            row=dict(iteration=iteration,starting_fraction=fractions[order[start_index]],equation_residual=norm,line_search=[]);trace.append(row)
            if norm<=tolerance:
                self.last_solve=dict(strategy=self.newton_strategy,starting_scores=start_scores,
                    attempted_fractions=[fractions[i] for i in order[:start_index+1]],converged_fraction=fractions[order[start_index]],iteration_evaluations=len(trace))
                return {k:out[k][0].copy() for k in ('poses','residual','history','forces','ledger','faults')},velocity[0].copy(),iteration,norm
            # Energy-weighted finite cells have sub-micrometre cohesive ranges.
            # A 1e-7 sqrt(J) perturbation crossed compression/damage branches
            # and produced a secant matrix rather than the local Jacobian.
            # Independent derivative/refinement tests bound this FP64 scale.
            # Midpoint translation/turn changes by h*delta/2. At microsecond
            # steps the velocity-only scale falls below contact-position ULPs.
            # Keep a declared weighted displacement floor, without changing
            # the force law, nonlinear tolerance or accepted velocities.
            epsilon=cp.maximum(1e-12*cp.maximum(1.,abs(y)),2e-16/h)
            perturbed=cp.repeat(y[None],2*count,axis=0)
            ids=cp.arange(count);perturbed[ids,ids]+=epsilon;perturbed[count+ids,ids]-=epsilon
            diff,r,_=trials(perturbed,base=out)
            if bool(cp.any(diff['faults'])):refuse('Jacobian trial crosses a geometry/numeric boundary')
            jacobian=((r[:count]-r[count:])/(2*epsilon[:,None])).T
            jacobian_point=y
            try:
                with cupyx.errstate(linalg='raise'):delta=cp.linalg.solve(jacobian,residual[0])
            except np.linalg.LinAlgError:refuse('Singular coupled Newton Jacobian')
            if not bool(cp.isfinite(delta).all()):refuse('Nonfinite coupled Newton direction')
            accepted=False
            for scale in (1.,.5,.25,.125,.0625,.03125,.015625,.0078125):
                candidate=y-scale*delta;probe,r,_=trials(candidate)
                fault=int(probe['faults'][0]);probe_norm=float(cp.linalg.norm(r[0])) if fault==0 else None
                row['line_search'].append(dict(scale=scale,fault=fault,equation_residual=probe_norm))
                if fault==0 and probe_norm<norm*(1-1e-4*scale):y=candidate;accepted=True;break
            if not accepted:
                # All starts share the SAME total 24-iteration limit. Restart
                # only the private nonlinear iterate; the physical input,
                # constitutive history, equation and admission gates are fixed.
                if guesses is not None and iteration+1<maximum_iterations and start_index+1<len(order) and start_scores[order[start_index+1]] is not None:
                    start_index+=1;y=guesses[order[start_index]].copy();continue
                refuse('Coupled Newton line search did not reduce the equation residual')
        refuse('Coupled Newton iteration budget exceeded')

def declaration(raw):
    defaults=dict(material='glass',ball_material='iron',ball_mass_kg=.01,height_m=.02,dt_s=1/960,experiment='sheet',device='cuda:0',pipeline='parallel',newton_strategy='ranked',contact_resolution='reference')
    if not isinstance(raw,dict) or set(raw)-set(defaults):raise ValueError('Unknown coupled scene field')
    d=defaults|raw
    if d['device']!='cuda:0' or d['experiment'] not in ('sheet','freefall'):raise ValueError('Only explicit CUDA sheet/freefall experiments admitted')
    if d['pipeline'] not in ('parallel','serial-reference'):raise ValueError('Unknown coupled trial pipeline')
    if d['newton_strategy'] not in ('ranked','single-reference'):raise ValueError('Unknown Newton starting strategy')
    if d['contact_resolution'] not in ('reference','phase-0.25','phase-0.125','phase-0.0625'):raise ValueError('Unknown contact timestep policy')
    for name in ('material','ball_material'):
        if d[name] not in ('glass','oak','iron','ice'):raise ValueError('Unknown declared material')
    for name,lo,hi in (('ball_mass_kg',.001,1.),('height_m',.001,10.)):
        if type(d[name]) not in (float,int) or not math.isfinite(d[name]) or not lo<=d[name]<=hi:raise ValueError('Invalid '+name)
    if type(d['dt_s']) not in (float,int) or d['dt_s'] not in (1/240,1/480,1/960,1/1920):raise ValueError('Unadmitted coupled host timestep')
    return d

class GpuCoupledWorld:
    def __init__(self,raw):
        self.d=declaration(raw);profiles=json.loads((ROOT/'client/voxel-lab/material-laws.json').read_text(encoding='utf8'))['profiles'];profiles={p['material']:p for p in profiles}
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
        self.eval=CoupledEvaluator(bodies,edges,pipeline=self.d['pipeline'],newton_strategy=self.d['newton_strategy']);self.ticks=0;self.time=0.;self.step_s=0.;self.last_ms=0.;self.histories=np.zeros((len(edges),32))
        self.P_ground=np.zeros(3);self.L_ground=np.zeros(3);self.max_residual=0.;self.fracture=self.plastic=self.return_excess=0.;self.total_iterations=0;self.microsteps=0
        baseline=self.eval.evaluate(self.eval.bodies[:,14:20],1e-12,gravity=0)
        if int(baseline['faults'][0]):raise RuntimeError('Invalid initial coupled energy state')
        ledger=cp.asnumpy(baseline['ledger'])[0];self.stored_j=float(ledger[0]);self.contact_j=float(ledger[4])
        self.initial_energy=self.mechanics(np.array(bodies))[0]+self.stored_j+self.contact_j
        self.last_accounts=[];self.rejected=None;self.hash=source_hash();self.accepted=self._snapshot(np.array(bodies))

    @staticmethod
    def mechanics(bodies):
        mass=bodies[:,1];energy=.5*np.sum(mass[:,None]*bodies[:,14:17]**2)+.5*np.sum(bodies[:,2,None]*bodies[:,17:20]**2)+9.81*np.sum(mass*bodies[:,8])
        p=np.sum(mass[:,None]*bodies[:,14:17],axis=0);l=np.sum(np.cross(bodies[:,7:10],mass[:,None]*bodies[:,14:17])+bodies[:,2,None]*bodies[:,17:20],axis=0)
        return float(energy),p,l

    def advance(self,steps):
        if self.rejected:raise ValueError('Refused coupled world is stopped; reset required')
        if type(steps) is not int or not 1<=steps<=32 or self.ticks+steps>round(2/self.d['dt_s']):raise ValueError('Invalid coupled advance')
        saved_b=self.eval.bodies.copy();saved_e=self.eval.edges.copy();accepted_b=cp.asnumpy(saved_b);accepted_e=cp.asnumpy(saved_e)
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
                    before=cp.asnumpy(self.eval.bodies);energy0,p0,l0=self.mechanics(before)
                    try:out,velocity,iterations,equation=self.eval.solve(h)
                    except TrialFailure as error:
                        last_solver_failure=error.details
                        refusals.append(dict(trial=trials,dt_s=h,depth=depth,error=str(error),
                            private_elapsed_s=sum(a['dt_s'] for a in accounts),
                            equation_residual=(error.details.get('iterations') or [{}])[-1].get('equation_residual')))
                        if depth>=10:raise
                        queue.extend([(h/2,depth+1),(h/2,depth+1)]);continue
                    ending=before.copy();ending[:,7:14]=cp.asnumpy(out['poses']);ending[:,14:20]=cp.asnumpy(velocity)
                    ending[:,23:26]=before[:,23:26]+h*(before[:,14:17]+ending[:,14:17])/2
                    ledger=cp.asnumpy(out['ledger']);forces=cp.asnumpy(out['forces']);history=cp.asnumpy(out['history']);energy1,p1,l1=self.mechanics(ending)
                    fixed=before[:,1]==0;reaction=-h*forces[fixed,:3].sum(axis=0)
                    midpoint=(before[:,7:10]+ending[:,7:10])/2
                    reaction_torque=-h*(np.cross(midpoint[fixed],forces[fixed,:3])+forces[fixed,3:]).sum(axis=0)
                    gravity_impulse=np.array([0,-9.81*before[:,1].sum()*h,0]);gravity_torque=h*np.cross(midpoint,before[:,1,None]*[0,-9.81,0]).sum(axis=0)
                    balance=energy1-energy0+ledger[1]-ledger[0]+ledger[2]+ledger[3]+ledger[5]-ledger[4]
                    pres=p1-p0-reaction-gravity_impulse;lres=l1-l0-reaction_torque-gravity_torque
                    tolerance=1e-10+1e-8*max(abs(energy0+ledger[0]+ledger[4]),1e-3)
                    scale=float(np.min(2*before[before[:,0]!=0,4:7]));travel=float(np.max(np.linalg.norm(ending[:,7:10]-before[:,7:10],axis=1)))
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
                    accounts.append(dict(dt_s=h,energy_residual_j=balance,energy_tolerance_j=tolerance,P_residual_n_s=pres.tolist(),L_residual_n_m_s=lres.tolist(),
                        ground_impulse_n_s=reaction.tolist(),ground_torque_impulse_n_m_s=reaction_torque.tolist(),ledger=ledger.tolist(),iterations=iterations,equation_residual=equation,
                        poses_wxyz=ending[:,7:14].tolist(),velocities=ending[:,14:20].tolist(),material_history=history.tolist(),newton_start=copy.deepcopy(self.eval.last_solve),contact_schedule=schedule))
            self.histories=history;self.ticks+=steps;self.time+=steps*self.d['dt_s'];self.microsteps+=updates;self.total_iterations+=sum(a['iterations'] for a in accounts)
            self.fracture+=sum(a['ledger'][2] for a in accounts) if self.material_model!='connector-plastic' else 0
            self.plastic+=sum(a['ledger'][2] for a in accounts) if self.material_model=='connector-plastic' else 0
            self.return_excess+=sum(a['ledger'][3] for a in accounts)
            self.P_ground+=sum((np.array(a['ground_impulse_n_s']) for a in accounts),start=np.zeros(3));self.L_ground+=sum((np.array(a['ground_torque_impulse_n_m_s']) for a in accounts),start=np.zeros(3))
            self.max_residual=max(self.max_residual,max(abs(a['energy_residual_j']) for a in accounts));self.last_accounts=accounts
            self.stored_j=float(ledger[1]);self.contact_j=float(ledger[5])
            self.last_ms=(time.perf_counter()-started)*1000;self.step_s+=self.last_ms/1000;self.accepted=self._snapshot(ending);return self.snapshot()
        except Exception as error:
            restored=False
            try:cp.copyto(self.eval.bodies,saved_b);cp.copyto(self.eval.edges,saved_e);cp.cuda.get_current_stream().synchronize();restored=True
            except Exception:pass # A poisoned CUDA context cannot confirm GPU rollback.
            self.rejected=dict(error=str(error),accepted_time_s=self.time,interval_rolled_back=restored,accepted_snapshot_preserved=True,
                failed_interval_substeps=updates,trial_attempts=trials,subdivision_refusals=refusals,
                last_solver_failure=last_solver_failure,last_trial_accounts=accounts[-4:],contact_timestep_policy=self.d['contact_resolution'],
                last_contact_schedule=schedule,failed_interval_physical_s=sum(a['dt_s'] for a in accounts))
            raise RuntimeError(str(error)) from error

    def _snapshot(self,bodies):
        energy,p,l=self.mechanics(bodies);cells=[]
        for row,b in zip(self.meta,bodies):cells.append(row|dict(position_m=b[7:10].tolist(),quaternion_wxyz=b[10:14].tolist(),velocity_m_s=b[14:17].tolist(),angular_velocity_rad_s=b[17:20].tolist()))
        kinds=cp.asnumpy(self.eval.edges[:,2]).astype(int) if self.eval.m else []
        separated=int(sum(s[6]>0 for k,s in zip(kinds,self.histories) if k!=1));yielded=int(sum(s[14]>0 for k,s in zip(kinds,self.histories) if k==1))
        return dict(schema='banjo.cupy-coupled-finite-cells.v1',declaration=copy.deepcopy(self.d),time_s=self.time,dt_s=self.d['dt_s'],ticks=self.ticks,cells=cells,history_arrays=self.histories.tolist(),
            diagnostics=dict(dynamic_mass_kg=float(bodies[:,1].sum()),mechanical_j=energy,material_stored_j=self.stored_j,contact_stored_j=self.contact_j,
                global_energy_residual_j=energy+self.stored_j+self.contact_j+self.fracture+self.plastic+self.return_excess-self.initial_energy,
                momentum_n_s=p.tolist(),angular_momentum_n_m_s=l.tolist(),
                fracture_work_j=self.fracture,plastic_work_j=self.plastic,numerical_return_excess_j=self.return_excess,separated_sites=separated,yielded_faces=yielded,interfaces=self.eval.m,
                maximum_energy_residual_j=self.max_residual,ground_impulse_n_s=self.P_ground.tolist(),ground_torque_impulse_n_m_s=self.L_ground.tolist()),
            substep_accounts=copy.deepcopy(self.last_accounts),performance=dict(pipeline=self.eval.pipeline,newton_strategy=self.eval.newton_strategy,contact_resolution=self.d['contact_resolution'],step_s=self.step_s,last_batch_ms=self.last_ms,compute_ratio=self.time/self.step_s if self.step_s else None,
                microsteps=self.microsteps,nonlinear_iterations=self.total_iterations,trial_evaluations=self.eval.evaluations),
            qualification=dict(backend='cupy-implicit-body',gpu=True,device='cuda:0',dtype='float64',source_sha256=self.hash,complete_physics_validated=False,realtime_qualified=False,
                scope='Experimental finite rigid-cell isotropic inertia; declared mixed-mode cohesive/6-mode plastic interfaces and frictionless normal compliance. No calibrated bulk/grain/J2/thermal law or CCD qualification.'))

    def snapshot(self):
        out=copy.deepcopy(self.accepted)
        if self.rejected:out['rejected_candidate']=copy.deepcopy(self.rejected)
        return out
