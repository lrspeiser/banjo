#include "world/SparseThermalWorld.hpp"

#include <nlohmann/json.hpp>

#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <functional>
#include <iostream>
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
    if (!std::isfinite(actual) || std::abs(actual - expected) > tolerance) {
        throw std::runtime_error(
            std::string(message) + ": actual=" + std::to_string(actual) +
            " expected=" + std::to_string(expected));
    }
}

WorldThermalMaterial unitMaterial(unsigned id, std::string name = "unit material") {
    return {
        .id = id,
        .solid_density_kg_m3 = 1.0,
        .thermal = {
            .display_name = std::move(name),
            .specific_heat_capacity_j_kg_k = 1.0,
            .thermal_conductivity_w_m_k = 1.0,
        },
    };
}

WorldStepBudget generousBudget() {
    return {
        .maximum_jobs = 4096,
        .maximum_cell_operations = 10'000'000,
        .maximum_wall_ms = 1000.0,
    };
}

void advanceOneSecond(SparseThermalWorld &world) {
    for (int i = 0; i < 4; ++i) {
        const auto receipt = world.advance(0.25, generousBudget());
        require(receipt.error.empty(), "thermal advance must complete without an audit error");
    }
}

const ThermalCellView &cellAt(
    const std::vector<ThermalCellView> &cells, const VoxelAddress &address) {
    const auto found = std::find_if(cells.begin(), cells.end(), [&](const auto &cell) {
        return cell.address == address;
    });
    if (found == cells.end()) throw std::runtime_error("expected active cell is missing");
    return *found;
}

void coldStorageScalesWithoutScanning() {
    constexpr double voxel_size_m = 1.0 / 16.0;
    SparseThermalWorld one_meter(voxel_size_m);
    SparseThermalWorld sixteen_meter(voxel_size_m);
    one_meter.addMaterial(unitMaterial(1));
    sixteen_meter.addMaterial(unitMaterial(1));
    one_meter.addUniformChunk({0, 0, 0}, 1, 300.0);
    for (int z = 0; z < 16; ++z) {
        for (int y = 0; y < 16; ++y) {
            for (int x = 0; x < 16; ++x) {
                sixteen_meter.addUniformChunk({x, y, z}, 1, 300.0);
            }
        }
    }

    require(one_meter.representedVoxelCount() == 4096,
            "one-meter cube should use one compact 16-cube chunk");
    require(sixteen_meter.representedVoxelCount() == 16'777'216,
            "sixteen-meter cube should represent 16^3 chunks");
    require(one_meter.activeCellCount() == 0 && sixteen_meter.activeCellCount() == 0,
            "cold uniform chunks allocate no active cells");

    const auto small_receipt = one_meter.advance(0.1, generousBudget());
    const auto large_receipt = sixteen_meter.advance(0.1, generousBudget());
    require(small_receipt.completed_jobs == 0 && large_receipt.completed_jobs == 0,
            "worlds without active regions schedule no thermal jobs");
    const auto small_report = nlohmann::json::parse(one_meter.reportJson());
    const auto large_report = nlohmann::json::parse(sixteen_meter.reportJson());
    require(small_report["performance"]["cold_chunks_scanned_per_advance"] == 0 &&
                large_report["performance"]["cold_chunks_scanned_per_advance"] == 0,
            "advance must not scan cold chunks at either world size");
    require(large_report["state_payload_bytes"].get<std::uint64_t>() >
                small_report["state_payload_bytes"].get<std::uint64_t>(),
            "declared cold storage payload should scale with stored chunks");
}

void twoCellConductionMatchesExactPair() {
    SparseThermalWorld world(1.0);
    world.addMaterial(unitMaterial(1));
    world.addUniformChunk({0, 0, 0}, 1, 300.0);
    const VoxelAddress hot{{0, 0, 0}, 0, 0, 0};
    const VoxelAddress cold{{0, 0, 0}, 1, 0, 0};
    world.activateInsulatedRegion(1, {hot, cold}, 0.2);
    near(world.addHeat(hot, 300.0, 300.0, 0.0), 300.0, 0.0,
         "initial heater work");
    advanceOneSecond(world);

    const auto cells = world.activeCells();
    const double decay = std::exp(-2.0);
    near(cellAt(cells, hot).temperature_k, 450.0 + 150.0 * decay, 1e-10,
         "two-cell exact hot temperature");
    near(cellAt(cells, cold).temperature_k, 450.0 - 150.0 * decay, 1e-10,
         "two-cell exact cold temperature");
    near(cellAt(cells, hot).temperature_k + cellAt(cells, cold).temperature_k,
         900.0, 1e-10, "two-cell energy conservation");
}

std::vector<ThermalCellView> runThreeCellLine(double fixed_step_s) {
    SparseThermalWorld world(1.0);
    world.addMaterial(unitMaterial(1));
    world.addUniformChunk({0, 0, 0}, 1, 300.0);
    const std::vector<VoxelAddress> addresses{
        {{0, 0, 0}, 0, 0, 0},
        {{0, 0, 0}, 1, 0, 0},
        {{0, 0, 0}, 2, 0, 0},
    };
    world.activateInsulatedRegion(1, addresses, fixed_step_s);
    (void)world.addHeat(addresses.front(), 300.0, 300.0, 0.0);
    advanceOneSecond(world);
    return world.activeCells();
}

void threeCellGraphConvergesToAnalyticalSolution() {
    const auto coarse = runThreeCellLine(0.1);
    const auto fine = runThreeCellLine(0.01);
    const double e1 = std::exp(-1.0);
    const double e3 = std::exp(-3.0);
    const std::vector<double> exact{
        400.0 + 150.0 * e1 + 50.0 * e3,
        400.0 - 100.0 * e3,
        400.0 - 150.0 * e1 + 50.0 * e3,
    };
    auto maximumError = [&](const std::vector<ThermalCellView> &cells) {
        double error = 0.0;
        for (unsigned x = 0; x < 3; ++x) {
            const VoxelAddress address{{0, 0, 0}, x, 0, 0};
            error = std::max(error, std::abs(cellAt(cells, address).temperature_k - exact[x]));
        }
        return error;
    };
    const double coarse_error = maximumError(coarse);
    const double fine_error = maximumError(fine);
    require(fine_error < coarse_error * 0.02,
            "symmetric graph splitting should converge quadratically under refinement");
    require(fine_error < 0.01, "fine three-cell graph should approach analytical diffusion");
}

void zeroBudgetDefersAtomicallyThenCatchesUp() {
    SparseThermalWorld world(1.0);
    world.addMaterial(unitMaterial(1));
    world.addUniformChunk({0, 0, 0}, 1, 300.0);
    const VoxelAddress hot{{0, 0, 0}, 0, 0, 0};
    const VoxelAddress cold{{0, 0, 0}, 1, 0, 0};
    world.activateInsulatedRegion(1, {hot, cold}, 0.1);
    (void)world.addHeat(hot, 300.0, 300.0, 0.0);
    const auto before = world.activeCells();
    const auto deferred = world.advance(
        0.2,
        {.maximum_jobs = 0, .maximum_cell_operations = 0, .maximum_wall_ms = 1000.0});
    require(deferred.completed_jobs == 0 && deferred.count_budget_exhausted &&
                deferred.regions_late == 1,
            "zero count budget should report an explicitly late region");
    const auto unchanged = world.activeCells();
    near(cellAt(unchanged, hot).temperature_k, cellAt(before, hot).temperature_k, 0.0,
         "deferred hot cell remains atomic");
    near(cellAt(unchanged, cold).temperature_k, cellAt(before, cold).temperature_k, 0.0,
         "deferred cold cell remains atomic");
    near(cellAt(unchanged, hot).region_time_s, 0.0, 0.0,
         "deferred region keeps accepted time");

    const auto caught_up = world.advance(0.0, generousBudget());
    require(caught_up.completed_jobs == 2 && caught_up.regions_late == 0,
            "later budget should process both deferred fixed steps");
    const auto after = world.activeCells();
    require(cellAt(after, hot).temperature_k < cellAt(before, hot).temperature_k &&
                cellAt(after, cold).temperature_k > cellAt(before, cold).temperature_k,
            "catch-up applies the deferred conduction");
    near(cellAt(after, hot).region_time_s, 0.2, 1e-15,
         "accepted time catches requested time");
}

void invalidActivationDoesNotPublishPartialState() {
    SparseThermalWorld world(1.0);
    world.addMaterial(unitMaterial(1));
    world.addUniformChunk({0, 0, 0}, 1, 300.0);
    const VoxelAddress valid{{0, 0, 0}, 0, 0, 0};
    const VoxelAddress missing{{1, 0, 0}, 0, 0, 0};
    bool rejected = false;
    try {
        world.activateInsulatedRegion(1, {valid, missing});
    } catch (const std::invalid_argument &) {
        rejected = true;
    }
    require(rejected && world.activeCellCount() == 0,
            "invalid activation must not publish its valid prefix");
    world.activateInsulatedRegion(1, {valid});
    require(world.activeCellCount() == 1,
            "cell from rejected activation remains available for a valid transaction");
}

void crossChunkCellsConductInsideInsulatedRegion() {
    SparseThermalWorld world(1.0);
    world.addMaterial(unitMaterial(1));
    world.addUniformChunk({0, 0, 0}, 1, 600.0);
    world.addUniformChunk({1, 0, 0}, 1, 300.0);
    const VoxelAddress left{{0, 0, 0}, 15, 0, 0};
    const VoxelAddress right{{1, 0, 0}, 0, 0, 0};
    world.activateInsulatedRegion(7, {left, right}, 0.1);
    const auto receipt = world.advance(0.1, generousBudget());
    require(receipt.completed_jobs == 1, "cross-chunk pair should schedule one region job");
    const auto cells = world.activeCells();
    require(cellAt(cells, left).temperature_k < 600.0 &&
                cellAt(cells, right).temperature_k > 300.0,
            "face neighbors across a chunk boundary should exchange heat");
    const auto report = nlohmann::json::parse(world.reportJson());
    require(report["regions"][0]["edges"] == 1 &&
                report["regions"][0]["boundary"] == "explicitly insulated",
            "cross-chunk edge remains within one declared insulated region");
}

WorldThermalMaterial referenceMaterial(
    unsigned id,
    std::string name,
    double density,
    double heat_capacity,
    double conductivity) {
    return {
        .id = id,
        .solid_density_kg_m3 = density,
        .thermal = {
            .display_name = std::move(name),
            .specific_heat_capacity_j_kg_k = heat_capacity,
            .thermal_conductivity_w_m_k = conductivity,
        },
    };
}

WorldThermalMaterial reactiveWood(unsigned id, double oxygen_kg_per_kg_solid) {
    auto material = referenceMaterial(id, "wood-like demo", 700.0, 1700.0, 0.12);
    material.fuel_mass_fraction = 0.5;
    material.oxygen_kg_per_kg_solid = oxygen_kg_per_kg_solid;
    material.thermal.reaction = {
        .enabled = true,
        .activation_temperature_k = 600.0,
        .maximum_rate_per_s = 1.0,
        .heat_of_combustion_j_kg = 100'000.0,
        .oxygen_required_kg_per_kg_fuel = 1.0,
    };
    return material;
}

void reactionConservesAndIsPropertyDrivenAcrossMaterials() {
    SparseThermalWorld world(0.1);
    world.addMaterial(reactiveWood(1, 0.5));
    world.addMaterial(referenceMaterial(2, "glass", 2500.0, 840.0, 1.0));
    world.addMaterial(referenceMaterial(3, "iron", 7870.0, 450.0, 80.0));
    world.addMaterial(reactiveWood(4, 0.0));
    world.addUniformChunk({0, 0, 0}, 1, 700.0);
    world.addUniformChunk({2, 0, 0}, 2, 700.0);
    world.addUniformChunk({4, 0, 0}, 3, 700.0);
    world.addUniformChunk({6, 0, 0}, 4, 700.0);
    const VoxelAddress wood{{0, 0, 0}, 0, 0, 0};
    const VoxelAddress glass{{2, 0, 0}, 0, 0, 0};
    const VoxelAddress iron{{4, 0, 0}, 0, 0, 0};
    const VoxelAddress no_oxygen{{6, 0, 0}, 0, 0, 0};
    world.activateInsulatedRegion(9, {wood, glass, iron, no_oxygen}, 0.1);
    const auto before = world.activeCells();
    const auto receipt = world.advance(0.1, generousBudget());
    require(receipt.completed_jobs == 1 && receipt.error.empty(),
            "mixed-material reaction job should pass internal audits");
    const auto after = world.activeCells();
    require(cellAt(after, wood).fuel_kg < cellAt(before, wood).fuel_kg &&
                cellAt(after, wood).temperature_k > cellAt(before, wood).temperature_k,
            "hot oxygenated fuel consumes fuel and releases heat");
    near(cellAt(after, no_oxygen).fuel_kg, cellAt(before, no_oxygen).fuel_kg, 0.0,
         "same reactive material without local oxygen does not react");
    near(cellAt(after, no_oxygen).temperature_k, 700.0, 0.0,
         "no-oxygen control releases no heat");
    near(cellAt(after, glass).temperature_k, 700.0, 0.0,
         "reaction-disabled glass remains thermal-only");
    near(cellAt(after, iron).temperature_k, 700.0, 0.0,
         "reaction-disabled iron remains thermal-only");

    const auto report = nlohmann::json::parse(world.reportJson());
    const auto &region = report["regions"][0];
    require(region["reaction_heat_j"].get<double>() > 0.0 &&
                region["products_kg"].get<double>() > 0.0,
            "reaction receipt exposes heat and retained product mass");
    near(region["mass_residual_kg"].get<double>(), 0.0, 1e-12,
         "mixed reaction mass conservation");
    near(region["combined_energy_residual_j"].get<double>(), 0.0, 1e-7,
         "sensible plus remaining chemical energy conservation");
}

void staleHeatCommandIsRejectedAtomically() {
    SparseThermalWorld world(1.0);
    world.addMaterial(unitMaterial(1));
    world.addUniformChunk({0, 0, 0}, 1, 300.0);
    const VoxelAddress cell{{0, 0, 0}, 0, 0, 0};
    world.activateInsulatedRegion(1, {cell}, 0.1);
    (void)world.advance(0.1, generousBudget());
    const auto before = world.activeCells();
    bool rejected = false;
    try {
        (void)world.addHeat(cell, 100.0, 100.0, 0.0);
    } catch (const std::invalid_argument &) {
        rejected = true;
    }
    require(rejected, "heat command with stale accepted time must be rejected");
    const auto after = world.activeCells();
    near(cellAt(after, cell).temperature_k, cellAt(before, cell).temperature_k, 0.0,
         "stale heat rejection leaves cell energy unchanged");
    near(cellAt(after, cell).region_time_s, cellAt(before, cell).region_time_s, 0.0,
         "stale heat rejection leaves accepted time unchanged");
}

} // namespace

int main() {
    const std::vector<std::pair<std::string_view, std::function<void()>>> tests{
        {"cold storage scales without scans", coldStorageScalesWithoutScanning},
        {"two-cell exact conduction", twoCellConductionMatchesExactPair},
        {"three-cell graph convergence", threeCellGraphConvergesToAnalyticalSolution},
        {"zero-budget deferral and catch-up", zeroBudgetDefersAtomicallyThenCatchesUp},
        {"invalid activation atomicity", invalidActivationDoesNotPublishPartialState},
        {"cross-chunk insulated adjacency", crossChunkCellsConductInsideInsulatedRegion},
        {"property-driven reaction conservation", reactionConservesAndIsPropertyDrivenAcrossMaterials},
        {"stale heat rejection", staleHeatCommandIsRejectedAtomically},
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
