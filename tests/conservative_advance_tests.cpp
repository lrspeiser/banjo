#include "physics/ConservativeAdvance.hpp"
#include "physics/MechanicalAccounting.hpp"
#include "material/MaterialCatalog.hpp"
#include "material/MaterialCompiler.hpp"
#include <algorithm>
#include <cmath>
#include <functional>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <vector>

namespace {
using namespace banjo;
void require(bool condition, const char *message) { if (!condition) throw std::runtime_error(message); }
void near(double a, double b, double tolerance, const char *message) {
    if (!std::isfinite(a) || std::abs(a-b) > tolerance) throw std::runtime_error(message);
}
struct Point {
    LatticeAsset asset;
    ActiveMatter matter;
    Point(Vec3 position, Vec3 velocity, double mass = 2) {
        asset.recipe.voxel_size_m = .02; matter.asset = &asset;
        matter.nodes.push_back({position, {}, velocity, mass, {}});
    }
};
void pointPlanePhasesAndRestitution() {
    const auto plane = makeSupportPlane({}, {0,1,0});
    for (const double e : {0.0, .3, 1.0}) for (const double phase : {0.0, .001, .1, .25, .333, .5, .75, .99, 1.25}) {
        Point p({0,.1*phase,0}, {.3,-1,.2});
        const auto result = tryConservativeAdvance(p.matter, .1, {}, nullptr, {.step={.support=&plane}, .normal_restitution=e});
        require(result.balance.converged, "point/plane event advance converges");
        near(result.advanced_time_s,.1,0,"full interval is advanced");
        near(p.matter.nodes[0].position_world_m.y, phase < 1 ? e*.1*(1-phase) : .1*(phase-1), 1e-10,
             "impact phase does not stall the post-impact trajectory");
        near(p.matter.nodes[0].velocity_m_s.y, phase < 1 ? e : -1, 1e-10, "specified normal restitution");
        near(p.matter.nodes[0].position_world_m.x,.03,1e-12,"frictionless tangent motion");
        near(result.impact_loss_j,phase < 1 ? 1-e*e : 0,1e-9,"analytical restitution work");
        near(result.balance.normal_contact_loss_j,0,1e-9,"impact phase does not add numerical loss");
        near(result.balance.support_impulse_kg_m_s.y,phase < 1 ? 2*(1+e) : 0,1e-9,"analytical support impulse");
    }
}
void pointGravityAndImpactClock() {
    Point p({0,.03,0},{0,-1,0});
    const auto plane = makeSupportPlane({}, {0,1,0});
    const double hit = (std::sqrt(1.6)-1)/10, rest = .1-hit, rebound = std::sqrt(1.6);
    const auto result = tryConservativeAdvance(p.matter,.1,{0,-10,0},nullptr,{.step={.support=&plane}});
    require(result.balance.converged,"accelerated impact time converges");
    near(p.matter.nodes[0].position_world_m.y,rebound*rest-5*rest*rest,1e-9,"ballistic post-impact position");
    near(p.matter.nodes[0].velocity_m_s.y,rebound-10*rest,1e-9,"gravity acts over the complete clock");
    near(result.balance.energy_residual_j,0,1e-9,"gravity and impact energy balance");
}
void finiteSphereCrossingHasReaction() {
  for (const double e : {0.0,.3,1.0}) {
    Point p({-2,0,0},{40,0,0},1);
    CoupledSphereState sphere{{},.5,2,.2};
    const auto result = tryConservativeAdvance(p.matter,.1,{},&sphere,{.normal_restitution=e});
    require(result.balance.converged,"crossing interval resolves a finite-sphere impact");
    near(p.matter.nodes[0].velocity_m_s.x,40*(1-2*e)/3,1e-8,"two-body restitution point velocity");
    near(sphere.motion.linear_velocity_m_s.x,40*(1+e)/3,1e-8,"finite sphere receives reaction");
    near(p.matter.nodes[0].position_world_m.x,-.5+.0625*40*(1-2*e)/3,1e-8,"point continues after impact");
    near(sphere.motion.center_of_mass_world_m.x,.0625*40*(1+e)/3,1e-8,"sphere shares the post-impact clock");
    near(result.impact_loss_j,1600*(1-e*e)/3,1e-8,"analytical two-body impact loss");
    near(length(result.balance.linear_momentum_residual_kg_m_s),0,1e-8,"two-body interval momentum");
  }
}
void eventFrameAndInvalidState() {
    const Vec3 axis=normalized(Vec3{1,2,3}), offset{1,-2,.5}, boost{.2,0,.3};
    const Quat rotation{std::cos(.31),axis.x*std::sin(.31),axis.y*std::sin(.31),axis.z*std::sin(.31)};
    Point original({0,.03,0},{.3,-1,.2});
    Point moved(rotation.rotate(original.matter.nodes[0].position_world_m)+offset,
                rotation.rotate(original.matter.nodes[0].velocity_m_s+boost));
    const auto plane=makeSupportPlane({}, {0,1,0});
    const auto moved_plane=makeSupportPlane(offset,rotation.rotate({0,1,0}));
    const auto a=tryConservativeAdvance(original.matter,.1,{0,-10,0},nullptr,{.step={.support=&plane},.normal_restitution=.3});
    const auto b=tryConservativeAdvance(moved.matter,.1,rotation.rotate({0,-10,0}),nullptr,
        {.step={.support=&moved_plane},.normal_restitution=.3});
    require(a.balance.converged && b.balance.converged,"transformed accelerated event solves converge");
    near(length(moved.matter.nodes[0].position_world_m-offset-rotation.rotate(original.matter.nodes[0].position_world_m+.1*boost)),
        0,1e-9,"event trajectory rotates/translates with tangential boost");
    near(length(b.balance.support_impulse_kg_m_s-rotation.rotate(a.balance.support_impulse_kg_m_s)),0,1e-9,"event reaction rotates");
    near(b.impact_loss_j,a.impact_loss_j,1e-9,"event work is frame consistent");
    for (unsigned invalid=0;invalid<4;++invalid) {
        Point p({0,0,0},{0,-1,0});
        ConservativeAdvanceSettings settings{.step={.support=&plane}};
        if (invalid==0) p.matter.nodes[0].mass_kg=0;
        if (invalid==1) p.asset.recipe.voxel_size_m=std::numeric_limits<double>::quiet_NaN();
        if (invalid==2) settings.step.relative_energy_tolerance=-1;
        if (invalid==3) settings.step.support_half_tangent_m=std::numeric_limits<double>::quiet_NaN();
        bool rejected=false;
        try {(void)tryConservativeAdvance(p.matter,.1,{},nullptr,settings);}
        catch(const std::invalid_argument &) {rejected=true;}
        require(rejected,"invalid input rejects before impact work");
        near(p.matter.nodes[0].velocity_m_s.y,-1,0,"invalid input preserves velocity");
    }
}
void partialIntervalFailureRollsBack() {
    Point p({0,.05,0},{0,-1,0});
    const auto plane = makeSupportPlane({}, {0,1,0});
    const auto result = tryConservativeAdvance(p.matter,.1,{},nullptr,
        {.step={.support=&plane},.maximum_substeps=1});
    std::cout << "rollback trials=" << result.trials << " substeps=" << result.substeps
              << " converged=" << result.balance.converged << " time=" << result.advanced_time_s << '\n';
    require(!result.balance.converged && result.substeps == 1,"budget expires after an internal accepted arrival");
    near(result.advanced_time_s,0,0,"failed interval reports no published time");
    near(p.matter.nodes[0].position_world_m.y,.05,0,"whole interval position rollback");
    near(p.matter.nodes[0].velocity_m_s.y,-1,0,"whole interval velocity rollback");
}
void exactEndpointContactAndRest() {
    Point p({0,.1,0},{0,-1,0});
    const auto plane = makeSupportPlane({}, {0,1,0});
    const ConservativeAdvanceSettings settings{.step={.support=&plane}};
    require(tryConservativeAdvance(p.matter,.1,{},nullptr,settings).balance.converged,"arrival at interval boundary");
    require(tryConservativeAdvance(p.matter,.1,{},nullptr,settings).balance.converged,"boundary impact at next interval start");
    near(p.matter.nodes[0].position_world_m.y,.1,1e-10,"boundary impact has full outgoing flight");
    Point resting({0,0,0},{});
    const auto result = tryConservativeAdvance(resting.matter,.1,{0,-10,0},nullptr,settings);
    require(result.balance.converged,"resting support reaction converges");
    near(resting.matter.nodes[0].position_world_m.y,0,1e-12,"resting support gap");
    near(result.balance.support_impulse_kg_m_s.y,2,1e-10,"resting gravity reaction");
}

void departingContactReturnsAtClosingRoot() {
    Point p({0,5e-15,0},{.3,1,.2});
    const auto plane=makeSupportPlane({}, {0,1,0});
    const double hit=(1+std::sqrt(1+20*p.matter.nodes[0].position_world_m.y))/10;
    const double rest=.21-hit, outgoing=.3*(10*hit-1);
    const auto result=tryConservativeAdvance(p.matter,.21,{0,-10,0},nullptr,
        {.step={.support=&plane},.normal_restitution=.3});
    require(result.balance.converged,"departing near-contact returns at a closing root");
    near(p.matter.nodes[0].position_world_m.y,outgoing*rest-5*rest*rest,1e-10,"resolved departure and return position");
    near(p.matter.nodes[0].velocity_m_s.y,outgoing-10*rest,1e-10,"one return impact then gravity");
    require(result.impact_events==1,"departing contact is not an incoming event");
}

void sampledBoundaryRemainderAdvances() {
    for (const auto preset:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}) {
        const auto compiled=compileElasticLatticeReference(makeReferenceMaterial(preset,17),.04,2);
        const auto asset=generateSphereLattice({.25,.04,2,3},compiled);
        ActiveMatter matter;
        matter.asset=&asset; matter.material=compiled; matter.bonds.resize(asset.bonds.size());
        double minimum_y=0;
        for (const auto &node:asset.nodes) {
            matter.nodes.push_back({node.local_position_m,{}, {.3,-1,.2},node.represented_volume_m3*compiled.density_kg_m3,{}});
            minimum_y=std::min(minimum_y,node.local_position_m.y);
        }
        const auto before=measureMaterialMechanics(matter);
        const auto plane=makeSupportPlane({0,minimum_y-.001,0},{0,1,0});
        const auto result=tryConservativeAdvance(matter,.001,{},nullptr,{.step={.support=&plane}});
        require(result.balance.converged,"all materials finish a nominal boundary arrival");
        near(result.advanced_time_s,.001,0,"the entire boundary interval is published");
        near(result.remaining_time_s,0,0,"no tiny remainder is dropped");
        const auto after=measureMaterialMechanics(matter);
        near(after.mechanicalEnergy()+result.impact_loss_j+result.balance.normal_contact_loss_j,
            before.mechanicalEnergy(),1e-9*before.mechanicalEnergy(),"boundary interval independent energy ledger");
        near(length(after.linear_momentum_kg_m_s-before.linear_momentum_kg_m_s-result.balance.support_impulse_kg_m_s),
            0,1e-9*length(before.linear_momentum_kg_m_s),"boundary interval finite reaction");
        for (const auto &node:matter.nodes)
            require(signedDistanceToPlane(plane,node.position_world_m)>=-1e-10,"boundary interval has no unresolved penetration");
        std::cout<<"boundary material="<<materialPresetName(preset)<<" substeps="<<result.substeps<<" last_dt_s="
                 <<result.last_trial_dt_s<<" energy_residual_j="<<result.balance.energy_residual_j<<'\n';
    }
}

void comparativeElasticCompilerAndImpacts() {
    for (const auto preset : {MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}) {
        const auto definition=makeReferenceMaterial(preset,17);
        const auto declared_model=definition.model;
        const auto compiled=compileElasticLatticeReference(definition,.12,2);
        require(definition.model==declared_model,"elastic comparison does not relabel the material model");
        require(std::isinf(compiled.damage_start_stretch) && std::isinf(compiled.damage_end_stretch) &&
                std::isinf(compiled.compression_damage_start_strain) && std::isinf(compiled.shear_damage_start_strain),
                "elastic comparison does not enable substance-specific fracture");
        near(compiled.density_kg_m3,definition.density_kg_m3,0,"catalog density is retained");
        const auto asset=generateSphereLattice({.25,.12,2,3},compiled);
        ActiveMatter matter;
        matter.asset=&asset;matter.material=compiled;matter.bonds.resize(asset.bonds.size());
        double minimum_y=0;
        for (const auto &node:asset.nodes) {
            matter.nodes.push_back({node.local_position_m,{}, {.3,-1,.2},node.represented_volume_m3*compiled.density_kg_m3,{}});
            minimum_y=std::min(minimum_y,node.local_position_m.y);
        }
        const auto before=measureMaterialMechanics(matter);
        near(before.mass_kg,asset.represented_volume_m3*definition.density_kg_m3,1e-9,"material-derived comparative mass");
        const auto plane=makeSupportPlane({0,minimum_y-.001,0},{0,1,0});
        const auto result=tryConservativeAdvance(matter,.002,{},nullptr,{.step={.support=&plane}});
        require(result.balance.converged,"all retained materials finish the event impact");
        require(result.impact_events>1 && result.substeps>2,"case exercises repeated elastic contacts and event location");
        const auto after=measureMaterialMechanics(matter);
        const double energy_scale=std::max(1.0,before.mechanicalEnergy());
        near(after.mechanicalEnergy()+result.impact_loss_j+result.balance.normal_contact_loss_j,
             before.mechanicalEnergy(),1e-9*energy_scale,"independent comparative energy ledger");
        const double momentum_scale=std::max({1.0,length(before.linear_momentum_kg_m_s),length(result.balance.support_impulse_kg_m_s)});
        near(length(after.linear_momentum_kg_m_s-before.linear_momentum_kg_m_s-result.balance.support_impulse_kg_m_s),
             0,1e-9*momentum_scale,"comparative support reaction");
        near(result.impact_loss_j,0,1e-9*energy_scale,"unit-restitution event loss stays numerical");
        near(result.balance.normal_contact_loss_j,0,1e-9*energy_scale,"old impact-phase loss is absent");
        std::cout<<"comparison material="<<materialPresetName(preset)<<" mass_kg="<<before.mass_kg
                 <<" events="<<result.impact_events<<" trials="<<result.trials<<" energy_residual_j="<<result.balance.energy_residual_j<<'\n';
    }
}
}
int main() {
    const std::vector<std::pair<const char *,std::function<void()>>> tests{
        {"point/plane phase and restitution",pointPlanePhasesAndRestitution},
        {"gravity and impact clock",pointGravityAndImpactClock},
        {"finite sphere crossing and reaction",finiteSphereCrossingHasReaction},
        {"partial interval rollback",partialIntervalFailureRollsBack},
        {"boundary impact and resting support",exactEndpointContactAndRest},
        {"departing contact returns at closing root",departingContactReturnsAtClosingRoot},
        {"glass/oak/iron boundary remainder",sampledBoundaryRemainderAdvances},
        {"event frame and invalid state",eventFrameAndInvalidState},
        {"glass/oak/iron elastic reference and repeated impact",comparativeElasticCompilerAndImpacts}};
    unsigned failures=0;
    for (const auto &[name,test]:tests) {
        try {test();std::cout<<"[PASS] "<<name<<'\n';}
        catch(const std::exception &e) {++failures;std::cerr<<"[FAIL] "<<name<<": "<<e.what()<<'\n';}
    }
    return failures ? 1 : 0;
}
