#include "physics/CompliantAdvance.hpp"
#include "physics/MechanicalAccounting.hpp"
#include "material/MaterialCatalog.hpp"
#include "material/MaterialCompiler.hpp"
#include <cmath>
#include <functional>
#include <iostream>
#include <numbers>
#include <stdexcept>
#include <vector>

namespace {
using namespace banjo;
void require(bool condition,const char *message) { if (!condition) throw std::runtime_error(message); }
void near(double a,double b,double tolerance,const char *message) {
    if (!std::isfinite(a) || std::abs(a-b)>tolerance) throw std::runtime_error(message);
}
struct Fixture {
    LatticeAsset asset;
    ActiveMatter matter;
    Fixture() { asset.recipe.voxel_size_m=.02; matter.asset=&asset; }
};
CompliantAdvanceSettings settings(double error) {
    return {.step={.normal={2000,0},.maximum_compression_m=.1},
        .error={error,error,error,error,1},.initial_trial_dt_s=.05,.maximum_trial_dt_s=.05,.minimum_trial_dt_s=1e-9};
}
void analyticalElasticAccuracy() {
    const double omega=std::sqrt(200.0),duration=.2;
    double prior_error=0;
    unsigned prior_steps=0;
    for (double tolerance:{1e-2,1e-4}) {
        Fixture f;
        f.matter.nodes={{{-.5,0,0},{},{-.2,0,0},1,{}},{{.5,0,0},{},{.2,0,0},1,{}}};
        f.asset.bonds.push_back({.node_a=0,.node_b=1,.rest_length_m=1,.compliance=.01});
        f.matter.bonds.emplace_back();
        const auto before=measureMaterialMechanics(f.matter);
        const auto result=tryCompliantAdvance(f.matter,duration,settings(tolerance));
        require(result.step.balance.converged,"adaptive oscillator converges");
        require(result.maximum_accepted_error<=1 && result.rejected_segments>0,"error controller refines oscillator");
        near(result.advanced_time_s,duration,0,"full requested clock advanced");
        const double x=f.matter.nodes[1].position_world_m.x-f.matter.nodes[0].position_world_m.x-1;
        const double v=f.matter.nodes[1].velocity_m_s.x-f.matter.nodes[0].velocity_m_s.x;
        const double error=std::abs(v-.4*std::cos(omega*duration))+omega*std::abs(x-.4/omega*std::sin(omega*duration));
        if (prior_error>0) {
            require(error<prior_error/20 && result.accepted_segments>prior_steps,"tightening controller improves analytical trajectory");
            require(error<1e-4,"tight adaptive oscillator matches continuous oracle");
        }
        const auto after=measureMaterialMechanics(f.matter);
        near(after.mechanicalEnergy(),before.mechanicalEnergy(),1e-9,"adaptive oscillator energy");
        near(length(after.linear_momentum_kg_m_s-before.linear_momentum_kg_m_s),0,1e-9,"adaptive oscillator momentum");
        std::cout<<"oscillator tolerance="<<tolerance<<" error="<<error<<" segments="<<result.accepted_segments<<" trials="<<result.trials<<'\n';
        prior_error=error; prior_steps=result.accepted_segments;
    }
}
void analyticalDampedContact() {
    Fixture f; f.matter.nodes={{{0,0,0},{},{.3,-1,.2},2,{}}};
    const auto plane=makeSupportPlane({}, {0,1,0});
    auto s=settings(1e-4); s.step.solver.support=&plane;
    const double zeta=.25,omega=std::sqrt(1000.0),duration=.25;
    s.step.normal.compression_damping_kg_s=2*zeta*std::sqrt(4000.0);
    const double peak=std::acos(zeta)/(omega*std::sqrt(1-zeta*zeta));
    const double rebound=std::exp(-zeta*omega*peak),release=peak+std::numbers::pi/(2*omega);
    const auto result=tryCompliantAdvance(f.matter,duration,s);
    require(result.step.balance.converged,"adaptive damped contact converges");
    near(f.matter.nodes[0].velocity_m_s.y,rebound,1e-4,"adaptive continuous rebound");
    near(f.matter.nodes[0].position_world_m.y,rebound*(duration-release),1e-4,"adaptive contact duration and flight");
    near(result.step.contact_damping_loss_j,1-rebound*rebound,1e-4,"adaptive continuous damping work");
    near(result.step.balance.support_impulse_kg_m_s.y,2*(1+f.matter.nodes[0].velocity_m_s.y),1e-9,"adaptive support reaction");
    require(result.maximum_accepted_error<=1,"accepted contact error indicator bounded");
    std::cout<<"bounce vy="<<f.matter.nodes[0].velocity_m_s.y<<" loss="<<result.step.contact_damping_loss_j
        <<" segments="<<result.accepted_segments<<" rejected="<<result.rejected_segments<<'\n';
}
void loadedGravityLedger() {
    Fixture f; f.matter.nodes={{{0,0,0},{},{.3,0,.2},2,{}}};
    const Vec3 gravity{0,-9.81,0};
    const auto plane=makeSupportPlane({}, {0,1,0});
    auto s=settings(1e-4); s.step.solver.support=&plane;
    s.step.normal.compression_damping_kg_s=2*std::sqrt(4000.0);
    const auto before=measureMaterialMechanics(f.matter,gravity);
    const auto result=tryCompliantAdvance(f.matter,.5,s,gravity);
    require(result.step.balance.converged,"adaptive loaded contact converges");
    const double w=std::sqrt(1000.0),y=-.00981*(1-(1+w*.5)*std::exp(-w*.5));
    near(f.matter.nodes[0].position_world_m.y,y,1e-6,"adaptive loaded analytical position");
    const auto after=measureMaterialMechanics(f.matter,gravity);
    near(after.mechanicalEnergy()+result.step.contact_energy_after_j+result.step.contact_damping_loss_j,before.mechanicalEnergy(),1e-9,"adaptive gravity/contact work ledger");
    near(length(result.step.balance.angular_momentum_residual_kg_m2_s),0,1e-9,"piecewise gravity torque ledger");
}
void rollbackAndTinyRemainder() {
    Fixture f; f.matter.nodes={{{1,2,3},{},{.3,-.2,.4},2,{}}};
    CoupledSphereState sphere{{{4,2,3},{},{.1,.2,.3},{}},.5,3,.3};
    auto s=settings(1e-3); s.initial_trial_dt_s=s.maximum_trial_dt_s=.001; s.maximum_trials=4;
    const auto rejected=tryCompliantAdvance(f.matter,.004,s,{},&sphere);
    require(!rejected.step.balance.converged && rejected.failure==CompliantAdvanceFailure::TrialBudget && rejected.accepted_segments==1,"partial progress exhausts bounded trial budget");
    near(rejected.advanced_time_s,0,0,"failed requested interval publishes no time");
    near(length(f.matter.nodes[0].position_world_m-Vec3{1,2,3}),0,0,"failed interval retains material position");
    near(length(sphere.motion.center_of_mass_world_m-Vec3{4,2,3}),0,0,"failed interval retains finite body");
    s.maximum_trials=100; s.minimum_trial_dt_s=.0001;
    const double duration=.002+1e-12;
    const auto result=tryCompliantAdvance(f.matter,duration,s,{},&sphere);
    require(result.step.balance.converged && result.accepted_segments==3,"tiny final remainder is advanced");
    near(result.advanced_time_s,duration,0,"tiny remainder retained in published clock");
    near(length(f.matter.nodes[0].position_world_m-Vec3{1,2,3}-duration*Vec3{.3,-.2,.4}),0,1e-14,"full free-flight trajectory");
    Fixture oscillating; oscillating.matter.nodes={{{0,0,0},{},{0,-1,0},2,{}}};
    const auto plane=makeSupportPlane({}, {0,1,0});
    s.step.solver.support=&plane; s.initial_trial_dt_s=s.maximum_trial_dt_s=s.minimum_trial_dt_s=.01;
    s.error={1e-12,1e-12,1e-12,1e-12,1};
    const auto limit=tryCompliantAdvance(oscillating.matter,.02,s);
    require(limit.failure==CompliantAdvanceFailure::StepLimit && !limit.step.balance.converged,"error floor fails without accepting inaccurate step");
    near(oscillating.matter.nodes[0].velocity_m_s.y,-1,0,"error rejection retains velocity");
}
void finitePairFrameInvariance() {
    const Vec3 n=normalized(Vec3{-.8,.6,.1}),axis=normalized(Vec3{1,2,3}),offset{1,-2,.5},boost{.3,-.4,.2};
    const Quat rotation{std::cos(.31),axis.x*std::sin(.31),axis.y*std::sin(.31),axis.z*std::sin(.31)};
    Fixture a,b; a.matter.nodes={{{.5*n},{},{1.2,-.3,.2},1,{}}};
    b.matter.nodes={{{rotation.rotate(.5*n)+offset},{},rotation.rotate({1.2,-.3,.2})+boost,1,{}}};
    CoupledSphereState first{{},.5,2,.2}; first.motion.linear_velocity_m_s={-.2,.1,0};
    auto second=first; second.motion.center_of_mass_world_m=offset;
    second.motion.linear_velocity_m_s=rotation.rotate(first.motion.linear_velocity_m_s)+boost;
    second.motion.orientation_world=rotation;
    auto s=settings(1e-4); s.step.normal.compression_damping_kg_s=4;
    const auto x=tryCompliantAdvance(a.matter,.02,s,{},&first),y=tryCompliantAdvance(b.matter,.02,s,{},&second);
    require(x.step.balance.converged && y.step.balance.converged,"adaptive finite pair/frame converges");
    near(length(b.matter.nodes[0].position_world_m-offset-.02*boost-rotation.rotate(a.matter.nodes[0].position_world_m)),0,1e-7,"adaptive rotated boosted position");
    near(length(second.motion.linear_velocity_m_s-boost-rotation.rotate(first.motion.linear_velocity_m_s)),0,1e-7,"adaptive finite reaction frame");
    near(x.step.contact_damping_loss_j,y.step.contact_damping_loss_j,1e-7,"adaptive damping is frame independent");
}
void comparativeMaterialController() {
    for (const auto preset:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}) {
        const auto compiled=compileElasticLatticeReference(makeReferenceMaterial(preset,17),.12,2);
        const auto asset=generateSphereLattice({.25,.12,2,3},compiled);
        ActiveMatter matter; matter.asset=&asset; matter.material=compiled; matter.bonds.resize(asset.bonds.size());
        double minimum_y=0;
        for (const auto &node:asset.nodes) {
            matter.nodes.push_back({node.local_position_m,{},{.3,-1,.2},node.represented_volume_m3*compiled.density_kg_m3,{}});
            minimum_y=std::min(minimum_y,node.local_position_m.y);
        }
        const auto plane=makeSupportPlane({0,minimum_y-.00005,0},{0,1,0});
        auto s=settings(1e-3); s.error.reference_time_s=.001;
        s.step={.solver={.support=&plane},.normal={1e8,10000},.maximum_compression_m=.005};
        s.initial_trial_dt_s=s.maximum_trial_dt_s=.0002;
        const auto before=measureMaterialMechanics(matter);
        const auto result=tryCompliantAdvance(matter,.0002,s);
        if (!result.step.balance.converged) std::cerr<<"material failure="<<compliantAdvanceFailureName(result.failure)<<" raw="<<compliantFailureName(result.last_trial.failure)<<" error="<<result.last_error.normalized<<'\n';
        require(result.step.balance.converged && result.maximum_accepted_error<=1,"comparative material adaptive impact converges");
        require(result.step.maximum_compression_m>0 && result.step.contact_damping_loss_j>0,"comparative impact reaches compliant contact");
        const auto after=measureMaterialMechanics(matter);
        near(after.mechanicalEnergy()+result.step.contact_energy_after_j+result.step.contact_damping_loss_j,before.mechanicalEnergy(),1e-8*before.mechanicalEnergy(),"comparative adaptive energy");
        std::cout<<materialPresetName(preset)<<" segments="<<result.accepted_segments<<" rejected="<<result.rejected_segments<<" trials="<<result.trials<<" min_step="<<result.minimum_accepted_step_s<<'\n';
    }
}
void shallowSweptContact() {
    Fixture coarse,adaptive,reference;
    coarse.matter.nodes={{{-.25,.499,0},{},{100,0,0},1,{}}};
    adaptive.matter.nodes=reference.matter.nodes=coarse.matter.nodes;
    CoupledSphereState coarse_sphere{{},.5,2,.2};
    auto adaptive_sphere=coarse_sphere, reference_sphere=coarse_sphere;
    auto s=settings(1e-5);
    s.step.normal={1e6,100}; s.step.maximum_compression_m=.01;
    s.error={1e-6,1e-3,1e-6,1e-5,.001};
    s.initial_trial_dt_s=s.maximum_trial_dt_s=.01;
    const auto skipped=tryCompliantStep(coarse.matter,.01,s.step,{},&coarse_sphere);
    require(!skipped.balance.converged && skipped.failure==CompliantStepFailure::Geometry,
        "raw step rejects shallow contact buried between outside endpoints");
    near(coarse.matter.nodes[0].position_world_m.x,-.25,0,"swept rejection retains input state");
    coarse.matter.nodes[0].position_world_m.y=.5;
    const auto tangent=tryCompliantStep(coarse.matter,.01,s.step,{},&coarse_sphere);
    require(tangent.balance.converged,"exactly tangent free flight is not a buried contact");
    near(length(coarse_sphere.motion.linear_velocity_m_s),0,0,"tangent flight has no invented reaction");
    const auto result=tryCompliantAdvance(adaptive.matter,.01,s,{},&adaptive_sphere);
    require(result.step.balance.converged && result.rejected_segments>0,"adaptive sweep resolves grazing contact");
    for (unsigned i=0;i<20000;++i) {
        const auto step=tryCompliantStep(reference.matter,5e-7,s.step,{},&reference_sphere);
        require(step.balance.converged,"fine grazing reference converges");
    }
    require(length(adaptive_sphere.motion.linear_velocity_m_s)>.01,"grazing finite body receives a reaction");
    const double velocity_error=length(adaptive_sphere.motion.linear_velocity_m_s-reference_sphere.motion.linear_velocity_m_s);
    near(velocity_error,0,1e-4,"adaptive grazing reaction matches fine trajectory");
    near(length(adaptive.matter.nodes[0].position_world_m-reference.matter.nodes[0].position_world_m),0,1e-6,
        "adaptive grazing position matches fine trajectory");
    near(length(result.step.balance.linear_momentum_residual_kg_m_s),0,1e-9,"grazing momentum ledger");
    near(length(result.step.balance.angular_momentum_residual_kg_m2_s),0,1e-9,"grazing angular ledger");
    near(result.step.balance.energy_residual_j,0,1e-6,"grazing work ledger");
    std::cout<<"grazing reaction="<<length(adaptive_sphere.motion.linear_velocity_m_s)<<" velocity difference="<<velocity_error
        <<" segments="<<result.accepted_segments<<" rejected="<<result.rejected_segments<<'\n';
}
}
int main() {
    const std::vector<std::pair<const char*,std::function<void()>>> tests{
        {"adaptive analytical oscillator",analyticalElasticAccuracy},{"adaptive analytical bounce",analyticalDampedContact},
        {"adaptive loaded gravity ledger",loadedGravityLedger},{"rollback, bounds and exact remainder",rollbackAndTinyRemainder},
        {"adaptive finite pair reference frames",finitePairFrameInvariance},{"glass/oak/iron adaptive contact",comparativeMaterialController},
        {"shallow swept finite-sphere contact",shallowSweptContact}};
    unsigned failures=0;
    for (const auto &[name,test]:tests) {
        try {test();std::cout<<"[PASS] "<<name<<'\n';}
        catch(const std::exception &e) {++failures;std::cerr<<"[FAIL] "<<name<<": "<<e.what()<<'\n';}
    }
    return failures ? 1 : 0;
}
