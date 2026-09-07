#include "fastlattice/LatticeSchedule.hpp"

#include <algorithm>
#include <bit>
#include <cstddef>
#include <cstdint>
#include <numeric>
#include <stdexcept>
#include <vector>

namespace banjo::fastlattice {

LatticeSchedule buildLatticeSchedule(const LatticeAsset &asset) {
    const std::uint32_t boundaries[2] = {0U, static_cast<std::uint32_t>(asset.nodes.size())};
    return buildLatticeSchedule(asset, std::span<const std::uint32_t>(boundaries, 2));
}

LatticeSchedule buildLatticeSchedule(
    const LatticeAsset &asset,
    std::span<const std::uint32_t> node_block_begin) {
    const std::uint32_t node_count = static_cast<std::uint32_t>(asset.nodes.size());
    const std::uint32_t bond_count = static_cast<std::uint32_t>(asset.bonds.size());
    if (node_block_begin.size() < 2U || node_block_begin.front() != 0U ||
        node_block_begin.back() != node_count ||
        !std::is_sorted(node_block_begin.begin(), node_block_begin.end()))
        throw std::invalid_argument("lattice schedule needs sorted node block offsets covering every node");

    LatticeSchedule schedule;
    schedule.block_count = static_cast<std::uint32_t>(node_block_begin.size() - 1U);
    schedule.node_block_begin.assign(node_block_begin.begin(), node_block_begin.end());

    std::vector<std::uint32_t> block_of_node(node_count);
    for (std::uint32_t block = 0; block < schedule.block_count; ++block)
        for (std::uint32_t node = node_block_begin[block]; node < node_block_begin[block + 1U]; ++node)
            block_of_node[node] = block;

    // Greedy edge colouring in original bond order; up to 64 colours.
    std::vector<std::uint64_t> used(node_count, 0ULL);
    std::vector<std::uint8_t> color(bond_count);
    std::vector<std::uint32_t> owner(bond_count);
    std::vector<std::uint8_t> boundary(bond_count);
    std::uint32_t colors = 0;
    for (std::uint32_t bond = 0; bond < bond_count; ++bond) {
        const BondRest &rest = asset.bonds[bond];
        if (rest.node_a >= node_count || rest.node_b >= node_count || rest.node_a == rest.node_b)
            throw std::invalid_argument("lattice bond joins invalid nodes");
        const std::uint64_t free = ~(used[rest.node_a] | used[rest.node_b]);
        if (free == 0ULL) throw std::runtime_error("lattice needs more than 64 bond colours");
        const unsigned c = static_cast<unsigned>(std::countr_zero(free));
        used[rest.node_a] |= 1ULL << c;
        used[rest.node_b] |= 1ULL << c;
        color[bond] = static_cast<std::uint8_t>(c);
        colors = std::max(colors, c + 1U);
        const std::uint32_t block_a = block_of_node[rest.node_a];
        const std::uint32_t block_b = block_of_node[rest.node_b];
        const std::uint32_t low = std::min(block_a, block_b), high = std::max(block_a, block_b);
        if (high - low > 1U)
            throw std::invalid_argument(
                "slab decomposition needs slabs at least one neighbour horizon thick");
        owner[bond] = low;
        boundary[bond] = high != low ? 1U : 0U;
        if (boundary[bond]) ++schedule.boundary_bond_count;
    }
    schedule.color_count = colors;

    schedule.bond_order.resize(bond_count);
    std::iota(schedule.bond_order.begin(), schedule.bond_order.end(), 0U);
    std::stable_sort(schedule.bond_order.begin(), schedule.bond_order.end(),
        [&](std::uint32_t left, std::uint32_t right) {
            if (owner[left] != owner[right]) return owner[left] < owner[right];
            if (boundary[left] != boundary[right]) return boundary[left] < boundary[right];
            return color[left] < color[right];
        });
    schedule.bond_schedule_index.resize(bond_count);
    schedule.bond_color.resize(bond_count);
    for (std::uint32_t s = 0; s < bond_count; ++s) {
        schedule.bond_schedule_index[schedule.bond_order[s]] = s;
        schedule.bond_color[s] = color[schedule.bond_order[s]];
    }

    const std::size_t ranges = static_cast<std::size_t>(schedule.block_count) * 2U * std::max(colors, 1U);
    schedule.range_begin.assign(ranges, 0U);
    schedule.range_end.assign(ranges, 0U);
    schedule.bond_block_begin.assign(schedule.block_count + 1U, 0U);
    for (std::uint32_t s = 0; s < bond_count; ++s) {
        const std::uint32_t original = schedule.bond_order[s];
        const std::size_t key = (static_cast<std::size_t>(owner[original]) * 2U + boundary[original]) *
                                    std::max(colors, 1U) + color[original];
        if (schedule.range_end[key] == 0U && schedule.range_begin[key] == 0U) {
            schedule.range_begin[key] = s;
        }
        schedule.range_end[key] = s + 1U;
        schedule.bond_block_begin[owner[original] + 1U] = s + 1U;
    }
    // Empty ranges must not alias [0, 0) with a real range starting at 0.
    for (std::size_t key = 0; key < ranges; ++key)
        if (schedule.range_end[key] == 0U) schedule.range_begin[key] = 0U;
    for (std::uint32_t block = 1; block <= schedule.block_count; ++block)
        schedule.bond_block_begin[block] =
            std::max(schedule.bond_block_begin[block], schedule.bond_block_begin[block - 1U]);
    return schedule;
}

} // namespace banjo::fastlattice
