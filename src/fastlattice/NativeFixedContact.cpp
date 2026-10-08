#include "fastlattice/NativeFixedContact.hpp"
#include <cmath>
#include <algorithm>
#include <limits>

namespace banjo::fastlattice {
namespace {
void validateAudit(const NativeContactStepAudit &a,bool callback=false) {
    for(double v:{a.contact_loss_j,a.reconciliation_loss_j,a.source_numerical_energy_j,a.native_step_energy_j})
        if(!std::isfinite(v))throw std::invalid_argument("contact accuracy audit contains nonfinite energy");
    for(Vec3 v:{a.source_numerical_impulse_n_s,a.source_numerical_angular_kg_m2_s,a.geometry_couple_kg_m2_s,
                a.native_step_impulse_n_s,a.native_step_angular_kg_m2_s})
        if(!std::isfinite(length(v)))throw std::invalid_argument("contact accuracy audit contains nonfinite impulse");
    if(a.contact_loss_j<0||a.reconciliation_loss_j<0)
        throw std::invalid_argument("contact accuracy audit contains negative dissipation");
    if(callback&&(a.native_step_energy_j!=0||length(a.native_step_impulse_n_s)!=0||length(a.native_step_angular_kg_m2_s)!=0))
        throw std::invalid_argument("contact callback cannot supply native stepping measurements");
}
NativeContactStepAudit addAudit(NativeContactStepAudit a,const NativeContactStepAudit &b) {
    a.contact_loss_j+=b.contact_loss_j;a.reconciliation_loss_j+=b.reconciliation_loss_j;
    a.source_numerical_energy_j+=b.source_numerical_energy_j;
    a.source_numerical_impulse_n_s+=b.source_numerical_impulse_n_s;
    a.source_numerical_angular_kg_m2_s+=b.source_numerical_angular_kg_m2_s;
    a.geometry_couple_kg_m2_s+=b.geometry_couple_kg_m2_s;
    a.native_step_energy_j+=b.native_step_energy_j;
    a.native_step_impulse_n_s+=b.native_step_impulse_n_s;
    a.native_step_angular_kg_m2_s+=b.native_step_angular_kg_m2_s;
    if(b.active_manifolds>std::numeric_limits<std::uint64_t>::max()-a.active_manifolds)
        throw std::overflow_error("contact accuracy receipt count overflow");
    a.active_manifolds+=b.active_manifolds;validateAudit(a);return a;
}
struct AccuracySnapshot {
    LatticeState material;
    RunStatus status;
    std::vector<RigidSnapshot> native;
    NativeContactStepAudit audit;
};
AccuracySnapshot accuracySnapshot(JoltWorld &world,LatticeBackend &target,
    const std::vector<MatterBodyId> &ids,const NativeContactStepAudit &audit) {
    if(world.activeBodyIds()!=ids)throw std::logic_error("contact accuracy trial changed native participation");
    AccuracySnapshot out;SphereState<double> sphere;target.download(out.material,sphere);
    out.status=target.status();out.audit=audit;
    for(auto id:ids)out.native.push_back(world.snapshot(id));return out;
}
double accuracyError(const AccuracySnapshot &a,const AccuracySnapshot &b,const NativeContactAccuracySettings &s,NativeContactAccuracyResult &result) {
    ContactAccuracyComparison c{s,result};c.materialState(a.material,b.material);c.sources(a.native,b.native,"native");c.materialLedgers(a.status,b.status);
    const auto &p=a.audit,&q=b.audit;
    c.metric="contact dissipation";
    c.scalar(p.contact_loss_j,q.contact_loss_j,s.energy_j);
    c.scalar(p.reconciliation_loss_j,q.reconciliation_loss_j,s.energy_j);
    c.metric="source contact correction";c.scalar(p.source_numerical_energy_j,q.source_numerical_energy_j,s.energy_j);
    c.metric="native step energy";c.scalar(p.native_step_energy_j,q.native_step_energy_j,s.energy_j);
    c.metric="source contact impulse/couple";
    c.vector(p.source_numerical_impulse_n_s,q.source_numerical_impulse_n_s,s.impulse_n_s);
    c.vector(p.source_numerical_angular_kg_m2_s,q.source_numerical_angular_kg_m2_s,s.angular_impulse_kg_m2_s);
    c.vector(p.geometry_couple_kg_m2_s,q.geometry_couple_kg_m2_s,s.angular_impulse_kg_m2_s);
    c.metric="native step impulse";c.vector(p.native_step_impulse_n_s,q.native_step_impulse_n_s,s.impulse_n_s);
    c.vector(p.native_step_angular_kg_m2_s,q.native_step_angular_kg_m2_s,s.angular_impulse_kg_m2_s);
    return c.error;
}
}
NativeContactAccuracyResult advanceNativeFixedTargetControlled(JoltWorld &world,LatticeBackend &target,
    double interval,const NativeContactAccuracySettings &settings,const std::function<NativeContactStepAudit(double)> &contact) {
    const double maximum=target.externalContactTimestep(),start_time=target.externalContactElapsedTime();
    if(!contact||!std::isfinite(interval)||interval<=0||interval>maximum||settings.maximum_halvings>20||
        (settings.composition!=NativeContactComposition::BeforeForces&&settings.composition!=NativeContactComposition::VerletForceBoundaries))
        throw std::invalid_argument("invalid controlled contact interval, callback or refinement budget");
    for(double v:{settings.minimum_step_s,settings.position_m,settings.velocity_m_s,settings.orientation_rad,
        settings.angular_velocity_rad_s,settings.damage_fraction,settings.history_strain,settings.plastic_extension_m,
        settings.plastic_strain,settings.energy_j,settings.impulse_n_s,settings.angular_impulse_kg_m2_s})
        if(!std::isfinite(v)||v<=0)throw std::invalid_argument("contact accuracy bounds must be finite and positive");
    if(interval*.5<settings.minimum_step_s||!std::isfinite(start_time+interval)||start_time+interval<=start_time)
        throw std::invalid_argument("controlled contact interval cannot advance within its minimum step");
    const auto ids=world.activeBodyIds();
    if(ids.size()>2048||world.stepCount()>std::numeric_limits<std::uint64_t>::max()-2)
        throw std::invalid_argument("controlled contact native budget exceeded");
    LatticeState initial;SphereState<double> sphere;target.download(initial,sphere);
    if(initial.u.empty()||initial.u.size()>3U*1024U||initial.alive.size()>65536U)
        throw std::invalid_argument("controlled contact material budget exceeded");
    NativeContactAccuracyResult result;
    const auto step=[&](double dt) {
        NativeContactStepAudit audit;
        const auto project=[&] {
            const auto tick=world.stepCount();const auto receipt=contact(dt);validateAudit(receipt,true);
            if(world.stepCount()!=tick)throw std::logic_error("contact accuracy callback advanced the native world");
            audit=addAudit(audit,receipt);
        };
        const auto advance_source=[&] {
            const auto before=world.mechanicalTotals();world.step(dt);const auto after=world.mechanicalTotals();
            audit.native_step_energy_j=after.mechanicalEnergy()-before.mechanicalEnergy();
            audit.native_step_impulse_n_s=after.linear_momentum_kg_m_s-before.linear_momentum_kg_m_s;
            audit.native_step_angular_kg_m2_s=after.angular_momentum_kg_m2_s-before.angular_momentum_kg_m2_s;
            validateAudit(audit);
        };
        if(settings.composition==NativeContactComposition::BeforeForces)
            target.advanceExternalContactStep(dt,[&]{project();advance_source();});
        else target.advanceCoupledContactStep(dt,[&](ExternalContactPhase phase) {
            project();if(phase==ExternalContactPhase::BeforeDrift)advance_source();
        });
        return audit;
    };
    for(unsigned round=0;round<=settings.maximum_halvings;++round) {
        ++result.attempted_intervals;AccuracySnapshot full;
        (void)runNativeFixedTargetTrial(world,target,[&] {
            const auto audit=step(interval);full=accuracySnapshot(world,target,ids,audit);return false;
        });
        const bool accepted=runNativeFixedTargetTrial(world,target,[&] {
            const auto first=step(interval*.5);const auto audit=addAudit(first,step(interval*.5));
            const auto fine=accuracySnapshot(world,target,ids,audit);
            result.topology_agrees=full.material.alive==fine.material.alive&&full.material.failure_mode==fine.material.failure_mode;
            result.compared_interval_s=interval;
            result.normalized_error=accuracyError(full,fine,settings,result);
            if(!result.topology_agrees||result.normalized_error>1)return false;
            const double elapsed=target.externalContactElapsedTime()-start_time;
            if(std::abs(elapsed-interval)>16*std::numeric_limits<double>::epsilon()*std::max(start_time+interval,interval))
                throw std::logic_error("controlled contact trial lost physical time");
            result.accepted_audit=audit;return true;
        });
        if(accepted) {
            result.accepted=true;result.accepted_interval_s=interval;
            result.suggested_interval_s=std::min(maximum,result.normalized_error<.125?2*interval:interval);
            return result;
        }
        ++result.rejected_intervals;
        if(round==settings.maximum_halvings||interval*.25<settings.minimum_step_s)break;
        interval*=.5;
    }
    result.suggested_interval_s=interval;return result;
}
NativeFixedManifoldTransfer applyNativeFixedLocalSurfaceManifold(JoltWorld &world,LatticeBackend &target,
    std::span<const NativeSurfaceWitness> witnesses,const MaterialContactRegionSettings &settings,
    MatterBodyId proxy,MatterBodyId striker,const PointContactRoundoffBudget &budget) {
    NativeFixedManifoldTransfer out;out.target_step=target.status().total_steps;
    out.horizon_s=target.externalContactTimestep();
    if(witnesses.empty())return out;
    if(witnesses.size()>64)throw std::invalid_argument("native manifold witness budget exceeded");
    std::vector<std::uint32_t> ids;
    for(const auto &w:witnesses) {
        out.regions.push_back(target.externalContactRegion(w.seed,settings));
        for(const auto id:out.regions.back().nodes)ids.push_back(id);
    }
    std::sort(ids.begin(),ids.end());ids.erase(std::unique(ids.begin(),ids.end()),ids.end());
    if(ids.size()>64)throw std::invalid_argument("native manifold material union exceeds 64 nodes");
    std::vector<ActiveNodeState> nodes;
    for(const auto id:ids)nodes.push_back(target.externalContactPoint(id));
    std::vector<FixedSurfaceContact> contacts;
    for(std::size_t k=0;k<witnesses.size();++k) {
        const auto &w=witnesses[k];FixedSurfaceContact c;
        c.surface_world_m=w.surface_world_m;c.normal_world=w.normal_world;c.gap_m=w.gap_m;c.settings=w.settings;
        for(const auto id:out.regions[k].nodes)c.nodes.push_back(static_cast<std::uint32_t>(std::lower_bound(ids.begin(),ids.end(),id)-ids.begin()));
        contacts.push_back(std::move(c));
    }
    const auto prepared=world.prepareExternalFixedSurfaceManifold(proxy,striker,nodes,contacts,out.horizon_s,budget);
    if(!prepared.receipt().contact.active_contacts){out.source=prepared.receipt();return out;}
    std::vector<ExternalPointVelocity> updates;
    for(std::size_t k=0;k<ids.size();++k)updates.push_back({ids[k],nodes[k],prepared.receipt().contact.node_velocities_m_s[k]});
    const auto delta=target.validateExternalPointVelocities(updates);
    Vec3 impulse{},moment{};
    for(std::size_t k=0;k<witnesses.size();++k) {
        const auto j=prepared.receipt().contact.impulses_n_s[k];impulse+=j;moment+=cross(witnesses[k].surface_world_m,j);
    }
    if(length(delta.impulse_n_s-impulse)>1e-10*(1+length(impulse))||
        length(delta.angular_impulse_kg_m2_s-moment)>1e-10*(1+length(moment)))
        throw std::invalid_argument("native manifold target force/moment reproduction failed");
    out.source=world.commitExternalFixedSurfaceManifold(prepared);
    out.target=target.applyExternalPointVelocities(updates);return out;
}
bool runNativeFixedTargetTrial(JoltWorld &world,LatticeBackend &target,const std::function<bool()> &trial) {
    if (!trial) throw std::invalid_argument("empty native/target trial");
    return target.runReversibleTrial([&] {return world.runExternalFixedTrial(trial);});
}
NativeFixedPointTransfer applyNativeFixedPointTransfer(JoltWorld &world,LatticeBackend &target,
    std::uint32_t node,MatterBodyId proxy,MatterBodyId striker,Vec3 normal,double gap,
    const PointRigidContactSettings &settings,const PointContactRoundoffBudget &budget) {
    NativeFixedPointTransfer out;out.node=node;out.target_step=target.status().total_steps;
    out.horizon_s=target.externalContactTimestep();
    const auto before=target.externalContactPoint(node);auto point=before;
    const auto prepared=world.prepareExternalFixedPointContact(proxy,striker,before,normal,gap,out.horizon_s,settings,budget);
    if(!prepared.receipt().contact.modal_contact.applied) {out.source=prepared.receipt();return out;}
    // In the double CPU reference this preflights the exact candidate and all
    // cumulative target ledger arithmetic. It cannot round or clamp velocity.
    (void)target.validateExternalPointVelocity(node,before,prepared.receipt().contact.modal_contact.node_velocity_m_s);
    out.source=world.commitExternalFixedPointContact(prepared,point);
    // One host thread; native commit cannot mutate the target backend. The
    // validated assignment performs no allocation, upload or time advance.
    out.target=target.applyExternalPointVelocity(node,before,point.velocity_m_s);
    return out;
}
NativeFixedSurfaceTransfer applyNativeFixedSurfaceTransfer(JoltWorld &world,LatticeBackend &target,
    std::span<const std::uint32_t> support,MatterBodyId proxy,MatterBodyId striker,Vec3 surface,
    Vec3 normal,double gap,const PointRigidContactSettings &settings,const PointContactRoundoffBudget &budget) {
    if(support.size()<4||support.size()>64)throw std::invalid_argument("surface contact needs 4..64 support nodes");
    NativeFixedSurfaceTransfer out;out.target_step=target.status().total_steps;
    out.horizon_s=target.externalContactTimestep();
    std::vector<ActiveNodeState> nodes;nodes.reserve(support.size());
    for(std::size_t i=0;i<support.size();++i) {
        for(std::size_t j=0;j<i;++j)if(support[j]==support[i])throw std::invalid_argument("duplicate surface support node");
        nodes.push_back(target.externalContactPoint(support[i]));
    }
    out.stencil=makeMaterialContactStencil(nodes,surface);auto point=out.stencil.point;
    const auto prepared=world.prepareExternalFixedPointContact(proxy,striker,point,normal,gap,out.horizon_s,settings,budget);
    if(!prepared.receipt().contact.modal_contact.applied) {out.source=prepared.receipt();return out;}
    const auto &contact=prepared.receipt().contact.modal_contact;
    const auto velocities=materialContactVelocities(nodes,out.stencil,contact.impulse_to_node_n_s);
    std::vector<ExternalPointVelocity> updates;updates.reserve(nodes.size());
    for(std::size_t i=0;i<nodes.size();++i)updates.push_back({support[i],nodes[i],velocities[i]});
    const auto delta=target.validateExternalPointVelocities(updates);
    const Vec3 expected_moment=cross(surface,contact.impulse_to_node_n_s);
    const double expected_work=dot(out.stencil.point.velocity_m_s,contact.impulse_to_node_n_s)+
        .5*dot(contact.impulse_to_node_n_s,contact.impulse_to_node_n_s)/out.stencil.point.mass_kg;
    out.target_impulse_error_n_s=delta.impulse_n_s-contact.impulse_to_node_n_s;
    out.target_angular_error_kg_m2_s=delta.angular_impulse_kg_m2_s-expected_moment;
    out.target_work_error_j=delta.work_j-expected_work;
    // Double-reference reproduction bounds; native float roundoff is still
    // independently admitted by the existing source budget. Preflight all of
    // these and the cumulative target ledger before either system is written.
    const auto norm=[](Vec3 v){return std::hypot(v.x,v.y,v.z);};
    if(norm(out.target_impulse_error_n_s)>1e-10*(1+norm(contact.impulse_to_node_n_s))||
       norm(out.target_angular_error_kg_m2_s)>1e-10*(1+norm(expected_moment))||
       !std::isfinite(out.target_work_error_j)||std::abs(out.target_work_error_j)>1e-10*(1+std::abs(expected_work)))
        throw std::invalid_argument("surface contact target reproduction exceeds double reference bounds");
    out.source=world.commitExternalFixedPointContact(prepared,point);
    out.target=target.applyExternalPointVelocities(updates);
    return out;
}
NativeFixedSurfaceTransfer applyNativeFixedLocalSurfaceTransfer(JoltWorld &world,LatticeBackend &target,
    std::uint32_t seed,const MaterialContactRegionSettings &region_settings,MatterBodyId proxy,MatterBodyId striker,
    Vec3 surface,Vec3 normal,double gap,const PointRigidContactSettings &settings,const PointContactRoundoffBudget &budget) {
    auto region=target.externalContactRegion(seed,region_settings);
    auto out=applyNativeFixedSurfaceTransfer(world,target,region.nodes,proxy,striker,surface,normal,gap,settings,budget);
    out.region=std::move(region);return out;
}
}
