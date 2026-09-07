#include "physics/CohesiveAssembly.hpp"

#include <cmath>
#include <cstdlib>
#include <functional>
#include <iostream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace {
using namespace banjo;

struct TestFailure : std::runtime_error {
    using std::runtime_error::runtime_error;
};

void require(bool condition, std::string_view message) {
    if (!condition)
        throw TestFailure(std::string(message));
}

void near(double actual, double expected, double tolerance, std::string_view message) {
    if (!std::isfinite(actual) || std::abs(actual - expected) > tolerance)
        throw TestFailure(std::string(message) + ": actual=" + std::to_string(actual) +
                          " expected=" + std::to_string(expected));
}

SmallStrainLaw elastic() {
    return {
        .kind = SmallStrainLawKind::IsotropicElastic,
        .young_modulus_pa = {1.e6, 0., 0.},
        .poisson_xy_yz_zx = {.25, 0., 0.},
        .maximum_total_strain_norm = .05,
    };
}

FractureTopology twoTetTopology() {
    PatchDefinition definition;
    definition.reference_positions_m = {
        {0., 0., 0.}, {1., 0., 0.}, {0., 1., 0.}, {0., 0., 1.}, {0., 0., -1.}};
    definition.elements = {{{0, 1, 2, 3}, 0}, {{0, 2, 1, 4}, 0}};
    definition.materials = {{elastic(), 1200.}};
    definition.fixed_components.resize(5);
    return compileFractureTopology(definition);
}

CohesiveFacetLaw law(double strength = 5.e7, double gc = 10.) {
    return {
        .stiffness_pa_per_m = 5.e14,
        .strength_pa = strength,
        .fracture_energy_j_m2 = gc,
        .compression_stiffness_pa_per_m = 3.e14,
        .tangential_stiffness_pa_per_m = 2.e14,
    };
}

std::vector<Vec3> opened(const FractureTopology &topology, double opening,
                         bool one_side_node_only = false) {
    std::vector<Vec3> displacement(topology.local_to_original_node.size());
    const auto &facet = topology.internal_facets.front();
    for (unsigned i = 0; i < (one_side_node_only ? 1U : 3U); ++i) {
        const unsigned b = facet.side_b.local_nodes[facet.side_b_index_for_side_a[i]];
        displacement[b] = opening * facet.reference_normal_a;
    }
    return displacement;
}

void assembled_loading_advances_and_separates_transactionally() {
    const auto topology = twoTetTopology();
    const auto cohesive = law();
    const double failure = 2. * cohesive.fracture_energy_j_m2 / cohesive.strength_pa;
    std::vector<CohesiveFacetState> state(1);
    const auto loaded =
        evaluateCohesiveAssembly(topology, opened(topology, .55 * failure), state, {cohesive});
    require(!loaded.fully_separated_facets[0] && loaded.separation.components.size() == 1,
            "damaged but cohesive facet retains connectivity");
    require(loaded.fracture_dissipation_j > 0. && loaded.stored_energy_j > 0.,
            "local opening drives cohesive storage and damage");
    require(state[0].integration_points[0].maximum_opening_m == 0.,
            "candidate evaluation leaves caller history unchanged");

    const auto separated = evaluateCohesiveAssembly(topology, opened(topology, 1.1 * failure),
                                                    loaded.candidate_facet_states, {cohesive});
    require(separated.fully_separated_facets[0] && separated.separated_integration_points[0] == 3,
            "all quadrature failures mark the assembled facet separated");
    require(separated.separation.components.size() == 2 &&
                separated.separation.newly_exposed_faces.size() == 2,
            "full cohesive failure drives topology components and both exposed sides");
}

void partial_quadrature_failure_retains_connection() {
    const auto topology = twoTetTopology();
    const auto cohesive = law();
    const double failure = 2. * cohesive.fracture_energy_j_m2 / cohesive.strength_pa;
    const auto partial =
        evaluateCohesiveAssembly(topology, opened(topology, 2. * failure, true), {{}}, {cohesive});
    require(partial.separated_integration_points[0] == 1,
            "localized displacement can fail one quadrature history");
    require(!partial.fully_separated_facets[0] && partial.separation.components.size() == 1 &&
                partial.separation.newly_exposed_faces.empty(),
            "partial quadrature damage does not disconnect or expose the facet");
}

void force_moment_mass_and_fracture_work_close() {
    const auto topology = twoTetTopology();
    const auto cohesive = law();
    const double failure = 2. * cohesive.fracture_energy_j_m2 / cohesive.strength_pa;
    const auto result =
        evaluateCohesiveAssembly(topology, opened(topology, 1.1 * failure), {{}}, {cohesive});
    near(length(result.resultant_n), 0., 1.e-8, "assembled cohesive resultant closes");
    near(length(result.reference_moment_n_m), 0., 1.e-8,
         "assembled cohesive reference moment closes");
    near(result.fracture_dissipation_j,
         cohesive.fracture_energy_j_m2 * topology.internal_facets[0].reference_area_m2,
         cohesive.fracture_energy_j_m2 * 1.e-12, "complete fracture pays Gc times area");
    near(result.opening_work_j, result.stored_energy_j + result.fracture_dissipation_increment_j,
         cohesive.fracture_energy_j_m2 * 1.e-12, "assembly opening-work ledger closes");
    double local_mass = 0.;
    for (const double mass : topology.local_nodal_masses_kg)
        local_mass += mass;
    near(local_mass, topology.mass_kg, topology.mass_kg * 1.e-13,
         "cohesive assembly retains topology physical mass");
}

void heterogeneous_numeric_laws_are_assigned_by_facet() {
    const auto topology = compileFractureTopology(
        makeTetrahedralBrick({.04, .03, .02}, {1, 1, 1}, {elastic(), 1000.}));
    require(topology.internal_facets.size() > 1, "heterogeneous fixture has multiple facets");
    // Peak elastic work for this comparison law is 1000 J/m2, so Gc=2000
    // is admissible while keeping it substantially harder to separate.
    std::vector<CohesiveFacetLaw> laws(topology.internal_facets.size(), law(1.e9, 2000.));
    laws[0] = law(5.e7, 10.);
    const double weak_failure = 2. * laws[0].fracture_energy_j_m2 / laws[0].strength_pa;
    std::vector<Vec3> displacement(topology.local_to_original_node.size());
    const auto &target = topology.internal_facets[0];
    for (unsigned i = 0; i < 3; ++i) {
        const unsigned b = target.side_b.local_nodes[target.side_b_index_for_side_a[i]];
        displacement[b] = 1.1 * weak_failure * target.reference_normal_a;
    }
    const auto result = evaluateCohesiveAssembly(
        topology, displacement, std::vector<CohesiveFacetState>(laws.size()), laws);
    require(result.fully_separated_facets[0], "weak numeric facet law reaches failure");
    require(result.fully_separated_facets.size() == laws.size(),
            "each internal facet retains its independently assigned numeric law slot");
    require(result.fracture_dissipation_j >=
                laws[0].fracture_energy_j_m2 * target.reference_area_m2,
            "heterogeneous assembly includes target facet fracture work");
}

void late_budget_failure_preserves_caller_history() {
    const auto topology = twoTetTopology();
    const auto cohesive = law();
    std::vector<CohesiveFacetState> prior(1);
    prior[0].integration_points[0].maximum_opening_m = 1.e-8;
    const auto before = prior;
    CohesiveAssemblyLimits limits;
    limits.separation.maximum_adjacency_visits = 1;
    bool threw = false;
    try {
        (void)evaluateCohesiveAssembly(topology, opened(topology, 0.), prior, {cohesive}, limits);
    } catch (const std::invalid_argument &) {
        threw = true;
    }
    require(threw, "late connectivity budget exhaustion rejects candidate assembly");
    require(prior[0].integration_points[0].maximum_opening_m ==
                before[0].integration_points[0].maximum_opening_m,
            "late failure preserves caller-owned cohesive history");
}

void mutable_topology_facet_membership_is_validated() {
    auto topology = twoTetTopology();
    topology.internal_facets[0].side_a.local_nodes[0] =
        topology.duplicated_definition.elements[1].nodes[3];
    bool threw = false;
    try {
        (void)evaluateCohesiveAssembly(
            topology, std::vector<Vec3>(topology.local_to_original_node.size()), {{}}, {law()});
    } catch (const std::invalid_argument &) {
        threw = true;
    }
    require(threw, "public topology facet nodes must belong to their declared tetrahedron");
}

} // namespace

int main() {
    const std::vector<std::pair<std::string, std::function<void()>>> tests = {
        {"assembled loading advances and separates transactionally",
         assembled_loading_advances_and_separates_transactionally},
        {"partial quadrature failure retains connection",
         partial_quadrature_failure_retains_connection},
        {"force moment mass and fracture work close", force_moment_mass_and_fracture_work_close},
        {"heterogeneous numeric laws are assigned by facet",
         heterogeneous_numeric_laws_are_assigned_by_facet},
        {"late budget failure preserves caller history",
         late_budget_failure_preserves_caller_history},
        {"mutable topology facet membership is validated",
         mutable_topology_facet_membership_is_validated},
    };
    unsigned failures = 0;
    for (const auto &[name, test] : tests) {
        try {
            test();
            std::cout << "PASS " << name << '\n';
        } catch (const std::exception &error) {
            ++failures;
            std::cerr << "FAIL " << name << ": " << error.what() << '\n';
        }
    }
    std::cout << (tests.size() - failures) << '/' << tests.size()
              << " cohesive assembly tests passed\n";
    return failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
