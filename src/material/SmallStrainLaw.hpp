#pragma once

#include "material/Plasticity.hpp"

#include <array>
#include <cstdint>

namespace banjo {

enum class SmallStrainLawKind : std::uint8_t {
    IsotropicElastic,
    OrthotropicElastic,
    J2Plastic,
};

// SI small-strain material-point law in fixed world/material-aligned axes.
//
// IsotropicElastic uses young_modulus_pa[0], poisson_xy_yz_zx[0], and
// maximum_total_strain_norm. The remaining entries are optional aliases: zero
// means unspecified and a nonzero value must match the derived isotropic value.
// OrthotropicElastic uses every common array entry. poisson_xy is minus the y
// strain divided by x strain under uniaxial x stress; yz and zx follow the same
// first-axis loading convention. Reciprocal ratios are derived from compliance
// symmetry. J2Plastic uses j2; nonzero common aliases must agree with j2.
//
// This adapter is a quasistatic material-point reference. It does not provide
// finite-strain kinematics, rotations of material axes, contact, fracture,
// geometry, dents, or calibrated wood/metal behavior.
struct SmallStrainLaw {
    SmallStrainLawKind kind{SmallStrainLawKind::IsotropicElastic};
    J2Material j2;
    std::array<double, 3> young_modulus_pa{};
    std::array<double, 3> poisson_xy_yz_zx{};
    std::array<double, 3> shear_xy_yz_zx_pa{};
    double maximum_total_strain_norm{};
};

struct SmallStrainResponse {
    J2State state;
    SymmetricTensor3 stress_pa;
    // Columns are d(stress)/d(xx,yy,zz,xy,yz,zx), where the shear entries are
    // physical tensor components. The represented operator is self-adjoint
    // under doubleContract(), whose shear weights are two; its raw 6x6 array
    // need not be symmetric under an unweighted Euclidean dot product.
    std::array<SymmetricTensor3, 6> tangent_columns;
    // Current stored elastic plus hardening free energy density.
    double stored_free_energy_j_m3{};
    // Current cumulative physical plastic dissipation density.
    double plastic_dissipation_j_m3{};
    // Incremental end-stress backward-Euler quadrature excess. This is not a
    // measurement of external work.
    double backward_euler_work_excess_j_m3{};
    bool yielded{};
};

// Throws on invalid active parameters, inconsistent aliases, non-SPD
// orthotropic compliance, or values outside the declared small-strain range.
void validateSmallStrainLaw(const SmallStrainLaw &law);

// Evaluates an absolute total strain transactionally from prior persistent
// state. Elastic laws require zero plastic history. For J2, a zero increment at
// a state on the yield surface takes the elastic trial branch; the returned
// elastic tangent is the documented one-sided derivative for that point.
[[nodiscard]] SmallStrainResponse evaluateSmallStrain(
    const SmallStrainLaw &law,
    const J2State &prior,
    const SymmetricTensor3 &absolute_total_strain);

[[nodiscard]] SymmetricTensor3 applySmallStrainTangent(
    const SmallStrainResponse &response,
    const SymmetricTensor3 &direction);

} // namespace banjo
