#pragma once
#include "core/Math.hpp"
#include <algorithm>
#include <stdexcept>

namespace banjo {
// Instantaneous world-space state. Caller derives mass/inertia from matter and
// supplies an impulse from a contact/interface solve; this is not a force law.
struct AttachmentBody {
    double mass_kg{};
    Mat3 inertia_world_kg_m2;
    Vec3 center_m{}, velocity_m_s{}, angular_velocity_rad_s{};
};
struct AttachmentImpulseResult {
    AttachmentBody a,b;
    double kinetic_change_j{}, impulse_work_j{}, work_residual_j{};
    Vec3 momentum_residual_kg_m_s{}, angular_impulse_kg_m2_s{}, angular_residual_kg_m2_s{};
};
inline AttachmentImpulseResult applyAttachmentImpulse(const AttachmentBody &a,const AttachmentBody &b,
                                                       Vec3 point_a_m,Vec3 point_b_m,Vec3 impulse_on_a_n_s) {
    const auto finite=[](Vec3 v){return std::isfinite(v.x)&&std::isfinite(v.y)&&std::isfinite(v.z);};
    const auto inverse=[&](const AttachmentBody &body){
        if(!std::isfinite(body.mass_kg)||body.mass_kg<=0||!finite(body.center_m)||!finite(body.velocity_m_s)||!finite(body.angular_velocity_rad_s))
            throw std::invalid_argument("invalid attachment body");
        double scale=0;
        for(const auto &row:body.inertia_world_kg_m2.m)for(double x:row){if(!std::isfinite(x))throw std::invalid_argument("invalid inertia");scale=std::max(scale,std::abs(x));}
        if(scale==0)throw std::invalid_argument("zero inertia");
        Mat3 n=body.inertia_world_kg_m2;
        for(auto &row:n.m)for(double &x:row)x/=scale;
        for(unsigned i=0;i<3;++i)for(unsigned j=0;j<3;++j)
            if(std::abs(n.m[i][j]-n.m[j][i])>1e-14)throw std::invalid_argument("asymmetric inertia");
        if(n.m[0][0]<=0||n.m[0][0]*n.m[1][1]-n.m[0][1]*n.m[1][0]<=0||n.determinant()<=1e-14)
            throw std::invalid_argument("inertia must be positive definite and well conditioned");
        auto inv=n.inverse(0).value();for(auto &row:inv.m)for(double &x:row){x/=scale;if(!std::isfinite(x))throw std::invalid_argument("inertia inverse overflow");}return inv;
    };
    const auto ia=inverse(a),ib=inverse(b);
    if(!finite(point_a_m)||!finite(point_b_m)||!finite(impulse_on_a_n_s))throw std::invalid_argument("invalid attachment impulse/point");
    AttachmentImpulseResult out;out.a=a;out.b=b;
    const Vec3 ra=point_a_m-a.center_m,rb=point_b_m-b.center_m,j=impulse_on_a_n_s;
    out.a.velocity_m_s+=j/a.mass_kg;out.b.velocity_m_s-=j/b.mass_kg;
    out.a.angular_velocity_rad_s+=ia*cross(ra,j);out.b.angular_velocity_rad_s-=ib*cross(rb,j);
    const auto kinetic=[](const AttachmentBody &x){return .5*x.mass_kg*lengthSquared(x.velocity_m_s)+.5*dot(x.angular_velocity_rad_s,x.inertia_world_kg_m2*x.angular_velocity_rad_s);};
    const auto momentum=[](const AttachmentBody &x){return x.mass_kg*x.velocity_m_s;};
    const auto angular=[&](const AttachmentBody &x){return cross(x.center_m,momentum(x))+x.inertia_world_kg_m2*x.angular_velocity_rad_s;};
    const auto velocity=[](const AttachmentBody &x,Vec3 arm){return x.velocity_m_s+cross(x.angular_velocity_rad_s,arm);};
    out.kinetic_change_j=kinetic(out.a)+kinetic(out.b)-kinetic(a)-kinetic(b);
    out.impulse_work_j=.5*dot(j,velocity(a,ra)+velocity(out.a,ra)-velocity(b,rb)-velocity(out.b,rb));
    out.work_residual_j=out.kinetic_change_j-out.impulse_work_j;
    out.momentum_residual_kg_m_s=momentum(out.a)+momentum(out.b)-momentum(a)-momentum(b);
    // Equal/opposite impulses at distinct points have this net couple. A closed
    // central interaction requires it to vanish; a noncentral law owns it.
    out.angular_impulse_kg_m2_s=cross(point_a_m-point_b_m,j);
    out.angular_residual_kg_m2_s=angular(out.a)+angular(out.b)-angular(a)-angular(b)-out.angular_impulse_kg_m2_s;
    const double e=kinetic(a)+kinetic(b)+std::abs(out.impulse_work_j);
    if(!std::isfinite(e)||!std::isfinite(out.work_residual_j)||!finite(out.momentum_residual_kg_m_s)||!finite(out.angular_residual_kg_m2_s)||
       std::abs(out.work_residual_j)>1e-12+1e-10*e)
        throw std::invalid_argument("attachment impulse overflow or work budget exceeded");
    return out;
}
}
