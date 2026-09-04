#include "fracture/ActivationPolicy.hpp"
#include "fracture/BrittleBondSolver.hpp"
#include "fracture/ConnectedComponents.hpp"
#include "fracture/FragmentMassProperties.hpp"
#include "material/MaterialCompiler.hpp"
#include "matter/Lattice.hpp"
#include "rigid/JoltWorld.hpp"

#include <algorithm>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <numbers>
#include <optional>
#include <stdexcept>
#include <vector>

namespace {

banjo::MaterialDefinition ironMaterial() {
    banjo::MaterialDefinition material;
    material.name = "iron";
    material.model = banjo::MaterialModel::RigidOnly;
    material.density_kg_m3 = 7870.0;
    material.young_modulus_pa = 211.0e9;
    material.poisson_ratio = 0.29;
    material.tensile_strength_pa = 200.0e6;
    material.fracture_energy_j_m2 = 100000.0;
    material.friction = 0.55;
    material.restitution = 0.08;
    return material;
}

banjo::MaterialDefinition glassMaterial() {
    banjo::MaterialDefinition material;
    material.name = "brittle_glass_v0";
    material.model = banjo::MaterialModel::BrittleBond;
    material.density_kg_m3 = 2500.0;
    material.young_modulus_pa = 70.0e9;
    material.poisson_ratio = 0.22;
    material.tensile_strength_pa = 45.0e6;
    material.fracture_energy_j_m2 = 8.0;
    material.friction = 0.35;
    material.restitution = 0.12;
    material.damping_ratio = 0.015;
    material.strength_variation = 0.12;
    material.seed = 971;
    material.calibration.activation_energy_scale = 1.0;
    material.calibration.damage_strain_multiplier = 8.0;
    material.calibration.break_strain_multiplier = 16.0;
    return material;
}

} // namespace

int main() {
    try {
        constexpr banjo::MatterBodyId kIronBall = 1;
        constexpr banjo::MatterBodyId kGlassBall = 2;
        constexpr double kRadius = 0.25;
        constexpr double kVoxelSize = 0.04;
        constexpr double kRigidDt = 1.0 / 120.0;
        constexpr double kMaterialDt = 1.0 / 240.0;

        const banjo::MaterialDefinition iron = ironMaterial();
        const banjo::MaterialDefinition glass = glassMaterial();
        const banjo::CompiledBrittleMaterial compiled_glass =
            banjo::compileBrittleMaterial(glass, kVoxelSize, 2U);
        const banjo::LatticeAsset glass_lattice = banjo::generateSphereLattice(
            {kRadius, kVoxelSize, 2U, 3U}, compiled_glass);

        const double analytic_glass_mass =
            (4.0 / 3.0) * std::numbers::pi * kRadius * kRadius * kRadius *
            glass.density_kg_m3;

        std::cout << std::fixed << std::setprecision(4);
        std::cout << "Banjo rolling-ball material laboratory\n";
        std::cout << "  glass nodes: " << glass_lattice.nodes.size() << '\n';
        std::cout << "  intact bonds: " << glass_lattice.bonds.size() << '\n';
        std::cout << "  represented mass: " << glass_lattice.total_mass_kg << " kg\n";
        std::cout << "  analytic mass: " << analytic_glass_mass << " kg\n";

        banjo::JoltWorld rigid_world;
        rigid_world.addFloor();
        rigid_world.addBall({
            kIronBall,
            kRadius,
            iron,
            {-1.50, kRadius + 0.001, 0.0},
            {8.0, 0.0, 0.0},
            {0.0, 0.0, -8.0 / kRadius},
        });
        rigid_world.addBall({
            kGlassBall,
            kRadius,
            glass,
            {0.0, kRadius + 0.001, 0.0},
            {0.0, 0.0, 0.0},
            {0.0, 0.0, 0.0},
        });

        banjo::ActivationPolicy activation_policy;
        std::optional<banjo::ImpactEvent> activating_impact;
        banjo::ActivationDecision decision;

        for (unsigned step = 0; step < 600U && !activating_impact; ++step) {
            rigid_world.step(kRigidDt);
            std::vector<banjo::ImpactEvent> impacts = rigid_world.drainImpacts();
            std::sort(impacts.begin(), impacts.end(), [](const auto &a, const auto &b) {
                if (a.fixed_tick != b.fixed_tick) {
                    return a.fixed_tick < b.fixed_tick;
                }
                if (a.body_a != b.body_a) {
                    return a.body_a < b.body_a;
                }
                return a.body_b < b.body_b;
            });

            for (const banjo::ImpactEvent &impact : impacts) {
                if (!impact.involves(kGlassBall)) {
                    continue;
                }
                decision = activation_policy.evaluate(
                    impact, {kGlassBall, kRadius, glass, 0.0});
                std::cout << "Impact at tick " << impact.fixed_tick
                          << ": speed=" << impact.closing_speed_m_s
                          << " m/s, energy=" << impact.available_normal_energy_j
                          << " J, threshold=" << decision.threshold_energy_j
                          << " J, normalized=" << decision.normalized_energy << '\n';
                if (decision.activate) {
                    activating_impact = impact;
                    break;
                }
            }
        }

        if (!activating_impact) {
            std::cerr << "No activating iron/glass impact was detected.\n";
            return EXIT_FAILURE;
        }

        // Method A handoff: let Jolt resolve the rigid collision, then transfer the glass
        // post-contact bulk state into material nodes. The fracture pulse adds internal energy
        // with zero net translation so the collision impulse is not applied twice.
        const banjo::RigidSnapshot post_contact_glass = rigid_world.snapshot(kGlassBall);
        rigid_world.removeAndDestroy(kGlassBall);

        banjo::BrittleBondSolver solver({
            .substeps = 2,
            .constraint_iterations = 8,
            .floor_height_m = 0.0,
            .floor_friction = 0.4,
            .impact_internal_energy_fraction = 0.18,
            .maximum_internal_energy_j = 5000.0,
        });
        banjo::ActiveMatter active_glass = solver.activate(
            kGlassBall,
            glass_lattice,
            compiled_glass,
            post_contact_glass,
            *activating_impact);

        std::size_t last_broken = 0U;
        unsigned stable_steps = 0U;
        for (unsigned step = 0; step < 480U; ++step) {
            const banjo::MaterialStepStats stats =
                solver.step(active_glass, kMaterialDt, {0.0, -9.81, 0.0});
            if (stats.total_broken_bonds == last_broken) {
                ++stable_steps;
            } else {
                stable_steps = 0U;
                last_broken = stats.total_broken_bonds;
            }
            if (step % 30U == 0U || stats.broken_bonds_this_step > 0U) {
                std::cout << "Material step " << step
                          << ": broken=" << stats.total_broken_bonds
                          << ", newly broken=" << stats.broken_bonds_this_step
                          << ", max stretch=" << stats.maximum_tensile_stretch << '\n';
            }
            if (stable_steps >= 120U && stats.total_broken_bonds > 0U) {
                break;
            }
        }

        const std::vector<banjo::FragmentComponent> components =
            banjo::findConnectedComponents(active_glass);
        std::cout << "Discovered " << components.size()
                  << " connected material component(s).\n";

        double combined_mass = 0.0;
        banjo::Vec3 combined_linear_momentum{};
        const std::size_t report_count = std::min<std::size_t>(components.size(), 10U);
        for (std::size_t i = 0; i < components.size(); ++i) {
            const auto properties = banjo::calculateFragmentMassProperties(
                active_glass, components[i].node_indices);
            combined_mass += properties.mass_kg;
            combined_linear_momentum += properties.mass_kg * properties.linear_velocity_m_s;
            if (i < report_count) {
                std::cout << "  component " << i
                          << ": nodes=" << components[i].node_indices.size()
                          << ", mass=" << properties.mass_kg << " kg"
                          << ", speed=" << banjo::length(properties.linear_velocity_m_s)
                          << " m/s\n";
            }
        }

        std::cout << "Combined component mass: " << combined_mass << " kg\n";
        std::cout << "Combined linear momentum: ("
                  << combined_linear_momentum.x << ", "
                  << combined_linear_momentum.y << ", "
                  << combined_linear_momentum.z << ") kg*m/s\n";
        std::cout << "Next milestone: mesh these components, build convex proxies, and batch-add them to Jolt.\n";
        return EXIT_SUCCESS;
    } catch (const std::exception &error) {
        std::cerr << "Fatal error: " << error.what() << '\n';
        return EXIT_FAILURE;
    }
}
