#pragma once

#include <compare>
#include <cstddef>
#include <cstdint>
#include <type_traits>

namespace banjo {

// Symmetric tensor with physical tensor shear components: xy is epsilon_xy,
// not engineering shear gamma_xy. Scalar order is xx, yy, zz, xy, yz, zx.
struct SymmetricTensor3 {
    double xx{}, yy{}, zz{}, xy{}, yz{}, zx{};

    auto operator<=>(const SymmetricTensor3 &) const = default;
};

enum class ContinuumConstitutiveFamily : std::uint8_t {
    SmallStrainIsotropicJ2,
    BrittleDamage,
    Orthotropic,
};

// SI material-point parameters. maximum_total_strain_norm is a declared
// Frobenius-norm validity limit for this small-strain reference.
struct J2Material {
    ContinuumConstitutiveFamily family{
        ContinuumConstitutiveFamily::SmallStrainIsotropicJ2};
    double young_modulus_pa{};
    double poisson_ratio{};
    double initial_yield_stress_pa{};
    double isotropic_hardening_modulus_pa{};
    double maximum_total_strain_norm{};
};

// Compact persistent material-point state. The stable scalar field order is:
// total strain [xx yy zz xy yz zx], plastic strain [xx yy zz xy yz zx],
// equivalent plastic strain, cumulative plastic dissipation [J/m^3].
// Stress is intentionally reconstructed from material + (total-plastic)
// strain rather than persisted redundantly. No field may reset on reload.
struct J2State {
    SymmetricTensor3 total_strain;
    SymmetricTensor3 plastic_strain;
    double equivalent_plastic_strain{};
    double plastic_dissipation_j_m3{};

    auto operator<=>(const J2State &) const = default;
};

inline constexpr std::size_t kJ2StateScalarCount = 14;
static_assert(sizeof(SymmetricTensor3) == 6 * sizeof(double));
static_assert(sizeof(J2State) == kJ2StateScalarCount * sizeof(double));
static_assert(std::is_standard_layout_v<J2State>);
static_assert(std::is_trivially_copyable_v<J2State>);

struct J2EnergyDensity {
    double elastic_free_energy_j_m3{};
    double isotropic_hardening_free_energy_j_m3{};
    double plastic_dissipation_j_m3{};

    [[nodiscard]] double storedFreeEnergyJPerM3() const {
        return elastic_free_energy_j_m3 +
               isotropic_hardening_free_energy_j_m3;
    }
};

struct J2Update {
    J2State state;
    SymmetricTensor3 stress_pa;
    SymmetricTensor3 trial_stress_pa;
    SymmetricTensor3 plastic_strain_increment;
    bool yielded{};
    double trial_equivalent_stress_pa{};
    double yield_stress_before_pa{};
    double yield_stress_after_pa{};
    double equivalent_plastic_strain_increment{};
    // Exact integral of the linear yield stress over the returned equivalent
    // plastic-strain increment. This is an internal constitutive partition,
    // not a measurement of external work.
    double constitutive_plastic_work_j_m3{};
    double hardening_free_energy_increment_j_m3{};
    double plastic_dissipation_increment_j_m3{};
    double stored_free_energy_increment_j_m3{};
    // sigma_(n+1):Delta epsilon. This backward-Euler end-stress quadrature is
    // not asserted to equal actual external work. Its excess over stored
    // energy plus physical dissipation is reported separately.
    double backward_euler_stress_work_j_m3{};
    double backward_euler_work_excess_j_m3{};
};

[[nodiscard]] double trace(const SymmetricTensor3 &tensor);
[[nodiscard]] SymmetricTensor3 deviatoric(const SymmetricTensor3 &tensor);
[[nodiscard]] double doubleContract(
    const SymmetricTensor3 &first, const SymmetricTensor3 &second);
[[nodiscard]] double frobeniusNorm(const SymmetricTensor3 &tensor);
[[nodiscard]] double vonMisesEquivalentStressPa(
    const SymmetricTensor3 &stress_pa);

// Throws before publishing any state when material/state/increment is invalid.
// The backward-Euler radial return is a quasistatic small-strain isotropic
// material-point reference. It contains no contact, fracture, geometry, dent
// shape, rate, temperature, finite-strain, or anisotropic wood law.
void validateJ2Material(const J2Material &material);
void validateJ2State(const J2Material &material, const J2State &state);
[[nodiscard]] SymmetricTensor3 reconstructJ2StressPa(
    const J2Material &material, const J2State &state);
[[nodiscard]] J2EnergyDensity j2EnergyDensity(
    const J2Material &material, const J2State &state);
[[nodiscard]] J2Update integrateJ2StrainIncrement(
    const J2Material &material,
    const J2State &state,
    const SymmetricTensor3 &strain_increment);

} // namespace banjo
