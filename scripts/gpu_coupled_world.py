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
extern "C" __global__ void coupled_trials(const double *bodies,unsigned n,const double *edges,unsigned m,
    const double *velocity,unsigned batch,double h,double gy,double *poses,double *residual,
    double *histories,double *forces,double *ledger,int *faults){
    const unsigned i=blockDim.x*blockIdx.x+threadIdx.x;if(i>=batch)return;
    faults[i]=banjo::coupledTrialUnchecked(bodies,n,edges,m,velocity+6*n*i,h,{0,gy,0},
        poses+7*n*i,residual+6*n*i,histories+32*m*i,forces+6*n*i,ledger+12*i);
}
'''
class TrialFailure(RuntimeError):pass

class CoupledEvaluator:
    def __init__(self,bodies,edges):
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
        self.kernel=self.module.get_function('coupled_trials');self.storage={};self.evaluations=0
        self.dynamic=cp.asarray(np.flatnonzero(np.repeat(np.asarray(bodies)[:,1]>0,6)),dtype=cp.int32)
        self.weights=cp.sqrt(cp.repeat(self.bodies[:,1:3],3,axis=1)).reshape(-1)
        self.active_weights=self.weights[self.dynamic]

    def evaluate(self,velocity,h,gravity=-9.81):
        velocity=cp.ascontiguousarray(velocity,dtype=cp.float64).reshape(-1,self.n,6);batch=len(velocity)
        if batch not in self.storage:
            self.storage[batch]=dict(poses=cp.zeros((batch,self.n,7),dtype=cp.float64),residual=cp.zeros((batch,self.n,6),dtype=cp.float64),
                history=cp.zeros((batch,self.m,32),dtype=cp.float64),forces=cp.zeros((batch,self.n,6),dtype=cp.float64),ledger=cp.zeros((batch,12),dtype=cp.float64),faults=cp.zeros(batch,dtype=cp.int32))
        out=self.storage[batch]
        self.kernel(((batch+31)//32,),(32,),(self.bodies,np.uint32(self.n),self.edges,np.uint32(self.m),velocity,np.uint32(batch),np.float64(h),np.float64(gravity),out['poses'],out['residual'],out['history'],out['forces'],out['ledger'],out['faults']))
        self.evaluations+=batch;return out

    def solve(self,h,gravity=-9.81,maximum_iterations=24):
        original=self.bodies[:,14:20].reshape(-1);y=original[self.dynamic]*self.active_weights
        count=len(y);tolerance=1e-10*max(1.,float(cp.linalg.norm(y)))
        def trials(values):
            values=values.reshape(-1,count);velocity=cp.broadcast_to(original,(len(values),len(original))).copy()
            velocity[:,self.dynamic]=values/self.active_weights
            result=self.evaluate(velocity,h,gravity)
            return result,result['residual'].reshape(len(values),-1)[:,self.dynamic],velocity.reshape(-1,self.n,6)
        for iteration in range(maximum_iterations):
            out,residual,velocity=trials(y)
            if int(out['faults'][0]):raise TrialFailure('Coupled trial fault '+str(int(out['faults'][0])))
            norm=float(cp.linalg.norm(residual[0]))
            if norm<=tolerance:
                return {k:v[0].copy() for k,v in out.items()},velocity[0].copy(),iteration,norm
            # Energy-weighted finite cells have sub-micrometre cohesive ranges.
            # A 1e-7 sqrt(J) perturbation crossed compression/damage branches
            # and produced a secant matrix rather than the local Jacobian.
            # Independent derivative/refinement tests bound this FP64 scale.
            epsilon=1e-12*cp.maximum(1.,abs(y))
            perturbed=cp.repeat(y[None],2*count,axis=0)
            ids=cp.arange(count);perturbed[ids,ids]+=epsilon;perturbed[count+ids,ids]-=epsilon
            diff,r,_=trials(perturbed)
            if bool(cp.any(diff['faults'])):raise TrialFailure('Jacobian trial crosses a geometry/numeric boundary')
            jacobian=((r[:count]-r[count:])/(2*epsilon[:,None])).T
            try:
                with cupyx.errstate(linalg='raise'):delta=cp.linalg.solve(jacobian,residual[0])
            except np.linalg.LinAlgError as error:raise TrialFailure('Singular coupled Newton Jacobian') from error
            if not bool(cp.isfinite(delta).all()):raise TrialFailure('Nonfinite coupled Newton direction')
            accepted=False
            for scale in (1.,.5,.25,.125,.0625,.03125,.015625,.0078125):
                candidate=y-scale*delta;probe,r,_=trials(candidate)
                if int(probe['faults'][0])==0 and float(cp.linalg.norm(r[0]))<norm*(1-1e-4*scale):y=candidate;accepted=True;break
            if not accepted:raise TrialFailure('Coupled Newton line search did not reduce the equation residual')
        raise TrialFailure('Coupled Newton iteration budget exceeded')

def declaration(raw):
    defaults=dict(material='glass',ball_material='iron',ball_mass_kg=.01,height_m=.02,dt_s=1/960,experiment='sheet',device='cuda:0')
    if not isinstance(raw,dict) or set(raw)-set(defaults):raise ValueError('Unknown coupled scene field')
    d=defaults|raw
    if d['device']!='cuda:0' or d['experiment'] not in ('sheet','freefall'):raise ValueError('Only explicit CUDA sheet/freefall experiments admitted')
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
        self.eval=CoupledEvaluator(bodies,edges);self.ticks=0;self.time=0.;self.step_s=0.;self.last_ms=0.;self.histories=np.zeros((len(edges),32))
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
        accounts=[];started=time.perf_counter();updates=0;trials=0
        try:
            for host_tick in range(steps):
                queue=[(self.d['dt_s'],0)]
                while queue:
                    trials+=1
                    if trials>128 or time.perf_counter()-started>30:raise TrialFailure('Coupled interval trial/time budget')
                    h,depth=queue.pop();before=cp.asnumpy(self.eval.bodies);energy0,p0,l0=self.mechanics(before)
                    try:out,velocity,iterations,equation=self.eval.solve(h)
                    except TrialFailure:
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
                        if depth>=10:raise TrialFailure('Coupled finite/compression/travel/conservation gate')
                        queue.extend([(h/2,depth+1),(h/2,depth+1)]);continue
                    updates+=1
                    if updates>512 or time.perf_counter()-started>30:raise TrialFailure('Coupled interval work budget')
                    self.eval.bodies[:,23:26]+=h*(self.eval.bodies[:,14:17]+velocity[:,:3])/2
                    self.eval.bodies[:,7:14]=out['poses'];self.eval.bodies[:,14:20]=velocity
                    if self.eval.m:self.eval.edges[:,35:67]=out['history']
                    accounts.append(dict(dt_s=h,energy_residual_j=balance,energy_tolerance_j=tolerance,P_residual_n_s=pres.tolist(),L_residual_n_m_s=lres.tolist(),
                        ground_impulse_n_s=reaction.tolist(),ground_torque_impulse_n_m_s=reaction_torque.tolist(),ledger=ledger.tolist(),iterations=iterations,equation_residual=equation,
                        poses_wxyz=ending[:,7:14].tolist(),velocities=ending[:,14:20].tolist(),material_history=history.tolist()))
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
            self.rejected=dict(error=str(error),accepted_time_s=self.time,interval_rolled_back=restored,accepted_snapshot_preserved=True,failed_interval_substeps=updates,last_trial_accounts=accounts[-4:])
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
            substep_accounts=copy.deepcopy(self.last_accounts),performance=dict(step_s=self.step_s,last_batch_ms=self.last_ms,compute_ratio=self.time/self.step_s if self.step_s else None,
                microsteps=self.microsteps,nonlinear_iterations=self.total_iterations,trial_evaluations=self.eval.evaluations),
            qualification=dict(backend='cupy-implicit-body',gpu=True,device='cuda:0',dtype='float64',source_sha256=self.hash,complete_physics_validated=False,realtime_qualified=False,
                scope='Experimental finite rigid-cell isotropic inertia; declared mixed-mode cohesive/6-mode plastic interfaces and frictionless normal compliance. No calibrated bulk/grain/J2/thermal law or CCD qualification.'))

    def snapshot(self):
        out=copy.deepcopy(self.accepted)
        if self.rejected:out['rejected_candidate']=copy.deepcopy(self.rejected)
        return out
