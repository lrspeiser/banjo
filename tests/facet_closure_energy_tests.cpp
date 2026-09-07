#include "physics/CorotatedCohesiveFacet.hpp"
#include "physics/PairedFacetContact.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdlib>
#include <functional>
#include <iostream>
#include <stdexcept>
#include <string_view>
#include <vector>

namespace {
using namespace banjo;
using Triangle = std::array<Vec3, 3>;

void check(bool condition, std::string_view message) {
    if (!condition)
        throw std::runtime_error(std::string(message));
}

void near(double actual, double expected, double tolerance, std::string_view message) {
    check(std::isfinite(actual) && std::isfinite(expected) &&
              std::abs(actual - expected) <= tolerance,
          message);
}

void nearVec(Vec3 actual, Vec3 expected, double tolerance, std::string_view message) {
    near(length(actual - expected), 0., tolerance, message);
}

CohesiveFacetLaw illustrativeLaw() {
    return {.stiffness_pa_per_m = 1.6e9,
            .strength_pa = 1.8e5,
            .fracture_energy_j_m2 = 32.,
            .compression_stiffness_pa_per_m = 9.e8,
            .tangential_stiffness_pa_per_m = 7.e8};
}

Triangle referenceTriangle() {
    return {{{0., 0., 0.}, {.03, 0., 0.}, {.004, .02, 0.}}};
}

Triangle translated(Triangle value, Vec3 offset) {
    for (Vec3 &point : value)
        point += offset;
    return value;
}

Quat rotation(Vec3 axis, double angle) {
    axis = normalized(axis);
    const double half = .5 * angle;
    return {std::cos(half), axis.x * std::sin(half), axis.y * std::sin(half),
            axis.z * std::sin(half)};
}

Triangle transform(Triangle value, Quat orientation, Vec3 translation) {
    for (Vec3 &point : value)
        point = orientation.rotate(point) + translation;
    return value;
}

double area(const Triangle &triangle) {
    return .5 * length(cross(triangle[1] - triangle[0], triangle[2] - triangle[0]));
}

struct FracturedClosure {
    CorotatedCohesiveFacetEvaluation evaluation;
    Triangle a;
    Triangle b;
    double compression_energy{};
};

FracturedClosure makeFracturedClosure() {
    const auto law = illustrativeLaw();
    const Triangle reference = referenceTriangle();
    constexpr double compression = 2.e-5;
    const double failure = 2. * law.fracture_energy_j_m2 / law.strength_pa;
    const double tangential_scale =
        std::sqrt(law.tangential_stiffness_pa_per_m / law.stiffness_pa_per_m);

    CorotatedCohesiveFacetState state;
    double initial_compression_energy = -1.;
    CorotatedCohesiveFacetEvaluation evaluation;
    Triangle b = reference;
    for (unsigned increment = 0; increment <= 12; ++increment) {
        const double slip =
            1.2 * failure * static_cast<double>(increment) / (12. * tangential_scale);
        b = translated(reference, {slip, 0., -compression});
        evaluation = advanceCorotatedCohesiveFacet(law, reference, reference, b, state);
        state = evaluation.state;
        if (increment == 0)
            initial_compression_energy = evaluation.compression_stored_energy_j;
        near(evaluation.compression_stored_energy_j, initial_compression_energy, 3.e-16,
             "fixed normal closure preserves reversible compression energy during slip");
        near(evaluation.stored_energy_j,
             evaluation.cohesive_stored_energy_j + evaluation.compression_stored_energy_j, 3.e-16,
             "total stored energy equals its reported split");
    }
    check(evaluation.separated_integration_points == 3,
          "sufficient tangential slip fully damages all integration points");
    near(evaluation.cohesive_stored_energy_j, 0., 2.e-16,
         "fully damaged closure retains no cohesive stored energy");
    near(evaluation.fracture_dissipation_j, law.fracture_energy_j_m2 * area(reference), 2.e-14,
         "full damage dissipates Gc times reference area");
    check(initial_compression_energy > 0.,
          "compressed fractured facet retains positive reversible energy");
    return {evaluation, reference, b, initial_compression_energy};
}

void closure_energy_survives_damage_and_releases_without_healing() {
    const auto closure = makeFracturedClosure();
    const auto law = illustrativeLaw();
    const Triangle reference = referenceTriangle();
    const auto released_b = translated(reference, {0., 0., 3.e-5});
    const auto released = advanceCorotatedCohesiveFacet(law, reference, reference, released_b,
                                                        closure.evaluation.state);

    check(released.separated_integration_points == 3,
          "positive-gap release does not heal fully damaged history");
    near(released.fracture_dissipation_j, closure.evaluation.fracture_dissipation_j, 2.e-14,
         "release preserves irreversible fracture dissipation");
    near(released.stored_energy_j, 0., 2.e-16, "released fully damaged facet stores no energy");
    near(released.cohesive_stored_energy_j, 0., 2.e-16,
         "released fully damaged facet has no cohesive energy");
    near(released.compression_stored_energy_j, 0., 2.e-16,
         "positive gap releases all compression energy");
    for (unsigned node = 0; node < 3; ++node) {
        nearVec(released.forces_on_a_n[node], {}, 2.e-10, "released side A is force free");
        nearVec(released.forces_on_b_n[node], {}, 2.e-10, "released side B is force free");
    }
}

void rigid_motion_preserves_closure_energy_and_footprint() {
    const auto closure = makeFracturedClosure();
    const auto law = illustrativeLaw();
    const Triangle reference = referenceTriangle();
    const Quat orientation = rotation({.3, -.7, .4}, 1.13);
    const Vec3 shift{2.1, -.8, 3.4};
    const Triangle moved_a = transform(closure.a, orientation, shift);
    const Triangle moved_b = transform(closure.b, orientation, shift);
    const auto moved =
        advanceCorotatedCohesiveFacet(law, reference, moved_a, moved_b, closure.evaluation.state);

    near(moved.compression_stored_energy_j, closure.compression_energy, 2.e-13,
         "rigid motion preserves fractured closure energy");
    near(moved.stored_energy_j, moved.cohesive_stored_energy_j + moved.compression_stored_energy_j,
         3.e-16, "objective evaluation preserves exact stored-energy split");
    nearVec(moved.resultant_n, {}, 2.e-6, "rotated closure forces balance globally");
    nearVec(moved.current_moment_n_m, {}, 2.e-5, "rotated closure moments balance globally");

    const auto footprint = pairedFacetCompressionFootprint(moved_a, moved_b);
    check(footprint.resolved && footprint.compressed_points == 3 &&
              footprint.valid_footprint_points == 3,
          "rotated matching closure retains all finite contact footprints");
}

void laterally_disjoint_compression_is_rejected_by_footprint() {
    const Triangle reference = referenceTriangle();
    const Triangle outside = translated(reference, {.04, 0., -2.e-5});
    const auto footprint = pairedFacetCompressionFootprint(reference, outside);
    check(footprint.resolved && footprint.compressed_points == 3 &&
              footprint.valid_footprint_points == 0,
          "compressed quadrature points outside the paired triangle are rejected");
    for (const auto &point : footprint.integration_points)
        check(point.compressed && !point.projections_in_footprint,
              "each disjoint compressed projection is explicitly outside");
}

void fractured_compression_force_is_frozen_history_energy_gradient() {
    const auto closure = makeFracturedClosure();
    const auto law = illustrativeLaw();
    const Triangle reference = referenceTriangle();
    const Triangle a = reference;
    const Triangle b = translated(reference, {0., 0., -2.e-5});
    const auto base = advanceCorotatedCohesiveFacet(law, reference, a, b, closure.evaluation.state);
    check(base.separated_integration_points == 3 && base.cohesive_stored_energy_j == 0. &&
              base.compression_stored_energy_j > 0.,
          "finite difference starts from fully fractured pure compression");

    constexpr double step = 2.e-8;
    for (unsigned side = 0; side < 2; ++side)
        for (unsigned node = 0; node < 3; ++node)
            for (unsigned axis = 0; axis < 3; ++axis) {
                Triangle plus_a = a, minus_a = a, plus_b = b, minus_b = b;
                Vec3 &plus = side ? plus_b[node] : plus_a[node];
                Vec3 &minus = side ? minus_b[node] : minus_a[node];
                double *upper = axis == 0 ? &plus.x : axis == 1 ? &plus.y : &plus.z;
                double *lower = axis == 0 ? &minus.x : axis == 1 ? &minus.y : &minus.z;
                *upper += step;
                *lower -= step;
                const auto e_plus = advanceCorotatedCohesiveFacet(law, reference, plus_a, plus_b,
                                                                  closure.evaluation.state);
                const auto e_minus = advanceCorotatedCohesiveFacet(law, reference, minus_a, minus_b,
                                                                   closure.evaluation.state);
                const double numerical =
                    -(e_plus.stored_energy_j - e_minus.stored_energy_j) / (2. * step);
                const Vec3 force = side ? base.forces_on_b_n[node] : base.forces_on_a_n[node];
                const double actual = axis == 0 ? force.x : axis == 1 ? force.y : force.z;
                near(actual, numerical, std::max(2.e-3, std::abs(numerical) * 3.e-5),
                     "fractured closure force is the frozen-history energy gradient");
            }
}

} // namespace

int main() {
    const std::vector<std::pair<std::string_view, std::function<void()>>> tests{
        {"closure energy survives fracture and releases",
         closure_energy_survives_damage_and_releases_without_healing},
        {"rigid closure preserves energy and footprint",
         rigid_motion_preserves_closure_energy_and_footprint},
        {"disjoint compression is outside footprint",
         laterally_disjoint_compression_is_rejected_by_footprint},
        {"fractured closure force matches energy gradient",
         fractured_compression_force_is_frozen_history_energy_gradient},
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
              << " facet closure energy tests passed\n";
    return failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
