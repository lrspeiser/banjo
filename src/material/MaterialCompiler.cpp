#include "material/MaterialCompiler.hpp"

#include <algorithm>
#include <stdexcept>

namespace banjo {

CompiledBrittleMaterial compileBrittleMaterial(
    const MaterialDefinition &material,
    double voxel_size_m,
    unsigned neighbor_horizon_cells) {
    if (material.model != MaterialModel::BrittleBond) {
        throw std::invalid_argument("compileBrittleMaterial requires a brittle-bond material");
    }
    if (material.density_kg_m3 <= 0.0 || material.young_modulus_pa <= 0.0 ||
        material.tensile_strength_pa <= 0.0 || material.fracture_energy_j_m2 <= 0.0 ||
        voxel_size_m <= 0.0 || neighbor_horizon_cells == 0U) {
        throw std::invalid_argument("material and lattice parameters must be positive");
    }

    const double representative_area_m2 = voxel_size_m * voxel_size_m;
    const double representative_length_m = voxel_size_m * static_cast<double>(neighbor_horizon_cells);
    const double spring_stiffness_n_m =
        material.young_modulus_pa * representative_area_m2 / representative_length_m;
    const double physical_failure_strain = material.tensile_strength_pa / material.young_modulus_pa;

    CompiledBrittleMaterial compiled;
    compiled.density_kg_m3 = material.density_kg_m3;
    compiled.bond_compliance = 1.0 / spring_stiffness_n_m;
    compiled.damage_start_stretch = std::max(
        1.0e-5, physical_failure_strain * material.calibration.damage_strain_multiplier);
    compiled.damage_end_stretch = std::max(
        compiled.damage_start_stretch * 1.01,
        physical_failure_strain * material.calibration.break_strain_multiplier);
    compiled.bond_damping = std::clamp(material.damping_ratio, 0.0, 1.0);
    compiled.fracture_energy_j_m2 = material.fracture_energy_j_m2;
    compiled.activation_energy_scale = std::max(0.0, material.calibration.activation_energy_scale);
    compiled.strength_variation = std::clamp(material.strength_variation, 0.0, 0.95);
    compiled.seed = material.seed;
    return compiled;
}

} // namespace banjo
