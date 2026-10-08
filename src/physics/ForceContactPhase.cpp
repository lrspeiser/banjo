#include "physics/ForceContactPhase.hpp"
#include "physics/ContactTensor.hpp"
#include <cmath>
#include <stdexcept>

namespace banjo {
namespace {
void require(bool ok,const char *why){if(!ok)throw std::invalid_argument(why);}
bool finite(Vec3 v){return std::isfinite(v.x)&&std::isfinite(v.y)&&std::isfinite(v.z);}
bool equal(Vec3 a,Vec3 b){return a.x==b.x&&a.y==b.y&&a.z==b.z;}
bool equal(Quat a,Quat b){return a.w==b.w&&a.x==b.x&&a.y==b.y&&a.z==b.z;}
void measure(ForceContactPhaseAudit &out,Vec3 v0,Vec3 v1,Vec3 v2,Vec3 jf,Vec3 jc) {
    require(finite(v0)&&finite(v1)&&finite(v2)&&finite(jf)&&finite(jc),"force/contact phase kinematics overflow");
    out.sequential_force_work_j+=.5*dot(jf,v0+v1);
    out.sequential_contact_work_j+=.5*dot(jc,v1+v2);
    out.simultaneous_force_work_j+=.5*dot(jf,v0+v2);
    out.simultaneous_contact_work_j+=.5*dot(jc,v0+v2);
    out.force_cross_work_j+=.5*dot(jf,v2-v1);
    out.contact_cross_work_j-=.5*dot(jc,v1-v0);
}
}
ForceContactPhaseAudit auditForceContactPhase(std::span<const ForceContactPointStates> points,
    std::span<const ForceContactRigidStates> rigid) {
    require(points.size()<=1024&&rigid.size()<=256&&(!points.empty()||!rigid.empty()),"force/contact phase exceeds bounded DOF domain");
    ForceContactPhaseAudit out;Vec3 delta_p{},delta_l{};
    for(const auto &states:points){const auto &a=states.before_forces,&b=states.after_forces,&c=states.after_contact;
        require(std::isfinite(a.mass_kg)&&a.mass_kg>0&&a.mass_kg==b.mass_kg&&a.mass_kg==c.mass_kg&&finite(a.position_world_m)&&
            finite(a.previous_position_world_m)&&equal(a.position_world_m,b.position_world_m)&&equal(a.position_world_m,c.position_world_m)&&
            equal(a.previous_position_world_m,b.previous_position_world_m)&&equal(a.previous_position_world_m,c.previous_position_world_m)&&
            equal(a.spin_angular_velocity_rad_s,{})&&equal(b.spin_angular_velocity_rad_s,{})&&equal(c.spin_angular_velocity_rad_s,{}),
            "force/contact phase changed point geometry/mass or admitted spin");
        const auto jf=a.mass_kg*(b.velocity_m_s-a.velocity_m_s),jc=a.mass_kg*(c.velocity_m_s-b.velocity_m_s);
        measure(out,a.velocity_m_s,b.velocity_m_s,c.velocity_m_s,jf,jc);
        out.kinetic_change_j+=.5*a.mass_kg*dot(c.velocity_m_s-a.velocity_m_s,c.velocity_m_s+a.velocity_m_s);
        out.force_impulse_n_s+=jf;out.contact_impulse_n_s+=jc;
        out.force_angular_impulse_kg_m2_s+=cross(a.position_world_m,jf);out.contact_angular_impulse_kg_m2_s+=cross(a.position_world_m,jc);
        const auto delta=a.mass_kg*(c.velocity_m_s-a.velocity_m_s);delta_p+=delta;delta_l+=cross(a.position_world_m,delta);
    }
    for(const auto &states:rigid){const auto &a=states.before_forces,&b=states.after_forces,&c=states.after_contact;
        require(std::isfinite(a.mass_kg)&&a.mass_kg>0&&finite(a.motion.center_of_mass_world_m),"invalid finite rigid phase mass/geometry");
        const auto q=a.motion.orientation_world;
        require(std::isfinite(q.w)&&std::isfinite(q.x)&&std::isfinite(q.y)&&std::isfinite(q.z)&&
            std::abs(q.w*q.w+q.x*q.x+q.y*q.y+q.z*q.z-1)<=1e-10,"invalid unit rigid phase orientation");
        (void)inverseContactTensor(a.inertia_world_kg_m2);
        require(a.mass_kg==b.mass_kg&&a.mass_kg==c.mass_kg&&a.inertia_world_kg_m2.m==b.inertia_world_kg_m2.m&&
            a.inertia_world_kg_m2.m==c.inertia_world_kg_m2.m&&equal(a.motion.center_of_mass_world_m,b.motion.center_of_mass_world_m)&&
            equal(a.motion.center_of_mass_world_m,c.motion.center_of_mass_world_m)&&equal(a.motion.orientation_world,b.motion.orientation_world)&&
            equal(a.motion.orientation_world,c.motion.orientation_world),"force/contact phase changed rigid geometry/mass/tensor");
        const auto v0=a.motion.linear_velocity_m_s,v1=b.motion.linear_velocity_m_s,v2=c.motion.linear_velocity_m_s;
        const auto w0=a.motion.angular_velocity_rad_s,w1=b.motion.angular_velocity_rad_s,w2=c.motion.angular_velocity_rad_s;
        const auto jf=a.mass_kg*(v1-v0),jc=a.mass_kg*(v2-v1);
        const auto kf=a.inertia_world_kg_m2*(w1-w0),kc=a.inertia_world_kg_m2*(w2-w1);
        measure(out,v0,v1,v2,jf,jc);measure(out,w0,w1,w2,kf,kc);
        out.kinetic_change_j+=.5*a.mass_kg*dot(v2-v0,v2+v0)+.5*dot(a.inertia_world_kg_m2*(w2-w0),w2+w0);
        out.force_impulse_n_s+=jf;out.contact_impulse_n_s+=jc;
        out.force_angular_impulse_kg_m2_s+=cross(a.motion.center_of_mass_world_m,jf)+kf;
        out.contact_angular_impulse_kg_m2_s+=cross(a.motion.center_of_mass_world_m,jc)+kc;
        const auto delta=a.mass_kg*(v2-v0);delta_p+=delta;delta_l+=cross(a.motion.center_of_mass_world_m,delta)+a.inertia_world_kg_m2*(w2-w0);
    }
    out.energy_residual_j=out.kinetic_change_j-out.simultaneous_force_work_j-out.simultaneous_contact_work_j;
    out.cross_work_residual_j=out.force_cross_work_j+out.contact_cross_work_j;
    out.momentum_residual_n_s=delta_p-out.force_impulse_n_s-out.contact_impulse_n_s;
    out.angular_residual_kg_m2_s=delta_l-out.force_angular_impulse_kg_m2_s-out.contact_angular_impulse_kg_m2_s;
    for(double value:{out.kinetic_change_j,out.sequential_force_work_j,out.sequential_contact_work_j,
        out.simultaneous_force_work_j,out.simultaneous_contact_work_j,out.force_cross_work_j,out.contact_cross_work_j,
        out.energy_residual_j,out.cross_work_residual_j})require(std::isfinite(value),"force/contact phase work overflow");
    for(Vec3 value:{out.force_impulse_n_s,out.contact_impulse_n_s,out.force_angular_impulse_kg_m2_s,
        out.contact_angular_impulse_kg_m2_s,out.momentum_residual_n_s,out.angular_residual_kg_m2_s})
        require(finite(value),"force/contact phase impulse overflow");
    return out;
}
}
