#pragma once
#ifdef _WIN32
#ifdef BANJO_THERMAL_FIELDS_BUILD
#define BANJO_FIELD_API __declspec(dllexport)
#else
#define BANJO_FIELD_API __declspec(dllimport)
#endif
#else
#define BANJO_FIELD_API __attribute__((visibility("default")))
#endif
// Bounded scalar field adapter. A cell owns an original, fixed thermal mass
// and four closed species reservoirs. It does NOT own geometric motion.
// Cell width 16: thermal_mass_kg, thermal_energy_J, cs, cl (J/kg/K),
// melt_K, latent_J/kg, fuel_kg, oxygen_kg, inert_kg, products_kg,
// chemical_J/kg_fuel, reaction_rate_1/s, activation_K, oxygen/fuel ratio,
// heater_W, reaction_enabled (0 or 1).
// Edge width 3: cell_a, cell_b (exact integer indices), conductance_W/K.
// Receipt width 8: total_energy_before/after_J, external_heat_J,
// converted_chemical_J, species_mass_before/after_kg, energy_residual_J,
// pair_exchange_calls. Failure returns -1 and leaves BOTH outputs unchanged.
extern "C" BANJO_FIELD_API int banjo_thermal_field_step(
    const double* cells, int count, const double* edges, int edge_count,
    double dt_s, double* result, double* receipt);
extern "C" BANJO_FIELD_API int banjo_thermal_field_observe(
    const double* cells, int count, double* temperature_and_liquid_fraction);
