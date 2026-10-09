#include "rigid/RigidComponent.hpp"
#include "material/MaterialCatalog.hpp"
#include <cmath>
#include <iostream>
#include <stdexcept>
using namespace banjo;
namespace {
void check(bool x,const char *why){if(!x)throw std::runtime_error(why);}
void transfer(MaterialPreset preset,bool log){
    JoltWorld world(0,{},RigidJobExecution::Inline);world.setGravity({});
    world.setForcePhaseObservationsEnabled(true);world.setContactImpulseObservationsEnabled(true);
    auto material=makeReferenceMaterial(preset);material.model=MaterialModel::RigidOnly;
    auto other=makeReferenceMaterial(MaterialPreset::Iron);other.model=MaterialModel::RigidOnly;
    const Vec3 velocity{1,.2,-.3},spin{.4,-.2,.1};
    const Quat rotation{std::cos(.1),0,0,std::sin(.1)};
    world.addBox({1,{.1,.04,.08},material,{{-.05,3,0},rotation,velocity+cross(spin,Vec3{-.05,0,0}),spin},false});
    world.addBox({2,{.06,.07,.09},other,{{.05,3,0},rotation,velocity+cross(spin,Vec3{.05,0,0}),spin},false});
    for(const auto id:{1U,2U})world.setContinuousCollision(id,false);
    const auto joint=world.addFaceSpring({1,2,{0,3,0},{1,0,0},{0,1,0},{1000,900,800},{2,3,4},{1,1,1},{.01,.02,.03},log,false});
    if(log)world.setFacePlasticRest(joint,{.001,0,0},{0,.002,0});
    world.setPairContactOwner(1,2,PairContactOwner::External);
    const auto original=world.faceSpringObservation(joint);
    RigidComponent component(100,{{1,{.1,.04,.08},material},{2,{.06,.07,.09},other}});
    const auto reject=component.collapse(world,.1);
    check(!reject.admitted&&world.contains(1)&&world.contains(2)&&!world.contains(100),"stored energy refusal leaves original scene");
    ComponentTransferBudget budget;budget.nonrigid_energy_j=1e-8;budget.energy_j=1e-4;budget.angular_momentum_n_m_s=1e-4;
    // Representation-only round trip at the same physical instant. For the
    // nonzero plastic rest fixture no elapsed rigid continuation is admitted.
    const auto collapsed=component.collapse(world,0,budget);
    check(collapsed.admitted&&collapsed.audit.measured,"native compound transfer admitted");
    check(world.parked(1)&&world.parked(2)&&!world.contains(1)&&world.contains(100),"original bodies parked, one active owner");
    check(world.faceComponentParked(joint)&&!world.faceSpringObservation(joint).solver_scheduled.value(),"native rest retained and dormant impulses not scheduled");
    std::string why;const MatterBodyId partial[]{1};const auto states=component.snapshots(world);
    check(!world.restoreFaceComponent(partial,std::span(states).first(1),why)&&world.parked(1),"partial component restore refused before mutation");
    if(log){bool rejected=false;try{world.setFacePlasticRest(joint,{.5,0,0},{});}catch(const std::invalid_argument&){rejected=true;}
        check(rejected,"constitutive edits require restoring detailed component first");}
    bool duplicate=false;try{world.addBox({1,{.1,.04,.08},material,{{},{},{},{}},false});}catch(const std::logic_error&){duplicate=true;}
    check(duplicate&&world.parked(1),"parked original ID cannot be reused for another body");
    const auto proxyBefore=world.snapshot(100);
    check(!world.runReversibleTrial([&]{world.step(.001);return false;}),"proxy trial rejection");
    check(length(world.snapshot(100).center_of_mass_world_m-proxyBefore.center_of_mass_world_m)==0,"native proxy rollback exact");
    const auto expanded=component.expand(world);
    check(expanded.admitted&&expanded.audit.measured&&world.contains(1)&&world.contains(2)&&!world.contains(100),"original native cells restored without duplicate proxy");
    const auto restored=world.faceSpringObservation(joint);
    check(length(restored.displacement_cs_m-original.displacement_cs_m)<2e-6&&
        length(restored.rotation_cs_rad-original.rotation_cs_rad)<2e-6,"local material frames and plastic rest survive round trip");
    check(world.pairContactOwner(1,2)==PairContactOwner::External,"internal pair ownership retained");
    world.step(.0001);check(world.faceSpringObservation(joint).solver_scheduled.value(),"restored native constraint actually solves");
    std::cout<<material.name<<" log="<<log<<" dM="<<expanded.audit.after.mass_kg-expanded.audit.before.mass_kg
        <<" dE="<<expanded.audit.after.mechanicalEnergy()-expanded.audit.before.mechanicalEnergy()
        <<" dP="<<length(expanded.audit.after.linear_momentum_kg_m_s-expanded.audit.before.linear_momentum_kg_m_s)
        <<" dL="<<length(expanded.audit.after.angular_momentum_kg_m2_s-expanded.audit.before.angular_momentum_kg_m2_s)<<'\n';
}
void geometryAndContinuation(){
    JoltWorld world(0,{},RigidJobExecution::Inline);world.setGravity({});
    auto m=makeReferenceMaterial(MaterialPreset::Glass);m.model=MaterialModel::RigidOnly;
    for(const auto id:{1U,2U})world.addBox({id,{.1,.1,.1},m,{{id==1?-.2:.2,2,0},{},{0,0,.1},{}},false});
    world.addFaceSpring({1,2,{0,2,0},{1,0,0},{0,1,0},{100,100,100},{1,1,1},{0,0,0},{0,0,0}});
    world.setPairContactOwner(1,2,PairContactOwner::External);
    RigidComponent component(100,{{1,{.1,.1,.1},m},{2,{.1,.1,.1},m}});
    for(unsigned round=0;round<2;++round){
        check(component.collapse(world,0).admitted,"repeated free component collapse");
        check(!world.castRay({0,2,-1},{0,0,1},2).hit,"compound does not fill empty gap with a convex hull");
        check(world.castRay({-.2,2,-1},{0,0,1},2).body_id==100,"original occupied cell surface belongs to proxy");
        for(unsigned i=0;i<100;++i)world.step(.001);
        const auto restored=component.expand(world);
        check(restored.admitted&&world.contains(1)&&world.contains(2),"second elapsed handoff restores source bodies");
        check(std::abs(world.snapshot(1).linear_velocity_m_s.z-.1)<1e-7,"elapsed free motion survives restoration");
    }
}
void preflight(){
    JoltWorld world(0,{},RigidJobExecution::Inline);world.setGravity({});
    auto material=makeReferenceMaterial(MaterialPreset::Glass);material.model=MaterialModel::RigidOnly;
    for(const auto id:{1U,2U})world.addBox({id,{.1,.1,.1},material,{{.1*id,2,0},{},{},{}},false});
    const auto joint=world.addFaceSpring({1,2,{.15,2,0},{1,0,0},{0,1,0},{100,100,100},{1,1,1},{0,0,0},{0,0,0}});
    std::string why;const MatterBodyId full[]{1,2};
    world.pushBody(1,{1,0,0});
    check(!world.parkFaceComponent(full,why)&&world.contains(1),"pending native force cannot disappear into a proxy");
    const MatterBodyId partial[]{1};
    check(!world.parkFaceComponent(partial,why)&&world.contains(1)&&!world.faceComponentParked(joint),"open component refused without disabling constraints");
    RigidComponent component(100,{{1,{.1,.1,.1},material},{2,{.1,.1,.1},material}});
    world.applyRigidState(2,{{.2,2,0},{},{0,2,0},{}});
    check(!component.collapse(world,0).admitted&&world.contains(1)&&world.contains(2),"nonrigid velocity cannot disappear in handoff");
    bool refused=false;
    check(world.runReversibleTrial([&]{try{const MatterBodyId ids[]{1,2};(void)world.parkFaceComponent(ids,why);}catch(const std::logic_error&){refused=true;}return true;}),"trial test");
    check(refused&&world.contains(1),"configuration mutation refused in native trial");
}
}
int main(){try{for(const auto p:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron,MaterialPreset::Ice})for(bool log:{false,true})transfer(p,log);geometryAndContinuation();preflight();}
    catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}}
