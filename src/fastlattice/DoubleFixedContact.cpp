#include "fastlattice/DoubleFixedContact.hpp"
#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>
#include <type_traits>

namespace banjo::fastlattice {
namespace {
MechanicalTotals total(const std::vector<RigidMechanicalState> &bodies){
    MechanicalTotals out;for(const auto &body:bodies)out+=measureRigidMechanics(body);return out;
}
void require(bool ok,const char *why){if(!ok)throw std::invalid_argument(why);}
}
DoubleFixedManifoldTransfer applyDoubleFixedLocalSurfaceManifold(DoubleFixedSource &source,LatticeBackend &target,
    std::span<const MaterialSurfaceWitness> witnesses,const MaterialContactRegionSettings &settings,std::uint32_t striker) {
    DoubleFixedManifoldTransfer out;out.target_step=target.status().total_steps;out.horizon_s=target.externalContactTimestep();
    if(witnesses.empty())return out;
    require(witnesses.size()<=64,"double manifold witness budget exceeded");
    std::vector<std::uint32_t> ids;
    for(const auto &w:witnesses){out.regions.push_back(target.externalContactRegion(w.seed,settings));
        for(const auto id:out.regions.back().nodes)ids.push_back(id);}
    std::sort(ids.begin(),ids.end());ids.erase(std::unique(ids.begin(),ids.end()),ids.end());
    require(ids.size()<=64,"double manifold material union exceeds 64 nodes");
    std::vector<ActiveNodeState> nodes;for(const auto id:ids)nodes.push_back(target.externalContactPoint(id));
    std::vector<FixedSurfaceContact> contacts;
    for(std::size_t k=0;k<witnesses.size();++k){const auto &w=witnesses[k];FixedSurfaceContact c;
        c.surface_world_m=w.surface_world_m;c.normal_world=w.normal_world;c.gap_m=w.gap_m;c.settings=w.settings;
        for(const auto id:out.regions[k].nodes)c.nodes.push_back(static_cast<std::uint32_t>(std::lower_bound(ids.begin(),ids.end(),id)-ids.begin()));
        contacts.push_back(std::move(c));}
    const auto before=source.bodies();
    out.contact=evaluateFixedSurfaceManifold(nodes,contacts,before,source.links(),striker,out.horizon_s);
    if(!out.contact.active_contacts)return out;
    auto candidate=source;candidate.adoptContact(out.contact.bodies);
    std::vector<ExternalPointVelocity> updates;
    for(std::size_t k=0;k<ids.size();++k)updates.push_back({ids[k],nodes[k],out.contact.node_velocities_m_s[k]});
    const auto delta=target.validateExternalPointVelocities(updates);
    const auto a=total(before),b=total(candidate.bodies());
    out.source_work_j=b.kinetic_energy_j-a.kinetic_energy_j;
    out.source_roundoff_energy_j=out.source_work_j-
        (out.contact.kinetic_change_j-delta.work_j);
    out.work_residual_j=out.source_work_j+delta.work_j+out.contact.dissipated_energy_j+out.contact.reconciliation_loss_j;
    out.momentum_residual_n_s=b.linear_momentum_kg_m_s-a.linear_momentum_kg_m_s+delta.impulse_n_s;
    out.angular_residual_kg_m2_s=b.angular_momentum_kg_m2_s-a.angular_momentum_kg_m2_s+delta.angular_impulse_kg_m2_s-
        out.contact.geometry_couple_kg_m2_s;
    require(std::isfinite(out.work_residual_j)&&std::isfinite(out.source_roundoff_energy_j)&&
        std::abs(out.work_residual_j)<=1e-10&&length(out.momentum_residual_n_s)<=1e-9&&
        length(out.angular_residual_kg_m2_s)<=1e-9,"double source/target transfer failed full impulse/work preflight");
    // Every allocation, source admissibility and target ledger preflight has
    // finished. Target commits atomically; moving its prepared source is no-throw.
    static_assert(std::is_nothrow_move_assignable_v<DoubleFixedSource>);
    out.target=target.applyExternalPointVelocities(updates);source=std::move(candidate);return out;
}
bool runDoubleFixedTargetTrial(DoubleFixedSource &source,LatticeBackend &target,const std::function<bool()> &trial){
    require(static_cast<bool>(trial),"empty double source/target trial");auto saved=source;
    try{const bool accepted=target.runReversibleTrial(trial);if(!accepted)source=std::move(saved);return accepted;}
    catch(...){source=std::move(saved);throw;}
}
DoubleFixedStep advanceDoubleFixedTargetStep(DoubleFixedSource &source,LatticeBackend &target,double dt,
    const std::function<DoubleFixedManifoldTransfer(double)> &contact,std::span<const DoubleSourceWrench> wrenches){
    require(std::isfinite(dt)&&dt>0&&dt<=1&&static_cast<bool>(contact),"invalid double coupled step/callback");
    require(wrenches.size()<=256,"double source wrench budget exceeded");
    const auto members=source.bodies();
    for(const auto &w:wrenches)require(w.member<members.size()&&std::isfinite(length(w.point_member_local_m))&&
        std::isfinite(length(w.force_world_n))&&std::isfinite(length(w.free_torque_world_n_m)),"invalid double source wrench");
    DoubleFixedStep out;out.interval_s=dt;out.source_loads.reserve(2*wrenches.size());out.contacts.reserve(2);
    const bool accepted=runDoubleFixedTargetTrial(source,target,[&]{
        const auto steps=source.steps(),target_steps=target.status().total_steps;
        const auto source_time=source.elapsedTime(),target_time=target.externalContactElapsedTime();
        const double tolerance=16*std::numeric_limits<double>::epsilon()*std::max({source_time+dt,target_time+dt,dt});
        require(std::abs(source_time-target_time)<=tolerance&&source_time+dt>source_time&&target_time+dt>target_time,
            "double source/target absolute clocks do not agree or cannot advance");
        target.advanceCoupledContactStep(dt,[&](ExternalContactPhase phase){
            // Source and target force kicks surround the same actual drift.
            // Local application points follow current member geometry. All
            // signed actuator work and fixing reactions remain in receipts.
            for(const auto &w:wrenches){const auto body=source.bodies()[w.member].motion;
                const auto point=body.center_of_mass_world_m+body.orientation_world.rotate(w.point_member_local_m);
                out.source_loads.push_back(source.applyImpulse(w.member,point,.5*dt*w.force_world_n,.5*dt*w.free_torque_world_n_m));}
            const auto at=source.steps();const auto clock=source.elapsedTime();
            auto receipt=contact(dt);
            require(source.steps()==at&&source.elapsedTime()==clock,"double contact callback advanced source time");
            out.contacts.push_back(std::move(receipt));
            if(phase==ExternalContactPhase::BeforeDrift)out.free_drift=source.advanceFree(dt);
        });
        require(source.steps()==steps+1&&target.status().total_steps==target_steps+1&&
            std::abs(source.elapsedTime()-source_time-dt)<=tolerance&&
            std::abs(target.externalContactElapsedTime()-target_time-dt)<=tolerance,
            "double coupled step lost shared physical time");return true;
    });
    if(!accepted)throw std::logic_error("double coupled step unexpectedly refused commit");return out;
}
} // namespace banjo::fastlattice
