#pragma once

#include "core/Math.hpp"

#include <array>

namespace banjo {

struct TetrahedronContactSide {
    std::array<Vec3, 4> positions_m{};
    std::array<Vec3, 4> velocities_m_s{};
    std::array<double, 4> lumped_masses_kg{};
    // true means the corresponding velocity component is constrained to zero.
    std::array<std::array<bool, 3>, 4> fixed_components{};
    std::array<double, 4> barycentric{};
};

struct TetrahedronContactImpulseOptions {
    double witness_tolerance_m{1.e-8};
    double unit_normal_tolerance{1.e-10};
    double closing_speed_tolerance_m_s{1.e-12};
    double maximum_position_m{1000.};
    double maximum_speed_m_s{1.e6};
    double maximum_mass_kg{1.e12};
};

struct TetrahedronContactImpulseResult {
    bool applied{};
    std::array<Vec3, 4> velocities_a_m_s{};
    std::array<Vec3, 4> velocities_b_m_s{};
    Vec3 contact_point_a_m{};
    Vec3 contact_point_b_m{};
    double relative_normal_speed_before_m_s{};
    double relative_normal_speed_after_m_s{};
    double inverse_effective_mass_kg_inv{};
    double normal_impulse_n_s{};
    double kinetic_dissipation_j{};
    // Constraint impulse and its moment about the current coordinate origin.
    Vec3 support_impulse_n_s{};
    Vec3 support_current_moment_n_m_s{};
    Vec3 raw_linear_momentum_change_kg_m_s{};
    Vec3 raw_angular_momentum_change_kg_m2_s{};
    Vec3 linear_momentum_residual_kg_m_s{};
    Vec3 angular_momentum_residual_kg_m2_s{};
    double work_residual_j{};
};

// Applies a frictionless, zero-restitution normal impulse to candidate nodal
// velocities. Inputs are never mutated. The normal points from witness A to B.
// The reconstructed witness separation must be parallel to the normal within
// witness_tolerance_m; this routine performs no positional correction.
[[nodiscard]] TetrahedronContactImpulseResult evaluateTetrahedronContactImpulse(
    const TetrahedronContactSide &a, const TetrahedronContactSide &b,
    Vec3 unit_normal_a_to_b, const TetrahedronContactImpulseOptions &options = {});

} // namespace banjo
