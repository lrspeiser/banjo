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
    double compression_damage_start_strain{};
    double compression_damage_end_strain{};
    double shear_damage_start_strain{};
    double shear_damage_end_strain{};
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

// A uniform cubic-cell box: cells_x by cells_y by cells_z cells of one size,
// every cell fully occupied, centred on the lattice origin. The bonds follow
// exactly the sphere generator's rules (same horizon, same compliance weights,
// same strength variation), so a solver that runs on a sphere lattice runs on a
// box lattice unchanged and two lanes fed the same recipe see the same bonds.
// Full occupancy also means every node carries the same mass, which removes
// the surface-cell mass spread the sphere sampling produces.
struct BoxRecipe {
    unsigned cells_x{};
    unsigned cells_y{};
    unsigned cells_z{};
    double voxel_size_m{};
    unsigned neighbor_horizon_cells{2};
};

[[nodiscard]] LatticeAsset generateBoxLattice(
    const BoxRecipe &recipe,
    const CompiledBrittleMaterial &material);

// Period of the fastest bond mode carried by this lattice and the corresponding
// explicit-integration substep limit.
//
// For each node, omega = sqrt(sum of incident bond stiffness / node mass); the
// reported values use the largest omega in the lattice. XPBD's position solve is
// not conditionally stable, so exceeding this limit does not blow the solver up.
// It bounds *accuracy*: above it the lattice cannot carry its own elastic wave,
// so any strain the damage law then reads is a discretization result. Report it
// alongside a chosen material step rather than assuming the step is resolved.
struct LatticeResolutionLimit {
    double fastest_mode_angular_frequency_rad_s{};
    double fastest_mode_period_s{};
    double explicit_substep_limit_s{}; // 2 / omega_max
    std::uint32_t governing_node{};
};

// A lattice from an arbitrary set of occupied cells on one shared grid.
//
// Cell (i, j, k) is centred at ((i + 0.5) h, (j + 0.5) h, (k + 0.5) h), so the
// grid origin is a corner at the world origin and a body standing on the ground
// starts at j = 0. Two objects voxelised onto this grid can be unioned: a cell
// claimed by both appears once, which is how a handle is joined to a blade
// rather than left overlapping it. Bonds are built by the same neighbour rule
// every other generator uses, so they cross the seam and the result is one
// object, not two touching ones.
//
// Duplicate cells in `cells` are ignored rather than refused: the union of two
// overlapping shapes is the ordinary case here, not an error.
struct VoxelRecipe {
    std::vector<GridCoord> cells;
    double voxel_size_m{};
    unsigned neighbor_horizon_cells{2};
};

[[nodiscard]] LatticeAsset generateVoxelLattice(
    const VoxelRecipe &recipe,
    const CompiledBrittleMaterial &material);

[[nodiscard]] LatticeResolutionLimit measureLatticeResolutionLimit(
    const LatticeAsset &asset, const CompiledBrittleMaterial &material);

} // namespace banjo
