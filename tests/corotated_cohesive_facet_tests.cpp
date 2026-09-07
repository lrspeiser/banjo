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

std::array<Vec3, 3> triangle() {
    return {{{0., 0., 0.}, {.03, 0., 0.}, {.004, .02, 0.}}};
}

Quat rotation(Vec3 axis, double angle) {
    axis = normalized(axis);
    const double half = .5 * angle;
    return {std::cos(half), axis.x * std::sin(half),
            axis.y * std::sin(half), axis.z * std::sin(half)};
}

std::array<Vec3, 3> transform(const std::array<Vec3, 3> &points,
                              Quat orientation, Vec3 translation) {
    auto result = points;
    for (Vec3 &point : result) point = orientation.rotate(point) + translation;
    return result;
}

void objectivity_rotates_forces_and_preserves_history() {
    const auto reference = triangle();
    auto a = reference, b = reference;
    b[0] += Vec3{2.e-5, -1.e-5, 7.e-5};
    b[1] += Vec3{-1.e-5, 1.e-5, 8.e-5};
    b[2] += Vec3{1.e-5, 2.e-5, 6.e-5};
    const auto base = advanceCorotatedCohesiveFacet(law(), reference, a, b);
    const Quat q = rotation({.3, -.8, .5}, 1.7);
    const Vec3 shift{4., -2., 1.5};
    const auto rotated = advanceCorotatedCohesiveFacet(
        law(), reference, transform(a, q, shift), transform(b, q, shift), base.state);
    near(rotated.stored_energy_j, base.stored_energy_j, 2.e-10,
         "superposed rigid motion preserves stored energy");
    near(rotated.fracture_dissipation_j, base.fracture_dissipation_j, 2.e-10,
         "superposed rigid motion preserves irreversible damage energy");
    near(rotated.fracture_dissipation_increment_j, 0., 2.e-12,
         "rigid motion of prior deformed state creates no new damage");
    for (unsigned i = 0; i < 3; ++i) {
        nearVec(rotated.forces_on_a_n[i], q.rotate(base.forces_on_a_n[i]), 3.e-3,
                "side-A objective force rotates");
        nearVec(rotated.forces_on_b_n[i], q.rotate(base.forces_on_b_n[i]), 3.e-3,
                "side-B objective force rotates");
    }
    nearVec(rotated.resultant_n, {}, 5.e-3,
            "objective facet has zero total current force");
    nearVec(rotated.current_moment_n_m, {}, 3.e-2,
            "objective facet has zero full current moment");
}

void force_matches_current_potential_finite_difference() {
    const auto reference = triangle();
    auto a = reference, b = reference;
    b[0] += Vec3{1.e-5, 2.e-5, 4.e-5};
    b[1] += Vec3{-2.e-5, 1.e-5, 7.e-5};
    b[2] += Vec3{2.e-5, -1.e-5, 5.e-5};
    const auto seeded = advanceCorotatedCohesiveFacet(law(), reference, a, b);
    const auto base = advanceCorotatedCohesiveFacet(law(), reference, a, b, seeded.state);
    constexpr double step = 4.e-8;
    for (unsigned side = 0; side < 2; ++side)
        for (unsigned node = 0; node < 3; ++node)
            for (unsigned axis = 0; axis < 3; ++axis) {
                auto plus_a = a, minus_a = a, plus_b = b, minus_b = b;
                Vec3 &plus = side ? plus_b[node] : plus_a[node];
                Vec3 &minus = side ? minus_b[node] : minus_a[node];
                double *upper = axis == 0 ? &plus.x : axis == 1 ? &plus.y : &plus.z;
                double *lower = axis == 0 ? &minus.x : axis == 1 ? &minus.y : &minus.z;
                *upper += step;
                *lower -= step;
                const auto e_plus = advanceCorotatedCohesiveFacet(
                    law(), reference, plus_a, plus_b, seeded.state);
                const auto e_minus = advanceCorotatedCohesiveFacet(
                    law(), reference, minus_a, minus_b, seeded.state);
                const double numerical = -(e_plus.stored_energy_j - e_minus.stored_energy_j) /
                                         (2. * step);
                const Vec3 force = side ? base.forces_on_b_n[node] : base.forces_on_a_n[node];
                const double actual = axis == 0 ? force.x : axis == 1 ? force.y : force.z;
                near(actual, numerical, std::max(2.e-2, std::abs(numerical) * 2.e-4),
                     "force includes moving-frame potential variation");
            }
}

void full_separation_pays_reference_gc_area() {
    const auto reference = triangle();
    auto b = reference;
    const double failure = 2. * law().fracture_energy_j_m2 / law().strength_pa;
    for (Vec3 &point : b) point.z += 1.1 * failure;
    const auto result = advanceCorotatedCohesiveFacet(law(), reference, reference, b);
    const double area = .5 * length(cross(reference[1] - reference[0],
                                          reference[2] - reference[0]));
    check(result.separated_integration_points == 3,
          "uniform sufficient opening separates every integration point");
    near(result.fracture_dissipation_j, law().fracture_energy_j_m2 * area, 1.e-13,
         "complete objective facet separation pays Gc times reference area");
    near(result.stored_energy_j, 0., 1.e-15,
         "fully separated tensile facet stores no energy");
}

void damaged_unload_reload_is_objective() {
    const auto reference = triangle();
    const double failure = 2. * law().fracture_energy_j_m2 / law().strength_pa;
    auto damaged_b = reference;
    for (Vec3 &point : damaged_b) point.z += .7 * failure;
    const auto damaged = advanceCorotatedCohesiveFacet(
        law(), reference, reference, damaged_b);
    check(damaged.fracture_dissipation_j > 0. &&
              damaged.separated_integration_points == 0,
          "subcritical loading creates retained partial damage");
    const auto unloaded = advanceCorotatedCohesiveFacet(
        law(), reference, reference, reference, damaged.state);
    near(unloaded.stored_energy_j, 0., 1.e-15,
         "damaged interface unloads stored energy without healing");
    near(unloaded.fracture_dissipation_j, damaged.fracture_dissipation_j, 1.e-14,
         "unloading preserves irreversible fracture energy");

    auto reloaded_b = reference;
    for (Vec3 &point : reloaded_b) point += Vec3{.08 * failure, 0., .35 * failure};
    const auto reloaded = advanceCorotatedCohesiveFacet(
        law(), reference, reference, reloaded_b, unloaded.state);
    const Quat q = rotation({-.4, .2, .7}, .9);
    const Vec3 shift{-1.2, .7, 2.1};
    const auto rotated = advanceCorotatedCohesiveFacet(
        law(), reference, transform(reference, q, shift),
        transform(reloaded_b, q, shift), unloaded.state);
    near(rotated.stored_energy_j, reloaded.stored_energy_j, 2.e-11,
         "damaged reload energy is objective after unload");
    near(rotated.fracture_dissipation_j, reloaded.fracture_dissipation_j, 2.e-11,
         "damaged reload history is objective after unload");
    near(rotated.fracture_dissipation_increment_j, 0., 1.e-14,
         "reload below prior maximum creates no new fracture energy");
    for (unsigned i = 0; i < 3; ++i) {
        nearVec(rotated.forces_on_a_n[i], q.rotate(reloaded.forces_on_a_n[i]), 2.e-7,
                "damaged side-A reload force rotates objectively");
        nearVec(rotated.forces_on_b_n[i], q.rotate(reloaded.forces_on_b_n[i]), 2.e-7,
                "damaged side-B reload force rotates objectively");
    }
}

void invalid_frames_and_work_caps_reject() {
    const auto reference = triangle();
    auto degenerate = reference;
    degenerate[2] = degenerate[1];
    bool threw = false;
    try { (void)advanceCorotatedCohesiveFacet(law(), reference, degenerate, degenerate); }
    catch (const std::invalid_argument &) { threw = true; }
    check(threw, "degenerate current frame rejects");

    auto inverted = reference;
    std::swap(inverted[1], inverted[2]);
    threw = false;
    try { (void)advanceCorotatedCohesiveFacet(law(), reference, inverted, reference); }
    catch (const std::invalid_argument &) { threw = true; }
    check(threw, "inverted side frame rejects");

    CorotatedCohesiveFacetOptions limited;
    limited.maximum_derivative_evaluations = 0;
    threw = false;
    try { (void)advanceCorotatedCohesiveFacet(law(), reference, reference, reference, {}, limited); }
    catch (const std::invalid_argument &) { threw = true; }
    check(threw, "potential-gradient work cap rejects transactionally");

    auto extreme = reference;
    for (Vec3 &point : extreme) point.z += 1.e200;
    threw = false;
    try { (void)advanceCorotatedCohesiveFacet(law(), reference, reference, extreme); }
    catch (const std::invalid_argument &) { threw = true; }
    check(threw, "nonfinite objective energy or force range rejects");
}

} // namespace

int main() {
    const std::vector<std::pair<std::string, std::function<void()>>> tests{
        {"objectivity rotates forces and preserves history", objectivity_rotates_forces_and_preserves_history},
        {"force matches current potential finite difference", force_matches_current_potential_finite_difference},
        {"full separation pays reference Gc area", full_separation_pays_reference_gc_area},
        {"damaged unload reload is objective", damaged_unload_reload_is_objective},
        {"invalid frames and work caps reject", invalid_frames_and_work_caps_reject},
    };
    unsigned failures = 0;
    for (const auto &[name, test] : tests) {
        try { test(); std::cout << "PASS " << name << '\n'; }
        catch (const std::exception &error) {
            ++failures; std::cerr << "FAIL " << name << ": " << error.what() << '\n';
        }
    }
    std::cout << tests.size() - failures << '/' << tests.size()
              << " corotated cohesive facet tests passed\n";
    return failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
