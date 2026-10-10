// Bounded ideal revolute-joint reference. SI, CPU FP64; no renderer dependency.
#include <algorithm>
#include <cmath>
#include <limits>
#ifdef _WIN32
#define BANJO_MECHANISM_EXPORT extern "C" __declspec(dllexport)
#else
#define BANJO_MECHANISM_EXPORT extern "C" __attribute__((visibility("default")))
#endif
namespace {
double sinc(double x) { return std::abs(x)<1e-5 ? 1-x*x/6+x*x*x*x/120 : std::sin(x)/x; }
// Exact angle-integrated torque divided by angle increment, including its limit.
double torque(double a,double b,double gravityTorque,double forceLever,double fx,double fy,double drive) {
    const double mid=.5*(a+b), scale=sinc(.5*(b-a));
    return scale*(-gravityTorque*std::sin(mid)+forceLever*(fx*std::cos(mid)+fy*std::sin(mid)))+drive;
}
}
BANJO_MECHANISM_EXPORT int banjo_mechanism_abi() { return 1; }
// settings: mass, I_pin, I_com, length, g, Fx, Fy, drive torque, support, dt.
// state: time, angle, angular velocity, COM x/y, COM vx/vy, mode (0 sleep,1 hinge,2 free).
// receipt: deltaK, deltaUg, external work, energy residual, support Jx/Jy,
//          external Jx/Jy, applied angular impulse about pin/COM, solve residual, iterations,
//          support angular impulse, external angular impulse, Px/Py/Lz residuals.
BANJO_MECHANISM_EXPORT int banjo_mechanism_step(const double* p,const double* before,double* after,double* receipt) {
    if(!p||!before||!after||!receipt) return -1;
    for(int i=0;i<10;++i) if(!std::isfinite(p[i])) return -2;
    for(int i=0;i<8;++i) if(!std::isfinite(before[i])) return -2;
    if(p[0]<=0||p[1]<=0||p[2]<=0||p[3]<=0||p[4]<0||p[9]<=0||p[9]>.02||
       (p[8]!=0&&p[8]!=1)||before[7]<0||before[7]>2||std::floor(before[7])!=before[7]) return -3;
    const double representedPinInertia=p[2]+p[0]*p[3]*p[3]*.25;
    if(!std::isfinite(representedPinInertia)||std::abs(p[1]-representedPinInertia)>1e-12*representedPinInertia||before[0]<0) return -9;
    double s[8]; std::copy(before,before+8,s);
    const double m=p[0], l=p[3]*.5,h=p[9],a=s[1],w=s[2];
    const bool pinned=p[8]==1;
    if(pinned&&s[7]==2) return -4; // Reattaching a moving object needs an impact law.
    if(s[7]!=2) { s[3]=l*std::sin(a); s[4]=1.5-l*std::cos(a); s[5]=l*std::cos(a)*w; s[6]=l*std::sin(a)*w; }
    const double inertia=pinned?p[1]:p[2], grav=pinned?m*p[4]*l:0,lever=pinned?p[3]:l;
    // Bounded unique-root regime; refusing an unresolved interval preserves state.
    const double lipschitz=std::abs(grav)+lever*std::hypot(p[5],p[6]);
    if(h*h*lipschitz/inertia>.25) return -5;
    double b=a+h*w; int it=0;
    for(;it<80;++it) {
        const double next=a+h*w+.5*h*h*torque(a,b,grav,lever,p[5],p[6],p[7])/inertia;
        if(std::abs(next-b)<2e-15*(1+std::abs(next))) {b=next;break;}
        b=next;
    }
    if(it==80||!std::isfinite(b)) return -6;
    const double tq=torque(a,b,grav,lever,p[5],p[6],p[7]);
    const double w1=w+h*tq/inertia;
    double n[8]={s[0]+h,b,w1,0,0,0,0,1};
    if(pinned) {
        n[3]=l*std::sin(b);n[4]=1.5-l*std::cos(b);
        n[5]=l*std::cos(b)*w1;n[6]=l*std::sin(b)*w1;
        if(a==0&&w==0&&p[5]==0&&p[7]==0&&p[6]<=0) n[7]=0;
    } else {
        n[7]=2;n[5]=s[5]+h*p[5]/m;n[6]=s[6]+h*(p[6]/m-p[4]);
        n[3]=s[3]+.5*h*(s[5]+n[5]);n[4]=s[4]+.5*h*(s[6]+n[6]);
    }
    const auto kinetic=[&](const double* v) {return .5*m*(v[5]*v[5]+v[6]*v[6])+.5*p[2]*v[2]*v[2];};
    const double dk=kinetic(n)-kinetic(s),du=m*p[4]*(n[4]-s[4]);
    const double forceArm=pinned?p[3]:l;
    const double tipdx=(pinned?0:n[3]-s[3])+forceArm*(std::sin(b)-std::sin(a));
    const double tipdy=(pinned?0:n[4]-s[4])-forceArm*(std::cos(b)-std::cos(a));
    const double work=p[5]*tipdx+p[6]*tipdy+p[7]*(b-a);
    const double jx=h*p[5],jy=h*(p[6]-m*p[4]);
    const double rx=m*(n[5]-s[5])-jx,ry=m*(n[6]-s[6])-jy;
    const double supportL=pinned?-1.5*rx:0;
    const double externalL=pinned?h*tq-1.5*jx:
        .5*(s[3]+n[3])*jy-.5*(s[4]+n[4])*jx+h*tq;
    const auto angular=[&](const double* v) {return m*(v[3]*v[6]-v[4]*v[5])+p[2]*v[2];};
    double r[16]={dk,du,work,dk+du-work,rx,ry,jx,jy,h*tq,
        b-a-.5*h*(w+w1),static_cast<double>(it+1),supportL,externalL,
        m*(n[5]-s[5])-jx-rx,m*(n[6]-s[6])-jy-ry,angular(n)-angular(s)-externalL-supportL};
    if(!pinned&&(std::abs(rx)+std::abs(ry)>1e-10*(1+m)))return -7;
    for(double v:n)if(!std::isfinite(v))return -8;
    for(double v:r)if(!std::isfinite(v))return -8;
    const double energyScale=1+std::abs(kinetic(s))+std::abs(m*p[4]*s[4])+std::abs(work);
    const double angularScale=1+std::abs(angular(s))+std::abs(externalL)+std::abs(supportL);
    if(std::abs(r[3])>2e-10*energyScale||std::abs(r[15])>1e-10*angularScale) return -10;
    std::copy(n,n+8,after);std::copy(r,r+16,receipt);return 0;
}
