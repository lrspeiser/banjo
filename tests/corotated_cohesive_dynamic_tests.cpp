#include "physics/CohesiveDynamicPatch.hpp"
#include "physics/CohesiveSphereWorld.hpp"

#include <algorithm>
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

SmallStrainLaw elastic() {
    return {.kind = SmallStrainLawKind::IsotropicElastic,
            .young_modulus_pa = {1.e5, 0, 0},
            .poisson_xy_yz_zx = {.2, 0, 0},
            .maximum_total_strain_norm = .2};
}

PatchDefinition coupon() {
    PatchDefinition definition;
    definition.reference_positions_m = {
        {-.01, -.008, 0.}, {.012, -.007, .001}, {-.008, .011, -.001},
        {-.009, -.006, .018}, {-.008, -.006, -.017}};
    definition.elements = {{{0, 1, 2, 3}, 0}, {{0, 2, 1, 4}, 0}};
    definition.materials = {{elastic(), 1000.}};
    definition.fixed_components.resize(5);
    return definition;
}

CohesiveFacetLaw interfaceLaw() {
    return {.stiffness_pa_per_m = 1.e6,
            .strength_pa = 1000.,
            .fracture_energy_j_m2 = 2.,
            .compression_stiffness_pa_per_m = 1.e6,
            .tangential_stiffness_pa_per_m = 4.e5};
}

CohesiveDynamicPatchOptions options() {
    CohesiveDynamicPatchOptions result;
    result.kinematics = CohesiveKinematics::Corotated;
    result.maximum_time_step_s = 2.e-4;
    result.maximum_absolute_energy_residual_j = 2.e-7;
    result.minimum_deformation_jacobian = .2;
    result.maximum_deformation_gradient_norm = 4.;
    return result;
}

Quat rotation(Vec3 axis, double angle) {
    axis = normalized(axis);
    const double half = .5 * angle;
    return {std::cos(half), axis.x * std::sin(half),
            axis.y * std::sin(half), axis.z * std::sin(half)};
}

PatchDefinition transformed(PatchDefinition definition, Quat q, Vec3 shift) {
    for (Vec3 &point : definition.reference_positions_m)
        point = q.rotate(point) + shift;
    return definition;
}

std::vector<CohesiveFacetLaw> laws(const PatchDefinition &definition) {
    return std::vector<CohesiveFacetLaw>(
        compileFractureTopology(definition).internal_facets.size(), interfaceLaw());
}

std::vector<Vec3> initialVelocity(const CohesiveDynamicPatch &patch,
                                  Quat q = {}, bool rotated = false) {
    const Vec3 omega{0., 0., 20.};
    std::vector<Vec3> velocity;
    velocity.reserve(patch.topology().local_to_original_node.size());
    for (const unsigned original : patch.topology().local_to_original_node) {
        const Vec3 p = coupon().reference_positions_m[original];
        const Vec3 rigid = cross(omega, p);
        const Vec3 small_stretch{.04 * p.x, -.02 * p.y, .01 * p.z};
        velocity.push_back(rotated ? q.rotate(rigid + small_stretch)
                                   : rigid + small_stretch);
    }
    return velocity;
}

struct Run {
    CohesiveDynamicPatch patch;
    double maximum_residual{};
    double sum_absolute_residual{};
    double maximum_stretch{};
    explicit Run(CohesiveDynamicPatch value) : patch(std::move(value)) {}
};

Run simulate(PatchDefinition definition, double fraction, Quat q = {},
             bool rotated = false, bool apply_load = false) {
    CohesiveDynamicPatch dynamic(definition, laws(definition), options());
    dynamic.setVelocitiesMPerS(initialVelocity(dynamic, q, rotated));
    Run run(std::move(dynamic));
    constexpr double duration = .02;
    double time = 0.;
    while (time < duration) {
        const double dt = std::min(fraction * run.patch.stableTimeStepLimitS(),
                                   duration - time);
        std::vector<Vec3> force(run.patch.state().velocities_m_s.size());
        if (apply_load)
            std::fill(force.begin(), force.end(),
                      rotated ? q.rotate(Vec3{.002, -.001, .003})
                              : Vec3{.002, -.001, .003});
        const auto report = run.patch.step(dt, force);
        check(report.accepted, report.error.c_str());
        check(report.facet_derivative_evaluations ==
                  run.patch.topology().internal_facets.size(),
              "each active objective facet uses one bounded derivative pass");
        run.maximum_residual = std::max(run.maximum_residual,
                                        std::abs(report.numerical_energy_residual_j));
        run.sum_absolute_residual += std::abs(report.numerical_energy_residual_j);
        run.maximum_stretch = std::max(run.maximum_stretch,
                                       report.maximum_elastic_stretch_norm);
        time += dt;
    }
    return run;
}

Vec3 angularMomentum(const CohesiveDynamicPatch &patch) {
    const auto positions = patch.positionsM();
    const auto &velocity = patch.state().velocities_m_s;
    const auto &mass = patch.nodalMassesKg();
    double total_mass = 0.;
    Vec3 center, center_velocity;
    for (std::size_t i = 0; i < mass.size(); ++i) {
        total_mass += mass[i]; center += mass[i] * positions[i];
        center_velocity += mass[i] * velocity[i];
    }
    center = center / total_mass; center_velocity = center_velocity / total_mass;
    Vec3 momentum;
    for (std::size_t i = 0; i < mass.size(); ++i)
        momentum += mass[i] * cross(positions[i] - center,
                                    velocity[i] - center_velocity);
    return momentum;
}

void finite_spin_and_energy_refine() {
    CohesiveDynamicPatch initial(coupon(), laws(coupon()), options());
    initial.setVelocitiesMPerS(initialVelocity(initial));
    const Vec3 initial_angular = angularMomentum(initial);
    const auto coarse = simulate(coupon(), .2);
    const auto fine = simulate(coupon(), .1);
    const auto reference = coupon().reference_positions_m;
    const auto positions = fine.patch.positionsM();
    const auto &map = fine.patch.topology().local_to_original_node;
    auto local_for_original = [&](unsigned original) {
        return static_cast<std::size_t>(std::find(map.begin(), map.end(), original) - map.begin());
    };
    const Vec3 initial_edge = reference[1] - reference[0];
    const Vec3 final_edge = positions[local_for_original(1)] - positions[local_for_original(0)];
    const double angle = std::atan2(cross(initial_edge, final_edge).z,
                                    dot(initial_edge, final_edge));
    check(angle > .25, "corotated coupon must undergo more than 0.25 rad actual rotation");
    check(fine.maximum_stretch > 0. && fine.maximum_stretch < .2,
          "rotating coupon retains a small nonzero elastic stretch in declared domain");
    nearVec(angularMomentum(fine.patch), initial_angular, 2.e-8,
            "objective internal forces preserve current angular momentum");
    check(fine.sum_absolute_residual < coarse.sum_absolute_residual * .7,
          "halving timestep reduces accumulated absolute raw energy residual");
    check(fine.maximum_residual <= options().maximum_absolute_energy_residual_j,
          "every accepted corotated step satisfies raw energy budget");
}

void rotated_translated_experiments_agree() {
    const Quat q = rotation({.3, -.4, .8}, 1.1);
    const Vec3 shift{1.2, -.7, 2.};
    const auto base = simulate(coupon(), .1, {}, false, true);
    const auto moved = simulate(transformed(coupon(), q, shift), .1, q, true, true);
    const auto base_positions = base.patch.positionsM();
    const auto moved_positions = moved.patch.positionsM();
    for (std::size_t i = 0; i < base_positions.size(); ++i) {
        nearVec(moved_positions[i], q.rotate(base_positions[i]) + shift, 2.e-10,
                "rotated and translated corotated trajectory positions agree");
        nearVec(moved.patch.state().velocities_m_s[i],
                q.rotate(base.patch.state().velocities_m_s[i]), 2.e-9,
                "rotated corotated trajectory velocities agree");
    }
    const auto a = base.patch.report(), b = moved.patch.report();
    near(a.kinetic_energy_j, b.kinetic_energy_j, 2.e-12,
         "objective paired kinetic energy agrees");
    near(a.bulk_stored_energy_j + a.cohesive_stored_energy_j,
         b.bulk_stored_energy_j + b.cohesive_stored_energy_j, 2.e-11,
         "objective paired stored energy agrees");
}

void compression_handoff_preserves_accepted_state() {
    auto bulk = elastic();
    bulk.young_modulus_pa[0] = 1.e6;
    bulk.poisson_xy_yz_zx[0] = .25;
    bulk.maximum_total_strain_norm = .12;
    const auto definition = makeTetrahedralBrick({.08, .02, .08}, {1, 1, 1}, {bulk, 1000.});
    const CohesiveFacetLaw interface{1.e9, 1.e4, .1, 1.e9, 2.e8};
    const auto topology = compileFractureTopology(definition);
    auto dynamic = options();
    dynamic.maximum_displacement_gradient_norm = .12;
    dynamic.maximum_absolute_energy_residual_j = 2.e-4;
    PatchContactOptions contact;
    contact.friction_coefficient = .1;
    contact.contact_margin_m = 1.e-6;
    contact.maximum_penetration_m = 1.e-5;
    contact.maximum_contact_events = 128;
    contact.maximum_geometry_queries = 20000;
    contact.maximum_geometry_iterations = 100000;
    constexpr double radius = .012;
    const double mass = 4. / 3. * std::acos(-1.) * radius * radius * radius * 7870.;
    CohesiveSphereWorld world(definition,
        {{.007, .02 + radius + 2.e-5, .009}, {0, -1., 0}, {}, radius, mass},
        std::vector<CohesiveFacetLaw>(topology.internal_facets.size(), interface), dynamic, contact);
    const double dt = .1 * world.material().stableTimeStepLimitS();
    for (unsigned step = 0; step < 1000; ++step) {
        const auto before = world.material().state();
        const auto sphere = world.sphere();
        const auto energy = world.material().report();
        const auto result = world.step(dt, std::vector<Vec3>(before.velocities_m_s.size()));
        if (result.accepted) continue;
        check(result.material.contact_handoff_required.has_value(),
              "compressed separation must identify its missing contact handoff");
        const auto evidence = *result.material.contact_handoff_required;
        check(evidence.facet_index < topology.internal_facets.size() &&
                  std::isfinite(evidence.retained_compression_energy_j) &&
                  evidence.retained_compression_energy_j > 0,
              "rejected interface reports actual retained energy and facet");
        const auto &after = world.material().state();
        check(before.time_s == after.time_s && before.revision == after.revision &&
                  before.fully_separated_facets == after.fully_separated_facets,
              "handoff rejection preserves clock and topology");
        for (std::size_t i = 0; i < before.velocities_m_s.size(); ++i) {
            nearVec(after.displacements_m[i], before.displacements_m[i], 0., "positions roll back");
            nearVec(after.velocities_m_s[i], before.velocities_m_s[i], 0., "velocities roll back");
        }
        for (std::size_t i = 0; i < before.corotated_facet_states.size(); ++i)
            for (unsigned p = 0; p < 3; ++p) {
                const auto a = before.corotated_facet_states[i].integration_points[p];
                const auto b = after.corotated_facet_states[i].integration_points[p];
                check(a.opening_m == b.opening_m && a.maximum_opening_m == b.maximum_opening_m,
                      "irreversible history rolls back");
            }
        nearVec(world.sphere().center_m, sphere.center_m, 0., "sphere position rolls back");
        nearVec(world.sphere().velocity_m_s, sphere.velocity_m_s, 0., "sphere velocity rolls back");
        nearVec(world.sphere().spin_rad_s, sphere.spin_rad_s, 0., "sphere spin rolls back");
        const auto retained = world.material().report();
        check(retained.bulk_stored_energy_j == energy.bulk_stored_energy_j &&
                  retained.cohesive_stored_energy_j == energy.cohesive_stored_energy_j &&
                  retained.fracture_dissipation_j == energy.fracture_dissipation_j,
              "accepted energy is neither deleted nor replaced by rejected trial energy");
        return;
    }
    check(false, "fixture must exercise unresolved compressed fracture handoff");
}

} // namespace

int main() {
    const std::vector<std::pair<std::string, std::function<void()>>> tests{
        {"finite spin and energy refine", finite_spin_and_energy_refine},
        {"rotated translated experiments agree", rotated_translated_experiments_agree},
        {"compression handoff preserves accepted state", compression_handoff_preserves_accepted_state},
    };
    unsigned failures = 0;
    for (const auto &[name, test] : tests) {
        try { test(); std::cout << "PASS " << name << '\n'; }
        catch (const std::exception &error) {
            ++failures; std::cerr << "FAIL " << name << ": " << error.what() << '\n';
        }
    }
    std::cout << tests.size() - failures << '/' << tests.size()
              << " corotated cohesive dynamic tests passed\n";
    return failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
