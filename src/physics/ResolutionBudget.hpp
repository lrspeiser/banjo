#pragma once
#include <span>
#include <cstddef>

namespace banjo {
struct ResolutionLink {std::size_t a{},b{};double stiffness_n_m{};};
struct ResolutionBudget {
    double maximum_frequency_bound_rad_s{};
    double maximum_step_s{};
    double step_frequency_product{};
    unsigned required_substeps{};
    bool temporally_resolved{};
    bool fits_substep_budget{};
};
// For central linear springs, omega_max^2 <= 2 max_i(sum_j k_ij / m_i).
// The angle limit is a temporal sampling requirement, NOT an accuracy or
// material-validation certificate. Contact and nonlinear tangents need their
// own additional bounds. No stiffness/material parameter is changed.
ResolutionBudget assessSpringResolution(std::span<const double> masses_kg,
    std::span<const ResolutionLink> links,double host_step_s,
    unsigned maximum_substeps=256,double maximum_phase_radians=.2);
}
