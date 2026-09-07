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

[[nodiscard]] LatticeResolutionLimit measureLatticeResolutionLimit(
    const LatticeAsset &asset, const CompiledBrittleMaterial &material);

} // namespace banjo
