#pragma once
#include "physics/PointRigidContact.hpp"
#include "physics/MaterialContactStencil.hpp"
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
struct FixedAssemblyVelocityAudit {
    std::vector<FixedVelocityImpulse> reactions;
    double work_j{};
    Vec3 momentum_residual_n_s{},geometry_couple_kg_m2_s{},angular_residual_kg_m2_s{};
};
struct FixedAssemblyReconciliation {
    RigidMechanicalState modal;
    std::vector<RigidMechanicalState> bodies;
    FixedAssemblyVelocityAudit audit;
    double loss_j{};
};
// Same fixed-tree reduction/reaction calculation used by contact, exposed for
// an authoritative CPU source. No pose/time or mass change. Initial relative
// motion has an explicit reconciliation loss, never hidden in later contact.
[[nodiscard]] FixedAssemblyReconciliation reconcileFixedAssembly(
    const std::vector<RigidMechanicalState> &,const std::vector<FixedVelocityLink> &,std::uint32_t striker=0);
// Instantaneous velocity change at unchanged physical geometry. External
// angular impulse is about the world origin. Returns actual member reactions;
// refuses altered mass/inertia/pose or an unclosed tree response.
[[nodiscard]] FixedAssemblyVelocityAudit auditFixedAssemblyVelocityChange(
    const std::vector<RigidMechanicalState> &before,const std::vector<RigidMechanicalState> &after,
    const std::vector<FixedVelocityLink> &,std::uint32_t loaded_member,
    Vec3 external_impulse_n_s,Vec3 external_angular_impulse_origin_kg_m2_s);
struct FixedAssemblyContactResult {
    // Reduced six-coordinate contact result; its rigid pose is a modal frame,
    // not any member's geometry. Only `bodies` contains physical body states.
    PointRigidContactResult modal_contact;
    std::vector<RigidMechanicalState> bodies;
    std::vector<FixedVelocityImpulse> reconciliation,contact_reactions;
    double reconciliation_loss_j{},kinetic_change_j{},work_residual_j{};
    Vec3 momentum_residual_kg_m_s{},geometry_couple_kg_m2_s{},angular_residual_kg_m2_s{};
};
struct FixedSurfaceContact {
    std::vector<std::uint32_t> nodes; // Indices into the shared actual node array.
    Vec3 surface_world_m{},normal_world{};
    double gap_m{};
    PointRigidContactSettings settings;
};
struct FixedSurfaceManifoldResult {
    std::vector<RigidMechanicalState> bodies;
    std::vector<Vec3> node_velocities_m_s,impulses_n_s;
    std::vector<FixedVelocityImpulse> reconciliation,contact_reactions;
    double reconciliation_loss_j{},dissipated_energy_j{},kinetic_change_j{},work_residual_j{};
    Vec3 momentum_residual_kg_m_s{},geometry_couple_kg_m2_s{},angular_residual_kg_m2_s{};
    unsigned iterations{},active_contacts{};
};
// One simultaneous Coulomb manifold over overlapping affine material supports
// and one finite fixed source tree. Restitution targets are frozen at admission.
// Bounded block iteration may remove an earlier tentative impulse; only the
// converged, whole-system audited result is returned. No state/time mutation.
[[nodiscard]] FixedSurfaceManifoldResult evaluateFixedSurfaceManifold(
    std::span<const ActiveNodeState> nodes,const std::vector<FixedSurfaceContact> &contacts,
    const std::vector<RigidMechanicalState> &bodies,const std::vector<FixedVelocityLink> &links,
    std::uint32_t striker,double dt_s);
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
