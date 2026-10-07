#include "physics/MaterialContactStencil.hpp"
#include "physics/ContactTensor.hpp"
#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace banjo {
namespace {
bool finite(Vec3 v) {return std::isfinite(v.x)&&std::isfinite(v.y)&&std::isfinite(v.z);}
double norm(Vec3 v) {return std::hypot(v.x,v.y,v.z);}
void require(bool v,const char *why) {if(!v)throw std::invalid_argument(why);}
}
MaterialContactStencil makeMaterialContactStencil(std::span<const ActiveNodeState> nodes,Vec3 surface) {
    require(nodes.size()>=4 && nodes.size()<=64 && finite(surface),"invalid material contact region or surface");
    const Vec3 base=nodes.front().position_world_m;
    double mass=0;Vec3 centre{};
    for(const auto &n:nodes) {
        require(std::isfinite(n.mass_kg)&&n.mass_kg>0&&finite(n.position_world_m)&&finite(n.previous_position_world_m)&&finite(n.velocity_m_s)&&
            n.spin_angular_velocity_rad_s.x==0&&n.spin_angular_velocity_rad_s.y==0&&n.spin_angular_velocity_rad_s.z==0,
            "invalid translational material contact node");
        mass+=n.mass_kg;
    }
    require(std::isfinite(mass)&&mass>0,"material contact region mass overflow");
    for(const auto &n:nodes)centre+=(n.mass_kg/mass)*(n.position_world_m-base);
    double radius=0;
    for(const auto &n:nodes)radius=std::max(radius,norm(n.position_world_m-base-centre));
    require(finite(centre)&&std::isfinite(radius)&&radius>=1e-9&&radius<=100,
        "material contact region has unsupported extent");
    const Vec3 wanted=(surface-base-centre)/radius;
    require(finite(wanted)&&norm(wanted)<=3,"material contact extrapolation exceeds its local support");
    Mat3 covariance;
    for(const auto &n:nodes) {
        const Vec3 q=(n.position_world_m-base-centre)/radius;
        const double v[]{q.x,q.y,q.z},fraction=n.mass_kg/mass;
        for(unsigned i=0;i<3;++i)for(unsigned j=0;j<3;++j)covariance.m[i][j]+=fraction*v[i]*v[j];
    }
    const Vec3 affine=inverseContactTensor(covariance)*wanted;
    MaterialContactStencil out;out.point.position_world_m=surface;out.point.previous_position_world_m=surface;
    out.weights.reserve(nodes.size());double sum=0,inverse_mass=0;Vec3 moment{};
    for(const auto &n:nodes) {
        const Vec3 q=(n.position_world_m-base-centre)/radius;
        const double w=(n.mass_kg/mass)*(1+dot(q,affine));
        require(std::isfinite(w)&&std::abs(w)<=4,"material contact weight exceeds bounded affine reduction");
        out.weights.push_back(w);sum+=w;moment+=w*q;inverse_mass+=w*w/n.mass_kg;
        out.point.velocity_m_s+=w*n.velocity_m_s;
    }
    require(std::abs(sum-1)<=1e-10&&norm(moment-wanted)<=1e-10&&std::isfinite(inverse_mass)&&inverse_mass>0&&
        finite(out.point.velocity_m_s),"material contact affine reproduction is unresolved");
    out.point.mass_kg=1/inverse_mass;
    require(std::isfinite(out.point.mass_kg)&&out.point.mass_kg>0,"material contact virtual mass overflow");
    return out;
}
std::vector<Vec3> materialContactVelocities(std::span<const ActiveNodeState> nodes,
    const MaterialContactStencil &stencil,Vec3 impulse) {
    require(nodes.size()==stencil.weights.size()&&finite(impulse),"invalid material contact impulse span");
    // Revalidate the mutable value against the current support before emitting
    // candidates; a stale velocity/mass/geometry or edited weight cannot pass.
    const auto checked=makeMaterialContactStencil(nodes,stencil.point.position_world_m);
    require(checked.weights==stencil.weights&&checked.point.mass_kg==stencil.point.mass_kg&&
        norm(checked.point.velocity_m_s-stencil.point.velocity_m_s)==0&&
        norm(stencil.point.previous_position_world_m-stencil.point.position_world_m)==0&&
        norm(stencil.point.spin_angular_velocity_rad_s)==0,"stale or edited material contact stencil");
    std::vector<Vec3> result;result.reserve(nodes.size());
    for(std::size_t i=0;i<nodes.size();++i) {
        require(std::isfinite(nodes[i].mass_kg)&&nodes[i].mass_kg>0&&std::isfinite(stencil.weights[i]),
            "invalid material contact update");
        const Vec3 v=nodes[i].velocity_m_s+(stencil.weights[i]/nodes[i].mass_kg)*impulse;
        require(finite(v),"material contact velocity overflow");result.push_back(v);
    }
    return result;
}
}
