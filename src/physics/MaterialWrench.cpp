#include "physics/MaterialWrench.hpp"
#include <stdexcept>
namespace banjo {
namespace {
FrameVector vector(Vec3 v){if(!std::isfinite(v.x)||!std::isfinite(v.y)||!std::isfinite(v.z))throw std::invalid_argument("nonfinite material frame");return {v.x,v.y,v.z};}
FrameQuaternion unit(Quat q){
    const double n=std::sqrt(q.w*q.w+q.x*q.x+q.y*q.y+q.z*q.z);
    if(!std::isfinite(n)||std::abs(n-1)>1e-4)throw std::invalid_argument("nonunit material frame");
    return {q.w/n,q.x/n,q.y/n,q.z/n};
}
}
FiniteFrameCoordinates materialCoordinates(const MaterialFrame &a,const MaterialFrame &b){
    const auto out=finiteFrameCoordinatesUnchecked(vector(a.com),vector(b.com),unit(a.orientation),unit(b.orientation),vector(a.local_anchor),vector(b.local_anchor),unit(a.local_frame),unit(b.local_frame));
    if(out.rotation.branch_angle>=3.141592653589793-1e-7)throw std::invalid_argument("material frame reaches nonunique pi branch");
    for(const auto q:out.q)if(!std::isfinite(q))throw std::invalid_argument("nonfinite material coordinate");
    return out;
}
FiniteFrameWrenches materialWrenches(const MaterialFrame &a,const MaterialFrame &b,const std::array<double,6> &loads){
    for(const auto load:loads)if(!std::isfinite(load))throw std::invalid_argument("nonfinite material load");
    return finiteFrameWrenchesUnchecked(materialCoordinates(a,b),vector(a.com),vector(b.com),loads.data());
}
}
