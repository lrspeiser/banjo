#pragma once

#include "fastlattice/FastLattice.hpp"
#include <array>
#include <vector>

namespace banjo::fastlattice {

// Canonical serial-reference partition, not a rigid-motion fit. Node maps keep
// original cell identity; bond maps are in each sub-asset's ORIGINAL order.
// Every live bond stays inside one component. Internal dead bonds stay in its
// state; dead crossing bonds are archived separately, never recreated.
struct ConstituentComponent {
    LatticeAsset asset;
    LatticeSchedule schedule;
    LatticeState state;
    std::vector<std::uint32_t> parent_nodes, parent_bonds;
    bool attached_to_boundary{};
};

struct SeveredConstituentBond {
    std::uint32_t parent_bond{}, parent_node_a{}, parent_node_b{};
    Vec3 rest_edge_m{};
    double rest_length_m{}, rest_length_sq_minus_m2{}, weight{}, compliance{};
    std::array<double,6> thresholds{};
    double damage{}, previous_tensile{}, previous_compressive{}, previous_shear{};
    double plastic_extension_m{}, plastic_strain_m{};
    std::uint8_t failure_mode{};
};

struct ConstituentPartition {
    std::vector<ConstituentComponent> components;
    std::vector<SeveredConstituentBond> severed_interfaces;
};

// Bounded read-only preparation for ownership transfer. Keeps exact canonical
// motion, reference geometry, mobility, compliance, thresholds and histories.
// Does not reset velocity, recenter, regenerate material thresholds, allocate
// source work between children, advance time, or publish/consume source matter.
// Caller must retire the old solver when admitting the prepared components.
// This preserves serial Verlet state; it is not an XPBD multiplier checkpoint.
[[nodiscard]] ConstituentPartition partitionConstituents(
    const LatticeAsset &,const LatticeSchedule &,const LatticeState &);

} // namespace banjo::fastlattice
