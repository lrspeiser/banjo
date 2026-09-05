#include "fracture/BrittleBondSolver.hpp"
#include "fracture/ConnectedComponents.hpp"
#include "fracture/FragmentGeometry.hpp"
#include "material/MaterialCatalog.hpp"
#include "material/MaterialCompiler.hpp"
#include "physics/MechanicalAccounting.hpp"
#include "rigid/JoltWorld.hpp"
#include "sim/RollingBallExperiment.hpp"

#include <algorithm>
#include <cmath>
#include <functional>
#include <iostream>
#include <numeric>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace {
using namespace banjo;
void require(bool condition, std::string_view message) {
    if (!condition) throw std::runtime_error(std::string(message));
}
void near(double actual, double expected, double tolerance, std::string_view message) {
    if (!std::isfinite(actual) || std::abs(actual - expected) > tolerance)
        throw std::runtime_error(std::string(message) + ": actual=" + std::to_string(actual) +
                                 " expected=" + std::to_string(expected));
}
void nearVector(Vec3 actual, Vec3 expected, double tolerance, std::string_view message) {
    near(length(actual - expected), 0.0, tolerance, message);
}
Mat3 isotropic(double value) {
    Mat3 result;
    for (unsigned i = 0; i < 3; ++i) result.m[i][i] = value;
    return result;
}
ActiveMatter activate(const LatticeAsset &asset, const CompiledBrittleMaterial &material,
                     const RigidSnapshot &motion) {
    ImpactEvent impact;
    impact.body_a = 1; impact.body_b = 2; impact.normal_a_to_b = {1, 0, 0};
    BrittleBondSolver solver({.support_enabled = false});
    return solver.activate(2, asset, material, motion, impact);
}
void requireTransfer(const MechanicalTotals &before, const MechanicalTotals &after,
                     double relative_tolerance, bool preserve_kinetic = true) {
    near(after.mass_kg, before.mass_kg,
         relative_tolerance * before.mass_kg, "transfer mass");
    nearVector(after.centerOfMass(), before.centerOfMass(),
               relative_tolerance * std::max(1.0, length(before.centerOfMass())), "transfer COM");
    nearVector(after.linear_momentum_kg_m_s, before.linear_momentum_kg_m_s,
               relative_tolerance * std::max(1.0, length(before.linear_momentum_kg_m_s)), "transfer linear momentum");
    nearVector(after.angular_momentum_kg_m2_s, before.angular_momentum_kg_m2_s,
               relative_tolerance * std::max(1.0, length(before.angular_momentum_kg_m2_s)), "transfer angular momentum");
    if (preserve_kinetic) near(after.kinetic_energy_j, before.kinetic_energy_j,
        relative_tolerance * std::max(1.0, before.kinetic_energy_j), "transfer kinetic energy");
}

void spinningCellKeepsFiniteInertia() {
    LatticeAsset asset;
    asset.recipe.voxel_size_m = 0.002;
    ActiveMatter matter;
    matter.asset = &asset;
    const Vec3 spin{2, -3, 4};
    matter.nodes.push_back({{1, 2, 3}, {}, {0.2, 0.3, -0.4}, 0.02, spin});
    const std::vector<std::uint32_t> indices{0};
    const auto fragment = calculateFragmentMassProperties(matter, indices);
    const double expected_inertia = 0.02 * 0.002 * 0.002 / 6.0;
    nearVector(fragment.angular_momentum_kg_m2_s, expected_inertia * spin, 1e-20,
               "single cell intrinsic angular momentum");
    nearVector(fragment.angular_velocity_rad_s, spin, 1e-12,
               "small finite inertia must not zero the fragment spin");
    near(fragment.coarsening_kinetic_loss_j, 0.0, 1e-15, "single cell needs no coarsening loss");
}

void spinningSphereActivationAndHandoffAgree() {
    const auto definition = makeReferenceMaterial(MaterialPreset::Glass, 17);
    for (const double h : {0.04, 0.08, 0.12}) {
        const auto material = compileBrittleMaterial(definition, h, 2);
        const auto asset = generateSphereLattice({0.25, h, 2, 3}, material);
        const RigidSnapshot rigid{{2, -3, 1}, {std::cos(.37), 0, std::sin(.37), 0},
                                  {1.2, -0.4, 0.7}, {3, -2, 5}};
        // Symmetry of the sphere recipe gives an isotropic tensor independent
        // of the orientation. Check that assumption instead of silently using it.
        const double inertia = asset.rest_inertia_kg_m2.m[0][0];
        for (unsigned i = 0; i < 3; ++i)
            for (unsigned j = 0; j < 3; ++j)
                near(asset.rest_inertia_kg_m2.m[i][j], i == j ? inertia : 0.0,
                     1e-12 * inertia, "sampled sphere isotropic inertia");
        const auto active = activate(asset, material, rigid);
        const auto before = measureRigidMechanics({rigid, asset.total_mass_kg, isotropic(inertia)});
        const auto after = measureMaterialMechanics(active);
        requireTransfer(before, after, 1e-11);
        std::vector<std::uint32_t> indices(active.nodes.size());
        std::iota(indices.begin(), indices.end(), 0U);
        const auto fragment = calculateFragmentMassProperties(active, indices);
        nearVector(fragment.angular_velocity_rad_s, rigid.angular_velocity_rad_s,
                   1e-11, "intact sphere rigidification must preserve spin");
        near(fragment.coarsening_kinetic_loss_j, 0.0, 1e-9, "rigid motion has no coarsening loss");
    }
}

void splitTransferIncludesActualJoltAndDebrisState() {
    const auto material = compileBrittleMaterial(makeReferenceMaterial(MaterialPreset::Glass, 17), .08, 2);
    const auto asset = generateSphereLattice({.25, .08, 2, 3}, material);
    auto active = activate(asset, material, {{.3, 2, -.2}, {}, {1, -.3, .2}, {3, -2, 5}});
    // Kinematic transfer fixture, not an authoritative fracture algorithm.
    for (auto &bond : active.bonds) bond.alive = false;
    const auto before = measureMaterialMechanics(active);
    const auto components = findConnectedComponents(active);
    const auto built = buildFragmentRepresentations(active, components,
        {.maximum_rigid_fragments = 4, .minimum_nodes_per_rigid_fragment = 1});
    require(!built.debris_particles.empty(), "fixture must exercise overflow debris");
    JoltWorld world;
    world.setGravity({});
    world.addFragments(built.rigid_fragments);
    auto actual = world.mechanicalTotals();
    for (const auto &particle : built.debris_particles) {
        actual += measureRigidMechanics({
            {particle.position_world_m, {}, particle.velocity_m_s, particle.angular_velocity_rad_s},
            particle.mass_kg, particle.inertia_world_kg_m2});
    }
    // Actual Jolt state is single precision; core-only checks above are tighter.
    requireTransfer(before, actual, 2e-6);
    near(built.coarsening_kinetic_loss_j, 0.0, 1e-9, "singletons preserve all spin energy");
}

void nonRigidCoarseningReportsItsLoss() {
    LatticeAsset asset;
    asset.recipe.voxel_size_m = .01;
    ActiveMatter matter;
    matter.asset = &asset;
    matter.nodes.push_back({{-.2, 0, 0}, {}, {-2, 0, 0}, 1, {}});
    matter.nodes.push_back({{.2, 0, 0}, {}, {2, 0, 0}, 1, {}});
    const std::vector<std::uint32_t> indices{0, 1};
    const auto fragment = calculateFragmentMassProperties(matter, indices);
    near(fragment.source_kinetic_energy_j, 4.0, 1e-12, "opposing radial motion energy");
    near(fragment.rigid_kinetic_energy_j, 0.0, 1e-12, "zero net rigid motion");
    near(fragment.coarsening_kinetic_loss_j, 4.0, 1e-12, "lost internal motion must be explicit");
}

void positionCorrectionReportsAngularChange() {
    LatticeAsset asset;
    asset.recipe.voxel_size_m = .01;
    ActiveMatter matter;
    matter.asset = &asset;
    matter.nodes.push_back({{.99, 0, 0}, {}, {1, 2, 0}, 1, {}});
    CoupledSphereState sphere{{}, 1.0, 2.0, .8};
    const auto measure = [&]() {
        auto totals = measureMaterialMechanics(matter);
        totals += measureRigidMechanics({sphere.motion, sphere.mass_kg, isotropic(sphere.inertia_kg_m2)});
        return totals;
    };
    const auto before = measure();
    const auto stats = solveSphereMaterialContacts(matter, sphere, .001, {}, true);
    const auto after = measure();
    require(stats.impulse_contacts == 0 && stats.maximum_position_correction_m > 0.0,
            "separating overlap fixture isolates numerical position correction");
    near(after.kinetic_energy_j, before.kinetic_energy_j, 1e-12, "split correction keeps kinetic energy");
    nearVector(after.linear_momentum_kg_m_s, before.linear_momentum_kg_m_s, 1e-12,
               "split correction keeps linear momentum");
    require(length(stats.position_correction_angular_momentum_delta_kg_m2_s) > .001,
            "split correction is not automatically angular-momentum neutral");
    nearVector(after.angular_momentum_kg_m2_s - before.angular_momentum_kg_m2_s,
               stats.position_correction_angular_momentum_delta_kg_m2_s, 1e-12,
               "numerical angular change must be explicitly recorded");
}

void actualJoltFreeFlightAccountsForGravity() {
    JoltWorld world;
    const Vec3 gravity{0, -9.81, 0};
    world.setGravity(gravity);
    world.addBall({.body_id = 1, .radius_m = .25,
        .material = makeReferenceMaterial(MaterialPreset::Iron, 17),
        .position_world_m = {1, 3, 2}, .linear_velocity_m_s = {2, 1, -.5},
        .angular_velocity_rad_s = {1, 2, 3}});
    const auto before = world.mechanicalTotals(gravity);
    constexpr double dt = 1.0 / 240.0;
    constexpr unsigned steps = 60;
    for (unsigned i = 0; i < steps; ++i) world.step(dt);
    const auto after = world.mechanicalTotals(gravity);
    const Vec3 external_impulse = before.mass_kg * (dt * steps) * gravity;
    nearVector(after.linear_momentum_kg_m_s - before.linear_momentum_kg_m_s,
               external_impulse, 2e-5 * length(external_impulse), "free-flight gravitational impulse");
    // Semi-implicit Euler loses O(dt) total K+U, unlike unexplained input work.
    const double euler_loss = .5 * before.mass_kg * lengthSquared(gravity) * steps * dt * dt;
    near(after.mechanicalEnergy() - before.mechanicalEnergy(), -euler_loss,
         2e-3 * euler_loss, "gravity energy residual must follow the integration rule");
}

void runtimeTransferAuditsAreMeasured() {
    for (const bool supported : {false, true}) {
        ExperimentSettings settings;
        settings.support_enabled = supported;
        settings.gravity_m_s2 = supported ? Vec3{0, -9.81, 0} : Vec3{};
        settings.target_initial_speed_m_s = 1.0; // Nonzero target spin exercises activation.
        settings.minimum_material_steps = 20;
        settings.stable_material_steps_before_handoff = 10;
        settings.maximum_material_steps = 120;
        RollingBallExperiment experiment(settings);
        const auto initial = experiment.mechanicalTotals();
        for (unsigned i = 0; i < 240 && experiment.phase() != ExperimentPhase::RigidFragments; ++i)
            experiment.stepFixed();
        const auto &stats = experiment.stats();
        require(stats.activation_transfer.measured && stats.fragment_transfer.measured,
                "runtime must measure both representation transitions");
        requireTransfer(stats.activation_transfer.before, stats.activation_transfer.after, 2e-6);
        requireTransfer(stats.fragment_transfer.before, stats.fragment_transfer.after, 2e-6, false);
        const double energy_residual = stats.fragment_transfer.after.mechanicalEnergy() -
            stats.fragment_transfer.before.mechanicalEnergy() +
            stats.coarsening_kinetic_loss_j + stats.coarsening_elastic_loss_j;
        near(energy_residual, 0.0,
             2e-6 * std::max(1.0, stats.fragment_transfer.before.mechanicalEnergy()),
             "handoff mechanical loss must reconcile with actual inserted state");
        require(stats.coarsening_kinetic_loss_j >= -1e-8, "passive rigidification cannot create energy");
        const auto final = experiment.mechanicalTotals();
        const Vec3 recorded_numerical_angular_change =
            stats.contact_correction_angular_momentum_delta_kg_m2_s +
            stats.constraint_angular_momentum_delta_kg_m2_s;
        std::cout << (supported ? "supported" : "isolated")
                  << " handoff energy residual=" << energy_residual
                  << " J; whole-run delta-P=" << length(final.linear_momentum_kg_m_s - initial.linear_momentum_kg_m_s)
                  << " N*s; whole-run delta-L=" << length(final.angular_momentum_kg_m2_s - initial.angular_momentum_kg_m2_s)
                  << " kg*m^2/s (not a closed step ledger)\n";
        if (!supported) {
            const auto residual = final.angular_momentum_kg_m2_s - initial.angular_momentum_kg_m2_s -
                recorded_numerical_angular_change;
            std::cout << "isolated angular correction=" << length(recorded_numerical_angular_change)
                      << "; remainder=" << length(residual) << " kg*m^2/s\n";
        }
    }
}
} // namespace

int main() {
    const std::vector<std::pair<std::string_view, std::function<void()>>> tests{
        {"small spinning cell", spinningCellKeepsFiniteInertia},
        {"rotated spinning sphere transfers", spinningSphereActivationAndHandoffAgree},
        {"actual Jolt and debris transfer", splitTransferIncludesActualJoltAndDebrisState},
        {"explicit non-rigid coarsening loss", nonRigidCoarseningReportsItsLoss},
        {"position correction angular ledger", positionCorrectionReportsAngularChange},
        {"actual Jolt gravity ledger", actualJoltFreeFlightAccountsForGravity},
        {"runtime transition audits", runtimeTransferAuditsAreMeasured},
    };
    unsigned failures = 0;
    for (const auto &[name, test] : tests) {
        try { test(); std::cout << "[PASS] " << name << '\n'; }
        catch (const std::exception &e) { ++failures; std::cerr << "[FAIL] " << name << ": " << e.what() << '\n'; }
    }
    return failures ? 1 : 0;
}
