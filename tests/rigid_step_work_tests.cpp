#include "physics/RigidStepWork.hpp"
#include <iostream>
#include <stdexcept>
using namespace banjo;
namespace {
void check(bool v,const char *message){if(!v)throw std::runtime_error(message);}
Mat3 diagonal(Vec3 d){Mat3 m;m.m[0][0]=d.x;m.m[1][1]=d.y;m.m[2][2]=d.z;return m;}
RigidStepWorkInput base(){RigidStepWorkInput s;s.before={{{0,1,0},{},{1,2,3},{1,2,3}},2,diagonal({3,4,5})};
    s.after=s.before;s.spin_after_gyro_rad_s=s.spin_after_forces_rad_s=s.before.motion.angular_velocity_rad_s;s.velocity_after_forces_m_s=s.before.motion.linear_velocity_m_s;return s;}
void mixed_impulses(){auto s=base();s.gravity_impulse_n_s={0,-.4,0};s.spring_impulse_n_s={.3,.1,-.2};s.contact_impulse_n_s={-.1,.2,.4};
    s.spring_couple_n_m_s={.2,-.3,.1};s.contact_couple_n_m_s={.1,.4,-.2};s.velocity_after_forces_m_s+=s.gravity_impulse_n_s/2;
    s.after.motion.linear_velocity_m_s=s.velocity_after_forces_m_s+(s.spring_impulse_n_s+s.contact_impulse_n_s)/2;
    s.after.motion.angular_velocity_rad_s+=*s.before.inertia_world_kg_m2.inverse()*(s.spring_couple_n_m_s+s.contact_couple_n_m_s);
    s.after.motion.center_of_mass_world_m+=.02*s.after.motion.linear_velocity_m_s;
    const auto a=auditRigidStepWork({&s,1},{0,-10,0});
    check(length(a.solver_linear_residual_n_s)<1e-14&&length(a.solver_angular_residual_n_m_s)<1e-14,"mixed source impulses account actual kicks");
    check(std::abs(a.solver_residual_work_j)<1e-13&&std::abs(a.energy_residual_j)<1e-13,"common-phase mixed work closes kinetic change");
    const double expected_gravity=dot(s.gravity_impulse_n_s,.5*(s.before.motion.linear_velocity_m_s+s.velocity_after_forces_m_s));
    check(std::abs(a.gravity_work_j-expected_gravity)<1e-14,"measured gravity work uses actual force midpoint");
    // Deliberately omit a known source: the audit must expose it as a residual.
    s.contact_impulse_n_s={};const auto missing=auditRigidStepWork({&s,1},{0,-10,0});
    check(length(missing.solver_linear_residual_n_s)>.4&&std::abs(missing.solver_residual_work_j)>.1,"omitted impulse is not hidden by algebraic closure");
}
void gravity_loss(){auto s=base();s.before.motion.angular_velocity_rad_s={};s.after=s.before;s.spin_after_gyro_rad_s=s.spin_after_forces_rad_s={};
    s.gravity_impulse_n_s={0,-.4,0};s.velocity_after_forces_m_s=s.before.motion.linear_velocity_m_s+s.gravity_impulse_n_s/2;
    s.after.motion.linear_velocity_m_s=s.velocity_after_forces_m_s;s.after.motion.center_of_mass_world_m+=.02*s.after.motion.linear_velocity_m_s;
    const auto a=auditRigidStepWork({&s,1},{0,-10,0});
    check(std::abs(a.gravity_work_j+a.potential_change_j+.04)<1e-13,"semi-implicit freefall numerical loss is measured, not heat");
}
void gyro_and_drift(){auto s=base();s.before.motion.angular_velocity_rad_s={1,0,0};s.after=s.before;
    s.spin_after_gyro_rad_s=s.spin_after_forces_rad_s={1.01,0,0};s.after.motion.angular_velocity_rad_s={1.01,0,0};
    s.after.inertia_world_kg_m2=diagonal({4,3,5});const auto a=auditRigidStepWork({&s,1},{});
    check(std::abs(a.gyro_kick_j-.5*3*(1.01*1.01-1))<1e-14,"gyro energy change retained independently");
    check(std::abs(a.rotation_drift_j-.5*1.01*1.01)<1e-14,"actual rotated inertia drift is measured");
    check(std::abs(a.other_force_work_j)<1e-14&&std::abs(a.energy_residual_j)<1e-14,"no loss invented to cancel gyro/drift");
}
void velocity_limits(){auto s=base();s.integration_observed=true;
    s.velocity_after_solver_m_s=s.velocity_after_forces_m_s;s.spin_after_solver_rad_s=s.spin_after_forces_rad_s;
    s.velocity_after_limit_m_s=.5*s.velocity_after_solver_m_s;s.spin_after_limit_rad_s=.5*s.spin_after_solver_rad_s;
    s.after.motion.linear_velocity_m_s=s.velocity_after_limit_m_s;s.after.motion.angular_velocity_rad_s=s.spin_after_limit_rad_s;
    const auto a=auditRigidStepWork({&s,1},{});
    const double expected=-.75*(.5*2*14+.5*(3+16+45));
    check(std::abs(a.velocity_limit_work_j-expected)<1e-13,"actual speed cap loss is distinct from contact and solver work");
    check(std::abs(a.solver_residual_work_j)<1e-13&&std::abs(a.energy_residual_j)<1e-13,"speed cap does not masquerade as unexplained solver work");
    check(length(a.velocity_limit_couple_n_m_s-Vec3{-1.5,-4,-7.5})<1e-13,"actual angular limit impulse measured");
    s.after.motion.linear_velocity_m_s={};s.after.motion.angular_velocity_rad_s={};const auto stopped=auditRigidStepWork({&s,1},{});
    check(stopped.post_integration_work_j<0&&std::abs(stopped.energy_residual_j)<1e-13,"later velocity clearing is separate from the speed cap");
}
}
int main(){try{mixed_impulses();gravity_loss();gyro_and_drift();velocity_limits();auto s=base();s.after.mass_kg=3;
    bool refused=false;try{(void)auditRigidStepWork({&s,1},{});}catch(const std::invalid_argument &){refused=true;}check(refused,"changed mass refuses");
    s=base();s.before.inertia_world_kg_m2.m[0][0]=-1;refused=false;try{(void)auditRigidStepWork({&s,1},{});}catch(const std::invalid_argument &){refused=true;}check(refused,"invalid inertia refuses");
    std::cout<<"PASS mixed impulses, omitted-source residual, freefall loss, gyro/drift and two refusals\n";return 0;
}catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}}
