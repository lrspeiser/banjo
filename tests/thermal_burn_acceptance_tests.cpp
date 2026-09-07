#include "world/SparseThermalWorld.hpp"

#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <functional>
#include <iostream>
#include <memory>
#include <nlohmann/json.hpp>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace {
using namespace banjo;
using Json = nlohmann::json;
void require(bool condition, std::string_view message) {
    if (!condition)
        throw std::runtime_error(std::string(message));
}
void near(double actual, double expected, double tolerance, std::string_view message) {
    if (!std::isfinite(actual) || std::abs(actual - expected) > tolerance)
        throw std::runtime_error(std::string(message));
}
WorldThermalMaterial inert(unsigned id, std::string name, double density, double heat_capacity,
                           double conductivity) {
    return {.id = id,
            .solid_density_kg_m3 = density,
            .thermal = {.display_name = std::move(name),
                        .specific_heat_capacity_j_kg_k = heat_capacity,
                        .thermal_conductivity_w_m_k = conductivity}};
}
WorldThermalMaterial oak(unsigned id, std::string name = "oak") {
    auto value = inert(id, std::move(name), 700., 1700., .12);
    value.fuel_mass_fraction = .1;
    value.oxygen_kg_per_kg_solid = .001;
    value.thermal.reaction = {.enabled = true,
                              .activation_temperature_k = 600.,
                              .maximum_rate_per_s = 20.,
                              .heat_of_combustion_j_kg = 16.e6,
                              .oxygen_required_kg_per_kg_fuel = 1.};
    return value;
}
WorldStepBudget generous() {
    return {64, 32768, 1000.};
}
const ThermalCellView &at(const std::vector<ThermalCellView> &cells, const VoxelAddress &address) {
    const auto found = std::find_if(cells.begin(), cells.end(),
                                    [&](const auto &entry) { return entry.address == address; });
    if (found == cells.end())
        throw std::runtime_error("cell missing");
    return *found;
}
struct Fixture {
    SparseThermalWorld world{.02};
    VoxelAddress heated{{0, 0, 0}, 8, 8, 8}, neighbor{{0, 0, 0}, 9, 8, 8},
        nonneighbor{{0, 0, 0}, 10, 8, 8}, control{{0, 0, 0}, 12, 8, 8};
    Fixture(WorldThermalMaterial material, double dt) {
        const unsigned id = material.id;
        world.addMaterial(std::move(material));
        world.addUniformChunk({0, 0, 0}, id, 300.);
        world.activateInsulatedRegion(1, {heated, neighbor, nonneighbor, control}, dt);
        near(world.addHeat(heated, 3000., 3000., 0.), 3000., 0., "finite heater work");
    }
};

void matchedMaterialsConductAndOnlyPropertiesReact() {
    for (double dt : {.01, .05}) {
        for (auto material : std::vector<WorldThermalMaterial>{
                 inert(1, "glass", 2500., 840., 1.), oak(2), inert(3, "iron", 7870., 450., 80.)}) {
            const bool reactive = material.thermal.reaction.enabled;
            Fixture fixture(std::move(material), dt);
            const auto before = fixture.world.activeCells();
            const auto receipt = fixture.world.advance(dt, generous());
            require(receipt.error.empty() && receipt.completed_jobs == 1,
                    "matched material thermal job must complete");
            const auto after = fixture.world.activeCells();
            require(at(after, fixture.neighbor).temperature_k >
                        at(before, fixture.neighbor).temperature_k,
                    "declared conductivity must heat a face neighbor");
            near(at(after, fixture.control).temperature_k, 300., 0.,
                 "isolated unheated control must remain unchanged");
            near(at(after, fixture.nonneighbor).fuel_kg, at(before, fixture.nonneighbor).fuel_kg,
                 0., "non-neighbor must not burn on the immediate step");
            const auto report = Json::parse(fixture.world.reportJson())["regions"][0];
            require((report["reaction_heat_j"].get<double>() > 0) == reactive,
                    "reaction enablement must come from declared material properties");
            const unsigned remaining = static_cast<unsigned>(std::llround(.1 / dt)) - 1;
            for (unsigned step = 0; step < remaining; ++step)
                require(fixture.world.advance(dt, generous()).error.empty(),
                        "matched 0.1 second horizon must complete");
            for (const auto &value : fixture.world.activeCells())
                near(value.region_time_s, .1, 1.e-12, "matched final horizon");
            const auto final_report = Json::parse(fixture.world.reportJson())["regions"][0];
            near(final_report["combined_energy_residual_j"].get<double>(), 0., 1.e-6,
                 "combined sensible chemical and external energy ledger");
        }
    }
}

void finiteFuelExtinguishesWithOxygenRemaining() {
    auto material = oak(2);
    material.fuel_mass_fraction = .001;
    material.oxygen_kg_per_kg_solid = .1;
    material.thermal.reaction.maximum_rate_per_s = 1.e6;
    Fixture fixture(std::move(material), .01);
    require(fixture.world.advance(.01, generous()).error.empty(), "fuel exhaustion first step");
    const auto first = at(fixture.world.activeCells(), fixture.heated);
    near(first.fuel_kg, 0., 1.e-18, "finite fuel must exhaust exactly");
    require(first.oxygen_kg > 0, "fuel-limited control must retain oxygen");
    const double heat = Json::parse(fixture.world.reportJson())["regions"][0]["reaction_heat_j"];
    require(fixture.world.advance(.01, generous()).error.empty(), "fuel exhaustion second step");
    const auto second = at(fixture.world.activeCells(), fixture.heated);
    near(second.fuel_kg, 0., 1.e-18, "exhausted fuel remains extinct");
    near(Json::parse(fixture.world.reportJson())["regions"][0]["reaction_heat_j"].get<double>(),
         heat, 1.e-12, "fuel exhaustion stops further reaction heat");
}

void finiteOxygenExtinguishesOakReaction() {
    for (double dt : {.01, .05}) {
        Fixture fixture(oak(2), dt);
        require(fixture.world.advance(dt, generous()).error.empty(), "first oak step");
        const auto first_cells = fixture.world.activeCells();
        near(at(first_cells, fixture.heated).oxygen_kg, 0., 1.e-18,
             "finite oxygen reservoir must be exhausted exactly");
        const auto first_report = Json::parse(fixture.world.reportJson())["regions"][0];
        const double heat = first_report["reaction_heat_j"];
        const double fuel = at(first_cells, fixture.heated).fuel_kg;
        require(fixture.world.advance(dt, generous()).error.empty(), "second oak step");
        const auto second_cells = fixture.world.activeCells();
        const auto second_report = Json::parse(fixture.world.reportJson())["regions"][0];
        near(second_report["reaction_heat_j"].get<double>(), heat, 1.e-12,
             "oxygen exhaustion must stop further heat release");
        near(at(second_cells, fixture.heated).fuel_kg, fuel, 1.e-18,
             "oxygen exhaustion must stop further fuel consumption");
    }
}

void reactionDoesNotDependOnOakDisplayName() {
    Fixture named(oak(2, "oak"), .05), renamed(oak(2, "blue test solid"), .05);
    named.world.advance(.05, generous());
    renamed.world.advance(.05, generous());
    const auto a = at(named.world.activeCells(), named.heated);
    const auto b = at(renamed.world.activeCells(), renamed.heated);
    near(a.fuel_kg, b.fuel_kg, 0., "renaming cannot alter fuel response");
    near(a.temperature_k, b.temperature_k, 0., "renaming cannot alter thermal response");
}

void budgetsBoundLagAndIgnoreColdStorageVolume() {
    auto make = [](unsigned extra_chunks) {
        auto world = std::make_unique<SparseThermalWorld>(.02);
        world->addMaterial(inert(1, "glass", 2500., 840., 1.));
        world->addUniformChunk({0, 0, 0}, 1, 300.);
        for (unsigned i = 0; i < extra_chunks; ++i)
            world->addUniformChunk({static_cast<int>(i) + 2, 0, 0}, 1, 300.);
        world->activateInsulatedRegion(1, {{{0, 0, 0}, 8, 8, 8}}, .01);
        return world;
    };
    auto small = make(0), large = make(128);
    const WorldStepBudget limited{1, 100, 1000.};
    const auto a = small->advance(.25, limited), b = large->advance(.25, limited);
    require(a.completed_jobs == 1 && a.count_budget_exhausted && a.regions_late == 1 &&
                a.maximum_lag_s > .2,
            "bounded scheduler must expose unfinished lag");
    require(a.cell_operations == b.cell_operations && a.completed_jobs == b.completed_jobs,
            "unrelated compact cold storage must not change active work");
}
} // namespace

int main() {
    const std::vector<std::pair<std::string_view, std::function<void()>>> tests{
        {"matched conduction and property reaction", matchedMaterialsConductAndOnlyPropertiesReact},
        {"finite oxygen extinction", finiteOxygenExtinguishesOakReaction},
        {"finite fuel extinction", finiteFuelExtinguishesWithOxygenRemaining},
        {"display name invariance", reactionDoesNotDependOnOakDisplayName},
        {"bounded lag and sparse cost", budgetsBoundLagAndIgnoreColdStorageVolume}};
    unsigned failures = 0;
    for (const auto &[name, test] : tests) {
        try {
            test();
            std::cout << "[PASS] " << name << '\n';
        } catch (const std::exception &e) {
            ++failures;
            std::cerr << "[FAIL] " << name << ": " << e.what() << '\n';
        }
    }
    std::cout << tests.size() - failures << '/' << tests.size() << " tests passed\n";
    return failures ? EXIT_FAILURE : EXIT_SUCCESS;
}
