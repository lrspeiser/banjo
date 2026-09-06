#include "material/Plasticity.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>

namespace banjo {
namespace {

bool finite(const SymmetricTensor3 &a) {
    return std::isfinite(a.xx) && std::isfinite(a.yy) &&
           std::isfinite(a.zz) && std::isfinite(a.xy) &&
           std::isfinite(a.yz) && std::isfinite(a.zx);
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

double shearModulus(const J2Material &material) {
    return material.young_modulus_pa /
           (2.0 * (1.0 + material.poisson_ratio));
}

double lameLambda(const J2Material &material) {
    return material.young_modulus_pa * material.poisson_ratio /
           ((1.0 + material.poisson_ratio) *
            (1.0 - 2.0 * material.poisson_ratio));
}

SymmetricTensor3 elasticStressUnchecked(
    const J2Material &material, const J2State &state) {
    const SymmetricTensor3 elastic =
        subtract(state.total_strain, state.plastic_strain);
    const double hydrostatic = lameLambda(material) * trace(elastic);
    SymmetricTensor3 stress = scale(elastic, 2.0 * shearModulus(material));
    stress.xx += hydrostatic;
    stress.yy += hydrostatic;
    stress.zz += hydrostatic;
    return stress;
}

double stateTolerance(double scale) {
    return 256.0 * std::numeric_limits<double>::epsilon() *
           std::max(1.0, scale);
}

void requireFiniteIncrement(const SymmetricTensor3 &increment) {
    if (!finite(increment)) {
        throw std::invalid_argument("J2 strain increment must be finite");
    }
}

} // namespace

double trace(const SymmetricTensor3 &tensor) {
    return tensor.xx + tensor.yy + tensor.zz;
}

SymmetricTensor3 deviatoric(const SymmetricTensor3 &tensor) {
    const double mean = trace(tensor) / 3.0;
    SymmetricTensor3 result = tensor;
    result.xx -= mean;
    result.yy -= mean;
    result.zz -= mean;
    return result;
}

double doubleContract(
    const SymmetricTensor3 &first, const SymmetricTensor3 &second) {
    return first.xx * second.xx + first.yy * second.yy +
           first.zz * second.zz +
           2.0 * (first.xy * second.xy + first.yz * second.yz +
                  first.zx * second.zx);
}

double frobeniusNorm(const SymmetricTensor3 &tensor) {
    return std::sqrt(std::max(0.0, doubleContract(tensor, tensor)));
}

double vonMisesEquivalentStressPa(const SymmetricTensor3 &stress_pa) {
    const SymmetricTensor3 deviator = deviatoric(stress_pa);
    return std::sqrt(
        std::max(0.0, 1.5 * doubleContract(deviator, deviator)));
}

void validateJ2Material(const J2Material &material) {
    if (material.family !=
        ContinuumConstitutiveFamily::SmallStrainIsotropicJ2) {
        throw std::invalid_argument(
            "J2 integration requires the small-strain isotropic J2 family");
    }
    if (!std::isfinite(material.young_modulus_pa) ||
        material.young_modulus_pa <= 0.0 ||
        !std::isfinite(material.poisson_ratio) ||
        material.poisson_ratio <= -1.0 ||
        material.poisson_ratio >= 0.5 ||
        !std::isfinite(material.initial_yield_stress_pa) ||
        material.initial_yield_stress_pa <= 0.0 ||
        !std::isfinite(material.isotropic_hardening_modulus_pa) ||
        material.isotropic_hardening_modulus_pa < 0.0 ||
        !std::isfinite(material.maximum_total_strain_norm) ||
        material.maximum_total_strain_norm <= 0.0 ||
        !std::isfinite(shearModulus(material)) ||
        !std::isfinite(lameLambda(material))) {
        throw std::invalid_argument(
            "invalid finite SI parameters for small-strain isotropic J2");
    }
}

void validateJ2State(const J2Material &material, const J2State &state) {
    validateJ2Material(material);
    if (!finite(state.total_strain) || !finite(state.plastic_strain) ||
        !std::isfinite(state.equivalent_plastic_strain) ||
        state.equivalent_plastic_strain < 0.0 ||
        !std::isfinite(state.plastic_dissipation_j_m3) ||
        state.plastic_dissipation_j_m3 < 0.0) {
        throw std::invalid_argument(
            "J2 persistent state must contain finite nonnegative history");
    }
    const double total_norm = frobeniusNorm(state.total_strain);
    if (!std::isfinite(total_norm) ||
        total_norm > material.maximum_total_strain_norm) {
        throw std::invalid_argument(
            "J2 state exceeds declared small-strain validity norm");
    }
    const double plastic_norm = frobeniusNorm(state.plastic_strain);
    if (std::abs(trace(state.plastic_strain)) >
        stateTolerance(plastic_norm)) {
        throw std::invalid_argument(
            "J2 plastic strain must remain deviatoric");
    }
    const double represented_equivalent =
        std::sqrt(std::max(
            0.0, (2.0 / 3.0) *
                     doubleContract(
                         state.plastic_strain, state.plastic_strain)));
    if (represented_equivalent >
        state.equivalent_plastic_strain +
            stateTolerance(state.equivalent_plastic_strain)) {
        throw std::invalid_argument(
            "J2 accumulated equivalent plastic strain is inconsistent");
    }
    const double expected_dissipation =
        material.initial_yield_stress_pa *
        state.equivalent_plastic_strain;
    if (!std::isfinite(expected_dissipation) ||
        std::abs(
            state.plastic_dissipation_j_m3 -
            expected_dissipation) >
            stateTolerance(expected_dissipation)) {
        throw std::invalid_argument(
            "J2 dissipation history is inconsistent with material calibration");
    }
    const SymmetricTensor3 reconstructed_stress =
        elasticStressUnchecked(material, state);
    if (!finite(reconstructed_stress)) {
        throw std::invalid_argument(
            "J2 state does not reconstruct finite stress");
    }
    const double current_yield =
        material.initial_yield_stress_pa +
        material.isotropic_hardening_modulus_pa *
            state.equivalent_plastic_strain;
    const double equivalent_stress =
        vonMisesEquivalentStressPa(reconstructed_stress);
    if (!std::isfinite(current_yield) ||
        equivalent_stress >
            current_yield + stateTolerance(current_yield)) {
        throw std::invalid_argument(
            "J2 restored state lies outside its current yield surface");
    }
}

SymmetricTensor3 reconstructJ2StressPa(
    const J2Material &material, const J2State &state) {
    validateJ2State(material, state);
    return elasticStressUnchecked(material, state);
}

J2EnergyDensity j2EnergyDensity(
    const J2Material &material, const J2State &state) {
    validateJ2State(material, state);
    const SymmetricTensor3 elastic =
        subtract(state.total_strain, state.plastic_strain);
    const SymmetricTensor3 stress =
        elasticStressUnchecked(material, state);
    const double elastic_energy =
        0.5 * doubleContract(stress, elastic);
    const double hardening_energy =
        0.5 * material.isotropic_hardening_modulus_pa *
        state.equivalent_plastic_strain *
        state.equivalent_plastic_strain;
    if (!std::isfinite(elastic_energy) || elastic_energy < 0.0 ||
        !std::isfinite(hardening_energy) || hardening_energy < 0.0) {
        throw std::invalid_argument(
            "J2 state has invalid free-energy density");
    }
    return {
        elastic_energy,
        hardening_energy,
        state.plastic_dissipation_j_m3,
    };
}

J2Update integrateJ2StrainIncrement(
    const J2Material &material,
    const J2State &state,
    const SymmetricTensor3 &strain_increment) {
    validateJ2State(material, state);
    requireFiniteIncrement(strain_increment);

    const SymmetricTensor3 old_stress =
        elasticStressUnchecked(material, state);
    const double yield_before =
        material.initial_yield_stress_pa +
        material.isotropic_hardening_modulus_pa *
            state.equivalent_plastic_strain;

    if (strain_increment == SymmetricTensor3{}) {
        return {
            state,
            old_stress,
            old_stress,
            {},
            false,
            vonMisesEquivalentStressPa(old_stress),
            yield_before,
            yield_before,
        };
    }

    J2State candidate = state;
    candidate.total_strain =
        add(candidate.total_strain, strain_increment);
    if (frobeniusNorm(candidate.total_strain) >
        material.maximum_total_strain_norm) {
        throw std::invalid_argument(
            "J2 update exceeds declared small-strain validity norm");
    }

    const SymmetricTensor3 trial_stress =
        elasticStressUnchecked(material, candidate);
    const SymmetricTensor3 trial_deviator =
        deviatoric(trial_stress);
    const double trial_equivalent =
        vonMisesEquivalentStressPa(trial_stress);
    if (!std::isfinite(trial_equivalent)) {
        throw std::invalid_argument(
            "J2 trial equivalent stress is not finite");
    }

    J2Update update;
    update.state = candidate;
    update.trial_stress_pa = trial_stress;
    update.trial_equivalent_stress_pa = trial_equivalent;
    update.yield_stress_before_pa = yield_before;
    const double yield_function = trial_equivalent - yield_before;
    const double yield_tolerance =
        stateTolerance(std::max(trial_equivalent, yield_before));
    if (yield_function > yield_tolerance) {
        const double shear = shearModulus(material);
        const double denominator =
            3.0 * shear +
            material.isotropic_hardening_modulus_pa;
        const double plastic_increment =
            yield_function / denominator;
        if (!std::isfinite(plastic_increment) ||
            plastic_increment <= 0.0) {
            throw std::invalid_argument(
                "J2 radial return produced invalid plastic increment");
        }
        update.yielded = true;
        update.equivalent_plastic_strain_increment =
            plastic_increment;
        update.plastic_strain_increment =
            scale(
                trial_deviator,
                1.5 * plastic_increment /
                    trial_equivalent);
        update.state.plastic_strain = deviatoric(
            add(
                state.plastic_strain,
                update.plastic_strain_increment));
        update.state.equivalent_plastic_strain +=
            plastic_increment;
        update.plastic_dissipation_increment_j_m3 =
            material.initial_yield_stress_pa *
            plastic_increment;
        update.state.plastic_dissipation_j_m3 +=
            update.plastic_dissipation_increment_j_m3;
        update.hardening_free_energy_increment_j_m3 =
            material.isotropic_hardening_modulus_pa *
            (state.equivalent_plastic_strain *
                 plastic_increment +
             0.5 * plastic_increment * plastic_increment);
        update.constitutive_plastic_work_j_m3 =
            update.plastic_dissipation_increment_j_m3 +
            update.hardening_free_energy_increment_j_m3;
    }

    validateJ2State(material, update.state);
    update.stress_pa =
        elasticStressUnchecked(material, update.state);
    update.yield_stress_after_pa =
        material.initial_yield_stress_pa +
        material.isotropic_hardening_modulus_pa *
            update.state.equivalent_plastic_strain;
    // Difference the quadratic elastic energy through its exact secant form.
    // Subtracting two total free energies loses the increment when a restored
    // prestrained state is queried at a nearby representable strain.
    const SymmetricTensor3 accepted_total_strain_increment =
        subtract(update.state.total_strain, state.total_strain);
    const SymmetricTensor3 accepted_plastic_strain_increment =
        subtract(update.state.plastic_strain, state.plastic_strain);
    const SymmetricTensor3 elastic_strain_increment =
        subtract(
            accepted_total_strain_increment,
            accepted_plastic_strain_increment);
    update.stored_free_energy_increment_j_m3 =
        0.5 * doubleContract(
                  add(old_stress, update.stress_pa),
                  elastic_strain_increment) +
        update.hardening_free_energy_increment_j_m3;
    update.backward_euler_stress_work_j_m3 =
        doubleContract(
            update.stress_pa, accepted_total_strain_increment);
    update.backward_euler_work_excess_j_m3 =
        update.backward_euler_stress_work_j_m3 -
        update.stored_free_energy_increment_j_m3 -
        update.plastic_dissipation_increment_j_m3;
    const double work_scale = std::max({
        1.0,
        std::abs(update.backward_euler_stress_work_j_m3),
        std::abs(update.stored_free_energy_increment_j_m3),
        update.plastic_dissipation_increment_j_m3,
    });
    if (!std::isfinite(update.backward_euler_work_excess_j_m3) ||
        update.backward_euler_work_excess_j_m3 <
            -stateTolerance(work_scale)) {
        throw std::invalid_argument(
            "J2 backward-Euler work excess is invalid");
    }
    update.backward_euler_work_excess_j_m3 =
        std::max(0.0, update.backward_euler_work_excess_j_m3);
    return update;
}

} // namespace banjo
