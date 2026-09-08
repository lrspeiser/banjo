#include "material/MaterialCompiler.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <numbers>
#include <stdexcept>
#include <string>

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

[[nodiscard]] double compiledFailureStrain(
    double physical_failure_strain,
    double multiplier,
    double minimum = 1.0e-5) {
    if (physical_failure_strain <= 0.0) {
        return std::numeric_limits<double>::infinity();
    }
    return std::max(minimum, physical_failure_strain * multiplier);
}

} // namespace

CompiledBrittleMaterial compileElasticLatticeReference(
    const MaterialDefinition &material, double voxel_size_m, unsigned neighbor_horizon_cells) {
    validateElasticProperties(material);
    if (!std::isfinite(material.density_kg_m3) || !std::isfinite(material.young_modulus_pa) ||
        !std::isfinite(material.poisson_ratio) || !std::isfinite(voxel_size_m) || voxel_size_m <= 0 ||
        neighbor_horizon_cells == 0) throw std::invalid_argument("invalid elastic reference parameters");
    CompiledBrittleMaterial compiled;
    compiled.density_kg_m3 = material.density_kg_m3;
    compiled.poisson_ratio = material.poisson_ratio;
    const double area = voxel_size_m*voxel_size_m;
    const double length = voxel_size_m*static_cast<double>(neighbor_horizon_cells);
    compiled.bond_compliance = 1.0/(material.young_modulus_pa*area/length);
    const double disabled = std::numeric_limits<double>::infinity();
    compiled.damage_start_stretch = compiled.damage_end_stretch = disabled;
    compiled.compression_damage_start_strain = compiled.compression_damage_end_strain = disabled;
    compiled.shear_damage_start_strain = compiled.shear_damage_end_strain = disabled;
    compiled.bond_damping = 0;
    compiled.strength_variation = 0;
    compiled.seed = material.seed;
    return compiled;
}

CompiledBrittleMaterial withStrengthDerivedFailure(
    CompiledBrittleMaterial compiled, const MaterialDefinition &material) {
    if (!std::isfinite(material.young_modulus_pa) || material.young_modulus_pa <= 0.0 ||
        !std::isfinite(material.poisson_ratio) || material.poisson_ratio <= -1.0)
        throw std::invalid_argument("strength-derived failure needs a valid elastic material");
    const double physical_tensile_strain =
        material.tensile_strength_pa / material.young_modulus_pa;
    const double physical_compressive_strain =
        material.compressive_strength_pa > 0.0
            ? material.compressive_strength_pa / material.young_modulus_pa
            : 0.0;
    const double shear_modulus_pa =
        material.young_modulus_pa / (2.0 * (1.0 + material.poisson_ratio));
    const double physical_shear_strain = material.shear_strength_pa > 0.0
                                             ? material.shear_strength_pa /
                                                   shear_modulus_pa
                                             : 0.0;
    compiled.damage_start_stretch = compiledFailureStrain(
        physical_tensile_strain,
        material.calibration.damage_strain_multiplier);
    compiled.damage_end_stretch = std::max(
        compiled.damage_start_stretch * 1.01,
        compiledFailureStrain(
            physical_tensile_strain,
            material.calibration.break_strain_multiplier));
    compiled.compression_damage_start_strain = compiledFailureStrain(
        physical_compressive_strain,
        material.calibration.damage_strain_multiplier);
    compiled.compression_damage_end_strain = std::max(
        compiled.compression_damage_start_strain * 1.01,
        compiledFailureStrain(
            physical_compressive_strain,
            material.calibration.break_strain_multiplier));
    compiled.shear_damage_start_strain = compiledFailureStrain(
        physical_shear_strain,
        material.calibration.damage_strain_multiplier);
    compiled.shear_damage_end_strain = std::max(
        compiled.shear_damage_start_strain * 1.01,
        compiledFailureStrain(
            physical_shear_strain,
            material.calibration.break_strain_multiplier));
    return compiled;
}

CompiledBrittleMaterial withPlasticFlow(
    CompiledBrittleMaterial compiled, const MaterialDefinition &material) {
    if (!std::isfinite(material.young_modulus_pa) || material.young_modulus_pa <= 0.0)
        throw std::invalid_argument("plastic flow needs a valid elastic material");
    if (!std::isfinite(material.yield_strength_pa) || material.yield_strength_pa < 0.0 ||
        !std::isfinite(material.hardening_ratio) || material.hardening_ratio < 0.0)
        throw std::invalid_argument("yield strength and hardening ratio must be finite and non-negative");
    if (material.yield_strength_pa <= 0.0) {
        compiled.yield_stretch = 0.0;
        compiled.plastic_hardening_ratio = 0.0;
        return compiled;
    }
    compiled.yield_stretch = material.yield_strength_pa / material.young_modulus_pa;
    compiled.plastic_hardening_ratio = material.hardening_ratio;
    return compiled;
}

LatticeHorizonGeometry latticeHorizonGeometry(unsigned neighbor_horizon_cells) {
    if (neighbor_horizon_cells == 0U) {
        throw std::invalid_argument("lattice horizon must be at least one cell");
    }
    // The same offset walk as matter/Lattice.cpp buildBonds: integer offsets
    // within the grid distance, one member of each +/- pair.
    const auto positiveHalf = [](int dx, int dy, int dz) {
        return dz > 0 || (dz == 0 && dy > 0) || (dz == 0 && dy == 0 && dx > 0);
    };
    LatticeHorizonGeometry g;
    g.horizon = neighbor_horizon_cells;
    const int m = static_cast<int>(neighbor_horizon_cells);
    const double inv_sqrt2 = 1.0 / std::sqrt(2.0);
    const double inv_sqrt3 = 1.0 / std::sqrt(3.0);
    for (int dz = -m; dz <= m; ++dz) {
        for (int dy = -m; dy <= m; ++dy) {
            for (int dx = -m; dx <= m; ++dx) {
                if (!positiveHalf(dx, dy, dz)) continue;
                const double d2 = static_cast<double>(dx * dx + dy * dy + dz * dz);
                if (std::sqrt(d2) > static_cast<double>(m) + 1.0e-9) continue;
                ++g.bonds_per_node;
                g.crossings_100 += std::abs(static_cast<double>(dx));
                g.crossings_110 += std::abs(static_cast<double>(dx + dy)) * inv_sqrt2;
                g.crossings_111 += std::abs(static_cast<double>(dx + dy + dz)) * inv_sqrt3;
                const double nx2 = static_cast<double>(dx * dx) / d2;
                const double ny2 = static_cast<double>(dy * dy) / d2;
                g.sum_nx4 += nx2 * nx2;
                g.sum_nx2ny2 += nx2 * ny2;
            }
        }
    }
    return g;
}

double energyScaledCriticalStretch(
    double fracture_energy_j_m2,
    double young_modulus_pa,
    double voxel_size_m,
    unsigned neighbor_horizon_cells) {
    if (!std::isfinite(fracture_energy_j_m2) || fracture_energy_j_m2 <= 0.0 ||
        !std::isfinite(young_modulus_pa) || young_modulus_pa <= 0.0 ||
        !std::isfinite(voxel_size_m) || voxel_size_m <= 0.0 || neighbor_horizon_cells == 0U) {
        throw std::invalid_argument(
            "energy-scaled failure needs positive Gc, modulus, cell size and horizon");
    }
    const LatticeHorizonGeometry g = latticeHorizonGeometry(neighbor_horizon_cells);
    // Per-bond energy at stretch s: E h^3 s^2 / (2 m). Crossings per unit
    // {100} area: N_100 / h^2. Energy per unit area: N_100 E h s^2 / (2 m).
    return std::sqrt(2.0 * static_cast<double>(neighbor_horizon_cells) * fracture_energy_j_m2 /
                     (g.crossings_100 * young_modulus_pa * voxel_size_m));
}

CompiledBrittleMaterial withEnergyScaledFailure(
    CompiledBrittleMaterial compiled,
    const MaterialDefinition &material,
    double voxel_size_m,
    unsigned neighbor_horizon_cells) {
    // Start from the strength surface: its compressive and shear ramps are
    // kept, and its tensile removal stretch is the bound the energy-scaled
    // stretch may not exceed.
    compiled = withStrengthDerivedFailure(compiled, material);
    const double strength_end = compiled.damage_end_stretch;
    const double energy_stretch = energyScaledCriticalStretch(
        material.fracture_energy_j_m2, material.young_modulus_pa, voxel_size_m, neighbor_horizon_cells);
    // The same floor compiledFailureStrain applies to the strength law, so a
    // threshold can never sit inside the criterion's rounding noise. Where the
    // floor bites, the Gc calibration is broken by it: the removal stretch is
    // then larger than the derivation asks for and the crack costs more than
    // Gc. That is visible rather than silent - TileImpactScene reports both
    // energy_scaled_stretch and lattice_crack_energy_j_m2, so a floored run
    // shows a crack energy above the material's Gc - and no catalogue material
    // reaches it at 20, 10 or 5 mm cells with horizon 2 or 3 (the smallest is
    // ceramic at 20 mm, horizon 3: 1.89e-5, about twice the floor).
    const double bounded_end = std::max(1.0e-5, std::min(energy_stretch, strength_end));
    const double break_multiplier = material.calibration.break_strain_multiplier;
    const double damage_multiplier = material.calibration.damage_strain_multiplier;
    const double start_fraction =
        (std::isfinite(break_multiplier) && break_multiplier > 0.0 && std::isfinite(damage_multiplier) &&
         damage_multiplier > 0.0)
            ? std::clamp(damage_multiplier / break_multiplier, 0.0, 1.0)
            : 0.5;
    compiled.damage_start_stretch = std::max(1.0e-5, bounded_end * start_fraction);
    compiled.damage_end_stretch = std::max(compiled.damage_start_stretch * 1.01, bounded_end);
    compiled.failure_law = BondFailureLaw::EnergyScaled;
    compiled.energy_scaled_stretch = energy_stretch;
    compiled.strength_bound_active = strength_end < energy_stretch;
    return compiled;
}

CompiledBrittleMaterial withFailureLaw(
    CompiledBrittleMaterial compiled,
    const MaterialDefinition &material,
    double voxel_size_m,
    unsigned neighbor_horizon_cells) {
    switch (material.failure_law) {
    case BondFailureLaw::StrainThreshold:
        compiled = withStrengthDerivedFailure(compiled, material);
        compiled.failure_law = BondFailureLaw::StrainThreshold;
        compiled.energy_scaled_stretch = 0.0;
        compiled.strength_bound_active = false;
        return compiled;
    case BondFailureLaw::EnergyScaled:
        return withEnergyScaledFailure(compiled, material, voxel_size_m, neighbor_horizon_cells);
    }
    throw std::invalid_argument("unknown bond failure law");
}

std::string_view bondFailureLawName(BondFailureLaw law) {
    switch (law) {
    case BondFailureLaw::StrainThreshold:
        return "strain-threshold";
    case BondFailureLaw::EnergyScaled:
        return "energy-scaled";
    }
    return "unknown";
}

BondFailureLaw parseBondFailureLaw(std::string_view name) {
    if (name == "strain-threshold") return BondFailureLaw::StrainThreshold;
    if (name == "energy-scaled") return BondFailureLaw::EnergyScaled;
    throw std::invalid_argument("unknown bond failure law: " + std::string(name) +
                                " (expected strain-threshold or energy-scaled)");
}

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

    CompiledBrittleMaterial compiled;
    compiled.density_kg_m3 = material.density_kg_m3;
    compiled.poisson_ratio = material.poisson_ratio;
    compiled.bond_compliance = 1.0 / spring_stiffness_n_m;
    compiled = withFailureLaw(compiled, material, voxel_size_m, neighbor_horizon_cells);
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

double dampingRatioFromCoefficientOfRestitution(double restitution) {
    const double bounded = std::clamp(restitution, 0.0, 1.0);
    if (bounded >= 1.0) {
        return 0.0;
    }
    if (bounded <= 1.0e-12) {
        return 0.999999;
    }
    const double logarithm = std::log(bounded);
    return std::clamp(
        -logarithm /
            std::sqrt(std::numbers::pi * std::numbers::pi + logarithm * logarithm),
        0.0,
        0.999999);
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
