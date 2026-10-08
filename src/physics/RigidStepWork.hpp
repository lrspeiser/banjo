#pragma once
#include "physics/MechanicalAccounting.hpp"
#include <span>
namespace banjo {
struct RigidStepWorkInput {
    RigidMechanicalState before,after;
    Vec3 spin_after_gyro_rad_s{},velocity_after_forces_m_s{},spin_after_forces_rad_s{};
    Vec3 gravity_impulse_n_s{},spring_impulse_n_s{},spring_couple_n_m_s{},contact_impulse_n_s{},contact_couple_n_m_s{};
    Vec3 velocity_after_solver_m_s{},spin_after_solver_rad_s{},velocity_after_limit_m_s{},spin_after_limit_rad_s{};
    bool integration_observed{};
};
struct RigidStepWork {
    double gravity_work_j{},gyro_kick_j{},other_force_work_j{},spring_work_j{},contact_work_j{};
    double solver_residual_work_j{},rotation_drift_j{},potential_change_j{},kinetic_change_j{},energy_residual_j{};
    Vec3 solver_linear_residual_n_s{},solver_angular_residual_n_m_s{},angular_drift_n_m_s{};
    double velocity_limit_work_j{},post_integration_work_j{};
    Vec3 velocity_limit_impulse_n_s{},velocity_limit_couple_n_m_s{};
};
// Common fixed-geometry kinetic phases from actual native observations. Source
// impulses are independently supplied, not inferred from final velocities.
// Signed residual/gyro/drift terms remain numerical or unexplained; not heat.
// The identity does not by itself prove an accurate force/contact/material law.
[[nodiscard]] RigidStepWork auditRigidStepWork(std::span<const RigidStepWorkInput>,Vec3 gravity_m_s2);
}
