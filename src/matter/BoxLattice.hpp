#pragma once

#include "matter/Lattice.hpp"

#include <cstdint>
#include <vector>

namespace banjo {

// A rectangular block of uniform cubic cells: the tile the fast lanes strike.
// Bonds follow generateSphereLattice's rules exactly (grid horizon, rest
// length, compliance over the horizon weight, strength variation per bond), so
// a box lattice and a sphere lattice of the same material break by the same
// numbers. Every cell is full, so node masses are uniform and the resolution
// limit is set by the interior node, not by a partially sampled surface cell.
struct BoxRecipe {
    Vec3 dimensions_m{};
    double voxel_size_m{};
    unsigned neighbor_horizon_cells{2};
};

// Node index = x + nx * (y + ny * z); z is the slowest axis so contiguous
// index ranges are slabs of z layers, which the lattice schedule uses.
struct BoxLatticeLayout {
    unsigned nx{}, ny{}, nz{};
};

// Dimensions must be whole multiples of the cell size (uniform cubic cells
// only); anything else is refused rather than silently rounded.
[[nodiscard]] LatticeAsset generateBoxLattice(
    const BoxRecipe &recipe,
    const CompiledBrittleMaterial &material,
    BoxLatticeLayout *layout = nullptr);

// Node-range boundaries for splitting a box lattice into at most
// requested_blocks slabs along z, each at least neighbor_horizon_cells layers
// thick so that every bond joins the same or adjacent slabs. Returns
// block_count + 1 node offsets.
[[nodiscard]] std::vector<std::uint32_t> boxLatticeSlabs(
    const BoxLatticeLayout &layout,
    unsigned neighbor_horizon_cells,
    unsigned requested_blocks);

} // namespace banjo
