#include "material/MaterialCatalog.hpp"

#include <cstddef>
#include <stdexcept>
#include <string>

namespace banjo {
namespace {

MaterialDefinition baseMaterial(
    std::string_view name,
    MaterialModel model,
    double density_kg_m3,
    double young_modulus_pa,
    double poisson_ratio) {
    MaterialDefinition material;
    material.name = std::string(name);
    material.model = model;
    material.density_kg_m3 = density_kg_m3;
    material.young_modulus_pa = young_modulus_pa;
    material.poisson_ratio = poisson_ratio;
    return material;
}

void setContact(
    MaterialDefinition &material,
    double static_friction,
    double dynamic_friction,
    double rolling_resistance,
    double contact_damping_ratio) {
    material.static_friction = static_friction;
    material.dynamic_friction = dynamic_friction;
    material.friction = dynamic_friction;
    material.rolling_resistance = rolling_resistance;
    material.contact_damping_ratio = contact_damping_ratio;
    material.derive_restitution_from_damping = true;
}

} // namespace

std::string_view materialPresetName(MaterialPreset preset) {
    switch (preset) {
    case MaterialPreset::Iron:
        return "iron";
    case MaterialPreset::Aluminum:
        return "aluminum";
    case MaterialPreset::Glass:
        return "glass";
    case MaterialPreset::Ceramic:
        return "alumina ceramic";
    case MaterialPreset::Oak:
        return "oak";
    case MaterialPreset::Rubber:
        return "rubber";
    case MaterialPreset::Ice:
        return "ice";
    case MaterialPreset::Concrete:
        return "concrete";
    }
    return "unknown";
}

MaterialDefinition makeReferenceMaterial(MaterialPreset preset, std::uint64_t seed) {
    MaterialDefinition material;
    switch (preset) {
    case MaterialPreset::Iron:
        material = baseMaterial("iron", MaterialModel::RigidOnly, 7870.0, 211.0e9, 0.29);
        material.yield_strength_pa = 200.0e6;
        material.tensile_strength_pa = 250.0e6;
        material.compressive_strength_pa = 600.0e6;
        material.shear_strength_pa = 170.0e6;
        material.hardness_pa = 1.5e9;
        material.fracture_energy_j_m2 = 100000.0;
        material.damping_ratio = 0.015;
        setContact(material, 0.60, 0.45, 0.002, 0.18);
        break;
    case MaterialPreset::Aluminum:
        material = baseMaterial(
            "aluminum_6061_t6", MaterialModel::RigidOnly, 2700.0, 68.9e9, 0.33);
        material.yield_strength_pa = 276.0e6;
        material.tensile_strength_pa = 310.0e6;
        material.compressive_strength_pa = 250.0e6;
        material.shear_strength_pa = 207.0e6;
        material.hardness_pa = 950.0e6;
        material.fracture_energy_j_m2 = 25000.0;
        material.damping_ratio = 0.02;
        setContact(material, 0.61, 0.47, 0.003, 0.16);
        break;
    case MaterialPreset::Glass:
        material = baseMaterial(
            "soda_lime_glass", MaterialModel::BrittleBond, 2500.0, 70.0e9, 0.22);
        material.tensile_strength_pa = 45.0e6;
        material.compressive_strength_pa = 1000.0e6;
        material.shear_strength_pa = 35.0e6;
        material.hardness_pa = 5.5e9;
        material.fracture_energy_j_m2 = 8.0;
        material.damping_ratio = 0.015;
        material.strength_variation = 0.12;
        material.calibration.activation_energy_scale = 1.0;
        // Failure follows the declared 45 MPa tensile / 35 MPa shear strengths
        // through the shared SolverCalibration defaults. The previous 8x/16x
        // strain multipliers put bond failure at 360-720 MPa, so a resolved
        // impact that exceeds glass strength five-fold produced no damage at
        // all; the fragmentation seen in earlier runs came from the unbounded
        // support projection instead. This is a strength-based lattice
        // criterion, not a Gc-calibrated one, and remains uncalibrated against
        // laboratory glass data.
        material.calibration.damage_strain_multiplier = 1.0;
        material.calibration.break_strain_multiplier = 2.0;
        setContact(material, 0.45, 0.35, 0.001, 0.08);
        break;
    case MaterialPreset::Ceramic:
        material = baseMaterial(
            "alumina_ceramic", MaterialModel::BrittleBond, 3900.0, 300.0e9, 0.22);
        material.tensile_strength_pa = 300.0e6;
        material.compressive_strength_pa = 2200.0e6;
        material.shear_strength_pa = 240.0e6;
        material.hardness_pa = 15.0e9;
        material.fracture_energy_j_m2 = 25.0;
        material.damping_ratio = 0.01;
        material.strength_variation = 0.08;
        material.calibration.activation_energy_scale = 2.0;
        material.calibration.damage_strain_multiplier = 6.0;
        material.calibration.break_strain_multiplier = 12.0;
        setContact(material, 0.50, 0.38, 0.001, 0.06);
        break;
    case MaterialPreset::Oak:
        material = baseMaterial("oak", MaterialModel::RigidOnly, 700.0, 12.0e9, 0.35);
        material.yield_strength_pa = 45.0e6;
        material.tensile_strength_pa = 90.0e6;
        material.compressive_strength_pa = 52.0e6;
        material.shear_strength_pa = 11.0e6;
        material.hardness_pa = 35.0e6;
        material.fracture_energy_j_m2 = 1000.0;
        material.damping_ratio = 0.04;
        material.anisotropy_ratio = 8.0;
        setContact(material, 0.62, 0.42, 0.010, 0.24);
        break;
    case MaterialPreset::Rubber:
        material = baseMaterial(
            "natural_rubber", MaterialModel::RigidOnly, 1100.0, 10.0e6, 0.49);
        material.yield_strength_pa = 6.0e6;
        material.tensile_strength_pa = 20.0e6;
        material.compressive_strength_pa = 15.0e6;
        material.shear_strength_pa = 3.5e6;
        material.hardness_pa = 6.0e6;
        material.fracture_energy_j_m2 = 5000.0;
        material.damping_ratio = 0.18;
        setContact(material, 1.00, 0.80, 0.025, 0.05);
        break;
    case MaterialPreset::Ice:
        material = baseMaterial("freshwater_ice", MaterialModel::BrittleBond, 917.0, 9.0e9, 0.33);
        material.tensile_strength_pa = 1.0e6;
        material.compressive_strength_pa = 5.0e6;
        material.shear_strength_pa = 1.0e6;
        material.hardness_pa = 10.0e6;
        material.fracture_energy_j_m2 = 1.5;
        material.damping_ratio = 0.025;
        material.strength_variation = 0.18;
        material.calibration.activation_energy_scale = 1.5;
        material.calibration.damage_strain_multiplier = 5.0;
        material.calibration.break_strain_multiplier = 10.0;
        setContact(material, 0.10, 0.03, 0.001, 0.12);
        break;
    case MaterialPreset::Concrete:
        material = baseMaterial("concrete", MaterialModel::RigidOnly, 2400.0, 30.0e9, 0.20);
        material.tensile_strength_pa = 3.0e6;
        material.compressive_strength_pa = 35.0e6;
        material.shear_strength_pa = 5.0e6;
        material.hardness_pa = 100.0e6;
        material.fracture_energy_j_m2 = 100.0;
        material.damping_ratio = 0.04;
        setContact(material, 0.75, 0.62, 0.015, 0.30);
        break;
    }
    material.seed = seed;
    return material;
}

MaterialPreset materialPresetFromOrdinal(unsigned ordinal) {
    if (ordinal >= kMaterialPresets.size()) {
        throw std::out_of_range("material preset ordinal is invalid");
    }
    return kMaterialPresets[ordinal];
}

MaterialPreset nextMaterialPreset(MaterialPreset preset) {
    for (std::size_t index = 0; index < kMaterialPresets.size(); ++index) {
        if (kMaterialPresets[index] == preset) {
            return kMaterialPresets[(index + 1U) % kMaterialPresets.size()];
        }
    }
    throw std::invalid_argument("unknown material preset");
}

} // namespace banjo
