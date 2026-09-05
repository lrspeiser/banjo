#pragma once

#include <string>

namespace banjo::thermal {

// Constant-property, lumped thermal data. display_name is metadata only and
// never selects behavior.
struct MaterialProperties {
    std::string display_name;
    double specific_heat_capacity_j_kg_k{};
    double thermal_conductivity_w_m_k{};

    struct FuelReaction {
        bool enabled{};
        double activation_temperature_k{};
        double maximum_rate_per_s{};
        double heat_of_combustion_j_kg{};
        double oxygen_required_kg_per_kg_fuel{};
    } reaction{};
};

// Sensible energy is measured from 0 K. reference_heat_capacity_j_k is fixed
// for this constant-heat-capacity approximation. The four mass reservoirs
// must sum to mass_kg; reaction only moves mass between those reservoirs.
struct LumpState {
    double mass_kg{};
    double reference_heat_capacity_j_k{};
    double sensible_energy_j{};
    double remaining_fuel_kg{};
    double available_oxygen_kg{};
    double inert_mass_kg{};
    double reaction_products_kg{};
};

struct HeaterResult {
    LumpState state{};
    double applied_work_j{};
};

struct PairExchangeResult {
    LumpState first{};
    LumpState second{};
    // Positive means energy moved from second to first.
    double energy_to_first_j{};
};

struct ReactionResult {
    LumpState state{};
    double consumed_fuel_kg{};
    double consumed_oxygen_kg{};
    double produced_products_kg{};
    double released_heat_j{};
};

void validateMaterial(const MaterialProperties &material);
void validateLump(const LumpState &state);

[[nodiscard]] LumpState makeLump(
    const MaterialProperties &material,
    double temperature_k,
    double remaining_fuel_kg,
    double available_oxygen_kg,
    double inert_mass_kg,
    double reaction_products_kg = 0.0);

// Convenience for a fresh solid lump. solid_mass_kg excludes the finite local
// oxygen reservoir; fuel_mass_fraction splits solid mass into fuel and inert mass.
// The fixed sensible heat capacity is solid_mass_kg * material specific heat;
// trapped oxygen and later products add conserved mass but not heat capacity.
[[nodiscard]] LumpState makeLumpFromSolidMass(
    const MaterialProperties &material,
    double temperature_k,
    double solid_mass_kg,
    double fuel_mass_fraction = 0.0,
    double trapped_oxygen_kg = 0.0);

[[nodiscard]] double temperatureK(const LumpState &state);
[[nodiscard]] double totalChemicalEnergyJ(
    const LumpState &state, const MaterialProperties &material);

// Symmetric half-distance conduction model: G = k_harmonic * area / distance.
// It returns zero if either conductivity or the interface area is zero.
[[nodiscard]] double interfaceConductanceWPerK(
    const MaterialProperties &first_material,
    const MaterialProperties &second_material,
    double interface_area_m2,
    double center_distance_m);

// Adds min(requested_energy_j, maximum_energy_j) as explicit external work.
[[nodiscard]] HeaterResult applyBoundedHeater(
    const LumpState &state,
    double requested_energy_j,
    double maximum_energy_j);

// Exact closed-form solution for one isolated pair with constant G, C1 and C2.
// Combining sequential edge calls is operator splitting, not an exact network solve.
[[nodiscard]] PairExchangeResult exchangePairExact(
    const LumpState &first,
    const LumpState &second,
    double conductance_w_k,
    double dt_s);

// First-order lumped fuel consumption while initially at or above activation.
// Released chemical energy becomes sensible energy in the same lump.
[[nodiscard]] ReactionResult reactAdiabatic(
    const LumpState &state,
    const MaterialProperties &material,
    double dt_s);

} // namespace banjo::thermal
