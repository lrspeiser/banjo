#pragma once

#include "core/Math.hpp"
#include "core/Types.hpp"
#include "fracture/ActivationPolicy.hpp"
#include "fracture/ActiveMatter.hpp"
#include "fracture/BrittleBondSolver.hpp"
#include "fracture/FragmentGeometry.hpp"
#include "fracture/ImpactEvent.hpp"
#include "material/Material.hpp"
#include "matter/Lattice.hpp"
#include "rigid/JoltWorld.hpp"

#include <cstddef>
#include <cstdint>
#include <memory>
#include <optional>
#include <string_view>
#include <vector>

namespace banjo {

enum class ExperimentPhase : std::uint8_t {
    Rigid,
    Fracturing,
    RigidFragments,
};

[[nodiscard]] std::string_view experimentPhaseName(ExperimentPhase phase);

struct ExperimentSettings {
    double radius_m{0.25};
    double voxel_size_m{0.04};
    unsigned neighbor_horizon_cells{2};
    unsigned occupancy_samples_per_axis{3};

    double iron_speed_m_s{8.0};
    Vec3 gravity_m_s2{0.0, -9.81, 0.0};
    std::uint64_t material_seed{971};

    double rigid_step_s{1.0 / 120.0};
    double material_step_s{1.0 / 240.0};
    unsigned minimum_material_steps{180};
    unsigned stable_material_steps_before_handoff{60};
    unsigned maximum_material_steps{480};

    double impact_internal_energy_fraction{0.12};
    double maximum_internal_energy_j{1200.0};

    std::size_t maximum_rigid_fragments{64};
    std::size_t minimum_nodes_per_rigid_fragment{1};
    std::size_t maximum_collision_points{192};
};

struct ExperimentStats {
    ExperimentPhase phase{ExperimentPhase::Rigid};
    std::uint64_t rigid_steps{};
    std::uint64_t material_steps{};

    std::size_t active_nodes{};
    std::size_t total_bonds{};
    std::size_t broken_bonds{};
    std::size_t connected_components{1};
    std::size_t rigid_fragments{};
    std::size_t debris_particles{};

    double represented_glass_mass_kg{};
    double fragment_mass_kg{};
    double mass_error_kg{};

    double impact_speed_m_s{};
    double impact_energy_j{};
    double activation_threshold_j{};
    double normalized_impact_energy{};

    double maximum_tensile_stretch{};
    double active_kinetic_energy_j{};
    double active_elastic_energy_j{};
    double maximum_node_speed_m_s{};
};

struct DebrisParticleState {
    Vec3 position_world_m{};
    Vec3 velocity_m_s{};
    Vec3 angular_velocity_rad_s{};
    double mass_kg{};
    double radius_m{};
};

class RollingBallExperiment {
public:
    explicit RollingBallExperiment(ExperimentSettings settings = {});
    ~RollingBallExperiment();

    RollingBallExperiment(const RollingBallExperiment &) = delete;
    RollingBallExperiment &operator=(const RollingBallExperiment &) = delete;
    RollingBallExperiment(RollingBallExperiment &&) noexcept;
    RollingBallExperiment &operator=(RollingBallExperiment &&) noexcept;

    void reset(ExperimentSettings settings);
    void stepFixed();

    [[nodiscard]] const ExperimentSettings &settings() const { return settings_; }
    [[nodiscard]] const ExperimentStats &stats() const { return stats_; }
    [[nodiscard]] ExperimentPhase phase() const { return stats_.phase; }

    [[nodiscard]] std::optional<RigidSnapshot> rigidSnapshot(MatterBodyId body_id) const;
    [[nodiscard]] const ActiveMatter *activeMatter() const;
    [[nodiscard]] const std::optional<ImpactEvent> &activatingImpact() const {
        return activating_impact_;
    }
    [[nodiscard]] const FragmentBuildResult &fragmentBuild() const { return fragment_build_; }
    [[nodiscard]] const std::vector<DebrisParticleState> &debrisParticles() const {
        return debris_particles_;
    }
    [[nodiscard]] const LatticeAsset &glassLattice() const { return glass_lattice_; }

    static constexpr MatterBodyId kIronBallId = 1;
    static constexpr MatterBodyId kGlassBallId = 2;

private:
    void initializeWorld();
    void stepRigidPhase();
    void stepFracturingPhase();
    void stepRigidFragmentsPhase();
    void finalizeFragments();
    void updateComponentCount();
    void integrateDebris(double dt_s);

    ExperimentSettings settings_{};
    ExperimentStats stats_{};

    MaterialDefinition iron_material_{};
    MaterialDefinition glass_material_{};
    CompiledBrittleMaterial compiled_glass_{};
    LatticeAsset glass_lattice_{};

    ActivationPolicy activation_policy_{};
    BrittleBondSolver solver_{};
    std::unique_ptr<JoltWorld> rigid_world_;

    std::optional<ImpactEvent> activating_impact_;
    std::optional<ActiveMatter> active_glass_;
    std::vector<FragmentComponent> latest_components_;
    FragmentBuildResult fragment_build_{};
    std::vector<DebrisParticleState> debris_particles_;

    std::size_t last_broken_bonds_{};
    unsigned stable_material_steps_{};
    double material_time_accumulator_s_{};
};

} // namespace banjo
