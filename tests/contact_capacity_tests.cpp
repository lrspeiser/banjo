#include "platform/PlatformWorld.hpp"
#include "rigid/JoltWorld.hpp"
#include "material/MaterialCatalog.hpp"

#include <nlohmann/json.hpp>

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <filesystem>
#include <fstream>
#include <functional>
#include <iostream>
#include <optional>
#include <stdexcept>
#include <string_view>
#include <type_traits>
#include <utility>
#include <vector>

namespace {
using banjo::JoltWorld;
using banjo::MaterialPreset;
using banjo::PlatformWorld;
using banjo::RigidBallDescription;
using banjo::RigidContactCapacity;
using banjo::RigidSnapshot;
using banjo::Vec3;
using json = nlohmann::json;

struct TestFailure : std::runtime_error { using std::runtime_error::runtime_error; };

void require(bool condition, std::string_view message) {
    if (!condition) throw TestFailure(std::string(message));
}

json readJson(const std::filesystem::path &path) {
    std::ifstream input(path);
    require(input.good(), "fixture must be readable");
    return json::parse(input);
}

json authoringPackage(std::optional<json> budget = std::nullopt) {
    const auto catalog = readJson(std::filesystem::path(BANJO_SOURCE_DIR) /
                                  "examples" / "authoring" / "presets.json");
    json source = {
        {"package_version", 2}, {"physics_abi", "banjo-network-2"},
        {"backend", "material-network-v2"}, {"units", "SI"},
        {"name", "contact capacity three material matter balls"},
        {"required_capabilities", {"cell-deformation", "cohesive-damage",
                                     "directional-lattice", "ellipsoid",
                                     "finite-ground", "gravity", "contact",
                                     "render-instances"}},
        {"fixed_dt_s", 1.0 / 480.0}, {"max_steps_per_call", 240},
        {"solver_iterations", 24}, {"temporal_policy", "diagnose"},
        {"gravity_m_s2", {0.0, -9.81, 0.0}},
        {"ground", {{"half_length_m", 2.0}, {"half_width_m", 2.0}, {"friction", 0.4}}},
        {"materials", json::array()}, {"objects", json::array()}
    };
    const std::vector<std::string> materials{"glass", "oak", "iron"};
    const std::vector<std::string> templates{
        "glass_matter_ball", "wood_matter_ball", "iron_matter_ball"};
    for (const auto &id : materials) {
        const auto found = std::find_if(
            catalog["materials"].begin(), catalog["materials"].end(),
            [&](const auto &material) { return material.at("id") == id; });
        require(found != catalog["materials"].end(), "authoring material is missing");
        source["materials"].push_back(*found);
    }
    const std::vector<double> x{-0.2, 0.0, 0.2};
    for (unsigned index = 0; index < templates.size(); ++index) {
        auto object = catalog["object_presets"].at(templates[index]);
        object["id"] = index + 1;
        object["name"] = materials[index] + " contact-capacity ball";
        object["position_m"] = {x[index], 0.04, 0.0};
        object["velocity_m_s"] = {0.0, 0.0, 0.0};
        object["spin_rad_s"] = {0.0, 0.0, 0.0};
        object["resolution"] = {7, 7, 7};
        source["objects"].push_back(std::move(object));
    }
    if (budget) source["contact_budget"] = *budget;
    return source;
}

std::unique_ptr<PlatformWorld> load(const json &source) {
    return PlatformWorld::load(source.dump());
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

json report(PlatformWorld &world) { return json::parse(world.reportJson()); }

const json &objectResult(const json &value, unsigned id) {
    for (const auto &object : value.at("objects"))
        if (object.at("id") == id) return object;
    throw TestFailure("report object is missing");
}

void step(PlatformWorld &world, unsigned count) {
    const auto result = world.step(count);
    require(result.completed_steps == count && result.error.empty(),
            "capacity-sized network step must complete without a fault");
}

void near(double actual, double expected, double tolerance, std::string_view message) {
    if (!std::isfinite(actual) || !std::isfinite(expected) || !std::isfinite(tolerance))
        throw TestFailure(std::string(message));
    if (std::abs(actual - expected) > tolerance * std::max(1.0, std::abs(expected)))
        throw TestFailure(std::string(message));
}

void nearVec(Vec3 actual, Vec3 expected, double tolerance, std::string_view message) {
    near(actual.x, expected.x, tolerance, message);
    near(actual.y, expected.y, tolerance, message);
    near(actual.z, expected.z, tolerance, message);
}

void capacitySizedMatterBallsStep() {
    auto world = load(authoringPackage());
    const auto initial = report(*world);
    require(initial.at("cells") == 537, "three 7^3 matter balls should occupy 537 cells");
    step(*world, 16);
    const auto after = report(*world);
    require(after.at("ticks") == 16 && after.at("fault").get<std::string>().empty(),
            "capacity-sized matter balls should survive the first contact steps");
    require(after.at("contact_budget").at("initial_pair_upper_bound").get<unsigned>() <=
                after.at("contact_budget").at("body_pairs").get<unsigned>(),
            "default body-pair capacity must contain the load-time bound");
}

void oldContactBudgetRejectsOverloadedMatterBalls() {
    const auto old = json{{"body_pairs", 16384}, {"constraints", 8192}};
    rejects(authoringPackage(old), "old contact budget must reject the matter-ball load");
}

void malformedContactBudgetsReject() {
    auto source = authoringPackage(json{{"body_pairs", 127}, {"constraints", 64}});
    rejects(source, "body-pair lower bound must reject");
    source["contact_budget"] = {{"body_pairs", 64}, {"constraints", 128}};
    rejects(source, "body-pairs below constraints must reject");
    source["contact_budget"] = {{"body_pairs", 262145}, {"constraints", 65536}};
    rejects(source, "body-pair upper bound must reject");
    source["contact_budget"] = {{"body_pairs", 65536}, {"constraints", 32768}, {"extra", 1}};
    rejects(source, "unknown contact-budget field must reject");
}

json panelFixture() {
    return readJson(std::filesystem::path(BANJO_SOURCE_DIR) / "assets" /
                    "material-showcase" / "01-clamped-panels-02mps.json");
}

void panelCapacityDoesNotChangeAcceptedState() {
    auto lowSource = panelFixture();
    lowSource["contact_budget"] = {{"body_pairs", 16384}, {"constraints", 8192}};
    auto highSource = panelFixture();
    highSource["contact_budget"] = {{"body_pairs", 262144}, {"constraints", 65536}};
    auto low = load(lowSource);
    auto high = load(highSource);
    step(*low, 72);
    step(*high, 72);
    const auto lowReport = report(*low);
    const auto highReport = report(*high);
    require(lowReport.at("contact_budget").at("initial_pair_upper_bound") <= 16384,
            "panel fixture must fit the explicit low capacity");
    require(highReport.at("contact_budget").at("initial_pair_upper_bound") ==
                lowReport.at("contact_budget").at("initial_pair_upper_bound"),
            "capacity must not change the load-time pair bound");
    for (const auto key : {"ticks", "cells", "links", "broken_links", "damaged_links",
                           "connected_components"})
        require(lowReport.at(key) == highReport.at(key),
                "capacity must preserve panel discrete outcomes");
    near(lowReport.at("mechanical_energy_j"), highReport.at("mechanical_energy_j"), 1e-8,
         "capacity must preserve panel mechanical energy");
    const auto lowObjects = low->renderInstances();
    const auto highObjects = high->renderInstances();
    require(lowObjects.size() == highObjects.size(), "capacity must preserve instance count");
    for (std::size_t i = 0; i < lowObjects.size(); ++i) {
        require(lowObjects[i].object_id == highObjects[i].object_id &&
                    lowObjects[i].element_id == highObjects[i].element_id,
                "capacity must preserve instance identity");
        nearVec(lowObjects[i].state.center_of_mass_world_m,
                highObjects[i].state.center_of_mass_world_m, 1e-8,
                "capacity must preserve instance position");
        nearVec(lowObjects[i].state.linear_velocity_m_s,
                highObjects[i].state.linear_velocity_m_s, 1e-8,
                "capacity must preserve instance velocity");
        const auto &lowObject = objectResult(lowReport, lowObjects[i].object_id);
        const auto &highObject = objectResult(highReport, highObjects[i].object_id);
        near(lowObject.at("mass_kg"), highObject.at("mass_kg"), 1e-12,
             "capacity must preserve object mass");
    }
}

using ContactDiagnostics = std::decay_t<decltype(std::declval<JoltWorld>().contactDiagnostics())>;

void requireSameDiagnostics(const ContactDiagnostics &actual,
                            const ContactDiagnostics &expected,
                            std::string_view message) {
    require(actual.capacity.body_pairs == expected.capacity.body_pairs &&
                actual.capacity.constraints == expected.capacity.constraints,
            message);
    near(actual.speculative_distance_m, expected.speculative_distance_m, 1e-12, message);
    require(actual.last_manifolds == expected.last_manifolds &&
                actual.peak_manifolds == expected.peak_manifolds &&
                actual.last_points == expected.last_points &&
                actual.peak_points == expected.peak_points &&
                actual.last_speculative_manifolds == expected.last_speculative_manifolds &&
                actual.peak_speculative_manifolds == expected.peak_speculative_manifolds,
            message);
}

void requireSameSnapshot(const RigidSnapshot &actual, const RigidSnapshot &expected,
                         std::string_view message) {
    nearVec(actual.center_of_mass_world_m, expected.center_of_mass_world_m, 1e-12, message);
    near(actual.orientation_world.w, expected.orientation_world.w, 1e-12, message);
    near(actual.orientation_world.x, expected.orientation_world.x, 1e-12, message);
    near(actual.orientation_world.y, expected.orientation_world.y, 1e-12, message);
    near(actual.orientation_world.z, expected.orientation_world.z, 1e-12, message);
    nearVec(actual.linear_velocity_m_s, expected.linear_velocity_m_s, 1e-12, message);
    nearVec(actual.angular_velocity_rad_s, expected.angular_velocity_rad_s, 1e-12, message);
}

struct BallRun {
    RigidSnapshot first{};
    RigidSnapshot second{};
    std::vector<banjo::ImpactEvent> impacts;
    ContactDiagnostics diagnostics;
    std::size_t pair_bound{};
};

BallRun directBallRun(bool observations) {
    JoltWorld world(0, RigidContactCapacity{16384, 8192});
    world.setGravity({0.0, 0.0, 0.0});
    world.setImpactObservationsEnabled(observations);
    const auto material = banjo::makeReferenceMaterial(MaterialPreset::Iron);
    world.addBall({1, 0.04, material, {-0.05, 0.0, 0.0}, {0.5, 0.0, 0.0}, {}, 0.0, 0.4});
    world.addBall({2, 0.04, material, {0.05, 0.0, 0.0}, {-0.5, 0.0, 0.0}, {}, 0.0, 0.4});
    const auto pairBound = world.contactPairUpperBound();
    for (unsigned i = 0; i < 16; ++i) world.step(1.0 / 480.0);
    return {world.snapshot(1), world.snapshot(2), world.drainImpacts(),
            world.contactDiagnostics(), pairBound};
}

void directImpactObservationTogglePreservesResponse() {
    const auto observed = directBallRun(true);
    const auto quiet = directBallRun(false);
    require(!observed.impacts.empty(), "enabled impact observations must report the ball contact");
    require(quiet.impacts.empty(), "disabled impact observations must omit optional events");
    require(observed.pair_bound > 0 && observed.pair_bound == quiet.pair_bound,
            "contact pair upper bound must be positive and observation-independent");
    nearVec(observed.first.center_of_mass_world_m, quiet.first.center_of_mass_world_m, 1e-8,
            "observation toggle must preserve first ball position");
    nearVec(observed.second.center_of_mass_world_m, quiet.second.center_of_mass_world_m, 1e-8,
            "observation toggle must preserve second ball position");
    nearVec(observed.first.linear_velocity_m_s, quiet.first.linear_velocity_m_s, 1e-8,
            "observation toggle must preserve first ball velocity");
    nearVec(observed.second.linear_velocity_m_s, quiet.second.linear_velocity_m_s, 1e-8,
            "observation toggle must preserve second ball velocity");
    require(observed.diagnostics.peak_manifolds > 0,
            "contact diagnostics must retain a manifold peak for the direct impact");
    require(observed.diagnostics.peak_points > 0,
            "contact diagnostics must retain a contact-point peak for the direct impact");
}

void rejectedTrialRestoresContactDiagnosticsAndReplayState() {
    JoltWorld world(0, RigidContactCapacity{16384, 8192});
    world.setGravity({0.0, 0.0, 0.0});
    const auto material = banjo::makeReferenceMaterial(MaterialPreset::Iron);
    world.addBall({1, 0.04, material, {-0.08, 0.0, 0.0}, {0.5, 0.0, 0.0}, {}, 0.0, 0.4});
    world.addBall({2, 0.04, material, {0.08, 0.0, 0.0}, {-0.5, 0.0, 0.0}, {}, 0.0, 0.4});
    for (unsigned i = 0; i < 8; ++i) world.step(1.0 / 480.0);

    const auto beforeFirst = world.snapshot(1);
    const auto beforeSecond = world.snapshot(2);
    const auto beforeDiagnostics = world.contactDiagnostics();
    RigidSnapshot rejectedFirst{}, rejectedSecond{};
    ContactDiagnostics rejectedDiagnostics{};
    require(!world.runReversibleTrial([&] {
                for (unsigned i = 0; i < 80; ++i) world.step(1.0 / 480.0);
                rejectedFirst = world.snapshot(1);
                rejectedSecond = world.snapshot(2);
                rejectedDiagnostics = world.contactDiagnostics();
                return false;
            }),
            "rejected contact trial must return false");
    require(rejectedDiagnostics.peak_manifolds > beforeDiagnostics.peak_manifolds &&
                rejectedDiagnostics.peak_points > beforeDiagnostics.peak_points,
            "rejected contact trial must exercise manifold diagnostics");
    requireSameSnapshot(world.snapshot(1), beforeFirst,
                        "rejected contact trial must restore first body state");
    requireSameSnapshot(world.snapshot(2), beforeSecond,
                        "rejected contact trial must restore second body state");
    requireSameDiagnostics(world.contactDiagnostics(), beforeDiagnostics,
                           "rejected contact trial must restore contact diagnostics");

    RigidSnapshot acceptedFirst{}, acceptedSecond{};
    ContactDiagnostics acceptedDiagnostics{};
    require(world.runReversibleTrial([&] {
                for (unsigned i = 0; i < 80; ++i) world.step(1.0 / 480.0);
                acceptedFirst = world.snapshot(1);
                acceptedSecond = world.snapshot(2);
                acceptedDiagnostics = world.contactDiagnostics();
                return true;
            }),
            "accepted replay contact trial must return true");
    requireSameSnapshot(acceptedFirst, rejectedFirst,
                        "restored contact trial must replay first body state");
    requireSameSnapshot(acceptedSecond, rejectedSecond,
                        "restored contact trial must replay second body state");
    requireSameDiagnostics(acceptedDiagnostics, rejectedDiagnostics,
                           "restored contact trial must replay diagnostics");
}

} // namespace

int main() {
    const std::vector<std::pair<std::string_view, std::function<void()>>> tests{
        {"capacity-sized matter balls step", capacitySizedMatterBallsStep},
        {"old contact budget rejects overloaded load", oldContactBudgetRejectsOverloadedMatterBalls},
        {"malformed contact budgets reject", malformedContactBudgetsReject},
        {"panel capacity preserves accepted state", panelCapacityDoesNotChangeAcceptedState},
        {"impact observation toggle preserves response", directImpactObservationTogglePreservesResponse},
        {"rejected trial restores contact diagnostics and replay state",
         rejectedTrialRestoresContactDiagnosticsAndReplayState},
    };
    std::size_t failures = 0;
    for (const auto &[name, test] : tests) {
        try { test(); std::cout << "[PASS] " << name << '\n'; }
        catch (const std::exception &error) {
            ++failures; std::cerr << "[FAIL] " << name << ": " << error.what() << '\n';
        }
    }
    std::cout << tests.size() - failures << '/' << tests.size() << " tests passed\n";
    return failures == 0 ? 0 : 1;
}
