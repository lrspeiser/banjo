#include "thermal/ThermalKernel.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>
#include <string_view>

namespace banjo::thermal {
namespace {

void requireFiniteNonnegative(double value, std::string_view field) {
    if (!std::isfinite(value) || value < 0.0) {
        throw std::invalid_argument(std::string(field) + " must be finite and non-negative");
    }
}

void requireFinitePositive(double value, std::string_view field) {
    if (!std::isfinite(value) || value <= 0.0) {
        throw std::invalid_argument(std::string(field) + " must be finite and positive");
    }
}

double reservoirMass(const LumpState &state) {
    const double reactants = state.remaining_fuel_kg + state.available_oxygen_kg;
    const double non_reactants = state.inert_mass_kg + state.reaction_products_kg;
    if (!std::isfinite(reactants) || !std::isfinite(non_reactants) ||
        !std::isfinite(reactants + non_reactants)) {
        throw std::invalid_argument("lump reservoir mass sum must be finite");
    }
    return reactants + non_reactants;
}

void requireFiniteResult(double value, std::string_view quantity) {
    if (!std::isfinite(value)) {
        throw std::overflow_error(std::string(quantity) + " is not representable");
    }
}

} // namespace

void validateMaterial(const MaterialProperties &material) {
    requireFinitePositive(
        material.specific_heat_capacity_j_kg_k,
        "specific_heat_capacity_j_kg_k");
    requireFiniteNonnegative(
        material.thermal_conductivity_w_m_k,
        "thermal_conductivity_w_m_k");

    const auto &reaction = material.reaction;
    requireFiniteNonnegative(reaction.activation_temperature_k, "activation_temperature_k");
    requireFiniteNonnegative(reaction.maximum_rate_per_s, "maximum_rate_per_s");
    requireFiniteNonnegative(reaction.heat_of_combustion_j_kg, "heat_of_combustion_j_kg");
    requireFiniteNonnegative(
        reaction.oxygen_required_kg_per_kg_fuel,
        "oxygen_required_kg_per_kg_fuel");
    if (reaction.enabled &&
        (reaction.maximum_rate_per_s <= 0.0 ||
         reaction.heat_of_combustion_j_kg <= 0.0 ||
         reaction.oxygen_required_kg_per_kg_fuel <= 0.0)) {
        throw std::invalid_argument(
            "enabled fuel reaction requires positive rate, heat, and oxygen ratio");
    }
}

void validateLump(const LumpState &state) {
    requireFinitePositive(state.mass_kg, "mass_kg");
    requireFinitePositive(state.reference_heat_capacity_j_k, "reference_heat_capacity_j_k");
    requireFiniteNonnegative(state.sensible_energy_j, "sensible_energy_j");
    requireFiniteNonnegative(state.remaining_fuel_kg, "remaining_fuel_kg");
    requireFiniteNonnegative(state.available_oxygen_kg, "available_oxygen_kg");
    requireFiniteNonnegative(state.inert_mass_kg, "inert_mass_kg");
    requireFiniteNonnegative(state.reaction_products_kg, "reaction_products_kg");

    const double accounted_mass = reservoirMass(state);
    const double scale = std::max({1.0, state.mass_kg, accounted_mass});
    if (std::abs(accounted_mass - state.mass_kg) >
        32.0 * std::numeric_limits<double>::epsilon() * scale) {
        throw std::invalid_argument("lump mass reservoirs must sum to mass_kg");
    }
    requireFiniteResult(
        state.sensible_energy_j / state.reference_heat_capacity_j_k,
        "temperature");
}

LumpState makeLump(
    const MaterialProperties &material,
    double temperature_k,
    double remaining_fuel_kg,
    double available_oxygen_kg,
    double inert_mass_kg,
    double reaction_products_kg) {
    validateMaterial(material);
    requireFiniteNonnegative(temperature_k, "temperature_k");
    requireFiniteNonnegative(remaining_fuel_kg, "remaining_fuel_kg");
    requireFiniteNonnegative(available_oxygen_kg, "available_oxygen_kg");
    requireFiniteNonnegative(inert_mass_kg, "inert_mass_kg");
    requireFiniteNonnegative(reaction_products_kg, "reaction_products_kg");

    LumpState result;
    result.remaining_fuel_kg = remaining_fuel_kg;
    result.available_oxygen_kg = available_oxygen_kg;
    result.inert_mass_kg = inert_mass_kg;
    result.reaction_products_kg = reaction_products_kg;
    result.mass_kg = reservoirMass(result);
    requireFinitePositive(result.mass_kg, "mass_kg");
    result.reference_heat_capacity_j_k =
        result.mass_kg * material.specific_heat_capacity_j_kg_k;
    result.sensible_energy_j = result.reference_heat_capacity_j_k * temperature_k;
    requireFiniteResult(result.reference_heat_capacity_j_k, "reference heat capacity");
    requireFiniteResult(result.sensible_energy_j, "sensible energy");
    validateLump(result);
    return result;
}

LumpState makeLumpFromSolidMass(
    const MaterialProperties &material,
    double temperature_k,
    double solid_mass_kg,
    double fuel_mass_fraction,
    double trapped_oxygen_kg) {
    requireFinitePositive(solid_mass_kg, "solid_mass_kg");
    requireFiniteNonnegative(fuel_mass_fraction, "fuel_mass_fraction");
    if (fuel_mass_fraction > 1.0) {
        throw std::invalid_argument("fuel_mass_fraction must not exceed one");
    }
    requireFiniteNonnegative(trapped_oxygen_kg, "trapped_oxygen_kg");
    const double fuel_mass_kg = solid_mass_kg * fuel_mass_fraction;
    LumpState result = makeLump(
        material,
        temperature_k,
        fuel_mass_kg,
        trapped_oxygen_kg,
        solid_mass_kg - fuel_mass_kg);
    result.reference_heat_capacity_j_k =
        solid_mass_kg * material.specific_heat_capacity_j_kg_k;
    result.sensible_energy_j = result.reference_heat_capacity_j_k * temperature_k;
    requireFiniteResult(result.reference_heat_capacity_j_k, "reference heat capacity");
    requireFiniteResult(result.sensible_energy_j, "sensible energy");
    validateLump(result);
    return result;
}

double temperatureK(const LumpState &state) {
    validateLump(state);
    return state.sensible_energy_j / state.reference_heat_capacity_j_k;
}

double totalChemicalEnergyJ(
    const LumpState &state, const MaterialProperties &material) {
    validateLump(state);
    validateMaterial(material);
    const double energy = state.remaining_fuel_kg * material.reaction.heat_of_combustion_j_kg;
    requireFiniteResult(energy, "chemical energy");
    return energy;
}

double interfaceConductanceWPerK(
    const MaterialProperties &first_material,
    const MaterialProperties &second_material,
    double interface_area_m2,
    double center_distance_m) {
    validateMaterial(first_material);
    validateMaterial(second_material);
    requireFiniteNonnegative(interface_area_m2, "interface_area_m2");
    requireFinitePositive(center_distance_m, "center_distance_m");
    const double first_k = first_material.thermal_conductivity_w_m_k;
    const double second_k = second_material.thermal_conductivity_w_m_k;
    if (interface_area_m2 == 0.0 || first_k == 0.0 || second_k == 0.0) {
        return 0.0;
    }
    const double lower_k = std::min(first_k, second_k);
    const double upper_k = std::max(first_k, second_k);
    const double harmonic_k = lower_k / (0.5 * (1.0 + lower_k / upper_k));
    const double conductance = harmonic_k * interface_area_m2 / center_distance_m;
    requireFiniteResult(conductance, "interface conductance");
    return conductance;
}

HeaterResult applyBoundedHeater(
    const LumpState &state,
    double requested_energy_j,
    double maximum_energy_j) {
    validateLump(state);
    requireFiniteNonnegative(requested_energy_j, "requested_energy_j");
    requireFiniteNonnegative(maximum_energy_j, "maximum_energy_j");
    HeaterResult result{state, std::min(requested_energy_j, maximum_energy_j)};
    requireFiniteResult(result.state.sensible_energy_j + result.applied_work_j, "heated energy");
    result.state.sensible_energy_j += result.applied_work_j;
    return result;
}

PairExchangeResult exchangePairExact(
    const LumpState &first,
    const LumpState &second,
    double conductance_w_k,
    double dt_s) {
    validateLump(first);
    validateLump(second);
    requireFiniteNonnegative(conductance_w_k, "conductance_w_k");
    requireFiniteNonnegative(dt_s, "dt_s");

    PairExchangeResult result{first, second, 0.0};
    if (conductance_w_k == 0.0 || dt_s == 0.0 ||
        (first.sensible_energy_j == second.sensible_energy_j &&
         first.reference_heat_capacity_j_k == second.reference_heat_capacity_j_k)) {
        return result;
    }

    const double c1 = first.reference_heat_capacity_j_k;
    const double c2 = second.reference_heat_capacity_j_k;
    const double combined_capacity = c1 + c2;
    const double combined_energy = first.sensible_energy_j + second.sensible_energy_j;
    requireFiniteResult(combined_capacity, "combined heat capacity");
    requireFiniteResult(combined_energy, "combined sensible energy");

    const double rate_per_s = conductance_w_k * (1.0 / c1 + 1.0 / c2);
    const double exponent = rate_per_s * dt_s;
    const double one_minus_decay =
        std::isfinite(exponent) ? -std::expm1(-exponent) : 1.0;
    const double equilibrium_first_energy = combined_energy * (c1 / combined_capacity);
    requireFiniteResult(equilibrium_first_energy, "equilibrium energy");
    double transfer =
        (equilibrium_first_energy - first.sensible_energy_j) * one_minus_decay;
    requireFiniteResult(transfer, "pair energy transfer");

    // Protect positivity against the final few ulps without changing the
    // analytical result at ordinary scales.
    transfer = std::clamp(
        transfer,
        -first.sensible_energy_j,
        second.sensible_energy_j);
    result.first.sensible_energy_j += transfer;
    result.second.sensible_energy_j -= transfer;
    result.energy_to_first_j = transfer;
    validateLump(result.first);
    validateLump(result.second);
    return result;
}

ReactionResult reactAdiabatic(
    const LumpState &state,
    const MaterialProperties &material,
    double dt_s) {
    validateLump(state);
    validateMaterial(material);
    requireFiniteNonnegative(dt_s, "dt_s");

    ReactionResult result{state};
    const auto &reaction = material.reaction;
    if (!reaction.enabled || dt_s == 0.0 || state.remaining_fuel_kg == 0.0 ||
        state.available_oxygen_kg == 0.0 ||
        temperatureK(state) < reaction.activation_temperature_k) {
        return result;
    }

    const double exponent = reaction.maximum_rate_per_s * dt_s;
    const double reacted_fraction =
        std::isfinite(exponent) ? -std::expm1(-exponent) : 1.0;
    const double kinetic_limit_kg = state.remaining_fuel_kg * reacted_fraction;
    const double oxygen_limit_kg =
        state.available_oxygen_kg / reaction.oxygen_required_kg_per_kg_fuel;
    result.consumed_fuel_kg =
        std::min({state.remaining_fuel_kg, kinetic_limit_kg, oxygen_limit_kg});
    result.consumed_oxygen_kg =
        result.consumed_fuel_kg * reaction.oxygen_required_kg_per_kg_fuel;
    result.produced_products_kg = result.consumed_fuel_kg + result.consumed_oxygen_kg;
    result.released_heat_j =
        result.consumed_fuel_kg * reaction.heat_of_combustion_j_kg;
    requireFiniteResult(result.consumed_oxygen_kg, "consumed oxygen");
    requireFiniteResult(result.produced_products_kg, "reaction products");
    requireFiniteResult(result.released_heat_j, "released heat");
    requireFiniteResult(
        state.sensible_energy_j + result.released_heat_j,
        "post-reaction sensible energy");

    result.state.remaining_fuel_kg -= result.consumed_fuel_kg;
    result.state.available_oxygen_kg -= result.consumed_oxygen_kg;
    result.state.reaction_products_kg += result.produced_products_kg;
    result.state.sensible_energy_j += result.released_heat_j;
    // Remove tiny negative residuals caused by subtraction at an exhaustion bound.
    result.state.remaining_fuel_kg = std::max(0.0, result.state.remaining_fuel_kg);
    result.state.available_oxygen_kg = std::max(0.0, result.state.available_oxygen_kg);
    validateLump(result.state);
    return result;
}

} // namespace banjo::thermal
