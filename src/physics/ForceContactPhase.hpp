#pragma once
#include "physics/PointRigidContact.hpp"
#include <span>

namespace banjo {
struct ForceContactPointStates {
    ActiveNodeState before_forces,after_forces,after_contact;
};
struct ForceContactRigidStates {
    RigidMechanicalState before_forces,after_forces,after_contact;
};
struct ForceContactPhaseAudit {
    double kinetic_change_j{};
    double sequential_force_work_j{},sequential_contact_work_j{};
    double simultaneous_force_work_j{},simultaneous_contact_work_j{};
    double force_cross_work_j{},contact_cross_work_j{};
    double point_contact_work_j{},rigid_contact_work_j{},rigid_force_work_j{};
    double energy_residual_j{},cross_work_residual_j{};
    Vec3 force_impulse_n_s{},contact_impulse_n_s{};
    Vec3 force_angular_impulse_kg_m2_s{},contact_angular_impulse_kg_m2_s{};
    Vec3 momentum_residual_n_s{},angular_residual_kg_m2_s{};
};
// Three actual velocity states at identical geometry/mass/tensor: before the
// force kick, after forces, and after contact. Work attributed concurrently
// uses the common phase midpoint (before + after)/2; sequential operator work
// and their exactly opposing cross terms remain visible. 0..1024 translating
// points and 0..256 finite rigid members, at least one degree of freedom.
// Pure measurement: no response, state edits, loss reclassification, changed
// contact law, or tolerance. A signed contact work is NOT automatically a
// physical dissipation/constitutive law. Dynamic DOF work identity is not a
// substitute for support, external-force, fracture or full-pipeline accounts.
[[nodiscard]] ForceContactPhaseAudit auditForceContactPhase(
    std::span<const ForceContactPointStates>,std::span<const ForceContactRigidStates>);
}
