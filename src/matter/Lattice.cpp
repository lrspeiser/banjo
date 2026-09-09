#include "matter/Lattice.hpp"

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <stdexcept>
#include <unordered_map>
#include <vector>

namespace banjo {
namespace {

struct GridCoordHash {
    [[nodiscard]] std::size_t operator()(const GridCoord &coord) const noexcept {
        std::uint64_t value = static_cast<std::uint32_t>(coord.x);
        value = (value * 0x9e3779b185ebca87ULL) ^
                static_cast<std::uint32_t>(coord.y);
        value = (value * 0xc2b2ae3d27d4eb4fULL) ^
                static_cast<std::uint32_t>(coord.z);
        value ^= value >> 33U;
        value *= 0xff51afd7ed558ccdULL;
        value ^= value >> 33U;
        return static_cast<std::size_t>(value);
    }
};

[[nodiscard]] std::uint64_t splitmix64(std::uint64_t value) {
    value += 0x9e3779b97f4a7c15ULL;
    value = (value ^ (value >> 30U)) * 0xbf58476d1ce4e5b9ULL;
    value = (value ^ (value >> 27U)) * 0x94d049bb133111ebULL;
    return value ^ (value >> 31U);
}

[[nodiscard]] double signedVariation(
    std::uint64_t seed,
    std::uint32_t node_a,
    std::uint32_t node_b,
    double amplitude) {
    std::uint64_t value = seed;
    value ^= static_cast<std::uint64_t>(node_a) << 32U;
    value ^= static_cast<std::uint64_t>(node_b);
    value = splitmix64(value);
    const double unit = static_cast<double>(value >> 11U) *
                        (1.0 / 9007199254740992.0);
    return 1.0 + amplitude * (2.0 * unit - 1.0);
}

[[nodiscard]] bool positiveHalfOffset(int dx, int dy, int dz) {
    return dz > 0 || (dz == 0 && dy > 0) ||
           (dz == 0 && dy == 0 && dx > 0);
}

[[nodiscard]] double occupancyFraction(
    const Vec3 &center,
    double voxel_size_m,
    double radius_m,
    unsigned samples_per_axis) {
    unsigned inside = 0U;
    const unsigned total =
        samples_per_axis * samples_per_axis * samples_per_axis;
    for (unsigned sx = 0; sx < samples_per_axis; ++sx) {
        for (unsigned sy = 0; sy < samples_per_axis; ++sy) {
            for (unsigned sz = 0; sz < samples_per_axis; ++sz) {
                const auto offset = [samples_per_axis](unsigned sample) {
                    return (static_cast<double>(sample) + 0.5) /
                               static_cast<double>(samples_per_axis) -
                           0.5;
                };
                const Vec3 point = center + voxel_size_m *
                                                Vec3{
                                                    offset(sx),
                                                    offset(sy),
                                                    offset(sz),
                                                };
                if (lengthSquared(point) <= radius_m * radius_m) {
                    ++inside;
                }
            }
        }
    }
    return static_cast<double>(inside) / static_cast<double>(total);
}

[[nodiscard]] Mat3 calculateRestInertia(
    const std::vector<LatticeNodeRest> &nodes,
    double density_kg_m3,
    const Vec3 &center_of_mass,
    double voxel_size_m) {
    Mat3 inertia{};
    for (const LatticeNodeRest &node : nodes) {
        const double mass = density_kg_m3 * node.represented_volume_m3;
        const Vec3 r = node.local_position_m - center_of_mass;
        const double cell_diagonal_inertia =
            mass * voxel_size_m * voxel_size_m / 6.0;

        inertia.m[0][0] +=
            mass * (r.y * r.y + r.z * r.z) + cell_diagonal_inertia;
        inertia.m[1][1] +=
            mass * (r.x * r.x + r.z * r.z) + cell_diagonal_inertia;
        inertia.m[2][2] +=
            mass * (r.x * r.x + r.y * r.y) + cell_diagonal_inertia;
        inertia.m[0][1] -= mass * r.x * r.y;
        inertia.m[1][0] = inertia.m[0][1];
        inertia.m[0][2] -= mass * r.x * r.z;
        inertia.m[2][0] = inertia.m[0][2];
        inertia.m[1][2] -= mass * r.y * r.z;
        inertia.m[2][1] = inertia.m[1][2];
    }
    return inertia;
}

void buildBonds(
    LatticeAsset &asset,
    const std::unordered_map<GridCoord, std::uint32_t, GridCoordHash> &node_by_grid,
    const CompiledBrittleMaterial &material,
    unsigned neighbor_horizon_cells) {
    const double voxel_size_m = asset.recipe.voxel_size_m;
    const int horizon =
        static_cast<int>(neighbor_horizon_cells);
    for (std::uint32_t node_index = 0;
         node_index < asset.nodes.size();
         ++node_index) {
        const GridCoord origin = asset.nodes[node_index].grid;
        for (int dz = -horizon; dz <= horizon; ++dz) {
            for (int dy = -horizon; dy <= horizon; ++dy) {
                for (int dx = -horizon; dx <= horizon; ++dx) {
                    if (!positiveHalfOffset(dx, dy, dz)) {
                        continue;
                    }
                    const double grid_distance = std::sqrt(
                        static_cast<double>(
                            dx * dx + dy * dy + dz * dz));
                    if (grid_distance >
                        static_cast<double>(horizon) + 1.0e-9) {
                        continue;
                    }

                    const GridCoord neighbor{
                        origin.x + dx,
                        origin.y + dy,
                        origin.z + dz,
                    };
                    const auto found = node_by_grid.find(neighbor);
                    if (found == node_by_grid.end()) {
                        continue;
                    }

                    const std::uint32_t other_index = found->second;
                    const double rest_length =
                        grid_distance * voxel_size_m;
                    const double horizon_weight =
                        1.0 / std::max(1.0, grid_distance * grid_distance);
                    const double variation = signedVariation(
                        material.seed,
                        node_index,
                        other_index,
                        material.strength_variation);
                    asset.bonds.push_back({
                        node_index,
                        other_index,
                        rest_length,
                        material.bond_compliance / horizon_weight,
                        material.damage_start_stretch * variation,
                        material.damage_end_stretch * variation,
                        material.compression_damage_start_strain * variation,
                        material.compression_damage_end_strain * variation,
                        material.shear_damage_start_strain * variation,
                        material.shear_damage_end_strain * variation,
                    });
                }
            }
        }
    }

}

void buildAdjacency(LatticeAsset &asset) {
    std::vector<std::uint32_t> degree(asset.nodes.size(), 0U);
    for (const BondRest &bond : asset.bonds) {
        ++degree[bond.node_a];
        ++degree[bond.node_b];
    }

    asset.adjacency_offsets.resize(asset.nodes.size() + 1U, 0U);
    for (std::size_t node = 0; node < asset.nodes.size(); ++node) {
        asset.adjacency_offsets[node + 1U] =
            asset.adjacency_offsets[node] + degree[node];
    }
    asset.adjacent_bond_indices.resize(asset.adjacency_offsets.back());
    std::vector<std::uint32_t> cursor = asset.adjacency_offsets;
    for (std::uint32_t bond_index = 0;
         bond_index < asset.bonds.size();
         ++bond_index) {
        const BondRest &bond = asset.bonds[bond_index];
        asset.adjacent_bond_indices[cursor[bond.node_a]++] = bond_index;
        asset.adjacent_bond_indices[cursor[bond.node_b]++] = bond_index;
    }

}

} // namespace

LatticeAsset generateSphereLattice(
    const SphereRecipe &recipe,
    const CompiledBrittleMaterial &material) {
    if (recipe.radius_m <= 0.0 || recipe.voxel_size_m <= 0.0 ||
        recipe.neighbor_horizon_cells == 0U ||
        recipe.occupancy_samples_per_axis == 0U) {
        throw std::invalid_argument(
            "sphere recipe values must be positive");
    }

    LatticeAsset asset;
    asset.recipe = recipe;

    const int extent =
        static_cast<int>(std::ceil(recipe.radius_m / recipe.voxel_size_m));
    const double voxel_volume = recipe.voxel_size_m * recipe.voxel_size_m *
                                recipe.voxel_size_m;
    std::unordered_map<GridCoord, std::uint32_t, GridCoordHash> node_by_grid;

    for (int z = -extent; z <= extent; ++z) {
        for (int y = -extent; y <= extent; ++y) {
            for (int x = -extent; x <= extent; ++x) {
                const Vec3 center{
                    static_cast<double>(x) * recipe.voxel_size_m,
                    static_cast<double>(y) * recipe.voxel_size_m,
                    static_cast<double>(z) * recipe.voxel_size_m,
                };
                const double occupied = occupancyFraction(
                    center,
                    recipe.voxel_size_m,
                    recipe.radius_m,
                    recipe.occupancy_samples_per_axis);
                if (occupied <= 0.0) {
                    continue;
                }

                const bool surface = occupied < 0.999999 ||
                                     length(center) +
                                             0.5 * std::sqrt(3.0) *
                                                 recipe.voxel_size_m >=
                                         recipe.radius_m;
                const std::uint32_t index =
                    static_cast<std::uint32_t>(asset.nodes.size());
                const GridCoord grid{x, y, z};
                asset.nodes.push_back({
                    center,
                    grid,
                    occupied * voxel_volume,
                    surface,
                });
                node_by_grid.emplace(grid, index);
                asset.represented_volume_m3 += occupied * voxel_volume;
            }
        }
    }

    asset.total_mass_kg =
        asset.represented_volume_m3 * material.density_kg_m3;
    if (asset.total_mass_kg <= 0.0) {
        throw std::runtime_error("sphere lattice contains no material");
    }

    Vec3 weighted_center{};
    for (const LatticeNodeRest &node : asset.nodes) {
        const double node_mass =
            node.represented_volume_m3 * material.density_kg_m3;
        weighted_center += node_mass * node.local_position_m;
    }
    asset.rest_center_of_mass_m =
        weighted_center / asset.total_mass_kg;
    asset.rest_inertia_kg_m2 = calculateRestInertia(
        asset.nodes,
        material.density_kg_m3,
        asset.rest_center_of_mass_m,
        recipe.voxel_size_m);

    buildBonds(asset, node_by_grid, material, recipe.neighbor_horizon_cells);
    buildAdjacency(asset);
    return asset;
}

LatticeAsset generateBoxLattice(
    const BoxRecipe &recipe,
    const CompiledBrittleMaterial &material) {
    if (recipe.cells_x == 0U || recipe.cells_y == 0U || recipe.cells_z == 0U ||
        !std::isfinite(recipe.voxel_size_m) || recipe.voxel_size_m <= 0.0 ||
        recipe.neighbor_horizon_cells == 0U) {
        throw std::invalid_argument("box recipe needs positive cell counts, cell size and horizon");
    }
    if (static_cast<std::uint64_t>(recipe.cells_x) * recipe.cells_y * recipe.cells_z > 4000000ULL) {
        throw std::invalid_argument("box recipe exceeds the lattice node budget");
    }
    if (!(material.density_kg_m3 > 0.0)) {
        throw std::invalid_argument("box lattice needs a positive density");
    }

    LatticeAsset asset;
    const Vec3 half_extent{
        0.5 * recipe.cells_x * recipe.voxel_size_m,
        0.5 * recipe.cells_y * recipe.voxel_size_m,
        0.5 * recipe.cells_z * recipe.voxel_size_m,
    };
    asset.recipe = {length(half_extent), recipe.voxel_size_m, recipe.neighbor_horizon_cells, 1U};
    const double voxel_volume = recipe.voxel_size_m * recipe.voxel_size_m * recipe.voxel_size_m;
    std::unordered_map<GridCoord, std::uint32_t, GridCoordHash> node_by_grid;
    node_by_grid.reserve(static_cast<std::size_t>(recipe.cells_x) * recipe.cells_y * recipe.cells_z);

    for (int z = 0; z < static_cast<int>(recipe.cells_z); ++z) {
        for (int y = 0; y < static_cast<int>(recipe.cells_y); ++y) {
            for (int x = 0; x < static_cast<int>(recipe.cells_x); ++x) {
                const Vec3 center{
                    (static_cast<double>(x) + 0.5) * recipe.voxel_size_m - half_extent.x,
                    (static_cast<double>(y) + 0.5) * recipe.voxel_size_m - half_extent.y,
                    (static_cast<double>(z) + 0.5) * recipe.voxel_size_m - half_extent.z,
                };
                const bool surface = x == 0 || y == 0 || z == 0 ||
                    x + 1 == static_cast<int>(recipe.cells_x) ||
                    y + 1 == static_cast<int>(recipe.cells_y) ||
                    z + 1 == static_cast<int>(recipe.cells_z);
                const GridCoord grid{x, y, z};
                node_by_grid.emplace(grid, static_cast<std::uint32_t>(asset.nodes.size()));
                asset.nodes.push_back({center, grid, voxel_volume, surface});
                asset.represented_volume_m3 += voxel_volume;
            }
        }
    }
    asset.total_mass_kg = asset.represented_volume_m3 * material.density_kg_m3;
    Vec3 weighted_center{};
    for (const LatticeNodeRest &node : asset.nodes) {
        weighted_center += node.represented_volume_m3 * material.density_kg_m3 * node.local_position_m;
    }
    asset.rest_center_of_mass_m = weighted_center / asset.total_mass_kg;
    asset.rest_inertia_kg_m2 = calculateRestInertia(
        asset.nodes, material.density_kg_m3, asset.rest_center_of_mass_m, recipe.voxel_size_m);
    buildBonds(asset, node_by_grid, material, recipe.neighbor_horizon_cells);
    buildAdjacency(asset);
    return asset;
}

LatticeAsset generateVoxelLattice(
    const VoxelRecipe &recipe,
    const CompiledBrittleMaterial &material) {
    if (recipe.cells.empty() || !std::isfinite(recipe.voxel_size_m) ||
        recipe.voxel_size_m <= 0.0 || recipe.neighbor_horizon_cells == 0U) {
        throw std::invalid_argument("voxel recipe needs cells, a positive cell size and a horizon");
    }
    if (recipe.cells.size() > 4000000U) {
        throw std::invalid_argument("voxel recipe exceeds the lattice node budget");
    }
    if (!(material.density_kg_m3 > 0.0)) {
        throw std::invalid_argument("voxel lattice needs a positive density");
    }

    LatticeAsset asset;
    const double h = recipe.voxel_size_m;
    const double voxel_volume = h * h * h;
    std::unordered_map<GridCoord, std::uint32_t, GridCoordHash> node_by_grid;
    node_by_grid.reserve(recipe.cells.size());

    // One node per distinct cell. A cell two shapes both claim is one cell.
    for (const GridCoord &grid : recipe.cells) {
        if (node_by_grid.contains(grid)) continue;
        const Vec3 center{(static_cast<double>(grid.x) + 0.5) * h,
                          (static_cast<double>(grid.y) + 0.5) * h,
                          (static_cast<double>(grid.z) + 0.5) * h};
        node_by_grid.emplace(grid, static_cast<std::uint32_t>(asset.nodes.size()));
        asset.nodes.push_back({center, grid, voxel_volume, true});
        asset.represented_volume_m3 += voxel_volume;
    }
    // A cell is interior when all six of its face neighbours are present. This
    // is what the box generator means by surface, decided by occupancy rather
    // than by being on the edge of a box.
    for (LatticeNodeRest &node : asset.nodes) {
        const GridCoord g = node.grid;
        node.surface_node =
            !(node_by_grid.contains({g.x + 1, g.y, g.z}) && node_by_grid.contains({g.x - 1, g.y, g.z}) &&
              node_by_grid.contains({g.x, g.y + 1, g.z}) && node_by_grid.contains({g.x, g.y - 1, g.z}) &&
              node_by_grid.contains({g.x, g.y, g.z + 1}) && node_by_grid.contains({g.x, g.y, g.z - 1}));
    }

    asset.recipe = {0.5 * h * std::cbrt(static_cast<double>(asset.nodes.size())), h,
                    recipe.neighbor_horizon_cells, 1U};
    asset.total_mass_kg = asset.represented_volume_m3 * material.density_kg_m3;
    Vec3 weighted_center{};
    for (const LatticeNodeRest &node : asset.nodes) {
        weighted_center += node.represented_volume_m3 * material.density_kg_m3 * node.local_position_m;
    }
    asset.rest_center_of_mass_m = weighted_center / asset.total_mass_kg;
    asset.rest_inertia_kg_m2 = calculateRestInertia(
        asset.nodes, material.density_kg_m3, asset.rest_center_of_mass_m, h);
    buildBonds(asset, node_by_grid, material, recipe.neighbor_horizon_cells);
    buildAdjacency(asset);
    return asset;
}

LatticeResolutionLimit measureLatticeResolutionLimit(
    const LatticeAsset &asset, const CompiledBrittleMaterial &material) {
    LatticeResolutionLimit limit;
    if (asset.nodes.empty() || asset.adjacency_offsets.size() != asset.nodes.size() + 1U) {
        return limit;
    }
    for (std::uint32_t node = 0; node < asset.nodes.size(); ++node) {
        const double mass_kg = asset.nodes[node].represented_volume_m3 * material.density_kg_m3;
        if (!(mass_kg > 0.0)) continue;
        double stiffness_n_m = 0.0;
        for (std::uint32_t adjacency = asset.adjacency_offsets[node];
             adjacency < asset.adjacency_offsets[node + 1U]; ++adjacency) {
            const double compliance = asset.bonds[asset.adjacent_bond_indices[adjacency]].compliance;
            if (compliance > 0.0) stiffness_n_m += 1.0 / compliance;
        }
        if (!(stiffness_n_m > 0.0)) continue;
        const double omega = std::sqrt(stiffness_n_m / mass_kg);
        if (omega > limit.fastest_mode_angular_frequency_rad_s) {
            limit.fastest_mode_angular_frequency_rad_s = omega;
            limit.governing_node = node;
        }
    }
    if (limit.fastest_mode_angular_frequency_rad_s > 0.0) {
        limit.fastest_mode_period_s =
            2.0 * std::acos(-1.0) / limit.fastest_mode_angular_frequency_rad_s;
        limit.explicit_substep_limit_s = 2.0 / limit.fastest_mode_angular_frequency_rad_s;
    }
    return limit;
}

} // namespace banjo
