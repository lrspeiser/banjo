#pragma once

#include "physics/SmallStrainPatch.hpp"

#include <array>
#include <cstddef>
#include <cstdint>
#include <vector>

namespace banjo {

struct FractureTopologyLimits {
    std::size_t maximum_original_nodes{4096};
    std::size_t maximum_tetrahedra{16384};
    std::size_t maximum_local_nodes{65536};
    std::size_t maximum_facets{65536};
};

struct FractureFacetSide {
    unsigned tetrahedron{};
    unsigned opposite_local_vertex{};
    // Both arrays use this side's outward winding.
    std::array<unsigned, 3> original_nodes{};
    std::array<unsigned, 3> local_nodes{};
};

struct FractureFacetPair {
    FractureFacetSide side_a;
    FractureFacetSide side_b;
    // For each side_a entry, gives the index of the same original vertex in side_b.
    std::array<unsigned, 3> side_b_index_for_side_a{};
    Vec3 reference_normal_a{};
    double reference_area_m2{};
};

struct FractureTetInfo {
    double reference_volume_m3{};
    double mass_kg{};
};

struct FractureTopology {
    // Each tetrahedron owns four nodes. Materials and component constraints are
    // copied from the source definition, while mass stays rho*volume/4 per copy.
    PatchDefinition duplicated_definition;
    std::vector<unsigned> local_to_original_node;
    std::vector<double> local_nodal_masses_kg;
    std::vector<FractureTetInfo> tetrahedra;
    std::vector<FractureFacetPair> internal_facets;
    std::vector<FractureFacetSide> original_exterior_faces;
    double reference_volume_m3{};
    double mass_kg{};
};

struct FractureSeparationLimits {
    std::uint64_t maximum_adjacency_visits{262144};
    std::size_t maximum_components{16384};
    std::size_t maximum_newly_exposed_faces{65536};
};

struct FractureSeparation {
    std::vector<unsigned> component_by_tetrahedron;
    // Components and their tetrahedra are ordered by the smallest tetrahedron id.
    std::vector<std::vector<unsigned>> components;
    // Two outward sides for every explicitly separated internal facet.
    std::vector<FractureFacetSide> newly_exposed_faces;
    std::uint64_t adjacency_visits{};
};

// Compiles connectivity only. It does not select failed facets or implement a
// knife/cutting law. The duplicated definition is a future separated-domain
// representation; SmallStrainPatch currently rejects its coincident node copies.
// SmallStrainPatch is also a small-strain model and cannot represent freely flying,
// finite-rotation fragments after separation.
[[nodiscard]] FractureTopology compileFractureTopology(const PatchDefinition &definition,
                                                       const FractureTopologyLimits &limits = {});

// A true flag removes only that accepted internal facet bond. Geometry alone never
// severs a bond. Failure throws without mutating topology or caller-owned flags.
[[nodiscard]] FractureSeparation
evaluateAcceptedSeparations(const FractureTopology &topology,
                            const std::vector<bool> &accepted_facet_separations,
                            const FractureSeparationLimits &limits = {});

} // namespace banjo
