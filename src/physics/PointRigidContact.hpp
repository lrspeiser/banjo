#pragma once

#include "physics/MechanicalAccounting.hpp"

namespace banjo {

struct PointRigidContactSettings {
    double static_friction{},dynamic_friction{},restitution{};
    double restitution_speed_threshold_m_s{.5};
    double contact_margin_m{1e-5};
};

struct PointRigidContactResult {
    bool applied{},sticking{};
    Vec3 node_velocity_m_s{};
    RigidMechanicalState rigid{};
    Vec3 impulse_to_node_n_s{},angular_impulse_to_rigid_kg_m2_s{};
    double normal_impulse_n_s{},tangent_impulse_n_s{};
    double relative_normal_before_m_s{},relative_normal_after_m_s{};
    double target_normal_speed_m_s{},slip_after_m_s{};
    double impulse_work_j{},kinetic_change_j{},dissipated_energy_j{},work_residual_j{};
    Vec3 momentum_residual_kg_m_s{},angular_residual_kg_m2_s{};
    unsigned friction_iterations{};
};

// One instantaneous finite rigid body / translational material-point response.
// Geometry supplies signed gap and a unit normal pointing FROM rigid TO point.
// Both reactions act at the point's centre: its contact envelope has no spin
// degree of freedom. Inertia is the rigid body's actual world tensor, including
// finite-cell self inertia. No sphere substitution, position correction, hand
// controller, fixing, geometry search or fracture is implemented here.
// Inputs are immutable. Unsupported/inaccurate friction/restitution combinations
// refuse rather than publishing a candidate with positive kinetic work.
[[nodiscard]] PointRigidContactResult evaluatePointRigidContact(
    const ActiveNodeState &node,const RigidMechanicalState &rigid,
    Vec3 normal_world,double gap_m,double dt_s,
    const PointRigidContactSettings &settings={});

} // namespace banjo
