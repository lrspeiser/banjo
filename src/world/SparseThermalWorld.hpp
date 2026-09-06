#pragma once
#include "thermal/ThermalKernel.hpp"
#include "thermal/EnthalpyLaw.hpp"
#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#include <vector>

namespace banjo {
struct ChunkAddress {int x{},y{},z{};auto operator<=>(const ChunkAddress&) const=default;};
struct VoxelAddress {ChunkAddress chunk;unsigned x{},y{},z{};auto operator<=>(const VoxelAddress&) const=default;};
struct WorldThermalMaterial {
    unsigned id{};double solid_density_kg_m3{},fuel_mass_fraction{},oxygen_kg_per_kg_solid{};
    thermal::MaterialProperties thermal;
    std::optional<thermal::EnthalpyMaterial> phase_change;
};
struct ThermalCellView {
    VoxelAddress address;unsigned material{},region{};
    double temperature_k{},fuel_kg{},oxygen_kg{},region_time_s{},liquid_fraction{};
    bool phase_change{};
};
struct WorldStepBudget {unsigned maximum_jobs{64},maximum_cell_operations{32768};double maximum_wall_ms{4};};
struct ThermalFrontierPolicy {
    // A compact cold neighbor becomes a candidate when the absolute face
    // temperature difference reaches this SI threshold. Deferred faces are
    // treated as insulated until admission.
    double activation_temperature_difference_k{};
    unsigned maximum_face_probes_per_step{64};
    unsigned maximum_cells_added_per_step{8};
    unsigned maximum_pending_cells{128};
};
struct WorldStepReceipt {
    unsigned completed_jobs{},cell_operations{},regions_late{};
    unsigned frontier_face_probes{},frontier_cells_added{},frontier_candidates_pending{};
    unsigned frontier_regions_budget_blocked{};
    double wall_ms{},requested_time_s{},maximum_lag_s{};
    double oldest_frontier_candidate_age_s{};
    bool count_budget_exhausted{},wall_budget_exhausted{};
    std::string error;
};
struct ThermalRegionJoinReceipt {
    unsigned preserved_region_id{},retired_region_id{},cells{},edges{},joined_face_edges{};
    double accepted_time_s{};
};
// First world-scale storage/scheduling slice: compact uniform 16^3 chunks and
// explicitly activated thermal regions, insulated by default. Opt-in bounded
// cold-neighbor activation carries stored state into the same-clock region;
// deferred faces remain insulated approximations, with no global error bound.
// No mechanics, airflow, independent cross-clock flux, thermal weakening or
// automatic coarsening is claimed. The explicit join below makes
// two regions one same-clock island. Main-thread API; jobs publish atomically.
class SparseThermalWorld {
public:
    explicit SparseThermalWorld(double voxel_size_m);
    ~SparseThermalWorld();
    void addMaterial(WorldThermalMaterial material);
    void addUniformChunk(ChunkAddress address,unsigned material,double temperature_k,double liquid_fraction_at_melt=0);
    void activateInsulatedRegion(unsigned id,const std::vector<VoxelAddress>& cells,double fixed_step_s=.05);
    // Opts an existing caught-up region into bounded cold-neighbor growth.
    // The expected time makes the policy command transactional and rejects
    // stale/backlogged callers before mutation. Growth keeps this region's
    // clock and never joins or exchanges with another active region.
    void enableThermalFrontier(
        unsigned region_id,ThermalFrontierPolicy policy,double expected_region_time_s);
    // Atomically joins two caught-up, face-adjacent regions on the same clock.
    // The first ID survives and the second ID remains permanently retired.
    ThermalRegionJoinReceipt joinInsulatedRegions(
        unsigned first_region_id,unsigned second_region_id,double expected_region_time_s);
    // Applies work at the explicitly acknowledged accepted region time.
    // A stale timestamp or a backlogged region rejects before mutation.
    double addHeat(VoxelAddress cell,double requested_j,double limit_j,double expected_region_time_s);
    WorldStepReceipt advance(double requested_elapsed_s,WorldStepBudget budget={});
    std::vector<ThermalCellView> activeCells() const;
    std::string reportJson() const;
    std::uint64_t representedVoxelCount() const;
    std::size_t activeCellCount() const;
private:
    struct Impl;std::unique_ptr<Impl> impl_;
};
}
