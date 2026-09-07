#pragma once

#include "matter/Lattice.hpp"

#include <cstdint>
#include <span>
#include <vector>

namespace banjo::fastlattice {

// How the bonds of a lattice are swept in parallel without changing the
// Gauss-Seidel character of the XPBD solve.
//
// Bonds sharing a node cannot be solved at the same time, so the bond graph is
// edge-coloured greedily; one colour is a set of node-disjoint bonds that a
// block solves in one parallel stage. Across blocks, nodes are split into
// contiguous slabs and a bond is owned by the slab of its lower node: interior
// bonds (both ends in one slab) are swept first by every block, then the
// boundary bonds of even-numbered slabs, then those of odd-numbered slabs.
// Every bond is solved exactly once per iteration against the latest
// positions, so this is a Gauss-Seidel sweep in a permuted bond order, not a
// Jacobi relaxation. The permutation is the only difference from the CPU
// lane's index-order sweep; docs/fast-gpu-checkpoint.md measures its effect.
//
// The slab rule requires every bond to join the same or adjacent slabs, i.e.
// slabs at least one neighbour horizon thick; buildLatticeSchedule refuses
// anything else.
struct LatticeSchedule {
    std::uint32_t block_count{1};
    std::uint32_t color_count{};
    std::uint32_t boundary_bond_count{};
    // block_count + 1 node offsets.
    std::vector<std::uint32_t> node_block_begin;
    // schedule index -> original bond index, and the inverse.
    std::vector<std::uint32_t> bond_order;
    std::vector<std::uint32_t> bond_schedule_index;
    // block_count + 1 offsets into the schedule order, bonds grouped by owner.
    std::vector<std::uint32_t> bond_block_begin;
    // ((block * 2 + boundary) * color_count + color) -> [begin, end) in
    // schedule order.
    std::vector<std::uint32_t> range_begin;
    std::vector<std::uint32_t> range_end;
    std::vector<std::uint8_t> bond_color; // per schedule index
};

[[nodiscard]] LatticeSchedule buildLatticeSchedule(
    const LatticeAsset &asset,
    std::span<const std::uint32_t> node_block_begin);

// Single-block schedule for any lattice.
[[nodiscard]] LatticeSchedule buildLatticeSchedule(const LatticeAsset &asset);

} // namespace banjo::fastlattice
