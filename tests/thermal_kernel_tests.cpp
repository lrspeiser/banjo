#include "thermal/ThermalKernel.hpp"

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
using namespace banjo::thermal;

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

MaterialProperties glass(std::string name = "glass") {
    return {std::move(name), 840.0, 1.0, {}};
}

MaterialProperties iron(std::string name = "iron") {
    return {std::move(name), 450.0, 80.0, {}};
}

MaterialProperties wood(std::string name = "wood-like demo") {
    return {
        std::move(name),
        1700.0,
        0.12,
        {.enabled = true,
         .activation_temperature_k = 600.0,
         .maximum_rate_per_s = 2.0,
         .heat_of_combustion_j_kg = 16.0e6,
         .oxygen_required_kg_per_kg_fuel = 1.5},
    };
}

double totalMass(const LumpState &state) {
    return state.remaining_fuel_kg + state.available_oxygen_kg +
        state.inert_mass_kg + state.reaction_products_kg;
}

void exactTwoLumpSolution() {
    const auto material = glass();
    const LumpState hot = makeLump(material, 500.0, 0.0, 0.0, 2.0);
    const LumpState cold = makeLump(material, 100.0, 0.0, 0.0, 1.0);
    constexpr double conductance = 120.0;
    constexpr double dt = 7.0;
    const auto result = exchangePairExact(hot, cold, conductance, dt);

    const double c1 = hot.reference_heat_capacity_j_k;
    const double c2 = cold.reference_heat_capacity_j_k;
    const double mean = (c1 * 500.0 + c2 * 100.0) / (c1 + c2);
    const double decay = std::exp(-conductance * (1.0 / c1 + 1.0 / c2) * dt);
    near(temperatureK(result.first), mean + c2 / (c1 + c2) * 400.0 * decay,
         1e-12, "hot analytical temperature");
    near(temperatureK(result.second), mean - c1 / (c1 + c2) * 400.0 * decay,
         1e-12, "cold analytical temperature");
    near(result.first.sensible_energy_j + result.second.sensible_energy_j,
         hot.sensible_energy_j + cold.sensible_energy_j, 1e-9,
         "pair sensible energy");
    near(result.energy_to_first_j,
         result.first.sensible_energy_j - hot.sensible_energy_j, 1e-9,
         "equal and opposite transfer ledger");
}

void pairPartitionInvariantAndLargeStepPositive() {
    const auto material = iron();
    const LumpState first = makeLump(material, 1500.0, 0.0, 0.0, 0.25);
    const LumpState second = makeLump(material, 2.0, 0.0, 0.0, 4.0);
    constexpr double conductance = 9000.0;
    const auto whole = exchangePairExact(first, second, conductance, 20.0);

    auto split_first = first;
    auto split_second = second;
    for (int i = 0; i < 200; ++i) {
        const auto part = exchangePairExact(split_first, split_second, conductance, 0.1);
        split_first = part.first;
        split_second = part.second;
    }
    near(split_first.sensible_energy_j, whole.first.sensible_energy_j, 1e-8,
         "partitioned first energy");
    near(split_second.sensible_energy_j, whole.second.sensible_energy_j, 1e-8,
         "partitioned second energy");

    const auto huge = exchangePairExact(first, second, 1.0e300, 1.0e300);
    require(temperatureK(huge.first) >= 0.0 && temperatureK(huge.second) >= 0.0,
            "large step temperatures stay non-negative");
    near(temperatureK(huge.first), temperatureK(huge.second), 1e-12,
         "large step reaches equilibrium");
}

void conductanceUsesDeclaredProperties() {
    const auto g = glass();
    const auto i = iron();
    const double expected_k = 2.0 / (1.0 / g.thermal_conductivity_w_m_k +
                                     1.0 / i.thermal_conductivity_w_m_k);
    near(interfaceConductanceWPerK(g, i, 0.5, 0.25), expected_k * 2.0, 1e-12,
         "harmonic interface conductance");
    near(interfaceConductanceWPerK(g, MaterialProperties{"insulator", 1000.0, 0.0},
                                   0.5, 0.25),
         0.0, 0.0, "zero-conductivity boundary");
}

void heaterReportsBoundedExternalWork() {
    const auto state = makeLumpFromSolidMass(glass(), 300.0, 2.0);
    const auto heated = applyBoundedHeater(state, 5000.0, 1200.0);
    near(heated.applied_work_j, 1200.0, 0.0, "heater work bound");
    near(heated.state.sensible_energy_j - state.sensible_energy_j, 1200.0, 0.0,
         "heater energy ledger");
}

void freshSolidUsesFixedSolidHeatCapacity() {
    const auto material = wood();
    const auto state = makeLumpFromSolidMass(material, 650.0, 4.0, 0.25, 2.0);
    near(state.reference_heat_capacity_j_k,
         4.0 * material.specific_heat_capacity_j_kg_k, 0.0,
         "solid reference heat capacity excludes trapped oxygen");
    near(temperatureK(state), 650.0, 1e-12, "fresh solid temperature");
    const auto reacted = reactAdiabatic(state, material, 1.0);
    near(reacted.state.reference_heat_capacity_j_k,
         state.reference_heat_capacity_j_k, 0.0,
         "reaction retains constant heat-capacity approximation");
}

void reactionConservesMassAndSensiblePlusChemicalEnergy() {
    const auto material = wood();
    const auto initial = makeLumpFromSolidMass(material, 700.0, 5.0, 0.4, 5.0);
    const double energy_before = initial.sensible_energy_j +
        totalChemicalEnergyJ(initial, material);
    const auto result = reactAdiabatic(initial, material, 0.25);
    require(result.consumed_fuel_kg > 0.0, "hot oxygenated fuel reacts");
    near(result.produced_products_kg,
         result.consumed_fuel_kg + result.consumed_oxygen_kg, 1e-15,
         "products contain both reactant masses");
    near(totalMass(result.state), totalMass(initial), 2e-15, "reaction total mass");
    near(result.state.mass_kg, initial.mass_kg, 0.0, "declared lump mass");
    near(result.state.sensible_energy_j + totalChemicalEnergyJ(result.state, material),
         energy_before, 1e-8, "adiabatic sensible plus chemical energy");
    near(result.released_heat_j,
         result.consumed_fuel_kg * material.reaction.heat_of_combustion_j_kg,
         1e-9, "released heat ledger");
}

void reactionBoundsAndInactiveCases() {
    const auto material = wood();
    const auto oxygen_limited = makeLump(material, 700.0, 10.0, 0.3, 1.0);
    const auto exhausted = reactAdiabatic(oxygen_limited, material, 1.0e9);
    near(exhausted.consumed_fuel_kg, 0.2, 1e-15, "oxygen-limited fuel consumption");
    near(exhausted.state.available_oxygen_kg, 0.0, 1e-15, "oxygen exhaustion");

    const auto fuel_limited = makeLump(material, 700.0, 0.25, 10.0, 1.0);
    const auto fuel_exhausted = reactAdiabatic(fuel_limited, material, 1.0e9);
    near(fuel_exhausted.state.remaining_fuel_kg, 0.0, 1e-15, "fuel exhaustion");

    const auto no_oxygen = makeLump(material, 700.0, 1.0, 0.0, 1.0);
    near(reactAdiabatic(no_oxygen, material, 10.0).consumed_fuel_kg, 0.0, 0.0,
         "no oxygen means no reaction");
    const auto cold = makeLump(material, 599.9, 1.0, 2.0, 1.0);
    near(reactAdiabatic(cold, material, 10.0).consumed_fuel_kg, 0.0, 0.0,
         "cold fuel does not react");

    const auto glass_state = makeLump(glass(), 2000.0, 0.0, 0.0, 1.0);
    near(reactAdiabatic(glass_state, glass(), 10.0).released_heat_j, 0.0, 0.0,
         "glass is thermal-only by declared properties");
    const auto iron_state = makeLump(iron(), 2000.0, 0.0, 0.0, 1.0);
    near(reactAdiabatic(iron_state, iron(), 10.0).released_heat_j, 0.0, 0.0,
         "iron is thermal-only by declared properties");
}

void materialDisplayNameCannotChangePhysics() {
    const auto oak = wood("oak");
    const auto renamed = wood("fictional blue block");
    const auto first = makeLump(oak, 800.0, 1.0, 3.0, 2.0);
    const auto second = makeLump(renamed, 800.0, 1.0, 3.0, 2.0);
    const auto oak_result = reactAdiabatic(first, oak, 0.4);
    const auto renamed_result = reactAdiabatic(second, renamed, 0.4);
    near(oak_result.consumed_fuel_kg, renamed_result.consumed_fuel_kg, 0.0,
         "display name invariant reaction");
    near(oak_result.state.sensible_energy_j, renamed_result.state.sensible_energy_j, 0.0,
         "display name invariant energy");
}

void invalidInputIsAtomic() {
    const auto state = makeLump(glass(), 300.0, 0.0, 0.0, 1.0);
    const LumpState original = state;
    bool rejected = false;
    try {
        (void)exchangePairExact(
            state, state, std::numeric_limits<double>::quiet_NaN(), 1.0);
    } catch (const std::invalid_argument &) {
        rejected = true;
    }
    require(rejected, "non-finite conductance rejected");
    near(state.sensible_energy_j, original.sensible_energy_j, 0.0,
         "invalid pair call leaves input untouched");

    auto bad_material = wood();
    bad_material.reaction.maximum_rate_per_s = -1.0;
    rejected = false;
    try {
        (void)reactAdiabatic(state, bad_material, 1.0);
    } catch (const std::invalid_argument &) {
        rejected = true;
    }
    require(rejected, "negative reaction rate rejected");
    near(state.sensible_energy_j, original.sensible_energy_j, 0.0,
         "invalid reaction call leaves input untouched");

    LumpState inconsistent = state;
    inconsistent.mass_kg += 1.0;
    rejected = false;
    try {
        (void)applyBoundedHeater(inconsistent, 1.0, 1.0);
    } catch (const std::invalid_argument &) {
        rejected = true;
    }
    require(rejected, "unaccounted mass rejected");
}

} // namespace

int main() {
    const std::vector<std::pair<std::string_view, std::function<void()>>> tests{
        {"analytical exact pair", exactTwoLumpSolution},
        {"pair partition invariance", pairPartitionInvariantAndLargeStepPositive},
        {"declared conductivity", conductanceUsesDeclaredProperties},
        {"bounded heater work", heaterReportsBoundedExternalWork},
        {"fixed solid heat capacity", freshSolidUsesFixedSolidHeatCapacity},
        {"reaction conservation", reactionConservesMassAndSensiblePlusChemicalEnergy},
        {"reaction bounds and inactive materials", reactionBoundsAndInactiveCases},
        {"material display-name invariance", materialDisplayNameCannotChangePhysics},
        {"invalid input atomicity", invalidInputIsAtomic},
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
