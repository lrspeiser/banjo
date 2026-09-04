#include "core/Plane.hpp"
#include "fracture/BrittleBondSolver.hpp"
#include "material/MaterialCatalog.hpp"
#include "material/MaterialCompiler.hpp"
#include "matter/Lattice.hpp"

#include <cmath>
#include <cstdlib>
#include <functional>
#include <iostream>
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

struct Fixture {
    Fixture()
        : material(banjo::makeReferenceMaterial(
              banjo::MaterialPreset::Glass,
              42)),
          compiled(banjo::compileBrittleMaterial(material, 0.08, 2U)),
          lattice(banjo::generateSphereLattice(
              {0.25, 0.08, 2U, 3U},
              compiled)),
          solver({
              .substeps = 1,
              .constraint_iterations = 1,
              .use_support_plane = true,
              .support_plane = banjo::makeSupportPlane(
                  {0.0, -10.0, 0.0},
                  {0.0, 1.0, 0.0}),
              .surface_dynamic_friction = 0.0,
              .surface_restitution = 0.0,
              .impact_internal_energy_fraction = 0.0,
              .maximum_internal_energy_j = 0.0,
          }) {
        banjo::ImpactEvent impact;
        impact.body_a = 1;
        impact.body_b = 2;
        active = solver.activate(
            2,
            lattice,
            compiled,
            {{0.0, 0.0, 0.0}, {}, {}, {}},
            impact);
    }

    Fixture(const Fixture &) = delete;
    Fixture &operator=(const Fixture &) = delete;
    Fixture(Fixture &&) = delete;
    Fixture &operator=(Fixture &&) = delete;

    banjo::MaterialDefinition material;
    banjo::CompiledBrittleMaterial compiled;
    banjo::LatticeAsset lattice;
    banjo::BrittleBondSolver solver;
    banjo::ActiveMatter active;
};

void compiledStrengthsProduceDistinctFailureStrains() {
    Fixture fixture;
    require(
        fixture.compiled.compression_damage_start_strain >
            fixture.compiled.damage_start_stretch,
        "glass compression threshold should reflect its greater compressive strength");
    require(
        fixture.compiled.shear_damage_start_strain >
            fixture.compiled.damage_start_stretch,
        "glass shear threshold should be compiled from shear strength and shear modulus");
    require(
        fixture.compiled.compression_damage_end_strain >
            fixture.compiled.compression_damage_start_strain,
        "compression damage must have a progressive interval");
}

void rigidRotationDoesNotCreateMaterialStrain() {
    Fixture fixture;
    const double half_angle = 0.25 * std::acos(-1.0);
    const banjo::Quat rotation{
        std::cos(half_angle),
        0.0,
        0.0,
        std::sin(half_angle),
    };
    for (banjo::ActiveNodeState &node : fixture.active.nodes) {
        node.position_world_m = rotation.rotate(node.position_world_m);
        node.previous_position_world_m = node.position_world_m;
        node.velocity_m_s = {};
    }

    const banjo::MaterialStepStats stats =
        fixture.solver.step(fixture.active, 1.0 / 240.0, {});
    require(stats.total_broken_bonds == 0U,
            "Green-Lagrange strain should not interpret rigid rotation as damage");
    require(stats.maximum_shear_strain < 1.0e-6,
            "rigid rotation should have approximately zero shear strain");
}

void largeCompressionUsesCompressiveFailureMode() {
    Fixture fixture;
    for (banjo::ActiveNodeState &node : fixture.active.nodes) {
        node.position_world_m.x *= 0.45;
        node.previous_position_world_m = node.position_world_m;
        node.velocity_m_s = {};
    }

    const banjo::MaterialStepStats stats =
        fixture.solver.step(fixture.active, 1.0 / 240.0, {});
    require(stats.maximum_compressive_strain > 0.1,
            "compressed lattice should report a nontrivial principal compression");
    require(stats.compressive_failures > 0U,
            "compression beyond compiled strength should break bonds as compression");
}

void simpleShearIsDetectedByLocalDeformationGradient() {
    Fixture fixture;
    for (banjo::ActiveNodeState &node : fixture.active.nodes) {
        node.position_world_m.x += 0.40 * node.position_world_m.y;
        node.previous_position_world_m = node.position_world_m;
        node.velocity_m_s = {};
    }

    const banjo::MaterialStepStats stats =
        fixture.solver.step(fixture.active, 1.0 / 240.0, {});
    require(stats.maximum_shear_strain > 0.01,
            "simple shear should be visible in the local rotation-invariant strain tensor");
    require(stats.shear_failures > 0U || stats.tensile_failures > 0U,
            "large simple shear should drive a material failure mode");
}

} // namespace

int main() {
    const std::vector<std::pair<std::string_view, std::function<void()>>> tests{
        {"compiled strength strains", compiledStrengthsProduceDistinctFailureStrains},
        {"rigid rotation is strain free", rigidRotationDoesNotCreateMaterialStrain},
        {"compression failure mode", largeCompressionUsesCompressiveFailureMode},
        {"simple shear is detected", simpleShearIsDetectedByLocalDeformationGradient},
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
