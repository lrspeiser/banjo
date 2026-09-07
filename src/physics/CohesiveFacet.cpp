#include "physics/CohesiveFacet.hpp"

#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace banjo {
namespace {

constexpr std::array<std::array<double, 3>, 3> quadrature{{
    {{2.0 / 3.0, 1.0 / 6.0, 1.0 / 6.0}},
    {{1.0 / 6.0, 2.0 / 3.0, 1.0 / 6.0}},
    {{1.0 / 6.0, 1.0 / 6.0, 2.0 / 3.0}},
}};

void require(bool condition, const char *message) {
    if (!condition)
        throw std::invalid_argument(message);
}

bool finiteVector(Vec3 value) {
    return std::isfinite(value.x) && std::isfinite(value.y) && std::isfinite(value.z);
}

Vec3 interpolate(const std::array<Vec3, 3> &values, const std::array<double, 3> &weights) {
    return weights[0] * values[0] + weights[1] * values[1] + weights[2] * values[2];
}

void addDistributed(std::array<Vec3, 3> &side_a, std::array<Vec3, 3> &side_b,
                    const std::array<double, 3> &weights, Vec3 force_on_a) {
    for (unsigned node = 0; node < 3; ++node) {
        side_a[node] += weights[node] * force_on_a;
        side_b[node] -= weights[node] * force_on_a;
    }
}

} // namespace

CohesiveFacetEvaluation advanceCohesiveFacet(const CohesiveFacetLaw &law,
                                             const std::array<Vec3, 3> &reference_triangle,
                                             const std::array<Vec3, 3> &displacements_a,
                                             const std::array<Vec3, 3> &displacements_b,
                                             const CohesiveFacetState &prior) {
    for (Vec3 point : reference_triangle)
        require(finiteVector(point), "cohesive facet reference geometry must be finite");
    for (Vec3 value : displacements_a)
        require(finiteVector(value), "cohesive facet side-A displacement must be finite");
    for (Vec3 value : displacements_b)
        require(finiteVector(value), "cohesive facet side-B displacement must be finite");

    const Vec3 area_vector = cross(reference_triangle[1] - reference_triangle[0],
                                   reference_triangle[2] - reference_triangle[0]);
    const double twice_area = length(area_vector);
    require(std::isfinite(twice_area) && twice_area > 0,
            "cohesive facet reference triangle must have positive finite area");
    const double area = 0.5 * twice_area;
    require(std::isfinite(area) && area > 0, "cohesive facet area exceeds numeric range");
    const Vec3 normal = area_vector / twice_area;
    require(finiteVector(normal), "cohesive facet normal is not finite");

    const CohesiveInterfaceLaw point_law{
        law.stiffness_pa_per_m, law.strength_pa, law.fracture_energy_j_m2, area / 3.0, 0.0,
    };
    require(std::isfinite(law.tangential_stiffness_pa_per_m) &&
                law.tangential_stiffness_pa_per_m >= 0,
            "cohesive facet tangential stiffness must be finite and nonnegative");
    require(std::isfinite(law.compression_stiffness_pa_per_m) &&
                law.compression_stiffness_pa_per_m >= 0,
            "cohesive facet compression stiffness must be finite and nonnegative");
    const double tangential_ratio = law.tangential_stiffness_pa_per_m / law.stiffness_pa_per_m;
    require(std::isfinite(tangential_ratio),
            "cohesive facet stiffness ratio exceeds numeric range");

    CohesiveFacetEvaluation result;
    result.area_m2 = area;
    for (unsigned point = 0; point < 3; ++point) {
        const auto &shape = quadrature[point];
        const Vec3 relative =
            interpolate(displacements_b, shape) - interpolate(displacements_a, shape);
        const Vec3 previous_relative = prior.relative_displacement_m[point];
        require(finiteVector(previous_relative),
                "cohesive facet prior relative displacement must be finite");
        const double normal_gap = dot(relative, normal);
        const double previous_normal_gap = dot(previous_relative, normal);
        const Vec3 tangent_gap = relative - normal_gap * normal;
        const Vec3 previous_tangent_gap = previous_relative - previous_normal_gap * normal;
        const double opening_squared = std::max(0.0, normal_gap) * std::max(0.0, normal_gap) +
                                       tangential_ratio * lengthSquared(tangent_gap);
        const double previous_opening_squared =
            std::max(0.0, previous_normal_gap) * std::max(0.0, previous_normal_gap) +
            tangential_ratio * lengthSquared(previous_tangent_gap);
        const double opening = std::sqrt(opening_squared);
        const double previous_opening = std::sqrt(previous_opening_squared);
        require(std::isfinite(opening) && std::isfinite(previous_opening),
                "cohesive facet effective opening is not finite");
        const double history_tolerance =
            1e-12 * std::max({1.0, opening, previous_opening,
                              prior.integration_points[point].maximum_opening_m});
        require(std::abs(prior.integration_points[point].opening_m - previous_opening) <=
                    history_tolerance,
                "cohesive facet prior kinematics and history disagree");

        const auto increment =
            advanceCohesiveInterface(point_law, prior.integration_points[point], opening);
        result.state.integration_points[point] = increment.state;
        result.state.relative_displacement_m[point] = relative;
        result.integration_points[point] = increment.response;
        const double compression_energy = 0.5 * point_law.area_m2 *
                                          law.compression_stiffness_pa_per_m *
                                          std::min(0.0, normal_gap) * std::min(0.0, normal_gap);
        const double previous_compression_energy =
            0.5 * point_law.area_m2 * law.compression_stiffness_pa_per_m *
            std::min(0.0, previous_normal_gap) * std::min(0.0, previous_normal_gap);
        const double stored_energy = increment.response.stored_energy_j + compression_energy;
        const double previous_stored_energy =
            evaluateCohesiveInterface(point_law, prior.integration_points[point]).stored_energy_j +
            previous_compression_energy;
        result.stored_energy_j += stored_energy;
        result.dissipated_energy_j += increment.response.dissipated_energy_j;
        result.dissipated_increment_j += increment.dissipated_increment_j;
        const double interface_work =
            stored_energy - previous_stored_energy + increment.dissipated_increment_j;
        result.opening_work_j += interface_work;
        result.separated_integration_points += increment.response.separated ? 1U : 0U;

        Vec3 traction;
        if (opening > 0) {
            traction = (increment.response.traction_pa / opening) *
                       (std::max(0.0, normal_gap) * normal + tangential_ratio * tangent_gap);
        }
        if (normal_gap < 0)
            traction += law.compression_stiffness_pa_per_m * normal_gap * normal;
        require(finiteVector(traction), "cohesive facet traction exceeds numeric range");
        result.traction_pa[point] = traction;
        const Vec3 endpoint_force = point_law.area_m2 * traction;
        const Vec3 displacement_increment = relative - previous_relative;
        const double increment_squared = lengthSquared(displacement_increment);
        Vec3 work_force = endpoint_force;
        if (increment_squared > 0) {
            // Gonzalez discrete gradient: retain the endpoint traction in all
            // directions orthogonal to this increment and correct only the
            // increment direction so dot(Fbar,dg) equals Delta(Psi)+Delta(D).
            work_force += ((interface_work - dot(endpoint_force, displacement_increment)) /
                           increment_squared) *
                          displacement_increment;
        } else {
            require(interface_work == 0, "stationary cohesive facet increment changed its energy");
        }
        require(finiteVector(work_force),
                "cohesive facet discrete work force exceeds numeric range");
        result.balance_residual_j += dot(work_force, displacement_increment) - interface_work;
        addDistributed(result.forces_on_a_n, result.forces_on_b_n, shape, endpoint_force);
        addDistributed(result.work_forces_on_a_n, result.work_forces_on_b_n, shape, work_force);
    }

    for (unsigned node = 0; node < 3; ++node) {
        require(finiteVector(result.forces_on_a_n[node]) &&
                    finiteVector(result.forces_on_b_n[node]) &&
                    finiteVector(result.work_forces_on_a_n[node]) &&
                    finiteVector(result.work_forces_on_b_n[node]),
                "cohesive facet force exceeds numeric range");
        result.resultant_on_a_n += result.forces_on_a_n[node];
        result.reference_moment_on_a_n_m +=
            cross(reference_triangle[node], result.forces_on_a_n[node]);
    }
    require(
        finiteVector(result.resultant_on_a_n) && finiteVector(result.reference_moment_on_a_n_m) &&
            std::isfinite(result.stored_energy_j) && std::isfinite(result.dissipated_energy_j) &&
            std::isfinite(result.dissipated_increment_j) && std::isfinite(result.opening_work_j) &&
            std::isfinite(result.balance_residual_j),
        "cohesive facet result exceeds numeric range");
    return result;
}

} // namespace banjo
