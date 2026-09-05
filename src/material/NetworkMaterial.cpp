#include "material/NetworkMaterial.hpp"

#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace banjo {
namespace {

void finitePositive(double value, const char *what) {
    if (!std::isfinite(value) || value <= 0.0) throw std::invalid_argument(what);
}

double harmonicDirectional(Vec3 values, Vec3 direction, const char *what) {
    const double value = direction.x * direction.x / values.x +
        direction.y * direction.y / values.y + direction.z * direction.z / values.z;
    if (!std::isfinite(value) || value <= 0.0) throw std::invalid_argument(what);
    return 1.0 / value;
}

} // namespace

void validateNetworkMaterial(const NetworkMaterial &material) {
    finitePositive(material.density_kg_m3, "network density must be positive and finite");
    finitePositive(material.young_modulus_pa.x, "network Young modulus must be positive and finite");
    finitePositive(material.young_modulus_pa.y, "network Young modulus must be positive and finite");
    finitePositive(material.young_modulus_pa.z, "network Young modulus must be positive and finite");
    finitePositive(material.tensile_strength_pa.x, "network strength must be positive and finite");
    finitePositive(material.tensile_strength_pa.y, "network strength must be positive and finite");
    finitePositive(material.tensile_strength_pa.z, "network strength must be positive and finite");
    finitePositive(material.fracture_energy_j_m2.x, "network fracture energy must be positive and finite");
    finitePositive(material.fracture_energy_j_m2.y, "network fracture energy must be positive and finite");
    finitePositive(material.fracture_energy_j_m2.z, "network fracture energy must be positive and finite");
    if (!std::isfinite(material.damping_ratio) || material.damping_ratio < 0.0 ||
        !std::isfinite(material.friction) || material.friction < 0.0 ||
        !std::isfinite(material.yield_strength_pa) || material.yield_strength_pa < 0.0 ||
        !std::isfinite(material.hardening_ratio) || material.hardening_ratio != 0.0) {
        throw std::invalid_argument("invalid network damping, friction, yield or hardening");
    }
    if (material.yield_strength_pa > 0.0 && material.fracture_enabled) {
        throw std::invalid_argument("network v2 does not combine plasticity and fracture");
    }
    if (material.failure_law != NetworkFailureLaw::Cohesive && material.failure_law != NetworkFailureLaw::Brittle)
        throw std::invalid_argument("unknown network failure law");
}

DirectionalNetworkParameters directionalNetworkParameters(
    const NetworkMaterial &material, Vec3 direction, double area_m2, double rest_length_m) {
    validateNetworkMaterial(material);
    if (!std::isfinite(lengthSquared(direction)) || std::abs(length(direction) - 1.0) > 1.0e-9) {
        throw std::invalid_argument("network direction must be unit length");
    }
    finitePositive(area_m2, "network area must be positive and finite");
    finitePositive(rest_length_m, "network rest length must be positive and finite");
    const double modulus = harmonicDirectional(material.young_modulus_pa, direction, "invalid directional modulus");
    const double strength = harmonicDirectional(material.tensile_strength_pa, direction, "invalid directional strength");
    const double fracture = harmonicDirectional(material.fracture_energy_j_m2, direction, "invalid directional fracture energy");
    DirectionalNetworkParameters result;
    result.stiffness_n_m = modulus * area_m2 / rest_length_m;
    result.strength_n = strength * area_m2;
    result.fracture_work_j = fracture * area_m2;
    result.area_m2 = area_m2;
    result.rest_length_m = rest_length_m;
    result.yield_force_n = material.yield_strength_pa > 0.0 ? material.yield_strength_pa * area_m2 : 0.0;
    return result;
}

NetworkBondUpdate advanceNetworkBond(
    const NetworkMaterial &material,
    const DirectionalNetworkParameters &parameters,
    const NetworkBondHistory &input,
    double total_extension_m,
    double rest_length_m) {
    validateNetworkMaterial(material);
    finitePositive(parameters.stiffness_n_m, "network stiffness must be positive and finite");
    finitePositive(parameters.strength_n, "network strength force must be positive and finite");
    finitePositive(parameters.fracture_work_j, "network fracture work must be positive and finite");
    finitePositive(parameters.area_m2, "network parameter area must be positive and finite");
    finitePositive(rest_length_m, "network rest length must be positive and finite");
    if (!std::isfinite(parameters.area_m2) || !std::isfinite(parameters.rest_length_m) ||
        std::abs(parameters.rest_length_m - rest_length_m) > 1.0e-12 * std::max(1.0, rest_length_m)) {
        throw std::invalid_argument("network bond geometry does not match parameters");
    }
    if (!std::isfinite(total_extension_m) || input.damage < 0.0 || input.damage > 1.0 ||
        input.maximum_elastic_opening_m < 0.0 || input.fracture_dissipation_j < 0.0 ||
        input.plastic_dissipation_j < 0.0 || !std::isfinite(input.plastic_extension_m) ||
        !std::isfinite(input.maximum_elastic_opening_m) || !std::isfinite(input.damage) ||
        !std::isfinite(input.fracture_dissipation_j) || !std::isfinite(input.plastic_dissipation_j) ||
        !std::isfinite(input.unreleased_energy_j) || input.unreleased_energy_j < 0.0 ||
        !std::isfinite(parameters.yield_force_n) || parameters.yield_force_n < 0.0) {
        throw std::invalid_argument("invalid network bond history or extension");
    }
    const double d0 = parameters.strength_n / parameters.stiffness_n_m;
    const double df = 2.0 * parameters.fracture_work_j / parameters.strength_n;
    if (!std::isfinite(d0) || !std::isfinite(df) ||
        (material.failure_law == NetworkFailureLaw::Cohesive && material.fracture_enabled && df <= d0)) {
        throw std::invalid_argument("network cohesive law requires df greater than d0");
    }

    NetworkBondUpdate result;
    result.history = input;
    // A removed connection never regains compression stiffness; subsequent
    // compression is owned by contact between the separated physical cells.
    if (input.damage >= 1.0 - 1e-12) { result.failed = true; return result; }
    result.stiffness_n_m = parameters.stiffness_n_m;
    double elastic_extension = total_extension_m - result.history.plastic_extension_m;
    if (parameters.yield_force_n > 0.0) {
        const double yield_extension = parameters.yield_force_n / parameters.stiffness_n_m;
        const double magnitude = std::abs(elastic_extension);
        if (magnitude > yield_extension) {
            const double increment = magnitude - yield_extension;
            result.history.plastic_extension_m += std::copysign(increment, elastic_extension);
            result.plastic_increment_j = parameters.yield_force_n * increment;
            result.history.plastic_dissipation_j += result.plastic_increment_j;
            elastic_extension = std::copysign(yield_extension, elastic_extension);
        }
    }
    const double opening = std::max(0.0, elastic_extension);
    const double old_opening = result.history.maximum_elastic_opening_m;
    const double stored_energy = 0.5 * parameters.stiffness_n_m *
        elastic_extension * elastic_extension;
    if (material.failure_law == NetworkFailureLaw::Brittle && material.fracture_enabled &&
        elastic_extension > 0.0 && result.history.damage < 1.0 &&
        elastic_extension >= d0 && stored_energy >= parameters.fracture_work_j) {
        result.history.maximum_elastic_opening_m = std::max(old_opening, elastic_extension);
        result.history.damage = 1.0;
        result.fracture_increment_j = parameters.fracture_work_j;
        result.history.fracture_dissipation_j += result.fracture_increment_j;
        result.unreleased_energy_j = std::max(0.0, stored_energy - parameters.fracture_work_j);
        result.history.unreleased_energy_j += result.unreleased_energy_j;
        result.stiffness_n_m = elastic_extension >= 0.0 ? 0.0 : parameters.stiffness_n_m;
        result.elastic_energy_j = 0.0;
        result.failed = true;
        return result;
    }
    if (material.fracture_enabled && material.failure_law == NetworkFailureLaw::Cohesive &&
        opening > result.history.maximum_elastic_opening_m) {
        result.history.maximum_elastic_opening_m = opening;
        if (opening <= d0) {
            result.history.damage = 0.0;
        } else {
            // Secant damage reproduces the linear softening traction
            // t(kappa)=strength*(df-kappa)/(df-d0).
            result.history.damage = std::clamp(
                1.0 - d0 * (df - opening) / (opening * (df - d0)), 0.0, 1.0);
        }
    }
    if (material.fracture_enabled && material.failure_law == NetworkFailureLaw::Cohesive) {
        result.fracture_increment_j = parameters.fracture_work_j *
            std::clamp((result.history.maximum_elastic_opening_m - d0) /
                           (df - d0), 0.0, 1.0);
        result.fracture_increment_j -= parameters.fracture_work_j *
            std::clamp((old_opening - d0) / (df - d0), 0.0, 1.0);
        result.fracture_increment_j = std::max(0.0, result.fracture_increment_j);
    }
    result.history.fracture_dissipation_j += result.fracture_increment_j;
    const double traction_factor = 1.0 - result.history.damage;
    result.stiffness_n_m = elastic_extension >= 0.0
        ? parameters.stiffness_n_m * traction_factor : parameters.stiffness_n_m;
    result.elastic_energy_j = 0.5 * parameters.stiffness_n_m *
        (elastic_extension * elastic_extension) * (elastic_extension >= 0.0 ? traction_factor : 1.0);
    result.failed = result.history.damage >= 1.0 - 1.0e-12;
    return result;
}

} // namespace banjo
