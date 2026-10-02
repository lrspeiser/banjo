#include "physics/PointRigidContact.hpp"
#include "physics/ContactTensor.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <limits>
#include <numbers>
#include <stdexcept>

namespace banjo {
namespace {
bool finite(Vec3 v) { return std::isfinite(v.x)&&std::isfinite(v.y)&&std::isfinite(v.z); }
double norm(Vec3 v) { return std::hypot(v.x,v.y,v.z); }
void require(bool ok,const char *why) { if (!ok) throw std::invalid_argument(why); }

double kinetic(const ActiveNodeState &node,const RigidMechanicalState &rigid) {
    const auto &motion=rigid.motion;
    return .5*node.mass_kg*lengthSquared(node.velocity_m_s)+
           .5*rigid.mass_kg*lengthSquared(motion.linear_velocity_m_s)+
           .5*dot(motion.angular_velocity_rad_s,rigid.inertia_world_kg_m2*motion.angular_velocity_rad_s);
}
Vec3 tangentPart(Vec3 v,Vec3 normal) { return v-dot(v,normal)*normal; }

// Nonassociated Coulomb slip: normal speed reaches its declared target and
// tangent impulse opposes the FINAL slip, with |Jt|=mu*Jn. A bounded angular
// root solve avoids treating an anisotropic body's tangent mass as a scalar.
struct SlipCandidate { bool valid{};Vec3 impulse{};double residual{},alignment{}; };
Vec3 slidingImpulse(Vec3 relative,Vec3 normal,const Mat3 &effective,
                    double wanted,double mu,unsigned &iterations) {
    const double normal_mass=dot(normal,effective*normal);
    const double normal_delta=wanted-dot(relative,normal);
    if (mu==0) return (normal_delta/normal_mass)*normal;
    const Vec3 initial=tangentPart(relative+(normal_delta/normal_mass)*(effective*normal),normal);
    const double speed=norm(initial);
    if (!(speed>0)) throw std::domain_error("point-rigid sliding direction is unresolved");
    const Vec3 u=initial/speed,v=cross(normal,u);
    const double tolerance=1e-11*std::max(norm(relative),std::abs(wanted));
    const auto candidate=[&](double angle) {
        ++iterations;
        const Vec3 direction=std::cos(angle)*u+std::sin(angle)*v;
        const Vec3 perpendicular=-std::sin(angle)*u+std::cos(angle)*v;
        const Vec3 response=effective*(normal-mu*direction);
        const double denominator=dot(normal,response);
        SlipCandidate out;
        if (!(denominator>0)||!std::isfinite(denominator)) return out;
        const double impulse=normal_delta/denominator;
        const Vec3 after=tangentPart(relative+impulse*response,normal);
        out.impulse=impulse*(normal-mu*direction);
        out.residual=dot(perpendicular,after);out.alignment=dot(direction,after);
        out.valid=finite(out.impulse)&&std::isfinite(out.residual)&&std::isfinite(out.alignment);
        return out;
    };
    double angle=0;
    // Newton near the post-normal slip direction, with bounded angular steps.
    for (unsigned attempt=0;attempt<24;++attempt) {
        const auto here=candidate(angle);
        if (!here.valid) break;
        if (std::abs(here.residual)<=tolerance&&here.alignment>=0) return here.impulse;
        const Vec3 direction=std::cos(angle)*u+std::sin(angle)*v;
        const Vec3 perpendicular=-std::sin(angle)*u+std::cos(angle)*v;
        const Vec3 response=effective*(normal-mu*direction);
        const Vec3 derivative=effective*(-mu*perpendicular);
        const double denominator=dot(normal,response);
        const double impulse=normal_delta/denominator;
        const double impulse_derivative=-impulse*dot(normal,derivative)/denominator;
        const Vec3 after=tangentPart(relative+impulse*response,normal);
        const Vec3 after_derivative=tangentPart(impulse_derivative*response+impulse*derivative,normal);
        const double slope=-dot(direction,after)+dot(perpendicular,after_derivative);
        if (!std::isfinite(slope)||std::abs(slope)<=std::numeric_limits<double>::epsilon()*speed) break;
        angle-=std::clamp(here.residual/slope,-std::numbers::pi/4,std::numbers::pi/4);
    }
    // A bracket contains only valid finite evaluations. Invalid mass signs
    // are never fabricated into a sign change or accepted as a slip root.
    double left=-std::numbers::pi;auto a=candidate(left);
    for (unsigned segment=1;segment<=64;++segment) {
        const double right=-std::numbers::pi+2*std::numbers::pi*segment/64;
        const auto b=candidate(right);
        if (b.valid&&std::abs(b.residual)<=tolerance&&b.alignment>=0) return b.impulse;
        if (a.valid&&b.valid&&std::signbit(a.residual)!=std::signbit(b.residual)) {
            double low=left,high=right;auto lower=a;
            for (unsigned split=0;split<48;++split) {
                const double middle=.5*(low+high);const auto c=candidate(middle);
                if (!c.valid) break;
                if (std::abs(c.residual)<=tolerance&&c.alignment>=0) return c.impulse;
                if (std::signbit(lower.residual)==std::signbit(c.residual)) { low=middle;lower=c; }
                else high=middle;
            }
        }
        left=right;a=b;
    }
    throw std::domain_error("point-rigid Coulomb slip did not converge");
}
} // namespace

PointRigidContactResult evaluatePointRigidContact(const ActiveNodeState &node,
    const RigidMechanicalState &rigid,Vec3 normal,double gap,double timestep,
    const PointRigidContactSettings &settings) {
    require(std::isfinite(timestep)&&timestep>0&&std::isfinite(gap)&&finite(normal)&&
            std::abs(norm(normal)-1)<=1e-10,"invalid point-rigid timestep, gap or unit normal");
    require(std::isfinite(settings.static_friction)&&std::isfinite(settings.dynamic_friction)&&
            settings.dynamic_friction>=0&&settings.static_friction>=settings.dynamic_friction&&
            std::isfinite(settings.restitution)&&settings.restitution>=0&&settings.restitution<=1&&
            std::isfinite(settings.restitution_speed_threshold_m_s)&&settings.restitution_speed_threshold_m_s>=0&&
            std::isfinite(settings.contact_margin_m)&&settings.contact_margin_m>=0,
            "invalid point-rigid contact law");
    require(std::isfinite(node.mass_kg)&&node.mass_kg>0&&std::isfinite(rigid.mass_kg)&&rigid.mass_kg>0&&
            finite(node.position_world_m)&&finite(node.velocity_m_s)&&
            finite(rigid.motion.center_of_mass_world_m)&&finite(rigid.motion.linear_velocity_m_s)&&
            finite(rigid.motion.angular_velocity_rad_s),"invalid point-rigid mass or motion");
    const Mat3 inverse_inertia=inverseContactTensor(rigid.inertia_world_kg_m2);
    normal=normal/norm(normal);
    const Vec3 arm=node.position_world_m-rigid.motion.center_of_mass_world_m;
    const Vec3 relative=node.velocity_m_s-rigid.motion.linear_velocity_m_s-
                        cross(rigid.motion.angular_velocity_rad_s,arm);
    const double before=kinetic(node,rigid);
    require(finite(arm)&&finite(relative)&&std::isfinite(before),"point-rigid state exceeds finite range");
    PointRigidContactResult out;out.rigid=rigid;out.node_velocity_m_s=node.velocity_m_s;
    out.relative_normal_before_m_s=dot(relative,normal);
    out.relative_normal_after_m_s=out.relative_normal_before_m_s;
    out.slip_after_m_s=norm(tangentPart(relative,normal));
    if (gap>std::max(settings.contact_margin_m,-out.relative_normal_before_m_s*timestep)) return out;
    const double restitution=-out.relative_normal_before_m_s>settings.restitution_speed_threshold_m_s?
        settings.restitution:0;
    out.target_normal_speed_m_s=gap>settings.contact_margin_m?-gap/timestep:
        -restitution*std::min(out.relative_normal_before_m_s,0.);
    if (out.relative_normal_before_m_s>=out.target_normal_speed_m_s) return out;
    Mat3 effective;
    const std::array<Vec3,3> directions{Vec3{1,0,0},Vec3{0,1,0},Vec3{0,0,1}};
    const double inverse_mass=1/node.mass_kg+1/rigid.mass_kg;
    for (unsigned column=0;column<3;++column) {
        const Vec3 response=inverse_mass*directions[column]+cross(inverse_inertia*cross(arm,directions[column]),arm);
        effective.m[0][column]=response.x;effective.m[1][column]=response.y;effective.m[2][column]=response.z;
    }
    const auto inverse_effective=inverseContactTensor(effective);
    Vec3 impulse=inverse_effective*(out.target_normal_speed_m_s*normal-relative);
    const double normal_candidate=dot(impulse,normal);
    if (normal_candidate>0&&norm(tangentPart(impulse,normal))<=settings.static_friction*normal_candidate) {
        out.sticking=true;
    } else impulse=slidingImpulse(relative,normal,effective,out.target_normal_speed_m_s,
                                  settings.dynamic_friction,out.friction_iterations);
    require(finite(impulse),"point-rigid impulse overflow");
    out.impulse_to_node_n_s=impulse;out.angular_impulse_to_rigid_kg_m2_s=-cross(arm,impulse);
    out.node_velocity_m_s+=impulse/node.mass_kg;
    out.rigid.motion.linear_velocity_m_s-=impulse/rigid.mass_kg;
    out.rigid.motion.angular_velocity_rad_s+=inverse_inertia*out.angular_impulse_to_rigid_kg_m2_s;
    require(finite(out.node_velocity_m_s)&&finite(out.rigid.motion.linear_velocity_m_s)&&
            finite(out.rigid.motion.angular_velocity_rad_s),"point-rigid candidate motion overflow");
    ActiveNodeState result_node=node;result_node.velocity_m_s=out.node_velocity_m_s;
    const double after=kinetic(result_node,out.rigid);
    const Vec3 relative_after=out.node_velocity_m_s-out.rigid.motion.linear_velocity_m_s-
        cross(out.rigid.motion.angular_velocity_rad_s,arm);
    out.normal_impulse_n_s=dot(impulse,normal);out.tangent_impulse_n_s=norm(tangentPart(impulse,normal));
    out.relative_normal_after_m_s=dot(relative_after,normal);
    out.slip_after_m_s=norm(tangentPart(relative_after,normal));
    out.impulse_work_j=dot(impulse,.5*(relative+relative_after));
    out.kinetic_change_j=after-before;
    const double energy_bound=1e-12+1e-10*(std::abs(before)+std::abs(after)+std::abs(out.impulse_work_j));
    if (!std::isfinite(after)||!std::isfinite(out.impulse_work_j)||out.impulse_work_j>energy_bound)
        throw std::domain_error("point-rigid restitution/friction produces positive kinetic work");
    out.dissipated_energy_j=std::max(0.,-out.impulse_work_j);
    out.work_residual_j=out.kinetic_change_j+out.dissipated_energy_j;
    const Vec3 point_impulse=node.mass_kg*(out.node_velocity_m_s-node.velocity_m_s);
    const Vec3 rigid_impulse=rigid.mass_kg*(out.rigid.motion.linear_velocity_m_s-rigid.motion.linear_velocity_m_s);
    out.momentum_residual_kg_m_s=point_impulse+rigid_impulse;
    out.angular_residual_kg_m2_s=cross(node.position_world_m,point_impulse)+
        cross(rigid.motion.center_of_mass_world_m,rigid_impulse)+
        rigid.inertia_world_kg_m2*(out.rigid.motion.angular_velocity_rad_s-rigid.motion.angular_velocity_rad_s);
    const double speed_bound=1e-10*std::max({norm(relative),std::abs(out.target_normal_speed_m_s),1e-12});
    if (!finite(out.momentum_residual_kg_m_s)||!finite(out.angular_residual_kg_m2_s)||
        !std::isfinite(out.work_residual_j)||std::abs(out.work_residual_j)>energy_bound||
        std::abs(out.relative_normal_after_m_s-out.target_normal_speed_m_s)>speed_bound||
        out.normal_impulse_n_s<0||(out.sticking&&out.slip_after_m_s>speed_bound))
        throw std::domain_error("point-rigid impulse failed its work or velocity audit");
    out.applied=true;return out;
}
} // namespace banjo
