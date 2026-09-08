#include "matter/LatticeMerge.hpp"

#include <stdexcept>

namespace banjo {

MergedLattice mergeLattices(std::span<const LatticePart> parts) {
    if (parts.empty()) throw std::invalid_argument("a merged lattice needs at least one part");

    MergedLattice merged;
    std::size_t total_nodes = 0;
    std::size_t total_bonds = 0;
    for (const LatticePart &part : parts) {
        if (part.asset == nullptr) throw std::invalid_argument("a lattice part has no asset");
        if (!(part.density_kg_m3 > 0.0)) throw std::invalid_argument("a lattice part has no density");
        if (part.asset->nodes.empty()) throw std::invalid_argument("a lattice part has no nodes");
        total_nodes += part.asset->nodes.size();
        total_bonds += part.asset->bonds.size();
    }

    LatticeAsset &out = merged.asset;
    out.nodes.reserve(total_nodes);
    out.bonds.reserve(total_bonds);
    out.adjacency_offsets.reserve(total_nodes + 1U);
    out.adjacent_bond_indices.reserve(2U * total_bonds);
    merged.part_of_node.reserve(total_nodes);
    merged.part_of_bond.reserve(total_bonds);
    merged.node_mass_kg.reserve(total_nodes);
    merged.part_node_begin.reserve(parts.size() + 1U);

    // The first part keeps the recipe so a single-part merge is that part with
    // its nodes moved: nothing downstream that reads the recipe sees a change.
    out.recipe = parts.front().asset->recipe;
    out.adjacency_offsets.push_back(0U);

    double mass_total = 0.0;
    Vec3 mass_weighted{0.0, 0.0, 0.0};

    for (std::uint32_t p = 0; p < parts.size(); ++p) {
        const LatticePart &part = parts[p];
        const LatticeAsset &in = *part.asset;
        const auto node_offset = static_cast<std::uint32_t>(out.nodes.size());
        const auto bond_offset = static_cast<std::uint32_t>(out.bonds.size());
        merged.part_node_begin.push_back(node_offset);

        for (const LatticeNodeRest &node : in.nodes) {
            LatticeNodeRest placed = node;
            // Bake the placement in. A part's own rest centre of mass is
            // removed first so center_m means the centre of that object,
            // whatever local origin its generator used.
            placed.local_position_m = part.center_m + (node.local_position_m - in.rest_center_of_mass_m);
            out.nodes.push_back(placed);
            merged.part_of_node.push_back(p);
            const double mass = node.represented_volume_m3 * part.density_kg_m3;
            merged.node_mass_kg.push_back(mass);
            mass_total += mass;
            mass_weighted = mass_weighted + placed.local_position_m * mass;
        }

        for (const BondRest &bond : in.bonds) {
            BondRest shifted = bond;
            shifted.node_a = bond.node_a + node_offset;
            shifted.node_b = bond.node_b + node_offset;
            out.bonds.push_back(shifted);
            merged.part_of_bond.push_back(p);
        }

        // Adjacency is a prefix-sum over nodes into a bond-index list; both
        // sides shift by this part's offsets.
        for (std::size_t i = 0; i < in.nodes.size(); ++i) {
            const std::uint32_t begin = in.adjacency_offsets[i];
            const std::uint32_t end = in.adjacency_offsets[i + 1U];
            for (std::uint32_t k = begin; k < end; ++k)
                out.adjacent_bond_indices.push_back(in.adjacent_bond_indices[k] + bond_offset);
            out.adjacency_offsets.push_back(static_cast<std::uint32_t>(out.adjacent_bond_indices.size()));
        }

        out.represented_volume_m3 += in.represented_volume_m3;
    }
    merged.part_node_begin.push_back(static_cast<std::uint32_t>(out.nodes.size()));

    out.total_mass_kg = mass_total;
    out.rest_center_of_mass_m = mass_total > 0.0 ? mass_weighted * (1.0 / mass_total) : Vec3{};

    // Inertia about the merged centre of mass, from point masses at the nodes.
    // The parts' own tensors cannot simply be added: they are each about a
    // different centre.
    Mat3 inertia{};
    for (std::size_t i = 0; i < out.nodes.size(); ++i) {
        const Vec3 d = out.nodes[i].local_position_m - out.rest_center_of_mass_m;
        const double m = merged.node_mass_kg[i];
        const double dxx = d.x * d.x, dyy = d.y * d.y, dzz = d.z * d.z;
        inertia.m[0][0] += m * (dyy + dzz);
        inertia.m[1][1] += m * (dxx + dzz);
        inertia.m[2][2] += m * (dxx + dyy);
        inertia.m[0][1] -= m * d.x * d.y;
        inertia.m[0][2] -= m * d.x * d.z;
        inertia.m[1][2] -= m * d.y * d.z;
    }
    inertia.m[1][0] = inertia.m[0][1];
    inertia.m[2][0] = inertia.m[0][2];
    inertia.m[2][1] = inertia.m[1][2];
    out.rest_inertia_kg_m2 = inertia;
    return merged;
}

} // namespace banjo
