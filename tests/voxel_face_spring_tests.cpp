#include "rigid/JoltWorld.hpp"
#include "material/MaterialCatalog.hpp"
#include "physics/RotationStrain.hpp"
#include <cmath>
#include <iostream>
#include <stdexcept>
using namespace banjo;
namespace {
RigidJobExecution execution=RigidJobExecution::ThreadPool;
bool log_gradient=false;
void check(bool value,const char *why){if(!value)throw std::runtime_error(why);}
double axis(Vec3 a,Vec3 b){return dot(a,b);}
void oracle(double damping,double initial_extension){
    JoltWorld world(0,{},execution);world.setGravity({});world.setContactSolverIterations(96,4);
    auto material=makeReferenceMaterial(MaterialPreset::Iron);material.model=MaterialModel::RigidOnly;
    world.addBox({1,{.1,.1,.1},material,{{-.06,0,0},{},{-.1,0,0},{}},false});
    world.addBox({2,{.1,.1,.1},material,{{ .06,0,0},{},{ .1,0,0},{}},false});
    world.setPairContactOwner(1,2,PairContactOwner::External);
    const double stiffness=1000,h=1./240;
    const auto joint=world.addFaceSpring({1,2,{},{1,0,0},{0,1,0},{stiffness,stiffness,stiffness},{10,10,10},{damping,damping,damping},{0,0,0},log_gradient});
    if(initial_extension){
        auto a=world.snapshot(1),b=world.snapshot(2);
        a.center_of_mass_world_m.x-=initial_extension/2;
        b.center_of_mass_world_m.x+=initial_extension/2;
        world.applyRigidState(1,a);world.applyRigidState(2,b);
    }
    const auto before=world.mechanicalTotals();const auto a0=world.mechanicalState(1),b0=world.mechanicalState(2);
    const auto face0=world.faceSpringObservation(joint);
    world.step(h);
    const auto a=world.mechanicalState(1),b=world.mechanicalState(2);const auto after=world.mechanicalTotals();const auto face=world.faceSpringObservation(joint);
    const double speed=axis(b.motion.linear_velocity_m_s-a.motion.linear_velocity_m_s,face0.translation_axes_world[0]);
    const double reduced=1/(1/a.mass_kg+1/b.mass_kg);
    const double expected=(.2-h*stiffness*face0.displacement_cs_m.x/reduced)/(1+h*damping/reduced+h*h*stiffness/reduced);
    check(std::abs(speed-expected)<2e-7,"implicit spring endpoint speed oracle");
    check(std::abs(face.displacement_cs_m.x-face0.displacement_cs_m.x-h*speed)<2e-8,"native anchor drift oracle");
    check(std::abs(face.linear_impulse_cs_n_s.x+h*(stiffness*face.displacement_cs_m.x+damping*speed))<2e-7,"spring constitutive impulse oracle");
    const double physical=h*damping*speed*speed,numerical_elastic=.5*stiffness*h*h*speed*speed;
    const double numerical_velocity=.5*a.mass_kg*lengthSquared(a.motion.linear_velocity_m_s-a0.motion.linear_velocity_m_s)+.5*b.mass_kg*lengthSquared(b.motion.linear_velocity_m_s-b0.motion.linear_velocity_m_s);
    const double elastic=.5*stiffness*lengthSquared(face.displacement_cs_m);
    const double residual=after.kinetic_energy_j+elastic+physical+numerical_elastic+numerical_velocity-before.kinetic_energy_j-.5*stiffness*lengthSquared(face0.displacement_cs_m);
    check(std::abs(residual)<2e-8,"physical and backward-Euler losses close analytical energy ledger");
    check(length(after.linear_momentum_kg_m_s-before.linear_momentum_kg_m_s)<1e-7,"spring pair total momentum");
    check(length(after.angular_momentum_kg_m2_s-before.angular_momentum_kg_m2_s)<1e-7,"spring pair total angular momentum");
    check(!world.runReversibleTrial([&]{world.step(h);return false;}),"trial refuses");
    const auto restored=world.faceSpringObservation(joint);
    check(restored.displacement_cs_m.x==face.displacement_cs_m.x&&restored.linear_impulse_cs_n_s.x==face.linear_impulse_cs_n_s.x,"face spring rollback restores observation");
    std::cout<<"extension="<<initial_extension<<" damping="<<damping<<" physical_j="<<physical<<" numerical_elastic_j="<<numerical_elastic<<" numerical_velocity_j="<<numerical_velocity<<" residual_j="<<residual<<'\n';
}
void torsion(double damping){
    JoltWorld world(0,{},execution);world.setGravity({});world.setContactSolverIterations(96,4);
    auto material=makeReferenceMaterial(MaterialPreset::Iron);material.model=MaterialModel::RigidOnly;
    world.addBox({1,{.1,.1,.1},material,{{-.06,0,0},{},{},{-.1,0,0}},false});
    world.addBox({2,{.1,.1,.1},material,{{ .06,0,0},{},{},{ .1,0,0}},false});
    world.setPairContactOwner(1,2,PairContactOwner::External);
    const double k=10,h=1./240;
    const auto joint=world.addFaceSpring({1,2,{},{1,0,0},{0,1,0},{1000,1000,1000},{k,k,k},{0,0,0},{damping,damping,damping},log_gradient});
    const auto before=world.mechanicalTotals();const auto a0=world.mechanicalState(1),b0=world.mechanicalState(2);
    world.step(h);
    const auto a=world.mechanicalState(1),b=world.mechanicalState(2);const auto face=world.faceSpringObservation(joint);
    const auto after=world.mechanicalTotals();
    const double speed=b.motion.angular_velocity_rad_s.x-a.motion.angular_velocity_rad_s.x;
    const double reduced=1/(1/a0.inertia_world_kg_m2.m[0][0]+1/b0.inertia_world_kg_m2.m[0][0]);
    const double expected=.2/(1+h*damping/reduced+h*h*k/reduced);
    check(std::abs(speed-expected)<2e-7,"implicit torsion endpoint speed oracle");
    check(std::abs(face.rotation_cs_rad.x-h*speed)<2e-8,"native angular drift oracle");
    check(std::abs(face.angular_impulse_cs_n_m_s.x+h*(k*h*speed+damping*speed))<2e-8,"torsion constitutive impulse oracle");
    const double physical=h*damping*speed*speed,numerical_elastic=.5*k*h*h*speed*speed;
    const double numerical_velocity=.5*a0.inertia_world_kg_m2.m[0][0]*lengthSquared(a.motion.angular_velocity_rad_s-a0.motion.angular_velocity_rad_s)+.5*b0.inertia_world_kg_m2.m[0][0]*lengthSquared(b.motion.angular_velocity_rad_s-b0.motion.angular_velocity_rad_s);
    const double residual=after.kinetic_energy_j+.5*k*lengthSquared(face.rotation_cs_rad)+physical+numerical_elastic+numerical_velocity-before.kinetic_energy_j;
    check(std::abs(residual)<2e-9,"small-angle torsion energy ledger");
    check(length(after.angular_momentum_kg_m2_s-before.angular_momentum_kg_m2_s)<1e-7,"torsion angular momentum");
    std::cout<<"torsion damping="<<damping<<" residual_j="<<residual<<'\n';
}
void nearest_orientation(){
    JoltWorld world(0,{},execution);world.setGravity({});
    auto material=makeReferenceMaterial(MaterialPreset::Iron);material.model=MaterialModel::RigidOnly;
    world.addBox({1,{.1,.1,.1},material,{{-.06,0,0},{},{},{}},false});
    world.addBox({2,{.1,.1,.1},material,{{ .06,0,0},{},{},{}},false});
    const auto joint=world.addFaceSpring({1,2,{},{1,0,0},{0,1,0},{1000,1000,1000},{10,10,10},{0,0,0},{0,0,0}});
    auto pose=world.snapshot(2);pose.orientation_world={0,1,0,0};world.applyRigidState(2,pose);
    const auto face=world.faceSpringObservation(joint);
    check(std::abs(face.rotation_cs_rad.x-std::acos(-1.))<1e-7,"physical pi rotation");
    check(face.rotation_error_cs_rad.x==-2,"native orientation tie chooses negative identity target");
}
void contact_oracle(bool fixed,double friction){
    JoltWorld world(0,{},execution);world.setGravity({});world.configureVoxelContacts(.004);
    world.setContactSolverIterations(96,4);world.setContactImpulseObservationsEnabled(true);
    auto material=makeReferenceMaterial(MaterialPreset::Iron);material.model=MaterialModel::RigidOnly;
    material.static_friction=material.dynamic_friction=material.friction=friction;
    material.restitution=0;material.derive_restitution_from_damping=false;material.rolling_resistance=0;
    // Combined-contact restitution is derived from this damping declaration.
    material.contact_damping_ratio=.999999;
    world.addBox({1,{.1,.1,.1},material,{{-.05,0,0},{},fixed?Vec3{}:Vec3{1,.3,0},{}},fixed});
    world.addBox({2,{.1,.1,.1},material,{{ .05,0,0},{},{-1,-.3,0},{}},false});
    if(!fixed)world.setContinuousCollision(1,false);world.setContinuousCollision(2,false);
    const auto a0=world.mechanicalState(1),b0=world.mechanicalState(2);
    world.step(1./960);
    const auto a=world.mechanicalState(1),b=world.mechanicalState(2);
    Vec3 impulse{},angular_a{},angular_b{};double work=0;
    const auto observations=world.contactImpulseObservations();check(!observations.empty(),"actual contact observation missing");
    for(const auto &contact:observations){
        check(contact.a==1&&contact.b==2,"native contact body order");
        const auto pair=[&](Vec3 point,Vec3 push){
            impulse+=push;const auto ra=point-a0.motion.center_of_mass_world_m,rb=point-b0.motion.center_of_mass_world_m;
            angular_a-=cross(ra,push);angular_b+=cross(rb,push);
            const auto speed=b.motion.linear_velocity_m_s+cross(b.motion.angular_velocity_rad_s,rb)-a.motion.linear_velocity_m_s-cross(a.motion.angular_velocity_rad_s,ra);
            work+=dot(push,speed);
        };
        for(const auto &point:contact.points)pair(point.point_world_m,contact.normal_a_to_b*point.normal_impulse_n_s);
        pair(contact.friction_point_world_m,contact.friction_impulse_on_b_n_s);
        angular_a-=contact.twist_impulse_on_b_n_m_s;angular_b+=contact.twist_impulse_on_b_n_m_s;
        work+=dot(contact.twist_impulse_on_b_n_m_s,b.motion.angular_velocity_rad_s-a.motion.angular_velocity_rad_s);
    }
    check(length(b.mass_kg*(b.motion.linear_velocity_m_s-b0.motion.linear_velocity_m_s)-impulse)<2e-6,"actual contact impulse changes B momentum");
    if(friction==0)check(std::abs(impulse.x-b.mass_kg)<2e-6,"equal-mass or anchored inelastic normal impulse oracle");
    check(length(b0.inertia_world_kg_m2*(b.motion.angular_velocity_rad_s-b0.motion.angular_velocity_rad_s)-angular_b)<2e-6,"actual contact lever arm changes B spin");
    if(!fixed){
        check(length(a.mass_kg*(a.motion.linear_velocity_m_s-a0.motion.linear_velocity_m_s)+impulse)<2e-6,"actual contact reaction changes A momentum");
        check(length(a0.inertia_world_kg_m2*(a.motion.angular_velocity_rad_s-a0.motion.angular_velocity_rad_s)-angular_a)<2e-6,"actual contact reaction lever arm changes A spin");
    }
    const auto kinetic=[](const RigidMechanicalState &state,const Mat3 &inertia){return .5*state.mass_kg*lengthSquared(state.motion.linear_velocity_m_s)+.5*dot(state.motion.angular_velocity_rad_s,inertia*state.motion.angular_velocity_rad_s);};
    const double quadratic_velocity=.5*a.mass_kg*lengthSquared(a.motion.linear_velocity_m_s-a0.motion.linear_velocity_m_s)+.5*b.mass_kg*lengthSquared(b.motion.linear_velocity_m_s-b0.motion.linear_velocity_m_s)
        +.5*dot(a.motion.angular_velocity_rad_s-a0.motion.angular_velocity_rad_s,a0.inertia_world_kg_m2*(a.motion.angular_velocity_rad_s-a0.motion.angular_velocity_rad_s))
        +.5*dot(b.motion.angular_velocity_rad_s-b0.motion.angular_velocity_rad_s,b0.inertia_world_kg_m2*(b.motion.angular_velocity_rad_s-b0.motion.angular_velocity_rad_s));
    const double residual=kinetic(a,a0.inertia_world_kg_m2)+kinetic(b,b0.inertia_world_kg_m2)-kinetic(a0,a0.inertia_world_kg_m2)-kinetic(b0,b0.inertia_world_kg_m2)-work+quadratic_velocity;
    check(std::abs(residual)<3e-6,"contact endpoint work plus velocity quadratic closes fixed-frame energy ledger");
    const Vec3 saved_impulse=impulse;const auto saved_count=observations.size();
    check(!world.runReversibleTrial([&]{world.step(1./960);return false;}),"contact trial refuses");
    Vec3 restored{};for(const auto &contact:world.contactImpulseObservations()){
        for(const auto &point:contact.points)restored+=contact.normal_a_to_b*point.normal_impulse_n_s;
        restored+=contact.friction_impulse_on_b_n_s;
    }
    check(world.contactImpulseObservations().size()==saved_count&&length(restored-saved_impulse)==0,"contact audit rollback restores last accepted impulses");
    world.setContinuousCollision(2,true);bool swept_refused=false;
    try{world.runReversibleTrial([&]{world.step(1./960);return true;});}catch(const std::runtime_error &error){swept_refused=std::string(error.what()).find("discrete contacts only")!=std::string::npos;}
    check(swept_refused,"unqualified CCD impulse auditing refuses explicitly");
    check(world.snapshot(2).center_of_mass_world_m.x==b.motion.center_of_mass_world_m.x,"CCD audit refusal restores native position");
    check(world.contactImpulseObservations().size()==saved_count,"CCD audit refusal restores observation");
    world.setContinuousCollision(2,false);
    if(!fixed)world.sleep(1);world.sleep(2);world.step(1./960);
    check(world.contactImpulseObservations().empty(),"dormant cached contact lambdas are not counted again");
    auto away=world.snapshot(2);away.center_of_mass_world_m.x=2;world.applyRigidState(2,away);world.step(1./960);
    check(world.contactImpulseObservations().empty(),"inactive cache impulses are not reported as new contact");
    std::cout<<"contact fixed="<<fixed<<" friction="<<friction<<" residual_j="<<residual<<" impulse_n_s="<<length(impulse)<<'\n';
}
void gravity_oracle(){
    JoltWorld world(0,{},execution);world.setGravity({0,-9.81,0});world.setContactImpulseObservationsEnabled(true);
    world.setForcePhaseObservationsEnabled(true);
    auto material=makeReferenceMaterial(MaterialPreset::Iron);material.model=MaterialModel::RigidOnly;
    world.addBox({1,{.1,.1,.1},material,{{0,10,0},{},{},{}},false});world.setContinuousCollision(1,false);
    const auto before=world.mechanicalState(1);world.step(1./960);const auto after=world.mechanicalState(1);
    const auto impulse=world.observedGravityImpulseN_s();
    const auto phase=world.forcePhaseObservations().front();check(phase.body==1&&phase.force_scheduled,"actual native force stage is observed");
    check(length(phase.before.motion.linear_velocity_m_s-before.motion.linear_velocity_m_s)==0,"native observer retains actual initial velocity");
    check(length(phase.velocity_after_forces_m_s-after.motion.linear_velocity_m_s)==0,"native observer sees actual final force velocity before constraints");
    check(length(phase.gravity_impulse_n_s-impulse)==0,"native observed force schedule equals gravity audit");
    check(phase.integration_scheduled&&length(phase.velocity_after_solver_m_s-after.motion.linear_velocity_m_s)==0,"actual native integration stage observed");
    check(length(impulse-after.mass_kg*(after.motion.linear_velocity_m_s-before.motion.linear_velocity_m_s))<1e-10,"native gravity scheduled impulse matches freefall momentum");
    check(!world.runReversibleTrial([&]{world.step(1./480);return false;}),"gravity audit trial refuses");
    check(length(world.observedGravityImpulseN_s()-impulse)==0,"gravity audit rolls back exactly");
    check(length(world.forcePhaseObservations().front().velocity_after_forces_m_s-phase.velocity_after_forces_m_s)==0,"actual force stage rolls back exactly");
    world.sleep(1);world.step(1./960);
    check(length(world.observedGravityImpulseN_s())==0,"sleeping body receives no scheduled gravity impulse");
    check(!world.forcePhaseObservations().front().force_scheduled,"sleeping cached force stage is not reported again");
    check(!world.forcePhaseObservations().front().integration_scheduled,"sleeping integration stage is not counted again");
    std::cout<<"gravity active impulse_n_s="<<length(impulse)<<" sleeping impulse_n_s=0\n";
}
void log_gradient_impulse_oracle(){
    JoltWorld world(0,{},execution);world.setGravity({});world.setContactSolverIterations(96,4);
    auto material=makeReferenceMaterial(MaterialPreset::Iron);material.model=MaterialModel::RigidOnly;
    world.addBox({1,{.1,.1,.1},material,{{},{},{},{}},false});
    world.addBox({2,{.1,.1,.1},material,{{},{},{},{}},false});world.setPairContactOwner(1,2,PairContactOwner::External);
    const Vec3 k{2,7,13},phi{.4,.9,-.3};const double angle=length(phi),scale=std::sin(angle/2)/angle;
    const auto joint=world.addFaceSpring({1,2,{},{1,0,0},{0,1,0},{1000,1000,1000},k,{},{},true});
    auto state=world.snapshot(2);state.orientation_world={std::cos(angle/2),phi.x*scale,phi.y*scale,phi.z*scale};world.applyRigidState(2,state);
    const auto a0=world.mechanicalState(1),b0=world.mechanicalState(2);const auto frame=world.faceSpringObservation(joint);
    const Vec3 gradient=frame.rotation_axes_world[0]*(k.x*phi.x)+frame.rotation_axes_world[1]*(k.y*phi.y)+frame.rotation_axes_world[2]*(k.z*phi.z);
    const double h=1e-6;world.step(h);const auto a=world.mechanicalState(1),b=world.mechanicalState(2);const auto response=world.faceSpringObservation(joint);
    const auto impulse_b=b0.inertia_world_kg_m2*(b.motion.angular_velocity_rad_s-b0.motion.angular_velocity_rad_s);
    const auto impulse_a=a0.inertia_world_kg_m2*(a.motion.angular_velocity_rad_s-a0.motion.angular_velocity_rad_s);
    check(length(impulse_b/h+gradient)<4e-5,"finite-angle native torque follows anisotropic energy gradient");
    check(length(impulse_a+impulse_b)<1e-10,"finite-angle native equal opposite torque");
    const auto saved=world.snapshot(2);check(!world.runReversibleTrial([&]{world.step(h);return false;}),"log gradient trial refuses");
    const auto restored=world.faceSpringObservation(joint);
    check(length(restored.angular_impulse_cs_n_m_s-response.angular_impulse_cs_n_m_s)==0,"log generalized impulse rollback");
    check(world.snapshot(2).orientation_world.w==saved.orientation_world.w,"log frame rollback");
    std::cout<<"log finite-angle torque residual_nm="<<length(impulse_b/h+gradient)<<" reaction_residual_nms="<<length(impulse_a+impulse_b)<<'\n';
}
void limit_observation_oracle(){
    JoltWorld world(0,{},execution);world.setGravity({});world.setForcePhaseObservationsEnabled(true);
    auto material=makeReferenceMaterial(MaterialPreset::Iron);material.model=MaterialModel::RigidOnly;
    for(unsigned id:{1u,2u})world.addBox({id,{.1,.1,.1},material,{{},{},{},{}},false});
    world.setPairContactOwner(1,2,PairContactOwner::External);
    world.addFaceSpring({1,2,{},{1,0,0},{0,1,0},{1000,1000,1000},{1e8,1e8,1e8},{},{},false});
    auto state=world.snapshot(2);state.orientation_world={std::cos(.5),std::sin(.5),0,0};world.applyRigidState(2,state);
    world.step(1e-5);bool capped=false;
    for(const auto &p:world.forcePhaseObservations()){
        check(p.integration_scheduled,"native cap observation scheduled");
        check(length(p.spin_after_limit_rad_s)<=1000.001,"native cap bound retained");
        capped|=length(p.spin_after_solver_rad_s)>length(p.spin_after_limit_rad_s)+1;
    }
    check(capped,"oracle must exercise a real native angular speed cap");
    const auto saved=world.forcePhaseObservations().front();
    check(!world.runReversibleTrial([&]{world.step(1e-5);return false;}),"native cap trial refuses");
    check(length(world.forcePhaseObservations().front().spin_after_solver_rad_s-saved.spin_after_solver_rad_s)==0,"actual pre-limit velocities roll back");
    std::cout<<"native angular cap observed and restored\n";
}
}
int main(){try{for(auto policy:{RigidJobExecution::ThreadPool,RigidJobExecution::Inline}){execution=policy;std::cout<<"execution="<<(policy==RigidJobExecution::Inline?"inline":"thread-pool")<<'\n';for(bool law:{false,true}){log_gradient=law;for(double extension:{0.,.01}){oracle(0,extension);oracle(20,extension);}torsion(0);torsion(.005);}nearest_orientation();for(bool fixed:{false,true})for(double friction:{0.,.4})contact_oracle(fixed,friction);gravity_oracle();log_gradient_impulse_oracle();limit_observation_oracle();}return 0;}catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}}
