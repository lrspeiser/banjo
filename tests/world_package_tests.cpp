#include "world/WorldPackage.hpp"

#include <nlohmann/json.hpp>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdlib>
#include <functional>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace {
using Json = nlohmann::json;
using namespace banjo;

void require(bool condition, std::string_view message) {
    if (!condition) throw std::runtime_error(std::string(message));
}

void near(double actual, double expected, double tolerance, std::string_view message) {
    if (!std::isfinite(actual) || std::abs(actual - expected) > tolerance) {
        throw std::runtime_error(
            std::string(message) + ": actual=" + std::to_string(actual) +
            " expected=" + std::to_string(expected));
    }
}

Json cell(std::array<int, 3> chunk, std::array<unsigned, 3> local = {0, 0, 0}) {
    return {{"chunk", chunk}, {"local", local}};
}

Json passiveMaterial(
    unsigned id,
    std::string name,
    double density,
    double heat_capacity,
    double conductivity) {
    return {
        {"id", id},
        {"name", std::move(name)},
        {"density_kg_m3", density},
        {"heat_capacity_j_kg_k", heat_capacity},
        {"conductivity_w_m_k", conductivity},
    };
}

Json waterMaterial(unsigned id = 4) {
    Json water = passiveMaterial(id, "water/ice constant-volume demonstrator",
                                 1000.0, 2100.0, 2.2);
    water["phase_change"] = {
        {"liquid_heat_capacity_j_kg_k", 4180.0},
        {"melting_temperature_k", 273.15},
        {"latent_heat_j_kg", 334000.0},
    };
    return water;
}

Json comparativePackage() {
    Json oak = passiveMaterial(2, "oak-like reaction demonstrator", 700.0, 1700.0, 0.12);
    oak["fuel_fraction"] = 0.1;
    oak["oxygen_per_kg_solid"] = 0.15;
    oak["reaction"] = {
        {"activation_temperature_k", 600.0},
        {"rate_per_s", 2.0},
        {"heat_of_combustion_j_kg", 16.0e6},
        {"oxygen_per_kg_fuel", 1.5},
    };
    return {
        {"physics_abi", "banjo-thermal-world-1"},
        {"units", "SI"},
        {"voxel_size_m", 0.1},
        {"materials",
         Json::array({
             passiveMaterial(1, "glass", 2500.0, 840.0, 1.0),
             oak,
             passiveMaterial(3, "iron", 7870.0, 450.0, 80.0),
             waterMaterial(),
         })},
        {"chunks",
         Json::array({
             {{"position", {0, 0, 0}}, {"material", 1}, {"temperature_k", 293.15}},
             {{"position", {2, 0, 0}}, {"material", 2}, {"temperature_k", 650.0}},
             {{"position", {4, 0, 0}}, {"material", 3}, {"temperature_k", 293.15}},
             {{"position", {6, 0, 0}},
              {"material", 4},
              {"temperature_k", 273.15},
              {"liquid_fraction_at_melt", 0.25}},
         })},
        {"regions",
         Json::array({
             {{"id", 1}, {"step_s", 0.05}, {"cells", Json::array({cell({0, 0, 0})})}},
             {{"id", 2}, {"step_s", 0.05}, {"cells", Json::array({cell({2, 0, 0})})}},
             {{"id", 3}, {"step_s", 0.05}, {"cells", Json::array({cell({4, 0, 0})})}},
             {{"id", 4}, {"step_s", 0.05}, {"cells", Json::array({cell({6, 0, 0})})}},
         })},
    };
}

template <class Mutation>
void requireRejected(Mutation mutation, std::string_view message) {
    Json package = comparativePackage();
    mutation(package);
    bool rejected = false;
    try {
        (void)loadWorldPackage(package.dump());
    } catch (const std::exception &) {
        rejected = true;
    }
    require(rejected, message);
}

const ThermalCellView &findCell(
    const std::vector<ThermalCellView> &cells, unsigned region, unsigned material) {
    const auto found = std::find_if(cells.begin(), cells.end(), [&](const auto &view) {
        return view.region == region && view.material == material;
    });
    if (found == cells.end()) throw std::runtime_error("expected package cell is missing");
    return *found;
}

void validComparativePackagePreservesIdentityAndPhase() {
    auto world = loadWorldPackage(comparativePackage().dump());
    require(world->representedVoxelCount() == 4U * 4096U,
            "four declared chunks should remain compact uniform storage");
    require(world->activeCellCount() == 4, "four declared regions should activate four cells");
    const auto cells = world->activeCells();
    require(findCell(cells, 1, 1).material == 1 && findCell(cells, 2, 2).material == 2 &&
                findCell(cells, 3, 3).material == 3,
            "glass, oak, and iron IDs survive package loading");
    const auto &water = findCell(cells, 4, 4);
    near(water.temperature_k, 273.15, 1e-12, "water melting temperature");
    near(water.liquid_fraction, 0.25, 1e-12, "water phase identity");
}

void closedSchemaRejectsUnknownFieldsAtEveryLevel() {
    const std::vector<std::function<void(Json &)>> mutations{
        [](Json &j) { j["script"] = "run me"; },
        [](Json &j) { j["materials"][0]["color"] = "blue"; },
        [](Json &j) { j["materials"][1]["reaction"]["flame_speed"] = 1.0; },
        [](Json &j) { j["materials"][3]["phase_change"]["boiling_temperature_k"] = 373.15; },
        [](Json &j) { j["chunks"][0]["size"] = 16; },
        [](Json &j) { j["regions"][0]["boundary"] = "open"; },
        [](Json &j) { j["regions"][0]["cells"][0]["material"] = 1; },
        [](Json &j) {
            j["heaters"] = Json::array({
                {{"cell", cell({0, 0, 0})},
                 {"energy_j", 1.0},
                 {"maximum_energy_j", 1.0},
                 {"power_w", 1.0}},
            });
        },
    };
    for (const auto &mutation : mutations) {
        requireRejected(mutation, "unknown nested package field must be rejected");
    }
}

void incompatibleTypesBoundsAndReferencesAreRejected() {
    requireRejected([](Json &j) { j["physics_abi"] = "banjo-thermal-world-2"; },
                    "unknown ABI rejected");
    requireRejected([](Json &j) { j["units"] = "imperial"; }, "unknown units rejected");
    requireRejected([](Json &j) { j["voxel_size_m"] = nullptr; },
                    "non-finite/non-numeric scalar rejected");
    requireRejected([](Json &j) { j["materials"][0]["id"] = 1.5; },
                    "floating-point material ID rejected");
    requireRejected([](Json &j) { j["materials"][0]["density_kg_m3"] = 30001.0; },
                    "out-of-range density rejected");
    requireRejected([](Json &j) { j["chunks"][0]["temperature_k"] = 10001.0; },
                    "out-of-range temperature rejected");
    requireRejected([](Json &j) { j["regions"][0]["cells"][0]["local"][0] = 16; },
                    "out-of-range local coordinate rejected");
    requireRejected([](Json &j) { j["chunks"][0]["material"] = 99; },
                    "unknown chunk material rejected");
}

void combinedReactionAndPhaseLawIsRejected() {
    requireRejected(
        [](Json &j) {
            j["materials"][3]["fuel_fraction"] = 0.1;
            j["materials"][3]["oxygen_per_kg_solid"] = 0.1;
            j["materials"][3]["reaction"] = {
                {"activation_temperature_k", 300.0},
                {"rate_per_s", 1.0},
                {"heat_of_combustion_j_kg", 1.0e6},
                {"oxygen_per_kg_fuel", 1.0},
            };
        },
        "unimplemented phase plus reaction coupling rejected");
}

void packageHeaterChangesPhaseEnthalpyWithoutChangingMass() {
    Json package{
        {"physics_abi", "banjo-thermal-world-1"},
        {"units", "SI"},
        {"voxel_size_m", 0.1},
        {"materials", Json::array({waterMaterial()})},
        {"chunks", Json::array({
             {{"position", {0, 0, 0}}, {"material", 4}, {"temperature_k", 263.15}},
         })},
        {"regions", Json::array({
             {{"id", 1}, {"step_s", 0.05}, {"cells", Json::array({cell({0, 0, 0})})}},
         })},
        {"heaters", Json::array({
             {{"cell", cell({0, 0, 0})},
              {"energy_j", 188000.0},
              {"maximum_energy_j", 188000.0}},
         })},
    };
    auto world = loadWorldPackage(package.dump());
    const auto cells = world->activeCells();
    require(cells.size() == 1 && cells.front().material == 4,
            "heater preserves water material identity");
    near(cells.front().temperature_k, 273.15, 1e-12,
         "heater first warms ice to its melting temperature");
    near(cells.front().liquid_fraction, 0.5, 1e-12,
         "bounded heater supplies half the latent heat after sensible warming");
    const auto report = Json::parse(world->reportJson());
    near(report["active_mass_kg"].get<double>(), 1.0, 1e-15,
         "phase heater preserves one-voxel mass");
    near(report["external_work_j"].get<double>(), 188000.0, 1e-9,
         "package heater work is explicit");
    near(report["combined_active_energy_residual_j"].get<double>(), 0.0, 1e-9,
         "phase enthalpy change reconciles with heater work");
}

Json crossChunkPhasePackage(double step_s) {
    return {
        {"physics_abi", "banjo-thermal-world-1"},
        {"units", "SI"},
        {"voxel_size_m", 0.1},
        {"materials", Json::array({
             passiveMaterial(3, "iron", 7870.0, 450.0, 80.0),
             waterMaterial(),
         })},
        {"chunks", Json::array({
             {{"position", {0, 0, 0}}, {"material", 3}, {"temperature_k", 1000.0}},
             {{"position", {1, 0, 0}}, {"material", 4}, {"temperature_k", 273.15},
              {"liquid_fraction_at_melt", 0.1}},
             {{"position", {3, 0, 0}}, {"material", 3}, {"temperature_k", 100.0}},
             {{"position", {4, 0, 0}}, {"material", 4}, {"temperature_k", 273.15},
              {"liquid_fraction_at_melt", 0.9}},
         })},
        {"regions", Json::array({
             {{"id", 1}, {"step_s", step_s}, {"cells", Json::array({
                  cell({0, 0, 0}, {15, 0, 0}), cell({1, 0, 0}, {0, 0, 0}),
              })}},
             {{"id", 2}, {"step_s", step_s}, {"cells", Json::array({
                  cell({3, 0, 0}, {15, 0, 0}), cell({4, 0, 0}, {0, 0, 0}),
              })}},
         })},
    };
}

void crossChunkIronWaterExchangeMeltsFreezesAndConservesEnthalpy() {
    auto world = loadWorldPackage(crossChunkPhasePackage(0.05).dump());
    const auto before_cells = world->activeCells();
    const double melt_before = findCell(before_cells, 1, 4).liquid_fraction;
    const double freeze_before = findCell(before_cells, 2, 4).liquid_fraction;
    const auto before_report = Json::parse(world->reportJson());
    double enthalpy_before = 0.0;
    for (const auto &region : before_report["regions"]) {
        enthalpy_before += region["thermal_enthalpy_j"].get<double>();
    }
    for (int i = 0; i < 4; ++i) {
        const auto receipt = world->advance(
            0.25, {.maximum_jobs = 4096,
                   .maximum_cell_operations = 10'000'000,
                   .maximum_wall_ms = 1000.0});
        require(receipt.error.empty(), "cross-chunk phase exchange must pass energy audit");
    }
    const auto after_cells = world->activeCells();
    const auto &melted_water = findCell(after_cells, 1, 4);
    const auto &frozen_water = findCell(after_cells, 2, 4);
    require(melted_water.liquid_fraction > melt_before,
            "hot iron transfers enthalpy across chunk boundary and melts ice");
    require(frozen_water.liquid_fraction < freeze_before,
            "cold iron receives enthalpy across chunk boundary and freezes water");
    require(melted_water.material == 4 && frozen_water.material == 4,
            "phase evolution keeps the declared water material ID");

    const auto after_report = Json::parse(world->reportJson());
    double enthalpy_after = 0.0;
    for (const auto &region : after_report["regions"]) {
        enthalpy_after += region["thermal_enthalpy_j"].get<double>();
        near(region["combined_energy_residual_j"].get<double>(), 0.0, 1e-6,
             "insulated region thermal enthalpy audit");
        require(region["edges"] == 1, "each cross-chunk region has one face edge");
    }
    near(enthalpy_after, enthalpy_before, 1e-6,
         "opposite melt/freeze regions conserve total thermal enthalpy");
}

} // namespace

int main() {
    const std::vector<std::pair<std::string_view, std::function<void()>>> tests{
        {"valid comparative identity and phase", validComparativePackagePreservesIdentityAndPhase},
        {"closed schema unknown-field rejection", closedSchemaRejectsUnknownFieldsAtEveryLevel},
        {"type bound and reference rejection", incompatibleTypesBoundsAndReferencesAreRejected},
        {"phase reaction coupling rejection", combinedReactionAndPhaseLawIsRejected},
        {"package heater phase enthalpy", packageHeaterChangesPhaseEnthalpyWithoutChangingMass},
        {"cross-chunk melt freeze conservation", crossChunkIronWaterExchangeMeltsFreezesAndConservesEnthalpy},
    };
    unsigned failures = 0;
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
