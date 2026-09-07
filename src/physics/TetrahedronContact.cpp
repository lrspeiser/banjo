#include "physics/TetrahedronContact.hpp"

#include <Jolt/Jolt.h>
#include <Jolt/Geometry/ConvexSupport.h>
#include <Jolt/Geometry/EPAPenetrationDepth.h>

#include <cmath>
#include <cfloat>

namespace banjo {
namespace {
bool finite(Vec3 p) { return std::isfinite(p.x)&&std::isfinite(p.y)&&std::isfinite(p.z); }
JPH::Vec3 jolt(Vec3 p) { return JPH::Vec3(float(p.x),float(p.y),float(p.z)); }
Vec3 native(JPH::Vec3Arg p) { return {p.GetX(),p.GetY(),p.GetZ()}; }
double det(Vec3 a,Vec3 b,Vec3 c){return dot(a,cross(b,c));}
bool weights(Vec3 p,const std::array<Vec3,4>&t,std::array<double,4>&w){
    const Vec3 a=t[1]-t[0],b=t[2]-t[0],c=t[3]-t[0],q=p-t[0];
    const double d=det(a,b,c),scale=length(a)*length(b)*length(c);
    if(!std::isfinite(d)||!std::isfinite(scale)||std::abs(d)<=std::max(1.e-24,scale*1.e-12))return false;
    w[1]=det(q,b,c)/d;w[2]=det(a,q,c)/d;w[3]=det(a,b,q)/d;w[0]=1-w[1]-w[2]-w[3];
    for(double x:w)if(!std::isfinite(x)||x < -2.e-5 || x > 1.00002)return false;
    return true;
}
}

TetrahedronContactResult tetrahedronContact(const std::array<Vec3,4>&a,
                                             const std::array<Vec3,4>&b){
    TetrahedronContactResult r;
    for(Vec3 p:a)if(!finite(p)||length(p)>1000.)return r;
    for(Vec3 p:b)if(!finite(p)||length(p)>1000.)return r;
    std::array<double,4> dummy;
    if(!weights(a[0],a,dummy)||!weights(b[0],b,dummy))return r;
    std::array<JPH::Vec3,4> ja,jb;
    for(unsigned i=0;i<4;++i){ja[i]=jolt(a[i]);jb[i]=jolt(b[i]);}
    const JPH::PolygonConvexSupport support_a(ja),support_b(jb);
    JPH::EPAPenetrationDepth epa;JPH::Vec3 direction=JPH::Vec3::sAxisX(),pa,pb;
    ++r.narrow_phase_calls;
    const auto status=epa.GetPenetrationDepthStepGJK(support_a,0.f,support_b,0.f,1.e-8f,direction,pa,pb);
    if(status==JPH::EPAPenetrationDepth::EStatus::NotColliding){
        r.point_a_world_m=native(pa);r.point_b_world_m=native(pb);
        r.separation_distance_m=length(r.point_b_world_m-r.point_a_world_m);
        if(!weights(r.point_a_world_m,a,r.barycentric_a)||!weights(r.point_b_world_m,b,r.barycentric_b))return {};
        r.normal_a_to_b=r.separation_distance_m>0?(r.point_b_world_m-r.point_a_world_m)/r.separation_distance_m:Vec3{};
        r.resolved=true;return r;
    }
    if(status==JPH::EPAPenetrationDepth::EStatus::Indeterminate){
        if(!epa.GetPenetrationDepthStepEPA(support_a,support_b,FLT_EPSILON,direction,pa,pb))return r;
    }
    r.point_a_world_m=native(pa);r.point_b_world_m=native(pb);
    const Vec3 difference=r.point_b_world_m-r.point_a_world_m;
    r.penetration_depth_m=length(difference);
    if(!finite(difference)||!std::isfinite(r.penetration_depth_m)||
       !weights(r.point_a_world_m,a,r.barycentric_a)||!weights(r.point_b_world_m,b,r.barycentric_b))return {};
    if(r.penetration_depth_m>0.)r.normal_a_to_b=difference/r.penetration_depth_m;
    else { const Vec3 d=native(direction); if(lengthSquared(d)==0.)return {};r.normal_a_to_b=normalized(d); }
    r.hit=true;r.resolved=true;return r;
}
} // namespace banjo
