#include "physics/SmallStrainPatch.hpp"

#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <iostream>
#include <stdexcept>
#include <string_view>
#include <vector>

namespace {
using namespace banjo;

void check(bool condition, std::string_view message) {
    if (!condition) throw std::runtime_error(std::string(message));
}

SmallStrainLaw illustrativeJ2() {
    SmallStrainLaw law;
    law.kind = SmallStrainLawKind::J2Plastic;
    law.j2 = {.young_modulus_pa = 211.e9,
              .poisson_ratio = .29,
              .initial_yield_stress_pa = 250.e6,
              .isotropic_hardening_modulus_pa = 1.e9,
              .maximum_total_strain_norm = .05};
    law.maximum_total_strain_norm = .05;
    return law;
}

SmallStrainLaw matchedElastic() {
    return {.kind = SmallStrainLawKind::IsotropicElastic,
            .young_modulus_pa = {211.e9, 0., 0.},
            .poisson_xy_yz_zx = {.29, 0., 0.},
            .maximum_total_strain_norm = .05};
}

PatchDefinition supportedBrick(const SmallStrainLaw &law) {
    auto definition = makeTetrahedralBrick({1., 1., 1.}, {1, 1, 1}, {law, 7870.});
    for (std::size_t i = 0; i < definition.reference_positions_m.size(); ++i) {
        const Vec3 p = definition.reference_positions_m[i];
        if (p.y == 0.) definition.fixed_components[i][1] = true;
        if (p.x == -.5 && p.y == 0. && p.z == -.5) {
            definition.fixed_components[i][0] = true;
            definition.fixed_components[i][2] = true;
        }
        if (p.x == .5 && p.y == 0. && p.z == -.5)
            definition.fixed_components[i][2] = true;
    }
    return definition;
}

double triangleArea(Vec3 a, Vec3 b, Vec3 c) {
    return .5 * length(cross(b - a, c - a));
}

PatchLoad traction(const SmallStrainPatch &patch, double stress_pa) {
    const auto &reference = patch.definition().reference_positions_m;
    PatchLoad load{std::vector<Vec3>(reference.size()), std::vector<Vec3>(reference.size())};
    double area = 0.;
    for (const auto &face : patch.boundaryTriangles()) {
        if (reference[face[0]].y != 1. || reference[face[1]].y != 1. ||
            reference[face[2]].y != 1.)
            continue;
        const double face_area = triangleArea(reference[face[0]], reference[face[1]],
                                              reference[face[2]]);
        area += face_area;
        for (unsigned node : face)
            load.nodal_forces_n[node].y += stress_pa * face_area / 3.;
    }
    check(std::abs(area - 1.) < 1.e-14, "loaded boundary area mismatch");
    return load;
}

PatchSolveOptions options() {
    PatchSolveOptions result;
    result.maximum_newton_iterations = 50;
    result.maximum_cg_iterations = 2048;
    result.maximum_element_visits = 4000000;
    result.relative_force_tolerance = 2.e-10;
    result.absolute_force_tolerance_n = 1.e-4;
    return result;
}

struct CycleResult {
    PatchSolveResult unloaded;
    double maximum_displacement_m{};
    double maximum_equivalent_plastic_strain{};
    double maximum_plastic_strain_norm{};
};

CycleResult loadAndUnload(SmallStrainPatch &patch) {
    constexpr unsigned increments = 40;
    // Under monotone uniaxial stress control, (270-250) MPa / 1 GPa gives
    // approximately .02 accumulated plastic strain. Including elastic strain
    // remains comfortably inside the law's declared .05 small-strain domain.
    constexpr double peak_stress_pa = 270.e6;
    for (unsigned step = 1; step <= increments; ++step) {
        const auto result = patch.solveLoad(
            traction(patch, peak_stress_pa * step / increments), options());
        check(result.accepted, "incremental traction loading did not converge");
    }
    PatchSolveResult result;
    for (unsigned step = increments; step-- > 0;) {
        result = patch.solveLoad(
            traction(patch, peak_stress_pa * step / increments), options());
        check(result.accepted, "incremental zero-load return did not converge");
    }
    check(result.applied_force_n.x == 0. && result.applied_force_n.y == 0. &&
              result.applied_force_n.z == 0.,
          "final accepted endpoint must have zero external load");
    check(result.free_force_residual_n <= result.force_tolerance_n,
          "unloaded endpoint must satisfy the declared equilibrium tolerance");

    CycleResult cycle{.unloaded = result};
    for (const Vec3 displacement : patch.state().displacements_m)
        cycle.maximum_displacement_m =
            std::max(cycle.maximum_displacement_m, length(displacement));
    for (const J2State &point : patch.state().material_points) {
        cycle.maximum_equivalent_plastic_strain =
            std::max(cycle.maximum_equivalent_plastic_strain,
                     point.equivalent_plastic_strain);
        cycle.maximum_plastic_strain_norm =
            std::max(cycle.maximum_plastic_strain_norm,
                     frobeniusNorm(point.plastic_strain));
    }
    return cycle;
}

} // namespace

int main() {
    try {
        SmallStrainPatch plastic(supportedBrick(illustrativeJ2()));
        SmallStrainPatch elastic(supportedBrick(matchedElastic()));
        const CycleResult plastic_cycle = loadAndUnload(plastic);
        const CycleResult elastic_cycle = loadAndUnload(elastic);

        check(plastic_cycle.maximum_displacement_m > 1.e-5,
              "J2 zero-load equilibrium must retain a residual displacement");
        check(plastic_cycle.maximum_equivalent_plastic_strain > 0. &&
                  plastic_cycle.maximum_plastic_strain_norm > 0. &&
                  plastic_cycle.unloaded.plastic_dissipation_j > 0.,
              "J2 unload must retain plastic tensor history and dissipation");
        check(elastic_cycle.maximum_displacement_m < 1.e-12,
              "matched elastic control must return to its reference geometry");
        check(elastic_cycle.maximum_equivalent_plastic_strain == 0. &&
                  elastic_cycle.unloaded.plastic_dissipation_j == 0.,
              "elastic control cannot retain plastic history or dissipation");
        check(std::abs(elastic.state().accumulated_trapezoidal_external_work_j) < 1.e-3,
              "matched elastic cycle must close trapezoidal external work");
        const double plastic_energy_partition =
            plastic_cycle.unloaded.stored_free_energy_j +
            plastic_cycle.unloaded.plastic_dissipation_j;
        check(std::abs(plastic.state().accumulated_trapezoidal_external_work_j -
                       plastic_energy_partition) <= 2.e-4 * plastic_energy_partition,
              "refined load cycle must close stored-plus-dissipated trapezoidal work");

        std::cout << "[INFO] fixture=illustrative_uncalibrated_j2"
                  << " residual_displacement_m=" << plastic_cycle.maximum_displacement_m
                  << " free_force_residual_n=" << plastic_cycle.unloaded.free_force_residual_n
                  << " force_tolerance_n=" << plastic_cycle.unloaded.force_tolerance_n
                  << " max_equivalent_plastic_strain="
                  << plastic_cycle.maximum_equivalent_plastic_strain
                  << " max_plastic_strain_norm="
                  << plastic_cycle.maximum_plastic_strain_norm
                  << " stored_energy_j=" << plastic_cycle.unloaded.stored_free_energy_j
                  << " plastic_dissipation_j="
                  << plastic_cycle.unloaded.plastic_dissipation_j
                  << " accumulated_trapezoidal_work_j="
                  << plastic.state().accumulated_trapezoidal_external_work_j
                  << " accumulated_backward_euler_work_j="
                  << plastic.state().accumulated_backward_euler_external_work_j
                  << " elastic_residual_displacement_m="
                  << elastic_cycle.maximum_displacement_m << '\n';
        return EXIT_SUCCESS;
    } catch (const std::exception &error) {
        std::cerr << "[FAIL] " << error.what() << '\n';
        return EXIT_FAILURE;
    }
}
