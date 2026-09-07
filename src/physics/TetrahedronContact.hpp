#pragma once

#include "core/Math.hpp"

#include <array>

namespace banjo {

struct TetrahedronContactResult {
    bool resolved{};
    bool hit{};
    Vec3 normal_a_to_b{};
    double penetration_depth_m{};
    double separation_distance_m{};
    Vec3 point_a_world_m{};
    Vec3 point_b_world_m{};
    std::array<double, 4> barycentric_a{};
    std::array<double, 4> barycentric_b{};
    unsigned narrow_phase_calls{};
};

// Pure bounded GJK/EPA query. Barycentric arrays follow the supplied vertex
// order. Contact geometry never implies fracture, cutting, or an impulse.
[[nodiscard]] TetrahedronContactResult tetrahedronContact(
    const std::array<Vec3, 4> &tetrahedron_a_world_m,
    const std::array<Vec3, 4> &tetrahedron_b_world_m);

} // namespace banjo
