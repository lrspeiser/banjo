#pragma once

#include "core/Math.hpp"
#include <cstddef>
#include <limits>
#include <vector>

namespace banjo {
// Explicit normal interface law: U = k*min(gap,0)^2/2. A dashpot acts
// only during compression. No restitution coefficient is prescribed.
struct NormalComplianceLaw {
    double stiffness_n_m{};
    double compression_damping_kg_s{};
};
struct NormalComplianceEvaluation {
    double impulse_kg_m_s{}, impulse_gap_derivative_kg_s{};
    double energy_before_j{}, energy_after_j{}, damping_loss_j{};
};
[[nodiscard]] NormalComplianceEvaluation evaluateNormalCompliance(
    double gap0_m, double gap_change_m, double dt_s, const NormalComplianceLaw &law);

namespace detail {
inline constexpr std::size_t fixed_contact_body = std::numeric_limits<std::size_t>::max();
struct ElasticNormalContact {
    std::size_t a{}, b{fixed_contact_body};
    Vec3 relative0, normal;
    double gap0_m{}, sphere_radius_m{}; // radius > 0 selects finite-sphere geometry
    NormalComplianceLaw law;
};
struct ElasticContactEvaluation {
    bool valid{true};
    Vec3 impulse_on_a;
    Mat3 velocity_tangent; // minus d(impulse_on_a)/d(endpoint relative velocity)
    double energy_before_j{}, energy_after_j{}, damping_loss_j{}, compression_m{};
};
[[nodiscard]] ElasticContactEvaluation evaluateElasticContact(const ElasticNormalContact &contact,
    const std::vector<Vec3> &initial, const std::vector<Vec3> &velocity, double dt);
}
}
