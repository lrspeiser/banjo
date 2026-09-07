#include "physics/SegmentTriangleContact.hpp"

#include "physics/SweptSphereTriangle.hpp"

#include <algorithm>
#include <cmath>
#include <limits>

namespace banjo {
namespace {

bool finite(Vec3 value) {
    return std::isfinite(value.x) && std::isfinite(value.y) && std::isfinite(value.z);
}

struct SegmentPairClosest {
    double first{}, second{};
    Vec3 point_first{}, point_second{};
    double distance{};
};

SegmentPairClosest closestSegments(Vec3 p0, Vec3 p1, Vec3 q0, Vec3 q1) {
    const Vec3 d1 = p1 - p0, d2 = q1 - q0, r = p0 - q0;
    const double a = dot(d1, d1), e = dot(d2, d2), b = dot(d1, d2);
    const double c = dot(d1, r), f = dot(d2, r);
    const double denominator = a * e - b * b;
    double s = denominator > 64. * std::numeric_limits<double>::epsilon() * a * e
                   ? std::clamp((b * f - c * e) / denominator, 0., 1.)
                   : 0.;
    double t = (b * s + f) / e;
    if (t < 0.) {
        t = 0.;
        s = std::clamp(-c / a, 0., 1.);
    } else if (t > 1.) {
        t = 1.;
        s = std::clamp((b - c) / a, 0., 1.);
    }
    const Vec3 first = p0 + s * d1, second = q0 + t * d2;
    return {s, t, first, second, length(first - second)};
}

void accept(SegmentTriangleContactResult &result, Vec3 segment_point,
            double segment_t, Vec3 triangle_point,
            std::array<double, 3> barycentric, double distance) {
    if (distance >= result.distance_m) return;
    result.distance_m = distance;
    result.closest_point_segment_m = segment_point;
    result.segment_barycentric = segment_t;
    result.closest_point_triangle_m = triangle_point;
    result.triangle_barycentric = barycentric;
}

} // namespace

SegmentTriangleContactResult closestSegmentTriangle(
    const std::array<Vec3, 2> &segment,
    const std::array<Vec3, 3> &triangle) {
    SegmentTriangleContactResult result;
    result.distance_m = std::numeric_limits<double>::infinity();
    for (Vec3 point : segment) if (!finite(point) || length(point) > 1000.) return {};
    for (Vec3 point : triangle) if (!finite(point) || length(point) > 1000.) return {};
    const Vec3 segment_direction = segment[1] - segment[0];
    const double segment2 = lengthSquared(segment_direction);
    const Vec3 edge0 = triangle[1] - triangle[0];
    const Vec3 edge1 = triangle[2] - triangle[0];
    const double triangle_scale2 = std::max({lengthSquared(edge0), lengthSquared(edge1),
                                             lengthSquared(triangle[2] - triangle[1])});
    const Vec3 area_vector = cross(edge0, edge1);
    const double area2 = lengthSquared(area_vector);
    if (!std::isfinite(segment2) || !(segment2 > 0.) ||
        !std::isfinite(triangle_scale2) || !(triangle_scale2 > 0.) ||
        !std::isfinite(area2) ||
        area2 <= 64. * std::numeric_limits<double>::epsilon() *
                     triangle_scale2 * triangle_scale2)
        return {};
    result.triangle_winding_normal = area_vector / std::sqrt(area2);
    result.endpoint_signed_plane_distance_m = {
        dot(segment[0] - triangle[0], result.triangle_winding_normal),
        dot(segment[1] - triangle[0], result.triangle_winding_normal)};
    const double scale = std::max({1., std::sqrt(segment2), std::sqrt(triangle_scale2)});
    const double tolerance = 128. * std::numeric_limits<double>::epsilon() * scale;

    const double plane_difference = result.endpoint_signed_plane_distance_m[0] -
                                    result.endpoint_signed_plane_distance_m[1];
    if (plane_difference != 0.) {
        const double t = result.endpoint_signed_plane_distance_m[0] / plane_difference;
        if (t >= 0. && t <= 1.) {
            const Vec3 point = segment[0] + t * segment_direction;
            const auto closest = closestPointOnTriangle(point, triangle);
            ++result.candidate_work;
            if (!closest.resolved) return {};
            if (closest.distance_m <= tolerance) {
                result.resolved = true;
                result.distance_m = 0.;
                result.closest_point_segment_m = point;
                result.closest_point_triangle_m = closest.position_world_m;
                result.segment_barycentric = t;
                result.triangle_barycentric = closest.barycentric;
                const bool interior = std::all_of(closest.barycentric.begin(),
                    closest.barycentric.end(), [&](double value) { return value > tolerance; });
                const bool strict_crossing =
                    result.endpoint_signed_plane_distance_m[0] *
                        result.endpoint_signed_plane_distance_m[1] < 0.;
                result.classification = strict_crossing && interior
                                            ? SegmentTriangleClassification::PiercingInterior
                                            : SegmentTriangleClassification::Touching;
                return result;
            }
        }
    }

    for (unsigned endpoint = 0; endpoint < 2; ++endpoint) {
        const auto closest = closestPointOnTriangle(segment[endpoint], triangle);
        ++result.candidate_work;
        if (!closest.resolved) return {};
        accept(result, segment[endpoint], static_cast<double>(endpoint),
               closest.position_world_m, closest.barycentric, closest.distance_m);
    }
    for (unsigned edge = 0; edge < 3; ++edge) {
        const unsigned next = (edge + 1) % 3;
        const auto closest = closestSegments(segment[0], segment[1],
                                             triangle[edge], triangle[next]);
        ++result.candidate_work;
        if (!std::isfinite(closest.distance)) return {};
        std::array<double, 3> barycentric{};
        barycentric[edge] = 1. - closest.second;
        barycentric[next] = closest.second;
        accept(result, closest.point_first, closest.first, closest.point_second,
               barycentric, closest.distance);
    }
    if (!finite(result.closest_point_segment_m) ||
        !finite(result.closest_point_triangle_m) || !std::isfinite(result.distance_m))
        return {};
    result.resolved = true;
    if (result.distance_m <= tolerance) {
        result.distance_m = 0.;
        result.classification =
            std::abs(result.endpoint_signed_plane_distance_m[0]) <= tolerance &&
                    std::abs(result.endpoint_signed_plane_distance_m[1]) <= tolerance
                ? SegmentTriangleClassification::CoplanarOverlap
                : SegmentTriangleClassification::Touching;
    }
    return result;
}

} // namespace banjo
