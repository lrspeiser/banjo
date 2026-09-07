#pragma once

#include "physics/FractureTopology.hpp"

#include <cstddef>
#include <cstdint>
#include <limits>
#include <vector>

namespace banjo {

struct FractureOverlapLimits {
    double penetration_tolerance_m{1.e-10};
    std::uint64_t maximum_tetrahedron_pairs{1000000};
    std::uint64_t maximum_sat_axes{50000000};
};

struct FractureOverlapResult {
    bool resolved{true};
    bool interpenetrating{false};
    bool unowned_interpenetrating{false};
    // Minimum over tested cross-component pairs. Positive is separated, zero is
    // touching, and negative is the SAT penetration-depth estimate.
    double minimum_signed_separation_m{std::numeric_limits<double>::infinity()};
    unsigned tetrahedron_a{std::numeric_limits<unsigned>::max()};
    unsigned tetrahedron_b{std::numeric_limits<unsigned>::max()};
    std::uint64_t tetrahedron_pairs{};
    std::uint64_t broad_phase_candidates{};
    std::uint64_t sat_axes{};
    std::uint64_t owned_overlap_pairs{};
};

// Audits current tet-local positions for overlap between already disconnected
// components. It supplies no impulse or repair. Invalid input throws; exhausting
// either work cap returns resolved=false and must not be treated as collision-free.
[[nodiscard]] FractureOverlapResult
detectFractureOverlap(const FractureTopology &topology,
                      const std::vector<Vec3> &current_positions_m,
                      const FractureSeparation &separation,
                      const FractureOverlapLimits &limits = {},
                      const std::vector<unsigned> &contact_owned_internal_facets = {});

} // namespace banjo
