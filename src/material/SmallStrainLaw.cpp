#include "material/SmallStrainLaw.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>

namespace banjo {
namespace {

using Matrix3 = std::array<std::array<double, 3>, 3>;

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

double tolerance(double scale_value) {
    return 256.0 * std::numeric_limits<double>::epsilon() *
           std::max(1.0, std::abs(scale_value));
}

bool approximatelyEqual(double first, double second) {
    return std::abs(first - second) <=
           tolerance(std::max(std::abs(first), std::abs(second)));
}

void validateOptionalAlias(
    double alias, double expected, const char *message) {
    if (!std::isfinite(alias) ||
        (alias != 0.0 && !approximatelyEqual(alias, expected))) {
        throw std::invalid_argument(message);
    }
}

double isotropicShear(double young, double poisson) {
    return young / (2.0 * (1.0 + poisson));
}

double isotropicLambda(double young, double poisson) {
    return young * poisson /
           ((1.0 + poisson) * (1.0 - 2.0 * poisson));
}

void validateIsotropicScalars(
    double young, double poisson, double maximum_norm) {
    if (!std::isfinite(young) || young <= 0.0 ||
        !std::isfinite(poisson) || poisson <= -1.0 || poisson >= 0.5 ||
        !std::isfinite(maximum_norm) || maximum_norm <= 0.0 ||
        !std::isfinite(isotropicShear(young, poisson)) ||
        !std::isfinite(isotropicLambda(young, poisson))) {
        throw std::invalid_argument(
            "invalid finite SI parameters for isotropic small-strain law");
    }
}

SymmetricTensor3 isotropicStress(
    double young,
    double poisson,
    const SymmetricTensor3 &strain) {
    const double shear = isotropicShear(young, poisson);
    SymmetricTensor3 result = scale(strain, 2.0 * shear);
    const double hydrostatic = isotropicLambda(young, poisson) * trace(strain);
    result.xx += hydrostatic;
    result.yy += hydrostatic;
    result.zz += hydrostatic;
    return result;
}

Matrix3 orthotropicCompliance(const SmallStrainLaw &law) {
    const auto &young = law.young_modulus_pa;
    const auto &poisson = law.poisson_xy_yz_zx;
    Matrix3 compliance{};
    compliance[0][0] = 1.0 / young[0];
    compliance[1][1] = 1.0 / young[1];
    compliance[2][2] = 1.0 / young[2];
    compliance[0][1] = compliance[1][0] = -poisson[0] / young[0];
    compliance[1][2] = compliance[2][1] = -poisson[1] / young[1];
    compliance[0][2] = compliance[2][0] = -poisson[2] / young[2];
    return compliance;
}

Matrix3 invertSpd(const Matrix3 &matrix) {
    Matrix3 lower{};
    for (std::size_t i = 0; i < 3; ++i) {
        for (std::size_t j = 0; j <= i; ++j) {
            double value = matrix[i][j];
            for (std::size_t k = 0; k < j; ++k) {
                value -= lower[i][k] * lower[j][k];
            }
            if (i == j) {
                if (!std::isfinite(value) || value <= 0.0) {
                    throw std::invalid_argument(
                        "orthotropic normal compliance must be positive definite");
                }
                lower[i][j] = std::sqrt(value);
            } else {
                lower[i][j] = value / lower[j][j];
                if (!std::isfinite(lower[i][j])) {
                    throw std::invalid_argument(
                        "orthotropic compliance factorization is not finite");
                }
            }
        }
    }

    Matrix3 inverse{};
    for (std::size_t column = 0; column < 3; ++column) {
        std::array<double, 3> intermediate{};
        for (std::size_t i = 0; i < 3; ++i) {
            double value = i == column ? 1.0 : 0.0;
            for (std::size_t k = 0; k < i; ++k) {
                value -= lower[i][k] * intermediate[k];
            }
            intermediate[i] = value / lower[i][i];
        }
        std::array<double, 3> solution{};
        for (std::size_t offset = 0; offset < 3; ++offset) {
            const std::size_t i = 2 - offset;
            double value = intermediate[i];
            for (std::size_t k = i + 1; k < 3; ++k) {
                value -= lower[k][i] * solution[k];
            }
            solution[i] = value / lower[i][i];
            if (!std::isfinite(solution[i])) {
                throw std::invalid_argument(
                    "orthotropic stiffness inverse is not finite");
            }
        }
        for (std::size_t row = 0; row < 3; ++row) {
            inverse[row][column] = solution[row];
        }
    }
    for (std::size_t i = 0; i < 3; ++i) {
        for (std::size_t j = i + 1; j < 3; ++j) {
            const double symmetric = 0.5 * (inverse[i][j] + inverse[j][i]);
            inverse[i][j] = symmetric;
            inverse[j][i] = symmetric;
        }
    }
    return inverse;
}

Matrix3 orthotropicStiffness(const SmallStrainLaw &law) {
    return invertSpd(orthotropicCompliance(law));
}

SymmetricTensor3 orthotropicStress(
    const SmallStrainLaw &law,
    const Matrix3 &normal_stiffness,
    const SymmetricTensor3 &strain) {
    const std::array<double, 3> normal_strain{
        strain.xx, strain.yy, strain.zz};
    std::array<double, 3> normal_stress{};
    for (std::size_t i = 0; i < 3; ++i) {
        for (std::size_t j = 0; j < 3; ++j) {
            normal_stress[i] += normal_stiffness[i][j] * normal_strain[j];
        }
    }
    return {
        normal_stress[0],
        normal_stress[1],
        normal_stress[2],
        2.0 * law.shear_xy_yz_zx_pa[0] * strain.xy,
        2.0 * law.shear_xy_yz_zx_pa[1] * strain.yz,
        2.0 * law.shear_xy_yz_zx_pa[2] * strain.zx,
    };
}

void validateElasticState(
    const J2State &state, double maximum_total_strain_norm) {
    if (!finite(state.total_strain) ||
        frobeniusNorm(state.total_strain) > maximum_total_strain_norm ||
        state.plastic_strain != SymmetricTensor3{} ||
        state.equivalent_plastic_strain != 0.0 ||
        state.plastic_dissipation_j_m3 != 0.0) {
        throw std::invalid_argument(
            "elastic small-strain state must be finite, in range, and have zero plastic history");
    }
}

template <class Operator>
std::array<SymmetricTensor3, 6> tangentColumns(Operator &&operation) {
    const std::array<SymmetricTensor3, 6> basis{
        SymmetricTensor3{.xx = 1.0},
        SymmetricTensor3{.yy = 1.0},
        SymmetricTensor3{.zz = 1.0},
        SymmetricTensor3{.xy = 1.0},
        SymmetricTensor3{.yz = 1.0},
        SymmetricTensor3{.zx = 1.0},
    };
    std::array<SymmetricTensor3, 6> columns{};
    for (std::size_t i = 0; i < columns.size(); ++i) {
        columns[i] = operation(basis[i]);
        if (!finite(columns[i])) {
            throw std::invalid_argument(
                "small-strain tangent contains a nonfinite column");
        }
    }
    return columns;
}

std::array<double, 6> components(const SymmetricTensor3 &tensor) {
    return {tensor.xx, tensor.yy, tensor.zz,
            tensor.xy, tensor.yz, tensor.zx};
}

SmallStrainResponse evaluateElastic(
    const SmallStrainLaw &law,
    const J2State &prior,
    const SymmetricTensor3 &absolute_total_strain) {
    const double maximum_norm = law.maximum_total_strain_norm;
    validateElasticState(prior, maximum_norm);
    if (!finite(absolute_total_strain) ||
        frobeniusNorm(absolute_total_strain) > maximum_norm) {
        throw std::invalid_argument(
            "elastic update exceeds declared small-strain validity norm");
    }

    Matrix3 normal_stiffness{};
    const auto stress_operator = [&](const SymmetricTensor3 &strain) {
        if (law.kind == SmallStrainLawKind::IsotropicElastic) {
            return isotropicStress(
                law.young_modulus_pa[0],
                law.poisson_xy_yz_zx[0],
                strain);
        }
        return orthotropicStress(law, normal_stiffness, strain);
    };
    if (law.kind == SmallStrainLawKind::OrthotropicElastic) {
        normal_stiffness = orthotropicStiffness(law);
    }

    SmallStrainResponse response;
    response.state = prior;
    response.state.total_strain = absolute_total_strain;
    response.stress_pa = stress_operator(absolute_total_strain);
    response.tangent_columns = tangentColumns(stress_operator);
    response.stored_free_energy_j_m3 =
        0.5 * doubleContract(response.stress_pa, absolute_total_strain);

    const SymmetricTensor3 old_stress = stress_operator(prior.total_strain);
    const double old_energy =
        0.5 * doubleContract(old_stress, prior.total_strain);
    const SymmetricTensor3 increment =
        subtract(absolute_total_strain, prior.total_strain);
    response.backward_euler_work_excess_j_m3 =
        doubleContract(response.stress_pa, increment) -
        (response.stored_free_energy_j_m3 - old_energy);
    const double energy_scale = std::max({
        1.0,
        std::abs(response.stored_free_energy_j_m3),
        std::abs(old_energy),
    });
    if (!std::isfinite(response.stored_free_energy_j_m3) ||
        response.stored_free_energy_j_m3 < -tolerance(energy_scale) ||
        !std::isfinite(response.backward_euler_work_excess_j_m3) ||
        response.backward_euler_work_excess_j_m3 < -tolerance(energy_scale)) {
        throw std::invalid_argument(
            "elastic small-strain response has invalid energy density");
    }
    response.stored_free_energy_j_m3 =
        std::max(0.0, response.stored_free_energy_j_m3);
    response.backward_euler_work_excess_j_m3 =
        std::max(0.0, response.backward_euler_work_excess_j_m3);
    return response;
}

SmallStrainResponse evaluateJ2(
    const SmallStrainLaw &law,
    const J2State &prior,
    const SymmetricTensor3 &absolute_total_strain) {
    if (!finite(absolute_total_strain)) {
        throw std::invalid_argument("J2 absolute total strain must be finite");
    }
    const SymmetricTensor3 increment =
        subtract(absolute_total_strain, prior.total_strain);
    const J2Update update =
        integrateJ2StrainIncrement(law.j2, prior, increment);
    const double shear = isotropicShear(
        law.j2.young_modulus_pa, law.j2.poisson_ratio);

    auto tangent = [&](const SymmetricTensor3 &direction) {
        SymmetricTensor3 result = isotropicStress(
            law.j2.young_modulus_pa,
            law.j2.poisson_ratio,
            direction);
        if (!update.yielded) {
            return result;
        }

        // Consistent returned-branch tangent derived from the radial-return
        // relation documented by Jeremy Bleyer, Computational Mechanics
        // Numerical Tours with FEniCSx, "Elasto-plastic analysis of a 2D von
        // Mises material", equations 20-22 and the algorithmic tangent:
        // https://bleyerj.github.io/comet-fenicsx/tours/nonlinear_problems/plasticity/plasticity.html
        const SymmetricTensor3 trial_deviator =
            deviatoric(update.trial_stress_pa);
        const double trial_equivalent = update.trial_equivalent_stress_pa;
        const SymmetricTensor3 normal =
            scale(trial_deviator, 1.0 / trial_equivalent);
        const double beta =
            3.0 * shear *
            update.equivalent_plastic_strain_increment /
            trial_equivalent;
        const double normal_coefficient =
            3.0 * shear *
            (3.0 * shear /
                 (3.0 * shear +
                  law.j2.isotropic_hardening_modulus_pa) -
             beta);
        result = subtract(
            result,
            scale(
                normal,
                normal_coefficient * doubleContract(normal, direction)));
        result = subtract(
            result,
            scale(deviatoric(direction), 2.0 * shear * beta));
        return result;
    };

    const J2EnergyDensity energy = j2EnergyDensity(law.j2, update.state);
    SmallStrainResponse response;
    response.state = update.state;
    response.stress_pa = update.stress_pa;
    response.tangent_columns = tangentColumns(tangent);
    response.stored_free_energy_j_m3 = energy.storedFreeEnergyJPerM3();
    response.plastic_dissipation_j_m3 =
        energy.plastic_dissipation_j_m3;
    response.backward_euler_work_excess_j_m3 =
        update.backward_euler_work_excess_j_m3;
    response.yielded = update.yielded;
    return response;
}

} // namespace

void validateSmallStrainLaw(const SmallStrainLaw &law) {
    if (law.kind == SmallStrainLawKind::IsotropicElastic) {
        const double young = law.young_modulus_pa[0];
        const double poisson = law.poisson_xy_yz_zx[0];
        validateIsotropicScalars(
            young, poisson, law.maximum_total_strain_norm);
        const double shear = isotropicShear(young, poisson);
        validateOptionalAlias(
            law.young_modulus_pa[1], young,
            "isotropic y Young-modulus alias conflicts with x value");
        validateOptionalAlias(
            law.young_modulus_pa[2], young,
            "isotropic z Young-modulus alias conflicts with x value");
        validateOptionalAlias(
            law.poisson_xy_yz_zx[1], poisson,
            "isotropic yz Poisson alias conflicts with xy value");
        validateOptionalAlias(
            law.poisson_xy_yz_zx[2], poisson,
            "isotropic zx Poisson alias conflicts with xy value");
        for (double alias : law.shear_xy_yz_zx_pa) {
            validateOptionalAlias(
                alias, shear,
                "isotropic shear-modulus alias conflicts with E and nu");
        }
        return;
    }

    if (law.kind == SmallStrainLawKind::OrthotropicElastic) {
        if (!std::isfinite(law.maximum_total_strain_norm) ||
            law.maximum_total_strain_norm <= 0.0) {
            throw std::invalid_argument(
                "orthotropic maximum total strain norm must be finite and positive");
        }
        for (double young : law.young_modulus_pa) {
            if (!std::isfinite(young) || young <= 0.0) {
                throw std::invalid_argument(
                    "orthotropic Young moduli must be finite and positive");
            }
        }
        for (double poisson : law.poisson_xy_yz_zx) {
            if (!std::isfinite(poisson)) {
                throw std::invalid_argument(
                    "orthotropic Poisson ratios must be finite");
            }
        }
        for (double shear : law.shear_xy_yz_zx_pa) {
            if (!std::isfinite(shear) || shear <= 0.0) {
                throw std::invalid_argument(
                    "orthotropic shear moduli must be finite and positive");
            }
        }
        (void)orthotropicStiffness(law);
        return;
    }

    if (law.kind == SmallStrainLawKind::J2Plastic) {
        validateJ2Material(law.j2);
        const double shear = isotropicShear(
            law.j2.young_modulus_pa, law.j2.poisson_ratio);
        for (double alias : law.young_modulus_pa) {
            validateOptionalAlias(
                alias, law.j2.young_modulus_pa,
                "J2 Young-modulus alias conflicts with J2 material");
        }
        for (double alias : law.poisson_xy_yz_zx) {
            validateOptionalAlias(
                alias, law.j2.poisson_ratio,
                "J2 Poisson alias conflicts with J2 material");
        }
        for (double alias : law.shear_xy_yz_zx_pa) {
            validateOptionalAlias(
                alias, shear,
                "J2 shear-modulus alias conflicts with J2 material");
        }
        validateOptionalAlias(
            law.maximum_total_strain_norm,
            law.j2.maximum_total_strain_norm,
            "J2 maximum-strain alias conflicts with J2 material");
        return;
    }

    throw std::invalid_argument("unknown small-strain law kind");
}

SmallStrainResponse evaluateSmallStrain(
    const SmallStrainLaw &law,
    const J2State &prior,
    const SymmetricTensor3 &absolute_total_strain) {
    validateSmallStrainLaw(law);
    if (law.kind == SmallStrainLawKind::J2Plastic) {
        return evaluateJ2(law, prior, absolute_total_strain);
    }
    return evaluateElastic(law, prior, absolute_total_strain);
}

SymmetricTensor3 applySmallStrainTangent(
    const SmallStrainResponse &response,
    const SymmetricTensor3 &direction) {
    if (!finite(direction)) {
        throw std::invalid_argument(
            "small-strain tangent direction must be finite");
    }
    const auto weights = components(direction);
    SymmetricTensor3 result{};
    for (std::size_t i = 0; i < weights.size(); ++i) {
        if (!finite(response.tangent_columns[i])) {
            throw std::invalid_argument(
                "small-strain response tangent must be finite");
        }
        result = add(result, scale(response.tangent_columns[i], weights[i]));
    }
    if (!finite(result)) {
        throw std::invalid_argument(
            "small-strain tangent application is not finite");
    }
    return result;
}

} // namespace banjo
