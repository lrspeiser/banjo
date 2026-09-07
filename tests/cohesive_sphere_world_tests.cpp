#include "physics/CohesiveSphereWorld.hpp"

#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <functional>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
using namespace banjo;

void check(bool condition, const char *message) {
    if (!condition) throw std::runtime_error(message);
}

SmallStrainLaw isotropic(double young, double poisson) {
    return {.kind = SmallStrainLawKind::IsotropicElastic,
            .young_modulus_pa = {young, 0, 0},
            .poisson_xy_yz_zx = {poisson, 0, 0},
            .maximum_total_strain_norm = .12};
}

SmallStrainLaw oak() {
    return {.kind = SmallStrainLawKind::OrthotropicElastic,
            .young_modulus_pa = {.7e9, 12e9, 1e9},
            .poisson_xy_yz_zx = {.025, .30, .30},
            .shear_xy_yz_zx_pa = {.6e9, .7e9, .1e9},
            .maximum_total_strain_norm = .05};
}

CohesiveFacetLaw interfaceLaw(double strength = 1.e4, double gc = .1) {
    return {.stiffness_pa_per_m = 1.e9,
            .strength_pa = strength,
            .fracture_energy_j_m2 = gc,
            .compression_stiffness_pa_per_m = 1.e9,
            .tangential_stiffness_pa_per_m = 2.e8};
}

PatchDefinition patch(SmallStrainLaw law = isotropic(1.e6, .25),
                      double density = 1000.) {
    return makeTetrahedralBrick({.08, .02, .08}, {1, 1, 1}, {law, density});
}

PatchSphere sphere(double speed) {
    constexpr double radius = .012, density = 7870.;
    const double mass = 4. / 3. * std::acos(-1.) * radius * radius * radius * density;
    return {{.007, .02 + radius + 2.e-5, .009}, {0, -speed, 0}, {}, radius, mass};
}

CohesiveDynamicPatchOptions dynamics(double energy_budget = 2.e-4) {
    CohesiveDynamicPatchOptions options;
    options.maximum_displacement_gradient_norm = .12;
    options.maximum_absolute_energy_residual_j = energy_budget;
    options.maximum_time_step_s = 2.e-4;
    return options;
}

PatchContactOptions contact() {
    return {.friction_coefficient = .1,
            .contact_margin_m = 1.e-6,
            .maximum_penetration_m = 1.e-5,
            .maximum_contact_events = 128,
            .maximum_geometry_queries = 20000,
            .maximum_geometry_iterations = 100000};
}

std::vector<CohesiveFacetLaw> laws(const PatchDefinition &definition,
                                   CohesiveFacetLaw law) {
    const auto topology = compileFractureTopology(definition);
    return std::vector<CohesiveFacetLaw>(topology.internal_facets.size(), law);
}

struct Run {
    bool completed{};
    std::string error;
    unsigned contacts{}, maximum_separated{}, maximum_components{1};
    double maximum_damage{}, maximum_energy_residual{}, maximum_momentum_residual{};
};

Run run(double speed, CohesiveFacetLaw cohesive, double duration) {
    const auto definition = patch();
    CohesiveSphereWorld world(definition, sphere(speed), laws(definition, cohesive),
                              dynamics(), contact());
    Run result;
    double elapsed = 0.;
    for (unsigned step = 0; step < 30000 && elapsed < duration; ++step) {
        const double dt = std::min(.2 * world.material().stableTimeStepLimitS(), duration - elapsed);
        const auto report = world.step(dt,
            std::vector<Vec3>(world.material().state().velocities_m_s.size()));
        if (!report.accepted) { result.error = report.error; return result; }
        elapsed += dt;
        result.contacts += report.contact.impulse_contacts;
        result.maximum_separated = std::max(result.maximum_separated,
                                             report.material.fully_separated_facets);
        result.maximum_components = std::max(result.maximum_components,
            static_cast<unsigned>(world.material().state().separation.components.size()));
        result.maximum_energy_residual = std::max(result.maximum_energy_residual,
            std::abs(report.contact.numerical_energy_balance_residual_j));
        result.maximum_momentum_residual = std::max(result.maximum_momentum_residual,
            length(report.contact.linear_momentum_balance_residual_kg_m_s));
        for (const auto &facet : world.material().state().facet_states)
            for (const auto &point : facet.integration_points)
                result.maximum_damage = std::max(result.maximum_damage,
                    evaluateCohesiveInterface({cohesive.stiffness_pa_per_m,
                                               cohesive.strength_pa,
                                               cohesive.fracture_energy_j_m2, 1.,
                                               cohesive.compression_stiffness_pa_per_m}, point).damage);
    }
    result.completed = elapsed >= duration;
    return result;
}

void low_and_high_force_driven_impacts() {
    const auto low = run(.03, interfaceLaw(), .008);
    check(low.completed, low.error.c_str());
    check(low.contacts > 0, "low impact must actually contact the deformable patch");
    check(low.maximum_separated == 0 && low.maximum_components == 1,
          "low impact must retain cohesive topology");

    const auto high = run(1.0, interfaceLaw(), .008);
    check(high.contacts > 0 && high.maximum_damage > 0,
          "high impact must drive cohesive history through actual contact");
    check(high.maximum_separated > 0 && high.maximum_components > 1,
          "sufficient contact loading must separate at least one cohesive facet");
    check(high.maximum_energy_residual <= dynamics().maximum_absolute_energy_residual_j,
          "accepted impact must satisfy raw energy budget");
    check(high.maximum_momentum_residual < 1.e-8,
          "free sphere-patch impact must conserve total linear momentum");
    check(!high.completed &&
              high.error.find("small displacement-gradient validity limit") != std::string::npos,
          "post-separation finite-rotation trajectory remains an explicit model limit");
}

void failure_rolls_back_sphere_patch_and_history() {
    const auto definition = patch();
    CohesiveSphereWorld world(definition, sphere(1.), laws(definition, interfaceLaw()),
                              dynamics(1.e-16), contact());
    const auto sphere_before = world.sphere();
    const auto state_before = world.material().state();
    const auto report = world.step(.8 * world.material().stableTimeStepLimitS(),
        std::vector<Vec3>(state_before.velocities_m_s.size()));
    check(!report.accepted, "strict raw energy budget must reject impact trial");
    check(world.material().state().revision == state_before.revision &&
              world.material().state().time_s == state_before.time_s &&
              length(world.sphere().center_m - sphere_before.center_m) == 0 &&
              length(world.sphere().velocity_m_s - sphere_before.velocity_m_s) == 0,
          "rejected coupled trial must preserve sphere and patch state");
    bool history_unchanged =
        world.material().state().facet_states.size() == state_before.facet_states.size();
    for (std::size_t facet = 0; facet < state_before.facet_states.size(); ++facet)
        for (unsigned point = 0; point < 3; ++point) {
            const auto &actual = world.material().state().facet_states[facet];
            const auto &before = state_before.facet_states[facet];
            history_unchanged = history_unchanged &&
                actual.integration_points[point].opening_m ==
                    before.integration_points[point].opening_m &&
                actual.integration_points[point].maximum_opening_m ==
                    before.integration_points[point].maximum_opening_m &&
                length(actual.relative_displacement_m[point] -
                       before.relative_displacement_m[point]) == 0.;
        }
    check(history_unchanged, "rejected coupled trial must preserve cohesive history");
}

void catalog_bulk_smoke_uses_separate_interface_assumption() {
    struct Case { const char *name; SmallStrainLaw law; double density; };
    const std::vector<Case> cases{{"glass", isotropic(70e9, .22), 2500.},
                                  {"oak", oak(), 700.},
                                  {"iron", isotropic(211e9, .29), 7870.}};
    for (const auto &entry : cases) {
        const auto definition = patch(entry.law, entry.density);
        // Shared numerical interface assumption only: peak elastic work is
        // 200 kJ/m2, below the explicitly supplied 400 kJ/m2 fracture energy.
        const auto assumed_interface = interfaceLaw(2.e7, 4.e5);
        CohesiveSphereWorld world(definition, sphere(.03),
            laws(definition, assumed_interface), dynamics(1.e-5), contact());
        constexpr double duration = 8.e-4;
        double elapsed = 0.;
        unsigned accepted_contacts = 0, steps = 0;
        while (elapsed < duration && steps < 10000) {
            const double dt = std::min(.05 * world.material().stableTimeStepLimitS(),
                                       duration - elapsed);
            const auto report = world.step(dt,
                std::vector<Vec3>(world.material().state().velocities_m_s.size()));
            check(report.accepted, entry.name);
            accepted_contacts += report.contact.impulse_contacts;
            elapsed += dt;
            ++steps;
        }
        check(std::abs(elapsed - duration) <= 1.e-15 && steps < 10000,
              "catalog contact control must finish within explicit step cap");
        check(accepted_contacts > 0,
              "catalog bulk control must reach actual sphere-surface contact");
        check(world.material().report().fully_separated_facets == 0,
              "catalog bulk smoke must not equate shared interface assumption with fracture");
    }
}

} // namespace

int main() {
    const std::vector<std::pair<std::string, std::function<void()>>> tests{
        {"low and high force-driven impacts", low_and_high_force_driven_impacts},
        {"failure rolls back sphere patch and history", failure_rolls_back_sphere_patch_and_history},
        {"catalog bulk smoke uses separate interface assumption", catalog_bulk_smoke_uses_separate_interface_assumption},
    };
    unsigned failures = 0;
    for (const auto &[name, test] : tests) {
        try { test(); std::cout << "PASS " << name << '\n'; }
        catch (const std::exception &error) {
            ++failures; std::cerr << "FAIL " << name << ": " << error.what() << '\n';
        }
    }
    std::cout << tests.size() - failures << '/' << tests.size()
              << " cohesive sphere world tests passed\n";
    return failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
