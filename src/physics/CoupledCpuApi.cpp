// Bounded host ABI over the SAME private CPU/CUDA physical trial equations.
#include <cmath>
#include <initializer_list>
#include "physics/FiniteFrameKernel.hpp"
#include "physics/CohesiveInterfaceKernel.hpp"
#include "material/ConnectorModeKernel.hpp"
#include "physics/MaterialHistoryKernel.hpp"
#include "physics/NormalComplianceKernel.hpp"
#include "physics/CoupledGpuKernel.hpp"
#include "physics/CoupledFlightKernel.hpp"
#if defined(_WIN32)
#define BANJO_CPU_EXPORT extern "C" __declspec(dllexport)
#else
#define BANJO_CPU_EXPORT extern "C" __attribute__((visibility("default")))
#endif
namespace {
bool finite(const double* p,unsigned count){
    if(!p&&count)return false;
    for(unsigned i=0;i<count;++i)if(!std::isfinite(p[i]))return false;
    return true;
}
bool scene(const double* b,unsigned n,const double* e,unsigned m,double h,double gy){
    if(!n||n>banjo::dgMaxBodies||m>banjo::dgMaxEdges||!finite(b,30*n)||!finite(e,70*m)||
       !std::isfinite(h)||h<=0||h>1||!std::isfinite(gy))return false;
    for(unsigned i=0;i<n;++i){const double* r=b+30*i;
        if(r[0]<0||r[0]>2||r[0]!=std::floor(r[0])||r[1]<0||r[2]<0||r[3]<=0||
           (r[0]==0&&r[1]>0)||(r[1]>0&&r[2]<=0))return false;
        for(unsigned j=4;j<7;++j)if(r[j]<=0)return false;
        for(unsigned start:{10u,26u}){double norm=0;for(unsigned j=0;j<4;++j)norm+=r[start+j]*r[start+j];if(std::fabs(norm-1)>1e-10)return false;}
        for(unsigned j=0;j<3;++j)if(std::fabs(r[7+j]-(r[20+j]+r[23+j]))>1e-12)return false;
        if(r[1]>0&&r[0]==1&&(r[4]!=r[5]||r[4]!=r[6]))return false;
    }
    for(unsigned i=0;i<m;++i){const double* r=e+70*i;
        if(r[0]<0||r[1]<0||r[0]>=n||r[1]>=n||r[0]==r[1]||r[0]!=std::floor(r[0])||r[1]!=std::floor(r[1])||r[3]<=0||r[2]<0||r[2]>2||r[2]!=std::floor(r[2]))return false;
        for(unsigned start:{10u,14u}){double norm=0;for(unsigned j=0;j<4;++j)norm+=r[start+j]*r[start+j];if(std::fabs(norm-1)>1e-10)return false;}
        if(r[2]==1){for(unsigned j=23;j<35;++j)if(r[j]<=0)return false;}
        else if(r[18]<=0||r[19]<=0||r[20]<=0||r[21]<=0||r[22]<0||(r[2]==2&&r[23]<=0))return false;
    }
    return true;
}
}
BANJO_CPU_EXPORT unsigned banjo_coupled_cpu_abi(){return 1;}
BANJO_CPU_EXPORT int banjo_coupled_cpu_trials(const double* b,unsigned n,const double* e,unsigned m,
    const double* v,unsigned batch,double h,double gy,double* poses,double* residual,
    double* history,double* forces,double* ledger,int* faults){
    if(!batch||batch>384||!scene(b,n,e,m,h,gy)||!finite(v,6*n*batch)||!poses||!residual||
       (!history&&m)||!forces||!ledger||!faults)return -1;
    for(unsigned i=0;i<batch;++i)faults[i]=banjo::coupledTrialUnchecked(b,n,e,m,v+6*n*i,h,{0,gy,0},
        poses+7*n*i,residual+6*n*i,history?history+32*m*i:nullptr,forces+6*n*i,ledger+12*i);
    return 0;
}
BANJO_CPU_EXPORT int banjo_coupled_cpu_schedule(const double* b,unsigned n,double h,double gy,
    double phase,double tolerance,double* out){
    if(!scene(b,n,nullptr,0,h,gy)||!std::isfinite(phase)||phase<=0||phase>1||!std::isfinite(tolerance)||tolerance<0||!out)return -1;
    unsigned k=0;
    for(unsigned a=0;a<n;++a)for(unsigned c=a+1;c<n;++c){
        if(b[30*a+1]==0&&b[30*c+1]==0)continue;
        double va[6],vc[6];for(unsigned j=0;j<6;++j){va[j]=b[30*a+14+j];vc[j]=b[30*c+14+j];}
        if(b[30*a+1]>0)va[1]+=h*gy;
        if(b[30*c+1]>0)vc[1]+=h*gy;
        const auto pa=banjo::dgPrepareTrial(b+30*a,va,h),pc=banjo::dgPrepareTrial(b+30*c,vc,h);
        const auto r=banjo::dgContactSchedule(b+30*a,b+30*c,pa.initial,pc.initial,pa.ending,pc.ending,h,phase,tolerance);
        out[3*k]=r.step_s;out[3*k+1]=r.frequency_rad_s;out[3*k+2]=r.excitation_m_s;++k;
    }
    return static_cast<int>(k);
}
BANJO_CPU_EXPORT int banjo_coupled_cpu_flight(const double* b,unsigned n,unsigned sphere,double h,double gy,
    double travel,double* bounds,double* poses,double* v,double* f,double* r){
    if(!scene(b,n,nullptr,0,h,gy)||sphere>=n||b[30*sphere]!=2||b[30*sphere+1]<=0||
       !std::isfinite(travel)||travel<0||!bounds||!poses||!v||!f||!r)return -1;
    for(unsigned i=0;i<n;++i)banjo::dgIsolatedSphereBound(b,n,sphere,i,h,gy,travel,bounds);
    banjo::dgIsolatedSphereStep(b,sphere,h,gy,poses,v,f,r);
    return 0;
}
