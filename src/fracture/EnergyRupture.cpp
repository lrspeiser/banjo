#include "fracture/EnergyRupture.hpp"
#include "physics/MechanicalAccounting.hpp"
#include <algorithm>
#include <cmath>
#include <stdexcept>
namespace banjo {
namespace {
bool positive(double x){return std::isfinite(x)&&x>0;}
bool finite(Vec3 p){return std::isfinite(p.x)&&std::isfinite(p.y)&&std::isfinite(p.z);}
void validate(const ActiveMatter &m,std::span<const RuptureInterface> laws,double budget){
    if(!m.asset||m.bonds.size()!=m.asset->bonds.size()||laws.size()!=m.bonds.size()||m.bonds.size()>4096||m.nodes.size()>2048||
       m.nodes.empty()||m.nodes.size()!=m.asset->nodes.size()||!positive(m.asset->recipe.voxel_size_m)||!std::isfinite(budget)||budget<0)
        throw std::invalid_argument("invalid bounded rupture state or event budget");
    for(const auto &n:m.nodes)if(!positive(n.mass_kg)||!finite(n.position_world_m)||!finite(n.velocity_m_s)||!finite(n.spin_angular_velocity_rad_s))
        throw std::invalid_argument("rupture requires finite physical node states");
    for(std::size_t i=0;i<m.bonds.size();++i){
        const auto &b=m.asset->bonds[i];const auto &s=m.bonds[i];
        if(b.node_a>=m.nodes.size()||b.node_b>=m.nodes.size()||b.node_a==b.node_b)
            throw std::invalid_argument("invalid rupture endpoints");
        if(s.alive&&(s.damage!=0||s.failure_mode!=BondFailureMode::None))throw std::invalid_argument("partially damaged legacy bonds require explicit law migration");
        (void)compileRuptureThreshold(b,laws[i]);
    }
}
void requireUnfailedInitialState(const ActiveMatter &matter,std::span<const RuptureInterface> laws){
    for(std::size_t i=0;i<matter.bonds.size();++i)if(matter.bonds[i].alive){
        const auto &b=matter.asset->bonds[i];const auto threshold=compileRuptureThreshold(b,laws[i]);
        const double extension=length(matter.nodes[b.node_b].position_world_m-matter.nodes[b.node_a].position_world_m)-b.rest_length_m;
        if(extension>0&&.5*extension*extension/b.compliance>=threshold.work_j)
            throw std::invalid_argument("initial state already meets rupture threshold; resolve initial topology before advancing time");
    }
}

}
RuptureThreshold compileRuptureThreshold(const BondRest &bond,const RuptureInterface &law){
    if(!positive(bond.compliance)||!positive(bond.rest_length_m)||!positive(law.area_m2)||
       !positive(law.fracture_energy_j_m2)||!positive(law.minimum_tensile_strength_pa))
        throw std::invalid_argument("rupture requires positive finite compliance, length, area, toughness and strength");
    RuptureThreshold t;t.work_j=law.area_m2*law.fracture_energy_j_m2;
    t.extension_m=std::sqrt(2*bond.compliance*t.work_j);t.stress_pa=t.extension_m/(bond.compliance*law.area_m2);
    if(!positive(t.work_j)||!positive(t.extension_m)||!positive(t.stress_pa))throw std::invalid_argument("rupture threshold is not representable");
    if(t.stress_pa<law.minimum_tensile_strength_pa)throw std::invalid_argument("connector compliance, area and toughness would fail below declared strength; refine geometry or select another calibrated law");
    return t;
}
std::vector<RuptureInterface> compileMaterialRuptureInterfaces(const MaterialDefinition &material,const LatticeAsset &asset,std::span<const double> areas){
    if(material.model!=MaterialModel::BrittleBond)throw std::invalid_argument("material has no supported brittle rupture law");
    if(areas.size()!=asset.bonds.size()||areas.size()>4096)throw std::invalid_argument("one bounded geometric interface area is required per bond");
    std::vector<RuptureInterface> result;result.reserve(areas.size());
    for(std::size_t i=0;i<areas.size();++i){
        result.push_back({areas[i],material.fracture_energy_j_m2,material.tensile_strength_pa});
        (void)compileRuptureThreshold(asset.bonds[i],result.back());
    }
    return result;
}
RuptureResult tryEnergyRupture(ActiveMatter &matter,std::span<const RuptureInterface> laws,double budget){
    validate(matter,laws,budget);RuptureResult result;
    for(std::size_t i=0;i<matter.bonds.size();++i){
        if(!matter.bonds[i].alive)continue;
        const auto &bond=matter.asset->bonds[i];const auto threshold=compileRuptureThreshold(bond,laws[i]);
        const double extension=length(matter.nodes[bond.node_b].position_world_m-matter.nodes[bond.node_a].position_world_m)-bond.rest_length_m;
        const double energy=.5*extension*extension/bond.compliance;
        if(!std::isfinite(extension)||!std::isfinite(energy))throw std::invalid_argument("rupture extension/energy overflow");
        if(extension<=0||energy<threshold.work_j)continue;
        result.broken_bonds.push_back(static_cast<std::uint32_t>(i));
        result.removed_elastic_energy_j+=energy;result.fracture_work_j+=threshold.work_j;
        result.event_overshoot_loss_j+=energy-threshold.work_j;
    }
    if(!std::isfinite(result.removed_elastic_energy_j)||!std::isfinite(result.event_overshoot_loss_j))throw std::invalid_argument("rupture ledger overflow");
    if(result.event_overshoot_loss_j>budget)return result;
    // Prepare all allocations and verify balance before publishing any topology.
    auto candidate=matter;
    for(auto index:result.broken_bonds){auto &b=candidate.bonds[index];b.alive=false;b.damage=1;b.failure_mode=BondFailureMode::Tension;b.accumulated_lambda=0;}
    candidate.connectivity_dirty=candidate.connectivity_dirty||!result.broken_bonds.empty();
    const auto before=measureMaterialMechanics(matter),after=measureMaterialMechanics(candidate);
    result.balance_residual_j=after.elastic_energy_j+result.fracture_work_j+result.event_overshoot_loss_j-before.elastic_energy_j;
    if(!std::isfinite(result.balance_residual_j)||std::abs(result.balance_residual_j)>1e-12*std::max(1e-30,before.elastic_energy_j))
        throw std::runtime_error("rupture energy ledger failed closure");
    matter=std::move(candidate);result.accepted=true;return result;
}
RuptureStepResult tryEnergyRuptureStep(ActiveMatter &matter,double dt,std::span<const RuptureInterface> laws,double budget,
    const ConservativeStepSettings &settings,Vec3 gravity){
    validate(matter,laws,budget);
    requireUnfailedInitialState(matter,laws);
    if(settings.support)throw std::invalid_argument("rupture step support coupling is not yet supported");
    auto candidate=matter;RuptureStepResult result;
    result.elastic=tryConservativeStep(candidate,dt,gravity,nullptr,settings);
    if(!result.elastic.converged)return result;
    result.rupture=tryEnergyRupture(candidate,laws,budget);
    if(!result.rupture.accepted)return result;
    matter=std::move(candidate);result.accepted=true;return result;
}
CompliantRuptureStepResult tryCompliantRuptureStep(ActiveMatter &matter,CoupledSphereState &sphere,double dt,
    std::span<const RuptureInterface> laws,double budget,const CompliantStepSettings &settings,Vec3 gravity){
    validate(matter,laws,budget);
    requireUnfailedInitialState(matter,laws);
    if(settings.solver.support)throw std::invalid_argument("rupture step support coupling is not yet supported");
    auto candidate=matter;auto candidate_sphere=sphere;CompliantRuptureStepResult result;
    result.contact=tryCompliantStep(candidate,dt,settings,gravity,&candidate_sphere);
    if(!result.contact.balance.converged)return result;
    result.rupture=tryEnergyRupture(candidate,laws,budget);
    if(!result.rupture.accepted)return result;
    matter=std::move(candidate);sphere=candidate_sphere;result.accepted=true;return result;
}
}
