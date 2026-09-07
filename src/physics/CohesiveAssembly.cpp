#include "physics/CohesiveAssembly.hpp"

#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace banjo {
namespace {

void require(bool condition, const char *message) {
    if (!condition)
        throw std::invalid_argument(message);
}

bool finite(Vec3 value) {
    return std::isfinite(value.x) && std::isfinite(value.y) && std::isfinite(value.z);
}

} // namespace

CohesiveAssemblyEvaluation evaluateCohesiveAssembly(const FractureTopology &topology,
                                                    const std::vector<Vec3> &displacements,
                                                    const std::vector<CohesiveFacetState> &prior,
                                                    const std::vector<CohesiveFacetLaw> &laws,
                                                    const CohesiveAssemblyLimits &limits) {
    require(limits.maximum_local_nodes > 0 && limits.maximum_local_nodes <= 65536 &&
                limits.maximum_facets > 0 && limits.maximum_facets <= 65536 &&
                limits.maximum_facet_evaluations > 0 && limits.maximum_facet_evaluations <= 65536 &&
                limits.maximum_nodal_scatters > 0 && limits.maximum_nodal_scatters <= 393216,
            "Invalid cohesive assembly work budget");
    const std::size_t node_count = topology.duplicated_definition.reference_positions_m.size();
    const std::size_t facet_count = topology.internal_facets.size();
    require(node_count > 0 && node_count <= limits.maximum_local_nodes,
            "Cohesive assembly local-node budget exceeded");
    require(facet_count <= limits.maximum_facets, "Cohesive assembly facet budget exceeded");
    require(facet_count <= limits.maximum_facet_evaluations,
            "Cohesive assembly facet-evaluation budget exhausted");
    require(facet_count <= limits.maximum_nodal_scatters / 6,
            "Cohesive assembly nodal-scatter budget exhausted");
    require(displacements.size() == node_count,
            "Cohesive assembly displacement count differs from local nodes");
    require(topology.local_to_original_node.size() == node_count &&
                topology.local_nodal_masses_kg.size() == node_count,
            "Invalid cohesive assembly local-node topology");
    require(prior.size() == facet_count, "Cohesive assembly history count differs from facets");
    require(laws.size() == facet_count, "Cohesive assembly law count differs from facets");
    for (const Vec3 value : displacements)
        require(finite(value), "Cohesive assembly displacement must be finite");

    CohesiveAssemblyEvaluation out;
    out.nodal_forces_n.resize(node_count);
    out.work_conjugate_nodal_forces_n.resize(node_count);
    out.candidate_facet_states.reserve(facet_count);
    out.separated_integration_points.reserve(facet_count);
    out.fully_separated_facets.reserve(facet_count);
    for (std::size_t facet_id = 0; facet_id < facet_count; ++facet_id) {
        const auto &facet = topology.internal_facets[facet_id];
        require(facet.side_a.tetrahedron < topology.duplicated_definition.elements.size() &&
                    facet.side_b.tetrahedron < topology.duplicated_definition.elements.size() &&
                    facet.side_a.tetrahedron != facet.side_b.tetrahedron,
                "Invalid cohesive facet tetrahedron adjacency");
        const auto validate_side = [&](const FractureFacetSide &side) {
            require(side.opposite_local_vertex < 4, "Invalid cohesive facet opposite local vertex");
            const auto &tet = topology.duplicated_definition.elements[side.tetrahedron];
            std::array<bool, 4> seen{};
            for (unsigned i = 0; i < 3; ++i) {
                const auto found =
                    std::find(tet.nodes.begin(), tet.nodes.end(), side.local_nodes[i]);
                require(found != tet.nodes.end(),
                        "Cohesive facet side node is outside its tetrahedron");
                const unsigned local = static_cast<unsigned>(found - tet.nodes.begin());
                require(local != side.opposite_local_vertex && !seen[local],
                        "Cohesive facet side has invalid or repeated local node");
                seen[local] = true;
                require(side.local_nodes[i] < topology.local_to_original_node.size() &&
                            topology.local_to_original_node[side.local_nodes[i]] ==
                                side.original_nodes[i],
                        "Cohesive facet side original-node mapping mismatch");
            }
            for (unsigned local = 0; local < 4; ++local)
                require(seen[local] == (local != side.opposite_local_vertex),
                        "Cohesive facet side does not match its tetrahedron face");
        };
        validate_side(facet.side_a);
        validate_side(facet.side_b);
        std::array<Vec3, 3> reference{};
        std::array<Vec3, 3> displacement_a{};
        std::array<Vec3, 3> displacement_b{};
        std::array<unsigned, 3> local_b{};
        std::array<bool, 3> used_b_indices{};
        for (unsigned i = 0; i < 3; ++i) {
            const unsigned a = facet.side_a.local_nodes[i];
            require(a < node_count, "Invalid cohesive facet side-A local node");
            const unsigned b_index = facet.side_b_index_for_side_a[i];
            require(b_index < 3 && !used_b_indices[b_index],
                    "Invalid cohesive facet vertex correspondence");
            used_b_indices[b_index] = true;
            const unsigned b = facet.side_b.local_nodes[b_index];
            require(b < node_count &&
                        topology.local_to_original_node[a] == topology.local_to_original_node[b],
                    "Invalid cohesive facet corresponding local node");
            reference[i] = topology.duplicated_definition.reference_positions_m[a];
            require(length(reference[i] -
                           topology.duplicated_definition.reference_positions_m[b]) == 0.,
                    "Cohesive facet copies do not share exact reference geometry");
            displacement_a[i] = displacements[a];
            displacement_b[i] = displacements[b];
            local_b[i] = b;
        }
        const auto evaluation = advanceCohesiveFacet(laws[facet_id], reference, displacement_a,
                                                     displacement_b, prior[facet_id]);
        ++out.facet_evaluations;
        out.candidate_facet_states.push_back(evaluation.state);
        out.separated_integration_points.push_back(evaluation.separated_integration_points);
        out.fully_separated_facets.push_back(evaluation.separated_integration_points == 3);
        out.stored_energy_j += evaluation.stored_energy_j;
        out.fracture_dissipation_j += evaluation.dissipated_energy_j;
        out.fracture_dissipation_increment_j += evaluation.dissipated_increment_j;
        out.opening_work_j += evaluation.opening_work_j;
        out.balance_residual_j += evaluation.balance_residual_j;
        for (unsigned i = 0; i < 3; ++i) {
            const unsigned a = facet.side_a.local_nodes[i];
            const unsigned b = local_b[i];
            out.nodal_forces_n[a] += evaluation.forces_on_a_n[i];
            out.nodal_forces_n[b] += evaluation.forces_on_b_n[i];
            out.work_conjugate_nodal_forces_n[a] += evaluation.work_forces_on_a_n[i];
            out.work_conjugate_nodal_forces_n[b] += evaluation.work_forces_on_b_n[i];
            out.nodal_scatters += 2;
        }
    }
    out.separation =
        evaluateAcceptedSeparations(topology, out.fully_separated_facets, limits.separation);
    for (std::size_t i = 0; i < node_count; ++i) {
        require(finite(out.nodal_forces_n[i]) && finite(out.work_conjugate_nodal_forces_n[i]),
                "Cohesive assembly force exceeds numeric range");
        out.resultant_n += out.nodal_forces_n[i];
        out.reference_moment_n_m +=
            cross(topology.duplicated_definition.reference_positions_m[i], out.nodal_forces_n[i]);
    }
    require(finite(out.resultant_n) && finite(out.reference_moment_n_m) &&
                std::isfinite(out.stored_energy_j) && std::isfinite(out.fracture_dissipation_j) &&
                std::isfinite(out.fracture_dissipation_increment_j) &&
                std::isfinite(out.opening_work_j) && std::isfinite(out.balance_residual_j),
            "Cohesive assembly ledger exceeds numeric range");
    return out;
}

} // namespace banjo
