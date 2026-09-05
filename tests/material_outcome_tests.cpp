#include "fracture/BrittleBondSolver.hpp"
#include "material/MaterialCatalog.hpp"
#include "material/MaterialCompiler.hpp"
#include "matter/Lattice.hpp"
#include "precompute/MaterialOutcome.hpp"

#include <cmath>
#include <cstdlib>
#include <filesystem>
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

void requireNear(double actual, double expected, double tolerance, std::string_view message) {
    if (std::abs(actual - expected) > tolerance) {
        throw TestFailure(std::string(message));
    }
}

banjo::MaterialOutcomeKey defaultKey() {
    return banjo::makeMaterialOutcomeKey({});
}

banjo::ActiveMatter makeActive(
    const banjo::LatticeAsset &lattice,
    const banjo::CompiledBrittleMaterial &compiled,
    const banjo::RigidSnapshot &rigid) {
    banjo::ImpactEvent impact;
    impact.body_a = 1;
    impact.body_b = 2;
    banjo::BrittleBondSolver solver({
        .substeps = 1,
        .constraint_iterations = 1,
        .use_support_plane = true,
        .support_plane = banjo::makeSupportPlane(
            {0.0, -10.0, 0.0},
            {0.0, 1.0, 0.0}),
        .impact_internal_energy_fraction = 0.0,
        .maximum_internal_energy_j = 0.0,
    });
    return solver.activate(2, lattice, compiled, rigid, impact);
}

void keyIncludesEveryOutcomeChangingField() {
    const banjo::MaterialOutcomeKey baseline = defaultKey();
    banjo::MaterialOutcomeKeyInput changed_input;
    changed_input.gravity_world_m_s2 = {0.0, 9.81, 0.0};
    const banjo::MaterialOutcomeKey changed_gravity =
        banjo::makeMaterialOutcomeKey(changed_input);
    require(!(baseline == changed_gravity),
            "outcome key must distinguish gravity direction");

    changed_input = {};
    changed_input.constraint_iterations = 12;
    const banjo::MaterialOutcomeKey changed_solver =
        banjo::makeMaterialOutcomeKey(changed_input);
    require(!(baseline == changed_solver),
            "outcome key must distinguish solver iteration count");
    require(
        banjo::materialOutcomeFingerprint(baseline) !=
            banjo::materialOutcomeFingerprint(changed_solver),
        "outcome fingerprint must change with solver configuration");
}

void capturedOutcomeCanBeAppliedInAnotherRigidFrame() {
    const banjo::MaterialDefinition glass =
        banjo::makeReferenceMaterial(banjo::MaterialPreset::Glass, 971);
    const banjo::CompiledBrittleMaterial compiled =
        banjo::compileBrittleMaterial(glass, 0.10, 2U);
    const banjo::LatticeAsset lattice =
        banjo::generateSphereLattice({0.25, 0.10, 2U, 2U}, compiled);

    const double half_source_angle = 0.15;
    const banjo::RigidSnapshot source_rigid{
        {2.0, 3.0, -1.0},
        {std::cos(half_source_angle), 0.0, std::sin(half_source_angle), 0.0},
        {1.2, -0.4, 0.6},
        {0.0, 0.5, 0.0},
    };
    banjo::ActiveMatter source = makeActive(lattice, compiled, source_rigid);
    for (std::size_t index = 0; index < source.nodes.size(); ++index) {
        const double phase = static_cast<double>(index % 11U) / 11.0;
        source.nodes[index].position_world_m += {
            0.006 * phase,
            -0.004 * phase,
            0.003 * phase,
        };
        source.nodes[index].velocity_m_s += {
            0.7 * phase,
            -0.2 * phase,
            0.4 * phase,
        };
    }
    for (std::size_t index = 0; index < source.bonds.size(); index += 9U) {
        source.bonds[index].alive = false;
        source.bonds[index].damage = 1.0;
        source.bonds[index].failure_mode = banjo::BondFailureMode::Shear;
    }

    const banjo::MaterialOutcome captured = banjo::captureMaterialOutcome(
        defaultKey(), source, source_rigid, 321U);

    const double half_target_angle = -0.31;
    const banjo::RigidSnapshot target_rigid{
        {-4.0, 1.5, 2.0},
        {std::cos(half_target_angle), 0.0, 0.0, std::sin(half_target_angle)},
        {-0.5, 1.1, -0.2},
        {0.3, 0.0, -0.4},
    };
    banjo::ActiveMatter target = makeActive(lattice, compiled, target_rigid);
    banjo::applyMaterialOutcome(captured, target_rigid, target);
    const banjo::MaterialOutcome recaptured = banjo::captureMaterialOutcome(
        defaultKey(), target, target_rigid, target.step_index);

    require(recaptured.nodes.size() == captured.nodes.size(),
            "replayed outcome must retain node topology");
    require(recaptured.bonds.size() == captured.bonds.size(),
            "replayed outcome must retain bond topology");
    require(recaptured.material_steps == captured.material_steps,
            "replayed outcome must retain material step count");
    requireNear(
        recaptured.represented_mass_kg,
        captured.represented_mass_kg,
        1.0e-10,
        "replayed outcome must preserve represented mass");

    for (std::size_t index = 0; index < captured.nodes.size(); ++index) {
        const banjo::CachedMaterialNode &a = captured.nodes[index];
        const banjo::CachedMaterialNode &b = recaptured.nodes[index];
        require(
            banjo::length(
                a.position_from_activation_com_local_m -
                b.position_from_activation_com_local_m) < 1.0e-10,
            "contact-frame node position must round trip through another rigid pose");
        require(
            banjo::length(
                a.velocity_minus_activation_linear_local_m_s -
                b.velocity_minus_activation_linear_local_m_s) < 1.0e-10,
            "contact-frame node velocity must round trip through another rigid pose");
    }
    for (std::size_t index = 0; index < captured.bonds.size(); ++index) {
        require(captured.bonds[index].alive == recaptured.bonds[index].alive,
                "replayed bond alive state must match");
        require(captured.bonds[index].failure_mode == recaptured.bonds[index].failure_mode,
                "replayed bond failure mode must match");
        requireNear(
            captured.bonds[index].damage,
            recaptured.bonds[index].damage,
            1.0e-12,
            "replayed bond damage must match");
    }
}

void outcomeFileRoundTripsDeterministically() {
    const banjo::MaterialDefinition glass =
        banjo::makeReferenceMaterial(banjo::MaterialPreset::Glass, 971);
    const banjo::CompiledBrittleMaterial compiled =
        banjo::compileBrittleMaterial(glass, 0.12, 1U);
    const banjo::LatticeAsset lattice =
        banjo::generateSphereLattice({0.25, 0.12, 1U, 2U}, compiled);
    const banjo::RigidSnapshot rigid{{1.0, 2.0, 3.0}, {}, {0.5, 0.0, 0.0}, {}};
    const banjo::ActiveMatter active = makeActive(lattice, compiled, rigid);
    const banjo::MaterialOutcome original = banjo::captureMaterialOutcome(
        defaultKey(), active, rigid, 17U);

    const std::filesystem::path path =
        std::filesystem::temp_directory_path() /
        "banjo-material-outcome-test.bmo";
    banjo::saveMaterialOutcome(original, path);
    const banjo::MaterialOutcome loaded = banjo::loadMaterialOutcome(path);
    std::filesystem::remove(path);

    require(loaded.key == original.key, "serialized outcome key must round trip");
    require(loaded.nodes.size() == original.nodes.size(),
            "serialized outcome nodes must round trip");
    require(loaded.bonds.size() == original.bonds.size(),
            "serialized outcome bonds must round trip");
    requireNear(
        loaded.nodes.front().position_from_activation_com_local_m.x,
        original.nodes.front().position_from_activation_com_local_m.x,
        1.0e-15,
        "serialized node state must retain double precision");
}

} // namespace

int main() {
    const std::vector<std::pair<std::string_view, std::function<void()>>> tests{
        {"outcome key covers physics", keyIncludesEveryOutcomeChangingField},
        {"outcome transforms between frames",
         capturedOutcomeCanBeAppliedInAnotherRigidFrame},
        {"outcome file round trip", outcomeFileRoundTripsDeterministically},
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
    std::cout << tests.size() - failures << '/' << tests.size()
              << " tests passed\n";
    return failures == 0U ? EXIT_SUCCESS : EXIT_FAILURE;
}
