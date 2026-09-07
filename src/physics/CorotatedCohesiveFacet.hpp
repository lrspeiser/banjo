#pragma once

#include "physics/CohesiveFacet.hpp"

#include <array>
#include <cstdint>

namespace banjo {

struct CorotatedCohesiveFacetState {
    std::array<CohesiveInterfaceState, 3> integration_points{};
};

struct CorotatedCohesiveFacetOptions {
    std::uint64_t maximum_derivative_evaluations{1};
};

struct CorotatedCohesiveFacetEvaluation {
    CorotatedCohesiveFacetState state;
    std::array<CohesiveInterfaceResponse, 3> integration_points{};
    std::array<Vec3, 3> forces_on_a_n{};
    std::array<Vec3, 3> forces_on_b_n{};
    Vec3 resultant_n{};
    Vec3 current_moment_n_m{};
    double reference_area_m2{};
    double stored_energy_j{};
    double cohesive_stored_energy_j{};
    double compression_stored_energy_j{};
    double fracture_dissipation_j{};
    double fracture_dissipation_increment_j{};
    unsigned separated_integration_points{};
    std::uint64_t derivative_evaluations{};
};

// Objective finite-rotation triangular interface evaluation. The current
// midsurface defines the rotating normal/tangent frame, while reference area
// fixes SI force and Gc*area fracture work. Endpoint forces are the forward-mode
// gradient of the frozen-history current potential, including frame variation.
// This is an interface law only: no blade contact, bulk finite-strain law,
// fragment dynamics, or calibrated material behavior is implied.
[[nodiscard]] CorotatedCohesiveFacetEvaluation advanceCorotatedCohesiveFacet(
    const CohesiveFacetLaw &law,
    const std::array<Vec3, 3> &reference_triangle_m,
    const std::array<Vec3, 3> &current_a_m,
    const std::array<Vec3, 3> &current_b_m,
    const CorotatedCohesiveFacetState &prior = {},
    const CorotatedCohesiveFacetOptions &options = {});

} // namespace banjo
