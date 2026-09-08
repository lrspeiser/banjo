#pragma once

// Several lattice objects in one lattice.
//
// The fast lattice solver never asks what material it is stepping: node mass is
// per node, and compliance and all six damage thresholds are per bond, both
// carried by the asset. So a lattice holding a glass plate, an oak block and an
// iron ball is the same object to the solver as a lattice holding one plate.
// What keeps them separate objects is that no bond crosses between them; what
// makes them meet is node-to-node contact, which acts on any pair with no live
// bond joining it.
//
// Merging is therefore concatenation: nodes with their placement baked into the
// rest position, bonds with their endpoints shifted, adjacency rebuilt. Nothing
// about a part changes, so a single-part merge reproduces that part exactly.

#include "matter/Lattice.hpp"

#include <cstdint>
#include <span>
#include <vector>

namespace banjo {

// One object going into the merge: its lattice, where its rest centre of mass
// sits in the scene, and the density that turns represented volume into mass.
struct LatticePart {
    const LatticeAsset *asset{};
    Vec3 center_m{};
    double density_kg_m3{};
};

struct MergedLattice {
    LatticeAsset asset;
    // Which part each node and bond came from, so a caller can colour, name or
    // report per object after the merge.
    std::vector<std::uint32_t> part_of_node;
    std::vector<std::uint32_t> part_of_bond;
    // Node mass, already multiplied by the owning part's density. The scene
    // fills ActiveMatter from this rather than from one global density.
    std::vector<double> node_mass_kg;
    // Node index at which each part starts, part_count + 1 entries. No bond
    // crosses a part, so these are also valid solver slab boundaries: every
    // bond joins nodes inside one slab, which is the schedule's requirement
    // satisfied trivially rather than by a horizon argument.
    std::vector<std::uint32_t> part_node_begin;
};

// Rest positions in the merged asset are scene coordinates, not part-local
// ones: each part's nodes are placed about its own center_m. The merged
// rest_center_of_mass_m is the mass-weighted centroid of everything, so a
// caller that subtracts it gets the same convention a single part had.
[[nodiscard]] MergedLattice mergeLattices(std::span<const LatticePart> parts);

} // namespace banjo
