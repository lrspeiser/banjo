#include "fastlattice/NativeFixedContact.hpp"

namespace banjo::fastlattice {
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
}
