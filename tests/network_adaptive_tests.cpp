#include "platform/PlatformWorld.hpp"

#include <nlohmann/json.hpp>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <functional>
#include <iostream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace {

using banjo::PlatformBondLine;
using banjo::PlatformInstance;
using banjo::PlatformSkin;
using banjo::PlatformWorld;
using banjo::RigidPrimitive;
using banjo::RigidSnapshot;
using banjo::Vec3;
using json = nlohmann::json;

struct TestFailure : std::runtime_error { using std::runtime_error::runtime_error; };

void require(bool condition, std::string_view message) {
    if (!condition) throw TestFailure(std::string(message));
}

void near(double actual, double expected, double tolerance, std::string_view message) {
    if (!std::isfinite(actual) || !std::isfinite(expected) || !std::isfinite(tolerance) ||
        std::abs(actual - expected) > tolerance * std::max(1.0, std::abs(expected)))
        throw TestFailure(std::string(message));
}

void nearVec(const Vec3 &actual, const Vec3 &expected, double tolerance,
             std::string_view message) {
    near(actual.x, expected.x, tolerance, message);
    near(actual.y, expected.y, tolerance, message);
    near(actual.z, expected.z, tolerance, message);
}

json fixture(std::string_view name) {
    const auto path = std::filesystem::path(BANJO_SOURCE_DIR) / "assets" /
                      "material-showcase" / name;
    std::ifstream input(path);
    require(input.good(), "adaptive network fixture must be readable");
    return json::parse(input);
}

std::unique_ptr<PlatformWorld> load(const json &source) {
    return PlatformWorld::load(source.dump());
}

json report(PlatformWorld &world) { return json::parse(world.reportJson()); }

double reportMass(const json &value) {
    double result = 0.0;
    for (const auto &object : value.at("objects")) result += object.at("mass_kg").get<double>();
    return result;
}

void rejects(const json &source, std::string_view message) {
    try {
        auto world = load(source);
        (void)world;
    } catch (const std::exception &) {
        return;
    }
    throw TestFailure(std::string(message));
}

json damagePolicy(unsigned depth = 2, double damage = 0.001,
                  double plastic = 0.002, double brittle = 0.01,
                  std::string_view onLimit = "report") {
    return json{{"maximum_depth", depth},
                {"maximum_damage_increment", damage},
                {"maximum_plastic_strain_increment", plastic},
                {"maximum_brittle_opening_overshoot", brittle},
                {"on_limit", std::string(onLimit)}};
}

void runSteps(PlatformWorld &world, unsigned count) {
    for (unsigned i = 0; i < count; ++i) {
        const auto result = world.step(1);
        require(result.completed_steps == 1 && result.error.empty(),
                "adaptive network step must complete without a fault");
    }
}

void requireSameSnapshot(const RigidSnapshot &actual, const RigidSnapshot &expected,
                         std::string_view message, double tolerance = 1.0e-10) {
    nearVec(actual.center_of_mass_world_m, expected.center_of_mass_world_m, tolerance, message);
    near(actual.orientation_world.w, expected.orientation_world.w, tolerance, message);
    near(actual.orientation_world.x, expected.orientation_world.x, tolerance, message);
    near(actual.orientation_world.y, expected.orientation_world.y, tolerance, message);
    near(actual.orientation_world.z, expected.orientation_world.z, tolerance, message);
    nearVec(actual.linear_velocity_m_s, expected.linear_velocity_m_s, tolerance, message);
    nearVec(actual.angular_velocity_rad_s, expected.angular_velocity_rad_s, tolerance, message);
}

void requireSamePrimitive(const RigidPrimitive &actual, const RigidPrimitive &expected,
                          std::string_view message) {
    require(actual.kind == expected.kind, message);
    near(actual.radius_m, expected.radius_m, 1.0e-12, message);
    nearVec(actual.dimensions_m, expected.dimensions_m, 1.0e-12, message);
}

void requireSameInstances(const std::vector<PlatformInstance> &actual,
                          const std::vector<PlatformInstance> &expected,
                          std::string_view message) {
    require(actual.size() == expected.size(), message);
    for (std::size_t i = 0; i < actual.size(); ++i) {
        const auto &a = actual[i];
        const auto &b = expected[i];
        require(a.object_id == b.object_id && a.element_id == b.element_id &&
                    a.component_id == b.component_id && a.material == b.material &&
                    a.color_rgba == b.color_rgba && a.material_id == b.material_id &&
                    a.deformable_cell == b.deformable_cell,
                message);
        requireSamePrimitive(a.geometry, b.geometry, message);
        requireSameSnapshot(a.state, b.state, message);
        require(a.local_mesh.size() == b.local_mesh.size(), message);
        for (std::size_t t = 0; t < a.local_mesh.size(); ++t)
            for (unsigned c = 0; c < 3; ++c)
                nearVec(a.local_mesh[t][c], b.local_mesh[t][c], 1.0e-12, message);
    }
}

void requireSameBonds(const std::vector<PlatformBondLine> &actual,
                      const std::vector<PlatformBondLine> &expected,
                      std::string_view message) {
    require(actual.size() == expected.size(), message);
    for (std::size_t i = 0; i < actual.size(); ++i) {
        const auto &a = actual[i];
        const auto &b = expected[i];
        nearVec(a.a, b.a, 1.0e-10, message);
        nearVec(a.b, b.b, 1.0e-10, message);
        require(a.live == b.live && a.object_id == b.object_id &&
                    a.a_element == b.a_element && a.b_element == b.b_element,
                message);
        near(a.damage, b.damage, 1.0e-10, message);
        near(a.plastic_extension_m, b.plastic_extension_m, 1.0e-10, message);
    }
}

void requireSameSkins(const std::vector<PlatformSkin> &actual,
                      const std::vector<PlatformSkin> &expected,
                      std::string_view message) {
    require(actual.size() == expected.size(), message);
    for (std::size_t i = 0; i < actual.size(); ++i) {
        const auto &a = actual[i];
        const auto &b = expected[i];
        require(a.object_id == b.object_id && a.material_id == b.material_id &&
                    a.color_rgba == b.color_rgba &&
                    a.mesh.revision == b.mesh.revision &&
                    a.mesh.exposed_faces == b.mesh.exposed_faces &&
                    a.mesh.fracture_faces == b.mesh.fracture_faces &&
                    a.mesh.triangles.size() == b.mesh.triangles.size(),
                message);
        for (std::size_t t = 0; t < a.mesh.triangles.size(); ++t) {
            const auto &at = a.mesh.triangles[t];
            const auto &bt = b.mesh.triangles[t];
            require(at.component == bt.component && at.source_cell == bt.source_cell &&
                        at.fracture_surface == bt.fracture_surface,
                    message);
            for (unsigned c = 0; c < 3; ++c)
                nearVec(at.positions_world_m[c], bt.positions_world_m[c], 1.0e-10, message);
        }
    }
}

json physicalReport(json value) {
    // These fields are diagnostics or error/performance metadata. The package
    // is declaration metadata, so remove it when comparing two policies.
    for (const char *key : {"damage_integration", "contact_budget", "skin", "performance",
                            "fault", "state_valid", "package"})
        value.erase(key);
    return value;
}

void requireSameJson(const json &actual, const json &expected, std::string_view message,
                     double tolerance = 1.0e-10) {
    if (actual.is_number() && expected.is_number()) {
        near(actual.get<double>(), expected.get<double>(), tolerance, message);
        return;
    }
    require(actual.type() == expected.type(), message);
    if (actual.is_object()) {
        require(actual.size() == expected.size(), message);
        for (auto it = actual.begin(); it != actual.end(); ++it) {
            require(expected.contains(it.key()), message);
            requireSameJson(it.value(), expected.at(it.key()), message, tolerance);
        }
    } else if (actual.is_array()) {
        require(actual.size() == expected.size(), message);
        for (std::size_t i = 0; i < actual.size(); ++i)
            requireSameJson(actual[i], expected[i], message, tolerance);
    } else {
        require(actual == expected, message);
    }
}

void policyValidationRejectsMalformedBounds() {
    const auto base = fixture("03-clamped-panels-12mps.json");

    auto bad = base;
    bad["damage_integration"] = damagePolicy();
    bad["damage_integration"]["unknown"] = 1;
    rejects(bad, "unknown damage-integration fields must reject");

    bad = base;
    bad["damage_integration"] = nullptr;
    rejects(bad, "null damage-integration policy must reject");
    bad = base;
    bad["damage_integration"] = {{"maximum_depth", "2"}};
    rejects(bad, "malformed maximum depth must reject");

    for (const auto value : {-1, 9}) {
        bad = base;
        bad["damage_integration"] = {{"maximum_depth", value}};
        rejects(bad, "maximum depth bounds must reject");
    }
    for (const auto value : {1.0e-7, 1.000001}) {
        bad = base;
        bad["damage_integration"] = {{"maximum_damage_increment", value}};
        rejects(bad, "damage-increment bounds must reject");
    }
    for (const auto value : {1.0e-9, 1.000001}) {
        bad = base;
        bad["damage_integration"] = {{"maximum_plastic_strain_increment", value}};
        rejects(bad, "plastic-increment bounds must reject");
    }
    for (const auto value : {1.0e-9, 1.000001}) {
        bad = base;
        bad["damage_integration"] = {{"maximum_brittle_opening_overshoot", value}};
        rejects(bad, "brittle-overshoot bounds must reject");
    }
    bad = base;
    bad["damage_integration"] = {{"on_limit", "stop"}};
    rejects(bad, "unknown damage-integration limit policy must reject");
    bad = base;
    bad["damage_integration"] = {{"on_limit", 1}};
    rejects(bad, "malformed damage-integration limit policy must reject");

    auto valid = base;
    valid["damage_integration"] = damagePolicy(8, 1.0, 0.1, 1.0);
    auto world = load(valid);
    const auto configured = report(*world).at("damage_integration");
    // Each stability substep of a tick may bisect to the configured depth, so
    // the per-tick trial bound is the depth bound times the substep count
    // rather than a constant. Asserted as that product, so the relationship is
    // checked rather than a number that silently tracks the substep clock.
    const auto substeps = configured.at("stability_substeps_per_tick").get<unsigned>();
    require(substeps >= 1, "adaptive policy must report its stability substep count");
    require(configured.at("mode") == "adaptive-damage-trials" &&
                configured.at("maximum_depth") == 8 &&
                configured.at("maximum_solver_trials_per_tick") == substeps * 511,
            "maximum adaptive policy bounds must be admitted and reported");
}

void defaultAndDepthZeroHaveTheSamePhysicalResult() {
    auto defaultPolicySource = fixture("03-clamped-panels-12mps.json");
    defaultPolicySource["damage_integration"] = json::object();
    auto defaultPolicyWorld = load(defaultPolicySource);
    require(report(*defaultPolicyWorld).at("damage_integration").at("on_limit") == "reject",
            "opt-in adaptive policy defaults to strict rejection");
    auto ordinary = load(fixture("03-clamped-panels-12mps.json"));
    auto adaptiveSource = fixture("03-clamped-panels-12mps.json");
    adaptiveSource["damage_integration"] = damagePolicy(0, 0.05, 0.002, 0.05);
    auto depthZero = load(adaptiveSource);
    runSteps(*ordinary, 72);
    runSteps(*depthZero, 72);
    requireSameJson(physicalReport(report(*depthZero)), physicalReport(report(*ordinary)),
                    "depth-zero adaptive trials must preserve panel physical report");
    requireSameInstances(depthZero->renderInstances(), ordinary->renderInstances(),
                         "depth-zero adaptive trials must preserve every panel cell state");
    requireSameBonds(depthZero->renderBonds(), ordinary->renderBonds(),
                     "depth-zero adaptive trials must preserve every panel bond");
    requireSameSkins(depthZero->renderSkins(), ordinary->renderSkins(),
                     "depth-zero adaptive trials must preserve rendered panel skins");
}

void adaptiveTrialsSplitTheTomatoWithoutChangingMassOrClock() {
    auto source = fixture("04-tomato-proxy-knife-cut.json");
    source["damage_integration"] = damagePolicy(2, 0.001, 0.002, 0.01);
    auto world = load(source);
    const auto initial = report(*world);
    runSteps(*world, 48);
    const auto result = report(*world);
    const auto &integration = result.at("damage_integration");
    const auto ticks = result.at("ticks").get<unsigned>();
    const auto maxTrials = integration.at("maximum_solver_trials_per_tick").get<std::uint64_t>();
    const double acceptedDamage = integration.at("accepted_maximum_damage_increment").get<double>();
    const double acceptedPlastic = integration.at("accepted_maximum_plastic_strain_increment").get<double>();
    const double acceptedBrittle = integration.at("accepted_maximum_brittle_opening_overshoot").get<double>();
    const double configuredDamage = integration.at("maximum_damage_increment").get<double>();
    const auto unresolved = integration.at("unresolved_substeps").get<std::uint64_t>();
    require(integration.at("mode") == "adaptive-damage-trials" &&
                integration.at("rejected_trials").get<std::uint64_t>() > 0 &&
                integration.at("accepted_substeps").get<std::uint64_t>() > ticks &&
                integration.at("deepest_trial").get<unsigned>() <= 2 &&
                integration.at("solver_trials").get<std::uint64_t>() <= maxTrials * ticks &&
                integration.at("configured_limits_are_targets_in_report_mode").get<bool>() &&
                integration.at("endpoint_acceptance_criteria").get<bool>() &&
                !integration.at("detects_intra_substep_peaks").get<bool>(),
            "adaptive tomato run must split within its per-tick trial bound");
    require(std::isfinite(acceptedDamage) && acceptedDamage >= 0.0 &&
                std::isfinite(acceptedPlastic) && acceptedPlastic >= 0.0 &&
                std::isfinite(acceptedBrittle) && acceptedBrittle >= 0.0,
            "adaptive report must expose finite nonnegative accepted maxima");
    if (unresolved == 0)
        require(acceptedDamage <= configuredDamage * (1.0 + 1.0e-12),
                "resolved report-mode damage must meet its configured target");
    near(result.at("elapsed_s").get<double>(), ticks * source.at("fixed_dt_s").get<double>(),
         1.0e-12, "adaptive tomato run must preserve authored elapsed time");
    near(reportMass(result), reportMass(initial), 1.0e-10,
         "adaptive tomato run must retain modeled mass");
    require(integration.at("smallest_accepted_step_s").get<double>() > 0.0 &&
                integration.at("smallest_accepted_step_s").get<double>() <=
                    source.at("fixed_dt_s").get<double>(),
            "adaptive tomato run must report a bounded accepted substep");
}

void rejectedAdaptiveTickRestoresPhysicalStateAndSkinQueriesAreReadOnly() {
    auto source = fixture("04-tomato-proxy-knife-cut.json");
    source["damage_integration"] = damagePolicy(3, 1.0e-6, 1.0e-8, 1.0e-8, "reject");
    auto world = load(source);
    bool rejected = false;
    for (unsigned i = 0; i < 144; ++i) {
        const auto beforeReport = report(*world);
        const auto beforeInstances = world->renderInstances();
        const auto beforeBonds = world->renderBonds();
        const auto beforeSkins = world->renderSkins();
        const auto result = world->step(1);
        if (result.error.empty()) {
            require(result.completed_steps == 1,
                    "accepted strict adaptive step must advance exactly one tick");
            continue;
        }

        rejected = true;
        require(result.completed_steps == 0 &&
                    result.error.find("damage integration limit exceeded") != std::string::npos,
                "strict adaptive limit must reject the complete outer tick");
        const auto afterReport = report(*world);
        const auto &beforeIntegration = beforeReport.at("damage_integration");
        const auto &integration = afterReport.at("damage_integration");
        require(integration.at("terminal_limit_rejections").get<std::uint64_t>() == 1 &&
                    integration.at("rolled_back_ticks").get<std::uint64_t>() > 0 &&
                    integration.at("discarded_substeps").get<std::uint64_t>() > 0 &&
                    integration.at("rejected_trials").get<std::uint64_t>() > 0,
                "strict rejection must report rollback after discarded accepted substeps");
        for (const char *key : {"accepted_maximum_damage_increment",
                                "accepted_maximum_plastic_strain_increment",
                                "accepted_maximum_brittle_opening_overshoot"})
            near(integration.at(key).get<double>(), beforeIntegration.at(key).get<double>(),
                 1.0e-12, "strict rejection must preserve accepted maxima");
        requireSameJson(physicalReport(afterReport), physicalReport(beforeReport),
                        "strict adaptive rejection must restore the complete physical report",
                        1.0e-12);
        requireSameInstances(world->renderInstances(), beforeInstances,
                             "strict adaptive rejection must restore every cell state");
        requireSameBonds(world->renderBonds(), beforeBonds,
                         "strict adaptive rejection must restore every bond state");
        requireSameSkins(world->renderSkins(), beforeSkins,
                         "strict adaptive rejection must restore skin revisions and cells");

        const auto reportBeforeSkinQuery = report(*world);
        const auto instancesBeforeSkinQuery = world->renderInstances();
        const auto bondsBeforeSkinQuery = world->renderBonds();
        (void)world->renderSkins();
        requireSameJson(physicalReport(report(*world)), physicalReport(reportBeforeSkinQuery),
                        "skin querying must not mutate physical report state", 1.0e-12);
        requireSameInstances(world->renderInstances(), instancesBeforeSkinQuery,
                             "skin querying must not mutate cell state");
        requireSameBonds(world->renderBonds(), bondsBeforeSkinQuery,
                         "skin querying must not mutate bond state");
        break;
    }
    require(rejected, "strict adaptive tomato fixture must reach a rejected limit");
}

} // namespace

int main() {
    const std::vector<std::pair<std::string_view, std::function<void()>>> tests{
        {"adaptive policy validation", policyValidationRejectsMalformedBounds},
        {"depth-zero physical equivalence", defaultAndDepthZeroHaveTheSamePhysicalResult},
        {"adaptive bounded tomato split", adaptiveTrialsSplitTheTomatoWithoutChangingMassOrClock},
        {"strict adaptive rollback and skin query", rejectedAdaptiveTickRestoresPhysicalStateAndSkinQueriesAreReadOnly},
    };
    std::size_t failures = 0;
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
    return failures == 0 ? 0 : 1;
}
