#include "physics/RotationStrain.hpp"
#include <stdexcept>
namespace banjo {
namespace {
Quat unit(Quat q){
    const double n=std::sqrt(q.w*q.w+q.x*q.x+q.y*q.y+q.z*q.z);
    if(!std::isfinite(n)||std::abs(n-1)>1e-4)throw std::invalid_argument("invalid rotation strain frame");
    return {q.w/n,q.x/n,q.y/n,q.z/n};
}
Quat multiply(Quat a,Quat b){return {a.w*b.w-a.x*b.x-a.y*b.y-a.z*b.z,
    a.w*b.x+a.x*b.w+a.y*b.z-a.z*b.y,a.w*b.y-a.x*b.z+a.y*b.w+a.z*b.x,
    a.w*b.z+a.x*b.y-a.y*b.x+a.z*b.w};}
}
RotationStrain rotationStrain(Quat a,Quat b){
    a=unit(a);b=unit(b);auto q=multiply({a.w,-a.x,-a.y,-a.z},b);
    if(q.w<0)q={-q.w,-q.x,-q.y,-q.z};
    const Vec3 v{q.x,q.y,q.z};const double sine=length(v),angle=2*std::atan2(sine,q.w);
    if(angle>=3.141592653589793-1e-7)throw std::invalid_argument("rotation strain reaches nonunique pi branch");
    const Vec3 phi=sine>1e-14?v*(angle/sine):v*2;
    const double t2=lengthSquared(phi);
    // J_left^{-T} = I + [phi]/2 + A [phi]^2; series avoids cancellation.
    const double coefficient=t2<1e-8?1./12+t2/720+t2*t2/30240:
        (1-.5*angle/std::tan(.5*angle))/t2;
    RotationStrain out{phi,{}};const Vec3 axes[]{{1,0,0},{0,1,0},{0,0,1}};
    for(unsigned i=0;i<3;++i)out.gradient_axes_world[i]=a.rotate(axes[i]+.5*cross(phi,axes[i])+coefficient*cross(phi,cross(phi,axes[i])));
    return out;
}
}
