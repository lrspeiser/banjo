#include "physics/CorotatedCohesiveFacet.hpp"

#include <cmath>
#include <cstdlib>
#include <functional>
#include <iostream>
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

CohesiveFacetLaw law() {
    return {.stiffness_pa_per_m = 2.e9,
            .strength_pa = 2.e5,
            .fracture_energy_j_m2 = 40.,
            .compression_stiffness_pa_per_m = 1.e9,
            .tangential_stiffness_pa_per_m = 8.e8};
}

std::array<Vec3, 3> referenceTriangle() {
    return {{{0., 0., 0.}, {.03, 0., 0.}, {.004, .02, 0.}}};
}

Quat rotation(Vec3 axis, double angle) {
    axis = normalized(axis);
    const double half = .5 * angle;
    return {std::cos(half), axis.x * std::sin(half),
            axis.y * std::sin(half), axis.z * std::sin(half)};
}

std::array<Vec3, 3> transformed(const std::array<Vec3, 3> &points,
                                Quat q, Vec3 shift) {
    auto result = points;
    for (Vec3 &point : result) point = q.rotate(point) + shift;
    return result;
}

std::array<Vec3, 3> withUniformLocalGap(const std::array<Vec3, 3> &side_a,
                                        Quat q, Vec3 local_gap) {
    auto result = side_a;
    const Vec3 gap = q.rotate(local_gap);
    for (Vec3 &point : result) point += gap;
    return result;
}

double area() {
    const auto reference = referenceTriangle();
    return .5 * length(cross(reference[1] - reference[0],
                             reference[2] - reference[0]));
}

void mixed_mode_tearing_survives_large_rotation_and_unloading() {
    const auto reference = referenceTriangle();
    const auto cohesive = law();
    const double failure = 2. * cohesive.fracture_energy_j_m2 / cohesive.strength_pa;
    const Quat q = rotation({.3, -.6, .7}, 2.1);
    const Vec3 shift{1.4, -.8, 2.3};
    const auto side_a = transformed(reference, q, shift);

    const auto first = advanceCorotatedCohesiveFacet(
        cohesive, reference, side_a,
        withUniformLocalGap(side_a, q, {.25 * failure, 0., .30 * failure}));
    check(first.fracture_dissipation_j > 0. && first.separated_integration_points == 0,
          "mixed opening and shear initiates progressive damage after large rotation");

    const auto second = advanceCorotatedCohesiveFacet(
        cohesive, reference, side_a,
        withUniformLocalGap(side_a, q, {.75 * failure, 0., .45 * failure}), first.state);
    check(second.fracture_dissipation_j > first.fracture_dissipation_j &&
              second.fracture_dissipation_increment_j > 0.,
          "larger mixed-mode opening advances irreversible damage");

    const auto unloaded = advanceCorotatedCohesiveFacet(
        cohesive, reference, side_a, side_a, second.state);
    near(unloaded.stored_energy_j, 0., 1.e-15,
         "mixed-mode damaged facet unloads reversible stored energy");
    near(unloaded.fracture_dissipation_j, second.fracture_dissipation_j, 1.e-13,
         "mixed-mode unloading cannot heal fracture energy");
    near(unloaded.fracture_dissipation_increment_j, 0., 1.e-15,
         "unloading creates no additional fracture energy");

    const auto complete = advanceCorotatedCohesiveFacet(
        cohesive, reference, side_a,
        withUniformLocalGap(side_a, q, {.8 * failure, 0., .95 * failure}),
        unloaded.state);
    check(complete.separated_integration_points == 3,
          "sufficient mixed-mode loading completes all quadrature histories");
    near(complete.fracture_dissipation_j,
         cohesive.fracture_energy_j_m2 * area(), 1.e-13,
         "complete mixed-mode tearing pays Gc times reference area");
    near(complete.stored_energy_j, 0., 1.e-15,
         "complete tensile/shear separation retains no cohesive stored energy");
    nearVec(complete.resultant_n, {}, 1.e-11,
            "complete objective tearing has zero resultant");
    nearVec(complete.current_moment_n_m, {}, 1.e-11,
            "complete objective tearing has zero current moment");
}

void compressed_shear_control_exposes_confined_law_scope() {
    const auto reference = referenceTriangle();
    const auto cohesive = law();
    const double failure = 2. * cohesive.fracture_energy_j_m2 / cohesive.strength_pa;
    const double tangent_ratio = cohesive.tangential_stiffness_pa_per_m /
                                 cohesive.stiffness_pa_per_m;
    const Quat q = rotation({-.2, .9, .3}, 1.6);
    const auto side_a = transformed(reference, q, {-.7, 1.1, .4});

    const auto compression_only = advanceCorotatedCohesiveFacet(
        cohesive, reference, side_a,
        withUniformLocalGap(side_a, q, {0., 0., -.2 * failure}));
    near(compression_only.fracture_dissipation_j, 0., 0.,
         "pure closure does not drive tensile/shear damage history");
    check(compression_only.stored_energy_j > 0.,
          "pure closure stores separate reversible compression energy");

    const double shear = .7 * failure / std::sqrt(tangent_ratio);
    const auto confined_shear = advanceCorotatedCohesiveFacet(
        cohesive, reference, side_a,
        withUniformLocalGap(side_a, q, {shear, 0., -.2 * failure}),
        compression_only.state);
    check(confined_shear.fracture_dissipation_j > 0. &&
              confined_shear.fracture_dissipation_increment_j > 0. &&
              confined_shear.separated_integration_points == 0,
          "tangential separation advances mixed-mode damage under compression");
    check(confined_shear.stored_energy_j > 0.,
          "confined shear retains reversible compression plus damaged shear energy");

    const auto release = advanceCorotatedCohesiveFacet(
        cohesive, reference, side_a, side_a, confined_shear.state);
    near(release.fracture_dissipation_j, confined_shear.fracture_dissipation_j, 1.e-13,
         "release from confined shear preserves irreversible damage");
    near(release.stored_energy_j, 0., 1.e-15,
         "release returns compression and cohesive stored energy");
    std::cout << "confined_shear_damage_j=" << confined_shear.fracture_dissipation_j
              << " compression_only_damage_j=" << compression_only.fracture_dissipation_j
              << '\n';
}

struct RefinedPath {
    double final_dissipation{};
    double summed_increments{};
    double maximum_increment{};
};

RefinedPath runMixedPath(unsigned increments) {
    const auto reference = referenceTriangle();
    const auto cohesive = law();
    const double failure = 2. * cohesive.fracture_energy_j_m2 / cohesive.strength_pa;
    const Quat q = rotation({.3, -.6, .7}, 2.1);
    const auto side_a = transformed(reference, q, {1.4, -.8, 2.3});
    CorotatedCohesiveFacetState state;
    RefinedPath result;
    double previous_dissipation = 0.;
    for (unsigned step = 1; step <= increments; ++step) {
        const double fraction = static_cast<double>(step) / increments;
        const auto evaluation = advanceCorotatedCohesiveFacet(
            cohesive, reference, side_a,
            withUniformLocalGap(side_a, q,
                                {fraction * .8 * failure, 0.,
                                 fraction * .95 * failure}),
            state);
        check(evaluation.fracture_dissipation_j >= previous_dissipation,
              "refined mixed-mode path damage must be monotone");
        result.summed_increments += evaluation.fracture_dissipation_increment_j;
        result.maximum_increment = std::max(result.maximum_increment,
                                             evaluation.fracture_dissipation_increment_j);
        previous_dissipation = evaluation.fracture_dissipation_j;
        result.final_dissipation = evaluation.fracture_dissipation_j;
        state = evaluation.state;
    }
    return result;
}

void loading_increment_refinement_preserves_fracture_work() {
    const auto coarse = runMixedPath(4);
    const auto fine = runMixedPath(40);
    const double exact = law().fracture_energy_j_m2 * area();
    near(coarse.final_dissipation, exact, 1.e-13,
         "coarse mixed path pays exact complete fracture work");
    near(fine.final_dissipation, exact, 1.e-13,
         "refined mixed path pays exact complete fracture work");
    near(coarse.summed_increments, coarse.final_dissipation, 1.e-13,
         "coarse irreversible increments sum to final fracture work");
    near(fine.summed_increments, fine.final_dissipation, 1.e-13,
         "refined irreversible increments sum to final fracture work");
    check(fine.maximum_increment < coarse.maximum_increment,
          "loading refinement reduces the largest unresolved damage jump");
    std::cout << "mixed_path_exact_gc_area_j=" << exact
              << " coarse_max_damage_increment_j=" << coarse.maximum_increment
              << " fine_max_damage_increment_j=" << fine.maximum_increment << '\n';
}

} // namespace

int main() {
    const std::vector<std::pair<std::string, std::function<void()>>> tests{
        {"mixed-mode tearing survives large rotation and unloading",
         mixed_mode_tearing_survives_large_rotation_and_unloading},
        {"compressed shear control exposes confined law scope",
         compressed_shear_control_exposes_confined_law_scope},
        {"loading increment refinement preserves fracture work",
         loading_increment_refinement_preserves_fracture_work},
    };
    unsigned failures = 0;
    for (const auto &[name, test] : tests) {
        try { test(); std::cout << "PASS " << name << '\n'; }
        catch (const std::exception &error) {
            ++failures; std::cerr << "FAIL " << name << ": " << error.what() << '\n';
        }
    }
    std::cout << tests.size() - failures << '/' << tests.size()
              << " cutting/tearing coupon tests passed\n";
    return failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
