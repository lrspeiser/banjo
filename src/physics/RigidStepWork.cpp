#include "physics/RigidStepWork.hpp"
#include <algorithm>
#include <cmath>
#include <stdexcept>
namespace banjo {
namespace {
bool finite(Vec3 v){return std::isfinite(v.x)&&std::isfinite(v.y)&&std::isfinite(v.z);}
double kinetic(const RigidMechanicalState &s,Vec3 v,Vec3 w){return .5*s.mass_kg*lengthSquared(v)+.5*dot(w,s.inertia_world_kg_m2*w);}
}
RigidStepWork auditRigidStepWork(std::span<const RigidStepWorkInput> states,Vec3 gravity){
    if(states.empty()||states.size()>512||!finite(gravity))throw std::invalid_argument("invalid rigid work audit domain");
    RigidStepWork out;
    for(const auto &s:states){const auto &a=s.before,&b=s.after;
        if(!std::isfinite(a.mass_kg)||a.mass_kg<=0||a.mass_kg!=b.mass_kg)
            throw std::invalid_argument("rigid work audit mass changed");
        for(auto v:{a.motion.center_of_mass_world_m,b.motion.center_of_mass_world_m,a.motion.linear_velocity_m_s,a.motion.angular_velocity_rad_s,
            b.motion.linear_velocity_m_s,b.motion.angular_velocity_rad_s,s.spin_after_gyro_rad_s,s.velocity_after_forces_m_s,s.spin_after_forces_rad_s,
            s.gravity_impulse_n_s,s.spring_impulse_n_s,s.spring_couple_n_m_s,s.contact_impulse_n_s,s.contact_couple_n_m_s,
            s.velocity_after_solver_m_s,s.spin_after_solver_rad_s,s.velocity_after_limit_m_s,s.spin_after_limit_rad_s})
            if(!finite(v))throw std::invalid_argument("rigid work audit nonfinite state/source");
        for(const auto *tensor:{&a.inertia_world_kg_m2,&b.inertia_world_kg_m2}){
            double scale=0;for(const auto &row:tensor->m)for(double x:row){if(!std::isfinite(x))throw std::invalid_argument("rigid work audit nonfinite inertia");scale=std::max(scale,std::abs(x));}
            if(!(tensor->m[0][0]>0&&tensor->m[1][1]>0&&tensor->m[2][2]>0&&tensor->m[0][0]*tensor->m[1][1]-tensor->m[0][1]*tensor->m[1][0]>0&&tensor->determinant()>0))throw std::invalid_argument("rigid work audit invalid inertia");
            for(unsigned i=0;i<3;++i)for(unsigned j=i+1;j<3;++j)if(std::abs(tensor->m[i][j]-tensor->m[j][i])>1e-6*scale)
                throw std::invalid_argument("rigid work audit native inertia skew exceeds bound");
        }
        const auto v0=a.motion.linear_velocity_m_s,w0=a.motion.angular_velocity_rad_s,v1=s.velocity_after_forces_m_s,w1=s.spin_after_forces_rad_s;
        const auto v2=s.integration_observed?s.velocity_after_solver_m_s:b.motion.linear_velocity_m_s;
        const auto w2=s.integration_observed?s.spin_after_solver_rad_s:b.motion.angular_velocity_rad_s;
        const auto vl=s.integration_observed?s.velocity_after_limit_m_s:v2,wl=s.integration_observed?s.spin_after_limit_rad_s:w2;
        const auto vf=b.motion.linear_velocity_m_s,wf=b.motion.angular_velocity_rad_s;
        const double k0=kinetic(a,v0,w0),kg=kinetic(a,v0,s.spin_after_gyro_rad_s),k1=kinetic(a,v1,w1),k2=kinetic(a,v2,w2);
        const double kl=kinetic(a,vl,wl),rotated=kinetic(b,vl,wl),actual=kinetic(b,vf,wf);
        const double gravity_work=dot(s.gravity_impulse_n_s,.5*(v0+v1));
        const double spring=dot(s.spring_impulse_n_s,.5*(v1+v2))+dot(s.spring_couple_n_m_s,.5*(w1+w2));
        const double contact=dot(s.contact_impulse_n_s,.5*(v1+v2))+dot(s.contact_couple_n_m_s,.5*(w1+w2));
        out.gravity_work_j+=gravity_work;out.gyro_kick_j+=kg-k0;out.other_force_work_j+=k1-kg-gravity_work;
        out.spring_work_j+=spring;out.contact_work_j+=contact;out.solver_residual_work_j+=k2-k1-spring-contact;
        out.velocity_limit_work_j+=kl-k2;out.rotation_drift_j+=rotated-kl;out.post_integration_work_j+=actual-rotated;out.kinetic_change_j+=actual-k0;
        out.velocity_limit_impulse_n_s+=a.mass_kg*(vl-v2);out.velocity_limit_couple_n_m_s+=a.inertia_world_kg_m2*(wl-w2);
        out.potential_change_j-=a.mass_kg*dot(gravity,b.motion.center_of_mass_world_m-a.motion.center_of_mass_world_m);
        out.solver_linear_residual_n_s+=a.mass_kg*(v2-v1)-s.spring_impulse_n_s-s.contact_impulse_n_s;
        out.solver_angular_residual_n_m_s+=a.inertia_world_kg_m2*(w2-w1)-s.spring_couple_n_m_s-s.contact_couple_n_m_s;
        out.angular_drift_n_m_s+=(b.inertia_world_kg_m2*wf-a.inertia_world_kg_m2*wf)
            +cross(b.motion.center_of_mass_world_m-a.motion.center_of_mass_world_m,a.mass_kg*vf);
    }
    out.energy_residual_j=out.kinetic_change_j-out.gravity_work_j-out.gyro_kick_j-out.other_force_work_j-out.spring_work_j-out.contact_work_j-out.solver_residual_work_j-out.velocity_limit_work_j-out.rotation_drift_j-out.post_integration_work_j;
    for(double x:{out.gravity_work_j,out.gyro_kick_j,out.other_force_work_j,out.spring_work_j,out.contact_work_j,out.solver_residual_work_j,out.velocity_limit_work_j,out.post_integration_work_j,out.rotation_drift_j,out.potential_change_j,out.kinetic_change_j,out.energy_residual_j})
        if(!std::isfinite(x))throw std::invalid_argument("rigid work audit overflow");
    return out;
}
ContactFrictionStationarity auditContactFrictionStationarity(Vec3 impulse,Vec3 slip,double cap,
    double twist,double spin,double twist_cap){
    if(!finite(impulse)||!finite(slip)||!std::isfinite(cap)||cap<0||!std::isfinite(twist)
        ||!std::isfinite(spin)||!std::isfinite(twist_cap)||twist_cap<0)
        throw std::invalid_argument("invalid contact friction stationarity domain");
    ContactFrictionStationarity out;
    out.friction_work_j=dot(impulse,slip);out.twist_work_j=twist*spin;
    out.friction_gap_j=out.friction_work_j+cap*length(slip);
    out.twist_gap_j=out.twist_work_j+twist_cap*std::abs(spin);
    out.friction_cap_excess_n_s=std::max(0.,length(impulse)-cap);
    out.twist_cap_excess_n_m_s=std::max(0.,std::abs(twist)-twist_cap);
    for(double x:{out.friction_work_j,out.twist_work_j,out.friction_gap_j,out.twist_gap_j,
        out.friction_cap_excess_n_s,out.twist_cap_excess_n_m_s})
        if(!std::isfinite(x))throw std::invalid_argument("contact friction stationarity overflow");
    return out;
}
}
