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
namespace {
DoubleFixedStep advanceOwnedDoubleFixedTargetStep(DoubleFixedSource &source,LatticeBackend &target,double dt,
    const std::function<DoubleFixedManifoldTransfer(double)> &contact,std::span<const DoubleSourceWrench> wrenches){
    require(std::isfinite(dt)&&dt>0&&dt<=1&&static_cast<bool>(contact),"invalid double coupled step/callback");
    require(wrenches.size()<=256,"double source wrench budget exceeded");
    const auto members=source.bodies();
    for(const auto &w:wrenches)require(w.member<members.size()&&std::isfinite(length(w.point_member_local_m))&&
        std::isfinite(length(w.force_world_n))&&std::isfinite(length(w.free_torque_world_n_m)),"invalid double source wrench");
    DoubleFixedStep out;out.interval_s=dt;out.source_loads.reserve(2*wrenches.size());out.contacts.reserve(2);
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
        "double coupled step lost shared physical time");
    return out;
}
}
DoubleFixedStep advanceDoubleFixedTargetStep(DoubleFixedSource &source,LatticeBackend &target,double dt,
    const std::function<DoubleFixedManifoldTransfer(double)> &contact,std::span<const DoubleSourceWrench> wrenches){
    DoubleFixedStep out;
    if(!runDoubleFixedTargetTrial(source,target,[&]{out=advanceOwnedDoubleFixedTargetStep(source,target,dt,contact,wrenches);return true;}))
        throw std::logic_error("double coupled step unexpectedly refused commit");
    return out;
}
namespace {
void addFixings(DoubleContactStepAudit &out,std::span<const FixedVelocityImpulse> reactions) {
    if(reactions.empty())return;
    if(out.fixing_reactions.empty())out.fixing_reactions.resize(reactions.size());
    require(out.fixing_reactions.size()==reactions.size(),"double accuracy fixing identity changed");
    for(std::size_t i=0;i<reactions.size();++i){auto &a=out.fixing_reactions[i];const auto &b=reactions[i];
        a.impulse_on_b_n_s+=b.impulse_on_b_n_s;a.free_angular_impulse_on_b_kg_m2_s+=b.free_angular_impulse_on_b_kg_m2_s;a.work_j+=b.work_j;}
}
void validateDoubleAudit(const DoubleContactStepAudit &a) {
    for(double v:{a.contact_loss_j,a.reconciliation_loss_j,a.source_roundoff_energy_j,a.source_drift_energy_j,a.source_load_work_j})
        require(std::isfinite(v),"double accuracy energy overflow");
    for(Vec3 v:{a.contact_impulse_residual_n_s,a.contact_angular_residual_kg_m2_s,a.geometry_couple_kg_m2_s,
        a.drift_impulse_residual_n_s,a.drift_angular_residual_kg_m2_s,a.source_load_impulse_n_s,a.source_load_angular_kg_m2_s})
        require(std::isfinite(length(v)),"double accuracy impulse overflow");
    require(a.contact_loss_j>=0&&a.reconciliation_loss_j>=0,"double accuracy negative dissipation");
    for(const auto &r:a.fixing_reactions)require(std::isfinite(length(r.impulse_on_b_n_s))&&
        std::isfinite(length(r.free_angular_impulse_on_b_kg_m2_s))&&std::isfinite(r.work_j),"double accuracy fixing overflow");
}
DoubleContactStepAudit stepAudit(const DoubleFixedStep &step,std::size_t fixing_count) {
    DoubleContactStepAudit out;out.fixing_reactions.resize(fixing_count);out.source_drift_energy_j=step.free_drift.numerical_energy_j;
    out.drift_impulse_residual_n_s=step.free_drift.momentum_residual_n_s;out.drift_angular_residual_kg_m2_s=step.free_drift.angular_residual_kg_m2_s;
    for(const auto &r:step.contacts){out.contact_loss_j+=r.contact.dissipated_energy_j;out.reconciliation_loss_j+=r.contact.reconciliation_loss_j;
        out.source_roundoff_energy_j+=r.source_roundoff_energy_j;out.contact_impulse_residual_n_s+=r.momentum_residual_n_s;
        out.contact_angular_residual_kg_m2_s+=r.angular_residual_kg_m2_s;out.geometry_couple_kg_m2_s+=r.contact.geometry_couple_kg_m2_s;
        out.active_manifolds+=r.contact.active_contacts?1:0;addFixings(out,r.contact.reconciliation);addFixings(out,r.contact.contact_reactions);}
    for(const auto &r:step.source_loads){out.source_load_work_j+=r.aggregate.work_j;out.source_load_impulse_n_s+=r.aggregate.impulse_n_s;
        out.source_load_angular_kg_m2_s+=r.aggregate.angular_impulse_origin_kg_m2_s;addFixings(out,r.fixing.reactions);}
    validateDoubleAudit(out);return out;
}
DoubleContactStepAudit addDoubleAudit(DoubleContactStepAudit a,const DoubleContactStepAudit &b) {
    a.contact_loss_j+=b.contact_loss_j;a.reconciliation_loss_j+=b.reconciliation_loss_j;
    a.source_roundoff_energy_j+=b.source_roundoff_energy_j;a.source_drift_energy_j+=b.source_drift_energy_j;a.source_load_work_j+=b.source_load_work_j;
    a.contact_impulse_residual_n_s+=b.contact_impulse_residual_n_s;a.contact_angular_residual_kg_m2_s+=b.contact_angular_residual_kg_m2_s;
    a.geometry_couple_kg_m2_s+=b.geometry_couple_kg_m2_s;a.drift_impulse_residual_n_s+=b.drift_impulse_residual_n_s;
    a.drift_angular_residual_kg_m2_s+=b.drift_angular_residual_kg_m2_s;a.source_load_impulse_n_s+=b.source_load_impulse_n_s;
    a.source_load_angular_kg_m2_s+=b.source_load_angular_kg_m2_s;
    require(b.active_manifolds<=std::numeric_limits<std::uint64_t>::max()-a.active_manifolds,"double accuracy count overflow");
    a.active_manifolds+=b.active_manifolds;addFixings(a,b.fixing_reactions);validateDoubleAudit(a);return a;
}
struct DoubleAccuracySnapshot {
    LatticeState material;RunStatus status;std::vector<RigidSnapshot> source;
    Vec3 spin_momentum_kg_m2_s;DoubleContactStepAudit audit;
};
DoubleAccuracySnapshot doubleAccuracySnapshot(const DoubleFixedSource &source,LatticeBackend &target,DoubleContactStepAudit audit) {
    DoubleAccuracySnapshot out;SphereState<double> sphere;target.download(out.material,sphere);out.status=target.status();
    for(const auto &b:source.bodies())out.source.push_back(b.motion);
    out.spin_momentum_kg_m2_s=source.state().spin_momentum_world_kg_m2_s;out.audit=std::move(audit);return out;
}
double doubleAccuracyError(const DoubleAccuracySnapshot &a,const DoubleAccuracySnapshot &b,
    const ContactAccuracySettings &s,DoubleContactAccuracyResult &out) {
    ContactAccuracyComparison c{s,out};c.materialState(a.material,b.material);c.sources(a.source,b.source,"source");c.materialLedgers(a.status,b.status);
    c.metric="source spin momentum";c.vector(a.spin_momentum_kg_m2_s,b.spin_momentum_kg_m2_s,s.angular_impulse_kg_m2_s);
    const auto &x=a.audit,&y=b.audit;
    c.metric="contact dissipation";c.scalar(x.contact_loss_j,y.contact_loss_j,s.energy_j);c.scalar(x.reconciliation_loss_j,y.reconciliation_loss_j,s.energy_j);
    c.metric="source contact correction";c.scalar(x.source_roundoff_energy_j,y.source_roundoff_energy_j,s.energy_j);
    c.vector(x.contact_impulse_residual_n_s,y.contact_impulse_residual_n_s,s.impulse_n_s);
    c.vector(x.contact_angular_residual_kg_m2_s,y.contact_angular_residual_kg_m2_s,s.angular_impulse_kg_m2_s);
    c.vector(x.geometry_couple_kg_m2_s,y.geometry_couple_kg_m2_s,s.angular_impulse_kg_m2_s);
    c.metric="source free drift";c.scalar(x.source_drift_energy_j,y.source_drift_energy_j,s.energy_j);
    c.vector(x.drift_impulse_residual_n_s,y.drift_impulse_residual_n_s,s.impulse_n_s);
    c.vector(x.drift_angular_residual_kg_m2_s,y.drift_angular_residual_kg_m2_s,s.angular_impulse_kg_m2_s);
    c.metric="source external transfer";c.scalar(x.source_load_work_j,y.source_load_work_j,s.energy_j);
    c.vector(x.source_load_impulse_n_s,y.source_load_impulse_n_s,s.impulse_n_s);
    c.vector(x.source_load_angular_kg_m2_s,y.source_load_angular_kg_m2_s,s.angular_impulse_kg_m2_s);
    require(x.fixing_reactions.size()==y.fixing_reactions.size(),"double accuracy fixing dimensions changed");
    c.metric="source fixing reactions";
    for(std::size_t i=0;i<x.fixing_reactions.size();++i){const auto &p=x.fixing_reactions[i],&q=y.fixing_reactions[i];
        c.vector(p.impulse_on_b_n_s,q.impulse_on_b_n_s,s.impulse_n_s);
        c.vector(p.free_angular_impulse_on_b_kg_m2_s,q.free_angular_impulse_on_b_kg_m2_s,s.angular_impulse_kg_m2_s);
        c.scalar(p.work_j,q.work_j,s.energy_j);}
    return c.error;
}
}
DoubleContactAccuracyResult advanceDoubleFixedTargetControlled(DoubleFixedSource &source,LatticeBackend &target,
    double interval,const ContactAccuracySettings &settings,const std::function<DoubleFixedManifoldTransfer(double)> &contact,
    std::span<const DoubleSourceWrench> wrenches) {
    const auto maximum=target.externalContactTimestep(),start_time=target.externalContactElapsedTime();
    require(contact&&std::isfinite(interval)&&interval>0&&interval<=maximum&&settings.maximum_halvings<=20,
        "invalid double controlled interval/callback/refinement budget");
    for(double v:{settings.minimum_step_s,settings.position_m,settings.velocity_m_s,settings.orientation_rad,
        settings.angular_velocity_rad_s,settings.damage_fraction,settings.history_strain,settings.plastic_extension_m,
        settings.plastic_strain,settings.energy_j,settings.impulse_n_s,settings.angular_impulse_kg_m2_s})
        require(std::isfinite(v)&&v>0,"double accuracy bounds must be finite and positive");
    require(interval*.5>=settings.minimum_step_s&&std::isfinite(start_time+interval)&&start_time+interval>start_time,
        "double controlled interval cannot advance within its minimum step");
    require(source.steps()<=std::numeric_limits<std::uint64_t>::max()-2,"double accuracy source step overflow");
    LatticeState initial;SphereState<double> sphere;target.download(initial,sphere);
    require(!initial.u.empty()&&initial.u.size()<=3U*1024U&&initial.alive.size()<=65536U,"double accuracy material budget exceeded");
    DoubleContactAccuracyResult out;
    const auto fixing_count=source.links().size();
    const auto step=[&](double dt){return stepAudit(advanceOwnedDoubleFixedTargetStep(source,target,dt,contact,wrenches),fixing_count);};
    for(unsigned round=0;round<=settings.maximum_halvings;++round){
        ++out.attempted_intervals;DoubleAccuracySnapshot full;
        (void)runDoubleFixedTargetTrial(source,target,[&]{full=doubleAccuracySnapshot(source,target,step(interval));return false;});
        const bool accepted=runDoubleFixedTargetTrial(source,target,[&]{
            auto audit=step(interval*.5);audit=addDoubleAudit(std::move(audit),step(interval*.5));
            const auto fine=doubleAccuracySnapshot(source,target,audit);
            out.topology_agrees=full.material.alive==fine.material.alive&&full.material.failure_mode==fine.material.failure_mode;
            out.compared_interval_s=interval;out.normalized_error=doubleAccuracyError(full,fine,settings,out);
            if(!out.topology_agrees||out.normalized_error>1)return false;
            require(std::abs(target.externalContactElapsedTime()-start_time-interval)<=
                16*std::numeric_limits<double>::epsilon()*std::max(start_time+interval,interval),"double accuracy lost elapsed time");
            out.accepted_audit=std::move(audit);return true;
        });
        if(accepted){out.accepted=true;out.accepted_interval_s=interval;
            out.suggested_interval_s=std::min(maximum,out.normalized_error<.125?2*interval:interval);return out;}
        ++out.rejected_intervals;
        if(round==settings.maximum_halvings||interval*.25<settings.minimum_step_s)break;
        interval*=.5;
    }
    out.suggested_interval_s=interval;return out;
}
} // namespace banjo::fastlattice
