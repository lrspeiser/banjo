#pragma once

#include "physics/CohesiveFacet.hpp"
#include "physics/FractureTopology.hpp"

#include <cstddef>
#include <cstdint>
#include <vector>

namespace banjo {

struct CohesiveAssemblyLimits {
    std::size_t maximum_local_nodes{65536};
    std::size_t maximum_facets{65536};
    std::uint64_t maximum_facet_evaluations{65536};
    std::uint64_t maximum_nodal_scatters{393216};
    FractureSeparationLimits separation{};
};

struct CohesiveAssemblyEvaluation {
    std::vector<Vec3> nodal_forces_n;
    std::vector<Vec3> work_conjugate_nodal_forces_n;
    std::vector<CohesiveFacetState> candidate_facet_states;
    std::vector<unsigned> separated_integration_points;
    std::vector<bool> fully_separated_facets;
    FractureSeparation separation;
    double stored_energy_j{};
    double fracture_dissipation_j{};
    double fracture_dissipation_increment_j{};
    double opening_work_j{};
    double balance_residual_j{};
    Vec3 resultant_n{};
    Vec3 reference_moment_n_m{};
    std::uint64_t facet_evaluations{};
    std::uint64_t nodal_scatters{};
};

// Pure candidate assembly. Laws and histories are assigned by internal-facet
// index; material names and geometric planes never select separation. A facet
// becomes disconnected only after all three quadrature histories have reached
// the cohesive law's failure state. Caller-owned history is never mutated.
[[nodiscard]] CohesiveAssemblyEvaluation evaluateCohesiveAssembly(
    const FractureTopology &topology, const std::vector<Vec3> &local_displacements_m,
    const std::vector<CohesiveFacetState> &prior_facet_states,
    const std::vector<CohesiveFacetLaw> &facet_laws, const CohesiveAssemblyLimits &limits = {});

} // namespace banjo
