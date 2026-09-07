#include "physics/SweptSegmentTriangle.hpp"

#include <cmath>
#include <functional>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string_view>
#include <vector>

namespace {
using namespace banjo;
using Segment = std::array<Vec3, 2>;
using Triangle = std::array<Vec3, 3>;

const Triangle face{{{-2., 0., -2.}, {2., 0., -2.}, {0., 0., 2.}}};
const std::array<Vec3, 2> still_segment{};
const std::array<Vec3, 3> still_triangle{};

void require(bool value, std::string_view message) {
    if (!value) throw std::runtime_error(std::string(message));
}
void near(double actual, double expected, double tolerance,
          std::string_view message) {
    require(std::isfinite(actual) && std::abs(actual - expected) <= tolerance,
            message);
}

Quat rotation(Vec3 axis, double angle) {
    axis = normalized(axis);
    const double half = .5 * angle;
    return {std::cos(half), axis.x * std::sin(half),
            axis.y * std::sin(half), axis.z * std::sin(half)};
}

void fast_face_crossing_does_not_tunnel() {
    const Segment edge{{{-1., 10., 0.}, {1., 10., 0.}}};
    const std::array<Vec3, 2> velocity{{{0., -1000., 0.}, {0., -1000., 0.}}};
    const auto hit = sweepSegmentTriangle(edge, velocity, face, still_triangle,
                                          .02, {.contact_radius_m = .1});
    require(hit.resolved && hit.hit, "fast blade edge must not tunnel through face");
    near(hit.time_s, .0099, 2.e-9, "fast capsule contact time");
    require(hit.geometry.segment_barycentric >= 0. &&
                hit.geometry.segment_barycentric <= 1.,
            "contact exposes blade-edge coordinate");
}

void edge_grazing_and_initial_overlap() {
    const Segment edge{{{-1., 1., -2.5}, {1., 1., -2.5}}};
    const std::array<Vec3, 2> velocity{{{0., -1., 0.}, {0., -1., 0.}}};
    auto hit = sweepSegmentTriangle(edge, velocity, face, still_triangle, 2.,
                                    {.contact_radius_m = 1.});
    require(hit.resolved && hit.hit, "capsule must resolve triangle-edge grazing");
    near(hit.time_s, 1. - std::sqrt(.75), 5.e-8, "edge grazing time");
    require(hit.geometry.triangle_barycentric[2] == 0.,
            "grazing contact lies on triangle edge");

    hit = sweepSegmentTriangle({{{-.2, .05, 0.}, {.2, .05, 0.}}}, still_segment,
                               face, still_triangle, 1., {.contact_radius_m = .1});
    require(hit.resolved && hit.hit && hit.time_s == 0.,
            "initial capsule overlap is immediate");
}

void exact_tangency_is_never_certified_as_a_miss() {
    const Segment edge{{{-1., 1., -3.}, {1., 1., -3.}}};
    const std::array<Vec3, 2> velocity{{{0., -1., 0.}, {0., -1., 0.}}};
    const auto result = sweepSegmentTriangle(
        edge, velocity, face, still_triangle, 2.,
        {.contact_radius_m = 1., .maximum_evaluations = 64});
    require(result.hit || !result.resolved,
            "exact tangency must not be certified as a miss");
    if (result.hit) {
        require(result.resolved && result.geometry.distance_m <= 1. + 1.e-9,
                "resolved tangency lies inside the declared contact band");
    } else {
        require(result.stagnated || result.evaluations == 64,
                "unresolved tangency reports stagnation or bounded exhaustion");
    }
}

void moving_target_and_stationary_miss() {
    const Segment edge{{{-.5, 3., 0.}, {.5, 3., 0.}}};
    std::array<Vec3, 3> upward{{{0., 2., 0.}, {0., 2., 0.}, {0., 2., 0.}}};
    auto hit = sweepSegmentTriangle(edge, still_segment, face, upward, 2.,
                                    {.contact_radius_m = .5});
    require(hit.resolved && hit.hit, "moving tissue triangle must reach blade capsule");
    near(hit.time_s, 1.25, 2.e-9, "moving-target contact time");

    hit = sweepSegmentTriangle(edge, still_segment, face, still_triangle, 1.,
                               {.contact_radius_m = .5});
    require(hit.resolved && !hit.hit && hit.time_s == 1.,
            "zero-relative-velocity separation is a resolved miss");
}

void common_translation_reports_final_geometry() {
    const Segment edge{{{-.5, 3., 0.}, {.5, 3., 0.}}};
    const std::array<Vec3, 2> segment_velocity{{{2., -1., .5}, {2., -1., .5}}};
    const std::array<Vec3, 3> triangle_velocity{{
        {2., -1., .5}, {2., -1., .5}, {2., -1., .5}}};
    const auto result = sweepSegmentTriangle(
        edge, segment_velocity, face, triangle_velocity, .4,
        {.contact_radius_m = .5, .maximum_evaluations = 2});
    require(result.resolved && !result.hit && result.time_s == .4 &&
                result.evaluations == 2,
            "common translation resolves at the requested endpoint");
    near(result.geometry.closest_point_segment_m.x, -.5 + .8, 1.e-14,
         "final segment witness includes common x translation");
    near(result.geometry.closest_point_segment_m.y, 3. - .4, 1.e-14,
         "final segment witness includes common y translation");
    near(result.geometry.closest_point_triangle_m.y, -.4, 1.e-14,
         "final triangle witness includes common translation");
}

void rigid_transform_preserves_contact() {
    Segment edge{{{-.3, 2., 0.}, {.7, 2., 0.}}};
    std::array<Vec3, 2> velocity{{{0., -3., 0.}, {0., -3., 0.}}};
    const auto base = sweepSegmentTriangle(edge, velocity, face, still_triangle, 1.,
                                           {.contact_radius_m = .2});
    const Quat q = rotation({.2, -.7, .4}, 1.1);
    const Vec3 shift{3., -2., .8};
    Triangle moved_face = face;
    for (Vec3 &point : edge) point = q.rotate(point) + shift;
    for (Vec3 &v : velocity) v = q.rotate(v);
    for (Vec3 &point : moved_face) point = q.rotate(point) + shift;
    const auto moved = sweepSegmentTriangle(edge, velocity, moved_face,
                                            still_triangle, 1.,
                                            {.contact_radius_m = .2});
    require(base.resolved && base.hit && moved.resolved && moved.hit,
            "rigidly transformed sweep remains a hit");
    near(moved.time_s, base.time_s, 1.e-13,
         "rigid transform preserves contact time");
    const Vec3 moved_separation = moved.geometry.closest_point_segment_m -
                                  moved.geometry.closest_point_triangle_m;
    const Vec3 base_separation = base.geometry.closest_point_segment_m -
                                 base.geometry.closest_point_triangle_m;
    require(length(moved_separation - q.rotate(base_separation)) <= 1.e-13,
            "rigid transform preserves the closest separation vector");
    require(moved.geometry.segment_barycentric >= 0. &&
                moved.geometry.segment_barycentric <= 1.,
            "transformed nonunique witness remains on the finite blade edge");
}

void exhaustion_and_invalid_geometry_are_unresolved() {
    const Segment edge{{{-1., 3., 0.}, {1., 3., 0.}}};
    const std::array<Vec3, 2> velocity{{{0., -1., 0.}, {0., -1., 0.}}};
    auto result = sweepSegmentTriangle(
        edge, velocity, face,
        {{{-.2, 0., 0.}, {.2, 0., 0.}, {0., 0., .2}}}, 10.,
        {.contact_radius_m = .1, .maximum_evaluations = 1});
    require(!result.resolved && !result.hit && result.evaluations == 1,
            "work-cap exhaustion must not be reported as a miss");

    Triangle degenerate{{{0., 0., 0.}, {1., 0., 0.}, {2., 0., 0.}}};
    result = sweepSegmentTriangle(edge, velocity, degenerate, still_triangle, 1.);
    require(!result.resolved, "degenerate moving triangle is unresolved");
    result = sweepSegmentTriangle(edge, velocity, face, still_triangle, 1.,
                                  {.maximum_evaluations = 4097});
    require(!result.resolved, "unbounded work request is rejected");
    result = sweepSegmentTriangle(
        edge, velocity, face, still_triangle, 1.,
        {.contact_radius_m = std::numeric_limits<double>::max(),
         .distance_tolerance_m = std::numeric_limits<double>::max()});
    require(!result.resolved,
            "overflowing contact radius plus tolerance is rejected");
    auto invalid_velocity = velocity;
    invalid_velocity[0].x = std::numeric_limits<double>::quiet_NaN();
    result = sweepSegmentTriangle(edge, invalid_velocity, face, still_triangle, 1.);
    require(!result.resolved, "nonfinite motion is rejected");
}

} // namespace

int main() {
    const std::vector<std::pair<std::string_view, std::function<void()>>> tests{
        {"fast face crossing", fast_face_crossing_does_not_tunnel},
        {"edge grazing and initial overlap", edge_grazing_and_initial_overlap},
        {"exact tangency remains conservative", exact_tangency_is_never_certified_as_a_miss},
        {"moving target and stationary miss", moving_target_and_stationary_miss},
        {"common translation final witness", common_translation_reports_final_geometry},
        {"rigid transform invariance", rigid_transform_preserves_contact},
        {"work exhaustion and invalid geometry", exhaustion_and_invalid_geometry_are_unresolved},
    };
    unsigned failures = 0;
    for (const auto &[name, test] : tests)
        try {
            test();
            std::cout << "[PASS] " << name << '\n';
        } catch (const std::exception &error) {
            ++failures;
            std::cerr << "[FAIL] " << name << ": " << error.what() << '\n';
        }
    std::cout << tests.size() - failures << '/' << tests.size()
              << " swept segment-triangle tests passed\n";
    return failures ? 1 : 0;
}
