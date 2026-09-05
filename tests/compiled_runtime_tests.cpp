#include "platform/PlatformWorld.hpp"

#include <nlohmann/json.hpp>

#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <functional>
#include <iostream>
#include <iterator>
#include <stdexcept>
#include <string>
#include <string_view>

namespace {

using banjo::PlatformWorld;
using nlohmann::json;

struct TestFailure : std::runtime_error { using std::runtime_error::runtime_error; };

void require(bool condition, std::string_view message) {
    if (!condition) throw TestFailure(std::string(message));
}

json fixture(std::string_view name) {
    const auto path = std::filesystem::path(BANJO_SOURCE_DIR) / "assets" / "runtime-v1" / name;
    std::ifstream input(path);
    require(input.good(), "runtime fixture must be readable");
    return json::parse(input);
}

std::unique_ptr<PlatformWorld> load(const json &package) {
    return PlatformWorld::load(package.dump());
}

void runSteps(PlatformWorld &world, unsigned total) {
    for (unsigned done = 0; done < total; done += 240) {
        const auto result = world.step(std::min(240U, total - done));
        require(result.completed_steps == std::min(240U, total - done),
                "runtime fixture must complete every requested step");
        require(result.error.empty(), "runtime fixture must not fault");
    }
}

const json &materialResult(const json &report, unsigned objectId) {
    for (const auto &result : report.at("material_results"))
        if (result.at("object_id") == objectId) return result;
    throw TestFailure("material result object is missing");
}

void requireTransferBounds(const json &report) {
    require(std::abs(report.at("maximum_transfer_energy_error_j").get<double>()) < 1.0e-5,
            "transfer energy error must remain bounded");
    require(std::abs(report.at("maximum_transfer_momentum_error_kg_m_s").get<double>()) < 1.0e-5,
            "transfer momentum error must remain bounded");
    require(std::abs(report.at("maximum_transfer_mass_error_kg").get<double>()) < 1.0e-6,
            "transfer mass error must remain bounded");
}

void freeFlightHasNoLocalWork() {
    auto source = fixture("07-free-flight.json");
    for(auto &object : source["objects"]) object["spin_rad_s"] = {1, 2, 3};
    auto world = load(source);
    auto startReport = json::parse(world->reportJson());
    for(auto &object : startReport["objects"])
        require(object["spin_rad_s"] == json({1, 2, 3}), "intact report must retain physical spin");
    const auto initial = world->renderInstances();
    runSteps(*world, 1440);
    const auto final = world->renderInstances();
    const auto report = json::parse(world->reportJson());
    require(world->fractureCount() == 0 && report.at("local_solves") == 0,
            "free flight must not activate local response or fracture");
    require(report.at("fault").get<std::string>().empty(), "free flight must remain fault free");
    require(initial.size() == final.size(), "free flight must preserve all objects");
    const double elapsed = 1440.0 * world->fixedStep();
    for (std::size_t i = 0; i < initial.size(); ++i) {
        const auto expected = initial[i].state.center_of_mass_world_m +
            elapsed * initial[i].state.linear_velocity_m_s;
        // Jolt retains float velocity/dt with double positions. A 1 um bound
        // covers their accumulated rounding over this 3 s trajectory.
        require(banjo::length(final[i].state.center_of_mass_world_m - expected) < 1.0e-6,
                "free-flight position must follow uniform motion");
        require(banjo::length(final[i].state.linear_velocity_m_s - initial[i].state.linear_velocity_m_s) < 1.0e-12,
                "free-flight velocity must remain uniform");
    }
}

void dropsExerciseMaterialBoundaries() {
    for (const auto name : {"01-iron-drop-0.15m.json", "03-iron-drop-1.5m.json", "05-cube-drop-1.5m.json"}) {
        auto world = load(fixture(name));
        runSteps(*world, 1440);
        const auto report = json::parse(world->reportJson());
        require(report.at("fault").get<std::string>().empty(), "drop fixture must remain fault free");
        const auto &oak = materialResult(report, 3);
        const auto &iron = materialResult(report, 2);
        require(oak.at("broken_links") == 0 && oak.at("components") == 1,
                "oak must remain rigid-only and connected");
        require(iron.at("broken_links") == 0 && iron.at("components") == 1,
                "iron must remain rigid-only and connected");
        if (std::string_view(name) == "01-iron-drop-0.15m.json") {
            const auto &glass = materialResult(report, 1);
            require(glass.at("components") == 1 && glass.at("broken_links") < glass.at("compiled_links"),
                    "low impact must retain a connected body despite possible cracks");
        }
        if (std::string_view(name) != "01-iron-drop-0.15m.json") {
            const auto &glass = materialResult(report, 1);
            require(glass.at("components") > 1 && glass.at("broken_links") > 0 &&
                        glass.at("broken_links") < glass.at("compiled_links"),
                    "high glass impact must fracture progressively with surviving links");
            requireTransferBounds(report);
            require(report["objects"][0]["spin_rad_s"].is_null(),
                    "separated object must not report a fabricated aggregate spin");
            require(report["fragment_states"].size() == report["connected_components"].get<std::size_t>(),
                    "each fragment must export its physical pose and velocity");
        }
    }
}

void bowlFractureIsContactAttributed() {
    auto world = load(fixture("06-bowl-three-materials.json"));
    runSteps(*world, 240);
    auto half = json::parse(world->reportJson());
    require(half.at("fracture_events").empty(), "bowl must have no fracture before the first observed event");
    runSteps(*world, 1200);
    const auto report = json::parse(world->reportJson());
    require(!report.at("fracture_events").empty(), "bowl must eventually fracture glass");
    require(report.at("fracture_events").front().at("contact_other_body") == 3,
            "first bowl fracture must be attributed to the iron body");
    requireTransferBounds(report);
}

void admissionRejectsUnsupportedPackages() {
    auto invalid = fixture("01-iron-drop-0.15m.json");
    invalid["fixed_dt_s"] = 1.0 / 239.0;
    bool rejected = false;
    try { (void)load(invalid); } catch (const std::exception &) { rejected = true; }
    require(rejected, "compiled backend must reject dt above 1/240");

    invalid = fixture("01-iron-drop-0.15m.json");
    invalid["required_capabilities"].push_back("plasticity");
    rejected = false;
    try { (void)load(invalid); } catch (const std::exception &) { rejected = true; }
    require(rejected, "unsupported capability must be rejected");

    invalid = fixture("01-iron-drop-0.15m.json");
    invalid["backend"] = "rigid-v1";
    invalid["required_capabilities"] = {"sphere", "contact"};
    rejected = false;
    try { (void)load(invalid); } catch (const std::exception &) { rejected = true; }
    require(rejected, "seeded objects must be rejected by a noncompiled backend");

    invalid = fixture("08-load-96-objects.json");
    const auto original = invalid.at("objects");
    for (unsigned i = 0; i < 33; ++i) {
        auto copy = original[i % original.size()];
        copy["id"] = 1000 + i;
        invalid["objects"].push_back(copy);
    }
    require(invalid.at("objects").size() > 128, "oversized admission fixture must exceed the object limit");
    rejected = false;
    try { (void)load(invalid); } catch (const std::exception &) { rejected = true; }
    require(rejected, "compiled backend must reject more than 128 objects");
}

} // namespace

int main() {
    const std::pair<std::string_view, std::function<void()>> tests[] = {
        {"free flight", freeFlightHasNoLocalWork},
        {"material drop boundaries", dropsExerciseMaterialBoundaries},
        {"bowl contact attribution", bowlFractureIsContactAttributed},
        {"package admission", admissionRejectsUnsupportedPackages},
    };
    std::size_t failures = 0;
    for (const auto &[name, test] : tests) {
        try { test(); std::cout << "[PASS] " << name << '\n'; }
        catch (const std::exception &error) { ++failures; std::cerr << "[FAIL] " << name << ": " << error.what() << '\n'; }
    }
    std::cout << (std::size(tests) - failures) << '/' << std::size(tests) << " tests passed\n";
    return failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
