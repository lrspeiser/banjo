#pragma once

#include "core/Math.hpp"

#include <array>

namespace banjo {

struct TriangleClosestPointResult {
    bool resolved{};
    Vec3 position_world_m{};
    std::array<double, 3> barycentric{};
    Vec3 normal_triangle_to_query{};
    double distance_m{};
    bool used_winding_normal{};
};

// Returns the closest point on a non-degenerate, finite triangle. The normal
// points from the triangle toward query_point. At zero distance its direction
// is undefined geometrically, so the triangle winding is used and reported.
[[nodiscard]] TriangleClosestPointResult
closestPointOnTriangle(const Vec3 &query_point_world_m,
                       const std::array<Vec3, 3> &triangle_world_m);

struct SweptSphereTriangleSettings {
    double distance_tolerance_m{1.0e-9};
    unsigned maximum_iterations{64};
};

struct SweptSphereTriangleResult {
    bool hit{};
    bool resolved{};
    double time_s{};
    Vec3 closest_point_world_m{};
    std::array<double, 3> barycentric{};
    Vec3 normal_triangle_to_sphere{};
    double distance_m{};
    unsigned iterations{};
    bool used_winding_normal{};
};

// All positions vary linearly over [0, duration_s]. A resolved miss has
// hit=false and time_s=duration_s. Invalid/degenerate input and an exhausted
// iteration budget are explicitly unresolved.
[[nodiscard]] SweptSphereTriangleResult
sweepSphereTriangle(const Vec3 &sphere_center_world_m, const Vec3 &sphere_velocity_m_s,
                    double sphere_radius_m, const std::array<Vec3, 3> &triangle_world_m,
                    const std::array<Vec3, 3> &triangle_velocity_m_s, double duration_s,
                    const SweptSphereTriangleSettings &settings = {});

} // namespace banjo
