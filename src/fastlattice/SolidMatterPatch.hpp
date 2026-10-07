#pragma once

#include "fastlattice/FastLattice.hpp"
#include "material/Material.hpp"
#include "matter/Lattice.hpp"

#include <memory>
#include <string>
#include <vector>

namespace banjo::fastlattice {

// CPU constituent-matter reference for a finite, initially whole solid block.
// Optional source-node clamps model an ideal stationary far boundary with
// audited reactions. This is not terrain activation, a soil law, a finite
// neighbouring-world solver, or a live gameplay adapter. It uses the
// existing isotropic central-bond strength surface, not preset-name fracture.
struct SolidCell {
    std::string source;
    std::uint32_t source_node{};
    GridCoord grid;
    double edge_m{}, volume_m3{}, mass_kg{};
    Vec3 position_m{}, velocity_m_s{};
};

struct SolidComponent {
    std::vector<SolidCell> cells;
    double mass_kg{};
    bool attached_to_boundary{};
};

struct SolidPatchReport {
    double time_s{}, timestep_s{}, positive_source_work_j{};
    double mass_kg{}, volume_m3{}, kinetic_j{}, elastic_j{}, removed_bond_energy_j{};
    double source_work_j{}, integration_error_j{}, energy_residual_j{};
    Vec3 momentum_kg_m_s{}, angular_momentum_kg_m2_s{};
    Vec3 source_impulse_n_s{}, source_angular_impulse_kg_m2_s{};
    Vec3 boundary_impulse_n_s{}, boundary_angular_impulse_kg_m2_s{};
    Vec3 momentum_residual_kg_m_s{}, angular_residual_kg_m2_s{};
    std::uint32_t broken_bonds{};
};

struct SolidPulseResult {
    unsigned accepted_steps{};
    bool work_budget_reached{};
    double positive_work_j{}, wall_s{};
    SolidPatchReport state;
};

class SolidMatterPatch {
public:
    SolidMatterPatch(std::string source, Vec3 dimensions_m, double cell_m,
                    const MaterialDefinition &material, Vec3 center_m = {},
                    double timestep_fraction = .1, double maximum_timestep_s = 1e-7,
                    const std::vector<std::uint32_t> &fixed_source_nodes = {});
    ~SolidMatterPatch();
    SolidMatterPatch(const SolidMatterPatch &) = delete;
    SolidMatterPatch &operator=(const SolidMatterPatch &) = delete;

    // Force span is bounded; every accepted substep measures signed source work
    // and its reaction impulse/torque. Positive work cannot exceed the budget.
    // The first over-budget trial rolls back motion, clock and damage together.
    // Unloading does not recharge the positive-work budget. No velocities,
    // fragment patterns, directions or fragment counts are assigned here.
    SolidPulseResult pulse(const std::vector<Vec3> &forces_n, unsigned steps,
                           double maximum_positive_work_j);
    [[nodiscard]] SolidPatchReport report() const;
    [[nodiscard]] std::vector<SolidComponent> components() const;
    [[nodiscard]] const LatticeState &state() const { return state_; }
    [[nodiscard]] const LatticeAsset &asset() const { return asset_; }

private:
    std::string source_;
    double cell_m_{}, timestep_s_{}, positive_work_j_{};
    LatticeAsset asset_;
    CompiledBrittleMaterial compiled_;
    LatticeSchedule schedule_;
    LatticeState state_;
    std::unique_ptr<LatticeBackend> backend_;
};

} // namespace banjo::fastlattice
