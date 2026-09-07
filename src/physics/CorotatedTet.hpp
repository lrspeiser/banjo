#pragma once

#include "core/Math.hpp"

#include <array>

namespace banjo {

// Optional isotropic finite-rotation elastic law. Parameters are SI Lamé
// moduli; no material name selects this model. The potential density is
//   mu ||F-R||_F^2 + lambda/2 (tr(R^T F)-3)^2,
// where R is the proper polar rotation. This is an elastic corotated model,
// not a fracture, plasticity, or calibrated glass law.
struct CorotatedTetLaw {
    double shear_modulus_pa{};
    double lame_lambda_pa{};
    double density_kg_m3{};
    double minimum_deformation_jacobian{1.e-6};
    double maximum_deformation_gradient_norm{10.};
    unsigned maximum_polar_iterations{32};
    double polar_tolerance{1.e-12};
};

struct CorotatedTetEvaluation {
    Mat3 deformation_gradient;
    Mat3 rotation;
    Mat3 first_piola_stress_pa;
    // Gradient of stored energy with respect to each current vertex position.
    // A dynamics integrator applies its negative as the physical elastic force.
    std::array<Vec3, 4> internal_forces_n{};
    std::array<double, 4> nodal_masses_kg{};
    double reference_volume_m3{};
    double mass_kg{};
    double stored_energy_j{};
    unsigned polar_iterations{};
};

// Fixed-reference tetrahedral evaluation. Both reference and current
// tetrahedra must retain positive nonsingular orientation and remain inside the
// declared deformation bound. The result is objective under superposed rigid
// rotation. It does not rotate CohesiveFacet's fixed reference frame and does
// not add fragment self-contact; those remain caller-owned coupling gaps.
[[nodiscard]] CorotatedTetEvaluation evaluateCorotatedTet(
    const CorotatedTetLaw &law,
    const std::array<Vec3, 4> &reference_positions_m,
    const std::array<Vec3, 4> &current_positions_m);

} // namespace banjo
