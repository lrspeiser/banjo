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

    // Bulk mechanical response at the declared reference state.
    double density_kg_m3{};
    double young_modulus_pa{};
    double poisson_ratio{};
    double yield_strength_pa{};
    double tensile_strength_pa{};
    double compressive_strength_pa{};
    double shear_strength_pa{};
    double hardness_pa{};
    double fracture_energy_j_m2{};

    // Surface/contact response. `friction` remains the legacy fallback for
    // existing content; new content should author static and dynamic values.
    double friction{0.5};
    double static_friction{-1.0};
    double dynamic_friction{-1.0};
    double rolling_resistance{};
    double restitution{};
    double contact_damping_ratio{0.05};
    bool derive_restitution_from_damping{};

    // Internal material dissipation and directional structure.
    double damping_ratio{0.01};
    double anisotropy_ratio{1.0};
    double reference_temperature_k{293.15};

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

struct CompiledContactMaterial {
    double static_friction{};
    double dynamic_friction{};
    double rolling_resistance{};
    double restitution{};
    double contact_damping_ratio{};
    double young_modulus_pa{};
    double poisson_ratio{};
};

struct CombinedContactMaterial {
    double static_friction{};
    double dynamic_friction{};
    double rolling_resistance{};
    double restitution{};
    double contact_damping_ratio{};
    double effective_modulus_pa{};
};

} // namespace banjo
