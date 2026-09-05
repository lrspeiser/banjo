#pragma once
#include "core/Math.hpp"
#include <algorithm>
#include <array>
#include <numbers>
#include <stdexcept>

namespace banjo {
enum class PrimitiveKind { Sphere, Box };
// Dimensions describe occupied homogeneous matter, not a render proxy.
struct RigidPrimitive {
    PrimitiveKind kind{PrimitiveKind::Sphere};
    double radius_m{.06};
    Vec3 dimensions_m{.12,.08,.10}; // Full box lengths in object-local axes.

    [[nodiscard]] double volume() const {
        return kind==PrimitiveKind::Sphere ? 4.0/3*std::numbers::pi*radius_m*radius_m*radius_m
                                          : dimensions_m.x*dimensions_m.y*dimensions_m.z;
    }
    [[nodiscard]] Mat3 inertia(double mass) const {
        Mat3 result;
        if(kind==PrimitiveKind::Sphere) {
            for(unsigned i=0;i<3;++i)result.m[i][i]=.4*mass*radius_m*radius_m;
        }else {
            const auto d=dimensions_m;
            result.m[0][0]=mass*(d.y*d.y+d.z*d.z)/12;
            result.m[1][1]=mass*(d.x*d.x+d.z*d.z)/12;
            result.m[2][2]=mass*(d.x*d.x+d.y*d.y)/12;
        }
        return result;
    }
    [[nodiscard]] double extent(Vec3 unit_axis,Quat orientation) const {
        if(kind==PrimitiveKind::Sphere)return radius_m;
        return .5*(dimensions_m.x*std::abs(dot(unit_axis,orientation.rotate({1,0,0})))+
                   dimensions_m.y*std::abs(dot(unit_axis,orientation.rotate({0,1,0})))+
                   dimensions_m.z*std::abs(dot(unit_axis,orientation.rotate({0,0,1}))));
    }
    [[nodiscard]] std::array<Vec3,8> corners() const {
        std::array<Vec3,8> points;
        for(unsigned i=0;i<8;++i)points[i]={((i&1)?1:-1)*dimensions_m.x/2,
            ((i&2)?1:-1)*dimensions_m.y/2,((i&4)?1:-1)*dimensions_m.z/2};
        return points;
    }
};
// Exact sphere/OBB and OBB/OBB separation (15-axis SAT), with an explicit
// authoring clearance. Simulation contact remains owned by the rigid solver.
[[nodiscard]] inline bool primitivesOverlap(const RigidPrimitive &a,Vec3 pa,Quat qa,
    const RigidPrimitive &b,Vec3 pb,Quat qb,double clearance=.001) {
    if(a.kind==PrimitiveKind::Sphere&&b.kind==PrimitiveKind::Sphere)
        return length(pa-pb)<=a.radius_m+b.radius_m+clearance;
    if(a.kind==PrimitiveKind::Sphere||b.kind==PrimitiveKind::Sphere) {
        if(b.kind==PrimitiveKind::Sphere)return primitivesOverlap(b,pb,qb,a,pa,qa,clearance);
        const Quat inverse{qb.w,-qb.x,-qb.y,-qb.z};
        const Vec3 local=inverse.rotate(pa-pb),h=b.dimensions_m/2;
        const Vec3 closest{std::clamp(local.x,-h.x,h.x),std::clamp(local.y,-h.y,h.y),std::clamp(local.z,-h.z,h.z)};
        return length(local-closest)<=a.radius_m+clearance;
    }
    const std::array<Vec3,3> aa{qa.rotate({1,0,0}),qa.rotate({0,1,0}),qa.rotate({0,0,1})};
    const std::array<Vec3,3> bb{qb.rotate({1,0,0}),qb.rotate({0,1,0}),qb.rotate({0,0,1})};
    const auto separated=[&](Vec3 axis) {
        if(lengthSquared(axis)<1e-20)return false;
        axis=normalized(axis);
        return std::abs(dot(pa-pb,axis))>a.extent(axis,qa)+b.extent(axis,qb)+clearance;
    };
    for(auto axis:aa)if(separated(axis))return false;
    for(auto axis:bb)if(separated(axis))return false;
    for(auto x:aa)for(auto y:bb)if(separated(cross(x,y)))return false;
    return true;
}
[[nodiscard]] inline Mat3 rotateInertia(const Mat3 &local,Quat q) {
    const std::array<Vec3,3> axes{q.rotate({1,0,0}),q.rotate({0,1,0}),q.rotate({0,0,1})};
    double r[3][3]{{axes[0].x,axes[1].x,axes[2].x},{axes[0].y,axes[1].y,axes[2].y},{axes[0].z,axes[1].z,axes[2].z}};
    Mat3 result;
    for(unsigned i=0;i<3;++i)for(unsigned j=0;j<3;++j)
        for(unsigned k=0;k<3;++k)for(unsigned l=0;l<3;++l)result.m[i][j]+=r[i][k]*local.m[k][l]*r[j][l];
    return result;
}
}
