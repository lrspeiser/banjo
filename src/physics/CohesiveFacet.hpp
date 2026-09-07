#pragma once

#include "core/Math.hpp"
#include "physics/CohesiveInterface.hpp"

#include <array>

namespace banjo {

// Three-point integration of a cohesive law over a flat triangular interface.
// Kinematics are small-displacement in the fixed reference frame. With a
// positive tangential stiffness, the effective opening is
// sqrt(<gn>_+^2 + kt/kn * |gt|^2). Thus the undamaged potential is
// (kn*<gn>_+^2 + kt*|gt|^2)/2, and the declared strength and Gc govern the
// shared effective-opening history. Zero kt retains mode-I-only behavior.
struct CohesiveFacetLaw {
    double stiffness_pa_per_m{};
    double strength_pa{};
    double fracture_energy_j_m2{};
    double compression_stiffness_pa_per_m{};
    double tangential_stiffness_pa_per_m{};
};

struct CohesiveFacetState {
    std::array<CohesiveInterfaceState, 3> integration_points{};
    std::array<Vec3, 3> relative_displacement_m{};
};

struct CohesiveFacetEvaluation {
    CohesiveFacetState state;
    std::array<CohesiveInterfaceResponse, 3> integration_points{};
    std::array<Vec3, 3> traction_pa{};
    // Endpoint forces for equations of motion. Side A and side B are equal and
    // opposite in total and are distributed with triangle shape functions.
    std::array<Vec3, 3> forces_on_a_n{};
    std::array<Vec3, 3> forces_on_b_n{};
    // Algebraic discrete-gradient forces whose dot product with this increment's
    // nodal displacement equals minus opening_work_j. They are a work diagnostic
    // and optional energy-method input, not evidence that endpoint-force time
    // integration conserves energy. A dynamics caller using forces_on_* must
    // retain its own timestep work/error acceptance gate.
    std::array<Vec3, 3> work_forces_on_a_n{};
    std::array<Vec3, 3> work_forces_on_b_n{};
    Vec3 resultant_on_a_n{};
    Vec3 reference_moment_on_a_n_m{};
    double area_m2{};
    double stored_energy_j{};
    double dissipated_energy_j{};
    double dissipated_increment_j{};
    double opening_work_j{};
    double balance_residual_j{};
    unsigned separated_integration_points{};
};

// Pure candidate evaluation: prior is unchanged. reference_triangle_m is the
// coincident interface geometry, wound so its normal points from side A to B.
// Displacements are absolute from that common reference configuration.
[[nodiscard]] CohesiveFacetEvaluation
advanceCohesiveFacet(const CohesiveFacetLaw &law, const std::array<Vec3, 3> &reference_triangle_m,
                     const std::array<Vec3, 3> &displacements_a_m,
                     const std::array<Vec3, 3> &displacements_b_m,
                     const CohesiveFacetState &prior = {});

} // namespace banjo
