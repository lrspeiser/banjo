#pragma once

#include "core/Math.hpp"
#include "material/Material.hpp"

#include <cstddef>
#include <cstdint>
#include <string_view>

namespace banjo {

enum class PredictedFailureMode : std::uint8_t {
    None,
    Elastic,
    SurfaceDamage,
    Yielding,
    BrittleCrack,
    Fragmentation,
};

enum class InclineMotionRegime : std::uint8_t {
    AtRest,
    RollingWithoutSlip,
    Sliding,
    Detached,
};

enum class RuntimeStrategy : std::uint8_t {
    RigidRealtime,
    MaterialRealtime,
    HybridAdaptive,
    PrecomputeRecommended,
    CachedMaterial,
};

[[nodiscard]] std::string_view predictedFailureModeName(PredictedFailureMode mode);
[[nodiscard]] std::string_view inclineMotionRegimeName(InclineMotionRegime regime);
[[nodiscard]] std::string_view runtimeStrategyName(RuntimeStrategy strategy);

struct BallScenarioInput {
    MaterialDefinition striker_material{};
    MaterialDefinition target_material{};
    MaterialDefinition surface_material{};

    double striker_radius_m{0.25};
    double target_radius_m{0.25};
    double striker_speed_m_s{8.0};
    double target_speed_m_s{};
    double slope_angle_degrees{};
    Vec3 gravity_world_m_s2{0.0, -9.81, 0.0};
    double sphere_inertia_factor{0.4};

    double voxel_size_m{0.04};
    std::size_t estimated_active_nodes{};
    std::size_t estimated_bonds{};
    unsigned material_substeps{2};
    unsigned constraint_iterations{8};
    unsigned estimated_material_steps{240};
    std::uint64_t realtime_constraint_budget{50'000'000ULL};
    bool cached_material_outcome_available{};
};

struct ImpactProjection {
    double striker_mass_kg{};
    double target_mass_kg{};
    double reduced_mass_kg{};
    double reduced_radius_m{};
    double relative_normal_speed_m_s{};
    double available_energy_j{};

    double effective_modulus_pa{};
    double maximum_indent_m{};
    double peak_force_n{};
    double contact_radius_m{};
    double peak_contact_pressure_pa{};

    double combined_static_friction{};
    double combined_dynamic_friction{};
    double combined_restitution{};
    double combined_rolling_resistance{};

    double fracture_energy_threshold_j{};
    double fracture_energy_ratio{};
    double tensile_stress_ratio{};
    double compressive_stress_ratio{};
    double yield_stress_ratio{};

    double striker_post_speed_m_s{};
    double target_post_speed_m_s{};
    PredictedFailureMode predicted_failure{PredictedFailureMode::None};
};

struct InclineProjection {
    double slope_angle_degrees{};
    double gravity_tangent_m_s2{};
    double gravity_normal_m_s2{};
    double gravity_outward_m_s2{};
    double required_static_friction{};
    double available_static_friction{};
    double available_dynamic_friction{};
    double rolling_resistance{};
    double acceleration_along_slope_m_s2{};
    double no_slip_angle_limit_degrees{};
    InclineMotionRegime regime{InclineMotionRegime::AtRest};
};

struct ScenarioProjection {
    ImpactProjection impact{};
    InclineProjection incline{};
    std::uint64_t estimated_constraint_solves{};
    RuntimeStrategy runtime_strategy{RuntimeStrategy::RigidRealtime};
};

[[nodiscard]] ScenarioProjection projectBallScenario(const BallScenarioInput &input);

} // namespace banjo
