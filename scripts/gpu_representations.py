"""CUDA wrappers for the shared isolated sphere equations."""
from coupled_representations import FlightPartition,FAMILIES
KERNEL=r'''
extern "C" __global__ void isolated_sphere_bounds(const double *bodies,unsigned n,unsigned sphere,
    double h,double gy,double accepted_other_travel,double *bounds){
    const unsigned i=blockDim.x*blockIdx.x+threadIdx.x;
    banjo::dgIsolatedSphereBound(bodies,n,sphere,i,h,gy,accepted_other_travel,bounds);
}
extern "C" __global__ void isolated_sphere_step(const double *bodies,unsigned sphere,double h,double gy,
    double *poses,double *velocity,double *forces,double *residual){
    if(threadIdx.x||blockIdx.x)return;
    banjo::dgIsolatedSphereStep(bodies,sphere,h,gy,poses,velocity,forces,residual);
}
'''
