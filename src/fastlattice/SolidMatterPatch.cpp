#include "fastlattice/SolidMatterPatch.hpp"
#include "fracture/ConnectedComponents.hpp"
#include "material/MaterialCompiler.hpp"
#include "matter/BoxLattice.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <stdexcept>
#include <numeric>
#include <limits>

namespace banjo::fastlattice {
namespace {
bool finite(Vec3 v) { return std::isfinite(v.x) && std::isfinite(v.y) && std::isfinite(v.z); }
Vec3 vectorAt(const std::vector<double> &a, std::uint32_t i) {
    return {a[3*i],a[3*i+1],a[3*i+2]};
}
}

SolidMatterPatch::SolidMatterPatch(std::string source, Vec3 dimensions_m, double cell_m,
                                 const MaterialDefinition &material, Vec3 center_m,
                                 double timestep_fraction, double maximum_timestep_s,
                                 const std::vector<std::uint32_t> &fixed_source_nodes)
    : source_(std::move(source)), cell_m_(cell_m) {
    if (source_.empty() || source_.size()>160 || fixed_source_nodes.size()>1024 ||
        !finite(center_m) || !finite(dimensions_m) ||
        !(cell_m>0) || !std::isfinite(cell_m) ||
        !(timestep_fraction>0 && timestep_fraction<=.2) ||
        !(maximum_timestep_s>0) || !std::isfinite(maximum_timestep_s))
        throw std::invalid_argument("invalid constituent solid patch declaration");
    // Preflight before allocating. Whole dimensions are enforced by the lattice
    // generator, not rounded to make terrain/object resolutions appear equal.
    const Vec3 n=dimensions_m/cell_m;
    if (!(n.x>=2 && n.y>=2 && n.z>=2) || n.x*n.y*n.z>1024)
        throw std::invalid_argument("solid patch requires 2 or more cells per axis and at most 1024 cells");
    compiled_=withStrengthDerivedFailure(compileElasticLatticeReference(material,cell_m,2),material);
    asset_=generateBoxTileLattice({dimensions_m,cell_m,2},compiled_);
    ActiveMatter matter; matter.asset=&asset_; matter.material=compiled_;
    for (const auto &node:asset_.nodes) {
        const Vec3 at=center_m+node.local_position_m;
        const double mass=node.represented_volume_m3*compiled_.density_kg_m3;
        if (!(mass>0) || !std::isfinite(mass)) throw std::invalid_argument("invalid cell density/mass");
        matter.nodes.push_back({at,at,{},mass,{}});
        matter.reference_positions_world_m.push_back(at);
    }
    matter.bonds.resize(asset_.bonds.size());
    schedule_=buildLatticeSchedule(asset_);
    state_=buildLatticeState(matter,schedule_,center_m);
    // Nodes retain source numbering; only bonds are schedule-permuted. Keep
    // physical mass and all constitutive histories, declare only mobility.
    auto fixed=fixed_source_nodes;
    std::sort(fixed.begin(),fixed.end());
    if (std::adjacent_find(fixed.begin(),fixed.end())!=fixed.end()||
        (!fixed.empty()&&fixed.back()>=state_.node_count))
        throw std::invalid_argument("solid boundary nodes repeat or exceed the source patch");
    for (const auto node:fixed) state_.inv_mass[node]=0;
    timestep_s_=std::min(maximum_timestep_s,timestep_fraction*latticeStateSubstepLimit(state_));
    if (!(timestep_s_>0) || !std::isfinite(timestep_s_)) throw std::invalid_argument("invalid solid stable step");
    StepSettings<double> settings{};
    settings.dt=timestep_s_; settings.constraint_iterations=1;
    settings.bond_integrator=kBondVelocityVerlet; settings.audit_energy=1;
    backend_=makeCpuLatticeBackend(schedule_,Precision::Double);
    backend_->upload(state_,settings,{});
    source_nodes_.resize(state_.node_count);std::iota(source_nodes_.begin(),source_nodes_.end(),0);
    source_bonds_.resize(state_.bond_count);std::iota(source_bonds_.begin(),source_bonds_.end(),0);
}

SolidMatterPatch::~SolidMatterPatch()=default;

SolidMatterPatch::SolidMatterPatch(std::string source,double cell,const CompiledBrittleMaterial &compiled,
    ConstituentComponent part,std::vector<std::uint32_t> nodes,std::vector<std::uint32_t> bonds,
    std::uint64_t accepted_steps,double dt)
    :source_(std::move(source)),cell_m_(cell),timestep_s_(dt),asset_(std::move(part.asset)),compiled_(compiled),
    schedule_(std::move(part.schedule)),state_(std::move(part.state)),source_nodes_(std::move(nodes)),
    source_bonds_(std::move(bonds)),initial_steps_(accepted_steps) {
    StepSettings<double> settings{};settings.dt=dt;settings.constraint_iterations=1;
    settings.bond_integrator=kBondVelocityVerlet;settings.audit_energy=1;
    // The wrapper currently declares elastic/strength only. A different source
    // adapter must pass its exact solver settings, not infer plasticity by name.
    backend_=makeCpuLatticeBackend(schedule_,Precision::Double);backend_->upload(state_,settings,{});
    initial_=report(); // capture inherited mechanical state before accounts run
}

SolidPulseResult SolidMatterPatch::pulse(const std::vector<Vec3> &forces_n, unsigned steps,
                                      double maximum_positive_work_j) {
    if(!backend_)throw std::logic_error("constituent ownership was transferred; archived source cannot step");
    if(steps>std::numeric_limits<std::uint64_t>::max()-initial_steps_-backend_->status().total_steps)
        throw std::overflow_error("constituent accepted step counter overflow");
    if (forces_n.size()!=state_.node_count || steps>2048 ||
        maximum_positive_work_j<0 || !std::isfinite(maximum_positive_work_j) ||
        !std::all_of(forces_n.begin(),forces_n.end(),[](Vec3 f){return finite(f)&&length(f)<=1e8;}))
        throw std::invalid_argument("invalid bounded solid force pulse");
    const auto started=std::chrono::steady_clock::now();
    SolidPulseResult out;
    try {
    for (unsigned i=0;i<steps;++i) {
        const double previous=backend_->status().external_load.work_j;
        double positive=0;
        const bool accepted=backend_->runReversibleTrial([&]() {
            backend_->setExternalForces(forces_n,1);
            backend_->run({.max_steps=1});
            const double delta=backend_->status().external_load.work_j-previous;
            if (!std::isfinite(delta)) throw std::runtime_error("nonfinite solid source work");
            positive=std::max(0.,delta);
            return positive<=maximum_positive_work_j-out.positive_work_j;
        });
        if (!accepted) {out.work_budget_reached=true;break;}
        out.positive_work_j+=positive; positive_work_j_+=positive;
        ++out.accepted_steps;
    }
    } catch (...) {
        // Earlier accepted substeps stay committed. Keep the canonical cache
        // aligned with them if a later reversible trial fails exceptionally.
        SphereState<double> unused{};backend_->download(state_,unused);throw;
    }
    SphereState<double> unused{};
    backend_->download(state_,unused);
    out.state=report();
    out.wall_s=std::chrono::duration<double>(std::chrono::steady_clock::now()-started).count();
    return out;
}

SolidPatchReport SolidMatterPatch::report() const {
    if(!backend_) {auto result=retired_;result.owns_constituents=false;return result;}
    const auto &s=backend_->status();
    SolidPatchReport out;
    out.accepted_steps=initial_steps_+s.total_steps;
    out.time_s=static_cast<double>(out.accepted_steps)*timestep_s_;out.timestep_s=timestep_s_;
    out.positive_source_work_j=positive_work_j_;
    out.mass_kg=asset_.total_mass_kg;out.volume_m3=asset_.represented_volume_m3;
    out.kinetic_j=latticeStateKineticEnergy(state_);out.elastic_j=latticeStateElasticEnergy(state_);
    out.removed_bond_energy_j=s.removed_energy_j;out.source_work_j=s.external_load.work_j;
    out.integration_error_j=s.integration_numerical_energy_j;
    out.initial_mechanical_j=initial_.kinetic_j+initial_.elastic_j;
    out.energy_residual_j=out.kinetic_j+out.elastic_j+out.removed_bond_energy_j-out.initial_mechanical_j-out.source_work_j-out.integration_error_j;
    out.source_impulse_n_s=s.external_load.impulse_n_s;
    out.source_angular_impulse_kg_m2_s=s.external_load.angular_impulse_kg_m2_s;
    out.boundary_impulse_n_s=s.fixed_boundary.impulse_n_s;
    out.boundary_angular_impulse_kg_m2_s=s.fixed_boundary.angular_impulse_kg_m2_s;
    out.bond_roundoff_impulse_n_s=s.bond_kick_roundoff_impulse_n_s;
    out.bond_roundoff_angular_kg_m2_s=s.bond_kick_roundoff_angular_kg_m2_s;
    out.broken_bonds=s.broken_bonds;
    for (std::uint32_t i=0;i<state_.node_count;++i) {
        const Vec3 p=state_.mass[i]*vectorAt(state_.v,i);
        out.momentum_kg_m_s+=p;
        out.angular_momentum_kg_m2_s+=cross(state_.origin+vectorAt(state_.x0,i)+vectorAt(state_.u,i),p);
    }
    out.momentum_residual_kg_m_s=out.momentum_kg_m_s-initial_.momentum_kg_m_s-out.source_impulse_n_s-out.boundary_impulse_n_s-out.bond_roundoff_impulse_n_s;
    out.angular_residual_kg_m2_s=out.angular_momentum_kg_m2_s-initial_.angular_momentum_kg_m2_s-out.source_angular_impulse_kg_m2_s-out.boundary_angular_impulse_kg_m2_s-out.bond_roundoff_angular_kg_m2_s;
    return out;
}

std::vector<SolidComponent> SolidMatterPatch::components() const {
    ActiveMatter matter;matter.asset=&asset_;matter.material=compiled_;
    matter.nodes.resize(asset_.nodes.size());matter.bonds.resize(asset_.bonds.size());
    writeBackLatticeState(state_,schedule_,matter);
    std::vector<SolidComponent> out;
    for (const auto &component:findConnectedComponents(matter)) {
        SolidComponent part;
        for (const auto i:component.node_indices) {
            const auto &rest=asset_.nodes[i];const auto &now=matter.nodes[i];
            part.cells.push_back({source_,source_nodes_[i],rest.grid,cell_m_,rest.represented_volume_m3,
                                  rest.represented_volume_m3*compiled_.density_kg_m3,now.position_world_m,now.velocity_m_s});
            part.mass_kg+=rest.represented_volume_m3*compiled_.density_kg_m3;
            part.attached_to_boundary=part.attached_to_boundary||state_.inv_mass[i]==0;
        }
        out.push_back(std::move(part));
    }
    return out;
}

SolidPatchTransfer SolidMatterPatch::transferToComponents() {
    if(!backend_)throw std::logic_error("constituent source was already transferred");
    auto prepared=partitionConstituents(asset_,schedule_,state_);
    SolidPatchTransfer out;out.before=report();out.severed_interfaces=std::move(prepared.severed_interfaces);
    out.components.reserve(prepared.components.size());
    for(auto &part:prepared.components) {
        std::vector<std::uint32_t> nodes,bonds;
        for(const auto i:part.parent_nodes)nodes.push_back(source_nodes_[i]);
        for(const auto i:part.parent_bonds)bonds.push_back(source_bonds_[i]);
        out.components.push_back(std::unique_ptr<SolidMatterPatch>(new SolidMatterPatch(source_,cell_m_,compiled_,
            std::move(part),std::move(nodes),std::move(bonds),out.before.accepted_steps,timestep_s_)));
    }
    for(auto &edge:out.severed_interfaces) {
        edge.parent_bond=source_bonds_[edge.parent_bond];
        edge.parent_node_a=source_nodes_[edge.parent_node_a];edge.parent_node_b=source_nodes_[edge.parent_node_b];
    }
    // All allocations, topology/history checks and solver admission precede
    // retirement. Failure leaves the sole original owner available for retry.
    retired_=out.before;backend_.reset();return out;
}
} // namespace banjo::fastlattice
