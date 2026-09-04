#pragma once

#include <cstdint>
#include <string>

namespace banjo {

enum class MaterialModel : std::uint8_t {
    RigidOnly,
    BrittleBond,
};

struct SolverCalibration {
    double activation_energy_scale{1.0};
    double damage_strain_multiplier{1.0};
    double break_strain_multiplier{2.0};
};

struct MaterialDefinition {
    std::string name;
    MaterialModel model{MaterialModel::RigidOnly};

    double density_kg_m3{};
    double young_modulus_pa{};
    double poisson_ratio{};
    double tensile_strength_pa{};
    double fracture_energy_j_m2{};

    double friction{0.5};
    double restitution{0.0};
    double damping_ratio{0.01};

    double strength_variation{};
    std::uint64_t seed{};
    SolverCalibration calibration{};
};

struct CompiledBrittleMaterial {
    double density_kg_m3{};
    double bond_compliance{};
    double damage_start_stretch{};
    double damage_end_stretch{};
    double bond_damping{};
    double fracture_energy_j_m2{};
    double activation_energy_scale{1.0};
    double strength_variation{};
    std::uint64_t seed{};
};

} // namespace banjo
