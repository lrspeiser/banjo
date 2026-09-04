#include "material/MaterialCompiler.hpp"

#include <algorithm>
#include <cmath>
#include <numbers>
#include <stdexcept>

namespace banjo {
namespace {

void validateElasticProperties(const MaterialDefinition &material) {
    if (material.density_kg_m3 <= 0.0 || material.young_modulus_pa <= 0.0 ||
        material.poisson_ratio <= -1.0 || material.poisson_ratio >= 0.5) {
        throw std::invalid_argument(
            "material requires positive density/modulus and -1 < Poisson ratio < 0.5");
    }
}

[[nodiscard]] double resolvedDynamicFriction(const MaterialDefinition &material) {
    return std::max(
        0.0,
        material.dynamic_friction >= 0.0 ? material.dynamic_friction : material.friction);
}

[[nodiscard]] double elasticCompliance(const CompiledContactMaterial &material) {
    return (1.0 - material.poisson_ratio * material.poisson_ratio) /
           material.young_modulus_pa;
}

} // namespace

CompiledBrittleMaterial compileBrittleMaterial(
    const MaterialDefinition &material,
    double voxel_size_m,
    unsigned neighbor_horizon_cells) {
    if (material.model != MaterialModel::BrittleBond) {
        throw std::invalid_argument("compileBrittleMaterial requires a brittle-bond material");
    }
    validateElasticProperties(material);
    if (material.tensile_strength_pa <= 0.0 || material.fracture_energy_j_m2 <= 0.0 ||
        voxel_size_m <= 0.0 || neighbor_horizon_cells == 0U) {
        throw std::invalid_argument("brittle material and lattice parameters must be positive");
    }

    const double representative_area_m2 = voxel_size_m * voxel_size_m;
    const double representative_length_m =
        voxel_size_m * static_cast<double>(neighbor_horizon_cells);
    const double spring_stiffness_n_m =
        material.young_modulus_pa * representative_area_m2 / representative_length_m;
    const double physical_failure_strain =
        material.tensile_strength_pa / material.young_modulus_pa;

    CompiledBrittleMaterial compiled;
    compiled.density_kg_m3 = material.density_kg_m3;
    compiled.bond_compliance = 1.0 / spring_stiffness_n_m;
    compiled.damage_start_stretch = std::max(
        1.0e-5,
        physical_failure_strain * material.calibration.damage_strain_multiplier);
    compiled.damage_end_stretch = std::max(
        compiled.damage_start_stretch * 1.01,
        physical_failure_strain * material.calibration.break_strain_multiplier);
    compiled.bond_damping = std::clamp(material.damping_ratio, 0.0, 1.0);
    compiled.fracture_energy_j_m2 = material.fracture_energy_j_m2;
    compiled.activation_energy_scale =
        std::max(0.0, material.calibration.activation_energy_scale);
    compiled.strength_variation =
        std::clamp(material.strength_variation, 0.0, 0.95);
    compiled.seed = material.seed;
    return compiled;
}

double coefficientOfRestitutionFromDamping(double damping_ratio) {
    const double damping = std::clamp(damping_ratio, 0.0, 0.999999);
    if (damping <= 0.0) {
        return 1.0;
    }
    const double denominator = std::sqrt(std::max(1.0e-12, 1.0 - damping * damping));
    return std::clamp(
        std::exp(-std::numbers::pi * damping / denominator),
        0.0,
        1.0);
}

CompiledContactMaterial compileContactMaterial(const MaterialDefinition &material) {
    validateElasticProperties(material);

    CompiledContactMaterial compiled;
    compiled.dynamic_friction = resolvedDynamicFriction(material);
    compiled.static_friction = std::max(
        compiled.dynamic_friction,
        material.static_friction >= 0.0
            ? material.static_friction
            : compiled.dynamic_friction);
    compiled.rolling_resistance = std::clamp(material.rolling_resistance, 0.0, 1.0);
    compiled.contact_damping_ratio =
        std::clamp(material.contact_damping_ratio, 0.0, 0.999999);
    compiled.restitution = material.derive_restitution_from_damping
                               ? coefficientOfRestitutionFromDamping(
                                     compiled.contact_damping_ratio)
                               : std::clamp(material.restitution, 0.0, 1.0);
    compiled.young_modulus_pa = material.young_modulus_pa;
    compiled.poisson_ratio = material.poisson_ratio;
    return compiled;
}

CombinedContactMaterial combineContactMaterials(
    const CompiledContactMaterial &first,
    const CompiledContactMaterial &second) {
    const double compliance_first = elasticCompliance(first);
    const double compliance_second = elasticCompliance(second);
    const double total_compliance = compliance_first + compliance_second;
    if (total_compliance <= 0.0) {
        throw std::invalid_argument("combined contact compliance must be positive");
    }

    CombinedContactMaterial combined;
    combined.static_friction = std::sqrt(
        std::max(0.0, first.static_friction * second.static_friction));
    combined.dynamic_friction = std::sqrt(
        std::max(0.0, first.dynamic_friction * second.dynamic_friction));
    combined.rolling_resistance = std::clamp(
        first.rolling_resistance + second.rolling_resistance,
        0.0,
        1.0);
    combined.contact_damping_ratio = std::clamp(
        (first.contact_damping_ratio * compliance_first +
         second.contact_damping_ratio * compliance_second) /
            total_compliance,
        0.0,
        0.999999);
    combined.restitution =
        coefficientOfRestitutionFromDamping(combined.contact_damping_ratio);
    combined.effective_modulus_pa = 1.0 / total_compliance;
    return combined;
}

} // namespace banjo
