#pragma once

#include "core/Math.hpp"
#include "core/Plane.hpp"
#include "core/Types.hpp"
#include "fracture/ActivationPolicy.hpp"
#include "fracture/ActiveMatter.hpp"
#include "fracture/BrittleBondSolver.hpp"
#include "fracture/FragmentGeometry.hpp"
#include "fracture/ImpactEvent.hpp"
#include "material/Material.hpp"
#include "material/MaterialCatalog.hpp"
#include "matter/Lattice.hpp"
#include "prediction/BallScenarioProjection.hpp"
#include "prediction/ScenarioCache.hpp"
#include "rigid/JoltWorld.hpp"
#include "physics/RollingKinematics.hpp"

#include <cstddef>
#include <cstdint>
#include <filesystem>
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
    MaterialPreset striker_material{MaterialPreset::Iron};
    MaterialPreset target_material{MaterialPreset::Glass};
    MaterialPreset surface_material{MaterialPreset::Concrete};

    double radius_m{0.25};
    double voxel_size_m{0.04};
    unsigned neighbor_horizon_cells{2};
    unsigned occupancy_samples_per_axis{3};

    // Retained name for source compatibility; this is the selected striker's speed.
    double iron_speed_m_s{8.0};
    double target_initial_speed_m_s{};
    double surface_slope_degrees{};
    double sphere_inertia_factor{0.4};
    double striker_spin_ratio{1.0}; // 1 = rolling; 0 = initially sliding

    Vec3 gravity_m_s2{0.0, -9.81, 0.0};
    bool support_enabled{true};
    std::uint64_t material_seed{971};

    double rigid_step_s{1.0 / 120.0};
    double material_step_s{1.0 / 240.0};
    // Numerical resolution of the active material solver. These select how the
    // same constitutive law is integrated; they are not material properties.
    unsigned material_substeps{1};
    unsigned material_constraint_iterations{8};
    unsigned minimum_material_steps{180};
    unsigned stable_material_steps_before_handoff{60};
    unsigned maximum_material_steps{480};

    double impact_internal_energy_fraction{0.0}; // must be zero in contact-driven runtime
    double maximum_internal_energy_j{1200.0};

    std::size_t maximum_rigid_fragments{64};
    std::size_t minimum_nodes_per_rigid_fragment{1};
    std::size_t maximum_collision_points{192};
    std::uint64_t realtime_constraint_budget{50'000'000ULL};
    bool audit_material_stages{};
};

struct ExperimentStats {
    ExperimentPhase phase{ExperimentPhase::Rigid};
    std::uint64_t fixed_ticks{};
    double simulated_time_s{};
    std::uint64_t rigid_steps{};
    std::uint64_t material_steps{};

    std::size_t active_nodes{};
    std::size_t total_bonds{};
    std::size_t broken_bonds{};
    std::size_t connected_components{1};
    std::size_t rigid_fragments{};
    std::size_t debris_particles{};

    double represented_target_mass_kg{};
    double represented_glass_mass_kg{};
    double fragment_mass_kg{};
    double mass_error_kg{};

    double impact_speed_m_s{};
    double impact_tangential_speed_m_s{};
    double impact_energy_j{};
    double activation_threshold_j{};
    double normalized_impact_energy{};
    double actual_contact_friction{};
    double actual_contact_restitution{};

    double predicted_peak_force_n{};
    double predicted_peak_pressure_pa{};
    double predicted_striker_mass_kg{};
    double predicted_target_mass_kg{};
    double predicted_slope_acceleration_m_s2{};
    PredictedFailureMode predicted_failure{PredictedFailureMode::None};
    InclineMotionRegime predicted_incline_regime{InclineMotionRegime::AtRest};
    RuntimeStrategy runtime_strategy{RuntimeStrategy::RigidRealtime};
    bool projection_cache_hit{};

    double maximum_tensile_stretch{};
    // Resolution limit of the compiled target lattice, reported next to the
    // configured material step so an unresolved run is visible rather than
    // assumed. See matter/Lattice.hpp.
    LatticeResolutionLimit target_resolution_limit{};
    double active_kinetic_energy_j{};
    double active_elastic_energy_j{};
    double maximum_node_speed_m_s{};
    RollingKinematics striker_motion{};
    RollingKinematics target_motion{};
    std::size_t coupled_contact_points{};
    double coupled_impulse_n_s{};
    double coupled_contact_dissipation_j{};
    double internal_damping_loss_j{};
    double maximum_contact_penetration_m{};
    bool activation_response_deferred{};
    RepresentationTransferAudit activation_transfer{};
    RepresentationTransferAudit fragment_transfer{};
    double coarsening_kinetic_loss_j{};
    double coarsening_elastic_loss_j{};
    Vec3 contact_correction_angular_momentum_delta_kg_m2_s{};
    Vec3 constraint_angular_momentum_delta_kg_m2_s{};
    double constraint_mechanical_energy_delta_j{};
    double unassigned_bond_removal_energy_j{};
    std::uint64_t audited_material_steps{};
    MaterialStageChanges material_stage_changes{};
};

struct DebrisParticleState {
    Vec3 position_world_m{};
    Vec3 velocity_m_s{};
    Vec3 angular_velocity_rad_s{};
    double mass_kg{};
    double radius_m{};
    Mat3 inertia_world_kg_m2{};
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

    [[nodiscard]] std::size_t loadProjectionCache(
        const std::filesystem::path &path);
    void saveProjectionCache(const std::filesystem::path &path) const;

    [[nodiscard]] const ExperimentSettings &settings() const { return settings_; }
    [[nodiscard]] const ExperimentStats &stats() const { return stats_; }
    [[nodiscard]] ExperimentPhase phase() const { return stats_.phase; }
    [[nodiscard]] const SupportPlaneFrame &supportPlane() const { return support_plane_; }
    [[nodiscard]] const ScenarioProjection &scenarioProjection() const {
        return scenario_projection_;
    }
    [[nodiscard]] const MaterialDefinition &strikerMaterial() const {
        return striker_material_;
    }
    [[nodiscard]] const MaterialDefinition &targetMaterial() const {
        return target_material_;
    }
    [[nodiscard]] const MaterialDefinition &surfaceMaterial() const {
        return surface_material_;
    }

    [[nodiscard]] std::optional<RigidSnapshot> rigidSnapshot(
        MatterBodyId body_id) const;
    [[nodiscard]] const ActiveMatter *activeMatter() const;
    [[nodiscard]] MechanicalTotals mechanicalTotals() const;
    [[nodiscard]] const std::optional<ImpactEvent> &activatingImpact() const {
        return activating_impact_;
    }
    [[nodiscard]] const FragmentBuildResult &fragmentBuild() const {
        return fragment_build_;
    }
    [[nodiscard]] const std::vector<DebrisParticleState> &debrisParticles() const {
        return debris_particles_;
    }
    [[nodiscard]] const LatticeAsset *targetLattice() const {
        return target_lattice_ ? &*target_lattice_ : nullptr;
    }
    [[nodiscard]] const LatticeAsset &glassLattice() const;

    static constexpr MatterBodyId kStrikerBallId = 1;
    static constexpr MatterBodyId kTargetBallId = 2;
    static constexpr MatterBodyId kIronBallId = kStrikerBallId;
    static constexpr MatterBodyId kGlassBallId = kTargetBallId;

private:
    void initializeWorld();
    void updateScenarioProjection();
    void stepRigidPhase(double dt_s);
    void stepFracturingPhase(double dt_s);
    void stepRigidFragmentsPhase(double dt_s);
    void updateMotionDiagnostics();
    void finalizeFragments();
    void updateComponentCount();
    void integrateDebris(double dt_s);

    ExperimentSettings settings_{};
    ExperimentStats stats_{};

    MaterialDefinition striker_material_{};
    MaterialDefinition target_material_{};
    MaterialDefinition surface_material_{};
    CombinedContactMaterial target_surface_contact_{};
    std::optional<CompiledBrittleMaterial> compiled_target_;
    std::optional<LatticeAsset> target_lattice_;
    SupportPlaneFrame support_plane_{};

    ScenarioProjectionCache projection_cache_{};
    ScenarioProjection scenario_projection_{};

    ActivationPolicy activation_policy_{};
    BrittleBondSolver solver_{};
    std::unique_ptr<JoltWorld> rigid_world_;

    std::optional<ImpactEvent> activating_impact_;
    std::optional<ActiveMatter> active_target_;
    std::vector<FragmentComponent> latest_components_;
    FragmentBuildResult fragment_build_{};
    std::vector<DebrisParticleState> debris_particles_;

    std::size_t last_broken_bonds_{};
    unsigned stable_material_steps_{};
    double material_time_accumulator_s_{}; // elapsed physical time in material mode
    double stable_material_time_s_{};
};

} // namespace banjo
