#include "physics/ConservativeStep.hpp"
#include "physics/MechanicalAccounting.hpp"
#include "material/MaterialCatalog.hpp"
#include "material/MaterialCompiler.hpp"
#include <cmath>
#include <functional>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
using namespace banjo;
void require(bool condition, const char *message) { if (!condition) throw std::runtime_error(message); }
void near(double actual, double expected, double tolerance, const char *message) {
    if (!std::isfinite(actual) || std::abs(actual - expected) > tolerance)
        throw std::runtime_error(std::string(message) + ": " + std::to_string(actual) + " vs " + std::to_string(expected));
}
struct Fixture {
    LatticeAsset asset;
    ActiveMatter matter;
    Fixture() {
        asset.recipe.voxel_size_m = .02;
        matter.asset = &asset;
        matter.nodes = {{{-.5, 0, 0}, {}, {-.2, 0, 0}, 1, {}}, {{.5, 0, 0}, {}, {.2, 0, 0}, 1, {}}};
        addBond(0, 1, .01);
    }
    void addBond(unsigned a, unsigned b, double compliance) {
        asset.bonds.push_back({.node_a = a, .node_b = b,
            .rest_length_m = length(matter.nodes[b].position_world_m - matter.nodes[a].position_world_m),
            .compliance = compliance});
        matter.bonds.emplace_back();
    }
};
MechanicalTotals totals(const ActiveMatter &matter, const CoupledSphereState *sphere = nullptr, Vec3 gravity = {}) {
    auto result = measureMaterialMechanics(matter, gravity);
    if (sphere) {
        Mat3 inertia;
        for (unsigned i = 0; i < 3; ++i) inertia.m[i][i] = sphere->inertia_kg_m2;
        result += measureRigidMechanics({sphere->motion, sphere->mass_kg, inertia}, gravity);
    }
    return result;
}
void momentumAndEnergy(const MechanicalTotals &before, const MechanicalTotals &after,
                       double energy_loss = 0, double tolerance = 1e-9) {
    near(length(after.linear_momentum_kg_m_s - before.linear_momentum_kg_m_s), 0, tolerance, "linear momentum");
    near(length(after.angular_momentum_kg_m2_s - before.angular_momentum_kg_m2_s), 0, tolerance, "angular momentum");
    near(after.mechanicalEnergy() + energy_loss, before.mechanicalEnergy(), tolerance, "energy including named loss");
}
void radialAnalyticalReference() {
    for (const double dt : {.001, .01, .1, 1.0}) {
        Fixture f;
        const auto before = totals(f.matter);
        const auto result = tryConservativeStep(f.matter, dt);
        require(result.converged, "radial spring must converge");
        const double extension = .4 * dt / (1 + .5 * dt * dt / .01);
        near(f.matter.nodes[1].position_world_m.x - f.matter.nodes[0].position_world_m.x - 1,
             extension, 1e-12, "midpoint scalar spring displacement");
        near(f.matter.nodes[1].velocity_m_s.x - f.matter.nodes[0].velocity_m_s.x,
             .4 - dt * extension / .01, 1e-12, "midpoint scalar spring relative velocity");
        momentumAndEnergy(before, totals(f.matter));
    }
}
void rotatingSpringConservesOverTime() {
    Fixture f;
    f.asset.bonds[0].compliance = .001;
    const Vec3 boost{.3, -.1, .2};
    const Vec3 offset{2, -3, 1};
    for (auto &node : f.matter.nodes) {
        node.velocity_m_s = boost + cross(Vec3{1, 2, 3}, node.position_world_m);
        node.position_world_m += offset;
        node.spin_angular_velocity_rad_s = {1, -2, 3};
    }
    const auto before = totals(f.matter);
    for (unsigned i = 0; i < 100; ++i) require(tryConservativeStep(f.matter, .01).converged, "rotating spring converges");
    const auto after = totals(f.matter);
    momentumAndEnergy(before, after, 0, 1e-8);
    near(length(after.centerOfMass() - before.centerOfMass() - boost), 0, 1e-11, "COM follows its free velocity");
}
void threeDimensionalNetwork() {
    Fixture f;
    f.asset.bonds.clear(); f.matter.bonds.clear();
    f.matter.nodes = {{{0, 0, 0}, {}, {.1, -.2, .3}, 1, {}},
        {{1, 0, 0}, {}, {-.2, .3, -.1}, 2, {}}, {{0, 1, 0}, {}, {.3, .2, -.3}, 3, {}},
        {{0, 0, 1}, {}, {-.1, -.3, .2}, 4, {}}};
    for (unsigned a = 0; a < 4; ++a) for (unsigned b = a + 1; b < 4; ++b) f.addBond(a, b, .001);
    const auto before = totals(f.matter);
    for (unsigned i = 0; i < 20; ++i) require(tryConservativeStep(f.matter, .01).converged, "3D spring network converges");
    momentumAndEnergy(before, totals(f.matter), 0, 1e-8);
}
void supportedElasticImpact() {
    Fixture f;
    f.matter.nodes[0].position_world_m = {1, .05, .2};
    f.matter.nodes[1].position_world_m = {1, 1.05, .2};
    for (auto &node : f.matter.nodes) node.velocity_m_s = {0, -1, 0};
    f.asset.bonds[0].compliance = .001;
    const auto plane = makeSupportPlane({}, {0, 1, 0});
    const Vec3 gravity{0, -10, 0};
    const auto before = totals(f.matter, nullptr, gravity);
    const auto old = f.matter.nodes;
    const auto result = tryConservativeStep(f.matter, .1, gravity, nullptr, {.support = &plane});
    require(result.converged, "coupled elastic floor impact converges");
    const auto after = totals(f.matter, nullptr, gravity);
    near(after.mechanicalEnergy() + result.normal_contact_loss_j, before.mechanicalEnergy(), 1e-8,
         "floor cannot inject unbudgeted spring energy");
    near(length(after.linear_momentum_kg_m_s - before.linear_momentum_kg_m_s - .1 * before.mass_kg * gravity -
                result.support_impulse_kg_m_s), 0, 1e-9, "support and gravity linear reactions");
    Vec3 gravity_torque;
    for (std::size_t i = 0; i < old.size(); ++i)
        gravity_torque += cross(.5 * (old[i].position_world_m + f.matter.nodes[i].position_world_m),
                               .1 * old[i].mass_kg * gravity);
    near(length(after.angular_momentum_kg_m2_s - before.angular_momentum_kg_m2_s - gravity_torque -
                result.support_angular_impulse_kg_m2_s), 0, 1e-9, "support and gravity angular reactions");
    require(f.matter.nodes[0].position_world_m.y >= -1e-10, "material cannot pass through support");
}
void finiteSphereAndElasticTargetAdvanceTogether() {
    Fixture f;
    f.matter.nodes[0].position_world_m = {.6, 0, 0};
    f.matter.nodes[1].position_world_m = {1.6, 0, 0};
    for (auto &node : f.matter.nodes) node.velocity_m_s = {};
    CoupledSphereState sphere{{{}, {}, {2, 0, 0}, {}}, .5, 2, .2};
    const auto before = totals(f.matter, &sphere);
    const auto result = tryConservativeStep(f.matter, .1, {}, &sphere);
    require(result.converged, "finite-sphere coupled solve converges");
    const auto after = totals(f.matter, &sphere);
    momentumAndEnergy(before, after, result.normal_contact_loss_j, 1e-8);
    near(after.centerOfMass().x - before.centerOfMass().x, .1, 1e-10, "all participants share the same physical clock");
    require(length(f.matter.nodes[0].position_world_m - sphere.motion.center_of_mass_world_m) >= .5 - 1e-10,
            "coupled elastic target remains outside sphere");
    require(after.elastic_energy_j > 0 && sphere.motion.linear_velocity_m_s.x < 2,
            "contact must supply strain energy from finite-mass motion");
}
void failedSolveIsTransactional() {
    Fixture f;
    const auto before = f.matter.nodes;
    const auto result = tryConservativeStep(f.matter, .1, {}, nullptr, {.maximum_iterations = 1});
    require(!result.converged, "insufficient iteration budget must be reported");
    for (std::size_t i = 0; i < before.size(); ++i) {
        near(length(before[i].position_world_m - f.matter.nodes[i].position_world_m), 0, 0, "failed solve preserves positions");
        near(length(before[i].velocity_m_s - f.matter.nodes[i].velocity_m_s), 0, 0, "failed solve preserves velocities");
    }
    f.asset.bonds.clear(); f.matter.bonds.clear(); f.matter.nodes.resize(1);
    f.matter.nodes[0].position_world_m = {-2, 0, 0};
    f.matter.nodes[0].velocity_m_s = {40, 0, 0};
    CoupledSphereState sphere{{}, .5, 2, .2};
    const auto crossing = tryConservativeStep(f.matter, .1, {}, &sphere);
    require(!crossing.converged, "a trajectory crossing the sphere cannot silently tunnel");
    near(f.matter.nodes[0].position_world_m.x, -2, 0, "rejected crossing preserves state");
}

void offCenterContactAndFrameInvariance() {
    Fixture original, moved;
    original.matter.nodes[0].position_world_m = {.6, .15, .05};
    original.matter.nodes[1].position_world_m = {1.6, .15, .05};
    for (auto &node : original.matter.nodes) node.velocity_m_s = {};
    moved.matter.nodes = original.matter.nodes;
    const Quat rotation{std::cos(.31), 0, std::sin(.31), 0};
    const Vec3 boost{1, -.3, .2}, offset{2, -3, 1};
    for (auto &node : moved.matter.nodes) {
        node.position_world_m = rotation.rotate(node.position_world_m) + offset;
        node.velocity_m_s = rotation.rotate(node.velocity_m_s) + boost;
    }
    CoupledSphereState sphere{{{}, {}, {2, 0, 0}, {0, 0, 3}}, .5, 2, .2};
    auto transformed = sphere;
    transformed.motion.center_of_mass_world_m = offset;
    transformed.motion.linear_velocity_m_s = rotation.rotate(sphere.motion.linear_velocity_m_s) + boost;
    transformed.motion.angular_velocity_rad_s = rotation.rotate(sphere.motion.angular_velocity_rad_s);
    transformed.motion.orientation_world = rotation;
    const auto before = totals(original.matter, &sphere);
    const auto moved_before = totals(moved.matter, &transformed);
    const auto a = tryConservativeStep(original.matter, .1, {}, &sphere);
    const auto b = tryConservativeStep(moved.matter, .1, {}, &transformed);
    require(a.converged && b.converged, "off-center contact converges in both frames");
    momentumAndEnergy(before, totals(original.matter, &sphere), a.normal_contact_loss_j, 1e-8);
    momentumAndEnergy(moved_before, totals(moved.matter, &transformed), b.normal_contact_loss_j, 1e-8);
    for (std::size_t i = 0; i < original.matter.nodes.size(); ++i) {
        near(length(moved.matter.nodes[i].position_world_m - rotation.rotate(original.matter.nodes[i].position_world_m) -
                    offset - .1*boost), 0, 1e-9, "rotated/boosted contact trajectory");
    }
    near(sphere.motion.orientation_world.w, std::cos(.15), 1e-12, "free sphere spin advances orientation");
    near(sphere.motion.orientation_world.z, std::sin(.15), 1e-12, "free sphere spin axis");
}

void sampledLatticeReference() {
    auto material = makeReferenceMaterial(MaterialPreset::Glass, 17);
    // A deliberately softer elastic fixture separates network-solver accuracy
    // from the as-yet uncalibrated glass constitutive preset.
    material.young_modulus_pa = 1e5;
    const auto compiled = compileBrittleMaterial(material, .12, 1);
    const auto asset = generateSphereLattice({.25, .12, 1, 2}, compiled);
    ActiveMatter matter;
    matter.asset = &asset;
    matter.material = compiled;
    matter.bonds.resize(asset.bonds.size());
    for (const auto &node : asset.nodes) matter.nodes.push_back({node.local_position_m, {},
        Vec3{.1, -.2, .3} + cross(Vec3{1, -2, 3}, node.local_position_m),
        node.represented_volume_m3 * compiled.density_kg_m3, {1, -2, 3}});
    const auto before = totals(matter);
    unsigned iterations = 0;
    for (unsigned i = 0; i < 10; ++i) {
        const auto result = tryConservativeStep(matter, .002);
        require(result.converged, "sampled material network converges");
        iterations += result.iterations;
    }
    momentumAndEnergy(before, totals(matter), 0, 1e-7);
    std::cout << "sampled reference nodes=" << matter.nodes.size() << " bonds=" << matter.bonds.size()
              << " iterations=" << iterations << '\n';
}

void energyCheckRejectsUnresolvedNetwork() {
    Fixture f;
    f.matter.nodes.push_back({{0, 1, 0}, {}, {.4, -.3, .2}, 1, {}});
    f.addBond(0, 2, .01);
    f.addBond(1, 2, .01);
    const auto original = f.matter.nodes;
    const auto result = tryConservativeStep(f.matter, .1, {}, nullptr,
        {.maximum_iterations = 1, .velocity_tolerance_m_s = 1e6, .relative_energy_tolerance = 1e-12});
    require(result.balance_measured && std::abs(result.energy_residual_j) > 1e-10,
            "fixture must reach the energy audit with an unresolved constitutive update");
    require(!result.converged, "a loose iteration stop cannot bypass the energy balance");
    for (std::size_t i = 0; i < original.size(); ++i)
        near(length(f.matter.nodes[i].velocity_m_s - original[i].velocity_m_s), 0, 0,
             "energy rejection preserves the starting state");
}

void localAndGlobalSolveAgree() {
    Fixture global, local;
    global.matter.nodes.push_back({{0, 1, .2}, {}, {.4, -.3, .2}, 2, {}});
    global.addBond(0, 2, .001);
    global.addBond(1, 2, .002);
    local.asset = global.asset;
    local.matter.nodes = global.matter.nodes;
    local.matter.bonds = global.matter.bonds;
    for (unsigned step = 0; step < 20; ++step) {
        require(tryConservativeStep(global.matter, .01).converged, "global comparison converges");
        require(tryConservativeStep(local.matter, .01, {}, nullptr, {.global_elastic_solve = false}).converged,
                "local comparison converges");
        for (std::size_t i = 0; i < global.matter.nodes.size(); ++i) {
            near(length(global.matter.nodes[i].position_world_m - local.matter.nodes[i].position_world_m),
                 0, 1e-8, "independent elastic solvers agree on position");
            near(length(global.matter.nodes[i].velocity_m_s - local.matter.nodes[i].velocity_m_s),
                 0, 1e-8, "independent elastic solvers agree on velocity");
        }
    }
}

void analyticalTimeStepConvergence() {
    // Two unit masses joined by k=100 N/m have relative frequency sqrt(200).
    // The extension stays positive/small enough that the 1D harmonic oracle
    // does not cross the nondifferentiable collapsed-spring configuration.
    const double frequency = std::sqrt(200.0), duration = .2;
    const double exact_extension = .4 / frequency * std::sin(frequency * duration);
    const double exact_velocity = .4 * std::cos(frequency * duration);
    double previous_position_error = 0, previous_velocity_error = 0;
    for (const unsigned steps : {10u, 20u, 40u}) {
        Fixture f;
        for (unsigned i = 0; i < steps; ++i)
            require(tryConservativeStep(f.matter, duration / steps).converged, "time refinement converges");
        const double position_error = std::abs(f.matter.nodes[1].position_world_m.x -
            f.matter.nodes[0].position_world_m.x - 1 - exact_extension);
        const double velocity_error = std::abs(f.matter.nodes[1].velocity_m_s.x -
            f.matter.nodes[0].velocity_m_s.x - exact_velocity);
        if (previous_position_error > 0) {
            require(previous_position_error / position_error > 3.8 && previous_position_error / position_error < 4.2,
                    "radial trajectory has second-order position convergence");
            require(previous_velocity_error / velocity_error > 3.8 && previous_velocity_error / velocity_error < 4.2,
                    "radial trajectory has second-order velocity convergence");
        }
        previous_position_error = position_error;
        previous_velocity_error = velocity_error;
        std::cout << "radial dt=" << duration / steps << " position_error_m=" << position_error
                  << " velocity_error_m_s=" << velocity_error << '\n';
    }
}

void actualGlassAtPracticalStep() {
    const auto compiled = compileBrittleMaterial(makeReferenceMaterial(MaterialPreset::Glass, 17), .04, 2);
    const auto asset = generateSphereLattice({.25, .04, 2, 3}, compiled);
    ActiveMatter matter;
    matter.asset = &asset;
    matter.material = compiled;
    matter.bonds.resize(asset.bonds.size());
    for (const auto &node : asset.nodes) matter.nodes.push_back({node.local_position_m, {},
        Vec3{.3, -.1, .2} + cross(Vec3{1, -2, 3}, node.local_position_m),
        node.represented_volume_m3 * compiled.density_kg_m3, {1, -2, 3}});
    const auto before = totals(matter);
    const auto original = matter.nodes;
    const auto failed = tryConservativeStep(matter, .002, {}, nullptr,
        {.maximum_iterations = 1, .maximum_linear_iterations = 1});
    require(!failed.converged, "insufficient global solve budget is rejected");
    for (std::size_t i = 0; i < original.size(); ++i) {
        near(length(matter.nodes[i].position_world_m - original[i].position_world_m), 0, 0,
             "limited global solve retains positions");
        near(length(matter.nodes[i].velocity_m_s - original[i].velocity_m_s), 0, 0,
             "limited global solve retains velocities");
    }
    unsigned linear_iterations = 0;
    for (unsigned step = 0; step < 5; ++step) {
        const auto result = tryConservativeStep(matter, .002);
        require(result.converged && result.balance_measured, "full glass lattice passes unchanged acceptance checks");
        require(result.constitutive_velocity_residual_m_s <= 1e-9, "glass constitutive residual");
        linear_iterations += result.linear_iterations;
    }
    // This is a numerical regression of the actual preset, not calibration or
    // a claim that unresolved glass vibration is accurate at this timestep.
    momentumAndEnergy(before, totals(matter), 0, 1e-8);
    std::cout << "actual glass nodes=" << matter.nodes.size() << " bonds=" << matter.bonds.size()
              << " linear_iterations=" << linear_iterations << '\n';
}
}

int main() {
    const std::vector<std::pair<const char *, std::function<void()>>> tests{
        {"radial spring analytical reference", radialAnalyticalReference},
        {"rotating spring energy and angular momentum", rotatingSpringConservesOverTime},
        {"three-dimensional elastic network", threeDimensionalNetwork},
        {"coupled support and strain energy", supportedElasticImpact},
        {"finite sphere and elastic target", finiteSphereAndElasticTargetAdvanceTogether},
        {"transactional rejection and no tunneling", failedSolveIsTransactional},
        {"off-center contact and frame invariance", offCenterContactAndFrameInvariance},
        {"sampled elastic lattice", sampledLatticeReference},
        {"energy audit rejects unresolved solve", energyCheckRejectsUnresolvedNetwork},
        {"local and global elastic solutions agree", localAndGlobalSolveAgree},
        {"analytical timestep convergence", analyticalTimeStepConvergence},
        {"actual glass at practical timestep", actualGlassAtPracticalStep}};
    unsigned failures = 0;
    for (const auto &[name, test] : tests) {
        try { test(); std::cout << "[PASS] " << name << '\n'; }
        catch (const std::exception &error) { ++failures; std::cerr << "[FAIL] " << name << ": " << error.what() << '\n'; }
    }
    return failures ? 1 : 0;
}
