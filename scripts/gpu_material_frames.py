"""Actual finite-frame coordinates and conjugate material wrenches on CUDA.

No integrator or collision response is supplied here. A bridge can write these
COM wrenches to the GPU rigid solver; its coupled work must still be admitted.
"""
from pathlib import Path
import hashlib
import numpy as np
import cupy as cp
from gpu_material_laws import ResidentLaws
ROOT=Path(__file__).resolve().parents[1]
SOURCES=('scripts/gpu_material_frames.py','src/physics/FiniteFrameKernel.hpp',
         'src/physics/MaterialWrench.cpp','src/physics/RotationStrain.cpp')

def source_hash():
    h=hashlib.sha256()
    for name in SOURCES:
        h.update(name.encode());h.update(b'\0');h.update((ROOT/name).read_bytes())
    return h.hexdigest()

KERNEL=r'''
__device__ banjo::FrameVector vector(const double *p){return {p[0],p[1],p[2]};}
__device__ banjo::FrameQuaternion quaternion(const double *p){
    const double n=sqrt(p[0]*p[0]+p[1]*p[1]+p[2]*p[2]+p[3]*p[3]);
    return {p[0]/n,p[1]/n,p[2]/n,p[3]/n};
}
__device__ bool valid(const double *p){
    for(int j=0;j<14;++j)if(!isfinite(p[j]))return false;
    for(int offset=3;offset<=10;offset+=7){
        const double n=sqrt(p[offset]*p[offset]+p[offset+1]*p[offset+1]+p[offset+2]*p[offset+2]+p[offset+3]*p[offset+3]);
        if(fabs(n-1)>1e-4)return false;
    }
    return true;
}
__device__ banjo::FiniteFrameCoordinates coordinates(const double *a,const double *b){
    return banjo::finiteFrameCoordinatesUnchecked(vector(a),vector(b),quaternion(a+3),quaternion(b+3),vector(a+7),vector(b+7),quaternion(a+10),quaternion(b+10));
}
extern "C" __global__ void frame_coordinates(const double *frames,double *q,int *faults,unsigned n){
    const unsigned i=blockDim.x*blockIdx.x+threadIdx.x;if(i>=n)return;
    const double *a=frames+28*i,*b=a+14;
    int fault=(!valid(a)||!valid(b))?1:0;
    if(fault){faults[i]=fault;return;}
    const auto c=coordinates(a,b);
    if(c.rotation.branch_angle>=3.141592653589793-1e-7)fault=2;
    for(unsigned j=0;j<6;++j){q[6*i+j]=c.q[j];if(!isfinite(c.q[j]))fault=3;}
    faults[i]=fault;
}
extern "C" __global__ void frame_wrenches(const double *frames,const double *loads,double *out,unsigned n){
    const unsigned i=blockDim.x*blockIdx.x+threadIdx.x;if(i>=n)return;
    const double *a=frames+28*i,*b=a+14;const auto c=coordinates(a,b);
    const auto w=banjo::finiteFrameWrenchesUnchecked(c,vector(a),vector(b),loads+6*i);
    const banjo::FrameVector v[]{w.force_a,w.torque_a,w.force_b,w.torque_b};
    for(unsigned j=0;j<4;++j){out[12*i+3*j]=v[j].x;out[12*i+3*j+1]=v[j].y;out[12*i+3*j+2]=v[j].z;}
}
extern "C" __global__ void material_loads(const int *kinds,const double *coefficients,const double *state,double *loads,unsigned n){
    const unsigned i=blockDim.x*blockIdx.x+threadIdx.x;if(i>=n)return;
    for(unsigned j=0;j<6;++j)loads[6*i+j]=kinds[i]?coefficients[12*i+j]*(state[32*i+22+j]-state[32*i+j]):(j==0?state[32*i+2]:0);
}
'''


class ResidentFrames:
    """Immutable topology; frame rows are COM, wxyz, local anchor, local wxyz."""
    def __init__(self,count):
        if type(count) is not int or not 1<=count<=65536:raise ValueError('Invalid frame count')
        if (cp.__version__,np.__version__)!=('13.5.1','2.5.3'):raise RuntimeError('Unverified frame runtime')
        cp.cuda.Device(0).use();self.count=count
        code=(ROOT/SOURCES[1]).read_text(encoding='utf8').replace('#pragma once','')+'\n'+KERNEL
        self.module=cp.RawModule(code=code,options=('--std=c++17','--fmad=false'))
        self.coordinate_kernel=self.module.get_function('frame_coordinates')
        self.wrench_kernel=self.module.get_function('frame_wrenches')
        self.load_kernel=self.module.get_function('material_loads')
        self.frames=cp.empty((count,2,14),dtype=cp.float64);self.q=cp.empty((count,6),dtype=cp.float64)
        self.faults=cp.zeros(count,dtype=cp.int32);self.loads=cp.empty_like(self.q);self.wrenches=cp.empty((count,4,3),dtype=cp.float64)
        self.grid=((count+127)//128,);self.block=(128,)
        self.ready=False

    def coordinates(self,frames):
        cp.cuda.Device(0).use()
        self.ready=False
        f=cp.asarray(frames,dtype=cp.float64)
        if f.device.id!=0 or f.shape!=self.frames.shape:raise ValueError('Invalid frame shape/device')
        cp.copyto(self.frames,f)
        self.coordinate_kernel(self.grid,self.block,(self.frames,self.q,self.faults,np.uint32(self.count)))
        if bool(cp.any(self.faults)):raise ValueError('Nonfinite/nonunit frame or nonunique pi branch; history retained')
        self.ready=True
        return self.q

    def forces(self,loads):
        if not self.ready:raise ValueError('No validated material frames')
        values=cp.asarray(loads,dtype=cp.float64)
        if values.device.id!=0 or values.shape!=self.loads.shape or not bool(cp.isfinite(values).all()):raise ValueError('Invalid finite-frame loads')
        cp.copyto(self.loads,values)
        self.wrench_kernel(self.grid,self.block,(self.frames,self.loads,self.wrenches,np.uint32(self.count)))
        if not bool(cp.isfinite(self.wrenches).all()):raise RuntimeError('Nonfinite material wrench')
        return self.wrenches

    def material_forces(self,laws:ResidentLaws):
        if not self.ready:raise ValueError('No validated material frames')
        if len(laws.profiles)!=self.count:raise ValueError('Interface/frame topology mismatch')
        self.load_kernel(self.grid,self.block,(laws.kinds,laws.coefficients,laws.state,self.loads,np.uint32(self.count)))
        return self.forces(self.loads)


def write_physx_wrenches(world,wrenches):
    """Only GPU body inputs, never pose/velocity assignment or USD animation.

    The caller provides accumulated COM forces/torques, N and N m; the world
    owns the collision response. CUDA -> CUDA float32 is explicit. All mapped
    rows are filled and synchronized before commit consumes each group.
    """
    from ovphysx.types import SimObjectType,ObjectScope
    import warp as wp
    if world.sdk is None or hasattr(world,'rejected_candidate'):raise ValueError('Closed/refused GPU world; reset required')
    if not isinstance(wrenches,cp.ndarray) or wrenches.device.id!=world.device.ordinal:raise ValueError('Wrench source must be resident on the world GPU')
    values=cp.asarray(wrenches,dtype=cp.float64)
    if values.shape!=(len(world.paths),6) or not bool(cp.isfinite(values).all()):raise ValueError('Invalid body wrench')
    if cp.cuda.Device().id!=world.device.ordinal:raise RuntimeError('Wrench GPU mismatch')
    narrowed=values.astype(cp.float32)
    if not bool(cp.isfinite(narrowed).all()):raise ValueError('Wrench exceeds actual PhysX FP32 range')
    seen=set()
    with world.sdk.write(SimObjectType.RIGID_BODY,'wrench',scope=ObjectScope.ALL) as write:
        mapped=[]
        for group in write.groups:
            names=world.pd.get_path_strings(group.prim_list)
            if len(group.tensors)!=1 or group.prim_offset!=0 or group.prim_count!=len(names):raise RuntimeError('Unsupported wrench layout')
            tensor=group.tensors[0]
            if not tensor.device.is_cuda or tensor.device.ordinal!=world.device.ordinal or tensor.shape!=(len(names),9) or tensor.dtype!=wp.float32:raise RuntimeError('Wrench write is not actual CUDA')
            if any(p not in world.paths or p in seen for p in names):raise RuntimeError('Unknown/duplicate wrench body')
            seen.update(names);mapped.append((group,names))
        if seen!=set(world.paths):raise RuntimeError('Incomplete body wrench write')
        for group,names in mapped:
            tensor=group.tensors[0]
            rows=cp.asarray([world.paths.index(p) for p in names],dtype=cp.int32)
            view=cp.from_dlpack(tensor)
            # COM torques already include lever arms; applying at COM avoids
            # adding the same r x F a second time inside the SDK.
            view[:,:6]=narrowed[rows]
            view[:,6:]=cp.from_dlpack(world.bound_pose)[rows,:3]
            cp.cuda.get_current_stream().synchronize()
            write.commit(group)
