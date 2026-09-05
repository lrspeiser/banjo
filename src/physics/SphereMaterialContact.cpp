#include "physics/SphereMaterialContact.hpp"
#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace banjo {
namespace {
double kinetic(const ActiveNodeState &node, const CoupledSphereState &sphere) {
    return 0.5 * node.mass_kg * lengthSquared(node.velocity_m_s) +
        0.5 * sphere.mass_kg * lengthSquared(sphere.motion.linear_velocity_m_s) +
        0.5 * sphere.inertia_kg_m2 * lengthSquared(sphere.motion.angular_velocity_rad_s);
}
}
SphereMaterialContactStats solveSphereMaterialContacts(
    ActiveMatter &matter, CoupledSphereState &sphere, double dt_s,
    const SphereMaterialContactSettings &settings, bool correct_positions) {
    if (!std::isfinite(dt_s) || dt_s <= 0.0 ||
        !std::isfinite(sphere.mass_kg) || sphere.mass_kg <= 0.0 ||
        !std::isfinite(sphere.inertia_kg_m2) || sphere.inertia_kg_m2 <= 0.0 ||
        !std::isfinite(sphere.radius_m) || sphere.radius_m <= 0.0 ||
        !std::isfinite(settings.node_contact_radius_m) || settings.node_contact_radius_m < 0.0 ||
        !std::isfinite(settings.static_friction) || settings.static_friction < 0.0 ||
        !std::isfinite(settings.dynamic_friction) || settings.dynamic_friction < 0.0 ||
        !std::isfinite(settings.restitution) || settings.restitution < 0.0 || settings.restitution > 1.0) {
        throw std::invalid_argument("invalid sphere-material contact state or coefficients");
    }
    SphereMaterialContactStats stats;
    const double inverse_sphere_mass = 1.0 / sphere.mass_kg;
    const double inverse_inertia = 1.0 / sphere.inertia_kg_m2;
    const double contact_radius = sphere.radius_m + settings.node_contact_radius_m;
    for (ActiveNodeState &node : matter.nodes) {
        if (node.mass_kg <= 0.0) continue;
        Vec3 r = node.position_world_m - sphere.motion.center_of_mass_world_m;
        const double distance = length(r);
        const Vec3 normal = normalized(r);
        const double gap = distance - contact_radius;
        const Vec3 relative = node.velocity_m_s - sphere.motion.linear_velocity_m_s -
            cross(sphere.motion.angular_velocity_rad_s, r);
        const double vn = dot(relative, normal);
        // Speculative normal constraint stops a point before it crosses the
        // surface. It never applies an attractive force to separating points.
        if (gap > std::max(settings.contact_margin_m, -vn * dt_s)) continue;
        stats.maximum_penetration_m = std::max(stats.maximum_penetration_m, -gap);
        const double inverse_node_mass = 1.0 / node.mass_kg;
        const auto effective_inverse_mass = [&](const Vec3 &direction) {
            return inverse_node_mass + inverse_sphere_mass +
                inverse_inertia * lengthSquared(cross(r, direction));
        };
        const double restitution = -vn > settings.restitution_speed_threshold_m_s
            ? settings.restitution : 0.0;
        const double desired_vn = gap > settings.contact_margin_m
            ? -gap / dt_s : -restitution * std::min(vn, 0.0);
        const double normal_impulse = std::max(0.0,
            (desired_vn - vn) / effective_inverse_mass(normal));
        if (normal_impulse > 0.0) {
            const double before = kinetic(node, sphere);
            const auto apply = [&](const Vec3 &impulse) {
                node.velocity_m_s += inverse_node_mass * impulse;
                sphere.motion.linear_velocity_m_s -= inverse_sphere_mass * impulse;
                const Vec3 torque_impulse = -cross(r, impulse);
                sphere.motion.angular_velocity_rad_s += inverse_inertia * torque_impulse;
                stats.impulse_to_material_n_s += impulse;
                stats.angular_impulse_to_sphere_kg_m2_s += torque_impulse;
            };
            apply(normal_impulse * normal);
            const Vec3 after_normal_relative = node.velocity_m_s -
                sphere.motion.linear_velocity_m_s - cross(sphere.motion.angular_velocity_rad_s, r);
            const Vec3 tangent = after_normal_relative - dot(after_normal_relative, normal) * normal;
            const double tangent_speed = length(tangent);
            if (tangent_speed > 1.0e-12) {
                const Vec3 direction = tangent / tangent_speed;
                const double sticking_impulse = tangent_speed / effective_inverse_mass(direction);
                const double friction_impulse = sticking_impulse <= settings.static_friction * normal_impulse
                    ? sticking_impulse
                    : std::min(sticking_impulse, settings.dynamic_friction * normal_impulse);
                apply(-friction_impulse * direction);
            }
            stats.dissipated_kinetic_energy_j += before - kinetic(node, sphere);
            ++stats.impulse_contacts;
        }
        // Split geometric correction: preserve COM and do NOT convert overlap
        // into kinetic energy. This is numerical stabilization, not a force law.
        if (correct_positions && gap < -settings.contact_margin_m) {
            const double correction = std::min(-gap - settings.contact_margin_m,
                0.2 * std::max(settings.node_contact_radius_m, sphere.radius_m * 0.01));
            const double sum_inverse_mass = inverse_node_mass + inverse_sphere_mass;
            const Vec3 node_shift = (correction * inverse_node_mass / sum_inverse_mass) * normal;
            const Vec3 sphere_shift = -(correction * inverse_sphere_mass / sum_inverse_mass) * normal;
            stats.position_correction_angular_momentum_delta_kg_m2_s +=
                cross(node_shift, node.mass_kg * node.velocity_m_s) +
                cross(sphere_shift, sphere.mass_kg * sphere.motion.linear_velocity_m_s);
            node.position_world_m += node_shift;
            sphere.motion.center_of_mass_world_m += sphere_shift;
            stats.maximum_position_correction_m = std::max(stats.maximum_position_correction_m, correction);
        }
    }
    return stats;
}
} // namespace banjo
