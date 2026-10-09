"""Bounded reusable FP64 cuSOLVER operation; status remains on the GPU.

Same pivoted LU/getrs routines as pinned CuPy solve. Private safe substitutions
only keep a failed operation executable: nonzero status MUST reject its result.
No host read or CPU numerical fallback in enqueue(). Buffers are overwritten
on the next call, and an instance belongs to one device/ordered CUDA stream.
"""
import ctypes
import struct
import sys
from pathlib import Path
import cupy as cp
import numpy as np
from cupy_backends.cuda.libs import cublas,cusolver

class NativeCuSolver:
    """Pinned Windows x64 ABI for the ALREADY loaded NVIDIA library.

    CuPy 13.5's wrappers explicitly forbid stream capture. Native cuSOLVER
    calls are a separate tested path; no wrapper flags are patched or ignored.
    """
    def __init__(self):
        if sys.platform!='win32' or struct.calcsize('P')!=8:raise RuntimeError('Native cuSOLVER bridge is verified only on Windows x64')
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.GetModuleHandleW.argtypes=[ctypes.c_wchar_p];kernel.GetModuleHandleW.restype=ctypes.c_void_p
        handle=kernel.GetModuleHandleW('cusolver64_11.dll')
        if not handle:raise RuntimeError('Pinned cuSOLVER library is not loaded')
        kernel.GetModuleFileNameW.argtypes=[ctypes.c_void_p,ctypes.c_wchar_p,ctypes.c_uint];kernel.GetModuleFileNameW.restype=ctypes.c_uint
        path=ctypes.create_unicode_buffer(32768);length=kernel.GetModuleFileNameW(handle,path,len(path))
        if not length or length>=len(path):raise RuntimeError('Cannot identify loaded cuSOLVER library')
        self.path=Path(path.value);self.library=ctypes.WinDLL(str(self.path))
        prop=self.library.cusolverGetProperty;prop.argtypes=[ctypes.c_int,ctypes.POINTER(ctypes.c_int)];prop.restype=ctypes.c_int
        version=[]
        for i in range(3):
            value=ctypes.c_int();self.check(prop(i,ctypes.byref(value)));version.append(value.value)
        self.version=tuple(version)
        if self.version!=(11,7,5):raise RuntimeError('Unverified native cuSOLVER version '+str(self.version))
        p=ctypes.c_void_p;i=ctypes.c_int
        self.set_stream=self.library.cusolverDnSetStream;self.set_stream.argtypes=[p,p];self.set_stream.restype=i
        self.getrf=self.library.cusolverDnDgetrf;self.getrf.argtypes=[p,i,i,p,i,p,p,p];self.getrf.restype=i
        self.getrs=self.library.cusolverDnDgetrs;self.getrs.argtypes=[p,i,i,i,p,i,p,p,i,p];self.getrs.restype=i

    @staticmethod
    def check(status):
        if status:raise RuntimeError('Native cuSOLVER API refused operation: '+str(status))

KERNEL=r'''
extern "C" __global__ void guard_linear_input(double *a,double *b,unsigned n,int *status){
    __shared__ unsigned bad;if(threadIdx.x==0){bad=0;status[0]=status[1]=status[2]=0;}__syncthreads();
    for(unsigned i=threadIdx.x;i<n*n;i+=blockDim.x)if(!isfinite(a[i]))atomicOr(&bad,1u);
    for(unsigned i=threadIdx.x;i<n;i+=blockDim.x)if(!isfinite(b[i]))atomicOr(&bad,1u);
    __syncthreads();if(!bad)return;
    if(threadIdx.x==0)status[0]=1;
    for(unsigned i=threadIdx.x;i<n*n;i+=blockDim.x)a[i]=(i%n==i/n)?1:0;
    for(unsigned i=threadIdx.x;i<n;i+=blockDim.x)b[i]=0;
}
extern "C" __global__ void guard_linear_factor(double *a,double *b,int *pivot,unsigned n,const int *info,int *status){
    __shared__ unsigned bad;if(threadIdx.x==0)bad=0;__syncthreads();
    for(unsigned i=threadIdx.x;i<n*n;i+=blockDim.x)if(!isfinite(a[i]))atomicOr(&bad,1u);
    __syncthreads();
    if(threadIdx.x==0){status[1]=info[0];if(!status[0])status[0]=info[0]?2:bad?3:0;}__syncthreads();
    if(!status[0])return;
    // This is not a valid replacement direction. The retained fault rejects
    // it. Avoid running a triangular solve on a singular/nonfinite factor.
    for(unsigned i=threadIdx.x;i<n*n;i+=blockDim.x)a[i]=(i%n==i/n)?1:0;
    for(unsigned i=threadIdx.x;i<n;i+=blockDim.x){b[i]=0;pivot[i]=i+1;}
}
extern "C" __global__ void finish_linear_status(const double *b,unsigned n,const int *info,int *status){
    __shared__ unsigned bad;if(threadIdx.x==0)bad=0;__syncthreads();
    for(unsigned i=threadIdx.x;i<n;i+=blockDim.x)if(!isfinite(b[i]))atomicOr(&bad,1u);
    __syncthreads();if(threadIdx.x==0){status[2]=info[0];if(!status[0])status[0]=info[0]?4:bad?5:0;}
}
'''

class ResidentLinearSolve:
    def __init__(self,size):
        if (cp.__version__,np.__version__)!=('13.5.1','2.5.3'):raise RuntimeError('Unverified resident linear runtime')
        if type(size) is not int or not 1<=size<=192:raise ValueError('Linear dimension outside declared capacity')
        if cp.cuda.runtime.getDevice()!=0:raise ValueError('Only the explicit CUDA device 0 is admitted')
        self.size=size;self.device=0;self.stream_ptr=cp.cuda.get_current_stream().ptr
        self.factor=cp.empty((size,size),dtype=cp.float64,order='F');self.solution=cp.empty(size,dtype=cp.float64)
        self.pivot=cp.empty(size,dtype=cp.int32);self.factor_info=cp.empty(1,dtype=cp.int32);self.solve_info=cp.empty(1,dtype=cp.int32)
        self.status=cp.empty(3,dtype=cp.int32)
        handle=cp.cuda.device.get_cusolver_handle()
        length=cusolver.dgetrf_bufferSize(handle,size,size,self.factor.data.ptr,size)
        self.workspace=cp.empty(length,dtype=cp.float64)
        self.native=NativeCuSolver()
        self.module=cp.RawModule(code=KERNEL,options=('--std=c++17','--fmad=false'))
        self.guard_input=self.module.get_function('guard_linear_input');self.guard_factor=self.module.get_function('guard_linear_factor');self.finish=self.module.get_function('finish_linear_status')

    def enqueue(self,matrix,rhs):
        n=self.size
        if cp.cuda.runtime.getDevice()!=self.device or cp.cuda.get_current_stream().ptr!=self.stream_ptr:raise ValueError('Resident linear instance requires its original device/ordered stream')
        if not isinstance(matrix,cp.ndarray) or not isinstance(rhs,cp.ndarray) or matrix.shape!=(n,n) or rhs.shape!=(n,) or matrix.dtype!=cp.float64 or rhs.dtype!=cp.float64:raise ValueError('Expected bounded FP64 matrix and vector')
        if matrix.device.id!=self.device or rhs.device.id!=self.device:raise ValueError('Linear inputs are on the wrong device')
        if any(cp.may_share_memory(value,private) for value in (matrix,rhs) for private in (self.factor,self.solution,self.workspace)):raise ValueError('Linear inputs may not alias private output/work buffers')
        # Copy input values; never overwrite the Newton tangent or residual.
        cp.copyto(self.factor,matrix);cp.copyto(self.solution,rhs)
        self.guard_input((1,),(128,),(self.factor,self.solution,np.uint32(n),self.status))
        handle=cp.cuda.device.get_cusolver_handle()
        self.native.check(self.native.set_stream(handle,self.stream_ptr))
        self.native.check(self.native.getrf(handle,n,n,self.factor.data.ptr,n,self.workspace.data.ptr,self.pivot.data.ptr,self.factor_info.data.ptr))
        self.guard_factor((1,),(128,),(self.factor,self.solution,self.pivot,np.uint32(n),self.factor_info,self.status))
        self.native.check(self.native.getrs(handle,cublas.CUBLAS_OP_N,n,1,self.factor.data.ptr,n,self.pivot.data.ptr,self.solution.data.ptr,n,self.solve_info.data.ptr))
        self.finish((1,),(128,),(self.solution,np.uint32(n),self.solve_info,self.status))
        return self.solution,self.status
