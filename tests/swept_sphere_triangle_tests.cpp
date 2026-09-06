#include "physics/SweptSphereTriangle.hpp"

#include <cmath>
#include <functional>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string_view>
#include <vector>

namespace {
using namespace banjo;
using Triangle = std::array<Vec3, 3>;
const Triangle face{{{-2, 0, -2}, {2, 0, -2}, {0, 0, 2}}};
const std::array<Vec3, 3> still{};
void require(bool value, std::string_view message) {
    if (!value)
        throw std::runtime_error(std::string(message));
}
void near(double actual, double expected, double tolerance, std::string_view message) {
    require(std::abs(actual - expected) <= tolerance, message);
}

void closestRegionsAndFallback() {
    auto q = closestPointOnTriangle({0, 2, 0}, face);
    require(q.resolved && q.barycentric[0] > 0 && q.barycentric[1] > 0 && q.barycentric[2] > 0,
            "interior point should select face");
    near(q.distance_m, 2, 1e-14, "face distance");
    q = closestPointOnTriangle({0, 0, -3}, face);
    require(q.resolved && q.barycentric[2] == 0, "outside point should select edge");
    q = closestPointOnTriangle({-3, 0, -3}, face);
    require(q.resolved && q.barycentric[0] == 1, "outside point should select vertex");
    q = closestPointOnTriangle({0, 0, 0}, face);
    require(q.resolved && q.used_winding_normal && q.normal_triangle_to_query.y < 0,
            "zero separation should report winding fallback");
}

void fastFaceCrossingDoesNotTunnel() {
    const auto hit = sweepSphereTriangle({0, 10, 0}, {0, -1000, 0}, .25, face, still, .02);
    require(hit.resolved && hit.hit, "fast sphere should not cross a thin triangle");
    near(hit.time_s, .00975, 2e-9, "first face contact time");
    require(hit.barycentric[0] > 0 && hit.barycentric[1] > 0 && hit.barycentric[2] > 0,
            "crossing should hit face interior");
}

void edgeVertexAndTangency() {
    auto hit = sweepSphereTriangle({0, 1, -3}, {0, -1, 0}, 1, face, still, 2);
    require(hit.resolved && hit.hit && hit.barycentric[2] == 0, "edge tangency should hit");
    near(hit.time_s, 1, 6e-5, "edge tangency time within distance tolerance");
    hit = sweepSphereTriangle({-3, 1, -3}, {0, -1, 0}, std::sqrt(2.0), face, still, 2);
    require(hit.resolved && hit.hit && hit.barycentric[0] == 1, "vertex tangency should hit");
    near(hit.time_s, 1, 6e-5, "vertex tangency time within distance tolerance");
}

void initialOverlapAndMovingTriangle() {
    auto hit = sweepSphereTriangle({0, .1, 0}, {}, .2, face, still, 1);
    require(hit.resolved && hit.hit && hit.time_s == 0, "initial overlap should be immediate");
    const std::array<Vec3, 3> upward{{{0, 2, 0}, {0, 2, 0}, {0, 2, 0}}};
    hit = sweepSphereTriangle({0, 3, 0}, {}, .5, face, upward, 2);
    require(hit.resolved && hit.hit, "moving triangle should collide with stationary sphere");
    near(hit.time_s, 1.25, 2e-9, "moving triangle contact time");
    near(hit.closest_point_world_m.y, 2.5, 2e-9,
         "moving triangle closest point must be reported in world space");
}

void earliestFeatureWins() {
    const auto hit = sweepSphereTriangle({-3, 2, -3}, {3, -2, 3}, .2, face, still, 2);
    require(hit.resolved && hit.hit, "trajectory from a nearest vertex should reach the face");
    near(hit.time_s, .9, 2e-8, "face must win over the initially closest vertex feature");
    require(hit.barycentric[0] > 0 && hit.barycentric[1] > 0 && hit.barycentric[2] > 0,
            "earliest contact should be in the face interior");
}

void deformingTangentialRecedingResolvesMiss() {
    const std::array<Vec3, 3> velocities{{{-300, -2, 40}, {250, -2, -60}, {75, -2, 120}}};
    const auto result =
        sweepSphereTriangle({0, 1, 0}, {100000, 0, 0}, .1, face, velocities, 1e-4,
                            {.distance_tolerance_m = 1e-9, .maximum_iterations = 128});
    require(result.resolved && !result.hit,
            "high tangential speed on a receding deforming triangle must resolve as a miss");
    require(result.iterations <= 128, "receding miss must respect the geometry-query budget");
}

void deformingTriangleClosingHit() {
    const std::array<Vec3, 3> velocities{{{-.1, 1, 0}, {.1, 1, 0}, {0, 1, .1}}};
    const auto hit = sweepSphereTriangle({0, 1, 0}, {}, .1, face, velocities, 1,
                                         {.distance_tolerance_m = 1e-9, .maximum_iterations = 128});
    require(hit.resolved && hit.hit, "deforming triangle should retain a closing face hit");
    near(hit.time_s, .9, 2e-8, "deforming face contact time");
    require(hit.barycentric[0] > 0 && hit.barycentric[1] > 0 && hit.barycentric[2] > 0,
            "deforming collision should remain in the face interior");
}

void smallRotatedFaceRetainsWinding() {
    const double diagonal = 1e-8 / std::sqrt(2.0);
    const Triangle small{{{0, 0, 0}, {0, 0, 1e-8}, {diagonal, -diagonal, 0}}};
    const Vec3 normal{1 / std::sqrt(2.0), 1 / std::sqrt(2.0), 0};
    const Vec3 centroid = (small[0] + small[1] + small[2]) / 3.0;
    const auto hit =
        sweepSphereTriangle(centroid + 4e-9 * normal, -1e-8 * normal, 1e-9, small, still, 1,
                            {.distance_tolerance_m = 1e-14, .maximum_iterations = 128});
    require(hit.resolved && hit.hit,
            "small valid rotated triangle must use its geometric winding for face CCD");
    near(hit.time_s, .299999, 2e-8, "small rotated face contact time");
    require(hit.barycentric[0] > 0 && hit.barycentric[1] > 0 && hit.barycentric[2] > 0,
            "small rotated collision should hit the face interior");
}

void failuresAreNotMisses() {
    auto deforming = still;
    deforming[2].x = .01;
    auto result = sweepSphereTriangle({0, 10, 0}, {3, -1, 2}, .1, face, deforming, 10,
                                      {.distance_tolerance_m = 1e-12, .maximum_iterations = 1});
    require(!result.hit && !result.resolved && result.iterations == 1,
            "iteration exhaustion must remain unresolved");
    Triangle degenerate{{{0, 0, 0}, {1, 0, 0}, {2, 0, 0}}};
    result = sweepSphereTriangle({}, {}, 1, degenerate, still, 1);
    require(!result.hit && !result.resolved, "degenerate triangle must be invalid");
    Triangle invalid = face;
    invalid[0].x = std::numeric_limits<double>::quiet_NaN();
    result = sweepSphereTriangle({}, {}, 1, invalid, still, 1);
    require(!result.hit && !result.resolved, "non-finite geometry must be invalid");
    result = sweepSphereTriangle({}, {}, 1, face, still, 1,
                                 {.distance_tolerance_m = 1e-9, .maximum_iterations = 4097});
    require(!result.hit && !result.resolved, "unbounded iteration request must be invalid");
    result = sweepSphereTriangle({1e308, 0, 0}, {}, 1, face, still, 1);
    require(!result.hit && !result.resolved, "overflowing finite geometry must be invalid");
    const Triangle unit{{{0, 0, 0}, {1, 0, 0}, {0, 0, 1}}};
    result = sweepSphereTriangle({1e100, 1, 0}, {-1e100, 0, 0}, .1, unit, still, 1);
    require(!result.hit && !result.resolved,
            "non-finite quadratic intermediates must be unresolved");
}
} // namespace

int main() {
    const std::vector<std::pair<std::string_view, std::function<void()>>> tests{
        {"closest face edge vertex", closestRegionsAndFallback},
        {"fast face crossing", fastFaceCrossingDoesNotTunnel},
        {"edge vertex tangency", edgeVertexAndTangency},
        {"overlap and moving triangle", initialOverlapAndMovingTriangle},
        {"earliest changing feature", earliestFeatureWins},
        {"deforming tangential receding miss", deformingTangentialRecedingResolvesMiss},
        {"deforming closing hit", deformingTriangleClosingHit},
        {"small rotated face winding", smallRotatedFaceRetainsWinding},
        {"unresolved and invalid", failuresAreNotMisses},
    };
    unsigned failures = 0;
    for (const auto &[name, test] : tests)
        try {
            test();
            std::cout << "[PASS] " << name << '\n';
        } catch (const std::exception &e) {
            ++failures;
            std::cerr << "[FAIL] " << name << ": " << e.what() << '\n';
        }
    std::cout << tests.size() - failures << '/' << tests.size() << " tests passed\n";
    return failures ? 1 : 0;
}
