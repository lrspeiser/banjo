#include "rigid/JoltWorld.hpp"
#include "material/MaterialCatalog.hpp"
#include "material/MaterialCompiler.hpp"
#include "physics/RotationStrain.hpp"
#include "physics/RigidStepWork.hpp"
#include <cmath>
#include <iostream>
#include <limits>
#include <stdexcept>
using namespace banjo;
namespace {
RigidJobExecution execution=RigidJobExecution::ThreadPool;
bool log_gradient=false;
void check(bool value,const char *why){if(!value)throw std::runtime_error(why);}
double axis(Vec3 a,Vec3 b){return dot(a,b);}
void execution_profile_oracle(){
    for(auto preset:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}){
        JoltWorld reference(0,{},execution),measured(0,{},execution);
        auto material=makeReferenceMaterial(preset);material.model=MaterialModel::RigidOnly;
        for(auto *world:{&reference,&measured}){
            world->setGravity({});world->setContactImpulseObservationsEnabled(true);
            world->addBox({1,{.1,.1,.1},material,{{-.05,0,0},{},{},{}},true});
            world->addBox({2,{.1,.1,.1},material,{{ .05,0,0},{},{-1,.4,0},{.2,.1,.3}},false});
            world->setContinuousCollision(2,false);
        }
        measured.setExecutionProfilingEnabled(true);
        const auto same=[&]{
            const auto a=reference.snapshot(2),b=measured.snapshot(2);
            check(lengthSquared(a.center_of_mass_world_m-b.center_of_mass_world_m)==0&&
                lengthSquared(a.linear_velocity_m_s-b.linear_velocity_m_s)==0&&
                lengthSquared(a.angular_velocity_rad_s-b.angular_velocity_rad_s)==0&&
                a.orientation_world.w==b.orientation_world.w&&a.orientation_world.x==b.orientation_world.x&&
                a.orientation_world.y==b.orientation_world.y&&a.orientation_world.z==b.orientation_world.z,
                "profiling preserves exact native motion");
            check(reference.mechanicalTotals({}).kinetic_energy_j==measured.mechanicalTotals({}).kinetic_energy_j,
                "profiling preserves actual kinetic energy");
        };
        for(unsigned i=0;i<40;++i){reference.step(1./960);measured.step(1./960);same();}
        check(!reference.executionProfile().enabled&&reference.executionProfile().step_calls==0,
            "profiling is disabled by default");
        const auto initial=measured.executionProfile();
        check(initial.enabled&&initial.step_calls==40&&initial.trial_calls==0,"profile counts direct steps");
        check(!measured.runReversibleTrial([&]{measured.step(1./960);return false;}),"profile rejection fixture");same();
        const auto rejected=measured.executionProfile();
        check(rejected.step_calls==41&&rejected.trial_calls==1&&rejected.trial_restores==1,
            "actual rejected work is retained by the profiler");
        bool caught=false;
        try{(void)measured.runReversibleTrial([&]()->bool{measured.step(1./960);throw std::runtime_error("timed trial");});}
        catch(const std::runtime_error&){caught=true;}same();
        const auto failed=measured.executionProfile();
        check(caught&&failed.step_calls==42&&failed.trial_calls==2&&failed.trial_restores==2,
            "exception restoration is measured without publishing candidate motion");
        check(measured.runReversibleTrial([&]{
            bool refused=false;try{measured.setExecutionProfilingEnabled(false);}catch(const std::logic_error&){refused=true;}
            check(refused,"profile cannot reset during an active trial");return true;
        }),"profile configuration refusal fixture");
        const auto final=measured.executionProfile();
        for(double ms:{final.step_prepare_ms,final.native_update_ms,final.contact_observation_ms,final.post_step_ms,
                final.trial_capture_ms,final.trial_restore_ms})check(std::isfinite(ms)&&ms>=0,"bounded finite wall timers");
        check(final.native_update_ms>0&&final.trial_capture_ms>0&&final.trial_restore_ms>0,"real timed execution stages observed");
        measured.setExecutionProfilingEnabled(false);
        check(!measured.executionProfile().enabled&&measured.executionProfile().step_calls==0,"explicit profile reset");same();
        check(!measured.runReversibleTrial([&]{
            measured.step(1./960);const auto parent=measured.snapshot(2);
            check(!measured.runReversibleTrial([&]{measured.step(1./960);return false;}),"nested rejection");
            const auto restored=measured.snapshot(2);
            check(lengthSquared(parent.center_of_mass_world_m-restored.center_of_mass_world_m)==0&&
                lengthSquared(parent.linear_velocity_m_s-restored.linear_velocity_m_s)==0&&
                lengthSquared(parent.angular_velocity_rad_s-restored.angular_velocity_rad_s)==0,
                "child recorder restores its own candidate without overwriting parent storage");
            check(measured.runReversibleTrial([&]{measured.step(1./960);return true;}),"accepted child fixture");
            return false;
        }),"parent rejection after child acceptance");same();
        std::function<bool(unsigned)> nest=[&](unsigned depth){
            return measured.runReversibleTrial([&]{
                measured.step(1./960);
                if(depth<16)(void)nest(depth+1);
                else{
                    bool refused=false;try{(void)nest(depth+1);}catch(const std::invalid_argument&){refused=true;}
                    check(refused,"recorder depth bound remains explicit");
                }
                return false;
            });
        };
        check(!nest(1),"maximum-depth recorder recovery");same();
    }
}
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
void sleeping_spring_oracle(){
    JoltWorld world(0,{},execution);world.setGravity({});world.setForcePhaseObservationsEnabled(true);
    auto material=makeReferenceMaterial(MaterialPreset::Iron);material.model=MaterialModel::RigidOnly;
    world.addBox({1,{.1,.1,.1},material,{{-.06,0,0},{},{-.1,0,0},{}},false});
    world.addBox({2,{.1,.1,.1},material,{{ .06,0,0},{},{ .1,0,0},{}},false});
    world.setPairContactOwner(1,2,PairContactOwner::External);
    const auto joint=world.addFaceSpring({1,2,{},{1,0,0},{0,1,0},{1000,1000,1000},{10,10,10},{},{},log_gradient});
    check(world.faceSpringObservation(joint).solver_scheduled==false,"new spring has no accepted solve yet");
    check(!world.runReversibleTrial([&]{world.step(1./240);return false;}),"first native step can reject");
    check(world.forcePhaseObservations().empty()&&world.faceSpringObservation(joint).solver_scheduled==false,
        "first-step rollback restores both empty observation storage and its lookup map");
    world.step(1./240);const auto solved=world.faceSpringObservation(joint);
    check(solved.solver_scheduled==true&&length(solved.linear_impulse_cs_n_s)>1e-4,"spring oracle exercises an actual solve");
    world.sleep(1);world.sleep(2);world.step(1./3840);const auto dormant=world.faceSpringObservation(joint);
    check(dormant.solver_scheduled==false,"both sleeping endpoints exclude a new spring solve");
    check(length(dormant.linear_impulse_cs_n_s-solved.linear_impulse_cs_n_s)==0,"native retains nonzero old spring lambda while asleep");
    auto awake=world.snapshot(1);awake.linear_velocity_m_s.x=-.1;world.applyRigidState(1,awake);
    check(!world.runReversibleTrial([&]{world.step(1./960);check(world.faceSpringObservation(joint).solver_scheduled==true,"waking a connected body schedules the spring");return false;}),"wake trial refuses");
    check(world.faceSpringObservation(joint).solver_scheduled==false,"rollback restores accepted dormant schedule");
    std::cout<<"sleeping spring cached impulse excluded, waking and rollback observed\n";
}
void centered_torsion_oracle(MaterialPreset preset,double damping){
    JoltWorld world(0,{},execution);world.setCenteredIntegration(true);world.setGravity({});world.setContactSolverIterations(96,4);
    auto material=makeReferenceMaterial(preset);material.model=MaterialModel::RigidOnly;
    world.addBox({1,{.1,.1,.1},material,{{-.06,0,0},{},{},{-.1,0,0}},false});
    world.addBox({2,{.1,.1,.1},material,{{ .06,0,0},{},{},{ .1,0,0}},false});
    world.setContinuousCollision(1,false);world.setContinuousCollision(2,false);
    world.setPairContactOwner(1,2,PairContactOwner::External);
    const double k=10,h=1./240;
    const auto joint=world.addFaceSpring({1,2,{},{1,0,0},{0,1,0},{1000,1000,1000},{k,k,k},{},{damping,damping,damping},true,true});
    const double energy0=world.mechanicalTotals().kinetic_energy_j;
    double physical=0,maximum_error=0;
    for(unsigned i=0;i<240;++i){
        const auto f0=world.faceSpringObservation(joint);const auto a0=world.mechanicalState(1),b0=world.mechanicalState(2);
        const double v0=b0.motion.angular_velocity_rad_s.x-a0.motion.angular_velocity_rad_s.x;
        const double mu=1/(1/a0.inertia_world_kg_m2.m[0][0]+1/b0.inertia_world_kg_m2.m[0][0]);
        world.step(h);const auto f1=world.faceSpringObservation(joint);const auto after=world.mechanicalTotals();
        const double v1=world.snapshot(2).angular_velocity_rad_s.x-world.snapshot(1).angular_velocity_rad_s.x;
        const double coefficient=damping/2+h*k/4;
        const double expected=(v0-h*(k*f0.rotation_cs_rad.x+coefficient*v0)/mu)/(1+h*coefficient/mu);
        check(std::abs(v1-expected)<4e-6,"centered torsion analytical velocity");
        const double mid=.5*(v0+v1);physical+=h*damping*mid*mid;
        maximum_error=std::max(maximum_error,std::abs(after.kinetic_energy_j+.5*k*lengthSquared(f1.rotation_cs_rad)+physical-energy0));
        check(length(after.angular_momentum_kg_m2_s)<1e-7,"centered torsion angular momentum");
    }
    check(maximum_error<2e-7,"centered torsion energy with declared damping over 240 steps");
    std::cout<<"material="<<materialSceneName(preset)<<" centered torsion damping="<<damping<<" energy_error_j="<<maximum_error<<" declared_damping_j="<<physical<<'\n';
}
void centered_gravity_oracle(){
    JoltWorld world(0,{},execution);world.setCenteredIntegration(true);world.setGravity({0,-8,0});
    auto m=makeReferenceMaterial(MaterialPreset::Iron);m.model=MaterialModel::RigidOnly;
    world.addBox({1,{.1,.1,.1},m,{{0,10,0},{},{},{}},false});world.setContinuousCollision(1,false);
    const auto initial=world.mechanicalTotals({0,-8,0});const double h=1./256;
    for(unsigned i=0;i<256;++i)world.step(h);
    const auto final=world.mechanicalTotals({0,-8,0});const auto state=world.snapshot(1);
    check(std::abs(state.center_of_mass_world_m.y-6.)<1e-10,"centered gravity analytical displacement");
    std::cout<<"centered gravity y="<<state.center_of_mass_world_m.y<<" v="<<state.linear_velocity_m_s.y<<" energy_error_j="<<final.mechanicalEnergy()-initial.mechanicalEnergy()<<std::endl;
    check(std::abs(final.mechanicalEnergy()-initial.mechanicalEnergy())<1e-10,"centered binary-exact gravity energy no Euler drift loss");
    std::cout<<"centered gravity energy_error_j="<<final.mechanicalEnergy()-initial.mechanicalEnergy()<<'\n';
}
void centered_small_spin_oracle(MaterialPreset preset){
    // All three steps are the same one-second free-spin experiment. The two
    // finer steps lie below the pinned native angular-increment cutoff.
    const Vec3 spin{.000128,0,0};
    auto material=makeReferenceMaterial(preset);material.model=MaterialModel::RigidOnly;
    for(unsigned count:{64U,256U,1024U}){
        JoltWorld world(0,{},execution);world.setCenteredIntegration(true);world.setGravity({});
        world.addBox({1,{.1,.1,.1},material,{{1,2,3},{},{},spin},false});world.setContinuousCollision(1,false);
        const auto initial=world.mechanicalTotals();const auto state0=world.snapshot(1);
        const double h=1./count;
        for(unsigned i=0;i<count;++i)world.step(h);
        const auto state=world.snapshot(1);const auto final=world.mechanicalTotals();
        const double angle=2*std::atan2(state.orientation_world.x,state.orientation_world.w);
        check(std::abs(angle-spin.x)<2e-9,"centered submicroradian rotation converges under time refinement");
        check(length(state.center_of_mass_world_m-state0.center_of_mass_world_m)==0,"centered rotation preserves centre of mass");
        check(length(state.angular_velocity_rad_s-spin)<1e-10,"free spin not assigned or damped by rotation integration");
        check(std::abs(final.kinetic_energy_j-initial.kinetic_energy_j)<1e-15,"small-spin energy retained");
        check(length(final.angular_momentum_kg_m2_s-initial.angular_momentum_kg_m2_s)<1e-12,"small-spin angular momentum retained");
        const auto accepted=world.snapshot(1);
        check(!world.runReversibleTrial([&]{world.step(h);return false;}),"small-spin trial refusal");
        const auto restored=world.snapshot(1);
        check(restored.orientation_world.x==accepted.orientation_world.x&&restored.orientation_world.w==accepted.orientation_world.w,"small-spin native pose rollback");
        std::cout<<"material="<<materialSceneName(preset)<<" centered small-spin steps="<<count<<" angle_rad="<<angle<<" angle_error_rad="<<angle-spin.x<<" energy_error_j="<<final.kinetic_energy_j-initial.kinetic_energy_j<<'\n';
    }
#ifndef BANJO_JOLT_CONTINUOUS_SMALL_ROTATION
    JoltWorld reference(0,{},execution);reference.setGravity({});
    reference.addBox({1,{.1,.1,.1},material,{{1,2,3},{},{},spin},false});reference.setContinuousCollision(1,false);
    reference.step(1./256);
    check(reference.snapshot(1).orientation_world.x==0&&reference.snapshot(1).angular_velocity_rad_s.x>0,"reference dead zone precedes native sleep");
    for(unsigned i=1;i<256;++i)reference.step(1./256);
    const auto state=reference.snapshot(1);
    check(state.orientation_world.x==0,"pinned reference cutoff remains unchanged");
#endif
}
void centered_pair_oracle(MaterialPreset preset,double damping){
    JoltWorld world(0,{},execution);world.setCenteredIntegration(true);world.setGravity({});world.setContactSolverIterations(96,4);
    auto material=makeReferenceMaterial(preset);material.model=MaterialModel::RigidOnly;
    world.addBox({1,{.1,.1,.1},material,{{-.06,0,0},{},{-.1,0,0},{}},false});
    world.addBox({2,{.1,.1,.1},material,{{ .06,0,0},{},{ .1,0,0},{}},false});
    world.setContinuousCollision(1,false);world.setContinuousCollision(2,false);
    world.setPairContactOwner(1,2,PairContactOwner::External);
    const double k=1000,h=1./240;
    const auto joint=world.addFaceSpring({1,2,{},{1,0,0},{0,1,0},{k,k,k},{10,10,10},{damping,damping,damping},{},true,true});
    auto a=world.snapshot(1),b=world.snapshot(2);a.center_of_mass_world_m.x-=.005;b.center_of_mass_world_m.x+=.005;
    world.applyRigidState(1,a);world.applyRigidState(2,b);
    const auto initial=world.mechanicalTotals();const auto initial_face=world.faceSpringObservation(joint);
    const double energy0=initial.kinetic_energy_j+.5*k*lengthSquared(initial_face.displacement_cs_m);
    double physical=0,maximum_error=0;
    for(unsigned i=0;i<240;++i){
        const auto before=world.mechanicalTotals();const auto f0=world.faceSpringObservation(joint);
        const auto a0=world.mechanicalState(1),b0=world.mechanicalState(2);
        const double v0=b0.motion.linear_velocity_m_s.x-a0.motion.linear_velocity_m_s.x;
        const double mu=1/(1/a0.mass_kg+1/b0.mass_kg);
        world.step(h);const auto f1=world.faceSpringObservation(joint);const auto after=world.mechanicalTotals();
        const double v1=world.snapshot(2).linear_velocity_m_s.x-world.snapshot(1).linear_velocity_m_s.x;
        const double coefficient=damping/2+h*k/4;
        const double expected=(v0-h*(k*f0.displacement_cs_m.x+coefficient*v0)/mu)/(1+h*coefficient/mu);
        if(std::abs(v1-expected)>=3e-6)std::cout<<"centered mismatch i="<<i<<" material="<<materialSceneName(preset)<<" v0="<<v0<<" v1="<<v1<<" expected="<<expected<<" q0="<<f0.displacement_cs_m.x<<" impulse="<<f1.linear_impulse_cs_n_s.x<<std::endl;
        check(std::abs(v1-expected)<3e-6,"centered spring analytical velocity");
        const double mid=.5*(v0+v1);
        check(std::abs(f1.displacement_cs_m.x-f0.displacement_cs_m.x-h*mid)<1e-8,"centered drift uses actual midpoint velocity");
        physical+=h*damping*mid*mid;
        const double energy=after.kinetic_energy_j+.5*k*lengthSquared(f1.displacement_cs_m);
        maximum_error=std::max(maximum_error,std::abs(energy+physical-energy0));
        check(length(after.linear_momentum_kg_m_s-before.linear_momentum_kg_m_s)<1e-7,"centered spring linear momentum");
        check(length(after.angular_momentum_kg_m2_s-before.angular_momentum_kg_m2_s)<1e-7,"centered spring angular momentum");
        if(i==0){
            const auto state=world.snapshot(1);
            check(!world.runReversibleTrial([&]{world.step(h);return false;}),"centered refusal rolls back");
            check(world.snapshot(1).center_of_mass_world_m.x==state.center_of_mass_world_m.x,"centered pose restored");
            check(world.faceSpringObservation(joint).linear_impulse_cs_n_s.x==f1.linear_impulse_cs_n_s.x,"centered spring state restored");
        }
    }
    check(maximum_error<2e-6,"centered spring energy with only declared damping over 240 steps");
    bool late=false;try{world.setCenteredIntegration(false);}catch(const std::logic_error&){late=true;}
    check(late,"centered integration cannot change live history");
    bool ccd=false;try{world.setContinuousCollision(1,true);}catch(const std::invalid_argument&){ccd=true;}
    check(ccd,"uncoupled CCD refused in centered world");
    std::cout<<"material="<<materialSceneName(preset)<<" centered damping="<<damping<<" energy_error_j="<<maximum_error<<" declared_damping_j="<<physical<<'\n';
}
// Frozen-normal unilateral midpoint boundary; not a material indentation law.
void midpoint_contact_oracle(MaterialPreset preset,bool fixed,double fraction,double h){
    JoltWorld world(0,{},execution);world.setCenteredIntegration(true);world.setGravity({});
    world.configureVoxelContacts(.1);world.setContactSolverIterations(96,4);
    world.setContactImpulseObservationsEnabled(true);
    world.setContactRestitutionModel(RigidContactRestitution::MidpointUnilateral);
    auto material=makeReferenceMaterial(preset);material.model=MaterialModel::RigidOnly;
    material.static_friction=material.dynamic_friction=material.friction=material.rolling_resistance=0;
    const double closing=fixed?1:2,gap=closing*h*fraction;
    world.addBox({1,{.1,.1,.1},material,{{-.05-gap/2,0,0},{},fixed?Vec3{}:Vec3{1,0,0},{}},fixed});
    world.addBox({2,{.1,.1,.1},material,{{ .05+gap/2,0,0},{},{-1,0,0},{}},false});
    if(!fixed)world.setContinuousCollision(1,false);world.setContinuousCollision(2,false);
    const auto a0=world.mechanicalState(1),b0=world.mechanicalState(2);const auto before=world.mechanicalTotals({});
    world.step(h);const auto a=world.mechanicalState(1),b=world.mechanicalState(2);const auto after=world.mechanicalTotals({});
    const double final_relative=b.motion.linear_velocity_m_s.x-a.motion.linear_velocity_m_s.x;
    const double expected=fraction<1?closing*(1-2*fraction):-closing;
    // Native contact witnesses are float even with double COM positions.
    // Their gap error becomes velocity error divided by h under refinement.
    const double gap_tolerance=8*std::numeric_limits<float>::epsilon()*.1;
    const double velocity_tolerance=2*gap_tolerance/h;
    check(std::abs(final_relative-expected)<velocity_tolerance,"midpoint contact relative velocity follows gap complementarity");
    const double final_gap=b.motion.center_of_mass_world_m.x-a.motion.center_of_mass_world_m.x-.1;
    const double expected_gap=fraction<1?0:gap-closing*h;
    check(std::abs(final_gap-expected_gap)<gap_tolerance,"midpoint contact integrates the predicted separation");
    const double reduced=fixed?b0.mass_kg:1/(1/a0.mass_kg+1/b0.mass_kg);
    const double expected_change=.5*reduced*(expected*expected-closing*closing);
    check(std::abs(after.kinetic_energy_j-before.kinetic_energy_j-expected_change)<reduced*(std::abs(expected)*velocity_tolerance+.5*velocity_tolerance*velocity_tolerance)+3e-6,"midpoint contact energy matches analytical boundary work");
    Vec3 impulse{},torque_b{};double work=0;
    for(const auto &contact:world.contactImpulseObservations())for(const auto &point:contact.points){
        const auto push=contact.normal_a_to_b*point.normal_impulse_n_s;
        const auto ra=point.point_world_m-a0.motion.center_of_mass_world_m,rb=point.point_world_m-b0.motion.center_of_mass_world_m;
        const auto v0=b0.motion.linear_velocity_m_s+cross(b0.motion.angular_velocity_rad_s,rb)-a0.motion.linear_velocity_m_s-cross(a0.motion.angular_velocity_rad_s,ra);
        const auto v1=b.motion.linear_velocity_m_s+cross(b.motion.angular_velocity_rad_s,rb)-a.motion.linear_velocity_m_s-cross(a.motion.angular_velocity_rad_s,ra);
        impulse+=push;torque_b+=cross(rb,push);work+=dot(push,(v0+v1)/2);
    }
    // Four contact rows accumulate float velocity/impulse updates. Bound
    // this distinct oracle by 32 float eps times its momentum/work scale;
    // record the actual residuals rather than treating this as world accuracy.
    const double momentum_tolerance=32*std::numeric_limits<float>::epsilon()*b0.mass_kg*(1+closing);
    const double impulse_error=length(b0.mass_kg*(b.motion.linear_velocity_m_s-b0.motion.linear_velocity_m_s)-impulse);
    const double work_error=after.kinetic_energy_j-before.kinetic_energy_j-work;
    check(impulse_error<momentum_tolerance,"midpoint contact impulse matches native momentum change");
    check(length(b0.inertia_world_kg_m2*(b.motion.angular_velocity_rad_s-b0.motion.angular_velocity_rad_s)-torque_b)<momentum_tolerance*.1,"midpoint contact actual lever arms account for torque");
    check(std::abs(work_error)<momentum_tolerance*closing,"midpoint contact work matches kinetic change");
    check(work<momentum_tolerance*closing,"nonoverlapping midpoint normal contact does not add energy");
    if(!fixed){
        check(length(after.linear_momentum_kg_m_s-before.linear_momentum_kg_m_s)<momentum_tolerance,"midpoint contact equal opposite reactions");
        check(length(after.angular_momentum_kg_m2_s-before.angular_momentum_kg_m2_s)<momentum_tolerance*.1,"midpoint contact global angular momentum");
    }
    const auto accepted=world.snapshot(2);const auto saved_count=world.contactImpulseObservations().size();
    check(!world.runReversibleTrial([&]{world.step(h);return false;}),"midpoint contact can reject the next trial");
    check(world.snapshot(2).center_of_mass_world_m.x==accepted.center_of_mass_world_m.x&&world.snapshot(2).linear_velocity_m_s.x==accepted.linear_velocity_m_s.x,"midpoint contact rollback retains accepted motion");
    check(world.contactImpulseObservations().size()==saved_count,"midpoint contact rollback retains accepted observations");
    std::cout<<"material="<<materialSceneName(preset)<<" midpoint-contact fixed="<<fixed<<" fraction="<<fraction<<" h="<<h<<" final_gap_m="<<final_gap<<" velocity_error_m_s="<<final_relative-expected<<" gap_error_m="<<final_gap-expected_gap<<" energy_error_j="<<after.kinetic_energy_j-before.kinetic_energy_j-expected_change<<" impulse_error_n_s="<<impulse_error<<" work_error_j="<<work_error<<" work_j="<<work<<'\n';
}
// Coupled torsion reverses endpoint spin during the solve. Endpoint friction
// can then add work at the trajectory midpoint; retain that failing control.
void midpoint_twist_reversal_oracle(MaterialPreset preset,bool repaired,bool sliding,bool block=false){
    JoltWorld world(0,{},execution);world.setCenteredIntegration(true);world.setGravity({});
    world.configureVoxelContacts(.004);world.setContactSolverIterations(96,4);
    world.setContactImpulseObservationsEnabled(true);
    world.setContactRestitutionModel(block?RigidContactRestitution::MidpointBlockFriction:repaired?RigidContactRestitution::MidpointUnilateral:RigidContactRestitution::ResolvedDeformation);
    auto material=makeReferenceMaterial(preset);material.model=MaterialModel::RigidOnly;
    material.static_friction=material.dynamic_friction=material.friction=.4;material.rolling_resistance=0;
    world.addBox({1,{.1,.1,.1},material,{{-.05,0,0},{},{},{}},true});
    world.addBox({2,{.1,.1,.1},material,{{ .05,0,0},{},{-1,sliding?1.:0,0},sliding?Vec3{}:Vec3{1,0,0}},false});
    world.addBox({3,{.1,.1,.1},material,{{ .30,0,0},{},{},{}},true});
    world.setContinuousCollision(2,false);world.setPairContactOwner(2,3,PairContactOwner::External);
    const double k=1e4,h=1./240;const Vec3 kt{1,sliding?1e7:1,1},kr{k,sliding?k:1,sliding?k:1};
    const auto joint=world.addFaceSpring({2,3,{.05,0,0},{1,0,0},{0,1,0},kt,kr,{},{},true,true});
    const auto a0=world.mechanicalState(2);const auto before=world.mechanicalTotals({});
    world.step(h);const auto a=world.mechanicalState(2);const auto face=world.faceSpringObservation(joint);
    const double e0=.5*dot(a0.motion.angular_velocity_rad_s,a0.inertia_world_kg_m2*a0.motion.angular_velocity_rad_s)+.5*a0.mass_kg*a0.motion.linear_velocity_m_s.y*a0.motion.linear_velocity_m_s.y;
    const auto potential=[](Vec3 stiffness,Vec3 value){return .5*(stiffness.x*value.x*value.x+stiffness.y*value.y*value.y+stiffness.z*value.z*value.z);};
    const double elastic=potential(kt,face.displacement_cs_m)+potential(kr,face.rotation_cs_rad);
    const double e1=.5*dot(a.motion.angular_velocity_rad_s,a.inertia_world_kg_m2*a.motion.angular_velocity_rad_s)+.5*a.mass_kg*(a.motion.linear_velocity_m_s.y*a.motion.linear_velocity_m_s.y+a.motion.linear_velocity_m_s.z*a.motion.linear_velocity_m_s.z)+elastic;
    double twist_gap=0,slide_gap=0;
    for(const auto &c:world.contactImpulseObservations()){
        check(c.a==1&&c.b==2,"controlled friction observes the intended complete body pair");
        check(std::abs(c.combined_friction-.4)<1e-7,"observed friction is the coefficient supplied to the native solver");
        double cap=0,twist_cap=0;for(const auto &p:c.points){cap+=p.normal_impulse_n_s;twist_cap+=p.normal_impulse_n_s*p.friction_radius_m;}
        cap*=c.combined_friction;twist_cap*=c.combined_friction;
        const auto velocity=[&](const RigidMechanicalState &s){return s.motion.linear_velocity_m_s+cross(s.motion.angular_velocity_rad_s,c.friction_point_world_m-a0.motion.center_of_mass_world_m);};
        const auto relative=(velocity(a0)+velocity(a))/2;
        const auto slip=relative-dot(relative,c.normal_a_to_b)*c.normal_a_to_b;
        const auto stationarity=auditContactFrictionStationarity(c.friction_impulse_on_b_n_s,slip,cap,
            dot(c.twist_impulse_on_b_n_m_s,c.normal_a_to_b),dot((a0.motion.angular_velocity_rad_s+a.motion.angular_velocity_rad_s)/2,c.normal_a_to_b),twist_cap);
        twist_gap=std::max(twist_gap,stationarity.twist_gap_j);slide_gap=std::max(slide_gap,stationarity.friction_gap_j);
        if(repaired)check(stationarity.twist_cap_excess_n_m_s<1e-7&&stationarity.friction_cap_excess_n_s<1e-6,"controlled matched friction retains native Coulomb caps");
    }
    std::cout<<"material="<<materialSceneName(preset)<<(sliding?" midpoint-slide repaired=":" midpoint-twist repaired=")<<repaired<<" block="<<block<<" coupled_energy_change_j="<<e1-e0<<" spin_x_rad_s="<<a.motion.angular_velocity_rad_s.x<<'\n';
    std::cout<<"stationarity material="<<materialSceneName(preset)<<" repaired="<<repaired<<" sliding="<<sliding<<" twist_gap_j="<<twist_gap<<" friction_gap_j="<<slide_gap<<'\n';
    if(repaired){
        check(twist_gap<5e-6&&slide_gap<5e-6,"controlled midpoint contact agrees with final slip and twist");
        check(e1-e0<4e-7,"midpoint friction cannot create energy in a coupled direction reversal");
        if(!sliding)check(std::abs(a.motion.angular_velocity_rad_s.x+1)<3e-5,"midpoint twist satisfies the shared trajectory constraint");
        check(world.mechanicalTotals({}).kinetic_energy_j+elastic-before.kinetic_energy_j<5e-6,"coupled midpoint contact creates no energy beyond native float bound");
    }else check(e1-e0>1e-5,"endpoint friction control retains observed coupled energy creation");
}
// A partial support patch shifts the friction point away from the COM;
// yawed unequal dimensions couple both tangent rows and the twist row.
void block_anisotropic_patch_oracle(MaterialPreset preset,bool endpoint=false){
    JoltWorld world(0,{},execution);world.setCenteredIntegration(!endpoint);world.setGravity({});
    world.configureVoxelContacts(.004);world.setContactSolverIterations(96,4);
    world.setContactImpulseObservationsEnabled(true);
    world.setContactRestitutionModel(endpoint?RigidContactRestitution::MaterialBlockFriction:RigidContactRestitution::MidpointBlockFriction);
    auto material=makeReferenceMaterial(preset);material.model=MaterialModel::RigidOnly;
    material.static_friction=material.dynamic_friction=material.friction=.4;material.rolling_resistance=0;
    const double angle=.37;
    world.addBox({1,{.06,.1,.06},material,{{.025,-.05,.015},{},{},{}},true});
    world.addBox({2,{.15,.1,.08},material,{{0,.05,0},{std::cos(angle/2),0,std::sin(angle/2),0},{1,-1,.5},{2,5,-3}},false});
    world.setContinuousCollision(2,false);
    const auto before=world.mechanicalState(2);world.step(1./960);const auto after=world.mechanicalState(2);
    double gap=0,work=0,common_work=0;unsigned contacts=0;
    for(const auto& c:world.contactImpulseObservations()){
        check(c.a==1&&c.b==2,"anisotropic block observes intended support pair");++contacts;
        double cap=0,twist_cap=0;for(const auto& point:c.points){cap+=point.normal_impulse_n_s;twist_cap+=point.normal_impulse_n_s*point.friction_radius_m;}
        cap*=c.combined_friction;twist_cap*=c.combined_friction;
        const Vec3 r=c.friction_point_world_m-before.motion.center_of_mass_world_m;
        Vec3 slip=(before.motion.linear_velocity_m_s+after.motion.linear_velocity_m_s+cross(before.motion.angular_velocity_rad_s+after.motion.angular_velocity_rad_s,r))/2;
        if(endpoint)slip=after.motion.linear_velocity_m_s+cross(after.motion.angular_velocity_rad_s,r);
        slip-=dot(slip,c.normal_a_to_b)*c.normal_a_to_b;
        const auto audit=auditContactFrictionStationarity(c.friction_impulse_on_b_n_s,slip,cap,
            dot(c.twist_impulse_on_b_n_m_s,c.normal_a_to_b),dot(endpoint?after.motion.angular_velocity_rad_s:(before.motion.angular_velocity_rad_s+after.motion.angular_velocity_rad_s)/2,c.normal_a_to_b),twist_cap);
        gap=std::max(gap,std::max(audit.friction_gap_j,audit.twist_gap_j));work+=audit.friction_work_j+audit.twist_work_j;
        common_work+=dot(c.friction_impulse_on_b_n_s,(before.motion.linear_velocity_m_s+after.motion.linear_velocity_m_s+cross(before.motion.angular_velocity_rad_s+after.motion.angular_velocity_rad_s,r))/2)+dot(c.twist_impulse_on_b_n_m_s,(before.motion.angular_velocity_rad_s+after.motion.angular_velocity_rad_s)/2);
        check(audit.friction_cap_excess_n_s<1e-6&&audit.twist_cap_excess_n_m_s<1e-8,"anisotropic block retains native caps");
    }
    check(contacts>0&&gap<5e-6&&work<=1e-6&&common_work<=1e-6,"anisotropic native block final stationarity and actual dissipative work");
    std::cout<<"material="<<materialSceneName(preset)<<" anisotropic_block endpoint="<<endpoint<<" gap_j="<<gap<<" friction_work_j="<<common_work<<'\n';
}
void midpoint_contact_configuration_oracle(){
    JoltWorld world(0,{},execution);bool refused=false;
    try{world.setContactRestitutionModel(RigidContactRestitution::MidpointUnilateral);}catch(const std::invalid_argument &){refused=true;}
    check(refused,"midpoint contact refuses endpoint pose integration");
    world.setCenteredIntegration(true);world.setContactRestitutionModel(RigidContactRestitution::MidpointUnilateral);
    refused=false;try{world.setCenteredIntegration(false);}catch(const std::logic_error &){refused=true;}
    check(refused,"midpoint contact cannot lose its matching pose integrator");
}
void restitution_model_oracle(MaterialPreset preset,bool resolved,bool block=false){
    JoltWorld world(0,{},execution);world.setGravity({});world.configureVoxelContacts(.004);
    world.setContactSolverIterations(96,4);world.setContactImpulseObservationsEnabled(true);
    world.setContactRestitutionModel(block?RigidContactRestitution::MaterialBlockFriction:resolved?RigidContactRestitution::ResolvedDeformation:RigidContactRestitution::MaterialCombination);
    auto material=makeReferenceMaterial(preset);material.model=MaterialModel::RigidOnly;
    material.static_friction=material.dynamic_friction=material.friction=material.rolling_resistance=0;
    world.addBox({1,{.1,.1,.1},material,{{-.05,0,0},{},{1,0,0},{}},false});
    world.addBox({2,{.1,.1,.1},material,{{ .05,0,0},{},{-1,0,0},{}},false});
    world.setContinuousCollision(1,false);world.setContinuousCollision(2,false);
    const auto before=world.mechanicalTotals({});world.step(1./960);const auto after=world.mechanicalTotals({});
    const auto combined=combineContactMaterials(compileContactMaterial(material),compileContactMaterial(material));
    const double e=resolved?0:combined.restitution,mass=.001*material.density_kg_m3;
    check(std::abs(world.snapshot(2).linear_velocity_m_s.x-e)<2e-6,"declared restitution model has analytical separating speed");
    check(std::abs(after.kinetic_energy_j-mass*e*e)<1e-5,"declared normal impact has analytical energy loss");
    check(length(after.linear_momentum_kg_m_s-before.linear_momentum_kg_m_s)<2e-6,"normal impact retains momentum");
    check(length(after.angular_momentum_kg_m2_s-before.angular_momentum_kg_m2_s)<2e-6,"normal impact retains angular momentum");
    bool late=false;try{world.setContactRestitutionModel(RigidContactRestitution::MaterialCombination);}catch(const std::logic_error&){late=true;}
    check(late,"contact model cannot change with live bodies/history");
    std::cout<<"material="<<materialSceneName(preset)<<" resolved="<<resolved<<" e="<<e<<" loss_j="<<before.kinetic_energy_j-after.kinetic_energy_j<<'\n';
}
void resolved_assembly_recovery_oracle(MaterialPreset preset){
    JoltWorld world(0,{},execution);world.setGravity({});world.configureVoxelContacts(.004);
    world.setContactSolverIterations(96,4);world.setContactImpulseObservationsEnabled(true);
    world.setContactRestitutionModel(RigidContactRestitution::ResolvedDeformation);
    auto material=makeReferenceMaterial(preset);material.model=MaterialModel::RigidOnly;
    material.static_friction=material.dynamic_friction=material.friction=material.rolling_resistance=0;
    world.addBox({1,{.1,.1,.1},material,{{0,.05,0},{},{0,-1,0},{}},false});
    world.addBox({2,{.1,.1,.1},material,{{0,.15,0},{},{0,-1,0},{}},false});
    world.addBox({3,{.4,.1,.4},material,{{0,-.05,0},{},{},{}},true});
    world.setContinuousCollision(1,false);world.setContinuousCollision(2,false);
    world.setPairContactOwner(1,2,PairContactOwner::External);
    // Declared linear-spring oracle, not a calibrated material stiffness.
    const auto joint=world.addFaceSpring({1,2,{0,.1,0},{0,1,0},{1,0,0},{1000,1000,1000},{1,1,1},{},{}});
    const double initial=world.mechanicalTotals({}).kinetic_energy_j;
    double peak_elastic=0,peak_energy=initial,upward=0;unsigned contacts=0;
    for(unsigned i=0;i<400;++i){
        world.step(1./960);const auto s=world.faceSpringObservation(joint);
        const double elastic=500*lengthSquared(s.displacement_cs_m)+.5*lengthSquared(s.rotation_cs_rad);
        peak_elastic=std::max(peak_elastic,elastic);peak_energy=std::max(peak_energy,world.mechanicalTotals({}).kinetic_energy_j+elastic);
        upward=std::max(upward,world.snapshot(2).linear_velocity_m_s.y);
        contacts+=unsigned(world.contactImpulseObservations().size());
    }
    check(contacts>0&&peak_elastic>.01,"assembly has actual contact and stores elastic energy");
    check(upward>.1,"inelastic surface constraints allow actual elastic assembly recovery");
    check(peak_energy-initial<1e-5,"declared one-dimensional recovery creates no energy beyond native float tolerance");
    std::cout<<"material="<<materialSceneName(preset)<<" assembly_recovery="<<upward<<" peak_elastic_j="<<peak_elastic<<" peak_energy_excess_j="<<peak_energy-initial<<'\n';
}
}
int main(){try{for(auto policy:{RigidJobExecution::ThreadPool,RigidJobExecution::Inline}){execution=policy;execution_profile_oracle();std::cout<<"execution="<<(policy==RigidJobExecution::Inline?"inline":"thread-pool")<<'\n';for(bool law:{false,true}){log_gradient=law;for(double extension:{0.,.01}){oracle(0,extension);oracle(20,extension);}torsion(0);torsion(.005);sleeping_spring_oracle();}nearest_orientation();for(bool fixed:{false,true})for(double friction:{0.,.4})contact_oracle(fixed,friction);gravity_oracle();log_gradient_impulse_oracle();limit_observation_oracle();for(auto material:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron})for(bool resolved:{false,true})restitution_model_oracle(material,resolved);for(auto material:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron})resolved_assembly_recovery_oracle(material);for(auto material:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron})for(double damping:{0.,20.})centered_pair_oracle(material,damping);for(auto material:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron})for(double damping:{0.,.02})centered_torsion_oracle(material,damping);centered_gravity_oracle();for(auto material:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron,MaterialPreset::Ice})for(bool endpoint:{false,true})block_anisotropic_patch_oracle(material,endpoint);for(auto material:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron,MaterialPreset::Ice})restitution_model_oracle(material,false,true);midpoint_contact_configuration_oracle();for(auto material:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron})for(bool repaired:{false,true})for(bool sliding:{false,true})midpoint_twist_reversal_oracle(material,repaired,sliding);for(auto material:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron})for(bool sliding:{false,true})midpoint_twist_reversal_oracle(material,true,sliding,true);for(auto material:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron})for(bool fixed:{false,true})for(double fraction:{0.,.25,.75,1.25})for(double h:{1./960,1./3840})midpoint_contact_oracle(material,fixed,fraction,h);for(auto material:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron})centered_small_spin_oracle(material);}return 0;}catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}}
