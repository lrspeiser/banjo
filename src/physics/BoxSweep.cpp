#include "physics/BoxSweep.hpp"
#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>
namespace banjo {
BoxSweep boundBoxSweep(Vec3 size,Vec3 center,Quat q,double travel){
    const auto finite=[](Vec3 x){return std::isfinite(x.x)&&std::isfinite(x.y)&&std::isfinite(x.z);};
    const double norm=q.w*q.w+q.x*q.x+q.y*q.y+q.z*q.z;
    if(!finite(size)||!finite(center)||std::min({size.x,size.y,size.z})<=0||
       !std::isfinite(norm)||std::abs(norm-1)>1e-4||!std::isfinite(travel)||travel<0)
        throw std::invalid_argument("invalid finite box sweep");
    const auto x=q.rotate({size.x/2,0,0}),y=q.rotate({0,size.y/2,0}),z=q.rotate({0,0,size.z/2});
    // Native geometry/poses are float. Pad bounds, never alter a body pose.
    const double pad=64*std::numeric_limits<float>::epsilon()*std::max({length(size),std::abs(center.x),std::abs(center.y),std::abs(center.z)});
    return {center,{std::abs(x.x)+std::abs(y.x)+std::abs(z.x)+pad,
                    std::abs(x.y)+std::abs(y.y)+std::abs(z.y)+pad,
                    std::abs(x.z)+std::abs(y.z)+std::abs(z.z)+pad},travel,std::min({size.x,size.y,size.z})};
}
double boxSweepRatio(const BoxSweep &a,const BoxSweep &b,double margin){
    if(!std::isfinite(margin)||margin<0)throw std::invalid_argument("invalid speculative sweep margin");
    const double travel=a.vertex_travel_m+b.vertex_travel_m;
    const auto extent=a.half_extent_m+b.half_extent_m;
    const auto delta=b.center_m-a.center_m;
    if(std::abs(delta.x)>extent.x+travel+margin||std::abs(delta.y)>extent.y+travel+margin||std::abs(delta.z)>extent.z+travel+margin)return 0;
    return travel/(.05*std::min(a.minimum_feature_m,b.minimum_feature_m));
}
}
