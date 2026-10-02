#pragma once
#include "physics/PointRigidContact.hpp"
#include <cstdint>
#include <vector>

namespace banjo {
struct FixedVelocityLink {
    std::uint32_t a{},b{};
    Vec3 point_a_world_m{},point_b_world_m{};
};
struct FixedVelocityImpulse {
    Vec3 impulse_on_b_n_s{},free_angular_impulse_on_b_kg_m2_s{};
    double work_j{};
};
struct FixedAssemblyContactResult {
    // Reduced six-coordinate contact result; its rigid pose is a modal frame,
    // not any member's geometry. Only `bodies` contains physical body states.
    PointRigidContactResult modal_contact;
    std::vector<RigidMechanicalState> bodies;
    std::vector<FixedVelocityImpulse> reconciliation,contact_reactions;
    double reconciliation_loss_j{},kinetic_change_j{},work_residual_j{};
    Vec3 momentum_residual_kg_m_s{},geometry_couple_kg_m2_s{},angular_residual_kg_m2_s{};
};
// Instantaneous ideal six-DOF fixed-tree velocity solve plus one point contact.
// 1..256 finite dynamic bodies, exactly N-1 links forming a tree. A link equates
// attachment-point velocities and angular velocities; position/orientation
// drift is NOT corrected. Noncoincident anchors retain their measured couple.
// Existing relative velocity is reconciled by constraint impulses with its
// own loss account; restitution acts on that admitted constrained state.
// No force distribution, pose reset, hand, joint failure or time integration.
[[nodiscard]] FixedAssemblyContactResult evaluatePointFixedAssemblyContact(
    const ActiveNodeState &point,const std::vector<RigidMechanicalState> &bodies,
    const std::vector<FixedVelocityLink> &links,std::uint32_t striker,
    Vec3 normal_world,double gap_m,double dt_s,const PointRigidContactSettings &settings={});
} // namespace banjo
