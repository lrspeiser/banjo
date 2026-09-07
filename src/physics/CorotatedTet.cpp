#include "physics/CorotatedTet.hpp"

#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace banjo {
namespace {

void require(bool condition, const char *message) {
    if (!condition) throw std::invalid_argument(message);
}

bool finite(Vec3 value) {
    return std::isfinite(value.x) && std::isfinite(value.y) && std::isfinite(value.z);
}

bool finite(const Mat3 &value) {
    for (const auto &row : value.m)
        for (double entry : row)
            if (!std::isfinite(entry)) return false;
    return true;
}

Mat3 columns(Vec3 a, Vec3 b, Vec3 c) {
    Mat3 result;
    for (unsigned row = 0; row < 3; ++row) {
        const double av = row == 0 ? a.x : row == 1 ? a.y : a.z;
        const double bv = row == 0 ? b.x : row == 1 ? b.y : b.z;
        const double cv = row == 0 ? c.x : row == 1 ? c.y : c.z;
        result.m[row] = {av, bv, cv};
    }
    return result;
}

Mat3 transpose(const Mat3 &value) {
    Mat3 result;
    for (unsigned i = 0; i < 3; ++i)
        for (unsigned j = 0; j < 3; ++j)
            result.m[i][j] = value.m[j][i];
    return result;
}

Mat3 multiply(const Mat3 &a, const Mat3 &b) {
    Mat3 result;
    for (unsigned i = 0; i < 3; ++i)
        for (unsigned j = 0; j < 3; ++j)
            for (unsigned k = 0; k < 3; ++k)
                result.m[i][j] += a.m[i][k] * b.m[k][j];
    return result;
}

Mat3 add(Mat3 a, const Mat3 &b) {
    for (unsigned i = 0; i < 3; ++i)
        for (unsigned j = 0; j < 3; ++j)
            a.m[i][j] += b.m[i][j];
    return a;
}

Mat3 subtract(Mat3 a, const Mat3 &b) {
    for (unsigned i = 0; i < 3; ++i)
        for (unsigned j = 0; j < 3; ++j)
            a.m[i][j] -= b.m[i][j];
    return a;
}

Mat3 scale(Mat3 value, double factor) {
    for (auto &row : value.m)
        for (double &entry : row)
            entry *= factor;
    return value;
}

double frobeniusSquared(const Mat3 &value) {
    double result = 0;
    for (const auto &row : value.m)
        for (double entry : row)
            result += entry * entry;
    return result;
}

double trace(const Mat3 &value) {
    return value.m[0][0] + value.m[1][1] + value.m[2][2];
}

Mat3 inverseRelative(const Mat3 &value, double scale_hint, const char *message) {
    const double determinant = value.determinant();
    require(std::isfinite(determinant) && determinant > 0 &&
                determinant > 1.e-12 * scale_hint,
            message);
    const auto inverse = value.inverse(0.0);
    require(inverse.has_value() && finite(*inverse), message);
    return *inverse;
}

std::pair<Mat3, unsigned> properPolarRotation(const Mat3 &deformation,
                                              const CorotatedTetLaw &law) {
    Mat3 rotation = deformation;
    for (unsigned iteration = 1; iteration <= law.maximum_polar_iterations; ++iteration) {
        const auto inverse = rotation.inverse(0.0);
        require(inverse.has_value() && finite(*inverse),
                "Corotated polar iteration became singular");
        const Mat3 next = scale(add(rotation, transpose(*inverse)), 0.5);
        const double change = std::sqrt(frobeniusSquared(subtract(next, rotation)));
        require(finite(next) && std::isfinite(change),
                "Corotated polar iteration exceeded numeric range");
        rotation = next;
        if (change <= law.polar_tolerance) {
            require(rotation.determinant() > 0,
                    "Corotated polar factor is not a proper rotation");
            const Mat3 orthogonality =
                subtract(multiply(transpose(rotation), rotation),
                         columns({1, 0, 0}, {0, 1, 0}, {0, 0, 1}));
            require(std::sqrt(frobeniusSquared(orthogonality)) <=
                        32 * law.polar_tolerance,
                    "Corotated polar factor failed orthogonality tolerance");
            return {rotation, iteration};
        }
    }
    throw std::invalid_argument("Corotated polar iteration budget exhausted");
}

} // namespace

CorotatedTetEvaluation evaluateCorotatedTet(
    const CorotatedTetLaw &law, const std::array<Vec3, 4> &reference,
    const std::array<Vec3, 4> &current) {
    require(std::isfinite(law.shear_modulus_pa) && law.shear_modulus_pa > 0 &&
                std::isfinite(law.lame_lambda_pa) && law.lame_lambda_pa >= 0 &&
                std::isfinite(law.density_kg_m3) && law.density_kg_m3 > 0 &&
                std::isfinite(law.minimum_deformation_jacobian) &&
                law.minimum_deformation_jacobian > 0 &&
                law.minimum_deformation_jacobian <= 1 &&
                std::isfinite(law.maximum_deformation_gradient_norm) &&
                law.maximum_deformation_gradient_norm >= std::sqrt(3.0) &&
                law.maximum_deformation_gradient_norm <= 100 &&
                law.maximum_polar_iterations > 0 && law.maximum_polar_iterations <= 128 &&
                std::isfinite(law.polar_tolerance) && law.polar_tolerance > 0 &&
                law.polar_tolerance <= 1.e-6,
            "Invalid corotated tetrahedron law or solver bounds");
    for (Vec3 value : reference)
        require(finite(value), "Corotated reference position must be finite");
    for (Vec3 value : current)
        require(finite(value), "Corotated current position must be finite");

    const Mat3 reference_edges = columns(reference[1] - reference[0],
                                         reference[2] - reference[0],
                                         reference[3] - reference[0]);
    const double reference_scale = length(reference[1] - reference[0]) *
                                   length(reference[2] - reference[0]) *
                                   length(reference[3] - reference[0]);
    const Mat3 inverse_reference = inverseRelative(
        reference_edges, reference_scale,
        "Corotated reference tetrahedron must have positive nonsingular orientation");
    const double reference_determinant = reference_edges.determinant();
    const double volume = reference_determinant / 6;
    const Mat3 current_edges = columns(current[1] - current[0], current[2] - current[0],
                                       current[3] - current[0]);
    const Mat3 deformation = multiply(current_edges, inverse_reference);
    const double jacobian = deformation.determinant();
    const double deformation_norm = std::sqrt(frobeniusSquared(deformation));
    require(finite(deformation) && std::isfinite(jacobian) &&
                jacobian >= law.minimum_deformation_jacobian &&
                std::isfinite(deformation_norm) &&
                deformation_norm <= law.maximum_deformation_gradient_norm,
            "Corotated current tetrahedron is inverted, singular, or outside its domain");

    const auto [rotation, iterations] = properPolarRotation(deformation, law);
    const Mat3 strain_like = subtract(deformation, rotation);
    const double dilation = trace(multiply(transpose(rotation), deformation)) - 3;
    const double energy_density =
        law.shear_modulus_pa * frobeniusSquared(strain_like) +
        0.5 * law.lame_lambda_pa * dilation * dilation;
    const Mat3 stress = add(scale(strain_like, 2 * law.shear_modulus_pa),
                            scale(rotation, law.lame_lambda_pa * dilation));
    require(std::isfinite(energy_density) && energy_density >= 0 && finite(stress),
            "Corotated response exceeded numeric range");

    CorotatedTetEvaluation result;
    result.deformation_gradient = deformation;
    result.rotation = rotation;
    result.first_piola_stress_pa = stress;
    result.reference_volume_m3 = volume;
    result.mass_kg = volume * law.density_kg_m3;
    result.stored_energy_j = volume * energy_density;
    result.polar_iterations = iterations;
    require(std::isfinite(result.mass_kg) && result.mass_kg > 0 &&
                std::isfinite(result.stored_energy_j),
            "Corotated mass or energy exceeded numeric range");
    for (double &mass : result.nodal_masses_kg)
        mass = result.mass_kg / 4;

    const Mat3 inverse_reference_transpose = transpose(inverse_reference);
    std::array<Vec3, 4> gradients;
    gradients[1] = inverse_reference_transpose * Vec3{1, 0, 0};
    gradients[2] = inverse_reference_transpose * Vec3{0, 1, 0};
    gradients[3] = inverse_reference_transpose * Vec3{0, 0, 1};
    gradients[0] = -(gradients[1] + gradients[2] + gradients[3]);
    for (unsigned i = 0; i < 4; ++i) {
        result.internal_forces_n[i] = volume * (stress * gradients[i]);
        require(finite(result.internal_forces_n[i]),
                "Corotated internal force exceeded numeric range");
    }
    return result;
}

} // namespace banjo
