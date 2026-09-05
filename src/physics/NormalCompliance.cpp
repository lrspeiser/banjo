#include "physics/NormalCompliance.hpp"
#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace banjo {
NormalComplianceEvaluation evaluateNormalCompliance(double g0, double change, double dt,
                                                    const NormalComplianceLaw &law) {
    if (!std::isfinite(g0) || !std::isfinite(change) || !std::isfinite(dt) || dt<=0 ||
        !std::isfinite(law.stiffness_n_m) || law.stiffness_n_m<=0 ||
        !std::isfinite(law.compression_damping_kg_s) || law.compression_damping_kg_s<0)
        throw std::invalid_argument("invalid normal-compliance evaluation");
    const double g1 = g0 + change;
    const double s0 = std::min(g0, 0.0), s1 = std::min(g1, 0.0);
    NormalComplianceEvaluation result;
    result.energy_before_j = .5 * law.stiffness_n_m * s0 * s0;
    result.energy_after_j = .5 * law.stiffness_n_m * s1 * s1;
    double force = 0, derivative = 0;
    if (g0 <= 0 && g1 <= 0) {
        force = -.5 * law.stiffness_n_m * (2*g0 + change);
        derivative = -.5 * law.stiffness_n_m;
    } else if (g0 > 0 && g1 < 0) {
        force = -.5 * law.stiffness_n_m * g1*g1 / change;
        derivative = -.5 * law.stiffness_n_m * g1*(2*change-g1)/(change*change);
    } else if (g0 < 0 && g1 > 0) {
        force = .5 * law.stiffness_n_m * g0*g0 / change;
        derivative = -.5 * law.stiffness_n_m * g0*g0/(change*change);
    }
    // Integrate compression-only dashpot work on the linear gap path. Use the
    // stable increment directly when both states are compressed.
    const double compressed_change = g0 <= 0 && g1 <= 0 ? change : s1-s0;
    const double damping_impulse = -law.compression_damping_kg_s * std::min(compressed_change, 0.0);
    result.impulse_kg_m_s = dt*force + damping_impulse;
    result.impulse_gap_derivative_kg_s = dt*derivative;
    if (g1 <= 0 && compressed_change <= 0)
        result.impulse_gap_derivative_kg_s -= law.compression_damping_kg_s;
    result.damping_loss_j = -damping_impulse * change/dt;
    return result;
}

detail::ElasticContactEvaluation detail::evaluateElasticContact(const ElasticNormalContact &contact,
    const std::vector<Vec3> &initial, const std::vector<Vec3> &velocity, double dt) {
    ElasticContactEvaluation result;
    Vec3 sum_velocity = initial[contact.a] + velocity[contact.a];
    if (contact.b != fixed_contact_body) sum_velocity -= initial[contact.b] + velocity[contact.b];
    const Vec3 displacement = .5*dt*sum_velocity;
    Vec3 normal = contact.normal, unit1 = normal;
    double change = dot(normal, displacement), sum_r = 0;
    if (contact.sphere_radius_m > 0) {
        const Vec3 q1 = contact.relative0 + displacement;
        const double r0 = length(contact.relative0), r1 = length(q1);
        sum_r = r0+r1;
        if (!std::isfinite(sum_r) || r0 <= 1e-15 || r1 <= 1e-15) { result.valid = false; return result; }
        normal = (2*contact.relative0 + displacement)/sum_r;
        unit1 = q1/r1;
        change = dot(displacement, normal);
    }
    if (!std::isfinite(change)) { result.valid=false; return result; }
    const auto scalar = evaluateNormalCompliance(contact.gap0_m, change, dt, contact.law);
    result.impulse_on_a = scalar.impulse_kg_m_s*normal;
    result.energy_before_j = scalar.energy_before_j;
    result.energy_after_j = scalar.energy_after_j;
    result.damping_loss_j = scalar.damping_loss_j;
    result.compression_m = std::max({0.0, -contact.gap0_m, -contact.gap0_m-change});
    const double n[3]{normal.x,normal.y,normal.z}, u[3]{unit1.x,unit1.y,unit1.z};
    const double geometric = sum_r > 0 ? scalar.impulse_kg_m_s/sum_r : 0;
    for (unsigned i=0;i<3;++i) for (unsigned j=0;j<3;++j)
        result.velocity_tangent.m[i][j] = -.5*dt*((i==j ? geometric : 0) +
            (scalar.impulse_gap_derivative_kg_s-geometric)*n[i]*u[j]);
    result.valid = std::isfinite(scalar.impulse_kg_m_s) && std::isfinite(scalar.impulse_gap_derivative_kg_s) &&
        std::isfinite(scalar.energy_before_j) && std::isfinite(scalar.energy_after_j) && std::isfinite(scalar.damping_loss_j);
    return result;
}
}
