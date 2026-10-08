#include "physics/ForceContactPhase.hpp"
#include <cmath>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <vector>

namespace {
using namespace banjo;
void require(bool ok,const char *why){if(!ok)throw std::runtime_error(why);}
void near(double value,double expected,double bound,const char *why){require(std::isfinite(value)&&std::abs(value-expected)<=bound,why);}
template<class F>void rejects(F f){bool caught=false;try{f();}catch(const std::invalid_argument&){caught=true;}require(caught,"malformed phase was admitted");}
RigidMechanicalState body(double mass,double inertia,Vec3 position,Vec3 velocity,Vec3 spin={}) {
    RigidMechanicalState b;b.mass_kg=mass;for(unsigned i=0;i<3;++i)b.inertia_world_kg_m2.m[i][i]=inertia;
    b.motion.center_of_mass_world_m=position;b.motion.linear_velocity_m_s=velocity;b.motion.angular_velocity_rad_s=spin;return b;
}
void closure(const ForceContactPhaseAudit &a){near(a.energy_residual_j,0,1e-12,"combined phase energy identity");
    near(a.cross_work_residual_j,0,1e-12,"opposing force/contact cross terms");
    near(length(a.momentum_residual_n_s),0,1e-12,"combined phase impulse identity");
    near(length(a.angular_residual_kg_m2_s),0,1e-12,"combined phase torque identity");
    near(a.simultaneous_force_work_j-a.sequential_force_work_j,a.force_cross_work_j,1e-12,"force cross-work attribution");
    near(a.simultaneous_contact_work_j-a.sequential_contact_work_j,a.contact_cross_work_j,1e-12,"contact cross-work attribution");}
ForceContactPhaseAudit constrainedMasses(double h,Vec3 boost={}) {
    // Independent exact ideal contact oracle: 2 kg and 3 kg start together at
    // 4 m/s, with a -20 N force on the 2 kg mass for h seconds. The connected
    // acceleration is -4 m/s². An ideal normal constraint does no work.
    const auto v0=Vec3{4,0,0}+boost,free=v0+Vec3{-10*h,0,0},end=v0+Vec3{-4*h,0,0};
    ActiveNodeState p{{1,0,0},{1,0,0},v0,2,{}};
    ForceContactPointStates point{p,p,p};point.after_forces.velocity_m_s=free;point.after_contact.velocity_m_s=end;
    const auto s=body(3,1,{},v0);ForceContactRigidStates rigid{s,s,s};rigid.after_contact.motion.linear_velocity_m_s=end;
    const auto audit=auditForceContactPhase(std::span(&point,1),std::span(&rigid,1));closure(audit);
    near(audit.simultaneous_contact_work_j,0,1e-12,"ideal maintained normal contact did work");
    near(audit.sequential_contact_work_j,-60*h*h,1e-12,"sequential projection loss oracle");
    near(audit.contact_cross_work_j,60*h*h,1e-12,"numerical projection cross term");
    near(audit.kinetic_change_j,-20*h*(v0.x-2*h),1e-12,"combined mass exact forcing work");
    near(length(audit.contact_impulse_n_s),0,1e-12,"paired contact reaction");return audit;
}
void translationOracles(){for(double h:{1e-3,5e-4,1e-4}){const auto a=constrainedMasses(h),b=constrainedMasses(h,{7,-2,3});
    near(b.simultaneous_contact_work_j,a.simultaneous_contact_work_j,1e-12,"Galilean ideal contact work");
    near(b.force_cross_work_j,a.force_cross_work_j,1e-12,"Galilean cross work");
    near(b.simultaneous_force_work_j-a.simultaneous_force_work_j,dot(Vec3{7,-2,3},a.force_impulse_n_s),1e-12,"Galilean external work");}
    const auto a=constrainedMasses(1e-3),b=constrainedMasses(5e-4);
    near(a.sequential_contact_work_j,4*b.sequential_contact_work_j,1e-12,"projection loss must scale quadratically");}
void rotationalOracle(){const double h=1e-3;const auto a=body(2,2,{}, {},{5,0,0}),b=body(3,3,{}, {},{5,0,0});
    ForceContactRigidStates rotorA{a,a,a},rotorB{b,b,b};rotorB.after_forces.motion.angular_velocity_rad_s={5-2*h,0,0};
    rotorA.after_contact.motion.angular_velocity_rad_s=rotorB.after_contact.motion.angular_velocity_rad_s={5-1.2*h,0,0};
    const ForceContactRigidStates states[]{rotorA,rotorB};const auto audit=auditForceContactPhase({},states);closure(audit);
    near(audit.simultaneous_contact_work_j,0,1e-12,"ideal coupled rotational constraint work");
    near(audit.sequential_contact_work_j,-2.4*h*h,1e-12,"rotational sequential loss");
    near(audit.simultaneous_force_work_j,-6*h*(5-.6*h),1e-12,"rotational torque work");
    near(length(audit.contact_angular_impulse_kg_m2_s),0,1e-12,"rotational contact torque pair");}
void impactOracle(){ActiveNodeState a{{},{},{-3,0,0},2,{}},b=a;b.velocity_m_s={1,0,0};
    const ForceContactPointStates states{a,a,b};const auto audit=auditForceContactPhase(std::span(&states,1),{});closure(audit);
    near(audit.sequential_contact_work_j,-8,0,"unforced dissipative impact work");
    near(audit.simultaneous_contact_work_j,-8,0,"unforced impact must retain loss");near(audit.contact_cross_work_j,0,0,"no force cross term at impact");}
void refusalOracles(){ActiveNodeState p{{1,2,3},{1,2,3},{4,5,6},2,{}};const ForceContactPointStates good{p,p,p};
    auto bad=good;bad.after_contact.mass_kg=3;rejects([&]{(void)auditForceContactPhase(std::span(&bad,1),{});});
    bad=good;bad.after_forces.position_world_m.x+=.1;rejects([&]{(void)auditForceContactPhase(std::span(&bad,1),{});});
    bad=good;bad.before_forces.spin_angular_velocity_rad_s.x=1;rejects([&]{(void)auditForceContactPhase(std::span(&bad,1),{});});
    bad=good;bad.after_contact.velocity_m_s.x=std::numeric_limits<double>::infinity();rejects([&]{(void)auditForceContactPhase(std::span(&bad,1),{});});
    const ForceContactPointStates late[]{good,bad};rejects([&]{(void)auditForceContactPhase(late,{});});
    require(good.before_forces.velocity_m_s.x==4&&good.after_contact.mass_kg==2,"pure refusal mutated inputs");
    const auto b=body(2,1,{},{});const ForceContactRigidStates rg{b,b,b};auto rb=rg;rb.after_contact.inertia_world_kg_m2.m[0][0]=2;
    rejects([&]{(void)auditForceContactPhase({},std::span(&rb,1));});rb=rg;rb.after_forces.motion.orientation_world.x=.1;
    rejects([&]{(void)auditForceContactPhase({},std::span(&rb,1));});
    rb=rg;rb.before_forces.mass_kg=rb.after_forces.mass_kg=rb.after_contact.mass_kg=-2;
    rejects([&]{(void)auditForceContactPhase({},std::span(&rb,1));});
    rb=rg;rb.before_forces.inertia_world_kg_m2.m[0][0]=rb.after_forces.inertia_world_kg_m2.m[0][0]=rb.after_contact.inertia_world_kg_m2.m[0][0]=-1;
    rejects([&]{(void)auditForceContactPhase({},std::span(&rb,1));});
    std::vector<ForceContactPointStates> large(1025,good);rejects([&]{(void)auditForceContactPhase(large,{});});
    std::vector<ForceContactRigidStates> bodies(257,rg);rejects([&]{(void)auditForceContactPhase({},bodies);});
    rejects([&]{(void)auditForceContactPhase({},{});});}
}
int main(){try{translationOracles();rotationalOracle();impactOracle();refusalOracles();
    std::cout<<"[PASS] force/contact phase analytical work, rotation, impact, frame and admission oracles\n";return 0;
}catch(const std::exception &e){std::cerr<<"[FAIL] "<<e.what()<<'\n';return 1;}}
