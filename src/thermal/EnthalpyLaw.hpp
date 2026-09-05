#pragma once

namespace banjo::thermal {

// A single isothermal phase transition with constant solid/liquid heat
// capacities. Enthalpy is specific (J/kg) and referenced to 0 K.
struct EnthalpyMaterial {
    double solid_heat_capacity_j_kg_k{};
    double liquid_heat_capacity_j_kg_k{};
    double melting_temperature_k{};
    double latent_heat_j_kg{};
};

struct EnthalpyState {
    double enthalpy_j_kg{};
    double temperature_k{};
    double liquid_fraction{};
};

struct EnthalpyLump {
    double mass_kg{};
    double enthalpy_j_kg{};
};

struct EnthalpyPairResult {
    EnthalpyLump first{};
    EnthalpyLump second{};
    // Positive means energy moved from second to first.
    double energy_to_first_j{};
};

void validateEnthalpyMaterial(const EnthalpyMaterial &material);
void validateEnthalpyLump(const EnthalpyLump &lump);

[[nodiscard]] EnthalpyState stateFromEnthalpy(
    const EnthalpyMaterial &material, double enthalpy_j_kg);

[[nodiscard]] double enthalpyFromTemperaturePhase(
    const EnthalpyMaterial &material, double temperature_k, double liquid_fraction);

// Backward-Euler conduction for two finite lumps. The solve is conservative,
// bounded, and first-order in time; it is not an exact transient solution.
[[nodiscard]] EnthalpyPairResult exchangePairBackwardEuler(
    const EnthalpyMaterial &first_material,
    const EnthalpyLump &first,
    const EnthalpyMaterial &second_material,
    const EnthalpyLump &second,
    double conductance_w_k,
    double dt_s);

} // namespace banjo::thermal
