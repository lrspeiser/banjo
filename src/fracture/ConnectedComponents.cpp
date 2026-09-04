#include "fracture/ConnectedComponents.hpp"

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <stdexcept>
#include <unordered_map>
#include <utility>
#include <vector>

namespace banjo {
namespace {

class DisjointSet {
public:
    explicit DisjointSet(std::size_t size) : parent_(size), rank_(size, 0U) {
        for (std::size_t i = 0; i < size; ++i) {
            parent_[i] = static_cast<std::uint32_t>(i);
        }
    }

    [[nodiscard]] std::uint32_t find(std::uint32_t value) {
        if (parent_[value] != value) {
            parent_[value] = find(parent_[value]);
        }
        return parent_[value];
    }

    void unite(std::uint32_t a, std::uint32_t b) {
        a = find(a);
        b = find(b);
        if (a == b) {
            return;
        }
        if (rank_[a] < rank_[b]) {
            std::swap(a, b);
        }
        parent_[b] = a;
        if (rank_[a] == rank_[b]) {
            ++rank_[a];
        }
    }

private:
    std::vector<std::uint32_t> parent_;
    std::vector<std::uint8_t> rank_;
};

} // namespace

std::vector<FragmentComponent> findConnectedComponents(const ActiveMatter &matter) {
    if (matter.asset == nullptr || matter.nodes.size() != matter.asset->nodes.size() ||
        matter.bonds.size() != matter.asset->bonds.size()) {
        throw std::invalid_argument("active matter does not match its lattice asset");
    }

    DisjointSet components(matter.nodes.size());
    for (std::size_t bond_index = 0; bond_index < matter.bonds.size(); ++bond_index) {
        if (!matter.bonds[bond_index].alive) {
            continue;
        }
        const BondRest &bond = matter.asset->bonds[bond_index];
        components.unite(bond.node_a, bond.node_b);
    }

    std::unordered_map<std::uint32_t, std::size_t> component_by_root;
    std::vector<FragmentComponent> result;
    for (std::uint32_t node = 0; node < matter.nodes.size(); ++node) {
        const std::uint32_t root = components.find(node);
        auto [it, inserted] = component_by_root.emplace(root, result.size());
        if (inserted) {
            result.push_back({static_cast<std::uint32_t>(result.size()), {}});
        }
        result[it->second].node_indices.push_back(node);
    }

    std::sort(result.begin(), result.end(), [](const auto &a, const auto &b) {
        return a.node_indices.size() > b.node_indices.size();
    });
    for (std::uint32_t index = 0; index < result.size(); ++index) {
        result[index].id = index;
    }
    return result;
}

} // namespace banjo
