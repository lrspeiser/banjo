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
struct WorldStepReceipt {
    unsigned completed_jobs{},cell_operations{},regions_late{};
    double wall_ms{},requested_time_s{},maximum_lag_s{};
    bool count_budget_exhausted{},wall_budget_exhausted{};
    std::string error;
};
// First world-scale storage/scheduling slice: compact uniform 16^3 chunks and
// explicitly activated, INSULATED thermal regions. No implicit heat sink at a
// cold boundary: insulation is part of this experimental region contract.
// No mechanics, airflow, cross-region flux, thermal weakening or automatic
// activation/coarsening is claimed. Main-thread API; jobs publish atomically.
class SparseThermalWorld {
public:
    explicit SparseThermalWorld(double voxel_size_m);
    ~SparseThermalWorld();
    void addMaterial(WorldThermalMaterial material);
    void addUniformChunk(ChunkAddress address,unsigned material,double temperature_k,double liquid_fraction_at_melt=0);
    void activateInsulatedRegion(unsigned id,const std::vector<VoxelAddress>& cells,double fixed_step_s=.05);
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
