#include "matter/BoxLattice.hpp"

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <stdexcept>
#include <vector>

namespace banjo {
namespace {

// Same hash mixing as matter/Lattice.cpp so a bond between two node indices
// gets the same strength variation whatever generator produced it.
[[nodiscard]] std::uint64_t splitmix64(std::uint64_t value) {
    value += 0x9e3779b97f4a7c15ULL;
    value = (value ^ (value >> 30U)) * 0xbf58476d1ce4e5b9ULL;
    value = (value ^ (value >> 27U)) * 0x94d049bb133111ebULL;
    return value ^ (value >> 31U);
}

[[nodiscard]] double signedVariation(
    std::uint64_t seed, std::uint32_t node_a, std::uint32_t node_b, double amplitude) {
    std::uint64_t value = seed;
    value ^= static_cast<std::uint64_t>(node_a) << 32U;
    value ^= static_cast<std::uint64_t>(node_b);
    value = splitmix64(value);
    const double unit = static_cast<double>(value >> 11U) * (1.0 / 9007199254740992.0);
    return 1.0 + amplitude * (2.0 * unit - 1.0);
}

[[nodiscard]] bool positiveHalfOffset(int dx, int dy, int dz) {
    return dz > 0 || (dz == 0 && dy > 0) || (dz == 0 && dy == 0 && dx > 0);
}

[[nodiscard]] unsigned cellCount(double extent_m, double voxel_size_m, const char *axis) {
    const double cells = extent_m / voxel_size_m;
    const double rounded = std::round(cells);
    if (rounded < 1.0 || std::abs(cells - rounded) > 1.0e-6 * std::max(1.0, rounded)) {
        throw std::invalid_argument(
            std::string("box lattice ") + axis +
            " extent must be a whole number of uniform cubic cells");
    }
    return static_cast<unsigned>(rounded);
}

} // namespace

LatticeAsset generateBoxLattice(
    const BoxRecipe &recipe,
    const CompiledBrittleMaterial &material,
    BoxLatticeLayout *layout_out) {
    if (!(recipe.voxel_size_m > 0.0) || recipe.neighbor_horizon_cells == 0U ||
        !(recipe.dimensions_m.x > 0.0) || !(recipe.dimensions_m.y > 0.0) ||
        !(recipe.dimensions_m.z > 0.0)) {
        throw std::invalid_argument("box recipe values must be positive");
    }
    if (!(material.density_kg_m3 > 0.0)) {
        throw std::invalid_argument("box lattice needs a positive density");
    }
    const double h = recipe.voxel_size_m;
    const BoxLatticeLayout layout{
        cellCount(recipe.dimensions_m.x, h, "x"),
        cellCount(recipe.dimensions_m.y, h, "y"),
        cellCount(recipe.dimensions_m.z, h, "z"),
    };
    if (layout_out) *layout_out = layout;

    LatticeAsset asset;
    asset.recipe.radius_m = 0.0;
    asset.recipe.voxel_size_m = h;
    asset.recipe.neighbor_horizon_cells = recipe.neighbor_horizon_cells;
    asset.recipe.occupancy_samples_per_axis = 1;

    const double voxel_volume = h * h * h;
    const std::size_t node_total =
        static_cast<std::size_t>(layout.nx) * layout.ny * layout.nz;
    asset.nodes.reserve(node_total);
    for (unsigned z = 0; z < layout.nz; ++z) {
        for (unsigned y = 0; y < layout.ny; ++y) {
            for (unsigned x = 0; x < layout.nx; ++x) {
                const Vec3 center{
                    (static_cast<double>(x) + 0.5 - 0.5 * layout.nx) * h,
                    (static_cast<double>(y) + 0.5 - 0.5 * layout.ny) * h,
                    (static_cast<double>(z) + 0.5 - 0.5 * layout.nz) * h,
                };
                const bool surface = x == 0 || y == 0 || z == 0 || x + 1 == layout.nx ||
                                     y + 1 == layout.ny || z + 1 == layout.nz;
                asset.nodes.push_back({center, {static_cast<int>(x), static_cast<int>(y),
                                                static_cast<int>(z)}, voxel_volume, surface});
                asset.represented_volume_m3 += voxel_volume;
            }
        }
    }
    asset.total_mass_kg = asset.represented_volume_m3 * material.density_kg_m3;

    // Uniform cells: the centre of mass is the box centre by construction.
    Vec3 weighted{};
    for (const LatticeNodeRest &node : asset.nodes) weighted += node.local_position_m;
    asset.rest_center_of_mass_m = weighted / static_cast<double>(asset.nodes.size());
    for (const LatticeNodeRest &node : asset.nodes) {
        const double mass = material.density_kg_m3 * node.represented_volume_m3;
        const Vec3 r = node.local_position_m - asset.rest_center_of_mass_m;
        const double cell_diagonal_inertia = mass * h * h / 6.0;
        Mat3 &inertia = asset.rest_inertia_kg_m2;
        inertia.m[0][0] += mass * (r.y * r.y + r.z * r.z) + cell_diagonal_inertia;
        inertia.m[1][1] += mass * (r.x * r.x + r.z * r.z) + cell_diagonal_inertia;
        inertia.m[2][2] += mass * (r.x * r.x + r.y * r.y) + cell_diagonal_inertia;
        inertia.m[0][1] -= mass * r.x * r.y;
        inertia.m[1][0] = inertia.m[0][1];
        inertia.m[0][2] -= mass * r.x * r.z;
        inertia.m[2][0] = inertia.m[0][2];
        inertia.m[1][2] -= mass * r.y * r.z;
        inertia.m[2][1] = inertia.m[1][2];
    }

    const auto index = [&](unsigned x, unsigned y, unsigned z) {
        return static_cast<std::uint32_t>(x + layout.nx * (y + layout.ny * z));
    };
    const int horizon = static_cast<int>(recipe.neighbor_horizon_cells);
    for (std::uint32_t node_index = 0; node_index < asset.nodes.size(); ++node_index) {
        const GridCoord origin = asset.nodes[node_index].grid;
        for (int dz = -horizon; dz <= horizon; ++dz) {
            for (int dy = -horizon; dy <= horizon; ++dy) {
                for (int dx = -horizon; dx <= horizon; ++dx) {
                    if (!positiveHalfOffset(dx, dy, dz)) continue;
                    const double grid_distance =
                        std::sqrt(static_cast<double>(dx * dx + dy * dy + dz * dz));
                    if (grid_distance > static_cast<double>(horizon) + 1.0e-9) continue;
                    const int nx = origin.x + dx, ny = origin.y + dy, nz = origin.z + dz;
                    if (nx < 0 || ny < 0 || nz < 0 || nx >= static_cast<int>(layout.nx) ||
                        ny >= static_cast<int>(layout.ny) || nz >= static_cast<int>(layout.nz))
                        continue;
                    const std::uint32_t other_index = index(
                        static_cast<unsigned>(nx), static_cast<unsigned>(ny), static_cast<unsigned>(nz));
                    const double rest_length = grid_distance * h;
                    const double horizon_weight = 1.0 / std::max(1.0, grid_distance * grid_distance);
                    const double variation = signedVariation(
                        material.seed, node_index, other_index, material.strength_variation);
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

    std::vector<std::uint32_t> degree(asset.nodes.size(), 0U);
    for (const BondRest &bond : asset.bonds) {
        ++degree[bond.node_a];
        ++degree[bond.node_b];
    }
    asset.adjacency_offsets.resize(asset.nodes.size() + 1U, 0U);
    for (std::size_t node = 0; node < asset.nodes.size(); ++node)
        asset.adjacency_offsets[node + 1U] = asset.adjacency_offsets[node] + degree[node];
    asset.adjacent_bond_indices.resize(asset.adjacency_offsets.back());
    std::vector<std::uint32_t> cursor = asset.adjacency_offsets;
    for (std::uint32_t bond_index = 0; bond_index < asset.bonds.size(); ++bond_index) {
        const BondRest &bond = asset.bonds[bond_index];
        asset.adjacent_bond_indices[cursor[bond.node_a]++] = bond_index;
        asset.adjacent_bond_indices[cursor[bond.node_b]++] = bond_index;
    }
    return asset;
}

std::vector<std::uint32_t> boxLatticeSlabs(
    const BoxLatticeLayout &layout,
    unsigned neighbor_horizon_cells,
    unsigned requested_blocks) {
    if (layout.nx == 0 || layout.ny == 0 || layout.nz == 0 || neighbor_horizon_cells == 0)
        throw std::invalid_argument("slab split needs a non-empty layout and a positive horizon");
    const unsigned layers_per_block = neighbor_horizon_cells;
    unsigned blocks = std::max(1U, requested_blocks);
    blocks = std::min(blocks, std::max(1U, layout.nz / layers_per_block));
    const std::uint32_t layer_nodes = layout.nx * layout.ny;
    std::vector<std::uint32_t> begin;
    begin.reserve(blocks + 1U);
    for (unsigned b = 0; b <= blocks; ++b) {
        // Even split of z layers; every block gets at least layers_per_block.
        const unsigned layer = static_cast<unsigned>(
            (static_cast<std::uint64_t>(layout.nz) * b) / blocks);
        begin.push_back(layer * layer_nodes);
    }
    begin.back() = layer_nodes * layout.nz;
    return begin;
}

} // namespace banjo
