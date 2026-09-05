#pragma once

#include "core/Math.hpp"

#include <cmath>
#include <numbers>
#include <stdexcept>

namespace banjo {

struct SupportPlaneFrame {
    Vec3 point_world_m{};
    Vec3 normal_world{0.0, 1.0, 0.0};
    Vec3 tangent_world{1.0, 0.0, 0.0};
    Vec3 bitangent_world{0.0, 0.0, 1.0};
};

[[nodiscard]] inline SupportPlaneFrame makeSupportPlane(
    const Vec3 &point_world_m,
    const Vec3 &normal_world,
    const Vec3 &preferred_tangent_world = {1.0, 0.0, 0.0}) {
    if (lengthSquared(normal_world) <= 1.0e-18) {
        throw std::invalid_argument("support plane normal cannot be zero");
    }

    SupportPlaneFrame plane;
    plane.point_world_m = point_world_m;
    plane.normal_world = normalized(normal_world, {0.0, 1.0, 0.0});

    Vec3 tangent = preferred_tangent_world -
                   dot(preferred_tangent_world, plane.normal_world) *
                       plane.normal_world;
    if (lengthSquared(tangent) <= 1.0e-12) {
        const Vec3 fallback = std::abs(plane.normal_world.x) < 0.8
                                  ? Vec3{1.0, 0.0, 0.0}
                                  : Vec3{0.0, 0.0, 1.0};
        tangent = fallback -
                  dot(fallback, plane.normal_world) * plane.normal_world;
    }
    plane.tangent_world = normalized(tangent);
    plane.bitangent_world = normalized(
        cross(plane.tangent_world, plane.normal_world),
        {0.0, 0.0, 1.0});
    return plane;
}

[[nodiscard]] inline SupportPlaneFrame makeSupportPlaneFromSlopeDegrees(
    double slope_degrees,
    const Vec3 &point_world_m = {}) {
    if (!std::isfinite(slope_degrees) || std::abs(slope_degrees) >= 89.0) {
        throw std::invalid_argument(
            "support plane slope must be finite and below 89 degrees");
    }
    const double radians = slope_degrees * std::numbers::pi / 180.0;

    // Positive slope means that +tangent is downhill. This lets the rolling-ball
    // lab use a positive scalar acceleration convention while retaining a world-space plane.
    return makeSupportPlane(
        point_world_m,
        {std::sin(radians), std::cos(radians), 0.0},
        {std::cos(radians), -std::sin(radians), 0.0});
}

[[nodiscard]] inline double signedDistanceToPlane(
    const SupportPlaneFrame &plane,
    const Vec3 &point_world_m) {
    return dot(point_world_m - plane.point_world_m, plane.normal_world);
}

[[nodiscard]] inline Vec3 pointInPlaneFrame(
    const SupportPlaneFrame &plane,
    double tangent_distance_m,
    double bitangent_distance_m,
    double normal_offset_m = 0.0) {
    return plane.point_world_m + tangent_distance_m * plane.tangent_world +
           bitangent_distance_m * plane.bitangent_world +
           normal_offset_m * plane.normal_world;
}

[[nodiscard]] inline Vec3 projectVectorOntoPlane(
    const SupportPlaneFrame &plane,
    const Vec3 &vector_world) {
    return vector_world -
           dot(vector_world, plane.normal_world) * plane.normal_world;
}

[[nodiscard]] inline Vec3 projectPointOntoPlane(
    const SupportPlaneFrame &plane,
    const Vec3 &point_world_m) {
    return point_world_m -
           signedDistanceToPlane(plane, point_world_m) * plane.normal_world;
}

} // namespace banjo
