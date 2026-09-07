#include "physics/CohesiveFacet.hpp"

#include <algorithm>
#include <cmath>
#include <functional>
#include <iostream>
#include <limits>
#include <stdexcept>

using namespace banjo;

namespace {

void check(bool condition, const char *message) {
    if (!condition)
        throw std::runtime_error(message);
}

void near(double actual, double expected, double tolerance, const char *message) {
    check(std::isfinite(actual) && std::abs(actual - expected) <= tolerance, message);
}

void nearVector(Vec3 actual, Vec3 expected, double tolerance, const char *message) {
    near(length(actual - expected), 0.0, tolerance, message);
}

void rejects(const std::function<void()> &operation) {
    bool rejected = false;
    try {
        operation();
    } catch (const std::invalid_argument &) {
        rejected = true;
    }
    check(rejected, "expected invalid cohesive facet input to reject");
}

std::array<Vec3, 3> uniform(Vec3 value) {
    return {value, value, value};
}

double nodalWork(const CohesiveFacetEvaluation &evaluation, const std::array<Vec3, 3> &increment_a,
                 const std::array<Vec3, 3> &increment_b) {
    double work = 0;
    for (unsigned i = 0; i < 3; ++i) {
        work += dot(evaluation.work_forces_on_a_n[i], increment_a[i]);
        work += dot(evaluation.work_forces_on_b_n[i], increment_b[i]);
    }
    return work;
}

Vec3 rotateQuarterTurnAboutZ(Vec3 value) {
    return {-value.y, value.x, value.z};
}

} // namespace

int main() {
    try {
        const std::array<Vec3, 3> triangle{{{0, 0, 0}, {2, 0, 0}, {0, 1, 0}}};
        const double area = 1.0;
        const CohesiveFacetLaw law{
            .stiffness_pa_per_m = 5.0e14,
            .strength_pa = 5.0e7,
            .fracture_energy_j_m2 = 10.0,
            .compression_stiffness_pa_per_m = 3.0e14,
        };
        const double onset = law.strength_pa / law.stiffness_pa_per_m;
        const double failure = 2.0 * law.fracture_energy_j_m2 / law.strength_pa;
        const double energy_tolerance = law.fracture_energy_j_m2 * area * 2.0e-12;

        CohesiveFacetState state;
        double accumulated_work = 0;
        for (unsigned step = 1; step <= 101; ++step) {
            const double opening = 1.1 * failure * step / 101.0;
            const auto evaluation =
                advanceCohesiveFacet(law, triangle, uniform({}), uniform({0, 0, opening}), state);
            accumulated_work += evaluation.opening_work_j;
            state = evaluation.state;
            near(evaluation.balance_residual_j, 0.0, energy_tolerance,
                 "facet increment must close its independent work ledger");
        }
        const auto separated =
            advanceCohesiveFacet(law, triangle, uniform({}), uniform({0, 0, 1.1 * failure}), state);
        check(separated.separated_integration_points == 3,
              "uniform opening must separate all integration points");
        near(accumulated_work, law.fracture_energy_j_m2 * area, energy_tolerance,
             "complete facet opening work must equal Gc times physical area");
        near(separated.dissipated_energy_j, law.fracture_energy_j_m2 * area, energy_tolerance,
             "facet fracture dissipation must equal Gc times area");
        near(separated.stored_energy_j, 0.0, 0.0,
             "fully separated facet must retain no tensile energy");

        const auto damaged =
            advanceCohesiveFacet(law, triangle, uniform({}), uniform({0, 0, 0.6 * failure}));
        const auto unloaded =
            advanceCohesiveFacet(law, triangle, uniform({}), uniform({}), damaged.state);
        const auto reloaded = advanceCohesiveFacet(law, triangle, uniform({}),
                                                   uniform({0, 0, 0.6 * failure}), unloaded.state);
        near(reloaded.dissipated_increment_j, 0.0, energy_tolerance,
             "facet reload below its maximum must not dissipate twice");
        near(reloaded.dissipated_energy_j, damaged.dissipated_energy_j, energy_tolerance,
             "facet unload/reload must preserve irreversible history");
        near(unloaded.opening_work_j, -damaged.stored_energy_j, energy_tolerance,
             "facet unloading must return only stored energy");
        near(unloaded.opening_work_j + reloaded.opening_work_j, 0.0, energy_tolerance,
             "facet unload/reload work must cancel before new damage");

        const double compression = -0.25 * onset;
        const auto compressed = advanceCohesiveFacet(law, triangle, uniform({}),
                                                     uniform({0, 0, compression}), damaged.state);
        const auto compression_released =
            advanceCohesiveFacet(law, triangle, uniform({}), uniform({}), compressed.state);
        near(compressed.resultant_on_a_n.z, area * law.compression_stiffness_pa_per_m * compression,
             std::abs(area * law.compression_stiffness_pa_per_m * compression) * 1e-14,
             "compression resultant must use the reversible compression stiffness");
        near(compressed.dissipated_energy_j, damaged.dissipated_energy_j, energy_tolerance,
             "compression must not create or heal tensile damage");
        near(compression_released.opening_work_j, -compressed.stored_energy_j, energy_tolerance,
             "compression release must return its stored energy");

        const auto loaded =
            advanceCohesiveFacet(law, triangle, uniform({}), uniform({0, 0, 0.5 * onset}));
        Vec3 force_sum;
        Vec3 reference_moment;
        for (unsigned i = 0; i < 3; ++i) {
            force_sum += loaded.forces_on_a_n[i] + loaded.forces_on_b_n[i];
            reference_moment += cross(triangle[i], loaded.forces_on_a_n[i]);
            reference_moment += cross(triangle[i], loaded.forces_on_b_n[i]);
        }
        nearVector(force_sum, {}, 1e-12, "facet forces must be equal and opposite");
        nearVector(reference_moment, {}, 1e-12,
                   "facet forces must close moment about the reference origin");
        near(nodalWork(loaded, uniform({}), uniform({0, 0, 0.5 * onset})), -loaded.opening_work_j,
             energy_tolerance, "work-conjugate nodal forces must reproduce interface opening work");

        std::array<Vec3, 3> localized{};
        localized[0] = {0, 0, 2.0 * failure};
        const auto partial = advanceCohesiveFacet(law, triangle, uniform({}), localized);
        check(partial.separated_integration_points == 1,
              "nonuniform opening must permit localized quadrature-point propagation");
        check(partial.integration_points[0].damage == 1.0 &&
                  partial.integration_points[1].damage > 0.0 &&
                  partial.integration_points[1].damage < 1.0 &&
                  partial.integration_points[2].damage > 0.0 &&
                  partial.integration_points[2].damage < 1.0,
              "facet quadrature histories must advance independently");

        auto mixed_law = law;
        mixed_law.tangential_stiffness_pa_per_m = 0.25 * law.stiffness_pa_per_m;
        const double beta =
            std::sqrt(mixed_law.tangential_stiffness_pa_per_m / mixed_law.stiffness_pa_per_m);
        CohesiveFacetState shear_state;
        double shear_work = 0;
        for (unsigned step = 1; step <= 97; ++step) {
            const double slip = 1.1 * failure / beta * step / 97.0;
            const auto evaluation = advanceCohesiveFacet(mixed_law, triangle, uniform({}),
                                                         uniform({slip, 0, 0}), shear_state);
            shear_work += evaluation.opening_work_j;
            shear_state = evaluation.state;
        }
        const auto shear_separated = advanceCohesiveFacet(
            mixed_law, triangle, uniform({}), uniform({1.1 * failure / beta, 0, 0}), shear_state);
        check(shear_separated.separated_integration_points == 3,
              "declared tangential stiffness must transfer shear and permit separation");
        near(shear_work, mixed_law.fracture_energy_j_m2 * area, energy_tolerance,
             "pure shear effective opening must dissipate declared Gc times area");
        near(shear_separated.dissipated_energy_j, mixed_law.fracture_energy_j_m2 * area,
             energy_tolerance, "pure shear separation must charge fracture work once");

        for (bool shear : {false, true}) {
            CohesiveFacetState integration_state;
            double endpoint_work = 0;
            constexpr unsigned fine_steps = 20000;
            Vec3 previous_gap;
            for (unsigned step = 1; step <= fine_steps; ++step) {
                const double q = 1.05 * failure * step / fine_steps;
                const Vec3 gap = shear ? Vec3{q / beta, 0, 0} : Vec3{0, 0, q};
                const auto evaluation = advanceCohesiveFacet(mixed_law, triangle, uniform({}),
                                                             uniform(gap), integration_state);
                endpoint_work += dot(evaluation.resultant_on_a_n, gap - previous_gap);
                previous_gap = gap;
                integration_state = evaluation.state;
            }
            near(endpoint_work, mixed_law.fracture_energy_j_m2 * area,
                 mixed_law.fracture_energy_j_m2 * area * 2.0e-4,
                 shear ? "fine endpoint shear traction integration must approach Gc times area"
                       : "fine endpoint opening traction integration must approach Gc times area");
        }

        const auto shear_damaged = advanceCohesiveFacet(mixed_law, triangle, uniform({}),
                                                        uniform({0.6 * failure / beta, 0, 0}));
        const auto shear_unloaded = advanceCohesiveFacet(mixed_law, triangle, uniform({}),
                                                         uniform({}), shear_damaged.state);
        near(shear_unloaded.opening_work_j, -shear_damaged.stored_energy_j, energy_tolerance,
             "shear unloading must return only stored energy");
        near(shear_unloaded.dissipated_energy_j, shear_damaged.dissipated_energy_j,
             energy_tolerance, "shear unloading must not heal damage");

        const double constant_q = 0.55 * failure;
        const auto normal_path =
            advanceCohesiveFacet(mixed_law, triangle, uniform({}), uniform({0, 0, constant_q}));
        const auto rotated_path =
            advanceCohesiveFacet(mixed_law, triangle, uniform({}),
                                 uniform({constant_q / beta, 0, 0}), normal_path.state);
        near(rotated_path.dissipated_increment_j, 0.0, energy_tolerance,
             "rotating separation direction at fixed effective gap must not add damage");
        near(rotated_path.stored_energy_j, normal_path.stored_energy_j, energy_tolerance,
             "mixed-mode potential must be direction independent at fixed effective gap");
        near(rotated_path.opening_work_j, 0.0, energy_tolerance,
             "fixed-effective-gap direction rotation must do no cohesive work");
        near(nodalWork(rotated_path, uniform({}), uniform({constant_q / beta, 0, -constant_q})),
             -rotated_path.opening_work_j, energy_tolerance,
             "mixed-mode discrete force must close work on a nonproportional path");

        const Vec3 elastic_gap{0.12 * onset / beta, 0, 0.2 * onset};
        const auto elastic =
            advanceCohesiveFacet(mixed_law, triangle, uniform({}), uniform(elastic_gap));
        const double epsilon = onset * 1.0e-5;
        for (unsigned axis = 0; axis < 3; ++axis) {
            Vec3 direction;
            if (axis == 0)
                direction.x = 1;
            if (axis == 1)
                direction.y = 1;
            if (axis == 2)
                direction.z = 1;
            const auto plus = advanceCohesiveFacet(mixed_law, triangle, uniform({}),
                                                   uniform(elastic_gap + epsilon * direction));
            const auto minus = advanceCohesiveFacet(mixed_law, triangle, uniform({}),
                                                    uniform(elastic_gap - epsilon * direction));
            const double energy_gradient =
                (plus.stored_energy_j - minus.stored_energy_j) / (2 * epsilon);
            near(energy_gradient, dot(elastic.resultant_on_a_n, direction),
                 std::max(1e-6, std::abs(energy_gradient) * 2e-8),
                 "mixed-mode endpoint traction must be the undamaged potential gradient");
        }

        const Vec3 compressed_gap{0, 0, -0.2 * onset};
        const auto compression_endpoint =
            advanceCohesiveFacet(mixed_law, triangle, uniform({}), uniform(compressed_gap));
        const auto compression_plus = advanceCohesiveFacet(
            mixed_law, triangle, uniform({}), uniform(compressed_gap + Vec3{0, 0, epsilon}));
        const auto compression_minus = advanceCohesiveFacet(
            mixed_law, triangle, uniform({}), uniform(compressed_gap - Vec3{0, 0, epsilon}));
        const double compression_gradient =
            (compression_plus.stored_energy_j - compression_minus.stored_energy_j) / (2 * epsilon);
        near(compression_gradient, compression_endpoint.resultant_on_a_n.z,
             std::abs(compression_gradient) * 2e-8,
             "compression endpoint traction must be its reversible potential gradient");

        std::array<Vec3, 3> rotated_triangle;
        for (unsigned i = 0; i < 3; ++i)
            rotated_triangle[i] = rotateQuarterTurnAboutZ(triangle[i]);
        const Vec3 covariance_gap{0.1 * onset / beta, 0.07 * onset / beta, 0.15 * onset};
        const auto covariance =
            advanceCohesiveFacet(mixed_law, triangle, uniform({}), uniform(covariance_gap));
        const auto rotated_covariance =
            advanceCohesiveFacet(mixed_law, rotated_triangle, uniform({}),
                                 uniform(rotateQuarterTurnAboutZ(covariance_gap)));
        nearVector(rotated_covariance.resultant_on_a_n,
                   rotateQuarterTurnAboutZ(covariance.resultant_on_a_n), 1e-7,
                   "cohesive facet response must rotate with its reference frame");
        near(rotated_covariance.stored_energy_j, covariance.stored_energy_j, energy_tolerance,
             "cohesive facet energy must be frame invariant");

        const auto pure_compression =
            advanceCohesiveFacet(mixed_law, triangle, uniform({}), uniform({0, 0, -failure}));
        near(pure_compression.dissipated_energy_j, 0.0, 0.0,
             "pure compression must not initiate tensile or mixed-mode damage");
        check(pure_compression.separated_integration_points == 0,
              "pure compression must not separate an intact facet");

        auto bad_law = law;
        bad_law.fracture_energy_j_m2 = 0;
        rejects([&] { (void)advanceCohesiveFacet(bad_law, triangle, uniform({}), uniform({})); });
        bad_law = law;
        bad_law.tangential_stiffness_pa_per_m = -1;
        rejects([&] { (void)advanceCohesiveFacet(bad_law, triangle, uniform({}), uniform({})); });
        rejects([&] {
            const std::array<Vec3, 3> line{{{0, 0, 0}, {1, 0, 0}, {2, 0, 0}}};
            (void)advanceCohesiveFacet(law, line, uniform({}), uniform({}));
        });
        rejects([&] {
            auto invalid = uniform(Vec3{});
            invalid[1].x = std::numeric_limits<double>::quiet_NaN();
            (void)advanceCohesiveFacet(law, triangle, invalid, uniform({}));
        });
        rejects([&] {
            CohesiveFacetState invalid;
            invalid.integration_points[0] = {.opening_m = 1.0, .maximum_opening_m = 0.5};
            (void)advanceCohesiveFacet(law, triangle, uniform({}), uniform({}), invalid);
        });

        std::cout
            << "[PASS] cohesive facet work/history/compression/equilibrium/propagation/bounds\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "[FAIL] " << error.what() << '\n';
        return 1;
    }
}
