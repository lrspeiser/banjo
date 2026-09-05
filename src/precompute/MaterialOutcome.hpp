#pragma once

#include "core/Math.hpp"
#include "fracture/ActiveMatter.hpp"
#include "material/MaterialCatalog.hpp"

#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <vector>

namespace banjo {

inline constexpr std::uint32_t kMaterialOutcomeFormatVersion = 2U;
inline constexpr std::uint32_t kMaterialSolverModelVersion = 4U;

struct MaterialOutcomeKeyInput {
    MaterialPreset striker{MaterialPreset::Iron};
    MaterialPreset target{MaterialPreset::Glass};
    MaterialPreset surface{MaterialPreset::Concrete};

    double radius_m{0.25};
    double voxel_size_m{0.04};
    double striker_speed_m_s{8.0};
    double target_speed_m_s{};
    double slope_degrees{};
    Vec3 gravity_world_m_s2{0.0, -9.81, 0.0};

    unsigned neighbor_horizon_cells{2};
    unsigned occupancy_samples_per_axis{3};
    unsigned solver_substeps{2};
    unsigned constraint_iterations{8};
    unsigned minimum_material_steps{180};
    unsigned stable_material_steps{60};
    unsigned maximum_material_steps{480};

    double impact_internal_energy_fraction{0.12};
    double maximum_internal_energy_j{1200.0};
    std::uint64_t material_seed{971};
};

struct MaterialOutcomeKey {
    std::uint32_t format_version{kMaterialOutcomeFormatVersion};
    std::uint32_t solver_model_version{kMaterialSolverModelVersion};
    MaterialPreset striker{MaterialPreset::Iron};
    MaterialPreset target{MaterialPreset::Glass};
    MaterialPreset surface{MaterialPreset::Concrete};

    std::int32_t radius_micrometers{};
    std::int32_t voxel_micrometers{};
    std::int32_t striker_speed_millimeters_per_second{};
    std::int32_t target_speed_millimeters_per_second{};
    std::int32_t slope_millidegrees{};
    std::int32_t gravity_x_millimeters_per_second2{};
    std::int32_t gravity_y_millimeters_per_second2{};
    std::int32_t gravity_z_millimeters_per_second2{};

    std::uint32_t neighbor_horizon_cells{};
    std::uint32_t occupancy_samples_per_axis{};
    std::uint32_t solver_substeps{};
    std::uint32_t constraint_iterations{};
    std::uint32_t minimum_material_steps{};
    std::uint32_t stable_material_steps{};
    std::uint32_t maximum_material_steps{};

    std::int32_t impact_internal_energy_parts_per_million{};
    std::int64_t maximum_internal_energy_millijoules{};
    std::uint64_t material_seed{};

    [[nodiscard]] bool operator==(const MaterialOutcomeKey &) const = default;
};

struct CachedMaterialNode {
    Vec3 position_from_activation_com_local_m{};
    Vec3 velocity_minus_activation_linear_local_m_s{};
    Vec3 spin_angular_velocity_local_rad_s{};
};

struct CachedMaterialBond {
    double damage{};
    BondFailureMode failure_mode{BondFailureMode::None};
    bool alive{true};
};

struct MaterialOutcome {
    MaterialOutcomeKey key{};
    std::uint64_t material_steps{};
    double represented_mass_kg{};
    std::vector<CachedMaterialNode> nodes;
    std::vector<CachedMaterialBond> bonds;
};

[[nodiscard]] MaterialOutcomeKey makeMaterialOutcomeKey(
    const MaterialOutcomeKeyInput &input);
[[nodiscard]] std::uint64_t materialOutcomeFingerprint(
    const MaterialOutcomeKey &key);

[[nodiscard]] MaterialOutcome captureMaterialOutcome(
    const MaterialOutcomeKey &key,
    const ActiveMatter &matter,
    const RigidSnapshot &activation_rigid,
    std::uint64_t material_steps);

void applyMaterialOutcome(
    const MaterialOutcome &outcome,
    const RigidSnapshot &activation_rigid,
    ActiveMatter &matter);

void saveMaterialOutcome(
    const MaterialOutcome &outcome,
    const std::filesystem::path &path);
[[nodiscard]] MaterialOutcome loadMaterialOutcome(
    const std::filesystem::path &path);

} // namespace banjo
