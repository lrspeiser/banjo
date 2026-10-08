#pragma once
#include <array>

namespace banjo {
// Frozen contact geometry: p=(tangent impulse 1, tangent impulse 2, twist/L)
// in N s; gradient=(slip 1, slip 2, L*relative spin) in m/s. K=J M^-1 J^T
// is symmetric positive definite, in kg^-1. No material law is inferred here.
// Minimize .5*p^T*K*p + q^T*p over a disk times an interval, preserving the
// caller's Coulomb and twisting caps. q excludes this block's current impulse.
[[nodiscard]] std::array<double,3> solveContactFrictionBlock(
    const std::array<double,9>& inverse_mass,
    const std::array<double,3>& free_gradient,
    double tangent_cap_n_s, double scaled_twist_cap_n_s);
}
