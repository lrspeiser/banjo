#include "physics/PairedFacetContact.hpp"

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
const Triangle base{{{0., 0., 0.}, {2., 0., 0.}, {0., 2., 0.}}};

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

Triangle translated(Triangle value, Vec3 offset) {
    for (Vec3 &point : value) point += offset;
    return value;
}

void matching_compressed_planes_are_valid() {
    const auto result = pairedFacetCompressionFootprint(
        base, translated(base, {0., 0., -.01}));
    require(result.resolved && result.compressed_points == 3 &&
                result.valid_footprint_points == 3 && result.projection_work == 6,
            "matching compressed facets retain all finite footprints");
    for (const auto &point : result.integration_points)
        require(point.compressed && point.projections_in_footprint &&
                    point.minimum_barycentric_margin > .16,
                "interior quadrature projections have positive margin");
}

void tension_has_no_active_contact() {
    const auto result = pairedFacetCompressionFootprint(
        base, translated(base, {0., 0., .01}));
    require(result.resolved && result.compressed_points == 0 &&
                result.valid_footprint_points == 0 && result.projection_work == 0,
            "tensile gap has no compressive footprint work");
}

void lateral_slide_is_not_accepted_as_contact() {
    const auto result = pairedFacetCompressionFootprint(
        base, translated(base, {3., 0., -.01}));
    require(result.resolved && result.compressed_points == 3 &&
                result.valid_footprint_points == 0 && result.projection_work == 6,
            "signed compression outside finite overlap is invalid contact");
    for (const auto &point : result.integration_points)
        require(point.minimum_barycentric_margin < 0.,
                "outside projection reports negative barycentric margin");
}

void rigid_transform_preserves_margins() {
    Triangle a = base, b = translated(base, {.2, -.1, -.02});
    const auto original = pairedFacetCompressionFootprint(a, b);
    const Quat q = rotation({.3, -.4, .8}, 1.2);
    const Vec3 shift{4., -2., .7};
    for (Vec3 &point : a) point = q.rotate(point) + shift;
    for (Vec3 &point : b) point = q.rotate(point) + shift;
    const auto moved = pairedFacetCompressionFootprint(a, b);
    require(original.resolved && moved.resolved &&
                original.compressed_points == moved.compressed_points &&
                original.valid_footprint_points == moved.valid_footprint_points,
            "rigid transform preserves contact classifications");
    for (unsigned i = 0; i < 3; ++i)
        near(moved.integration_points[i].minimum_barycentric_margin,
             original.integration_points[i].minimum_barycentric_margin, 2.e-13,
             "rigid transform preserves footprint margin");
}

void edge_tolerance_and_invalid_geometry() {
    Triangle shifted = translated(base, {1. / 3. + 1.e-11, 0., -.01});
    auto result = pairedFacetCompressionFootprint(base, shifted);
    require(result.resolved && result.compressed_points == 3 &&
                result.valid_footprint_points == 3,
            "declared barycentric tolerance admits a roundoff-scale edge excess");
    result = pairedFacetCompressionFootprint(base, shifted, 0.);
    require(result.resolved && result.compressed_points == 3 &&
                result.valid_footprint_points < 3,
            "zero tolerance exposes the same projection beyond the finite edge");

    Triangle degenerate = base;
    degenerate[2] = {4., 0., 0.};
    result = pairedFacetCompressionFootprint(base, degenerate);
    require(!result.resolved, "degenerate side is explicitly unresolved");
    const Triangle skinny{{{0., 0., 0.}, {1., 0., 0.}, {1., 1.e-9, 0.}}};
    result = pairedFacetCompressionFootprint(
        skinny, translated(skinny, {0., 0., -1.e-3}));
    require(!result.resolved,
            "finite but ill-conditioned barycentric solve is unresolved");
    Triangle invalid = base;
    invalid[0].x = std::numeric_limits<double>::quiet_NaN();
    result = pairedFacetCompressionFootprint(invalid, base);
    require(!result.resolved, "nonfinite side is explicitly unresolved");
    result = pairedFacetCompressionFootprint(base, base, -1.e-10);
    require(!result.resolved, "negative barycentric tolerance is rejected");
}

} // namespace

int main() {
    const std::vector<std::pair<std::string_view, std::function<void()>>> tests{
        {"matching compressed planes", matching_compressed_planes_are_valid},
        {"tension is inactive", tension_has_no_active_contact},
        {"lateral slide loses footprint", lateral_slide_is_not_accepted_as_contact},
        {"rigid transform invariance", rigid_transform_preserves_margins},
        {"edge and invalid guards", edge_tolerance_and_invalid_geometry},
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
              << " paired-facet footprint tests passed\n";
    return failures ? 1 : 0;
}
