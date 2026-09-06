#include "thermal/EnthalpyLaw.hpp"

#include <algorithm>
#include <array>
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

static double temperatureSlopeUnchecked(const EnthalpyMaterial &material, double enthalpy) {
    const double solid_at_melt = material.solid_heat_capacity_j_kg_k * material.melting_temperature_k;
    const double liquid_at_melt = solid_at_melt + material.latent_heat_j_kg;
    if (enthalpy < solid_at_melt || material.latent_heat_j_kg == 0.0)
        return 1.0 / material.solid_heat_capacity_j_kg_k;
    if (enthalpy <= liquid_at_melt) return 0.0;
    return 1.0 / material.liquid_heat_capacity_j_kg_k;
}

static int backwardEulerResidualSign(double q, double scale, double temperature_difference) {
    const double flux = q / scale;
    if (flux < temperature_difference) return -1;
    if (flux > temperature_difference) return 1;
    return 0;
}

static double affineBackwardEulerRoot(double anchor, double temperature_difference,
    double temperature_drop_per_joule, double scale) {
    if (temperature_drop_per_joule == 0.0)
        return scale * temperature_difference;
    if (!std::isfinite(temperature_drop_per_joule))
        return anchor;

    // q = scale * (delta_temperature(anchor) - slope * (q - anchor)).
    // Choose the form whose dimensionless product cannot overflow. This also
    // avoids forming scale * temperature_difference for very stiff exchanges.
    if (scale <= 1.0 / temperature_drop_per_joule) {
        const double stiffness = scale * temperature_drop_per_joule;
        const double denominator = 1.0 + stiffness;
        return (scale / denominator) * temperature_difference +
               (stiffness / denominator) * anchor;
    }
    const double denominator = 1.0 / scale + temperature_drop_per_joule;
    return temperature_difference / denominator +
           (temperature_drop_per_joule / denominator) * anchor;
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
    auto temperatures = [&](double q) {
        const double ha = first.enthalpy_j_kg + q / first.mass_kg;
        const double hb = second.enthalpy_j_kg - q / second.mass_kg;
        return std::array{temperatureUnchecked(first_material, ha),
                          temperatureUnchecked(second_material, hb)};
    };

    // Each temperature is affine in enthalpy in its solid and liquid branches,
    // and constant on its latent-heat plateau. The four possible phase edges
    // partition the conservative energy interval into at most five affine
    // residual segments (a subset of the nine phase-branch pairs).
    std::array<double, 6> edges{};
    std::size_t edge_count = 0;
    edges[edge_count++] = low;
    edges[edge_count++] = high;
    auto addEdge = [&](double edge) {
        if (std::isfinite(edge) && edge > low && edge < high)
            edges[edge_count++] = edge;
    };
    const double first_solid_at_melt =
        first_material.solid_heat_capacity_j_kg_k * first_material.melting_temperature_k;
    const double first_liquid_at_melt = first_solid_at_melt + first_material.latent_heat_j_kg;
    const double second_solid_at_melt =
        second_material.solid_heat_capacity_j_kg_k * second_material.melting_temperature_k;
    const double second_liquid_at_melt = second_solid_at_melt + second_material.latent_heat_j_kg;
    addEdge(first.mass_kg * (first_solid_at_melt - first.enthalpy_j_kg));
    addEdge(first.mass_kg * (first_liquid_at_melt - first.enthalpy_j_kg));
    addEdge(second.mass_kg * (second.enthalpy_j_kg - second_solid_at_melt));
    addEdge(second.mass_kg * (second.enthalpy_j_kg - second_liquid_at_melt));
    std::sort(edges.begin(), edges.begin() + static_cast<std::ptrdiff_t>(edge_count));
    edge_count = static_cast<std::size_t>(std::unique(
        edges.begin(), edges.begin() + static_cast<std::ptrdiff_t>(edge_count)) - edges.begin());

    double q = 0.0;
    bool found = false;
    for (std::size_t i = 0; i + 1 < edge_count; ++i) {
        const double lo = edges[i];
        const double hi = edges[i + 1];
        const auto lo_temperatures = temperatures(lo);
        const auto hi_temperatures = temperatures(hi);
        const int lo_sign = backwardEulerResidualSign(
            lo, scale, lo_temperatures[1] - lo_temperatures[0]);
        const int hi_sign = backwardEulerResidualSign(
            hi, scale, hi_temperatures[1] - hi_temperatures[0]);
        if (lo_sign == 0) {
            q = lo;
            found = true;
            break;
        }
        if (hi_sign == 0) {
            q = hi;
            found = true;
            break;
        }
        if (lo_sign > 0 || hi_sign < 0) continue;

        const double interior = lo * 0.5 + hi * 0.5;
        const double first_enthalpy = first.enthalpy_j_kg + interior / first.mass_kg;
        const double second_enthalpy = second.enthalpy_j_kg - interior / second.mass_kg;
        // Use the point in this segment nearest zero as the affine anchor. Phase
        // slopes come from the interior; temperature itself is continuous at an
        // edge, and the small anchor avoids cancellation for extreme mass ratios.
        const double anchor = std::clamp(0.0, lo, hi);
        const auto anchor_temperatures = temperatures(anchor);
        const double temperature_drop_per_joule =
            temperatureSlopeUnchecked(first_material, first_enthalpy) / first.mass_kg +
            temperatureSlopeUnchecked(second_material, second_enthalpy) / second.mass_kg;
        q = std::clamp(affineBackwardEulerRoot(anchor,
                           anchor_temperatures[1] - anchor_temperatures[0],
                           temperature_drop_per_joule, scale),
                       lo, hi);
        found = true;
        break;
    }
    if (!found) throw std::runtime_error("backward-Euler phase solve failed to bracket a root");
    result.first.enthalpy_j_kg += q / first.mass_kg;
    result.second.enthalpy_j_kg -= q / second.mass_kg;
    result.energy_to_first_j = q;
    validateEnthalpyLump(result.first); validateEnthalpyLump(result.second);
    return result;
}
} // namespace banjo::thermal
