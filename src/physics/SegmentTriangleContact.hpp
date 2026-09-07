#pragma once

#include "core/Math.hpp"

#include <array>

namespace banjo {

enum class SegmentTriangleClassification {
    Separated,
    Touching,
    PiercingInterior,
    CoplanarOverlap,
};

struct SegmentTriangleContactResult {
    bool resolved{};
    SegmentTriangleClassification classification{SegmentTriangleClassification::Separated};
    Vec3 closest_point_segment_m{};
    Vec3 closest_point_triangle_m{};
    double segment_barycentric{}; // (1-t)*segment[0] + t*segment[1]
    std::array<double, 3> triangle_barycentric{};
    Vec3 triangle_winding_normal{};
    std::array<double, 2> endpoint_signed_plane_distance_m{};
    double distance_m{};
    unsigned candidate_work{};
};

// Static, bounded closest-feature query for a finite segment and triangle.
// Intersection is geometry only: it never implies a cut, impulse, damage, or
// material separation. Invalid or near-degenerate geometry returns resolved=false.
[[nodiscard]] SegmentTriangleContactResult closestSegmentTriangle(
    const std::array<Vec3, 2> &segment_m,
    const std::array<Vec3, 3> &triangle_m);

} // namespace banjo
