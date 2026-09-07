#include "physics/SegmentTriangleContact.hpp"

#include <cmath>
#include <cstdlib>
#include <functional>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <vector>

namespace {
using namespace banjo;

void check(bool condition, const char *message) {
    if (!condition) throw std::runtime_error(message);
}

void near(double actual, double expected, double tolerance, const char *message) {
    check(std::isfinite(actual) && std::abs(actual - expected) <= tolerance, message);
}

void nearVec(Vec3 actual, Vec3 expected, double tolerance, const char *message) {
    near(length(actual - expected), 0., tolerance, message);
}

const std::array<Vec3, 3> triangle{{{0., 0., 0.}, {2., 0., 0.}, {0., 2., 0.}}};

Quat rotation(Vec3 axis, double angle) {
    axis = normalized(axis);
    const double half = .5 * angle;
    return {std::cos(half), axis.x * std::sin(half),
            axis.y * std::sin(half), axis.z * std::sin(half)};
}

void face_piercing_reports_both_parameterizations() {
    const std::array<Vec3, 2> segment{{{.4, .5, 1.}, {.4, .5, -2.}}};
    const auto result = closestSegmentTriangle(segment, triangle);
    check(result.resolved &&
              result.classification == SegmentTriangleClassification::PiercingInterior,
          "segment crossing triangle interior must classify as piercing");
    near(result.distance_m, 0., 0., "piercing distance");
    near(result.segment_barycentric, 1. / 3., 1.e-14, "piercing segment coordinate");
    nearVec(result.closest_point_segment_m, {.4, .5, 0.}, 1.e-14,
            "piercing closest segment point");
    near(result.triangle_barycentric[0], .55, 1.e-14, "piercing triangle weight 0");
    near(result.triangle_barycentric[1], .2, 1.e-14, "piercing triangle weight 1");
    near(result.triangle_barycentric[2], .25, 1.e-14, "piercing triangle weight 2");
    check(result.endpoint_signed_plane_distance_m[0] > 0. &&
              result.endpoint_signed_plane_distance_m[1] < 0. &&
              result.candidate_work == 1,
          "piercing exposes oriented endpoint signs and bounded work");
}

void endpoint_edge_and_separated_features() {
    auto result = closestSegmentTriangle(
        {{{.5, .5, 0.}, {.5, .5, 1.}}}, triangle);
    check(result.resolved && result.classification == SegmentTriangleClassification::Touching,
          "segment endpoint on face must classify as touching");
    near(result.segment_barycentric, 0., 0., "touching endpoint parameter");

    result = closestSegmentTriangle(
        {{{-1., 1., 0.}, {2., 1., 0.}}}, triangle);
    check(result.resolved &&
              result.classification == SegmentTriangleClassification::CoplanarOverlap,
          "coplanar crossing of triangle edge must classify as overlap");
    near(result.distance_m, 0., 0., "coplanar edge overlap distance");
    check(result.triangle_barycentric[0] == 0. ||
              result.triangle_barycentric[1] == 0. ||
              result.triangle_barycentric[2] == 0.,
          "coplanar crossing identifies triangle edge feature");

    result = closestSegmentTriangle(
        {{{3., .5, 1.}, {3., .5, 2.}}}, triangle);
    check(result.resolved && result.classification == SegmentTriangleClassification::Separated &&
              result.distance_m > 1. && result.candidate_work == 5,
          "separated query resolves through bounded endpoint and edge candidates");
    near(result.segment_barycentric, 0., 1.e-14,
         "separated closest point uses lower segment endpoint");
}

void rigid_transform_preserves_geometry_and_parameters() {
    const std::array<Vec3, 2> segment{{{.7, .4, .8}, {.7, .4, -.6}}};
    const auto base = closestSegmentTriangle(segment, triangle);
    const Quat q = rotation({.2, -.7, .4}, 1.3);
    const Vec3 shift{3., -2., .8};
    auto moved_segment = segment;
    auto moved_triangle = triangle;
    for (Vec3 &point : moved_segment) point = q.rotate(point) + shift;
    for (Vec3 &point : moved_triangle) point = q.rotate(point) + shift;
    const auto moved = closestSegmentTriangle(moved_segment, moved_triangle);
    check(moved.resolved && moved.classification == base.classification,
          "rigid transform preserves intersection classification");
    near(moved.distance_m, base.distance_m, 1.e-13,
         "rigid transform preserves distance");
    near(moved.segment_barycentric, base.segment_barycentric, 1.e-13,
         "rigid transform preserves segment parameter");
    for (unsigned i = 0; i < 3; ++i)
        near(moved.triangle_barycentric[i], base.triangle_barycentric[i], 1.e-13,
             "rigid transform preserves triangle weights");
    nearVec(moved.closest_point_segment_m,
            q.rotate(base.closest_point_segment_m) + shift, 1.e-13,
            "rigid transform maps closest segment point");
    nearVec(moved.triangle_winding_normal, q.rotate(base.triangle_winding_normal), 1.e-13,
            "rigid transform rotates winding normal");
}

void small_valid_and_invalid_geometry_are_distinguished() {
    const std::array<Vec3, 3> small{{{0., 0., 0.}, {1.e-8, 0., 0.}, {0., 1.e-8, 0.}}};
    auto result = closestSegmentTriangle(
        {{{2.e-9, 2.e-9, 1.e-9}, {2.e-9, 2.e-9, -1.e-9}}}, small);
    check(result.resolved &&
              result.classification == SegmentTriangleClassification::PiercingInterior,
          "small but well-conditioned geometry remains resolved");

    auto degenerate = triangle;
    degenerate[2] = {4., 0., 0.};
    result = closestSegmentTriangle({{{0., 0., 1.}, {0., 0., -1.}}}, degenerate);
    check(!result.resolved, "degenerate triangle rejects explicitly");
    const std::array<Vec3, 3> near_degenerate{{
        {0., 0., 0.}, {1., 0., 0.}, {1., 1.e-9, 0.}}};
    result = closestSegmentTriangle(
        {{{.5, 0., 1.}, {.5, 0., -1.}}}, near_degenerate);
    check(!result.resolved,
          "triangle below the relative area conditioning limit rejects explicitly");
    result = closestSegmentTriangle({{{0., 0., 0.}, {0., 0., 0.}}}, triangle);
    check(!result.resolved, "zero-length blade edge rejects explicitly");
    auto invalid = triangle;
    invalid[0].x = std::numeric_limits<double>::quiet_NaN();
    result = closestSegmentTriangle({{{0., 0., 1.}, {0., 0., -1.}}}, invalid);
    check(!result.resolved, "nonfinite triangle rejects explicitly");
}

} // namespace

int main() {
    const std::vector<std::pair<std::string, std::function<void()>>> tests{
        {"face piercing reports both parameterizations", face_piercing_reports_both_parameterizations},
        {"endpoint edge and separated features", endpoint_edge_and_separated_features},
        {"rigid transform preserves geometry and parameters", rigid_transform_preserves_geometry_and_parameters},
        {"small valid and invalid geometry are distinguished", small_valid_and_invalid_geometry_are_distinguished},
    };
    unsigned failures = 0;
    for (const auto &[name, test] : tests) {
        try { test(); std::cout << "PASS " << name << '\n'; }
        catch (const std::exception &error) {
            ++failures; std::cerr << "FAIL " << name << ": " << error.what() << '\n';
        }
    }
    std::cout << tests.size() - failures << '/' << tests.size()
              << " segment-triangle geometry tests passed\n";
    return failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
