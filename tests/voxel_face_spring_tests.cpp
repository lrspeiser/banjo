#include "rigid/JoltWorld.hpp"
#include "material/MaterialCatalog.hpp"
#include <cmath>
#include <iostream>
#include <stdexcept>
using namespace banjo;
namespace {
void check(bool value,const char *why){if(!value)throw std::runtime_error(why);}
double axis(Vec3 a,Vec3 b){return dot(a,b);}
void oracle(double damping,double initial_extension){
    JoltWorld world(0);world.setGravity({});world.setContactSolverIterations(96,4);
    auto material=makeReferenceMaterial(MaterialPreset::Iron);material.model=MaterialModel::RigidOnly;
    world.addBox({1,{.1,.1,.1},material,{{-.06,0,0},{},{-.1,0,0},{}},false});
    world.addBox({2,{.1,.1,.1},material,{{ .06,0,0},{},{ .1,0,0},{}},false});
    world.setPairContactOwner(1,2,PairContactOwner::External);
    const double stiffness=1000,h=1./240;
    const auto joint=world.addFaceSpring({1,2,{},{1,0,0},{0,1,0},{stiffness,stiffness,stiffness},{10,10,10},{damping,damping,damping},{0,0,0}});
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
    JoltWorld world(0);world.setGravity({});world.setContactSolverIterations(96,4);
    auto material=makeReferenceMaterial(MaterialPreset::Iron);material.model=MaterialModel::RigidOnly;
    world.addBox({1,{.1,.1,.1},material,{{-.06,0,0},{},{},{-.1,0,0}},false});
    world.addBox({2,{.1,.1,.1},material,{{ .06,0,0},{},{},{ .1,0,0}},false});
    world.setPairContactOwner(1,2,PairContactOwner::External);
    const double k=10,h=1./240;
    const auto joint=world.addFaceSpring({1,2,{},{1,0,0},{0,1,0},{1000,1000,1000},{k,k,k},{0,0,0},{damping,damping,damping}});
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
    JoltWorld world(0);world.setGravity({});
    auto material=makeReferenceMaterial(MaterialPreset::Iron);material.model=MaterialModel::RigidOnly;
    world.addBox({1,{.1,.1,.1},material,{{-.06,0,0},{},{},{}},false});
    world.addBox({2,{.1,.1,.1},material,{{ .06,0,0},{},{},{}},false});
    const auto joint=world.addFaceSpring({1,2,{},{1,0,0},{0,1,0},{1000,1000,1000},{10,10,10},{0,0,0},{0,0,0}});
    auto pose=world.snapshot(2);pose.orientation_world={0,1,0,0};world.applyRigidState(2,pose);
    const auto face=world.faceSpringObservation(joint);
    check(std::abs(face.rotation_cs_rad.x-std::acos(-1.))<1e-7,"physical pi rotation");
    check(face.rotation_error_cs_rad.x==-2,"native orientation tie chooses negative identity target");
}
}
int main(){try{for(double extension:{0.,.01}){oracle(0,extension);oracle(20,extension);}torsion(0);torsion(.005);nearest_orientation();return 0;}catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}}
