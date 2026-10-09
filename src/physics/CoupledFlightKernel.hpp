#pragma once
// Shared swept proof and isolated isotropic flight. Requires CoupledGpuKernel.
// Same midpoint gravity/Cayley trial; no substitute contact response.
#if defined(__CUDACC__) || defined(__CUDACC_RTC__)
#define BANJO_FLIGHT_HD __host__ __device__
#else
#define BANJO_FLIGHT_HD
#endif
namespace banjo {
BANJO_FLIGHT_HD inline void dgIsolatedSphereBound(const double *bodies,unsigned n,unsigned sphere,unsigned i,
    double h,double gy,double accepted_other_travel,double *bounds){
    if(i>=n)return;
    if(i==sphere){bounds[i]=1e300;return;}
    const double *a=bodies+30*sphere,*b=bodies+30*i;
    double v[6];for(unsigned j=0;j<6;++j)v[j]=a[14+j];v[1]+=h*gy;
    const auto p=banjo::dgPrepareTrial(a,v,h);
    const auto d=banjo::dgSub(p.ending.p,p.initial.p);
    const double curve=fabs(gy)*h*h/8; // parabola's deviation from its chord
    const double other_travel=b[1]>0?accepted_other_travel:0;
    if(static_cast<int>(b[0])==0){
        const auto normal=banjo::frameRotate(banjo::dgRead4(b+10),{0,1,0});
        const double first=banjo::frameDot(banjo::dgSub(p.initial.p,banjo::dgRead3(b+7)),normal);
        const double last=banjo::frameDot(banjo::dgSub(p.ending.p,banjo::dgRead3(b+7)),normal);
        bounds[i]=(first<last?first:last)-a[4]-curve-other_travel;return;
    }
    const auto relative=banjo::dgSub(banjo::dgRead3(b+7),p.initial.p);
    const double length2=banjo::frameDot(d,d);
    double t=length2>0?banjo::frameDot(relative,d)/length2:0;t=t<0?0:t>1?1:t;
    const auto closest=banjo::frameAdd(p.initial.p,banjo::frameScale(d,t));
    // An enclosing sphere covers a box at every orientation, including
    // rotations beyond the current angular gate. It does not supply response.
    const double radius=static_cast<int>(b[0])==2?b[4]:sqrt(b[4]*b[4]+b[5]*b[5]+b[6]*b[6]);
    bounds[i]=banjo::dgLength(banjo::dgSub(closest,banjo::dgRead3(b+7)))-a[4]-radius-curve-other_travel;
}
BANJO_FLIGHT_HD inline void dgIsolatedSphereStep(const double *bodies,unsigned sphere,double h,double gy,
    double *poses,double *velocity,double *forces,double *residual){
const double *a=bodies+30*sphere;
    double v[6];for(unsigned j=0;j<6;++j)v[j]=a[14+j];v[1]+=h*gy;
    const auto p=banjo::dgPrepareTrial(a,v,h);
    banjo::dgWrite3(poses,p.ending.p);banjo::dgWrite4(poses+3,p.ending.q);
    for(unsigned j=0;j<6;++j){velocity[j]=v[j];forces[j]=j==1?a[1]*gy:0;
        const double mass=j<3?a[1]:a[2];residual[j]=(v[j]-a[14+j])*sqrt(mass)-h*forces[j]/sqrt(mass);}
}
}

#undef BANJO_FLIGHT_HD
