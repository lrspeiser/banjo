#include "fracture/ActivationPolicy.hpp"
#include "fracture/BrittleBondSolver.hpp"
#include "fracture/ConnectedComponents.hpp"
#include "fracture/FragmentMassProperties.hpp"
#include "material/MaterialCompiler.hpp"
#include "matter/Lattice.hpp"

#include <cmath>
#include <cstdlib>
#include <functional>
#include <iostream>
#include <numbers>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace {

struct TestFailure : std::runtime_error {
    using std::runtime_error::runtime_error;
};

void require(bool condition, std::string_view message) {
    if (!condition) {
        throw TestFailure(std::string(message));
    }
}

banjo::MaterialDefinition testGlass() {
    banjo::MaterialDefinition material;
    material.name = "test_glass";
    material.model = banjo::MaterialModel::BrittleBond;
    material.density_kg_m3 = 2500.0;
    material.young_modulus_pa = 70.0e9;
    material.poisson_ratio = 0.22;
    material.tensile_strength_pa = 45.0e6;
    material.fracture_energy_j_m2 = 8.0;
    material.damping_ratio = 0.01;
    material.strength_variation = 0.05;
    material.seed = 42;
    material.calibration.activation_energy_scale = 1.0;
    material.calibration.damage_strain_multiplier = 8.0;
    material.calibration.break_strain_multiplier = 16.0;
    return material;
}

void sphereMassConverges() {
    const auto material = testGlass();
    constexpr double radius = 0.25;
    const auto compiled = banjo::compileBrittleMaterial(material, 0.04, 2U);
    const auto lattice = banjo::generateSphereLattice({radius, 0.04, 2U, 3U}, compiled);
    const double expected_mass =
        (4.0 / 3.0) * std::numbers::pi * radius * radius * radius * material.density_kg_m3;
    const double relative_error = std::abs(lattice.total_mass_kg - expected_mass) / expected_mass;
    require(relative_error < 0.05, "sampled sphere mass should be within 5% of analytic mass");
    require(banjo::length(lattice.rest_center_of_mass_m) < 1.0e-10,
            "symmetric sampled sphere should have a centered COM");
}

void intactSphereIsOneComponent() {
    const auto material = testGlass();
    const auto compiled = banjo::compileBrittleMaterial(material, 0.08, 2U);
    const auto lattice = banjo::generateSphereLattice({0.25, 0.08, 2U, 2U}, compiled);

    banjo::ImpactEvent impact;
    impact.body_a = 1;
    impact.body_b = 2;
    impact.contact_point_world_m = {-0.25, 1.0, 0.0};
    impact.normal_a_to_b = {1.0, 0.0, 0.0};

    banjo::BrittleBondSolver solver;
    auto active = solver.activate(
        2, lattice, compiled, {{0.0, 1.0, 0.0}, {}, {}, {}}, impact);
    const auto components = banjo::findConnectedComponents(active);
    require(components.size() == 1U, "an intact lattice must not contain precut pieces");
}

void brokenPlaneCreatesMultipleComponents() {
    const auto material = testGlass();
    const auto compiled = banjo::compileBrittleMaterial(material, 0.08, 2U);
    const auto lattice = banjo::generateSphereLattice({0.25, 0.08, 2U, 2U}, compiled);

    banjo::ImpactEvent impact;
    impact.body_a = 1;
    impact.body_b = 2;
    impact.contact_point_world_m = {-0.25, 1.0, 0.0};
    impact.normal_a_to_b = {1.0, 0.0, 0.0};

    banjo::BrittleBondSolver solver;
    auto active = solver.activate(
        2, lattice, compiled, {{0.0, 1.0, 0.0}, {}, {}, {}}, impact);

    for (std::size_t i = 0; i < lattice.bonds.size(); ++i) {
        const auto &bond = lattice.bonds[i];
        const double a = lattice.nodes[bond.node_a].local_position_m.x;
        const double b = lattice.nodes[bond.node_b].local_position_m.x;
        if ((a < 0.0 && b >= 0.0) || (b < 0.0 && a >= 0.0)) {
            active.bonds[i].alive = false;
        }
    }

    const auto components = banjo::findConnectedComponents(active);
    require(components.size() >= 2U, "broken bond topology should define multiple pieces");
}

void activationUsesEnergyNotNames() {
    const auto glass = testGlass();
    banjo::ActivationPolicy policy;
    banjo::ImpactEvent impact;
    impact.body_a = 1;
    impact.body_b = 2;
    impact.closing_speed_m_s = 0.1;
    impact.available_normal_energy_j = 0.01;

    auto decision = policy.evaluate(impact, {2, 0.25, glass, 0.0});
    require(!decision.activate, "tiny impact should not activate glass");

    impact.closing_speed_m_s = 8.0;
    impact.available_normal_energy_j = 1000.0;
    decision = policy.evaluate(impact, {2, 0.25, glass, 0.0});
    require(decision.activate, "energetic impact should activate glass");
}

void activationPreservesBulkLinearMomentum() {
    const auto material = testGlass();
    const auto compiled = banjo::compileBrittleMaterial(material, 0.08, 2U);
    const auto lattice = banjo::generateSphereLattice({0.25, 0.08, 2U, 2U}, compiled);

    banjo::ImpactEvent impact;
    impact.body_a = 1;
    impact.body_b = 2;
    impact.contact_point_world_m = {-0.25, 1.0, 0.0};
    impact.normal_a_to_b = {1.0, 0.0, 0.0};
    impact.available_normal_energy_j = 100.0;

    const banjo::Vec3 rigid_velocity{2.0, -0.5, 0.25};
    banjo::BrittleBondSolver solver;
    const auto active = solver.activate(
        2,
        lattice,
        compiled,
        {{0.0, 1.0, 0.0}, {}, rigid_velocity, {}},
        impact);

    banjo::Vec3 momentum{};
    double mass = 0.0;
    for (const auto &node : active.nodes) {
        mass += node.mass_kg;
        momentum += node.mass_kg * node.velocity_m_s;
    }
    require(banjo::length(momentum - mass * rigid_velocity) < 1.0e-8,
            "internal pulse must not add bulk linear momentum");
}

void fragmentMassSumsToLatticeMass() {
    const auto material = testGlass();
    const auto compiled = banjo::compileBrittleMaterial(material, 0.08, 1U);
    const auto lattice = banjo::generateSphereLattice({0.25, 0.08, 1U, 2U}, compiled);

    banjo::ImpactEvent impact;
    impact.body_a = 1;
    impact.body_b = 2;
    impact.normal_a_to_b = {1.0, 0.0, 0.0};
    banjo::BrittleBondSolver solver;
    auto active = solver.activate(
        2, lattice, compiled, {{0.0, 1.0, 0.0}, {}, {1.0, 0.0, 0.0}, {}}, impact);

    for (std::size_t i = 0; i < lattice.bonds.size(); ++i) {
        const auto &bond = lattice.bonds[i];
        const double a = lattice.nodes[bond.node_a].local_position_m.x;
        const double b = lattice.nodes[bond.node_b].local_position_m.x;
        if ((a < 0.0 && b >= 0.0) || (b < 0.0 && a >= 0.0)) {
            active.bonds[i].alive = false;
        }
    }

    const auto components = banjo::findConnectedComponents(active);
    double component_mass = 0.0;
    for (const auto &component : components) {
        component_mass +=
            banjo::calculateFragmentMassProperties(active, component.node_indices).mass_kg;
    }
    require(std::abs(component_mass - lattice.total_mass_kg) < 1.0e-10,
            "component masses must exactly account for lattice mass");
}

void energeticImpactProducesEmergentDamage() {
    const auto material = testGlass();
    const auto compiled = banjo::compileBrittleMaterial(material, 0.06, 2U);
    const auto lattice = banjo::generateSphereLattice({0.25, 0.06, 2U, 3U}, compiled);

    banjo::ImpactEvent impact;
    impact.body_a = 1;
    impact.body_b = 2;
    impact.contact_point_world_m = {-0.25, 1.0, 0.0};
    impact.normal_a_to_b = {1.0, 0.0, 0.0};
    impact.closing_speed_m_s = 8.0;
    impact.available_normal_energy_j = 1000.0;

    banjo::BrittleBondSolver solver({
        .substeps = 2,
        .constraint_iterations = 8,
        .floor_height_m = -10.0,
        .floor_friction = 0.0,
        .impact_internal_energy_fraction = 0.35,
        .maximum_internal_energy_j = 1000.0,
    });
    auto active = solver.activate(
        2, lattice, compiled, {{0.0, 1.0, 0.0}, {}, {}, {}}, impact);

    std::size_t broken = 0U;
    for (unsigned step = 0; step < 240U && broken == 0U; ++step) {
        broken = solver.step(active, 1.0 / 240.0, {}).total_broken_bonds;
    }
    require(broken > 0U, "an energetic localized impact should break emergent lattice bonds");
}

} // namespace

int main() {
    const std::vector<std::pair<std::string_view, std::function<void()>>> tests{
        {"sphere mass converges", sphereMassConverges},
        {"intact sphere is one component", intactSphereIsOneComponent},
        {"broken plane creates components", brokenPlaneCreatesMultipleComponents},
        {"activation uses energy", activationUsesEnergyNotNames},
        {"activation preserves momentum", activationPreservesBulkLinearMomentum},
        {"fragment mass sums", fragmentMassSumsToLatticeMass},
        {"energetic impact damages lattice", energeticImpactProducesEmergentDamage},
    };

    std::size_t failures = 0U;
    for (const auto &[name, test] : tests) {
        try {
            test();
            std::cout << "[PASS] " << name << '\n';
        } catch (const std::exception &error) {
            ++failures;
            std::cerr << "[FAIL] " << name << ": " << error.what() << '\n';
        }
    }

    std::cout << tests.size() - failures << '/' << tests.size() << " tests passed\n";
    return failures == 0U ? EXIT_SUCCESS : EXIT_FAILURE;
}
