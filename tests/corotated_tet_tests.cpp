#include "physics/CorotatedTet.hpp"

#include <cmath>
#include <functional>
#include <iostream>
#include <limits>
#include <stdexcept>

using namespace banjo;

namespace {

void check(bool condition, const char *message) {
    if (!condition) throw std::runtime_error(message);
}

void near(double actual, double expected, double tolerance, const char *message) {
    check(std::isfinite(actual) && std::abs(actual - expected) <= tolerance, message);
}

void nearVector(Vec3 actual, Vec3 expected, double tolerance, const char *message) {
    near(length(actual - expected), 0, tolerance, message);
}

void rejects(const std::function<void()> &operation) {
    bool rejected = false;
    try {
        operation();
    } catch (const std::invalid_argument &) {
        rejected = true;
    }
    check(rejected, "expected invalid corotated tetrahedron input to reject");
}

Vec3 rotate(Vec3 value) {
    const double c = std::cos(0.8);
    const double s = std::sin(0.8);
    return {c * value.x - s * value.y, s * value.x + c * value.y, value.z};
}

double entry(const Mat3 &matrix, unsigned row, unsigned column) {
    return matrix.m[row][column];
}

} // namespace

int main() {
    try {
        const CorotatedTetLaw law{
            .shear_modulus_pa = 3.e6,
            .lame_lambda_pa = 4.e6,
            .density_kg_m3 = 2400,
            .minimum_deformation_jacobian = 1.e-5,
            .maximum_deformation_gradient_norm = 8,
            .maximum_polar_iterations = 64,
            .polar_tolerance = 1.e-13,
        };
        const std::array<Vec3, 4> reference{{
            {0, 0, 0}, {1.2, 0.1, 0}, {0.2, 0.9, 0.1}, {0.1, 0.2, 1.1}}};

        std::array<Vec3, 4> rigid;
        for (unsigned i = 0; i < 4; ++i)
            rigid[i] = rotate(reference[i]) + Vec3{3, -2, 0.7};
        const auto rigid_result = evaluateCorotatedTet(law, reference, rigid);
        near(rigid_result.stored_energy_j, 0, 1e-17,
             "finite rigid rotation must have zero corotated energy");
        for (Vec3 force : rigid_result.internal_forces_n)
            nearVector(force, {}, 1e-8, "finite rigid rotation must have zero elastic force");
        near(rigid_result.mass_kg,
             law.density_kg_m3 * rigid_result.reference_volume_m3, 1e-12,
             "tetrahedron mass must use reference volume and density");

        std::array<Vec3, 4> deformed = reference;
        deformed[1] += Vec3{0.08, 0.03, -0.01};
        deformed[2] += Vec3{-0.02, 0.05, 0.04};
        deformed[3] += Vec3{0.01, -0.03, 0.06};
        const auto evaluation = evaluateCorotatedTet(law, reference, deformed);
        const double epsilon = 2e-7;
        for (unsigned node = 0; node < 4; ++node) {
            for (unsigned axis = 0; axis < 3; ++axis) {
                auto plus = deformed;
                auto minus = deformed;
                if (axis == 0) {
                    plus[node].x += epsilon;
                    minus[node].x -= epsilon;
                } else if (axis == 1) {
                    plus[node].y += epsilon;
                    minus[node].y -= epsilon;
                } else {
                    plus[node].z += epsilon;
                    minus[node].z -= epsilon;
                }
                const double gradient =
                    (evaluateCorotatedTet(law, reference, plus).stored_energy_j -
                     evaluateCorotatedTet(law, reference, minus).stored_energy_j) /
                    (2 * epsilon);
                const double force = axis == 0 ? evaluation.internal_forces_n[node].x
                                               : axis == 1 ? evaluation.internal_forces_n[node].y
                                                           : evaluation.internal_forces_n[node].z;
                near(force, gradient, std::max(2e-3, std::abs(gradient) * 2e-7),
                     "analytic corotated force must match potential finite difference");
            }
        }

        Vec3 resultant;
        Vec3 moment;
        for (unsigned i = 0; i < 4; ++i) {
            resultant += evaluation.internal_forces_n[i];
            moment += cross(deformed[i], evaluation.internal_forces_n[i]);
        }
        nearVector(resultant, {}, 1e-9,
                   "corotated internal forces must conserve linear momentum");
        nearVector(moment, {}, 2e-9,
                   "objective corotated forces must conserve angular momentum");

        const double small = 1e-6;
        auto small_deformation = reference;
        for (Vec3 &position : small_deformation)
            position = {position.x * (1 + small) + 0.5 * small * position.y,
                        position.y * (1 - 0.4 * small) + 0.5 * small * position.x,
                        position.z * (1 + 0.2 * small)};
        const auto linear = evaluateCorotatedTet(law, reference, small_deformation);
        const double trace_strain = 0.8 * small;
        const double expected_xx = 2 * law.shear_modulus_pa * small +
                                   law.lame_lambda_pa * trace_strain;
        const double expected_yy = -0.8 * law.shear_modulus_pa * small +
                                   law.lame_lambda_pa * trace_strain;
        const double expected_zz = 0.4 * law.shear_modulus_pa * small +
                                   law.lame_lambda_pa * trace_strain;
        const double expected_xy = law.shear_modulus_pa * small;
        near(entry(linear.first_piola_stress_pa, 0, 0), expected_xx, 2e-4,
             "corotated law must recover linear isotropic xx stress");
        near(entry(linear.first_piola_stress_pa, 1, 1), expected_yy, 2e-4,
             "corotated law must recover linear isotropic yy stress");
        near(entry(linear.first_piola_stress_pa, 2, 2), expected_zz, 2e-4,
             "corotated law must recover linear isotropic zz stress");
        near(entry(linear.first_piola_stress_pa, 0, 1), expected_xy, 2e-4,
             "corotated law must recover linear isotropic shear stress");

        auto reversed_reference = reference;
        std::swap(reversed_reference[1], reversed_reference[2]);
        rejects([&] { (void)evaluateCorotatedTet(law, reversed_reference, rigid); });
        auto collapsed_reference = reference;
        collapsed_reference[3] = collapsed_reference[0];
        rejects([&] { (void)evaluateCorotatedTet(law, collapsed_reference, rigid); });
        auto inverted_current = reference;
        std::swap(inverted_current[1], inverted_current[2]);
        rejects([&] { (void)evaluateCorotatedTet(law, reference, inverted_current); });
        auto singular_current = reference;
        singular_current[3] = singular_current[0];
        rejects([&] { (void)evaluateCorotatedTet(law, reference, singular_current); });
        auto nonfinite = reference;
        nonfinite[0].x = std::numeric_limits<double>::infinity();
        rejects([&] { (void)evaluateCorotatedTet(law, reference, nonfinite); });

        std::cout << "[PASS] corotated tet objectivity/gradient/linear-limit/conservation/bounds\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "[FAIL] " << error.what() << '\n';
        return 1;
    }
}
