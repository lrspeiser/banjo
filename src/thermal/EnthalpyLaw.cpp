#include "thermal/EnthalpyLaw.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>
#include <string>
#include <string_view>

namespace banjo::thermal {
namespace {
void finiteNonnegative(double value, std::string_view name) {
    if (!std::isfinite(value) || value < 0.0) throw std::invalid_argument(std::string(name) + " must be finite and non-negative");
}
void finitePositive(double value, std::string_view name) {
    if (!std::isfinite(value) || value <= 0.0) throw std::invalid_argument(std::string(name) + " must be finite and positive");
}
}

void validateEnthalpyMaterial(const EnthalpyMaterial &material) {
    finitePositive(material.solid_heat_capacity_j_kg_k, "solid heat capacity");
    finitePositive(material.liquid_heat_capacity_j_kg_k, "liquid heat capacity");
    finitePositive(material.melting_temperature_k, "melting temperature");
    finiteNonnegative(material.latent_heat_j_kg, "latent heat");
    const double solid_at_melt = material.solid_heat_capacity_j_kg_k * material.melting_temperature_k;
    const double liquid_at_melt = solid_at_melt + material.latent_heat_j_kg;
    if (!std::isfinite(solid_at_melt) || !std::isfinite(liquid_at_melt))
        throw std::overflow_error("enthalpy phase thresholds are not representable");
    if (material.latent_heat_j_kg == 0.0 &&
        material.liquid_heat_capacity_j_kg_k != material.solid_heat_capacity_j_kg_k)
        throw std::invalid_argument("zero-latent material requires equal heat capacities");
}

void validateEnthalpyLump(const EnthalpyLump &lump) {
    finitePositive(lump.mass_kg, "lump mass");
    finiteNonnegative(lump.enthalpy_j_kg, "lump enthalpy");
}

static double temperatureUnchecked(const EnthalpyMaterial &material, double enthalpy) {
    const double solid_at_melt = material.solid_heat_capacity_j_kg_k * material.melting_temperature_k;
    const double liquid_at_melt = solid_at_melt + material.latent_heat_j_kg;
    if (enthalpy < solid_at_melt || material.latent_heat_j_kg == 0.0)
        return enthalpy / material.solid_heat_capacity_j_kg_k;
    if (enthalpy <= liquid_at_melt) return material.melting_temperature_k;
    return material.melting_temperature_k +
           (enthalpy - liquid_at_melt) / material.liquid_heat_capacity_j_kg_k;
}

EnthalpyState stateFromEnthalpy(const EnthalpyMaterial &material, double enthalpy) {
    validateEnthalpyMaterial(material);
    finiteNonnegative(enthalpy, "enthalpy");
    const double solid_at_melt = material.solid_heat_capacity_j_kg_k * material.melting_temperature_k;
    const double liquid_at_melt = solid_at_melt + material.latent_heat_j_kg;
    if (enthalpy < solid_at_melt || material.latent_heat_j_kg == 0.0) {
        const double temperature = enthalpy / material.solid_heat_capacity_j_kg_k;
        if (!std::isfinite(temperature)) throw std::overflow_error("temperature is not representable");
        return {enthalpy, temperature, enthalpy >= solid_at_melt ? 1.0 : 0.0};
    }
    if (enthalpy <= liquid_at_melt) {
        return {enthalpy, material.melting_temperature_k,
                (enthalpy - solid_at_melt) / material.latent_heat_j_kg};
    }
    const double temperature = material.melting_temperature_k +
        (enthalpy - liquid_at_melt) / material.liquid_heat_capacity_j_kg_k;
    if (!std::isfinite(temperature)) throw std::overflow_error("temperature is not representable");
    return {enthalpy, temperature, 1.0};
}

double enthalpyFromTemperaturePhase(const EnthalpyMaterial &material, double temperature, double fraction) {
    validateEnthalpyMaterial(material);
    finiteNonnegative(temperature, "temperature");
    finiteNonnegative(fraction, "liquid fraction");
    if (fraction > 1.0) throw std::invalid_argument("liquid fraction must not exceed one");
    const double solid_at_melt = material.solid_heat_capacity_j_kg_k * material.melting_temperature_k;
    if (material.latent_heat_j_kg == 0.0) {
        const double enthalpy = temperature * material.solid_heat_capacity_j_kg_k;
        if (!std::isfinite(enthalpy)) throw std::overflow_error("enthalpy is not representable");
        return enthalpy;
    }
    if (temperature < material.melting_temperature_k && fraction != 0.0)
        throw std::invalid_argument("sub-melting state must be solid");
    if (temperature > material.melting_temperature_k && fraction != 1.0)
        throw std::invalid_argument("super-melting state must be liquid");
    if (temperature == material.melting_temperature_k)
        return solid_at_melt + fraction * material.latent_heat_j_kg;
    if (temperature < material.melting_temperature_k) {
        const double enthalpy = temperature * material.solid_heat_capacity_j_kg_k;
        if (!std::isfinite(enthalpy)) throw std::overflow_error("enthalpy is not representable");
        return enthalpy;
    }
    const double enthalpy = solid_at_melt + material.latent_heat_j_kg +
        (temperature - material.melting_temperature_k) * material.liquid_heat_capacity_j_kg_k;
    if (!std::isfinite(enthalpy)) throw std::overflow_error("enthalpy is not representable");
    return enthalpy;
}

EnthalpyPairResult exchangePairBackwardEuler(const EnthalpyMaterial &first_material,
    const EnthalpyLump &first, const EnthalpyMaterial &second_material,
    const EnthalpyLump &second, double conductance, double dt) {
    validateEnthalpyMaterial(first_material); validateEnthalpyMaterial(second_material);
    validateEnthalpyLump(first); validateEnthalpyLump(second);
    finiteNonnegative(conductance, "conductance"); finiteNonnegative(dt, "time step");
    EnthalpyPairResult result{first, second, 0.0};
    if (conductance == 0.0 || dt == 0.0) return result;
    const double scale = conductance * dt;
    if (!std::isfinite(scale)) throw std::overflow_error("conductance-time product is not representable");
    if (scale == 0.0) return result;
    const double first_energy = first.mass_kg * first.enthalpy_j_kg;
    const double second_energy = second.mass_kg * second.enthalpy_j_kg;
    if (!std::isfinite(first_energy) || !std::isfinite(second_energy))
        throw std::overflow_error("lump energy is not representable");
    const double first_temperature = stateFromEnthalpy(first_material, first.enthalpy_j_kg).temperature_k;
    const double second_temperature = stateFromEnthalpy(second_material, second.enthalpy_j_kg).temperature_k;
    if (first_temperature == second_temperature) return result;
    const double low = -first_energy;
    const double high = second_energy;
    auto residual = [&](double q) {
        const double ha = first.enthalpy_j_kg + q / first.mass_kg;
        const double hb = second.enthalpy_j_kg - q / second.mass_kg;
        return q / scale - (temperatureUnchecked(second_material, hb) -
                            temperatureUnchecked(first_material, ha));
    };
    double lo = low, hi = high;
    for (unsigned iteration = 0; iteration < 64; ++iteration) {
        const double mid = lo * .5 + hi * .5;
        if (residual(mid) > 0.0) hi = mid; else lo = mid;
    }
    const double q = lo * .5 + hi * .5;
    result.first.enthalpy_j_kg += q / first.mass_kg;
    result.second.enthalpy_j_kg -= q / second.mass_kg;
    result.energy_to_first_j = q;
    validateEnthalpyLump(result.first); validateEnthalpyLump(result.second);
    return result;
}
} // namespace banjo::thermal
