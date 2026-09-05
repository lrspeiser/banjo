#pragma once

#include "core/Plane.hpp"
#include "physics/SphereMaterialContact.hpp"
#include <limits>

namespace banjo {

// CPU reference for a closed elastic step with optional frictionless normal
// contact. All participants start at the same time and advance together.
// No damage, damping, friction, restitution or geometric push-out is hidden here.
struct ConservativeStepSettings {
    unsigned maximum_iterations{256};
    double velocity_tolerance_m_s{1e-9};
    double relative_energy_tolerance{1e-9};
    double relative_momentum_tolerance{1e-9};
    double contact_tolerance_m{1e-10};
    const SupportPlaneFrame *support{};
    double support_half_tangent_m{std::numeric_limits<double>::infinity()};
    double support_half_bitangent_m{std::numeric_limits<double>::infinity()};
    // Newton/GMRES solves the whole elastic network; false retains the slower
    // per-bond nonlinear sweep as an independent numerical comparison.
    bool global_elastic_solve{true};
    // Krylov iterations per Newton update, not a relaxed physical tolerance.
    unsigned maximum_linear_iterations{400};
};

struct ConservativeStepResult {
    bool converged{};
    bool balance_measured{};
    unsigned iterations{};
    unsigned linear_iterations{};
    double constitutive_velocity_residual_m_s{};
    double energy_residual_j{};
    Vec3 linear_momentum_residual_kg_m_s{};
    Vec3 angular_momentum_residual_kg_m2_s{};
    // Normal constraints can remove energy when contact is reached during a
    // finite step. This is explicit numerical contact loss, not fracture work.
    double normal_contact_loss_j{};
    Vec3 support_impulse_kg_m_s{};
    Vec3 support_angular_impulse_kg_m2_s{};
    double maximum_penetration_m{};
};

// Transactional: failed convergence leaves every input state untouched.
// Rejects initially overlapping contacts beyond the declared tolerance.
// Steps that cross a finite support footprint edge are rejected for subdivision
// or a general contact handler; this reference does not invent edge geometry.
[[nodiscard]] ConservativeStepResult tryConservativeStep(
    ActiveMatter &matter, double dt_s, const Vec3 &gravity_m_s2 = {},
    CoupledSphereState *sphere = nullptr, const ConservativeStepSettings &settings = {});

} // namespace banjo
