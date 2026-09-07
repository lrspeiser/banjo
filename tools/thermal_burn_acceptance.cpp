#include "world/SparseThermalWorld.hpp"

#include <algorithm>
#include <cmath>
#include <iostream>
#include <nlohmann/json.hpp>
#include <string>
#include <vector>

namespace {
using namespace banjo;
using Json = nlohmann::json;

WorldThermalMaterial inert(unsigned id, std::string name, double density, double heat_capacity,
                           double conductivity) {
    return {.id = id,
            .solid_density_kg_m3 = density,
            .thermal = {.display_name = std::move(name),
                        .specific_heat_capacity_j_kg_k = heat_capacity,
                        .thermal_conductivity_w_m_k = conductivity}};
}

WorldThermalMaterial oak(unsigned id) {
    auto result = inert(id, "oak", 700., 1700., .12);
    result.fuel_mass_fraction = .1;
    result.oxygen_kg_per_kg_solid = .001;
    result.thermal.reaction = {.enabled = true,
                               .activation_temperature_k = 600.,
                               .maximum_rate_per_s = 20.,
                               .heat_of_combustion_j_kg = 16.e6,
                               .oxygen_required_kg_per_kg_fuel = 1.};
    return result;
}

Json descriptor(const WorldThermalMaterial &material) {
    const auto &reaction = material.thermal.reaction;
    return {{"id", material.id},
            {"display_name", material.thermal.display_name},
            {"solid_density_kg_m3", material.solid_density_kg_m3},
            {"specific_heat_capacity_j_kg_k", material.thermal.specific_heat_capacity_j_kg_k},
            {"thermal_conductivity_w_m_k", material.thermal.thermal_conductivity_w_m_k},
            {"fuel_mass_fraction", material.fuel_mass_fraction},
            {"oxygen_kg_per_kg_solid", material.oxygen_kg_per_kg_solid},
            {"reaction",
             {{"enabled", reaction.enabled},
              {"activation_temperature_k", reaction.activation_temperature_k},
              {"maximum_rate_per_s", reaction.maximum_rate_per_s},
              {"heat_of_combustion_j_kg", reaction.heat_of_combustion_j_kg},
              {"oxygen_required_kg_per_kg_fuel", reaction.oxygen_required_kg_per_kg_fuel}}},
            {"provenance", "explicit thermal burn acceptance demonstration parameters; not a "
                           "calibrated catalog material"}};
}

const ThermalCellView &cell(const std::vector<ThermalCellView> &cells,
                            const VoxelAddress &address) {
    const auto found = std::find_if(cells.begin(), cells.end(),
                                    [&](const auto &entry) { return entry.address == address; });
    if (found == cells.end())
        throw std::runtime_error("acceptance cell missing");
    return *found;
}

Json snapshot(const SparseThermalWorld &world, const VoxelAddress &heated,
              const VoxelAddress &neighbor, const VoxelAddress &nonneighbor,
              const VoxelAddress &control) {
    const auto cells = world.activeCells();
    auto item = [&](const VoxelAddress &address) {
        const auto &value = cell(cells, address);
        return Json{{"temperature_k", value.temperature_k},
                    {"fuel_kg", value.fuel_kg},
                    {"oxygen_kg", value.oxygen_kg}};
    };
    return {{"heated", item(heated)},
            {"neighbor", item(neighbor)},
            {"nonneighbor", item(nonneighbor)},
            {"unheated_control", item(control)}};
}

Json run(WorldThermalMaterial material, double fixed_step_s, WorldStepBudget budget) {
    constexpr double voxel_size = .02, heater_work = 3000.;
    SparseThermalWorld world(voxel_size);
    const unsigned material_id = material.id;
    const std::string name = material.thermal.display_name;
    const bool reactive = material.thermal.reaction.enabled;
    const Json material_descriptor = descriptor(material);
    world.addMaterial(std::move(material));
    world.addUniformChunk({0, 0, 0}, material_id, 300.);
    const VoxelAddress heated{{0, 0, 0}, 8, 8, 8};
    const VoxelAddress neighbor{{0, 0, 0}, 9, 8, 8};
    const VoxelAddress nonneighbor{{0, 0, 0}, 10, 8, 8};
    const VoxelAddress control{{0, 0, 0}, 12, 8, 8};
    world.activateInsulatedRegion(1, {heated, neighbor, nonneighbor, control}, fixed_step_s);
    const auto before = snapshot(world, heated, neighbor, nonneighbor, control);
    const double applied = world.addHeat(heated, heater_work, heater_work, 0.);
    Json trajectory = Json::array();
    trajectory.push_back({{"time_s", 0.}, {"cells", before}});
    WorldStepReceipt total_receipt;
    bool complete = true;
    Json first, second;
    double first_reaction_heat = 0;
    constexpr double horizon = .1;
    const unsigned steps = static_cast<unsigned>(std::llround(horizon / fixed_step_s));
    for (unsigned index = 1; index <= steps; ++index) {
        const auto receipt = world.advance(fixed_step_s, budget);
        total_receipt.completed_jobs += receipt.completed_jobs;
        total_receipt.cell_operations += receipt.cell_operations;
        total_receipt.maximum_lag_s = std::max(total_receipt.maximum_lag_s, receipt.maximum_lag_s);
        total_receipt.count_budget_exhausted =
            total_receipt.count_budget_exhausted || receipt.count_budget_exhausted;
        total_receipt.wall_budget_exhausted =
            total_receipt.wall_budget_exhausted || receipt.wall_budget_exhausted;
        if (!receipt.error.empty() || receipt.maximum_lag_s > 1.e-12)
            complete = false;
        const auto current = snapshot(world, heated, neighbor, nonneighbor, control);
        if (index == 1) {
            first = current;
            first_reaction_heat =
                Json::parse(world.reportJson())["regions"][0]["reaction_heat_j"].get<double>();
        }
        if (index == 2)
            second = current;
        trajectory.push_back({{"time_s", index * fixed_step_s}, {"cells", current}});
    }
    const auto report = Json::parse(world.reportJson());
    const auto &region = report["regions"][0];
    return {{"material_id", material_id},
            {"material", name},
            {"material_descriptor", material_descriptor},
            {"reaction_enabled", reactive},
            {"status", complete ? "complete" : "solver_limit"},
            {"fixed_step_s", fixed_step_s},
            {"voxel_size_m", voxel_size},
            {"requested_horizon_s", horizon},
            {"heater_requested_j", heater_work},
            {"heater_applied_j", applied},
            {"before", before},
            {"after_first_step", first},
            {"after_second_step", second},
            {"final", trajectory.back()["cells"]},
            {"trajectory", trajectory},
            {"first_reaction_heat_j", first_reaction_heat},
            {"reaction_heat_j", region["reaction_heat_j"]},
            {"thermal_enthalpy_j", region["thermal_enthalpy_j"]},
            {"chemical_energy_j", region["chemical_energy_j"]},
            {"external_heat_j", region["external_work_j"]},
            {"mass_kg", region["mass_kg"]},
            {"mass_residual_kg", region["mass_residual_kg"]},
            {"products_kg", region["products_kg"]},
            {"combined_energy_residual_j", region["combined_energy_residual_j"]},
            {"work",
             {{"completed_jobs", total_receipt.completed_jobs},
              {"cell_operations", total_receipt.cell_operations},
              {"maximum_lag_s", total_receipt.maximum_lag_s},
              {"count_budget_exhausted", total_receipt.count_budget_exhausted},
              {"wall_budget_exhausted", total_receipt.wall_budget_exhausted}}}};
}

Json fuelExtinctionControl() {
    auto material = oak(4);
    material.fuel_mass_fraction = .001;
    material.oxygen_kg_per_kg_solid = .1;
    material.thermal.reaction.maximum_rate_per_s = 1.e6;
    SparseThermalWorld world(.02);
    world.addMaterial(material);
    world.addUniformChunk({0, 0, 0}, 4, 300.);
    const VoxelAddress cell_address{{0, 0, 0}, 8, 8, 8};
    world.activateInsulatedRegion(1, {cell_address}, .01);
    world.addHeat(cell_address, 3000., 3000., 0.);
    world.advance(.01, {64, 32768, 1000.});
    const auto first = world.activeCells().front();
    const double heat = Json::parse(world.reportJson())["regions"][0]["reaction_heat_j"];
    world.advance(.01, {64, 32768, 1000.});
    const auto second = world.activeCells().front();
    const auto report = Json::parse(world.reportJson())["regions"][0];
    return {{"material_descriptor", descriptor(material)},
            {"fuel_after_first_kg", first.fuel_kg},
            {"fuel_after_second_kg", second.fuel_kg},
            {"oxygen_after_first_kg", first.oxygen_kg},
            {"reaction_heat_after_first_j", heat},
            {"reaction_heat_after_second_j", report["reaction_heat_j"]},
            {"extinguished_by", "finite fuel"}};
}

Json lagControl() {
    SparseThermalWorld world(.02);
    world.addMaterial(inert(1, "glass", 2500., 840., 1.));
    world.addUniformChunk({0, 0, 0}, 1, 300.);
    world.activateInsulatedRegion(1, {{{0, 0, 0}, 8, 8, 8}}, .01);
    const auto receipt = world.advance(
        .25, {.maximum_jobs = 1, .maximum_cell_operations = 100, .maximum_wall_ms = 1000.});
    return {{"completed_jobs", receipt.completed_jobs},
            {"cell_operations", receipt.cell_operations},
            {"regions_late", receipt.regions_late},
            {"maximum_lag_s", receipt.maximum_lag_s},
            {"count_budget_exhausted", receipt.count_budget_exhausted}};
}
} // namespace

int main() {
    try {
        const std::vector<WorldThermalMaterial> materials{
            inert(1, "glass", 2500., 840., 1.), oak(2), inert(3, "iron", 7870., 450., 80.)};
        Json cases = Json::array();
        for (double step : {.01, .05})
            for (const auto &material : materials)
                cases.push_back(run(material, step,
                                    {.maximum_jobs = 64,
                                     .maximum_cell_operations = 32768,
                                     .maximum_wall_ms = 1000.}));
        bool complete = std::all_of(cases.begin(), cases.end(),
                                    [](const auto &item) { return item["status"] == "complete"; });
        Json refinement = Json::array();
        for (unsigned material = 1; material <= 3; ++material) {
            const auto &fine = cases[material - 1], &coarse = cases[material + 2];
            refinement.push_back(
                {{"material_id", material},
                 {"heated_final_temperature_delta_k",
                  fine["final"]["heated"]["temperature_k"].get<double>() -
                      coarse["final"]["heated"]["temperature_k"].get<double>()},
                 {"neighbor_final_temperature_delta_k",
                  fine["final"]["neighbor"]["temperature_k"].get<double>() -
                      coarse["final"]["neighbor"]["temperature_k"].get<double>()},
                 {"fuel_final_delta_kg", fine["final"]["heated"]["fuel_kg"].get<double>() -
                                             coarse["final"]["heated"]["fuel_kg"].get<double>()},
                 {"interpretation", "measured timestep difference; not a convergence claim"}});
        }
        std::cout << Json{{"schema", "banjo.thermal-burn-acceptance.v1"},
                          {"status", complete ? "complete" : "solver_limit"},
                          {"physical_response_validated", false},
                          {"scope",
                           "Four-cell solid thermal reference; finite local oxygen/fuel, "
                           "no airflow, smoke, radiation, moisture, pyrolysis or calibration"},
                          {"assumptions",
                           {{"initial_temperature_k", 300.},
                            {"voxel_size_m", .02},
                            {"heated_cell_external_work_j", 3000.},
                            {"oak_fuel_mass_fraction", .1},
                            {"oak_oxygen_kg_per_kg_solid", .001},
                            {"oak_activation_temperature_k", 600.}}},
                          {"cases", cases},
                          {"timestep_refinement_deltas", refinement},
                          {"fuel_extinction_control", fuelExtinctionControl()},
                          {"bounded_lag_control", lagControl()}}
                         .dump()
                  << '\n';
        return 0;
    } catch (const std::exception &error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
