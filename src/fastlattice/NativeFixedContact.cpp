#include "fastlattice/NativeFixedContact.hpp"
#include <cmath>

namespace banjo::fastlattice {
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
}
