#include "physics/TetrahedronContactImpulse.hpp"

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

double component(Vec3 value, unsigned axis) {
    return axis == 0 ? value.x : axis == 1 ? value.y : value.z;
}

void setComponent(Vec3 &value, unsigned axis, double entry) {
    if (axis == 0) value.x = entry;
    else if (axis == 1) value.y = entry;
    else value.z = entry;
}

Vec3 freeProjection(Vec3 value, const std::array<bool, 3> &fixed) {
    for (unsigned axis = 0; axis < 3; ++axis)
        if (fixed[axis]) setComponent(value, axis, 0.);
    return value;
}

void validateOptions(const TetrahedronContactImpulseOptions &options) {
    require(std::isfinite(options.witness_tolerance_m) && options.witness_tolerance_m >= 0. &&
                options.witness_tolerance_m <= 1. &&
                std::isfinite(options.unit_normal_tolerance) &&
                options.unit_normal_tolerance > 0. && options.unit_normal_tolerance <= 1.e-3 &&
                std::isfinite(options.closing_speed_tolerance_m_s) &&
                options.closing_speed_tolerance_m_s >= 0. &&
                options.closing_speed_tolerance_m_s <= 1. &&
                std::isfinite(options.maximum_position_m) && options.maximum_position_m > 0. &&
                options.maximum_position_m <= 1.e9 && std::isfinite(options.maximum_speed_m_s) &&
                options.maximum_speed_m_s > 0. && options.maximum_speed_m_s <= 1.e9 &&
                std::isfinite(options.maximum_mass_kg) && options.maximum_mass_kg > 0. &&
                options.maximum_mass_kg <= 1.e18,
            "Invalid tetrahedron contact impulse options");
}

void validateSide(const TetrahedronContactSide &side,
                  const TetrahedronContactImpulseOptions &options) {
    double weight_sum = 0.;
    for (unsigned i = 0; i < 4; ++i) {
        require(finite(side.positions_m[i]) &&
                    length(side.positions_m[i]) <= options.maximum_position_m &&
                    finite(side.velocities_m_s[i]) &&
                    length(side.velocities_m_s[i]) <= options.maximum_speed_m_s &&
                    std::isfinite(side.lumped_masses_kg[i]) &&
                    side.lumped_masses_kg[i] > 0. &&
                    side.lumped_masses_kg[i] <= options.maximum_mass_kg &&
                    std::isfinite(side.barycentric[i]) && side.barycentric[i] >= 0. &&
                    side.barycentric[i] <= 1.,
                "Invalid tetrahedron contact side");
        weight_sum += side.barycentric[i];
        for (unsigned axis = 0; axis < 3; ++axis)
            require(!side.fixed_components[i][axis] ||
                        component(side.velocities_m_s[i], axis) == 0.,
                    "Fixed contact component has nonzero velocity");
    }
    require(std::isfinite(weight_sum) && std::abs(weight_sum - 1.) <= 1.e-12,
            "Contact barycentric weights must sum to one");
    const Vec3 e1 = side.positions_m[1] - side.positions_m[0];
    const Vec3 e2 = side.positions_m[2] - side.positions_m[0];
    const Vec3 e3 = side.positions_m[3] - side.positions_m[0];
    const double determinant = dot(e1, cross(e2, e3));
    const double scale = length(e1) * length(e2) * length(e3);
    require(std::isfinite(determinant) && determinant > std::max(1.e-24, scale * 1.e-12),
            "Contact tetrahedron must have positive nondegenerate volume");
}

Vec3 weighted(const std::array<Vec3, 4> &values, const std::array<double, 4> &weights) {
    Vec3 result;
    for (unsigned i = 0; i < 4; ++i) result += weights[i] * values[i];
    return result;
}

double kinetic(const TetrahedronContactSide &side, const std::array<Vec3, 4> &velocities) {
    double result = 0.;
    for (unsigned i = 0; i < 4; ++i)
        result += .5 * side.lumped_masses_kg[i] * dot(velocities[i], velocities[i]);
    return result;
}

} // namespace

TetrahedronContactImpulseResult evaluateTetrahedronContactImpulse(
    const TetrahedronContactSide &a, const TetrahedronContactSide &b, Vec3 normal,
    const TetrahedronContactImpulseOptions &options) {
    validateOptions(options);
    validateSide(a, options);
    validateSide(b, options);
    require(finite(normal), "Nonfinite tetrahedron contact normal");
    const double normal_length = length(normal);
    require(std::isfinite(normal_length) &&
                std::abs(normal_length - 1.) <= options.unit_normal_tolerance,
            "Tetrahedron contact normal is not unit length");
    normal = normal / normal_length;

    TetrahedronContactImpulseResult result;
    result.velocities_a_m_s = a.velocities_m_s;
    result.velocities_b_m_s = b.velocities_m_s;
    result.contact_point_a_m = weighted(a.positions_m, a.barycentric);
    result.contact_point_b_m = weighted(b.positions_m, b.barycentric);
    const Vec3 witness_delta = result.contact_point_b_m - result.contact_point_a_m;
    const Vec3 tangential_witness_delta = witness_delta - dot(witness_delta, normal) * normal;
    require(finite(result.contact_point_a_m) && finite(result.contact_point_b_m) &&
                finite(tangential_witness_delta) &&
                length(tangential_witness_delta) <= options.witness_tolerance_m,
            "Tetrahedron contact witness separation is not parallel to its normal");

    const Vec3 velocity_a = weighted(a.velocities_m_s, a.barycentric);
    const Vec3 velocity_b = weighted(b.velocities_m_s, b.barycentric);
    result.relative_normal_speed_before_m_s = dot(velocity_b - velocity_a, normal);
    require(std::isfinite(result.relative_normal_speed_before_m_s),
            "Nonfinite tetrahedron contact speed");
    if (result.relative_normal_speed_before_m_s >=
        -options.closing_speed_tolerance_m_s) {
        result.relative_normal_speed_after_m_s = result.relative_normal_speed_before_m_s;
        return result;
    }

    for (unsigned i = 0; i < 4; ++i) {
        const Vec3 free_a = freeProjection(normal, a.fixed_components[i]);
        const Vec3 free_b = freeProjection(normal, b.fixed_components[i]);
        result.inverse_effective_mass_kg_inv +=
            a.barycentric[i] * a.barycentric[i] * dot(free_a, free_a) /
                a.lumped_masses_kg[i] +
            b.barycentric[i] * b.barycentric[i] * dot(free_b, free_b) /
                b.lumped_masses_kg[i];
    }
    require(std::isfinite(result.inverse_effective_mass_kg_inv) &&
                result.inverse_effective_mass_kg_inv > 0.,
            "Closing contact has no free normal effective mass");
    result.normal_impulse_n_s =
        -result.relative_normal_speed_before_m_s / result.inverse_effective_mass_kg_inv;
    require(std::isfinite(result.normal_impulse_n_s) && result.normal_impulse_n_s >= 0.,
            "Invalid tetrahedron contact impulse");

    const double kinetic_before = kinetic(a, a.velocities_m_s) + kinetic(b, b.velocities_m_s);
    for (unsigned i = 0; i < 4; ++i) {
        const Vec3 impulse_a =
            freeProjection(-a.barycentric[i] * result.normal_impulse_n_s * normal,
                           a.fixed_components[i]);
        const Vec3 impulse_b =
            freeProjection(b.barycentric[i] * result.normal_impulse_n_s * normal,
                           b.fixed_components[i]);
        result.velocities_a_m_s[i] += impulse_a / a.lumped_masses_kg[i];
        result.velocities_b_m_s[i] += impulse_b / b.lumped_masses_kg[i];
        require(finite(result.velocities_a_m_s[i]) && finite(result.velocities_b_m_s[i]) &&
                    length(result.velocities_a_m_s[i]) <= options.maximum_speed_m_s &&
                    length(result.velocities_b_m_s[i]) <= options.maximum_speed_m_s,
                "Contact impulse candidate velocity exceeds bound");
        result.raw_linear_momentum_change_kg_m_s += impulse_a + impulse_b;
        result.raw_angular_momentum_change_kg_m2_s +=
            cross(a.positions_m[i], impulse_a) + cross(b.positions_m[i], impulse_b);
    }
    result.support_impulse_n_s = result.raw_linear_momentum_change_kg_m_s;
    result.support_current_moment_n_m_s = result.raw_angular_momentum_change_kg_m2_s;
    result.linear_momentum_residual_kg_m_s =
        result.raw_linear_momentum_change_kg_m_s - result.support_impulse_n_s;
    result.angular_momentum_residual_kg_m2_s =
        result.raw_angular_momentum_change_kg_m2_s - result.support_current_moment_n_m_s;
    const double kinetic_after =
        kinetic(a, result.velocities_a_m_s) + kinetic(b, result.velocities_b_m_s);
    result.kinetic_dissipation_j =
        .5 * result.relative_normal_speed_before_m_s *
        result.relative_normal_speed_before_m_s / result.inverse_effective_mass_kg_inv;
    require(std::isfinite(result.kinetic_dissipation_j),
            "Contact impulse produced invalid kinetic dissipation");
    result.work_residual_j = kinetic_after - kinetic_before + result.kinetic_dissipation_j;
    result.relative_normal_speed_after_m_s =
        dot(weighted(result.velocities_b_m_s, b.barycentric) -
                weighted(result.velocities_a_m_s, a.barycentric),
            normal);
    require(std::isfinite(result.relative_normal_speed_after_m_s) &&
                std::abs(result.relative_normal_speed_after_m_s) <=
                    1.e-10 * std::max(1., std::abs(result.relative_normal_speed_before_m_s)),
            "Contact impulse failed to stop normal closing speed");
    result.applied = true;
    return result;
}

} // namespace banjo
