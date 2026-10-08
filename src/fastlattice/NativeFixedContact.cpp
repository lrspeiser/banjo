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
double rotationDistance(Quat a,Quat b) {
    const double an=std::hypot(std::hypot(a.w,a.x),std::hypot(a.y,a.z));
    const double bn=std::hypot(std::hypot(b.w,b.x),std::hypot(b.y,b.z));
    if(!std::isfinite(an)||!std::isfinite(bn)||an<=0||bn<=0)
        throw std::invalid_argument("contact accuracy native rotation is invalid");
    const double aw=a.w/an,ax=a.x/an,ay=a.y/an,az=a.z/an;
    const double bw=b.w/bn,bx=b.x/bn,by=b.y/bn,bz=b.z/bn;
    const double minus=std::hypot(std::hypot(aw-bw,ax-bx),std::hypot(ay-by,az-bz));
    const double plus=std::hypot(std::hypot(aw+bw,ax+bx),std::hypot(ay+by,az+bz));
    return 4*std::asin(std::min(1.0,.5*std::min(minus,plus)));
}
double accuracyError(const AccuracySnapshot &a,const AccuracySnapshot &b,const NativeContactAccuracySettings &s,NativeContactAccuracyResult &result) {
    double error=0;result.error_metric.clear();result.error_bound=0;
    result.error_full_value={};result.error_fine_value={};result.error_is_vector=false;
    const char *metric="material state";
    const auto compare=[&](Vec3 x,Vec3 y,double bound,bool is_vector) {
        const double e=(is_vector?length(x-y):std::abs(x.x-y.x))/bound;
        if(!std::isfinite(e))throw std::overflow_error("contact accuracy comparison is nonfinite");
        if(e>error) {
            error=e;result.error_metric=metric;result.error_full_value=x;result.error_fine_value=y;
            result.error_bound=bound;result.error_is_vector=is_vector;
        }
    };
    const auto scalar=[&](double x,double y,double bound) {
        compare({x,0,0},{y,0,0},bound,false);
    };
    const auto vector=[&](Vec3 x,Vec3 y,double bound){compare(x,y,bound,true);};
    const auto array=[&](const std::vector<double> &x,const std::vector<double> &y,double bound) {
        if(x.size()!=y.size())throw std::logic_error("contact accuracy material dimensions changed");
        for(std::size_t i=0;i<x.size();++i)scalar(x[i],y[i],bound);
    };
    metric="material position";array(a.material.u,b.material.u,s.position_m);
    metric="material velocity";array(a.material.v,b.material.v,s.velocity_m_s);
    // u_prev samples different times in full and half steps, so cannot be
    // directly compared. Rollback preserves it; accepted integration owns it.
    metric="material damage/history";array(a.material.damage,b.material.damage,s.damage_fraction);
    array(a.material.prev_tensile,b.material.prev_tensile,s.history_strain);
    array(a.material.prev_compressive,b.material.prev_compressive,s.history_strain);
    array(a.material.prev_shear,b.material.prev_shear,s.history_strain);
    metric="material plastic state";array(a.material.plastic_extension,b.material.plastic_extension,s.plastic_extension_m);
    array(a.material.plastic_strain,b.material.plastic_strain,s.plastic_strain);
    if(a.native.size()!=b.native.size())throw std::logic_error("contact accuracy native dimensions changed");
    for(std::size_t i=0;i<a.native.size();++i) {
        const auto &x=a.native[i],&y=b.native[i];
        metric="native position";
        vector(x.center_of_mass_world_m,y.center_of_mass_world_m,s.position_m);
        metric="native velocity";
        vector(x.linear_velocity_m_s,y.linear_velocity_m_s,s.velocity_m_s);
        metric="native angular velocity";
        vector(x.angular_velocity_rad_s,y.angular_velocity_rad_s,s.angular_velocity_rad_s);
        metric="native orientation";
        scalar(rotationDistance(x.orientation_world,y.orientation_world),0,s.orientation_rad);
    }
    const auto load=[&](const ExternalLoadLedger &x,const ExternalLoadLedger &y) {
        scalar(x.work_j,y.work_j,s.energy_j);
        vector(x.requested_impulse_n_s,y.requested_impulse_n_s,s.impulse_n_s);
        vector(x.impulse_n_s,y.impulse_n_s,s.impulse_n_s);
        vector(x.requested_angular_impulse_kg_m2_s,y.requested_angular_impulse_kg_m2_s,s.angular_impulse_kg_m2_s);
        vector(x.angular_impulse_kg_m2_s,y.angular_impulse_kg_m2_s,s.angular_impulse_kg_m2_s);
    };
    const auto &x=a.status,&y=b.status;
    metric="external/gravity transfer";load(x.external_load,y.external_load);load(x.gravity_load,y.gravity_load);
    if(x.external_sources.size()!=y.external_sources.size())throw std::logic_error("contact accuracy force sources changed");
    for(std::size_t i=0;i<x.external_sources.size();++i) {
        if(x.external_sources[i].source!=y.external_sources[i].source)throw std::logic_error("contact accuracy force identity changed");
        load(x.external_sources[i].load,y.external_sources[i].load);
    }
    metric="target contact work (J)";scalar(x.external_point_transfer.work_j,y.external_point_transfer.work_j,s.energy_j);
    metric="target contact impulse (N s)";
    vector(x.external_point_transfer.impulse_n_s,y.external_point_transfer.impulse_n_s,s.impulse_n_s);
    metric="target contact angular impulse (kg m2/s)";
    vector(x.external_point_transfer.angular_impulse_kg_m2_s,y.external_point_transfer.angular_impulse_kg_m2_s,s.angular_impulse_kg_m2_s);
    metric="target boundary/correction";vector(x.fixed_boundary.impulse_n_s,y.fixed_boundary.impulse_n_s,s.impulse_n_s);
    vector(x.fixed_boundary.angular_impulse_kg_m2_s,y.fixed_boundary.angular_impulse_kg_m2_s,s.angular_impulse_kg_m2_s);
    vector(x.bond_kick_roundoff_impulse_n_s,y.bond_kick_roundoff_impulse_n_s,s.impulse_n_s);
    vector(x.bond_kick_roundoff_angular_kg_m2_s,y.bond_kick_roundoff_angular_kg_m2_s,s.angular_impulse_kg_m2_s);
    metric="target numerical integration";scalar(x.integration_numerical_energy_j,y.integration_numerical_energy_j,s.energy_j);
    metric="material work/loss";
    scalar(x.removed_energy_j,y.removed_energy_j,s.energy_j);
    scalar(x.plastic_work_j,y.plastic_work_j,s.energy_j);
    scalar(x.plastic_return_numerical_loss_j,y.plastic_return_numerical_loss_j,s.energy_j);
    scalar(x.damping_dissipated_j,y.damping_dissipated_j,s.energy_j);
    const auto &p=a.audit,&q=b.audit;
    metric="contact dissipation";
    scalar(p.contact_loss_j,q.contact_loss_j,s.energy_j);
    scalar(p.reconciliation_loss_j,q.reconciliation_loss_j,s.energy_j);
    metric="source contact correction";scalar(p.source_numerical_energy_j,q.source_numerical_energy_j,s.energy_j);
    metric="native step energy";scalar(p.native_step_energy_j,q.native_step_energy_j,s.energy_j);
    metric="source contact impulse/couple";
    vector(p.source_numerical_impulse_n_s,q.source_numerical_impulse_n_s,s.impulse_n_s);
    vector(p.source_numerical_angular_kg_m2_s,q.source_numerical_angular_kg_m2_s,s.angular_impulse_kg_m2_s);
    vector(p.geometry_couple_kg_m2_s,q.geometry_couple_kg_m2_s,s.angular_impulse_kg_m2_s);
    metric="native step impulse";vector(p.native_step_impulse_n_s,q.native_step_impulse_n_s,s.impulse_n_s);
    vector(p.native_step_angular_kg_m2_s,q.native_step_angular_kg_m2_s,s.angular_impulse_kg_m2_s);
    return error;
}
}
NativeContactAccuracyResult advanceNativeFixedTargetControlled(JoltWorld &world,LatticeBackend &target,
    double interval,const NativeContactAccuracySettings &settings,const std::function<NativeContactStepAudit(double)> &contact) {
    const double maximum=target.externalContactTimestep(),start_time=target.externalContactElapsedTime();
    if(!contact||!std::isfinite(interval)||interval<=0||interval>maximum||settings.maximum_halvings>20)
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
        target.advanceExternalContactStep(dt,[&] {
            const auto tick=world.stepCount();audit=contact(dt);validateAudit(audit,true);
            if(world.stepCount()!=tick)throw std::logic_error("contact accuracy callback advanced the native world");
            const auto before=world.mechanicalTotals();world.step(dt);const auto after=world.mechanicalTotals();
            audit.native_step_energy_j=after.mechanicalEnergy()-before.mechanicalEnergy();
            audit.native_step_impulse_n_s=after.linear_momentum_kg_m_s-before.linear_momentum_kg_m_s;
            audit.native_step_angular_kg_m2_s=after.angular_momentum_kg_m2_s-before.angular_momentum_kg_m2_s;
            validateAudit(audit);
        });return audit;
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
