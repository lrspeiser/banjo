#include "physics/FractureTopology.hpp"

#include <algorithm>
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

template <class Function> void rejects(Function &&function, std::string_view message) {
    bool threw = false;
    try {
        function();
    } catch (const std::invalid_argument &) {
        threw = true;
    }
    require(threw, message);
}

SmallStrainLaw elastic() {
    return {
        .kind = SmallStrainLawKind::IsotropicElastic,
        .young_modulus_pa = {1.e6, 0., 0.},
        .poisson_xy_yz_zx = {.25, 0., 0.},
        .maximum_total_strain_norm = .05,
    };
}

PatchDefinition twoTets() {
    PatchDefinition definition;
    definition.reference_positions_m = {
        {0., 0., 0.}, {1., 0., 0.}, {0., 1., 0.}, {0., 0., 1.}, {0., 0., -1.}};
    definition.elements = {{{0, 1, 2, 3}, 0}, {{0, 2, 1, 4}, 0}};
    definition.materials = {{elastic(), 1200.}};
    definition.fixed_components.resize(5);
    definition.fixed_components[0] = {true, false, true};
    return definition;
}

void two_tetrahedra_compile_with_exact_correspondence() {
    const auto source = twoTets();
    const auto topology = compileFractureTopology(source);
    require(topology.tetrahedra.size() == 2, "two tetrahedra retained");
    require(topology.duplicated_definition.reference_positions_m.size() == 8,
            "four local nodes allocated per tetrahedron");
    require(topology.local_to_original_node == std::vector<unsigned>({0, 1, 2, 3, 0, 2, 1, 4}),
            "deterministic tet-local node mapping");
    require(topology.duplicated_definition.fixed_components[0] == source.fixed_components[0] &&
                topology.duplicated_definition.fixed_components[4] == source.fixed_components[0],
            "constraints copied to every local occurrence");
    require(topology.internal_facets.size() == 1, "one internal facet pair");
    require(topology.original_exterior_faces.size() == 6, "six original exterior faces");

    const auto &facet = topology.internal_facets.front();
    near(facet.reference_area_m2, .5, 1.e-14, "shared reference area");
    require(facet.side_a.tetrahedron == 0 && facet.side_b.tetrahedron == 1,
            "facet sides follow deterministic tetrahedron order");
    const Vec3 a0 = source.reference_positions_m[facet.side_a.original_nodes[0]];
    const Vec3 a1 = source.reference_positions_m[facet.side_a.original_nodes[1]];
    const Vec3 a2 = source.reference_positions_m[facet.side_a.original_nodes[2]];
    require(dot(cross(a1 - a0, a2 - a0), facet.reference_normal_a) > 0.,
            "stored normal follows side A winding");
    for (unsigned i = 0; i < 3; ++i) {
        const unsigned j = facet.side_b_index_for_side_a[i];
        require(j < 3 && facet.side_a.original_nodes[i] == facet.side_b.original_nodes[j],
                "facet correspondence names the identical source vertex");
    }
    const Vec3 b0 = source.reference_positions_m[facet.side_b.original_nodes[0]];
    const Vec3 b1 = source.reference_positions_m[facet.side_b.original_nodes[1]];
    const Vec3 b2 = source.reference_positions_m[facet.side_b.original_nodes[2]];
    require(dot(cross(a1 - a0, a2 - a0), cross(b1 - b0, b2 - b0)) < 0.,
            "paired facet windings point outward from opposite tetrahedra");
}

void physical_mass_and_volume_survive_duplication() {
    constexpr double density = 1375.;
    const Vec3 dimensions{.08, .02, .06};
    auto source = makeTetrahedralBrick(dimensions, {2, 2, 3}, {elastic(), density});
    for (std::size_t i = 0; i < source.fixed_components.size(); ++i)
        if (source.reference_positions_m[i].y == 0.)
            source.fixed_components[i] = {true, true, true};
    const auto topology = compileFractureTopology(source);
    const double expected_volume = dimensions.x * dimensions.y * dimensions.z;
    near(topology.reference_volume_m3, expected_volume, expected_volume * 1.e-13,
         "structured-brick volume conserved");
    near(topology.mass_kg, density * expected_volume, density * expected_volume * 1.e-13,
         "structured-brick mass conserved");
    double local_mass = 0.;
    for (double mass : topology.local_nodal_masses_kg)
        local_mass += mass;
    near(local_mass, topology.mass_kg, topology.mass_kg * 1.e-13,
         "tet-local lumped masses sum to physical mass");
    for (std::size_t tet = 0; tet < topology.tetrahedra.size(); ++tet) {
        double sum = 0.;
        for (unsigned local = 0; local < 4; ++local)
            sum += topology.local_nodal_masses_kg[tet * 4 + local];
        near(sum, topology.tetrahedra[tet].mass_kg, topology.mass_kg * 1.e-14,
             "each tetrahedron owns exactly rho-volume mass");
    }
    require(topology.duplicated_definition.materials.size() == source.materials.size(),
            "material descriptors copied");
}

void accepted_flags_alone_change_connectivity_and_exposure() {
    const auto topology = compileFractureTopology(twoTets());
    const auto intact = evaluateAcceptedSeparations(topology, {false});
    require(intact.components.size() == 1 && intact.components[0] == std::vector<unsigned>({0, 1}),
            "intact neighboring tetrahedra form one component");
    require(intact.newly_exposed_faces.empty(), "intact internal face is not exposed");

    const auto separated = evaluateAcceptedSeparations(topology, {true});
    require(separated.components.size() == 2 &&
                separated.components[0] == std::vector<unsigned>({0}) &&
                separated.components[1] == std::vector<unsigned>({1}),
            "accepted shared-facet failure separates two tetrahedra");
    require(separated.newly_exposed_faces.size() == 2, "both failed-facet sides exposed");
    require(separated.newly_exposed_faces[0].tetrahedron == 0 &&
                separated.newly_exposed_faces[1].tetrahedron == 1,
            "newly exposed sides preserve deterministic pair order");
}

void one_local_failure_does_not_cut_an_alternate_path() {
    const auto topology = compileFractureTopology(
        makeTetrahedralBrick({.04, .03, .02}, {1, 1, 1}, {elastic(), 900.}));
    require(topology.internal_facets.size() >= 2, "brick contains an internal adjacency path");
    std::vector<bool> accepted(topology.internal_facets.size(), false);
    accepted.front() = true;
    const auto result = evaluateAcceptedSeparations(topology, accepted);
    require(result.components.size() == 1,
            "one local face failure does not override remaining connectivity");
    require(result.newly_exposed_faces.size() == 2, "only accepted local facet exposes surfaces");
}

void invalid_meshes_and_budgets_are_rejected() {
    auto reversed = twoTets();
    std::swap(reversed.elements[0].nodes[1], reversed.elements[0].nodes[2]);
    rejects([&] { (void)compileFractureTopology(reversed); }, "negative orientation rejected");

    auto nonmanifold = twoTets();
    nonmanifold.reference_positions_m.push_back({.1, .1, 2.});
    nonmanifold.fixed_components.push_back({});
    nonmanifold.elements.push_back({{0, 1, 2, 5}, 0});
    rejects([&] { (void)compileFractureTopology(nonmanifold); }, "third incident face rejected");

    auto same_side = twoTets();
    same_side.reference_positions_m[4] = {.1, .1, .5};
    same_side.elements[1].nodes = {0, 1, 2, 4};
    rejects([&] { (void)compileFractureTopology(same_side); },
            "shared tetrahedra on same side rejected");

    const auto source = twoTets();
    auto compile_limits = FractureTopologyLimits{};
    compile_limits.maximum_local_nodes = 4;
    rejects([&] { (void)compileFractureTopology(source, compile_limits); },
            "local-node budget enforced before allocation");
    compile_limits = {};
    compile_limits.maximum_facets = 1;
    rejects([&] { (void)compileFractureTopology(source, compile_limits); },
            "unique-face budget enforced during face insertion");
    const auto topology = compileFractureTopology(source);
    auto separation_limits = FractureSeparationLimits{};
    separation_limits.maximum_newly_exposed_faces = 1;
    rejects([&] { (void)evaluateAcceptedSeparations(topology, {true}, separation_limits); },
            "exposed-face budget enforced");
    separation_limits = {};
    separation_limits.maximum_adjacency_visits = 1;
    rejects([&] { (void)evaluateAcceptedSeparations(topology, {false}, separation_limits); },
            "adjacency work budget enforced");
    rejects([&] { (void)evaluateAcceptedSeparations(topology, {}); },
            "separation flag count validated");

    auto oversized_tets = topology;
    oversized_tets.tetrahedra.resize(16385);
    oversized_tets.duplicated_definition.elements.resize(16385);
    rejects([&] { (void)evaluateAcceptedSeparations(oversized_tets, {false}); },
            "supplied topology tetrahedron hard bound enforced before traversal");
    auto oversized_facets = topology;
    oversized_facets.internal_facets.resize(65537);
    std::vector<bool> oversized_flags(65537);
    rejects([&] { (void)evaluateAcceptedSeparations(oversized_facets, oversized_flags); },
            "supplied topology facet hard bound enforced before traversal");
}

} // namespace

int main() {
    const std::vector<std::pair<std::string, std::function<void()>>> tests = {
        {"two tetrahedra compile with exact correspondence",
         two_tetrahedra_compile_with_exact_correspondence},
        {"physical mass and volume survive duplication",
         physical_mass_and_volume_survive_duplication},
        {"accepted flags alone change connectivity and exposure",
         accepted_flags_alone_change_connectivity_and_exposure},
        {"one local failure does not cut an alternate path",
         one_local_failure_does_not_cut_an_alternate_path},
        {"invalid meshes and budgets are rejected", invalid_meshes_and_budgets_are_rejected},
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
              << " fracture topology tests passed\n";
    return failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
