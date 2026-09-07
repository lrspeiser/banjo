#include "physics/PairedFacetContact.hpp"

#include <algorithm>
#include <cmath>
#include <limits>

namespace banjo {
namespace {

constexpr std::array<std::array<double, 3>, 3> quadrature{{
    {{2. / 3., 1. / 6., 1. / 6.}},
    {{1. / 6., 2. / 3., 1. / 6.}},
    {{1. / 6., 1. / 6., 2. / 3.}},
}};

bool finite(Vec3 value) {
    return std::isfinite(value.x) && std::isfinite(value.y) &&
           std::isfinite(value.z);
}

Vec3 interpolate(const std::array<Vec3, 3> &triangle,
                 const std::array<double, 3> &weights) {
    return weights[0] * triangle[0] + weights[1] * triangle[1] +
           weights[2] * triangle[2];
}

struct TriangleFrame {
    bool resolved{};
    Vec3 normal{};
    double scale{};
};

TriangleFrame frame(const std::array<Vec3, 3> &triangle) {
    for (Vec3 point : triangle)
        if (!finite(point)) return {};
    const Vec3 first = triangle[1] - triangle[0];
    const Vec3 second = triangle[2] - triangle[0];
    const Vec3 area = cross(first, second);
    const double scale = length(first) * length(second);
    const double twice_area = length(area);
    if (!std::isfinite(scale) || !std::isfinite(twice_area) ||
        !(twice_area > std::max(1.e-24, scale * 1.e-12)))
        return {};
    return {true, area / twice_area, scale};
}

struct BarycentricResult {
    bool resolved{};
    std::array<double, 3> weights{};
};

BarycentricResult barycentric(Vec3 point,
                              const std::array<Vec3, 3> &triangle) {
    if (!finite(point)) return {};
    const Vec3 v0 = triangle[1] - triangle[0];
    const Vec3 v1 = triangle[2] - triangle[0];
    const Vec3 v2 = point - triangle[0];
    const double d00 = dot(v0, v0), d01 = dot(v0, v1);
    const double d11 = dot(v1, v1), d20 = dot(v2, v0);
    const double d21 = dot(v2, v1);
    const double denominator = d00 * d11 - d01 * d01;
    if (!std::isfinite(denominator) ||
        !(denominator > 64. * std::numeric_limits<double>::epsilon() *
                            d00 * d11))
        return {};
    const double second = (d11 * d20 - d01 * d21) / denominator;
    const double third = (d00 * d21 - d01 * d20) / denominator;
    const std::array<double, 3> weights{1. - second - third, second, third};
    for (double weight : weights)
        if (!std::isfinite(weight)) return {};
    return {true, weights};
}

} // namespace

PairedFacetContactResult pairedFacetCompressionFootprint(
    const std::array<Vec3, 3> &a, const std::array<Vec3, 3> &b,
    double tolerance) {
    PairedFacetContactResult result;
    if (!std::isfinite(tolerance) || tolerance < 0. || tolerance > 1.e-3)
        return result;
    const TriangleFrame frame_a = frame(a), frame_b = frame(b);
    if (!frame_a.resolved || !frame_b.resolved) return result;
    Vec3 middle_area = cross(.5 * (a[1] + b[1] - a[0] - b[0]),
                             .5 * (a[2] + b[2] - a[0] - b[0]));
    const double middle_length = length(middle_area);
    if (!std::isfinite(middle_length) ||
        !(middle_length > std::max(1.e-24, .5 * (frame_a.scale + frame_b.scale) * 1.e-12)))
        return result;
    const Vec3 normal = middle_area / middle_length;
    if (!(dot(frame_a.normal, normal) > 1.e-12) ||
        !(dot(frame_b.normal, normal) > 1.e-12))
        return result;
    result.midsurface_winding_normal = normal;

    for (unsigned point = 0; point < 3; ++point) {
        const Vec3 point_a = interpolate(a, quadrature[point]);
        const Vec3 point_b = interpolate(b, quadrature[point]);
        auto &output = result.integration_points[point];
        const double gap = dot(point_b - point_a, normal);
        if (!std::isfinite(gap)) return {};
        output.compressed = gap < 0.;
        if (!output.compressed) continue;
        ++result.compressed_points;
        const double a_on_b_denominator = dot(normal, frame_b.normal);
        const double b_on_a_denominator = dot(normal, frame_a.normal);
        if (!(a_on_b_denominator > 1.e-12) ||
            !(b_on_a_denominator > 1.e-12))
            return {};
        const Vec3 projection_a_on_b =
            point_a + dot(b[0] - point_a, frame_b.normal) /
                          a_on_b_denominator * normal;
        const Vec3 projection_b_on_a =
            point_b + dot(a[0] - point_b, frame_a.normal) /
                          b_on_a_denominator * normal;
        if (!finite(projection_a_on_b) || !finite(projection_b_on_a)) return {};
        const auto barycentric_a_on_b = barycentric(projection_a_on_b, b);
        const auto barycentric_b_on_a = barycentric(projection_b_on_a, a);
        if (!barycentric_a_on_b.resolved || !barycentric_b_on_a.resolved)
            return {};
        output.projection_a_on_b_barycentric = barycentric_a_on_b.weights;
        output.projection_b_on_a_barycentric = barycentric_b_on_a.weights;
        result.projection_work += 2;
        output.minimum_barycentric_margin = 1.;
        for (double weight : output.projection_a_on_b_barycentric)
            output.minimum_barycentric_margin =
                std::min(output.minimum_barycentric_margin, weight);
        for (double weight : output.projection_b_on_a_barycentric)
            output.minimum_barycentric_margin =
                std::min(output.minimum_barycentric_margin, weight);
        if (!std::isfinite(output.minimum_barycentric_margin)) return {};
        output.projections_in_footprint =
            output.minimum_barycentric_margin >= -tolerance;
        result.valid_footprint_points += output.projections_in_footprint ? 1U : 0U;
    }
    result.resolved = true;
    return result;
}

} // namespace banjo
