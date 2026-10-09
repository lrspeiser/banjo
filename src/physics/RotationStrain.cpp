#include "physics/RotationStrain.hpp"
#include "physics/FiniteFrameKernel.hpp"
#include <stdexcept>
namespace banjo {
namespace {
Quat unit(Quat q){
    const double n=std::sqrt(q.w*q.w+q.x*q.x+q.y*q.y+q.z*q.z);
    if(!std::isfinite(n)||std::abs(n-1)>1e-4)throw std::invalid_argument("invalid rotation strain frame");
    return {q.w/n,q.x/n,q.y/n,q.z/n};
}
}
RotationStrain rotationStrain(Quat a,Quat b){
    a=unit(a);b=unit(b);const auto shared=frameRotationStrainUnchecked({a.w,a.x,a.y,a.z},{b.w,b.x,b.y,b.z});
    if(shared.branch_angle>=3.141592653589793-1e-7)throw std::invalid_argument("rotation strain reaches nonunique pi branch");
    RotationStrain out{{shared.angle.x,shared.angle.y,shared.angle.z},{}};
    for(unsigned i=0;i<3;++i)out.gradient_axes_world[i]={shared.gradient[i].x,shared.gradient[i].y,shared.gradient[i].z};
    return out;
}
}
