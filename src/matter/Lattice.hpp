#pragma once

#include "core/Math.hpp"
#include "material/Material.hpp"

#include <cstdint>
#include <vector>

namespace banjo {

struct SphereRecipe {
    double radius_m{};
    double voxel_size_m{};
    unsigned neighbor_horizon_cells{2};
    unsigned occupancy_samples_per_axis{3};
};

struct GridCoord {
    int x{};
    int y{};
    int z{};

    [[nodiscard]] bool operator==(const GridCoord &) const = default;
};

struct LatticeNodeRest {
    Vec3 local_position_m{};
    GridCoord grid{};
    double represented_volume_m3{};
    bool surface_node{};
};

struct BondRest {
    std::uint32_t node_a{};
    std::uint32_t node_b{};
    double rest_length_m{};
    double compliance{};
    double damage_start_stretch{};
    double damage_end_stretch{};
};

struct LatticeAsset {
    SphereRecipe recipe{};
    std::vector<LatticeNodeRest> nodes;
    std::vector<BondRest> bonds;
    std::vector<std::uint32_t> adjacency_offsets;
    std::vector<std::uint32_t> adjacent_bond_indices;

    double represented_volume_m3{};
    double total_mass_kg{};
    Vec3 rest_center_of_mass_m{};
    Mat3 rest_inertia_kg_m2{};
};

[[nodiscard]] LatticeAsset generateSphereLattice(
    const SphereRecipe &recipe,
    const CompiledBrittleMaterial &material);

} // namespace banjo
