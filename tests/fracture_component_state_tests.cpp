#include "physics/FractureComponentState.hpp"

#include <cmath>
#include <cstdlib>
#include <functional>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace {
using namespace banjo;

struct TestFailure : std::runtime_error { using std::runtime_error::runtime_error; };

void require(bool condition, std::string_view message) {
    if (!condition) throw TestFailure(std::string(message));
}

void near(double actual, double expected, double tolerance, std::string_view message) {
    if (!std::isfinite(actual) || std::abs(actual - expected) > tolerance)
        throw TestFailure(std::string(message) + ": actual=" + std::to_string(actual) +
                          " expected=" + std::to_string(expected));
}

void nearVec(Vec3 actual, Vec3 expected, double tolerance, std::string_view message) {
    near(length(actual - expected), 0., tolerance, message);
}

SmallStrainLaw elastic() {
    return {
        .kind = SmallStrainLawKind::IsotropicElastic,
        .young_modulus_pa = {1.e6, 0., 0.},
        .poisson_xy_yz_zx = {.25, 0., 0.},
        .maximum_total_strain_norm = .05,
    };
}

FractureTopology twoTets(bool mixed_density = false) {
    PatchDefinition definition;
    definition.reference_positions_m = {
        {0., 0., 0.}, {1., 0., 0.}, {0., 1., 0.}, {0., 0., 1.}, {0., 0., -1.}};
    definition.materials = {{elastic(), 600.}, {elastic(), 1800.}};
    definition.elements = {{{0, 1, 2, 3}, 0}, {{0, 2, 1, 4}, mixed_density ? 1U : 0U}};
    definition.fixed_components.resize(5);
    return compileFractureTopology(definition);
}

std::vector<Vec3> referencePositions(const FractureTopology &topology) {
    return topology.duplicated_definition.reference_positions_m;
}

void connected_translation_and_rotation_are_recovered() {
    const auto topology = twoTets();
    const auto separation = evaluateAcceptedSeparations(topology, {false});
    const auto positions = referencePositions(topology);
    const Vec3 translation{.4, -.2, .7};
    const Vec3 spin{.3, -.5, .8};
    std::vector<Vec3> velocities(positions.size());
    double mass = 0.;
    Vec3 center;
    for (std::size_t i = 0; i < positions.size(); ++i) {
        mass += topology.local_nodal_masses_kg[i];
        center += topology.local_nodal_masses_kg[i] * positions[i];
    }
    center = center / mass;
    for (std::size_t i = 0; i < positions.size(); ++i)
        velocities[i] = translation + cross(spin, positions[i] - center);

    const auto result = extractFractureComponentStates(
        topology, separation, positions, velocities, {2., -1., .5});
    require(result.components.size() == 1 &&
                result.components[0].tetrahedra == std::vector<unsigned>({0, 1}),
            "connected topology yields stable original tetrahedron membership");
    const auto &component = result.components[0];
    require(!component.inertia_singular, "volumetric component inertia is nonsingular");
    nearVec(component.center_of_mass_velocity_m_s, translation, 1.e-13,
            "best-fit translation recovered");
    nearVec(component.best_fit_angular_velocity_rad_s, spin, 1.e-12,
            "best-fit angular velocity recovered");
    near(component.internal_kinetic_energy_j, 0., 1.e-13,
         "pure rigid motion has no internal kinetic residual");
    near(component.kinetic_decomposition_residual_j, 0., 1.e-12,
         "rigid kinetic decomposition closes");
}

void separated_components_preserve_aggregate_identities() {
    const auto topology = twoTets(true);
    const auto separation = evaluateAcceptedSeparations(topology, {true});
    const auto positions = referencePositions(topology);
    std::vector<Vec3> velocities(positions.size());
    for (unsigned i = 0; i < 4; ++i) velocities[i] = {1., 0., 0.};
    for (unsigned i = 4; i < 8; ++i) velocities[i] = {0., -2., .5};
    velocities[7] += Vec3{.1, -.05, .2};
    const Vec3 origin{-.3, .2, 1.};
    const auto result = extractFractureComponentStates(
        topology, separation, positions, velocities, origin);
    require(result.components.size() == 2 &&
                result.components[0].tetrahedra == std::vector<unsigned>({0}) &&
                result.components[1].tetrahedra == std::vector<unsigned>({1}),
            "accepted face yields deterministic separated component membership");

    double mass = 0., energy = 0.;
    Vec3 momentum, angular;
    for (std::size_t i = 0; i < positions.size(); ++i) {
        const double nodal_mass = topology.local_nodal_masses_kg[i];
        mass += nodal_mass;
        momentum += nodal_mass * velocities[i];
        angular += nodal_mass * cross(positions[i] - origin, velocities[i]);
        energy += .5 * nodal_mass * lengthSquared(velocities[i]);
    }
    near(result.mass_kg, mass, mass * 1.e-14, "aggregate component mass identity");
    nearVec(result.linear_momentum_kg_m_s, momentum, 1.e-12,
            "aggregate linear momentum identity");
    nearVec(result.angular_momentum_about_common_origin_kg_m2_s, angular, 1.e-12,
            "aggregate angular momentum identity at common origin");
    near(result.kinetic_energy_j, energy, energy * 1.e-13,
         "aggregate kinetic energy identity");
    near(result.components[0].mass_kg * 3., result.components[1].mass_kg,
         result.mass_kg * 1.e-13, "mixed material density controls component mass");
    require(result.components[1].internal_kinetic_energy_j > 0.,
            "nonrigid nodal velocity remains explicit internal kinetic energy");
}

void singular_inertia_retains_unresolved_energy() {
    const auto topology = twoTets();
    const auto separation = evaluateAcceptedSeparations(topology, {false});
    std::vector<Vec3> positions(topology.local_nodal_masses_kg.size());
    std::vector<Vec3> velocities(positions.size());
    for (std::size_t i = 0; i < positions.size(); ++i) {
        positions[i] = {static_cast<double>(i), 0., 0.};
        velocities[i] = {0., static_cast<double>(i % 3), 0.};
    }
    const auto result = extractFractureComponentStates(
        topology, separation, positions, velocities);
    const auto &component = result.components[0];
    require(component.inertia_singular, "collinear point masses report singular inertia");
    nearVec(component.best_fit_angular_velocity_rad_s, {}, 0.,
            "singular inertia does not invent a best-fit spin");
    require(component.internal_kinetic_energy_j > 0.,
            "singular inertia retains relative motion as internal kinetic energy");
    near(component.kinetic_decomposition_residual_j, 0., 1.e-12,
         "singular decomposition retains all kinetic energy");
}

void invalid_partition_state_and_budgets_reject() {
    const auto topology = twoTets();
    const auto separation = evaluateAcceptedSeparations(topology, {false});
    const auto positions = referencePositions(topology);
    const std::vector<Vec3> velocities(positions.size());
    auto bad_partition = separation;
    bad_partition.components[0] = {1, 0};
    bool threw = false;
    try {
        (void)extractFractureComponentStates(topology, bad_partition, positions, velocities);
    } catch (const std::invalid_argument &) { threw = true; }
    require(threw, "unsorted component membership rejects");

    auto bad_positions = positions;
    bad_positions[0].x = std::numeric_limits<double>::quiet_NaN();
    threw = false;
    try {
        (void)extractFractureComponentStates(topology, separation, bad_positions, velocities);
    } catch (const std::invalid_argument &) { threw = true; }
    require(threw, "nonfinite component state rejects");

    FractureComponentStateLimits limits;
    limits.maximum_node_visits = 23;
    threw = false;
    try {
        (void)extractFractureComponentStates(topology, separation, positions, velocities, {}, limits);
    } catch (const std::invalid_argument &) { threw = true; }
    require(threw, "node-visit work budget rejects without partial result");

    auto altered_mass = topology;
    altered_mass.local_nodal_masses_kg[0] *= 1.01;
    threw = false;
    try {
        (void)extractFractureComponentStates(altered_mass, separation, positions, velocities);
    } catch (const std::invalid_argument &) { threw = true; }
    require(threw, "altered positive nodal mass rejects undeclared mass conversion");
}

} // namespace

int main() {
    const std::vector<std::pair<std::string, std::function<void()>>> tests = {
        {"connected translation and rotation are recovered", connected_translation_and_rotation_are_recovered},
        {"separated components preserve aggregate identities", separated_components_preserve_aggregate_identities},
        {"singular inertia retains unresolved energy", singular_inertia_retains_unresolved_energy},
        {"invalid partition state and budgets reject", invalid_partition_state_and_budgets_reject},
    };
    unsigned failures = 0;
    for (const auto &[name, test] : tests) {
        try { test(); std::cout << "PASS " << name << '\n'; }
        catch (const std::exception &error) {
            ++failures; std::cerr << "FAIL " << name << ": " << error.what() << '\n';
        }
    }
    std::cout << (tests.size() - failures) << '/' << tests.size()
              << " fracture component-state tests passed\n";
    return failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
