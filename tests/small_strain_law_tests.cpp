#include "material/SmallStrainLaw.hpp"

#include <array>
#include <cmath>
#include <cstdlib>
#include <functional>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace {
using namespace banjo;

void require(bool condition, std::string_view message) {
    if (!condition) {
        throw std::runtime_error(std::string(message));
    }
}

void near(
    double actual,
    double expected,
    double tolerance,
    std::string_view message) {
    if (!std::isfinite(actual) ||
        std::abs(actual - expected) > tolerance) {
        throw std::runtime_error(
            std::string(message) + ": actual=" + std::to_string(actual) +
            " expected=" + std::to_string(expected));
    }
}

SymmetricTensor3 add(
    const SymmetricTensor3 &a, const SymmetricTensor3 &b) {
    return {a.xx + b.xx, a.yy + b.yy, a.zz + b.zz,
            a.xy + b.xy, a.yz + b.yz, a.zx + b.zx};
}

SymmetricTensor3 subtract(
    const SymmetricTensor3 &a, const SymmetricTensor3 &b) {
    return {a.xx - b.xx, a.yy - b.yy, a.zz - b.zz,
            a.xy - b.xy, a.yz - b.yz, a.zx - b.zx};
}

SymmetricTensor3 scale(const SymmetricTensor3 &a, double factor) {
    return {a.xx * factor, a.yy * factor, a.zz * factor,
            a.xy * factor, a.yz * factor, a.zx * factor};
}

SmallStrainLaw isotropicLaw() {
    constexpr double young = 210.0e9;
    constexpr double poisson = 0.29;
    const double shear = young / (2.0 * (1.0 + poisson));
    return {
        .kind = SmallStrainLawKind::IsotropicElastic,
        .young_modulus_pa = {young, young, young},
        .poisson_xy_yz_zx = {poisson, poisson, poisson},
        .shear_xy_yz_zx_pa = {shear, shear, shear},
        .maximum_total_strain_norm = 0.05,
    };
}

SmallStrainLaw orthotropicLaw() {
    return {
        .kind = SmallStrainLawKind::OrthotropicElastic,
        .young_modulus_pa = {12.0e9, 1.0e9, 0.8e9},
        .poisson_xy_yz_zx = {0.30, 0.25, 0.02},
        .shear_xy_yz_zx_pa = {0.7e9, 0.3e9, 0.4e9},
        .maximum_total_strain_norm = 0.05,
    };
}

SmallStrainLaw j2Law() {
    constexpr double young = 200.0e9;
    constexpr double poisson = 0.30;
    const double shear = young / (2.0 * (1.0 + poisson));
    const J2Material material{
        .family = ContinuumConstitutiveFamily::SmallStrainIsotropicJ2,
        .young_modulus_pa = young,
        .poisson_ratio = poisson,
        .initial_yield_stress_pa = 200.0e6,
        .isotropic_hardening_modulus_pa = 10.0e9,
        .maximum_total_strain_norm = 0.05,
    };
    return {
        .kind = SmallStrainLawKind::J2Plastic,
        .j2 = material,
        .young_modulus_pa = {young, young, young},
        .poisson_xy_yz_zx = {poisson, poisson, poisson},
        .shear_xy_yz_zx_pa = {shear, shear, shear},
        .maximum_total_strain_norm = material.maximum_total_strain_norm,
    };
}

void requireTensorNear(
    const SymmetricTensor3 &actual,
    const SymmetricTensor3 &expected,
    double absolute_tolerance,
    double relative_tolerance,
    std::string_view message) {
    const std::array<double, 6> actual_components{
        actual.xx, actual.yy, actual.zz,
        actual.xy, actual.yz, actual.zx};
    const std::array<double, 6> expected_components{
        expected.xx, expected.yy, expected.zz,
        expected.xy, expected.yz, expected.zx};
    for (std::size_t i = 0; i < actual_components.size(); ++i) {
        const double tolerance = absolute_tolerance +
            relative_tolerance * std::abs(expected_components[i]);
        near(actual_components[i], expected_components[i], tolerance, message);
    }
}

SymmetricTensor3 finiteDifference(
    const SmallStrainLaw &law,
    const J2State &prior,
    const SymmetricTensor3 &target,
    const SymmetricTensor3 &direction,
    double step) {
    const auto plus = evaluateSmallStrain(
        law, prior, add(target, scale(direction, step)));
    const auto minus = evaluateSmallStrain(
        law, prior, add(target, scale(direction, -step)));
    return scale(subtract(plus.stress_pa, minus.stress_pa), 0.5 / step);
}

void isotropicElasticAnalyticalAndDirectionalTangent() {
    const auto law = isotropicLaw();
    validateSmallStrainLaw(law);
    auto minimal_aliases = law;
    minimal_aliases.young_modulus_pa[1] = 0.0;
    minimal_aliases.young_modulus_pa[2] = 0.0;
    minimal_aliases.poisson_xy_yz_zx[1] = 0.0;
    minimal_aliases.poisson_xy_yz_zx[2] = 0.0;
    minimal_aliases.shear_xy_yz_zx_pa = {};
    validateSmallStrainLaw(minimal_aliases);
    const SymmetricTensor3 strain{
        .xx = 1.2e-3,
        .yy = -0.4e-3,
        .zz = 0.2e-3,
        .xy = 0.3e-3,
        .yz = -0.1e-3,
        .zx = 0.25e-3,
    };
    const auto response = evaluateSmallStrain(law, {}, strain);
    requireTensorNear(
        evaluateSmallStrain(minimal_aliases, {}, strain).stress_pa,
        response.stress_pa,
        0.0,
        0.0,
        "unspecified zero aliases preserve authoritative isotropic response");
    const double young = law.young_modulus_pa[0];
    const double poisson = law.poisson_xy_yz_zx[0];
    const double shear = young / (2.0 * (1.0 + poisson));
    const double lambda = young * poisson /
        ((1.0 + poisson) * (1.0 - 2.0 * poisson));
    SymmetricTensor3 expected = scale(strain, 2.0 * shear);
    expected.xx += lambda * trace(strain);
    expected.yy += lambda * trace(strain);
    expected.zz += lambda * trace(strain);
    requireTensorNear(
        response.stress_pa, expected, 1.0e-5, 1.0e-14,
        "isotropic analytical stress");
    near(
        response.stored_free_energy_j_m3,
        0.5 * doubleContract(expected, strain),
        1.0e-6,
        "isotropic stored energy");
    require(
        response.plastic_dissipation_j_m3 == 0.0 && !response.yielded,
        "elastic adapter has no plastic history");

    const std::array<SymmetricTensor3, 3> directions{
        SymmetricTensor3{.xx = 0.3, .yy = -0.2, .zz = 0.1,
                         .xy = 0.4, .yz = -0.5, .zx = 0.2},
        SymmetricTensor3{.xx = 1.0},
        SymmetricTensor3{.xy = 1.0},
    };
    for (const auto &direction : directions) {
        const auto applied = applySmallStrainTangent(response, direction);
        const auto difference =
            finiteDifference(law, {}, strain, direction, 1.0e-8);
        requireTensorNear(
            applied, difference, 1.0e3, 2.0e-9,
            "isotropic exact directional tangent");
    }
}

void orthotropicComplianceReciprocityAndPhysicalShear() {
    const auto law = orthotropicLaw();
    validateSmallStrainLaw(law);
    constexpr double normal_stress = 12.0e6;
    constexpr double shear_stress = 1.4e6;
    const SymmetricTensor3 strain{
        .xx = normal_stress / law.young_modulus_pa[0],
        .yy = -law.poisson_xy_yz_zx[0] *
              normal_stress / law.young_modulus_pa[0],
        .zz = -law.poisson_xy_yz_zx[2] *
              normal_stress / law.young_modulus_pa[2],
        .xy = shear_stress /
              (2.0 * law.shear_xy_yz_zx_pa[0]),
    };
    const auto response = evaluateSmallStrain(law, {}, strain);
    requireTensorNear(
        response.stress_pa,
        SymmetricTensor3{.xx = normal_stress, .xy = shear_stress},
        1.0e-6,
        1.0e-13,
        "orthotropic reciprocal compliance and physical shear");

    const SymmetricTensor3 first{
        .xx = 0.2, .yy = -0.3, .zz = 0.4,
        .xy = 0.6, .yz = -0.1, .zx = 0.25};
    const SymmetricTensor3 second{
        .xx = -0.5, .yy = 0.1, .zz = 0.2,
        .xy = -0.3, .yz = 0.4, .zx = 0.15};
    const auto c_first = applySmallStrainTangent(response, first);
    const auto c_second = applySmallStrainTangent(response, second);
    near(
        doubleContract(first, c_second),
        doubleContract(second, c_first),
        1.0e-4,
        "orthotropic tangent reciprocity uses tensor-weighted product");
    require(
        doubleContract(first, c_first) > 0.0,
        "SPD orthotropic law has positive directional stiffness");

    const auto difference =
        finiteDifference(law, {}, strain, first, 1.0e-8);
    requireTensorNear(
        c_first, difference, 1.0e2, 2.0e-9,
        "orthotropic exact directional tangent");
}

void j2PlasticConsistentDirectionalTangent() {
    const auto law = j2Law();
    const SymmetricTensor3 target{
        .xx = 0.004,
        .yy = -0.002,
        .zz = -0.002,
        .xy = 0.001,
        .yz = 0.0004,
    };
    const auto response = evaluateSmallStrain(law, {}, target);
    require(response.yielded, "J2 tangent fixture must be on plastic branch");
    const std::array<SymmetricTensor3, 4> directions{
        SymmetricTensor3{.xx = 0.3, .yy = -0.1, .zz = 0.2,
                         .xy = 0.4, .yz = -0.2, .zx = 0.1},
        SymmetricTensor3{.xx = 1.0},
        SymmetricTensor3{.xy = 1.0},
        SymmetricTensor3{.xx = 1.0, .yy = 1.0, .zz = 1.0},
    };
    for (const auto &direction : directions) {
        const auto applied = applySmallStrainTangent(response, direction);
        const auto difference =
            finiteDifference(law, {}, target, direction, 1.0e-8);
        requireTensorNear(
            applied, difference, 2.0e4, 2.0e-6,
            "J2 plastic consistent directional tangent");
    }

    const auto &first = directions[0];
    const auto &second = directions[2];
    const auto c_first = applySmallStrainTangent(response, first);
    const auto c_second = applySmallStrainTangent(response, second);
    near(
        doubleContract(first, c_second),
        doubleContract(second, c_first),
        1.0e-3,
        "J2 algorithmic tangent is tensor-weight self-adjoint");
    require(
        doubleContract(first, c_first) > 0.0,
        "hardening J2 algorithmic tangent is positive away from branch changes");
}

void j2HydrostaticShearAndUnloadingHistory() {
    const auto law = j2Law();
    const auto hydrostatic = evaluateSmallStrain(
        law, {}, SymmetricTensor3{.xx = 0.001, .yy = 0.001, .zz = 0.001});
    require(!hydrostatic.yielded, "hydrostatic strain does not yield J2");
    near(
        vonMisesEquivalentStressPa(hydrostatic.stress_pa),
        0.0,
        1.0e-5,
        "hydrostatic J2 equivalent stress");

    const auto loaded = evaluateSmallStrain(
        law, {}, SymmetricTensor3{.xy = 0.003});
    require(
        loaded.yielded && loaded.state.plastic_strain.xy > 0.0 &&
        loaded.plastic_dissipation_j_m3 > 0.0,
        "J2 shear creates persistent plastic history and dissipation");
    const auto unloaded = evaluateSmallStrain(
        law, loaded.state, loaded.state.plastic_strain);
    require(!unloaded.yielded, "J2 unloading is elastic");
    near(unloaded.stress_pa.xy, 0.0, 1.0e-5, "unloaded J2 shear stress");
    require(
        unloaded.state.plastic_strain == loaded.state.plastic_strain &&
        unloaded.state.equivalent_plastic_strain ==
            loaded.state.equivalent_plastic_strain &&
        unloaded.plastic_dissipation_j_m3 ==
            loaded.plastic_dissipation_j_m3,
        "unloading preserves permanent strain and dissipation exactly");
}

void zeroIncrementAtYieldUsesDocumentedElasticSide() {
    const auto law = j2Law();
    const auto loaded = evaluateSmallStrain(
        law, {}, SymmetricTensor3{.xy = 0.003});
    require(loaded.yielded, "zero-increment branch fixture first yields");
    const auto zero = evaluateSmallStrain(
        law, loaded.state, loaded.state.total_strain);
    require(!zero.yielded, "zero increment at yield takes elastic trial branch");
    const double shear = law.j2.young_modulus_pa /
        (2.0 * (1.0 + law.j2.poisson_ratio));
    const auto shear_column = applySmallStrainTangent(
        zero, SymmetricTensor3{.xy = 1.0});
    near(
        shear_column.xy,
        2.0 * shear,
        1.0e-5,
        "zero-increment one-sided shear tangent is elastic");
    require(
        zero.state == loaded.state,
        "zero-increment tangent evaluation preserves persistent state exactly");
}

void invalidFamiliesAndStatesRejectTransactionally() {
    auto invalid_orthotropic = orthotropicLaw();
    invalid_orthotropic.poisson_xy_yz_zx = {4.0, 0.0, 0.0};
    bool rejected = false;
    try {
        validateSmallStrainLaw(invalid_orthotropic);
    } catch (const std::invalid_argument &) {
        rejected = true;
    }
    require(rejected, "non-SPD orthotropic compliance rejects");

    auto invalid_shear = orthotropicLaw();
    invalid_shear.shear_xy_yz_zx_pa[1] = 0.0;
    rejected = false;
    try {
        validateSmallStrainLaw(invalid_shear);
    } catch (const std::invalid_argument &) {
        rejected = true;
    }
    require(rejected, "nonpositive orthotropic shear modulus rejects");

    auto conflicting_alias = isotropicLaw();
    conflicting_alias.young_modulus_pa[1] *= 0.9;
    rejected = false;
    try {
        validateSmallStrainLaw(conflicting_alias);
    } catch (const std::invalid_argument &) {
        rejected = true;
    }
    require(rejected, "conflicting isotropic alias rejects");

    auto conflicting_j2_alias = j2Law();
    conflicting_j2_alias.maximum_total_strain_norm *= 0.5;
    rejected = false;
    try {
        validateSmallStrainLaw(conflicting_j2_alias);
    } catch (const std::invalid_argument &) {
        rejected = true;
    }
    require(rejected, "conflicting J2 common alias rejects");

    auto nonfinite = isotropicLaw();
    nonfinite.poisson_xy_yz_zx[0] =
        std::numeric_limits<double>::quiet_NaN();
    rejected = false;
    try {
        validateSmallStrainLaw(nonfinite);
    } catch (const std::invalid_argument &) {
        rejected = true;
    }
    require(rejected, "nonfinite active law parameter rejects");

    const auto law = isotropicLaw();
    J2State invalid_state;
    invalid_state.plastic_strain.xy = 1.0e-4;
    const J2State before = invalid_state;
    rejected = false;
    try {
        (void)evaluateSmallStrain(law, invalid_state, {});
    } catch (const std::invalid_argument &) {
        rejected = true;
    }
    require(
        rejected && invalid_state == before,
        "elastic law rejects plastic history without mutating prior state");

    const J2State valid_prior{};
    rejected = false;
    try {
        (void)evaluateSmallStrain(
            law,
            valid_prior,
            SymmetricTensor3{
                .xx = std::numeric_limits<double>::infinity()});
    } catch (const std::invalid_argument &) {
        rejected = true;
    }
    require(
        rejected && valid_prior == J2State{},
        "nonfinite absolute strain rejects transactionally");
}

} // namespace

int main() {
    const std::vector<std::pair<std::string_view, std::function<void()>>> tests{
        {"isotropic analytical response and tangent",
         isotropicElasticAnalyticalAndDirectionalTangent},
        {"orthotropic reciprocity SPD and physical shear",
         orthotropicComplianceReciprocityAndPhysicalShear},
        {"J2 consistent directional tangent",
         j2PlasticConsistentDirectionalTangent},
        {"J2 hydrostatic shear and unloading history",
         j2HydrostaticShearAndUnloadingHistory},
        {"J2 zero-increment elastic-side tangent",
         zeroIncrementAtYieldUsesDocumentedElasticSide},
        {"invalid laws states and transactional rejection",
         invalidFamiliesAndStatesRejectTransactionally},
    };
    unsigned failures = 0;
    for (const auto &[name, test] : tests) {
        try {
            test();
            std::cout << "[PASS] " << name << '\n';
        } catch (const std::exception &error) {
            ++failures;
            std::cerr << "[FAIL] " << name << ": " << error.what() << '\n';
        }
    }
    std::cout << tests.size() - failures << '/' << tests.size()
              << " tests passed\n";
    return failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
