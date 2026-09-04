#include "core/Plane.hpp"
#include "material/MaterialCatalog.hpp"
#include "material/MaterialCompiler.hpp"
#include "prediction/BallScenarioProjection.hpp"
#include "prediction/ScenarioCache.hpp"

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

void catalogMaterialsCompileToValidContactLaws() {
    for (const banjo::MaterialPreset preset : banjo::kMaterialPresets) {
        const banjo::MaterialDefinition material =
            banjo::makeReferenceMaterial(preset, 42);
        const banjo::CompiledContactMaterial contact =
            banjo::compileContactMaterial(material);
        require(material.density_kg_m3 > 0.0, "catalog material density must be positive");
        require(material.young_modulus_pa > 0.0, "catalog material modulus must be positive");
        require(contact.static_friction >= contact.dynamic_friction,
                "static friction must not be below dynamic friction");
        require(contact.restitution >= 0.0 && contact.restitution <= 1.0,
                "compiled restitution must be a bounded coefficient");
    }
}

void dampingControlsRestitution() {
    const double lightly_damped = banjo::coefficientOfRestitutionFromDamping(0.05);
    const double heavily_damped = banjo::coefficientOfRestitutionFromDamping(0.40);
    require(lightly_damped > heavily_damped,
            "more contact damping should produce a lower restitution coefficient");
    require(std::abs(banjo::coefficientOfRestitutionFromDamping(0.0) - 1.0) < 1.0e-12,
            "zero damping should produce an elastic restitution limit");
}

void supportPlaneFramePreservesSignedDistance() {
    const banjo::SupportPlaneFrame plane =
        banjo::makeSupportPlaneFromSlopeDegrees(17.5, {0.0, 0.25, 0.0});
    const banjo::Vec3 point = banjo::pointInPlaneFrame(plane, 2.0, -0.7, 0.33);
    require(std::abs(banjo::signedDistanceToPlane(plane, point) - 0.33) < 1.0e-10,
            "plane-frame normal offset should equal signed distance");
    require(std::abs(banjo::dot(plane.normal_world, plane.tangent_world)) < 1.0e-12,
            "plane tangent must be orthogonal to normal");
}

banjo::BallScenarioInput referenceScenario(
    banjo::MaterialPreset striker,
    banjo::MaterialPreset target,
    double speed_m_s = 8.0,
    double slope_degrees = 0.0) {
    banjo::BallScenarioInput input;
    input.striker_material = banjo::makeReferenceMaterial(striker, 971);
    input.target_material = banjo::makeReferenceMaterial(target, 971);
    input.surface_material =
        banjo::makeReferenceMaterial(banjo::MaterialPreset::Concrete, 971);
    input.striker_speed_m_s = speed_m_s;
    input.slope_angle_degrees = slope_degrees;
    input.estimated_active_nodes = 1285;
    input.estimated_bonds = 17097;
    return input;
}

void hertzProjectionRespondsToMaterialAndMass() {
    const banjo::ScenarioProjection iron = banjo::projectBallScenario(
        referenceScenario(banjo::MaterialPreset::Iron, banjo::MaterialPreset::Glass));
    const banjo::ScenarioProjection aluminum = banjo::projectBallScenario(
        referenceScenario(banjo::MaterialPreset::Aluminum, banjo::MaterialPreset::Glass));

    require(iron.impact.available_energy_j > aluminum.impact.available_energy_j,
            "equal-size denser striker should carry more reduced impact energy");
    require(iron.impact.peak_force_n > 0.0 &&
                iron.impact.peak_contact_pressure_pa > 0.0,
            "Hertz screening projection should produce contact force and pressure");
    require(iron.impact.target_post_speed_m_s > 0.0,
            "one-dimensional momentum projection should move the target forward");
}

void inclineProjectionDistinguishesRollingAndSliding() {
    banjo::BallScenarioInput rubber = referenceScenario(
        banjo::MaterialPreset::Rubber, banjo::MaterialPreset::Glass, 0.0, 20.0);
    const banjo::ScenarioProjection rubber_projection = banjo::projectBallScenario(rubber);
    require(rubber_projection.incline.regime ==
                banjo::InclineMotionRegime::RollingWithoutSlip,
            "high-friction rubber should roll without initial slip on the reference incline");

    banjo::BallScenarioInput ice = referenceScenario(
        banjo::MaterialPreset::Ice, banjo::MaterialPreset::Glass, 0.0, 20.0);
    ice.surface_material = banjo::makeReferenceMaterial(banjo::MaterialPreset::Ice, 971);
    const banjo::ScenarioProjection ice_projection = banjo::projectBallScenario(ice);
    require(ice_projection.incline.regime == banjo::InclineMotionRegime::Sliding,
            "low-friction ice-on-ice should initially slide on the reference incline");
}

void runtimePlannerEscalatesWhenMaterialCostExceedsBudget() {
    banjo::BallScenarioInput input = referenceScenario(
        banjo::MaterialPreset::Iron, banjo::MaterialPreset::Glass);
    input.realtime_constraint_budget = 1000;
    const banjo::ScenarioProjection uncached = banjo::projectBallScenario(input);
    require(uncached.runtime_strategy == banjo::RuntimeStrategy::PrecomputeRecommended,
            "large brittle solve should recommend precomputation under a tiny budget");

    input.cached_material_outcome_available = true;
    const banjo::ScenarioProjection cached = banjo::projectBallScenario(input);
    require(cached.runtime_strategy == banjo::RuntimeStrategy::CachedMaterial,
            "available matching material outcome should be selected before an oversized solve");
}

void scenarioCacheRoundTripsCsv() {
    const banjo::ScenarioKey key = banjo::makeScenarioKey(
        banjo::MaterialPreset::Iron,
        banjo::MaterialPreset::Glass,
        banjo::MaterialPreset::Concrete,
        0.25,
        8.0,
        0.0,
        9.81,
        0.04,
        971);
    const banjo::BallScenarioInput input = referenceScenario(
        banjo::MaterialPreset::Iron, banjo::MaterialPreset::Glass);

    banjo::ScenarioProjectionCache cache;
    const banjo::ProjectionLookup first = cache.lookupOrProject(key, input);
    const banjo::ProjectionLookup second = cache.lookupOrProject(key, input);
    require(!first.cache_hit && second.cache_hit,
            "second exact scenario lookup should use the deterministic cache");

    const std::filesystem::path path =
        std::filesystem::temp_directory_path() / "banjo-scenario-cache-test.csv";
    cache.saveCsv(path);
    banjo::ScenarioProjectionCache loaded;
    require(loaded.loadCsv(path) == 1U, "saved projection cache should reload one entry");
    require(loaded.lookup(key).has_value(), "reloaded cache should contain the exact key");
    std::filesystem::remove(path);
}

} // namespace

int main() {
    const std::vector<std::pair<std::string_view, std::function<void()>>> tests{
        {"catalog materials compile", catalogMaterialsCompileToValidContactLaws},
        {"damping controls restitution", dampingControlsRestitution},
        {"support plane frame", supportPlaneFramePreservesSignedDistance},
        {"Hertz projection responds", hertzProjectionRespondsToMaterialAndMass},
        {"incline rolling and sliding", inclineProjectionDistinguishesRollingAndSliding},
        {"runtime planner escalates", runtimePlannerEscalatesWhenMaterialCostExceedsBudget},
        {"scenario cache round trip", scenarioCacheRoundTripsCsv},
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
